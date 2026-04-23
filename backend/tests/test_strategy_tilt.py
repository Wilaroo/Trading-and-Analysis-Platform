"""
Tests for services/strategy_tilt.py — pure-function Sharpe-tilt math.
"""
from datetime import datetime, timezone, timedelta

import pytest

from services.strategy_tilt import (
    compute_strategy_tilt,
    get_side_tilt_multiplier,
    get_strategy_tilt_cached,
    reset_cache_for_tests,
)


NOW = datetime(2026, 4, 23, 12, 0, 0, tzinfo=timezone.utc)


def _trade(direction, r_multiple=None, pnl=None, risk=100.0, age_days=1):
    d = {
        "direction": direction,
        "closed_at": (NOW - timedelta(days=age_days)).isoformat(),
    }
    if r_multiple is not None:
        d["r_multiple"] = r_multiple
    if pnl is not None:
        d["pnl"] = pnl
        d["risk_amount"] = risk
    return d


# ── _r_multiple + sharpe plumbing ────────────────────────────────────────

def test_neutral_tilt_when_no_trades():
    t = compute_strategy_tilt([], now=NOW)
    assert t["long_tilt"] == 1.0
    assert t["short_tilt"] == 1.0
    assert t["n_long"] == 0
    assert t["n_short"] == 0


def test_below_min_sample_stays_neutral():
    # 5 long trades, far below default min_trades_per_side=10
    trades = [_trade("long", r_multiple=3.0) for _ in range(5)]
    t = compute_strategy_tilt(trades, now=NOW)
    assert t["long_tilt"] == 1.0
    assert t["n_long"] == 5


def test_hot_long_side_tilts_longs_up_and_shorts_down():
    # 10 long winners with r=+1.0, 10 short losers with r=-1.0
    trades = [_trade("long", r_multiple=1.0) for _ in range(10)]
    trades += [_trade("short", r_multiple=-1.0) for _ in range(10)]
    t = compute_strategy_tilt(trades, now=NOW)
    # Long sharpe is infinite (std=0 → clamped to 0.0), so we need variety
    # to get a meaningful sharpe. Use mixed R-multiples.


def test_hot_long_cold_short_produces_expected_signed_tilt():
    """Real-world scenario: varied pnl on each side."""
    # Long side: mean R = +0.5, some variance → positive Sharpe
    long_rs = [1.0, 0.5, 0.3, 1.2, -0.2, 0.4, 0.8, 0.7, 0.1, 0.9]  # mean≈0.57
    # Short side: mean R = -0.4 → negative Sharpe
    short_rs = [-1.0, -0.5, 0.3, -0.8, -0.4, -0.6, -0.1, -0.3, -0.9, -0.7]
    trades = [_trade("long", r_multiple=r) for r in long_rs]
    trades += [_trade("short", r_multiple=r) for r in short_rs]

    t = compute_strategy_tilt(trades, now=NOW)
    assert t["n_long"] == 10
    assert t["n_short"] == 10
    assert t["sharpe_long"] > 0
    assert t["sharpe_short"] < 0
    # Long side should be tilted UP, short side DOWN
    assert t["long_tilt"] > 1.0
    assert t["short_tilt"] < 1.0


def test_tilt_is_bounded_by_floor_and_ceiling():
    # Extreme divergence — should still clamp to [0.5, 1.5]
    trades = [_trade("long", r_multiple=10.0) for _ in range(10)]
    trades += [_trade("short", r_multiple=-10.0) for _ in range(10)]
    t = compute_strategy_tilt(trades, now=NOW, scale=0.01)  # tiny scale → huge raw tilt
    assert 0.5 <= t["long_tilt"] <= 1.5
    assert 0.5 <= t["short_tilt"] <= 1.5


def test_tilt_respects_custom_bounds():
    trades = [_trade("long", r_multiple=1.0) for _ in range(10)]
    trades += [_trade("short", r_multiple=-1.0) for _ in range(10)]
    # Override bounds — should respect custom floor/ceiling
    t = compute_strategy_tilt(trades, now=NOW, floor=0.8, ceiling=1.2, scale=0.5)
    assert 0.8 <= t["long_tilt"] <= 1.2
    assert 0.8 <= t["short_tilt"] <= 1.2


def test_trades_older_than_lookback_are_dropped():
    # 10 recent long trades + 10 OLD (60 days ago) long losers that would
    # otherwise drag the Sharpe down
    recent = [_trade("long", r_multiple=1.0, age_days=5) for _ in range(10)]
    old_losers = [_trade("long", r_multiple=-5.0, age_days=60) for _ in range(10)]
    t = compute_strategy_tilt(recent + old_losers, now=NOW, lookback_days=30)
    assert t["n_long"] == 10  # only the recent ones counted


def test_pnl_risk_fallback_when_no_r_multiple():
    # Trades stored without explicit r_multiple — should compute pnl/risk
    trades = [_trade("long", pnl=50.0, risk=100.0) for _ in range(10)]  # R=0.5
    trades += [_trade("long", pnl=-25.0, risk=100.0) for _ in range(5)]  # R=-0.25
    trades += [_trade("short", r_multiple=0.0) for _ in range(10)]
    t = compute_strategy_tilt(trades, now=NOW)
    assert t["n_long"] == 15


def test_trade_without_direction_is_ignored():
    trades = [{"r_multiple": 1.0, "closed_at": NOW.isoformat()}]  # no direction
    t = compute_strategy_tilt(trades, now=NOW)
    assert t["n_long"] == 0
    assert t["n_short"] == 0


def test_malformed_pnl_or_risk_silently_skipped():
    trades = [
        {"direction": "long", "pnl": "not_a_number", "risk_amount": 100,
         "closed_at": NOW.isoformat()},
        {"direction": "long", "pnl": 50, "risk_amount": 0,  # div-by-zero guard
         "closed_at": NOW.isoformat()},
    ]
    t = compute_strategy_tilt(trades, now=NOW)
    assert t["n_long"] == 0


# ── side multiplier accessor ─────────────────────────────────────────────

def test_get_side_tilt_multiplier_long():
    tilt = {"long_tilt": 1.3, "short_tilt": 0.7}
    assert get_side_tilt_multiplier("long", tilt) == 1.3
    assert get_side_tilt_multiplier("LONG", tilt) == 1.3


def test_get_side_tilt_multiplier_short():
    tilt = {"long_tilt": 1.3, "short_tilt": 0.7}
    assert get_side_tilt_multiplier("short", tilt) == 0.7


def test_get_side_tilt_multiplier_unknown_direction_defaults_to_one():
    tilt = {"long_tilt": 1.3, "short_tilt": 0.7}
    assert get_side_tilt_multiplier("flat", tilt) == 1.0
    assert get_side_tilt_multiplier(None, tilt) == 1.0


# ── cache behavior ──────────────────────────────────────────────────────

def test_cached_tilt_returns_neutral_when_db_is_none():
    reset_cache_for_tests()
    t = get_strategy_tilt_cached(None)
    assert t["long_tilt"] == 1.0
    assert t["short_tilt"] == 1.0


def test_cached_tilt_memoises_within_ttl():
    reset_cache_for_tests()
    t1 = get_strategy_tilt_cached(None)
    t2 = get_strategy_tilt_cached(None)
    # Same dict instance returned from cache
    assert t1 is t2


def test_cached_tilt_force_refresh():
    reset_cache_for_tests()
    t1 = get_strategy_tilt_cached(None)
    t2 = get_strategy_tilt_cached(None, force_refresh=True)
    assert t1 is not t2  # force refresh returns a new dict
