"""v19.34.203 — earnings_calendar persistence (R0)."""
from datetime import datetime, timezone, timedelta

from services.earnings_service import _normalize_earnings_row


def test_normalize_basic():
    doc = _normalize_earnings_row({
        "symbol": "amd", "date": "2026-06-15", "hour": "amc",
        "epsEstimate": 1.2, "quarter": 2, "year": 2026,
    })
    assert doc["symbol"] == "AMD"
    assert doc["date"] == "2026-06-15T12:00:00+00:00"
    assert doc["date_only"] == "2026-06-15"
    assert doc["hour"] == "amc"
    assert doc["source"] == "finnhub"


def test_normalize_rejects_missing():
    assert _normalize_earnings_row({"symbol": "AMD"}) is None
    assert _normalize_earnings_row({"date": "2026-06-15"}) is None
    assert _normalize_earnings_row({"symbol": "", "date": ""}) is None


def test_future_earnings_sorts_after_now():
    now = datetime.now(timezone.utc)
    future = (now + timedelta(days=7)).date().isoformat()
    doc = _normalize_earnings_row({"symbol": "X", "date": future})
    assert doc["date"] >= now.isoformat()


def test_same_day_format():
    today = datetime.now(timezone.utc).date().isoformat()
    doc = _normalize_earnings_row({"symbol": "X", "date": today})
    assert doc["date"] == f"{today}T12:00:00+00:00"


def test_within_14d_window():
    now = datetime.now(timezone.utc)
    d = (now + timedelta(days=10)).date().isoformat()
    doc = _normalize_earnings_row({"symbol": "X", "date": d})
    upper = (now + timedelta(days=14)).isoformat()
    assert now.isoformat() <= doc["date"] <= upper
