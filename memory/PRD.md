# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform with 5-Phase Auto-Validation Pipeline, Data Inventory System, CNN chart detection, and maximum Interactive Brokers (IB) historical data collection.

## Architecture
- **Frontend**: React (CRA)
- **Backend**: FastAPI + PyMongo (sync driver)
- **Database**: MongoDB Atlas
- **External**: Interactive Brokers Gateway, Ollama (local AI), Alpaca (market data)
- **Deployment**: User runs locally with IB Gateway connection

## Critical Technical Note
The backend uses synchronous PyMongo inside async FastAPI. All DB calls in `async def` functions MUST be wrapped in `asyncio.to_thread()` to prevent event loop blocking. This is the single most important architectural constraint.

---

## Completed Work

### Session 1-N (Previous)
- Full trading platform with 16+ WebSocket streams
- Multi-agent AI system (Router, Trade Executor, Coach, Analyst)
- Market Regime Engine, Confidence Gate, TQS scoring
- Strategy Promotion lifecycle (SIMULATION → PAPER → LIVE)
- Learning architecture (Fast/Medium/Slow learning)
- RAG Knowledge Base, Shadow Tracker, Debate Agents
- Smart Stops, Circuit Breakers, Position Sizing
- IB Historical Data Collector, Live Scanner
- CNN Chart Detection module
- AI Training Pipeline (5-phase)

### Session N+1 (Skip/Resume Removal)
- Removed all skip/resume logic from training_pipeline.py
- Fixed 4 syntax/indentation errors

### Session N+2 (Event Loop Blocking Fix) — April 2026
- Fixed PyMongo `bool()` crash: `if self._db:` → `if self._db is not None:` (4 files)
- Wrapped WebSocket stream DB calls in `asyncio.to_thread()` (server.py: stream_training_status, stream_focus_mode, stream_sentcom_data, stream_data_collection)
- Wrapped heavy `report-card` endpoint (40+ DB calls) in `asyncio.to_thread()`
- Converted agent_data_service methods from fake-async to sync, wrapped at router level
- Converted strategy_promotion_service methods from fake-async to sync, wrapped at router level
- Wrapped learning_connectors `get_applied_thresholds` DB query in `asyncio.to_thread()`
- Wrapped ai_training.py endpoints (/regime-live, /model-inventory, /status) with `asyncio.to_thread()`
- Cleared stale training state and added auto-reset on startup

### Session N+3 (Browser Connection Starvation Fix) — April 2026
- **P0 Fix: Browser connection starvation**: Reduced `requestThrottler.js` maxConcurrent from 4→2, freeing 2 browser connections for POST/PUT/DELETE. Added `pause()`/`resume()`/`drainQueue()` methods. Training start now pauses all background GET polls before sending POST.
- **Fix: `_realtime_tech` AttributeError**: Changed `self._realtime_tech` → `self.technical_service` (lazy property) in `trading_bot_service.py` line 1427.
- **Fix: `dynamic_risk_service` missing module**: Corrected import from `dynamic_risk_service` → `dynamic_risk_engine` and `get_dynamic_risk_service` → `get_dynamic_risk_engine` in `server.py` stream_risk_status.
- **Fix: Shadow signal backlog**: Added bulk expiry of signals >5 days old in one MongoDB update_many, plus batch limit of 50 signals per scheduler run to prevent event loop starvation.

### Session N+4 (WebSocket Training Commands + Stale Status Fix) — April 2026
- **Architectural Shift**: Migrated training start/stop commands from HTTP POSTs to WebSocket messages (`start_pipeline`, `stop_pipeline`), completely bypassing browser's 6-connection HTTP limit
- **P0 Fix: Stale training status on boot**: Added startup cleanup routine in `server.py` `_deferred_heavy_init()` that resets `training_pipeline_status` MongoDB document to "idle" if phase is stale ("starting", "running", "preparing", "training") but no actual subprocess is running. This prevents the UI from falsely showing "Starting..." state on app boot after a backend restart or crash.

### Session N+5 — Jan 2026
- **Continuation**: Cloned repo from GitHub, implemented the stale training status fix that was identified but not applied in previous session
- **Fix location**: `/app/backend/server.py` lines 3420-3435 in `_deferred_heavy_init()` function

### Session N+6 (Current Session) — Feb 2026
- **P0 Fix: UI Training Status Desync** — Three-pronged fix:
  1. **Frontend optimistic update**: `TrainingPipelinePanel.jsx` now immediately sets `task_status` to `'running'`/`'idle'` on successful start/stop WS responses, so the button flips instantly without waiting for the status stream.
  2. **Reduced stream delay**: `stream_training_status()` initial sleep reduced from 25s → 5s so the real MongoDB status arrives quickly.
  3. **Immediate broadcast on start/stop**: After `start_pipeline` or `stop_pipeline` succeeds, backend immediately fetches fresh status from MongoDB and broadcasts `training_status` to all connected clients, bypassing the poll interval.

### Session N+7 — Feb 2026
- **P1: LightGBM GPU Auto-Detection Overhaul**:
  - Replaced naive `Booster()` GPU test with actual `lgb.train()` micro-benchmark (catches OpenCL linking issues)
  - Tests both `device` and `device_type` param names for cross-version compatibility
  - GPU-optimized params auto-enabled: `max_bin=63`, `gpu_use_dp=False` (single precision)
  - Created `gpu_setup_check.py` diagnostic script — detects GPU, CUDA, OpenCL, conda, gives tailored install instructions
- **P2: IB Pusher Timeout Fix**:
  - Root cause: Pusher was hitting `/api/focus-mode/status` which didn't exist — focus mode check always failed silently, so pusher NEVER paused during training
  - Added lightweight `/api/focus-mode/status` endpoint (returns in <15ms even under load)
  - Updated `ib_data_pusher.py`: completely stops cloud pushes during training mode (was still pushing every 30s, causing timeout spam)
  - Both `run()` and `run_auto_mode()` modes now fully pause during training
- **Performance**: Vectorized multiprocessing training (12-core, 50 symbols/chunk) — USER VERIFICATION PENDING

### Session N+8 — Feb 2026
- **P0 Fix: `_extract_symbol_worker` NameError crashing training pipeline**:
  - Root cause: `train_vectorized()` used `ProcessPoolExecutor` to call `_extract_symbol_worker`, but the function was never defined
  - Fix: Defined `_extract_symbol_worker()` at module scope in `timeseries_gbm.py` (required for pickle serialization across processes)
  - The worker creates a `TimeSeriesFeatureEngineer`, calls `extract_features_bulk()` for vectorized extraction, computes binary targets (price up/down), and returns `(feature_matrix, targets)`
  - Verified: pickle round-trip OK, synthetic data test passes (correct shapes, no NaN/Inf), full `train_vectorized()` end-to-end completes successfully

- **P1: Stream-Load-Extract Architecture — remove max_bars cap**:
  - Problem: `load_symbols_parallel` loaded ALL symbols' bars into RAM at once (~7.5GB+ for 2500 symbols), forcing `max_bars=10,000` cap per symbol (only ~25 trading days of 1-min data)
  - Solution: New `stream_load_and_extract()` function loads symbols in batches of 50 (`STREAM_BATCH_SIZE`), extracts features via multiprocessing, discards raw bars immediately, accumulates only compact float32 numpy arrays
  - Applied streaming pattern to ALL 8 training phases (generic, setup long/short, volatility, exit, sector, risk, regime, ensemble)
  - `max_bars` set to 0 (uncapped) for ALL 7 timeframes — models now train on full history
  - Peak RAM: ~750MB (one batch of raw bars) + accumulated features (float32), vs. old ~7.5GB (all raw bar dicts)
  - Verified: 120-symbol synthetic test across 3 batches produces identical results to single-batch approach

- **P1: 6-Point Pipeline Optimization Overhaul**:
  1. **Symbol Cache (#3)**: `get_cached_symbols()` caches `get_available_symbols` results per bar_size. Eliminates redundant $group aggregations over 177M rows (was running 10+ times per bar_size).
  2. **Vectorized remaining loops (#6)**: Replaced 2 Python for-loops in `extract_features_bulk` (volatility_ratio, higher_highs/lower_lows) with numpy vectorized operations using `sliding_window_view`.
  3. **Multiprocessing Phases 2/2.5/4/6 (#1)**: Created top-level worker functions (`_extract_setup_long_worker`, `_extract_setup_short_worker`, `_extract_exit_worker`, `_extract_risk_worker`) that distribute per-symbol extraction across 12 CPU cores via `ProcessPoolExecutor`.
  4. **Group-by-bar-size restructure (#2)**: Phases 2/2.5 now group all setup types by bar_size and load bars ONCE per bar_size (was loading same bars 10+ times for each setup type). Base features computed once per symbol, reused across setup types.
  5. **Numpy accumulation (#4)**: All phases now accumulate features as compact float32 numpy arrays instead of Python lists of lists (~8x memory savings during accumulation).
  6. **CNN adaptive step (#9)**: Added adaptive step size for image generation (targets ~500 windows/symbol max), `max_bars_per_symbol` and `max_samples` parameters to prevent OOM on high-bar-count symbols.

### Session N+9 — Feb 2026
- **P0 Fix: Phantom `QUICK` symbol hitting IB Gateway**:
  - Root cause: `user_viewed_tracker.track_symbol_view()` had no validation — any string could be persisted as a "viewed symbol" and flow into the wave scanner's Tier 1, causing IB to be queried for invalid tickers every scan cycle
  - Fix 1: Added `_is_valid_trackable_symbol()` to `user_viewed_tracker.py` — validates against the known index universe first (allows real tickers like "FAST"), then blocks common English words via a 150+ word blocklist
  - Fix 2: Added safety filter in `wave_scanner.py` when loading viewed symbols for Tier 1 — only includes symbols that pass `is_valid_symbol()` from the index universe
  - Fix 3: Hardened `smart_context_engine._extract_symbols()` — `$SYMBOL` extractions now validate against `KNOWN_SYMBOLS` + `is_valid_symbol()` before tracking (previously, any `$WORD` was tracked without validation)
  - User action needed: Run `db.user_viewed_symbols.deleteMany({symbol: "QUICK"})` in MongoDB shell to clean up any existing entries

- **P0 Fix: Frontend making ~20+ API calls per polling cycle during ML Training**:
  - Fix 1: `NIA/index.jsx` — `fetchAllData()` (9 parallel API calls) now skipped entirely when `isTrainingActive`, both on effect re-run and in the polling interval
  - Fix 2: `SystemStatusContext.jsx` — `checkAllServices()` (4 HTTP health checks) now skipped during training via `isTrainingActive()` import from safePolling
  - Fix 3: `App.js` — IB connection polling (1 call/60s) now skipped during training
  - Fix 4: `NIA/TrainingPipelinePanel.jsx` — HTTP fallback interval increased from 30s → 120s during training (WebSocket is the primary update mechanism)
  - Total savings: ~14+ API calls eliminated per polling cycle during training

---

## P0 Issues
- [FIXED] Event loop blocking on startup
- [FIXED] Status dots stuck red
- [FIXED] Training badge persisting forever
- [FIXED] Thread pool exhaustion during training
- [FIXED] `stream_training_status` crash
- [FIXED] DB backlogs cleared
- [FIXED] Thread pool exhaustion via aggressive frontend polling
- [FIXED] Startup thundering herd (IB Pusher timeout)
- [FIXED] False-positive "API" red dot in TickerTape
- [FIXED] Training subprocess isolation
- [FIXED] Event loop starvation during training
- [FIXED] IB Pusher GET timeout
- [FIXED] **Browser connection starvation blocking training POST** (April 2026)
- [FIXED] **`_realtime_tech` AttributeError crashing trade evaluation** (April 2026)
- [FIXED] **`dynamic_risk_service` module not found spamming logs** (April 2026)
- [FIXED] **Shadow signal backlog (4560+ pending)** (April 2026)
- [FIXED] **Stale training status on boot** (Jan 2026)
- [FIXED] **UI training status desync** (Feb 2026)
- [FIXED] **IB Pusher timeout spam during training** (Feb 2026)
- [FIXED] **Stale order infinite retry loop** (Feb 2026)
- [FIXED] **asyncio.coroutine crash** (Feb 2026)
- [FIXED] **Alert reasoning loopback timeout** (Feb 2026)
- [FIXED] **Learning context .upper() on None** (Feb 2026)
- [FIXED] **Market intel stream error** (Feb 2026)
- [FIXED] **_get_base_system_prompt missing** (Feb 2026)
- [FIXED] **`_extract_symbol_worker` NameError crashing training pipeline** (Feb 2026): Missing top-level worker function for multiprocessing

- [FIXED] **Phantom QUICK symbol hitting IB Gateway** (Feb 2026): Unvalidated symbol tracking + wave scanner safety filter
- [FIXED] **Frontend 20+ API calls during training** (Feb 2026): NIA panel, SystemStatus, App.js, TrainingPipelinePanel all gated behind training mode checks

## Recent Enhancements (April 2026)
- **Pipeline Progress Panel**: `PipelineProgressPanel.jsx` — real-time per-phase progress bars from WS training_status stream (zero extra polling).
- **Focus mode auto-pause**: `safePolling` globally pauses non-essential frontend polls during training. Backend streams + scheduler tasks also pause. All resume automatically when training completes via WS focus_mode broadcast.

## Prioritized Backlog

### P1
- Auto-Optimize AI Settings: Sweep confidence thresholds and lookback windows per strategy
- LightGBM GPU: User needs to install GPU-enabled LightGBM locally (run `python gpu_setup_check.py` for instructions). Code auto-detects and enables GPU params.

### P2
- Desktop notification system (alerts/sounds on AI training phase completion)
- Gap Fill training phase wiring
- Smart Templates from AI performance data
- Model Health card (staleness tracking + "Retrain Stale" action)

### P3
- Post-Development Local DB Migration to NVMe
- Systematic migration to Motor (async PyMongo driver) for long-term stability

---

## Key Files
- `/app/backend/server.py` — Main server, WebSocket streams
- `/app/backend/routers/ai_training.py` — Training pipeline endpoints
- `/app/backend/routers/focus_mode_router.py` — Focus mode endpoints (incl. /status for IB Pusher)
- `/app/backend/services/ai_modules/training_pipeline.py` — Training pipeline logic
- `/app/backend/services/ai_modules/timeseries_gbm.py` — LightGBM model (GPU auto-detect)
- `/app/backend/services/ai_modules/timeseries_features.py` — Vectorized feature extraction
- `/app/backend/services/user_viewed_tracker.py` — Symbol tracking with universe validation
- `/app/backend/services/wave_scanner.py` — Scanner tier system with safety filtering
- `/app/backend/services/smart_context_engine.py` — AI chat symbol extraction (validated)
- `/app/backend/services/focus_mode_manager.py` — Focus mode state management
- `/app/backend/scripts/gpu_setup_check.py` — GPU diagnostic + install instructions
- `/app/documents/scripts/ib_data_pusher.py` — IB Data Pusher (focus mode aware)
- `/app/frontend/src/utils/requestThrottler.js` — Browser connection management (max 2 concurrent GETs)
- `/app/frontend/src/utils/safePolling.js` — Training-aware polling with throttler integration
- `/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx` — Training start with queue drain
- `/app/frontend/src/components/NIA/index.jsx` — NIA panel (training-gated polling)
- `/app/frontend/src/contexts/SystemStatusContext.jsx` — System health (training-gated)

## Key API Endpoints
- `POST /api/ai-training/start` — Start training pipeline
- `GET /api/ai-training/status` — Training status
- `GET /api/ai-training/regime-live` — Live regime data
- `GET /api/focus-mode/status` — Lightweight focus mode check (for IB Pusher)
- `GET /api/ai-modules/report-card` — Personal trading report card
- `GET /api/strategy-promotion/phases` — Strategy lifecycle phases
- `GET /api/strategy-promotion/candidates` — Promotion candidates
