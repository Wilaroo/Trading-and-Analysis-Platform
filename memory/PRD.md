# TradeCommand - Trading and Analysis Platform

## Product Overview
TradeCommand is a comprehensive trading and analysis platform designed for active traders. It provides real-time stock data, strategy scanning, portfolio tracking, trade journaling, and earnings analysis with AI-powered catalyst scoring.

## Core Requirements

### Real-time Market Data
- Live stock quotes via Finnhub API
- Market indices tracking (SPY, QQQ, DIA, IWM, VIX)
- WebSocket for live price streaming
- Audio/visual price alerts with adjustable thresholds

### Strategy Scanner (50+ Strategies)
- Intraday and swing trading strategies
- Smart recommendations based on market context
- Strategy filtering by market conditions (Trending, Consolidation, Mean Reversion)
- RVOL and ATR-based market context classification

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
  - `catalyst_scoring.py` - Earnings catalyst scoring
  - `trade_journal.py` - Trade logging and templates
  - `market_context.py` - Market classification
  - `notifications.py` - Alert system
  - `strategy_recommendations.py` - Smart scanner
- `/app/backend/routers/` - API endpoints
  - `catalyst.py` - Catalyst scoring endpoints
  - `trades.py` - Trade journal and templates
  - `market_context.py` - Context analysis
  - `notifications.py` - Alerts

### Frontend (React)
- `/app/frontend/src/pages/` - Page components
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
- Strategy scanner (50 strategies)
- VST fundamental scoring
- Market context analysis
- Smart strategy recommendations

### Phase 3 - Trade Journal ✅
- Trade logging with P&L tracking
- Strategy performance analytics
- Performance matrix by context
- Trade Templates (basic + strategy)

### Phase 4 - Earnings & Catalyst ✅
- Earnings calendar with IV analysis
- Whisper EPS tracking
- Catalyst Scoring System (-10 to +10)
- Quick catalyst scorer in UI

## API Endpoints

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

### Market Context
- `POST /api/market-context/analyze` - Analyze symbols
- `GET /api/market-context/summary` - Watchlist summary

## Pending/Future Tasks

### P1 - Backend Refactoring
- Move remaining logic from server.py to services/routers
- Portfolio and watchlist modules

### P2 - Notifications Enhancement
- Real-time earnings notifications
- Toast/badge for imminent earnings

### P3 - Authentication
- User authentication system
- Multi-user support

### P4 - Integrations
- Interactive Brokers API
- Replace mock data (Insider Trading, COT)

## Notes
- **Mocked Data**: Insider trading and COT data use simulated values
- **API Key**: Finnhub API key in `/app/backend/.env`
- **No Auth**: Currently single-user mode without authentication
