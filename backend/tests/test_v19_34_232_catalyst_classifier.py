"""
v19.34.232 (task B) — Catalyst classifier regression tests.

Verifies the categorical tag priority (earnings > analyst > news > sympathy >
no_catalyst), the fail-open behaviour, and the env-gate. Services are faked so
the test needs no Mongo/Finnhub/IB.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.catalyst_classifier_service import CatalystClassifierService  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeNews:
    def __init__(self, by_symbol):
        self._m = by_symbol

    async def get_ticker_news(self, symbol, max_items=10):
        return [{"headline": h} for h in self._m.get(symbol.upper(), [])]


class _FakeRegime:
    def __init__(self, value):
        self.value = value


class _FakeSector:
    def __init__(self, value):
        self._v = value

    async def classify_for_symbol(self, symbol):
        return _FakeRegime(self._v)


class _FakeTagger:
    def tag_symbol(self, symbol):
        return "XLK"


def _svc(news=None, earnings=None, sector=None, tagger=None):
    s = CatalystClassifierService(db=None, news_service=news,
                                  sector_classifier=sector, sector_tagger=tagger)
    # bypass Mongo: stub the earnings set directly
    if earnings is not None:
        s._earn_cache = (9e18, {k.upper(): v for k, v in earnings.items()})
    else:
        s._earn_cache = (9e18, {})
    return s


def test_earnings_wins(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    s = _svc(news=_FakeNews({"AAA": ["AAA upgraded to Buy"]}),
             earnings={"AAA": {"hour": "bmo", "date": "2026-06-03"}})
    r = _run(s.classify("AAA", direction="long"))
    assert r["tag"] == "earnings" and "before open" in r["summary"]


def test_analyst_tag(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    s = _svc(news=_FakeNews({"BBB": ["Morgan Stanley downgrade BBB to Underweight"]}))
    r = _run(s.classify("BBB"))
    assert r["tag"] == "analyst" and "downgrade" in r["summary"].lower()


def test_news_tag(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    s = _svc(news=_FakeNews({"CCC": ["CCC wins $2B defense contract"]}))
    r = _run(s.classify("CCC"))
    assert r["tag"] == "news" and "defense" in r["summary"]


def test_sympathy_when_sector_moves(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    s = _svc(news=_FakeNews({}),  # no headlines
             sector=_FakeSector("trending_up"), tagger=_FakeTagger())
    r = _run(s.classify("DDD", direction="long"))
    assert r["tag"] == "sympathy" and "XLK" in r["summary"]


def test_sympathy_requires_matching_direction(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    # sector up but alert is SHORT → not sympathy → no_catalyst
    s = _svc(news=_FakeNews({}), sector=_FakeSector("trending_up"), tagger=_FakeTagger())
    r = _run(s.classify("DDD", direction="short"))
    assert r["tag"] == "no_catalyst"


def test_no_catalyst(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    s = _svc(news=_FakeNews({}))
    r = _run(s.classify("EEE"))
    assert r["tag"] == "no_catalyst"


def test_disabled_returns_no_catalyst(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "0")
    s = _svc(news=_FakeNews({"AAA": ["AAA upgraded"]}),
             earnings={"AAA": {"hour": "bmo", "date": "2026-06-03"}})
    r = _run(s.classify("AAA"))
    assert r["tag"] == "no_catalyst"


def test_failopen_on_bad_news_service(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")

    class _Boom:
        async def get_ticker_news(self, symbol, max_items=10):
            raise RuntimeError("network down")

    s = _svc(news=_Boom())
    r = _run(s.classify("AAA"))  # must not raise
    assert r["tag"] == "no_catalyst"


def test_valid_tag_always(monkeypatch):
    monkeypatch.setenv("CATALYST_TAGGING_ENABLED", "1")
    from services.catalyst_classifier_service import VALID_TAGS
    s = _svc(news=_FakeNews({"AAA": ["AAA wins contract"]}))
    r = _run(s.classify("AAA"))
    assert r["tag"] in VALID_TAGS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
