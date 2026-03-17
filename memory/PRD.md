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
- ✅ ~29,000 data fetch requests queued (10,473 completed = 36%)
- ✅ Data Coverage Dashboard verified working
- ✅ Backend returns correct data (12,198 symbols in ADV cache)
- ✅ **FIX: Heartbeat tolerance increased from 30s to 90s** (fixes fluctuating "All Systems Offline" status)
- ✅ **SIMPLIFIED PRIORITY COLLECTION SYSTEM** (March 17, 2026) - Replaces confusing mode toggle

### Phase 5: Priority-Based Data Collection ✅ (SIMPLIFIED)
Per user feedback, the explicit "Trading vs Collection Mode" toggle was replaced with a simpler priority-based system:

**How It Works:**
1. Script always runs in "trading" mode (live quotes + orders always active)
2. Historical data collection happens passively in background at low priority
3. When user clicks "Fill Gaps" button, `priority_collection` flag is set automatically
4. Priority mode speeds up historical data fetching (more requests, faster polling)
5. Priority mode auto-disables when the queue is empty

**Backend Endpoints:**
- `GET /api/ib/mode` - Returns current mode (always "trading"), priority_collection flag, pending count
- `POST /api/ib/priority-collection/enable` - Enable priority collection
- `POST /api/ib/priority-collection/disable` - Disable priority collection
- `GET /api/ib/priority-collection/status` - Full status with queue stats

**Frontend Changes (NIA.jsx):**
- Removed confusing "Trading/Collection Mode" toggle
- Added simple "Priority Collection" status indicator
- Shows "Normal Trading" (green) or "Priority Collection" (amber)
- "Speed Up" / "Slow Down" button to manually toggle priority
- Fill Gaps button auto-enables priority collection

**Local Script Changes (ib_data_pusher.py):**
- Default mode changed from "auto" to "trading"
- Main `run()` method now includes integrated historical data polling
- Checks for `priority_collection` flag every 30 seconds
- Priority mode: polls every 10s, fetches 10 requests per batch, quote push slowed to 30s
- Normal mode: polls every 60s, fetches 2 requests per batch, quote push at 5s
- Live trading (orders) always works regardless of priority mode

## Recent Changes
### March 17, 2026 - Simplified Priority Collection System (MAJOR)
- **User Feedback**: "Trading vs Collection Mode" toggle was confusing and slow
- **Solution**: Replaced explicit mode toggle with priority-based background collection
- **Key Change**: Script always in trading mode, priority flag speeds up historical data fetch
- **User Experience**: Click "Fill Gaps" → collection speeds up automatically → auto-returns to normal when done
- **Files Modified**:
  - `backend/routers/ib.py` - New priority collection endpoints
  - `backend/routers/ib_collector_router.py` - Fill Gaps now auto-enables priority
  - `frontend/src/components/NIA.jsx` - Removed mode toggle, added priority status
  - `documents/scripts/ib_data_pusher.py` - Integrated historical data polling with priority support

### March 17, 2026 - Connection Status Fix
- **Issue**: System status indicator was fluctuating between "Online" and "Offline" due to tight 30-second heartbeat window
- **Root cause**: Network latency to MongoDB Atlas + rate limiting + concurrent operations caused heartbeat delays
- **Fix**: Increased heartbeat tolerance from 30 seconds to 90 seconds in `/app/backend/routers/ib.py`
- **Files modified**: `backend/routers/ib.py` (functions: `is_pusher_connected`, `get_connection_status`, `get_pushed_ib_data`)

## Next Tasks
1. ⏳ **User Action**: Download updated `ib_data_pusher.py` to your local machine
2. ⏳ **User Action**: Run `StartTrading.bat` (or `python ib_data_pusher.py --cloud-url=... --mode=trading`)
3. ⏳ **User Action**: Click "Fill Gaps" in NIA dashboard to start prioritized collection
4. Monitor collection progress in "Progress" tab - watch pending count decrease
5. After collection completes (~18,611 pending requests), verify auto-training triggers

## Backlog
- (P1) Deep Scanner Overhaul - alternative data sources
- (P2) Advanced Model Training Dashboard
- (P2) Portfolio Analytics Dashboard
- (P3) Trade Journal & Alerts
- (P2) Cloud API Stability - investigate timeouts (server-side root cause)
