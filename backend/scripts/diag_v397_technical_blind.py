#!/usr/bin/env python3
"""
diag_v397_technical_blind.py  —  READ-ONLY: is the Levels=50 cluster a whole-snapshot
default (no live quote) or the naive S/R algorithm clustering?

get_technical_snapshot() returns None when there's no live IB pusher quote → the
WHOLE technical pillar defaults (rsi 50, rvol 1.0→volume 60, levels 50, trend
neutral). This cross-tabs persisted breakdowns to separate that from real-snapshot
levels clustering.

NO WRITES. Mongo only. Run:  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v397_technical_blind.py
"""
import os
import sys
from collections import Counter

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
EPS = 1e-3


def pct(a, b):
    return f"{100.0*a/b:.1f}%" if b else "n/a"


def main():
    if not MONGO_URL:
        print("MONGO_URL not set."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]

    cur = db["live_alerts"].find(
        {"tqs_breakdown.technical": {"$exists": True}},
        {"_id": 0, "tqs_breakdown.technical.raw_values": 1,
         "tqs_breakdown.technical.components": 1}).limit(50000)

    n = 0
    rvol_default = rsi_default = levels_50 = 0
    snap_none = 0                  # rvol==1.0 AND rsi==50 → snapshot-None signature
    levels_when_snap_none = Counter()
    levels_when_real = Counter()
    for d in cur:
        t = d.get("tqs_breakdown", {}).get("technical", {})
        raw, comp = t.get("raw_values") or {}, t.get("components") or {}
        if not raw and not comp:
            continue
        n += 1
        rvol = raw.get("rvol")
        rsi = raw.get("rsi")
        lvl = comp.get("levels")
        is_rvol_def = rvol is not None and abs(float(rvol) - 1.0) < EPS
        is_rsi_def = rsi is not None and abs(float(rsi) - 50.0) < EPS
        is_lvl50 = lvl is not None and abs(float(lvl) - 50.0) < 0.5
        rvol_default += is_rvol_def
        rsi_default += is_rsi_def
        levels_50 += is_lvl50
        if is_rvol_def and is_rsi_def:
            snap_none += 1
            if lvl is not None:
                levels_when_snap_none[round(float(lvl))] += 1
        elif lvl is not None:
            levels_when_real[round(float(lvl))] += 1

    print("=" * 64)
    print("TECHNICAL PILLAR BLIND CROSS-TAB  (v397, READ-ONLY)")
    print("=" * 64)
    print(f"alerts with technical breakdown: {n}\n")
    print(f"  RVOL == 1.00 default        : {pct(rvol_default, n)}")
    print(f"  RSI  == 50   default        : {pct(rsi_default, n)}")
    print(f"  Levels == 50                : {pct(levels_50, n)}")
    print(f"  SNAPSHOT-NONE signature     : {pct(snap_none, n)}  (rvol==1.0 AND rsi==50)")
    print(f"     -> the WHOLE technical pillar defaulted (no live quote at score time)")
    print(f"\n  Levels distribution WHEN snapshot-none ({snap_none} alerts):")
    for v, c in levels_when_snap_none.most_common(6):
        print(f"     levels={v:<4} {pct(c, snap_none)}")
    real = n - snap_none
    print(f"\n  Levels distribution WHEN real snapshot ({real} alerts):")
    for v, c in levels_when_real.most_common(8):
        print(f"     levels={v:<4} {pct(c, real)}")
    print("\n  Interpretation:")
    print("   - snapshot-none share  = the live-quote dependency gap (also hits RVOL/RSI).")
    print("   - levels=50 within real snapshots = naive 20-day min/max S/R clustering.")
    print("\nRead-only — nothing was modified.")


if __name__ == "__main__":
    main()
