"""
v19.21 — Premarket Gap-Scanner endpoint + CPU relief manager.
"""
import os
import sys
import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ============================================================================
# CPU Relief Manager
# ============================================================================
def test_cpu_relief_enable_disable_roundtrip():
    from services.cpu_relief_manager import CpuReliefManager
    mgr = CpuReliefManager()
    assert mgr.is_active() is False

    s = mgr.enable(reason="operator-test")
    assert s["active"] is True
    assert mgr.is_active() is True
    assert s["reason"] == "operator-test"

    s = mgr.disable()
    assert s["active"] is False
    assert mgr.is_active() is False


def test_cpu_relief_until_window_auto_disables():
    """When `until` is in the past, is_active() must auto-flip OFF."""
    from services.cpu_relief_manager import CpuReliefManager
    mgr = CpuReliefManager()
    mgr.enable()
    # Hand-set the until to the past (5s ago) so the auto-disable fires.
    mgr._until = datetime.now(timezone.utc) - timedelta(seconds=5)
    # First read auto-flips the state.
    assert mgr.is_active() is False
    # Subsequent reads stay off.
    assert mgr.is_active() is False


def test_cpu_relief_until_future_stays_on():
    from services.cpu_relief_manager import CpuReliefManager
    mgr = CpuReliefManager()
    mgr.enable()
    mgr._until = datetime.now(timezone.utc) + timedelta(hours=1)
    assert mgr.is_active() is True


def test_cpu_relief_record_deferred_increments_counter():
    from services.cpu_relief_manager import CpuReliefManager
    mgr = CpuReliefManager()
    mgr.enable()
    mgr.record_deferred("smart_backfill")
    mgr.record_deferred("smart_backfill")
    mgr.record_deferred("eval_historical")
    s = mgr.status()
    assert s["deferred_count"] == 3
    assert s["deferred_by_path"]["smart_backfill"] == 2
    assert s["deferred_by_path"]["eval_historical"] == 1


def test_cpu_relief_parse_until_handles_past_time():
    """A past 'HH:MM' (already happened today) must roll forward to next day."""
    from services.cpu_relief_manager import CpuReliefManager
    mgr = CpuReliefManager()
    # 00:01 today is almost certainly in the past — should resolve to tomorrow.
    parsed = mgr._parse_until("00:01")
    assert parsed is not None
    assert parsed > datetime.now(timezone.utc)


def test_cpu_relief_parse_until_invalid_returns_none():
    from services.cpu_relief_manager import CpuReliefManager
    mgr = CpuReliefManager()
    assert mgr._parse_until("not-a-time") is None
    assert mgr._parse_until(None) is None


# ============================================================================
# Premarket Gap-Scanner endpoint logic
# ============================================================================
def _make_alert(*, symbol, setup_type, gap_pct, age_seconds, direction="long"):
    """Build a fake LiveAlert-shaped object for the gappers endpoint test."""
    alert_time = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return SimpleNamespace(
        id=f"a-{symbol}",
        symbol=symbol,
        setup_type=setup_type,
        direction=direction,
        alert_time=alert_time.isoformat(),
        current_price=100.0,
        trigger_price=100.0,
        priority=SimpleNamespace(value="high"),
        market_setup="Gap & Go",
        is_countertrend=False,
        metadata={"gap_pct": gap_pct, "rvol": 3.5, "prev_close": 99.0},
    )


def test_gap_scanner_endpoint_filters_window_and_setups():
    from routers import live_scanner as ls

    fake_scanner = MagicMock()
    fake_scanner._running = True
    fake_scanner.get_live_alerts.return_value = [
        _make_alert(symbol="AAPL", setup_type="gap_fade",         gap_pct=4.2, age_seconds=30),
        _make_alert(symbol="TSLA", setup_type="premarket_high_break", gap_pct=6.0, age_seconds=120),
        _make_alert(symbol="OLD",  setup_type="gap_give_go",      gap_pct=8.0, age_seconds=60 * 30),  # outside 8 min
        _make_alert(symbol="NOPE", setup_type="9_ema_scalp",      gap_pct=0.5, age_seconds=60),       # not a gap setup, gap < 2%
        _make_alert(symbol="HOOD", setup_type="bouncy_ball",      gap_pct=3.5, age_seconds=120),      # gap >= 2%, should include
    ]
    ls._scanner = fake_scanner

    res = ls.get_premarket_gappers(window_minutes=8, min_gap_pct=2.0, max_results=10)
    assert res["success"] is True
    syms = [r["symbol"] for r in res["gappers"]]
    assert "AAPL" in syms      # gap setup, fresh
    assert "TSLA" in syms      # gap setup, fresh
    assert "HOOD" in syms      # non-gap setup but high gap_pct
    assert "OLD"  not in syms  # outside 8-min window
    assert "NOPE" not in syms  # gap setup not matched + gap_pct below threshold
    # Sort: largest |gap_pct| first → TSLA(6) > AAPL(4.2) > HOOD(3.5)
    assert syms == ["TSLA", "AAPL", "HOOD"]


def test_gap_scanner_endpoint_dedupes_symbols():
    """If the same symbol fires twice (different setups), only first is kept."""
    from routers import live_scanner as ls

    fake_scanner = MagicMock()
    fake_scanner._running = True
    fake_scanner.get_live_alerts.return_value = [
        _make_alert(symbol="AAPL", setup_type="gap_fade", gap_pct=4.2, age_seconds=30),
        _make_alert(symbol="AAPL", setup_type="premarket_high_break", gap_pct=4.5, age_seconds=60),
    ]
    ls._scanner = fake_scanner

    res = ls.get_premarket_gappers(window_minutes=8, min_gap_pct=2.0)
    assert len(res["gappers"]) == 1
    assert res["gappers"][0]["symbol"] == "AAPL"


def test_gap_scanner_endpoint_handles_no_alerts():
    from routers import live_scanner as ls
    fake_scanner = MagicMock()
    fake_scanner._running = True
    fake_scanner.get_live_alerts.return_value = []
    ls._scanner = fake_scanner

    res = ls.get_premarket_gappers()
    assert res["success"] is True
    assert res["count"] == 0
    assert res["gappers"] == []


# ============================================================================
# Smart-backfill defers when CPU relief is on
# ============================================================================
@pytest.mark.asyncio
async def test_smart_backfill_defers_when_cpu_relief_active():
    """The async wrapper must short-circuit and return a deferred payload
    whenever cpu_relief_manager.is_active() returns True."""
    from services.cpu_relief_manager import get_cpu_relief_manager
    from services.ib_historical_collector import IBHistoricalCollector

    relief = get_cpu_relief_manager()
    relief.enable(reason="pytest")
    try:
        collector = IBHistoricalCollector()
        result = await collector.smart_backfill(dry_run=False)
        assert result.get("deferred") is True
        assert result.get("success") is False
        # Counter incremented
        assert relief.status()["deferred_count"] >= 1
    finally:
        relief.disable()


@pytest.mark.asyncio
async def test_smart_backfill_dry_run_runs_even_with_relief_on():
    """Dry-run is cheap planning data — operator should always be able to
    invoke it during a CPU spike to decide what to do next."""
    from services.cpu_relief_manager import get_cpu_relief_manager
    from services.ib_historical_collector import IBHistoricalCollector

    relief = get_cpu_relief_manager()
    relief.enable(reason="pytest")
    try:
        collector = IBHistoricalCollector()
        result = await collector.smart_backfill(dry_run=True)
        # Dry-run should NOT be deferred — it should pass through.
        assert result.get("deferred") is None or result.get("deferred") is False
    finally:
        relief.disable()
