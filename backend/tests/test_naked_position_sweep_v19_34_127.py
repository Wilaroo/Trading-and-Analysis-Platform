"""v19.34.127 — Naked-position sweep + consolidator lifecycle event regression.

The actual root cause of the -$25k incident on 2026-05-12: IB
mass-cancelled 100+ of our protective stops at 11:21 and 15:29
independently of our code. Our consolidator / reissue paths only fire
when WE initiate the change; IB-initiated cancellations had ZERO
detection path. `bracket_lifecycle_events` for RJF/MTB/ARGX/UPS
confirmed: 0 reissue events on the bleeding day.

This test suite locks the v127 fix:
  • `_naked_position_sweep` walks `_open_trades`, queries IB live
    orders, detects any trade whose `stop_order_id` isn't in the live
    order book, and emergency-reissues via `attach_oca_stop_target`.
  • Every detection writes a `phase: "naked_sweep_reissue"` event to
    `bracket_lifecycle_events` so the operator can audit IB-initiated
    cancellations after the fact.
  • Consolidator merge events now persist a
    `phase: "consolidator_merge_reissue"` event for the same audit
    trail.
  • Sweep is safe in paper mode (skips silently), safe on broker
    outage (skips with reason), and safe on per-trade crashes
    (continues to next trade).
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _make_trade(*, tid, symbol, shares, stop_order_id):
    """Fixture for an open trade as the sweep would see it."""
    t = MagicMock()
    t.id = tid
    t.symbol = symbol
    t.remaining_shares = shares
    t.stop_order_id = stop_order_id
    t.target_order_id = None
    t.target_order_ids = []
    t.oca_group = None
    return t


def _make_bot(*, executor, open_trades, live_mode=True):
    """Fixture for a TradingBotService-like stub."""
    from services.trading_bot_service import TradingBotService
    bot = TradingBotService.__new__(TradingBotService)
    bot._trade_executor = executor
    bot._open_trades = open_trades
    bot._db = None  # _persist_lifecycle_event handles None DB cleanly
    bot._save_trade = MagicMock(return_value=None)
    return bot


# ────────────────────────────────────────────────────────────────────
# 1. Detection: trade with missing stop_order_id is flagged naked
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_detects_missing_stop_id():
    """`stop_order_id=None` ⇒ naked ⇒ reissue + lifecycle event."""
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock(return_value=[])

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"
    executor.attach_oca_stop_target = AsyncMock(
        return_value={
            "success": True,
            "stop_order_id": "STP-NEW-1",
            "target_order_id": "TGT-NEW-1",
            "oca_group": "OCA-NEW-1",
        }
    )

    trade = _make_trade(tid="t1", symbol="RJF", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with patch(
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

    # Verify lifecycle event was persisted with correct schema
    persist_mock.assert_awaited_once()
    ev = persist_mock.await_args.kwargs["event"]
    assert ev["phase"] == "naked_sweep_reissue"
    assert ev["success"] is True
    assert ev["trade_id"] == "t1"
    assert ev["symbol"] == "RJF"
    assert ev["new_stop_order_id"] == "STP-NEW-1"


# ────────────────────────────────────────────────────────────────────
# 2. Detection: stop_order_id present but NOT in IB live orders
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_detects_stop_id_missing_from_ib():
    """The yesterday scenario: trade.stop_order_id is set on our side,
    but IB cancelled it. Live order book doesn't contain it ⇒ naked."""
    ib_conn = AsyncMock()
    # IB returns OTHER live orders, but NOT the one we expect
    ib_conn.get_open_orders = AsyncMock(return_value=[
        {"order_id": "OTHER-1", "symbol": "AAPL"},
        {"order_id": "OTHER-2", "symbol": "MSFT"},
    ])

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"
    executor.attach_oca_stop_target = AsyncMock(
        return_value={"success": True, "stop_order_id": "STP-REISSUE",
                      "oca_group": "OCA-NEW"}
    )

    trade = _make_trade(tid="t-rjf", symbol="RJF", shares=200,
                        stop_order_id="STP-CANCELLED-BY-IB")
    bot = _make_bot(executor=executor, open_trades={"t-rjf": trade})

    with patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    assert result["naked_found"] == 1
    assert result["reissued"] == 1
    executor.attach_oca_stop_target.assert_awaited_once()


# ────────────────────────────────────────────────────────────────────
# 3. Non-naked: stop_order_id IS in live orders ⇒ no reissue
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_no_reissue_when_stop_is_live():
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock(return_value=[
        {"order_id": "STP-LIVE-123", "symbol": "AAPL"},
    ])

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"
    executor.attach_oca_stop_target = AsyncMock()

    trade = _make_trade(tid="t1", symbol="AAPL", shares=100,
                        stop_order_id="STP-LIVE-123")
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    result = await bot._naked_position_sweep()

    assert result["checked"] == 1
    assert result["naked_found"] == 0
    assert result["reissued"] == 0
    executor.attach_oca_stop_target.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 4. Paper mode: sweep skipped silently (no IB queries)
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_skipped_in_paper_mode():
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock()

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "PAPER"

    trade = _make_trade(tid="t1", symbol="AAPL", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    result = await bot._naked_position_sweep()
    assert result["skipped_reason"] == "non_live_mode:PAPER"
    ib_conn.get_open_orders.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# 5. No executor: skipped gracefully
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_skipped_when_no_executor():
    bot = _make_bot(executor=None, open_trades={})
    result = await bot._naked_position_sweep()
    assert result["skipped_reason"] == "no_trade_executor"


# ────────────────────────────────────────────────────────────────────
# 6. IB get_open_orders raises: sweep returns clean error, no crash
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_handles_ib_outage():
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock(
        side_effect=ConnectionError("IB Gateway offline")
    )

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"

    trade = _make_trade(tid="t1", symbol="AAPL", shares=100, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    result = await bot._naked_position_sweep()
    assert "ib_get_open_orders_failed" in result["skipped_reason"]
    # Sweep didn't crash; next iteration will retry.


# ────────────────────────────────────────────────────────────────────
# 7. Reissue FAILS (broker rejects): event persisted with success=False
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_persists_event_on_reissue_failure():
    """The catastrophic case — naked detected but broker rejects new
    OCA. Lifecycle event MUST land with success=False so the operator
    sees the still-naked position in /diagnostic/bracket-lifecycle."""
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock(return_value=[])

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"
    executor.attach_oca_stop_target = AsyncMock(
        return_value={"success": False, "error": "IB rejected: order limit"}
    )

    trade = _make_trade(tid="t1", symbol="RJF", shares=200, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"t1": trade})

    with patch(
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
# 8. Per-trade crash doesn't wedge the sweep
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_continues_after_per_trade_crash():
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock(return_value=[])

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"
    executor.attach_oca_stop_target = AsyncMock(
        return_value={"success": True, "stop_order_id": "OK"}
    )

    # First trade raises when reading remaining_shares
    bad_trade = MagicMock()
    bad_trade.id = "bad"
    type(bad_trade).remaining_shares = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("simulated crash"))
    )

    good_trade = _make_trade(tid="good", symbol="GOOD", shares=50, stop_order_id=None)
    bot = _make_bot(
        executor=executor,
        open_trades={"bad": bad_trade, "good": good_trade},
    )

    with patch(
        "services.bracket_reissue_service._persist_lifecycle_event",
        new_callable=AsyncMock,
    ):
        result = await bot._naked_position_sweep()

    # Bad trade crashed, but good trade was processed.
    assert result["reissued"] == 1


# ────────────────────────────────────────────────────────────────────
# 9. Sweep ignores closed-out trades (remaining_shares == 0)
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_ignores_zero_share_trades():
    ib_conn = AsyncMock()
    ib_conn.get_open_orders = AsyncMock(return_value=[])

    executor = MagicMock()
    executor._ib_service = ib_conn
    executor.mode = "LIVE"
    executor.attach_oca_stop_target = AsyncMock()

    closed_out = _make_trade(tid="c1", symbol="X", shares=0, stop_order_id=None)
    bot = _make_bot(executor=executor, open_trades={"c1": closed_out})

    result = await bot._naked_position_sweep()
    assert result["checked"] == 0
    assert result["naked_found"] == 0
    executor.attach_oca_stop_target.assert_not_awaited()
