# SentCom AI Trading Bot - Product Requirements Document

**Last Updated:** March 24, 2026

## Original Problem Statement
Build a self-improving AI trading bot "SentCom" by hardening the data pipeline, creating automation, and improving the UI.

## Core Requirements Status
1. Robust Data Pipeline - COMPLETED
2. Autonomous Learning Loop - IN PROGRESS
3. Comprehensive UI - IN PROGRESS
4. Startup Status Dashboard - COMPLETED
5. User Guide - COMPLETED
6. Focus Mode - COMPLETED
7. Startup & Polling Optimization - COMPLETED
8. Job Processing Pipeline - COMPLETED
9. Persistent Chat History - COMPLETED
10. Market Regime Clarity - COMPLETED
11. Shadow Learning - COMPLETED

## AI LLM Routing
| Priority | Provider | Model |
|----------|----------|-------|
| 1st | HTTP Ollama Proxy | gpt-oss:120b-cloud |
| 2nd | HTTP Ollama Proxy | llama3:8b (fallback) |
| 3rd | WS Ollama Proxy | qwen2.5:7b |
| 4th | Direct Ollama (ngrok) | qwen2.5:7b |
| 5th | Emergent GPT-4o | GPT-4o (paid) |

## Session Fixes (March 24, 2026)

### Event Loop Blocking Fix
- Wrapped Alpaca SDK sync calls in asyncio.to_thread() (alpaca_service.py)
- Wrapped sync pymongo calls in asyncio.to_thread() (realtime_technical_service.py, ib_historical_collector.py)
- All endpoints: <2ms locally (was 6-47s)

### StartupModal Rewrite
- Single /api/startup-check endpoint (in-memory, <2ms)
- AI status: green=Ollama available, yellow "Fallback Only"=Emergent only
- Non-blocking startup_event via asyncio.create_task()

### Data Loading & Persistence
- Context delays: 20s → 3s (SystemStatus, ConnectionManager)
- Tab switching: Command Center + NIA always mounted (display:none/block) — data persists
- Initial scanner alerts fetched via REST + WebSocket

### Position P&L Fix
- Backend: Fixed null P&L for IB positions — calculates from prices if unrealizedPnL unavailable
- Backend: Fixed field name `position_type` → `direction` for IB positions
- Frontend: Fixed field name mismatches in NewDashboard position cards (pnl_percent, entry_price, shares, direction)

### Learning Insights Fix
- Aggregates stats across all bot strategies (excludes manual imports)
- Shows: Win Rate, Total PnL, Avg R-Multiple, Edge Score

### Bot Performance Chart Fix
- Cached per-timerange data for instant Today/Week/Month/YTD switching
- No chart flash on switch (preserves old data while loading new)

### Market Regime Fix
- Fixed double-fetch on mount (lastState → useRef)
- Loading only on initial load, not refresh cycles

### Scanner Alerts Fix
- ScannerAlertsStrip now self-sufficient (fetches own data via REST if WebSocket prop is empty)
- Auto-refreshes every 30 seconds

### Fill-Gaps Endpoint Fix
- DB ops in asyncio.to_thread() — returns in ~25s (was hanging indefinitely)

## Key Files Modified
- backend/server.py — startup-check endpoint, non-blocking startup, scanner alert in WS initial data
- backend/services/alpaca_service.py — asyncio.to_thread for SDK calls
- backend/services/sentcom_service.py — position P&L calculation fix
- backend/services/realtime_technical_service.py — asyncio.to_thread for DB
- backend/routers/ib_collector_router.py — thread-safe fill-gaps
- frontend/src/App.js — always-mounted tabs, initial scanner alerts fetch
- frontend/src/components/StartupModal.jsx — single endpoint, AI status
- frontend/src/components/NewDashboard.jsx — position field fixes, self-sufficient alerts
- frontend/src/components/BotPerformanceChart.jsx — time range caching
- frontend/src/components/MarketRegimeWidget.jsx — double-fetch fix
- frontend/src/components/LearningInsightsWidget.jsx — stat aggregation
- frontend/src/contexts/SystemStatusContext.jsx — 3s delay
- frontend/src/contexts/ConnectionManagerContext.jsx — 3s delay

## Outstanding Backlog
### P1
1. Implement Best Model Protection (save only if accuracy improves)

### P2
2. Enable GPU for LightGBM
3. Complete Backend Router Refactoring
4. Migrate ~93 raw fetch() calls to central api instance

### P3
5. Setup-Specific AI Models (77 setups)
6. Backtesting Workflow Automation
