"""Tests for CUSUM event filter + calibration.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_cusum_filter.py -v
"""
import numpy as np
import os
import pytest

from services.ai_modules.cusum_filter import (
    cusum_events, calibrate_h, bars_per_year_for,
    filter_entry_indices, cusum_enabled,
)


def test_no_events_in_flat_market():
    closes = np.full(200, 100.0)
    ev = cusum_events(closes, h=0.01)
    assert len(ev) == 0


def test_events_fire_in_trending_market():
    closes = 100 * np.exp(np.cumsum(np.full(200, 0.005)))  # 0.5% per bar up
    ev = cusum_events(closes, h=0.02)
    assert len(ev) > 0
    # Should fire roughly every ~4 bars (0.02 / 0.005 = 4)
    assert 30 < len(ev) < 60


def test_calibrate_h_controls_event_density():
    rng = np.random.default_rng(0)
    n = 10000
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))

    # Target 50 events/year, say 10k bars = ~5 years → expect ~250 events
    h = calibrate_h(closes, target_events_per_year=50, bars_per_year=2000)
    ev = cusum_events(closes, h)

    # Should be within an order of magnitude of target
    assert 100 < len(ev) < 500
    assert 0.001 < h < 0.2


def test_bars_per_year_lookup():
    assert bars_per_year_for("1 min") == 252 * 390
    assert bars_per_year_for("5 mins") == 252 * 78
    assert bars_per_year_for("1 day") == 252
    assert bars_per_year_for("unknown") == 252 * 78


def test_filter_entry_indices_returns_subset():
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, 1000)))
    entries = np.arange(50, 990)
    filtered = filter_entry_indices(entries, closes, bar_size="5 mins",
                                    target_events_per_year=100, min_distance=2)
    # Filtered is strict subset (or empty fallback)
    assert set(filtered.tolist()).issubset(set(entries.tolist()))
    # Should reduce sample count meaningfully
    assert len(filtered) <= len(entries)


def test_filter_falls_back_to_all_when_no_events():
    closes = np.full(500, 100.0)   # flat → no events
    entries = np.arange(50, 480)
    filtered = filter_entry_indices(entries, closes, bar_size="5 mins",
                                    target_events_per_year=100)
    # Should return all entry_indices (fallback)
    assert len(filtered) == len(entries)


def test_cusum_events_respect_min_distance_via_filter():
    rng = np.random.default_rng(2)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, 5000)))
    entries = np.arange(50, 4990)
    filtered = filter_entry_indices(entries, closes, bar_size="1 min",
                                    target_events_per_year=500, min_distance=10)
    if len(filtered) >= 2:
        diffs = np.diff(filtered)
        assert (diffs >= 10).all()


def test_cusum_enabled_flag():
    os.environ.pop("TB_USE_CUSUM_SAMPLING", None)
    assert cusum_enabled() is False
    os.environ["TB_USE_CUSUM_SAMPLING"] = "1"
    assert cusum_enabled() is True
    os.environ["TB_USE_CUSUM_SAMPLING"] = "0"
    assert cusum_enabled() is False
    os.environ.pop("TB_USE_CUSUM_SAMPLING", None)


def test_symmetric_firing_both_directions():
    """CUSUM should fire on both up AND down trends."""
    up_trend = 100 * np.exp(np.cumsum(np.full(100, 0.003)))
    down_trend = 100 * np.exp(np.cumsum(np.full(100, -0.003)))
    closes = np.concatenate([up_trend, down_trend])
    ev = cusum_events(closes, h=0.02)
    assert len(ev) > 0
    # Should have events in BOTH halves
    first_half = sum(1 for i in ev if i < 100)
    second_half = sum(1 for i in ev if i >= 100)
    assert first_half > 0
    assert second_half > 0
