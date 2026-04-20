"""Regression test for feature_augmentors shape-consistency guarantee.

The bug: when TB_USE_FFD_FEATURES=1, symbols with <60 bars would silently
fall back to 46 cols (FFD returned None). Symbols with ≥60 bars produced 51
cols. Concatenating them across the universe crashed vstack with
'dimension 1 mismatch: 51 vs 46'.

Fix: augment_features must always append 5 FFD cols (zero-padded if real
FFD is unavailable) so per-symbol matrices concatenate cleanly.
"""
import numpy as np
import pytest
from services.ai_modules.feature_augmentors import augment_features, compute_ffd_columns


def _bars(n: int):
    return [
        {"open": 100.0 + i * 0.1, "high": 101.0 + i * 0.1, "low": 99.0 + i * 0.1,
         "close": 100.0 + i * 0.1 + (i % 3) * 0.05, "volume": 1000 + i}
        for i in range(n)
    ]


def test_augment_features_always_appends_5_cols_when_ffd_on(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    base_names = [f"f{i}" for i in range(46)]

    # Symbol A: plenty of data → FFD computes real cols
    bars_a = _bars(200)
    base_a = np.random.randn(200 - 49, 46).astype(np.float32)  # 151 rows
    mat_a, names_a = augment_features(base_a, base_names, bars_a)
    assert mat_a.shape[1] == 51
    assert len(names_a) == 51

    # Symbol B: 55 bars (too few for FFD's lookback+10=60 guard) → zero-pad
    bars_b = _bars(55)
    base_b = np.random.randn(55 - 49, 46).astype(np.float32)  # 6 rows
    mat_b, names_b = augment_features(base_b, base_names, bars_b)
    assert mat_b.shape[1] == 51, f"Expected 51 cols even on short series, got {mat_b.shape[1]}"
    assert len(names_b) == 51

    # Symbol C: exactly at the boundary (60 bars) → real FFD
    bars_c = _bars(60)
    base_c = np.random.randn(60 - 49, 46).astype(np.float32)  # 11 rows
    mat_c, names_c = augment_features(base_c, base_names, bars_c)
    assert mat_c.shape[1] == 51

    # The actual bug guard: vstacking A+B+C must NOT crash.
    stacked = np.vstack([mat_a, mat_b, mat_c])
    assert stacked.shape == (mat_a.shape[0] + mat_b.shape[0] + mat_c.shape[0], 51)


def test_augment_features_zero_pads_short_series():
    import os
    os.environ["TB_USE_FFD_FEATURES"] = "1"
    try:
        base_names = [f"f{i}" for i in range(46)]
        # Too-short series — FFD returns zeros
        short_bars = _bars(55)
        base = np.random.randn(6, 46).astype(np.float32)
        out, _ = augment_features(base, base_names, short_bars)
        # Last 5 cols should be exactly zero (the padding)
        assert np.all(out[:, 46:] == 0.0)
    finally:
        os.environ.pop("TB_USE_FFD_FEATURES", None)


def test_compute_ffd_columns_fallback_with_expected_rows():
    # Too few bars → zero matrix of expected_rows shape
    out = compute_ffd_columns(_bars(30), lookback=50, expected_rows=10)
    assert out is not None
    assert out.shape == (10, 5)
    assert np.all(out == 0.0)


def test_compute_ffd_columns_no_expected_rows_returns_none_when_short():
    # Legacy behaviour: without expected_rows, short series still returns None
    out = compute_ffd_columns(_bars(30), lookback=50)
    assert out is None


def test_augment_features_ffd_off_passthrough(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")
    base_names = [f"f{i}" for i in range(46)]
    base = np.random.randn(100, 46).astype(np.float32)
    out, names = augment_features(base, base_names, _bars(200))
    assert out.shape[1] == 46
    assert len(names) == 46
