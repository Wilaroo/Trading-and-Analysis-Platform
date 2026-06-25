"""DB-free proof of the v414 Seal #2 heal — `_find_orphan_source_bracket`.

The write-gap case: a `type=bracket` ENTRY filled at IB but never got the
v19.34.6 pre-submit bot_trade write, so the orphan reconciler would stamp a
synthetic 2% stop. v414 instead inherits the REAL stop/target from the filled
`order_queue` bracket row — but ONLY when that bracket's trade_id has no
bot_trade row (genuine gap), never stealing a tracked bracket's stop.

Asserts:
  • a FILLED long bracket with no bot_trade → returns its real stop/target;
  • a FILLED bracket whose trade_id HAS a bot_trade → skipped (tracked);
  • a directionally-invalid stop (stop above avg for a long) → skipped;
  • a wrong-direction (SELL parent) bracket for a long orphan → skipped.
"""
import os
from datetime import datetime, timezone


class _Cursor(list):
    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def _match(self, q, r):
        for k, v in q.items():
            rv = r.get(k)
            if isinstance(v, dict):
                if "$in" in v and rv not in v["$in"]:
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
        return _Cursor(dict(r) for r in self.rows if self._match(q or {}, r))

    def find_one(self, q=None, proj=None, sort=None):
        res = self.find(q, proj)
        return res[0] if res else None


class _DB:
    def __init__(self, colls):
        self._c = colls

    def __getitem__(self, name):
        return self._c.get(name, _Coll([]))


def _bracket(tid, sym, action, qty, fill, stop, target):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "order_id": "OQ-" + tid, "trade_id": tid, "symbol": sym, "type": "bracket",
        "status": "filled", "executed_at": now, "queued_at": now,
        "filled_qty": qty, "fill_price": fill,
        "parent": {"action": action, "quantity": qty},
        "stop": {"order_type": "STP", "stop_price": stop},
        "target": {"order_type": "LMT", "limit_price": target},
    }


class _Dir:
    def __init__(self, v):
        self.value = v


class TradeDirection:
    LONG = _Dir("long")
    SHORT = _Dir("short")


def run():
    from services.position_reconciler import PositionReconciler

    order_queue = [
        # genuine write-gap: LITE long, no bot_trade
        _bracket("GAP1", "LITE", "BUY", 8, 1010.0, 998.0, 1030.0),
        # tracked bracket: has a bot_trade → must be skipped
        _bracket("TRK1", "AAPL", "BUY", 50, 200.0, 196.0, 210.0),
        # directionally invalid: long but stop ABOVE fill → skipped
        _bracket("BAD1", "MSFT", "BUY", 10, 300.0, 305.0, 320.0),
        # wrong direction for a long orphan (SELL parent) → skipped
        _bracket("SHRT1", "TSLA", "SELL", 5, 250.0, 258.0, 230.0),
    ]
    bot_trades = [{"id": "TRK1", "symbol": "AAPL", "status": "open"}]
    db = _DB({"order_queue": _Coll(order_queue), "bot_trades": _Coll(bot_trades)})

    r = PositionReconciler(db=db)
    os.environ["RECONCILE_RELINK_BRACKET_WINDOW_MIN"] = "1440"

    # 1) genuine gap → inherit real stop/target
    m = r._find_orphan_source_bracket("LITE", TradeDirection.LONG, 8, 1010.0)
    assert m is not None, "GAP1 should match"
    assert m["stop_price"] == 998.0 and m["target_1"] == 1030.0
    assert m["order_id"] == "OQ-GAP1"
    print("✅ GAP1 → real stop 998.0 / target 1030.0 inherited")

    # 2) tracked bracket → skipped (never steal a tracked stop)
    assert r._find_orphan_source_bracket("AAPL", TradeDirection.LONG, 50, 200.0) is None
    print("✅ TRK1 (has bot_trade) → skipped")

    # 3) directionally-invalid stop → skipped
    assert r._find_orphan_source_bracket("MSFT", TradeDirection.LONG, 10, 300.0) is None
    print("✅ BAD1 (stop above avg for long) → skipped")

    # 4) wrong-direction parent → skipped for a long orphan
    assert r._find_orphan_source_bracket("TSLA", TradeDirection.LONG, 5, 250.0) is None
    print("✅ SHRT1 (SELL parent, long orphan) → skipped")

    # 5) qty sanity: 4x the orphan size → out of 0.5x–2x band → skipped
    assert r._find_orphan_source_bracket("LITE", TradeDirection.LONG, 40, 1010.0) is None
    print("✅ qty 40 vs bracket 8 (ratio 5x) → skipped")

    print("\n✅ v414 SEAL #2 HEAL OK — bracket-source relink correct + guarded")


if __name__ == "__main__":
    run()
