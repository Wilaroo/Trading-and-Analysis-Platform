"""Investigate the 97% order-cancellation rate (2026-04-21).

Audit showed 6,632 bot_trades with status=cancelled — dwarfs filled trades
(220). Before fixing it we need to know WHY orders cancel:
  - Stale limit prices (price moved before fill)
  - Too-aggressive limit offset (trying to shave pennies)
  - Manual bot restarts (pending orders died with the process)
  - IB gateway disconnects
  - Setup-specific rejection patterns (some setups may cancel 100%, others 50%)

This script breaks down cancellations by:
  - setup_type (is one setup responsible for most cancels?)
  - cancel reason (if stored in the doc)
  - time-of-day (market open? midday?)
  - order type (LMT vs MKT?)
  - age before cancel (did it cancel in 1s or 30m?)
  - symbol class (liquid vs thin?)

Run
---
    PYTHONPATH=backend python backend/scripts/investigate_cancellations.py
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict

from pymongo import MongoClient


def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


def main():
    db = get_db()
    bt = db["bot_trades"]
    print(f"[cancel-audit] db={db.name}")

    total = bt.count_documents({"status": {"$in": ["cancelled", "canceled"]}})
    print(f"[cancel-audit] Total cancelled: {total}")

    # Per-setup breakdown
    print("\n=== Cancellations per setup ===")
    rows = list(bt.aggregate([
        {"$match": {"status": {"$in": ["cancelled", "canceled"]}}},
        {"$group": {
            "_id": "$setup_type", "n": {"$sum": 1},
            "avg_entry": {"$avg": "$entry_price"},
        }},
        {"$sort": {"n": -1}},
    ]))
    for row in rows[:15]:
        print(f"  {str(row['_id']):<28} cancelled={row['n']:>5}  avg_entry={row.get('avg_entry') or 0:>8.2f}")

    # Known cancel reason fields
    print("\n=== Cancel reason field distribution ===")
    reason_fields = ["cancel_reason", "cancellation_reason", "status_reason",
                     "reject_reason", "last_error"]
    for field in reason_fields:
        exists = bt.count_documents({"status": {"$in": ["cancelled", "canceled"]},
                                     field: {"$exists": True, "$ne": None, "$ne": ""}})
        if exists:
            print(f"  `{field}`: {exists} docs have it set")
            for row in bt.aggregate([
                {"$match": {"status": {"$in": ["cancelled", "canceled"]},
                            field: {"$exists": True, "$ne": None}}},
                {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 10},
            ]):
                print(f"    {str(row['_id'])[:60]:<60} {row['n']}")
    # Also check order_type
    print("\n=== Order type mix (cancelled vs filled) ===")
    for ot_status in [("cancelled", "$in", ["cancelled", "canceled"]),
                      ("filled",     "$in", ["closed", "closed_manual"])]:
        label, op, val = ot_status
        counts: Counter = Counter()
        for d in bt.find({"status": {op: val}}, {"order_type": 1, "_id": 0}):
            counts[d.get("order_type", "?")] += 1
        summary = ", ".join(f"{k}={v}" for k, v in counts.most_common())
        print(f"  {label:<10} : {summary or 'no order_type field'}")

    # close_reason — the real "why" field on this schema
    print("\n=== close_reason distribution (cancelled docs) ===")
    reason_rows = list(bt.aggregate([
        {"$match": {"status": {"$in": ["cancelled", "canceled"]}}},
        {"$group": {"_id": "$close_reason", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": 20},
    ]))
    for row in reason_rows:
        label = str(row["_id"]) if row["_id"] is not None else "(null)"
        print(f"  {label[:60]:<60} {row['n']}")

    # entry_order_id presence — did we actually submit to pusher?
    print("\n=== entry_order_id presence on cancelled docs ===")
    total_cxl = bt.count_documents({"status": {"$in": ["cancelled", "canceled"]}})
    with_oid = bt.count_documents({
        "status": {"$in": ["cancelled", "canceled"]},
        "entry_order_id": {"$exists": True, "$nin": [None, ""]},
    })
    without_oid = total_cxl - with_oid
    print(f"  has entry_order_id  : {with_oid:>5}  ({with_oid/total_cxl:.1%})")
    print(f"  missing order_id    : {without_oid:>5}  ({without_oid/total_cxl:.1%}) → never queued / bot-side cancel")

    # Cross-check with order_queue collection (what pusher actually saw)
    print("\n=== order_queue status for cancelled bot_trades ===")
    oq = db["order_queue"]
    if oq.estimated_document_count() > 0:
        # Sample 2000 cancelled bot_trades that HAVE an entry_order_id, look them up
        oids = [d["entry_order_id"] for d in bt.find(
            {"status": {"$in": ["cancelled", "canceled"]},
             "entry_order_id": {"$exists": True, "$nin": [None, ""]}},
            {"entry_order_id": 1, "_id": 0}
        ).limit(2000)]
        print(f"  sampled {len(oids)} bot_trades with entry_order_id")
        if oids:
            oq_status = Counter()
            for oq_doc in oq.find({"order_id": {"$in": oids}},
                                  {"order_id": 1, "status": 1, "result": 1, "_id": 0}):
                oq_status[oq_doc.get("status", "?")] += 1
            matched = sum(oq_status.values())
            print(f"  matched in order_queue : {matched}/{len(oids)}")
            for k, v in oq_status.most_common():
                print(f"    {str(k):<20} {v}")
            print(f"  unmatched (not in oq)  : {len(oids) - matched}")
    else:
        print("  order_queue collection empty")

    # Age before cancel — use closed_at (last_updated doesn't exist on this schema)
    print("\n=== Age before cancel (created_at → closed_at) ===")
    ages = []
    for d in bt.find(
        {"status": {"$in": ["cancelled", "canceled"]},
         "created_at": {"$exists": True},
         "closed_at": {"$exists": True}},
        {"created_at": 1, "closed_at": 1, "_id": 0}
    ).limit(5000):
        try:
            # ISO strings → parse
            from datetime import datetime
            a = datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(d["closed_at"]).replace("Z", "+00:00"))
            ages.append((b - a).total_seconds())
        except Exception:
            continue
    if ages:
        ages.sort()
        n = len(ages)
        print(f"  Sample size: {n}")
        print(f"  Median age before cancel: {ages[n//2]:.1f}s")
        print(f"  p90: {ages[int(n*0.9)]:.1f}s   p95: {ages[int(n*0.95)]:.1f}s   max: {ages[-1]:.1f}s")
        bucket = defaultdict(int)
        for a in ages:
            if a < 1: bucket["<1s"] += 1
            elif a < 10: bucket["1-10s"] += 1
            elif a < 60: bucket["10-60s"] += 1
            elif a < 300: bucket["1-5m"] += 1
            elif a < 3600: bucket["5-60m"] += 1
            elif a < 86400: bucket["1-24h"] += 1
            else: bucket[">24h"] += 1
        for b, c in [("<1s", 0), ("1-10s", 0), ("10-60s", 0), ("1-5m", 0),
                     ("5-60m", 0), ("1-24h", 0), (">24h", 0)]:
            print(f"    {b:<8}: {bucket.get(b, 0)}")


if __name__ == "__main__":
    main()
