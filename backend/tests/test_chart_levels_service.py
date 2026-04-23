"""
Tests for services/chart_levels_service — PDH/PDL/PDC/PMH/PML computation.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.chart_levels_service import compute_chart_levels, get_chart_levels


def _bar(days_ago, high, low, close, open_=None):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "timestamp": ts,
        "high": high,
        "low": low,
        "close": close,
        "open": open_ if open_ is not None else close,
    }


def test_compute_empty_bars_returns_nulls():
    result = compute_chart_levels([])
    assert result == {"pdh": None, "pdl": None, "pdc": None, "pmh": None, "pml": None}


def test_compute_single_bar_returns_nulls_for_pdh_pdl():
    # A single bar is "today" — no previous day to reference
    bars = [_bar(0, 100, 95, 98)]
    r = compute_chart_levels(bars)
    assert r["pdh"] is None
    assert r["pdl"] is None


def test_pdh_pdl_pdc_from_second_to_last_bar():
    # bars ordered chronologically; second-to-last is "yesterday"
    bars = [
        _bar(3, 99, 94, 96),   # older
        _bar(1, 102, 97, 100), # yesterday
        _bar(0, 104, 99, 101), # today
    ]
    r = compute_chart_levels(bars)
    assert r["pdh"] == 102
    assert r["pdl"] == 97
    assert r["pdc"] == 100


def test_pmh_pml_from_previous_month_only():
    """Last month's bars should define PMH/PML, current month's excluded."""
    now = datetime.now(timezone.utc)
    # Generate 10 bars spanning previous month + current month
    bars = []
    # Previous month: use a date exactly 40 days ago (always previous month)
    prev_dt = now - timedelta(days=40)
    bars.append({
        "timestamp": prev_dt.isoformat(),
        "high": 110, "low": 90, "close": 100,
    })
    bars.append({
        "timestamp": (prev_dt + timedelta(days=1)).isoformat(),
        "high": 115, "low": 88, "close": 105,
    })
    # Current month
    bars.append({
        "timestamp": (now - timedelta(days=2)).isoformat(),
        "high": 200, "low": 50, "close": 150,
    })
    bars.append({
        "timestamp": (now - timedelta(days=1)).isoformat(),
        "high": 202, "low": 48, "close": 151,
    })
    bars.append({
        "timestamp": now.isoformat(),
        "high": 205, "low": 51, "close": 152,
    })

    r = compute_chart_levels(bars)
    # PMH from the previous-month bars (110 or 115)
    assert r["pmh"] == 115
    assert r["pml"] == 88
    # Current-month outliers (200/50) must not leak in
    assert r["pmh"] != 205
    assert r["pml"] != 48


def test_pmh_pml_none_when_only_current_month_data():
    """All bars within current month → no previous month to reference."""
    now = datetime.now(timezone.utc)
    bars = [
        _bar(0, 105, 95, 100),
        _bar(1, 106, 94, 101),
    ]
    r = compute_chart_levels(bars)
    assert r["pmh"] is None
    assert r["pml"] is None


def test_malformed_timestamps_skipped():
    bars = [
        {"timestamp": "not-a-date", "high": 100, "low": 90, "close": 95},
        _bar(1, 102, 97, 100),
        _bar(0, 104, 99, 101),
    ]
    r = compute_chart_levels(bars)
    assert r["pdh"] == 102
    assert r["pdl"] == 97


def test_numeric_timestamp_seconds_supported():
    """Unix seconds."""
    now_ts = datetime.now(timezone.utc).timestamp()
    bars = [
        {"timestamp": now_ts - 2 * 86400, "high": 100, "low": 95, "close": 98},
        {"timestamp": now_ts - 86400,     "high": 103, "low": 97, "close": 101},
        {"timestamp": now_ts,             "high": 105, "low": 99, "close": 102},
    ]
    r = compute_chart_levels(bars)
    assert r["pdh"] == 103
    assert r["pdl"] == 97


def test_get_chart_levels_none_db_returns_empty():
    r = get_chart_levels(None, "AAPL")
    assert r["pdh"] is None
    assert r["pdl"] is None


def test_get_chart_levels_empty_symbol():
    class _DB:
        def __getitem__(self, _): raise RuntimeError("should not be called")
    r = get_chart_levels(_DB(), "")
    assert r["pdh"] is None


def test_get_chart_levels_roundtrip_via_fake_db():
    class _Cur:
        def __init__(self, docs): self._docs = docs
        def sort(self, *_): return self
        def __iter__(self): return iter(self._docs)
    class _Col:
        def __init__(self, docs): self._docs = docs
        def find(self, q, proj=None): return _Cur(self._docs)
    class _DB:
        def __init__(self, docs): self._c = _Col(docs)
        def __getitem__(self, name): return self._c

    bars = [
        _bar(3, 99, 94, 96),
        _bar(1, 102, 97, 100),
        _bar(0, 104, 99, 101),
    ]
    db = _DB(bars)
    r = get_chart_levels(db, "AAPL")
    assert r["pdh"] == 102
    assert r["pdl"] == 97
    assert r["pdc"] == 100


def test_high_level_dict_shape_stable():
    """Contract: every response must have these 5 keys."""
    r = compute_chart_levels([])
    assert set(r.keys()) == {"pdh", "pdl", "pdc", "pmh", "pml"}
