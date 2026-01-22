# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform with REAL-TIME market data, technical analysis, AI-powered insights, audio/visual price alerts, VST fundamental scoring, Earnings Calendar with IV analysis, and now **Earnings Notifications** for watchlist stocks.

## What's Been Implemented (Jan 22, 2026 - Session 2)

### ✅ Core Features (All Working)
1. **Dashboard** - Real-time portfolio tracking, market overview, top movers
2. **TradingView Charts** - Interactive professional charts with RSI, MACD, MA indicators
3. **Strategy Scanner** - Scan stocks against 50 detailed trading strategies
4. **Trading Strategies** - 50 strategies (20 Intraday, 15 Swing, 15 Investment)
5. **VST Scoring System** - VectorVest-style fundamental scoring (RV, RS, RT) on 0-10 scale
6. **Earnings Calendar** - Full earnings tracking with IV, whispers, historical data
7. **Earnings Notifications** - **NEW!** Get notified when watchlist stocks have upcoming earnings
8. **Watchlist** - AI-ranked top 10 daily picks with MongoDB persistence
9. **Portfolio Tracker** - Real-time P&L with live prices (MongoDB persisted)
10. **Alert Center** - Strategy match notifications with adjustable thresholds
11. **Morning Newsletter** - AI-generated daily briefing

### ✅ NEW: Finnhub Integration (Session 2)
Upgraded stock data provider with 60 calls/minute (vs 8 for Twelve Data):
- **Primary**: Finnhub API (60 calls/min free tier)
- **Fallback 1**: Twelve Data API (8 calls/min)
- **Fallback 2**: Yahoo Finance
- **Fallback 3**: Simulated data

**StockDataService** (`/app/backend/services/stock_data.py`):
- Unified interface for multiple data providers
- Smart caching (60s for quotes, 1hr for fundamentals)
- Rate limiting protection
- Batch quote fetching with concurrency control

### ✅ NEW: Earnings Notifications (Session 2)
Automatic notifications for watchlist stocks with upcoming earnings:

**Features:**
- Checks watchlist stocks against earnings calendar
- Notifies 7 days before earnings
- Priority levels (high for high IV, medium otherwise)
- Earnings summary cards showing:
  - Watchlist stock count
  - Earnings this week
  - Earnings next week
  - High IV earnings count

**NotificationService** (`/app/backend/services/notifications.py`):
- Automatic earnings notification generation
- Mark read/unread functionality
- Notification cleanup (30 days)
- Price alert notifications

### ✅ NEW: Backend Refactoring (Session 2)
Started modularizing the monolithic `server.py`:

**New Structure:**
```
/app/backend/
├── routers/
│   ├── __init__.py
│   └── notifications.py    # Notifications endpoints
├── services/
│   ├── __init__.py
│   ├── stock_data.py       # Finnhub/TwelveData/Yahoo provider
│   └── notifications.py    # Earnings notifications logic
├── models/                 # (future: Pydantic models)
└── server.py               # Main app (still large, needs more refactoring)
```

### ✅ Alert Center Enhancement (Session 2)
Enhanced `/app/frontend/src/pages/AlertsPage.js`:
- **Tab Navigation**: Strategy Alerts | Earnings Notifications
- **Earnings Summary Cards**: Visual overview of upcoming earnings
- **Check Earnings Button**: Manually trigger earnings notification check
- **Unified notification management**: Mark read, delete, filter

## API Endpoints

### NEW: Notifications API
- `GET /api/notifications` - Get all notifications (with unread_only filter)
- `GET /api/notifications/check-earnings` - Check for new earnings notifications
- `GET /api/notifications/earnings-summary` - Get watchlist earnings summary
- `POST /api/notifications/{key}/read` - Mark notification as read
- `POST /api/notifications/mark-all-read` - Mark all as read
- `DELETE /api/notifications/{key}` - Delete notification
- `DELETE /api/notifications/cleanup/{days}` - Clean old notifications

### VST Scoring
- `GET /api/vst/{symbol}` - Full VST analysis with RV, RS, RT scores
- `POST /api/vst/batch` - Batch VST scoring for multiple symbols

### Stock Quotes (Updated)
- `GET /api/quotes/{symbol}` - Now uses StockDataService with Finnhub priority

### Other Endpoints (unchanged)
- `GET /api/fundamentals/{symbol}` - Basic fundamental data
- `GET /api/earnings/calendar` - Get earnings calendar
- `GET/POST/DELETE /api/watchlist`
- `GET/POST/DELETE /api/portfolio`

## Data Sources
- **Real-time quotes**: Finnhub API (primary, 60 calls/min) → Twelve Data → Yahoo Finance → Simulated
- **VST Scoring**: Uses quote + fundamental data from providers
- **Earnings data**: SIMULATED (realistic data generation)
- **Fundamentals/Insider/COT**: MOCKED (simulated when APIs unavailable)

## Configuration

### Environment Variables (`/app/backend/.env`)
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=tradecommand
FINNHUB_API_KEY=demo          # Get free key at finnhub.io/register
TWELVEDATA_API_KEY=demo
EMERGENT_LLM_KEY=sk-emergent-xxx
```

**To get better data reliability:**
1. Sign up at https://finnhub.io/register
2. Copy your API key from the Dashboard
3. Update FINNHUB_API_KEY in `/app/backend/.env`
4. Restart backend: `sudo supervisorctl restart backend`

## Test Coverage
- Backend: 22 pytest tests (100% pass rate)
- Frontend: All features tested via Playwright
- Test files: `/app/backend/tests/test_vst_and_features.py`

## Files Structure
```
/app/backend/
├── routers/notifications.py      # NEW: Notifications router
├── services/stock_data.py        # NEW: Multi-provider stock service
├── services/notifications.py     # NEW: Notification logic
└── server.py                     # Main app (refactored)

/app/frontend/src/
├── pages/
│   ├── AlertsPage.js            # UPDATED: With earnings notifications
│   ├── FundamentalsPage.js      # VST Scoring display
│   └── ... (12 pages total)
├── components/
│   └── PriceAlertNotification.js  # Alert threshold slider
└── App.js
```

## Known Limitations
- WebSocket shows OFFLINE but REST polling works
- Finnhub free tier has 15-min delay on quotes
- Insider Trading and COT data are mocked
- VST uses hardcoded benchmark values

## Priority Backlog
- **P1**: Get real Finnhub API key for better data (user action needed)
- **P2**: Continue backend refactoring (move more endpoints to routers)
- **P2**: User Authentication system
- **P3**: Interactive Brokers integration
- **P3**: Replace mock data (Insider Trading, COT) with real APIs
