"""
v19.34.43 — Flatten-All parallel close regression
=====================================================

Pins the parallelization fix that resolved operator-caught
`FLATTEN FAILED — timeout of 30000ms exceeded` on the BMNR
pre-consolidation 19-fragment day.

Asserts:
 1. With N=30 open trades, all 30 closes are dispatched concurrently
    (verified by checking the close_trade calls finish in time bounded
    by ceil(N/8) batches × per-call latency, NOT N × latency).
 2. Failures in some closes don't abort the loop — the others still complete.
 3. Concurrency is capped at 8 (no thundering-herd against IB).
"""
from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, "/app/backend")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mk_trades(n):
    return [SimpleNamespace(
        id=f"t{i}", symbol=f"SYM{i}",
        direction=SimpleNamespace(value="long"),
        remaining_shares=100,
        entry_time="2026-05-08T10:00:00+00:00",
    ) for i in range(n)]


def test_flatten_all_runs_closes_in_parallel_under_concurrency_cap():
    """30 closes, each taking 0.5s, must finish in < 5s thanks to sema=8."""
    from routers.safety_router import flatten_all

    trades = _mk_trades(30)
    fake_bot = MagicMock()
    fake_bot._open_trades = {t.id: t for t in trades}

    in_flight = {"current": 0, "max": 0}
    lock = asyncio.Lock()

    async def slow_close(trade_id, reason="emergency_flatten_all"):
        async with lock:
            in_flight["current"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["current"])
        await asyncio.sleep(0.5)
        async with lock:
            in_flight["current"] -= 1
        return True

    fake_bot.close_trade.side_effect = slow_close

    # Patch the singleton accessor used by flatten_all and motor client
    # to keep the cancel-queue step from doing real DB work.
    motor_mod = MagicMock()
    motor_mod.motor_asyncio.AsyncIOMotorClient.return_value.__getitem__.return_value.order_queue.update_many = MagicMock(
        return_value=_make_async_result(0)
    )

    with patch("services.trading_bot_service.get_trading_bot_service", return_value=fake_bot), \
         patch.dict("sys.modules", {"motor": motor_mod, "motor.motor_asyncio": motor_mod.motor_asyncio}):
        t0 = time.monotonic()
        result = _run(flatten_all(confirm="FLATTEN"))
        elapsed = time.monotonic() - t0

    # 30 closes × 0.5s sequential = 15s. With sema=8 it's ⌈30/8⌉=4 batches × 0.5s ≈ 2s.
    # Generous bound to absorb test scheduler jitter.
    assert elapsed < 5.0, f"flatten took {elapsed:.2f}s — not parallelized?"
    # Concurrency cap respected.
    assert in_flight["max"] <= 8, f"concurrency exceeded cap-8: max={in_flight['max']}"
    # All 30 succeeded.
    assert result["summary"]["positions_succeeded"] == 30
    assert result["summary"]["positions_failed"] == 0
    assert result["success"] is True


def test_flatten_all_partial_failures_do_not_abort_others():
    """Closes that raise must not stop other closes from running."""
    from routers.safety_router import flatten_all

    trades = _mk_trades(10)
    fake_bot = MagicMock()
    fake_bot._open_trades = {t.id: t for t in trades}

    async def selective_close(trade_id, reason="emergency_flatten_all"):
        # Every other trade fails.
        if int(trade_id[1:]) % 2 == 0:
            raise RuntimeError("simulated IB hiccup")
        return True

    fake_bot.close_trade.side_effect = selective_close

    motor_mod = MagicMock()
    motor_mod.motor_asyncio.AsyncIOMotorClient.return_value.__getitem__.return_value.order_queue.update_many = MagicMock(
        return_value=_make_async_result(0)
    )

    with patch("services.trading_bot_service.get_trading_bot_service", return_value=fake_bot), \
         patch.dict("sys.modules", {"motor": motor_mod, "motor.motor_asyncio": motor_mod.motor_asyncio}):
        result = _run(flatten_all(confirm="FLATTEN"))

    s = result["summary"]
    assert s["positions_requested_close"] == 10
    assert s["positions_succeeded"] == 5
    assert s["positions_failed"] == 5
    assert len(s["close_errors"]) == 5
    # `success` is True because at least one close worked.
    assert result["success"] is True


def _make_async_result(modified_count):
    """Helper: build an awaitable that resolves to a UpdateResult-shaped object."""
    class _Res:
        def __init__(self, mc):
            self.modified_count = mc

    async def _coro():
        return _Res(modified_count)

    return _coro()
