# TradeCommand - Advanced Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. The AI integrates the user's proprietary trading strategies, advanced chart patterns, technical analysis, risk management rules, and fundamental analysis to provide comprehensive trade analysis and personalized coaching.

## Core Requirements (Implemented)
1. **AI Assistant/Coach** - Sophisticated AI hub providing:
   - Trade analysis based on proprietary strategies
   - Real-time market news integration
   - Personalized coaching with rule enforcement
   - Knowledge of 36+ chart patterns from ChartGuys
   - Technical analysis (RSI, MACD, Bollinger Bands, etc.)
   - Fundamental analysis (P/E, ROE, D/E, FCF, etc.)
   
2. **Unified Trading Intelligence** - Centralized `TradingIntelligenceService`:
   - Deep integration of all knowledge sources
   - Trade setup scoring system (0-100 with grades A+ to F)
   - Pattern-strategy synergy analysis
   - Time-of-day and market regime awareness

3. **Real Trade Data Integration**:
   - Interactive Brokers Flex Web Service connection
   - Historical trade analysis
   - Performance metrics calculation

4. **UI/UX** - 3-column "AI Command Center" consolidating all modules

## Architecture

```
/app/
├── backend/
│   ├── routers/
│   │   └── assistant.py          # AI endpoints including /score-setup
│   ├── services/
│   │   ├── ai_assistant_service.py     # Main AI orchestrator
│   │   ├── trading_intelligence.py     # Unified scoring engine
│   │   ├── strategy_knowledge.py       # Proprietary strategies
│   │   ├── chart_patterns.py           # Basic chart patterns
│   │   ├── chart_patterns_detailed.py  # 36+ detailed patterns
│   │   ├── investopedia_knowledge.py   # Technical + Fundamental analysis
│   │   └── ib_flex_service.py          # IB trade history
│   └── server.py
└── frontend/
    └── src/
        ├── pages/CommandCenterPage.js
        └── components/AICommandPanel.jsx
```

## What's Been Implemented

### December 2025
- ✅ Verified AI Strategy Knowledge (fixed "AI Amnesia")
- ✅ Integrated Chart Pattern Intelligence (36+ patterns from ChartGuys)
- ✅ Created Unified Trading Intelligence System
- ✅ Added Trade Scoring API (`/api/assistant/score-setup`)
- ✅ Integrated Technical Analysis from Investopedia (RSI, MACD, Bollinger Bands, etc.)
- ✅ **Added Fundamental Analysis Knowledge Base** (P/E, P/B, PEG, ROE, D/E, FCF, EPS, etc.)
- ✅ Created stock fundamental scoring system with signals/warnings

## Key API Endpoints

### AI Assistant
- `POST /api/assistant/chat` - AI conversation (with real-time fundamentals + alert context)
- `POST /api/assistant/score-setup` - Trade setup scoring
- `POST /api/assistant/analyze-fundamentals` - Stock fundamental analysis
- `GET /api/assistant/realtime/fundamentals/{symbol}` - Live fundamental data
- `GET /api/assistant/realtime/analyze/{symbol}` - Full analysis
- `POST /api/assistant/realtime/compare` - Compare stocks' fundamentals

### Predictive Scanner
- `POST /api/scanner/scan` - Scan for forming trade setups
- `GET /api/scanner/setups` - Get tracked forming setups
- `GET /api/scanner/alerts` - Get imminent trigger alerts
- `GET /api/scanner/summary` - Dashboard summary

### Advanced Alert System (NEW)
- `POST /api/alerts/scan` - Full scan organized by timeframe
- `GET /api/alerts/scalp` - Scalp alerts: "Setting up now" / "On watch today"
- `GET /api/alerts/swing` - Swing alerts: "Setting up today" / "This week"
- `GET /api/alerts/summary` - Quick dashboard summary
- `POST /api/alerts/check-in-play/{symbol}` - Check if stock is "in play"
- `GET /api/alerts/scoring-weights` - View timeframe-based scoring weights

### Market Data
- `GET /api/market/news` - Market news
- `GET /api/ib/flex-trades` - IB trade history

## 3rd Party Integrations
- Interactive Brokers Flex Web Service
- Finnhub (market news, earnings)
- Alpaca Trading API (market data)
- Emergent LLM Key (GPT) - AI Assistant
- TradingView (`lightweight-charts`) - Frontend charting

## Prioritized Backlog

### P1 - High Priority
- [ ] Implement "Rubber Band Scanner" preset
- [ ] AI Coach proactive warnings for rule violations
- [ ] Proactive warning for historically losing tickers

### P2 - Medium Priority
- [ ] AI Assistant backtesting feature
- [ ] Keyboard shortcuts help overlay (`?` key)
- [ ] Trade Journal build-out
- [ ] Full user authentication

### P3 - Future
- [ ] Anchored VWAP Study
- [ ] Dedicated fundamental analysis API endpoint

## Known Issues
- Non-critical Python linting errors
- NPM vulnerabilities (from npm audit)

## Credentials Required
- `FINNHUB_API_KEY`
- `IB_FLEX_TOKEN` + `IB_FLEX_QUERY_ID`
- `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY`
- `EMERGENT_LLM_KEY`
