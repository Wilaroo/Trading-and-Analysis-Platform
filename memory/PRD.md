# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform optimization. Implement XGBoost GPU swap, resolve Train/Serve data skew by removing Alpaca dependencies, eliminate scanning bottlenecks, refactor the subtractive confidence gate to an additive system, integrate Deep Learning models across the dual-GPU architecture (DGX Spark + Windows PC), and optimize feature extraction for 128GB DGX Spark memory.

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB unified memory): Backend/Frontend + local MongoDB `tradecommand` (178M+ bars). Runs XGBoost + DL models.
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Turbo Collectors + (Future) distributed DL training over LAN.
- **Data**: 100% Interactive Brokers via local MongoDB. No Alpaca/Finnhub/TwelveData in trading paths.

## Completed Phases

### Phase 1: 100% IB Data (DONE)
### Phase 2: XGBoost GPU Swap (DONE)
### Phase 3: Training Optimizations (DONE)
### Phase 4: Scanner Upgrade (DONE)
### Phase 4.5: Confidence Gate Refactor (DONE)
### Phase 5a: Training Pipeline Bug Fixes (DONE)
### Phase 5b: Deep Learning Models (DONE)
### Phase 5c: FinBERT Sentiment (DONE)
### Phase 5d: Training Pipeline Optimization (DONE)
### Phase 5e: IB Pusher Training Guard (DONE)
### Phase 5f: Restart Script OOM Fix (DONE)
### Phase 5g: Memory Management & BSON Fix (DONE)
### Phase 5h: Systemic Pipeline Memory Fixes (DONE)
### Phase 5i: Pipeline Caching & Resume (DONE)
### Phase 5j: OOM Fix — Per-Bar-Size Symbol Caps (DONE)
### Phase 5k: Vectorized Feature Extraction (DONE)
### DL Model Status Fix (DONE)
### Phase 13 Validation Entry Rules (DONE)
### Shadow Tracking Stats Fix (DONE)
### Zombie Process Prevention (DONE)

## Thread Exhaustion Fix (DONE — Apr 16, 2026)

### Phase 1: Dedicated Chat Server (DONE)
- Extracted LLM Chat from main backend into isolated `chat_server.py` on port 8002
- `setupProxy.js` routes `/api/sentcom/chat` to chat server
- `spark_start.sh` / `spark_stop.sh` manage both processes

### Phase 1.5: Chat Context via MongoDB (DONE — Apr 16, 2026)
- **Problem:** Chat server (port 8002) couldn't fetch portfolio context from main backend (port 8001) due to thread exhaustion — all HTTP calls timed out
- **Fix 1:** IB push endpoint (`POST /api/ib/push-data`) now writes a snapshot to MongoDB `ib_live_snapshot` collection
- **Fix 2:** Chat server reads ALL context from MongoDB directly — zero HTTP calls to main backend
- **Fix 3:** Fixed wrong scanner URL (`/api/scanner/alerts` → `/api/live-scanner/alerts`)
- **Fix 4:** Fixed trades formatting crash (`NoneType.__format__` on `pnl=None`)
- **Fix 5:** Improved LLM prompt — no longer asks user to paste data when context is empty
- **Added:** `/context-debug` diagnostic endpoint on chat server (port 8002)
- **Result:** Chat has full portfolio awareness via MongoDB (trades, shadow decisions, positions when IB pushes)

### Phase 2: Streaming Cache Layer (DONE — Apr 16, 2026)
- **Problem:** 17 WebSocket stream tasks each made 1-3 `asyncio.to_thread()` calls per cycle = 26+ threads consumed every 10-15 seconds. Thread pool (32) saturated, sync endpoints queued, health check timed out.
- **Fix:** One `_streaming_cache_loop()` background task runs every 10s:
  - Single `asyncio.to_thread(_compute_all_sync_data)` call gathers ALL dashboard data in 1 thread
  - All 17 stream functions now read from a Python dict — zero threads, instant
  - Cache only refreshes when WebSocket clients are connected
  - Initial refresh on startup (warms cache before streams read)
- **Additional fixes:**
  - Thread pool: 32 → 64
  - `/api/health` and `/api/startup-check` → `async def` (immune to thread pool saturation)
  - Added `/api/cache-status` diagnostic endpoint
  - Fixed 4 heavy endpoints in `ai_training.py` from `async def` (blocking event loop with sync MongoDB) to `def` (runs in thread pool): `get_live_regime`, `list_trained_models`, `check_data_readiness`, `get_model_inventory`
  - Added `/ping` ultra-minimal diagnostic endpoint
  - Event loop debug monitor logs lag every 10s
- **Result:** Event loop lag 0-1ms, cache 14 keys populated, 1 thread/cycle instead of 26+

## Master Training Pipeline (13 Phases)
| Phase | What | Models |
|-------|------|--------|
| 1 | Generic Directional (Full Universe) | 7 |
| 2 | Setup-Specific (Long) | 17 |
| 2.5 | Setup-Specific (Short) | 17 |
| 3 | Volatility Prediction | 7 |
| 4 | Exit Timing | 10 |
| 5 | Sector-Relative | 3 |
| 6 | Risk-of-Ruin | 6 |
| 7 | Regime-Conditional | 28 |
| 8 | Ensemble Meta-Learner | 10 |
| 9 | CNN Chart Patterns | 13 |
| 11 | Deep Learning (VAE/TFT/CNN-LSTM) | 3 |
| 12 | FinBERT Sentiment | 1 |
| 13 | Auto-Validation (5-phase) | 34 |
| **Total** | | **156 work units** |

## Confidence Gate Scoring (12 Layers)
- Layer 1-12: See previous PRD for full details

## Key API Endpoints
- `127.0.0.1:8001/api/health` — Main backend health (async)
- `127.0.0.1:8001/ping` — Ultra-minimal diagnostic
- `127.0.0.1:8001/api/cache-status` — Streaming cache health
- `127.0.0.1:8002/health` — Chat server health
- `127.0.0.1:8002/chat` — Chat endpoint
- `127.0.0.1:8002/context-debug` — Chat context diagnostic
- All standard API endpoints under `/api/`

## Upcoming Tasks
- Optimize new-connection latency (~4s for terminal curl, frontend unaffected via keep-alive)
- Consider `uvloop` for faster event loop
- Reduce frontend duplicate API calls (regime-live, market-regime/summary called 4x per page)
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
- `/app/backend/routers/ai_training.py` — Training pipeline endpoints (sync fixes)
- `/app/frontend/src/setupProxy.js` — Routes chat to port 8002
- `/app/scripts/spark_start.sh` — Starts backend + chat + worker + frontend
- `/app/scripts/spark_stop.sh` — Ordered shutdown

## DB Collections
- `ib_historical_data` — 178M+ bars
- `ib_live_snapshot` — NEW: IB pushed data snapshot for chat server
- `timeseries_models` — XGBoost models
- `dl_models` — PyTorch DL models
- `shadow_decisions` — AI shadow decisions
- `trades` — Trade history
- `sentcom_chat_history` — Chat messages
- `training_pipeline_status` — Pipeline state
