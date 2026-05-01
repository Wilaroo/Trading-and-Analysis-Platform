"""
test_autonomy_readiness_503_v19_30_4.py — proves v19.30.4 (2026-05-02)
keeps `/api/autonomy/readiness` from crashing with 500 on transient
event-loop wedges, and parallelises its 7 sub-checks.

Background
----------
2026-05-02 afternoon, after v19.30.1/.2/.3 went live, the operator's
log showed:

    INFO: 192.168.50.1:52310 - "GET /api/autonomy/readiness HTTP/1.1" 500
    asyncio.exceptions.CancelledError

Root cause: `readiness()` made 7 internal HTTP calls SEQUENTIALLY, each
with a 5s timeout. Worst-case latency = 35s — which lined up exactly
with the recurring 35-46s event-loop wedges (a third wedge class
v19.30.1/.2 don't address). When the loop wedged, all 7 awaits
cancelled, the httpx context exit raised `CancelledError`, and FastAPI
returned 500 — even though the operator only wanted to know "is the
bot ready to trade".

v19.30.4 fix has two layers:
  1. Parallelise — `asyncio.gather` runs all 7 sub-checks concurrently.
     Worst case drops from 35s → 5s. (And on a healthy loop, ~50ms.)
  2. Catch `CancelledError` / `TimeoutError` at the top level and
     raise `HTTPException(503)` with a structured body. 503 is the
     correct status for "service busy, try again", whereas 500 says
     "I crashed" which the operator's pusher logs flag as a real bug.

Both are covered below.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest


# ── 1. Source-level: gather + try/except CancelledError/TimeoutError ──
def test_readiness_uses_asyncio_gather():
    """The 7 sub-checks MUST run concurrently via asyncio.gather. Pre-fix
    they ran sequentially with 5s timeouts → 35s worst case."""
    src = (
        Path(__file__).resolve().parents[1]
        / "routers" / "autonomy_router.py"
    ).read_text()
    idx = src.find("async def readiness")
    assert idx >= 0
    # Slice to handler body (until next top-level def or end of file)
    body = src[idx:idx + 5000]
    assert "asyncio.gather(" in body, (
        "readiness() must run sub-checks via asyncio.gather to parallelise "
        "(7 sequential 5s timeouts = 35s worst case)"
    )
    # All 7 sub-check functions must be inside the gather call
    for fn in [
        "_check_account",
        "_check_pusher_rpc",
        "_check_live_bars",
        "_check_trophy_run",
        "_check_kill_switch",
        "_check_eod",
        "_check_risk_consistency",
    ]:
        assert f"{fn}(client)" in body, f"{fn} must be in the gather list"


def test_readiness_handles_cancelled_error_gracefully():
    """A loop-wedge cancellation MUST become a 503, not a 500. Pre-fix
    the operator's pusher saw 500s in its logs every time the loop
    wedged."""
    src = (
        Path(__file__).resolve().parents[1]
        / "routers" / "autonomy_router.py"
    ).read_text()
    idx = src.find("async def readiness")
    body = src[idx:idx + 5000]
    assert "asyncio.CancelledError" in body, (
        "readiness() must catch asyncio.CancelledError and return 503"
    )
    assert "asyncio.TimeoutError" in body, (
        "readiness() must catch asyncio.TimeoutError and return 503"
    )
    assert "status_code=503" in body, (
        "readiness() must raise HTTPException(503) on cancel — "
        "pre-fix it bubbled out as 500"
    )


# ── 2. server.py auto-stack-dump on event-loop wedge ──────────────────
def test_event_loop_monitor_dumps_task_stacks_on_wedge():
    """When the event loop is blocked >5s, the monitor MUST automatically
    dump every running asyncio task's stack to the log. This is the
    smoking gun for finding the next wedge's source without operator
    intervention (pre-fix the operator had to race py-spy)."""
    src = (
        Path(__file__).resolve().parents[1] / "server.py"
    ).read_text()
    # Find the _event_loop_monitor body
    idx = src.find("async def _event_loop_monitor")
    assert idx >= 0
    body = src[idx:idx + 4000]
    assert "asyncio.all_tasks()" in body, (
        "monitor must enumerate all running tasks for the stack dump"
    )
    assert "print_stack" in body, "monitor must call task.print_stack(...)"
    assert "ASYNCIO TASK STACK DUMP" in body, (
        "monitor must emit a clearly labelled stack-dump section so the "
        "operator can grep /tmp/backend.log for it"
    )
    assert "DUMP_COOLDOWN_S" in body or "cooldown" in body.lower(), (
        "monitor must rate-limit stack dumps (cooldown) so a sustained "
        "wedge doesn't spam the log"
    )


# ── 3. Behavioural — gather makes the 7 sub-checks parallel ───────────
@pytest.mark.asyncio
async def test_readiness_runs_sub_checks_in_parallel():
    """Mock the 7 sub-checks to each sleep 0.3s. With sequential they'd
    take ≥2.1s; with gather they should take ≈0.3s. Proves the
    concurrency fix is wired up correctly."""
    from routers import autonomy_router as mod

    async def _slow_check(_client):
        await asyncio.sleep(0.3)
        return {"status": "green", "detail": "ok"}

    async def _fake_get_json(_client, _path):
        return {"enabled": False}

    patches = [
        patch.object(mod, "_check_account", side_effect=_slow_check),
        patch.object(mod, "_check_pusher_rpc", side_effect=_slow_check),
        patch.object(mod, "_check_live_bars", side_effect=_slow_check),
        patch.object(mod, "_check_trophy_run", side_effect=_slow_check),
        patch.object(mod, "_check_kill_switch", side_effect=_slow_check),
        patch.object(mod, "_check_eod", side_effect=_slow_check),
        patch.object(mod, "_check_risk_consistency", side_effect=_slow_check),
        patch.object(mod, "_get_json", side_effect=_fake_get_json),
    ]
    for p in patches:
        p.start()
    try:
        t0 = time.monotonic()
        result = await mod.readiness()
        elapsed = time.monotonic() - t0
    finally:
        for p in patches:
            p.stop()

    assert result["verdict"] == "green"
    # Sequential would be ~2.1s. Parallel is ~0.3s. Allow generous slack
    # but require strictly < 1s (i.e., 3x faster than sequential).
    assert elapsed < 1.0, (
        f"7 sub-checks took {elapsed:.2f}s — gather is not parallelising "
        f"(expected ~0.3s, sequential would be ~2.1s)"
    )


# ── 4. Behavioural — CancelledError → 503, not 500 ───────────────────
@pytest.mark.asyncio
async def test_readiness_returns_503_on_cancelled_error():
    """When asyncio.gather raises CancelledError (operator's exact
    failure mode), readiness MUST raise HTTPException(503), not let
    the error bubble out as a 500."""
    from fastapi import HTTPException
    from routers import autonomy_router as mod

    async def _crashing_check(_client):
        raise asyncio.CancelledError("simulated loop-wedge cancel")

    patches = [
        patch.object(mod, "_check_account", side_effect=_crashing_check),
        patch.object(mod, "_check_pusher_rpc", side_effect=_crashing_check),
        patch.object(mod, "_check_live_bars", side_effect=_crashing_check),
        patch.object(mod, "_check_trophy_run", side_effect=_crashing_check),
        patch.object(mod, "_check_kill_switch", side_effect=_crashing_check),
        patch.object(mod, "_check_eod", side_effect=_crashing_check),
        patch.object(mod, "_check_risk_consistency", side_effect=_crashing_check),
    ]
    for p in patches:
        p.start()
    try:
        with pytest.raises(HTTPException) as excinfo:
            await mod.readiness()
    finally:
        for p in patches:
            p.stop()

    assert excinfo.value.status_code == 503, (
        f"CancelledError should produce 503, got {excinfo.value.status_code}"
    )
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail.get("verdict") == "red"
    assert detail.get("ready_for_autonomous") is False
    assert "loop_busy" in (detail.get("blockers") or [])
    assert detail.get("error_class") == "CancelledError"
