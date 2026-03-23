# SentCom AI Training Guide

## Overview

The SentCom AI Trading Bot uses **LightGBM** machine learning models to predict price direction across 7 timeframes. This guide explains how to train and maintain these models.

---

## Training Methods

### 1. Full Universe Training (Recommended for Production)

Trains on ALL available historical data for maximum accuracy.

**PowerShell Command:**
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/train-full-universe-all" -Method POST -ContentType "application/json" -Body '{"symbol_batch_size": 50, "max_bars_per_symbol": 1000}'
```

**What it does:**
- Trains all 7 timeframes: 1 day, 1 hour, 5 mins, 15 mins, 30 mins, 1 min, 1 week
- Uses chunked loading to prevent memory crashes
- Expected runtime: 1-3 hours (depending on data size and indexes)

**Parameters:**
- `symbol_batch_size`: How many symbols to process at once (default: 50, increase for faster training if you have RAM)
- `max_bars_per_symbol`: Max historical bars per symbol (default: 1000)
- `timeframes`: Optional array to train specific timeframes, e.g., `["1 day", "1 hour"]`

### 2. Quick Train (For Testing)

Trains a single timeframe on a sample of data.

**PowerShell Command:**
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/train" -Method POST -ContentType "application/json" -Body '{"bar_size": "1 day", "num_symbols": 50}'
```

### 3. Train Single Timeframe (Full Data)

Train one specific timeframe on all available data.

**PowerShell Command:**
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/train-full-universe" -Method POST -ContentType "application/json" -Body '{"bar_size": "1 day", "symbol_batch_size": 50, "max_bars_per_symbol": 1000}'
```

---

## Monitoring Training Progress

### Check Training Status
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/training-status" | Select-Object -ExpandProperty Content
```

**Response fields:**
- `training_in_progress`: true/false
- `phase`: "loading_data", "training", "complete"
- `elapsed_seconds`: How long training has been running
- `message`: Current status message

### View Training History
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/training-history?limit=10" | Select-Object -ExpandProperty Content
```

### Check Model Status
```powershell
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/status" | Select-Object -ExpandProperty Content
```

---

## Supported Timeframes

| Timeframe | Model Name | Forecast Horizon |
|-----------|------------|------------------|
| 1 min | direction_predictor_1min | 5 bars (5 minutes) |
| 5 mins | direction_predictor_5min | 5 bars (25 minutes) |
| 15 mins | direction_predictor_15min | 5 bars (75 minutes) |
| 30 mins | direction_predictor_30min | 5 bars (2.5 hours) |
| 1 hour | direction_predictor_hourly | 5 bars (5 hours) |
| 1 day | direction_predictor_daily | 5 bars (5 days) |
| 1 week | direction_predictor_weekly | 5 bars (5 weeks) |

---

## Performance Tips

### 1. Add MongoDB Indexes (One-Time)

Run this in MongoDB Compass or shell to speed up training queries:

```javascript
// Connect to your database first, then run:
db.ib_historical_data.createIndex({ "bar_size": 1, "symbol": 1 });
db.ib_historical_data.createIndex({ "bar_size": 1 });
db.ib_historical_data.createIndex({ "symbol": 1, "bar_size": 1, "date": 1 });
```

This can reduce training time from 30 minutes to 5 minutes.

### 2. Memory Management

- **Recommended RAM**: 16GB+ for full universe training
- If training crashes, reduce `symbol_batch_size` to 25
- Close other applications during training

### 3. GPU Acceleration (Optional)

LightGBM can use GPU for faster training. Requires:
1. NVIDIA GPU with CUDA
2. LightGBM compiled with GPU support

To enable (after confirming GPU LightGBM is installed):
Edit `backend/services/ai_modules/timeseries_gbm.py` and uncomment:
```python
"device": "gpu",
"gpu_platform_id": 0,
"gpu_device_id": 0,
```

---

## Troubleshooting

### Training Crashes / Backend Dies

**Symptoms:**
- Backend terminal closes
- "Connection refused" errors
- Memory usage spikes to 90%+

**Solutions:**
1. Reduce `symbol_batch_size` from 50 to 25
2. Reduce `max_bars_per_symbol` from 1000 to 500
3. Close other applications to free RAM
4. Add MongoDB indexes (see above)

### "Model Save Failed" Error

**Symptoms:**
- Training completes but model doesn't save
- Error about `model_id` or duplicate key

**Solution:**
Run in MongoDB Compass or shell:
```javascript
db.timeseries_models.deleteMany({ model_id: null });
```

### Training Takes Too Long

**Symptoms:**
- Training stuck at "loading_data" phase
- Takes 30+ minutes

**Solutions:**
1. Add MongoDB indexes (most important!)
2. Check MongoDB Atlas alerts for slow queries
3. Reduce number of symbols or bars

### No Symbols Found

**Symptoms:**
- Error: "No symbols found for 1 day"

**Solution:**
You need to collect historical data first using the IB Historical Collector.

---

## Best Practices

1. **Train after data collection**: Always train after collecting new historical data
2. **Monitor accuracy**: Accuracy should be above 52% to be useful
3. **Train weekly**: Retrain models weekly to capture recent market patterns
4. **Start with 1 day**: The "1 day" timeframe usually has the most data and trains fastest
5. **Check training history**: Compare accuracy over time to ensure models aren't degrading

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai-modules/timeseries/train-full-universe-all` | POST | Train all timeframes |
| `/api/ai-modules/timeseries/train-full-universe` | POST | Train single timeframe |
| `/api/ai-modules/timeseries/train` | POST | Quick train (sample) |
| `/api/ai-modules/timeseries/training-status` | GET | Check training progress |
| `/api/ai-modules/timeseries/training-history` | GET | View past training runs |
| `/api/ai-modules/timeseries/status` | GET | Check model status |

---

## Example: Complete Training Workflow

```powershell
# 1. Check current model status
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/status" | Select-Object -ExpandProperty Content

# 2. Start full universe training
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/train-full-universe-all" -Method POST -ContentType "application/json" -Body '{"symbol_batch_size": 50, "max_bars_per_symbol": 1000}'

# 3. Monitor progress (repeat every few minutes)
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/training-status" | Select-Object -ExpandProperty Content

# 4. When complete, check results
Invoke-WebRequest -Uri "http://localhost:8001/api/ai-modules/timeseries/training-history?limit=7" | Select-Object -ExpandProperty Content
```

---

*Last Updated: March 2026*
