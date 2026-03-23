# SentCom AI Trading Bot - Product Requirements Document

## Original Problem Statement
Build a self-improving AI trading bot "SentCom" by hardening the data pipeline, creating automation, and improving the UI. After completing massive historical data collection (39M bars), the primary goal shifted to training AI models on this new dataset, integrating models into the bot's decision-making, and streamlining the local development/training environment.

## Core Requirements
1. **Robust Data Pipeline**: Collect historical data for all required timeframes ✅ COMPLETED
2. **Autonomous Learning Loop**: Implement automation for data collection and model training (IN PROGRESS)
3. **Comprehensive UI**: Consolidate all AI, learning, and data management features
4. **Startup Status Dashboard**: Correctly reflect backend service status
5. **Comprehensive User Guide**: Create detailed, visual, downloadable guide ✅ COMPLETED

## Architecture
```
/app
├── backend/
│   ├── routers/ai_modules.py       # AI endpoints (predictions, training)
│   ├── scripts/setup_mongodb_indexes.py
│   └── services/ai_modules/
│       ├── timeseries_service.py   # Training orchestration
│       └── timeseries_gbm.py       # LightGBM model (FIXED: model loading)
├── documents/
│   └── AI_TRAINING_GUIDE.md
└── memory/PRD.md
```

## What's Been Implemented

### March 23, 2026
- **FIXED**: Prediction API 404 errors - Enhanced `_load_model()` with fallback chain
  - Now loads `direction_predictor_daily` when default model not found
  - Verified working: `/api/ai-modules/timeseries/forecast` returns real predictions
  
### March 22-23, 2026 (Previous Session)
- Fixed "Full Universe" backend crash for larger timeframes
- Fixed MongoDB "duplicate key" error on model saving
- Trained models: "1 day" (53.7% accuracy), "1 hour" (55.4% accuracy)
- Created MongoDB index script for faster data loading
- Created AI Training Guide (`/app/documents/AI_TRAINING_GUIDE.md`)

## Trained Models
| Timeframe | Model Name | Accuracy | Training Samples |
|-----------|------------|----------|-----------------|
| 1 day | direction_predictor_daily | 53.7% | 2,796,708 |
| 1 hour | direction_predictor_1hour | 55.4% | 3,385,592 |

## Outstanding Issues

### P0 - Critical
1. **Intraday Training Crashes**: Memory overload on 5-min/15-min timeframes
   - Need smaller batch sizes for intraday
   - Consider one-at-a-time training approach

### P1 - High
2. **Frontend Polling Overload**: `ERR_INSUFFICIENT_RESOURCES`
   - Excessive API calls flooding browser/backend
   - Need to slow/pause polling during training

### P2 - Medium
3. Implement Backtesting Workflow Automation
4. Implement Best Model Protection (save only if accuracy improves)
5. Enable GPU for LightGBM

## Future Roadmap
- Setup-Specific AI Models (77 trading setups)
- Fix `fill-gaps` endpoint
- Complete Backend Router Refactoring

## Key API Endpoints
- `POST /api/ai-modules/timeseries/forecast` - Get prediction for symbol
- `GET /api/ai-modules/timeseries/status` - Model status
- `GET /api/ai-modules/timeseries/training-history` - Training history
- `POST /api/ai-modules/timeseries/train-full-universe-all` - Train all timeframes

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- Ollama Pro
- MongoDB Atlas (84% disk usage - monitor)
- PyTorch (with CUDA)
- LightGBM
- ChromaDB
