"""
Regression tests for 2026-04-29 (afternoon-3) Round 1 UI/Dashboard fixes:

  1. `/api/trading-bot/status` — falls back to IB pushed account snapshot
     when `_trade_executor.get_account_info()` returns empty (IB-mode
     operators were getting `account: {}` and seeing `$—` in the V5 HUD).
  2. `/api/scanner/strategy-mix` — falls back to in-memory `_live_alerts`
     when the Mongo `live_alerts` collection is empty so the V5
     StrategyMixCard always populates if the scanner is producing alerts.
  3. `live_symbol_snapshot.get_latest_snapshot` — falls back to yesterday's
     daily close from `ib_historical_data` when the intraday slice only
     has one bar (fixes SPY missing % change in TopMoversTile at open).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import mongomock


# --- 1. /status falls back to IB pushed account ----------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_bot_status_uses_executor_account_when_present():
    """When trade executor returns a populated account dict, surface it as-is."""
    from routers import trading_bot as tb_router

    bot = MagicMock()
    bot.get_status.return_value = {"running": True, "mode": "paper"}

    executor = MagicMock()
    executor.get_account_info = AsyncMock(return_value={
        "equity": 50_000.0,
        "buying_power": 200_000.0,
        "cash": 50_000.0,
        "portfolio_value": 50_000.0,
    })

    with patch.object(tb_router, "_trading_bot", bot), \
         patch.object(tb_router, "_trade_executor", executor):
        resp = _run(tb_router.get_bot_status())

    assert resp["account"]["equity"] == 50_000.0
    assert resp["account_equity"] == 50_000.0
    assert resp["equity"] == 50_000.0


def test_bot_status_falls_back_to_ib_pushed_when_executor_empty():
    """IB-mode operator: executor returns {} → must read NetLiquidation
    from `routers.ib._pushed_ib_data`."""
    from routers import trading_bot as tb_router
    from routers import ib as ib_router

    bot = MagicMock()
    bot.get_status.return_value = {"running": True, "mode": "live"}

    executor = MagicMock()
    executor.get_account_info = AsyncMock(return_value={})

    fake_ib = {
        "account": {
            "NetLiquidation": {"value": "73250.45", "currency": "USD", "account": "DUN615665"},
            "BuyingPower": {"value": "292001.80", "currency": "USD"},
            "TotalCashBalance": {"value": "12500.00", "currency": "USD"},
        },
        "last_update": "2026-04-29T14:32:00Z",
    }

    with patch.object(tb_router, "_trading_bot", bot), \
         patch.object(tb_router, "_trade_executor", executor), \
         patch.dict(ib_router._pushed_ib_data, fake_ib, clear=False):
        resp = _run(tb_router.get_bot_status())

    assert resp["account"]["equity"] == 73_250.45
    assert resp["account"]["source"] == "ib_pushed"
    assert resp["account_equity"] == 73_250.45
    assert resp["equity"] == 73_250.45


def test_bot_status_no_executor_no_pusher_returns_empty_account():
    """No executor + no IB push → account must be `{}` (operator sees `$—`,
    same behaviour as before — no false equity reported)."""
    from routers import trading_bot as tb_router
    from routers import ib as ib_router

    bot = MagicMock()
    bot.get_status.return_value = {"running": False, "mode": "stopped"}

    snap = dict(ib_router._pushed_ib_data)
    ib_router._pushed_ib_data["account"] = {}
    try:
        with patch.object(tb_router, "_trading_bot", bot), \
             patch.object(tb_router, "_trade_executor", None):
            resp = _run(tb_router.get_bot_status())
    finally:
        ib_router._pushed_ib_data.clear()
        ib_router._pushed_ib_data.update(snap)

    assert resp["account"] == {}
    assert "account_equity" not in resp


# --- 2. /strategy-mix falls back to in-memory alerts -----------------------

def test_strategy_mix_uses_mongo_when_populated():
    """When `live_alerts` collection has rows, use them as the primary source."""
    from routers import scanner as scanner_router

    db = mongomock.MongoClient().db
    db["live_alerts"].insert_many([
        {"setup_type": "breakout", "created_at": "2026-04-29T15:00:00Z"},
        {"setup_type": "breakout_long", "created_at": "2026-04-29T14:55:00Z"},
        {"setup_type": "vwap_bounce", "created_at": "2026-04-29T14:50:00Z"},
    ])

    svc = SimpleNamespace(db=db, _live_alerts={})
    with patch.object(scanner_router, "_scanner_service", svc):
        resp = scanner_router.get_strategy_mix(n=100)

    assert resp["total"] == 3
    by_type = {b["setup_type"]: b["count"] for b in resp["buckets"]}
    # `breakout` + `breakout_long` collapse to `breakout`
    assert by_type.get("breakout") == 2
    assert by_type.get("vwap_bounce") == 1


def test_strategy_mix_falls_back_to_in_memory_when_mongo_empty():
    """The audit case: scanner is firing, in-memory `_live_alerts` has
    items, but Mongo `live_alerts` is empty (persistence gap).
    Card must still populate."""
    from routers import scanner as scanner_router

    db = mongomock.MongoClient().db  # empty live_alerts collection

    in_mem = {
        "a1": SimpleNamespace(
            setup_type="relative_strength_leader",
            direction="long",
            created_at="2026-04-29T15:00:00Z",
            ai_edge_label=None,
        ),
        "a2": SimpleNamespace(
            setup_type="orb_long",
            direction="long",
            created_at="2026-04-29T14:55:00Z",
            ai_edge_label="STRONG_EDGE",
        ),
        "a3": SimpleNamespace(
            setup_type="orb_short",
            direction="short",
            created_at="2026-04-29T14:50:00Z",
            ai_edge_label=None,
        ),
    }
    svc = SimpleNamespace(db=db, _live_alerts=in_mem)
    with patch.object(scanner_router, "_scanner_service", svc):
        resp = scanner_router.get_strategy_mix(n=100)

    assert resp["total"] == 3
    by_type = {b["setup_type"]: b["count"] for b in resp["buckets"]}
    # orb_long + orb_short collapse to "orb"
    assert by_type.get("orb") == 2
    assert by_type.get("relative_strength_leader") == 1
    # STRONG_EDGE counter must propagate even from in-memory fallback
    orb_bucket = next(b for b in resp["buckets"] if b["setup_type"] == "orb")
    assert orb_bucket["strong_edge_count"] == 1


def test_strategy_mix_returns_empty_when_both_sources_empty():
    """Defensive: nothing in Mongo, nothing in memory → clean empty payload."""
    from routers import scanner as scanner_router

    db = mongomock.MongoClient().db
    svc = SimpleNamespace(db=db, _live_alerts={})
    with patch.object(scanner_router, "_scanner_service", svc):
        resp = scanner_router.get_strategy_mix(n=100)

    assert resp == {"success": True, "n": 0, "buckets": [], "total": 0}


# --- 3. SPY missing % — daily-close anchor fallback ------------------------

def test_snapshot_uses_daily_close_when_only_one_intraday_bar():
    """SPY at fresh market open: only 1 intraday 5-min bar exists, so the
    naive prev_close = last_price → change_pct=0 → frontend renders
    `+0.00%` or null. The daily-close anchor fix must read yesterday's
    1-day close from ib_historical_data and produce a real change_pct."""
    from services import live_symbol_snapshot as snap_mod

    fake_svc = SimpleNamespace()
    fake_svc.fetch_latest_session_bars = AsyncMock(return_value={
        "success": True,
        "bars": [{"close": 503.20, "date": "2026-04-29T13:30:00Z"}],
        "source": "pusher_rpc",
        "market_state": "rth",
        "fetched_at": "2026-04-29T13:30:00Z",
    })

    db = mongomock.MongoClient().db
    db["ib_historical_data"].insert_one({
        "symbol": "SPY",
        "bar_size": "1 day",
        "date": "2026-04-28T20:00:00Z",
        "close": 500.00,
    })

    with patch("services.hybrid_data_service.get_hybrid_data_service",
               return_value=fake_svc):
        with patch("server.db", db, create=True):
            res = _run(snap_mod.get_latest_snapshot("SPY", "5 mins"))

    assert res["success"] is True
    assert res["latest_price"] == 503.20
    # Anchored on yesterday's daily close ($500), not last_price
    assert res["prev_close"] == 500.00
    assert res["change_abs"] == 3.20
    # Change vs yesterday's close, not 0
    assert abs(res["change_pct"] - 0.64) < 0.01


def test_snapshot_keeps_intraday_prev_close_when_two_bars_present():
    """Normal case: two intraday bars → prev_close from the previous
    bar (existing behaviour). Daily anchor must NOT override."""
    from services import live_symbol_snapshot as snap_mod

    fake_svc = SimpleNamespace()
    fake_svc.fetch_latest_session_bars = AsyncMock(return_value={
        "success": True,
        "bars": [
            {"close": 502.00, "date": "2026-04-29T13:25:00Z"},
            {"close": 503.20, "date": "2026-04-29T13:30:00Z"},
        ],
        "source": "pusher_rpc",
        "market_state": "rth",
    })

    db = mongomock.MongoClient().db
    db["ib_historical_data"].insert_one({
        "symbol": "SPY",
        "bar_size": "1 day",
        "date": "2026-04-28T20:00:00Z",
        "close": 400.00,  # would produce a wildly different result if used
    })

    with patch("services.hybrid_data_service.get_hybrid_data_service",
               return_value=fake_svc):
        with patch("server.db", db, create=True):
            res = _run(snap_mod.get_latest_snapshot("SPY", "5 mins"))

    # Intraday prev bar wins (502.00), daily anchor (400.00) ignored
    assert res["prev_close"] == 502.00
    assert res["change_abs"] == 1.20


def test_snapshot_no_daily_anchor_when_db_unavailable():
    """If `server.db` lookup raises or is None, snapshot must still return
    the original (zero-change) result without raising."""
    from services import live_symbol_snapshot as snap_mod

    fake_svc = SimpleNamespace()
    fake_svc.fetch_latest_session_bars = AsyncMock(return_value={
        "success": True,
        "bars": [{"close": 503.20, "date": "2026-04-29T13:30:00Z"}],
        "source": "pusher_rpc",
        "market_state": "rth",
    })

    with patch("services.hybrid_data_service.get_hybrid_data_service",
               return_value=fake_svc):
        with patch("server.db", None, create=True):
            res = _run(snap_mod.get_latest_snapshot("SPY", "5 mins"))

    # No daily anchor available → falls back to last_price as prev → 0%
    assert res["success"] is True
    assert res["latest_price"] == 503.20
    assert res["change_pct"] == 0.0
