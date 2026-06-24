"""v404 — _find_reaped_pending matching logic (orphan re-link recovery).

Validates the read-only Mongo lookup that lets the reconciler inherit a reaped
pending's REAL stop/target instead of a synthetic 2% stop. Uses a fake db; the
fake's find() returns the provided docs (simulating the symbol/direction/regex/
window query already matched) so we exercise the python-side guards: stop
validity, directional consistency, and quantity sanity.
"""
from services.position_reconciler import PositionReconciler


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return iter(self._docs)


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *a, **k):
        return _Cursor(self._docs)


class _DB:
    def __init__(self, docs):
        self._c = _Coll(docs)

    def __getitem__(self, name):
        return self._c


def _mk(**over):
    d = {
        "id": "t1", "symbol": "AAPL", "direction": "long",
        "close_reason": "stale_pending_auto_reaper",
        "stop_price": 95.0, "target_prices": [110.0],
        "original_shares": 100, "shares": 100,
        "market_regime": "BULL",
        "entry_context": {"tqs": {"pillar_scores": {"setup": 60}}},
        "reaped_at": "2026-06-24T15:00:00+00:00",
    }
    d.update(over)
    return d


def _recon(docs):
    r = PositionReconciler.__new__(PositionReconciler)
    r._db = _DB(docs)
    return r


def test_match_returns_real_bracket():
    r = _recon([_mk()])
    m = r._find_reaped_pending("AAPL", "long", 100, avg_cost=100.0)
    assert m is not None
    assert m["id"] == "t1"
    assert m["stop_price"] == 95.0
    assert m["target_1"] == 110.0
    assert m["market_regime"] == "BULL"


def test_directional_mismatch_long_stop_above_cost_skipped():
    # LONG but stop is ABOVE avg_cost -> not a valid long stop -> no match.
    r = _recon([_mk(stop_price=105.0)])
    assert r._find_reaped_pending("AAPL", "long", 100, avg_cost=100.0) is None


def test_short_match():
    r = _recon([_mk(direction="short", stop_price=105.0, target_prices=[90.0])])
    m = r._find_reaped_pending("AAPL", "short", 100, avg_cost=100.0)
    assert m is not None and m["stop_price"] == 105.0


def test_qty_ratio_out_of_range_skipped():
    # orphan qty 10 vs original 100 -> ratio 0.1 < 0.5 -> skip.
    r = _recon([_mk(original_shares=100)])
    assert r._find_reaped_pending("AAPL", "long", 10, avg_cost=100.0) is None


def test_missing_stop_skipped():
    r = _recon([_mk(stop_price=None)])
    assert r._find_reaped_pending("AAPL", "long", 100, avg_cost=100.0) is None


def test_no_docs_returns_none():
    r = _recon([])
    assert r._find_reaped_pending("AAPL", "long", 100, avg_cost=100.0) is None


def test_picks_first_valid_when_first_invalid():
    docs = [_mk(id="bad", stop_price=105.0),   # invalid (long stop above cost)
            _mk(id="good", stop_price=96.0)]    # valid
    r = _recon(docs)
    m = r._find_reaped_pending("AAPL", "long", 100, avg_cost=100.0)
    assert m is not None and m["id"] == "good"


# ── v407 — _find_recent_bot_predecessor (generalized relink) ──

def test_predecessor_matches_any_close_reason():
    # Not a stale_pending — an eod_auto_close / readopt predecessor still matches.
    r = _recon([_mk(close_reason="eod_auto_close_v162")])
    m = r._find_recent_bot_predecessor("AAPL", "long", 100, avg_cost=100.0)
    assert m is not None and m["stop_price"] == 95.0 and m["target_1"] == 110.0


def test_predecessor_excludes_reconciled_entered_by():
    # A prior synthetic/reconciled row must NOT be inherited (no synthetic stop loop).
    r = _recon([_mk(entered_by="reconciled_external")])
    assert r._find_recent_bot_predecessor("AAPL", "long", 100, avg_cost=100.0) is None


def test_predecessor_directional_and_qty_guards():
    # long stop above cost -> skip; qty ratio out of range -> skip.
    assert _recon([_mk(stop_price=105.0)]) \
        ._find_recent_bot_predecessor("AAPL", "long", 100, avg_cost=100.0) is None
    assert _recon([_mk(original_shares=100)]) \
        ._find_recent_bot_predecessor("AAPL", "long", 10, avg_cost=100.0) is None


def test_predecessor_short_match():
    r = _recon([_mk(direction="short", stop_price=105.0, target_prices=[90.0],
                    close_reason="oca_closed_externally_v19_31")])
    m = r._find_recent_bot_predecessor("AAPL", "short", 100, avg_cost=100.0)
    assert m is not None and m["stop_price"] == 105.0
