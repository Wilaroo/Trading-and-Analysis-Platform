"""
Wave 2 + Wave 4 regression tests (2026-04-30 v19.8).

Pins the contracts of the two new endpoints:

  • GET  /api/sentcom/stream/history       (Wave 2 #9 — Deep Feed)
  • POST /api/sentcom/stream/label         (Wave 4 #8 — RLHF labels)
  • GET  /api/sentcom/stream/labels        (Wave 4 #8)
  • GET  /api/sentcom/stream/label/training-export

Tests use direct route-function calls (no TestClient) for the same
reason `test_dlq_purge_v19_2.py` does — sidesteps starlette/httpx
version drift in this container.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


# --------------------------------------------------------------------------
# Wave 2 (#9) — Deep Feed history endpoint
# --------------------------------------------------------------------------

def _make_fake_thoughts_db(rows):
    coll = MagicMock()
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=iter(rows))
    coll.find = MagicMock(return_value=cursor)

    class _DB:
        def __getitem__(self, name): return coll
        def get_collection(self, name): return coll
    return _DB(), coll


@pytest.mark.asyncio
async def test_stream_history_basic():
    from routers.sentcom import get_stream_history
    fake_rows = [
        {
            "id": "sentcom_111_1",
            "kind": "skip",
            "action_type": "skip_low_gate",
            "content": "AAPL gate 0.32 below floor",
            "symbol": "AAPL",
            "confidence": 0.32,
            "metadata": {"gate_score": 0.32},
            "created_at": datetime.now(timezone.utc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    ]
    fake_db, _coll = _make_fake_thoughts_db(fake_rows)
    with patch("services.sentcom_service._get_db", return_value=fake_db):
        body = await get_stream_history(minutes=60, limit=500, symbol=None, kind=None, q=None)
    assert body["success"] is True
    assert body["count"] == 1
    msg = body["messages"][0]
    assert msg["symbol"] == "AAPL"
    assert msg["kind"] == "skip"
    assert msg["text"] == msg["content"]


@pytest.mark.asyncio
async def test_stream_history_passes_filters_into_query():
    """Symbol / kind / q must reach the Mongo find query."""
    from routers.sentcom import get_stream_history
    fake_db, coll = _make_fake_thoughts_db([])
    with patch("services.sentcom_service._get_db", return_value=fake_db):
        await get_stream_history(minutes=10, limit=10, symbol="aapl", kind="skip", q="gate")
    call_args = coll.find.call_args
    query = call_args[0][0]
    assert query["symbol"]["$regex"] == "^aapl$"
    assert query["symbol"]["$options"] == "i"
    assert query["kind"] == "skip"
    assert "$or" in query
    or_clauses = query["$or"]
    assert any("content" in c for c in or_clauses)
    assert any("action_type" in c for c in or_clauses)


@pytest.mark.asyncio
async def test_stream_history_handles_missing_thoughts_collection():
    """If the Mongo find raises, the endpoint returns an error envelope
    rather than crashing."""
    from routers.sentcom import get_stream_history
    fake_db, coll = _make_fake_thoughts_db([])
    coll.find.side_effect = RuntimeError("mongo down")
    with patch("services.sentcom_service._get_db", return_value=fake_db):
        body = await get_stream_history(minutes=60, limit=500, symbol=None, kind=None, q=None)
    assert body["success"] is False
    assert body["messages"] == []


# --------------------------------------------------------------------------
# Wave 4 (#8) — RLHF labels endpoints
# --------------------------------------------------------------------------

def _make_fake_labels_db():
    """Stub Mongo with in-process state for upsert / delete / find."""
    state = {}  # (event_id, operator_id) -> doc

    coll = MagicMock()

    def update_one(key, update_doc, upsert=False):
        existing_key = (key["event_id"], key["operator_id"])
        if existing_key in state:
            state[existing_key].update(update_doc.get("$set", {}))
            r = MagicMock(); r.upserted_id = None; r.matched_count = 1
            return r
        if upsert:
            state[existing_key] = {**key, **update_doc.get("$set", {}), **update_doc.get("$setOnInsert", {})}
            r = MagicMock(); r.upserted_id = "abc"; r.matched_count = 0
            return r
        r = MagicMock(); r.upserted_id = None; r.matched_count = 0
        return r

    def delete_one(key):
        existing_key = (key["event_id"], key["operator_id"])
        if existing_key in state:
            del state[existing_key]
            r = MagicMock(); r.deleted_count = 1
            return r
        r = MagicMock(); r.deleted_count = 0
        return r

    def find(query, projection=None):
        rows = list(state.values())
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=iter(rows))
        return cursor

    coll.update_one.side_effect = update_one
    coll.delete_one.side_effect = delete_one
    coll.find.side_effect = find
    coll.create_index = MagicMock()

    class _DB:
        def __getitem__(self, name): return coll
    return _DB(), coll, state


@pytest.mark.asyncio
async def test_label_insert_idempotent():
    from routers.sentcom_labels import upsert_stream_label, StreamLabelRequest
    fake_db, _coll, state = _make_fake_labels_db()
    with patch("routers.sentcom_labels._get_db", return_value=fake_db):
        # Insert
        r1 = await upsert_stream_label(StreamLabelRequest(
            event_id="evt_1", label="up", symbol="AAPL", kind="scan",
        ))
        assert r1["action"] == "inserted"
        # Same label again → updated (idempotent)
        r2 = await upsert_stream_label(StreamLabelRequest(
            event_id="evt_1", label="up", symbol="AAPL",
        ))
        assert r2["action"] == "updated"
        assert len(state) == 1


@pytest.mark.asyncio
async def test_label_flip_up_to_down():
    from routers.sentcom_labels import upsert_stream_label, StreamLabelRequest
    fake_db, _coll, state = _make_fake_labels_db()
    with patch("routers.sentcom_labels._get_db", return_value=fake_db):
        await upsert_stream_label(StreamLabelRequest(event_id="evt_1", label="up"))
        r = await upsert_stream_label(StreamLabelRequest(event_id="evt_1", label="down"))
        assert r["action"] == "updated"
        assert state[("evt_1", "default")]["label"] == "down"


@pytest.mark.asyncio
async def test_label_clear_removes_row():
    from routers.sentcom_labels import upsert_stream_label, StreamLabelRequest
    fake_db, _coll, state = _make_fake_labels_db()
    with patch("routers.sentcom_labels._get_db", return_value=fake_db):
        await upsert_stream_label(StreamLabelRequest(event_id="evt_1", label="up"))
        assert len(state) == 1
        r = await upsert_stream_label(StreamLabelRequest(event_id="evt_1", label="clear"))
        assert r["action"] == "cleared"
        assert len(state) == 0


@pytest.mark.asyncio
async def test_label_invalid_value_raises_400():
    from routers.sentcom_labels import upsert_stream_label, StreamLabelRequest
    with pytest.raises(HTTPException) as excinfo:
        await upsert_stream_label(StreamLabelRequest(event_id="evt", label="sideways"))
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_get_labels_returns_counts():
    from routers.sentcom_labels import upsert_stream_label, get_stream_labels, StreamLabelRequest
    fake_db, _coll, _state = _make_fake_labels_db()
    with patch("routers.sentcom_labels._get_db", return_value=fake_db):
        await upsert_stream_label(StreamLabelRequest(event_id="e1", label="up"))
        await upsert_stream_label(StreamLabelRequest(event_id="e2", label="down"))
        await upsert_stream_label(StreamLabelRequest(event_id="e3", label="up"))
        body = await get_stream_labels(operator_id="default", minutes=60, symbol=None, label=None, limit=500)
    assert body["count"] == 3
    assert body["counts"]["up"] == 2
    assert body["counts"]["down"] == 1


@pytest.mark.asyncio
async def test_label_request_max_note_length():
    """note has max_length=500 — pydantic must reject longer."""
    from routers.sentcom_labels import StreamLabelRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StreamLabelRequest(event_id="x", label="up", note="A" * 501)


@pytest.mark.asyncio
async def test_label_event_id_required():
    """event_id is min_length=1 — empty must be rejected."""
    from routers.sentcom_labels import StreamLabelRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StreamLabelRequest(event_id="", label="up")
