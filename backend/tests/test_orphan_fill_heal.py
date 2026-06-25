"""DB-free proof of the Seal #2 write-gap probe (v2, base-trade_id-keyed):
  • a bare FILLED entry with no bot_trade → ONE entry_write_gap, $-linked once
    even though a derived CLOSE-<id> leg shares its base id;
  • a trade_id that HAS a bot_trade is ignored;
  • a base seen ONLY via a derived CLOSE-<id> leg → exit_only (NOT a gap);
  • a pending (non-fill) order is excluded.
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
        return self._c[name]


def run():
    now = datetime.now(timezone.utc).isoformat()
    order_queue = [
        # entry write gap: bare BUY 'GHOST1' filled, no bot_trade
        {"trade_id": "GHOST1", "symbol": "VRT", "status": "filled", "action": "BUY",
         "filled_qty": 100, "fill_price": 90.0, "executed_at": now, "queued_at": now},
        # derived CLOSE leg shares base GHOST1 → must NOT create a second gap
        {"trade_id": "CLOSE-GHOST1", "symbol": "VRT", "status": "filled", "action": "SELL",
         "filled_qty": 100, "fill_price": 86.0, "executed_at": now, "queued_at": now},
        # healthy: bare BUY 'REAL1' filled, bot_trade exists → ignored
        {"trade_id": "REAL1", "symbol": "AAPL", "status": "filled", "action": "BUY",
         "filled_qty": 50, "fill_price": 200.0, "executed_at": now, "queued_at": now},
        # exit-only base: only a derived ADOPT-STOP leg, no bare entry, no bot_trade
        {"trade_id": "ADOPT-STOP-XONLY", "symbol": "GM", "status": "filled", "action": "SELL",
         "filled_qty": 10, "fill_price": 75.0, "executed_at": now, "queued_at": now},
        # pending (non-fill) → excluded
        {"trade_id": "PEND1", "symbol": "TSLA", "status": "pending", "action": "BUY",
         "quantity": 10, "queued_at": now},
    ]
    bot_trades = [
        {"id": "REAL1", "symbol": "AAPL", "status": "open"},
        {"id": "ORPH9", "symbol": "VRT", "setup_type": "reconciled_orphan",
         "status": "closed", "realized_pnl": -400.0, "risk_amount": 200.0,
         "close_reason": "oca_closed_externally", "entry_time": now, "closed_at": now},
    ]
    db = _DB({"order_queue": _Coll(order_queue), "bot_trades": _Coll(bot_trades)})

    from services.orphan_fill_heal import generate_report
    rep = generate_report(db, days=120)
    import json
    print(json.dumps(rep, indent=2, default=str))

    wg = rep["write_gaps"]
    assert wg["n_entry_write_gaps"] == 1, "exactly one entry write gap (GHOST1 base)"
    assert wg["n_exit_only_orders_no_base"] == 1, "ADOPT-STOP-XONLY = exit-only, not a gap"
    assert wg["n_distinct_downstream_orphans"] == 1
    assert wg["leaked_usd_dedup"] == -400.0, "orphan counted ONCE despite the CLOSE leg"
    g = wg["samples"][0]
    assert g["base_trade_id"] == "GHOST1" and g["symbol"] == "VRT"
    assert g["direction"] == "long" and g["entry_price"] == 90.0 and g["filled_qty"] == 100
    assert all(s["base_trade_id"] != "REAL1" for s in wg["samples"]), "healthy trade ignored"
    print("\n✅ SEAL #2 PROBE v2 OK — derived legs normalized, gap $-linked once, "
          "exit-only excluded, healthy/non-fill ignored")


if __name__ == "__main__":
    run()
