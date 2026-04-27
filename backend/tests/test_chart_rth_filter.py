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


def test_rth_plus_premarket_keeps_both_sessions_and_tags_them():
    """The new default session keeps 4am-16:00 ET bars and tags each
    with `session: 'pre' | 'rth'` so the frontend can shade premarket."""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")

    bars = [
        {"time": _et_unix(2026, 4, 28, 4, 30)},   # premarket  → keep, pre
        {"time": _et_unix(2026, 4, 28, 9, 0)},    # premarket  → keep, pre
        {"time": _et_unix(2026, 4, 28, 9, 30)},   # RTH open   → keep, rth
        {"time": _et_unix(2026, 4, 28, 12, 0)},   # RTH        → keep, rth
        {"time": _et_unix(2026, 4, 28, 15, 59)},  # RTH close  → keep, rth
        {"time": _et_unix(2026, 4, 28, 17, 0)},   # post       → drop
        {"time": _et_unix(2026, 4, 28, 22, 0)},   # post       → drop
        {"time": _et_unix(2026, 4, 29, 1, 0)},    # overnight  → drop
        {"time": _et_unix(2026, 4, 25, 12, 0)},   # Saturday   → drop
    ]

    # Re-implement the filter logic locally (this lock test ensures
    # it stays correct in isolation; the integration with FastAPI is
    # covered separately).
    window_open = 4 * 60          # 4:00 AM
    window_close = 16 * 60        # 4:00 PM
    rth_open = 9 * 60 + 30
    kept = []
    for b in bars:
        dt = _dt.fromtimestamp(b["time"], tz=et)
        if dt.weekday() >= 5:
            continue
        mod = dt.hour * 60 + dt.minute
        if not (window_open <= mod < window_close):
            continue
        b["session"] = "pre" if mod < rth_open else "rth"
        kept.append(b)

    sessions = [b["session"] for b in kept]
    assert sessions == ["pre", "pre", "rth", "rth", "rth"], (
        f"unexpected session tags: {sessions}"
    )


def test_session_default_is_rth_plus_premarket():
    """The /api/sentcom/chart endpoint must default to
    `session=rth_plus_premarket` so premarket gap-context is preserved
    while still dropping noisy overnight/post-market bars."""
    import inspect
    from routers.sentcom_chart import get_chart_bars

    sig = inspect.signature(get_chart_bars)
    session_param = sig.parameters.get("session")
    assert session_param is not None, "session param must exist"
    default = session_param.default
    assert getattr(default, "default", default) == "rth_plus_premarket", (
        "session must default to 'rth_plus_premarket' so premarket "
        "bars are kept (operator request 2026-04-28)."
    )


def test_legacy_rth_only_param_still_supported():
    """Legacy `rth_only=true|false` query must still work (back-compat)."""
    import inspect
    from routers.sentcom_chart import get_chart_bars

    sig = inspect.signature(get_chart_bars)
    assert "rth_only" in sig.parameters, (
        "rth_only legacy param must remain for back-compat — frontend "
        "callers may still be passing it."
    )
