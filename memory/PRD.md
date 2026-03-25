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
20. **API Layer Cleanup (Mar 25, 2026)** — Removed xhrPost, abortPolling, global fetch override. Simplified throttler from 2→4 concurrent.
21. **Phase 1+2: Setup Training Config System (Mar 25, 2026)** — COMPLETED
    - Per-setup training configs: forecast horizon, noise threshold, class weighting, boost rounds
    - Noise filtering: Discards samples with |return| < threshold (removes noise zone)
    - Per-setup forecast horizons: SCALP=2d, ORB=3d, BREAKOUT=5d, MOMENTUM=7d, etc.
    - Class weighting via LightGBM scale_pos_weight (directional bias per setup)
    - UI: Setup model cards show horizon + noise threshold
    - Config file: /app/backend/services/ai_modules/setup_training_config.py

## Key Files
- `/app/backend/services/ai_modules/setup_training_config.py` — Per-setup training parameters
- `/app/backend/services/ai_modules/timeseries_service.py` — Training pipeline (uses config)
- `/app/backend/services/ai_modules/timeseries_gbm.py` — LightGBM model wrapper
- `/app/backend/services/ai_modules/setup_pattern_detector.py` — Pattern detection per setup type
- `/app/backend/services/ai_modules/setup_features.py` — Setup-specific feature engineering
- `/app/frontend/src/utils/api.js` — Simplified API layer (5 exports)
- `/app/frontend/src/hooks/useWebSocket.js` — WebSocket hook with sendTrainCommand
- `/app/frontend/src/components/NIA/SetupModelsPanel.jsx` — Setup model cards UI

## Upcoming Tasks (Phase 3: 3-Class Prediction)
- Change model output from binary UP/DOWN to 3-class UP/FLAT/DOWN
- UP = return > threshold, DOWN = return < -threshold, FLAT = in between
- Update prediction pipeline to return class + confidence
- Update UI to show FLAT/NO TRADE as valid prediction
- Bot integration: FLAT = skip trade

## Future Tasks
- (Phase 4) More training data via intraday bars (1hr, 15min)
- (P1) Backtesting Workflow Automation — auto-run backtests on new model
- (P3) Auto-Optimize AI Settings
- (P3) API Route Profiling Dashboard
- (P3) Compare Simulations Side-by-Side

## Testing
- `/app/test_reports/iteration_107.json` (General Training Job Queue, 20/20 passed)
- `/app/test_reports/iteration_108.json` (WebSocket Training Commands, 8/9 passed)
