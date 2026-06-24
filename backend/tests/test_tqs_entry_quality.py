"""Read-only TQS entry-quality cross-tab — verdict + correlation regression."""
from __future__ import annotations
import os, sys

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from services.tqs_entry_quality import generate_report, _spearman, _rank


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, q, proj=None):
        return [d for d in self._docs if d.get("status") == q.get("status", d.get("status"))]


class _DB:
    def __init__(self, docs): self._docs = docs
    def __getitem__(self, name): return _Coll(self._docs)


def _trade(score, grade, r, mfe, mae):
    # risk_amount=1 so realized_pnl == realized R
    return {"status": "closed", "setup_type": "breakout", "realized_pnl": r,
            "risk_amount": 1.0, "mfe_r": mfe, "mae_r": mae,
            "tqs_score": score, "tqs_grade": grade}


def test_spearman_monotonic():
    assert _spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert _spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0


def test_rank_handles_ties():
    assert _rank([10, 10, 20]) == [1.5, 1.5, 3.0]


def test_predictive_when_high_tqs_has_high_mfe():
    docs = []
    # high TQS → high MFE + positive R ; low TQS → low MFE + negative R
    for _ in range(20):
        docs.append(_trade(85, "A", 1.5, 2.0, -0.2))
        docs.append(_trade(45, "D", -0.8, 0.1, -1.0))
    rep = generate_report(_DB(docs), days=3650, min_n=5)
    assert rep["correlation"]["spearman_tqs_vs_mfe_r"] is not None
    assert rep["correlation"]["spearman_tqs_vs_mfe_r"] > 0.15
    assert rep["verdict"] == "predictive"
    grades = {g["bucket"]: g for g in rep["by_grade"]}
    assert grades["A"]["avg_mfe_r"] > grades["D"]["avg_mfe_r"]


def test_non_predictive_when_tqs_unrelated_to_mfe():
    docs = []
    # both grades realize the SAME low-MFE / slight-loss distribution
    for i in range(40):
        g, s = ("A", 82) if i % 2 == 0 else ("D", 44)
        docs.append(_trade(s, g, -0.1, 0.15, -0.25))
    rep = generate_report(_DB(docs), days=3650, min_n=5)
    c = rep["correlation"]["spearman_tqs_vs_mfe_r"]
    assert c is None or abs(c) < 0.05
    assert rep["verdict"] in ("non_predictive", "insufficient")


def test_inverted_when_high_tqs_worse():
    docs = []
    for _ in range(20):
        docs.append(_trade(85, "A", -1.0, 0.05, -1.2))   # high TQS, terrible
        docs.append(_trade(45, "D", 1.2, 1.8, -0.2))      # low TQS, great
    rep = generate_report(_DB(docs), days=3650, min_n=5)
    assert rep["correlation"]["spearman_tqs_vs_mfe_r"] < 0
    assert rep["verdict"] == "inverted"


def test_empty_db_safe():
    rep = generate_report(None, days=30)
    assert rep["by_grade"] == [] and rep["overall"] == {}
