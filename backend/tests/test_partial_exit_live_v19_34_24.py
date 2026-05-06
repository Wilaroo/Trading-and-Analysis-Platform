"""
test_partial_exit_live_v19_34_24.py — pins the v19.34.24 fix for the
missing ExecutorMode.LIVE branch in `execute_partial_exit`.

Bug class: `trade_executor_service.execute_partial_exit` only handled
SIMULATED + PAPER (Alpaca, disabled). When the manage loop detected a
target hit on a LIVE-mode trade and called into the executor, the
function fell off the end of the try block and implicitly returned
`None`. The caller in `position_manager.execute_partial_exit` then did
`result.get('success')` on None, raising AttributeError swallowed by
the broader manage-loop guard. Net effect: scale-outs silently no-op'd
in LIVE mode, and reconciled positions (which never get an IB-side OCA
bracket via the reconciler) had no way to fire targets at all.

Operator-discovered via FDX 2026-02-XX: price spiked through PT $374.44
+ $375.08, both reconciled legs sat unrealized at +$5,228 because
neither path could close them — no IB bracket existed AND the local
fire-the-target path was broken for LIVE.

v19.34.24 adds an `ExecutorMode.LIVE` branch that routes a standalone
MKT through the IB pusher queue (mirrors `_ib_close_position` without
the bracket-cancel prelude — bracket child cleanup after a partial fill
is the caller's responsibility via `bracket_reissue_service`).

Tests below cover:
  - LIVE long partial exit → SELL MKT queued with correct qty + filled
    fill_price returned (regression pin).
  - LIVE short partial exit → BUY MKT queued with correct qty.
  - LIVE pusher-disconnected → falls back to simulated success (matches
    `_ib_close_position` semantics, so caller's local state mutation
    stays consistent with paper-mode behaviour).
  - LIVE order rejected at IB → `success=False` with the rejection
    reason propagated.
  - LIVE timeout → `success=False` with explicit timeout error.
  - Defensive: SIMULATED mode still returns clean success (regression
    pin against the pre-existing path).
  - Unhandled mode (deliberately set to a bogus value) → explicit
    `success=False` instead of the pre-v19.34.24 implicit None.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.trade_executor_service import (  # noqa: E402
    ExecutorMode,
    TradeExecutorService,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_trade(direction: str = "long", trade_id: str = "T-FDX-1",
                symbol: str = "FDX", current_price: float = 375.88):
    """Build a minimal trade-shaped object for the executor.

    The executor only touches `direction.value`, `id`, `symbol`, and
    `current_price` on the partial-exit path.
    """
    return SimpleNamespace(
        id=trade_id,
        symbol=symbol,
        direction=SimpleNamespace(value=direction),
        current_price=current_price,
        shares=625,
    )


def _live_executor() -> TradeExecutorService:
    svc = TradeExecutorService()
    svc._mode = ExecutorMode.LIVE
    svc._initialized = True  # skip _ensure_initialized branching
    return svc


# ─────────────────────────────────────────────────────────────────────
# 1. LIVE long partial exit — happy path, MKT fills cleanly.
# ─────────────────────────────────────────────────────────────────────
def test_live_long_partial_exit_queues_sell_and_returns_fill():
    svc = _live_executor()
    trade = _make_trade(direction="long", current_price=375.88)

    queued_payloads = []

    def _fake_queue_order(payload):
        queued_payloads.append(payload)
        return "IB-ORD-99"

    fake_result = {
        "result": {
            "status": "filled",
            "fill_price": 375.92,
        }
    }

    with patch("routers.ib.queue_order", side_effect=_fake_queue_order), \
         patch("routers.ib.get_order_result", return_value=fake_result), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        out = _run(svc.execute_partial_exit(trade, shares=256))

    assert out["success"] is True, out
    assert out["fill_price"] == pytest.approx(375.92)
    assert out["shares"] == 256
    assert out["broker"] == "interactive_brokers"
    assert out["order_id"] == "IB-ORD-99"

    # Pusher payload contract — opposite side, MKT, partial qty.
    assert len(queued_payloads) == 1
    p = queued_payloads[0]
    assert p["symbol"] == "FDX"
    assert p["action"] == "SELL"          # long exit fires SELL
    assert p["quantity"] == 256           # partial, NOT full size
    assert p["order_type"] == "MKT"
    assert p["limit_price"] is None
    assert p["stop_price"] is None
    assert p["trade_id"] == "PARTIAL-T-FDX-1"


# ─────────────────────────────────────────────────────────────────────
# 2. LIVE short partial exit — closing direction is BUY.
# ─────────────────────────────────────────────────────────────────────
def test_live_short_partial_exit_queues_buy():
    svc = _live_executor()
    trade = _make_trade(direction="short", trade_id="T-BP-1",
                        symbol="BP", current_price=44.18)

    queued_payloads = []

    with patch("routers.ib.queue_order",
               side_effect=lambda p: queued_payloads.append(p) or "IB-OK"), \
         patch("routers.ib.get_order_result",
               return_value={"result": {"status": "filled",
                                        "fill_price": 44.10}}), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        out = _run(svc.execute_partial_exit(trade, shares=400))

    assert out["success"] is True
    assert queued_payloads[0]["action"] == "BUY"   # short exit fires BUY
    assert queued_payloads[0]["quantity"] == 400


# ─────────────────────────────────────────────────────────────────────
# 3. LIVE pusher disconnected — falls back to simulated success so the
#    caller's local state mutation matches paper-mode semantics.
# ─────────────────────────────────────────────────────────────────────
def test_live_pusher_disconnected_simulates_success():
    svc = _live_executor()
    trade = _make_trade(direction="long")

    with patch("routers.ib.is_pusher_connected", return_value=False):
        out = _run(svc.execute_partial_exit(trade, shares=100))

    assert out["success"] is True
    assert out["simulated"] is True
    assert out["fill_price"] == pytest.approx(trade.current_price)
    assert out["shares"] == 100
    assert out["order_id"].startswith("SIM-PARTIAL-")


# ─────────────────────────────────────────────────────────────────────
# 4. LIVE IB rejects the partial fill — propagate the error, do NOT
#    let the caller mutate local state.
# ─────────────────────────────────────────────────────────────────────
def test_live_partial_exit_rejected_propagates_failure():
    svc = _live_executor()
    trade = _make_trade(direction="long")

    fake_result = {
        "result": {
            "status": "rejected",
            "error": "INSUFFICIENT_QUANTITY",
        }
    }

    with patch("routers.ib.queue_order", return_value="IB-REJ-1"), \
         patch("routers.ib.get_order_result", return_value=fake_result), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        out = _run(svc.execute_partial_exit(trade, shares=50))

    assert out["success"] is False
    assert "INSUFFICIENT_QUANTITY" in out["error"]
    assert out["order_id"] == "IB-REJ-1"
    assert out["shares"] == 0


# ─────────────────────────────────────────────────────────────────────
# 5. LIVE timeout — get_order_result returns None.
# ─────────────────────────────────────────────────────────────────────
def test_live_partial_exit_timeout_returns_explicit_failure():
    svc = _live_executor()
    trade = _make_trade(direction="long")

    with patch("routers.ib.queue_order", return_value="IB-TIMEOUT-1"), \
         patch("routers.ib.get_order_result", return_value=None), \
         patch("routers.ib.is_pusher_connected", return_value=True):
        out = _run(svc.execute_partial_exit(trade, shares=10))

    assert out["success"] is False
    assert "Timeout" in out["error"]
    assert out["order_id"] == "IB-TIMEOUT-1"


# ─────────────────────────────────────────────────────────────────────
# 6. Regression: SIMULATED mode still returns clean success.
# ─────────────────────────────────────────────────────────────────────
def test_simulated_partial_exit_still_works():
    svc = TradeExecutorService()
    svc._mode = ExecutorMode.SIMULATED
    trade = _make_trade(direction="long")

    out = _run(svc.execute_partial_exit(trade, shares=42))

    assert out["success"] is True
    assert out["simulated"] is True
    assert out["fill_price"] == pytest.approx(trade.current_price)
    assert out["shares"] == 42


# ─────────────────────────────────────────────────────────────────────
# 7. Defensive: unhandled executor mode — pre-v19.34.24 returned None
#    implicitly and the caller crashed on `.get('success')`. Now we
#    surface the bug explicitly.
# ─────────────────────────────────────────────────────────────────────
def test_unhandled_mode_returns_explicit_failure_not_none():
    svc = TradeExecutorService()
    # Force an unrecognized mode (bypassing the Enum on purpose to
    # reproduce the pre-fix dead-end). The defensive branch must catch
    # it instead of letting the function fall off the end.
    svc._mode = "BOGUS_MODE"
    svc._initialized = True
    trade = _make_trade(direction="long")

    out = _run(svc.execute_partial_exit(trade, shares=1))

    assert out is not None  # the actual regression pin
    assert out["success"] is False
    assert "unhandled_executor_mode" in out["error"]
