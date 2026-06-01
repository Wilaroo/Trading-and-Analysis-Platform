"""
v19.34.197 — chart cold-load latency fix.

Diagnosis (read-only diag_chart_latency.py on the live DGX): cold intraday
/chart loads took 18-21s while daily took <300ms. Root cause: the per-miss
live pusher-RPC merge (rpc.latest_bars, an on-demand IB historical request
for quote-subscribed symbols) blocked the whole chart load with NO timeout.

Fixes:
  1. routers/sentcom_chart.py — time-bound the live merge with
     asyncio.wait_for(CHART_LIVE_MERGE_TIMEOUT_S, default 3s); serve the
     historical window on timeout (chart-tail WS backfills live bars).
  2. services/chart_response_cache.chart_cache_ttl_for — env-tunable; intraday
     default bumped 30s -> 60s (CHART_CACHE_TTL_INTRADAY_S / _DAILY_S) to
     reduce cold-miss frequency. This file tests (2).
"""
import importlib

import services.chart_response_cache as crc


def _reload():
    importlib.reload(crc)
    return crc.chart_cache_ttl_for


def test_default_intraday_60_daily_180(monkeypatch):
    monkeypatch.delenv("CHART_CACHE_TTL_INTRADAY_S", raising=False)
    monkeypatch.delenv("CHART_CACHE_TTL_DAILY_S", raising=False)
    # v19.34.198 — disable the session-aware rollover clamp so this test
    # pins the *base* TTL contract deterministically (clamp is covered in
    # test_v19_34_198_session_aware_ttl.py).
    monkeypatch.setenv("CHART_CACHE_SESSION_AWARE", "false")
    ttl = crc.chart_cache_ttl_for
    assert ttl("5min") == 60
    assert ttl("1min") == 60
    assert ttl("15min") == 60
    assert ttl("1day") == 180
    assert ttl("1week") == 180
    assert ttl("") == 60  # unknown/empty → intraday default


def test_env_override_intraday(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "120")
    monkeypatch.setenv("CHART_CACHE_SESSION_AWARE", "false")
    ttl = crc.chart_cache_ttl_for
    assert ttl("5min") == 120
    assert ttl("1day") == 180  # daily untouched


def test_env_override_daily(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_DAILY_S", "600")
    monkeypatch.setenv("CHART_CACHE_SESSION_AWARE", "false")
    ttl = crc.chart_cache_ttl_for
    assert ttl("1day") == 600
    assert ttl("5min") == 60


def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "not-a-number")
    monkeypatch.setenv("CHART_CACHE_TTL_DAILY_S", "-5")  # non-positive → default
    monkeypatch.setenv("CHART_CACHE_SESSION_AWARE", "false")
    ttl = crc.chart_cache_ttl_for
    assert ttl("5min") == 60
    assert ttl("1day") == 180
