"""Backfill `exit_price` on bot_trades that were marked `status=closed` but
never had the exit price persisted.

Problem
-------
The Mongo audit revealed 70 docs with `status=closed` AND `exit_price=None`.
These are real trades that completed but hit a persistence bug — likely a
race condition in `_close_trade` where status was flipped before the full
doc was persisted.

Recovery strategy
-----------------
For each orphaned doc we can try, in order:
  1. `fill_price` + `realized_pnl` + `shares` + `direction` → infer exit
     (long:  exit = fill + pnl/shares ; short: exit = fill - pnl/shares)
  2. If only `realized_pnl` is present (no fill_price) → can derive % return
     but not absolute exit price → skip (mark as "partial_recover")
  3. Anything we can't recover → leave alone (keeps data honest)

Also writes `r_multiple` when we have entry/stop/exit (reuses the same
compute_r_multiple helper).

Run
---
    PYTHONPATH=backend python backend/scripts/backfill_closed_no_exit.py --dry-run
    PYTHONPATH=backend python backend/scripts/backfill_closed_no_exit.py
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient

# Reuse the pure helper — avoids code drift
from scripts.backfill_r_multiples import compute_r_multiple  # type: ignore


# ── Pure helpers (unit-tested) ────────────────────────────────────────────

def infer_exit_from_pnl(
    fill_price: float,
    realized_pnl: float,
    shares: int,
    direction: str,
) -> float | None:
    """Compute exit price from the accounting identity.

    Long:  realized_pnl = shares * (exit - fill)  → exit = fill + pnl/shares
    Short: realized_pnl = shares * (fill - exit)  → exit = fill - pnl/shares
    """
    if fill_price is None or realized_pnl is None or shares is None:
        return None
    try:
        f = float(fill_price)
        p = float(realized_pnl)
        n = int(shares)
    except (TypeError, ValueError):
        return None
    if n <= 0 or f <= 0:
        return None

    dir_lower = (direction or "").lower()
    if dir_lower in ("long", "buy", "up"):
        return round(f + p / n, 4)
    if dir_lower in ("short", "sell", "down"):
        return round(f - p / n, 4)
    return None


# ── Main ──────────────────────────────────────────────────────────────────

def get_db():
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME", "tradecommand")
    return MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--collection", default="bot_trades")
    args = ap.parse_args()

    db = get_db()
    coll = db[args.collection]
    print(f"[fix-closed] db={db.name} collection={args.collection}")

    filt = {
        "status": {"$in": ["closed", "closed_manual"]},
        "$or": [{"exit_price": None}, {"exit_price": {"$exists": False}}],
    }
    total = coll.count_documents(filt)
    print(f"[fix-closed] Found {total} closed-no-exit docs")

    recovered = 0
    unrecoverable = 0
    r_updated = 0
    reasons: Counter = Counter()

    cursor = coll.find(filt, {"_id": 1, "id": 1, "symbol": 1, "setup_type": 1,
                              "direction": 1, "entry_price": 1, "stop_price": 1,
                              "fill_price": 1, "realized_pnl": 1, "shares": 1})

    for doc in cursor:
        fill = doc.get("fill_price") or doc.get("entry_price")  # fall back to entry
        pnl = doc.get("realized_pnl")
        shares = doc.get("shares")
        direction = doc.get("direction")

        exit_p = infer_exit_from_pnl(fill, pnl, shares, direction)
        if exit_p is None:
            unrecoverable += 1
            if pnl is None:
                reasons["no_realized_pnl"] += 1
            elif not fill:
                reasons["no_fill_or_entry_price"] += 1
            elif not shares:
                reasons["no_shares"] += 1
            elif not direction:
                reasons["no_direction"] += 1
            else:
                reasons["other"] += 1
            continue

        update: dict = {"exit_price": exit_p, "exit_price_inferred": True}

        # Also compute r_multiple while we're here
        r = compute_r_multiple(
            doc.get("entry_price"), doc.get("stop_price"),
            exit_p, direction,
        )
        if r is not None:
            update["r_multiple"] = round(r, 4)
            r_updated += 1

        if not args.dry_run:
            coll.update_one({"_id": doc["_id"]}, {"$set": update})
        recovered += 1

    print(f"[fix-closed] recovered={recovered} r_multiple_set={r_updated} "
          f"unrecoverable={unrecoverable} {'(DRY RUN)' if args.dry_run else ''}")
    if reasons:
        print("[fix-closed] Unrecoverable reasons:")
        for reason, n in reasons.most_common():
            print(f"  {n:>4} {reason}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
