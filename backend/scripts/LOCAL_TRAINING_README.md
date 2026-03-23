# SentCom Local AI Training Guide

## Quick Start

### 1. Install Dependencies
```bash
pip install pymongo lightgbm numpy pandas scikit-learn psutil
```

### 2. Set MongoDB Connection
```bash
# Your MongoDB Atlas connection string
export MONGO_URL="mongodb+srv://wilsonerik0_db_user:t1GH7fNMayacsZT6@sentcom.xqmcbz.mongodb.net/?appName=sentcom"
export DB_NAME="tradecommand"
```

### 3. Run Training

**Train single timeframe:**
```bash
python local_train.py --timeframe "5 mins"
python local_train.py --timeframe "15 mins"
python local_train.py --timeframe "30 mins"
```

**Train all timeframes (will take several hours):**
```bash
python local_train.py --timeframe "all"
```

**Custom settings:**
```bash
# Faster training with smaller batches (uses less memory)
python local_train.py --timeframe "5 mins" --batch-size 5

# More data per symbol
python local_train.py --timeframe "5 mins" --max-bars 20000
```

## Expected Training Times

| Timeframe | Symbols | Est. Time | Memory |
|-----------|---------|-----------|--------|
| 1 min     | ~4000   | 4-6 hours | 4-8 GB |
| 5 mins    | ~4000   | 3-4 hours | 4-8 GB |
| 15 mins   | ~4000   | 2-3 hours | 3-6 GB |
| 30 mins   | ~4000   | 1-2 hours | 2-4 GB |
| 1 hour    | ~4600   | 1-2 hours | 2-4 GB |
| 1 day     | ~4200   | 30-60 min | 1-2 GB |
| 1 week    | ~4000   | 15-30 min | 1-2 GB |

## Already Trained Models

These models are already saved and working:
- **1 day** - 53.7% accuracy (2.8M samples)
- **1 hour** - 55.4% accuracy (3.4M samples)

## Tips

1. **Start with daily/hourly** - they train faster and use less memory
2. **Run overnight** - intraday timeframes take several hours
3. **Monitor memory** - the script will stop if memory exceeds 8GB
4. **Models auto-save** - once training completes, models are saved to MongoDB and immediately available in the app

## Troubleshooting

**Connection refused:**
- Check your MongoDB connection string
- Ensure your IP is whitelisted in MongoDB Atlas

**Out of memory:**
- Reduce `--batch-size` (e.g., `--batch-size 5`)
- Close other applications

**Slow training:**
- This is normal for intraday data (millions of bars)
- The script processes in batches to prevent crashes
