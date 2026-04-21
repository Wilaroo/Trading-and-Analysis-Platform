"""Retro-tag bot-side filter trades (2026-04-22).

The 2026-04-22 audit revealed all 6,632 "cancelled" bot_trades were actually
strategy-phase filters (simulation_phase / paper_phase) — not broker cancels.
They dogpiled into the CANCELLED bucket and made the execution health
dashboard show a bogus 97% cancel rate.

This script retro-tags them by `close_reason`:
  - close_reason == "simulation_phase"  → status = "simulated"
  - close_reason == "paper_phase"       → status = "paper"
  - close_reason == "guardrail_veto"    → status = "vetoed"
  - anything else that's currently "cancelled"  → leave alone (real broker cancels)

Idempotent. Safe to re-run.

Usage:
    PYTHONPATH=backend python3 backend/scripts/retag_bot_side_cancels.py
    PYTHONPATH=backend python3 backend/scripts/retag_bot_side_cancels.py --dry-run
"""
from __future__ import annotations

import os
import sys
from pymongo import MongoClient


def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


RETAG_MAP = {
    "simulation_phase": "simulated",
    "paper_phase":      "paper",
    "guardrail_veto":   "vetoed",
}


def main(dry_run: bool = False):
    db = get_db()
    bt = db["bot_trades"]
    print(f"[retag] db={db.name}  dry_run={dry_run}")

    total_before = bt.count_documents({"status": {"$in": ["cancelled", "canceled"]}})
    print(f"[retag] docs with status=cancelled BEFORE: {total_before}")

    grand_total = 0
    for reason, new_status in RETAG_MAP.items():
        filt = {
            "status": {"$in": ["cancelled", "canceled"]},
            "close_reason": reason,
        }
        n = bt.count_documents(filt)
        if n == 0:
            print(f"  {reason:<20} → {new_status:<12}  : 0 docs (skip)")
            continue
        print(f"  {reason:<20} → {new_status:<12}  : {n} docs", end="")
        if dry_run:
            print("  [DRY RUN]")
        else:
            res = bt.update_many(filt, {"$set": {"status": new_status}})
            print(f"  → modified {res.modified_count}")
            grand_total += res.modified_count

    total_after = bt.count_documents({"status": {"$in": ["cancelled", "canceled"]}})
    print(f"[retag] docs with status=cancelled AFTER : {total_after}")
    print(f"[retag] retagged {grand_total} docs")

    # Final breakdown by status
    print("\n=== Final status distribution ===")
    for row in bt.aggregate([
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]):
        print(f"  {str(row['_id']):<15} {row['n']}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
