# Backlog / Future Ideas

## ⭐ UNIFIED + TUNABLE SHADOW-TRACKING UI (saved 2026-06-23 — operator request, "C" from P5)
One consolidated, operator-tunable cockpit surface for ALL shadow/observe instrumentation, instead of
today's scattered tiles + raw JSON endpoints. Build LATER (after enough P3/P4/P5 data accrues).
- **Consolidate these feeds into one panel:**
  - P3/P4 shadow ARMS — `GET /api/slow-learning/shadow/arm-report` (champion / unified_1a2a / gate_off /
    regime_fit): win% + raw & size-weighted R + GO/REDUCE/SKIP split.
  - P5 thesis-invalidation — `GET /api/slow-learning/thesis-invalidation/report` (regime_hostile_cell +
    hard_regime_flip): would-have-exited-R vs held-R delta, helped/hurt counts.
  - Existing shadow_signals + shadow_filters (Phase-6) + P-WIRE regime shadows (regime_shadows[]).
  - Live Shadow-vs-Real win-rate tile (already in ShadowVsRealTile.jsx).
- **Tunable knobs exposed in the UI (read live, write to env/flags):** REDUCE_STEP, REGIME_REDUCE_MULT,
  T6 hard_r/soft_r/min_eff_n, regime suppression mode (shadow|active), THESIS_INVALIDATION_MODE
  (off|observe|active), SHADOW_ARMS_ENABLED.
- **Promote-to-live controls:** one-click "promote arm" (flip the live decision authority to the winning
  arm) + "activate regime suppression" + "activate thesis-invalidation exits" — each gated behind a
  confirm + a probation/capital-ramp window (bounded autonomy, never auto-flips).
- Design per /app/design_guidelines (Control-Room dark glass, cyan/amber/rose; NO purple). Ties to the
  V6 Track-B cockpit (S4 STAND-DOWN abstention state, S5 thesis-invalidation tag, S6 Strategy Autonomy).



## Setup-EV-Audit live dashboard (saved 2026-06-18)
Add `GET /api/scanner/setup-ev-audit` + a small V5 tile that surfaces, per setup:
verdict (preserve / long-only / rewrite / suppressed), last-audited EV (winsorAvg R + win%),
sample size, and audit date. Turns the per-setup build-docs (v353–v359…) into a live dashboard
so the operator can see at a glance which detectors are doctrine-aligned vs pending.
Source of truth: the memory/v3xx_*_build.md docs (could seed a small `setup_ev_audit` Mongo
collection the patchers/diag scripts write to). P2 — do after the setup-alignment queue.

### Adjudicated so far (Replay→Validate→ground-truth template)
- v353 second_chance — re-aligned (gated RR 1.5–2.5)
- v354 vwap_bounce — SUPPRESSED (negative-EV)
- v355 orb — REWRITTEN (true 15-min OR doctrine)
- v356 daily_breakout — PRESERVED (naturally +EV)
- v357 fashionably_late — SUPPRESSED (negative-EV)
- v358 daily_squeeze — LONG-ONLY (short branch -EV)
- v359 squeeze — SUPPRESSED (negative-EV daily-compression duplicate of daily_squeeze)
- v360 first_move_up + first_move_down — BOTH SUPPRESSED (negative-EV counter-trend morning fades)
- v361 big_dog — TIGHTENED (min-price $10 + min-stop 1.0%; baseline breakeven -> +0.097R win53% n=268)
- v361b big_dog/puppy_dog DOCTRINE RE-AUDIT — both are loose proxies (no mid-day window/PDH/cons-stop/trail); keep v361 live, queued P1 doctrine rewrite
- v362 gap_give_go — DOCTRINE REWRITE (1-min give->consolidation->range-break, cons-low stop, 2R; +0.233R win47% n=492 vs ~+0.07R loose code)
- v363 spencer_scalp — DOCTRINE REWRITE (LONG-only; 20-min tight range <15% dayRange upper-1/3, vol-surge break, range-low stop, 2R; +0.04-0.06R; short dropped, all-day)

### Queue remaining
NONE — scalp/intraday cheat-sheet adjudication queue COMPLETE.

### Future enhancements
- Scaled measured-move exits (spencer 1R/2R/3R; gap_give_go Move2Move double-bar-break trail) — position-mgmt layer.
- v364 big_dog/puppy_dog doctrine rewrite — EVALUATED, NOT SHIPPED (doctrine +0.02-0.04R < shipped v361 +0.097R; kept v361). See memory/v364_big_puppy_dog_eval.md.
