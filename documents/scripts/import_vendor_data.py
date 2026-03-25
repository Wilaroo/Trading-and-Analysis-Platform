"""
Vendor OHLCV Data Importer
==========================
Imports ndjson/CSV 1-min OHLCV data from a third-party vendor into MongoDB Atlas.

Run this on your LOCAL machine (same as the IB Data Pusher).

Usage:
    python import_vendor_data.py --file /path/to/data.ndjson
    python import_vendor_data.py --file /path/to/data.csv --format csv
    python import_vendor_data.py --file /path/to/data.ndjson --min-adv 500000

Features:
- Streams file line-by-line (constant ~50MB memory regardless of file size)
- Filters to qualifying symbols only (queries ADV cache from Atlas)
- Skips bars already in the database (dedup by date range)
- Bulk writes in batches of 5000 for performance
- Progress tracking with ETA
- Resumable: use --resume to skip already-imported symbols

Required:
    pip install pymongo dnspython
"""

import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient, UpdateOne
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("VendorImport")

# ─── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_MONGO_URL = os.environ.get(
    "MONGO_URL",
    ""  # Set via --mongo-url or MONGO_URL env var
)
DEFAULT_DB_NAME = os.environ.get("DB_NAME", "tradecommand")
DEFAULT_COLLECTION = "ib_historical_data"
DEFAULT_ADV_COLLECTION = "symbol_adv_cache"
DEFAULT_BATCH_SIZE = 5000
DEFAULT_MIN_ADV = 500_000  # Intraday tier — only 1-min data for liquid symbols
DEFAULT_BAR_SIZE = "1 min"
DEFAULT_SKIP_DAYS = 7  # Skip bars within the last N days (already have from IB)


# ─── Field Mapping ────────────────────────────────────────────────────────────

def map_vendor_row(row: dict, import_ts: str) -> dict:
    """
    Map vendor ndjson/csv fields to our ib_historical_data schema.

    Vendor fields:  ticker, open, high, low, close, total_volume, candle_volume,
                    start_time, end_time
    Our fields:     symbol, bar_size, date, open, high, low, close, volume,
                    collected_at, source
    """
    symbol = (row.get("ticker") or row.get("symbol") or "").upper().strip()
    if not symbol:
        return None

    # Use candle_volume (per-bar) if available, else total_volume
    volume = row.get("candle_volume") or row.get("total_volume") or row.get("volume") or 0
    try:
        volume = int(float(volume))
    except (ValueError, TypeError):
        volume = 0

    # Date: prefer start_time, fall back to date/timestamp
    date_str = row.get("start_time") or row.get("date") or row.get("timestamp") or ""
    if not date_str:
        return None

    try:
        o = float(row.get("open", 0))
        h = float(row.get("high", 0))
        l = float(row.get("low", 0))
        c = float(row.get("close", 0))
    except (ValueError, TypeError):
        return None

    return {
        "symbol": symbol,
        "bar_size": DEFAULT_BAR_SIZE,
        "date": str(date_str),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": volume,
        "collected_at": import_ts,
        "source": "vendor_import",
    }


# ─── Core Import Logic ───────────────────────────────────────────────────────

def load_qualifying_symbols(db, min_adv: int) -> set:
    """Load qualifying symbols from ADV cache."""
    adv_col = db[DEFAULT_ADV_COLLECTION]
    count = adv_col.count_documents({"avg_volume": {"$gte": min_adv}})
    logger.info(f"Loading qualifying symbols with ADV >= {min_adv:,} ...")
    symbols = set()
    for doc in adv_col.find({"avg_volume": {"$gte": min_adv}}, {"symbol": 1, "_id": 0}):
        s = doc.get("symbol", "").upper()
        if s:
            symbols.add(s)
    logger.info(f"Loaded {len(symbols)} qualifying symbols (from {count} in cache)")
    return symbols


def load_already_imported_symbols(db, bar_size: str) -> set:
    """Get symbols that already have substantial vendor-imported data."""
    col = db[DEFAULT_COLLECTION]
    pipeline = [
        {"$match": {"bar_size": bar_size, "source": "vendor_import"}},
        {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": 1000}}},  # At least 1000 bars imported
    ]
    already = set()
    for doc in col.aggregate(pipeline, allowDiskUse=True):
        already.add(doc["_id"])
    return already


def get_existing_date_range(db, bar_size: str) -> dict:
    """
    Get earliest existing bar date per symbol to avoid re-importing overlapping data.
    Returns {symbol: earliest_date_str}
    """
    col = db[DEFAULT_COLLECTION]
    pipeline = [
        {"$match": {"bar_size": bar_size}},
        {"$group": {"_id": "$symbol", "latest": {"$max": "$date"}}},
    ]
    result = {}
    for doc in col.aggregate(pipeline, allowDiskUse=True):
        result[doc["_id"]] = doc["latest"]
    return result


def should_skip_bar(date_str: str, skip_after: dict, symbol: str) -> bool:
    """
    Skip a bar if we already have data at or after this date for this symbol.
    This avoids re-importing the last week of data we got from IB.
    """
    cutoff = skip_after.get(symbol)
    if not cutoff:
        return False
    # Simple string comparison works for ISO dates
    try:
        return str(date_str)[:19] >= str(cutoff)[:19]
    except Exception:
        return False


def run_import(
    file_path: str,
    mongo_url: str,
    db_name: str,
    min_adv: int,
    batch_size: int,
    file_format: str,
    skip_days: int,
    resume: bool,
    dry_run: bool,
    specific_symbols: list = None,
):
    """Main import pipeline."""

    # ── Connect to Atlas ──
    logger.info(f"Connecting to MongoDB Atlas ...")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=10000)
    db = client[db_name]

    # Quick connectivity check
    try:
        db.command("ping")
        logger.info(f"Connected to database: {db_name}")
    except Exception as e:
        logger.error(f"Cannot connect to MongoDB: {e}")
        sys.exit(1)

    col = db[DEFAULT_COLLECTION]

    # ── Load qualifying symbols ──
    if specific_symbols:
        qualifying = set(s.upper() for s in specific_symbols)
        logger.info(f"Using {len(qualifying)} specific symbols")
    else:
        qualifying = load_qualifying_symbols(db, min_adv)

    if not qualifying:
        logger.error("No qualifying symbols found. Is the ADV cache populated?")
        sys.exit(1)

    # ── Resume support ──
    already_imported = set()
    if resume:
        already_imported = load_already_imported_symbols(db, DEFAULT_BAR_SIZE)
        if already_imported:
            logger.info(f"Resume mode: skipping {len(already_imported)} already-imported symbols")

    # ── Load existing date ranges to avoid overlap ──
    logger.info("Loading existing data dates for dedup ...")
    existing_latest = get_existing_date_range(db, DEFAULT_BAR_SIZE)
    logger.info(f"Found existing data for {len(existing_latest)} symbols")

    # ── Compute skip-after cutoff ──
    # If skip_days > 0, skip any bar whose date is within the last N days
    now = datetime.now(timezone.utc)
    skip_cutoff_date = (now - timedelta(days=skip_days)).strftime("%Y-%m-%dT00:00:00")
    logger.info(f"Skipping bars after {skip_cutoff_date} (last {skip_days} days — already have from IB)")

    # ── Open file and stream ──
    file_size = os.path.getsize(file_path)
    logger.info(f"Opening {file_path} ({file_size / 1e9:.2f} GB)")

    import_ts = now.isoformat()
    batch = []
    stats = {
        "lines_read": 0,
        "filtered_out": 0,
        "skipped_overlap": 0,
        "skipped_resume": 0,
        "skipped_bad": 0,
        "written": 0,
        "batches": 0,
    }
    start_time = time.time()
    last_report = time.time()

    def flush_batch():
        if not batch or dry_run:
            if dry_run and batch:
                stats["written"] += len(batch)
            batch.clear()
            return
        ops = []
        for doc in batch:
            ops.append(UpdateOne(
                {"symbol": doc["symbol"], "bar_size": doc["bar_size"], "date": doc["date"]},
                {"$set": doc},
                upsert=True,
            ))
        try:
            result = col.bulk_write(ops, ordered=False)
            stats["written"] += result.upserted_count + result.modified_count
        except Exception as e:
            # Bulk write errors often contain partial successes
            if hasattr(e, 'details'):
                inserted = e.details.get('nUpserted', 0) + e.details.get('nModified', 0)
                stats["written"] += inserted
            logger.warning(f"Bulk write partial error: {e}")
        stats["batches"] += 1
        batch.clear()

    def report_progress():
        elapsed = time.time() - start_time
        rate = stats["lines_read"] / elapsed if elapsed > 0 else 0
        written_rate = stats["written"] / elapsed if elapsed > 0 else 0

        # Estimate remaining based on file position
        pct = (bytes_read / file_size * 100) if file_size > 0 else 0
        if pct > 0:
            eta_seconds = elapsed / (pct / 100) - elapsed
            eta_str = f"{eta_seconds/60:.0f}m" if eta_seconds < 3600 else f"{eta_seconds/3600:.1f}h"
        else:
            eta_str = "?"

        logger.info(
            f"Progress: {stats['lines_read']:,} lines | "
            f"{stats['written']:,} written | "
            f"{stats['filtered_out']:,} filtered | "
            f"{stats['skipped_overlap']:,} overlap | "
            f"{rate:,.0f} lines/s | {written_rate:,.0f} writes/s | "
            f"{pct:.1f}% | ETA: {eta_str}"
        )

    bytes_read = 0

    with open(file_path, "r", encoding="utf-8") as f:
        if file_format == "csv":
            reader = csv.DictReader(f)
            for row in reader:
                stats["lines_read"] += 1
                bytes_read = f.tell()

                mapped = map_vendor_row(row, import_ts)
                if not mapped:
                    stats["skipped_bad"] += 1
                    continue

                symbol = mapped["symbol"]
                if symbol not in qualifying:
                    stats["filtered_out"] += 1
                    continue
                if resume and symbol in already_imported:
                    stats["skipped_resume"] += 1
                    continue

                # Skip overlap (bars we already have from IB)
                bar_date = mapped["date"]
                if bar_date[:19] >= skip_cutoff_date[:19]:
                    stats["skipped_overlap"] += 1
                    continue
                # Also skip if this specific bar overlaps existing data
                if should_skip_bar(bar_date, existing_latest, symbol):
                    stats["skipped_overlap"] += 1
                    continue

                batch.append(mapped)
                if len(batch) >= batch_size:
                    flush_batch()

                if time.time() - last_report >= 10:
                    report_progress()
                    last_report = time.time()
        else:
            # ndjson: one JSON object per line
            for line in f:
                stats["lines_read"] += 1
                bytes_read = f.tell()

                line = line.strip()
                if not line:
                    continue

                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    stats["skipped_bad"] += 1
                    continue

                mapped = map_vendor_row(row, import_ts)
                if not mapped:
                    stats["skipped_bad"] += 1
                    continue

                symbol = mapped["symbol"]
                if symbol not in qualifying:
                    stats["filtered_out"] += 1
                    continue
                if resume and symbol in already_imported:
                    stats["skipped_resume"] += 1
                    continue

                # Skip overlap
                bar_date = mapped["date"]
                if bar_date[:19] >= skip_cutoff_date[:19]:
                    stats["skipped_overlap"] += 1
                    continue
                if should_skip_bar(bar_date, existing_latest, symbol):
                    stats["skipped_overlap"] += 1
                    continue

                batch.append(mapped)
                if len(batch) >= batch_size:
                    flush_batch()

                if time.time() - last_report >= 10:
                    report_progress()
                    last_report = time.time()

    # Final flush
    flush_batch()

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("IMPORT COMPLETE")
    logger.info(f"  Time:            {elapsed/60:.1f} minutes")
    logger.info(f"  Lines read:      {stats['lines_read']:,}")
    logger.info(f"  Written to DB:   {stats['written']:,}")
    logger.info(f"  Filtered (ADV):  {stats['filtered_out']:,}")
    logger.info(f"  Skipped overlap: {stats['skipped_overlap']:,}")
    logger.info(f"  Skipped resume:  {stats['skipped_resume']:,}")
    logger.info(f"  Bad/malformed:   {stats['skipped_bad']:,}")
    logger.info(f"  Batches:         {stats['batches']:,}")
    logger.info("=" * 60)

    client.close()
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Import vendor OHLCV data into MongoDB Atlas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Import ndjson with default settings (intraday symbols only)
  python import_vendor_data.py --file data.ndjson --mongo-url "mongodb+srv://..."

  # Import CSV, all symbols with ADV >= 100K
  python import_vendor_data.py --file data.csv --format csv --min-adv 100000

  # Dry run (no writes, just see what would happen)
  python import_vendor_data.py --file data.ndjson --dry-run

  # Resume interrupted import
  python import_vendor_data.py --file data.ndjson --resume

  # Import only specific symbols
  python import_vendor_data.py --file data.ndjson --symbols AAPL,MSFT,TSLA
        """
    )
    parser.add_argument("--file", required=True, help="Path to ndjson or csv file")
    parser.add_argument("--format", choices=["ndjson", "csv"], default="ndjson",
                        help="File format (default: ndjson)")
    parser.add_argument("--mongo-url", default=DEFAULT_MONGO_URL,
                        help="MongoDB connection string (or set MONGO_URL env var)")
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME,
                        help=f"Database name (default: {DEFAULT_DB_NAME})")
    parser.add_argument("--min-adv", type=int, default=DEFAULT_MIN_ADV,
                        help=f"Minimum ADV to qualify (default: {DEFAULT_MIN_ADV:,})")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Bulk write batch size (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--skip-days", type=int, default=DEFAULT_SKIP_DAYS,
                        help=f"Skip bars within the last N days (default: {DEFAULT_SKIP_DAYS})")
    parser.add_argument("--resume", action="store_true",
                        help="Skip symbols that already have vendor data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to DB, just report what would happen")
    parser.add_argument("--symbols", type=str, default=None,
                        help="Comma-separated list of specific symbols to import")

    args = parser.parse_args()

    if not args.mongo_url:
        logger.error("No MongoDB URL provided. Use --mongo-url or set MONGO_URL env var.")
        sys.exit(1)

    if not os.path.exists(args.file):
        logger.error(f"File not found: {args.file}")
        sys.exit(1)

    specific_symbols = None
    if args.symbols:
        specific_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    run_import(
        file_path=args.file,
        mongo_url=args.mongo_url,
        db_name=args.db_name,
        min_adv=args.min_adv,
        batch_size=args.batch_size,
        file_format=args.format,
        skip_days=args.skip_days,
        resume=args.resume,
        dry_run=args.dry_run,
        specific_symbols=specific_symbols,
    )


if __name__ == "__main__":
    main()
