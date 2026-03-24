# SentCom AI Trading Bot - Product Requirements Document

**Last Updated:** March 24, 2026

## Original Problem Statement
Build a self-improving AI trading bot "SentCom" by hardening the data pipeline, creating automation, and improving the UI. After completing massive historical data collection (39M bars), the primary goal shifted to training AI models on this new dataset, integrating models into the bot's decision-making, and streamlining the local development/training environment.

A critical issue emerged where the user's local backend would freeze or crash during startup and under heavy load. This made application stability the top priority.

## Core Requirements
1. **Robust Data Pipeline**: Collect historical data for all required timeframes - COMPLETED
2. **Autonomous Learning Loop**: Implement automation for data collection and model training - IN PROGRESS
3. **Comprehensive UI**: Consolidate all AI, learning, and data management features - IN PROGRESS
4. **Startup Status Dashboard**: Correctly reflect backend service status - COMPLETED
5. **Comprehensive User Guide**: Create detailed, visual, downloadable guide - COMPLETED
6. **Resource Prioritization System ("Focus Mode")**: Manage application resources - COMPLETED
7. **Startup & Polling Optimization**: Prevent backend overload from frontend requests - COMPLETED
8. **Job Processing Pipeline**: Background jobs (AI training) correctly created, queued, and executed by worker - COMPLETED
9. **Persistent Chat History**: Chat messages persist across sessions/refreshes - COMPLETED
10. **Market Regime Clarity**: Improved Market Regime panel readability - COMPLETED
11. **Enable Shadow Learning**: System automatically evaluates shadow trade decisions - COMPLETED

## Architecture
```
/app
+-- backend/
|   +-- server.py              # Main FastAPI server (non-blocking startup, /api/startup-check)
|   +-- worker.py              # Background job processor
|   +-- routers/               # Modular API routers
|   +-- services/              # Business logic
|   |   +-- alpaca_service.py  # Fixed: sync SDK calls now use asyncio.to_thread()
|   |   +-- realtime_technical_service.py  # Fixed: DB calls use asyncio.to_thread()
|   |   +-- ib_historical_collector.py     # Fixed: DB ops use asyncio.to_thread()
|   +-- models/                # Data models
|   +-- database.py            # MongoDB connection
+-- frontend/src/
|   +-- components/
|   |   +-- StartupModal.jsx   # Rewritten: single /api/startup-check endpoint
|   |   +-- SentCom.jsx        # Main AI command center (safePolling integrated)
|   |   +-- NewDashboard.jsx   # Bot-centric dashboard (safePolling integrated)
|   |   +-- JobManager.jsx     # Background jobs (fixed button nesting)
|   +-- contexts/
|   |   +-- FocusModeContext.jsx
|   |   +-- StartupManagerContext.jsx
|   +-- hooks/
|   |   +-- useVisibility.js
|   |   +-- useSmartPolling.js
|   |   +-- useCommandCenterData.js
|   +-- utils/
|   |   +-- safePolling.js
|   |   +-- requestThrottler.js
|   |   +-- api.js
|   +-- pages/
|       +-- CommandCenterPage.js
+-- documents/                 # Guides, scripts, deployment docs
+-- memory/PRD.md
```

## What's Been Implemented

### Event Loop Blocking Fix (March 24, 2026) - COMPLETED
**Root cause**: Alpaca SDK makes synchronous HTTP calls (`get_stock_latest_quote`, `get_stock_bars`, etc.) but these were called from async functions without `asyncio.to_thread()`. Background tasks (scanner, trading bot) called these continuously, blocking the entire asyncio event loop for seconds at a time. This made even simple endpoints like `/api/health` take 6-47 seconds.

**Fixes applied**:
1. **Alpaca Service** (`services/alpaca_service.py`): Wrapped all sync SDK calls (`get_stock_latest_quote`, `get_stock_latest_trade`, `get_stock_bars`, `get_account`) in `asyncio.to_thread()`
2. **Technical Service** (`services/realtime_technical_service.py`): Wrapped sync pymongo `_get_daily_bars_from_db()` call in `asyncio.to_thread()`
3. **IB Collector** (`services/ib_historical_collector.py`): Moved `run_per_stock_collection` DB operations into `asyncio.to_thread()`
4. **Fill-Gaps Endpoint** (`routers/ib_collector_router.py`): Wrapped DB-heavy gap scanning into `asyncio.to_thread()`

**Result**: All endpoints now respond in <300ms consistently (was 6-47s)

### StartupModal Fix (March 24, 2026) - COMPLETED
**Root cause**: Modal made 6+ sequential HTTP requests to individual service endpoints (each taking 6-47s due to event loop blocking). Total startup time exceeded 30 seconds.

**Fixes applied**:
1. Created `/api/startup-check` endpoint that returns ALL service statuses from in-memory state only (no DB/network calls, responds in ~100ms)
2. Rewrote `StartupModal.jsx` to use single consolidated endpoint instead of 6+ sequential calls
3. Made `startup_event` non-blocking by deferring IB connect, scanner start, and bot start into `asyncio.create_task()`

**Result**: Modal completes in <3 seconds (was 30+ seconds or stuck indefinitely)

### Fill-Gaps Endpoint Fix (March 24, 2026) - COMPLETED
**Root cause**: Sync pymongo queries on large collections blocked the event loop indefinitely.
**Fix**: DB operations wrapped in `asyncio.to_thread()`
**Result**: Endpoint returns in ~25 seconds for 442 symbols (was hanging indefinitely)

### Previous Implementations
- IB Service Event Loop Fix (March 23, 2026)
- Startup & Polling Optimization (safePolling, requestThrottler)
- Focus Mode System
- Job Queue Fix (March 24, 2026)
- WebSocket Status Fix
- Focus-Aware Polling Integration
- Worker Process Jobs
- Job Completion Notifications
- Command Center Header Consolidation
- Frontend Resilience Layer

## Trained Models
| Timeframe | Model Name | Accuracy | Training Samples |
|-----------|------------|----------|-----------------|
| 1 day | direction_predictor_daily | 53.7% | 2,796,708 |
| 1 hour | direction_predictor_1hour | 55.4% | 3,385,592 |

## Outstanding Issues / Backlog

### P1 - High Priority
1. **Implement Best Model Protection** - Save only if accuracy improves over current active model

### P2 - Medium Priority
2. **Enable GPU for LightGBM** - Re-install with GPU support
3. **Complete Backend Router Refactoring** - Activate modular routers in server.py
4. **Migrate remaining direct fetch() calls** - ~93 raw fetch calls to use central api (axios) instance
5. **Implement useVisibility in off-screen components** - Further optimization using IntersectionObserver

### P3 - Future
6. **Setup-Specific AI Models** (77 trading setups)
7. **Implement Backtesting Workflow Automation**

## Key API Endpoints
- `GET /api/health` - Backend health check (~100ms)
- `GET /api/startup-check` - Consolidated startup status (~100ms, in-memory only)
- `GET /api/consolidated-status` - All service statuses in one call
- `POST /api/jobs` - Create background job
- `GET /api/jobs/status/{job_id}` - Poll job status
- `POST /api/ai-modules/timeseries/forecast` - Get AI prediction
- `GET /api/ai-modules/timeseries/status` - Model status
- `POST /api/ib-collector/fill-gaps` - Smart gap filler (~25s)

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- Ollama Pro
- MongoDB Atlas
- PyTorch (with CUDA)
- LightGBM
- ChromaDB
- Alpaca Markets (data feed)
- motor (async MongoDB driver)
