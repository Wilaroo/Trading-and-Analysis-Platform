#!/usr/bin/env python3
"""A4b READ-ONLY — quantify the "<5-sample EV suppression" slice (Option B scoping).

pnl_compute.recompute_strategy_stats_for_setup line ~518 sets:
    ev = avg_rr if n_all >= 5 else 0.0
so any setup with 1-4 GRADED R-outcomes has its expected_value_r FORCED to 0.0
(reads 'No data' on the Setup pillar). This script measures EXACTLY how many recent
unstamped alerts sit on setups with 1-4 graded R-outcomes (the only slice that
lowering the gate could recover), what real EV they'd get, and crucially the
SIGN of that EV (stamping a negative EV LOWERS the Setup pillar — may be undesirable).

Reuses pnl_compute's own _base_setup / _classify_outcome / _is_reconciliation_artifact
so the per-setup R-sample matches what the live recompute produces byte-for-byte.
WRITES NOTHING. Reads project {"_id": 0} where applicable.

Usage (DGX, repo root):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_a4b_ev_sample_sizes.py --days 5
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

for _l in open("backend/.env"):
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.strip().split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient
from services.pnl_compute import (
    _base_setup, _classify_outcome, _is_reconciliation_artifact,
)

a = sys.argv
days = float(a[a.index("--days") + 1]) if "--days" in a else 5
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
pct = lambda n, d: f"{100.0 * n / d:.1f}%" if d else "n/a"
since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

# ---------------------------------------------------------------- per-base R sample
# Mirror recompute_strategy_stats_for_setup's genuine filter + classification.
rows = list(db.alert_outcomes.find(
    {}, {"_id": 1, "setup_type": 1, "outcome": 1, "r_multiple": 1,
         "net_pnl": 1, "pnl": 1, "closed_at": 1, "genuine": 1,
         "close_reason": 1, "r_risk_unreliable": 1}))

r_by_base = defaultdict(list)   # base -> list of graded R-multiples (the EV sample)
trig_by_base = Counter()
for d in rows:
    if d.get("genuine", True) is False:
        continue
    if d.get("r_risk_unreliable") is True:
        continue
    if _is_reconciliation_artifact(d.get("setup_type"), d.get("close_reason")):
        continue
    base = _base_setup(d.get("setup_type"))
    if not base:
        continue
    r = d.get("r_multiple")
    r = float(r) if isinstance(r, (int, float)) else None
    pnl_v = d.get("net_pnl")
    if pnl_v is None:
        pnl_v = d.get("pnl")
    pnl_v = float(pnl_v) if isinstance(pnl_v, (int, float)) else 0.0
    cls = _classify_outcome(d.get("outcome"), r, pnl_v)
    if cls is None:
        continue
    trig_by_base[base] += 1
    if r is not None:
        r_by_base[base].append(r)

def n_of(base):
    return len(r_by_base.get(base, []))

def ev_of(base):
    rs = r_by_base.get(base, [])
    return (sum(rs) / len(rs)) if rs else None

print(f"== A4b EV sample-size audit · last {days:g}d (since {since}) · gate=n_all>=5 ==\n")
print(f"alert_outcomes rows scanned: {len(rows)}")
print(f"distinct setup families with >=1 graded R-outcome: {len(r_by_base)}")
size_hist = Counter()
for b in r_by_base:
    n = n_of(b)
    size_hist["5+" if n >= 5 else ("3-4" if n >= 3 else ("1-2" if n >= 1 else "0"))] += 1
print(f"  family R-sample-size histogram: "
      + " · ".join(f"{k}:{size_hist[k]}" for k in ("1-2", "3-4", "5+") if size_hist[k]))
print()

# ---------------------------------------------------------------- recent unstamped alerts
cur = db.live_alerts.find(
    {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0},
     "$or": [{"strategy_ev_r": 0}, {"strategy_ev_r": 0.0}, {"strategy_ev_r": {"$exists": False}}]},
    {"_id": 0, "setup_type": 1})

# bucket each UNSTAMPED alert by the R-sample-size of its base
buck = Counter()                 # '0' | '1-2' | '3-4' | '5+_zeroEV'
gain_pos = Counter()             # threshold -> alerts that'd gain a POSITIVE ev
gain_neg = Counter()             # threshold -> alerts that'd gain a NEGATIVE ev
per_base_unstamped = Counter()
N_unstamped = 0
for doc in cur:
    N_unstamped += 1
    base = _base_setup(doc.get("setup_type"))
    per_base_unstamped[base] += 1
    n = n_of(base)
    ev = ev_of(base)
    if n == 0:
        buck["0 (NO graded R — proxy is the only honest read)"] += 1
    elif n >= 5:
        # already n>=5 so a 0 EV here is a GENUINE ~0 realized edge
        buck["5+ but EV~0 (genuine flat edge — proxy correct)"] += 1
    else:
        buck[f"{'3-4' if n >= 3 else '1-2'} samples (SUPPRESSED by gate)"] += 1
        for thr in (1, 2, 3, 4):
            if n >= thr:
                (gain_pos if (ev or 0) > 0 else gain_neg)[thr] += 1

print(f"recent UNSTAMPED scored alerts (strategy_ev_r==0): {N_unstamped}\n")
print("bucketed by their setup family's graded R-sample size:")
for k, v in buck.most_common():
    print(f"  {v:6d}  ({pct(v, N_unstamped)})  {k}")
print()

print("IF the n_all>=5 gate were lowered to >=THR, unstamped alerts that would gain a REAL EV:")
print(f"  {'THR':>4}  {'+EV alerts':>10}  {'-EV alerts':>10}   (note: -EV stamping LOWERS the Setup pillar)")
for thr in (3, 2, 1):
    print(f"  {thr:>4}  {gain_pos[thr]:>10}  {gain_neg[thr]:>10}")
print()

# per-base detail for the suppressed (1-4 sample) families that actually appear in the window
suppressed_bases = sorted(
    (b for b in per_base_unstamped if 1 <= n_of(b) <= 4),
    key=lambda b: -per_base_unstamped[b])
if suppressed_bases:
    print("Suppressed families present in the window (1-4 samples — the Option-B target):")
    print(f"  {'unstamped':>9}  {'n_R':>4}  {'real EV':>8}  setup_family")
    for b in suppressed_bases:
        print(f"  {per_base_unstamped[b]:>9}  {n_of(b):>4}  {ev_of(b):>+8.2f}  {b}")
else:
    print("No 1-4 sample families appear among unstamped alerts in the window —")
    print("=> lowering the gate would recover ~0. Option B is a no-op; prefer Option A.")
