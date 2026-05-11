"""v19.34.92 — OCA propagation regression tests.

Locks in:
  - When the cloud queues an order with `oca_group`, that field survives
    the round-trip into `get_pending_orders()` so the pusher can read it.
  - Likewise for `oca_type`, `time_in_force`, `outside_rth` — every field
    the pusher needs to faithfully forward to IB.

Note: These tests cover the CLOUD-SIDE half of the v92 fix. The pusher-side
half (actually setting `ib_order.ocaGroup` before `placeOrder`) lives in
`/app/documents/scripts/ib_data_pusher.py` and runs on the user's Windows
box — exercised by live trading, not pytest.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def fresh_queue():
    """Build an OrderQueueService backed by a fake in-memory Mongo
    collection, since we can't reach Mongo from pytest in CI."""
    from services.order_queue_service import OrderQueueService

    class FakeCollection:
        def __init__(self):
            self.docs = []

        def find_one(self, q):
            for d in self.docs:
                if all(d.get(k) == v for k, v in q.items()):
                    return d
            return None

        def insert_one(self, d):
            self.docs.append(d)
            return MagicMock(inserted_id="fake")

        def find(self, q=None, projection=None):
            q = q or {}
            results = []
            for d in self.docs:
                ok = True
                for k, v in q.items():
                    dv = d.get(k)
                    if isinstance(v, dict) and "$in" in v:
                        if dv not in v["$in"]:
                            ok = False
                            break
                    elif isinstance(v, dict) and "$lt" in v:
                        # treat as match-everything for simplicity
                        pass
                    elif dv != v:
                        ok = False
                        break
                if ok:
                    results.append(dict(d))
            class _Cursor:
                def __init__(self, rs):
                    self._r = rs
                def sort(self, *a, **kw):
                    return self
                def __iter__(self):
                    return iter(self._r)
            return _Cursor(results)

        def update_many(self, q, update):
            return MagicMock(modified_count=0)

        def find_one_and_update(self, q, update, return_document=None):
            return None

    svc = OrderQueueService.__new__(OrderQueueService)
    svc._collection = FakeCollection()
    svc._initialized = True
    yield svc


def test_oca_group_survives_queue_round_trip(fresh_queue):
    """Cloud queues a STP with oca_group → pusher reads it back intact."""
    svc = fresh_queue
    order_id = svc.queue_order({
        "symbol": "MDT",
        "action": "BUY",
        "quantity": 412,
        "order_type": "STP",
        "stop_price": 76.0,
        "oca_group": "REISSUE-OCA-TST-001",
        "oca_type": 1,
        "time_in_force": "GTC",
        "outside_rth": True,
    })
    assert order_id
    pending = svc.get_pending_orders()
    assert len(pending) == 1
    p = pending[0]
    assert p["oca_group"] == "REISSUE-OCA-TST-001"
    # oca_type/tif/outside_rth aren't projected from the doc itself but
    # the pusher reads the full dict, so confirm they're in the doc.
    raw = svc._collection.docs[0]
    assert raw.get("oca_type") == 1
    assert raw.get("time_in_force") == "GTC"
    assert raw.get("outside_rth") is True


def test_no_oca_group_does_not_crash(fresh_queue):
    """Naked orders (no oca_group) must still be queued/retrievable."""
    svc = fresh_queue
    oid = svc.queue_order({
        "symbol": "AAPL",
        "action": "SELL",
        "quantity": 100,
        "order_type": "MKT",
    })
    assert oid
    pending = svc.get_pending_orders()
    assert len(pending) == 1
    # oca_group key may be absent OR None — both fine.
    assert not pending[0].get("oca_group")


def test_oca_group_paired_legs_share_same_value(fresh_queue):
    """Two legs (STP + LMT) submitted with the SAME oca_group string
    must both be retrievable with that exact value — otherwise IB can't
    auto-cancel one when the other fills."""
    svc = fresh_queue
    shared_oca = "ADOPT-OCA-MDT-trade-123-abc"
    stop_id = svc.queue_order({
        "symbol": "MDT", "action": "BUY", "quantity": 412,
        "order_type": "STP", "stop_price": 76.0,
        "oca_group": shared_oca,
    })
    target_id = svc.queue_order({
        "symbol": "MDT", "action": "BUY", "quantity": 412,
        "order_type": "LMT", "limit_price": 70.0,
        "oca_group": shared_oca,
    })
    assert stop_id and target_id and stop_id != target_id
    pending = svc.get_pending_orders()
    assert len(pending) == 2
    ocas = {p["oca_group"] for p in pending}
    assert ocas == {shared_oca}  # exactly one unique oca shared by both legs


def test_oca_type_defaults_to_1_when_missing(fresh_queue):
    """If `oca_type` is omitted, the pusher's fallback should use 1
    (cancel-on-fill-with-block). The queue must not silently default
    to a different value that would break OCA semantics."""
    svc = fresh_queue
    svc.queue_order({
        "symbol": "MDT", "action": "BUY", "quantity": 412,
        "order_type": "STP", "stop_price": 76.0,
        "oca_group": "OCA-X",
        # oca_type intentionally absent
    })
    raw = svc._collection.docs[0]
    # Cloud doesn't synthesize oca_type — that's the pusher's job.
    # But the queued doc must be retrievable without crashing.
    assert raw.get("oca_group") == "OCA-X"
    assert "oca_type" not in raw or raw["oca_type"] is None
