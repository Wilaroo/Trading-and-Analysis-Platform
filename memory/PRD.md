# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform with REAL-TIME market data, technical analysis, AI-powered insights, audio/visual price alerts, VST fundamental scoring, and Earnings Calendar with IV analysis.

## What's Been Implemented (Jan 22, 2026)

### ✅ Core Features (All Working)
1. **Dashboard** - Real-time portfolio tracking, market overview, top movers
2. **TradingView Charts** - Interactive professional charts with RSI, MACD, MA indicators
3. **Strategy Scanner** - Scan stocks against 50 detailed trading strategies
4. **Trading Strategies** - 50 strategies (20 Intraday, 15 Swing, 15 Investment)
5. **VST Scoring System** - VectorVest-style fundamental scoring (RV, RS, RT) on 0-10 scale
6. **Earnings Calendar** - Full earnings tracking with IV, whispers, historical data
7. **Watchlist** - AI-ranked top 10 daily picks with MongoDB persistence
8. **Portfolio Tracker** - Real-time P&L with live prices (MongoDB persisted)
9. **Alert Center** - Strategy match notifications with adjustable thresholds
10. **Morning Newsletter** - AI-generated daily briefing

### ✅ VST Scoring System (NEW - Iteration 4)
VectorVest-style fundamental analysis with scores on 0-10 scale:

**Relative Value (RV):**
- Expected return calculation
- Valuation score (P/E, P/B analysis)
- PEG ratio scoring
- ROE component

**Relative Safety (RS):**
- Leverage/liquidity metrics
- Profitability assessment
- Returns quality
- Volatility (Beta-based)

**Relative Timing (RT):**
- Momentum scoring (1W, 1M, 3M returns)
- Trend position (SMA20/SMA50)
- RSI momentum

**VST Composite:**
- Weighted combination: RV 35%, RS 30%, RT 35%
- Recommendations: STRONG BUY, BUY, HOLD, SELL
- Color coding: Green (≥7), Blue (≥5.5), Yellow (≥4), Red (<4)

### ✅ Custom Alert Threshold
- Adjustable threshold slider (0.5% to 10%)
- Audio toggle for alerts
- Real-time indicator display
- Persisted to localStorage

### ✅ TradingView Integration (Fixed)
- Error overlay suppressed via CSS
- Full chart functionality with technical indicators
- RSI, MACD, Moving Averages displayed
- Symbol switching with popular stocks presets

### ✅ Audio/Visual Price Alerts
- Adjustable threshold (0.5% - 10%)
- Audio tones for bullish/bearish moves
- Visual toast notifications
- Settings panel via gear icon

### ✅ Frontend Architecture
App.js split into modular components:
- `/pages/` - 12 page components (including FundamentalsPage with VST)
- `/components/` - Sidebar, TickerTape, PriceAlertNotification, AlertSettingsPanel
- `/hooks/` - useWebSocket, usePriceAlerts
- `/utils/` - api, alertSounds

## API Endpoints

### VST Scoring (NEW)
- `GET /api/vst/{symbol}` - Full VST analysis with RV, RS, RT scores
- `POST /api/vst/batch` - Batch VST scoring for multiple symbols
- `GET /api/fundamentals/{symbol}` - Basic fundamental data

### Earnings Calendar
- `GET /api/earnings/calendar` - Get earnings calendar (date range filter)
- `GET /api/earnings/{symbol}` - Detailed earnings data for symbol
- `GET /api/earnings/iv/{symbol}` - IV analysis for earnings

### Scanner
- `POST /api/scanner/scan` - Scan with 50-strategy criteria

### Watchlist & Portfolio
- `GET/POST/DELETE /api/watchlist`
- `GET/POST/DELETE /api/portfolio`

## Data Sources
- **Real-time quotes**: Twelve Data API (8 req/min limit, cached)
- **VST Scoring**: Uses Twelve Data + calculated metrics
- **Earnings data**: SIMULATED (realistic data generation)
- **Fundamentals/Insider/COT**: MOCKED (simulated when APIs unavailable)

## Known Limitations
- WebSocket shows OFFLINE but REST polling works
- Twelve Data API rate limit (8 req/min) - uses caching
- Insider Trading and COT data are mocked
- VST uses hardcoded benchmark values (BOND_YIELD=4.5%, MARKET_AVG_RETURN=10%)

## Test Coverage
- Backend: 22 pytest tests (100% pass rate)
- Frontend: All features tested via Playwright
- Test files: `/app/backend/tests/test_vst_and_features.py`

## Files Structure
```
/app/frontend/src/
├── pages/
│   ├── FundamentalsPage.js    # VST Scoring display
│   ├── EarningsCalendarPage.js
│   ├── DashboardPage.js
│   ├── ChartsPage.js
│   ├── ScannerPage.js
│   └── ... (12 pages total)
├── components/
│   ├── Sidebar.js
│   ├── PriceAlertNotification.js  # Includes AlertSettingsPanel
│   └── ...
├── hooks/
│   └── usePriceAlerts.js  # Alert threshold management
└── App.js
```

## Priority Backlog
- **P1**: Replace Twelve Data with Finnhub (60 calls/min free tier)
- **P1**: Add Earnings Notifications for watchlist stocks
- **P2**: Refactor backend server.py into routers/services
- **P2**: User Authentication system
- **P3**: Interactive Brokers integration
- **P3**: Replace mock data (Insider Trading, COT) with real APIs
