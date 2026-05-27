"""v19.34.168 — regime_snapshots persistence service tests.

Uses a tiny mock collection (no real Mongo needed) to verify:
  - First call persists
  - Same regime/agreement/divergence does NOT persist again
  - Change in regime label persists
  - Change in agreement persists
  - Change in divergence_flag persists
  - Stats math is correct
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class MockColl:
    def __init__(self):
        self.docs = []
        self.indexes = []

    def create_index(self, spec, **kwargs):
        self.indexes.append((spec, kwargs))

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("Res", (), {"inserted_id": len(self.docs)})()

    def find_one(self, query=None, sort=None, projection=None):
        items = sorted(self.docs, key=lambda d: d.get("ts"), reverse=True) if sort else self.docs
        return items[0] if items else None

    def find(self, query=None):
        items = list(self.docs)
        if query and "ts" in query:
            cutoff = query["ts"].get("$gte")
            if cutoff:
                items = [d for d in items if d["ts"] >= cutoff]
        # Return a chainable cursor
        return _Cursor(items)


class _Cursor:
    def __init__(self, items):
        self.items = items
    def sort(self, key, direction=1):
        self.items.sort(key=lambda d: d.get(key), reverse=(direction == -1))
        return self
    def limit(self, n):
        self.items = self.items[:n]
        return self
    def __iter__(self):
        return iter(self.items)


class MockDB:
    def __init__(self):
        self.colls = {}
    def __getitem__(self, name):
        if name not in self.colls:
            self.colls[name] = MockColl()
        return self.colls[name]


def _meta(agreement="unanimous_up", divergence=False, uptrend=3, downtrend=0, max_range=0.5):
    return {
        "index_agreement": agreement,
        "divergence_flag": divergence,
        "uptrend_votes": uptrend,
        "downtrend_votes": downtrend,
        "max_daily_range_pct": max_range,
        "indices_valid": 3,
        "per_index": {"spy": {"trend": "uptrend"}, "qqq": None, "iwm": None},
    }


def _reset_module_state():
    """Clear the per-process in-memory dedup cache between tests."""
    from services import regime_persistence_service as svc
    svc._last_snapshot_key.clear()
    svc._ttl_index_created.clear()


def test_first_call_persists():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed
    db = MockDB()
    result = record_if_changed(db, "strong_uptrend", _meta())
    assert result is not None
    assert len(db["regime_snapshots"].docs) == 1
    assert db["regime_snapshots"].docs[0]["regime"] == "strong_uptrend"


def test_unchanged_regime_does_not_persist_again():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed
    db = MockDB()
    record_if_changed(db, "strong_uptrend", _meta())
    record_if_changed(db, "strong_uptrend", _meta())
    record_if_changed(db, "strong_uptrend", _meta())
    assert len(db["regime_snapshots"].docs) == 1, "should still be 1 — no change"


def test_regime_label_change_persists():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed
    db = MockDB()
    record_if_changed(db, "strong_uptrend", _meta())
    record_if_changed(db, "momentum", _meta())  # different regime
    assert len(db["regime_snapshots"].docs) == 2


def test_agreement_change_persists_even_with_same_regime():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed
    db = MockDB()
    record_if_changed(db, "momentum", _meta(agreement="unanimous_up"))
    record_if_changed(db, "momentum", _meta(agreement="majority_up"))
    assert len(db["regime_snapshots"].docs) == 2


def test_divergence_flag_change_persists():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed
    db = MockDB()
    record_if_changed(db, "momentum", _meta(divergence=False))
    record_if_changed(db, "momentum", _meta(divergence=True))
    assert len(db["regime_snapshots"].docs) == 2


def test_seeds_from_db_to_avoid_double_write_across_restarts():
    """If the DB already has a recent snapshot with the same key, a fresh
    process should NOT write the same row again on first call."""
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed
    db = MockDB()
    # Pre-seed DB with an existing row (simulating prior process)
    db["regime_snapshots"].docs.append({
        "ts": datetime.now(timezone.utc) - timedelta(minutes=5),
        "regime": "volatile",
        "agreement": "mixed",
        "divergence_flag": False,
    })
    # New process records same state — should skip
    result = record_if_changed(db, "volatile", _meta(agreement="mixed"))
    assert result is None
    assert len(db["regime_snapshots"].docs) == 1


def test_ttl_index_is_created():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed, TTL_SECONDS
    db = MockDB()
    record_if_changed(db, "strong_uptrend", _meta())
    indexes = db["regime_snapshots"].indexes
    ttl_index = next((i for i in indexes if i[1].get("expireAfterSeconds") == TTL_SECONDS), None)
    assert ttl_index is not None, "TTL index missing"


def test_query_history_returns_recent_snapshots():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed, query_history
    db = MockDB()
    record_if_changed(db, "strong_uptrend", _meta())
    record_if_changed(db, "momentum", _meta())
    record_if_changed(db, "volatile", _meta())
    history = query_history(db, hours=24)
    assert len(history) == 3
    # Newest first
    assert history[0]["regime"] == "volatile"
    assert history[-1]["regime"] == "strong_uptrend"


def test_query_stats_computes_percentages():
    _reset_module_state()
    from services.regime_persistence_service import query_stats
    db = MockDB()
    now = datetime.now(timezone.utc)
    # Manually insert with known timestamps so we can verify math
    db["regime_snapshots"].docs = [
        {"ts": now - timedelta(hours=3), "regime": "strong_uptrend",
         "agreement": "unanimous_up", "divergence_flag": False},
        {"ts": now - timedelta(hours=2), "regime": "momentum",
         "agreement": "unanimous_up", "divergence_flag": False},
        # Most recent = volatile, lasts from 1h ago to NOW (1h)
        {"ts": now - timedelta(hours=1), "regime": "volatile",
         "agreement": "mixed", "divergence_flag": False},
    ]
    stats = query_stats(db, hours=24)
    pct = stats["regimes_pct"]
    # strong_uptrend: from -3h to -2h = 1h.  momentum: -2h to -1h = 1h.  volatile: -1h to now = 1h.
    # Each ~33.33%
    assert 30 <= pct.get("strong_uptrend", 0) <= 36
    assert 30 <= pct.get("momentum", 0) <= 36
    assert 30 <= pct.get("volatile", 0) <= 36
    assert stats["snapshots_observed"] == 3


def test_query_stats_empty_window_returns_empty():
    _reset_module_state()
    from services.regime_persistence_service import query_stats
    db = MockDB()
    stats = query_stats(db, hours=24)
    assert stats["regimes"] == {} or stats.get("snapshots_observed", 0) == 0


def test_none_db_no_crash():
    _reset_module_state()
    from services.regime_persistence_service import record_if_changed, query_history, query_stats
    assert record_if_changed(None, "strong_uptrend", _meta()) is None
    assert query_history(None) == []
    s = query_stats(None)
    assert s["regimes"] == {}
