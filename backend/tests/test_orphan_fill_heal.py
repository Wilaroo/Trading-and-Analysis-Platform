"""DB-free proof of the Seal #2 write-gap probe (base-trade_id-keyed, period+mechanism):
  • bare FILLED entry, no bot_trade, post-fix, downstream orphan → became_reconciled_orphan,
    $-linked once even with a derived CLOSE-<id> leg sharing the base;
  • a base listed in bracket_lifecycle_events.merged_from_siblings → consolidated_in_memory;
  • a trade_id with a bot_trade → ignored;  derived-only base → exit_only (not a gap);
  • pending (non-fill) → excluded.
"""
from datetime import datetime, timezone


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def _match(self, q, r):
        for k, v in q.items():
            rv = r.get(k)
            if isinstance(v, dict):
                if "$in" in v and rv not in v["$in"]:
                    return False
                if "$ne" in v and rv == v["$ne"]:
                    return False
                if "$gte" in v and not (rv is not None and str(rv) >= v["$gte"]):
                    return False
                if "$exists" in v and (rv is not None) != v["$exists"]:
                    return False
            elif k == "$or":
                if not any(self._match(sub, r) for sub in v):
                    return False
            elif rv != v:
                return False
        return True

    def find(self, q=None, proj=None):
        return [dict(r) for r in self.rows if self._match(q or {}, r)]

    def find_one(self, q=None, proj=None, sort=None):
        res = self.find(q, proj)
        return res[0] if res else None


class _DB:
    def __init__(self, colls):
        self._c = colls

    def __getitem__(self, name):
        return self._c.get(name, _Coll([]))


def run():
    now = datetime.now(timezone.utc).isoformat()   # post-2026-05-05
    order_queue = [
        {"trade_id": "GHOST1", "symbol": "VRT", "status": "filled", "action": "BUY",
         "filled_qty": 100, "fill_price": 90.0, "executed_at": now, "queued_at": now},
        {"trade_id": "CLOSE-GHOST1", "symbol": "VRT", "status": "filled", "action": "SELL",
         "filled_qty": 100, "fill_price": 86.0, "executed_at": now, "queued_at": now},
        {"trade_id": "REAL1", "symbol": "AAPL", "status": "filled", "action": "BUY",
         "filled_qty": 50, "fill_price": 200.0, "executed_at": now, "queued_at": now},
        {"trade_id": "ADOPT-STOP-XONLY", "symbol": "GM", "status": "filled", "action": "SELL",
         "filled_qty": 10, "fill_price": 75.0, "executed_at": now, "queued_at": now},
        {"trade_id": "MERGED1", "symbol": "NVDA", "status": "filled", "action": "BUY",
         "filled_qty": 20, "fill_price": 120.0, "executed_at": now, "queued_at": now},
        {"trade_id": "UNTRK1", "symbol": "IBIT", "status": "filled", "action": "BUY",
         "filled_qty": 5, "fill_price": 60.0, "executed_at": now, "queued_at": now},
        {"trade_id": "PEND1", "symbol": "TSLA", "status": "pending", "action": "BUY",
         "quantity": 10, "queued_at": now},
    ]
    bot_trades = [
        {"id": "REAL1", "symbol": "AAPL", "status": "open"},
        {"id": "ORPH9", "symbol": "VRT", "setup_type": "reconciled_orphan",
         "status": "closed", "realized_pnl": -400.0, "risk_amount": 200.0,
         "close_reason": "oca_closed_externally", "entry_time": now, "closed_at": now},
    ]
    lifecycle = [{"merged_from_siblings": ["MERGED1"]}]
    db = _DB({"order_queue": _Coll(order_queue), "bot_trades": _Coll(bot_trades),
              "bracket_lifecycle_events": _Coll(lifecycle)})

    from services.orphan_fill_heal import generate_report
    rep = generate_report(db, days=120)
    import json
    print(json.dumps(rep, indent=2, default=str))

    cls = rep["population"]["classes"]
    assert cls.get("entry_write_gap") == 3, "GHOST1, MERGED1, UNTRK1 = bare entries w/o record"
    assert cls.get("exit_only_orders_no_base") == 1, "ADOPT-STOP-XONLY = exit-only"
    assert cls.get("has_record") == 1, "REAL1 ignored"
    assert rep["by_period"].get("post_fix") == 3
    pm = rep["post_fix_mechanism"]
    assert pm.get("consolidated_in_memory", {}).get("n") == 1, "MERGED1 = consolidated"
    assert pm.get("became_reconciled_orphan", {}).get("n") == 1, "GHOST1 = orphan"
    assert pm.get("truly_untracked", {}).get("n") == 1, "NVDA = untracked, $0"
    ll = rep["live_leak"]
    assert ll["n_post_fix_orphan_gaps"] == 1
    assert ll["leaked_usd"] == -400.0, "orphan counted ONCE despite the CLOSE leg"
    assert ll["n_distinct_orphans"] == 1
    s = rep["samples"][0]
    assert s["base_trade_id"] == "GHOST1" and s["symbol"] == "VRT"
    assert s["direction"] == "long" and s["entry_price"] == 90.0 and s["filled_qty"] == 100
    print("\n✅ SEAL #2 PROBE OK — period split + mechanism buckets correct, $-linked once")


if __name__ == "__main__":
    run()
