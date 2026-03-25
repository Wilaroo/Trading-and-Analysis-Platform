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
3. Comprehensive User Guide
4. Resource Prioritization ("Focus Mode") & Job Queue
5. Startup & Polling Optimization
6. Persistent Chat History
7. Market Regime Detection
8. Shadow Learning (AI makes paper decisions alongside real trades)
9. AI Comparison Backtesting (setup-only, AI+setup, AI-only modes)
10. Best Model Protection (new models must beat existing to be promoted)
11. P0 Backend Performance Fix (asyncio event loop unblocking)
12. P2 Refactoring (GPU for LightGBM, backend router refactoring, fetch migration, engine merge, code cleanup, server extraction)
13. Setup-Specific AI Models
14. Worker-Based Job Queue for ALL Training
15. Advanced Setup-Specific Models with Pattern Detection
16. P0 FIX: WebSocket Training Commands — Training bypasses HTTP
17. Bug Fixes: safeGet/safePost, Template Literals, System Status
18. API Layer Cleanup — Simplified throttler, removed legacy code
19. Phase 1+2: Setup Training Config System — Per-setup noise filtering
20. Phase 3: 3-Class Prediction — UP/FLAT/DOWN instead of binary
21. Phase 4: Multi-Timeframe Training (deprecated by Phase 5)
22. **Phase 5: Profile-Based Setup Models (Mar 25, 2026)** — COMPLETED
    - COMPLETE ARCHITECTURE REWRITE: Each (setup_type, bar_size) combo gets its own model
    - 17 total profiles across 10 setup types
    - Intraday models: SCALP(1min/5min), ORB(5min), GAP_AND_GO(5min), VWAP(5min)
    - Dual models: BREAKOUT(5min+1day), RANGE(5min+1day), MEAN_REVERSION(5min+1day), REVERSAL(5min+1day)
    - Swing models: TREND_CONTINUATION(5min+1day), MOMENTUM(1hour+1day)
    - Native forecast horizons: SCALP/1min=30min, SCALP/5min=1hr, RANGE/5min=3hr, REVERSAL/5min=5hr, TREND_CONT/5min=fullday
    - DB compound key: (setup_type, bar_size)
    - Model naming: {setup}_{slug}_predictor (e.g., scalp_5min_predictor)
    - Verified: SCALP/5min → 60.4% accuracy, 5,771 samples

## Profile Architecture
```
setup_training_config.py defines SETUP_TRAINING_PROFILES:
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

## Key Files
- `/app/backend/services/ai_modules/setup_training_config.py` — Profile-based training configs
- `/app/backend/services/ai_modules/timeseries_service.py` — Training pipeline (profile-aware)
- `/app/backend/services/ai_modules/timeseries_gbm.py` — LightGBM model wrapper
- `/app/backend/worker.py` — Background job processor (profile-aware)
- `/app/backend/routers/ai_modules.py` — API endpoints (bar_size optional in train request)

## Upcoming Tasks
- (P1) Backtesting Workflow Automation — auto-run backtests on new model
- (P2) Update Frontend SetupModelsPanel to display profile-based status (multiple bars per setup)
- (P3) Auto-Optimize AI Settings — sweep confidence thresholds/lookback windows
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations Side-by-Side

## Future Refactoring
- Shift ~44 active polling intervals to WebSocket-based updates
- predict_for_setup() — select model by matching trade's bar_size to available profiles

## Testing
- `/app/test_reports/iteration_107.json` (General Training, 20/20)
- `/app/test_reports/iteration_108.json` (WebSocket Training, 8/9)
- Phase 5 verified: SCALP → 2 profiles (1min: 50.5%, 5min: 60.4%), worker logs confirmed, status API shows 17 profiles
