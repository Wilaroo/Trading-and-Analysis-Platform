"""
Regression tests for the pusher's `request_account_updates` and
`fetch_news_providers` timeout-protected contract added 2026-04-29
(afternoon-12).

Background: 2026-04-29 (afternoon-12) the pusher hung on
`Requesting account updates...` after a Windows pull + restart. IB
Gateway was green, but `IB.reqAccountUpdates` (which calls
`_run(reqAccountUpdatesAsync(...))` and awaits the initial
`accountDownloadEnd` event) never returned. The push loop never
started → operator dashboard stuck on `IB PUSHER DEAD · last push never`.

Fix: both `request_account_updates` and `fetch_news_providers` wrap
their async ib_insync calls in `asyncio.wait_for(...)` with finite
timeouts. On timeout, the push loop continues and the data populates
naturally as IB streams it (`accountValueEvent` is wired in
__init__).

These tests assert the behaviour via direct source inspection, since
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


def test_request_account_updates_uses_async_with_timeout():
    """`request_account_updates` MUST wrap the async ib_insync call in
    `asyncio.wait_for(...)` with a finite timeout. The high-level
    sync call (which is `_run(reqAccountUpdatesAsync())` and would
    block forever waiting for `accountDownloadEnd`) is forbidden as
    the primary path.
    """
    body = _slice(_read(), r"def request_account_updates", r"^    def [a-z_]+\(")
    assert "wait_for" in body, "Missing asyncio.wait_for guard"
    assert "reqAccountUpdatesAsync" in body, (
        "Must use async ib_insync call (so wrapper request-registration runs)"
    )
    # Explicit timeout
    assert "timeout=10.0" in body or "timeout=10" in body, (
        "Expected 10s timeout on reqAccountUpdatesAsync"
    )


def test_request_account_updates_handles_timeout_gracefully():
    """On `asyncio.TimeoutError`, the function must log a warning and
    return — not raise — so the push loop can still start.
    """
    body = _slice(_read(), r"def request_account_updates", r"^    def [a-z_]+\(")
    assert "TimeoutError" in body, "Missing TimeoutError handler"
    assert "logger.warning" in body, (
        "Must log a warning (not error) so the push loop continues"
    )


def test_request_account_updates_falls_back_when_async_missing():
    """Older ib_insync builds may not expose `reqAccountUpdatesAsync`.
    The fallback to the sync `reqAccountUpdates(account=...)` call
    MUST be preserved for backwards-compatibility.
    """
    body = _slice(_read(), r"def request_account_updates", r"^    def [a-z_]+\(")
    assert "AttributeError" in body, "AttributeError fallback missing"
    assert "self.ib.reqAccountUpdates(account=" in body, (
        "Sync fallback for older ib_insync builds missing"
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
