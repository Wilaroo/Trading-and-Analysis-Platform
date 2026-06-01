"""
v19.34.196 — operator force-flatten an orphaned IB position by symbol.

`POST /api/trading-bot/positions/{symbol}/flatten` lets the operator flatten a
position that exists at IB but has NO bot trade_id (orphans the
/trades/{id}/close path can't touch). It reads the live IB position, cancels
every working order for the symbol (clears OCA brackets that trip IB's
15-order cap), then sends a MKT to flatten — bypassing the post-stop cooldown.
"""
import asyncio
import pytest
from fastapi import HTTPException

from routers.trading_bot import flatten_position_by_symbol


class _FakeIBD:
    def __init__(self, positions, connected=True, order_success=True):
        self._positions = positions
        self._connected = connected
        self._order_success = order_success
        self.market_orders = []
        self.cancelled_symbols = []
        self._cancel_before_order = None

    async def ensure_connected(self):
        return self._connected

    async def get_positions_fresh(self):
        return self._positions

    async def cancel_all_open_orders_for_symbol(self, sym, side=None):
        self.cancelled_symbols.append(sym.upper())
        return {"success": True, "cancelled": [101, 102]}

    async def place_market_order(self, sym, action, qty):
        # Record whether the cancel ran first (OCA must be cleared before MKT).
        self._cancel_before_order = list(self.cancelled_symbols)
        self.market_orders.append((sym.upper(), action, int(qty)))
        if self._order_success:
            return {"success": True, "order_id": 555, "perm_id": 999, "status": "Submitted"}
        return {"success": False, "error": "rejected"}


def _patch(monkeypatch, ibd):
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: ibd, raising=False,
    )


def _run(symbol):
    return asyncio.run(flatten_position_by_symbol(symbol, {"reason": "test"}))


# ── 1. long position → SELL MKT abs(net), cancel orders FIRST ─────────────
def test_flatten_long_sends_sell_after_cancel(monkeypatch):
    ibd = _FakeIBD([{"symbol": "AAPL", "position": 100, "sec_type": "STK"}])
    _patch(monkeypatch, ibd)
    out = _run("aapl")
    assert out["success"] is True
    assert out["action"] == "SELL" and out["quantity"] == 100
    assert ibd.market_orders == [("AAPL", "SELL", 100)]
    assert ibd.cancelled_symbols == ["AAPL"]
    assert ibd._cancel_before_order == ["AAPL"], "must cancel OCA before the MKT"


# ── 2. short position → BUY MKT abs(net) ──────────────────────────────────
def test_flatten_short_sends_buy(monkeypatch):
    ibd = _FakeIBD([{"symbol": "TSLA", "position": -50, "sec_type": "STK"}])
    _patch(monkeypatch, ibd)
    out = _run("TSLA")
    assert out["action"] == "BUY" and out["quantity"] == 50
    assert ibd.market_orders == [("TSLA", "BUY", 50)]


# ── 3. no position → nothing to flatten, no order ─────────────────────────
def test_flatten_no_position_is_noop(monkeypatch):
    ibd = _FakeIBD([{"symbol": "NVDA", "position": 0, "sec_type": "STK"}])
    _patch(monkeypatch, ibd)
    out = _run("NVDA")
    assert out["success"] is True
    assert "No open" in out["message"]
    assert ibd.market_orders == []


# ── 4. ib_direct not connected → 503 ──────────────────────────────────────
def test_flatten_not_connected_503(monkeypatch):
    ibd = _FakeIBD([], connected=False)
    _patch(monkeypatch, ibd)
    with pytest.raises(HTTPException) as ei:
        _run("AAPL")
    assert ei.value.status_code == 503


# ── 5. flatten order rejected → 400 ───────────────────────────────────────
def test_flatten_order_failure_400(monkeypatch):
    ibd = _FakeIBD(
        [{"symbol": "AMD", "position": 25, "sec_type": "STK"}],
        order_success=False,
    )
    _patch(monkeypatch, ibd)
    with pytest.raises(HTTPException) as ei:
        _run("AMD")
    assert ei.value.status_code == 400


# ── 6. blank symbol → 400 ─────────────────────────────────────────────────
def test_flatten_blank_symbol_400(monkeypatch):
    ibd = _FakeIBD([])
    _patch(monkeypatch, ibd)
    with pytest.raises(HTTPException) as ei:
        _run("   ")
    assert ei.value.status_code == 400
