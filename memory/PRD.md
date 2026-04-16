# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform optimization across DGX Spark + Windows PC dual-GPU architecture.

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB): Backend + Frontend + MongoDB (178M+ bars)
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Pusher + Collectors
- **Data**: 100% Interactive Brokers via local MongoDB

## All Completed Work (Apr 16, 2026)

### Thread Exhaustion Fix
- Phase 1: Dedicated Chat Server (port 8002)
- Phase 1.5: Chat Context via MongoDB (zero HTTP to main backend)
- Phase 2: Streaming Cache Layer (1 thread/cycle vs 26+)
- Server Health Badge (inline in SENTCOM header)

### Stability Optimization Pass (Round 1)
- Chat proxy → async httpx (zero threads for chat)
- 28 async endpoints → def (stopped blocking event loop)
- IB trade execution: get_order_result → asyncio.to_thread
- Aggregated insights endpoint: 5 API calls → 1
- Request throttler: maxConcurrent 2 → 4
- WS first-broadcast fix for scanner/trades/sentcom

### Stability Optimization Pass (Round 2 — Phase A)
- Schedulers moved to startup event (APScheduler-safe, enables future uvloop)
- Response caching: shadow/stats, report-card, regime-live, model-inventory (30s TTL)
- Pre-computed ib_historical_data summaries (ib_data_summary collection)
- Aggregated /api/ai-modules/insights-summary endpoint

## Upcoming Tasks
- Phase 5e: RL Position Sizer
- Phase 6: Distributed PC Worker
- Phase 7: Infrastructure Polish (systemd)
- Re-enable uvloop (schedulers now in startup event — ready)

## Key Files
- `/backend/server.py` — Main backend + streaming cache
- `/backend/chat_server.py` — Isolated chat server (port 8002)
- `/backend/routers/sentcom.py` — Chat proxy (async httpx)
- `/backend/routers/ai_modules.py` — AI endpoints + insights-summary + caching
- `/backend/routers/ai_training.py` — Training endpoints + response cache
- `/backend/services/trade_executor_service.py` — IB trade execution (threaded)
- `/frontend/src/components/ServerHealthBadge.jsx` — Health badge
- `/frontend/src/utils/requestThrottler.js` — Throttler (maxConcurrent=4)
