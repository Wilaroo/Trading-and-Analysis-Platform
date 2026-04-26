"""
Contract tests for /api/backfill/readiness — the pre-retrain readiness
gate added 2026-04-24.

These exercise `compute_readiness()` against a fake in-memory mongo
surface so we don't need the DGX's ib_historical_data to run the suite.
"""
from datetime import datetime, timezone, timedelta

import pytest

from services import backfill_readiness_service as svc


# ---------------------------------------------------------------------------
# Fake mongo helpers
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeCollection:
    def __init__(self):
        self.docs = []
        self._indexes = []

    def insert(self, doc):
        self.docs.append(doc)

    def list_indexes(self):
        # Mongo returns _id_ + whatever the collection set up. Tests can
        # opt-in to indexes by appending to ._indexes.
        return iter(self._indexes)

    def count_documents(self, filt, **kwargs):
        limit = kwargs.get("limit")
        n = sum(1 for d in self.docs if self._match(d, filt))
        return min(n, limit) if limit else n

    def find(self, filt=None, projection=None):
        return _FakeCursor([d for d in self.docs if self._match(d, filt or {})])

    def find_one(self, filt=None, projection=None, sort=None):
        matches = [d for d in self.docs if self._match(d, filt or {})]
        if sort:
            key, direction = sort[0]
            matches.sort(key=lambda x: x.get(key) or "", reverse=(direction == -1))
        return matches[0] if matches else None

    def aggregate(self, pipeline, **kwargs):
        # Minimal subset: $match → $group (by symbol with $max date OR
        # counts) → $match → $limit.
        rows = list(self.docs)
        for stage in pipeline:
            if "$match" in stage:
                f = stage["$match"]
                rows = [r for r in rows if self._match(r, f)]
            elif "$group" in stage:
                g = stage["$group"]
                _id_expr = g.get("_id")
                bucket = {}
                for r in rows:
                    if isinstance(_id_expr, str) and _id_expr.startswith("$"):
                        key = r.get(_id_expr[1:])
                    elif isinstance(_id_expr, dict):
                        key = tuple(
                            (k, r.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v)
                            for k, v in _id_expr.items()
                        )
                    else:
                        key = _id_expr
                    b = bucket.setdefault(key, {"_id": key})
                    for field, op in g.items():
                        if field == "_id":
                            continue
                        if "$max" in op:
                            src = op["$max"][1:]
                            cur = b.get(field)
                            if cur is None or (r.get(src) and r[src] > cur):
                                b[field] = r.get(src)
                        elif "$sum" in op:
                            b[field] = b.get(field, 0) + (
                                op["$sum"] if isinstance(op["$sum"], int)
                                else r.get(op["$sum"][1:], 0) or 0
                            )
                # Re-expand dict-keyed _ids back to dict
                rows = []
                for k, v in bucket.items():
                    if isinstance(k, tuple):
                        v = dict(v)
                        v["_id"] = {kk: kv for kk, kv in k}
                    rows.append(v)
            elif "$limit" in stage:
                rows = rows[: stage["$limit"]]
            elif "$sort" in stage:
                pass  # not needed for these tests
        return _FakeCursor(rows)

    @staticmethod
    def _match(doc, filt):
        for k, v in filt.items():
            actual = doc.get(k)
            if isinstance(v, dict):
                for op, arg in v.items():
                    if op == "$gte" and not (actual is not None and actual >= arg):
                        return False
                    elif op == "$lt" and not (actual is not None and actual < arg):
                        return False
                    elif op == "$gt" and not (actual is not None and actual > arg):
                        return False
                    elif op == "$in" and actual not in arg:
                        return False
                    elif op == "$nin" and actual in arg:
                        return False
                    elif op == "$ne" and actual == arg:
                        return False
                    elif op == "$regex":
                        import re
                        if not (isinstance(actual, str) and re.search(arg, actual)):
                            return False
            else:
                if actual != v:
                    return False
        return True


class _FakeDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCollection())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_db():
    """A healthy DB: queue empty, critical symbols all fresh on every tf,
    small intraday universe, no dupes, good density."""
    db = _FakeDB()
    now = datetime.now(timezone.utc)
    recent_iso = now.isoformat()
    # Intraday universe = critical list + 2 extras so density/freshness rollups have data.
    universe = svc.CRITICAL_SYMBOLS + ["TSLA", "INTC"]
    # Stamp the unique compound index so _check_no_duplicates passes.
    db["ib_historical_data"]._indexes.append({
        "name": "symbol_1_bar_size_1_date_1",
        "key": {"symbol": 1, "bar_size": 1, "date": 1},
        "unique": True,
    })
    for sym in universe:
        db["symbol_adv_cache"].insert({
            "symbol": sym,
            "avg_volume": 1_000_000,
            "avg_dollar_volume": 100_000_000,  # qualifies for intraday
        })
        for tf in svc.CRITICAL_TIMEFRAMES:
            # Insert enough 5 mins bars to clear the density floor.
            bars = svc.DENSITY_MIN_5MIN_BARS + 1 if tf == "5 mins" else 200
            for i in range(bars):
                db["ib_historical_data"].insert({
                    "symbol": sym,
                    "bar_size": tf,
                    "date": (now - timedelta(minutes=5 * i)).isoformat(),
                })
    return db


@pytest.fixture
def queue_active_db(fresh_db):
    """A DB that is otherwise green but still has queue items pending."""
    fresh_db["historical_data_requests"].insert({"status": "pending"})
    fresh_db["historical_data_requests"].insert({"status": "claimed"})
    return fresh_db


@pytest.fixture
def stale_critical_db(fresh_db):
    """A DB where SPY's latest 5-min bar is 30 days old (clearly stale)."""
    # Wipe SPY 5-min bars, insert one very old bar.
    fresh_db["ib_historical_data"].docs = [
        d for d in fresh_db["ib_historical_data"].docs
        if not (d["symbol"] == "SPY" and d["bar_size"] == "5 mins")
    ]
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fresh_db["ib_historical_data"].insert({"symbol": "SPY", "bar_size": "5 mins", "date": old})
    return fresh_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_returns_green(fresh_db):
    result = svc.compute_readiness(fresh_db)
    assert result["success"] is True
    assert result["verdict"] == "green", result["blockers"]
    assert result["ready_to_train"] is True
    assert result["blockers"] == []
    assert "READY" in result["summary"]

def test_queue_still_active_forces_red(queue_active_db):
    result = svc.compute_readiness(queue_active_db)
    assert result["verdict"] == "red"
    assert result["ready_to_train"] is False
    assert result["checks"]["queue_drained"]["status"] == "red"
    assert result["checks"]["queue_drained"]["pending"] == 1
    assert result["checks"]["queue_drained"]["claimed"] == 1
    assert any("queue" in s.lower() or "drain" in s.lower() for s in result["next_steps"])


def test_stale_critical_symbol_forces_red(stale_critical_db):
    result = svc.compute_readiness(stale_critical_db)
    assert result["verdict"] == "red"
    assert result["checks"]["critical_symbols_fresh"]["status"] == "red"
    assert "SPY" in result["checks"]["critical_symbols_fresh"]["stale_symbols"]
    # Must tell the user exactly what to do.
    assert any("SPY" in s for s in result["next_steps"])


def test_response_shape_contract(fresh_db):
    """Locks the public contract the UI depends on."""
    r = svc.compute_readiness(fresh_db)
    for k in ("success", "verdict", "ready_to_train", "summary",
              "blockers", "warnings", "next_steps", "checks", "generated_at"):
        assert k in r, f"missing top-level key {k!r}"
    for name in ("queue_drained", "critical_symbols_fresh",
                 "overall_freshness", "no_duplicates", "density_adequate"):
        assert name in r["checks"], f"missing check {name!r}"
        assert r["checks"][name]["status"] in ("green", "yellow", "red")
        assert isinstance(r["checks"][name].get("detail"), str)


def test_endpoint_registered():
    """The router must be wired on /api/backfill/readiness."""
    from routers import backfill_router
    paths = [r.path for r in backfill_router.router.routes]
    assert "/api/backfill/readiness" in paths, paths
