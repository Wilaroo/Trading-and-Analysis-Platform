"""
test_v19_34_220_fundamental_news_cache.py

Validates v19.34.220 — the Fundamental pillar reads recent news from the local
`news_articles` cache (FinBERT-scored) instead of the slow/hanging live
get_ticker_news path:
  - recent cache rows → has_recent_news lifts catalyst off the 40 floor
  - FinBERT sentiment dict {"score": ...} drives directional catalyst
  - empty cache → catalyst stays at the no-catalyst floor (40)
"""
import asyncio
import importlib
from datetime import datetime, timezone, timedelta

fq = importlib.import_module("services.tqs.fundamental_quality")


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return _Cursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class _Coll:
    def __init__(self, docs=None):
        self._docs = docs or []

    def find(self, q=None, proj=None):
        q = q or {}
        out = []
        for d in self._docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$gte" in v:
                    if str(d.get(k, "")) < v["$gte"]:
                        ok = False
                elif d.get(k) != v:
                    ok = False
            if ok:
                out.append(d)
        return _Cursor(out)

    def find_one(self, q=None):
        return None


class _DB:
    def __init__(self, news_docs):
        self._news = _Coll(news_docs)

    def __getitem__(self, name):
        return self._news if name == "news_articles" else _Coll([])


def _score(symbol, direction, news_docs):
    svc = fq.get_fundamental_quality_service()
    svc.set_services(ib_service=None, news_service=None, db=_DB(news_docs))
    return asyncio.new_event_loop().run_until_complete(
        svc.calculate_score(symbol=symbol, direction=direction)
    )


def test_no_news_catalyst_floored():
    r = _score("AAA", "long", [])
    assert r.has_catalyst is False
    assert r.catalyst_score == 40  # the no-catalyst floor


def test_recent_positive_news_lifts_catalyst_for_long():
    docs = [
        {"symbol": "AAA", "datetime": _iso(2),
         "sentiment": {"sentiment": "positive", "score": 0.8}},
        {"symbol": "AAA", "datetime": _iso(10),
         "sentiment": {"sentiment": "positive", "score": 0.6}},
    ]
    r = _score("AAA", "long", docs)
    assert r.catalyst_score == 65  # long + avg sentiment 0.7 > 0.3 (off the 40 floor)


def test_recent_neutral_news_lifts_off_floor():
    docs = [{"symbol": "AAA", "datetime": _iso(5),
             "sentiment": {"sentiment": "neutral", "score": 0.0}}]
    r = _score("AAA", "long", docs)
    assert r.catalyst_score == 50  # news present but no directional edge


def test_stale_news_ignored():
    # 100h old → outside the 72h window → treated as no news
    docs = [{"symbol": "AAA", "datetime": _iso(100),
             "sentiment": {"sentiment": "positive", "score": 0.9}}]
    r = _score("AAA", "long", docs)
    assert r.catalyst_score == 40


def test_unscored_sentiment_none_is_neutral():
    docs = [{"symbol": "AAA", "datetime": _iso(3), "sentiment": None}]
    r = _score("AAA", "long", docs)
    assert r.catalyst_score == 50
