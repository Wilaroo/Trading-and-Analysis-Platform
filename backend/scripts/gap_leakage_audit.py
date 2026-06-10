#!/usr/bin/env python3
"""
v19.34.318 — Gap-fill LEAKAGE audit (run on the DGX, read-only, no retrain).

The promoted gap models score a suspiciously high ~94.6% on a ~30% base rate.
Hypothesis: look-ahead leakage. The training target checks fill over [i, i+w]
(INCLUDING the session-open bar i), and the feature row for bar i also includes
bar i's own high/low/close + first-bar close/volume. So any gap that fills
*within the opening bar* is trivially readable from the features.

This script quantifies the leak on real intraday bars:
  • fill_rate_current  — target as trained: fill within [i, i+w]
  • fill_in_open_bar   — % of ALL gaps that fill DURING bar i alone
  • of FILLS, % that occurred in bar i (the leakable fraction)
  • fill_rate_nopeek   — honest target: fill within [i+1, i+w] (exclude open bar)

If a large share of fills happen in bar i, the headline accuracy is inflated by
leakage and the target must be made "no-peek" (decide at the open; exclude bar i
from both features and the fill window).

Usage (from backend/, env sourced):
    PYTHONPATH=. ../.venv/bin/python scripts/gap_leakage_audit.py
    PYTHONPATH=. ../.venv/bin/python scripts/gap_leakage_audit.py --symbols 150
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from pymongo import MongoClient

from services.ai_modules.gap_fill_model import (
    GAP_MODEL_CONFIGS, OVERNIGHT_GAP_MIN_PCT, find_session_open_indices,
)


def _touched(lows, highs, pc, gap_dir):
    """Did price touch prev_close in this slice? gap_dir>0: low<=pc; else high>=pc."""
    if gap_dir > 0:
        return bool(np.any(lows <= pc))
    return bool(np.any(highs >= pc))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=150)
    args = ap.parse_args()
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    print("=" * 72)
    print("GAP-FILL LEAKAGE AUDIT (v19.34.318) — read-only")
    print("=" * 72)

    for bs, cfg in GAP_MODEL_CONFIGS.items():
        w = cfg["early_window_bars"]
        syms = db["ib_historical_data"].distinct("symbol", {"bar_size": bs})[:args.symbols]

        n_gaps = 0
        fill_cur = 0          # fill within [i, i+w]
        fill_open = 0         # fill within bar i only
        fill_nopeek = 0       # fill within [i+1, i+w]
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
                if i < 1 or i + w >= len(bars):
                    continue
                pc = closes[i - 1]
                if pc <= 0:
                    continue
                gap = (opens[i] - pc) / pc
                if abs(gap) < OVERNIGHT_GAP_MIN_PCT:
                    continue
                gd = 1.0 if gap > 0 else -1.0
                n_gaps += 1
                cur = _touched(lows[i:i + w], highs[i:i + w], pc, gd)
                openbar = _touched(lows[i:i + 1], highs[i:i + 1], pc, gd)
                nopeek = _touched(lows[i + 1:i + w], highs[i + 1:i + w], pc, gd)
                fill_cur += int(cur)
                fill_open += int(openbar)
                fill_nopeek += int(nopeek)

        if n_gaps == 0:
            print(f"\n[{bs}] no qualifying gaps")
            continue
        pct = lambda x: 100.0 * x / n_gaps
        leak_share = 100.0 * fill_open / fill_cur if fill_cur else 0.0
        print(f"\n[{bs}]  window={w} bars   gaps={n_gaps}")
        print(f"  fill_rate_current  [i .. i+w] : {pct(fill_cur):5.1f}%   (target as trained)")
        print(f"  fill_in_OPEN_bar   [i]        : {pct(fill_open):5.1f}%   (leakable in bar i)")
        print(f"  fill_rate_nopeek   [i+1..i+w] : {pct(fill_nopeek):5.1f}%   (honest target)")
        print(f"  → of all fills, {leak_share:4.1f}% happen in the OPEN bar (leak surface)")
        verdict = ("SEVERE leakage — redesign target (no-peek)" if leak_share >= 40
                   else "moderate leakage — recommend no-peek target" if leak_share >= 20
                   else "low leakage — target acceptable")
        print(f"  VERDICT: {verdict}")

    print("\nIf leak_share is high, the ~94.6% headline is inflated: the model reads")
    print("bar-i's own range. Fix = decide at the open → exclude bar i from BOTH the")
    print("feature row and the fill window (target over [i+1, i+w]).")


if __name__ == "__main__":
    main()
