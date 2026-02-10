# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. Features a fully autonomous trading bot with a mutual learning loop — AI and bot learn from and improve each other. UI streamlined into a tab-based layout for clean navigation.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **AI**: Ollama (primary, local/free) -> Emergent LLM GPT-4o (fallback)
- **Integrations**: Alpaca (paper trading), Finnhub (real-time news), IB, yfinance

## Architecture (3-Tab Layout)
```
/app/
├── backend/
│   ├── routers/
│   │   ├── trading_bot.py
│   │   ├── learning_dashboard.py
│   │   ├── market_intel.py
│   │   ├── live_scanner.py
│   │   └── assistant.py
│   ├── services/
│   │   ├── trading_bot_service.py
│   │   ├── strategy_performance_service.py
│   │   ├── market_intel_service.py      # Anti-hallucination + real Finnhub news
│   │   ├── ai_assistant_service.py      # Ollama primary, Emergent fallback
│   │   ├── alpaca_service.py
│   │   └── background_scanner.py
│   └── server.py
└── frontend/
    └── src/
        ├── hooks/useCommandCenterData.js
        ├── components/
        │   ├── layout/ (HeaderBar, QuickStatsRow)
        │   ├── tabs/ (TradingTab, AICoachTab, AnalyticsTab)
        │   ├── MarketIntelPanel.jsx
        │   ├── TradingBotPanel.jsx
        │   ├── LearningDashboard.jsx
        │   └── AICommandPanel.jsx
        └── pages/CommandCenterPage.js
```

## Completed Features
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot with strategy configs
3. AI <-> Bot integration: mutual awareness
4. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning
5. Performance optimization: caching, batching, tab-aware polling
6. UI Consolidation: 3-tab layout (Signals | Command | Analytics)
7. CommandCenterPage Refactoring: modular components
8. Market Intelligence: 5 daily auto-reports with real-time news
9. Morning Routine Auto-Trigger
10. Bot + AI Unification: merged into Command tab
11. Ollama Integration: local LLM primary, Emergent fallback
12. **Anti-Hallucination Fix**: Real Finnhub news, exact bot/strategy data, correct timestamps

## Prioritized Backlog

### P1 - Next Up
- Rubber Band Scanner Preset
- AI Coach Proactive Warnings

### P2 - Future
- Full bot state persistence in MongoDB
- AI Backtesting Feature
- Keyboard Shortcuts, Trade Journal, Full Auth
- Weekly performance digest
