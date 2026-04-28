"""
Regression tests for the pusher-side subscription gate added 2026-04-29
(afternoon-13) to `/rpc/latest-bars` and `/rpc/latest-bars-batch`.

Background: 2026-04-29 (afternoon-13) operator's pusher logs showed
storm of `[RPC] latest-bars XXX failed:` warnings for symbols not in
the 14-symbol L1 subscription list (TQQQ, SQQQ, PLTR, META, SOXL,
AVGO, XLE, GLD, HOOD, NFLX, VOO, SMH, etc). Each failed request
burned 18s in `qualifyContracts + reqHistoricalData` before timing
out, clogging the IB event loop and causing >120s push-data response
times on DGX (`Read timed out (read timeout=120)`).

Root cause: the DGX-side gate in `services/ib_pusher_rpc.py::latest_bars`
falls through when `/rpc/subscriptions` returns None (transient
timeout / cache-empty post-restart). When DGX-side gate fails, the
pusher had no defense.

Fix: server-side subscription gate in BOTH `/rpc/latest-bars` and
`/rpc/latest-bars-batch`. Unsubscribed symbols return
`success: False, error: "not_subscribed"` immediately — no IB calls
made. Index symbols (VIX, SPX, NDX, RUT, DJX, VVIX) are exempt
because they're commonly requested for regime reference and may not
be in `subscribed_contracts`.

Tests assert via direct source inspection since running the actual
pusher requires Windows + IB Gateway + ib_insync.
"""

from __future__ import annotations

import re
from pathlib import Path

PUSHER_PATH = Path("/app/documents/scripts/ib_data_pusher.py")
RPC_PATH = Path("/app/backend/services/ib_pusher_rpc.py")


def _read(path: Path) -> str:
    assert path.exists(), f"{path} missing"
    return path.read_text(encoding="utf-8")


def _slice(src: str, start_pat: str, end_pat: str) -> str:
    lines = src.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.search(start_pat, ln)), None)
    assert start is not None, f"start pattern not found: {start_pat}"
    for j in range(start + 1, len(lines)):
        if re.search(end_pat, lines[j]):
            return "\n".join(lines[start:j])
    raise AssertionError(f"end pattern not found: {end_pat}")


def test_latest_bars_handler_rejects_unsubscribed_symbols():
    """`/rpc/latest-bars` MUST reject symbols not in
    `pusher.subscribed_contracts` upfront with `success: False,
    error: "not_subscribed"` — NO call to qualifyContracts /
    reqHistoricalData for unsubscribed symbols.
    """
    src = _read(PUSHER_PATH)
    body = _slice(src, r"def rpc_latest_bars\(req:", r"@app\.(post|get)\(")
    # Subscription gate must be present BEFORE the try block that calls IB.
    assert "not in pusher.subscribed_contracts" in body, (
        "Server-side subscription gate missing"
    )
    assert '"error": "not_subscribed"' in body, (
        "Expected `not_subscribed` error string"
    )
    # Index symbols must be exempted.
    assert "INDEX_SYMBOLS" in body, "INDEX_SYMBOLS exemption missing"
    # The gate must run before reqHistoricalDataAsync.
    gate_idx = body.index("not in pusher.subscribed_contracts")
    ib_call_idx = body.index("reqHistoricalDataAsync")
    assert gate_idx < ib_call_idx, (
        "Subscription gate must run BEFORE reqHistoricalDataAsync "
        "(otherwise unsubscribed symbols still burn IB pacing budget)"
    )


def test_latest_bars_batch_handler_filters_unsubscribed_symbols():
    """`/rpc/latest-bars-batch` MUST partition input symbols into
    subscribed (sent to IB) and unsubscribed (returned as fast
    `not_subscribed` failures). All unsubscribed symbols must appear
    in the response so the caller's symbol order is preserved.
    """
    src = _read(PUSHER_PATH)
    body = _slice(src, r"def rpc_latest_bars_batch\(req:", r"@app\.(post|get)\(")
    assert "rejected_results" in body, (
        "Batch handler must accumulate rejected (unsubscribed) entries"
    )
    assert '"error": "not_subscribed"' in body, (
        "Batch handler must emit `not_subscribed` for unsubscribed symbols"
    )
    # The ALL-rejected shortcut MUST not call IB at all.
    assert "if not symbols:" in body, "Missing all-rejected fast path"
    # Merge + return must include rejected entries.
    assert "merged" in body or "list(results) + rejected_results" in body, (
        "Final response must merge IB results + rejected entries"
    )


def test_dgx_subscriptions_timeout_bumped_to_8s():
    """DGX-side `_PusherRPCClient.subscriptions()` must use timeout=8.0
    when calling `/rpc/subscriptions`. The earlier 3.0s value caused
    cache-miss → fallthrough → MORE unsubscribed-symbol calls under
    load (the exact spiral that motivated this fix).
    """
    src = _read(RPC_PATH)
    body = _slice(src, r"def subscriptions\(", r"^    def [a-z_]+")
    assert "/rpc/subscriptions" in body
    assert "timeout=8.0" in body or "timeout=8" in body, (
        "Expected timeout=8.0 on /rpc/subscriptions GET — "
        "lower values cause gate fallthrough under pusher load"
    )


def test_dgx_latest_bars_gate_unchanged_for_subscribed_symbols():
    """The DGX-side gate must STILL allow subscribed symbols through.
    Only unsubscribed symbols should be short-circuited. Defense
    against an over-eager refactor.
    """
    src = _read(RPC_PATH)
    body = _slice(src, r"def latest_bars\(", r"^    def [a-z_]+")
    # Three-state gate: True | False | None. False blocks; None falls through.
    assert "is_pusher_subscribed" in body
    assert "if gate is False:" in body, (
        "Gate must use `is False` (not `not gate`) so None falls through"
    )
    # Subscribed symbols still hit the RPC endpoint.
    assert "/rpc/latest-bars" in body
