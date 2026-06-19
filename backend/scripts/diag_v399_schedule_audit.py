#!/usr/bin/env python3
"""
diag_v399_schedule_audit.py  —  READ-ONLY: is each scheduled job ACTUALLY running?

The 3 schedulers (trading_scheduler / eod_generation_service / scheduler_service)
are all in-memory BackgroundScheduler wall-clock crons — NO misfire grace, NO
persistence, NO catch-up. If the app is down at trigger time the job is silently
skipped. There's no run-log, so we judge by OUTPUT FRESHNESS in Mongo.

Part A — freshness of each job's output collection vs its expected cadence.
Part B — full freshness board: newest timestamp in every collection (catch the rest).

NO WRITES. Run: PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v399_schedule_audit.py
"""
import os
import sys
from datetime import datetime, timezone

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "tradecommand")
TS_FIELDS = ["updated_at", "fetched_at", "computed_at", "generated_at",
             "created_at", "as_of", "timestamp", "date", "snapshot_date", "run_at"]

# (job_id, schedule, collection, max_age_hours)  — high-confidence mappings
JOBS = [
    ("earnings_calendar_refresh", "6:00 daily",  "earnings_calendar",            36),
    ("adv_cache_rebuild",         "17:10 daily", "symbol_adv_cache",             36),
    ("rs_leadership_compute",     "17:30 daily", "rs_leadership",                36),
    ("eod_daily_topup",           "16:35 daily", "ib_historical_data",           36),
    ("institutional_refresh",     "Sun 3:00",    "institutional_ownership_cache",200),
    ("warm_fundamentals",         "(manual)",    "symbol_fundamentals_cache",    36),
    ("learning_stats_rebuild",    "17:30 daily", "learning_stats",               36),
    ("daily_recap_drc",           "16:30 daily", "daily_recaps",                 36),
    ("premarket_gameplan",        "9:00 daily",  "premarket_gameplans",          36),
    ("self_reflection",           "17:00 daily", "self_reflections",             36),
    ("playbook_analysis",         "16:45 daily", "playbook_analysis",            36),
    ("regime_expectancy",         "16:35 daily", "regime_expectancy",            48),
    ("gate_calibration",          "16:30 daily", "confidence_gate_calibration",  48),
    ("weekly_report",             "Fri 16:30",   "weekly_reports",               200),
]


def newest_ts(coll):
    """Return (datetime, field) of newest doc, best-effort, index-friendly."""
    try:
        doc = coll.find_one({}, sort=[("_id", -1)], max_time_ms=2000) or {}
    except Exception:
        doc = {}
    present = [f for f in TS_FIELDS if f in doc]
    best = None; bestf = None
    for f in present:
        try:
            d = coll.find_one({f: {"$ne": None}}, {f: 1}, sort=[(f, -1)], max_time_ms=3000)
        except Exception:
            continue
        if not d:
            continue
        v = d.get(f)
        dt = _to_dt(v)
        if dt and (best is None or dt > best):
            best, bestf = dt, f
    return best, bestf


def _to_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                d = datetime.strptime(v.replace("Z", "+0000"), fmt)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def main():
    if not MONGO_URL:
        print("MONGO_URL not set."); sys.exit(1)
    from pymongo import MongoClient
    db = MongoClient(MONGO_URL, serverSelectionTimeoutMS=4000)[DB_NAME]
    now = datetime.now(timezone.utc)
    existing = set(db.list_collection_names())

    print("=" * 78)
    print("SCHEDULED JOB FRESHNESS AUDIT  (v399, READ-ONLY)")
    print("=" * 78)
    print(f"now (UTC): {now.isoformat()}\n")
    print(f"{'JOB':<26}{'SCHEDULE':<14}{'COLLECTION':<30}{'AGE':<12}STATUS")
    print("-" * 78)
    for job, sched, coll_name, max_age in JOBS:
        if coll_name not in existing:
            print(f"{job:<26}{sched:<14}{coll_name:<30}{'—':<12}MISSING (collection absent)")
            continue
        dt, f = newest_ts(db[coll_name])
        if not dt:
            print(f"{job:<26}{sched:<14}{coll_name:<30}{'?':<12}NO TIMESTAMP")
            continue
        age_h = (now - dt).total_seconds() / 3600
        status = "FRESH" if age_h <= max_age else ("STALE %.0fh > %dh" % (age_h, max_age))
        print(f"{job:<26}{sched:<14}{coll_name:<30}{age_h:>6.1f}h     {status}  ({f})")

    print("\n" + "=" * 78)
    print("PART B — full freshness board (newest timestamp per collection)")
    print("=" * 78)
    rows = []
    for name in sorted(existing):
        dt, f = newest_ts(db[name])
        cnt = db[name].estimated_document_count()
        rows.append((name, cnt, dt, f))
    for name, cnt, dt, f in rows:
        age = ("%.1fh" % ((now - dt).total_seconds() / 3600)) if dt else "—"
        print(f"  {name:<40} docs={cnt:<9} newest={age:<10}{('('+f+')') if f else 'no-ts'}")

    print("\nRead-only — nothing was modified.")


if __name__ == "__main__":
    main()
