#!/usr/bin/env python3
"""
diag_v399_schedule_audit.py  — READ-ONLY scheduler freshness audit.

Answers the question: "if the app is only open part of the day, which
scheduled jobs are silently going stale because BackgroundScheduler has
no persistence / no misfire grace?"

Two evidence sources, cross-checked:
  A) JOB LOGS   — when each job *last reported* it ran
       - scheduled_task_logs   (trading_scheduler._log_task_result)
       - eod_generation_log    (eod_generation_service._log_generation)
  B) OUTPUT FRESHNESS — when each job's *data product* was last written
       (the real proof a job did its work, independent of the log row)

Nothing is written. Safe to run anytime, repeatedly.

Usage (on the DGX, from /app or wherever backend/.env lives):
    python3 diag_v399_schedule_audit.py
    python3 diag_v399_schedule_audit.py --env /app/backend/.env
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

try:
    from pymongo import MongoClient
except Exception:
    print("pymongo not importable — run inside the backend venv.")
    sys.exit(1)


# ---------- env / db ----------
def load_env(env_path):
    vals = {}
    if env_path and os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    # fall back to process env
    for k in ("MONGO_URL", "DB_NAME"):
        vals.setdefault(k, os.environ.get(k, ""))
    return vals


def parse_dt(v):
    """Coerce any of the timestamp shapes we store into an aware UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        # epoch seconds or ms
        try:
            ts = float(v)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip().replace("Z", "+00:00")
        for fmt in (None,):  # try fromisoformat first
            try:
                dt = datetime.fromisoformat(s)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        # date-only "YYYY-MM-DD"
        try:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def age_str(dt, now):
    if dt is None:
        return "—"
    delta = now - dt
    secs = delta.total_seconds()
    if secs < 0:
        return "future?"
    d = int(secs // 86400)
    h = int((secs % 86400) // 3600)
    m = int((secs % 3600) // 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


# Candidate timestamp fields, newest-first preference per output collection.
TS_FIELDS = ["updated_at", "last_updated", "lastUpdated", "as_of", "asof",
             "fetched_at", "computed_at", "timestamp", "created_at",
             "date", "started_at", "completed_at"]


def newest_doc_age(db, coll_name, now):
    """Return (age, field, count, newest_dt) for the freshest doc in a collection."""
    if coll_name not in db.list_collection_names():
        return ("NO COLLECTION", None, 0, None)
    col = db[coll_name]
    count = col.estimated_document_count()
    if count == 0:
        return ("EMPTY", None, 0, None)
    best_dt, best_field = None, None
    for fld in TS_FIELDS:
        try:
            doc = col.find({fld: {"$exists": True, "$ne": None}}, {fld: 1}) \
                     .sort(fld, -1).limit(1)
            doc = next(iter(doc), None)
        except Exception:
            doc = None
        if not doc:
            continue
        dt = parse_dt(doc.get(fld))
        if dt and (best_dt is None or dt > best_dt):
            best_dt, best_field = dt, fld
    if best_dt is None:
        return ("NO TS FIELD", None, count, None)
    return (age_str(best_dt, now), best_field, count, best_dt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=None,
                    help="path to backend/.env (auto-detects common locations)")
    args = ap.parse_args()

    env_path = args.env
    if env_path is None:
        for cand in ("/app/backend/.env", "backend/.env", ".env",
                     os.path.join(os.path.dirname(__file__), "..", "backend", ".env")):
            if os.path.exists(cand):
                env_path = cand
                break
    env = load_env(env_path)
    mongo_url = env.get("MONGO_URL")
    db_name = env.get("DB_NAME") or "tradecommand"
    if not mongo_url:
        print("MONGO_URL not found. Pass --env /path/to/backend/.env")
        sys.exit(1)

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client[db_name]
    now = datetime.now(timezone.utc)

    print("=" * 78)
    print(f"  v399 SCHEDULER FRESHNESS AUDIT   (read-only)")
    print(f"  db={db_name}   now={now.isoformat()}")
    print(f"  env={env_path}")
    print("=" * 78)

    # ---------- A1. trading_scheduler job logs ----------
    print("\n[A1] trading_scheduler  ->  scheduled_task_logs")
    print("-" * 78)
    stl = db["scheduled_task_logs"]
    if "scheduled_task_logs" not in db.list_collection_names() or stl.estimated_document_count() == 0:
        print("  (no scheduled_task_logs rows — scheduler may never have logged)")
    else:
        task_types = stl.distinct("task_type")
        print(f"  {'task_type':<30}{'last_run_age':<14}{'last_ok_age':<14}{'last_summary'}")
        for tt in sorted(task_types):
            last = next(iter(stl.find({"task_type": tt}).sort("started_at", -1).limit(1)), None)
            last_ok = next(iter(stl.find({"task_type": tt, "success": True}).sort("started_at", -1).limit(1)), None)
            la = age_str(parse_dt(last.get("started_at")) if last else None, now)
            oa = age_str(parse_dt(last_ok.get("started_at")) if last_ok else None, now)
            summ = (last.get("result_summary") or last.get("error") or "")[:40] if last else ""
            print(f"  {tt:<30}{la:<14}{oa:<14}{summ}")

    # ---------- A2. eod_generation_service logs ----------
    print("\n[A2] eod_generation_service  ->  eod_generation_log")
    print("-" * 78)
    eod = db["eod_generation_log"]
    if "eod_generation_log" not in db.list_collection_names() or eod.estimated_document_count() == 0:
        print("  (no eod_generation_log rows)")
    else:
        types = eod.distinct("type")
        print(f"  {'type':<30}{'last_run_age':<14}{'last_ok_age':<14}{'status/msg'}")
        for t in sorted(types):
            last = next(iter(eod.find({"type": t}).sort("timestamp", -1).limit(1)), None)
            last_ok = next(iter(eod.find({"type": t, "status": "success"}).sort("timestamp", -1).limit(1)), None)
            la = age_str(parse_dt(last.get("timestamp")) if last else None, now)
            oa = age_str(parse_dt(last_ok.get("timestamp")) if last_ok else None, now)
            msg = f"{last.get('status','')}: {(last.get('message') or '')[:32]}" if last else ""
            print(f"  {t:<30}{la:<14}{oa:<14}{msg}")

    # ---------- B. output-data freshness (the real proof) ----------
    # (collection, friendly job name, expected cadence, stale-threshold-hours)
    OUTPUTS = [
        ("symbol_fundamentals_cache",     "warm-fundamentals (MANUAL today)", "daily?",  36),
        ("institutional_ownership_cache", "institutional_ownership_refresh",  "Sun wk",  192),
        ("earnings_calendar",             "earnings_calendar_refresh",        "6:00 AM", 36),
        ("learning_stats",                "learning_stats_rebuild",           "5:30 PM", 60),
        ("rs_leadership",                 "rs_leadership_compute",            "5:30 PM", 60),
        ("adv_cache",                     "adv_cache_rebuild",               "5:10 PM", 60),
        ("model_validations",             "weekly_revalidation",             "Sun 10PM",240),
        ("game_plans",                    "premarket_gameplan",              "9:00 AM", 36),
        ("daily_report_cards",            "auto_generate_drc",               "4:30 PM", 60),
    ]
    print("\n[B] OUTPUT-DATA FRESHNESS  (independent proof the job's product exists)")
    print("-" * 78)
    print(f"  {'collection':<32}{'docs':<9}{'newest_age':<13}{'ts_field':<14}{'STALE?'}")
    for coll, job, cadence, thr_h in OUTPUTS:
        age, fld, cnt, dt = newest_doc_age(db, coll, now)
        stale = ""
        if dt is not None:
            stale = "🔴 STALE" if (now - dt) > timedelta(hours=thr_h) else "ok"
        elif age in ("EMPTY", "NO COLLECTION"):
            stale = "🔴 " + age
        print(f"  {coll:<32}{str(cnt):<9}{age:<13}{str(fld or '—'):<14}{stale}  [{job}]")

    # ---------- B2. fundamentals coverage detail ----------
    print("\n[B2] fundamentals coverage detail (symbol_fundamentals_cache)")
    print("-" * 78)
    if "symbol_fundamentals_cache" in db.list_collection_names():
        sfc = db["symbol_fundamentals_cache"]
        total = sfc.estimated_document_count()
        roe = sfc.count_documents({"roe_pct": {"$ne": None}})
        nm = sfc.count_documents({"net_margin_pct": {"$ne": None}})
        gr = sfc.count_documents({"proj_lt_growth_pct": {"$ne": None}})
        def pct(n):
            return f"{(100.0*n/total):.0f}%" if total else "—"
        print(f"  total symbols       : {total}")
        print(f"  roe_pct populated   : {roe} ({pct(roe)})")
        print(f"  net_margin populated: {nm} ({pct(nm)})")
        print(f"  proj_growth pop.    : {gr} ({pct(gr)})")
    else:
        print("  (collection missing)")

    print("\n" + "=" * 78)
    print("  Legend: 'last_run_age' = newest log row; 'last_ok_age' = newest")
    print("  SUCCESS row. A big gap between them = job is firing but failing.")
    print("  Section [B] STALE = the data product is older than its cadence ->")
    print("  the job silently missed its window while the app was closed.")
    print("=" * 78)


if __name__ == "__main__":
    main()
