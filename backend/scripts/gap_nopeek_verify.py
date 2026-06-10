#!/usr/bin/env python3
"""
v19.34.319 — NO-PEEK gap-fill verify (run on the DGX, read-only, no retrain).

Replays the EXACT v319 no-peek target window [i+1, i+early_window] (excluding
the session-open bar i) on real intraday bars and reports the honest fill rate
per timeframe. Companion to scripts/gap_leakage_audit.py — that script proved
the leak; this one confirms the post-fix target is BALANCED (goal: ~25-75%) and
that the open-bar fills are no longer counted.

Usage (from backend/, env sourced):
    PYTHONPATH=. ../.venv/bin/python scripts/gap_nopeek_verify.py
    PYTHONPATH=. ../.venv/bin/python scripts/gap_nopeek_verify.py --symbols 150
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from pymongo import MongoClient

from services.ai_modules.gap_fill_model import (
    GAP_MODEL_CONFIGS, OVERNIGHT_GAP_MIN_PCT, compute_gap_fill_target,
    find_session_open_indices,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=150)
    args = ap.parse_args()
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    print("=" * 72)
    print("GAP-FILL NO-PEEK VERIFY (v19.34.319) — read-only")
    print("=" * 72)

    for bs, cfg in GAP_MODEL_CONFIGS.items():
        w = cfg["early_window_bars"]
        syms = db["ib_historical_data"].distinct("symbol", {"bar_size": bs})[:args.symbols]

        n_gaps = 0
        fill_nopeek = 0          # v319 target: fill within [i+1, i+w]
        for sym in syms:
            bars = list(db["ib_historical_data"].find(
                {"symbol": sym, "bar_size": bs},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1},
            ).sort("date", 1).limit(20000))
            if len(bars) < 70 + w:
                continue
            opens = np.array([b["open"] for b in bars], float)
            highs = np.array([b["high"] for b in bars], float)
            lows = np.array([b["low"] for b in bars], float)
            closes = np.array([b["close"] for b in bars], float)
            dates = [str(b.get("date", "")) for b in bars]
            sess = find_session_open_indices(dates)

            for k in range(1, len(sess)):
                i = sess[k]
                # mirror the training bounds exactly (decide-at-open, post-open window)
                if i < 50 or i + 1 + w > len(bars):
                    continue
                pc = closes[i - 1]
                if pc <= 0:
                    continue
                gap = (opens[i] - pc) / pc
                if abs(gap) < OVERNIGHT_GAP_MIN_PCT:
                    continue
                gd = 1.0 if gap > 0 else -1.0
                n_gaps += 1
                t = compute_gap_fill_target(
                    lows[i + 1:i + 1 + w], highs[i + 1:i + 1 + w], pc, gd, w,
                )
                fill_nopeek += int(t == 1)

        if n_gaps == 0:
            print(f"\n[{bs}] no qualifying gaps")
            continue
        rate = 100.0 * fill_nopeek / n_gaps
        banded = 25.0 <= rate <= 75.0
        print(f"\n[{bs}]  window={w} bars (post-open)   gaps={n_gaps}")
        print(f"  fill_rate_nopeek  [i+1 .. i+w] : {rate:5.1f}%   "
              f"({'BALANCED ✅' if banded else 'OUT OF BAND ⚠'})")

    print("\nThis is the honest target the v319 models train on. Open-bar fills are")
    print("excluded; a model that still scores ~90%+ on this would indicate a")
    print("REMAINING leak — expect accuracy near a tradeable edge, not ~94.6%.")


if __name__ == "__main__":
    main()
