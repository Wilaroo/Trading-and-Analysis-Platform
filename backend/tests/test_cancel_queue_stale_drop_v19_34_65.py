"""v19.34.65 — Stale-drop guard tests for the IB cancellation queue.

Scope: ensure the orphan-gtc auto-sweep stops re-arming dead IB
order IDs forever once IB has conclusively reported them gone.

Failure modes covered:
  1. Fatal IB error (10147 "Order not found") → 1-strike stale_dropped.
  2. Generic failure → 3-strike stale_dropped.
  3. Pusher reports `not_found` → immediate stale_dropped.
  4. Re-queue attempts on a stale_dropped entry are no-ops.
  5. A successful cancel resets the failure_count.
"""
import importlib
import sys

import pytest


@pytest.fixture()
def ib_module():
    """Fresh import so the in-memory queue starts empty per test."""
    # Drop any cached module so the in-memory dicts are clean.
    for mod_name in list(sys.modules):
        if mod_name == "routers.ib" or mod_name.endswith(".routers.ib"):
            del sys.modules[mod_name]
    sys.path.insert(0, "/app/backend")
    mod = importlib.import_module("routers.ib")
    # Ensure queue is empty.
    mod._cancellation_queue.clear()
    yield mod
    mod._cancellation_queue.clear()


def _report_failed(ib_module, ib_order_id: int, error: str):
    """Helper — invoke the result endpoint handler directly."""
    return ib_module.report_cancellation_result(
        ib_module.CancellationResult(
            ib_order_id=ib_order_id,
            status="failed",
            error=error,
        )
    )


def test_fatal_error_10147_drops_after_one_failure(ib_module):
    """10147 is fatal — the entry should be `stale_dropped` after a single failure."""
    entry = ib_module.queue_cancellation(101, reason="orphan-gtc auto-sweep")
    assert entry["status"] == "pending"
    assert entry["failure_count"] == 0

    resp = _report_failed(ib_module, 101, "Error 10147, reqId 101: OrderId 101 that needs to be cancelled is not found")
    cancellation = resp["cancellation"]
    assert cancellation["status"] == "stale_dropped"
    assert cancellation["failure_count"] == 1
    assert cancellation["stale_dropped_reason"] == "fatal_ib_error"


def test_generic_failure_drops_after_three_strikes(ib_module):
    """Non-fatal errors get 3 attempts before being marked stale_dropped."""
    ib_module.queue_cancellation(202, reason="orphan-gtc auto-sweep")
    # Strike 1
    resp = _report_failed(ib_module, 202, "transient network blip")
    assert resp["cancellation"]["status"] == "failed"
    assert resp["cancellation"]["failure_count"] == 1
    # Re-queue (reconciler retry) — should be allowed since not yet stale.
    ib_module.queue_cancellation(202, reason="orphan-gtc auto-sweep")
    assert ib_module._cancellation_queue[202]["status"] == "pending"
    assert ib_module._cancellation_queue[202]["failure_count"] == 1
    # Strike 2
    resp = _report_failed(ib_module, 202, "another transient blip")
    assert resp["cancellation"]["status"] == "failed"
    assert resp["cancellation"]["failure_count"] == 2
    # Strike 3 → stale_dropped.
    ib_module.queue_cancellation(202, reason="orphan-gtc auto-sweep")
    resp = _report_failed(ib_module, 202, "still failing")
    assert resp["cancellation"]["status"] == "stale_dropped"
    assert resp["cancellation"]["failure_count"] == 3
    assert resp["cancellation"]["stale_dropped_reason"] == "exceeded_failure_threshold"


def test_not_found_is_immediate_stale_drop(ib_module):
    """Pusher-reported `not_found` is conclusive — drop immediately."""
    ib_module.queue_cancellation(303, reason="orphan-gtc auto-sweep")
    resp = ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=303, status="not_found")
    )
    assert resp["cancellation"]["status"] == "stale_dropped"
    assert resp["cancellation"]["stale_dropped_reason"] == "pusher_reported_not_found"


def test_requeue_on_stale_dropped_is_noop(ib_module):
    """Once stale_dropped, queue_cancellation must NOT re-arm the order.

    This is the core guarantee that stops the log-spam loop: the
    orphan-gtc reconciler will keep calling queue_cancellation every
    scan cycle, but each call returns the existing terminal entry
    unchanged — the pusher never sees it again.
    """
    ib_module.queue_cancellation(404, reason="orphan-gtc auto-sweep")
    _report_failed(ib_module, 404, "Error 10147 OrderId not found")
    assert ib_module._cancellation_queue[404]["status"] == "stale_dropped"

    # Re-queue 5x — should remain stale_dropped each time.
    for _ in range(5):
        entry = ib_module.queue_cancellation(404, reason="orphan-gtc auto-sweep")
        assert entry["status"] == "stale_dropped"
        assert entry["failure_count"] == 1  # unchanged

    # And it must NOT appear in /cancellations/pending output.
    pending_resp = ib_module.get_pending_cancellations()
    pending_ids = [c["ib_order_id"] for c in pending_resp["cancellations"]]
    assert 404 not in pending_ids


def test_successful_cancel_resets_failure_count(ib_module):
    """A clean `cancelled` result resets the strike counter so the
    same ib_order_id (if ever reused) starts fresh."""
    ib_module.queue_cancellation(505, reason="orphan-gtc auto-sweep")
    _report_failed(ib_module, 505, "transient blip")
    assert ib_module._cancellation_queue[505]["failure_count"] == 1

    ib_module.queue_cancellation(505, reason="orphan-gtc auto-sweep")
    resp = ib_module.report_cancellation_result(
        ib_module.CancellationResult(ib_order_id=505, status="cancelled")
    )
    assert resp["cancellation"]["status"] == "cancelled"
    assert resp["cancellation"]["failure_count"] == 0


def test_fatal_error_codes_are_detected(ib_module):
    """Spot-check the _is_fatal_cancel_error helper across the documented codes."""
    assert ib_module._is_fatal_cancel_error("Error 10147 OrderId not found") is True
    assert ib_module._is_fatal_cancel_error("Error 10148 already filled") is True
    assert ib_module._is_fatal_cancel_error("Error 200: No security definition") is True
    assert ib_module._is_fatal_cancel_error("Error 1100 connection lost") is False
    assert ib_module._is_fatal_cancel_error("") is False
    assert ib_module._is_fatal_cancel_error(None) is False
