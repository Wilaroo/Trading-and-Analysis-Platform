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
│   │   ├── alpaca_service.py                 # Optimized with caching
│   │   ├── realtime_technical_service.py     # Optimized cache TTL
│   │   └── background_scanner.py             # Optimized scan interval
│   └── server.py
└── frontend/
    └── src/
        ├── components/
        │   ├── TradingBotPanel.jsx       # Bot control (20s polling)
        │   ├── LearningDashboard.jsx     # Strategy perf (60s polling)
        │   ├── AICommandPanel.jsx        # AI chat + Bot Trades (30s polling)
        │   └── LiveAlertsPanel.jsx       # Real-time alerts (60s polling)
        └── pages/
            └── CommandCenterPage.js      # 3-tab layout, tab-aware polling
```

## Performance Optimization Summary (Dec 2025)
### Before → After
| Component | Before | After | Impact |
|-----------|--------|-------|--------|
| Alpaca quote cache | 5s TTL | 15s TTL | -67% quote API calls |
| Alpaca bars cache | None | 120s TTL | Eliminates repeat bar fetches |
| Technical snapshots | 30s TTL | 120s TTL | -75% technical API calls |
| Background scanner | 60s interval | 90s interval | -33% scan cycles |
| Bot scan loop | 30s interval | 60s interval | -50% bot scan cycles |
| stream_quotes | 10s, individual calls | 15s, batch API | -70% quote stream calls |
| TradingBotPanel poll | 10s | 20s | -50% frontend calls |
| Bot Trades poll | 10s | 30s | -67% frontend calls |
| Learning Dashboard | 30s | 60s | -50% frontend calls |
| System health | 30s | 60s | -50% frontend calls |
| Fast poll | 10s all tabs | 30s tab-aware | -80% with tab gating |
| **Total Alpaca API** | **~55/min** | **~15/min** | **-73% reduction** |

## Completed Features (All Phases)
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot: full lifecycle, risk mgmt, profit-taking, trailing stops
3. Strategy configs: 6 strategies, EOD auto-close, CRUD API, frontend editing
4. AI ↔ Bot integration: AI evaluates trades, bot awareness in chat, Bot Trades in AI panel
5. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning, scheduled post-market
6. 3-tab UI: Trading | AI Coach | Analytics with expandable stat card dropdowns
7. Performance optimization: centralized caching, batch APIs, tab-aware polling

## Prioritized Backlog

### P1 - Next Up
- Implement "Rubber Band Scanner" Preset
- AI Coach Proactive Warnings

### P2 - Future
- Full bot state persistence in MongoDB
- AI Backtesting Feature
- Keyboard Shortcuts, Trade Journal, Full Auth
- Weekly performance digest
