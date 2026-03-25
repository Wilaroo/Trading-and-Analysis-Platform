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
    - Reduced throttler concurrency from 16 to 4 (browser limit is 6)
    - POST/PUT/DELETE bypass throttler entirely
    - Added `xhrPost` utility for training actions (bypasses axios stack)
18. **Fix: IB Gateway Startup Check Shows False Green (Mar 25, 2026)** - COMPLETED
    - Now checks actual data flow, not just socket connection
    - Shows "No Data" (yellow) when connected but farms are down
19. **CRITICAL FIX: Setup Models Were Copies of General Model (Mar 25, 2026)** - COMPLETED
    - **Root cause**: `train_from_features()` called `_save_model()` which compared against the general model, model protection rejected the setup model (lower accuracy), reloaded the general model, then `_save_setup_model_to_db()` saved the general model as the setup model
    - **Fix 1**: Added `skip_save=True` parameter to `train_from_features()` — setup training skips GBM's internal save
    - **Fix 2**: Setup model protection in `train_setup_model()` now compares against existing setup model of SAME TYPE (not the general model)
    - **Fix 3**: `predict_for_setup()` now extracts both base features AND setup-specific features before prediction (previously only extracted base features, leaving setup features as zeros)
    - **Verified**: MOMENTUM=47.3%, BREAKOUT=48.4% (each has its own accuracy, general model untouched at 76.8%)

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

## Upcoming Tasks
- **(P1) Backtesting Workflow Automation** — Auto-run backtests when a new model is trained

## Future/Backlog
- (P3) Auto-Optimize AI Settings — Sweep confidence thresholds & lookback windows
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations side-by-side
- (P2) Improve setup model accuracy — current models at ~47-48%, may need better pattern detection, more data, or feature engineering

## Known Minor Issues
- None

## Testing
- `/app/test_reports/iteration_107.json` (General Training Job Queue, 20/20 passed)
