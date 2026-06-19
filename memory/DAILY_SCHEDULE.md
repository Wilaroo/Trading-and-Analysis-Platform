# DAILY_SCHEDULE.md — TradeCommand Time-Sensitive & Scheduled Operations
> Canonical reference for EVERYTHING the system does on a clock.
> All times **ET**. Sources: `trading_scheduler.py`, `eod_generation_service.py`,
> `scheduler_service.py`, `position_manager.py`, `opportunity_evaluator.py`,
> Windows `.bat` Task Scheduler entries, AGENTS.md §12/§15.
> **RULE: if you add/change any scheduled job, cron, window, or worker loop,
> update this file in the same commit.** (Same discipline as AGENTS.md §15.)
> Last full audit: 2026-06-12 (v322v era).

---

## 1. OVERNIGHT (every night)
| Time | What | Where | Notes |
|---|---|---|---|
| ~2:00 AM | IB Gateway daily auto-restart | IBKR (external) | Sessions drop; expected. |
| 2:15 AM | `PostRestartAuto.bat` | Windows Task Scheduler | Re-login IB Gateway, restart pusher, resume collection queue. |
| 2:15 AM | IB Collection Auto-Resume | `trading_scheduler` | Backend-side resume of historical collection. Fixed v322v (AttributeError killed it nightly before 2026-06-12). |
| Cron (night) | `NightlyAuto.bat` | Windows Task Scheduler | StartTrading → health wait → nightly Smart-Backfill cycle → exit. |

## 2. PRE-MARKET (weekdays)
| Time | What | Where | Notes |
|---|---|---|---|
| 6:00 AM | Earnings-calendar refresh | `trading_scheduler` (v19.34.203) | Feeds earnings-risk gate. |
| 6:30 AM | Pre-market briefing | `scheduler_service` | Daily briefing generation. |
| 9:25 AM | `StartTrading.bat` (operator) | Windows | ⚠️ Step 2 does `git checkout -- . && git pull` — WIPES uncommitted code. Spark restart via `spark_stop.sh`/`start_backend.sh`. |
| Boot+0s | Session restore (open/closed trades) | `bot_persistence` | v322t: full-field rehydration — `Restored N open trades` only logs when N>0. |
| Boot+~75s | Missed-EOD boot sweep | `position_manager` (v322s) | Flattens any `close_at_eod` trade that escaped a prior 15:45 window (process-down case). Silent = good. |
| Boot | Orphan-GTC sweep, naked-position sweep, boot reconcile | reconcilers | Boot order matters — loops sleep at start (AGENTS.md §15). |

## 3. MARKET HOURS 9:30–16:00 — continuous worker loops
| Cadence | Loop | Notes |
|---|---|---|
| scan-tick | Scan loop (`_scan_loop`) | Master signal evaluation + entry firing. |
| 15 s | Kill-switch monitor | Realized+unrealized PnL vs daily-loss cap (v19.34.123). |
| 30 s | Mid-bar tick lifecycle | Tick→bar persister. |
| 45 s | Realized-PnL autosync | Syncs `bot_trades.pnl` from IB executions. |
| 45 s | Stale-pending reaper | Cancels orders stuck Pending Submit. |
| 60 s | Share-drift loop | IB-vs-bot share drift → `share_drift_events`. |
| 60 s | Orphan reconcile loop | Continuous orphan adoption/ejection. |
| 60 s | Quote-resub watchdog | v19.34.80 — verifies pusher re-subscribes landed. |
| 5 min | Shadow Signal Update | `trading_scheduler`, market hours only. |
| rolling | Scalp-decay sweep | 60-min decay for scalp-STYLE trades (v322u: style-aware; never touches swing/multi_day/position). |

## 4. EOD RISK WINDOWS (weekdays — hard-coded sequence)
| Time | What | Notes |
|---|---|---|
| 15:35 | EOD no-new-entries cut | **WARN-ONLY soft cut** (operator decision 2026-06-11). Hard cut at grace expiry. |
| 15:45 | RegT bracket cutoff + EOD flatten pass | `close_at_eod` styles flattened; brackets can no longer be attached. |
| 15:55 | EOD close sweep (final) | Catches stragglers. |
| 15:56 | Final cutoff | Post-sweep guard. |
| 16:00 | Market close | Book must be flat for `close_at_eod` styles. |

## 5. POST-CLOSE LEARNING CASCADE (weekdays, order matters)
| Time | Job | Where |
|---|---|---|
| 16:00 | Daily Analysis (medium-learning services) | `trading_scheduler` |
| 16:01 Fri | Friday close snapshot | `eod_generation_service` |
| 16:15 | Edge Decay Check | `trading_scheduler` |
| 16:25 | Confidence Gate Outcome Reconcile | `trading_scheduler` |
| 16:30 | Confidence Gate Calibration | `trading_scheduler` |
| 16:30 | Daily Recap (DRC) generation | `eod_generation_service` |
| 16:30 Fri | Weekly Report Generation | `trading_scheduler` |
| 16:35 | Regime Expectancy Refresh (T6) | `trading_scheduler` |
| 16:35 | Entry-Price ↔ IB.avgCost Sync (v19.34.148) | `trading_scheduler` |
| 16:35 | EOD Daily-Bar Top-Up (v322g) | `trading_scheduler` |
| 16:45 | Playbook Analysis | `eod_generation_service` |
| 16:50 | Landscape Grading | `eod_generation_service` |
| 17:00 | Self-Reflection | `eod_generation_service` |
| 17:00 | Learning Connections Sync | `trading_scheduler` |
| 17:10 | Nightly ADV Cache Rebuild (v322g) | `trading_scheduler` |
| 17:30 | Learning-Stats Full Rebuild (v19.34.200) | `trading_scheduler` |
| 17:30 | RS Leadership Nightly Compute (v322) | `trading_scheduler` |
| 18:00 | Multiplier Threshold Optimizer | `eod_generation_service` |
| 18:30 | Nightly Fundamentals Warm-Fill (v399) | `scheduler_catchup` (cron on `trading_scheduler`'s APScheduler) — clientId-11; lifts `symbol_fundamentals_cache` coverage hands-free |

## 5b. BOOT-TIME CATCH-UP / STALENESS GUARD (v399)
> `services/scheduler_catchup.py`, wired in `server.py` startup. Fixes the
> in-memory `BackgroundScheduler` flaw (no persistence / no misfire grace →
> missed jobs silently skip when the app is closed during a cron window).
- **~startup+120s**: `run_catch_up_sweep()` checks each catch-up-eligible job's
  last *successful* run (from `scheduled_task_logs` / output-collection
  freshness) vs its last *expected* fire (business-day aware). Overdue jobs are
  **auto-staggered** and re-run (Mongo-only 20s apart; IB/heavy 120s apart).
- **Holiday-aware**: `_is_market_holiday()` (2026 US calendar baked in) +
  `_market_currently_open()` — on a full-day holiday the live session is treated
  as CLOSED so market-unsafe catch-ups (warm-fundamentals on clientId-11,
  entry-price sync) may run on the free socket instead of wrongly deferring.
- Writes a `catch_up_sweep` row to `scheduled_task_logs` each boot (visible in
  `diag_v399`). NOTE: `[catchup]` `logger.info` lines are NOT captured by the
  console log handler — the Mongo row is the source of truth.
- KNOWN MINOR: jobs that don't call `_log_task_result` (`learning_stats_rebuild`,
  `earnings_calendar_refresh`) have no task-log row → probe returns None → they
  re-run on every boot (harmless/idempotent). Refine to collection-probe if the
  needless re-run ever matters.

## 6. WEEKEND
| Time | What | Where |
|---|---|---|
| Sat 8:00 AM | `WeekendAuto.bat` — full batch: backfill + ML training + simulations | Windows Task Scheduler |
| Sat 12:00 PM | Weekend Landscape Prewarm | `eod_generation_service` |
| Sun 2:00 PM | Weekend Briefing generation | `eod_generation_service` |
| Sun 3:00 AM | Institutional-Ownership Refresh | `trading_scheduler` |
| Sun 10:00 PM | Weekly Model Revalidation | `trading_scheduler` |

## 7. FAILURE MODES TIED TO THE CLOCK (learned the hard way)
- **Backend down during 15:45–16:00** → EOD flatten escapes → overnight carry
  (ACMR 65h incident). Mitigated by v322s missed-EOD boot sweep.
- **Friday crash** → escape carries the whole WEEKEND. Watch Friday boots.
- **2:00 AM IB restart** → anything scheduled 2:00–2:15 must tolerate a dead
  Gateway. Auto-resume at 2:15 exists for this (fixed v322v).
- **StartTrading.bat git wipe at 9:25** → any uncommitted DGX code is LOST.
  Commit + push before every restart, always.
- **Post-close cascade ordering** → gate calibration (16:30) needs Daily
  Analysis (16:00) outcomes; RS leadership (17:30) needs daily-bar top-up
  (16:35) + ADV rebuild (17:10). Don't reorder casually.
- **App not running 24/7** → wall-clock cron jobs silently skip when the app
  is closed during their window (no persistence/grace in BackgroundScheduler).
  Mitigated by the v399 boot catch-up sweep (§5b).
- **gate_calibration was DEAD for 35 days** (≤ 2026-06-19) — `name 'v' is not
  defined` NameError in `gate_calibrator.py` bucket_analysis ({**v} → {**buckets[k]}).
  Fired nightly but crashed at result assembly → thresholds never recalibrated.
  Fixed v399. Watch `last_run_age` vs `last_ok_age` gaps in `diag_v399` — a large
  gap = a job firing but failing every time.
