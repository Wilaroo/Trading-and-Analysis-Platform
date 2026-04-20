"""Tests for fractional_diff module.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_fractional_diff.py -v
"""
import numpy as np
import pytest

from services.ai_modules.fractional_diff import (
    _get_weights, _get_weights_ffd,
    frac_diff_ffd, find_min_d, compute_ffd_features,
)


def test_weights_start_at_one():
    w = _get_weights_ffd(0.5, threshold=1e-4)
    assert w[-1] == 1.0   # most-recent-bar weight is 1.0


def test_weights_ffd_truncates_at_threshold():
    w_loose = _get_weights_ffd(0.5, threshold=1e-2)
    w_tight = _get_weights_ffd(0.5, threshold=1e-6)
    # Tighter threshold → more weights retained
    assert len(w_tight) > len(w_loose)


def test_ffd_returns_nan_prefix():
    series = np.linspace(100, 200, 500)
    out = frac_diff_ffd(series, d=0.5, threshold=1e-4)
    # Should have some NaNs at the start (one per weight-window bar)
    n_nan = int(np.isnan(out).sum())
    assert n_nan > 0
    assert n_nan < 200


def test_ffd_on_random_walk_is_finite():
    rng = np.random.default_rng(0)
    closes = 100 + np.cumsum(rng.normal(0, 1, 1000))
    out = frac_diff_ffd(closes, d=0.4)
    valid = out[~np.isnan(out)]
    assert np.isfinite(valid).all()
    # FFD should have bounded variance (not blowing up)
    assert abs(float(valid.mean())) < 20.0
    assert float(valid.std()) < 50.0


def test_d_zero_is_identity():
    """d=0 should return the original series (w = [1])"""
    series = np.arange(100, dtype=np.float64)
    out = frac_diff_ffd(series, d=0.0, threshold=1e-8)
    # d=0 weight vector is just [1.0], so output = input at every position
    # (no NaNs except maybe first)
    valid = out[~np.isnan(out)]
    assert len(valid) >= 99
    # Elements should match input
    assert np.allclose(valid[-10:], series[-len(valid[-10:]):], atol=1e-6)


def test_find_min_d_returns_reasonable_value():
    rng = np.random.default_rng(1)
    # Build a trending series that needs SOME differentiation
    trend = np.arange(2000, dtype=np.float64) * 0.05
    noise = rng.normal(0, 1, 2000)
    closes = 100 + trend + np.cumsum(noise * 0.1)

    d = find_min_d(np.log(closes))
    assert 0.0 <= d <= 1.0
    # For a trending log-price, optimal d is typically 0.3–0.6
    # (not testing hard bounds since depends on random seed)


def test_compute_ffd_features_returns_expected_keys():
    rng = np.random.default_rng(2)
    closes = 100 + np.cumsum(rng.normal(0, 1, 500))
    feats = compute_ffd_features(closes)
    assert "ffd_close_adaptive" in feats
    assert "ffd_close_03" in feats
    assert "ffd_close_05" in feats
    assert "ffd_close_07" in feats
    assert "ffd_optimal_d" in feats
    assert 0.0 <= feats["ffd_optimal_d"] <= 1.0
    # All series should have same length as input
    for k in ("ffd_close_adaptive", "ffd_close_03", "ffd_close_05", "ffd_close_07"):
        assert len(feats[k]) == len(closes)


def test_d_cache_reuses_adaptive_d():
    closes = 100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 600))
    cache = {}
    compute_ffd_features(closes, d_cache=cache, cache_key="AAPL_1d")
    assert "AAPL_1d" in cache
    d1 = cache["AAPL_1d"]
    # Second call should use cache
    compute_ffd_features(closes, d_cache=cache, cache_key="AAPL_1d")
    assert cache["AAPL_1d"] == d1   # unchanged
