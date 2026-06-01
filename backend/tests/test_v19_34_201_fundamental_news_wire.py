"""
v19.34.201 — fundamental pillar catalyst/news wiring.

The TQS engine never passed `news_service`/`db` into the fundamental pillar, so
its catalyst component (30% of the pillar) was permanently stuck at the
"no catalyst" floor of 40 → the flat ~57 fundamental score. This verifies the
news → catalyst/sentiment enrichment now fires and lifts the catalyst score.

`news_service._analyze_sentiment` returns a STRING (bullish/bearish/neutral);
the pillar maps it to a float internally.
"""
import asyncio
from datetime import datetime, timezone

from services.tqs.fundamental_quality import FundamentalQualityService


class _FakeNews:
    def __init__(self, items):
        self._items = items

    async def get_ticker_news(self, symbol, max_items=10):
        return self._items


def _news(sentiment, placeholder=False, headline="x"):
    return {
        "symbol": "TST", "headline": headline, "sentiment": sentiment,
        "is_placeholder": placeholder,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_bullish_news_lifts_catalyst_above_floor():
    svc = FundamentalQualityService()
    svc.set_services(news_service=_FakeNews([_news("bullish"), _news("bullish")]))
    res = _run(svc.calculate_score("TST", direction="long"))
    # has_recent_news + positive sentiment → catalyst 65 (vs 40 floor)
    assert res.catalyst_score >= 65
    assert res.has_catalyst is False  # routed via has_recent_news branch
    assert res.score > 57.0  # beats the all-defaults flat score


def test_no_newsservice_keeps_default_floor():
    svc = FundamentalQualityService()
    svc.set_services()  # no news service wired
    res = _run(svc.calculate_score("TST", direction="long"))
    assert res.catalyst_score == 40  # unchanged "no catalyst" floor


def test_placeholder_news_ignored():
    svc = FundamentalQualityService()
    svc.set_services(news_service=_FakeNews([_news("bullish", placeholder=True)]))
    res = _run(svc.calculate_score("TST", direction="long"))
    # only placeholder → treated as no news → floor
    assert res.catalyst_score == 40


def test_bearish_news_supports_short():
    svc = FundamentalQualityService()
    svc.set_services(news_service=_FakeNews([_news("bearish"), _news("bearish")]))
    res = _run(svc.calculate_score("TST", direction="short"))
    # short + negative sentiment → recent-negative-news branch (65)
    assert res.catalyst_score >= 65


def test_explicit_args_override_newsservice():
    # If the caller passes catalyst data, news_service must NOT override it.
    svc = FundamentalQualityService()
    svc.set_services(news_service=_FakeNews([_news("bearish")]))
    res = _run(svc.calculate_score(
        "TST", direction="long", has_catalyst=True, catalyst_type="earnings",
        earnings_catalyst_score=8))
    assert res.catalyst_score == 95  # strong earnings catalyst, not news
