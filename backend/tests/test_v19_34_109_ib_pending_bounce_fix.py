"""
Tests for v19.34.109 — IB_PENDING status to break the duplicate-block bounce.

PRODUCTION INCIDENT TIMELINE 2026-02-12:
  • v19.34.103 widened bracket payload but broke ACK signature → bracket storm.
  • v19.34.107 widened the ACK signature → bracket storm killed.
  • v19.34.108 fixed `PendingSubmit` misclassification → single-leg storm killed.
  • POST-v108: rejection rate dropped 78% → ~10%, but operator still saw a
    constant trickle of `"Duplicate submission blocked"` rejections. Mapped
    the bounce loop:
       1. Pusher submits abc123 → IB returns PendingSubmit → 30s timeout
       2. v108 reports `pending` (not `rejected`) ← the fix
       3. update_order_status("pending") writes status="pending" to Mongo
       4. Mongo row goes BACK into the pending pool ← THE BUG
       5. Pusher polls, sees abc123 again, hits idempotency cache
       6. Reports `rejected: Duplicate submission blocked`
       7. Reconciler retries adoption → goto 1

v109 introduces an intermediate `IB_PENDING` state for orders that have
already been submitted to IB but haven't terminally resolved. Excluded
from the polling pool, auto-expires after 10 min.

Tests mock the MongoDB collection (per the existing
`test_queue_bracket_passthrough.py` pattern) so they run anywhere
without needing a live Mongo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from services.order_queue_service import OrderQueueService, OrderStatus


def _mk_service() -> OrderQueueService:
    """Build a service with a stub MongoDB collection. The stub records
    every $set update so tests can assert what status the service
    decided to write."""
    svc = OrderQueueService()
    svc._collection = MagicMock()
    svc._collection.insert_one.side_effect = (
        lambda doc: doc.update({"_id": "fake_oid"}) or MagicMock(inserted_id="fake_oid")
    )
    # Default: update_one returns modified_count=1 so update_order_status
    # returns True.
    svc._collection.update_one.return_value = MagicMock(modified_count=1)
    svc._collection.update_many.return_value = MagicMock(modified_count=0)
    svc._initialized = True
    return svc


def _last_set(svc) -> dict:
    """Return the $set payload from the most recent update_one call."""
    args, kwargs = svc._collection.update_one.call_args
    update = args[1] if len(args) > 1 else kwargs["update"]
    return update["$set"]


# ─────────────────────────────────────────────────────────────────────
class TestIbPendingTranslation:

    def test_pending_with_ib_order_id_becomes_ib_pending(self):
        svc = _mk_service()
        svc.update_order_status("abc123", "pending", ib_order_id=99999)
        s = _last_set(svc)
        assert s["status"] == OrderStatus.IB_PENDING.value, (
            f"pending+ib_order_id MUST translate to IB_PENDING; "
            f"got {s['status']}. v109 regression."
        )
        assert s["ib_order_id"] == 99999
        assert "ib_pending_at" in s, (
            "IB_PENDING rows MUST be stamped with ib_pending_at so the "
            "10-min auto-expiry watchdog can find them."
        )

    def test_pending_without_ib_order_id_stays_pending(self):
        """A legit `pending` ack with NO ib_order_id means the pusher
        aborted before reaching IB. That's a real failure signal we
        should NOT mask as IB_PENDING."""
        svc = _mk_service()
        svc.update_order_status("abc123", "pending")
        s = _last_set(svc)
        assert s["status"] == "pending"
        assert "ib_pending_at" not in s

    def test_filled_passes_through_unchanged(self):
        svc = _mk_service()
        svc.update_order_status(
            "abc123", "filled", fill_price=100.5, filled_qty=100,
            ib_order_id=88888,
        )
        s = _last_set(svc)
        assert s["status"] == "filled"
        assert s["fill_price"] == 100.5

    def test_rejected_passes_through_unchanged(self):
        svc = _mk_service()
        svc.update_order_status(
            "abc123", "rejected", ib_order_id=77777,
            error="Real IB rejection",
        )
        s = _last_set(svc)
        assert s["status"] == "rejected"
        assert s["error"] == "Real IB rejection"

    def test_cancelled_passes_through_unchanged(self):
        svc = _mk_service()
        svc.update_order_status("abc123", "cancelled", ib_order_id=66666)
        s = _last_set(svc)
        assert s["status"] == "cancelled"


class TestQueueStatusSurfacesIbPending:
    """The `ib_pending` count must be surfaced in get_queue_status so
    the operator can distinguish 'waiting on IB' from 'truly stuck'."""

    def test_ib_pending_counted_separately(self):
        svc = _mk_service()
        # Stub the aggregation pipeline result.
        svc._collection.aggregate.return_value = iter([
            {"_id": "pending", "count": 5},
            {"_id": "ib_pending", "count": 3},
            {"_id": "filled", "count": 100},
            {"_id": "rejected", "count": 10},
        ])
        out = svc.get_queue_status()
        assert out["ib_pending"] == 3
        assert out["pending"] == 5  # plain pending still counted
        assert out["filled"] == 100
        assert out["total"] == 5 + 3 + 100 + 10

    def test_ib_pending_count_defaults_to_zero(self):
        """When no rows are in IB_PENDING, the field must still be 0
        (not missing) so UI consumers don't have to handle absence."""
        svc = _mk_service()
        svc._collection.aggregate.return_value = iter([
            {"_id": "filled", "count": 50},
        ])
        out = svc.get_queue_status()
        assert out["ib_pending"] == 0


class TestIbPendingAutoExpiry:
    """Stuck IB_PENDING rows (>10 min) get auto-rejected on the next
    get_pending_orders() poll. This is the safety valve when IB never
    sends a terminal state for an order."""

    def test_get_pending_orders_runs_ib_pending_cleanup(self):
        svc = _mk_service()
        # Stub the find cursor: must support .sort() returning iterable.
        cursor = MagicMock()
        cursor.sort.return_value = iter([])
        svc._collection.find.return_value = cursor
        svc.get_pending_orders()
        # We expect TWO update_many calls inside get_pending_orders:
        #   1. CLAIMED >5min → EXPIRED (legacy)
        #   2. IB_PENDING >10min → REJECTED (v109)
        update_many_calls = svc._collection.update_many.call_args_list
        # At minimum, find the IB_PENDING cleanup call.
        ib_cleanup_call = None
        for call in update_many_calls:
            args, _ = call
            filter_q = args[0]
            if filter_q.get("status") == OrderStatus.IB_PENDING.value:
                ib_cleanup_call = call
                break
        assert ib_cleanup_call is not None, (
            "get_pending_orders MUST sweep stale IB_PENDING rows; "
            "v109 watchdog missing."
        )
        # Confirm the filter uses ib_pending_at < 10-min-cutoff
        filter_q = ib_cleanup_call[0][0]
        assert "ib_pending_at" in filter_q
        assert "$lt" in filter_q["ib_pending_at"]
        # Confirm the $set transitions to rejected with a clear error.
        update = ib_cleanup_call[0][1]["$set"]
        assert update["status"] == OrderStatus.REJECTED.value
        assert "Auto-expired" in update["error"]


class TestEnumIntegrity:
    """Sanity: IB_PENDING enum exists and is exposed."""

    def test_ib_pending_enum_value(self):
        assert OrderStatus.IB_PENDING.value == "ib_pending"

    def test_ib_pending_distinct_from_pending(self):
        assert OrderStatus.IB_PENDING != OrderStatus.PENDING

    def test_ib_pending_distinct_from_claimed(self):
        assert OrderStatus.IB_PENDING != OrderStatus.CLAIMED


class TestBackwardCompatibility:

    def test_v107_bracket_ack_kwargs_accepted(self):
        """v107 widened the ACK with stop_order_id / target_order_id /
        target_order_ids / oca_group. update_order_status MUST accept
        these gracefully (forward-compat for **kwargs callers)."""
        svc = _mk_service()
        # Should not raise — kwargs are absorbed via **_extra_v107_fields.
        svc.update_order_status(
            "abc123", "filled", fill_price=100.0, filled_qty=100,
            ib_order_id=22222,
            stop_order_id=22223,
            target_order_id=22224,
            target_order_ids=[22224, 22225],
            oca_group="oca_TEST_v109",
        )
        s = _last_set(svc)
        assert s["status"] == "filled"

    def test_pre_v109_callsites_still_work(self):
        """Old call sites that don't pass ib_order_id at all (legacy
        rejections from pre-v107 code paths) must continue to work."""
        svc = _mk_service()
        svc.update_order_status("abc123", "rejected", error="legacy")
        s = _last_set(svc)
        assert s["status"] == "rejected"
        assert s["error"] == "legacy"
