# TradeCommand - Trading and Analysis Platform

## Product Overview
TradeCommand is a comprehensive trading and analysis platform designed for active traders. It provides real-time stock data, strategy scanning, portfolio tracking, trade journaling, and earnings analysis with AI-powered catalyst scoring.

## Core Requirements

### Real-time Market Data
- Live stock quotes via Finnhub API
- Market indices tracking (SPY, QQQ, DIA, IWM, VIX)
- WebSocket for live price streaming
- Audio/visual price alerts with adjustable thresholds

### Interactive Brokers Integration ✅ NEW
- Connect to IB Gateway for paper trading
- Real-time market data streaming from IB
- Place/cancel orders (Market, Limit, Stop, Stop-Limit)
- View account summary, positions, and open orders

### Strategy Scanner (77 Strategies)
- **Now stored in MongoDB** (refactored from hardcoded data)
- Intraday, swing, and investment trading strategies
- Smart recommendations based on market context
- Strategy filtering by market conditions (Trending, Consolidation, Mean Reversion)
- RVOL and ATR-based market context classification
- Full CRUD operations via `/api/strategies` endpoints
- Search strategies by name, criteria, or indicators

### Earnings Calendar
- Upcoming earnings with implied volatility analysis
- Whisper EPS and sentiment tracking
- Catalyst Scoring System (-10 to +10 scale)
- IV percentile and expected move calculations

### Trade Journal
- Trade logging with entry/exit tracking
- Strategy performance analytics by market context
- Trade Templates for quick logging (basic + strategy-specific)
- **Quick Trade from Scanner** - One-click trade logging from scanner results
- P&L tracking and win rate analysis
- Inline notes editing

### Trading Rules Engine
- Consolidated trading knowledge from 18+ PDFs
- Dynamic strategy recommendations based on market conditions
- Game plan framework and daily routines
- Common mistakes and avoidance rules

### Portfolio & Watchlist
- Position tracking with average cost basis
- Watchlist management
- Real-time P&L calculations

### VST Fundamental Scoring
- 0-10 scale fundamental scoring
- Revenue growth, margin analysis, earnings quality
- Comparative valuation metrics

## Technical Architecture

### Backend (FastAPI)
- `/app/backend/server.py` - Main application
- `/app/backend/services/` - Business logic modules
  - `stock_data.py` - Finnhub API integration
  - `ib_service.py` - Interactive Brokers integration ✅ NEW
  - `catalyst_scoring.py` - Earnings catalyst scoring
  - `trade_journal.py` - Trade logging and templates
  - `market_context.py` - Market classification
  - `notifications.py` - Alert system
  - `trading_rules.py` - Trading rules engine
  - `strategy_recommendations.py` - Smart scanner
- `/app/backend/routers/` - API endpoints
  - `ib.py` - Interactive Brokers endpoints ✅ NEW
  - `catalyst.py` - Catalyst scoring endpoints
  - `trades.py` - Trade journal and templates
  - `rules.py` - Trading rules endpoints
  - `market_context.py` - Context analysis
  - `notifications.py` - Alerts

### Frontend (React)
- `/app/frontend/src/pages/` - Page components
  - `IBTradingPage.js` - Interactive Brokers trading UI ✅ NEW
- `/app/frontend/src/components/` - Reusable UI
- `/app/frontend/src/utils/api.js` - API client

### Database (MongoDB)
- `positions` - Portfolio positions
- `watchlist` - User watchlist
- `trades` - Trade journal entries
- `trade_templates` - Custom trade templates
- `catalysts` - Catalyst scores
- `alerts` - Price alerts

## Implemented Features (as of Jan 2026)

### Phase 1 - Core Platform ✅
- Dashboard with market overview
- Real-time quotes via Finnhub
- Portfolio and watchlist management
- TradingView charting integration

### Phase 2 - Strategy & Analysis ✅
- Strategy scanner (77 strategies)
- VST fundamental scoring
- Market context analysis
- Smart strategy recommendations

### Phase 3 - Trade Journal ✅
- Trade logging with P&L tracking
- Strategy performance analytics
- Performance matrix by context
- Trade Templates (basic + strategy)
- Quick Trade from Scanner
- Inline notes editing

### Phase 4 - Earnings & Catalyst ✅
- Earnings calendar with IV analysis
- Whisper EPS tracking
- Catalyst Scoring System (-10 to +10)
- Quick catalyst scorer in UI

### Phase 5 - Trading Rules Engine ✅
- Consolidated knowledge from 18+ user PDFs
- Dynamic strategy recommender
- Game plan and daily routine frameworks
- Common mistakes avoidance

### Phase 6 - Interactive Brokers Integration ✅ NEW (Jan 22, 2026)
- IB Gateway connection (port 4002 for paper trading)
- Account summary with net liquidation, buying power, cash
- Position tracking from IB
- Order placement (Market, Limit, Stop, Stop-Limit)
- Open orders management with cancel functionality
- Auto-refresh of account data
- **Bug Fix (Dec 2025)**: Resolved order placement timeout by implementing threaded architecture
  - All IB operations now run in dedicated `IBWorkerThread` with its own event loop
  - Queue-based communication between FastAPI and IB thread for Windows compatibility
  - Eliminates asyncio event loop conflicts with ib_insync on Python 3.11+

## API Endpoints

### Interactive Brokers ✅ NEW
- `GET /api/ib/status` - Connection status
- `POST /api/ib/connect` - Connect to IB Gateway
- `POST /api/ib/disconnect` - Disconnect from IB
- `GET /api/ib/account/summary` - Account summary
- `GET /api/ib/account/positions` - Current positions
- `GET /api/ib/quote/{symbol}` - Real-time quote
- `POST /api/ib/order` - Place order
- `DELETE /api/ib/order/{order_id}` - Cancel order
- `GET /api/ib/orders/open` - Open orders
- `GET /api/ib/executions` - Today's fills
- `GET /api/ib/historical/{symbol}` - Historical data

### Catalyst Scoring
- `POST /api/catalyst/score/quick` - Quick earnings score
- `GET /api/catalyst/score-guide` - Scoring rubric
- `GET /api/catalyst/history/{symbol}` - Symbol history
- `GET /api/catalyst/recent` - Recent scores

### Trade Journal & Templates
- `POST /api/trades` - Create trade
- `GET /api/trades` - List trades
- `PUT /api/trades/{id}/close` - Close trade
- `GET /api/trades/performance` - Analytics
- `GET /api/trades/templates/defaults` - System templates
- `GET /api/trades/templates/list` - All templates
- `POST /api/trades/from-template` - Create from template
- `PATCH /api/trades/{trade_id}/notes` - Update trade notes

### Trading Rules
- `GET /api/rules/recommend` - Strategy recommendations
- `GET /api/rules/game-plan` - Daily game plan
- `GET /api/rules/avoidance` - Universal avoidance rules

### Market Context
- `POST /api/market-context/analyze` - Analyze symbols
- `GET /api/market-context/summary` - Watchlist summary

## IB Gateway Configuration
- **Host**: 127.0.0.1
- **Port**: 4002 (paper trading)
- **Client ID**: 1
- **Account ID**: DUN615665

## Pending/Future Tasks

### P1 - Backend Refactoring
- Move remaining logic from server.py to services/routers
- Migrate 77 hardcoded strategies to MongoDB collection
- Portfolio and watchlist modules

### P2 - Notifications Enhancement
- Real-time earnings notifications
- Toast/badge for imminent earnings

### P3 - Authentication
- User authentication system
- Multi-user support

### P4 - Data Sources
- Replace mock data (Insider Trading, COT) with real APIs

## Notes
- **Mocked Data**: Insider trading and COT data use simulated values
- **API Keys**: Finnhub API key in `/app/backend/.env`
- **IB Gateway Required**: Must have IB Gateway running on port 4002 for paper trading
- **No Auth**: Currently single-user mode without authentication
