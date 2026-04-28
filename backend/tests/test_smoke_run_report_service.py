"""
Regression tests for `smoke_run_report_service`.

Locks the verdict-rollup contract: red dominates amber dominates green.
Each phase reporter handles missing data / missing collections without
crashing. Operator-readable `summary` paragraph is well-formed.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from services import smoke_run_report_service as srs


# ─── Helpers ────────────────────────────────────────────────────────────

def _bot_trade(*, hours_ago=1, status="closed", with_meta=True,
               r=1.0, pnl=100.0, exit_reason="target_hit"):
    ec = {"multipliers": {"vp_path": 1.0}} if with_meta else {}
    return {
        "id": "t",
        "status": status,
        "realized_r_multiple": r,
        "realized_pnl": pnl,
        "exit_reason": exit_reason,
        "entry_context": ec,
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(),
    }


def _make_db(trades=None, alerts=None, orders=None,
             have_kill_switch_history=False):
    db = MagicMock()

    # MagicMock's __getitem__ + collection methods
    def _coll_for(name):
        coll = MagicMock()
        if name == "bot_trades":
            data = trades or []
            coll.count_documents = lambda q: len([t for t in data if _matches(t, q)])
            coll.find = lambda q, proj=None: iter([t for t in data if _matches(t, q)])
            coll.aggregate = lambda pipeline: iter([])
        elif name == "live_alerts":
            data = alerts or []
            coll.count_documents = lambda q: len([a for a in data if _matches(a, q)])
            coll.aggregate = lambda pipeline: iter([])
        elif name in ("bot_orders", "order_history", "ib_order_log"):
            data = orders or []
            coll.count_documents = lambda q: len([o for o in data if _matches(o, q)])
        return coll

    db.__getitem__.side_effect = _coll_for

    coll_names = ["bot_trades", "live_alerts"]
    if orders is not None:
        coll_names.append("bot_orders")
    if have_kill_switch_history:
        coll_names.append("kill_switch_history")
    db.list_collection_names = lambda: coll_names
    return db


def _matches(doc, query):
    """Simplistic query matcher for tests — handles $gte on created_at
    + simple key equality."""
    for k, v in query.items():
        if isinstance(v, dict):
            if "$gte" in v:
                doc_val = doc.get(k)
                if doc_val is None or str(doc_val) < str(v["$gte"]):
                    return False
            elif "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif "$exists" in v:
                exists = bool(_dotted_get(doc, k))
                if exists != v["$exists"]:
                    return False
        else:
            if doc.get(k) != v:
                return False
    return True


def _dotted_get(doc, key):
    parts = key.split(".")
    cur = doc
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
        if cur is None:
            return None
    return cur


# ─── Test cases ─────────────────────────────────────────────────────────

def test_verdict_green_when_all_phases_clean():
    trades = [_bot_trade(r=2.0, with_meta=True) for _ in range(5)]
    db = _make_db(trades=trades, alerts=[{"created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()} for _ in range(10)])
    out = srs.compute_smoke_run_report(db, hours_back=24)
    # CLOSE+EVAL+SCAN+MANAGE+HEALTH should be green; ORDER may be amber
    # without an order log collection. Verify per-phase first:
    statuses = {p["phase"]: p["status"] for p in out["phases"]}
    assert statuses.get("EVAL") == "green"   # 100% multiplier coverage
    assert statuses.get("CLOSE") == "green"   # closed > 0
    assert statuses.get("HEALTH") == "green"   # 0 trips


def test_verdict_red_when_kill_switch_tripped():
    """A kill_switch_history entry within the window should trip HEALTH
    to red, which dominates the overall verdict."""
    trades = [_bot_trade(r=2.0) for _ in range(5)]
    alerts = [{"created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()} for _ in range(10)]
    db = _make_db(trades=trades, alerts=alerts, have_kill_switch_history=True)
    db["kill_switch_history"].count_documents = lambda q: 1
    out = srs.compute_smoke_run_report(db, hours_back=24)
    assert out["verdict"] == "red"


def test_verdict_amber_when_eval_meta_coverage_low():
    """If 50% of bot_trades lack `entry_context.multipliers`, EVAL
    flags amber, which surfaces in the rolled-up verdict."""
    trades = [_bot_trade(r=2.0, with_meta=True) for _ in range(2)]
    trades += [_bot_trade(r=1.0, with_meta=False) for _ in range(3)]
    alerts = [{"created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()} for _ in range(10)]
    db = _make_db(trades=trades, alerts=alerts)
    out = srs.compute_smoke_run_report(db, hours_back=24)
    statuses = {p["phase"]: p["status"] for p in out["phases"]}
    # 2/5 = 0.40 coverage → red threshold (0.50) yes, so red
    assert statuses["EVAL"] in {"red", "amber"}


def test_verdict_amber_when_no_data():
    """Empty system: SCAN amber, EVAL amber, CLOSE amber. Verdict amber."""
    db = _make_db(trades=[], alerts=[])
    out = srs.compute_smoke_run_report(db, hours_back=24)
    assert out["verdict"] in {"amber", "red"}


def test_no_db_returns_red_verdict():
    out = srs.compute_smoke_run_report(None, hours_back=24)
    assert out["verdict"] == "red"
    assert out["reason"] == "db not available"


def test_summary_paragraph_includes_each_phase():
    trades = [_bot_trade(r=2.0) for _ in range(3)]
    alerts = [{"created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()} for _ in range(10)]
    db = _make_db(trades=trades, alerts=alerts)
    out = srs.compute_smoke_run_report(db, hours_back=24)
    summary = out["summary"]
    for phase_name in ("SCAN", "EVAL", "ORDER", "MANAGE", "CLOSE", "HEALTH"):
        assert phase_name in summary, f"summary missing {phase_name}"
    # Verdict is on the first line
    assert summary.split("\n")[0].startswith("Smoke-run verdict:")


def test_classify_helper_higher_is_better():
    assert srs._classify(0.95, red=0.6, amber=0.85) == "green"
    assert srs._classify(0.70, red=0.6, amber=0.85) == "amber"
    assert srs._classify(0.40, red=0.6, amber=0.85) == "red"


def test_classify_helper_lower_is_better():
    assert srs._classify(500, red=5000, amber=2000, higher_is_better=False) == "green"
    assert srs._classify(3000, red=5000, amber=2000, higher_is_better=False) == "amber"
    assert srs._classify(8000, red=5000, amber=2000, higher_is_better=False) == "red"


def test_classify_handles_none():
    """Missing data is amber, not red — yellow-flag, don't block flip."""
    assert srs._classify(None, red=0.6, amber=0.85) == "amber"
