"""Backfill `r_multiple` on closed bot_trades docs that have entry/stop/exit.

Problem
-------
The setup-coverage audit showed `avg_R` is "—" across every setup — meaning no
bot_trades doc has `r_multiple` stored. Win-rate alone is meaningless for
training Phase 2E models: a 75%-WR setup with 0.2R wins and 3R losses is a
losing strategy.

Fix
---
R-multiple is pure math given the 3 prices we already store:
    long:  r = (exit_price - entry_price) / (entry_price - stop_price)
    short: r = (entry_price - exit_price) / (stop_price - entry_price)

This script scans `bot_trades` for closed docs missing `r_multiple` and
fills it in. Idempotent (skips docs that already have the field set).

Run
---
    PYTHONPATH=backend python backend/scripts/backfill_r_multiples.py
    PYTHONPATH=backend python backend/scripts/backfill_r_multiples.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient


# ── Pure helper (unit-tested) ─────────────────────────────────────────────

def compute_r_multiple(
    entry_price: float,
    stop_price: float,
    exit_price: float,
    direction: str,
) -> float | None:
    """Return signed R-multiple, or None if the inputs are degenerate.

    A long with exit == entry returns 0R (break-even).
    A long stopped exactly at stop returns -1R.
    """
    if entry_price is None or stop_price is None or exit_price is None:
        return None
    try:
        entry = float(entry_price)
        stop = float(stop_price)
        exit_ = float(exit_price)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or stop <= 0 or exit_ <= 0:
        return None

    dir_lower = (direction or "").lower()
    if dir_lower in ("long", "buy", "up"):
        risk = entry - stop
    elif dir_lower in ("short", "sell", "down"):
        risk = stop - entry
    else:
        return None

    if risk == 0:
        return None  # Can't compute R when stop is at entry

    if dir_lower in ("long", "buy", "up"):
        return (exit_ - entry) / risk
    return (entry - exit_) / risk


# ── Main ──────────────────────────────────────────────────────────────────

def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute but don't write to Mongo.")
    ap.add_argument("--collection", default="bot_trades")
    args = ap.parse_args()

    db = get_db()
    coll = db[args.collection]
    print(f"[backfill] db={db.name} collection={args.collection}")

    # Only consider closed trades with all 3 prices, and no r_multiple set.
    filt = {
        "exit_price": {"$exists": True, "$ne": None},
        "entry_price": {"$exists": True, "$ne": None},
        "stop_price": {"$exists": True, "$ne": None},
        "$or": [
            {"r_multiple": {"$exists": False}},
            {"r_multiple": None},
        ],
    }

    updated = 0
    skipped = 0
    per_setup: Counter = Counter()
    reasons: Counter = Counter()

    cursor = coll.find(filt, {"_id": 1, "entry_price": 1, "stop_price": 1,
                              "exit_price": 1, "direction": 1,
                              "setup_type": 1})

    for doc in cursor:
        r = compute_r_multiple(
            doc.get("entry_price"), doc.get("stop_price"),
            doc.get("exit_price"), doc.get("direction"),
        )
        if r is None:
            skipped += 1
            dir_lower = (doc.get("direction") or "").lower()
            if not dir_lower:
                reasons["missing_direction"] += 1
            elif dir_lower not in ("long", "buy", "up", "short", "sell", "down"):
                reasons[f"unknown_direction:{dir_lower}"] += 1
            else:
                reasons["zero_risk_or_bad_price"] += 1
            continue

        setup = doc.get("setup_type", "?")
        per_setup[setup] += 1

        if not args.dry_run:
            coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"r_multiple": round(r, 4)}},
            )
        updated += 1

    print(f"[backfill] updated={updated} skipped={skipped} "
          f"{'(DRY RUN)' if args.dry_run else ''}")
    if skipped:
        print("[backfill] skip reasons:")
        for reason, n in reasons.most_common():
            print(f"  {n:>6} {reason}")
    if per_setup:
        print("[backfill] R-multiples backfilled by setup (top 20):")
        for setup, n in per_setup.most_common(20):
            print(f"  {n:>6} {setup}")

    # Emit a quick post-backfill summary of R distribution
    if not args.dry_run and updated:
        print("\n[backfill] Post-backfill R distribution (all bot_trades with r_multiple):")
        pipeline = [
            {"$match": {"r_multiple": {"$ne": None}}},
            {"$group": {
                "_id": "$setup_type",
                "n": {"$sum": 1},
                "avg_r": {"$avg": "$r_multiple"},
                "wins": {"$sum": {"$cond": [{"$gt": ["$r_multiple", 0]}, 1, 0]}},
                "losses": {"$sum": {"$cond": [{"$lt": ["$r_multiple", 0]}, 1, 0]}},
            }},
            {"$sort": {"n": -1}},
            {"$limit": 20},
        ]
        for row in coll.aggregate(pipeline):
            wr = row["wins"] / (row["wins"] + row["losses"]) if (row["wins"] + row["losses"]) else 0.0
            print(f"  {row['_id']:<28} n={row['n']:>5}  wr={wr:>5.1%}  avgR={row['avg_r']:+.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
