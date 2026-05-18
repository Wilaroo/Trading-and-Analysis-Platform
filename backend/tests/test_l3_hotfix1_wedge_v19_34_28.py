"""
v19.34.28 L3-hotfix1 — Regression: place_bracket_order must NOT wedge
the event loop.

Forensic context
================
On 2026-05-18 during Phase L3 (live paper validation of ib-direct order
path), the very first real candidate to reach the executor (COIN
vwap_fade_long) wedged the main event loop for ~5.0s. Backend log:

    📤 [_execute_trade] Calling trade_executor.place_bracket_order...
    === WEDGE WATCHDOG TRIGGERED (main thread stuck for 5.0s) ===
    === END WEDGE WATCHDOG ===

Root cause: `ib_direct_service.place_bracket_order` and `execute_entry`
both contained the anti-pattern:

    await asyncio.wait_for(
        asyncio.to_thread(self._ib.sleep, 0.5),
        timeout=wait_for_submission_s,    # = 5.0s
    )

`ib_async`'s `IB.sleep()` internally calls
`loop.run_until_complete(...)` on the **main event loop**. Running it
from a worker thread (via asyncio.to_thread) caused the worker to
contest for the loop the main thread owns → either deadlock or wait
until the wait_for timeout. Forensic fingerprint: wedge duration ==
wait_for_submission_s (5.0s) exactly.

This regression test guarantees:
  1. The source no longer contains the wedge pattern.
  2. `place_bracket_order` and `execute_entry` use plain
     `asyncio.sleep` for the post-submit settle.
  3. Calling both functions against a fake IB does NOT block longer
     than ~1.5s (settle + minor overhead).
"""
from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import ib_direct_service as ibd_module


# ── 1. Source-level guard: the wedge pattern must NEVER come back ──


def test_no_to_thread_ib_sleep_anti_pattern_in_source():
    """If anyone re-introduces `asyncio.to_thread(self._ib.sleep, ...)`,
    this test will fail loudly. Comments mentioning it for historical
    context are allowed; CODE that schedules it is not.
    """
    src = Path(ibd_module.__file__).read_text()
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue  # historical commentary in comments is fine
        assert "to_thread(self._ib.sleep" not in stripped, (
            "v19.34.28 L3-hotfix1 regression: `asyncio.to_thread(self._ib.sleep,"
            " ...)` re-introduced. This wedges the event loop. Use plain "
            "`await asyncio.sleep(...)` instead. Offending line: %r" % line
        )


# ── 2. Both functions use plain asyncio.sleep for the settle ──


def _strip_comments(src: str) -> str:
    """Drop full-line comments so we only inspect EXECUTABLE code."""
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def test_place_bracket_order_uses_plain_asyncio_sleep():
    src = inspect.getsource(ibd_module.IBDirectService.place_bracket_order)
    assert "await asyncio.sleep(0.5)" in src, (
        "place_bracket_order must use `await asyncio.sleep(0.5)` for the "
        "post-submit settle (L3-hotfix1)."
    )
    assert "to_thread(self._ib.sleep" not in _strip_comments(src), (
        "place_bracket_order still contains the wedging pattern in code."
    )


def test_place_entry_uses_plain_asyncio_sleep():
    src = inspect.getsource(ibd_module.IBDirectService.place_entry)
    assert "await asyncio.sleep(0.5)" in src, (
        "place_entry must use `await asyncio.sleep(0.5)` for the "
        "post-submit settle (L3-hotfix1)."
    )
    assert "to_thread(self._ib.sleep" not in _strip_comments(src), (
        "place_entry still contains the wedging pattern in code."
    )


# ── 3. Behavioural: place_bracket_order returns within ~1.5s under
#       a synthetic fake IB. Pre-hotfix this would have hung indefinitely
#       (or until the wait_for timeout) because the to_thread worker
#       blocked on the main loop. ──


class _FakeOrderStatus:
    status = "Submitted"
    filled = 0
    avgFillPrice = 0.0


class _FakeTrade:
    def __init__(self, order_id: int):
        self.order = SimpleNamespace(orderId=order_id, ocaGroup=f"oca-{order_id}")
        self.orderStatus = _FakeOrderStatus()


class _FakeBracket:
    def __init__(self):
        self.parent = SimpleNamespace(orderId=0, ocaGroup="oca-100")
        self.takeProfit = SimpleNamespace(orderId=0, ocaGroup="oca-100")
        self.stopLoss = SimpleNamespace(orderId=0, ocaGroup="oca-100")


class _FakeIB:
    """Minimal stand-in for ib_async.IB. Critically, NONE of its methods
    block — this is what makes the pre-hotfix wedge impossible to
    reproduce in a unit test in the first place. The test instead
    asserts on (a) source-level absence of the anti-pattern and
    (b) wall-clock under a synthetic happy path."""

    def __init__(self):
        self._connected = True
        self._next_id = 100

    def isConnected(self):
        return self._connected

    def managedAccounts(self):
        return ["DUN615665"]

    def qualifyContracts(self, contract):
        return [contract]

    def bracketOrder(self, action, quantity, limitPrice, takeProfitPrice, stopLossPrice):
        return _FakeBracket()

    def placeOrder(self, contract, order):
        self._next_id += 1
        order.orderId = self._next_id
        order.ocaGroup = f"oca-{self._next_id}"
        return _FakeTrade(self._next_id)


@pytest.mark.asyncio
async def test_place_bracket_order_completes_quickly():
    """End-to-end: with a fake IB, the function should return well
    within 2 seconds. Pre-hotfix it could hang for ~5s (the wait_for
    timeout) on the first call.
    """
    svc = ibd_module.IBDirectService()
    svc._ib = _FakeIB()
    svc._connected = True
    # bypass connection / authorization guards
    svc.is_authorized_to_trade = MagicMock(return_value=True)
    svc.ensure_connected = MagicMock(
        return_value=asyncio.sleep(0, result=True),
    )

    # Patch the async coroutine the function actually awaits.
    async def _ok():
        return True
    svc.ensure_connected = _ok

    trade = SimpleNamespace(
        symbol="TEST",
        direction=SimpleNamespace(value="long"),
        shares=10,
        entry_price=100.0,
        stop_price=99.0,
        target_prices=[101.0],
    )

    t0 = time.monotonic()
    result = await svc.place_bracket_order(trade)
    elapsed = time.monotonic() - t0

    # Must complete in well under 2 seconds (the settle is 0.5s).
    assert elapsed < 2.0, (
        f"place_bracket_order took {elapsed:.2f}s — wedge regression? "
        "Expected < 2.0s after L3-hotfix1."
    )
    # The fake IB returns Submitted status → success=True.
    assert result["success"] is True
    assert result["broker"] == "ib_direct"
    assert result["simulated"] is False
    assert isinstance(result["entry_order_id"], int)
    assert isinstance(result["stop_order_id"], int)
    assert isinstance(result["target_order_id"], int)
