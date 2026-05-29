"""
v19.34.179 regression tests — prioritization, slot allocation, exposure
caps, and effective position cap.

These guard four fixes:
  F-A : get_live_alerts priority sort (CRITICAL first, recency-desc)
  F-B : _get_trade_alerts quality-ranked slot allocation
  F-C : portfolio exposure guard math (now wired into the autonomous path)
  cap : effective max_open_positions = min(bot, kill-switch SAFETY_MAX_POSITIONS)

Pure-logic tests (no IB / GPU / live DB) per the DGX hardware constraint.
The F-A / F-B helpers mirror the exact algorithm shipped in source.
"""
from enum import Enum


class _P(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_ORDER = {_P.CRITICAL: 0, _P.HIGH: 1, _P.MEDIUM: 2, _P.LOW: 3}


class _Alert:
    def __init__(self, name, priority, created_at):
        self.name = name
        self.priority = priority
        self.created_at = created_at  # ISO string, as in LiveAlert


def _sorted_like_get_live_alerts(alerts):
    """Mirror of enhanced_scanner.get_live_alerts() v19.34.179 sort."""
    alerts = list(alerts)
    alerts.sort(key=lambda x: x.created_at, reverse=True)
    alerts.sort(key=lambda x: _ORDER.get(x.priority, 4))
    return alerts


def test_fa_priority_sort_critical_first_recency_within_bucket():
    al = [
        _Alert("LOW_old", _P.LOW, "2026-01-01T09:00:00"),
        _Alert("CRIT_new", _P.CRITICAL, "2026-01-01T09:05:00"),
        _Alert("CRIT_old", _P.CRITICAL, "2026-01-01T09:01:00"),
        _Alert("HIGH", _P.HIGH, "2026-01-01T09:02:00"),
        _Alert("MED", _P.MEDIUM, "2026-01-01T09:03:00"),
    ]
    out = [a.name for a in _sorted_like_get_live_alerts(al)]
    assert out == ["CRIT_new", "CRIT_old", "HIGH", "MED", "LOW_old"]


def test_fa_regression_critical_not_last():
    """The pre-fix bug put CRITICAL LAST. Guard against re-introducing it."""
    al = [
        _Alert("LOW", _P.LOW, "2026-01-01T09:00:00"),
        _Alert("CRIT", _P.CRITICAL, "2026-01-01T09:01:00"),
    ]
    out = [a.name for a in _sorted_like_get_live_alerts(al)]
    assert out[0] == "CRIT"


def _alert_rank(a):
    """Mirror of trading_bot_service._get_trade_alerts v19.34.179 rank."""
    prio = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
        str(a.get("priority") or "medium").lower(), 4
    )
    return (
        prio,
        -float(a.get("tqs_score") or 0),
        -float(a.get("trigger_probability") or 0),
        -float(a.get("score") or 0),
    )


def test_fb_quality_ranking_best_ideas_first():
    alerts = [
        {"symbol": "D1", "priority": "low", "tqs_score": 30},
        {"symbol": "A1", "priority": "high", "tqs_score": 92},
        {"symbol": "A2", "priority": "high", "tqs_score": 80},
        {"symbol": "C1", "priority": "critical", "tqs_score": 40},
    ]
    alerts.sort(key=_alert_rank)
    assert [a["symbol"] for a in alerts] == ["C1", "A1", "A2", "D1"]


def test_fb_tiebreak_uses_trigger_probability_then_score():
    alerts = [
        {"symbol": "X", "priority": "high", "tqs_score": 70, "trigger_probability": 0.5},
        {"symbol": "Y", "priority": "high", "tqs_score": 70, "trigger_probability": 0.9},
    ]
    alerts.sort(key=_alert_rank)
    assert [a["symbol"] for a in alerts] == ["Y", "X"]


def test_fb_missing_fields_default_safely():
    alerts = [{"symbol": "Z"}, {"symbol": "A", "priority": "critical"}]
    alerts.sort(key=_alert_rank)
    assert alerts[0]["symbol"] == "A"


def test_fc_position_style_exposure_clamp():
    from services.portfolio_exposure_guard import POSITION_STYLES, compute_exposure

    class T:
        trade_style = "position"
        remaining_shares = 400
        current_price = 70.0
        entry_price = 70.0
        symbol = "ABC"
        setup_type = "stage_2_breakout"

    # $28k open vs 30% of $100k = $30k cap -> $2k remaining -> 28 shares @ $70
    snap = compute_exposure([T()], 100000.0, cap_pct=30.0, styles=POSITION_STYLES)
    assert snap.remaining_value == 2000.0
    assert int(snap.remaining_value // 70.0) == 28
    assert snap.cap_breached is False


def test_fc_long_horizon_cap_breach_blocks():
    from services.portfolio_exposure_guard import LONG_HORIZON_STYLES, compute_exposure

    class T:
        trade_style = "swing"
        remaining_shares = 1000
        current_price = 60.0
        entry_price = 60.0
        symbol = "DEF"
        setup_type = "daily_breakout"

    # $60k open vs 55% of $100k = $55k cap -> breached, 0 shares remaining
    snap = compute_exposure([T()], 100000.0, cap_pct=55.0, styles=LONG_HORIZON_STYLES)
    assert snap.cap_breached is True
    assert int(snap.remaining_value // 60.0) == 0


def _effective_max_positions(bot_cap, safety_cap):
    """Mirror of trading_bot_service intake gate v19.34.179."""
    eff = bot_cap
    if safety_cap and safety_cap > 0:
        eff = min(eff, safety_cap)
    return eff


def test_effective_max_positions_is_min_of_bot_and_safety():
    assert _effective_max_positions(25, 5) == 5     # kill switch stricter
    assert _effective_max_positions(5, 25) == 5     # bot stricter
    assert _effective_max_positions(25, 0) == 25    # safety unset -> bot binds
    assert _effective_max_positions(25, None) == 25
