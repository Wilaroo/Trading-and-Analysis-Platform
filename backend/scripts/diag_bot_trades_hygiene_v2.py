#!/usr/bin/env python3
"""diag_bot_trades_hygiene_v2.py  —  READ-ONLY  (2026-06-16)

V2 — fixes v1's `$or entry_time/exit_time` filter that excluded the
exact degraded rows we wanted to scan. Switches to `closed_at` and
`created_at` (which DO populate) as the time filter, with a broader
catch-all status match.
"""
import os, sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

WINDOW_DAYS = 30
HYG_FIELDS = ("entry_time", "exit_time", "entry_price", "exit_price",
              "size", "conid", "pnl", "status", "symbol", "side",
              "trade_id", "strategy", "setup_type", "closed_at", "created_at")


def hr(t): print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def is_missing(v, field):
    if v is None or v == "" or v == "<MISSING>": return True
    if field in ("size", "conid") and v == 0: return True
    if field in ("entry_price", "exit_price", "pnl") and v == 0:
        # zero PnL is legitimate (full break-even); only None/missing flagged.
        return False
    return False


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn: print("ERROR: env"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    col = db["bot_trades"]

    # Time filter: trades with closed_at OR created_at in last 30d.
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    closed_q = {
        "status": {"$regex": "^(closed|CLOSED|filled|complete)$", "$options": "i"},
        "$or": [{"closed_at": {"$gte": since}},
                {"created_at": {"$gte": since}}],
    }
    n_closed = col.count_documents(closed_q)
    n_total_30d = col.count_documents(
        {"$or": [{"closed_at": {"$gte": since}},
                 {"created_at": {"$gte": since}}]})
    print(f"Closed trades in last {WINDOW_DAYS}d : {n_closed:,}")
    print(f"All trades in last {WINDOW_DAYS}d    : {n_total_30d:,}")

    hr("Section 1 — field missingness in CLOSED trades, last 30d")
    miss = Counter()
    sample_total = 0
    for r in col.find(closed_q, {"_id": 0}).limit(20_000):
        sample_total += 1
        for f in HYG_FIELDS:
            if is_missing(r.get(f), f):
                miss[f] += 1
    print(f"  scanned {sample_total:,} closed trades\n")
    print(f"  {'field':>14} {'missing':>9} {'rate':>7}")
    for f in HYG_FIELDS:
        c = miss.get(f, 0)
        if c == 0: continue
        pct = c / max(sample_total, 1) * 100
        flag = " ⚠ HIGH" if pct >= 5 else (" ·" if pct >= 1 else "")
        print(f"  {f:>14} {c:>9,} {pct:>6.2f}%{flag}")
    if not miss:
        print("  (no missing fields detected — clean!)")

    hr("Section 2 — CLOSED with non-zero PnL but missing entry_time/size/conid")
    deg_q = {
        **closed_q,
        "pnl": {"$exists": True, "$nin": [0, None]},
        "$or": [{"entry_time": {"$in": [None, ""]}},
                {"size": {"$in": [None, 0]}},
                {"conid": {"$in": [None, 0, ""]}}],
    }
    # Above $or conflicts with outer $or — fix by using $and.
    deg_q = {"$and": [
        {"status": {"$regex": "^(closed|CLOSED|filled|complete)$", "$options": "i"}},
        {"$or": [{"closed_at": {"$gte": since}}, {"created_at": {"$gte": since}}]},
        {"pnl": {"$exists": True, "$nin": [0, None]}},
        {"$or": [{"entry_time": {"$in": [None, ""]}},
                 {"size": {"$in": [None, 0]}},
                 {"conid": {"$in": [None, 0, ""]}}]},
    ]}
    deg = list(col.find(deg_q, {"_id": 0, "trade_id": 1, "symbol": 1,
                                "pnl": 1, "entry_time": 1, "size": 1,
                                "conid": 1, "closed_at": 1,
                                "close_reason": 1}).limit(50))
    print(f"  degraded rows: {len(deg)} (capped at 50)\n")
    for r in deg[:25]:
        miss_fields = [f for f in ("entry_time", "size", "conid")
                       if is_missing(r.get(f), f)]
        closed_at = (r.get("closed_at") or "")[:19]
        reason = (r.get("close_reason") or "")[:18]
        print(f"    {r.get('symbol','?'):>8}  "
              f"trade_id={str(r.get('trade_id','?'))[:18]:>20}  "
              f"pnl={float(r.get('pnl') or 0):>+8.2f}  "
              f"closed={closed_at:>19}  reason={reason:>18}  "
              f"missing=[{','.join(miss_fields)}]")

    hr("Section 3 — Pattern detection")
    # Group degraded by close_reason and by entered_by to find the upstream.
    by_reason, by_entered_by = Counter(), Counter()
    for r in col.find(deg_q, {"_id": 0, "close_reason": 1,
                              "entered_by": 1}).limit(5_000):
        by_reason[r.get("close_reason") or "<none>"] += 1
        by_entered_by[r.get("entered_by") or "<none>"] += 1
    print(f"  degraded grouped by close_reason:")
    for k, v in by_reason.most_common(10):
        print(f"    {k:>30} : {v}")
    print(f"\n  degraded grouped by entered_by:")
    for k, v in by_entered_by.most_common(10):
        print(f"    {k:>30} : {v}")

    print("\n  Verdict guidance:")
    print("    • If degraded clusters on a single close_reason → that path is buggy")
    print("    • If degraded clusters on entered_by=bot_fired → executions-persister")
    print("    • If isolated to specific symbols → likely IB execDetails race")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
