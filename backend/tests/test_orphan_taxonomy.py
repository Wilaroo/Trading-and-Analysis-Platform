"""Unit tests for the orphan creation-cause taxonomy (read-only diagnostic).

A tiny fake Mongo (list-backed find with $or/$gte/$regex + count) drives the
classifier through each creation class so the priority order and markers are
verified without a live DB.
"""
import re
from datetime import datetime, timezone, timedelta

from services.orphan_taxonomy import generate_report

NOW = datetime.now(timezone.utc)


def _iso(mins_ago):
    return (NOW - timedelta(minutes=mins_ago)).isoformat()


def _orphan(symbol, direction, r_pnl, risk, **kw):
    d = {
        "id": kw.get("id", f"orph_{symbol}_{abs(r_pnl)}"),
        "symbol": symbol, "direction": direction,
        "status": "closed", "setup_type": "reconciled_orphan",
        "entered_by": "reconciled_external",
        "entry_price": kw.get("entry_price", 100.0),
        "stop_price": kw.get("stop_price", 98.0),
        "shares": kw.get("shares", 100),
        "original_shares": kw.get("original_shares", kw.get("shares", 100)),
        "realized_pnl": r_pnl, "risk_amount": risk,
        "close_reason": kw.get("close_reason", "oca_closed_externally_v19_31"),
        "synthetic_source": kw.get("synthetic_source", "default_pct"),
        "entry_context": kw.get("entry_context", {"reconciled": True}),
        "entry_time": kw.get("entry_time", _iso(60)),
        "closed_at": kw.get("closed_at", _iso(30)),
        "created_at": kw.get("entry_time", _iso(60)),
    }
    return d


def _pred(symbol, direction, close_reason, **kw):
    return {
        "id": kw.get("id", f"pred_{symbol}"),
        "symbol": symbol, "direction": direction,
        "status": "closed", "setup_type": kw.get("setup_type", "vwap_bounce"),
        "entry_price": 100.0, "stop_price": 98.0,
        "shares": kw.get("shares", 100),
        "original_shares": kw.get("original_shares", kw.get("shares", 100)),
        "realized_pnl": kw.get("realized_pnl", 0.0),
        "risk_amount": kw.get("risk_amount", 200.0),
        "close_reason": close_reason,
        "entry_time": kw.get("entry_time", _iso(120)),
        "closed_at": kw.get("closed_at", _iso(90)),
        "reaped_at": kw.get("reaped_at"),
        "created_at": kw.get("entry_time", _iso(120)),
    }


def _match(doc, q):
    for k, cond in q.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        val = doc.get(k)
        if isinstance(cond, dict):
            if "$gte" in cond and not (val is not None and val >= cond["$gte"]):
                return False
            if "$regex" in cond and not (
                    isinstance(val, str) and re.search(cond["$regex"], val)):
                return False
            if "$nin" in cond and val in cond["$nin"]:
                return False
        else:
            if val != cond:
                return False
    return True


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, q=None, proj=None):
        q = q or {}
        return [dict(r) for r in self.rows if _match(r, q)]

    def count_documents(self, q):
        return sum(1 for r in self.rows if _match(r, q))


class _DB:
    def __init__(self, trades, thoughts=None, integrity=None):
        self._c = {
            "bot_trades": _Coll(trades),
            "sentcom_thoughts": _Coll(thoughts or []),
            "state_integrity_events": _Coll(integrity or []),
        }

    def __getitem__(self, name):
        return self._c.get(name, _Coll([]))


def _find(report, cause):
    for row in report["taxonomy"]:
        if row["creation_cause"] == cause:
            return row
    return None


def test_reaped_pending_via_relink_marker():
    o = _orphan("AAA", "long", -100.0, 200.0,
                synthetic_source="relinked_reaped_pending")
    rep = generate_report(_DB([o]))
    row = _find(rep, "reaped_pending_filled")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["marker"] == "relink_marker"


def test_reaped_pending_via_stale_predecessor():
    o = _orphan("BBB", "long", -80.0, 200.0, entry_time=_iso(50))
    p = _pred("BBB", "long", "stale_pending_auto_reaper",
              closed_at=_iso(70), reaped_at=_iso(70))
    rep = generate_report(_DB([o, p]))
    row = _find(rep, "reaped_pending_filled")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["marker"] == "stale_pending_predecessor"
    # relink coverage should flag this as a would-relink observe candidate.
    assert rep["relink_coverage"]["would_relink_observe_marker"] == 1


def test_exit_overfill_residual():
    # Predecessor closed normally; orphan is a 20-share residual of a 100 close.
    o = _orphan("CCC", "short", -40.0, 200.0, shares=20, original_shares=20,
                entry_time=_iso(40), close_reason="oca_closed_externally_v19_31")
    p = _pred("CCC", "long", "target_1_complete", shares=100,
              original_shares=100, closed_at=_iso(50))
    rep = generate_report(_DB([o, p]))
    row = _find(rep, "exit_overfill_residual")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["qty_ratio_orphan_over_pred"] <= 0.75


def test_readopt_loop_full_reappearance():
    # A full-size position closed externally then re-adopted at full qty.
    o = _orphan("GGG", "long", -50.0, 200.0, shares=100, original_shares=100,
                entry_time=_iso(40), close_reason="oca_closed_externally_v19_31")
    p = _pred("GGG", "long", "oca_closed_externally_v19_31", shares=100,
              original_shares=100, closed_at=_iso(70))
    rep = generate_report(_DB([o, p]))
    row = _find(rep, "readopt_loop")
    assert row and row["n"] == 1
    ev = row["samples"][0]["evidence"]
    assert ev["marker"] == "external_close_full_readopt"
    assert ev["qty_ratio_orphan_over_pred"] > 0.75


def test_readopt_loop_dir_flip():
    # A long position closed externally; a SHORT orphan re-appears (dir flip).
    o = _orphan("HHH", "short", -200.0, 200.0, shares=100, original_shares=100,
                entry_time=_iso(30), close_reason="oca_closed_externally_v19_31")
    p = _pred("HHH", "long", "oca_closed_externally_v19_31", shares=100,
              original_shares=100, closed_at=_iso(60))
    rep = generate_report(_DB([o, p]))
    row = _find(rep, "readopt_loop")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["dir_relation"] == "dir_flip"


def test_eod_reopen():
    # A position EOD-closed then re-adopted next session.
    o = _orphan("III", "long", -20.0, 200.0, shares=54, original_shares=54,
                entry_time=_iso(30), close_reason="oca_closed_externally_v19_31")
    p = _pred("III", "long", "eod_auto_close_v162", shares=54,
              original_shares=54, closed_at=_iso(700))
    rep = generate_report(_DB([o, p]))
    row = _find(rep, "eod_reopen")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["marker"] == "eod_auto_close_predecessor"


def test_share_drift_excess_concurrent_open():
    # A concurrently-open bot trade overlaps the orphan's life → drift excess.
    o = _orphan("DDD", "long", -30.0, 200.0,
                entry_time=_iso(40), closed_at=_iso(10))
    concurrent = {
        "id": "open_DDD", "symbol": "DDD", "direction": "long",
        "status": "open", "setup_type": "vwap_bounce",
        "entry_price": 100.0, "stop_price": 98.0, "shares": 100,
        "original_shares": 100, "realized_pnl": 0.0, "risk_amount": 200.0,
        "close_reason": "", "entry_time": _iso(120), "closed_at": None,
        "created_at": _iso(120),
    }
    rep = generate_report(_DB([o, concurrent]))
    row = _find(rep, "share_drift_excess")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["marker"] == "concurrent_open_trade"


def test_restart_orphan_via_boot_event():
    o = _orphan("EEE", "long", -25.0, 200.0, entry_time=_iso(20))
    thought = {"event": "auto_reconcile_at_boot", "timestamp": _iso(24),
               "metadata": {"symbols": ["EEE"]}}
    rep = generate_report(_DB([o], thoughts=[thought]))
    row = _find(rep, "restart_orphan")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["marker"] == "auto_reconcile_at_boot"


def test_true_foreign_no_predecessor():
    o = _orphan("FFF", "long", -10.0, 200.0, entry_time=_iso(30))
    rep = generate_report(_DB([o]))
    row = _find(rep, "true_foreign")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["marker"] == "no_predecessor_in_lookback"


def test_population_and_verdict():
    trades = [
        _orphan("AAA", "long", -100.0, 200.0,
                synthetic_source="relinked_reaped_pending"),
        _orphan("FFF", "long", -10.0, 200.0),
    ]
    rep = generate_report(_DB(trades))
    assert rep["population"]["n_closed_orphans"] == 2
    assert rep["population"]["total_leak_r"] < 0
    assert "biggest $ leak" in rep["verdict"]


def test_empty_db_safe():
    assert generate_report(None)["report_period_days"] == 120
    rep = generate_report(_DB([]))
    assert rep["population"]["n_closed_orphans"] == 0
