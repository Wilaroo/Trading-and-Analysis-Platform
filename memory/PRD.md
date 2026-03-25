# SentCom AI Trading Platform - Product Requirements

## Overview
AI-powered trading platform with autonomous learning, backtesting, and market analysis capabilities.

## Architecture
- **Backend**: FastAPI (Python) + MongoDB + Worker process (supervisor-managed)
- **Frontend**: React + Shadcn UI
- **3rd Party**: Interactive Brokers, Ollama Pro, Alpaca, Finnhub, LightGBM, PyTorch, ChromaDB

## Completed Features
1. Robust Data Pipeline (stocks, options, futures, COT, insider)
2. Startup Status Dashboard
3. Resource Prioritization ("Focus Mode") & Job Queue
4. Persistent Chat History & Market Regime Detection
5. Shadow Learning (AI paper decisions alongside real trades)
6. AI Comparison Backtesting (setup-only, AI+setup, AI-only modes)
7. Best Model Protection (new models must beat existing)
8. P0 Backend Performance Fix (asyncio event loop unblocking)
9. Worker-Based Job Queue for ALL Training
10. WebSocket Training Commands (bypasses HTTP)
11. API Layer Cleanup (simplified throttler, removed legacy code)
12. Phase 1-3: Setup Training Config, Noise Filtering, 3-Class Prediction (UP/FLAT/DOWN)
13. **Phase 5: Profile-Based Setup Models (Mar 25, 2026)** — COMPLETED
    - Each (setup_type, bar_size) gets its own model with native forecast horizon
    - 17 total profiles across 10 setup types
    - Intraday models on 1min/5min, swing models on 1day/1hour
    - DB compound key: (setup_type, bar_size)
14. **NIA UI Consolidation (Mar 25, 2026)** — COMPLETED
    - Reduced from 11 panels to 4 collapsible sections
    - AI Command Center (Setup Models tab + Live Performance tab)
    - Data & Backtesting (Data Collection + Market Scanner + Backtesting)
    - Strategy & Performance (Pipeline + Report Card)
    - Enhanced QuickStatsBar with data source visibility, model counts, detail

## Profile Architecture
```
SCALP → [1min (h=30, 30min), 5min (h=12, 1hr)]
ORB → [5min (h=12, 1hr)]
GAP_AND_GO → [5min (h=12, 1hr)]
VWAP → [5min (h=12, 1hr)]
BREAKOUT → [5min (h=24, 2hr), 1day (h=5, 5d)]
RANGE → [5min (h=36, 3hr), 1day (h=5, 5d)]
MEAN_REVERSION → [5min (h=36, 3hr), 1day (h=5, 5d)]
REVERSAL → [5min (h=60, 5hr), 1day (h=5, 5d)]
TREND_CONTINUATION → [5min (h=78, fullday), 1day (h=7, 1wk)]
MOMENTUM → [1hour (h=14, 2d), 1day (h=7, 1wk)]
```

## NIA Layout (v4.0)
```
QuickStatsBar — Data source, bars stored, collections, profiles trained, backtests, promotions, connectors
AI Command Center — [Setup Models | Live Performance]
Data & Backtesting — [Data Collection | Market Scanner | Backtesting]
Strategy & Performance — [Pipeline | Report Card]
```

## Key Files
- `/app/backend/services/ai_modules/setup_training_config.py` — Profile-based training configs
- `/app/backend/services/ai_modules/timeseries_service.py` — Training pipeline (profile-aware)
- `/app/backend/worker.py` — Background job processor (profile-aware)
- `/app/backend/server.py` — WebSocket handler (train_setup, train_setup_all)
- `/app/frontend/src/components/NIA/index.jsx` — NIA main (4-section layout)
- `/app/frontend/src/components/NIA/SetupModelsPanel.jsx` — Profile-aware setup model cards
- `/app/frontend/src/components/NIA/AICommandCenter.jsx` — AI section wrapper
- `/app/frontend/src/components/NIA/DataBacktestingPanel.jsx` — Data section wrapper
- `/app/frontend/src/components/NIA/StrategyPerformancePanel.jsx` — Strategy section wrapper
- `/app/frontend/src/components/NIA/QuickStatsBar.jsx` — Enhanced stats bar

## Upcoming Tasks (User-Confirmed Priorities)
1. (P1) **Richer Trade Tagging** — Pattern variations (VWAP_BOUNCE vs rubberband vs consolidation break), entry context, MFE/MAE tracking
2. (P1) **ADV-Filtered Training Symbols** — Use all symbols filtered by ADV volume (no low-volume for intraday)
3. (P1) **Deprecate General Model** — Replace with lightweight Market Regime indicator
4. (P2) Backtesting Workflow Automation
5. (P3) Auto-Optimize AI Settings
6. (P3) Compare Simulations Side-by-Side

## Future Refactoring
- Shift ~44 active polling intervals to WebSocket-based updates
- `predict_for_setup()` — select model by matching trade's bar_size to available profiles
