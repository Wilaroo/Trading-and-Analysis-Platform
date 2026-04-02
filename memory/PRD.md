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
- `/app/backend/services/focus_mode_manager.py` — Focus mode state management
- `/app/backend/scripts/gpu_setup_check.py` — GPU diagnostic + install instructions
- `/app/documents/scripts/ib_data_pusher.py` — IB Data Pusher (focus mode aware)
- `/app/frontend/src/utils/requestThrottler.js` — Browser connection management (max 2 concurrent GETs)
- `/app/frontend/src/utils/safePolling.js` — Training-aware polling with throttler integration
- `/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx` — Training start with queue drain

## Key API Endpoints
- `POST /api/ai-training/start` — Start training pipeline
- `GET /api/ai-training/status` — Training status
- `GET /api/ai-training/regime-live` — Live regime data
- `GET /api/focus-mode/status` — Lightweight focus mode check (for IB Pusher)
- `GET /api/ai-modules/report-card` — Personal trading report card
- `GET /api/strategy-promotion/phases` — Strategy lifecycle phases
- `GET /api/strategy-promotion/candidates` — Promotion candidates
