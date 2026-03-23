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
│       ├── timeseries_service.py   # Training orchestration (memory-safe settings added)
│       └── timeseries_gbm.py       # LightGBM model (model loading fixed)
├── frontend/src/
│   ├── contexts/
│   │   ├── DataCacheContext.jsx
│   │   └── TrainingModeContext.jsx # NEW: Centralized training mode control
│   ├── components/
│   │   ├── UnifiedAITraining.jsx   # Updated with training mode notifications
│   │   ├── SimulatorControl.jsx    # Updated with training-aware polling
│   │   ├── NIA.jsx                 # Updated with training-aware polling
│   │   └── TrainingModeIndicator.jsx # NEW: Visual training indicator
│   └── pages/
│       └── TradeOpportunitiesPage.js # Updated with training-aware polling
├── documents/
│   └── AI_TRAINING_GUIDE.md
└── memory/PRD.md
```

## What's Been Implemented

### March 23, 2026 (Current Session)

#### Fix 1: Prediction API 404 Errors - FIXED
- Enhanced `_load_model()` in `timeseries_gbm.py` with fallback chain
- Now auto-loads `direction_predictor_daily` when default model not found
- Verified: `/api/ai-modules/timeseries/forecast` returns real predictions

#### Fix 2: Frontend Polling Overload - FIXED
- Created `TrainingModeContext` to centrally control polling during training
- When training is active, polling intervals are automatically slowed 10x
- Updated components: `UnifiedAITraining`, `SimulatorControl`, `TradeOpportunitiesPage`, `NIA`
- Added `TrainingModeIndicator` component for visual feedback

#### Fix 3: Intraday Training Memory Safety - IMPLEMENTED
- Added `TIMEFRAME_SETTINGS` with per-timeframe batch sizes:
  - "1 min": batch_size=10, max_bars=200
  - "5 mins": batch_size=15, max_bars=300
  - "15 mins": batch_size=20, max_bars=400
  - "30 mins": batch_size=25, max_bars=500
  - "1 hour": batch_size=50, max_bars=1000
  - "1 day": batch_size=100, max_bars=2000
- Added memory monitoring with 3GB emergency stop
- Added longer pauses (10s) between intraday timeframes

### Previous Session (March 22-23, 2026)
- Fixed "Full Universe" backend crash for larger timeframes
- Fixed MongoDB "duplicate key" error on model saving
- Trained models: "1 day" (53.7% accuracy), "1 hour" (55.4% accuracy)
- Created MongoDB index script for faster data loading
- Created AI Training Guide

## Trained Models
| Timeframe | Model Name | Accuracy | Training Samples |
|-----------|------------|----------|-----------------|
| 1 day | direction_predictor_daily | 53.7% | 2,796,708 |
| 1 hour | direction_predictor_1hour | 55.4% | 3,385,592 |

## Outstanding Issues

### P2 - Medium Priority
1. **Implement Backtesting Workflow Automation** - Create automated backtesting scripts
2. **Enable Best Model Protection** - Save only if accuracy improves
3. **Enable GPU for LightGBM** - Re-install with GPU support

## Future Roadmap
- Setup-Specific AI Models (77 trading setups)
- Fix `fill-gaps` endpoint
- Complete Backend Router Refactoring

## Key API Endpoints
- `POST /api/ai-modules/timeseries/forecast` - Get prediction for symbol ✅ WORKING
- `GET /api/ai-modules/timeseries/status` - Model status ✅ WORKING
- `GET /api/ai-modules/timeseries/training-history` - Training history ✅ WORKING
- `POST /api/ai-modules/timeseries/train-full-universe-all` - Train all timeframes ✅ MEMORY-OPTIMIZED

## Files Modified This Session
- `/app/backend/services/ai_modules/timeseries_gbm.py` - Fixed model loading
- `/app/backend/services/ai_modules/timeseries_service.py` - Added memory-safe settings
- `/app/frontend/src/contexts/TrainingModeContext.jsx` - NEW
- `/app/frontend/src/contexts/index.js` - Updated exports
- `/app/frontend/src/components/TrainingModeIndicator.jsx` - NEW
- `/app/frontend/src/components/UnifiedAITraining.jsx` - Training mode integration
- `/app/frontend/src/components/SimulatorControl.jsx` - Training-aware polling
- `/app/frontend/src/components/NIA.jsx` - Training-aware polling
- `/app/frontend/src/pages/TradeOpportunitiesPage.js` - Training-aware polling
- `/app/frontend/src/App.js` - Added TrainingModeProvider and indicator

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- Ollama Pro
- MongoDB Atlas (84% disk usage - monitor)
- PyTorch (with CUDA)
- LightGBM
- ChromaDB
