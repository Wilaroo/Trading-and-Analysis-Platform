# SentCom AI Trading Platform - Product Requirements

## Overview
AI-powered trading platform with autonomous learning, backtesting, and market analysis capabilities.

## Architecture
- **Backend**: FastAPI (Python) + MongoDB
- **Frontend**: React + Shadcn UI
- **3rd Party**: Interactive Brokers, Ollama Pro, Alpaca, Finnhub, LightGBM, PyTorch, ChromaDB

## Completed Features
1. Robust Data Pipeline (stocks, options, futures, COT, insider)
2. Startup Status Dashboard
3. Comprehensive User Guide
4. Resource Prioritization ("Focus Mode") & Job Queue
5. Startup & Polling Optimization
6. Persistent Chat History
7. Market Regime Detection
8. Shadow Learning (AI makes paper decisions alongside real trades)
9. AI Comparison Backtesting (setup-only, AI+setup, AI-only modes)
10. Best Model Protection (new models must beat existing to be promoted)
11. P0 Backend Performance Fix (asyncio event loop unblocking)

## P2 Refactoring (Feb-Mar 2026)

### P2.1: GPU for LightGBM - COMPLETED
- Auto-detection of GPU availability for LightGBM training

### P2.2: Backend Router Refactoring - COMPLETED
- **server.py reduced from 5,038 to 3,741 lines** (26% reduction)
- **Inline routes reduced from 56 to 19** (remaining are system-level/WebSocket)
- Extracted route groups: watchlist, portfolio, earnings, ollama_proxy, market_data, advanced_backtest

### P2.3: Migrate Raw fetch() Calls - COMPLETED
- **108 raw fetch() calls migrated to centralized api utility**
- Added `safeGet`, `safePost`, `safeDelete` helpers to `utils/api.js`

### P2.4: Merge historical_simulation_engine - COMPLETED (Mar 25, 2026)
- Added "Full AI Sim" tab to AdvancedBacktestPanel
- Backend endpoints: POST /full-ai-simulation, GET /status, /trades, /decisions, /summary, /jobs
- Fixed summary endpoint (was using non-existent methods)
- Frontend: Full config form, job start + status polling, detailed results with Summary/Trades/Decisions tabs
- Per-symbol breakdown in summary view
- Fixed missing api/safeGet imports in RightSidebar.jsx and TradingBotPanel.jsx (pre-existing compilation errors)
- Backend tests: 12/12 passed (iteration_104)

## Upcoming Tasks
- **(P1.5)** AI Parameter Auto-Optimizer: sweep confidence thresholds & lookback windows
- **(P2)** Finalize server.py refactoring: extract remaining 19 inline routes (health, status, scanner, dashboard, websockets)
- **(P2)** Code Cleanup: delete deprecated files (simulation_router.py, historical_simulation_engine.py, TeamBrain.jsx)

## Future/Backlog
- **(P3)** Setup-Specific AI Models (train per trading setup)
- **(P3)** Backtesting Workflow Automation (auto-run on model train)
- **(P3)** Auto-Optimize AI Settings (saved enhancement idea)
- **(P3)** API Route Profiling Dashboard

## Key API Endpoints
- `/api/health` — System health check
- `/api/watchlist`, `/api/smart-watchlist` — Watchlist management
- `/api/portfolio` — Portfolio positions
- `/api/earnings/*` — Earnings calendar & analysis
- `/api/quotes/*`, `/api/market/*`, `/api/news` — Market data
- `/api/ollama-proxy/*` — Ollama proxy
- `/api/backtest/ai-comparison` — AI comparison backtesting
- `/api/backtest/full-ai-simulation` — Full AI pipeline simulation (NEW)
- `/api/backtest/full-ai-simulation/summary/{job_id}` — Simulation summary with per-symbol breakdown (NEW)
- `/api/backtest/full-ai-simulation/trades/{job_id}` — Simulation trades (NEW)
- `/api/backtest/full-ai-simulation/decisions/{job_id}` — AI decisions log (NEW)
- `/api/ai-modules/timeseries/*` — AI model management
- `/api/dashboard/*` — Dashboard aggregation

## Database Collections
- `watchlists`, `portfolios`, `alerts` — User data
- `timeseries_model_archive` — Historical AI model versions
- `sentcom_chats` — Chat history
- `sim_jobs`, `sim_trades`, `sim_decisions` — Full AI simulation data

## Testing
- Test reports: `/app/test_reports/iteration_104.json` (latest - 12/12 backend tests passed)
- Backend tests: `/app/backend/tests/test_full_ai_simulation.py`
