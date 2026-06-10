#!/usr/bin/env python3
"""
diag_model_family_audit.py  —  audit  (2026-06-10)   READ-ONLY

One-shot audit of EVERY promoted model in timeseries_models, grouped by family:
  - count, avg accuracy
  - class-collapse count (min per-class recall < 0.10 → fake "edge")
  - CONSUMED-at-inference verdict (from the code audit)

Lets us split the ~110 promoted models into: (live + healthy), (live + collapsed
→ urgent), (dead + healthy → wire-in candidates), (dead + collapsed → retire).

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/diag_model_family_audit.py
"""
import os
import re
import sys
from collections import defaultdict

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
COLL = "timeseries_models"
FLOOR = 0.10

# (regex, family, consumed_at_inference)  — first match wins; order matters.
RULES = [
    (r"_high_vol$|_bull_trend$|_bear_trend$|_range_bound$", "regime_conditional", False),
    (r"^vol_predictor_",        "volatility",       False),
    (r"^gap_fill_",             "gap_fill",         False),
    (r"^exit_timing_",          "exit_timing",      False),
    (r"^risk_of_ruin_",         "risk_of_ruin",     False),
    (r"^sector_relative_|^sector_",  "sector_relative", False),
    (r"^ensemble_",             "ensemble",         True),   # gate meta-labeler
    (r"^direction_predictor_(1min|5min|15min|30min|1hour|daily|weekly)$", "direction_LIVE", True),
    (r"_predictor$",            "setup_models",     "via-ensemble?"),
]


def _fam(name):
    for rx, fam, consumed in RULES:
        if re.search(rx, name):
            return fam, consumed
    return "other", "?"


def _acc(d):
    m = d.get("metrics") or {}
    for src in (m, d):
        v = src.get("accuracy")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _minrecall(d):
    m = d.get("metrics") or {}
    ru = m.get("recall_up"); rd = m.get("recall_down")
    if isinstance(ru, (int, float)) and isinstance(rd, (int, float)):
        return min(float(ru), float(rd))
    return None


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    docs = list(db[COLL].find({}, {"_id": 0, "name": 1, "metrics": 1, "num_classes": 1}))
    print(f"\ntimeseries_models total: {len(docs)}\n")

    fams = defaultdict(lambda: {"n": 0, "acc": [], "collapsed": 0, "consumed": "?", "names": []})
    for d in docs:
        name = d.get("name", "?")
        fam, consumed = _fam(name)
        f = fams[fam]
        f["n"] += 1
        f["consumed"] = consumed
        a = _acc(d)
        if a is not None:
            f["acc"].append(a)
        mr = _minrecall(d)
        if mr is not None and mr < FLOOR:
            f["collapsed"] += 1
        f["names"].append(name)

    print(f"  {'family':>20} {'n':>4} {'avg_acc':>8} {'collapsed':>10} {'consumed?':>14}")
    print("  " + "-" * 62)
    tot_dead = tot_collapsed = 0
    for fam in sorted(fams, key=lambda x: -fams[x]["n"]):
        f = fams[fam]
        avg = sum(f["acc"]) / len(f["acc"]) if f["acc"] else float("nan")
        consumed = f["consumed"]
        cons_str = {True: "LIVE", False: "DEAD"}.get(consumed, str(consumed))
        print(f"  {fam:>20} {f['n']:>4} {avg:>8.3f} {f['collapsed']:>4}/{f['n']:<5} {cons_str:>14}")
        if consumed is False:
            tot_dead += f["n"]
        tot_collapsed += f["collapsed"]

    print("\n  SUMMARY")
    print(f"    total promoted models : {len(docs)}")
    print(f"    DEAD at inference     : {tot_dead}")
    print(f"    class-collapsed       : {tot_collapsed}")
    print("    (DEAD = trained nightly, never read by any live decision path)")

    # quick edge scan among DEAD families: which have healthy two-sided models?
    print("\n  DEAD-but-HEALTHY (wire-in candidates, min-recall >= 0.10 & acc >= 0.52):")
    for d in docs:
        name = d.get("name", "?")
        fam, consumed = _fam(name)
        if consumed is not False:
            continue
        a = _acc(d); mr = _minrecall(d)
        if a is not None and mr is not None and a >= 0.52 and mr >= FLOOR:
            print(f"     {name:>34}  acc={a:.3f}  min_recall={mr:.2f}")

    print("\nDONE.\n")


if __name__ == "__main__":
    main()
