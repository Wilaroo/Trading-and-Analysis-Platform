# TradeCommand / SentCom — Product Requirements

## Original problem statement
AI trading platform running across DGX Spark (Linux) + Windows PC (IB Gateway). Goal: stable massive training pipeline, real-time responsive UI, SentCom chat aware of live portfolio status without hanging the backend, and a bot that can go live for automated trading with accurate dashboards.

## Architecture
- **DGX Spark (Linux, 192.168.50.2)**: Backend FastAPI :8001, Chat :8002, MongoDB :27017, Frontend React :3000, Ollama :11434, worker, Blackwell GPU
- **Windows PC (192.168.50.1)**: IB Gateway :4002, IB Data Pusher (client 15), 4 Turbo Collectors (clients 16–19)
- Orders flow: Spark backend `/api/ib/orders/queue` → Mongo `order_queue` → Windows pusher polls `/api/ib/orders/pending` → submits to IB → reports via `/api/ib/orders/result`
- Position/quotes flow: IB Gateway → pusher → `POST /api/ib/push-data` → in-memory `_pushed_ib_data` (+ Mongo snapshot for chat_server)

## Completed in this session (2026-04-21 — continued fork)
### Phase 8 DMatrix Fix & Bet-Sizing Wire-In (2026-04-21)
**Problem 1 (broadcast)**: Phase 8 ensemble failed with `ValueError: could not broadcast input array from shape (2382,) into shape (2431,)` — inline FFD augmentation was dropping 49 lookback rows vs the pre-computed `features_matrix`.
**Fix 1**: Removed inline FFD augmentation; reverted to zero-fill fallback so row counts stay consistent. Pytest suite expanded.

**Problem 2 (DMatrix)**: After broadcast fix, Phase 8 failed with `TypeError: Expecting data to be a DMatrix object, got: numpy.ndarray` — `TimeSeriesGBM._model` is an `xgb.Booster` (not `XGBClassifier`) which requires `DMatrix` input.
**Fix 2**: `training_pipeline.py` Phase 8 sub_model + setup_model predicts now wrap features in `xgb.DMatrix(..., feature_names=sm._feature_names)` before calling `.predict()`. Added `test_phase8_booster_dmatrix.py` (3 regression tests including source-level guard against future regressions).
**Verification (user, 2026-04-21 15:24Z)**: Phase 8 now producing real ensembles — 5/10 done at time of writing: meanrev=65.6%, reversal=66.3%, momentum=58.3%, trend=55.3%. All binary meta-labelers with ~44% WIN rate on 390K samples.

### Phase 8 → Live Bet-Sizing Wire-In (2026-04-21) — COMPLETED & VERIFIED LIVE
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
