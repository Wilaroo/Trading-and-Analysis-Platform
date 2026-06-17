#!/usr/bin/env python3
"""
v320x — REGIME VALIDATION (READ-ONLY): is the regime stuff ACCURATE + PREDICTIVE?

Backtests BOTH regime subsystems against realized forward index moves, using the
REAL production functions on ib_historical_data daily bars (no reimplementation):

PART 1 — P-WIRE classify_regime (high_vol / bull / bear / range)
  • Recomputes the regime label for each SPY day via the production
    classify_regime(), recovers vol_expansion (atr_5/atr_20), and cross-tabs the
    label against an ABSOLUTE realized-vol proxy (20d annualized stdev of daily
    returns). Answers: "is high_vol firing on genuinely volatile tape, or is it a
    relative-expansion artifact at low absolute vol?" (the VIX-16 question).
  • Threshold sensitivity: % high_vol at the 1.3 cutoff vs 1.4 / 1.5 / 1.6.
  • PREDICTIVENESS: per regime label, the realized forward |move| (did high_vol
    actually precede bigger moves?) and signed forward return (did bull precede up?).

PART 2 — MTF directional trend score (market_regime_engine.TrendSignalBlock)
  • Recomputes the 0-100 per-index trend score (SPY/QQQ/IWM) for each day via the
    production _score_index(), buckets bull(>=60)/neutral/bear(<=40), and measures
    forward index return per bucket. Answers: "is the directional regime PREDICTIVE
    or just coherent?"

NOTHING is written.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320x_regime_validation.py [LOOKBACK_DAYS]  # default 180
"""
import sys
from collections import defaultdict
from statistics import mean, median, pstdev

import numpy as np
from pymongo import MongoClient

sys.path.insert(0, "backend")
try:
    from services.ai_modules.regime_conditional_model import classify_regime
    from services.market_regime_engine import TrendSignalBlock
except Exception:  # pragma: no cover
    from backend.services.ai_modules.regime_conditional_model import classify_regime
    from backend.services.market_regime_engine import TrendSignalBlock

FWD = (1, 3, 5)
TRADING_YR = 252


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _load_daily(db, sym, n=500):
    cur = (db.ib_historical_data
           .find({"symbol": sym.upper(), "bar_size": "1 day"},
                 {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1})
           .sort("date", -1).limit(n))
    seen = {}
    for b in cur:
        dk = str(b.get("date", ""))[:10]
        if dk and b.get("close", 0) > 0:
            seen[dk] = b
    return sorted(seen.values(), key=lambda x: str(x["date"])[:10])  # oldest-first


def _vol_expansion(h, lo, c):
    """Replicates classify_regime._atr exactly. Arrays most-recent-FIRST."""
    n = len(c)

    def atr(period):
        vals = []
        for i in range(min(period, n - 1)):
            tr = max(h[i] - lo[i],
                     abs(h[i] - c[i + 1]) if i + 1 < n else h[i] - lo[i],
                     abs(lo[i] - c[i + 1]) if i + 1 < n else h[i] - lo[i])
            vals.append(tr)
        return mean(vals) if vals else 0.0
    a5, a20 = atr(5), atr(20)
    return a5 / a20 if a20 > 0 else 1.0


def _pct(n, d):
    return f"{100.0*n/d:.0f}%" if d else "n/a"


def part1_pwire(db, lookback):
    print("=" * 70)
    print("PART 1 — P-WIRE classify_regime (SPY daily)  [the high_vol question]")
    print("=" * 70)
    spy = _load_daily(db, "SPY", lookback + 60)
    closes = [b["close"] for b in spy]
    highs = [b["high"] for b in spy]
    lows = [b["low"] for b in spy]
    dates = [str(b["date"])[:10] for b in spy]
    N = len(spy)
    if N < 60:
        print(f"  insufficient SPY daily bars ({N})"); return

    daily_ret = [0.0] + [(closes[i] / closes[i - 1] - 1) for i in range(1, N)]
    rows = []
    start = max(25, N - lookback)
    for i in range(start, N - max(FWD)):
        win = slice(i - 24, i + 1)
        c = np.array(closes[win][::-1]); h = np.array(highs[win][::-1]); lo = np.array(lows[win][::-1])
        label = classify_regime(c, h, lo)
        ve = _vol_expansion(list(h), list(lo), list(c))
        # absolute realized vol up to day i (20d annualized %)
        win20 = daily_ret[max(1, i - 19): i + 1]
        rv = pstdev(win20) * (TRADING_YR ** 0.5) * 100 if len(win20) > 2 else 0.0
        fwd = {k: (closes[i + k] / closes[i] - 1) * 100 for k in FWD}
        rows.append((dates[i], label, ve, rv, fwd))

    n = len(rows)
    by_label = defaultdict(list)
    for r in rows:
        by_label[r[1]].append(r)
    print(f"\n  classified {n} SPY days (last ~{lookback}td)")
    print("  regime distribution:")
    for lab in sorted(by_label, key=lambda k: -len(by_label[k])):
        print(f"     {lab:<12} {len(by_label[lab]):>4}  ({_pct(len(by_label[lab]), n)})")

    # absolute-vol cross-tab
    print("\n  ABSOLUTE realized-vol (20d annualized %) by regime  — is high_vol genuinely volatile?")
    print(f"     {'regime':<12} {'n':>4} {'med_realvol':>12} {'p90':>7} {'med_VE':>8}")
    allrv = sorted(r[3] for r in rows)
    for lab in sorted(by_label, key=lambda k: -len(by_label[k])):
        g = by_label[lab]
        rvs = sorted(x[3] for x in g)
        ves = sorted(x[2] for x in g)
        p90 = rvs[int(0.9 * (len(rvs) - 1))] if rvs else 0
        print(f"     {lab:<12} {len(g):>4} {median(rvs):>12.1f} {p90:>7.1f} {median(ves):>8.2f}")
    print(f"     {'ALL-DAYS':<12} {n:>4} {median(allrv):>12.1f} "
          f"{allrv[int(0.9*(len(allrv)-1))]:>7.1f}")
    print("     (if high_vol med_realvol ≈ ALL-DAYS, the label is NOT tracking true volatility)")

    # threshold sensitivity
    ves = [r[2] for r in rows]
    print("\n  vol_expansion (atr5/atr20) distribution + threshold sensitivity:")
    print(f"     min={min(ves):.2f}  median={median(ves):.2f}  "
          f"p90={sorted(ves)[int(0.9*(len(ves)-1))]:.2f}  max={max(ves):.2f}")
    for thr in (1.3, 1.4, 1.5, 1.6):
        hv = sum(1 for v in ves if v > thr)
        print(f"     %high_vol @ threshold >{thr}:  {_pct(hv, n)}  ({hv}/{n})")

    # predictiveness
    print("\n  PREDICTIVENESS — realized forward move per regime (SPY %):")
    print(f"     {'regime':<12} {'n':>4} | " + "  ".join(f"fwd{k}d signed/|abs|" for k in FWD))
    for lab in sorted(by_label, key=lambda k: -len(by_label[k])):
        g = by_label[lab]
        parts = []
        for k in FWD:
            sig = mean(x[4][k] for x in g)
            ab = mean(abs(x[4][k]) for x in g)
            parts.append(f"{sig:+.2f}/{ab:.2f}")
        print(f"     {lab:<12} {len(g):>4} | " + "   ".join(parts))
    print("     (high_vol SHOULD show larger |abs| forward moves; bull +signed, bear -signed)")


def part2_mtf(db, lookback):
    print("\n" + "=" * 70)
    print("PART 2 — MTF directional trend score (TrendSignalBlock._score_index)")
    print("=" * 70)
    tb = TrendSignalBlock()
    for sym in ("SPY", "QQQ", "IWM"):
        bars = _load_daily(db, sym, max(420, lookback + 220))
        N = len(bars)
        if N < 210:
            print(f"\n  {sym}: insufficient daily bars ({N}, need >=210) — skip"); continue
        closes = [b["close"] for b in bars]
        buckets = defaultdict(list)  # band -> list of fwd5 %
        start = max(200, N - lookback)
        scored = 0
        for i in range(start, N - max(FWD)):
            res = tb._score_index(bars[: i + 1])
            if not res:
                continue
            scored += 1
            s = res["score"]
            band = "BULL(>=60)" if s >= 60 else ("BEAR(<=40)" if s <= 40 else "NEUTRAL")
            fwd5 = (closes[i + 5] / closes[i] - 1) * 100
            buckets[band].append(fwd5)
        print(f"\n  {sym}: scored {scored} days")
        print(f"     {'band':<12} {'n':>4} {'avg_fwd5%':>10} {'%positive':>10}")
        for band in ("BULL(>=60)", "NEUTRAL", "BEAR(<=40)"):
            v = buckets.get(band, [])
            if not v:
                print(f"     {band:<12} {0:>4}"); continue
            pos = sum(1 for x in v if x > 0)
            print(f"     {band:<12} {len(v):>4} {mean(v):>10.2f} {_pct(pos, len(v)):>10}")
        print("     (predictive if BULL avg_fwd5% > NEUTRAL > BEAR and BULL %positive > 50)")


def main():
    lookback = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 180
    db = _db()
    print(f"\n### v320x REGIME VALIDATION — lookback {lookback} trading days ###\n")
    part1_pwire(db, lookback)
    part2_mtf(db, lookback)
    print("\n### READING IT ###")
    print("• PART 1: if high_vol's med_realvol ≈ all-days AND %high_vol collapses when")
    print("    the threshold moves 1.3→1.5, then high_vol is a relative-expansion ARTIFACT")
    print("    (fires at low absolute vol / VIX~16) → recalibration is justified after all.")
    print("• If high_vol genuinely shows higher realvol AND larger forward |moves|, the")
    print("    1.3 threshold is accurate (your earlier audit) → leave it.")
    print("• PART 2: BULL>NEUTRAL>BEAR on forward returns = the directional regime is")
    print("    predictive, not just internally coherent.\n")


if __name__ == "__main__":
    main()
