#!/usr/bin/env python3
"""
backfill_hold_seconds.py
========================
One-time (idempotent) backfill of the `hold_seconds` label on CLOSED
`bot_trades` rows. Companion to the v19.34.274 instrumentation that now
stamps `hold_seconds` on every fresh close via `BotTrade.to_dict()`.

`hold_seconds = closed_at − (executed_at || created_at)` in seconds.

Idempotent: only touches CLOSED rows where `hold_seconds` is missing or
None AND both the entry timestamp and `closed_at` parse cleanly. Re-runs
are safe — already-stamped rows are skipped.

Run from the backend dir on the DGX:
    python scripts/backfill_hold_seconds.py            # apply
    python scripts/backfill_hold_seconds.py --dry-run  # report only
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
load_dotenv(_BACKEND / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")


def _parse(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _hold_seconds(entry_ts, close_ts):
    a = _parse(entry_ts)
    b = _parse(close_ts)
    if a is None or b is None:
        return None
    secs = (b - a).total_seconds()
    return round(secs, 1) if secs >= 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change without writing.")
    args = ap.parse_args()

    client = MongoClient(MONGO_URL)
    col = client[DB_NAME]["bot_trades"]

    query = {
        "status": {"$in": ["closed", "CLOSED"]},
        "$or": [
            {"hold_seconds": {"$exists": False}},
            {"hold_seconds": None},
        ],
    }
    cursor = col.find(
        query,
        {"_id": 1, "executed_at": 1, "created_at": 1, "closed_at": 1},
    )

    scanned = updated = skipped = 0
    for doc in cursor:
        scanned += 1
        hs = _hold_seconds(doc.get("executed_at") or doc.get("created_at"),
                           doc.get("closed_at"))
        if hs is None:
            skipped += 1
            continue
        if args.dry_run:
            updated += 1
            continue
        col.update_one({"_id": doc["_id"]}, {"$set": {"hold_seconds": hs}})
        updated += 1

    verb = "would update" if args.dry_run else "updated"
    print(f"hold_seconds backfill: scanned={scanned} {verb}={updated} "
          f"skipped(unparseable)={skipped}")
    client.close()


if __name__ == "__main__":
    main()
