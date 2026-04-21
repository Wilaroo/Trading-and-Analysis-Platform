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

    # Sample 5 cancelled docs to inspect schema
    print("\n=== Sample 5 cancelled docs (full field set) ===")
    for d in bt.find({"status": {"$in": ["cancelled", "canceled"]}}).limit(5):
        # Remove _id for readability, print keys only
        keys = sorted(d.keys())
        print(f"  id={d.get('id', '?')} sym={d.get('symbol', '?'):<6} setup={d.get('setup_type', '?')}")
        print(f"    keys present: {keys}")
        print(f"    entry={d.get('entry_price')} fill={d.get('fill_price')} "
              f"stop={d.get('stop_price')} order_type={d.get('order_type')}")

    # Age before cancel
    print("\n=== Age before cancel (created_at → last_updated diff) ===")
    ages = []
    for d in bt.find(
        {"status": {"$in": ["cancelled", "canceled"]},
         "created_at": {"$exists": True},
         "last_updated": {"$exists": True}},
        {"created_at": 1, "last_updated": 1, "_id": 0}
    ).limit(5000):
        try:
            # ISO strings → parse
            from datetime import datetime
            a = datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(d["last_updated"]).replace("Z", "+00:00"))
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
