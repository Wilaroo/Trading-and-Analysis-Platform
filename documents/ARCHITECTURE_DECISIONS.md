# Architecture Decisions — SentCom AI Trading Platform
## Date: April 8, 2026

This document captures all major technical decisions made during the planning session, including rationale and implications for implementation.

---

## Decision 1: Remove Alpaca/IEX from Critical Path — Go 100% IB

### Context
The platform used 3 data sources: IB (historical via collectors + real-time via pusher), Alpaca IEX (intraday bars for scanning), and Finnhub (company profiles, earnings). Models are trained on IB consolidated tape data but live scanning uses Alpaca IEX-only data (~3-5% of total market volume).

### Decision
- **Remove Alpaca** from all scanning and execution paths
- **Remove TwelveData** entirely (dead code)
- **Remove Finnhub** from price/bar data paths
- **Keep yfinance** for UI fundamentals display (PE, revenue, quality metrics)
- **Keep Finnhub** ONLY for earnings calendar (cross-verified with IB per-symbol earnings)

### Rationale
1. **Train/serve data skew**: Models train on IB consolidated tape but predict on Alpaca IEX data. Volume, VWAP, and bar prices differ between sources. This is the #1 accuracy killer.
2. **Latency**: MongoDB queries (local, microseconds) replace Alpaca API calls (network, 50-200ms)
3. **Reliability**: Zero external API dependencies during market hours
4. **Simplicity**: One data source = no reconciliation, no fallback logic, no rate limiting

### Impact
- `realtime_technical_service.py`: Query `ib_historical_data` for intraday bars instead of Alpaca
- `enhanced_scanner.py`: IB Pusher only for quotes; latest MongoDB bar price as fallback
- `stock_data.py`: Remove Finnhub/TwelveData providers
- `hybrid_data_service.py`: Simplify to MongoDB-only
- `alpaca_service.py`: Keep file intact as dormant fallback (do not import or call)

### Risk
If IB Pusher disconnects AND collectors fall behind, some symbols may have stale bars. Mitigation: staleness check (skip symbols with bars >24h old on intraday timeframes).

---

## Decision 2: Swap LightGBM to XGBoost GPU

### Context
LightGBM falls back to CPU on the DGX Spark because it requires OpenCL (not CUDA native). Training 177M rows on CPU takes 154+ hours. The Blackwell GB10 GPU sits idle during training.

### Decision
Replace LightGBM with XGBoost using `tree_method='hist'` and `device='cuda'`.

### Rationale
1. XGBoost has native CUDA support — no OpenCL dependency
2. `tree_method='hist'` on GPU is 10-50x faster than CPU for large datasets
3. 128GB unified memory on Blackwell eliminates OOM issues
4. XGBoost prediction output is compatible (probability, direction, confidence)

### Impact
- `timeseries_gbm.py`: Replace `lgb.Dataset/lgb.train` with `xgb.DMatrix/xgb.train`
- Model serialization: Switch from pickle to XGBoost JSON (`.save_model()/.load_model()`)
- `requirements.txt`: Add `xgboost` (keep `lightgbm` for backwards compat during transition)
- Class name `TimeSeriesGBM` stays unchanged (generic name)

### Key Parameters
```python
params = {
    'tree_method': 'hist',
    'device': 'cuda',
    'objective': 'binary:logistic',  # or 'multi:softprob'
    'eval_metric': 'logloss',
    'max_depth': 8,
    'learning_rate': 0.05,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'max_bin': 256,
    'n_estimators': 200,
}
```

### Note on Inference
XGBoost single-sample inference is faster on CPU than GPU (GPU kernel launch overhead exceeds computation for 1 sample). Training uses GPU; inference stays CPU. This is standard practice.

---

## Decision 3: Confidence Gate Refactor — Subtractive to Additive Scoring

### Context (The Problem)
The current Confidence Gate starts at 50 points and subtracts for risk signals:
- Regime against: -25
- Model disagrees: -15
- Cross-model conflict: -10
- CNN negative: -10

This means 3 negative signals can reduce score to 0, causing an automatic SKIP even if 8 other models AGREE. Adding 5 more DL models (TFT, CNN-LSTM, FinBERT, VAE, RL) exponentially increases the probability of at least one "disagreement," making the bot progressively more paralyzed.

### Decision
Refactor to **additive scoring with weighted ensemble voting**:
- Start at 0 (not 50)
- Each confirming signal ADDS points proportional to model accuracy
- Each disagreeing signal SUBTRACTS points proportional to model accuracy
- A 55% accuracy model's vote weighs less than a 75% accuracy model's vote
- High uncertainty = abstain (no vote), not disagree

### New Scoring Architecture
```
Base: 0
For each model that voted:
    if agrees_with_trade:
        score += model_accuracy_weight * confidence * MAX_MODEL_POINTS
    elif disagrees:
        score -= model_accuracy_weight * confidence * MAX_MODEL_PENALTY
    elif uncertain (confidence < threshold):
        score += 0  # abstain

Regime aligned:     +15 to +20
Quality score:      +5 to +10
Learning feedback:  +/- 5 to 10
Sector-relative:    +5 to +10 (NEW)

Thresholds:
    GO:     score >= 60
    REDUCE: score >= 35
    SKIP:   score < 35

Floor: score cannot go below 25 from model stacking alone
       (ensures trade is at least CONSIDERED at reduced size)
```

### Additional Changes
1. **Rolling window for Smart Filter**: Last 30 days or 20 trades (whichever is larger), not all-time cumulative. Old losses decay.
2. **Sector-relative regime**: If stock's sector is strong while SPY is weak, don't penalize. Use sector ETF performance.
3. **Fuzzy threshold margins**: Within 5% of any pattern detection threshold, use partial credit instead of binary pass/fail.
4. **Model abstention**: Models with confidence < 0.4 abstain instead of casting a weak vote.

### Rationale
More models should make the bot SMARTER, not more paralyzed. Additive scoring with weighted voting ensures high-accuracy models have proportionally more influence, and adding models increases potential confirmation signals rather than veto opportunities.

---

## Decision 4: Dual-GPU Distributed Training

### Context
The DGX Spark has a Blackwell GB10 (128GB), and the Windows PC now has an RTX 5060 Ti (16GB GDDR7). Both are Blackwell architecture with CUDA support, connected via 10GbE.

### Decision
Split training workloads across both GPUs:

| Workload | Machine | Reason |
|----------|---------|--------|
| XGBoost Phases 1-8 | Spark (GB10) | Data is local in MongoDB, needs 128GB for massive datasets |
| TFT (Phase 11) | Spark (GB10) | Multi-timeframe attention, benefits from 128GB |
| CNN-LSTM (Phase 9) | PC (5060 Ti) | Image gen is CPU-heavy (Ryzen IPC > Grace ARM), 16GB sufficient |
| FinBERT Sentiment | PC (5060 Ti) | Pre-trained transformer, fine-tune fits in 16GB |
| VAE Regime Detection | PC (5060 Ti) | Smaller model |
| RL Position Sizer | PC (5060 Ti) | Lightweight episode-based |

### Implementation
- `pc_training_worker.py`: Python script on Windows PC
- Connects to Spark's MongoDB over LAN (10GbE)
- Downloads training data subset, trains locally on RTX 5060 Ti
- Uploads trained model back to MongoDB `timeseries_models` collection
- Spark backend orchestrates: assigns workloads, waits for both GPUs to finish

### Impact
- Parallel training: ~8-10 hours total vs ~12-16 hours serial
- No code changes needed on existing Spark training pipeline (it just gets a companion)

---

## Decision 5: Scanner Performance Optimization

### Context
Current scanner: 10 symbols/batch, 1s delay, 60s interval, 200 symbol waves. Full universe coverage takes 12-15 minutes. With 128GB on Spark and Ryzen 5800XT on PC, these are dramatically underutilized.

### Decision
| Parameter | Current | New |
|-----------|---------|-----|
| symbols_per_batch | 10 | 100 |
| batch_delay | 1.0s | 0.1s |
| scan_interval | 60s | 30s |
| wave_size | 200 | 500 |
| bot_scan_interval | 30s | 15s |

Plus: Event-driven scanning (trigger on IB data push) and batch model inference.

### Impact
- Full universe coverage: 12-15 min -> 2-3 min
- Setup detection: up to 60s delay -> <1s (event-driven)
- Model inference: 132ms sequential -> 2ms batched

---

## Decision 6: Keep yfinance, Cross-Verify Earnings with IB

### Context
yfinance provides deep fundamental data (PE, revenue, margins, ROE, financial statements) that IB's `reqFundamentalData` doesn't easily replicate. Finnhub provides earnings calendars.

### Decision
- Keep yfinance for UI fundamentals display (cached, non-blocking, not in trading path)
- Keep Finnhub ONLY for earnings calendar
- Add IB per-symbol earnings dates as cross-verification layer
- When Finnhub and IB disagree on earnings date, flag for user review

### Rationale
yfinance is free (no API key), well-maintained, and provides data IB can't easily serve in bulk. It's read-only UI data, never in the trading decision path. The cost of replacing it exceeds the benefit.

---

## Decision 7: Symbol Universe Management

### Current State
Static Python lists in `index_symbols.py` (1,473 symbols). Last updated Feb 11, 2026. Not auto-refreshing.

### Decision (Phase 7)
1. Add quarterly auto-refresh script (pull from ETF holdings APIs)
2. Add dynamic expansion via IB Scanner API (`reqScannerSubscription`) for real-time top movers/RVOL leaders
3. Dynamically-added symbols are temporary (expire after market close) and don't persist to static lists
4. Static lists are the "core universe," dynamic adds are the "opportunity layer"

---

## Kill Chain Analysis — 27 Gates Where Good Trades Can Die

### Layer 0: Visibility (Can the bot see the stock?)
1. Not in 1,473-symbol universe -> INVISIBLE
2. No IB Pusher subscription -> No live quote
3. Historical data gap -> Weaker model predictions

### Layer 1: Pre-Filters (Instant elimination)
4. ADV < 100K -> REJECTED
5. Blacklisted symbol -> REJECTED
6. RVOL < 0.8 -> SKIPPED
7. ADV fetch fails -> REJECTED (fail-closed)

### Layer 2: Timing (When does it get scanned?)
8. Tier 3 symbol -> Wait 8-15 minutes for wave rotation
9. Scan interval 60s -> Blind spots between scans
10. Batch of 10 + 1s delay -> Artificial slowdown

### Layer 3: Pattern Detection
11. Setup type not in enabled list -> INVISIBLE
12. Time window mismatch -> REJECTED
13. Parameter just outside threshold (RSI 69.9 vs 70) -> MISSED

### Layer 4: Smart Filter (Historical performance)
14. Win rate < 35% -> ALL future instances SKIPPED (no decay!)
15. Win rate 35-50% + TQS < 75 -> SKIP
16. First time seeing setup -> 50% size (bootstrap mode)

### Layer 5: Confidence Gate (AI voting)
17. Regime against -> -25 points
18. Model disagrees -> -15 points, -30% size
19. Cross-model conflict -> -10 points, -20% size
20. CNN chart negative -> -10 points, -20% size
21. Score < 40 -> COMPLETE SKIP
22. Score 40-65 -> REDUCE to 60% size

### Layer 6: Risk Limits
23. Max positions reached -> ALL blocked
24. Daily loss limit hit -> Bot shuts down
25. Outside trading hours -> No trades
26. Already have position in symbol -> Skip
27. Top 20 alert cap per scan -> Overflow ignored

### Fixes Planned (Phase 4 + 4.5)
- Layers 1-3: Scanner optimization (batch sizes, intervals, event-driven)
- Layer 4: Rolling window decay, not cumulative all-time
- Layer 5: Additive scoring, weighted voting, model abstention, confidence floor
- Layer 6: Unchanged (risk limits are correct and necessary)
