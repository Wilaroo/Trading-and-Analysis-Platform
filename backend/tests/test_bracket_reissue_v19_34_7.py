"""
test_bracket_reissue_v19_34_7.py — pin the v19.34.7 bracket re-issue
service. Operator-driven safety for the OCA bracket lifecycle: cancel
the old stale legs, recompute stop/target/qty for the post-event
position, submit a new OCA pair sharing the oca_group string.

2026-05-05 PM — operator request after the XLU 6-bracket forensic
revealed that the bot creates duplicate brackets on scale-in / scale-
out events without cancelling the old ones, leading to:
  (a) over-protected stops sized for the original (pre-scale) qty
  (b) duplicate OCA stacks at IB causing double-fills

This test file pins:
  1. Pure compute (compute_reissue_params) — stop math, target qty
     allocation, TIF resolution, edge cases.
  2. Cancel-then-ack flow (cancel_active_bracket_legs).
  3. Submit OCA pair (submit_oca_pair).
  4. Orchestrator (reissue_bracket_for_trade) — happy path + abort on
     cancel failure + abort on submit failure.

All tests are pure-Python — no IB Gateway, no network, no real DB.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _trade(**overrides):
    """Build a real BotTrade for compute_reissue_params + reissue path."""
    from services.trading_bot_service import (
        BotTrade, TradeDirection, TradeStatus, TradeTimeframe,
    )
    base = dict(
        id="trade-xlu-1",
        symbol="XLU",
        direction=TradeDirection.LONG,
        status=TradeStatus.OPEN,
        setup_type="opening_range_break",
        timeframe=TradeTimeframe.INTRADAY,
        quality_score=70,
        quality_grade="B",
        entry_price=80.00,
        current_price=80.00,
        stop_price=79.00,
        target_prices=[81.00, 82.00, 83.00],
        shares=100,
        remaining_shares=100,
        risk_amount=100.0,
        potential_reward=300.0,
        risk_reward_ratio=3.0,
        scale_out_config={
            "enabled": True,
            "scale_out_pcts": [0.50, 0.30, 0.20],
            "targets_hit": [],
            "partial_exits": [],
        },
        trade_style="intraday",
    )
    base.update(overrides)
    return BotTrade(**base)


def _risk_params(**overrides):
    from services.trading_bot_service import RiskParameters
    rp = RiskParameters()
    for k, v in overrides.items():
        setattr(rp, k, v)
    return rp


# --------------------------------------------------------------------------
# Pure compute
# --------------------------------------------------------------------------

class TestComputeReissueParams:

    def test_long_scale_in_recomputes_stop_from_new_avg_entry(self):
        """Scale-in: 100 sh @ $80, then add 50 sh @ $81 → 150 sh weighted-avg
        ~$80.33. Stop = $80.33 × (1 - 2.0%) = ~$78.73."""
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade()
        plan = compute_reissue_params(
            trade=trade,
            risk_params=_risk_params(reconciled_default_stop_pct=2.0),
            reason="scale_in",
            new_total_shares=150,
            new_avg_entry=80.33,
        )
        assert plan.symbol == "XLU"
        assert plan.direction == "long"
        assert plan.new_total_shares == 150
        assert plan.remaining_shares == 150
        assert plan.new_stop_price == round(80.33 * 0.98, 2)
        # Targets preserved at original price levels
        assert plan.target_price_levels == [81.00, 82.00, 83.00]
        # Qtys split 50/30/20 of 150 → 75/45/30
        assert plan.target_qtys == [75, 45, 30]
        assert sum(plan.target_qtys) == 150  # honors remaining
        assert plan.new_tif == "DAY"  # intraday
        assert plan.new_outside_rth is False

    def test_short_recomputes_stop_above_entry(self):
        """Short trade: stop must be ABOVE new avg entry."""
        from services.bracket_reissue_service import compute_reissue_params
        from services.trading_bot_service import TradeDirection
        trade = _trade(
            direction=TradeDirection.SHORT,
            entry_price=80.00, target_prices=[78.00],
            stop_price=81.50,
            scale_out_config={"enabled": True, "scale_out_pcts": [1.0],
                              "targets_hit": [], "partial_exits": []},
        )
        plan = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="scale_in", new_total_shares=200, new_avg_entry=80.00,
        )
        # Short stop ABOVE entry: 80 × 1.02 = 81.60
        assert plan.new_stop_price == 81.60
        assert plan.target_price_levels == [78.00]
        assert plan.target_qtys == [200]

    def test_scale_out_recomputes_target_qtys_for_remaining(self):
        """After 33sh of 100sh scale-out fired, remaining = 67. Targets
        recompute qtys against 67 with original 50/30/20 pcts."""
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade()
        plan = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="scale_out",
            new_total_shares=100,            # original size unchanged
            already_executed_shares=33,      # 33 already exited
            new_avg_entry=80.00,
        )
        assert plan.remaining_shares == 67
        # 67 × 50/30/20: floor = 33/20/13 = 66 → residual 1 → last bucket gets +1
        assert sum(plan.target_qtys) == 67
        # Stop sized for the remaining qty only (sub_oca_pair handles this)
        # — that's tested in the submit_oca_pair test.

    def test_remaining_zero_raises(self):
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade()
        with pytest.raises(ValueError, match="remaining shares"):
            compute_reissue_params(
                trade=trade, risk_params=_risk_params(),
                reason="scale_out", new_total_shares=100,
                already_executed_shares=100,
            )

    def test_zero_total_shares_raises(self):
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade()
        with pytest.raises(ValueError, match="must be > 0"):
            compute_reissue_params(
                trade=trade, risk_params=_risk_params(),
                reason="manual", new_total_shares=0,
            )

    def test_zero_avg_entry_raises(self):
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade(entry_price=0.0, fill_price=0.0)
        with pytest.raises(ValueError, match="avg_entry must be > 0"):
            compute_reissue_params(
                trade=trade, risk_params=_risk_params(),
                reason="manual", new_total_shares=100, new_avg_entry=0,
            )

    def test_swing_classification_promotes_to_gtc(self):
        """trade_style='multi_day' → bracket_tif returns ('GTC', True)."""
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade(trade_style="multi_day")
        plan = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="tif_promotion",
            new_total_shares=100, new_avg_entry=80.00,
        )
        assert plan.new_tif == "GTC"
        assert plan.new_outside_rth is True

    def test_no_target_levels_synthesizes_2r(self):
        """If trade has no target_prices, synthesize a 2R target."""
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade(target_prices=[])
        plan = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="manual",
            new_total_shares=100, new_avg_entry=80.00,
        )
        # stop = 80 × 0.98 = 78.40 → risk = 1.60 → 2R = 80 + 3.20 = 83.20
        assert plan.target_price_levels == [83.20]
        assert plan.target_qtys == [100]

    def test_preserve_target_levels_false_forces_synthesis(self):
        """preserve_target_levels=False ignores existing targets."""
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade()
        plan = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="manual",
            new_total_shares=100, new_avg_entry=80.00,
            preserve_target_levels=False,
        )
        # Synthesized 2R, NOT the original [81, 82, 83]
        assert plan.target_price_levels == [83.20]

    def test_oca_group_string_unique_per_call(self):
        """Each plan computes a unique OCA group string (timestamp + uuid)."""
        from services.bracket_reissue_service import compute_reissue_params
        trade = _trade()
        plan_a = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="manual",
            new_total_shares=100, new_avg_entry=80.00,
        )
        plan_b = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="manual",
            new_total_shares=100, new_avg_entry=80.00,
        )
        assert plan_a.oca_group != plan_b.oca_group
        assert plan_a.oca_group.startswith("REISSUE-trade-xlu-1-")

    def test_target_qtys_drop_zero_buckets(self):
        """Tiny remaining + many targets — zero buckets must be dropped."""
        from services.bracket_reissue_service import compute_reissue_params
        # 3 sh remaining, 50/30/20 pcts → floors = 1/0/0 → 1 + residual 2
        # → final = 1, 0, 2 → drop zero → [1, 2] in last lump
        trade = _trade(shares=3, remaining_shares=3,
                       scale_out_config={"enabled": True,
                                         "scale_out_pcts": [0.50, 0.30, 0.20],
                                         "targets_hit": [], "partial_exits": []})
        plan = compute_reissue_params(
            trade=trade, risk_params=_risk_params(),
            reason="manual",
            new_total_shares=3, new_avg_entry=80.00,
        )
        # No zero-qty target submitted to IB
        assert all(q > 0 for q in plan.target_qtys)
        assert sum(plan.target_qtys) == 3


# --------------------------------------------------------------------------
# Cancel + ack waiter
# --------------------------------------------------------------------------

class TestCancelActiveBracketLegs:

    @pytest.mark.asyncio
    async def test_cancels_all_active_legs(self):
        from services.bracket_reissue_service import cancel_active_bracket_legs
        # Mongo state: 3 active legs for trade-xlu-1
        active_state = {
            "ord-stop-1": "pending",
            "ord-tgt-1":  "pending",
            "ord-tgt-2":  "claimed",
        }

        def _find(q, projection=None):
            # First call: return all active rows
            if "$in" in (q.get("status") or {}):
                return [
                    {"order_id": oid, "status": st,
                     "order_type": "STP" if "stop" in oid else "LMT"}
                    for oid, st in active_state.items()
                ]
            # Subsequent ack-poll calls: return current statuses
            ids = q["order_id"]["$in"]
            return [{"order_id": oid, "status": active_state[oid]} for oid in ids]

        coll = MagicMock()
        coll.find = _find

        def _cancel(oid):
            active_state[oid] = "cancelled"
            return True

        svc = MagicMock()
        svc._collection = coll
        svc.cancel_order = _cancel

        result = await cancel_active_bracket_legs(
            trade_id="trade-xlu-1", queue_service=svc,
            cancel_ack_timeout_s=1.0,
        )

        assert result["success"] is True
        assert sorted(result["cancelled_orders"]) == sorted(active_state.keys())
        assert result["stuck_orders"] == []

    @pytest.mark.asyncio
    async def test_no_active_legs_is_vacuously_success(self):
        """If there are no active legs, the cancel is trivially successful."""
        from services.bracket_reissue_service import cancel_active_bracket_legs
        coll = MagicMock()
        coll.find = MagicMock(return_value=[])
        svc = MagicMock()
        svc._collection = coll

        result = await cancel_active_bracket_legs(
            trade_id="trade-xlu-1", queue_service=svc,
            cancel_ack_timeout_s=0.1,
        )
        assert result["success"] is True
        assert result["cancelled_orders"] == []

    @pytest.mark.asyncio
    async def test_stuck_orders_marked_when_ack_times_out(self):
        """If cancel_order returns OK but Mongo never flips to 'cancelled'
        within timeout, the order MUST be reported as stuck so the
        orchestrator aborts the re-issue."""
        from services.bracket_reissue_service import cancel_active_bracket_legs
        active_state = {"ord-stuck": "pending"}  # never flips

        def _find(q, projection=None):
            if "$in" in (q.get("status") or {}):
                return [{"order_id": "ord-stuck", "status": "pending",
                         "order_type": "STP"}]
            return [{"order_id": oid, "status": active_state[oid]}
                    for oid in q["order_id"]["$in"]]

        coll = MagicMock()
        coll.find = _find
        svc = MagicMock()
        svc._collection = coll
        svc.cancel_order = MagicMock(return_value=True)

        result = await cancel_active_bracket_legs(
            trade_id="trade-stuck", queue_service=svc,
            cancel_ack_timeout_s=0.3,
        )

        assert result["success"] is False
        assert result["stuck_orders"] == ["ord-stuck"]
        assert result["cancelled_orders"] == []


# --------------------------------------------------------------------------
# Submit OCA pair
# --------------------------------------------------------------------------

class TestSubmitOcaPair:

    def test_stop_and_targets_share_oca_group(self):
        from services.bracket_reissue_service import (
            ReissuePlan, submit_oca_pair,
        )
        captured = []
        def _q(payload):
            oid = f"ord-{len(captured)+1}"
            payload["__id__"] = oid
            captured.append(payload)
            return oid

        plan = ReissuePlan(
            trade_id="t1", symbol="XLU", direction="long",
            new_total_shares=150, remaining_shares=150,
            new_stop_price=78.73,
            target_price_levels=[81.00, 82.00, 83.00],
            target_qtys=[75, 45, 30],
            new_tif="DAY", new_outside_rth=False,
            oca_group="OCA-TEST", reason="scale_in",
        )
        result = submit_oca_pair(plan=plan, queue_order_fn=_q)

        assert result["success"] is True
        # 1 stop + 3 targets = 4 submissions
        assert len(captured) == 4
        # All 4 share the same oca_group
        assert all(c["oca_group"] == "OCA-TEST" for c in captured)
        # Stop is sized for the FULL remaining qty
        stop = captured[0]
        assert stop["order_type"] == "STP"
        assert stop["quantity"] == 150
        assert stop["stop_price"] == 78.73
        # Targets preserve their respective qtys
        target_qtys = [c["quantity"] for c in captured[1:]]
        assert target_qtys == [75, 45, 30]
        target_prices = [c["limit_price"] for c in captured[1:]]
        assert target_prices == [81.00, 82.00, 83.00]
        # Action flips to SELL for long
        assert all(c["action"] == "SELL" for c in captured)

    def test_short_uses_buy_action_on_legs(self):
        from services.bracket_reissue_service import (
            ReissuePlan, submit_oca_pair,
        )
        captured = []
        plan = ReissuePlan(
            trade_id="t1", symbol="HOOD", direction="short",
            new_total_shares=100, remaining_shares=100,
            new_stop_price=85.00, target_price_levels=[80.00],
            target_qtys=[100], new_tif="DAY", new_outside_rth=False,
            oca_group="OCA-S", reason="scale_in",
        )
        submit_oca_pair(plan=plan, queue_order_fn=lambda p: captured.append(p) or "x")
        assert all(c["action"] == "BUY" for c in captured)


# --------------------------------------------------------------------------
# Orchestrator: reissue_bracket_for_trade
# --------------------------------------------------------------------------

def _make_bot_for_orchestrator():
    from services.trading_bot_service import RiskParameters
    bot = MagicMock()
    bot.risk_params = RiskParameters()
    bot._save_trade = AsyncMock()
    bot._emit_stream_event = AsyncMock()
    return bot


def _make_queue_service_for_orchestrator(initial_active=None, cancel_succeeds=True,
                                          ack_immediately=True):
    """Build a mock queue_service that tracks state for the orchestrator path."""
    state = {}
    if initial_active:
        for oid in initial_active:
            state[oid] = "pending"

    def _find(q, projection=None):
        if "$in" in (q.get("status") or {}):
            return [
                {"order_id": oid, "status": state[oid], "order_type": "STP"}
                for oid in state
                if state[oid] in ("pending", "claimed", "executing")
            ]
        ids = q["order_id"]["$in"]
        return [{"order_id": oid, "status": state[oid]} for oid in ids
                if oid in state]

    def _cancel(oid):
        if not cancel_succeeds:
            return False
        if ack_immediately:
            state[oid] = "cancelled"
        return True

    svc = MagicMock()
    svc._initialized = True
    svc.initialize = MagicMock()
    coll = MagicMock()
    coll.find = _find
    svc._collection = coll
    svc.cancel_order = _cancel
    svc.state = state
    return svc


class TestReissueBracketOrchestrator:

    @pytest.mark.asyncio
    async def test_happy_path_cancels_old_and_submits_new(self):
        from services.bracket_reissue_service import reissue_bracket_for_trade

        trade = _trade()
        bot = _make_bot_for_orchestrator()
        svc = _make_queue_service_for_orchestrator(initial_active=["ord-old-stop", "ord-old-tgt"])
        new_orders = []
        def _q(p):
            oid = f"ord-new-{len(new_orders)+1}"
            new_orders.append((oid, p))
            return oid

        result = await reissue_bracket_for_trade(
            trade=trade, bot=bot, reason="scale_in",
            new_total_shares=150, new_avg_entry=80.33,
            queue_service=svc, queue_order_fn=_q,
        )

        assert result["success"] is True
        assert result["phase"] == "done"
        # Both old legs cancelled
        assert sorted(result["cancel_result"]["cancelled_orders"]) == [
            "ord-old-stop", "ord-old-tgt"
        ]
        # 1 stop + 3 targets = 4 new orders
        assert len(new_orders) == 4
        # Trade record updated with new stop / oca / first target id
        assert trade.stop_price == result["plan"]["new_stop_price"]
        assert trade.oca_group == result["submit_result"]["oca_group"]
        assert trade.stop_order_id == result["submit_result"]["stop_order_id"]
        # _save_trade was called post-submit
        bot._save_trade.assert_awaited_once_with(trade)

    @pytest.mark.asyncio
    async def test_cancel_failure_aborts_and_does_not_submit(self):
        """Cancel fails → ABORT, no new orders submitted, CRITICAL warning emitted."""
        from services.bracket_reissue_service import reissue_bracket_for_trade

        trade = _trade()
        bot = _make_bot_for_orchestrator()
        # Cancel issued but ack never arrives → stuck
        svc = _make_queue_service_for_orchestrator(
            initial_active=["ord-stuck"], cancel_succeeds=True,
            ack_immediately=False,
        )
        new_orders = []
        def _q(p):
            new_orders.append(p)
            return "ord-x"

        result = await reissue_bracket_for_trade(
            trade=trade, bot=bot, reason="scale_in",
            new_total_shares=150, new_avg_entry=80.33,
            queue_service=svc, queue_order_fn=_q,
            cancel_ack_timeout_s=0.2,
        )

        assert result["success"] is False
        assert result["phase"] == "cancel"
        assert result["error"] == "cancel_failed_abort"
        assert new_orders == []  # NO new orders submitted
        # CRITICAL stream warning emitted
        bot._emit_stream_event.assert_awaited_once()
        evt = bot._emit_stream_event.await_args.args[0]
        assert evt["severity"] == "critical"
        assert evt["title"] == "Bracket re-issue aborted"

    @pytest.mark.asyncio
    async def test_compute_failure_aborts_before_cancel(self):
        """If compute_reissue_params raises (e.g. zero remaining), the
        orchestrator MUST abort before touching IB. No cancels, no submits."""
        from services.bracket_reissue_service import reissue_bracket_for_trade

        trade = _trade()
        bot = _make_bot_for_orchestrator()
        svc = _make_queue_service_for_orchestrator(initial_active=["ord-old"])
        new_orders = []

        result = await reissue_bracket_for_trade(
            trade=trade, bot=bot, reason="scale_out",
            new_total_shares=100, already_executed_shares=100,  # zero remaining
            queue_service=svc, queue_order_fn=lambda p: new_orders.append(p) or "x",
        )

        assert result["success"] is False
        assert result["phase"] == "compute"
        # Cancel was NOT called — every old leg still active
        assert all(svc.state[oid] == "pending" for oid in svc.state)
        assert new_orders == []
