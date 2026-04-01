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
- [FIXED — USER VERIFICATION PENDING] Thread pool exhaustion during training: Dedicated `ThreadPoolExecutor(max_workers=2)` added to `training_pipeline.py`. ML training tasks no longer compete with DB queries for the default asyncio thread pool.
- [FIXED] `stream_training_status` crash: `UnboundLocalError` on `status` variable when no WS clients connected at startup. Fixed by initializing `status = None` before the while loop in `server.py`.

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
