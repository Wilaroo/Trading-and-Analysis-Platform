"""Seal #2 — fill→bot_trade WRITE-GAP probe (READ-ONLY, base-trade_id-keyed).

WHY v2: the first cut counted ANY filled order_queue row whose `trade_id` lacked a
`bot_trades` row. On real data that over-flagged badly — `order_queue` carries
MANAGEMENT orders whose trade_id is a DERIVED string (`CLOSE-<id>`,
`ADOPT-STOP-<id>`, `SCALE-<id>`…) that can NEVER match a bare `bot_trades.id`, and
it double-counted the same reconciled_orphan's loss once per leg. Both inflated the
leak. v2 fixes that:

  • NORMALIZE every trade_id to its BASE id (strip synthetic prefixes), then group.
  • A base id is a TRUE entry write gap ONLY when a BARE opening order (BUY/SELL,
    trade_id == base) was FILLED yet NO `bot_trades` row exists for that base id.
    (Bases seen only via derived CLOSE-/ADOPT- legs ⇒ `exit_only_orders_no_base`,
    a different flavor — not an entry-write gap.)
  • $ leak = sum over DISTINCT downstream reconciled_orphans, each linked by symbol
    + time-proximity (±3d to the fill), counted ONCE.

Writes NOTHING. Active heal is a later, flag-gated step.
Endpoint: GET /api/slow-learning/orphan-fill-heal/report?days=120
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from services.orphan_leak_rca import _fnum, _parse_ts

logger = logging.getLogger(__name__)

_FILLED_STATES = ("filled", "partial")
_RECONCILED_SETUPS = ("reconciled_orphan", "reconciled_excess_slice")
# synthetic / derived order-id prefixes (management legs share the entry's base id)
_PREFIX = re.compile(
    r'^(CLOSE|ADOPT-STOP|ADOPT|EXIT|STOP|TGT|TARGET|SCALE|TRIM|FLATTEN|FLAT)-', re.I)
_MATCH_WINDOW_DAYS = 3


def _base_id(tid):
    """Strip stacked synthetic prefixes → the underlying bot_trade id."""
    if not tid:
        return tid
    prev = None
    t = str(tid)
    while prev != t:
        prev = t
        t = _PREFIX.sub("", t)
    return t


def _opening_action(leg):
    a = (leg.get("action") or "").upper()
    if not a:
        a = ((leg.get("parent") or {}).get("action") or "").upper()
    return a if a in ("BUY", "SELL") else None


def _leg_qty(leg):
    return _fnum(leg.get("filled_qty")) or _fnum(leg.get("quantity")) \
        or _fnum((leg.get("parent") or {}).get("quantity"))


def generate_report(db, days: int = 120) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "mode": "observe",
    }
    if db is None:
        return out

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    try:
        rows = list(db["order_queue"].find(
            {"status": {"$in": list(_FILLED_STATES)}, "trade_id": {"$ne": None},
             "$or": [{"executed_at": {"$gte": cutoff}}, {"queued_at": {"$gte": cutoff}}]},
            {"_id": 0, "trade_id": 1, "symbol": 1, "action": 1, "parent": 1,
             "quantity": 1, "filled_qty": 1, "fill_price": 1,
             "executed_at": 1, "queued_at": 1}))
    except Exception as e:
        out["error"] = "order_queue scan failed: %s" % (str(e)[:120])
        return out

    # group filled rows by BASE trade_id
    grp = defaultdict(lambda: {"rows": [], "entry_leg": None})
    for r in rows:
        tid = r.get("trade_id")
        b = _base_id(tid)
        g = grp[b]
        g["rows"].append(r)
        if tid == b and _opening_action(r):   # a bare opening order = the entry
            cur = g["entry_leg"]
            if cur is None or str(r.get("executed_at") or "") < str(cur.get("executed_at") or "~"):
                g["entry_leg"] = r

    classes = Counter()
    gaps = []
    orphan_pnl = {}        # distinct downstream orphan id → realized_pnl (counted once)
    bt_cache = {}
    for b, g in grp.items():
        if b in bt_cache:
            has_bt = bt_cache[b]
        else:
            try:
                has_bt = db["bot_trades"].find_one({"id": b}, {"_id": 1}) is not None
            except Exception:
                has_bt = True   # fail-safe: never flag what we can't verify
            bt_cache[b] = has_bt
        if has_bt:
            classes["has_record"] += 1
            continue

        cls = "entry_write_gap" if g["entry_leg"] is not None else "exit_only_orders_no_base"
        classes[cls] += 1
        if cls != "entry_write_gap":
            continue

        op = g["entry_leg"]
        sym = (op.get("symbol") or "").upper()
        fts = _parse_ts(op.get("executed_at") or op.get("queued_at"))
        action = _opening_action(op)
        direction = "long" if action == "BUY" else "short" if action == "SELL" else None
        qty = _leg_qty(op)

        # time-matched, deduped downstream reconciled_orphan ($ attribution)
        best, best_dd = None, None
        try:
            for c in db["bot_trades"].find(
                    {"symbol": sym, "setup_type": {"$in": list(_RECONCILED_SETUPS)}},
                    {"_id": 0, "id": 1, "realized_pnl": 1, "risk_amount": 1,
                     "entry_time": 1, "executed_at": 1, "closed_at": 1, "close_reason": 1}):
                ct = _parse_ts(c.get("entry_time") or c.get("executed_at") or c.get("closed_at"))
                if fts and ct and abs((ct - fts).days) <= _MATCH_WINDOW_DAYS:
                    dd = abs((ct - fts).total_seconds())
                    if best_dd is None or dd < best_dd:
                        best_dd, best = dd, c
        except Exception:
            pass
        downstream = None
        if best:
            orphan_pnl[best["id"]] = _fnum(best.get("realized_pnl")) or 0.0
            downstream = {"orphan_id": best["id"],
                          "realized_pnl": _fnum(best.get("realized_pnl")),
                          "close_reason": str(best.get("close_reason") or "")[:32]}

        gaps.append({
            "base_trade_id": b, "symbol": sym, "direction": direction,
            "filled_qty": int(qty) if qty else None,
            "entry_price": _fnum(op.get("fill_price")),
            "executed_at": op.get("executed_at") or op.get("queued_at"),
            "n_queue_legs": len(g["rows"]),
            "downstream_reconciled_orphan": downstream,
        })

    leaked_usd = round(sum(orphan_pnl.values()), 0)
    sym_counter = Counter(g["symbol"] for g in gaps)
    gaps.sort(key=lambda x: ((x["downstream_reconciled_orphan"] or {}).get("realized_pnl") or 0.0))

    out["population"] = {
        "filled_order_queue_rows": len(rows),
        "distinct_base_trade_ids": len(grp),
        "classes": dict(classes),
    }
    out["write_gaps"] = {
        "n_entry_write_gaps": len(gaps),
        "n_exit_only_orders_no_base": classes.get("exit_only_orders_no_base", 0),
        "n_distinct_downstream_orphans": len(orphan_pnl),
        "leaked_usd_dedup": leaked_usd,
        "top_symbols": sym_counter.most_common(12),
        "samples": gaps[:25],
    }
    out["verdict"] = (
        ("%d TRUE entry-write gaps (a bare opening order FILLED but no bot_trade row). "
         "%d link to distinct reconciled_orphans ≈ $%d leaked (deduped, time-matched). "
         "(%d exit-only/derived-id bases excluded as non-gaps.) Real gaps ⇒ next: "
         "harden the live entry pre-write (retry + fill-confirm heal), flag-gated." % (
             len(gaps), len(orphan_pnl), int(leaked_usd),
             classes.get("exit_only_orders_no_base", 0)))
        if gaps else
        "0 entry-write gaps: every FILLED bare opening order resolves to a bot_trade. "
        "The −$ leak was NOT an entry write gap (derived CLOSE-/ADOPT- legs + symbol-"
        "level artifacts). No source fix at the entry write site.")
    return out
