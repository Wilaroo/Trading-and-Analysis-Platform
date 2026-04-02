"""
Symbol Inventory Report
Run locally: python scripts/symbol_inventory.py

Shows qualifying symbol counts per ADV tier and timeframe,
factoring in min_bars requirements from BAR_SIZE_CONFIGS.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")

BAR_SIZE_CONFIGS = {
    "1 min":   {"min_bars": 200},
    "5 mins":  {"min_bars": 200},
    "15 mins": {"min_bars": 150},
    "30 mins": {"min_bars": 150},
    "1 hour":  {"min_bars": 100},
    "1 day":   {"min_bars": 100},
    "1 week":  {"min_bars": 50},
}

ADV_TIERS = [
    ("500K+",   500_000),
    ("1M+",   1_000_000),
    ("2M+",   2_000_000),
    ("5M+",   5_000_000),
    ("10M+", 10_000_000),
]


def main():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    # Get all ADV data
    adv_data = list(db["symbol_adv_cache"].find({}, {"_id": 0, "symbol": 1, "avg_volume": 1}))
    print(f"\nTotal symbols in ADV cache: {len(adv_data)}\n")

    # Build symbol -> ADV map
    adv_map = {d["symbol"]: d.get("avg_volume", 0) for d in adv_data}

    # For each bar_size, get symbol bar counts
    bar_counts = {}  # {bar_size: {symbol: count}}
    for bs, cfg in BAR_SIZE_CONFIGS.items():
        print(f"Counting bars for {bs}...", end=" ", flush=True)
        pipeline = [
            {"$match": {"bar_size": bs}},
            {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
        ]
        try:
            results = list(db["ib_historical_data"].aggregate(
                pipeline, allowDiskUse=True, maxTimeMS=300000
            ))
            bar_counts[bs] = {r["_id"]: r["count"] for r in results}
            print(f"{len(results)} symbols found")
        except Exception as e:
            print(f"TIMEOUT/ERROR: {e}")
            bar_counts[bs] = {}

    # Print header
    timeframes = list(BAR_SIZE_CONFIGS.keys())
    header = f"{'ADV Tier':<12}" + "".join(f"{tf:>10}" for tf in timeframes)
    print("\n" + "=" * len(header))
    print("QUALIFYING SYMBOLS BY ADV TIER & TIMEFRAME")
    print("(min_bars requirement per timeframe applied)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    for tier_name, min_adv in ADV_TIERS:
        tier_symbols = {s for s, v in adv_map.items() if v >= min_adv}
        row = f"{tier_name:<12}"
        for bs in timeframes:
            min_bars = BAR_SIZE_CONFIGS[bs]["min_bars"]
            counts = bar_counts.get(bs, {})
            qualifying = sum(1 for s in tier_symbols if counts.get(s, 0) >= min_bars)
            row += f"{qualifying:>10}"
        print(row)

    # Total row (all ADV)
    print("-" * len(header))
    row = f"{'ALL':<12}"
    for bs in timeframes:
        min_bars = BAR_SIZE_CONFIGS[bs]["min_bars"]
        counts = bar_counts.get(bs, {})
        qualifying = sum(1 for s, c in counts.items() if c >= min_bars)
        row += f"{qualifying:>10}"
    print(row)

    # Also show avg bars per qualifying symbol
    print("\n" + "=" * len(header))
    print("AVG BARS PER QUALIFYING SYMBOL")
    print("=" * len(header))
    row = f"{'AVG BARS':<12}"
    for bs in timeframes:
        min_bars = BAR_SIZE_CONFIGS[bs]["min_bars"]
        counts = bar_counts.get(bs, {})
        qualifying_counts = [c for c in counts.values() if c >= min_bars]
        avg = int(sum(qualifying_counts) / len(qualifying_counts)) if qualifying_counts else 0
        row += f"{avg:>10}"
    print(row)

    client.close()


if __name__ == "__main__":
    main()
