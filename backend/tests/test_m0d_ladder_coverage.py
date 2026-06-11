"""
M0d (2026-06-12) — ladder coverage audit + top-up tests.

The CZR/IGV/KRE incident: legs 2..n of an M0 ladder were cancelled while
leg 1 survived. The binary naked check (stop_order_id ∈ live orders) read
the trades as fully protected, leaving 105/28/14 shares naked. M0d audits
ACTUAL covered quantity and tops-up the shortfall with one appended OCA leg.

Covers:
  1. _m0_coverage_scan — covered qty math + dead-leg mutation to 'lost'.
  2. _m0_furthest_lost_target — direction-aware target selection.
  3. ib_direct.m0_topup_leg — single appended OCA leg, never clobbers
     sibling leg records, stop-only fallback, id stamping.
  4. Sweep integration — partial coverage → top-up (clamped, flip-guard
     verified) and NO naked reissue; full coverage → no action; unverified
     IB side → skip top-up but still never naked-reissue.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.trading_bot_service import (
    _m0_coverage_scan,
    _m0_furthest_lost_target,
)
from tests.test_m0_ladder import FakeIB, make_svc, make_trade, run
from tests.test_naked_position_sweep_v19_34_127 import (
    _UNRELATED_ORDER,
    _make_bot,
    _make_executor,
    _make_trade,
    _patch_fetch,
    _patch_positions,
)


def _legs(*specs):
    """spec = (idx, qty, stop_order_id, status, stop_px, target_px)"""
    return [
        {"idx": i, "qty": q, "stop_order_id": sid, "status": st,
         "stop_px": spx, "target_px": tpx, "oca_group": f"G-{i}",
         "target_order_id": 900 + i}
        for (i, q, sid, st, spx, tpx) in specs
    ]


# ─── 1. coverage scan ────────────────────────────────────────────────────────

class TestCoverageScan:
    def test_full_coverage(self):
        t = SimpleNamespace(scale_out_config={"m0_legs": _legs(
            (0, 70, 201, "working", 28.72, 30.44),
            (1, 53, 202, "working", 28.72, 31.31),
            (2, 52, 203, "working", 28.72, 34.77),
        )})
        cov, spx, lost = _m0_coverage_scan(t, {"201", "202", "203"})
        assert cov == 175 and lost == 0 and spx == 28.72

    def test_partial_coverage_marks_dead_legs_lost(self):
        t = SimpleNamespace(scale_out_config={"m0_legs": _legs(
            (0, 70, 201, "working", 28.72, 30.44),
            (1, 53, 202, "working", 28.72, 31.31),
            (2, 52, 203, "working", 28.72, 34.77),
        )})
        cov, spx, lost = _m0_coverage_scan(t, {"201", "UNRELATED-1"})
        assert cov == 70 and lost == 2 and spx == 28.72
        statuses = [l["status"] for l in t.scale_out_config["m0_legs"]]
        assert statuses == ["working", "lost", "lost"]

    def test_filled_legs_ignored(self):
        t = SimpleNamespace(scale_out_config={"m0_legs": _legs(
            (0, 70, 201, "filled_tp", 28.72, 30.44),
            (1, 53, 202, "working", 29.10, 31.31),
        )})
        cov, spx, lost = _m0_coverage_scan(t, {"202"})
        assert cov == 53 and lost == 0 and spx == 29.10  # BE-moved stop px

    def test_non_m0_trade(self):
        assert _m0_coverage_scan(
            SimpleNamespace(scale_out_config={}), {"1"}) == (0, None, 0)


# ─── 2. furthest lost target ─────────────────────────────────────────────────

class TestFurthestLostTarget:
    def _trade(self, direction, statuses=("lost", "lost", "working")):
        return SimpleNamespace(
            direction=SimpleNamespace(value=direction),
            scale_out_config={"m0_legs": _legs(
                (0, 10, 201, statuses[0], 28.72, 30.44),
                (1, 10, 202, statuses[1], 28.72, 31.31),
                (2, 10, 203, statuses[2], 28.72, 34.77),
            )},
        )

    def test_long_takes_max(self):
        assert _m0_furthest_lost_target(self._trade("long")) == 31.31

    def test_short_takes_min(self):
        t = self._trade("short")
        assert _m0_furthest_lost_target(t) == 30.44

    def test_none_when_no_lost_legs(self):
        t = self._trade("long", statuses=("working", "working", "working"))
        assert _m0_furthest_lost_target(t) is None


# ─── 3. ib_direct.m0_topup_leg ───────────────────────────────────────────────

class TestTopupLeg:
    def test_places_stop_and_target_and_appends(self):
        fake = FakeIB()
        svc = make_svc(fake)
        trade = make_trade(shares=175)
        trade.scale_out_config["m0_legs"] = _legs(
            (0, 70, 201, "working", 28.72, 30.44),
            (1, 53, 202, "lost", 28.72, 31.31),
        )
        trade.target_order_ids = ["999"]
        res = run(svc.m0_topup_leg(
            trade, qty=105, stop_px=28.72, target_px=31.31, tif="DAY"))
        assert res["success"] is True and res["m0_topup"] is True
        assert res["qty"] == 105
        # stop placed FIRST, then target, same OCA group
        types = [type(o).__name__ for _, o in fake.placed]
        assert types == ["StopOrder", "LimitOrder"]
        assert fake.placed[0][1].ocaGroup == fake.placed[1][1].ocaGroup
        assert "m0testtrade123456" in fake.placed[0][1].ocaGroup
        assert "-L3-" in fake.placed[0][1].ocaGroup  # idx continues at 2 → L3
        # leg APPENDED — siblings untouched
        legs = trade.scale_out_config["m0_legs"]
        assert len(legs) == 3
        assert legs[0]["status"] == "working" and legs[1]["status"] == "lost"
        assert legs[2]["topup"] is True and legs[2]["status"] == "working"
        assert legs[2]["idx"] == 2 and legs[2]["qty"] == 105
        # ids appended, not clobbered
        assert trade.target_order_ids[0] == "999"
        assert str(res["stop_order_id"]) in trade.target_order_ids
        assert str(res["target_order_id"]) in trade.target_order_ids

    def test_stop_only_when_no_target(self):
        fake = FakeIB()
        svc = make_svc(fake)
        trade = make_trade(shares=100)
        trade.scale_out_config["m0_legs"] = _legs(
            (0, 50, 201, "working", 99.0, None))
        res = run(svc.m0_topup_leg(trade, qty=50, stop_px=99.0, target_px=None))
        assert res["success"] is True and res["target_order_id"] is None
        assert [type(o).__name__ for _, o in fake.placed] == ["StopOrder"]
        assert trade.scale_out_config["m0_legs"][-1]["target_order_id"] is None

    def test_qty_lt_1_rejected(self):
        svc = make_svc(FakeIB())
        res = run(svc.m0_topup_leg(make_trade(), qty=0, stop_px=99.0))
        assert res["success"] is False and "qty_lt_1" in res["error"]


# ─── 4. sweep integration ────────────────────────────────────────────────────

def _m0_sweep_trade(*, covered_stop="201", remaining=175):
    t = _make_trade(tid="t-czr", symbol="CZR", shares=remaining,
                    stop_order_id=covered_stop)
    t.remaining_shares = remaining
    t.direction = SimpleNamespace(value="long")
    t.stop_price = 28.72
    t.scale_out_config = {"m0_legs": _legs(
        (0, 70, 201, "working", 28.72, 30.44),
        (1, 53, 202, "working", 28.72, 31.31),
        (2, 52, 203, "working", 28.72, 34.77),
    )}
    t.last_bracket_attach_at = None
    return t


def _patch_topup(result=None):
    ibd = MagicMock()
    ibd.m0_topup_leg = AsyncMock(return_value=result or {
        "success": True, "stop_order_id": 555, "target_order_id": 556,
        "oca_group": "G-T", "m0_topup": True,
    })
    return patch("services.ib_direct_service.get_ib_direct_service",
                 return_value=ibd), ibd


@pytest.mark.asyncio
async def test_partial_coverage_triggers_clamped_topup_not_reissue():
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    trade = _m0_sweep_trade()
    bot = _make_bot(executor=executor, open_trades={"t-czr": trade})
    topup_patch, ibd = _patch_topup()

    # Only leg-1 stop (201) live; legs 2-3 dead. IB confirms 175 long.
    with _patch_fetch([{"ib_order_id": "201", "symbol": "CZR"},
                       _UNRELATED_ORDER]), \
         _patch_positions([{"symbol": "CZR", "position": 175}]), topup_patch:
        result = await bot._naked_position_sweep()

    assert result.get("m0_shortfall_found") == 1
    assert result.get("m0_topup_placed") == 1
    assert result["naked_found"] == 0          # never treated as naked
    executor.attach_oca_stop_target.assert_not_awaited()
    ibd.m0_topup_leg.assert_awaited_once()
    kw = ibd.m0_topup_leg.await_args.kwargs
    assert kw["qty"] == 105                    # 175 - 70 covered
    assert kw["stop_px"] == 28.72
    assert kw["target_px"] == 34.77            # furthest lost target (long)
    # dead legs were mutated to lost
    statuses = [l["status"] for l in trade.scale_out_config["m0_legs"]]
    assert statuses == ["working", "lost", "lost"]


@pytest.mark.asyncio
async def test_full_coverage_no_action():
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    trade = _m0_sweep_trade()
    bot = _make_bot(executor=executor, open_trades={"t-czr": trade})
    topup_patch, ibd = _patch_topup()

    with _patch_fetch([{"ib_order_id": "201", "symbol": "CZR"},
                       {"ib_order_id": "202", "symbol": "CZR"},
                       {"ib_order_id": "203", "symbol": "CZR"}]), \
         _patch_positions([{"symbol": "CZR", "position": 175}]), topup_patch:
        result = await bot._naked_position_sweep()

    assert result.get("m0_shortfall_found") is None
    ibd.m0_topup_leg.assert_not_awaited()
    executor.attach_oca_stop_target.assert_not_awaited()
    assert result["naked_found"] == 0


@pytest.mark.asyncio
async def test_unverified_ib_side_skips_topup_but_never_reissues():
    executor = _make_executor()
    executor.attach_oca_stop_target = AsyncMock()
    trade = _m0_sweep_trade()
    bot = _make_bot(executor=executor, open_trades={"t-czr": trade})
    topup_patch, ibd = _patch_topup()

    # IB positions show a DIFFERENT symbol only → CZR side unverifiable.
    with _patch_fetch([{"ib_order_id": "201", "symbol": "CZR"},
                       _UNRELATED_ORDER]), \
         _patch_positions([{"symbol": "AAPL", "position": 10}]), topup_patch:
        result = await bot._naked_position_sweep()

    assert result.get("m0_shortfall_found") == 1
    ibd.m0_topup_leg.assert_not_awaited()      # no blind top-up
    executor.attach_oca_stop_target.assert_not_awaited()
    assert result["naked_found"] == 0


@pytest.mark.asyncio
async def test_whole_ladder_dead_falls_through_to_naked_reissue():
    executor = _make_executor(oca_result={
        "success": True, "stop_order_id": "STP-NEW", "oca_group": "OCA-NEW",
    })
    trade = _m0_sweep_trade(covered_stop="201")
    bot = _make_bot(executor=executor, open_trades={"t-czr": trade})
    topup_patch, ibd = _patch_topup()

    # NO ladder stop live at all → covered == 0 → standard naked path.
    with _patch_fetch([_UNRELATED_ORDER]), \
         _patch_positions([{"symbol": "CZR", "position": 175}]), topup_patch, \
         patch("services.bracket_reissue_service._persist_lifecycle_event",
               new_callable=AsyncMock):
        result = await bot._naked_position_sweep()

    ibd.m0_topup_leg.assert_not_awaited()
    assert result["naked_found"] == 1
    assert result["reissued"] == 1
    statuses = [l["status"] for l in trade.scale_out_config["m0_legs"]]
    assert statuses == ["lost", "lost", "lost"]
