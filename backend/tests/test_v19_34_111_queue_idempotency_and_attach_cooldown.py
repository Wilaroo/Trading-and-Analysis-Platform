"""
Tests for v19.34.111 — Reconciler re-queue bounce fix.

Two layered guards close the duplicate-order generation gap that
forced v109 to patch the symptom (the pusher's "Duplicate submission
blocked" bounce loop). Pre-v111 root cause:

  • `order_queue_service.queue_order()` generated a fresh uuid `order_id`
    on every call, with no idempotency check on `trade_id`. The
    reconciler's 30s share-drift loop happily queued a second / third
    STP+LMT pair under `trade_id="ADOPT-STOP-<trade.id>"` while the
    pusher was still working the first one — each got a different
    `order_id` so Spark's queue never noticed it was a duplicate
    intent.

  • Even with queue-level dedup, an aggressive caller could melt the
    queue by hammering it inside a single second; the reconciler
    needed its own cooldown so duplicate intents don't even reach
    the queue layer.

v111 ships both guards:

  1. **Queue-level `trade_id` idempotency** (order_queue_service.py).
     If a row with `trade_id` is in any in-flight state — PENDING,
     CLAIMED, IB_PENDING, EXECUTING — return its `order_id`. Caller
     sees the same order they would have submitted; the pusher
     keeps working the original. Terminal states (filled/rejected/
     cancelled/expired/partial/timeout) DO NOT block — yesterday's
     stop must be re-quotable today.

  2. **Reconciler bracket-attach cooldown** (position_reconciler.py).
     Per-`trade.id` monotonic timestamp of the last attach attempt.
     If a subsequent call lands inside `BRACKET_ATTACH_COOLDOWN_S`
     (default 60s, env-overridable), the reconciler skips and stamps
     a cooldown skip diagnostic.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Guard 1 — Queue-level `trade_id` idempotency
# ---------------------------------------------------------------------------

def _make_mocked_service(in_flight_doc=None):
    """Build an `OrderQueueService` whose Mongo collection is a MagicMock
    that returns `in_flight_doc` on find_one (or None to indicate no
    duplicate)."""
    from services.order_queue_service import OrderQueueService

    svc = OrderQueueService()
    svc._initialized = True
    svc._collection = MagicMock()
    svc._collection.find_one = MagicMock(return_value=in_flight_doc)
    svc._collection.insert_one = MagicMock(return_value=MagicMock(inserted_id="x"))
    # Bypass kill-switch
    svc._maybe_refuse_for_kill_switch = MagicMock(return_value=None)
    return svc


class TestQueueLevelTradeIdIdempotency:
    """`queue_order()` MUST return the existing order_id when a row with
    the same `trade_id` is already in-flight."""

    def test_returns_existing_order_id_when_trade_id_already_pending(self):
        existing = {"order_id": "abc12345", "status": "pending", "queued_at": "2026-02-12T10:00:00Z"}
        svc = _make_mocked_service(in_flight_doc=existing)
        oid = svc.queue_order({
            "symbol": "SBUX", "action": "SELL", "quantity": 100,
            "order_type": "STP", "stop_price": 95.0,
            "trade_id": "ADOPT-STOP-TR123",
        })
        assert oid == "abc12345", (
            "queue_order MUST return the existing pending order_id when "
            "the same trade_id is already in-flight — otherwise the "
            "v109 bounce-loop respawn comes back."
        )
        # CRITICAL: must NOT insert a duplicate row.
        svc._collection.insert_one.assert_not_called()

    def test_returns_existing_order_id_when_trade_id_ib_pending(self):
        """IB_PENDING (v109) is also in-flight. Re-issuing during this
        window is exactly the bounce-loop fingerprint."""
        existing = {"order_id": "ib999999", "status": "ib_pending", "queued_at": "..."}
        svc = _make_mocked_service(in_flight_doc=existing)
        oid = svc.queue_order({
            "symbol": "TSLA", "action": "BUY", "quantity": 50,
            "order_type": "STP", "stop_price": 200.0,
            "trade_id": "ADOPT-STOP-TR777",
        })
        assert oid == "ib999999"
        svc._collection.insert_one.assert_not_called()

    def test_returns_existing_when_claimed_or_executing(self):
        for status in ("claimed", "executing"):
            existing = {"order_id": f"oid-{status}", "status": status}
            svc = _make_mocked_service(in_flight_doc=existing)
            oid = svc.queue_order({
                "symbol": "AAPL", "action": "SELL", "quantity": 10,
                "order_type": "STP", "stop_price": 150.0,
                "trade_id": "ADOPT-STOP-TR-CL",
            })
            assert oid == f"oid-{status}", (
                f"{status} is in-flight — queue_order must dedup, not insert."
            )
            svc._collection.insert_one.assert_not_called()

    def test_inserts_new_row_when_no_duplicate(self):
        """Falsy `find_one` = no in-flight duplicate → normal insert."""
        svc = _make_mocked_service(in_flight_doc=None)
        oid = svc.queue_order({
            "symbol": "GOOG", "action": "BUY", "quantity": 5,
            "order_type": "LMT", "limit_price": 140.0,
            "trade_id": "FIRST-TIME-INTENT",
        })
        assert oid != ""
        assert len(oid) >= 6  # uuid4 short form
        svc._collection.insert_one.assert_called_once()

    def test_inserts_new_row_when_trade_id_missing(self):
        """Legacy callers with no `trade_id` (e.g. one-off ops) MUST
        keep working — the guard only applies when a trade_id is set."""
        svc = _make_mocked_service(in_flight_doc=None)
        oid = svc.queue_order({
            "symbol": "MSFT", "action": "SELL", "quantity": 20,
            "order_type": "MKT",
        })
        assert oid
        # find_one should not have been called at all for anonymous orders
        # (the guard is keyed on trade_id presence).
        svc._collection.find_one.assert_not_called()
        svc._collection.insert_one.assert_called_once()

    def test_empty_string_trade_id_treated_as_missing(self):
        svc = _make_mocked_service(in_flight_doc=None)
        oid = svc.queue_order({
            "symbol": "NVDA", "action": "BUY", "quantity": 1,
            "order_type": "MKT",
            "trade_id": "   ",  # whitespace
        })
        assert oid
        svc._collection.find_one.assert_not_called()
        svc._collection.insert_one.assert_called_once()

    def test_terminal_status_rows_do_not_block(self):
        """If yesterday's STP filled and today's reconciliation cycle
        attempts a fresh attach under the same trade_id, the new
        intent MUST go through. We assert by feeding the find_one mock
        a `None` return (Mongo would return None for the in-flight
        filter on a row that's already filled)."""
        # The actual production filter is
        #   {"status": {"$in": [pending, claimed, ib_pending, executing]}}
        # so a filled/cancelled row CANNOT match. Mock None reflects that.
        svc = _make_mocked_service(in_flight_doc=None)
        oid = svc.queue_order({
            "symbol": "AMD", "action": "SELL", "quantity": 100,
            "order_type": "STP", "stop_price": 150.0,
            "trade_id": "ADOPT-STOP-TR-YESTERDAY",
        })
        assert oid
        svc._collection.insert_one.assert_called_once()

    def test_find_one_filter_uses_in_flight_statuses(self):
        """The Mongo query filter MUST restrict to in-flight statuses."""
        from services.order_queue_service import OrderStatus

        svc = _make_mocked_service(in_flight_doc=None)
        svc.queue_order({
            "symbol": "F", "action": "BUY", "quantity": 100,
            "order_type": "MKT",
            "trade_id": "TR-CHECK-FILTER",
        })
        svc._collection.find_one.assert_called_once()
        filter_arg = svc._collection.find_one.call_args[0][0]
        assert filter_arg["trade_id"] == "TR-CHECK-FILTER"
        in_clause = filter_arg["status"]["$in"]
        assert OrderStatus.PENDING.value in in_clause
        assert OrderStatus.CLAIMED.value in in_clause
        assert OrderStatus.IB_PENDING.value in in_clause
        assert OrderStatus.EXECUTING.value in in_clause
        # Terminal states MUST NOT be in the filter
        assert OrderStatus.FILLED.value not in in_clause
        assert OrderStatus.REJECTED.value not in in_clause
        assert OrderStatus.CANCELLED.value not in in_clause

    def test_guard_failure_falls_through_to_insert(self):
        """If the Mongo idempotency probe raises (network blip, index
        race), the guard MUST swallow + fall through to the legacy
        insert path. Worst case = pre-v111 duplicate behaviour, which
        is still a recoverable state. Crashing the queue would not be."""
        from services.order_queue_service import OrderQueueService

        svc = OrderQueueService()
        svc._initialized = True
        svc._collection = MagicMock()
        svc._collection.find_one = MagicMock(side_effect=RuntimeError("network blip"))
        svc._collection.insert_one = MagicMock(return_value=MagicMock(inserted_id="x"))
        svc._maybe_refuse_for_kill_switch = MagicMock(return_value=None)

        oid = svc.queue_order({
            "symbol": "GME", "action": "BUY", "quantity": 1,
            "order_type": "MKT",
            "trade_id": "TR-WHEN-MONGO-BLIPS",
        })
        # Insert MUST still happen — we never want to silently drop an
        # order because the dedup probe failed.
        svc._collection.insert_one.assert_called_once()
        assert oid


# ---------------------------------------------------------------------------
# Guard 2 — Reconciler bracket-attach cooldown
# ---------------------------------------------------------------------------

class TestBracketAttachCooldown:
    """The reconciler caps attach-attempt frequency per `trade.id` to
    `BRACKET_ATTACH_COOLDOWN_S` (default 60s) so even a misconfigured
    caller can't flood the queue with redundant STP+LMT intents."""

    def setup_method(self):
        from services.position_reconciler import PositionReconciler
        self.r = PositionReconciler(db=MagicMock())

    def test_no_cooldown_on_first_attempt(self):
        """A trade we've never seen MUST not be in cooldown."""
        assert self.r._bracket_attach_in_cooldown("TR-NEW-001") is None

    def test_cooldown_active_immediately_after_stamp(self):
        self.r._stamp_bracket_attach("TR-RECENT-001")
        remaining = self.r._bracket_attach_in_cooldown("TR-RECENT-001")
        assert remaining is not None
        assert 0 < remaining <= self.r._BRACKET_ATTACH_COOLDOWN_S

    def test_cooldown_clears_after_window_expires(self):
        """Setting `last_bracket_attach_at` to a long-ago timestamp
        must release the cooldown. Tests the time arithmetic without
        needing to sleep."""
        import time
        # Pretend the last attach was 2× cooldown ago.
        self.r._last_bracket_attach_at["TR-OLD-001"] = (
            time.monotonic() - 2 * self.r._BRACKET_ATTACH_COOLDOWN_S
        )
        assert self.r._bracket_attach_in_cooldown("TR-OLD-001") is None

    def test_falsy_trade_id_never_blocked(self):
        """Empty / None trade ids bypass the guard for legacy paths."""
        assert self.r._bracket_attach_in_cooldown("") is None
        assert self.r._bracket_attach_in_cooldown(None) is None

    def test_stamp_falsy_trade_id_is_noop(self):
        """Stamping with no id must not pollute the map (would otherwise
        block ALL future falsy-id callers under the empty string key)."""
        self.r._stamp_bracket_attach("")
        self.r._stamp_bracket_attach(None)
        assert self.r._last_bracket_attach_at == {}

    def test_independent_cooldowns_per_trade_id(self):
        """Attaching trade A must not interfere with attaching trade B."""
        self.r._stamp_bracket_attach("TR-A")
        assert self.r._bracket_attach_in_cooldown("TR-A") is not None
        assert self.r._bracket_attach_in_cooldown("TR-B") is None

    def test_cooldown_seconds_env_override(self, monkeypatch):
        from services.position_reconciler import PositionReconciler

        monkeypatch.setenv("BRACKET_ATTACH_COOLDOWN_S", "12.5")
        r = PositionReconciler(db=MagicMock())
        assert r._BRACKET_ATTACH_COOLDOWN_S == 12.5

    def test_cooldown_default_when_env_invalid(self, monkeypatch):
        from services.position_reconciler import PositionReconciler

        monkeypatch.setenv("BRACKET_ATTACH_COOLDOWN_S", "not-a-number")
        r = PositionReconciler(db=MagicMock())
        # Falls back to the default sentinel — invalid env must NOT
        # crash construction.
        assert r._BRACKET_ATTACH_COOLDOWN_S == 60.0

    def test_skip_counter_increments_on_documented_blocks(self):
        """Diagnostic counter used by the operator-visible status pill.
        Manually walk the cooldown-detect → skip pattern that the
        production call sites use."""
        self.r._stamp_bracket_attach("TR-COUNT-001")
        baseline = self.r._bracket_attach_cooldown_skips
        # Simulate three attach attempts hitting cooldown.
        for _ in range(3):
            if self.r._bracket_attach_in_cooldown("TR-COUNT-001") is not None:
                self.r._bracket_attach_cooldown_skips += 1
        assert self.r._bracket_attach_cooldown_skips == baseline + 3


class TestCooldownCallsiteWiring:
    """Source-level assertions that the three production attach sites
    all wrap their `attach_oca_stop_target(...)` in the cooldown
    guard. Without this, the queue-level idempotency is the only
    defense and an aggressive caller can still burn Mongo writes."""

    @pytest.fixture
    def reconciler_src(self):
        return (BACKEND_DIR / "services" / "position_reconciler.py").read_text()

    def test_reconcile_orphan_positions_path_wraps_attach(self, reconciler_src):
        """The big orphan-adoption branch in `reconcile_orphan_positions`
        is the most frequent re-queue source (boot retry + manual
        RECONCILE button + share-drift fallback). Must check cooldown."""
        idx = reconciler_src.find("[RECONCILE BRACKET]")
        assert idx >= 0, "Could not find reconcile-orphan attach site"
        # Search backwards for the cooldown guard
        window = reconciler_src[max(0, idx - 3000):idx]
        assert "_bracket_attach_in_cooldown(trade.id)" in window, (
            "reconcile_orphan_positions attach site is NOT wrapped in "
            "v19.34.111 cooldown guard — duplicate STP+LMT under same "
            "trade_id can leak through on every 30s share-drift tick."
        )

    def test_grow_existing_excess_slice_wraps_attach(self, reconciler_src):
        """The grow-slice path reissues OCA on every share-count change.
        Without cooldown a noisy drift signal floods the queue."""
        idx = reconciler_src.find("[v19.34.42 grow NAKED]")
        assert idx >= 0
        window = reconciler_src[max(0, idx - 2000):idx]
        assert "_bracket_attach_in_cooldown(trade.id)" in window, (
            "_grow_existing_excess_slice attach site missing cooldown "
            "guard — every drift-recheck would respawn intents."
        )

    def test_spawn_excess_slice_wraps_attach(self, reconciler_src):
        """The new-slice path (v19.34.15b) attaches OCA immediately on
        adoption. Must also cooldown so a flickering drift signal
        doesn't queue 5 STPs in 10 seconds."""
        idx = reconciler_src.find("[v19.34.28 PARTIAL-OCA]")
        assert idx >= 0
        window = reconciler_src[max(0, idx - 3000):idx]
        assert "_bracket_attach_in_cooldown(trade.id)" in window, (
            "_spawn_excess_slice attach site missing cooldown guard."
        )

    def test_stamp_bracket_attach_called_before_attempt(self, reconciler_src):
        """Every cooldown-guarded site MUST stamp the attempt BEFORE
        invoking the executor — otherwise the cooldown only kicks in
        after success, defeating the throttle."""
        # All three sites should have _stamp_bracket_attach(trade.id)
        # immediately before the await call.
        stamp_count = reconciler_src.count("self._stamp_bracket_attach(trade.id)")
        assert stamp_count >= 3, (
            f"Expected ≥3 _stamp_bracket_attach call sites (one per "
            f"attach branch); found {stamp_count}. Cooldown is leaky "
            f"if a path skips the stamp."
        )


# ---------------------------------------------------------------------------
# Integration — queue-level guard observed end-to-end
# ---------------------------------------------------------------------------

class TestEndToEndIdempotencyContract:
    """Smoke-test that documents the production contract: two callers
    queue the *same* trade_id back-to-back, only one Mongo row gets
    inserted, both receive the same order_id."""

    def test_two_callers_same_trade_id_share_order_id(self):
        # First call inserts; second call sees in-flight row.
        from services.order_queue_service import OrderQueueService

        svc = OrderQueueService()
        svc._initialized = True
        svc._collection = MagicMock()
        svc._maybe_refuse_for_kill_switch = MagicMock(return_value=None)

        # First call: no row exists → insert.
        svc._collection.find_one = MagicMock(return_value=None)
        svc._collection.insert_one = MagicMock(return_value=MagicMock(inserted_id="x"))
        oid_1 = svc.queue_order({
            "symbol": "SBUX", "action": "SELL", "quantity": 50,
            "order_type": "STP", "stop_price": 100.0,
            "trade_id": "ADOPT-STOP-RACE",
        })
        assert oid_1
        assert svc._collection.insert_one.call_count == 1

        # Second call: the first row is now in-flight → dedup, return existing id.
        existing = {"order_id": oid_1, "status": "pending"}
        svc._collection.find_one = MagicMock(return_value=existing)
        oid_2 = svc.queue_order({
            "symbol": "SBUX", "action": "SELL", "quantity": 50,
            "order_type": "STP", "stop_price": 100.0,
            "trade_id": "ADOPT-STOP-RACE",
        })
        assert oid_2 == oid_1, (
            "Second concurrent caller with the same trade_id MUST see "
            "the first order's id back — that's the contract that kills "
            "the v109 bounce loop at the root."
        )
        # Insert count is still 1 — second call did NOT add a row.
        assert svc._collection.insert_one.call_count == 1
