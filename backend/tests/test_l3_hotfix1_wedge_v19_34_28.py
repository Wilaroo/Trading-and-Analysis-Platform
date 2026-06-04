"""v19.34.28 L3-hotfix1 — Regression: place_bracket_order must NOT wedge."""
from __future__ import annotations
import asyncio, inspect, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from services import ib_direct_service as ibd_module


def _strip_comments(src: str) -> str:
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


def test_no_to_thread_ib_sleep_anti_pattern_in_source():
    src = Path(ibd_module.__file__).read_text()
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "to_thread(self._ib.sleep" not in line, (
            "L3-hotfix1 regression: wedge pattern re-introduced: %r" % line
        )


def test_place_bracket_order_uses_plain_asyncio_sleep():
    src = inspect.getsource(ibd_module.IBDirectService.place_bracket_order)
    assert "await asyncio.sleep(0.5)" in src
    assert "to_thread(self._ib.sleep" not in _strip_comments(src)


def test_place_entry_uses_plain_asyncio_sleep():
    src = inspect.getsource(ibd_module.IBDirectService.place_entry)
    assert "await asyncio.sleep(0.5)" in src
    assert "to_thread(self._ib.sleep" not in _strip_comments(src)


class _FakeOrderStatus:
    status = "Submitted"; filled = 0; avgFillPrice = 0.0


class _FakeTrade:
    def __init__(self, oid):
        self.order = SimpleNamespace(orderId=oid, ocaGroup=f"oca-{oid}")
        self.orderStatus = _FakeOrderStatus()


class _FakeBracket:
    def __init__(self):
        self.parent = SimpleNamespace(orderId=0, ocaGroup="oca-100")
        self.takeProfit = SimpleNamespace(orderId=0, ocaGroup="oca-100")
        self.stopLoss = SimpleNamespace(orderId=0, ocaGroup="oca-100")


class _FakeIB:
    def __init__(self):
        self._connected = True; self._next_id = 100
    def isConnected(self): return self._connected
    def managedAccounts(self): return ["DUN615665"]
    def qualifyContracts(self, c): return [c]
    def bracketOrder(self, **kw): return _FakeBracket()
    def placeOrder(self, contract, order):
        self._next_id += 1
        order.orderId = self._next_id
        order.ocaGroup = f"oca-{self._next_id}"
        return _FakeTrade(self._next_id)


@pytest.mark.asyncio
async def test_place_bracket_order_completes_quickly():
    svc = ibd_module.IBDirectService()
    svc._ib = _FakeIB(); svc._connected = True
    svc.is_authorized_to_trade = MagicMock(return_value=True)
    async def _ok(): return True
    svc.ensure_connected = _ok
    trade = SimpleNamespace(
        symbol="TEST",
        direction=SimpleNamespace(value="long"),
        shares=10, entry_price=100.0, stop_price=99.0,
        target_prices=[101.0],
    )
    t0 = time.monotonic()
    result = await svc.place_bracket_order(trade)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0, f"place_bracket_order took {elapsed:.2f}s — wedge?"
    assert result["success"] is True
    assert result["broker"] == "ib_direct"
    assert isinstance(result["entry_order_id"], int)
