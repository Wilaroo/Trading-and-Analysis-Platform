# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform with REAL-TIME market data, technical analysis, AI-powered insights, audio/visual price alerts, and now **Earnings Calendar** with IV analysis.

## What's Been Implemented (Jan 22, 2026)

### ✅ Core Features (All Working)
1. **Dashboard** - Real-time portfolio tracking, market overview, top movers
2. **TradingView Charts** - Interactive professional charts with RSI, MACD, MA indicators
3. **Strategy Scanner** - Scan stocks against 50 detailed trading strategies
4. **Trading Strategies** - 50 strategies (20 Intraday, 15 Swing, 15 Investment)
5. **Earnings Calendar** - NEW! Full earnings tracking with IV, whispers, historical data
6. **Watchlist** - AI-ranked top 10 daily picks with MongoDB persistence
7. **Portfolio Tracker** - Real-time P&L with live prices (MongoDB persisted)
8. **Alert Center** - Strategy match notifications
9. **Morning Newsletter** - AI-generated daily briefing

### ✅ NEW: Earnings Calendar
Complete earnings tracking system with:

**Calendar Features:**
- Date range navigation (weekly view)
- List view and Calendar view modes
- Filter by symbol
- Quick stats (Total Reports, Before Open, After Close, High IV)

**Earnings Data:**
- Company name and ticker
- Earnings date and time (BMO/AMC)
- Fiscal quarter
- EPS Estimate vs Whisper EPS
- Analyst count and revisions
- Sentiment (Bullish/Bearish/Neutral/Very Bullish/Very Bearish)

**Implied Volatility Analysis:**
- Current IV
- IV Rank and Percentile
- Expected Move (% and $)
- Straddle/Strangle cost
- IV Term Structure chart (7-90 DTE)
- IV Crush expected
- Strategy suggestions (e.g., "IV elevated - consider selling premium")

**Earnings Whispers:**
- Whisper EPS vs Consensus
- Whisper sentiment
- Beat probability
- Confidence level
- Historical beat rate

**Historical Performance:**
- Last 8 quarters of data
- EPS estimates vs actuals
- Revenue estimates vs actuals
- EPS surprise %
- Stock reaction (1-day, 5-day)
- IV before/after earnings
- IV crush %
- Volume vs average

**Statistics:**
- Beat rate
- Average surprise
- Average stock reaction
- Max positive/negative reaction
- Average IV crush

### ✅ Audio/Visual Price Alerts
- Adjustable threshold (0.5% - 10%)
- Audio tones for bullish/bearish moves
- Visual toast notifications
- Settings panel

### ✅ Frontend Refactoring Complete
App.js split into modular components:
- `/pages/` - 12 page components (including EarningsCalendarPage)
- `/components/` - Sidebar, TickerTape, PriceAlertNotification
- `/hooks/` - useWebSocket, usePriceAlerts
- `/utils/` - api, alertSounds

## API Endpoints

### Earnings Calendar (NEW)
- `GET /api/earnings/calendar` - Get earnings calendar (date range filter)
- `GET /api/earnings/{symbol}` - Detailed earnings data for symbol
- `GET /api/earnings/iv/{symbol}` - IV analysis for earnings

### Scanner
- `POST /api/scanner/scan` - Scan with 50-strategy criteria

### Watchlist & Portfolio
- `GET/POST/DELETE /api/watchlist`
- `GET/POST/DELETE /api/portfolio`

## Data Sources
- **Real-time quotes**: Twelve Data API
- **Earnings data**: SIMULATED (realistic data generation)
- **Fundamentals/Insider/COT**: MOCKED (simulated when APIs unavailable)

## Files Structure
```
/app/frontend/src/
├── pages/
│   ├── EarningsCalendarPage.js   # NEW - Earnings with IV, whispers, history
│   ├── DashboardPage.js
│   ├── ChartsPage.js
│   ├── ScannerPage.js
│   └── ... (12 pages total)
├── components/
│   ├── Sidebar.js (updated with Earnings nav)
│   └── ...
└── App.js
```

## Next Steps (Backlog)
- **P1**: User Authentication (Interactive Brokers integration)
- **P2**: Refactor backend into routers/services
- **P3**: Integrate real earnings APIs (e.g., Alpha Vantage, Financial Modeling Prep)
