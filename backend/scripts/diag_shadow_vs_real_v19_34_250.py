#!/usr/bin/env python3
"""
v19.34.250 — SHADOW-vs-REAL FORENSIC (READ-ONLY) — Issue #2 / the "18pt gap".

The ShadowVsRealTile shows shadow_wr − real_wr, but they measure DIFFERENT
universes: shadow_wr = would_have_pnl>0 over ALL tracked decisions (idealized,
hold-to-outcome); real_wr = realized_pnl>0 over the bot's EXECUTED trades
(actually managed, early exits/EOD/stops). This script separates a real edge gap
from a measurement artifact by:

  1. Re-deriving both headline win-rates (shadow tracked vs real executed).
  2. APPLES-TO-APPLES: join shadow decisions flagged was_executed to the real
     trade_outcomes (symbol + entry-time proximity) and compare would_have_r vs
     actual_r on the SAME trades → that delta IS the execution erosion.
  3. recommendation mix + confidence, so we see if "proceed-only" skews shadow_wr.

Run on DGX:
    .venv/bin/python backend/scripts/diag_shadow_vs_real_v19_34_250.py --days 30
"""
import argparse
import os
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient  # noqa: E402

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[os.environ.get("DB_NAME", "tradecommand")]
db.client.admin.command("ping")
print(f"[db] {mongo_url}")

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=30)
args = ap.parse_args()
cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(ts):
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


sd = list(db["shadow_decisions"].find(
    {"$or": [{"timestamp": {"$gte": cutoff}}, {"created_at": {"$gte": cutoff}}]},
    {"_id": 0, "symbol": 1, "timestamp": 1, "created_at": 1, "was_executed": 1,
     "outcome_tracked": 1, "would_have_pnl": 1, "would_have_r": 1,
     "combined_recommendation": 1, "confidence_score": 1}))

print(f"\n{'='*70}\nSHADOW vs REAL — {len(sd)} decisions, last {args.days}d\n{'='*70}")

tracked = [d for d in sd if d.get("outcome_tracked")]
executed = [d for d in sd if d.get("was_executed")]
shadow_wins = [d for d in tracked if (_f(d.get("would_have_pnl")) or 0) > 0]
shadow_wr = 100 * len(shadow_wins) / len(tracked) if tracked else None
print(f"\n  SHADOW: total={len(sd)} tracked={len(tracked)} executed={len(executed)}")
print(f"  shadow win% (would_have_pnl>0 over tracked) = "
      f"{shadow_wr:.1f}%" if shadow_wr is not None else "  shadow win% = —")
print(f"  recommendation mix: {dict(Counter(d.get('combined_recommendation','?') for d in sd).most_common(6))}")

# real win-rate from the now-complete trade_outcomes
to = list(db["trade_outcomes"].find(
    {"created_at": {"$gte": cutoff}}, {"_id": 0, "symbol": 1, "entry_time": 1,
     "actual_r": 1, "outcome": 1, "pnl": 1}))
real_wins = [t for t in to if t.get("outcome") == "won" or (_f(t.get("pnl")) or 0) > 0]
real_wr = 100 * len(real_wins) / len(to) if to else None
print(f"\n  REAL: trade_outcomes={len(to)}  real win% = "
      f"{real_wr:.1f}%" if real_wr is not None else "  real win% = —")
if shadow_wr is not None and real_wr is not None:
    print(f"\n  HEADLINE GAP (shadow − real) = {shadow_wr - real_wr:+.1f}pp  "
          f"← but mixed universes; see apples-to-apples below")

# ── apples-to-apples: executed shadow ↔ real trade_outcomes ─────────
print(f"\n  {'─'*60}\n  APPLES-TO-APPLES (executed shadow decisions ↔ real outcomes)\n  {'─'*60}")
# index trade_outcomes by symbol → [(entry_dt, actual_r)]
idx = {}
for t in to:
    idx.setdefault(t.get("symbol"), []).append((_dt(t.get("entry_time")), _f(t.get("actual_r"))))

paired = []
for d in executed:
    sym = d.get("symbol")
    sdt = _dt(d.get("timestamp") or d.get("created_at"))
    wr_r = _f(d.get("would_have_r"))
    if not sym or sdt is None or wr_r is None or sym not in idx:
        continue
    # nearest real outcome within 1 day
    best = None
    for (edt, ar) in idx[sym]:
        if edt is None or ar is None:
            continue
        gap = abs((edt - sdt).total_seconds())
        if gap < 86400 and (best is None or gap < best[0]):
            best = (gap, ar)
    if best:
        paired.append((sym, wr_r, best[1]))

if paired:
    would = [p[1] for p in paired]
    actual = [p[2] for p in paired]
    would_win = 100 * sum(1 for x in would if x > 0) / len(would)
    actual_win = 100 * sum(1 for x in actual if x > 0) / len(actual)
    print(f"  matched pairs = {len(paired)}")
    print(f"  would_have_r  mean={statistics.mean(would):+.2f}R  win%={would_win:.0f}%")
    print(f"  actual_r      mean={statistics.mean(actual):+.2f}R  win%={actual_win:.0f}%")
    print(f"  EXECUTION EROSION (would − actual) = {statistics.mean(would)-statistics.mean(actual):+.2f}R/trade")
    print("  → if would≈actual, the headline gap is a MEASUREMENT artifact")
    print("    (shadow idealized exits vs real managed exits), not lost edge.")
    print("  worst erosion (symbol, would_r, actual_r):")
    for p in sorted(paired, key=lambda x: x[2] - x[1])[:10]:
        print(f"      {str(p[0]):<8} would={p[1]:+.2f}R  actual={p[2]:+.2f}R")
else:
    print("  no executed-shadow ↔ real matches in window (check was_executed flag / timing)")

print("\nDone. (read-only)\n")
