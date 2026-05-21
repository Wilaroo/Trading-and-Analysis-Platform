"""v19.34.65c — Cancellation queue stats endpoint tests."""
import importlib
import sys

import pytest


@pytest.fixture()
def ib_module():
    """Fresh import so the in-memory queue starts empty per test."""
    for mod_name in list(sys.modules):
        if mod_name == "routers.ib" or mod_name.endswith(".routers.ib"):
            del sys.modules[mod_name]
    sys.path.insert(0, "/app/backend")
    mod = importlib.import_module("routers.ib")
    mod._cancellation_queue.clear()
    yield mod
    mod._cancellation_queue.clear()


def test_stats_empty_returns_zeros(ib_module):
    """Empty queue → all status buckets zero, recent list empty."""
    resp = ib_module.get_cancellation_stats()
    assert resp["success"] is True
    assert resp["queue_size"] == 0
    assert resp["totals"] == {
        "pending": 0, "claimed": 0, "cancelled": 0,
        "failed": 0, "stale_dropped": 0, "expired": 0,
    }
    assert resp["recent_stale_dropped"] == []
    assert resp["session_started_at"]  # must be set


def test_stats_counts_each_status(ib_module):
    """Each terminal/non-terminal state lands in the correct bucket."""
    ib_module.queue_cancellation(1, reason="r1")  # pending
    ib_module.queue_cancellation(2, reason="r2")
    ib_module.claim_cancellation(2)  # claimed
    ib_module.queue_cancellation(3, reason="r3")
    ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=3, status="cancelled")
    )
    ib_module.queue_cancellation(4, reason="r4")
    ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=4, status="failed", error="transient")
    )
    ib_module.queue_cancellation(5, reason="r5")
    # Fatal error → stale_dropped immediately.
    ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=5, status="failed", error="Error 10147")
    )

    resp = ib_module.get_cancellation_stats()
    t = resp["totals"]
    assert t["pending"] == 1
    assert t["claimed"] == 1
    assert t["cancelled"] == 1
    assert t["failed"] == 1
    assert t["stale_dropped"] == 1
    assert resp["queue_size"] == 5


def test_stats_breakdown_by_reason(ib_module):
    """Stale_dropped entries are bucketed by stale_dropped_reason."""
    # Fatal IB error → fatal_ib_error
    ib_module.queue_cancellation(10, reason="ra")
    ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=10, status="failed", error="Error 10147")
    )
    # Pusher reported not_found → pusher_reported_not_found
    ib_module.queue_cancellation(11, reason="rb")
    ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=11, status="not_found")
    )
    # 3 polls without result → exceeded_poll_served_count_no_result
    ib_module.queue_cancellation(12, reason="rc")
    for _ in range(4):
        ib_module.get_pending_cancellations()

    resp = ib_module.get_cancellation_stats()
    b = resp["stale_dropped_breakdown"]
    assert b["fatal_ib_error"] == 1
    assert b["pusher_reported_not_found"] == 1
    assert b["exceeded_poll_served_count_no_result"] == 1
    assert resp["totals"]["stale_dropped"] == 3


def test_stats_recent_capped_at_ten_newest_first(ib_module):
    """`recent_stale_dropped` returns at most 10 entries, newest first."""
    # Generate 12 stale-dropped entries via fatal errors.
    for i in range(100, 112):
        ib_module.queue_cancellation(i, reason=f"r{i}")
        ib_module.report_cancellation_result(
            ib_module.CancellationResult(
                ib_order_id=i, status="failed", error="Error 10147",
            )
        )
    resp = ib_module.get_cancellation_stats()
    assert resp["totals"]["stale_dropped"] == 12
    recent = resp["recent_stale_dropped"]
    assert len(recent) == 10
    # Sorted newest-first.
    completed = [r["completed_at"] for r in recent]
    assert completed == sorted(completed, reverse=True)


def test_stats_recent_entry_shape(ib_module):
    """Each `recent_stale_dropped` row carries the fields the HUD pill expects."""
    ib_module.queue_cancellation(
        999, reason="v19.34.31 Patch C: pre-attach LIN", requested_by="patch_c",
    )
    ib_module.report_cancellation_result(
        ib_module.CancellationResult(
            ib_order_id=999, status="failed", error="Error 10147 not found",
        )
    )
    resp = ib_module.get_cancellation_stats()
    row = resp["recent_stale_dropped"][0]
    assert row["ib_order_id"] == 999
    assert row["reason"] == "v19.34.31 Patch C: pre-attach LIN"
    assert row["stale_dropped_reason"] == "fatal_ib_error"
    assert "10147" in (row["error"] or "")
    assert row["completed_at"]
