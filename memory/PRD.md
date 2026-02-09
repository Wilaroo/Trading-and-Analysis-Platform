# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. Features a fully autonomous trading bot with a mutual learning loop — AI and bot learn from and improve each other. UI streamlined into a tab-based layout for clean navigation.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **Integrations**: Alpaca (paper trading), Finnhub, IB, Emergent LLM (GPT), yfinance

## Architecture (3-Tab Layout)
```
/app/
├── backend/
│   ├── routers/
│   │   ├── trading_bot.py           # Bot control, demo trades, simulate-closed
│   │   ├── learning_dashboard.py    # Strategy stats, AI analysis, recommendations
│   │   ├── live_scanner.py          # SSE real-time alerts
│   │   └── assistant.py             # AI chat (bot + learning aware)
│   ├── services/
│   │   ├── trading_bot_service.py            # Core bot logic
│   │   ├── trade_executor_service.py         # Alpaca execution
│   │   ├── strategy_performance_service.py   # Learning loop + scheduler
│   │   ├── ai_assistant_service.py           # AI with bot + learning context
│   │   └── background_scanner.py             # Market scanning
│   └── server.py
└── frontend/
    └── src/
        ├── components/
        │   ├── TradingBotPanel.jsx       # Bot control
        │   ├── LearningDashboard.jsx     # Strategy perf + auto-tuning
        │   ├── AICommandPanel.jsx        # AI chat + Bot Trades
        │   └── LiveAlertsPanel.jsx       # Real-time alerts
        └── pages/
            └── CommandCenterPage.js      # 3-tab layout: Trading | AI Coach | Analytics
```

## Tab Layout
| Tab | Content |
|-----|---------|
| **Trading** | Live Trade Alerts + Trading Bot Panel (mode selector, active trades, P&L) |
| **AI Coach** | Holdings (left), AI Command Center with Bot Trades (center), Market Intel + Alerts (right) |
| **Analytics** | Learning Dashboard (strategy cards, AI recommendations, tuning history) + Scanner + Alerts |

## Completed Features (All Phases)
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot: full lifecycle, risk mgmt, profit-taking, trailing stops
3. Strategy configs: 6 strategies, EOD auto-close, CRUD API, frontend editing
4. AI ↔ Bot integration: AI evaluates trades, bot awareness in chat, Bot Trades in AI panel
5. Mutual Learning Loop: per-strategy performance tracking (MongoDB), AI analysis, heuristic recommendations, auto-tuning with safety guardrails, audit trail
6. Scheduled auto-analysis: 4:15 PM ET daily post-market
7. AI conversational access: "How are my strategies performing?" returns actual data
8. 3-tab UI restructure: Trading | AI Coach | Analytics

## Key API Endpoints
- `POST /api/trading-bot/start|stop` | `GET /api/trading-bot/status`
- `GET/PUT /api/trading-bot/strategy-configs/{strategy}`
- `GET /api/trading-bot/trades/all|pending|open|closed`
- `POST /api/trading-bot/demo-trade` | `POST /api/trading-bot/demo/simulate-closed`
- `GET /api/learning/strategy-stats` | `POST /api/learning/analyze`
- `GET /api/learning/recommendations` | `POST /api/learning/recommendations/{id}`
- `GET /api/learning/tuning-history`
- `POST /api/assistant/chat` (bot + learning aware)

## Prioritized Backlog

### P1 - Next Up
- Implement "Rubber Band Scanner" Preset
- AI Coach Proactive Warnings

### P2 - Future
- Database Persistence for full Bot State
- AI Backtesting Feature
- Keyboard Shortcuts Help Overlay
- Trade Journal
- Full User Authentication
