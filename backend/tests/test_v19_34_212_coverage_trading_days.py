"""v19.34.212 — chart coverage uses TRADING days, not calendar days.

Regression guard for the AIQ "70% coverage" report: RTH-complete 5-min data
was capped at ~70% because `expected = calendar_days * 78` counted weekends/
holidays as sessions.
"""
from datetime import datetime, timedelta, timezone

from services.hybrid_data_service import (
    _trading_days, _expected_bars, _BARS_PER_RTH_SESSION,
)


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_trading_days_excludes_weekends():
    # Mon 2026-06-01 .. Sun 2026-06-07 inclusive -> 5 weekdays
    assert _trading_days(_utc(2026, 6, 1), _utc(2026, 6, 7)) == 5
    # Sat..Sun -> 0
    assert _trading_days(_utc(2026, 6, 6), _utc(2026, 6, 7)) == 0
    # single weekday -> 1
    assert _trading_days(_utc(2026, 6, 3), _utc(2026, 6, 3)) == 1


def test_expected_bars_per_timeframe():
    s, e = _utc(2026, 6, 1), _utc(2026, 6, 5)  # Mon..Fri = 5 sessions
    assert _expected_bars("5min", s, e) == 5 * 78
    assert _expected_bars("1min", s, e) == 5 * 390
    assert _expected_bars("15min", s, e) == 5 * 26
    assert _expected_bars("1hour", s, e) == 5 * 7
    assert _expected_bars("1day", s, e) == 5 * 1
    # unknown timeframe falls back to 5-min density
    assert _expected_bars("3min", s, e) == 5 * 78


def test_rth_complete_data_reads_full_not_seventy():
    # 45-calendar-day window ~ 32 trading days. Fully-backfilled RTH 5-min data
    # (~78 bars/session) must read ~100%, NOT ~70%.
    end = _utc(2026, 6, 2)
    start = end - timedelta(days=45)
    td = _trading_days(start, end)
    bars = td * 78
    expected = _expected_bars("5min", start, end)
    coverage = min(bars / expected, 1.0)
    assert coverage == 1.0
    # the OLD calendar-day formula would have produced ~0.71
    old = bars / (45 * 78)
    assert old < 0.75


def test_expected_never_zero():
    s = e = _utc(2026, 6, 6)  # a Saturday -> 0 weekdays
    assert _expected_bars("5min", s, e) >= 1
    assert set(_BARS_PER_RTH_SESSION) == {"1min", "5min", "15min", "1hour", "1day"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
