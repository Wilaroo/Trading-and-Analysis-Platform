# TradeCommand - Trading and Analysis Platform

## Original Problem Statement
Build "TradeCommand," an advanced Trading and Analysis Platform with a highly intelligent AI assistant that serves as a trading coach. Features a fully autonomous trading bot with a mutual learning loop — AI and bot learn from and improve each other. UI streamlined into a tab-based layout for clean navigation.

## Tech Stack
- **Frontend**: React, TailwindCSS, Framer Motion, Lightweight Charts
- **Backend**: FastAPI, Python
- **Database**: MongoDB
- **AI**: Ollama (primary, local/free) -> Emergent LLM GPT-4o (fallback)
- **Integrations**: Alpaca (paper trading), Finnhub, IB, yfinance

## Architecture (3-Tab Layout - Consolidated Feb 2026)
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
│   │   ├── ai_assistant_service.py      # Dual LLM: Ollama primary, Emergent fallback
│   │   ├── alpaca_service.py
│   │   └── background_scanner.py
│   └── server.py                        # Includes GET /api/llm/status
└── frontend/
    └── src/
        ├── hooks/
        │   └── useCommandCenterData.js
        ├── components/
        │   ├── layout/
        │   │   ├── HeaderBar.jsx
        │   │   └── QuickStatsRow.jsx
        │   ├── tabs/
        │   │   ├── TradingTab.jsx         # Signals only (TradeSignals)
        │   │   ├── AICoachTab.jsx         # Unified: Bot + AI Chat + Market Intel
        │   │   └── AnalyticsTab.jsx
        │   ├── MarketIntelPanel.jsx       # Time-of-day reports + auto-trigger
        │   ├── TradingBotPanel.jsx
        │   ├── LearningDashboard.jsx
        │   ├── AICommandPanel.jsx
        │   └── TradeSignals.jsx
        └── pages/
            └── CommandCenterPage.js
```

## Tab Structure
| Tab | Label | Contents |
|-----|-------|----------|
| Signals | Lightning icon | Trade Signals feed |
| Command | Target icon | Trading Bot + AI Chat + Market Intel (unified hub) |
| Analytics | Chart icon | Learning Dashboard + Scanner |

## Ollama Integration (Feb 2026)
- **Primary provider**: Ollama via ngrok tunnel (llama3:8b)
- **Fallback**: Emergent LLM (GPT-4o) — auto-switches if Ollama unreachable
- **Available models**: llama3:8b, qwen2.5:7b, gemma3:4b
- **Config**: `OLLAMA_URL` and `OLLAMA_MODEL` in backend/.env
- **Status endpoint**: `GET /api/llm/status` — shows provider, connectivity, available models
- **Architecture**: `_call_llm()` tries Ollama first → catches errors → falls back to Emergent
- **Note**: ngrok free tier URL changes on restart — update `OLLAMA_URL` in .env when it changes

## Completed Features
1. Core platform: AI assistant, background scanner, SSE alerts
2. Autonomous trading bot with strategy configs
3. AI <-> Bot integration: mutual awareness
4. Mutual Learning Loop: performance tracking, AI analysis, auto-tuning
5. Performance optimization: caching, batching, tab-aware polling
6. UI Consolidation: clean 3-tab layout, header dropdowns
7. CommandCenterPage Refactoring: modular components
8. Market Intelligence & Strategy Playbook: 5 daily auto-reports
9. Morning Routine Auto-Trigger
10. Bot + AI Unification: merged into Command tab
11. **Ollama Integration: local LLM as primary, Emergent as fallback**

## Prioritized Backlog

### P1 - Next Up
- Rubber Band Scanner Preset
- AI Coach Proactive Warnings

### P2 - Future
- Full bot state persistence in MongoDB
- AI Backtesting Feature
- Keyboard Shortcuts, Trade Journal, Full Auth
- Weekly performance digest
