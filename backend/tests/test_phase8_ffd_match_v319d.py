"""
v319d — Phase-8 ensemble FFD MATCH-FIX.

Sub-models (Phase 1 direction_predictor + Phase 2 setup_specific) are trained on
46 base + 5 FFD = 51 cols when TB_USE_FFD_FEATURES=1. The Phase-8 ensemble used a
raw 46-wide features_matrix, so the col_map FFD positions (46-50) fell out of
bounds and were ZERO-FILLED → sub-models' FFD splits always saw 0. The fix
FFD-augments features_matrix inline (same augmentor as training).

These tests pin the augmentation contract + the col_map fill behavior the Phase-8
loop relies on (pure; no feature engineer / DB / GPU).
"""
import numpy as np
import pytest

from services.ai_modules.feature_augmentors import (
    augment_features, augmented_feature_names, FFD_NAMES,
)


def _bars(n=160, seed=0):
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return [{"close": float(c), "high": float(c + 0.2), "low": float(c - 0.2),
             "open": float(c)} for c in closes]


def test_augment_appends_5_ffd_cols_when_enabled(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    lb = 50
    bars = _bars()
    K = len(bars) - lb + 1
    base = np.ones((K, 46), dtype=np.float32)
    names = [f"f{i}" for i in range(46)]

    aug, aug_names = augment_features(base, names, bars, lookback=lb, cache_key="T_5mins")

    assert aug.shape == (K, 51)
    assert aug_names == names + FFD_NAMES
    # base columns preserved untouched
    assert np.all(aug[:, :46] == 1)
    # FFD block is NOT all-zero (the whole point of the fix vs zero-fill)
    assert not np.all(aug[:, 46:51] == 0)
    # ffd_optimal_d (last col) is always populated
    assert np.count_nonzero(aug[:, 50]) == K


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")
    lb = 50
    bars = _bars()
    K = len(bars) - lb + 1
    base = np.ones((K, 46), dtype=np.float32)
    names = [f"f{i}" for i in range(46)]

    aug, aug_names = augment_features(base, names, bars, lookback=lb)
    assert aug.shape == (K, 46)
    assert aug_names == names


def test_colmap_fill_delivers_real_ffd_not_zeros(monkeypatch):
    """Reproduces the Phase-8 col_map fill: with the fix, the FFD columns handed
    to a sub-model are populated; with the OLD 46-wide matrix they were 0."""
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    lb = 50
    bars = _bars()
    K = len(bars) - lb + 1
    base = np.ones((K, 46), dtype=np.float32)
    names = [f"f{i}" for i in range(46)]

    aug, aug_names = augment_features(base, names, bars, lookback=lb, cache_key="T_5mins")

    # a sub-model trained on 2 base feats + the 5 FFD feats
    sub_feature_names = ["f3", "f10"] + FFD_NAMES
    name_to_idx = {n: i for i, n in enumerate(aug_names)}      # over 51 augmented names
    col_map = [name_to_idx.get(f, -1) for f in sub_feature_names]

    # ── FIXED path: features_matrix is the 51-wide augmented matrix ──
    fixed = np.zeros((K, len(col_map)), dtype=np.float32)
    for ci, src in enumerate(col_map):
        if 0 <= src < aug.shape[1]:
            fixed[:, ci] = aug[:, src]
    # the ffd_optimal_d column (last in sub_feature_names) must be populated
    assert np.count_nonzero(fixed[:, -1]) == K
    assert not np.all(fixed[:, 2:] == 0)  # the 5 FFD slots not all zero

    # ── OLD broken path: 46-wide matrix → FFD src indices (>=46) out of bounds ──
    old = np.zeros((K, len(col_map)), dtype=np.float32)
    for ci, src in enumerate(col_map):
        if 0 <= src < base.shape[1]:   # base.shape[1] == 46
            old[:, ci] = base[:, src]
    assert np.all(old[:, 2:] == 0)  # every FFD slot was zero-filled (the bug)


def test_row_alignment_matches_base_rows(monkeypatch):
    """augment must return exactly len(base) rows so Phase-8 labels stay aligned."""
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    lb = 50
    bars = _bars(n=200)
    for n_usable in (40, 90, 140):
        base = np.ones((n_usable, 46), dtype=np.float32)
        names = [f"f{i}" for i in range(46)]
        aug, _ = augment_features(base, names, bars, lookback=lb, cache_key="T_5mins")
        assert aug.shape[0] == n_usable
