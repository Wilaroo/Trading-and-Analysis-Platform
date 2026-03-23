# SentCom AI Trading Bot - Product Requirements Document

**Last Updated:** March 24, 2026

## Original Problem Statement
Build a self-improving AI trading bot "SentCom" by hardening the data pipeline, creating automation, and improving the UI. After completing massive historical data collection (39M bars), the primary goal shifted to training AI models on this new dataset, integrating models into the bot's decision-making, and streamlining the local development/training environment.

A critical issue emerged where the user's local backend would freeze or crash during startup and under heavy load. This made application stability the top priority.

## Core Requirements
1. **Robust Data Pipeline**: Collect historical data for all required timeframes - COMPLETED
2. **Autonomous Learning Loop**: Implement automation for data collection and model training - IN PROGRESS
8. **Job Processing Pipeline**: Background jobs (AI training) correctly created, queued, and executed by worker - COMPLETED
3. **Comprehensive UI**: Consolidate all AI, learning, and data management features - IN PROGRESS
4. **Startup Status Dashboard**: Correctly reflect backend service status - COMPLETED
5. **Comprehensive User Guide**: Create detailed, visual, downloadable guide - COMPLETED
6. **Resource Prioritization System ("Focus Mode")**: Manage application resources - COMPLETED
7. **Startup & Polling Optimization**: Prevent backend overload from frontend requests - COMPLETED

## Architecture
```
/app
+-- backend/
|   +-- server.py              # Main FastAPI server
|   +-- worker.py              # Background job processor
|   +-- routers/               # Modular API routers
|   +-- services/              # Business logic
|   +-- models/                # Data models
|   +-- database.py            # MongoDB connection
+-- frontend/src/
|   +-- components/
|   |   +-- StartupModal.jsx   # Sequential health checks
|   |   +-- SentCom.jsx        # Main AI command center (safePolling integrated)
|   |   +-- NewDashboard.jsx   # Bot-centric dashboard (safePolling integrated)
|   |   +-- JobManager.jsx     # Background jobs (safePolling integrated)
|   +-- contexts/
|   |   +-- FocusModeContext.jsx
|   |   +-- StartupManagerContext.jsx
|   +-- hooks/
|   |   +-- useVisibility.js   # Viewport/tab visibility hook
|   |   +-- useSmartPolling.js  # Focus-aware polling
|   |   +-- useCommandCenterData.js # (safePolling integrated)
|   +-- utils/
|   |   +-- safePolling.js     # NEW: Staggered, visibility-aware polling
|   |   +-- requestThrottler.js # 4-concurrent-max request limiter
|   |   +-- api.js             # Axios instance with throttler
|   +-- pages/
|       +-- CommandCenterPage.js # (safePolling integrated)
+-- documents/                 # Guides, scripts, deployment docs
+-- memory/PRD.md
```

## What's Been Implemented

### IB Service Event Loop Fix (March 23, 2026) - COMPLETED
**Root cause**: All 18 `async def` methods in `ib_service.py` called `_send_request()` synchronously, which uses `queue.get(timeout=30)` — a blocking call that froze the entire asyncio event loop. During IB Gateway connect (20s timeout), NO HTTP requests could be processed.

**Fix**: Added `_async_request()` method that wraps `_send_request` in `asyncio.to_thread()`. All 18 async methods now use this non-blocking wrapper. The health endpoint responds in ~11ms even while IB operations are in progress.
Multi-layered defense against backend overload during startup:

1. **Sequential Health Checks** (StartupModal.jsx):
   - Checks services one at a time with 750ms delay between each
   - Uses **recursive setTimeout** (not setInterval) — no overlapping rounds
   - **Bypasses the request throttler** via `window.__originalFetch` — health checks don't compete with other queued requests
   - Skips services that already returned 'success' — no redundant re-checks
   - Auto-passes Database when Backend succeeds (same `/api/health` endpoint)
   - 10s timeout (increased from 5s) for slow-starting backends
   - **"Start Anyway" button** after 5 attempts — user is never stuck
   - Blocks main app content until core services verified
   - WebSocket check runs independently

2. **safePolling Utility** (utils/safePolling.js) - NEW:
   - Random stagger (0-3s) on first poll to prevent thundering herd
   - Deterministic spread based on creation order (300ms increments)
   - Tab visibility awareness - skips polls when tab is hidden
   - `essential` flag for trading-critical polls that should continue
   - Applied to 17+ polling intervals across the codebase

3. **Request Throttler** (utils/requestThrottler.js):
   - Global fetch() patch limits to 4 concurrent requests
   - Queue system for excess requests
   - Prevents browser ERR_INSUFFICIENT_RESOURCES

4. **Context Startup Deferral**:
   - ConnectionManager delays health checks 5s, starts periodic loop after 10s (was: immediate + 30s setInterval)
   - FocusModeContext delays sync 8s, reduced polling to 30s (was: immediate + 10s setInterval)
   - StartupStatusDashboard deferred until after modal completes

5. **StartupManager** (contexts/StartupManagerContext.jsx):
   - Wave-based feature loading (5 waves over 60s)
   - useSmartPolling respects wave readiness

6. **Focus Mode** (contexts/FocusModeContext.jsx):
   - Modes: Live Trading | Data Collection | AI Training | Backtesting
   - Non-essential polling auto-pauses in non-Live modes

### Components Updated with safePolling:
- SentCom.jsx (11 polling hooks)
- useCommandCenterData.js (5 polling intervals)
- CommandCenterPage.js (1 Ollama poll)
- AICoachTab.jsx (1 regime/session poll)
- NewDashboard.jsx (4 polling intervals)
- StartupStatusDashboard.jsx (1 status poll)
- MarketRegimeWidget.jsx (1 regime poll)
- LearningInsightsWidget.jsx (1 insights poll)
- JobManager.jsx (1 jobs poll)
- BotPerformanceChart.jsx (1 equity curve poll)

### Job Queue Fix (March 24, 2026) - COMPLETED
**Root cause**: `job_queue_manager.py` was partially refactored — first 5 methods used `asyncio.to_thread` correctly, but 7 remaining methods (`complete_job`, `fail_job`, `cancel_job`, `get_recent_jobs`, `get_running_jobs`, `cleanup_old_jobs`, `get_queue_stats`) still used raw `await` on synchronous pymongo calls or motor-style `cursor.to_list()` syntax. Additionally, the `/jobs/stats` and `/jobs/cleanup` routes were defined after the `/jobs/{job_id}` wildcard in `focus_mode_router.py`, causing them to be swallowed by the wildcard match.

**Fix**: Converted all 7 remaining methods to use `asyncio.to_thread` for pymongo calls. Moved `/jobs/stats` and `/jobs/cleanup` routes before the `{job_id}` wildcard. Cleaned up 10 stale "running" jobs from previous failed attempts.

**All 8 job queue endpoints verified working**: create, list, running, pending, stats, get-by-id, cancel, cleanup.

### Previous Implementations
- WebSocket Status Fix
- Focus-Aware Polling Integration
- Worker Process Jobs
- JobManager UI Component
- Job Completion Notifications
- Command Center Header Consolidation
- Frontend Resilience Layer (contexts, hooks)

## Trained Models
| Timeframe | Model Name | Accuracy | Training Samples |
|-----------|------------|----------|-----------------|
| 1 day | direction_predictor_daily | 53.7% | 2,796,708 |
| 1 hour | direction_predictor_1hour | 55.4% | 3,385,592 |

## Outstanding Issues / Backlog

### P1 - High Priority
1. **Implement Best Model Protection** - Save only if accuracy improves over current active model
2. **Fix `fill-gaps` Endpoint** - `/api/ib-collector/fill-gaps` hangs the server

### P2 - Medium Priority
3. **Enable GPU for LightGBM** - Re-install with GPU support
4. **Complete Backend Router Refactoring** - Activate modular routers in server.py
5. **Migrate remaining direct fetch() calls** - ~93 raw fetch calls to use central api (axios) instance
6. **Implement useVisibility in off-screen components** - Further optimization using IntersectionObserver

### P3 - Future
7. **Setup-Specific AI Models** (77 trading setups)
8. **Implement Backtesting Workflow Automation**

## Key API Endpoints
- `GET /api/health` - Backend health check
- `GET /api/consolidated-status` - All service statuses in one call
- `POST /api/jobs` - Create background job
- `GET /api/jobs/status/{job_id}` - Poll job status
- `POST /api/ai-modules/timeseries/forecast` - Get AI prediction
- `GET /api/ai-modules/timeseries/status` - Model status

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- Ollama Pro
- MongoDB Atlas
- PyTorch (with CUDA)
- LightGBM
- ChromaDB
- motor (async MongoDB driver)
