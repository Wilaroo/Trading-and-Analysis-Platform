"""
v19.34.48 — Kill-switch gate regression
==========================================

Pins the bottom-line defense in `routers.ib.queue_order` that REFUSES
entry orders when `safety_guardrails.kill_switch_active` is True.

Operator-discovered 2026-05-07: bot bought 1,454 sh EBAY + submitted
a fresh OCA bracket while kill switch was tripped. Some entry path
bypassed the high-level guards and reached `queue_order` directly.

Asserts:
  1. With kill switch ACTIVE, queue_order REFUSES bare entry orders
     (no trade_id prefix → treated as entry).
  2. Refused order has status="rejected" and is queryable via
     `get_order_result` immediately (no wait timeout).
  3. With kill switch ACTIVE, queue_order ALLOWS protective orders:
     STOP-, ADOPT-STOP-, ADOPT-TGT-, TARGET-, OCA-, TGT- prefixes.
  4. With kill switch ACTIVE, queue_order ALLOWS close orders:
     CLOSE-, PARTIAL- prefixes.
  5. With kill switch ACTIVE, queue_order ALLOWS orders with explicit
     `intent: "close"|"protective"|"stop"|"target"|"cancel"` field.
  6. With kill switch INACTIVE, queue_order passes everything through
     (gate is a no-op).
  7. If safety_guardrails import fails (defensive fallback), gate is
     a no-op (don't block legitimate closes during outage).
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/app/backend")


def _mk_guard(active: bool, reason: str = "operator_test"):
    state = SimpleNamespace(
        kill_switch_active=active,
        kill_switch_reason=reason,
        kill_switch_tripped_at="2026-05-07T18:00:00+00:00",
    )
    return SimpleNamespace(state=state)


def _mock_queue_service():
    """Return a fake order_queue_service that accepts inserts."""
    svc = MagicMock()
    svc._completed = {}
    # get_order looks up by id in our simulated completed map.
    svc.get_order = MagicMock(side_effect=lambda oid: svc._completed.get(oid))
    return svc


def test_gate_refuses_bare_entry_when_kill_switch_active():
    from routers.ib import queue_order, get_order_result

    fake_guard = _mk_guard(active=True, reason="operator_close_cancel_all")
    svc = _mock_queue_service()

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True), \
         patch("routers.ib.get_order_queue_service", return_value=svc):
        # Bare entry — no trade_id prefix.
        order_id = queue_order({
            "symbol": "EBAY", "action": "BUY", "quantity": 14,
            "trade_id": "abc-123-uuid",   # bare uuid, no prefix
            "order_type": "MKT",
        })
        # Refused id pattern.
        assert order_id.startswith("ks-refused-"), (
            f"expected refusal id, got {order_id}"
        )
        # Result is immediately available with status=rejected.
        result = get_order_result(order_id, timeout=2.0)
        assert result is not None
        assert result["status"] == "rejected"
        assert "kill_switch_active" in result["result"]["error"]


def test_gate_allows_close_orders_when_kill_switch_active():
    """CLOSE-, PARTIAL- prefixes must be allowed so flatten still works."""
    from routers.ib import queue_order

    fake_guard = _mk_guard(active=True)
    svc = _mock_queue_service()
    svc.queue_order = MagicMock(return_value="real-order-id-1")

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True), \
         patch("routers.ib.get_order_queue_service", return_value=svc):
        for tid in ("CLOSE-x", "PARTIAL-y"):
            order_id = queue_order({
                "symbol": "BMNR", "action": "SELL", "quantity": 100,
                "trade_id": tid, "order_type": "MKT",
            })
            assert not order_id.startswith("ks-refused-"), (
                f"close prefix {tid} should NOT be refused"
            )


def test_gate_allows_protective_orders_when_kill_switch_active():
    """STOP-, ADOPT-, TARGET-, OCA-, TGT- prefixes must be allowed."""
    from routers.ib import queue_order

    fake_guard = _mk_guard(active=True)
    svc = _mock_queue_service()
    svc.queue_order = MagicMock(return_value="real-order-id-2")

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True), \
         patch("routers.ib.get_order_queue_service", return_value=svc):
        for tid in ("STOP-x", "ADOPT-STOP-x", "ADOPT-TGT-x",
                    "TARGET-x", "OCA-x", "TGT-x"):
            order_id = queue_order({
                "symbol": "BMNR", "action": "SELL", "quantity": 100,
                "trade_id": tid, "order_type": "STP", "stop_price": 20,
            })
            assert not order_id.startswith("ks-refused-"), (
                f"protective prefix {tid} should NOT be refused"
            )


def test_gate_allows_explicit_intent_close_when_kill_switch_active():
    from routers.ib import queue_order

    fake_guard = _mk_guard(active=True)
    svc = _mock_queue_service()
    svc.queue_order = MagicMock(return_value="real-order-id-3")

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True), \
         patch("routers.ib.get_order_queue_service", return_value=svc):
        for intent in ("close", "protective", "stop", "target", "cancel"):
            order_id = queue_order({
                "symbol": "BMNR", "action": "SELL", "quantity": 100,
                "trade_id": "anything-bare",
                "intent": intent,
                "order_type": "MKT",
            })
            assert not order_id.startswith("ks-refused-"), (
                f"explicit intent={intent} should NOT be refused"
            )


def test_gate_passes_through_when_kill_switch_inactive():
    from routers.ib import queue_order

    fake_guard = _mk_guard(active=False)
    svc = _mock_queue_service()
    svc.queue_order = MagicMock(return_value="real-order-id-4")

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True), \
         patch("routers.ib.get_order_queue_service", return_value=svc):
        order_id = queue_order({
            "symbol": "EBAY", "action": "BUY", "quantity": 14,
            "trade_id": "bare-entry",
            "order_type": "MKT",
        })
        assert not order_id.startswith("ks-refused-")
        # Real queue path was called.
        svc.queue_order.assert_called_once()


def test_gate_fails_open_when_safety_guardrails_unavailable():
    """If guardrails import / lookup fails, gate must NOT block orders.
    Defense in depth — the high-level guards are still in play.
    """
    from routers.ib import queue_order

    svc = _mock_queue_service()
    svc.queue_order = MagicMock(return_value="real-order-id-5")

    with patch("services.safety_guardrails.get_safety_guardrails",
               side_effect=RuntimeError("simulated outage"), create=True), \
         patch("routers.ib.get_order_queue_service", return_value=svc):
        order_id = queue_order({
            "symbol": "EBAY", "action": "BUY", "quantity": 14,
            "trade_id": "bare-entry",
            "order_type": "MKT",
        })
        # Falls through to normal queue path.
        assert not order_id.startswith("ks-refused-")
