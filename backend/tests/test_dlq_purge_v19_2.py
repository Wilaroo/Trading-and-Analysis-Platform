"""
v19.2 — DLQ purge endpoint tests (2026-04-30)

Why this exists: the V5 HUD's DLQ badge surfaces the count of
permanently-failed historical-data collection requests. With v17/v18
expanding the universe scan, the DLQ accumulates entries IB will
NEVER successfully serve (delisted symbols, ambiguous contracts,
"no security definition" errors). Retrying these wastes IB pacing
budget; they need to be DROPPED from the queue.

This endpoint deletes them. Tests guard:
  ★ permanent_only=True (default) only matches known-permanent errors.
  ★ permanent_only=False without force=True is REJECTED (400).
  ★ Audit log is written.
  ★ dry_run returns the count without deleting.
  ★ older_than_hours filter combines with permanent_only correctly.
  ★ Endpoint shape stable (success / purged_count / by_error_type / sample).

Note: tests call the route function directly (rather than via FastAPI
TestClient) so they run independent of starlette/httpx version drift.
The query/path-arg contract is exercised the same way uvicorn invokes
the function — keyword args mapped from query params.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_fake_queue(failed_docs):
    """Build a fake queue service whose `.collection.find()`/`.delete_many()`
    return / report on the given docs."""
    coll = MagicMock()

    def find(query=None, projection=None):
        rows = list(failed_docs)
        cursor = MagicMock()
        cursor.__iter__ = lambda self: iter(rows)
        cursor.limit = MagicMock(return_value=cursor)
        return cursor

    coll.find.side_effect = find
    coll.delete_many = MagicMock(
        return_value=MagicMock(deleted_count=len(failed_docs))
    )

    service = MagicMock()
    service.collection = coll
    service._initialized = True
    return service


def _make_fake_db():
    """Stub db with a mocked `dlq_purge_log` collection for audit writes."""
    log_col = MagicMock()
    log_col.insert_one = MagicMock()
    log_col.create_index = MagicMock()

    class _DB:
        def __getitem__(self, name):
            return log_col

        def get_collection(self, name):
            return log_col

    return _DB(), log_col


def _call_purge(**kwargs):
    """Invoke the dlq_purge route function with default kwargs."""
    from routers.diagnostic_router import dlq_purge

    defaults = {
        "permanent_only": True,
        "older_than_hours": None,
        "bar_size": None,
        "force": False,
        "dry_run": False,
    }
    defaults.update(kwargs)
    return dlq_purge(**defaults)


# --------------------------------------------------------------------------
# Safety: permanent_only=False without force=True must 400
# --------------------------------------------------------------------------

def test_purge_rejects_non_permanent_without_force():
    """The HARDEST safety guard: a sleepy operator hitting the endpoint
    with permanent_only=false but without force=true should get 400,
    not a mass-deletion."""
    with pytest.raises(HTTPException) as excinfo:
        _call_purge(permanent_only=False, force=False)
    assert excinfo.value.status_code == 400
    assert "force" in str(excinfo.value.detail).lower()


def test_purge_rejects_non_permanent_without_force_default():
    """force defaults to False, so omitting force should also 400."""
    with pytest.raises(HTTPException) as excinfo:
        _call_purge(permanent_only=False)
    assert excinfo.value.status_code == 400


# --------------------------------------------------------------------------
# Default (permanent_only=True) deletes only allowlisted errors
# --------------------------------------------------------------------------

def test_purge_default_deletes_permanent_failures():
    fake_docs = [
        {"symbol": "SLY", "bar_size": "1 min",
         "failure_reason": "No security definition has been found"},
        {"symbol": "OLDSTOCK", "bar_size": "5 mins",
         "result_status": "no_data"},
        {"symbol": "ZOMBIE", "bar_size": "1 day",
         "error": "contract_not_found for ZOMBIE"},
    ]
    fake_service = _make_fake_queue(fake_docs)
    fake_db, fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        body = _call_purge()

    assert body["success"] is True
    assert body["dry_run"] is False
    assert body["purged_count"] == 3
    assert body["permanent_only"] is True
    fake_service.collection.delete_many.assert_called_once()
    fake_log.insert_one.assert_called_once()


def test_purge_default_uses_permanent_allowlist_query():
    """Verify the actual delete query restricts to the known-permanent
    error patterns. A future contributor widening the regex must update
    the test deliberately."""
    fake_service = _make_fake_queue([])
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        _call_purge()

    # delete_many was called with the permanent-only $or query
    args, _kwargs = fake_service.collection.delete_many.call_args
    query = args[0]
    assert query["status"] == "failed"
    assert "$or" in query
    # Confirm the known-permanent strings appear in the regex
    or_clauses = query["$or"]
    regex_str = next(
        (c["failure_reason"]["$regex"] for c in or_clauses
         if "failure_reason" in c),
        "",
    )
    assert "no security definition" in regex_str
    assert "no_data" in regex_str
    assert "contract not found" in regex_str


# --------------------------------------------------------------------------
# Dry-run returns the count without deleting
# --------------------------------------------------------------------------

def test_dry_run_does_not_delete():
    fake_docs = [
        {"symbol": "SLY", "bar_size": "1 min",
         "failure_reason": "No security definition has been found"},
    ]
    fake_service = _make_fake_queue(fake_docs)
    fake_db, fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        body = _call_purge(dry_run=True)

    assert body["dry_run"] is True
    assert body["would_purge_count"] == 1
    fake_service.collection.delete_many.assert_not_called()
    # No audit log entry on dry runs (operator hasn't decided yet)
    fake_log.insert_one.assert_not_called()


# --------------------------------------------------------------------------
# Endpoint shape stable
# --------------------------------------------------------------------------

@pytest.mark.parametrize("dry_run,expected_shape_keys", [
    (
        True,
        ["success", "dry_run", "would_purge_count", "by_error_type",
         "by_bar_size", "sample", "permanent_only", "timestamp"],
    ),
    (
        False,
        ["success", "dry_run", "purged_count", "by_error_type",
         "by_bar_size", "sample", "permanent_only", "timestamp"],
    ),
])
def test_purge_response_shape(dry_run, expected_shape_keys):
    fake_service = _make_fake_queue([
        {"symbol": "TEST", "bar_size": "1 min", "failure_reason": "no_data"},
    ])
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        body = _call_purge(dry_run=dry_run)

    for key in expected_shape_keys:
        assert key in body, f"Response missing key '{key}': {body}"


# --------------------------------------------------------------------------
# Aggregation stats are populated
# --------------------------------------------------------------------------

def test_purge_aggregates_by_error_type_and_bar_size():
    fake_docs = [
        {"symbol": "SLY", "bar_size": "1 min",
         "failure_reason": "No security definition"},
        {"symbol": "ZOMBIE", "bar_size": "1 min",
         "failure_reason": "No security definition"},
        {"symbol": "OLD", "bar_size": "5 mins", "result_status": "no_data"},
    ]
    fake_service = _make_fake_queue(fake_docs)
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        body = _call_purge(dry_run=True)

    assert body["by_bar_size"] == {"1 min": 2, "5 mins": 1}
    assert sum(body["by_error_type"].values()) == 3
    # Sample populated, capped at 10
    assert isinstance(body["sample"], list)
    assert len(body["sample"]) <= 10
    assert all("symbol" in row for row in body["sample"])


# --------------------------------------------------------------------------
# force=true explicitly required for "purge ALL failed" mode
# --------------------------------------------------------------------------

def test_purge_force_mode_works_when_explicitly_requested():
    fake_docs = [
        {"symbol": "TRANSIENT", "bar_size": "1 min",
         "result_status": "rate_limited"},
        {"symbol": "SLY", "bar_size": "1 min",
         "failure_reason": "no security definition"},
    ]
    fake_service = _make_fake_queue(fake_docs)
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        body = _call_purge(permanent_only=False, force=True)

    assert body["purged_count"] == 2
    assert body["permanent_only"] is False
    # Force mode: query should NOT have the permanent allowlist regex
    args, _kwargs = fake_service.collection.delete_many.call_args
    query = args[0]
    assert query["status"] == "failed"
    # Either no $or at all (no other filters) OR only timestamp $or — but
    # NOT the regex-based one.
    if "$or" in query:
        or_clauses = query["$or"]
        regex_present = any(
            isinstance(c, dict)
            and any(isinstance(v, dict) and "$regex" in v for v in c.values())
            for c in or_clauses
        )
        assert not regex_present, (
            "force mode should not add the permanent-only regex filter"
        )


# --------------------------------------------------------------------------
# older_than_hours filter combines with permanent_only correctly ($and)
# --------------------------------------------------------------------------

def test_older_than_hours_with_permanent_only_uses_and():
    """When both permanent_only=True (regex $or) and older_than_hours
    (timestamp $or) are active, the query must combine them via $and."""
    fake_service = _make_fake_queue([])
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        _call_purge(permanent_only=True, older_than_hours=72)

    args, _kwargs = fake_service.collection.delete_many.call_args
    query = args[0]
    assert query["status"] == "failed"
    assert "$and" in query
    assert len(query["$and"]) == 2
    # First clause: regex on the failure fields
    # Second clause: timestamp filter on completed_at / created_at
    timestamp_clause = query["$and"][1]["$or"]
    assert any("completed_at" in c for c in timestamp_clause)
    assert any("created_at" in c for c in timestamp_clause)
    # And the original $or should NOT remain at top level
    assert "$or" not in query


def test_older_than_hours_alone_uses_or_at_top_level():
    """Without permanent_only, the timestamp filter sits at top-level
    via $or (no $and necessary)."""
    fake_service = _make_fake_queue([])
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        _call_purge(permanent_only=False, force=True, older_than_hours=24)

    args, _kwargs = fake_service.collection.delete_many.call_args
    query = args[0]
    assert "$and" not in query
    assert "$or" in query
    # The $or here is the timestamp filter only (no regex)
    or_clauses = query["$or"]
    assert any("completed_at" in c for c in or_clauses)


# --------------------------------------------------------------------------
# bar_size filter narrows the query
# --------------------------------------------------------------------------

def test_bar_size_filter_scopes_query():
    fake_service = _make_fake_queue([])
    fake_db, _fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        _call_purge(bar_size="1 min")

    args, _kwargs = fake_service.collection.delete_many.call_args
    query = args[0]
    assert query.get("bar_size") == "1 min"


# --------------------------------------------------------------------------
# Audit log entry shape is correct
# --------------------------------------------------------------------------

def test_audit_log_entry_shape():
    fake_docs = [
        {"symbol": "SLY", "bar_size": "1 min",
         "failure_reason": "No security definition"},
    ]
    fake_service = _make_fake_queue(fake_docs)
    fake_db, fake_log = _make_fake_db()

    with patch(
        "services.historical_data_queue_service.get_historical_data_queue_service",
        return_value=fake_service,
    ), patch("routers.diagnostic_router._get_db", return_value=fake_db):
        _call_purge(permanent_only=True, older_than_hours=24, bar_size="1 min")

    fake_log.insert_one.assert_called_once()
    entry = fake_log.insert_one.call_args[0][0]
    for key in [
        "ts", "ts_dt", "purged_count", "by_error_type", "by_bar_size",
        "permanent_only", "older_than_hours", "bar_size", "force",
    ]:
        assert key in entry, f"Audit log missing '{key}': {entry}"
    assert entry["permanent_only"] is True
    assert entry["older_than_hours"] == 24
    assert entry["bar_size"] == "1 min"
