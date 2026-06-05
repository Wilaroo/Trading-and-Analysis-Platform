#!/usr/bin/env python3
"""
backfill_v19_34_271_canonical.py — m5 immediate re-key (optional one-shot)

After applying v19.34.271, the grade / EV / learning-stats stores re-key to
CANONICAL buckets and exclude artifacts — but that only takes effect for rows
WRITTEN after the change (the 16:05 EOD grade tick + the nightly learning
rebuild). This script forces all three NOW so the rolling 30d cards, the F-gate,
and the TQS setup pillar read the clean canonical buckets immediately, and it
DELETES the stale variant/artifact rows so they don't linger for up to 30 days.

Run from the backend dir inside the server venv:
    cd ~/Trading-and-Analysis-Platform/backend
    python3 scripts/backfill_v19_34_271_canonical.py            # apply
    python3 scripts/backfill_v19_34_271_canonical.py --dry-run  # preview only

Idempotent + safe to re-run. Honors the same env flags as the live code
(GRADING_CANONICAL_ROLLUP / EV_CANONICAL_ROLLUP / LEARNING_CANONICAL_BASE).
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta

# Allow running as `python3 scripts/backfill_v19_34_271_canonical.py` from the
# backend dir (add the backend dir — the script's parent's parent — to path).
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Load backend/.env so MONGO_URL / DB_NAME resolve when run standalone.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
except Exception:
    pass

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def main(dry_run: bool, days: int):
    from database import get_database
    from services.setup_taxonomy import canonicalize, is_edge_excluded
    from services.setup_grading_service import (
        get_setup_grading_service, GRADE_COLLECTION,
    )
    from services.learning_loop_service import get_learning_loop_service

    db = get_database()
    et = ZoneInfo("US/Eastern") if ZoneInfo else None
    today = (datetime.now(et) if et else datetime.utcnow()).date()

    # ── 1) Recompute canonical setup grades over the rolling window ──────────
    svc = get_setup_grading_service()
    dates = [(today - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(days)]
    graded = 0
    if not dry_run:
        for date in dates:
            try:
                res = svc.compute_eod_grades(trading_date=date)
                graded += int(res.get("setups_graded", 0))
            except Exception as e:
                print(f"  grade recompute {date} failed (skipped): {e}")
    print(f"[grades] recomputed {graded} setup-day snapshots over {days}d"
          f"{' (DRY-RUN: skipped)' if dry_run else ''}")

    # ── 2) Delete stale variant / artifact grade rows in the window ─────────
    coll = db[GRADE_COLLECTION]
    stale_ids, stale_examples = [], []
    for doc in coll.find({"trading_date": {"$in": dates}}, {"setup_type": 1}):
        st = doc.get("setup_type") or ""
        if is_edge_excluded(st) or canonicalize(st) != st:
            stale_ids.append(doc["_id"])
            if len(stale_examples) < 8:
                stale_examples.append(st)
    if stale_ids and not dry_run:
        coll.delete_many({"_id": {"$in": stale_ids}})
    print(f"[grades] {'would delete' if dry_run else 'deleted'} "
          f"{len(stale_ids)} stale variant/artifact rows "
          f"(e.g. {sorted(set(stale_examples))})")

    # ── 3) Re-key EV buckets (merge variant r-outcomes into canonical) ──────
    ev_coll = db["ev_tracking"]
    merged: dict = {}
    delete_ev_ids = []
    for doc in ev_coll.find({}):
        st = doc.get("setup_type") or ""
        if is_edge_excluded(st):
            delete_ev_ids.append(doc["_id"])
            continue
        canon = canonicalize(st) or st
        if canon != st:
            delete_ev_ids.append(doc["_id"])
        bucket = merged.setdefault(canon, [])
        bucket.extend(doc.get("r_outcomes", []) or [])
    ev_rekeyed = sum(1 for st in merged if any(True for _ in [st]))
    if not dry_run:
        from services.ev_tracking_service import get_ev_service
        ev_svc = get_ev_service(db)
        if delete_ev_ids:
            ev_coll.delete_many({"_id": {"$in": delete_ev_ids}})
        for canon, r_list in merged.items():
            from services.ev_tracking_service import EVTrackingRecord
            rec = EVTrackingRecord(setup_type=canon)
            for r in r_list:
                rec.r_outcomes.append(float(r))
                rec.total_trades += 1
                if float(r) > 0:
                    rec.wins += 1
                elif float(r) < 0:
                    rec.losses += 1
            ev_svc._ev_records[canon] = rec
            ev_svc.calculate_ev(canon)
    print(f"[ev] {'would re-key' if dry_run else 're-keyed'} into "
          f"{len(merged)} canonical buckets; "
          f"{'would delete' if dry_run else 'deleted'} {len(delete_ev_ids)} variant/artifact docs")

    # ── 4) Rebuild learning stats (the TQS corrected store) ─────────────────
    n = 0
    if not dry_run:
        ll = get_learning_loop_service()
        ll.set_db(db)
        n = asyncio.run(ll.rebuild_learning_stats_from_all_outcomes())
    print(f"[learning] rebuilt {n} canonical contexts"
          f"{' (DRY-RUN: skipped)' if dry_run else ''}")

    print("\nDONE." + (" (dry-run — nothing written)" if dry_run else
                       " Grade/EV/learning stores now canonical."))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=45,
                    help="calendar days back to recompute grades (default 45)")
    args = ap.parse_args()
    try:
        main(dry_run=args.dry_run, days=args.days)
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
