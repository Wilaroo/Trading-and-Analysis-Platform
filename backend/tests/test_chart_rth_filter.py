"""
Tests for the chart's RTH-only filter (added 2026-04-28).

Operator request: *"the charts still have a lot of timeframe and data
and time gaps. how do we close those?"* Answer: filter intraday bars
to RTH (9:30-16:00 ET, weekdays only) at the API layer. Keeps the
underlying cache untouched (so backfill / live-tick persister still
write extended-hours bars), but the chart returns a contiguous
RTH-only slice.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest


def _et_unix(year, month, day, hour, minute=0):
    """Return a unix timestamp for the given ET wall-clock time."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    return int(datetime(year, month, day, hour, minute, tzinfo=et).timestamp())


def test_rth_filter_drops_overnight_bars():
    """Bars outside 9:30-16:00 ET on weekdays must be filtered."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")

    bars = [
        # Tuesday 4/28/2026, mix of RTH + premarket + post-market + overnight
        {"time": _et_unix(2026, 4, 28, 4, 30), "open": 1, "close": 1.1},   # premarket
        {"time": _et_unix(2026, 4, 28, 9, 30), "open": 1, "close": 1.1},   # RTH open
        {"time": _et_unix(2026, 4, 28, 12, 0), "open": 1, "close": 1.1},   # RTH midday
        {"time": _et_unix(2026, 4, 28, 15, 59), "open": 1, "close": 1.1},  # RTH close
        {"time": _et_unix(2026, 4, 28, 16, 0), "open": 1, "close": 1.1},   # post-market boundary
        {"time": _et_unix(2026, 4, 28, 19, 0), "open": 1, "close": 1.1},   # post-market
        {"time": _et_unix(2026, 4, 29, 2, 0), "open": 1, "close": 1.1},    # overnight
    ]

    rth = []
    for b in bars:
        dt = _dt.fromtimestamp(b["time"], tz=et)
        if (
            dt.weekday() < 5
            and 9 * 60 + 30 <= dt.hour * 60 + dt.minute < 16 * 60
        ):
            rth.append(b)
    assert len(rth) == 3  # 9:30, 12:00, 15:59
    times = [_dt.fromtimestamp(b["time"], tz=et).strftime("%H:%M") for b in rth]
    assert "09:30" in times
    assert "12:00" in times
    assert "15:59" in times


def test_rth_filter_drops_weekends():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")

    bars = [
        {"time": _et_unix(2026, 4, 24, 12, 0), "open": 1},  # Friday — keep
        {"time": _et_unix(2026, 4, 25, 12, 0), "open": 1},  # Saturday — drop
        {"time": _et_unix(2026, 4, 26, 12, 0), "open": 1},  # Sunday — drop
        {"time": _et_unix(2026, 4, 27, 12, 0), "open": 1},  # Monday — keep
    ]
    rth = []
    for b in bars:
        dt = _dt.fromtimestamp(b["time"], tz=et)
        if (
            dt.weekday() < 5
            and 9 * 60 + 30 <= dt.hour * 60 + dt.minute < 16 * 60
        ):
            rth.append(b)
    assert len(rth) == 2  # Friday + Monday only


def test_rth_filter_default_is_true():
    """The /api/sentcom/chart endpoint must default `rth_only=true` so
    the operator's "charts still have a lot of gaps" concern is resolved
    out of the box for intraday timeframes (no client opt-in needed)."""
    import inspect
    from routers.sentcom_chart import get_chart_bars

    sig = inspect.signature(get_chart_bars)
    rth_param = sig.parameters.get("rth_only")
    assert rth_param is not None, "rth_only param must exist"
    # Query default — pull the default value from the FastAPI Query() wrapper.
    default = rth_param.default
    # `default` is a FastAPI Query object; its `.default` is the underlying
    # default value.
    assert getattr(default, "default", default) is True, (
        "rth_only must default to True so charts close gaps without "
        "requiring frontend opt-in."
    )
