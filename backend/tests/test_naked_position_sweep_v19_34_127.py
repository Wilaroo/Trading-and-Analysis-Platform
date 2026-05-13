"""v19.34.127 / .129 — Naked-position sweep regression.

The actual root cause of the -$25k incident on 2026-05-12: IB
mass-cancelled 100+ of our protective stops at 11:21 and 15:29
independently of our code. Our consolidator / reissue paths only fire
when WE initiate the change; IB-initiated cancellations had ZERO
detection path. `bracket_lifecycle_events` for RJF/MTB/ARGX/UPS
confirmed: 0 reissue events on the bleeding day.

v19.34.127: introduced `_naked_position_sweep` that walks
`_open_trades`, queries IB open orders, detects naked positions, and
emergency-reissues via `attach_oca_stop_target`.

v19.34.129: rewired the open-orders source to `_fetch_ib_open_orders`
(3-tier ib_direct → pusher-relay → `_pushed_ib_data["orders"]`) so
the sweep works on the DGX pusher-only deployment shape.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_trade(*, tid, symbol, shares, stop_order_id):
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.remaining_shares = shares
    t.stop_order_id = stop_order_id
    t.target_order_id = None
    t.target_order_ids = []
    t.oca_group = None
    return t


def _make_bot(*, executor, open_trades):
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService.__new__(TradingBotService)
    bot._trade_executor = executor
    bot._open_trades = open_trades
    bot._db = None
    bot._save_trade = MagicMock(return_value=None)
    return bot


def _make_executor(*, mode="LIVE", oca_result=None):
    """Executor mock — no `_ib_client` needed since the sweep now
    delegates to `_fetch_ib_open_orders`."""
    executor = MagicMock()
    executor.mode = mode
    if oca_result is not None:
        executor.attach_oca_stop_target = AsyncMock(return_value=oca_result)
    return executor


def _patch_fetch(ib_orders, source_tier="pusher_orders_snapshot"):
    """Patch the 3-tier open-orders resolver to return `ib_orders`."""
    return patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new_callable=AsyncMock,
        return_value=(ib_orders, {"tier": source_tier, "ok": True}),
    )


# ────────────────────────────────────────────────────────────────────
# 1. stop_order_id=None ⇒ naked ⇒ reissue + lifecycle event
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_detects_missing_stop_id():
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-NEW-1",
        "target_order_id": "TGT-NEW-1", "oca_group": "OCA-NEW-1",
    })
    trade = _make_trade(tid="t1", symbol="RJF", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ) as persist_mock:
        result = await bot._naked_position_sweep()

    assert result["checked"] == 1
    assert result["naked_found"] == 1
    assert result["reissued"] == 1
    assert result["reissue_failed"] == 0
    executor.attach_oca_stop_target.assert_awaited_once_with(trade)
    assert trade.stop_order_id == "STP-NEW-1"

    persist_mock.assert_awaited_once()
    ev = persist_mock.await_args.kwargs["event"]
    assert ev["phase"] == "naked_sweep_reissue"
    assert ev["success"] is True
    assert ev["trade_id"] == "t1"
    assert ev["symbol"] == "RJF"
    assert ev["new_stop_order_id"] == "STP-NEW-1"


# ────────────────────────────────────────────────────────────────────
# 2. stop_id present but NOT in IB live orders ⇒ naked
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_detects_stop_id_missing_from_ib():
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-REISSUE", "oca_group": "OCA-NEW",
    })
    trade = _make_trade(tid="t-rjf", symbol="RJF", shares=200,
                        stop_order_id="STP-CANCELLED-BY-IB")
    bot = _make_bot(executor=executor, open_trades={"t-rjf": trade})

    # IB returns OTHER live orders, not the one we expect
    with _patch_fetch([
        {"ib_order_id": "OTHER-1", "symbol": "AAPL"},
        {"ib_order_id": "OTHER-2", "symbol": "MSFT"},
    ]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["naked_found"] == 1
    assert result["reissued"] == 1


# ────────────────────────────────────────────────────────────────────
# 3. stop IS in live orders ⇒ no reissue
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_no_reissue_when_stop_is_live():
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    trade = _make_trade(tid="t1", symbol="AAPL", shares=100,
                        stop_order_id="STP-LIVE-123")
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with _patch_fetch([{"ib_order_id": "STP-LIVE-123", "symbol": "AAPL"}]):
        result = await bot._naked_position_sweep()

    assert result["checked"] == 1
    assert result["naked_found"] == 0
    executor.attach_oca_stop_target.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 4. Non-LIVE executor mode ⇒ skipped silently
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_skipped_in_paper_mode():
    executor = _make_executor(mode="SIMULATED")
    executor.attach_oca_stop_target = AsyncMock()
    trade = _make_trade(tid="t1", symbol="AAPL", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with _patch_fetch([]):
        result = await bot._naked_position_sweep()

    assert result["skipped_reason"] == "non_live_mode:SIMULATED"
    executor.attach_oca_stop_target.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 5. No executor ⇒ skipped gracefully
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_skipped_when_no_executor():
    bot = _make_bot(executor=None, open_trades={})
    result = await bot._naked_position_sweep()
    assert result["skipped_reason"] == "no_trade_executor"


# ────────────────────────────────────────────────────────────────────
# 6. Open-orders fetch raises ⇒ clean skip with reason
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_handles_fetch_failure():
    executor = _make_executor()
    trade = _make_trade(tid="t1", symbol="AAPL", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new_callable=AsyncMock,
        side_effect=ConnectionError("IB Gateway offline"),
    ):
        result = await bot._naked_position_sweep()

    assert "open_orders_fetch_failed" in result["skipped_reason"]


# ────────────────────────────────────────────────────────────────────
# 7. Open-orders source returns None (no working tier)
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_skipped_when_no_source_available():
    executor = _make_executor()
    trade = _make_trade(tid="t1", symbol="AAPL", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with patch(
        "services.orphan_gtc_reconciler._fetch_ib_open_orders",
        new_callable=AsyncMock,
        return_value=(None, {"tier": None, "error": "all_tiers_failed"}),
    ):
        result = await bot._naked_position_sweep()
    assert "open_orders_unavailable" in result["skipped_reason"]


# ────────────────────────────────────────────────────────────────────
# 8. Reissue fails ⇒ event persisted with success=False
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_persists_event_on_reissue_failure():
    executor = _make_executor(oca_result={
        "success": False, "error": "IB rejected: order limit",
    })
    trade = _make_trade(tid="t1", symbol="RJF", shares=200, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ) as persist_mock:
        result = await bot._naked_position_sweep()

    assert result["naked_found"] == 1
    assert result["reissued"] == 0
    assert result["reissue_failed"] == 1
    persist_mock.assert_awaited_once()
    ev = persist_mock.await_args.kwargs["event"]
    assert ev["phase"] == "naked_sweep_reissue"
    assert ev["success"] is False
    assert "order limit" in (ev.get("error") or "")


# ────────────────────────────────────────────────────────────────────
# 9. Per-trade crash doesn't wedge the sweep
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_continues_after_per_trade_crash():
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "OK",
    })
    bad_trade = MagicMock()
    bad_trade.id = "bad"
    type(bad_trade).remaining_shares = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("simulated"))
    )
    good_trade = _make_trade(tid="good", symbol="GOOD", shares=50, stop_order_id=None)
    bot = _make_bot(executor=executor,
                    open_trades={"bad": bad_trade, "good": good_trade})

    with _patch_fetch([]), patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()
    assert result["reissued"] == 1


# ────────────────────────────────────────────────────────────────────
# 10. Zero-share trades ignored
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_ignores_zero_share_trades():
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    closed_out = _make_trade(tid="c1", symbol="X", shares=0, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"c1": closed_out})

    with _patch_fetch([]):
        result = await bot._naked_position_sweep()
    assert result["checked"] == 0
    assert result["naked_found"] == 0
    executor.attach_oca_stop_target.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 11. Resolver matches on perm_id OR ib_order_id (pusher snapshot uses both)
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_matches_perm_id_as_well_as_order_id():
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    trade = _make_trade(tid="t1", symbol="AAPL", shares=100,
                        stop_order_id="PERM-999")  # tracked as perm_id
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with _patch_fetch([
        {"ib_order_id": "12345", "perm_id": "PERM-999", "symbol": "AAPL"},
    ]):
        result = await bot._naked_position_sweep()

    assert result["checked"] == 1
    assert result["naked_found"] == 0
    executor.attach_oca_stop_target.assert_not_awaited()
