"""
v19.34.315 — Phase-3 volatility target filtering regression.

The v19.34.312 `compute_vol_targets_batch` emits -1.0 for degenerate (flat)
windows and documents "caller should filter out -1.0 entries". The Phase-3
caller didn't, so negative labels reached bincount/XGBoost →
"'list' argument must have no negative elements" → 0/7 vol models.

These tests pin the contract: batch targets can be negative, and the
caller-side `y >= 0` mask removes them so a downstream bincount is safe.
"""
import numpy as np

from services.ai_modules.volatility_model import compute_vol_targets_batch


def test_flat_window_produces_negative_target():
    # A fully flat series → every trailing window has vol == 0 → target -1.0
    closes = np.full(100, 100.0, dtype=np.float64)
    t = compute_vol_targets_batch(closes, forecast_horizon=10, start_idx=50)
    assert t.size > 0
    assert -1.0 in np.unique(t)
    assert set(np.unique(t)).issubset({-1.0, 0.0, 1.0})


def test_valid_mask_removes_negatives_and_bincount_is_safe():
    y = np.array([1.0, 0.0, -1.0, 1.0, -1.0, 0.0], dtype=np.float32)
    valid = y >= 0.0
    y_clean = y[valid]
    assert (y_clean >= 0).all()
    assert y_clean.tolist() == [1.0, 0.0, 1.0, 0.0]
    # The exact op that used to blow up must now succeed
    counts = np.bincount(y_clean.astype(int), minlength=2)
    assert counts.tolist() == [2, 2]


def test_xy_filter_stays_aligned():
    """Filtering X and y with the same boolean mask preserves row alignment."""
    X = np.arange(12, dtype=np.float32).reshape(6, 2)
    y = np.array([1.0, -1.0, 0.0, -1.0, 1.0, 0.0], dtype=np.float32)
    valid = y >= 0.0
    Xc, yc = X[valid], y[valid]
    assert Xc.shape == (4, 2)
    assert yc.shape == (4,)
    # rows 0,2,4,5 survived
    assert Xc[:, 0].tolist() == [0.0, 4.0, 8.0, 10.0]
