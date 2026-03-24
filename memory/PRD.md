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

## P2 Refactoring (IN PROGRESS - Feb 2026)

### P2.1: GPU for LightGBM ✅ COMPLETED
- Auto-detection of GPU availability for LightGBM training

### P2.2: Backend Router Refactoring ✅ COMPLETED
- **server.py reduced from 5,038 → 3,741 lines** (26% reduction)
- **Inline routes reduced from 56 → 19** (remaining are system-level/WebSocket)
- Extracted route groups:
  - `routers/watchlist.py` — Watchlist CRUD + Smart Watchlist
  - `routers/portfolio.py` — Portfolio positions with IB fallback
  - `routers/earnings_router.py` — Earnings calendar, analysis, IV
  - `routers/ollama_proxy.py` — HTTP proxy state, endpoints, helpers
  - `routers/market_data.py` — Quotes, fundamentals, VST, insider, COT, news

### P2.3: Migrate Raw fetch() Calls ✅ COMPLETED
- **108 raw fetch() calls migrated to centralized api utility**
- Added `safeGet`, `safePost`, `safeDelete` helpers to `utils/api.js`
- Updated 21 frontend files
- Preserved EventSource/WebSocket URL patterns (kept API_URL where needed)

### P2.4: Merge historical_simulation_engine — NOT STARTED
- Merge into advanced_backtest_engine as "AI Simulation" mode

## Upcoming Tasks
- **(P1.5)** AI Parameter Auto-Optimizer — sweep confidence thresholds & lookback windows
- **(P2.4)** Merge historical_simulation_engine into advanced_backtest_engine

## Future/Backlog
- **(P3)** Setup-Specific AI Models (train per trading setup)
- **(P3)** Backtesting Workflow Automation (auto-run on model train)
- **(P3)** Auto-Optimize AI Settings (saved enhancement idea)

## Key API Endpoints
- `/api/health` — System health check
- `/api/watchlist`, `/api/smart-watchlist` — Watchlist management (router)
- `/api/portfolio` — Portfolio positions (router)
- `/api/earnings/*` — Earnings calendar & analysis (router)
- `/api/quotes/*`, `/api/market/*`, `/api/news` — Market data (router)
- `/api/ollama-proxy/*`, `/api/ollama-usage` — Ollama proxy (router)
- `/api/backtest/ai-comparison` — AI comparison backtesting
- `/api/ai-modules/timeseries/*` — AI model management
- `/api/dashboard/*` — Dashboard aggregation

## Database Collections
- `watchlists`, `portfolios`, `alerts` — User data
- `timeseries_model_archive` — Historical AI model versions
- `sentcom_chats` — Chat history
- Various market data collections

## Testing
- Test reports: `/app/test_reports/iteration_103.json` (latest - all 20 tests passed)
- Backend tests: `/app/backend/tests/test_p2_router_refactoring.py`
