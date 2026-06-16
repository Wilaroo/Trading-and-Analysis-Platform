#!/usr/bin/env python3
"""diag_spy_atr_distribution.py  —  READ-ONLY  (2026-06-16)

Computes SPY's ATR_5 / ATR_20 ratio distribution over multiple lookback
windows to inform the P0 classify_regime threshold decision.

Output: per-window quantiles + "days exceeding current threshold (1.3)" +
"threshold needed for target high_vol rate (25%)".
"""
import os
import sys
from datetime import datetime, timezone, timedelta
import numpy as np
from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass


def _atr(highs, lows, closes, period):
    """ATR as classify_regime computes it — most-recent-first arrays."""
    n = len(closes)
    vals = []
    for i in range(min(period, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
            abs(lows[i] - closes[i + 1]) if i + 1 < n else highs[i] - lows[i],
        )
        vals.append(tr)
    return float(np.mean(vals)) if vals else 0.0


def main():
    mu, dn = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mu or not dn:
        print("ERROR: MONGO_URL/DB_NAME not set"); sys.exit(1)
    db = MongoClient(mu, serverSelectionTimeoutMS=8000)[dn]
    col = db["ib_historical_data"]
    # Pull last ~200 SPY daily bars (most-recent-first).
    bars = list(col.find(
        {"symbol": "SPY", "bar_size": "1 day"},
        {"_id": 0, "date": 1, "close": 1, "high": 1, "low": 1},
    ).sort("date", -1).limit(200))
    print(f"Loaded {len(bars)} SPY daily bars from ib_historical_data")
    if len(bars) < 50:
        print("Not enough bars for analysis (need ≥50). Aborting.")
        sys.exit(1)

    # Compute ratio at each day t using bars[t..t+24] as 'most-recent-first'
    # slice — exact same window classify_regime sees at that day.
    closes = np.array([b["close"] for b in bars], dtype=float)
    highs  = np.array([b["high"]  for b in bars], dtype=float)
    lows   = np.array([b["low"]   for b in bars], dtype=float)
    dates  = [b["date"] for b in bars]

    ratios = []
    for t in range(len(closes) - 25):
        c = closes[t:t+30]; h = highs[t:t+30]; l = lows[t:t+30]
        atr5 = _atr(h, l, c, 5)
        atr20 = _atr(h, l, c, 20)
        if atr20 > 0:
            ratios.append((dates[t], atr5 / atr20))
    print(f"Computed {len(ratios)} daily ATR_5/ATR_20 ratios.\n")

    # Windows: 30d, 90d, 180d (most recent N entries).
    for window in (30, 90, 180):
        if len(ratios) < window:
            print(f"-- {window}d window: insufficient data ({len(ratios)} bars available)")
            continue
        sub = ratios[:window]
        vals = np.array([r for _, r in sub])
        n_over_13 = int(np.sum(vals > 1.3))
        pct_over_13 = n_over_13 / len(vals) * 100
        # Threshold to get exactly 25% high_vol (75th percentile of ratio).
        t_25 = float(np.percentile(vals, 75))
        # Quantiles
        q = lambda p: float(np.percentile(vals, p))
        print(f"-- last {window}d ({sub[-1][0][:10]} → {sub[0][0][:10]}) --")
        print(f"   ratio p25/p50/p75/p90/p95: "
              f"{q(25):.3f} / {q(50):.3f} / {q(75):.3f} / {q(90):.3f} / {q(95):.3f}")
        print(f"   mean: {float(np.mean(vals)):.3f}   std: {float(np.std(vals)):.3f}")
        print(f"   days exceeding 1.3 (current threshold): "
              f"{n_over_13}/{len(vals)} ({pct_over_13:.1f}%)")
        print(f"   threshold for ~25% high_vol rate: {t_25:.3f}")
        print()

    # Recent 7d sanity (vs the 91% high_vol diag observation).
    sub = ratios[:7]
    vals = np.array([r for _, r in sub])
    n_over_13 = int(np.sum(vals > 1.3))
    print(f"-- last 7d (sanity vs observed 91% high_vol) --")
    print(f"   days exceeding 1.3: {n_over_13}/{len(vals)} "
          f"({n_over_13/len(vals)*100:.1f}%)")
    print(f"   per-day:")
    for dt, r in sub:
        flag = " ← HIGH_VOL fires" if r > 1.3 else ""
        print(f"     {dt[:10]}  ratio={r:.3f}{flag}")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
