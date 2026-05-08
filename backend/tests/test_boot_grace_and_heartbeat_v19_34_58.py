"""
v19.34.57 / v19.34.58 — boot-grace, retry, and heartbeat tests.

These are pure unit tests covering the small additions:
  * PusherRotationService._loop_body sleeps BOOT_GRACE_S before its
    first rotation and retries once on `pusher_unreachable`.
  * IBDirectService._heartbeat_check flips the service to disconnected
    when the heartbeat raises.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from services import pusher_rotation_service as prs


# ────────────────────────────────────────────────────────────────────
# v19.34.57 — boot grace + first-cycle retry on pusher_unreachable
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_body_sleeps_boot_grace_before_first_rotation(monkeypatch):
    """The rotation loop must sleep BOOT_GRACE_S before its first
    rotate_once call so the pusher RPC has time to warm up."""
    sleep_calls = []

    real_sleep = asyncio.sleep

    async def _spy_sleep(delay):
        sleep_calls.append(delay)
        # Make the loop exit promptly after first iteration.
        if len(sleep_calls) >= 2:
            svc._running = False
        await real_sleep(0)

    svc = prs.PusherRotationService(
        db=None, bot=None, pusher_client=MagicMock(),
    )
    svc._running = True
    svc.rotate_once = MagicMock(return_value={"applied": True})

    monkeypatch.setattr(asyncio, "sleep", _spy_sleep)
    await svc._loop_body()

    # First sleep should be BOOT_GRACE_S (boot grace), and rotate_once
    # should have been called.
    assert sleep_calls[0] == prs.PusherRotationService.BOOT_GRACE_S
    svc.rotate_once.assert_called()


@pytest.mark.asyncio
async def test_loop_body_retries_on_pusher_unreachable(monkeypatch):
    """First-cycle pusher_unreachable triggers exactly one retry."""
    real_sleep = asyncio.sleep

    async def _no_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    svc = prs.PusherRotationService(
        db=None, bot=None, pusher_client=MagicMock(),
    )
    svc._running = True

    call_log = []

    def _rotate_once():
        call_log.append("rotate")
        # First call returns pusher_unreachable, second succeeds.
        if len(call_log) == 1:
            return {"applied": False, "error": "pusher_unreachable"}
        svc._running = False
        svc._last_rotation = {"applied": True}
        return {"applied": True}

    svc.rotate_once = _rotate_once

    await svc._loop_body()

    assert call_log == ["rotate", "rotate"], (
        f"expected exactly one retry on first-cycle pusher_unreachable, "
        f"got call sequence: {call_log}"
    )


@pytest.mark.asyncio
async def test_loop_body_does_not_retry_on_second_cycle(monkeypatch):
    """Steady-state pusher_unreachable does NOT retry — wait for next
    LOOP_TICK_SECONDS instead."""
    real_sleep = asyncio.sleep

    async def _no_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    svc = prs.PusherRotationService(
        db=None, bot=None, pusher_client=MagicMock(),
    )
    svc._running = True
    # Pretend the first cycle already happened.
    svc._last_rotation = {"applied": True, "ts": "x"}

    call_log = []

    def _rotate_once():
        call_log.append("rotate")
        svc._running = False
        return {"applied": False, "error": "pusher_unreachable"}

    svc.rotate_once = _rotate_once

    # Force a refresh due so rotate_once is invoked at all.
    with patch.object(svc, "_is_refresh_due", return_value=(True, "test_forced")):
        await svc._loop_body()

    assert call_log == ["rotate"], (
        "second-cycle pusher_unreachable must NOT trigger a retry "
        f"(got {call_log})"
    )


# ────────────────────────────────────────────────────────────────────
# v19.34.58 — IB-direct heartbeat marks socket dropped on failure
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_failure_flips_service_to_disconnected():
    from services import ib_direct_service

    svc = ib_direct_service.IBDirectService()
    fake_ib = MagicMock()
    fake_ib.isConnected.return_value = True

    async def _raises(*_a, **_k):
        raise ConnectionError("simulated half-open socket")

    fake_ib.reqCurrentTimeAsync = _raises
    svc._ib = fake_ib
    svc._connected = True
    svc._authorized_to_trade = True

    ok = await svc._heartbeat_check()

    assert ok is False
    assert svc._connected is False
    assert svc._authorized_to_trade is False
    assert svc._heartbeat_failures_total == 1
    assert svc._drop_count_total == 1
    assert svc._last_drop_reason and "heartbeat_failed" in svc._last_drop_reason


@pytest.mark.asyncio
async def test_heartbeat_success_records_timestamp():
    from services import ib_direct_service

    svc = ib_direct_service.IBDirectService()
    fake_ib = MagicMock()
    fake_ib.isConnected.return_value = True

    async def _ok(*_a, **_k):
        return "2026-02-08 10:00:00"

    fake_ib.reqCurrentTimeAsync = _ok
    svc._ib = fake_ib
    svc._connected = True

    ok = await svc._heartbeat_check()

    assert ok is True
    assert svc._last_heartbeat_ok_at is not None
    assert svc._heartbeat_failures_total == 0
    assert svc._connected is True


@pytest.mark.asyncio
async def test_heartbeat_timeout_marks_dropped():
    from services import ib_direct_service

    svc = ib_direct_service.IBDirectService()
    # Tighten the deadline so the test exits fast.
    svc._HEARTBEAT_DEADLINE_S = 0.05

    fake_ib = MagicMock()
    fake_ib.isConnected.return_value = True

    async def _slow(*_a, **_k):
        await asyncio.sleep(1.0)
        return "never"

    fake_ib.reqCurrentTimeAsync = _slow
    svc._ib = fake_ib
    svc._connected = True

    ok = await svc._heartbeat_check()

    assert ok is False
    assert svc._connected is False
    assert "heartbeat_failed" in (svc._last_drop_reason or "")


def test_status_dict_includes_heartbeat_metrics():
    from services import ib_direct_service

    svc = ib_direct_service.IBDirectService()
    svc._heartbeat_failures_total = 7
    svc._last_heartbeat_ok_at = 1234.0
    svc._last_heartbeat_failed_at = 1240.0

    out = svc._status_dict("disconnected")
    stab = out["stability"]
    assert stab["heartbeat_failures_total"] == 7
    assert stab["last_heartbeat_ok_at"] == 1234.0
    assert stab["last_heartbeat_failed_at"] == 1240.0
