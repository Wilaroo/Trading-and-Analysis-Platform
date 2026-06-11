"""v19.34.89 — Auto-orphan-sweep regression tests.

Locks in:
  - _fetch_ib_open_orders falls through to _pushed_ib_data["orders"] Tier 3
    when tiers 1 (ib_direct) and 2 (ib_service relay) are both unavailable.
  - cancel_orphan_gtc_orders falls through to the v19.34.88 cancel queue
    when ib_direct is disconnected/unavailable.
  - Only SAFE_TO_AUTO_CANCEL verdicts are auto-cancelled; mismatched_size
    and tracked are refused.
"""
import importlib
import sys
import pytest


@pytest.fixture
def fresh_modules():
    """Reload routers.ib + orphan_gtc_reconciler so module state is clean."""
    for mod_name in ("routers.ib", "services.orphan_gtc_reconciler"):
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
    import routers.ib as ib_mod
    import services.orphan_gtc_reconciler as og_mod
    ib_mod._cancellation_queue.clear()
    # Seed pusher data with a couple of fake open orders for Tier 3 tests.
    ib_mod._pushed_ib_data["orders"] = []
    ib_mod._pushed_ib_data["positions"] = []
    yield ib_mod, og_mod
    ib_mod._cancellation_queue.clear()
    ib_mod._pushed_ib_data["orders"] = []
    ib_mod._pushed_ib_data["positions"] = []


@pytest.mark.asyncio
async def test_tier3_fetch_reads_pusher_orders(fresh_modules):
    """When ib_direct and ib_service are unavailable, _fetch_ib_open_orders
    must surface orders from _pushed_ib_data["orders"]."""
    ib_mod, og_mod = fresh_modules
    ib_mod._pushed_ib_data["orders"] = [
        {
            "order_id": 12345, "perm_id": 0,
            "symbol": "AAPL", "action": "SELL",
            "quantity": 100, "remaining": 100,
            "order_type": "STP", "limit_price": None, "stop_price": 150.0,
            "tif": "GTC", "status": "PreSubmitted",
        },
    ]
    orders, src = await og_mod._fetch_ib_open_orders()
    assert orders is not None
    assert src["tier"] in ("pusher_orders_snapshot", "ib_service_relay", "ib_direct")
    # On a pusher-only deployment this is the only tier that returns data.
    if src["tier"] == "pusher_orders_snapshot":
        assert len(orders) == 1
        assert orders[0]["ib_order_id"] == 12345
        assert orders[0]["symbol"] == "AAPL"
        assert orders[0]["stop_price"] == 150.0


@pytest.mark.asyncio
async def test_tier3_skips_terminal_orders(fresh_modules):
    """Cancelled/Filled orders in the pusher snapshot must NOT show up
    as working orders."""
    ib_mod, og_mod = fresh_modules
    ib_mod._pushed_ib_data["orders"] = [
        {"order_id": 1, "symbol": "X", "status": "Filled", "quantity": 10,
         "order_type": "LMT", "action": "SELL", "tif": "GTC"},
        {"order_id": 2, "symbol": "Y", "status": "Cancelled", "quantity": 10,
         "order_type": "STP", "action": "SELL", "tif": "GTC"},
        {"order_id": 3, "symbol": "Z", "status": "Submitted", "quantity": 10,
         "order_type": "LMT", "action": "SELL", "tif": "GTC"},
    ]
    orders, src = await og_mod._fetch_ib_open_orders()
    if src["tier"] == "pusher_orders_snapshot":
        # Only the Submitted one should pass.
        assert len(orders) == 1
        assert orders[0]["ib_order_id"] == 3


@pytest.mark.asyncio
async def test_cancel_orphan_uses_queue_when_ib_direct_unavailable(fresh_modules):
    """When ib_direct isn't reachable, cancel_orphan_gtc_orders must
    route safe verdicts through the v19.34.88 cancel queue."""
    ib_mod, og_mod = fresh_modules
    verdicts = [
        og_mod.OrderVerdict(
            ib_order_id=98765, perm_id=None, symbol="TST", action="SELL",
            quantity=100, order_type="STP", limit_price=None, stop_price=10.0,
            time_in_force="GTC", status="PreSubmitted",
            verdict=og_mod.VERDICT_NAKED_NO_POSITION,
        ),
    ]
    result = await og_mod.cancel_orphan_gtc_orders(verdicts_to_cancel=verdicts)
    # On the test env ib_direct returns None → queue fallback fires.
    assert result["requested"] == 1
    assert len(result["cancelled"]) == 1
    assert result["cancelled"][0]["ib_order_id"] == 98765
    assert result["cancelled"][0]["via"] == "cancel_queue"
    # Queue entry must exist.
    assert 98765 in ib_mod._cancellation_queue
    entry = ib_mod._cancellation_queue[98765]
    assert entry["status"] == "pending"
    assert "orphan-gtc auto-sweep" in entry["reason"]


@pytest.mark.asyncio
async def test_cancel_orphan_refuses_unsafe_verdicts(fresh_modules):
    """mismatched_size and tracked must NEVER be auto-cancelled."""
    ib_mod, og_mod = fresh_modules
    verdicts = [
        og_mod.OrderVerdict(
            ib_order_id=111, perm_id=None, symbol="UNSAFE1", action="SELL",
            quantity=10, order_type="STP", limit_price=None, stop_price=1.0,
            time_in_force="GTC", status="Submitted",
            verdict=og_mod.VERDICT_MISMATCHED_SIZE,
        ),
        og_mod.OrderVerdict(
            ib_order_id=222, perm_id=None, symbol="UNSAFE2", action="SELL",
            quantity=10, order_type="STP", limit_price=None, stop_price=1.0,
            time_in_force="GTC", status="Submitted",
            verdict=og_mod.VERDICT_TRACKED,
        ),
    ]
    result = await og_mod.cancel_orphan_gtc_orders(verdicts_to_cancel=verdicts)
    assert result["requested"] == 2
    assert len(result["cancelled"]) == 0
    assert len(result["refused_unsafe"]) == 2
    # Neither order ID should be in the cancel queue.
    assert 111 not in ib_mod._cancellation_queue
    assert 222 not in ib_mod._cancellation_queue


@pytest.mark.asyncio
async def test_cancel_orphan_mixed_safe_and_unsafe(fresh_modules):
    """Mix of safe + unsafe → only safe queued, unsafe in refused list."""
    ib_mod, og_mod = fresh_modules
    verdicts = [
        og_mod.OrderVerdict(
            ib_order_id=300, perm_id=None, symbol="SAFE", action="SELL",
            quantity=10, order_type="STP", limit_price=None, stop_price=1.0,
            time_in_force="GTC", status="Submitted",
            verdict=og_mod.VERDICT_ORPHAN_NO_TRADE,
        ),
        og_mod.OrderVerdict(
            ib_order_id=400, perm_id=None, symbol="UNSAFE", action="SELL",
            quantity=10, order_type="STP", limit_price=None, stop_price=1.0,
            time_in_force="GTC", status="Submitted",
            verdict=og_mod.VERDICT_MISMATCHED_SIZE,
        ),
    ]
    result = await og_mod.cancel_orphan_gtc_orders(verdicts_to_cancel=verdicts)
    assert len(result["cancelled"]) == 1
    assert result["cancelled"][0]["ib_order_id"] == 300
    assert len(result["refused_unsafe"]) == 1
    assert result["refused_unsafe"][0]["ib_order_id"] == 400
    assert 300 in ib_mod._cancellation_queue
    assert 400 not in ib_mod._cancellation_queue


@pytest.mark.asyncio
async def test_safe_to_auto_cancel_constant_unchanged():
    """Defensive: the SAFE_TO_AUTO_CANCEL set must remain
    {NAKED_NO_POSITION, ORPHAN_NO_TRADE, EOD_INTRADAY_ENTRY} (the
    third member added in v19.34.151 for the EOD intraday-entry
    sweep). Expanding it further without explicit operator review
    would risk cancelling stops that are legitimately protecting
    positions (MISMATCHED_SIZE) — and awaiting_data (M0c) must NEVER
    be auto-cancellable."""
    from services.orphan_gtc_reconciler import (
        SAFE_TO_AUTO_CANCEL,
        VERDICT_NAKED_NO_POSITION,
        VERDICT_ORPHAN_NO_TRADE,
        VERDICT_EOD_INTRADAY_ENTRY,
        VERDICT_AWAITING_DATA,
        VERDICT_MISMATCHED_SIZE,
        VERDICT_TRACKED,
    )
    assert SAFE_TO_AUTO_CANCEL == frozenset({
        VERDICT_NAKED_NO_POSITION,
        VERDICT_ORPHAN_NO_TRADE,
        VERDICT_EOD_INTRADAY_ENTRY,
    })
    assert VERDICT_MISMATCHED_SIZE not in SAFE_TO_AUTO_CANCEL
    assert VERDICT_TRACKED not in SAFE_TO_AUTO_CANCEL
    assert VERDICT_AWAITING_DATA not in SAFE_TO_AUTO_CANCEL


@pytest.mark.asyncio
async def test_idempotent_requeue_during_sweep(fresh_modules):
    """If the same verdict is fed twice (e.g., two consecutive sweep
    ticks before the pusher processes the first batch), the queue
    must not double-queue or reset the original timestamp."""
    ib_mod, og_mod = fresh_modules
    v = og_mod.OrderVerdict(
        ib_order_id=555, perm_id=None, symbol="DUP", action="SELL",
        quantity=10, order_type="STP", limit_price=None, stop_price=1.0,
        time_in_force="GTC", status="Submitted",
        verdict=og_mod.VERDICT_NAKED_NO_POSITION,
    )
    r1 = await og_mod.cancel_orphan_gtc_orders(verdicts_to_cancel=[v])
    ts1 = ib_mod._cancellation_queue[555]["requested_at"]
    r2 = await og_mod.cancel_orphan_gtc_orders(verdicts_to_cancel=[v])
    ts2 = ib_mod._cancellation_queue[555]["requested_at"]
    assert ts1 == ts2  # idempotent timestamp
    assert len(r1["cancelled"]) == 1
    assert len(r2["cancelled"]) == 1  # function still reports it as cancelled-queued
