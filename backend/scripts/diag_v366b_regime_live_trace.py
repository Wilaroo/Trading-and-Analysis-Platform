#!/usr/bin/env python3
"""
diag_v366b_regime_live_trace.py  (READ-ONLY — trace WHY live regime = high_vol ~95%).

The v366 readiness diag found a contradiction: 94.8% of shadow records are tagged
`high_vol`, but SPY *daily* vol_expansion>1.3 only fires ~16% of days. classify_current_regime()
reads SPY "1 day" bars (timeseries_service.py:3120-3135), so the live tag should match. This
script replicates that EXACT aggregation pipeline and dumps every intermediate so we see the
true root cause: dirty/duplicate/partial daily bars, a stuck regime, or genuine recent vol.

NOTHING IS WRITTEN.

Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v366b_regime_live_trace.py
"""
import sys
from datetime import datetime, timezone


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


def _atr(highs, lows, closes, period):
    """EXACT replica of classify_regime._atr (most-recent-first)."""
    n = len(closes)
    vals = []
    for i in range(min(period, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
            abs(lows[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
        )
        vals.append(tr)
    return (sum(vals) / len(vals)) if vals else 0.0


def main():
    db = _load_db()
    col = db["ib_historical_data"]

    print("\n=== v366b LIVE REGIME TRACE (SPY 1 day) ===\n")

    # ── collection health ───────────────────────────────────────────────────
    total = col.count_documents({"symbol": "SPY", "bar_size": "1 day"})
    print(f"SPY '1 day' docs total: {total}")
    recent = list(col.find({"symbol": "SPY", "bar_size": "1 day"},
                           {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1,
                            "close": 1, "volume": 1}).sort("date", -1).limit(8))
    print("\n8 most-recent raw docs (by date desc) — check type/dupes/partial today-bar:")
    for r in recent:
        d = r.get("date")
        print(f"  date={str(d)!r:<34} type={type(d).__name__:<8} "
              f"O={r.get('open')} H={r.get('high')} L={r.get('low')} C={r.get('close')} V={r.get('volume')}")

    # ── replicate the EXACT live pipeline (timeseries_service.classify_current_regime) ──
    pipeline = [
        {"$match": {"symbol": "SPY", "bar_size": "1 day"}},
        {"$addFields": {"date_key": {"$substr": [{"$toString": "$date"}, 0, 10]}}},
        {"$sort": {"date": -1}},
        {"$group": {"_id": "$date_key", "close": {"$first": "$close"},
                    "high": {"$first": "$high"}, "low": {"$first": "$low"}}},
        {"$sort": {"_id": -1}},
        {"$limit": 30},
    ]
    bars = list(col.aggregate(pipeline, allowDiskUse=True))
    print(f"\npipeline returned {len(bars)} grouped daily bars (most-recent-first):")
    for b in bars[:30]:
        print(f"  {b['_id']:<12} C={b.get('close'):<8} H={b.get('high'):<8} L={b.get('low')}")

    if len(bars) < 25:
        print("\n*** < 25 bars -> classify_current_regime returns None (NOT high_vol). ***\n")
        return

    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    a5 = _atr(highs, lows, closes, 5)
    a20 = _atr(highs, lows, closes, 20)
    ve = a5 / a20 if a20 > 0 else 1.0

    # date-key ordering sanity (are these really the 30 most-recent CALENDAR days?)
    keys = [b["_id"] for b in bars]
    ordered = keys == sorted(keys, reverse=True)
    distinct = len(set(keys)) == len(keys)

    print("\n=== classify_regime intermediates (from the pipeline bars) ===")
    print(f"  date_keys ordered desc : {ordered}   distinct: {distinct}")
    print(f"  span                   : {keys[-1]} .. {keys[0]}")
    print(f"  atr_5  = {a5:.4f}")
    print(f"  atr_20 = {a20:.4f}")
    print(f"  vol_expansion (atr5/atr20) = {ve:.4f}   -> high_vol if > 1.3  => "
          f"{'HIGH_VOL' if ve > 1.3 else 'not high_vol'}")

    # what the clean (calibration) path would say using the SAME 30 bars
    print("\n=== cross-check ===")
    print(f"  If this vol_expansion ({ve:.2f}) drives EVERY live decision, that explains the")
    print(f"  94.8% high_vol — the regime is effectively STUCK at one daily value (5-min TTL")
    print(f"  cache just re-derives the same daily number all session).")
    print(f"  ROOT-CAUSE CHECK:")
    print(f"   • If atr_5 >> atr_20 here but the readiness calib said med~1.0 -> the pipeline bars")
    print(f"     are DIRTY (partial today-bar / duplicate / mis-sorted date_key) vs the clean series.")
    print(f"   • If ve<=1.3 here -> the stored shadow 'regime' is STALE (old high-vol period) and")
    print(f"     today's value is fine -> the corpus skew is historical, will self-correct.")
    print(f"   • If ve>1.3 here AND the 30 bars look clean+recent -> SPY genuinely IS in expansion")
    print(f"     now; the skew is real-but-correct and the fix is multi-TF + time, not threshold.\n")


if __name__ == "__main__":
    main()
