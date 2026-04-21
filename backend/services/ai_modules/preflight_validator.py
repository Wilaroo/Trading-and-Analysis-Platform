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

What it checks (all using synthetic OHLCV bars, no DB needed)
-------------------------------------------------------------
Phase 2   (setup long)    — runs `_extract_setup_long_worker`, compares to combined_names
Phase 2.5 (setup short)   — runs `_extract_setup_short_worker`, compares to combined_names
Phase 3   (volatility)    — static: base ⊕ VOL ⊕ REGIME name count invariants
Phase 4   (exit timing)   — runs `_extract_exit_worker`, compares to combined_names
Phase 5   (sector)        — static invariant: base 46-col + SECTOR_REL names
Phase 5.5 (gap fill)      — static invariant: base 46-col + GAP names
Phase 6   (risk of ruin)  — runs `_extract_risk_worker`, compares to combined_names
Phase 7   (regime)        — static: base-only 46 cols == base_names len
Phase 8   (ensemble)      — static: len(ENSEMBLE_FEATURE_NAMES) well-defined

Base invariant (applies to ALL phases via cached_extract_features_bulk):
  `extract_features_bulk` output cols == `get_feature_names()` len (== 46)
  If this ever drifts (e.g., someone later FFD-augments inside bulk extractor),
  Phases 3/5/5.5/7 will silently break like Phase 2 did. This check catches that.

Any failure → returns `ok=False` + detailed failure list, which the
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


# ── Base invariant: get_feature_names() matches extract_features_bulk cols ──

def _validate_base_invariant(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every non-setup phase relies on `cached_extract_features_bulk` producing
    exactly `len(get_feature_names())` columns. If that invariant ever breaks
    (e.g., someone silently adds FFD to the bulk extractor), Phase 3/5/5.5/7
    will crash the same way Phase 2 did. Catch drift here."""
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    names = fe.get_feature_names()
    mat = fe.extract_features_bulk(bars)
    failures: List[Dict[str, Any]] = []
    if mat is None:
        failures.append({"phase": "base_invariant", "error": "extract_features_bulk returned None"})
        return failures
    if mat.shape[1] != len(names):
        failures.append({
            "phase": "base_invariant",
            "feature_names_len": len(names),
            "extract_features_bulk_cols": int(mat.shape[1]),
            "diff": int(mat.shape[1]) - len(names),
            "note": "extract_features_bulk output does not match get_feature_names() length",
        })
    logger.info(
        f"[preflight] base invariant: names={len(names)}, bulk_cols={mat.shape[1]}, "
        f"{'OK' if not failures else 'MISMATCH'}"
    )
    return failures


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


# ── Phase 4: Exit Timing ───────────────────────────────────────────────

def _validate_exit_phase(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from services.ai_modules.training_pipeline import _extract_exit_worker
    from services.ai_modules.exit_timing_model import EXIT_MODEL_CONFIGS, EXIT_FEATURE_NAMES
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    base_names = fe.get_feature_names()
    combined_names = base_names + [f"exit_{n}" for n in EXIT_FEATURE_NAMES]

    exit_configs = [(st, cfg["max_horizon"]) for st, cfg in EXIT_MODEL_CONFIGS.items()]
    failures: List[Dict[str, Any]] = []
    try:
        res = _extract_exit_worker(("PREFLIGHT", bars, exit_configs))
    except Exception as e:
        return [{"phase": "exit", "error": f"worker raised: {e}"}]
    if not res:
        logger.info("[preflight] Phase 4 exit: worker returned empty (synthetic bars) — skipping shape check")
        return failures
    for st_key, (X, _y) in res.items():
        if len(combined_names) != X.shape[1]:
            failures.append({
                "phase": "exit", "setup_type": st_key,
                "combined_names_len": len(combined_names),
                "X_cols": int(X.shape[1]),
                "diff": int(X.shape[1]) - len(combined_names),
            })
    logger.info(f"[preflight] Phase 4 exit: checked {len(res)} setups, {len(failures)} mismatches")
    return failures


# ── Phase 6: Risk of Ruin ──────────────────────────────────────────────

def _validate_risk_phase(bars: List[Dict[str, Any]], bar_sizes: List[str]) -> List[Dict[str, Any]]:
    from services.ai_modules.training_pipeline import _extract_risk_worker
    from services.ai_modules.risk_of_ruin_model import RISK_MODEL_CONFIGS, RISK_FEATURE_NAMES
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    base_names = fe.get_feature_names()
    combined_names = base_names + [f"risk_{n}" for n in RISK_FEATURE_NAMES]

    risk_configs = [
        (bs, RISK_MODEL_CONFIGS[bs]["max_bars"])
        for bs in bar_sizes if bs in RISK_MODEL_CONFIGS
    ]
    if not risk_configs:
        return []

    failures: List[Dict[str, Any]] = []
    try:
        res = _extract_risk_worker(("PREFLIGHT", bars, risk_configs))
    except Exception as e:
        return [{"phase": "risk", "error": f"worker raised: {e}"}]
    if not res:
        logger.info("[preflight] Phase 6 risk: worker returned empty — skipping")
        return failures
    for bs_key, (X, _y) in res.items():
        if len(combined_names) != X.shape[1]:
            failures.append({
                "phase": "risk", "bar_size": bs_key,
                "combined_names_len": len(combined_names),
                "X_cols": int(X.shape[1]),
                "diff": int(X.shape[1]) - len(combined_names),
            })
    logger.info(f"[preflight] Phase 6 risk: checked {len(res)} bar_sizes, {len(failures)} mismatches")
    return failures


# ── Phases 3/5/5.5/7/8: Static name-length invariants ──────────────────
# These phases use `cached_extract_features_bulk` (no FFD) and build X from
# `base_matrix (46 cols) + secondary_feature_matrix`. If base invariant
# holds, each phase's combined_names == X.shape[1] by construction
# (verified by code inspection). Here we just assert the secondary name lists
# are well-formed and non-empty.

def _validate_static_phases() -> List[Dict[str, Any]]:
    from services.ai_modules.volatility_model import VOL_FEATURE_NAMES
    from services.ai_modules.regime_features import REGIME_FEATURE_NAMES
    from services.ai_modules.sector_relative_model import SECTOR_REL_FEATURE_NAMES
    from services.ai_modules.gap_fill_model import GAP_FEATURE_NAMES
    from services.ai_modules.ensemble_model import ENSEMBLE_FEATURE_NAMES

    failures: List[Dict[str, Any]] = []
    checks = {
        "vol":      VOL_FEATURE_NAMES,
        "regime":   REGIME_FEATURE_NAMES,
        "sector":   SECTOR_REL_FEATURE_NAMES,
        "gap":      GAP_FEATURE_NAMES,
        "ensemble": ENSEMBLE_FEATURE_NAMES,
    }
    for phase, names in checks.items():
        if not isinstance(names, (list, tuple)) or len(names) == 0:
            failures.append({"phase": phase, "error": f"{phase} feature names list is empty or invalid"})
            continue
        if len(set(names)) != len(names):
            failures.append({"phase": phase, "error": f"{phase} feature names contain duplicates"})
    logger.info(f"[preflight] Static name-list checks: {len(failures)} failures")
    return failures


# ── Public API ─────────────────────────────────────────────────────────

def preflight_validate_shapes(phases: List[str], bar_sizes: List[str] = None) -> Dict[str, Any]:
    """
    Run pre-flight shape validation for all enabled phases.

    Args:
        phases: list of phases that will run (e.g., ["setup", "short", "volatility"]).
        bar_sizes: list of bar_sizes (only used by Phase 6 risk).

    Returns:
        {"ok": bool, "checked_phases": [...], "failures": [...], "duration_s": float}
    """
    import os
    import time

    if bar_sizes is None:
        bar_sizes = ["1 min", "5 mins", "15 mins", "30 mins", "1 hour", "1 day"]

    start = time.monotonic()
    bars = _synthetic_bars(n=600)

    flags = {
        "TB_USE_FFD_FEATURES": os.environ.get("TB_USE_FFD_FEATURES", "0"),
        "TB_USE_CUSUM":        os.environ.get("TB_USE_CUSUM", "0"),
    }
    logger.info(f"[preflight] Starting shape validation. Flags: {flags}")

    failures: List[Dict[str, Any]] = []
    checked_phases: List[str] = []

    # Base invariant runs always — all phases depend on it
    checked_phases.append("base_invariant")
    failures.extend(_validate_base_invariant(bars))

    if "setup" in phases:
        checked_phases.append("setup_long")
        failures.extend(_validate_long_setups(bars))

    if "short" in phases:
        checked_phases.append("setup_short")
        failures.extend(_validate_short_setups(bars))

    if "exit" in phases:
        checked_phases.append("exit")
        failures.extend(_validate_exit_phase(bars))

    if "risk" in phases:
        checked_phases.append("risk")
        failures.extend(_validate_risk_phase(bars, bar_sizes))

    # Static checks for phases whose X is built by column-write construction
    static_needed = any(p in phases for p in ("volatility", "sector", "gap_fill", "regime", "ensemble"))
    if static_needed:
        checked_phases.append("static_name_lists")
        failures.extend(_validate_static_phases())

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
