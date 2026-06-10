#!/usr/bin/env python3
"""
run_gate_outcome_reconcile.py  —  v19.34.311b  (2026-06-10)

Manual / cron runner for the gate-outcome COVERAGE reconciler. Backfills
confidence_gate_log outcomes from CLEAN closed bot_trades that carry a stamped
decision_id (entry pipeline v19.34.311b). Quarantines build-phase chaos via the
clean-trade hygiene filter.

Dry-run by default (prints what WOULD be backfilled). Pass --apply to write.

Run:
    cd ~/Trading-and-Analysis-Platform && \
      .venv/bin/python backend/scripts/run_gate_outcome_reconcile.py          # dry
      .venv/bin/python backend/scripts/run_gate_outcome_reconcile.py --apply  # write
"""
import os
import sys

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.ai_modules.gate_outcome_reconciler import GateOutcomeReconciler

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
APPLY = "--apply" in sys.argv


def main():
    if not MONGO_URL or not DB_NAME:
        print("ERROR: MONGO_URL / DB_NAME not set in backend/.env")
        sys.exit(1)
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=8000)[DB_NAME]
    rec = GateOutcomeReconciler(db=db)
    stats = rec.reconcile(dry_run=not APPLY)

    print("\n=== GATE OUTCOME RECONCILE ===")
    print(f"  mode            : {'APPLY (writing)' if APPLY else 'DRY-RUN'}")
    print(f"  scanned         : {stats.get('scanned')}")
    print(f"  clean           : {stats.get('clean')}")
    print(f"  excluded        : {stats.get('excluded')}")
    print(f"  matched gate-log: {stats.get('matched')}")
    print(f"  already tracked : {stats.get('already_tracked')}")
    print(f"  no gate-log     : {stats.get('no_gate_log')}")
    print(f"  BACKFILLED      : {stats.get('backfilled')}")
    if stats.get("exclude_reasons"):
        print("  exclude reasons :")
        for r, c in sorted(stats["exclude_reasons"].items(), key=lambda x: -x[1]):
            print(f"      {c:>5}  {r}")
    if not APPLY:
        print("\n  Re-run with --apply to write the backfill.")
    print()


if __name__ == "__main__":
    main()
