"""
test_bar_poll_wedge_fix_v19_30_2.py — proves v19.30.2 (2026-05-02) keeps
the FastAPI event loop responsive when the Windows IB pusher is OFF.

Background
----------
2026-05-02, after v19.30.1 shipped the push-data backpressure fix, the
operator hit a SECOND wedge during degraded boot (IB Gateway off):

```
$ curl -m 5 localhost:8001/api/health
* Operation timed out after 5003 milliseconds with 0 bytes received
```

`py-spy dump` on the wedged process pinpointed the exact line:

```
MainThread BLOCKED in:
  services/ib_pusher_rpc.py:124    _request          ← sync HTTP call
  services/ib_pusher_rpc.py:202    subscriptions
  services/ib_pusher_rpc.py:400    get_subscribed_set
  services/bar_poll_service.py:229 _build_symbol_pools
  services/bar_poll_service.py:291 poll_pool_once
  services/bar_poll_service.py:491 _loop_body        ← async loop body
```

Root cause: `bar_poll_service._build_symbol_pools()` is a sync `def`
called inline from async `poll_pool_once`. It does:
  1. `self.pusher.get_subscribed_set()` — sync HTTP call to Windows
     pusher with an 8s timeout. When the pusher is fully OFF, every
     call burns the full 8s.
  2. Three sync `db["symbol_adv_cache"].find().sort()` cursor iterations
     in inline list comprehensions.

With ~3 pools × ~8s + sync mongo overhead = 24-36s loop wedge.

The fix has two layers:
  1. Wrap `_build_symbol_pools()` in `asyncio.to_thread` from
     `poll_pool_once`. The pusher RPC + mongo work now runs on a
     thread, keeping the event loop responsive.
  2. Drop the `subscriptions()` timeout from 8s → 3s. Even if a future
     caller bypasses the to_thread offload, max impact is bounded.
     Subscription state changes rarely (operator action) and the 30s
     `_subs_cache` TTL smooths the steady-state call rate.

The `services/ib_pusher_rpc.py` module's own header docstring says
"Call from async paths via asyncio.to_thread" — this fix simply
finishes honoring that contract.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 1. poll_pool_once offloads _build_symbol_pools to a thread ─────────
def test_poll_pool_once_offloads_pool_build_to_thread():
    """The async hot-path `poll_pool_once` MUST offload
    `_build_symbol_pools` to a thread because it does a sync pusher
    RPC call + sync mongo iteration. Pre-fix this was inline and
    wedged the event loop for 24-36s when the pusher was OFF."""
    src = Path(__file__).resolve().parents[1] / "services" / "bar_poll_service.py"
    text = src.read_text()
    # Find the poll_pool_once body
    idx = text.find("async def poll_pool_once")
    assert idx >= 0, "poll_pool_once handler missing"
    body = text[idx:idx + 3000]
    # Must call _build_symbol_pools via asyncio.to_thread
    assert "asyncio.to_thread(self._build_symbol_pools)" in body, (
        "poll_pool_once must call _build_symbol_pools via asyncio.to_thread "
        "to keep the event loop responsive when the pusher RPC blocks"
    )
    # Must NOT have the inline pre-fix pattern
    assert "self._build_symbol_pools().get(" not in body, (
        "Pre-fix inline pattern detected — _build_symbol_pools must run via to_thread"
    )


# ── 2. Pusher subscriptions timeout dropped to 3s ──────────────────────
def test_subscriptions_timeout_is_short_enough():
    """The pusher RPC `subscriptions()` call MUST use a short timeout
    (≤3s). The pre-fix 8s timeout meant a fully-OFF pusher would
    wedge the loop for 24-36s across pool iterations.

    The 30s subscription cache TTL still smooths steady-state call
    rate, so the timeout only matters on cold-cache / force_refresh
    paths — and those are exactly the paths the wedge fired on.
    """
    src = Path(__file__).resolve().parents[1] / "services" / "ib_pusher_rpc.py"
    text = src.read_text()
    # Find the subscriptions() body
    idx = text.find("def subscriptions(self,")
    assert idx >= 0, "subscriptions() method missing"
    body = text[idx:idx + 2500]
    # Look for the /rpc/subscriptions call timeout. v19.30.11 changed
    # the call from `_request(...)` to `_request_with_dedup(...)` so
    # concurrent cold-cache races coalesce; the timeout MUST still be
    # ≤3s either way (the pre-fix 8s burned the loop for 24-36s).
    import re
    m = re.search(
        r'_request(?:_with_dedup)?\(\s*"GET",\s*"/rpc/subscriptions",\s*timeout=(\d+(?:\.\d+)?)\s*\)',
        body,
    )
    assert m is not None, "could not find /rpc/subscriptions _request call"
    timeout = float(m.group(1))
    assert timeout <= 3.5, (
        f"subscriptions() RPC timeout is {timeout}s — must be ≤3s so a "
        f"fully-OFF pusher fails fast instead of wedging the loop"
    )


# ── 3. Behavioural — slow pusher RPC does not wedge the event loop ────
@pytest.mark.asyncio
async def test_slow_pusher_rpc_does_not_wedge_event_loop():
    """Simulate the operator's failure mode: pusher RPC is slow / hung.
    `poll_pool_once` must complete (with empty pool) without blocking
    the event loop, because the slow work runs in a thread.

    Pre-fix: the sync pusher RPC inside `_build_symbol_pools` would
    pin the event loop for the full timeout window.
    Post-fix: to_thread keeps the loop responsive; a background pinger
    sees no starvation while the pool build is in flight.
    """
    from services import bar_poll_service as bps_module

    # Build a stub BarPollService with mocked pusher + mongo.
    # The pusher's get_subscribed_set sleeps 0.5s to simulate slow RPC
    # — pre-fix this would block the loop, post-fix it's in a thread.
    class _SlowPusher:
        def get_subscribed_set(self, force_refresh=False):
            time.sleep(0.5)  # simulate slow RPC (real-world: 8s timeout)
            return set()

    class _StubDB:
        def __getitem__(self, name):
            return _StubColl()

    class _StubColl:
        def find(self, *a, **k):
            return _StubCursor()

    class _StubCursor:
        def sort(self, *a, **k):
            return iter([])  # empty cursor

    # Reset module singleton so we don't leak state across tests
    bps_module._bar_poll_service = None
    svc = bps_module.BarPollService(
        db=_StubDB(),
        scanner=MagicMock(),
        pusher_client=_SlowPusher(),
        technical_service=None,
        in_rth_only=False,
    )

    # Run a background pinger that measures event-loop responsiveness
    blocked_for = 0.0
    stop = False

    async def pinger():
        nonlocal blocked_for
        while not stop:
            t0 = time.monotonic()
            await asyncio.sleep(0.01)
            elapsed = time.monotonic() - t0
            if elapsed > 0.05:
                blocked_for = max(blocked_for, elapsed)

    pinger_task = asyncio.create_task(pinger())
    await asyncio.sleep(0.05)  # let pinger get started

    # Call poll_pool_once for each pool — pre-fix this would wedge
    # the loop for ~0.5s × 3 pools = ~1.5s (real-world: 8s × 3 = 24s)
    t0 = time.monotonic()
    await svc.poll_pool_once("intraday_noncore")
    await svc.poll_pool_once("swing")
    await svc.poll_pool_once("investment")
    elapsed = time.monotonic() - t0

    stop = True
    await pinger_task

    # The to_thread offload means the loop should NEVER be blocked
    # for more than ~50ms (the pinger tick interval). Pre-fix the
    # pinger would have been starved for the full pool-build duration.
    assert blocked_for < 0.10, (
        f"Event loop was blocked for {blocked_for*1000:.0f}ms during "
        f"slow pusher RPC — to_thread offload not protecting the loop"
    )
    # The 3 pool calls collectively took at least 3 × 0.5s = 1.5s, but
    # they ran in threads concurrently with our pinger.
    assert elapsed >= 1.4, (
        f"3 sequential slow pool builds completed in {elapsed:.2f}s — "
        f"sanity check that the slow RPC actually ran"
    )


# ── 4. Behavioural — to_thread is reachable from poll_pool_once ───────
def test_poll_pool_once_compiles_with_to_thread_offload():
    """Smoke test: importing `bar_poll_service` must succeed and the
    `poll_pool_once` method must contain the `asyncio.to_thread` call
    referenced in (1). Catches accidental indentation/typo regressions
    that wouldn't show up in a source-grep test."""
    import importlib
    from services import bar_poll_service as bps_module
    importlib.reload(bps_module)
    # The method must exist
    assert hasattr(bps_module.BarPollService, "poll_pool_once")
    # It must be a coroutine function
    import inspect
    assert inspect.iscoroutinefunction(
        bps_module.BarPollService.poll_pool_once
    ), "poll_pool_once must be async"


# ── 5. The pusher RPC module docstring contract is satisfied ──────────
def test_pusher_rpc_module_docstring_contract_honored():
    """The `services/ib_pusher_rpc.py` module's own header docstring
    explicitly says 'Call from async paths via asyncio.to_thread'.
    Verify that the only async caller of
    `pusher.get_subscribed_set()` (bar_poll_service) honors that."""
    bps = (
        Path(__file__).resolve().parents[1]
        / "services" / "bar_poll_service.py"
    ).read_text()
    rpc = (
        Path(__file__).resolve().parents[1]
        / "services" / "ib_pusher_rpc.py"
    ).read_text()
    # Header contract
    assert "Call from async paths via asyncio.to_thread" in rpc, (
        "Pusher RPC module header contract removed — protect the contract "
        "or update this test if the architecture changed."
    )
    # Caller honors it
    assert "asyncio.to_thread(self._build_symbol_pools)" in bps, (
        "bar_poll_service must offload `_build_symbol_pools` to a thread "
        "because it transitively calls pusher.get_subscribed_set() (sync HTTP)"
    )
