# TradeCommand - Trading and Analysis Platform

## Overview
A comprehensive trading platform with REAL-TIME market data, technical analysis, VST fundamental scoring, **Market Context Classification**, and **Smart Strategy Recommendations**.

## What's Been Implemented (Jan 22, 2026)

### ✅ Smart Strategy Recommendations (NEW)
Intelligent filtering of 50 strategies based on market context:

**How it works:**
1. Scanner analyzes each stock's market context (Trending/Consolidation/Mean Reversion)
2. Maps context to optimal strategies using research-backed recommendations
3. Highlights matching strategies with ★ and avoid strategies with ✕
4. Ranks results by "Context Alignment" score

**Features:**
- **Alignment Column**: Shows what % of matched strategies fit the context
- **Context Filter Bar**: One-click filter by Trending/Range/Reversion
- **Smart Sorting**: Results sorted by context alignment when enabled
- **Visual Indicators**: ★ for recommended, ✕ for avoid strategies
- **Avoid Strategies**: Strategies marked to avoid in current context (red/strikethrough)

**Strategy Mappings:**
| Context | Primary Strategies | Secondary | Avoid |
|---------|-------------------|-----------|-------|
| TRENDING | INT-01, INT-02, INT-05, INT-10, INT-14, INT-15, SWG-01, SWG-04 | INT-03, INT-04, INT-06, SWG-02 | INT-13, SWG-03 |
| CONSOLIDATION | INT-09, INT-12, INT-13, INT-17, INT-19, SWG-03, SWG-13 | INT-02, INT-03, SWG-02 | INT-01, INT-04, INT-14 |
| MEAN_REVERSION | INT-07, INT-08, INT-11, INT-20, SWG-06, SWG-10, SWG-14 | INT-06, INT-12, SWG-03 | INT-01, INT-04, INT-15 |

### ✅ Market Context Analysis System
Auto-classify stocks into 3 contexts:

**TRENDING**: High RVOL, Rising ATR, Clear direction
- Trade Styles: Breakout Confirmation, Pullback Continuation, Momentum

**CONSOLIDATION**: Low RVOL, Declining ATR, Tight range
- Trade Styles: Range Trading, Scalping, Rubber Band Setup

**MEAN REVERSION**: Overextended price, High z-score
- Trade Styles: VWAP Reversion, Exhaustion Reversal, Key Level Reversal

### ✅ Market Context Dashboard (`/market-context`)
- Summary cards showing context distribution
- Expandable stock cards with detailed metrics
- Custom symbol analysis
- Recommended trade styles per context

### ✅ Core Features
1. **Dashboard** - Real-time portfolio tracking, top movers
2. **TradingView Charts** - Professional charts with indicators
3. **Strategy Scanner** - 50 strategies with smart context filtering
4. **VST Scoring** - VectorVest-style fundamental scoring (0-10)
5. **Earnings Calendar** - IV analysis, whispers, historical data
6. **Earnings Notifications** - Alerts for watchlist stocks
7. **Watchlist/Portfolio** - MongoDB persistence

### ✅ Finnhub Integration
- 60 calls/min (vs 8 for Twelve Data)
- Real-time quotes and historical candles
- Company profiles

## API Endpoints

### Strategy Recommendations API (NEW)
- `GET /api/market-context/recommendations/{symbol}` - Smart recommendations for a symbol
- `GET /api/market-context/matrix` - Context-strategy mapping matrix

### Market Context API
- `GET /api/market-context/{symbol}` - Context analysis
- `POST /api/market-context/batch` - Batch analysis
- `GET /api/market-context/watchlist/analysis` - Watchlist analysis

### Other APIs
- `GET /api/quotes/{symbol}` - Real-time quote (Finnhub)
- `GET /api/vst/{symbol}` - VST scoring
- `GET /api/notifications` - Notifications
- CRUD: `/api/watchlist`, `/api/portfolio`

## Files Structure
```
/app/backend/
├── routers/
│   ├── notifications.py
│   └── market_context.py
├── services/
│   ├── stock_data.py              # Finnhub provider
│   ├── notifications.py
│   ├── market_context.py          # Context classification
│   └── strategy_recommendations.py # NEW: Smart filtering
└── server.py

/app/frontend/src/
├── pages/
│   ├── MarketContextPage.js       # Context dashboard
│   ├── ScannerPage.js             # UPDATED: Smart recommendations
│   └── ... (13 pages total)
└── App.js
```

## Configuration
```
FINNHUB_API_KEY=d5p596hr01qs8sp44dn0d5p596hr01qs8sp44dng
TWELVEDATA_API_KEY=demo
MONGO_URL=mongodb://localhost:27017
DB_NAME=tradecommand
```

## Priority Backlog
- **P2**: User Authentication system
- **P2**: Continue backend refactoring
- **P3**: Interactive Brokers integration
- **P3**: Replace mock data with real APIs
