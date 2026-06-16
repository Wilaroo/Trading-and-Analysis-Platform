#!/usr/bin/env python3
"""diag_v320g_spcx_exit_lookup.py  —  READ-ONLY  (2026-06-16, v320g prep)

The SPCX bot_trades row id=31651c71 (closed 2026-06-15T19:56:32, 42sh long,
entered_by=bot_fired) is missing `exit_price` even though `realized_pnl`
and `net_pnl` are populated. This diag surfaces enough context to
decide HOW to back-fill exit_price safely:

  Section 1 — Full bot_trades doc for the degraded row.
  Section 2 — ib_executions cross-ref:
              candidates with symbol=SPCX, side=SELL, shares matching,
              exec_time within ±10 minutes of closed_at.
  Section 3 — bot_orders cross-ref:
              all orders linked to this trade_id (parent + brackets);
              terminal status + avg_fill_price if available.
  Section 4 — Back-calc check:
              implied_exit_price = entry_price + realized_pnl/shares
              (long). Cross-validates whatever ib_executions returns.

No writes. Run before drafting repair_v320g_spcx_exit_backfill.py.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


TARGET_ID = "31651c71"
SYMBOL = "SPCX"
WINDOW_MIN = 10  # ± minutes around closed_at for ib_executions probe


def hr(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def _parse_iso(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_dt(dt):
    if dt is None:
        return "—"
    if isinstance(dt, str):
        return dt[:25]
    return dt.isoformat()[:25]


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    # ----- Section 1
    hr(f"Section 1 — bot_trades doc id={TARGET_ID}")
    bt_doc = db["bot_trades"].find_one({"id": TARGET_ID}, {"_id": 0})
    if not bt_doc:
        print(f"  ERROR: no bot_trades row with id={TARGET_ID}")
        sys.exit(1)
    interesting = ("id", "symbol", "direction", "shares", "status",
                   "entered_by", "entry_price", "exit_price", "fill_price",
                   "realized_pnl", "net_pnl", "pnl_pct",
                   "entry_order_id", "stop_order_id", "target_order_ids",
                   "created_at", "executed_at", "closed_at",
                   "close_reason", "close_at_eod", "commission_per_share",
                   "commission_min", "total_commissions")
    for k in interesting:
        v = bt_doc.get(k, "<missing>")
        print(f"  {k:>22} : {v}")
    closed_at = _parse_iso(bt_doc.get("closed_at"))
    entry_price = bt_doc.get("entry_price")
    realized_pnl = bt_doc.get("realized_pnl")
    shares = bt_doc.get("shares") or 0
    direction = bt_doc.get("direction")

    # ----- Section 2
    hr(f"Section 2 — ib_executions probe (±{WINDOW_MIN}m around closed_at)")
    if "ib_executions" not in db.list_collection_names():
        print("  ib_executions collection not present in this DB.")
    elif closed_at is None:
        print("  closed_at not parseable; skipping window probe.")
    else:
        # Try multiple plausible time-field names + value shapes.
        win_start = (closed_at - timedelta(minutes=WINDOW_MIN))
        win_end = (closed_at + timedelta(minutes=WINDOW_MIN))
        time_candidates = ("exec_time", "time", "ts", "execution_time",
                           "executed_at", "exec_at")
        # Try both ISO-string and datetime forms.
        clauses = []
        for tf in time_candidates:
            clauses.append({tf: {"$gte": win_start.isoformat(),
                                 "$lte": win_end.isoformat()}})
            clauses.append({tf: {"$gte": win_start, "$lte": win_end}})

        execs = list(db["ib_executions"].find(
            {"symbol": SYMBOL, "$or": clauses},
            {"_id": 0},
        ))
        if not execs:
            execs = list(db["ib_executions"].find(
                {"symbol": SYMBOL},
                {"_id": 0},
            ).sort([("exec_time", -1), ("time", -1), ("ts", -1)]).limit(10))
            print("  No execs found in window. Showing 10 most-recent SPCX execs:")
        else:
            print(f"  Found {len(execs)} candidate(s) in ±{WINDOW_MIN}m window:")

        seen_keys = set()
        for ix, ex in enumerate(execs):
            seen_keys.update(ex.keys())
            print(f"\n  --- candidate {ix+1} ---")
            # Print common fields prominently
            for k in ("symbol", "side", "action", "shares", "qty",
                      "fill_price", "price", "avg_price",
                      "exec_time", "time", "ts", "executed_at",
                      "order_id", "exec_id", "perm_id", "trade_id"):
                if k in ex:
                    print(f"    {k:>14} : {ex.get(k)}")
        if seen_keys:
            print(f"\n  union of fields seen: {sorted(seen_keys)[:20]}")

    # ----- Section 3
    hr("Section 3 — bot_orders cross-ref")
    entry_oid = bt_doc.get("entry_order_id")
    stop_oid = bt_doc.get("stop_order_id")
    tgt_oids = bt_doc.get("target_order_ids") or []
    order_ids = [str(x) for x in ([entry_oid, stop_oid] + list(tgt_oids)) if x]
    print(f"  linked order_ids: {order_ids}")
    if "bot_orders" in db.list_collection_names() and order_ids:
        for oid in order_ids:
            # bot_orders may key on int or str.
            q = {"$or": [{"order_id": oid},
                         {"order_id": int(oid)} if oid.isdigit() else {"order_id": oid}]}
            o = db["bot_orders"].find_one(q, {"_id": 0})
            if not o:
                print(f"  order {oid}: not found in bot_orders")
                continue
            print(f"\n  --- order {oid} ---")
            for k in ("order_id", "action", "order_type", "status",
                      "symbol", "shares", "avg_fill_price",
                      "lmt_price", "aux_price", "submitted_at",
                      "filled_at", "filled", "remaining"):
                if k in o:
                    print(f"    {k:>15} : {o.get(k)}")

    # ----- Section 4
    hr("Section 4 — back-calculation cross-check")
    if (entry_price is not None and realized_pnl is not None
            and isinstance(shares, (int, float)) and shares):
        if direction == "long":
            implied = entry_price + (realized_pnl / shares)
        elif direction == "short":
            implied = entry_price - (realized_pnl / shares)
        else:
            implied = None
        print(f"  entry_price  = {entry_price}")
        print(f"  realized_pnl = {realized_pnl}")
        print(f"  shares       = {shares}")
        print(f"  direction    = {direction}")
        print(f"  ⇒ implied exit_price = {implied}")
        print("\n  REPAIR DECISION TREE:")
        print(f"   • If ib_executions returned a SELL @ price ≈ "
              f"{implied} (within $0.05) → use that as canonical.")
        print(f"   • If ib_executions returned NOTHING → back-calc "
              f"{implied} is safe (realized_pnl is the source of truth).")
        print("   • If ib_executions price ≠ implied by > $0.05 → "
              "INVESTIGATE before patching; PnL math is wrong.")
    else:
        print("  cannot back-calculate (entry_price / realized_pnl / shares "
              "missing).")
    print("\nDONE.")


if __name__ == "__main__":
    main()
