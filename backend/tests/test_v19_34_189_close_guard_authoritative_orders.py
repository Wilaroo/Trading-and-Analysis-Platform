"""
v19.34.189 — Close-guard authoritative open-orders fix.

Root cause (CF/BAP, 2026-05-29): `_cancel_ib_bracket_orders` pre-filtered
tracked bracket children against `_ib.trades()` — an in-memory CACHE that
(a) freezes status at disconnect and is never purged on socket-reconnect,
and (b) can't be marked terminal when the order was placed under a different
clientId (the pusher). Dead orders therefore showed as `Submitted` forever →
`wait_for_orders_terminal` timed out → every close aborted with
`bracket_cancel_timeout_race_risk`.

Fix: partition tracked oids against a FRESH `reqAllOpenOrders` round-trip (the
TRUE currently-working orders across all clients). These tests lock the
partition contract + the conservative fetch fallback (no IB hardware needed).
"""
import asyncio
import types

from services.trade_executor_service import TradeExecutorService


# ── pure partition logic ────────────────────────────────────────────────
def test_partition_all_live_blocks():
    present, gone = TradeExecutorService._partition_oids_by_live_set(
        [10913, 10914], {10913, 10914, 9999})
    assert present == [10913, 10914]
    assert gone == []


def test_partition_all_dead_safe():
    # CF case: tracked children no longer in IB's authoritative open set.
    present, gone = TradeExecutorService._partition_oids_by_live_set(
        [10913, 10914], {5, 6, 7})
    assert present == []
    assert gone == [10913, 10914]


def test_partition_mixed_preserves_order():
    present, gone = TradeExecutorService._partition_oids_by_live_set(
        [9760, 9761, 10913], {10913})
    assert present == [10913]
    assert gone == [9760, 9761]


def test_partition_empty_inputs():
    assert TradeExecutorService._partition_oids_by_live_set([], {1, 2}) == ([], [])


# ── authoritative fresh-fetch helper ────────────────────────────────────
def _make_svc():
    # Bypass __init__ (it touches broker config); we only exercise the
    # two new helpers which don't read instance state beyond the method.
    return object.__new__(TradeExecutorService)


def _fake_trade(oid):
    return types.SimpleNamespace(order=types.SimpleNamespace(orderId=oid))


def test_fetch_live_ids_returns_set(monkeypatch):
    svc = _make_svc()

    class _FakeIB:
        def reqAllOpenOrders(self):
            # last entry has order=None → must be skipped by the guard
            return [_fake_trade(10913), _fake_trade(10914),
                    types.SimpleNamespace(order=None)]

    class _FakeIBD:
        _ib = _FakeIB()
        async def ensure_connected(self):
            return True

    import services.trade_executor_service as mod
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: _FakeIBD(), raising=False,
    )
    ids = asyncio.run(svc._fetch_live_open_order_ids())
    # None-order trade is skipped; real ids returned.
    assert ids == {10913, 10914}


def test_fetch_live_ids_none_when_disconnected(monkeypatch):
    svc = _make_svc()

    class _FakeIBD:
        _ib = object()
        async def ensure_connected(self):
            return False

    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: _FakeIBD(), raising=False,
    )
    # None is the conservative signal → caller keeps the block-safe path.
    assert asyncio.run(svc._fetch_live_open_order_ids()) is None


def test_fetch_live_ids_none_on_exception(monkeypatch):
    svc = _make_svc()

    class _FakeIB:
        def reqAllOpenOrders(self):
            raise RuntimeError("IB gateway wedged")

    class _FakeIBD:
        _ib = _FakeIB()
        async def ensure_connected(self):
            return True

    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service",
        lambda: _FakeIBD(), raising=False,
    )
    assert asyncio.run(svc._fetch_live_open_order_ids()) is None
