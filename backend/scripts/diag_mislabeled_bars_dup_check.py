#!/usr/bin/env python3
"""diag_mislabeled_bars_dup_check.py  —  READ-ONLY  (2026-06-16, v320e prep)

Verifies the v320d-flagged ~386,919 mislabeled rows (bar_size="1 day"
docs whose `date` is len > 10 → actually 1-min bars mislabeled) have
TRUE duplicates in the proper `bar_size="1 min"` collection, before we
authorize a destructive cleanup.

Samples N rows from the mislabeled set, checks for matching (symbol, date)
entries in the 1-min bar_size set, reports the match rate.
"""
import os, sys, random
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

SAMPLE = 200  # cheap

def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn: print("ERROR: env"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    col = db["ib_historical_data"]
    # Mislabeled population: bar_size="1 day" AND len(date)>10.
    mis_q = {"bar_size": "1 day",
             "$expr": {"$gt": [{"$strLenCP": {"$ifNull": ["$date", ""]}}, 10]}}
    n_mis = col.count_documents(mis_q)
    print(f"Mislabeled rows (bar_size='1 day' with len(date) > 10): {n_mis:,}")
    if n_mis == 0:
        print("Nothing to verify."); return
    sample_size = min(SAMPLE, n_mis)
    # Use $sample for uniform random sample.
    sample = list(col.aggregate([
        {"$match": mis_q},
        {"$sample": {"size": sample_size}},
        {"$project": {"_id": 0, "symbol": 1, "date": 1, "close": 1, "open": 1,
                      "high": 1, "low": 1, "volume": 1}},
    ]))
    print(f"\nSampled {len(sample)} rows for duplicate verification:\n")

    dup_match, partial, missing = 0, 0, 0
    examples_match, examples_missing = [], []
    for r in sample:
        # Look for a real 1-min bar matching (symbol, date).
        match = col.find_one(
            {"symbol": r["symbol"], "bar_size": "1 min", "date": r["date"]},
            {"_id": 0, "open": 1, "close": 1, "high": 1, "low": 1, "volume": 1},
        )
        if match is None:
            missing += 1
            if len(examples_missing) < 5:
                examples_missing.append((r["symbol"], r["date"]))
            continue
        # Strict OHLC+vol match → true duplicate.
        keys = ("open", "high", "low", "close", "volume")
        if all(match.get(k) == r.get(k) for k in keys):
            dup_match += 1
            if len(examples_match) < 3:
                examples_match.append((r["symbol"], r["date"]))
        else:
            partial += 1
    print(f"  EXACT-MATCH duplicates : {dup_match} / {len(sample)} "
          f"({dup_match/len(sample)*100:.1f}%)  ← safe-to-delete population")
    print(f"  partial (symbol+date match, OHLC differs): {partial}")
    print(f"  NO 1-min counterpart found: {missing}  ← would lose data on delete")
    if examples_match:
        print(f"\n  example matches:")
        for s, d in examples_match: print(f"    {s} {d}")
    if examples_missing:
        print(f"\n  example UNIQUE rows (DELETE WOULD LOSE THESE):")
        for s, d in examples_missing: print(f"    {s} {d}")
    print(f"\n  Verdict guidance:")
    print(f"    • dup_match ≥ 95% AND missing == 0  →  safe to bulk delete")
    print(f"    • missing > 0                       →  per-row dedupe required")
    print(f"    • partial > 0                       →  investigate OHLC drift")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
