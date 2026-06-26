# 👁️ WATCHLIST — Pending Evaluation / Flags To Decide / Data Accruing
**Purpose:** single source of truth for everything that is *flagged, shadow/observe-mode, or
waiting on data* and therefore needs a **deliberate check → promote / tune / kill** decision.
Nothing here should silently rot. When an item is decided, MOVE it to CHANGELOG.md and delete
its row here.

**Last reviewed:** 2026-06-26
**How to use:** each row has → *what · current state · exact check · decision rule · when*.
Endpoints assume `http://localhost:8001` on the DGX. Flag rollback is always "unset env line in
`backend/.env` + `./start_backend.sh --force`".

---

## 🔴 A. ACTIVE A/B THIS WEEK — flags just turned ON, watch then promote/rollback

### A1. `TAPE_CONFIRM_DEFERRED=true` + `TAPE_CONFIRM_MODE=router`  ← ARMED 2026-06-26 · verdict STILL PENDING
- **What:** deferred tape-confirmation (JIT L2) — tape is now the LAST gate; neutral-no-L2
  scalp/intraday alerts are held `tape_pending` and confirmed on real depth instead of being
  rejected. Fixes the 97% intraday tape rejection (06-25: 656→17→2→0).
- **⚠️ 2026-06-26 — could NOT decide: the `stats` counters + `recent_verdicts` were IN-MEMORY only
  and the day's TWO backend restarts (loser-cleanup deploy) wiped the morning sample. `expired`
  verdicts were never persisted, so there was no durable full-day record.**
- **✅ FIXED (2026-06-26, pending DGX deploy):** each resolved verdict (confirm/adverse/expired)
  now persists to the `tape_confirm_verdicts` collection (`_resolve_tape_pending` in
  `enhanced_scanner.py`), and a restart-proof read-only endpoint reads the full day:
  `GET /api/scanner/tape-confirm/history?days=1` → counts by verdict, source split, `confirm_rate`,
  and a `read` heuristic (PROMOTE/TUNE/ROLLBACK-leaning per the rule below).
- **Check (NEXT clean session, after the deploy):**
  - `curl -s localhost:8001/api/scanner/tape-confirm/history?days=1 | python3 -m json.tool`  ← restart-proof, use this
  - `curl -s localhost:8001/api/scanner/tape-confirm/status | python3 -m json.tool`  ← live since-boot
  - `curl -s localhost:8001/api/diagnostic/trade-funnel | python3 -m json.tool`
- **Decision rule (after ONE clean RTH session, NO restart):**
  - PROMOTE (flip default ON in code, delete the flag) if: `confirm > 0`, `adverse` is catching bad
    flow, `expired` is NOT dominating, funnel tape-confirmed climbs off ~17, auto-exec-eligible > 0,
    and NO adverse-flow burst at the open.
  - TUNE if `expired` dominates → L2 not reaching candidates fast enough → raise
    `TAPE_CONFIRM_PENDING_TTL_S` or switch `TAPE_CONFIRM_MODE=jit`.
  - ROLLBACK instantly if adverse-flow burst at open (unset the two env lines).
- **When:** next clean RTH session (flags ON, NO mid-day restart) → read `/tape-confirm/history` near
  close → ping main agent to do the promotion.
- **Related dormant knob:** `TAPE_NONADVERSE_GATE` (default OFF) — alternative "block only
  adverse L1+momentum, no L2 wait" mode; only consider after router mode proves out.

### A2. `TAPE_CONFIRM_SCALP_INTRADAY_ONLY=true`  ← ON (set prior session)
- **What:** swing/position/multi_day/investment bypass tape entirely (chart holds, not
  order-flow entries); only scalp/intraday require it.
- **Check:** funnel — longer-horizon auto-exec-eligible should rise; tape no longer the choke
  for swing/position. `tape-confirm/status.nonadverse_gate`/scope behave as expected.
- **Decision:** PROMOTE to default if longer-horizon entries increase without quality drop.
- **When:** same session as A1.

### A3. `PER_STYLE_AUTOEXEC_FLOORS=true`  ← ON (set prior session)
- **What:** per-style EV-R auto-exec floors (scalp 0.15 / intraday 0.12 / multi_day 0.05 /
  swing 0.05 / position 0.03 / investment 0.03) instead of the single 0.10 scalar.
- **Check:** `setup-ev` + funnel — scalps need higher proven EV; swing/position pass on lower.
- **Decision:** PROMOTE if it tightens scalps without starving proven swing/position setups.
- **When:** same session as A1.

---

## 🟠 B. DORMANT FLAGS — built, default no-op, awaiting data to flip ON (or kill)

### B1. Entry Edge Score gate — `ENTRY_EDGE_VETO_ENABLED` (off) / `ENTRY_EDGE_PROMOTE_MODE` (off) / `ENTRY_EDGE_SIZE_ENABLED` (off)
- **What:** the ACTIVE-PROGRAM replacement scorer. Veto/abstention gate (skip bottom-decile
  edge) is the proven lever; size mult proved ~0 lift (keep OFF).
- **Check:** `curl -s "localhost:8001/api/slow-learning/entry-edge-score/report?days=120&target=win&clip=3&model=conditional"`
  — compare conditional vs `model=marginal`; read the `abstention_curve` (bleed saved per veto cutoff).
- **⛔ 2026-06-26 RAN ON DGX (target=mfe_r, n=887, 5-fold) → PROMOTE RULE NOT MET. DO NOT WIRE THE VETO.**
  Both models predict MFE weakly (+0.08/+0.11 spearman) but are INVERSE to realized R
  (marginal −0.108, conditional −0.054). The abstention curve does NOT reduce realized bleed —
  conditional skip-bottom-30% makes avg realized R WORSE (−0.149→−0.175) and stays negative
  everywhere; marginal only "improves" by trading fewer trades (still −0.076 after skipping 50%).
  Per the rule below, the veto is NOT ready. The ONLY durable signals are `time_window`
  (morning ≫ afternoon/power-hour) and `setup_type` — NOT the per-trade score.
- **Decision:** if conditional beats marginal OOS materially AND abstention curve shows real
  bleed reduction → wire the live SHADOW abstention arm first, then promote veto. Status:
  `GET /api/slow-learning/entry-edge/recent`. (As of 2026-06-26: condition FAILED — held.)
- **When:** revisit only after (1) Phase-0 coverage (D1) fills `sector_regime`/`rs_rating` on new
  entries, AND (2) the entry-feature-discovery work finds a feature that tracks REALIZED R
  out-of-sample (current features only weakly track MFE). Until then the veto is dormant by design.

### B2. TQS scheme-B renorm — `TQS_RENORM_PRESENT` (off / dormant)
- **What:** recompute pillars over PRESENT sub-scores only (drop "No data", renormalize),
  de-compresses grades upward → MORE trades cross auto-exec floors.
- **Decision:** DO NOT flip on yet (edge thin + some inputs inverse-signed). Revisit only as
  part of the Entry Edge Score program; likely SUPERSEDED by it. Candidate to DELETE if Edge
  Score promotes.
- **When:** tied to Entry Edge Score outcome (B1).

### B3. TQS setup-subscore shrink — `TQS_SETUP_PATTERN_SHRINK` / `TQS_SETUP_WR_SHRINK` (both 1.0 = no-op)
- **What:** A/B dials to shrink the anti-predictive static SMB pattern rank + degenerate
  historical win_rate toward neutral (s→50+(s-50)*k).
- **Check:** set one to 0.5 or 0.0, restart, observe grade separation vs realized R.
- **Decision:** likely SUPERSEDED by Entry Edge Score. Only A/B if TQS stays the gate basis.

### B4. Thesis-invalidation exits — `THESIS_INVALIDATION_MODE=observe` (dormant)
- **What:** close/trim a position when its *reason* dies (hard_regime_flip / regime_hostile_cell).
  Phase-2 ACTIVE close + P5 partial-trim are built but gated to observe.
- **Check:** `curl -s "localhost:8001/api/slow-learning/thesis-invalidation/report?days=30"`
  — `avg_r_delta` per trigger (exit-at-signal R vs held R; >0 = exiting beat holding).
- **Decision:** flip `THESIS_INVALIDATION_MODE=active` (starts with `hard_regime_flip` only via
  `THESIS_INVALIDATION_ACT_TRIGGERS`) if avg_r_delta is solidly +.
- **When:** after enough closed trades accrue signals on DGX.

### B5. Strategy autonomy — `STRATEGY_AUTONOMY_MODE=observe` (read-model only)
- **What:** per-strategy DISABLE/WATCH/ENABLE recommendations by current regime band.
- **Check:** `curl -s localhost:8001/api/slow-learning/strategy-autonomy/report`
- **Decision:** wire active enforcement (feed recs into DISABLED_SETUPS gate) only after a
  probation window shows the recs are right.
- **When:** after expectancy table cells fill on DGX.

### B6. Shadow-arm authority A/B — `SHADOW_ARMS_ENABLED=true` (recording, not directing)
- **What:** champion (live dual-gate) vs `unified_1a2a` vs `gate_off` vs `regime_fit` arms,
  scored in `shadow_signals` (raw + size-weighted R) — never touches IB.
- **Check:** `curl -s "localhost:8001/api/slow-learning/shadow/arm-report?days=14"`
- **Decision:** if `unified_1a2a` weighted-R beats champion → promote it to the live verdict
  authority (collapses the TQS↔gate double-discount). If `regime_fit` shows more SKIPs in
  hostile bands with better R → promote (flip T6 to active + adopt unified).
- **When:** after arms accrue over RTH sessions.

### B7. Orphan→bracket relink — `RECONCILE_RELINK_BRACKET_SOURCE` (locked = fix, insurance)
- **What:** v414 heal — relink FILLED orphan entries to their real order_queue bracket.
- **Check:** orphan-fill-heal report → `post_fix_orphan_date_histogram`; `state_integrity_events`.
- **Decision:** keep =fix permanently; ESCALATE (hunt the pre-write root) ONLY if the histogram
  shows fresh recurrence (was DORMANT, last burst 2026-05, 0 in ~3 weeks).
- **When:** spot-check monthly / on any orphan-bleed report.

---

## 🟡 C. DATA-ACCUMULATION — no flag, just needs a report read after data accrues

### C1. Entry Edge Score Phase-0 coverage  ← BLOCKER for B1
- **What:** verify `sector_regime` / `rs_rating` / `symbol_rs_regime` / `trigger_price` are now
  STAMPING on new entries (was 0% pre-build because old trades had no Phase-0 keys).
- **Check:** `curl -s "localhost:8001/api/slow-learning/entry-edge-coverage/report?days=45"`
  → per-field coverage % + `archetype_cell.complete_pct`.
- **Decision:** if sector_regime/rs_rating still dark on POST-build trades → add a sync fallback
  in `opportunity_evaluator.build_entry_context`. Else proceed to B1.
- **When:** after 1–2 RTH sessions of fresh entries.

### C2. Per-archetype GRADE triple (1C) on real data
- **Check:** `entry-edge/recent` + gate `status().grade_cohorts` (DGX showed 44).
- **Decision:** confirm grade ranks realized-R within kind cohorts before any sizing use.

### C3. Data-Integrity Scorecard (monitor)
- **Check:** `curl -s "localhost:8001/api/integrity/data-scorecard?days_edge=45&days_tqs=30"`
- **Decision:** chase any pillar that flips to FAIL (TQS feed darkness, Phase-0 darkest field).

### C4. Swing-bleed setup hunt (EV problem, worst horizon −0.215R)
- **Check:** `curl -s "localhost:8001/api/slow-learning/setup-ev/report?horizon=swing&days=30"`
- **Decision:** suppress/tighten the specific leaking setup_type(s) (v353–v363 playbook).

---

## 🟢 D. SCHEDULED / TIME-GATED RE-CHECKS (do not action early)

### D1. ⏰ 2026-07-08 — TQS scalp-inversion re-audit (held for v401 data)
- **Check:** `curl -s "localhost:8001/api/slow-learning/tqs-integrity/report?days=30"` (+ grade_by_horizon).
- **Act ONLY IF:** score still ok_spread AND scalp grade still inverted at larger n AND a scalp
  pillar shows |corr|>~2/√n with hi_R<lo_R → bump execution weight on scalp/intraday (STYLE_WEIGHTS).
  Do NOT reweight on noise. (Detail: ROADMAP "SCHEDULED RE-CHECKS".)

### D2. ⏰ daily_breakout SUPPRESSED (in `DISABLED_SETUPS`) — re-enable when breakouts work
- **Re-enable when:** regime → sustained trend/RISK_ON, OR fresh 60–90d diag_v356 replay +EV, OR
  `GET /api/slow-learning/setup-ev/report?setup=daily_breakout&days=30` shows avg_r>0 on n≥15.
- Detail: `memory/v403_daily_breakout_suppress.md`.

---

## ⚪ E. PENDING ACTIONS (deferred, not yet done)

### E1. ✅ Loser cleanup — proven-bleeder blocklist PROMOTED INTO CODE (2026-06-26, pending DGX deploy)
- **Done (code, sandbox-tested):** `DEFAULT_DISABLED_SETUPS` in `services/entry_gate.py` is now the
  canonical proven-bleeder list = `daily_breakout, vwap_fade_short, vwap_bounce, off_sides_short`
  (was env-only `daily_breakout,vwap_fade_short`, which silently left `vwap_bounce` −1.22R/n31 and
  `off_sides_short` −0.58R/n16 ENABLED). Operator chose 1b (conservative): `backside` stays enabled
  (see E2). Data justification: setup_type is the dominant realized-R factor (eta²=0.21, 120d audit).
- **Also built (read-only):** `GET /api/diagnostic/disabled-setups-audit?days=30&min_n=5` — shows
  effective-vs-default disabled, **`env_dropped_from_default`** (proven bleeders an env silently
  re-enabled), and currently-enabled-but-bleeding setups. Regression test:
  `tests/test_disabled_setups_default_2026_06_26.py` (5 pass).
- **DEPLOY (after close):** Save-to-GitHub → DGX pull → **REMOVE the `DISABLED_SETUPS=` line from
  `backend/.env`** (so the code default governs; keeping the old line re-enables the 2 bleeders and the
  audit will WARN) → `./start_backend.sh --force` → verify `disabled-setups-audit` shows all 4 + clean.
- **Note:** original handoff said append `breakout`/`mean_reversion` — superseded by the realized-R
  data (those weren't the leaks; `vwap_bounce`/`off_sides_short` were).

### E1b. ✅ strategy-autonomy recommender no longer mislabels mild bleeders as "healthy/ENABLE" (2026-06-26, pending DGX deploy)
- **Was:** `_classify` ENABLE band was `wmr > soft_r(-0.12)`, so −0.09R/−0.02R setups (backside,
  stage_2_breakout) were labeled "healthy → ENABLE".
- **Fix (code, 7 unit tests pass):** added `enable_r` gate (default 0.0) — any `wmr < enable_r` →
  WATCH ("no proven edge: …"); only genuinely non-negative expectancy → ENABLE/healthy. Advisory-only,
  zero live-loop behavior change. Files: `services/strategy_autonomy.py`,
  `tests/test_strategy_autonomy_enable_r_2026_06_26.py`. Ships with the same DGX deploy as E1.

### E2. 🟡 `backside` time-decay exit (44% WR, −$935 → +EV)  ← DEFERRED by operator 2026-06-26
- **Plan:** time-based exit in the exit policy for stalled backside setups; env-gated, observe-first.
- **Status:** deliberately parked; revisit after V6 Phase B.

### E3. 🟡 Re-evaluate `max_open_positions` cap (currently 25)
- **Note:** horizon-funnel showed capacity NOT biting (0 capacity_rejections) → low priority
  unless a future session shows approved≫taken.
