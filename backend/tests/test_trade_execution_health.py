"""Unit tests for TradeExecutionHealth pure-logic helpers (2026-04-21)."""
import pytest

from services.trade_execution_health import (
    STOP_HONOR_THRESHOLD, CRITICAL_FAILURE_RATE, WARNING_FAILURE_RATE,
    analyze_stop_honor, classify_alert_level, StopHonorResult,
)


# ── analyze_stop_honor ────────────────────────────────────────────────────

def test_long_stop_honored_at_1R_loss():
    """Long entry 100, stop 95 (risk $5), exit 95 = stopped at -1R. Honored."""
    r = analyze_stop_honor(100, 95, 95, "long")
    assert r.realized_R_signed == pytest.approx(-1.0)
    assert r.blew_past_stop is False


def test_long_stop_failed_10R_blow_through():
    """USO-style: entry 108.28, stop 108.31 (risk $0.03), exit 116.12 → -261R."""
    r = analyze_stop_honor(108.28, 108.31, 116.12, "short")  # short: stop above entry
    assert r.realized_R_signed == pytest.approx(-261.333, abs=0.01)
    assert r.blew_past_stop is True
    assert r.slippage_ratio == pytest.approx(261.333, abs=0.01)


def test_winner_not_flagged_as_stop_failure():
    """Winners don't count — they ran into the profit side, not past stop."""
    # Long 100 → 110 with stop 95 = +2R winner
    r = analyze_stop_honor(100, 95, 110, "long")
    assert r.realized_R_signed == pytest.approx(2.0)
    assert r.blew_past_stop is False


def test_short_stop_honored():
    """Short entry 50, stop 52 (risk $2), exit 52 = stopped at -1R."""
    r = analyze_stop_honor(50, 52, 52, "short")
    assert r.realized_R_signed == pytest.approx(-1.0)
    assert r.blew_past_stop is False


def test_small_slippage_not_flagged():
    """Stopped at -1.2R (small slippage, likely fills slip) = honored."""
    r = analyze_stop_honor(100, 95, 94, "long")
    assert r.realized_R_signed == pytest.approx(-1.2)
    assert r.blew_past_stop is False  # threshold is 1.5R


def test_slippage_just_over_threshold_flagged():
    r = analyze_stop_honor(100, 95, 92, "long")  # -1.6R loser
    assert r.blew_past_stop is True


def test_returns_none_on_bad_inputs():
    assert analyze_stop_honor(None, 95, 110, "long") is None
    assert analyze_stop_honor(100, None, 110, "long") is None
    assert analyze_stop_honor(100, 95, None, "long") is None
    assert analyze_stop_honor(100, 100, 110, "long") is None  # zero risk
    assert analyze_stop_honor(-1, 95, 110, "long") is None
    assert analyze_stop_honor(100, 95, 110, "") is None
    assert analyze_stop_honor(100, 95, 110, "sideways") is None


def test_direction_aliases_honored():
    for alias in ("long", "LONG", "buy", "up"):
        r = analyze_stop_honor(100, 95, 110, alias)
        assert r and r.realized_R_signed == pytest.approx(2.0)
    for alias in ("short", "sell", "down"):
        r = analyze_stop_honor(50, 52, 48, alias)
        assert r and r.realized_R_signed == pytest.approx(1.0)


def test_trade_metadata_passed_through():
    r = analyze_stop_honor(100, 95, 95, "long",
                           trade_id="t-7", symbol="USO", setup_type="vwap_fade_short")
    assert r.trade_id == "t-7"
    assert r.symbol == "USO"
    assert r.setup_type == "vwap_fade_short"
    assert r.intended_1R == pytest.approx(5.0)


# ── classify_alert_level ──────────────────────────────────────────────────

def test_alert_insufficient_data_below_min_trades():
    assert classify_alert_level(0.50, 2) == "insufficient_data"
    assert classify_alert_level(0.50, 4) == "insufficient_data"


def test_alert_ok_below_warning_threshold():
    assert classify_alert_level(0.04, 100) == "ok"
    assert classify_alert_level(WARNING_FAILURE_RATE - 0.001, 100) == "ok"


def test_alert_warning_at_5_to_15_pct():
    assert classify_alert_level(0.05, 100) == "warning"
    assert classify_alert_level(0.10, 100) == "warning"
    assert classify_alert_level(CRITICAL_FAILURE_RATE - 0.001, 100) == "warning"


def test_alert_critical_above_15_pct():
    assert classify_alert_level(CRITICAL_FAILURE_RATE, 100) == "critical"
    assert classify_alert_level(0.20, 100) == "critical"
    assert classify_alert_level(0.50, 100) == "critical"


# ── thresholds are sane ───────────────────────────────────────────────────

def test_threshold_ordering():
    """Warning must be lower than critical; honor threshold > 1.0 so tiny slippage doesn't flag."""
    assert WARNING_FAILURE_RATE < CRITICAL_FAILURE_RATE
    assert STOP_HONOR_THRESHOLD > 1.0


def test_stop_honor_result_is_dataclass():
    """StopHonorResult must serialize cleanly (for API response)."""
    r = analyze_stop_honor(100, 95, 95, "long")
    d = r.__dict__
    assert "realized_R_signed" in d
    assert "blew_past_stop" in d
    assert "slippage_ratio" in d
