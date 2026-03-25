"""
Recalculate symbol_adv_cache using actual IB historical daily bar data.

This script:
1. Queries ib_historical_data for REAL daily bars (date length == 10, not mistagged intraday)
2. Calculates 20-day average volume per symbol
3. Replaces the entire symbol_adv_cache collection with accurate data
4. Reports counts at various ADV thresholds

Can be run standalone or imported as a function.
"""
import os
import sys
import pymongo
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


def recalculate_adv_cache(db, lookback_days: int = 20, min_bars: int = 10, verbose: bool = True):
    """
    Recalculate ADV cache from ib_historical_data daily bars.
    
    Args:
        db: PyMongo database instance
        lookback_days: Number of recent trading days to average (default 20)
        min_bars: Minimum daily bars required to include a symbol (default 10)
        verbose: Print progress
    
    Returns:
        dict with stats about the operation
    """
    if verbose:
        print(f"Starting ADV cache recalculation (lookback={lookback_days}, min_bars={min_bars})...")
    
    # Step 1: Aggregate real daily bars per symbol
    # Real daily bars have date strings of length 10 ("YYYY-MM-DD")
    # Mistagged intraday bars have length 25 ("YYYY-MM-DDTHH:MM:SS-TZ:TZ")
    pipeline = [
        {"$match": {"bar_size": "1 day"}},
        # Filter to only real daily bars (date string length == 10)
        {"$addFields": {"_dateLen": {"$strLenCP": {"$toString": "$date"}}}},
        {"$match": {"_dateLen": 10}},
        # Sort descending so $push gives us most recent first
        {"$sort": {"date": -1}},
        # Group by symbol, collect volumes (most recent first)
        {"$group": {
            "_id": "$symbol",
            "volumes": {"$push": "$volume"},
            "dates": {"$push": "$date"},
            "total_bars": {"$sum": 1}
        }},
        # Only symbols with enough data
        {"$match": {"total_bars": {"$gte": min_bars}}}
    ]
    
    if verbose:
        print("Running aggregation pipeline (this may take a minute)...")
    
    results = list(db.ib_historical_data.aggregate(pipeline, allowDiskUse=True))
    
    if verbose:
        print(f"Found {len(results)} symbols with >= {min_bars} real daily bars")
    
    # Step 2: Calculate ADV for each symbol and build cache documents
    now_iso = datetime.now(timezone.utc).isoformat()
    cache_docs = []
    
    for r in results:
        symbol = r["_id"]
        # Take only the last N days of volume
        recent_vols = r["volumes"][:lookback_days]
        recent_dates = r["dates"][:lookback_days]
        
        # Filter out None/zero volumes
        valid_vols = [v for v in recent_vols if v and v > 0]
        
        if not valid_vols:
            continue
        
        avg_volume = sum(valid_vols) / len(valid_vols)
        
        cache_docs.append({
            "symbol": symbol,
            "avg_volume": round(avg_volume, 2),
            "sample_days": lookback_days,
            "days_used": len(valid_vols),
            "bar_count": r["total_bars"],
            "latest_date": recent_dates[0] if recent_dates else None,
            "updated_at": now_iso,
            "source": "ib_historical_recalc"
        })
    
    if verbose:
        print(f"Calculated ADV for {len(cache_docs)} symbols")
    
    # Step 3: Replace the collection
    if verbose:
        old_count = db.symbol_adv_cache.count_documents({})
        print(f"Replacing symbol_adv_cache (old: {old_count} entries, new: {len(cache_docs)} entries)")
    
    # Drop old data and bulk insert new
    db.symbol_adv_cache.delete_many({})
    
    if cache_docs:
        # Insert in batches for safety
        batch_size = 1000
        for i in range(0, len(cache_docs), batch_size):
            batch = cache_docs[i:i + batch_size]
            db.symbol_adv_cache.insert_many(batch)
            if verbose:
                print(f"  Inserted batch {i // batch_size + 1} ({len(batch)} docs)")
    
    # Ensure indexes (skip if already exist)
    existing = db.symbol_adv_cache.index_information()
    if not any("symbol" in str(idx.get("key", "")) for idx in existing.values()):
        db.symbol_adv_cache.create_index("symbol", unique=True)
    if not any("avg_volume" in str(idx.get("key", "")) for idx in existing.values()):
        db.symbol_adv_cache.create_index("avg_volume")
    
    # Step 4: Report stats
    thresholds = {
        "50k+": 50_000,
        "100k+": 100_000, 
        "500k+": 500_000,
        "1M+": 1_000_000,
        "5M+": 5_000_000
    }
    
    threshold_counts = {}
    for label, thresh in thresholds.items():
        count = sum(1 for d in cache_docs if d["avg_volume"] >= thresh)
        threshold_counts[label] = count
    
    stats = {
        "total_symbols": len(cache_docs),
        "thresholds": threshold_counts,
        "lookback_days": lookback_days,
        "min_bars": min_bars
    }
    
    if verbose:
        print("\n=== ADV Cache Recalculation Complete ===")
        print(f"Total symbols cached: {len(cache_docs)}")
        print("Threshold breakdown:")
        for label, count in threshold_counts.items():
            print(f"  ADV >= {label}: {count} symbols")
        
        # Spot check known symbols
        print("\nSpot check (top liquid):")
        for sym in ["AAPL", "TSLA", "NVDA", "MSFT", "SPY", "AMD", "META"]:
            doc = next((d for d in cache_docs if d["symbol"] == sym), None)
            if doc:
                print(f"  {sym}: ADV = {int(doc['avg_volume']):,}")
            else:
                print(f"  {sym}: NOT FOUND")
    
    return stats


if __name__ == "__main__":
    client = pymongo.MongoClient(os.environ.get("MONGO_URL"))
    db = client["tradecommand"]
    
    stats = recalculate_adv_cache(db, lookback_days=20, min_bars=10, verbose=True)
    
    print(f"\nDone. Stats: {stats}")
