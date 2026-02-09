# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. The platform includes a fully autonomous trading bot integrated into the AI Command Center, capable of scanning for opportunities, evaluating trades, managing risk, calculating position sizes, and executing trades (both paper and live). The AI and bot are deeply integrated — learning from and improving each other through a mutual learning loop.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts (TradingView)
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **Integrations**: Alpaca (paper trading), Finnhub (fundamentals), IB (scanners), Emergent LLM (GPT), yfinance

## Core Architecture
```
/app/
├── backend/
│   ├── routers/
│   │   ├── trading_bot.py         # Bot control, demo trades, simulate-closed
│   │   ├── learning_dashboard.py  # Strategy stats, AI analysis, recommendations
│   │   ├── live_scanner.py        # SSE real-time alerts
│   │   └── assistant.py           # AI chat (bot-aware)
│   ├── services/
│   │   ├── trading_bot_service.py          # Core bot logic, state, risk
│   │   ├── trade_executor_service.py       # Alpaca order execution
│   │   ├── strategy_performance_service.py # Learning loop: tracking, analysis, tuning
│   │   ├── ai_assistant_service.py         # AI chat + bot awareness + trade eval
│   │   └── background_scanner.py           # Async market scanning
│   └── server.py                  # Wires all services together
└── frontend/
    └── src/
        ├── components/
        │   ├── TradingBotPanel.jsx     # Bot control UI
        │   ├── LearningDashboard.jsx   # Strategy perf + AI tuning UI
        │   ├── AICommandPanel.jsx      # AI chat + Bot Trades section
        │   └── LiveAlertsPanel.jsx     # Real-time alerts
        └── pages/
            └── CommandCenterPage.js    # Main page integrating all panels
```

## Completed Features

### Phase 1: Core Platform
- AI Assistant with real-time data, background scanner with SSE alerts

### Phase 2: Autonomous Trading Bot
- Full trade lifecycle, risk management, profit-taking, trailing stops, automatic stop-loss

### Phase 3: Strategy-Specific Configurations
- TradeTimeframe enum, 6 strategies, EOD auto-close, CRUD API, frontend editing

### Phase 4: AI ↔ Bot Deep Integration
- AI evaluates trades before execution, full bot awareness in chat, Bot Trades in AI Command Panel

### Phase 5: Mutual Learning Loop (Dec 2025)
- **Strategy Performance Tracker**: Records every closed trade to MongoDB `strategy_performance` collection with per-strategy aggregation (win rate, avg P&L, R:R, close reasons, stop %)
- **AI Performance Analyzer**: Analyzes patterns across strategies, identifies issues (stops too tight, scaling out too aggressively), generates specific parameter recommendations
- **Auto-Tuning Engine**: Applies AI recommendations to strategy configs with safety guardrails (trail_pct min 0.5%, max 8%, max ±20% change). Full audit trail in `tuning_history` collection
- **Heuristic Recommendation Engine**: Data-driven fallback when AI doesn't produce structured recs. Fires on >50% stop rate + <50% win rate → suggests widening trail_pct
- **Learning Dashboard UI**: Strategy performance cards with win rate bars, total P&L, W/L, avg P&L, best/worst trade, stop%. AI Analysis button, recommendation Apply/Dismiss, expandable tuning history
- **Simulate Closed Endpoint**: POST /api/trading-bot/demo/simulate-closed for testing learning loop outside market hours

## Key API Endpoints
### Trading Bot
- `POST /api/trading-bot/start|stop` - Bot control
- `GET /api/trading-bot/status` - Status with strategy_configs
- `GET/PUT /api/trading-bot/strategy-configs/{strategy}` - CRUD
- `GET /api/trading-bot/trades/all|pending|open|closed` - Trade lists
- `POST /api/trading-bot/demo-trade` - Create pending demo trade
- `POST /api/trading-bot/demo/simulate-closed` - Create closed trade for learning

### Learning Dashboard
- `GET /api/learning/strategy-stats` - Aggregated per-strategy performance
- `POST /api/learning/analyze` - Trigger AI analysis (~15s)
- `GET /api/learning/recommendations` - Pending recommendations
- `POST /api/learning/recommendations/{rec_id}` - Apply/dismiss recommendation
- `GET /api/learning/tuning-history` - Audit trail

### AI Assistant
- `POST /api/assistant/chat` - AI chat (bot-aware, mentions actual trades)

## MongoDB Collections
- `strategy_performance`: Per-trade performance records
- `tuning_recommendations`: AI/heuristic recommendations
- `tuning_history`: Applied changes audit trail
- `performance_analyses`: Saved AI analysis records
- `bot_trades`: Trade state (in-memory primary, DB backup)

## Prioritized Backlog

### P1 - Next Up
- Implement "Rubber Band Scanner" Preset
- AI Coach Proactive Warnings (real-time rule violation detection)

### P2 - Future
- Database Persistence for full Bot State (survive restarts)
- AI Assistant Backtesting Feature
- Keyboard Shortcuts Help Overlay
- Trade Journal (full implementation)
- Full User Authentication

## Known Limitations
- Bot state (open trades, daily stats) is in-memory; lost on restart
- Demo/simulate endpoints are primary testing tools outside market hours
- AI analysis response time ~10-15 seconds
