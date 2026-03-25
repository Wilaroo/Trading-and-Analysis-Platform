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
15. **ADV Cache Recalculation & Filtered Training (Mar 25, 2026)** — COMPLETED
    - Fixed `symbol_adv_cache`: replaced 12,283 legacy Alpaca entries with 9,248 entries from real IB daily bars
    - ADV thresholds: 500K+ intraday (1min/5min/1hr), 100K+ swing (1day), 50K+ position (1week)
    - Training pipeline filters by ADV before selecting symbols
    - Result: ~2,700 symbols for intraday, ~3,900 for swing, ~4,600 for position
    - API: `GET /api/ai-modules/adv/stats`, `POST /api/ai-modules/adv/recalculate`
16. **Market Regime Integration (Mar 25, 2026)** — COMPLETED
    - **Layer 1: Regime Training Features** — 6 SPY-derived features added to training pipeline:
      regime_spy_trend, regime_spy_rsi, regime_spy_momentum, regime_volatility,
      regime_vol_expansion, regime_breadth_proxy
    - RegimeFeatureProvider preloads SPY daily bars for historical date lookups during training
    - Models trained with regime features get 52→58 total features
    - **Layer 2: Regime-Aware Prediction Confidence** — After model predicts, confidence is
      adjusted based on current regime alignment with setup preferences:
      +15% boost for aligned regimes, -20% dampen for misaligned
    - Prediction API response now includes `regime_adjustment` field with reasoning
    - Files: `regime_features.py` (Layer 1), `regime_confidence.py` (Layer 2)

## ADV Threshold Architecture
```
Bar Size    | ADV Minimum | Trading Style          | Qualifying Symbols
------------|-------------|------------------------|-------------------
1 min       | 500,000     | Intraday/Scalp         | ~2,618
5 mins      | 500,000     | Intraday/Scalp         | ~2,673
1 hour      | 500,000     | Intraday (short swing)  | ~2,675
1 day       | 100,000     | Swing                  | ~3,883
1 week      | 50,000      | Position/Investment    | ~4,611
```

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

## Market Regime Integration
```
Layer 1 — Training Features (6 SPY-derived):
  regime_spy_trend       — SPY vs 20-SMA (uptrend/downtrend)
  regime_spy_rsi         — SPY RSI normalized [-1, 1]
  regime_spy_momentum    — SPY 5-bar return
  regime_volatility      — SPY ATR as % of price
  regime_vol_expansion   — 5d ATR / 20d ATR ratio
  regime_breadth_proxy   — % of last 10 bars that closed up

Layer 2 — Prediction Confidence Adjustment:
  Setup-to-Regime preference mapping (e.g., BREAKOUT → confirmed_up)
  Aligned: +15% confidence | Misaligned: -20% confidence
  Uses both MarketRegimeEngine state AND scanner regime
```

## Key Files
- `/app/backend/services/ai_modules/setup_training_config.py` — Profile configs + ADV thresholds
- `/app/backend/services/ai_modules/timeseries_service.py` — Training pipeline (ADV-filtered, regime-aware)
- `/app/backend/services/ai_modules/regime_features.py` — Layer 1: Regime training features
- `/app/backend/services/ai_modules/regime_confidence.py` — Layer 2: Regime confidence adjustment
- `/app/backend/scripts/recalculate_adv_cache.py` — ADV cache recalculation
- `/app/backend/routers/ai_modules.py` — ADV stats/recalculate endpoints
- `/app/backend/worker.py` — Background job processor (profile-aware)
- `/app/backend/server.py` — WebSocket handler (train_setup, train_setup_all)
- `/app/frontend/src/components/NIA/index.jsx` — NIA main (4-section layout)
- `/app/frontend/src/components/NIA/SetupModelsPanel.jsx` — Profile-aware setup model cards

## Upcoming Tasks (User-Confirmed Priorities)
1. (P1) **Richer Trade Tagging** — Pattern variations (VWAP_BOUNCE vs rubberband), entry context, MFE/MAE tracking
2. (P1) Backtesting Workflow Automation — auto-backtest on new model training
3. (P3) Auto-Optimize AI Settings
4. (P3) Compare Simulations Side-by-Side

## Future Refactoring
- Shift ~44 active polling intervals to WebSocket-based updates
- `predict_for_setup()` — select model by matching trade's bar_size to available profiles
