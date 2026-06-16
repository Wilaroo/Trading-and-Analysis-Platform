#!/usr/bin/env python3
"""diag_arm_target_hit_probe.py  —  READ-ONLY  (2026-06-16)

Operator reports: "ARM trade hit its targets yesterday" but
sanitize_v2 returned target_hit=0 across 112 clean trades. Triangulate:

  1. All ARM bot_trades from the last 7 days (any status), full doc.
  2. Distinct close_reason taxonomy across ALL closed trades in the last
     7 days — surfaces every close_reason variant the system writes
     (catches things like "target_1_hit", "tp1_hit", "bracket_target",
     "pt1_hit", etc. that the sanitize funnel might miss).
  3. Cross-ref to bracket_lifecycle_events for ARM in last 2 days —
     shows the TARGET leg's actual fire events (independent of
     bot_trades' close_reason).
  4. Cross-ref to ib_executions for ARM SELLs (closing fills) on
     yesterday's session, with order_id linkage to ARM's
     target_order_ids.

No writes. Output is fully diagnostic.
"""
from __future__ import annotations
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


def hr(t):
    print("\n" + "=" * 92 + f"\n  {t}\n" + "=" * 92)


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL / DB_NAME env not set")
        sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]

    now = datetime.now(timezone.utc)
    since_7d = (now - timedelta(days=7)).isoformat()
    since_2d = (now - timedelta(days=2)).isoformat()

    # ── 1. all ARM trades last 7d ────────────────────────────────────────
    hr("Section 1 — ARM bot_trades, last 7 days (all statuses)")
    arm_trades = list(db["bot_trades"].find(
        {"symbol": "ARM",
         "$or": [{"created_at": {"$gte": since_7d}},
                 {"executed_at": {"$gte": since_7d}},
                 {"closed_at": {"$gte": since_7d}}]},
        {"_id": 0},
    ))
    print(f"  found {len(arm_trades)} ARM trade(s)")
    interesting = ("id", "symbol", "direction", "shares", "status",
                   "entered_by", "setup_type", "trade_style",
                   "entry_price", "fill_price", "exit_price",
                   "stop_price", "target_prices", "target_order_ids",
                   "entry_order_id", "stop_order_id",
                   "created_at", "executed_at", "closed_at",
                   "close_reason", "close_at_eod",
                   "realized_pnl", "net_pnl", "pnl_pct",
                   "mae_r", "mfe_r")
    for i, t in enumerate(arm_trades):
        print(f"\n  --- ARM trade {i+1}/{len(arm_trades)} ---")
        for k in interesting:
            v = t.get(k, "<missing>")
            if isinstance(v, list) and len(v) > 4:
                v = f"[{len(v)} items: {v[:3]}...]"
            print(f"    {k:>22} : {v}")

    # ── 2. close_reason taxonomy ─────────────────────────────────────────
    hr("Section 2 — distinct close_reason values across all closed trades, last 7d")
    reasons = Counter()
    for t in db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": since_7d}},
        {"_id": 0, "close_reason": 1},
    ):
        reasons[t.get("close_reason") or "<none>"] += 1
    print(f"  {len(reasons)} distinct close_reason values  (top 30):")
    for r, n in reasons.most_common(30):
        hit = "  ← TARGET-LIKE" if any(
            k in r.lower() for k in ("target", "pt1", "pt2", "tp1", "tp2",
                                      "bracket_fill", "profit"))  else ""
        print(f"    {n:>5}× {r}{hit}")

    # ── 3. bracket_lifecycle_events for ARM ──────────────────────────────
    hr("Section 3 — bracket_lifecycle_events for ARM, last 2 days")
    if "bracket_lifecycle_events" in db.list_collection_names():
        bevs = list(db["bracket_lifecycle_events"].find(
            {"symbol": "ARM",
             "$or": [{"ts": {"$gte": since_2d}},
                     {"timestamp": {"$gte": since_2d}}]},
            {"_id": 0},
        ).sort([("ts", 1), ("timestamp", 1)]).limit(60))
        print(f"  found {len(bevs)} bracket events")
        for e in bevs:
            ts = e.get("ts") or e.get("timestamp") or "?"
            evt = e.get("event") or e.get("kind") or "?"
            oid = e.get("order_id", "")
            leg = e.get("leg", "")
            note = e.get("note") or e.get("reason") or ""
            print(f"    {ts[:25]:25}  {evt:30}  leg={leg}  oid={oid}  {note[:40]}")
    else:
        print("  (bracket_lifecycle_events collection not present)")

    # ── 4. ib_executions for ARM SELLs, last 2d ──────────────────────────
    hr("Section 4 — ib_executions for ARM SELL fills, last 2 days")
    if "ib_executions" in db.list_collection_names():
        execs = list(db["ib_executions"].find(
            {"symbol": "ARM",
             "$and": [
                 {"$or": [{"side": "SELL"}, {"action": "SELL"}]},
                 {"$or": [{"time": {"$gte": since_2d}},
                          {"exec_time": {"$gte": since_2d}},
                          {"ts": {"$gte": since_2d}}]},
             ]},
            {"_id": 0},
        ))
        print(f"  found {len(execs)} ARM SELL execs")
        for e in execs:
            t = e.get("time") or e.get("exec_time") or e.get("ts") or "?"
            sh = e.get("shares") or e.get("qty") or 0
            px = e.get("price") or e.get("fill_price") or e.get("avg_price") or 0
            oid = e.get("order_id", "")
            xid = e.get("exec_id", "")
            print(f"    {t[:25]:25}  shares={sh:<6}  price={px:<10}  "
                  f"order_id={oid}  exec_id={xid}")

        # Cross-ref to ARM bot_trades' target_order_ids
        all_tgt_ids = set()
        for t in arm_trades:
            for tid in (t.get("target_order_ids") or []):
                all_tgt_ids.add(str(tid))
        if all_tgt_ids:
            print(f"\n  ARM target_order_ids tracked: {sorted(all_tgt_ids)[:10]}")
            for e in execs:
                if str(e.get("order_id")) in all_tgt_ids:
                    print(f"  ✓ MATCH: exec order_id={e.get('order_id')} "
                          f"is a target leg!  → exit_price={e.get('price')}")
    else:
        print("  (ib_executions collection not present)")

    print("\nDONE.")


if __name__ == "__main__":
    main()
