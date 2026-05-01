"""
test_event_loop_wedge_fix_v19_30_1.py — proves v19.30.1 (2026-05-02) keeps
the FastAPI event loop responsive while the Windows pusher hammers
/api/ib/push-data with bursts of quotes.

Background
----------
2026-05-02 morning, the live DGX backend wedged AFTER startup completed:
`curl -v -m 10 localhost:8001/api/health` would TCP-accept but never
return a single byte. Root cause: `/api/ib/push-data` was a SYNC `def`
handler that did:
  - `_db["ib_live_snapshot"].update_one(...)`  (sync pymongo)
  - `tick_to_bar_persister.on_push(...)`       (held a global threading
                                                Lock + sync per-bar
                                                update_one upserts)
inline on the FastAPI thread pool. With one Windows pusher pushing every
~2s and 100+ quote symbols, anyio's default 40-thread pool saturated and
every other handler (including the sync `/api/health`) queued forever.

v19.30.1 fixed it three ways:
  1. `/api/health` → `async def` (runs on event loop, immune to thread
     pool starvation regardless of what's happening downstream).
  2. `/api/ib/push-data` → `async def` + `asyncio.to_thread` for every
     sync mongo write + the tick→bar batch step. Loop stays responsive.
  3. Backpressure: bounded `_PUSH_DATA_MAX_CONCURRENT` in-flight count.
     Pushes beyond cap return 503 Retry-After:5 instantly so the pusher
     backs off cleanly instead of waiting 120s for a wedged response.

This file pins all three at the source / behaviour level.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 1. /api/health is async (event-loop protected) ─────────────────────
def test_health_endpoint_is_async_def():
    """/api/health MUST be `async def`. Pre-fix it was sync and shared
    the anyio thread pool with /api/ib/push-data — so a saturated pool
    starved /api/health to 0-byte timeouts."""
    src = Path(__file__).resolve().parents[1] / "routers" / "system_router.py"
    text = src.read_text()
    # Find the line right after the @router.get("/api/health") decorator
    idx = text.find('@router.get("/api/health")')
    assert idx >= 0, "/api/health route decorator missing"
    after = text[idx:idx + 400]
    assert "async def health_check" in after, (
        "/api/health must be `async def` so it runs on the event loop "
        "and bypasses anyio thread pool saturation"
    )


# ── 2. /api/ib/push-data is async ──────────────────────────────────────
def test_push_data_endpoint_is_async_def():
    """The push-data hot path MUST be async or every push blocks an
    anyio thread for the duration of mongo + tick→bar work.

    Pre-fix this was sync and did sync pymongo update_one inline.
    """
    src = Path(__file__).resolve().parents[1] / "routers" / "ib.py"
    text = src.read_text()
    idx = text.find('@router.post("/push-data")')
    assert idx >= 0, "/push-data route decorator missing"
    after = text[idx:idx + 400]
    assert "async def receive_pushed_ib_data" in after, (
        "/api/ib/push-data must be `async def` so the event loop stays "
        "responsive while mongo + tick→bar work runs in a thread"
    )


def test_push_data_offloads_mongo_to_thread():
    """All sync mongo work in /push-data MUST be wrapped in
    asyncio.to_thread. The two writes are:
      1. ib_live_snapshot upsert
      2. tick_to_bar_persister.on_push (inside it, sync mongo upserts)
    """
    src = Path(__file__).resolve().parents[1] / "routers" / "ib.py"
    text = src.read_text()
    # Slice to just the push-data handler body
    start = text.find("async def receive_pushed_ib_data")
    assert start >= 0
    end = text.find("\n@router.", start)
    body = text[start:end if end > 0 else len(text)]

    # Both async-offload patterns must appear inside the handler body
    assert "asyncio.to_thread(" in body, (
        "push-data must offload sync mongo with asyncio.to_thread"
    )
    # Specifically the snapshot upsert call site
    assert 'ib_live_snapshot' in body and 'update_one' in body, \
        "ib_live_snapshot snapshot upsert call must remain"
    # And tick_to_bar persister offload
    assert "on_push" in body and "to_thread" in body, \
        "tick_to_bar_persister.on_push must run via to_thread"


# ── 3. Backpressure: counters + 503 path exist ─────────────────────────
def test_push_data_has_backpressure_guard():
    """Module must define _PUSH_DATA_MAX_CONCURRENT + _push_in_flight +
    _push_dropped_503_total, and the handler must check the in-flight
    counter before accepting work."""
    src = Path(__file__).resolve().parents[1] / "routers" / "ib.py"
    text = src.read_text()
    assert "_PUSH_DATA_MAX_CONCURRENT" in text, "concurrency cap missing"
    assert "_push_in_flight" in text, "in-flight counter missing"
    assert "_push_dropped_503_total" in text, "drop counter missing"
    # Handler body must contain the 503 short-circuit
    start = text.find("async def receive_pushed_ib_data")
    body = text[start:]
    assert "if _push_in_flight >= _PUSH_DATA_MAX_CONCURRENT" in body, \
        "push-data must guard on the concurrency cap"
    assert "response.status_code = 503" in body, \
        "push-data must return 503 when cap is hit"
    assert 'response.headers["Retry-After"]' in body, \
        "push-data must set Retry-After so the pusher backs off cleanly"


# ── 4. Behavior — backpressure short-circuits without doing work ───────
@pytest.mark.asyncio
async def test_backpressure_returns_503_when_full():
    """When the in-flight counter is already at the cap, /push-data must
    return 503 INSTANTLY (no awaits, no DB calls). The pusher then sees
    a 503 + Retry-After header and backs off, instead of waiting on a
    wedged thread pool for 120s.
    """
    from routers import ib as ib_module
    from routers.ib import receive_pushed_ib_data, IBPushDataRequest

    # Force the in-flight counter to the cap
    ib_module._push_in_flight = ib_module._PUSH_DATA_MAX_CONCURRENT
    starting_drops = ib_module._push_dropped_503_total

    payload = IBPushDataRequest(
        timestamp="2026-05-02T09:30:00+00:00",
        source="test",
        quotes={"AAPL": {"last": 200.0}},
    )
    # FastAPI Response stub
    class _StubResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {}
    resp = _StubResponse()

    t0 = time.monotonic()
    out = await receive_pushed_ib_data(payload, resp)
    elapsed = time.monotonic() - t0

    # Reset for other tests
    ib_module._push_in_flight = 0

    assert resp.status_code == 503, "backpressure must return 503"
    assert resp.headers.get("Retry-After") == "5", "pusher needs Retry-After:5"
    assert out.get("success") is False
    assert out.get("error") == "backpressure"
    assert ib_module._push_dropped_503_total == starting_drops + 1, \
        "drop counter must be bumped on each rejected push"
    # Must short-circuit fast — < 50ms is generous (real path is <1ms)
    assert elapsed < 0.05, f"backpressure short-circuit took {elapsed}s"


# ── 5. Behavior — happy path keeps loop responsive under push storm ───
@pytest.mark.asyncio
async def test_push_storm_does_not_block_event_loop():
    """Simulate the operator's real failure mode: a tight loop of pushes
    fired at the handler. While the pushes are running, a separate
    coroutine pings asyncio.sleep(0) every 10ms — if the loop is wedged
    by sync mongo work the pings get starved.

    With v19.30.1's `to_thread` wrap the loop must stay responsive.
    """
    # Pre-import `server` so the test doesn't measure the one-time
    # ~2.8s import cost (in production uvicorn imports server before
    # any push-data request can land, so this cost is always paid up-
    # front during boot, not on the hot path).
    import server  # noqa: F401

    from routers import ib as ib_module
    from routers.ib import receive_pushed_ib_data, IBPushDataRequest

    # Reset state
    ib_module._push_in_flight = 0
    starting_total = ib_module._push_count_total

    # Mock the heavy work so we don't need a real Mongo / tick_to_bar
    # we patch the to_thread target functions to simulate work taking
    # 100ms (would WEDGE the loop in pre-v19.30.1 because they ran inline)
    def _slow_sync_upsert(*_a, **_k):
        time.sleep(0.10)
        return None

    class _StubPersister:
        def on_push(self, _quotes):
            time.sleep(0.05)
            return 0

    blocked_for = 0.0
    stop_pinger = False

    async def background_pinger():
        nonlocal blocked_for
        while not stop_pinger:
            t0 = time.monotonic()
            await asyncio.sleep(0.01)
            elapsed = time.monotonic() - t0
            if elapsed > 0.05:
                blocked_for = max(blocked_for, elapsed)

    async def hammer():
        """Send 8 pushes back-to-back."""
        with patch("services.tick_to_bar_persister.get_tick_to_bar_persister",
                   return_value=_StubPersister()):
            with patch("database.get_database") as _gdb:
                _stub_db = MagicMock()
                _stub_db.__getitem__.return_value.update_one.side_effect = _slow_sync_upsert
                _gdb.return_value = _stub_db

                class _StubResp:
                    def __init__(self):
                        self.status_code = 200
                        self.headers = {}

                tasks = []
                for i in range(8):
                    payload = IBPushDataRequest(
                        timestamp="2026-05-02T09:30:00+00:00",
                        source="test",
                        quotes={f"SYM{i}": {"last": 100.0}},
                    )
                    tasks.append(receive_pushed_ib_data(payload, _StubResp()))
                await asyncio.gather(*tasks)

    pinger_task = asyncio.create_task(background_pinger())
    await asyncio.sleep(0.05)  # let pinger get started
    await hammer()
    stop_pinger = True
    await pinger_task

    # Reset
    ib_module._push_in_flight = 0

    # If sync work ran inline (pre-fix), pinger would have been starved
    # for the full 100ms+ on each push. With to_thread, the pinger should
    # stay healthy even under 8 concurrent (but bounded by the semaphore)
    # pushes.
    assert blocked_for < 0.10, (
        f"event loop starved for {blocked_for*1000:.0f}ms during push storm — "
        f"to_thread offload not protecting the loop"
    )
    # Some pushes must have completed (those that fit under the cap)
    pushed_count = ib_module._push_count_total - starting_total
    assert pushed_count > 0, "no pushes completed during the storm test"


# ── 6. Tick-to-bar persister offload contract ──────────────────────────
def test_tick_to_bar_offload_pattern_in_push_handler():
    """The persister's on_push grabs a global threading.Lock and does sync
    mongo upserts in a per-bar loop. v19.30.1 wraps the call in
    asyncio.to_thread so it can never wedge the event loop, even when
    a bar finalisation pass touches dozens of symbols at once.
    """
    src = Path(__file__).resolve().parents[1] / "routers" / "ib.py"
    text = src.read_text()
    start = text.find("async def receive_pushed_ib_data")
    body = text[start:start + 8000]
    # Persister on_push must be called via to_thread, not inline
    assert "_persister.on_push" in body or "persister.on_push" in body, \
        "tick_to_bar persister must still be invoked"
    # Must NOT have inline `get_tick_to_bar_persister().on_push(` synchronously
    assert "get_tick_to_bar_persister().on_push(" not in body, (
        "Pre-fix inline pattern detected — tick_to_bar must run via to_thread"
    )
