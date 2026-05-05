"""
test_pre_submit_mongo_first_v19_34_6.py — pin the Pre-execution
Mongo-first sanity gate that v19.34.6 added to `TradeExecution.execute_trade`.

2026-05-05 v19.34.6 — operator-driven safety improvement after the
GTC zombie investigation:

  > Pre-execution Mongo-first sanity gate: Write `bot_trades` row with
  > `status='pending'` BEFORE submitting to IB. Eliminates "IB fill
  > but no Mongo row" class of bug.

The contract this test pins:
  1. Before `place_bracket_order` is called, `bot._save_trade(trade)`
     MUST be invoked once.
  2. The trade's `status` MUST be `PENDING` at that pre-submit save.
  3. The trade's `pre_submit_at` field MUST be a non-empty ISO string.
  4. After successful fill, the post-fill save call MUST upsert with
     `status=OPEN` (overwriting the pre-submit row by trade.id).
  5. After broker rejection, post-rejection save MUST upsert with
     `status=REJECTED` (overwriting the pre-submit row by trade.id).
  6. Pre-execution VETO branches (paper/simulation/guardrail/dedup) MUST
     NOT trigger the pre-submit save — they short-circuit before any
     broker call so no IB-fill-without-Mongo-row risk exists.

All tests are pure-Python — no IB Gateway, no network, no DB.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_trade(**overrides):
    """Construct a real BotTrade for execute_trade() to operate on.
    Avoids dataclass-default landmines vs MagicMock by building the
    actual class."""
    from services.trading_bot_service import (
        BotTrade, TradeDirection, TradeStatus, TradeTimeframe,
    )
    base = dict(
        id="trade-presubmit-1",
        symbol="HOOD",
        direction=TradeDirection.LONG,
        status=TradeStatus.PENDING,
        setup_type="opening_range_break",
        timeframe=TradeTimeframe.INTRADAY,
        quality_score=70,
        quality_grade="B",
        entry_price=73.42,
        current_price=73.42,
        stop_price=72.10,
        target_prices=[76.50, 78.20],
        shares=100,
        risk_amount=132.0,
        potential_reward=308.0,
        risk_reward_ratio=2.33,
    )
    base.update(overrides)
    return BotTrade(**base)


def _make_bot(executor_result):
    """Stub TradingBotService just enough that execute_trade can run."""
    bot = MagicMock()
    bot._strategy_promotion_service = None  # skip phase check
    bot._learning_loop = None
    bot._trade_callbacks = []
    bot._daily_stats = MagicMock(trades_executed=0)
    bot._open_trades = {}
    bot._pending_trades = {}
    bot._db = None  # don't touch real Mongo

    # Records every call to _save_trade so we can assert ordering
    bot.save_calls = []

    async def _save_trade_recorder(trade):
        # Snapshot the trade state at the moment of save
        bot.save_calls.append({
            "status": (trade.status.value if hasattr(trade.status, "value")
                       else trade.status),
            "pre_submit_at": getattr(trade, "pre_submit_at", None),
            "fill_price": getattr(trade, "fill_price", None),
            "executed_at": getattr(trade, "executed_at", None),
            "notes": getattr(trade, "notes", ""),
            "close_reason": getattr(trade, "close_reason", None),
        })

    bot._save_trade = _save_trade_recorder
    bot._notify_trade_update = AsyncMock()
    bot._log_trade_to_journal = AsyncMock()
    bot._add_filter_thought = MagicMock()

    def _apply_commission(trade, shares):
        return 0.0
    bot._apply_commission = _apply_commission

    # Mock executor that returns the configured result
    executor = MagicMock()
    executor.get_mode = MagicMock(return_value=MagicMock(value="paper"))
    executor.place_bracket_order = AsyncMock(return_value=executor_result)
    executor.execute_entry = AsyncMock(return_value=executor_result)
    executor.place_stop_order = AsyncMock(return_value={"success": True, "order_id": "stop-1"})
    executor.get_account_info = AsyncMock(return_value={"equity": 100000.0})
    bot._trade_executor = executor
    return bot


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestPreSubmitMongoFirstV19_34_6:

    @pytest.mark.asyncio
    async def test_pre_submit_save_happens_before_broker_call(self):
        """The contract: Mongo gets the row BEFORE place_bracket_order
        is invoked, with status=PENDING + a pre_submit_at timestamp."""
        from services.trade_execution import TradeExecution

        # Configure broker to capture the trade state at submit time
        broker_seen_state = {}

        async def _place_bracket_seen(trade):
            broker_seen_state["status_at_submit"] = (
                trade.status.value if hasattr(trade.status, "value") else trade.status
            )
            broker_seen_state["pre_submit_at_at_submit"] = getattr(trade, "pre_submit_at", None)
            broker_seen_state["save_calls_seen"] = list(bot.save_calls)  # snapshot
            return {
                "success": True,
                "entry_order_id": "ord-123",
                "fill_price": 73.50,
                "filled_qty": 100,
                "status": "filled",
                "broker": "interactive_brokers",
                "stop_order_id": "stop-1",
                "target_order_id": "tgt-1",
                "oca_group": "oca-abc",
            }

        bot = _make_bot(executor_result={"success": True})
        bot._trade_executor.place_bracket_order = _place_bracket_seen

        trade = _make_trade()
        bot._pending_trades[trade.id] = trade

        executor = TradeExecution()
        await executor.execute_trade(trade, bot)

        # AT LEAST ONE save happened BEFORE the broker was called
        assert len(broker_seen_state["save_calls_seen"]) >= 1, (
            "execute_trade did NOT save to Mongo before calling the broker — "
            "the v19.34.6 pre-submit gate is broken."
        )
        pre = broker_seen_state["save_calls_seen"][0]
        assert pre["status"] == "pending", (
            f"pre-submit save status should be 'pending', got {pre['status']!r}"
        )
        assert pre["pre_submit_at"], (
            "pre_submit_at must be stamped on the trade by the time of "
            "the pre-submit save"
        )
        assert "PRE-SUBMIT-v19.34.6" in (pre["notes"] or "")

        # And the trade was confirmed PENDING at the moment of submit
        assert broker_seen_state["status_at_submit"] == "pending"

    @pytest.mark.asyncio
    async def test_post_fill_save_overwrites_with_open(self):
        """After successful broker fill, the SECOND save flips to OPEN."""
        from services.trade_execution import TradeExecution

        bot = _make_bot(executor_result={
            "success": True,
            "entry_order_id": "ord-200",
            "fill_price": 73.55,
            "filled_qty": 100,
            "status": "filled",
            "broker": "interactive_brokers",
            "stop_order_id": "stop-2",
            "target_order_id": "tgt-2",
        })

        trade = _make_trade(id="trade-flow-2")
        bot._pending_trades[trade.id] = trade

        executor = TradeExecution()
        await executor.execute_trade(trade, bot)

        statuses = [c["status"] for c in bot.save_calls]
        assert "pending" in statuses, (
            f"pre-submit row was not saved as pending: {statuses}"
        )
        assert "open" in statuses, (
            f"post-fill save did not flip to OPEN: {statuses}"
        )
        # Pre-submit MUST come before OPEN in temporal order.
        first_pending_idx = statuses.index("pending")
        first_open_idx = statuses.index("open")
        assert first_pending_idx < first_open_idx, (
            f"pre-submit (pending) must be saved BEFORE the post-fill "
            f"(open) save: order was {statuses}"
        )

    @pytest.mark.asyncio
    async def test_broker_rejection_overwrites_with_rejected(self):
        """After broker rejection, post-rejection save flips to REJECTED."""
        from services.trade_execution import TradeExecution

        bot = _make_bot(executor_result={
            "success": False,
            "error": "insufficient buying power",
            "status": "rejected",
        })

        trade = _make_trade(id="trade-flow-rej")
        bot._pending_trades[trade.id] = trade

        executor = TradeExecution()
        await executor.execute_trade(trade, bot)

        statuses = [c["status"] for c in bot.save_calls]
        # Pre-submit recorded as pending
        assert "pending" in statuses
        # Post-rejection recorded as rejected (final state)
        assert "rejected" in statuses, (
            f"final save did not flip to REJECTED on broker rejection: {statuses}"
        )

    @pytest.mark.asyncio
    async def test_no_executor_skips_pre_submit_save(self):
        """If no trade_executor is configured, execute_trade returns
        BEFORE the pre-submit branch, so NO save happens at all."""
        from services.trade_execution import TradeExecution

        bot = _make_bot(executor_result={"success": True})
        bot._trade_executor = None  # break the executor

        trade = _make_trade(id="trade-no-exec")
        bot._pending_trades[trade.id] = trade

        executor = TradeExecution()
        await executor.execute_trade(trade, bot)

        # No save happened — defensive: we never want to write a PENDING
        # row that we know we'll never submit to the broker.
        assert bot.save_calls == [], (
            f"execute_trade unexpectedly saved when executor was missing: "
            f"{bot.save_calls}"
        )

    @pytest.mark.asyncio
    async def test_pre_submit_at_field_persists_through_to_dict(self):
        """`pre_submit_at` must be in to_dict() so persist_trade writes
        it to Mongo. Direct field test."""
        from services.trading_bot_service import (
            BotTrade, TradeDirection, TradeStatus, TradeTimeframe,
        )
        t = BotTrade(
            id="t1", symbol="X", direction=TradeDirection.LONG,
            status=TradeStatus.OPEN, setup_type="orb",
            timeframe=TradeTimeframe.INTRADAY,
            quality_score=70, quality_grade="B",
            entry_price=10.0, current_price=10.0, stop_price=9.0,
            target_prices=[12.0], shares=10, risk_amount=10.0,
            potential_reward=20.0, risk_reward_ratio=2.0,
        )
        # Default is None until pre-submit gate fires
        d = t.to_dict()
        assert "pre_submit_at" in d
        assert d["pre_submit_at"] is None

        t.pre_submit_at = "2026-05-05T13:30:00+00:00"
        d2 = t.to_dict()
        assert d2["pre_submit_at"] == "2026-05-05T13:30:00+00:00"

    @pytest.mark.asyncio
    async def test_pre_submit_save_failure_does_not_block_broker(self):
        """If the pre-submit save raises, we MUST still proceed to the
        broker. Better to have a missing audit row than to block a
        legitimate entry on a transient Mongo hiccup."""
        from services.trade_execution import TradeExecution

        bot = _make_bot(executor_result={
            "success": True,
            "entry_order_id": "ord-300",
            "fill_price": 73.55,
            "filled_qty": 100,
            "status": "filled",
            "broker": "interactive_brokers",
            "stop_order_id": "stop-3",
            "target_order_id": "tgt-3",
        })

        # Make the FIRST save raise; subsequent saves succeed.
        original_recorder = bot._save_trade
        call_count = {"n": 0}

        async def _flaky_save(trade):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated mongo hiccup on pre-submit")
            await original_recorder(trade)

        bot._save_trade = _flaky_save

        trade = _make_trade(id="trade-flaky-presubmit")
        bot._pending_trades[trade.id] = trade

        executor = TradeExecution()
        # MUST NOT raise
        await executor.execute_trade(trade, bot)

        # Broker call DID happen (1 call to place_bracket_order)
        assert bot._trade_executor.place_bracket_order.await_count == 1, (
            "broker should still be called when pre-submit save fails"
        )
        # Post-fill save succeeded after the flaky pre-submit
        statuses = [c["status"] for c in bot.save_calls]
        assert "open" in statuses, (
            f"post-fill save should have written OPEN: {statuses}"
        )
