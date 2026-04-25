#!/usr/bin/env python3
"""
fix_googl_intraday.py — surgical fix for GOOGL's stale 1-min and
15-min timeframes.

The smart-backfill auto-skipped GOOGL on these two bar sizes because
its other timeframes (5-min, 1-hour, 1-day) were already fresh, so the
"any-bar-size-recent" heuristic considered the symbol fresh overall.
Result: GOOGL 1-min and 15-min are stuck on 2026-03-17 (~39 days old),
the only thing blocking the readiness verdict from going green.

This script bypasses smart-backfill and inserts queue requests directly
via HistoricalDataQueueService.create_request(). The 4 turbo collectors
will pick them up within ~60s. Runs in a few seconds.

Usage:
    ~/venv/bin/python3 scripts/fix_googl_intraday.py [SYMBOL ...]
    ~/venv/bin/python3 scripts/fix_googl_intraday.py GOOGL TSLA
    # Default symbol = GOOGL.
"""
import sys
from pathlib import Path

# Make the backend importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import os
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except ImportError:
    pass

from pymongo import MongoClient
from services.historical_data_queue_service import HistoricalDataQueueService

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or os.environ.get("MONGO_DB") or "tradecommand"

# IB max-lookback per bar_size — same chain that smart-backfill uses
# but applied unconditionally to the symbols we care about.
DURATIONS_FOR_BAR_SIZE = {
    "1 min":   ["7 D", "7 D", "7 D", "7 D", "7 D"],   # ~5 weeks (IB caps 1-min at 1W per request)
    "15 mins": ["1 M", "1 M", "1 M", "1 M"],          # ~4 months
}

symbols = [s.upper() for s in (sys.argv[1:] or ["GOOGL"])]
print(f"Connecting: {MONGO_URL} / {DB_NAME}")
client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = client[DB_NAME]
svc = HistoricalDataQueueService(db)

queued = []
skipped = []
for sym in symbols:
    print(f"\n=== {sym} ===")
    for bar_size, durations in DURATIONS_FOR_BAR_SIZE.items():
        for i, dur in enumerate(durations):
            req_id = svc.create_request(
                symbol=sym, bar_size=bar_size, duration=dur,
                end_date=None,            # let collector chain backward
                skip_if_pending=True,
            )
            if req_id:
                # create_request returns the existing id when deduped — to
                # tell apart "queued new" vs "deduped", check the doc's
                # creation timestamp (best-effort).
                doc = db["historical_data_requests"].find_one(
                    {"request_id": req_id},
                    {"_id": 0, "status": 1, "created_at": 1},
                )
                tag = "queued" if doc and doc.get("status") in ("pending", "claimed") else "deduped"
                print(f"  {tag:>8}  {bar_size:<8} {dur:<6} → {req_id[:12]}…")
                (queued if tag == "queued" else skipped).append((sym, bar_size, dur, req_id))
            else:
                print(f"  failed   {bar_size:<8} {dur:<6}")

print(f"\nDone. queued={len(queued)}, deduped={len(skipped)}")
print("Wait ~60s, then re-check with:")
print("  ~/venv/bin/python3 scripts/verify_bar_counts.py 2>&1 | grep -E 'symbol|GOOGL'")
print("And re-poll readiness:")
print("  curl -fsS http://localhost:8001/api/backfill/readiness | jq '.verdict, .blockers'")
