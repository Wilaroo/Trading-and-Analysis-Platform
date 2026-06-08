#!/usr/bin/env python3
"""
diag_family_x_regime.py  (READ-ONLY)
====================================
Re-runs the regime-conditioned expectancy using the SYSTEM's OWN taxonomy
(services.setup_taxonomy) instead of an ad-hoc 'fade' grouping — so the result
is aligned with the live SSOT that the scanner/scoring already use.

For every closed trade:
    canonical   = canonicalize(setup_type)
    family      = strategy_family(setup_type)   # continuation/breakout/reversion/reversal/rotation
    cls         = setup_class(setup_type)        # momentum/fade/swing/position
    clean_R     = realized_pnl / risk_amount     (risk_amount>0, |R|<=10)
    regime band = BULL>60 / NEUT46-60 / BEAR<=45  (from stored regime_score)

Then: mean clean_R per (strategy_family × regime_band) and (setup_class × band).
This is the table the regime-aware gate should be calibrated against.

Edge-excluded artifacts (is_edge_excluded) are dropped automatically.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_family_x_regime.py
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
from services.setup_taxonomy import (  # noqa: E402
    canonicalize, strategy_family, setup_class, is_edge_excluded,
)

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def fnum(v):
    try:
        f = float(v)
        return f if f == f else None
    except Exception:
        return None


def band(sc):
    if sc is None:
        return None
    if sc > 60:
        return "BULL>60"
    if sc >= 46:
        return "NEUT"
    return "BEAR<=45"


rows = list(db.bot_trades.find(
    {"status": "closed"},
    {"_id": 0, "realized_pnl": 1, "risk_amount": 1, "setup_type": 1,
     "synthetic_source": 1, "regime_score": 1},
))

fam_band = defaultdict(lambda: defaultdict(list))
cls_band = defaultdict(lambda: defaultdict(list))
fam_setups = defaultdict(set)
excluded = 0
for r in rows:
    raw = r.get("setup_type", "")
    if is_edge_excluded(raw) or r.get("synthetic_source"):
        excluded += 1
        continue
    pnl = fnum(r.get("realized_pnl"))
    ra = fnum(r.get("risk_amount"))
    if pnl is None or not ra or ra <= 0:
        continue
    cr = pnl / ra
    if not (-10 <= cr <= 10):
        continue
    b = band(fnum(r.get("regime_score")))
    if b is None:
        continue
    fam = strategy_family(raw)
    cls = setup_class(raw)
    fam_band[fam][b].append(cr)
    cls_band[cls][b].append(cr)
    fam_setups[fam].add(canonicalize(raw))


def cell(lst):
    return f"n={len(lst):<4}{statistics.mean(lst):+.3f}" if lst else f"{'-':>11}"


BANDS = ["BEAR<=45", "NEUT", "BULL>60"]
print("=" * 80)
print(f"STRATEGY_FAMILY × REGIME BAND (clean mean R)   [edge-excluded dropped: {excluded}]")
print("=" * 80)
print(f"\n{'family':<16}" + "".join(f"{b:>16}" for b in BANDS))
print("-" * 64)
for fam in sorted(fam_band.keys()):
    print(f"{fam:<16}" + "".join(f"{cell(fam_band[fam][b]):>16}" for b in BANDS))

print("\n" + "=" * 80)
print("SETUP_CLASS × REGIME BAND (clean mean R)")
print("=" * 80)
print(f"\n{'class':<16}" + "".join(f"{b:>16}" for b in BANDS))
print("-" * 64)
for cls in sorted(cls_band.keys()):
    print(f"{cls:<16}" + "".join(f"{cell(cls_band[cls][b]):>16}" for b in BANDS))

print("\n" + "=" * 80)
print("Canonical setups per family (so we see exactly what the gate would scope):")
print("=" * 80)
for fam in sorted(fam_setups.keys()):
    print(f"  {fam:<14}: {', '.join(sorted(fam_setups[fam]))}")

print("\nREAD: 'reversion' and 'reversal' are the counter-trend families. If they're")
print("negative under BULL>60 but ok under BEAR, the gate suppresses THESE families")
print("in strong trends — using the live taxonomy, not an ad-hoc 'fade' set.")
print("\nDONE — paste this whole block back.")
