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
    - ALL training endpoints now return `job_id` immediately (non-blocking)
    - Worker process handles: TRAINING, SETUP_TRAINING, DATA_COLLECTION, BACKTEST, CALIBRATION
    - Frontend polls `/api/jobs/{job_id}` for real-time progress
    - Endpoints wired: `/train`, `/train-all`, `/train-full-universe`, `/train-full-universe-all`, `/setups/train`, `/setups/train-all`
    - Worker runs as supervisor process with auto-restart
15. **Advanced Setup-Specific Models with Pattern Detection (Mar 25, 2026)** - COMPLETED
    - Pattern detection (`setup_pattern_detector.py`) filters training data to setup-relevant bars only
    - Setup-specific features (`setup_features.py`) add 6 extra features per setup type
    - Training pipeline: scan bars → detect patterns → extract base+setup features → train enriched model
    - Verified: BREAKOUT model trained on 1,438 patterns from 8,900 bars with 52 combined features

## Key API Endpoints

### Training Endpoints (all return job_id, non-blocking)
- `POST /api/ai-modules/timeseries/train` — Single timeframe training
- `POST /api/ai-modules/timeseries/train-all` — All timeframes
- `POST /api/ai-modules/timeseries/train-full-universe` — Full universe single TF
- `POST /api/ai-modules/timeseries/train-full-universe-all` — Full universe all TFs
- `POST /api/ai-modules/timeseries/setups/train` — Setup-specific model
- `POST /api/ai-modules/timeseries/setups/train-all` — All setup models
- `POST /api/ai-modules/timeseries/stop-training` — Stop training

### Job Queue Endpoints
- `POST /api/jobs` — Create job
- `GET /api/jobs/{job_id}` — Poll job status/progress
- `GET /api/jobs` — List jobs
- `DELETE /api/jobs/{job_id}` — Cancel job
- `GET /api/jobs/running` — Running jobs
- `GET /api/jobs/stats` — Queue statistics

## Worker Process
- Supervisor config: `/etc/supervisor/conf.d/worker.conf`
- Handles: TRAINING, SETUP_TRAINING, DATA_COLLECTION, BACKTEST, CALIBRATION
- Polls MongoDB `job_queue` every 5s for pending jobs
- Progress tracking via `job_queue_manager.update_progress()`

## Code Cleanup (Mar 25, 2026) — COMPLETED
- Renamed `historical_simulation_engine.py` → `simulation_engine.py`
- Updated all 3 import references (worker.py, server.py, advanced_backtest_router.py)
- Deleted the old file

## Upcoming Tasks
- **(P1) Backtesting Workflow Automation** — Auto-run backtests when a new model is trained

## Future/Backlog
- (P3) Auto-Optimize AI Settings — Sweep confidence thresholds & lookback windows
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations side-by-side

## Known Minor Issues
- General Model "Untrained" Display — Race condition on NIA page (low priority, API returns correct data)

## Testing
- `/app/test_reports/iteration_107.json` (latest - General Training Job Queue, 20/20 passed)
- `/app/test_reports/iteration_106.json` (Worker Job Queue for Setup Training, 12/12 passed)
- `/app/test_reports/iteration_105.json` (Setup Models, 10/10 passed)
- Backend tests: `/app/backend/tests/test_general_training_job_queue.py`, `/app/backend/tests/test_worker_job_queue.py`
