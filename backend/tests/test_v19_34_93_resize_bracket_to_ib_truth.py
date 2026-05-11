"""v19.34.93 — resize-bracket-to-ib-truth regression tests.

Locks in:
  - Dry-run returns the planned cancel + attach without firing anything.
  - target_qty=0 without `allow_zero_qty` is rejected (safety guard).
  - No bot trade + target_qty>0 + no override prices → 400 error.
  - Successful path: queues cancels for all existing legs, returns
    cancel_summary, calls attach_oca_stop_target with overridden qty.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, "/app/backend")


@pytest.fixture
def patched_app():
    import routers.trading_bot as tb
    orig_bot = tb._trading_bot
    executor = SimpleNamespace(
        attach_oca_stop_target=AsyncMock(return_value={
            "success": True,
            "stop_order_id": 9991,
            "target_order_id": 9992,
            "oca_group": "NEW-OCA-X",
        }),
    )
    bot = SimpleNamespace(_open_trades={}, _trade_executor=executor)
    tb._trading_bot = bot
    yield bot, tb.resize_bracket_to_ib_truth, tb.ResizeBracketRequest
    tb._trading_bot = orig_bot


def _leg(order_id, qty, price, order_type, symbol="ABC", action="SELL", oca=None):
    return {
        "order_id": order_id,
        "quantity": qty,
        ("stop_price" if order_type.startswith("STP") else "limit_price"): price,
        "oca_group": oca,
        "action": action,
        "order_type": order_type,
        "status": "PreSubmitted",
        "symbol": symbol,
    }


@pytest.mark.asyncio
async def test_dry_run_returns_plan_without_firing(patched_app):
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ABC", remaining_shares=100, stop_order_id="999",
            stop_price=95.0, target_prices=[110.0], direction="long",
        ),
    }
    orders = [
        _leg(101, 100, 90.0, "STP", "ABC"),
        _leg(102, 100, 115.0, "LMT", "ABC"),
    ]
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(symbol="ABC", dry_run=True))
    assert resp["success"] is True
    assert resp["dry_run"] is True
    assert resp["bot_position_qty"] == 100
    assert resp["target_qty"] == 100
    assert sorted(resp["would_cancel_ids"]) == [101, 102]
    assert resp["would_attach"]["qty"] == 100
    assert resp["would_attach"]["stop_price"] == 95.0
    assert resp["would_attach"]["target_price"] == 110.0
    # Executor must NOT have been called.
    bot._trade_executor.attach_oca_stop_target.assert_not_called()


@pytest.mark.asyncio
async def test_zero_qty_without_allow_flag_is_rejected(patched_app):
    """target_qty=0 without allow_zero_qty=True must 400."""
    bot, handler, Req = patched_app
    # No bot trade for ABC → bot_position_qty=0 → target_qty resolves to 0.
    from fastapi import HTTPException
    with patch("routers.ib._pushed_ib_data", {"orders": []}):
        with pytest.raises(HTTPException) as exc:
            await handler(Req(symbol="ABC", dry_run=False))
    assert exc.value.status_code == 400
    assert "allow_zero_qty" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_zero_qty_with_allow_flag_just_cancels(patched_app):
    """target_qty=0 with allow_zero_qty=True cancels everything; no attach."""
    bot, handler, Req = patched_app
    orders = [
        _leg(101, 50, 90.0, "STP", "ABC"),
        _leg(102, 50, 115.0, "LMT", "ABC"),
    ]
    import routers.ib as ib_mod
    ib_mod._cancellation_queue.clear()
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(
            symbol="ABC", dry_run=False, target_qty=0,
            allow_zero_qty=True, cancel_wait_s=0.1,
        ))
    assert resp["success"] is True
    assert resp["target_qty"] == 0
    assert sorted(c["order_id"] for c in resp["cancelled"]) == [101, 102]
    assert resp["attached"] is None  # no re-attach
    bot._trade_executor.attach_oca_stop_target.assert_not_called()
    ib_mod._cancellation_queue.clear()


@pytest.mark.asyncio
async def test_target_qty_but_no_bot_trade_400(patched_app):
    """target_qty>0 + no bot trade tracking symbol → 400 unless prices passed."""
    bot, handler, Req = patched_app
    # No open trades.
    from fastapi import HTTPException
    with patch("routers.ib._pushed_ib_data", {"orders": []}):
        with pytest.raises(HTTPException) as exc:
            await handler(Req(symbol="ABC", dry_run=False, target_qty=50))
    assert exc.value.status_code == 400
    assert "no bot trade" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_full_flow_cancels_and_reattaches(patched_app):
    """End-to-end: existing legs queued for cancel, executor called with
    overridden qty."""
    bot, handler, Req = patched_app
    bot._open_trades = {
        "t-1": SimpleNamespace(
            symbol="ABC", remaining_shares=200, stop_order_id="999",
            stop_price=95.0, target_prices=[110.0], direction="long",
        ),
    }
    orders = [
        _leg(101, 100, 90.0, "STP", "ABC"),
        _leg(102, 100, 115.0, "LMT", "ABC"),
        _leg(103, 100, 91.0, "STP", "ABC"),
        _leg(104, 100, 116.0, "LMT", "ABC"),
    ]
    import routers.ib as ib_mod
    ib_mod._cancellation_queue.clear()
    with patch("routers.ib._pushed_ib_data", {"orders": orders}):
        resp = await handler(Req(
            symbol="ABC", dry_run=False, cancel_wait_s=0.1,
        ))
    assert resp["success"] is True
    assert resp["target_qty"] == 200
    assert sorted(c["order_id"] for c in resp["cancelled"]) == [101, 102, 103, 104]
    # Executor called once.
    bot._trade_executor.attach_oca_stop_target.assert_called_once()
    # Returns the new bracket details.
    assert resp["attached"]["stop_order_id"] == 9991
    assert resp["attached"]["target_order_id"] == 9992
    assert resp["attached"]["oca_group"] == "NEW-OCA-X"
    assert resp["attached"]["qty"] == 200
    ib_mod._cancellation_queue.clear()


@pytest.mark.asyncio
async def test_price_overrides_dont_mutate_trade(patched_app):
    """new_stop_price/new_target_price must NOT permanently mutate the
    bot's tracked trade object — they're temporary overrides for the
    executor call only."""
    bot, handler, Req = patched_app
    trade = SimpleNamespace(
        symbol="ABC", remaining_shares=100, stop_order_id="999",
        stop_price=95.0, target_prices=[110.0], direction="long",
    )
    bot._open_trades = {"t-1": trade}
    import routers.ib as ib_mod
    ib_mod._cancellation_queue.clear()
    with patch("routers.ib._pushed_ib_data", {"orders": []}):
        await handler(Req(
            symbol="ABC", dry_run=False,
            new_stop_price=92.0, new_target_price=112.0,
            cancel_wait_s=0.05,
        ))
    # Trade prices restored.
    assert trade.stop_price == 95.0
    assert trade.target_prices == [110.0]
    ib_mod._cancellation_queue.clear()
