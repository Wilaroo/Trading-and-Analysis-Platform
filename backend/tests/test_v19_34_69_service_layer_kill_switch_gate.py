"""
v19.34.69 — BMNR P-1 kill-switch bypass regression
====================================================

Background
----------
2026-05-11 14:14:34 UTC, operator manually tripped the kill switch
(`safety_guardrails.state.kill_switch_active = True`, persisted to
mongo). At ~14:1X UTC the bot still opened a position in BMNR. The
operator confirmed the fill in TWS/IB — this was a real fill on a
real entry order, not a phantom UI artifact.

Root-cause audit found the leak: `agents/trade_executor_agent.py::
_execute_order` imports the service directly via
`get_order_queue_service()` and calls `.queue_order(...)` on it. That
path bypassed the `routers/ib._kill_switch_gate` chokepoint, which was
the ONLY kill-switch defense at the queue layer prior to v19.34.69.

Fix
---
Push the gate down one level: into `OrderQueueService.queue_order()`
itself, via `services.kill_switch_gate.evaluate_kill_switch_gate`.
Now EVERY caller — including the agent, the bracket reissue service,
the position reconciler, and any future producer — is gated at the
absolute lowest layer before the pusher sees the row.

Assertions
----------
1. With kill switch ACTIVE, an entry order submitted through the
   `agents/trade_executor_agent.py::_execute_order` code path
   (direct `service.queue_order(...)` call, no router wrapper)
   is REFUSED at the service layer (returns `ks-refused-*`, no
   row written to the actual pending queue).
2. With kill switch ACTIVE, a protective order (oca_group set, stop
   order_type) submitted through the same direct service path is
   still ALLOWED through (so flatten / re-bracket flows keep working).
3. With kill switch INACTIVE, the service-layer gate is a no-op.
4. The refusal row is persisted with `status=rejected` so
   `service.get_order(refused_id)` returns it immediately (no 30s
   timeout wait at the agent).
5. The shared helper `evaluate_kill_switch_gate` matches the
   intent-detection contract of `routers/ib._kill_switch_gate`
   (so both layers reject/allow the same set of payloads).
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/app/backend")


def _mk_guard(active: bool, reason: str = "bmnr_test"):
    state = SimpleNamespace(
        kill_switch_active=active,
        kill_switch_reason=reason,
        kill_switch_tripped_at=1778508874.121693,  # 2026-05-11 14:14:34Z
    )
    return SimpleNamespace(state=state)


def _fresh_service():
    """Build an OrderQueueService instance with a mocked Mongo collection
    so we can exercise queue_order() without touching real Mongo."""
    from services.order_queue_service import OrderQueueService
    svc = OrderQueueService()
    svc._initialized = True  # bypass real Mongo connect
    svc._collection = MagicMock()
    svc._collection.insert_one = MagicMock(return_value=MagicMock(inserted_id="x"))
    # find_one used by get_order
    _store: dict = {}
    def _insert(doc):
        # Capture inserts so we can assert what was written.
        _store[doc.get("_id") or doc.get("order_id")] = {
            k: v for k, v in doc.items() if k != "_id"
        }
        return MagicMock(inserted_id=doc.get("_id"))
    svc._collection.insert_one.side_effect = _insert
    svc._collection.find_one = MagicMock(
        side_effect=lambda q, *a, **kw: _store.get(q.get("order_id"))
    )
    svc._inserted = _store  # test hook
    return svc


# ── 1. BMNR P-1: agent path is REFUSED at service layer ─────────────
def test_agent_direct_queue_order_path_is_refused_when_kill_switch_active():
    """Pins BMNR P-1 regression: a bare entry submitted through the
    `trade_executor_agent._execute_order` payload shape (direct
    service.queue_order call) MUST be refused when kill switch is on."""
    svc = _fresh_service()
    fake_guard = _mk_guard(active=True, reason="operator_manual_2026_05_11")

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True):
        # This is the exact payload shape produced by
        # agents/trade_executor_agent.py::_execute_order.
        agent_payload = {
            "symbol": "BMNR",
            "action": "BUY",
            "quantity": 50,
            "order_type": "MKT",
            "limit_price": None,
            "source": "trade_executor_agent",
        }
        order_id = svc.queue_order(agent_payload)

    assert order_id.startswith("ks-refused-"), (
        f"BMNR P-1 regression: expected service-layer refusal, got {order_id}"
    )
    # Refusal row persisted with status=rejected.
    row = svc._inserted.get(order_id)
    assert row is not None, "refusal row should be persisted"
    assert row["status"] == "rejected"
    assert row["result"]["error"] == "kill_switch_active_v19_34_48"
    assert row["symbol"] == "BMNR"
    assert row["rejected_by"] == "_kill_switch_gate_v19_34_69"


# ── 2. Protective orders STILL pass through service-layer gate ──────
def test_service_gate_allows_oca_bracket_legs_when_kill_switch_active():
    """When kill switch is active, protective orders (stop/target with
    oca_group set) must still queue normally — operator's flatten and
    re-bracket flows depend on this."""
    svc = _fresh_service()
    fake_guard = _mk_guard(active=True)

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True):
        # Protective stop leg with oca_group set.
        order_id = svc.queue_order({
            "symbol": "BMNR", "action": "SELL", "quantity": 50,
            "order_type": "STP", "stop_price": 20.0,
            "trade_id": "REISSUE-STOP-abc",
            "oca_group": "OCA-bmnr-123",
        })

    assert not order_id.startswith("ks-refused-"), (
        f"protective bracket leg should NOT be refused, got {order_id}"
    )


def test_service_gate_allows_stop_order_type_alone_when_kill_switch_active():
    """STP / STP_LMT / TRAIL / TRAIL_LMT order_type alone signals
    protective intent — must pass even without oca_group or keyword
    in trade_id."""
    svc = _fresh_service()
    fake_guard = _mk_guard(active=True)

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True):
        order_id = svc.queue_order({
            "symbol": "BMNR", "action": "SELL", "quantity": 50,
            "order_type": "STP", "stop_price": 20.0,
            "trade_id": "bare-uuid-no-prefix",
        })

    assert not order_id.startswith("ks-refused-")


# ── 3. Kill switch INACTIVE → gate is no-op ─────────────────────────
def test_service_gate_no_op_when_kill_switch_inactive():
    svc = _fresh_service()
    fake_guard = _mk_guard(active=False)

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard, create=True):
        order_id = svc.queue_order({
            "symbol": "BMNR", "action": "BUY", "quantity": 50,
            "order_type": "MKT", "trade_id": "bare-uuid-no-prefix",
        })

    assert not order_id.startswith("ks-refused-"), (
        f"with kill switch OFF, gate must pass through; got {order_id}"
    )


# ── 4. Guardrails outage → fail-open (legitimate closes survive) ────
def test_service_gate_fails_open_when_guardrails_unavailable():
    """If `safety_guardrails` cannot be imported / read, we MUST
    fail-open — refusing legitimate close-side orders during a
    guardrails outage is worse than letting an occasional entry
    slip (the executor-layer guard in trade_executor_service.py
    is the secondary defense for that scenario)."""
    svc = _fresh_service()

    def _explode():
        raise RuntimeError("guardrails module crashed")

    with patch("services.safety_guardrails.get_safety_guardrails",
               side_effect=_explode, create=True):
        order_id = svc.queue_order({
            "symbol": "BMNR", "action": "BUY", "quantity": 50,
            "order_type": "MKT", "trade_id": "x",
        })

    assert not order_id.startswith("ks-refused-")


# ── 5. Shared helper parity with routers/ib._kill_switch_gate ───────
def test_evaluate_kill_switch_gate_intent_parity():
    """`services.kill_switch_gate.evaluate_kill_switch_gate` MUST honour
    the same protective-intent ladder that `routers.ib._kill_switch_gate`
    has been enforcing since v19.34.53. If these drift, callers will
    see inconsistent refusal behaviour depending on which entry path
    they used."""
    from services.kill_switch_gate import (
        is_protective_intent, evaluate_kill_switch_gate,
    )

    # Each tuple = (order, should_be_protective)
    cases = [
        # 1. Explicit intent
        ({"intent": "close", "trade_id": "x"}, True),
        ({"intent": "protective", "trade_id": "x"}, True),
        # 2. oca_group alone
        ({"oca_group": "OCA-1", "trade_id": "x"}, True),
        # 3. Stop family order_type
        ({"order_type": "STP", "trade_id": "x"}, True),
        ({"order_type": "STP LMT", "trade_id": "x"}, True),
        ({"order_type": "TRAIL", "trade_id": "x"}, True),
        # 4. trade_id keyword substring
        ({"trade_id": "REISSUE-STOP-abc"}, True),
        ({"trade_id": "FOO-CANCEL-xyz"}, True),
        ({"trade_id": "FLATTEN-AAA"}, True),
        # 5. Legacy prefix
        ({"trade_id": "CLOSE-x"}, True),
        ({"trade_id": "PARTIAL-x"}, True),
        # Negative: bare entry payloads
        ({"trade_id": "abc-123-uuid", "order_type": "MKT"}, False),
        ({"trade_id": "", "order_type": "LMT"}, False),
        ({}, False),
    ]
    for order, expected in cases:
        got = is_protective_intent(order)
        assert got is expected, (
            f"protective-intent mismatch for {order}: expected {expected}, got {got}"
        )

    # End-to-end: gate evaluates None for protective, dict for entry,
    # always None when kill switch inactive.
    fake_guard_on = _mk_guard(active=True)
    fake_guard_off = _mk_guard(active=False)

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard_on, create=True):
        # Entry → refusal dict.
        refusal = evaluate_kill_switch_gate(
            {"symbol": "BMNR", "trade_id": "bare", "order_type": "MKT"}
        )
        assert refusal is not None
        assert refusal["status"] == "rejected"
        # Protective → None.
        assert evaluate_kill_switch_gate(
            {"symbol": "BMNR", "trade_id": "STOP-x", "order_type": "STP"}
        ) is None

    with patch("services.safety_guardrails.get_safety_guardrails",
               return_value=fake_guard_off, create=True):
        # Kill switch off → always None.
        assert evaluate_kill_switch_gate(
            {"symbol": "BMNR", "trade_id": "bare", "order_type": "MKT"}
        ) is None
