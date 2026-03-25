# SentCom AI Trading Platform — PRD

## Original Problem Statement
Build a sophisticated AI-powered trading platform with real-time market intelligence, automated trading capabilities, and advanced AI model training/validation.

## Current Session Enhancement
Implement a full 5-Phase Auto-Validation Pipeline that runs after AI model training, displaying results within each setup card and connecting validation data throughout the application.

## Architecture
```
/app
├── backend/
│   ├── scripts/
│   │   └── recalculate_adv_cache.py
│   ├── services/
│   │   ├── ai_modules/
│   │   │   ├── timeseries_service.py
│   │   │   ├── setup_training_config.py
│   │   │   ├── regime_features.py
│   │   │   ├── regime_confidence.py
│   │   │   └── post_training_validator.py    # UPDATED: Full 5-phase pipeline
│   │   ├── slow_learning/
│   │   │   └── advanced_backtest_engine.py   # Hosts all 5 backtest methods
│   │   ├── focus_mode_manager.py
│   │   └── trading_bot_service.py
│   ├── routers/
│   │   └── ai_modules.py                    # UPDATED: 4 validation endpoints
│   ├── server.py
│   └── worker.py                             # UPDATED: Wired 5-phase + batch validation
└── frontend/
    └── src/
        ├── components/
        │   ├── FocusModeBadge.jsx
        │   └── NIA/
        │       ├── SetupModelsPanel.jsx      # REWRITTEN: Full validation UI
        │       └── AICommandCenter.jsx
        └── contexts/
            └── FocusModeContext.jsx
```

## Completed Features

### Session 1 (Previous)
- ADV Cache Recalculation & API endpoints
- ADV-Filtered Training in timeseries_service
- Market Regime Integration (Layer 1: 6 features + Layer 2: Confidence dampening)
- Richer Trade Logging (MFE/MAE tracking)
- Auto-Managed Focus Mode (dynamic resource throttling)
- Train→Validate→Promote Pipeline (basic: AI comparison only)
- Maximized Training Data Configs

### Session 2 (Current) — Feb 25, 2026
- **Full 5-Phase Auto-Validation Pipeline** (DONE)
  - Phase 1: AI Comparison (setup-only vs AI+setup vs AI-only)
  - Phase 2: Monte Carlo (5K simulations, risk assessment)
  - Phase 3: Walk-Forward (robustness/overfitting check, top 3 symbols)
  - Phase 4: Multi-Strategy (compare all setup types head-to-head, batch only)
  - Phase 5: Market-Wide (scan 200 liquid symbols, batch only)
- **Smart pipeline ordering**: Per-profile (1-3) then batch (4-5)
- **Composite promotion decision**: AI edge + MC risk + WF efficiency + baseline comparison
- **Fixed _get_backtest_engine** in worker.py (was passing constructor args incorrectly)
- **4 API endpoints**: /validation/latest, /validation/history, /validation/batch-history, /validation/baselines
- **Richer SetupModelsPanel UI**: Per-profile validation badges, phase indicators, quick metrics, expandable details, batch validation panel
- **Testing**: 100% backend (10/10), 100% frontend — verified by testing agent

## API Endpoints
- `GET /api/ai-modules/validation/latest` — Latest validation per (setup_type, bar_size)
- `GET /api/ai-modules/validation/history` — Full validation history
- `GET /api/ai-modules/validation/batch-history` — Batch validation results (phases 4-5)
- `GET /api/ai-modules/validation/baselines` — Current model baselines
- `GET /api/ai-modules/timeseries/setups/status` — All setup types with profiles

## DB Collections
- `model_validations` — Per-profile validation records (phases 1-3)
- `batch_validations` — Batch-level results (phases 4-5)
- `model_baselines` — Current baseline metrics for promotion comparison
- `setup_type_models_backup` — Model snapshots for rollback on rejection

## Backlog

### P2 — Upcoming
- MFE/MAE Scatter Chart per setup type

### P3 — Future
- Auto-Optimize AI Settings (sweep confidence thresholds)
- Compare Simulations Side-by-Side (equity curves)
- API Route Profiling Dashboard
- Shift ~44 active polling intervals to WebSocket-based updates
- Refactor trading_bot_service.py (4,300+ lines → discrete modules)
