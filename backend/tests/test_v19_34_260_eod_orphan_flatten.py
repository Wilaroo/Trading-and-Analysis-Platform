"""
Regression test for v19.34.260 — EOD-window orphan FLATTEN-instead-of-ADOPT.

Bug history
-----------
2026-06-03: the EOD auto-close pass ran at 15:45:16 ET (19 closed, 0 failed)
and marked `_eod_close_executed_today=True`. ~30s later, at 15:45:47, the
orphan reconciler ADOPTED 13 IB positions the bot had REJECT-ed, as fresh
intraday trades. Bracket attach was blocked (`past_regt_soft_edge_cutoff`),
so they were carried UNPROTECTED overnight. The main EOD pass never re-ran
(gated by the flag), so the operator flattened them by hand.

Fix
---
A) `reconcile_orphan_positions` now checks the bracket-attach governor BEFORE
   adopting. If we're past the Reg-T soft-edge cutoff, the orphan is FLATTENED
   (`_flatten_eod_window_orphan`) instead of adopted — never naked overnight.
B) The flatten path verifies IB went flat, adds the symbol to the re-adopt
   cooldown (`bot._recently_closed_symbols`) + operator-flatten suppression,
   and records a `bot_events` row for the postmortem (kills the re-adopt loop).

These tests cover: the governor trigger condition, the functional behaviour of
the flatten helper, and the structural wiring of the guard before adoption.
"""
import ast
import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from services.position_reconciler import PositionReconciler


# ───────────────────────── governor trigger ─────────────────────────

def test_governor_reports_cutoff_after_345_et():
    """The guard fires only when the governor reports the Reg-T cutoff.
    Verify the governor returns `past_regt_soft_edge_cutoff` after 15:45 ET
    and does NOT report it mid-morning."""
    from services.bracket_attach_governor import get_governor
    gov = get_governor()

    after = datetime(2026, 6, 3, 15, 50, tzinfo=ZoneInfo("America/New_York"))
    ok_after, reason_after = gov.should_attempt_attach("AAPL", now_et=after)
    assert ok_after is False
    assert reason_after == "past_regt_soft_edge_cutoff"

    before = datetime(2026, 6, 3, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    ok_before, reason_before = gov.should_attempt_attach("MSFT", now_et=before)
    assert reason_before != "past_regt_soft_edge_cutoff"


# ───────────────────────── flatten helper behaviour ─────────────────────────

class _FakeIBDirect:
    def __init__(self):
        self.close_calls = []

    async def place_close_market(self, trade, *, wait_for_fill_s=10.0):
        self.close_calls.append({
            "symbol": trade.symbol,
            "shares": trade.shares,
            "direction": getattr(trade.direction, "value", trade.direction),
            "wait": wait_for_fill_s,
        })
        return {"success": True, "status": "filled", "filled_qty": trade.shares,
                "fill_price": 100.0}

    async def verify_position_flat(self, symbol, expected_remaining=0, tolerance=0):
        return {"is_flat": True, "ib_position": 0, "expected": 0, "divergence": 0}


class _FakeSuppression:
    def __init__(self):
        self.added = []

    def add(self, symbol, reason="", trade_ids=None):
        self.added.append((symbol, reason))


class _FakeEvents:
    def __init__(self):
        self.inserted = []

    def insert_one(self, doc):
        self.inserted.append(doc)


def _run(coro):
    return asyncio.run(coro)


def test_flatten_helper_closes_verifies_and_breaks_loop(monkeypatch):
    """`_flatten_eod_window_orphan` must: place a MKT close, verify flat,
    add the symbol to the re-adopt cooldown + suppression, and record an
    `eod_window_orphan_flatten` event."""
    fake_ib = _FakeIBDirect()
    fake_supp = _FakeSuppression()
    fake_events = _FakeEvents()

    monkeypatch.setattr("services.ib_direct_service.get_ib_direct_service",
                        lambda: fake_ib, raising=True)
    monkeypatch.setattr(
        "services.operator_flatten_suppression.get_operator_flatten_suppression",
        lambda: fake_supp, raising=True)

    bot = SimpleNamespace(
        _db=SimpleNamespace(bot_events=fake_events),
        _recently_closed_symbols={},
    )
    rec = PositionReconciler(db=SimpleNamespace(bot_events=fake_events))
    direction = SimpleNamespace(value="long")

    result = _run(rec._flatten_eod_window_orphan(bot, "CLS", direction, 3, 460.15))

    # A — a real MKT close was placed for the right symbol/size.
    assert len(fake_ib.close_calls) == 1
    assert fake_ib.close_calls[0]["symbol"] == "CLS"
    assert fake_ib.close_calls[0]["shares"] == 3
    assert result["flattened"] is True
    assert result["verified_flat"] is True

    # B — the re-adoption loop is broken: cooldown + suppression set.
    assert "CLS" in bot._recently_closed_symbols
    assert any(sym == "CLS" for sym, _ in fake_supp.added)

    # Postmortem trail written.
    assert any(d.get("event_type") == "eod_window_orphan_flatten"
               and d.get("symbol") == "CLS"
               for d in fake_events.inserted)


def test_flatten_helper_breaks_loop_even_if_close_fails(monkeypatch):
    """Defense-in-depth: even when the IB close fails, we must STILL add the
    symbol to cooldown + suppression so the reconciler does not re-adopt an
    unprotected orphan next cycle (it's left for ghost-flatten / operator)."""
    class _FailingIB(_FakeIBDirect):
        async def place_close_market(self, trade, *, wait_for_fill_s=10.0):
            self.close_calls.append(trade.symbol)
            return {"success": False, "error": "ib_direct_not_connected"}

    fake_ib = _FailingIB()
    fake_supp = _FakeSuppression()
    fake_events = _FakeEvents()
    monkeypatch.setattr("services.ib_direct_service.get_ib_direct_service",
                        lambda: fake_ib, raising=True)
    monkeypatch.setattr(
        "services.operator_flatten_suppression.get_operator_flatten_suppression",
        lambda: fake_supp, raising=True)

    bot = SimpleNamespace(_db=SimpleNamespace(bot_events=fake_events),
                          _recently_closed_symbols={})
    rec = PositionReconciler(db=SimpleNamespace(bot_events=fake_events))

    result = _run(rec._flatten_eod_window_orphan(
        bot, "SCHD", SimpleNamespace(value="short"), 77, 32.46))

    assert result["flattened"] is False
    assert "SCHD" in bot._recently_closed_symbols
    assert any(sym == "SCHD" for sym, _ in fake_supp.added)


# ───────────────────────── structural wiring ─────────────────────────

def test_guard_runs_before_adoption():
    """The EOD-window guard must `continue` (skip adoption) BEFORE the
    `BotTrade(` orphan is constructed. If the guard moved below adoption,
    we'd adopt-then-flatten (and could still naked-carry on flatten failure)."""
    src = inspect.getsource(PositionReconciler.reconcile_orphan_positions)
    guard_pos = src.find("past_regt_soft_edge_cutoff")
    flatten_call_pos = src.find("_flatten_eod_window_orphan")
    bottrade_pos = src.find("trade = BotTrade(")
    assert guard_pos > 0, "EOD-window guard removed from reconcile_orphan_positions"
    assert flatten_call_pos > 0, "flatten helper no longer called from the loop"
    assert bottrade_pos > 0, "BotTrade adoption construction not found"
    assert flatten_call_pos < bottrade_pos, (
        "v19.34.260 ordering violation: the EOD-window flatten guard must run "
        "BEFORE the orphan BotTrade is constructed/adopted."
    )


def test_helper_uses_verify_and_suppression():
    """The flatten helper must verify IB-flat and engage the re-adopt
    suppression — the two pieces that break the re-adoption loop."""
    src = inspect.getsource(PositionReconciler._flatten_eod_window_orphan)
    assert "verify_position_flat" in src
    assert "_recently_closed_symbols" in src
    assert "get_operator_flatten_suppression" in src
    assert "eod_window_orphan_flatten" in src


def test_source_is_syntactically_valid():
    import services.position_reconciler as pr
    ast.parse(inspect.getsource(pr))
