"""
test_ib_orders_endpoint_v19_34_6.py — pin the new GET /api/ib/orders
visibility endpoint (v19.34.6, 2026-05-05).

Operator request from handoff: "Create `GET /api/ib/orders` endpoint
for visibility (needed for boot sweep + audit cross-check + UI debug
panel)."

Architecture: DGX has no direct IB connection in this deployment, so
we read from the canonical Mongo `order_queue` collection — the
source of truth for everything Spark told the pusher to do. Returns
the orders the bot has submitted with rich state, filterable.

All tests use mocked Mongo cursors — no real DB / IB / pusher.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _make_order(**overrides):
    base = {
        "order_id": "ord-abc-123",
        "symbol": "HOOD",
        "action": "BUY",
        "quantity": 100,
        "order_type": "MKT",
        "time_in_force": "DAY",
        "status": "filled",
        "queued_at": "2026-05-05T13:30:01+00:00",
        "claimed_at": "2026-05-05T13:30:01.500+00:00",
        "executed_at": "2026-05-05T13:30:02+00:00",
        "fill_price": 73.42,
        "filled_qty": 100,
        "ib_order_id": 9001,
        "trade_id": "trade-xyz",
        "attempts": 1,
    }
    base.update(overrides)
    return base


def _patch_queue_service_with(rows, captured_query=None):
    """Returns a context manager that patches `get_order_queue_service`
    to return a fake service whose `_collection.find()` returns the
    given rows. `captured_query` is a dict — when passed, the chosen
    Mongo query is written into it as `captured_query["q"]`."""
    fake_collection = MagicMock()

    def _find(q, projection=None):
        if captured_query is not None:
            captured_query["q"] = q
            captured_query["projection"] = projection
        cursor = MagicMock()
        cursor.sort.return_value = cursor

        def _limit(n):
            captured_query and captured_query.update({"limit": n})
            return rows[:n]
        cursor.limit = _limit
        return cursor

    fake_collection.find = _find

    fake_service = MagicMock()
    fake_service._initialized = True
    fake_service._collection = fake_collection
    fake_service.initialize = MagicMock()

    return patch("routers.ib.get_order_queue_service", return_value=fake_service)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

class TestIbOrdersEndpointV19_34_6:

    def test_returns_recent_orders_no_filter(self):
        from routers.ib import get_ib_orders
        rows = [
            _make_order(order_id="o1", status="filled", symbol="HOOD"),
            _make_order(order_id="o2", status="pending", symbol="MELI"),
            _make_order(order_id="o3", status="rejected", symbol="STX"),
        ]
        with _patch_queue_service_with(rows):
            resp = get_ib_orders()

        assert resp["success"] is True
        assert resp["count"] == 3
        assert resp["source"] == "mongo_order_queue"
        assert resp["summary"] == {"filled": 1, "pending": 1, "rejected": 1}
        ids = [o["order_id"] for o in resp["orders"]]
        assert ids == ["o1", "o2", "o3"]

    def test_status_single_filter(self):
        from routers.ib import get_ib_orders
        rows = [_make_order(status="pending", order_id="p1")]
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            resp = get_ib_orders(status="pending")

        assert resp["success"] is True
        assert captured["q"]["status"] == "pending"
        assert resp["filters_applied"]["status"] == "pending"

    def test_status_csv_filter_uses_mongo_in_query(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(status="pending,claimed,executing")

        assert captured["q"]["status"] == {"$in": ["pending", "claimed", "executing"]}

    def test_open_only_shorthand(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(open_only=True)

        # open_only must produce the canonical 3-status $in query
        assert captured["q"]["status"] == {"$in": ["pending", "claimed", "executing"]}

    def test_symbol_filter_is_uppercased(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(symbol="hood")

        assert captured["q"]["symbol"] == "HOOD"

    def test_order_type_filter(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(order_type="bracket")

        assert captured["q"]["order_type"] == "bracket"

    def test_since_filter_passes_through(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        since_ts = "2026-05-05T13:30:00"
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(since=since_ts)

        assert captured["q"]["queued_at"] == {"$gte": since_ts}

    def test_limit_cap_at_500(self):
        from routers.ib import get_ib_orders
        rows = [_make_order(order_id=f"o{i}") for i in range(10)]
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(limit=99999)
        assert captured["limit"] == 500

    def test_limit_min_at_1(self):
        from routers.ib import get_ib_orders
        rows = [_make_order(order_id="o1")]
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(limit=0)
        assert captured["limit"] == 1

    def test_open_only_overrides_status_param(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            # If both passed, open_only should win to avoid ambiguity
            get_ib_orders(status="filled", open_only=True)

        assert captured["q"]["status"] == {"$in": ["pending", "claimed", "executing"]}

    def test_combined_filters_all_applied(self):
        from routers.ib import get_ib_orders
        rows = []
        captured = {}
        with _patch_queue_service_with(rows, captured_query=captured):
            get_ib_orders(
                status="pending",
                symbol="hood",
                order_type="bracket",
                since="2026-05-05T13:30:00",
                limit=25,
            )

        assert captured["q"] == {
            "status": "pending",
            "symbol": "HOOD",
            "order_type": "bracket",
            "queued_at": {"$gte": "2026-05-05T13:30:00"},
        }
        assert captured["limit"] == 25

    def test_summary_aggregates_status_counts_correctly(self):
        from routers.ib import get_ib_orders
        rows = [
            _make_order(status="pending", order_id="p1"),
            _make_order(status="pending", order_id="p2"),
            _make_order(status="filled", order_id="f1"),
            _make_order(status="filled", order_id="f2"),
            _make_order(status="filled", order_id="f3"),
            _make_order(status="rejected", order_id="r1"),
        ]
        with _patch_queue_service_with(rows):
            resp = get_ib_orders()

        assert resp["summary"] == {"pending": 2, "filled": 3, "rejected": 1}
        assert resp["count"] == 6

    def test_empty_result_returns_clean_payload(self):
        from routers.ib import get_ib_orders
        with _patch_queue_service_with([]):
            resp = get_ib_orders()

        assert resp["success"] is True
        assert resp["count"] == 0
        assert resp["orders"] == []
        assert resp["summary"] == {}

    def test_mongo_failure_returns_safe_error(self):
        """Defensive: a Mongo cursor exception MUST NOT 500 the route —
        return success:false with the error payload."""
        from routers.ib import get_ib_orders

        broken_service = MagicMock()
        broken_service._initialized = True
        broken_service._collection.find.side_effect = RuntimeError("mongo down")

        with patch("routers.ib.get_order_queue_service", return_value=broken_service):
            resp = get_ib_orders()

        assert resp["success"] is False
        assert "mongo down" in resp["error"]
        assert resp["count"] == 0
        assert resp["orders"] == []

    def test_response_excludes_mongo_object_id(self):
        """Defensive contract: never leak `_id` into the response."""
        from routers.ib import get_ib_orders

        captured = {}
        with _patch_queue_service_with([_make_order()], captured_query=captured):
            get_ib_orders()

        assert captured["projection"] == {"_id": 0}

    def test_unknown_status_groups_under_unknown_in_summary(self):
        """Rows with missing/null status should still be counted, not
        crash the summary aggregator."""
        from routers.ib import get_ib_orders
        rows = [
            _make_order(status=None, order_id="x1"),
            _make_order(order_id="x2"),  # default "filled"
        ]
        # Strip status from x2 to confirm `unknown` bucket
        rows[1].pop("status")

        with _patch_queue_service_with(rows):
            resp = get_ib_orders()

        # Both rows landed in unknown
        assert resp["summary"].get("unknown") == 2
        assert resp["count"] == 2
