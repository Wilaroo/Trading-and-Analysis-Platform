"""
v19.34.28 L3-hotfix3 — Regression: get_our_positions MUST NOT block the
asyncio event loop on the sync pusher HTTP call.

Forensic context
================
On 2026-05-18 (post L3-hotfix2) the wedge-watchdog stack dump pinned the
main thread inside:

    File "backend/services/sentcom_service.py", line 2136, in get_our_positions
        _snap = _gas()
    File "backend/services/ib_pusher_rpc.py", line 703, in get_account_snapshot
        return get_pusher_rpc_client().account_snapshot()
    File "backend/services/ib_pusher_rpc.py", line 368, in _request
        resp = self._session.request(...)
    File ".../urllib3/util/connection.py", line 73, in create_connection
        sock.connect(sa)

Synchronous `requests` HTTP call on the asyncio event loop. Under
`BOT_ORDER_PATH=direct` the pusher RPC channel is intentionally offline,
so the call blocks on TCP connect until the 5s timeout fires. The frontend
hits `/api/sentcom/positions` on every dashboard tick, so every tick
wedged the loop.

Fix: wrap `_gas()` in `asyncio.to_thread(...)` so the sync HTTP call
runs in a worker thread.

This regression test guarantees:
  1. Source-level: `_snap = _gas()` is gone from `get_our_positions`.
  2. Source-level: there's a `to_thread(...)` near the `_gas` import.
  3. A version marker remains so future patchers see this is sensitive.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from services import sentcom_service as svc_mod


def _strip_comments(src: str) -> str:
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


def test_get_our_positions_does_not_call_gas_sync():
    """The bare `_snap = _gas()` blocking pattern must NOT appear in the
    `get_our_positions` async handler. The sync HTTP probe must hop to a
    worker thread."""
    src = inspect.getsource(svc_mod.SentComService.get_our_positions)
    code = _strip_comments(src)

    assert "_snap = _gas()" not in code, (
        "L3-hotfix3 regression: blocking pattern `_snap = _gas()` returned. "
        "This is a sync HTTP request to the pusher RPC and wedges the event "
        "loop. Use `_snap = await asyncio.to_thread(_gas)` instead."
    )
    assert "to_thread(_gas)" in code, (
        "L3-hotfix3 regression: `_gas` must be invoked via asyncio.to_thread "
        "to keep the sync HTTP call off the asyncio main loop."
    )


def test_l3_hotfix3_marker_present():
    """A version marker must remain near the patched call site so future
    refactors see this is a known sensitive spot."""
    path = Path(svc_mod.__file__)
    assert "L3-hotfix3" in path.read_text(), (
        "Expected an `L3-hotfix3` marker comment near the patched _gas() "
        "call site in services/sentcom_service.py."
    )
