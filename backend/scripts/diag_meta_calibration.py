#!/usr/bin/env python3
"""
diag_meta_calibration.py  (READ-ONLY)
=====================================
DECISION-CRITICAL: should the meta-labeler force-skip (p_win < 0.50) be relaxed?

The meta-labeler trains with BALANCED class weights, so p_win is a RANKING signal,
not a calibrated probability. Before lowering the 0.50 cut we must measure, from
REAL outcomes, whether p_win is calibrated and what the actual reward:risk is.

This reads confidence_gate_log rows that:
  - have an ensemble_meta_signal.p_win, AND
  - were executed (decision GO/REDUCE) and have a tracked outcome.

It then builds a RELIABILITY CURVE:
  p_win bucket  ->  realized win-rate, avg P&L, count

plus the realized reward:risk (avg win $ / avg loss $), which gives the TRUE
breakeven win-rate. If realized win-rate tracks p_win and the 0.50-0.55 band is
already comfortably above breakeven, then the 0.45-0.50 band is plausibly still
profitable and relaxing the cut is justified. If 0.50-0.55 is already marginal,
the cut should stay.

NOTE: force-skipped trades (p_win<0.50) were never taken, so we cannot measure
them directly — we infer from the calibration trend in the traded region.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_meta_calibration.py
"""
import os
from collections import defaultdict

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

# Pull executed, outcome-tracked rows that carry a meta-labeler p_win
cur = db.confidence_gate_log.find(
    {"outcome_tracked": True, "ensemble_meta_signal": {"$ne": None}},
    {"_id": 0, "ensemble_meta_signal": 1, "trade_outcome": 1,
     "outcome_pnl": 1, "decision": 1, "setup_type": 1},
)

BUCKETS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.75), (0.75, 1.01)]


def bkey(p):
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return (lo, hi)
    return None


agg = defaultdict(lambda: {"n": 0, "win": 0, "loss": 0, "scratch": 0,
                           "pnl": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0,
                           "n_win_pnl": 0, "n_loss_pnl": 0})
per_setup = defaultdict(lambda: {"n": 0, "win": 0, "pnl": 0.0})
n_rows = 0
all_win_pnl, all_loss_pnl = [], []

for r in cur:
    ems = r.get("ensemble_meta_signal") or {}
    p = ems.get("p_win")
    if p is None:
        continue
    try:
        p = float(p)
    except Exception:
        continue
    bk = bkey(p)
    if bk is None:
        continue
    n_rows += 1
    outcome = (r.get("trade_outcome") or "").lower()
    pnl = r.get("outcome_pnl")
    try:
        pnl = float(pnl) if pnl is not None else 0.0
    except Exception:
        pnl = 0.0

    a = agg[bk]
    a["n"] += 1
    a["pnl"] += pnl
    if outcome == "win":
        a["win"] += 1
        a["win_pnl"] += pnl
        a["n_win_pnl"] += 1
        all_win_pnl.append(pnl)
    elif outcome == "loss":
        a["loss"] += 1
        a["loss_pnl"] += pnl
        a["n_loss_pnl"] += 1
        all_loss_pnl.append(pnl)
    else:
        a["scratch"] += 1

    st = r.get("setup_type", "?")
    per_setup[st]["n"] += 1
    per_setup[st]["pnl"] += pnl
    if outcome == "win":
        per_setup[st]["win"] += 1

print("=" * 84)
print(f"META-LABELER CALIBRATION  (executed + outcome-tracked rows: {n_rows:,})")
print("=" * 84)

if n_rows == 0:
    print("  No outcome-tracked rows carry an ensemble_meta_signal.p_win.")
    print("  (Outcome tracking may not be wired, or p_win not logged.) Can't calibrate.")
else:
    print(f"\n{'p_win band':<14}{'n':>7}{'win%':>8}{'avg$':>10}{'total$':>12}  reliability")
    print("-" * 84)
    for lo, hi in BUCKETS:
        a = agg.get((lo, hi))
        if not a or a["n"] == 0:
            print(f"{lo:.2f}-{hi:.2f}   {'(none)':>7}")
            continue
        decided = a["win"] + a["loss"]
        wr = (a["win"] / decided) if decided else 0.0
        avg = a["pnl"] / a["n"]
        mid = (lo + hi) / 2
        # reliability: realized win-rate vs bucket midpoint
        flag = "≈calibrated" if abs(wr - mid) < 0.08 else ("OVER-confident" if wr < mid else "UNDER-confident")
        print(f"{lo:.2f}-{hi:.2f}   {a['n']:>7}{wr*100:>7.1f}%{avg:>10.2f}{a['pnl']:>12.0f}  {flag}")

    # Realized reward:risk and true breakeven
    import statistics
    avg_win = statistics.mean(all_win_pnl) if all_win_pnl else 0.0
    avg_loss = statistics.mean(all_loss_pnl) if all_loss_pnl else 0.0
    print("\n" + "-" * 84)
    print(f"Realized avg WIN  $: {avg_win:8.2f}  (n={len(all_win_pnl)})")
    print(f"Realized avg LOSS $: {avg_loss:8.2f}  (n={len(all_loss_pnl)})")
    if avg_loss != 0:
        rr = abs(avg_win / avg_loss)
        breakeven = 1.0 / (1.0 + rr)
        print(f"Realized reward:risk = {rr:.2f} : 1   →  TRUE breakeven win-rate = {breakeven*100:.1f}%")
        print(f"  (NOT the assumed 2:1 / 33.3%. Use THIS to judge the skipped band.)")

    # Lowest traded band verdict
    lowest = agg.get((0.50, 0.55))
    if lowest and (lowest["win"] + lowest["loss"]) > 0 and avg_loss != 0:
        decided = lowest["win"] + lowest["loss"]
        wr = lowest["win"] / decided
        print(f"\nLowest TRADED band 0.50-0.55: win-rate {wr*100:.1f}%, avg ${lowest['pnl']/lowest['n']:.2f}/trade")
        if wr > breakeven + 0.03 and lowest["pnl"] > 0:
            print("  → comfortably profitable. The 0.45-0.50 band is PLAUSIBLY still positive —")
            print("    relaxing the cut toward ~0.45 is worth a guarded test.")
        elif lowest["pnl"] <= 0 or wr < breakeven:
            print("  → already marginal/negative. KEEP the 0.50 cut; do NOT relax it.")
        else:
            print("  → borderline. Relax only with tight risk + monitoring.")

    print("\nTop setups by trade count (executed, p_win>=0.50):")
    for st, d in sorted(per_setup.items(), key=lambda kv: -kv[1]["n"])[:10]:
        wr = (d["win"] / d["n"] * 100) if d["n"] else 0
        print(f"  {st:<24} n={d['n']:>5}  win%={wr:5.1f}  total$={d['pnl']:.0f}")

# How many are being force-skipped (context)
skip_meta = db.confidence_gate_log.count_documents({
    "decision": "SKIP",
    "ensemble_meta_signal.p_win": {"$lt": 0.50, "$ne": None},
})
print(f"\nFor context: {skip_meta:,} logged SKIPs had meta p_win<0.50 (force-skipped, never traded).")
print("\nDONE — paste this whole block back.")
