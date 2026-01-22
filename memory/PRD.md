# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform with REAL-TIME market data, technical analysis, VST fundamental scoring, **Market Context Classification** (Trending/Consolidation/Mean Reversion), and Earnings Notifications.

## What's Been Implemented (Jan 22, 2026 - Session 2)

### ✅ NEW: Market Context Analysis System
Auto-classify stocks into 3 market contexts based on your trading document:

**1. TRENDING Market**
- Identification: High RVOL (≥1.5), Rising ATR, Clear price direction
- Trade Styles: Breakout Confirmation, Pullback Continuation, Momentum Trading
- Sub-types: AGGRESSIVE (high volatility) or PASSIVE (gradual movement)
- Recommended Strategies: INT-01, INT-02, INT-03, INT-05, INT-14, INT-15

**2. CONSOLIDATION (Range) Market**
- Identification: Low RVOL (<1.0), Declining ATR, Tight range (<5%)
- Trade Styles: Range Trading, Scalping, Rubber Band Setup
- Recommended Strategies: INT-09, INT-12, INT-13, INT-17

**3. MEAN REVERSION Market**
- Identification: Overextended price (>2 std devs), High z-score
- Trade Styles: VWAP Reversion, Exhaustion Reversal, Key Level Reversal
- Recommended Strategies: INT-07, INT-08, INT-11, INT-12

### ✅ Market Context Dashboard (`/market-context`)
- **Summary Cards**: Visual breakdown of Trending/Consolidation/Mean Reversion stocks
- **Expandable Stock Cards**: Click to see detailed metrics (ATR, Trend, Range, Extension)
- **Custom Symbol Analysis**: Analyze any ticker on-demand
- **Recommended Trade Styles**: Context-appropriate strategy suggestions

### ✅ Enhanced Strategy Scanner
- **New "Context" Column**: Shows market context badge for each scanned stock
- **Context Match Highlighting**: Strategies that match the market context are highlighted with ★
- **Auto-classify Toggle**: Enable/disable market context analysis during scan
- **Parallel Analysis**: Scanner fetches quotes AND context simultaneously

### ✅ ATR-Based Consolidation Detection
- Calculates 14-period ATR and ATR trend (Rising/Declining/Flat)
- ATR change percentage used for consolidation signals
- Declining ATR (-10% or more) indicates consolidation

### ✅ Core Features (All Working)
1. **Dashboard** - Real-time portfolio tracking, market overview, top movers
2. **TradingView Charts** - Interactive professional charts with RSI, MACD, MA
3. **Strategy Scanner** - 50 strategies with market context integration
4. **VST Scoring System** - VectorVest-style fundamental scoring (0-10 scale)
5. **Earnings Calendar** - Full earnings tracking with IV analysis
6. **Earnings Notifications** - Alerts for watchlist stocks with upcoming earnings
7. **Watchlist** - AI-ranked picks with MongoDB persistence
8. **Portfolio Tracker** - Real-time P&L tracking
9. **Alert Center** - Strategy match + earnings notifications

### ✅ Finnhub Integration (60 calls/min)
- Primary data provider with fallback chain
- Real-time quotes and historical candle data
- Company profiles and earnings calendar

## API Endpoints

### Market Context API (NEW)
- `GET /api/market-context/{symbol}` - Full context analysis for a symbol
- `POST /api/market-context/batch` - Batch analysis for multiple symbols
- `GET /api/market-context/watchlist/analysis` - Analyze all watchlist stocks
- `GET /api/market-context/strategies/{context}` - Get strategies for context type

### Notifications API
- `GET /api/notifications` - Get all notifications
- `GET /api/notifications/check-earnings` - Check for earnings notifications
- `GET /api/notifications/earnings-summary` - Watchlist earnings summary

### Other APIs
- `GET /api/quotes/{symbol}` - Real-time quote (Finnhub)
- `GET /api/vst/{symbol}` - VST fundamental scoring
- `GET /api/earnings/calendar` - Earnings calendar
- CRUD: `/api/watchlist`, `/api/portfolio`

## Files Structure
```
/app/backend/
├── routers/
│   ├── notifications.py      # Notifications endpoints
│   └── market_context.py     # Market context endpoints
├── services/
│   ├── stock_data.py         # Finnhub/multi-provider service
│   ├── notifications.py      # Notification logic
│   └── market_context.py     # Context classification logic
└── server.py

/app/frontend/src/
├── pages/
│   ├── MarketContextPage.js  # NEW: Context dashboard
│   ├── ScannerPage.js        # UPDATED: With context column
│   ├── AlertsPage.js         # UPDATED: Earnings notifications
│   └── ... (13 pages total)
├── components/
│   └── Sidebar.js            # UPDATED: Market Context nav
└── App.js
```

## Configuration
```
# /app/backend/.env
FINNHUB_API_KEY=d5p596hr01qs8sp44dn0d5p596hr01qs8sp44dng
TWELVEDATA_API_KEY=demo
MONGO_URL=mongodb://localhost:27017
DB_NAME=tradecommand
```

## Test Results
- All quotes using Finnhub (60 calls/min)
- Market Context working with real historical data
- Scanner shows context badges and highlights matching strategies

## Priority Backlog
- **P2**: Continue backend refactoring (move more endpoints to routers)
- **P2**: User Authentication system
- **P3**: Interactive Brokers integration
- **P3**: Replace mock data (Insider Trading, COT) with real APIs
