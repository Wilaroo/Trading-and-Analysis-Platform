# SentCom AI Trading Platform - Product Requirements

## Overview
AI-powered trading platform with autonomous learning, backtesting, and market analysis capabilities.

## Architecture
- **Backend**: FastAPI (Python) + MongoDB
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
    - Models stored in `setup_type_models` MongoDB collection

## Key API Endpoints

### Setup-Specific Model Endpoints (ai_modules.py)
- `GET /api/ai-modules/timeseries/setups/status` — Status of all 10 setup models
- `POST /api/ai-modules/timeseries/setups/train` — Train model for specific setup type
- `POST /api/ai-modules/timeseries/setups/train-all` — Train all setup models (background)
- `POST /api/ai-modules/timeseries/setups/predict` — Predict using setup-specific model
- `POST /api/ai-modules/timeseries/stop-training` — Stop any running training

### Other Key Endpoints
- `/api/health` — Health check
- `/api/ai-modules/timeseries/*` — General timeseries AI endpoints
- `/api/backtest/*` — Strategy backtesting
- `/api/dashboard/*` — Dashboard stats

## Database Collections
- `setup_type_models` — Setup-specific AI model storage (NEW)
- `timeseries_models`, `ai_models` — General timeframe model storage
- `ib_historical_data` — Historical price data (39M+ bars)
- `watchlists`, `portfolios`, `alerts` — User data
- `sim_jobs`, `sim_trades`, `sim_decisions` — Simulation data

## Upcoming Tasks
- **(P1) Backtesting Workflow Automation** — Auto-run backtests when a new model is trained
- **(P2) Code Cleanup** — Delete unused historical_simulation_engine.py (still has active references in worker.py, server.py, advanced_backtest_router.py)

## Future/Backlog
- (P3) Auto-Optimize AI Settings — Sweep confidence thresholds & lookback windows
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations side-by-side

## Testing
- Test reports: `/app/test_reports/iteration_105.json` (latest - Setup Models)
- Test reports: `/app/test_reports/iteration_104.json` (Full AI Sim)
- Backend tests: `/app/backend/tests/test_setup_models.py`
