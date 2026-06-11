"""
M0 laddered scale-out — test suite (2026-06).

Covers:
  1. order_policy_registry — new 3-rung scalp/intraday ladders + env parsing.
  2. ib_direct_service._m0_ladder_plan — gating + exact qty accounting.
  3. ib_direct_service._m0_place_oca_ladder — per-leg OCA pairs, ownership
     tokens in group names, trade-state stamping, stop-failure rollback.
  4. ib_direct_service.modify_stop_price — in-place modification.
  5. m0_ladder_manager — leg-fill detection (corroborated), blank-snapshot
     safety, TP/stop attribution, BE/trail stop-sync ratchet + throttle.

Run:  cd backend && ../.venv/bin/python -m pytest tests/test_m0_ladder.py -q
(or in the container: cd /app/backend && python -m pytest tests/test_m0_ladder.py -q)
"""
import asyncio
import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ───────────────────────── fakes ─────────────────────────

class FakeOrderStatus:
    def __init__(self, status="Submitted"):
        self.status = status


class FakeIBTrade:
    def __init__(self, contract, order):
        self.contract = contract
        self.order = order
        self.orderStatus = FakeOrderStatus()
        self._active = True

    def isActive(self):
        return self._active


class FakeIB:
    def __init__(self):
        self._next_id = itertools.count(1000)
        self.placed = []          # (contract, order) in submission sequence
        self.cancelled = []       # order objects
        self._trades = []
        self.fail_on_stop_idx = None   # raise on Nth StopOrder placement

    def placeOrder(self, contract, order):
        is_modify = getattr(order, "orderId", 0) and any(
            t.order is order for t in self._trades
        )
        if not is_modify:
            if (self.fail_on_stop_idx is not None
                    and type(order).__name__ == "StopOrder"):
                n_stops = sum(1 for _, o in self.placed
                              if type(o).__name__ == "StopOrder")
                if n_stops == self.fail_on_stop_idx:
                    raise RuntimeError("synthetic stop submit failure")
            order.orderId = next(self._next_id)
            t = FakeIBTrade(contract, order)
            self._trades.append(t)
            self.placed.append((contract, order))
            return t
        # modification path — return existing trade
        for t in self._trades:
            if t.order is order:
                return t
        raise AssertionError("modify of unknown order")

    def cancelOrder(self, order):
        self.cancelled.append(order)
        for t in self._trades:
            if t.order is order:
                t._active = False

    def trades(self):
        return list(self._trades)

    async def qualifyContractsAsync(self, contract):
        return [contract]


def make_svc(fake_ib):
    """Bare IBDirectService with the network surface stubbed out."""
    from services.ib_direct_service import IBDirectService
    svc = IBDirectService.__new__(IBDirectService)
    svc._ib = fake_ib
    svc.config = SimpleNamespace(read_only=False)

    async def _connected():
        return True
    svc.ensure_connected = _connected
    svc.is_authorized_to_trade = lambda: True

    async def _tick(contract):
        return 0.01
    svc._resolve_min_tick = _tick
    svc.has_permanent_failure_error = lambda oid: None
    return svc


def make_trade(shares=100, entry=100.0, stop=99.0, style="scalp",
               targets=None, direction="long"):
    return SimpleNamespace(
        id="m0testtrade123456",
        symbol="TEST",
        direction=direction,
        trade_style=style,
        shares=shares,
        entry_price=entry,
        fill_price=entry,
        stop_price=stop,
        current_price=entry,
        mfe_price=entry,
        remaining_shares=shares,
        original_shares=shares,
        realized_pnl=0.0,
        target_prices=targets if targets is not None else [],
        target_order_ids=[],
        scale_out_config={"enabled": True, "targets_hit": [], "partial_exits": []},
        trailing_stop_config={"enabled": True, "mode": "original",
                              "original_stop": stop, "current_stop": stop},
    )


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset_manager_state(monkeypatch):
    import services.m0_ladder_manager as mgr
    mgr._SNAPSHOT["at"] = 0.0
    mgr._SNAPSHOT["ids"] = None
    mgr._LAST_SYNC_AT.clear()
    monkeypatch.setenv("IB_BRACKET_POLL_S", "0.2")
    yield


# ───────────────────── 1. registry ─────────────────────

class TestRegistryLadders:
    def test_scalp_default_is_3_rung_40_30_30(self):
        from services.order_policy_registry import get_policy
        l = get_policy("scalp").tp_ladder
        assert [(r.pct_of_position, r.r_multiple) for r in l] == [
            (0.40, 1.0), (0.30, 2.0), (0.30, 4.0)]

    def test_intraday_default_runner_cap_6r(self):
        from services.order_policy_registry import get_policy
        l = get_policy("intraday").tp_ladder
        assert [(r.pct_of_position, r.r_multiple) for r in l] == [
            (0.40, 1.0), (0.30, 2.0), (0.30, 6.0)]

    def test_long_horizon_ladders_unchanged(self):
        from services.order_policy_registry import get_policy
        assert [(r.pct_of_position, r.r_multiple)
                for r in get_policy("multi_day").tp_ladder] == [
            (0.33, 2.0), (0.33, 5.0), (0.34, 10.0)]

    def test_env_parser_valid(self, monkeypatch):
        from services.order_policy_registry import _ladder_from_env, TpLadderRung
        monkeypatch.setenv("X_LADDER", "0.5@1.5,0.5@3.0")
        out = _ladder_from_env("X_LADDER", [TpLadderRung(1.0, 2.0)])
        assert [(r.pct_of_position, r.r_multiple) for r in out] == [(0.5, 1.5), (0.5, 3.0)]

    @pytest.mark.parametrize("bad", [
        "0.9@1.0,0.3@2.0",        # pcts don't sum to 1
        "0.5@2.0,0.5@1.0",        # not ascending
        "1.0@1.0",                # single rung
        "garbage",                # unparseable
        "0.5@1.0,0.5@-2.0",       # negative r
    ])
    def test_env_parser_invalid_falls_back(self, monkeypatch, bad):
        from services.order_policy_registry import _ladder_from_env, TpLadderRung
        default = [TpLadderRung(0.4, 1.0), TpLadderRung(0.6, 2.0)]
        monkeypatch.setenv("X_LADDER", bad)
        assert _ladder_from_env("X_LADDER", default) is default


# ───────────────────── 2. ladder plan ─────────────────────

class TestLadderPlan:
    def _plan(self, trade, qty=None, stop=None):
        svc = make_svc(FakeIB())
        return svc._m0_ladder_plan(trade, qty or trade.shares,
                                   stop or trade.stop_price)

    def test_qty_split_exact_40_30_30(self):
        legs = self._plan(make_trade(shares=100))
        assert [l["qty"] for l in legs] == [40, 30, 30]
        assert sum(l["qty"] for l in legs) == 100

    def test_drift_absorbed_by_last_leg(self):
        legs = self._plan(make_trade(shares=17))
        assert sum(l["qty"] for l in legs) == 17
        assert all(l["qty"] >= 1 for l in legs)

    def test_r_multiple_prices_long(self):
        legs = self._plan(make_trade(shares=100, entry=100.0, stop=99.0))
        assert [l["target_px"] for l in legs] == [101.0, 102.0, 104.0]

    def test_r_multiple_prices_short(self):
        legs = self._plan(make_trade(shares=100, entry=100.0, stop=101.0,
                                     direction="short"))
        assert [l["target_px"] for l in legs] == [99.0, 98.0, 96.0]

    def test_single_far_explicit_target_is_ignored_M0a(self):
        # The live-session bug: scanner's lone target (≈2.6R out) must NOT
        # become leg 1 — all legs use R-math.
        legs = self._plan(make_trade(shares=100, targets=[108.55]))
        assert [l["target_px"] for l in legs] == [101.0, 102.0, 104.0]

    def test_full_monotonic_explicit_ladder_is_used(self):
        legs = self._plan(make_trade(shares=100,
                                     targets=[101.37, 102.5, 105.25]))
        assert [l["target_px"] for l in legs] == [101.37, 102.5, 105.25]

    def test_inverted_explicit_ladder_falls_back_to_r_math(self):
        legs = self._plan(make_trade(shares=100,
                                     targets=[105.0, 102.0, 103.0]))
        assert [l["target_px"] for l in legs] == [101.0, 102.0, 104.0]

    def test_short_descending_explicit_ladder_is_used(self):
        legs = self._plan(make_trade(shares=100, entry=100.0, stop=101.0,
                                     direction="short",
                                     targets=[98.8, 97.5, 94.0]))
        assert [l["target_px"] for l in legs] == [98.8, 97.5, 94.0]

    def test_short_ascending_explicit_rejected_r_math_used(self):
        legs = self._plan(make_trade(shares=100, entry=100.0, stop=101.0,
                                     direction="short",
                                     targets=[94.0, 97.5, 98.8]))
        assert [l["target_px"] for l in legs] == [99.0, 98.0, 96.0]

    def test_gate_min_shares(self):
        assert self._plan(make_trade(shares=9)) is None

    def test_gate_style(self):
        assert self._plan(make_trade(style="swing")) is None

    def test_gate_env_disabled(self, monkeypatch):
        monkeypatch.setenv("M0_LADDER_ENABLED", "false")
        assert self._plan(make_trade()) is None

    def test_gate_zero_risk(self):
        assert self._plan(make_trade(entry=100.0, stop=100.0)) is None


# ─────────────── 3. ladder placement at IB ───────────────

class TestLadderPlacement:
    def _place(self, trade, fake_ib=None):
        svc = make_svc(fake_ib or FakeIB())
        legs = svc._m0_ladder_plan(trade, trade.shares, trade.stop_price)
        assert legs
        return svc, run(svc._m0_place_oca_ladder(
            trade=trade, symbol=trade.symbol, qty=trade.shares,
            stop_px=trade.stop_price, legs=legs, action="SELL",
            tif_u="DAY", outside_rth=False, exchange="SMART", currency="USD",
        ))

    def test_happy_path_places_6_orders_stops_first(self):
        trade = make_trade(shares=100)
        svc, res = self._place(trade)
        assert res["success"] is True and res["m0_ladder"] is True
        kinds = [type(o).__name__ for _, o in svc._ib.placed]
        assert kinds == ["StopOrder"] * 3 + ["LimitOrder"] * 3
        assert len(res["legs"]) == 3
        assert sum(l["qty"] for l in res["legs"]) == 100

    def test_oca_groups_carry_trade_id_token_and_leg_suffix(self):
        trade = make_trade()
        _, res = self._place(trade)
        for i, g in enumerate(res["oca_groups"]):
            assert trade.id in g                  # v322k ownership token
            assert f"-L{i + 1}-" in g
        assert len(set(res["oca_groups"])) == 3   # one group PER leg

    def test_stop_and_target_share_their_legs_group(self):
        trade = make_trade()
        svc, res = self._place(trade)
        stops = [o for _, o in svc._ib.placed if type(o).__name__ == "StopOrder"]
        tgts = [o for _, o in svc._ib.placed if type(o).__name__ == "LimitOrder"]
        for s, t in zip(stops, tgts):
            assert s.ocaGroup == t.ocaGroup
            assert s.totalQuantity == t.totalQuantity

    def test_trade_state_stamped(self):
        trade = make_trade()
        _, res = self._place(trade)
        m0 = trade.scale_out_config["m0_legs"]
        assert len(m0) == 3 and all(l["status"] == "working" for l in m0)
        assert trade.scale_out_config["m0_ib_stop_px"] == 99.0
        # cancel-path coverage: all 3 target ids + stops of legs 2-3.
        assert len(trade.target_order_ids) == 5
        assert str(res["stop_order_id"]) not in trade.target_order_ids

    def test_stop_failure_rolls_back_everything(self):
        fake = FakeIB()
        fake.fail_on_stop_idx = 1   # second stop placement raises
        trade = make_trade()
        _, res = self._place(trade, fake)
        assert res["success"] is False
        assert "m0_stop_submit_failed_L2" in res["error"]
        assert len(fake.cancelled) == 1   # the one stop already placed
        assert not trade.scale_out_config.get("m0_legs")


# ─────────────── 4. modify_stop_price ───────────────

class TestModifyStop:
    def test_in_place_modify(self):
        fake = FakeIB()
        svc = make_svc(fake)
        from ib_async import StopOrder  # the service's own import source
        t = fake.placeOrder(SimpleNamespace(symbol="TEST"),
                            StopOrder("SELL", 40, 99.0))
        res = run(svc.modify_stop_price(t.order.orderId, 100.0))
        assert res["success"] is True and res["stop_price"] == 100.0
        assert t.order.auxPrice == 100.0
        assert not fake.cancelled            # NOT cancel/replace

    def test_unchanged_price_noop(self):
        fake = FakeIB()
        svc = make_svc(fake)
        from ib_async import StopOrder
        t = fake.placeOrder(SimpleNamespace(symbol="TEST"),
                            StopOrder("SELL", 40, 99.0))
        res = run(svc.modify_stop_price(t.order.orderId, 99.0))
        assert res["success"] is True and res.get("unchanged") is True

    def test_order_not_open(self):
        svc = make_svc(FakeIB())
        res = run(svc.modify_stop_price(424242, 100.0))
        assert res["success"] is False and res["error"] == "order_not_open"


# ─────────────── 5. m0_ladder_manager ───────────────

class FakeIbDirect:
    def __init__(self, open_ids=None, live_abs=0):
        self.open_ids = open_ids or []
        self.live_abs = live_abs
        self.modified = []   # (order_id, new_stop)

    async def get_open_orders(self):
        return [{"order_id": i} for i in self.open_ids]

    async def live_position_abs(self, symbol):
        return self.live_abs

    async def modify_stop_price(self, order_id, new_stop):
        self.modified.append((order_id, new_stop))
        return {"success": True, "order_id": order_id, "stop_price": new_stop}


def m0_trade_with_legs(**kw):
    t = make_trade(**kw)
    t.scale_out_config["m0_legs"] = [
        {"idx": 0, "qty": 40, "stop_order_id": 1, "target_order_id": 2,
         "stop_px": 99.0, "target_px": 101.0, "r_multiple": 1.0, "status": "working"},
        {"idx": 1, "qty": 30, "stop_order_id": 3, "target_order_id": 4,
         "stop_px": 99.0, "target_px": 102.0, "r_multiple": 2.0, "status": "working"},
        {"idx": 2, "qty": 30, "stop_order_id": 5, "target_order_id": 6,
         "stop_px": 99.0, "target_px": 104.0, "r_multiple": 4.0, "status": "working"},
    ]
    t.scale_out_config["m0_ib_stop_px"] = 99.0
    return t


def patch_ibd(monkeypatch, fake):
    import services.ib_direct_service as ibd_mod
    monkeypatch.setattr(ibd_mod, "get_ib_direct_service", lambda: fake)


class FakeBot:
    def __init__(self):
        self.notified = []

    async def _notify_trade_update(self, trade, reason):
        self.notified.append(reason)


class TestLegFillDetection:
    def test_leg1_tp_fill_stamps_targets_hit(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        trade.mfe_price = 101.2     # price reached T1 → TP attribution
        # legs 2,3 (ids 3..6) still open; leg 1 (1,2) gone; IB holds 60.
        fake = FakeIbDirect(open_ids=[3, 4, 5, 6], live_abs=60)
        patch_ibd(monkeypatch, fake)
        bot = FakeBot()
        run(manage_m0_trade(trade, bot))
        legs = trade.scale_out_config["m0_legs"]
        assert legs[0]["status"] == "filled_tp"
        assert trade.scale_out_config["targets_hit"] == [0]
        assert trade.remaining_shares == 60
        assert trade.realized_pnl == pytest.approx(40 * 1.0)   # 40sh × $1
        assert bot.notified == ["m0_leg_fill"]

    def test_stop_fill_attribution_no_targets_hit(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        trade.mfe_price = 100.3     # never reached T1 → stop attribution
        fake = FakeIbDirect(open_ids=[3, 4, 5, 6], live_abs=60)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert trade.scale_out_config["m0_legs"][0]["status"] == "filled_stop"
        assert trade.scale_out_config["targets_hit"] == []
        assert trade.realized_pnl == pytest.approx(40 * -1.0)

    def test_blank_snapshot_never_marks_fills(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        fake = FakeIbDirect(open_ids=[], live_abs=0)   # degraded read
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert all(l["status"] == "working"
                   for l in trade.scale_out_config["m0_legs"])

    def test_no_position_deficit_no_fills(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        # orders all working AND position intact.
        fake = FakeIbDirect(open_ids=[1, 2, 3, 4, 5, 6], live_abs=100)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert trade.remaining_shares == 100

    def test_non_m0_trade_is_noop(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = make_trade()
        patch_ibd(monkeypatch, FakeIbDirect())
        run(manage_m0_trade(trade, FakeBot()))   # must not raise


class TestStopSync:
    def test_breakeven_sync_modifies_all_working_stops(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        trade.scale_out_config["m0_legs"][0]["status"] = "filled_tp"
        trade.trailing_stop_config.update(mode="breakeven", current_stop=100.0)
        fake = FakeIbDirect(open_ids=[3, 4, 5, 6], live_abs=60)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert sorted(oid for oid, _ in fake.modified) == [3, 5]
        assert all(px == 100.0 for _, px in fake.modified)
        assert trade.scale_out_config["m0_ib_stop_px"] == 100.0

    def test_ratchet_only_long_never_loosens(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        trade.scale_out_config["m0_ib_stop_px"] = 100.0   # already at BE
        trade.trailing_stop_config.update(mode="breakeven", current_stop=99.5)
        fake = FakeIbDirect(open_ids=[1, 2, 3, 4, 5, 6], live_abs=100)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert fake.modified == []

    def test_sub_threshold_move_skipped(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        # 0.02 move < 0.1R (= $0.10 of the $1 risk)
        trade.trailing_stop_config.update(mode="trailing", current_stop=99.02)
        fake = FakeIbDirect(open_ids=[1, 2, 3, 4, 5, 6], live_abs=100)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert fake.modified == []

    def test_throttle_blocks_rapid_resync(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()
        trade.trailing_stop_config.update(mode="trailing", current_stop=100.0)
        fake = FakeIbDirect(open_ids=[1, 2, 3, 4, 5, 6], live_abs=100)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        n_first = len(fake.modified)
        assert n_first == 3
        trade.trailing_stop_config["current_stop"] = 100.5
        run(manage_m0_trade(trade, FakeBot()))   # within 30s window
        assert len(fake.modified) == n_first      # throttled

    def test_original_mode_never_syncs(self, monkeypatch):
        from services.m0_ladder_manager import manage_m0_trade
        trade = m0_trade_with_legs()   # mode stays 'original'
        fake = FakeIbDirect(open_ids=[1, 2, 3, 4, 5, 6], live_abs=100)
        patch_ibd(monkeypatch, fake)
        run(manage_m0_trade(trade, FakeBot()))
        assert fake.modified == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
