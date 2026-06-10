"""
Tests for v19.34.311b gate outcome ATTRIBUTION + COVERAGE infra:
  - record_trade_outcome exact-match on decision_id
  - fuzzy fallback restricted to GO/REDUCE (SKIP can't absorb outcomes)
  - is_clean_for_learning hygiene filter
  - GateOutcomeReconciler backfill (win/loss/scratch from pnl)
"""
import asyncio
import pytest

from services.ai_modules.confidence_gate import ConfidenceGate
from services.ai_modules.gate_outcome_reconciler import (
    is_clean_for_learning, GateOutcomeReconciler,
)


# ---------------- record_trade_outcome match logic ----------------

class _FakeGateCol:
    def __init__(self):
        self.last_query = None
        self.last_set = None
        self.last_kwargs = None

    def find_one_and_update(self, query, update, **kwargs):
        self.last_query = query
        self.last_set = update["$set"]
        self.last_kwargs = kwargs
        return {"decision": query.get("decision", "GO"), **update["$set"]}


class _FakeGateDB:
    def __init__(self):
        self._col = _FakeGateCol()

    def __getitem__(self, name):
        return self._col


def _record(db, **kw):
    gate = ConfidenceGate.__new__(ConfidenceGate)
    gate._db = db
    return asyncio.run(gate.record_trade_outcome("AAPL", "breakout", **kw))


def test_exact_match_uses_decision_id_no_sort():
    db = _FakeGateDB()
    ok = _record(db, outcome="won", pnl=10, decision_id="abc-123")
    assert ok is True
    assert db._col.last_query == {"decision_id": "abc-123", "outcome_tracked": False}
    # exact match must NOT pass a sort (it's unique)
    assert "sort" not in db._col.last_kwargs
    assert db._col.last_set["trade_outcome"] == "win"


def test_fuzzy_fallback_restricts_to_go_reduce():
    db = _FakeGateDB()
    ok = _record(db, outcome="lost", pnl=-5)  # no decision_id
    assert ok is True
    q = db._col.last_query
    assert q["symbol"] == "AAPL" and q["setup_type"] == "breakout"
    assert q["decision"] == {"$in": ["GO", "REDUCE"]}
    assert db._col.last_kwargs["sort"] == [("timestamp", -1)]
    assert db._col.last_set["trade_outcome"] == "loss"


# ---------------- hygiene filter ----------------

def _base_trade(**over):
    t = {
        "status": "closed", "entered_by": "bot_fired", "fill_price": 100.0,
        "shares": 50, "stop_price": 98.0, "realized_pnl": 25.0,
        "entry_context": {"confidence_gate": {"decision_id": "d1"}},
    }
    t.update(over)
    return t


@pytest.mark.parametrize("over,ok", [
    ({}, True),
    ({"entered_by": "reconciled_excess_v19_34_15b"}, False),
    ({"entered_by": "imported_from_ib"}, False),
    ({"entered_by": "manual"}, False),
    ({"status": "open"}, False),
    ({"fill_price": 0}, False),
    ({"shares": 0}, False),
    ({"stop_price": 0}, False),         # unmanaged (no bracket)
    ({"realized_pnl": None, "net_pnl": None, "pnl": None}, False),
])
def test_is_clean_for_learning(over, ok):
    clean, _reason = is_clean_for_learning(_base_trade(**over))
    assert clean is ok


# ---------------- reconciler backfill ----------------

class _RecCol:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.updates = []

    def find(self, q, proj=None):
        class _Cur(list):
            def limit(self, n):
                return self
        return _Cur(self.docs)

    def find_one(self, q, proj=None):
        for d in self.docs:
            if d.get("decision_id") == q.get("decision_id"):
                return d
        return None

    def update_one(self, q, update):
        self.updates.append((q, update["$set"]))
        class _R:
            modified_count = 1
        return _R()


class _RecDB:
    def __init__(self, trades, gatelogs):
        self._bt = _RecCol(trades)
        self._cg = _RecCol(gatelogs)

    def __getitem__(self, name):
        return self._bt if name == "bot_trades" else self._cg


def test_reconciler_backfills_clean_trade_win():
    trades = [_base_trade(realized_pnl=42.0)]
    gatelogs = [{"decision_id": "d1", "outcome_tracked": False}]
    db = _RecDB(trades, gatelogs)
    stats = GateOutcomeReconciler(db=db).reconcile(dry_run=False)
    assert stats["clean"] == 1
    assert stats["backfilled"] == 1
    q, s = db._cg.updates[0]
    assert s["trade_outcome"] == "win"
    assert s["outcome_pnl"] == 42.0
    assert s["outcome_source"] == "reconciler"


def test_reconciler_skips_already_tracked_and_dirty():
    trades = [
        _base_trade(realized_pnl=10.0),  # clean d1
        _base_trade(entered_by="reconciled_external",
                    entry_context={"confidence_gate": {"decision_id": "d2"}}),  # dirty
    ]
    gatelogs = [
        {"decision_id": "d1", "outcome_tracked": True},   # already tracked
        {"decision_id": "d2", "outcome_tracked": False},
    ]
    db = _RecDB(trades, gatelogs)
    stats = GateOutcomeReconciler(db=db).reconcile(dry_run=False)
    assert stats["already_tracked"] == 1
    assert stats["excluded"] == 1
    assert stats["backfilled"] == 0
