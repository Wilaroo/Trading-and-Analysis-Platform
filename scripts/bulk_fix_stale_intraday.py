#!/usr/bin/env python3
"""
bulk_fix_stale_intraday.py — fan out the GOOGL fix to every intraday
symbol whose 1-min or 15-min timeframe is stale (or any user-supplied
list of bar sizes).

Why this exists: smart-backfill checks freshness *per symbol* and
considers a symbol fresh if ANY of its bar_sizes are fresh. So when
the daily / hourly / 5-min backfill ran, every symbol's 1-min and
15-min got skipped — leaving ~1,500 intraday symbols with 1-min and
15-min latest bars older than the freshness budget.

This script:
  1. Walks the intraday universe (avg_volume >= 500K from
     `symbol_adv_cache`).
  2. For each (symbol, bar_size) pair, looks up the latest bar in
     `ib_historical_data`.
  3. If the latest bar is older than the freshness budget for that
     bar_size, queues a one-shot refill request via
     `HistoricalDataQueueService.create_request()` — IB will fill from
     "now" backward to its max-lookback for the bar_size.

Usage:
    ~/venv/bin/python3 scripts/bulk_fix_stale_intraday.py
    # specific bar sizes:
    ~/venv/bin/python3 scripts/bulk_fix_stale_intraday.py --bar-sizes "1 min,15 mins"
    # dry-run only:
    ~/venv/bin/python3 scripts/bulk_fix_stale_intraday.py --dry-run

Idempotent: skip_if_pending=True ensures we don't re-queue requests
that are already pending for the same (symbol, bar_size).
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
except ImportError:
    pass

from pymongo import MongoClient
from services.historical_data_queue_service import HistoricalDataQueueService

# Same freshness budgets used by backfill_readiness_service.
STALE_DAYS = {
    "1 min": 3, "5 mins": 3, "15 mins": 5, "30 mins": 5,
    "1 hour": 7, "1 day": 3, "1 week": 14,
}
# Max-lookback durations IB allows in a single request, per bar size.
DEFAULT_DURATION = {
    "1 min":   "7 D",     # IB cap
    "5 mins":  "1 M",
    "15 mins": "1 M",
    "30 mins": "3 M",
    "1 hour":  "1 Y",
    "1 day":   "5 Y",
    "1 week":  "10 Y",
}

ap = argparse.ArgumentParser()
ap.add_argument("--bar-sizes", default="1 min,15 mins",
                help="Comma-separated bar_sizes to refill (default: '1 min,15 mins')")
ap.add_argument("--min-volume", type=int, default=500_000,
                help="ADV threshold for the universe (default 500K = intraday tier)")
ap.add_argument("--dry-run", action="store_true",
                help="Print what would be queued, don't insert")
args = ap.parse_args()

bar_sizes = [b.strip() for b in args.bar_sizes.split(",") if b.strip()]
for bs in bar_sizes:
    assert bs in STALE_DAYS, f"Unknown bar_size: {bs!r}; valid: {list(STALE_DAYS)}"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or os.environ.get("MONGO_DB") or "tradecommand"
print(f"Connecting: {MONGO_URL} / {DB_NAME}")
client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = client[DB_NAME]

# 1. Walk the intraday universe
adv = db["symbol_adv_cache"]
universe = sorted({
    d["symbol"] for d in adv.find(
        {"avg_volume": {"$gte": args.min_volume}}, {"symbol": 1, "_id": 0}
    ) if d.get("symbol")
})
print(f"Universe: {len(universe):,} symbols (avg_volume >= {args.min_volume:,})")
print(f"Bar sizes to refill: {bar_sizes}")
print(f"Dry run: {args.dry_run}")

# 2. Find stale (symbol, bar_size) pairs
hist = db["ib_historical_data"]
now = datetime.now(timezone.utc)

def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        ) if "T" not in str(s) else datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None

stale_pairs = []
t0 = time.time()
for i, sym in enumerate(universe):
    if i and i % 500 == 0:
        print(f"  ...scanned {i:,} symbols ({time.time() - t0:.1f}s)")
    for bs in bar_sizes:
        doc = hist.find_one(
            {"symbol": sym, "bar_size": bs},
            {"_id": 0, "date": 1},
            sort=[("date", -1)],
        )
        latest = parse_iso(doc.get("date") if doc else None)
        if latest is None:
            stale_pairs.append((sym, bs, "no_data"))
            continue
        age_days = (now - latest).total_seconds() / 86400.0
        if age_days > STALE_DAYS[bs]:
            stale_pairs.append((sym, bs, f"{age_days:.1f}d"))

print(f"\nScan finished in {time.time() - t0:.1f}s. "
      f"Found {len(stale_pairs):,} stale (symbol, bar_size) pairs.")
by_bs = {}
for _, bs, _ in stale_pairs:
    by_bs[bs] = by_bs.get(bs, 0) + 1
print("By bar size:", by_bs)

# 3. Queue refills (or dry-run)
if args.dry_run:
    print("\n--- DRY RUN — no requests queued ---")
    print("First 20 stale pairs:")
    for sym, bs, age in stale_pairs[:20]:
        print(f"  {sym:<8} {bs:<8} stale {age}")
    sys.exit(0)

svc = HistoricalDataQueueService(db)
queued = deduped = 0
print("\nQueueing refills...")
for sym, bs, _age in stale_pairs:
    duration = DEFAULT_DURATION.get(bs, "1 W")
    req_id = svc.create_request(
        symbol=sym,
        bar_size=bs,
        duration=duration,
        end_date=None,
        skip_if_pending=True,
    )
    if not req_id:
        continue
    # Tag as queued vs deduped by checking creation timestamp proximity.
    # (HistoricalDataQueueService returns existing request_id when deduped.)
    doc = db["historical_data_requests"].find_one(
        {"request_id": req_id},
        {"_id": 0, "created_at": 1},
    )
    created = doc.get("created_at") if doc else None
    if created and isinstance(created, datetime) and (now - created.replace(tzinfo=timezone.utc) if created.tzinfo is None else now - created).total_seconds() < 60:
        queued += 1
    else:
        deduped += 1

print(f"\nDone. queued={queued:,}, deduped={deduped:,}")
print("\nWatch the queue drain:")
print("  watch -n 30 'curl -fsS http://localhost:8001/api/ib-collector/queue-progress | jq .'")
print("\nRe-poll readiness once the queue is empty:")
print("  curl -fsS http://localhost:8001/api/backfill/readiness | jq '{verdict, blockers}'")
