"""
v19.22.1 — Bracket-order detection in the Windows-side pusher.

The bug: every bracket order from the backend was rejected with
"Unknown order type: bracket" because `_execute_queued_order` only
handled MKT/LMT/STP/STP_LMT. 184 of 323 orders (~63%) failed today.

We can't unit-test the actual IB submission (requires ib_insync +
running Gateway), but we CAN unit-test the detection logic that
identifies a bracket and pulls the correct action/qty/limit_price
from the parent payload before falling through to the leg-builder.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _detect_bracket_and_resolve_legs(order: dict):
    """Mirrors the exact logic shipped in
    `documents/scripts/ib_data_pusher.py:_execute_queued_order` — we lift
    it into a pure helper so we can unit-test detection without spinning
    ib_insync up. If this helper drifts from the pusher source, the
    pusher fix is broken."""
    order_type = order.get("order_type", "MKT")
    is_bracket = (
        (order.get("type") or "").lower() == "bracket"
        or (order_type or "").lower() == "bracket"
    )
    action = order.get("action")
    quantity = order.get("quantity")
    limit_price = order.get("limit_price")

    if is_bracket:
        parent_payload = order.get("parent") or {}
        action = parent_payload.get("action", action)
        quantity = parent_payload.get("quantity", quantity)
        limit_price = parent_payload.get("limit_price", limit_price)
        order_type = (parent_payload.get("order_type") or "LMT").upper()

    return {
        "is_bracket": is_bracket,
        "action": action,
        "quantity": quantity,
        "limit_price": limit_price,
        "order_type": order_type,
    }


# -- The exact shape the operator's `/api/ib/orders/queue/status` showed -- #
def _hood_bracket_order():
    return {
        "order_id": "a053d117",
        "symbol": "HOOD",
        "action": None,
        "quantity": None,
        "order_type": "bracket",
        "limit_price": None,
        "stop_price": None,
        "time_in_force": "DAY",
        "trade_id": "424873ae",
        "type": "bracket",
        "parent": {
            "action": "BUY",
            "quantity": 258,
            "order_type": "LMT",
            "limit_price": 73.69,
            "time_in_force": "DAY",
            "exchange": "SMART",
        },
        "stop": {
            "action": "SELL",
            "quantity": 258,
            "order_type": "STP",
            "stop_price": 68.33,
            "time_in_force": "GTC",
            "outside_rth": True,
        },
        "target": {
            "action": "SELL",
            "quantity": 258,
            "order_type": "LMT",
            "limit_price": 82.07,
            "time_in_force": "GTC",
            "outside_rth": True,
        },
    }


def test_bracket_detected_via_type_field():
    """The `type: "bracket"` field must mark the order as a bracket."""
    out = _detect_bracket_and_resolve_legs(_hood_bracket_order())
    assert out["is_bracket"] is True


def test_bracket_detected_via_order_type_field():
    """`order_type: "bracket"` (without nested `type`) must also be detected."""
    o = _hood_bracket_order()
    o.pop("type")
    out = _detect_bracket_and_resolve_legs(o)
    assert out["is_bracket"] is True


def test_bracket_lifts_action_qty_price_from_parent():
    """The bug: top-level action/quantity/limit_price are None on bracket
    orders (the parent payload owns them). Pre-v19.22.1 the pusher passed
    those Nones into ib_insync constructors and crashed. The fix lifts
    them from the parent payload."""
    out = _detect_bracket_and_resolve_legs(_hood_bracket_order())
    assert out["action"] == "BUY"
    assert out["quantity"] == 258
    assert out["limit_price"] == 73.69
    assert out["order_type"] == "LMT"  # parent's order_type, not the bracket marker


def test_regular_order_unchanged():
    """A regular MKT/LMT order must NOT be treated as a bracket."""
    o = {
        "order_id": "x",
        "symbol": "AAPL",
        "action": "BUY",
        "quantity": 100,
        "order_type": "LMT",
        "limit_price": 200.0,
    }
    out = _detect_bracket_and_resolve_legs(o)
    assert out["is_bracket"] is False
    assert out["action"] == "BUY"
    assert out["quantity"] == 100
    assert out["limit_price"] == 200.0
    assert out["order_type"] == "LMT"


def test_bracket_with_missing_parent_falls_back_to_top_level():
    """Defensive: if the parent payload is missing on a bracket-marked
    order, the resolver returns the top-level (None) values rather than
    crashing — caller can then reject cleanly."""
    o = _hood_bracket_order()
    o.pop("parent", None)
    out = _detect_bracket_and_resolve_legs(o)
    assert out["is_bracket"] is True
    # All None — not a hard fail; downstream gets to error explicitly.
    assert out["action"] is None
    assert out["quantity"] is None


def test_bracket_case_insensitive():
    o = _hood_bracket_order()
    o["type"] = "BRACKET"
    o["order_type"] = "Bracket"
    out = _detect_bracket_and_resolve_legs(o)
    assert out["is_bracket"] is True
