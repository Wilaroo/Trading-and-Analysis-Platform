"""v19.34.94 — Cancel-queue TTL/reaper regression tests.

Locks in:
  - Entries that sit `pending` > 10 min are auto-expired with a clear error.
  - Entries that sit `claimed` > 5 min (pusher died mid-cancel) revert to
    `pending` so the next poll can retry.
  - Fresh entries are never reaped.
  - Reaper runs on every `GET /cancellations/pending` (no separate task).
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone, timedelta

import pytest


@pytest.fixture
def fresh_module():
    """Reload routers.ib and clear the cancellation queue."""
    if "routers.ib" in sys.modules:
        importlib.reload(sys.modules["routers.ib"])
    import routers.ib as ib_mod
    ib_mod._cancellation_queue.clear()
    yield ib_mod
    ib_mod._cancellation_queue.clear()


def test_fresh_pending_not_reaped(fresh_module):
    """Just-queued entries must remain pending."""
    ib_mod = fresh_module
    ib_mod.queue_cancellation(100, reason="fresh")
    resp = ib_mod.get_pending_cancellations()
    assert resp["count"] == 1
    assert resp["reaped"]["expired"] == 0
    assert resp["reaped"]["reverted_to_pending"] == 0
    assert ib_mod._cancellation_queue[100]["status"] == "pending"


def test_old_pending_auto_expired(fresh_module):
    """A pending entry older than 10 min must be auto-expired."""
    ib_mod = fresh_module
    ib_mod.queue_cancellation(200, reason="old-orphan")
    eleven_min_ago = datetime.now(timezone.utc) - timedelta(minutes=11)
    ib_mod._cancellation_queue[200]["requested_at"] = eleven_min_ago.isoformat()
    resp = ib_mod.get_pending_cancellations()
    assert resp["count"] == 0
    assert resp["reaped"]["expired"] == 1
    entry = ib_mod._cancellation_queue[200]
    assert entry["status"] == "expired"
    assert "Auto-expired" in (entry["error"] or "")


def test_claimed_too_long_reverts_to_pending(fresh_module):
    """A claimed entry with no result for > 5 min reverts to pending."""
    ib_mod = fresh_module
    ib_mod.queue_cancellation(300, reason="pusher-died")
    ib_mod._cancellation_queue[300]["status"] = "claimed"
    six_min_ago = datetime.now(timezone.utc) - timedelta(minutes=6)
    ib_mod._cancellation_queue[300]["claimed_at"] = six_min_ago.isoformat()
    resp = ib_mod.get_pending_cancellations()
    assert resp["count"] == 1
    assert resp["reaped"]["reverted_to_pending"] == 1
    entry = ib_mod._cancellation_queue[300]
    assert entry["status"] == "pending"
    assert entry["claimed_at"] is None


def test_terminal_states_not_touched(fresh_module):
    """cancelled/failed/not_found entries are never reaped."""
    ib_mod = fresh_module
    for oid, status in [(401, "cancelled"), (402, "failed"), (403, "not_found")]:
        ib_mod.queue_cancellation(oid, reason="terminal")
        ib_mod._cancellation_queue[oid]["status"] = status
        ancient = datetime.now(timezone.utc) - timedelta(hours=1)
        ib_mod._cancellation_queue[oid]["requested_at"] = ancient.isoformat()
        ib_mod._cancellation_queue[oid]["claimed_at"] = ancient.isoformat()
    resp = ib_mod.get_pending_cancellations()
    assert resp["count"] == 0
    assert resp["reaped"] == {"expired": 0, "reverted_to_pending": 0}
    assert ib_mod._cancellation_queue[401]["status"] == "cancelled"
    assert ib_mod._cancellation_queue[402]["status"] == "failed"
    assert ib_mod._cancellation_queue[403]["status"] == "not_found"


def test_recently_claimed_not_reverted(fresh_module):
    """A claim that's only 30s old should NOT be reverted yet."""
    ib_mod = fresh_module
    ib_mod.queue_cancellation(500, reason="recent-claim")
    ib_mod._cancellation_queue[500]["status"] = "claimed"
    thirty_s_ago = datetime.now(timezone.utc) - timedelta(seconds=30)
    ib_mod._cancellation_queue[500]["claimed_at"] = thirty_s_ago.isoformat()
    resp = ib_mod.get_pending_cancellations()
    assert resp["reaped"]["reverted_to_pending"] == 0
    assert ib_mod._cancellation_queue[500]["status"] == "claimed"


def test_malformed_timestamps_dont_crash_reaper(fresh_module):
    """A malformed requested_at or claimed_at must not crash the reaper."""
    ib_mod = fresh_module
    ib_mod.queue_cancellation(600, reason="malformed")
    ib_mod._cancellation_queue[600]["requested_at"] = "not-a-real-iso-string"
    ib_mod.queue_cancellation(601, reason="malformed2")
    ib_mod._cancellation_queue[601]["status"] = "claimed"
    ib_mod._cancellation_queue[601]["claimed_at"] = "still-not-a-real-iso"
    # Must NOT raise.
    resp = ib_mod.get_pending_cancellations()
    assert resp["success"] is True
