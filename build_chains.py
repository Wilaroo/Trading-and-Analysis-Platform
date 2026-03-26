"""
Max Lookback Chain Builder
==========================
Generates chained IB historical data requests directly into MongoDB queue.

Run this script to queue up max-lookback chaining requests for all qualifying
symbols across specified timeframes. Runs independently of the backend server.

Usage:
    # All timeframes except 1-min (vendor covers that)
    python3 build_chains.py --bar-sizes "5 mins,15 mins,30 mins,1 hour,1 day,1 week"

    # Specific symbols only
    python3 build_chains.py --symbols AAPL,TSLA,MSFT

    # Dry run (see what would be queued)
    python3 build_chains.py --dry-run

    # Limit to 100 symbols
    python3 build_chains.py --max-symbols 100
"""

import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

# ─── IB Limits ────────────────────────────────────────────────────────────────

BAR_CONFIGS = {
    "1 min": {"max_duration": "1 W", "max_history_days": 180},
    "5 mins": {"max_duration": "1 M", "max_history_days": 730},
    "15 mins": {"max_duration": "3 M", "max_history_days": 730},
    "30 mins": {"max_duration": "6 M", "max_history_days": 730},
    "1 hour": {"max_duration": "1 Y", "max_history_days": 1825},
    "1 day": {"max_duration": "8 Y", "max_history_days": 7300},
    "1 week": {"max_duration": "20 Y", "max_history_days": 7300},
}

DURATION_TO_DAYS = {
    "1 D": 1, "2 D": 2, "1 W": 7, "2 W": 14,
    "1 M": 30, "2 M": 60, "3 M": 90, "6 M": 180,
    "1 Y": 365, "2 Y": 730, "5 Y": 1825, "8 Y": 2920,
    "10 Y": 3650, "20 Y": 7300,
}

TIER_TIMEFRAMES = {
    "intraday": ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
    "swing": ["5 mins", "30 mins", "1 hour", "1 day"],
    "investment": ["1 hour", "1 day", "1 week"],
}

ADV_THRESHOLDS = {
    "intraday": 500_000,
    "swing": 100_000,
    "investment": 50_000,
}


def get_tier(avg_volume):
    if avg_volume >= ADV_THRESHOLDS["intraday"]:
        return "intraday"
    elif avg_volume >= ADV_THRESHOLDS["swing"]:
        return "swing"
    elif avg_volume >= ADV_THRESHOLDS["investment"]:
        return "investment"
    return "skip"


def generate_chains(bar_size, earliest_existing_date=None):
    config = BAR_CONFIGS.get(bar_size)
    if not config:
        return []

    max_duration = config["max_duration"]
    max_lookback_days = config["max_history_days"]
    step_days = DURATION_TO_DAYS.get(max_duration, 30)

    now = datetime.now(timezone.utc)
    max_lookback_start = now - timedelta(days=max_lookback_days)

    if earliest_existing_date:
        if isinstance(earliest_existing_date, str):
            try:
                chain_from = datetime.fromisoformat(
                    earliest_existing_date.replace("Z", "+00:00")
                )
            except ValueError:
                try:
                    chain_from = datetime.strptime(
                        earliest_existing_date[:10], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    chain_from = now
        elif isinstance(earliest_existing_date, datetime):
            chain_from = earliest_existing_date
        else:
            chain_from = now

        if chain_from.tzinfo is None:
            chain_from = chain_from.replace(tzinfo=timezone.utc)
    else:
        chain_from = now

    if chain_from <= max_lookback_start:
        return []

    chains = []
    current_end = chain_from
    while current_end > max_lookback_start:
        end_date_str = current_end.strftime("%Y%m%d %H:%M:%S")
        chains.append({"duration": max_duration, "end_date": end_date_str})
        current_end -= timedelta(days=step_days)

    return chains


def main():
    parser = argparse.ArgumentParser(description="Build max lookback chain requests into MongoDB queue")
    parser.add_argument("--bar-sizes", type=str, default="5 mins,15 mins,30 mins,1 hour,1 day,1 week",
                        help="Comma-separated bar sizes (default: all except 1 min)")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated specific symbols (default: all qualifying)")
    parser.add_argument("--max-symbols", type=int, default=None,
                        help="Max number of symbols to process")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to DB, just report counts")
    parser.add_argument("--mongo-url", type=str, default=None,
                        help="MongoDB URL (default: from backend .env)")

    args = parser.parse_args()

    # Get MongoDB URL
    mongo_url = args.mongo_url
    if not mongo_url:
        env_path = os.path.join(os.path.dirname(__file__), "..", "backend", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("MONGO_URL="):
                        mongo_url = line.strip().split("=", 1)[1]
                        break
    if not mongo_url:
        mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: No MongoDB URL. Use --mongo-url or set MONGO_URL")
        sys.exit(1)

    bar_sizes_filter = set(b.strip() for b in args.bar_sizes.split(",") if b.strip())
    specific_symbols = None
    if args.symbols:
        specific_symbols = set(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    print(f"Connecting to MongoDB ...")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)
    db = client["tradecommand"]
    db.command("ping")
    print(f"Connected. Bar sizes: {bar_sizes_filter}")

    adv_col = db["symbol_adv_cache"]
    data_col = db["ib_historical_data"]
    queue_col = db["historical_data_requests"]

    # ── Get qualifying symbols ──
    if specific_symbols:
        symbols = list(adv_col.find(
            {"symbol": {"$in": list(specific_symbols)}, "avg_volume": {"$gte": ADV_THRESHOLDS["investment"]}},
            {"symbol": 1, "avg_volume": 1, "_id": 0}
        ).sort("avg_volume", -1))
    else:
        symbols = list(adv_col.find(
            {"avg_volume": {"$gte": ADV_THRESHOLDS["investment"]}},
            {"symbol": 1, "avg_volume": 1, "_id": 0}
        ).sort("avg_volume", -1))

    if args.max_symbols:
        symbols = symbols[:args.max_symbols]

    print(f"Found {len(symbols)} qualifying symbols")

    # ── Get earliest dates for all (symbol, bar_size) combos ──
    print("Querying earliest bar dates for smart chaining ...")
    t0 = time.time()
    earliest_dates = {}
    pipeline = [
        {"$group": {
            "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
            "earliest": {"$min": "$date"},
        }}
    ]
    for doc in data_col.aggregate(pipeline, allowDiskUse=True):
        _id = doc.get("_id", {})
        sym = _id.get("symbol")
        bs = _id.get("bar_size")
        if sym and bs:
            earliest_dates[(sym, bs)] = doc["earliest"]
    print(f"  Found {len(earliest_dates)} existing (symbol, bar_size) combos in {time.time()-t0:.1f}s")

    # ── Check existing pending requests to avoid duplicates ──
    print("Checking existing pending requests ...")
    existing_pending = set()
    for doc in queue_col.find(
        {"status": {"$in": ["pending", "claimed"]}, "end_date": {"$ne": ""}},
        {"symbol": 1, "bar_size": 1, "end_date": 1, "_id": 0}
    ):
        existing_pending.add((doc["symbol"], doc["bar_size"], doc.get("end_date", "")))
    print(f"  Found {len(existing_pending)} existing pending chained requests")

    # ── Build chains ──
    print("\nBuilding chains ...")
    total_chains = 0
    skipped_coverage = 0
    skipped_dedup = 0
    requests_to_insert = []
    tier_counts = {"intraday": 0, "swing": 0, "investment": 0}

    for i, sym_data in enumerate(symbols):
        symbol = sym_data["symbol"]
        avg_volume = sym_data.get("avg_volume", 0)
        tier = get_tier(avg_volume)
        if tier == "skip":
            continue

        if tier not in tier_counts:
            tier_counts[tier] = 0
        tier_counts[tier] += 1

        timeframes = TIER_TIMEFRAMES.get(tier, ["1 day"])
        timeframes = [tf for tf in timeframes if tf in bar_sizes_filter]

        for bar_size in timeframes:
            earliest = earliest_dates.get((symbol, bar_size))
            chains = generate_chains(bar_size, earliest)

            if not chains:
                skipped_coverage += 1
                continue

            for chain in chains:
                key = (symbol, bar_size, chain["end_date"])
                if key in existing_pending:
                    skipped_dedup += 1
                    continue

                request_id = f"hist_{uuid.uuid4().hex[:12]}"
                requests_to_insert.append({
                    "request_id": request_id,
                    "symbol": symbol,
                    "duration": chain["duration"],
                    "bar_size": bar_size,
                    "end_date": chain["end_date"],
                    "callback_id": None,
                    "status": "pending",
                    "data": None,
                    "error": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "claimed_at": None,
                    "completed_at": None,
                })
                total_chains += 1

        if (i + 1) % 500 == 0:
            print(f"  Processed {i+1}/{len(symbols)} symbols ... {total_chains} chains so far")

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"CHAIN BUILD SUMMARY")
    print(f"{'='*60}")
    print(f"  Symbols processed:    {len(symbols)}")
    print(f"  Tier breakdown:       {tier_counts}")
    print(f"  Bar sizes:            {bar_sizes_filter}")
    print(f"  Chains to queue:      {total_chains}")
    print(f"  Skipped (full data):  {skipped_coverage}")
    print(f"  Skipped (dedup):      {skipped_dedup}")

    est_seconds = total_chains * 3.5
    est_hours = est_seconds / 3600
    if est_hours >= 24:
        print(f"  Estimated time:       {est_hours/24:.1f} days ({est_hours:.0f} hours)")
    else:
        print(f"  Estimated time:       {est_hours:.1f} hours")

    if args.dry_run:
        print(f"\n  DRY RUN — nothing was written to the queue.")
    else:
        # Batch insert
        print(f"\n  Inserting {total_chains} requests into queue ...")
        batch_size = 5000
        inserted = 0
        for i in range(0, len(requests_to_insert), batch_size):
            batch = requests_to_insert[i:i+batch_size]
            queue_col.insert_many(batch, ordered=False)
            inserted += len(batch)
            print(f"    Inserted {inserted}/{total_chains} ...")

        print(f"\n  DONE. {total_chains} chained requests are now in the queue.")
        print(f"  Start your IB Data Pusher to begin processing.")

    print(f"{'='*60}")
    client.close()


if __name__ == "__main__":
    main()
