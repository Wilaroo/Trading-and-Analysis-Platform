#!/usr/bin/env python3
"""
diag_expectancy_clean.py  (READ-ONLY)
=====================================
Resolves the $-vs-R contradiction in closed bot_trades by computing a CLEAN
R-multiple for EVERY closed trade as:

      clean_R = realized_pnl / risk_amount      (when risk_amount > 0)

instead of relying on the sparse/corrupt stored `r_multiple` (only 211/1522,
median 0, mean -2.35 from outliers). Also separates REAL strategy trades from
reconciliation artifacts (reconciled_orphan / reconciled_excess_slice /
synthetic_source), which distort both $ and R.

Reports:
  A. risk_amount sanity — how many closed trades have valid vs corrupt risk.
  B. Portfolio expectancy (clean R) — all closed, and "real only" (artifacts removed).
  C. Per-setup clean expectancy: n, win%, mean R, median R, total $, $/risk.
     Flags statistically-meaningful bleeders (n>=20 and mean_R < -0.1).
  D. Concentration check — top setups by |PnL| to expose size-driven distortion.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_expectancy_clean.py
"""
import os
import statistics
from collections import defaultdict

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def fnum(v):
    try:
        f = float(v)
        return f if f == f else None  # NaN guard
    except Exception:
        return None


ARTIFACT_SETUPS = {"reconciled_orphan", "reconciled_excess_slice"}

rows = list(db.bot_trades.find(
    {"status": "closed"},
    {"_id": 0, "realized_pnl": 1, "risk_amount": 1, "setup_type": 1,
     "direction": 1, "synthetic_source": 1, "shares": 1, "quality_score": 1,
     "tqs_score": 1, "market_regime": 1},
))
print("=" * 82)
print(f"CLEAN EXPECTANCY — {len(rows):,} closed trades")
print("=" * 82)

# A. risk_amount sanity
valid_risk = bad_risk = 0
for r in rows:
    ra = fnum(r.get("risk_amount"))
    if ra is not None and ra > 0:
        valid_risk += 1
    else:
        bad_risk += 1
print(f"\nA. risk_amount: valid(>0)={valid_risk}  missing/<=0={bad_risk}")
print("   (clean_R can only be computed on the valid ones)")


def summarize(label, subset):
    pnls = [fnum(r.get("realized_pnl")) or 0.0 for r in subset]
    rs = []
    won = lost = 0
    for r in subset:
        ra = fnum(r.get("risk_amount"))
        pnl = fnum(r.get("realized_pnl"))
        if pnl is None:
            continue
        if pnl > 0:
            won += 1
        elif pnl < 0:
            lost += 1
        if ra and ra > 0:
            cr = pnl / ra
            # clamp absurd outliers (corrupt risk) for the trimmed mean
            if -10 <= cr <= 10:
                rs.append(cr)
    total = sum(pnls)
    dec = won + lost
    print(f"\n{label}:")
    print(f"  n={len(subset)}  total $={total:,.0f}  avg $/trade={total/max(len(subset),1):,.1f}")
    print(f"  win-rate={won/max(dec,1)*100:.1f}%  (won={won} lost={lost})")
    if rs:
        print(f"  clean_R (|R|<=10, n={len(rs)}): mean={statistics.mean(rs):+.3f}  "
              f"median={statistics.median(rs):+.3f}")
        pos = sum(1 for x in rs if x > 0)
        print(f"  → expectancy {'+POSITIVE' if statistics.mean(rs) > 0 else '-NEGATIVE'} per unit risk")


# B. Portfolio expectancy
summarize("B1. ALL closed", rows)
real = [r for r in rows
        if str(r.get("setup_type", "")) not in ARTIFACT_SETUPS
        and not r.get("synthetic_source")]
summarize("B2. REAL strategy trades (artifacts removed)", real)

# C. Per-setup clean expectancy (real only)
print("\n" + "=" * 82)
print("C. PER-SETUP clean expectancy (real strategy trades)")
print("=" * 82)
per = defaultdict(lambda: {"n": 0, "won": 0, "lost": 0, "pnl": 0.0, "r": []})
for r in real:
    st = str(r.get("setup_type", "?"))
    pnl = fnum(r.get("realized_pnl"))
    ra = fnum(r.get("risk_amount"))
    d = per[st]
    d["n"] += 1
    if pnl is not None:
        d["pnl"] += pnl
        if pnl > 0:
            d["won"] += 1
        elif pnl < 0:
            d["lost"] += 1
        if ra and ra > 0 and -10 <= pnl / ra <= 10:
            d["r"].append(pnl / ra)

print(f"\n{'setup':<24}{'n':>5}{'win%':>7}{'meanR':>8}{'medR':>8}{'total$':>11}")
print("-" * 70)
bleeders = []
for st, d in sorted(per.items(), key=lambda kv: kv[1]["pnl"]):
    dec = d["won"] + d["lost"]
    wr = d["won"] / dec * 100 if dec else 0
    mr = statistics.mean(d["r"]) if d["r"] else 0.0
    md = statistics.median(d["r"]) if d["r"] else 0.0
    flag = "🔴" if (d["n"] >= 20 and mr < -0.10) else ("🟢" if mr > 0.10 else "⚪")
    print(f"{flag}{st:<23}{d['n']:>5}{wr:>6.1f}%{mr:>+8.3f}{md:>+8.3f}{d['pnl']:>11.0f}")
    if d["n"] >= 20 and mr < -0.10:
        bleeders.append((st, d["n"], mr, d["pnl"]))

# D. Concentration
print("\n" + "=" * 82)
print("D. CONCENTRATION — top 8 setups by |total $| (exposes size-driven distortion)")
print("=" * 82)
for st, d in sorted(per.items(), key=lambda kv: -abs(kv[1]["pnl"]))[:8]:
    mr = statistics.mean(d["r"]) if d["r"] else 0.0
    print(f"  {st:<24} total$={d['pnl']:>11.0f}   meanR={mr:+.3f}   n={d['n']}")

print("\n" + "=" * 82)
print("VERDICT")
print("=" * 82)
if bleeders:
    print("Statistically meaningful BLEEDERS (n>=20, meanR < -0.10) — candidates to")
    print("disable or fix first:")
    for st, n, mr, pnl in sorted(bleeders, key=lambda x: x[2]):
        print(f"  🔴 {st:<22} n={n:>4}  meanR={mr:+.3f}  total$={pnl:,.0f}")
else:
    print("  No setup meets the bleeder bar (n>=20 & meanR<-0.10) on clean R.")
print("\nDONE — paste this whole block back.")
