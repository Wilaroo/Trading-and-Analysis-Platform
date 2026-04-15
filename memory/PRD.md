# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform optimization. Implement XGBoost GPU swap, resolve Train/Serve data skew by removing Alpaca dependencies, eliminate scanning bottlenecks, refactor the subtractive confidence gate to an additive system, integrate Deep Learning models across the dual-GPU architecture (DGX Spark + Windows PC), and optimize feature extraction for 128GB DGX Spark memory.

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB unified memory): Backend/Frontend + local MongoDB `tradecommand` (178M+ bars). Runs XGBoost + DL models.
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Turbo Collectors + (Future) distributed DL training over LAN.
- **Data**: 100% Interactive Brokers via local MongoDB. No Alpaca/Finnhub/TwelveData in trading paths.

## Completed Phases

### Phase 1: 100% IB Data (DONE)
- Removed Alpaca, Finnhub, TwelveData from all trading/scanning paths

### Phase 2: XGBoost GPU Swap (DONE)
- Replaced LightGBM with XGBoost (`tree_method='hist'`, `device='cuda'`)

### Phase 3: Training Optimizations (DONE)
- Vectorized `extract_features_bulk()`, feature caching, batch sizes 500

### Phase 4: Scanner Upgrade (DONE)
- ADV-tiered scanning, 100 symbols per batch

### Phase 4.5: Confidence Gate Refactor (DONE)
- Additive 0-100 scoring, 12 layers, GO >= 55 / REDUCE >= 30 / SKIP < 30

### Phase 5a: Training Pipeline Bug Fixes (DONE — April 7, 2026)
- 9 critical XGBoost pipeline bugs fixed and verified on Spark hardware

### Phase 5b: Deep Learning Models (DONE — April 7, 2026)
- VAE Regime Detection (Layer 10), TFT Multi-Timeframe (Layer 9), CNN-LSTM (Layer 11)
- Full PyTorch implementations with train/predict/save/load
- Wired into Confidence Gate and training pipeline (Phase 11)

### Phase 5c: FinBERT Sentiment (DONE — April 8, 2026)
- FinnhubNewsCollector + FinBERTSentiment with 6 API endpoints
- Worker `FINBERT_ANALYSIS` job type for background pipeline
- Wired into training pipeline (Phase 12)
- Decoupled from live training loop — Gate Layer 12 ready when activated

### Phase 5d: Training Pipeline Optimization (DONE — April 8, 2026)
- **9x memory reduction**: Replaced `.tolist()` Python list accumulation with numpy chunk pattern across `train_full_universe()`, `TimeSeriesGBM.train()`, and `_train_single_setup_profile()`
- **10-50x setup training speedup**: Replaced per-match `extract_features()` with one `extract_features_bulk()` per symbol + numpy indexing
- **Training mode bridge**: Connected `training_mode_manager` ↔ `focus_mode_manager` so scanner/bot/WS streams genuinely pause during training
- **Pipeline Phase 1 upgraded**: Replaced old `stream_load_and_extract` with optimized `train_full_universe()` — eliminates redundancy with Full Universe button
- **Phase 11 + 12 added**: DL models and FinBERT wired into master training pipeline
- **Results**: Daily model 2 min (cached), 1-hour model 30M samples in 66 min, memory flat ~15-25GB

## Master Training Pipeline (13 Phases)
| Phase | What | Models |
|-------|------|--------|
| 1 | Generic Directional (Full Universe) | 7 |
| 2 | Setup-Specific (Long) | 17 |
| 2.5 | Setup-Specific (Short) | 17 |
| 3 | Volatility Prediction | 7 |
| 4 | Exit Timing | 10 |
| 5 | Sector-Relative | 3 |
| 6 | Risk-of-Ruin | 6 |
| 7 | Regime-Conditional | 28 |
| 8 | Ensemble Meta-Learner | 10 |
| 9 | CNN Chart Patterns | 13 |
| 11 | Deep Learning (VAE/TFT/CNN-LSTM) | 3 |
| 12 | FinBERT Sentiment | 1 |
| 13 | Auto-Validation (5-phase) | 34 |
| **Total** | | **156 work units** |

## Confidence Gate Scoring (12 Layers)
- Layer 1: Regime Check (max +20 / floor -10)
- Layer 2: AI Regime (max +10 / floor -5)
- Layer 3: Model Consensus (max +15 / floor -5)
- Layer 4: Live Model Prediction (max +15 / floor -5)
- Layer 5: Cross-Model Agreement (max +5 / floor -5)
- Layer 6: Quality Score (max +10 / floor -5)
- Layer 7: Learning Loop Feedback (max +8 / floor -5)
- Layer 8: CNN Visual Pattern (max +12 / floor -5)
- Layer 9: TFT Multi-Timeframe (max +12 / floor -5)
- Layer 10: VAE Regime Detection (max +8 / floor -5)
- Layer 11: CNN-LSTM Temporal (max +10 / floor -5)
- Layer 12: FinBERT Sentiment (INACTIVE — max +7 / floor -5) [READY]

## Key API Endpoints
- `/api/ai-modules/timeseries/train-full-universe-all` — Train all 7 directional models
- `/api/ai-modules/timeseries/setups/train-all` — Train all 35 setup profiles
- `/api/ai-modules/dl/train-all` — Train 3 DL models
- `/api/ai-modules/finbert/*` — 6 FinBERT endpoints
- `/api/ai-modules/dl/status` — DL + FinBERT status
- `/api/ai-training/start` — Master pipeline (all 13 phases)
- `/api/ai-training/is-active` — Lightweight training status check (for IB Pusher/Collectors)

### Phase 5e: IB Pusher Training Guard (DONE — April 8, 2026)
- **Bug Fixed:** IB Pusher's `run()` mode was checking `http://127.0.0.1:8001` for training status — but pusher runs on Windows PC, not Spark. Focus mode check silently failed, pusher kept hammering MongoDB during training.
- **New Endpoint:** `GET /api/ai-training/is-active` — lightweight boolean check consolidating `focus_mode_manager` + `training_mode_manager` + subprocess status. 14ms response time.
- **Pusher Fix:** Changed `local_backend_url` to `spark_backend_url` (cloud_url = `http://192.168.50.2:8001`). Added proper exponential backoff: 30s checks normally, 60s checks during training, 5s sleep per tick when paused, clear console logging.
- **Collectors Fixed:** Added same training guard to `ib_historical_collector.py`, `v3`, and `v4` — all back off 60s per cycle when training detected.
- **Auto-Mode Fixed:** `_check_cloud_mode()` now checks the new `/api/ai-training/is-active` endpoint first (most reliable signal).

### Phase 5f: Restart Script OOM Fix (DONE — Feb 2026)
- **Bug Fixed:** `.bat` restart script (`TradeCommand_Spark_AITraining.bat`) Step 2.5 only killed `server.py`, `worker.py`, and frontend — but NOT `training_subprocess` GPU processes. On restart, 13 new training subprocesses stacked on top of existing ones, causing 100% RAM (128GB), 12GB swap, and 91.6°C thermal throttle.
- **Fix:** Added `pkill -9 -f training_subprocess` and `pkill -9 -f training_pipeline` as the FIRST kill commands (before backend/worker), with 2s delay, then verification pass to catch stubborn processes. Increased shutdown wait from 5s to 8s.

### Phase 5g: Memory Management & BSON Fix (CODE COMPLETE — Feb 2026, PENDING USER TEST)
- **P0 OOM/Swap Thrashing Fix:**
  - Added `_phase_memory_cleanup()` using `gc.collect()` + `ctypes.CDLL("libc.so.6").malloc_trim(0)` to force glibc to release freed Python memory back to OS between ALL 12 phase transitions (previously 2 were missing: Phase 3→4 and Phase 5→5.5)
  - Low-memory detection: if <30GB available after cleanup, sleeps 10s and retries
  - Capped `MAX_EXTRACT_WORKERS` to 8, `SETUP_PHASE_MAX_SYMBOLS` to 750
  - Auto-resolve `max_bars` from `BAR_SIZE_CONFIGS` (never truly unlimited)
  - `_system_preflight()` kills orphan processes, sets `vm.swappiness=10`, logs memory state
  - 6 Python memory leaks fixed (missing `del` + `gc.collect()`)
  - Start/Stop routes have OS-level `pgrep`/`pkill` guards
- **P1 XGBoost BSON Size Limit Fix:**
  - `_save_model()` now uses `zlib.compress(model_bytes, level=6)` + Base64 encoding
  - Models stored as `xgboost_json_zlib` format (35MB raw → ~3MB compressed)
  - `_load_model()` detects format and `zlib.decompress()` before loading
  - Backward-compatible with legacy `xgboost_json` and LightGBM pickle formats

### Phase 5h: Systemic Pipeline Memory Fixes (CODE COMPLETE — Feb 2026, PENDING USER TEST)
- **8 systemic issues identified and fixed across the entire 13-phase pipeline:**
  1. Added 2 missing `_phase_memory_cleanup()` calls (Phase 3→4, Phase 5→5.5) — ~10-20GB leaked per run
  2. Changed all 5 `pool.shutdown(wait=False)` to `wait=True` — prevents overlapping forked worker processes
  3. Refactored Phases 3, 5, 5.5 from per-row Python list accumulation to pre-allocated buffer chunks — eliminates millions of tiny numpy arrays and ~2-4GB Python object overhead
  4. Changed all `dtype=float` (float64, 8 bytes) to `dtype=np.float32` (4 bytes) in Phases 3, 5, 5.5, 7, 8 — halves memory for price arrays
  5. Added missing `del X, y; gc.collect()` after training in Phases 3, 5, 7
  6. Removed `.tolist()` conversion in Phase 3 (unnecessary numpy→list→numpy round-trip)
  7. Refactored Phase 7 (Regime) from per-row `.copy()` to per-symbol chunk accumulation with regime splitting
  8. All 12 phase transitions now have cleanup calls (verified: 14 phases - first - last = 12 cleanups)
- **Estimated memory savings:** 15-25GB cumulative across full pipeline run
### Phase 5i: Pipeline Caching & Resume (CODE COMPLETE — Feb 2026, PENDING USER TEST)
- **4 caching layers implemented to speed up future training runs:**
  1. **NVMe Bar Cache** — Bars loaded from MongoDB once per symbol+bar_size, cached as pickle on NVMe disk. Later phases read from disk (NVMe ~5-7 GB/s) instead of re-querying MongoDB. Saves minutes of I/O per phase.
  2. **NVMe Feature Cache** — `extract_features_bulk` results cached as `.npy` on disk. Phases 3, 5, 5.5, 7, 8 share pre-computed feature matrices. Saves hours of CPU recomputation.
  3. **Pipeline Resume** — Before training each model, checks MongoDB for existing model trained within N hours (default 24h). Skips training if model is fresh. If pipeline crashes at Phase 7, restart only trains Phases 7-12 (Phases 1-6 are auto-skipped). API supports `force_retrain=true` to override.
  4. **Shared Regime/SPY Data** — RegimeFeatureProvider created once at pipeline start, reused by Phase 3 (Volatility) and Phase 7 (Regime). Eliminates duplicate SPY data loading.
- **Resume checks added to all 11 training phases** (Phase 1, 2, 2.5, 3, 4, 5, 5.5, 6, 7, 8, 11)
- **API Parameters:** `POST /api/ai-training/start` now accepts:
  - `force_retrain: bool` (default: false) — retrain all models ignoring cache
  - `resume_max_age_hours: float` (default: 24.0) — skip models trained within N hours
- **Cache lifecycle:** NVMe disk cache (`/tmp/training_cache/`) cleared at pipeline start, preserved at end for debugging
### Phase 5j: OOM Fix — Per-Bar-Size Symbol Caps & Memory Guard (CODE COMPLETE — Feb 2026)
- **Root Cause:** OS OOM killer terminated pipeline (173GB virtual, 90GB RSS on 128GB system). 2500 symbols × 50K 5-min bars = 125M rows accumulated in `all_X`. `np.vstack` doubled peak to ~100GB → OOM.
- **Fix 1 — Frequency-scaled symbol caps in BAR_SIZE_CONFIGS:**
  - 1 min: 200 symbols (×50K bars = 10M rows)
  - 5 mins: 500 symbols (×50K bars = 25M rows)
  - 15 mins: 750 symbols (×20K bars = 15M rows)
  - 30 mins: 1000 symbols (×13K bars = 13M rows)
  - 1 hour: 1500 symbols (×6K bars = 9M rows)
  - 1 day: 2500 symbols (×500 bars = 1.25M rows) — unchanged
  - 1 week: 2500 symbols (×200 bars = 500K rows) — unchanged
- **Fix 2 — Pre-vstack memory guard:** `_check_vstack_memory()` reads `/proc/meminfo`, estimates peak from `sum(x.nbytes)×2`, and auto-truncates oldest symbol chunks if >80% of available RAM. Applied to all 4 inline vstack points (Phases 3, 5, 5.5, 7).
- **Fix 3 — Test mode:** `--test-mode` flag caps symbols to 50, bars to 5000. Runs entire pipeline in minutes for systematic per-phase testing.
- **API:** `POST /api/ai-training/start` now supports `test_mode: true`
- **CLI:** `python -m services.ai_modules.training_subprocess --phases volatility --test-mode`

### Phase 5k: Vectorized Feature Extraction (CODE COMPLETE — Feb 2026, PENDING USER TEST)
- **Root Cause:** Per-bar Python `for i in range(50, len(bars) - fh)` loops in Phases 2, 2.5, 3, 4, 5, 6, and 7 created ~125M iterations across all symbols (500 symbols × 50K bars × 5 freq). Each iteration called Python functions, created numpy slices, and did dict operations. This was the #1 CPU bottleneck, accounting for 65% of pipeline runtime (~17 min per 50-symbol batch).
- **Fix 1 — Vectorized vol targets:** `compute_vol_targets_batch()` in `volatility_model.py` — uses `numpy.lib.stride_tricks.sliding_window_view` to compute trailing/forward realized vols for ALL bars simultaneously. 91x speedup verified.
- **Fix 2 — Vectorized vol features:** `compute_vol_features_batch()` — computes all 6 vol-specific features (vol_rank_20, vol_rank_50, vol_acceleration, range_expansion, gap_frequency, volume_vol_corr) for all bars at once using rolling windows and vectorized correlation. 159x speedup verified.
- **Fix 3 — Vectorized sector-relative targets & features:** `compute_sector_relative_targets_batch()` and `compute_sector_relative_features_batch()` in `sector_relative_model.py` — computes all 10 sector features vectorized.
- **Fix 4 — Date-based regime cache:** Phase 3 now extracts unique dates from bars and calls `get_regime_features_for_date()` once per unique date (~250 calls per year vs ~50K calls per symbol).
- **Fix 5 — Phase 7 (Regime-Conditional) vectorized:** Targets computed as vectorized numpy operations, regime classification cached by unique date.
- **Fix 6 — `extract_features_bulk()` returns float32:** Halves memory for feature matrices (XGBoost uses float32 internally).
- **Fix 7 — Workers pre-compute sliding windows:** `_extract_setup_long_worker`, `_extract_setup_short_worker`, `_extract_exit_worker`, `_extract_risk_worker` now pre-compute ALL reversed OHLCV windows via `sliding_window_view` once (zero-copy views). Eliminates ~250K per-bar array allocations per symbol.
- **Fix 8 — Workers vectorize targets:** All 4 workers compute targets (UP/DOWN/FLAT, MFE bars, stop-hit) as vectorized numpy operations instead of per-bar function calls. Exit targets use vectorized argmax/argmin on forward windows. Risk targets use pre-computed rolling ATR and forward window scans.
- **Fix 9 — Workers fix broken imports:** `_extract_exit_worker` imported from non-existent `exit_features` (fixed to `exit_timing_model`). `_extract_risk_worker` imported from non-existent `risk_features` (fixed to `risk_of_ruin_model`).
- **Fix 10 — MongoDB `load_symbols_parallel` optimization:** Checks NVMe disk cache synchronously for ALL symbols upfront (O(1) per file), only sends cache misses to MongoDB. After first pipeline phase, subsequent phases get 100% cache hits with zero MongoDB queries.
- **Known issue:** ~~Phase 5.5 (Gap Fill) had a pre-existing `compute_gap_features` signature mismatch — pipeline passed `avg_volume_20`/`atr_10` kwargs but function expected `daily_closes`/`daily_highs`. Phase 5.5 had never successfully run.~~ **FIXED** — now passes correct MRF window arrays + pre-computed sliding windows + vectorized gap detection.
- **Test suite:** `/app/backend/tests/test_vectorization.py` — 9 tests verify correctness (bit-for-bit target match, feature tolerance, worker output validation) and performance (91-162x speedup on 5K bars, ~25000x on 50K bars).
- **Expected pipeline impact:** All inner per-bar loops across Phases 2-7 now use pre-computed windows and vectorized targets. Total pipeline runtime should drop from hours to well under an hour.

## Upcoming Tasks
- Phase 5g: RL Position Sizer (needs trade outcome data)
- Phase 6: Distributed PC Worker (LAN training on RTX 5060 Ti)
- Phase 7: Infrastructure Polish (systemd, notifications, symbol rotation)
- FinBERT UI panel in NIA
- Activate FinBERT as Gate Layer 12
- Per-signal weight optimizer
- Deprecate/remove `ollama_proxy_manager.py` (native Ollama on Spark replaces it)

## Key Files
- `/app/backend/services/ai_modules/training_pipeline.py` — Master 13-phase pipeline
- `/app/backend/services/ai_modules/timeseries_service.py` — Full Universe training
- `/app/backend/services/ai_modules/timeseries_gbm.py` — XGBoost model
- `/app/backend/services/ai_modules/timeseries_features.py` — Feature engineering (float32 output)
- `/app/backend/services/ai_modules/volatility_model.py` — Volatility model + vectorized batch functions
- `/app/backend/services/ai_modules/sector_relative_model.py` — Sector-relative model + vectorized batch functions
- `/app/backend/services/ai_modules/regime_features.py` — Regime feature provider
- `/app/backend/services/ai_modules/confidence_gate.py` — 12-layer scoring
- `/app/backend/services/ai_modules/vae_regime.py` — VAE Regime Detection
- `/app/backend/services/ai_modules/temporal_fusion_transformer.py` — TFT
- `/app/backend/services/ai_modules/cnn_lstm_model.py` — CNN-LSTM
- `/app/backend/services/ai_modules/finbert_sentiment.py` — FinBERT Sentiment
- `/app/backend/routers/ai_modules.py` — All AI API endpoints
- `/app/backend/worker.py` — Background job processor
- `/app/backend/tests/test_vectorization.py` — Vectorization correctness & perf tests
- `/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx` — Pipeline UI

## DB Collections
- `ib_historical_data` — 178M+ bars
- `timeseries_models` — XGBoost models
- `feature_cache` — Cached training features
- `dl_models` — PyTorch DL models
- `news_articles` — Finnhub news articles
- `news_sentiment` — FinBERT scored articles
- `confidence_gate_log` — AI decisions
- `job_queue` — Background jobs
