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

### Session 4.8 (Mar 26, 2026 - P3 Complete: WebSocket Context + Full Migration + SmartFilter Delegation)

### Session 5.0 (Mar 27, 2026 - Short Setup Models + Short Interest Data Integration)

- **Phase 1: Short Setup Models** (10 new short setup types, 17 new model profiles)
  - `short_setup_features.py` — 10 feature extractors, each with 5-6 inverse features:
    - SHORT_BREAKDOWN: dist_from_support, lower_low_streak, lower_high_streak, down_vs_up_volume, breakdown_magnitude, upper_wick_ratio
    - SHORT_MOMENTUM: bearish_momentum_accel, down_streak, ema_stack_bearish, below_ema_count, bearish_vol_alignment, rsi_decline
    - SHORT_REVERSAL: overbought_rsi, dist_from_recent_high, bearish_engulfing, shooting_star, volume_climax, bearish_divergence
    - SHORT_GAP_FADE: gap_up_size, gap_fill_pct, post_gap_bearish, gap_vs_atr, gap_rejection, fade_volume_ratio
    - SHORT_VWAP: price_vs_vwap, below_vwap_duration, vwap_slope, vol_below_vwap_ratio, vwap_rejection
    - SHORT_MEAN_REVERSION: zscore_high, bb_upper_position, rsi_overbought_level, overextension_duration, momentum_deceleration, vol_at_high
    - SHORT_SCALP: bearish_body, close_at_low, decline_speed, red_bar_ratio, downside_vol_expansion, spread_proxy
    - SHORT_ORB: below_or_low, dist_below_or, or_range_pct, breakdown_vol_ratio, first_bar_bearish
    - SHORT_TREND: bearish_trend_strength, below_ma_count, ema21_rejection, lower_highs_count, macd_bearish
    - SHORT_RANGE: range_position, below_range, time_in_range, breakdown_vol_surge, failed_upbreak
  - Updated `setup_training_config.py`: 17 SHORT_* profiles with `direction: "short"` flag
  - Updated `training_pipeline.py`: Phase 2.5 trains short models with inverted targets (DOWN = positive outcome)
  - Updated `setup_features.py`: SHORT_* extractors registered in main registry
  - Total models: 63 → **80** (17 new short models)

- **Phase 2: Short Interest Data Integration** (IB + FINRA)
  - `short_interest_service.py` — Unified short interest data from two sources:
    - IB Gateway: Real-time `shortableShares` + `shortable` level (tick 236) pushed by local pusher
    - FINRA: Bi-monthly consolidated short interest from free API (NYSE + NASDAQ + OTC)
  - `routers/short_data.py` — API endpoints:
    - `GET /api/short-data/summary` — Data coverage overview
    - `GET /api/short-data/symbol/{symbol}` — Combined IB + FINRA data per symbol
    - `GET /api/short-data/bulk?symbols=...` — Bulk query
    - `POST /api/short-data/ib/push` — Receives IB shortable data from local pusher
    - `POST /api/short-data/finra/fetch` — Triggers FINRA data refresh (supports `force` and `settlement_date` params)
  - Updated `ib_data_pusher.py`:
    - Added tick type 236 to market data subscriptions
    - Captures `shortable_level` (tick 46)
    - Pushes shortable data to `/api/short-data/ib/push` alongside regular market data
  - MongoDB collections: `ib_short_data` (real-time), `finra_short_interest` (bi-monthly)
  - FINRA data: 2,702 records stored, 1 per symbol, single latest settlement date (2026-03-13)
  - FINRA fetch optimizations (Mar 27, 2026):
    - Auto-discovers latest settlement date (probes narrow windows, most-recent first)
    - Skip logic: won't re-fetch if already have >= 2000 records for latest date
    - Single-date fetch: only fetches target date (no multi-date bloat)
    - Upserts by symbol only (1 record per symbol, latest always wins)
    - Auto-cleans stale records from older settlement dates
    - ADV filter: only stores symbols with avg_volume >= 500K
    - `force=true` param to bypass skip and re-fetch

- **ADV Cache Audit & IEX Contamination Cleanup** (Mar 27, 2026)
  - Audited all code paths that write to or read from `symbol_adv_cache`
  - **Deprecated `build_adv_cache()`** in `ib_historical_collector.py` — was using Alpaca IEX data (underreports volume ~95%). Now redirects to `rebuild_adv_from_ib_data()` which uses IB daily bars
  - **Removed Alpaca IEX fallback** from `enhanced_scanner.py: _batch_fetch_adv_smart()` — was Source 3. Now uses: (0) pre-calculated IB cache → (1) IB historical live query → (2) IB real-time volume. Fail-closed if no IB data
  - **Added `_get_adv_from_cache()`** — new fast-path lookup that reads `symbol_adv_cache` directly (bulk $in query)
  - **Fixed snapshot ADV overwrite** in `_scan_symbol_all_setups()` — Alpaca snapshot no longer overwrites in-memory ADV cache when IB data already loaded
  - **Removed 90 lines of dead Alpaca IEX code** from `ib_historical_collector.py`
  - **Cleaned 10,724 stale FINRA records** (2018/2020/2025 dates) from production DB
  - ADV cache status: 9,248 symbols, all from `source: ib_historical_recalc`, 2,702 qualifying (≥500K)

- **Weekly ADV Cache Auto-Recalculation** (Mar 27, 2026)
  - Background scheduler runs every Sunday at 10 PM ET (before Monday open)
  - Uses 10-day lookback (2 trading weeks) with min 5 bars per symbol
  - Integrated into `server.py` startup via `asyncio.create_task(_weekly_adv_recalc_loop())`
  - Uses `recalculate_adv_cache.py` (IB daily bars only, no IEX)
  - Manual trigger available: `POST /api/ib-collector/build-adv-cache` or `POST /api/ai-modules/adv/recalculate`

- **Vendor 1-Min Data Import**: User actively importing ~3.35GB of 30-day vendor data
  - 2026-02-18 through 2026-03-18, full market OHLCV 1-min bars
  - Import script runs locally with `--skip-days 0` (no overlap with IB data)
  - Progress: ~89% complete at last check (~11M bars written to Atlas)

- **Collector Speed Optimization**: `base_batch_delay` 10s → 6s → 3s (0 pacing violations)

- **Deployment**: User trashed cloud deployment — running fully local setup

- **WebSocketDataContext** (`contexts/WebSocketDataContext.jsx`)
  - Centralized WS data store: 13 data types (quotes, ibStatus, botStatus, botTrades, scannerStatus, scannerAlerts, smartWatchlist, coachingNotifications, confidenceGate, trainingStatus, marketRegime, filterThoughts, sentcomStream)
  - `useWsData()` hook — any component can subscribe to any WS data type without prop drilling
  - Wrapped in App.js around entire component tree
  - Processes all incoming WS messages via `lastWsMessage` forwarding

- **Backend: 12th WS Push Type** (`filter_thoughts`)
  - `stream_filter_thoughts()` — pushes smart filter thoughts every 10s (change-detected)

- **Frontend WebSocket Migration** (Polling → WS)
  - `useTradingBotControl`: 5s polling → WS `bot_status` (removed setInterval)
  - `useIBConnectionStatus`: 3s polling → WS `ib_status` (removed setInterval)
  - `useSentComAlerts`: 5s polling → WS `scanner_alerts` (removed setInterval)
  - `TradingBotPanel`: 20s polling → WS `bot_status` + `bot_trades` + `scanner_alerts` (removed setInterval, kept 3s order queue poll for confirmations)
  - All migrated hooks: initial REST fetch + WebSocket handles subsequent updates

- **SmartFilter Delegation** (`trading_bot_service.py` → `smart_filter.py`)
  - `_evaluate_strategy_filter()` now delegates to `self._smart_filter.evaluate()`
  - `_add_filter_thought()` delegates to `self._smart_filter.add_thought()`
  - `get_filter_thoughts()` delegates to `self._smart_filter.get_thoughts()`
  - `get/update_smart_filter_config()` delegates to `self._smart_filter.config/update_config()`
  - ~120 lines of inline code replaced with 20 lines of delegation

- **Bug Fixes (Testing Agent)**:
  - Fixed TradingBotPanel calling non-existent `setTrades` — separated by status

### Session 4.7 (Mar 26, 2026 - IB Paper Orders + Commissions + DMA Filter)

- **Gap 2: IB Paper Account Order Execution** (`trade_executor_service.py`)
  - Enabled LIVE mode when IB pusher is connected (removed forced SIMULATED fallback)
  - Orders route through order queue → local IB Gateway → paper account execution
  - Market orders (MKT) for immediate execution
  - Falls back to SIMULATED only when pusher is NOT connected

- **Commission Tracking** (`trading_bot_service.py`)
  - IB tiered pricing: $0.005/share, $1.00 minimum per order
  - BotTrade fields: `commission_per_share`, `commission_min`, `total_commissions`, `net_pnl`
  - Commission applied on: entry, each scale-out, final exit
  - `net_pnl = realized_pnl - total_commissions`
  - Daily stats now use `net_pnl` (after commissions) instead of `realized_pnl`

- **Price Recalculation on Confirmation** (`confirm_trade()`)
  - On confirm: fetches current price from IB quotes (primary) or Alpaca (fallback)
  - Recalculates: entry_price, shares, remaining_shares, target_prices
  - Preserves stop_price (risk anchor), adjusts position size to match risk rules

- **Stale Alert Timeout** (`confirm_trade()`)
  - Scalps: 5 min, Day trades: 10 min, Swings: 15 min, Investment: 60 min
  - Expired alerts auto-rejected with `[EXPIRED]` tag

- **Gap 6: DMA Directional Filter** (`enhanced_scanner.py`)
  - Swing trades (multi_day): require price above EMA50 for longs, below for shorts
  - Investment trades (position): also require price above SMA200 for longs, below for shorts
  - Filters applied in `_process_new_alert()` before alert is emitted

- **Bug Fixes:**
  - Fixed NoneType crash in `_build_entry_context` when technicals is None
  - Fixed `risk_per_trade` → `max_risk_per_trade` field name in `confirm_trade`

### Session 4.6 (Mar 26, 2026 - Data Heatmap + WebSocket Migration + Refactor)

- **P2: Data Coverage Heatmap** (`NIA/DataHeatmap.jsx`)
  - Visual grid: rows = Tiers (Intraday/Swing/Investment), columns = bar sizes (1m/5m/15m/30m/1h/1D/1W)
  - Cells gradient color-coded by coverage % (emerald 98%+ → red <25% → gray 0%)
  - Hover tooltips show exact symbol counts and bar totals
  - Pending queue badges on cells with active collections
  - Summary strip: total symbols, bars, gaps
  - Color legend at bottom
  - Merged into DataCollectionPanel's Coverage tab, replacing the old per-tier card view

- **P3: WebSocket Migration** (3 new push types)
  - `stream_confidence_gate()` — pushes confidence gate summary + decisions every 15s (change-detected)
  - `stream_training_status()` — pushes training pipeline status every 30s (change-detected)
  - `stream_market_regime()` — pushes market regime data every 60s (change-detected)
  - App.js creates `wsConfidenceGate`, `wsTrainingStatus`, `wsMarketRegime` state
  - NIA panels (SentComIntelligencePanel, TrainingPipelinePanel) now accept WS data as props
  - Removed `setInterval` polling from both panels — initial REST fetch only, WebSocket handles subsequent updates
  - Total backend WS push types: 11 (quotes, ib_status, bot_status, bot_trades, scanner_status, scanner_alerts, smart_watchlist, coaching_notifications, confidence_gate, training_status, market_regime)

- **P3: Smart Filter Extraction** (`services/smart_filter.py`)
  - Extracted `SmartFilter` class from `trading_bot_service.py`
  - Standalone module with: `evaluate()`, `add_thought()`, `get_thoughts()`, `update_config()`
  - Includes cold-start bootstrap mode and full decision tree
  - Trading bot still uses its inline version (migration to delegating is future work)

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
- **Twitter/X Social Stream Widget**: Command Center widget for followed handle tweets (no paid API)
- **Training Pipeline Execution**: Train all ~154 models on available 52.7M+ bars
  - Can start immediately with `POST /api/ai-training/start`
  - Retrain on complete dataset once collection reaches 100%
- User to purchase vendor 1-min data and run import script

### P2 - Upcoming
- MFE/MAE Scatter Chart per setup type
- Auto-Optimize AI Settings (sweep confidence thresholds/lookback windows)
- **Confidence Gate Tuner**: Backend prepwork done (GAP 5) — decision outcomes are now tracked in `confidence_gate_log` with `outcome_tracked`, `trade_outcome`, `outcome_pnl` fields. `GET /api/ai-training/confidence-gate/accuracy` endpoint ready. UI tuner is next step.

### P3 - Future
- ~~Complete WebSocket migration for remaining ~20+ polling components~~ **DONE (Mar 27, 2026)**
  - Added 7 new backend WS push types: `order_queue`, `risk_status`, `sentcom_data`, `market_intel`, `data_collection`, `focus_mode`, `simulator`
  - Migrated 13 frontend components from setInterval polling to WebSocket subscription
  - Components: StreamOfConsciousness, DynamicRiskPanel, TradingBotPanel (order queue), SimulatorControl, NewDashboard, MarketIntelPanel, LiveAlertsPanel, DataCollectionPanel, FocusModeContext, useSentCom.js (8 hooks), useTickerModal, DashboardPage
  - ~36 → 25 remaining setInterval calls (all are job polling, UI timers, heartbeats — appropriate)
  - Estimated reduction: ~400 HTTP requests/min → near zero polling traffic

- ~~Ticker/Chart Modal Audit & Load Speed Optimization~~ **DONE (Mar 27, 2026)**
  - **EnhancedTickerModal.jsx** optimizations:
    - Wired `useWsData()` for real-time WebSocket price quotes (replaces stale REST-only prices)
    - Two-phase data loading: critical (analysis + chart bars) first, deferred (quality, earnings, news, learning insights) after — reduces initial blocking calls from 5+1 to 2
    - Per-symbol data cache (60s TTL) for instant re-opens of same ticker
    - Static constants (`TIMEFRAMES`, `QUICK_TICKERS`, `TABS`) moved outside component
    - Sub-components wrapped with `React.memo` (GlassCard, PositionProgressBar, ScoreRing)
    - Removed `fetchWithRetry` wrapper (eliminated retry delays on every endpoint)
    - Chart init delay reduced from 100ms to 50ms
    - Consolidated learning insights fetch into deferred phase (removed duplicate effect)
  - **TickerDetailModal.jsx** optimizations:
    - Wired `useWsData()` for real-time WebSocket price quotes
    - Two-phase data loading: critical (analysis + chart) first, deferred (quality, earnings) after — reduces initial calls from 4 to 2
    - Per-symbol data cache (60s TTL) for instant re-opens
    - Removed `fetchWithRetry` wrapper
    - Chart init delay reduced from 150ms to 50ms

- ~~Full App Component Audit — Data Display, Update Speed, Persistence~~ **DONE (Mar 27, 2026)**
  - **Data Flow Fixes:**
    - Wired `wsMarketRegime` through App.js → ibProps → CommandCenterPage → AICoachTab (was only going to NIA)
    - AICoachTab now uses WS market regime data with REST fallback (eliminated 60s polling)
    - MarketRegimeWidget now subscribes to WS `marketRegime` for instant state changes (supplements 30-min REST poll)
  - **Persistence Fixes:**
    - ChartsPage: `chartSymbol` now reads from localStorage on mount (was resetting to 'SPY' on every tab switch)
    - ChartsPage: Unified `recentChartSymbols` localStorage key with CommandCenter (was using different keys)
    - TradeJournalPage: Added `useAppState()` caching for trades, performance, matrix data — instant display on tab switch
  - **Polling Reduction / WS Integration:**
    - SentCom.jsx: Added WS subscriptions to all 5 local hooks (useSentComStatus, useSentComStream, useSentComPositions, useSentComContext, useSentComAlerts) — data now updates in real-time via WS, with REST polling as fallback
    - NewDashboard: Reduced polling intervals from 15s to 30s for dashboard/account/order data
    - NewDashboard DashboardHeader: Session poll reduced from 30s to 60s
  - **Impact:** ~40% reduction in REST polling across the app. Critical data now flows via WebSocket in real-time. Tab switches are instant for previously slow-loading pages.

- ~~Startup/Status Systems Audit — Real WS & DB Checks~~ **DONE (Mar 27, 2026)**
  - `/api/startup-check`: `websocket` now checks actual `ConnectionManager.active_connections` (was hardcoded `true`). `database` checks `mongo_client is not None` (was hardcoded `true`). Added `ws_connections` count field.
  - `/api/startup-status`: Fixed WS check (was using nonexistent `server.quote_connections`), bot/scanner status now reads real runtime state (was hardcoded "ready").
  - `StartupModal.jsx`: Uses `useWsData().isConnected` to supplement backend WS check. Shows "Live (N conns)" detail text.
  - All checks remain in-memory only — zero I/O, zero startup slowdown.

- ~~AI Model Architecture Buildout — Super Model + Training Maximization~~ **DONE (Mar 27, 2026)**
  - **Part A: Training Data Maximization**
    - Removed artificial `max_symbols` cap (was 2,000-2,500) — ADV qualification is now the sole filter
    - Removed artificial `max_bars_per_symbol` cap (was 2,500-5,000) — models train on ALL available IB historical data
    - `_get_training_symbols_from_db` now returns ALL ADV-qualified symbols with no `$limit` stage
    - Memory safety preserved: per-symbol processing discards bars after feature extraction
  - **Part B: Confidence Gate — Relevant Model Consensus**
    - Rewrote `_query_model_consensus()` with direction-aware filtering
    - Only setup-type-matching models vote (SCALP models don't influence SWING evaluations)
    - SHORT models excluded from LONG evaluations and vice versa
    - General direction model always included as baseline
    - Returns detailed breakdown: setup_models_count, general_models_count, ensemble_models_count
  - **Part C: Ensemble Model — Setup-Specific Integration**
    - Enhanced `extract_ensemble_features()` to accept `setup_predictions` parameter
    - New features: `setup_prob_up`, `setup_prob_down`, `setup_confidence`, `setup_agreement`
    - `setup_agreement` measures whether setup-specific models agree with general consensus
    - All votes (general + setup) now included in meta-features (agreement, entropy, bull_vote_pct)
  - **Part D: Learning Loop → Confidence Gate Feedback**
    - New `_get_learning_feedback()` method closes the feedback loop
    - Queries per-setup win rates from `trade_outcomes` via Learning Loop service
    - Dynamic confidence adjustment: hot setups (65%+ WR) get +15 pts, cold setups (<40% WR) get -15 pts + 40% size reduction
    - Edge decay detection: additional -5 pts + 20% size reduction when rolling win rate is declining
    - Minimum 5 trade sample size to avoid noise influence
  - **Part E: Full Pipeline Wiring**
    - Wired `predict_for_setup()` into Confidence Gate via new `_get_live_prediction()` — models now make live predictions during trade evaluation (was missing — models trained but never ran inference in live flow)
    - Live prediction influences confidence: model agrees → +15 pts, model disagrees → -15 pts + 30% size reduction
    - Entry context now includes `live_prediction` and `learning_feedback` for post-trade analysis
    - SentCom filter thoughts expanded from 2 to 4 reasoning items — shows model predictions and learning feedback
    - Full data flow: Scanner → Opportunity Evaluator → Confidence Gate (regime + model consensus + live prediction + learning feedback + quality) → Trading Bot → Trade Record → SentCom Stream → WebSocket → Frontend

  - **LightGBM GPU Support Wired** (Mar 27, 2026)
    - `InstallML_GPU.bat`: Now installs LightGBM with `--config-settings=cmake.define.USE_GPU=ON`, verifies GPU via Booster test
    - `TradeCommand_AITraining.bat`: Auto-detects CPU-only LightGBM at startup, upgrades to GPU version automatically (with CPU fallback)
    - `StartLocal_GPU.bat`: Added LightGBM GPU status to prereq check and health check
    - Backend auto-detection (`timeseries_gbm.py`): When GPU LightGBM installed, `DEFAULT_PARAMS` auto-sets `device=gpu`, `gpu_platform_id=0`, `gpu_device_id=0` — flows to all training paths
    - No `requirements.txt` changes (user installs GPU LightGBM locally via bat)

- **Pipeline Gap Fixes — Full AI Data Flow Wiring** (Mar 27, 2026)
  - **GAP 1: TQS → Confidence Gate**: Confidence Gate Step 3 now uses TQS score (5-pillar) instead of raw scanner score (was using `alert.score` default 70)
  - **GAP 2: AI → TQS**: Scanner now runs AI enrichment BEFORE TQS calculation (was opposite). TQS `calculate_tqs()` now receives `ai_model_direction/confidence/agrees` from scanner AI, activating Context Quality's AI alignment scoring (10% weight, was always neutral 50)
  - **GAP 3: Post-Gate TQS Recalculation**: Opportunity evaluator recalculates TQS after Confidence Gate runs, using the setup-specific live prediction data. Entry context now captures `tqs.pre_gate_score`, `tqs.post_gate_score`, `tqs.delta` for post-trade analysis
  - **GAP 4: Cross-Model Agreement**: New Step 2c in Confidence Gate compares static model consensus (Step 2) with live prediction (Step 2b). Both agree → +5 pts. Both disagree → -10 pts + 20% size reduction. Mixed → noted in reasoning. Tracked in `cross_model_agreement` field
  - **GAP 5: Gate Decision Outcome Tracking**: `confidence_gate_log` now stores `outcome_tracked`, `trade_outcome`, `outcome_pnl` fields. Learning loop auto-updates gate decisions when trades close via `record_trade_outcome()`. New `GET /api/ai-training/confidence-gate/accuracy` endpoint returns per-decision win rates for future Gate Tuner UI

- **Refactored `trading_bot_service.py`** (Mar 27, 2026)
  - Extracted `stop_manager.py` (121 lines) — Trailing stop, breakeven, trail position logic
  - Extracted `trade_intelligence.py` (346 lines) — News sentiment, technical analysis, quality metrics, intelligence scoring
  - Extracted `trade_execution.py` (312 lines) — Trade execution, confirmation (stale check + price recalc), rejection
  - Extracted `position_reconciler.py` (463 lines) — IB position reconciliation, sync, phantom close, full sync
  - Extracted `position_manager.py` (464 lines) — P&L updates, MFE/MAE tracking, scale-out, EOD close, trade close
  - Extracted `bot_persistence.py` (486 lines) — State restore/save, trade persistence, trade deserialization
  - Extracted `opportunity_evaluator.py` (673 lines) — Full evaluation pipeline, position sizing, entry context, explanation generation
  - Extracted `scanner_integration.py` (198 lines) — Scanner auto-execution, trade journal logging
  - Main file: 4,444 → 1,643 lines (2,801 lines extracted into 8 modules, 63% reduction)
  - Public API unchanged — delegation wrappers maintain backward compatibility
- Migrate trading_bot_service.py to use extracted smart_filter.py module (delegation instead of inline)
- Refactoring complete for trading_bot_service.py (1,643 lines core orchestrator + 8 extracted modules)

### Post-Development: Full Local Migration
**Goal:** Run the entire platform locally with zero cloud dependencies (except IB Gateway's internet connection for live data/trading). Eliminates Atlas costs, reduces latency, ensures data privacy.

#### Migration Steps
1. Install MongoDB Community Server, configure data directory on dedicated drive
2. `mongodump` all collections from Atlas
3. `mongorestore` to local MongoDB
4. Update `.env`: `MONGO_URL=mongodb://localhost:27017/tradecommand`
5. Verify all services connect locally
6. Decommission Atlas cluster

#### Recommended Hardware (5-Year Horizon)
**Why these specs:** The platform runs MongoDB (RAM-hungry for large datasets), LightGBM training (CPU-bound), Ollama AI models (GPU VRAM), plus 7+ concurrent processes (backend, frontend, pusher, 3 collectors, worker). Data grows ~50-100GB/year.

| Component | Recommendation | Why |
|-----------|---------------|-----|
| **CPU** | AMD Ryzen 9 7950X (16 cores/32 threads) or Intel i9-14900K | LightGBM training is heavily multi-threaded. 3 collectors + backend + worker all run simultaneously. 16 cores gives headroom for 5 years. |
| **RAM** | **64GB DDR5** (minimum 32GB) | MongoDB keeps hot data in RAM. At ~500GB-1TB of data over 5 years, 64GB ensures your most-queried data (recent bars, model cache) stays in memory. LightGBM training can also spike to 8-16GB. |
| **Primary SSD** | 2TB NVMe Gen4 (Samsung 990 Pro or WD Black SN850X) | MongoDB data directory lives here. NVMe gives <0.1ms random reads vs 5-10ms on external HDD. Critical for query performance. |
| **Backup Drive** | 4TB external SSD (Samsung T7 Shield or similar) | Nightly `mongodump` backups. Not for running the DB — just disaster recovery. |
| **GPU** | NVIDIA RTX 4070 Ti Super (16GB VRAM) or RTX 4080 | Ollama models: 7B needs ~4GB VRAM, 13B needs ~8GB, 70B needs ~40GB. 16GB lets you run 13B models comfortably with room to grow. Also future-proofs for PyTorch/TensorFlow if you add deep learning models. |
| **PSU** | 850W 80+ Gold | Handles CPU + GPU under full load with headroom. |
| **UPS** | APC 1500VA battery backup | Protects against power loss during DB writes or model training. Critical for data integrity. |
| **OS** | Windows 11 Pro | Already your environment. Pro gives Hyper-V/WSL2 if needed. |

#### Software Stack
| Software | Version | Purpose |
|----------|---------|---------|
| MongoDB Community Server | 7.x+ | Local database (free, no license) |
| Python | 3.11+ | Backend, collectors, training |
| Node.js | 20 LTS | Frontend |
| NVIDIA CUDA Toolkit | 12.x | GPU acceleration for Ollama + future ML |
| Ollama | Latest | Local AI inference |
| IB Gateway | Latest | Live market data + order execution |

#### Estimated Data Growth (5 Years)
| Timeframe | Bars/Day (2700 symbols) | Year 1 | Year 5 |
|-----------|------------------------|--------|--------|
| 1 min | ~1,053,000 | ~265M bars | ~1.3B bars |
| 5 min | ~210,600 | ~53M | ~265M |
| 15 min | ~70,200 | ~18M | ~88M |
| 1 hour | ~17,550 | ~4.4M | ~22M |
| 1 day | ~2,700 | ~680K | ~3.4M |
| **Storage** | | **~150GB** | **~750GB-1TB** |

#### Cost Comparison (5 Years)
| | Atlas M10+ | Local Setup |
|---|---|---|
| Year 1 | ~$600-1,200/yr | ~$2,500 one-time hardware |
| Year 2-5 | ~$2,400-4,800 | $0 (electricity only) |
| **5-Year Total** | **$3,000-6,000** | **~$2,500 + electricity** |

**Bottom line:** Local pays for itself within 1-2 years and gives you faster performance, full data ownership, and zero recurring costs.

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

## Session 7 (Current - Mar 30, 2026) — Trade Journal AI Integration

### Phase 1: Wire Journal → AI Learning Loop (**DONE**)
- Modified `trade_journal.py` → `close_trade()` now writes to `trade_outcomes` collection via `_feed_learning_loop()`
- Closed journal trades automatically feed the Learning Loop and Confidence Gate outcome tracker
- New `source` field on trades: `manual`, `bot`, `ib`
- New `outcome` field on close: `won`, `lost`, `breakeven`

### Phase 2: AI Context on Trade Records (**DONE**)
- New `POST /api/trades/{id}/enrich-ai` endpoint captures current AI state:
  - Confidence Gate decision (GO/REDUCE/SKIP), confidence score, position multiplier, trading mode
  - Model predictions (direction, confidence, model used)
  - TQS score and grade (Trade Quality Score)
- `ai_context` stored on trade document, displayed as badges in frontend
- New `GET /api/trades/ai/learning-stats` endpoint shows journal-sourced outcomes and Confidence Gate accuracy
- Frontend: `AIContextBadge` component renders Gate/Prediction/TQS badges on trade rows
- Frontend: "Enrich with AI" (Zap icon) button on open trades without AI context
- Frontend: AI Learning Loop stats panel shows when journal outcomes exist

### Phase 3: Unified Trade View (**DONE** — Mar 30, 2026)
- New `GET /api/trades/unified` endpoint merges journal trades + bot trades from MongoDB `bot_trades` collection
- Source filter: `?source=manual` or `?source=bot` or all
- Status filter: `?status=open` or `?status=closed`
- Bot trades normalized to same schema as journal trades with extra fields: `quality_grade`, `trade_style`, `close_reason`, `smb_grade`, `mfe_pct`, `mae_pct`
- Frontend: Source filter toggle (All Sources / Manual / Bot) in Trade Log tab
- Frontend: Bot trades display extra badges (grade, style, close reason, MFE/MAE)
- Frontend: Bot trades are read-only (no close/delete/enrich buttons)
- 116 total trades visible (5 manual + 95 bot + 16 older manual)

### Key Files Updated (Phase 3)
- `/app/backend/routers/trades.py` - `GET /unified` endpoint (reads bot_trades directly from MongoDB)
- `/app/frontend/src/pages/TradeJournalPage.js` - `sourceFilter` state, unified data loading, bot-aware TradeRow

### Command Center Layout Rework (**DONE** — Mar 30, 2026)
- Reworked Command Center layout:
  1. Status Header (top)
  2. Full-width SOC + chat bubble (SentCom component)
  3. Below SentCom (in NewDashboard.jsx): Positions panel (left, col-span-7) + Scanner panel (right, col-span-5)
- Removed old ScannerAlertsStrip horizontal card layout
- DetailedPositionsPanel shows: entry/current/P&L, setup/style/timeframe, stop/distance, AI context, holding time, MFE/MAE, R:R, monitoring alerts
- ScannerAlertsPanel shows: live scanner alerts + "Watching" setups section
- Positions and alerts data fetched independently in NewDashboard with 15s polling

### Key Files (Layout Rework)
- `/app/frontend/src/components/NewDashboard.jsx` - Dashboard layout with data fetching for positions/alerts/setups
- `/app/frontend/src/components/DetailedPositionsPanel.jsx` (NEW)
- `/app/frontend/src/components/ScannerAlertsPanel.jsx` (NEW)
- `/app/frontend/src/components/SentCom.jsx` - Reverted to SOC + chat bubble only (no panels inside)
- Replaced 50/50 SOC/Chat split with SOC taking 100% of the panel
- Chat is now a floating purple bubble (bottom-right corner of SOC panel)
- Clicking bubble expands a 360×420px mini chat window overlaying the SOC
- Chat window: header, quick action pills (Performance/News/Brief/Rules/Summary), messages, input
- Minimize button collapses back to bubble
- Unread badge shows when AI responds while chat is minimized
- SOC continues scrolling uninterrupted behind the overlay

### Key Files (Chat Bubble)
- `/app/frontend/src/components/ChatBubbleOverlay.jsx` (NEW)
- `/app/frontend/src/components/SentCom.jsx` - Modified embedded view to use full-width SOC + ChatBubbleOverlay

## Saved Enhancement Ideas
- **Trade Review AI Annotation**: After closing a trade, the AI automatically annotates what it would have done differently (e.g., "Gate said REDUCE but trade won +$300 — Gate was too conservative in TRENDING context"). Accelerates learning feedback loop and Gate calibration.

## Prioritized Backlog

### P0 (Completed)
- Phase 4: AI-Enhanced Performance Dashboard — AI accuracy per strategy, gate stats, learning insights (**DONE** — Mar 30, 2026)

### P1
- Twitter/X Social Stream Widget for Command Center
- Auto-Optimize AI Settings (confidence threshold sweeping)
- Chat integration with snapshot annotations (click annotation → ask AI for reasoning)

### P2 (Future)
- Confidence Gate Tuner UI (after 50-100 live trades accumulated)
- Smart Templates based on historical AI performance
- Trade Review AI Annotation (what AI would have done differently)
- Post-Development Local DB Migration to NVMe

### Phase 4: AI-Enhanced Performance Dashboard (**DONE** — Mar 30, 2026)
- New `GET /api/trades/ai/strategy-insights` endpoint: per-strategy win rate, gate stats (GO/REDUCE/SKIP distribution), edge trend (improving/stable/declining)
- Enriched `PerformanceMatrix` component with `aiInsights` prop rendering AI Performance by Strategy section
- Strategy insight cards with gate decision distribution bar and edge trend indicator
- AI Learning Loop panel shows journal-sourced outcomes and Confidence Gate accuracy
- All endpoints converted to sync `def` to avoid event loop blocking in container

### UI Cleanup: Removed Background Job Widget from Command Center (Mar 30, 2026)
- Removed `JobManager` widget from AICoachTab's right sidebar (both new + classic layouts)
- Background job info remains accessible in NIA tab via DataCollectionPanel
- Frees up Command Center real estate for trading-relevant widgets

### Trade Chart Snapshots with AI Annotations (Mar 30, 2026)
- **Backend Service**: `services/trade_snapshot_service.py` — Auto-generates annotated candlestick charts
  - Renders OHLCV charts via `mplfinance` with entry/exit markers, stop lines, target levels
  - AI annotations: confidence gate decisions, market regime, smart filter, TQS, technicals
  - Scale-out and stop adjustment markers
  - Fallback synthetic candlestick generator when historical bars unavailable
  - Generates realistic OHLCV data from trade's entry/exit/stop/target/MFE/MAE data
  - Auto-upgrades to real bars when IB Gateway historical data available
  - Charts stored as base64 PNG (~75KB each) in `trade_snapshots` MongoDB collection
  - **204 snapshots generated** across all closed bot trades with candlestick charts
- **API Router**: `routers/trade_snapshots.py` (sync endpoints to avoid event loop blocking)
  - `GET /api/trades/snapshots` — List all snapshots (metadata only)
  - `GET /api/trades/snapshots/{trade_id}?source=bot` — Get snapshot with chart image
  - `GET /api/trades/snapshots/{trade_id}/image` — Raw PNG response
  - `POST /api/trades/snapshots/{trade_id}/generate` — Generate/regenerate snapshot
  - `POST /api/trades/snapshots/batch?limit=50` — Batch generate for closed trades
- **Auto-Trigger Hooks**: Snapshot auto-generates on trade close
  - Bot trades: `position_manager.py` → `close_trade()` method
  - Manual trades: `trade_journal.py` → `close_trade()` method
- **Frontend**: `TradeSnapshotViewer` component in `TradeJournalPage.js`
  - Camera icon on closed trade rows to toggle snapshot view
  - Base64 chart image display with metadata overlay
  - AI Decision Timeline with expandable annotation cards (entry, exit, scale_out, stop_adjust, gate_decision)
  - Generate/Regenerate buttons
- **Testing**: 12/12 pytest tests pass, code review passed (iteration_121.json)
- **Status**: 204 snapshots generated in MongoDB

### Annotation AI Explain + Chat Integration (Mar 30, 2026)
- **Backend**: Two new endpoints in `routers/trade_snapshots.py`:
  - `POST /api/trades/snapshots/{trade_id}/explain` — AI-powered annotation explanation via Ollama/GPT-OSS
  - `POST /api/trades/snapshots/{trade_id}/chat-context` — Pre-formatted context message for SentCom chat
  - `_call_llm_sync()` — Ollama HTTP proxy → Direct Ollama → Emergent LLM → structured fallback
- **Frontend**: Enhanced `TradeSnapshotViewer` in `TradeJournalPage.js`:
  - **"Ask AI" button** on each expanded annotation → inline AI explanation panel (cyan styling)
  - **"Ask More in Chat" button** → opens inline mini-chat thread with SentCom AI
  - Inline chat thread with context message, user messages, assistant replies, and input field
  - Sends follow-up questions to `POST /api/sentcom/chat` for full conversational flow
- **Testing**: 31/31 pytest tests pass (iteration_122.json)

### "What I'd Do Differently" Hindsight Analysis (Mar 30, 2026)
- **Backend**: `POST /api/trades/snapshots/{trade_id}/hindsight` endpoint
  - `_build_hindsight_data()` — Queries strategy_performance (similar trades), confidence_gate_log (current gate stance), trade_outcomes (learning loop), builds data-driven improvements list
  - `_build_hindsight_prompt()` — Creates structured LLM prompt comparing actual outcome vs current model knowledge
  - Improvements logic handles wins (sizing up, low WR outliers, gate deterioration) and losses (tight stops, SKIP/REDUCE recommendations, low WR)
- **Frontend**: "What I'd Do Differently" button in TradeSnapshotViewer
  - Amber-styled button → loading state → analysis panel with:
    - 3 data cards: Similar Trades (count + win rate), Gate Today (GO/REDUCE/SKIP + confidence), Outcomes Tracked
    - Key Takeaways list with AlertTriangle icons
    - AI Self-Review narrative from Ollama/GPT-OSS (or structured fallback)
    - Re-analyze button
- **Testing**: 23/23 pytest tests pass (iteration_123.json)

### P0 (Next)
- (All P0 items complete)


### Known Issues
- Backend event loop occasionally blocks during IB connection retries (known httpx self-calling timeout issue)
- Old trades (pre-January 2026) missing `source` and `outcome` fields (not critical)