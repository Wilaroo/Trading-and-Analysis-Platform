#!/usr/bin/env python3
"""
v19.34.314 — P-TARGET fill-rate balance audit (run on the DGX, NO retrain).

Proves the redesigned overnight-gap target produces a BALANCED class
distribution (vs the old ~98% fill rate) by replaying the new sampler over
real intraday bars in MongoDB. Read-only — trains nothing, writes nothing.

For each intraday timeframe it reports, side-by-side:
  OLD lens  — every intrabar gap ≥0.2%, fill checked across the FULL window
  NEW lens  — overnight OPEN gap ≥0.5% only, fill checked in the EARLY window

Usage (from backend/, env sourced):
    PYTHONPATH=. ../.venv/bin/python scripts/gap_target_audit.py
    PYTHONPATH=. ../.venv/bin/python scripts/gap_target_audit.py --symbols 150
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from pymongo import MongoClient

from services.ai_modules.gap_fill_model import (
    GAP_MODEL_CONFIGS, OVERNIGHT_GAP_MIN_PCT,
    compute_gap_fill_target, find_session_open_indices,
)

# Old design constants (for the side-by-side comparison only)
OLD_INTRABAR_GAP_MIN = 0.002
OLD_FULL_WINDOW = {"1 min": 390, "5 mins": 78, "15 mins": 26}


def _fetch_symbols(db, bar_size, limit):
    syms = db["ib_historical_data"].distinct("symbol", {"bar_size": bar_size})
    return syms[:limit]


def _load_bars(db, sym, bar_size, cap=20000):
    rows = list(db["ib_historical_data"].find(
        {"symbol": sym, "bar_size": bar_size},
        {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ).sort("date", 1).limit(cap))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=120)
    args = ap.parse_args()

    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    print("=" * 70)
    print("P-TARGET fill-rate balance audit (v19.34.314) — read-only, no retrain")
    print("=" * 70)

    for bs, cfg in GAP_MODEL_CONFIGS.items():
        early = cfg["early_window_bars"]
        full = OLD_FULL_WINDOW.get(bs, early)
        syms = _fetch_symbols(db, bs, args.symbols)

        new_y, old_y = [], []
        for sym in syms:
            bars = _load_bars(db, sym, bs)
            if len(bars) < 70 + max(early, full):
                continue
            closes = np.array([b["close"] for b in bars], dtype=np.float64)
            opens = np.array([b["open"] for b in bars], dtype=np.float64)
            highs = np.array([b["high"] for b in bars], dtype=np.float64)
            lows = np.array([b["low"] for b in bars], dtype=np.float64)
            dates = [str(b.get("date", "")) for b in bars]

            # NEW lens — overnight open gaps ≥0.5%, early window
            sess = find_session_open_indices(dates)
            for k in range(1, len(sess)):
                i = sess[k]
                if i < 1 or i + early >= len(bars):
                    continue
                pc = closes[i - 1]
                if pc <= 0:
                    continue
                gap = (opens[i] - pc) / pc
                if abs(gap) < OVERNIGHT_GAP_MIN_PCT:
                    continue
                t = compute_gap_fill_target(lows[i:i + early], highs[i:i + early],
                                            pc, 1.0 if gap > 0 else -1.0, early)
                if t is not None:
                    new_y.append(t)

            # OLD lens — every intrabar gap ≥0.2%, full window
            for i in range(1, len(bars) - full):
                pc = closes[i - 1]
                if pc <= 0:
                    continue
                g = abs(opens[i] - pc) / pc
                if g < OLD_INTRABAR_GAP_MIN:
                    continue
                t = compute_gap_fill_target(lows[i:i + full], highs[i:i + full],
                                            pc, 1.0 if opens[i] > pc else -1.0, full)
                if t is not None:
                    old_y.append(t)

        def _bal(y):
            if not y:
                return "n=0"
            a = np.array(y)
            fill = 100 * a.mean()
            return f"n={len(a):>7}  fill={fill:5.1f}%  no-fill={100-fill:5.1f}%"

        print(f"\n[{bs}]  early_window={early} bars")
        print(f"  OLD (intrabar ≥0.2%, {full}-bar window): {_bal(old_y)}")
        print(f"  NEW (overnight ≥0.5%, {early}-bar window): {_bal(new_y)}")
        if new_y:
            fill = 100 * np.mean(new_y)
            verdict = ("BALANCED ✅" if 25 <= fill <= 75
                       else "still imbalanced ⚠️ (consider tuning window/threshold)")
            print(f"  → NEW class balance: {verdict}")

    print("\nGoal: NEW fill% in ~25-75% band (vs old ~98%) → trainable, non-collapsed target.")


if __name__ == "__main__":
    main()
