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
- **Cloud Dev**: Ollama + ngrok → `https://tradehub-420.preview.emergentagent.com`
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

## Prioritized Backlog
### P0 - Completed
- ✅ Scanner ↔ AI ↔ Trading Bot real-time integration
- ✅ AI Trading Assistant Phase 1 (integrated panel)
- ✅ AI Trading Assistant Phase 2 (AI-curated opportunities widget)

### P1 - Next Up
- Full index population (Russell 2000 needs ~1,600 more, Nasdaq 1000 needs ~400 more)
- Portfolio awareness: Proactive suggestions ("Scale out of AMD?", "Heavy tech exposure")
- Audio alerts for high-priority setups

### P2 - Future
- Strategy backtesting integration
- Level 2 order book analysis (tape reading)
- Full bot state persistence in MongoDB
- Weekly performance digest
