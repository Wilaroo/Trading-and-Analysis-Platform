"""
v19.34.198 — session-aware chart cache TTL (5 PM ET rollover clamp).

Operator runs a large CHART_CACHE_TTL_INTRADAY_S (e.g. 28800 = 8h) so
same-session chart revisits are instant. A fixed 8h TTL set late in the
session would bleed the closing skeleton into the next premarket open.
The fix clamps every *intraday* entry so it never outlives the next
5 PM ET rollover, while daily TTL and the disable flag are untouched.

These tests inject an explicit `now` (ET-anchored) so they're
deterministic regardless of when the suite runs.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import services.chart_response_cache as crc

ET = ZoneInfo("America/New_York")


def _et(hour, minute=0):
    """A UTC datetime corresponding to today's ET hour:minute."""
    now_et = datetime.now(ET).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return now_et.astimezone(timezone.utc)


def test_seconds_until_rollover_basic():
    # 10:00 ET -> 7h until 5 PM ET.
    assert crc._seconds_until_session_rollover(_et(10), 17) == 7 * 3600
    # 3:55 PM ET -> 1h 5m.
    assert crc._seconds_until_session_rollover(_et(15, 55), 17) == 65 * 60
    # After rollover (8 PM ET) -> next day's 5 PM (21h away).
    assert crc._seconds_until_session_rollover(_et(20), 17) == 21 * 3600


def test_intraday_clamped_to_rollover(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "28800")  # 8h
    monkeypatch.delenv("CHART_CACHE_SESSION_AWARE", raising=False)
    # Mid-session: 8h base but only 7h until 5 PM -> clamped to 7h.
    assert crc.chart_cache_ttl_for("5min", now=_et(10)) == 7 * 3600
    # Near close: clamped to the small remaining window.
    assert crc.chart_cache_ttl_for("1min", now=_et(16, 30)) == 30 * 60


def test_intraday_uses_base_when_rollover_far(monkeypatch):
    # Just after rollover the next boundary is ~24h away, so the 8h base
    # TTL is the binding cap (not the rollover).
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "28800")
    monkeypatch.delenv("CHART_CACHE_SESSION_AWARE", raising=False)
    assert crc.chart_cache_ttl_for("5min", now=_et(17, 1)) == 28800


def test_daily_never_clamped(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_DAILY_S", "180")
    monkeypatch.delenv("CHART_CACHE_SESSION_AWARE", raising=False)
    # Daily ignores the rollover clamp entirely.
    assert crc.chart_cache_ttl_for("1day", now=_et(15, 59)) == 180


def test_disable_flag_restores_flat_ttl(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "28800")
    monkeypatch.setenv("CHART_CACHE_SESSION_AWARE", "false")
    # Clamp disabled -> full base TTL even at 3:55 PM.
    assert crc.chart_cache_ttl_for("5min", now=_et(15, 55)) == 28800


def test_custom_rollover_hour(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "28800")
    monkeypatch.setenv("CHART_CACHE_ROLLOVER_HOUR_ET", "16")  # 4 PM
    monkeypatch.delenv("CHART_CACHE_SESSION_AWARE", raising=False)
    # 10:00 ET -> 6h until 4 PM ET.
    assert crc.chart_cache_ttl_for("5min", now=_et(10)) == 6 * 3600


def test_floor_prevents_zero_ttl(monkeypatch):
    monkeypatch.setenv("CHART_CACHE_TTL_INTRADAY_S", "28800")
    monkeypatch.delenv("CHART_CACHE_SESSION_AWARE", raising=False)
    # One second before rollover -> floor of 30s, never 0/negative.
    one_sec_before = _et(17) - timedelta(seconds=1)
    assert crc.chart_cache_ttl_for("5min", now=one_sec_before) == 30
