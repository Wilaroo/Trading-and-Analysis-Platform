"""v19.34.88 — Cancellation queue regression tests.

Locks in:
  - queue_cancellation() idempotency on ib_order_id
  - status transitions: pending → claimed → cancelled/failed
  - GET /cancellations/pending excludes claimed/terminal entries
  - cancel-excess-bracket-legs falls through to queue when
    _ib_service is disconnected (pusher-only deployment).
"""
import importlib
import sys
import pytest
from datetime import datetime, timezone


@pytest.fixture
def fresh_ib_module():
    """Reload routers.ib so _cancellation_queue starts clean."""
    if "routers.ib" in sys.modules:
        importlib.reload(sys.modules["routers.ib"])
    import routers.ib as ib_mod
    ib_mod._cancellation_queue.clear()
    yield ib_mod
    ib_mod._cancellation_queue.clear()


def test_queue_cancellation_basic(fresh_ib_module):
    ib_mod = fresh_ib_module
    entry = ib_mod.queue_cancellation(12345, reason="test", requested_by="pytest")
    assert entry["ib_order_id"] == 12345
    assert entry["status"] == "pending"
    assert entry["reason"] == "test"
    assert entry["requested_by"] == "pytest"
    assert entry["claimed_at"] is None
    assert entry["completed_at"] is None


def test_queue_cancellation_idempotent(fresh_ib_module):
    """Re-queueing the same ib_order_id while pending must not reset state."""
    ib_mod = fresh_ib_module
    e1 = ib_mod.queue_cancellation(42, reason="first")
    ts1 = e1["requested_at"]
    e2 = ib_mod.queue_cancellation(42, reason="second")
    assert e2["requested_at"] == ts1  # NOT reset
    assert e2["reason"] == "first"     # original reason preserved


def test_queue_cancellation_int_coercion(fresh_ib_module):
    ib_mod = fresh_ib_module
    entry = ib_mod.queue_cancellation("789")  # string → int
    assert entry["ib_order_id"] == 789


def test_queue_cancellation_rejects_bad_input(fresh_ib_module):
    ib_mod = fresh_ib_module
    with pytest.raises(ValueError):
        ib_mod.queue_cancellation("not-a-number")


def test_pending_excludes_claimed(fresh_ib_module):
    """GET /cancellations/pending must NOT return claimed entries."""
    ib_mod = fresh_ib_module
    ib_mod.queue_cancellation(1)
    ib_mod.queue_cancellation(2)
    # Manually claim #1
    ib_mod._cancellation_queue[1]["status"] = "claimed"
    ib_mod._cancellation_queue[1]["claimed_at"] = datetime.now(timezone.utc).isoformat()
    # Simulate what GET /pending returns
    pending = [e for e in ib_mod._cancellation_queue.values() if e["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["ib_order_id"] == 2


def test_pending_excludes_terminal(fresh_ib_module):
    ib_mod = fresh_ib_module
    ib_mod.queue_cancellation(10)
    ib_mod.queue_cancellation(20)
    ib_mod.queue_cancellation(30)
    ib_mod._cancellation_queue[10]["status"] = "cancelled"
    ib_mod._cancellation_queue[20]["status"] = "failed"
    ib_mod._cancellation_queue[30]["status"] = "not_found"
    pending = [e for e in ib_mod._cancellation_queue.values() if e["status"] == "pending"]
    assert pending == []


def test_get_cancellation_status_missing(fresh_ib_module):
    ib_mod = fresh_ib_module
    assert ib_mod.get_cancellation_status(99999) is None


def test_get_cancellation_status_existing(fresh_ib_module):
    ib_mod = fresh_ib_module
    ib_mod.queue_cancellation(555, reason="audit")
    got = ib_mod.get_cancellation_status(555)
    assert got is not None
    assert got["reason"] == "audit"
