"""Collapse `relative_strength_leader` / `relative_strength_laggard` into the
taxonomy-canonical `relative_strength_long` / `relative_strength_short`.

Problem
-------
Setup coverage audit shows 29,350 alerts on `relative_strength_leader/laggard`
(the biggest class by volume) tagged with names NOT in TRADING_TAXONOMY.md.
Meanwhile the canonical `relative_strength` code has zero data. This is
scanner drift — the scanner emits a different name than the taxonomy expects.

Fix
---
Rename in all 4 collections:
    relative_strength_leader  → relative_strength_long
    relative_strength_laggard → relative_strength_short

This matches the audit script's normalization (`_long`/`_short` suffixes get
stripped back to `relative_strength` for per-code stats), so the 29k rows
start counting toward taxonomy coverage instead of "scanner drift".

Run
---
    PYTHONPATH=backend python backend/scripts/collapse_relative_strength.py --dry-run
    PYTHONPATH=backend python backend/scripts/collapse_relative_strength.py
"""
from __future__ import annotations

import argparse
import os
from typing import Dict, Tuple

from pymongo import MongoClient


# ── Pure rename map (unit-tested) ────────────────────────────────────────

RENAME_MAP: Dict[str, str] = {
    "relative_strength_leader": "relative_strength_long",
    "relative_strength_laggard": "relative_strength_short",
    # Case-insensitive variants are handled by the query
}

COLLECTIONS = ("trades", "bot_trades", "trade_snapshots", "live_alerts")


def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


def plan_updates(db) -> Dict[Tuple[str, str, str], int]:
    """Count how many docs would change per (collection, old, new). Read-only."""
    plan: Dict[Tuple[str, str, str], int] = {}
    for coll_name in COLLECTIONS:
        coll = db[coll_name]
        for old, new in RENAME_MAP.items():
            # Case-insensitive exact match
            n = coll.count_documents({"setup_type": {"$regex": f"^{old}$", "$options": "i"}})
            plan[(coll_name, old, new)] = n
    return plan


def apply_updates(db, plan: Dict[Tuple[str, str, str], int]) -> int:
    """Execute the rename. Returns total docs modified."""
    total = 0
    for (coll_name, old, new), count in plan.items():
        if count == 0:
            continue
        coll = db[coll_name]
        res = coll.update_many(
            {"setup_type": {"$regex": f"^{old}$", "$options": "i"}},
            {"$set": {"setup_type": new}},
        )
        total += res.modified_count
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan but don't write.")
    args = ap.parse_args()

    db = get_db()
    print(f"[collapse-rs] db={db.name}")

    plan = plan_updates(db)
    total_planned = sum(plan.values())
    print(f"[collapse-rs] rename plan ({total_planned} docs):")
    for (coll, old, new), n in plan.items():
        if n > 0:
            print(f"  {coll:>18}: {n:>6} docs  '{old}' → '{new}'")
    if total_planned == 0:
        print("[collapse-rs] Nothing to rename — already clean.")
        return

    if args.dry_run:
        print("[collapse-rs] DRY-RUN — no writes. Re-run without --dry-run to apply.")
        return

    modified = apply_updates(db, plan)
    print(f"[collapse-rs] ✅ Renamed {modified} docs.")
    print("[collapse-rs] Re-run `audit_setup_coverage.py` to see the updated picture.")


if __name__ == "__main__":
    main()
