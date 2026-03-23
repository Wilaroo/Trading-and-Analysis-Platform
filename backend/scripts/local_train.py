#!/usr/bin/env python3
"""
SentCom Local AI Training Script
================================
Run this script locally to train AI models on your full dataset.

Prerequisites:
1. Python 3.9+ installed
2. Install dependencies: pip install pymongo lightgbm numpy pandas scikit-learn psutil
3. MongoDB connection (your data is in MongoDB Atlas)

Usage:
    python local_train.py --timeframe "5 mins"
    python local_train.py --timeframe "all"
    python local_train.py --timeframe "5 mins" --batch-size 20 --max-bars 5000

Environment Variables:
    MONGO_URL - Your MongoDB connection string (required)
    DB_NAME - Database name (default: tradecommand)
"""

import os
import sys
import argparse
import time
import gc
import pickle
import base64
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

# Check dependencies
try:
    import numpy as np
    import pandas as pd
    from pymongo import MongoClient
    import lightgbm as lgb
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    import psutil
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install pymongo lightgbm numpy pandas scikit-learn psutil")
    sys.exit(1)


# Configuration
TIMEFRAME_SETTINGS = {
    "1 min": {"batch_size": 5, "max_bars": 10000, "model_name": "direction_predictor_1min"},
    "5 mins": {"batch_size": 10, "max_bars": 10000, "model_name": "direction_predictor_5min"},
    "15 mins": {"batch_size": 15, "max_bars": 10000, "model_name": "direction_predictor_15min"},
    "30 mins": {"batch_size": 20, "max_bars": 10000, "model_name": "direction_predictor_30min"},
    "1 hour": {"batch_size": 50, "max_bars": 10000, "model_name": "direction_predictor_1hour"},
    "1 day": {"batch_size": 100, "max_bars": 10000, "model_name": "direction_predictor_daily"},
    "1 week": {"batch_size": 100, "max_bars": 10000, "model_name": "direction_predictor_weekly"},
}

# LightGBM parameters (same as production)
LGB_PARAMS = {
    'objective': 'binary',
    'metric': 'binary_logloss',
    'boosting_type': 'gbdt',
    'num_leaves': 31,
    'learning_rate': 0.05,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 5,
    'verbose': -1,
    'n_jobs': -1,
    'force_col_wise': True,
}


def get_memory_mb():
    """Get current memory usage in MB"""
    return psutil.Process().memory_info().rss / 1024 / 1024


def extract_features(df: pd.DataFrame) -> tuple:
    """Extract features from OHLCV data"""
    if len(df) < 20:
        return None, None
    
    features = []
    targets = []
    
    # Sort by date
    df = df.sort_values('date').reset_index(drop=True)
    
    for i in range(20, len(df) - 1):
        window = df.iloc[i-20:i]
        
        try:
            # Price features
            close_prices = window['close'].values
            high_prices = window['high'].values
            low_prices = window['low'].values
            volumes = window['volume'].values
            
            # Returns
            returns = np.diff(close_prices) / close_prices[:-1]
            
            # Feature vector
            feature = [
                returns[-1],  # Last return
                returns[-5:].mean() if len(returns) >= 5 else returns.mean(),  # 5-period avg return
                returns.std(),  # Volatility
                (close_prices[-1] - close_prices.min()) / (close_prices.max() - close_prices.min() + 1e-8),  # Position in range
                volumes[-1] / (volumes.mean() + 1e-8),  # Relative volume
                (close_prices[-1] - close_prices.mean()) / (close_prices.std() + 1e-8),  # Z-score
                (high_prices[-1] - low_prices[-1]) / (close_prices[-1] + 1e-8),  # Range ratio
                returns[-1] - returns.mean(),  # Return deviation
            ]
            
            # Target: 1 if next close > current close
            target = 1 if df.iloc[i + 1]['close'] > df.iloc[i]['close'] else 0
            
            features.append(feature)
            targets.append(target)
            
        except Exception:
            continue
    
    return features, targets


def train_timeframe(db, timeframe: str, batch_size: int, max_bars: int):
    """Train model for a single timeframe"""
    
    print(f"\n{'='*60}")
    print(f"Training: {timeframe}")
    print(f"Batch size: {batch_size} symbols at a time")
    print(f"Max bars per symbol: {max_bars}")
    print(f"{'='*60}\n")
    
    settings = TIMEFRAME_SETTINGS.get(timeframe, {})
    model_name = settings.get("model_name", f"direction_predictor_{timeframe.replace(' ', '')}")
    
    # Get all symbols with data for this timeframe
    print("Finding symbols with data...")
    pipeline = [
        {"$match": {"bar_size": timeframe}},
        {"$group": {"_id": "$symbol"}},
    ]
    symbols = [doc["_id"] for doc in db.ib_historical_data.aggregate(pipeline)]
    print(f"Found {len(symbols):,} symbols with {timeframe} data")
    
    if not symbols:
        print(f"No data found for {timeframe}")
        return None
    
    # Process in batches
    all_features = []
    all_targets = []
    total_bars = 0
    symbols_with_data = 0
    start_time = time.time()
    
    for batch_idx in range(0, len(symbols), batch_size):
        batch_symbols = symbols[batch_idx:batch_idx + batch_size]
        batch_num = batch_idx // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        
        print(f"\nBatch {batch_num}/{total_batches}: Processing {len(batch_symbols)} symbols...")
        
        for symbol in batch_symbols:
            try:
                # Fetch data for symbol
                cursor = db.ib_historical_data.find(
                    {"symbol": symbol, "bar_size": timeframe},
                    {"date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "_id": 0}
                ).sort("date", 1).limit(max_bars)
                
                data = list(cursor)
                if len(data) < 25:
                    continue
                
                df = pd.DataFrame(data)
                features, targets = extract_features(df)
                
                if features and len(features) > 0:
                    all_features.extend(features)
                    all_targets.extend(targets)
                    symbols_with_data += 1
                    total_bars += len(data)
                    
            except Exception as e:
                print(f"  Error processing {symbol}: {e}")
                continue
        
        # Progress update
        elapsed = time.time() - start_time
        mem_mb = get_memory_mb()
        pct = (batch_idx + len(batch_symbols)) / len(symbols) * 100
        print(f"  Progress: {pct:.1f}% | Samples: {len(all_features):,} | Memory: {mem_mb:.0f} MB | Elapsed: {elapsed/60:.1f} min")
        
        # Garbage collection
        gc.collect()
        
        # Memory safety check
        if mem_mb > 8000:  # 8GB limit for local
            print(f"WARNING: High memory usage ({mem_mb:.0f} MB) - stopping early")
            break
    
    print(f"\nFeature extraction complete!")
    print(f"  Total samples: {len(all_features):,}")
    print(f"  Symbols with data: {symbols_with_data:,}")
    print(f"  Total bars: {total_bars:,}")
    
    if len(all_features) < 100:
        print("Insufficient data for training")
        return None
    
    # Convert to numpy
    X = np.array(all_features, dtype=np.float32)
    y = np.array(all_targets, dtype=np.int32)
    
    # Handle NaN/Inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    
    # Train/test split
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print(f"\nTraining LightGBM model...")
    print(f"  Training samples: {len(X_train):,}")
    print(f"  Validation samples: {len(X_val):,}")
    
    # Create datasets
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    # Train
    model = lgb.train(
        LGB_PARAMS,
        train_data,
        num_boost_round=500,
        valid_sets=[train_data, val_data],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50),
            lgb.log_evaluation(period=100)
        ]
    )
    
    # Evaluate
    val_preds = model.predict(X_val)
    val_preds_binary = (val_preds > 0.5).astype(int)
    accuracy = (val_preds_binary == y_val).mean()
    
    elapsed_total = time.time() - start_time
    
    print(f"\n{'='*60}")
    print(f"Training Complete: {timeframe}")
    print(f"  Accuracy: {accuracy*100:.2f}%")
    print(f"  Training samples: {len(X_train):,}")
    print(f"  Total time: {elapsed_total/60:.1f} minutes")
    print(f"{'='*60}\n")
    
    # Save to MongoDB
    print("Saving model to database...")
    
    version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    model_bytes = pickle.dumps(model)
    model_b64 = base64.b64encode(model_bytes).decode('utf-8')
    
    model_doc = {
        "name": model_name,
        "version": version,
        "model_data": model_b64,
        "metrics": {
            "accuracy": accuracy,
            "training_samples": len(X_train),
            "validation_samples": len(X_val),
        },
        "updated_at": datetime.now(timezone.utc)
    }
    
    db.timeseries_models.update_one(
        {"name": model_name},
        {"$set": model_doc},
        upsert=True
    )
    
    # Save to training history
    history_doc = {
        "model_name": model_name,
        "bar_size": timeframe,
        "accuracy": accuracy,
        "training_samples": len(X_train),
        "validation_samples": len(X_val),
        "symbols_used": symbols_with_data,
        "total_bars": total_bars,
        "version": version,
        "elapsed_seconds": elapsed_total,
        "timestamp": datetime.now(timezone.utc)
    }
    
    db.timeseries_training_history.insert_one(history_doc)
    
    print(f"Model saved: {model_name} ({version})")
    
    return {
        "timeframe": timeframe,
        "accuracy": accuracy,
        "samples": len(X_train),
        "symbols": symbols_with_data,
        "elapsed_minutes": elapsed_total / 60
    }


def main():
    parser = argparse.ArgumentParser(description="SentCom Local AI Training")
    parser.add_argument("--timeframe", type=str, default="5 mins",
                        help="Timeframe to train (e.g., '5 mins', '1 hour', 'all')")
    parser.add_argument("--batch-size", type=int, default=None,
                        help="Override batch size (symbols per batch)")
    parser.add_argument("--max-bars", type=int, default=None,
                        help="Override max bars per symbol")
    parser.add_argument("--mongo-url", type=str, default=None,
                        help="MongoDB connection string (or set MONGO_URL env var)")
    args = parser.parse_args()
    
    # Get MongoDB connection
    mongo_url = args.mongo_url or os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MongoDB connection string required")
        print("Set MONGO_URL environment variable or use --mongo-url")
        print("\nExample:")
        print('  export MONGO_URL="mongodb+srv://user:pass@cluster.mongodb.net/"')
        print('  python local_train.py --timeframe "5 mins"')
        sys.exit(1)
    
    db_name = os.environ.get("DB_NAME", "tradecommand")
    
    print("SentCom Local AI Training")
    print("=" * 60)
    print(f"MongoDB: {mongo_url[:50]}...")
    print(f"Database: {db_name}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Memory: {get_memory_mb():.0f} MB")
    print("=" * 60)
    
    # Connect to MongoDB
    print("\nConnecting to MongoDB...")
    client = MongoClient(mongo_url)
    db = client[db_name]
    
    # Test connection
    try:
        db.command("ping")
        print("Connected successfully!")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
    
    # Determine timeframes to train
    if args.timeframe.lower() == "all":
        timeframes = list(TIMEFRAME_SETTINGS.keys())
    else:
        timeframes = [args.timeframe]
    
    results = []
    
    for tf in timeframes:
        settings = TIMEFRAME_SETTINGS.get(tf, {"batch_size": 50, "max_bars": 10000})
        batch_size = args.batch_size or settings["batch_size"]
        max_bars = args.max_bars or settings["max_bars"]
        
        result = train_timeframe(db, tf, batch_size, max_bars)
        if result:
            results.append(result)
        
        # GC between timeframes
        gc.collect()
    
    # Summary
    print("\n" + "=" * 60)
    print("TRAINING SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"  {r['timeframe']:12} | {r['accuracy']*100:5.1f}% | {r['samples']:>10,} samples | {r['elapsed_minutes']:.1f} min")
    print("=" * 60)
    print("Models saved to MongoDB - they will be available in the app!")


if __name__ == "__main__":
    main()
