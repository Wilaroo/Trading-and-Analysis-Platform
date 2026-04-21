"""Unit tests for PositionReconciler.protect_orphan_positions (Phase 4, 2026-04-22).

Uses monkeypatching to stub out IB/pusher IO so the emergency-stop logic
can be verified offline.
"""
import asyncio

import pytest

from services import position_reconciler as pr_mod


class _FakeTrade:
    def __init__(self, trade_id, symbol, stop_order_id=None, stop_price=None):
        self.id = trade_id
        self.symbol = symbol
        self.stop_order_id = stop_order_id
        self.stop_price = stop_price


class _FakeBot:
    def __init__(self, open_trades=None):
        self._open_trades = {t.id: t for t in (open_trades or [])}
        self.saved_trades = []

    async def _save_trade(self, trade):
        self.saved_trades.append(trade.id)


def _install_ib_stubs(monkeypatch, ib_positions, queue_orders_list, connected=True):
    """Install fake routers.ib symbols the reconciler reads."""
    class _FakeIBModule:
        _pushed_ib_data = {"positions": ib_positions}

        @staticmethod
        def is_pusher_connected():
            return connected

        @staticmethod
        def queue_order(payload):
            oid = f"oid-{len(queue_orders_list)}"
            queue_orders_list.append(payload)
            return oid

    import sys
    import types
    fake = types.ModuleType("routers.ib")
    fake._pushed_ib_data = _FakeIBModule._pushed_ib_data
    fake.is_pusher_connected = _FakeIBModule.is_pusher_connected
    fake.queue_order = _FakeIBModule.queue_order
    monkeypatch.setitem(sys.modules, "routers.ib", fake)


def test_skip_when_pusher_disconnected(monkeypatch):
    _install_ib_stubs(monkeypatch, [], [], connected=False)
    reconciler = pr_mod.PositionReconciler()
    bot = _FakeBot()
    r = asyncio.run(reconciler.protect_orphan_positions(bot))
    assert r["errors"] and "pusher" in r["errors"][0]["error"].lower()


def test_position_already_protected_counted_as_such(monkeypatch):
    positions = [{"symbol": "AAPL", "position": 100, "avgCost": 150.0}]
    orders = []
    _install_ib_stubs(monkeypatch, positions, orders)
    reconciler = pr_mod.PositionReconciler()
    trade = _FakeTrade("t1", "AAPL", stop_order_id="existing-stop", stop_price=148.0)
    bot = _FakeBot([trade])
    r = asyncio.run(reconciler.protect_orphan_positions(bot))
    assert len(r["already_protected"]) == 1
    assert r["already_protected"][0]["trade_id"] == "t1"
    assert len(orders) == 0            # no new order placed
    assert len(r["protected"]) == 0


def test_unprotected_tracked_trade_gets_stop_placed(monkeypatch):
    """Bot has the trade but stop_order_id is missing — use intended stop."""
    positions = [{"symbol": "MSFT", "position": 50, "avgCost": 400.0}]
    orders = []
    _install_ib_stubs(monkeypatch, positions, orders)
    reconciler = pr_mod.PositionReconciler()
    trade = _FakeTrade("t1", "MSFT", stop_order_id=None, stop_price=395.0)
    bot = _FakeBot([trade])
    r = asyncio.run(reconciler.protect_orphan_positions(bot))
    assert len(r["protected"]) == 1
    assert r["protected"][0]["stop_price"] == 395.0      # intended stop used
    assert orders[0]["order_type"] == "STP"
    assert orders[0]["action"] == "SELL"                 # long → SELL stop
    assert trade.stop_order_id == "oid-0"                # trade updated
    assert "t1" in bot.saved_trades


def test_untracked_short_uses_risk_pct(monkeypatch):
    """Short IB position with no matching bot trade → derive 1% emergency stop ABOVE avg."""
    positions = [{"symbol": "GNW", "position": -200, "avgCost": 8.05}]
    orders = []
    _install_ib_stubs(monkeypatch, positions, orders)
    reconciler = pr_mod.PositionReconciler()
    bot = _FakeBot([])
    r = asyncio.run(reconciler.protect_orphan_positions(bot, risk_pct=0.01))
    assert len(r["protected"]) == 1
    expected = round(8.05 * 1.01, 2)                     # short → stop ABOVE
    assert r["protected"][0]["stop_price"] == expected
    assert orders[0]["action"] == "BUY"                  # short → BUY stop


def test_dry_run_does_not_place_orders(monkeypatch):
    positions = [{"symbol": "PD", "position": 1000, "avgCost": 7.30}]
    orders = []
    _install_ib_stubs(monkeypatch, positions, orders)
    reconciler = pr_mod.PositionReconciler()
    bot = _FakeBot([])
    r = asyncio.run(reconciler.protect_orphan_positions(bot, dry_run=True))
    assert len(r["protected"]) == 1
    assert r["protected"][0]["dry_run"] is True
    assert len(orders) == 0


def test_skip_when_zero_avg_cost_and_no_intended_stop(monkeypatch):
    """Can't derive a stop if we have nothing to anchor on — skip, don't crash."""
    positions = [{"symbol": "XXX", "position": 100, "avgCost": 0}]
    orders = []
    _install_ib_stubs(monkeypatch, positions, orders)
    reconciler = pr_mod.PositionReconciler()
    bot = _FakeBot([])
    r = asyncio.run(reconciler.protect_orphan_positions(bot))
    assert len(r["skipped"]) == 1
    assert r["skipped"][0]["reason"] == "no_price_to_derive_stop"
    assert len(orders) == 0


def test_flat_position_ignored(monkeypatch):
    """Positions with |qty| < 1 (e.g., phantom residual) must be skipped."""
    positions = [{"symbol": "XXX", "position": 0.3, "avgCost": 100}]
    orders = []
    _install_ib_stubs(monkeypatch, positions, orders)
    reconciler = pr_mod.PositionReconciler()
    bot = _FakeBot([])
    r = asyncio.run(reconciler.protect_orphan_positions(bot))
    assert len(r["protected"]) == 0
    assert len(r["skipped"]) == 0
    assert len(orders) == 0
