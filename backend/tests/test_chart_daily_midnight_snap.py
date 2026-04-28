"""
Regression tests for the 1day timestamp-snap behaviour shipped 2026-04-28d.

IB returns daily bars with the session-open timestamp (e.g. "2026-03-25T13:30:00Z"
= 9:30am ET = 13:30 UTC). lightweight-charts then treated those as intraday
ticks and emitted "1:30 PM" labels on the daily-chart x-axis. The fix snaps
each daily bar's `time` to midnight UTC of its calendar day so the chart
only sees one bar per day at a clean 00:00:00 UTC boundary.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock
import pytest

from routers import sentcom_chart


class _FakeBarsResult:
    def __init__(self, bars, success=True):
        self.success = success
        self.bars = bars
        self.error = None
        self.stale = False
        self.stale_reason = None
        self.latest_available_date = None
        self.partial = False
        self.coverage = None


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset injected service after each test so tests don't bleed."""
    yield
    sentcom_chart._hybrid_data_service = None
    sentcom_chart._db = None


def _seed_service(bars):
    svc = MagicMock()
    svc.TIMEFRAMES = {"1day": {"ib_bar_size": "1 day"}}
    svc.get_bars = AsyncMock(return_value=_FakeBarsResult(bars))
    svc.fetch_latest_session_bars = AsyncMock(return_value={"success": False})
    sentcom_chart._hybrid_data_service = svc


@pytest.mark.asyncio
async def test_daily_bars_snap_to_midnight_utc():
    """Each daily bar's `time` becomes midnight UTC of its calendar day."""
    # 9:30am ET = 13:30 UTC (during EDT)
    bars = [
        {"timestamp": "2026-03-23T13:30:00Z", "open": 100, "high": 102, "low": 99,  "close": 101, "volume": 1_000_000},
        {"timestamp": "2026-03-24T13:30:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1_100_000},
        {"timestamp": "2026-03-25T13:30:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1_200_000},
    ]
    _seed_service(bars)

    out = await sentcom_chart.get_chart_bars(symbol="TSLA", timeframe="1day", days=30)
    assert out["success"] is True
    assert out["bar_count"] == 3
    for b in out["bars"]:
        # Every kept bar lands at midnight UTC
        assert b["time"] % 86400 == 0
        # Calendar day matches the original timestamp
        d = datetime.fromtimestamp(b["time"], tz=timezone.utc)
        assert d.hour == 0 and d.minute == 0 and d.second == 0


@pytest.mark.asyncio
async def test_daily_dedup_collapses_two_bars_on_same_day():
    """If IB returns two daily rows landing on the same calendar day
    (e.g. 9:30am and 16:00 same date) we keep only the first."""
    bars = [
        {"timestamp": "2026-03-25T13:30:00Z", "open": 100, "high": 102, "low": 99,  "close": 101, "volume": 1_000_000},
        {"timestamp": "2026-03-25T20:00:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 500_000},
        {"timestamp": "2026-03-26T13:30:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 900_000},
    ]
    _seed_service(bars)

    out = await sentcom_chart.get_chart_bars(symbol="TSLA", timeframe="1day", days=30)
    assert out["success"] is True
    # 3 rows -> 2 unique calendar days
    assert out["bar_count"] == 2


@pytest.mark.asyncio
async def test_intraday_timestamps_unchanged():
    """5min bars must NOT be snapped — only daily."""
    bars = [
        {"timestamp": "2026-03-25T13:30:00Z", "open": 100, "high": 102, "low": 99,  "close": 101, "volume": 100_000},
        {"timestamp": "2026-03-25T13:35:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 110_000},
    ]
    _seed_service(bars)
    sentcom_chart._hybrid_data_service.TIMEFRAMES = {"5min": {"ib_bar_size": "5 mins"}}
    sentcom_chart._hybrid_data_service.fetch_latest_session_bars = AsyncMock(return_value={"success": False})

    # Use session=all so the RTH filter doesn't drop anything
    out = await sentcom_chart.get_chart_bars(symbol="TSLA", timeframe="5min", days=1, session="all")
    assert out["success"] is True
    # First bar's time is 13:30 UTC = 48600 seconds past midnight
    times = [b["time"] for b in out["bars"]]
    assert any(t % 86400 != 0 for t in times), "5min bars should KEEP their intraday timestamps"
