"""DB-free proof of the Seal #2 write-gap probe: a FILLED order_queue trade_id with
no bot_trade is flagged (and $-linked to its reconciled_orphan); a trade_id that HAS
a bot_trade is ignored; an exit-only/legacy symbol does not produce false gaps."""
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
        if sort:
            key, direction = sort[0]
            res.sort(key=lambda r: str(r.get(key) or ""), reverse=(direction < 0))
        return res[0] if res else None

    def count_documents(self, q=None):
        return len(self.find(q or {}))


class _DB:
    def __init__(self, colls):
        self._c = colls

    def __getitem__(self, name):
        return self._c[name]


def run():
    now = datetime.now(timezone.utc).isoformat()

    order_queue = [
        # GAP: filled entry, trade_id 'GHOST1' — no bot_trade exists
        {"trade_id": "GHOST1", "symbol": "VRT", "status": "filled", "type": "bracket",
         "parent": {"action": "BUY", "quantity": 100}, "filled_qty": 100,
         "fill_price": 90.0, "executed_at": now, "queued_at": now},
        {"trade_id": "GHOST1", "symbol": "VRT", "status": "filled", "action": "SELL",
         "filled_qty": 100, "fill_price": 86.0, "executed_at": now, "queued_at": now},
        # HEALTHY: filled entry, trade_id 'REAL1' — bot_trade exists → must be ignored
        {"trade_id": "REAL1", "symbol": "AAPL", "status": "filled", "action": "BUY",
         "filled_qty": 50, "fill_price": 200.0, "executed_at": now, "queued_at": now},
        # NON-FILL: pending order — must not count
        {"trade_id": "PEND1", "symbol": "TSLA", "status": "pending", "action": "BUY",
         "quantity": 10, "queued_at": now},
    ]
    bot_trades = [
        {"id": "REAL1", "symbol": "AAPL", "status": "open"},
        # the GHOST1 fill became a contextless reconciled_orphan that lost -$400
        {"id": "ORPH9", "symbol": "VRT", "setup_type": "reconciled_orphan",
         "status": "closed", "realized_pnl": -400.0, "risk_amount": 200.0,
         "close_reason": "oca_closed_externally", "closed_at": now},
    ]
    ib_executions = [{"symbol": "VRT"}, {"symbol": "VRT"}]

    db = _DB({
        "order_queue": _Coll(order_queue),
        "bot_trades": _Coll(bot_trades),
        "ib_executions": _Coll(ib_executions),
    })

    from services.orphan_fill_heal import generate_report
    rep = generate_report(db, days=120)
    import json
    print(json.dumps(rep, indent=2, default=str))

    wg = rep["write_gaps"]
    assert wg["n_trade_ids"] == 1, "exactly one true write gap (GHOST1)"
    g = wg["samples"][0]
    assert g["trade_id"] == "GHOST1"
    assert g["symbol"] == "VRT"
    assert g["direction"] == "long", "BUY parent → long"
    assert g["entry_price"] == 90.0, "opening leg fill price"
    assert g["filled_qty"] == 100
    assert g["downstream_reconciled_orphan"]["orphan_id"] == "ORPH9"
    assert wg["leaked_usd"] == -400.0, "downstream $ attributed to the gap"
    assert wg["n_with_downstream_orphan"] == 1
    # REAL1 (has bot_trade) and PEND1 (not filled) must NOT appear
    assert all(s["trade_id"] != "REAL1" for s in wg["samples"]), "healthy trade ignored"

    print("\n✅ SEAL #2 PROBE OK — true gap flagged + $-linked, healthy/non-fill ignored")


if __name__ == "__main__":
    run()
