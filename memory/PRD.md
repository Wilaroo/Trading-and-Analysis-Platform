# SentCom AI Trading Platform - PRD

## Original Problem Statement
AI trading platform with 5-Phase Auto-Validation Pipeline, Data Inventory System, and maximum IB historical data collection via request chaining.

## Core Requirements
1. **5-Phase Auto-Validation UI** - Display AI Comparison, Monte Carlo, Walk-Forward, and baseline results per setup model (**DONE**)
2. **Data Inventory System** - Unified DB tracking data depth per symbol/timeframe vs expected minimums (**DONE**)
3. **Max Lookback Data Chaining** - Auto-chunk and chain IB API requests to fetch maximum historical data (**DONE**)
4. **Vendor Data Import** - Stream-import bulk ndjson/CSV OHLCV data from third-party vendors (**DONE**)

## Architecture
- **Frontend**: React + Shadcn/UI
- **Backend**: FastAPI + MongoDB Atlas (~39M+ historical bars)
- **Local Scripts**: IB Data Pusher (connects to IB Gateway), Vendor Data Importer

## What's Been Implemented

### Session 1 (Previous)
- 5-Phase Auto-Validation Pipeline UI in SetupModelsPanel.jsx
- Backend worker.py and ai_modules.py routing for batch validations
- Data inventory service (data_inventory_service.py) for gap analysis
- Cleared 15 stale collection jobs

### Session 2 (Current - Mar 25, 2026)
- **IB Request Chaining Logic**: `generate_chain_requests()` method in `ib_historical_collector.py`
  - Calculates chains needed per (symbol, bar_size) based on existing data depth
  - Steps backward in time using `end_date` field
  - Anti-redundancy: queries earliest bar dates to only chain for missing windows
  - Duration-to-calendar-days mapping for accurate step calculations

- **Queue Service `end_date` Support**: `historical_data_queue_service.py`
  - Added `end_date` param to `create_request()`
  - Updated dedup logic to include `end_date` for chain uniqueness

- **IB Pusher Updates**: `ib_data_pusher.py`
  - All 3 fetch methods read `end_date` from request
  - Pass to IB's `reqHistoricalData(endDateTime=end_date)`
  - Auto-reconnect with exponential backoff (survives Gateway restarts)
  - Auto-login via VBScript (types credentials after Gateway restart)
  - Connection health check every loop iteration

- **Async Storage Fix**: `routers/ib.py`
  - Historical data result endpoint now responds instantly
  - Bars written to Atlas in background via asyncio.create_task
  - Eliminates all timeout issues for both collector and trading pusher

- **New API Endpoints**:
  - `POST /api/ib-collector/max-lookback-collection` - Background max lookback with chaining
  - `GET /api/ib-collector/max-lookback-status` - Check background job status
  - `GET /api/ib-collector/chain-preview?symbol=X&bar_size=Y` - Preview chains for any symbol

- **Vendor Data Import Script**: `documents/scripts/import_vendor_data.py`
  - Streaming ndjson/CSV parser (constant memory)
  - Filters to qualifying symbols via ADV cache
  - Skips overlapping date ranges
  - bulk_write in batches of 5000
  - Progress tracking, resume support, dry-run mode

- **Standalone Chain Builder**: `build_chains.py`
  - Direct MongoDB queue insertion (bypasses API for large jobs)
  - Queued 111,192 chained requests for 4,611 symbols

- **Bat File Updates**:
  - `TradeCommand_AITraining.bat`: Added Step 9 (Collector), now 11 steps, health check shows queue progress
  - `StartTrading.bat` + `StartCollection.bat`: Pointed to localhost:8001
  - All scripts use local backend (no more Cloudflare timeouts)

- **Bug Fix**: `/api/ai-modules/timeseries/status` 500 error (unhashable list type)

### Session 3 (Mar 26, 2026)
- **Auto-Skip Dead Symbols**: `ib_data_pusher.py`
  - Tracks `_dead_symbols` set and `_symbol_nodata_count` dict
  - After 2 consecutive no-data/no-security-definition results, symbol is flagged dead
  - All future queue requests for dead symbols skip IB entirely (instant claim+skip)
  - Calls backend `POST /api/ib/historical-data/skip-symbol` to bulk-mark remaining pending requests
  - Status log now shows dead symbol count and list

- **Timezone Fix (IB Warning 2174)**: `ib_data_pusher.py`
  - New `_normalize_end_date()` method ensures all `end_date` values include explicit "UTC" suffix
  - Applied to `_collection_fetch_single`, `_collection_fetch_single_fast`, and `_fetch_and_return_historical_data`
  - Eliminates IB warning about implicit timezone before IB removes support

- **New API Endpoint**: `POST /api/ib/historical-data/skip-symbol`
  - Bulk-updates all pending requests for a symbol to `skipped_dead_symbol` status
  - Returns count of skipped requests
  - Pre-emptively skipped 107 SGN requests as first use

- **Multi-Instance Collection**: `ib_data_pusher.py` + `historical_data_queue_service.py` + `ib.py`
  - New CLI args: `--bar-sizes` (filter by timeframe), `--partition`/`--partition-total` (symbol hash partitioning)
  - Backend `/pending` endpoint accepts `bar_sizes`, `partition`, `partition_total` query params
  - Queue service `get_pending_requests()` filters by bar_size and symbol partition
  - Enables running 3 parallel collector instances with independent IB pacing limits

- **5-Min Duration Optimization**: `build_chains.py`
  - Tested and confirmed IB accepts `"3 M"` duration for 5-min bars (was `"1 M"`)
  - Re-queued all 5-min requests: 64K → 21K (67% reduction, ~8 chains/symbol instead of ~24)
  - Updated BAR_CONFIGS to use `"3 M"` for future runs

- **Swing-Tier 5-Min Trim**
  - Cancelled 31K pending 5-min requests for swing-tier symbols (100K-500K ADV)
  - Swing symbols retain 30 mins, 1 hour, 1 day coverage

- **Queue Reduction Summary**: 153K → 79K pending requests (48% reduction)

- **Bat File Update**: `TradeCommand_AITraining.bat`
  - Step 9 now launches 3 collector instances (client IDs 16/17/18)
  - Collector 1: Daily/Weekly (dark yellow), Collector 2: Hourly/15m/30m (light red), Collector 3: 5-min (aqua)
  - Updated terminal color guide and health check display

### Session 4.5 (Mar 26, 2026 - AI Confidence Gate & Cold-Start Fix)
- **Cold-Start Smart Filter Fix**: `trading_bot_service.py`
  - Added bootstrap mode: when wins+losses=0 but sample_size>=5, proceeds with 50% sizing instead of blocking
  - Fixes catch-22 where SentCom couldn't trade because no history, couldn't build history because not trading
  - Log shows: "Bootstrap mode for {symbol} {setup_type} - {N} alerts detected but 0 completed trades. Taking with 50% size to build history."

- **AI Confidence Gate (NEW)**: `services/ai_modules/confidence_gate.py`
  - Pre-trade intelligence layer SentCom checks before every trade
  - Evaluates: regime (rule-based + AI classification), model consensus, quality score
  - Returns GO/REDUCE/SKIP decision with confidence score (0-100) and position multiplier
  - Maintains trading mode: AGGRESSIVE / NORMAL / CAUTIOUS / DEFENSIVE
  - Decision log persisted to `confidence_gate_log` collection
  - Tracks daily stats: evaluated, taken, skipped, take rate

- **Confidence Gate API Endpoints**: `routers/ai_training.py`
  - `GET /api/ai-training/confidence-gate/summary` - Trading mode, today's stats, streak
  - `GET /api/ai-training/confidence-gate/decisions` - Recent decision log
  - `GET /api/ai-training/confidence-gate/stats` - Lifetime + daily statistics
  - `POST /api/ai-training/confidence-gate/evaluate` - Manual pre-trade check

- **SentCom Intelligence Panel (NEW)**: `NIA/SentComIntelligencePanel.jsx`
  - Shows SentCom's current trading mode (Aggressive/Normal/Cautious/Defensive) with reason
  - Today's decision stats: Evaluated, Taken, Skipped, Take Rate
  - Streak indicator (3+ consecutive GO/SKIP)
  - Recent decisions log with per-decision reasoning
  - Wired into NIA dashboard between Training Pipeline and Data & Backtesting

- **MarketRegimeWidget Enhancement**: Updated expand button text to "AI Details"

- **Confidence Gate Wired to Trading Bot**: `trading_bot_service.py` + `server.py`
  - Integrated into `_evaluate_opportunity()` between Smart Filter and Intelligence Gathering
  - Flow: Setup → Smart Filter → **Confidence Gate** → Position Sizing → Execute
  - Gate returns GO/REDUCE/SKIP based on regime (rule-based + AI) + model consensus + quality score
  - SKIP: Trade logged but not taken
  - REDUCE: Position multiplier applied to reduce size
  - GO: Full size proceeds
  - All decisions logged to `confidence_gate_log` collection and SentCom Intelligence Panel
  - Position multiplier applied in position sizing section alongside smart filter adjustment
  - Entry context (`entry_context.confidence_gate`) captures gate decision, score, reasoning for post-trade analysis
  - Trading mode (Aggressive/Normal/Cautious/Defensive) auto-updated based on regime conditions

- **Bug Fixes (Found by Testing Agent)**:
  - Fixed 3x MongoDB truth testing errors (`if mongo_db:` → `if mongo_db is not None:`) in ai_training.py
  - Fixed import error in model-inventory endpoint (wrong import names from setup_training_config)

### Session 4 (Mar 26, 2026 - AI Model Architecture Expansion)
- **Expanded Regime Features (6 → 24)**: `regime_features.py`
  - Added QQQ (growth/tech) and IWM (small-cap) features alongside SPY
  - 6 features per index: trend, RSI, momentum, volatility, vol expansion, breadth
  - 3 cross-correlation features: SPY-QQQ, SPY-IWM, QQQ-IWM return correlation
  - 3 rotation/divergence signals: growth vs market, small vs large, growth vs value
  - Backward compatible: old models get 0.0 for new features

- **Multi-Timeframe Context Features (NEW 8 features)**: `multi_timeframe_features.py`
  - Daily-level context injected into intraday models
  - Features: daily_trend, daily_rsi, daily_momentum, daily_volatility, daily_bb_position, daily_volume_trend, daily_higher_tf_align, daily_gap
  - Provides stock's own daily-level context (vs regime features which provide index-level context)
  - Integrated into training loop and prediction path

- **Volatility Prediction Model (NEW)**: `volatility_model.py`
  - Predicts HIGH_VOL vs LOW_VOL for next N bars
  - 6 vol-specific features: vol_rank_20, vol_rank_50, vol_acceleration, range_expansion, gap_frequency, volume_vol_corr
  - 7 models (one per timeframe) with per-timeframe forecast horizons
  - Critical for dynamic position sizing and stop distance calibration

- **Exit Timing Model (NEW)**: `exit_timing_model.py`
  - Predicts optimal holding period: QUICK (1-5 bars), MEDIUM (6-15), EXTENDED (16+)
  - 7 exit-specific features: mfe_10_pct, mae_10_pct, mfe_mae_ratio, streak_length, exhaustion_rsi, momentum_decay, volume_climax
  - 10 models (one per setup type) with configurable max horizons
  - Target: bars until Maximum Favorable Excursion (MFE) peak

- **Regime-Conditional Model Framework (NEW)**: `regime_conditional_model.py`
  - 4 market regimes: bull_trend, bear_trend, range_bound, high_vol
  - SPY-based regime classifier using SMA/RSI/momentum/ATR expansion
  - At prediction: detect regime → route to regime-specific model variant
  - Up to 92 regime-conditional model variants (23 base × 4 regimes)

- **Multi-Timeframe Ensemble / Meta-Learner (NEW)**: `ensemble_model.py`
  - Stacks daily + hourly + 5-min model predictions as input features
  - 14 meta-features: per-model prob_up/prob_down/confidence + agreement_count, avg_confidence, confidence_spread, direction_entropy, bull_vote_pct
  - 10 ensemble models (one per setup type)
  - Captures "all timeframes agree" signals for highest probability setups

- **Bulk Training Pipeline (NEW)**: `training_pipeline.py` + `routers/ai_training.py`
  - 5 API endpoints: POST /start, GET /status, POST /stop, GET /models, GET /data-readiness
  - Trains all model types in coordinated phases: generic → setup → volatility → exit → regime → ensemble
  - Progress tracking via training_pipeline_status collection
  - Accuracy-gated model promotion (new model must beat old to replace it)

## Key Technical Details

### Model Architecture Summary (Post-Session 4)
| Model Category | Count | Features Per Sample | Target |
|----------------|-------|--------------------| -------|
| Generic Directional | 7 | 78 (base 46 + regime 24 + MTF 8) | UP/DOWN binary |
| Setup-Specific | 16 | 83-86 (+ setup features) | UP/DOWN/FLAT 3-class |
| Volatility Prediction | 7 | 76 (base 46 + vol 6 + regime 24) | HIGH_VOL/LOW_VOL |
| Exit Timing | 10 | 53 (base 46 + exit 7) | QUICK/MEDIUM/EXTENDED |
| Sector-Relative | 3 | 56 (base 46 + sector 10) | OUTPERFORM/UNDERPERFORM |
| Gap Fill Probability | 3 | 55 (base 46 + gap 9) | GAP_FILL/GAP_CONTINUE |
| Risk-of-Ruin | 6 | 54 (base 46 + risk 8) | STOP_HIT/SURVIVED |
| Regime-Conditional | ~92 | Same as parent model | Same as parent model |
| Ensemble Meta-Learner | 10 | 14 (stacked predictions) | UP/DOWN/FLAT |
| **Total** | **~154** | | |

### Target Variable System
| Type | Description | Use Case |
|------|-------------|----------|
| classification_binary | UP (>0.5%) vs DOWN | Simple directional models |
| classification_3class | UP/FLAT/DOWN with noise filter | Setup-specific models |
| regression | Actual return magnitude | Information-rich; post-hoc threshold |
| r_multiple | Return / ATR (normalized) | Cross-volatility comparison |
| asymmetric | Regime-adjusted thresholds | Bull: easy longs; Bear: easy shorts |

### Regime-Aware Thresholds
| Regime | Long Threshold | Short Threshold | Rationale |
|--------|---------------|-----------------|-----------|
| Bull Trend | >0.3% | <-0.8% | Easy to go long, hard to short |
| Bear Trend | >0.8% | <-0.3% | Hard to go long, easy to short |
| Range Bound | >0.5% | <-0.5% | Symmetric |
| High Vol | >1.0% | <-1.0% | Wider to filter noise |

### IB Lookback Limits & Chaining
| Bar Size | Max Lookback | Duration/Request | Chains/Symbol |
|----------|-------------|-----------------|---------------|
| 1 min    | 180 days    | 1 W             | ~26           |
| 5 mins   | 730 days    | 1 M             | ~25           |
| 15 mins  | 730 days    | 3 M             | ~9            |
| 30 mins  | 730 days    | 6 M             | ~5            |
| 1 hour   | 1825 days   | 1 Y             | ~5            |
| 1 day    | 7300 days   | 8 Y             | ~3            |
| 1 week   | 7300 days   | 20 Y            | ~1            |

### Data Inventory Thresholds
- MIN_BACKTEST_BARS: 1min=3900, 5min=780, 15min=260, 30min=130, 1hr=65, 1day=252, 1wk=52
- Depth categories: Deep (10x min), Backtestable (>min), Moderate (50-100%), Shallow (<50%), Stub (<10%)

## Prioritized Backlog

### P0 - Active
- IB data collection at ~65.6% (136,730/208,517 completed, 249 failed)
- Feature engineering & model architecture complete — ready for training when collection finishes

### P1 - Next Up
- **Training Pipeline Execution**: Train all ~154 models on available 52.7M+ bars
  - Can start immediately with `POST /api/ai-training/start`
  - Retrain on complete dataset once collection reaches 100%
- User to purchase vendor 1-min data and run import script

### P2 - Upcoming
- Real-time collection dashboard (heatmap of data depth per symbol/bar_size)
- MFE/MAE Scatter Chart per setup type
- Auto-Optimize AI Settings (sweep confidence thresholds/lookback windows)

### P3 - Future
- Refactor active polling to WebSocket (~44 intervals)
- Refactor trading_bot_service.py (4,300+ lines → modules)

## Key Files
- `/app/backend/services/ib_historical_collector.py` - Chaining logic
- `/app/backend/services/data_inventory_service.py` - Gap analysis
- `/app/backend/services/historical_data_queue_service.py` - Queue with end_date
- `/app/backend/routers/ib_collector_router.py` - Collection endpoints
- `/app/backend/routers/ai_training.py` - Training pipeline API (NEW)
- `/app/backend/services/ai_modules/regime_features.py` - SPY+QQQ+IWM regime context (UPDATED)
- `/app/backend/services/ai_modules/multi_timeframe_features.py` - Daily context for intraday (NEW)
- `/app/backend/services/ai_modules/volatility_model.py` - Vol prediction features+targets (NEW)
- `/app/backend/services/ai_modules/exit_timing_model.py` - Exit timing features+targets (NEW)
- `/app/backend/services/ai_modules/regime_conditional_model.py` - Regime classifier+routing (NEW)
- `/app/backend/services/ai_modules/ensemble_model.py` - Meta-learner features (NEW)
- `/app/backend/services/ai_modules/training_pipeline.py` - Bulk training orchestrator (NEW)
- `/app/backend/services/ai_modules/sector_relative_model.py` - Sector-relative features & targets (NEW)
- `/app/backend/services/ai_modules/gap_fill_model.py` - Gap fill probability features & targets (NEW)
- `/app/backend/services/ai_modules/risk_of_ruin_model.py` - Risk-of-ruin features & targets (NEW)
- `/app/backend/services/ai_modules/advanced_targets.py` - Advanced target variable system (NEW)
- `/app/backend/services/ai_modules/confidence_gate.py` - Pre-trade confidence gate (NEW)
- `/app/frontend/src/components/NIA/SentComIntelligencePanel.jsx` - SentCom Intelligence UI (NEW)
- `/app/documents/scripts/ib_data_pusher.py` - Local IB fetcher (updated for end_date)
- `/app/documents/scripts/import_vendor_data.py` - Vendor bulk import
