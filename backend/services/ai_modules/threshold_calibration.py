"""
Per-model threshold calibration for 3-class directional classifiers.

Problem
-------
With the triple-barrier 3-class scheme (DOWN / FLAT / UP), probability
mass is split across three classes, so the max per-class probability
rarely exceeds 0.55 — even when the model has a clear directional edge.
A global 0.55 confidence gate (legacy from the 2-class era) filters out
virtually every prediction.

Fix
---
Each model calibrates its own UP/DOWN thresholds from its training-set
prediction distribution:

    threshold_up   = clip(percentile(p_up,   pct), floor, ceiling)
    threshold_down = clip(percentile(p_down, pct), floor, ceiling)

with conservative defaults:
    pct     = 80   (top 20% of predictions by confidence)
    floor   = 0.45  (never below — prevents noise trading)
    ceiling = 0.60  (never above — prevents starvation)

Idea: a model whose p95 UP probability is 0.424 should gate LONGs at
~0.42, not 0.55. A model whose p95 UP is 0.70 should gate at ~0.60.

Consumers
---------
- `ModelMetrics` now carries `calibrated_up_threshold` /
  `calibrated_down_threshold` fields (default 0.50).
- `confidence_gate.py` reads these at inference time and uses the
  model-specific threshold for CONFIRMS scoring.

The calibration is computed INSIDE the training loop (both
`train_full_universe` and `train_from_features`) using the validation-
set prediction probabilities. Both paths call
`calibrate_thresholds_from_probs()`.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


# ── conservative defaults ────────────────────────────────────────────────

DEFAULT_PERCENTILE = 80.0       # take top 20% of predictions by confidence
DEFAULT_FLOOR = 0.45            # never gate below this — prevents noise trading
DEFAULT_CEILING = 0.60          # never gate above this — prevents starvation
NEUTRAL_THRESHOLD = 0.50        # used when no calibration data is available


def calibrate_threshold(
    probs: np.ndarray,
    *,
    percentile: float = DEFAULT_PERCENTILE,
    floor: float = DEFAULT_FLOOR,
    ceiling: float = DEFAULT_CEILING,
) -> float:
    """Return a calibrated threshold from a vector of class probabilities.

    Args:
        probs: 1D array of per-sample probabilities for a single class
               (e.g. y_pred_proba[:, 2] for UP).
        percentile: percentile at which to set the threshold. 80 → top-20%.
        floor / ceiling: bound the output.

    Returns:
        A float in [floor, ceiling]. NEUTRAL_THRESHOLD if the input is
        empty or all-NaN.
    """
    if probs is None:
        return NEUTRAL_THRESHOLD
    arr = np.asarray(probs, dtype=np.float64).ravel()
    if arr.size == 0:
        return NEUTRAL_THRESHOLD
    # Drop NaN/inf defensively
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return NEUTRAL_THRESHOLD
    thr = float(np.percentile(arr, percentile))
    return float(np.clip(thr, floor, ceiling))


def calibrate_thresholds_from_probs(
    y_pred_proba: np.ndarray,
    *,
    num_classes: int = 3,
    percentile: float = DEFAULT_PERCENTILE,
    floor: float = DEFAULT_FLOOR,
    ceiling: float = DEFAULT_CEILING,
) -> Tuple[float, float]:
    """Compute (up_threshold, down_threshold) from a validation-set
    `y_pred_proba` matrix.

    Args:
        y_pred_proba: (N, C) for multiclass, or (N,) for binary.
                      For multiclass with num_classes=3, columns are
                      [P(DOWN), P(FLAT), P(UP)].
        num_classes:  2 or 3.

    Returns:
        (up_threshold, down_threshold). Defaults to neutral (0.50, 0.50)
        on any unexpected input shape — never raises.
    """
    if y_pred_proba is None:
        return NEUTRAL_THRESHOLD, NEUTRAL_THRESHOLD
    arr = np.asarray(y_pred_proba)
    if arr.size == 0:
        return NEUTRAL_THRESHOLD, NEUTRAL_THRESHOLD

    if num_classes >= 3 and arr.ndim == 2 and arr.shape[1] >= 3:
        up = arr[:, 2]
        down = arr[:, 0]
    elif arr.ndim == 1 or (arr.ndim == 2 and arr.shape[1] == 1):
        # Binary: P(UP) scalar; P(DOWN) = 1 - P(UP)
        up = arr.ravel()
        down = 1.0 - up
    else:
        return NEUTRAL_THRESHOLD, NEUTRAL_THRESHOLD

    up_thr = calibrate_threshold(up, percentile=percentile, floor=floor, ceiling=ceiling)
    down_thr = calibrate_threshold(down, percentile=percentile, floor=floor, ceiling=ceiling)
    return up_thr, down_thr


def get_effective_threshold(
    metrics: Optional[dict],
    direction: str,
    *,
    floor: float = DEFAULT_FLOOR,
    ceiling: float = DEFAULT_CEILING,
) -> float:
    """Read the calibrated threshold from a model's metrics dict.

    Gracefully falls back to NEUTRAL_THRESHOLD (0.50) when:
      - metrics is None
      - the field is missing or zero/NaN
      - direction is not 'long'/'up' or 'short'/'down'

    Used by the confidence gate to size the CONFIRMS threshold per-model.
    """
    if metrics is None:
        return NEUTRAL_THRESHOLD
    d = (direction or "").lower()
    if d in ("long", "up", "buy"):
        key = "calibrated_up_threshold"
    elif d in ("short", "down", "sell"):
        key = "calibrated_down_threshold"
    else:
        return NEUTRAL_THRESHOLD
    v = metrics.get(key, NEUTRAL_THRESHOLD)
    try:
        vf = float(v)
    except (TypeError, ValueError):
        return NEUTRAL_THRESHOLD
    if not np.isfinite(vf) or vf <= 0:
        return NEUTRAL_THRESHOLD
    return float(np.clip(vf, floor, ceiling))
