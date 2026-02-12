# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with AI trading coach, autonomous trading bot, and mutual learning loop.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **AI**: Smart Routing — Ollama (local/free) + GPT-4o (Emergent, deep tasks)
- **Integrations**: Alpaca, Finnhub, IB Gateway (see Data Sources below)

## Data Sources

| Source | Provides | Availability |
|--------|----------|--------------|
| **Alpaca** | Real-time quotes, paper trading, account data | Cloud (always on) |
| **Finnhub** | 100 live news headlines, earnings calendar | Cloud (always on) |
| **IB Gateway** | VIX index, IB scanners, fundamentals, live trading | Local only (requires IB Gateway running) |
| **Ollama** | Free AI for chat, summaries, market intel | Via ngrok tunnel |

## Startup Modes
- **Cloud Dev**: Ollama + ngrok → `https://command-charts.preview.emergentagent.com`
- **Full Local**: All services on PC → `http://localhost:3000`
- See `/documents/STARTUP_GUIDE.md` for detailed instructions

## Smart AI Routing (Feb 2026)
| Complexity | Model | Tasks | Cost |
|-----------|-------|-------|------|
| **light** | Ollama (llama3:8b) | Quick chat, summaries | Free |
| **standard** | Ollama first, GPT-4o fallback | Market intel reports, general chat | Free (mostly) |
| **deep** | GPT-4o (Emergent) | Strategy analysis, trade evaluation, "should I buy", recommendations | Credits |

### Deep Keyword Triggers
`should i buy`, `should i sell`, `analyze`, `evaluate`, `deep dive`, `strategy`, `backtest`, `risk`, `recommend`, `quality score`, `compare`, `portfolio`, `rebalance`, `hedge`, `options`, `earnings play`, `swing trade`, `position size`, `thesis`

## Market Intel Data Sources (7 total)
1. Finnhub News (100 live headlines, earnings & analyst actions filtered)
2. Market Indices (SPY, QQQ, IWM, DIA, VIX)
3. Watchlist Quotes (AAPL, MSFT, NVDA, TSLA, AMD, META, GOOGL, AMZN)
4. Account/Positions (Alpaca)
5. Trading Bot Status (exact state from service)
6. Strategy Performance (exact from learning loop DB)
7. Scanner Signals (live alerts from enhanced scanner)

## Enhanced Scanner (Feb 2026)
**~1,083 symbols scanned via ETF-based wave scanning (SPY + QQQ + IWM) with 30+ SMB strategies**

### Features Implemented:
| Feature | Description |
|---------|-------------|
| **ETF-Based Universe** | Stocks organized by SPY (Tier 1), QQQ (Tier 1), IWM (Tier 3 rotating) |
| **Volume Filtering** | ADV >= 100K for general, ADV >= 500K for intraday/scalp setups |
| **Wave Scanning** | Tiered scanning: Watchlist (T1) → High RVOL (T2) → Rotating Universe (T3) |
| **Smart Watchlist** | Hybrid auto-populated + manual watchlist with strategy-based expiration |
| **RVOL Pre-filtering** | Skips symbols with RVOL < 0.8 to focus on active stocks |
| **Tape Reading** | Analyzes bid/ask spread, order imbalance, momentum for confirmation |
| **Win-Rate Tracking** | Records outcomes for each strategy, calculates win rate & profit factor |
| **Auto-Execution** | Wires high-priority tape-confirmed alerts directly to Trading Bot |
| **AI Coaching** | Proactive AI notifications for high-priority scanner alerts |
| **Quarterly Rebalance Alerts** | System flags when ETF lists need refreshing |

### Universe Structure:
| ETF | Coverage | Count | Priority |
|-----|----------|-------|----------|
| SPY | S&P 500 Large Caps | ~492 | **Tier 1** (every scan) |
| QQQ | Nasdaq-100 Tech | ~120 | **Tier 1** (every scan) |
| IWM | Russell 2000 Small Caps | ~545 | **Tier 3** (rotating) |
| **Total Unique** | | ~1,083 | |

### Volume Filters:
- **General/Swing setups**: ADV >= 100,000
- **Intraday/Scalp setups**: ADV >= 500,000

### Scanner → AI → Bot Integration (Feb 2026)
```
Scanner detects HIGH/CRITICAL alert
    ↓
Auto-populates Smart Watchlist
    ↓
Triggers AI Coaching Notification
    ↓
(If auto-execute enabled) Submits to Trading Bot
```

### New API Endpoints (Feb 2026):
- `GET /api/assistant/coach/scanner-notifications` - Get proactive coaching alerts
- `POST /api/assistant/coach/scanner-coaching?symbol=X&setup_type=Y` - Manual coaching
- `GET /api/live-scanner/config/volume-filter` - Get ADV filter settings
- `POST /api/live-scanner/config/volume-filter` - Set ADV filter thresholds

### Existing API Endpoints:
- `GET /api/live-scanner/stats/strategies` - Win-rate stats per setup
- `POST /api/live-scanner/stats/record-outcome` - Record alert result
- `POST /api/live-scanner/auto-execute/enable` - Enable/disable auto-execution
- `GET /api/live-scanner/auto-execute/status` - Auto-execute status
- `POST /api/live-scanner/config/rvol-filter` - Set RVOL filter threshold
- `GET /api/smart-watchlist` - Get hybrid watchlist
- `POST /api/smart-watchlist/add` - Manual add to watchlist
- `DELETE /api/smart-watchlist/{symbol}` - Remove from watchlist

### Strategies Implemented:
| Category | Strategies |
|----------|------------|
| **Opening (9:30-9:45)** | First VWAP Pullback, Opening Drive, First Move Up/Down, Bella Fade |
| **Morning Momentum** | ORB, HitchHiker, Gap Give and Go, Gap Pick and Roll |
| **Core Session** | Spencer Scalp, Second Chance, Back$ide, Off Sides, Fashionably Late |
| **Mean Reversion** | Rubber Band, VWAP Bounce, VWAP Fade, Tidal Wave |
| **Consolidation** | Big Dog, Puppy Dog, 9-EMA Scalp, ABC Scalp |
| **Afternoon** | HOD Breakout, Time-of-Day Fade |
| **Special** | Breaking News, Volume Capitulation, Range Break, Breakout |

### Time-of-Day Filtering:
- Each strategy only triggers during its valid time window
- Time windows: opening_auction, opening_drive, morning_momentum, morning_session, late_morning, midday, afternoon, close

### Market Regime Detection:
- Scanner reads SPY to determine: strong_uptrend, strong_downtrend, range_bound, volatile, momentum, fade
- Strategies filtered based on optimal market conditions

### Universe Coverage:
- S&P 500: 493 symbols
- Nasdaq 1000: 610 symbols
- Russell 2000: 412 symbols (partial)
- ETFs: 228 symbols
- **Total Unique: 1,425 symbols**

## Architecture
```
/app/
├── backend/
│   ├── data/
│   │   └── index_symbols.py           # S&P 500, Nasdaq 1000, Russell 2000 lists
│   ├── routers/ (trading_bot, learning_dashboard, market_intel, assistant, live_scanner)
│   ├── services/
│   │   ├── ai_assistant_service.py      # Smart routing + Scanner coaching notifications
│   │   ├── enhanced_scanner.py          # Wave scanning + AI/Bot integration
│   │   ├── smart_watchlist_service.py   # Hybrid auto/manual watchlist
│   │   ├── wave_scanner.py              # Tiered universe scanning
│   │   ├── index_universe.py            # Large symbol universe management
│   │   ├── support_resistance_service.py # Advanced S/R calculation
│   │   ├── trading_bot_service.py
│   │   ├── strategy_performance_service.py
│   │   └── market_intel_service.py
│   └── server.py
└── frontend/
    ├── pages/CommandCenterPage.js       # 2-tab layout: Command | Analytics
    ├── components/
    │   ├── AICommandPanel.jsx           # **AI Trading Assistant** - Bot + AI + Scanner integrated
    │   ├── RightSidebar.jsx             # Smart Watchlist widget
    │   └── MarketIntel/MarketIntelPanel.jsx
    └── utils/
        └── tickerUtils.jsx              # Clickable ticker utility
```

## Completed Features
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot with strategy configs (30+ strategies)
3. AI ↔ Bot integration: mutual awareness
4. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning
5. Performance optimization: caching, batching, tab-aware polling
6. UI: **2-tab layout (Command | Analytics)** - Consolidated from 3 tabs
7. Market Intelligence: 5 daily auto-reports, real Finnhub news, anti-hallucination
8. Morning Routine Auto-Trigger
9. Ollama Integration: local LLM via ngrok tunnel
10. Smart AI Routing: Ollama (light/standard) + GPT-4o (deep)
11. Enhanced Market Intel: 7 data sources
12. Newsletter + LLM Service routed through shared AI system
13. Signal Bubbles Integration: Live scanner signals displayed as clickable bubbles
14. **Clickable Tickers & News** (Feb 2026): All stock tickers clickable throughout UI
15. **Advanced S/R Analysis** (Feb 2026): Pivot Points, Volume Profile, historical zones
16. **Wave Scanning** (Feb 2026): Tiered scanning of 1,425 symbols
17. **Smart Watchlist** (Feb 2026): Hybrid auto/manual with strategy-based expiration
18. **Scanner → AI Coaching** (Feb 2026): Proactive notifications for high-priority alerts
19. **AI Trading Assistant Phase 1** (Feb 2026): Integrated panel with Bot + AI + Scanner
    - Bot controls (Start/Stop, Mode selector) in header
    - Coaching alerts with Execute/Half Size/Pass buttons
    - Confirmation dialog before trade execution
    - Conversational trading: "take NVDA", "show my trades", "stop the bot"
    - Removed separate TradingBotPanel
20. **AI Trading Assistant Phase 2** (Feb 2026): AI-Curated Opportunities
    - Two-column layout: Expanded chat (left) + Curated widget (right)
    - AI-Curated Opportunities widget shows top 3-5 TAKE/WAIT setups
    - Rank badges (#1, #2, #3), verdict icons, one-click Execute/Pass
    - Collapsed sections (Bot Trades, Earnings, Watchlist) for more chat space
    - Toast notifications for new TAKE opportunities
21. **Consolidated Stats Header** (Feb 2026): Removed QuickStatsRow
    - All stats moved into AI Trading Assistant header
    - Two-row layout: Account stats (top) + Bot controls (bottom)
    - Top row: Net Liquidation, Today's P&L, Positions, Market Regime
    - Bottom row: Bot toggle, P&L, open count, Mode selector
    - Cleaner UI with more vertical space for content
22. **Tavily Agent Skills** (Feb 2026): Credit-optimized research tools
    - Intelligent caching with variable TTLs (3min-24hr based on data type)
    - Agent Skills: `get_company_info`, `get_stock_analysis`, `get_market_context`
    - Combines FREE sources (Finnhub, Finviz, Yahoo scrapers) before using Tavily
    - Quick analysis mode (0 credits) for basic data
    - Cache stats monitoring via `/api/research/stats`

## Prioritized Backlog
### P0 - Completed
- ✅ Scanner ↔ AI ↔ Trading Bot real-time integration
- ✅ AI Trading Assistant Phase 1 (integrated panel)
- ✅ AI Trading Assistant Phase 2 (AI-curated opportunities widget)
- ✅ Consolidated Stats Header (removed QuickStatsRow)
- ✅ Tavily Agent Skills with intelligent caching
- ✅ Charts Tab Integration (TradingView embedded, click-to-view from widgets)

### P1 - Next Up
- Remove old redundant ChartsPage.js and its route (now superseded by ChartsTab)
- Portfolio awareness: Proactive suggestions ("Scale out of AMD?", "Heavy tech exposure")
- Audio alerts for high-priority setups
- Focus Mode: Hide all sections except chat + top opportunity when actively trading
- Full index population (Russell 2000 needs ~1,600 more, Nasdaq 1000 needs ~400 more)

### P2 - Future
- Strategy backtesting integration
- Level 2 order book analysis (tape reading)
- Full bot state persistence in MongoDB
- Weekly performance digest

---

## Session Log - February 12, 2026

### Tavily Agent Skills Implementation
**Goal**: Integrate Tavily's Agent Skills with aggressive caching to minimize credit usage on free tier.

**Implementation:**
1. **Intelligent Cache System**: Variable TTLs based on data freshness requirements
   - Company info: 1 hour (fundamentals don't change often)
   - Stock analysis: 10 minutes
   - News: 3 minutes
   - SEC filings: 24 hours
   - Deep dive/market context: 15 minutes

2. **Agent Skills Created**:
   - `get_company_info(ticker)`: Combines Finnhub + Finviz + Yahoo, uses Tavily only if gaps exist
   - `get_stock_analysis(ticker, type)`: Quick (0 credits), News (1 credit), Comprehensive (1-2 credits)
   - `get_market_context()`: Daily market overview (indices, regime, themes)

3. **Credit Optimization Strategy**:
   - Check FREE sources first (Finnhub, Finviz scrapers, Yahoo scrapers)
   - Only call Tavily to fill data gaps
   - Use "basic" search depth when possible (1 credit vs 2)
   - Cache all results aggressively

4. **New API Endpoints**:
   - `GET /api/research/skills/company-info/{ticker}`
   - `GET /api/research/skills/stock-analysis/{ticker}?analysis_type=quick|news|comprehensive`
   - `GET /api/research/skills/market-context`
   - `GET /api/research/stats` (cache monitoring)
   - `GET /api/research/budget` (credit budget status)
   - `POST /api/research/budget/limit` (update monthly limit)

5. **Credit Budget Tracking**:
   - Persistent monthly tracking in MongoDB (`tavily_credit_usage` collection)
   - Warning thresholds: 50% (low), 75% (medium), 90% (high), 95% (critical)
   - Auto-blocks searches when limit exceeded
   - Projects usage and warns if on track to exceed
   - Resets automatically on month rollover
   - **Frontend indicator in header bar** showing remaining credits with color-coded status
   - **Clickable modal** with detailed usage breakdown: circular progress ring, stats grid (daily avg, projected, session, days left), on-track indicator, recent queries list
   - **Credits Saved Banner**: Green gradient showing credits saved by caching, savings percentage, cache hit rate, and effective cost comparison

6. **AI Assistant Integration**:
   - Updated intent detection to route to Agent Skills
   - New research types: `company_info`, `stock_analysis`, `market_context`
   - Rich formatting for Agent Skill results

### Files Modified
- `backend/services/web_research_service.py` - Added IntelligentCache, Agent Skills, CreditBudgetTracker
- `backend/services/ai_assistant_service.py` - Updated research intent detection & formatting
- `backend/routers/research.py` - New Agent Skills and budget endpoints
- `backend/server.py` - Initialize web research service with DB on startup
- `frontend/src/hooks/useCommandCenterData.js` - Added creditBudget state and fetching
- `frontend/src/pages/CommandCenterPage.js` - Pass creditBudget to HeaderBar
- `frontend/src/components/layout/HeaderBar.jsx` - Added credit budget indicator UI

---

## Session Log - February 11, 2026

### P0 Bug Fix: IB Connection UI Issue
**Problem**: Frontend UI showed IB Gateway as "disconnected" despite backend being connected.

**Root Causes Fixed**:
1. `datetime` objects in `alpaca_service.py` not serialized to ISO strings before WebSocket broadcast
2. React StrictMode causing double-mounting and rapid WebSocket connect/disconnect cycles
3. Stale WebSocket connections not being properly cleaned up

**Fixes Applied**:
- Converted all `_cached_at` datetime fields to `.isoformat()` strings
- Disabled React StrictMode in `index.js`
- Improved WebSocket `ConnectionManager` to auto-cleanup stale connections
- Added auto-connect to IB Gateway on backend startup

### System Optimizations Implemented
1. **Staggered Polling Intervals**: Bot status 20s, trades 25s, coaching 15s (were all 10-15s)
2. **Batch Init Endpoint**: New `GET /api/dashboard/init` returns system health, alerts, smart watchlist in ONE call
3. **Phased Startup Loading**: Critical data first, earnings calendar loads last (1s delay)
4. **Removed Unused Newsletter Fetch**: No longer fetched on Command Center startup
5. **Reduced IB Check Interval**: 30s → 15s for faster UI updates

### Files Modified
- `backend/server.py` - WebSocket manager, auto-connect, batch init endpoint
- `backend/services/alpaca_service.py` - datetime serialization fix
- `backend/services/fundamental_data_service.py` - datetime serialization fix
- `frontend/src/index.js` - Disabled StrictMode
- `frontend/src/App.js` - IB check interval, debug logging
- `frontend/src/hooks/useCommandCenterData.js` - Batch init, staggered loading
- `frontend/src/components/AICommandPanel.jsx` - Optimized polling intervals
- `frontend/src/components/layout/HeaderBar.jsx` - Safety check for systemHealth.services
