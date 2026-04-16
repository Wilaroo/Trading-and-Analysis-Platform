# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform optimization across DGX Spark + Windows PC dual-GPU architecture.

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB): Backend + Frontend + MongoDB (178M+ bars)
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Pusher + Collectors
- **Data**: 100% Interactive Brokers via local MongoDB

## Completed Work (Apr 16, 2026)

### Thread Exhaustion Fix
- Phase 1: Dedicated Chat Server (port 8002)
- Phase 1.5: Chat Context via MongoDB (zero HTTP to main backend)
- Phase 2: Streaming Cache Layer (1 thread/cycle vs 26+)
- Server Health Badge (inline in SENTCOM header)

### Stability Optimization Pass
- **Chat proxy**: `sync requests.post` → `async httpx` (zero threads for chat)
- **28 async endpoints → def**: Stopped blocking event loop with sync MongoDB
  - ai_modules.py: 10 endpoints
  - quick_actions.py: 5 endpoints
  - learning_connectors_router.py: 5 endpoints
  - ai_training.py: 4 endpoints (+ response caching)
  - market_context.py: 3 endpoints
  - short_data.py: 1 endpoint
- **IB order execution**: `get_order_result` wrapped in `asyncio.to_thread` (was blocking event loop for 60s during trade execution)
- **IB order result endpoint**: `async def` → `def` (time.sleep in loop)
- **Aggregated insights endpoint**: `/api/ai-modules/insights-summary` replaces 5 separate calls
- **Request throttler**: `maxConcurrent` 2 → 4
- **WS first-broadcast fix**: Scanner/trades/sentcom now broadcast on first cycle
- **SentCom WS delay**: 15s → 5s, cache defaults include positions key

## Key Endpoints
- `localhost:8001/api/health` — Backend health (async)
- `localhost:8001/ping` — Minimal diagnostic
- `localhost:8001/api/cache-status` — Cache health + memory + threads
- `localhost:8002/health` — Chat server
- `localhost:8002/chat` — Chat endpoint
- `localhost:8002/context-debug` — Chat context diagnostic
- `localhost:8001/api/ai-modules/insights-summary` — Aggregated AI insights

## Upcoming Tasks
- Phase 5e: RL Position Sizer
- Phase 6: Distributed PC Worker
- Phase 7: Infrastructure Polish (systemd)
- Per-signal weight optimizer
- Wire confidence gate into Phase 13 validation
- Re-enable uvloop (after moving APScheduler init to startup event)

## Key Files
- `/backend/server.py` — Main backend + streaming cache
- `/backend/chat_server.py` — Isolated chat server (port 8002)
- `/backend/routers/sentcom.py` — Chat proxy (now async httpx)
- `/backend/routers/ai_modules.py` — AI endpoints + insights-summary
- `/backend/routers/ai_training.py` — Training endpoints + response cache
- `/backend/services/trade_executor_service.py` — IB trade execution
- `/frontend/src/components/ServerHealthBadge.jsx` — Health badge
- `/frontend/src/utils/requestThrottler.js` — Throttler (maxConcurrent=4)
- `/scripts/spark_start.sh` — Startup script
