"""v19.34.70 PATCH C — `/positions/reconcile-bracket-state` endpoint.

Lets the operator (or a scheduled Patch D loop) explicitly null out
stale `stop_order_id` / `target_order_id(s)` refs from the bot's
`_open_trades` view after cross-checking against IB's live order cache.

These tests call the endpoint coroutine directly (matching the pattern
of test_eod_close_now_honors_flag_v19_34_69.py — avoids httpx version
drift in this env).
"""
import asyncio
from datetime import datetime, timezone

import pytest

from routers import trading_bot as tb_module
from routers.trading_bot import ReconcileBracketStateRequest


# ---------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------
class _FakeTrade:
    def __init__(self, trade_id, symbol,
                 stop_oid=None, target_oid=None, target_oids=None):
        self.id = trade_id
        self.symbol = symbol
        self.stop_order_id = stop_oid
        self.target_order_id = target_oid
        self.target_order_ids = target_oids or []


class _FakeBot:
    def __init__(self, trades=None):
        self._open_trades = {t.id: t for t in (trades or [])}
        self._persist_called_for = []

    def _persist_trade(self, trade):
        self._persist_called_for.append(trade.id)


def _call(payload, bot, live_ids, cache_available, monkeypatch):
    """Mount bot + patch the async ib-cache helper, then call the endpoint."""
    monkeypatch.setattr(tb_module, "_trading_bot", bot)

    async def _fake_ib_live_ids():
        return (set(live_ids), cache_available)

    monkeypatch.setattr(tb_module, "_ib_live_order_ids_async", _fake_ib_live_ids)
    req = ReconcileBracketStateRequest(**(payload or {}))
    return asyncio.run(tb_module.reconcile_bracket_state(req))


# ---------------------------------------------------------------------
# 1. Dry run — stale ids surfaced but not modified
# ---------------------------------------------------------------------
def test_dry_run_surfaces_stale_but_does_not_modify(monkeypatch):
    """The 2026-05-21 scenario: trade tracks 4729/4730 but IB cache is
    empty. Dry run reports the stale state and what WOULD be cleared,
    but does NOT mutate the trade and does NOT persist."""
    trade = _FakeTrade("t1", "CF", stop_oid=4729, target_oid=4730)
    bot = _FakeBot([trade])

    resp = _call(
        payload={"dry_run": True}, bot=bot,
        live_ids=set(), cache_available=True, monkeypatch=monkeypatch,
    )

    assert resp["success"] is True
    assert resp["dry_run"] is True
    assert resp["ib_cache_available"] is True
    assert resp["trades_audited"] == 1
    assert resp["trades_modified"] == 0   # dry_run = no writes
    row = resp["trades"][0]
    assert row["symbol"] == "CF"
    assert row["before"]["stop_state"] == "stale"
    assert row["before"]["target_state"] == "stale"
    assert row["after"]["stop_order_id"] is None
    assert row["after"]["target_order_ids"] == []
    assert row["fully_unprotected"] is True
    assert row["applied"] is False
    # State on the trade itself untouched
    assert trade.stop_order_id == 4729
    assert trade.target_order_id == 4730
    assert bot._persist_called_for == []


# ---------------------------------------------------------------------
# 2. Live run — actually clears + persists
# ---------------------------------------------------------------------
def test_live_run_clears_stale_and_persists(monkeypatch):
    trade = _FakeTrade("t1", "CF", stop_oid=4729, target_oid=4730)
    bot = _FakeBot([trade])

    resp = _call(
        payload={"dry_run": False}, bot=bot,
        live_ids=set(), cache_available=True, monkeypatch=monkeypatch,
    )

    assert resp["trades_modified"] == 1
    row = resp["trades"][0]
    assert row["applied"] is True
    # Trade was mutated
    assert trade.stop_order_id is None
    assert trade.target_order_id is None
    assert trade.target_order_ids == []
    # Persistence was called
    assert bot._persist_called_for == ["t1"]


# ---------------------------------------------------------------------
# 3. Live ids → no-op (don't clear good refs)
# ---------------------------------------------------------------------
def test_live_ids_are_left_alone(monkeypatch):
    """Trades whose tracked ids ARE in IB cache must not appear in the
    audit (and certainly must not be cleared)."""
    trade = _FakeTrade("t1", "MSFT", stop_oid=100, target_oid=200)
    bot = _FakeBot([trade])

    resp = _call(
        payload={"dry_run": False}, bot=bot,
        live_ids={100, 200}, cache_available=True, monkeypatch=monkeypatch,
    )

    assert resp["trades_audited"] == 0
    assert resp["trades_modified"] == 0
    assert trade.stop_order_id == 100
    assert trade.target_order_id == 200
    assert bot._persist_called_for == []


# ---------------------------------------------------------------------
# 4. Mixed: stale stop, live target → clears only the stop
# ---------------------------------------------------------------------
def test_mixed_clears_only_stale_leg(monkeypatch):
    trade = _FakeTrade("t1", "AAPL", stop_oid=100, target_oid=200)
    bot = _FakeBot([trade])

    resp = _call(
        payload={"dry_run": False}, bot=bot,
        live_ids={200}, cache_available=True, monkeypatch=monkeypatch,
    )

    row = resp["trades"][0]
    assert row["before"]["stop_state"] == "stale"
    assert row["before"]["target_state"] == "live"
    assert row["after"]["stop_order_id"] is None
    assert row["after"]["target_order_ids"] == [200]
    assert row["fully_unprotected"] is False   # target still real
    assert trade.stop_order_id is None
    assert trade.target_order_id == 200       # untouched
    assert bot._persist_called_for == ["t1"]


# ---------------------------------------------------------------------
# 5. ib_direct unavailable → refuse to reconcile (safety)
# ---------------------------------------------------------------------
def test_ib_cache_unavailable_refuses_to_clear(monkeypatch):
    """If we can't query IB, we MUST refuse to null anything. Clearing
    a good ref when the bracket is actually live would force an
    unnecessary re-attach + risk bracket stacking."""
    trade = _FakeTrade("t1", "CF", stop_oid=4729, target_oid=4730)
    bot = _FakeBot([trade])

    resp = _call(
        payload={"dry_run": False}, bot=bot,
        live_ids=set(), cache_available=False, monkeypatch=monkeypatch,
    )

    assert resp["success"] is False
    assert resp["ib_cache_available"] is False
    assert resp["trades_modified"] == 0
    assert "ib_direct" in resp["error"].lower()
    assert trade.stop_order_id == 4729   # untouched
    assert bot._persist_called_for == []


# ---------------------------------------------------------------------
# 6. Symbol filter
# ---------------------------------------------------------------------
def test_symbol_filter_only_processes_named_symbols(monkeypatch):
    trades = [
        _FakeTrade("t1", "CF", stop_oid=4729),
        _FakeTrade("t2", "INTU", stop_oid=4725),
        _FakeTrade("t3", "AAPL", stop_oid=100),
    ]
    bot = _FakeBot(trades)

    resp = _call(
        payload={"dry_run": False, "symbols": ["CF", "INTU"]},
        bot=bot, live_ids=set(), cache_available=True,
        monkeypatch=monkeypatch,
    )

    syms = sorted(r["symbol"] for r in resp["trades"])
    assert syms == ["CF", "INTU"]
    assert "AAPL" not in syms
    # AAPL untouched
    assert trades[2].stop_order_id == 100


# ---------------------------------------------------------------------
# 7. No open trades → graceful return
# ---------------------------------------------------------------------
def test_no_open_trades_returns_empty_report(monkeypatch):
    bot = _FakeBot([])
    resp = _call(
        payload={"dry_run": True}, bot=bot,
        live_ids=set(), cache_available=True, monkeypatch=monkeypatch,
    )
    assert resp["success"] is True
    assert resp["trades_audited"] == 0
    assert "no open trades" in resp["message"].lower()


# ---------------------------------------------------------------------
# 8. Sim ids untouched (paper mode protection)
# ---------------------------------------------------------------------
def test_sim_ids_are_not_cleared(monkeypatch):
    """SIM-* ids are paper-mode placeholders the bot's manage loop
    expects to see. Don't clear them just because IB cache doesn't
    have them — they were never real IB orders to begin with."""
    trade = _FakeTrade("t1", "CF",
                       stop_oid="SIM-STOP-abc",
                       target_oid="SIM-TGT-xyz")
    bot = _FakeBot([trade])

    resp = _call(
        payload={"dry_run": False}, bot=bot,
        live_ids=set(), cache_available=True, monkeypatch=monkeypatch,
    )

    assert resp["trades_audited"] == 0
    assert trade.stop_order_id == "SIM-STOP-abc"   # untouched
    assert trade.target_order_id == "SIM-TGT-xyz"  # untouched


# ---------------------------------------------------------------------
# 9. 503 when bot not initialized
# ---------------------------------------------------------------------
def test_503_when_bot_uninitialized(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(tb_module, "_trading_bot", None)

    async def _fake_ib_live_ids():
        return (set(), True)
    monkeypatch.setattr(tb_module, "_ib_live_order_ids_async", _fake_ib_live_ids)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(tb_module.reconcile_bracket_state(
            ReconcileBracketStateRequest(dry_run=True),
        ))
    assert excinfo.value.status_code == 503
