# SentCom AI Trading Platform - Product Requirements

## Overview
AI-powered trading platform with autonomous learning, backtesting, and market analysis capabilities.

## Architecture
- **Backend**: FastAPI (Python) + MongoDB + Worker process
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
    - Backend: 5 new API endpoints for setup model management
    - Service: train_setup_model, train_all_setup_models, predict_for_setup, get_setup_models_status
    - Frontend: SetupModelsPanel.jsx on NIA page with train/status/predict UI
    - 10 setup types: MOMENTUM, SCALP, BREAKOUT, GAP_AND_GO, RANGE, REVERSAL, TREND_CONTINUATION, ORB, VWAP, MEAN_REVERSION
14. **Worker-Based Job Queue for Setup Training (Mar 25, 2026)** - COMPLETED
    - Added `SETUP_TRAINING` job type to job queue manager
    - Added `process_setup_training_job()` to worker.py (handles single + all setup types)
    - Wired setup train endpoints to enqueue jobs → API returns job_id immediately
    - Frontend polls `/api/jobs/{job_id}` every 2.5s for real-time progress (percent + message)
    - Worker runs as separate supervisor process (`/etc/supervisor/conf.d/worker.conf`)
    - Progress bars show on setup cards during training

## Key API Endpoints

### Setup-Specific Model Endpoints (ai_modules.py)
- `GET /api/ai-modules/timeseries/setups/status` — Status of all 10 setup models
- `POST /api/ai-modules/timeseries/setups/train` — Enqueue training job for specific setup type (returns job_id)
- `POST /api/ai-modules/timeseries/setups/train-all` — Enqueue job to train all setup models (returns job_id)
- `POST /api/ai-modules/timeseries/setups/predict` — Predict using setup-specific model
- `POST /api/ai-modules/timeseries/stop-training` — Stop any running training

### Job Queue Endpoints (focus_mode_router.py)
- `POST /api/jobs` — Create a new background job
- `GET /api/jobs` — List jobs with filtering
- `GET /api/jobs/{job_id}` — Poll job status/progress
- `DELETE /api/jobs/{job_id}` — Cancel a job
- `GET /api/jobs/running` — Get running jobs
- `GET /api/jobs/stats` — Queue statistics

## Database Collections
- `job_queue` — Background job queue (training, backtest, data collection, calibration, setup_training)
- `setup_type_models` — Setup-specific AI model storage
- `timeseries_models`, `ai_models` — General timeframe model storage
- `ib_historical_data` — Historical price data (39M+ bars)

## Worker Process
- Runs as separate supervisor process (`worker.py`)
- Handles: TRAINING, SETUP_TRAINING, DATA_COLLECTION, BACKTEST, CALIBRATION
- Polls MongoDB job_queue every 5s for pending jobs
- Processes jobs with progress tracking
- Config: `/etc/supervisor/conf.d/worker.conf`

## Upcoming Tasks
- **(P1) Backtesting Workflow Automation** — Auto-run backtests when a new model is trained
- **(P1) Wire existing general training through worker** — The general model training still runs inline in the server; should be moved to worker for consistency
- **(P2) Code Cleanup** — Delete unused historical_simulation_engine.py (still has active references)

## Future/Backlog
- (P3) Auto-Optimize AI Settings — Sweep confidence thresholds & lookback windows
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations side-by-side

## Testing
- Test reports: `/app/test_reports/iteration_106.json` (latest - Worker Job Queue)
- Test reports: `/app/test_reports/iteration_105.json` (Setup Models)
- Backend tests: `/app/backend/tests/test_worker_job_queue.py`
