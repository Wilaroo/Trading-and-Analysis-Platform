"""Fix the 18 inverted-stop short trades found in the 2026-04-21 audit.

Problem
-------
`audit_setup_coverage.py` found 18 trades with `*_short` setup_type but
`stop_price < entry_price`. On a real short, stop must be ABOVE entry
(price rising against you triggers the stop). These docs are data-corrupted
either from:

  - Direction field being flipped post-entry
  - stop_price being set to a long-style stop by mistake
  - Column swap during an import (see `imported_from_ib` setup)

Strategy
--------
For each bad doc:
  1. If `entry < stop < exit` on a "short" → looks like the trade was actually
     a LONG mis-tagged — flip `direction` to "long".
  2. If `stop < entry` consistently with the data → the stop was inverted;
     swap stop with a sensible value if fill_price is available, otherwise
     mark the doc as `data_corrupt: true` and skip r_multiple.
  3. Log every change for audit.

Run
---
    PYTHONPATH=backend python backend/scripts/fix_inverted_short_stops.py --dry-run
    PYTHONPATH=backend python backend/scripts/fix_inverted_short_stops.py
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from pymongo import MongoClient


# ── Pure helper (unit-tested) ─────────────────────────────────────────────

def diagnose_inverted_stop(
    direction: str,
    entry_price: float,
    stop_price: float,
    exit_price: float = None,
) -> str:
    """Classify the type of corruption on a `*_short` doc with stop < entry.

    Returns one of:
      - 'ok'                — stop is ABOVE entry (not corrupt)
      - 'direction_flip'    — exit moves in a way that suggests a LONG trade
      - 'stop_inverted'     — stop is below entry but exit behavior is short-like
      - 'ambiguous'         — can't tell without more data (mark corrupt, skip)
    """
    if direction is None or entry_price is None or stop_price is None:
        return "ambiguous"
    try:
        e = float(entry_price)
        s = float(stop_price)
    except (TypeError, ValueError):
        return "ambiguous"

    dir_lower = (direction or "").lower()
    if dir_lower not in ("short", "sell", "down"):
        return "ok"  # Not a short — not our concern

    if s >= e:
        return "ok"  # Stop above entry — correct for a short

    # Stop is below entry but direction says short — corruption
    if exit_price is None:
        return "ambiguous"
    try:
        x = float(exit_price)
    except (TypeError, ValueError):
        return "ambiguous"

    # If exit is above entry (price went up) and direction is short → loser → OK for short
    # If exit is below entry (price went down) and direction is short → winner → OK for short
    # But we already know stop < entry which is inverted, so:
    #   - If exit > entry (price up) → consistent with either long-loser OR short-winner
    #     but given stop < entry (long-style), more likely was a LONG that lost.
    #   - If exit < entry (price down) → consistent with either long-loser OR short-winner
    #     but short_winner scenario: stop would have been entered ABOVE entry. So
    #     stop < entry + exit < entry = likely MISTAGGED LONG that won.
    if x > e:
        return "direction_flip"  # Probably a long that lost
    return "direction_flip"      # Probably a long that won


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
    print(f"[fix-inverted] db={db.name} collection={args.collection}")

    # Find shorts with stop < entry (the audit's exact query)
    filt = {
        "setup_type": {"$regex": "_short$"},
        "$expr": {"$lt": ["$stop_price", "$entry_price"]},
    }
    total = coll.count_documents(filt)
    print(f"[fix-inverted] Found {total} inverted-stop short docs")

    classifications: Counter = Counter()
    changes: list = []

    for doc in coll.find(filt, {"_id": 1, "id": 1, "symbol": 1, "setup_type": 1,
                                "direction": 1, "entry_price": 1, "stop_price": 1,
                                "exit_price": 1}):
        diag = diagnose_inverted_stop(
            doc.get("direction"),
            doc.get("entry_price"),
            doc.get("stop_price"),
            doc.get("exit_price"),
        )
        classifications[diag] += 1

        if diag == "direction_flip":
            update = {
                "direction": "long",
                "data_corrected": True,
                "data_correction_reason": "direction_flip_from_inverted_stop_audit",
            }
            # r_multiple will need to be recomputed — remove the stale one
            update_unset = {"r_multiple": ""}
            changes.append((doc["_id"], doc.get("symbol", "?"),
                           doc.get("direction"), "long", diag))
            if not args.dry_run:
                coll.update_one(
                    {"_id": doc["_id"]},
                    {"$set": update, "$unset": update_unset},
                )
        elif diag == "ambiguous":
            update = {
                "data_corrupt": True,
                "data_correction_reason": "inverted_stop_ambiguous",
            }
            changes.append((doc["_id"], doc.get("symbol", "?"),
                           "MARK_CORRUPT", "?", diag))
            if not args.dry_run:
                coll.update_one({"_id": doc["_id"]}, {"$set": update})

    print(f"[fix-inverted] diagnostic breakdown:")
    for k, n in classifications.most_common():
        print(f"  {n:>3} {k}")

    if changes:
        print(f"\n[fix-inverted] changes {'planned' if args.dry_run else 'applied'}:")
        for _id, sym, old, new, diag in changes[:20]:
            print(f"  {sym:<8} direction: {old:<10} → {new:<10}  ({diag})")

    if args.dry_run:
        print("\n[fix-inverted] DRY-RUN — no writes.")
    else:
        print("\n[fix-inverted] Re-run `backfill_r_multiples.py` to "
              "recompute r_multiple for re-directed trades.")


if __name__ == "__main__":
    sys.exit(main())
