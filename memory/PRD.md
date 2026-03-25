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
16. **P0 FIX: WebSocket Training Commands (Mar 25, 2026)** — Training bypasses HTTP, goes through WebSocket
17. **Bug Fix: System Status Indicators (Mar 25, 2026)** — Fixed safeGet returning axios response, checked .ok (fetch-only property)
18. **Bug Fix: Template Literals (Mar 25, 2026)** — Fixed 11 instances of single-quote template literals across 5 files
19. **Bug Fix: safeGet/safePost (Mar 25, 2026)** — Fixed 15+ components using .ok/.json() on axios responses
20. **API Layer Cleanup (Mar 25, 2026)** — Removed xhrPost, abortPolling, global fetch override. Simplified throttler from 2->4 concurrent.
21. **Phase 1+2: Setup Training Config System (Mar 25, 2026)** — Per-setup training configs with noise filtering
22. **Phase 3: 3-Class Prediction (Mar 25, 2026)** — Models predict UP/FLAT/DOWN instead of binary UP/DOWN
23. **Phase 4: Multi-Timeframe Training (Mar 25, 2026)** — COMPLETED & VERIFIED
    - Setup models now train across multiple bar sizes (e.g., '1 day' + '1 hour')
    - Forecast horizon auto-scales per bar size via `get_bar_horizon()`
    - SCALP verified: 9,646 samples from 2 bar sizes vs 4,574 from single (2.1x increase)
    - Config: `setup_training_config.py` defines `training_bar_sizes` per setup type
    - Model protection still works (new model must beat existing accuracy)

## Key Files
- `/app/backend/services/ai_modules/setup_training_config.py` — Per-setup training parameters (bar sizes, horizons, thresholds)
- `/app/backend/services/ai_modules/timeseries_service.py` — Training pipeline with multi-timeframe loop
- `/app/backend/services/ai_modules/timeseries_gbm.py` — LightGBM model wrapper (3-class support)
- `/app/backend/services/ai_modules/setup_pattern_detector.py` — Pattern detection per setup type
- `/app/backend/services/ai_modules/setup_features.py` — Setup-specific feature engineering
- `/app/backend/worker.py` — Background job processor
- `/app/frontend/src/utils/api.js` — Simplified API layer (5 exports)
- `/app/frontend/src/hooks/useWebSocket.js` — WebSocket hook with sendTrainCommand
- `/app/frontend/src/components/NIA/SetupModelsPanel.jsx` — Setup model cards UI

## Upcoming Tasks
- (P1) Backtesting Workflow Automation — auto-run backtests on new model
- (P3) Auto-Optimize AI Settings — sweep confidence thresholds/lookback windows
- (P3) API Route Profiling Dashboard — monitor API performance
- (P3) Compare Simulations Side-by-Side — compare equity curves

## Future Refactoring
- Shift ~44 active polling intervals to WebSocket-based updates

## Testing
- `/app/test_reports/iteration_107.json` (General Training Job Queue, 20/20 passed)
- `/app/test_reports/iteration_108.json` (WebSocket Training Commands, 8/9 passed)
- Phase 4 manually verified via worker logs (SCALP multi-timeframe: 2 bar sizes, 9646 samples, correct horizon scaling)
