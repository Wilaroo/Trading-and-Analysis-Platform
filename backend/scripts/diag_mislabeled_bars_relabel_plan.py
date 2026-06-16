#!/usr/bin/env python3
"""diag_mislabeled_bars_relabel_plan.py  —  READ-ONLY  (2026-06-16, v320e-relabel prep)

V1 diag showed bulk-delete would lose 64.5% of 386,919 rows (~250k unique
1-min bars wearing a `bar_size="1 day"` label). Cleanup must be RE-LABEL
not delete. This diag scopes the relabel by stratifying the population
into the three treatment buckets WITHOUT touching anything.

Output:
  Section 1 — total population count + projected bucket sizes (extrapolated
              from a 1000-row sample).
  Section 2 — population by source (which symbols / which date ranges).
  Section 3 — collision check: would a relabel UPDATE create new dup KVs
              against existing 1-min docs? (Need to know before patcher.)
"""
import os, sys, random
from collections import Counter, defaultdict
from datetime import datetime
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

SAMPLE_SIZE = 1000   # gives ±1.5% on 386k pop
SHOW_TOP_SYMBOLS = 25


def hr(t): print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn: print("ERROR: env"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    col = db["ib_historical_data"]

    mis_q = {"bar_size": "1 day",
             "$expr": {"$gt": [{"$strLenCP": {"$ifNull": ["$date", ""]}}, 10]}}
    n_mis = col.count_documents(mis_q)
    print(f"Total mislabeled rows: {n_mis:,}")
    if n_mis == 0:
        print("Nothing to do."); return

    sample = list(col.aggregate([
        {"$match": mis_q},
        {"$sample": {"size": SAMPLE_SIZE}},
        {"$project": {"_id": 0, "symbol": 1, "date": 1,
                      "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}},
    ]))
    n_sample = len(sample)
    print(f"Sampled {n_sample} rows for stratification\n")

    bucket_exact, bucket_partial, bucket_unique = [], [], []
    keys_ohlcv = ("open", "high", "low", "close", "volume")
    for r in sample:
        match = col.find_one(
            {"symbol": r["symbol"], "bar_size": "1 min", "date": r["date"]},
            {"_id": 0, **{k: 1 for k in keys_ohlcv}},
        )
        if match is None:
            bucket_unique.append(r)
        elif all(match.get(k) == r.get(k) for k in keys_ohlcv):
            bucket_exact.append(r)
        else:
            bucket_partial.append((r, match))

    hr("Section 1 — projected treatment buckets")
    for name, bucket in [
        ("EXACT-MATCH DUPLICATE (safe DELETE)", bucket_exact),
        ("UNIQUE row (RELABEL to '1 min')", bucket_unique),
        ("PARTIAL OHLCV match (INVESTIGATE)", bucket_partial),
    ]:
        n = len(bucket)
        pct = n / n_sample * 100
        proj = int(n_mis * pct / 100)
        print(f"  {name:>40}: {n:>4}/{n_sample}  ({pct:5.1f}%) "
              f"→ projected {proj:>7,} rows")
    print(f"\n  ± projection error at 95% CI ≈ "
          f"±{int(n_mis * 1.96 * 0.5 / (n_sample ** 0.5)):,} rows")

    hr("Section 2 — population breakdown by symbol (top 25)")
    pipeline = [
        {"$match": mis_q},
        {"$group": {"_id": "$symbol", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": SHOW_TOP_SYMBOLS},
    ]
    print(f"  {'symbol':>10} {'rows':>10}")
    total_top = 0
    for d in col.aggregate(pipeline):
        sym = d["_id"] or "?"
        print(f"  {sym:>10} {d['n']:>10,}")
        total_top += d["n"]
    print(f"\n  top-{SHOW_TOP_SYMBOLS} accounts for {total_top:,} "
          f"({total_top / n_mis * 100:.1f}%) of mislabeled rows")

    hr("Section 3 — partial-match OHLCV drift examples")
    for r, m in bucket_partial[:5]:
        diffs = {k: (r.get(k), m.get(k)) for k in keys_ohlcv
                 if r.get(k) != m.get(k)}
        print(f"  {r['symbol']:>8}  {r['date'][:19]}")
        for k, (rv, mv) in diffs.items():
            print(f"      {k}: mislabeled={rv}  vs  1min_existing={mv}")
    if not bucket_partial:
        print("  no partial matches in this sample")

    hr("RELABEL PLAN (proposed for v320e-cleanup patcher)")
    print("  Step 1: For each row in `ib_historical_data` matching mis_q,")
    print("          probe (symbol, date) in `bar_size='1 min'`.")
    print("  Step 2: If exact OHLCV match → DELETE (the 'bar_size=1 day' row).")
    print("  Step 3: If no match → UPDATE bar_size = '1 min' in place.")
    print("  Step 4: If partial match → flag for manual review (write to a")
    print("          new `ib_historical_data_partial_review` collection,")
    print("          DO NOT auto-resolve).")
    print("  Safety: process in batches of 1,000; --check / --apply / --rollback.")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
