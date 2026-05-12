"""
test_safety_close_resilience_v19_34_119.py
─────────────────────────────────────────────────────────────────────────────
Regression guards for the v19.34.119 "26/26 close_returned_false" incident.

What was broken:
  • UI 'Close all' returned `close_returned_false` for every position with
    no surfaced broker error — operator could not see WHY closes failed.
  • Secondary `/emergency-flatten-ib` was conditional on ib_direct
    (clientId=11). When clientId=11 was flapping, the operator had no
    automated recovery — had to flatten in TWS manually.
  • There was no pre-flight signal that the close paths would actually
    work (working-order cap saturation, login conflicts).

What v19.34.119 added:
  1. `position_manager.close_trade` stashes the real broker error on
     `trade._last_close_error` BEFORE returning False.
  2. `safety_router.flatten_all` auto-chains to nuclear + pusher-fallback
     when the primary path returns 0 successes.
  3. New `/api/safety/diagnose-close-readiness` pre-flight endpoint that
     surfaces verdict + expected path + working-order saturation per symbol.
  4. New `_pusher_fallback_close_groups()` helper that bypasses ib_direct
     entirely (uses pusher's cancellations/queue + retries close_trade).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helper: lightweight bot/trade stubs ────────────────────────────────
class _Risk:
    base_atr_multiplier = 1.5
    min_atr_multiplier = 1.0
    max_atr_multiplier = 3.0


def _mk_trade(trade_id: str, symbol: str = "ONON", direction: str = "short",
              shares: int = 100, remaining: int = 100):
    """Minimal trade-shaped object with the attributes
    position_manager.close_trade reads."""
    return SimpleNamespace(
        id=trade_id, symbol=symbol,
        direction=SimpleNamespace(value=direction),
        shares=shares, remaining_shares=remaining,
        current_price=35.0, fill_price=34.0,
        realized_pnl=0.0, unrealized_pnl=0.0,
        total_commissions=0.0, net_pnl=0.0,
        entered_by="", setup_type="day_2_continuation",
        executed_at="2026-02-12T00:00:00",
    )


# ──────────────────────────────────────────────────────────────────────
# 1. close_trade error propagation (Tier-1 fix #4)
# ──────────────────────────────────────────────────────────────────────
class TestCloseTradeErrorPropagation:
    """close_trade must stash the real broker error on the trade object
    before returning False, so safety_router can surface it instead of
    the opaque `close returned False`."""

    @pytest.mark.asyncio
    async def test_executor_failure_sets_last_close_error(self):
        from services.position_manager import PositionManager

        trade = _mk_trade("t-abc")
        bot = SimpleNamespace(
            _open_trades={"t-abc": trade},
            _closed_trades=[],
            risk_params=_Risk(),
            _trade_executor=SimpleNamespace(
                close_position=AsyncMock(return_value={
                    "success": False,
                    "error": "IB Error 201: 15-order working cap",
                })
            ),
            _save_trade=AsyncMock(),
            _stop_manager=None,
        )
        pm = PositionManager()
        # Bypass the IB-direct clamp so we hit the executor path directly.
        pm._clamp_shares_to_ib_position = AsyncMock(
            side_effect=lambda t, s, reason=None: s
        )

        with patch("services.trade_drop_recorder.record_trade_drop"):
            ok = await pm.close_trade("t-abc", bot, reason="emergency_flatten_all")

        assert ok is False, "close_trade must return False on executor refusal"
        assert hasattr(trade, "_last_close_error"), (
            "v19.34.119: trade must carry the broker error after a failed close"
        )
        assert "201" in trade._last_close_error, (
            "v19.34.119: actual IB error must be surfaced, not 'unknown'"
        )
        assert hasattr(trade, "_last_close_error_at")

    @pytest.mark.asyncio
    async def test_successful_close_does_not_stamp_error(self):
        from services.position_manager import PositionManager
        from services.trading_bot_service import TradeStatus  # noqa

        trade = _mk_trade("t-ok")
        bot = SimpleNamespace(
            _open_trades={"t-ok": trade},
            _closed_trades=[],
            risk_params=_Risk(),
            _trade_executor=SimpleNamespace(
                close_position=AsyncMock(return_value={
                    "success": True, "fill_price": 35.0,
                })
            ),
            _daily_stats=SimpleNamespace(
                net_pnl=0.0, trades_won=0, trades_lost=0,
                largest_win=0.0, largest_loss=0.0, win_rate=0.0,
            ),
            _save_trade=AsyncMock(),
            _stop_manager=None,
            _notify_trade_update=AsyncMock(),
            _log_trade_to_journal=AsyncMock(),
            _log_trade_to_regime_performance=AsyncMock(),
            _perf_service=None,
            _learning_loop=None,
            _apply_commission=lambda t, s: 0.0,
        )
        pm = PositionManager()
        pm._clamp_shares_to_ib_position = AsyncMock(side_effect=lambda t, s, reason=None: s)
        ok = await pm.close_trade("t-ok", bot, reason="manual")
        assert ok is True
        # Successful close should NOT leave a stale error on the trade.
        assert getattr(trade, "_last_close_error", None) in (None, "")


# ──────────────────────────────────────────────────────────────────────
# 2. diagnose-close-readiness pre-flight (Tier-1 fix #1)
# ──────────────────────────────────────────────────────────────────────
class TestDiagnoseCloseReadiness:
    """Pre-flight verdict must clearly distinguish green / yellow / red
    and identify which path will run."""

    @pytest.mark.asyncio
    async def test_verdict_red_when_pusher_down(self):
        from routers import safety_router
        with patch("routers.ib.is_pusher_connected", return_value=False), \
             patch("routers.ib._pushed_ib_data", new={}, create=True), \
             patch("services.ib_direct_service.get_ib_direct_service") as mk_ibd, \
             patch("services.trading_bot_service.get_trading_bot_service") as mk_bot, \
             patch("motor.motor_asyncio.AsyncIOMotorClient") as mk_mongo:
            ibd = MagicMock()
            ibd.is_connected.return_value = False
            ibd.is_authorized_to_trade.return_value = False
            ibd.status.return_value = {"connected": False}
            mk_ibd.return_value = ibd
            mk_bot.return_value = SimpleNamespace(_open_trades={})
            mk_mongo.return_value.__getitem__.return_value.order_queue.count_documents = AsyncMock(return_value=0)
            out = await safety_router.diagnose_close_readiness()
            assert out["verdict"] == "red", out
            assert "pusher" in " ".join(out["issues"]).lower()
            assert out["pusher"]["connected"] is False

    @pytest.mark.asyncio
    async def test_verdict_red_when_working_orders_over_cap(self):
        from routers import safety_router
        trade = _mk_trade("t1", symbol="ONON", direction="short")
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             patch("routers.ib._pushed_ib_data", new={}, create=True), \
             patch("services.ib_direct_service.get_ib_direct_service") as mk_ibd, \
             patch("services.trading_bot_service.get_trading_bot_service") as mk_bot, \
             patch("motor.motor_asyncio.AsyncIOMotorClient") as mk_mongo:
            ibd = MagicMock()
            ibd.is_connected.return_value = True
            ibd.is_authorized_to_trade.return_value = True
            ibd.status.return_value = {"connected": True}
            ibd.get_positions = AsyncMock(return_value=[])
            mk_ibd.return_value = ibd
            mk_bot.return_value = SimpleNamespace(_open_trades={"t1": trade})
            # 18 working orders for ONON — over the 15-cap
            mk_mongo.return_value.__getitem__.return_value.order_queue.count_documents = AsyncMock(return_value=18)
            out = await safety_router.diagnose_close_readiness()
            assert out["verdict"] == "red", out
            assert any(r["over_cap"] for r in out["working_orders_by_symbol"])
            assert "pusher_fallback" in out["expected_path"]

    @pytest.mark.asyncio
    async def test_verdict_green_when_all_healthy(self):
        from routers import safety_router
        with patch("routers.ib.is_pusher_connected", return_value=True), \
             patch("routers.ib._pushed_ib_data", new={}, create=True), \
             patch("services.ib_direct_service.get_ib_direct_service") as mk_ibd, \
             patch("services.trading_bot_service.get_trading_bot_service") as mk_bot, \
             patch("motor.motor_asyncio.AsyncIOMotorClient") as mk_mongo:
            ibd = MagicMock()
            ibd.is_connected.return_value = True
            ibd.is_authorized_to_trade.return_value = True
            ibd.status.return_value = {"connected": True}
            ibd.get_positions = AsyncMock(return_value=[])
            mk_ibd.return_value = ibd
            mk_bot.return_value = SimpleNamespace(_open_trades={})
            mk_mongo.return_value.__getitem__.return_value.order_queue.count_documents = AsyncMock(return_value=0)
            out = await safety_router.diagnose_close_readiness()
            assert out["verdict"] == "green"
            assert out["expected_path"] == "primary"


# ──────────────────────────────────────────────────────────────────────
# 3. Pusher-fallback close (Tier-1 fix #3)
# ──────────────────────────────────────────────────────────────────────
class TestPusherFallbackClose:
    """Pusher-fallback must enumerate ib_order_ids from MongoDB,
    enqueue cancellations, wait, then retry close_trade."""

    @pytest.mark.asyncio
    async def test_enqueues_cancellations_for_affected_symbols(self):
        from routers import safety_router

        trade = _mk_trade("t-onon", symbol="ONON", direction="short")
        groups = {("ONON", "short"): [trade]}
        bot = SimpleNamespace(close_trade=AsyncMock(return_value=True))

        # Mock the MongoDB cursor with 3 working orders for ONON.
        rows = [
            {"ib_order_id": 1001, "symbol": "ONON", "status": "filled"},
            {"ib_order_id": 1002, "symbol": "ONON", "status": "filled"},
            {"ib_order_id": 1003, "symbol": "ONON", "status": "pending"},
        ]
        async def _async_iter(_self):
            for r in rows:
                yield r
        cursor = MagicMock()
        cursor.__aiter__ = _async_iter

        with patch("motor.motor_asyncio.AsyncIOMotorClient") as mk_mongo, \
             patch("routers.ib.queue_cancellation") as mk_q, \
             patch("asyncio.sleep", new=AsyncMock()):  # skip the 10s wait
            mk_mongo.return_value.__getitem__.return_value.order_queue.find.return_value = cursor
            result = await safety_router._pusher_fallback_close_groups(bot, groups)

        assert result["cancellations_queued"] == 3, result
        assert mk_q.call_count == 3
        # ib_order_ids forwarded correctly
        called_ids = sorted(c.kwargs["ib_order_id"] for c in mk_q.call_args_list)
        assert called_ids == [1001, 1002, 1003]
        # Then the retry close_trade succeeded
        assert result["succeeded_count"] == 1
        bot.close_trade.assert_awaited_once_with(
            "t-onon", reason="v19_34_119_pusher_fallback",
        )

    @pytest.mark.asyncio
    async def test_surfaces_broker_error_on_retry_failure(self):
        from routers import safety_router

        trade = _mk_trade("t-rjf", symbol="RJF", direction="long")
        groups = {("RJF", "long"): [trade]}

        async def _fail_and_stamp(tid, reason=None):
            # Mimic position_manager.close_trade: stamp the broker err
            # on the trade object BEFORE returning False.
            trade._last_close_error = "IB Error 201: 15-order cap"
            return False

        bot = SimpleNamespace(close_trade=AsyncMock(side_effect=_fail_and_stamp))

        async def _empty_iter(_self):
            if False:
                yield
        cursor = MagicMock()
        cursor.__aiter__ = _empty_iter

        with patch("motor.motor_asyncio.AsyncIOMotorClient") as mk_mongo, \
             patch("routers.ib.queue_cancellation"), \
             patch("asyncio.sleep", new=AsyncMock()):
            mk_mongo.return_value.__getitem__.return_value.order_queue.find.return_value = cursor
            result = await safety_router._pusher_fallback_close_groups(bot, groups)

        assert result["succeeded_count"] == 0
        assert result["failed_count"] == 1
        # Broker error must be surfaced from trade._last_close_error
        assert "201" in result["groups"][0]["err"]


# ──────────────────────────────────────────────────────────────────────
# 4. Auto-chain inline-nuclear safety (Tier-1 fix #2)
# ──────────────────────────────────────────────────────────────────────
class TestInlineNuclearAutoChain:
    """Inline-nuclear must report clearly when ib_direct is down — that's
    the SECONDARY failure mode that left the operator stranded in the
    real incident. Must NOT raise; must NOT block the pusher fallback."""

    @pytest.mark.asyncio
    async def test_returns_clean_failure_when_ib_direct_down(self):
        from routers import safety_router
        with patch("services.ib_direct_service.get_ib_direct_service") as mk_ibd:
            ibd = MagicMock()
            ibd.ensure_connected = AsyncMock(return_value=False)
            ibd.is_authorized_to_trade.return_value = False
            mk_ibd.return_value = ibd
            out = await safety_router._attempt_emergency_flatten_ib_inline()
            assert out["success"] is False
            assert "not connected" in out["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_clean_failure_when_not_authorized(self):
        from routers import safety_router
        with patch("services.ib_direct_service.get_ib_direct_service") as mk_ibd:
            ibd = MagicMock()
            ibd.ensure_connected = AsyncMock(return_value=True)
            ibd.is_authorized_to_trade.return_value = False
            mk_ibd.return_value = ibd
            out = await safety_router._attempt_emergency_flatten_ib_inline()
            assert out["success"] is False
            assert "authorized" in out["error"].lower()
            # The "TWS login conflict" hint is the specific operator-facing
            # diagnosis from the incident post-mortem.
            assert "managedAccounts" in out["error"] or "login" in out["error"]
