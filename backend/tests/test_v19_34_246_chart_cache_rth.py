"""
v19.34.246 — chart-cache RTH freshness ceiling.

Bug: CHART_CACHE_TTL_INTRADAY_S=28800 (8h) cached the MAIN SentCom chart's
full-window response for the entire session, so the live chart froze at the
first fetch (IBM stuck at 10:17, no newer candles). The session-aware rollover
clamp only stopped the cache crossing INTO the next session — it didn't keep
the chart fresh DURING RTH.

Fix: during the active session (04:00-20:00 ET, when bars form), cap the
intraday TTL to CHART_CACHE_RTH_MAX_S (default 60s); the long TTL still applies
overnight for instant revisits.
"""
import os
from datetime import datetime, timezone

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.chart_response_cache import (  # noqa: E402
    chart_cache_ttl_for, _is_session_active_now,
)

# weekday RTH / overnight / weekend reference instants (June 2026 = EDT, UTC-4)
RTH = datetime(2026, 6, 3, 15, 0, tzinfo=timezone.utc)        # Wed 11:00 ET
OVERNIGHT = datetime(2026, 6, 3, 6, 0, tzinfo=timezone.utc)   # Wed 02:00 ET
WEEKEND = datetime(2026, 6, 6, 15, 0, tzinfo=timezone.utc)    # Sat 11:00 ET


def _set_env():
    os.environ["CHART_CACHE_TTL_INTRADAY_S"] = "28800"  # operator's 8h
    os.environ.pop("CHART_CACHE_RTH_MAX_S", None)        # use default 60
    os.environ["CHART_CACHE_SESSION_AWARE"] = "true"


def test_session_active_detection():
    assert _is_session_active_now(RTH) is True
    assert _is_session_active_now(OVERNIGHT) is False
    assert _is_session_active_now(WEEKEND) is False


def test_intraday_capped_during_rth():
    _set_env()
    # 8h env, but RTH ceiling caps it to 60s — the live chart stays fresh.
    assert chart_cache_ttl_for("5min", now=RTH) <= 60


def test_intraday_long_overnight():
    _set_env()
    # Overnight: no new bars, long TTL is fine for instant revisits (clamped
    # only by the rollover, which is hours away → well above the 60s ceiling).
    assert chart_cache_ttl_for("5min", now=OVERNIGHT) > 60


def test_rth_ceiling_env_override():
    _set_env()
    os.environ["CHART_CACHE_RTH_MAX_S"] = "30"
    try:
        assert chart_cache_ttl_for("1min", now=RTH) <= 30
    finally:
        os.environ.pop("CHART_CACHE_RTH_MAX_S", None)


def test_daily_unaffected_by_rth_ceiling():
    _set_env()
    os.environ["CHART_CACHE_TTL_DAILY_S"] = "180"
    assert chart_cache_ttl_for("1day", now=RTH) == 180
