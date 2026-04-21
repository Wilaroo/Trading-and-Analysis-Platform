"""Regression test for bracket-order field passthrough in the order queue.

Bug: prior to 2026-04-23, `OrderQueueService.queue_order()` used a hardcoded
whitelist that silently stripped the `type`, `parent`, `stop`, `target`, and
`oca_group` fields before inserting into MongoDB. The Windows pusher then
received a degenerate payload and could not execute atomic IB brackets.

These tests mock the MongoDB collection (so they run natively on DGX Spark
without touching the live DB) and verify:
  1. Bracket fields are preserved in the stored document.
  2. Regular flat orders are unaffected.
  3. The `QueuedOrder` Pydantic model accepts the bracket shape.
"""
from unittest.mock import MagicMock

from services.order_queue_service import OrderQueueService, QueuedOrder


def _mk_service() -> OrderQueueService:
    """Build a service with a fake MongoDB collection for isolation."""
    svc = OrderQueueService()
    svc._collection = MagicMock()
    # insert_one mimics pymongo behavior: mutates input dict with _id
    svc._collection.insert_one.side_effect = (
        lambda doc: doc.update({"_id": "fake_oid"}) or MagicMock(inserted_id="fake_oid")
    )
    svc._initialized = True
    return svc


def test_bracket_order_preserves_type_parent_stop_target():
    svc = _mk_service()

    payload = {
        "type": "bracket",
        "trade_id": "tid-123",
        "symbol": "USO",
        "parent": {
            "action": "SELL",
            "quantity": 1000,
            "order_type": "LMT",
            "limit_price": 108.28,
            "time_in_force": "DAY",
            "exchange": "SMART",
        },
        "stop": {
            "action": "BUY",
            "quantity": 1000,
            "order_type": "STP",
            "stop_price": 109.20,
            "time_in_force": "GTC",
            "outside_rth": True,
        },
        "target": {
            "action": "BUY",
            "quantity": 1000,
            "order_type": "LMT",
            "limit_price": 106.50,
            "time_in_force": "GTC",
            "outside_rth": True,
        },
    }

    order_id = svc.queue_order(payload)
    assert order_id, "queue_order should return a non-empty id"

    # Grab the doc that was actually inserted
    svc._collection.insert_one.assert_called_once()
    stored = svc._collection.insert_one.call_args[0][0]

    # Core identifiers
    assert stored["order_id"] == order_id
    assert stored["symbol"] == "USO"
    assert stored["trade_id"] == "tid-123"
    assert stored["status"] == "pending"

    # Bracket-specific fields must NOT be stripped
    assert stored["type"] == "bracket", "bracket type flag was dropped"
    assert stored["parent"] == payload["parent"], "parent leg was dropped"
    assert stored["stop"] == payload["stop"], "stop leg was dropped"
    assert stored["target"] == payload["target"], "target leg was dropped"

    # Parent fields must be reachable by the pusher
    assert stored["parent"]["limit_price"] == 108.28
    assert stored["stop"]["stop_price"] == 109.20
    assert stored["target"]["limit_price"] == 106.50

    # For bracket orders the top-level order_type is "bracket"
    assert stored["order_type"] == "bracket"


def test_bracket_with_oca_group_preserved():
    svc = _mk_service()
    payload = {
        "type": "bracket",
        "symbol": "AAPL",
        "oca_group": "OCA_AAPL_abc123",
        "parent": {"action": "BUY", "quantity": 10, "order_type": "LMT", "limit_price": 100.0},
        "stop": {"action": "SELL", "quantity": 10, "order_type": "STP", "stop_price": 98.0},
        "target": {"action": "SELL", "quantity": 10, "order_type": "LMT", "limit_price": 104.0},
    }
    svc.queue_order(payload)
    stored = svc._collection.insert_one.call_args[0][0]
    assert stored["oca_group"] == "OCA_AAPL_abc123"


def test_regular_order_unaffected():
    """Regression guard: flat MKT/LMT orders must still work as before."""
    svc = _mk_service()

    payload = {
        "symbol": "aapl",
        "action": "buy",
        "quantity": 50,
        "order_type": "LMT",
        "limit_price": 150.25,
        "time_in_force": "DAY",
        "trade_id": "tid-reg-1",
    }

    svc.queue_order(payload)
    stored = svc._collection.insert_one.call_args[0][0]

    assert stored["symbol"] == "AAPL", "symbol should be upper-cased"
    assert stored["action"] == "BUY", "action should be upper-cased"
    assert stored["quantity"] == 50
    assert stored["order_type"] == "LMT"
    assert stored["limit_price"] == 150.25
    # Must NOT carry bracket fields by accident
    assert "type" not in stored or stored.get("type") is None
    assert "parent" not in stored or stored.get("parent") is None


def test_pydantic_model_accepts_bracket_fields():
    """QueuedOrder must tolerate the bracket shape without stripping."""
    o = QueuedOrder(
        order_id="abc12345",
        symbol="USO",
        type="bracket",
        order_type="bracket",
        parent={"action": "SELL", "quantity": 100, "limit_price": 108.28},
        stop={"action": "BUY", "quantity": 100, "stop_price": 109.20},
        target={"action": "BUY", "quantity": 100, "limit_price": 106.50},
    )
    assert o.type == "bracket"
    assert o.parent["limit_price"] == 108.28
    assert o.stop["stop_price"] == 109.20
    assert o.target["limit_price"] == 106.50


def test_pydantic_model_accepts_extra_unknown_fields():
    """extra='allow' ensures future-compat with new pusher fields."""
    o = QueuedOrder(
        order_id="abc12345",
        symbol="AAPL",
        some_future_field="whatever",
    )
    # No AttributeError, no ValidationError
    assert o.order_id == "abc12345"
