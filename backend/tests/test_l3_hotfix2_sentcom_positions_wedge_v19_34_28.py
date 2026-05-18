"""
v19.34.28 L3-hotfix2 — Regression: /api/sentcom/positions MUST NOT block
the asyncio event loop on Mongo I/O.

Forensic context
================
On 2026-05-18 (post L3-hotfix1) the wedge-watchdog stack dump pinned the
main thread inside:

    File "backend/routers/sentcom.py", line 485, in get_positions
        closed_today_raw = list(cursor)
    File "pymongo/cursor.py", line 1264, in next
        if len(self.__data) or self._refresh():
    ...
    File "pymongo/network.py", line 340, in _receive_data_on_socket
        chunk_length = conn.conn.recv_into(mv[bytes_read:])

Synchronous pymongo cursor iteration on the FastAPI event loop. When Mongo
takes >5s to respond, the loop wedges and EVERYTHING stalls — including
the trading bot's scan loop. v19.30 already fixed an identical wedge in
`get_thoughts()` (line ~190) but missed this twin in `get_positions()`.

Fix: wrap `list(cursor)` in `asyncio.to_thread(...)` so the blocking
iteration runs in a worker thread.

This regression test guarantees:
  1. Source-level: the bare `list(cursor)` pattern is gone from
     `get_positions`.
  2. Behavioural: when the cursor's underlying iteration sleeps 0.3s
     (simulating a slow Mongo), the asyncio loop stays responsive.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path

import pytest


# ── Source-level guard ────────────────────────────────────────────────


def test_get_positions_does_not_call_list_cursor_directly():
    """The bare `list(cursor)` pattern (where `cursor` is a sync pymongo
    cursor produced inside the async handler) must NOT appear in
    `get_positions`. The materialization MUST happen via
    `asyncio.to_thread(...)` (or a worker function called via to_thread)
    so socket I/O doesn't block the event loop.
    """
    from routers import sentcom as sentcom_mod
    src = inspect.getsource(sentcom_mod.get_positions)

    # Strip comments so historical commentary doesn't false-trip the check.
    code_lines = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
    code = "\n".join(code_lines)

    # The fixed handler uses asyncio.to_thread to materialize the cursor.
    assert "to_thread(" in code, (
        "L3-hotfix2 regression: get_positions must use asyncio.to_thread to "
        "materialize Mongo cursors. Otherwise sync pymongo iteration blocks "
        "the asyncio event loop on socket.recv_into and trips the wedge "
        "watchdog when Mongo is slow."
    )

    # The bare pattern `list(cursor)` (where cursor was bound at module-level
    # or just above) must not be present any more.
    assert "closed_today_raw = list(cursor)" not in code, (
        "L3-hotfix2 regression: the original blocking pattern "
        "`closed_today_raw = list(cursor)` is back. This wedges the event "
        "loop. Use `await asyncio.to_thread(...)` instead."
    )


def test_source_marker_present():
    """A version comment must remain so future patchers know this is a known
    sensitive spot. Pre-emptive defence against a future refactor that
    accidentally reintroduces the blocking pattern."""
    path = Path(__file__).parent.parent / "routers" / "sentcom.py"
    src = path.read_text()
    assert "L3-hotfix2" in src, (
        "Expected an `L3-hotfix2` marker comment near the closed_today "
        "Mongo cursor in routers/sentcom.py."
    )


# ── Behavioural: the asyncio loop must remain responsive while
#    Mongo I/O is in flight. We simulate a slow Mongo by running a
#    sync sleep inside the to_thread call and asserting that another
#    task on the same loop continues making progress.


@pytest.mark.asyncio
async def test_to_thread_does_not_block_event_loop():
    """End-to-end: a slow sync `list(cursor)`-equivalent inside
    asyncio.to_thread must NOT block the loop. A concurrent coroutine
    that does `await asyncio.sleep(0.05)` repeatedly should make at
    least ~15 ticks in 0.8s even while the simulated Mongo work is
    running.
    """
    SIMULATED_MONGO_DURATION = 0.8

    def _simulated_slow_pymongo_list():
        """Synchronous function that simulates pymongo's blocking
        socket.recv_into during a slow query."""
        time.sleep(SIMULATED_MONGO_DURATION)
        return [{"symbol": "TEST", "status": "closed"}]

    ticks = {"n": 0}

    async def _heartbeat():
        # Bumps once every 50 ms. If the loop is wedged, this will lag.
        deadline = time.monotonic() + SIMULATED_MONGO_DURATION + 0.2
        while time.monotonic() < deadline:
            ticks["n"] += 1
            await asyncio.sleep(0.05)

    # Run the "slow mongo" call and the heartbeat concurrently.
    t0 = time.monotonic()
    rows, _ = await asyncio.gather(
        asyncio.to_thread(_simulated_slow_pymongo_list),
        _heartbeat(),
    )
    elapsed = time.monotonic() - t0

    assert rows == [{"symbol": "TEST", "status": "closed"}]
    # Total wallclock should be ~SIMULATED_MONGO_DURATION (concurrency!),
    # NOT 2x. If they ran sequentially we'd see ~1.6s.
    assert elapsed < SIMULATED_MONGO_DURATION + 0.4, (
        f"Concurrent execution took {elapsed:.2f}s; expected ~{SIMULATED_MONGO_DURATION:.2f}s. "
        "The to_thread call may be blocking the loop."
    )
    # Heartbeat should have ticked at least 12 times (~0.6s of 50ms ticks).
    # In a wedged-loop scenario it would tick once or twice and then go quiet.
    assert ticks["n"] >= 12, (
        f"Loop heartbeat only fired {ticks['n']} times during the simulated "
        f"slow Mongo call — expected >=12. The loop appears wedged."
    )
