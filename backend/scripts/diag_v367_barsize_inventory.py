#!/usr/bin/env python3
"""diag_v367_barsize_inventory.py (READ-ONLY) — what bar_sizes exist in ib_historical_data.

Verifies whether the v367 multi-TF shadow loop can actually log 1min/15min: it only emits a
record for a bar_size when >=50 bars exist for the symbol. If 1min/15min aren't collected,
multi-TF silently produces nothing and we must adjust the _shadow_tfs list to collected sizes.
NOTHING IS WRITTEN.
Usage: .venv/bin/python backend/scripts/diag_v367_barsize_inventory.py
"""
from collections import Counter


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def main():
    db = _load_db()
    col = db["ib_historical_data"]
    print("\n=== ib_historical_data bar_size inventory (distinct sizes + doc counts) ===")
    agg = list(col.aggregate([
        {"$group": {"_id": "$bar_size", "docs": {"$sum": 1},
                    "syms": {"$addToSet": "$symbol"}}},
        {"$project": {"docs": 1, "nsyms": {"$size": "$syms"}}},
        {"$sort": {"docs": -1}},
    ], allowDiskUse=True))
    for r in agg:
        print(f"  {str(r['_id']):<12} docs={r['docs']:>9}  symbols={r['nsyms']}")

    # for a few in-play symbols, show per-tf coverage vs the >=50 threshold the loop needs
    syms = [s for s in ("SPY", "QQQ", "AAPL", "TSLA", "NVDA")]
    tfs = ["1 min", "5 mins", "15 mins", "30 mins", "1 hour", "1 day"]
    print("\n=== per-symbol coverage (>=50 needed for a shadow record) ===")
    print(f"  {'symbol':<8}" + "".join(f"{t:>10}" for t in tfs))
    for sym in syms:
        cells = []
        for t in tfs:
            n = col.count_documents({"symbol": sym, "bar_size": t}, limit=200)
            cells.append(f"{n:>10}")
        print(f"  {sym:<8}" + "".join(cells))
    print("\n  -> v367 _shadow_tfs = ['1 min','5 mins','15 mins']. Any column showing <50 for")
    print("     most symbols means that timeframe won't accrue multi-TF shadow records;")
    print("     adjust _shadow_tfs to the collected sizes (e.g. add '30 mins'/'1 hour').\n")


if __name__ == "__main__":
    main()
