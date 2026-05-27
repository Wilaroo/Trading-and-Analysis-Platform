"""v19.34.168.1 — Tests for composite/history and composite/stats endpoints.

Validates that:
  1. /api/market-regime/composite/history reads from `regime_snapshots`
     (NOT `market_regime_state`)
  2. /api/market-regime/composite/stats returns regime % breakdowns
  3. Renamed routes do not collide with daily Engine A `/history` route
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Make backend importable when run from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from services import regime_persistence_service as rps  # noqa: E402


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.indexes = []
        self.inserted = []

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    def find_one(self, query=None, sort=None, projection=None):
        docs = self.docs
        if sort:
            field, direction = sort[0]
            docs = sorted(docs, key=lambda d: d.get(field), reverse=(direction == -1))
        return docs[0] if docs else None

    def insert_one(self, doc):
        self.inserted.append(doc)
        self.docs.append(doc)

    def find(self, query=None):
        cutoff = None
        if query and "ts" in query and "$gte" in query["ts"]:
            cutoff = query["ts"]["$gte"]
        results = [d for d in self.docs if cutoff is None or d.get("ts") >= cutoff]
        return _Cursor(results)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field, direction):
        self._docs.sort(key=lambda d: d.get(field), reverse=(direction == -1))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeDB:
    def __init__(self):
        self._collections = {"regime_snapshots": _FakeCollection()}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


@pytest.fixture(autouse=True)
def _reset_module_state():
    rps._last_snapshot_key.clear()
    rps._ttl_index_created.clear()
    yield


def test_record_if_changed_persists_on_first_observation():
    db = _FakeDB()
    out = rps.record_if_changed(
        db, "strong_uptrend",
        {"index_agreement": "unanimous_up", "divergence_flag": False,
         "uptrend_votes": 3, "downtrend_votes": 0}
    )
    assert out is not None
    assert db["regime_snapshots"].inserted[0]["regime"] == "strong_uptrend"


def test_record_if_changed_skips_when_regime_unchanged():
    db = _FakeDB()
    meta = {"index_agreement": "unanimous_up", "divergence_flag": False}
    rps.record_if_changed(db, "strong_uptrend", meta)
    out = rps.record_if_changed(db, "strong_uptrend", meta)
    assert out is None
    assert len(db["regime_snapshots"].inserted) == 1


def test_record_if_changed_writes_on_divergence_flip():
    db = _FakeDB()
    rps.record_if_changed(db, "strong_uptrend",
                          {"index_agreement": "unanimous_up", "divergence_flag": False})
    out = rps.record_if_changed(db, "strong_uptrend",
                                {"index_agreement": "majority_up", "divergence_flag": True})
    assert out is not None
    assert len(db["regime_snapshots"].inserted) == 2


def test_query_history_returns_recent_snapshots_only():
    db = _FakeDB()
    now = datetime.now(timezone.utc)
    db["regime_snapshots"].docs = [
        {"ts": now - timedelta(hours=48), "regime": "volatile",
         "agreement": "mixed", "divergence_flag": False},
        {"ts": now - timedelta(hours=2), "regime": "strong_uptrend",
         "agreement": "unanimous_up", "divergence_flag": False},
    ]
    out = rps.query_history(db, hours=6, limit=100)
    assert len(out) == 1
    assert out[0]["regime"] == "strong_uptrend"


def test_query_stats_returns_percent_time_in_regime():
    db = _FakeDB()
    now = datetime.now(timezone.utc)
    db["regime_snapshots"].docs = [
        {"ts": now - timedelta(hours=4), "regime": "volatile"},
        {"ts": now - timedelta(hours=2), "regime": "strong_uptrend"},
    ]
    out = rps.query_stats(db, hours=6)
    assert out["snapshots_observed"] == 2
    pct = out["regimes_pct"]
    # 2h volatile, 2h uptrend → 50/50 of observed window
    assert abs(pct["volatile"] - 50.0) < 1.0
    assert abs(pct["strong_uptrend"] - 50.0) < 1.0


def test_query_history_empty_db_returns_empty_list():
    db = _FakeDB()
    assert rps.query_history(db, hours=24) == []


def test_query_stats_empty_db_returns_zero_breakdown():
    db = _FakeDB()
    out = rps.query_stats(db, hours=24)
    assert out["regimes"] == {} or out.get("regimes_pct") == {}


def test_server_endpoints_use_composite_namespace():
    """Reads server.py and verifies the new endpoints live under
    `/api/market-regime/composite/...` (not the daily `/api/market-regime/...`
    which collides with the Engine A router)."""
    server_path = os.path.join(BACKEND, "server.py")
    with open(server_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/api/market-regime/composite/history")' in src, \
        "v168 composite/history endpoint missing"
    assert '@app.get("/api/market-regime/composite/stats")' in src, \
        "v168 composite/stats endpoint missing"
    # And the OLD broken namespace must NOT be present anymore.
    assert '@app.get("/api/market-regime/history")' not in src, \
        "stale v168 /history route still present — would collide with router prefix"
    assert '@app.get("/api/market-regime/stats")' not in src, \
        "stale v168 /stats route still present"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
