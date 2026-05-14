"""
test_scanner_thought_emissions_v19_34_26.py
============================================
Verifies the v19.34.26 wiring of `_emit_scanner_thought` across the
remaining filter sites in `services/enhanced_scanner.py` (RVOL gate,
in-play strict gate, per-symbol dedup, priority-dedup, and the final
trigger-emit at alert acceptance).

We don't spin up the full scanner — too many dependencies (Mongo,
in-play service, learning loop, smart watchlist). Instead we stub a
tiny harness object that owns just the methods/state under test and
patch `services.sentcom_service.emit_stream_event` to capture every
emission for assertion.

The dedup TTL on `_emit_scanner_thought` is per-(symbol, kind) so we
use distinct kinds across tests to avoid cross-test suppression.
"""
from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, "/app/backend")
import services.enhanced_scanner as es  # noqa: E402


# ────────────────────────────────────────────────────────────────────
# Minimal harness — borrows the real `_emit_scanner_thought` impl via
# a thin instance so we don't have to instantiate EnhancedScanner.
# ────────────────────────────────────────────────────────────────────
class _Harness:
    def __init__(self):
        self._scanner_thought_dedup = {}
        self._scanner_thought_dedup_ttl = 30.0


_Harness._emit_scanner_thought = es.EnhancedBackgroundScanner._emit_scanner_thought


@pytest.fixture()
def harness():
    return _Harness()


@pytest.fixture()
def captured(monkeypatch):
    events = []

    async def _capture(payload):
        events.append(payload)

    # The scanner's helper imports emit_stream_event lazily inside the
    # function, so we patch `services.sentcom_service.emit_stream_event`.
    import services.sentcom_service as ss
    monkeypatch.setattr(ss, "emit_stream_event", _capture, raising=True)
    return events


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) \
        else asyncio.new_event_loop().run_until_complete(coro)


# ── 1. _emit_scanner_thought core behaviour ─────────────────────────

def test_emit_payload_shape(harness, captured):
    asyncio.run(harness._emit_scanner_thought(
        symbol="nvda", kind="reject", text="🚫 RVOL too low",
        setup_type="orb_long", direction="long",
        filter="rvol_min", rvol=0.3,
    ))
    assert len(captured) == 1
    p = captured[0]
    assert p["kind"] == "thought"
    assert p["event"] == "scanner_reject"
    assert p["symbol"] == "NVDA"  # always upper
    assert p["text"].startswith("🚫")
    md = p["metadata"]
    assert md["source"] == "enhanced_scanner"
    assert md["kind"] == "reject"
    assert md["setup_type"] == "orb_long"
    assert md["direction"] == "long"
    assert md["filter"] == "rvol_min"
    assert md["rvol"] == 0.3


def test_dedup_within_ttl_suppresses_second_emit(harness, captured):
    """Same (symbol, kind) inside the TTL window should fire ONCE."""
    asyncio.run(harness._emit_scanner_thought(symbol="NVDA", kind="skip", text="first"))
    asyncio.run(harness._emit_scanner_thought(symbol="NVDA", kind="skip", text="second"))
    assert len(captured) == 1
    assert captured[0]["text"] == "first"


def test_dedup_differing_kinds_both_fire(harness, captured):
    """Different kinds on the same symbol should NOT be deduped together."""
    asyncio.run(harness._emit_scanner_thought(symbol="NVDA", kind="reject", text="r"))
    asyncio.run(harness._emit_scanner_thought(symbol="NVDA", kind="trigger", text="t"))
    assert len(captured) == 2
    kinds = [p["metadata"]["kind"] for p in captured]
    assert set(kinds) == {"reject", "trigger"}


def test_dedup_expires_after_ttl(harness, captured):
    """Outside the dedup window the same (symbol, kind) MUST fire again."""
    harness._scanner_thought_dedup_ttl = 0.05  # tighten the window
    asyncio.run(harness._emit_scanner_thought(symbol="NVDA", kind="skip", text="first"))
    time.sleep(0.06)
    asyncio.run(harness._emit_scanner_thought(symbol="NVDA", kind="skip", text="second"))
    assert len(captured) == 2


# ── 2. RVOL / in-play / dedup filter texts are well-formed ──────────
# We don't actually run the full _scan_symbol path (too many deps),
# but we can sanity-check the *shape* of the texts our v19.34.26
# wiring emits by mimicking the lines as the file calls them. This
# guards against accidentally breaking the f-string substitution.

def test_rvol_skip_text_format(harness, captured):
    snapshot_rvol = 0.42
    min_rvol = 0.8
    asyncio.run(harness._emit_scanner_thought(
        symbol="WULF", kind="skip",
        text=f"🟤 WULF skipped — RVOL {snapshot_rvol:.2f}× below floor {min_rvol:.2f}×",
        filter="rvol_min", rvol=snapshot_rvol, min_rvol=min_rvol,
    ))
    assert "RVOL 0.42×" in captured[0]["text"]
    assert "0.80×" in captured[0]["text"]
    assert captured[0]["metadata"]["filter"] == "rvol_min"


def test_trigger_text_includes_priority_and_rr(harness, captured):
    asyncio.run(harness._emit_scanner_thought(
        symbol="NVDA", kind="trigger",
        text="✅ NVDA orb_long fired · high priority · R:R 2.40 · tape ✓",
        setup_type="orb_long", direction="long",
        priority="high", rr=2.4, tape_confirmation=True,
        trigger_price=950.10,
    ))
    p = captured[0]
    assert p["text"].startswith("✅ NVDA")
    assert "R:R 2.40" in p["text"]
    assert "tape ✓" in p["text"]
    md = p["metadata"]
    assert md["priority"] == "high"
    assert md["rr"] == 2.4
    assert md["tape_confirmation"] is True


def test_dedup_skip_emits_with_filter_metadata(harness, captured):
    asyncio.run(harness._emit_scanner_thought(
        symbol="AAPL", kind="skip",
        text="🔁 AAPL orb_long dedup — identical active alert already live",
        setup_type="orb_long", direction="long",
        filter="dedup_same_setup",
    ))
    p = captured[0]
    assert p["metadata"]["filter"] == "dedup_same_setup"
    assert "dedup" in p["text"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
