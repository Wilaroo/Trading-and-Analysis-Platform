# v399 — Scheduler Boot Catch-Up (Staleness Guard) + Gate-Calibration Fix

Date: 2026-06-19 (Juneteenth holiday — used as a safe dry window).
Deployed via paste.rs patcher; committed/pushed from DGX (main: a2cb54f →
09495df2 cleanup → 0b94a39b gitignore). Verified live on DGX.

## Problem
- In-memory `BackgroundScheduler` (trading_scheduler.py, eod_generation_service.py)
  has NO persistence and NO misfire_grace_time → when the app is closed during a
  job's cron window, that day's job silently skips and never retries. User does
  not run the app 24/7.
- AUDIT BONUS: `diag_v399` revealed `gate_calibration` had `last_ok_age = 35d`
  while `last_run_age = 18h` — firing nightly but crashing every time with
  `name 'v' is not defined`. Confidence-gate thresholds had not recalibrated
  in over a month.

## Changes
1. `services/ai_modules/gate_calibrator.py` — `bucket_analysis` comprehension
   used `{**v}` inside `for k in sorted_buckets` (v undefined) → `{**buckets[k]}`.
2. `services/scheduler_catchup.py` (NEW):
   - `run_catch_up_sweep(db, trading_scheduler, eod_service)` — spawned in
     startup; sleeps 120s, then for each registered job compares last-success
     (scheduled_task_logs / eod_generation_log / output-collection freshness)
     vs last-expected-fire (business-day aware). Overdue → auto-staggered re-run.
   - Holiday-aware: `_US_MARKET_HOLIDAYS_2026`, `_is_market_holiday`,
     `_market_currently_open`. Market-unsafe jobs (warm-fundamentals clientId-11,
     entry_price_sync) defer only when live session truly active (not on holidays).
   - `warm_fundamentals_sweep(db)` — standalone clientId-11 fundamentals warm-fill
     mirroring /api/short-data/warm-fundamentals (shares its `_warm_progress`).
   - `install_warm_fundamentals_cron(ts, db)` — adds 18:30 ET Mon-Fri cron onto
     trading_scheduler's APScheduler (Issue 2 — hands-free fundamentals coverage).
3. `server.py` startup — installs the warm-fundamentals cron + spawns the sweep.

## Verified (live, 2026-06-19)
- `catch_up_sweep` row written: "2 job(s) queued for catch-up".
- `gate_calibration` last_ok 35d → 13m, "Calibrated from 239 outcomes: GO>=40".
- `learning_stats` output 4m fresh (caught up).
- Holiday correctly treated as session-closed.

## Known minor / follow-ups
- `learning_stats_rebuild` + `earnings_calendar_refresh` don't call
  `_log_task_result` → no task-log row → catch-up sees None → re-runs every boot
  (harmless/idempotent). Could switch their freshness probe to collection-based.
- `[catchup]` `logger.info` lines NOT captured by console log handler; the
  Mongo `catch_up_sweep` row is the source of truth. Bump level if visibility wanted.
- Fundamentals coverage still ~33% (roe/net_margin), target >80%. Nightly 18:30
  cron will build it up; a manual full warm-fill over a weekend accelerates it.
- `adv_cache` collection name in diag [B] is a wrong guess (job logs success);
  real ADV output lands elsewhere — cosmetic diag issue only.

## Files of reference
- services/scheduler_catchup.py
- services/trading_scheduler.py, services/eod_generation_service.py
- services/ai_modules/gate_calibrator.py
- routers/short_data.py (/api/short-data/warm-fundamentals)
- memory/DAILY_SCHEDULE.md §5/§5b/§7
