"""
v19.34.28 — OCA-linked stop+target attach on reconciler adoption.

Pre-v19.34.28 the reconciler's `_spawn_excess_slice` attached only a
STP on adoption (v19.34.27). If the position ran in our favour, the
only way to take profit was the manage loop's mid-bar target check or
EOD close — and if the bot crashed between adoption and next scan, the
position was stop-only with no upside ticket.

Post-v19.34.28 both legs ship under a single OCA group so IB auto-
cancels the survivor when one fills. Survives bot crashes.

Also covers `attach_oca_stop_target` as a unit — PAPER fallback,
missing target_prices, stop-submit failure refusing to submit target,
target-only failure returning partial:true with stop still live.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── executor.attach_oca_stop_target unit tests ─────────────────────────

@pytest.mark.asyncio
async def test_attach_oca_simulated_mode_returns_sim_ids():
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.SIMULATED
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 140.0
    trade.target_prices = [150.0]
    trade.direction = MagicMock()
    trade.direction.value = "long"

    r = await ex.attach_oca_stop_target(trade)
    assert r["success"]
    assert r["stop_order_id"].startswith("SIM-STP-")
    assert r["target_order_id"].startswith("SIM-TGT-")
    assert r["simulated"]


@pytest.mark.asyncio
async def test_attach_oca_pusher_offline_returns_sim_ids_success_true():
    """Pusher offline must not block reconciler adoption — return sim
    ids + success=True so the slice still enters _open_trades."""
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 140.0
    trade.target_prices = [150.0]
    trade.direction = MagicMock()
    trade.direction.value = "long"

    with patch("routers.ib.is_pusher_connected", return_value=False):
        r = await ex.attach_oca_stop_target(trade)
    assert r["success"] is True
    assert r["simulated"] is True
    assert r.get("pusher_offline") is True


@pytest.mark.asyncio
async def test_attach_oca_missing_target_price_returns_error():
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 140.0
    trade.target_prices = []  # empty
    trade.direction = MagicMock()
    trade.direction.value = "long"

    with patch("routers.ib.is_pusher_connected", return_value=True):
        r = await ex.attach_oca_stop_target(trade)
    assert r["success"] is False
    assert "missing stop_price or target_price" in r["error"]


@pytest.mark.asyncio
async def test_attach_oca_stop_fails_refuses_target_submit():
    """If STP submit fails, LMT target must NOT be submitted (one-sided
    exposure is worse than no bracket)."""
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 140.0
    trade.target_prices = [150.0]
    trade.direction = MagicMock()
    trade.direction.value = "long"

    submitted_payloads = []

    def fake_queue(payload):
        submitted_payloads.append(payload)
        if payload["order_type"] == "STP":
            raise RuntimeError("STP rejected at pusher")
        return f"mock-{payload['order_type']}-id"

    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib.queue_order", side_effect=fake_queue):
        r = await ex.attach_oca_stop_target(trade)

    assert r["success"] is False
    assert "stop_submit_failed" in r["error"]
    # Only STP attempt was made, target was NOT attempted.
    assert len(submitted_payloads) == 1
    assert submitted_payloads[0]["order_type"] == "STP"


@pytest.mark.asyncio
async def test_attach_oca_target_fails_returns_partial_success():
    """STP succeeds, LMT fails — return success=True with partial=True
    so the reconciler still stamps the stop id on the trade."""
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 140.0
    trade.target_prices = [150.0]
    trade.direction = MagicMock()
    trade.direction.value = "long"

    def fake_queue(payload):
        if payload["order_type"] == "STP":
            return "STP-123"
        if payload["order_type"] == "LMT":
            raise RuntimeError("LMT rejected")
        return "x"

    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib.queue_order", side_effect=fake_queue):
        r = await ex.attach_oca_stop_target(trade)

    assert r["success"] is True
    assert r["stop_order_id"] == "STP-123"
    assert r["target_order_id"] is None
    assert r["partial"] is True
    assert any("LMT rejected" in str(e) for e in r.get("errors", []))


@pytest.mark.asyncio
async def test_attach_oca_both_legs_succeed_shared_oca_group():
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 140.0
    trade.target_prices = [150.0]
    trade.direction = MagicMock()
    trade.direction.value = "long"

    submitted = []

    def fake_queue(payload):
        submitted.append(payload)
        return f"{payload['order_type']}-{len(submitted)}"

    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib.queue_order", side_effect=fake_queue):
        r = await ex.attach_oca_stop_target(trade)

    assert r["success"] is True
    assert r["stop_order_id"] == "STP-1"
    assert r["target_order_id"] == "LMT-2"
    assert r["partial"] is False
    # Both legs MUST share the same oca_group.
    assert submitted[0]["oca_group"] == submitted[1]["oca_group"]
    assert submitted[0]["oca_group"].startswith("ADOPT-OCA-UPS-")
    # Actions both opposite-side (close direction).
    assert submitted[0]["action"] == "SELL"
    assert submitted[1]["action"] == "SELL"


@pytest.mark.asyncio
async def test_attach_oca_short_position_uses_buy_action():
    from services.trade_executor_service import TradeExecutorService, ExecutorMode
    ex = TradeExecutorService()
    ex._mode = ExecutorMode.LIVE
    ex._initialized = True
    trade = MagicMock()
    trade.id = "t1"
    trade.symbol = "UPS"
    trade.shares = 100
    trade.stop_price = 160.0
    trade.target_prices = [145.0]
    trade.direction = MagicMock()
    trade.direction.value = "short"

    submitted = []

    def fake_queue(payload):
        submitted.append(payload)
        return f"{payload['order_type']}-{len(submitted)}"

    with patch("routers.ib.is_pusher_connected", return_value=True), \
         patch("routers.ib.queue_order", side_effect=fake_queue):
        await ex.attach_oca_stop_target(trade)

    # Closing a short = BUY
    assert submitted[0]["action"] == "BUY"
    assert submitted[1]["action"] == "BUY"


# ─── reconciler._spawn_excess_slice calls attach_oca_stop_target ────────

@pytest.mark.asyncio
async def test_spawn_excess_slice_attaches_oca_bracket():
    """Happy path: attach_oca_stop_target returns both ids → stamped."""
    from services.position_reconciler import PositionReconciler
    fake_executor = MagicMock()
    fake_executor.attach_oca_stop_target = AsyncMock(return_value={
        "success": True,
        "stop_order_id": "STP-9",
        "target_order_id": "LMT-9",
        "oca_group": "ADOPT-OCA-UPS-abc-deadbe",
        "partial": False,
        "errors": [],
    })

    bot = MagicMock()
    bot._open_trades = {}
    bot._save_trade = AsyncMock()
    bot._trade_executor = fake_executor

    recon = PositionReconciler(db=MagicMock())
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

    new_id = await recon._spawn_excess_slice(
        bot, "UPS", ib_qty_signed=100, bot_q=0,
        ib_meta={"avg_cost": 145.0},
        ib_quote={"last": 145.0},
        stop_pct=2.0, rr=2.0,
        BotTrade=BotTrade, TradeDirection=TradeDirection, TradeStatus=TradeStatus,
    )

    assert new_id in bot._open_trades
    fake_executor.attach_oca_stop_target.assert_awaited_once()
    spawned = bot._open_trades[new_id]
    assert spawned.stop_order_id == "STP-9"
    assert spawned.target_order_id == "LMT-9"
    assert spawned.oca_group == "ADOPT-OCA-UPS-abc-deadbe"


@pytest.mark.asyncio
async def test_spawn_excess_slice_partial_oca_still_adopts(caplog):
    """Partial (stop-only) OCA still stamps stop_order_id + logs
    PARTIAL-OCA error so operator sees the missing target."""
    from services.position_reconciler import PositionReconciler
    fake_executor = MagicMock()
    fake_executor.attach_oca_stop_target = AsyncMock(return_value={
        "success": True,
        "stop_order_id": "STP-9",
        "target_order_id": None,
        "oca_group": "ADOPT-OCA-UPS-x",
        "partial": True,
        "errors": ["LMT rejected"],
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

    assert new_id in bot._open_trades
    spawned = bot._open_trades[new_id]
    assert spawned.stop_order_id == "STP-9"
    # target_order_id is NOT set when target failed
    assert getattr(spawned, "target_order_id", None) in (None, "")
    # Operator-visible error logged
    assert any("PARTIAL-OCA" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_spawn_excess_slice_oca_attach_total_failure(caplog):
    """attach_oca returns success=False → slice adopted + LOUD error."""
    from services.position_reconciler import PositionReconciler
    fake_executor = MagicMock()
    fake_executor.attach_oca_stop_target = AsyncMock(return_value={
        "success": False,
        "error": "pusher_exploded",
        "stop_order_id": None,
        "target_order_id": None,
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

    assert new_id in bot._open_trades
    # NAKED-SLICE error visible to operator
    assert any("NAKED-SLICE" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_spawn_excess_slice_uses_stop_only_fallback_for_legacy_executor():
    """If the executor lacks attach_oca_stop_target (legacy mock), fall
    back to place_stop_order so existing integration tests keep working."""
    from services.position_reconciler import PositionReconciler
    fake_executor = MagicMock(spec=["place_stop_order"])
    fake_executor.place_stop_order = AsyncMock(return_value={
        "success": True, "order_id": "LEGACY-STP",
    })

    bot = MagicMock()
    bot._open_trades = {}
    bot._save_trade = AsyncMock()
    bot._trade_executor = fake_executor

    recon = PositionReconciler(db=MagicMock())
    from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

    new_id = await recon._spawn_excess_slice(
        bot, "UPS", ib_qty_signed=100, bot_q=0,
        ib_meta={"avg_cost": 145.0},
        ib_quote={"last": 145.0},
        stop_pct=2.0, rr=2.0,
        BotTrade=BotTrade, TradeDirection=TradeDirection, TradeStatus=TradeStatus,
    )

    spawned = bot._open_trades[new_id]
    fake_executor.place_stop_order.assert_awaited_once()
    assert spawned.stop_order_id == "LEGACY-STP"
