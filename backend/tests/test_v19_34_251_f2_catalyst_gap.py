"""
v19.34.251 (F2) — catalyst_tag + gap_pct populated at entry.

The Phase-D edge ranker buckets realized trade_outcomes by catalyst+gap, but
both buckets were 100% empty because (1) catalyst_tag was only stamped on
PREMARKET alerts (never the RTH ones that actually fire) and (2) entry_context
never carried gap_pct/catalyst_tag through to trade_outcomes.

These tests lock: the catalyst classifier reads the LOCAL news_articles +
earnings_calendar caches (no live API hang) under mongo_only, and
build_entry_context persists both fields from the alert.
"""

from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone

import pytest

from services.catalyst_classifier_service import CatalystClassifierService
from services.opportunity_evaluator import OpportunityEvaluator


def _db_with(news=None, earnings=None):
    """Mock DB serving news_articles + earnings_calendar collections."""
    db = MagicMock()
    news = news or []
    earnings = earnings or []

    def _getitem(name):
        col = MagicMock()
        if name == "news_articles":
            cur = MagicMock()
            cur.sort.return_value.limit.return_value = news
            col.find.return_value = cur
        elif name == "earnings_calendar":
            col.find.return_value = earnings
        return col

    db.__getitem__.side_effect = _getitem
    return db


@pytest.mark.asyncio
async def test_classify_earnings_from_calendar_mongo_only():
    """Symbol with an earnings_calendar row today → 'earnings' tag, no API."""
    today = datetime.now(timezone.utc).date().isoformat()
    db = _db_with(earnings=[{"symbol": "NVDA", "hour": "amc", "date": f"{today}T00:00:00"}])
    live_news = MagicMock()
    live_news.get_ticker_news = AsyncMock(return_value=[{"headline": "should not be used"}])
    clf = CatalystClassifierService(db=db, news_service=live_news)

    res = await clf.classify("NVDA", direction="long", gap_pct=4.0, mongo_only=True)

    assert res["tag"] == "earnings"
    # Live news service must NOT be called on the mongo_only hot path.
    live_news.get_ticker_news.assert_not_called()


@pytest.mark.asyncio
async def test_classify_analyst_from_local_news():
    """A local news headline with an analyst keyword → 'analyst' tag."""
    db = _db_with(news=[{"headline": "Morgan Stanley upgrades AAPL to overweight"}])
    clf = CatalystClassifierService(db=db, news_service=None)

    res = await clf.classify("AAPL", direction="long", mongo_only=True)
    assert res["tag"] == "analyst"


@pytest.mark.asyncio
async def test_classify_news_from_local_cache():
    """A material local headline (non-analyst) → 'news' tag."""
    db = _db_with(news=[{"headline": "AAPL unveils new product line at event"}])
    clf = CatalystClassifierService(db=db, news_service=None)

    res = await clf.classify("AAPL", direction="long", mongo_only=True)
    assert res["tag"] == "news"


@pytest.mark.asyncio
async def test_classify_no_catalyst_when_nothing_local():
    """No earnings, no news, no sector → 'no_catalyst' (fade-prone)."""
    db = _db_with()
    clf = CatalystClassifierService(db=db, news_service=None)

    res = await clf.classify("ZZZZ", direction="long", mongo_only=True)
    assert res["tag"] == "no_catalyst"


@pytest.mark.asyncio
async def test_recent_headlines_mongo_reads_local_collection():
    """_recent_headlines_mongo returns trimmed headlines from news_articles."""
    db = _db_with(news=[{"headline": " breaking news "}, {"headline": ""}])
    clf = CatalystClassifierService(db=db)
    heads = clf._recent_headlines_mongo("AAPL")
    assert heads == ["breaking news"]


def test_build_entry_context_persists_catalyst_and_gap():
    """build_entry_context copies catalyst_tag + signed gap_pct from the alert."""
    ev = OpportunityEvaluator()
    alert = {
        "symbol": "MU", "setup_type": "gap_and_go", "direction": "long",
        "catalyst_tag": "earnings", "catalyst_summary": "Earnings after close.",
        "gap_pct": 5.234,
    }
    ctx = ev.build_entry_context(
        alert=alert, intelligence={}, regime="RISK_ON", regime_score=70.0,
        filter_action="allow", filter_win_rate=0.55, atr=1.2, atr_percent=2.1,
    )
    assert ctx["catalyst_tag"] == "earnings"
    assert ctx["catalyst_summary"] == "Earnings after close."
    assert ctx["gap_pct"] == 5.23  # rounded to 2dp


def test_build_entry_context_defaults_when_alert_lacks_fields():
    """Missing catalyst/gap → safe defaults (empty tag, 0.0 gap)."""
    ev = OpportunityEvaluator()
    ctx = ev.build_entry_context(
        alert={"symbol": "X", "setup_type": "range_break", "direction": "short"},
        intelligence={}, regime="CAUTION", regime_score=50.0,
        filter_action="allow", filter_win_rate=0.5, atr=1.0, atr_percent=1.5,
    )
    assert ctx["catalyst_tag"] == ""
    assert ctx["gap_pct"] == 0.0
