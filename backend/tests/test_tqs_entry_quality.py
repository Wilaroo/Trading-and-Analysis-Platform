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


def _ptrade(setup, tech, fund, ctx_, exe, r, mfe):
    return {"status": "closed", "realized_pnl": r, "risk_amount": 1.0, "mfe_r": mfe,
            "entry_context": {"tqs": {
                "pillar_scores": {"setup": setup, "technical": tech, "fundamental": fund,
                                  "context": ctx_, "execution": exe},
                "weights": {"setup": 0.15, "technical": 0.10, "fundamental": 0.40,
                            "context": 0.20, "execution": 0.15},
                "post_gate_score": 50.0}}}


def test_pillar_predictiveness_finds_signal_pillar():
    from services.tqs_entry_quality import generate_pillar_report
    docs = []
    # 'technical' tracks MFE strongly; 'fundamental' is pure noise.
    for i in range(60):
        hi = i % 2 == 0
        tech = 80 if hi else 30
        fund = 30 if hi else 80          # inversely related to outcome
        mfe = 1.8 if hi else 0.1
        r = 1.2 if hi else -0.8
        docs.append(_ptrade(50, tech, fund, 50, 50, r, mfe))
    rep = generate_pillar_report(_DB(docs), days=3650, min_n=10)
    by = {p["pillar"]: p for p in rep["pillars"]}
    assert by["technical"]["spearman_vs_mfe"] > 0.5
    assert by["fundamental"]["spearman_vs_mfe"] < 0
    assert rep["pillars"][0]["pillar"] == "technical"      # ranked most-predictive
    assert rep["current_weights"]["fundamental"] == 0.40   # modal weights surfaced
    assert "technical" in rep["suggested_weights_by_mfe_signal"]


def test_pillar_report_empty_db_safe():
    from services.tqs_entry_quality import generate_pillar_report
    rep = generate_pillar_report(None, days=30)
    assert rep["pillars"] == [] and rep["n"] == 0
