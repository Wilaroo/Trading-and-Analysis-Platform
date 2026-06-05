#!/usr/bin/env python3
"""
migrate_v19_34_272_tidal_wave.py — m8 data migration

Every historical `tidal_wave` row in the DB was produced by the OLD reversion
detector — they are genuinely FADES, just mislabeled. m8 reassigns the name
`tidal_wave` to a NEW true-momentum detector. To keep the new momentum bucket
clean (and credit the fade track-record to its true name), this migrates all
existing `tidal_wave` rows → `fading_bounce`, then recomputes the derived stores.

  Source rows renamed : bot_trades, trade_outcomes, alert_outcomes, ev_tracking
  Derived rebuilt     : setup_grade_records (recompute), learning_stats (rebuild)

Run from the backend dir inside the server venv:
    cd ~/Trading-and-Analysis-Platform/backend
    python3 scripts/migrate_v19_34_272_tidal_wave.py --dry-run   # preview
    python3 scripts/migrate_v19_34_272_tidal_wave.py             # apply

Idempotent + safe to re-run (a second run finds 0 tidal_wave source rows).
SAFETY: run BEFORE the new momentum detector has produced any real tidal_wave
trades (i.e. right after the m8 deploy) so no momentum rows get misfiled.
"""
import argparse
import asyncio
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
except Exception:
    pass

OLD = "tidal_wave"
NEW = "fading_bounce"


def main(dry_run: bool, days: int):
    from database import get_database
    from services.setup_grading_service import get_setup_grading_service, GRADE_COLLECTION
    from services.learning_loop_service import get_learning_loop_service
    from datetime import datetime, timedelta
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("US/Eastern")
    except Exception:
        et = None

    db = get_database()

    # ── 1) Rename source rows: setup_type tidal_wave → fading_bounce ────────
    for coll in ("bot_trades", "trade_outcomes", "alert_outcomes"):
        n = db[coll].count_documents({"setup_type": OLD})
        if n and not dry_run:
            db[coll].update_many({"setup_type": OLD}, {"$set": {"setup_type": NEW}})
        print(f"[{coll}] {'would rename' if dry_run else 'renamed'} {n} {OLD}→{NEW} rows")

    # ── 2) EV: rename/merge the tidal_wave bucket into fading_bounce ────────
    ev = db["ev_tracking"]
    old_doc = ev.find_one({"setup_type": OLD})
    if old_doc:
        if not dry_run:
            existing = ev.find_one({"setup_type": NEW})
            if existing:
                merged_r = (existing.get("r_outcomes", []) or []) + (old_doc.get("r_outcomes", []) or [])
                ev.update_one({"setup_type": NEW}, {"$set": {"r_outcomes": merged_r}})
                ev.delete_one({"_id": old_doc["_id"]})
            else:
                ev.update_one({"_id": old_doc["_id"]}, {"$set": {"setup_type": NEW}})
        print(f"[ev_tracking] {'would migrate' if dry_run else 'migrated'} {OLD}→{NEW} bucket")
    else:
        print(f"[ev_tracking] no {OLD} bucket")

    # ── 3) Drop derived tidal_wave rows (recompute/rebuild replaces them) ───
    gn = db[GRADE_COLLECTION].count_documents({"setup_type": OLD})
    ls = db["learning_stats"].count_documents({"setup_type": OLD})
    if not dry_run:
        db[GRADE_COLLECTION].delete_many({"setup_type": OLD})
        db["learning_stats"].delete_many({"setup_type": OLD})
    print(f"[setup_grade_records] {'would delete' if dry_run else 'deleted'} {gn} {OLD} grade rows")
    print(f"[learning_stats] {'would delete' if dry_run else 'deleted'} {ls} {OLD} stat rows")

    # ── 4) Recompute grades + rebuild learning from the renamed sources ─────
    if not dry_run:
        svc = get_setup_grading_service()
        today = (datetime.now(et) if et else datetime.utcnow()).date()
        graded = 0
        for d in range(days):
            date = (today - timedelta(days=d)).strftime("%Y-%m-%d")
            try:
                graded += int(svc.compute_eod_grades(trading_date=date).get("setups_graded", 0))
            except Exception as e:
                print(f"  grade recompute {date} failed (skipped): {e}")
        ll = get_learning_loop_service()
        ll.set_db(db)
        n = asyncio.run(ll.rebuild_learning_stats_from_all_outcomes())
        print(f"[recompute] {graded} grade snapshots over {days}d; learning rebuilt {n} contexts")
    else:
        print(f"[recompute] would recompute grades over {days}d + rebuild learning (DRY-RUN: skipped)")

    print("\nDONE." + (" (dry-run — nothing written)" if dry_run else
                       f" Historical {OLD} migrated to {NEW}; {OLD} now reserved for the momentum detector."))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()
    try:
        main(dry_run=args.dry_run, days=args.days)
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
