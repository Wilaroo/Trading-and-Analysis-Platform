"""Seal #2 — fill→bot_trade WRITE-GAP probe (READ-ONLY, trade_id-keyed).

WHY: the v407 lineage probe classified `order_no_trade` by ANY `order_queue` row on
the *symbol* (incl. exit/stop/target/reconciler legs), so it could not tell a TRUE
entry-write gap from an artifact. This probe keys on the only unambiguous signal:

    an `order_queue` row that the pusher marked FILLED, carrying a `trade_id`,
    whose `trade_id` has NO `bot_trades` row → a confirmed fill the bot never
    persisted as a trade (the record-less bug Seal #2 targets).

The entry path already pre-writes a PENDING `bot_trades` row before the broker call
(v19.34.6), so a real gap means that pre-write (or every post-fill upsert) was lost
for that trade_id. This probe proves how many such gaps exist, the $ they leaked
downstream (linked to the `reconciled_orphan` they became), and previews the
bot_trade a heal WOULD write. Writes NOTHING — the active heal is a later, flagged step.

Endpoint: GET /api/slow-learning/orphan-fill-heal/report?days=120
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from services.orphan_leak_rca import _fnum, _clean_r, _parse_ts

logger = logging.getLogger(__name__)

_FILLED_STATES = ("filled", "partial")
_RECONCILED_SETUPS = ("reconciled_orphan", "reconciled_excess_slice")


def _opening_leg(legs):
    """The leg that OPENED the position = earliest-executed filled leg. For bracket
    rows the opening action lives in `parent`; for flat rows it is top-level `action`."""
    def _exec(l):
        return _parse_ts(l.get("executed_at")) or _parse_ts(l.get("queued_at")) \
            or datetime.max.replace(tzinfo=timezone.utc)
    return sorted(legs, key=_exec)[0] if legs else None


def _leg_action(leg):
    a = (leg.get("action") or "").upper()
    if not a:
        parent = leg.get("parent") or {}
        a = (parent.get("action") or "").upper()
    return a or None


def _leg_qty(leg):
    return _fnum(leg.get("filled_qty")) or _fnum(leg.get("quantity")) \
        or _fnum((leg.get("parent") or {}).get("quantity"))


def generate_report(db, days: int = 120) -> dict:
    out = {
        "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "report_period_days": days,
        "mode": "observe",  # read-only; no writes
    }
    if db is None:
        return out

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    # 1. terminal-fill order_queue rows in-window that carry a trade_id
    try:
        rows = list(db["order_queue"].find(
            {"status": {"$in": list(_FILLED_STATES)},
             "trade_id": {"$ne": None},
             "$or": [{"executed_at": {"$gte": cutoff}},
                     {"queued_at": {"$gte": cutoff}}]},
            {"_id": 0, "trade_id": 1, "symbol": 1, "action": 1, "status": 1,
             "order_type": 1, "type": 1, "parent": 1, "quantity": 1, "filled_qty": 1,
             "fill_price": 1, "executed_at": 1, "queued_at": 1}))
    except Exception as e:
        out["error"] = "order_queue scan failed: %s" % (str(e)[:120])
        return out

    by_tid = defaultdict(list)
    for r in rows:
        by_tid[r.get("trade_id")].append(r)
    out["population"] = {"filled_order_queue_trade_ids": len(by_tid),
                         "filled_order_queue_rows": len(rows)}

    gaps = []
    bt_cache = {}
    for tid, legs in by_tid.items():
        if tid in bt_cache:
            has_bt = bt_cache[tid]
        else:
            try:
                has_bt = db["bot_trades"].find_one({"id": tid}, {"_id": 1}) is not None
            except Exception:
                has_bt = True   # fail-safe: don't flag if we can't verify
            bt_cache[tid] = has_bt
        if has_bt:
            continue   # trade_id HAS a record → not a write gap

        open_leg = _opening_leg(legs)
        action = _leg_action(open_leg) if open_leg else None
        direction = "long" if action == "BUY" else "short" if action == "SELL" else None
        sym = (open_leg.get("symbol") if open_leg else "") or ""
        sym = sym.upper()
        entry_px = _fnum(open_leg.get("fill_price")) if open_leg else None
        qty = _leg_qty(open_leg) if open_leg else None
        executed_at = (open_leg.get("executed_at") or open_leg.get("queued_at")) if open_leg else None

        # ib_executions corroboration (did the broker really fill this symbol?)
        try:
            ie_n = db["ib_executions"].count_documents({"symbol": sym})
        except Exception:
            ie_n = -1

        # downstream: did this fill surface as a reconciled_orphan we can $-attribute?
        downstream = None
        try:
            d = db["bot_trades"].find_one(
                {"symbol": sym, "setup_type": {"$in": list(_RECONCILED_SETUPS)}},
                {"_id": 0, "id": 1, "status": 1, "realized_pnl": 1, "risk_amount": 1,
                 "close_reason": 1, "closed_at": 1},
                sort=[("closed_at", -1)])
            if d:
                downstream = {
                    "orphan_id": d.get("id"), "status": d.get("status"),
                    "realized_pnl": _fnum(d.get("realized_pnl")),
                    "realized_r": _clean_r(d.get("realized_pnl"), d.get("risk_amount")),
                    "close_reason": str(d.get("close_reason") or "")[:32],
                }
        except Exception:
            pass

        gaps.append({
            "trade_id": tid, "symbol": sym, "direction": direction,
            "opening_action": action, "entry_price": entry_px,
            "filled_qty": int(qty) if qty else None, "executed_at": executed_at,
            "n_queue_legs": len(legs),
            "leg_statuses": Counter(l.get("status") for l in legs).most_common(),
            "ib_executions_for_symbol": ie_n,
            "downstream_reconciled_orphan": downstream,
            "heal_preview": {
                "would_create_bot_trade": {
                    "id": tid, "symbol": sym, "direction": direction,
                    "shares": int(qty) if qty else None, "entry_price": entry_px,
                    "setup_type": "reconciled_fill_heal", "entered_by": "seal2_fill_heal",
                },
                "blocked_reason": (
                    "downstream reconciled_orphan already records this position — "
                    "active heal would double-count; prevention belongs in the live "
                    "write path" if downstream else None),
            },
        })

    # aggregate
    leaked_usd = sum((g["downstream_reconciled_orphan"] or {}).get("realized_pnl") or 0.0
                     for g in gaps)
    leaked_r = sum((g["downstream_reconciled_orphan"] or {}).get("realized_r") or 0.0
                   for g in gaps)
    n_with_orphan = sum(1 for g in gaps if g["downstream_reconciled_orphan"])
    sym_counter = Counter(g["symbol"] for g in gaps)
    gaps.sort(key=lambda g: ((g["downstream_reconciled_orphan"] or {}).get("realized_pnl") or 0.0))

    out["write_gaps"] = {
        "n_trade_ids": len(gaps),
        "n_with_downstream_orphan": n_with_orphan,
        "n_untracked_no_downstream": len(gaps) - n_with_orphan,
        "leaked_usd": round(leaked_usd, 0),
        "leaked_r": round(leaked_r, 2),
        "top_symbols": sym_counter.most_common(12),
        "samples": gaps[:25],
    }
    out["verdict"] = (
        ("%d filled order_queue trade_ids have NO bot_trade row (TRUE write gaps). "
         "%d already became reconciled_orphans (≈$%d / %sR leaked downstream); %d are "
         "untracked with no downstream record. Real gaps confirmed ⇒ next step: harden "
         "the live entry pre-write (retry + fill-confirm heal), flag-gated." % (
             len(gaps), n_with_orphan, int(leaked_usd), round(leaked_r, 1),
             len(gaps) - n_with_orphan))
        if gaps else
        "0 write gaps: every FILLED order_queue trade_id resolves to a bot_trade row. "
        "The v407 `order_no_trade` bucket was a symbol-level artifact (exit/leg orders), "
        "NOT an entry write gap — no source fix needed.")
    return out
