# SentCom AI Trading Bot - Product Requirements Document

**Last Updated:** March 24, 2026

## Original Problem Statement
Build a self-improving AI trading bot "SentCom" by hardening the data pipeline, creating automation, and improving the UI. After completing massive historical data collection (39M bars), the primary goal shifted to training AI models on this new dataset, integrating models into the bot's decision-making, and streamlining the local development/training environment.

## Core Requirements Status
1. Robust Data Pipeline - COMPLETED
2. Autonomous Learning Loop - IN PROGRESS
3. Comprehensive UI - IN PROGRESS
4. Startup Status Dashboard - COMPLETED
5. Comprehensive User Guide - COMPLETED
6. Resource Prioritization System ("Focus Mode") - COMPLETED
7. Startup & Polling Optimization - COMPLETED
8. Job Processing Pipeline - COMPLETED
9. Persistent Chat History - COMPLETED
10. Market Regime Clarity - COMPLETED
11. Enable Shadow Learning - COMPLETED

## Architecture
```
/app
+-- backend/
|   +-- server.py              # Main FastAPI (non-blocking startup, /api/startup-check)
|   +-- services/
|   |   +-- alpaca_service.py  # asyncio.to_thread() for sync SDK calls
|   |   +-- realtime_technical_service.py  # asyncio.to_thread() for DB calls
|   |   +-- ai_assistant_service.py  # LLM routing: Ollama Cloud → Local → Emergent
|   |   +-- ib_historical_collector.py  # asyncio.to_thread() for DB ops
+-- frontend/src/
|   +-- App.js                 # Tab persistence (Command Center + NIA always mounted)
|   +-- components/
|   |   +-- StartupModal.jsx   # Single /api/startup-check endpoint
|   |   +-- LearningInsightsWidget.jsx  # Fixed: aggregates per-strategy stats
|   |   +-- BotPerformanceChart.jsx     # Fixed: cached time range switching
|   |   +-- MarketRegimeWidget.jsx      # Fixed: useRef for lastState, no double-fetch
|   +-- contexts/
|   |   +-- SystemStatusContext.jsx       # 3s startup delay (was 20s)
|   |   +-- ConnectionManagerContext.jsx  # 3s startup delay (was 20s)
```

## AI LLM Routing Architecture
| Priority | Provider | Model | Usage |
|----------|----------|-------|-------|
| 1st | HTTP Ollama Proxy | gpt-oss:120b-cloud | Primary (free) |
| 2nd | HTTP Ollama Proxy | llama3:8b | Fallback if cloud fails |
| 3rd | WebSocket Ollama Proxy | qwen2.5:7b | Alt connection |
| 4th | Direct Ollama (ngrok) | qwen2.5:7b | No proxy available |
| 5th | Emergent GPT-4o | GPT-4o | Last resort (paid) |

## Implemented Fixes (March 24, 2026)

### Event Loop Blocking Fix
- Wrapped Alpaca SDK sync calls in asyncio.to_thread()
- Wrapped sync pymongo calls in asyncio.to_thread()
- All endpoints now respond in <2ms locally (was 6-47s)

### StartupModal
- Single /api/startup-check endpoint (in-memory only, <2ms)
- AI status: green when Ollama available, yellow "Fallback Only" when only Emergent
- Non-blocking startup_event via asyncio.create_task()
- "Start Anyway" after 2 failed checks

### Data Loading & Persistence
- Context delays: 20s → 3s (SystemStatus, ConnectionManager)
- Tab switching: Command Center + NIA always mounted (display:none/block)
- Initial scanner alerts fetched via REST, not just WebSocket stream

### Learning Insights Widget
- Fixed: now aggregates stats across all bot strategies (excluding manual imports)
- Shows: Win Rate, Total PnL, Avg R-Multiple, Edge Score
- Previously showed "--" for everything (API returned per-strategy dict, widget expected flat fields)

### Bot Performance Chart
- Cached time range data (instant switching between Today/Week/Month/YTD)
- No chart flash on time range switch (preserves old data while loading new)

### Market Regime Widget
- Fixed double-fetch on mount (lastState moved to useRef)
- Loading spinner only on initial load, not on refresh cycles

### Fill-Gaps Endpoint
- DB ops wrapped in asyncio.to_thread()
- Returns in ~25s for 442 symbols (was hanging indefinitely)

## Outstanding Issues / Backlog

### P1 - High Priority
1. Implement Best Model Protection (save only if accuracy improves)

### P2 - Medium Priority
2. Enable GPU for LightGBM
3. Complete Backend Router Refactoring
4. Migrate ~93 raw fetch() calls to central api (axios) instance
5. Implement useVisibility in off-screen components

### P3 - Future
6. Setup-Specific AI Models (77 trading setups)
7. Backtesting Workflow Automation

## Key API Endpoints
- `GET /api/startup-check` - Consolidated startup status (<2ms)
- `GET /api/health` - Backend health check (<2ms)
- `GET /api/market-regime/summary` - Market regime data
- `GET /api/learning/strategy-stats` - Per-strategy learning stats
- `GET /api/trading-bot/performance/equity-curve?period=today|week|month|ytd`
- `GET /api/live-scanner/alerts` - Scanner alerts (REST)
- `POST /api/ib-collector/fill-gaps` - Smart gap filler (~25s)

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- Ollama Pro (Cloud + Local)
- MongoDB Atlas
- PyTorch (with CUDA)
- LightGBM
- ChromaDB
- Alpaca Markets
- Emergent LLM Key (GPT-4o fallback)
