# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. The platform includes a fully autonomous trading bot integrated into the AI Command Center, capable of scanning for opportunities, evaluating trades, managing risk, calculating position sizes, and executing trades (both paper and live) based on user-defined strategies.

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
│   ├── services/ (trading_bot_service.py, trade_executor_service.py, background_scanner.py, etc.)
│   └── server.py
└── frontend/
    └── src/
        ├── components/ (TradingBotPanel.jsx, LiveAlertsPanel.jsx, etc.)
        └── pages/ (CommandCenterPage.js, etc.)
```

## Completed Features

### Phase 1: Core Platform
- AI Assistant powered by TradingIntelligenceService with real-time data
- Background scanner with SSE-based real-time alerts
- Chart patterns, technical analysis, fundamental data services

### Phase 2: Autonomous Trading Bot (Feature Complete)
- Full trade lifecycle: opportunity evaluation, order execution (Alpaca), position tracking, trade closing
- Risk management: position sizing, max risk per trade, daily loss limits
- Bot modes: Autonomous, Confirmation, Paused
- Advanced features: profit-taking with multi-level scale-out, dynamic trailing stops, automatic stop-loss

### Phase 3: Strategy-Specific Configurations (Completed Dec 2025)
- **TradeTimeframe enum**: scalp, intraday, swing, position
- **STRATEGY_CONFIG dict**: 6 pre-configured strategies with per-strategy trail_pct, scale_out_pcts, close_at_eod
- **EOD Close Logic**: Automatically closes scalp/intraday trades at 3:50 PM ET
- **API Endpoints**: GET/PUT /api/trading-bot/strategy-configs for CRUD operations
- **Frontend UI**: Strategy Configuration panel in settings with inline editing
- **Trade Cards**: Timeframe badges (SCALP/INTRADAY/SWING/POSITION) with color coding, EOD Close badge

## Key API Endpoints
- `POST /api/trading-bot/start|stop` - Bot control
- `GET /api/trading-bot/status` - Status with strategy_configs
- `GET /api/trading-bot/strategy-configs` - All strategy configs
- `PUT /api/trading-bot/strategy-configs/{strategy}` - Update strategy config
- `GET /api/trading-bot/trades/pending|open|closed` - Trade lists
- `POST /api/trading-bot/demo-trade` - Create demo trade for testing
- `GET /api/live-scanner/stream-alerts` - SSE real-time alerts

## Strategy Configurations
| Strategy | Timeframe | Trail % | EOD Close | Scale-Out |
|----------|-----------|---------|-----------|-----------|
| Rubber Band | Scalp | 1.0% | Yes | 50/30/20 |
| VWAP Bounce | Scalp | 1.0% | Yes | 50/30/20 |
| Breakout | Intraday | 1.5% | Yes | 33/33/34 |
| Squeeze | Swing | 2.5% | No | 25/25/50 |
| Trend Continuation | Swing | 2.5% | No | 25/25/50 |
| Position Trade | Position | 3.0% | No | 20/30/50 |

## Prioritized Backlog

### P1 - Next Up
- Implement "Rubber Band Scanner" Preset
- AI Coach Proactive Warnings (real-time rule violation detection)

### P2 - Future
- Database Persistence for Bot State (survive restarts)
- AI Assistant Backtesting Feature
- Keyboard Shortcuts Help Overlay
- Trade Journal (full implementation)
- Full User Authentication

## Known Limitations
- Bot state (trades, P&L) is primarily in-memory; lost on restart
- Demo trade generator is main testing tool outside market hours
