"""
v19.34.80 — Cancel-excess-bracket-legs endpoint regression
============================================================

Operator-triggered companion to:
  - v19.34.77 audit (read-only) — diagnoses stacking
  - v19.34.79 sibling sweep — seals the leak going forward

This endpoint unwinds HISTORICAL stacking. Picks ONE bracket pair to
keep per symbol, cancels the rest via the same `cancel_order` primitive
used by `_grow_existing_excess_slice` and `cancel-all-pending-orders`.

Decision strategy (highest priority first):
  1. `keep_oca_group="OCA-xxx"` — full operator control.
  2. `keep_order_ids=[...]` — explicit "don't cancel these".
  3. Canonical slice (whatever `bot._open_trades[sym].stop_order_id` /
     `.target_order_ids` track).
  4. Fallback: newest by IB order_id (monotonic).

Assertions
----------
1. Empty pending → noop response, no errors.
2. Dry-run reports cancelled-list without firing.
3. Apply with direct IB service available → calls `cancel_order` for
   every non-kept leg.
4. `keep_oca_group` honoured even when canonical exists.
5. `keep_order_ids` honoured.
6. Canonical preferred when no operator override.
7. Newest fallback when canonical doesn't match any pending leg.
8. Target prefers same-OCA-group as kept stop, falls back to newest.
9. `_ib_service=None` (pusher-only deploy) returns helpful error,
   doesn't crash.
10. `cancel_order` returning False is recorded in errors.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, "/app/backend")


def _leg(order_id, qty, price, oca_group, order_type, action="SELL"):
    return {
        "order_id": order_id,
        "quantity": qty,
        "stop_price" if order_type.startswith("STP") else "limit_price": price,
        "oca_group": oca_group,
        "action": action,
        "order_type": order_type,
        "status": "PreSubmitted",
        "symbol": "ADBE",
    }


@pytest.fixture
def patched_app():
    import routers.trading_bot as tb
    orig_bot = tb._trading_bot
    bot = SimpleNamespace(_open_trades={}, _save_trade=AsyncMock())
    tb._trading_bot = bot
    yield bot, tb.cancel_excess_bracket_legs, tb.CancelExcessBracketLegsRequest
    tb._trading_bot = orig_bot


@pytest.mark.asyncio
async def test_empty_pending_returns_noop(patched_app):
    bot, handler, Req = patched_app
    with patch("routers.ib._pushed_ib_data", {"orders": []}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    assert resp["success"] is True
    assert resp["kept"] is None
    assert resp["cancelled"] == []
    assert resp["errors"] == []


@pytest.mark.asyncio
async def test_dry_run_reports_without_firing(patched_app):
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(102, 40, 270.75, "OCA-A", "LMT"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
        _leg(104, 80, 270.75, "OCA-B", "LMT"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    assert resp["dry_run"] is True
    # Default: newest (highest order_id) is kept (OCA-B, ids 103/104).
    assert resp["kept"]["stop"]["order_id"] == 103
    assert resp["kept"]["target"]["order_id"] == 104
    cancelled_ids = sorted(l["order_id"] for l in resp["cancelled"])
    assert cancelled_ids == [101, 102]


@pytest.mark.asyncio
async def test_apply_fires_cancel_for_each_excess(patched_app):
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(102, 40, 270.75, "OCA-A", "LMT"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
        _leg(104, 80, 270.75, "OCA-B", "LMT"),
    ]
    # v19.34.88 — endpoint now gates on is_connected(); must return True
    # to take the direct-IB path instead of falling through to the queue.
    mock_ib = SimpleNamespace(
        cancel_order=AsyncMock(return_value=True),
        is_connected=lambda: True,
    )
    with patch("routers.ib._pushed_ib_data", {"orders": orders}), \
         patch("routers.ib._ib_service", mock_ib):
        resp = await handler(Req(symbol="ADBE", dry_run=False))
    assert mock_ib.cancel_order.await_count == 2
    cancelled_ids = sorted(c.args[0] for c in mock_ib.cancel_order.call_args_list)
    assert cancelled_ids == [101, 102]
    assert resp["errors"] == []


@pytest.mark.asyncio
async def test_keep_oca_group_overrides_default(patched_app):
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(102, 40, 270.75, "OCA-A", "LMT"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
        _leg(104, 80, 270.75, "OCA-B", "LMT"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(
            symbol="ADBE", dry_run=True,
            keep_oca_group="OCA-A",
        ))
    assert resp["kept"]["stop"]["order_id"] == 101
    assert resp["kept"]["target"]["order_id"] == 102
    assert resp["kept"]["decision_source"] == "keep_oca_group"


@pytest.mark.asyncio
async def test_keep_order_ids_honoured(patched_app):
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(102, 40, 270.75, "OCA-A", "LMT"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(
            symbol="ADBE", dry_run=True,
            keep_order_ids=[103],
        ))
    assert resp["kept"]["stop"]["order_id"] == 103
    assert resp["kept"]["decision_source"] == "keep_order_ids"


@pytest.mark.asyncio
async def test_canonical_slice_preferred_when_present(patched_app):
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ADBE",
            stop_order_id="101",
            target_order_ids=["102"],
        ),
    }
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(102, 40, 270.75, "OCA-A", "LMT"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
        _leg(104, 80, 270.75, "OCA-B", "LMT"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    assert resp["kept"]["stop"]["order_id"] == 101
    assert resp["kept"]["target"]["order_id"] == 102
    assert resp["kept"]["decision_source"] == "canonical_slice"


@pytest.mark.asyncio
async def test_newest_fallback_when_canonical_missing(patched_app):
    """Canonical points to an order_id that's not in pending legs →
    fall back to newest."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ADBE",
            stop_order_id="999",  # not in pending
            target_order_ids=["998"],
        ),
    }
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(102, 40, 270.75, "OCA-A", "LMT"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
        _leg(104, 80, 270.75, "OCA-B", "LMT"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    # Stop fallback to newest = 103.
    assert resp["kept"]["stop"]["order_id"] == 103
    # Target prefers same-OCA-group as kept stop = 104.
    assert resp["kept"]["target"]["order_id"] == 104


@pytest.mark.asyncio
async def test_pusher_only_deploy_routes_through_cancel_queue(patched_app):
    """v19.34.88 — When `_ib_service` is None (pusher-only DGX deploy),
    cancels are enqueued via `queue_cancellation` instead of returning
    an error. Pre-v88 this returned ib_service_unavailable; v88 made it
    self-healing."""
    bot, handler, Req = patched_app
    # Clean the queue so we can assert exactly what got added.
    import routers.ib as ib_mod
    ib_mod._cancellation_queue.clear()
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}), \
         patch("routers.ib._ib_service", None):
        resp = await handler(Req(symbol="ADBE", dry_run=False))
    assert resp["success"] is True
    # Excess legs queued; no errors.
    assert resp["errors"] == []
    queue_statuses = [c.get("queue_status") for c in resp["cancelled"]]
    assert queue_statuses and all(s == "pending" for s in queue_statuses)
    ib_mod._cancellation_queue.clear()


@pytest.mark.asyncio
async def test_cancel_returning_false_is_recorded(patched_app):
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 40, 237.05, "OCA-A", "STP"),
        _leg(103, 80, 237.05, "OCA-B", "STP"),
    ]
    # v19.34.88 — is_connected must be True to use the direct-IB path
    # (where the False return is surfaced as cancel_returned_false).
    mock_ib = SimpleNamespace(
        cancel_order=AsyncMock(return_value=False),
        is_connected=lambda: True,
    )
    with patch("routers.ib._pushed_ib_data", {"orders": orders}), \
         patch("routers.ib._ib_service", mock_ib):
        resp = await handler(Req(symbol="ADBE", dry_run=False))
    assert any(
        e.get("error") == "cancel_returned_false" and e.get("order_id") == 101
        for e in resp["errors"]
    )


@pytest.mark.asyncio
async def test_only_target_legs_present_picks_newest_target(patched_app):
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 40, 270.75, "OCA-A", "LMT"),
        _leg(102, 80, 270.75, "OCA-B", "LMT"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ADBE", dry_run=True))
    assert resp["kept"]["target"]["order_id"] == 102
    assert resp["kept"]["stop"] is None
    assert resp["cancelled"][0]["order_id"] == 101
