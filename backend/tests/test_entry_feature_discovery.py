"""Read-only entry feature-discovery — continuous spearman + categorical eta^2."""
from __future__ import annotations
import os, sys

HERE = os.path.dirname(__file__)
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from services.entry_feature_discovery import generate_report, _eta2, _minutes_from_open


class _Coll:
    def __init__(self, docs): self._docs = docs
    def find(self, q, proj=None):
        return [d for d in self._docs if d.get("status") == q.get("status", d.get("status"))]


class _DB:
    def __init__(self, docs): self._docs = docs
    def __getitem__(self, name): return _Coll(self._docs)


def _trade(setup, regime, rvol, r, mfe, tw="morning"):
    return {"status": "closed", "realized_pnl": r, "risk_amount": 1.0, "mfe_r": mfe,
            "setup_type": setup, "direction": "long", "timeframe": "scalp",
            "tape_score": 5, "entry_price": 100.0,
            "entry_context": {"scanner_setup_type": setup, "market_regime": regime,
                              "rvol": rvol, "time_window": tw,
                              "technicals": {"trend": "up", "vwap_relation": "above"},
                              "confidence_gate": {"decision": "go", "confidence_score": 50}}}


def test_minutes_from_open():
    assert _minutes_from_open("09:30:00") == 0
    assert _minutes_from_open("10:30:00") == 60
    assert _minutes_from_open("bad") is None


def test_eta2_perfect_separation():
    # two groups with zero within-variance, different means → eta2 == 1.0
    assert _eta2({"a": [1.0, 1.0, 1.0], "b": [2.0, 2.0, 2.0]}) == 1.0
    # identical groups → eta2 == 0.0
    assert _eta2({"a": [1.0, 2.0], "b": [1.0, 2.0]}) == 0.0


def test_continuous_signal_detected():
    # rvol strongly tracks MFE; build 80 trades where higher rvol → higher mfe/r
    docs = []
    for i in range(80):
        hi = i % 2 == 0
        docs.append(_trade("breakout", "trend", 3.0 if hi else 0.5,
                            1.2 if hi else -0.7, 1.9 if hi else 0.1))
    rep = generate_report(_DB(docs), days=3650, min_n=20, cat_min=10)
    cont = {c["feature"]: c for c in rep["continuous"]}
    assert cont["rvol"]["spearman_vs_mfe"] > 0.5


def test_categorical_setup_type_separates():
    docs = []
    for _ in range(30):
        docs.append(_trade("vwap_continuation", "trend", 1.5, 1.0, 1.6))   # winners
    for _ in range(30):
        docs.append(_trade("daily_breakout", "chop", 1.5, -0.8, 0.1))      # losers
    rep = generate_report(_DB(docs), days=3650, min_n=20, cat_min=10)
    cat = {c["feature"]: c for c in rep["categorical"]}
    assert cat["setup_type"]["eta2_vs_r"] is not None and cat["setup_type"]["eta2_vs_r"] > 0.3
    assert cat["setup_type"]["best"][0]["value"] == "vwap_continuation"


def test_empty_db_safe():
    rep = generate_report(None, days=30)
    assert rep["continuous"] == [] and rep["categorical"] == [] and rep["n"] == 0
