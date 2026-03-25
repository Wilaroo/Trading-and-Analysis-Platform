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
### P2.2: Backend Router Refactoring - COMPLETED
- **server.py reduced from 5,038 to 3,091 lines** (39% total reduction)
- **Inline routes reduced from 56 to 4** (only WebSocket/SSE/scripts remain)
- Extracted route groups: watchlist, portfolio, earnings, ollama_proxy, market_data, advanced_backtest, system_status, dashboard (includes alerts CRUD, scanner, wave-scanner, universe)

### P2.3: Migrate Raw fetch() Calls - COMPLETED
### P2.4: Merge historical_simulation_engine - COMPLETED (Mar 25, 2026)
- Full AI Sim tab with detailed results (Summary/Trades/Decisions)
- Market-wide backtest now runs as background jobs with progress polling

### P2.5: Code Cleanup - COMPLETED (Mar 25, 2026)
- Deleted `simulation_router.py` (superseded by advanced_backtest_router)
- Deleted `TeamBrain.jsx` (unused component)
- Removed all references from server.py
- Fixed pre-existing bugs in consolidated-status (undefined variable names)
- Fixed missing imports in RightSidebar.jsx and TradingBotPanel.jsx

### P2.6: Final server.py Extraction - COMPLETED (Mar 25, 2026)
- **Created `system_router.py`**: health, startup-check, consolidated-status, llm/status, system/monitor (5 routes)
- **Created `dashboard_router.py`**: dashboard/stats, dashboard/init, alerts CRUD, scanner/scan, scanner/presets, wave-scanner/*, universe/* (12 routes)
- All 17 REST routes extracted; only 4 routes remain (2 WebSocket, 1 SSE, 1 scripts)
- Fixed consolidated-status to use get_service_optional correctly (was using undefined variable names)

## Remaining in server.py
- 4 inline routes: `/api/ws/quotes` (WebSocket), `/api/ws/ollama-proxy` (WebSocket), `/api/stream/status` (SSE), `/api/scripts/{script_name}` (static)
- These are tightly coupled to ConnectionManager + background tasks and should remain

## Upcoming Tasks
- **(P1.5)** AI Parameter Auto-Optimizer: sweep confidence thresholds & lookback windows
- **(P3)** Setup-Specific AI Models (train per trading setup)
- **(P3)** Backtesting Workflow Automation (auto-run on model train)

## Future/Backlog
- (P3) Auto-Optimize AI Settings
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations side-by-side

## Key API Endpoints (by router)
### system_router.py
- `/api/health` — Health check
- `/api/startup-check` — Ultra-lightweight service status
- `/api/consolidated-status` — Combined service status
- `/api/llm/status` — LLM provider status
- `/api/system/monitor` — Comprehensive system health

### dashboard_router.py
- `/api/dashboard/stats` — Dashboard summary stats
- `/api/dashboard/init` — Batch initial data load
- `/api/alerts`, `/api/alerts/generate`, `/api/alerts/clear` — Alert CRUD
- `/api/scanner/scan`, `/api/scanner/presets` — Market scanner
- `/api/wave-scanner/*` — Wave scanner (batch/stats/config)
- `/api/universe/*` — Index universe (stats/symbols)

### advanced_backtest_router.py
- `/api/backtest/*` — Strategy backtesting, AI comparison, full AI simulation

### Other routers
- watchlist, portfolio, earnings, ollama_proxy, market_data, ai_modules, etc.

## Database Collections
- `watchlists`, `portfolios`, `alerts` — User data
- `timeseries_model_archive` — Historical AI model versions
- `sentcom_chats` — Chat history
- `sim_jobs`, `sim_trades`, `sim_decisions` — Full AI simulation data

## Testing
- Test reports: `/app/test_reports/iteration_104.json` (latest)
