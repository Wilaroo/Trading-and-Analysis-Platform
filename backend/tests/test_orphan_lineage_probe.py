"""Unit tests for the orphan lineage forensic probe (read-only)."""
from datetime import datetime, timezone, timedelta

from services.orphan_lineage_probe import generate_report

NOW = datetime.now(timezone.utc)


def _iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def _orphan(symbol, direction, usd, **kw):
    return {
        "id": kw.get("id", f"orph_{symbol}"), "symbol": symbol,
        "direction": direction, "status": "closed",
        "setup_type": "reconciled_orphan", "entered_by": "reconciled_external",
        "realized_pnl": usd, "risk_amount": kw.get("risk", 200.0),
        "shares": kw.get("shares", 100), "original_shares": kw.get("shares", 100),
        "close_reason": kw.get("close_reason", "oca_closed_externally_v19_31"),
        "entry_time": kw.get("entry_time", _iso(2)),
        "closed_at": kw.get("closed_at", _iso(1)),
    }


def _genuine(symbol, direction, days_ago, **kw):
    return {
        "id": kw.get("id", f"gen_{symbol}"), "symbol": symbol,
        "direction": direction, "status": "closed",
        "setup_type": kw.get("setup_type", "vwap_bounce"),
        "entered_by": kw.get("entered_by", "bot"),
        "close_reason": kw.get("close_reason", "target_1_complete"),
        "entry_time": _iso(days_ago), "closed_at": _iso(days_ago),
        "stop_price": 95.0,
    }


def _match(doc, q):
    for k, cond in q.items():
        if k == "$or":
            if not any(_match(doc, s) for s in cond):
                return False
            continue
        v = doc.get(k)
        if isinstance(cond, dict):
            if "$gte" in cond and not (v is not None and v >= cond["$gte"]):
                return False
            if "$nin" in cond and v in cond["$nin"]:
                return False
        elif v != cond:
            return False
    return True


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a, **k):
        key = a[0] if a else "entry_time"
        self.rows = sorted(self.rows, key=lambda r: r.get(key) or "", reverse=True)
        return self

    def limit(self, n):
        return iter(self.rows[:n])

    def __iter__(self):
        return iter(self.rows)


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def find(self, q=None, proj=None):
        return _Cur([dict(r) for r in self.rows if _match(r, q or {})])

    def count_documents(self, q):
        return sum(1 for r in self.rows if _match(r, q))


class _DB:
    def __init__(self, trades, order_queue=None, ib_exec=None):
        self._c = {"bot_trades": _Coll(trades),
                   "order_queue": _Coll(order_queue or []),
                   "ib_executions": _Coll(ib_exec or [])}

    def __getitem__(self, n):
        return self._c.get(n, _Coll([]))


def _find(rep, cls):
    for row in rep["lineage"]:
        if row["lineage_class"] == cls:
            return row
    return None


def test_old_lineage_beyond_window():
    db = _DB([_orphan("UAL", "long", -666.0), _genuine("UAL", "long", 300)])
    rep = generate_report(db, lineage_window_days=240)
    row = _find(rep, "old_lineage")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["pred_recency_days_ago"] > 240


def test_relinkable_lineage_within_window():
    db = _DB([_orphan("AAPL", "long", -10.0), _genuine("AAPL", "long", 30)])
    rep = generate_report(db, lineage_window_days=240)
    assert _find(rep, "relinkable_lineage")["n"] == 1


def test_order_no_trade():
    db = _DB([_orphan("SHLD", "short", -815.0)],
             order_queue=[{"symbol": "SHLD", "action": "SELL", "created_at": _iso(5)}])
    row = _find(generate_report(db), "order_no_trade")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["order_queue_hits"] == 1


def test_truly_absent():
    db = _DB([_orphan("VRT", "short", -465.0)])
    row = _find(generate_report(db), "truly_absent")
    assert row and row["n"] == 1
    assert row["samples"][0]["evidence"]["order_queue_hits"] == 0


def test_reconciled_predecessor_not_counted_as_lineage():
    # A bot_trade with reconciled entered_by must NOT count as genuine lineage
    # (passes the setup $nin filter but is rejected in-loop) → truly_absent.
    db = _DB([_orphan("XYZ", "long", -5.0),
              _genuine("XYZ", "long", 10, setup_type="vwap_bounce",
                       entered_by="reconciled_external", id="recon_slice")])
    assert _find(generate_report(db), "truly_absent")["n"] == 1


def test_empty_safe():
    assert generate_report(None)["report_period_days"] == 120
    assert generate_report(_DB([]))["population"]["n_closed_orphans"] == 0
