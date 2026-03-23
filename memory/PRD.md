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
1. **Apply MongoDB indexes** - Will speed up training from 29 min to ~5 min
2. **Train all 7 timeframes** - Currently only "1 day" is trained
3. **Fix Full Universe button in UI** - Frontend polling overloads browser

### P1 - Medium Priority
1. **Best Model Protection** - Only save new models if accuracy improves
2. **Automated retraining schedule** - Weekly model refresh
3. **Model comparison dashboard** - Track accuracy over time

### P2 - Lower Priority
1. **Enable GPU for LightGBM** - Faster training
2. **Fix `fill-gaps` endpoint** - Currently hangs server
3. **Setup-specific AI models** - Train on 77 trading setups

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

### March 22, 2026
- **Issue**: Full Universe training crashed backend
- **Root cause**: Background task memory allocation + synchronous MongoDB queries blocking event loop + model save failing due to `model_id: null` unique index violation
- **Fix**: 
  1. Added `asyncio.to_thread` for blocking DB queries
  2. Reduced default batch sizes (100→50 symbols, 2000→1000 bars)
  3. Added aggressive try-except with logging
  4. Added `model_id` field to model save
- **Result**: Training completed successfully with 53.1% accuracy on "1 day" timeframe

---

*Last Updated: March 22, 2026*
