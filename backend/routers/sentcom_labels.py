"""
Wave 4 (#8) — Operator RLHF Labels
==================================

Adds a thin endpoint that lets the V5 stream UI capture operator
👍/👎 reactions on individual stream events. These reactions are the
ground-truth labels that close the loop on the self-improving model:
the bot sees a setup → forms a decision → the operator agrees or
disagrees post-hoc → the label feeds the per-Trade ML model's reward
signal alongside the realised P&L.

DESIGN
------
- One row per (event_id, operator_id) with `label ∈ {up, down}` +
  optional 1-line note.
- `event_id` is the SentCom message id (`sentcom_<unix>_<n>` from
  `sentcom_thoughts.id`). When operator hits 👍 again on the same
  event, we UPDATE not insert (idempotent toggle); a follow-up 👎
  flips the label cleanly.
- TTL: 90 days (longer than `sentcom_thoughts` 7d because the labels
  can survive past the events themselves; the training pipeline
  only needs the (symbol, action_type, decision, label, ts)
  tuple to learn).
- We DO NOT block on this; the UI fires-and-forgets so a slow Mongo
  doesn't pause stream interactions.

The downstream training pipeline will read `sentcom_labels` joined
with `sentcom_thoughts` by event_id, and use the label-vs-outcome
pair as a soft RLHF signal (in addition to realised P&L).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sentcom", tags=["SentCom"])


_LABEL_VALUES = {"up", "down", "clear"}
_COLLECTION = "sentcom_labels"
_TTL_DAYS = 90
_indexed_once = False


def _get_db():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    client = MongoClient(mongo_url)
    return client[db_name]


def _ensure_indexes():
    global _indexed_once
    if _indexed_once:
        return
    try:
        col = _get_db()[_COLLECTION]
        col.create_index(
            "ts",
            expireAfterSeconds=_TTL_DAYS * 86400,
            name="ts_ttl",
        )
        # Idempotent toggle: one row per (event_id, operator_id).
        col.create_index(
            [("event_id", 1), ("operator_id", 1)],
            unique=True,
            name="event_operator_uniq",
        )
        # Training-pipe hot path: scan recent labels by symbol or kind.
        col.create_index([("symbol", 1), ("ts", -1)], name="symbol_recent")
        col.create_index([("kind", 1), ("ts", -1)], name="kind_recent")
        _indexed_once = True
    except Exception as e:
        logger.debug(f"sentcom_labels index init skipped: {e}")


class StreamLabelRequest(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=200)
    label: str = Field(..., description="up | down | clear (clear removes the label)")
    operator_id: str = Field(default="default", min_length=1, max_length=100)
    # Optional context — UI captures these so the training pipeline
    # doesn't need to re-join with sentcom_thoughts for the common
    # filter dimensions.
    symbol: Optional[str] = None
    kind: Optional[str] = None
    action_type: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)


@router.post("/stream/label")
async def upsert_stream_label(req: StreamLabelRequest):
    """Operator 👍 / 👎 on a stream event.

    Idempotent: hitting the same label twice is a no-op (returns the
    existing row's `_id`); flipping (up → down) updates the row;
    `label="clear"` removes the row.
    """
    if req.label not in _LABEL_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"label must be one of {sorted(_LABEL_VALUES)}",
        )
    _ensure_indexes()
    col = _get_db()[_COLLECTION]
    key = {"event_id": req.event_id, "operator_id": req.operator_id}

    if req.label == "clear":
        result = col.delete_one(key)
        return {
            "success": True,
            "action": "cleared" if result.deleted_count else "no_op",
            "event_id": req.event_id,
        }

    update_doc = {
        "$set": {
            "label": req.label,
            "ts": datetime.now(timezone.utc),
            "symbol": (req.symbol or "").upper() or None,
            "kind": req.kind,
            "action_type": req.action_type,
            "note": req.note,
        },
        "$setOnInsert": {
            "event_id": req.event_id,
            "operator_id": req.operator_id,
            "first_labeled_at": datetime.now(timezone.utc),
        },
    }
    result = col.update_one(key, update_doc, upsert=True)
    return {
        "success": True,
        "action": "inserted" if result.upserted_id else "updated",
        "event_id": req.event_id,
        "label": req.label,
    }


@router.get("/stream/labels")
async def get_stream_labels(
    operator_id: str = Query("default"),
    minutes: int = Query(1440, ge=1, le=129600),  # default 24h, max 90d
    symbol: Optional[str] = Query(None),
    label: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """List recent labels for an operator. Used by the V5 UI to:
      - Hydrate the 👍/👎 state of visible rows on initial render
      - Power a "today: 12 👍 / 4 👎" counter in the HUD/stream header
      - Provide an export point for the training pipeline.
    """
    from datetime import timedelta
    _ensure_indexes()
    col = _get_db()[_COLLECTION]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = {"operator_id": operator_id, "ts": {"$gte": cutoff}}
    if symbol:
        query["symbol"] = symbol.upper()
    if label and label in {"up", "down"}:
        query["label"] = label

    cursor = col.find(query, {"_id": 0}).sort("ts", -1).limit(limit)
    rows = []
    for r in cursor:
        if isinstance(r.get("ts"), datetime):
            r["ts"] = r["ts"].isoformat()
        if isinstance(r.get("first_labeled_at"), datetime):
            r["first_labeled_at"] = r["first_labeled_at"].isoformat()
        rows.append(r)

    # Counts are O(1) for the operator UI to show "X up / Y down today".
    counts = {"up": 0, "down": 0}
    for r in rows:
        if r.get("label") in counts:
            counts[r["label"]] += 1

    return {
        "success": True,
        "labels": rows,
        "count": len(rows),
        "counts": counts,
        "operator_id": operator_id,
    }


@router.get("/stream/label/training-export")
async def training_export(
    minutes: int = Query(10080, ge=60, le=129600),  # default 7d, max 90d
    label: Optional[str] = Query(None, description="up / down — both if omitted"),
    limit: int = Query(2000, ge=1, le=20000),
):
    """JSONL-friendly export joining labels with their stored stream
    events for the per-Trade ML training pipeline.

    Returns rows of:
      { event_id, label, symbol, kind, action_type, note,
        first_labeled_at, ts (last update),
        event: { content, confidence, metadata, timestamp }  }

    The training script can stream-process this without re-querying
    `sentcom_thoughts`.
    """
    from datetime import timedelta
    _ensure_indexes()
    db = _get_db()
    col = db[_COLLECTION]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    query = {"ts": {"$gte": cutoff}}
    if label and label in {"up", "down"}:
        query["label"] = label

    rows = list(
        col.find(query, {"_id": 0}).sort("ts", -1).limit(limit)
    )
    # Hydrate the original stream content where it still exists
    # (sentcom_thoughts has a 7-day TTL — older rows return event=None).
    event_ids = [r.get("event_id") for r in rows if r.get("event_id")]
    thoughts = {
        t.get("id"): t
        for t in db["sentcom_thoughts"]
        .find({"id": {"$in": event_ids}}, {"_id": 0})
    }

    out = []
    for r in rows:
        event = thoughts.get(r.get("event_id"))
        if isinstance(r.get("ts"), datetime):
            r["ts"] = r["ts"].isoformat()
        if isinstance(r.get("first_labeled_at"), datetime):
            r["first_labeled_at"] = r["first_labeled_at"].isoformat()
        if event and isinstance(event.get("created_at"), datetime):
            event["created_at"] = event["created_at"].isoformat()
        out.append({**r, "event": event})

    return {
        "success": True,
        "rows": out,
        "count": len(out),
        "minutes": minutes,
        "label_filter": label,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
