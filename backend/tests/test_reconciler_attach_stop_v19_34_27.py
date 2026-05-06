"""
v19.34.27 — Reconciler attaches IB stop on `_spawn_excess_slice` adoption.

Pre-fix the spawned slice was naked at IB: bot's `_open_trades` had a
stop_price field, but no STP order existed at the broker. If the bot
crashed or the manage loop's mid-bar stop check missed, the position
drifted unprotected.

Post-fix `_spawn_excess_slice` calls `bot._trade_executor.place_stop_order(trade)`
immediately after persisting and stamps `trade.stop_order_id` on
success. Failures are LOUD-LOGGED (not raised) so the slice still gets
adopted into _open_trades for the manage loop to track.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_spawn_excess_slice_attaches_ib_stop():
    """v19.34.27 legacy path: executor lacks attach_oca_stop_target →
    falls back to place_stop_order (covered in full by v19.34.28 tests;
    this pins the fallback code path stays supported)."""
    from services.position_reconciler import PositionReconciler

    fake_executor = MagicMock(spec=["place_stop_order"])
    fake_executor.place_stop_order = AsyncMock(return_value={
        "success": True, "order_id": "STP-123",
    })

    bot = MagicMock()
    bot._open_trades = {}
    bot._save_trade = AsyncMock()
    bot._trade_executor = fake_executor

    recon = PositionReconciler(db=MagicMock())

    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

    new_id = await recon._spawn_excess_slice(
        bot, "UPS", ib_qty_signed=100, bot_q=0,
        ib_meta={"avg_cost": 145.0, "market_price": 145.0},
        ib_quote={"last": 145.0, "close": 145.0},
        stop_pct=2.0, rr=2.0,
        BotTrade=BotTrade, TradeDirection=TradeDirection, TradeStatus=TradeStatus,
    )

    assert new_id in bot._open_trades, "spawned trade must be in _open_trades"
    fake_executor.place_stop_order.assert_awaited_once()
    placed_trade = fake_executor.place_stop_order.call_args[0][0]
    assert placed_trade.symbol == "UPS"
    assert placed_trade.shares == 100
    assert bot._open_trades[new_id].stop_order_id == "STP-123"


@pytest.mark.asyncio
async def test_spawn_excess_slice_loud_logs_when_stop_fails(caplog):
    """v19.34.27 legacy path fallback + failure — pins NAKED-SLICE log."""
    from services.position_reconciler import PositionReconciler

    fake_executor = MagicMock(spec=["place_stop_order"])
    fake_executor.place_stop_order = AsyncMock(return_value={
        "success": False, "error": "pusher_offline",
    })

    bot = MagicMock()
    bot._open_trades = {}
    bot._save_trade = AsyncMock()
    bot._trade_executor = fake_executor

    recon = PositionReconciler(db=MagicMock())

    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

    import logging
    with caplog.at_level(logging.ERROR):
        new_id = await recon._spawn_excess_slice(
            bot, "UPS", ib_qty_signed=100, bot_q=0,
            ib_meta={"avg_cost": 145.0},
            ib_quote={"last": 145.0},
            stop_pct=2.0, rr=2.0,
            BotTrade=BotTrade, TradeDirection=TradeDirection, TradeStatus=TradeStatus,
        )

    # Slice is still adopted (manage loop must keep tracking it).
    assert new_id in bot._open_trades
    # ERROR was logged so the operator can grep for `NAKED-SLICE`.
    assert any("NAKED-SLICE" in rec.message for rec in caplog.records), \
        "must log NAKED-SLICE when stop attach fails"


@pytest.mark.asyncio
async def test_spawn_excess_slice_handles_missing_executor():
    """No _trade_executor on bot → still adopts slice with WARN log."""
    from services.position_reconciler import PositionReconciler

    bot = MagicMock(spec=["_open_trades", "_save_trade"])
    bot._open_trades = {}
    bot._save_trade = AsyncMock()
    # Note: no `_trade_executor` attribute.

    recon = PositionReconciler(db=MagicMock())

    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

    new_id = await recon._spawn_excess_slice(
        bot, "UPS", ib_qty_signed=100, bot_q=0,
        ib_meta={"avg_cost": 145.0},
        ib_quote={"last": 145.0},
        stop_pct=2.0, rr=2.0,
        BotTrade=BotTrade, TradeDirection=TradeDirection, TradeStatus=TradeStatus,
    )
    # Adoption succeeded; spawn does not crash on missing executor.
    assert new_id in bot._open_trades


@pytest.mark.asyncio
async def test_spawn_excess_slice_handles_executor_exception(caplog):
    """attach_oca_stop_target raises → caught + logged + slice still adopted."""
    from services.position_reconciler import PositionReconciler

    fake_executor = MagicMock()
    fake_executor.attach_oca_stop_target = AsyncMock(side_effect=RuntimeError("boom"))

    bot = MagicMock()
    bot._open_trades = {}
    bot._save_trade = AsyncMock()
    bot._trade_executor = fake_executor

    recon = PositionReconciler(db=MagicMock())

    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
    import logging

    with caplog.at_level(logging.ERROR):
        new_id = await recon._spawn_excess_slice(
            bot, "UPS", ib_qty_signed=100, bot_q=0,
            ib_meta={"avg_cost": 145.0},
            ib_quote={"last": 145.0},
            stop_pct=2.0, rr=2.0,
            BotTrade=BotTrade, TradeDirection=TradeDirection, TradeStatus=TradeStatus,
        )
    assert new_id in bot._open_trades
    # Exception path logs `OCA-attach raised`
    assert any("OCA-attach raised" in rec.message for rec in caplog.records)
