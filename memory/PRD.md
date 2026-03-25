# SentCom AI Trading Platform - Product Requirements

## Overview
AI-powered trading platform with autonomous learning, backtesting, and market analysis capabilities.

## Architecture
- **Backend**: FastAPI (Python) + MongoDB + Worker process (supervisor-managed)
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
12. P2 Refactoring (GPU for LightGBM, backend router refactoring, fetch migration, engine merge, code cleanup, server extraction)
13. **Setup-Specific AI Models (Mar 25, 2026)** - COMPLETED
14. **Worker-Based Job Queue for ALL Training (Mar 25, 2026)** - COMPLETED
15. **Advanced Setup-Specific Models with Pattern Detection (Mar 25, 2026)** - COMPLETED
16. **Fix: AI Model "Untrained" Display on First Load (Mar 25, 2026)** - COMPLETED
17. **Fix: POST Requests Blocked by Request Throttler (Mar 25, 2026)** - COMPLETED
18. **Fix: IB Gateway Startup Check Shows False Green (Mar 25, 2026)** - COMPLETED
19. **CRITICAL FIX: Setup Models Were Copies of General Model (Mar 25, 2026)** - COMPLETED
20. **P0 FIX: WebSocket Training Commands (Mar 25, 2026)** - COMPLETED
    - Root cause: Browser's HTTP connection pool (6 per domain) saturated by polling GET requests, blocking training POST requests
    - Fix: All training commands (setup, setup_all, general) now sent via WebSocket, bypassing HTTP entirely
    - Backend: 3 new WebSocket actions (train_setup, train_setup_all, train_general) using job_queue_manager singleton
    - Frontend: useWebSocket hook exposes `sendTrainCommand()` promise-based function
    - Frontend: SetupModelsPanel + UnifiedAITraining migrated from xhrPost → sendTrainCommand
    - Also fixed: WebSocket URL now correctly includes /api/ws/quotes path

## Key API Endpoints

### Training Endpoints (all return job_id, non-blocking)
- `POST /api/ai-modules/timeseries/train` — Single timeframe training
- `POST /api/ai-modules/timeseries/train-all` — All timeframes
- `POST /api/ai-modules/timeseries/train-full-universe` — Full universe single TF
- `POST /api/ai-modules/timeseries/train-full-universe-all` — Full universe all TFs
- `POST /api/ai-modules/timeseries/setups/train` — Setup-specific model
- `POST /api/ai-modules/timeseries/setups/train-all` — All setup models

### WebSocket Training (bypasses HTTP — preferred for UI)
- `WS /api/ws/quotes` action: `train_setup` — Queue setup-specific model training
- `WS /api/ws/quotes` action: `train_setup_all` — Queue all setup models training
- `WS /api/ws/quotes` action: `train_general` — Queue general model training

### Job Queue Endpoints
- `POST /api/jobs` — Create job
- `GET /api/jobs/{job_id}` — Poll job status/progress
- `GET /api/jobs` — List jobs
- `DELETE /api/jobs/{job_id}` — Cancel job

## Upcoming Tasks
- **(P1) Backtesting Workflow Automation** — Auto-run backtests when a new model is trained
- **(P2) Improve Setup Model Accuracy** — Current models at ~47-48%, need better pattern detection

## Future/Backlog
- (P3) Auto-Optimize AI Settings — Sweep confidence thresholds & lookback windows
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations side-by-side

## Known Minor Issues
- None

## Testing
- `/app/test_reports/iteration_107.json` (General Training Job Queue, 20/20 passed)
- `/app/test_reports/iteration_108.json` (WebSocket Training Commands, 8/9 passed, 1 transient)
