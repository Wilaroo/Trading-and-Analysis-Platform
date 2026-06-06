"""
v19.34.289 F2 — DATA-TRUST: minute-level intraday-bar freshness gate.

Audit Phase 1 finding F2: intraday freshness was gated in TRADING DAYS and was
bypassed entirely when a live quote existed, so VWAP/RSI/EMA could be computed
from hours-stale bars while the snapshot read "real". A live quote only proves
the PRICE is fresh, not the indicators.

Fix: during RTH, if the trailing intraday bar was COLLECTED (written to Mongo)
longer than SCANNER_INTRADAY_MAX_BAR_AGE_MIN ago, flag snapshot.intraday_stale so
the auto-exec gate blocks it (info-only — the alert still surfaces). collected_at
is UTC, so the check is timezone-safe (the bar `date` can be ET or UTC).
"""
import asyncio
from datetime import datetime, timezone, timedelta

import mongomock
import pytest

import services.live_bar_cache as lbc
from services.realtime_technical_service import RealTimeTechnicalService


def _svc():
    s = RealTimeTechnicalService()
    s.set_db(mongomock.MongoClient()["t"])
    return s


def _daily(n=40, start=120.0, step=-0.8):
    bars = []
    px = start
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        o, c = px, px + step
        bars.append({
            "timestamp": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(o, 2), "high": round(max(o, c) + 0.3, 2),
            "low": round(min(o, c) - 0.3, 2), "close": round(c, 2), "volume": 1_000_000,
        })
        px = c
    return bars


def _intraday(n=6, collected_age_min=1.0):
    """n intraday bars; trailing bar carries a collected_at `collected_age_min`
    minutes in the past (UTC)."""
    now = datetime.now(timezone.utc)
    bars = []
    for i in range(n):
        bars.append({
            "timestamp": (now - timedelta(minutes=5 * (n - i))).isoformat(),
            "open": 100 + i * 0.1, "high": 100.5 + i * 0.1,
            "low": 99.5 + i * 0.1, "close": 100.2 + i * 0.1, "volume": 5000,
        })
    bars[-1]["collected_at"] = (now - timedelta(minutes=collected_age_min)).isoformat()
    return bars


# ── unit: collected-age helper ────────────────────────────────────────────────

def test_collected_age_recent():
    s = _svc()
    age = s._intraday_collected_age_min(_intraday(collected_age_min=2.0))
    assert age is not None and 1.5 < age < 3.0


def test_collected_age_old():
    s = _svc()
    age = s._intraday_collected_age_min(_intraday(collected_age_min=45.0))
    assert age is not None and age > 40


def test_collected_age_absent_is_none():
    s = _svc()
    bars = _intraday()
    bars[-1].pop("collected_at")
    assert s._intraday_collected_age_min(bars) is None  # live-overlay bar -> fresh
    assert s._intraday_collected_age_min([]) is None


# ── integration: snapshot.intraday_stale gate ────────────────────────────────

def _run_snapshot(s, intraday, monkeypatch, market_state):
    monkeypatch.setattr(s, "_get_intraday_bars_from_db", lambda *a, **k: intraday)
    monkeypatch.setattr(s, "_get_daily_bars_from_db", lambda *a, **k: _daily())
    monkeypatch.setattr(s, "_get_ib_quote", lambda sym: {"price": 100.0, "symbol": sym})

    async def _no_live(*a, **k):
        return None
    monkeypatch.setattr(s, "_get_live_intraday_bars", _no_live)

    async def _spy():
        return 0.0
    monkeypatch.setattr(s, "_get_spy_change", _spy)
    monkeypatch.setattr(lbc, "classify_market_state", lambda *a, **k: market_state)
    return asyncio.run(s.get_technical_snapshot("AAPL", force_refresh=True))


def test_stale_intraday_flagged_during_rth(monkeypatch):
    s = _svc()
    snap = _run_snapshot(s, _intraday(collected_age_min=45.0), monkeypatch, "rth")
    assert snap is not None
    assert snap.intraday_stale is True
    assert snap.intraday_bar_age_min is not None and snap.intraday_bar_age_min > 40


def test_fresh_intraday_not_flagged_during_rth(monkeypatch):
    s = _svc()
    snap = _run_snapshot(s, _intraday(collected_age_min=1.0), monkeypatch, "rth")
    assert snap is not None
    assert snap.intraday_stale is False


def test_stale_intraday_not_flagged_outside_rth(monkeypatch):
    s = _svc()
    # Same stale bars, but overnight -> NOT flagged (intraday naturally sparse).
    snap = _run_snapshot(s, _intraday(collected_age_min=120.0), monkeypatch, "overnight")
    assert snap is not None
    assert snap.intraday_stale is False


def test_env_threshold_respected(monkeypatch):
    s = _svc()
    monkeypatch.setenv("SCANNER_INTRADAY_MAX_BAR_AGE_MIN", "60")
    # 45 min old < 60 min threshold -> fresh.
    snap = _run_snapshot(s, _intraday(collected_age_min=45.0), monkeypatch, "rth")
    assert snap is not None
    assert snap.intraday_stale is False
