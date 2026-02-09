# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. The platform includes a fully autonomous trading bot integrated into the AI Command Center, capable of scanning for opportunities, evaluating trades, managing risk, calculating position sizes, and executing trades (both paper and live) based on user-defined strategies. The AI and bot must be deeply integrated — learning from and improving each other.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts (TradingView)
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **Integrations**: Alpaca (paper trading), Finnhub (fundamentals), IB (scanners), Emergent LLM (GPT), yfinance

## Core Architecture
```
/app/
├── backend/
│   ├── routers/ (trading_bot.py, live_scanner.py, assistant.py, etc.)
│   ├── services/ (trading_bot_service.py, trade_executor_service.py, ai_assistant_service.py, background_scanner.py)
│   └── server.py (wires AI ↔ Bot integration on startup)
└── frontend/
    └── src/
        ├── components/ (TradingBotPanel.jsx, AICommandPanel.jsx, LiveAlertsPanel.jsx)
        └── pages/ (CommandCenterPage.js)
```

## Completed Features

### Phase 1: Core Platform
- AI Assistant powered by TradingIntelligenceService with real-time data
- Background scanner with SSE-based real-time alerts
- Chart patterns, technical analysis, fundamental data services

### Phase 2: Autonomous Trading Bot
- Full trade lifecycle: opportunity evaluation, order execution (Alpaca), position tracking, trade closing
- Risk management: position sizing, max risk per trade, daily loss limits
- Bot modes: Autonomous, Confirmation, Paused
- Advanced features: profit-taking with multi-level scale-out, dynamic trailing stops, automatic stop-loss

### Phase 3: Strategy-Specific Configurations (Dec 2025)
- TradeTimeframe enum (scalp/intraday/swing/position), 6 pre-configured strategies
- EOD auto-close logic for scalp/intraday trades at 3:50 PM ET
- CRUD API endpoints for strategy configs (GET/PUT /api/trading-bot/strategy-configs)
- Frontend Strategy Configuration panel with inline editing
- Trade cards show timeframe badges and EOD Close indicators

### Phase 4: AI ↔ Bot Deep Integration (Dec 2025)
- **AI evaluates bot trades**: `evaluate_bot_opportunity()` reviews each trade before execution; can APPROVE, CAUTION, or REJECT
- **AI has full bot awareness**: `get_bot_context_for_ai()` injects bot state (pending/open/closed trades, P&L, strategy configs) into AI context when user asks bot-related questions
- **Bot Trades in AI Command Panel**: New section in `AICommandPanel.jsx` with:
  - Daily stats (trades count, W/L, P&L)
  - Pending/Open/Closed tabs showing all bot trades
  - Click any trade to ask AI for analysis
  - "Bot Status" quick action pill
  - Auto-refresh every 10 seconds
- **Service wiring**: `server.py` connects `assistant_service.set_trading_bot(trading_bot)` and `trading_bot._ai_assistant = assistant_service` on startup

## Key API Endpoints
- `POST /api/trading-bot/start|stop` - Bot control
- `GET /api/trading-bot/status` - Status with strategy_configs
- `GET /api/trading-bot/strategy-configs` - All strategy configs
- `PUT /api/trading-bot/strategy-configs/{strategy}` - Update strategy config
- `GET /api/trading-bot/trades/all` - All trades for AI Command Panel
- `GET /api/trading-bot/trades/pending|open|closed` - Trade lists
- `POST /api/trading-bot/demo-trade` - Create demo trade for testing
- `POST /api/trading-bot/evaluate-trade` - AI evaluates a trade
- `POST /api/assistant/chat` - AI chat (now bot-aware)
- `GET /api/live-scanner/stream-alerts` - SSE real-time alerts

## Prioritized Backlog

### P1 - Next Up
- Implement "Rubber Band Scanner" Preset
- AI Coach Proactive Warnings (real-time rule violation detection)
- Mutual Learning Loop (AI analyzes bot performance, bot adjusts strategy weights)

### P2 - Future
- Database Persistence for Bot State (survive restarts)
- AI Assistant Backtesting Feature
- Keyboard Shortcuts Help Overlay
- Trade Journal (full implementation)
- Full User Authentication

## Known Limitations
- Bot state (trades, P&L) is primarily in-memory; lost on restart
- Demo trade generator is main testing tool outside market hours
- AI responses for bot queries may vary slightly due to LLM response variability
