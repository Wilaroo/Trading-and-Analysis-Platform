# TradeCommand PRD - Product Requirements Document

## Original Problem Statement
Build a self-improving AI trading bot ("SentCom") with:
- Robust data pipeline for multiple timeframes
- Autonomous learning loop (nightly/weekend automation)
- Comprehensive UI consolidating all AI/learning features
- High-quality live scanner with actionable alerts
- Persistent MongoDB Atlas storage

## Current Architecture

### Environment Strategy
- **Local**: Full trading with IB Gateway, ML training (GPU), all features
- **Preview** (sentcom-evolve.preview.emergentagent.com): Development/testing
- **Production** (tradecommand.trade): Lightweight deployment (ML disabled)

### Tech Stack
- Backend: FastAPI (Python 3.13)
- Frontend: React
- Database: MongoDB Atlas
- ML: LightGBM, PyTorch (CUDA 12.8), ChromaDB
- AI: Ollama (llama3:8b local), gpt-oss cloud fallback
- Broker: Interactive Brokers Gateway

### User Hardware
- RAM: 16GB
- GPU: NVIDIA GeForce RTX 5060 Ti
- Local ML: Fully configured with CUDA support

---

## Completed Work

### March 19, 2026 ✅
- **Comprehensive User Guide Created** - `TradeCommand_Complete_Guide.html`
  - Full visual guide covering all SentCom features
  - Sections: Startup, Architecture, Trading Day, AI Decision Making, Trade Execution, Data Collection, Learning Systems, Chat Examples, End of Day, Weekend Automation
  - Located at `/app/frontend/public/docs/TradeCommand_Complete_Guide.html`
  - Downloadable/printable with styled dark theme

- **Optimized Historical Data Collection Pipeline**
  - Implemented "smart-batch-claim" API endpoint (`/api/ib-collector/smart-batch-claim`)
  - Added intelligent skip logic to avoid re-fetching complete data
  - ~3x performance improvement in collection throughput
  - Updated `ib_historical_collector.py` with new skip feature

- **Enhanced StartHistoricalCollector.bat (v3.0)**
  - Robust auto-login with VBScript-based IB Gateway credentials
  - Backend health checks before starting collection
  - Client ID conflict management
  - Full error handling and recovery

### March 18, 2026 ✅
- **Local Environment Setup**
  - Created `TradeCommand_Ultimate.bat` - one-click startup script
  - Auto git pull on startup
  - Sequential IB Gateway login with auto-credentials
  - Starts: Backend, Frontend, Ollama, IB Data Pusher
  - GPU detection and CUDA configuration

- **ML/GPU Setup**
  - Installed PyTorch with CUDA 12.8 support
  - Installed: lightgbm, transformers, sentence-transformers, chromadb
  - RTX 5060 Ti detected and ready for training
  - Made ML dependencies optional for production deployment

- **Production Deployment Fix**
  - Removed heavy ML dependencies from requirements.txt for production
  - Made ChromaDB optional with graceful degradation
  - Production can now deploy without crashing

- **Desktop Shortcuts Created**
  - `StartLocal.bat` → Calls TradeCommand_Ultimate.bat
  - `StartHistoricalCollector.bat` → Historical data collection (client 11)

---

## In Progress / Backlog

### P0 - High Priority
- [x] **Startup Status Dashboard** ✅ COMPLETED (March 18, 2026)
- [x] **Comprehensive User Guide** ✅ COMPLETED (March 19, 2026)
- [x] **Optimized Data Collection Pipeline** ✅ COMPLETED (March 19, 2026)
- [x] **Complete Historical Data Collection** ✅ COMPLETED (March 20, 2026) - 39M+ bars collected
- [x] **Install Missing ML Dependencies** ✅ COMPLETED - lightgbm, chromadb installed
- [x] **Multi-Timeframe AI Training System** ✅ COMPLETED (March 21, 2026)
  - Backend: New endpoints for training models per timeframe
    - `POST /api/ai-modules/timeseries/train` - Train single timeframe model
    - `POST /api/ai-modules/timeseries/train-all` - Train all 7 timeframe models
    - `GET /api/ai-modules/timeseries/available-data` - View data by timeframe
    - `GET /api/ai-modules/timeseries/training-status` - Monitor training progress
  - Frontend: New MultiTimeframeTraining component in NIA
    - Visual cards for each timeframe showing bar count and symbol count
    - Individual "Train Model" buttons per timeframe
    - "Train All" button for sequential training of all models
  - 7 specialized models for different trading styles:
    - 1 min (5M bars) - Ultra-short scalping
    - 5 mins (8.5M bars) - Intraday scalping  
    - 15 mins (6.1M bars) - Short-term swings
    - 30 mins (4M bars) - Intraday swings
    - 1 hour (7.6M bars) - Swing trading
    - 1 day (7M bars) - Position trades
    - 1 week (690K bars) - Long-term trends
- [ ] **Run Full AI Model Training** - NEXT: User needs to run training on local machine

### P1 - Medium Priority
- [ ] Fix `/api/ib-collector/fill-gaps` endpoint (hangs under load, needs non-blocking refactor)
- [ ] Complete backend router refactoring (ib_modules not yet activated)
- [ ] Complete frontend hook refactoring (useSentCom.js not yet integrated)
- [ ] Re-enable trading bot & schedulers after data collection

### P2 - Lower Priority
- [ ] Refactor NIA.jsx and server.py
- [ ] Setup-specific AI models (77 trading setups)
- [ ] Deep scanner overhaul
- [ ] Portfolio analytics dashboard
- [ ] Advanced model training dashboard

---

## Key Files Reference

### Startup Scripts
- `/app/documents/TradeCommand_Ultimate.bat` - Main local startup
- `/app/documents/scripts/ib_historical_collector.py` - Historical data (client 11)
- `/app/documents/scripts/ib_data_pusher.py` - Live data (client 10)

### Backend
- `/app/backend/server.py` - Main server
- `/app/backend/routers/ib.py` - IB endpoints including smart-batch-claim
- `/app/backend/services/ai_modules/__init__.py` - ML optional loading
- `/app/backend/services/rag/vector_store.py` - ChromaDB optional

### Frontend
- `/app/frontend/src/components/SentCom.jsx` - Main trading UI
- `/app/frontend/src/components/NIA.jsx` - AI training UI
- `/app/frontend/src/hooks/useSentCom.js` - Extracted hooks (not yet integrated)
- `/app/frontend/public/docs/TradeCommand_Complete_Guide.html` - User Guide

---

## Configuration

### IB Gateway
- Path: `C:\Jts\ibgateway\1037\ibgateway.exe`
- Port: 4002
- Client IDs: 10 (data pusher), 11 (historical collector)

### Local URLs
- Backend: http://localhost:8001
- Frontend: http://localhost:3000
- Ollama: http://localhost:11434

### User Repo Path
- `C:\Users\13174\Trading-and-Analysis-Platform`

---

## Notes
- Ollama falls back from gpt-oss:120b-cloud to llama3:8b when cloud unavailable
- `emergentintegrations` not installed locally (fine - uses Ollama directly)
- Production deployment limited to non-ML features due to resource constraints
