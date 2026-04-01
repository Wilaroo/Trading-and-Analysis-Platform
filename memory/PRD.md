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

---

## P0 Issues
- [FIXED ✅] **Event loop blocking on startup**: `market_regime_engine.py` had 5 sync MongoDB calls. Wrapped in `asyncio.to_thread()`.
- [FIXED ✅] **Status dots stuck red**: `SystemStatusContext` health checks bypassed `requestThrottler` via direct `fetch()`.
- [FIXED ✅] **Training badge persisting forever**: `FocusModeContext` syncs with backend on mount.
- [FIXED ✅] **Thread pool exhaustion during training**: Dedicated `TRAINING_POOL` in `training_pipeline.py`.
- [FIXED ✅] **`stream_training_status` crash**: Variable scope bug fixed.
- [FIXED ✅] **DB backlogs cleared**: Training pipeline + focus mode reset.
- [FIXED ✅] **Thread pool exhaustion via aggressive frontend polling**: Reduced HTTP polling from ~40 req/30s to ~8 req/30s. Migrated IB status, bot status, alerts, positions, and context to use WebSocket as primary data source with HTTP as slow backup. Key changes in SentCom.jsx (10 hooks), useCommandCenterData.js, CommandCenterPage.js, JobManager.jsx, StartupStatusDashboard.jsx.
- [FIXED ✅] **Startup thundering herd (IB Pusher timeout at ~10s)**: Frontend was firing 20+ HTTP requests simultaneously at t=0 on page load. Staggered initial loads across 12 seconds (2-3 req/s max). Backend: wrapped sync `bulk_write` in `short_interest_service.py` with `asyncio.to_thread`. **Critical fix**: Converted `push-data`, `pushed-data`, `health`, and `startup-check` endpoints from `async def` to `def` — they now run in the thread pool, completely immune to event loop blocking from background tasks. Files changed: SentCom.jsx (11 hooks staggered), useCommandCenterData.js (4-phase delays), short_interest_service.py, ib.py, system_router.py.
- [FIXED ✅] **False-positive "API" red dot in TickerTape** (April 2026): Self-healing logic in SystemStatusContext. Threshold 3→5, interval 60s→90s.
- [FIXED ✅] **Training subprocess isolation** (April 2026): Training pipeline now runs in a completely separate subprocess (own GIL, own memory). The MONGO_URL was being corrupted when passed as CLI arg — now passed via environment variable inheritance. Event loop is 100% free during training.
- [FIXED ✅] **Event loop starvation during training** (April 2026): 13 WS streams + 4 scheduler tasks now check focus mode and pause during training. Only 3 essential streams remain active (training_status, focus_mode, system_status).
- [FIXED ✅] **IB Pusher GET timeout** (April 2026): `/api/ib/orders/pending` was sync on event loop — wrapped in `asyncio.to_thread`. Plus `push-data`/`pushed-data` converted to `async def` (in-memory only, no thread pool needed).

## Recent Enhancements (April 2026)
- **Pipeline Progress Panel**: `PipelineProgressPanel.jsx` — real-time per-phase progress bars from WS training_status stream (zero extra polling).
- **Focus mode auto-pause**: `safePolling` globally pauses non-essential frontend polls during training. Backend streams + scheduler tasks also pause. All resume automatically when training completes via WS focus_mode broadcast.

## Prioritized Backlog

### P1
- Auto-Optimize AI Settings: Sweep confidence thresholds and lookback windows per strategy

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
- `/app/backend/services/ai_modules/training_pipeline.py` — Training pipeline logic
- `/app/backend/services/ai_modules/agent_data_service.py` — Agent context data (sync)
- `/app/backend/services/strategy_promotion_service.py` — Strategy lifecycle (sync)
- `/app/backend/routers/ai_modules.py` — AI module endpoints
- `/app/backend/routers/strategy_promotion_router.py` — Promotion endpoints
- `/app/backend/routers/learning_connectors_router.py` — Learning connector endpoints

## Key API Endpoints
- `POST /api/ai-training/start` — Start training pipeline
- `GET /api/ai-training/status` — Training status
- `GET /api/ai-training/regime-live` — Live regime data
- `GET /api/ai-modules/report-card` — Personal trading report card
- `GET /api/strategy-promotion/phases` — Strategy lifecycle phases
- `GET /api/strategy-promotion/candidates` — Promotion candidates
