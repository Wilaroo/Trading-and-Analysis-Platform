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

### Phase 2: XGBoost GPU Swap (DONE)
- Replaced LightGBM with XGBoost (`tree_method='hist'`, `device='cuda'`)

### Phase 3: Training Optimizations (DONE)
- Vectorized `extract_features_bulk()`, feature caching, batch sizes 500

### Phase 4: Scanner Upgrade (DONE)
- ADV-tiered scanning, 100 symbols per batch

### Phase 4.5: Confidence Gate Refactor (DONE)
- Additive 0-100 scoring, 12 layers, GO >= 55 / REDUCE >= 30 / SKIP < 30

### Phase 5a: Training Pipeline Bug Fixes (DONE — April 7, 2026)
- 9 critical XGBoost pipeline bugs fixed and verified on Spark hardware

### Phase 5b: Deep Learning Models (DONE — April 7, 2026)
- VAE Regime Detection (Layer 10), TFT Multi-Timeframe (Layer 9), CNN-LSTM (Layer 11)
- Full PyTorch implementations with train/predict/save/load
- Wired into Confidence Gate and training pipeline (Phase 11)

### Phase 5c: FinBERT Sentiment (DONE — April 8, 2026)
- FinnhubNewsCollector + FinBERTSentiment with 6 API endpoints
- Worker `FINBERT_ANALYSIS` job type for background pipeline
- Wired into training pipeline (Phase 12)
- Decoupled from live training loop — Gate Layer 12 ready when activated

### Phase 5d: Training Pipeline Optimization (DONE — April 8, 2026)
- **9x memory reduction**: Replaced `.tolist()` Python list accumulation with numpy chunk pattern across `train_full_universe()`, `TimeSeriesGBM.train()`, and `_train_single_setup_profile()`
- **10-50x setup training speedup**: Replaced per-match `extract_features()` with one `extract_features_bulk()` per symbol + numpy indexing
- **Training mode bridge**: Connected `training_mode_manager` ↔ `focus_mode_manager` so scanner/bot/WS streams genuinely pause during training
- **Pipeline Phase 1 upgraded**: Replaced old `stream_load_and_extract` with optimized `train_full_universe()` — eliminates redundancy with Full Universe button
- **Phase 11 + 12 added**: DL models and FinBERT wired into master training pipeline
- **Results**: Daily model 2 min (cached), 1-hour model 30M samples in 66 min, memory flat ~15-25GB

## Master Training Pipeline (13 Phases)
| Phase | What | Models |
|-------|------|--------|
| 1 | Generic Directional (Full Universe) | 7 |
| 2 | Setup-Specific (Long) | 17 |
| 2.5 | Setup-Specific (Short) | 17 |
| 3 | Volatility Prediction | 7 |
| 4 | Exit Timing | 10 |
| 5 | Sector-Relative | 3 |
| 6 | Risk-of-Ruin | 6 |
| 7 | Regime-Conditional | 28 |
| 8 | Ensemble Meta-Learner | 10 |
| 9 | CNN Chart Patterns | 13 |
| 11 | Deep Learning (VAE/TFT/CNN-LSTM) | 3 |
| 12 | FinBERT Sentiment | 1 |
| 13 | Auto-Validation (5-phase) | 34 |
| **Total** | | **156 work units** |

## Confidence Gate Scoring (12 Layers)
- Layer 1: Regime Check (max +20 / floor -10)
- Layer 2: AI Regime (max +10 / floor -5)
- Layer 3: Model Consensus (max +15 / floor -5)
- Layer 4: Live Model Prediction (max +15 / floor -5)
- Layer 5: Cross-Model Agreement (max +5 / floor -5)
- Layer 6: Quality Score (max +10 / floor -5)
- Layer 7: Learning Loop Feedback (max +8 / floor -5)
- Layer 8: CNN Visual Pattern (max +12 / floor -5)
- Layer 9: TFT Multi-Timeframe (max +12 / floor -5)
- Layer 10: VAE Regime Detection (max +8 / floor -5)
- Layer 11: CNN-LSTM Temporal (max +10 / floor -5)
- Layer 12: FinBERT Sentiment (INACTIVE — max +7 / floor -5) [READY]

## Key API Endpoints
- `/api/ai-modules/timeseries/train-full-universe-all` — Train all 7 directional models
- `/api/ai-modules/timeseries/setups/train-all` — Train all 35 setup profiles
- `/api/ai-modules/dl/train-all` — Train 3 DL models
- `/api/ai-modules/finbert/*` — 6 FinBERT endpoints
- `/api/ai-modules/dl/status` — DL + FinBERT status
- `/api/ai-training/start` — Master pipeline (all 13 phases)
- `/api/ai-training/is-active` — Lightweight training status check (for IB Pusher/Collectors)

### Phase 5e: IB Pusher Training Guard (DONE — April 8, 2026)
- **Bug Fixed:** IB Pusher's `run()` mode was checking `http://127.0.0.1:8001` for training status — but pusher runs on Windows PC, not Spark. Focus mode check silently failed, pusher kept hammering MongoDB during training.
- **New Endpoint:** `GET /api/ai-training/is-active` — lightweight boolean check consolidating `focus_mode_manager` + `training_mode_manager` + subprocess status. 14ms response time.
- **Pusher Fix:** Changed `local_backend_url` to `spark_backend_url` (cloud_url = `http://192.168.50.2:8001`). Added proper exponential backoff: 30s checks normally, 60s checks during training, 5s sleep per tick when paused, clear console logging.
- **Collectors Fixed:** Added same training guard to `ib_historical_collector.py`, `v3`, and `v4` — all back off 60s per cycle when training detected.
- **Auto-Mode Fixed:** `_check_cloud_mode()` now checks the new `/api/ai-training/is-active` endpoint first (most reliable signal).

## Upcoming Tasks
- Phase 5f: RL Position Sizer (needs trade outcome data)
- Phase 6: Distributed PC Worker (LAN training on RTX 5060 Ti)
- Phase 7: Infrastructure Polish (systemd, notifications, symbol rotation)
- FinBERT UI panel in NIA
- Activate FinBERT as Gate Layer 12
- Per-signal weight optimizer
- Deprecate/remove `ollama_proxy_manager.py` (native Ollama on Spark replaces it)

## Key Files
- `/app/backend/services/ai_modules/training_pipeline.py` — Master 13-phase pipeline
- `/app/backend/services/ai_modules/timeseries_service.py` — Full Universe training
- `/app/backend/services/ai_modules/timeseries_gbm.py` — XGBoost model
- `/app/backend/services/ai_modules/confidence_gate.py` — 12-layer scoring
- `/app/backend/services/ai_modules/vae_regime.py` — VAE Regime Detection
- `/app/backend/services/ai_modules/temporal_fusion_transformer.py` — TFT
- `/app/backend/services/ai_modules/cnn_lstm_model.py` — CNN-LSTM
- `/app/backend/services/ai_modules/finbert_sentiment.py` — FinBERT Sentiment
- `/app/backend/routers/ai_modules.py` — All AI API endpoints
- `/app/backend/worker.py` — Background job processor
- `/app/frontend/src/components/NIA/TrainingPipelinePanel.jsx` — Pipeline UI

## DB Collections
- `ib_historical_data` — 178M+ bars
- `timeseries_models` — XGBoost models
- `feature_cache` — Cached training features
- `dl_models` — PyTorch DL models
- `news_articles` — Finnhub news articles
- `news_sentiment` — FinBERT scored articles
- `confidence_gate_log` — AI decisions
- `job_queue` — Background jobs
