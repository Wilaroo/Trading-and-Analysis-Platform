"""
Tests for v19.34.107b — POST /api/trading-bot/cancel-adopt-oca-storm

Surgical-flush endpoint for orphan ADOPT-OCA recovery wrappers. Validates:
  • Empty snapshot → 0 queued, success.
  • Live ADOPT-OCA orders → all queued; legit brackets untouched.
  • symbol_filter limits the cancel set to a single ticker.
  • dry_run mode previews without queueing.
  • Filled/Cancelled orders are skipped (only pending statuses).
  • Cancels already in-flight (v19.34.88 queue) are not re-queued.

Tests call the route handler function directly (rather than HTTPing the
live backend) so we can mutate the in-memory `_pushed_ib_data["orders"]`
snapshot the handler reads from. Mutating the running backend over HTTP
would require a seed endpoint we don't want in production.
"""
from __future__ import annotations

import pytest

# Import once at module load so all tests share the same modules.
from routers import ib as ib_mod
from routers.trading_bot import cancel_adopt_oca_storm


_LIVE_STORM = [
    # 4 wrappers across 2 storm OCA groups for MTB + RJF
    {"order_id": 115150, "symbol": "MTB", "action": "BUY",
     "quantity": 188, "order_type": "STP", "status": "PreSubmitted",
     "aux_price": 208.42, "oca_group": "ADOPT-OCA-MTB-c0b9db64-a5df6d"},
    {"order_id": 115509, "symbol": "MTB", "action": "BUY",
     "quantity": 188, "order_type": "LMT", "status": "Submitted",
     "limit_price": 204.29, "oca_group": "ADOPT-OCA-MTB-c0b9db64-a5df6d"},
    {"order_id": 115765, "symbol": "RJF", "action": "BUY",
     "quantity": 289, "order_type": "STP", "status": "PreSubmitted",
     "aux_price": 154.66, "oca_group": "ADOPT-OCA-RJF-950c1787-4d1ad8"},
    {"order_id": 115795, "symbol": "RJF", "action": "BUY",
     "quantity": 289, "order_type": "LMT", "status": "Submitted",
     "limit_price": 141.26, "oca_group": "ADOPT-OCA-RJF-950c1787-4d1ad8"},
    # Legitimate v19.34.103 bracket — must NOT be touched
    {"order_id": 115748, "symbol": "RJF", "action": "SELL",
     "quantity": 43, "order_type": "LMT", "status": "Submitted",
     "limit_price": 150.17, "oca_group": "oca_RJF_0486f940"},
    {"order_id": 115749, "symbol": "RJF", "action": "BUY",
     "quantity": 22, "order_type": "LMT", "status": "Submitted",
     "limit_price": 140.68, "oca_group": "oca_RJF_0486f940"},
    # A filled wrapper — must NOT be re-cancelled
    {"order_id": 115888, "symbol": "AAPL", "action": "BUY",
     "quantity": 50, "order_type": "STP", "status": "Filled",
     "aux_price": 195.00, "oca_group": "ADOPT-OCA-AAPL-deadbe"},
]


@pytest.fixture(autouse=True)
def snapshot_and_restore():
    """Snapshot + restore in-memory state around every test so we never
    leak fake orders or cancellations into the running backend's
    production view."""
    original_orders = list(ib_mod._pushed_ib_data.get("orders") or [])
    original_cancels = dict(ib_mod._cancellation_queue)
    yield
    ib_mod._pushed_ib_data["orders"] = original_orders
    ib_mod._cancellation_queue.clear()
    ib_mod._cancellation_queue.update(original_cancels)


def _seed(orders):
    ib_mod._pushed_ib_data["orders"] = list(orders)


# ─────────────────────────────────────────────────────────────────────
class TestCancelAdoptOcaStorm:

    def test_empty_snapshot_returns_zero(self):
        _seed([])
        out = cancel_adopt_oca_storm({"dry_run": True})
        assert out["success"] is True
        assert out["queued"] == 0
        assert out["targets"] == []
        assert out["oca_groups_touched"] == []

    def test_dry_run_lists_targets_but_does_not_queue(self):
        _seed(_LIVE_STORM)
        out = cancel_adopt_oca_storm({"dry_run": True})
        assert out["dry_run"] is True
        assert out["queued"] == 0
        # 4 pending ADOPT-OCA, excluding 2 legit + 1 Filled
        assert len(out["targets"]) == 4
        target_ids = {t["ib_order_id"] for t in out["targets"]}
        assert target_ids == {115150, 115509, 115765, 115795}
        assert 115748 not in target_ids and 115749 not in target_ids
        assert 115888 not in target_ids
        # Nothing leaked into the cancel queue.
        for tid in target_ids:
            assert tid not in ib_mod._cancellation_queue

    def test_live_flush_queues_all_adopt_oca_pending(self):
        _seed(_LIVE_STORM)
        out = cancel_adopt_oca_storm({"reason": "test_v107b"})
        assert out["queued"] == 4
        assert len(out["targets"]) == 4
        assert set(out["oca_groups_touched"]) == {
            "ADOPT-OCA-MTB-c0b9db64-a5df6d",
            "ADOPT-OCA-RJF-950c1787-4d1ad8",
        }
        for tid in {115150, 115509, 115765, 115795}:
            entry = ib_mod._cancellation_queue.get(tid)
            assert entry is not None and entry["status"] == "pending"
            assert entry["reason"] == "test_v107b"
        assert 115748 not in ib_mod._cancellation_queue
        assert 115749 not in ib_mod._cancellation_queue

    def test_symbol_filter_limits_to_one_ticker(self):
        _seed(_LIVE_STORM)
        out = cancel_adopt_oca_storm({"symbol": "rjf", "dry_run": True})
        ids = {t["ib_order_id"] for t in out["targets"]}
        assert ids == {115765, 115795}
        assert out["symbol_filter"] == "RJF"

    def test_in_flight_cancels_are_not_re_queued(self):
        _seed(_LIVE_STORM)
        ib_mod.queue_cancellation(
            ib_order_id=115150, reason="earlier_flush",
            requested_by="test",
        )
        out = cancel_adopt_oca_storm({})
        target_ids = {t["ib_order_id"] for t in out["targets"]}
        assert 115150 not in target_ids
        assert target_ids == {115509, 115765, 115795}
        assert out["queued"] == 3

    def test_response_has_summary_string(self):
        _seed(_LIVE_STORM[:2])
        out = cancel_adopt_oca_storm({"dry_run": True})
        assert "2 ADOPT-OCA order" in out["summary"]
        assert "1 OCA group" in out["summary"]
        assert "Would cancel" in out["summary"]

    def test_only_pending_statuses_targeted(self):
        _seed([
            {"order_id": 1, "symbol": "X", "status": "Cancelled",
             "order_type": "STP", "oca_group": "ADOPT-OCA-X-1"},
            {"order_id": 2, "symbol": "X", "status": "Inactive",
             "order_type": "LMT", "oca_group": "ADOPT-OCA-X-1"},
            {"order_id": 3, "symbol": "X", "status": "PendingSubmit",
             "order_type": "STP", "oca_group": "ADOPT-OCA-X-2"},
        ])
        out = cancel_adopt_oca_storm({"dry_run": True})
        assert {t["ib_order_id"] for t in out["targets"]} == {3}

    def test_none_payload_uses_defaults(self):
        """Endpoint must tolerate Body(default=None) — operator can
        POST with no body for a 'flush everything' shortcut."""
        _seed(_LIVE_STORM[:2])
        out = cancel_adopt_oca_storm(None)
        assert out["success"] is True
        assert out["dry_run"] is False
        assert out["queued"] == 2
