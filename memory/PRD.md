# SentCom AI Trading Platform - PRD

## Original Problem Statement
AI trading platform with 5-Phase Auto-Validation Pipeline, Data Inventory System, CNN chart detection, and maximum Interactive Brokers (IB) historical data collection. Optimizing the ML training pipeline performance over 177M MongoDB rows, resolving stale AI Training status, fixing UI desyncs, and utilizing hardware efficiently.

**NEW (April 2026):** Major architecture upgrade — dual Blackwell GPU distributed training, 100% IB data pipeline (removing Alpaca/Finnhub/TwelveData), XGBoost GPU swap, 5 new Deep Learning models, Confidence Gate refactor from subtractive to additive scoring, and scanner performance optimization.

## Hardware Architecture
```
+--------------------------------------+     +--------------------------------------+
|        DGX SPARK (Linux)             |     |       WINDOWS PC                     |
|        IP: 192.168.50.2              |     |       IP: 192.168.50.1               |
|                                      |     |                                      |
|  GPU: Blackwell GB10 (128GB unified) |     |  GPU: RTX 5060 Ti 16GB GDDR7         |
|  CPU: Grace ARM (~10 cores)          |<--->|  CPU: Ryzen 7 5800XT (8C/16T, 3.8G)  |
|  RAM: 128GB unified                  |10GbE|  RAM: 32GB DDR4                       |
|                                      |     |  CUDA: 13.2 / Driver: 595.79         |
|  FastAPI Backend (venv) :8001        |     |  Mobo: ASUS PRIME X570-P (PCIe 4.0)  |
|  MongoDB (Docker) :27017             |     |                                      |
|  Ollama :11434                       |     |  IB Gateway :4002                     |
|  Frontend React :3000                |     |  8x Turbo Data Collectors (planned)   |
|                                      |     |  Live Data Pusher                     |
|  ROLE: Heavy GBM + TFT training,     |     |  Browser UI                           |
|        Backend, DB, Scanner           |     |  ROLE: CNN/DL training, data collect  |
+--------------------------------------+     +--------------------------------------+
```

## Data Architecture (Post-Cleanup)
```
CRITICAL PATH (100% IB — zero external dependencies):
  IB Gateway -> IB Pusher -> Spark Backend -> MongoDB ib_historical_data (177M+ rows)
  Scanner + AI Models + Execution all use IB-sourced data ONLY

UI ENRICHMENT (non-blocking, cached):
  yfinance -> Fundamentals display (PE, revenue, margins, quality scores)
  Finnhub -> Earnings calendar (cross-verified with IB per-symbol earnings)
  
REMOVED:
  Alpaca (quotes, bars, execution) -> REPLACED by IB Pusher + MongoDB
  TwelveData -> REMOVED (dead code)
  Finnhub price/bar data -> REPLACED by MongoDB ib_historical_data
```

## Current Data Coverage (as of April 7, 2026)
- **Total bars**: 177,394,521 in ib_historical_data
- **ADV symbols**: 9,187
- **Scan universe**: 1,473 unique symbols (SPY 495 + QQQ 120 + NASDAQ Ext 480 + IWM 542 + ETFs)
- **Timeframes**: 1min, 5min, 15min, 30min, 1hour, 1day, 1week
- **Symbol lists last updated**: Feb 11, 2026 (next rebalance: March 20, 2026)

## What's Been Implemented

### Session: April 8, 2026 (Fork 1 — Phase 1 + Phase 2 Implementation)

#### Phase 1: Data Foundation — 100% IB Pipeline (COMPLETE)
- **1a.** `realtime_technical_service.py`: Replaced Alpaca intraday bars with MongoDB `ib_historical_data` queries. Added `_get_intraday_bars_from_db()` method.
- **1b.** `enhanced_scanner.py`: Replaced Alpaca quote fallback with MongoDB latest bar in `_get_quote_with_ib_priority()`. Replaced Alpaca ADV fetch with MongoDB aggregate in `_fetch_single_adv()`.
- **1c.** `stock_data.py`: Removed Alpaca, Finnhub, and TwelveData from quote chain. Added `_fetch_mongodb_bar_quote()` as fallback between IB Pusher and Yahoo.
- **1d.** `stock_data.py`: Removed all TwelveData methods and references.
- **1e.** `hybrid_data_service.py`: Removed `_fetch_from_alpaca()` method and Alpaca rate limiter. Fixed `_get_from_cache()` to use correct IB field names (`bar_size`, `date`).
- **1f.** `market_context.py`: Replaced Finnhub candles with MongoDB `ib_historical_data` query. Added `set_db()` method.
- **1g.** Earnings calendar (Finnhub + IB cross-verification) preserved.
- **1h.** Added staleness check: `_check_staleness()` skips symbols with bars >24h old.
- **Wiring:** `server.py` updated to pass `db` reference to `stock_service` and `market_context_service`.

#### Phase 2: XGBoost GPU Swap (COMPLETE)
- **2a.** `timeseries_gbm.py`: Replaced `import lightgbm as lgb` with `import xgboost as xgb`.
- **2b.** GPU detection: Auto-detects CUDA GPU via XGBoost native test (no OpenCL needed).
- **2c.** `DEFAULT_PARAMS`: Mapped to XGBoost format (`binary:logistic`, `tree_method='hist'`, `device='cuda'`).
- **2d.** `train()`, `train_vectorized()`, `train_from_features()`: All use `xgb.DMatrix` + `xgb.train()`.
- **2e.** `predict()`: Uses `xgb.DMatrix` for inference.
- **2f.** `_save_model()`: Uses XGBoost native JSON serialization (not pickle).
- **2g.** `_load_model()`: Supports both new XGBoost JSON and legacy LightGBM pickle (graceful migration).
- **2h.** `requirements.txt`: Updated with `xgboost==3.2.0`.

#### Testing (13/13 pass)
- Alpaca removal verified (zero references in critical paths)
- Staleness check tested (fresh, stale, no data)
- XGBoost params, training, serialization format, and prediction contract validated

#### Phase 3: Training Optimizations (COMPLETE)
- Feature caching: New `feature_cache` MongoDB collection stores precomputed features with 1-week TTL, auto-invalidates on feature set changes
- Batch sizes: 5x-10x increase (1min: 5→25, 5min: 10→50, 1day: 100→500) for 128GB Spark
- Float32 enforcement: All training arrays use `np.float32` to halve memory
- Fixed `timeseries_service.py`: Replaced `pickle.loads/dumps` with XGBoost JSON serialization throughout

#### Phase 4: Scanner Upgrade (COMPLETE)
- Scan config: 100 symbols/batch (was 10), 0.1s delay (was 1s), 15s interval (was 60s)
- **Tiered scanning**: Intraday ≥500K ADV (every ~15s), Swing ≥100K (every ~2min), Investment ≥50K (11:00 AM + 3:45 PM ET only)
- Staleness check v2: IB Pusher-aware (live quote = never stale), market-hours-aware (counts trading days, not calendar days), handles IB date format `YYYYMMDD HH:MM:SS`
- Investment tier ADV set to 50K per user's existing data

#### Phase 4.5: Confidence Gate Refactor (COMPLETE)
- **Additive scoring** (base 0, earn confirmation): Regime ±20/10, AI ±10/5, Consensus ±15/5, Live Model ±15/5 (accuracy-weighted), Cross-Model ±5, Quality ±10/5, Learning ±8/5, CNN ±12/5
- **Floor protection**: Regime max -10, all others max -5 per gate
- **Thresholds**: ≥55 GO, ≥30 REDUCE, <30 SKIP
- `scoring_version: "additive_v1"` field in all gate log entries
- CNN signal + cnn_signal field added to result dict

#### Testing (32/32 pass across all phases)
- Phase 1-2: 13 tests (Alpaca removal, staleness, XGBoost)
- Phase 3: 5 tests (batch sizes, float32, feature cache, no-pickle)
- Phase 4: 7 tests (scan config, investment tier, three tiers, staleness IB format, weekend handling)
- Phase 4.5: 7 tests (additive base 0, scoring version, floor protection, thresholds, docstring, CNN signal, no base-50)

### Session: April 8, 2026 (Previous — Planning Session)
- Complete architecture audit of data sources, scanning pipeline, and kill chain
- Identified train/serve data skew (models train on IB, scanner uses Alpaca)
- Identified 27-point kill chain causing potential over-filtering
- Identified Confidence Gate "subtractive scoring" problem (more models = more vetoes)
- Documented complete 7.5-phase Master Build Plan
- Created Architecture Decisions document
- Created detailed Implementation Guide for forked sessions

### Session: April 7, 2026
- Created backend `.env` and frontend `.env` for DGX Spark
- Fixed `asyncio.create_task` crash at module load
- Fixed WebSocket startup modal blocking
- Fixed DynamicRiskPanel and SentCom null-check spam
- Full MongoDB migration: Atlas -> Spark local Docker (177.8M rows)
- Optimized fill-gaps endpoint: replaced `distinct()` with aggregation pipeline
- Fixed ib_historical_collector pacing bug
- Created `TradeCommand_Spark_AITraining.bat`
- 4 turbo collectors running overnight to fill all data gaps

### Previous Sessions
- Fixed phantom `QUICK` symbol (Yahoo Finance validation)
- Fixed frontend aggressive polling during training mode
- Configured 10Gbps direct Ethernet link (Windows PC <-> DGX Spark)
- Set up DGX Spark base dependencies

## Master Build Plan (7.5 Phases)

### Phase 1: Data Foundation — 100% IB Pipeline [COMPLETE ✅]
- 1a. Remove Alpaca from live scanning (replace intraday bars with MongoDB queries) ✅
- 1b. Remove Alpaca quote fallback (IB Pusher only, latest MongoDB bar as fallback) ✅
- 1c. Remove Finnhub from price/bar data paths (market_context.py, stock_data.py) ✅
- 1d. Remove TwelveData references (dead code cleanup) ✅
- 1e. Clean up hybrid_data_service.py (MongoDB-only) ✅
- 1f. Keep yfinance for UI fundamentals (cached, non-blocking) ✅
- 1g. Earnings calendar: Keep Finnhub + add IB per-symbol earnings as cross-check ✅
- 1h. Add staleness check (skip symbols with bars >24h old on intraday) ✅

### Phase 2: Training Engine — LightGBM -> XGBoost GPU [COMPLETE ✅]
- 2a. Swap LightGBM to XGBoost in timeseries_gbm.py ✅
- 2b. Set tree_method='hist', device='cuda' for Blackwell GPU ✅
- 2c. Preserve pipeline contract (same input features, output format) ✅
- 2d. Update model serialization (XGBoost JSON format) ✅
- 2e. Update requirements.txt ✅

### Phase 3: Training Optimizations [COMPLETE ✅]
- 3a. Feature caching — save/load precomputed features from MongoDB `feature_cache` ✅
- 3b. Batch sizes increased for 128GB: 1min 5→25, 5min 10→50, 15min 15→75, 1hr 50→200, 1day 100→500 ✅
- 3c. Float32 enforcement in numpy arrays ✅
- 3d. XGBoost memory tuning (max_bin=256) ✅
- Fixed pickle→XGBoost JSON in timeseries_service.py model reload/save ✅

### Phase 4: Scanner Upgrade [COMPLETE ✅]
- 4a. symbols_per_batch 10 → 100 ✅
- 4b. batch_delay 1.0s → 0.1s ✅
- 4c. scan_interval 60s → 15s ✅
- 4d. Tiered scanning by ADV: Intraday ≥500K (every 15s), Swing ≥100K (every 2min), Investment ≥50K (11AM + 3:45PM ET only) ✅
- 4e. Staleness check: IB Pusher-aware + market-hours-aware (3 trading days, IB date formats, weekends) ✅

### Phase 4.5: Confidence Gate Refactor [COMPLETE ✅] **CRITICAL — Done before Phase 5**
- Subtractive (base 50) → Additive (base 0) with graduated point scales ✅
- Floor protection: regime max -10, all others max -5 ✅
- Thresholds: ≥55 GO, ≥30 REDUCE, <30 SKIP ✅
- scoring_version: "additive_v1" for migration tracking ✅
- CNN signal + learning loop capped in result ✅

### Phase 5: Deep Learning Models [NOT STARTED]
- 5a. Temporal Fusion Transformer (TFT) — Phase 11 (new)
- 5b. CNN -> CNN-LSTM upgrade — Phase 9
- 5c. FinBERT Sentiment — SentCom integration
- 5d. VAE Regime Detection — Regime Engine addition
- 5e. RL Position Sizer — Execution step
Each model integrates into Confidence Gate as additional weighted voter

### Phase 6: Distributed Training — PC Worker [NOT STARTED]
- 6a. pc_training_worker.py for Windows PC (RTX 5060 Ti)
- 6b. Training coordinator (Spark assigns heavy to itself, lighter to PC)
- 6c. Model sync via MongoDB over 10GbE

### Phase 7: Infrastructure & Polish [NOT STARTED]
- 7a. Expand Turbo Collectors 4 -> 8 (client IDs 16-23)
- 7b. systemd services on Spark (auto-boot backend/frontend/MongoDB)
- 7c. Desktop notifications (training complete, high-priority scanner alerts)
- 7d. Symbol list auto-refresh (quarterly rebalance from live ETF holdings)
- 7e. Resume training feature (skip completed phases on restart)
- 7f. Expand IB Pusher watchlist for broader coverage
- 7g. Dynamic universe expansion (IB scanner API for real-time top movers)

## Estimated Training Times (Full Pipeline)
| Config | Time |
|--------|------|
| Current (LightGBM CPU) | 154+ hours (6.4 days) |
| XGBoost GPU only | ~20 hours |
| + Feature caching | ~12 hours |
| + Batch optimization | ~10 hours |
| + Dual GPU parallel | ~8-10 hours |
| Full pipeline + all DL models | ~10-14 hours |

## Key Technical Notes
- **CRITICAL**: DO NOT run `apt install nvidia-*` or `dkms` on the DGX Spark
- **CRITICAL**: Do not use `.distinct()` on ib_historical_data (177M+ rows, will timeout)
- **Virtual Environment**: All Python on Spark must use `source ~/venv/bin/activate`
- **nohup**: Always use `nohup` for backend/frontend on Spark via SSH
- **localhost quirk**: Use `192.168.50.2` (not `localhost`) for curl on Spark
- **IB Client IDs**: Pusher=15, Collectors=16-19 (expand to 16-23 for 8 collectors)
- **emergentintegrations**: Not installed on Spark
- **Train/serve skew**: Must be resolved (Phase 1) before any model retraining

## Key Files
### Backend Core
- `backend/.env` - Spark environment config
- `backend/server.py` - FastAPI main (fixed startup crash)
- `backend/services/trading_bot_service.py` - Bot main (27-gate pipeline)
- `backend/services/enhanced_scanner.py` - Live market scanner (4144 lines)
- `backend/services/smart_filter.py` - Historical win-rate filter
- `backend/services/ai_modules/confidence_gate.py` - AI voting gate (938 lines)
- `backend/services/ai_modules/timeseries_gbm.py` - LightGBM (-> XGBoost swap target)
- `backend/services/ai_modules/training_pipeline.py` - 10-phase training (2222 lines)
- `backend/services/realtime_technical_service.py` - Technical data (Alpaca removal target)
- `backend/services/stock_data.py` - Stock data providers (cleanup target)
- `backend/services/hybrid_data_service.py` - Hybrid data (simplification target)
- `backend/services/alpaca_service.py` - Alpaca (keep as dormant fallback)
- `backend/data/index_symbols.py` - 1,473-symbol universe

### Frontend Core
- `frontend/.env` - Frontend config
- `frontend/src/components/SentCom.jsx` - Main trading UI
- `frontend/src/components/StartupModal.jsx` - Startup checks
- `frontend/src/components/DynamicRiskPanel.jsx` - Risk display

### Documents
- `documents/DGX_SPARK_ENV_TEMPLATE.md` - ENV reference
- `documents/TradeCommand_Spark_AITraining.bat` - Windows startup
- `documents/SPARK_SYSTEMD_SETUP.md` - systemd setup guide
- `documents/scripts/ib_historical_collector.py` - Gap fill collector
- `documents/scripts/ib_data_pusher.py` - Live data pusher
- `documents/MASTER_BUILD_PLAN.md` - Detailed implementation guide
- `documents/ARCHITECTURE_DECISIONS.md` - All technical decisions documented

## Kill Chain Analysis (27 Gates)
See `/app/documents/ARCHITECTURE_DECISIONS.md` for full analysis of every point where a good trade can be missed, and the planned fixes.
