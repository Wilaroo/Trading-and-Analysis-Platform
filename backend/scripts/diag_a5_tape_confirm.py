#!/usr/bin/env python3
"""A5 READ-ONLY — why is tape_confirmation 0/N for HIGH/CRITICAL alerts?

The intraday auto-execute gate hard-requires alert.tape_confirmation, set from
_get_tape_reading: confirmation_for_long = tape_score >= 0.2 (short <= -0.2), where
  tape_score = spread(+0.2 tight / -0.2 wide / 0 neutral)
             + imbalance * 0.4          (L2 imbalance if available, else bid/ask sizes)
             + momentum(+0.3 up / -0.3 down / 0)   (momentum needs rvol >= 2.0)
With level2_symbols=0 the imbalance term is whatever the quote bid/ask sizes give
(often 0), so confirmation hinges on a TIGHT spread (+0.2) or strong momentum.

This script reads PERSISTED alert tape fields (tape_signals = [spread, imbalance,
momentum] enum values, tape_confirmation, tape_score normalized 0..10, rvol, direction)
for recent HIGH/CRITICAL scored alerts and shows EXACTLY which signal is killing
confirmation + how many alerts each candidate lever would recover. WRITES NOTHING.

Usage (DGX, repo root):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_a5_tape_confirm.py --days 1
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import Counter

for _l in open("backend/.env"):
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.strip().split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient

a = sys.argv
days = float(a[a.index("--days") + 1]) if "--days" in a else 1
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
pct = lambda n, d: f"{100.0 * n / d:.1f}%" if d else "n/a"
since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

cur = db.live_alerts.find(
    {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0},
     "priority": {"$in": ["high", "critical", "HIGH", "CRITICAL"]}},
    {"_id": 0, "symbol": 1, "direction": 1, "priority": 1, "tape_confirmation": 1,
     "tape_score": 1, "tape_signals": 1, "rvol": 1, "setup_type": 1, "created_at": 1})

N = 0
conf = 0
spread_c, imb_c, mom_c = Counter(), Counter(), Counter()
all_neutral = 0
raw_hist = Counter()
rvol_ge2 = 0
recover_if_tight = 0     # not confirmed long, but raw+0.2 (tight spread) would reach 0.2
recover_if_mom = 0       # not confirmed long, but raw+0.3 (momentum) would reach 0.2
by_dir = Counter()
samples = []

for d in cur:
    N += 1
    sig = d.get("tape_signals") or []
    sp = sig[0] if len(sig) > 0 else "?"
    im = sig[1] if len(sig) > 1 else "?"
    mo = sig[2] if len(sig) > 2 else "?"
    spread_c[sp] += 1
    imb_c[im] += 1
    mom_c[mo] += 1
    if sp == "neutral" and im == "neutral" and mo == "neutral":
        all_neutral += 1
    tc = bool(d.get("tape_confirmation"))
    conf += 1 if tc else 0
    by_dir[(d.get("direction"), tc)] += 1
    rv = float(d.get("rvol", 0.0) or 0.0)
    if rv >= 2.0:
        rvol_ge2 += 1
    # back out raw tape_score from normalized 0..10:  raw = norm/5 - 1
    norm = d.get("tape_score")
    raw = (float(norm) / 5.0 - 1.0) if isinstance(norm, (int, float)) else None
    if raw is not None:
        raw_hist[round(raw, 1)] += 1
        if not tc and d.get("direction") == "long":
            if sp != "tight_spread" and (raw + 0.2) >= 0.2:
                recover_if_tight += 1
            if (raw + 0.3) >= 0.2:
                recover_if_mom += 1
    if not tc and len(samples) < 12:
        samples.append((d.get("symbol"), d.get("direction"), d.get("setup_type"),
                        round(raw, 2) if raw is not None else None, sp, im, mo, round(rv, 1)))

print(f"== A5 tape-confirmation audit · last {days:g}d (since {since}) ==\n")
print(f"HIGH/CRITICAL scored alerts: {N}")
print(f"  tape_confirmation TRUE:  {conf}/{N}  ({pct(conf, N)})")
print(f"  tape_confirmation FALSE: {N-conf}/{N}  ({pct(N-conf, N)})")
print(f"  ALL THREE signals neutral: {all_neutral}/{N}  ({pct(all_neutral, N)})")
print(f"  rvol >= 2.0 (momentum-eligible): {rvol_ge2}/{N}  ({pct(rvol_ge2, N)})")
print()
print("SPREAD signal:   " + " · ".join(f"{k}={v}" for k, v in spread_c.most_common()))
print("IMBALANCE signal:" + " · ".join(f" {k}={v}" for k, v in imb_c.most_common()))
print("MOMENTUM signal: " + " · ".join(f"{k}={v}" for k, v in mom_c.most_common()))
print()
print("raw tape_score histogram (gate needs |raw| >= 0.2):")
for k in sorted(raw_hist):
    bar = "#" * min(60, raw_hist[k])
    print(f"  {k:>5.1f}  {raw_hist[k]:>5}  {bar}")
print()
print("PROJECTED lever impact (longs only, currently unconfirmed):")
print(f"  would confirm if spread read TIGHT (+0.2): {recover_if_tight}")
print(f"  would confirm if momentum fired   (+0.3): {recover_if_mom}")
print()
print("dir/confirm split: " + " · ".join(f"{k[0]}/{'conf' if k[1] else 'no'}={v}" for k, v in by_dir.most_common()))
print()
print("sample unconfirmed alerts (symbol, dir, setup, raw_tape, spread, imb, mom, rvol):")
for s in samples:
    print("  ", s)
