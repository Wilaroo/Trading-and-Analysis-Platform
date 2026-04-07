# SentCom AI Trading Platform — PRD

## Original Problem Statement
AI trading platform optimization. Implement XGBoost GPU swap, resolve Train/Serve data skew by removing Alpaca dependencies, eliminate scanning bottlenecks, refactor the subtractive confidence gate to an additive system, integrate Deep Learning models across the dual-GPU architecture (DGX Spark + Windows PC), and optimize feature extraction for 128GB DGX Spark memory.

## Architecture
- **DGX Spark** (Linux, Blackwell GPU, 128GB unified memory): Backend/Frontend + local MongoDB `tradecommand` (178M+ bars). Runs XGBoost + DL models.
- **Windows PC** (Ryzen 7, RTX 5060 Ti): IB Gateway/Turbo Collectors + (Future) distributed DL training over LAN.
- **Data**: 100% Interactive Brokers via local MongoDB. No Alpaca/Finnhub/TwelveData in trading paths.

## Completed Phases

### Phase 1: 100% IB Data (DONE)
- Removed Alpaca, Finnhub, TwelveData from all trading/scanning paths
- All training and inference strictly through IB data in MongoDB

### Phase 2: XGBoost GPU Swap (DONE)
- Replaced LightGBM with XGBoost (`tree_method='hist'`, `device='cuda'`)
- Updated `timeseries_gbm.py` with XGBoost native training

### Phase 3: Training Optimizations (DONE)
- Vectorized `extract_features_bulk()` for numpy sliding windows
- Feature caching in MongoDB
- Batch sizes increased to 500 symbols for 128GB Spark

### Phase 4: Scanner Upgrade (DONE)
- ADV-tiered scanning (Intraday > 500K, Swing > 100K, Investment > 50K)
- 100 symbols per batch, trading-day staleness check

### Phase 4.5: Confidence Gate Refactor (DONE)
- Additive 0-100 scoring system with floor protection
- Thresholds: GO >= 55, REDUCE >= 30, SKIP < 30

### Phase 5a: Training Pipeline Bug Fixes (DONE — April 7, 2026)
1. Fixed `train_full_universe()` — was still calling LightGBM, now uses XGBoost GPU
2. Fixed 3GB memory cap → 100GB for 128GB Spark
3. Fixed method defaults: symbol_batch_size 50→500, max_bars_per_symbol 1000→99999
4. Fixed router defaults: max_bars 1000/2000→99999
5. Fixed worker param passthrough for max_bars and batch_size
6. Fixed Pydantic model defaults 100/2000→500/99999
7. Fixed model save: XGBoost Booster uses temp file instead of BytesIO
8. Fixed misleading model save log (archived vs promoted)
9. Fixed stale feature cache guidance (clear before re-training)

### Phase 5b: Deep Learning Models (DONE — April 7, 2026)
Three new DL models created and integrated into the Confidence Gate:

1. **VAE Regime Detection** (`vae_regime.py`)
   - Variational Autoencoder for unsupervised market regime labeling
   - 5 regimes: Bull Trending, Bear Trending, High Volatility, Mean Reverting, Momentum Surge
   - Trains on SPY + sector ETF microstructure features
   - Confidence Gate Layer 10: max +8 / floor -5

2. **Temporal Fusion Transformer** (`temporal_fusion_transformer.py`)
   - Multi-timeframe attention model (1min, 5min, 15min, 1hour, 1day)
   - Variable Selection Network learns feature importance per timeframe
   - Cross-timeframe patterns (e.g., "daily trend up + 15min pullback = continuation")
   - Confidence Gate Layer 9: max +12 / floor -5

3. **CNN-LSTM** (`cnn_lstm_model.py`)
   - Temporal chart pattern recognition
   - 1D CNN backbone + LSTM sequence processing + attention
   - Learns pattern evolution over 5 consecutive windows
   - Confidence Gate Layer 11: max +10 / floor -5

**API Endpoints:**
- `POST /api/ai-modules/dl/train-vae-regime`
- `POST /api/ai-modules/dl/train-tft`
- `POST /api/ai-modules/dl/train-cnn-lstm`
- `POST /api/ai-modules/dl/train-all` (all 3 sequentially)
- `GET /api/ai-modules/dl/status`

**Worker Integration:** `DL_TRAINING` job type added to job queue system.

**Frontend:** "Train All DL Models" button added to AI Training panel.

## Confidence Gate Scoring (Updated)
Max theoretical: ~115 pts
- Layer 1: Regime Check (max +20 / floor -10)
- Layer 2: AI Regime (max +10 / floor -5)
- Layer 3: Model Consensus (max +15 / floor -5)
- Layer 4: Live Model Prediction (max +15 / floor -5)
- Layer 5: Cross-Model Agreement (max +5 / floor -5)
- Layer 6: Quality Score (max +10 / floor -5)
- Layer 7: Learning Loop Feedback (max +8 / floor -5)
- Layer 8: CNN Visual Pattern (max +12 / floor -5)
- Layer 9: TFT Multi-Timeframe (max +12 / floor -5) [NEW]
- Layer 10: VAE Regime Detection (max +8 / floor -5) [NEW]
- Layer 11: CNN-LSTM Temporal (max +10 / floor -5) [NEW]

## Current Status
- XGBoost full-universe training running on Spark (7 timeframes, 178M bars)
- DL models created, integrated into gate, API endpoints live
- Awaiting XGBoost training completion, then DL training

## Upcoming Tasks
- 🟡 (P1) Phase 5c: FinBERT Sentiment — needs news data source (IB news or scraper)
- 🟡 (P1) Phase 5d: RL Position Sizer — PPO/SAC agent for dynamic sizing
- 🟡 (P2) Phase 6: Distributed PC Worker — training coordinator for Windows PC over LAN
- ⚪ (P3) Phase 7: Infrastructure Polish — systemd, notifications, symbol rotation

## Key Files
- `/app/backend/services/ai_modules/timeseries_gbm.py` — XGBoost model
- `/app/backend/services/ai_modules/timeseries_service.py` — Training orchestration
- `/app/backend/services/ai_modules/confidence_gate.py` — Additive scoring (11 layers)
- `/app/backend/services/ai_modules/vae_regime.py` — VAE Regime Detection [NEW]
- `/app/backend/services/ai_modules/temporal_fusion_transformer.py` — TFT [NEW]
- `/app/backend/services/ai_modules/cnn_lstm_model.py` — CNN-LSTM [NEW]
- `/app/backend/routers/ai_modules.py` — Training + DL API endpoints
- `/app/backend/worker.py` — Background job processor
- `/app/backend/tests/test_phase3_4_45.py` — Test suite (38 tests)

## DB Schema
- `tradecommand.ib_historical_data` — 178M+ bars (compound index: symbol, bar_size, date)
- `tradecommand.timeseries_models` — XGBoost models (JSON format)
- `tradecommand.feature_cache` — Cached training features
- `tradecommand.dl_models` — PyTorch DL models (base64 state_dict) [NEW]
- `tradecommand.confidence_gate_log` — AI decisions (scoring_version: "additive_v1")
