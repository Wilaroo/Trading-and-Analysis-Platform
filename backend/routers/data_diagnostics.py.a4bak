"""
data_diagnostics.py — v399b

Two operator-facing data-health surfaces for the Diagnostics tab:

  GET /api/diagnostics/data-schedule
      Live punchlist of every scheduled job (DAILY_SCHEDULE.md, productized):
      per job -> last run, last *success*, next scheduled fire, output-data
      freshness, and an issue flag. A big gap between last-run and last-success
      = a job firing but failing (this is the UI that would have surfaced the
      35-day-dead gate_calibration on day one). Folds in the last boot catch-up
      sweep result.

  GET /api/tqs/coverage
      Real-vs-default coverage of the TQS pillars/sub-scores over recently
      scored alerts. The tell is the v391 descriptor verdict == "No data".

Both are read-only.
"""
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Data Diagnostics"])

NO_DATA = "No data"
PILLARS = ["setup", "technical", "fundamental", "context", "execution"]

# job key -> catalog row.  scheduler: 'trading'|'eod'  ;  src: 'task_log'|'eod_log'
# aps_id: APScheduler job id for next-run lookup ; coll/field: output freshness
_CATALOG = [
    # key, label, category, scheduler, aps_id, src, log_key, coll, field, stale_h
    ("ib_collection_resume", "IB Collection Resume", "Overnight", "trading", "ib_collection_resume", "task_log", "ib_collection_resume", None, None, 30),
    ("earnings_calendar_refresh", "Earnings Calendar", "Pre-market", "trading", "earnings_calendar_refresh", "coll", None, "earnings_calendar", "date", 30),
    ("premarket_gameplan", "Premarket Gameplan", "Pre-market", "eod", "auto_generate_premarket_gameplan", "eod_log", "premarket_gameplan", "game_plans", "updated_at", 30),
    ("daily_analysis", "Daily Analysis", "Post-close cascade", "trading", "daily_analysis", "task_log", "daily_analysis", None, None, 30),
    ("edge_decay_check", "Edge Decay Check", "Post-close cascade", "trading", "edge_decay_check", "task_log", "edge_decay_check", None, None, 30),
    ("gate_outcome_reconcile", "Gate Outcome Reconcile", "Post-close cascade", "trading", "gate_outcome_reconcile", "task_log", "gate_outcome_reconcile", None, None, 30),
    ("gate_calibration", "Gate Calibration", "Post-close cascade", "trading", "gate_calibration", "task_log", "gate_calibration", None, None, 30),
    ("drc", "Daily Recap (DRC)", "Post-close cascade", "eod", "auto_generate_drc", "eod_log", "drc", "daily_report_cards", "updated_at", 30),
    ("regime_expectancy_refresh", "Regime Expectancy", "Post-close cascade", "trading", "regime_expectancy_refresh", "task_log", "regime_expectancy_refresh", None, None, 30),
    ("entry_price_sync", "Entry-Price Sync", "Post-close cascade", "trading", "entry_price_sync", "task_log", "entry_price_sync", None, None, 30),
    ("eod_daily_topup", "EOD Daily-Bar Top-Up", "Post-close cascade", "trading", "eod_daily_topup", "task_log", "eod_daily_topup", None, None, 30),
    ("playbook_analysis", "Playbook Analysis", "Post-close cascade", "eod", "auto_playbook_analysis", "eod_log", "playbook_analysis", None, None, 30),
    ("self_reflection", "Self-Reflection", "Post-close cascade", "eod", "auto_self_reflection", "eod_log", "self_reflection", None, None, 30),
    ("learning_sync", "Learning Sync", "Post-close cascade", "trading", "learning_sync", "task_log", "learning_sync", None, None, 30),
    ("adv_cache_rebuild", "ADV Cache Rebuild", "Post-close cascade", "trading", "adv_cache_rebuild", "task_log", "adv_cache_rebuild", None, None, 30),
    ("learning_stats_rebuild", "Learning-Stats Rebuild", "Post-close cascade", "trading", "learning_stats_rebuild", "coll", None, "learning_stats", "last_updated", 30),
    ("rs_leadership_compute", "RS Leadership Compute", "Post-close cascade", "trading", "rs_leadership_compute", "task_log", "rs_leadership_compute", "rs_leadership", "computed_at", 30),
    ("warm_fundamentals_nightly", "Fundamentals Warm-Fill", "Post-close cascade", "trading", "warm_fundamentals_nightly", "coll", None, "symbol_fundamentals_cache", "fetched_at", 30),
    ("weekly_report", "Weekly Report", "Weekend", "trading", "weekly_report", "task_log", "weekly_report", None, None, 192),
    ("institutional_ownership_refresh", "Institutional Ownership", "Weekend", "trading", "institutional_ownership_refresh", "coll", None, "institutional_ownership_cache", "fetched_at", 192),
    ("weekly_revalidation", "Model Revalidation", "Weekend", "trading", "weekly_revalidation", "task_log", "weekly_revalidation", None, None, 240),
    ("weekend_briefing", "Weekend Briefing", "Weekend", "eod", "auto_generate_weekend_briefing", "eod_log", None, None, None, 192),
]


def _db():
    from server import db as mongo_db
    return mongo_db


def _as_utc(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _age_s(dt, now):
    return None if dt is None else max(0.0, (now - dt).total_seconds())


def _next_runs():
    """Map APScheduler job_id -> ISO next_run from both schedulers."""
    out = {}
    try:
        from services.trading_scheduler import get_trading_scheduler
        for j in (get_trading_scheduler().get_scheduled_jobs() or []):
            if j.get("next_run"):
                out[j["id"]] = j["next_run"]
    except Exception as e:
        logger.debug("next_runs trading: %s", e)
    try:
        from services.eod_generation_service import get_eod_service
        eod = get_eod_service()
        sched = getattr(eod, "scheduler", None) if eod else None
        if sched is not None:
            for j in sched.get_jobs():
                nr = getattr(j, "next_run_time", None)
                if nr:
                    out[j.id] = nr.isoformat()
    except Exception as e:
        logger.debug("next_runs eod: %s", e)
    return out


def _last_success(db, src, log_key, coll, field):
    try:
        if src == "task_log":
            d = db["scheduled_task_logs"].find_one(
                {"task_type": log_key, "success": True},
                sort=[("started_at", -1)], projection={"started_at": 1})
            return _as_utc(d.get("started_at")) if d else None
        if src == "eod_log":
            d = db["eod_generation_log"].find_one(
                {"type": log_key, "status": "success"},
                sort=[("timestamp", -1)], projection={"timestamp": 1})
            return _as_utc(d.get("timestamp")) if d else None
        if src == "coll" and coll and field:
            d = db[coll].find_one({field: {"$exists": True, "$ne": None}},
                                  sort=[(field, -1)], projection={field: 1})
            return _as_utc(d.get(field)) if d else None
    except Exception as e:
        logger.debug("last_success %s: %s", log_key or coll, e)
    return None


def _last_run(db, src, log_key):
    try:
        if src == "task_log":
            d = db["scheduled_task_logs"].find_one(
                {"task_type": log_key}, sort=[("started_at", -1)],
                projection={"started_at": 1, "result_summary": 1, "error": 1, "success": 1})
            if d:
                return (_as_utc(d.get("started_at")),
                        d.get("result_summary") or d.get("error") or "",
                        bool(d.get("success")))
        if src == "eod_log":
            d = db["eod_generation_log"].find_one(
                {"type": log_key}, sort=[("timestamp", -1)],
                projection={"timestamp": 1, "message": 1, "status": 1})
            if d:
                return (_as_utc(d.get("timestamp")), d.get("message") or "",
                        d.get("status") == "success")
    except Exception as e:
        logger.debug("last_run %s: %s", log_key, e)
    return (None, "", None)


@router.get("/api/diagnostics/data-schedule")
async def data_schedule():
    db = _db()
    if db is None:
        return {"success": False, "detail": "DB not connected"}
    now = datetime.now(timezone.utc)
    nexts = _next_runs()

    rows = []
    for (key, label, cat, scheduler, aps_id, src, log_key,
         coll, field, stale_h) in _CATALOG:
        last_ok = _last_success(db, src, log_key, coll, field)
        last_run_dt, summary, last_ok_flag = (None, "", None)
        if src in ("task_log", "eod_log") and log_key:
            last_run_dt, summary, last_ok_flag = _last_run(db, src, log_key)
        else:
            last_run_dt = last_ok  # coll-backed jobs: freshness == last run
        # output product freshness (independent proof)
        out_dt = None
        if coll and field:
            out_dt = _last_success(db, "coll", None, coll, field)

        ok_age = _age_s(last_ok, now)
        run_age = _age_s(last_run_dt, now)
        # issue detection
        issue = None
        if last_ok is None and last_run_dt is None:
            issue = "never_run"
        elif last_ok is None and last_run_dt is not None:
            issue = "failing"           # fires but never succeeds (the gate bug)
        elif ok_age is not None and ok_age > stale_h * 3600:
            issue = "stale"
        elif (run_age is not None and ok_age is not None
              and run_age + 6 * 3600 < ok_age):
            issue = "failing"           # last run failed well after last success
        rows.append({
            "key": key, "label": label, "category": cat,
            "last_run": last_run_dt.isoformat() if last_run_dt else None,
            "last_run_age_s": run_age,
            "last_success": last_ok.isoformat() if last_ok else None,
            "last_success_age_s": ok_age,
            "next_run": nexts.get(aps_id),
            "output_fresh_age_s": _age_s(out_dt, now),
            "summary": (summary or "")[:160],
            "issue": issue,
            "stale_threshold_h": stale_h,
        })

    # last boot catch-up sweep
    catchup = None
    try:
        d = db["scheduled_task_logs"].find_one(
            {"task_type": "catch_up_sweep"}, sort=[("started_at", -1)])
        if d:
            meta = d.get("metadata") or {}
            catchup = {
                "at": d.get("started_at"),
                "summary": d.get("result_summary"),
                "market_open": meta.get("market_open"),
                "scheduled": meta.get("scheduled") or [],
            }
    except Exception as e:
        logger.debug("catchup row: %s", e)

    counts = defaultdict(int)
    for r in rows:
        counts[r["issue"] or "ok"] += 1

    return {
        "success": True,
        "as_of": now.isoformat(),
        "rows": rows,
        "catchup": catchup,
        "counts": dict(counts),
        "categories": ["Overnight", "Pre-market", "Post-close cascade", "Weekend"],
    }


@router.get("/api/tqs/coverage")
async def tqs_coverage(days: int = Query(7, ge=1, le=90),
                       limit: int = Query(0, ge=0, le=20000)):
    db = _db()
    if db is None:
        return {"success": False, "detail": "DB not connected"}
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    cur = db.live_alerts.find(
        {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}},
        {"tqs_breakdown": 1, "symbol": 1, "created_at": 1}).sort("created_at", -1)
    if limit:
        cur = cur.limit(limit)

    comp = defaultdict(lambda: defaultdict(lambda: {"label": "", "total": 0, "no_data": 0}))
    pillar_tot = defaultdict(lambda: {"t": 0, "nd": 0})
    n_alerts = n_bd = n_disp = 0
    sample = None

    for doc in cur:
        n_alerts += 1
        bd = doc.get("tqs_breakdown") or {}
        if not bd:
            continue
        n_bd += 1
        had = False
        for p in PILLARS:
            pdata = bd.get(p)
            if not isinstance(pdata, dict):
                continue
            disp = pdata.get("display")
            if not isinstance(disp, dict):
                continue
            had = True
            for ckey, blk in disp.items():
                if not isinstance(blk, dict):
                    continue
                rec = comp[p][ckey]
                rec["label"] = blk.get("label", ckey)
                rec["total"] += 1
                nd = (blk.get("verdict") == NO_DATA)
                rec["no_data"] += 1 if nd else 0
                pillar_tot[p]["t"] += 1
                pillar_tot[p]["nd"] += 1 if nd else 0
        if had:
            n_disp += 1
            if sample is None:
                sample = doc

    pillars = []
    g_t = g_nd = 0
    for p in PILLARS:
        recs = comp.get(p)
        if not recs:
            continue
        pt = pillar_tot[p]
        g_t += pt["t"]
        g_nd += pt["nd"]
        components = []
        for ckey, rec in sorted(recs.items()):
            tot = rec["total"]
            components.append({
                "key": ckey, "label": rec["label"], "samples": tot,
                "real_pct": round(100.0 * (tot - rec["no_data"]) / tot, 1) if tot else 0,
                "no_data_pct": round(100.0 * rec["no_data"] / tot, 1) if tot else 0,
            })
        pillars.append({
            "pillar": p,
            "coverage_pct": round(100.0 * (1 - pt["nd"] / pt["t"]), 1) if pt["t"] else 0,
            "components": components,
        })

    sample_out = None
    if sample is not None:
        bd = sample.get("tqs_breakdown") or {}
        sv = {}
        for p in PILLARS:
            pdata = bd.get(p)
            if isinstance(pdata, dict) and isinstance(pdata.get("display"), dict):
                sv[p] = {b.get("label"): b.get("verdict")
                         for b in pdata["display"].values() if isinstance(b, dict)}
        sample_out = {"symbol": sample.get("symbol"),
                      "created_at": str(sample.get("created_at"))[:19], "verdicts": sv}

    return {
        "success": True,
        "as_of": now.isoformat(),
        "window_days": days,
        "alerts_scanned": n_alerts,
        "with_breakdown": n_bd,
        "with_display": n_disp,
        "legacy_no_display": n_bd - n_disp,
        "overall_coverage_pct": round(100.0 * (1 - g_nd / g_t), 1) if g_t else 0,
        "real_subscores": g_t - g_nd,
        "total_subscores": g_t,
        "pillars": pillars,
        "sample": sample_out,
    }
