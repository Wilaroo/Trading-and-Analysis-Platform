"""
v19.34.302 — EOD final-window force-flatten of BRACKETED sweep-misses.

CONTEXT: the v301 naked-flatten guard only flattens UNPROTECTED positions. But the
06-04 MRSH/CEG class is a sweep-miss that still HAS a (synthetic) bracket — it isn't
naked, so v301 skipped it and it rode to the 16:00+ auction. v302 extends the guard:
past the final cutoff (default 15:56 ET, after the EOD close sweep ran), any
intraday/orphan position still open — even bracketed — is force-flattened (cancel
the working bracket first, then MKT). Genuine swing/position holds stay exempt.

These are integration tests over `PositionManager._eod_naked_flatten_guard`, driving
it with a fake ib_direct service + fake bot and a frozen ET clock.
"""
import asyncio
from datetime import datetime, timezone

import pytest

import services.position_manager as pm_mod
from services.position_manager import PositionManager


# ───────────────── fakes ─────────────────

def _frozen_datetime(instant_utc):
    """Return a datetime subclass whose now(tz) yields a fixed instant."""
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant_utc.astimezone(tz) if tz else instant_utc
    return _Fixed


def _et_instant(hour, minute):
    """A UTC instant that maps to the given June-2026 (EDT, UTC-4) ET wall time.
    June 9 2026 is a Tuesday (weekday < 5)."""
    return datetime(2026, 6, 9, hour + 4, minute, tzinfo=timezone.utc)


def _pos(symbol, qty, sec_type="STK"):
    return {"symbol": symbol, "position": qty, "sec_type": sec_type}


def _order(symbol, action, order_type=None, stop_price=None):
    return {"symbol": symbol, "action": action, "order_type": order_type, "stop_price": stop_price}


class _FakeSvc:
    _connected = True

    def __init__(self, positions, orders, cancel_makes_flat=None):
        self._positions = list(positions)
        self._orders = list(orders)
        self._cancel_makes_flat = {s.upper() for s in (cancel_makes_flat or [])}
        self.market_orders = []   # list of (sym, action, qty)
        self.cancels = []         # list of sym

    async def get_positions(self):
        return list(self._positions)

    async def get_open_orders(self):
        return list(self._orders)

    async def cancel_all_open_orders_for_symbol(self, symbol, side=None):
        s = symbol.upper()
        self.cancels.append(s)
        if s in self._cancel_makes_flat:
            self._positions = [
                p for p in self._positions if (p.get("symbol") or "").upper() != s
            ]
        return {"success": True, "cancelled": [1, 2]}

    async def place_market_order(self, symbol, action, qty):
        self.market_orders.append((symbol.upper(), action, int(qty)))
        return {"success": True}


class _FakeTrade:
    def __init__(self, symbol, close_at_eod=True):
        self.symbol = symbol
        self.close_at_eod = close_at_eod


class _FakeColl:
    def __init__(self):
        self.docs = []

    def insert_one(self, d):
        self.docs.append(d)


class _FakeDB:
    def __init__(self):
        self._coll = _FakeColl()

    def __getitem__(self, _key):
        return self._coll


class _FakeBot:
    def __init__(self, trades=None):
        self._open_trades = {t.symbol.upper(): t for t in (trades or [])}
        self._db = _FakeDB()
        self._last_naked_guard_ts = 0.0


def _run(svc, bot, *, hour, minute, monkeypatch, env=None):
    monkeypatch.setattr(pm_mod, "datetime", _frozen_datetime(_et_instant(hour, minute)))
    monkeypatch.setattr(
        "services.ib_direct_service.get_ib_direct_service", lambda: svc, raising=False
    )
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return asyncio.run(PositionManager()._eod_naked_flatten_guard(bot))


# ───────────────── v302: bracketed sweep-miss ─────────────────

def test_bracketed_intraday_force_flattened_in_final_window(monkeypatch):
    # Long 100, protected by a SELL stop (NOT naked), tracked intraday, 15:57 ET.
    svc = _FakeSvc([_pos("MA", 100)], [_order("MA", "SELL", "STP", 470.0)])
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=True)])
    res = _run(svc, bot, hour=15, minute=57, monkeypatch=monkeypatch)
    assert res["force_flattened_attempts"] == 1
    assert svc.cancels == ["MA"]                       # bracket cancelled first
    assert svc.market_orders == [("MA", "SELL", 100)]  # then MKT close
    assert res["flattened"] == 1
    assert res["naked"] == 0


def test_bracketed_intraday_NOT_flattened_before_final_window(monkeypatch):
    # Same position at 15:50 ET — before the 15:56 final cutoff → leave it.
    svc = _FakeSvc([_pos("MA", 100)], [_order("MA", "SELL", "STP", 470.0)])
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=True)])
    res = _run(svc, bot, hour=15, minute=50, monkeypatch=monkeypatch)
    assert res["force_flattened_attempts"] == 0
    assert svc.cancels == []
    assert svc.market_orders == []
    assert res["flattened"] == 0


def test_bracketed_swing_hold_exempt_in_final_window(monkeypatch):
    # Tracked swing hold (close_at_eod=False), bracketed, 15:57 → never flattened.
    svc = _FakeSvc([_pos("MA", 100)], [_order("MA", "SELL", "STP", 470.0)])
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=False)])
    res = _run(svc, bot, hour=15, minute=57, monkeypatch=monkeypatch)
    assert res["force_flattened_attempts"] == 0
    assert res["flattened"] == 0
    assert res["alarmed"] == 0          # protected swing hold → no alarm
    assert svc.market_orders == []


def test_naked_swing_hold_alarmed_not_flattened(monkeypatch):
    # Tracked swing hold gone NAKED at 15:57 → alarm, do NOT flatten.
    svc = _FakeSvc([_pos("MA", 100)], [])  # no protective stop
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=False)])
    res = _run(svc, bot, hour=15, minute=57, monkeypatch=monkeypatch)
    assert res["alarmed"] == 1
    assert res["flattened"] == 0
    assert svc.market_orders == []
    assert any(d["event"] == "naked_overnight_hold" for d in bot._db._coll.docs)


# ───────────────── v301 behaviour preserved ─────────────────

def test_naked_intraday_flattened_v301_path_no_cancel(monkeypatch):
    # Naked intraday at 15:50 (before final window) → v301 flatten, NO bracket cancel.
    svc = _FakeSvc([_pos("MA", 100)], [])
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=True)])
    res = _run(svc, bot, hour=15, minute=50, monkeypatch=monkeypatch)
    assert res["naked"] == 1
    assert res["flattened"] == 1
    assert svc.cancels == []                            # naked → nothing to cancel
    assert svc.market_orders == [("MA", "SELL", 100)]


def test_naked_untracked_orphan_flattened(monkeypatch):
    # Untracked orphan (not in _open_trades), naked, 15:50 → flatten.
    svc = _FakeSvc([_pos("XYZ", -50)], [])  # short orphan
    bot = _FakeBot([])  # no tracked trades
    res = _run(svc, bot, hour=15, minute=50, monkeypatch=monkeypatch)
    assert res["naked"] == 1
    assert res["flattened"] == 1
    assert svc.market_orders == [("XYZ", "BUY", 50)]    # buy-to-cover the short


# ───────────────── cancel-race + window/env gates ─────────────────

def test_leg_fills_during_cancel_no_mkt(monkeypatch):
    # Bracketed intraday at 15:57; a leg fills during the cancel → position flat →
    # NO MKT close should be sent.
    svc = _FakeSvc(
        [_pos("MA", 100)], [_order("MA", "SELL", "STP", 470.0)],
        cancel_makes_flat=["MA"],
    )
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=True)])
    res = _run(svc, bot, hour=15, minute=57, monkeypatch=monkeypatch)
    assert svc.cancels == ["MA"]
    assert svc.market_orders == []                      # already flat → no MKT
    assert res["flattened"] == 1
    assert any(
        d.get("note") == "closed_by_leg_during_cancel" for d in bot._db._coll.docs
    )


def test_outside_window_skips(monkeypatch):
    svc = _FakeSvc([_pos("MA", 100)], [])
    bot = _FakeBot([_FakeTrade("MA")])
    res = _run(svc, bot, hour=15, minute=30, monkeypatch=monkeypatch)
    assert res["skipped_reason"] == "outside_window"
    assert svc.market_orders == []


def test_force_flatten_disabled_env_leaves_bracketed(monkeypatch):
    # EOD_FORCE_FLATTEN_BRACKETED=false → bracketed position is NOT force-flattened
    # even in the final window (v301 naked path still active separately).
    svc = _FakeSvc([_pos("MA", 100)], [_order("MA", "SELL", "STP", 470.0)])
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=True)])
    res = _run(svc, bot, hour=15, minute=57, monkeypatch=monkeypatch,
               env={"EOD_FORCE_FLATTEN_BRACKETED": "false"})
    assert res["force_flattened_attempts"] == 0
    assert svc.market_orders == []


def test_force_flatten_minute_env_override(monkeypatch):
    # Custom final cutoff at 15:50 via env → a bracketed position at 15:52 flattens.
    svc = _FakeSvc([_pos("MA", 100)], [_order("MA", "SELL", "STP", 470.0)])
    bot = _FakeBot([_FakeTrade("MA", close_at_eod=True)])
    res = _run(svc, bot, hour=15, minute=52, monkeypatch=monkeypatch,
               env={"EOD_FORCE_FLATTEN_MINUTE": "50"})
    assert res["force_flattened_attempts"] == 1
    assert svc.market_orders == [("MA", "SELL", 100)]


def test_guard_disabled_env(monkeypatch):
    svc = _FakeSvc([_pos("MA", 100)], [])
    bot = _FakeBot([_FakeTrade("MA")])
    res = _run(svc, bot, hour=15, minute=57, monkeypatch=monkeypatch,
               env={"EOD_NAKED_FLATTEN_GUARD": "false"})
    assert res["skipped_reason"] == "disabled"
