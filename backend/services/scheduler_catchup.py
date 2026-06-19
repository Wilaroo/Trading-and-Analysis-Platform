"""
scheduler_catchup.py — v399 boot-time staleness guard / catch-up sweep.

WHY
---
The cron schedulers (`trading_scheduler`, `eod_generation_service`) use an
in-memory APScheduler `BackgroundScheduler` with NO persistence and NO
misfire grace. If the app is closed during a job's cron window, that day's
job silently skips and never retries. (Confirmed by diag_v399.)

WHAT
----
On backend startup we run ONE catch-up sweep:
  1. For each catch-up-eligible job, compute the most recent scheduled
     "expected fire" time that has already passed (business-day aware, so
     weekends never produce false positives).
  2. Read the job's last *successful* run (from scheduled_task_logs /
     eod_generation_log / output-collection freshness).
  3. If last_success is missing or older than the last expected fire, the
     job is OVERDUE -> we re-run it, AUTO-STAGGERED so a cold boot doesn't
     stampede Mongo or the IB sockets.

Market-unsafe jobs (live clientId-11 fundamentals warm-fill, entry-price
sync) only catch up when the market is CLOSED.

Also wires the fundamentals warm-fill as a nightly cron (18:30 ET weekdays)
so it is hands-free going forward (Issue 2).

Idempotent. Read-mostly: it only triggers the same job coroutines the cron
would have run; each logs its own result row, so a re-run of diag_v399
afterwards reflects the catch-up.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ── per-job stagger (seconds) so a cold boot doesn't stampede ──
_INITIAL_DELAY_S = 120     # let heavy init settle before any catch-up
_MONGO_GAP_S = 20          # gap between Mongo-only catch-up jobs
_IB_GAP_S = 120            # gap between IB / heavy catch-up jobs

# ── job registry ───────────────────────────────────────────────
# schedule: (hour, minute, dow)  dow in {'weekday','daily','sun'}
# source:   how to read last-success  ('task_log' | 'eod_log' | 'coll')
# market_safe: may run during RTH (False -> only when market closed)
# heavy:    use the longer IB stagger gap
_JOBS = [
    # name                         method_attr                      schedule          source     coll/field                       market_safe heavy
    ("daily_analysis",             "_run_daily_analysis",           (16, 0,  "weekday"), "task_log", None,                          True,  False),
    ("edge_decay_check",           "_run_edge_decay_check",         (16, 15, "weekday"), "task_log", None,                          True,  False),
    ("gate_outcome_reconcile",     "_run_gate_outcome_reconcile",   (16, 25, "weekday"), "task_log", None,                          True,  False),
    ("gate_calibration",           "_run_gate_calibration",         (16, 30, "weekday"), "task_log", None,                          True,  False),
    ("regime_expectancy_refresh",  "_run_regime_expectancy_refresh",(16, 35, "weekday"), "task_log", None,                          True,  False),
    ("eod_daily_topup",            "_run_eod_daily_topup",          (16, 35, "weekday"), "task_log", None,                          True,  False),
    ("learning_sync",              "_run_learning_sync",            (17, 0,  "weekday"), "task_log", None,                          True,  False),
    ("adv_cache_rebuild",          "_run_adv_cache_rebuild",        (17, 10, "weekday"), "task_log", None,                          True,  False),
    ("learning_stats_rebuild",     "_run_learning_stats_rebuild",   (17, 30, "daily"),   "task_log", None,                          True,  False),
    ("rs_leadership_compute",      "_run_rs_leadership_compute",    (17, 30, "weekday"), "task_log", None,                          True,  False),
    ("earnings_calendar_refresh",  "_run_earnings_calendar_refresh",(6,  0,  "daily"),   "task_log", None,                          True,  False),
    # ── heavy / IB / market-unsafe ──
    ("institutional_ownership_refresh", "_run_institutional_ownership_refresh", (3, 0, "sun"), "coll",
        ("institutional_ownership_cache", "fetched_at"),                       False, True),
    ("entry_price_sync",           "_run_entry_price_sync",         (16, 35, "weekday"), "task_log", None,                          False, True),
    # warm-fundamentals: new nightly cron + boot catch-up (clientId-11, off-hours only)
    ("warm_fundamentals",          None,                            (18, 30, "weekday"), "coll",
        ("symbol_fundamentals_cache", "fetched_at"),                           False, True),
]


def _et_now():
    import pytz
    return datetime.now(pytz.timezone("US/Eastern"))


# US equity-market full-day holidays (no live session -> IB sockets free).
# Half-days still trade, so they are intentionally NOT listed here.
_US_MARKET_HOLIDAYS_2026 = {
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Jr. Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
}


def _is_market_holiday(now_et):
    return now_et.strftime("%Y-%m-%d") in _US_MARKET_HOLIDAYS_2026


def _market_currently_open(trading_scheduler, now_et):
    """Holiday-aware live-session check. is_market_hours() only knows
    weekday + clock, so on a full-day holiday it wrongly reports open. On a
    holiday the live session is dark and the IB sockets are free, so we treat
    the market as CLOSED -> market-unsafe catch-ups are allowed to run."""
    if _is_market_holiday(now_et):
        return False
    try:
        return bool(trading_scheduler.is_market_hours())
    except Exception:
        return False


def _last_expected_fire_utc(now_et, hour, minute, dow):
    """Most recent scheduled fire <= now (business-day aware), as UTC dt."""
    for back in range(0, 10):
        cand = (now_et - timedelta(days=back)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if cand > now_et:
            continue
        wd = cand.weekday()  # 0=Mon .. 6=Sun
        if (dow == "daily"
                or (dow == "weekday" and wd < 5)
                or (dow == "sun" and wd == 6)):
            return cand.astimezone(timezone.utc)
    return None


def _as_utc(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _last_success(db, name, source, coll_field):
    """Return last successful run datetime (UTC) for a job."""
    try:
        if source == "task_log":
            doc = db["scheduled_task_logs"].find_one(
                {"task_type": name, "success": True},
                sort=[("started_at", -1)], projection={"started_at": 1})
            return _as_utc(doc.get("started_at")) if doc else None
        if source == "eod_log":
            doc = db["eod_generation_log"].find_one(
                {"type": name, "status": "success"},
                sort=[("timestamp", -1)], projection={"timestamp": 1})
            return _as_utc(doc.get("timestamp")) if doc else None
        if source == "coll":
            coll, field = coll_field
            doc = db[coll].find_one(
                {field: {"$exists": True, "$ne": None}},
                sort=[(field, -1)], projection={field: 1})
            return _as_utc(doc.get(field)) if doc else None
    except Exception as e:
        logger.warning("[catchup] last_success(%s) failed: %s", name, e)
    return None


async def warm_fundamentals_sweep(db, days=5, throttle=0.8, institutional=True, limit=0):
    """Standalone fundamentals warm-fill (clientId-11, off-hours). Mirrors the
    /api/short-data/warm-fundamentals endpoint so the cron + boot catch-up and
    the manual button share one code path and one progress dict."""
    from services.unified_fundamentals_cache import (
        get_cached_fundamentals, refresh_institutional_ownership)
    # share the router's progress dict if importable (keeps /status accurate)
    try:
        from routers.short_data import _warm_progress
    except Exception:
        _warm_progress = {}
    if _warm_progress.get("running"):
        logger.info("[catchup] warm-fundamentals already running — skip")
        return
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    uni = sorted(db.live_alerts.distinct(
        "symbol", {"created_at": {"$gte": since}, "tqs_score": {"$gt": 0}}))
    if limit:
        uni = uni[:limit]
    _warm_progress.update({"running": True, "done": 0, "total": len(uni),
                           "ib_float": 0, "institutional": 0,
                           "started_at": datetime.now(timezone.utc).isoformat(),
                           "finished_at": None})
    logger.info("[catchup] warm-fundamentals sweep starting: %d symbols", len(uni))
    try:
        for sym in uni:
            if institutional:
                try:
                    ex = db.institutional_ownership_cache.find_one(
                        {"symbol": sym}, {"fetched_at": 1})
                    fa = _as_utc(ex.get("fetched_at")) if ex else None
                    fresh = fa is not None and (datetime.now(timezone.utc) - fa).days < 7
                    if fresh:
                        _warm_progress["institutional"] += 1
                    else:
                        pct = await refresh_institutional_ownership(sym, db=db)
                        if pct is not None:
                            _warm_progress["institutional"] += 1
                except Exception as exc:
                    logger.debug("[catchup] warm institutional %s: %s", sym, exc)
            try:
                merged = await get_cached_fundamentals(sym, force_refresh=True)
                if merged and merged.get("float_shares"):
                    _warm_progress["ib_float"] += 1
            except Exception as exc:
                logger.debug("[catchup] warm float %s: %s", sym, exc)
            _warm_progress["done"] += 1
            await asyncio.sleep(throttle)
    finally:
        _warm_progress["running"] = False
        _warm_progress["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("[catchup] warm-fundamentals sweep complete: %s", dict(_warm_progress))


def _build_runner(name, method_attr, trading_scheduler, eod_service, db):
    """Resolve the coroutine to run for a job (called fresh at fire time)."""
    if name == "warm_fundamentals":
        return lambda: warm_fundamentals_sweep(db)
    if method_attr and trading_scheduler is not None:
        fn = getattr(trading_scheduler, method_attr, None)
        if fn is not None:
            return fn
    return None


async def run_catch_up_sweep(db, trading_scheduler, eod_service=None):
    """Boot-time staleness guard. Spawned as a background task on startup."""
    try:
        await asyncio.sleep(_INITIAL_DELAY_S)
        now_et = _et_now()
        now_utc = datetime.now(timezone.utc)

        market_open = _market_currently_open(trading_scheduler, now_et)
        if _is_market_holiday(now_et):
            logger.info("[catchup] %s is a US market holiday — treating "
                        "session as CLOSED (IB sockets free)",
                        now_et.strftime("%Y-%m-%d"))

        overdue = []
        for (name, method_attr, sched, source, coll_field, market_safe, heavy) in _JOBS:
            hour, minute, dow = sched
            expected = _last_expected_fire_utc(now_et, hour, minute, dow)
            if expected is None:
                continue
            last_ok = _last_success(db, name, source, coll_field)
            is_overdue = (last_ok is None) or (last_ok < expected)
            if not is_overdue:
                continue
            if (not market_safe) and market_open:
                logger.info("[catchup] %s overdue but market OPEN — deferring "
                            "(market-unsafe job)", name)
                continue
            runner = _build_runner(name, method_attr, trading_scheduler, eod_service, db)
            if runner is None:
                logger.warning("[catchup] %s overdue but no runner resolved", name)
                continue
            overdue.append((name, runner, heavy, last_ok, expected))

        if not overdue:
            logger.info("[catchup] sweep: all jobs fresh, nothing to catch up "
                        "(market_open=%s)", market_open)
            _log_summary(db, now_utc, market_open, [])
            return

        logger.info("[catchup] sweep: %d overdue job(s) -> %s",
                    len(overdue), [o[0] for o in overdue])

        # auto-stagger
        delay = 0
        scheduled_names = []
        for (name, runner, heavy, last_ok, expected) in overdue:
            asyncio.create_task(
                _run_after(delay, name, runner),
                name=f"catchup_{name}")
            scheduled_names.append({
                "job": name,
                "delay_s": delay,
                "last_ok": last_ok.isoformat() if last_ok else None,
                "expected_fire": expected.isoformat() if expected else None,
            })
            delay += _IB_GAP_S if heavy else _MONGO_GAP_S

        _log_summary(db, now_utc, market_open, scheduled_names)
    except Exception as e:
        logger.error("[catchup] sweep failed: %s", e, exc_info=True)


async def _run_after(delay_s, name, runner):
    if delay_s:
        await asyncio.sleep(delay_s)
    try:
        logger.info("[catchup] running overdue job: %s", name)
        await runner()
        logger.info("[catchup] done: %s", name)
    except Exception as e:
        logger.error("[catchup] job %s failed: %s", name, e, exc_info=True)


def _log_summary(db, now_utc, market_open, scheduled):
    """Write a sweep summary into scheduled_task_logs so diag_v399 shows it."""
    try:
        db["scheduled_task_logs"].insert_one({
            "task_type": "catch_up_sweep",
            "success": True,
            "started_at": now_utc.isoformat(),
            "completed_at": now_utc.isoformat(),
            "duration_seconds": 0,
            "result_summary": (f"{len(scheduled)} job(s) queued for catch-up "
                               f"(market_open={market_open})"),
            "metadata": {"market_open": market_open, "scheduled": scheduled},
        })
    except Exception as e:
        logger.warning("[catchup] could not log summary: %s", e)


def install_warm_fundamentals_cron(trading_scheduler, db):
    """Issue 2 — wire the fundamentals warm-fill as a nightly cron (18:30 ET
    weekdays, after the full post-close cascade) so >80% coverage is
    maintained hands-free. Added onto the existing BackgroundScheduler."""
    try:
        sched = getattr(trading_scheduler, "_scheduler", None)
        if sched is None:
            logger.warning("[catchup] no APScheduler on trading_scheduler — "
                           "warm-fundamentals cron not installed")
            return False
        from apscheduler.triggers.cron import CronTrigger

        def _job():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(warm_fundamentals_sweep(db))
            except Exception as e:
                logger.error("[catchup] warm-fundamentals cron failed: %s", e)
            finally:
                loop.close()

        sched.add_job(
            _job,
            CronTrigger(day_of_week="mon-fri", hour=18, minute=30,
                        timezone="US/Eastern"),
            id="warm_fundamentals_nightly",
            name="Nightly Fundamentals Warm-Fill",
            replace_existing=True,
        )
        logger.info("[catchup] warm-fundamentals nightly cron installed "
                    "(18:30 ET Mon-Fri)")
        return True
    except Exception as e:
        logger.error("[catchup] install warm-fundamentals cron failed: %s", e)
        return False
