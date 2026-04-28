"""
Regression tests for the parked LiveHealthMonitor scaffold.

Locks the trip-wire conditions: pusher offline, account-guard mismatch,
RPC p99 spike, consecutive rejects, bot loop stale. Each condition
should fire `kill_switch_latch` exactly once via `_trip_killswitch`.

Pure-async tests, no DB / FastAPI. Verifies the safety contract before
the scaffold is wired into TradingBotService.
"""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from services import live_health_monitor as lhm


# ─── Helpers ────────────────────────────────────────────────────────────

class _FakeBot:
    """Bare-minimum bot stand-in that carries the attributes
    LiveHealthMonitor reads."""
    def __init__(self):
        self._last_pusher_heartbeat_ts = time.time()
        self._account_guard_status = {"ok": True}
        self._last_loop_iteration_ts = time.time()
        self.is_active = True
        self._trip_calls = []

    def kill_switch_latch(self, reason):
        self._trip_calls.append(reason)


@pytest.fixture
def bot():
    return _FakeBot()


@pytest.fixture
def monitor(bot):
    return lhm.LiveHealthMonitor(bot)


# ─── Trip-condition tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_trip_when_all_signals_healthy(monitor, bot):
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is False
    assert snap["trips"] == []
    assert bot._trip_calls == []


@pytest.mark.asyncio
async def test_trips_when_pusher_offline_more_than_60s(monitor, bot):
    bot._last_pusher_heartbeat_ts = time.time() - 75   # 75s old
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is True
    assert any("pusher_offline" in t for t in snap["trips"])
    assert len(bot._trip_calls) == 1


@pytest.mark.asyncio
async def test_trips_on_account_guard_mismatch(monitor, bot):
    bot._account_guard_status = {"ok": False, "reason": "different_account"}
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is True
    assert any("account_guard_mismatch" in t for t in snap["trips"])


@pytest.mark.asyncio
async def test_trips_on_rpc_p99_spike(monitor, bot):
    # Seed 100 RPC samples — 99 fast, 1 super-slow ⇒ p99 = slow value.
    for _ in range(99):
        monitor.record_rpc_latency_ms(50)
    monitor.record_rpc_latency_ms(8000)   # spike
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is True
    assert any("rpc_p99_" in t for t in snap["trips"])


@pytest.mark.asyncio
async def test_does_not_trip_on_few_rpc_samples(monitor, bot):
    """With only 10 samples, p99 is too noisy; we require ≥30."""
    for _ in range(10):
        monitor.record_rpc_latency_ms(8000)
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is False


@pytest.mark.asyncio
async def test_trips_on_consecutive_rejects(monitor, bot):
    for _ in range(5):
        monitor.record_order_outcome(accepted=False)
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is True
    assert any("consecutive_rejects" in t for t in snap["trips"])


@pytest.mark.asyncio
async def test_accepted_order_resets_consecutive_rejects(monitor, bot):
    for _ in range(4):
        monitor.record_order_outcome(accepted=False)
    monitor.record_order_outcome(accepted=True)   # resets
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["consecutive_rejects"] == 0
    assert snap["tripped"] is False


@pytest.mark.asyncio
async def test_trips_on_stale_bot_loop(monitor, bot):
    bot._last_loop_iteration_ts = time.time() - 120
    await monitor._check_once()
    snap = monitor.snapshot()
    assert snap["tripped"] is True
    assert any("bot_loop_stuck" in t for t in snap["trips"])


@pytest.mark.asyncio
async def test_killswitch_fired_with_full_reason_string(monitor, bot):
    """When multiple trips fire on the same tick, all are joined and
    surfaced via a single kill_switch_latch call."""
    bot._last_pusher_heartbeat_ts = time.time() - 75
    bot._last_loop_iteration_ts = time.time() - 120
    await monitor._check_once()
    assert len(bot._trip_calls) == 1
    reason = bot._trip_calls[0]
    assert "pusher_offline" in reason
    assert "bot_loop_stuck" in reason


@pytest.mark.asyncio
async def test_killswitch_fallback_pauses_bot_when_no_latch_method():
    """Bots without `kill_switch_latch` should at least flip is_active=False."""
    class _NoLatchBot:
        def __init__(self):
            self.is_active = True
            self._last_pusher_heartbeat_ts = time.time() - 75
    bare = _NoLatchBot()
    mon = lhm.LiveHealthMonitor(bare)
    await mon._check_once()
    assert bare.is_active is False
