"""
Deep-learning training utilities: class weights, sample uniqueness weights,
purged chronological split, and light scorecard integration for TFT + CNN-LSTM.

Scope note (why this module exists)
-----------------------------------
The Phase 1 infrastructure (event_intervals, purged_cpcv, model_scorecard,
deflated_sharpe) was wired into the XGBoost training pipeline only. TFT and
CNN-LSTM still train with plain `CrossEntropyLoss` on a chronological 80/20
split, which leaks labeled future bars into the training window and lets
majority-class collapse stall val_acc under 52%.

This helper is the minimum surface needed to close those gaps without
changing model checkpoints, inference paths, or default training runtime.

Everything here is pure-numpy + torch (torch imports lazy so pytest works
without the GPU wheels).

Design contract
---------------
- No gradient changes unless the caller opts in by passing the weights we produce.
- No behaviour change at inference — checkpoints never carry this info.
- Purged split degenerates to a plain chronological split when no overlap
  exists, so pipelines that don't emit valid intervals keep current behaviour.
- CPCV stability is an OPT-IN extra pass (env flag `TB_DL_CPCV_FOLDS`), so
  default training runtime is untouched.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from services.ai_modules.event_intervals import (
    average_uniqueness,
)

logger = logging.getLogger(__name__)


# ── Class weights ───────────────────────────────────────────────────────

def compute_balanced_class_weights(
    y: np.ndarray,
    num_classes: int = 3,
    clip_ratio: float = 5.0,
    scheme: str = "balanced",
) -> np.ndarray:
    """
    Per-class weights with two schemes:

    scheme="balanced" (default, sklearn-style inverse frequency):
        w[c] = N / (num_classes * count[c])

        Math pressure on a tiny minority class is large — for the Phase 13
        split 45% FLAT / 39% DOWN / 16% UP this boosts UP by ~2.8×, which
        was strong enough to completely STARVE the DOWN class (Spark
        retrain 2026-04-23 produced recall_up=0.597 but recall_down=0.000).

    scheme="balanced_sqrt" (dampened, used for 3-class triple-barrier where
    all classes are meaningful):
        w[c] = sqrt(N_max / count[c])

        Max boost drops from ~2.8× to ~1.7× on the same split, so the
        minority UP gets a real learning signal without fully cannibalising
        gradient pressure on DOWN. Chosen explicitly to avoid the pendulum
        swing the linear-inverse scheme produced on 2026-04-23.

    Both schemes are scaled so min(w) == 1 and clipped to `clip_ratio`.
    Missing classes get w = clip_ratio (max weight) so the model is told
    they're rare when some do appear mid-epoch.

    Returns a float32 numpy array shape (num_classes,).
    """
    y = np.asarray(y, dtype=np.int64)
    if len(y) == 0:
        return np.ones(num_classes, dtype=np.float32)

    counts = np.bincount(y, minlength=num_classes).astype(np.float64)
    weights = np.full(num_classes, clip_ratio, dtype=np.float64)
    mask = counts > 0

    if scheme == "balanced_sqrt":
        # sqrt(N_max / count[c]) — dampened inverse-frequency
        n_max = float(counts.max()) if mask.any() else 1.0
        weights[mask] = np.sqrt(n_max / counts[mask])
    elif scheme == "balanced":
        total = counts.sum()
        weights[mask] = total / (num_classes * counts[mask])
    else:
        raise ValueError(f"Unknown class-weight scheme: {scheme!r}")

    # Scale so min==1 so the absolute loss magnitude is comparable to the
    # unweighted case. Then clip the ratio of max/min.
    min_w = float(weights.min())
    if min_w > 0:
        weights = weights / min_w
    weights = np.clip(weights, 1.0, float(clip_ratio))
    return weights.astype(np.float32)


def compute_per_sample_class_weights(
    y: np.ndarray,
    num_classes: int = 3,
    clip_ratio: float = 5.0,
    scheme: str = "balanced",
) -> np.ndarray:
    """
    Per-sample weight vector for class-balancing with frameworks that consume
    `sample_weight` (XGBoost DMatrix, sklearn, lightgbm — anywhere class_weight
    isn't directly supported).

    `scheme` is passed through to `compute_balanced_class_weights`. The
    output is normalized so mean(w) == 1, which preserves the absolute loss
    scale.

    Returns float32 array of length len(y). Missing classes in y are silently
    ignored for the output (they have no samples to weight).
    """
    y = np.asarray(y, dtype=np.int64)
    if len(y) == 0:
        return np.array([], dtype=np.float32)
    class_w = compute_balanced_class_weights(
        y, num_classes=num_classes, clip_ratio=clip_ratio, scheme=scheme,
    )
    # Clamp indices into range — defensive against stray labels
    idx = np.clip(y, 0, num_classes - 1)
    per_sample = class_w[idx].astype(np.float32)
    m = float(per_sample.mean())
    if m > 0:
        per_sample = per_sample / m
    return per_sample.astype(np.float32)


def get_class_weight_scheme() -> str:
    """Resolve the active class-weight scheme from `TB_CLASS_WEIGHT_MODE`.

    Default is `balanced_sqrt` — the dampened inverse-frequency weighting
    that was introduced on 2026-04-24 after the pure `balanced` scheme
    caused the DOWN class to collapse on the 5-min generic predictor
    (recall_up=0.597 but recall_down=0.000 on Spark retrain v20260422_181416).

    Allowed values: "balanced", "balanced_sqrt". Unknown values fall back
    to `balanced_sqrt` with a warning so a typo can't silently regress the
    fix.
    """
    raw = os.environ.get("TB_CLASS_WEIGHT_MODE", "balanced_sqrt").strip().lower()
    if raw in ("balanced", "balanced_sqrt"):
        return raw
    logger.warning(
        "Unknown TB_CLASS_WEIGHT_MODE=%r; falling back to 'balanced_sqrt'.", raw
    )
    return "balanced_sqrt"


# ── Sample uniqueness weights ───────────────────────────────────────────

def compute_sample_weights_from_intervals(
    per_symbol_intervals: Sequence[np.ndarray],
    per_symbol_n_bars: Sequence[int],
) -> np.ndarray:
    """
    Compute López de Prado avg_uniqueness weights per-symbol, then concatenate.

    Events from different symbols have disjoint bar axes (symbol A's bar 500 is
    independent of symbol B's bar 500), so concurrency must be computed PER
    SYMBOL before concatenation. This prevents a spurious "overlap" reading
    between independent symbols.

    Args:
        per_symbol_intervals: list of (N_sym, 2) int64 arrays — entry/exit idx
        per_symbol_n_bars:    list of total bars per symbol (same order)

    Returns:
        float32 array of length sum(N_sym), normalized to mean == 1.
        Empty input returns an empty array (caller falls back to uniform).
    """
    if not per_symbol_intervals:
        return np.array([], dtype=np.float32)

    if len(per_symbol_intervals) != len(per_symbol_n_bars):
        raise ValueError("per_symbol_intervals and per_symbol_n_bars must align")

    chunks: List[np.ndarray] = []
    for intervals, n_bars in zip(per_symbol_intervals, per_symbol_n_bars):
        if len(intervals) == 0:
            continue
        u = average_uniqueness(intervals, n_bars)
        chunks.append(u.astype(np.float32))

    if not chunks:
        return np.array([], dtype=np.float32)

    w = np.concatenate(chunks)
    mean_w = float(w.mean()) if len(w) else 1.0
    if mean_w > 0:
        w = w / mean_w
    return w.astype(np.float32)


# ── Purged chronological split ──────────────────────────────────────────

def purged_chronological_split(
    intervals: Optional[np.ndarray],
    n_samples: int,
    split_frac: float = 0.8,
    embargo_bars: int = 0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Walk-forward chronological split with leakage-purging at the boundary.

    Take the first `split_frac` of samples as train, the remainder as val.
    Then drop train samples whose [entry, exit] extends into the val window
    plus an embargo buffer — those labels peek into val data.

    When `intervals` is None or empty, falls back to a plain chronological
    split. This preserves exact current behavior for any caller that skips
    interval tracking.

    Args:
        intervals:  (N, 2) int64 entry/exit indices aligned with sample order.
                    Coordinates only need to be monotonic PER-SYMBOL; the
                    purge compares train→test within-symbol scope where the
                    caller has concatenated one symbol at a time.
        n_samples:  total number of samples.
        split_frac: fraction in [0,1) for the train portion (default 0.8).
        embargo_bars: extra buffer of bars past the test boundary to purge.

    Returns:
        (train_idx, val_idx) — int64 numpy arrays.
    """
    if not 0.0 < split_frac < 1.0:
        raise ValueError("split_frac must be in (0, 1)")
    if n_samples <= 1:
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)

    split = int(n_samples * split_frac)
    split = max(1, min(split, n_samples - 1))
    train_idx = np.arange(split, dtype=np.int64)
    val_idx = np.arange(split, n_samples, dtype=np.int64)

    if intervals is None or len(intervals) != n_samples:
        return train_idx, val_idx

    intervals = np.asarray(intervals, dtype=np.int64)
    val_entry = intervals[val_idx, 0]
    if len(val_entry) == 0:
        return train_idx, val_idx
    val_min_entry = int(val_entry.min()) - int(embargo_bars)

    # Purge: keep train events whose exit bar is before val window (minus embargo).
    # Using a per-sample filter is O(N) and correct when intervals are on
    # consistent axes within the evaluated portion. For multi-symbol arrays,
    # symbols further than the embargo naturally pass.
    train_exits = intervals[train_idx, 1]
    keep_mask = train_exits < val_min_entry
    train_idx = train_idx[keep_mask]
    return train_idx, val_idx


# ── CPCV stability (optional post-training pass) ────────────────────────

def dl_cpcv_folds_from_env() -> int:
    """Read `TB_DL_CPCV_FOLDS` env var (default 0 — CPCV disabled)."""
    try:
        return max(0, int(os.environ.get("TB_DL_CPCV_FOLDS", "0") or 0))
    except ValueError:
        return 0


def run_cpcv_accuracy_stability(
    train_eval_fn,
    intervals: Optional[np.ndarray],
    n_samples: int,
    n_splits: int = 5,
    n_test_splits: int = 2,
    embargo_bars: int = 0,
) -> Dict[str, float]:
    """
    Run purged CPCV on top of a cheap train-and-evaluate function.

    `train_eval_fn(train_idx, val_idx)` must return a single scalar accuracy
    (or any comparable score). This is meant for a LIGHTWEIGHT re-train
    (fewer epochs, small model) because CPCV fires C(n_splits, n_test_splits)
    times.

    Returns:
        {mean, std, min, max, median, negative_pct, n}
        plus the raw scores under key "scores".
        All-zero + n=0 when skipped (e.g. too few samples).
    """
    if n_samples < n_splits * 20 or intervals is None or len(intervals) != n_samples:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0,
                "median": 0.0, "negative_pct": 0.0, "n": 0, "scores": []}

    # Local import to keep module import cheap
    from services.ai_modules.purged_cpcv import CombinatorialPurgedKFold, cpcv_stability

    splitter = CombinatorialPurgedKFold(
        event_intervals=intervals,
        n_splits=n_splits,
        n_test_splits=n_test_splits,
        embargo_bars=embargo_bars,
    )
    scores: List[float] = []
    for fold_i, (tr, te) in enumerate(splitter.split()):
        if len(tr) < 10 or len(te) < 5:
            continue
        try:
            s = float(train_eval_fn(tr, te))
            if np.isfinite(s):
                scores.append(s)
        except Exception as e:
            logger.warning(f"CPCV fold {fold_i} failed: {e}")

    stab = cpcv_stability(scores) if scores else {}
    return {
        "mean": float(stab.get("mean", 0.0)),
        "std": float(stab.get("std", 0.0)),
        "min": float(stab.get("min", 0.0)),
        "max": float(stab.get("max", 0.0)),
        "median": float(stab.get("median", 0.0)),
        "negative_pct": float(stab.get("negative_pct", 0.0)),
        "n": int(len(scores)),
        "scores": [float(s) for s in scores],
    }


# ── DL-appropriate scorecard ────────────────────────────────────────────

def build_dl_scorecard(
    model_name: str,
    version: str,
    num_samples: int,
    best_val_acc: float,
    majority_baseline: float,
    class_counts: Dict[str, int],
    cpcv_stability: Optional[Dict[str, float]] = None,
    bar_size: str = "",
    trade_side: str = "both",
    setup_type: str = "GENERAL",
) -> Dict[str, Any]:
    """
    Build a minimal scorecard dict for a DL classifier.

    DL classifiers at training time don't produce per-trade PnL, so the full
    PnL-based fields stay zero. We populate what IS available:

      - hit_rate              = best_val_acc
      - ai_vs_setup_edge_pp   = (val_acc - majority_baseline) * 100
      - num_trades            = training sample count
      - cpcv_sharpe_mean/std/negative_pct  (stability of val_acc across CPCV folds)

    Returns a dict (not ModelScorecard) to match the existing
    timeseries_models.scorecard persistence pattern used by XGBoost saves,
    so NIA + the validator UI can read it without schema shims.
    """
    edge_pp = (float(best_val_acc) - float(majority_baseline)) * 100.0
    cpcv = cpcv_stability or {}

    sc: Dict[str, Any] = {
        "model_name": model_name,
        "setup_type": setup_type,
        "bar_size": bar_size,
        "trade_side": trade_side,
        "version": version,

        # Classifier metrics
        "hit_rate": float(best_val_acc),
        "majority_baseline": float(majority_baseline),
        "ai_vs_setup_edge_pp": float(edge_pp),
        "num_trades": int(num_samples),

        # Class mix
        "class_counts": {str(k): int(v) for k, v in class_counts.items()},

        # CPCV stability
        "cpcv_sharpe_mean": float(cpcv.get("mean", 0.0)),
        "cpcv_sharpe_std":  float(cpcv.get("std", 0.0)),
        "cpcv_negative_pct": float(cpcv.get("negative_pct", 0.0)),
        "cpcv_n_folds":     int(cpcv.get("n", 0)),

        # PnL-based fields intentionally zero for DL classifiers
        "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "deflated_sharpe": 0.0,
        "total_return_pct": 0.0, "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,

        # Source tag so consumers know this was built without PnL backtest
        "scorecard_source": "dl_classifier_training",
    }
    # Light "grade" purely based on edge above majority, purely informative.
    if edge_pp >= 5.0:
        sc["composite_grade"] = "A"
    elif edge_pp >= 3.0:
        sc["composite_grade"] = "B"
    elif edge_pp >= 1.0:
        sc["composite_grade"] = "C"
    elif edge_pp >= 0.0:
        sc["composite_grade"] = "D"
    else:
        sc["composite_grade"] = "F"
    sc["composite_score"] = float(max(0.0, min(100.0, edge_pp * 10.0)))
    return sc
