"""
v19.34.82 — Force reconcile down (shrink bot tracking to IB truth)
==================================================================

Background
----------
2026-05-12: After the kill-switch bypass incident, the bot's
`_open_trades` over-tracked vs IB (PEP: 2266 bot vs 971 IB; ADBE
similar). The existing reconcilers only handled "IB has more than
bot" — the over-tracking case had no escape hatch. The bot kept
managing phantom shares.

`POST /api/trading-bot/force-reconcile-down` is that escape hatch:
  - shrinks `shares`/`remaining_shares` on the bot's open trades for
    a symbol until the sum matches `target_qty`.
  - never sends any broker order.
  - emits a `share_drift_events` audit row.

Tested behavior
---------------
1. Dry-run returns the FIFO shrink plan WITHOUT mutating trade state.
2. dry_run=False applies the plan: shares + remaining_shares both
   shrink, _save_trade is invoked, and a share_drift_events row is
   written.
3. target_qty omitted → endpoint queries `get_pushed_positions()` and
   uses |IB qty| as target.
4. Multiple trades for the same symbol shrink FIFO (oldest first).
5. target_qty >= tracked_total → endpoint refuses to grow/no-op, with
   an explanation that the orphan reconciler should be used instead.
6. Symbol with no open trades → success message, no plan, no mutation.
7. Endpoint NEVER calls the trade executor (no broker orders).
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/app/backend")


def _mk_trade(
    trade_id: str, symbol: str, shares: int,
    remaining_shares: int = None, direction: str = "long",
):
    return SimpleNamespace(
        id=trade_id, symbol=symbol,
        shares=shares,
        remaining_shares=remaining_shares if remaining_shares is not None else shares,
        direction=SimpleNamespace(value=direction),
        notes="",
    )


@pytest.fixture
def patched_app():
    import routers.trading_bot as tb
    orig_bot, orig_exec = tb._trading_bot, tb._trade_executor

    save_mock = MagicMock(return_value=None)
    # Mock a Mongo collection so the audit log path runs without errors.
    drift_collection = MagicMock()
    db = {"share_drift_events": drift_collection}

    bot = SimpleNamespace(
        _open_trades=OrderedDict(),
        _save_trade=save_mock,
        _db=db,
    )
    executor = SimpleNamespace(
        attach_oca_stop_target=AsyncMock(return_value={"success": True}),
        # Sentinel attribute: any test that touches this means the
        # endpoint mistakenly tried to talk to the broker.
        place_order=MagicMock(side_effect=AssertionError(
            "force-reconcile-down must NEVER send broker orders"
        )),
    )
    tb._trading_bot = bot
    tb._trade_executor = executor

    yield bot, executor, tb.force_reconcile_down, tb.ForceReconcileDownRequest, save_mock, drift_collection

    tb._trading_bot, tb._trade_executor = orig_bot, orig_exec


@pytest.mark.asyncio
async def test_dry_run_plans_but_does_not_mutate(patched_app):
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep-1", _mk_trade("t-pep-1", "PEP", 1500, remaining_shares=1500, direction="short")),
        ("t-pep-2", _mk_trade("t-pep-2", "PEP", 766, remaining_shares=766, direction="short")),
    ])
    resp = await handler(Req(symbol="PEP", target_qty=971, dry_run=True))
    assert resp["success"] is True
    assert resp["dry_run"] is True
    assert resp["target_qty"] == 971
    assert resp["target_qty_source"] == "operator"
    assert resp["before"]["tracked_total"] == 2266
    # FIFO: oldest (t-pep-1) shrinks first by 1295 → 205 remaining.
    # But cut is min(excess=1295, live=1500) = 1295, leaving 205.
    # Remaining excess = 0, so t-pep-2 untouched.
    plan = resp["plan"]
    assert plan[0]["trade_id"] == "t-pep-1"
    assert plan[0]["delta"] == -1295
    assert plan[0]["to_shares"] == 205
    assert plan[0]["to_remaining"] == 205
    assert plan[1]["trade_id"] == "t-pep-2"
    assert plan[1]["delta"] == 0
    # Mutation guards.
    assert bot._open_trades["t-pep-1"].shares == 1500
    assert bot._open_trades["t-pep-2"].shares == 766
    save_mock.assert_not_called()
    drift.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_apply_mutates_trades_and_writes_audit(patched_app):
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep-1", _mk_trade("t-pep-1", "PEP", 1500, remaining_shares=1500, direction="short")),
        ("t-pep-2", _mk_trade("t-pep-2", "PEP", 766, remaining_shares=766, direction="short")),
    ])
    resp = await handler(Req(
        symbol="PEP", target_qty=971, dry_run=False,
        reason="post-kill-switch carryover",
    ))
    assert resp["dry_run"] is False
    assert resp["after"]["tracked_total"] == 971
    # In-memory state mutated.
    assert bot._open_trades["t-pep-1"].shares == 205
    assert bot._open_trades["t-pep-1"].remaining_shares == 205
    assert bot._open_trades["t-pep-2"].shares == 766
    # Save called for the one trade that actually changed.
    assert save_mock.call_count == 1
    saved_trade = save_mock.call_args[0][0]
    assert saved_trade.id == "t-pep-1"
    # Audit log fired with the right shape.
    drift.insert_one.assert_called_once()
    audit = drift.insert_one.call_args[0][0]
    assert audit["event"] == "force_reconcile_down_v19_34_82"
    assert audit["symbol"] == "PEP"
    assert audit["tracked_before"] == 2266
    assert audit["tracked_after"] == 971
    assert audit["delta_shares"] == -1295
    assert audit["operator_reason"] == "post-kill-switch carryover"
    assert audit["target_qty_source"] == "operator"
    assert len(audit["trades_touched"]) == 1
    assert audit["trades_touched"][0]["trade_id"] == "t-pep-1"
    # Notes annotated for forensics.
    assert "v19.34.82 force-reconcile-down" in bot._open_trades["t-pep-1"].notes


@pytest.mark.asyncio
async def test_target_qty_omitted_falls_back_to_ib_pushed(patched_app):
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep-1", _mk_trade("t-pep-1", "PEP", 2266, remaining_shares=2266, direction="short")),
    ])
    # Simulate pusher: IB shows PEP short 971 (negative for short).
    fake_positions = [
        {"symbol": "ADBE", "position": 80},
        {"symbol": "PEP", "position": -971},
    ]
    with patch("routers.ib.get_pushed_positions", return_value=fake_positions):
        resp = await handler(Req(symbol="PEP", dry_run=True))
    assert resp["target_qty"] == 971
    assert resp["target_qty_source"] == "ib_pushed"
    assert resp["plan"][0]["to_shares"] == 971


@pytest.mark.asyncio
async def test_target_above_tracked_is_refused(patched_app):
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep-1", _mk_trade("t-pep-1", "PEP", 500, remaining_shares=500, direction="short")),
    ])
    resp = await handler(Req(symbol="PEP", target_qty=1000, dry_run=False))
    assert resp["success"] is True
    assert resp["plan"] == []
    assert "only SHRINKS" in resp["message"]
    # No mutation, no audit.
    assert bot._open_trades["t-pep-1"].shares == 500
    save_mock.assert_not_called()
    drift.insert_one.assert_not_called()


@pytest.mark.asyncio
async def test_no_open_trades_for_symbol(patched_app):
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-bmnr-1", _mk_trade("t-bmnr-1", "BMNR", 658, direction="long")),
    ])
    resp = await handler(Req(symbol="ZZZ", target_qty=0, dry_run=True))
    assert resp["success"] is True
    assert resp["plan"] == []
    assert resp["before"]["tracked_total"] == 0


@pytest.mark.asyncio
async def test_endpoint_never_calls_broker(patched_app):
    """The whole point of this endpoint: NO broker orders. Ever."""
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-pep-1", _mk_trade("t-pep-1", "PEP", 2266, remaining_shares=2266, direction="short")),
    ])
    await handler(Req(symbol="PEP", target_qty=971, dry_run=False))
    # No order placement should have happened.
    executor.place_order.assert_not_called()
    executor.attach_oca_stop_target.assert_not_awaited()


@pytest.mark.asyncio
async def test_fifo_shrink_spans_multiple_trades(patched_app):
    """Excess > oldest trade size → cut oldest entirely, then next."""
    bot, executor, handler, Req, save_mock, drift = patched_app
    bot._open_trades = OrderedDict([
        ("t-1", _mk_trade("t-1", "ADBE", 200, remaining_shares=200, direction="long")),
        ("t-2", _mk_trade("t-2", "ADBE", 200, remaining_shares=200, direction="long")),
        ("t-3", _mk_trade("t-3", "ADBE", 200, remaining_shares=200, direction="long")),
    ])
    resp = await handler(Req(symbol="ADBE", target_qty=80, dry_run=True))
    plan = resp["plan"]
    # tracked=600, target=80, excess=520. Cut t-1 by 200, t-2 by 200,
    # t-3 by 120 → leaving 80.
    assert plan[0]["delta"] == -200 and plan[0]["to_remaining"] == 0
    assert plan[1]["delta"] == -200 and plan[1]["to_remaining"] == 0
    assert plan[2]["delta"] == -120 and plan[2]["to_remaining"] == 80


@pytest.mark.asyncio
async def test_invalid_inputs(patched_app):
    bot, executor, handler, Req, save_mock, drift = patched_app
    # Empty symbol.
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await handler(Req(symbol="", target_qty=10))
    assert exc.value.status_code == 400
    # Negative target.
    bot._open_trades = OrderedDict([
        ("t-1", _mk_trade("t-1", "AAA", 100)),
    ])
    with pytest.raises(HTTPException) as exc:
        await handler(Req(symbol="AAA", target_qty=-5))
    assert exc.value.status_code == 400
