#!/usr/bin/env python3
"""
v19.34.249 — ONE-TIME learning-loop COVERAGE BACKFILL (F1) + canonical
strategy_stats recompute (F3).

Repairs the historical backlog the audit found: closed bot_trades that the
OCA-external sweep / EOD auto-close / operator close-panel / consolidation paths
left out of trade_outcomes + alert_outcomes (~17% coverage). Ingests them via the
reconciler (stored entry-time context, hygiene-aware), then recomputes
strategy_stats whole-trade/genuine for every affected setup.

DEFAULT = DRY RUN (prints before/after coverage + EV table, writes nothing).
  .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py            # preview
  .venv/bin/python backend/scripts/backfill_v19_34_249_learning_coverage.py --commit   # write
  optional: --days N   (default: all-time)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pymongo import MongoClient  # noqa: E402

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db_name = os.environ.get("DB_NAME", "tradecommand")
db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[db_name]
db.client.admin.command("ping")
print(f"[db] {mongo_url} / {db_name}")

# pnl_compute lazily inits its own _AO_DB MongoClient against the same env, so the
# reconciler's downstream writes (alert_outcomes / strategy_stats) land in this DB.
from services import pnl_compute  # noqa: E402
pnl_compute._get_outcomes_collection()

from services.learning_reconciler import reconcile  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--commit", action="store_true")
ap.add_argument("--days", type=int, default=None)
args = ap.parse_args()


def coverage():
    closed = db["bot_trades"].count_documents({"status": {"$in": ["closed", "CLOSED"]}})
    to = db["trade_outcomes"].count_documents({})
    ao = db["alert_outcomes"].count_documents({})
    return closed, to, ao


def ev_table(tag):
    print(f"\n  strategy_stats EV snapshot [{tag}]:")
    print(f"  {'setup':<24}{'trig':>5}{'won':>5}{'win%':>6}{'EV_r':>7}")
    for d in db["strategy_stats"].find({}, {"_id": 0}).sort("alerts_triggered", -1).limit(12):
        wr = (d.get("win_rate") or 0) * 100
        print(f"  {str(d.get('setup_type'))[:24]:<24}{d.get('alerts_triggered', 0):>5}"
              f"{d.get('alerts_won', 0):>5}{wr:>5.0f}%{d.get('expected_value_r', 0):>7.2f}")


c0, t0, a0 = coverage()
print(f"\nBEFORE  closed={c0}  trade_outcomes={t0}  alert_outcomes={a0}")
ev_table("before")

rep = reconcile(db, days=args.days, commit=args.commit, verbose=True)
print(f"\nRECONCILE REPORT: {rep}")

if args.commit:
    c1, t1, a1 = coverage()
    print(f"\nAFTER   closed={c1}  trade_outcomes={t1} (+{t1-t0})  alert_outcomes={a1} (+{a1-a0})")
    ev_table("after")
    print("\n✅ COMMITTED. Restart backend so TQS reloads strategy_stats: ./start_backend.sh --force")
else:
    print("\nDRY RUN — nothing written. Re-run with --commit to apply.")
