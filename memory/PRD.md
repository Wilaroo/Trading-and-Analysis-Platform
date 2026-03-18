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

## Completed Work (March 18, 2026)

### Local Environment Setup ✅
- Created `TradeCommand_Ultimate.bat` - one-click startup script
- Auto git pull on startup
- Sequential IB Gateway login with auto-credentials
- Starts: Backend, Frontend, Ollama, IB Data Pusher
- GPU detection and CUDA configuration

### ML/GPU Setup ✅
- Installed PyTorch with CUDA 12.8 support
- Installed: lightgbm, transformers, sentence-transformers, chromadb
- RTX 5060 Ti detected and ready for training
- Made ML dependencies optional for production deployment

### Production Deployment Fix ✅
- Removed heavy ML dependencies from requirements.txt for production
- Made ChromaDB optional with graceful degradation
- Production can now deploy without crashing

### Desktop Shortcuts Created
- `StartLocal.bat` → Calls TradeCommand_Ultimate.bat
- `StartHistoricalCollector.bat` → Historical data collection (client 11)

---

## In Progress / Backlog

### P0 - High Priority
- [ ] **Startup Status Dashboard** - Visual indicator showing all services initializing
  - Shows: Backend, MongoDB, IB Gateway, Data Pusher, Ollama, Trading Bot, WebSocket
  - Auto-dismisses when ready
  - Prevents user interaction during startup

### P1 - Medium Priority
- [ ] Complete backend router refactoring (ib_modules not yet activated)
- [ ] Complete frontend hook refactoring (useSentCom.js not yet integrated)
- [ ] Full AI model training run with GPU

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
- `/app/backend/services/ai_modules/__init__.py` - ML optional loading
- `/app/backend/services/rag/vector_store.py` - ChromaDB optional

### Frontend
- `/app/frontend/src/components/SentCom.jsx` - Main trading UI
- `/app/frontend/src/components/NIA.jsx` - AI training UI
- `/app/frontend/src/hooks/useSentCom.js` - Extracted hooks (not yet integrated)

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
