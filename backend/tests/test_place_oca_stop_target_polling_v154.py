"""Offline unit tests for v19.34.154 `place_oca_stop_target` polling.

Verifies the post-place polling layer that classifies async IB
rejections into `permanent_failure`, `stop_terminal_reject`, and
`partial=True` outcomes — pre-v154 the function returned
`success=True` unconditionally as soon as both `placeOrder` calls
completed, even though IB could reject either leg ~100-2000ms later.

These tests stub `ib_async` primitives so the suite runs without
DGX / IB Gateway.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_place_oca_stop_target_polling_v154.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from dataclasses import dataclass, field
from typing import List, Optional

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ── Fake order-status objects ───────────────────────────────────────


@dataclass
class _FakeOrderStatus:
    status: str = "Submitted"
    filled: int = 0
    avgFillPrice: float = 0.0


@dataclass
class _FakeOrder:
    orderId: int = 0
    permId: int = 0


@dataclass
class _FakeTrade:
    order: _FakeOrder = field(default_factory=_FakeOrder)
    orderStatus: _FakeOrderStatus = field(default_factory=_FakeOrderStatus)


class _FakeIB:
    """Minimal mock that mimics `ib_async.IB` for the bits
    `place_oca_stop_target` touches: `qualifyContractsAsync`,
    `reqContractDetailsAsync`, `placeOrder`, `cancelOrder`.
    """
    def __init__(self):
        self._next_id = 1000
        self.placed: List[_FakeTrade] = []
        self.cancelled: List[int] = []
        # `errorEvent` mirrors ib_async's regular subscribable list.
        self._error_handlers = []
        self.errorEvent = self._EventList(self._error_handlers)
        # `final_status_per_id` lets tests pre-program each leg's
        # eventual orderStatus (e.g., 'Cancelled' after 200ms).
        self.final_status_per_id: dict = {}

    def isConnected(self):
        return True

    async def qualifyContractsAsync(self, contract):
        return [contract]

    async def reqContractDetailsAsync(self, contract):
        # Bare-minimum object with `.minTick`
        class _D: minTick = 0.01
        return [_D()]

    def placeOrder(self, contract, order):
        self._next_id += 1
        oid = self._next_id
        order.orderId = oid
        tr = _FakeTrade(order=order, orderStatus=_FakeOrderStatus(status="Submitted"))
        self.placed.append(tr)
        # Schedule the eventual status flip if pre-programmed.
        rule = self.final_status_per_id.get(len(self.placed) - 1)
        if rule:
            async def _flip():
                await asyncio.sleep(rule["delay_s"])
                tr.orderStatus.status = rule["status"]
                # If the rule includes an error event, fire it.
                for ec, msg in rule.get("errors", []):
                    for h in self._error_handlers:
                        try:
                            h(oid, ec, msg, contract)
                        except Exception:
                            pass
            asyncio.get_event_loop().create_task(_flip())
        return tr

    def cancelOrder(self, order):
        self.cancelled.append(int(order.orderId))

    # ib_async exposes `errorEvent` as a += subscribable.
    class _EventList:
        def __init__(self, sink): self._sink = sink
        def __iadd__(self, handler):
            self._sink.append(handler)
            return self


# ── Test fixtures ───────────────────────────────────────────────────


@pytest.fixture
def fake_trade():
    class _T:
        symbol = "TEST"
        id = "trade-abc"
        shares = 100
        stop_price = 99.0
        target_prices = [101.0]
        class direction:
            value = "long"
    return _T()


@pytest.fixture
def svc():
    """Build a real IBDirectService with `_ib` swapped for our fake."""
    from services.ib_direct_service import IBDirectService
    s = IBDirectService()
    s._ib = _FakeIB()
    s._connected = True
    s._authorized_to_trade = True
    # Wire the errorEvent handler the way `connect()` does.
    def _on_error(reqId, errorCode, errorString, contract=None):
        try:
            rid = int(reqId)
        except Exception:
            return
        if rid <= 0:
            return
        s._order_errors.setdefault(rid, []).append(
            (int(errorCode), str(errorString)[:240], time.time())
        )
    s._ib.errorEvent += _on_error
    # Bypass ensure_connected (we're already "connected" via fakes).
    async def _ensure(): return True
    s.ensure_connected = _ensure  # type: ignore
    return s


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_both_legs_working_returns_success(svc, fake_trade):
    """Happy path: both legs Submitted, no errors → success=True,
    permanent_failure=False, partial=False."""
    os.environ["IB_BRACKET_POLL_S"] = "0.5"
    res = await svc.place_oca_stop_target(fake_trade)
    assert res["success"] is True
    assert res["permanent_failure"] is False
    assert res["partial"] is False
    assert res["stop_status"] == "working"
    assert res["target_status"] == "working"
    assert res["stop_order_id"] is not None
    assert res["target_order_id"] is not None


@pytest.mark.asyncio
async def test_target_reg_t_201_marks_permanent_failure(svc, fake_trade):
    """LMT (2nd placeOrder) gets Error 201 ~100ms after submission →
    permanent_failure=True, target_order_id=None in return, partial=True,
    overall success=True (STP is still alive)."""
    os.environ["IB_BRACKET_POLL_S"] = "1.0"
    # Index 1 is the LMT (placed second).
    svc._ib.final_status_per_id[1] = {
        "delay_s": 0.1,
        "status": "Cancelled",
        "errors": [(201, "Order rejected - REG-T margin would result")],
    }
    res = await svc.place_oca_stop_target(fake_trade)
    assert res["permanent_failure"] is True
    assert res["target_error_code"] == 201
    assert res["target_order_id"] is None  # Nulled because tp_alive=False
    assert res["stop_status"] == "working"
    assert res["success"] is True  # STP is alive
    assert res["partial"] is True


@pytest.mark.asyncio
async def test_stop_reject_triggers_target_cancel_and_failure(svc, fake_trade):
    """STP (1st placeOrder) gets Error 201 → cancel TP, return
    success=False with stop_terminal_reject=True so caller emergency-
    flattens the naked position."""
    os.environ["IB_BRACKET_POLL_S"] = "1.0"
    svc._ib.final_status_per_id[0] = {
        "delay_s": 0.1,
        "status": "Cancelled",
        "errors": [(201, "REG-T")],
    }
    res = await svc.place_oca_stop_target(fake_trade)
    assert res["success"] is False
    assert res["stop_terminal_reject"] is True
    assert res["stop_error_code"] == 201
    assert res["permanent_failure"] is True
    # TP should have been cancelled to avoid one-sided exposure.
    assert len(svc._ib.cancelled) == 1


@pytest.mark.asyncio
async def test_transient_target_cancel_no_permanent_code(svc, fake_trade):
    """LMT gets cancelled with NO error code (just a Cancelled status,
    e.g. operator hit cancel) → permanent_failure=False, target ID
    nulled, partial=True. STP still alive → success=True."""
    os.environ["IB_BRACKET_POLL_S"] = "1.0"
    svc._ib.final_status_per_id[1] = {
        "delay_s": 0.1,
        "status": "Cancelled",
        "errors": [],
    }
    res = await svc.place_oca_stop_target(fake_trade)
    assert res["success"] is True
    assert res["permanent_failure"] is False
    assert res["partial"] is True
    assert res["target_status"].startswith("terminal_cancelled")


@pytest.mark.asyncio
async def test_polling_window_is_bounded(svc, fake_trade):
    """Polling shouldn't hang if both legs stay Submitted — must
    return within ~poll_s + small slack."""
    os.environ["IB_BRACKET_POLL_S"] = "0.4"
    t0 = asyncio.get_event_loop().time()
    res = await svc.place_oca_stop_target(fake_trade)
    elapsed = asyncio.get_event_loop().time() - t0
    assert elapsed < 1.5, f"polling took too long: {elapsed:.2f}s"
    assert res["success"] is True
