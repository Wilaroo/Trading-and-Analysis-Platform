# Master Build Plan — Implementation Guide
## SentCom AI Trading Platform — April 2026

This document provides exact file-level implementation details for each phase.
Used by forked sessions to execute without re-discovery.

---

## Phase 1: Data Foundation — 100% IB Pipeline

### 1a. Replace Alpaca Intraday Bars with MongoDB
**File:** `backend/services/realtime_technical_service.py`
**Line ~233:** `intraday_bars = await self.alpaca.get_bars(symbol, "5Min", 78)`
**Change to:** Query `ib_historical_data` collection for recent 5-min bars:
```python
async def _get_intraday_bars_from_db(self, symbol: str, bar_size: str = "5 mins", limit: int = 78):
    """Get recent intraday bars from ib_historical_data (same source as training)."""
    pipeline = [
        {"$match": {"symbol": symbol, "bar_size": bar_size}},
        {"$sort": {"date": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}},
    ]
    bars = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
    bars.reverse()  # Chronological order
    return bars
```
**Fallback:** If <10 bars returned (data gap), skip symbol for this scan cycle. Do NOT fall back to Alpaca.

### 1b. Remove Alpaca Quote Fallback
**File:** `backend/services/enhanced_scanner.py`
**Method:** `_get_quote_with_ib_priority()` (or similar)
**Change:** Remove Alpaca fallback. If IB Pusher has no quote, use latest bar close from `ib_historical_data` as estimated price. If no recent bar either, skip symbol.

### 1c. Remove Finnhub from Price/Bar Paths
**File:** `backend/services/stock_data.py`
**Change:** Remove `finnhub.Client` usage for quotes and candles. Keep only the earnings calendar endpoint.
**File:** `backend/services/market_context.py` (line ~481-489)
**Change:** Replace Finnhub historical candles with `ib_historical_data` query.

### 1d. Remove TwelveData
**File:** `backend/services/stock_data.py`
**Change:** Remove all TwelveData references (it's a dead fallback).

### 1e. Simplify hybrid_data_service.py
**File:** `backend/services/hybrid_data_service.py`
**Change:** Remove Alpaca fallback paths. Single source: MongoDB `ib_historical_data` + IB Pusher.

### 1f. Keep yfinance
No changes. Already only used for UI fundamentals (non-blocking).

### 1g. Earnings Calendar Cross-Verification
**File:** `backend/services/stock_data.py` (or new utility)
**Add:** When displaying earnings for a symbol:
1. Get Finnhub earnings date
2. Get IB earnings date via `reqFundamentalData` (if available from pusher)
3. If both agree: display with "verified" badge
4. If they disagree: display both dates with warning flag

### 1h. Staleness Check
**File:** `backend/services/realtime_technical_service.py`
**Add:** Before returning intraday bars, check if most recent bar is within 24 hours. If stale, return empty (scanner will skip this symbol).

### Testing Phase 1
```bash
# Verify no Alpaca API calls happen during scanning
grep -rn "alpaca" /app/backend/services/realtime_technical_service.py  # should be zero
grep -rn "alpaca" /app/backend/services/enhanced_scanner.py  # should only be in dormant fallback

# Test intraday bar query
curl -s "$API_URL/api/health" | python3 -c "import sys,json; print(json.load(sys.stdin))"

# Verify scanner works with IB-only data
# Start scanner, check logs for "alpaca" or "IEX" references — should be NONE
```

---

## Phase 2: Training Engine — LightGBM -> XGBoost GPU

### 2a-2d. Core Swap
**File:** `backend/services/ai_modules/timeseries_gbm.py` (1194 lines)

**Key changes:**
1. Replace `import lightgbm as lgb` with `import xgboost as xgb`
2. Replace `lgb.Dataset(X, y)` with `xgb.DMatrix(X, label=y)`
3. Replace `lgb.train(params, dataset, ...)` with `xgb.train(params, dmatrix, ...)`
4. Replace `model.predict(X)` with `model.predict(xgb.DMatrix(X))`
5. Replace model save: `pickle.dump` -> `model.save_model('model.json')`
6. Replace model load: `pickle.load` -> `xgb.Booster(); model.load_model('model.json')`

**LightGBM params -> XGBoost params mapping:**
```
lgb 'objective': 'binary'        -> xgb 'objective': 'binary:logistic'
lgb 'metric': 'binary_logloss'   -> xgb 'eval_metric': 'logloss'
lgb 'num_leaves': 63             -> xgb 'max_depth': 8 (approx equivalent)
lgb 'learning_rate': 0.05        -> xgb 'learning_rate': 0.05 (same)
lgb 'feature_fraction': 0.8      -> xgb 'colsample_bytree': 0.8
lgb 'bagging_fraction': 0.8      -> xgb 'subsample': 0.8
lgb 'n_estimators': 200          -> xgb num_boost_round=200
NEW:                              -> xgb 'tree_method': 'hist'
NEW:                              -> xgb 'device': 'cuda'
NEW:                              -> xgb 'max_bin': 256
```

**CRITICAL:** Preserve the output contract. Downstream consumers (ensemble, confidence gate) expect:
- `probability_up`: float 0-1
- `direction`: "up" | "down" | "flat"
- `confidence`: float 0-1
XGBoost binary:logistic outputs probabilities natively — same as LightGBM binary.

### 2e. Requirements
```bash
pip install xgboost && pip freeze > /app/backend/requirements.txt
```
Note: Keep `lightgbm` in requirements for backwards compatibility during transition.

### Testing Phase 2
```python
# Quick validation script
import xgboost as xgb
import numpy as np

# Verify GPU is accessible
X = np.random.randn(10000, 50).astype(np.float32)
y = np.random.randint(0, 2, 10000)
dtrain = xgb.DMatrix(X, label=y)
params = {'tree_method': 'hist', 'device': 'cuda', 'objective': 'binary:logistic', 'max_depth': 6}
model = xgb.train(params, dtrain, num_boost_round=10)
preds = model.predict(dtrain)
print(f"GPU training OK. Predictions shape: {preds.shape}, range: [{preds.min():.3f}, {preds.max():.3f}]")
```

---

## Phase 3: Training Optimizations

### 3a. Feature Caching
**File:** `backend/services/ai_modules/training_pipeline.py`
**Concept:** After Phase 1 extracts base features for all symbols, cache the feature matrices in a dict keyed by (symbol, bar_size). Phases 2-8 retrieve cached base features and only compute their phase-specific extras.

**Implementation:**
```python
# Global feature cache (cleared between full training runs)
_feature_cache = {}  # key: (symbol, bar_size) -> value: DataFrame of base features

async def get_cached_base_features(symbol, bar_size, db):
    key = (symbol, bar_size)
    if key in _feature_cache:
        return _feature_cache[key].copy()
    # Extract from DB (expensive)
    features = await extract_base_features(symbol, bar_size, db)
    _feature_cache[key] = features
    return features.copy()

def clear_feature_cache():
    global _feature_cache
    _feature_cache.clear()
```

### 3b. Batch Size
**File:** `backend/services/ai_modules/training_pipeline.py` (line ~38)
```python
STREAM_BATCH_SIZE = 25  # Change to 150 (128GB memory handles it)
```

### 3c. Worker Count
**File:** `backend/services/ai_modules/training_pipeline.py`
```python
MAX_EXTRACT_WORKERS = max(1, os.cpu_count() - 2)  # Was // 2
```

---

## Phase 4: Scanner Upgrade

### 4a-4e. Config Changes
**File:** `backend/services/enhanced_scanner.py` (line ~585-590)
```python
self._symbols_per_batch = 100       # Was 10
self._batch_delay = 0.1             # Was 1.0
self._scan_interval = 30            # Was 60
self._wave_size = 500               # Was 200
```
**File:** `backend/services/trading_bot_service.py`
```python
self._scan_interval = 15            # Was 30
```

### 4f. Event-Driven Scan Hook
**File:** `backend/routers/ib.py` (in `receive_pushed_ib_data`)
**Add:** After storing pushed data, trigger immediate scan for the pushed symbol:
```python
# After saving quote to in-memory dict
asyncio.create_task(trigger_symbol_scan(symbol))
```

### 4g. Batch Model Inference
**File:** `backend/services/ai_modules/timeseries_gbm.py`
**Add:** `predict_batch(symbols_features_matrix)` method that takes a NumPy matrix of all symbols' features and returns predictions in one GPU call.

---

## Phase 4.5: Confidence Gate Refactor

### Core Changes
**File:** `backend/services/ai_modules/confidence_gate.py`

**Replace the evaluate() method scoring logic:**

```python
# OLD: Subtractive
confidence_points = 50  # Start neutral
if regime_against: confidence_points -= 25
if model_disagrees: confidence_points -= 15

# NEW: Additive with weighted voting
confidence_points = 0

# Regime contribution
if regime_aligned: confidence_points += regime_weight  # 15-20
elif regime_against: confidence_points -= regime_penalty  # 10-15 (less than before)

# Model voting (weighted by accuracy)
for model in relevant_models:
    weight = model.accuracy * model.sample_size_factor  # Higher accuracy = more weight
    if model.agrees:
        confidence_points += weight * MAX_MODEL_CONFIRM  # e.g., weight * 10
    elif model.disagrees:
        confidence_points -= weight * MAX_MODEL_PENALTY  # e.g., weight * 5
    # else: model abstains (confidence < 0.4), no points added or removed

# Floor protection
confidence_points = max(25, confidence_points)  # Never auto-zero from model stacking

# Quality and learning loop (additive)
confidence_points += quality_contribution  # 5-10
confidence_points += learning_feedback     # +/- 5-10
```

**New thresholds:**
```python
GO_THRESHOLD = 60      # Was 65
REDUCE_THRESHOLD = 35  # Was 40
# Below 35 = SKIP
```

### Smart Filter Rolling Window
**File:** `backend/services/smart_filter.py`
**Change:** Instead of all-time win rate, compute from last 30 days or last 20 trades:
```python
# Filter to recent trades only
cutoff = datetime.now(timezone.utc) - timedelta(days=30)
recent_stats = [t for t in stats if t['date'] >= cutoff]
# If fewer than min_sample_size recent trades, use all-time but with decay
```

### Sector-Relative Regime
**File:** `backend/services/ai_modules/confidence_gate.py`
**Add:** Before penalizing for regime, check if the stock's sector is outperforming:
```python
sector_etf = get_sector_etf(symbol)  # e.g., XLK for tech stocks
sector_performance = get_recent_performance(sector_etf)
if sector_performance > 0 and regime_state == "CONFIRMED_DOWN":
    # Sector is strong despite broad weakness — reduce regime penalty
    regime_penalty *= 0.5
    reasoning.append(f"Sector {sector_etf} strong despite weak SPY — halving regime penalty")
```

---

## Phase 5: Deep Learning Models

Each model follows the same integration pattern:
1. Create model file in `backend/services/ai_modules/`
2. Add training phase in `training_pipeline.py`
3. Add prediction method callable by Confidence Gate
4. Register as weighted voter in Confidence Gate
5. Test independently, then test in pipeline

### 5a. TFT (Temporal Fusion Transformer)
**New file:** `backend/services/ai_modules/temporal_fusion_transformer.py`
- PyTorch implementation
- Multi-timeframe input (1min + 5min + 15min + daily)
- Attention mechanism learns which timeframes matter per symbol/regime
- Output: (direction, confidence, uncertainty)
- Training on Spark GPU (needs multi-timeframe data = 128GB)

### 5b. CNN-LSTM
**File:** `backend/services/ai_modules/cnn_chart_model.py` (upgrade existing)
- Add LSTM layers after CNN feature extraction
- Input: sequence of chart images (not just single snapshot)
- Captures temporal evolution of chart patterns
- Training on PC GPU (16GB sufficient)

### 5c. FinBERT Sentiment
**New file:** `backend/services/ai_modules/finbert_sentiment.py`
- Pre-trained FinBERT model (from HuggingFace)
- Fine-tune on financial news headlines from IB/Ollama
- Input: recent news for symbol
- Output: sentiment score (-1 to +1) + confidence
- Training on PC GPU

### 5d. VAE Regime Detection
**New file:** `backend/services/ai_modules/vae_regime.py`
- Variational Autoencoder for unsupervised regime detection
- Input: market microstructure features (volatility, correlation, breadth)
- Output: regime label + certainty
- Supplements rule-based regime engine
- Training on Spark GPU

### 5e. RL Position Sizer
**New file:** `backend/services/ai_modules/rl_position_sizer.py`
- Reinforcement Learning agent (PPO or SAC)
- State: account value, open positions, regime, confidence score
- Action: position size (0% to max%)
- Reward: risk-adjusted returns
- Replaces rule-based position sizing in opportunity_evaluator
- Training on PC GPU

---

## Phase 6: Distributed Training

### PC Training Worker
**New file:** `documents/scripts/pc_training_worker.py`
```python
"""
Runs on Windows PC (RTX 5060 Ti).
Connects to Spark's MongoDB over LAN.
Trains assigned models locally.
Uploads trained models back to MongoDB.
"""
import pymongo
import torch

SPARK_MONGO_URL = "mongodb://192.168.50.2:27017"
DB_NAME = "sentcom"

# 1. Connect to Spark MongoDB
client = pymongo.MongoClient(SPARK_MONGO_URL)
db = client[DB_NAME]

# 2. Check training queue for PC-assigned models
queue = db["training_queue"].find({"assigned_to": "pc", "status": "pending"})

# 3. For each model: download data, train, upload
for task in queue:
    model_type = task["model_type"]  # "cnn_lstm", "finbert", "vae", "rl"
    # ... train on RTX 5060 Ti ...
    # ... upload to timeseries_models collection ...
```

---

## Phase 7: Infrastructure

### 7a. 8 Turbo Collectors
**File:** `documents/TradeCommand_Spark_AITraining.bat`
**Change:** Add client IDs 20-23 (currently 16-19):
```bat
start "Turbo-5" cmd /k python ib_historical_collector.py --client-id 20 --turbo
start "Turbo-6" cmd /k python ib_historical_collector.py --client-id 21 --turbo
start "Turbo-7" cmd /k python ib_historical_collector.py --client-id 22 --turbo
start "Turbo-8" cmd /k python ib_historical_collector.py --client-id 23 --turbo
```

### 7b. systemd Services
Follow existing `/app/documents/SPARK_SYSTEMD_SETUP.md`

### 7e. Resume Training
**File:** `backend/services/ai_modules/training_pipeline.py`
**Add:** Before each phase, check if models for that phase already exist in `timeseries_models`:
```python
existing = db["timeseries_models"].find_one({"phase": phase_num, "bar_size": bar_size})
if existing and existing.get("completed"):
    logger.info(f"Phase {phase_num} already trained for {bar_size} — skipping")
    continue
```

---

## Execution Order for Forked Sessions

### Fork 1: Phases 1 + 2 (Data Foundation + XGBoost)
Both are backend changes with no frontend impact. Test together.

### Fork 2: Phases 3 + 4 (Training Optimization + Scanner)
Config tuning + feature cache. Independent systems, test separately.

### Fork 3: Phase 4.5 (Confidence Gate Refactor)
MUST complete before adding DL models. Test thoroughly with existing model set.

### Fork 4: Phase 5a (TFT)
Single new model. Test integration with Confidence Gate.

### Fork 5: Phase 5b (CNN-LSTM)
Upgrade existing Phase 9. Test alongside TFT.

### Fork 6: Phases 5c-5e (FinBERT, VAE, RL)
Three smaller models. Can batch if time allows.

### Fork 7: Phases 6 + 7 (Distributed Training + Infrastructure)
Polish and production hardening.
