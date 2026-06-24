# v403 — daily_breakout SUPPRESSED (swing bleeder) — 2026-06-24

## Finding (setup-EV audit drill-down, days=30, horizon=swing)
`daily_breakout` was the dominant swing bleeder: **n=16, 0.0% win, avg -0.595R, total -9.52R**
(~61% of the entire swing -EV). Drill-down:
- BY DIRECTION: 100% long (it's a long-only 20d-high breakout).
- BY REGIME: HOLD n=9 (-0.756R), RISK_ON n=7 (-0.389R) — loses in BOTH postures → no safe regime to
  gate into with this sample.
- BY CLOSE_REASON: `oca_closed_externally_v19_31` n=8 @ -0.90R (= 75% of the bleed; ran to protective
  stop), `v5_operator_close_panel` n=4 (operator already manually cutting), stop_loss/eod/emergency = rest.
- Failure mode: breakout triggers → immediate reversal → stop. Classic breakout failure in a
  mean-reverting/chop market. NOT a gap tail (no -2R/-3R outliers), NOT a bug (legit OCA stops).

## Context vs v356
v356 VALIDATED daily_breakout +EV over a 180-day MULTI-REGIME replay (24,086 events, +0.06R, +1455R).
The 0/16 here is a 30-day CHOP-window result — regime-conditional failure, not a broken detector.

## Action: SUPPRESS via env (reversible, operator-controlled)
✅ **CONFIRMED LIVE 2026-06-24** — `backend/.env:77` `DISABLED_SETUPS=vwap_fade_short,daily_breakout`,
backend restarted, parsed blocklist verified `['daily_breakout','vwap_fade_short']`.
Blocks at the entry gate (trading_bot_service `_disabled_setups()` → reason_code "setup_disabled").

## ⏰ RE-ENABLE CONDITION (do NOT leave disabled forever — it's +EV in trend regimes)
Re-enable daily_breakout when EITHER:
  (1) market regime shifts to sustained TREND/RISK_ON (breakouts working again), OR
  (2) a fresh `diag_v356_daily_breakout_replay.py` re-run (recent 60–90d) shows it back to +EV, OR
  (3) the 2026-07-08 TQS re-audit / setup-EV re-check shows daily_breakout avg_r > 0 on n>=15.
Re-check command: `GET /api/slow-learning/setup-ev/report?setup=daily_breakout&days=30`.

## Next swing watch-item (not yet actioned)
`trend_continuation_short` — n=24 (only non-thin besides daily_breakout), avg -0.092R but winsor -0.212R
(positive outliers masking consistent small losses). Marginal — watch; revisit if it crosses into
bleeding (avg_r<=-0.10) with more closes.
