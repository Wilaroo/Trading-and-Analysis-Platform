"""
v19.34.319 — NO-PEEK gap-fill target/feature pins.

The v314 sampler leaked: bar i (session open) was included in BOTH the feature
row and the fill window, so a gap that filled DURING the open bar was trivially
readable (leak audit: 76.2% of 15m fills land in bar i → inflated ~94.6% acc).

v319 decides AT THE OPEN: the fill target is evaluated over [i+1, i+w]
(excluding the open bar) and the two bar-i-derived gap features are neutralized.

These tests pin the pure logic (no DB / GPU / IB needed).
"""
import numpy as np

from services.ai_modules.gap_fill_model import (
    compute_gap_features,
    compute_gap_fill_target,
)


# --- helpers ---------------------------------------------------------------

def _daily_ctx(n=25, price=100.0):
    """Most-recent-first daily arrays for compute_gap_features."""
    closes = np.full(n, price, dtype=float)
    highs = np.full(n, price * 1.01, dtype=float)
    lows = np.full(n, price * 0.99, dtype=float)
    vols = np.full(n, 1_000_000.0, dtype=float)
    return closes, highs, lows, vols


# --- target window: bar i must be excluded ---------------------------------

def test_fill_only_in_open_bar_is_NOT_a_nopeek_fill():
    """Gap-up fills (low <= prev_close) ONLY in the open bar i; the bars AFTER
    the open never return to prev_close. No-peek slice [i+1:i+1+w] => 0;
    the old leaky slice [i:i+w] => 1."""
    prev_close = 100.0
    w = 3
    # window starting at the open bar i:
    #   i   : low dips to 99.5 (FILLS prev_close) <- leak
    #   i+1 : stays above (no fill)
    #   i+2 : stays above (no fill)
    #   i+3 : stays above (no fill)
    lows = np.array([99.5, 101.0, 101.2, 101.3])
    highs = np.array([102.0, 102.0, 102.2, 102.3])

    # leaky (old) target includes bar i -> 1
    assert compute_gap_fill_target(lows[0:w], highs[0:w], prev_close, 1.0, w) == 1
    # no-peek (v319) target excludes bar i -> 0
    assert compute_gap_fill_target(lows[1:1 + w], highs[1:1 + w], prev_close, 1.0, w) == 0


def test_fill_after_open_bar_is_a_nopeek_fill():
    """Gap-up that fills at i+2 (after the open bar) => no-peek target 1."""
    prev_close = 100.0
    w = 3
    lows = np.array([101.0, 101.0, 99.4, 101.3])  # dips at i+2
    highs = np.array([102.0, 102.0, 102.0, 102.0])
    assert compute_gap_fill_target(lows[1:1 + w], highs[1:1 + w], prev_close, 1.0, w) == 1


def test_gap_down_nopeek_open_bar_excluded():
    """Gap-down fills (high >= prev_close) only in the open bar => no-peek 0."""
    prev_close = 100.0
    w = 3
    highs = np.array([100.6, 99.0, 98.8, 98.7])  # only bar i reaches prev_close
    lows = np.array([97.0, 97.0, 96.8, 96.7])
    assert compute_gap_fill_target(lows[0:w], highs[0:w], prev_close, -1.0, w) == 1      # leaky
    assert compute_gap_fill_target(lows[1:1 + w], highs[1:1 + w], prev_close, -1.0, w) == 0  # no-peek


# --- feature neutralization: no bar-i close/volume -------------------------

def test_premarket_momentum_zero_when_close_equals_open():
    """v319 passes today_close_bar1=today_open => premarket_momentum must be 0."""
    closes, highs, lows, vols = _daily_ctx()
    feats = compute_gap_features(
        today_open=101.0,
        today_close_bar1=101.0,   # == open (no-peek neutralization)
        today_volume_bar1=0.0,    # no open-bar volume known yet
        prev_day_open=99.0,
        prev_day_high=100.5,
        prev_day_low=98.5,
        prev_day_close=100.0,
        daily_closes=closes, daily_highs=highs, daily_lows=lows, daily_volumes=vols,
    )
    assert feats["premarket_momentum"] == 0.0


def test_volume_ratio_zero_when_open_bar_volume_unknown():
    """today_volume_bar1=0.0 => gap_volume_ratio is 0 (not a bar-i leak)."""
    closes, highs, lows, vols = _daily_ctx()
    feats = compute_gap_features(
        today_open=101.0,
        today_close_bar1=101.0,
        today_volume_bar1=0.0,
        prev_day_open=99.0,
        prev_day_high=100.5,
        prev_day_low=98.5,
        prev_day_close=100.0,
        daily_closes=closes, daily_highs=highs, daily_lows=lows, daily_volumes=vols,
    )
    assert feats["gap_volume_ratio"] == 0.0


def test_gap_size_pct_still_uses_known_open():
    """gap_size_pct only needs the open price (known AT THE OPEN) — must survive."""
    closes, highs, lows, vols = _daily_ctx()
    feats = compute_gap_features(
        today_open=102.0,
        today_close_bar1=102.0,
        today_volume_bar1=0.0,
        prev_day_open=99.0,
        prev_day_high=100.5,
        prev_day_low=98.5,
        prev_day_close=100.0,
        daily_closes=closes, daily_highs=highs, daily_lows=lows, daily_volumes=vols,
    )
    assert abs(feats["gap_size_pct"] - 0.02) < 1e-9
    assert feats["gap_direction"] == 1.0
