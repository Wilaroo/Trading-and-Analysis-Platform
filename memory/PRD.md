# TradeCommand / SentCom — Product Requirements

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.

## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)

## Completed this fork (2026-04-24 — Gate diag + DL Phase-1 + Post-Phase-13 fixes)

### Post-Phase-13 findings (user ran `scripts/revalidate_all.py` on Spark)
- **3 SHORT models PROMOTED** with real edge: SHORT_SCALP/1 min (417 trades, 53.0% WR, **1.52 Sharpe**, +6.5pp edge), SHORT_VWAP/5 mins (525 trades, 54.3% WR, **1.76 Sharpe**, +5.3pp), SHORT_REVERSAL/5 mins (459 trades, 53.4% WR, **1.94 Sharpe**, +7.6pp).
- **10/10 LONG setups REJECTED — `trades=0` in Phase 1** across every one. Root cause diagnosed: 3-class XGBoost softprob models collapsed to always-predicting DOWN/FLAT (triple-barrier PT=2×ATR vs SL=1×ATR + bearish training regime → DOWN-heavy labels). Neither the 13-layer confidence gate nor the DL class weights (which only affect TFT/CNN-LSTM) could touch this — the XGBoost training loop itself was uniform-weighted for class balance.
- Secondary: several shorts failed only on MC P(profit) or WF efficiency (SHORT_ORB 52.5% MC, SHORT_BREAKDOWN 68% WF).
- Multiple models have training_acc <52% (ORB 48.6%, GAP_AND_GO 48.5%, MOMENTUM 44.2%) → dead weight, should be deleted on next cleanup pass.

### Option A — Short-model routing SHIPPED
**Problem:** Scanner emits fine-grained setup_types like `rubber_band_scalp_short` / `vwap_reclaim_short`; training saves aggregate keys like `SHORT_SCALP` / `SHORT_VWAP` / `SHORT_REVERSAL`. The `predict_for_setup` path did a naive `setup_type.upper()` dict lookup → every promoted short model was unreachable from the live scanner path. The edge was being ignored.

**Fix:** New `TimeSeriesAIService._resolve_setup_model_key(setup_type, available_keys)` static resolver with priority chain:
  1. Exact uppercase match (preserves existing behavior)
  2. Legacy `VWAP_BOUNCE` / `VWAP_FADE` → `VWAP`
  3. Short-side routing: strip `_SHORT` suffix, try `SHORT_<base>` exact, then family substring match against 10 known SHORT_* models (SCALP → SHORT_SCALP, VWAP → SHORT_VWAP, etc.)
  4. Long-side: strip `_LONG`, try base, then family substring
  5. Fallback to raw (caller routes to general model)

Wired into `predict_for_setup` line 2492. Existing long-side VWAP_BOUNCE/VWAP_FADE routing preserved. Fully reversible — resolver is pure.

**Impact:** `rubber_band_scalp_short` → `SHORT_SCALP` (newly promoted), `vwap_reclaim_short` → `SHORT_VWAP`, `halfback_reversal_short` → `SHORT_REVERSAL`. All three promoted shorts are now reachable from the live scanner path.

**Regression coverage** — `backend/tests/test_setup_model_resolver.py` (10 tests): exact match, legacy VWAP mapping, 4 scalp-short variants, 3 vwap-short variants, 3 reversal-short variants, long-side suffix strip, unknown-setup fallback, short→base fallback when no SHORT models loaded, empty/None passthrough, VWAP_FADE_SHORT double-suffix case. All 10 pass.

### Option B — XGBoost class-balance fix SHIPPED
**Problem:** The 10/10 long rejects in Phase 13 were caused by 3-class XGBoost softprob collapsing to "always predict DOWN/FLAT" because `train_from_features` used uniform `sample_weight` for class balance. The triple-barrier label distribution (DOWN ≈ 50-60%, FLAT ≈ 30-40%, UP ≈ 10-15%) meant gradient pressure on the UP class was minimal.

**Fix:** Added `apply_class_balance: bool = True` kwarg to `TimeSeriesGBM.train_from_features`. When True (default), the method:
  1. Computes sklearn-balanced per-sample weights via new `dl_training_utils.compute_per_sample_class_weights(y, num_classes=3, clip_ratio=5.0)` — inverse-frequency, clipped 5×, mean-normalized to 1.0
  2. Multiplies element-wise into existing `sample_weights` (uniqueness) — both signals stacked
  3. Re-normalizes to mean==1 so absolute loss scale is unchanged
  4. DMatrix receives the blended weight vector → XGBoost sees ~5× more gradient pressure on UP class samples
  5. Logged as `class_balanced (per-class weights=[1.0, 1.67, 5.0])` in training output

Default=True so next retrain gets the fix automatically. `apply_class_balance=False` reproduces legacy behavior bit-for-bit.

**Regression coverage** — `backend/tests/test_xgb_class_balance.py` (4 tests):
  - Minority-class samples weigh ~5× majority-class samples for the Phase-13 skew pattern
  - `train_from_features(apply_class_balance=True)` actually passes class-balanced `weight=` into `xgb.DMatrix` (integration-style with stubbed xgb)
  - `apply_class_balance=False` → DMatrix weight= is None (legacy uniform)
  - Uniqueness + class-balance blend: element-wise product, mean-normalized, class skew preserved in the blend

Plus 3 new unit tests for `compute_per_sample_class_weights` in `test_dl_training_utils.py`.

**Full session suite: 46/46 passing** (9 gate-log + 23 DL utils + 4 XGB class balance + 10 setup resolver).

**Next step for user (on Spark):**
1. Save to Github → `git pull` on Spark
2. Restart backend
3. Kick off full retrain. Watch for log lines:
   - `Training from pre-extracted features: ..., class_balanced (per-class weights=[1.0, 1.6, 4.8])` — confirms class balance is active
   - `[TFT] Purged split: ... class_weights=[1.0, 0.45, 2.1] sample_w_mean=1.000` (on TFT/CNN-LSTM retrain)
4. Re-run `scripts/revalidate_all.py` — expect non-zero trade counts on LONG setups and more promotions.
5. (Optional) `export TB_DL_CPCV_FOLDS=5` before retrain for CPCV stability distribution in the scorecard.

## Completed prior fork (2026-04-24 — Gate-log diagnostic + DL Phase-1 closure)

### P0 Task 2 — TFT + CNN-LSTM: Phase-1 infra closed SHIPPED
Background: Phase 1 (sample-uniqueness weights, purged CPCV, scorecard, deflated Sharpe) was wired into XGBoost on 2026-04-20 but never plumbed into the DL training loops. Both models were training with plain `CrossEntropyLoss` on a chronological 80/20 split — the #1 likely cause of the <52% accuracy collapse and the `TFT signal IGNORED` / `CNN-LSTM signal IGNORED` log spam in the confidence gate.

**New module — `services/ai_modules/dl_training_utils.py`** (pure-numpy + torch, imports are lazy so tests run without GPU wheels):
  - `compute_balanced_class_weights(y, num_classes=3, clip_ratio=5.0)` — sklearn "balanced" inverse-frequency weights scaled so min=1, clipped at 5× so a tiny minority class doesn't explode gradients.
  - `compute_sample_weights_from_intervals(per_symbol_intervals, per_symbol_n_bars)` — López de Prado `average_uniqueness` **per symbol** (concurrency only meaningful within one bar axis), concatenated and normalized to mean=1.
  - `purged_chronological_split(intervals, n_samples, split_frac=0.8, embargo_bars=5)` — walk-forward split that drops train events whose [entry, exit] extends into the val-window plus embargo. Falls back to plain chronological when `intervals` is None → pipelines that skip interval tracking keep current behavior.
  - `run_cpcv_accuracy_stability(train_eval_fn, intervals, n_samples, …)` — opt-in CPCV stability measurement via env var `TB_DL_CPCV_FOLDS` (default 0 = OFF, so current training runtime is unchanged). When enabled, runs lightweight re-trains across `C(n_splits, n_test_splits)` purged folds and returns mean / std / negative_pct / scores for the scorecard.
  - `build_dl_scorecard(...)` — emits a scorecard dict compatible with the existing `timeseries_models.scorecard` persistence pattern: hit_rate=val_acc, ai_vs_setup_edge_pp, cpcv stability, grade A-F based on edge-vs-baseline. PnL fields stay 0 (DL classifiers don't produce PnL at train time).

**TFT wire-in (`services/ai_modules/temporal_fusion_transformer.py`)**:
  - Tracks `(entry_idx, exit_idx)` per sample per symbol via `build_event_intervals_from_triple_barrier` (same PT/SL/horizon as labeling, so spans match).
  - Concatenates intervals with a per-symbol global offset (`_cumulative_bar_offset += n_bars + max_symbols`) so cross-symbol samples never appear to overlap.
  - `nn.CrossEntropyLoss()` → `nn.CrossEntropyLoss(weight=class_weights_t, reduction='none')` + per-sample uniqueness multiply before the batch mean.
  - Plain 80/20 split → `purged_chronological_split(embargo_bars=5)`.
  - Optional CPCV stability pass (gated on `TB_DL_CPCV_FOLDS`) runs **after** main training; scorecard captures stability, then original best_state is restored.
  - Scorecard persisted to Mongo `dl_models.scorecard` (non-fatal on failure). Returns `class_weights`, `sample_weight_mean`, `purged_split`, `cpcv_stability`, `scorecard` in the train() result dict.

**CNN-LSTM wire-in (`services/ai_modules/cnn_lstm_model.py`)**: Same treatment.
  - `extract_sequence_features()` gains a backward-compatible `return_intervals=False` kwarg; when True also returns `entry_indices` + `n_bars`.
  - Auxiliary win-probability loss (class-2 binary target) is now also sample-weight scaled via `reduction='none'`.
  - Same class-weighted CE, purged split, CPCV-optional, scorecard persistence.

**Backward compat contract (explicit):**
  - Prediction paths untouched — `predict()` signatures unchanged on both models.
  - Saved checkpoints untouched — `_save_model` writes the same fields; scorecard is written via a follow-up `update_one`.
  - Default training runtime unchanged — CPCV is OFF by default.
  - When interval tracking fails (e.g. empty `global_intervals_chunks`), `purged_chronological_split` degrades to the plain chronological split, matching pre-change behavior.

**Regression coverage — `backend/tests/test_dl_training_utils.py` (20 tests, all passing):**
  - Class-weight math: inverse-frequency, clip at 5×, uniform input, missing-class clip, empty input.
  - Sample weights: unique events = uniform 1.0, overlapping events downweighted (standalone beats overlapping), multi-symbol concat, empty input.
  - Purged split: leaky train event purged, no-intervals → plain chronological, misaligned intervals → fallback, tiny dataset → empty.
  - Scorecard: edge + grade A for +11pp, grade F for negative edge.
  - CPCV env parsing: default 0, valid int, invalid string, negative clamped.
  - `run_cpcv_accuracy_stability` integration with real `CombinatorialPurgedKFold`.

**Full session suite: 29/29 passing** (9 gate-log + 20 DL utils).

**Next step for user (on Spark):**
1. Save to Github → `git pull` on Spark
2. Restart backend (`pkill -f "python server.py" && cd backend && nohup /home/spark-1a60/venv/bin/python server.py > /tmp/backend.log 2>&1 &`)
3. Kick off TFT + CNN-LSTM retrain via NIA (or worker job). Look for log lines like:
   `[TFT] Purged split: train=... val=... class_weights=[1.0, 0.45, 2.1] sample_w_mean=1.000`
4. Check `dl_models.<name>.scorecard.hit_rate` — should clear 0.52 so layers 9/10/11 stop being IGNORED.
5. (Optional, heavier) `export TB_DL_CPCV_FOLDS=5` before retrain to get CPCV stability distribution in the scorecard.
6. Re-run `analyze_gate_log.py --days 14` post-retrain to quantify Layer 9/10/11 revival.

### P0 Task 1 — `analyze_gate_log.py` SHIPPED
Purpose: Phase 13 revalidation rejected every setup (0 trades passing the 13-layer gate). Before touching models (TFT/CNN-LSTM triple-barrier rebuild), we need **empirical** data on which of the 13 layers actually add edge vs. pure friction. This script answers that.

- `/app/backend/scripts/analyze_gate_log.py` — reads `confidence_gate_log`, parses the free-form `reasoning` list to classify each line into one of the 13 layers via deterministic prefix regexes (contract with confidence_gate.py), extracts the signed score delta from the trailing `(+N…)` / `(-N…)` marker, and emits per-layer:
  - `fire_rate`, `positive_rate`, `negative_rate`
  - `mean_delta`, `median_delta`, `stdev_delta`
  - When `outcome_tracked=True` rows exist: `win_rate_when_positive`, `edge_when_positive` (WR lift over baseline), same for negative. **This is the friction-vs-edge measurement.**
  - A heuristic verdict per layer: `EDGE` / `FRICTION` / `NEUTRAL` / `LOW DATA` / `DORMANT` / `PENDING OUTCOMES`.
  - Writes `/tmp/gate_log_stats.md` (human) + `/tmp/gate_log_stats.json` (machine) and prints to stdout.
- CLI flags: `--days`, `--symbol`, `--setup`, `--direction`, `--outcome-only`, `--limit`.
- **Tests**: `/app/backend/tests/test_analyze_gate_log.py` — 9 tests: prefix classification for all 12 active layers + decision-line exclusion, delta extraction (positive/negative/trailing-clause/neutral), per-doc layer aggregation, decision-count + fire-rate math, outcome-conditional edge math (baseline + conditional WR), friction heuristic on a synthetic losing layer. All 9 pass in 0.10s.
- Zero changes to the gate itself — pure read-side analysis, safe to run while live and while Phase 13 revalidation is still in flight.

**Next step (user on Spark):**
```
cd ~/Trading-and-Analysis-Platform && git pull
PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/analyze_gate_log.py --days 30
# or, narrowed to outcome-tracked only:
PYTHONPATH=backend /home/spark-1a60/venv/bin/python backend/scripts/analyze_gate_log.py --days 90 --outcome-only
```
Share the `/tmp/gate_log_stats.md` output — that's the input to Task 2 (DL model rebuild scope).

## Completed prior fork (2026-04-23 — Layer 13 FinBERT + frontend + latency + confirm_trade)

### P1 — FinBERT Layer 13 wired into ConfidenceGate SHIPPED
- **Discovery**: `FinBERTSentiment` class was already built (`ai_modules/finbert_sentiment.py`) with a docstring explicitly reading *"Confidence Gate (INACTIVE): Ready to wire as Layer 12 when user enables it."* All 5,328 articles in MongoDB `news_sentiment` already pre-scored (scorer loop is running). Infrastructure was 95% there.
- **Wire-up** in `services/ai_modules/confidence_gate.py`:
  - `__init__` adds `self._finbert_scorer = None` (lazy init)
  - Class docstring extended with Layer 13 line
  - New Layer 13 block inserted between Layer 12 and decision logic (lines ~605-670)
  - Calls `self._finbert_scorer.get_symbol_sentiment(symbol, lookback_days=2, min_articles=3)`
  - Aligns score with trade direction (long: positive is good; short: negative is good)
  - Scales by scorer's `confidence` (low std across articles → stronger signal)
  - Point scale: +10 (strong aligned), +6 (aligned), +3 (mild), -3 (opposing), -5 floor (strong opposing)
  - Wrapped in try/except — FinBERT errors never fail the gate (graceful no-op with warning log)
- **Regression tests**: `backend/tests/test_layer13_finbert_sentiment.py` — 4 tests, all pass. Lazy-init pattern verified, docstring contract verified, bounded +10/-5 verified, import safety verified.
- **Test suite status**: 20/20 pass across all session's backend regression tests.

### Phase 13 revalidation (next step, user-run on Spark)
Layer 13 is live in the code but `revalidate_all.py` needs to run on Spark against historical trades to quantify Layer 13's contribution + recalibrate gate thresholds. This requires live DB + models + ensembles already on Spark — can't run from fork. Handoff command: `cd ~/Trading-and-Analysis-Platform/backend && /home/spark-1a60/venv/bin/python scripts/revalidate_all.py`.

### P1 — Frontend execution-health indicators SHIPPED
- **`TradeExecutionHealthCard.jsx`** — compact badge in SentCom header (next to ServerHealthBadge). Polls `/api/trading-bot/execution-health?hours=24` every 60s. 4 states with distinct color + icon: HEALTHY (emerald, <5% failure) / WATCH (amber, 5-15%) / CRITICAL (red, ≥15%) / LOW-DATA (grey, <5 trades). Hover tooltip shows raw stats.
- **`BotHealthBanner.jsx`** — full-width red banner that **only renders when alert_level is CRITICAL**. Silent otherwise. Shows top 3 failing setups + total R bled. Session-dismissable via ×. Integrated at top of SentCom embedded mode (above ambient effects).

Both components use `memo`, 60s poll cadence, `data-testid` attributes, and follow existing `ServerHealthBadge` conventions. Lint clean.

### P1 — `confirm_trade` false-negative FIXED
**Root cause:** `TradeExecution.confirm_trade` returned `trade.status == TradeStatus.OPEN` only, so trades correctly filtered by the strategy phase gate (`SIMULATED`, `PAPER`) or pre-trade guardrail (`VETOED`) reported as API failures. The router then raised 400 "Failed to execute trade" on legitimate pipeline outcomes — misleading when demoing trades or using the confirmation mode UI.

**Fix:**
- `/app/backend/services/trade_execution.py` — confirm_trade now treats `{OPEN, PARTIAL, SIMULATED, VETOED, PAPER}` as the handled-successfully set. Genuine `REJECTED`, stale-alert, and missing-trade paths still return False.
- `/app/backend/routers/trading_bot.py` — `POST /api/trading-bot/trades/{id}/confirm` now returns 200 with the actual status + a status-specific message (executed / simulated / paper / vetoed / partial). 404 reserved for missing trade, 400 only for real rejections (with `reason` in detail).

**Regression coverage:** `/app/backend/tests/test_confirm_trade_semantics.py` — 8 tests covering every terminal status + stale-alert + missing-trade. All pass.

### P0 — Queue schema stripping bracket fields FIXED
**Root cause:** `OrderQueueService.queue_order()` built its insert document from a hardcoded whitelist (`symbol/action/quantity/order_type/limit_price/stop_price/trade_id/...`) that silently dropped `type`, `parent`, `stop`, `target`, and `oca_group`. The Windows pusher then received a degenerate payload and could not execute atomic IB brackets — the final blocker for Phase 3 bracket orders.

**Fix:**
- `/app/backend/services/order_queue_service.py` — `queue_order()` now detects `type == "bracket"` and preserves `parent`, `stop`, `target`, `oca_group` in the stored doc. For bracket orders `order_type` is stamped as `"bracket"` and flat `action/quantity` are nulled (they live inside `parent`). Regular flat orders are unchanged.
- `QueuedOrder` Pydantic model now uses `model_config = ConfigDict(extra="allow")` and explicitly declares `type/parent/stop/target/oca_group`. `action`/`quantity` relaxed to `Optional` (bracket shape has them inside `parent`).
- `/app/backend/routers/ib.py` — `QueuedOrderRequest` mirrors the same bracket fields + `extra="allow"`. The `/api/ib/orders/queue` endpoint now branches cleanly for bracket vs. flat orders and validates each shape independently.

**Regression coverage:** `/app/backend/tests/test_queue_bracket_passthrough.py` — 5 tests locking in: bracket fields preserved, `oca_group` preserved, flat orders unaffected, Pydantic model accepts bracket shape, Pydantic accepts unknown-future fields. All 8 related tests pass (5 new + 3 existing bracket-wiring).

**Impact:** Windows pusher will now receive the full bracket payload on its next poll of `/api/ib/orders/pending`. Atomic IB bracket orders activate end-to-end — no more naked positions on restart/disconnect.

## Completed in prior session (2026-04-22 — fork 2, execution hardening batch)
### Dashboard truthfulness fix — retag bot-side cancels (2026-04-22 evening)
Audit revealed all 6,632 "cancelled" bot_trades were `close_reason=simulation_phase` bot-side filters, not broker cancels. Added dedicated `TradeStatus` values (`PAPER`, `SIMULATED`, `VETOED`) so future filters don't pollute the `cancelled` bucket. Migration script `scripts/retag_bot_side_cancels.py` retro-tagged 6,632 docs; execution-health now reports real failure rate (17.07% — dominated by already-disabled vwap_fade_short).

### Phase 3 — Bot-side bracket caller swap (2026-04-22 evening)
`trade_executor_service.place_bracket_order` + `_ib_bracket` / `_simulate_bracket`: queues an atomic `{"type":"bracket",...}` payload to the pusher with correctly-computed parent LMT offset (scalp-aware), child STP/LMT target, and GTC/outside-RTH flags. `trade_execution.execute_trade` now calls `place_bracket_order` first; on `bracket_not_supported` / `alpaca_bracket_not_implemented` / missing-stop-or-target it falls back to the legacy `execute_entry` + `place_stop_order` flow. Result shape is translated so downstream code doesn't change.

### Phase 4 — Startup orphan-position protection (2026-04-22 evening)
`PositionReconciler.protect_orphan_positions`: scans `_pushed_ib_data["positions"]`, finds any with no working bot-side stop, places emergency STP using intended stop_price if known else 1% risk from avgCost (SELL for longs, BUY for shorts). Trade docs updated with the new stop_order_id and saved. Wired into `TradingBotService.start()` as a fire-and-forget background task (15s delay so pusher has time to publish positions). New endpoint `POST /api/trading-bot/positions/protect-orphans?dry_run=true|false&risk_pct=0.01` for manual triage.

### Autopsy fallback — use realized_pnl when exit_price missing
`summarize_trade_outcome` now falls back to `realized_pnl` when `exit_price=0/None` and `r_multiple` can't be recomputed (fixes the imported_from_ib case where PD bled $7.3k but showed `verdict=unknown`).

### New pytest coverage (2026-04-22 evening — 27 new tests, all passing)
- `tests/test_orphan_protection.py` (7 tests): pusher-disconnected guard, already-protected accounting, unprotected tracked trade gets stop, untracked short derives above-entry stop, dry-run safety, zero-avgcost skip, flat-position ignore.
- `tests/test_bracket_order_wiring.py` (3 tests): simulated 3-legged return shape, Alpaca fallback signal, missing-stop-or-target graceful decline.
- `tests/test_trade_autopsy.py` +2 tests: realized_pnl fallback when exit_price=0.

### Pusher contract spec delivered
`/app/memory/PUSHER_BRACKET_SPEC.md` — full bracket payload contract, reference `ib_insync` handler code, ACK response shape, fallback signaling, smoke-test commands. Pusher-side implementation pending on Windows PC.


### Alert de-dup wired into scan loop
`services/trading_bot_service._scan_for_opportunities` runs the `AlertDeduplicator` hard veto BEFORE confidence-gate evaluation. Blocks repeat fires on already-open `(symbol, setup, direction)` and enforces a 5-min cooldown. This stops the PRCT-style stacking disaster where 8 identical vwap_fade_short alerts each bled -8.9R.

### Trade Autopsy API endpoints
Added to `routers/trading_bot.py`:
- `GET /api/trading-bot/trade-autopsy/{trade_id}` — full forensic view: outcome, stop-honor, slippage_R, gate snapshot, scanner context.
- `GET /api/trading-bot/recent-losses?limit=N` — list worst-R trades for triage workflow.

### IB `place_bracket_order()` primitive (Phase 1 of bracket migration)
`services/ib_service.py` now exposes an atomic native IB bracket: parent LMT/MKT + OCA stop + OCA target. Uses `ib_insync` with explicit `parentId`, `ocaGroup`, `ocaType=1`, and `transmit=false/false/true` flags. Includes directional sanity validation (long: stop<entry<target, short: reverse) and emits a unique `oca_group` id per trade. Once the parent fills, the stop and target live at IB as GTC — the bot can die/restart and the stop remains enforced.

### Pre-execution guard rails
New pure module `services/execution_guardrails.py` + wired into `services/trade_execution.execute_trade` BEFORE `trade_executor.execute_entry`. Rejects:
- Stops tighter than 0.3×ATR(14) (or 10 bps of price if ATR unavailable)
- Positions whose notional exceeds 1% of account equity (temporary cap while bracket migration is in progress)
Failed trades are marked `TradeStatus.REJECTED` with `close_reason="guardrail_veto"`.

### Pytest coverage (24 new tests, 82/82 passing in exec-hardening suite)
- `tests/test_alert_deduplicator.py` (8 tests): open-position veto, cooldown window, symbol/setup/direction independence, ordering precedence.
- `tests/test_execution_guardrails.py` (10 tests): USO-style tight-stop rejection, ATR vs pct fallback, notional cap, no-equity fallback.
- `tests/test_trade_autopsy.py` (6 tests): long/short verdict, stop-honored vs blown-through slippage, r_multiple precedence.


## Completed in this session (2026-04-21 — continued fork)
### Phase 8 DMatrix Fix & Bet-Sizing Wire-In (2026-04-21)
**Problem 1 (broadcast)**: Phase 8 ensemble failed with `ValueError: could not broadcast input array from shape (2382,) into shape (2431,)` — inline FFD augmentation was dropping 49 lookback rows vs the pre-computed `features_matrix`.
**Fix 1**: Removed inline FFD augmentation; reverted to zero-fill fallback so row counts stay consistent. Pytest suite expanded.

**Problem 2 (DMatrix)**: After broadcast fix, Phase 8 failed with `TypeError: Expecting data to be a DMatrix object, got: numpy.ndarray` — `TimeSeriesGBM._model` is an `xgb.Booster` (not `XGBClassifier`) which requires `DMatrix` input.
**Fix 2**: `training_pipeline.py` Phase 8 sub_model + setup_model predicts now wrap features in `xgb.DMatrix(..., feature_names=sm._feature_names)` before calling `.predict()`. Added `test_phase8_booster_dmatrix.py` (3 regression tests including source-level guard against future regressions).
**Verification (user, 2026-04-21 15:24Z)**: Phase 8 now producing real ensembles — 5/10 done at time of writing: meanrev=65.6%, reversal=66.3%, momentum=58.3%, trend=55.3%. All binary meta-labelers with ~44% WIN rate on 390K samples.

### Data Pipeline Audit & Cleanup (2026-04-21) — COMPLETED
- **`/backend/scripts/diagnose_alert_outcome_gap.py`** — per-setup funnel audit (alerts → orders → filled → closed → with_R) with `classify_leak` helper (ratio-based, not binary) and cancellation tracking.
- **`/backend/scripts/backfill_r_multiples.py`** — pure-math R-multiple backfill on closed bot_trades. Backfilled **141 docs** (post cleanup = 211 total with r_multiple). Idempotent.
- **`/backend/scripts/backfill_closed_no_exit.py`** — recovers exit_price from `fill_price + realized_pnl + shares + direction` on orphaned `status=closed, exit_price=None` docs. Recovered **70/70 orphans** (r_multiple_set=70).
- **`/backend/scripts/collapse_relative_strength.py`** — migrated `relative_strength_leader/laggard` → `relative_strength_long/short`. **Renamed 29,350 docs**. Eliminates "scanner drift" from the audit.
- **Tests**: `test_data_pipeline_scripts.py` (25 tests) — long/short R-multiple math, direction aliases, classify_leak ratio thresholds, exit inference roundtrip. 25/25 passing.

### 🚨 CRITICAL FINDINGS FROM AUDIT (2026-04-21)
After data cleanup, the truth is clear:
1. **`vwap_fade_short` is catastrophic**: 51 trades, 8.9% WR, **avg_R = -9.57** (losing 9.57× risk per trade). Total bleed: ~-488R. Stops are set correctly but **not being honored at IB** — stops are 2-4¢ wide, exits are $0.40-$7.84 past stop. Root cause: either no STP order placed at IB, or stop distance < tick buffer / noise floor.
2. **97% order cancellation rate**: on top setups, 1,216/1,220 `second_chance` orders cancel before fill (likely stale limit prices). Similar for squeeze, vwap_bounce.
3. **Only 211 total filled+closed trades exist across all setups** — too few to train Phase 2E CNNs. Needs weeks of live trading (with fixed stop execution) to accumulate.
4. **Only `vwap_fade_long` has real positive EV** (n=24, WR=58%, avg_R=+0.81 → ~0.36R/trade EV). Everything else scratches or bleeds.
5. **18/239 shorts have inverted stops** (stop below entry) — 7.5% data corruption, minor fix.


- **`/backend/services/ai_modules/ensemble_live_inference.py`** — runs full ensemble meta-labeling pipeline at trade-decision time: loads sub-models (5min/1h/1d) + setup 1-day model + `ensemble_<setup>` → extracts ensemble features → predicts `P(win)` on current bar. Degrades gracefully (returns `has_prediction=False` with reason) if any piece is missing.
- **Model cache (10-min TTL, thread-safe)** — `_cached_gbm_load` pins loaded XGBoost Boosters in memory across gate calls. Auto-evicts post-training via `clear_model_cache()` hook in `training_pipeline.py`. Measured speedup on DGX Spark: cold=2.33s, warm=0.33s (**7× faster**), partial miss=0.83s (**2.8×**). Enables ~180 evals/min/core production throughput.
- **`bet_size_multiplier_from_p_win(p_win)`** — Kelly-inspired tiered ramp:
  - `p_win < 0.50` → 0.0 (**force SKIP** per user requirement)
  - `0.50-0.55` → 0.50× (half size, borderline edge)
  - `0.55-0.65` → 1.00× (full size)
  - `0.65-0.75` → 1.25× (scale up)
  - `≥ 0.75` → 1.50× (max boost, cap prevents over-leverage)
- **`confidence_gate.py` Layer 12** — calls `_get_ensemble_meta_signal()` (async wrapper over thread pool) and contributes:
  - +15 points if `p_win ≥ 0.75`, +10 if `≥ 0.65`, +5 if `≥ 0.55`, 0 if `≥ 0.50`
  - Position multiplier scaled via `bet_size_multiplier_from_p_win`
  - **Hard SKIP** when `p_win < 0.5` overrides any positive score
- **`SCANNER_TO_ENSEMBLE_KEY`** — maps 35 scanner setup names (VWAP_BOUNCE, SQUEEZE, RUBBER_BAND, OPENING_DRIVE, etc.) → 10 ensemble config keys, PLUS canonical key pass-through (`REVERSAL`, `BREAKOUT`, `MEAN_REVERSION`, etc. accepted directly).
- **Live verification on DGX Spark (2026-04-21)**:
  - AAPL / BREAKOUT_CONFIRMED → `p_win=40%` → correctly hard-skipped (ensemble_breakout, setup_dir=flat)
  - NVDA / TREND_CONTINUATION → `p_win=22%` → correctly hard-skipped (ensemble_trend)
  - TSLA / REVERSAL → `p_win=50.04%` → correctly routed to borderline (0.5× size, ensemble_reversal)
- **Tests**: `test_ensemble_live_inference.py` (14 tests) — bet-size ramp (monotonic, boundary, cap), graceful miss paths, full mocked inference, model cache reuse/eviction/TTL. **44/44 total Phase 8 / ensemble / preflight / metrics tests passing.**



### Phase 2/2.5 FFD name-mismatch crash — FIXED (P0)
- **Symptom**: `scalp_1min_predictor: expected 57, got 52` when Phase 2 started after Phase 1 completed.
- **Root cause**: `_extract_setup_long_worker` / `_extract_setup_short_worker` augment `base_matrix` with 5 FFD columns when `TB_USE_FFD_FEATURES=1` (46 → 51). The outer Phase 2/2.5 loop in `training_pipeline.py` built `combined_names` from the NON-augmented `feature_engineer.get_feature_names()` (46) + setup names (6) → 52 names vs 57 X cols.
- **Fix**: `training_pipeline.py` lines 1426 & 1614 now wrap base_names with `augmented_feature_names(...)` from `feature_augmentors.py`, which appends the 5 FFD names when the flag is on.
- **Guardrail test**: `backend/tests/test_phase2_combined_names_shape.py` (4 tests, all passing) — rebuilds Phase 2 & 2.5 combined_names exactly as the training loop does and asserts `len(combined_names) == X.shape[1]` in both FFD-ON and FFD-OFF modes. Catches any regression of this bug class.

### Phase 8 Ensemble — REDESIGNED as Meta-Labeler (2026-04-21)
**Problem discovered**: All 10 ensemble models had identical metrics (accuracy=0.4542..., precision_up=0, precision_down=0) — degenerate "always predict FLAT" classifiers. Root cause: (a) 3-class prediction on universe-wide data collapsed to majority class (45% FLAT); (b) no setup-direction filter → training distribution ≠ inference distribution; (c) no class weighting.

**Fix (López de Prado meta-labeling, ch.3)**:
- Each `ensemble_<setup>` now REQUIRES its `setup_specific_<setup>_1day` sub-model to be present (training skips cleanly otherwise)
- Filters training bars to those where setup sub-model signals UP or DOWN (matches live inference)
- Converts 3-class TB target → binary WIN/LOSS conditioned on setup direction:
  - setup=UP + TB=UP → WIN(1)
  - setup=DOWN + TB=DOWN → WIN(1)
  - else → LOSS(0)
- Class-balanced `sample_weights` (inverse class frequency) to prevent majority-class collapse
- Skips model if <50 of either class present
- Tags model with `label_scheme=meta_label_binary`, `meta_labeler=True`, `setup_type=<X>` for downstream bet-sizing consumers
- Implements Phase 2C roadmap item (meta-labeler bet-sizing) by consolidating it into Phase 8
- Zero live-trading consumers at time of fix → safe redesign (dormant models)
- `backend/tests/test_ensemble_meta_labeling.py` — 13 tests covering label transformation (all 6 direction×TB combos), FLAT exclusion, class-balancing weights (balanced/imbalanced/pathological cases), and end-to-end synthetic pipeline

### CNN Metrics Fix (2026-04-21)
**Problem discovered**: All 34 per-setup CNN models showed `metrics.accuracy=1.0`. UI and scorecard read this field → misleading. Root cause: `accuracy` was saving the 17-class pattern-classification score, which is tautologically 1.0 because every sample in `cnn_<setup>_<bar_size>` has the same setup_type label. Real predictive metric `win_auc` was already computed (~0.55-0.85 range) but not surfaced.

**Fix**:
- `cnn_training_pipeline.py` now sets `metrics.accuracy = win_auc` (the actual win/loss AUC)
- Added full binary classifier metrics: `win_accuracy`, `win_precision`, `win_recall`, `win_f1`
- Kept `pattern_classification_accuracy` as debug-only reference
- `backend/scripts/migrate_cnn_accuracy_to_win_auc.py` — idempotent one-shot migration to update the 34 existing records in `cnn_models`
- `backend/tests/test_cnn_metrics_fix.py` — 5 tests covering perfect/realistic/degenerate/single-class cases + migration semantics
- Promotion gate unchanged (already correctly used `win_auc >= 0.55`)

### Pre-flight Shape Validator — EXTENDED (P1)
- `/backend/services/ai_modules/preflight_validator.py` — runs in `run_training_pipeline` immediately after disk-cache clear, BEFORE any phase kicks off heavy work.
- **Now covers every XGBoost training phase** (as of 2026-04-21):
  - `base_invariant` — `extract_features_bulk` output cols == `get_feature_names()` len (the master invariant; catches hypothetical future FFD-into-bulk drift)
  - **Phase 2 long** — runs `_extract_setup_long_worker`, rebuilds combined_names, asserts equality
  - **Phase 2.5 short** — runs `_extract_setup_short_worker`, same
  - **Phase 4 exit** — runs `_extract_exit_worker`, asserts 46 + len(EXIT_FEATURE_NAMES)
  - **Phase 6 risk** — runs `_extract_risk_worker`, asserts 46 + len(RISK_FEATURE_NAMES)
  - **Phases 3/5/5.5/7/8 static** — validates VOL/REGIME/SECTOR_REL/GAP/ENSEMBLE feature name lists are non-empty and dedup'd (their X matrix is built by column-write construction and is correct-by-construction when the base invariant holds)
- Uses 600 synthetic bars under current env flags (`TB_USE_FFD_FEATURES`, `TB_USE_CUSUM`).
- **Runtime**: **~2.0 seconds** for all 10 phases with FFD+CUSUM on (measured).
- Fails the retrain fast with a structured error if ANY mismatch is found (vs a 44h retrain crashing halfway).
- Result stored in `training_status.preflight` for the UI.
- Safe-guarded: a bug in the validator itself is logged as a warning and does NOT block training.
- `backend/tests/test_preflight_validator.py` — 5 tests: all-phases happy path with all flags on, FFD-off pass, only-requested-phases scoping, **negative test** reproducing the 2026-04-21 bug (asserts diff=+5), and **negative test** for base invariant drift (simulates hypothetical future FFD-into-bulk injection and asserts the invariant check catches it).
- **Next step for user**: restart retrain; Phase 2 onwards should now proceed cleanly AND every future retrain is protected.

## Completed in this session (2026-04-20)
### Phase 0A — PT/SL Sweep Infrastructure — DONE
- `/backend/services/ai_modules/triple_barrier_config.py` — get/save per (setup, bar_size, side)
- `/backend/scripts/sweep_triple_barrier.py` — grid sweep over PT×SL picking balanced class distribution
- Long + short workers now read per-setup config; callers resolve configs from Mongo before launching workers
- New API `GET /api/ai-training/triple-barrier-configs`; NIA panel shows PT/SL badge per profile

### Phase 1 — Validator Truth Layer — DONE (code), pending Spark retrain to activate
- **1A Event Intervals** (`event_intervals.py`): every sample tracked as `[entry_idx, exit_idx]`; concurrency_weights computed via López de Prado avg_uniqueness formula
- **1B Sample Uniqueness Weights** in `train_from_features(sample_weights=...)` — non-IID correction
- **1C Purged K-Fold + CPCV** (`purged_cpcv.py`) — `PurgedKFold` and `CombinatorialPurgedKFold` with embargo + purging by event interval overlap
- **1D Model Scorecard** (`model_scorecard.py`) — `ModelScorecard` dataclass + composite grade A-F from 7 weighted factors
- **1E Trial Registry** (`trial_registry.py`) — Mongo `research_trials` collection; K_independent from unique feature_set hashes
- **1F Deflated Sharpe Ratio** (`deflated_sharpe.py`) — Bailey & López de Prado 2014, Euler-Mascheroni expected-max-Sharpe, skew/kurt correction
- **1G Post-training validator** now auto-builds scorecard + DSR + records trial after every validation
- **1H Validator** persists scorecard on both `model_validations.scorecard` and `timeseries_models.scorecard`
- **1I UI** — `ModelScorecard.jsx` color-coded bundle display + expander button per profile in `SetupModelsPanel.jsx`
- **APIs**: `GET /api/ai-training/scorecard/{model_name}`, `GET /api/ai-training/scorecards`, `GET /api/ai-training/trial-stats/{setup}/{bar_size}`

### Phase 2A — CUSUM Event Filter — DONE
- `cusum_filter.py` — López de Prado symmetric CUSUM; `calibrate_h` auto-targets ~100 events/yr; `filter_entry_indices` honors a min-distance guard
- Wired into 3 workers (`_extract_symbol_worker`, `_extract_setup_long_worker`, `_extract_setup_short_worker`) with flag `TB_USE_CUSUM`

### Phase 2B — Fractional Differentiation — DONE (2026-04-21)
- `fractional_diff.py` — FFD (fixed-width window) + adaptive d (binary-search lowest ADF-passing d)
- `feature_augmentors.py` — flag-gated `augment_features()` appends 5 FFD cols (`ffd_close_adaptive`, `ffd_close_03/05/07`, `ffd_optimal_d`)
- Wired into all 3 worker types; 46-col base becomes 51-col when `TB_USE_FFD_FEATURES=1`
- `test_ffd_pipeline_integration.py` — 6 new tests verify end-to-end shape, finiteness, and all-flags-on combination

### Phase 2D — HRP/NCO Portfolio Allocator — DONE (code, pending wire-up)
- `hrp_allocator.py` — López de Prado Hierarchical Risk Parity + Nested Clustered Optimization
- Not yet wired into `trading_bot_service.py` (P1 backlog)

### Tests — 41 passing (+30 new)
- `test_phase1_foundation.py` — 19 tests covering event intervals, purged CV, DSR, scorecard
- `test_trial_registry.py` — 4 tests (mongomock)
- `test_sample_weights_integration.py` — 2 tests end-to-end
- `test_triple_barrier_config.py` — 5 tests (mongomock)
- Existing `test_triple_barrier_labeler.py`, `test_timeseries_gbm_triple_barrier.py` updated for 3-tuple worker return

### Pending on Spark (for Phase 1 to activate)
1. Save to Github → `git pull` on Spark
2. `pip install mongomock` in Spark venv (if running pytest)
3. Restart backend (`pkill server.py` + start)
4. Run PT/SL sweep: `PYTHONPATH=$HOME/Trading-and-Analysis-Platform/backend python backend/scripts/sweep_triple_barrier.py --symbols 150`
5. Kick off full retrain via NIA "Start Training" button
6. After retrain finishes, every model in Mongo `timeseries_models` will have a `scorecard` field; NIA page will show grades + expand-on-click full bundle

## Earlier in this session
### XGBoost & setup models rewired to triple-barrier labels (P0) — DONE
- `_extract_symbol_worker` (Phase 1 generic directional, `timeseries_gbm.py`) now produces
  triple-barrier 3-class labels (0=DOWN/SL-hit, 1=FLAT/time-exit, 2=UP/PT-hit) instead of
  binary `future > current`. Feature cache key bumped to `_tb3c` to invalidate stale entries.
- `_extract_setup_long_worker` (Phase 2) and `_extract_setup_short_worker` (Phase 2.5) switched
  from noise-band 3-class to triple-barrier 3-class. Shorts use negated-series trick so the
  lower barrier == PT for a short.
- Phase 7 regime-conditional models switched from binary `future_ret > 0` to triple-barrier
  3-class; `train_from_features(num_classes=3)`.
- Phase 8 ensemble meta-learner switched from ±0.3% threshold 3-class to triple-barrier
  (using ATR-scaled barriers with `max_bars = anchor_fh`).
- `TimeSeriesGBM.train()` and `train_vectorized()` now delegate to
  `train_from_features(num_classes=3)` — single canonical training path.
- `TimeSeriesGBM.predict()` handles 3-class softmax output (shape (1,3)) → `{down, flat, up}`.
- Persistence: `_save_model()` writes `num_classes` and `label_scheme`
  (`triple_barrier_3class` or `binary`); `_load_model()` restores `_num_classes`.
- `get_setup_models_status()` now returns `label_scheme` per profile from DB so UI can
  distinguish freshly-trained triple-barrier models from legacy binary models.
- NIA `SetupModelsPanel` shows a green **Triple-Barrier** badge for new models and a red
  **Legacy binary** warning for models that need retraining.

### Test coverage
- `backend/tests/test_triple_barrier_labeler.py` (8 tests, unchanged).
- NEW: `backend/tests/test_timeseries_gbm_triple_barrier.py` (3 tests):
  - `_extract_symbol_worker` returns int64 3-class targets.
  - End-to-end train_from_features(num_classes=3) + XGBoost softprob predict returns (N,3).
  - `get_model_info`/`get_status` surface `num_classes` and `label_scheme`.
- All 11 tests pass (`PYTHONPATH=backend python -m pytest backend/tests/…`).

### Downstream consumers — verified wired to new scheme (no code changes needed):
- `predict_for_setup` (timeseries_service.py): already handles 3-class softprob output →
  returns `{direction: up/down/flat, probability_up/down/flat, confidence, num_classes}`.
- `confidence_gate.py`: consumes via `_get_live_prediction` → `predict_for_setup` (up/down/flat),
  plus `_get_tft_signal`, `_get_cnn_lstm_signal`, `_get_cnn_signal`, `_get_vae_regime_signal`
  which already return 3-class direction strings.
- TFT + CNN-LSTM `predict()`: direction_map {0:down, 1:flat, 2:up} — matches triple-barrier
  class indices (fixed earlier this session).
- Scanner / Trading Bot / Learning Loop / Trade Journal / NIA / SentCom Chat: consume
  `direction` as semantic string ("up"/"down"/"flat" for prediction, "long"/"short" for trade
  side). No changes needed — prediction interface unchanged.

### Retrain plan (USER — run on Spark once Phase 13 revalidation finishes)
1. Stop the current bot and revalidation script.
2. Clear the NVMe feature cache so `_tb3c` keys rebuild:
   `mongo tradecommand --eval 'db.feature_cache.deleteMany({})'`
3. Kick off a full retrain (Phase 1 → Phase 8): `python backend/scripts/local_train.py`
   (or the worker job if available). This will produce triple-barrier models that
   overwrite the old binary/noise-band models in `timeseries_models` collection (protected
   by the best-model promotion gate — new model must beat accuracy of current active).
4. After training, rerun `python backend/scripts/revalidate_all.py` to validate the new
   models against the fail-closed gates.
5. Retrain DL models (TFT, CNN-LSTM, VAE) via the Phase 11 job so their metadata matches
   (`regime_diversity`, `win_auc`).
6. Verify the NIA page shows green **Triple-Barrier** badges on every trained profile,
   and that 0-trade filter rate drops below 100% on sample symbols.


### P0 Morning Briefing bogus-position bug — RESOLVED
- Root-caused: `MorningBriefingModal.jsx` calls `/api/portfolio`, which pulls IB-pushed positions. When marketPrice=0 on restart, `gain_loss = 0 − cost_basis` produced fake -$1.2M.
- Fix: `backend/routers/portfolio.py` — added `quote_ready` flag per position and `quotes_ready` in summary; trusts IB's `unrealizedPNL` until live quote arrives; filters zero-share rows.
- Fix: `frontend/src/components/MorningBriefingModal.jsx` — shows amber "awaiting quotes" badge instead of fake PnL. Flatten button removed (wrong place for destructive admin action).

### New `POST /api/portfolio/flatten-paper` endpoint
- Guard rails: `confirm=FLATTEN` token, paper-account-only (code starts with 'D'), 120s cooldown, pre-flight cancel of stale `flatten_*` orders, pusher-freshness check (refuses if last_update >30s old).

### IB Pusher double-execution bug — FIXED
- Root cause: TWS mid-session auto-upgrade + fixed pusher clientId=15 → IB replayed stale session state as new orders, causing 2×-3× fills per flatten order.
- `documents/scripts/ib_data_pusher.py` — added `_recently_submitted` in-memory idempotency cache stamping each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10 min.
- `documents/scripts/StartTradeCommand.bat` — pusher clientId now randomized 20–69 per startup so stale TWS sessions can't replay.

### 🚨 Credential leak — FIXED
- Paper password was hardcoded in `.bat` and committed to GitHub. Moved to local-only `.ib_secret`, `.gitignore` updated, `README_SECRETS.md` added.
- User rotated paper password + created `.ib_secret` on Windows.

### Validator fail-open paths — LAYER 1 FIXED, LAYER 2 IDENTIFIED AND FIXED
- **Layer 1 (earlier session)**: `Insufficient trades → promoting by default` → replaced with 9 fail-closed gates (n≥30, Sharpe≥0.5, edge≥5pp, MC P(profit)≥55%, etc.)
- **Layer 2 (today, 2026-04-20)**: when a failing model had no prior baseline to roll back to, validator silently flipped `decision["promote"] = True` and saved the broken model as baseline. Now rejects outright and does NOT write a baseline; trading bot reads baselines as the live-trading gate, so rejected models cannot leak into prod.
- `backend/scripts/revalidate_all.py` — fixed dict-vs-string bug in SETUP_TRAINING_PROFILES iteration.

### Phase 13 revalidation — RUNNING
- Launched against 20 unique setup types (best bar_size each, from 34 trained pairs).
- Uses fixed fail-closed validator + new layer-2 fix.
- ETA ~60-90 min. First run pending verification.

## Active P0 Blockers
### 🟢 Pusher double-execution bug — FIXED (pending verification on Windows)
- **Root cause**: TWS mid-session auto-upgrade caused the pusher's IB client connection (fixed clientId=15) to reconnect with stale session state. Previously-submitted MKT orders got replayed by TWS as if new, causing 2×-3× execution for each flatten order.
- **Fixes applied (2026-04-20)**:
  1. `ib_data_pusher.py` — `_recently_submitted` in-memory cache stamps each `order_id → (timestamp, ib_order_id)` immediately after `placeOrder()`. Any duplicate poll of same order_id is blocked + reported rejected within 10-min window.
  2. `StartTradeCommand.bat` — pusher clientId now randomized 20–69 each startup (`set /a IB_PUSHER_CLIENT_ID=%RANDOM% %% 50 + 20`). TWS can't replay a clientId it's never seen.
  3. `routers/portfolio.py` flatten endpoint — refuses to fire if pusher snapshot > 30s old (prevents flattening against stale positions).
  4. Pre-flight cancel of prior `flatten_*` orders (already done in first pass).
- **Verification plan for next session**: re-enable TWS API, restart pusher with new fixes, queue a single test order, confirm IB shows exactly one fill.

### 🚨 Security — paper password was committed to git
- `StartTradeCommand.bat` had `set IB_PASSWORD=Socr1025!@!?` hardcoded (line 30, pre-fix).
- **Fixed**: password moved to local `.ib_secret` file loaded via `call "%REPO_DIR%\.ib_secret"`. `.gitignore` updated to cover `*.secret`. `documents/scripts/README_SECRETS.md` explains setup.
- **User action required**: rotate the paper password in IB Account Management, then create `.ib_secret` on the Windows PC with the new password.

## P1 Outstanding
- Phase 13 revalidation: `backend/scripts/revalidate_all.py` against the fixed fail-closed validator (was next after Morning Briefing)
- Phase 6 Distributed PC Worker: offload CNN/DL training to Windows PC over LAN
- Rebuild TFT / CNN-LSTM with triple-barrier targets (binary up/down → majority-class collapse)
- Wire FinBERT into confidence gate as Layer 12
- Wire confidence gate into live validation

## Model Inventory & Deprecation Status (2026-04-21)

| Layer | Model family | Count | Status | Notes |
|---|---|---|---|---|
| **Sub-models** | XGBoost `setup_specific_<setup>_<bs>` | 17 long + 17 short = 34 | ✅ Keep (retraining now) | Tabular direction predictor, uses FFD+CUSUM+TB |
| | XGBoost `direction_predictor_<bs>`, `vol_<bs>`, `exit_*`, `risk_*`, `regime_*`, `sector_*`, `gap_*` | ~65 | ✅ Keep | Generic + specialist tabular models |
| | DL `cnn_lstm_chart` | 1 | ✅ Keep | 1D CNN+LSTM on OHLCV sequences; feeds Phase 2E tabular arm |
| | DL `tft_<bs>`, `vae_<bs>` | 2 | ✅ Keep | Temporal fusion + regime encoder |
| | FinBERT sentiment | 1 | ✅ Keep | Layer 12 of confidence gate (pending wire-in) |
| | Legacy `cnn_<setup>_<bs>` | 34 | 🗑 **Deprecate post-Phase 2E** | Strict subset of Phase 2E; no unique value |
| **Meta-labelers** | XGBoost `ensemble_<setup>` (Phase 8) | 10 | ✅ Keep | Tabular meta-labeler, P(win). **Phase 2C equivalent.** Just redesigned 2026-04-21 |
| | Phase 2E `phase2e_<setup>` (visual+tabular) | 0 | 🔨 **Build** | Hybrid multimodal meta-labeler; will supersede legacy CNN |
| **Fusion** | `P(win)_final = w_tab·P_tab + w_vis·P_vis` | 0 | 🔮 Future | After both meta-labelers prove individual edge |

**Net reduction once Phase 2E ships**: 34 legacy CNN models → ~10 Phase 2E models. Phase 9 removed from training pipeline. Full-retrain time drops from ~7h to ~5h.

## Post-Retrain Roadmap (proper sequencing)

The order below is intentional — each step depends on artifacts from the prior step.

### Step 1 — [USER] Full retrain with all flags
- `TB_USE_CUSUM=1 TB_USE_FFD_FEATURES=1`
- Populates `timeseries_models.scorecard` with 15-metric grades across all current setups.
- Produces the first deflated-Sharpe-validated, uniqueness-weighted, CUSUM+FFD-featured model set.

### Step 1.5 — Setup Coverage Audit (run immediately after retrain)
Run `PYTHONPATH=backend python backend/scripts/audit_setup_coverage.py`.

Writes `/tmp/setup_coverage_audit.md` summarising, per taxonomy code:
- # of tagged trades across `trades` / `bot_trades` / `trade_snapshots` / `live_alerts`
- Win rate + avg R-multiple
- Verdict: `trainable` / `thin` / `negative_edge` / `too_few` / `unknown_outcome`
- Highlighted Phase 2E Tier-1 candidates (visual-pattern setups with enough data).

This is the critical bridge: TRADING_TAXONOMY.md defines ~35 SMB setups but the
XGBoost pipeline only trains 10 long + 10 short generic families. The audit tells
us which of the 35 have the journal coverage to warrant dedicated (setup, bar_size)
XGBoost + CNN model pairs in Step 5/Step 6.

Inputs to Step 2 (scorecard triage): A-grade generic model + strong audit
coverage  →  split into dedicated setup-specific model.

### Step 2 — Scorecard triage
- Sort all models by composite grade (A-F).
- **Delete** setups grading D/F that can't be salvaged (REVERSAL/5min almost certainly in this bucket — see `/app/memory/notes_sweep_observations.md`).
- **Widen PT/SL sweep grid** on daily setups (all converged to pt=1.5/sl=1.5/max_bars=5 — suspicious).
- Free up training budget for new setups in Step 5.

### Step 3 — Phase 2C: XGBoost Tabular Meta-Labeler ✅ COMPLETED 2026-04-21
**Consolidated into Phase 8 Ensemble** (see "Phase 8 Ensemble — REDESIGNED as Meta-Labeler" above).
Each `ensemble_<setup>` now IS the Phase 2C tabular bet-sizer: P(win | setup_direction, meta_features).

### Step 3.5 — Wire bet-sizer into `trading_bot_service.py` (NEXT)
- `confidence_gate.py` → add `_get_meta_label_signal(setup_type, features)` reading `ensemble_<setup>`
- Expose `meta_label_p_win` in confidence gate result
- `opportunity_evaluator.calculate_position_size()` → new `meta_multiplier` (capped [0.3, 1.5]) alongside volatility + regime multipliers
- Skip trade if `P(win) < 0.50` (meta-labeler says "no edge")
- Log `meta_label_p_win` + `meta_multiplier` in `trade.entry_context` for backtest uplift tracking
- Fallback: absent `ensemble_<setup>` → unchanged sizing (safe)

### Step 4 — Phase 6: Distributed PC Worker infrastructure
- Training coordinator on Spark offloads CNN/DL jobs to Windows PC over LAN.
- REST endpoint contract + job queue + heartbeat + result sync.
- Enables Step 5 (CNN visual meta-labeler would otherwise bottleneck Spark's GB10).

### Step 5 — Phase 2E: Setup-Specific Visual CNN Meta-Labeler ⭐ (high conviction)
Scalp setups (especially SMB-style) are visually defined. Tabular features flatten the chart into 46 numbers; a CNN trained on the actual chart image sees the shape.

**Architecture:** Hybrid multimodal — chart-image CNN + tabular MLP → concat → classifier.

**Pipeline:**
1. **Chart rendering** — OHLCV window → 96×96 or 128×128 PNG with candlesticks, volume bars, and setup-relevant overlays (9EMA/21EMA/VWAP). No axis labels; pure visual signal.
2. **Shared backbone** — train one CNN (EfficientNet-Small or similar) on ALL setups' charts with triple-barrier labels. Self-supervised contrastive pre-training optional.
3. **Per-setup fine-tune heads** — each setup gets a lightweight fine-tuning head on ~5-10k labeled examples.
4. **Tabular fusion** — concat MLP features (46 base + setup + regime + VIX + sub-model probs from cnn_lstm/TFT) with backbone visual features before the classifier head.
5. **Inference** — López de Prado meta-labeling, visual edition: XGBoost says "rubberband scalp candidate" → multimodal CNN sees the chart + context → returns `P(win)`. Combined into bet size.
6. **Explainability** — Grad-CAM activation overlay surfaced to NIA UI so user can verify the CNN is learning real patterns (exhaustion wick, volume climax) vs spurious noise.

**Distribution (requires Step 4):** Spark GB10 trains the shared backbone once a week; Windows PC fine-tunes per-setup heads overnight.

### Step 5.5 — DEPRECATE legacy `cnn_<setup>_<bs>` (34 models) — post-Phase 2E
The current 34 per-setup CNN models in `cnn_models` collection are a **strict subset** of what Phase 2E does:
- Image-only input (no tabular fusion)
- Isolated per-setup training (~2K samples each, no shared backbone transfer learning)
- 17-class pattern head is tautologically 100% (every sample has same setup_type); only the win-AUC head carries signal

**Cutover plan:**
1. Phase 2E models go live + validated on scorecard (≥2 weeks shadow mode)
2. Switch `confidence_gate.py` to read `phase2e_<setup>` instead of `cnn_<setup>`
3. **Remove Phase 9 from the training pipeline** (shaves ~1h 51min off every full retrain — from ~7h to ~5h)
4. Archive `cnn_models` collection (30-day backup), then drop
5. Remove `chart_pattern_cnn.py` + per-setup loop in `cnn_training_pipeline.py`
6. Scorecard: replace 34 `cnn_<setup>` rows with ~10 `phase2e_<setup>` rows

**Keep** `cnn_lstm_chart` (DL model) — different modality (1D CNN+LSTM on OHLCV sequences, not images). Its output feeds into Phase 2E's tabular arm as a stacking feature.

### Step 6 — Add SMB-specific setups (tiered)
Only after visual CNN infrastructure exists, and only for setups the CNN/scorecard analysis justifies.

**Tier 1 — Scalp/Intraday (5-min and 1-min):**
- `RUBBERBAND_SCALP` (long + short) — 2+ ATR stretch from 9EMA/VWAP → reversion scalp
- `EMA9_PULLBACK` (long + short) — trending stock pulls to 9EMA on lower volume → continuation
- `FIRST_RED_CANDLE` / `FIRST_GREEN_CANDLE` — first reversal candle after parabolic move

**Tier 2 — Day-structure:**
- `OPENING_DRIVE_REVERSAL` (5 min) — exhausted opening drive fade
- `HALFBACK_REVERSION` — 50% morning-range retrace
- `INSIDE_DAY_BREAKOUT` (1 day)

**Tier 3 — Cross-instrument (needs SPY sync in training data):**
- `RS_VS_SPY_LONG` / `RW_VS_SPY_SHORT` — relative strength divergence vs SPY

Each new setup needs: detector in `setup_pattern_detector.py`, feature extractor in `setup_features.py`/`short_setup_features.py`, PT/SL sweep entry, and (if visual) chart-render config.

## P2 / Backlog
- Motor async MongoDB driver migration (replace sync PyMongo in hot paths)
- Per-signal weight optimizer for gate auto-tuning
- Earnings calendar + news feed in Chat
- Sparkline (12-wk promotion rate) on ValidationSummaryCard
- `server.py` breakup → `routers/` + `models/` + `tests/`

## Key API surface
- `GET /api/portfolio` — IB pushed positions + manual fallback; quote_ready guard
- `POST /api/portfolio/flatten-paper?confirm=FLATTEN` — flatten paper account, 120s cooldown
- `GET /api/assistant/coach/morning-briefing` — coach prompt only (not position source)
- `GET /api/ai-modules/validation/summary` — promotion-rate dashboard
- `POST /api/ib/push-data` — receive pusher snapshot
- `GET /api/ib/orders/pending` — pusher polls this
- `POST /api/ib/orders/claim/{id}`, `POST /api/ib/orders/result` — claim/complete hooks pusher should use but may not

## Key files
- `backend/routers/portfolio.py` — portfolio endpoint + new flatten-paper
- `backend/routers/ib.py` — push-data + order queue glue
- `backend/services/order_queue_service.py` — Mongo-backed queue with auto-expire
- `frontend/src/components/MorningBriefingModal.jsx` — briefing UI + Flatten button
- `backend/services/ai_modules/post_training_validator.py` — 9 fail-closed gates
- `backend/scripts/revalidate_all.py` — Phase 13 revalidation script

## Hardware runtime notes
- Can't test this codebase in the Emergent container (no IB, no pusher, no GPU). All verification is curl/python on the user's Spark. Testing agents unavailable for integration flows.
- Code changes reach Spark via "Save to Github" → `git pull` on both Windows and Spark.
- Backend restart: `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` (Spark uses `.venv`, not supervisor)
