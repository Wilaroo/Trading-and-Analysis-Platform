#!/usr/bin/env python3
"""
diag_v392b_sector_probe.py  —  READ-ONLY root-cause probe for Sector = 100% blind

Sector context is 'unknown' for the entire book. From code, get_sector_rankings()
pulls sector-ETF quotes via alpaca_service (DEAD on the ib-direct DGX) → empty
rankings → get_stock_sector_context() returns None. The v254-style fix is to
rank the sector ETFs from ib_historical_data daily bars and map symbol→sector
from the universe-wide symbol_adv_cache. THIS PROBE confirms that data exists.

NO WRITES. NO IB CONNECTION. Run from repo root:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v392b_sector_probe.py
"""
import os
import sys
from collections import Counter

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLB"]


def main():
    if not MONGO_URL:
        print("MONGO_URL not set."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]

    print("=" * 64)
    print("SECTOR ROOT-CAUSE PROBE  (v392b, READ-ONLY)")
    print("=" * 64)
    print(f"DB: {DB_NAME}\n")

    # 1) IB daily bars for the sector ETFs (the v254-style ranking source)
    print("1) ib_historical_data daily bars for sector ETFs:")
    hist = db["ib_historical_data"]
    etf_ok = 0
    for etf in SECTOR_ETFS:
        n = hist.count_documents({"symbol": etf, "bar_size": "1 day"})
        latest = None
        if n:
            d = hist.find_one({"symbol": etf, "bar_size": "1 day"},
                              {"_id": 0, "date": 1}, sort=[("date", -1)])
            latest = d.get("date") if d else None
            etf_ok += 1
        print(f"   {etf}: {n:>5} bars   latest={latest}")
    print(f"   => {etf_ok}/{len(SECTOR_ETFS)} ETFs have daily bars\n")

    # 2) Universe sector tags (symbol_adv_cache.sector) — symbol→sector source
    print("2) symbol_adv_cache sector tags (symbol→sector map for the universe):")
    adv = db["symbol_adv_cache"]
    total = adv.count_documents({})
    tagged = adv.count_documents({"sector": {"$exists": True, "$nin": [None, "", "unknown", "Unknown"]}})
    print(f"   total symbols: {total}   with a sector tag: {tagged}"
          + (f"  ({100.0*tagged/total:.0f}%)" if total else ""))
    sample = Counter()
    for d in adv.find({"sector": {"$exists": True, "$ne": None}}, {"_id": 0, "sector": 1}).limit(5000):
        s = d.get("sector")
        if s:
            sample[str(s)] += 1
    if sample:
        print("   distinct sector values (sample):")
        for s, c in sample.most_common(20):
            print(f"      {s:<28} n={c}")
    else:
        print("   (no sector tags found)")
    print()

    # 3) Cross-check: do recent alert symbols have a sector tag available?
    print("3) coverage of recent alert symbols by symbol_adv_cache sector tag:")
    syms = db["live_alerts"].distinct("symbol")
    covered = 0
    for s in syms:
        if adv.count_documents({"symbol": s, "sector": {"$nin": [None, "", "unknown", "Unknown"]}}, limit=1):
            covered += 1
    print(f"   distinct alert symbols: {len(syms)}   with sector tag: {covered}"
          + (f"  ({100.0*covered/len(syms):.0f}%)" if syms else ""))

    # Verdict
    print("\n--- VERDICT ---")
    bars_ok = etf_ok >= 8
    tags_ok = (total and tagged / total >= 0.5)
    if bars_ok and tags_ok:
        print("FIXABLE via IB bars: sector ETFs have daily bars AND the universe is")
        print("sector-tagged. Recommend v254-style fix: rank ETFs from ib_historical_data")
        print("daily 1d %, map symbol→sector from symbol_adv_cache. No alpaca dependency.")
    else:
        if not bars_ok:
            print("BLOCKER: sector ETFs lack daily bars in ib_historical_data — would need")
            print("to backfill the 10 ETFs first (same collector as index bars).")
        if not tags_ok:
            print("BLOCKER: symbol_adv_cache sector coverage is thin — would need to run")
            print("sector_tag_service over the universe first.")
    print("\nRead-only — nothing was modified.")


if __name__ == "__main__":
    main()
