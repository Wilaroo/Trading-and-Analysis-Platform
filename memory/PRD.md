# TradeCommand - Trading and Analysis Platform

## Product Overview
TradeCommand is a comprehensive trading and analysis platform designed for active traders. It provides real-time stock data, strategy scanning, portfolio tracking, trade journaling, and earnings analysis with AI-powered catalyst scoring.

## UI Architecture (v2.0) - Command Center

### Command Center (Main Hub)
The application is now consolidated into a single **Command Center** that serves as the primary trading intelligence hub. This eliminates the need to switch between multiple tabs.

**Included Panels:**
- **Quick Stats Row**: Net Liquidation, Today's P&L, Positions, Alerts, Market Regime, Opportunities count
- **Holdings**: Current positions with P&L tracking (collapsible)
- **Watchlist**: Quick view of watched tickers with live prices
- **Alerts**: Recent strategy alerts with badges
- **Earnings Calendar**: Upcoming earnings with BMO/AMC timing, dates, catalyst scores (collapsible)
- **Scanner Controls**: Top Gainers, Top Losers, Most Active, Gap Up, Gap Down
- **Trade Opportunities**: Scan results with HIGH CONVICTION badges, quick Buy/Short buttons
- **Market Intelligence**: Newsletter summary with sentiment, opportunities, and game plan

**Minimal Navigation (4 Tabs Only):**
1. Command Center (main)
2. Trade Journal
3. Charts
4. IB Trading

**Legacy Pages (Data Integrated into Command Center):**
- Dashboard → Merged into Command Center stats
- Trade Opportunities → Scanner is now in Command Center
- Newsletter → Summary shown in Market Intelligence panel
- Watchlist → Dedicated panel in Command Center
- Portfolio → Holdings panel shows positions
- Alerts → Dedicated panel in Command Center
- Market Context → Regime shown in Quick Stats
- Fundamentals → Available in Ticker Detail Modal
- News → Available in Ticker Detail Modal

## Core Requirements

### Real-time Market Data
- Live stock quotes via IB Gateway API
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
- `/app/backend/server.py` - Main application (refactored)
- `/app/backend/services/` - Business logic modules
  - `stock_data.py` - Finnhub API integration
  - `ib_service.py` - Interactive Brokers integration ✅ 
  - `strategy_service.py` - Strategy CRUD operations ✅ NEW (refactored)
  - `catalyst_scoring.py` - Earnings catalyst scoring
  - `trade_journal.py` - Trade logging and templates
  - `market_context.py` - Market classification
  - `notifications.py` - Alert system
  - `trading_rules.py` - Trading rules engine
  - `strategy_recommendations.py` - Smart scanner
- `/app/backend/routers/` - API endpoints
  - `ib.py` - Interactive Brokers endpoints
  - `strategies.py` - Strategy CRUD endpoints ✅ NEW (refactored)
  - `catalyst.py` - Catalyst scoring endpoints
  - `trades.py` - Trade journal and templates
  - `rules.py` - Trading rules endpoints
  - `market_context.py` - Context analysis
  - `notifications.py` - Alerts
- `/app/backend/data/` - Data files
  - `strategies_data.py` - 77 strategy definitions ✅ NEW (moved from server.py)

### Frontend (React)
- `/app/frontend/src/pages/` - Page components
  - `IBTradingPage.js` - Interactive Brokers trading UI
- `/app/frontend/src/components/` - Reusable UI
- `/app/frontend/src/utils/api.js` - API client

### Database (MongoDB)
- `strategies` - Trading strategies (77 strategies) ✅ NEW
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

### Phase 6 - Interactive Brokers Integration ✅ (Jan 22, 2026)
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

### Phase 7 - Backend Refactoring ✅ (Dec 2025)
- **Migrated 77 strategies from hardcoded data to MongoDB**
- Created `/app/backend/services/strategy_service.py` for strategy CRUD operations
- Created `/app/backend/routers/strategies.py` for strategy API endpoints
- Created `/app/backend/data/strategies_data.py` to store strategy seed data
- Auto-seeds strategies on first startup
- New API endpoints: search, categories, CRUD operations
- Significantly reduced `server.py` file size (~450 lines removed)

### Phase 11 - Enhanced Scanner & Chart Features ✅ NEW (Jan 2026)
- **Enhanced Scanner with Auto-Feature Calculation**:
  - `/api/ib/scanner/enhanced` endpoint
  - Auto-fetches 5-minute historical bars for each scanned stock
  - Calculates technical features (RSI, RVOL, VWAP, ATR, MACD)
  - Calculates intraday conviction score
  - Sorts results by conviction score (highest first)
  - Returns high_conviction_count for quick stats
- **HIGH CONVICTION Badges**:
  - Green glow border on high-conviction opportunity cards
  - "⚡ HIGH CONVICTION" badge with score
  - Conviction signals displayed (e.g., "High RVOL (3.5x)", "Near VWAP")
  - Enhanced stats: RVOL, RSI, VWAP% columns
- **Stop-Loss / Take-Profit on Charts**:
  - Toggle "Show SL/TP Lines" button in Analyze modal
  - Auto-suggested levels based on ATR (1.5x ATR stop, 3x ATR target)
  - Editable Entry, Stop Loss, Take Profit inputs
  - Real-time R:R Ratio calculation
  - Price lines drawn on chart:
    - Cyan line = Entry
    - Red dashed line = Stop Loss
    - Green dashed line = Take Profit

### Phase 12 - News & Newsletter Integration ✅ NEW (Jan 2026)
- **Premarket Newsletter Revamp**:
  - Complete redesign of NewsletterPage.js with daytrader-style UI
  - AI-powered newsletter generation using Perplexity API (Sonar model)
  - Market sentiment badge (BULLISH/BEARISH/NEUTRAL)
  - Overnight recap with international markets and futures
  - Key support/resistance levels for SPY/QQQ
  - Trade opportunities with Entry/Stop/Target prices
  - Catalyst watch section for economic events and earnings
  - Risk factors panel
  - Today's Game Plan section
  - Watchlist table with AI-scored picks
- **Ticker-Specific News Integration**:
  - News tab added to TickerDetailModal in Trade Opportunities page
  - Real-time news fetching from IB Gateway API
  - News headlines with source, timestamp, and sentiment
  - Fallback display when IB is not connected
- **Backend Services**:
  - `/app/backend/services/newsletter_service.py` - Perplexity API integration
  - `/app/backend/services/news_service.py` - IB news fetching
  - `/app/backend/routers/newsletter.py` - Newsletter and news API endpoints
- **New API Endpoints**:
  - `GET /api/newsletter/latest` - Get latest newsletter
  - `POST /api/newsletter/generate` - Generate new premarket briefing
  - `GET /api/newsletter/news/{symbol}` - Get ticker-specific news
  - `GET /api/newsletter/news` - Get general market news
  - `GET /api/ib/news/{symbol}` - Get IB news for ticker
  - `GET /api/ib/news` - Get general IB market news
- **Environment Variables**:
  - `PERPLEXITY_API_KEY` - API key for Perplexity AI
  - `PERPLEXITY_MODEL` - Model to use (default: sonar)

### Phase 10 - Feature Engineering Service ✅ NEW (Jan 2026)
- **Comprehensive technical indicator library** for IB Gateway integration:
  - **Price/Volume**: OHLCV, returns, gaps, dollar volume, RVOL
  - **Moving Averages**: SMA (10/20/50/100/200), EMA (9/20/50), cross signals, slopes
  - **Volatility**: ATR, True Range %, Historical Volatility, Range compression
  - **Momentum**: RSI (2/14), Stochastics, MACD, ROC, Williams %R
  - **VWAP**: Price vs VWAP, distance %, ATR bands
  - **Structure**: 20-bar/20-day/52-week highs/lows, prior day levels, pivot points
  - **Opening Range**: ORH/ORL, breakout detection
  - **Relative Strength**: vs SPY, vs Sector, RS ranking
- **High-Conviction Intraday Score** (0-100):
  - RVOL >= 2 (25 pts)
  - Near VWAP <= 0.5% (20 pts)
  - Above EMA20 (15 pts)
  - RSI 45-75 (15 pts)
  - Opening Range break (15 pts)
  - Near PDH/PDL (10 pts)
  - Strong catalyst (10 bonus pts)
- **VectorVest-style Composite Scores**:
  - RV Score (Relative Value)
  - RS Score (Relative Safety)
  - RT Score (Relative Timing)
  - VST Score (Composite)
- **API Endpoints**:
  - `POST /api/features/calculate` - Full feature calculation
  - `POST /api/features/quick-analysis` - Real-time quick analysis
  - `GET /api/features/indicators` - List all available indicators
  - `GET /api/features/high-conviction-criteria` - View criteria

### Phase 9 - Universal Scoring Engine ✅ NEW (Jan 2026)
- **Comprehensive stock scoring system (0-100)** with letter grades (A+ to D)
- **Top Picks UI Panel** ✅ integrated into Trade Opportunities page:
  - Timeframe toggle: All, Day (Intraday), Swing, Long-term
  - Direction filter: All, Long (↑), Short (↓)
  - Each pick displays:
    - Symbol, Grade, Composite Score
    - Direction (STRONG_LONG, LONG, NEUTRAL, SHORT, STRONG_SHORT)
    - Quick stats: RVOL, Gap%, VWAP position
    - Success probability bar with confidence level
    - 3 Support levels + 3 Resistance levels
    - Quick Buy/Short buttons when connected
  - Auto-scores opportunities when scanner runs
- **Five scoring categories:**
  - Technical (35%): VWAP position, RVOL by market cap, Gap%, MA distance, pattern recognition
  - Fundamental (20%): VectorVest-style scoring (Value, Safety, Growth, Timing)
  - Catalyst (20%): SMB system + major fundamental changes (earnings surprises, news)
  - Risk (10%): Float requirements, short interest, R:R ratio, liquidity
  - Context (15%): Market regime alignment, sector strength, strategy matching
- **User's custom rules integrated:**
  - Above VWAP = prioritize LONG, Below VWAP = prioritize SHORT
  - RVOL thresholds: 5x small cap, 3x mid cap, 2x large cap
  - Gap threshold: ≥4%
  - Extended above MAs = mean reversion SHORT, Extended below = rubber band LONG
  - Minimum 50M float
  - Short squeeze watchlist (>20% SI + 250K shares available)
- **Direction bias calculation:** STRONG_LONG, LONG, NEUTRAL, SHORT, STRONG_SHORT
- **Timeframe recommendations:** Intraday, Swing, Long-term
- **3 key support/resistance levels** per ticker
- **Success probability (20-90%)** based on rule compliance and historical patterns
- **API endpoints:**
  - `POST /api/scoring/analyze` - Single stock analysis
  - `POST /api/scoring/batch` - Multiple stocks
  - `POST /api/scoring/top-picks` - Filtered top picks
  - `GET /api/scoring/criteria` - View scoring weights/rules
  - `GET /api/scoring/timeframes` - Timeframe criteria

### Phase 8 - Trade Opportunities Dashboard ✅ (Dec 2025 - Jan 2026)
- **New consolidated "Trade Opportunities" page** - Replaces multiple scattered pages
- **IB Market Scanner Integration** - Scan US stocks in real-time via IB API:
  - Top % Gainers/Losers
  - Most Active by volume
  - Gap Up/Down stocks
  - 52-week High/Low
- **Strategy Matching** - Auto-matches scanned stocks to 77 trading strategies
- **Ticker Detail Modal with IB Real-time Chart** ✅ NEW (Jan 2026):
  - TradingView Lightweight Charts with IB historical data
  - Multiple timeframes (1m, 5m, 15m, 1H, Daily)
  - Candlestick + Volume visualization
  - Auto-refresh every 30 seconds
  - Price data, volume, high/low stats
  - Matching strategies with criteria
  - Trading rules and warnings
  - One-click trade buttons
- **Quick Trade from Scanner** ✅ (Jan 2026) - One-click order placement:
  - Buy/Short buttons on every opportunity card
  - Quick trade modal with quantity presets (10, 50, 100, 500)
  - Order types: Market, Limit, Stop, Stop-Limit
  - Auto-populated limit/stop prices from current quote
  - Estimated cost/proceeds calculator
  - Direct order execution via IB API
  - **Trade Confirmation Sound** - Audio feedback on order placement
  - **Toast Notifications** - Visual feedback with order details
- **Active Trades Panel with Real-time P&L** ✅ NEW (Jan 2026):
  - Entry price tracking
  - Current price (live from IB quotes)
  - Real-time P&L calculation ($ and %)
  - Long/Short position color coding
  - Remove trade from tracking
- **Strategy names displayed properly** - "INT-VWAP Bounce" instead of "INT-06"
- **Account panel** - Shows net liquidation, buying power, P&L, positions
- **Market Context panel** - Current regime, SPY/QQQ/VIX status
- **Auto-scan mode** - Automatically scans every 60 seconds when enabled
- **Sidebar reorganized** - Trade Opportunities at top, legacy pages grouped below

## API Endpoints

### Strategies ✅ NEW (Refactored)
- `GET /api/strategies` - Get all strategies (optional `?category=` filter)
- `GET /api/strategies/categories` - Get all strategy categories
- `GET /api/strategies/search?q=` - Search strategies by name/criteria/indicators
- `GET /api/strategies/count` - Get total strategy count
- `GET /api/strategies/{strategy_id}` - Get specific strategy
- `POST /api/strategies` - Create new strategy
- `PUT /api/strategies/{strategy_id}` - Update strategy
- `DELETE /api/strategies/{strategy_id}` - Delete strategy
- `POST /api/strategies/batch` - Get multiple strategies by IDs

### Interactive Brokers
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

### P1 - Order Fill Notifications
- Polling for IB order status changes
- Real-time toast and sound notifications when trades are filled

### P1 - Short Squeeze Watchlist
- Dedicated scanner/UI for high short interest stocks
- Shares available to short tracking

### P2 - Strategy Management UI
- Interface to add, edit, delete trading strategies
- CRUD operations directly within the application

### P2 - User Authentication
- Login system for multiple users
- Multi-user support

### P2 - Trade Journal Integration
- Automate logging of trades from Quick Trade feature
- Link trades to journal entries

### P2 - Multi-Chart Layout
- View multiple charts side-by-side

### P3 - Replace Mock Data
- Insider Trading with real API data
- Commitment of Traders (COT) reports

### P3 - Hotkeys
- Keyboard shortcuts for trading actions

### P3 - Mobile Responsive Design
- Responsive layout for mobile devices

## Notes
- **Mocked Data**: Insider trading and COT data use simulated values
- **API Keys**: 
  - Finnhub API key in `/app/backend/.env`
  - Perplexity API key in `/app/backend/.env` (for AI newsletter)
- **IB Gateway Required**: Must have IB Gateway running on port 4002 for paper trading
- **No Auth**: Currently single-user mode without authentication

## Changelog

### Jan 26, 2026 - Panel Reordering
**Implemented:**
- Restructured Command Center layout from 3-column grid to single-column flow
- New panel order (top to bottom):
  1. Holdings & Watchlist (side by side)
  2. Market Intelligence
  3. Trade Opportunities
  4. Smart Scanner
  5. Breakout Alerts
  6. Price Alerts
  7. Earnings
  8. Short Squeeze
  9. System Alerts (at bottom)
- Removed redundant Scanner Controls panel (replaced by Smart Scanner)

**Files Modified:**
- `/app/frontend/src/pages/CommandCenterPage.js` - Complete panel restructure

### Jan 26, 2026 - Comprehensive Smart Scanner
**Implemented:**
1. **Smart Scanner Panel** - Complete replacement of the basic scanner system
   - **Scans ALL types simultaneously**: Top Gainers, Losers, Most Active, Gap Up/Down, 13-week H/L
   - **Analyzes against ALL 77 trading rules** for each candidate
   - **Auto-detects timeframe**: Scalp, Intraday, Swing, Position based on strategy matches and features
   - **Score threshold slider**: Adjustable 0-100 (default 50) to filter alerts
   - **Categorized alerts with caps**:
     - Scalp: 10 max
     - Intraday: 25 max
     - Swing: 25 max
     - Position: 25 max
   - **Timeframe tabs**: Filter by All, Scalp, Intraday, Swing, Position
   - **Rich alert cards** with:
     - Direction (LONG/SHORT), Grade (A-F)
     - Entry/Stop/Target/R:R trade plan
     - Rules matched count (X/77)
     - Trigger reason
   - **Click to expand** for full analysis in modal
   - Runs automatically every 60 seconds when Auto-Scan enabled
   - Backend endpoint: `/api/ib/scanner/comprehensive` (POST)

**Files Modified:**
- `/app/backend/routers/ib.py` - Added comprehensive scanner endpoint with timeframe detection
- `/app/frontend/src/pages/CommandCenterPage.js` - New Smart Scanner panel UI with slider and tabs

### Jan 26, 2026 - Enhanced Alerts & Help Tooltips
**Implemented:**
1. **Smart Alerts Panel (Enhanced Contextual Alerts)**
   - New dedicated panel in Command Center for rich, contextual trading alerts
   - Each alert includes:
     - Exact timestamp (formatted naturally: "Today at 2:30pm")
     - Triggering rule/reason
     - Trading timeframe (scalp, intraday, swing, position)
     - Direction (LONG/SHORT) and Grade (A-F)
     - Full trade plan (Entry, Stop, Target, R/R)
     - Signal Strength (rules matched out of 77)
     - Natural language summary
   - Expandable modal with full analysis details
   - Direct Buy/Short buttons from alert
   - Backend service: `/app/backend/services/enhanced_alerts.py`
   - API endpoints: `/api/ib/alerts/enhanced` (GET, DELETE, etc.)

2. **Help Tooltip System Integration**
   - HelpTooltip component integrated across the UI
   - Dotted underline on hover for terms with definitions
   - Tooltip shows: term name, short definition, link to glossary
   - Integrated in:
     - **Technicals Tab**: RSI, RVOL, VWAP, VWAP Dist, EMA 9/20, SMA 50, ATR, MACD, Volume, Trend
     - **Overview Tab Scores**: Overall, Technical, Fundamental, Catalyst, Confidence
     - **Short Squeeze Panel**: SI%, DTC (Days to Cover), RVOL
     - **Enhanced Alerts Modal**: All scores and trade plan fields
   - Component: `/app/frontend/src/components/HelpTooltip.js`

3. **Chart Error Handling Verified**
   - Chart tab properly shows error when IB Gateway disconnected
   - Message: "IB Gateway is disconnected and no cached data available"
   - This is expected behavior, not a bug

**Files Modified:**
- `/app/frontend/src/pages/CommandCenterPage.js` - Added Smart Alerts panel, HelpTooltip integration
- `/app/frontend/src/components/HelpTooltip.js` - Added additional term IDs

### Jan 26, 2026 - Signal Strength + Glossary Page
**Implemented:**
1. **Signal Strength Indicator** for Breakout Alerts
   - Shows X/77 rules matched (e.g., "7/77")
   - Visual progress bar showing percentage
   - Labels: VERY STRONG (10+), STRONG (7-9), MODERATE (4-6), WEAK (1-3)
   - Color-coded: Green, Cyan, Yellow, Gray

2. **Glossary & Logic Page** (`/glossary`)
   - New sidebar navigation item "Glossary & Logic"
   - **33 terms documented** with comprehensive explanations
   - **10 Categories**: Scores & Grades, Technical Indicators, Momentum & Volume, Support & Resistance, Trading Strategies, Risk Management, Order Types, Market Context, Earnings & Catalysts, Abbreviations
   - **Global Search**: Search terms, definitions, or concepts
   - **Expandable Entries**: Click to expand full definitions
   - **Related Terms**: Links to related glossary entries
   - **Tags**: Clickable tags for quick filtering

**Key Terms Documented:**
- Overall Score, Grade (A/B/C/D/F), Technical Score, Fundamental Score, Catalyst Score, Confidence Score, Signal Strength, Breakout Score
- RSI, MACD, VWAP, EMA, SMA, ATR
- RVOL, Volume Profile, Momentum
- Support, Resistance
- Stop Loss, Risk/Reward, Position Sizing
- Market/Limit/Stop-Limit Orders
- Market Regime, VIX
- IV, Expected Move, Short Interest
- Common Abbreviations reference

### Jan 26, 2026 - No Mock Data + Breakout Alerts
**Implemented:**
1. **Removed ALL Mock Data**
   - Historical data, short squeeze scanner, and all other endpoints now return ONLY real IB Gateway data
   - Created `/app/backend/services/data_cache.py` for caching real data with timestamps
   - When IB Gateway disconnected: shows cached data with "last_updated" timestamp
   - When no cached data: displays clear error message asking to connect IB Gateway
   - Auto-refresh pending when connection is restored

2. **Breakout Alerts Scanner** (`/api/ib/scanner/breakouts`)
   - Scans for stocks breaking above resistance (LONG) or below support (SHORT)
   - Returns TOP 10 that meet ALL criteria:
     - Match user's 77 trading rules/strategies
     - Meet momentum criteria (RVOL >= 1.2, trend alignment)
     - Overall score >= 60
     - At least one strategy match
   - Includes: breakout_score, entry, stop_loss, target, risk_reward, matched_strategies
   - Sound + toast notifications for new breakouts

3. **Chart Error Handling**
   - Chart tab now shows proper error message when data unavailable
   - Shows "IB Gateway is disconnected and no cached data available"
   - Graceful degradation with all other data still visible

4. **Data Cache Service**
   - Caches: historical data, quotes, account data, positions, short interest, news
   - Each cached item includes `last_updated` timestamp
   - `is_cached: true` flag indicates non-realtime data

**Known Issues:**
- Chart candlesticks still not rendering even with valid data (TradingView library issue)

### Jan 26, 2026 - P1 Features Implementation
**Implemented:**
1. **Short Squeeze Watchlist Panel**
   - New panel on Command Center showing 10 high short interest stocks
   - Displays: Squeeze Score (0-100), Short Interest %, Days to Cover, RVOL
   - Color-coded risk levels (HIGH=red, MEDIUM=yellow, LOW=gray)
   - Click to open Ticker Detail Modal
   - Backend endpoint: `/api/ib/scanner/short-squeeze`

2. **Price Alerts with Sound Notifications**
   - Create alerts for any symbol at target price (above/below)
   - Toast notifications when alerts trigger
   - Sound alerts (can be toggled on/off)
   - Backend endpoints: `/api/ib/alerts/price` (CRUD), `/api/ib/alerts/price/check`
   - Polls every 10 seconds when connected

3. **Order Fill Notifications**
   - Backend endpoints for tracking orders: `/api/ib/orders/track`, `/api/ib/orders/fills`
   - Sound notification when orders are filled
   - Toast notification with order details

4. **Historical Data API Enhancement**
   - `/api/ib/historical/{symbol}` now returns mock data when IB Gateway disconnected
   - Prevents errors when testing without live connection

**Known Issues:**
- Chart rendering in Ticker Detail Modal shows blank canvas (data loads correctly, TradingView library initializes, but candlesticks don't render)
- Workaround: Overview tab displays all key data including price, scores, and analysis

### Jan 26, 2026 - Bug Fix: Ticker Detail Modal
- **Issue**: The comprehensive "Ticker Detail Modal" was not populating data when clicking on tickers
- **Root Cause**: The Alerts section items in `CommandCenterPage.js` were missing the `onClick` handler to set `selectedTicker` state
- **Fix**: Added `onClick={() => setSelectedTicker({ symbol: alert.symbol, quote: {} })}` to alert items
- **Also Added**: `data-testid` attributes for better testability
- **Verified Working**:
  - Modal opens correctly from Alerts, Earnings, Watchlist, Holdings, and Trade Opportunities sections
  - All tabs populate correctly: Overview, Chart, Technicals, Fundamentals, Strategies, News
  - Scores, trading analysis, company info, and matched strategies all display properly



### Jan 26, 2026 - Critical Backend Bug Fix (P0)
**Fixed:**
1. **IBService.run_scanner() Method Signature**
   - **Error**: `IBService.run_scanner() got an unexpected keyword argument 'limit'`
   - **Root Cause**: Scanner calls in `ib.py` were using `limit=` parameter instead of `max_results=`
   - **Fix**: Changed `limit=20` and `limit=30` to `max_results=20` and `max_results=30` in:
     - Line 1230 (short-squeeze scanner)
     - Line 1741 (comprehensive scanner)

2. **FeatureEngineService Method Name**
   - **Error**: `'FeatureEngineService' object has no attribute 'calculate_features'`
   - **Root Cause**: Multiple locations calling non-existent method `calculate_features()` instead of `calculate_all_features()`
   - **Fix**: Updated all calls to use `calculate_all_features()` with correct parameters:
     - Line 659 (analysis endpoint): `calc_all_features()` → `calculate_all_features(bars_5m=bars)`
     - Line 1254 (short-squeeze scanner)
     - Line 1472 (breakout scanner)
     - Line 1796 (comprehensive scanner)
     - Line 2209 (symbol analysis endpoint)

**Files Modified:**
- `/app/backend/routers/ib.py` - Fixed 7 method calls

**Verified Working:**
- All scanner endpoints now return proper 503 responses when IB Gateway disconnected (instead of 500 crashes)
- `/api/ib/scanner/short-squeeze` - Returns appropriate error
- `/api/ib/scanner/breakouts` - Returns appropriate error
- `/api/ib/scanner/comprehensive` - Returns appropriate error
- `/api/ib/analysis/AAPL` - Returns proper analysis data
- Frontend loads without crashes

### Jan 26, 2026 - System Monitor Feature
**Implemented:**
1. **Backend Health Check Endpoint** (`/api/system/monitor`)
   - Comprehensive health check for all backend services
   - Returns overall status: healthy, partial, or degraded
   - Checks 7 services:
     - MongoDB database connection
     - IB Gateway connection status
     - Strategies service (77 strategies loaded)
     - Feature Engine (technical indicators)
     - Scoring Engine
     - AI/LLM (Emergent LLM Key)
     - Market Data (Finnhub API)
   - Returns status details for each service
   - Summary counts: healthy, warning, disconnected, error

2. **Compact System Monitor in Header** (Command Center)
   - Simplified status indicator next to "Command Center" heading
   - Shows colored dots for each service (green=healthy, orange=disconnected, red=error)
   - Displays "X/Y" count (e.g., "6/7" = 6 healthy out of 7 total)
   - Hover over dots to see service name and details
   - Auto-refreshes every 30 seconds
   - Color-coded overall status (green/yellow/red)

**Files Modified:**
- `/app/backend/server.py` - Added `/api/system/monitor` endpoint
- `/app/frontend/src/pages/CommandCenterPage.js` - Added compact System Monitor to header



### Jan 26, 2026 - Additional Backend Bug Fixes
**Fixed:**
1. **VIX Contract Type Error**
   - **Error**: `No security definition has been found for the request, contract: Stock(symbol='VIX')`
   - **Root Cause**: VIX is an index, not a stock - requires different contract type in IB
   - **Fix**: Updated `get_quote` in `ib_service.py` to detect VIX and use `Index("VIX", "CBOE")` instead of `Stock`

2. **UniversalScoringEngine Method Name**
   - **Error**: `'UniversalScoringEngine' object has no attribute 'calculate_scores'`
   - **Root Cause**: Calling non-existent method `calculate_scores()` instead of `calculate_composite_score()`
   - **Fix**: Updated all 3 occurrences in `ib.py` to use correct method with proper `stock_data` dict:
     - Line 1504 (breakout scanner)
     - Line 1806 (comprehensive scanner)
     - Line 2224 (symbol analysis endpoint)

**Files Modified:**
- `/app/backend/services/ib_service.py` - Fixed VIX contract type
- `/app/backend/routers/ib.py` - Fixed 3 scoring engine method calls



### Jan 27, 2026 - MongoDB Persistence for Scanner Cache
**Implemented:**
1. **DataCache MongoDB Persistence**
   - Scanner cache now persists to MongoDB collection `data_cache`
   - Quote cache persists after batch updates
   - Short interest data persists periodically
   - Data loads automatically from MongoDB on server startup

2. **Persistence Methods Added:**
   - `_load_from_mongodb()` - Loads cached data on initialization
   - `_persist_scanner_cache()` - Saves scanner results to MongoDB
   - `_persist_quote_cache()` - Saves quotes to MongoDB
   - `_persist_short_interest_cache()` - Saves short interest data

3. **Benefits:**
   - Scanner results survive server restarts
   - Overnight/premarket data available even after app restart
   - No data loss when IB Gateway disconnects

**Files Modified:**
- `/app/backend/services/data_cache.py` - Added MongoDB persistence layer



### Jan 27, 2026 - Knowledge Base System
**Implemented:**
1. **Backend Knowledge Service** (`/app/backend/services/knowledge_service.py`)
   - MongoDB-based storage in `knowledge_base` collection
   - Full-text search with indexes
   - Types: strategy, pattern, insight, rule, note, indicator, checklist
   - Categories: entry, exit, risk_management, position_sizing, etc.
   - CRUD operations with soft delete
   - Usage tracking, confidence scoring
   - Export/import for backup

2. **API Endpoints** (`/app/backend/routers/knowledge.py`)
   - `POST /api/knowledge` - Add new entry
   - `GET /api/knowledge` - Search entries (query, type, category, tags)
   - `GET /api/knowledge/stats` - Get statistics
   - `GET /api/knowledge/types` - Get available types/categories
   - `GET /api/knowledge/{id}` - Get single entry
   - `PUT /api/knowledge/{id}` - Update entry
   - `DELETE /api/knowledge/{id}` - Delete entry
   - `GET /api/knowledge/export/all` - Export all entries
   - `POST /api/knowledge/import` - Import entries

3. **Frontend UI** (`/app/frontend/src/components/KnowledgeBase.jsx`)
   - Modal accessible via "Knowledge" button in header
   - Search with type/category filters
   - Add/edit form with all fields
   - Entry list with icons, tags, confidence
   - Edit and delete actions
   - Stats footer showing entry counts by type

**Usage:**
- Click "Knowledge" button in Command Center header
- Add strategies, patterns, insights, rules
- Search by text, filter by type/category
- Tag entries for easy filtering
- Set confidence levels (0-100%)

**Files Created:**
- `/app/backend/services/knowledge_service.py`
- `/app/backend/routers/knowledge.py`
- `/app/frontend/src/components/KnowledgeBase.jsx`



### Jan 27, 2026 - AI Learning System & Knowledge Integration (MAJOR UPDATE)
**Implemented:**
1. **AI Learning System**
   - Portable LLM service (`llm_service.py`) - Works with OpenAI API key or Emergent LLM Key
   - Document processor (`document_processor.py`) - Extracts text from PDFs using PyPDF2
   - Knowledge service (`knowledge_service.py`) - Stores structured knowledge in MongoDB
   - Learning router (`learning.py`) - API endpoints for learning and analysis

2. **Knowledge Integration into Scoring & Market Intelligence**
   - `knowledge_integration.py` - New service that bridges knowledge base with scoring engine
   - Scoring engine now includes `knowledge_base` object with applicable strategies
   - Newsletter service includes KB strategy insights in prompts
   - Trade bias enhanced by knowledge base confidence

3. **API Endpoints for Learning System**
   - `GET /api/learn/status` - Returns KB stats and LLM status
   - `POST /api/learn/text` - Learn strategies from text input
   - `POST /api/learn/analyze/{symbol}` - Analyze stock with KB integration
   - `POST /api/learn/enhance-opportunities` - Enhance opportunities with strategy insights
   - `GET /api/learn/ai-recommendation/{symbol}` - Get AI-powered trade recommendation
   - `POST /api/learn/bulk` - Bulk import knowledge entries

4. **Knowledge Base Populated with 97 Entries**
   - 77 strategies from "151 Trading Strategies.pdf"
   - 11 trading rules (position sizing, R:R, daily loss limits)
   - 4 indicators (VWAP bias, volume confirmation)
   - 2 checklists (short squeeze criteria, overnight hold)
   - 2 insights (news catalyst hierarchy)
   - Covers: Options, Stocks, ETFs, Futures, FX, Global Macro, ML strategies

5. **Scoring Engine Enhancement**
   - Composite scores now include `knowledge_base` object
   - Contains: `applicable_strategies`, `kb_trade_bias`, `kb_confidence`
   - Score boosted when KB agrees with trade direction

6. **Newsletter/Market Intelligence Enhancement**
   - Prompts now include KB strategy insights
   - Shows which strategies apply to which opportunities
   - Backed by learned trading knowledge

**Files Created:**
- `/app/backend/services/llm_service.py`
- `/app/backend/services/document_processor.py`
- `/app/backend/services/knowledge_integration.py`
- `/app/backend/routers/learning.py`

**Files Modified:**
- `/app/backend/services/scoring_engine.py` - Added KB integration
- `/app/backend/services/newsletter_service.py` - Added KB insights to prompts

**Testing:**
- 19/19 backend tests passed
- Frontend Knowledge button and modal working
- All API endpoints verified working



### Jan 27, 2026 - Earnings Quality Factor Integration (Quantpedia Strategy)
**Implemented:**
1. **Quality Service** (`/app/backend/services/quality_service.py`)
   - 4-factor quality scoring: Accruals, ROE, CF/A, D/A
   - Data sources: Known data (fallback), Yahoo Finance, FMP API, IB
   - Composite scoring (0-400 scale) with percentile rankings
   - Quality classifications: High/Low quality, Letter grades (A+ to F)
   - Trading signals: LONG for high quality, SHORT for low quality
   - Bear market hedge portfolio generation

2. **Quality API Endpoints** (`/app/backend/routers/quality.py`)
   - `GET /api/quality/metrics/{symbol}` - Raw quality metrics
   - `GET /api/quality/score/{symbol}` - Composite quality score
   - `POST /api/quality/scan` - Scan symbols for quality stocks
   - `GET /api/quality/scanner/high-quality` - Find high quality stocks
   - `GET /api/quality/hedge/bear-market` - Bear market hedge portfolio
   - `GET /api/quality/leaderboard` - Ranked list by quality

3. **Scoring Engine Enhancement**
   - Added "Earnings Quality" component to fundamental scoring
   - Up to 20 bonus points for high-quality stocks
   - Scores ROE, D/A, CF/A, and Accruals individually

4. **Knowledge Base Updated**
   - 9 new entries for Earnings Quality Factor strategy
   - Includes trading rules, indicators, and bear market hedge strategy
   - Total knowledge base: 108 entries (82 strategies, 13 rules, 8 indicators)

**Files Created:**
- `/app/backend/services/quality_service.py`
- `/app/backend/routers/quality.py`

**Files Modified:**
- `/app/backend/server.py` - Added quality router and service
- `/app/backend/services/scoring_engine.py` - Added earnings quality bonus scoring
- `/app/backend/requirements.txt` - Added yfinance dependency

**API Usage Examples:**
```bash
# Get quality score for AAPL
curl /api/quality/score/AAPL

# Get quality leaderboard
curl /api/quality/leaderboard?symbols=AAPL,MSFT,NVDA,BA

# Get bear market hedge portfolio
curl /api/quality/hedge/bear-market
```


### Jan 27, 2026 - Quality Factor UI Panel
**Implemented:**
1. **QualityPanel Component** (`/app/frontend/src/components/QualityPanel.jsx`)
   - Quality Factor panel in Command Center
   - Shows quality grades (A+ to F) for scanned stocks
   - 4-factor metric bars: Accruals, ROE, CF/A, D/A
   - Filter tabs: All, High Quality, Low Quality
   - Leaderboard view showing top quality stocks
   - LONG/SHORT signal indicators
   - Info banner explaining the 4 quality factors

2. **Integration with Command Center**
   - Panel appears below Trade Opportunities
   - Auto-fetches quality scores when opportunities are scanned
   - Clicking a stock opens the ticker detail modal
   - Leaderboard shows ranked list of major stocks

**Files Created:**
- `/app/frontend/src/components/QualityPanel.jsx`

**Files Modified:**
- `/app/frontend/src/pages/CommandCenterPage.js` - Imported and integrated QualityPanel

**Note:** Quality Panel was later removed per user request - quality integrated into scoring/assistant instead.


### Jan 27, 2026 - AI Trading Assistant (Hybrid Architecture)
**Implemented:**
1. **AI Assistant Service** (`/app/backend/services/ai_assistant_service.py`)
   - Portable LLM architecture: Emergent (default), OpenAI, Perplexity support
   - Conversation memory with MongoDB persistence
   - Learns frequent request patterns and suggests them
   - Integrates with knowledge base (108+ strategies/rules)
   - Integrates with quality service for stock analysis
   - Trading rule enforcement in responses
   - Pattern detection in user's trading behavior

2. **AI Assistant API** (`/app/backend/routers/assistant.py`)
   - `POST /api/assistant/chat` - Main chat endpoint
   - `POST /api/assistant/analyze-trade` - Analyze a trade idea
   - `GET /api/assistant/premarket-briefing` - Auto-generated morning briefing
   - `GET /api/assistant/review-patterns` - Analyze trading patterns
   - `GET /api/assistant/suggestions` - Frequently asked requests
   - `GET /api/assistant/history/{session_id}` - Conversation history
   - `GET /api/assistant/sessions` - All conversation sessions
   - `GET /api/assistant/providers` - Available LLM providers
   - `GET /api/assistant/status` - Service health status

3. **AI Assistant UI** (`/app/frontend/src/components/AIAssistant.jsx`)
   - Modal chat interface with message history
   - Welcome screen with 6 quick suggestion buttons
   - Real-time "Analyzing..." indicator
   - Markdown rendering for AI responses
   - Session history browser
   - Minimize/maximize functionality
   - Clear conversation option
   - Quick action buttons during conversation

4. **System Prompt Personality**
   - ANALYTICAL: Explains reasoning step-by-step
   - PROTECTIVE: Enforces trading rules, warns about violations
   - EDUCATIONAL: Helps understand why, not just what
   - HONEST: States uncertainty, never fabricates data

**Features:**
- Conversation memory persisted to MongoDB
- Suggests frequently asked requests
- Enforces trading rules in responses
- Detects patterns in trading behavior
- Uses quality scores in analysis
- Searches knowledge base for relevant strategies

**Files Created:**
- `/app/backend/services/ai_assistant_service.py`
- `/app/backend/routers/assistant.py`
- `/app/frontend/src/components/AIAssistant.jsx`

**Files Modified:**
- `/app/backend/server.py` - Added assistant router and service
- `/app/frontend/src/pages/CommandCenterPage.js` - Added AI Assistant button and modal




### Jan 27, 2026 - Quality Integration & Pre-Market Scheduler (Session Update)
**Implemented:**
1. **Quality Badges on Trade Opportunity Cards**
   - Each opportunity card now shows quality grade badge (A+, A, B, C, etc.)
   - Color-coded: Green (A+/A), Cyan (B+/B), Yellow (C+/C), Red (D/F)
   - Scanner auto-fetches quality scores using `/api/quality/enhance-opportunities`

2. **Ask AI Button on Individual Stocks**
   - Every opportunity card has "AI" button that opens AI Assistant
   - Pre-fills prompt with stock-specific analysis request
   - Ticker Detail Modal header also has Ask AI button

3. **Pre-Market Briefing Auto-Generation (Scheduled)**
   - New scheduler service (`/app/backend/services/scheduler_service.py`)
   - Schedule pre-market briefing generation at 6:30 AM ET daily
   - Toggle button in Market Intelligence section ("Schedule" / "6:30 AM")
   - API endpoints: `POST /api/scheduler/premarket/schedule`, `DELETE /api/scheduler/premarket/stop`

4. **Quality Tab in Ticker Detail Modal**
   - New "Quality" tab showing 4-factor Earnings Quality scores
   - Visual progress bars for each factor (Accruals, ROE, CF/A, D/A)
   - Shows quality grade, percentile rank, signal (LONG/SHORT/NEUTRAL)
   - Raw metrics display (actual values)
   - Info banner explaining the quality factor methodology
   - Header shows Q:grade badge (e.g., Q:A)

5. **Cleanup**
   - Deleted unused `/app/frontend/src/components/QualityPanel.jsx`

**Files Created:**
- `/app/backend/services/scheduler_service.py` - Scheduler service for automated tasks
- `/app/backend/routers/scheduler.py` - Scheduler API endpoints

**Files Modified:**
- `/app/backend/server.py` - Added scheduler service and router
- `/app/frontend/src/pages/CommandCenterPage.js`:
  - Trade Opportunity cards: quality badges + AI button
  - TickerDetailModal: Quality tab, Ask AI button in header
  - Market Intelligence: Schedule toggle button
  - Scanner: auto-enhances with quality scores

**API Endpoints:**
- `GET /api/scheduler/status` - Scheduler health status
- `POST /api/scheduler/premarket/schedule` - Enable auto pre-market generation
- `DELETE /api/scheduler/premarket/stop` - Disable auto pre-market generation
- `POST /api/scheduler/premarket/generate-now` - Manual trigger
- `GET /api/scheduler/premarket/latest` - Get cached briefing

**Testing:**
- 23/23 backend tests passed (iteration_8.json)
- All frontend features verified working



### Jan 28, 2026 - P0-P2 Trading Features Implementation
**Implemented:**

1. **P0: Custom Trading Indicators (COMPLETE)**
   - `market_indicators.py` - Full implementation of:
     - **VOLD Ratio**: Market breadth indicator using SPY/QQQ/IWM volume direction
     - **5 ATR Over-Extension Bands**: Identifies stocks in over-extended territory
     - **Volume Threshold Study**: Standard deviation-based significant volume detection
     - **Market Regime Classification**: 4-regime model (Aggressive Trending, Passive Trending, Volatile Range, Quiet Consolidation)
   - API endpoints in `market_context.py`:
     - `GET /api/market-context/indicators/vold` - VOLD ratio and trend day detection
     - `GET /api/market-context/indicators/regime` - Full market regime analysis
     - `GET /api/market-context/indicators/extension/{symbol}` - Stock ATR extension analysis
     - `GET /api/market-context/indicators/volume-threshold/{symbol}` - Volume significance
   - Scoring engine integration:
     - `score_advanced_indicators()` method adds VOLD alignment, ATR extension, and volume significance scoring
     - 10% weight for advanced indicators in composite score
     - Warnings and bonuses based on indicator signals

2. **P1: Visual WebSocket vs IB Gateway Status Indicator (COMPLETE)**
   - Dual connection status display in Command Center header:
     - **WebSocket (Quotes)**: Blue indicator with pulsing dot when streaming active, orange with spinner when reconnecting
     - **IB Gateway**: Green when connected, red when disconnected
   - Clear visual distinction helps user understand:
     - WebSocket reconnection = quotes temporarily unavailable (auto-reconnects)
     - IB Gateway disconnect = trading/scanning unavailable (requires manual connect)
   - Tooltips explain each connection type's purpose
   - Props added to CommandCenterPage: `wsConnected`, `wsLastUpdate`

3. **P2: IB Connection Stability Verification (FEATURES IN PLACE)**
   - Thread-safe busy lock (`_busy_lock`) prevents race conditions
   - 10-second scan cooldown prevents rapid consecutive scans
   - Pre-scan stability check returns cached results during cooldown
   - Status endpoint returns `is_busy` and `busy_operation` for UI feedback
   - Auto-reconnect logic in worker thread heartbeat
   - **Note**: User testing required to verify stability under load

**Files Modified:**
- `/app/frontend/src/App.js` - Added `wsConnected`, `wsLastUpdate` to ibProps
- `/app/frontend/src/pages/CommandCenterPage.js` - New dual connection status UI

**Already Implemented (Previous Session):**
- `/app/backend/services/market_indicators.py` - Full VOLD, ATR, Volume, Regime logic
- `/app/backend/routers/market_context.py` - Indicator endpoints
- `/app/backend/services/scoring_engine.py` - Advanced indicators integration
- `/app/backend/services/ib_service.py` - Thread-safe busy lock, heartbeat
- `/app/backend/routers/ib.py` - Scan cooldown, stability checks

**API Verification:**
```bash
# VOLD Ratio endpoint working
curl /api/market-context/indicators/vold
# Returns: nyse/nasdaq vold_ratio, is_trend_day, market_bias

# Market Regime endpoint working  
curl /api/market-context/indicators/regime
# Returns: regime classification, favored/avoid setups, position sizing guidance
```
