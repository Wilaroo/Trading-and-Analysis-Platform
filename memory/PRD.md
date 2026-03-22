# SentCom AI Trading Bot - Product Requirements Document

## Original Problem Statement
The user wants to evolve their AI trading bot, "SentCom," into a self-improving system by hardening the data pipeline, creating automation, and improving the UI. After completing a massive historical data collection (39M bars), the primary goal has shifted to training the AI models on this new dataset, integrating the models into the bot's decision-making, and streamlining the local development/training environment for stability and performance.

## Core Requirements

### 1. Robust Data Pipeline ✅ COMPLETED
- Collect historical data for all required timeframes
- 39M bars collected across 7 timeframes

### 2. Autonomous Learning Loop 🔄 IN PROGRESS
- Implement automation for data collection and model training
- **Current Blocker**: Full Universe training crashes backend

### 3. Comprehensive UI 🔄 IN PROGRESS
- Consolidate all AI, learning, and data management features into an intuitive dashboard
- localStorage caching for data persistence

### 4. Startup Status Dashboard ✅ PARTIALLY COMPLETE
- UI correctly reflects the status of all backend services

### 5. Comprehensive User Guide ✅ COMPLETED
- Detailed, visual, and downloadable guide created

---

## Current Issues

### P0 - Critical
- **Full Universe Training Crashes Backend**: When triggering "Full Universe" training, the backend process crashes silently after the API returns 200 OK. The background task fails to complete.
  - **Status**: DEBUGGING IN PROGRESS
  - **Latest Changes**: Added aggressive logging, reduced batch sizes (50 symbols, 1000 bars), added memory safeguards
  - **Next Step**: User to test and report last log message before crash

### P1 - High Priority
- **Full Train Function Broken**: Stops after completing just one model instead of all 7 timeframes
  - **Status**: BLOCKED by P0

---

## Architecture

### Backend Stack
- FastAPI (async)
- MongoDB Atlas
- LightGBM for ML
- PyTorch with CUDA
- ChromaDB

### Frontend Stack
- React
- localStorage for state persistence

### Key Files
- `/app/backend/services/ai_modules/timeseries_service.py` - Training logic
- `/app/backend/routers/ai_modules.py` - API endpoints
- `/app/frontend/src/components/UnifiedAITraining.jsx` - Training UI

### Key Endpoints
- `POST /api/ai-modules/timeseries/train` - Single timeframe training
- `POST /api/ai-modules/timeseries/train-all` - All timeframes (sample)
- `POST /api/ai-modules/timeseries/train-full-universe` - Full universe single timeframe
- `POST /api/ai-modules/timeseries/train-full-universe-all` - Full universe all timeframes

---

## Completed Work (This Session)

### Dec 2025
- Added aggressive debugging to Full Universe training
- Reduced default batch sizes for memory safety (100→50 symbols, 2000→1000 bars)
- Added sys.stdout.flush() to all log statements to capture output before crash
- Added MemoryError specific exception handling
- Temporary debug mode: limited to 1 day timeframe and 100 symbols

---

## Upcoming Tasks

### After P0 Fixed
1. **Implement Best Model Protection** - Only save new models if accuracy improves
2. **Set up Automated Data Collection & Retraining** - Schedule incremental updates
3. **Model Comparison Dashboard** - Compare accuracy trends

### Future/Backlog
- Fix `fill-gaps` endpoint hanging issue
- Complete backend router refactoring
- Setup-specific AI models (77 trading setups)
- Deep Scanner overhaul

---

## 3rd Party Integrations
- Interactive Brokers (IB Gateway)
- Ollama Pro
- MongoDB Atlas
- PyTorch (with CUDA)
- LightGBM
- ChromaDB
