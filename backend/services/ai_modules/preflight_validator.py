"""
Pre-flight Shape Validator — run BEFORE the massive retrain starts.

Motivation
----------
On 2026-04-21 Phase 2 crashed after ~12 min of Phase 1 with:
    scalp_1min_predictor: ('feature names must have the same length
    as the number of data columns, ', 'expected 57, got 52')

The bug: setup workers FFD-augment base_matrix (46 → 51 cols) when
`TB_USE_FFD_FEATURES=1`, but the outer pipeline loop built `combined_names`
from the NON-augmented name list → 52 names vs 57 X cols.

This validator catches that class of bug in <5 seconds using synthetic
bars, so a 44h retrain never dies of a 1-line mismatch.

What it checks
--------------
For every (setup_type, bar_size) in Phase 2 (long) and Phase 2.5 (short):
  1. Run the real worker on synthetic bars under current env flags
     (TB_USE_FFD_FEATURES, TB_USE_CUSUM).
  2. Rebuild `combined_names` exactly as the pipeline loop does.
  3. Assert `len(combined_names) == X.shape[1]`.

Any mismatch → returns `ok=False` + detailed failure list, which the
pipeline caller aborts on before spending hours.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


# ── Synthetic bar generator (self-contained — no DB) ───────────────────

def _synthetic_bars(n: int = 600, seed: int = 42) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    highs = closes + np.abs(rng.normal(0.3, 0.2, n))
    lows = closes - np.abs(rng.normal(0.3, 0.2, n))
    opens = closes + rng.normal(0, 0.1, n)
    volumes = rng.integers(100_000, 1_000_000, n).astype(float)
    return [
        {
            "open": float(opens[i]),
            "high": float(max(highs[i], closes[i], opens[i])),
            "low": float(min(lows[i], closes[i], opens[i])),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "date": f"2026-03-{(i % 28) + 1:02d}",
        }
        for i in range(n)
    ]


# ── Phase 2 (long) and 2.5 (short) shape validator ─────────────────────

def _validate_long_setups(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate every long setup_type used in Phase 2."""
    from services.ai_modules.training_pipeline import (
        _extract_setup_long_worker, ALL_SETUP_TYPES,
    )
    from services.ai_modules.setup_training_config import get_setup_profiles
    from services.ai_modules.setup_features import get_setup_feature_names
    from services.ai_modules.feature_augmentors import augmented_feature_names
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    base_names = augmented_feature_names(fe.get_feature_names())

    failures: List[Dict[str, Any]] = []
    checked = 0

    # Group by bar_size so we mimic the real loop (same worker call shape)
    from collections import defaultdict
    profiles_by_bs: Dict[str, list] = defaultdict(list)
    for st in ALL_SETUP_TYPES:
        for p in get_setup_profiles(st):
            profiles_by_bs[p["bar_size"]].append((st, p))

    for bs, st_profiles in profiles_by_bs.items():
        setup_configs = [
            (st, p["forecast_horizon"], p.get("noise_threshold", 0.003), 2.0, 1.0, 14)
            for st, p in st_profiles
        ]
        try:
            res = _extract_setup_long_worker(("PREFLIGHT", bars, setup_configs))
        except Exception as e:
            failures.append({
                "phase": "setup_long", "bar_size": bs, "setup_type": "<all>",
                "error": f"worker raised: {e}",
            })
            continue
        if not res:
            # Not a shape bug — synthetic bars might not trigger every setup
            continue

        for (st, fh), (X, _y) in res.items():
            combined_names = base_names + [f"setup_{n}" for n in get_setup_feature_names(st)]
            checked += 1
            if len(combined_names) != X.shape[1]:
                failures.append({
                    "phase": "setup_long", "bar_size": bs, "setup_type": st,
                    "forecast_horizon": fh,
                    "combined_names_len": len(combined_names),
                    "X_cols": int(X.shape[1]),
                    "diff": int(X.shape[1]) - len(combined_names),
                })
    logger.info(f"[preflight] Phase 2 long: checked {checked} setups, {len(failures)} mismatches")
    return failures


def _validate_short_setups(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate every short setup_type used in Phase 2.5."""
    from services.ai_modules.training_pipeline import (
        _extract_setup_short_worker, ALL_SHORT_SETUP_TYPES,
    )
    from services.ai_modules.setup_training_config import get_setup_profiles
    from services.ai_modules.short_setup_features import get_short_setup_feature_names
    from services.ai_modules.feature_augmentors import augmented_feature_names
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    base_names = augmented_feature_names(fe.get_feature_names())

    failures: List[Dict[str, Any]] = []
    checked = 0

    from collections import defaultdict
    profiles_by_bs: Dict[str, list] = defaultdict(list)
    for st in ALL_SHORT_SETUP_TYPES:
        for p in get_setup_profiles(st):
            profiles_by_bs[p["bar_size"]].append((st, p))

    for bs, st_profiles in profiles_by_bs.items():
        setup_configs = [
            (st, p["forecast_horizon"], p.get("noise_threshold", 0.003), 2.0, 1.0, 14)
            for st, p in st_profiles
        ]
        try:
            res = _extract_setup_short_worker(("PREFLIGHT", bars, setup_configs))
        except Exception as e:
            failures.append({
                "phase": "setup_short", "bar_size": bs, "setup_type": "<all>",
                "error": f"worker raised: {e}",
            })
            continue
        if not res:
            continue

        for (st, fh), (X, _y) in res.items():
            combined_names = base_names + [f"short_{n}" for n in get_short_setup_feature_names(st)]
            checked += 1
            if len(combined_names) != X.shape[1]:
                failures.append({
                    "phase": "setup_short", "bar_size": bs, "setup_type": st,
                    "forecast_horizon": fh,
                    "combined_names_len": len(combined_names),
                    "X_cols": int(X.shape[1]),
                    "diff": int(X.shape[1]) - len(combined_names),
                })
    logger.info(f"[preflight] Phase 2.5 short: checked {checked} setups, {len(failures)} mismatches")
    return failures


# ── Public API ─────────────────────────────────────────────────────────

def preflight_validate_shapes(phases: List[str]) -> Dict[str, Any]:
    """
    Run pre-flight shape validation for all enabled phases.

    Args:
        phases: list of phases that will run (e.g., ["setup", "short", "volatility"]).

    Returns:
        {"ok": bool, "checked_phases": [...], "failures": [...], "duration_s": float}
    """
    import os
    import time

    start = time.monotonic()
    bars = _synthetic_bars(n=600)

    flags = {
        "TB_USE_FFD_FEATURES": os.environ.get("TB_USE_FFD_FEATURES", "0"),
        "TB_USE_CUSUM":        os.environ.get("TB_USE_CUSUM", "0"),
    }
    logger.info(f"[preflight] Starting shape validation. Flags: {flags}")

    failures: List[Dict[str, Any]] = []
    checked_phases: List[str] = []

    if "setup" in phases:
        checked_phases.append("setup_long")
        failures.extend(_validate_long_setups(bars))

    if "short" in phases:
        checked_phases.append("setup_short")
        failures.extend(_validate_short_setups(bars))

    duration = time.monotonic() - start
    ok = len(failures) == 0

    if ok:
        logger.info(
            f"[preflight] ✅ PASSED in {duration:.1f}s — phases={checked_phases}, flags={flags}"
        )
    else:
        logger.error(f"[preflight] ❌ FAILED in {duration:.1f}s — {len(failures)} mismatches:")
        for f in failures:
            logger.error(f"[preflight]   {f}")

    return {
        "ok": ok,
        "checked_phases": checked_phases,
        "failures": failures,
        "duration_s": round(duration, 2),
        "flags": flags,
    }
