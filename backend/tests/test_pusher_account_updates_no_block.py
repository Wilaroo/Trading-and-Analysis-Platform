"""
Regression tests for the pusher's `request_account_updates` and
`fetch_news_providers` fire-and-forget contract added 2026-04-29
(afternoon-12).

Background: 2026-04-29 (afternoon-12) the pusher hung on
`Requesting account updates...` after a Windows pull + restart. IB
Gateway was green, but `IB.reqAccountUpdates` (which calls
`_run(reqAccountUpdatesAsync(...))` and awaits the initial
`accountDownloadEnd` event) never returned. The push loop never
started → operator dashboard stuck on `IB PUSHER DEAD · last push never`.

Fix: `request_account_updates` now uses the raw `client.reqAccountUpdates`
sync wire-protocol send (no await of `accountDownloadEnd`).
`fetch_news_providers` now wraps the async call in `asyncio.wait_for`
with an 8s timeout. Either way, the push loop gets to start.

These tests assert both behaviours via direct source inspection, since
running the actual pusher requires Windows + IB Gateway + ib_insync.
"""

from __future__ import annotations

import re
from pathlib import Path

PUSHER_PATH = Path("/app/documents/scripts/ib_data_pusher.py")


def _read():
    assert PUSHER_PATH.exists(), f"{PUSHER_PATH} missing"
    return PUSHER_PATH.read_text(encoding="utf-8")


def _slice(src: str, start_pat: str, end_pat: str) -> str:
    lines = src.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.search(start_pat, ln)), None)
    assert start is not None, f"start pattern not found: {start_pat}"
    for j in range(start + 1, len(lines)):
        if re.search(end_pat, lines[j]):
            return "\n".join(lines[start:j])
    raise AssertionError(f"end pattern not found: {end_pat}")


def test_request_account_updates_uses_raw_client_send():
    """The raw `client.reqAccountUpdates(True, account)` MUST be the
    primary code path. The high-level `IB.reqAccountUpdates` is allowed
    only as a fallback when the raw client method is missing.
    """
    body = _slice(_read(), r"def request_account_updates", r"^    def [a-z_]+\(")
    assert "client = getattr(self.ib, \"client\", None)" in body, (
        "Raw client lookup missing — fix may have regressed"
    )
    assert "raw_req = getattr(client, \"reqAccountUpdates\"" in body
    assert "raw_req(True, accounts[0])" in body, (
        "Raw client send not present — pusher will hang on IB stalls"
    )


def test_request_account_updates_does_not_block_on_high_level_call():
    """The high-level `self.ib.reqAccountUpdates(account=...)` call —
    which is `_run(reqAccountUpdatesAsync())` and awaits
    `accountDownloadEnd` — must NOT be the primary path. It's only
    reachable as the fallback when `client.reqAccountUpdates` is
    callable check fails.
    """
    body = _slice(_read(), r"def request_account_updates", r"^    def [a-z_]+\(")
    # Confirm the high-level call is gated behind the callable check.
    assert "if callable(raw_req):" in body
    # Confirm the high-level call lives in the `else` branch only.
    high_level_lines = [ln for ln in body.splitlines() if "self.ib.reqAccountUpdates(account=" in ln]
    assert len(high_level_lines) == 1, "Expected exactly one high-level call (in fallback else)"
    # Lines before it must include the `else:` branch marker.
    idx = body.index(high_level_lines[0])
    preceding = body[:idx]
    assert "else:" in preceding.splitlines()[-3:][0] or "else:" in preceding, (
        "High-level call must be inside the fallback else branch"
    )


def test_fetch_news_providers_has_timeout():
    """`fetch_news_providers` must wrap the async call in
    `asyncio.wait_for` with a finite timeout so a stalled IB news
    service cannot block the push loop forever.
    """
    body = _slice(_read(), r"def fetch_news_providers", r"^    def [a-z_]+\(")
    assert "wait_for" in body, "fetch_news_providers missing asyncio.wait_for guard"
    assert "timeout=8.0" in body or "timeout=8" in body, (
        "Expected 8s timeout on reqNewsProvidersAsync"
    )
    assert "TimeoutError" in body, "Missing TimeoutError handler"


def test_fetch_news_providers_falls_back_when_async_missing():
    """Older ib_insync builds may not expose `reqNewsProvidersAsync`.
    The fallback to the sync `reqNewsProviders` MUST be preserved so
    the pusher remains backwards-compatible.
    """
    body = _slice(_read(), r"def fetch_news_providers", r"^    def [a-z_]+\(")
    assert "AttributeError" in body, "AttributeError fallback missing"
    assert "self.ib.reqNewsProviders()" in body, (
        "Sync fallback for older ib_insync builds missing"
    )
