"""
Tests for v19.34.103 — TP ladder expanded into multi-rung OCA `targets`
array in the IB bracket payload.

Validates:
  • Single-rung policies (scalp) → exactly 1 leg in targets[].
  • Multi-rung policies (position has 3 rungs at 25/25/50 %) → 3 legs.
  • Sum(quantities) across all rungs == trade.shares EXACTLY (drift
    absorbed into the last rung). IB OCA accounting must not drift.
  • Each leg shares the same TIF + outside_rth + action as the stop.
  • Limit prices come from the policy's r_multiple × risk_distance,
    or from explicit `trade.target_prices` when available.
  • Legacy `target: {...}` block always populated with the first rung
    so older pushers continue to work.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock

import pytest

from services.trade_executor_service import TradeExecutorService, ExecutorMode


class _Direction:
    def __init__(self, value: str):
        self.value = value


@dataclass
class FakeTrade:
    id: str
    symbol: str
    direction: _Direction
    setup_type: str
    timeframe: str
    trade_style: str
    entry_price: float
    stop_price: float
    shares: int
    target_prices: List[float] = field(default_factory=list)


def _capture(monkeypatch):
    captured = {}

    def fake_queue_order(payload):
        captured["payload"] = payload
        return "OID"

    def fake_get_order_result(_id, _to):
        return {"result": {"status": "working", "entry_order_id": 1,
                           "stop_order_id": 2, "target_order_id": 3,
                           "oca_group": "oca_x"}}

    monkeypatch.setattr("routers.ib.queue_order", fake_queue_order)
    monkeypatch.setattr("routers.ib.get_order_result", fake_get_order_result)
    monkeypatch.setattr("routers.ib.is_pusher_connected", lambda: True)

    async def _run(trade):
        ex = TradeExecutorService()
        ex._mode = ExecutorMode.LIVE
        ex._initialized = True
        ex._kill_switch_refusal = MagicMock(return_value=None)
        ex._maybe_schedule_shadow_observe = MagicMock(return_value=None)
        await ex._ib_bracket(trade)
        return captured["payload"]

    return _run


def _trade(style: str, shares: int = 100, targets=None) -> FakeTrade:
    return FakeTrade(
        id="T", symbol="MSFT", direction=_Direction("long"),
        setup_type="weekly_base", timeframe="1d", trade_style=style,
        entry_price=100.0, stop_price=95.0, shares=shares,
        target_prices=targets or [],
    )


class TestTpLadderShape:
    def test_scalp_has_single_target_rung(self, monkeypatch):
        run = _capture(monkeypatch)
        p = asyncio.run(run(_trade("scalp", shares=100)))
        assert isinstance(p["targets"], list)
        assert len(p["targets"]) == 1
        assert p["targets"][0]["quantity"] == 100
        # Scalp ladder is 100% @ +1R → entry 100 + 1*(100-95) = 105
        assert p["targets"][0]["limit_price"] == 105.0
        assert p["targets"][0]["r_multiple"] == 1.0

    def test_intraday_two_rung_ladder(self, monkeypatch):
        run = _capture(monkeypatch)
        p = asyncio.run(run(_trade("intraday", shares=100)))
        assert len(p["targets"]) == 2
        qty_sum = sum(t["quantity"] for t in p["targets"])
        assert qty_sum == 100
        # 50% @ 2R, 50% @ 5R → 50 @ 110, 50 @ 125
        assert p["targets"][0]["limit_price"] == 110.0
        assert p["targets"][1]["limit_price"] == 125.0

    def test_position_three_rung_ladder_sums_exact(self, monkeypatch):
        run = _capture(monkeypatch)
        # Position policy = 25% @ 4R, 25% @ 8R, 50% @ 15R
        p = asyncio.run(run(_trade("position", shares=101)))
        assert len(p["targets"]) == 3
        # 25/25/50 of 101 = 25/25/51 → sum = 101 (drift absorbed into last)
        qtys = [t["quantity"] for t in p["targets"]]
        assert sum(qtys) == 101, f"OCA accounting drift: {qtys}"
        assert qtys[2] >= qtys[0]  # last rung carries the bigger half
        assert p["targets"][0]["r_multiple"] == 4.0
        assert p["targets"][2]["r_multiple"] == 15.0

    def test_investment_three_rung_ladder(self, monkeypatch):
        run = _capture(monkeypatch)
        # Investment = 30% @ 3R, 30% @ 6R, 40% @ 12R
        p = asyncio.run(run(_trade("investment", shares=200)))
        assert len(p["targets"]) == 3
        qtys = [t["quantity"] for t in p["targets"]]
        assert sum(qtys) == 200
        assert qtys == [60, 60, 80]

    def test_swing_two_rung_ladder(self, monkeypatch):
        run = _capture(monkeypatch)
        # Swing = 50% @ 2R, 50% @ 5R
        p = asyncio.run(run(_trade("swing", shares=10)))
        assert len(p["targets"]) == 2
        assert sum(t["quantity"] for t in p["targets"]) == 10

    def test_target_leg_inherits_stop_tif_and_outside_rth(self, monkeypatch):
        run = _capture(monkeypatch)
        p = asyncio.run(run(_trade("position", shares=100)))
        for leg in p["targets"]:
            assert leg["time_in_force"] == p["stop"]["time_in_force"] == "GTC"
            assert leg["outside_rth"] == p["stop"]["outside_rth"] is True
            assert leg["order_type"] == "LMT"
            assert leg["action"] == "SELL"  # exit for a long

    def test_legacy_target_field_populated_with_first_rung(self, monkeypatch):
        """Older pushers without v19.34.103 support must still see a
        well-formed single-target leg matching the first rung."""
        run = _capture(monkeypatch)
        p = asyncio.run(run(_trade("position", shares=100)))
        assert p["target"]["limit_price"] == p["targets"][0]["limit_price"]
        assert p["target"]["quantity"] == p["targets"][0]["quantity"]
        assert p["target"]["time_in_force"] == p["targets"][0]["time_in_force"]

    def test_explicit_target_prices_override_r_multiple(self, monkeypatch):
        run = _capture(monkeypatch)
        # Operator/scanner provided explicit targets — those win for
        # the matching ladder index.
        trade = _trade("position", shares=100, targets=[107.5, 120.0, 200.0])
        p = asyncio.run(run(trade))
        assert p["targets"][0]["limit_price"] == 107.5
        assert p["targets"][1]["limit_price"] == 120.0
        assert p["targets"][2]["limit_price"] == 200.0

    def test_short_trade_uses_buy_to_cover_action(self, monkeypatch):
        run = _capture(monkeypatch)
        trade = FakeTrade(
            id="S", symbol="QQQ", direction=_Direction("short"),
            setup_type="lhld", timeframe="1d", trade_style="swing",
            entry_price=400.0, stop_price=410.0, shares=20,
            target_prices=[],
        )
        p = asyncio.run(run(trade))
        for leg in p["targets"]:
            assert leg["action"] == "BUY"
        # Short swing: 50% @ 2R, 50% @ 5R → entry - r*risk_distance
        # risk = 10 → 400 - 2*10 = 380, 400 - 5*10 = 350
        assert p["targets"][0]["limit_price"] == 380.0
        assert p["targets"][1]["limit_price"] == 350.0

    def test_tiny_position_still_allocates_at_least_one_share_per_rung(self, monkeypatch):
        run = _capture(monkeypatch)
        # 3 shares with a 25/25/50 ladder would round to 1/1/2 -
        # ensures we don't drop a rung to zero quantity.
        p = asyncio.run(run(_trade("position", shares=3)))
        for leg in p["targets"]:
            assert leg["quantity"] >= 1
        assert sum(t["quantity"] for t in p["targets"]) == 3
