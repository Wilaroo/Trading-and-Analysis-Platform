"""
Regression tests for OrderQueueService.reconcile_dead_letters (P1).

Uses the already-running local backend's Mongo via the singleton service
with its own ephemeral documents (custom `_reconcile_test_` order_id prefix
+ teardown). No external network needed.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.order_queue_service import (
    OrderStatus,
    get_order_queue_service,
)

RECONCILE_PREFIX = "_reconcile_test_"


def _seed(service, order_id, status, ts_field, age_seconds, symbol="TEST"):
    """Insert a synthetic order with a specific status and timestamp-age."""
    now = datetime.now(timezone.utc)
    ts_iso = (now - timedelta(seconds=age_seconds)).isoformat()
    doc = {
        "order_id": f"{RECONCILE_PREFIX}{order_id}",
        "symbol": symbol,
        "action": "BUY",
        "quantity": 10,
        "order_type": "MKT",
        "time_in_force": "DAY",
        "status": status,
        "queued_at": ts_iso if ts_field == "queued_at" else now.isoformat(),
        "claimed_at": ts_iso if ts_field == "claimed_at" else None,
        "executed_at": ts_iso if ts_field == "executed_at" else None,
        "fill_price": None,
        "filled_qty": None,
        "ib_order_id": None,
        "error": None,
        "attempts": 0,
    }
    # Ensure indexes exist before inserting
    if not service._initialized:
        service.initialize()
    # Remove any leftover from previous run
    service._collection.delete_one({"order_id": doc["order_id"]})
    service._collection.insert_one(doc)


@pytest.fixture(autouse=True)
def cleanup_reconcile_docs():
    service = get_order_queue_service()
    if not service._initialized:
        service.initialize()
    service._collection.delete_many({"order_id": {"$regex": f"^{RECONCILE_PREFIX}"}})
    yield
    service._collection.delete_many({"order_id": {"$regex": f"^{RECONCILE_PREFIX}"}})


def _get(service, short_id):
    return service._collection.find_one(
        {"order_id": f"{RECONCILE_PREFIX}{short_id}"}, {"_id": 0},
    )


def test_reconcile_pending_past_timeout_becomes_timeout():
    svc = get_order_queue_service()
    _seed(svc, "p1", OrderStatus.PENDING.value, "queued_at", age_seconds=180)
    summary = svc.reconcile_dead_letters(pending_timeout_sec=120)
    assert summary["timed_out"] >= 1
    assert summary["by_status"]["pending"] >= 1
    doc = _get(svc, "p1")
    assert doc["status"] == OrderStatus.TIMEOUT.value
    assert "no pusher pickup" in (doc.get("error") or "")
    assert doc.get("timed_out_at") is not None


def test_reconcile_pending_within_timeout_untouched():
    svc = get_order_queue_service()
    _seed(svc, "p2", OrderStatus.PENDING.value, "queued_at", age_seconds=10)
    summary = svc.reconcile_dead_letters(pending_timeout_sec=120)
    # our seeded doc should NOT be in the list
    ours = [o for o in summary["orders"]
            if (o.get("order_id") or "").endswith("p2")]
    assert ours == []
    doc = _get(svc, "p2")
    assert doc["status"] == OrderStatus.PENDING.value


def test_reconcile_claimed_crash_recovery():
    svc = get_order_queue_service()
    _seed(svc, "c1", OrderStatus.CLAIMED.value, "claimed_at", age_seconds=300)
    summary = svc.reconcile_dead_letters(claimed_timeout_sec=120)
    doc = _get(svc, "c1")
    assert doc["status"] == OrderStatus.TIMEOUT.value
    assert "pusher claimed" in (doc.get("error") or "")
    # surfaced in the return summary
    ours = [o for o in summary["orders"]
            if (o.get("order_id") or "").endswith("c1")]
    assert len(ours) == 1
    assert ours[0]["prior_status"] == "claimed"
    assert ours[0]["age_sec"] is not None and ours[0]["age_sec"] >= 120


def test_reconcile_executing_silent_reject():
    svc = get_order_queue_service()
    _seed(svc, "e1", OrderStatus.EXECUTING.value, "executed_at", age_seconds=600)
    summary = svc.reconcile_dead_letters(executing_timeout_sec=300)
    doc = _get(svc, "e1")
    assert doc["status"] == OrderStatus.TIMEOUT.value
    assert "broker ACK/fill never arrived" in (doc.get("error") or "")
    ours = [o for o in summary["orders"]
            if (o.get("order_id") or "").endswith("e1")]
    assert len(ours) == 1
    assert ours[0]["prior_status"] == "executing"


def test_reconcile_returns_zero_when_no_stale_orders():
    svc = get_order_queue_service()
    _seed(svc, "fresh1", OrderStatus.PENDING.value, "queued_at", age_seconds=5)
    summary = svc.reconcile_dead_letters(
        pending_timeout_sec=120, claimed_timeout_sec=120, executing_timeout_sec=300,
    )
    ours = [o for o in summary["orders"]
            if (o.get("order_id") or "").startswith(RECONCILE_PREFIX)]
    assert ours == []


def test_reconcile_filled_and_rejected_never_touched():
    svc = get_order_queue_service()
    _seed(svc, "f1", "filled", "executed_at", age_seconds=99999)
    _seed(svc, "r1", "rejected", "executed_at", age_seconds=99999)
    _seed(svc, "x1", "cancelled", "executed_at", age_seconds=99999)
    svc.reconcile_dead_letters()
    for sid, expected in [("f1", "filled"), ("r1", "rejected"), ("x1", "cancelled")]:
        doc = _get(svc, sid)
        assert doc["status"] == expected, f"{sid} must remain {expected}"


def test_reconcile_api_endpoint_roundtrip(api_base_url):
    """Hit /api/ib/orders/reconcile and confirm the summary shape."""
    import requests
    svc = get_order_queue_service()
    _seed(svc, "api1", OrderStatus.PENDING.value, "queued_at", age_seconds=180)
    r = requests.post(
        f"{api_base_url}/api/ib/orders/reconcile?pending_timeout_sec=120",
        timeout=5,
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert "timed_out" in body
    assert "by_status" in body
    assert "orders" in body
    # Our seeded order should now be TIMEOUT
    doc = _get(svc, "api1")
    assert doc["status"] == OrderStatus.TIMEOUT.value
