"""
v19.34.288 F3 — DATA-TRUST: stop fabricating indicator geometry.

Audit Phase 1 finding F3: when intraday bars were thin/missing, the snapshot
fabricated indicators with price multipliers (vwap=price*0.998, ema9=price*0.99,
ema20=price*0.985, rsi=50). Those invented numbers fed real stop/target geometry.

The fix replaces fabrication with a 3-tier REAL-or-flag hierarchy:
  - real    : >=5 real intraday bars (unchanged)
  - warming : 1-4 real intraday bars -> compute from the real bars that exist
  - proxy   : 0 intraday bars -> anchor to REAL daily values (session open for
              VWAP, prior close for short EMAs, REAL daily RSI) -- never a
              price multiplier.
And a missing DAILY history is now a fail-closed skip + a `data_gap_events`
flag (hybrid-C) instead of fabricated daily levels.
"""
import asyncio
from datetime import datetime, timezone, timedelta

import mongomock
import pytest

from services.realtime_technical_service import RealTimeTechnicalService


def _daily_downtrend(n=40, start=120.0, step=-0.8):
    """n daily bars trending DOWN so a real RSI is clearly < 50 (not the old
    hardcoded 50 fallback). Returns chronological (oldest first)."""
    bars = []
    px = start
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        o = px
        c = px + step
        h = max(o, c) + 0.3
        lo = min(o, c) - 0.3
        bars.append({
            "timestamp": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(o, 2), "high": round(h, 2),
            "low": round(lo, 2), "close": round(c, 2), "volume": 1_000_000,
        })
        px = c
    return bars


def _svc():
    s = RealTimeTechnicalService()
    s.set_db(mongomock.MongoClient()["t"])
    return s


def test_proxy_no_intraday_uses_real_daily_anchors_not_multipliers():
    s = _svc()
    daily = _daily_downtrend()
    price = 100.0
    snap = s._calculate_snapshot(
        symbol="AAPL", current_price=price,
        intraday_bars=None, daily_bars=daily,
        quote={"price": price}, spy_change_pct=0.0,
    )
    # Labeled as proxy (so downstream sees it traded on a proxy).
    assert snap.data_quality == "proxy"
    assert snap.bars_used == 0
    # VWAP anchored to REAL session open, NOT the fabricated price*0.998.
    assert snap.vwap != round(price * 0.998, 2)
    assert snap.vwap == round(daily[-1]["open"], 2)
    # EMAs anchored to REAL prior close, NOT price*0.99 / price*0.985.
    assert snap.ema_9 != round(price * 0.99, 2)
    assert snap.ema_20 != round(price * 0.985, 2)
    assert snap.ema_9 == round(daily[-2]["close"], 2)
    # RSI is a REAL daily RSI on a downtrend (clearly < 50), NOT the old 50.
    assert snap.rsi_14 != 50
    assert snap.rsi_14 < 50


def test_warming_few_intraday_bars_computed_from_real_bars():
    s = _svc()
    daily = _daily_downtrend()
    # 3 real intraday bars (1-4 -> warming).
    intraday = [
        {"timestamp": "2026-02-10 09:35:00", "open": 100, "high": 101, "low": 99.5, "close": 100.5, "volume": 5000},
        {"timestamp": "2026-02-10 09:40:00", "open": 100.5, "high": 101.5, "low": 100, "close": 101.0, "volume": 6000},
        {"timestamp": "2026-02-10 09:45:00", "open": 101.0, "high": 101.8, "low": 100.8, "close": 101.4, "volume": 7000},
    ]
    snap = s._calculate_snapshot(
        symbol="AAPL", current_price=101.4,
        intraday_bars=intraday, daily_bars=daily,
        quote={"price": 101.4}, spy_change_pct=0.0,
    )
    assert snap.data_quality == "warming"
    assert snap.bars_used == 3
    # VWAP computed from the REAL bars (must equal the manual VWAP).
    tp = [(b["high"] + b["low"] + b["close"]) / 3 for b in intraday]
    vol = [b["volume"] for b in intraday]
    expected_vwap = round(sum(t * v for t, v in zip(tp, vol)) / sum(vol), 2)
    assert snap.vwap == expected_vwap
    # Not the fabricated multiplier.
    assert snap.vwap != round(101.4 * 0.998, 2)


def test_full_intraday_still_real():
    s = _svc()
    daily = _daily_downtrend()
    intraday = [
        {"timestamp": f"2026-02-10 09:{30 + i}:00", "open": 100 + i * 0.1,
         "high": 100.5 + i * 0.1, "low": 99.5 + i * 0.1,
         "close": 100.2 + i * 0.1, "volume": 5000 + i * 100}
        for i in range(20)
    ]
    snap = s._calculate_snapshot(
        symbol="AAPL", current_price=102.0,
        intraday_bars=intraday, daily_bars=daily,
        quote={"price": 102.0}, spy_change_pct=0.0,
    )
    assert snap.data_quality == "real"
    assert snap.bars_used == 20


def test_no_price_multiplier_fabrication_anywhere_in_proxy_path():
    """Belt-and-braces: the proxy snapshot must not equal ANY of the four old
    fabricated values."""
    s = _svc()
    daily = _daily_downtrend()
    price = 250.0
    snap = s._calculate_snapshot(
        symbol="NVDA", current_price=price,
        intraday_bars=[], daily_bars=daily,
        quote={"price": price}, spy_change_pct=0.0,
    )
    forbidden = {
        round(price * 0.998, 2),  # old vwap
        round(price * 0.99, 2),   # old ema9
        round(price * 0.985, 2),  # old ema20
    }
    assert snap.vwap not in forbidden
    assert snap.ema_9 not in forbidden
    assert snap.ema_20 not in forbidden
    assert snap.rsi_14 != 50


def test_flag_daily_data_gap_writes_event_idempotent():
    s = _svc()
    s._flag_daily_data_gap("tsla")
    s._flag_daily_data_gap("TSLA")  # same day -> upsert, hits increments
    rows = list(s._db["data_gap_events"].find({"kind": "daily_missing"}))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "TSLA"
    assert rows[0]["hits"] == 2


def test_get_snapshot_skips_and_flags_on_missing_daily(monkeypatch):
    """When a live quote exists but daily bars are missing, snapshot returns
    None (fail-closed) AND records a daily-gap flag."""
    s = _svc()

    monkeypatch.setattr(s, "_get_intraday_bars_from_db", lambda *a, **k: None)
    monkeypatch.setattr(s, "_get_daily_bars_from_db", lambda *a, **k: None)
    monkeypatch.setattr(s, "_get_ib_quote", lambda sym: {"price": 100.0, "symbol": sym})

    async def _no_live(*a, **k):
        return None
    monkeypatch.setattr(s, "_get_live_intraday_bars", _no_live)

    async def _spy():
        return 0.0
    monkeypatch.setattr(s, "_get_spy_change", _spy)

    result = asyncio.run(s.get_technical_snapshot("AAPL"))
    assert result is None
    flagged = list(s._db["data_gap_events"].find({"symbol": "AAPL", "kind": "daily_missing"}))
    assert len(flagged) == 1
