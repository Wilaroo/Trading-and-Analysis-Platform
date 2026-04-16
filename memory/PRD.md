# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform optimization. Implement XGBoost GPU swap, resolve Train/Serve data skew by removing Alpaca dependencies, eliminate scanning bottlenecks, refactor the subtractive confidence gate to an additive system, integrate Deep Learning models across the dual-GPU architecture (DGX Spark + Windows PC), and optimize feature extraction for 128GB DGX Spark memory.

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB unified memory): Backend/Frontend + local MongoDB `tradecommand` (178M+ bars). Runs XGBoost + DL models.
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Turbo Collectors + (Future) distributed DL training over LAN.
- **Data**: 100% Interactive Brokers via local MongoDB. No Alpaca/Finnhub/TwelveData in trading paths.

## Thread Exhaustion Fix (DONE — Apr 16, 2026)

### Phase 1: Dedicated Chat Server (DONE)
- Extracted LLM Chat from main backend into isolated `chat_server.py` on port 8002

### Phase 1.5: Chat Context via MongoDB (DONE)
- Chat server reads ALL context from MongoDB directly — zero HTTP calls to main backend
- IB push endpoint writes snapshots to `ib_live_snapshot` collection

### Phase 2: Streaming Cache Layer (DONE)
- One `_streaming_cache_loop()` gathers ALL data in 1 thread every 10s
- All 17 stream functions read from Python dict — zero threads
- Thread pool: 32 → 64, health/startup endpoints made async
- Heavy blocking endpoints converted from `async def` to `def`
- Response caching (30s TTL) for `regime-live` and `model-inventory`

### Server Health Badge (DONE)
- Compact inline badge in SENTCOM header showing latency, threads, memory
- Native hover tooltip with full details
- Polls `/api/cache-status` every 20s
- Green dot based on backend health status, latency color-coded separately

### uvloop (DISABLED)
- Conflicts with APScheduler's event loop handling at module load time
- TODO: Move scheduler init to startup event, then re-enable

## Upcoming Tasks
- Phase 5e: RL Position Sizer
- Phase 6: Distributed PC Worker
- Phase 7: Infrastructure Polish (systemd services)
- Per-signal weight optimizer
- Wire confidence gate into Phase 13 validation

## Key Files
- `/app/backend/server.py` — Main backend + streaming cache layer
- `/app/backend/chat_server.py` — Isolated chat server (port 8002)
- `/app/backend/routers/system_router.py` — Health, startup, cache-status endpoints
- `/app/backend/routers/ib.py` — IB endpoints + MongoDB snapshot write
- `/app/backend/routers/ai_training.py` — Training endpoints (sync fixes + response cache)
- `/app/frontend/src/components/ServerHealthBadge.jsx` — Server health badge
- `/app/frontend/src/components/SentCom.jsx` — Main UI (imports health badge)
- `/app/scripts/spark_start.sh` — Starts all services
- `/app/scripts/spark_stop.sh` — Ordered shutdown
