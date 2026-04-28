"""
multiplier_threshold_optimizer_v2.py — DESIGN SKETCH (not yet wired)

================================================================
STATUS: Scaffolded 2026-04-28e for future activation.
        Not imported by any router or scheduler yet.
        Activate by:
          1. Replacing `from .multiplier_threshold_optimizer import run_optimization`
             with `from .multiplier_threshold_optimizer_v2 import run_optimization_v2`
             in `eod_generation_service.py` and `routers/trading_bot.py`.
          2. Bumping cohort-size requirements (`_MIN_COHORT_N_V2`) — v2
             needs MORE data than v1 because we hold out 20% for validation.
          3. Running the v2 endpoint with `dry_run=true` for a few weeks
             alongside v1 to compare proposal stability.
================================================================

WHY V2: the v1 optimizer (rule-based stepping on last-30d cohort lift)
can chase a lucky 30-day window. If a cohort's lift was +0.40R purely
because of a momentum regime in the last 2 weeks, v1 will happily
loosen the threshold to fire MORE often — only to discover next month
that lift was regime-driven, not threshold-driven.

V2's fix: **train/validate split**. We split the trade window into a
training slice (oldest 80%) and a held-out validation slice (most-
recent 20%). The optimizer proposes a threshold change based on
training-slice lift, then verifies the proposed direction is ALSO
positive on the held-out slice before persisting. Proposals that
disagree across slices are tagged `holdout_disagrees` and shelved.

This is the canonical defense against threshold over-fitting in a
rolling-window optimizer; same idea quants use to validate ML feature
selections against a held-out test fold.

================================================================
ALGORITHM
================================================================

1. Load all closed `bot_trades` over `days_back` days (default 60d —
   double the v1 window because we're splitting).

2. Sort chronologically by `created_at`.

3. Split: `train` = first 80% of trades, `holdout` = last 20%.

4. For each layer (stop_guard, target_snap, vp_path):
     a. Compute `train_lift` and `holdout_lift` separately
        (mean_R fired - mean_R not_fired in each slice).
     b. If either slice has < `_MIN_COHORT_N_V2` trades in either
        cohort → skip layer (insufficient data).
     c. Propose a step using `train_lift` (same rule as v1).
     d. Validate: does `sign(holdout_lift) == sign(train_lift)` AND
        `|holdout_lift|` > some smaller floor (e.g. 0.10R)?
        - YES → propose the change, tag `holdout_validated`.
        - NO  → leave threshold alone, tag `holdout_disagrees` in notes.

5. Apply only the validated proposals. Persist the full payload
   (including the holdout numbers) to `multiplier_threshold_history_v2`
   so v1 history is preserved for direct A/B comparison.

================================================================
PROS vs V1
================================================================
+ Robust to short-term regime noise — won't over-fit to 2-week regimes
+ Audit trail explicitly records "we wanted to change X but holdout
  didn't agree" — gives the operator confidence in the conservatism
+ Higher confidence per applied change → can later RAISE the per-night
  step cap (`_MAX_STEP_PCT`) safely

CONS / OPEN QUESTIONS
- Need ~2x more cohort data for the same statistical power. The
  `_MIN_COHORT_N_V2` will need to be ~25-30 (vs 15 in v1).
- 80/20 ratio is arbitrary; could expose as a parameter, but defaults
  matter most.
- We should consider time-decayed weighting on the training slice
  (recent trades count more than 60-day-old ones). NOT included in
  this sketch — keep it for v3.

================================================================
INTERFACE
================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services import smart_levels_service as sls
from services.multiplier_threshold_optimizer import (
    _LAYER_TO_THRESHOLD,
    _propose_step,
    _current_threshold,
)

logger = logging.getLogger(__name__)


# ─── Tuning knobs ──────────────────────────────────────────────────────

# Default lookback. Doubled vs v1 because we split 80/20.
_DEFAULT_LOOKBACK_DAYS_V2 = 60

# Train/validation split ratio (training slice = oldest fraction).
_TRAIN_RATIO = 0.80

# Min cohort size in BOTH slices (train AND holdout) before we'll
# touch a threshold. Higher than v1's 15 because we're splitting.
_MIN_COHORT_N_V2 = 25

# Holdout-validation floor: holdout lift sign must agree with train,
# AND |holdout_lift| must exceed this to count as "directionally
# validated" (not just statistical noise on the held-out slice).
_HOLDOUT_LIFT_FLOOR_R = 0.10


# ─── Helpers ────────────────────────────────────────────────────────────

def _split_trades_chronologically(
    trades: List[Dict[str, Any]], train_ratio: float = _TRAIN_RATIO,
) -> Dict[str, List[Dict[str, Any]]]:
    """Sort by `created_at` ascending, return `{train: [...], holdout: [...]}`.
    Assumes each trade has a parseable `created_at` ISO string. Trades
    missing the field land at the front of the list (treated as oldest).
    """
    def _ts(t):
        s = t.get("created_at")
        if not s:
            return ""
        return str(s)
    sorted_trades = sorted(trades, key=_ts)
    n = len(sorted_trades)
    cutoff = int(n * train_ratio)
    return {
        "train":   sorted_trades[:cutoff],
        "holdout": sorted_trades[cutoff:],
    }


def _compute_layer_lift(trades: List[Dict[str, Any]], layer: str) -> Dict[str, Any]:
    """For a single layer + slice, compute fired/not_fired cohort sizes
    and mean R-multiples. Returns a dict — None values when cohort empty.

    NOTE: This duplicates a small piece of the v1 logic intentionally so
    we can split cleanly. If v2 ships, refactor into a shared helper in
    `multiplier_analytics_service.py`.
    """
    fired_rs:   List[float] = []
    notfired_rs: List[float] = []
    for t in trades:
        ec = (t.get("entry_context") or {}).get("multipliers") or {}
        r = t.get("realized_r_multiple") or t.get("r_multiple")
        if r is None:
            continue
        try:
            r_f = float(r)
        except (TypeError, ValueError):
            continue
        if r_f != r_f:    # NaN
            continue
        fired = False
        if layer == "stop_guard":
            fired = bool((ec.get("stop_guard") or {}).get("snapped"))
        elif layer == "target_snap":
            snaps = ec.get("target_snap") or []
            fired = any(bool(s.get("snapped")) for s in snaps if isinstance(s, dict))
        elif layer == "vp_path":
            vp = ec.get("vp_path")
            try:
                fired = (vp is not None) and (float(vp) < 1.0)
            except (TypeError, ValueError):
                fired = False
        (fired_rs if fired else notfired_rs).append(r_f)
    return {
        "n_fired":      len(fired_rs),
        "n_not_fired":  len(notfired_rs),
        "mean_r_fired": sum(fired_rs) / len(fired_rs) if fired_rs else None,
        "mean_r_not":   sum(notfired_rs) / len(notfired_rs) if notfired_rs else None,
        "lift":
            (sum(fired_rs) / len(fired_rs)) - (sum(notfired_rs) / len(notfired_rs))
            if fired_rs and notfired_rs else None,
    }


def _holdout_agrees(train_lift: Optional[float], holdout_lift: Optional[float]) -> bool:
    """True iff the holdout slice's lift sign agrees with training AND
    its magnitude is above the noise floor."""
    if train_lift is None or holdout_lift is None:
        return False
    if abs(holdout_lift) < _HOLDOUT_LIFT_FLOOR_R:
        return False
    return (train_lift > 0) == (holdout_lift > 0)


# ─── Public API ────────────────────────────────────────────────────────

def run_optimization_v2(
    db,
    days_back: int = _DEFAULT_LOOKBACK_DAYS_V2,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """v2 of the threshold optimizer with held-out validation. NOT yet
    wired into the scheduler — activate by swapping the import in
    `eod_generation_service.py` and the admin router.

    Returns a payload structurally compatible with v1 plus per-layer
    `train` and `holdout` sub-objects so the operator can audit *why*
    a proposal was applied / shelved.
    """
    if db is None:
        return {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "version": "v2_holdout_validated",
            "error": "db not available",
            "applied": False,
            "dry_run": dry_run,
        }

    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days_back))).isoformat()
    try:
        trades = list(db["bot_trades"].find(
            {"status": "closed", "created_at": {"$gte": cutoff}},
            {"_id": 0, "id": 1, "created_at": 1, "entry_context": 1,
             "realized_r_multiple": 1, "r_multiple": 1},
        ))
    except Exception as e:
        return {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "version": "v2_holdout_validated",
            "error": f"trade fetch failed: {e}",
            "applied": False,
            "dry_run": dry_run,
        }

    splits = _split_trades_chronologically(trades)
    notes: List[str] = []
    proposals: Dict[str, Dict[str, Any]] = {}
    thresholds_before: Dict[str, float] = {}
    thresholds_after:  Dict[str, float] = {}

    for layer, threshold_name in _LAYER_TO_THRESHOLD.items():
        train_stats   = _compute_layer_lift(splits["train"],   layer)
        holdout_stats = _compute_layer_lift(splits["holdout"], layer)
        current = _current_threshold(threshold_name)
        thresholds_before[threshold_name] = current

        # Min-N gate (v2 — both slices)
        if (train_stats["n_fired"]   < _MIN_COHORT_N_V2 or
            train_stats["n_not_fired"] < _MIN_COHORT_N_V2 or
            holdout_stats["n_fired"]   < _MIN_COHORT_N_V2 // 4 or
            holdout_stats["n_not_fired"] < _MIN_COHORT_N_V2 // 4):
            thresholds_after[threshold_name] = current
            proposals[threshold_name] = {
                "current": current, "proposed": current, "step_pct": 0.0,
                "reason": "insufficient_data_v2",
                "train": train_stats, "holdout": holdout_stats,
            }
            notes.append(
                f"{threshold_name}: insufficient_data_v2 "
                f"(train {train_stats['n_fired']}/{train_stats['n_not_fired']}, "
                f"holdout {holdout_stats['n_fired']}/{holdout_stats['n_not_fired']})"
            )
            continue

        prop = _propose_step(threshold_name, train_stats["lift"], current)

        if prop["new"] == current:
            # No change proposed at all — pass through with neutral reason
            thresholds_after[threshold_name] = current
            proposals[threshold_name] = {
                "current": current, "proposed": current,
                "step_pct": 0.0,
                "reason": prop["reason"],
                "train": train_stats, "holdout": holdout_stats,
                "holdout_validated": None,
            }
            continue

        # Validate against holdout
        agrees = _holdout_agrees(train_stats["lift"], holdout_stats["lift"])
        if not agrees:
            thresholds_after[threshold_name] = current
            proposals[threshold_name] = {
                "current": current, "proposed": current,
                "step_pct": 0.0,
                "reason": "holdout_disagrees",
                "train_proposed": prop["new"],
                "train": train_stats, "holdout": holdout_stats,
                "holdout_validated": False,
            }
            notes.append(
                f"{threshold_name}: holdout_disagrees "
                f"(train_lift={train_stats['lift']}, holdout_lift={holdout_stats['lift']}); "
                f"shelving proposal {current:.4f} → {prop['new']:.4f}"
            )
            continue

        thresholds_after[threshold_name] = prop["new"]
        proposals[threshold_name] = {
            "current": current, "proposed": prop["new"],
            "step_pct": prop["step_pct"],
            "reason": prop["reason"],
            "train": train_stats, "holdout": holdout_stats,
            "holdout_validated": True,
        }
        notes.append(
            f"{threshold_name}: {current:.4f} → {prop['new']:.4f} "
            f"(train_lift={train_stats['lift']:.3f}, holdout_lift={holdout_stats['lift']:.3f}) ✓ validated"
        )

    payload = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "version": "v2_holdout_validated",
        "window_days": days_back,
        "n_train": len(splits["train"]),
        "n_holdout": len(splits["holdout"]),
        "proposals": proposals,
        "thresholds_before": thresholds_before,
        "thresholds_after":  thresholds_after,
        "applied": False,
        "dry_run": dry_run,
        "notes": notes,
    }

    if dry_run:
        return payload

    any_change = any(
        thresholds_before[k] != thresholds_after[k] for k in thresholds_before
    )
    if not any_change:
        notes.append("no thresholds changed; nothing persisted")
        return payload

    try:
        # Note: writes to v2-namespaced collection so v1 + v2 history
        # can be A/B-compared if both are ever active simultaneously.
        db["multiplier_threshold_history_v2"].insert_one({**payload, "applied": True})
        payload["applied"] = True
        sls.invalidate_threshold_cache()
        logger.info(f"multiplier_threshold_optimizer_v2 applied: {notes}")
    except Exception as e:
        logger.error(f"failed to persist v2 threshold optimizer result: {e}")
        notes.append(f"persist failed: {e}")

    return payload
