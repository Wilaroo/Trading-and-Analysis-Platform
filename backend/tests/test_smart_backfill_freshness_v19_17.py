"""
v19.17 — Bar-size-aware smart_backfill freshness gate (2026-04-30).

Pre-v19.17 the smart_backfill freshness gate was bar-size-agnostic:
``if days_behind <= freshness_days (default 2): skip``.

For "1 day" bars that meant the post-close run on day N would skip
refreshing because ``days_behind = 1`` (last bar = day N-1) — so day
N's just-finalised daily bar never got pulled until day N+3 when
the count finally crossed the 2-day threshold.

NVDA on Spark hit this exact path:
  - Last bar in Mongo: Apr 27 (Monday)
  - Apr 28 17:40 ET smart_backfill run: days_behind=1, skipped fresh
  - Apr 29 22:34 ET (no run since)
  - User noticed Apr 28 + 29 missing on the V5 ticker chart.

v19.17 adds ``_expected_latest_session_date(bar_size, now_dt)`` which
returns the exact session date we expect to have. The freshness gate
becomes ``last_dt.date() >= expected_session: skip`` — so post-close
on day N requires day N's bar; pre-close requires the prior weekday;
weekends require the prior Friday.

Tests pin:
  - The helper itself (every clock × bar_size combination).
  - The gate now correctly queues the Apr 28-style scenario.
  - Backwards-compat: intraday "fresh" cases still skip during RTH.
  - Weekend handling (Saturday at 10 AM expects Friday's bar).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------
# Helper — `_expected_latest_session_date` direct unit tests
# --------------------------------------------------------------------------

def _make_collector_stub():
    """Instantiate the collector without dragging Mongo/IB."""
    from services.ib_historical_collector import IBHistoricalCollector
    inst = IBHistoricalCollector.__new__(IBHistoricalCollector)
    inst._db = MagicMock()
    inst._data_col = MagicMock()
    return inst


def _et_to_utc(year, month, day, hour, minute=0):
    """Helper — build a UTC datetime that lands at ET (year, month, day,
    hour, minute) so the production code's `now_dt.astimezone(ET)`
    yields what we expect.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    et_dt = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))
    return et_dt.astimezone(timezone.utc)


# ---- "1 day" bar size ----

def test_expected_daily_post_close_weekday_returns_today():
    """Tuesday Apr 28 at 5:00 PM ET — daily bar for Apr 28 has just
    finalised. Expected = Apr 28."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 28, 17, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 28)


def test_expected_daily_pre_close_weekday_returns_prior_weekday():
    """Wednesday Apr 29 at 11:00 AM ET — Apr 29's bar is NOT yet
    available from IB (RTH still open). Expected = Apr 28 (prior
    weekday)."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 29, 11, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 28)


def test_expected_daily_premarket_returns_prior_weekday():
    """Tuesday Apr 28 at 7:00 AM ET — Apr 28's bar not yet available.
    Expected = Apr 27 (Monday)."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 28, 7, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 27)


def test_expected_daily_saturday_returns_friday():
    """Saturday Apr 25 at 10:00 AM ET. Expected = Apr 24 (Friday)."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 25, 10, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 24)


def test_expected_daily_sunday_returns_friday():
    """Sunday Apr 26 at 8:00 PM ET. Expected = Apr 24 (Friday)."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 26, 20, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 24)


def test_expected_daily_monday_morning_returns_friday():
    """Monday Apr 27 at 9:00 AM ET — Friday Apr 24 is the most recent
    finalised session."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 27, 9, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 24)


def test_expected_daily_monday_after_close_returns_monday():
    """Monday Apr 27 at 5:00 PM ET — Monday's bar finalised."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 27, 17, 0)
    assert inst._expected_latest_session_date("1 day", now) == date(2026, 4, 27)


# ---- "1 week" bar size ----

def test_expected_weekly_thursday_returns_prior_friday():
    """Thursday Apr 30 — most recent Friday is Apr 24."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 30, 14, 0)
    assert inst._expected_latest_session_date("1 week", now) == date(2026, 4, 24)


def test_expected_weekly_friday_returns_today():
    """Friday Apr 24 — today IS Friday."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 24, 17, 0)
    assert inst._expected_latest_session_date("1 week", now) == date(2026, 4, 24)


def test_expected_weekly_sunday_returns_friday():
    """Sunday Apr 26 — most recent Friday is Apr 24."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 26, 12, 0)
    assert inst._expected_latest_session_date("1 week", now) == date(2026, 4, 24)


# ---- intraday bar sizes ----

@pytest.mark.parametrize("bar_size", ["1 min", "5 mins", "15 mins", "30 mins", "1 hour"])
def test_expected_intraday_during_rth_returns_today(bar_size):
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 29, 11, 30)  # Wed RTH
    assert inst._expected_latest_session_date(bar_size, now) == date(2026, 4, 29)


@pytest.mark.parametrize("bar_size", ["1 min", "5 mins", "15 mins"])
def test_expected_intraday_saturday_returns_friday(bar_size):
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 25, 14, 0)  # Sat afternoon
    assert inst._expected_latest_session_date(bar_size, now) == date(2026, 4, 24)


# --------------------------------------------------------------------------
# Source-level pin — `_smart_backfill_sync` actually USES the helper
# --------------------------------------------------------------------------

def test_smart_backfill_uses_v19_17_gate():
    """If a future contributor reverts the freshness gate to the
    bar-size-agnostic ``days_behind <= freshness_days``, this test
    fires before we ship.
    """
    import os
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "services", "ib_historical_collector.py"
    )
    with open(src_path) as f:
        src = f.read()
    assert "_expected_latest_session_date" in src
    assert "is_fresh_v19_17 = last_session >= expected_session" in src
    # Guard against the OLD gate being silently restored:
    # The exact string `if days_behind <= freshness_days:` (with that
    # specific colon-terminated form) was the bug. Make sure it doesn't
    # come back as the primary gate.
    assert "if days_behind <= freshness_days:" not in src, (
        "v19.17 regression — the old bar-size-agnostic freshness gate "
        "is back in _smart_backfill_sync. Daily bars will start "
        "missing yesterday's session again."
    )


# --------------------------------------------------------------------------
# Behavioural regression — pin the exact NVDA Apr 28-style scenario
# --------------------------------------------------------------------------

def test_apr28_post_close_run_with_apr27_last_bar_is_NOT_fresh():
    """Reproduces the bug that caused the NVDA report on Spark.

    Last NVDA "1 day" bar in Mongo = Apr 27 (Monday).
    smart_backfill runs at Apr 28 17:40 ET (Tuesday after close).
    Pre-v19.17: days_behind=1 ≤ freshness_days=2 → skipped fresh →
    Apr 28's bar never collected.
    Post-v19.17: expected_session=Apr 28 > last_session=Apr 27 →
    NOT fresh → queued for fetch.
    """
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 28, 17, 40)  # 5:40 PM ET Tuesday
    expected = inst._expected_latest_session_date("1 day", now)
    last_session = date(2026, 4, 27)
    assert expected == date(2026, 4, 28)
    assert last_session < expected, (
        "v19.17 must NOT treat Apr 27 as fresh on Apr 28 evening — "
        "that's the exact bug that caused 2 missing trading days "
        "for NVDA on Spark."
    )


def test_post_close_run_with_today_last_bar_IS_fresh():
    """Inverse of the above: if last bar IS today's, smart_backfill
    must skip as fresh (no double-fetch waste)."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 28, 17, 40)
    expected = inst._expected_latest_session_date("1 day", now)
    last_session = date(2026, 4, 28)
    assert last_session >= expected


def test_intraday_during_rth_with_today_last_bar_IS_fresh():
    """Intraday RTH happy path — bars from today's session are 'fresh'."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 29, 14, 0)  # 2 PM ET Wednesday
    expected = inst._expected_latest_session_date("5 mins", now)
    last_session = date(2026, 4, 29)
    assert last_session >= expected


def test_intraday_during_rth_with_yesterday_last_bar_is_NOT_fresh():
    """Intraday RTH stale path — if last 5-min bar is yesterday's,
    we must queue a fresh pull."""
    inst = _make_collector_stub()
    now = _et_to_utc(2026, 4, 29, 14, 0)
    expected = inst._expected_latest_session_date("5 mins", now)
    last_session = date(2026, 4, 28)
    assert last_session < expected
