# SentCom AI Trading Bot - Product Requirements Document

## Original Problem Statement
The user wants to evolve their AI trading bot, "SentCom," into a self-improving system by hardening the data pipeline, creating automation, and improving the UI. After completing a massive historical data collection (39M bars), the primary goal has shifted to training the AI models on this new dataset, integrating the models into the bot's decision-making, and streamlining the local development/training environment for stability and performance.

---

## Completed Features

### Phase 1: Data Pipeline ✅ COMPLETED
- Historical data collection for all 7 timeframes
- 39M+ bars collected and stored in MongoDB Atlas
- IB Gateway integration for real-time and historical data

### Phase 2: Full Universe Training ✅ COMPLETED (March 22, 2026)
- **Fixed**: Backend crashing during training (memory management + async)
- **Fixed**: Model save failing (MongoDB model_id unique index issue)
- **Added**: Background task training with progress monitoring
- **Added**: Chunked data loading to prevent memory crashes
- **Added**: Aggressive logging for debugging
- **Created**: Comprehensive training guide (`/documents/AI_TRAINING_GUIDE.md`)

**How to train (PowerShell):**
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/train-full-universe-all" -Method POST -ContentType "application/json" -Body '{"symbol_batch_size": 50, "max_bars_per_symbol": 1000}'
```

**First successful training results:**
- Timeframe: 1 day
- Accuracy: 53.1%
- Training samples: 75,600
- Elapsed time: 29 minutes

### Phase 3: UI Dashboard ✅ PARTIALLY COMPLETE
- localStorage caching for data persistence
- Training status indicators
- Full Universe training button (via PowerShell for now)

### Phase 4: User Guide ✅ COMPLETED
- Comprehensive training guide created
- Troubleshooting section included
- API reference documented

---

## In Progress

### MongoDB Optimization (Ready to Apply)
Added indexes to `data_storage_manager.py`:
```python
IndexModel([("bar_size", ASCENDING), ("symbol", ASCENDING)])  # For training queries
IndexModel([("bar_size", ASCENDING)])  # For getting all symbols by timeframe
```

**User action needed**: Restart backend to apply indexes, OR manually create in MongoDB Compass.

---

## Upcoming Tasks

### P0 - High Priority
1. ✅ **Apply MongoDB indexes** - DONE! Speeds up training significantly
2. 🔄 **Train all 7 timeframes** - IN PROGRESS (1 day ✅, 1 hour ✅, 5 mins 🔄, 4 more queued)
3. **Fix Full Universe button in UI** - Frontend polling overloads browser

### P1 - Medium Priority
1. **Best Model Protection** - Only save new models if accuracy improves
2. **Automated retraining schedule** - Weekly model refresh
3. **Model comparison dashboard** - Track accuracy over time

### P2 - Lower Priority
1. **Enable GPU for LightGBM** - Faster training
2. **Fix `fill-gaps` endpoint** - Currently hangs server

---

## 🗺️ ROADMAP - Major Features

### 🎯 Phase A: Setup-Specific AI Models (HIGH VALUE)
**Goal:** Train 77 specialized models - one for each trading setup

**Why:** A "gap_and_go" model learns different patterns than a "mean_reversion" model. Specialized models = better predictions.

**Implementation Steps:**
1. Add setup tagging to trade/alert collections
2. Create `setup_training_data` collection from backtests
3. Build `/api/ai-modules/timeseries/train-setup` endpoint
4. Update prediction logic to select correct model per setup
5. Train top 10 setups first, then expand to all 77

**Performance Impact:** Minimal - 77 models = ~400MB RAM, <1ms per prediction

**Data Requirements:** 500+ trades per setup (from backtests + real trades)

---

### 📊 Phase B: Automated Backtesting Workflow (HIGH VALUE)
**Goal:** Prove AI adds value with rigorous backtesting

**Workflow:**
```
1. Train AI Models (DONE)
        ↓
2. Baseline Backtest (No AI)
        ↓
3. AI-Enhanced Backtest
        ↓
4. Compare Results
        ↓
5. Optimize Thresholds (52%, 55%, 58%)
        ↓
6. Walk-Forward Validation
        ↓
7. Shadow Mode (Paper Trading)
        ↓
8. Go Live with Confidence
```

**Key Endpoints:**
- `POST /api/simulation/run` - Run full bot simulation
- `POST /api/backtest/walk-forward` - Out-of-sample testing
- `POST /api/backtest/monte-carlo` - Risk analysis
- `GET /api/simulation/compare/{job1}/{job2}` - Compare results

**Automation Script:** Create PowerShell script to run entire workflow automatically

**Metrics to Track:**
- Win rate (baseline vs AI-enhanced)
- Profit factor improvement
- Drawdown reduction
- AI prediction accuracy per setup

---

### 🔄 Phase C: Continuous Learning Pipeline
**Goal:** Keep models fresh with new market data

**Components:**
1. **Weekly Retraining Schedule** - Auto-retrain on Sundays
2. **Best Model Protection** - Only save if accuracy improves
3. **Model Version History** - Track performance over time
4. **Drift Detection** - Alert when model accuracy drops
5. **A/B Testing** - Compare old vs new model in shadow mode

---

### 📈 Phase D: Advanced Analytics Dashboard
**Goal:** Visualize AI performance and trading results

**Features:**
1. Model accuracy trends over time
2. Per-setup performance breakdown
3. Regime-based analysis (RISK_ON vs RISK_OFF)
4. AI decision heatmaps
5. Backtest comparison charts

---

## Architecture

### Tech Stack
- **Backend**: FastAPI (async), Python 3.11+
- **Frontend**: React with localStorage caching
- **Database**: MongoDB Atlas (M20 tier)
- **ML**: LightGBM for gradient boosting
- **GPU**: PyTorch with CUDA (for future use)

### Key Files
| File | Purpose |
|------|---------|
| `backend/services/ai_modules/timeseries_service.py` | Training orchestration |
| `backend/services/ai_modules/timeseries_gbm.py` | LightGBM model wrapper |
| `backend/routers/ai_modules.py` | Training API endpoints |
| `backend/services/data_storage_manager.py` | MongoDB index management |
| `documents/AI_TRAINING_GUIDE.md` | User documentation |

### Training Endpoints
| Endpoint | Description |
|----------|-------------|
| `POST /api/ai-modules/timeseries/train-full-universe-all` | Train all 7 timeframes |
| `POST /api/ai-modules/timeseries/train-full-universe` | Train single timeframe |
| `GET /api/ai-modules/timeseries/training-status` | Check progress |
| `GET /api/ai-modules/timeseries/training-history` | View past runs |

---

## Known Issues

### Resolved This Session
1. ~~Backend crashes during Full Universe training~~ → Fixed with async background tasks + memory management
2. ~~Model save fails with MongoDB error~~ → Fixed by adding `model_id` field

### Remaining
1. **Frontend polling overload** - Too many concurrent requests causes browser `ERR_INSUFFICIENT_RESOURCES`
2. **Training slow without indexes** - 29 min instead of ~5 min
3. **fill-gaps endpoint** - Hangs the server

---

## Configuration

### Default Training Parameters
```json
{
  "symbol_batch_size": 50,
  "max_bars_per_symbol": 1000
}
```

### Supported Timeframes
1. 1 min → `direction_predictor_1min`
2. 5 mins → `direction_predictor_5min`
3. 15 mins → `direction_predictor_15min`
4. 30 mins → `direction_predictor_30min`
5. 1 hour → `direction_predictor_hourly`
6. 1 day → `direction_predictor_daily`
7. 1 week → `direction_predictor_weekly`

---

## 3rd Party Integrations
- Interactive Brokers (IB Gateway) - Live data & execution
- MongoDB Atlas - Data storage
- Ollama Pro - LLM for coaching
- PyTorch with CUDA - Future GPU acceleration
- LightGBM - ML model training
- ChromaDB - RAG knowledge base

---

## Session Log

### March 22-23, 2026
- **Issue**: Full Universe training crashed backend
- **Root cause**: Background task memory allocation + synchronous MongoDB queries blocking event loop + model save failing due to `model_id: null` unique index violation
- **Fix**: 
  1. Added `asyncio.to_thread` for blocking DB queries
  2. Reduced default batch sizes (100→50 symbols, 2000→1000 bars)
  3. Added aggressive try-except with logging
  4. Added `model_id` field to model save
  5. Removed debug limits (100 symbols → ALL symbols)
  6. Enabled all 7 timeframes
- **MongoDB indexes**: Applied successfully, cleaned up null model_ids
- **Training Results** (in progress):
  - 1 day: ✅ 53.7% accuracy
  - 1 hour: ✅ 55.4% accuracy  
  - 5 mins: 🔄 In progress
  - 15 mins, 30 mins, 1 min, 1 week: Queued
- **Documentation Created**:
  - `/documents/AI_TRAINING_GUIDE.md` - Complete training guide
  - `/backend/scripts/setup_mongodb_indexes.py` - Index setup script
- **Roadmap Added**:
  - Phase A: Setup-Specific AI Models (77 models)
  - Phase B: Automated Backtesting Workflow
  - Phase C: Continuous Learning Pipeline
  - Phase D: Advanced Analytics Dashboard

---

## Quick Reference

### Training Commands (PowerShell)
```powershell
# Start full training (all 7 timeframes)
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/train-full-universe-all" -Method POST -ContentType "application/json" -Body '{"symbol_batch_size": 50, "max_bars_per_symbol": 1000}'

# Check training status
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/training-status" | Select-Object -ExpandProperty Content

# View training history
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/training-history?limit=10" | Select-Object -ExpandProperty Content
```

### Backtesting Commands (PowerShell)
```powershell
# Run simulation without AI (baseline)
Invoke-WebRequest -Uri "http://localhost:8001/api/simulation/run" -Method POST -ContentType "application/json" -Body '{"name": "Baseline", "start_date": "2025-06-01", "end_date": "2026-03-01", "use_ai": false}'

# Run simulation with AI
Invoke-WebRequest -Uri "http://localhost:8001/api/simulation/run" -Method POST -ContentType "application/json" -Body '{"name": "With_AI", "start_date": "2025-06-01", "end_date": "2026-03-01", "use_ai": true, "ai_confidence_threshold": 0.55}'

# View simulation results
Invoke-WebRequest -Uri "http://localhost:8001/api/simulation/jobs?limit=5" | Select-Object -ExpandProperty Content
```

---

*Last Updated: March 22, 2026*
