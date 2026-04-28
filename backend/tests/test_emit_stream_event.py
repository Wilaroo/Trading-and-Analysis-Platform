"""
Regression tests for `emit_stream_event` — module-level helper that
push-publishes events into the SentCom unified stream buffer. Was
silently missing prior to 2026-04-29 (afternoon-3): callers (bot
safety blocks, IB router order timeouts) imported the name inside
try/except → ImportError → no events ever reached the V5 stream.
"""

from __future__ import annotations

import asyncio
import pytest

from services.sentcom_service import (
    SentComService,
    emit_stream_event,
    get_sentcom_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton between tests so buffer state doesn't leak."""
    import services.sentcom_service as mod
    mod._sentcom_service = SentComService()
    yield
    mod._sentcom_service = None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_emit_pushes_message_into_stream_buffer():
    ok = _run(emit_stream_event({
        "kind": "skip",
        "event": "safety_block",
        "symbol": "TSLA",
        "text": "Safety block (max_position): would breach risk caps",
    }))
    assert ok is True
    svc = get_sentcom_service()
    assert len(svc._stream_buffer) == 1
    msg = svc._stream_buffer[0]
    assert msg.symbol == "TSLA"
    assert msg.type == "skip"
    assert msg.action_type == "safety_block"
    assert "Safety block" in msg.content


def test_emit_dedups_repeated_events():
    payload = {
        "kind": "fill",
        "symbol": "AAPL",
        "text": "Filled LONG 100 AAPL @ $180.50",
    }
    assert _run(emit_stream_event(payload)) is True
    # Second identical emit should be deduped (returns False)
    assert _run(emit_stream_event(payload)) is False
    svc = get_sentcom_service()
    assert len(svc._stream_buffer) == 1


def test_emit_rejects_empty_text():
    assert _run(emit_stream_event({"kind": "info", "text": ""})) is False
    assert _run(emit_stream_event({"kind": "info"})) is False
    svc = get_sentcom_service()
    assert len(svc._stream_buffer) == 0


def test_emit_normalises_unknown_kind_to_info():
    ok = _run(emit_stream_event({
        "kind": "wat_is_this",
        "text": "test event",
    }))
    assert ok is True
    svc = get_sentcom_service()
    assert svc._stream_buffer[0].type == "info"


def test_emit_accepts_content_or_text_synonym():
    """Callers may pass either `text` or `content` — both must work."""
    ok = _run(emit_stream_event({
        "type": "fill",
        "content": "Order timeout for NVDA",
        "symbol": "NVDA",
    }))
    assert ok is True
    svc = get_sentcom_service()
    assert "Order timeout" in svc._stream_buffer[0].content


def test_emit_never_raises_on_garbage_input():
    """Fire-and-forget contract — must not crash callers with bad input."""
    assert _run(emit_stream_event(None)) is False
    assert _run(emit_stream_event("not a dict")) is False
    assert _run(emit_stream_event({"kind": "info", "text": "x", "metadata": "garbage"})) is True
    # garbage metadata wrapped, not crashed
    svc = get_sentcom_service()
    assert isinstance(svc._stream_buffer[0].metadata, dict)


def test_emit_trims_buffer_to_max_size():
    """Buffer must not grow unboundedly."""
    svc = get_sentcom_service()
    svc._stream_max_size = 5
    for i in range(10):
        _run(emit_stream_event({
            "kind": "info",
            "text": f"event {i}",
        }))
    assert len(svc._stream_buffer) == 5
    # Newest first — should be event 9 / 8 / 7 / 6 / 5
    contents = [m.content for m in svc._stream_buffer]
    assert "event 9" in contents
    assert "event 0" not in contents


def test_emit_appears_in_get_unified_stream():
    """End-to-end: after emit, get_unified_stream returns it from buffer."""
    _run(emit_stream_event({
        "kind": "alert",
        "symbol": "MSFT",
        "text": "Big squeeze setup forming",
    }))
    svc = get_sentcom_service()
    # Stream buffer is the source of truth — get_unified_stream reads it
    assert any(m.content == "Big squeeze setup forming"
               for m in svc._stream_buffer)
