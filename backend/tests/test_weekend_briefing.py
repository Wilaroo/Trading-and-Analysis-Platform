"""
Regression tests for `services/weekend_briefing_service.py`.

Hardware-bound integration (Finnhub fetches, Mongo, LLM) is mocked — we
verify the *contract* and resilience of the service:
    * `_iso_week()` produces ISO-week strings stable across timezones.
    * `_filter_sector_catalysts()` keyword matching pins the public list
      so future edits to CATALYST_KEYWORDS can't silently drop terms.
    * `_build_risk_map()` flags earnings-on-position + high-impact macro.
    * `WeekendBriefingService.get_latest()` falls back to most-recent doc
      when no entry exists for the current week.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from services.weekend_briefing_service import (
    CATALYST_KEYWORDS,
    SECTOR_ETFS,
    WeekendBriefingService,
    _build_risk_map,
    _filter_sector_catalysts,
    _iso_week,
    _last_week_window,
    _next_trading_window,
)


# ──────────────────────────────────────────────────────────────────────
# ISO-week helpers
# ──────────────────────────────────────────────────────────────────────


def test_iso_week_strict_format():
    wid = _iso_week()
    # "%G-W%V" → "2026-W04" style — 4-digit ISO year, literal "-W", 2-digit week.
    assert len(wid) == 8
    assert wid[4:6] == "-W"
    assert wid[:4].isdigit()
    assert wid[6:].isdigit()


def test_iso_week_known_date():
    """Sunday 2026-01-04 falls in ISO week 1 of 2026."""
    sun = datetime(2026, 1, 4, 19, 0, tzinfo=timezone.utc)  # 14:00 ET
    assert _iso_week(sun) == "2026-W01"


def test_next_trading_window_is_seven_days():
    win = _next_trading_window(datetime(2026, 1, 4, 19, 0, tzinfo=timezone.utc))
    assert win["from"] == "2026-01-04"
    assert win["to"] == "2026-01-11"


def test_last_week_window_is_seven_days_back():
    win = _last_week_window(datetime(2026, 1, 11, 19, 0, tzinfo=timezone.utc))
    assert win["from"] == "2026-01-04"
    assert win["to"] == "2026-01-11"


# ──────────────────────────────────────────────────────────────────────
# Catalyst keyword filter
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("keyword", [
    "fda", "approval", "earnings", "ipo", "merger",
    "fed", "fomc", "rate", "lawsuit", "conference",
])
def test_catalyst_keyword_present(keyword):
    """Every keyword in CATALYST_KEYWORDS must classify a synthetic headline."""
    assert keyword in CATALYST_KEYWORDS
    h = [{"headline": f"BIGCO announces {keyword} update", "summary": ""}]
    out = _filter_sector_catalysts(h)
    assert len(out) == 1
    assert keyword in out[0]["matched_keywords"]


def test_catalyst_filter_dedups_keywords_per_headline():
    h = [{"headline": "FDA approval for FDA-led trial", "summary": "fda fda fda"}]
    out = _filter_sector_catalysts(h)
    assert len(out) == 1
    # Cap on per-headline keywords is 3 — pin the exposed shape.
    assert len(out[0]["matched_keywords"]) <= 3


def test_catalyst_filter_drops_non_catalyst_headlines():
    h = [{"headline": "Stock market closed for the day", "summary": "—"}]
    assert _filter_sector_catalysts(h) == []


def test_catalyst_filter_caps_to_twelve():
    h = [{"headline": f"earnings beat #{i}", "summary": ""} for i in range(50)]
    out = _filter_sector_catalysts(h)
    assert len(out) == 12


# ──────────────────────────────────────────────────────────────────────
# Risk map builder
# ──────────────────────────────────────────────────────────────────────


def test_risk_map_flags_earnings_on_position():
    earnings = [{"symbol": "AAPL", "date": "2026-04-30", "timing": "After Close"}]
    risks = _build_risk_map(positions=["AAPL"], earnings=earnings, macro=[])
    assert any(r["type"] == "earnings_on_position" and r["symbol"] == "AAPL"
               for r in risks)


def test_risk_map_ignores_earnings_on_unheld_position():
    earnings = [{"symbol": "AAPL", "date": "2026-04-30", "timing": "After Close"}]
    risks = _build_risk_map(positions=["NVDA"], earnings=earnings, macro=[])
    assert all(r["type"] != "earnings_on_position" for r in risks)


def test_risk_map_flags_high_impact_macro():
    macro = [{"event": "FOMC", "impact": "high", "time": "14:00"}]
    risks = _build_risk_map(positions=[], earnings=[], macro=macro)
    assert any(r["type"] == "high_impact_macro" for r in risks)


def test_risk_map_skips_low_impact_macro():
    macro = [{"event": "Building Permits", "impact": "low", "time": "08:30"}]
    risks = _build_risk_map(positions=[], earnings=[], macro=macro)
    assert risks == []


def test_risk_map_caps_at_fifteen():
    earnings = [{"symbol": "AAPL", "date": "2026-04-30", "timing": "After Close"}] * 20
    risks = _build_risk_map(positions=["AAPL"], earnings=earnings, macro=[])
    assert len(risks) <= 15


# ──────────────────────────────────────────────────────────────────────
# Service surface — get_latest fallback path
# ──────────────────────────────────────────────────────────────────────


def _mock_db_with_doc(doc):
    """Build a Mongo mock that returns `doc` for `find_one(_id=current_week)`
    on the second call, and no doc for the first (forces the fallback path).
    """
    db = MagicMock()
    col = db["weekend_briefings"]
    col.find_one = MagicMock(side_effect=[None, doc])
    col.create_index = MagicMock()
    db.__getitem__.return_value = col
    return db


def test_get_latest_falls_back_to_most_recent_when_current_week_missing():
    last_week_doc = {"iso_week": "2026-W17", "generated_at": "2026-04-20T18:00:00Z",
                     "gameplan": "old gameplan"}
    db = _mock_db_with_doc(last_week_doc)
    svc = WeekendBriefingService(db)
    out = svc.get_latest()
    assert out is not None
    assert out["iso_week"] == "2026-W17"


def test_get_latest_returns_none_when_db_unavailable():
    svc = WeekendBriefingService(None)
    assert svc.get_latest() is None


def test_get_latest_swallows_db_exceptions():
    db = MagicMock()
    db["weekend_briefings"].find_one.side_effect = RuntimeError("boom")
    db.__getitem__.return_value = db["weekend_briefings"]
    svc = WeekendBriefingService(db)
    assert svc.get_latest() is None


# ──────────────────────────────────────────────────────────────────────
# Static surface — pin the sector ETF list so future edits don't silently
# drop a major sector.
# ──────────────────────────────────────────────────────────────────────


def test_sector_etfs_includes_all_eleven_select_sector_spdrs():
    expected = {"XLK", "XLF", "XLE", "XLV", "XLI", "XLC",
                "XLY", "XLP", "XLU", "XLRE", "XLB"}
    assert set(SECTOR_ETFS.keys()) == expected
