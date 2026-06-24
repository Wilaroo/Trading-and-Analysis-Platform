"""orphan_leak_rca report logic — predecessor linkage + re-adopt-loop detection.

Uses a tiny fake collection so we can exercise the pure python without Mongo.
"""
from datetime import datetime, timezone, timedelta
from services.orphan_leak_rca import generate_report


class _FakeColl:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query=None, proj=None):
        # Tests use recent timestamps so the days-cutoff $or always passes;
        # return everything and let the python logic do the work.
        return list(self._docs)


class _FakeDB:
    def __init__(self, docs):
        self._coll = _FakeColl(docs)

    def __getitem__(self, name):
        assert name == "bot_trades"
        return self._coll


def _iso(dt):
    return dt.isoformat()


def _build_docs():
    now = datetime.now(timezone.utc)
    # Predecessor: real bot trade, regime known, WIDE stop (5%), closed externally.
    pred = {
        "id": "pred1", "symbol": "AAPL", "direction": "long", "status": "closed",
        "setup_type": "trend_continuation", "entry_price": 100.0, "stop_price": 95.0,
        "realized_pnl": -50.0, "risk_amount": 100.0,
        "close_reason": "oca_closed_externally_v19_31", "market_regime": "BULL",
        "entry_context": {"tqs": {"pillar_scores": {"setup": 60}}, "reconciled": False},
        "entry_time": _iso(now - timedelta(hours=3)),
        "closed_at": _iso(now - timedelta(minutes=30)),
        "created_at": _iso(now - timedelta(hours=3)),
    }
    # Orphan: spawned 30m after pred close, TIGHT 2% stop, default_pct, loses.
    orphan = {
        "id": "orph1", "symbol": "AAPL", "direction": "long", "status": "closed",
        "setup_type": "reconciled_orphan", "synthetic_source": "default_pct",
        "entry_price": 101.0, "stop_price": 98.98,  # ~2% stop
        "realized_pnl": -200.0, "risk_amount": 100.0,
        "close_reason": "oca_closed_externally_v19_31", "market_regime": "UNKNOWN",
        "entry_context": {"reconciled": True},
        "entry_time": _iso(now),
        "closed_at": _iso(now + timedelta(minutes=20)),
        "created_at": _iso(now),
    }
    return [pred, orphan]


def test_population_and_close_reasons():
    rep = generate_report(_FakeDB(_build_docs()), days=120, gap_min=120)
    assert rep["population"]["n_closed_orphans"] == 1
    assert rep["population"]["negative_r_count"] == 1
    assert rep["population"]["total_clean_r"] == -2.0
    assert rep["close_reasons"][0]["reason"] == "oca_closed_externally_v19_31"


def test_predecessor_linkage_recoverable_and_tighter():
    rep = generate_report(_FakeDB(_build_docs()), days=120, gap_min=120)
    pl = rep["predecessor_linkage"]
    assert pl["with_predecessor"] == 1
    assert pl["recoverable_context"] == 1          # pred had tqs + BULL regime
    assert pl["orphan_stop_tighter_than_predecessor"] == 1  # 2% < 5%


def test_readopt_loop_detected_within_window():
    rep = generate_report(_FakeDB(_build_docs()), days=120, gap_min=120)
    loop = rep["readopt_loop"]
    assert loop["n"] == 1
    assert loop["leak_r"] == -2.0
    assert loop["samples"][0]["symbol"] == "AAPL"


def test_readopt_loop_excluded_when_gap_too_large():
    docs = _build_docs()
    # Push the orphan entry 5h after pred close -> outside a 120m window.
    pred_close = datetime.fromisoformat(docs[0]["closed_at"])
    docs[1]["entry_time"] = (pred_close + timedelta(hours=5)).isoformat()
    docs[1]["created_at"] = docs[1]["entry_time"]
    rep = generate_report(_FakeDB(docs), days=120, gap_min=120)
    assert rep["readopt_loop"]["n"] == 0
    # still linked as a predecessor, just not a tight re-adopt loop
    assert rep["predecessor_linkage"]["with_predecessor"] == 1


def test_empty_db_safe():
    rep = generate_report(_FakeDB([]), days=120)
    assert rep["population"]["n_closed_orphans"] == 0
