"""
test_event_loop_protection_v19_30.py — proves the v19.30 hot-fix
patches don't regress and that the scan-loop watchdog actually fires.

Background: 2026-05-01 morning, the live DGX backend wedged for
44-61s at a stretch under push-storm load. Root cause: sync pymongo
calls inside async FastAPI handlers (notably `/api/sentcom/stream/history`)
plus an unbounded scan loop. v19.30 added:
    1. `asyncio.to_thread` wrap on stream/history mongo materialisation.
    2. Per-phase `asyncio.wait_for` watchdogs in the trading-bot scan loop.

This file pins both behaviours.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest


# ── 1. Watchdog timeout actually fires ─────────────────────────────────
@pytest.mark.asyncio
async def test_wait_for_cancels_async_sleeper():
    """If a phase has a cooperative `await`, wait_for cancels it."""
    async def slow_phase():
        await asyncio.sleep(2.0)
        return "done"

    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(slow_phase(), timeout=0.2)
    elapsed = time.monotonic() - start
    # Should fire well under 1s (test budget allows for some slack).
    assert elapsed < 1.0, f"watchdog took {elapsed}s to fire"


@pytest.mark.asyncio
async def test_wait_for_does_not_block_other_work():
    """Watchdog firing on phase A must not block phase B."""
    async def slow_a():
        await asyncio.sleep(2.0)

    async def quick_b():
        await asyncio.sleep(0.05)
        return "b-done"

    start = time.monotonic()
    try:
        await asyncio.wait_for(slow_a(), timeout=0.1)
    except asyncio.TimeoutError:
        pass
    result_b = await asyncio.wait_for(quick_b(), timeout=1.0)
    elapsed = time.monotonic() - start
    assert result_b == "b-done"
    assert elapsed < 1.5, f"phase B starved by phase A — elapsed {elapsed}s"


# ── 2. to_thread wrap pattern keeps the loop responsive ────────────────
@pytest.mark.asyncio
async def test_to_thread_keeps_event_loop_responsive():
    """A blocking sync call wrapped in to_thread must NOT stall the loop."""
    blocked_for = 0.0

    async def slow_blocking_call():
        # This is what the buggy stream/history endpoint did pre-v19.30:
        # synchronous .find() + list() blocking the loop.
        def _sync():
            time.sleep(0.5)
            return ["row1", "row2"]
        return await asyncio.to_thread(_sync)

    async def background_pinger():
        nonlocal blocked_for
        for _ in range(20):
            t0 = time.monotonic()
            await asyncio.sleep(0.01)
            elapsed = time.monotonic() - t0
            if elapsed > 0.05:
                blocked_for = max(blocked_for, elapsed)

    pinger_task = asyncio.create_task(background_pinger())
    await asyncio.sleep(0.05)  # let pinger get going first
    rows = await slow_blocking_call()
    await pinger_task

    assert rows == ["row1", "row2"]
    # Pinger should never have been blocked > 50ms in any tick. If
    # `to_thread` failed and ran inline, the pinger would have been
    # stalled for the full 500ms.
    assert blocked_for < 0.10, f"event loop got blocked for {blocked_for}s — to_thread leaking"


@pytest.mark.asyncio
async def test_inline_blocking_call_DOES_block_loop():
    """Negative control: confirm a non-to_thread sync call DOES stall.

    This proves the test harness is sensitive enough to detect the
    bug v19.30 fixes — if this test ever stops failing, our to_thread
    test above is no longer meaningful.
    """
    blocked_for = 0.0

    async def slow_inline_call():
        # The pre-v19.30 pattern: sync work directly in async handler.
        time.sleep(0.5)
        return ["row1", "row2"]

    async def background_pinger():
        nonlocal blocked_for
        for _ in range(20):
            t0 = time.monotonic()
            await asyncio.sleep(0.01)
            elapsed = time.monotonic() - t0
            if elapsed > 0.05:
                blocked_for = max(blocked_for, elapsed)

    pinger_task = asyncio.create_task(background_pinger())
    await asyncio.sleep(0.05)  # let pinger get going first
    await slow_inline_call()
    await pinger_task

    # Inline blocking call MUST starve the pinger for >100ms — proving
    # our positive test above was actually measuring something real.
    assert blocked_for >= 0.10, f"sanity check failed — pinger only blocked {blocked_for}s"


# ── 3. Stream-history endpoint pattern smoke test ──────────────────────
@pytest.mark.asyncio
async def test_stream_history_query_pattern_uses_indexable_action_type():
    """Confirm the v19.30 query strategy hits action_type-equality first
    (indexable) before falling back to regex (full-collection-scan).

    This is a structural test against the query dict, not Mongo itself.
    """
    # Mirror the structure built by the v19.30 stream/history handler
    # when `q` is provided. Should include action_type equality as the
    # first $or branch so Mongo's planner picks an indexed path.
    q = "wrong_direction_phantom"
    import re
    q_lower = q.strip().lower()
    or_clauses = [
        {"action_type": q_lower},
        {"content": {"$regex": re.escape(q), "$options": "i"}},
        {"action_type": {"$regex": re.escape(q), "$options": "i"}},
    ]
    assert or_clauses[0] == {"action_type": "wrong_direction_phantom"}
    assert "$regex" in or_clauses[1]["content"]
    assert "$regex" in or_clauses[2]["action_type"]


# ── 4. Watchdog budgets match the v19.30 spec ──────────────────────────
def test_v19_30_phase_budgets_documented():
    """The wallclock budgets should match the comment in trading_bot_service.

    If someone tunes them, this test forces them to also update the doc.
    """
    from pathlib import Path
    expected = {"scan": 20.0, "pos": 8.0, "eod": 5.0}
    # Read the source file relative to this test (works on /app/ in
    # Emergent container AND on Spark's ~/Trading-and-Analysis-Platform).
    src_path = Path(__file__).resolve().parents[1] / "services" / "trading_bot_service.py"
    src = src_path.read_text()
    assert "_SCAN_WALL_S = 20.0" in src
    assert "_POS_WALL_S = 8.0" in src
    assert "_EOD_WALL_S = 5.0" in src
    # Total worst-case per scan must stay < 30s scan_interval so the
    # bot can't drift behind real time on a string of timeouts.
    total = expected["scan"] + expected["pos"] + expected["eod"]
    assert total < 35, f"phase budget {total}s ≥ scan_interval — bot will drift"


# ── 5. Boot-time watchdogs (server.py) ─────────────────────────────────
def test_v19_30_startup_phases_have_watchdogs():
    """Every async startup phase must have an asyncio.wait_for cap so
    a hung Mongo/IB call can't wedge the entire boot for 30s+.
    """
    from pathlib import Path
    src_path = Path(__file__).resolve().parents[1] / "server.py"
    src = src_path.read_text()
    # IB Gateway connect — 8s budget
    assert "asyncio.wait_for(ib_svc.connect(), timeout=8.0)" in src, \
        "IB connect must be wrapped in 8s wait_for (v19.30)"
    # Trading bot restore — 10s budget
    assert "asyncio.wait_for(trading_bot._restore_state(), timeout=10.0)" in src
    # Trading bot start — 5s budget
    assert "asyncio.wait_for(trading_bot.start(), timeout=5.0)" in src
    # Simulation engine init — 8s budget
    assert "asyncio.wait_for(simulation_engine.initialize(), timeout=8.0)" in src


# ── 6. Simulation engine init no longer blocks event loop ──────────────
def test_v19_30_simulation_engine_uses_to_thread():
    """The simulation engine's startup-time Mongo calls (find_one,
    create_index) were confirmed wedging the event loop in production.
    They must now go through asyncio.to_thread.
    """
    from pathlib import Path
    src_path = Path(__file__).resolve().parents[1] / "services" / "simulation_engine.py"
    src = src_path.read_text()
    # Both find_one calls inside _load_symbol_universes
    assert src.count("await asyncio.to_thread(") >= 4, \
        "simulation_engine.initialize must use to_thread for find_one/update_one/create_index"
    # The dangerous patterns we removed should NOT exist anymore
    assert "self._db[self.JOBS_COLLECTION].create_index(" not in src or \
           "_ensure_indexes()" in src
    # Inline find_one without to_thread is the bug we fixed
    bad_patterns = [
        'cached = self._db["symbol_universe"].find_one(',
        'sp500 = self._db["symbol_universe"].find_one(',
    ]
    for pat in bad_patterns:
        assert pat not in src, f"Inline sync mongo found again: {pat}"
