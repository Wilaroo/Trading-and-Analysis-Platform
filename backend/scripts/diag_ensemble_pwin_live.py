#!/usr/bin/env python3
"""
diag_ensemble_pwin_live.py  —  P-LIVE-1 verification  (2026-06-10)   READ-ONLY

Settles whether the ensemble meta-labeler is genuinely broken or whether the
argmax-recall "collapse" flag was the wrong lens for a graded-probability model.

The gate logs the live P(win) in each decision's reasoning:
    "Ensemble meta-labeler <name>: P(win)=NN% ..."
This parses that across recent decisions and reports the live distribution +
how often each gate branch fires (force-skip <0.5, +5/+10/+15 bands).

Verdict logic:
  - If p_win SPANS 0.5 with real spread (crosses the bands) -> DISCRIMINATING.
    The training argmax-recall flag was misleading; do NOT class-weight.
  - If p_win is squashed near one value / rarely crosses 0.5 -> genuinely broken.

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_ensemble_pwin_live.py
"""
import os
import re
import sys
from collections import Counter, defaultdict

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
SAMPLE = 20000
PWIN_RE = re.compile(r"Ensemble meta-labeler\s+(\S+):\s*P\(win\)=(\d+)%")


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    cg = db["confidence_gate_log"]

    hr(f"ENSEMBLE LIVE P(win) — last {SAMPLE:,} decisions")
    pwins = []
    per_ens = defaultdict(list)
    unavailable = 0
    seen = 0
    for d in cg.find({}, {"_id": 0, "reasoning": 1}).sort("timestamp", -1).limit(SAMPLE):
        seen += 1
        blob = " || ".join(d.get("reasoning", []) or [])
        m = PWIN_RE.search(blob)
        if m:
            name = m.group(1)
            pw = int(m.group(2)) / 100.0
            pwins.append(pw)
            per_ens[name].append(pw)
        elif "Ensemble meta-labeler unavailable" in blob:
            unavailable += 1

    if not pwins:
        print("  No ensemble P(win) entries parsed. (Different reasoning format?)")
        return

    pwins.sort()
    n = len(pwins)
    def q(p): return pwins[min(n - 1, int(n * p))]
    frac = lambda lo, hi: sum(1 for x in pwins if lo <= x < hi) / n

    print(f"  decisions sampled     : {seen:,}")
    print(f"  with ensemble P(win)  : {n:,}")
    print(f"  ensemble unavailable  : {unavailable:,}")
    print(f"\n  p_win  min={pwins[0]:.2f}  p10={q(.10):.2f}  median={q(.50):.2f}  "
          f"p90={q(.90):.2f}  max={pwins[-1]:.2f}  std={(sum((x-sum(pwins)/n)**2 for x in pwins)/n)**0.5:.3f}")
    print("\n  gate-branch distribution:")
    print(f"     <0.50  FORCE-SKIP : {frac(0,0.50)*100:5.1f}%")
    print(f"     0.50-0.55 half    : {frac(0.50,0.55)*100:5.1f}%")
    print(f"     0.55-0.65 (+5)    : {frac(0.55,0.65)*100:5.1f}%")
    print(f"     0.65-0.75 (+10)   : {frac(0.65,0.75)*100:5.1f}%")
    print(f"     >=0.75   (+15)    : {sum(1 for x in pwins if x>=0.75)/n*100:5.1f}%")

    hr("PER-ENSEMBLE SPREAD")
    print(f"  {'ensemble':>20} {'n':>6} {'median':>7} {'min':>5} {'max':>5} {'<0.5%':>7}")
    for name in sorted(per_ens, key=lambda x: -len(per_ens[x])):
        v = sorted(per_ens[name]); k = len(v)
        med = v[k//2]; skp = sum(1 for x in v if x < 0.5)/k*100
        print(f"  {name:>20} {k:>6} {med:>7.2f} {v[0]:>5.2f} {v[-1]:>5.2f} {skp:>6.1f}%")

    hr("VERDICT")
    spread = pwins[-1] - pwins[0]
    crosses = 0.05 < frac(0, 0.50) < 0.95  # both sides of 0.5 represented
    if spread >= 0.20 and crosses:
        print("  DISCRIMINATING — p_win spans 0.5 with real spread. The training")
        print("  argmax-recall 'collapse' flag was the WRONG metric for this graded")
        print("  meta-labeler. DO NOT class-weight (it would distort calibration and")
        print("  the gate's 0.5/0.75 thresholds). Treat P-LIVE-1 as a false alarm;")
        print("  re-validate calibration on forward CLEAN outcomes instead.")
    else:
        print("  SQUASHED — p_win barely moves / rarely crosses 0.5. Genuinely weak")
        print("  discrimination → P-LIVE-1 is real: rebuild the meta-label target")
        print("  (balanced/quantile) and RECALIBRATE the gate's p_win thresholds.")
    print("\nDONE.\n")


if __name__ == "__main__":
    main()
