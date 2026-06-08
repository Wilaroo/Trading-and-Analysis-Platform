"""
v19.34.291 F4 — snapshot-cache freshness on the decision path.
v19.34.292 F5 — session-anchored intraday window (no prior-session blending).

F4: the shared snapshot cache TTL is 120s; auto-exec must not run on data up to
2 min stale. get_technical_snapshot now accepts `max_age_sec`, and the scanner
passes a tight value (SCANNER_SNAPSHOT_MAX_AGE_SEC, default 30) so decisions use
fresh data while bulk callers (bar-poll) keep the default TTL.

F5: _filter_current_session keeps only bars from the trailing bar's ET session so
VWAP / short EMAs / HOD-LOD don't blend yesterday into today.
"""
import asyncio
from datetime import datetime, timezone, timedelta

import mongomock

from services.realtime_technical_service import RealTimeTechnicalService


def _svc():
    s = RealTimeTechnicalService()
    s.set_db(mongomock.MongoClient()["t"])
    return s


# ── F5: session anchoring ─────────────────────────────────────────────────────

def test_session_filter_drops_prior_session():
    s = _svc()
    bars = [
        {"timestamp": "2026-02-09T14:35:00+00:00", "close": 1},   # ET Feb 9 09:35
        {"timestamp": "2026-02-09T20:55:00+00:00", "close": 2},   # ET Feb 9 15:55
        {"timestamp": "2026-02-10T14:35:00+00:00", "close": 3},   # ET Feb 10 09:35
        {"timestamp": "2026-02-10T15:00:00+00:00", "close": 4},   # ET Feb 10 10:00
    ]
    out = s._filter_current_session(bars)
    assert [b["close"] for b in out] == [3, 4]


def test_session_filter_evening_bar_not_misbucketed():
    """A 7:30pm ET bar is past UTC-midnight (UTC Feb 11) but belongs to the ET
    Feb-10 session — RTH bars must still be kept (regression on naive UTC date)."""
    s = _svc()
    bars = [
        {"timestamp": "2026-02-10T14:35:00+00:00", "close": 1},   # ET Feb 10 09:35
        {"timestamp": "2026-02-10T20:55:00+00:00", "close": 2},   # ET Feb 10 15:55
        {"timestamp": "2026-02-11T00:30:00+00:00", "close": 3},   # ET Feb 10 19:30
    ]
    out = s._filter_current_session(bars)
    assert [b["close"] for b in out] == [1, 2, 3]  # all same ET session


def test_session_filter_ib_format_dates():
    s = _svc()
    bars = [
        {"timestamp": "20260209 09:35:00", "close": 1},
        {"timestamp": "20260210 09:35:00", "close": 2},
        {"timestamp": "20260210 10:00:00", "close": 3},
    ]
    out = s._filter_current_session(bars)
    assert [b["close"] for b in out] == [2, 3]


def test_session_filter_single_session_unchanged():
    s = _svc()
    bars = [{"timestamp": "2026-02-10T14:35:00+00:00", "close": i} for i in range(5)]
    assert s._filter_current_session(bars) == bars
    assert s._filter_current_session([bars[0]]) == [bars[0]]  # <2 -> unchanged


def test_session_filter_failopen_on_garbage():
    s = _svc()
    bars = [{"timestamp": "???", "close": 1}, {"timestamp": "???", "close": 2}]
    # Unparseable dates -> both share the same (empty-ish) key -> unchanged set.
    out = s._filter_current_session(bars)
    assert len(out) == 2


# ── F4: max_age_sec freshness override ───────────────────────────────────────

def _fresh_cached(s, symbol, age_sec):
    daily = [
        {"timestamp": f"2026-01-{i+1:02d}", "open": 100, "high": 101, "low": 99,
         "close": 100.5, "volume": 1_000_000} for i in range(22)
    ]
    snap = s._calculate_snapshot(
        symbol=symbol, current_price=100.0, intraday_bars=None,
        daily_bars=daily, quote={"price": 100.0}, spy_change_pct=0.0,
    )
    # Backdate the snapshot so the cache-age check sees it as `age_sec` old.
    snap.timestamp = (datetime.now(timezone.utc) - timedelta(seconds=age_sec)).isoformat()
    s._cache[symbol] = snap
    return snap


def test_max_age_sec_rejects_stale_cache():
    s = _svc()
    cached = _fresh_cached(s, "AAPL", age_sec=90)  # 90s old; global TTL=120 would serve it

    async def go():
        # With a tight 30s window the 90s cache is too stale -> NOT returned.
        # (No DB data here, so a miss returns None, proving the cache was bypassed.)
        return await s.get_technical_snapshot("AAPL", mongo_only=True, max_age_sec=30)

    assert asyncio.run(go()) is None


def test_default_ttl_still_serves_recent_cache():
    s = _svc()
    cached = _fresh_cached(s, "AAPL", age_sec=90)  # 90s < default 120s TTL

    async def go():
        return await s.get_technical_snapshot("AAPL", mongo_only=True)  # no override

    assert asyncio.run(go()) is cached
