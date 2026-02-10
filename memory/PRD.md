# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. Features a fully autonomous trading bot with a mutual learning loop — AI and bot learn from and improve each other. UI streamlined into a tab-based layout for clean navigation.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **Integrations**: Alpaca (paper trading), Finnhub, IB, Emergent LLM (GPT), yfinance

## Architecture (3-Tab Layout - Refactored Feb 2026)
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
        ├── hooks/
        │   └── useCommandCenterData.js   # All state + data fetching (extracted)
        ├── components/
        │   ├── layout/
        │   │   ├── HeaderBar.jsx          # Search, connections, system health
        │   │   └── QuickStatsRow.jsx      # 6 stat cards with dropdowns
        │   ├── tabs/
        │   │   ├── TradingTab.jsx         # TradeSignals + TradingBotPanel
        │   │   ├── AICoachTab.jsx         # AICommandPanel + Market Intel
        │   │   └── AnalyticsTab.jsx       # LearningDashboard + Scanner
        │   ├── shared/
        │   │   └── UIComponents.jsx       # Card, Badge, SectionHeader
        │   ├── TradingBotPanel.jsx        # Bot control (20s polling)
        │   ├── LearningDashboard.jsx      # Strategy perf (60s polling)
        │   ├── AICommandPanel.jsx         # AI chat + Bot Trades (30s polling)
        │   └── TradeSignals.jsx           # Trade signals feed
        └── pages/
            └── CommandCenterPage.js       # Thin orchestrator (~165 lines)
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
4. AI <-> Bot integration: AI evaluates trades, bot awareness in chat, Bot Trades in AI panel
5. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning, scheduled post-market
6. 3-tab UI: Trading | AI Coach | Analytics with expandable stat card dropdowns
7. Performance optimization: centralized caching, batch APIs, tab-aware polling
8. UI Consolidation: Merged 6 alert panels into 2 clean systems (TradeSignals + header dropdowns)
9. **CommandCenterPage Refactoring (Feb 2026)**: Split 1464-line monolith into 7 modular components

## Refactoring Summary (Feb 2026)
| File | Lines | Purpose |
|------|-------|---------|
| CommandCenterPage.js | 165 | Thin orchestrator |
| useCommandCenterData.js | ~250 | All state + data fetching hook |
| HeaderBar.jsx | ~200 | Search, connections, system health |
| QuickStatsRow.jsx | ~180 | 6 stat cards with dropdowns |
| TradingTab.jsx | ~30 | TradeSignals + TradingBotPanel |
| AICoachTab.jsx | ~74 | AICommandPanel + Market Intel |
| AnalyticsTab.jsx | ~82 | LearningDashboard + Scanner |
| UIComponents.jsx | ~43 | Card, Badge, SectionHeader |

## Prioritized Backlog

### P1 - Next Up
- Implement "Rubber Band Scanner" Preset
- AI Coach Proactive Warnings

### P2 - Future
- Full bot state persistence in MongoDB
- AI Backtesting Feature
- Keyboard Shortcuts, Trade Journal, Full Auth
- Weekly performance digest
