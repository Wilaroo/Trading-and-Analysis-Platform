"""
v19.3 — Hot-fix: live-tick scanner must use mongo_only=True (2026-04-30)

After v19.1 fixed bar_poll's pusher bombardment, the operator's
14:58 ET screenshot still showed the SAME `[RPC] latest-bars X failed`
cascade plus 120s timeouts on `/api/ib/push-data`, equity $-, pusher
RED, frozen unified stream. Investigation revealed the live-tick
scanner (`enhanced_scanner._scan_symbol_all_setups`) was the OTHER
caller hitting the live-bar overlay — ~480 calls/cycle, each firing
`/rpc/latest-bars`, blowing IB's 60-req/10min pacing within 2-3
cycles.

The fix: `_scan_symbol_all_setups` now passes `mongo_only=True` to
`get_technical_snapshot`. Live quote still flows through
`_pushed_ib_data` independently. Mongo bars are <60s lagged — fine
for the 5-min/15-min bar detectors.

These regression guards prevent a future contributor from "cleaning
up" the flag and silently re-introducing the cascade.
"""
from __future__ import annotations

import inspect
import re

import pytest


def _read_scanner_source() -> str:
    from services import enhanced_scanner as scanner_module
    return inspect.getsource(scanner_module)


# --------------------------------------------------------------------------
# 1. The hot-path call site MUST pass mongo_only=True
# --------------------------------------------------------------------------

def test_scan_symbol_all_setups_uses_mongo_only():
    """The single most important guard: `_scan_symbol_all_setups` must
    call `get_technical_snapshot(...)` with `mongo_only=True`."""
    src = _read_scanner_source()

    # Find the body of `_scan_symbol_all_setups` (greedy match up to next `async def`).
    fn_match = re.search(
        r"async def _scan_symbol_all_setups\(.*?\n"
        r"(.*?)"
        r"(?=\n {0,4}async def |\n {0,4}def )",
        src, re.DOTALL,
    )
    assert fn_match, (
        "Could not locate `_scan_symbol_all_setups` in enhanced_scanner.py"
    )
    body = fn_match.group(1)

    # The first `get_technical_snapshot(...)` call in the body must include
    # `mongo_only=True`.
    snap_call = re.search(
        r"get_technical_snapshot\([^)]*\)",
        body, re.DOTALL,
    )
    assert snap_call, (
        "`_scan_symbol_all_setups` no longer calls `get_technical_snapshot` "
        "— update this test if the call site moved."
    )
    assert "mongo_only=True" in snap_call.group(0), (
        "🚨 v19.3 REGRESSION: `_scan_symbol_all_setups` must pass "
        "`mongo_only=True` to `get_technical_snapshot`. Without it, the "
        "live-tick scanner triggers `/rpc/latest-bars` for ~480 symbols "
        "per cycle, blowing IB's 60-req/10min pacing limit within 2-3 "
        "cycles. See test_scanner_mongo_only_v19_3.py docstring for "
        "the operator screenshot context."
    )


# --------------------------------------------------------------------------
# 2. Bar-poll regression guard from v19.1 still active (defense in depth)
# --------------------------------------------------------------------------

def test_bar_poll_service_still_uses_mongo_only():
    """Sanity check that the v19.1 bar-poll fix is still in place."""
    from services import bar_poll_service as bps_module
    src = inspect.getsource(bps_module)
    assert "get_batch_snapshots(" in src
    # The call must include mongo_only=True
    call_match = re.search(
        r"get_batch_snapshots\([^)]*\)", src, re.DOTALL,
    )
    assert call_match, "bar_poll_service no longer calls get_batch_snapshots"
    assert "mongo_only=True" in call_match.group(0), (
        "🚨 v19.1 REGRESSION: `bar_poll_service` must pass "
        "`mongo_only=True` to `get_batch_snapshots`."
    )


# --------------------------------------------------------------------------
# 3. The realtime_technical_service still EXPOSES the mongo_only param
# --------------------------------------------------------------------------

def test_get_technical_snapshot_signature_has_mongo_only():
    from services.realtime_technical_service import RealTimeTechnicalService
    sig = inspect.signature(RealTimeTechnicalService.get_technical_snapshot)
    assert "mongo_only" in sig.parameters, (
        "`get_technical_snapshot` must expose a `mongo_only` parameter — "
        "this is the kill-switch that decouples the live-tick scanner + "
        "bar-poll from the pusher RPC overlay."
    )
    # Default must remain False to preserve behaviour for callers like
    # the API endpoints + AI assistant where freshness > pacing safety.
    assert sig.parameters["mongo_only"].default is False, (
        "`get_technical_snapshot` default for `mongo_only` must be False. "
        "Hot paths opt-IN; one-off callers stay on the freshness path."
    )


def test_get_batch_snapshots_signature_has_mongo_only():
    from services.realtime_technical_service import RealTimeTechnicalService
    sig = inspect.signature(RealTimeTechnicalService.get_batch_snapshots)
    assert "mongo_only" in sig.parameters
    assert sig.parameters["mongo_only"].default is False
