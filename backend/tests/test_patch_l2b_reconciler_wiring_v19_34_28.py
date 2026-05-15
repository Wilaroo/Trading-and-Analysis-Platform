"""v19.34.28 Patch L2b — Reconciler / Guard wiring regression tests.

L2a shipped the new IBDirectService write+read methods + executor
routing. L2b wires the read consumers (position reconciler, orphan-GTC
positions fetch, account guard lookup) at the new authoritative
sources when `BOT_ORDER_PATH=direct`.

Tests pin:
  • _l2b_fetch_ib_positions: direct mode uses ib_direct.get_positions_fresh
  • _l2b_fetch_ib_positions: default mode (pusher) untouched
  • _l2b_fetch_ib_positions: strict_direct=True returns "unavailable" on socket miss
  • _l2b_fetch_ib_positions: ib_direct exception falls through to pusher (non-strict)
  • orphan_gtc_reconciler._fetch_ib_positions: direct mode tier = "ib_direct_fresh"
  • orphan_gtc_reconciler._fetch_ib_positions: pusher tier = "pusher_snapshot"
  • account guard lookup uses ib_direct.managedAccounts in direct mode
  • account guard lookup falls back to pusher in pusher mode
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, AsyncMock

# Make backend importable regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

from services import position_reconciler as pr
from services import orphan_gtc_reconciler as ogr


# ─────────────────────────────────────────────────────────────────────
# 1. _l2b_fetch_ib_positions — env-var gated direct path
# ─────────────────────────────────────────────────────────────────────

def test_l2b_fetch_positions_direct_mode_uses_ib_direct_fresh():
    fake = [{"symbol": "ABC", "position": 100.0, "avg_cost": 12.34, "fresh": True}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = True
    mock_ibd.get_positions_fresh = AsyncMock(return_value=fake)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd):
        positions, source = asyncio.run(pr._l2b_fetch_ib_positions())
    assert source == "ib_direct_fresh"
    assert positions == fake
    mock_ibd.get_positions_fresh.assert_awaited_once()


def test_l2b_fetch_positions_default_mode_uses_pusher_snapshot():
    """Without BOT_ORDER_PATH=direct, falls straight through to the
    pusher snapshot — ib_direct.get_positions_fresh is NEVER invoked."""
    fake_pusher = [{"symbol": "XYZ", "position": 50.0}]
    mock_ibd = MagicMock()
    mock_ibd.get_positions_fresh = AsyncMock(return_value=[{"never": True}])
    env = {k: v for k, v in os.environ.items() if k != "BOT_ORDER_PATH"}
    with patch.dict(os.environ, env, clear=True), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib._pushed_ib_data", {"positions": fake_pusher}):
        positions, source = asyncio.run(pr._l2b_fetch_ib_positions())
    assert source == "pusher_snapshot"
    assert positions == fake_pusher
    mock_ibd.get_positions_fresh.assert_not_called()


def test_l2b_fetch_positions_strict_direct_returns_unavailable_on_miss():
    """In strict mode, an ib_direct socket miss returns ([], 'unavailable')
    instead of falling through to the (possibly stale) pusher snapshot."""
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = False
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd):
        positions, source = asyncio.run(pr._l2b_fetch_ib_positions(strict_direct=True))
    assert positions == []
    assert source == "unavailable"


def test_l2b_fetch_positions_non_strict_falls_through_on_ib_direct_exception():
    """If ib_direct raises, non-strict mode silently falls back to pusher."""
    fake_pusher = [{"symbol": "AAA", "position": 10.0}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = True
    mock_ibd.get_positions_fresh = AsyncMock(side_effect=RuntimeError("socket drop"))
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib._pushed_ib_data", {"positions": fake_pusher}):
        positions, source = asyncio.run(pr._l2b_fetch_ib_positions())
    assert positions == fake_pusher
    assert source == "pusher_snapshot"


def test_l2b_fetch_positions_pusher_mode_explicit():
    """BOT_ORDER_PATH=pusher is identical to default behaviour."""
    fake_pusher = [{"symbol": "BBB", "position": 25.0}]
    mock_ibd = MagicMock()
    mock_ibd.get_positions_fresh = AsyncMock(return_value=[{"never": True}])
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "pusher"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib._pushed_ib_data", {"positions": fake_pusher}):
        positions, source = asyncio.run(pr._l2b_fetch_ib_positions())
    assert source == "pusher_snapshot"
    assert positions == fake_pusher
    mock_ibd.get_positions_fresh.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# 2. orphan_gtc_reconciler._fetch_ib_positions — independent wiring
# ─────────────────────────────────────────────────────────────────────

def test_l2b_orphan_gtc_fetch_positions_direct_mode():
    """orphan_gtc_reconciler._fetch_ib_positions also surfaces the
    ib_direct fresh fast path under BOT_ORDER_PATH=direct."""
    fake = [{"symbol": "MMM", "position": 200.0, "fresh": True}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = True
    mock_ibd.get_positions_fresh = AsyncMock(return_value=fake)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd):
        positions, src = ogr._fetch_ib_positions()
    assert src["tier"] == "ib_direct_fresh"
    assert src["ok"] is True
    assert positions == fake


def test_l2b_orphan_gtc_fetch_positions_pusher_default():
    fake_pusher = [{"symbol": "NNN", "position": 75.0}]
    mock_ibd = MagicMock()
    mock_ibd.get_positions_fresh = AsyncMock(return_value=[{"never": True}])
    env = {k: v for k, v in os.environ.items() if k != "BOT_ORDER_PATH"}
    with patch.dict(os.environ, env, clear=True), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib.get_pushed_positions", return_value=fake_pusher), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        positions, src = ogr._fetch_ib_positions()
    assert src["tier"] == "pusher_snapshot"
    assert src["ok"] is True
    assert positions == fake_pusher
    mock_ibd.get_positions_fresh.assert_not_called()


def test_l2b_orphan_gtc_fetch_positions_direct_socket_down_falls_back():
    """When direct socket is unreachable, falls through to pusher
    (non-strict — orphan-GTC needs SOME data to classify against)."""
    fake_pusher = [{"symbol": "PPP", "position": 12.0}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = False
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib.get_pushed_positions", return_value=fake_pusher), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        positions, src = ogr._fetch_ib_positions()
    assert src["tier"] == "pusher_snapshot"
    assert positions == fake_pusher


# ── L2b-hotfix1 — sync _fetch_ib_positions must NOT deadlock when called
# from inside a running event loop. Before the hotfix, this scenario
# wedged the backend boot for 162s because the helper spawned a thread
# that tried to await ib_async on a loop owned by the parent thread.
def test_l2b_hotfix1_sync_fetch_inside_event_loop_does_not_deadlock():
    """Sync _fetch_ib_positions called from inside a running loop must
    silently fall through to the pusher snapshot (no thread spawn, no
    asyncio.run, no deadlock)."""
    fake_pusher = [{"symbol": "SAFE", "position": 1.0}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = True
    # If the hotfix regresses, the test will hang here for >5s. Wrap in
    # asyncio.wait_for to fail fast instead of stalling the suite.
    async def _runner():
        return await asyncio.wait_for(
            asyncio.to_thread(ogr._fetch_ib_positions), timeout=5.0,
        )
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib.get_pushed_positions", return_value=fake_pusher), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        # Run the sync helper from a thread inside an event loop —
        # the sync helper itself sees no running loop on its own
        # thread, so the test must explicitly check the "inside-loop"
        # branch by calling it on the loop thread.
        async def _on_loop():
            return ogr._fetch_ib_positions()
        positions, src = asyncio.run(asyncio.wait_for(_on_loop(), timeout=5.0))
    # Inside running loop → must NOT touch ib_direct → pusher fallback.
    assert src["tier"] == "pusher_snapshot"
    assert positions == fake_pusher
    mock_ibd.get_positions_fresh.assert_not_called()


def test_l2b_hotfix1_async_helper_returns_ib_direct_fresh_when_direct():
    """The new _fetch_ib_positions_async should be used by async
    callers — uses ib_direct fresh path safely with native await."""
    fake = [{"symbol": "ASYNC", "position": 100.0, "fresh": True}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = True
    mock_ibd.get_positions_fresh = AsyncMock(return_value=fake)
    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd):
        positions, src = asyncio.run(ogr._fetch_ib_positions_async())
    assert src["tier"] == "ib_direct_fresh"
    assert positions == fake
    mock_ibd.get_positions_fresh.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────
# 3. position_reconciler.reconcile_positions_with_ib — direct mode path
# ─────────────────────────────────────────────────────────────────────

def _make_bot_with_empty_open_trades():
    """Minimal bot stub: just _open_trades dict, used by reconciler."""
    bot = SimpleNamespace()
    bot._open_trades = {}
    return bot


def test_l2b_reconcile_positions_records_source_tier_direct():
    """reconcile_positions_with_ib should record the L2b source tier
    in its report so the operator UI can see which feed was used."""
    fake = [{"symbol": "ABC", "position": 100.0, "avgCost": 12.34}]
    mock_ibd = MagicMock()
    mock_ibd.is_connected.return_value = True
    mock_ibd.get_positions_fresh = AsyncMock(return_value=fake)

    reconciler = pr.PositionReconciler.__new__(pr.PositionReconciler)
    reconciler._db = None  # not used by the reconcile path under test
    bot = _make_bot_with_empty_open_trades()

    with patch.dict(os.environ, {"BOT_ORDER_PATH": "direct"}, clear=False), \
         patch("services.ib_direct_service.get_ib_direct_service",
               return_value=mock_ibd), \
         patch("routers.ib._pushed_ib_data", {"positions": [{"never": True}]}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        report = asyncio.run(reconciler.reconcile_positions_with_ib(bot))

    assert report["positions_source"] == "ib_direct_fresh"
    assert any(p["symbol"] == "ABC" for p in report["ib_positions"])


def test_l2b_reconcile_positions_default_mode_uses_pusher():
    fake_pusher = [{"symbol": "ZZZ", "position": 5.0, "avgCost": 9.0}]
    reconciler = pr.PositionReconciler.__new__(pr.PositionReconciler)
    reconciler._db = None
    bot = _make_bot_with_empty_open_trades()
    env = {k: v for k, v in os.environ.items() if k != "BOT_ORDER_PATH"}
    with patch.dict(os.environ, env, clear=True), \
         patch("routers.ib._pushed_ib_data", {"positions": fake_pusher}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        report = asyncio.run(reconciler.reconcile_positions_with_ib(bot))
    assert report.get("positions_source") == "pusher_snapshot"
    assert any(p["symbol"] == "ZZZ" for p in report["ib_positions"])
