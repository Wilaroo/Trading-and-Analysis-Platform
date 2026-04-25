#!/usr/bin/env python3
"""
verify_bar_counts.py — Direct Mongo audit of ib_historical_data.

Bypasses the inventory-summary endpoint (which is a cache of the last
`build-inventory` run) and counts what's *actually* in the collection
right now.

Run on the DGX Spark host (or anywhere with MONGO_URL pointed at the
right Mongo):

    python3 scripts/verify_bar_counts.py

Output: real bar count per timeframe, per tier, plus a comparison
against the inventory-summary endpoint so any drift is obvious.
"""
from __future__ import annotations

import os
import sys
import time
from collections import defaultdict

try:
    from dotenv import load_dotenv
    load_dotenv("backend/.env")
except ImportError:
    pass

try:
    from pymongo import MongoClient
except ImportError:
    print("ERROR: pymongo not installed. Run: pip install pymongo python-dotenv", file=sys.stderr)
    sys.exit(2)

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or os.environ.get("MONGO_DB") or "sentcom_db"

print(f"=== verify_bar_counts.py — connecting to {MONGO_URL} / {DB_NAME} ===\n")

t0 = time.time()
client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = client[DB_NAME]

# 1) Top-line counts
hist = db["ib_historical_data"]
print("--- ib_historical_data (the live time-series collection) ---")
print(f"  estimatedDocumentCount(): {hist.estimated_document_count():>15,}")
print("  countDocuments({})    :  taking exact count, may be slow ...")
exact = hist.count_documents({})
print(f"  countDocuments({{}})    : {exact:>15,}")

# 2) Per-bar-size breakdown using the existing index
print("\n--- bars per bar_size (using $group, hinted to (symbol,bar_size,date)) ---")
try:
    pipeline = [{"$group": {"_id": "$bar_size", "bars": {"$sum": 1}, "symbols": {"$addToSet": "$symbol"}}}]
    rows = list(hist.aggregate(
        pipeline,
        allowDiskUse=True,
        hint="symbol_1_bar_size_1_date_1",
        maxTimeMS=120_000,
    ))
except Exception as e:
    print(f"  hinted aggregation failed ({e}); retrying without hint ...")
    rows = list(hist.aggregate(pipeline, allowDiskUse=True, maxTimeMS=180_000))

rows.sort(key=lambda r: -r.get("bars", 0))
total_bars = 0
print(f"  {'bar_size':<12} {'bars':>15} {'unique_symbols':>16}")
for r in rows:
    bs = r["_id"] or "(null)"
    bars = r.get("bars", 0)
    syms = len(r.get("symbols", []))
    total_bars += bars
    print(f"  {bs:<12} {bars:>15,} {syms:>16,}")
print(f"  {'-'*44}")
print(f"  {'TOTAL':<12} {total_bars:>15,}")

# 3) Per-tier breakdown using symbol_adv_cache
print("\n--- bars per tier (joining symbol_adv_cache) ---")
adv = db["symbol_adv_cache"]
adv_total = adv.count_documents({})
print(f"  symbol_adv_cache total: {adv_total:,}")

# Crude tiering identical to the rest of the app
def tier_for(av: int | float | None) -> str:
    if not av or av < 50_000:
        return "skip"
    if av < 100_000:
        return "investment"
    if av < 500_000:
        return "swing"
    return "intraday"

tier_symbols = defaultdict(set)
for d in adv.find({}, {"_id": 0, "symbol": 1, "avg_volume": 1}):
    tier_symbols[tier_for(d.get("avg_volume"))].add(d.get("symbol"))

print(f"  {'tier':<12} {'symbols':>10}")
for t in ("intraday", "swing", "investment", "skip"):
    print(f"  {t:<12} {len(tier_symbols[t]):>10,}")

# 4) Critical symbol latest-bar sanity
print("\n--- latest bar per (critical symbol, timeframe) ---")
CRITICAL = ["SPY", "QQQ", "DIA", "IWM", "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN"]
TFS = ["1 min", "5 mins", "15 mins", "1 hour", "1 day"]
print(f"  {'symbol':<7} " + "  ".join(f"{tf:>20}" for tf in TFS))
for s in CRITICAL:
    cells = []
    for tf in TFS:
        doc = hist.find_one({"symbol": s, "bar_size": tf}, {"_id": 0, "date": 1}, sort=[("date", -1)])
        cells.append(str(doc.get("date") or "—")[:19] if doc else "MISSING")
    print(f"  {s:<7} " + "  ".join(f"{c:>20}" for c in cells))

# 5) Compare against the inventory-summary cache (if endpoint reachable)
import urllib.request
import json
print("\n--- inventory-summary endpoint (cached) vs reality ---")
try:
    with urllib.request.urlopen("http://localhost:8001/api/ib-collector/inventory/summary", timeout=10) as r:
        summary = json.load(r)
    cached = sum(b.get("total_bars", 0) for b in summary.get("by_bar_size", []))
    print(f"  cached total_bars (inventory-summary): {cached:,}")
    print(f"  live total_bars  (ib_historical_data): {total_bars:,}")
    diff = total_bars - cached
    if abs(diff) > total_bars * 0.05:
        print(f"  >>>> DRIFT: cached inventory is OFF by {diff:+,} bars (>5%).")
        print( "       Rebuild it via: curl -X POST http://localhost:8001/api/ib-collector/build-inventory")
    else:
        print( "  in sync (drift <5%).")
except Exception as e:
    print(f"  (could not reach endpoint: {e})")

print(f"\n=== done in {time.time() - t0:.1f}s ===")
