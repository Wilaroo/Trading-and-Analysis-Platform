"""
Regression tests for services/l2_router.py.

Covers the path-B contract: top-3 EVAL alerts → 3 paper-mode L2 slots,
diff-based sub/unsub, idempotent on in-sync ticks, graceful when
pusher unreachable.
"""

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    from services import l2_router

    l2_router._router = None
    yield
    l2_router._router = None


def _make_alert(symbol, priority_str="HIGH", tqs=70.0, age_sec=60, status="active"):
    from services.enhanced_scanner import AlertPriority

    pri_map = {
        "CRITICAL": AlertPriority.CRITICAL,
        "HIGH": AlertPriority.HIGH,
        "MEDIUM": AlertPriority.MEDIUM,
        "LOW": AlertPriority.LOW,
    }
    return SimpleNamespace(
        symbol=symbol,
        priority=pri_map[priority_str],
        tqs_score=tqs,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_sec),
        status=status,
    )


def test_compute_desired_l2_picks_top_3_by_priority_then_tqs():
    from services import l2_router

    scanner = SimpleNamespace(
        _live_alerts={
            "1": _make_alert("AAPL", "HIGH", 80),
            "2": _make_alert("MSFT", "CRITICAL", 75),
            "3": _make_alert("NVDA", "HIGH", 90),
            "4": _make_alert("TSLA", "MEDIUM", 95),
            "5": _make_alert("AMD", "HIGH", 65),
        }
    )
    r = l2_router.L2DynamicRouter(scanner=scanner)
    desired = r._compute_desired_l2()
    # CRITICAL > HIGH > MEDIUM. Among HIGH, sort by TQS desc.
    assert desired == ["MSFT", "NVDA", "AAPL"]


def test_compute_desired_l2_dedupes_by_symbol():
    from services import l2_router

    scanner = SimpleNamespace(
        _live_alerts={
            "1": _make_alert("AAPL", "CRITICAL", 80),
            "2": _make_alert("AAPL", "HIGH", 70),  # dup symbol
            "3": _make_alert("MSFT", "HIGH", 60),
            "4": _make_alert("NVDA", "HIGH", 50),
        }
    )
    r = l2_router.L2DynamicRouter(scanner=scanner)
    desired = r._compute_desired_l2()
    assert desired == ["AAPL", "MSFT", "NVDA"]


def test_compute_desired_l2_skips_stale_alerts():
    from services import l2_router

    scanner = SimpleNamespace(
        _live_alerts={
            "1": _make_alert("STALE", "CRITICAL", 99, age_sec=99999),
            "2": _make_alert("FRESH", "HIGH", 50, age_sec=60),
        }
    )
    r = l2_router.L2DynamicRouter(scanner=scanner)
    assert r._compute_desired_l2() == ["FRESH"]


def test_compute_desired_l2_skips_inactive_alerts():
    from services import l2_router

    scanner = SimpleNamespace(
        _live_alerts={
            "1": _make_alert("FILLED", "CRITICAL", 99, status="filled"),
            "2": _make_alert("ACTIVE", "HIGH", 50),
        }
    )
    r = l2_router.L2DynamicRouter(scanner=scanner)
    assert r._compute_desired_l2() == ["ACTIVE"]


def test_compute_desired_l2_no_scanner_returns_empty():
    from services import l2_router

    r = l2_router.L2DynamicRouter(scanner=None)
    assert r._compute_desired_l2() == []


@pytest.mark.asyncio
async def test_route_once_in_sync_skips_calls():
    from services import l2_router

    scanner = SimpleNamespace(
        _live_alerts={
            "1": _make_alert("AAPL", "HIGH"),
            "2": _make_alert("MSFT", "HIGH", 60),
            "3": _make_alert("NVDA", "HIGH", 50),
        }
    )
    r = l2_router.L2DynamicRouter(scanner=scanner)

    with patch.object(r, "_pusher_l2_set", return_value=["AAPL", "MSFT", "NVDA"]):
        with patch.object(r, "_send_subscribe_l2") as sub_mock, \
             patch.object(r, "_send_unsubscribe_l2") as unsub_mock:
            result = await r._route_once()

    assert result["skipped"] is True
    assert result["reason"] == "in_sync"
    sub_mock.assert_not_called()
    unsub_mock.assert_not_called()


@pytest.mark.asyncio
async def test_route_once_diffs_and_sends_sub_unsub():
    from services import l2_router

    scanner = SimpleNamespace(
        _live_alerts={
            "1": _make_alert("AAPL", "HIGH", 80),
            "2": _make_alert("NVDA", "HIGH", 70),
            "3": _make_alert("TSLA", "HIGH", 60),
        }
    )
    r = l2_router.L2DynamicRouter(scanner=scanner)

    sub_calls = []
    unsub_calls = []

    def fake_sub(symbols):
        sub_calls.append(list(symbols))
        return {"added": list(symbols), "skipped_capped": [], "total_l2_subscribed": 3}

    def fake_unsub(symbols):
        unsub_calls.append(list(symbols))
        return {"removed": list(symbols)}

    # Pusher currently has SPY/QQQ/IWM (legacy); we want AAPL/NVDA/TSLA.
    with patch.object(r, "_pusher_l2_set", return_value=["SPY", "QQQ", "IWM"]):
        with patch.object(r, "_send_subscribe_l2", side_effect=fake_sub), \
             patch.object(r, "_send_unsubscribe_l2", side_effect=fake_unsub):
            decision = await r._route_once()

    assert sorted(unsub_calls[0]) == ["IWM", "QQQ", "SPY"]
    assert sorted(sub_calls[0]) == ["AAPL", "NVDA", "TSLA"]
    assert sorted(decision["added"]) == ["AAPL", "NVDA", "TSLA"]
    assert sorted(decision["removed"]) == ["IWM", "QQQ", "SPY"]
    # Audit ring captures the decision.
    assert len(r._audit) == 1


@pytest.mark.asyncio
async def test_route_once_skips_when_pusher_unreachable():
    from services import l2_router

    scanner = SimpleNamespace(_live_alerts={"1": _make_alert("AAPL")})
    r = l2_router.L2DynamicRouter(scanner=scanner)

    with patch.object(r, "_pusher_l2_set", return_value=None):
        with patch.object(r, "_send_subscribe_l2") as sub_mock, \
             patch.object(r, "_send_unsubscribe_l2") as unsub_mock:
            result = await r._route_once()

    assert result["skipped"] is True
    assert result["reason"] == "pusher_unreachable"
    sub_mock.assert_not_called()
    unsub_mock.assert_not_called()


def test_status_returns_introspection():
    from services import l2_router

    r = l2_router.L2DynamicRouter()
    s = r.status()
    assert s["max_l2_slots"] == 3
    assert s["tick_interval_sec"] == 15.0
    assert s["alert_freshness_sec"] == 600
    assert s["tick_count"] == 0
    assert "recent_decisions" in s


def test_disabled_via_env_does_not_start(monkeypatch):
    from services import l2_router

    monkeypatch.setenv("ENABLE_L2_DYNAMIC_ROUTING", "false")
    r = l2_router.L2DynamicRouter()
    started = r.start()
    assert started is False
    assert r._running is False


def test_singleton_helpers():
    from services import l2_router

    a = l2_router.get_l2_router()
    b = l2_router.get_l2_router()
    assert a is b
    scanner = SimpleNamespace(_live_alerts={})
    c = l2_router.init_l2_router(scanner)
    assert c is a
    assert c._scanner is scanner
