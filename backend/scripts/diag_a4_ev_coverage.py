#!/usr/bin/env python3
"""A4 READ-ONLY EV-stamping COVERAGE audit — "why is the Setup pillar's Expected-Value
sub-score 'No data' for ~43% of scored alerts, and how much of that is RECOVERABLE?"

Causal chain (verified in code):
  enhanced_scanner._stamp_strategy_metrics stamps alert.strategy_ev_r from
  _strategy_stats[ crude(setup_type) ]  where crude = split('_long')[0].split('_short')[0].
  The enrich path passes (strategy_ev_r or None) into tqs_engine -> setup_quality;
  a 0.0 / missing EV => has_ev_data=False => ev_is_proxy=True => the 'Expected Value'
  sub-score display.verdict == 'No data' (the exact thing GET /api/tqs/coverage counts).

Hypothesis: _strategy_stats / the strategy_stats collection is keyed by the SSOT
CANONICAL setup name (setup_taxonomy.canonicalize), but the stamping uses the CRUDE
split — so aliased / suffixed setups (tidal_wave->fading_bounce, *_confirmed, *_scalp,
etc.) MISS the bucket that actually holds EV, get lazily cold-started at EV 0.0, and
the EV sub-score reads 'No data' even though a real EV exists under the canonical key.

This script PROVES or DISPROVES that on live data and quantifies the recoverable %.
It WRITES NOTHING. All reads project {"_id": 0}.

Usage (DGX, repo root):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_a4_ev_coverage.py --days 5
Optional: --grace 20   (cold-start outcome floor; default mirrors _win_rate_grace_min_trades)
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
from services.setup_taxonomy import canonicalize

a = sys.argv
days = float(a[a.index("--days") + 1]) if "--days" in a else 5
GRACE = int(a[a.index("--grace") + 1]) if "--grace" in a else 20
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
pct = lambda n, d: f"{100.0 * n / d:.1f}%" if d else "n/a"
since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def crude(s):
    return str(s or "").split("_long")[0].split("_short")[0]


# ---------------------------------------------------------------- strategy_stats
stats = {}
for d in db.strategy_stats.find({}, {"_id": 0}):
    st = d.get("setup_type")
    if not st:
        continue
    stats[st] = {
        "ev": float(d.get("expected_value_r", 0.0) or 0.0),
        "trig": int(d.get("alerts_triggered", 0) or 0),
        "nout": len(d.get("r_outcomes", []) or []),
        "wr": float(d.get("win_rate", 0.0) or 0.0),
    }

print(f"== A4 EV-stamping coverage audit · last {days:g}d (since {since}) · grace={GRACE} ==\n")
print(f"strategy_stats collection: {len(stats)} rows")
noncanon = sorted(k for k in stats if canonicalize(k) != k)
print(f"  rows whose key != canonicalize(key): {len(noncanon)}"
      + (f"   e.g. {noncanon[:10]}" if noncanon else "   (all keys already canonical)"))
ev_rows = sorted(k for k, v in stats.items() if v["ev"] != 0.0)
print(f"  rows with NON-ZERO expected_value_r: {len(ev_rows)}/{len(stats)}"
      + (f"   {[ (k, round(stats[k]['ev'],2)) for k in ev_rows[:12] ]}" if ev_rows else ""))
print()


def ev_of(key):
    r = stats.get(key)
    return r["ev"] if r else 0.0


# ---------------------------------------------------------------- recent alerts
cur = db.live_alerts.find(
    {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}},
    {"_id": 0, "setup_type": 1, "canonical_setup": 1, "strategy_ev_r": 1,
     "risk_reward": 1, "tqs_breakdown": 1},
)

N = 0
stamped = 0                      # strategy_ev_r != 0 on the alert
ev_nodata = 0                    # live display verdict == 'No data' (the coverage metric)
ev_have_display = 0
causes = Counter()               # attribution of UNSTAMPED (strategy_ev_r == 0) alerts
recoverable_pairs = Counter()    # (raw_setup -> canonical) that would be recovered by canon lookup
nodata_but_recoverable = 0       # alerts whose live verdict is 'No data' AND canon bucket has EV

for doc in cur:
    N += 1
    raw = doc.get("setup_type") or ""
    cn = doc.get("canonical_setup") or canonicalize(raw)
    cb = crude(raw)
    ev_alert = float(doc.get("strategy_ev_r", 0.0) or 0.0)
    rr = doc.get("risk_reward")

    # live coverage signal straight off the persisted breakdown
    verdict = None
    bd = doc.get("tqs_breakdown") or {}
    setp = bd.get("setup") if isinstance(bd, dict) else None
    disp = setp.get("display") if isinstance(setp, dict) else None
    blk = disp.get("expected_value") if isinstance(disp, dict) else None
    if isinstance(blk, dict):
        ev_have_display += 1
        verdict = blk.get("verdict")
        if verdict == "No data":
            ev_nodata += 1

    if ev_alert != 0.0:
        stamped += 1
        continue

    # ---- attribute the UNSTAMPED alert ----
    cb_ev, cn_ev = ev_of(cb), ev_of(cn)
    cn_row = stats.get(cn)
    if cn_ev != 0.0 and cb_ev == 0.0:
        causes["RECOVERABLE_CANON (canon bucket HAS EV, crude misses)"] += 1
        recoverable_pairs[f"{raw}  ->  {cn}  (EV {cn_ev:+.2f}R)"] += 1
        if verdict == "No data":
            nodata_but_recoverable += 1
    elif cb_ev != 0.0:
        causes["ANOMALY (crude bucket has EV but alert unstamped)"] += 1
    elif cn_row and cn_row["nout"] > 0:
        causes["GENUINE_ZERO_EV (canon has graded outcomes, EV computes ~0 -> proxy correct)"] += 1
    elif cn_row and cn_row["trig"] > 0:
        causes["TRIGGERED_NO_GRADED (fired but 0 graded R outcomes yet)"] += 1
    elif cn_row:
        causes["COLD_START (canon row exists, no outcomes)"] += 1
    else:
        causes["NO_STATS_ROW (no crude or canon row at all)"] += 1

unstamped = N - stamped
print(f"scored alerts in window (tqs_score>0): {N}")
print(f"  strategy_ev_r STAMPED (non-zero): {stamped}/{N}  ({pct(stamped, N)})")
print(f"  strategy_ev_r UNSTAMPED (==0):    {unstamped}/{N}  ({pct(unstamped, N)})")
print()
print(f"LIVE coverage metric (persisted tqs_breakdown.setup.display.expected_value):")
print(f"  alerts carrying the EV display block: {ev_have_display}/{N}")
print(f"  EV verdict == 'No data':              {ev_nodata}/{ev_have_display}"
      f"  -> EV real coverage {pct(ev_have_display - ev_nodata, ev_have_display)}")
print()
print("UNSTAMPED attribution (root cause of strategy_ev_r == 0):")
for cause, n in causes.most_common():
    print(f"  {n:6d}  ({pct(n, unstamped)})  {cause}")
print()

rec_total = sum(n for c, n in causes.items() if c.startswith("RECOVERABLE_CANON"))
print(f"PROJECTED FIX IMPACT (canonical lookup in _stamp_strategy_metrics):")
print(f"  unstamped alerts recoverable via canon lookup: {rec_total}/{unstamped}  ({pct(rec_total, unstamped)})")
print(f"  of those, currently reading 'No data' live:     {nodata_but_recoverable}")
if ev_have_display:
    proj_real = (ev_have_display - ev_nodata) + nodata_but_recoverable
    print(f"  projected EV real-coverage after fix: {pct(ev_have_display - ev_nodata, ev_have_display)}"
          f"  ->  {pct(proj_real, ev_have_display)}")
print()
if recoverable_pairs:
    print("Top recoverable raw->canonical setups (would gain a real EV):")
    for pair, n in recoverable_pairs.most_common(20):
        print(f"  {n:6d}  {pair}")
else:
    print("No RECOVERABLE_CANON pairs found — the 43% is genuine cold-start / zero-EV,")
    print("NOT a canonicalization miss. (Fix would be a no-op; revisit EV warm-fill instead.)")
