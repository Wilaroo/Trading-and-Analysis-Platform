"""De-duplicate bot_trades docs with identical `id` fields (2026-04-22).

A past cleanup script ("Legacy cleanup — validator fail-open era") inserted
zeroed-out duplicates rather than updating in-place. The result: many trade
ids have 2+ docs, and `find_one({'id': x})` returns whichever is first. The
autopsy endpoint already handles this defensively, but MongoDB itself should
have one doc per id for sane aggregations.

Strategy
--------
For each duplicate group, pick the "winner" using the same informativeness
scoring the autopsy uses (r_multiple set > nonzero pnl > real exit > etc.)
Keep winner, delete losers. Idempotent.

Usage
-----
    PYTHONPATH=backend python3 backend/scripts/dedupe_bot_trades.py --dry-run
    PYTHONPATH=backend python3 backend/scripts/dedupe_bot_trades.py      # actually delete

By default runs in dry-run unless `--apply` is passed explicitly — this is
deliberate: data deletion needs an affirmative opt-in.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Any, Dict, List

from pymongo import MongoClient


def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


def informativeness(doc: Dict[str, Any]) -> int:
    """Higher = more 'real' data on this doc. Match TradeAutopsy.autopsy."""
    score = 0
    if doc.get("r_multiple") is not None:
        score += 100
    pnl = doc.get("realized_pnl")
    try:
        if pnl is not None and abs(float(pnl)) > 0.01:
            score += 50
    except (TypeError, ValueError):
        pass
    if doc.get("exit_price") not in (None, 0):
        score += 20
    if doc.get("stop_order_id"):
        score += 5
    if doc.get("entry_order_id"):
        score += 5
    # Prefer non-cleanup close_reason
    cr = (doc.get("close_reason") or "").lower()
    if cr and "legacy cleanup" not in cr:
        score += 30
    return score


def main(apply: bool = False):
    db = get_db()
    bt = db["bot_trades"]
    print(f"[dedupe] db={db.name}  apply={apply}")

    # Find ids with > 1 doc
    dup_pipeline = [
        {"$group": {"_id": "$id", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$sort": {"n": -1}},
    ]
    dup_ids = [row["_id"] for row in bt.aggregate(dup_pipeline)]
    print(f"[dedupe] Found {len(dup_ids)} ids with duplicates")
    if not dup_ids:
        return

    total_deleted = 0
    for tid in dup_ids:
        candidates: List[Dict[str, Any]] = list(bt.find({"id": tid}))
        if len(candidates) < 2:
            continue
        # Winner = highest informativeness; ties broken by natural find order
        # (can't rely on _id.generation_time — some historical docs have
        # string _ids rather than ObjectIds).
        scored = sorted(candidates, key=informativeness, reverse=True)
        winner, losers = scored[0], scored[1:]
        print(f"\n  id={tid}  (winners score={informativeness(winner)}, losers={len(losers)})")
        print(f"    KEEP    pnl={winner.get('realized_pnl')} r={winner.get('r_multiple')} reason={winner.get('close_reason')!r}")
        for loser in losers:
            print(f"    DELETE  pnl={loser.get('realized_pnl')} r={loser.get('r_multiple')} reason={loser.get('close_reason')!r}")
            if apply:
                bt.delete_one({"_id": loser["_id"]})
                total_deleted += 1

    print(f"\n[dedupe] {'DELETED' if apply else 'Would delete'} {total_deleted if apply else 'dry-run — count varies'} docs")

    # Summary
    print("\n=== Post-run status distribution ===")
    for row in bt.aggregate([
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]):
        print(f"  {str(row['_id']):<15} {row['n']}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
