#!/usr/bin/env python3
"""
rebuild_strategy_stats_v284.py — Stat Hygiene / Win-rate Pollution rebuild.

WHY
  `strategy_stats` (the TQS Setup-pillar EV + real-win-rate feed that drives the
  Smart Filter) was polluted by reconciliation/phantom ARTIFACT rows:
    - reconciled_orphan, reconciled_excess_slice, *_sweep, phantom_* closes.
  These were tagged genuine=False from v240 onward, but LEGACY alert_outcomes rows
  written before v240 have NO `genuine` field, so the recompute defaulted them to
  genuine=True and they kept dragging win-rates / EV down → Smart Filter over-gated.

WHAT IT DOES  (idempotent, DRY-RUN by default)
  1. BACKFILL: stamps genuine=False + hygiene_tag on every legacy alert_outcomes
     row whose setup_type / close_reason decodes to a reconciliation/phantom
     artifact (same substrings as services.trade_outcome_hygiene). Rows already
     flagged genuine=False are left untouched.
  2. RECOMPUTE: rebuilds strategy_stats whole-trade from alert_outcomes for EVERY
     setup family via the canonical pnl_compute.recompute_strategy_stats_for_setup
     (genuine_only=True). 0-PnL scratches are correctly excluded (neither win nor
     loss), fixing the old bot_trades-based "0 PnL counted as a loss" bug.

USAGE
  .venv/bin/python backend/scripts/rebuild_strategy_stats_v284.py            # DRY RUN
  .venv/bin/python backend/scripts/rebuild_strategy_stats_v284.py --commit   # WRITE
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db_name = os.environ.get("DB_NAME", "tradecommand")
db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]
db.client.admin.command("ping")
print(f"[db] {mongo_url} / {db_name}")

from services import pnl_compute  # noqa: E402
from services.pnl_compute import _base_setup, _is_reconciliation_artifact  # noqa: E402

# Point the canonical recompute writer at THIS db (it lazily inits its own client
# against the same env, but make the binding explicit for the rebuild run).
pnl_compute._get_outcomes_collection()
pnl_compute._AO_DB = db

ap = argparse.ArgumentParser()
ap.add_argument("--commit", action="store_true")
args = ap.parse_args()

ao = db["alert_outcomes"]
ss = db["strategy_stats"]


def ev_table(tag):
    print(f"\n  strategy_stats EV snapshot [{tag}]:")
    print(f"  {'setup':<26}{'trig':>5}{'won':>5}{'win%':>6}{'EV_r':>8}")
    for d in ss.find({}, {"_id": 0}).sort("alerts_triggered", -1).limit(20):
        wr = (d.get("win_rate") or 0) * 100
        print(f"  {str(d.get('setup_type'))[:26]:<26}{d.get('alerts_triggered', 0):>5}"
              f"{d.get('alerts_won', 0):>5}{wr:>5.0f}%{d.get('expected_value_r', 0):>8.2f}")


# ── STEP 1: identify legacy artifact rows ──────────────────────────────────
artifact_ids = []
for d in ao.find({}, {"_id": 1, "setup_type": 1, "close_reason": 1, "genuine": 1}):
    if d.get("genuine") is False:
        continue  # already correctly flagged
    if _is_reconciliation_artifact(d.get("setup_type"), d.get("close_reason")):
        artifact_ids.append(d["_id"])

total_ao = ao.count_documents({})
already_flagged = ao.count_documents({"genuine": False})
print(f"\nBEFORE  alert_outcomes={total_ao}  already_flagged_artifacts={already_flagged}"
      f"  legacy_artifacts_to_fix={len(artifact_ids)}")
ev_table("before")

# ── STEP 2: backfill genuine=False on legacy artifact rows ─────────────────
if artifact_ids:
    if args.commit:
        res = ao.update_many(
            {"_id": {"$in": artifact_ids}},
            {"$set": {"genuine": False, "hygiene_tag": "rebuild_v284_legacy_artifact"}},
        )
        print(f"\n[step1] flagged {res.modified_count} legacy artifact rows genuine=False")
    else:
        print(f"\n[step1] WOULD flag {len(artifact_ids)} legacy artifact rows genuine=False")

# ── STEP 3: recompute strategy_stats for every setup family ────────────────
bases = sorted({_base_setup(s) for s in ao.distinct("setup_type") if _base_setup(s)})
print(f"\n[step2] {len(bases)} setup families to recompute: {bases}")

if args.commit:
    recomputed = 0
    for b in bases:
        doc = pnl_compute.recompute_strategy_stats_for_setup(b, genuine_only=True)
        if doc is not None:
            recomputed += 1
    print(f"[step2] recomputed {recomputed}/{len(bases)} families")
    ev_table("after")
    print("\n✅ COMMITTED. Restart backend so TQS reloads strategy_stats.")
else:
    # Dry-run preview: compute (in-memory) without writing by reading current state.
    print("\nDRY RUN — nothing written. Re-run with --commit to apply.")
