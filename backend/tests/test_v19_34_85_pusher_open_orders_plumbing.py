"""
v19.34.85 — Pusher open-orders snapshot plumbing
=================================================

Background
----------
2026-05-12: `bracket-stacking-audit` reported "clean_symbols" for
every position even though the bot had just stacked 8 new OCA
brackets on top of existing live stops at IB. Root cause: the
audit reads `_pushed_ib_data["orders"]`, which was NEVER populated.
The Windows pusher's payload schema (`IBPushDataRequest`) had no
`orders` field, and the pusher never sent one.

v19.34.85 closes the gap by:
  1. Adding `orders: list = Field(default=[])` to `IBPushDataRequest`.
  2. Storing `request.orders` into `_pushed_ib_data["orders"]` on
     every push (always replacing — empty list means "IB has no
     pending orders", not "stale data").
  3. Returning `orders` count in the push response for log/audit
     traceability.

Tested behavior
---------------
1. Schema accepts an `orders` field with default [].
2. Pushing a payload with orders stores them in _pushed_ib_data.
3. Subsequent push with orders=[] replaces snapshot to empty
   (we trust the pusher's view of "no open orders").
4. Pushes without orders (legacy pre-v85 pushers) still work —
   default empty list, no exception.
5. `bracket-stacking-audit` reads the pushed orders and correctly
   surfaces stacking (was reporting "clean" pre-v85).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, "/app/backend")


def _req(**overrides):
    from routers.ib import IBPushDataRequest
    base = dict(
        timestamp=datetime.now(timezone.utc).isoformat(),
        source="ib_gateway",
        quotes={"SPY": {"last": 600.0}},
    )
    base.update(overrides)
    return IBPushDataRequest(**base)


@pytest.fixture
def isolated_pushed_data():
    """Snapshot + reset _pushed_ib_data so tests don't bleed."""
    import routers.ib as ib_mod
    orig = dict(ib_mod._pushed_ib_data)
    ib_mod._pushed_ib_data.clear()
    ib_mod._pushed_ib_data.update({
        "last_update": None, "quotes": {}, "account": {},
        "positions": [], "level2": {}, "fundamentals": {},
        "news": {}, "news_providers": [], "orders": [],
        "connected": False,
    })
    yield ib_mod
    ib_mod._pushed_ib_data.clear()
    ib_mod._pushed_ib_data.update(orig)


def test_v85_schema_accepts_orders_default_empty():
    """IBPushDataRequest schema must have an `orders` field that
    defaults to [] (backward-compat with pre-v85 pushers)."""
    req = _req()
    assert req.orders == []
    req2 = _req(orders=[{"order_id": 1}])
    assert len(req2.orders) == 1


@pytest.mark.asyncio
async def test_v85_orders_stored_on_push(isolated_pushed_data):
    ib_mod = isolated_pushed_data
    response_mock = SimpleNamespace(status_code=200, headers={})
    req = _req(orders=[
        {
            "order_id": 12345, "symbol": "PEP", "action": "BUY",
            "quantity": 2266, "order_type": "STP", "status": "PreSubmitted",
            "aux_price": 152.41, "oca_group": "ADOPT-OCA-PEP-9848a5a0-4204f3",
        },
        {
            "order_id": 12346, "symbol": "PEP", "action": "BUY",
            "quantity": 2266, "order_type": "LMT", "status": "PreSubmitted",
            "limit_price": 137.47, "oca_group": "ADOPT-OCA-PEP-9848a5a0-4204f3",
        },
    ])
    body = await ib_mod.receive_pushed_ib_data(req, response_mock)
    assert body["success"] is True
    assert body["received"]["orders"] == 2
    stored = ib_mod._pushed_ib_data["orders"]
    assert len(stored) == 2
    assert stored[0]["symbol"] == "PEP"
    assert stored[0]["aux_price"] == 152.41
    assert stored[1]["limit_price"] == 137.47


@pytest.mark.asyncio
async def test_v85_orders_replaced_on_next_push(isolated_pushed_data):
    """Empty orders on a subsequent push means 'IB has no pending
    orders now' — replace, don't merge."""
    ib_mod = isolated_pushed_data
    response_mock = SimpleNamespace(status_code=200, headers={})
    # Seed.
    await ib_mod.receive_pushed_ib_data(
        _req(orders=[{"order_id": 1, "symbol": "ADBE", "quantity": 100, "status": "Submitted"}]),
        response_mock,
    )
    assert len(ib_mod._pushed_ib_data["orders"]) == 1
    # Next push: empty orders → snapshot replaced.
    await ib_mod.receive_pushed_ib_data(_req(orders=[]), response_mock)
    assert ib_mod._pushed_ib_data["orders"] == []


@pytest.mark.asyncio
async def test_v85_legacy_pre_v85_push_still_works(isolated_pushed_data):
    """Pre-v85 pushers never sent an `orders` field. Schema default
    must keep them working without exceptions."""
    ib_mod = isolated_pushed_data
    response_mock = SimpleNamespace(status_code=200, headers={})
    req = _req()  # no orders kw
    body = await ib_mod.receive_pushed_ib_data(req, response_mock)
    assert body["success"] is True
    assert body["received"]["orders"] == 0
    assert ib_mod._pushed_ib_data["orders"] == []


@pytest.mark.asyncio
async def test_v85_bracket_stacking_audit_sees_pushed_orders(isolated_pushed_data):
    """v19.34.85 end-to-end: with orders pushed, the audit should
    surface stacking. Pre-v85 the audit was structurally blind and
    reported "clean" no matter what."""
    ib_mod = isolated_pushed_data
    response_mock = SimpleNamespace(status_code=200, headers={})
    # Seed positions + 3x stacked stops for ADBE (the 2026-05-12
    # 4x-stacking fingerprint, scaled to 3 for the test).
    await ib_mod.receive_pushed_ib_data(
        _req(
            positions=[
                {"symbol": "ADBE", "position": 100, "avg_cost": 246.95}
            ],
            orders=[
                {
                    "order_id": 1, "symbol": "ADBE", "action": "SELL",
                    "quantity": 100, "order_type": "STP",
                    "status": "PreSubmitted", "aux_price": 241.0,
                    "oca_group": "OCA-1",
                },
                {
                    "order_id": 2, "symbol": "ADBE", "action": "SELL",
                    "quantity": 100, "order_type": "STP",
                    "status": "PreSubmitted", "aux_price": 241.5,
                    "oca_group": "OCA-2",
                },
                {
                    "order_id": 3, "symbol": "ADBE", "action": "SELL",
                    "quantity": 100, "order_type": "STP",
                    "status": "PreSubmitted", "aux_price": 242.0,
                    "oca_group": "OCA-3",
                },
            ],
        ),
        response_mock,
    )
    # Inject a bot trade for ADBE so the audit has bot-side context.
    import routers.trading_bot as tb
    orig_bot = tb._trading_bot
    tb._trading_bot = SimpleNamespace(
        _open_trades={
            "t-adbe": SimpleNamespace(
                symbol="ADBE", shares=100, remaining_shares=100,
                direction=SimpleNamespace(value="long"),
            ),
        }
    )
    try:
        body = await tb.bracket_stacking_audit()
        # Pre-v85: clean_symbols would include ADBE because orders
        # were invisible. Post-v85: ADBE must appear in `symbols`
        # with `excess_stop_qty=200`.
        adbe_rows = [s for s in body["symbols"] if s["symbol"] == "ADBE"]
        assert len(adbe_rows) == 1, (
            f"v19.34.85 regression: ADBE must appear in stacking audit "
            f"output once orders are pushed. clean_symbols={body.get('clean_symbols')}, "
            f"symbols={body.get('symbols')}"
        )
        assert adbe_rows[0]["excess_stop_qty"] == 200
        assert adbe_rows[0]["pending_stop_qty_total"] == 300
        assert "ADBE" not in body.get("clean_symbols", [])
    finally:
        tb._trading_bot = orig_bot
