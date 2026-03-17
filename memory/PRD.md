# SentCom AI Trading Bot - Product Requirements Document

## Original Problem Statement
Build a self-improving AI trading bot system "SentCom" with:
1. Robust data pipeline for historical data collection
2. Autonomous learning loop (nightly/weekend automation)
3. Comprehensive UI for AI, learning, and data management
4. Data coverage dashboard for tracking collected data
5. High-quality live scanner with AI predictions

## Core Architecture
```
/app
├── backend/          # FastAPI backend
│   ├── routers/      # API endpoints
│   ├── services/     # Business logic
│   ├── models/       # Data models
│   └── agents/       # AI agents
├── frontend/         # React frontend
│   ├── src/
│   │   ├── components/   # UI components
│   │   ├── pages/        # Page components
│   │   ├── hooks/        # Custom hooks
│   │   └── contexts/     # React contexts
└── memory/           # Documentation
```

## Key Features Implemented

### Phase 1: Data Pipeline ✅
- Historical data collection from IB Gateway
- Multi-timeframe support (1 min, 5 mins, 15 mins, 30 mins, 1 hour, 1 day, 1 week)
- ADV-based tier filtering (Intraday, Swing, Investment)
- "Quick Fill" feature for collecting only missing data

### Phase 2: Training Automation ✅
- Auto-train toggle after data collection
- Training status endpoint
- Training job tracking in MongoDB

### Phase 3: Scanner AI Integration ✅
- Live scanner with AI predictions
- Confidence score and predicted move display
- Filtering by AI confidence

### Phase 4: Data Coverage Dashboard ✅
- Per-tier coverage visualization
- Per-timeframe coverage statistics
- Data gaps identification
- Backend fix for correct MongoDB collection names

## Key Endpoints
- `GET /api/ib-collector/data-coverage` - Data coverage statistics
- `POST /api/ib-collector/fill-gaps` - Collect missing data
- `GET /api/training/status` - Training job status
- `GET /api/scanner/alerts` - Live scanner alerts with AI

## Key Components
- `NIA.jsx` - Neural Intelligence Agency dashboard
- `MarketScannerPanel.jsx` - Live scanner UI
- `AdvancedBacktestPanel.jsx` - Backtesting interface

## Database Collections
- `ib_historical_data` - Time-series bar data
- `symbol_adv_cache` - Average daily volume cache
- `training_jobs` - Training job metadata
- `app_settings` - Application settings

## Current Status (March 17, 2026)
- ✅ Database migrated to MongoDB Atlas (persistent storage)
- ✅ ~21,000 data fetch requests audited and queued
- ✅ Data Coverage Dashboard verified working
- ✅ Backend returns correct data (12,198 symbols in ADV cache)
- ✅ **FIX: Heartbeat tolerance increased from 30s to 90s** (fixes fluctuating "All Systems Offline" status)

## Recent Changes
### March 17, 2026 - Connection Status Fix
- **Issue**: System status indicator was fluctuating between "Online" and "Offline" due to tight 30-second heartbeat window
- **Root cause**: Network latency to MongoDB Atlas + rate limiting + concurrent operations caused heartbeat delays
- **Fix**: Increased heartbeat tolerance from 30 seconds to 90 seconds in `/app/backend/routers/ib.py`
- **Files modified**: `backend/routers/ib.py` (functions: `is_pusher_connected`, `get_connection_status`, `get_pushed_ib_data`)

## Next Tasks
1. ⏳ User: Restart `StartTrading.bat` and verify stable connection status
2. Monitor large-scale data collection (~21,000 requests)
3. Verify auto-training triggers after data collection
4. Test AI-enhanced scanner
5. Monitor SentCom bot

## Backlog
- (P1) Deep Scanner Overhaul - alternative data sources
- (P2) Advanced Model Training Dashboard
- (P2) Portfolio Analytics Dashboard
- (P3) Trade Journal & Alerts
