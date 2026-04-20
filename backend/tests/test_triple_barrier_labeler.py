"""
Tests for triple-barrier labeler.
Run: cd /app && python -m pytest backend/tests/test_triple_barrier_labeler.py -v
"""

import numpy as np
import pytest

from backend.services.ai_modules.triple_barrier_labeler import (
    triple_barrier_label_single,
    triple_barrier_labels,
    label_to_class_index,
    class_index_to_direction,
    label_distribution,
    atr,
)


def _make_rising_bars(n=50, slope=0.5, noise=0.1, start=100.0):
    """Bars that trend up with small noise — upper barrier should hit first."""
    np.random.seed(0)
    closes = start + np.arange(n) * slope + np.random.randn(n) * noise
    highs = closes + np.abs(np.random.randn(n) * noise) + 0.2
    lows = closes - np.abs(np.random.randn(n) * noise) - 0.2
    return highs.astype(np.float64), lows.astype(np.float64), closes.astype(np.float64)


def _make_falling_bars(n=50, slope=-0.5, noise=0.1, start=100.0):
    np.random.seed(1)
    closes = start + np.arange(n) * slope + np.random.randn(n) * noise
    highs = closes + np.abs(np.random.randn(n) * noise) + 0.2
    lows = closes - np.abs(np.random.randn(n) * noise) - 0.2
    return highs.astype(np.float64), lows.astype(np.float64), closes.astype(np.float64)


def test_upper_barrier_hit_in_trending_up_market():
    highs, lows, closes = _make_rising_bars(n=50, slope=0.5, noise=0.05)
    label = triple_barrier_label_single(
        highs, lows, closes,
        entry_idx=20,
        pt_atr_mult=1.0, sl_atr_mult=1.0,
        max_bars=20,
        atr_value=0.5,
    )
    assert label == 1, f"Expected +1 (upper barrier hit), got {label}"


def test_lower_barrier_hit_in_trending_down_market():
    highs, lows, closes = _make_falling_bars(n=50, slope=-0.5, noise=0.05)
    label = triple_barrier_label_single(
        highs, lows, closes,
        entry_idx=20,
        pt_atr_mult=1.0, sl_atr_mult=1.0,
        max_bars=20,
        atr_value=0.5,
    )
    assert label == -1, f"Expected -1 (lower barrier hit), got {label}"


def test_time_barrier_in_flat_market():
    n = 50
    closes = np.full(n, 100.0, dtype=np.float64)
    closes += np.random.RandomState(42).randn(n) * 0.05  # tiny noise
    highs = closes + 0.02
    lows = closes - 0.02
    label = triple_barrier_label_single(
        highs, lows, closes,
        entry_idx=20,
        pt_atr_mult=5.0, sl_atr_mult=5.0,  # wide barriers
        max_bars=10,
        atr_value=0.1,
    )
    assert label == 0, f"Expected 0 (time barrier), got {label}"


def test_returns_zero_when_atr_missing_or_invalid():
    highs, lows, closes = _make_rising_bars()
    assert triple_barrier_label_single(highs, lows, closes, 10, atr_value=None) == 0
    assert triple_barrier_label_single(highs, lows, closes, 10, atr_value=np.nan) == 0
    assert triple_barrier_label_single(highs, lows, closes, 10, atr_value=0.0) == 0
    assert triple_barrier_label_single(highs, lows, closes, 10, atr_value=-1.0) == 0


def test_returns_zero_when_entry_near_end():
    highs, lows, closes = _make_rising_bars(n=30)
    # entry at last bar → no future data
    assert triple_barrier_label_single(highs, lows, closes, 29, atr_value=0.5) == 0


def test_batch_labeler_distribution_balanced_in_mixed_regime():
    """Random walk should produce roughly balanced labels (not 100% one class)."""
    np.random.seed(7)
    n = 500
    closes = 100 + np.cumsum(np.random.randn(n) * 0.3)
    highs = closes + np.abs(np.random.randn(n) * 0.2)
    lows = closes - np.abs(np.random.randn(n) * 0.2)
    labels = triple_barrier_labels(
        highs.astype(np.float64), lows.astype(np.float64), closes.astype(np.float64),
        pt_atr_mult=2.0, sl_atr_mult=1.0,
        max_bars=15,
        atr_period=14,
    )
    dist = label_distribution(labels)
    # Sanity: no class should be 100% dominant (that was the old binary-target bug)
    assert dist["down"] < 0.95 and dist["flat"] < 0.95 and dist["up"] < 0.95, dist
    assert dist["total"] > 0


def test_class_index_mapping_round_trip():
    for raw in (-1, 0, 1):
        idx = label_to_class_index(raw)
        assert idx in (0, 1, 2)
    assert label_to_class_index(-1) == 0
    assert label_to_class_index(0) == 1
    assert label_to_class_index(1) == 2
    assert class_index_to_direction(0) == "down"
    assert class_index_to_direction(1) == "flat"
    assert class_index_to_direction(2) == "up"


def test_atr_produces_positive_values_after_warmup():
    highs, lows, closes = _make_rising_bars(n=100)
    a = atr(highs, lows, closes, period=14)
    assert np.all(np.isnan(a[:13])), "First 13 values should be NaN"
    assert np.all(np.isfinite(a[14:])), "Rest should be finite"
    assert np.all(a[14:] > 0), "ATR must be positive"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
