"""
Tests for the after-hours carry-forward ranker
(`enhanced_scanner._rank_carry_forward_setups_for_tomorrow`) and
the next-market-open helper (`_next_market_open_iso`).

Operator request 2026-04-28: *"the scanner should now recognize that
its after hours and should be scanning setups that it found today
that might be ready for tomorrow when the market opens."*
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest


def _make_alert(symbol, setup_type, direction, tqs, grade, headline=""):
    """Build a LiveAlert with the canonical dataclass shape."""
    from services.enhanced_scanner import LiveAlert, AlertPriority

    pri = AlertPriority.HIGH if tqs >= 70 else AlertPriority.MEDIUM if tqs >= 60 else AlertPriority.LOW
    return LiveAlert(
        id=f"id_{symbol}_{setup_type}",
        symbol=symbol,
        setup_type=setup_type,
        strategy_name=setup_type,
        direction=direction,
        priority=pri,
        current_price=100.0,
        trigger_price=100.0,
        stop_loss=98.0,
        target=104.0,
        risk_reward=2.0,
        trigger_probability=0.7,
        win_probability=0.65,
        minutes_to_trigger=0,
        headline=headline or f"{symbol} {setup_type}",
        reasoning=["test reasoning"],
        time_window="MIDDAY",
        market_regime="neutral",
        tqs_score=tqs,
        tqs_grade=grade,
    )


@pytest.fixture
def scanner_with_alerts():
    """Build an EnhancedBackgroundScanner pre-seeded with today's
    intraday alerts in `_live_alerts` and a fake Mongo."""
    from services.enhanced_scanner import EnhancedBackgroundScanner

    s = EnhancedBackgroundScanner()
    s.db = MagicMock()
    s.db["live_alerts"].find.return_value.sort.return_value.limit.return_value = []

    s._live_alerts = {
        "a1": _make_alert("NVDA", "relative_strength_leader", "long", 82, "A",
                          headline="RS LEADER NVDA +6.8%"),
        "a2": _make_alert("AAPL", "vwap_fade", "short", 66, "B",
                          headline="AAPL fading VWAP"),
        "a3": _make_alert("XYZ", "orb", "long", 42, "D",
                          headline="XYZ low-quality ORB"),
    }
    return s


@pytest.mark.asyncio
async def test_carry_forward_promotes_high_quality_continuation(scanner_with_alerts):
    s = scanner_with_alerts
    promoted = []
    async def _capture(alert):
        promoted.append(alert)
    s._process_new_alert = _capture

    await s._rank_carry_forward_setups_for_tomorrow()

    promoted_symbols = [a.symbol for a in promoted]
    assert "NVDA" in promoted_symbols, "high-quality RS leader must carry forward"
    nvda = next(a for a in promoted if a.symbol == "NVDA")
    assert nvda.setup_type == "day_2_continuation"
    assert nvda.tqs_score >= 85  # 82 + 5 carry-forward bonus
    assert "Day-2 continuation" in nvda.reasoning[0]
    assert nvda.expires_at is not None  # tomorrow's open


@pytest.mark.asyncio
async def test_carry_forward_promotes_fade_as_gap_fill(scanner_with_alerts):
    s = scanner_with_alerts
    promoted = []
    async def _capture(alert):
        promoted.append(alert)
    s._process_new_alert = _capture

    await s._rank_carry_forward_setups_for_tomorrow()

    aapl = [a for a in promoted if a.symbol == "AAPL"]
    assert aapl, "fade alert with TQS 66 must carry forward"
    assert aapl[0].setup_type == "gap_fill_open"
    assert "gap-fill" in aapl[0].reasoning[0]


@pytest.mark.asyncio
async def test_carry_forward_drops_low_quality_alerts(scanner_with_alerts):
    s = scanner_with_alerts
    promoted = []
    async def _capture(alert):
        promoted.append(alert)
    s._process_new_alert = _capture

    await s._rank_carry_forward_setups_for_tomorrow()

    promoted_symbols = [a.symbol for a in promoted]
    assert "XYZ" not in promoted_symbols, (
        "TQS 42 must NOT carry forward — quality bar is 60+"
    )


@pytest.mark.asyncio
async def test_carry_forward_handles_no_alerts(scanner_with_alerts):
    s = scanner_with_alerts
    s._live_alerts = {}
    s.db["live_alerts"].find.return_value.sort.return_value.limit.return_value = []

    promoted = []
    async def _capture(alert):
        promoted.append(alert)
    s._process_new_alert = _capture

    await s._rank_carry_forward_setups_for_tomorrow()
    assert promoted == []


@pytest.mark.asyncio
async def test_carry_forward_is_capped_at_top_10(scanner_with_alerts):
    s = scanner_with_alerts
    s._live_alerts = {
        f"a{i}": _make_alert(
            f"S{i:02}", "relative_strength_leader", "long",
            70 + (i % 25), "B",
        )
        for i in range(50)
    }
    promoted = []
    async def _capture(alert):
        promoted.append(alert)
    s._process_new_alert = _capture

    await s._rank_carry_forward_setups_for_tomorrow()
    assert len(promoted) == 10, f"expected top 10, got {len(promoted)}"


def test_next_market_open_skips_weekend(scanner_with_alerts):
    s = scanner_with_alerts
    next_open = s._next_market_open_iso()
    assert next_open.tzinfo is not None
    from zoneinfo import ZoneInfo
    et = next_open.astimezone(ZoneInfo("America/New_York"))
    assert et.weekday() < 5, f"next open landed on weekend: {et.strftime('%A')}"
    assert et.hour == 9 and et.minute == 30


@pytest.mark.asyncio
async def test_carry_forward_dedupes_same_symbol_setup(scanner_with_alerts):
    """In-memory + Mongo duplicates must not promote twice."""
    s = scanner_with_alerts
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    s.db["live_alerts"].find.return_value.sort.return_value.limit.return_value = [
        {
            "symbol": "NVDA", "setup_type": "relative_strength_leader",
            "direction": "long", "tqs_score": 82, "tqs_grade": "A",
            "created_at": today + "T15:00:00+00:00",
            "current_price": 480, "stop_loss": 475, "target": 490,
            "headline": "(dup)", "reasoning": ["dup"],
        }
    ]
    promoted = []
    async def _capture(alert):
        promoted.append(alert)
    s._process_new_alert = _capture

    await s._rank_carry_forward_setups_for_tomorrow()
    nvda_count = sum(1 for a in promoted if a.symbol == "NVDA")
    assert nvda_count == 1, f"NVDA promoted {nvda_count} times — dedup broken"
