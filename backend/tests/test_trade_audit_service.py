"""
Tests for services/trade_audit_service.py — trade post-mortem log.
"""
from types import SimpleNamespace

import pytest

from services.trade_audit_service import (
    build_audit_record,
    record_audit_entry,
    query_audit,
    COLLECTION_NAME,
)


# ── Fake Mongo for unit tests ──────────────────────────────────────────

class _FakeCollection:
    def __init__(self):
        self.docs: list = []

    def insert_one(self, d):
        self.docs.append(d)
        return SimpleNamespace(inserted_id="fake")

    def find(self, q=None, proj=None):
        q = q or {}
        def _match(doc, q):
            for k, v in q.items():
                if "." in k:
                    # dotted: model.model_version
                    head, tail = k.split(".", 1)
                    sub = doc.get(head) or {}
                    if _get_nested(sub, tail) != v:
                        return False
                elif isinstance(v, dict) and "$gte" in v:
                    if (doc.get(k) or "") < v["$gte"]:
                        return False
                elif doc.get(k) != v:
                    return False
            return True
        matching = [d for d in self.docs if _match(d, q)]
        return _FakeCursor(matching)


def _get_nested(d, path):
    parts = path.split(".")
    cur = d
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        reverse = direction == -1
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=reverse)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeDB:
    def __init__(self):
        self._collections: dict = {}

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


# ── build_audit_record (pure) ──────────────────────────────────────────

def test_build_record_from_full_inputs():
    trade = SimpleNamespace(
        id="t_123",
        symbol="AAPL",
        direction=SimpleNamespace(value="long"),
        setup_type="orb",
        timeframe="5m",
        entry_price=150.0,
        stop_price=147.0,
        target_prices=[155.0, 160.0],
        shares=100,
        risk_amount=300.0,
        potential_reward=1000.0,
        risk_reward_ratio=3.33,
        quality_score=85.0,
        quality_grade="A",
    )
    gate = {
        "decision": "GO",
        "confidence_score": 72,
        "position_multiplier": 1.0,
        "reasoning": ["AI CONFIRMS long", "regime aligned"],
    }
    pred = {
        "model_used": "orb_5min_predictor",
        "model_type": "setup_specific",
        "model_version": "v20260422_233118",
        "num_classes": 3,
        "direction": "up",
        "probability_up": 0.52,
        "probability_down": 0.25,
        "probability_flat": 0.23,
        "confidence": 0.52,
        "model_metrics": {
            "calibrated_up_threshold": 0.48,
            "calibrated_down_threshold": 0.55,
            "accuracy": 0.527,
            "precision_up": 0.44,
            "recall_up": 0.33,
            "precision_down": 0.58,
            "recall_down": 0.62,
        },
    }
    multipliers = {
        "smart_filter": 1.0,
        "confidence_gate": 0.9,
        "regime": 1.1,
        "strategy_tilt": 1.05,
        "hrp_allocator": 0.95,
    }

    doc = build_audit_record(
        trade, gate_result=gate, model_prediction=pred,
        regime="RISK_ON", multipliers=multipliers,
    )

    assert doc["trade_id"] == "t_123"
    assert doc["symbol"] == "AAPL"
    assert doc["direction"] == "long"
    assert doc["setup_type"] == "orb"
    assert doc["entry"]["entry_price"] == 150.0
    assert doc["entry"]["stop_price"] == 147.0
    assert doc["gate"]["decision"] == "GO"
    assert doc["gate"]["score"] == 72
    assert len(doc["gate"]["reasoning"]) == 2
    assert doc["model"]["model_version"] == "v20260422_233118"
    assert doc["model"]["calibrated_up_threshold"] == 0.48
    assert doc["model"]["p_up"] == 0.52
    assert doc["multipliers"]["strategy_tilt"] == 1.05
    assert doc["multipliers"]["hrp_allocator"] == 0.95
    assert doc["regime"] == "RISK_ON"
    assert "created_at" in doc


def test_build_record_handles_missing_gate_and_prediction():
    trade = SimpleNamespace(id="t_x", symbol="MSFT", direction="short", setup_type="vwap")
    doc = build_audit_record(trade)
    assert doc["trade_id"] == "t_x"
    assert doc["direction"] == "short"
    assert doc["gate"]["decision"] is None
    assert doc["model"]["model_version"] is None


def test_build_record_reads_dict_trade():
    """Works if caller passes a plain dict instead of an object."""
    trade = {
        "id": "t_d",
        "symbol": "TSLA",
        "direction": "long",
        "setup_type": "opening_drive",
        "entry_price": 250.0,
    }
    doc = build_audit_record(trade)
    assert doc["trade_id"] == "t_d"
    assert doc["symbol"] == "TSLA"
    assert doc["entry"]["entry_price"] == 250.0


def test_build_record_caps_reasoning_at_12():
    reasoning = [f"reason_{i}" for i in range(20)]
    trade = SimpleNamespace(id="t", symbol="X")
    doc = build_audit_record(
        trade, gate_result={"reasoning": reasoning},
    )
    assert len(doc["gate"]["reasoning"]) == 12


# ── record_audit_entry ──────────────────────────────────────────────────

def test_record_audit_none_db_is_noop():
    trade = SimpleNamespace(id="t", symbol="X")
    assert record_audit_entry(None, trade) is False


def test_record_audit_writes_to_collection():
    db = _FakeDB()
    trade = SimpleNamespace(
        id="t_1",
        symbol="AAPL",
        direction=SimpleNamespace(value="long"),
    )
    ok = record_audit_entry(db, trade)
    assert ok is True
    assert len(db[COLLECTION_NAME].docs) == 1
    assert db[COLLECTION_NAME].docs[0]["symbol"] == "AAPL"


def test_record_audit_swallows_exceptions():
    class _Broken:
        def __getitem__(self, _):
            class _C:
                def insert_one(self, _):
                    raise RuntimeError("boom")
            return _C()
    trade = SimpleNamespace(id="t", symbol="X")
    assert record_audit_entry(_Broken(), trade) is False


# ── query_audit ─────────────────────────────────────────────────────────

def test_query_audit_filters_by_symbol():
    db = _FakeDB()
    for i, sym in enumerate(["AAPL", "MSFT", "AAPL"]):
        trade = SimpleNamespace(id=f"t{i}", symbol=sym, direction="long")
        record_audit_entry(db, trade)
    result = query_audit(db, symbol="AAPL")
    assert len(result) == 2
    assert all(r["symbol"] == "AAPL" for r in result)


def test_query_audit_filters_by_setup_type():
    db = _FakeDB()
    for i, setup in enumerate(["orb", "vwap", "orb"]):
        trade = SimpleNamespace(
            id=f"t{i}", symbol="X", direction="long", setup_type=setup,
        )
        record_audit_entry(db, trade)
    assert len(query_audit(db, setup_type="orb")) == 2


def test_query_audit_respects_limit():
    db = _FakeDB()
    for i in range(20):
        trade = SimpleNamespace(id=f"t{i}", symbol="X")
        record_audit_entry(db, trade)
    assert len(query_audit(db, limit=5)) == 5


def test_query_audit_none_db_returns_empty():
    assert query_audit(None) == []


def test_query_audit_filters_by_model_version():
    db = _FakeDB()
    versions = ["v1", "v2", "v1"]
    for i, v in enumerate(versions):
        trade = SimpleNamespace(id=f"t{i}", symbol="X")
        record_audit_entry(
            db, trade,
            model_prediction={
                "model_version": v,
                "model_metrics": {},
            },
        )
    result = query_audit(db, model_version="v1")
    assert len(result) == 2
    assert all(r["model"]["model_version"] == "v1" for r in result)
