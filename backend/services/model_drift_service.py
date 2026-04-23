"""
Model Drift Detection — PSI + KS on live prediction distributions.

Concept
-------
Even a well-trained model slowly loses its edge when live market regime
drifts away from the training distribution. We catch this early by
comparing RECENT prediction distributions against a longer HISTORICAL
baseline for the same model.

Signals
-------
* Population Stability Index (PSI): sum of bucket-weighted log-ratios
    PSI = Σ (rec% - base%) · ln(rec% / base%)
  Thresholds (industry standard):
    PSI < 0.10  → healthy     (no meaningful shift)
    0.10-0.25   → warning     (monitor; may need retrain)
    > 0.25      → critical    (retrain now)

* Kolmogorov-Smirnov (KS) statistic: max CDF gap between the two
  distributions. Complements PSI — KS is scale-invariant and catches
  tail shifts PSI can miss when bucket counts are sparse.

Inputs
------
Pulls prediction rows from `confidence_gate_log` (the existing
decision-time logging collection) for each model. Each row carries:
  {model_version, prob_up, prob_down, created_at, ...}

We need at least `MIN_SAMPLES` predictions in each window — otherwise
drift cannot be measured reliably and we return `status="insufficient_data"`.

Integration
-----------
* `check_drift_for_model(db, model_version)` — single model
* `check_drift_all_models(db)` — scan all models seen in the log
* `/api/sentcom/drift` router endpoint exposes the latest snapshot.
* Snapshots are persisted to `model_drift_log` for V5 dashboard history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

COLLECTION_LOG = "model_drift_log"
SOURCE_COLLECTION = "confidence_gate_log"

MIN_SAMPLES = 50
BUCKETS = 10

PSI_WARNING = 0.10
PSI_CRITICAL = 0.25
KS_WARNING = 0.12
KS_CRITICAL = 0.20


# ── pure math ────────────────────────────────────────────────────────────

def psi(baseline: np.ndarray, recent: np.ndarray, n_buckets: int = BUCKETS) -> float:
    """Population Stability Index between two 1-D samples.

    Both arrays are bucketed into the same [0, 1] quantile bins derived
    from the baseline. Returns the scalar PSI.
    """
    baseline = np.asarray(baseline, dtype=np.float64).ravel()
    recent = np.asarray(recent, dtype=np.float64).ravel()
    if baseline.size == 0 or recent.size == 0:
        return 0.0

    lo = float(min(baseline.min(), recent.min()))
    hi = float(max(baseline.max(), recent.max()))
    if hi - lo < 1e-9:
        return 0.0
    edges = np.linspace(lo, hi, n_buckets + 1)

    base_counts, _ = np.histogram(baseline, bins=edges)
    rec_counts, _ = np.histogram(recent, bins=edges)

    # Laplace-smooth to avoid zero buckets (per common PSI implementation)
    eps = 1e-6
    base_pct = (base_counts + eps) / (base_counts.sum() + eps * n_buckets)
    rec_pct = (rec_counts + eps) / (rec_counts.sum() + eps * n_buckets)

    return float(np.sum((rec_pct - base_pct) * np.log(rec_pct / base_pct)))


def ks_stat(baseline: np.ndarray, recent: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov statistic (no p-value).

    Self-contained — no scipy dep. Uses the fast empirical-CDF
    formulation.
    """
    a = np.sort(np.asarray(baseline, dtype=np.float64).ravel())
    b = np.sort(np.asarray(recent, dtype=np.float64).ravel())
    if a.size == 0 or b.size == 0:
        return 0.0
    # Pooled sort
    pooled = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, pooled, side="right") / a.size
    cdf_b = np.searchsorted(b, pooled, side="right") / b.size
    return float(np.max(np.abs(cdf_a - cdf_b)))


def classify_drift(psi_val: float, ks_val: float) -> str:
    """Combine PSI + KS into a human label."""
    if psi_val >= PSI_CRITICAL or ks_val >= KS_CRITICAL:
        return "critical"
    if psi_val >= PSI_WARNING or ks_val >= KS_WARNING:
        return "warning"
    return "healthy"


# ── DB-backed check ──────────────────────────────────────────────────────

def _fetch_probs(
    db,
    *,
    model_version: Optional[str],
    start_iso: str,
    end_iso: Optional[str] = None,
    field: str = "prob_up",
    limit: int = 5000,
) -> np.ndarray:
    """Pull a 1-D probability array from the confidence gate log."""
    if db is None:
        return np.array([])
    q: Dict[str, Any] = {field: {"$exists": True, "$ne": None}}
    if model_version:
        q["model_version"] = model_version
    created_clause: Dict[str, Any] = {"$gte": start_iso}
    if end_iso:
        created_clause["$lt"] = end_iso
    q["created_at"] = created_clause
    try:
        cursor = db[SOURCE_COLLECTION].find(q, {"_id": 0, field: 1}).limit(limit)
        vals = [float(d[field]) for d in cursor if isinstance(d.get(field), (int, float))]
        return np.asarray(vals, dtype=np.float64)
    except Exception as e:
        logger.debug(f"[Drift] fetch failed: {e}")
        return np.array([])


def check_drift_for_model(
    db,
    model_version: str,
    *,
    recent_hours: int = 24,
    baseline_days: int = 30,
    field: str = "prob_up",
) -> Dict[str, Any]:
    """Compute drift for a single model across two time windows.

    The recent window is the last `recent_hours` hours. The baseline is
    the preceding `baseline_days` (ending at the start of the recent
    window so they don't overlap).
    """
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(hours=recent_hours)
    baseline_start = recent_start - timedelta(days=baseline_days)

    recent = _fetch_probs(
        db, model_version=model_version,
        start_iso=recent_start.isoformat(), field=field,
    )
    baseline = _fetch_probs(
        db, model_version=model_version,
        start_iso=baseline_start.isoformat(), end_iso=recent_start.isoformat(),
        field=field,
    )

    result: Dict[str, Any] = {
        "model_version": model_version,
        "field": field,
        "recent_n": int(recent.size),
        "baseline_n": int(baseline.size),
        "checked_at": now.isoformat(),
    }

    if recent.size < MIN_SAMPLES or baseline.size < MIN_SAMPLES:
        result["status"] = "insufficient_data"
        result["psi"] = 0.0
        result["ks"] = 0.0
        result["message"] = (
            f"Need ≥{MIN_SAMPLES} samples per window (recent={recent.size}, "
            f"baseline={baseline.size})"
        )
        return result

    psi_val = psi(baseline, recent)
    ks_val = ks_stat(baseline, recent)
    status = classify_drift(psi_val, ks_val)

    result["psi"] = round(psi_val, 4)
    result["ks"] = round(ks_val, 4)
    result["status"] = status

    # Summary stats for context
    result["recent_mean"] = round(float(recent.mean()), 4)
    result["baseline_mean"] = round(float(baseline.mean()), 4)
    result["mean_shift"] = round(float(recent.mean() - baseline.mean()), 4)

    if status == "critical":
        result["recommendation"] = "Retrain this model — live regime has meaningfully diverged from training distribution."
    elif status == "warning":
        result["recommendation"] = "Monitor; schedule a retrain within the next sprint."
    else:
        result["recommendation"] = "No action needed."

    # Best-effort log write
    try:
        db[COLLECTION_LOG].insert_one(dict(result))
        result.pop("_id", None)
    except Exception:
        pass

    return result


def check_drift_all_models(
    db,
    *,
    recent_hours: int = 24,
    baseline_days: int = 30,
) -> List[Dict[str, Any]]:
    """Run drift check for every distinct model_version seen in the
    source collection within the baseline window."""
    if db is None:
        return []
    baseline_start = (
        datetime.now(timezone.utc) - timedelta(days=baseline_days + 1)
    ).isoformat()
    try:
        versions = db[SOURCE_COLLECTION].distinct(
            "model_version",
            {"created_at": {"$gte": baseline_start}},
        )
    except Exception as e:
        logger.debug(f"[Drift] distinct failed: {e}")
        return []

    out: List[Dict[str, Any]] = []
    for v in versions:
        if not v:
            continue
        out.append(check_drift_for_model(
            db, model_version=v,
            recent_hours=recent_hours, baseline_days=baseline_days,
        ))
    return out
