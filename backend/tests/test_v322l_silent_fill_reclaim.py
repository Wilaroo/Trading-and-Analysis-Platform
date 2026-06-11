"""
test_v322l_silent_fill_reclaim.py — regression tests for the IB Gateway
false-rejection race (2026-06-11 UNP/USB at the open).

Incident chain: orders placed at 09:32 under Gateway load were tagged by the
two-step path as `parent_not_filled:cancelled` → trade saved REJECTED with
close_reason=broker_rejected — but the fills landed at IB seconds later. The
v19.34.15a poll-back detected the silent fill but only emitted an event; the
generic drift loop then adopted the position as an anonymous
`reconciled_excess_slice` ("I did NOT open this position"), losing the
original setup tag, stop and targets.

v322l: the poll-back now RE-CLAIMS the rejected trade in-place — flips it
back to OPEN with its original SL/PT (R-preserved when the true avg fill is
recoverable) and attaches brackets immediately.

Guards under test:
  1. Happy path — trade re-claimed: OPEN, in bot._open_trades, brackets
     attached, notes stamped.
  2. Direction mismatch (long rejection, short delta) → NOT claimed.
  3. Partial silent fill → claims min(|delta|, planned shares).
  4. Bracket attach failure → trade still re-claimed OPEN (tracked naked,
     naked-sweep covers), returns True.
  5. No bot reference → returns False (drift-loop fallback).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.trade_execution import (  # noqa: E402
    _reclaim_silently_filled_trade_v322l,
)
from services.trading_bot_service import TradeStatus  # noqa: E402


def _trade(direction="long", shares=69, entry=261.50, stop=259.20,
           targets=(266.10,)):
    return SimpleNamespace(
        id="3faaf3a1", symbol="UNP",
        direction=SimpleNamespace(value=direction),
        status=TradeStatus.REJECTED,
        shares=shares, remaining_shares=0, original_shares=0,
        entry_price=entry, stop_price=stop, target_prices=list(targets),
        fill_price=None, executed_at=None, close_reason="broker_rejected",
        notes="[REJECTED: parent_not_filled:cancelled]",
        setup_type="orb_breakout",
        entry_order_id=None, stop_order_id=None, target_order_id=None,
        target_order_ids=[], oca_group=None,
        mfe_price=None, mae_price=None,
    )


class _FakeBot:
    def __init__(self, attach_result):
        self._open_trades = {}
        self._pending_trades = {}
        self._daily_stats = SimpleNamespace(trades_executed=0)
        self.saved = []
        self._attach_result = attach_result

        async def _attach(trade):
            return self._attach_result
        self._trade_executor = SimpleNamespace(attach_oca_stop_target=_attach)

    async def _save_trade(self, t):
        self.saved.append(t)


ATTACH_OK = {"success": True, "stop_order_id": 9001,
             "target_order_id": 9002, "oca_group": "ADOPT-OCA-UNP-3faaf3a1-x"}


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_reclaim_restores_open_trade_with_original_brackets():
    bot, trade = _FakeBot(ATTACH_OK), _trade()
    ok = _run(_reclaim_silently_filled_trade_v322l(
        trade=trade, bot=bot, delta=+69, entry_order_id=355401,
        rejected_error="parent_not_filled:cancelled"))
    assert ok is True
    assert trade.status == TradeStatus.OPEN
    assert trade.close_reason is None
    assert bot._open_trades["3faaf3a1"] is trade
    assert trade.remaining_shares == 69 and trade.original_shares == 69
    assert trade.stop_order_id == 9001 and trade.target_order_id == 9002
    assert trade.stop_price == 259.20          # original SL preserved
    assert trade.target_prices == [266.10]     # original PT preserved
    assert "v322l RECLAIMED" in trade.notes
    assert len(bot.saved) == 2                 # pre-attach + post-attach
    assert bot._daily_stats.trades_executed == 1


def test_direction_mismatch_not_reclaimed():
    bot, trade = _FakeBot(ATTACH_OK), _trade(direction="long")
    ok = _run(_reclaim_silently_filled_trade_v322l(
        trade=trade, bot=bot, delta=-69, entry_order_id=None,
        rejected_error="parent_not_filled:cancelled"))
    assert ok is False
    assert trade.status == TradeStatus.REJECTED
    assert bot._open_trades == {} and bot.saved == []


def test_partial_silent_fill_claims_delta():
    bot, trade = _FakeBot(ATTACH_OK), _trade(shares=100)
    ok = _run(_reclaim_silently_filled_trade_v322l(
        trade=trade, bot=bot, delta=+40, entry_order_id=None,
        rejected_error="parent_not_filled:timeout"))
    assert ok is True
    assert trade.shares == 40
    assert trade.remaining_shares == 40 and trade.original_shares == 40


def test_attach_failure_still_reclaims_open():
    bot = _FakeBot({"success": False, "error": "pusher_offline"})
    trade = _trade()
    ok = _run(_reclaim_silently_filled_trade_v322l(
        trade=trade, bot=bot, delta=+69, entry_order_id=None,
        rejected_error="parent_not_filled:cancelled"))
    assert ok is True
    assert trade.status == TradeStatus.OPEN
    assert trade.stop_order_id is None        # naked but TRACKED
    assert bot._open_trades["3faaf3a1"] is trade


def test_no_bot_returns_false():
    trade = _trade()
    ok = _run(_reclaim_silently_filled_trade_v322l(
        trade=trade, bot=None, delta=+69, entry_order_id=None,
        rejected_error="x"))
    assert ok is False
    assert trade.status == TradeStatus.REJECTED


def test_short_direction_claims_negative_delta():
    bot, trade = _FakeBot(ATTACH_OK), _trade(direction="short")
    ok = _run(_reclaim_silently_filled_trade_v322l(
        trade=trade, bot=bot, delta=-69, entry_order_id=None,
        rejected_error="parent_not_filled:cancelled"))
    assert ok is True
    assert trade.status == TradeStatus.OPEN
