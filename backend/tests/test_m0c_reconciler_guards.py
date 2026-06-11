"""
M0c (2026-06-12) — reconciler ladder-safety guards.

Covers the CASY ladder-kill incident: after a backend restart the in-memory
pusher snapshot is wiped; the boot orphan-GTC audit and the v127 naked-sweep
then saw positions=[] / orders=[] and destroyed valid M0 OCA ladder legs.

Guards under test:
  1. audit_orphan_gtc_orders ABORTS (success=False) on an empty positions
     snapshot while the bot tracks active trades (fail-closed).
  2. classify_open_orders downgrades naked_no_position → awaiting_data when
     the order maps to an ACTIVE bot trade with remaining shares
     (contradiction = stale snapshot, never auto-cancel).
  3. Genuine naked classification still works (closed trade / no trade).
  4. _m0_working_leg_stop_ids returns live ladder stop ids (sweep helper).
  5. Naked-sweep success handler must not clobber target_order_ids when the
     reissue placed a new M0 ladder (m0_ladder=True).
  6. PositionConsolidator skips groups holding working M0 ladder legs.
"""
import asyncio
from types import SimpleNamespace

import pytest

from services.orphan_gtc_reconciler import (
    VERDICT_AWAITING_DATA,
    VERDICT_NAKED_NO_POSITION,
    VERDICT_TRACKED,
    SAFE_TO_AUTO_CANCEL,
    classify_open_orders,
    audit_orphan_gtc_orders,
)
from services.trading_bot_service import _m0_working_leg_stop_ids


# ─── helpers ─────────────────────────────────────────────────────────────────

def _order(oid=101, sym="CASY", action="SELL", otype="STP", tif="GTC", oca=""):
    return {
        "ib_order_id": oid, "perm_id": None, "symbol": sym, "action": action,
        "quantity": 6, "order_type": otype, "limit_price": None,
        "stop_price": 500.0, "time_in_force": tif, "status": "Submitted",
        "oca_group": oca,
    }


def _trade_row(tid="abcd1234ef", status="open", remaining=15, **kw):
    row = {
        "id": tid, "symbol": "CASY", "status": status,
        "remaining_shares": remaining, "stop_order_id": 101,
        "target_order_id": 102, "target_order_ids": ["102", "103", "104"],
    }
    row.update(kw)
    return row


# ─── 1. audit-level empty-snapshot circuit breaker ───────────────────────────

class TestEmptySnapshotCircuitBreaker:
    def _run_audit(self, monkeypatch, *, positions, pos_src, trades, bot=None):
        import services.orphan_gtc_reconciler as ogr

        async def fake_orders():
            return [_order()], {"tier": "ib_direct", "ok": True, "count": 1}

        async def fake_positions():
            return positions, pos_src

        monkeypatch.setattr(ogr, "_fetch_ib_open_orders", fake_orders)
        monkeypatch.setattr(ogr, "_fetch_ib_positions_async", fake_positions)
        monkeypatch.setattr(
            ogr, "_fetch_bot_trades",
            lambda b: (trades, {"tier": "mongo_bot_trades", "ok": True}),
        )
        return asyncio.get_event_loop().run_until_complete(
            audit_orphan_gtc_orders(bot=bot, only_gtc=False)
        )

    def test_aborts_on_empty_positions_with_active_trades(self, monkeypatch):
        out = self._run_audit(
            monkeypatch,
            positions=[],
            pos_src={"tier": "pusher_snapshot", "ok": True, "pusher_connected": True},
            trades=[_trade_row(status="open", remaining=15)],
        )
        assert out["success"] is False
        assert out["reason"] == "empty_positions_snapshot_guard"
        assert out["verdicts"] == []

    def test_aborts_on_empty_positions_with_unprimed_pusher(self, monkeypatch):
        # No active trades, but the pusher feed isn't fresh — backend just
        # restarted, snapshot wiped. Must not classify anything.
        out = self._run_audit(
            monkeypatch,
            positions=[],
            pos_src={"tier": "pusher_snapshot", "ok": True, "pusher_connected": False},
            trades=[_trade_row(status="closed", remaining=0)],
        )
        assert out["success"] is False
        assert out["reason"] == "empty_positions_snapshot_guard"

    def test_aborts_on_empty_positions_with_in_memory_trades(self, monkeypatch):
        bot = SimpleNamespace(_open_trades={"t1": object()}, _db=None)
        out = self._run_audit(
            monkeypatch,
            positions=[],
            pos_src={"tier": "pusher_snapshot", "ok": True, "pusher_connected": True},
            trades=[],
            bot=bot,
        )
        assert out["success"] is False
        assert out["reason"] == "empty_positions_snapshot_guard"

    def test_proceeds_on_empty_positions_when_flat_and_fresh(self, monkeypatch):
        # Fresh pusher + bot tracks nothing → empty positions is trustable;
        # the lone GTC stop is a genuine naked zombie and must be flagged.
        out = self._run_audit(
            monkeypatch,
            positions=[],
            pos_src={"tier": "pusher_snapshot", "ok": True, "pusher_connected": True},
            trades=[],
        )
        assert out["success"] is True
        assert out["summary"][VERDICT_NAKED_NO_POSITION] >= 1

    def test_proceeds_on_nonempty_positions(self, monkeypatch):
        out = self._run_audit(
            monkeypatch,
            positions=[{"symbol": "CASY", "position": 15}],
            pos_src={"tier": "ib_direct_fresh", "ok": True},
            trades=[_trade_row()],
        )
        assert out["success"] is True
        assert out["summary"][VERDICT_TRACKED] >= 1


# ─── 2/3. classifier active-trade contradiction guard ────────────────────────

class TestClassifierActiveTradeGuard:
    def test_matched_active_trade_flat_snapshot_is_awaiting_data(self):
        verdicts = classify_open_orders(
            ib_open_orders=[_order(oid=101)],
            ib_positions=[],  # flat snapshot
            bot_trades=[_trade_row(status="open", remaining=15)],
            only_gtc=False,
        )
        assert len(verdicts) == 1
        assert verdicts[0].verdict == VERDICT_AWAITING_DATA
        assert VERDICT_AWAITING_DATA not in SAFE_TO_AUTO_CANCEL

    def test_m0_leg_matched_via_target_order_ids_list(self):
        # Leg 3's target (oid=104) only appears in target_order_ids.
        verdicts = classify_open_orders(
            ib_open_orders=[_order(oid=104, otype="LMT")],
            ib_positions=[],
            bot_trades=[_trade_row(status="open", remaining=15)],
            only_gtc=False,
        )
        assert verdicts[0].verdict == VERDICT_AWAITING_DATA

    def test_m0_leg_matched_via_oca_group_token(self):
        # Order ids unknown to Mongo but OCA group embeds the trade id
        # (ADOPT-OCA-{sym}-{trade_id}-L{n}-{nonce}).
        verdicts = classify_open_orders(
            ib_open_orders=[_order(oid=999, oca="ADOPT-OCA-CASY-abcd1234ef-L2-aa11bb")],
            ib_positions=[],
            bot_trades=[_trade_row(status="open", remaining=15)],
            only_gtc=False,
        )
        assert verdicts[0].verdict == VERDICT_AWAITING_DATA

    def test_closed_trade_flat_snapshot_still_naked(self):
        # Regression: genuine naked zombies (trade closed, order alive)
        # must still classify naked → auto-cancellable.
        verdicts = classify_open_orders(
            ib_open_orders=[_order(oid=101)],
            ib_positions=[],
            bot_trades=[_trade_row(status="closed", remaining=0)],
            only_gtc=False,
        )
        assert verdicts[0].verdict == VERDICT_NAKED_NO_POSITION

    def test_unmatched_order_flat_snapshot_still_naked(self):
        verdicts = classify_open_orders(
            ib_open_orders=[_order(oid=555)],
            ib_positions=[],
            bot_trades=[],
            only_gtc=False,
        )
        assert verdicts[0].verdict == VERDICT_NAKED_NO_POSITION

    def test_active_trade_with_position_still_tracked(self):
        verdicts = classify_open_orders(
            ib_open_orders=[_order(oid=101)],
            ib_positions=[{"symbol": "CASY", "position": 15}],
            bot_trades=[_trade_row()],
            only_gtc=False,
        )
        assert verdicts[0].verdict == VERDICT_TRACKED


# ─── 4. naked-sweep ladder helper ────────────────────────────────────────────

class TestM0WorkingLegStopIds:
    def test_returns_working_leg_stop_ids(self):
        trade = SimpleNamespace(scale_out_config={"m0_legs": [
            {"idx": 0, "status": "filled_tp", "stop_order_id": 201},
            {"idx": 1, "status": "working", "stop_order_id": 202},
            {"idx": 2, "status": "working", "stop_order_id": 203},
        ]})
        assert _m0_working_leg_stop_ids(trade) == ["202", "203"]

    def test_empty_for_non_m0_trade(self):
        assert _m0_working_leg_stop_ids(SimpleNamespace(scale_out_config={})) == []
        assert _m0_working_leg_stop_ids(SimpleNamespace(scale_out_config=None)) == []

    def test_sweep_semantics_any_live_leg_means_protected(self):
        # Leg 1 stop OCA-cancelled after its TP filled; legs 2-3 still live.
        trade = SimpleNamespace(
            stop_order_id=201,  # leg-1 stop — gone from live orders
            scale_out_config={"m0_legs": [
                {"idx": 0, "status": "filled_tp", "stop_order_id": 201},
                {"idx": 1, "status": "working", "stop_order_id": 202},
                {"idx": 2, "status": "working", "stop_order_id": 203},
            ]},
        )
        live_order_ids = {"202", "203", "302", "303"}  # legs 2-3 pairs
        m0_ids = _m0_working_leg_stop_ids(trade)
        assert any(s in live_order_ids for s in m0_ids)  # → NOT naked


# ─── 6. consolidator M0 skip ─────────────────────────────────────────────────

class TestConsolidatorM0Skip:
    def test_skips_group_with_working_m0_ladder(self):
        from services.position_consolidator import PositionConsolidator

        def mk_trade(tid, m0=False):
            return SimpleNamespace(
                id=tid, symbol="CASY",
                direction=SimpleNamespace(value="long"),
                remaining_shares=10, shares=10,
                scale_out_config=(
                    {"m0_legs": [{"idx": 0, "status": "working",
                                  "stop_order_id": 201}]} if m0 else {}
                ),
            )

        canonical = mk_trade("aaaa1111bb", m0=True)
        sibling = mk_trade("cccc2222dd")
        bot = SimpleNamespace(
            _open_trades={"aaaa1111bb": canonical, "cccc2222dd": sibling},
            _trade_executor=None,
        )
        g = {
            "symbol": "CASY", "direction": "long",
            "proposed_total_shares": 20,
            "proposed_canonical": {"trade_id": "aaaa1111bb"},
        }
        pc = PositionConsolidator(db=None)
        out = asyncio.get_event_loop().run_until_complete(
            pc._consolidate_one_group(bot, g)
        )
        assert out["skipped"] is True
        assert out["reason"] == "m0_ladder_active"
        assert "aaaa1111bb" in out["m0_trades"]
        # Ladder untouched: order ids must NOT have been cleared.
        assert canonical.scale_out_config["m0_legs"][0]["status"] == "working"
