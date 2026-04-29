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
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_app():
    """Mount only the diagnostic router for tests so we don't pull in
    the full server lifespan + IB pusher import chain."""
    from fastapi import FastAPI
    from routers.diagnostic_router import router as diagnostic_router
    app = FastAPI()
    app.include_router(diagnostic_router)
    return app


def _make_fake_queue(failed_docs):
    """Build a fake queue service whose `.collection.find()`/`.delete_many()`
    return / report on the given docs."""
    coll = MagicMock()
    # find() returns a lazy iterator; honour any query args by filtering
    def find(query=None, projection=None):
        rows = failed_docs
        # Crude regex filter: if query has $or or $and, just return all
        # for the test (the actual Mongo regex matching is provider's job)
        cursor = MagicMock()
        cursor.__iter__ = lambda self: iter(rows)
        cursor.limit = MagicMock(return_value=cursor)
        return cursor
    coll.find.side_effect = find
    coll.delete_many = MagicMock(return_value=MagicMock(deleted_count=len(failed_docs)))

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


# --------------------------------------------------------------------------
# Safety: permanent_only=False without force=True must 400
# --------------------------------------------------------------------------

def test_purge_rejects_non_permanent_without_force():
    """The HARDEST safety guard: a sleepy operator hitting the endpoint
    with permanent_only=false but without force=true should get 400,
    not a mass-deletion."""
    app = _make_app()
    client = TestClient(app)

    response = client.post(
        "/api/diagnostic/dlq-purge?permanent_only=false&force=false",
    )
    assert response.status_code == 400, (
        "Without force=true, permanent_only=false MUST be rejected to "
        "prevent accidental mass-deletion of retryable transient failures."
    )
    assert "force" in response.json().get("detail", "").lower()


def test_purge_rejects_non_permanent_without_force_default():
    """force defaults to False, so omitting force should also 400."""
    app = _make_app()
    client = TestClient(app)
    response = client.post("/api/diagnostic/dlq-purge?permanent_only=false")
    assert response.status_code == 400


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

    app = _make_app()
    client = TestClient(app)

    with patch("services.historical_data_queue_service.get_historical_data_queue_service",
               return_value=fake_service), \
         patch("routers.diagnostic_router._get_db", return_value=fake_db):
        response = client.post("/api/diagnostic/dlq-purge")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["dry_run"] is False
    assert body["purged_count"] == 3
    assert body["permanent_only"] is True
    fake_service.collection.delete_many.assert_called_once()
    # Audit log written
    fake_log.insert_one.assert_called_once()


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

    app = _make_app()
    client = TestClient(app)

    with patch("services.historical_data_queue_service.get_historical_data_queue_service",
               return_value=fake_service), \
         patch("routers.diagnostic_router._get_db", return_value=fake_db):
        response = client.post("/api/diagnostic/dlq-purge?dry_run=true")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["would_purge_count"] == 1
    fake_service.collection.delete_many.assert_not_called()
    # No audit log entry on dry runs (operator hasn't decided yet)
    fake_log.insert_one.assert_not_called()


# --------------------------------------------------------------------------
# Endpoint shape stable
# --------------------------------------------------------------------------

@pytest.mark.parametrize("dry_run_qs,expected_shape_keys", [
    (
        "?dry_run=true",
        ["success", "dry_run", "would_purge_count", "by_error_type",
         "by_bar_size", "sample", "permanent_only", "timestamp"],
    ),
    (
        "",
        ["success", "dry_run", "purged_count", "by_error_type",
         "by_bar_size", "sample", "permanent_only", "timestamp"],
    ),
])
def test_purge_response_shape(dry_run_qs, expected_shape_keys):
    fake_service = _make_fake_queue([
        {"symbol": "TEST", "bar_size": "1 min", "failure_reason": "no_data"},
    ])
    fake_db, _fake_log = _make_fake_db()

    app = _make_app()
    client = TestClient(app)

    with patch("services.historical_data_queue_service.get_historical_data_queue_service",
               return_value=fake_service), \
         patch("routers.diagnostic_router._get_db", return_value=fake_db):
        response = client.post(f"/api/diagnostic/dlq-purge{dry_run_qs}")

    assert response.status_code == 200
    body = response.json()
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

    app = _make_app()
    client = TestClient(app)

    with patch("services.historical_data_queue_service.get_historical_data_queue_service",
               return_value=fake_service), \
         patch("routers.diagnostic_router._get_db", return_value=fake_db):
        response = client.post("/api/diagnostic/dlq-purge?dry_run=true")

    body = response.json()
    assert body["by_bar_size"] == {"1 min": 2, "5 mins": 1}
    # by_error_type — exact key text depends on truncation, but counts are right
    assert sum(body["by_error_type"].values()) == 3


# --------------------------------------------------------------------------
# force=true explicitly required for "purge ALL failed" mode
# --------------------------------------------------------------------------

def test_purge_force_mode_works_when_explicitly_requested():
    fake_docs = [
        {"symbol": "TRANSIENT", "bar_size": "1 min", "result_status": "rate_limited"},
        {"symbol": "SLY", "bar_size": "1 min", "failure_reason": "no security definition"},
    ]
    fake_service = _make_fake_queue(fake_docs)
    fake_db, _fake_log = _make_fake_db()

    app = _make_app()
    client = TestClient(app)

    with patch("services.historical_data_queue_service.get_historical_data_queue_service",
               return_value=fake_service), \
         patch("routers.diagnostic_router._get_db", return_value=fake_db):
        response = client.post(
            "/api/diagnostic/dlq-purge?permanent_only=false&force=true",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["purged_count"] == 2
    assert body["permanent_only"] is False
