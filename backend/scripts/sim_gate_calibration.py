#!/usr/bin/env python3
"""
sim_gate_calibration.py  —  v19.34.311  (2026-06-10)   READ-ONLY, never persists

Demonstrates WHY the current gate auto-calibrator (gate_calibrator.py) would
push thresholds UP rather than loosen, and contrasts win-rate targeting vs
expectancy (EV) targeting on the SAME outcomes.

It also prints a correct (timestamp-sorted) trading-mode distribution, fixing
the unsorted B3 panel in diag_gate_calibration_audit.py.

Run AFTER --apply-relabel for the truest picture (works either way):
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/sim_gate_calibration.py
"""
import os
import sys
from collections import Counter

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

GATE_DEFAULTS = {"aggressive": 28, "normal": 38, "cautious": 50, "defensive": 60}
GO_WR, REDUCE_WR = 0.50, 0.38  # current win-rate targets in gate_calibrator.py


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    col = db["confidence_gate_log"]

    # ---- corrected mode distribution: recent 20k (timestamp DESC) + overall ----
    hr("MODE DISTRIBUTION (corrected — timestamp-sorted)")
    recent = Counter()
    for d in col.find({}, {"_id": 0, "trading_mode": 1}).sort("timestamp", -1).limit(20000):
        recent[str(d.get("trading_mode", "?"))] += 1
    rtot = sum(recent.values()) or 1
    print("  most-recent 20,000 decisions:")
    for k, v in recent.most_common():
        print(f"     {k:>10}: {v:,} ({100*v/rtot:.1f}%)")
    print("  overall (aggregation over ALL docs):")
    agg = col.aggregate([{"$group": {"_id": "$trading_mode", "n": {"$sum": 1}}},
                         {"$sort": {"n": -1}}])
    rows = list(agg)
    otot = sum(r["n"] for r in rows) or 1
    for r in rows:
        print(f"     {str(r['_id']):>10}: {r['n']:,} ({100*r['n']/otot:.1f}%)")

    # ---- pull tracked outcomes (post-relabel canonicalized) ----
    hr("CALIBRATION SIMULATION  (win-rate target vs EV target — READ-ONLY)")
    docs = list(col.find(
        {"outcome_tracked": True, "confidence_score": {"$exists": True}},
        {"_id": 0, "confidence_score": 1, "trade_outcome": 1, "outcome_pnl": 1},
    ))
    n = len(docs)
    print(f"  tracked outcomes available: {n}")
    if n == 0:
        print("  Nothing to simulate. Run --apply-relabel first / let trades close.")
        return

    def canon(o):
        o = str(o or "").lower()
        if o in ("win", "won", "w"):
            return "win"
        if o in ("loss", "lost", "lose", "l"):
            return "loss"
        return "scratch"

    buckets = {}
    for d in docs:
        b = (int(d.get("confidence_score", 0)) // 5) * 5
        s = buckets.setdefault(b, {"total": 0, "wins": 0, "pnl": 0.0})
        s["total"] += 1
        if canon(d.get("trade_outcome")) == "win":
            s["wins"] += 1
        s["pnl"] += float(d.get("outcome_pnl") or 0.0)

    keys = sorted(buckets)
    overall_w = sum(b["wins"] for b in buckets.values())
    overall_pnl = sum(b["pnl"] for b in buckets.values())
    print(f"  overall win-rate: {overall_w}/{n} = {100*overall_w/n:.1f}%   "
          f"total P&L: {overall_pnl:+.2f}   avg/trade: {overall_pnl/n:+.2f}")

    print("\n  cumulative (take all trades with score >= X):")
    print(f"     {'score>=':>8} {'trades':>7} {'win%':>6} {'EV/trade':>9} {'totPnL':>10}")
    cum = {}
    for t in keys:
        sel = [b for b in keys if b >= t]
        tot = sum(buckets[b]["total"] for b in sel)
        win = sum(buckets[b]["wins"] for b in sel)
        pnl = sum(buckets[b]["pnl"] for b in sel)
        wr = win / tot if tot else 0
        ev = pnl / tot if tot else 0
        cum[t] = {"total": tot, "wr": wr, "ev": ev}
        print(f"     {t:>8} {tot:>7} {100*wr:>5.1f}% {ev:>9.2f} {pnl:>10.2f}")

    def find_wr(target, min_s):
        for t in keys:
            if cum[t]["total"] >= min_s and cum[t]["wr"] >= target:
                return t
        return 40  # gate_calibrator fallback

    def find_ev(min_s):
        for t in keys:
            if cum[t]["total"] >= min_s and cum[t]["ev"] > 0:
                return t
        return None

    go_wr = find_wr(GO_WR, 10)
    red_wr = find_wr(REDUCE_WR, 5)
    go_ev = find_ev(10)
    red_ev = find_ev(5)

    hr("WHAT EACH OBJECTIVE WOULD SET")
    print(f"  WIN-RATE objective (current code):  base_go={go_wr}  base_reduce={red_wr}")
    print("     -> per-mode (offsets in gate_calibrator):")
    for m, off in (("normal", 0), ("cautious", 15), ("defensive", 25)):
        print(f"        {m:>10}: GO={go_wr+off}  vs default {GATE_DEFAULTS[m]}  "
              f"-> {'STRICTER' if go_wr+off > GATE_DEFAULTS[m] else 'looser/same'}")
    print(f"\n  EXPECTANCY objective (proposed):    base_go={go_ev}  base_reduce={red_ev}")
    print("     (lowest score where cumulative EV/trade > 0 — i.e. profitable to take)")

    print("\nDONE.  (Nothing was written to the database.)\n")


if __name__ == "__main__":
    main()
