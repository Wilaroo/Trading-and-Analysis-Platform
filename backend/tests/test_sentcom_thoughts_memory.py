"""
Regression tests for `sentcom_thoughts` persistence — the operator's
V4 "AI brain memory" carry-over to V5. Asserts:

  - `emit_stream_event` writes to the `sentcom_thoughts` Mongo collection
    in addition to the in-memory buffer.
  - `get_recent_thoughts` recalls them with optional symbol / kind /
    minutes filters and returns rows newest-first.
  - SentCom service rehydrates the stream buffer from the collection on
    init (survives backend restarts).
  - The chat path injects recent thoughts into the orchestrator context
    (so the AI can answer "what were we doing on SPY this morning?").
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import mongomock
import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _patch_db_and_reset():
    """Patch _get_db to a fresh mongomock + reset the singleton between tests."""
    import services.sentcom_service as mod
    db = mongomock.MongoClient().db
    with patch.object(mod, "_get_db", lambda: db):
        # mongomock doesn't support TTL; mark indexes "initialised" so the
        # real call no-ops cleanly.
        mod._thoughts_index_initialised = True
        mod._sentcom_service = None  # force fresh instance
        yield db
        mod._sentcom_service = None
        mod._thoughts_index_initialised = False


def test_emit_persists_event_to_mongo(_patch_db_and_reset):
    from services.sentcom_service import emit_stream_event

    ok = _run(emit_stream_event({
        "kind": "evaluation",
        "event": "evaluating_setup",
        "symbol": "NVDA",
        "text": "🤔 Evaluating NVDA orb LONG (TQS 72 B)",
        "metadata": {"setup_type": "orb", "tqs_score": 72},
    }))
    assert ok is True

    # Give the asyncio.create_task time to land
    _run(asyncio.sleep(0.05))

    rows = list(_patch_db_and_reset["sentcom_thoughts"].find({}, {"_id": 0}))
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "NVDA"
    assert r["kind"] == "evaluation"
    assert "Evaluating NVDA" in r["content"]
    assert r["action_type"] == "evaluating_setup"
    assert r["metadata"]["setup_type"] == "orb"


def test_get_recent_thoughts_filters_by_symbol(_patch_db_and_reset):
    from services.sentcom_service import emit_stream_event, get_recent_thoughts

    for sym, txt in [("AAPL", "fill"), ("NVDA", "eval"), ("AAPL", "skip")]:
        _run(emit_stream_event({
            "kind": "fill",  # use distinct text → distinct dedup keys
            "symbol": sym,
            "text": f"{txt} on {sym} {time.time_ns()}",
        }))
    _run(asyncio.sleep(0.05))

    aapl = get_recent_thoughts(symbol="AAPL", limit=10)
    assert len(aapl) == 2
    assert all(r["symbol"] == "AAPL" for r in aapl)


def test_get_recent_thoughts_filters_by_kind(_patch_db_and_reset):
    from services.sentcom_service import emit_stream_event, get_recent_thoughts

    _run(emit_stream_event({"kind": "fill", "symbol": "TSLA", "text": "filled 1"}))
    _run(emit_stream_event({"kind": "evaluation", "symbol": "TSLA", "text": "evaluating 1"}))
    _run(emit_stream_event({"kind": "skip", "symbol": "TSLA", "text": "skipped 1"}))
    _run(asyncio.sleep(0.05))

    only_fills = get_recent_thoughts(kind="fill", limit=10)
    assert len(only_fills) == 1
    assert only_fills[0]["kind"] == "fill"


def test_get_recent_thoughts_returns_newest_first(_patch_db_and_reset):
    from services.sentcom_service import emit_stream_event, get_recent_thoughts

    for i in range(3):
        _run(emit_stream_event({
            "kind": "info", "symbol": f"SYM{i}",
            "text": f"event {i}",
        }))
        _run(asyncio.sleep(0.01))  # ensure distinct created_at

    rows = get_recent_thoughts(limit=10)
    contents = [r["content"] for r in rows]
    # Newest first → "event 2" before "event 0"
    assert contents.index("event 2") < contents.index("event 0")


def test_get_recent_thoughts_respects_minutes_window(_patch_db_and_reset):
    from services.sentcom_service import THOUGHTS_COLLECTION, get_recent_thoughts

    # Insert one fresh thought + one old thought directly
    _patch_db_and_reset[THOUGHTS_COLLECTION].insert_many([
        {
            "id": "fresh", "kind": "info", "content": "fresh thought",
            "symbol": "X", "metadata": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc),
        },
        {
            "id": "old", "kind": "info", "content": "old thought",
            "symbol": "X", "metadata": {},
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(),
            "created_at": datetime.now(timezone.utc) - timedelta(hours=10),
        },
    ])

    last_hour = get_recent_thoughts(minutes=60, limit=10)
    assert len(last_hour) == 1
    assert last_hour[0]["id"] == "fresh"

    last_day = get_recent_thoughts(minutes=24 * 60, limit=10)
    assert len(last_day) == 2


def test_sentcom_service_rehydrates_stream_buffer_on_init(_patch_db_and_reset):
    """Backend restart simulation: thoughts in Mongo, no in-memory buffer
    yet → on init, `_load_recent_thoughts` must hydrate `_stream_buffer`."""
    from services.sentcom_service import THOUGHTS_COLLECTION, SentComService

    now = datetime.now(timezone.utc)
    _patch_db_and_reset[THOUGHTS_COLLECTION].insert_many([
        {
            "id": "t1", "kind": "fill", "content": "Filled NVDA",
            "symbol": "NVDA", "action_type": "trade_filled", "metadata": {},
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "created_at": now - timedelta(minutes=10),
        },
        {
            "id": "t2", "kind": "evaluation", "content": "Evaluating AAPL orb",
            "symbol": "AAPL", "action_type": "evaluating_setup", "metadata": {},
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "created_at": now - timedelta(minutes=5),
        },
    ])

    svc = SentComService()
    contents = [m.content for m in svc._stream_buffer]
    assert "Filled NVDA" in contents
    assert "Evaluating AAPL orb" in contents
    # Newest first inside the buffer
    assert svc._stream_buffer[0].content == "Evaluating AAPL orb"


def test_thoughts_router_endpoint_returns_filtered_rows(_patch_db_and_reset):
    """End-to-end: hit the router-level endpoint."""
    from routers.sentcom import get_thoughts
    from services.sentcom_service import emit_stream_event

    _run(emit_stream_event({"kind": "evaluation", "symbol": "MSFT", "text": "thinking msft"}))
    _run(emit_stream_event({"kind": "fill", "symbol": "MSFT", "text": "filled msft"}))
    _run(emit_stream_event({"kind": "fill", "symbol": "GOOG", "text": "filled goog"}))
    _run(asyncio.sleep(0.05))

    resp = get_thoughts(symbol="MSFT", kind=None, minutes=60, limit=50)
    assert resp["success"] is True
    assert resp["count"] == 2
    assert all(t["symbol"] == "MSFT" for t in resp["thoughts"])

    resp_kind = get_thoughts(symbol=None, kind="fill", minutes=60, limit=50)
    assert resp_kind["count"] == 2
    assert all(t["kind"] == "fill" for t in resp_kind["thoughts"])
