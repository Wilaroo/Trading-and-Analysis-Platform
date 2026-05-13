"""v19.34.125 — regression for the schema-fixed `/diagnostic/bracket-lifecycle`
endpoint.

Pre-fix, the endpoint queried `ts` (ISO string) against the persistence
layer that actually stamps `created_at` (BSON datetime). Result: every
call returned `0 events / 0 trades` even on a day when the bot had
cancelled 100+ brackets. This regression locks the writer/reader
schema contract.

Coverage:
  • Reader queries `created_at` as a datetime range (no `ts`).
  • `phase` values map to the operator-readable categories that match
    what the writer in `bracket_reissue_service.py` actually emits
    (`done`, `cancel`, `submit`, `throttle`, `boot_zombie_sweep`).
  • Mass-cancel cluster detection (5+ within 60s) still fires.
  • `naked_positions` surface (cancel succeeded but submit failed —
    the catastrophic state from the -$25k incident).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _ev(*, phase, success, symbol, trade_id, created_at):
    return {
        "phase": phase, "success": success, "symbol": symbol,
        "trade_id": trade_id, "created_at": created_at,
        "reason": "test", "started_at": created_at.isoformat(),
    }


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs
    def sort(self, *_a, **_k):
        return self
    def limit(self, *_a, **_k):
        return self
    def __iter__(self):
        return iter(self._docs)


def _patch_db(events):
    """Return a stub DB whose bracket_lifecycle_events collection
    yields `events` from .find() and reports sensible counts."""
    coll = MagicMock()
    coll.find = MagicMock(return_value=_FakeCursor(events))
    coll.estimated_document_count = MagicMock(return_value=len(events))
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=coll)
    return db, coll


def test_queries_created_at_not_ts():
    """The reader MUST hit `created_at` (the field the writer stamps),
    not the legacy `ts` field that never existed."""
    from routers import diagnostic_router

    today = datetime.now(timezone.utc).replace(hour=14, minute=0, second=0, microsecond=0)
    events = [_ev(phase="done", success=True, symbol="AAPL",
                  trade_id="t1", created_at=today)]
    db, coll = _patch_db(events)
    with patch.object(diagnostic_router, "_get_db", return_value=db):
        resp = diagnostic_router.bracket_lifecycle_audit()

    # Verify the query that hit Mongo was on created_at (datetime range).
    # The endpoint also makes a second `.find()` probe for the latest
    # event in the collection, so check the FIRST call.
    first_call = coll.find.call_args_list[0]
    query = first_call.args[0] if first_call.args else first_call.kwargs.get("filter") or {}
    assert "created_at" in query, f"reader still using legacy field: {query}"
    assert "ts" not in query, f"reader regressed back to ts: {query}"
    assert "$gte" in query["created_at"]
    assert "$lt" in query["created_at"]
    # Datetime, not string
    assert hasattr(query["created_at"]["$gte"], "year")

    assert resp["success"] is True
    assert resp["total_events"] == 1
    assert resp["unique_trades"] == 1


def test_phase_classification_matches_writer_schema():
    """The five phases written by `bracket_reissue_service.py` must
    each map to a non-`unknown:*` category."""
    from routers import diagnostic_router

    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
    events = [
        _ev(phase="done",      success=True,  symbol="AAPL", trade_id="t1", created_at=now),
        _ev(phase="cancel",    success=False, symbol="MSFT", trade_id="t2", created_at=now),
        _ev(phase="submit",    success=False, symbol="NVDA", trade_id="t3", created_at=now),
        _ev(phase="throttle",  success=False, symbol="GOOG", trade_id="t4", created_at=now),
        _ev(phase="boot_zombie_sweep", success=True, symbol="META", trade_id="t5",
            created_at=now),
    ]
    db, _ = _patch_db(events)
    with patch.object(diagnostic_router, "_get_db", return_value=db):
        resp = diagnostic_router.bracket_lifecycle_audit()

    cats = {row["trade_id"]: row["last_category"] for row in resp["per_trade"]}
    assert cats["t1"] == "reissue"
    assert cats["t2"] == "cancel_failed"
    assert cats["t3"] == "naked"
    assert cats["t4"] == "throttled"
    assert cats["t5"] == "boot_observation"
    # The catastrophic state (cancel OK + submit FAIL) is surfaced separately
    assert any(n["trade_id"] == "t3" for n in resp["naked_positions"])


def test_mass_cancel_cluster_detection():
    """5+ cancel-class events within 60s must flag a cluster."""
    from routers import diagnostic_router

    base = datetime.now(timezone.utc).replace(hour=15, minute=29, second=0, microsecond=0)
    events = [
        _ev(phase="cancel", success=False, symbol=f"S{i}", trade_id=f"t{i}",
            created_at=base + timedelta(seconds=i * 8))
        for i in range(7)  # 7 cancels in 56s → one cluster
    ]
    db, _ = _patch_db(events)
    with patch.object(diagnostic_router, "_get_db", return_value=db):
        resp = diagnostic_router.bracket_lifecycle_audit()

    assert len(resp["mass_cancel_clusters"]) == 1
    assert resp["mass_cancel_clusters"][0]["cancel_count"] == 7


def test_empty_collection_returns_clean_summary():
    """No events → success=True with explanatory summary."""
    from routers import diagnostic_router

    db, _ = _patch_db([])
    with patch.object(diagnostic_router, "_get_db", return_value=db):
        resp = diagnostic_router.bracket_lifecycle_audit()

    assert resp["success"] is True
    assert resp["total_events"] == 0
    assert resp["unique_trades"] == 0
    assert resp["mass_cancel_clusters"] == []
    assert resp["naked_positions"] == []


def test_invalid_date_returns_error():
    from routers import diagnostic_router

    db, _ = _patch_db([])
    with patch.object(diagnostic_router, "_get_db", return_value=db):
        resp = diagnostic_router.bracket_lifecycle_audit(date="not-a-date")
    assert resp["success"] is False
    assert "invalid date" in resp["error"].lower()
