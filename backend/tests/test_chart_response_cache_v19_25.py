"""
test_chart_response_cache_v19_25.py — pin the cache + tail-endpoint
contract shipped in v19.25 (chart performance hardening).

v19.25 attacks the "very very delayed chart loading" complaint with two
surgical wins:

  Tier 1 — backend response cache (`services/chart_response_cache.py`)
    Mongo-backed TTL cache for `/api/sentcom/chart`. 30s for intraday,
    180s for daily. Survives backend restarts via TTL index. Best-effort
    — cache failures fall through to the live compute path.

  Tier 2 — tail-only refresh endpoint (`/api/sentcom/chart-tail`)
    Returns ONLY new bars + last indicator values since `since=<unix>`.
    Frontend polls every 5s during RTH (smart polling) instead of
    re-shipping the full 5,000-bar window every 30s.

These tests run pure-Python — no IB, no network, no real Mongo.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --------------------------------------------------------------------------
# 1. ChartResponseCache — in-memory tier
# --------------------------------------------------------------------------

def test_cache_get_miss_returns_none():
    """Empty cache returns None on get — never raises."""
    from services.chart_response_cache import ChartResponseCache, make_cache_key
    c = ChartResponseCache(db=None)
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    assert _run(c.get(key)) is None


def test_cache_set_then_get_returns_payload():
    """Round-trip: a payload set with TTL=60 must come back on get."""
    from services.chart_response_cache import ChartResponseCache, make_cache_key
    c = ChartResponseCache(db=None)
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    payload = {
        "success": True, "symbol": "SPY", "timeframe": "5min",
        "bar_count": 3, "bars": [{"time": 1, "open": 100, "high": 101,
                                   "low": 99, "close": 100, "volume": 1000}],
    }
    ok = _run(c.set(key, payload, ttl_seconds=60))
    assert ok is True
    got = _run(c.get(key))
    assert got is not None
    assert got["symbol"] == "SPY"
    assert got["bar_count"] == 3


def test_cache_invalidate_drops_all_entries_for_symbol():
    """When a bot fills a trade for SBUX, every cached SBUX chart entry
    (1min, 5min, 1day, etc.) gets invalidated so the next chart load
    picks up the new marker."""
    from services.chart_response_cache import ChartResponseCache, make_cache_key
    c = ChartResponseCache(db=None)
    payload = {"success": True, "symbol": "SBUX", "bars": []}
    for tf in ("1min", "5min", "15min", "1day"):
        for days in (5, 30):
            k = make_cache_key("SBUX", tf, "rth_plus_premarket", days)
            _run(c.set(k, {**payload, "timeframe": tf}, ttl_seconds=120))
    # Add a non-SBUX entry that must NOT be touched.
    spy_key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    _run(c.set(spy_key, {**payload, "symbol": "SPY"}, ttl_seconds=60))

    dropped = _run(c.invalidate("SBUX"))
    assert dropped >= 8

    for tf in ("1min", "5min", "15min", "1day"):
        for days in (5, 30):
            k = make_cache_key("SBUX", tf, "rth_plus_premarket", days)
            assert _run(c.get(k)) is None
    # SPY entry survived
    assert _run(c.get(spy_key)) is not None


def test_cache_ttl_aware_for_daily_vs_intraday():
    """`chart_cache_ttl_for` must return 180s for daily, 30s for intraday.
    Tighter TTLs would cause the recompute hammer the cache fixes;
    looser would let the chart go visibly stale during live ticks."""
    from services.chart_response_cache import chart_cache_ttl_for
    assert chart_cache_ttl_for("1min") == 30
    assert chart_cache_ttl_for("5min") == 30
    assert chart_cache_ttl_for("15min") == 30
    assert chart_cache_ttl_for("1hour") == 30
    assert chart_cache_ttl_for("1day") == 180
    assert chart_cache_ttl_for("daily") == 180


def test_cache_singleton_attaches_db_lazily():
    """get_chart_response_cache() returns a process-wide singleton.
    The db handle can attach late (services boot before db is ready)."""
    from services.chart_response_cache import get_chart_response_cache
    c1 = get_chart_response_cache(db=None)
    fake_db = MagicMock()
    c2 = get_chart_response_cache(db=fake_db)
    assert c1 is c2
    assert c2._db is fake_db


def test_cache_key_normalization():
    """Cache keys collapse symbol case + timeframe whitespace so the
    frontend's slight variations all hit the same entry."""
    from services.chart_response_cache import make_cache_key
    a = make_cache_key("spy", "5min", "rth_plus_premarket", 5)
    b = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    c = make_cache_key("SPY", "5min", "RTH_PLUS_PREMARKET", 5)
    assert a == b == c


def test_cache_set_rejects_non_dict_response():
    """set() must reject garbage payloads — never store None / list /
    string into Mongo where it would crash on next get()."""
    from services.chart_response_cache import ChartResponseCache, make_cache_key
    c = ChartResponseCache(db=None)
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    assert _run(c.set(key, None, ttl_seconds=60)) is False
    assert _run(c.set(key, "garbage", ttl_seconds=60)) is False
    assert _run(c.set(key, [1, 2, 3], ttl_seconds=60)) is False


def test_cache_set_with_zero_ttl_floors_to_one_second():
    """ttl_seconds=0 would make the entry expire BEFORE we store it.
    The cache floors to 1s so we never persist instantly-stale data."""
    from datetime import datetime, timezone
    from services.chart_response_cache import ChartResponseCache, make_cache_key
    c = ChartResponseCache(db=None)
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    _run(c.set(key, {"symbol": "SPY"}, ttl_seconds=0))
    mem_entry = c._mem.get(key)
    assert mem_entry is not None
    assert mem_entry["expires_at"] > datetime.now(timezone.utc)


def test_cache_in_memory_eviction_on_expiry():
    """When the in-memory entry's `expires_at` has passed, get() must
    return None (don't serve stale)."""
    from datetime import datetime, timedelta, timezone
    from services.chart_response_cache import ChartResponseCache, make_cache_key
    c = ChartResponseCache(db=None)
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    # Inject a manually-expired entry.
    c._mem[key] = {
        "response": {"symbol": "SPY"},
        "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    assert _run(c.get(key)) is None
    # And the expired entry was popped.
    assert key not in c._mem


# --------------------------------------------------------------------------
# 2. /chart endpoint — cache integration
# --------------------------------------------------------------------------

def test_chart_endpoint_calls_cache_get_first():
    """`get_chart_bars` must check `cache.get` BEFORE the live compute
    path. A cache hit must return the cached payload + stamp `cache:'hit'`
    without touching `_hybrid_data_service.get_bars`."""
    import inspect
    import routers.sentcom_chart as sc
    src = inspect.getsource(sc.get_chart_bars)
    assert "get_chart_response_cache" in src
    assert "cache.get(" in src
    # The hit branch must short-circuit BEFORE result = await
    # _hybrid_data_service.get_bars(...) — assert ordering.
    hit_idx = src.find('"cache": "hit"')
    live_idx = src.find("_hybrid_data_service.get_bars")
    assert hit_idx > 0
    assert live_idx > 0
    assert hit_idx < live_idx, (
        "cache.get hit branch must short-circuit BEFORE the live compute path"
    )


def test_chart_endpoint_writes_cache_on_miss():
    """On a cache miss + successful compute, the endpoint must write
    the response back so the next request hits the cache."""
    import inspect
    import routers.sentcom_chart as sc
    src = inspect.getsource(sc.get_chart_bars)
    assert "cache.set(" in src
    assert "chart_cache_ttl_for" in src
    miss_idx = src.find('"cache": "miss"')
    set_idx = src.find("cache.set(")
    assert set_idx > 0 and miss_idx > 0
    assert set_idx < miss_idx, (
        "cache.set must run before the response with cache:'miss' is returned"
    )


# --------------------------------------------------------------------------
# 3. /chart-tail endpoint — incremental refresh contract
# --------------------------------------------------------------------------

def test_chart_tail_endpoint_registered():
    """POST /chart-tail must be on the sentcom_chart router."""
    from routers.sentcom_chart import router
    paths = {r.path for r in router.routes}
    matches = [p for p in paths if p.endswith("/chart-tail")]
    assert matches, "/chart-tail endpoint missing from sentcom_chart router"


def test_chart_tail_slices_cached_bars_by_since():
    """Cache hit path: tail returns ONLY bars with time > since +
    matching indicator points + markers > since."""
    from services.chart_response_cache import (
        get_chart_response_cache, make_cache_key,
    )
    cache = get_chart_response_cache(db=None)

    # Seed a cache entry mimicking the full /chart response shape.
    full_payload = {
        "success": True,
        "symbol": "SPY",
        "timeframe": "5min",
        "bar_count": 4,
        "bars": [
            {"time": 1000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"time": 1300, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1100},
            {"time": 1600, "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1200},
            {"time": 1900, "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1300},
        ],
        "indicators": {
            "vwap": [
                {"time": 1000, "value": 100.0},
                {"time": 1300, "value": 100.5},
                {"time": 1600, "value": 101.0},
                {"time": 1900, "value": 101.5},
            ],
            "ema_20": [
                {"time": 1900, "value": 101.7},
            ],
        },
        "markers": [
            {"time": 1300, "position": "belowBar", "color": "green",
             "shape": "arrowUp", "text": "buy"},
            {"time": 1900, "position": "aboveBar", "color": "red",
             "shape": "arrowDown", "text": "sell"},
        ],
    }
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    _run(cache.set(key, full_payload, ttl_seconds=60))

    import routers.sentcom_chart as sc
    sc._hybrid_data_service = MagicMock()  # bypass the 503 guard

    # Ask for everything after time=1300 — should get bars at 1600 + 1900,
    # vwap @ 1600 + 1900, ema_20 @ 1900, marker @ 1900.
    result = _run(sc.get_chart_tail(
        symbol="SPY",
        timeframe="5min",
        since=1300,
        session="rth_plus_premarket",
        rth_only=None,
        cap=50,
    ))

    assert result["success"] is True
    assert result["from_cache"] is True
    assert result["bar_count"] == 2
    assert [b["time"] for b in result["bars"]] == [1600, 1900]
    assert [p["time"] for p in result["indicators"]["vwap"]] == [1600, 1900]
    assert [p["time"] for p in result["indicators"]["ema_20"]] == [1900]
    assert [m["time"] for m in result["markers"]] == [1900]
    assert result["latest_time"] == 1900


def test_chart_tail_returns_empty_bars_when_no_new_data():
    """If `since` >= the latest cached bar, the tail must return zero
    bars without erroring. The frontend uses this signal to skip
    setData/update entirely."""
    from services.chart_response_cache import (
        get_chart_response_cache, make_cache_key,
    )
    cache = get_chart_response_cache(db=None)
    full_payload = {
        "success": True,
        "symbol": "SPY",
        "timeframe": "5min",
        "bars": [{"time": 1000, "open": 1, "high": 2, "low": 1, "close": 1, "volume": 1}],
        "indicators": {},
        "markers": [],
    }
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    _run(cache.set(key, full_payload, ttl_seconds=60))

    import routers.sentcom_chart as sc
    sc._hybrid_data_service = MagicMock()
    result = _run(sc.get_chart_tail(
        symbol="SPY", timeframe="5min", since=2000,
        session="rth_plus_premarket", rth_only=None, cap=50,
    ))
    assert result["success"] is True
    assert result["bar_count"] == 0
    assert result["bars"] == []
    assert result["from_cache"] is True


def test_chart_tail_caps_returned_bars():
    """Even on a long client-side gap, tail responses must cap the
    number of returned bars at `cap` (default 50). Prevents the tail
    endpoint from accidentally turning into a full window dump."""
    from services.chart_response_cache import (
        get_chart_response_cache, make_cache_key,
    )
    cache = get_chart_response_cache(db=None)
    bars = [
        {"time": i, "open": 1, "high": 2, "low": 1, "close": 1, "volume": 1}
        for i in range(1, 201)
    ]
    full_payload = {
        "success": True, "symbol": "SPY", "timeframe": "5min",
        "bars": bars, "indicators": {}, "markers": [],
    }
    key = make_cache_key("SPY", "5min", "rth_plus_premarket", 5)
    _run(cache.set(key, full_payload, ttl_seconds=60))

    import routers.sentcom_chart as sc
    sc._hybrid_data_service = MagicMock()
    result = _run(sc.get_chart_tail(
        symbol="SPY", timeframe="5min", since=0,
        session="rth_plus_premarket", rth_only=None, cap=50,
    ))
    assert result["bar_count"] == 50
    # Cap takes the LAST 50, not the FIRST — operator wants freshest.
    assert result["bars"][0]["time"] == 151
    assert result["bars"][-1]["time"] == 200


# --------------------------------------------------------------------------
# 4. trade_execution.py — cache invalidation on fills
# --------------------------------------------------------------------------

def test_trade_execution_invalidates_chart_cache_on_fill():
    """When a trade fills successfully, trade_execution.execute_trade
    must invalidate the chart cache for that symbol so the new entry
    marker shows on the very next chart render — without waiting for
    the 30s/180s TTL to expire."""
    import inspect
    from services import trade_execution
    src = inspect.getsource(trade_execution)
    assert "chart_response_cache" in src
    assert ".invalidate(trade.symbol)" in src


# --------------------------------------------------------------------------
# 5. ChartPanel.jsx — stale-while-revalidate + smart polling guards
# --------------------------------------------------------------------------

def test_chart_panel_uses_stale_while_revalidate_pattern():
    """ChartPanel.jsx must:
      - Maintain an in-component bars cache (`lastBarsCacheRef`)
      - Hydrate state from cache on cacheKey change
      - Skip the loading spinner when cached data is present
      - Hit /chart-tail on smart-poll, not /chart
      - Pause polling when document.visibilityState !== 'visible'
      - Use a longer interval outside RTH"""
    panel_path = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "sentcom" / "panels" / "ChartPanel.jsx"
    src = panel_path.read_text()
    assert "lastBarsCacheRef" in src
    assert "/api/sentcom/chart-tail" in src
    assert "visibilityState" in src
    assert "isRthEt" in src
    # Smart polling must use 5_000 (RTH) or 30_000 (off-hours) — not the
    # legacy 30s blanket polling that re-fetched the full window.
    assert "5_000" in src
    # The cold-load spinner must only fire when there's no cache.
    assert "if (!cached) {\n      setLoading(true);" in src
