## 2026-06-04 — TQS PILLAR + UI SSOT WORK (Part A deployed, Part B in progress)

**v19.34.254 — TQS context pillar de-compression (DEPLOYED + LIVE-VERIFIED).**
Context was frozen at ~62 ±3.5 because on the ib-direct DGX the live alpaca quote
path is dead (regime → range_bound=55) and the only per-symbol inputs (sector,
AI) defaulted to 50. Fix: added a per-symbol **Relative Strength** component (20%
weight) — stock vs the index it belongs to (QQQ/SPY/IWM via new
`data/index_symbols.benchmark_for()`), computed from `ib_historical_data` daily
bars (the data that's actually alive), smooth **tanh** map (calibrated from the
v253 diag: rs_1d stdev ~5.5%, fat tail to +44% → linear ±3% saturated, tanh
doesn't), **inverted for shorts**. Also: multi-index regime fallback (SPY/QQQ/IWM
0.5/0.3/0.2 composite from daily bars when no live SPY quote), and re-weight
(day-of-week 10%→3%, that weight → RS). New weights: regime 22 / RS 20 / time 18 /
sector 15 / VIX 12 / AI 10 / day 3. **Verified live:** context stdev 3.54→5.24
(+48%), rel_strength spans 2-98 (stdev 23.9). 7 pytest.
**v19.34.255 — direction-aware RS factor wording** (drill-down trust fix: a +1d
move is a tailwind for a long but a headwind for a short; show 1d+5d, frame by
side). DEPLOYED.
**v19.34.256 (Part B backend) — `GET /api/tqs/card-detail/{symbol}`** returns the
PERSISTED TQS breakdown that drove the card (not a fresh recompute) + folded
context (rolling 30d setup perf, catalyst+gap, position entry/SL/TP/PnL). The
drill-down drawer's data contract. paste.rs HW0GQ, deploy pending.
**Part B frontend (NEXT):** `TqsBadge` (single trusted badge on every ticker) +
`TqsDrillDownDrawer` (shadcn Sheet, 5 collapsible pillars + folded context) per
`/app/design_guidelines.json`; integrate into ScannerCardsV5 / GamePlanStockCard /
OpenPositionsV5; remove SMB + SetupGradeChip + edge-rank/why-size/shadow badges
from card faces (fold into drawer).


## 2026-06-04 — v19.34.252 (F2) CATALYST_TAG + GAP_PCT POPULATED AT ENTRY (BUILT, paste.rs d7Vfo, deploy pending)

Unblocks the Phase-D edge ranker, which starved because the `catalyst_tag` and
`gap_pct` buckets on `trade_outcomes` were ~100% empty. Two root causes:
1. **catalyst_tag was stamped on PREMARKET alerts only** (`_process_new_alert`
   gated on `time_window=="premarket"`), so the RTH alerts that actually fire
   never got a tag. Now stamped on EVERY alert lacking one.
2. **gap_pct/catalyst_tag never flowed to trade_outcomes** — `build_entry_context`
   didn't capture them and the live-close path didn't pass them through.

Fix (IB/local-data-first per operator directive — no live API on the hot path):
- `CatalystClassifierService`: new `_recent_headlines_mongo()` reads the local
  `news_articles` cache directly (FinBERT-scored, ~92k docs), + a `mongo_only`
  flag on `classify()`. The RTH stamping passes `mongo_only=True` so it NEVER
  hits the 30s live IB-news hang (mirrors the v220 fundamental-pillar fix).
  Earnings still come from the local `earnings_calendar` Mongo collection.
- `enhanced_scanner._process_new_alert`: stamps `catalyst_tag` on all untagged
  alerts (was premarket-only), fail-open + cached.
- `opportunity_evaluator.build_entry_context`: persists `catalyst_tag` +
  `catalyst_summary` + signed `gap_pct` into `entry_context`.
- `position_manager` live close: passes both from `trade.entry_context` into
  `record_trade_outcome`. The `learning_reconciler` already reads them from
  entry_context, so backfilled closes are covered too.
7 new pytest (`test_v19_34_251_f2_catalyst_gap.py`). Hardware-bound — pytest +
lint + import validated, no testing agent.


## 2026-06-04 — v19.34.251 SHADOW TRACKER MEASUREMENT FIX (BUILT, paste.rs CujQu, deploy+backfill pending)

Killed the fake "18pt gap" / 4,407 `would_have_r==0.00` shadow bug. Three root
causes, all fixed:
1. **`would_have_r` hardcoded 0.00** — `track_pending_outcomes()` called
   `update_outcome()` WITHOUT a stop, AND no stop was stored on the decision, so
   the R formula was always skipped. Fix: capture `stop_price` at log time;
   `update_outcome` now falls back to the stored stop.
2. **`would_have_pnl` direction-blind** (`outcome_price - entry`) — a winning
   SHORT scored as a loss. Fix: store `direction`; pnl is now
   `entry - outcome` for shorts, `outcome - entry` for longs.
3. **`was_executed` = the AI "proceed" recommendation** (~100% true), not a real
   fill. Fix: `was_executed` defaults False at log time and is flipped to True +
   linked to the real `trade_id` via new `ShadowTracker.mark_executed()`, called
   from the `trade_execution.py` pre-submit hook (status==PENDING, genuine
   broker-bound trades only). The recommendation intent still lives in
   `combined_recommendation`.

The consult call site (`trade_consultation.py`) already had direction/stop/target
— they were just never passed through to `log_decision`. Added `direction`,
`stop_price`, `target_price` to the `ShadowDecision` dataclass (legacy docs
deserialize with safe defaults). One-time `backfill_shadow_outcomes_v19_34_251.py`
repairs the ~4,407 historical decisions by joining to the nearest `bot_trades`
fill (recovers direction/stop/entry, recomputes pnl+R, corrects was_executed).
8 new pytest + 20 existing shadow-drain regression all pass. Hardware-bound — no
testing agent (pytest + lint + import + dry-run validated).


## 2026-06-03 — v19.34.249b RECONCILER FIXES (DEPLOYED + LIVE-VERIFIED, paste.rs FjHvv)

First `--commit` exposed two bugs (caught via the post-commit audit): alert_outcomes
wrote 0 and strategy_stats never recomputed because `pnl_compute._AO_DB` is None in a
standalone script (no `MONGO_URL` in-env) → canonical writers silently no-op'd; and
OCA-external/EOD sweeps persist `realized_pnl` but NOT `exit_price`, so the 186 bracket
target/stop fills landed in `skipped_no_prices`. Fixes: `reconcile()` now points
`_AO_DB` at the passed db when None, and reconstructs `exit_price` from
`realized_pnl/shares`. 10/10 pytest.

**LIVE-VERIFIED on DGX (full historical backfill committed):**
- Coverage: trade_outcomes 17%→**75%** (240/320, 14d); alert_outcomes 28%→**100%**.
  Connector map: oca_closed_externally 191→**147 TO / 191 AO** (was 5/8).
- strategy_stats EV now matches realized trade_outcomes (the F3 win): accumulation_entry
  **+0.62→−0.44**, vwap_fade **−0.15→−4.46**, daily_breakout +2.73 (genuine), rs_leader_break
  −0.18 (exact match), rubber_band −0.05 (exact). The TQS setup pillar now reads honest EV.
- Remaining TO gap (~25%) is hygiene-excluded artifacts (phantom/wrong-direction/recovery)
  + 44 OCA lacking stop/shares — correct by design.
- **Actionable signal surfaced:** vwap_fade avg_loss_r=5.92 (stops blown to −18R+), −3.66R
  realized over 138 trades → strongly justifies the deferred per-trade −1.5R circuit breaker.




Root-cause fix for the learning audit (v248/v248b). The loop only saw ~17% of
closed trades and the TQS setup pillar trusted an inflated EV.

**F1 — coverage reconciler (`services/learning_reconciler.py`, NEW).** The
OCA-external sweep / EOD auto-close / operator close-panel / consolidation paths
set status INLINE and skip `record_trade_outcome` + `alert_outcomes`, so 238
genuine closes (mostly bracket target/stop fills) never reached the sinks.
`reconcile(db, days, commit)` scans closed `bot_trades` missing from the sinks and
ingests them idempotently using each trade's STORED entry-time `entry_context` /
`market_regime` (not a stale recapture), honoring the hygiene `genuine` tag:
alert_outcomes ← all missing closes (tagged); trade_outcomes ← GENUINE only. It
does NOT call `LearningLoopService.record_trade_outcome` (that has live tilt/gate/
session side-effects that replaying history would corrupt). Wired into the nightly
`_run_learning_stats_rebuild` (days=7) so the rebuild sees the complete set. ZERO
close-path edits → no risk to the cancel/close handshake.

**F3 — canonical genuine whole-trade EV (`pnl_compute.py`).** The v216
`_upsert_strategy_stats_bestEffort` incremented monotonic counters per close-EVENT,
so scale-out partials double-counted (accumulation_entry read 52% win / +0.62R EV
vs the realized 11% / −0.43R; daily_breakout +2.61R vs −1.00R). Replaced with
`recompute_strategy_stats_for_setup(base, genuine_only)` which recomputes win_rate
AND EV from `alert_outcomes` (1 row/trade) so they share ONE whole-trade sample and
the live feed converges with the nightly backfill. `_upsert_strategy_stats_bestEffort`
is now a thin wrapper calling it.

**One-time backlog repair (manual, dry-run-first):**
`backend/scripts/backfill_v19_34_249_learning_coverage.py` [--commit] [--days N].

8/8 pytest (`test_v19_34_249_learning_reconciler.py`, mongomock). Hardware-bound —
no testing agent. Audit/verification scripts shipped too (v248, v248b).



## 2026-06-03 — v19.34.247 EOD-AWARE THRESHOLDS (#7 false pusher-dead banner + stale 3:55 gate, BUILT paste.rs URYip)

Two related run-into-the-close fixes:

(1) **FALSE "IB PUSHER DEAD" banner near EOD (#7, P0).** `/api/ib/pusher-health`
used a hard 30s dead threshold during all market hours. Near EOD the push cadence
legitimately slows — thin ticks into the bell PLUS the serialized 15:45 flatten
loop (many cancel/close IB round-trips) briefly lags the push-data handler past
30s — flashing a false dead banner at the exact moment the operator is watching
the close. New pure helper `_resolve_pusher_dead_threshold(et_minutes)` relaxes the
threshold (default 120s) inside the 15:40-16:05 ET window. The age-None ("never saw
a push") case is unchanged — a truly dead pusher still trips. Response now surfaces
`eod_relaxed` + the active `dead_threshold_s`. Env: `PUSHER_DEAD_THRESHOLD_S`,
`PUSHER_DEAD_EOD_THRESHOLD_S`, `PUSHER_DEAD_EOD_WINDOW_{START,END}_MIN`.

(2) **STALE "EOD fires at 3:55pm" gate text + 15:45-15:55 entry hole.** The v19.29
no-new-entries gate hardcoded HARD_CUT=15:55 / SOFT_CUT=15:45 and emitted "past
3:55pm ET, EOD flatten window owns the last 5 minutes" — but the EOD-flatten loop
moved to **15:45 ET** in v19.34.154. That left a 15:45-15:55 hole where the bot
could open a FRESH entry *while the flatten loop was already running* (the exact
unprotected-overnight risk this gate exists to stop), and the stream text was
stale. New pure helper `_eod_cut_times(eod_hour, eod_minute, grace_min)` re-pins
HARD cut to the bot's ACTUAL flatten time (half-day aware: 12:55), SOFT = HARD −
grace (env `EOD_NO_ENTRY_GRACE_MIN`, default 10m, warn-only). All operator-facing
strings derive from the resolved times → never goes stale again. Also fixed the
static trading-rules string ("by 3:45 PM ET") + two frontend banner comments
(COMMENT-ONLY, no yarn build needed).

9/9 pytest (`test_v19_34_247_eod_aware_thresholds.py`). Hardware-bound — no testing
agent. LIVE-VERIFY at 15:45 ET: pusher-dead banner should NOT flash during the
flatten slowdown; any late-day rejection should read "past 3:45pm" not "3:55pm".



## 2026-06-03 — v19.34.246 CHART-CACHE RTH FRESHNESS CEILING (C/#1, BUILT paste.rs xZQbP)

Root cause CONFIRMED for frozen live charts: `CHART_CACHE_TTL_INTRADAY_S=28800`
(8h) on the DGX cached the MAIN chart's full-window response for the whole
session → IBM 5min stuck at 10:17 with no newer candles (cache rows showed
cached_at 12:33 → expires_at 20:33, +8h). The session-aware rollover clamp only
prevented crossing into the NEXT session, not staleness DURING RTH.
Fix: `_is_session_active_now` (04:00-20:00 ET, DST-safe) + an RTH ceiling — during
the active session the intraday TTL is capped to `CHART_CACHE_RTH_MAX_S` (default
60s); the long 8h TTL still applies overnight for instant revisits. 5 pytest.
FOLLOW-UP: verify the chart-tail WS is actually appending live bars (the skeleton
should be topped up between cache rebuilds) — if it is, charts are near-instant;
if not, worst-case lag is now 60s instead of 8h.


## 2026-06-03 — v19.34.245 EOD CLOSE HONOURS TRADE-STYLE (B / #6, BUILT paste.rs 3CEck)

Recurring bug (logged v19.34.63/69): both EOD-close paths trusted a per-trade
`close_at_eod` attribute set at entry from STRATEGY_CONFIG with a default-True
fallback, so position/swing/investment setups MISSING the key were swept at EOD
(observed: accumulation_entry → eod_auto_close), skewing the learning loop by
flattening multi-day trades before stop/target.
Fix: `order_policy_registry.should_close_at_eod(trade)` resolves close_at_eod from
the trade-style POLICY (authoritative), used in BOTH `position_manager.check_eod_close`
and the manual `/eod-close-now` endpoint. Entry-time source default also fixed
(opportunity_evaluator) so the stored flag is right going forward. Long-horizon
styles held overnight; scalp/intraday still close (operator's priority). 8 pytest.

### C-progress (operator batch)
- #3 scalp-decay persistence — INVESTIGATED, NO BUG. Decay anchors to persisted
  `trade.executed_at` (restored on startup at bot_persistence:419), recomputed vs
  now each cycle — survives restarts correctly. No runtime timer.
- #1 charts stale — LEADING HYPOTHESIS: `chart_response_cache` intraday TTL
  (`CHART_CACHE_TTL_INTRADAY_S`) set large → full-window served from a frozen
  snapshot for hours; and/or chart-tail WS not appending fresh bars. Awaiting
  operator env value + reproduction scoping.


## 2026-06-03 — v19.34.243 PER-ENTRY GATE + v19.34.244 DISABLE vwap_fade_short

### v19.34.243 — per-entry batch gate (P0, DEPLOYED 4e238d51)
Fixed two entry-control incidents. The scan→execute loop checked PAUSE + the
position CAP once per cycle then fired the whole alert batch without re-checking.
Diag (`diag_entry_control.py`): normal peak concurrent 8-9; 06-02 overshot to 27
(busy day, batch spilled past the 25 cap); CEG (06-03) was a fresh 17s-lag market
entry in an in-flight batch. Fix: NEW `services/entry_gate.py` pure
`per_entry_gate_should_stop(open, pending, cap, paused)` re-checked before EVERY
entry — halts the batch on mid-cycle pause OR open+pending>=cap (counts pending,
closing the overshoot). Operator kept the 25 cap. 8 pytest.

### v19.34.244 — disable vwap_fade_short (P1, BUILT paste.rs g0vUR)
vwap_fade bleed diagnosed (`diag_vwap_fade_bleed.py`): the SHORT side is the whole
leak — n=53, 8% win, **-4.26R, -$22k**; 39% of trades blew past the 1R stop
(WTI -18R, PRCT shorted 8x at -8.88R = post-stop re-entry loop); only 7% ever went
green (fading into strength). vwap_fade_LONG is profitable (+0.51R, 31% win) and
stays on. Fix: NEW `DISABLED_SETUPS` env-blocklist (default `vwap_fade_short`)
checked at the bot entry gate — scanner still surfaces it for monitoring, only
TRADING is blocked. `parse_disabled_setups` in entry_gate.py. 12 pytest.

### Still open from the vwap_fade finding (queued)
- Per-trade max-loss circuit breaker (-1.5R hard market exit) so NO setup can ever
  do another -18R. Needs careful scoping of the manage/close path.
- CEG-style retry storm (9x stale_pending_auto_reaper/hr) — per-symbol retry backoff.


## 2026-06-03 — v19.34.241 hygiene: reject reconciliation/import setup_types (BUILT, paste.rs 0gajg)

The v240 dry-run showed `reconciled_excess_slice` (n=20), `reconciled_orphan` (n=5),
`imported_from_ib` (n=2) still grading as genuine setups — they reached bot_trades as
a `setup_type` but never came from a strategy detector. Added `_ARTIFACT_SETUP_SUBSTRINGS`
({reconciled, imported, phantom}) to `classify_close(setup_type=...)`; wired at the
pnl_compute live hook + backfill. 17 hygiene pytest pass. Re-deploy then re-run backfill.


## 2026-06-03 — v19.34.240 TRADE-OUTCOME HYGIENE (EV de-pollution) + MFE/MAE FLOOR (BUILT, paste.rs g2qmv)

### Why
`diag_accum_oca_drill` proved the `accumulation_entry` "underperformance" was a
MEASUREMENT artifact: ~94% of its closed trades were 2026-05-19→26 phantom/drift
wreckage (1-min external OCA unwinds, phantom sweeps, operator flattens with
±$20k P&L on entry==exit rows) polluting the `strategy_stats` EV scoreboard.
The pollution vector is `apply_close_pnl → _record_alert_outcome_bestEffort →
strategy_stats`, which runs on EVERY close. (`trade_outcomes`/edge-ranker is fed
only by the genuine manage-loop close at position_manager:3300, so it was clean.)

### What (Part A — hygiene)
- NEW `services/trade_outcome_hygiene.py` — single DRY classifier
  `classify_close(reason, entered_by, entry, exit, net_pnl, hold_s) -> (genuine, tag)`.
  Artifact rules: reason ∈ {phantom/sweep/purge/reconcile/operator_external/
  external_flatten}; entered_by ∈ {reconcil/phantom}; `oca_closed_externally`
  held <120s; entry==exit with |pnl|>$5.
- `pnl_compute`: tags `alert_outcomes` with genuine/hygiene_tag (audit preserved)
  and SKIPS the strategy_stats EV upsert for non-genuine closes.
- `gameplan_edge_ranker`: read-side defense — query excludes `genuine:False`
  (backward-compatible `$ne`), and drops rows with `|actual_r|>20` (corrupt R).

### What (Part B — MFE/MAE floor)
- `excursion_floor(direction, entry, exit, stop)` computes realized entry→exit R.
- `pnl_compute` finalizes `bot_trades.mfe_r/mae_r` from the floor when the manage
  loop left them 0 (sub-minute closes) — never overwrites a real peak. Was 34%
  populated globally because artifact trades die before any manage tick.

### Backfill (run AFTER deploy; idempotent; --dry-run first) paste.rs tAYth
`backfill_v19_34_240_hygiene.py`: rebuilds strategy_stats genuine-only over a
lookback window (CORRECTS the polluted EV now), retro-tags alert_outcomes, fills
bot_trades excursion floor. Writes ONLY stat fields — no order logic.

### Verification
23 pytest pass (`test_v19_34_240_outcome_hygiene.py`) + 24 edge-ranker regression
tests green. Hardware-bound: no testing agent. Deploy idempotent, pytest-gated,
git commit+push before restart.


## 2026-06-03 — v19.34.239 DYNAMIC trigger_probability (always-on) (BUILT, paste.rs dGeht)

### What
Every scanner detector (53 sites) stamps a HARDCODED per-setup `trigger_probability`
constant — a static label the probability gate had no live weight on. v239 treats
that constant as a CALIBRATED BASE and lets live signals move it:
- distance-to-trigger (`current_price` → `trigger_price`, %) and RVOL deltas
- clamped to [0.15, 0.90]

### How
The pure helper `compute_live_trigger_probability(base, distance_pct, rvol)` already
existed (v238) but was DEFINED-NEVER-CALLED. Rather than edit 53 detector sites, it
is now applied at the single enrichment chokepoint `enhanced_scanner._apply_setup_context`
(runs on every `_check_setup` hit at L3428). Fail-open: any error leaves the original
constant untouched. Always-on (operator confirmed). Affects new alerts going forward.

### Verification
- `tests/test_v19_34_239_dynamic_trigger_prob.py` 8/8 pass (.venv pytest).
- Hardware-bound: no testing agent. Deploy via paste.rs (idempotent gzip+base64,
  pytest-gated, git commit+push BEFORE restart, ./start_backend.sh --force).


## 2026-06-03 — v19.34.237 (Phase D follow-up B) DIRECTION-AWARE EDGE BUCKETS + COVERAGE AUDIT (BUILT, paste.rs MQsVr)

### What
- **Direction** added to every realized-edge bucket key (L1-L4) in
  `gameplan_edge_ranker.py`. A setup's EV differs long vs short, so long
  history no longer leaks into a short setup's score (and vice-versa).
  `normalize_direction()` defaults unknown → long (consistent both sides).
- **`coverage_summary()`** audit method: per-level {total, usable(≥MIN_SAMPLES)}
  bucket counts, so we can see how often the fine L4/L3 catalyst+gap+direction
  buckets actually fire vs falling back to L2/L1 as history accrues (Phase D
  follow-up item 3).
- Tests: `test_v19_34_237_edge_direction.py` 5/5 + v233 regression 10/10 = 15/15.
  Lint clean. Backend-only, no trading-path impact — deploy anytime.

### Deferred (Phase D follow-up item 2)
- Live `trigger_probability` formula port lives in the SCANNER (alert_system/
  enhanced_scanner), not the edge ranker — separate task, currently static per
  setup. Flagged for a follow-up when the scanner work resumes.

---

## 2026-06-03 — v19.34.236 (Part A) PENDING FILL ATTRIBUTION (BUILT, flag-gated OFF; deploy at close)

### What (the deep cure for bot-vs-IB drift)
When an entry actually FILLS at IB but the fill is never attributed back
(`entry_order_id=None` race: `place_bracket_order` raises/times-out after the
parent is live, `_execute_trade` leaves the row PENDING), the reaper used to
falsely reject it and the reconciler re-adopted the shares as a SYNTHETIC
`reconciled_excess` slice (losing setup/intent, pre-v235 re-arming an oversized
bracket). Now the reaper tick first MATCHES the live IB orphan to its original
PENDING row and PROMOTES it to OPEN, preserving `entered_by=bot_fired` + setup
+ TQS + AI context.

### How
- NEW `services/pending_fill_attribution.py` (pure/testable):
  `match_pending_to_orphan(symbol, signed_qty, pending_rows, now)` — same
  symbol+direction, pre_submit age in [30s, 3600s] (avoids racing in-flight
  entries / ancient pendings), order size able to produce the fill
  (`|orphan| <= shares*1.5`); picks closest share count then oldest. Plus
  `build_promotion_update()`.
- `trading_bot_service._attribute_pending_fills()` — flag-gated
  (`PENDING_FILL_ATTRIBUTION_ENABLED`, default OFF). Pulls live IB positions,
  finds orphans the bot isn't tracking as open, promotes the matched pending
  in-memory (pending→open) + persists + writes a `state_integrity_events`
  audit row. **Submits NO orders** — leaves protection to the v235-clamped
  naked-sweep. Called at the TOP of the reaper tick (before the reap decision)
  so a filled entry is promoted, not reaped/re-adopted.
- Tests: `test_v19_34_236_pending_fill_attribution.py` 12/12 (exact/partial/
  direction/symbol/too-young/too-old/overfill/closest/tie/zero/promotion-shape).
  Full drift suite 23/23 (234+235+236). Lint clean. paste.rs JmtSH.

### Deploy (at close, bot flat, then watch)
1. deploy script → inert (flag OFF). 2. enable `PENDING_FILL_ATTRIBUTION_ENABLED=1`
+ restart. 3. `grep v19.34.236 /tmp/backend.log` / `state_integrity_events
{event:"pending_fill_attributed"}`. Disable instantly via flag=0.

### Note — v1 scope
Promoter runs in the reaper loop (60s). If the reconciler wins a race and
spawns a synthetic first, the promoter skips (symbol now tracked) — no worse
than today; when the promoter wins, attribution is correct. Future: move the
hook into the reconciler's adoption decision for race-free promotion. Also
still open: `ib_executions` empty-for-day + executor `/positions` empty
(observability).

---

## 2026-06-03 — v19.34.235 (Part B) BRACKET-SIZE CLAMP (DEPLOYED, live during RTH w/ scanner paused)

### What
Every protective stop+target (re)issue now clamps its qty to the LIVE IB
position, so a stale `trade.shares` can never arm a closing order larger than
the position holds — the SOXX `Sell-43-vs-17` flip hazard is now structurally
impossible.

### How
- New module-level `clamp_protective_qty(requested, live_abs) -> (qty, clamped)`
  in `ib_direct_service.py`: only SHRINKS to a confirmed smaller position
  (0 < live < requested), never grows, and fail-opens (no clamp) when
  `live_abs is None`.
- New `IBDirectService.live_position_abs(symbol)`: returns |live IB position|
  or None (None on get_positions error / empty snapshot / symbol absent — so a
  snapshot gap never clamps a closing order down to 0).
- Applied at the two adoption/re-issue chokepoints that sized off
  `int(trade.shares)`:
  - `ib_direct.place_oca_stop_target` (the active BOT_ORDER_PATH=direct path)
  - `trade_executor.attach_oca_stop_target` queue path
- DELIBERATELY NOT applied to the two-step entry stop (`ib_direct.place_stop`):
  it sizes to a just-filled entry, and clamping there could under-protect a
  fresh fill if get_positions lags. Minimal blast radius.
- Tests: `test_v19_34_235_bracket_clamp.py` 6/6. Imports clean; the 3 lint
  warnings shown were pre-existing/unrelated. Deployed via paste.rs px3ub +
  `./start_backend.sh --force` (commit 6767e69e). Post-boot: healthy, clamp
  silent for BE (29==29) as expected.

### Still pending — Part A (the deep cure; DO at close / when flat)
- Capture `entry_order_id` on pre-submit + attribute IB execDetails/orderStatus
  so a filled pending flips to `open` and never reaches the reaper (eliminates
  the orphan creation at the source; v234 only guards the reaper symptom).
- Plus observability: `ib_executions` collection empty for the day; executor
  `/positions` returns empty while ib_direct returns data.

---

## 2026-06-03 — v19.34.234 BOT-vs-IB DRIFT: source-side guard (DEPLOYED, live-verified during RTH)

### Trigger
Live RTH: bot positions/brackets diverged from TWS. Forensics (read-only
`/tmp/diag_bot_vs_ib_today.py`, paste.rs 2RsUs) traced it to SOXX: bot tracked
a stale `reconciled_excess_v19_34_15b` slice and IB held **Sell 43** bracket
orders against a **17**-share long → flip-to-short-26 hazard. Operator
flattened manually; root-caused and patched.

### Root cause chain
1. Pre-submit entry orders had `entry_order_id=None` → IB `execDetails` fill
   never attributed back → `bot_trades` row stayed `pending`, `executed_at=None`.
2. `_stale_pending_reaper_loop` (v19.34.30) blindly marked it `rejected /
   stale_pending_auto_reaper` after 300s **without checking IB for a fill**.
3. The real (now-orphaned) IB shares got adopted as a synthetic
   `reconciled_excess` slice; the consolidator merged 17+26→43 and reissued a
   **43-share bracket**, then tracking shrank 43→17 (LIFO) but the 43 IB
   orders were never resized. Same reaper-vs-fill race churned SOXX/LRCX/ALAB/
   ASTS/NXPI/SMH all session (Day Tape full of reconciled_orphan/excess).
4. `positions/truth-diff` compared IB against the stale `.shares` (43) not
   `.remaining_shares` (17) → falsely flagged a 26-share mismatch while the
   bot's tracked position (17) actually matched IB.

### Shipped (commit e694a5e9, two low-blast-radius fixes safe for live RTH)
- **Pending-reaper fill-race guard** (`trading_bot_service.py`): new
  module-level `_reaper_should_skip_filled(sym, ib_pos_syms, bot_open_syms)`.
  Reaper now pulls live IB positions once per tick and SKIPS any stale pending
  whose symbol shows an IB position the bot isn't tracking as open (→ likely
  unattributed fill); logs `[v19.34.234 reaper-guard]` + writes a
  `state_integrity_events{event:"reaper_skip_likely_filled"}` audit row instead
  of falsely rejecting the real fill. Worst case = a benign lingering pending
  row; never places/closes an order.
- **truth-diff** (`routers/trading_bot.py`): compares IB against
  `remaining_shares` (live) with `.shares` fallback.
- Tests: `test_v19_34_234_reaper_fill_guard.py` 5/5. Lint clean (pre-existing
  F-warnings untouched). Deployed via paste.rs P5Lj9 + `./start_backend.sh
  --force` while flat. Post-boot: truth-diff `in_sync`, bot/ib=1/1, no false
  mismatch; bot resumed trading in sync.

### NOT yet done — the full cure (larger, safety-critical; do PAUSED / after close)
- Capture `entry_order_id` on pre-submit + attribute `execDetails`/
  `orderStatus` so a filled pending flips to `open` (never reaches the reaper).
- Clamp every bracket (re)issue to the live IB position size so a
  consolidator/naked-sweep can never arm an oversized closing order (flip).
- Secondary observability gaps surfaced: `ib_executions` collection empty for
  the day (exec audit trail not persisting); executor `/positions` returns
  empty while ib_direct returns data.

---

## 2026-06-03 — v19.34.233 PHASE D: Game Plan ranked by REALIZED open-session edge — BUILT, paste.rs https://paste.rs/edC3b (operator deploy pending)

### What
Replaced the heuristic pm→daily→intraday *append order* of the Game Plan's
`stocks_in_play` with a DATA-DRIVEN ranking from the bot's own realized
history (`trade_outcomes`). Each name is scored by Expected Value in R (EV-R)
the bot has historically captured for that *kind* of setup, blended with the
alert's TQS grade.

### How
- NEW `services/gameplan_edge_ranker.py` (`GamePlanEdgeRanker`, pure/testable):
  buckets decided outcomes by `(setup_type, catalyst_tag, gap_bucket,
  regime_bias)` and does a **shrinkage walk** to coarser buckets when a fine
  one is thin — L4 (full) → L3 (drop gap) → L2 (setup+regime) → L1 (setup) —
  picking the first level with ≥ MIN_SAMPLES (5) decided trades.
  - EV-R = win_rate·avg_win_R − loss_rate·avg_loss_R.
  - Blend: `score = (W_EV·k)·ev_comp + (1−W_EV·k)·tqs_comp`, with sample-size
    shrinkage `k = n/(n+10)`, `W_EV=0.65`. Thin buckets lean on TQS.
  - COLD-START (no bucket qualifies): `edge_source="tqs_fallback"`, ranks by
    TQS (preserves the prior heuristic order). Per operator choice.
  - Regime vocabularies differ (`CONFIRMED_UP` vs `strong_uptrend`) → both
    reduced to a shared bias bucket {up, down, range} so the dim is comparable.
- `gameplan_service._auto_populate_game_plan`: after stocks built + regime
  resolved, calls `GamePlanEdgeRanker.from_db(db).rank(...)`. Best-effort
  (never blocks a gameplan). `_alert_to_stock_entry` now carries `gap_pct`.
- `models/learning_models.TradeOutcome`: + `catalyst_tag` / `gap_pct` fields;
  `learning_loop_service.record_trade_outcome` accepts + persists them
  (default-safe) so the FINE buckets sharpen as outcomes accrue.
- FE `GamePlanStockCard.jsx`: `#edge_rank` badge in the card header — cyan =
  realized edge (title shows EV-R + sample size), grey = TQS fallback.
- Tests: `test_v19_34_233_gameplan_edge_rank.py` 10/10 (EV ordering, cold-start,
  shrinkage walk, MIN_SAMPLES gate, regime separation, fundamentals-catalyst
  fallback). Adjacent v231+v232 still green → 32/32 total. ruff + ESLint clean.

### Notes
- Additive: no existing path removed; ranking + 2 nullable outcome fields.
- Historical rows lack catalyst_tag/gap → fine buckets are empty for them; the
  shrinkage walk transparently lands on (setup+regime), which IS populated.
- Deploy script embeds full files (gzip+b64), idempotent, `git commit && push`
  (the `.bat` `git checkout -- .` would wipe uncommitted work). FE needs
  `yarn build`.

---

## 2026-06-02 — v19.34.228 TQS GRADE CALIBRATION (percentile rank + floor) — DEPLOYED, live-verified

### Problem (validated, not guessed)
The composite TQS is a weighted AVERAGE of 5 pillars (tqs_engine.calculate_tqs).
Averaging crushes variance → scores live in ~48-66, stdev ~2.9 (verified live:
`recomputed==stored` for every alert, left tail pre-gated `<48 ≈ 0%`, only 19
distinct integer scores). The old absolute bands (A≥85 …) lumped ~100% of trades
into C/C+ → 100% sized at 0.3× (the 1-share TSEM/MU positions). The absolute
score is a poor ruler but the RANKING is valid.

### Fix
- NEW `services/tqs/grade_calibration.py`: grade by PERCENTILE RANK against a
  rolling reference (trailing 5d of `live_alerts.tqs_score`, TTL-cached 15min,
  dedicated sync MongoClient like execution_quality) + ABSOLUTE FLOOR (no A
  unless raw≥60, no B unless ≥57). Monotonic/safe (only relabels), self-adapting
  (auto-respreads when pillars are later de-compressed — no redeploy), static-band
  fallback if reference unavailable/too small.
- `tqs_engine.calculate_tqs`: score→grade now calls `calibrate_grade` (static
  fallback on error).
- `opportunity_evaluator`: sizer recalibrated A=1.0 B=0.6 C=0.3 D=0.15 F=0.1
  (F added explicitly; was falling through to D). Env-overridable.
- Tests: `test_v19_34_228_tqs_grade_calibration.py` 7/7 pass.
- Env knobs: `TQS_CAL_ENABLED`, `TQS_CAL_PCT_{A,B,C,D}`, `TQS_CAL_FLOOR_{A,B}`,
  `TQS_CAL_WINDOW_DAYS`, `TQS_CAL_TTL_SEC`, `TQS_CAL_MIN_SAMPLE`,
  `POSITION_SIZE_GRADE_{A,B,C,D,F}_MULT`.
- Deploy `deploy_v19_34_228.py` (paste.rs, multi-file incl. new file, idempotent,
  runs pytest, commit+push). Commit 3374b43c on GitHub main.

### LIVE-VERIFIED (verify_tqs_calibration_live.py, market closed)
reference n=6492. New grade spread: A 9.3% / B 20.9% / C 35.4% / D 24.4% /
F 10.0% (target ~10/20/35/25/10 ✓). Mean size multiplier 0.371× (up from flat
0.30×) — a ~24% avg size-up because ~9% now earn A@1.0× (taken trades ~0.33-0.35×
since the bot doesn't take only top-ranked). Tunable live via env. Calibration
applies to NEW alerts going forward (historical grades unchanged).

### Durable follow-up (②, P0-next)
De-compress the pillars that squeeze the raw composite: `setup` (median 48,
caps ~65) and `execution` (median 49 = its floor; still defaults — not enough
per-setup trade_outcomes). Widening these widens the raw score; the calibration
layer then auto-respreads.

---


## 2026-06-02 — v19.34.227 HELD-POSITION QUOTE PIN + watchdog wiring fix

Follow-up to v226. ROOT of the CRM mark-less issue + two latent bugs:
- **position_manager manage loop**: an open trade with NO quote at all hit
  `if not quote: continue` and was NEVER flagged for re-subscribe (only the
  "stale quote" branch flagged symbols) → it stayed mark-less forever. Now it's
  added to `_stale_resub_set` so the resub drain + watchdog re-pin it.
- **quote_resub_watchdog_loop was a silent no-op in production**: it read
  `getattr(bot,"position_manager")` / `getattr(bot,"db")`, but the bot stores
  `_position_manager` / `_db` → `_tick` NEVER ran. Fixed the lookups, AND the
  watchdog now proactively PINS every `_open_trades` symbol into the pusher
  quote universe each cycle (subscribes any held name missing from the live
  subs). Held positions can no longer go mark-less (also needed for local stop
  checks).
- Tests: 11/11 pass (6 existing watchdog + 5 new pin —
  `test_v19_34_227_open_position_quote_pin.py`). Deploy:
  `deploy_v19_34_227.py` (paste.rs, multi-file, idempotent, commit+push).
  BACKEND restart required. ⚠️ Operator live-check pending: confirm
  `[v19.34.227 ... PINNING ...]` log + no open position with current_price=0.

---


## 2026-06-02 — v19.34.226 KILL-SWITCH FALSE-TRIP FIX (zero-mark unrealized)

### Symptom (operator-reported)
The v123 daily-loss kill-switch kept tripping: `realized=$155 + unrealized=
-$18,890 = -$18,735 ≤ -$5,000`, blocking all new trades. Operator suspected a
recent change.

### Root cause (proven via diag_killswitch_unrealized.py on the live bot)
The kill-switch sums `unrealized_pnl` over in-memory `_open_trades`. ONE position
— **CRM**, 95 sh @ $198.92, `current_price = 0.00` (no live quote; dropped from
the push around the v224/225 pusher restarts) — produced
`(0 - 198.92) * 95 = -$18,897`, a FAKE loss. Genuine intraday P&L was +$7.23.
The unrealized calc blindly trusted a zero/missing mark.

### Fix (two defensive guards)
- `position_manager.py` (~L708): never compute unrealized when
  `current_price <= 0`; hold the last good value until a real mark arrives (also
  stops the UI showing a fake -$18,897 on CRM's card).
- `trading_bot_service._compute_realtime_daily_pnl`: SKIP any open trade with
  `current_price <= 0` from the kill-switch unrealized sum (logs the skip count).
  A missing mark must NEVER trip the daily-loss kill-switch.
- Deploy: `deploy_v19_34_226.py` (paste.rs, base64-guarded, idempotent,
  multi-file, commit+push). BACKEND change → DGX backend restart required.
- **LIVE-VERIFIED**: post-restart the kill-switch unrealized dropped from
  -$18,890 to +$201.76 (all genuine intraday), STALE/ZERO subtotal $0, CRM's
  quote recovered (+$120.65). False trips stopped. ✅

### Open follow-up (P1)
CRM had no live quote because an open position that's not in the current scan
universe can fall out of the quote push (exposed by the v224/225 restarts). The
guard makes the P&L math safe, but an open position with no mark also can't drive
local stop checks (IB-side bracket still protects). FOLLOW-UP: force
quote-subscription for every symbol in `_open_trades` so held positions always
have a live mark.

---


## 2026-06-02 — v19.34.224/225 L2 DYNAMIC-SUBSCRIBE FIXED (was 100% dead)

### Symptom (operator-reported, live pusher logs)
Every `/rpc/subscribe-l2` showed `added=[] skipped=[GDX,SGOV,...] (slots 0 → 0 / 6)`
and every push reported `level2: 0`. L2 (market depth) was completely
non-functional — 0 of N slots ever filled. The v221–223 slot bump to 6 was moot
because nothing landed in the slots.

### v19.34.224 — ROOT CAUSE: sync qualifyContracts inside the IB event loop
`/rpc/subscribe-l2` dispatches `_do_subscribe_l2` ONTO the IB event loop via
`_run_on_ib_loop` → `asyncio.run_coroutine_threadsafe`. Inside it called the
SYNC `subscribe_level2`, whose `self.ib.qualifyContracts()` does a reentrant
`loop.run_until_complete()` — illegal while the loop is already running ("This
event loop is already running"). It raised for EVERY symbol (both ISLAND and
NYSE attempts), fell through to `continue`, and left L2 at 0 forever. Same bug
class as the v19.34.30 `qualifyContractsAsync` sweep — this pusher site was
missed. (Startup L2 worked because it ran synchronously, but Path B disabled
startup index L2, routing 100% of L2 through the broken RPC path since 2026-04-28.)
- **Fix**: new async `subscribe_level2_async` that `await`s
  `qualifyContractsAsync`; the RPC coroutine now awaits it. Added a built-in
  entitlement probe (1.5s post-subscribe) that logs `L2 DATA OK <sym>: X bids /
  Y asks` vs `L2 NO DEPTH DATA <sym> ... entitlement` so the next run reveals
  whether any 0-data is a code bug or a missing IB depth entitlement.
- **LIVE-VERIFIED on DGX**: after restart, `added=[AXTI,IBM,MA,V,...] skipped=[]
  (slots 3 → 6 / 6)`, `L2 DATA OK ...: 5 bids / 5 asks`, pushes now show
  `level2: 6`. The paper account DOES have depth entitlement. ✅
- Deploy: `deploy_v19_34_224.py` (paste.rs, base64-guarded, idempotent,
  commit+push before restart). L2-only — no order-routing/data-push impact.

### v19.34.225 — FOLLOW-UP: ib_insync updateMktDepthL2 IndexError guard
Once depth actually flowed, ib_insync's `updateMktDepthL2` began throwing
`IndexError: list assignment index out of range` — it does `dom[position] = ...`
for an 'update' (operation=1) on a level never 'inserted' (position >= len(dom)).
Caught by the library decoder (no crash) but spammed logs + could drop depth
levels. Defensive monkeypatch installed at pusher import: wrap-and-retry that
pads the dom list with empty levels (price=0/size=0, filtered by
`poll_level2_data`) then calls the original. Read-only depth path — zero order
impact. Validated against real ib_insync (original raises; guard pads+applies;
normal insert/delete intact; idempotent). Deploy: `deploy_v19_34_225.py`
(paste.rs, commit ba7305ca pushed to GitHub main). Requires v224.
- **LIVE-VERIFIED on DGX**: after restart, L2 6/6 with `level2: 6` pushes and
  `5 bids / 5 asks` per symbol, and the `updateMktDepthL2` IndexError tracebacks
  STOPPED. ✅

---


## 2026-06-02 — v19.34.221–223 L2 SLOT BUMP (B) + ma_stack INVESTIGATION (C)

### v19.34.221 (B) — L2 router: MAX_L2_SLOTS env + IB-309 cap watch
- `services/l2_router.py`: `_MAX_L2_SLOTS` now reads `MAX_L2_SLOTS` env (default 3,
  the historical IB paper-mode ceiling). Deploy appended `MAX_L2_SLOTS=6` to
  backend/.env. Added an IB-Error-309 / pusher-cap watch — `cap_rejections` +
  `last_cap_skipped` surfaced in `/api/ib/l2-router-status`, WARN log when the
  pusher rejects an L2 add (no more silent thrash).
- Live-verified: status endpoint shows `max_l2_slots: 6`, `cap_rejections: 0`.
- Tests: `test_v19_34_221_l2_slots.py` 3/3. NOTE the status route is
  `/api/ib/l2-router-status` (NOT `/api/l2-router/status`).

### v19.34.221 (C) → v19.34.222 — ma_stack: ATTEMPTED, REVERTED
- Attempt (v221): derive ma_stack from EMA alignment (ema_9>ema_20>ema_50).
  BACKFIRED — went 78%→84.5% neutral. Root cause: the snapshot's `ema_9`/`ema_20`
  are INTRADAY (intraday bar EMAs) while `ema_50`/`sma_200` are DAILY, so the
  stack comparison re-introduced the exact timeframe mix v215 removed.
- v222: REVERTED `technical_quality.py` to the v215 intraday-`trend` logic.
  CONCLUSION (investigation result): ma_stack ~78% neutral is NOT a bug — it's an
  accurate read of the deliberately-conservative intraday trend classifier (v166)
  on a chopping tape; the snapshot cannot form a clean single-timeframe MA stack.
- Tests: `test_v19_34_222_ma_stack_trend.py` 4/4 (self-contained). Cleaned up two
  junk files ('=' and 'main') the terminal accidentally committed in 72087ba9.
  (v222 first run failed pytest on a prior-job test not present on the DGX repo;
  v222b finished the commit with a self-contained test. Commit 58b8819e.)

### v19.34.223 — Windows pusher L2 cap → env-driven
- `documents/scripts/ib_data_pusher.py`: replaced 5 hardcoded 3-slot caps with a
  single `_MAX_L2_SLOTS = int(os.environ.get("MAX_L2_SLOTS","3"))`, matching the
  backend so ONE env knob drives both sides. Commit 3f4ef779.
- Operator action (Windows `.bat`): add `set MAX_L2_SLOTS=6` in CONFIGURATION and
  inject `&& set MAX_L2_SLOTS=%MAX_L2_SLOTS%` into the Step-5 pusher launch line
  (alongside IB_PUSHER_L1_AUTO_TOP_N). The `.bat` Step 2 git-pulls both Win + DGX,
  so it auto-updates on restart once those two lines are added.
- CAVEAT: 6 only takes effect if the IB account grants ≥6 market-depth lines.
  Paper accounts historically 309'd at 5 — watch `cap_rejections` in l2-router
  status; if non-zero, IB is capping below 6 (need entitlement or dial back to 3).

### Deploy discipline
All via checksum-/content-guarded base64 paste.rs scripts
(`deploy_v19_34_221..223.py`), idempotent + transactional, commit+push before
restart. Hardware-bound — no testing agent. The Windows `.bat` restart is now
SAFE (all work committed+pushed; DGX `git checkout -- .` + `git pull` loses nothing).

---


## 2026-06-02 — v19.34.216–219 TQS PILLAR DE-PINNING (EV live-hook + Execution live-state)

### Context
Continuation of the P0 Signal Measurement Audit. `diag_tqs_pillar_breakdown.py`
showed two TQS pillars scoring CONSTANTS for ~100% of alerts: the Setup pillar's
**EV** (expected_value_r=0.0) and the **Execution** pillar (flat 48.80 — every
sub-component at its default).

### v19.34.216 — LIVE EV HOOK (strategy_stats stays fresh on every close)
- Root cause: the modern close path (`pnl_compute.apply_close_pnl`) writes
  `alert_outcomes` but the scanner's `record_alert_outcome` (the only writer of
  `strategy_stats`, the TQS Setup-pillar EV feed) requires `alert_id ∈
  scanner._live_alerts` — which reconciler/operator/manage-loop closes bypass.
  So `strategy_stats` was orphaned → EV=0 everywhere.
- Fix: `pnl_compute._record_alert_outcome_bestEffort` now ALSO upserts into
  `strategy_stats` (`_upsert_strategy_stats_bestEffort`), mirroring
  `backfill_strategy_stats.py` math + `base_setup` keying exactly, on every close.
- Backfill (operator-run `backfill_strategy_stats.py --commit`) seeded 15 setups
  (squeeze −0.01/54, accumulation_entry +0.62/44, daily_breakout +2.61/5…).
- Tests: `test_v19_34_216_strategy_stats_live_hook.py` 7/7.

### v19.34.217 / 218 / 219 — EXECUTION PILLAR LIVE-STATE (read trade_outcomes direct)
- Root cause (3-step diagnosis via `diag_execution_pillar.py` + `probe_live_exec_state.py`):
  the pillar reads `get_trader_profile()`, but (a) the persisted `trader_profiles`
  "default" doc was MISSING (the EOD daily batch never populated it), and (b) the
  in-memory profile that DOES exist has a broken win-rate aggregation (0) + a tilt
  counter that resets, and (c) `learning_loop.get_recent_outcomes()` returns EMPTY
  in the TQS-engine context (collections wired in a deferred background init).
- v217: derive recent_win_rate + consecutive_losses live from outcomes when the
  profile is empty (only fired when profile_has_data=False — but live profile had
  total_trades>0, so it didn't fire).
- v218: ALWAYS override those fields from outcomes (but still via learning_loop →
  returned empty → pillar pinned at the no-data constant 76.50).
- v219 (definitive): read `trade_outcomes` DIRECTLY via a cached pymongo client
  (same pattern as pnl_compute), independent of the flaky learning_loop ref.
  `_derive_live_execution_state` handles raw mongo dicts OR TradeOutcome objects.
  Emits a WARN if the direct read ever returns 0.
- Live-verified 2026-06-02: `recent_win_rate` + `avg_r_capture_pct` default-rate
  dropped 100% → 0% (now real ~0.48 win-rate). `consecutive_losses=0` is now
  CORRECT data (no current losing streak), not a default. Pillar 48.80→72.00.
  The pillar is identical across simultaneous alerts BY DESIGN (it measures the
  trader's global state, not per-symbol); it tracks performance over time.
- Tests: `test_v19_34_217_execution_pillar_live_state.py` 7/7.
- NOTE: per-setup `history_score` (25% of the pillar) is still constant because
  it ALSO uses learning_loop.get_recent_outcomes — a lower-value follow-up
  (would add per-setup execution-quality variation).

### Deploy
All four shipped via checksum-guarded base64 paste.rs scripts
(`deploy_v19_34_216..219.py`), idempotent + transactional, commit+push before
restart. Hardware-bound — no testing agent.

### v19.34.220 — FUNDAMENTAL PILLAR catalyst from news_articles cache
- Root cause (`diag_news_catalyst.py`): catalyst (30% of the pillar) floored at
  40 for ~100% of alerts. The pillar called the LIVE `news_service.get_ticker_news`
  per alert — which tries IB historical news FIRST with a 30s timeout (hangs in
  this ib-direct deployment; `/api/ib/news/<sym>` timed out >20s for all symbols)
  then Finnhub (rate-limited ~60/min) — unusable per-alert. Meanwhile the local
  `news_articles` cache (Finnhub+Yahoo collectors, 92k docs, FinBERT-scored,
  fresh today) sat unused. (Finnhub itself is healthy: 247 items for AAPL.)
- Fix: pillar now reads recent (≤72h) news for the symbol directly from
  `news_articles` (fast indexed lookup; `self._db` already wired) and derives
  has_recent_news + news_sentiment from the FinBERT `sentiment` dict
  ({"sentiment","score"}). Lifts catalyst 40→50 (news-neutral) / 65 (directional).
  Added `news_articles {symbol:1, datetime:-1}` index.
- Live-verified 2026-06-02: 63% of alerts (112/177) lifted off the 40 floor
  (90@50, 22@65, 65@40 genuinely no-news). Fundamental pillar max 65→69.5.
  Sample lifted: INTU, VOO, UPS, LUNR, SNPS, FN, HPE, TMUS…
- `has_catalyst` raw sentinel still reads 100% false BY DESIGN — it's a separate
  caller-driven flag, not the catalyst_score (which is now live).
- Tests: `test_v19_34_220_fundamental_news_cache.py` 5/5. Commit e98ec4e9.
- FOLLOW-UP (separate bug): the live `get_ticker_news` IB-historical-news path
  still hangs ≤30s (affects the UI `/api/ib/news/<sym>` endpoint). Lower priority.


### Still pinned (next levers)
`has_catalyst` 100% false (news feed stale, Issue 2); `institutional_pct` ~75%
default; `ma_stack` ~66% neutral; EV ~58% default (fills over time as the v216
hook accrues closes). TQS grade-band recalibration (Task 1) should wait until
these settle.

---


## 2026-06-01 — v19.34.212 Chart coverage uses TRADING days (AIQ "70%" fix)

### Report
Operator did an overnight historical backfill but AIQ's chart still showed
"PARTIAL — 70% COVERAGE".

### Root cause (NOT missing data)
`hybrid_data_service.get_bars` computed `expected = calendar_days * 78` and
`coverage = len(bars)/expected`. `78` = 5-min bars in ONE RTH session, but it
multiplied by every CALENDAR day (weekends + holidays included). Only ~69% of
calendar days are trading days, so RTH-complete intraday data structurally
caps at ~70% and never reaches the 0.8 "full" threshold. Diagnostic confirmed
AIQ has 34,465 5-min bars, 434/443 days full RTH (the 8 "partial" days are
legit half-sessions — Thanksgiving Fri, Christmas Eve, July 3 = 42 bars), and
trading-day coverage = 98-101%.

### Fix
New `_trading_days()` (weekday count) + `_expected_bars(timeframe,...)` =
trading_days × per-session bar count (`1min`:390 `5min`:78 `15min`:26
`1hour`:7 `1day`:1). Coverage now `min(len/expected, 1.0)`. Also fixed the
same calendar-day bug in `_estimate_fallback_bar_count`. AIQ now reads ~100%.
Chart cache TTL is 30s (intraday) so charts self-heal within ~30s of restart.

### Tests — `backend/tests/test_v19_34_212_coverage_trading_days.py` (4/4)
Deploy: `deploy_v19_34_212.py` (paste.rs), idempotent, validated vs sandbox.

---

## 2026-06-01 — v19.34.211b Scoring dedupe (catalyst double-count fix)

`DynamicUniverseBuilder.build().add()` added points every time a source was
seen but de-duped only the source *tag*. Catalyst feeds (earnings/news) list
the same ticker multiple times → inflated scores (VSCO read 68 vs the correct
30). Fix: `add()` now counts each distinct source ONCE (skip points if the
source label is already present). Movers (dict-deduped per scan) and core
(unique list) unaffected. Tests: +2 (`test_duplicate_catalyst_counts_once`,
`test_earnings_plus_news_each_count_once`); 8/8 green. Deploy: backend-only
`deploy_v19_34_211b.py` (paste.rs), idempotent, validated vs sandbox.

---

## 2026-06-01 — v19.34.211a Gameplan Dynamic-Movers UI + UTC-date alignment

- **Frontend** (`GamePlanTab.jsx`): new collapsible **Dynamic Movers** panel —
  renders `gamePlan.dynamic_movers` (symbol + score + colour-coded source tags
  held/watchlist/catalyst/mover) with a regime chip and a **Refresh** button
  that calls `POST /api/dynamic-universe/rebuild` then reloads the plan.
- **Backend** (`dynamic_universe_builder._push_to_gameplan`): writes
  `dynamic_movers` to the **UTC-date** gameplan doc (matching
  `journal_router /gameplan/today`) so the panel always reads the right plan.
- Deploy: `deploy_v19_34_211a.py` (paste.rs) — 5 anchored edits, validated vs
  reverse-applied sandbox + idempotent. Frontend webpack-compiles clean;
  full app load verified.

---

## 2026-06-01 — v19.34.211 DYNAMIC UNIVERSE BUILDER (movers + catalysts + regime tilt)

### Why
v210 made the daily/premarket scans sweep the full ADV-ranked universe, but
that universe is static — it ignores *today's* actionable names. Operator
asked the scanner to (a) run the whole universe every day, (b) hit qualified
scalp/intraday names many times/day, and (c) surface today's movers/catalysts
into the live loop AND the game plan / briefings.

### What
New `services/dynamic_universe_builder.py` composes a **priority-ranked daily
scan universe** each premarket + every ~45 min intraday, persisted to the
`daily_scan_universe` Mongo collection (one doc per ET date):
- **Liquid core** — top-600 by ADV (`get_universe_ranked`, intraday tier).
- **IB movers** — `ib_service.run_scanner()` over TOP_PERC_GAIN/LOSE, GAP_UP/
  DOWN, MOST_ACTIVE, HOT_BY_VOLUME (fallback: `ib_data_provider`
  most-active). Gated to the qualified universe (ADV ≥ $2M).
- **Catalysts** — today's earnings + fresh-news tickers, gated to qualified.
- **Held + watchlist** — open `bot_trades` + operator manual pins, always in,
  top priority, exempt from the gate.
- **Regime tilt** — `market_regime_engine` state biases mover scoring
  (CONFIRMED_UP → gainers/gap-ups aligned, CONFIRMED_DOWN → losers/gap-downs).
- Per-source weights → `priority_score`; dedup + sort DESC; top-40
  `priority_symbols`. Graceful degradation — a failed source NEVER yields an
  empty universe.

### Consumption (wiring)
- `enhanced_scanner`: `_maybe_rebuild_dynamic_universe()` (TTL-gated) runs in
  the premarket + RTH loops; `_merge_dynamic_priority()` front-loads priority
  names ahead of the v210 rotation wave in both daily + premarket scans.
- `wave_scanner.get_scan_batch`: top priority names injected into **RTH
  Tier-1** (scanned every ~15s) so live scalps catch today's movers.
- Top findings pushed into today's game plan (`dynamic_movers` field) for the
  gameplan / briefings.
- New API: `GET /api/dynamic-universe`, `GET /api/dynamic-universe/priority`,
  `POST /api/dynamic-universe/rebuild`.

### Tests — `backend/tests/test_v19_34_211_dynamic_universe_builder.py`
6/6 passing: scoring + qualification gate, regime tilt (up/down), priority
selection (pure-core excluded, held top), graceful degradation (empty movers),
freshness/maybe_rebuild. Plus live smoke test on this env: all 3 endpoints +
`POST /rebuild` built a valid doc with live regime detection.

### Deploy
`deploy_v19_34_211.py` (paste.rs → curl): creates 2 new files + 9 anchored
edits across enhanced_scanner/wave_scanner/server.py, transactional with .bak
+ compile/import rollback, idempotent. Validated against a synthetic pre-v211
DGX sandbox (reproduces exact target state byte-for-byte). **Commit before
restart.**

---

## 2026-06-01 — v19.34.210 KILL ALPHABETICAL EXECUTION BIAS (liquidity-ranked universe rotation)

### Incident
Operator noticed freshly-opened positions (AMD, AMDL, ARW, BB, AIQ…) skewed
suspiciously alphabetical. `diag_alpha_bias.py` confirmed **93.9% of OPENED
positions started with A–E** and 59.7% of *generated alerts* were A–E.

### Root cause
`_scan_daily_setups` and `_scan_premarket_setups` selected symbols with
`sorted(get_universe(self.db, tier="intraday"))[:200]` / `[:300]`.
`get_universe()` returns an **unordered set**, so `sorted()` ordered it
**alphabetically** and the `[:N]` slice truncated to A–early-B names —
structurally hiding the entire late-alphabet universe from the daily/premarket
detectors. (RTH `wave_scanner.py` was already ADV-ranked and unaffected.)

### Patch
1. **`symbol_universe.py`** — new `get_universe_ranked(db, tier, *, limit)`:
   qualified symbols ordered by `avg_dollar_volume` DESC (most-liquid first).
2. **`enhanced_scanner.py`** — new `_next_universe_wave(offset_attr, tier,
   wave_size)`: rotating per-scan cursor over the ranked universe; wraps for
   full coverage in `ceil(N/wave)` cycles. Both daily + premarket scans now
   sweep the **investment tier** ($2M+, ~3,339 names — the full qualified
   universe, per operator request "run the whole universe every day") at
   wave=500, env-overridable via `SCAN_UNIVERSE_TIER` /
   `DAILY_SCAN_WAVE_SIZE` / `PREMARKET_SCAN_WAVE_SIZE`.
   - Daily scan (~every 2.5 min RTH) → full universe swept every ~7 cycles
     (~17 min); premarket (~4 min) → ~28 min; after-hours (~20 min).
   - RTH scalp/intraday (Tier-2 top-200 ≥$50M every 15s) + swing (Tier-3
     rotating ≥$10M, full sweep ~3.25 min) loop **left untouched**.

### Tests — `backend/tests/test_v19_34_210_liquidity_universe_rotation.py`
8/8 passing: ranked ordering is liquidity-DESC (ZZZZ before AAAA), tier
thresholds, unqualifiable exclusion, limit, + wave full-coverage / cursor
advance / wrap-around / empty-universe.

### Deploy
Idempotent anchor-script `deploy_v19_34_210.py` (paste.rs → curl) with .bak +
import-test rollback. Verified against a synthetic old-state DGX sandbox and
for idempotency. **Requires `git commit` before backend restart** (restart runs
`git checkout -- .`).

---

## 2026-06-01 — v19.34.209 OFFLOAD SYNC HTTP OFF THE EVENT LOOP (close-all hang + pusher stall)

### Incident
Operator hit "close all" in Open Positions; the UI hung and the IB pusher
appeared to disconnect. Log forensics (`/tmp/diag_close_incident.py`) showed
`⚠️ EVENT LOOP BLOCKED for 2.8s!` and `=== WEDGE WATCHDOG TRIGGERED (main thread
stuck for 5.0s) ===` with the stack at `requests.get(url, params=params,
timeout=10)`, plus `Failed to get Finnhub news for VIAV: Read timed out`.

### Root cause
Several `async def` enrichment methods called **synchronous** `requests.get(...,
timeout=10..20)` directly on the asyncio event loop (Finnhub news/earnings,
Finnhub fundamentals, FMP quality). When upstream was slow, each call froze the
ENTIRE loop for up to the full timeout. That single freeze caused BOTH symptoms:
the manual-close API couldn't be scheduled (UI hang), and the pusher + ib_direct
heartbeats (also on the loop) went stale (`pusher snapshot 85s old`,
`ib_direct disconnected` fallthroughs). The close-all just coincided with the
scanner's Finnhub enrichment burst on the same symbols.

### Fix
Wrapped all 11 blocking `requests.get` call sites in `await
asyncio.to_thread(requests.get, ...)` so the socket I/O runs in a worker thread,
off the loop. Behaviour-preserving; threading-only. Files: `news_service.py`
(2), `earnings_service.py` (3), `fundamental_data_service.py` (3),
`quality_service.py` (3). `weekend_briefing_service.py`'s `requests.get` are in
plain sync `def` helpers (already off-loop) — left as-is.
### Verify
- `tests/test_v19_34_209_no_loop_block.py` (2/2) — a 0.4s blocking get no longer
  stalls a concurrent 50ms heartbeat (loop stays responsive); guard test asserts
  no bare `= requests.get(` remains in the 4 modules.
- DGX live: during the next scan/close burst the wedge watchdog "EVENT LOOP
  BLOCKED" lines should stop appearing.

---


## 2026-06-01 — v19.34.208 APPLY SMB SCORE REGARDLESS OF SETUP CONFIG (v207 follow-up)

### Why (live verification of v207)
Post-restart `live_alerts` showed a real spread (squeeze/gap_fade/fashionably_late
= 30–43) BUT every `vwap_fade_long` / `vwap_fade_short` / `vwap_continuation`
alert was still exactly 25. Same-instant proof: VIAV `gap_fade`=42 while VIAV
`vwap_fade_long`=25 — so it was NOT missing data. Root cause: in
`populate_smb_fields`, the injected `smb_score` was applied INSIDE `if config:`,
and those directional/variant setup names resolve to NO registry config
(`get_setup_config("vwap_fade_long") is None`), so the entire block (style,
targets, SMB, earnings) was skipped → flat 25.

### Fix
- `services/enhanced_scanner.py` `LiveAlert.populate_smb_fields` — moved the
  `smb_score` + `earnings_score` application OUT of the `if config:` gate. The
  config block still sets trade_style/targets when a config exists; the SMB
  score now applies whenever the context carries a valid `SMBVariableScore`,
  for any setup_type.
### Verify
- `tests/test_v19_34_208_smb_no_config.py` (5/5) — asserts vwap_fade_long
  (no config) now applies a 38/50 score; gap_fade (has config) unchanged.
- DGX live: re-run `/tmp/verify_v19_34_207b.py` next session — vwap_fade /
  vwap_continuation alerts should now score >=28 instead of 25.

---


## 2026-06-01 — v19.34.207 SMB 5-VARIABLE SCORING WIRED INTO LIVE SCANNER (Setup-pillar de-starvation)

### Why
`smb_score_total` was a flat **25** for every alert. Root cause: the live
scanner's only call to `populate_smb_fields` (`enhanced_scanner._process_new_alert`)
built the context with just `{market_regime, tape_score}` — it **never passed an
`smb_score`**, so the `SMBVariableScore` branch was skipped and the dataclass
default 25 stuck. That flat 25 then fed the TQS Setup pillar's SMB component
(15% weight), collapsing the spread.

### Fix (Approach A — canonical 11-point checklist)
- `services/enhanced_scanner.py` — new `async _compute_smb_5var(alert)` maps the
  alert's `TechnicalSnapshot` + fire-time fields into the canonical 11-point SMB
  checklist (`scoring_engine.evaluate_smb_checklist`) and folds it into the
  5-variable score (`smb_unified_scoring.convert_checklist_to_smb_score`). The
  `_process_new_alert` SMB block now injects `smb_score` (+ `earnings_score`)
  into the context. Snapshot→checklist mapping: gap/rvol→catalyst+volume,
  ema9/ema20/ema50+price→trend+MAs, support/resistance→S/R+R:R+exit,
  vwap/prev_close→MTF, rs/change%→relative-strength, setup_type→proven-success,
  regime→sentiment. Fails safe to the old default on any error.
### Verify
- `tests/test_v19_34_207_smb_5var.py` (4/4). Canonical-path spread:
  STRONG=46/50 (A+), PARTIAL=38/50 (B+), WEAK=25/50 (baseline). No more flat 25.
- DGX live: `/tmp/verify_v19_34_207.py` checks `live_alerts/bot_trades`
  `smb_score_total` distribution at next scan session.

---

## 2026-06-01 — v19.34.205 + v19.34.206 INSTITUTIONAL OWNERSHIP (R4 — final TQS Fundamental pillar component)

### v205 — type-2-only sum (correct bucket)
IB `ReportsOwnership` groups holders by `<type>`; summing ALL types double-counts
(~2x shares-out → 100% everywhere). Sum ONLY `type==2` (13F investment advisors).
Also fetch `shares_outstanding` from ReportSnapshot for the denominator when not
cached. AMD validated at 75.5%.

### v206 — control-stake / stale-artifact exclusion
type-2 alone still over-counted for some names because IB's Refinitiv feed carries
stale **controlling-stake** rows (AB: `AXA Financial`=182% of shares-out; AAMI:
`HNA Capital`=64%) — divested parents far above any free-float 13F position.
`parse_reports_ownership` now EXCLUDES any single type-2 holder whose quantity
exceeds `max_single_holder_frac` (default **50%**) of shares-outstanding, then
caps at 100%. Records `excluded_control_holders` for observability.
### Verify (live IB)
- AMD 75.5% (unchanged), AB 100%→31%, AAMI 100%→67%. Cache spread after refresh:
  93 syms, mean 65.6%, range 1.1–100%, 61/93 in the 20–99% band (was 62/84 at 100%).
- `tests/test_v19_34_206_institutional_ownership.py` (8/8).
- **Known limitation (P2):** ~20 high-institutional large-caps (GS, MS, SBUX…)
  still hit the 100% cap due to intra-type-2 parent/child overlap (e.g. "BlackRock
  Inc" + "BlackRock Fund Advisors" both filing, each <50%). Directionally correct;
  de-saturating needs fragile entity-name dedup → deferred.

---


## 2026-06-02 — v19.34.202 IB-SOURCED FUNDAMENTALS: FLOAT + SHORT-INTEREST% (R2+R3)

### Why (IB probe proof)
`probe_ib_fundamentals.py` (clientId 77, read-only) confirmed the operator's IB
account DOES serve Reuters fundamentals, and that **ReportSnapshot (~10KB)
already carries float + shares-outstanding**:
    <SharesOut Date="2026-04-29" TotalFloat="1623871179.0">1630600639.0</SharesOut>
→ shares-out = element text, float = `TotalFloat` attr. (ReportsOwnership also
works but is 3.6 MB/symbol — too heavy for per-symbol cache fills; institutional
ownership R4 deferred to a low-cadence job.)

Also confirmed the legacy `ib_service` fundamentals path is dead on this deploy
(every cached doc historically `source=finnhub`) → fundamentals must route
through the LIVE `ib_direct` clientId-11 socket.

### Fix
- `services/ib_direct_service.py` — new `get_fundamental_report(symbol,
  report_type="ReportSnapshot")` via `reqFundamentalDataAsync` on the live
  socket (mirrors the `get_contract_industry` guard pattern; 20s timeout).
- `services/ib_fundamentals_parser.py` — `parse_report_snapshot` now extracts
  `shares_outstanding` (`<SharesOut>` text) + `float_shares` (`TotalFloat` attr).
- `services/unified_fundamentals_cache.py`:
  * IB step now prefers `ib_direct` ReportSnapshot (legacy ib_service kept as a
    fallback only if ib_direct is down) → fills `float_shares` (**R3**).
  * New short-interest step: `short_interest_percent = FINRA short shares ÷ IB
    shares-outstanding` via `ShortInterestService.get_short_data_for_symbol`
    (**R2**). FINRA is bi-monthly — the accurate cadence for short interest.
  * New pure helper `compute_short_interest_pct()` (unit-tested).

### Verify
- `backend/tests/test_v19_34_202_ib_fundamentals.py` — 5/5 pass (SharesOut/Float
  parse from real AMD XML, missing-SharesOut safe, SI% math + guards). Lint clean
  on changed regions; all 3 services import OK.
- ✅ VERIFIED LIVE ON DGX (2026-06-01, commit 8f2a9d3b): cleared cache + forced
  in-backend fetch via `/api/tqs/breakdown/{sym}` for AMD/AVGO/ALAB →
  `source=ib_direct_report_snapshot+finnhub+finra_short`, with real
  `float_shares` (AMD 1.62B, AVGO 4.64B, ALAB 153M) and `short_interest_percent`
  (AMD 1.98, AVGO 1.11, ALAB 7.89). The IB ReportSnapshot fetch ONLY fires inside
  the backend process (where the live clientId-11 socket lives) — a standalone
  script has no IB connection and correctly falls back to Finnhub.
- NOTE: the 174 pre-existing cache docs backfill on their own 24h TTL (or force a
  symbol with `verify_v19_34_202.py`).

### Still ahead (this pillar)
R0 earnings_calendar persistence (Finnhub free, 15%), R4 institutional ownership
(IB ReportsOwnership — low-cadence job, 15%).

---


## 2026-06-02 — v19.34.201 FUNDAMENTAL PILLAR: CATALYST/NEWS WIRING (the 30% lever)

### Why (live diag proof)
`diag_fundamental_sources.py` on the DGX confirmed the fundamental pillar's
biggest component — **catalyst (30%)** — was permanently stuck at the
"no catalyst" floor of **40**. Root cause: `tqs_engine.set_services()` only
passed `ib_service` to the fundamental pillar, **never `news_service` or `db`**,
so `FundamentalQualityService._news_service`/`._db` were always None. The
pillar's news + earnings-calendar lookups were dead code → catalyst always 40,
contributing to the flat ~57 fundamental score on every trade.

The probe also proved `news_service.get_ticker_news()` IS alive (Finnhub
company-news + IB news, carries a `sentiment` STRING bullish/bearish/neutral).

### Fix
- `services/tqs/tqs_engine.py` — `set_services()` + `init_tqs_engine()` now
  accept and propagate `news_service` + `db` into the fundamental pillar.
- `server.py` — passes the live `news_service` + `db` into `init_tqs_engine`.
- `services/tqs/fundamental_quality.py`:
  * **News→catalyst enrichment** in `calculate_score`: when the caller didn't
    supply catalyst data and `_news_service` is wired, fetch recent ticker
    news (last 72h, placeholder items excluded), map the sentiment STRING to a
    float (bullish→+1 / bearish→−1 / neutral→0), average it, and route through
    the existing `has_recent_news` branch → catalyst score 50–85 instead of 40.
  * **Latent crash fixed**: `if self._db:` (pymongo `bool(Database)` raises
    `NotImplementedError` per AGENTS.md §6) → `is not None`; and
    `self._db.get("earnings_calendar")` (invalid on Database) → `self._db[...]`.
    These were dormant only because `_db` was always None; wiring it would have
    crashed the pillar without this fix.

### Verify
- `backend/tests/test_v19_34_201_fundamental_news_wire.py` — 5/5 pass (bullish
  lifts catalyst >floor, no-news-service keeps floor, placeholder ignored,
  bearish supports short, explicit caller args override news). Lint clean;
  `server.py` compiles. (Live-server `test_tqs_*_integration` failures in the
  sandbox are pre-existing — empty `REACT_APP_BACKEND_URL`, not this change.)
- ⚠️ OPERATOR LIVE-CHECK after restart: fundamental pillar's catalyst component
  should move off a flat 40 for symbols with recent news; re-run
  `diag_tqs_pillars.py` to confirm fundamental scores start spreading.

### Still ahead (this pillar)
R2 short-interest% (FINRA shares ÷ derived shares-out), R3 float, R0 earnings
persistence, R4 institutional (IB ReportsOwnership). News is the biggest single
lever and ships first.

---


## 2026-06-02 — v19.34.200 NIGHTLY learning_stats REBUILD (TQS setup-pillar data feed)

### Why
The TQS **setup pillar** reads `get_contextual_win_rate(setup_type=base)` from
`learning_stats`. That collection was sitting EMPTY despite a backlog of
`trade_outcomes` (the incremental `run_daily_analysis` path only aggregates
*today's* `reviewed:False` rows and wasn't persisting history). With no row,
the pillar defaults to `win_rate=0.5` → score 50 → TQS compresses into the "C"
band → every trade sized at ~0.30×. This is **data starvation, not weighting**
(STYLE_WEIGHTS are horizon-aware and correct — do NOT rebalance them).

### Fix
- `services/learning_loop_service.py`
  * New pure aggregator `_compute_learning_stats(context_key, outcomes)` —
    reads outcome dicts directly (stored docs are flatter than
    `TradeOutcome.from_dict` expects, which silently zeroed stats). Writes the
    exact fields the pillar reads (`win_rate`, `expected_value_r`,
    `total_trades`) + extras. Shared 1:1 with the manual backfill script.
  * New `async rebuild_learning_stats_from_all_outcomes()` — full, idempotent
    rebuild from ALL `trade_outcomes`, grouped by the NORMALIZED setup key the
    pillar queries (`lower().replace("_long","").replace("_short","")`).
    Upserts by `context_key`. Returns # contexts written.
- `services/trading_scheduler.py`
  * New nightly job `learning_stats_rebuild` @ **5:30 PM ET** →
    `_run_learning_stats_rebuild()`. Keeps the setup-pillar feed fresh so TQS
    spreads honestly over time.
  * `run_task_now("learning_stats_rebuild")` on-demand trigger wired (exposed
    via `POST /api/scheduler/run/learning_stats_rebuild`) so the operator can
    refresh without waiting for 5:30 PM.

### Verify
- `backend/tests/test_v19_34_200_learning_stats_rebuild.py` — 5/5 pass
  (win-rate/EV/PF math, all-losses, breakeven excluded from WR denominator,
  empty, bad/missing fields). Lint + syntax clean.
- ⚠️ OPERATOR LIVE-CHECK after deploy+restart: hit
  `POST /api/scheduler/run/learning_stats_rebuild` (or wait for 5:30 PM ET),
  then confirm `learning_stats` is populated and the setup pillar starts
  spreading off a flat 50. **Effect is forward-looking** (only new trades
  scored after the rebuild see the richer win-rate feed).

---


## 2026-06-01 — v19.34.199 RESTORE-PATH GRADE HYDRATION (honest TQS grade)

### Root cause (found via diag_sizing_provenance.py on live DGX)
Open swing trades (power_trend_stack / stage_2_breakout / pocket_pivot) showed
`unified_grade`/`tqs_grade` = EMPTY despite `entry_context.tqs.unified_grade`
being populated (C/C+). The card's `unifiedGrade()` then fell back to the legacy
`quality_grade` (B) and **labeled it "TQS B" — when real TQS was C/C+.**

`restore_open_trades` (the active boot restorer in bot_persistence.py)
constructs BotTrade from a HARDCODED field subset that omits
unified_grade/tqs_grade/tqs_score. So every restart returned multi-day trades
with empty grades, and the periodic persist then overwrote the DB (incl. the
v175 backfill) with those empties. New trades (created in-session) were fine;
only RESTORED trades lost the grade.

### Fix — `services/bot_persistence.py`
- New pure resolver `resolve_restore_grades(trade_doc, entry_context)` mirroring
  the v175 backfill priority: top-level field → `entry_context.tqs.unified_grade`
  → `post_gate_grade` → (unified only) legacy `quality_grade`.
- `restore_open_trades` now calls it after restoring `entry_context`, so the
  REAL TQS grade survives restarts and the UI label is honest (sizing already
  used the right TQS grade — this fixes the record + label only).
- Tests: `tests/test_v19_34_199_restore_grades.py` (6 cases incl. the exact
  swing-trade C+ derivation + reconciled "R" fallback). All green.

### Diagnostics added (read-only)
- `scripts/diag_sizing_provenance.py` — per-open-trade multiplier chain, sizing
  vs displayed stop, budget-vs-realized risk. Proved sizing is CORRECT (TQS-C
  trades sized at 0.30× as designed) and that "B sized as C" was a label bug,
  not a sizing bug.
- `scripts/diag_tqs_distribution.py` — TQS score/grade histogram + legacy-vs-TQS
  label divergence + per-setup mean TQS, to test whether TQS compresses into the
  C band.

### NOTE: NOT a sizing change
The earlier "Fix 1" (fall back to quality_grade in the sizer) was REJECTED after
the diagnostic proved these are genuinely TQS-C/C+ trades. Inflating them to B
size would resurrect the exact lenient-grade double-count v175 removed. Sizing
left untouched.

---

## 2026-06-01 — v19.34.198 SESSION-AWARE CHART CACHE TTL (5 PM ET rollover)

### Context
Operator set `CHART_CACHE_TTL_INTRADAY_S=28800` (8h) so same-session chart
revisits are instant (2ms cache hit + chart-tail WS backfill). Risk of a flat
8h TTL: an entry cached late in the session would bleed the closing-print
skeleton into the evening and the next premarket open.

### Fix — `services/chart_response_cache.py`
- New `_seconds_until_session_rollover(now, rollover_hour_et=17)` helper.
- `chart_cache_ttl_for(timeframe, now=None)` now CLAMPS the intraday TTL so an
  entry never outlives the next **5 PM ET** rollover. Same-session revisits stay
  instant; each new session rebuilds fresh. Examples (base 8h):
  10:00 ET → 7h · 3:55 PM → 1h · 4:30 PM → 30m · post-5 PM → full 8h.
- Floor of 30s prevents TTL=0 right at the boundary. Daily TTL untouched.
- Env: `CHART_CACHE_ROLLOVER_HOUR_ET` (default 17), `CHART_CACHE_SESSION_AWARE`
  ("false" disables the clamp → flat base TTL).

### Widen pre-warm — `routers/sentcom_chart.py`
- `POST /chart/warm` defaults: timeframes `["5min"]` → `["1min","5min","15min"]`;
  symbol cap 32 → 48. A single warm call now primes the operator's intraday set.

### Tests
- `tests/test_v19_34_198_session_aware_ttl.py` — 7 tests (rollover math, clamp,
  base-when-far, daily-never-clamped, disable flag, custom hour, zero floor).
- `tests/test_v19_34_197_chart_cache_ttl.py` — pinned `CHART_CACHE_SESSION_AWARE=false`
  so the base-TTL contract stays deterministic. **11/11 passing** locally.

### Deploy
`paste.rs` idempotent script `deploy_v19_34_198.py` (patch → pytest → git
commit+push → restart prompt). Dry-run verified: patches apply, 11 green,
2nd run fully idempotent (all skip).

---

## 2026-?? — v19.34.197 CHART COLD-LOAD LATENCY FIX (18-21s → ~3s)

### Diagnosis (read-only diag_chart_latency.py on the live DGX)
Cold INTRADAY `/chart` loads measured **18,000-21,000 ms**; daily was <300ms.
NOT payload (~85KB / 245 bars) and NOT Mongo (`get_bars` fast — daily proves
it). Root cause: the per-miss live pusher-RPC merge (`fetch_latest_session_bars`
→ `rpc.latest_bars`, an on-demand IB historical request for quote-subscribed
symbols) blocked the whole chart load with NO timeout. Daily skips the merge →
fast. Cache works (warm = 1-4ms) but the 30s intraday TTL + warm-only-top-12
meant most clicks were cold misses paying the full 18s.

### Fix
- `routers/sentcom_chart.py` — TIME-BOUND the merge with
  `asyncio.wait_for(CHART_LIVE_MERGE_TIMEOUT_S, default 3.0s)`. On timeout serve
  the historical window immediately; the chart-tail WS/poll backfills the live
  bars within ~5s, and the slow RPC still warms `live_bar_cache` for the next
  load. Cold worst case 18-21s → ~3s.
- `services/chart_response_cache.chart_cache_ttl_for` — env-tunable; intraday
  default 30s → 60s (`CHART_CACHE_TTL_INTRADAY_S` / `CHART_CACHE_TTL_DAILY_S`)
  to halve cold-miss frequency. Safe because the WS tail keeps the chart live.

### Verify
4/4 tests (`test_v19_34_197_chart_cache_ttl.py`); py_compile + ruff clean.
Deploy paste.rs `00uTK` (patch `SDNl1`). ⚠️ Operator: after restart re-run
`diag_chart_latency.py` — cold intraday should drop ~18s → ~3s.

---

## 2026-?? — v19.34.194–196 QUALITY GATE + DUAL TIMESTAMPS + OPERATOR FORCE-FLATTEN

Three operator-requested features (each with passing pytest; deploy wrapper
`https://paste.rs/a3R1H`, patch `https://paste.rs/FKfax`):

### v19.34.194 — $BIL quality gate (volatility floor + cash-equivalent blocklist)
`services/opportunity_evaluator.py` — two env-tunable hard gates early in
`evaluate_opportunity` (both fail-OPEN, drops logged via `record_rejection`):
  * `CASH_EQUIVALENT_BLOCKLIST` (default: BIL,BILS,SGOV,SHV,SHY,ICSH,… T-bill /
    ultra-short ETFs) → reason `cash_equivalent_blocklist`.
  * `MIN_TRADE_ATR_PCT` daily ATR% floor (FRACTION; default 0.003 = 0.3% — below
    SPY/QQQ ~0.7-1.4% so index ETFs pass, but catches $BIL ~0.1%). ATR% sourced
    from alert atr/price, else `symbol_adv_cache.atr_pct`. 0 disables; blocks
    ONLY when a measurement exists. Stops ultra-low-vol tickers becoming trades
    (the BIL R:R 0.02 incident). 6/6 tests.

### v19.34.195 — dual-shape timestamps on bot_trades + shadow_decisions
`bot_persistence.persist_trade` + `save_trade` and `shadow_tracker.log_decision`
now stamp `ts` (ISO) + `ts_dt` (BSON), anchored to `created_at` (stable across
updates), via `utils/timestamps.stamps()`. Completes the v172 normalization;
prevents silent cross-collection query misses. 4/4 tests.

### v19.34.196 — operator force-flatten orphaned IB positions by symbol
New `POST /api/trading-bot/positions/{symbol}/flatten` (`routers/trading_bot.py`)
— reads the live IB position via ib_direct, cancels every working order for the
symbol (clears OCA brackets that trip IB's 15-order cap), then sends a MKT to
flatten the net position. Operator-initiated → bypasses the post-stop cooldown.
The V5 `CloseTradeModal.jsx` now detects orphan rows (no `trade_id`), shows an
amber "Orphaned IB position" banner + "Force-flatten <SYM>" button, and routes
to this endpoint instead of erroring "Missing trade_id". 6/6 tests.

### Verify (hardware-bound — manual, NOT testing agent)
16/16 new tests pass; py_compile + ruff + eslint clean. Frontend hot-reloads.
⚠️ Operator: after deploy+restart, watch `/tmp/backend.log` for the v194 gate
logs, confirm new docs carry `ts`/`ts_dt`, and test Force-flatten on an orphan.

---

## 2026-?? — v19.34.193 SCANNER UNIVERSE-COVERAGE HARDENING (alphabetical A/B-only bug)

### Context (operator: "all Friday trades were A/B/C symbols")
A read-only coverage diagnostic proved the bot was blind to ~9,150 of ~9,400
symbols. Root cause chain:
  * The weekly ADV scheduler (`server.py`, Sundays 10 PM ET) called the legacy
    `scripts/recalculate_adv_cache.py`, which `delete_many()`'d
    `symbol_adv_cache` and rewrote 9,200 docs with ONLY `avg_volume` (share
    count) and NO `avg_dollar_volume`.
  * The wave-scanner ranks tier2/tier3 by `avg_dollar_volume >= $50M / $10M`,
    so both pools collapsed to 0 (`tier2_pool_size=0`, `tier3_roster_size=0`).
  * With tiers 2/3 empty, the scanner silently degraded to the 50-symbol
    ALPHABETICAL fallback watchlist → every trade an A/B name, every Sunday.

### Immediate data repair (operator-run, no code)
`POST /api/ib-collector/rebuild-adv-from-ib` → rebuilt 9,412 symbols with
`avg_dollar_volume` + ATR% + tier (intraday 1,145 / swing 844 / investment 507).

### Code fix (this patch — prevents recurrence)
- `server.py::_run_adv_recalc` now calls the CANONICAL
  `IBHistoricalCollector.rebuild_adv_from_ib_data()` (writes
  `avg_dollar_volume`+`atr_pct`+`tier`) instead of the footgun script.
- `scripts/recalculate_adv_cache.py::recalculate_adv_cache()` is DISABLED
  (raises `RuntimeError`, no `delete_many`) so a manual run can't wipe it.
- `services/wave_scanner.py`:
    * self-heals its db handle (`get_database()`) if a db-less singleton
      slipped through the init race;
    * BYPASSES the 10-min TTL while pools are empty (fast self-heal right after
      a rebuild — no 10-min blind window);
    * on the wipe signature (docs exist, 0 match `avg_dollar_volume>=$10M`)
      raises a LOUD alarm and falls back to an `avg_volume`-ranked liquid set —
      NEVER collapses to alphabetical again.

### Verify
- `backend/tests/test_v19_34_193_scanner_coverage_hardening.py` — 5/5 pass
  (healthy ADV-rank, broken-cache→avg_volume fallback non-alphabetical,
  empty-pool TTL bypass, populated-pool TTL honored, footgun disabled).
- py_compile + ruff clean.
- Deploy: paste.rs wrapper `https://paste.rs/Ksyzp` (patch `https://paste.rs/O6DNk`).
- ⚠️ OPERATOR LIVE-CHECK after restart (~90s): `tier2_pool_size ~200`,
  `tier3_roster_size ~1989`, live subs ADV-ranked (not all A/B).

### Diagnostics created
`/tmp/diag_scan_coverage_v19_34_193.py`, `/tmp/diag_adv_cache_fields_v19_34_193.py`.

---

## 2026-02-?? — v19.34.192 EOD/CLOSE BRACKET-CANCEL VIA IB_DIRECT (master clientId 11)

### Context (recurring P0 — EOD MKT-close deadlock)
At 15:45 ET EOD, `close_at_eod=True` positions repeatedly failed to flatten with
`bracket_cancel_timeout_race_risk`, and cross-session DAY/GTC bracket children
threw IB `10147 OrderId not found`. Root-caused in the close path:
`_cancel_ib_bracket_orders` dispatched its cancels through
`routers.ib._ib_service.cancel_order()` — the legacy `IBService` worker thread,
which on this DGX deployment is the **stale/disconnected** direct-ib_insync
worker (PRD v170) serialized on a 1-worker queue. The cancel never reached IB
before the 8s+5s terminal-wait expired → every close aborted. The throttle is
NOT a deliberate IB-pacing safeguard (IB's real limit is ~50 msg/s); it is an
unintended stale+serialized bottleneck.

### Fix (`services/trade_executor_service.py`, safety-critical path — dispatch only)
- New `_dispatch_bracket_cancel_v192(oid, symbol)` routes the cancel through the
  DGX-native `ib_direct` socket (IB Gateway **Master API client ID = 11**,
  v19.34.190). `ib_direct.cancel_order` cancels via the **live order OBJECT**
  (which carries `permId`) looked up from the `_ib.trades()` cache that
  `_fetch_live_open_order_ids` freshly populates via `reqAllOpenOrders`
  immediately before the loop. Master clientId 11 lets clientId-11 cancel
  cross-session orders → dodges `10147`.
- Both the primary cancel loop and the v19.34.73 retry loop now use the helper.
- Legacy `IBService` retained ONLY as a fallback (ib_direct down/None) so a
  cancel is never silently dropped.
- **The OCA-race contract is UNTOUCHED**: the 8s primary + 5s retry
  terminal-wait, the filled/timeout abort, and the v189 fresh-openorders
  re-check all remain exactly as before. Only the cancel TRANSPORT changed.

### Verify
- `backend/tests/test_v19_34_192_eod_cancel_dispatch.py` — 6 tests, all pass
  (prefers ib_direct; falls back on failure / None / disconnected; no-transport
  returns False; `_cancel_ib_bracket_orders` routes through the helper).
- `py_compile` clean. (7 adjacent failures in v189/v191/70a/v40 suites are
  PRE-EXISTING stale-mock / sandbox-env artifacts — confirmed identical with the
  patch stashed; not introduced here.)
- Deploy: paste.rs wrapper `https://paste.rs/orhz4` (patch `https://paste.rs/8CZIM`)
  — applies, runs the test, commits+pushes BEFORE restart.
- ⚠️ OPERATOR LIVE-CHECK (15:45 ET): grep `/tmp/backend.log` for
  `v19.34.192 eod-cancel ... via ib_direct (master clientId 11, permId-aware)`;
  every `close_at_eod=True` position flat by 15:59:30, NO
  `bracket_cancel_timeout_race_risk` aborts.

---

## 2026-02-?? — v19.34.191 EOD SUPERVISOR CRASH HARDENING

### Context
During a 16:00 ET EOD auto-close while IB Gateway was wedged, two P0 Python
bugs surfaced in the scan/EOD loop:
1. **PyMongo `bool(Database)` crash** — `NotImplementedError: Database objects
   do not implement truth value testing`, raised by `<Database> or <Database>`
   and `if <Database>:` checks.
2. **`_broadcast_event` AttributeError** — the method was dropped during the
   unified-stream migration, leaving ~9 EOD/orphan HUD call sites raising
   (swallowed) AttributeError → HUD banners silently dead.

### Changes
- **BUG 1 (17 sites, 6 files):** Replaced every `bool(Database)` truthiness
  trap with explicit `is not None` / `is None` checks and None-safe ternaries.
  - `position_manager.py` (1× `or`-pattern, 6× `if bot._db:`, 1× `if not bot._db:`)
  - `opportunity_evaluator.py` (4× `or`-pattern)
  - `position_consolidator.py` (2× `or self.db`)
  - `position_reconciler.py` (1× `or`-pattern)
  - `dynamic_risk_engine.py` (1× `if not self._db:`)
  - `simulation_engine.py` (1× `if bars and self._db:`)
- **BUG 2:** Restored `TradingBotService._broadcast_event` as a thin shim that
  maps the legacy `{"type", "timestamp", **extra}` payloads onto
  `emit_stream_event` (kind=`alert` for alarm/critical/blocked, else `system`;
  auto-humanized text line; extra fields → `metadata`). All 9 call sites work
  unchanged.

### Verify
- `backend/tests/test_v19_34_191_eod_crash_hardening.py` — 7 tests, all pass
  (NoBool sentinel proves truthiness fix; shim payload mapping + severity +
  bad-input safety).
- `py_compile` clean on all 7 touched files. Grep confirms zero residual
  `or`-on-Database or bare `if (bot|self)._db:` patterns.
- Deploy: paste.rs wrapper `https://paste.rs/Ew8Zg` (patch `YZ9CI`, test
  `vUsBm`) — commits+pushes before restart.

---

## 2026-05-29 — v19.34.190 MASTER-CLIENTID STARTUP GUARD + RUNBOOK

### Context
Follow-up to the CF/BAP close saga: the real fix for orphaned-bracket
cancellation was the IB Gateway **"Master API client ID = 11"** setting (lets
clientId-11 cancel cross-session/prior-process orders). That setting lives in
the Gateway's `jts.ini` on the Windows box — NOT in this repo — so it's lost on
a Gateway reinstall. Nothing to hardcode in the bot (it already connects as
`IB_DIRECT_CLIENT_ID`, default 11); we just lock it in with docs + a guard.

### Changes (additive, logging + doc only — zero trading-path impact)
- `services/ib_direct_service.py` — on every IB connect, compare `client_id`
  against `IB_EXPECTED_MASTER_CLIENT_ID` (default 11). Loud **WARN** if they
  differ ("bot may be UNABLE to cancel orphaned/cross-session brackets → IB
  10147"); calm **INFO** confirming master authority when they match.
- `memory/runbooks/ib_gateway_master_clientid.md` (NEW) — documents the
  required Gateway setting, the two in-sync values (`IB_DIRECT_CLIENT_ID` ↔
  Gateway Master API client ID), the symptom signature (10147 +
  PendingCancel→Submitted flap), and the re-set steps after any Gateway
  reinstall.

### Verify
`grep -iE 'v19.34.190|clientId=' /tmp/backend.log | tail -5` → expect
"clientId=11 matches documented master — cross-session/orphaned-order cancels
enabled". Compile-checked; the two E702 lint hits are pre-existing legacy.

---



## 2026-05-29 — v19.34.189 CLOSE-GUARD AUTHORITATIVE OPEN-ORDERS FIX

### Bug (operator-reported: BAP/CF wouldn't close)
Clicking **Close** aborted with `bracket_cancel_timeout_race_risk` and the
position never closed. Root-caused live on the DGX:
- The v19.34.64 OCA-race guard waits for each bracket child to reach a
  terminal status before sending the MKT close. Its v19.34.70A pre-filter
  partitioned tracked child orderIds against **`_ib.trades()`** — an
  in-memory CACHE.
- That cache (a) freezes an order's status at disconnect and is **never
  purged on socket-reconnect**, and (b) cannot be marked terminal by this
  client's error handler when the order was placed under a **different
  clientId** (the pusher) — `ib_async` keys `self.trades[(clientId, oid)]`,
  so the `cancelOrder→Error 10147 "not found"→auto-Cancelled` path misses.
- Net: orders already dead at IB showed as `Submitted`/`PreSubmitted`
  forever → `wait_for_orders_terminal` timed out → **every** close (manual
  + manage-loop) aborted. Confirmed: after a full backend restart (fresh IB
  object) BAP's cancelled orders vanished from the audit, proving stale cache.

### Fix (`services/trade_executor_service.py`, safety-critical path)
- New `_fetch_live_open_order_ids()` — AUTHORITATIVE set of orderIds open at
  IB across all clients via a fresh `reqAllOpenOrders` round-trip. Returns
  `None` on any failure (conservative: caller keeps the block-and-confirm path
  so flip-protection is never weakened on a transient query error).
- New pure `_partition_oids_by_live_set(oids, live_ids)` → `(present, gone)`.
- `_cancel_ib_bracket_orders` now pre-filters against the FRESH set (was the
  stale cache): children NOT in IB's live open-orders are `gone` → safe
  (`unknown`), skipped. Added a **post-wait** re-check too: any child that
  times out but is absent from a fresh `reqAllOpenOrders` is reclassified
  timeout→safe (catches OCA siblings IB auto-cancels mid-wait).
- Genuinely-live brackets still appear in the fresh set → still cancelled +
  confirmed before close → the 2026-05-20 direction-flip protection is intact.

### Verification
- 7/7 unit tests (`test_v19_34_189_close_guard_authoritative_orders.py`):
  partition contract (all-live/all-dead/mixed/empty) + fresh-fetch fallback
  (set / None-on-disconnect / None-on-exception). Backend compiles; lint clean
  (the one E722 is pre-existing legacy). No automated agent (hardware-bound).
- ⚠️ OPERATOR LIVE-CHECK: with TWS closed + bot connected, click Close on a
  stuck position; `grep 'v19.34.189 fresh-openorders' /tmp/backend.log`.

---



## 2026-05-30 — v19.34.188 MISSION CONTROL LIFECYCLE EMITS + INLINE SAFETY ACK

### What
Completes the Mission Control observability follow-ups noted in v19.34.184:
the live cockpit now shows the *whole* position-management + execution
lifecycle, and the operator can acknowledge a safety alarm inline (no tab
switch). (Re-tagged from a v19.34.186 collision with the BBAI tick-rounding
patch — see operator request.)

### Backend — new lifecycle emits (all fire-and-forget, never block the path)
- `services/stop_manager._record_stop_adjustment` — single chokepoint for
  trailing + breakeven + activation moves → emits **`stop_to_breakeven`**
  (Position lane, success) or **`trailing_stop_moved`** (Position lane, info).
- `services/trade_execution` — emits **`order_submitted`** (Execution lane)
  right before `place_bracket_order` so the operator sees intent before fill.
- `services/trade_executor_service` (partial branch) — emits **`partial_fill`**
  (Execution lane) with filled/remaining qty.
- All four classify into the correct lane in `stream_bus.classify_lane`
  (verified — no router change needed).

### Frontend — inline safety acknowledge
- `components/missioncontrol/SafetyRow.jsx` (NEW) — System/Safety strip row:
  alarm rows get an **"Ack + Unlock"** button → `POST /api/safety/reset-kill-switch`
  (the real operator re-arm), plus a local **dismiss (×)**. Non-alarm rows just
  render + dismiss.
- `pages/MissionControlPage.jsx` — System/Safety strip now renders `SafetyRow`
  (was the plain `StreamRow`), with a locally-dismissed-id set so muted rows
  stay hidden. Header count reflects visible (non-dismissed) rows.

### Verification
- 4 new lane-contract tests (`test_v19_34_188_lifecycle_emit_lanes.py`) +
  14 existing stream-bus tests = 18/18 pass. Both backend + frontend lint clean;
  all 3 backend services compile.
- Frontend mounts cleanly: `mission-control-page` + `mc-system-strip` testids
  present (no live data in the sandbox — connects live on the DGX). No automated
  testing agent per AGENTS.md (hardware-bound).
- ⚠️ OPERATOR LIVE-CHECK (RTH): open Mission Control — Execution lane should show
  `order_submitted` / `partial_fill`; Position lane should show stop→breakeven /
  trailing moves; trip + reset a kill-switch alarm via the inline "Ack + Unlock".

---



## 2026-05-30 — v19.34.185 F-F: GAMEPLAN-AWARE PRIORITIZATION (+ premarket gameplan scheduler)

### Why
The premarket Gameplan and the live bot were disconnected — the bot ranked
alerts purely on TQS/priority and ignored the operator's pre-open prep. Goal:
let the Gameplan softly steer slot allocation. **Accuracy pre-flight (audit)
revealed** the gameplan was only generated ON-DEMAND (when the journal tab is
opened) → today's plan was intraday-generated, all `live_scanner`, Neutral
bias. Boosting that would be circular. So F-F needs a stable PREMARKET plan
first.

### Part A — Premarket gameplan generation (data foundation)
`eod_generation_service`: new scheduled job **09:00 ET, Mon–Fri** that
FORCE-regenerates today's `game_plan` before the open (`delete_one` + 
`create_game_plan(auto_populate=True)`). At 09:00 the scanner buffer holds the
real conviction names — `pm_` premarket gappers + swing/position daily setups —
so `stocks_in_play` becomes genuine pre-open prep (`premarket_scanner` /
`daily_scanner` sources) and stays stable all session.
- New: `auto_generate_premarket_gameplan(date)`; logged via `_log_generation`.

### Part B — F-F soft conviction boost
`trading_bot_service._get_trade_alerts._alert_rank` (the v179 quality slot
ranker): TQS dimension now gets a mild, env-tunable additive boost:
- **+`GAMEPLAN_WATCHLIST_BOOST`** (default 8) if the symbol is on today's
  premarket/daily gameplan watchlist.
- **+`GAMEPLAN_BIAS_BOOST`** (default 4) if direction aligns with `market_bias`
  (long when Bullish / short when Bearish; nothing when Neutral).
- **Ranking-only**: never changes the stored TQS grade or any gate decision;
  the priority bucket still dominates (a low-priority gameplan name can't jump
  a high-priority non-gameplan one). A clearly-better non-gameplan setup
  (≥ boost higher TQS) still wins the slot.
- New helpers: `_compute_gameplan_boost` (static, pure) + `_get_gameplan_conviction`
  (reads only premarket/daily-sourced names + bias, cached ~5 min so the 09:00
  regeneration is picked up same session).

### Verification
- 11 F-F unit tests (watchlist hit, bias align/misalign, neutral, stacking,
  case-insensitivity, tunable-to-zero, mild-additive ranking effect). 51/51
  across v179/v182/v183/v184/v185 — no regressions. Both services compile.
- ⚠️ LIVE CONFIRMATION REQUIRED TOMORROW AM: after deploy + restart, the 09:00
  ET job runs; re-run the F-F audit (paste.rs/Npujw) → it should show
  "generated PREMARKET ✅" with `premarket_scanner`/`daily_scanner` names in
  stocks_in_play. ONLY THEN is the boost operating on real conviction data.
  (Today's intraday plan = nothing meaningful to boost yet.)
- Tunable kill-switch: set `GAMEPLAN_WATCHLIST_BOOST=0` and
  `GAMEPLAN_BIAS_BOOST=0` to disable the boost entirely.

---



## 2026-05-30 — v19.34.184 MISSION CONTROL (live multi-lane pipeline cockpit)

### What
A new top-level **Mission Control** tab: a live, always-on "cockpit" that
streams the bot's decision bus into 5 lanes — **Scanner | Gates | Execution |
Position | Reconciler** — plus a **System/Safety** strip, a heartbeat pip,
AGGREGATE/RAW scanner mode, severity filters, and click-through to a symbol's
recent-decision drawer.

### Why this design (coverage audit drove it)
A `sentcom_thoughts` audit over 7d showed the event bus already captures the
whole pipeline (~362k events), so we **reuse the existing bus** instead of
building a parallel system. Key finding: the **Scanner lane is a firehose**
(~324k `scanner_skip`/7d, peak ~600 events/min), NOT thin. So the architecture
centers on throttling that volume, not adding events.

### Performance (the operator's explicit concern: "will B slow the app?")
No — the trading hot path is untouched:
  • `StreamBus.publish()` is **synchronous, allocation-cheap, never awaits/sends**
    — a background ~300ms flush loop does the per-connection send.
  • **Zero idle overhead**: when no client is connected, `publish()` early-returns
    (after cheaply bumping the scanner roll-up counter).
  • **Scanner firehose handling (hybrid)**: in `aggregate` mode skips/rejects are
    NOT buffered — only counted and summarized via a periodic `scan_pulse`.
    `scanner_trigger` always streams. `raw` mode streams everything (buffered
    only when a raw subscriber exists). Hard `_MAX_BUFFER` load-shed on bursts.
  • **Always-on persistence**: `sentcom_thoughts` is written 24/7 regardless of
    the tab; the WS is only the live delivery channel (so nothing is lost when
    the tab is closed — reopen → backfill + resume).

### Backend
- `services/stream_bus.py` (NEW) — loop-local broadcaster + `classify_lane` /
  `severity_of` (action_type-primary, source/kind tie-breakers).
- `services/sentcom_service.py` — `emit_stream_event` now fans out to the bus
  (sync, fail-open).
- `server.py` — `@app.websocket("/api/ws/stream")` with subscribe (lanes +
  severities + mode), 20s keepalive, graceful disconnect.
- **New lane emits**: v183 guards (`wrong_side_stop_recomputed`,
  `position_stop_capped`) → Gates lane (live proof they fire); `target_hit`
  scale-out → Position lane.

### Frontend
- `pages/MissionControlPage.jsx` (NEW) — orchestrator (backfill + live tail).
- `hooks/useStreamSocket.js` (NEW) — WS client, backoff reconnect, sub push.
- `lib/laneClassify.js` (NEW) — client mirror of the server classifier (backfill).
- `components/missioncontrol/{StreamRow,LaneColumn,TrailDrawer}.jsx` (NEW).
- `App.js` + `Sidebar.js` — new "Mission Control" nav tab (Radio icon).

### Verification
- 14 stream-bus unit tests (lane classify, severity, firehose aggregate/raw,
  per-connection flush filter, scan_pulse). 48/48 across v169/v181/v182/v183/v184.
- **Live WS handshake verified** on the local backend (connect → lane-filtered
  subscribe → ping/pong).
- Frontend: lint clean, compiles with no module errors; smoke screenshot shows
  5 lanes + System strip + heartbeat + AGGREGATE/RAW + severity filters
  rendering (IDLE in the mirror — no REACT_APP_BACKEND_URL/live data; connects
  live on the DGX).
- Deploy patch: https://paste.rs/21jcv (14 files), `git apply --check` clean on
  v183 tree (DGX HEAD 7863a27d).

### Follow-ups (deferred, noted)
- More lifecycle emits (stop→breakeven, trailing-stop move, order_submitted,
  partial_fill, EOD-flatten-initiated) to further enrich Position/Execution.
- Inline "acknowledge" action on System/Safety alarms (currently click-through
  to the recent-decision drawer only).
- ⚠️ OPERATOR LIVE-CHECK: open Mission Control on the DGX during RTH — heartbeat
  should go LIVE, Scanner pulse should tick (triggers/skips/rejects), Gates
  should fill with rejection reasons; flip RAW to see the skip firehose.

---



## 2026-05-30 — v19.34.183 STOP-GEOMETRY SANITY (squeeze stale-trigger + evaluator guards)

### Why (found while validating v182 gameplan accuracy — now visible, not hidden)
With v182 surfacing real alert levels, three live alerts exposed bad stop
geometry: DIA `squeeze` long had `stop 505.82 ABOVE entry 501.63` (inverted),
and BMO `stage_2_breakout` carried a 16.8% structural stop. Root cause traced:
the alert dict maps `stop_price = alert.stop_loss`, and the evaluator only
recomputes a stop when one is MISSING (`if not stop_price`) — so detector
stops flow straight into sizing/brackets, inverted or over-wide.

### Bugs fixed
1. **DIA squeeze stale trigger (detector).** `_check_squeeze` set
   `trigger_price = bb_upper` (long) but anchored stop/target to *current
   price*. Once price has already broken out and run past the band, bb_upper
   is stale and an ATR stop (current_price − 1·ATR) lands ABOVE it → inverted
   long. Fix: anchor entry to `max(bb_upper, current_price)` (long) /
   `min(bb_lower, current_price)` (short), and compute stop+target+R:R off that
   single consistent `entry`. Normal pre-breakout case unchanged (entry =
   band). Option (i): fix the geometry, do NOT suppress the signal.
2. **Inverted stop reaches sizer (evaluator, defense-in-depth).** New wrong-side
   guard right after the stop resolve: if a long's stop ≥ entry (or short's
   stop ≤ entry), discard it and recompute via `calculate_atr_based_stop`
   (always correct-side). Catches ALL ~38 detectors, not just squeeze.
3. **v169 5% stop-cap bypassed for detector stops (evaluator).** v169's
   position/investment 5%-of-entry cap lives inside `calculate_atr_based_stop`,
   which only runs when no stop is supplied. stage_2_breakout / weekly_breakout
   supply their own wide structural stops, bypassing it → reopened the "1–3
   share" tiny-sizing problem. New cap applies the same 5% ceiling (env
   `MAX_STOP_PCT_POSITION` / `MAX_STOP_PCT_INVESTMENT`) to detector-supplied
   stops on position/investment horizons. Only TIGHTENS; never loosens.

### Not bugs (confirmed working)
- BOXX `three_week_tight` R:R 0.60 → v181 auto-ladder re-derives the target to
  clear the swing R:R floor. Working as designed.
- `LiveAlert.atr` persisting as 0.0 in diagnostics is a cosmetic display gap
  (detector used a real ATR ~5.1) — left as a future nit.

### Files changed
- `backend/services/enhanced_scanner.py` (`_check_squeeze` entry anchor)
- `backend/services/opportunity_evaluator.py` (wrong-side guard + detector stop-cap)
- `backend/tests/test_v19_34_183_stop_geometry.py` (new, 10 tests)

### Verification
- 10/10 new tests pass (3 exercise the REAL `_check_squeeze`; 7 mirror the
  evaluator guard logic). 62/62 across v169+v181+v179+v112+v182+v183 — no
  regressions. Both services compile; lint clean on the edited regions.
- Deploy patch: paste.rs URL provided in chat (3 files).
- Path touched is the ENTRY/sizing path, not the safety-critical close path.
- ⚠️ OPERATOR LIVE-CHECK: next session, grep `/tmp/backend.log` for
  `v19.34.183 wrong-side-stop` / `v19.34.183 stop-cap` to confirm the guards
  fire; confirm position-tier setups (stage_2_breakout) now size with sane
  share counts instead of 1–3.

---



## 2026-05-30 — v19.34.182 GAMEPLAN DATA-ACCURACY FIXES

### Why (operator confirmed live: stocks_in_play=0, empty key levels, $0 stops)
`gameplan_service._auto_populate_game_plan` had three data-accuracy bugs that
made the V5 Gameplan/Briefing card show blank/zero data — a hard prerequisite
for F-F (wiring premarket intelligence into the bot's prioritization).

### Bugs fixed
1. **$0 stops/targets** — entries read `getattr(alert,'stop_price')` /
   `'target_price'`, which don't exist on the `LiveAlert` dataclass (canonical
   fields are `stop_loss` / `target`). Every stop/target rendered as $0.
2. **Swing/position setups dropped** — `daily_alerts` (scan_tier swing/position)
   were computed then NEVER appended to `stocks_in_play`. Now appended (deduped)
   between the premarket and intraday tiers.
3. **Empty key levels** — `big_picture.key_levels` was never populated. Now
   filled with SPY/QQQ support+resistance (realtime technical service,
   `mongo_only=True`) and VIX (regime engine `volume_vix.signals.vix_price`).
4. **(bonus) Day-2 strict date−1** — looked up `date - 1 day`, landing on
   weekends/holidays with no plan (zero Day-2 names every Monday). Now queries
   the most recent PRIOR game plan (`{"date": {"$lt": date}}` sort desc).
5. **(bonus) reasoning List[str]** — coerced to text via `_reasoning_text`
   (was stored as a list / sliced as a list in if_then notes).

### Refactor
Extracted the duplicated entry-building into `_alert_to_stock_entry(alert,
source)` (single correct field mapping, used by all 3 tiers) + `_reasoning_text`
helper + `_populate_key_levels` helper. All best-effort / fail-open.

### Files changed
- `backend/services/gameplan_service.py`
- `backend/tests/test_v19_34_182_gameplan_accuracy.py` (new, 8 tests)

### Verification
- 8/8 new unit tests pass (pure logic; no DB/IB needed); 14/14 with the
  existing gameplan-narrative suite. Lint clean. Patch verified to `git apply
  --check` cleanly on the v181 tree (DGX HEAD 8f21c0f6).
- Deploy patch: https://paste.rs/i5pbj (gameplan_service.py + test).
- ⚠️ RUNTIME NOTE: `GET /journal/gameplan/today` only re-creates the plan when
  none exists for today. To see the fix on a day where a (buggy) plan already
  exists, delete today's `game_plans` row OR call `POST /journal/gameplan
  ?auto_populate=true` to regenerate. Tomorrow's open is clean automatically.

---



## 2026-05-29 — v19.34.181 OPENING-VOLATILITY TIME GATE + R:R AUTO-LADDER FALLBACK

### Why (operator-driven, from live 10:05 ET scanner review)
1. Swing/position/investment/multi-day setups were firing in the opening 30
   min — operator wants them gated to **10:15 ET+** (scalp/intraday stay
   all-day). Root cause: `_is_setup_valid_now` only blocks setups LISTED in
   `STRATEGY_TIME_WINDOWS`; none of the longer-horizon setups were listed, so
   the gate returned True (all-day) for them.
2. Longer-horizon setups were almost all rejected at the `min_risk_reward`
   gate at absurd R:R (BIL 0.02, BOXX 0.03, stage_2 0.57-0.76). Root cause:
   their detectors supply their OWN targets (set near daily structure, close
   to entry) paired with wide 2.5-3× ATR stops → R:R ≪ 1. The auto R-ladder
   only ran when NO targets were supplied, so it never rescued them.

### Fixes shipped
- **Time gate (enhanced_scanner):** new `LATER_HORIZON_STYLES`
  {swing, position, investment, multi_day} + `LATER_HORIZON_START_ET=(10,15)`.
  `_later_horizon_window_ok(alert)` blocks those styles before 10:15 ET; wired
  right after `_check_setup` so it gates on the alert's FINAL `trade_style`
  (an intraday-classified `squeeze` correctly stays all-day even though
  STRATEGY_CONFIG tags it swing). Scalp/intraday/unknown pass any time.
  Fail-open.
- **R:R auto-ladder fallback (opportunity_evaluator):** extracted the v112
  trade-style ladder into `_target_ladder_rungs(alert, setup_type)` (behavior
  identical). At the R:R gate, when a detector-supplied target yields
  sub-threshold R:R, re-derive the target from the ACTUAL per-share risk using
  the ladder, picking the smallest rung that clears `effective_min_rr`
  (swing→2.5R, position→2R), leaving the stop untouched. Only applies if the
  recomputed R:R actually clears the floor; otherwise rejects as before.
  Logs `🪜 ... auto-ladder fallback`.

### Files changed
- `backend/services/enhanced_scanner.py`
- `backend/services/opportunity_evaluator.py`
- `backend/tests/test_v19_34_112_scalp_sl_tp_fix.py` (anchored to new helper)
- `backend/tests/test_v19_34_181_timegate_and_rr_fallback.py` (new, 8 tests)

### Verification
- 8 new tests pass; 121/121 across all ladder/RR/exposure/TQS/prioritization
  suites green; both services compile.
- Live (post-deploy): R:R fallback verifiable now (`grep "auto-ladder fallback"
  /tmp/backend.log`; longer-horizon setups should start clearing the R:R gate).
  Time gate verifiable at TOMORROW's open (no swing/pos/inv/m-day alerts before
  10:15 ET; they appear at 10:15).
- ⚠️ Deploy restarts the backend mid-session → account-guard re-trips
  (re-acknowledge once account chip is green) and open positions get re-adopted
  by the reconciler. Prefer deploying when flat / after close.

---


## 2026-05-29 — v19.34.180 PUT /risk-params now persists MONGO_WINS fields

### Why
During v179 ops, setting `max_open_positions=25` via `POST /api/trading-bot/risk-params`
returned 25 in-memory but `effective-limits` kept reading 10. Root cause: the
endpoint persists via a fire-and-forget `asyncio.create_task(_save_state())`,
which races the `state_integrity` watchdog. `max_open_positions` (and 5 other
limits) are `MONGO_WINS`, so the watchdog reverted in-memory 25 back to the
stale Mongo 10 before the deferred save landed. The operator's API change
silently didn't stick (had to write Mongo directly + force-resync).

### Fix
`trading_bot_service.update_risk_params` now writes any updated `MONGO_WINS`
fields **synchronously** to `bot_state.risk_params.*` before the async save.
Sync pymongo is safe here — the method runs from a sync FastAPI route
(threadpool), not the event loop. Affects: `max_open_positions`,
`max_position_pct`, `max_daily_loss_pct`, `min_risk_reward`,
`reconciled_default_stop_pct`, `reconciled_default_rr`. MEMORY_WINS fields
(`starting_capital`, `setup_min_rr`, etc.) are intentionally excluded.

### Files changed
- `backend/services/trading_bot_service.py` (update_risk_params sync persist)
- `backend/tests/test_v19_34_180_risk_params_sync_persist.py` (new, 4 tests)

### Verification
- 4/4 unit tests pass; file compiles.
- Live (post-deploy): `POST /risk-params {max_open_positions:24}` → effective
  reads 24 with NO manual Mongo write or resync; restore to 25 confirmed.
- Ops note: live max_open_positions raised 10 → 25 (kill switch already 25).

---


## 2026-05-29 — v19.34.179 PRIORITIZATION + SLOT ALLOCATION + EXPOSURE + POS-CAP

### Why
Read-only audit of premarket prep / trade prioritization / scalp time-decay
surfaced four concrete defects. Fixed all four + the operator's
`max_open_positions` alignment question.

### Fixes shipped
- **F-A — inverted alert priority sort (P0)**. `enhanced_scanner.get_live_alerts`
  used `sort(key=(priority_order, created_at), reverse=True)` with
  `priority_order={CRITICAL:0…LOW:3}`, so `reverse=True` flipped the bucket
  order and **CRITICAL/HIGH alerts sorted LAST**. The bot intake
  (`_get_trade_alerts` → `[:20]` → slot fill) burned its position slots on
  LOW-priority alerts first and could truncate CRITICAL off the end. Replaced
  with a **stable two-pass sort** (recency desc, then priority asc) → CRITICAL
  first, newest-first within bucket. Proven: pre-fix order
  `[LOW,MED,HIGH,CRIT]`; post-fix `[CRIT_new,CRIT_old,HIGH,MED,LOW]`. The same
  file already used the correct convention at L1115 (CRITICAL=4) — confirming
  `get_live_alerts` was the outlier.
- **F-B — quality-ranked slot allocation**. `_get_trade_alerts` returned
  `alerts[:20]` in scanner order with no quality ranking. Added `_alert_rank`
  (priority bucket → tqs_score → trigger_probability → score, all desc) before
  the slice so the scarce `max_open_positions` slots go to the BEST ideas.
- **F-C — portfolio exposure caps now apply to autopilot**. The v96/98
  position-style (30%) + long-horizon (55%) caps via
  `portfolio_exposure_guard.compute_exposure` were wired ONLY into the manual
  `submit_trade` router path. Unattended bot entries could pile simultaneous
  long-horizon bets past the intended concentration (starving scalp/intraday
  buying power). Mirrored the clamp into `opportunity_evaluator.evaluate_opportunity`
  (autonomous path), right after final sizing: clamps shares to the remaining
  cap room, or rejects (`reason_code="portfolio_exposure_cap"`) when saturated.
  Fail-open. Per-symbol (v123) cap still applies independently.
- **F-E — morning-readiness false YELLOW**. `morning_readiness_service` expected
  EOD at 15:55; canonical is 15:45 (v181). Widened the accepted band to
  15:40–15:58 so the daily autopilot check stops throwing a spurious YELLOW.

### max_open_positions alignment (operator question — "isn't it 25 now?")
- **Code default bumped 10 → 25** (`RiskParameters.max_open_positions`). This is
  only the fallback; the LIVE value is Mongo `bot_state.risk_params.max_open_positions`.
- **Intake gate now uses the EFFECTIVE cap** = `min(bot value,
  SAFETY_MAX_POSITIONS)`. Previously the scan-loop intake (`:4097`) used the
  bot value alone while the kill switch enforced the min — so a bot=25 /
  kill-switch=5 config wasted evaluation on trades that would be blocked at
  execution. Gate can now only TIGHTEN (strictly safe).
- ⚠️ OPERATOR ACTION: the binding cap is `min(bot, SAFETY_MAX_POSITIONS)`. The
  kill-switch env default is **5**. If you want 25 live, set BOTH:
    - Mongo: `db.bot_state.updateOne({_id:"bot_state"},{$set:{"risk_params.max_open_positions":25}})`
    - DGX env: `SAFETY_MAX_POSITIONS=25` (then restart). Confirm via
      `GET /api/trading-bot/effective-limits` → `effective.max_open_positions`.

### F-D — scalp time-decay tagging audit (read-only script)
`backend/scripts/audit_scalp_timeframe_tagging_v19_34_179.py`. `check_scalp_decay`
only fires for `timeframe=="scalp"`, which is set from
`STRATEGY_CONFIG[setup_type]["timeframe"]` (default INTRADAY). Any scalp detector
missing/mis-tagged silently never time-decays (closes only at EOD). Run on DGX:
`DB_NAME=tradecommand python -m backend.scripts.audit_scalp_timeframe_tagging_v19_34_179`
→ prints mismatches; if any, add/correct the setup's STRATEGY_CONFIG timeframe.

### Files changed
- `backend/services/enhanced_scanner.py` (F-A)
- `backend/services/trading_bot_service.py` (F-B + pos-cap default + effective intake gate)
- `backend/services/opportunity_evaluator.py` (F-C autonomous exposure clamp)
- `backend/services/morning_readiness_service.py` (F-E)
- `backend/scripts/audit_scalp_timeframe_tagging_v19_34_179.py` (new, F-D)
- `backend/tests/test_v19_34_179_prioritization_and_caps.py` (new, 8 tests)

### Verification
- 8/8 new unit tests pass; 52/52 existing TQS + exposure-cap tests still green.
- All five changed files compile; F-C guard import + clamp math validated.
- ⚠️ No automated agent (hardware-bound). OPERATOR LIVE-CHECK: confirm
  CRITICAL alerts get slots first; run the F-D audit; set the pos-cap env/Mongo.

---


## 2026-05-29 — v19.34.177 PORTABLE CLOSED-TRADES FEED (foundation for pipeline tabs + V6)

### Why
Operator is planning a V5 layout change (pipeline-stage feeds as persistent
tabs) but V6 is on the horizon with a different layout philosophy. Decision:
build only the **layout-agnostic, V6-portable** pieces now and DEFER the
V5-only tab-container/layout restructure. Strict constraint: **zero impact on
the running app.**

### Shipped (fully additive)
- **Backend** `GET /api/sentcom/closed-trades?range=today|7d|30d` (new route in
  `routers/sentcom.py`). Sourced from `bot_trades`, reuses the EXACT v141 dedup
  key + flags synthetic/reconciler closes, computes a server-side summary
  (count / WR / net / ΣR / avg / worst / best). Rich rows: unified TQS grade,
  dir, shares, entry/exit price, **entry/exit time + hold duration**, realized $,
  R, MAE/MFE (R), close reason, trade type. Does NOT touch any existing route.
- **Frontend** `components/sentcom/v5/ClosedTradesTable.jsx` — portable,
  presentational, sortable rich table (data via props, emits onRowClick /
  onRangeChange). Drops into the future V5 Close tab AND V6 history view with no
  rework.
- **Frontend** `components/sentcom/preview/ClosedTradesPreview.jsx` — isolated
  harness (self-fetch + 15s live refresh) reachable ONLY at
  `?preview=closedfeed`. NOT mounted in the live tree.
- **App.js** — added the `?preview=closedfeed` escape-hatch branch (mirrors the
  existing `?preview=v6mock` pattern). Normal app render path unchanged.

### Verification
- Endpoint tested via curl across all 3 ranges: dedup confirmed (phantom NVDA
  dropped), range filtering confirmed, summary accurate. Proxy path confirmed.
- Real component renders real endpoint data in the V5 aesthetic (screenshot).
- Frontend compiles clean; lint passes. Zero changes to existing endpoints or
  the live command-center tree.

### Deferred (V5-only, pending V6 timing decision)
- Pipeline-feed tab container (HUD tiles → tabs), badge pulse, 3-column layout
  restructure, right-column → bot-stream move. Hold until operator confirms V6
  timeline (replace vs coexist).

---

## 2026-05-29 — v19.34.176 REGIME ENGINE: COMPOSITE SPY/QQQ/IWM TREND + TOLERANCE

### Why
The `market_regime_engine.py` TrendSignalBlock (35% of the composite regime
score that drives `bot._current_regime` → position sizing + direction bias)
was **SPY-only**: it accepted `qqq_bars` but never used it, ignored IWM
entirely, and used strict boolean MA comparisons. A SPY close 0.01% under the
21-EMA flipped a 20-pt signal off, so a flat tape with green QQQ/IWM could
still print a market-wide "downtrend" — the operator's "SPY downtrend
hallucination".

NOTE: v166 (SPY 0.25% tolerance) + v167 (composite SPY/QQQ/IWM) had already
shipped on 2026-05-27, but ONLY to `realtime_technical_service.py` (per-symbol
trend classifier) and `enhanced_scanner._update_market_context` (scanner ML
context). The **regime engine that drives trading decisions was never patched**
— this is that fix.

### Fix shipped (v19.34.176)
`backend/services/market_regime_engine.py`:
- `TrendSignalBlock` is now a **weighted composite of SPY/QQQ/IWM**
  (0.5 / 0.3 / 0.2, renormalized over whatever has ≥200 bars; SPY stays the
  anchor — if SPY data is missing the block returns neutral 50).
- New `_score_index()` scores each index independently; new `_band_points()`
  applies a **±0.25% tolerance band** (price within band = half credit /
  neutral instead of a hard 0/full flip) — matches v166.
- Surfaces `index_scores`, `indexes_used`, `blend_weights`, `divergence_flag`,
  and `tolerance_pct` in `trend_block.signals` for observability. Back-compat
  SPY MA fields retained.
- `_calculate_regime()` now fetches 200 bars for QQQ + IWM (was 50 for QQQ,
  none for IWM) and passes all three to the trend block.

### Files changed
- `backend/services/market_regime_engine.py`
- `backend/tests/test_regime_composite_trend_v19_34_176.py` (new, 8 tests passing)

### Verification
- 8/8 new unit tests pass (tolerance band, per-index scoring, blend,
  divergence, SPY-hallucination fix, SPY-only fallback, missing-SPY neutral).
- Backend boots clean; `/api/market-regime/current` responds (sandbox shows
  insufficient-data branch — no IB bars locally).
- ⚠️ OPERATOR LIVE-CHECK: on a day SPY is soft but QQQ/IWM green, confirm
  `signal_blocks.trend.signals.indexes_used = [spy, qqq, iwm]` and the regime
  no longer flips to CONFIRMED_DOWN on SPY alone.

---

## 2026-05-29 — v19.34.175 TQS/SMB UNIFICATION + 5-PILLAR UI DRILL-DOWN

### Why
TQS (Trade Quality Score) is now the single source of truth for a trade's
grade. SMB grade was being read by the position-size scaler even though SMB
is already 15% of the TQS Setup pillar (double-counting), AND the operator
UI showed confusing standalone SMB/"F" grade badges.

### CRITICAL latent bug found + fixed
Audit revealed `trading_bot_service._get_trade_alerts()` manually rebuilt the
alert dict that feeds `opportunity_evaluator.evaluate_opportunity()` and
**dropped every grade/quality field** (`tqs_grade`, `tqs_score`, `smb_grade`,
`tape_score`, `risk_reward`, `smb_score_total`, `trade_style`). Consequences in
production since v19.34.156:
  • Position sizing grade resolved to **D = 0.1×** on EVERY trade (grade was
    `None` → `_resolve_grade_multiplier(None)` → D). Operator confirmed NO
    `POSITION_SIZE_GRADE_*` env overrides on the DGX — so the bot has been
    sizing every trade at **10% of intended size**.
  • The post-gate TQS recalc ran on hardcoded defaults (smb_grade="B", tape=0,
    rr=2.0) instead of real alert values.

### Fixes shipped (operator chose option A — full TQS sizing)
- **Plumb real TQS data into the alert dict** (`trading_bot_service.py`
  `_get_trade_alerts`): tqs_score/grade/action/pillar_scores/pillar_grades/
  breakdown/weights + tape_score, smb_score_total, risk_reward, trade_style,
  and smb_grade (audit-only).
- **Rewire position sizing to TQS** (`opportunity_evaluator.py` ~L840):
  `alert_grade = _post_gate_tqs_grade → tqs_grade → trade_grade`. SMB no longer
  drives sizing. Multiplier table unchanged (A=1.0/B=0.7/C=0.3/D=0.1) → A-grade
  trades now size at full 1.0× (~10× larger than the broken 0.1×).
- **`unified_grade` field** added to `BotTrade` (= TQS grade), plus `tqs_grade`/
  `tqs_score`. `smb_grade` retained for audit only. Serialized via `to_dict()`,
  hydrated on restore via the dataclass allow-list.
- **5-pillar breakdown captured** at alert time (`enhanced_scanner.
  _enrich_alert_with_tqs`) + post-gate (`opportunity_evaluator`), stored in
  `entry_context.tqs.{pillar_scores,pillar_grades,breakdown,weights,
  unified_grade}`.
- **Frontend** (`OpenPositionsV5.jsx` + new `TqsPillarPanel.jsx`): SMB grade
  badges replaced with the unified TQS grade; standalone **F**/missing grade
  chips suppressed (confused operators). New expand-on-click 5-pillar drill-down
  (Setup/Technical/Fundamental/Context/Execution) showing per-pillar score,
  grade, weight, sub-component scores + ± factor bullets.
- **DB backfill** (`backend/scripts/backfill_v19_34_175_unified_grade.py`):
  idempotent, sets `unified_grade` on historical `bot_trades` from
  entry_context.tqs → score-derived grade → quality_grade → smb_grade. Supports
  `DRY_RUN=1`.

### Files changed
- `backend/services/trading_bot_service.py` (BotTrade fields + alert-dict plumbing)
- `backend/services/opportunity_evaluator.py` (sizing rewire + unified_grade + entry_context.tqs)
- `backend/services/enhanced_scanner.py` (LiveAlert pillar fields + capture)
- `frontend/src/components/sentcom/v5/OpenPositionsV5.jsx`
- `frontend/src/components/sentcom/v5/TqsPillarPanel.jsx` (new)
- `backend/scripts/backfill_v19_34_175_unified_grade.py` (new)
- `backend/tests/test_tqs_unification_v19_34_175.py` (new, 10 tests passing)

### Verification
- 10/10 unit tests pass. Backend compiles + `/api/tqs/*` endpoints return the
  expected 5-pillar breakdown. Frontend compiles clean. (No automated
  testing-agent — hardware-bound per AGENTS.md.)
- ⚠️ OPERATOR LIVE-CHECK NEEDED next session: confirm A-grade fills now size at
  full 1.0× (entry_context.multipliers.grade_scale = 1.0) and that the size
  jump is expected/acceptable.

---

## 2026-05-28 — v19.34.183/185/186 BBAI PHANTOM WHIPLASH FIX BUNDLE

### Investigation
After v181/v182 EOD fix, surfaced that ARMG and BBAI had `reconciled_external`
phantom trades on 2026-05-28. Initial hypothesis: stale GTC bracket legs from
prior sessions filling today. **Disproven** — `bot_orders` cross-session
check came back empty; IBKR statement showed both May 26 + May 27 BBAI
positions flattened cleanly.

Diagnostic scripts created (all read-only, surfaced via paste.rs):
- `/tmp/trace_orphan_origin.py` — classifies today's reconciled_* trades
  vs originating alerts; flagged 11/22 trades today with `alert_id=None`
  on `bot_trades` (separate v184 issue, deferred).
- `/tmp/verify_alert_persistence.py` — confirmed `live_alerts` IS the
  alert persistence collection (117K rows, 1989 today). Earlier
  hypothesis "alerts never persisted" was **wrong** — I was querying
  the wrong collection name. **Retracted.**
- `/tmp/bbai_origin_trace.py` — pulled full 7-day BBAI lifecycle.
- `/tmp/bbai_bracket_hunt.py` — auto-scanned every Mongo collection for
  BBAI rows, found bracket_lifecycle_events with smoking-gun error.

### Real Root Causes Found

**Cause 1 — Trade-ID Race**: Bot fires order → IB confirms fill → position
appears at IB. Reconciler runs (10-30s cadence) BEFORE the executor finishes
updating `_open_trades`. Sees IB position without matching internal record,
stamps `entered_by=reconciled_external`. Bot loses ownership of its own
trade. Evidence: `trade_audit_log` shows 25+ BBAI mean_reversion_short
intents today; `bot_trades` shows 0 as `bot_fired` and 3 as
`reconciled_external` with mangled share counts.

**Cause 2 — IB Error 110 (Variable Tick)**: Reconciler's orphan-stop math
in `position_reconciler.py:1310-1314` uses float arithmetic:
`stop_price = avg_cost - stop_distance`. For BBAI at $4.82 with 1.5%
stop, this produces $4.7477 — IB's tick grid for $1+ stocks requires
$0.01 increments, so IB returns Error 110, the `bracket_attach_governor`
permanently blocks the symbol for the day, and the phantom stays naked.
Evidence: 15+ consecutive `bracket_lifecycle_events` failures on BBAI
with `error=bracket_attach_blocked:permanent_block:ib_error_110_*`.

### Fixes Shipped

**v19.34.185 — Submit-Race Guard** (`position_reconciler.py:1259-1322`)
Before spawning a `reconciled_orphan` BotTrade for symbol X, scan
`bot._open_trades` for any trade matching X with `pre_submit_at`
within the last 60s. If found, refuse to adopt — log `submit_race_v19_34_185`
skip and let the next reconcile cycle find the trade properly
registered. Honors the v19.34.6 pre-submit stamping that was
previously ignored by the reconciler.

**v19.34.186 — Variable-Tick Rounding** (`position_reconciler.py:1377-1389`)
Added `_v186_tick_round()` after orphan-stop math. Uses Decimal +
ROUND_HALF_UP to snap stop_price + target_1 to the correct grid:
- Stock < $1.00 → $0.0001 (4 decimals)
- Stock >= $1.00 → $0.01 (2 decimals)

Both patches committed as `002b7345`. Deploy script at paste.rs/jQJ9k
(idempotent, auto-commits, auto-pushes).

**One-time data repair** (`/tmp/repair_phantom_v19_34_185.py`,
paste.rs/eNi97). Cross-references `trade_audit_log` planned trades
against `bot_trades` reconciled_external fills within ±120s and ±0.5%
price tolerance. For 2026-05-28: surfaced 6 candidates, repaired 1
(BBAI 277sh short → vwap_fade_short, audit_match=0434fb3e tight_match).
The other 5 left as-is (genuine external positions, share-count drift,
or partial-fill remnants — script conservatively requires strong evidence).

### Files Changed
- `backend/services/position_reconciler.py` (+80 lines)

### Verification Plan (2026-05-29 open)
1. 15:45 ET — EOD heartbeats fire (v181/v182 confirms)
2. Throughout session — No `submit_race_v19_34_185` adoptions of
   bot-fired trades; bot keeps ownership
3. Sub-$5 stocks — No more `ib_error_110` permanent blocks;
   brackets attach cleanly

### Still Open (Deferred to Future Sessions)
- v19.34.184 — `alert_id` stamping fix for `squeeze`, `vwap_bounce`,
  `gap_fade`, `daily_squeeze`, `pocket_pivot` paths. v19.34.36 wiring
  works for `mean_reversion_short` but bypasses these 5 setups.
  Today: 11/22 trades had `alert_id=None`.
- v19.34.187 — Defensive belt-and-suspenders cooldown
  (`_recent_executor_activity` dict) on the reconciler. Belt for v185
  if pre_submit_at isn't stamped on some new code path.
- v19.34.172 — Dual-shape timestamps (`ts` ISO + `ts_dt` BSON) on
  `bot_trades`, `alert_outcomes`, `shadow_decisions`,
  `bracket_lifecycle_events` to prevent silent 0-rows query bugs.
- v19.34.175 — TQS/SMB unification + 5-pillar UI drill-down panel
  (read-only with expand-on-click, hide SMB "F" badges).

---


## 2026-05-28 — v19.34.181 + v19.34.182 EOD AUTO-CLOSE RESTORED

### Trigger
EOD auto-close failed silently on 2026-05-28 — operator had to manually
flatten all positions in TWS at the close. The v169 heartbeat showed
0 entries, suggesting `check_eod_close()` was never reached. Initial
hypothesis (three early `continue`s in scan_loop: daily-loss / trading
hours / PAUSED) was wrong — diagnostic queries confirmed none had tripped.

### Real Root Cause
`/tmp/backend.log` showed 10× consecutive lines of:
```
⚠️ [TradingBot] _check_eod_close exceeded 5.0s budget — skipping this cycle
```

The `_EOD_WALL_S = 5.0` asyncio.wait_for timeout in `_scan_loop` was killing
`check_eod_close()` on every cycle. Reasons EOD needs > 5s:
- `check_position_memory_disagreement` (IB roundtrip)
- `_flatten_ghost_positions` sweep
- Parallel `asyncio.gather` of N IB close calls (~2–5s each)

TimeoutError → "skipping this cycle" → next scan → repeat. The cancellation
happened BEFORE reaching the heartbeat write at line 1209, explaining the
0-heartbeat post-mortem.

### Fixes
**v19.34.181** — Single-line bump in `services/trading_bot_service.py`:
```python
_EOD_WALL_S = 5.0  →  _EOD_WALL_S = 60.0
```
Also re-canonicalized `bot_config.eod_config` MongoDB document:
`{enabled: True, close_hour: 15, close_minute: 45}`.

**v19.34.182** — Belt + suspenders. Added dedicated `_eod_supervisor_loop()`
asyncio task spawned in `TradingBotService.start()`:
- Ticks every 15s, **independent** of `_scan_loop`.
- Calls `check_eod_close()`, `check_scalp_decay()`, `_check_eod_grading()`
  with **NO `asyncio.wait_for` wall** — EOD can take as long as it needs.
- Idempotent: scan_loop ALSO calls them (60s wall now); both paths safe
  to run concurrently via `_eod_close_executed_today` flag + grading
  per-day key.
- New 16:00 ET hard alarm: if any `close_at_eod=True` position is still
  open at 4:00 PM ET, fires a CRITICAL `sentcom_thoughts` row
  (`category="eod_post_close_alarm"`) + WS broadcast.
- Cancelled cleanly in `TradingBotService.stop()`.

### Verification
Backend restart confirmed:
```
🤖 [TradingBot] Scan loop started - interval: 30s
🛡️  [TradingBot] v19.34.182 EOD supervisor started (15s cadence, no wait_for wall)
```

### Files Changed
- `backend/services/trading_bot_service.py` (v181 sed + v182 patch)
- `bot_config.eod_config` MongoDB document (canonical 15:45)

### Operational Notes
- Per `AGENTS.md`, backend restart uses `./start_backend.sh --force` (not
  supervisorctl). The Windows `.bat` runs `git checkout -- .` on the DGX,
  so v182's deploy script auto-commits + pushes immediately.
- Diagnostic script saved at `/tmp/eod_diag.py` for future post-mortems.

---


## 2026-05-28 — v19.34.170 Timestamp normalization + Fundamentals reconnect

### Trigger
Two recurring stability issues identified in the v169 handoff:

1. **Timestamp type drift across DB collections** — `bot_trades`,
   `alert_outcomes`, `shadow_decisions` write ISO strings;
   `bracket_lifecycle_events` and `_persist_thought` writes use BSON
   datetimes. The v169 EOD heartbeat wrote `created_at` as an ISO
   string, which broke the `created_at` TTL index on `sentcom_thoughts`
   AND made the row invisible to `routers/diagnostics.py` queries that
   filter on `timestamp` (ISO). Cross-collection queries returned 0
   rows silently — a known cause of "phantom" debugging sessions.

2. **Fundamentals "Not connected to IB" log spam** —
   `TradeContextService._capture_fundamental_context` unconditionally
   called `ib_service.get_fundamentals(symbol)` which raises
   `ConnectionError` whenever the direct ib_insync worker is stale
   (most of the time on this DGX install, since live data uses the IB
   pusher RPC path). Each evaluated alert logged a WARN and left the
   `FundamentalContext` empty.

### Fix
- **`backend/utils/timestamps.py`** — new module exposing `now_iso`,
  `now_bson`, `parse_to_bson`, `parse_to_iso`, `stamps`, `epoch_ms`.
  Canonical convention going forward: new collections write BOTH a
  `ts` ISO string AND a `ts_dt` BSON datetime so either query shape
  succeeds. Existing collections keep their current shape but
  consumers use `parse_to_bson`/`parse_to_iso` to coerce input.
- **`services/position_manager.py` EOD heartbeat** — rewritten to the
  canonical `sentcom_thoughts` schema: `kind="system"`, `content`,
  ISO `timestamp` (so `routers/diagnostics.py` queries see it), BSON
  `created_at` (so the TTL index actually expires it after 7d). Keeps
  top-level `category="eod_heartbeat"` so the operator's existing
  `db.sentcom_thoughts.find({category:'eod_heartbeat'})` query shape
  from v169 still works.
- **`services/trade_context_service.py`** — gate the IB fundamentals
  call behind `ib_service.get_connection_status()` and fall back to
  the Finnhub-backed `FundamentalDataService` when the direct IB
  worker reports disconnected. Earnings proximity lookup is now
  independent of either upstream.

### Test
- `tests/test_v19_34_170_timestamps_and_fundamentals.py` — 12 tests:
  timestamp parse/round-trip, fundamentals fallback hits Finnhub when
  IB is down, no IB call when disconnected, IB path is preferred when
  connected, static guard against the EOD heartbeat regressing to ISO
  `created_at`. All 12 pass. Regression suite (v164/v165/v168.1/v169
  = 54 tests) all still green.

### Deployment notes
- No DB migration needed — change is forward-compatible.
- After the next DGX backend restart, new `sentcom_thoughts` rows for
  EOD heartbeats will have the new schema. Old v169-shape rows TTL out
  in 7d.

---


## 2026-05-28 — v19.34.169 Pre-market sizing+EOD observability

### Trigger
Operator report: small share sizes on POSITION-tier setups (e.g. ALAB
1 share, ASTS 3 shares); and EOD scheduler appeared silent yesterday,
requiring ~13 manual TWS closes. Diagnosed root causes:

1. **Sizing**: `rs_leader_break`, `accumulation_entry`, `power_trend_stack`,
   `stage_2_breakout` use 2.5-3.0× ATR multipliers. On high-priced
   volatile names this yields 12-14% raw stop distances, which
   combined with the fixed risk_per_trade budget collapsed share
   counts to 1-3. POSITION-tier setups are multi-day holds by design
   (`close_at_eod=False`); their stops were tuned for swing R:R, not
   intraday risk envelopes.

2. **EOD silence**: `_check_eod_close` IS wired into the scan loop
   (`trading_bot_service.py:3907`, with a wall-time budget) and
   `_eod_close_enabled=True` at init. But EOD state lives only
   in-memory on the `TradingBotService` instance — no DB
   audit trail. Yesterday's `/tmp/backend.log` was truncated by the
   morning restart, so we can't retrospectively prove what fired.
   The 11 filled positions all closed via `oca_closed_externally_v19_31`
   — the bot's catch-all when IB shows position vanished without
   bot-initiated close. That reason fires for BOTH IB OCA brackets
   AND operator-initiated TWS manual closes (the bot can't distinguish).

### Fix
- **`opportunity_evaluator.calculate_atr_based_stop`** — cap stop
  distance at 5% of entry for ATR multipliers ≥ 2.5 (INVESTMENT and
  POSITION horizons). Operator-tunable via env
  `MAX_STOP_PCT_INVESTMENT` / `MAX_STOP_PCT_POSITION`. Scalps and
  intraday setups unchanged. Cap NEVER widens an already-tight stop.
- **`position_manager.check_eod_close`** — write a `sentcom_thoughts`
  row (category=`eod_heartbeat`) once per minute inside the EOD
  window so the operator can SEE the scheduler firing from the UI
  even when no positions are eligible to close. Dedupes per HH:MM.
- **`start_backend.sh`** — archive `/tmp/backend.log` to
  `logs/backend_YYYYMMDD_HHMMSS.log` before each restart, with 30-day
  retention. Prevents future "where did yesterday's evidence go" gaps.

### Tests (`backend/tests/test_v19_34_169_stop_cap.py`)
- 8/8 passing: ALAB 5% cap, stage_2_breakout 5% cap (3.0× mult),
  accumulation_entry 5% cap (2.5× mult), intraday breakout NOT capped,
  9_ema_scalp NOT capped, env override (`MAX_STOP_PCT_POSITION=0.07`),
  already-tight stop preserved, short-side symmetry.

### Verified live on DGX
- POSITION-tier sizing: deployed via `backend/scripts/deploy_v19_34_169.py`.
  Restart confirmed; first qualifying trade will show stop_pct ≤ 5%.
- Log archive: `→ archived /tmp/backend.log → logs/backend_20260528_093341.log
  (702099 bytes)` on first restart.
- EOD heartbeat: deferred verification to today's 19:45-20:00 UTC
  window (operator to query `sentcom_thoughts` for category=eod_heartbeat).

### Known follow-ups
- EOD bug NOT confirmed-fixed yet — heartbeat is the diagnostic.
  Action item for tonight: query for `category=eod_heartbeat` after
  the close. If heartbeats fire but no closes go out for
  `close_at_eod=True` positions, the bug is downstream in the
  flatten path. If no heartbeats at all, the scan loop isn't reaching
  EOD code (timeout, wedged loop, etc.).
- `bot._eod_close_executed_today` flag is in-memory only — needs DB
  persistence so a mid-day crash doesn't repeat EOD.


## 2026-05-27 — v19.34.168.1 Composite regime history+stats routing fix

### Trigger
v168 added `/api/market-regime/history` + `/api/market-regime/stats`
endpoints as bare `@app.get(...)` decorators in `server.py`. Both
collided with the existing daily Engine A router (`routers/market_regime.py`
mounted at prefix `/api/market-regime`): `/history` was shadowed
(returned daily Engine A's `market_regime_state` rows instead of intraday
snapshots) and `/stats` returned 404.

### Fix
- Renamed the new intraday endpoints to live under the `composite/`
  namespace established by v167.1:
  - `GET /api/market-regime/composite/history` → reads `regime_snapshots`
  - `GET /api/market-regime/composite/stats` → % time-in-regime over N hours
- Both endpoints registered next to the working `/api/market-regime/composite`
  route at the end of `server.py` so binding is deterministic.
- Daily Engine A `/api/market-regime/history` still serves `market_regime_state`
  (no collision, verified via regression curl).
- `backend/services/regime_persistence_service.py` shipped with TTL=30d index,
  in-process change detection, history + stats query helpers.
- Idempotent deploy script `backend/scripts/deploy_v19_34_168_1.py`:
  strips any prior broken `@app.get("/api/market-regime/history")` /
  `/stats` decorators before injecting the new routes.

### Tests (`backend/tests/test_v19_34_168_1_endpoint_routing.py`)
- 8/8 passing: change-detection, divergence-flip persistence, history
  filter window, stats % calculation, empty-DB handling, and
  `server.py` namespace verification.

### Verified live on DGX
- `composite/history?hours=6` → `success:true, source:"regime_snapshots"`
- `composite/stats?hours=6` → `success:true, "no snapshots in window"`
  (correct — collection only populates on regime/agreement/divergence flips)
- `history?days=30` → still returns Engine A composite_score data (no regression)


## 2026-05-27 — v19.34.167 Composite SPY/QQQ/IWM market regime classifier

### Trigger
v166 fixed the SPY trend classifier but the SCANNER's regime gating
(`enhanced_scanner._update_market_context`) was still SPY-only — blind
to QQQ/IWM divergence. A clean uptrend in SPY+QQQ with IWM breaking
down would tag the market STRONG_UPTREND and let `9_ema_scalp` fire
into a small-cap-led reversal.

### Architecture decision
Audited the three existing regime layers (`MarketRegimeEngine` daily,
`enhanced_scanner._update_market_context` intraday, `realtime_technical_service.trend`
per-symbol kernel) — kept them separate (different timeframes) and
extended layer 2 to vote across the broad indexes using the layer 3
kernel as the per-index probe. No new infrastructure.

### Patch (`backend/services/enhanced_scanner.py`)
1. **`_update_market_context`** rewritten to `asyncio.gather` SPY+QQQ+IWM
   snapshots in parallel, then delegate to a pure classifier.
2. **`_classify_market_regime(spy, qqq, iwm)`** — new pure method:
   - VOLATILE if max daily_range_pct across valid indexes > 2.0
   - Unanimous (3/3) up + 3/3 above VWAP + EMA9 → STRONG_UPTREND
     (or MOMENTUM if SPY rsi > 60)
   - Unanimous (3/3) down + 3/3 not above VWAP → STRONG_DOWNTREND
   - Majority (2/3) up + 2/3 VWAP support → MOMENTUM (degraded)
   - Majority (2/3) down → FADE (degraded)
   - Mixed/no majority → RANGE_BOUND (or FADE if SPY quiet + extreme RSI)
3. **Single-index fallback** replays v166 logic verbatim if QQQ/IWM
   unavailable.
4. **`self._market_data`** new attribute exposing `indices_valid`,
   `index_agreement` (unanimous_up/down, majority_up/down, mixed),
   `divergence_flag`, `uptrend_votes`, `downtrend_votes`,
   `max_daily_range_pct`, and `per_index: {spy, qqq, iwm}` breakdown.
5. `self._spy_data` retained for backwards compat with downstream consumers.

### Tests — `backend/tests/test_market_regime_composite_v19_34_167.py`
14/14 passing on DGX:
- Unanimous up (clean / overbought)
- Unanimous down
- Small-cap divergence (SPY+QQQ up, IWM down) → MOMENTUM
- Tech divergence (majority down) → FADE
- 1-1-1 split → RANGE_BOUND
- VOLATILE override (IWM > 2% range)
- 2% boundary not VOLATILE (strict >)
- Single-index degraded mode (3 variants)
- Metadata structure sanity
- v166 audit case regression: must NOT classify STRONG_DOWNTREND

### Deploy
Single-line 12,904-char base64 paste (after chunked approach broke
when chat collapsed newlines). Pre/post SHA verified.

### Verification
- Pre: `73991b86facdc3e1...` → Post: `0bdbb7a97c6a78f7...` ✅
- New backend PID 3757239 serving on :8001 ✅
- Backup retained: `enhanced_scanner.py.pre_v167.bak`

### Watch next
- Scanner ticks emit new alerts with composite regime + divergence flag
- Setups that were silenced by false STRONG_DOWNTREND tags should
  start firing during clean uptrend / sideways regimes

---

## 2026-05-27 — v19.34.166 Trend classifier tolerance + macro-context veto

### Trigger
After v19.34.165 unlocked 5 momentum setups, the audit found that ~80% of
live alerts on a +0.48% SPY gap-up day were being tagged
`strong_downtrend` by `realtime_technical_service.get_technical_snapshot`.
SPY at 749.19 (EMA9=749.26, EMA20=749.65, EMA50=698.44, SMA200=698.44)
was classified "downtrend" because the original logic at L596-602 used
strict binary `>` vs EMA9/EMA20 — a 7-cent intraday print below EMA9
flipped the classification despite price sitting 7% above EMA50 and the
secular structure being a clean uptrend. The misclass poisoned every
setup gate that requires `trend == "uptrend"` (incl. `9_ema_scalp`,
dormant since 2026-04-07).

### Patch (`backend/services/realtime_technical_service.py` L593-643)
1. **Tolerance band — 0.25%** (`_TREND_TOLERANCE_PCT`). Distances within
   ±0.25% of an EMA count as "at" — neither above nor below — so noise-
   level prints don't flip uptrend↔downtrend tick-by-tick.
2. **Macro-context veto**. If price > EMA50 AND EMA50 > SMA200 (secular
   uptrend structure), the classifier may NEVER return "downtrend".

### Tests — `backend/tests/test_trend_classifier_v19_34_166.py`
9/9 passing.

### Verification
- pre `f38efa1ac07888a3...` → post `afba82a9db7bfa60...` ✅
- Live SPY trend went from "downtrend" → "sideways" at price=749.46,
  dist_from_ema9=-0.01%

---

## v19.34.229 — 2026-06-02 — TQS sizing back to risk-neutral (~0.30x mean)
Operator option (a): keep the v228 conviction tilt but normalize the magnitude
(scale x0.808) so the mean position-size multiplier returns to the historical
~0.30x (was 0.371x). Env-only, no code change. Deployed to DGX via paste.rs/xo0cs,
commit af7fab67. POSITION_SIZE_GRADE_A_MULT=0.80 B=0.48 C=0.24 D=0.12 F=0.08.
Verified mean=0.297x against live grade mix + real _resolve_grade_multiplier path.

## v19.34.230 — 2026-06-02 — TQS pillar de-compression (A1/A2/B3, env-gated)
Durable follow-up to v228/v229. Widen the raw TQS so the percentile calibration
has headroom over its absolute floors.
  A1 (setup_quality.py) — EV-from-R:R when no live EV: ev_score=clamp(25+(RR-1)*22,10,95)
    (was frozen at 30). A2 — missing/uninformative SMB -> neutral 50 (was C/35).
  B3 (execution_quality.py) — history_score per-setup_type from a 15-min-cached
    trade_outcomes aggregation, shrunk toward 60 by sample size (was pinned 60).
  Flags: TQS_SETUP_DECOMPRESS / TQS_EXEC_DECOMPRESS (default ON; revert via env+restart).
  Tunables: TQS_EXEC_HIST_TTL_SEC=900, TQS_EXEC_HIST_WINDOW_DAYS=30, TQS_EXEC_HIST_SHRINK_K=10.
  Offline recompute (4000 alerts): setup median 48.9->53.5, ceiling 67.6->73.6,
  stdev 6.68->7.44; composite stdev +0.06 (level shift, not spread) BUT clears the
  v228 B>=57/A>=60 floors -> should mint B/A live (was 66% C+/34% C/0.1% B).
  B3 currently ~no-op (sparse per-setup outcomes); grows as outcomes accrue.
  15/15 pytest (tests/test_v19_34_230_pillar_decompress.py). Deployed paste.rs/E5sQn,
  commit 2ea26925. LIVE-VERIFY 2026-06-03 RTH via diag_tqs_dist.py.

## v19.34.231 — 2026-06-03 — Premarket scanner REPAIR + TQS grading
Found the premarket scanner silently dead: all 7 inline LiveAlert(...) constructors
used a stale schema (stop_price/target_price/score/timestamp + missing required
fields) and threw TypeError, swallowed by `except Exception: pass` -> ZERO premarket
alerts ever (log always printed "0 morning watchlist alerts").
  - NEW enhanced_scanner._make_premarket_alert() factory: schema-valid LiveAlert,
    risk_reward from stop/target, time_window="premarket", live regime, priority
    from score (>=85 crit / >=75 high / >=60 med / else low), trigger/win prob
    from setup base rate. All 7 setups repaired (gap-go/fade/reversal, ORB x2,
    opening-drive x2).
  - _process_new_alert: TQS-grade any UNenriched alert (premarket + non-RTH);
    RTH skipped (tqs_score>0). Flag PREMARKET_TQS_ENABLED (default ON).
  - grade_calibration._refresh_reference: exclude time_window in {premarket,closed}
    -> premarket graded AGAINST the RTH reference, never skews it.
  - 13/13 pytest (tests/test_v19_34_231_premarket_tqs.py). Deployed paste.rs/uA1UC
    (gzip+base64, full-file replace, anchor-guarded + idempotent).

## v19.34.232 — 2026-06-03 — Catalyst classification for premarket gappers (task B)
NEW services/catalyst_classifier_service.py: categorical tag (earnings|analyst|news|
sympathy|no_catalyst) answering "why is it gapping". Composes EXISTING plumbing —
earnings from earnings_calendar Mongo collection (zero hot-path Finnhub), news from
IB-first NewsService (cached 30m), sympathy from sector classifier (light v1: sector
regime moving in gap direction). Informational only in v1, fail-open, env-gated
CATALYST_TAGGING_ENABLED (default ON).
  - enhanced_scanner.py: LiveAlert.catalyst_tag/catalyst_summary; lazy classifier;
    premarket alerts classified in _process_new_alert.
  - gameplan_service._alert_to_stock_entry: stocks-in-play now carry catalyst_tag/
    summary + premarket tqs_score/tqs_grade (surface on the Game Plan, not a new
    digest — decided existing 8:30 Pre-Market Briefing + Game Plan already cover it).
  - 9/9 v232 pytest (+13 v231). Deployed paste.rs/De4Hb as a SUPERSET incl v231
    (byte-idempotent, anchor-guarded, gzip+base64). Supersedes the standalone v231
    deploy (paste.rs/uA1UC).
Premarket intelligence initiative: A (v231) + B (v232) DONE; C (Daily Ops Digest)
de-scoped in favor of enriching Game Plan; D (gameplan ranking by realized edge) open.
