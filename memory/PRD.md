# TradeCommand / SentCom — Product Requirements


> **🧭 2026-06-26 — V6 Phase C: `/v6` real route PROMOTED + symbol search shipped (additive, live V5 untouched).**
> (1A) `ChartVerdictPanel` now has a **symbol search box** (type e.g. TSLA + Enter/"go" → drives
> ChartPanel + Verdict strip + Thinking/triggers via `onSymbolChange`→`setSelectedSymbol`); fixes the
> "can't pick a chart when the scanner is empty pre-market" gap. Sandbox-verified end-to-end (TSLA
> switched chart/verdict/thinking; empty data expected). (Phase C) `App.js` `isV6ShellPreview` now also
> matches the `/^\/v6(\/|$)/` pathname, so the shell is reachable at the clean **`/v6`** route while the
> legacy `?preview=v6shell` query still works and **V5 stays the default at `/`**. Verified: `/v6` renders
> the shell, `/` does NOT. SPA deep-link works because the DGX serves the frontend via `yarn start`
> (webpack historyApiFallback) — no nginx change needed. Files: `components/sentcom/v6/ChartVerdictPanel.jsx`,
> `pages/V6ShellPreview.jsx`, `App.js`. DEPLOY: Save to GitHub → DGX pull → `yarn build` + hard-refresh
> (or just navigate to `/v6` on the running dev server). NEXT: vertical layout proportion tuning (1B,
> deferred by operator), then P0 tape-calibration RTH verification.



> **🧭 2026-06-26 — V6 Phase B CORE PANELS COMPLETE (additive `?preview=v6shell`, live V5 untouched):**
> The shell is now a full working cockpit — DLP **Risk rail** (`/api/safety/risk-rail`), real
> **Scanner** + **Open Positions** (live `useSentCom*` hooks), **Chart+Verdict** center
> (`ChartPanel` + `/api/scanner/symbol-trace` gate-funnel verdict), glass-halo **Thinking pane**
> (`UnifiedStreamV5` + §A **trigger-progress** micro-bars via `/api/scanner/trigger-progress/{sym}`),
> and the rose-only **CRITICAL action bar** (FLATTEN / CANCEL-ORPHAN / RESET-KS / PUSHER-STATUS) wired
> to real safety endpoints. App-state via `/api/safety/system-state` (push-fresh recalibrated).
> All sandbox-verified (empty data) + DGX-deployed; populated visual states validate on DGX.
> NEXT: Phase C — promote to a real `/v6` route (still behind V5 default). Remaining polish: chart
> bars need DGX historical data; selected-symbol-driven verdict/triggers exercised live.


> **🧭 2026-06-26 — V6 Phase B (slice a+b) shipped (additive `?preview=v6shell`, live V5 untouched):**
> (a) real `ScannerCardsV5` + `OpenPositionsV5` panels mounted in the shell, fed by the same live
> `useSentCom*` hooks as V5; (b) new `GET /api/safety/system-state` (cheap, 2s-pollable §3
> compute_app_state) + `useAppState` repointed to it (graceful health fallback). Sandbox-verified
> (empty data); real visual pass = `yarn build` on DGX. NEXT: Chart+Verdict, Thinking pane,
> CRITICAL action bar, Risk rail → Phase C real `/v6` route.


> **👁️ 2026-06-26 — FLAG/OBSERVE WATCHLIST:** `memory/WATCHLIST_pending_evaluation.md` is the
> single tracker for every env flag, shadow/observe-mode feature, and data-accruing check that
> still needs a promote/tune/kill decision (tape deferred A/B, TQS dormant dials, thesis-
> invalidation, strategy-autonomy, shadow arms, Entry-Edge Phase-0 coverage, scheduled re-checks,
> loser cleanup). Review it before deciding to switch anything on/off.


> **🧭 2026-06-26 — P0 TAPE-CALIBRATION resolved via DEFERRED tape-confirmation (JIT Level-2). ALL env-gated, DEFAULT OFF == byte-identical legacy.**
> Root cause confirmed: with only a 3–6 symbol L2 entitlement, `_get_tape_reading` falls back
> to `100/100` sizes (imbalance 0) for ~99% of names → `tape_score 0` → fails the `>=0.2`
> positive-proof gate → 97% of HIGH/CRIT intraday alerts rejected (656→17 on 06-25). The L2
> router (`l2_router.py`, already running) rotates the 3 slots onto top scalp/intraday EVAL
> alerts, but the tape gate ran INLINE at alert-creation — BEFORE L2 arrived. FIX (operator
> chose "A+B"): tape is now the LAST gate. An alert passing every OTHER gate (auto-exec
> enabled + priority HIGH/CRIT + not-stale + EV-quality) but lacking live L2 is held
> `tape_pending` (NOT rejected); the L2 router (Mode A, `TAPE_CONFIRM_MODE=router`) or a
> per-candidate JIT subscribe (Mode B, `=jit`) puts depth on it, and a confirmation pass
> auto-executes ONLY on NON-ADVERSE flow (block strong opposite L2 imbalance / momentum-down).
> ENV (all DEFAULT OFF/legacy): `TAPE_CONFIRM_DEFERRED`, `TAPE_CONFIRM_MODE=router|jit`,
> `TAPE_NONADVERSE_GATE`, `TAPE_ADVERSE_SCORE` (0.3), `TAPE_ADVERSE_L2_IMBALANCE` (0.25),
> `TAPE_CONFIRM_PENDING_TTL_S` (90), `TAPE_CONFIRM_TICK_S` (3), `TAPE_JIT_POLL_S` (4),
> `TAPE_CONFIRM_FALLBACK=expire|nonadverse_l1`. Diagnostic: `GET /api/scanner/tape-confirm/status`.
> Verified in sandbox: 23/23 new pytest + 37/37 with related suites; runtime Mode-A confirm/
> adverse/TTL-expire + Mode-B JIT validated; live endpoint shows `deferred_enabled=false`,
> `loop_running=false` (legacy intact). DEPLOY: Save to GitHub → DGX pull → `./start_backend.sh
> --force`; activate by setting `TAPE_CONFIRM_DEFERRED=true` (+ `TAPE_CONFIRM_MODE`) then watch
> the funnel + `/api/scanner/tape-confirm/status`. Files: `services/enhanced_scanner.py`,
> `routers/scanner.py`, `tests/test_tape_confirm_deferred.py`. NOT YET tested on live DGX/IB.
> NEXT: backside time-decay exit (P2); loser cleanup (P2); V6 Phase B (P1).


> **🧭 2026-06-25 (cont.) — V6 Plan A · Phase A STARTED (shared-primitive extraction, ZERO behavior change).**
> Resumed the last in-progress item. Two §10 shared primitives lifted (V6_INTEGRATION_v110_v114):
> (1) `utils/orderPipelineSplit.js` — the v19.34.110 ORDER-tile split, lifted out of
> `SentComV5View.derivePipelineCounts` (now calls it; byte-identical output; smoke 9/9 vs an inline
> oracle). (2) `components/sentcom/v6/RowMetaChips.jsx` — inline-flex chip-cluster wrapper (children-based;
> single child == bare chip, so V5 is identical). Both V5 call-sites (`OpenPositionsV5`, `ScannerCardsV5`)
> now route TradeStyleChip through `<RowMetaChips>`. Verified: clean webpack compile + V5 cockpit renders
> (ORDER tile empty-state `0`/`—`, panels mount, no crash). Live row visuals confirm on the DGX (sandbox has
> no scanner/position data). NEXT: continue Phase A pure-component extractions → Phase B V6 shell + new
> `/api/safety/system-state` etc. (needs operator steer on Phase B scope before the multi-day shell build).


> **🧭 2026-06-25 — STATUS (forked session).** PROMOTE Edge Score is LIVE/`active` (TQS demoted).
> Done this session: (1C) GRADE is now a TRUE per-archetype percentile (graded within the
> trade's setup×direction "kind" cohort, global fallback) + per-cell confidence CI + a clean
> `entry_context.entry_edge.triple` UI contract; gate exposes `grade_cohorts` (DGX: 44).
> (2A/2B) Data-integrity gate CONFIRMED OK: Phase-0 stamping is wired correctly — the 0%
> coverage was because pre-build trades have NO Phase-0 keys (`ec_has_sector_key=False`); it
> accrues from the next RTH session. New unified scorecard `GET /api/integrity/data-scorecard`
> (Phase-0 coverage + TQS pillar darkness + grade honesty + canonical feed liveness).
> (V6 workstream 3 START) Edge-Score Provenance ring + drawer vertical slice shipped &
> testing-agent verified 7/7: `GET /api/slow-learning/entry-edge/recent` + `?preview=v6edge`
> (`EdgeProvenanceRing` decision donut + `EdgeDrawer`). Seal #2 closed/contained (v414 heal).
> NEXT: V6 Plan A Phase A (extract V5 panels) + verify Phase-0 + Edge triple on real DGX data
> next session.


> **🧭 2026-06-24 — ENTRY EDGE SCORE rebuild is the ACTIVE program. LOCKED PLAN: `memory/ENTRY_EDGE_SCORE_PLAN.md` (read before any scoring/TQS/gate work).**
> TQS deep-dive + entry-feature discovery (n=1002) proved BOTH decision authorities are
> noise: TQS composite spearman≈0 vs MFE (all 5 pillars dead, root cause = absent→neutral-50
> variance collapse + anti-predictive hardcoded tables + no setup×regime interaction + zero
> outcome-calibration), and the ML gate confidence_score is −0.029 vs MFE and INVERTED
> (`go` worse than `reduce`). DECISION: replace both with ONE outcome-calibrated **Entry Edge
> Score** = triple **(EDGE expected-MFE-R · GRADE rolling per-archetype percentile 0-100, single
> number NO letter · CONFIDENCE per-cell eff_n/CI)** on the archetype cell
> `setup × direction × style × time_window × market/sector/symbol regime`, with hierarchical
> shrinkage. Grade ranks ("best of its kind"); EDGE decides (GO iff conservative edge > 0).
> Resolves the architecture program's P3 hinge (third path) and retires the patch-the-pillars
> premise. Sequence: **Phase 0 persistence (DONE backend, observe-only)** → P3′ Edge Score v1
> (shadow) → P4′ regime-conditional + shrinkage → promote to single authority → feed the scanner/
> focus-list (finding). Docs: `TQS_DEEPDIVE_AUDIT_2026-06.md`, `ARCHITECTURE_REVIEW_2026-06.md`
> (updated), `DATA_INTEGRITY_PLAN_2026-06.md` (Phase 0 folded in). Mockups: design_mockups concepts.
>
> **PHASE 0 SHIPPED (backend, observe-only, NO live behavior change):**
> `opportunity_evaluator.build_entry_context` now stamps `sector_regime`, `rs_rating`,
> `symbol_rs_regime` (new `_classify_rs_regime` band helper: leader≥80/strong≥60/neutral≥41/
> weak≥21/laggard/unknown), and reliable `trigger_price` onto entry_context — the regime + chase
> dimensions the regime-conditional model needs but build_entry_context historically DROPPED
> (sector_regime was computed on the alert then discarded; rs_rating never persisted). NEW read-only
> coverage report `services/entry_edge_coverage.py` + `GET /api/slow-learning/entry-edge-coverage/report?days=45`
> — reports per-field coverage % + `archetype_cell.complete_pct` (fraction of trades with ALL 7
> dims present = the gate for when P4' has enough fully-dimensioned data). Verified locally
> (compiles, imports, endpoint 200, RS-band logic green; n=0 on preview pod — real data on DGX).
> NEXT: operator pulls+restarts → after a live session run the coverage report; new fields should
> trend up from 0. If sector_regime/rs_rating stay dark, wire a sync fallback
> (rs_leadership_service.get_rating_cached / sector classifier) in build_entry_context.
>
> **P3′ EDGE SCORE v1 BUILT (read-only model + OUT-OF-SAMPLE lift proof):**
> `services/entry_edge_score.py` — additive expected-R = global_mean + Σ shrunk marginal deltas
> (time_window, direction, timeframe, priority, setup_type + quantile-binned regime_score/rsi/
> trigger_probability/tape_score; empirical-Bayes K=20; reconciled_* excluded). The score TRIPLE
> via `score_full()`: EDGE (expected-R) · GRADE (0-100 rolling per-archetype percentile, no letter)
> · CONFIDENCE (eff_n band) + per-factor "why" contributions. Endpoint
> `GET /api/slow-learning/entry-edge-score/report?days=120&target=mfe_r|realized_r&k_folds=5`
> evaluates OUT-OF-SAMPLE via K-fold CV → decile lift, OOS Spearman vs mfe_r AND realized_R,
> per-factor effects, and a per-(setup×direction) within-archetype grade-reliability check.
> Synthetic validation GREEN (`tests/test_entry_edge_score.py`): signal → OOS spearman 0.74,
> top-decile +0.58R vs bottom −0.84R; noise → conservative −0.04 (never invents lift); triple
> orders good vs bad correctly. NEXT: operator runs the report on the DGX (~808 real entries) to
> read REAL OOS lift vs the champion gate (−0.029/inverted); beat it → wire the live shadow arm
> (market-open work).


> **🔧 2026-06-24 (v408) — GENERALIZED orphan relink (Seal #1, env observe default).**
> Taxonomy proved 87% of the −$5,714 orphan leak = 6 large positions that lost bot
> tracking and got OCA-stopped on a synthetic 2% stop (ARM −$1,398, ALNY −$1,106,
> SHLD −$815, UAL −$666, ARMG −$531, VRT −$465). Operator confirmed **bot is the SOLE
> opener** → nothing is truly foreign; an untracked IB position is ALWAYS a bot trade
> whose lineage broke → RESTORE tracking, never flatten. `position_reconciler.py`:
> generalizes v405 relink — new `_find_recent_bot_predecessor` (most recent NON-synthetic
> bot_trade on symbol+dir, any close_reason, window `RECONCILE_RELINK_ANY_WINDOW_MIN`=4320m,
> excludes reconciled_* / entered_by^reconciled, directional+qty guards). When the v404
> stale-pending relink misses, inherit the predecessor's REAL stop/target/regime/TQS instead
> of synthetic 2% OCA; stamps `synthetic_source=relinked_predecessor` + emits
> `orphan_relink_predecessor_observe`/`orphan_relinked_predecessor`. SAFE: adopt-path
> stop/context only — NO order/close/reaper/kill-switch touch; existing `breached` guard
> handles already-fired stops. Env `RECONCILE_RELINK_ANY_PREDECESSOR`=observe(default)|fix|off.
> Heals the −$3,216 relinkable bucket (readopt/eod_reopen/reaped). Tests 22 green. Doc:
> `memory/v408_orphan_relink_general_build.md`. ROLLOUT: pull+restart (observe) → watch
> `orphan_relink_predecessor_observe` → set =fix. NEXT: Seal #2 record-less true_foreign
> (−$1,897, SHLD/UAL/VRT have no bot_trade in 240d) → then B (entry quality).

> **🧭 2026-06-24 (v407) — orphan CREATION-CAUSE taxonomy (read-only) — "stitch the cut".**
> v406 MFE/MAE repair APPLIED on DGX (29/29 corrupt rows healed). New read-only endpoint
> `GET /api/slow-learning/orphan-taxonomy/report` (`services/orphan_taxonomy.py`) classifies
> every closed `reconciled_orphan` by HOW it lost tracking — reaped_pending_filled |
> exit_overfill_residual | share_drift_excess | restart_orphan | true_foreign | unclassified —
> so each path is sealed in code (not band-aided on the stop). Per class: n / leak_R / leak_USD /
> markers / **fix_site** / samples (worst-first) + monthly_by_class trend + v405 relink_coverage
> (incl. `orphan_relink_observe` counts). Tests `test_orphan_taxonomy.py` (8) green; endpoint 200.
> **RUN ON DGX:** `curl -s "http://localhost:8001/api/slow-learning/orphan-taxonomy/report?days=120" | python3 -m json.tool`
> → paste back → patch dominant class's fix_site (env-gated observe→fix). Then pivot to the
> system-wide ENTRY-quality problem (−0.306R/trade) per operator "do A then B". Doc: `memory/v407_orphan_taxonomy_build.md`.

> **🔧 2026-06-24 (v406) — MFE/MAE writer fix (P1, the corrupt-data bug).** Two bugs, both reproduced:
> (1) manage-loop MFE/MAE tracked from `current_price` with no `<=0` guard → a stale/zero quote set
> `mae_price=0` → `mae_r≈-50R` permanently (the "-3R MAE, closed -0.06R" symptom); (2) winner_capture>1.0
> from sparse-tick MFE under-sampling. Fixes: `position_manager.py` guards the block (`_cp>0`);
> `pnl_compute._backfill_excursion_floor` now bounds mfe_r≥realized-favorable / mae_r≤realized-adverse
> (was: only filled when ==0); `mfe_mae_study` drops `|R|>10` legacy-corrupt rows (reports
> `corrupt_excursions_dropped`) + clamps capture≤1.0. Writer/read-model only — no order/reaper/close
> change. Historical corrupt rows excluded from study (not rewritten). Tests: `test_mfe_mae_fix.py` (6),
> suite 24 green. Unblocks time-decay exit study + the evidence for the orphan stop-width decision.
> Doc: `memory/v406_mfe_mae_fix_build.md`.
> **NEXT (user directive): orphan PREVENTION — "stitch the cut, don't band-aid".** Root-cause WHY
> orphans get created (reconciler guards v185/v264/v260 have gaps), categorize all 120 by creation cause,
> prevent each class (promote bot's own fills; flatten genuinely-foreign positions) so they never adopt.


> **🔧 2026-06-24 (v405) — orphan leak ROOT-CAUSE FIX (env-gated, observe default).**
> RCA confirmed via DGX diagnostics: order path is `BOT_ORDER_PATH=direct` (clientId=11,
> no clientId=10); direct-IB flaps 1-3×/day → a filled bot PENDING gets reaped
> (`stale_pending_auto_reaper`) + popped from `_pending_trades` during a flap → the
> reconciler adopts the live fill as a synthetic orphan with a TIGHTER 2% stop (58/120)
> → OCA stop-out → -19.7R (ACTIVE: May 50/-12.19R, Jun 70/-7.54R).
> FIX in `position_reconciler.py`: new READ-ONLY `_find_reaped_pending` + re-link in
> `reconcile_orphan_positions` — inherit the bot's REAL stop/target/regime/TQS from the
> reaped Mongo row instead of synthetic 2%. Env `RECONCILE_RELINK_REAPED_PENDING`
> (observe=default, fix, off); window `RECONCILE_RELINK_WINDOW_MIN`=90. Forensic event
> `orphan_relink_observe`/`orphan_relinked_reaped_pending`. Blast radius: ONLY the orphan
> stop/context stamp — no order/reaper/cancel/close/kill-switch change. Tests: 18 passed.
> Docs: `memory/v405_orphan_relink_build.md`, `memory/AUDIT_orphan_leak_2026-06-24.md`.
> ROLLOUT: pull+restart (observe) → watch `orphan_relink_observe` count → set =fix when happy.

> **🧭 2026-06-24 (v404) — reconciled_orphan leak RCA tooling + tqs_integrity n-aware gate.**
> - 🔴 **P0 RCA (in progress):** new read-only endpoint `GET /api/slow-learning/orphan-leak/report`
>   (`services/orphan_leak_rca.py`) traces the `reconciled_orphan` chain (predecessor entry_context →
>   orphan synthetic 2% stop → `oca_closed_externally`). Reports population/leak-R, close-reason mix,
>   synthetic_source split, predecessor linkage (recoverable context + stop-tightening), and the
>   re-adopt-loop core (the fixable $). Delivered as an ENDPOINT (not a `diag_*.py` script — those are
>   .gitignored, can't ship via Save-to-GitHub). Unit-tested (5/5) + smoke-tested.
>   **RUN ON DGX:** `curl -s "http://localhost:8001/api/slow-learning/orphan-leak/report?days=120&gap_min=120" | python3 -m json.tool`
>   → result routes the fix (re-link original context+stop on re-adopt, OR refuse fresh OCA on thesis-less
>   re-adopt). Fix will be env-gated observe→fix.
> - ✅ **SHIPPED:** `services/tqs_integrity.py` `anti_predictive` now requires an n-aware significance gate
>   (|corr| > ~2/√n) via pure helpers `_sig_threshold`/`_is_significant`/`_anti_predictive` — stops false
>   alarms on noise (the held v401 scalp-pillar flags). Report rows add `sig_threshold`+`significant`.
>   Tests: `tests/test_tqs_integrity_significance.py` (6/6). Build doc: `memory/v404_orphan_rca_tqs_sig_build.md`.
> - ⏳ NEXT after DGX orphan run: implement the orphan re-link/flatten fix; then MFE/MAE scaling bug (P1)
>   → backside time-decay (P2). Save-to-GitHub `main-2.0` → DGX pull.


> **⏰ 2026-06-24 — SCHEDULED RE-CHECK (DO NOT FORGET): TQS scalp-inversion re-audit.**
> **WHEN:** on/after **2026-07-08** (≥1 week earliest = 2026-07-01). Needs v401 feeds
> (Entry-Tendency live + horizon-aware tape, shipped 2026-06-24) to accumulate into the
> window AND grade samples to grow.
> **WHY HELD:** as of 2026-06-24 the TQS-integrity probe (`GET /api/slow-learning/tqs-integrity/report?days=30`)
> showed: ✅ compression FIXED (score SD **8.99**, `ok_spread` — so **v394 pillar-renorm is NOT needed**,
> do not build it); ❌ scalp grade INVERTED (C +0.116R/n65 > A -0.081R/n29) BUT this is **statistically
> insignificant** (t≈0.9, p≈0.38) and **every scalp pillar corr is below significance** (|corr|<0.09 at
> n=123; needs ≈0.18). Reweighting scalp now = fitting to NOISE. Intraday is clean/monotonic (A>B>C).
> **DECISION RULE for the re-check (only act if ALL hold):** (1) score still `ok_spread`; (2) scalp still
> inverted in `grade_by_horizon` with LARGER n; (3) a pillar on the SCALP row shows |corr| > ~2/√n AND
> hi_R < lo_R. The one *consistent* (not-yet-significant) signal is **execution is the most predictive
> pillar** (intraday corr 0.209, 0.47R hi-vs-lo spread) and v401 strengthens it — so the likely action is
> **bump execution weight on scalp/intraday** (`STYLE_WEIGHTS` in `services/tqs/tqs_engine.py`), NOT a
> renorm. Re-run the probe + the pillar parser (see `v401_feed_subscores_build.md`) before changing weights.



> **🧭 2026-06-23 — HORIZON-FUNNEL DIAGNOSTIC delivered (scalp/intraday under-firing).** Read-only:
> `GET /api/slow-learning/horizon-funnel/report?days=` builds evaluated(gate)→approved(GO+REDUCE)→taken
> (bot_trades)→realized-R per horizon class (scalp/intraday/swing/position) with a CHOKE label
> (under_emitted | gate_veto | capacity | healthy). Tested (test_horizon_funnel.py). NEXT: run on DGX after
> an RTH window; the choke label routes the fix — gate_veto→TQS anchor/horizon-aware gate (ties to the next
> TQS-integrity task); capacity→MFE/MAE study + raise the 25-position cap. Read the report before changing thresholds.



> **🧭 2026-06-23 (P5 FINISHED) — partial-TRIM (soft) + full-CLOSE (hard) thesis-invalidation exits.**
> New `PositionManager.trim_position()` (reuses scale-out broker path + exact bookkeeping, keeps a runner) +
> bot-side internal-stop tighten (never crosses price). Routing: hard_regime_flip→close, regime_hostile_cell→
> trim+tighten; natural escalation (soft trims, later hard flip closes the runner). Still DORMANT
> (THESIS_INVALIDATION_MODE=observe). Knobs: THESIS_INVALIDATION_TRIM_PCT/_TRIM_TIGHTEN(_FRAC/_BUFFER_PCT).
> Tested: test_p5c (trim bookkeeping+stop), test_p5b (close/trim routing), P5 observe regression green; backend 200.
> NEXT-UP QUEUE (operator, see ROADMAP top): (1) 🔴 TQS scoring reliability/integrity — close the ORIGINAL
> problem statement; (2) 🟠 scalp/intraday under-firing diagnostic; (3) 🟠 MFE/MAE study → time-decay for
> long-horizon trades and/or raise max_open_positions (currently 25, gated by SAFETY_MAX_POSITIONS).



> **🧭 2026-06-23 (P5-PHASE-2 + P6) — built AHEAD, both DORMANT/observe by default (zero live change).**
> - ✅ **P5-Phase-2 — ACTIVE thesis-invalidation close** (thesis_invalidation.py): `active` mode closes via the
>   bot's `close_trade(reason="thesis_invalidation:<trigger>")` ONLY after the trigger persists ≥
>   THESIS_INVALIDATION_HYSTERESIS_SECONDS (default 180s) and is still firing; bounded to
>   THESIS_INVALIDATION_ACT_TRIGGERS (default hard_regime_flip) + MAX_ACTIONS_PER_CYCLE (5). Default observe ⇒
>   dormant. Tested (test_p5b_active_close.py): no first-sight close; acts post-hysteresis; hostile-cell filtered.
> - ✅ **P6 — Strategy Autonomy read-model** (NEW strategy_autonomy.py): compute-on-read ENABLE/WATCH/DISABLE/
>   UNKNOWN per strategy family for the CURRENT regime band, from the SAME T6 expectancy table (+30/90d
>   term-structure) + latest market_regime_state; surfaces static DISABLED_SETUPS. PURE read-model, no behavior
>   change; active enforcement DEFERRED (STRATEGY_AUTONOMY_MODE default observe). Endpoint
>   `GET /api/slow-learning/strategy-autonomy/report`. Tested (test_p6_strategy_autonomy.py) + preview 200.
> - ⏳ NEXT: Save-to-GitHub `main-2.0` → DGX pull. After RTH, read both reports; flip a flag only where the data
>   is solidly +. Then build the unified tunable Shadow-Tracking UI (idea C). Backlog: P5 trim (partial) variant,
>   P6 active enforcement + probation-window measurement, live catalyst feed (negative-catalyst invalidation).



> **🧭 2026-06-23 (P5) — THESIS-INVALIDATION EXITS — OBSERVE-FIRST detector (regime-flip) — WIRED + E2E-TESTED.**
> ARC-3 P5, shadow/observe-first; **NEVER closes a position in phase-1** (logs would-be exits only).
> - ✅ New `services/thesis_invalidation.py`: per manage-cycle scan of open positions for a dying reason —
>   `regime_hostile_cell` (setup×dir×CURRENT band now hostile per the SAME T6 table P4 uses, AND not hostile
>   at entry = genuine flip) + `hard_regime_flip` (band flips opposite, long BULL→BEAR / short BEAR→BULL).
>   Records to `thesis_invalidation_signals` (deduped 1/trade×trigger). `generate_report` joins closed trades
>   → exit-at-signal R vs held R (avg_r_delta>0 ⇒ exiting beat holding), by trigger + helped/hurt.
> - ✅ Hook: sibling call in `_update_open_positions` (giant `update_open_positions` untouched). Flag
>   `THESIS_INVALIDATION_MODE=off|observe|active` (default observe; active deferred). Endpoint
>   `GET /api/slow-learning/thesis-invalidation/report`.
> - ✅ TESTED: e2e PASS (BULL-entry long now hostile in BEAR → both triggers @ −0.5R; dedup holds; report
>   exit −0.5 vs held −2.0 = +1.5 helped; self-cleans); endpoint 200. Deferred: negative-catalyst (no live
>   feed), setup-premise-broken (bespoke). Saved idea "C" (unified tunable shadow-tracking UI) to BACKLOG_ideas.
> - ⏳ NEXT: Save-to-GitHub `main-2.0` → DGX pull. After a session read /thesis-invalidation/report; if
>   avg_r_delta solidly +, design phase-2 ACTIVE trim/close (hysteresis). Else P6 (autonomous strategy on/off).



> **🧭 2026-06-23 (P4) — REGIME-FIT ABSTENTION AT L5 — 4th shadow arm `regime_fit` — WIRED + E2E-TESTED.**
> ARC-2 P4 done as a challenger arm (shadow-first; zero live risk). Reuses the Confidence Gate's existing
> `regime_suppression` (T6 data-driven per-setup×regime expectancy: SKIP if weighted-mean-R ≤ −0.50 n≥25,
> REDUCE if ≤ −0.12) which is computed live but only enforced in mode="active" (today shadow).
> - ✅ Pure `resolve_regime_fit()` = unified verdict (A1) + overlay: hostile cell → **ABSTAIN** (SKIP, size 0);
>   soft-hostile → size-down ×0.4 + GO→REDUCE; NONE/absent → unified unchanged. `ARMS` now 4 (champion /
>   unified_1a2a / gate_off / **regime_fit**). Wired into `shadow_arms.py` (passes `gate_result.regime_suppression`),
>   arm-report auto-includes it, `ShadowVsRealTile.jsx` shows teal "R-FIT".
> - ✅ TESTED: 5-case logic smoke + extended e2e PASS (regime_fit ABSTAINS on a hostile cell where unified
>   only REDUCES, self-cleans); `/shadow/arm-report` 200; frontend transpiles. Live alert→arm cycle is DGX-only.
> - ⏳ DELIVERY: Save-to-GitHub `main-2.0` → DGX pull. After a session, read `/shadow/arm-report`: if `regime_fit`
>   beats champion/unified on win-rate / weighted-R, promote (flip T6 active + adopt unified). NEXT: P5 thesis-
>   invalidation exits.



> **🧭 2026-06-23 (P3 SEAM-3) — TQS ↔ Confidence-Gate UNIFICATION via SHADOW-ARM HARNESS — WIRED + E2E-TESTED.**
> First build on the NEW direct-edit + Save-to-GitHub (`main-2.0`) workflow (paste.rs retired).
> - ✅ Pure logic (`unified_verdict.py` A1=`unified_1a2a` TQS-anchored single-multiplier, A2=`gate_off` TQS-only,
>   `champion`=live stacked dual-gate) verified: over-veto case (grade-B + gate SKIP) → champion KILLS (0.0),
>   unified REDUCES (0.42, not killed), gate_off GOES (0.7). Kills the 68% over-veto + the double-discount.
> - ✅ Wired (`shadow_arms.py` recorder → existing `shadow_signals` engine, tier="shadow", NOTHING to IB):
>   `ShadowSignal`+`record_signal` extended (arm/tier/alert_id/arm_decision/size_mult/status); injected at the
>   Confidence-Gate decision site in `opportunity_evaluator.py` BEFORE the SKIP return; new
>   `GET /api/slow-learning/shadow/arm-report` (per-arm win% + raw & **size-weighted R**); `generate_report`
>   excludes arm rows; `ShadowVsRealTile.jsx` gains an additive arm-compare strip. Toggle `SHADOW_ARMS_ENABLED`.
> - ✅ TESTED: py_compile + logic smoke + endpoints 200 (preview) + FULL e2e (`tests/test_p3_shadow_arms_e2e.py`
>   PASS, self-cleaning). LIVE alert→arm path is DGX-only (IB Unavailable in preview) → verified structurally.
> - ⏳ NEXT: Save-to-GitHub `main-2.0` → pull on DGX → accrue arms over RTH → read `/shadow/arm-report`; if
>   `unified_1a2a` weighted-R beats `champion`, promote to live authority. Then P4 regime-fit abstention arm.



> **🧭 2026-06-23 (cont.) — v400 TQS4 setup dials + fundamentals probe.** Patcher-only.
> - ✅ Probe OVERTURNED win_rate: DEGENERATE (raw WR ~0.55 everywhere → score ~62), NOT anti-predictive;
>   the −0.62 was a 1-outlier artifact. Real weight already only 0.15 (v305). No fix → logged as a
>   learning-stats data thread (win-rate not differentiating setups).
> - ✅ patch_v400 (commit 7db16cb1) LIVE — env dials `TQS_SETUP_PATTERN_SHRINK` + `TQS_SETUP_WR_SHRINK`,
>   both default 1.0/off. pattern is the real lever (75-90 bucket loses every window; opening_drive=85 →
>   0% win). A/B with `=0.5`/`=0.0` when ready.
> - ⏳ FUNDAMENTALS: diag_fundamentals_feed (paste.rs/p3phF) built to root-cause dark catalyst/earnings —
>   prime suspect = Date-vs-ISO-string query mismatch on news_articles/earnings_calendar. Awaiting DGX run.


> **🧭 2026-06-23 SESSION (TQS3 — persistence + inverse re-verify).** Patcher-only (paste.rs).
> - ✅ Committed prior TQS1+TQS2 (commit 5ad1a5b2; TQS_RENORM_PRESENT dormant).
> - ✅ RE-VERIFIED the 3 "inverse" inputs (diag P5jFM): premise OVERTURNED — only **setup.pattern**
>   weakly inverse (−0.08/−0.13); **context.regime** DEGENERATE (zero-variance, dead weight);
>   **relative_strength** now **POSITIVE** (+0.30/+0.35 — v254 already fixed it) → RS/regime
>   inversions DROPPED. Bonus: **setup.win_rate** strongly anti-predictive (−0.62/−0.19) — own probe pending.
> - ✅ **patch_v393_tqs_breakdown_persist** (commit 0d70c023) LIVE — `bot_trades` now persists
>   top-level `tqs_breakdown` (was 0%). Forward-looking. MFE/MAE confirmed NOT a gap (v240 floor + manage-loop).
> - ⚠ VERSION NUMBERING: v392/v393 reuse existing bare-track numbers; latest is v399b → use **v400+** for new work.
> - ⏳ NEXT: accrue post-v393 closes → re-run diag P5jFM at full coverage → decide pattern fix
>   (likely DOWN-WEIGHT static SMB ranking, NOT invert) + probe the setup.win_rate anti-signal.


> **🧭 2026-06-22 SESSION ROLLUP (TQS HONESTY AUDIT).** Patcher-only (paste.rs, anchored/SHA-guarded).
> - ✅ **TQS data-honesty audit** — diag_tqs.py (paste.rs/DANPT) + diag_tqs_b.py (paste.rs/kudA2),
>   both read-only, run clean on DGX. Classifies all 28 sub-scores OK/ABSENT/PROXY/DEFAULT.
>   Composite is crushed (40.9–65.5, p50 50.1, sd 4.22) — too many sub-scores pinned at neutral.
> - 🔴 **AI-model = fabricated 35 penalty** on ~100% of book (timeseries model gives 0 usable
>   forecasts → LiveAlert defaults non-None → "weakly disagrees" branch). FIX #1 BUILT+DELIVERED:
>   patch_tqs1_ai_honest_encoding.py (paste.rs/L7QJy) — absent AI → honest neutral 50; real
>   forecasts unchanged. APPLY PENDING. Verify: diag_tqs.py --hours 1 → ai_model off 35.
> - ✅ **VIX is HONEST** (98.7% real readings; 85 = correct calm-VIX score). No fix — earlier flag overturned.
> - 🟡 **earnings 100% absent** = coverage gap (319 obscure tickers, liquid universe uncovered;
>   is_reported never set → v390 drift dead). Data task, deprioritised.
> - 🟡 **RSI=100** + **R-capture=5%** degenerate-data smells (from live FITB card; FITB math verified
>   end-to-end ✓). NEXT: RSI clamp/min-bars guard, R-capture probe, tilt [0,100] clamp.
> - 🔵 BIGGER OPEN THREAD: timeseries AI model yields 0 usable forecasts for the live universe
>   ("models that generalize" mandate) — separate investigation.
> - ⏳ Carried: apply patch_c2 + verify FROZEN marks→0 next RTH (operator ack'd applying; awaiting confirm).


> **🧭 2026-06-22 SESSION ROLLUP (newest first).** Patcher-only delivery (paste.rs, span-SHA guarded).
> - ✅ **A10 trigger-drift gate** — LIVE on DGX (commit 99da78b0), block mode. Stops stale/extended auto-exec entries (skip when live price drifts > AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT, default 2%, from trigger). Verified live: MCO flipped to WOULD-BLOCK at 2.07%.
> - ✅ **B carry-forward dedup** — LIVE on DGX (commit 087be6fb). Hydrate collapses to newest per (symbol,setup,dir) + persist-prune. Verified: live alerts 148 → 19.
> - ✅ **diag_a11 v2** (paste.rs/KoJgM) — read-only ready-to-fire snapshot: real live drift, dupe-collapse, n≥3 concentration gate.
> - ✅ **diag_c** (paste.rs/TJBxG) — proved handoff's TGT=0.00 is RESOLVED (all 25 holds have target + OCA attached). Surfaced residual: 17/25 FROZEN marks (UPL=0).
> - 🔜 **C2 IB-mark fallback** — BUILT + tested (pytest 6/6), PASTED, apply pending. patch_c2 paste.rs/1U9U8, test paste.rs/sVHXH, CHANGELOG note paste.rs/yb3hx. Fixes frozen marks via IB's per-position marketPrice (bypasses pusher sub cap). Env POSITION_IB_MARK_FALLBACK (default on). KILL-SWITCH NOTE: real marks → kill-switch sees true (possibly negative) UPL.
> - ℹ️ Operator manually closed/cancelled all positions 3:55pm ET 2026-06-22 (clean slate); C2 is preventive for next session.
> - ⏳ NEXT: apply C2 (+commit) & verify next RTH with diag_c (FROZEN→0); confirm A10 observe→block decision; Issue 3 per-style position cap; per-setup drift-distribution diag.


> **✅ 2026-06-22 — (A10) AUTO-EXEC TRIGGER RE-VALIDATION (DRIFT) GATE — APPLIED + LIVE on DGX
> (commit 99da78b0; CHANGELOG note 47d112f8), running in OBSERVE mode.** Closes the P0
> stale/extended daily-setup DRIP that A8's restart/feed
> guard couldn't stop. Settled the root cause by reading `_scan_daily_setups` +
> `_maybe_auto_execute_daily`: NOT a stale-price replay — the daily scan REBUILDS each breakout
> alert every cycle on fresh bars (current_price IS live), but `trigger_price` is the STABLE daily
> breakout level, so the detector keeps re-firing while price stays beyond it and `_auto_execute_alert`
> enters at an ever-more-EXTENDED live price; the old `created_at` is a dedup/upsert labeling
> artifact (why an age gate was wrong). FIX: gate in `_auto_execute_alert` (universal chokepoint for
> intraday + A6 daily) re-fetches live quote via `_get_quote_with_ib_priority` and SKIPs when
> abs(live-trigger)/trigger > `AUTO_EXEC_MAX_TRIGGER_DRIFT_PCT` (default 2.0%). Policy
> `AUTO_EXEC_TRIGGER_DRIFT_POLICY=block|observe|off`. FAIL-OPEN. Span-SHA guarded PRE a4b86c98 ->
> POST b87b0b0f (DGX whole-file 7a9389cc -> 25c418c7); round-trip + 7/7 logic cases green;
> pytest 8/8 on DGX. PATCHER paste.rs/fSYav (patch_a10_trigger_drift_gate.py), pytest
> paste.rs/O0npV, CHANGELOG note paste.rs/gpv9s. Backend restarted clean (health 8/8 green, IB
> connected, pusher fresh). VERIFY next RTH: grep "A10 trigger-drift gate (OBSERVE)" to size the
> drift distribution, then flip AUTO_EXEC_TRIGGER_DRIFT_POLICY=block + restart; re-run
> diag_a9_entry_provenance — late-session extended/backlogged stage_2_breakout entries collapse to ~0.
> NEXT (unchanged): Issue 2 target_price+live-mark plumbing · Issue 3 per-style position cap ·
> Task 1 card timestamp/price transparency UI. DGX patcher ONLY. English.**


> **✅ 2026-06-22 — UI Track A3 + A4 SHIPPED, LIVE, COMMITTED (A4 @ e3a3e555).**
> A3 (Why-Trace modal): 7 plain-language stages (scan→setup→grade→gate→size→manage→exit) opened
> from the TQS drawer header; operator-confirmed live on RTX. patcher paste.rs/44gvE.
> A4 (honest EV verdict): two read-only diags (paste.rs/AHzZu, paste.rs/inrep) PROVED the
> Setup-pillar EV "43% no-data" is GENUINE (not a canonicalization or stamping bug) — 44.9%
> NO_STATS_ROW + 43.3% genuine-zero-EV + 11.7% cold-start; the only coverage-moving lever
> (lower the n_all>=5 EV gate) was rejected as fabrication (544/578 of the gain is ONE setup,
> trend_continuation, n=2, +1.28R). Shipped the honest fix instead: the R:R proxy now reads
> verdict "Est. (R:R)" (descriptors.py/setup_quality.py) and /api/tqs/coverage reports it as a
> 3rd state (proxy_pct per component/pillar + proxy_subscores global; real_pct/coverage_pct
> UNCHANGED); TqsCoveragePanel.jsx 3-way render. patcher paste.rs/uZplq, 4 files/15 anchored
> chunks, PRE/POST SHA256, two-pass. Coverage is FORWARD-LOOKING (reads persisted breakdowns) →
> EV est% rises as post-restart alerts accrue; re-check /api/tqs/coverage next RTH.
> NEXT P1 (pick one): adrp_20d collector warm-fill · TQS↔Confidence-Gate unification (one
> decision authority + verdict). DEFER: Entry-Tendency plumbing (only ~2% trade_outcomes carry
> real entry_slippage — do NOT schedule run_daily_analysis; resurrects v391 false-positive).
> OPEN side-thread: trend_continuation 544 alerts/5d but only 2 graded outcomes (alert→closed
> conversion/grading gap). Open positions can show "target —" in Why-Trace when card/detail lack
> target_price (data-plumbing, not a modal bug). DGX patcher workflow ONLY. English.**


> **🔜 2026-06-19 — UI Track A1b: card-detail scoring_style — BUILT + PASTED (DGX apply pending).
> Drawer already reads detail.scoring_style but /api/tqs/card-detail never returned it (fell back
> to setup-derived guess). FIX (backend-only, additive 1 field in tqs_router.py): surface persisted
> pattern lens from tqs_breakdown.scoring_style (alerts) / entry_context.tqs.breakdown.scoring_style
> (positions). No frontend change. Extractor 6/6, py_compile OK, patcher round-trip IDENTICAL +
> idempotent + rollback + DRIFT-safe. PRE a808dd7c97be… / POST f52dbcd3e151…. PATCHER paste.rs/x2lda
> (patch_a1b_card_detail_scoring_style.py). VERIFY: apply → ./start_backend.sh --force → open drawer
> for a post-P1 symbol, "scored as" reflects persisted lens. NEXT: A3 Why-Trace modal. DGX patcher
> ONLY. English.**


> (DGX apply pending). Ring center now shows score + grade letter (58 / B); removed redundant
> header <TqsBadge/> chip (+ import). Frontend-only. Runtime-verified (4/4 exec) + mock screenshot.
> yarn build clean; 2-file patcher round-trip IDENTICAL + idempotent + rollback + DRIFT-safe.
> HASH GUARDS: ProvenanceRing PRE 29ad9c2a4fa9…(A2f)/POST ef43a78596fe…; ScannerCardsV5 PRE
> b7ff08ae52ec…(A2d)/POST 18697ef6affc…. PATCHER paste.rs/LXbv9 (patch_a2g_ring_number_letter.py).
> VERIFY: apply → yarn build → hard-refresh. NEXT: A1b (drawer scoring_style) → A3 Why-Trace.
> DGX patcher ONLY. English.**

> **🔧 2026-06-19 — UI Track A2f HOTFIX: RING TDZ CRASH — BUILT + PASTED (DGX apply pending).
> A2e crashed the scanner ("Cannot access 'NOM' before initialization") — center-number edit
> read `NOM` above its `const NOM=100` (temporal dead zone). FIX: reordered declarations; same
> A2e colors + numeric center, no crash. RUNTIME-verified (transpile+exec, 4/4 render). Accepts
> PRE broken-A2e aa0613232748… OR A2d 87871429d9c8… → POST 29ad9c2a4fa9…; round-trip both
> baselines IDENTICAL + idempotent + rollback + DRIFT-safe. PATCHER paste.rs/XmGDc
> (patch_a2f_ring_tdz_hotfix.py). A2e (XFsh4) SUPERSEDED. VERIFY: apply → yarn build →
> hard-refresh, scanner renders + rings show colors/number. Commit A2d+A2f after verify.
> LESSON: runtime-exec component logic changes, not just yarn build. NEXT: A1b → A3. English.**

> **🔜 2026-06-19 — UI Track A2e: RING COLORS + NUMERIC CENTER — SUPERSEDED BY A2f (had a TDZ
> crash). Palette + numeric-center design is correct; see A2f for the working build.**




> pending). Operator: rings show but too small ("full height of the scanner card"). FIX
> (frontend-only, presentational): ProvenanceRing.jsx → scalable (100×100 nominal viewBox +
> `fill` mode); ScannerCardsV5.jsx card → 2-col flex (full-height ring rail capped ~88px +
> flex-1 content column). ~3x bigger, legible (verified via HTML mock screenshot). yarn build
> clean; patcher round-trip IDENTICAL (both files) + idempotent + rollback clean + DRIFT-safe.
> HASH GUARDS: ProvenanceRing PRE 3c3e8f98c107…/POST 87871429d9c8…; ScannerCardsV5 PRE
> 605bb2993cfe… (== committed DGX A2c)/POST b7ff08ae52ec…. PATCHER paste.rs/hZIuh
> (patch_a2d_ring_fullheight.py, 2 files). VERIFY: apply → `cd frontend && yarn build` →
> hard-refresh, rings fill card height. NEXT after verify: A1b (drawer scoring_style) → A3
> Why-Trace. DGX patcher workflow ONLY. English.**


> **🔜 2026-06-19 — UI Track A2b: PROVENANCE RING ON OPEN POSITIONS — BUILT + PASTED (DGX
> apply pending). Operator hard-refreshed in PRE-MARKET after A2c and saw no rings — because
> only OPEN POSITIONS render pre-open (no live scanner alerts), and `/api/sentcom/positions`
> never serialized the per-pillar TQS grades (they ARE captured at fill time in
> `entry_context.tqs.pillar_grades`). FIX (backend-only, additive): emit `tqs_pillar_grades`
> on both position serializers in `sentcom_service.py` from `entry_context.tqs.pillar_grades`;
> the V5 position card already reads `p.tqs_pillar_grades` (A2 edit #4) so NO frontend change.
> CAVEAT: positions opened before fill-time pillar capture have empty grades → ring hidden.
> Local: py_compile OK, patcher round-trip IDENTICAL + idempotent + rollback clean + DRIFT-safe;
> PRE f7d2cd93e499… (repo HEAD 1721aa9) / POST 0ef6e9f6add4…. PATCHER paste.rs/DmlSF
> (patch_a2b_position_pillar_grades.py). VERIFY: apply → `./start_backend.sh --force` → rings
> appear on open positions that carry fill-time pillar grades. DGX patcher workflow ONLY. English.**


> **🔜 2026-06-19 — UI Track A2c PROVENANCE-RING FLICKER FIX BUILT + PASTED (DGX apply
> pending). Fixes operator-reported "rings popup then revert to no rings". Root cause:
> `ScannerCardsV5.buildCards()` rebuilds cards each render; WS `alerts` carry
> `tqs_pillar_grades` but REST `setups` don't, so on alert turnover the rebuilt card dropped
> the grades and the ring's `{card.tqs_pillar_grades && ...}` guard went falsy. FIX
> (frontend-only): sticky per-symbol grades cache (`useRef(Map)` + localStorage, 24h TTL) —
> scanner cards (source==='alert') that arrive WITH grades teach the cache; cards WITHOUT are
> backfilled (grades + grade + score). Persists across REST/WS turnover AND page reloads.
> Local: yarn build clean, 8/8 reconcile smoke, patcher round-trip IDENTICAL + idempotent +
> rollback clean + DRIFT-safe; PRE/POST SHA256 hash-guarded (AGENTS.md §2.2): PRE 4a7db055b416…
> (repo HEAD 1721aa9, == live DGX) / POST 605bb2993cfe…. PATCHER paste.rs/xJ33R
> (patch_a2c_sticky_grades_cache.py). VERIFY next:
> apply on DGX → `cd frontend && yarn build` → hard-refresh, confirm rings stay. NEXT after
> A2 verified: A1b backend (card-detail returns persisted scoring_style) → A3 Why-Trace modal.
> DGX patcher workflow ONLY — no testing_agent. English.**


> **✅ 2026-06-19 — v399 + v399b SHIPPED, VERIFIED LIVE ON DGX, PUSHED (main @ 4c0dafe2).**
> v399 (scheduler boot staleness-guard): `services/scheduler_catchup.py` re-runs cron jobs
> missed while the app was closed — auto-staggered (Mongo 20s / IB 120s), HOLIDAY-AWARE
> (2026 US calendar; market-unsafe jobs run on the free socket during holidays/weekends).
> Wired in server.py startup. Also added nightly Fundamentals Warm-Fill cron (18:30 ET Mon-Fri)
> = Issue 2 closed. BONUS: fixed `gate_calibrator.py` `{**v}`→`{**buckets[k]}` NameError that
> had silently killed gate calibration for 35 DAYS (now "Calibrated from 239 outcomes").
> v399b (Diagnostics tab): NEW `routers/data_diagnostics.py` → `GET /api/diagnostics/data-schedule`
> (job punchlist: last-run/last-success/next-fire/output-freshness/issue-flag + catch-up result)
> and `GET /api/tqs/coverage` (real-vs-default % per pillar/sub-score). Two new V5 sub-tabs
> (DataSchedulePanel, TqsCoveragePanel). Verified: coverage 87.2%, schedule 21/22 OK.
> Build docs: memory/v399_scheduler_catchup_build.md, memory/v399b_diagnostics_tiles_build.md.
> TQS coverage baseline (post-audit): Setup 71% (Tape 0% = no live feed, EV 57% = strategy_ev_r
> unstamped), Technical 100%, Fundamental 83%, Context 96% (Sector 77%), Execution 80%
> (Entry-Tendency 0% = only 2% of trade_outcomes carry real entry_slippage — DEFER, do NOT
> schedule run_daily_analysis or it resurrects the v391 false-positive). 🟡 Financials/Float/
> Institutional/Sector on auto-improve path via nightly warm-fundamentals + draining backfill.


> **🔜 2026-06-18 — v369 MISSED-MOVERS FIX BUILT + PASTED (DGX apply pending).
> Diags v376/v377 proved SNDK/MRVL/SPCX/TSLA were structurally filtered out by two
> bugs: (1b) `_passes_universal_liquidity_gate` fail-closed scalp/intraday alerts on
> `rvol <= 0` — but rvol==0.0 means UNMEASURED (no live-vol push outside top-400 L1),
> not zero; (2) `get_symbol_tier` skipped any `atr_pct > 10%`, excluding explosive
> deeply-liquid movers (MRVL/SPCX/SMCI). v369 (paste.rs/3Q8L5, §2.2 patcher, PRE-SHA
> enhanced_scanner 6cd66335… / ib_historical_collector a3cc6467…): rvol-unmeasured now
> DEFERS to the share-ADV + ADRP proofs (PASS if those + adv_dollar clear); a MEASURED
> rvol below floor still blocks (SCALP_RVOL_FAIL_CLOSED=true reverts). ATR ceiling
> WAIVED for $-vol >= intraday tier (ATR_CEILING_WAIVE_LIQUID=false reverts); MIN floor
> + thin-name ceiling kept. Whole-fn / ASCII-anchor chunks, auto-backup, py_compile,
> --check/--apply/--rollback, full local round-trip test green, paste cmp IDENTICAL.
> NO safety-critical path touched. VERIFY next RTH (diag_v376/v377). NEXT: Issue 3
> recompute strategy_stats on sanitized data; Issue 4 dedup_cooldown re-entries. DGX
> patcher workflow ONLY — no testing_agent. English.**


> **✅ 2026-06-17 (latest) — v19.34.323 (patch_v336) SHORT-FADE GATE + R-WINSOR
> DEPLOYED & COMMITTED (9ae11efc), LIVE. diag_v333/v334 forensics: trade_2_hold is
> net +$56.9k (the "-878R" was a risk_amount artifact); the REAL P0 = $26.4k EXCESS
> beyond the stop, 90% SHORTS / 88% vwap_fade_short — low-priced/illiquid strength-shorts
> with sub-1% stops gapped through OVERNIGHT (WTI 2.84/2c→3.21; PRCT 26.67/4c→27.02).
> DEEP ENGINE AUDIT (operator-requested): stop/target/IB-exec engines are SOUND — OCA
> stops are GTC market StopOrders that fired correctly; loss is gap slippage on a no-edge
> entry held overnight, NOT a placement bug. FIX (entry-side + analytics only, ZERO
> safety-critical-path change): (1) opportunity_evaluator short-fade gate blocks SHORT
> fade/reversion setups on price<$5 or stop%<1.0% (SHORT_FADE_GATE_POLICY=block|observe|off);
> (2) winsorize realized-R to ±R_WINSOR_CLAMP(3.0) in learning_loop._bucket + ev_tracking
> so -261R artifacts can't poison the meta-labeler. 9/9 pytest; backend health 6g/2y/0r.
> NEXT (deferred Part A): EOD-flatten ENFORCEMENT for intraday short fades (so they never
> ride overnight) tied to Issue-3 trade_2_hold classifier gap; then P0 breakdown 2470/0
> anomaly. DGX §2.2 patcher workflow ONLY — no testing_agent. English.**

> **✅ 2026-06-17 — v320r intraday scalp PRIORITY-CEILING FIX DEPLOYED & COMMITTED
> (8a69292a). Chain: diag_v320q (priority attribution, paste.rs/5WwmW) proved 66.8%
> of intraday's non-HIGH population is a STRUCTURAL ceiling — intraday scalps
> (second_chance/backside/fashionably_late + more) hard-code priority=MEDIUM so they
> can NEVER reach HIGH (the auto-fire bar), despite equal-or-better TQS/in-play/tape
> vs carry. diag_v320r-precheck (EV-gate calibration, paste.rs/gglWO) confirmed the EV
> gate lets them fire (cold-start grace) and correctly blocks proven losers
> (rs_leader_break -0.14R/39 outcomes EV-BLOCKED) → gate is calibrated. v320r
> (paste.rs/mTqD1, §2.2 patcher, PRE 89555e59→POST b631ebad) gave 3 scalps the existing
> tape-gated HIGH branch (HIGH if tape.confirmation_for_long else MEDIUM); alert-stamping
> only, EV gate still governs auto-fire. big_dog EXCLUDED (-2.12R/20%), gap_pick_roll
> EXCLUDED (DGX form unconfirmed). Backend restarted clean (health green 8/8). VERIFY
> NEXT RTH: re-run diag_v320q --days 5 → INTRADAY HIGH% should rise toward CARRY%.
> FOLLOW-UPS: gap_pick_roll DGX-form check; off_sides_short low-tape (3.8%) investigation;
> P-WIRE Phase 2 (~200 resolved shadow decisions); v321 EOD Flatten Modal. DGX patcher
> workflow ONLY — no testing_agent. English.**


> **✅ 2026-06-16 (later) — P0/P1 OCA + observability batch DEPLOYED & COMMITTED:
> v320h (observe, e7b9c682) → v320h.1 implied-primary (b259038a) + historical
> backfill (470 rows, net_pnl 29→−23,508 corrected) → v320i target_order_ids
> capture (f32593f7) → v320j unrealized_pnl DB-persist (08b53a51). All in `fix`,
> persisted in `backend/.env` (V320H_OCA_FIX_POLICY=fix, V320_DAILY_BAR_GATE_POLICY=observe).
> Issue 3 CLOSED via v320k diag (ib_executions = ~1.5-day retention, ±15m window
> correct, implied-primary validated). Issue 2 (gate observe→block) operator-gated
> on Windows log review. 10/10 pytest green.**


> **🔜 2026-06-16 (later) — v320h OCA close-path accounting PATCHER DELIVERED
> (DGX deploy pending operator). Fixes the recurring P0: the v19.31 external-
> close sweep in `position_manager.py` (`oca_closed_externally_v19_31`) marks
> the trade CLOSED + claims `realized_pnl` but never finalized `exit_price`,
> never recomputed `net_pnl` (left at the -$1.00 commission-min sentinel), and
> never refreshed `pnl_pct` — corrupting ~4 records/hr. The §2.2 patcher
> inserts a finalize block before `_persist_trade`: classify leg (long→SELL /
> short→BUY), source `exit_price` from matching `ib_executions` fill (±15m of
> close, fallback last `current_price`), `net_pnl = realized_pnl −
> total_commissions`, `pnl_pct` off entry basis. Gated by ENV
> `V320H_OCA_FIX_POLICY` (observe|fix|off, DEFAULT observe). PRE_SHA
> `ee4f3f2e…` / POST_SHA `e5cec8f9…`. paste.rs/n609C (round-trip cmp
> IDENTICAL). Locally validated check→apply→rollback + 4 pytest green
> (`tests/test_v320h_oca_close_finalize_patcher.py`). NOT yet applied on DGX.**


> **🔜 2026-06-16 — Issue 1 + Issue 2 from prior fork BOTH RESOLVED.
> (1) v320f-fix1 cleanup applied to 386,919 mislabeled `ib_historical_data`
> rows: 251,551 unique 1-min bars RESCUED (relabeled), 95,242 true duplicates
> removed, 40,126 partial-OHLCV-drift rows QUARANTINED to
> `bar_size='partial_review_v320f'` (full doc preserved in
> `ib_historical_data_partial_review` — likely consolidated-tape feed vs
> single-exchange canonical, awaiting operator triage). Pre→post: 386,919→0
> mislabeled. Full `--rollback` available via `mislabel_relabel_audit_v320f`.
> (2) v320g surgical rebuild applied to SPCX `id=31651c71`:
> `exit_price` None→189.30 (from `ib_executions` order_id=408355),
> `net_pnl` -1.00→698.65, `pnl_pct` 9.09→9.68; `realized_pnl=699.65` left
> unchanged (internally consistent w/ fill_price basis); audit
> `6a30e419caab658cd0b24668`; read-back verified. Next priorities
> per backlog: P-WIRE Phase 2 (BLOCKED on ~146 more resolved shadow
> decisions), [P-TARGET] rare-regime label realignment, multi-bar-size
> shadow logging, v320c ingest-time prevention (`reqHeadTimeStamp`),
> v321 EOD Flatten Modal in V5 UI. Atlas rotation still USER VERIFICATION
> PENDING.**

> **🔜 2026-06-15 — P-WIRE Phase 2 INVESTIGATION COMPLETE. Phase 2 is NOT
> code-blocked; it is *calibration + data-accumulation* blocked. (1) Regime-
> conditional retrain ran (`force_retrain=true phases=["regime"]`): 11 cells
> promoted, 5 cells (5min/15min/1hour × bull_trend/range_bound) had candidates
> CORRECTLY REJECTED by the v312 P0 collapse gate (recall_up well below the
> 0.10 floor; April version preserved). (2) Shadow eval @ 54 resolved decisions
> (need ~200) returned `GENERIC HOLDS` on a statistically thin sample. (3) Root
> cause for low shadow-trend data: `classify_regime` returns `high_vol` in ~91%
> of decisions because `vol_expansion > 1.3` preempts trend evaluation — that
> gate is too sensitive for SPY's current vol regime. (4) The 60.3%
> `regime_model_available=False` rate is fully explained by v322i quarantine
> of `5min_high_vol` (PBO=1.00) combined with 100% of shadow decisions firing
> at `bar_size=5 mins`. (5) Diag confirmed 28 regime variants exist
> (7 timeframes × 4 regimes), 3 quarantined: `1min_bear_trend`, `5min_bear_trend`,
> `5min_high_vol`. Issue 2 (May→June 2026 daily-bar gap, 183 symbols /
> 6,158 bars) — repair patcher v320c APPLIED, queue enqueued; collector
> processing. NO WIRE BUGS — system is design-correct. Next priorities:
> P0-CLASSIFIER (recalibrate vol threshold 1.3→~1.5 in
> `regime_conditional_model.py:96`), P1-TARGET (rare-regime label realignment
> for 5 stale + 3 PBO-quarantined cells), P1-MULTI-TF (let shadow logging
> fire across more bar_sizes than just 5min). Verified false alarms today:
> "base direction_predictors are LightGBM" was misleading log noise
> (`xgboost_json_zlib` not recognized by `timeseries_service.py:234` warm-reload
> but secondary loader handles it correctly).**

> **🔜 2026-06-15 — v19.34.320a + 320b DEPLOYED+VERIFIED. Pre-listing pollution
> guard (compute-time helper + recycled-ticker quarantine) shipped end-to-end:
> SPCX cleaned from 25 daily bars → 1, avg_volume 11.3M → 227M; 42 TRUE_RECYCLE
> symbols moved 35,524 polluted rows into `ib_historical_data_quarantine`
> (reversible). Classifier-refined sweep correctly skipped 33 LIKELY_INGEST_GAP
> symbols clustered on 2026-06-01 (separate ingest-pipeline issue to investigate).
> Mid-flight symbol-field repair script restored quarantine indexability.
> Backlog: v320c ingest-time prevention (head_timestamp guard); v320 daily-bar
> setup gate; diag_ingest_continuity.py; diag_bot_trades_hygiene.py.**

> **🔜 2026-06-12 — v322r APPLIED+COMMITTED on DGX (7b12a984). ACMR root cause PROVEN
> (backend down during Friday EOD window → weekend carry; created_at="" hid the row).
> v322s (missed-EOD boot sweep + created_at fix + repair script) built/tested, patcher at
> paste.rs/HPO1C — AWAITING OPERATOR APPLY.** M0 stack deployed; awaiting live ladder
> validation. DGX patcher workflow ONLY — no testing_agent, no git from bash. English.

> **🔜 FORKED 2026-06-11 — NEXT AGENT: read `/app/memory/NEXT_SESSION_TIER1_PLAN.md` FIRST.**
> All v319/b/c/d ML-integrity fixes are DEPLOYED + committed (DGX main @ d96def40). Full
> leakage audit done (clean). **Tier 1a (CPCV for GBMs, v320) + Tier 1b (backtest execution
> costs, v320b) are BUILT + container-tested — patchers on paste.rs mOsoh / UGzyM, tests
> 9ukb3 / 9Ryar — AWAITING OPERATOR APPLY on the DGX** (see CHANGELOG top entry). Pending
> DGX ops AFTER apply: retired-model eviction (paste.rs/wL0HT) + FULL RETRAIN (models then
> get CPCV-validated) + rotate Atlas password. DGX patcher workflow ONLY — no
> testing_agent, no git from bash. Respond in English.

> **⚠️ AGENTS — READ THIS BLOCK BEFORE ANY CODE CHANGE.**
>
> Open `/app/AGENTS.md` and read **§0 TL;DR** + any sections relevant
> to your task (typically §6.5 for journey context, §11.5 for the
> edit checklist). If you cannot or will not open the file, the 5
> rules below are the bare minimum — violating any of them has cost
> real money in production:
>
> 1. **`close_trade`, `submit_with_bracket`, kill-switch are SAFETY-
>    CRITICAL.** Fork via `_custom` siblings; never patch in place.
>    *(v19.34.123: $25k loss when kill-switch was bypassed.)*
> 2. **NEVER close at IB without `_cancel_ib_bracket_orders` + 8s + 5s
>    retry.** *(2026-05-20: IB position flipped direction.)*
> 3. **`_open_trades` is keyed by `trade_id`, NOT symbol.** Iterate
>    `.values()` and filter. *(b415ed5f phantom incident.)*
> 4. **`position_reconciler` MUST skip `entered_by="reconciled_excess_*"`**
>    on the orphan path or it duplicates trades every 60s. *(v19.34.22.)*
> 5. **Always project `{"_id": 0}` on Mongo reads.** ObjectId is not
>    JSON-serializable.
>
> Full context, why each rule exists, and the journey maps are in
> `/app/AGENTS.md`. Treat this PRD as the *what we're building*; treat
> AGENTS.md as the *how to safely touch it*.

> Lean, static spec. Dated work history lives in `CHANGELOG.md`.
> Open priorities and backlog live in `ROADMAP.md`.
>
> **Rules for the agent (keep these docs alive):**
>   - Ship something → prepend a `## YYYY-MM-DD — <title> — SHIPPED`
>     section to **CHANGELOG.md** (Why / Scope / Verification).
>   - Priority shifts → reorder **ROADMAP.md**; promoted item moves up,
>     completed item is removed and recorded in CHANGELOG.
>   - Architecture / API contract / hardware topology changes → edit
>     **PRD.md** (this file).
>   - Trap / journey / convention changes → edit **AGENTS.md**.
>   - Never silently drop history; never let `🔴 Now / Near-term` go
>     stale across more than one task.

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.


## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)




## Key API surface
- `GET /api/diagnostic/position-pnl-audit` — **v19.34.142d/e (2026-02-13)** — per-symbol diff of bot vs IB unrealized PnL with verdict classification (`OK`, `DRIFT_ABS`, `DRIFT_PCT`, `PHANTOM_IN_BOT`, `MISSING_IN_BOT`, `QTY_SIGN_MISMATCH`, `QTY_MAGNITUDE_MISMATCH`). Magnitude-mismatch rows include `ledger_fragments[]` listing every open BotTrade slice for the symbol (trade_id, shares, remaining_shares, setup_type, entered_by, stop_order_id, entry_time) so the operator can pinpoint which slice(s) over-booked vs IB. KMB phantom-share crisis use case: bot=144 / IB=55 fires a high-severity action with one-line `POST /api/trading-bot/reconcile-share-drift` remediation. Tolerance: `max(1 share, 1% of ib_qty)`.
- `GET /api/diagnostic/bracket-status[?symbols=A,B,C]` — **v19.34.143b (2026-02-13)** — live snapshot of every open fragment in `_open_trades` with `stop_order_id`, `is_simulated_stop`, `in_live_orders`, and a `status` (`BRACKETED / NAKED_NO_STOP / NAKED_SIM / NAKED_STALE`) per row. Cross-references against the 3-tier open-orders resolver used by `_naked_position_sweep`. Used by `scripts/verify_naked_orphan_healing.py` to confirm the v19.34.143 emergency-stop sweep healed reconciled orphans within the expected 60s cadence.
- `POST /api/trading-bot/sync-entry-prices` — **v19.34.148 (2026-02-13)** — manual reconciliation that snaps every open BotTrade's `entry_price` / `fill_price` to IB's live `avgCost`. Body: `{dry_run, symbols, tolerance_per_share}`. Returns per-trade synced/skipped report with signed `implied_pnl_correction` (direction-aware). Persists to `bot_trades` with audit columns. Also fires nightly via `TradingScheduler._run_entry_price_sync` at 16:35 ET Mon–Fri.
- `GET /api/portfolio` — IB pushed positions + manual fallback; quote_ready guard
- `POST /api/portfolio/flatten-paper?confirm=FLATTEN` — flatten paper account, 120s cooldown
- `GET /api/sentcom/positions` — bot + IB merged positions; injects live `_pushed_ib_data.quotes` into `current_price` so PnL doesn't lag the timer-driven `position_manager.update_open_positions` (2026-05-01 v19.22.3); exposes V5-rich fields `scan_tier / trade_style / reasoning[] / exit_rule / scale_out_state / trailing_stop_state / risk_reward_ratio / remaining_shares` (v19.23)
- `GET /api/sentcom/stream/history?symbol=X&minutes=N` — Used to fetch `sentcom_thoughts` for chart bubbles and per-symbol bot reasoning timeline (v19.23)
- `GET /api/diagnostics/unmatched-short-closes?days=N&symbol=X&emit_warning=bool` — **v19.34.16 (2026-05-06)** — flags Sell Short / Buy to Cover transactions in `ib_executions` that have NO matching `bot_trades` row with `direction=short`. FIFO inventory walk identifies SHORT round-trips (sell-short → buy-to-cover) and residual still-open shorts. When findings exist, emits `unmatched_sell_short_or_btc_v19_34_16` HIGH-severity stream warning. Closes the leak class v19.34.15a is designed to prevent. Companion to `scripts/audit_ib_fill_tape.py --bot-trades-json` cross-check.
- `GET /api/trading-bot/share-drift-status?symbols=X,Y` — **v19.34.18 (2026-05-06)** — read-only diagnostic for the v19.34.15b drift loop. Returns `{loop:{alive, task_exception, feature_flag, interval_s}, diag:{tick_count, last_tick_at, last_tick_status, last_tick_error, last_result_summary, last_drifts_detected, last_drifts_resolved, consecutive_failures}, pusher_connected, per_symbol:[{symbol, bot_qty_signed, ib_qty_signed, drift, would_act, verdict}], summary}`. Built to investigate why 93sh FDX + 338sh UPS naked drift went undetected. Pairs with the existing `POST /api/trading-bot/reconcile-share-drift` (`dry_run` flag) for full investigate-then-heal flow.
- `POST /api/trading-bot/reconcile-share-drift` — **v19.34.15b (2026-05-06)** — share-COUNT drift reconciler for already-tracked symbols. Detects 3 drift classes: `excess_unbracketed` (IB > bot → spawns `reconciled_excess_slice` BotTrade with 1% stop / 1R target, `entered_by="reconciled_excess_v19_34_15b"`), `partial_external_close` (IB < bot, IB > 0 → LIFO shrink of `remaining_shares`, newest trade drained first), `zero_external_close` (IB == 0 → closes bot_trade with `close_reason="external_close_v19_34_15b"`). Body: `{drift_threshold:int=1, auto_resolve:bool=true, dry_run:bool=false}`. Forensic write to `share_drift_events` Mongo collection (TTL 7d). Backed by 24/7 background loop (`SHARE_DRIFT_RECONCILE_ENABLED=true`, `SHARE_DRIFT_RECONCILE_INTERVAL_S=30`). Closes the v19.34.15a `[REJECTED: Bracket unknown]` race blind spot — orphan reconciler skips already-tracked symbols, so this is the only path that detects share-count drift on tracked positions.
- `POST /api/trading-bot/reconcile` — **v19.24 (2026-05-01)** — proper write-through reconcile of IB-only orphan positions. Materializes real `bot_trades` + in-memory `_open_trades` so manage-loop can actively trail stops / scale-out / EOD-close positions the bot didn't originate. Safety: `{all:true}` requires `{confirm:"RECONCILE_ALL"}`; stop-already-breached skip; idempotent (already-tracked skip). Body: `{symbols:[...]}` or `{all:true, confirm:"RECONCILE_ALL"}` with optional `stop_pct`/`rr` overrides. Counterpart to lazy-reconcile in `sentcom_service.get_our_positions` (v19.23.1) which only patched UI display.
- `GET /api/sentcom/chart-tail?symbol=X&timeframe=5min&since=<unix_ts>&cap=50` — **v19.25 (2026-05-01)** — incremental refresh endpoint. Returns ONLY new bars + matching indicator points + new markers since `since`. Reads through `chart_response_cache` (Mongo-backed TTL cache, 30s intraday / 180s daily, survives backend restart). Frontend `ChartPanel.jsx` smart-polls every 5s during RTH on the focused chart instead of re-shipping the full 5,000-bar window every 30s.
- `GET /api/ib/pusher-health` — **v19.30.11 (2026-05-01)** — adds `rpc_max_concurrent`, `rpc_circuit_state`, `rpc_circuit_open_remaining_s`, `rpc_circuit_recent_failures`, `rpc_circuit_short_circuit_total`, `rpc_semaphore_timeout_total`, `rpc_dedup_coalesced_total` to the `heartbeat` block. Surfaces the new throttle/circuit-breaker/dedup state on the V5 PusherHeartbeatTile.
- `GET /api/system/banner` — **v19.30.12 (2026-05-01)** — distinguishes 3 pusher failure modes: `pusher_rpc_dead` (critical, both channels down), `pusher_rpc_blocked` (warning, push HEALTHY but RPC firewall-blocked — exact case operator hit), `pusher_rpc_partial` (warning, edge cases). Action text includes the actual `netsh advfirewall` command for the RPC-blocked case.
- `GET /api/system/health` `pusher_rpc` subsystem — **v19.30.12 (2026-05-01)** — adds `push_age_s` + `push_fresh` to metrics. Reads `routers.ib._pushed_ib_data` module attr directly (the helper is shadowed by an async route). Severity matrix is push×RPC quadrants instead of just RPC failures.
- `GET /api/ib/account/positions` — **v19.30.10 (2026-05-01)** — simplified two-tier pusher read. Response shape: `{ positions, count, source: "memory"|"mongo_snapshot"|"empty", last_update }`. Hot path reads in-memory `_pushed_ib_data["positions"]`. Warm path reads Mongo `ib_live_snapshot.current` (survives backend restarts). Empty state when both tiers are empty. NEVER raises 503 — direct-IB call removed entirely (DGX has no direct IB connection in this deployment; pusher is the source of truth).
- `POST /api/trading-bot/cancel-all-pending-orders` — **v19.30.9 (2026-05-01)** — pre-open safety endpoint. Cancels pending+claimed rows in Mongo `order_queue` + direct IB-side open orders (when reachable). Requires `confirm:"CANCEL_ALL_PENDING"` token. Optional `symbols=[...]` scope + `dry_run:true` preview. Response surfaces `ib_unavailable:true` flag when direct IB is unreachable so operator knows to flatten via TWS / Workbench. Mirrors the `/flatten-paper?confirm=FLATTEN` safety pattern.
- `GET /api/system/account-mode` — **v19.31.13 (2026-05-04)** — operator-facing account-mode snapshot. Resolves `detected_mode` (paper/live/unknown) by classifying current pusher account ID through `account_guard.classify_account_id` (DU* prefix → paper, anything else → live). Returns `{detected_mode, effective_mode, current_account_id, expected_aliases, match, reason, ib_connected, active_mode}`. Powers the V5 HUD top-strip `<AccountModeBadge>` so the operator never confuses paper vs live across account flips.
- `GET /api/diagnostics/shadow-decisions?days=N&symbol=X&only_executed=&only_passed=` — **v19.31.13 (2026-05-04)** — V5 Diagnostics → Shadow Decisions tab. Reads `shadow_decisions` Mongo collection (the AI council's verdict on every alert, regardless of fire). Returns rows + summary: total, by_recommendation, executed_count/win_rate/pnl_sum, not_executed_count + would_pnl_sum, `divergence_signal` (`ai_too_conservative` / `ai_too_aggressive` / `balanced`).
- Realized-PnL auto-sync background task — **v19.31.13 (2026-05-04)** — `TradingBotService` schedules `_realized_pnl_autosync_loop()` every 30s. Scans `bot_trades` for `status=closed AND closed_at within last 24h AND realized_pnl in (0, null, missing)`, dedupes by symbol, and calls the same `routers.diagnostics._recalc_realized_pnl_for_symbol` helper as the manual `↻ Recalc` button. Idempotent + silent when healthy. Env: `REALIZED_PNL_AUTOSYNC_ENABLED=true`, `REALIZED_PNL_AUTOSYNC_INTERVAL_S=30`.
- `BotTrade.trade_type` — **v19.31.13 (2026-05-04)** — every fresh fill stamped at execution time with `paper`/`live`/`unknown` based on the IB account ID seen at fill time. Surfaced through `/api/sentcom/positions` (open + lazy IB-orphan branches), `/api/sentcom/positions.closed_today`, `/api/diagnostics/day-tape`, `/api/diagnostics/day-tape.csv` (new `trade_type` + `account_id_at_fill` columns), and `/api/diagnostics/forensics` (rolled up to `dominant_type` per symbol; `mixed` when concrete types diverge).
- `GET /api/ib-collector/throttle-policy` — **v19.31.14 (2026-05-04)** — RTH-aware historical-collector throttle. Returns `{max_concurrent_workers, rth_active, recommended_pending_request_limit, reason, et_iso}`. `max_concurrent_workers=1` during 9:30-15:55 ET weekdays, `4` otherwise. Windows IB pusher should poll every ~30s and cap its worker pool. Server-side enforcement: `/api/ib/historical-data/pending` caps the operator-passed `limit` at `recommended_pending_request_limit` when RTH is active so older pushers also benefit; payload includes `throttle_limit` + `rth_active` for the pusher to log/honor.
- `GET /api/trading-bot/boot-reconcile-status?pill_visible_seconds=600` — **v19.31.14 (2026-05-04)** — exposes the last `auto_reconcile_at_boot` event so the V5 HUD can render a "🔁 Auto-claimed N at boot" pill. Returns `{ran, ran_at, age_seconds, reconciled_count, skipped_count, errors_count, symbols, show_pill}`. Pill auto-hides after `pill_visible_seconds`. Backend persists to `bot_state.last_auto_reconcile_at_boot` so the pill survives restarts.
- `POST /api/sentcom/chart/warm` — **v19.32 (2026-05-04)** — pre-warm `chart_response_cache` for top-N visible scanner symbols × common timeframes. Body: `{symbols: [str], timeframes: [str]=["5min"], days: int=5, session: str="rth_plus_premarket", max_concurrent: int=4, per_cell_timeout_s: float=8.0}`. Concurrency-bounded by semaphore; per-cell timeout protects the batch. Returns `{success, summary: {warmed, skipped, failed, total}, elapsed_ms, results: [...]}`. ScannerCardsV5 calls this 1.5s-debounced on every top-12 card list change. Operator's NEXT chart click on a warmed symbol is <50ms vs. 400ms cold.
- `WS /api/sentcom/ws/chart-tail?symbol=X&timeframe=Y&since=Z&session=...` — **v19.33 (2026-05-04)** — server-pushed chart tail. Replaces 5s polling with 2s RTH-tick (30s off-hours) push-on-change. Reuses REST `get_chart_tail` handler internally; payload byte-identical so frontend merge code unchanged. Stamps `from_ws: true` + `server_t`. Heartbeat `{type:'ping', t:..., symbol:...}` every 15s of silence. Feature-flagged: `CHART_WS_ENABLED=false` immediate close-1008. `CHART_WS_TICK_S` env override. Hook `useChartTailWs` auto-reconnects with exponential backoff (1→2→4s); after 3 consecutive failures sets `status='fallback'` so polling loop resumes. Polling loop in `ChartPanel.jsx` pauses while `wsStatus ∈ {connecting, connected}`. New chart-ws-status pip ("live"/"poll"/"poll-fb") in chart header.
- `services/quote_tick_bus.py` + `GET /api/ib/quote-tick-bus/health` — **v19.34 (2026-05-04)** — in-memory L1 quote tick pub/sub. `defaultdict[symbol, set[asyncio.Queue]]` with bounded latest-N drop policy (size=8) per subscriber. Per-symbol drop counters; process-global publish/drop totals. Feature-flag `QUOTE_TICK_BUS_ENABLED=true` (default ON; no I/O when nobody subscribes). Pusher's `receive_pushed_ib_data` publishes every quote update to the bus.
- `services/bracket_tif.py` — **v19.34.5 (2026-05-05)** — classification-aware bracket TIF resolver. Intraday styles → `("DAY", False)`, overnight styles → `("GTC", True)`. Wired into trade_executor_service, ib_service, position_reconciler. Stops the GTC zombie bug at *placement* time.
- `GET /api/ib/orders` — **v19.34.6 (2026-05-05)** — Mongo `order_queue`-backed visibility endpoint. Filter by `status` (csv supported), `symbol`, `order_type`, `since`; `open_only=true` shorthand. Returns `{orders, summary, source: "mongo_order_queue", filters_applied}`. Replaces the dead `/orders/open` direct-IB endpoint.
- `POST /api/trading-bot/eod-validate-overnight-orders` — **v19.34.6 (2026-05-05)** — sweeps every active order with a GTC or `outside_rth=True` leg, classifies as `ok_swing_or_position` / `wrong_tif_intraday_parent` / `orphan_no_parent`, optionally cancels orphans + wrong-TIF rows. Two-step safety: requires BOTH `confirm="CANCEL_ORPHANS"` and `dry_run=False`. Closes the runtime edge of the GTC-zombie bug.
- `POST /api/trading-bot/cancel-orders-for-symbol` — **v19.34.6 (2026-05-05)** — EOD pre-cancel guard. Cancels every active order for one symbol BEFORE firing market-close flatten. Requires `confirm="CANCEL_FOR_SYMBOL"` token. Eliminates the OCA race against EOD market-close.
- `GET /api/trading-bot/effective-limits` — **v19.34.6 (2026-05-05)** — single canonical endpoint returning the most-restrictive AND across all guard layers (Master Safety, bot RiskParameters, PositionSizer, DynamicRisk). Mirrors `/api/safety/effective-risk-caps`. Fixes the 2026-05-04 operator confusion where Morning Prep UI showed 25 pos/$5k and `/status` showed 10 pos/$0.
- `services/sentcom_service.get_our_positions` watchlist filter — **v19.34.6 (2026-05-05)** — suppresses bot-tracked rows whose `setup_type` is in `_WATCHLIST_ONLY_SETUPS` (`carry_forward_watch`, `day_2_continuation`, `gap_fill_open`, `approaching_*`) when IB does NOT confirm a matching `(symbol, direction, qty>0)` position.
- `BotTrade.pre_submit_at` — **v19.34.6 (2026-05-05)** — ISO timestamp stamped immediately before broker call. Trade upserted to `bot_trades` with `status=PENDING` BEFORE `place_bracket_order`. Eliminates "IB fill but no Mongo row" gap. Save failure does NOT block the broker call (fail-open).
- `services/enhanced_scanner._persist_carry_forward_alert` + `_hydrate_carry_forward_alerts_from_mongo` — **v19.34.6 (2026-05-05)** — carry-forward gameplan persistence. After-hours `_rank_carry_forward_setups_for_tomorrow` writes to `carry_forward_alerts` Mongo collection on creation; `start()` rehydrates non-expired non-dismissed alerts back into `_live_alerts`. Morning prep workflow now survives backend restart.
- `services/bracket_reissue_service.py` — **v19.34.7 (2026-05-05 PM)** — unified `cancel-old + recompute + submit-new OCA pair` pipeline for the bracket lifecycle. Used by scale-out (auto-wired into `position_manager.check_and_execute_scale_out`), TIF promotion, manual operator overrides. Cancel-then-submit with 2s ack timeout; aborts on cancel failure (CRITICAL stream warning, never both old + new live). Recomputes stop from weighted-avg-entry × `default_stop_pct`; preserves target PRICE LEVELS, recomputes target QUANTITIES from new total × original `scale_out_pcts`. Feature-flag `BRACKET_REISSUE_AUTO_ENABLED=true` (default ON).
- `POST /api/trading-bot/reissue-bracket` — **v19.34.7 (2026-05-05 PM)** — operator-driven manual trigger for the bracket re-issue service. Supports `dry_run=true` to preview the computed plan. Body: `{trade_id, reason, new_total_shares?, new_avg_entry?, already_executed_shares?, preserve_target_levels?, cancel_ack_timeout_s?, dry_run?}`. 400/404/503 guards on missing args.
- `TradingBotService.start()` boot zombie sweeper — **v19.34.7 (2026-05-05 PM)** — 30s after startup, calls `eod_validate_overnight_orders` in dry-run mode and surfaces orphan + wrong-TIF counts to logs + operator stream. Does NOT auto-cancel — operator reviews + triggers cancel manually. Feature-flag `BOOT_ZOMBIE_SWEEP_ENABLED=true`.
- `services/rejection_cooldown_service.py` — **v19.34.8 (2026-05-05 PM)** — per-`(symbol, setup_type)` cooldown after a structural rejection. Subsequent re-evals during the cooldown window are short-circuited with a clear log breadcrumb. Auto-expiry; repeat rejections within window EXTEND the expiry + bump `rejection_count`. Operator nukes via `clear_cooldown` / `clear_all`. Wired into `trade_execution.execute_trade` at THREE points: top-of-function gate, broker-rejection branch, guardrail-veto branch. Defaults: `REJECTION_COOLDOWN_SECONDS=300` (5 min).
- `GET /api/trading-bot/rejection-cooldowns` + `POST /api/trading-bot/clear-rejection-cooldown` — **v19.34.8 (2026-05-05 PM)** — operator inspection / manual override endpoints for the rejection cooldown registry.
- `services/state_integrity_service.py` + `GET /api/trading-bot/integrity-status` + `POST /api/trading-bot/force-resync` — **v19.34.10 / 14 (2026-05-06)** — drift watchdog. Per-field policy: **MEMORY_WINS** for IB-sourced capital fields (`starting_capital`, `max_daily_loss`, `max_notional_per_trade`, `max_risk_per_trade`) + `setup_min_rr` (memory came from live IB / refresh-account; Mongo is just last persisted snapshot). **MONGO_WINS** for operator-tuned limits (`max_open_positions`, `max_position_pct`, `min_risk_reward`, `max_daily_loss_pct`, `reconciled_default_*`) — persisted Mongo IS the operator's intent. **Drift-loop detector** (v19.34.14): if same field flips ≥3 times in 600s, demote to detect-only for process lifetime; operator re-arms via `force-resync {rearm_demoted: true}`. Surfaces `demoted_fields[]` in status. Auto-resolve ON by default; flip via `STATE_INTEGRITY_AUTO_RESOLVE=false`. Drift events persist to `state_integrity_events` (TTL 7d) + emit CRITICAL `state_drift_detected_v19_34_10` Unified Stream event.
- `GET /api/trading-bot/bracket-history?trade_id|symbol&days&limit` — **v19.34.11 (2026-05-06)** — Mongo `bracket_lifecycle_events` (TTL 7d) reader. Returns full lifecycle of a trade's brackets (original → scale-out → re-issue → exit) with per-event `reason`, `phase`, `cancel_result`, `submit_result`, `plan` rich detail. Powers the V5 `<BracketHistoryPanel />` expandable inner panel inside `OpenPositionsV5.jsx`. Backend writer in `services/bracket_reissue_service._persist_lifecycle_event` runs on every `reissue_bracket_for_trade` return path (best-effort, never blocks broker call).
- `GET /api/trading-bot/rejection-events?symbol&setup_type&days&limit` — **v19.34.12 (2026-05-06)** — Mongo `rejection_events` (TTL 7d) reader with built-in heatmap aggregation. Returns `{events[], heatmap.rows[], heatmap.symbols[], heatmap.setups[], heatmap.max_rejections, heatmap.top_reasons[]}`. Powers the V5 Diagnostics → "Rejections" sub-tab heatmap (Symbol × Setup grid colored by rejection_count, tooltip per cell breaks down by reason). Backend writer in `services/rejection_cooldown_service._persist_rejection_event` runs on both initial-rejection and cooldown-extension paths.
- Quote `pushed_at` stamping at merge time + boot-reconcile retry pass — **v19.34.13 (2026-05-06)** — `routers/ib.receive_pushed_ib_data` now stamps `pushed_at` on every quote dict at merge (fixes "STALE 240m" V5 chip lying when pusher was LIVE 1s). Boot auto-reconcile schedules a 90s retry pass when the initial 20s pass leaves orphans skipped (clears `direction_unstable` 30s gate). `GET /api/trading-bot/boot-reconcile-status` exposes `skipped[]` per-orphan reasons + `retry_pass` flag. Redundant `<PusherHealthChip />` removed from HUD top strip (`<PusherHeartbeatTile />` panel below is single source of truth).

- `PositionManager.evaluate_single_trade_against_quote(trade, bot, quote)` + lifecycle reaper in `TradingBotService.start()` — **v19.34 (2026-05-04)** — manage-loop consumer for the tick bus. Per-open-trade subscriber task runs the same stop-trigger logic as `update_open_positions` on each fresh tick (~50ms cadence) instead of waiting for the next manage-loop cycle (~5-15s). Mirrors bid/ask-aware logic; trailing-stop precedence honored. Close reason stamped `stop_loss_mid_bar_v19_34` (or `..._<mode>_mid_bar_v19_34`) for journaling. Feature-flag `MID_BAR_TICK_EVAL_ENABLED=false` (default OFF — explicit opt-in after operator verifies bus health). Lifecycle reaper polls every 2s (`MID_BAR_TICK_RECONCILE_S`) — self-healing across all `_open_trades` insertion sites. Cancelled cleanly in `bot.stop()`.
- `GET /api/assistant/coach/morning-briefing` — Setup-landscape + multi-index-regime grounded morning briefing in 1st-person voice (2026-04-30 v4)
- `GET /api/assistant/coach/eod-briefing` — retrospective EOD coaching (2026-04-29 v3)
- `GET /api/assistant/coach/weekend-prep-briefing` — Sunday-night prep (2026-04-29 v3)
- `GET /api/scanner/setup-landscape?context=morning|midday|eod|weekend` — universe-wide Bellafiore-Setup snapshot + 1st-person narrative (now leads with multi-index regime line + cites yesterday's grade — 2026-04-30 v4)
- `GET /api/scanner/landscape-receipts?days=7&context=morning` — recent graded landscape predictions (closes the AI feedback loop — 2026-04-30 v4)
- `POST /api/scanner/landscape-grade?trading_day=YYYY-MM-DD` — manual trigger of EOD grading job (2026-04-30 v4)
- `POST /api/trading-bot/reconcile` — proper write-through reconcile of IB-only orphan positions; v19.29 added 30s direction stability gate (`direction_unstable` skip if observation history < 30s) preventing direction-mismatched claims.
- `GET /api/diagnostic/trade-drops?minutes=N&gate=X&limit=N` — silent execution-drop forensics; v19.29 instruments order-intent dedup blocks via `safety_guardrail` + `reason=intent_already_pending`.

## v19.29 validation harness (2026-05-01)

`backend/scripts/verify_v19_29.py` — read-only Python harness that
queries 6 backend surfaces to confirm v19.29's 5 fixes are wired and
observable end-to-end. Documented in `memory/V19_29_VALIDATION.md`.
Run during/after RTH:
```
python -m backend.scripts.verify_v19_29 --watch
```
- `GET /api/scanner/setup-trade-matrix` — full Trade × Setup matrix + classifier stats (2026-04-29 v2)
- `GET /api/scanner/sector-regime` — per-sector regime snapshot (11 SPDR ETFs + SPY benchmark, soft-gate ML feature — 2026-04-30 v6)
- `POST /api/scanner/backfill-sector-tags` — populate `symbol_adv_cache.sector` from the static GICS map (idempotent — 2026-04-30 v6)
- `GET /api/scanner/in-play-config` — current in-play scoring thresholds (single source of truth shared by scanner + AI assistant — 2026-04-30 v7)
- `PUT /api/scanner/in-play-config` — runtime threshold tuning, persists to `bot_state.in_play_config` (`{"strict_gate": true}` opts into hard gating — 2026-04-30 v7)
- `GET /api/diagnostic/trade-funnel?date=YYYY-MM-DD` — walks the alert→bot→execution chain and pinpoints the first dead stage (2026-04-30 v8)
- `GET /api/trading-bot/eod-status` — EOD countdown lookahead used by the V5 EodCountdownBannerV5 (status state-machine + intraday/swing counts; 2026-04-30 v19.14b)
- `POST /api/trading-bot/eod-close-now` — manual flatten of all open positions (bool-return fix 2026-04-30 v19.14b)
- `GET /api/system/morning-readiness` — pre-RTH autopilot go/no-go aggregator (2026-04-30 v19.18)
- `GET /api/diagnostic/trade-drops?minutes=N&gate=X&limit=N` — silent execution-drop forensics (2026-04-30 v12); 9 instrumented gates between AI gate and `bot_trades.insert_one()`
- `POST /api/diagnostic/dlq-purge?permanent_only=true&dry_run=true&older_than_hours=N&bar_size=X&force=true` — purges permanently-failed historical-data requests; safe-by-default allowlist + audit log to `dlq_purge_log` (2026-04-30 v19.2)
- `GET /api/scanner/setup-coverage` — orphan/silent/active/time-filtered diagnostic
- `GET /api/scanner/detector-stats` — per-detector evals + hits (cumulative + cycle)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot. **v19.30.1
  (2026-05-02)**: now `async def` with `asyncio.to_thread` offload
  for sync mongo snapshot upsert + `tick_to_bar_persister.on_push`,
  plus 503-Retry-After:5 backpressure when ≥4 pushes are in flight
  (cap = `_PUSH_DATA_MAX_CONCURRENT`). Pre-fix this sync handler did
  inline sync pymongo + held-lock per-bar upserts on every push,
  saturating anyio's 40-thread pool and wedging `/api/health` to
  0-byte timeouts. New observability: `/api/ib/pusher-health.heartbeat`
  exposes `push_in_flight`, `push_max_concurrent`, `push_dropped_503_total`.
- `GET /api/health` — **v19.30.1 (2026-05-02)**: `def` → `async def`.
  Must be async so it runs on the event loop directly, immune to
  thread-pool starvation regardless of what's happening downstream.
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not
- `POST /api/ai-modules/shadow/track-outcomes?drain=true&batch_size=50` — drain shadow-decision backlog (added 2026-04-29). Yields to event loop between batches.


## Canonical setup taxonomy (SSOT — v268→v271)

`services/setup_taxonomy.py` is the single source of truth for setup naming:
`canonicalize` (collapse `_long`/`_short`/`_scalp`/`_confirmed` + aliases),
`is_edge_excluded` (reconciled_*/imported_from_ib/approaching_*/watchlist),
`strategy_family`, `exit_archetype_prior`, `style_of`. Stamped on every alert via
`LiveAlert.__post_init__` (m3); exposed at `GET /api/sentcom/taxonomy` (m4) which
feeds `agents/vocabulary.py` (NIA) and `frontend/utils/tradeStyleMeta.js` (m4-fe).
**m5 (v271):** grading (`setup_grading_service`), EV (`ev_tracking_service`),
the corrected learning store (`learning_loop_service.rebuild_*` → read by
`tqs/setup_quality`) all roll up by canonical bucket + exclude artifacts; grades
compute off MEDIAN R with a sub-$1 `risk_amount` clamp. Flags (default ON,
reversible): `GRADING_CANONICAL_ROLLUP`, `GRADING_USE_MEDIAN`,
`GRADING_MIN_RISK_AMOUNT`, `EV_CANONICAL_ROLLUP`, `LEARNING_CANONICAL_BASE`.
Model feature input (`get_setup_features`) is intentionally UNCHANGED (m6 audit
done — `memory/M6_AI_FEATURE_INPUT_AUDIT_2026-06.md`; setup_type reaches models
only via coarse family routing, never a per-setup one-hot) — never feed
canonical/family names to trained models without a retrain.
**m8 (v272):** `tidal_wave` split — the old reversion detector → `fading_bounce`
(fade/reversion/target); a NEW true-momentum `tidal_wave` (RVOL surge + range
break, long runner; env-tunable TIDAL_WAVE_MIN_*) owns the name. Historical
`tidal_wave` rows migrate to `fading_bounce` via
`scripts/migrate_v19_34_272_tidal_wave.py`.
**Issue 2 (v273):** `smart_stop_service` bracket geometry now driven by SSOT
`exit_archetype_prior()` (INTRADAY_BRACKET_V2, env-reversible) — runner archetypes
(momentum/breakout/tidal_wave) get a tight stop + trailing remainder; target
archetypes (scalp/fade/fading_bounce) get a fixed 2-wave bracket.

## Pipeline architecture (Bellafiore + ML hybrid)

### Conceptual hierarchy (operator mental model + UI)
`Market Regime (SPY/QQQ/IWM/DIA) → Sector Regime → Daily Setup → Time/In-play → Trade`

### Runtime architecture (decided 2026-04-29 evening, locked 2026-04-30)
**Hard gates only in 3 places** to avoid compounding rejection rate
that would starve the ML pipeline of training data:
  1. **Time-window** (`_is_setup_valid_now` in `enhanced_scanner.py`) — opening_drive can't fire midday
  2. **In-Play / Universe** — ADV ≥ $2M/day floor (FAIL CLOSED on unknown ADV) + RVOL ≥ 0.8 floor + tier-based scan frequency. **Unified richer in-play score** (RVOL/Gap/ATR/Spread/Catalyst — `services/in_play_service.py`, shipped 2026-04-30 v7) is **stamped on every alert** as metadata; promotes to a hard gate only when `bot_state.in_play_config.strict_gate=true`.
  3. **Confidence gate** — predicted_R + win_prob threshold

**Everything else flows in as features** to the per-Trade ML models:
  - **Multi-index regime tag** (`MultiIndexRegimeClassifier` —
    shipped 2026-04-30) — composite SPY/QQQ/IWM/DIA label, 8 active
    buckets + UNKNOWN; one-hot encoded into `regime_label_*` features.
  - **Sector regime tag** (`SectorRegimeClassifier` — shipped
    2026-04-30) — 11 SPDR sector ETFs + SPY benchmark → 5 active
    buckets + UNKNOWN; per-symbol resolution via static GICS map
    in `SectorTagService`; one-hot encoded into `sector_label_*`
    features. Training uses `SectorRegimeHistoricalProvider` with
    per-(etf, date) caching.
  - Daily Setup tag (`MarketSetupClassifier` — shipped 2026-04-29 v2;
    one-hot encoded into `setup_label_*` features 2026-04-30)
  - Setup × Trade matrix context (`is_countertrend`, `out_of_context_warning`, `experimental` — shipped 2026-04-29 v2)
  - Setup landscape (`SetupLandscapeService` — shipped 2026-04-29 v3;
    extended with regime line 2026-04-30)
  - Numerical regime features (24 floats — `regime_features.py`,
    SPY/QQQ/IWM trend/RSI/momentum/breadth/correlations/rotations)

`STRATEGY_REGIME_PREFERENCES` in `enhanced_scanner.py` is METADATA
ONLY — explicitly NOT a hard-gate enforcement (re-documented
2026-04-30 to close the next-session-plan item #6). It documents the
operator's mental model of which trades thrive in which regimes; the
actual learning happens via the one-hot features above.

The matrix in `services/market_setup_classifier.py::TRADE_SETUP_MATRIX`
is the operator's source of truth for which Trade fits which Setup;
`/app/memory/SETUPS_AND_TRADES.md` is the human-readable mirror.


## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/routers/scanner.py` — `/setup-coverage`, `/setup-trade-matrix`, `/setup-landscape`, `/detector-stats`
- `backend/routers/assistant.py` — `/coach/morning-briefing`, `/coach/eod-briefing`, `/coach/weekend-prep-briefing`
- `backend/services/trade_drop_recorder.py` — **NEW 2026-04-30 v12** — silent-execution-drop audit trail. `record_trade_drop` writes to `trade_drops` Mongo collection (TTL 7d) + 500-deep in-memory ring buffer fallback + structured `[TRADE_DROP]` WARN log line. 9 KNOWN_GATES wired between AI confidence gate and `bot_trades.insert_one()`: `account_guard`, `safety_guardrail`, `safety_guardrail_crash`, `no_trade_executor`, `pre_exec_guardrail_veto`, `strategy_paper_phase`, `strategy_simulation_phase`, `broker_rejected`, `execution_exception`.
- `backend/services/trade_execution.py` — **PATCH 2026-04-30 v12** — `execute_trade` broker-reject + exception branches now call `await bot._save_trade(trade)` so REJECTED trades are no longer orphaned in process memory. This was the likeliest root cause of the April 16 → April 29 silent regression (zero `bot_trades` inserts despite 32 AI-gate GOs/day).
- `backend/routers/diagnostic_router.py` — `/api/diagnostic/trade-drops` endpoint added 2026-04-30 v12; aggregates drops by gate, names `first_killing_gate`, returns last 25 rows with full context.
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `backend/services/enhanced_scanner.py` — 38 trade detectors, scanner loop, `_apply_setup_context` matrix gate + multi-index regime stamping (2026-04-30), `LiveAlert` dataclass with context fields (`market_setup`, `is_countertrend`, `out_of_context_warning`, `experimental`, `multi_index_regime`)
- `backend/services/market_setup_classifier.py` — `MarketSetup` enum (7 + NEUTRAL), `MarketSetupClassifier` (daily-bar driven), `TRADE_SETUP_MATRIX`, `TRADE_ALIASES`, `EXPERIMENTAL_TRADES`, `lookup_trade_context()`, `_sync_classify_window()` for training-time per-bar labels (2026-04-30)
- `backend/services/in_play_service.py` — **NEW 2026-04-30** — unified in-play scorer used by both the live scanner (`score_from_snapshot`) and the AI assistant (`score_from_market_data`); runtime-tunable thresholds persisted to `bot_state.in_play_config`; SOFT mode by default (stamps `LiveAlert.in_play_score/reasons/disqualifiers` only), STRICT mode rejects alerts when `is_in_play=False`
- `backend/services/multi_index_regime_classifier.py` — **NEW 2026-04-30** — `MultiIndexRegime` enum (9 buckets), `MultiIndexRegimeClassifier` reads ~25 daily bars per index (SPY/QQQ/IWM/DIA), 5-min market-wide cache, `derive_regime_label_from_features()` for training
- `backend/services/sector_tag_service.py` — **NEW 2026-04-30** — static GICS-aligned `STATIC_SECTOR_MAP` (~340 most-liquid stocks) + ETF self-mapping; `tag_symbol`, `tag_many`, `coverage`, `backfill_symbol_adv_cache` (idempotent)
- `backend/services/sector_regime_classifier.py` — **NEW 2026-04-30** — `SectorRegime` enum (6 buckets: STRONG/ROTATING_IN/NEUTRAL/ROTATING_OUT/WEAK/UNKNOWN), `SectorRegimeClassifier` reads 11 SPDR ETFs + SPY (5-min market-wide cache), `SectorRegimeHistoricalProvider` for training-time per-sample sector regime lookup with per-(etf,date) caching
- `backend/services/ai_modules/composite_label_features.py` — **NEW 2026-04-30** — one-hot helpers: `SETUP_LABEL_FEATURE_NAMES` (7), `REGIME_LABEL_FEATURE_NAMES` (8), `SECTOR_LABEL_FEATURE_NAMES` (5), `ALL_LABEL_FEATURE_NAMES` (20), `build_label_features(market_setup, multi_index_regime, sector_regime)`
- `backend/scripts/backfill_sector_tags.py` — **NEW 2026-04-30** — one-shot CLI for sector backfill
- `backend/services/setup_landscape_service.py` — `SetupLandscapeService` with 4 narrative voices (morning/midday/eod/weekend), 1st-person voice rules, 60s cache, **regime line preface (2026-04-30)** + `LandscapeSnapshot.multi_index_regime/regime_confidence/regime_reasoning` + **auto-records snapshot to `landscape_predictions` (2026-04-30) + cites yesterday's grade in morning narrative**
- `backend/services/landscape_grading_service.py` — **NEW 2026-04-30** — `LandscapeGradingService` records every snapshot's prediction to `landscape_predictions`, grades EOD by joining to `alert_outcomes` (A/B/C/D/F per Bellafiore Setup family), `get_recent_grades` powers the morning briefing's "Quick receipt — yesterday I predicted ..." citation. **`get_weekly_summary` (2026-04-30 v5)** rolls up the past 7 days of grades for the Sunday weekend voice ("Last week's record — 3A · 1B · 1C — strong directional read")
- `backend/services/ai_assistant_service.py` — `get_coaching_alert()` injects landscape narrative + voice rules + multi-index regime fields into AI prompts and payload (2026-04-30)
- `backend/services/ai_modules/timeseries_service.py` — training (`_train_single_setup_profile`) + prediction (`predict_for_setup`) plumbed with the 15 categorical label features (2026-04-30)
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script
- `backend/services/smart_levels_service.py` — `compute_smart_levels`, `compute_stop_guard`, `compute_target_snap`, `compute_trailing_stop_snap` (added 2026-04-29 — liquidity-aware trail)
- `backend/services/stop_manager.py` — `set_db(db)` injection enables HVN-anchored breakeven + trail (2026-04-29). **Realtime stop-guard re-check (2026-04-30 v11)**: `_periodic_resnap_check` runs after every `update_trailing_stop` call (60s per-trade throttle), re-snaps to fresher HVN levels in `breakeven`/`trailing` modes, ratchet-only.
- `backend/services/sector_tag_service.py` — `tag_symbol_async` (2026-04-30 v11) full fallback chain: STATIC_MAP → `symbol_adv_cache.sector` → Finnhub `stock/profile2` industry → `_industry_to_etf` mapper → persist back to Mongo. `_PRIORITY_OVERRIDES` resolves conflicts (Biotech > Tech, REIT > Industrial, Renewable > Energy); `_EXPLICIT_NONE` blocklist returns UNKNOWN for cryptocurrency / SPAC / trust / fund.
- `frontend/src/components/sentcom/v5/ShadowVsRealTile.jsx` — **NEW 2026-04-30 v11** — V5 status-strip tile, reads `/api/ai-modules/shadow/stats` + `/api/trading-bot/stats/performance` every 60s, renders side-by-side win-rate + divergence signal (`shadow ahead` / `shadow behind` / `in sync` per ±5pp).
- `app/memory/SETUPS_AND_TRADES.md` — canonical doc for the 7 Setups + 22 Trades + matrix + aliases


## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)


## Audit tooling (v19.34.4 — 2026-05-04)

When operator wants to confirm bot accounting matches IB reality
(phantom shares, partial-fill drift, orphan adoptions):

1. Paste IB TWS Trades-pane → `memory/audit/<YYYY-MM-DD>_ib_fill_tape.txt`.
2. `python -m scripts.audit_ib_fill_tape --input ... --out report.md` — standalone parser + FIFO PnL + verdict classifier.
3. `python -m scripts.export_bot_trades_for_audit --date YYYY-MM-DD --out bt.json` — Spark Mongo export of today's `bot_trades` rows.
4. Re-run auditor with `--bot-trades-json bt.json` for cross-check section flagging IB-but-not-bot, bot-but-not-IB, and qty mismatches.

Full runbook: `memory/runbooks/audit_ib_fill_tape.md`.


## Scanner runtime architecture (v19.15 + v19.16 — 2026-04-30)

### Per-cycle context cache (v19.15)
At the top of each `_run_optimized_scan()` tick, `_refresh_cycle_context()`
prefetches the two market-wide classifiers (Multi-Index Regime + Sector
Regime) into a `Dict[str, Any]` on the scanner. `_apply_setup_context`
reads from this dict for all alerts in the same cycle instead of
awaiting the classifiers per-alert. TTL: 60s; on miss we fall back
to the per-alert path which is also TTL-cached internally (5 min).

### Tier-aware detector dispatch (v19.16)
`_intraday_only_setups` is a superset of `_intraday_setups` listing
every detector with explicit sub-5min timing or playbook "intraday
only" spec. The dispatch loop in `_scan_symbol_all_setups` skips
these detectors when the symbol's tier (from `_tier_cache`) is
non-intraday. Saves ~40% of detector calls on swing+investment
cohort and prevents stale-snapshot signals from polluting the AI
training pipeline.

## EOD Auto-Close (v19.14 — 2026-04-30)

- **Default window**: 3:55 PM ET on regular trading days, 12:55 PM ET
  on half-days (operator sets `EOD_HALF_DAY_TODAY=true` in env that
  morning). Configurable via `bot_config.eod_config.{close_hour,
  close_minute, enabled}` in Mongo.
- **Scope**: ONLY applies to trades flagged `close_at_eod=True` in
  `STRATEGY_CONFIGS` (intraday/scalp/day strategies). Swing
  (`squeeze`, `daily_*`, `earnings_momentum`, `sector_rotation`) and
  Position (`base_breakout`, `accumulation_entry`,
  `relative_strength_position`, `position_trade`) trades are
  explicitly held overnight.
- **Parallel closes**: `asyncio.gather` over all eligible trades
  bounds wall-time to single-trade IB-roundtrip latency.
- **Retry-on-partial**: if any close fails, the manage-loop tick
  (~every 1-2s) retries until either all succeed OR market_close_hour
  passes — at which point an `eod_after_close_alarm` WS event fires.
- **WS surface**: `eod_close_started` (window opens) + `eod_close_completed`
  (final state) + `eod_after_close_alarm` (positions still open after 4:00 PM).


## v19.34.110 — Pipeline Tile Split + Event-Driven Pusher ACK (2026-02-12)

**P3-A**: V5 HUD ORDER tile now renders `5q + 3@ib` split when there
are orders sitting at IB in `IB_PENDING` (v109). Falls back to flat
count when `ib_pending = 0`. Backend `SentComStatus` exposes
`order_pipeline.ib_pending`; also fixes a latent typo where the
service was reading `pending_count` / `executing_count` / `filled_today`
instead of the actual `get_queue_status` keys.

**P3-B**: `ib_data_pusher.py` no longer blocks on a 30s `while` loop
after `placeOrder`. Subscribes `trade.statusEvent` and reports
terminal states (Filled / Cancelled / Inactive) back to Spark
immediately. Pre-v110 polling capped queue throughput; v110
serializes only on `placeOrder` itself, not on terminal-state
discovery. The "still pending after 30s" fallback branch and the
"Unknown status:" rejection branch are removed entirely — under
event-driven dispatch we never time-out a transient.

Pusher redeploy required for P3-B; backend hot-reloads for P3-A
after frontend `yarn build`.

## v19.34.111 — Queue idempotency + reconciler attach cooldown (2026-02-12)

Root-cause fix for the bounce loop v109 patched at the symptom layer.
`order_queue_service.queue_order()` now returns the existing `order_id`
when the caller's `trade_id` is already in-flight (PENDING / CLAIMED /
IB_PENDING / EXECUTING). Reconciler's `attach_oca_stop_target` call
sites are throttled by a per-`trade.id` 60s cooldown
(`BRACKET_ATTACH_COOLDOWN_S` env-overridable). Two layered guards
ensure duplicate intents can't reach IB regardless of caller path.

## v19.34.112 — Scalp SL/TP calculation fix (2026-02-12)

Scalp setups (`scalp`, `nine_ema_scalp`, `spencer_scalp`, `abc_scalp`)
were silently using the generic 1.5-2.0× base ATR multiplier and the
fixed `[1.5R, 2.5R, 4R]` target ladder — wrong for <5min holding
periods. v112 ships:
- Tight ATR multipliers (0.4-0.5×) with min-clamp bypass for scalps only
- Trade-style-aware target ladder: scalp `[1R, 1.5R]`, intraday `[1.5R, 2.5R]`, swing `[1.5R, 2.5R, 4R]` (legacy), position `[2R, 4R, 8R]`
- `target_snap` skipped for scalps (avoids widening tight targets to S/R clusters)

Existing positions are NOT migrated — only new alerts get the v112 treatment.

## v19.34.113 — Setup Grading Subsystem (2026-02-12)

Per-setup_type performance scoreboard. Daily EOD tick (16:10 ET) walks
closed `bot_trades` and upserts per-(setup_type, date) snapshots into
`setup_grade_records`. Rolling 30-day grade card surfaces via the
V5 `SetupGradeChip` next to `TradeStyleChip` on positions + scanner
cards.

**Grade ladder**: A+ / A / B+ / B / C / F / INSUFFICIENT_DATA (< 5
trades). Formula gates on win_rate + avg_r — operator-readable, not
Sharpe. Sample-weighted rollup math (1-trade days don't count equally
with 20-trade days).

**API**: GET `/api/setup-grades`, GET `/api/setup-grades/{setup_type}`,
POST `/api/setup-grades/compute`, GET `/api/setup-grades/history/{setup_type}`.

**Observe-only**: chip and `get_grade_warning` API exist but do NOT
block alerts. A future PR can wire as a hard filter after a week of
live data validates the formula.

**Validates v112**: scalp ATR multiplier choices now have a measurable
scorecard. If `nine_ema_scalp` grades F at 0.4× consistently, widen
empirically rather than guessing.

## v19.34.114 — Yesterday's grade card in morning briefing (2026-02-12)

`GET /api/setup-grades/yesterday-recap` walks back up to 7 days to
find the most recent trading day with grade data; returns winners /
losers / a deterministic `summary_line` the LLM briefing can quote
verbatim. V5 `MorningPrepCard` renders the recap in its expanded
section: emerald winners, rose F-grade losers, italic advice.
Operator and LLM briefing now read identical text — no hallucination
surface on the citation.


## v19.34.115 — V6 integration prep + locked contracts (2026-02-12)

Locked the integration plan for v110–v114 → V6 panel rollout.
New: `/app/memory/V6_INTEGRATION_v110_v114.md` (master index).
Appended cross-reference sections to all three existing V6 specs.
Backend: promoted v111 cooldown counter to a 200-entry deque with
`get_attach_cooldown_skips()` public read — V6 Safety Activity Stream
aggregator dependency now satisfied. 5 non-negotiable invariants
codified for V6 implementation. 220/220 cumulative tests pass.

## v19.34.116 — POST /api/trading-bot/retune-stop (2026-02-12)

The "Tighten stop →" backend for V6 Position Health Console's
STOP-WIDE-FOR-STYLE row state. Recomputes the stop via v112's
OpportunityEvaluator table and re-fires attach_oca_stop_target under
v111 cooldown protection. Supports dry-run via `dry_run: true`.
Lets the operator surgically retune legacy v111-era scalp positions
WITHOUT waiting for V6 to ship. 18/18 new tests, 238/238 cumulative.

V6 Integration index marked the only remaining Phase C backend
dependency SHIPPED.

## v19.34.117 — POST /api/trading-bot/retune-stop/bulk-scalps (2026-02-12)

Bulk-fire version of v116's retune-stop. Default `dry_run=true`
(safety inversion vs single endpoint). Scans all open scalps, filters
by `stop_distance/atr > 1.0` (configurable), and applies v112's
corrected stop via shared `_retune_stop_core` helper. v111 cooldown
+ idempotency apply per-trade. One operator call to fix every
legacy wide-stop scalp in the book. Wires into V6 Position Health
Console's "Tighten all wide-stop scalps" batch action.
17/17 new tests, 255/255 cumulative v100→v117 PASS.

---
## Status update — 2026-06-05 (forked session)

### Done & verified on DGX (pytest 8/8, endpoint live)
- ✅ m5 (canonical grading/EV), m8 (tidal_wave momentum split / fading_bounce reversion) — code+data+tests committed (6696927f).
- ✅ Issue 2 — INTRADAY_BRACKET_V2 (runner/target/swing_hold/position_hold archetype brackets) — committed (b652f364).
- ✅ A — bracket reconciliation trace (`scripts/probe_bracket_reconcile.py`).
- ✅ B — horizon-aware daily-bar lookback (`market_setup_classifier.py`).
- ✅ C — `/api/scanner/in-play-health` endpoint + `scripts/probe_inplay_health.py`.
  (Deployed via compact anchored idempotent applier on paste.rs; backups *.bak.abc0606.)

### Next / backlog (reconciled 2026-06-05 — see ROADMAP.md for the live list)
- ✅ SHIPPED (verified in code): EV Leaderboard on MC (`EVLeaderboard.jsx`),
  adopted-position P&L split backend (`sentcom.py` `adopted_pnl_today`),
  `hold_seconds` at close (`trading_bot_service.py:1015`), EOD honors trade-style
  (`opportunity_evaluator.py` v245).
- 🟡 P1 OPEN: Bot-Vitals header on MC (off `/api/scanner/in-play-health`); MC sticky
  per-symbol search/filter across 5 lanes; squeeze intraday-vs-swing `trade_style` split.
- 🟢 P2 OPEN: L2 depth probe (`probe_l2_depth.py` — not built); "why-not-auto-traded" EV
  chip (v294 `ev_below`); adopted P&L split frontend chip; Gameplan boost surfacing;
  EOD close popup modal; scanner feed group/display; regime classifier tolerance patch.
- 🟢 P3 OPEN: break up server.py monolith; refresh AGENTS.md for SSOT architecture.

### Deploy/test constraints (unchanged)
- DO NOT use testing_agent (DGX hardware-bound). Validate via pytest + curl + probes in container, ship idempotent appliers via paste.rs.
- DGX restart: `./start_backend.sh --force`.

---
## m-series COMPLETE — 2026-06-05
- ✅ m1–m9 all shipped & verified on DGX (m9 = exit_archetype MFE/MAE data-override, paste.rs/vOlNF, 16/16 pytest).
- Open (m9 validation only): live market-hours run of `probe_bracket_reconcile.py --base http://localhost:8001` against open positions to confirm bracket attach+reconcile on the real IB path.
- Deferred cosmetic (fold into next deploy): probe CLI "no live DB" note (already fixed in container, not yet shipped).
- Next P1 UI: EV Leaderboard on Mission Control; Bot-Vitals header; MC sticky per-symbol search/filter across 5 lanes; Gameplan prioritization boost.

---
## ML Roadmap — decision logged 2026-06-05 (per-setup / realized-data models)

DECISION: Do NOT build per-raw-setup PRIMARY models. Family-keyed price-window
primaries (triple-barrier on ib_historical_data) pool statistical power and
generalize better; raw setups don't add samples to them. Setup nuance already
lives in per-family feature extractors + meta-labeler + m5 grade/EV pillars.

PLANNED (sample-gated, P1 when data allows): realized-outcome META-LABELING layer
— one model trained on bot_trades (entry-context features → realized win/R), with
`canonical_setup` as a FEATURE (not per-setup heads), gating/sizing the primary
signals. López de Prado meta-labeling; codebase already scaffolded (triple_barrier_
labeler, purged_cpcv). Validate with purged CPCV vs the current confidence gate
before it sizes anything.

GATE: needs ~hundreds of closed trades total, ~50–100 per canonical setup. Probe
shows tidal_wave=0, fading_bounce=2 (May→) — NOT trainable yet. Interim = the
statistical layer (learning-loop win-rate/EV, m5 grade, m9 override) — correct for
small N. Per-setup split only if a high-volume setup shows systematic calibration
error vs its family head (evidence-gated, one at a time).

NEXT ML STEPS:
1. (now) plain freshness retrain of family primaries (probe = GO; models ~39d stale).
2. (todo) extend retrain_readiness.py with a "realized-outcome trainability" budget
   (total + per-canonical closed-trade counts, label-field completeness, GO/WAIT for
   meta-labeling).
3. (later, gated) build the meta-labeling layer when the budget says GO.
4. (watch) confirm hold_seconds is stamped on bot_trades at close (net_pnl/mfe_r/
   mae_r already present) — needed as a clean label/feature for the meta-model.
   ✅ CONFIRMED 2026-06-05: `trading_bot_service.py:1015` stamps `hold_seconds` via
   `_compute_hold_seconds(entry_ts, close_ts)` at close.

---
## Action item added 2026-06-05: GPU-torch swap (P2, own task)
- torch is CPU build (2.10.0+cpu) while GPU works for XGBoost (CUDA enabled). CNN/deep-learning heads (P9 chart-pattern, P11 CNN-LSTM) train on CPU = slow.
- TODO: swap to a CUDA-enabled torch + matching torchvision (aarch64/Spark GB10) so P9/P11 train on GPU (~5–10× faster). Careful stack change, do as isolated task with a backup of the working CPU torch+torchvision (0.25.0). Verify `torch.cuda.is_available()` + re-run tensor probe after.

---
## 2026-06-08 — A+B+C audit P1 batch (v19.34.308–310) — PATCH READY (operator-apply pending)
Consolidated patch: https://paste.rs/q0CT1 (supersedes A+B-only paste.rs/p8mys).
- **A (v308)** IB-Gateway STARTUP hard-block probe: new `services/ib_boot_probe.py`, 30s grace poll of the IB execution feed; on fail → trips existing kill-switch (bot can't arm) + `/api/system/health` RED via new `ib_boot_probe` subsystem. Manual-reset by design.
- **B (v309)** Fundamental absent-data → NEUTRAL 50 (was optimistic: inst→80/float→65/earnings→60). `tqs/fundamental_quality.py`.
- **C (v310)** SMB: (C-1 always-on) persist `smb_5var_score` in `LiveAlert.to_dict()`; (C-2 env-gated `SMB_CHECKLIST_TIMEFRAME_AWARE`, DEFAULT OFF) timeframe-aware checklist thresholds + 50-SMA swing MTF confluence; (C-3 operator follow-up) drop the C→50 decompress via `TQS_SETUP_DECOMPRESS=false` after verifying real scores flow.
- Tests: 11/11 new (test_v308/309/310) + v305/smb_profiles/l4c regression green. NO testing_agent (DGX mandate).
- STILL PENDING (operator): rotate Atlas DB password (P0 security, old creds in git history).


---
## 2026-06-09 — Command Center regime + caps + HUD (v316f/g/h) — ✅ SHIPPED & LIVE ON DGX
- **v316f** (paste.rs/iagua): RegimeStrip.jsx (4-lane multi-tf band: context/lanes/long-short
  modes/$TICK/per-index/divergence) + `/summary` surfaces `multi_tf` + slashed-zero font
  (`.font-mono-data` font-feature "zero") + position cap unify → 25 (safety kill-switch
  5→25, LLMRules advisory floor 10→25). Operator set bot.max_open_positions=25 via POST
  /risk-params → `diag_risk_truth.py` confirms EFFECTIVE=25. Daily-loss left at 1%/~$2k
  (operator choice B).
- **v316g** (paste.rs/cYsqy): ROOT-CAUSE fix — the v315/v316 multi_tf ENGINE code
  (`_calculate_multi_tf`+`_get_tf_bars` in market_regime_engine.py, `get_historical_data`
  in ib_direct_service.py) had never landed on the DGX (only the helper module had). Strip
  was empty because `/current` returned multi_tf=null. VERIFIED LIVE: context=ALIGNED_UP,
  lanes 64.9/51.9/88.8/65.0, internals 64.8, per_index SPY60.6/QQQ60.5/IWM85.5. Intraday
  lanes fed by `live_tick` bars (queue historical returns no-data by design).
- **v316h** (paste.rs/mNomy): HUD top strip decluttered 14→6 core chips. Diagnostics
  (Brackets-Path/Connectivity/Scanner-Coverage/Boot-Reconcile/Drift-Guard/Cancel-Queue)
  folded into Ops Status popover "Pipeline Diagnostics" group; risk chips (LLM-Rules/
  Order-Policies) into Edge & Performance "Guardrails" group. Applied + yarn-built clean.

### Standing operator reminders (unchanged, P0/P1)
- 🔴 Rotate Atlas DB password (old creds in git history).
- 🟡 Retrain with TB_PT_MULT=1.5 / TB_SL_MULT=1.0.
- 🟡 v311 Monday-freshness buffer (paste.rs/L2rc2) — applied this session; verify the
  weekend-aware test is green after restart.

### Next P1
- M0 laddered server-side scale-out (multi-leg OCA).
- Optional: NEW effective-limits Guardrails chip (Pos 25 · Loss $5k/1%) surfacing the
  reconciler truth at a glance.

---
## 2026-06-11 — v19.34.319 gap-fill NO-PEEK fix — ✅ DONE & VERIFIED (deployed on DGX)
- Closed the gap-fill look-ahead leak (audit: 76.2%/49.6%/15.5% of 15m/5m/1m fills in the
  open bar). Training now decides AT THE OPEN: features end at bar i-1, bar-i gap features
  neutralized, target over [i+1, i+w]. Patch https://paste.rs/hIfcL applied; verify script
  showed balanced fill% (49/41/42%). 16/16 pytest.
- Honest models promoted: gap_fill_1min acc 0.750, 5min 0.689, 15min 0.706 (down from leaky
  0.83-0.94), healthy two-sided recall. Leaky 5min/15min + retired daily/weekly EVICTED via
  scripts/evict_leaky_gap_models_v319.py (paste.rs/KROyI). Only 3 honest intraday gap models remain.

## P1 patches — ✅ ALL DEPLOYED & GREEN on DGX (2026-06-11)
- v319d Phase-8 ensemble FFD match-fix → applied via https://paste.rs/U7WVq (training_pipeline.py).
  Sub-models now get real FFD (not zero-filled) in the meta-labeler. 4/4 pytest on DGX. Takes
  effect next ensemble/full retrain. FFD flag confirmed ON.
- v319b embargo + v319c GBM_FORCE_PROMOTE override → timeseries_gbm.py. The Brcge git-patch
  failed (DGX file had ~8-line drift above the class) so deployed via a line-number-proof
  STRING PATCHER https://paste.rs/GrkS1 (idempotent, py_compiles before write). +68 lines,
  12/12 pytest on DGX. Embargo de-biases all GBM train/val splits (logs `embargo gap: purging
  N boundary sample(s)…` on next full run); force-promote is the reusable lever to evict a
  known-invalid incumbent on future leakage fixes (env GBM_FORCE_PROMOTE).
  NOTE for future agents: prefer string patchers over git-diff patches for timeseries_gbm.py /
  large monolith files — line numbers drift between the container fork and the live DGX tree.

---
## 2026-06-10 — v322 Regime-First Funnel SHIPPED (container-validated, patch paste.rs/RVbeU)
- c2 (symbol regime → gate), sector regime → gate scoring, c3/T7 RS Leadership +
  Regime Focus List, focus-list scan-cadence promotion, P7 regime-conditional
  sample-count bug fix, mplfinance log-spam suppression. 43 new tests.
- "P1: per-stock multi-TF regime; regime-first scanning funnel (c3)" and
  "P2: RS leadership factor (RS 80+)" from the backlog below are now DONE.
- Remaining backlog updates: apply v322 on DGX BEFORE the full retrain (P7 fix
  affects the 28 regime-conditional models P-WIRE phase 2 depends on).

## Remaining backlog (from handoff, post-audit)
- Standing P0 (MANUAL, user action): rotate Atlas DB password (old creds in git history).
- PARKED: P-WIRE phase 2 wiring (needs ~5000 shadow decisions from pwire_shadow_eval.py).
- P1: ~~per-stock multi-TF regime (market_regime_engine.py); regime-first scanning funnel (c3)~~ ✅ v322.
- P2: dedicated intraday DL model; ~~RS leadership factor (RS 80+)~~ ✅ v322; Wyckoff trigger; L2 probe;
  break up server.py monolith.

---
## 2026-06-11 — v322k + v322l: orphan cancel↔re-issue loop + false-rejection re-claim
- **v322k (DEPLOYED on DGX, patch https://paste.rs/5H8Zw, 5/5 pytest on DGX)**: killed the
  UNP/USB pathological loop (orphan-GTC auto-sweep cancelled ADOPT-OCA brackets the
  naked-sweep had just issued, repeat ~60s). Root cause was NOT the limit(2000) cap (window
  was 890 rows) but stale order-id fields in the bot_trades snapshot. Fix: classifier now
  proves ownership via the trade id embedded in the OCA group name
  (ADOPT-OCA-{sym}-{trade_id}-{nonce}, ≥8-char token match) + oca_group threaded through
  tier-1/tier-3 order snapshots + sort("executed_at",-1) before the cap as defence.
  Files: services/orphan_gtc_reconciler.py, tests/test_v322k_orphan_loop.py.
- **v322l (CONTAINER-VALIDATED, patch https://paste.rs/fIwcU, 6/6 pytest, AWAITING DGX apply)**:
  fixes the upstream IB Gateway race — orders tagged `parent_not_filled:cancelled` →
  broker_rejected while the fill lands at IB. The v19.34.15a poll-back now RE-CLAIMS the
  rejected trade in-place (direction guard, qty clamp to |delta|, R-preserve via true avg
  fill from ib_direct fills by entry_order_id, brackets re-attached via
  attach_oca_stop_target, `trade_reclaimed_v322l` stream event) instead of leaving it to
  generic orphan adoption that lost setup/SL/PT.
  Files: services/trade_execution.py, tests/test_v322l_silent_fill_reclaim.py.
- Regression checked: all other failures in orphan/naked/trade-execution suites confirmed
  PRE-EXISTING (identical pre/post patch).
- NEXT: M0 laddered server-side scale-out (multi-leg OCA) — user's stated next priority.

---
## 2026-06-11 — v322m + v322n: scalp liquidity proof + ETF universe re-evaluation
- **v322m (patch https://paste.rs/2Cc5M, 30/30 tests, AWAITING DGX apply)**: AIQ/CZR audit
  found CZR ORB scalps judged against the $2M investment floor (scan_tier=investment +
  trade_style=scalp) with rvol=0.0, and AIQ scalping with only 2.2M sh/day. Fixes in
  enhanced_scanner: (1) floor = STRICTEST-OF(scan_tier, trade_style); (2) scalp/intraday
  alerts must prove RVOL ≥ SCALP_MIN_RVOL (default 1.0, rvol<=0 fail-closed); (3) scalp
  share-ADV floor SCALP_MIN_SHARE_ADV (default 3M sh/day, fail-closed). Env=0 disables.
- **v322n (patch https://paste.rs/quG8o, 9+66 tests, AWAITING DGX apply)**: ~25% of the
  top-400-dollar-ADV L1 universe was ETFs. New services/etf_classifier.py (8 classes).
  Focus list excludes leveraged_inverse/bond_cash/income/index_clone (carve-out:
  TQQQ/SQQQ/SOXL/SOXS per user). L1 top-N drops bond_cash/income/index_clone/single-stock
  leveraged (context ETF set unaffected; takes effect on pusher restart). bot_trades now
  stamped is_etf/etf_class for per-class EV measurement.
- Diagnostic created: /app/scripts/diag_liquidity_trail.py (paste.rs/rQfZB).
- FINDING: IB_PUSHER_L1_AUTO_TOP_N is set as a Windows env var (not in .bat) — auto-fetch
  works (404 symbols). The 14-symbol .bat IB_SYMBOLS list is fallback-only, harmless.
- NEXT: user applies v322m+v322n, then M0 laddered scale-out. Future: per-class EV review
  after ~2 weeks of tagged trades; ELF→XLE sector mis-tag; CZR tier misclassification probe.

---
## 2026-06-11 — v322o Quick-Wins Batch (CONTAINER-VALIDATED, patch https://paste.rs/VMM4l, AWAITING DGX apply)
- **#10 TQS stuck at C/C+ — ROOT CAUSE FOUND (display bug)**: backend calibration healthy
  (user diag: reference_n=16,069, scores 45–71). `TqsBadge.jsx` re-derived the grade from
  the raw score with the STATIC ladder (>=85=A…) "as single source of truth" (v19.34.257),
  undoing the v19.34.228 percentile calibration on the frontend. Fix: badge now prefers the
  backend-stamped calibrated `tqs_grade` (all call sites already pass it as gradeFallback);
  static ladder kept only for legacy rows with score-but-no-grade.
- **#5 2% toast spam**: usePriceAlerts.js dedup key was per-minute → re-toasted every 60s.
  Now ONE alert per symbol per 15 min (ALERT_COOLDOWN_MS).
- **#8 Command-center cutoff**: V5 root overflow-hidden → overflow-y-auto + main row hard
  floor min-h-[900px] + center column min-heights (chart 340 / stream 200 / drawer 240).
  Page scrolls on short viewports instead of crushing SentCom Intelligence / Deep Feed.
  v19.34.1 chart-ResizeObserver regression cannot recur (row height never content-driven).
- **#11 slow charts step 1**: /api/sentcom/chart now returns `timings` meta
  (cache_ms/mongo_ms/rpc_ms/indicators_ms/markers_ms/total_ms) on hit/miss/failure +
  WARNING log `[v322o chart-slow]` for loads > CHART_SLOW_LOG_MS (1500ms default).
  Verified all 4 paths via curl with seeded bars. NEXT: user loads slow charts → timings
  convict the phase → fix (likely short-circuit RPC merge for unsubscribed symbols).
- **#3 Scalp Exit Autopsy**: new read-only backend/scripts/scalp_exit_autopsy.py
  (https://paste.rs/Nv5cM): exit-bucket table (TP/SL/DECAY/EOD/EXTERNAL/MANUAL), TP
  realized-R distribution (M0 ladder input), decay post-exit replay vs 5-min bars — %
  stop-saved vs % left-on-table ≥0.5R/1R (v322p input). Validated against synthetic trades.
- NEXT: user applies v322o (backend restart needed) + pastes autopsy output + chart timings
  → then M0 laddered scale-out (3-leg OCA 40%@+1R/30%@+2R/30% runner, env-tunable, with
  orphan-safety: legs must share OCA group + ownership token per v322k conventions).

## 2026-06-11 — M0 Laddered Scale-Out BUILT (CONTAINER-VALIDATED, awaiting DGX apply)
- **Order-path finding**: DGX runs BOT_ORDER_PATH=direct (probe confirmed). The v19.34.103
  pusher ladder NEVER fired — every bracket has been single-target full-qty via
  ib_direct.place_oca_stop_target. Autopsy v2: EXT_TP 8 (+1.08R avg) vs EXT_SL 17
  (-1.62R avg — slippage red flag, backlog probe) vs EXT_SCRATCH 61 (71%).
- **M0 architecture** (paste.rs: patcher zQaVU, manager a4r4M, tests s6pgK):
  1. order_policy_registry: scalp/intraday tp_ladder → 40%@1R / 30%@2R / 30% runner
     (cap +4R scalp / +6R intraday). Env: M0_TP_LADDER_SCALP/_INTRADAY="0.4@1.0,...".
     _ladder_from_env validates (2-5 rungs, pcts sum 1, ascending R) else code default.
  2. ib_direct_service: _m0_ladder_plan (gates: M0_LADDER_ENABLED default true,
     M0_LADDER_STYLES default scalp,intraday, M0_LADDER_MIN_SHARES default 10) +
     _m0_place_oca_ladder: PER-LEG OCA pairs (stop_i+target_i own group
     `ADOPT-OCA-{sym}-{tradeid}-L{i}-{nonce}`, ocaType=1 — leg TP fill cancels only its
     own stop). Stops placed FIRST; any stop submit-fail or permanent-reject → cancel all,
     success=False (caller flattens). Target fail → stop-only leg, partial=True.
     All child ids → trade.target_order_ids so EVERY existing close/EOD/decay cancel
     path covers the ladder. modify_stop_price: in-place IB stop modify (same orderId,
     new auxPrice — OCA group preserved).
  3. NEW services/m0_ladder_manager.py: manage-loop tick. Leg-fill detection =
     open-orders snapshot (10s cache, blank snapshot → skip, never infer fills) +
     position-deficit corroboration; TP-vs-stop attribution via MFE; stamps
     targets_hit → EXISTING StopManager does BE-after-leg1/trail-after-leg2 internally;
     stop-sync pushes ratcheted current_stop to surviving IB stops (ratchet-only,
     M0_STOP_SYNC_MIN_R=0.1R min delta, M0_STOP_SYNC_INTERVAL_S=30s throttle).
  4. position_manager: manage hook after _update_trailing_stop + hard guard in
     check_and_execute_scale_out (m0_legs → return; kills v19.34.7 double-sell class).
- **Testing**: 36 new tests + 37 v322k-n regression all pass in container. Backend boots.
  test_strategy_configs.py failures are PRE-EXISTING (identical at HEAD).
- NEXT: user applies M0 + runs tests + paper-session validation checklist; then v322p
  decay (LIGHT touch — autopsy showed timer ~neutral), v322q, chart-slow phase fix
  (awaiting [v322o chart-slow] log lines from user).
- 2026-06-11 DEPLOYED: M0 applied on DGX (6/6 patches, 36/36 tests on-box), backend
  restarted clean (23s boot), registry ladders confirmed live (scalp 40/30/30 cap 4R,
  intraday cap 6R), health green incl. ib_gateway via ib-direct. AWAITING: first live
  [M0 LADDER] entry + leg-fill/BE-sync validation; [v322o chart-slow] log lines; TQS
  badge A/B visual confirmation.
- 2026-06-11 LIVE VALIDATION: M0 fired on 7 entries day 1 (C, SLV, CZR, IGV, CASY, KRE, B)
  — placement/qty-split/OCA-pairs all correct. BUG M0a found+fixed: scanner's single far
  target (~2.5R) became leg 1 while legs 2-3 used R-math → INVERTED ladders (C L1@145.36
  "1R" > L2@143.26 2R). Fix: explicit targets only honored as full monotonic ladder, else
  pure R-math (patcher U7Qtd, tests 0SILH, 40/40 pass). v322o2 taller layout shipped
  (row 1600px, browser-verified 1792px scroll). check_m0_status.py shipped (N81iR).
  TQS true-0-100 display rescale → backlog (pair with Tier 2a isotonic calibration).
- 2026-06-12 M0c SHIPPED (patcher https://paste.rs/lfViT): root cause of CASY ladder-kill
  CONFIRMED as unprimed in-memory snapshots after backend restarts (NOT a 4h-dead pusher —
  `_pushed_ib_data` wipes on every restart; boot audit fires 10s later; `if fresh:` in
  _fetch_ib_positions_async treats empty ib_direct reads as failure → falls to wiped
  snapshot → everything classified naked_no_position → auto-flush killed valid legs).
  Fixes: (1) audit_orphan_gtc_orders fail-closed abort on empty positions snapshot while
  bot tracks active trades OR pusher not fresh; (2) classifier downgrades matched-ACTIVE-
  trade+flat-snapshot to awaiting_data (never auto-cancel); (3) naked-sweep skips on
  blank order snapshot w/ tracked stop ids; (4) naked-sweep ladder-aware (ANY working
  m0_legs stop live at IB = protected; all-legs-lost → mark "lost" then reissue);
  (5) reissue no longer clobbers target_order_ids when reissue placed new M0 ladder;
  (6) consolidator refuses to merge groups holding working m0_legs. 15 new tests
  (test_m0c_reconciler_guards.py); 3 stale tests updated to current contracts
  (v89 cancel-queue fallback, async positions fetcher, v151 SAFE_TO_AUTO_CANCEL set);
  4 pre-existing sweep-test failures (v285 flip-guard unverifiable positions) repaired.
  148/148 relevant tests green in container. AWAITING: user applies M0c on DGX, runs
  pytest, flips M0_LADDER_ENABLED=true, restarts backend, validates next live ladder.
- 2026-06-12 M0c DEPLOYED+VERIFIED ON DGX: patcher lfViT (17/17 applied) + follow-up
  M0c-t1 patcher BaMtZ (test-only: _patch_fetch mocked tier pusher_orders_snapshot →
  ib_direct; DGX exports BOT_ORDER_PATH=direct so the v163 tier-mismatch guard skipped
  the sweep and 7 tests failed — env-dependent test flaw, reproduced+fixed in container).
  Final DGX run: 91/91 green in .venv (repo root ~/Trading-and-Analysis-Platform, use
  `source .venv/bin/activate`, NOT system python3.12). User instructed to flip
  M0_LADDER_ENABLED=true and restart. VALIDATION PENDING: clean boot audit (or M0c
  EMPTY-SNAPSHOT GUARD abort) with zero cancellations; next live ladder legs surviving
  restarts.
- 2026-06-11 v322t SHIPPED (patcher https://paste.rs/UxwrZ): CASY bookkeeping-rewrite
  class CLOSED at the root. (1) NEW shared hydrator `hydrate_trade_from_doc` in
  bot_persistence.py — restore_open_trades / restore_closed_trades / dict_to_trade now
  round-trip EVERY persisted BotTrade dataclass field (created_at, scale_out_config incl.
  m0_legs+targets_hit+partial_exits, close_at_eod, trade_style, trade_type, realized_pnl,
  commissions, bracket telemetry...). Pre-fix the boot restore rebuilt trades from a
  ~17-field subset; everything else reset to dataclass defaults and the next persist
  REWROTE Mongo with wiped values (mechanism behind the 675 created_at="" rows AND M0
  ladder state loss on every restart AND restored swings regaining close_at_eod=True).
  (2) save_trade: replace_one({"_id":id}) → update_one({"id":id},{"$set":...},upsert) —
  kills BOTH the Mongo-only-field drop (repair markers) and the duplicate-row hazard
  (persist_trade keys on "id", save_trade keyed on "_id" → two rows per trade, one going
  stale: the CASY rejected-vs-active two-row signature). v87/v27/v199 fallback overrides
  preserved (run AFTER hydration). 11 new tests (test_v322t_rehydration_preserves_fields
  .py, mongomock-driven through the REAL restore_open_trades); 2 stale tests updated
  (v19.34.21 source guard → hydrator successor; v195 dual-ts lookup _id→id). 91/91
  persistence-suite green in container. Patcher = whole-file replace w/ SHA256 pre-patch
  guards (--check dry-run, --force override, auto-backup). AWAITING: user applies on DGX,
  runs 91-test suite, commits BEFORE restart.
  OPERATOR DECISIONS LOGGED: 15:35-15:45 EOD window stays WARN-ONLY; V5 HUD Integrity
  tile deferred. NEXT: P1 broker-rejection re-fire churn (same signal fired 11x), then
  P1 taxonomy mismatch (style=swing/tf=intraday), IGV INT-21 hardening, v322p decay rework.
- 2026-06-11 v322t DEPLOYED+VERIFIED ON DGX: patcher UxwrZ applied (hash guards green),
  91-suite ran 87 passed + 4 FileNotFoundError failures in test_alert_id_threadthrough
  (pre-existing hardcoded "/app/backend/..." paths — container-only, NOT v322t).
  Follow-up v322t-t1 patcher Mcffz fixed paths to Path(__file__)-relative: 9/9 green
  on DGX. Commits 4d11bd76 (v322t) + 221162ef (t1) pushed. CASY bookkeeping-rewrite
  issue CLOSED end-to-end. Backend restart still pending (changes take effect on next
  boot). NOTE: many other test files still hardcode /app paths (test_chat_extended_*,
  test_collection_mode_*, test_collector_uses_end_date, test_confidence_gate_wiring...)
  — backlog: portable-test-paths sweep.
- 2026-06-11 v322u SHIPPED (patcher https://paste.rs/sKOpP) — pre-open mission-critical
  pair. (1) RE-FIRE CHURN root cause CONFIRMED in code: v19.34.8 cooldown's
  mark_rejection no-ops unless broker error text matches the 18-token structural
  allow-list; unlisted IB wordings (Error 110 tick-size, margin variants, pacing,
  "reason not given") got NO cooldown → identical signal re-fired every tick (the 11×
  churn). Fix: mark_rejection(assume_structural=True) at trade_execution broker-rejected
  branch = DEFAULT-DENY (only explicit transient match bypasses); guardrail/evaluator
  sites keep legacy allow-list. New is_transient_rejection helper. (2) TAXONOMY DRIFT
  root cause: timeframe from STRATEGY_CONFIG[setup_type] vs trade_style from scanner
  SETUP_TO_STYLE — parallel tables drift (style=swing+tf=intraday probe rows).
  Fix both sides: WRITE — reconcile_timeframe_with_style in opportunity_evaluator
  (style wins on conflict, [v322u TAXONOMY] log, legacy styles untouched); READ —
  check_scalp_decay style-aware (catches scalp-style/tf-drifted legacy Mongo rows,
  NEVER decays swing/multi_day/position/investment even if tf=scalp). 12 new tests
  (test_v322u_refire_cooldown_and_taxonomy.py, drives REAL check_scalp_decay w/ stub
  bot + env-pinned gates); 293/293 related suite green in container. Patcher = 5-file
  hash-guarded whole-file replace, sim-verified. AWAITING: user applies, 293 green,
  commit+push BEFORE restart; v322t+v322u both go live at tomorrow's StartTrading boot.
  DEFERRED to next session: IGV INT-21 session-age guard (item 4), repair_dedupe sweep,
  rehydration boot-log one-liner.
- 2026-06-11 (late) v322u DRIFT RESOLVED: bBNI9 aborted on DGX — opportunity_evaluator.py
  hash mismatch. Operator pasted their file (YTjMB, sha f7f2b734): DGX copy LACKS
  v19.34.266 MICRO_SETUPS block + lint formatting/noqa present in sandbox — sandbox-only
  drift; DGX adopted as canonical baseline per AGENTS.md §12 (sandbox evaluator replaced
  with DGX content + v322u edits re-applied). 293/293 re-verified on rebased build.
  Final patcher https://paste.rs/sKOpP (43KB compact anchored-chunk, round-trip verified).
  FLAGGED TO OPERATOR: MICRO_SETUPS (v19.34.266) is NOT live in production — needs a
  decision next session (ship it as its own patcher, or drop it from sandbox).
  LESSON: paste.rs hard-caps ~384KB (jY0IW/Pvqhc were silently truncated) — ALWAYS
  round-trip-verify uploads (download + cmp) before sharing URLs.
- 2026-06-11 (final) v322u DEPLOYED+VERIFIED ON DGX: patcher sKOpP applied clean (5/5
  hash-verified after rebase onto operator's evaluator YTjMB); 288 behavioral green;
  5 failures were test_evaluator_rejection_codes.py hardcoded /app paths → v322u-t1
  patcher DjFy1 fixed (5/5 green). Single commit cb1c356b pushed (user Ctrl-C'd first
  commit; t1 commit captured all 6 files: 4 prod + v322u tests + path fix). Full night
  shipped: v322t (4d11bd76) + t1 (221162ef) + v322u/u-t1 (cb1c356b) — ALL live at next
  StartTrading.bat boot. MORNING WATCH: [v322s MISSED-EOD] silence, [v322u TAXONOMY]
  breadcrumbs, M0 ladder live validation, zero re-fire chains.
  NEXT SESSION DECISIONS: MICRO_SETUPS v19.34.266 sandbox-only (ship or drop), IGV
  INT-21 session-age guard, repair_dedupe_bot_trades sweep, portable-test-paths sweep
  (~25 files w/ hardcoded /app — NEVER include unswept files in recommended suites
  without grepping for '"/app' first), AGENTS.md §2 refresh (compact anchored-chunk
  patcher convention + paste.rs 384KB cap + round-trip verify rule).
- 2026-06-12 ~08:30: v322v shipped (patcher a2o1f, commit bf96951c) — fixed nightly
  2:15AM IB collection auto-resume AttributeError (ib_service.is_connected →
  get_connection_status()["connected"]). Backend restarted 08:29:56 AFTER all patches →
  v322t/u/v ALREADY LIVE pre-open. Fresh log: 0 Tracebacks, 0 missed-EOD carryovers
  (boot sweep silent = correct), 0 open trades restored (flat book — "Restored N" only
  logs when N>0, confirmed in code). PRE-OPEN VERDICT: GREEN. NOTE: paste.rs ALSO 500s
  on ~88KB uploads now — keep patchers compact (anchored-chunk) and always round-trip
  verify.
- 2026-06-12 v322w SHIPPED (patcher https://paste.rs/6Wnyd, 27KB, sim+round-trip
  verified): housekeeping batch. (1) AGENTS.md §2+§11.5 refreshed — anchored-chunk
  hash-guarded patcher convention documented, paste.rs caps + round-trip rule, drift
  protocol. (2) NEW scripts/fix_test_paths_portable.py — sweeps 49 test files /
  150 hardcoded "/app/..." literals to _REPO_ROOT-relative (operator runs --check/
  --apply on DGX; in-container validated: ast-clean, pytest before/after identical
  17F/27P sample). (3) NEW scripts/diag_tqs_metalabel_readiness.py — read-only probe
  gating TQS 0-100 rescale (A-vs-B sample sufficiency) + meta-labeling (closed per
  setup ≥50/100). PROBE RESULTS (squeeze/dedupe, run 13:19Z): duplicates=NONE →
  repair_dedupe RETIRED; squeeze violations all LEGACY, none post-v322u → fix
  confirmed-by-design, keep watching. QUARANTINE LABEL: already done in v322j
  (timeseries_service.py:2161-2186) → RETIRED from backlog. ML freshness retrain:
  SUPERSEDED by 2026-06-10/11 full retrain (162 models) → RETIRED. MICRO_SETUPS:
  recommended DROP (never shipped, no env var, PBO quarantine covers concern;
  resurrectable from git d7c64e97) — awaiting user confirmation.
  NEXT: user applies v322w + runs sweep + probe → probe results gate TQS rescale &
  meta-labeling decisions. Then: Tier 2a calibration (approved, needs design),
  IGV INT-21 guard, v322p decay rework.
- 2026-06-12 v322w DEPLOYED+VERIFIED (commit 5c87284e): AGENTS.md refreshed (rebased on
  DGX copy k63G0, operator's PATCHER RULE section preserved), 49 test files/150 literals
  swept portable, probes committed. COLLECTION QUESTION ANSWERED: NIA collect button does
  NOT pause bot (collection_mode INACTIVE, separate IB client) — safe during RTH.
  PROBE RESULTS (1594 closed, 1395 bot-fired, 1010 TQS-scored):
  * TQS: severe clustering CONFIRMED (p25=55.5/p50=57.8/p75=59.8 — half of all trades in
    a 4.3pt band). Grades have ~NO discriminative power: A n=38 +0.01avgR/39.5%win vs
    B n=38 -0.23/34.2% (NOT statistically significant at n=38, z≈0.5); C+ holds 706 rows
    (70%) and is the WORST bucket (-0.40 avgR); D (n=12) outperforms B and C+.
    VERDICT: cosmetic 0-100 rescale would NOT fix discrimination — fold into Tier 2a as
    outcome-based recalibration (isotonic fit of expected R / win prob on tqs_score,
    rescale to outcome percentile).
  * META-LABELING: READY ≥100: squeeze (490!), accumulation_entry (102). Borderline
    50-99: vwap_fade_long 98, vwap_fade_short 94, gap_fade 80, vwap_bounce 73,
    vwap_continuation 73. v1 can start scoped to squeeze.
  PENDING: MICRO_SETUPS drop/ship decision; choose next build: Tier 2a calibration
  (incl TQS recalib) vs meta-labeling v1 (squeeze).
- 2026-06-12 SANITIZATION PIVOT + v322x: User requested double-check of v322w probe's
  green light → sanitize_v1 probe (9-stage funnel) run on DGX: raw 1594 closed → 257
  clean (16.1%). TQS rescale NO-GO (A=13/B=15, needed ≥30 each); meta-labeling NO-GO
  (accumulation_entry 102→9 — May 19-26 phantom-crisis debris; squeeze 490→82).
  Tier 2a calibration + TQS rescale + v322y meta-labeling PARKED (user-approved),
  data-sufficiency gated — see ROADMAP 2026-06-12 entry. sanitize_v2 (adds canonical
  classify_close hygiene layer, legacy_orphan, emergency_flatten) uploaded CnLiR.
  TQS card-vs-eval audit SOLVED: pre-gate (eval thought, gate input) vs post-gate
  AI-enriched (stamped on trade) — v322x emits 🧮 enrichment-shift thought (PzSgh,
  + test_v322x_tqs_enrichment_thought.py). MICRO_SETUPS applier deleted from sandbox
  (pathspec error on DGX confirmed it never existed there — drift closed).
- 2026-06-12 v324 INFINITE CHART HISTORY (paste.rs/peUbU, md5 a77306d5...): User
  rejected day-toggle concept — wants pure zoom/scroll history streaming. Built
  apply_v324.py: (1) backend GET /api/sentcom/chart-history — cursor-paginated
  (before=unix-sec, next_before resume cursor) older-bar chunks read DIRECTLY from
  ib_historical_data (get_bars staleness fallback would poison prepends with newest
  bars), 220-bar warm-up pad keeps EMA200/BB continuous across seams, per-tf chunk
  caps (1m/5m:1500, 15m/1h:1000, 1d:500); (2) GET /chart/available-timeframes —
  per-symbol bar counts so UI grays out timeframes with <50 bars (tier 2/3 symbols);
  (3) /chart-tail default-days probe aligned to frontend 7/14/30/60/365 lookbacks
  (was recomputing 1-day windows on tail cache-miss); (4) ChartPanel.jsx: daysLoaded
  doubling REMOVED, fetchOlderHistory prepends bars/indicators/markers on
  subscribeVisibleLogicalRangeChange (from<10), hasMoreHistoryRef + historyCursorRef
  + depth-guarded recursion for weekend-only chunks, cyan "Loading older history…"
  pill, timeframe buttons disabled+tooltip when unavailable, auto-hop to coarsest
  available tf. SANDBOX E2E VERIFIED: seeded 40d synthetic SPYTEST — scroll-drag
  walked May 29 → Apr 20 (start of data), pagination terminated has_more=false,
  no overlaps, indicators seam-continuous, 1m grayed for 5m-only symbol, backend
  pytest 7/7. PENDING: user applies on DGX + restart (also activates v323b/v323c —
  live app runs several commits behind; collector is upsert-based so interrupting
  the running historical collection loses nothing).
- 2026-06-12 v325 HSBG — HORIZON-SCALED BRACKET GEOMETRY (paste.rs/SgWMB, md5
  c41035a8...): Root-cause fix for 0/101 PT1 touches. opportunity_evaluator.py:
  (1) canonical DAILY-ATR basis (symbol_adv_cache.atr_pct preferred, plausibility
  window 0.3-20% of px, alert atr only if sane, 2% last resort — stamped in meta);
  (2) calculate_atr_based_stop(+trade_style kwarg): scalp ×HSBG_SCALP_FRAC(0.39=
  √(60/390)), intraday ×HSBG_INTRADAY_FRAC(0.35); swing/position/investment
  UNCHANGED; min stop floors 0.15%/0.35% of entry. CRITICAL: scaling ONLY when
  trade_style kwarg passed — /retune-stop feeds a 5-MIN ATR and omits it (old math
  preserved, regression-tested); (3) detector-stop horizon cap (tighten-only,
  1.5× canonical) for scalp/intraday; (4) v19.34.45 stop-floor threshold ×frac
  (else it would undo the fix); (5) reach gate: envelope=daily_atr×√(hold/390),
  hold: scalp min(60,to-close), intraday to-close, swing 10d/multi_day 5d/
  position 30d/investment 90d (×390min). pt1_env_ratio stamped in entry_context
  .multipliers.hsbg; warn-thought >0.85; HARD BLOCK >1.5 (reason_code=
  hsbg_pt_unreachable, user approved). Style resolution via trade_style_classifier
  .resolve_trade_style (trade_2_hold/unknown→intraday, scalp setups via
  _SCALP_SETUPS). Env: HSBG_ENABLED kill switch + 8 tunables. TESTED: 20 new unit
  tests + 24 pre-existing stop regression tests pass (retune + stop-floor suites).
- 2026-06-12 v325b BRACKET GEOMETRY OVERLAY (paste.rs/sQEqc, md5 ef4ba7e6...):
  ChartBracketGeometryOverlay in ChartPanel.jsx (PremarketShading pattern): red/
  green R/R zones entry→SL/PT1 anchored at entry bar→deadline; dotted cyan √time
  reach cone; "PTn · x.xx× reach" badges (green≤0.85/amber≤1.5/red — same
  thresholds as backend gate); dashed pink decay/EOD clock line + label. Renders
  only when position exists for focused symbol. New GET /api/sentcom/chart/
  reach-meta (atr_pct from symbol_adv_cache, fallback ATR14 from stored daily
  bars — curl-verified 0.0299 on synthetic 3% ATR symbol). Frontend compiles,
  no error boundaries, overlay dormant without position (screenshot-verified).
  PENDING: user applies v325 + v325b on DGX, commit, restart.
  NOTE: SmartStopService unification (merge its rules table with evaluator's,
  wire structure-snapping into entry path) deferred to v326 by design.
- 2026-06-12 v326 UNIFIED STOP-RULE SSOT + REAL-ATR AUDITS (paste.rs/tM454, md5
  7844fa6c...): (1) smart_stop_service._get_setup_rules now overrides initial_stop_
  atr_mult from evaluator SETUP_MULTIPLIERS on BOTH archetype(BRACKET_V2) + legacy
  paths via _with_unified_mult (dataclasses.replace, singletons never mutated;
  divergences fixed: mean_reversion 2.5→1.0, momentum 1.0→1.5; kill switch
  UNIFIED_STOP_RULES_ENABLED=0). Archetype tables keep owning trailing/BE/scale-out/
  runner shape. (2) calculate_intelligent_stop(+trade_style kwarg): v325 HSBG
  horizon parity — scalp/intraday rules scaled ×frac, legacy 2% min_stop_pct swapped
  for HSBG floors, anti-hunt buffer ×frac; triggers scale automatically (derive from
  initial mult). Omitting trade_style = old behavior (smart_stops router API
  unaffected). (3) NEW module helper resolve_daily_atr(db,symbol,ref_price) —
  canonical daily basis (adv_cache pref, 0.3-20% plausibility, 2% last resort).
  (4) trading_bot /audit-stops + /fix-stop: fake atr=entry*0.02 ERADICATED →
  resolve_daily_atr + trade_style passthrough; too-tight check now = HALF canonical
  v325 stop distance (was flat 0.75×daily-ATR which would flag every v325 scalp as
  critical); suboptimal slack ×frac. TESTED: 15 new tests + 20 v325 + 24 legacy
  regression all pass; backend boots; /audit-stops responds. GOTCHA found in
  testing: entry at exact $100 correctly triggers anti-hunt round-number buffer
  (+0.5×ATR×frac) — tests use non-round entries. PENDING: user applies on DGX
  (REQUIRES v325 applied first — patcher pre-flight checks for HSBG helpers).
- 2026-06-12 v328 DAILY-BAR LEAK REAL FIX + RTH BACKFILL GATE (patcher
  paste.rs/c3Rb9 md5 d59ca0941700643c5eb95c7ac0c7c7f6; probe diag_history_500
  paste.rs/tiE4b md5 14662f3a5561a29b07678de81c557b82): probe output proved
  v323b guard was bypassed — the IB Data Pusher uploads via router endpoints
  (/api/ib/historical-data/result + /batch-result in routers/ib.py AND
  ib_modules/historical_data.py) which bulk-write into ib_historical_data with
  NO guard; slow_learning alpaca writer also unguarded. v328 adds
  _is_inprogress_daily_bar guard to all 5 sites (TESTED live: today's daily bar
  blocked on both single+batch endpoints, historical bars stored). FIX 2: RTH
  deep-backfill gate in historical_data_queue_service.get_pending_requests —
  Mon-Fri 09:25-16:05 ET deep requests (non-empty end_date chains, >=2-month/
  year durations) held pending, auto-resume post-close; turbo "1 D".."1 M"
  unaffected (TESTED: gate on/off + HIST_BACKFILL_RTH_GATE=0 kill switch).
  Root-causes the "snapshot unavailable" blackout (IB 60req/10min pacing
  starvation). FIX 3: one-shot purge of provably-partial daily bars (last 10d,
  collected_at < own 16:15 ET close) — removes today's 40 leaked rows (TESTED:
  partial purged, final + no-collected_at kept). CHART WALL: NOT a parse bug —
  /chart-history throws HTTP 500 on DGX (works locally with identical mixed-
  format data; probe A3 proved formats parse fine). diag_history_500 probe
  replays endpoint in-process on DGX to capture the real traceback +
  serializability check + bar value-type strata. PENDING: user runs patcher,
  commits, restarts, runs probe, pastes output → v329 chart-wall fix.
  STILL OPEN: 14 legacy pre-v325 PT positions (user decision a/b/c pending),
  Atlas password rotation reminder, IGV INT-21 hardening, ELF→XLE mapping.
- 2026-06-12 v329 CHART WALL ROOT CAUSE + FIX (patcher paste.rs/jLt7o md5
  564a678b14608cca869c79ca422bcd2a): diag_history_500 on DGX captured the
  traceback — NameError: _sanitize_intraday_bars not defined at sentcom_chart
  line 1213. v324's /chart-history chunk was authored against the dev file
  which has the v19.34.265 bad-tick sanitizer; that helper was NEVER applied
  on DGX → every /chart-history call = HTTP 500 → frontend prepend dies →
  charts wall at initial window. v329 inserts the byte-identical sanitizer def
  before /chart-history (REQUIRED) + best-effort /chart parity clamp
  (OPTIONAL, graceful skip on drift). Patcher SELF-TESTS in-process: walks 8
  pages of ADBE 5-min via the patched module against live Mongo before user
  restarts. TESTED here on a degraded mirror replicating the DGX state:
  def inserted, parity inserted, self-test walks history, idempotent re-run
  all-SKIP. LESSON: v324 assumed dev-only helpers existed on DGX — future
  patchers must anchor-check every helper they call. PENDING: user runs v329,
  commits, restarts; then verify chart scrolls to Mar 2024.
- 2026-06-12 v330 INT-21 HARDENING + SECTOR WORDSTART + THOUGHT TTL TIERS
  (patcher paste.rs/NIPtw md5 bc5e3146588d03df9412c781f8e3e782): (1) _check_
  range_break gains 4 guards: >=60min RTH session age, HOD-LOD >= 0.6xATR,
  RVOL sanity band 0.2-50 (0=poisoned prior-day daily), snapshot <=5min fresh.
  (2) _industry_to_etf word-START matching (\b+key regex) — fixes ELF→XLE
  ("oil" inside "tOILetries") AND bonus bug "Aerospace & Defense"→None
  ("spac" inside "aeroSPACe" hit blocklist); stems still work (rail→railroads,
  gas→gasoline, utilit→utilities); + cosmetic/toiletries/beauty→XLP keys; DB
  repair ELF XLE→XLP in symbol_adv_cache. (3) kind="thought" rows matching
  _NOISE_CONTENT_RE (skipped/passing/no setup/snapshot unavailable/...) join
  7d expires_at tier; signal thoughts keep 190d; DB retro-tag of existing
  generic rows (255 tagged in dev DB). Ships tests/test_v330_hardening.py
  (9 tests); patcher SELF-TESTS via pytest (33 passed incl. sector + v323c
  regression). All TESTED on mirror: byte-identical, idempotent, retro-tag
  noise/signal split verified, ELF repair verified, backend boots.
  PENDING: user applies v330, commits, restarts. NEXT: watch 2026-06-15 open
  (scalps fire? snapshots GREEN? M0 OCA ladder on fill?); Data Health HUD
  pill offered; Atlas password rotation still outstanding.
- 2026-06-12 v331 MANUAL UNIVERSE PIN + SPCX (patcher paste.rs/FtUcg md5
  185b3090512ed2d59deb7c52d6ab87be): ANSWER to operator — IPOs are NOT
  auto-added: universe = symbol_adv_cache ADV>=$50M rebuilt from stored daily
  bars; day-one IPO has no bars→no ADV row→invisible, AND collection only
  targets cached symbols (chicken-and-egg). v331 adds manual_universe_pin:
  always in get_universe/get_universe_ranked (any tier), Layer-0 unqualifiable
  immunity, auto-flows to pusher L1 priority, pin_symbol()/unpin_symbol()
  helpers; nightly ADV rebuild $set-only so pin survives. DB phase pins SPCX
  + queues 5 short backfill requests (1d/1h/15m/5m/1m — not held by RTH gate).
  TESTED: 5 functional pin tests + 6 source tests, mirror byte-identical,
  idempotent, dev DB cleaned after test.
- 2026-06-12 OPERATOR Q&A LOGGED: (1) INT-21 v330 guards scope = ONLY
  _check_range_break intraday HOD/LOD detector; ORB/_check_breakout(S/R)/
  hod_breakout/squeeze/multi-month investment range logic untouched.
  (2) Friday backfill: no cancel needed — v328 gate holds deep reqs 09:25-
  16:05 ET, free-runs all weekend. (3) Regime-flip position policy advised:
  no immediate flatten; block new old-regime entries instantly, demote (BE/
  tighten) thesis-dependent positions only after flip persists 15-30min;
  scalps ride HSBG brackets. Implementation offered, not yet requested.
NEW INVESTIGATIONS (P1, operator-requested 2026-06-12):
  - EOD close sequence flattens EVERYTHING regardless of trade style/horizon
    (swing/investment positions should survive overnight). Investigate
    trading_bot EOD flatten path; then EOD flatten modal UX.
  - IB pusher goes DEAD ~15:45-15:50 ET EVERY session — overload? safety
    guard? MOC churn? Investigate pusher logs/heartbeats around that window.
  - Regime-flip position demotion policy (see Q&A above) — design + implement
    if operator confirms.
  - Morning-report probe → integrate into briefings modal infrastructure
    (scores the open: scalp count, snapshot uptime, gate activity, ladder
    fills — pass/fail on the week's fixes).
- 2026-06-12 v332 REGIME DEMOTION + EOD STYLE FIX + EOD/PUSHER PROBE (patcher
  paste.rs/g8lhz md5 1901e3a9ca5d21d11e3ee4906220d205):
  (1) EOD "closes everything" ROOT CAUSE: _eod_naked_flatten_guard (v301/302,
  15:45-16:00) still read raw close_at_eod ATTRIBUTE (blanket default-True)
  instead of should_close_at_eod policy — swing holds force-flattened at 15:56.
  Fixed to policy resolution like the v245 main pass; v302 test fakes updated
  to style-based contract.
  (2) NEW services/regime_demotion_service.py (operator-approved): adverse
  regime flip persisting REGIME_DEMOTION_CONFIRM_MIN (20min) demotes
  conflicting intraday/swing positions — stop→BE if >=0.25R else software-stop
  ratchet halfway to entry; NEVER IB order surgery (orphan-safe per operator's
  explicit concern); whipsaw revert cancels pending; scalps/long-horizon
  exempt. ALSO un-froze bot._current_regime (sizing multiplier was stuck at
  RISK_ON forever — _update_market_regime never called). Hooked into manage
  loop after _check_scalp_decay with 5s wall. Env: REGIME_DEMOTION_ENABLED/
  CONFIRM_MIN/BE_R. 12 tests in test_v332_regime_demotion.py.
  (3) scripts/diag_eod_pusher.py (read-only evidence probe): close reason x
  style audit 15:30-16:10 ET, per-minute pusher ingest timeline (DEAD-from
  detection), state_integrity_events, EOD heartbeats, queue gaps. 15:45
  "pusher death" window exactly coincides with RegT machinery (15:45 hard
  entry cut = the "safety guard" the operator suspected + EOD close pass at
  15:45 since v19.34.154 + naked-guard ib_direct polling). VERDICT PENDING:
  operator runs probe + watch_pusher_eod.py Monday.
  TESTED: 35 pytest pass (v332+v301+v302), mirror byte-identical, idempotent,
  backend boots. NOTE: ~36 PRE-EXISTING stale test failures in older eod test
  files (e.g. test_default_eod_close_minute_is_55 expects pre-v154 value,
  test_eod_generation needs running services) — not v332 regressions; cleanup
  candidate for a future maintenance pass.
  PENDING USER: apply v332, commit, restart. SPCX pinned+queued (v331 done).
- 2026-06-12 v333 SYSTEM INTEGRITY BRIEFING + AUDITABLE FEED (patcher
  paste.rs/EFeBv md5 c202e330524d5f98bb81d0374bdc6413), operator-approved:
  BACKEND new routers/integrity_router.py (registered in server.py after
  sentcom_chart include): GET /api/integrity/morning-report = live PASS/WARN/
  FAIL scorecard with 8 checks (scalps_fired, data_uptime %RTH-minutes,
  ingest_freshness, daily_bar_leak v328, backfill_gate v328+deep-held count,
  m0_ladder trades+legs filled, regime+demotions v332, integrity_events by
  severity); GET /api/integrity/feed = state_integrity_events merged with
  per-trade regime-demotion stop moves (old→new stop @ price from bot_trades.
  trailing_stop_config.stop_adjustments). FRONTEND: 5th "Integrity" shield
  button in BriefingsCompactStrip (no time window, static style, never
  pulses) → deep-dive modal briefingKey="integrity" renders IntegrityBody
  (checklist+feed) atop standard sections; IntegrityCardV5 also in BriefingsV5
  panel; shared useIntegrityReport hook (60s poll). VERIFIED via screenshot:
  modal renders scorecard + demotion feed with before/after stops. 7 tests
  in test_v333_integrity.py; mirror byte-identical (13 items), idempotent.
  PENDING USER: apply v333, commit, restart backend.
- 2026-06-12 v334 EOD POLICY FIX — FAILED SHIP (lesson): patcher generated
  with EMPTY CHUNKS (only test file shipped). User ran it, self-test failed,
  user committed failing test anyway. Root cause of bug itself: generic SMB
  fallback style `trade_2_hold` short-circuited get_policy_for_trade to
  DEFAULT_POLICY (intraday, close_at_eod=True) → 63 long-horizon positions
  flattened at 15:45 ET in 14 days, order storm starved IB pusher.
- 2026-06-13 v334b RE-SHIP WITH REAL PAYLOAD (patcher paste.rs/1GWyG):
  CHUNK for backend/services/order_policy_registry.py — unknown/generic
  styles now resolve via trade_style_classifier.resolve_trade_style (setup
  horizon wins): daily_breakout→multi_day, stage_2_breakout→position,
  rs_leader_break→investment, trend_continuation_short→multi_day all HOLD;
  squeeze/orb/no-setup → intraday close. Explicit canonical styles untouched.
  Patcher hardening: refuses to run if CHUNKS empty (exit 9), prechecks
  resolve_trade_style exists (exit 8), prints live resolution preview before
  pytest gate. VALIDATED on simulated pre-v334 repo: 45 pytest pass
  (v334+v301+v302+v332), patched file byte-identical to known-good local,
  idempotent re-run, paste.rs download round-trip diff-verified.
  Generator kept at /tmp/gen_v334b.py pattern: ALWAYS extract CHUNKS from
  the local passing file programmatically — never hand-assemble payloads.
  PENDING USER: apply v334b, commit, restart backend; then evaluate
  watch_pusher_eod.py output through 15:40-16:05 ET (Issue 2).
- 2026-06-13 v334b CONFIRMED LIVE: 06-12 close held all multi_day book at
  15:45 (intraday-only batch), pusher ingest GREEN full session (216k bars
  vs 13-28k prior), only 45s stall at 15:47 then recovered. Issue 2
  (pusher starvation) effectively resolved.
- 2026-06-13 v335 (patcher paste.rs/rQXvb): T-2 force-MKT escalation
  (_eod_t_minus_2_escalate) flattened ORCL/SMCI multi_day at 15:47 via the
  STALE per-trade close_at_eod attr — same bug class at 4 sites, all now
  routed through should_close_at_eod(): T-2 escalate, T-1 alert,
  EOD status endpoint counts, morning readiness stuck-classifier (would
  have RED-flagged CPB/PENN/DKNG holds next morning). 7 new tests in
  test_v335_eod_policy_consumers.py; 52 pass total w/ v334/v301/v302/v332.
  Sim-validated pre-v335, idempotent, byte-identical, round-trip verified.
  PENDING USER: apply v335, commit, restart backend.
- KNOWN/DEFERRED (user chose A-only): Bug B ib_boot_probe latches RED
  forever after mid-session restart (30s grace lost vs deferred IB
  connect; caused overall=red + "1 CRITICAL" all session 06-12). Proposed
  fix ready: background re-probe after FAIL → auto-clear health green,
  kill-switch latch stays manual; IB_BOOT_PROBE_GRACE_S env. NOT shipped.
  Also: historical_queue yellow (3,363 pending) ↔ "no intraday bars"
  thoughts 15:09-15:30 — monitor.
- 2026-06-13 v336 (patcher paste.rs/JPAgD): ib_boot_probe auto-recovery —
  after boot-grace FAIL the probe re-checks every 30s in background
  (_recovery_reprobe) and self-clears health to green ("recovered: ...");
  KILL-SWITCH latch untouched (manual reset preserved); grace env-tunable
  IB_BOOT_PROBE_GRACE_S (server.py). _STATE gains recovered_at. 4 new
  tests in test_v336_boot_probe_recovery.py (incl. assert no auto-reset
  of kill-switch); 59 pass total w/ v308+v335+v334+v301+v302+v332.
  Sim-validated on v335-applied repo (matches user deploy order),
  idempotent, byte-identical, round-trip verified.
  PENDING USER: apply v335 (paste.rs/rQXvb) then v336 (paste.rs/JPAgD),
  commit, restart backend, check kill-switch state after restart.

---
## 2026-06-18 — Setup-EV cheat-sheet adjudication COMPLETE (v353→v363, all DEPLOYED on DGX)
Replay→Validate→(cheat-sheet)→Rewrite/Tighten/Suppress, all via SHA-guarded paste.rs patchers + pytest:
- v357 fashionably_late SUPPRESS · v358 daily_squeeze LONG-only · v359 squeeze SUPPRESS
- v360 first_move_up/down SUPPRESS (negative-EV morning fades)
- v361 big_dog TIGHTEN (min-price $10 + min-stop 1%; breakeven -> +0.097R n=268)
- v361b big_dog/puppy_dog DOCTRINE RE-AUDIT (both loose proxies; v361 kept live; P1 doctrine rewrite queued)
- v362 gap_give_go DOCTRINE REWRITE (1-min give->consolidation->range-break, cons-low stop, 2R; +0.233R n=492)
- v363 spencer_scalp DOCTRINE REWRITE (LONG-only; 20-min tight range <15% dayRange upper-1/3, vol-surge break, range-low stop, 2R; +0.04-0.06R; short dropped, all-day)
Live whole-file SHA after v363: 0d9b24b150296d2bf252da31b2c3da9fe44bce47439d2ef2f958a1781327482a

### Remaining / backlog (P1/P2)
- P0: rotate Atlas MongoDB password (old creds in git history) — BLOCKED on operator.
- P1: scaled measured-move exits (spencer 1R/2R/3R; gap_give_go Move2Move double-bar-break trail) — position-mgmt layer.
- P1: big_dog/puppy_dog doctrine rewrite (mid-day 11:00-13:30 window + above-PDH + consolidation-base stop + trail).
- P1: P-WIRE Phase 2 eval; multi-bar-size shadow logging; live-detector monitoring (diag_live_setup_fires.py).
- P2: GET /api/scanner/setup-ev-audit endpoint + V5 tile (visualize v353-v363 verdicts); oca-finalize-health tile; server.py monolith breakup.


## 2026-06-22 — A7 status update (P0 scanner-liveness RESOLVED)
- P0 DEAD SCANNER: ROOT-CAUSED + fixed. enhanced_scanner.start() awaited the
  blocking carry-forward hydrate before _running=True/_scan_task spawn; the 5s
  asyncio.wait_for() boot budget cancelled start() mid-hydrate -> loop never
  launched (running=False, scan_count=0, 19 stale hydrated alerts).
- LIVE FIX CONFIRMED by operator: POST /api/live-scanner/start -> running=True,
  scan_count climbing (0->2 in 60s), last_scan fresh, symbols_scanned_last=422.
- DURABLE FIX delivered: patch_a7 (paste.rs/wQ5jm) reorders start() + softens the
  DMA directional filter (2% buffer / EMA50>SMA200 structure / pullback-setup
  exemption; DMA_LONG_BUFFER_PCT env). 14/14 local checks pass. Pending operator
  apply + backend restart for durability + DMA activation.
- NOTE: /api/scanner/status reflects the IDLE predictive_scanner (red herring);
  the REAL enhanced scanner state is /api/live-scanner/status.
- OPEN OFFER: optional scan-loop watchdog (auto-restart if _running flips False
  during RTH) for self-healing.
- Carried P1/P2 backlog unchanged: adrp_20d warm-fill, TQS<->Confidence gate
  unify, trend_continuation conversion gap, regime-fit abstention L5, thesis-
  invalidation exits L7, server.py monolith breakup, Atlas password rotation.

## 2026-06-22 — A8 + open follow-ups (post-scanner-resurrection)
- A8 SHIPPED (patch_a8, paste.rs/hsKB7): auto-exec RESTART/FEED GUARD in
  _auto_execute_alert (single chokepoint for intraday ~4212 + A6 daily ~7421).
  Warm-up holds auto-exec first AUTO_EXEC_WARMUP_SCANS cycles after (re)start +
  requires is_pusher_connected(). Fixes the 2026-06-22 flush-on-restart where
  ~14 stage_2_breakout backlog alerts (created 14:00-14:30Z) fired in one
  17:54-18:03Z burst on the A6 restart. test 8/8. Rejected age-gate (created_at
  pinned via dedup/upsert = unreliable). Pending operator apply+restart+commit.
- diag_a9_entry_provenance.py (paste.rs/U3k64) + diag_a8_position_freshness.py
  (paste.rs/7mfpN) created — read-only position audits.
- OPEN FOLLOW-UPS (operator: "investigate all"):
  P1  target_price plumbing alert->bot_trade (ALL 25 open positions have stops
      but NO target; R:R unmeasurable) + live-mark for position-tier holds
      (16 names entry==mark, UPL 0, not in live-sub set) -> unblocks L7
      thesis-invalidation exits.
  P1/P2  per-style position cap (16/25 were stage_2_breakout = concentration).
  P1  CARD TRANSPARENCY (operator UI ask): show Time of Alert (created_at),
      Time of Refreshed alert (last_updated), Time of Entry (executed_at),
      Time of Exit (closed_at), and Entry Price clearly on BOTH scanner cards
      and open-position cards (frontend patcher).
  watch: DXCM -5.5% (weakest open hold, still above stop).
- Also still open from prior: A6 fresh-quote gate now subsumed by A8; scan-loop
  watchdog (offered, not built); TQS<->Confidence gate unify; adrp_20d warm-fill.
--- 2026-06-24 — P4' LIVE EDGE VETO WIRED (env-flagged, fail-open) ---
DONE: Conditional Entry Edge Score gates live in opportunity_evaluator (skip
  bottom 30%, ENTRY_EDGE_VETO_ENABLED, fail-open) via services/entry_edge_gate.py
  + nightly 5:45pm ET refit. Observe-stamps entry_context.entry_edge always.
  Status/refresh endpoints added. Synthetic gate test passes; report regression OK.
NEXT (P0): Operator arm on DGX (ENTRY_EDGE_VETO_ENABLED=true), watch
  rejection_daily_counts["edge_score_veto"] vs realized book. Then Seal #2
  (order_no_trade tracking gap, -$920) + backside time-decay exit (P2).

--- 2026-06-24 — PROMOTE shadow-first (Edge Score → GO + sizing) ---
DONE: ENTRY_EDGE_PROMOTE_MODE (off|shadow|active). compute_decision() = GO on
  confidence-discounted conservative edge + size_mult (grade×confidence, 0.5–1.25).
  Shadow logs/stamps only; active stands-down non-GO + rescales shares. Backtest
  report /entry-edge-promote/report. Locally tested; NOT yet run/validated on DGX.
NEXT: Save→pull→restart on DGX. Run diag_edge_gate.py (promote backtest): confirm
  STAND-DOWN avg_R << 0 and sizing lift > 0. Then set ENTRY_EDGE_PROMOTE_MODE=shadow
  for a few sessions, then =active. Seal #2 active fix (bypass-path pre-write +
  fill-confirm reconciler) still pending (−$2,759 live leak).
