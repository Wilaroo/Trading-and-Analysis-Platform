#!/usr/bin/env python3
"""diag_bot_trades_hygiene.py  —  READ-ONLY  (2026-06-16, Issue 3 prep)

Inspects bot_trades for hygiene gaps. The specific known case (handoff):
SPCX successfully closed at TP (+$699) but its row is missing entry_time,
size, and conid. We need to know how widespread the pattern is and which
fields are most often missing, so the repair patcher targets surgically.

Output:
  Section 1 — SPCX row deep-inspect (the known incident).
  Section 2 — fleet-wide field-missingness audit (last 30d).
  Section 3 — anomaly rollup: closed-with-pnl but missing entry/exit fields.
"""
import os, sys
from collections import Counter, defaultdict
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
              "strategy", "setup_type", "entered_by")


def hr(t): print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn: print("ERROR: env"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    col = db["bot_trades"]
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    # ---- 1. SPCX deep-inspect ----
    hr("Section 1 — SPCX row(s) deep inspect")
    for r in col.find({"symbol": "SPCX"}, {"_id": 0}).sort("entry_time", -1).limit(5):
        print(f"\n  trade_id      : {r.get('trade_id', '?')}")
        for f in HYG_FIELDS:
            v = r.get(f, "<MISSING>")
            tag = "  ← MISSING" if v == "<MISSING>" or v is None or v == "" else ""
            print(f"  {f:>14}: {str(v)[:60]}{tag}")
        # Dump any extra fields not in HYG_FIELDS.
        extras = [k for k in r if k not in HYG_FIELDS]
        if extras:
            print(f"  (also has: {', '.join(extras[:12])}"
                  f"{'…' if len(extras) > 12 else ''})")

    # ---- 2. Fleet-wide field-missingness audit ----
    hr(f"Section 2 — field missingness in last {WINDOW_DAYS}d "
       "(of CLOSED trades only)")
    closed_q = {"status": {"$in": ["closed", "CLOSED", "filled", "complete"]},
                "$or": [{"entry_time": {"$gte": since.isoformat()}},
                        {"exit_time":  {"$gte": since.isoformat()}}]}
    n_closed = col.count_documents(closed_q)
    print(f"  closed trades scanned: {n_closed:,}\n")
    miss = Counter()
    for r in col.find(closed_q, {"_id": 0}).limit(5000):
        for f in HYG_FIELDS:
            v = r.get(f)
            if v is None or v == "" or v == 0 and f in ("size", "entry_price",
                                                        "exit_price", "conid"):
                miss[f] += 1
    print(f"  {'field':>14} {'missing':>9} {'rate':>7}")
    for f, c in miss.most_common():
        pct = c / max(n_closed, 1) * 100
        flag = " ⚠" if pct >= 1 else ""
        print(f"  {f:>14} {c:>9,} {pct:>6.2f}%{flag}")

    # ---- 3. Closed-with-pnl but missing critical fields ----
    hr("Section 3 — CLOSED with non-zero PnL but missing entry_time/size/conid")
    deg_q = {"status": {"$in": ["closed", "CLOSED", "filled", "complete"]},
             "pnl": {"$exists": True, "$ne": 0, "$ne": None},
             "$or": [{"entry_time": {"$in": [None, ""]}},
                     {"size": {"$in": [None, 0]}},
                     {"conid": {"$in": [None, 0, ""]}}]}
    deg = list(col.find(deg_q, {"_id": 0, "trade_id": 1, "symbol": 1,
                                "pnl": 1, "entry_time": 1, "exit_time": 1,
                                "size": 1, "conid": 1}).limit(50))
    print(f"  degraded rows found: {len(deg)} (capped at 50)")
    for r in deg[:25]:
        miss_fields = []
        if not r.get("entry_time"): miss_fields.append("entry_time")
        if not r.get("size"):       miss_fields.append("size")
        if not r.get("conid"):      miss_fields.append("conid")
        print(f"    {r.get('symbol','?'):>8}  "
              f"trade_id={str(r.get('trade_id','?'))[:18]:>20}  "
              f"pnl={r.get('pnl'):>+8.2f}  missing=[{','.join(miss_fields)}]")

    print("\n  Verdict guidance:")
    print("    • If degraded_count is small (< ~10) and only on EOD-closed → ")
    print("      build narrow repair (cross-ref IB executions by exit_time + symbol)")
    print("    • If degraded_count grows daily → fix the executions-persister upstream")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
