# v399b — Diagnostics: Data Schedule punchlist + TQS Coverage gauge

Date: 2026-06-19. Deployed via paste.rs patcher (patch_v399b.py). Frontend
change → required `yarn build` + `./start_backend.sh --force`. Verified live.

## What shipped
Two new sub-tabs in the **Diagnostics** tab (DiagnosticsPage.jsx SUB_TABS):

1. **Data Schedule** (`DataSchedulePanel.jsx`) — productized `diag_v399`.
   Punchlist grouped by DAILY_SCHEDULE categories. Per job: last run, last
   *success*, next scheduled fire (live from APScheduler), output-data
   freshness, issue flag (ok/stale/failing/never_run). FAILING = last-success
   lags last-run (the gate-calibration failure mode). Shows last boot catch-up.
   - `GET /api/diagnostics/data-schedule`
2. **TQS Coverage** (`TqsCoveragePanel.jsx`) — productized `diag_tqs_coverage`.
   Real-vs-default % per pillar/sub-score, 7/30/90d window toggle. Tell =
   v391 descriptor verdict == "No data".
   - `GET /api/tqs/coverage?days=N`

## Files
- NEW backend/routers/data_diagnostics.py (router, no prefix, full paths;
  registered in server.py Tier-1 block after sentiment_refresh_router).
- NEW frontend/src/components/sentcom/v5/DataSchedulePanel.jsx
- NEW frontend/src/components/sentcom/v5/TqsCoveragePanel.jsx
- EDIT server.py (router include), DiagnosticsPage.jsx (import + 2 sub-tabs +
  2 render cases).

## Verified live (2026-06-19)
- /api/tqs/coverage: overall 87.2% (2270/2604 real, 93 alerts w/ descriptors).
- /api/diagnostics/data-schedule: counts {ok:21, never_run:1}. gate_calibration
  now OK. weekend_briefing = never_run (correct — scheduled Sun 14:00 ET).

## Notes / follow-ups
- Coverage measured only over post-v391 alerts (those carrying descriptor
  `display` blocks); legacy alerts excluded by design.
- Two 🔴 score blind spots remain (deferred plumbing, NOT schedule issues):
  Setup→Tape (no live tape feed) and Execution→Entry-Tendency (only 2% of
  trade_outcomes carry real entry_slippage; trader_profile never populated —
  wiring run_daily_analysis would resurrect the v391 false-positive, so DON'T).
- 🟡 Financials/Float/Institutional/Sector on auto-improve path via nightly
  18:30 warm-fundamentals cron + draining backfill. Re-run diag_tqs_coverage
  after to confirm the gauge tracks the lift.
