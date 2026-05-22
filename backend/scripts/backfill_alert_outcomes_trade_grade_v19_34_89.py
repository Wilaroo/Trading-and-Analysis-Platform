#!/usr/bin/env python3
"""
backfill_alert_outcomes_trade_grade_v19_34_89.py
─────────────────────────────────────────────────────────────────────────────
One-shot backfill for the v19.34.89 fix.

PROBLEM
  Pre-v89, `pnl_compute._record_alert_outcome_bestEffort` wrote
  `alert_outcomes.trade_grade` from `trade.trade_grade`, which was almost
  always None. The actual SMB grade lives on `bot_trades.smb_grade`.
  Result: ~180 historical `alert_outcomes` rows have `trade_grade=None`
  and `setup_retro.py`'s A/B/C bucket breakdown is empty.

WHAT THIS DOES
  For every `alert_outcomes` doc where `trade_grade in (None, "", null)`,
  look up the matching `bot_trades` row by `trade_id` (falling back to
  `alert_id`), copy `smb_grade` into `trade_grade`, and stamp a
  `backfilled_by` audit field so we never double-process the row.

SAFETY
  - Idempotent: filters out rows already stamped with `backfilled_by`.
  - Dry-run by default. Pass `--apply` to actually write.
  - Prints a per-grade summary before/after.

USAGE
  # Dry run (default — shows what would change):
  python3 backend/scripts/backfill_alert_outcomes_trade_grade_v19_34_89.py

  # Real write:
  python3 backend/scripts/backfill_alert_outcomes_trade_grade_v19_34_89.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

try:
    from pymongo import MongoClient
except ImportError:
    print("ERROR: pymongo not installed. `pip install pymongo`.", file=sys.stderr)
    sys.exit(1)


BACKFILL_TAG = "backfill_v19_34_89"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write the updates (default: dry run).")
    parser.add_argument("--limit", type=int, default=0,
                        help="Optional cap on docs scanned (0 = all).")
    args = parser.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    if not mongo_url:
        print("ERROR: MONGO_URL env var not set.", file=sys.stderr)
        return 2

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
    db = client[db_name]
    outcomes = db["alert_outcomes"]
    trades = db["bot_trades"]

    # Find every outcome row that needs a grade copied in.
    filt = {
        "$and": [
            {"$or": [
                {"trade_grade": None},
                {"trade_grade": ""},
                {"trade_grade": {"$exists": False}},
            ]},
            {"backfilled_by": {"$ne": BACKFILL_TAG}},
        ]
    }
    cursor = outcomes.find(filt, {
        "_id": 1, "trade_id": 1, "alert_id": 1, "symbol": 1,
    })
    if args.limit > 0:
        cursor = cursor.limit(args.limit)

    scanned = 0
    matched_with_grade = 0
    matched_no_grade = 0
    no_trade = 0
    grade_dist: Counter = Counter()
    updates: list[tuple[object, str]] = []

    for doc in cursor:
        scanned += 1
        tid = doc.get("trade_id") or doc.get("alert_id")
        if not tid:
            no_trade += 1
            continue
        trade = trades.find_one(
            {"$or": [{"id": tid}, {"alert_id": tid}]},
            {"_id": 0, "smb_grade": 1, "trade_grade": 1},
        )
        if not trade:
            no_trade += 1
            continue
        grade = trade.get("smb_grade") or trade.get("trade_grade")
        if not grade:
            matched_no_grade += 1
            continue
        matched_with_grade += 1
        grade_dist[grade] += 1
        updates.append((doc["_id"], grade))

    print("\n[backfill v19.34.89] scan summary")
    print(f"  scanned outcomes (needing grade)     : {scanned}")
    print(f"  matched to a bot_trade with a grade  : {matched_with_grade}")
    print(f"  matched but trade has no grade       : {matched_no_grade}")
    print(f"  outcomes with no matching bot_trade  : {no_trade}")
    print("  grade distribution (would write):")
    for g, n in sorted(grade_dist.items()):
        print(f"    {g:>4} : {n}")

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to write.")
        return 0

    if not updates:
        print("\nNo rows to update. Done.")
        return 0

    written = 0
    for oid, grade in updates:
        res = outcomes.update_one(
            {"_id": oid},
            {"$set": {"trade_grade": grade, "backfilled_by": BACKFILL_TAG}},
        )
        if res.modified_count == 1:
            written += 1

    print(f"\n[backfill v19.34.89] wrote {written}/{len(updates)} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
