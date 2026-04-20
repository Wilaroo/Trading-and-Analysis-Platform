"""
Feature Augmentors — optional feature additions bolted onto the base matrix.

Each augmentor is flag-gated so existing 46-feature pipeline is untouched
unless explicitly enabled.

Currently:
    FFD (Fractional Differentiation): 5 columns added via
        TB_USE_FFD_FEATURES=1

Usage (in training_pipeline):
    from services.ai_modules.feature_augmentors import (
        augment_features, augmented_feature_names,
    )

    base = feature_engineer.extract_features_bulk(bars)
    X, names = augment_features(base, feature_engineer.get_feature_names(), bars)
    # X now has shape (N, 46 + extras) if flags on, else unchanged.
"""
from __future__ import annotations
import numpy as np
import os
from typing import List, Tuple, Optional, Dict

from services.ai_modules.fractional_diff import compute_ffd_features


# ─── Flags ──────────────────────────────────────────────────────────

def ffd_enabled() -> bool:
    return os.environ.get("TB_USE_FFD_FEATURES", "0") in ("1", "true", "True", "YES")


# ─── FFD Augmentor ──────────────────────────────────────────────────

FFD_NAMES = [
    "ffd_close_adaptive",
    "ffd_close_03",
    "ffd_close_05",
    "ffd_close_07",
    "ffd_optimal_d",
]


def compute_ffd_columns(
    bars: List[Dict],
    lookback: int = 50,
    d_cache: Optional[dict] = None,
    cache_key: Optional[str] = None,
    expected_rows: Optional[int] = None,
) -> Optional[np.ndarray]:
    """
    Build (N, 5) matrix of FFD features aligned to feature matrix rows.

    Feature-matrix row j corresponds to bar index (lookback - 1 + j), so we
    compute FFD on full closes and slice from (lookback - 1) onward.

    If ``expected_rows`` is given and FFD cannot be computed (too few bars),
    return a zero matrix of shape (expected_rows, 5) instead of None. This
    keeps downstream matrix shapes consistent across heterogeneous symbols.
    """
    def _zero_fallback():
        if expected_rows is not None and expected_rows > 0:
            return np.zeros((expected_rows, 5), dtype=np.float32)
        return None

    if len(bars) < lookback + 10:
        return _zero_fallback()
    try:
        closes = np.array([b.get("close", 0) for b in bars], dtype=np.float64)
        feats = compute_ffd_features(closes, d_cache=d_cache, cache_key=cache_key)

        start = lookback - 1
        adaptive = feats["ffd_close_adaptive"][start:]
        ffd_03 = feats["ffd_close_03"][start:]
        ffd_05 = feats["ffd_close_05"][start:]
        ffd_07 = feats["ffd_close_07"][start:]
        d_opt = feats["ffd_optimal_d"]

        n = len(adaptive)
        out = np.column_stack([
            np.nan_to_num(adaptive, nan=0.0, posinf=0.0, neginf=0.0),
            np.nan_to_num(ffd_03, nan=0.0, posinf=0.0, neginf=0.0),
            np.nan_to_num(ffd_05, nan=0.0, posinf=0.0, neginf=0.0),
            np.nan_to_num(ffd_07, nan=0.0, posinf=0.0, neginf=0.0),
            np.full(n, d_opt, dtype=np.float64),
        ]).astype(np.float32)
        return out
    except Exception:
        # Any numerical / ADF failure → zero-pad to keep shape consistent.
        return _zero_fallback()


def augment_features(
    base_matrix: np.ndarray,
    base_names: List[str],
    bars: List[Dict],
    lookback: int = 50,
    d_cache: Optional[dict] = None,
    cache_key: Optional[str] = None,
) -> Tuple[np.ndarray, List[str]]:
    """
    Return (augmented_matrix, augmented_names). Returns originals when all
    flags are off. When FFD is ON, always appends exactly 5 cols (zero-padded
    if the symbol can't produce real FFD features) so that per-symbol matrices
    concatenate cleanly across a heterogeneous universe.
    """
    if base_matrix is None:
        return base_matrix, base_names

    aug_cols = []
    aug_names = list(base_names)

    if ffd_enabled():
        ffd_cols = compute_ffd_columns(
            bars, lookback=lookback,
            d_cache=d_cache, cache_key=cache_key,
            expected_rows=len(base_matrix),
        )
        # compute_ffd_columns now guarantees shape (len(base_matrix), 5) when
        # expected_rows is given — real features when possible, zeros when not.
        if ffd_cols is None:
            ffd_cols = np.zeros((len(base_matrix), 5), dtype=np.float32)
        # Align length (defensive; expected_rows should make this a no-op)
        n_aligned = min(len(base_matrix), len(ffd_cols))
        base_matrix = base_matrix[:n_aligned]
        ffd_cols = ffd_cols[:n_aligned]
        aug_cols.append(ffd_cols)
        aug_names = aug_names + FFD_NAMES

    if not aug_cols:
        return base_matrix, aug_names

    stacked = np.hstack([base_matrix] + aug_cols)
    return stacked, aug_names


def augmented_feature_names(base_names: List[str]) -> List[str]:
    """Return the feature name list respecting currently-enabled augmentors."""
    out = list(base_names)
    if ffd_enabled():
        out = out + FFD_NAMES
    return out
