"""Unit tests for execution_guardrails (2026-04-21)."""
from services.execution_guardrails import (
    check_min_stop_distance, check_max_position_notional, run_all_guardrails,
)


# ── min_stop_distance ─────────────────────────────────────────────────────

def test_reject_absurd_uso_style_stop():
    """USO: entry 108.28, stop 108.31 (risk $0.03), ATR ≈ $1.00 → $0.30 threshold."""
    r = check_min_stop_distance(108.28, 108.31, atr_14=1.0)
    assert r.skip and "stop_too_tight" in r.reason


def test_allow_sane_stop_with_atr():
    """Entry 100, stop 98.5 (risk $1.50), ATR $2.0 → 0.3×ATR = $0.60 threshold."""
    r = check_min_stop_distance(100.0, 98.5, atr_14=2.0)
    assert r.allow


def test_fallback_pct_when_no_atr():
    """Without ATR, fall back to 10 bps minimum. 100 → needs ≥ $0.10."""
    assert check_min_stop_distance(100.0, 99.95).skip        # $0.05 < $0.10
    assert check_min_stop_distance(100.0, 99.85).allow       # $0.15 > $0.10


def test_invalid_prices_rejected():
    assert check_min_stop_distance(0, 0).skip
    assert check_min_stop_distance(100, 100).skip            # zero distance


# ── max_position_notional ─────────────────────────────────────────────────

def test_reject_oversized_position():
    """100k equity × 1% cap = $1k. 100 shares × $50 = $5k → reject."""
    r = check_max_position_notional(50.0, 100, 100_000.0)
    assert r.skip and "notional_over_cap" in r.reason


def test_allow_small_position():
    """100k × 1% = $1k. 10 shares × $50 = $500 → allow."""
    r = check_max_position_notional(50.0, 10, 100_000.0)
    assert r.allow


def test_no_equity_info_allows_through():
    """Don't block everything when equity feed is flaky."""
    r = check_max_position_notional(50.0, 100, None)
    assert r.allow


# ── run_all_guardrails ────────────────────────────────────────────────────

def test_all_allows_sane_trade():
    r = run_all_guardrails(100.0, 98.5, 10, atr_14=2.0, account_equity=100_000.0)
    assert r.allow


def test_all_stops_on_first_failure():
    """Bad stop distance should be reported even though notional is also bad."""
    r = run_all_guardrails(108.28, 108.31, 100_000, atr_14=1.0, account_equity=100_000)
    assert r.skip and "stop_too_tight" in r.reason   # first check trips
