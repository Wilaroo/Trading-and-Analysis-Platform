# TradeCommand - Trading and Analysis Platform

## Overview
Professional trading platform with real-time data, market context classification, smart strategy recommendations, and **Strategy Performance Tracking** to analyze which strategies work best in each market context.

## What's Been Implemented (Jan 22, 2026)

### ✅ NEW: Strategy Performance Tracking (Trade Journal)
Track trades and analyze performance by strategy and market context:

**Features:**
- **Log Trades**: Symbol, strategy, entry/exit prices, shares, direction, market context
- **Performance Summary**: Total trades, win rate, P&L, avg P&L, best context
- **Context Breakdown**: Win rate and P&L per market context (Trending/Consolidation/Mean Reversion)
- **Strategy-Context Matrix**: Best and worst strategy-context combinations
- **Filter Views**: All / Open / Closed trades

**Insights Provided:**
- Which contexts perform best (e.g., "Trending: 100% win rate")
- Which strategies to avoid in certain contexts
- Overall trading statistics

### ✅ Smart Strategy Recommendations
- Scanner auto-classifies market context
- Highlights strategies that match context (★)
- Shows strategies to avoid (✕)
- Context alignment scoring

### ✅ Market Context Classification
- **TRENDING**: High RVOL, Rising ATR
- **CONSOLIDATION**: Low RVOL, Declining ATR, Tight range
- **MEAN REVERSION**: Overextended price, High z-score

### ✅ Core Features
- Dashboard with real-time portfolio tracking
- TradingView charts with RSI, MACD, MA
- 50-strategy scanner with smart filtering
- VST fundamental scoring (0-10 scale)
- Earnings calendar with IV analysis
- Earnings notifications for watchlist
- Watchlist & Portfolio (MongoDB persisted)

### ✅ Data Sources
- **Finnhub API** (60 calls/min) - Real-time quotes
- Historical candle data for context analysis

## API Endpoints

### Trade Journal API (NEW)
- `POST /api/trades` - Log new trade
- `GET /api/trades` - Get trades (with filters)
- `GET /api/trades/open` - Get open positions
- `POST /api/trades/{id}/close` - Close trade
- `GET /api/trades/performance` - Performance summary
- `GET /api/trades/performance/matrix` - Strategy-context matrix

### Other APIs
- Market Context: `/api/market-context/*`
- Quotes: `/api/quotes/{symbol}`
- VST: `/api/vst/{symbol}`
- Notifications: `/api/notifications/*`

## Files Structure
```
/app/backend/
├── routers/
│   ├── notifications.py
│   ├── market_context.py
│   └── trades.py                 # NEW
├── services/
│   ├── stock_data.py
│   ├── market_context.py
│   ├── strategy_recommendations.py
│   └── trade_journal.py          # NEW
└── server.py

/app/frontend/src/pages/
├── TradeJournalPage.js           # NEW
├── MarketContextPage.js
├── ScannerPage.js
└── ... (14 pages total)
```

## MongoDB Collections
- `trades` - Trade records
- `strategy_performance` - Cached performance metrics
- `watchlists`, `portfolios`, etc.

## Sample Data
```
Trades: 5
Win Rate: 80%
P&L: $1,950

By Context:
- TRENDING: 100% win, +$1,200
- MEAN_REVERSION: 100% win, +$900
- CONSOLIDATION: 0% win, -$150
```

## Priority Backlog
- **P2**: User Authentication
- **P2**: Export trade history to CSV
- **P3**: Interactive Brokers integration
- **P3**: Replace mock data with real APIs
