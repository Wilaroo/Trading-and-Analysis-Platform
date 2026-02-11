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
- **Cloud Dev**: Ollama + ngrok → `https://trader-hq.preview.emergentagent.com`
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
**227 symbols scanned every 60 seconds with 30 SMB strategies**

### Features Implemented:
| Feature | Description |
|---------|-------------|
| **RVOL Pre-filtering** | Skips symbols with RVOL < 0.8 to focus on active stocks |
| **Tape Reading** | Analyzes bid/ask spread, order imbalance, momentum for confirmation |
| **Win-Rate Tracking** | Records outcomes for each strategy, calculates win rate & profit factor |
| **Auto-Execution** | Wires high-priority tape-confirmed alerts directly to Trading Bot |

### API Endpoints:
- `GET /api/live-scanner/stats/strategies` - Win-rate stats per setup
- `POST /api/live-scanner/stats/record-outcome` - Record alert result
- `POST /api/live-scanner/auto-execute/enable` - Enable/disable auto-execution
- `GET /api/live-scanner/auto-execute/status` - Auto-execute status
- `POST /api/live-scanner/config/rvol-filter` - Set RVOL filter threshold

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

### Watchlist (264 symbols):
- Mega cap tech, growth tech, financials, healthcare, energy, industrials
- High-volume movers, semiconductors, cloud/software, cybersecurity
- ETFs (SPY, QQQ, IWM, sector ETFs, leveraged ETFs)

## Architecture
```
/app/
├── backend/
│   ├── routers/ (trading_bot, learning_dashboard, market_intel, assistant, live_scanner)
│   ├── services/
│   │   ├── ai_assistant_service.py      # Smart routing: _call_llm(complexity=light|standard|deep)
│   │   ├── market_intel_service.py      # 7 data sources, anti-hallucination prompts
│   │   ├── trading_bot_service.py
│   │   ├── strategy_performance_service.py  # Learning loop → deep routing
│   │   ├── newsletter_service.py        # Now routes through shared AI assistant (deep)
│   │   ├── llm_service.py              # OllamaProvider added as first priority
│   │   └── background_scanner.py        # Generates alerts → live_scanner router
│   └── server.py
└── frontend/
    ├── pages/CommandCenterPage.js       # 2-tab layout: Command | Analytics
    ├── components/
    │   ├── TradingBotPanel.jsx          # Bot control + Signal Bubbles (fetches /api/live-scanner/alerts)
    │   ├── AICommandPanel.jsx           # AI chat with ticker detection
    │   └── MarketIntel/MarketIntelPanel.jsx
    └── hooks/useCommandCenterData.js
```

## Completed Features
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot with strategy configs (6 strategies)
3. AI <-> Bot integration: mutual awareness
4. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning
5. Performance optimization: caching, batching, tab-aware polling
6. UI: **2-tab layout (Command | Analytics)** - Consolidated from 3 tabs
7. Market Intelligence: 5 daily auto-reports, real Finnhub news, anti-hallucination
8. Morning Routine Auto-Trigger
9. Ollama Integration: local LLM via ngrok tunnel
10. Smart AI Routing: Ollama (light/standard) + GPT-4o (deep)
11. Enhanced Market Intel: 7 data sources (news, indices, watchlist, positions, bot, learning, scanner)
12. Newsletter + LLM Service routed through shared AI system
13. **Signal Bubbles Integration** (Feb 2026): Live scanner signals displayed as clickable bubbles in TradingBotPanel - removed separate Signals tab

## Prioritized Backlog
### P1 - Next Up
- Rubber Band Scanner Preset
- AI Coach Proactive Warnings
### P2 - Future
- Full bot state persistence in MongoDB
- AI Backtesting Feature
- Keyboard Shortcuts, Trade Journal, Full Auth
- Weekly performance digest
