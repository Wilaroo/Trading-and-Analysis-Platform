# TradeCommand PRD

## Original Problem Statement
The user wants to evolve their AI trading bot, "SentCom," into a self-improving system by hardening the data pipeline, creating automation, and improving the UI. The goal is to train AI models on a massive 39M+ bar historical dataset collected from Interactive Brokers.

## Core Requirements
1. **Robust Data Pipeline**: Collect historical data for all required timeframes for high-volume stocks
2. **Autonomous Learning Loop**: Implement automation for data collection and model training
3. **Comprehensive UI**: Consolidate all AI, learning, and data management features into an intuitive dashboard
4. **Multi-Timeframe AI Training**: Train specialized models for different trading styles

## User Personas
- Active day trader running scalp and swing strategies
- Uses 77 custom trading setups across multiple timeframes
- Runs IB Gateway locally on Windows machine
- MongoDB Atlas for cloud data storage

## Architecture
```
/app
├── backend/
│   ├── services/
│   │   ├── ai_modules/
│   │   │   ├── timeseries_service.py    # Multi-timeframe training
│   │   │   ├── timeseries_gbm.py        # LightGBM model
│   │   │   └── trade_consultation.py    # AI consultation for trades
│   │   ├── trading_bot_service.py       # Main trading bot
│   │   ├── enhanced_scanner.py          # Alert scanner
│   │   └── medium_learning/
│   │       └── calibration_service.py   # Scanner calibration
│   └── routers/
│       ├── ai_modules.py                # AI training endpoints
│       └── learning_connectors_router.py # Calibration endpoints
├── frontend/
│   └── src/components/
│       ├── UnifiedAITraining.jsx        # NEW: Merged training panel
│       └── NIA.jsx                      # Neural Intelligence Agency
└── documents/
    └── scripts/
        └── ib_historical_collector_v3.py # Optimized collector
```

## What's Been Implemented

### March 21, 2026 - Unified AI Training System
- [x] Merged TrainAllPanel + MultiTimeframeTraining into UnifiedAITraining
- [x] Multi-timeframe model training (7 timeframes: 1min, 5min, 15min, 30min, 1hr, daily, weekly)
- [x] Quick Train: Daily model + calibration workflow
- [x] Full Train: All 7 models sequentially
- [x] Training history tracking with accuracy trends
- [x] Calibration integration (scanner thresholds, module weights)
- [x] Removed artificial 100 symbol limit (now uses all ~9,400 symbols)

### March 20, 2026 - Data Collection Complete
- [x] 39M+ bars collected across all timeframes
- [x] Optimized v3 collector script
- [x] Parallel collection with unique IB client IDs

### March 19, 2026
- [x] Comprehensive User Guide (HTML)
- [x] Optimized data collection pipeline

### March 18, 2026
- [x] Startup Status Dashboard

## Prioritized Backlog

### P0 - High Priority
- [ ] **Run Full AI Model Training** - User needs to run training on local machine
- [ ] **Set Up Nightly Incremental Collection** - Grow intraday data over time

### P1 - Medium Priority
- [ ] **Fix `fill-gaps` Endpoint** - Hangs server under load, needs refactoring
- [ ] **Complete Backend Router Refactoring** - Activate modular routers
- [ ] **Complete Frontend Hook Refactoring** - Integrate hooks into SentCom.jsx

### P2 - Lower Priority
- [ ] **Setup-Specific AI Models** - Train models on 77 specific trading setups
- [ ] **Deep Scanner Overhaul** - Integrate alternative data sources
- [ ] **Model Comparison Dashboard** - Track accuracy across timeframes over time

## Data Schema

### ib_historical_data (39M+ docs)
```json
{
  "symbol": "NVDA",
  "bar_size": "5 mins",
  "date": "2026-03-20T10:30:00-04:00",
  "open": 123.45,
  "high": 124.00,
  "low": 123.00,
  "close": 123.80,
  "volume": 15000,
  "collected_at": "2026-03-20T16:00:00Z"
}
```

### model_training_history (NEW)
```json
{
  "timestamp": "2026-03-21T10:00:00Z",
  "bar_size": "1 day",
  "model_name": "direction_predictor_daily",
  "accuracy": 0.567,
  "training_samples": 6400000,
  "symbols_used": 9399
}
```

## API Endpoints

### AI Training
- `POST /api/ai-modules/timeseries/train` - Train single timeframe
- `POST /api/ai-modules/timeseries/train-all` - Train all 7 timeframes
- `GET /api/ai-modules/timeseries/available-data` - Data per timeframe
- `GET /api/ai-modules/timeseries/training-history` - Training history

### Calibration
- `POST /api/learning-connectors/sync/run-all-calibrations` - Run all calibrations
- `GET /api/medium-learning/calibration/config` - Current thresholds

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- MongoDB Atlas
- Ollama Pro (local LLM)
- LightGBM (ML)
- ChromaDB (vector store)
