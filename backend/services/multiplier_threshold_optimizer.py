"""
multiplier_threshold_optimizer.py — nightly self-tuning job for the
liquidity-aware execution layers shipped 2026-04-28e.

Goal: convert the liquidity-aware layers from a well-engineered system
into a self-improving one. Reads the last N days of `bot_trades`,
computes the mean-R *lift* (fired - not_fired) for each layer, and
proposes small bounded adjustments to the underlying thresholds in the
direction that maximises lift.

Three dials are tuned, all defined in `smart_levels_service.py`:

  - `_STOP_MIN_LEVEL_STRENGTH`  — strength bar to fire stop-guard
  - `_TARGET_SNAP_OUTSIDE_PCT`  — outer search window for target-snap
  - `_PATH_VOL_FAT_PCT`         — VP-path "thick HVN" threshold

Each run writes a single document into `multiplier_threshold_history`:

    {
      "ran_at": <iso>,
      "window_days": 30,
      "lift": {stop_guard: 0.12, target_snap: -0.05, vp_path: 0.08},
      "thresholds_before": {...},
      "thresholds_after":  {...},
      "applied": bool,
      "notes": [...],
    }

`get_active_thresholds(db)` in `smart_levels_service` reads the most
recent applied document with a TTL cache, so the snap layers pick up
new thresholds within ~5 min of an optimizer run — no code changes,
no service restart.

SAFETY:
  - **Per-run step cap**: never adjusts a threshold by more than 5% of
    its current value per night.
  - **Min-N gate**: skips a layer entirely if either cohort has fewer
    than `_MIN_COHORT_N` trades — adjusting thresholds on noise is
    worse than leaving them alone.
  - **Hard bounds**: every threshold has a `[min, max]` clamp so a
    sustained bad signal can't drift the value past sane operating
    limits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import smart_levels_service as sls
from services.multiplier_analytics_service import compute_multiplier_analytics

logger = logging.getLogger(__name__)


# ─── Tuning knobs ──────────────────────────────────────────────────────

# Min trades in EACH cohort before we'll touch a threshold. Less than
# this and we treat the lift signal as noise.
_MIN_COHORT_N = 15

# Max fraction of a threshold we're allowed to move per nightly run.
# Keeps adjustments small + reversible.
_MAX_STEP_PCT = 0.05

# Per-threshold metadata: hard clamps + which direction "more aggressive
# firing" pulls the value.
#   - direction = +1: HIGHER threshold → fires LESS often.
#   - direction = -1: HIGHER threshold → fires MORE often.
# When fired_mean_r < not_fired_mean_r (negative lift), we want to fire
# LESS often, i.e. push the threshold in the direction of `direction`.
_THRESHOLD_META = {
    "stop_min_level_strength": {
        "attr": "_STOP_MIN_LEVEL_STRENGTH",
        "min":  0.30,
        "max":  0.85,
        "direction": +1,    # higher → fires less
    },
    "target_snap_outside_pct": {
        "attr": "_TARGET_SNAP_OUTSIDE_PCT",
        "min":  0.005,
        "max":  0.030,
        "direction": -1,    # higher → fires more (wider search window)
    },
    "path_vol_fat_pct": {
        "attr": "_PATH_VOL_FAT_PCT",
        "min":  0.20,
        "max":  0.45,
        "direction": +1,    # higher → fires less (less aggressive downsizing)
    },
}

# Mapping from analytics layer name → which threshold to tune for it.
_LAYER_TO_THRESHOLD = {
    "stop_guard":  "stop_min_level_strength",
    "target_snap": "target_snap_outside_pct",
    "vp_path":     "path_vol_fat_pct",
}

# Lift bands (mean-R difference fired - not_fired) and the step they trigger.
_NEGATIVE_LIFT_TIGHTEN = -0.20    # < this → tighten threshold (fire less)
_POSITIVE_LIFT_LOOSEN  = +0.30    # > this → loosen threshold (fire more)

# How long an applied threshold doc is considered current. The runtime
# helper `get_active_thresholds` re-reads at most every TTL seconds.
_THRESHOLD_CACHE_TTL_SEC = 300


# ─── Helpers ───────────────────────────────────────────────────────────

def _current_threshold(name: str) -> float:
    """Read the live threshold value from the smart_levels_service
    module — falls back to the module default if no override is set."""
    meta = _THRESHOLD_META[name]
    return float(getattr(sls, meta["attr"]))


def _propose_step(name: str, lift: Optional[float], current: float) -> Dict[str, Any]:
    """Return `{new, step_pct, reason}` for a single threshold."""
    meta = _THRESHOLD_META[name]
    if lift is None:
        return {"new": current, "step_pct": 0.0, "reason": "insufficient_data"}

    if lift < _NEGATIVE_LIFT_TIGHTEN:
        # Layer is a net negative when it fires → fire LESS often
        step_sign = +meta["direction"]
        reason = "tighten_for_negative_lift"
    elif lift > _POSITIVE_LIFT_LOOSEN:
        # Layer is a net positive → try firing MORE often
        step_sign = -meta["direction"]
        reason = "loosen_for_positive_lift"
    else:
        return {"new": current, "step_pct": 0.0, "reason": "lift_within_band"}

    proposed = current * (1 + step_sign * _MAX_STEP_PCT)
    proposed = max(meta["min"], min(meta["max"], proposed))
    return {
        "new": round(proposed, 4),
        "step_pct": round((proposed / current) - 1.0, 4),
        "reason": reason,
    }


# ─── Public API ────────────────────────────────────────────────────────

def run_optimization(
    db,
    days_back: int = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Compute lift per layer and propose threshold adjustments.

    When `dry_run=False`, the proposed thresholds are written into the
    `multiplier_threshold_history` collection with `applied=True`. The
    runtime smart_levels_service reads that collection (with TTL cache)
    so adjustments take effect without a backend restart.

    Returns the full decision payload regardless of `dry_run`.
    """
    analytics = compute_multiplier_analytics(db, days_back=days_back, only_closed=True)

    notes: List[str] = []
    lifts: Dict[str, Optional[float]] = {}
    cohort_n: Dict[str, Dict[str, int]] = {}

    for layer_key, ana_key in (("stop_guard", "stop_guard"),
                                ("target_snap", "target_snap"),
                                ("vp_path", "vp_path")):
        ana = analytics.get(ana_key) or {}
        if layer_key == "vp_path":
            fired_label, notfired_label = "downsized", "full_size"
        else:
            fired_label, notfired_label = "fired", "not_fired"
        fired = ana.get(fired_label) or {}
        notf  = ana.get(notfired_label) or {}
        n_fired, n_not = fired.get("count", 0), notf.get("count", 0)
        cohort_n[layer_key] = {"fired": n_fired, "not_fired": n_not}

        if n_fired < _MIN_COHORT_N or n_not < _MIN_COHORT_N:
            lifts[layer_key] = None
            notes.append(
                f"{layer_key}: insufficient data ({n_fired}/{n_not} "
                f"< {_MIN_COHORT_N}); leaving threshold unchanged"
            )
            continue
        f_r, nf_r = fired.get("mean_r"), notf.get("mean_r")
        if f_r is None or nf_r is None:
            lifts[layer_key] = None
            notes.append(f"{layer_key}: missing mean_r in cohorts")
            continue
        lifts[layer_key] = round(f_r - nf_r, 4)

    thresholds_before: Dict[str, float] = {}
    thresholds_after:  Dict[str, float] = {}
    proposals: Dict[str, Dict[str, Any]] = {}

    for layer_key, threshold_name in _LAYER_TO_THRESHOLD.items():
        current = _current_threshold(threshold_name)
        prop = _propose_step(threshold_name, lifts.get(layer_key), current)
        thresholds_before[threshold_name] = current
        thresholds_after[threshold_name]  = prop["new"]
        proposals[threshold_name] = {
            "current":  current,
            "proposed": prop["new"],
            "step_pct": prop["step_pct"],
            "reason":   prop["reason"],
            "lift":     lifts.get(layer_key),
            "cohort_n": cohort_n[layer_key],
        }
        if prop["new"] != current:
            notes.append(
                f"{threshold_name}: {current:.4f} → {prop['new']:.4f} "
                f"({prop['reason']}, lift={lifts.get(layer_key)})"
            )

    payload: Dict[str, Any] = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days_back,
        "lifts": lifts,
        "cohort_n": cohort_n,
        "thresholds_before": thresholds_before,
        "thresholds_after":  thresholds_after,
        "proposals": proposals,
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
        payload["applied"] = False
        payload["notes"].append("no thresholds changed; nothing persisted")
        return payload

    # Persist + activate
    if db is not None:
        try:
            db["multiplier_threshold_history"].insert_one({**payload, "applied": True})
            payload["applied"] = True
            # Bust the runtime cache so next snap call reads new values.
            sls.invalidate_threshold_cache()
            logger.info(f"multiplier_threshold_optimizer applied: {payload['notes']}")
        except Exception as e:
            logger.error(f"failed to persist threshold optimizer result: {e}")
            payload["applied"] = False
            payload["notes"].append(f"persist failed: {e}")

    return payload
