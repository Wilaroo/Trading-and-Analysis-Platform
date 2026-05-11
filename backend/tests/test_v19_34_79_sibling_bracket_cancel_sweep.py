"""
v19.34.79 — Sibling-bracket cancel sweep regression
======================================================

Background
----------
2026-05-12 TWS forensic audit revealed systemic bracket-stacking on every
scale-in. ADBE 80sh long carried 320sh of pending stops (4x position),
EFA 963sh long carried 2,888sh (3x), GM 109sh long carried 1,282sh (12x).
If any leg fired, the others would have stayed live → next tick flips
the position massively short.

Root cause
----------
v19.34.42's `_grow_existing_excess_slice` correctly cancels the
CANONICAL slice's old bracket before placing the new one sized to the
cumulative position. But when the bot tracks multiple BotTrade objects
for the same symbol (scale-in via successive evals, or reconciler
spawning excess slices), each sibling has its OWN bracket at IB. The
grow path only cleaned up the canonical slice — every sibling kept its
bracket alive.

Fix
---
After the canonical slice's bracket is replaced, sweep sibling
BotTrades for the same (symbol, direction) and cancel their brackets
too. The canonical slice's NEW bracket already covers the cumulative
position size — sibling brackets are redundant by construction.

Assertions
----------
1. Single-trade-per-symbol case (no siblings) — sweep is a no-op,
   canonical's bracket still gets replaced.
2. Two-trade-same-symbol case — sibling's `_cancel_ib_bracket_orders`
   is invoked, its stop/target ids cleared, notes annotated.
3. Three-trade-same-symbol case — both siblings swept.
4. Opposing-direction trades (long + short on same symbol) — the short
   sibling is NOT touched (different exposure).
5. Different-symbol siblings are NOT touched.
6. Sibling whose executor cancel raises an exception is logged but
   does NOT crash the grow path.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "/app/backend")


def _mk_trade(tid, symbol, shares, direction="long",
              stop_order_id="REAL-STP", target_order_id="REAL-TGT"):
    direction_obj = SimpleNamespace(value=direction)
    return SimpleNamespace(
        id=tid, symbol=symbol, shares=shares, remaining_shares=shares,
        original_shares=shares,
        entry_price=100.0, fill_price=100.0, stop_price=98.0,
        target_prices=[105.0], target_price=105.0,
        direction=direction_obj,
        stop_order_id=stop_order_id,
        target_order_id=target_order_id,
        target_order_ids=[target_order_id] if target_order_id else [],
        oca_group="OCA-original",
        risk_amount=200.0,
        notes="",
    )


def _make_bot_with_executor(trades_list):
    bot = SimpleNamespace(
        _open_trades={t.id: t for t in trades_list},
        _save_trade=AsyncMock(return_value=None),
    )
    executor = SimpleNamespace(
        _cancel_ib_bracket_orders=AsyncMock(return_value=None),
        attach_oca_stop_target=AsyncMock(return_value={
            "success": True,
            "stop_order_id": "NEW-STP-cumulative",
            "target_order_id": "NEW-TGT-cumulative",
            "oca_group": "OCA-new-cumulative",
        }),
    )
    bot._trade_executor = executor
    return bot, executor


@pytest.mark.asyncio
async def test_no_siblings_is_noop_sweep():
    """Lone canonical slice → sweep finds no siblings, canonical bracket
    still gets cancelled+replaced via the original v19.34.42 logic."""
    from services.position_reconciler import PositionReconciler
    rec = PositionReconciler(db=None)
    canonical = _mk_trade("t-adbe", "ADBE", 40)
    bot, executor = _make_bot_with_executor([canonical])
    await rec._grow_existing_excess_slice(
        bot, canonical, "ADBE",
        ib_qty_signed=80, bot_q=40, ib_meta={}, ib_quote=None,
    )
    # Canonical's bracket was cancelled (once, from the original grow path).
    assert executor._cancel_ib_bracket_orders.await_count == 1
    awaited_arg = executor._cancel_ib_bracket_orders.call_args_list[0][0][0]
    assert awaited_arg is canonical
    # And new OCA was attached.
    executor.attach_oca_stop_target.assert_awaited_once()
    # New ids landed on canonical.
    assert canonical.stop_order_id == "NEW-STP-cumulative"


@pytest.mark.asyncio
async def test_one_sibling_same_symbol_same_direction_is_swept():
    """Sibling's bracket gets cancelled, ids cleared, notes annotated."""
    from services.position_reconciler import PositionReconciler
    rec = PositionReconciler(db=None)
    canonical = _mk_trade("t-1", "ADBE", 40)
    sibling = _mk_trade("t-2", "ADBE", 40,
                        stop_order_id="REAL-SIB-STP",
                        target_order_id="REAL-SIB-TGT")
    bot, executor = _make_bot_with_executor([canonical, sibling])
    await rec._grow_existing_excess_slice(
        bot, canonical, "ADBE",
        ib_qty_signed=80, bot_q=80, ib_meta={}, ib_quote=None,
    )
    # 2 cancel calls: one for canonical (orig logic) + one for sibling (v19.34.79).
    assert executor._cancel_ib_bracket_orders.await_count == 2
    cancelled_trades = [
        c[0][0] for c in executor._cancel_ib_bracket_orders.call_args_list
    ]
    assert sibling in cancelled_trades
    # Sibling ids cleared so it doesn't appear "bracketed" in v19.34.77 audit.
    assert sibling.stop_order_id is None
    assert sibling.target_order_ids == []
    # Note annotation present.
    assert "v19.34.79" in sibling.notes
    assert "merged into canonical slice" in sibling.notes
    assert "t-1" in sibling.notes


@pytest.mark.asyncio
async def test_multiple_siblings_all_swept():
    from services.position_reconciler import PositionReconciler
    rec = PositionReconciler(db=None)
    canonical = _mk_trade("t-1", "ADBE", 40)
    sib_a = _mk_trade("t-2", "ADBE", 40)
    sib_b = _mk_trade("t-3", "ADBE", 40)
    bot, executor = _make_bot_with_executor([canonical, sib_a, sib_b])
    await rec._grow_existing_excess_slice(
        bot, canonical, "ADBE",
        ib_qty_signed=120, bot_q=120, ib_meta={}, ib_quote=None,
    )
    assert executor._cancel_ib_bracket_orders.await_count == 3
    cancelled_trades = [
        c[0][0] for c in executor._cancel_ib_bracket_orders.call_args_list
    ]
    assert sib_a in cancelled_trades
    assert sib_b in cancelled_trades


@pytest.mark.asyncio
async def test_opposing_direction_sibling_is_not_swept():
    """A short trade on the same symbol represents a DIFFERENT exposure —
    don't sweep its bracket when growing a long position."""
    from services.position_reconciler import PositionReconciler
    rec = PositionReconciler(db=None)
    canonical_long = _mk_trade("t-long", "ADBE", 40, direction="long")
    short_sibling = _mk_trade("t-short", "ADBE", 40, direction="short")
    bot, executor = _make_bot_with_executor([canonical_long, short_sibling])
    await rec._grow_existing_excess_slice(
        bot, canonical_long, "ADBE",
        ib_qty_signed=80, bot_q=80, ib_meta={}, ib_quote=None,
    )
    # Only canonical cancelled, NOT the short sibling.
    assert executor._cancel_ib_bracket_orders.await_count == 1
    awaited_arg = executor._cancel_ib_bracket_orders.call_args_list[0][0][0]
    assert awaited_arg is canonical_long
    # Short sibling untouched.
    assert short_sibling.stop_order_id == "REAL-STP"
    assert "v19.34.79" not in short_sibling.notes


@pytest.mark.asyncio
async def test_different_symbol_sibling_is_not_swept():
    from services.position_reconciler import PositionReconciler
    rec = PositionReconciler(db=None)
    canonical = _mk_trade("t-adbe", "ADBE", 40)
    other_sym = _mk_trade("t-aapl", "AAPL", 40)
    bot, executor = _make_bot_with_executor([canonical, other_sym])
    await rec._grow_existing_excess_slice(
        bot, canonical, "ADBE",
        ib_qty_signed=80, bot_q=80, ib_meta={}, ib_quote=None,
    )
    assert executor._cancel_ib_bracket_orders.await_count == 1
    assert other_sym.stop_order_id == "REAL-STP"
    assert "v19.34.79" not in other_sym.notes


@pytest.mark.asyncio
async def test_sibling_cancel_exception_does_not_crash_grow():
    """If sibling cancel raises, log + continue. Canonical's grow
    must still succeed."""
    from services.position_reconciler import PositionReconciler
    rec = PositionReconciler(db=None)
    canonical = _mk_trade("t-1", "ADBE", 40)
    sibling = _mk_trade("t-2", "ADBE", 40)
    bot, executor = _make_bot_with_executor([canonical, sibling])

    # Make the sibling's cancel raise (canonical's still succeeds).
    async def _selective_cancel(trade):
        if trade is sibling:
            raise RuntimeError("simulated broker timeout on sibling cancel")
        return None
    executor._cancel_ib_bracket_orders = AsyncMock(side_effect=_selective_cancel)

    # Must not raise.
    await rec._grow_existing_excess_slice(
        bot, canonical, "ADBE",
        ib_qty_signed=80, bot_q=80, ib_meta={}, ib_quote=None,
    )
    # Canonical's new bracket still attached.
    executor.attach_oca_stop_target.assert_awaited_once()
    # Sibling's ids still cleared even though the broker cancel failed —
    # better to lose track than to think a defunct order is still alive.
    assert sibling.stop_order_id is None
