# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. Features a fully autonomous trading bot with a mutual learning loop — AI and bot learn from and improve each other. UI streamlined into a tab-based layout for clean navigation.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **Integrations**: Alpaca (paper trading), Finnhub, IB, Emergent LLM (GPT-4o), yfinance

## Architecture (3-Tab Layout)
```
/app/
├── backend/
│   ├── routers/
│   │   ├── trading_bot.py
│   │   ├── learning_dashboard.py
│   │   ├── market_intel.py              # Market Intel API + auto-trigger
│   │   ├── live_scanner.py
│   │   └── assistant.py
│   ├── services/
│   │   ├── trading_bot_service.py
│   │   ├── strategy_performance_service.py
│   │   ├── market_intel_service.py      # Market Intelligence & Strategy Playbook
│   │   ├── ai_assistant_service.py
│   │   ├── alpaca_service.py
│   │   └── background_scanner.py
│   └── server.py
└── frontend/
    └── src/
        ├── hooks/
        │   └── useCommandCenterData.js
        ├── components/
        │   ├── layout/
        │   │   ├── HeaderBar.jsx
        │   │   └── QuickStatsRow.jsx
        │   ├── tabs/
        │   │   ├── TradingTab.jsx
        │   │   ├── AICoachTab.jsx         # Uses MarketIntelPanel
        │   │   └── AnalyticsTab.jsx
        │   ├── shared/
        │   │   └── UIComponents.jsx
        │   ├── MarketIntelPanel.jsx       # Time-of-day Market Intelligence + Auto-trigger
        │   ├── TradingBotPanel.jsx
        │   ├── LearningDashboard.jsx
        │   ├── AICommandPanel.jsx
        │   └── TradeSignals.jsx
        └── pages/
            └── CommandCenterPage.js       # ~160 lines (refactored)
```

## Completed Features
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot: full lifecycle, risk mgmt, profit-taking, trailing stops
3. Strategy configs: 6 strategies, EOD auto-close, CRUD API, frontend editing
4. AI <-> Bot integration: AI evaluates trades, bot awareness in chat
5. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning, scheduled post-market
6. 3-tab UI: Trading | AI Coach | Analytics
7. Performance optimization: centralized caching, batch APIs, tab-aware polling
8. UI Consolidation: 6 alert panels merged into 2 clean systems
9. CommandCenterPage Refactoring: 1464-line monolith -> 7 modular components
10. Market Intelligence & Strategy Playbook: Time-of-day AI-generated reports
11. **Morning Routine Auto-Trigger**: Auto-generates appropriate report on app open

## Market Intelligence System
### Report Schedule (Eastern Time)
| Time | Type | Content |
|------|------|---------|
| 8:30 AM | Pre-Market Briefing | Overnight recap, earnings, upgrades/downgrades, strategy playbook, risk warnings |
| 10:30 AM | Early Market Report | First hour recap, key movers, bot activity, emerging setups |
| 2:00 PM | Midday Report | Day progress, P&L update, strategy scorecard, afternoon outlook |
| 2:30 PM | Power Hour Report | EOD setup, position review, momentum assessment, action items |
| 4:30 PM | Post-Market Wrap | Day summary, P&L recap, trade review, learning insights, tomorrow prep |

### Auto-Trigger
- On app open, `GET /api/market-intel/auto-trigger` checks current time window
- If no report exists for the current time slot, auto-generates it
- Shows "Preparing your morning briefing..." toast during generation
- Works weekdays only, from 6 AM ET onwards

### API Endpoints
- `GET /api/market-intel/current` - Most relevant report for current time
- `GET /api/market-intel/reports` - All today's reports
- `GET /api/market-intel/schedule` - Schedule with generation status
- `GET /api/market-intel/auto-trigger` - Check if auto-generation needed
- `POST /api/market-intel/generate/{type}` - Generate specific report

## Prioritized Backlog

### P1 - Next Up
- Rubber Band Scanner Preset
- AI Coach Proactive Warnings

### P2 - Future
- Full bot state persistence in MongoDB
- AI Backtesting Feature
- Keyboard Shortcuts, Trade Journal, Full Auth
- Weekly performance digest
