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
13. **Phase 5: Profile-Based Setup Models** — 17 profiles across 10 setup types
14. **NIA UI Consolidation** — 11 panels → 4 collapsible sections
15. **ADV Cache & Filtered Training** — 9,248 symbols from IB data, bar_size-based thresholds
16. **Market Regime Integration** — Layer 1 (6 SPY features in training), Layer 2 (confidence adjustment)
17. **Richer Trade Logging (Mar 25, 2026)** — COMPLETED
    - **MFE/MAE Tracking**: Dedicated `mfe_price`, `mfe_pct`, `mfe_r`, `mae_price`, `mae_pct`, `mae_r` fields on BotTrade. Tracked from moment of fill in position monitoring loop. Initialized at fill time, updated every price tick. R-multiples calculated relative to risk (entry-to-stop distance).
    - **Entry Context Capture**: `entry_context` dict field with 18+ data points: scanner signals, market regime, technical indicators (RSI, trend, VWAP), volume context (RVOL, ADV), time window classification (opening_auction → after_hours), AI prediction, strategy filter history.
    - **Pattern Variant**: `setup_variant` field stores granular SMB setup name (e.g., "spencer_scalp", "vwap_bounce") while `setup_type` keeps the broad AI category.
    - **Enhanced Journal Logging**: Entry records include setup_variant + entry_context. Exit records include MFE/MAE data (price, %, R-multiples) in both update and notes fields.
    - **Trade Restoration**: MFE/MAE and entry_context restored from DB on server restart.
    - **WebSocket/API**: All new fields included in `to_dict()` serialization, automatically surfaced in trade updates and API responses.
18. **Auto-Managed Focus Mode (Mar 25, 2026)** — COMPLETED
    - Training, backtesting, and data collection now auto-activate their respective focus modes
    - Worker auto-restores to LIVE mode when jobs complete (checks for pending jobs first)
    - Removed manual FocusModeSelector toggle from HeaderBar
    - Replaced with compact FocusModeBadge — invisible in LIVE mode, shows mode/progress/abort when active
    - Frontend syncs with backend every 5s for fast mode change detection
    - Priority matrix tuned: TRAINING zeroes IB streaming (not needed), COLLECTING zeroes bot scan
    - Wired: WS train handlers, backtest background jobs, data collection endpoints, cancel endpoints
19. **Automated Train→Validate→Promote Pipeline (Mar 25, 2026)** — COMPLETED
    - After training, automatically backtests the new model on top 20 liquid symbols (180 days)
    - Compares against stored baseline using composite score: Sharpe (40%), Win Rate (30%), Return (20%), AI Edge (10%)
    - Promotes if better (or first model), rolls back to backup if worse
    - Backs up current model before every training run
    - DB collections: `model_baselines` (current benchmarks), `model_validations` (audit trail), `setup_type_models_backup` (rollback)
    - API: `GET /api/ai-modules/validation/history`, `GET /api/ai-modules/validation/baselines`
    - Full pipeline: Click Train → TRAINING focus mode → Train model → Backup → Validate via backtest → Promote/Reject → Restore LIVE

## Key Data Models

### BotTrade (new fields)
```python
setup_variant: str           # "vwap_bounce", "spencer_scalp", etc.
entry_context: Dict          # 18+ keys capturing entry conditions
mfe_price: float             # Best favorable price since fill
mfe_pct: float               # MFE as % from entry
mfe_r: float                 # MFE in R-multiples
mae_price: float             # Worst adverse price since fill
mae_pct: float               # MAE as % from entry (negative)
mae_r: float                 # MAE in R-multiples (negative)
```

### Entry Context Structure
```python
{
    "scanner_setup_type": "hitchhiker",
    "strategy_name": "hitchhiker",
    "score": 85,
    "trigger_probability": 0.7,
    "tape_confirmation": true,
    "market_regime": "RISK_ON",
    "regime_score": 72.0,
    "filter_action": "PROCEED",
    "filter_win_rate": 0.62,
    "atr": 5.5,
    "atr_percent": 1.8,
    "rvol": 2.3,
    "technicals": {"trend": "uptrend", "rsi": 65, ...},
    "time_window": "morning_momentum",
    "entry_time_et": "10:15:32",
}
```

## ADV Threshold Architecture
```
Bar Size    | ADV Minimum | Qualifying Symbols
------------|-------------|-------------------
1 min       | 500,000     | ~2,618
5 mins      | 500,000     | ~2,673
1 hour      | 500,000     | ~2,675
1 day       | 100,000     | ~3,883
1 week      | 50,000      | ~4,611
```

## Profile Architecture
```
SCALP → [1min (h=30), 5min (h=12)]
ORB → [5min (h=12)]
GAP_AND_GO → [5min (h=12)]
VWAP → [5min (h=12)]
BREAKOUT → [5min (h=24), 1day (h=5)]
RANGE → [5min (h=36), 1day (h=5)]
MEAN_REVERSION → [5min (h=36), 1day (h=5)]
REVERSAL → [5min (h=60), 1day (h=5)]
TREND_CONTINUATION → [5min (h=78), 1day (h=7)]
MOMENTUM → [1hour (h=14), 1day (h=7)]
```

## Key Files
- `/app/backend/services/trading_bot_service.py` — BotTrade dataclass + MFE/MAE tracking + entry context builder
- `/app/backend/services/ai_modules/timeseries_service.py` — Training pipeline (ADV-filtered, regime-aware)
- `/app/backend/services/ai_modules/regime_features.py` — Regime training features (Layer 1)
- `/app/backend/services/ai_modules/regime_confidence.py` — Regime confidence adjustment (Layer 2)
- `/app/backend/services/ai_modules/setup_training_config.py` — Profile configs + ADV thresholds
- `/app/backend/scripts/recalculate_adv_cache.py` — ADV cache recalculation
- `/app/backend/services/smb_integration.py` — 30+ granular setup configs (SETUP_REGISTRY)
- `/app/frontend/src/components/NIA/index.jsx` — NIA main (4-section layout)

## Upcoming Tasks
1. (P2) **MFE/MAE Scatter Chart per Setup Type** — Visualize which setups leave money on the table vs which shake you out
2. (P3) Auto-Optimize AI Settings — sweep confidence thresholds/lookback windows
3. (P3) Compare Simulations Side-by-Side
4. (P3) API Route Profiling Dashboard

## Future Refactoring
- Shift ~44 active polling intervals to WebSocket-based updates
- `predict_for_setup()` — select model by matching trade's bar_size to available profiles
