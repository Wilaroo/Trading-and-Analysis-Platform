"""
XGBoost Time-Series Forecasting Model (GPU-accelerated)

Predicts directional price movement (up/down/flat) using features
extracted from OHLCV data.

Key Features:
- Native CUDA GPU acceleration via XGBoost (tree_method='hist', device='cuda')
- Probability outputs for confidence scoring
- Model persistence to MongoDB (XGBoost JSON format)
- Performance tracking and evaluation
- Best-model protection (only promotes if accuracy improves)

Replaces LightGBM (which required OpenCL, fell back to CPU on DGX Spark).
XGBoost with native CUDA support unlocks the Blackwell GB10 GPU.
"""

import logging
import json
import base64
import os
import io
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import xgboost as xgb

from .timeseries_features import (
    TimeSeriesFeatureEngineer,
    FeatureSet,
    get_feature_engineer
)

logger = logging.getLogger(__name__)


def _extract_symbol_worker(args):
    """
    Top-level worker function for ProcessPoolExecutor.

    Must be at module scope so pickle can serialize it across processes.

    Args:
        args: tuple of (symbol, bars, lookback, forecast_horizon)
              - bars in chronological order (oldest first)

    Returns:
        (feature_matrix, targets) or None
    """
    symbol, bars, lookback, forecast_horizon = args
    try:
        fe = TimeSeriesFeatureEngineer(lookback)
        feat_matrix = fe.extract_features_bulk(bars)
        if feat_matrix is None or len(feat_matrix) == 0:
            return None

        # feat_matrix row j corresponds to bar at index (lookback - 1 + j)
        # Target: binary — did price go up over forecast_horizon bars?
        closes = np.array([b.get("close", 0) for b in bars], dtype=np.float64)
        closes = np.where(closes == 0, 1.0, closes)

        n_win = len(feat_matrix)
        # We can only compute targets for windows where future price exists
        usable = n_win - forecast_horizon
        if usable < 1:
            return None

        # Current close for each window
        base_idx = lookback - 1  # first window's bar index
        current_prices = closes[base_idx: base_idx + usable]
        future_prices = closes[base_idx + forecast_horizon: base_idx + forecast_horizon + usable]

        targets = (future_prices > current_prices).astype(np.float32)

        # Trim feature matrix to match
        feat_matrix = feat_matrix[:usable]

        return (feat_matrix, targets)
    except Exception as e:
        logger.warning(f"Worker error for {symbol}: {e}")
        return None


@dataclass
class Prediction:
    """Model prediction result"""
    symbol: str = ""
    direction: str = ""  # "up", "down", "flat"
    probability_up: float = 0.5
    probability_down: float = 0.5
    confidence: float = 0.0
    
    # Model metadata
    model_version: str = ""
    feature_count: int = 0
    
    # Timestamp
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ModelMetrics:
    """Model performance metrics"""
    accuracy: float = 0.0
    precision_up: float = 0.0
    precision_down: float = 0.0
    recall_up: float = 0.0
    recall_down: float = 0.0
    f1_up: float = 0.0
    f1_down: float = 0.0
    
    # Sample info
    training_samples: int = 0
    validation_samples: int = 0
    
    # Feature importance
    top_features: List[str] = field(default_factory=list)
    
    # Metadata
    last_trained: str = ""
    last_evaluated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class TimeSeriesGBM:
    """
    XGBoost model for directional price forecasting (GPU-accelerated).
    
    Predicts probability of price moving up/down over the forecast horizon.
    Uses native CUDA via tree_method='hist' + device='cuda' on Blackwell GB10.
    """
    
    MODEL_COLLECTION = "timeseries_models"
    MODEL_ARCHIVE_COLLECTION = "timeseries_model_archive"
    PREDICTIONS_COLLECTION = "timeseries_predictions"
    
    # Check for CUDA GPU availability (via PyTorch if installed)
    GPU_AVAILABLE = False
    GPU_NAME = "unknown"
    try:
        import torch
        GPU_AVAILABLE = torch.cuda.is_available()
        if GPU_AVAILABLE:
            GPU_NAME = torch.cuda.get_device_name(0)
            logger.info(f"CUDA GPU detected: {GPU_NAME}")
    except ImportError:
        pass

    # XGBoost GPU support detection
    XGB_GPU_AVAILABLE = False
    try:
        _test_X = np.random.rand(100, 5).astype(np.float32)
        _test_y = np.random.randint(0, 2, 100).astype(np.float32)
        _test_dm = xgb.DMatrix(_test_X, label=_test_y)
        _test_params = {
            'tree_method': 'hist', 'device': 'cuda',
            'objective': 'binary:logistic', 'max_depth': 3,
            'verbosity': 0,
        }
        _test_model = xgb.train(_test_params, _test_dm, num_boost_round=2)
        XGB_GPU_AVAILABLE = True
        del _test_model, _test_dm, _test_X, _test_y
        logger.info("XGBoost CUDA GPU acceleration AVAILABLE")
        import multiprocessing as _mp
        if _mp.current_process().name == "MainProcess":
            print("[GPU] XGBoost CUDA acceleration ENABLED")
    except Exception as _xgb_err:
        logger.info(f"XGBoost GPU not available ({_xgb_err}), will use CPU")
        import multiprocessing as _mp
        if _mp.current_process().name == "MainProcess":
            print("[GPU] XGBoost GPU NOT available — training will use CPU")

    # Default model parameters — optimized for XGBoost with GPU
    DEFAULT_PARAMS = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "tree_method": "hist",
        "max_depth": 8,
        "learning_rate": 0.03,
        "colsample_bytree": 0.7,
        "subsample": 0.7,
        "min_child_weight": 50,
        "max_bin": 256,
        "verbosity": 0,
        "nthread": -1,
        "seed": 42,
    }

    # Enable GPU if available
    if XGB_GPU_AVAILABLE:
        DEFAULT_PARAMS["device"] = "cuda"
        logger.info("XGBoost GPU acceleration ENABLED (device=cuda, max_bin=256)")
    else:
        DEFAULT_PARAMS["device"] = "cpu"
    
    # Prediction threshold for "up" classification
    UP_THRESHOLD = 0.52
    
    def __init__(
        self,
        model_name: str = "direction_predictor",
        forecast_horizon: int = 5,
        params: Dict = None
    ):
        self.model_name = model_name
        self.forecast_horizon = forecast_horizon
        self.params = params or self.DEFAULT_PARAMS.copy()
        
        self._model: Optional[xgb.Booster] = None
        self._feature_engineer = get_feature_engineer()
        self._feature_names = self._feature_engineer.get_feature_names()
        
        # Database
        self._db = None
        
        # Metrics
        self._metrics = ModelMetrics()
        self._version = "v0.0.0"
        self._num_classes = 2
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            # Try to load existing model
            self._load_model()
            
    def _load_model(self):
        """Load model from database.
        
        Loading priority:
        1. Try exact model name match
        2. Fallback to "direction_predictor_daily" (most reliable model)
        3. Fallback to any available trained model
        
        Supports both XGBoost JSON (new) and legacy LightGBM pickle formats.
        """
        if self._db is None:
            return
            
        try:
            # Try to load exact model name first
            doc = self._db[self.MODEL_COLLECTION].find_one({"name": self.model_name})
            
            # Fallback 1: Try to load the daily model (most commonly trained)
            if not doc or "model_data" not in doc:
                logger.info(f"Model '{self.model_name}' not found, trying 'direction_predictor_daily'...")
                doc = self._db[self.MODEL_COLLECTION].find_one({"name": "direction_predictor_daily"})
            
            # Fallback 2: Try to load any available model
            if not doc or "model_data" not in doc:
                logger.info("Daily model not found, searching for any trained model...")
                doc = self._db[self.MODEL_COLLECTION].find_one(
                    {"model_data": {"$exists": True}},
                    sort=[("updated_at", -1)]  # Get most recently updated
                )
            
            if doc and "model_data" in doc:
                model_bytes = base64.b64decode(doc["model_data"])
                model_format = doc.get("model_format", "pickle")  # Default to pickle for legacy
                
                if model_format == "xgboost_json":
                    # New XGBoost JSON format
                    self._model = xgb.Booster()
                    self._model.load_model(bytearray(model_bytes))
                else:
                    # Legacy LightGBM pickle format — try to load via pickle
                    # This allows transition period where old models still work for inference
                    try:
                        import pickle
                        legacy_model = pickle.loads(model_bytes)
                        # LightGBM Booster loaded — can't use directly with XGBoost
                        # Log warning and skip (will retrain)
                        logger.warning(
                            f"Found legacy LightGBM model '{doc.get('name', 'unknown')}'. "
                            f"Needs retraining with XGBoost. Skipping load."
                        )
                        self._model = None
                        return
                    except Exception:
                        logger.warning("Could not load legacy model format")
                        return
                
                loaded_name = doc.get("name", "unknown")
                loaded_version = doc.get("version", "v0.0.0")
                self._metrics = ModelMetrics(**doc.get("metrics", {}))
                logger.info(f"Loaded model '{loaded_name}' version {loaded_version} (requested: {self.model_name})")
                if loaded_name == self.model_name:
                    self._version = loaded_version
                else:
                    self._version = "v0.0.0"
                    logger.info(f"Using fallback model '{loaded_name}' for initial weights; new model '{self.model_name}' will start at v0.1.0")
            else:
                logger.warning("No trained models found in database")
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
            
    def _save_model(self):
        """Save model to database with best-model protection.
        Uses XGBoost native JSON serialization (not pickle).
        
        Logic:
        1. Always archive the new model (for learning/reference)
        2. Only promote to active if accuracy >= current active model
        3. If new model is worse, log it but keep the old active model
        """
        if self._db is None or self._model is None:
            return False
            
        try:
            # Serialize XGBoost model to JSON bytes
            buffer = io.BytesIO()
            self._model.save_model(buffer)
            model_bytes = buffer.getvalue()
            model_data = base64.b64encode(model_bytes).decode("utf-8")
            new_accuracy = self._metrics.accuracy if self._metrics else 0
            
            model_doc = {
                "name": self.model_name,
                "model_id": self.model_name,
                "model_data": model_data,
                "model_format": "xgboost_json",  # Marks this as XGBoost format
                "engine": "xgboost",
                "version": self._version,
                "metrics": self._metrics.to_dict(),
                "params": {k: v for k, v in self.params.items() if not callable(v)},
                "feature_names": self._feature_names,
                "forecast_horizon": self.forecast_horizon,
                "saved_at": datetime.now(timezone.utc).isoformat()
            }
            
            # Step 1: Always archive the new model for future reference
            archive_doc = {**model_doc, "archived_at": datetime.now(timezone.utc).isoformat()}
            archive_doc.pop("model_id", None)  # Archive doesn't need unique constraint
            self._db[self.MODEL_ARCHIVE_COLLECTION].insert_one(archive_doc)
            logger.info(f"Archived model {self.model_name} {self._version} (accuracy={new_accuracy:.4f})")
            
            # Step 2: Check current active model's accuracy
            current_active = self._db[self.MODEL_COLLECTION].find_one(
                {"name": self.model_name},
                {"metrics": 1, "version": 1, "_id": 0}
            )
            
            should_promote = True
            if current_active and "metrics" in current_active:
                current_accuracy = current_active["metrics"].get("accuracy", 0)
                current_version = current_active.get("version", "unknown")
                
                if new_accuracy < current_accuracy:
                    should_promote = False
                    logger.warning(
                        f"Model protection: NEW {self._version} accuracy ({new_accuracy:.4f}) "
                        f"< ACTIVE {current_version} accuracy ({current_accuracy:.4f}). "
                        f"Keeping active model. New model archived for reference."
                    )
                elif new_accuracy == current_accuracy:
                    logger.info(
                        f"Model accuracy unchanged ({new_accuracy:.4f}). Updating active model."
                    )
                else:
                    logger.info(
                        f"Model improved: {current_accuracy:.4f} -> {new_accuracy:.4f} (+{new_accuracy - current_accuracy:.4f}). Promoting."
                    )
            
            # Step 3: Promote to active if better (or first model)
            if should_promote:
                model_doc["updated_at"] = datetime.now(timezone.utc).isoformat()
                model_doc["promoted_at"] = datetime.now(timezone.utc).isoformat()
                self._db[self.MODEL_COLLECTION].update_one(
                    {"name": self.model_name},
                    {"$set": model_doc},
                    upsert=True
                )
                logger.info(f"Promoted model {self.model_name} {self._version} as active (accuracy={new_accuracy:.4f})")
            else:
                # Reload the active model since we didn't promote
                self._load_model()
                
            return should_promote
        except Exception as e:
            logger.error(f"Could not save model: {e}")
            return False
    
    def get_model_history(self, limit: int = 20) -> List[Dict]:
        """Get archived model history for analysis and comparison"""
        if self._db is None:
            return []
        try:
            docs = list(self._db[self.MODEL_ARCHIVE_COLLECTION].find(
                {"name": self.model_name},
                {"_id": 0, "model_data": 0}  # Exclude heavy binary data
            ).sort("archived_at", -1).limit(limit))
            return docs
        except Exception as e:
            logger.warning(f"Could not fetch model history: {e}")
            return []
            
    # --- Feature Caching (Phase 3) ---
    FEATURE_CACHE_COLLECTION = "feature_cache"
    
    def _get_feature_cache_key(self, symbol: str, bar_size: str = "default") -> str:
        """Generate a cache key for a symbol's features"""
        return f"{symbol}_{bar_size}_{self.forecast_horizon}"
    
    def _save_features_to_cache(self, symbol: str, features: List[List[float]], targets: List[int], bar_size: str = "default"):
        """Save precomputed features to MongoDB for reuse across training cycles"""
        if self._db is None:
            return
        try:
            import base64
            import json
            cache_key = self._get_feature_cache_key(symbol, bar_size)
            # Store as compressed JSON bytes
            data = json.dumps({"features": features, "targets": targets}).encode()
            encoded = base64.b64encode(data).decode("utf-8")
            self._db[self.FEATURE_CACHE_COLLECTION].update_one(
                {"cache_key": cache_key},
                {"$set": {
                    "cache_key": cache_key,
                    "symbol": symbol,
                    "bar_size": bar_size,
                    "forecast_horizon": self.forecast_horizon,
                    "num_features": len(self._feature_names),
                    "num_samples": len(features),
                    "data": encoded,
                    "cached_at": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
        except Exception as e:
            logger.debug(f"Feature cache save failed for {symbol}: {e}")
    
    def _load_features_from_cache(self, symbol: str, bar_size: str = "default", max_age_hours: int = 168) -> Optional[dict]:
        """Load precomputed features from cache. Returns None if stale or missing.
        Default max_age is 168 hours (1 week) — features only need recomputation
        when new bars are collected or feature engineering changes."""
        if self._db is None:
            return None
        try:
            import json
            cache_key = self._get_feature_cache_key(symbol, bar_size)
            doc = self._db[self.FEATURE_CACHE_COLLECTION].find_one(
                {"cache_key": cache_key},
                {"_id": 0}
            )
            if not doc or "data" not in doc:
                return None
            # Check staleness
            cached_at = doc.get("cached_at", "")
            if cached_at:
                try:
                    cache_time = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - cache_time).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        return None
                except Exception:
                    pass
            # Verify feature count matches current feature set
            if doc.get("num_features", 0) != len(self._feature_names):
                return None
            data = json.loads(base64.b64decode(doc["data"]))
            return data
        except Exception as e:
            logger.debug(f"Feature cache load failed for {symbol}: {e}")
            return None
            
    def train(
        self,
        bars_by_symbol: Dict[str, List[Dict]],
        validation_split: float = 0.2,
        num_boost_round: int = 100,
        early_stopping_rounds: int = 10
    ) -> ModelMetrics:
        """
        Train the model on historical data.
        
        Args:
            bars_by_symbol: Dict of symbol -> list of OHLCV bars (oldest first)
            validation_split: Fraction of data for validation
            num_boost_round: Number of boosting rounds
            early_stopping_rounds: Early stopping patience
            
        Returns:
            ModelMetrics with training results
        """
        logger.info(f"Training model on {len(bars_by_symbol)} symbols...")
        
        # Extract features for all symbols (with caching)
        all_features = []
        all_targets = []
        cache_hits = 0
        cache_misses = 0
        
        symbols_processed = 0
        total_symbols = len(bars_by_symbol)
        for symbol, bars in bars_by_symbol.items():
            symbols_processed += 1
            if symbols_processed % 10 == 0 or symbols_processed == total_symbols:
                logger.info(f"[Feature extraction] {symbols_processed}/{total_symbols} symbols processed ({len(all_features)} samples so far, cache: {cache_hits} hits / {cache_misses} misses)")
            if len(bars) < 50 + self.forecast_horizon:
                continue
            
            # Try loading from feature cache first
            cached = self._load_features_from_cache(symbol)
            if cached and cached.get("features") and cached.get("targets"):
                all_features.extend(cached["features"])
                all_targets.extend(cached["targets"])
                cache_hits += 1
                continue
            
            cache_misses += 1
            
            # Use VECTORIZED bulk extraction (processes entire symbol in one pass)
            # instead of per-window Python loop — 10-50x faster
            bulk_features = self._feature_engineer.extract_features_bulk(bars)
            
            if bulk_features is not None and len(bulk_features) > self.forecast_horizon:
                # bulk_features shape: (n_windows, 46) — one row per valid window
                # Calculate targets for each window
                closes = np.array([b.get("close", 0) for b in bars], dtype=np.float32)
                lb = self._feature_engineer.lookback  # 50
                
                # Window i corresponds to bar index (lb-1+i) as the "current" bar
                # Target: price at (current + forecast_horizon) vs current
                n_usable = min(len(bulk_features), len(closes) - lb - self.forecast_horizon + 1)
                
                if n_usable > 0:
                    symbol_features = bulk_features[:n_usable].tolist()
                    symbol_targets = []
                    for i in range(n_usable):
                        current_idx = lb - 1 + i
                        future_idx = current_idx + self.forecast_horizon
                        if future_idx < len(closes) and closes[current_idx] > 0:
                            target_return = (closes[future_idx] - closes[current_idx]) / closes[current_idx]
                            symbol_targets.append(1 if target_return > 0 else 0)
                        else:
                            symbol_targets.append(0)
                    
                    all_features.extend(symbol_features)
                    all_targets.extend(symbol_targets)
                    # Save to cache for next training cycle
                    self._save_features_to_cache(symbol, symbol_features, symbol_targets)
        
        logger.info(f"Feature cache stats: {cache_hits} hits, {cache_misses} computed fresh")
                    
        if len(all_features) < 100:
            logger.warning(f"Insufficient training data: {len(all_features)} samples")
            return ModelMetrics()
            
        logger.info(f"Extracted {len(all_features)} training samples")
        
        # Convert to numpy (float32 to halve memory on 128GB Spark)
        X = np.array(all_features, dtype=np.float32)
        y = np.array(all_targets, dtype=np.float32)
        
        # Log class distribution
        n_up = np.sum(y == 1)
        n_down = np.sum(y == 0)
        logger.info(f"Class distribution: UP={n_up} ({n_up/len(y)*100:.1f}%), DOWN={n_down} ({n_down/len(y)*100:.1f}%)")
        
        # Split train/validation
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # Create XGBoost DMatrix datasets
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=self._feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=self._feature_names)
        
        # Train model with early stopping
        self._model = xgb.train(
            self.params,
            dtrain,
            num_boost_round=num_boost_round * 2,  # More rounds for better learning
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False
        )
        
        # Evaluate with dynamic threshold
        y_pred_proba = self._model.predict(dval)
        
        # Use class-specific threshold for better recall
        y_pred = (y_pred_proba > self.UP_THRESHOLD).astype(int)
        
        # Calculate metrics
        accuracy = np.mean(y_pred == y_val)
        
        # Precision/Recall for up direction
        tp_up = np.sum((y_pred == 1) & (y_val == 1))
        fp_up = np.sum((y_pred == 1) & (y_val == 0))
        fn_up = np.sum((y_pred == 0) & (y_val == 1))
        
        precision_up = tp_up / (tp_up + fp_up) if (tp_up + fp_up) > 0 else 0
        recall_up = tp_up / (tp_up + fn_up) if (tp_up + fn_up) > 0 else 0
        f1_up = 2 * precision_up * recall_up / (precision_up + recall_up) if (precision_up + recall_up) > 0 else 0
        
        # Feature importance
        importance_dict = self._model.get_score(importance_type="gain")
        # Sort by gain and get top 10
        sorted_features = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)[:10]
        top_features = [f[0] for f in sorted_features]
        
        # Update metrics
        self._metrics = ModelMetrics(
            accuracy=float(accuracy),
            precision_up=float(precision_up),
            recall_up=float(recall_up),
            f1_up=float(f1_up),
            training_samples=len(X_train),
            validation_samples=len(X_val),
            top_features=top_features,
            last_trained=datetime.now(timezone.utc).isoformat()
        )
        
        # Update version
        version_parts = self._version.replace("v", "").split(".")
        minor = int(version_parts[1]) + 1 if len(version_parts) > 1 else 1
        self._version = f"v0.{minor}.0"
        
        # Save model
        self._save_model()
        
        logger.info(f"Training complete: accuracy={accuracy:.3f}, precision_up={precision_up:.3f}, f1_up={f1_up:.3f}")
        
        return self._metrics

    def train_vectorized(
        self,
        bars_by_symbol: Dict[str, List[Dict]],
        feature_engineer=None,
        num_boost_round: int = 200,
        early_stopping_rounds: int = 20,
    ) -> ModelMetrics:
        """
        Vectorized training with multiprocess extraction and memory-efficient chunking.
        Uses all CPU cores for feature extraction, processes symbols in chunks to limit RAM.
        """
        from concurrent.futures import ProcessPoolExecutor, as_completed
        import gc

        if feature_engineer is None:
            from services.ai_modules.timeseries_features import get_feature_engineer
            feature_engineer = get_feature_engineer(50)

        total_symbols = len(bars_by_symbol)
        n_workers = max(1, os.cpu_count() - 2)  # Leave 2 cores for OS/backend
        chunk_size = 200  # Process 200 symbols at a time to limit memory

        logger.info(f"Training model (vectorized, {n_workers} workers) on {total_symbols} symbols...")

        all_features = []
        all_targets = []
        symbols_processed = 0

        # Process symbols in memory-efficient chunks
        symbol_items = list(bars_by_symbol.items())
        for chunk_start in range(0, total_symbols, chunk_size):
            chunk = symbol_items[chunk_start:chunk_start + chunk_size]
            chunk_end = min(chunk_start + chunk_size, total_symbols)

            # Prepare worker args: (bars, lookback, forecast_horizon)
            worker_args = []
            for symbol, bars in chunk:
                if len(bars) >= 50 + self.forecast_horizon:
                    worker_args.append((symbol, bars, 50, self.forecast_horizon))

            # Parallel extraction across CPU cores
            chunk_results = []
            try:
                with ProcessPoolExecutor(max_workers=n_workers) as pool:
                    futures = {pool.submit(_extract_symbol_worker, args): args[0] for args in worker_args}
                    for future in as_completed(futures):
                        try:
                            result = future.result(timeout=300)
                            if result is not None:
                                chunk_results.append(result)
                        except Exception as e:
                            logger.warning(f"Worker failed for {futures[future]}: {e}")
            except Exception as e:
                # Fallback to single-process if multiprocessing fails
                logger.warning(f"Multiprocess failed ({e}), falling back to single-process")
                for args in worker_args:
                    result = _extract_symbol_worker(args)
                    if result is not None:
                        chunk_results.append(result)

            # Collect results from this chunk
            for feat_matrix, targets in chunk_results:
                all_features.append(feat_matrix)
                all_targets.append(targets)

            symbols_processed += len(chunk)
            sample_count = sum(len(f) for f in all_features)
            logger.info(f"[Vectorized extraction] {symbols_processed}/{total_symbols} symbols ({sample_count} samples)")

            # Release raw bar data for this chunk to free memory
            # Delete from the original dict so the caller's memory is freed too
            for symbol, _ in chunk:
                bars_by_symbol.pop(symbol, None)
            del chunk, worker_args, chunk_results
            gc.collect()

        if not all_features:
            logger.warning("No training data extracted (vectorized)")
            return self._metrics

        X = np.vstack(all_features).astype(np.float32)
        y = np.concatenate(all_targets).astype(np.float32)

        # Release individual arrays to free memory before training
        del all_features, all_targets
        gc.collect()

        logger.info(f"Extracted {len(X)} training samples (vectorized)")

        # Filter out any rows with all zeros (failed extraction)
        valid_rows = np.any(X != 0, axis=1)
        X = X[valid_rows]
        y = y[valid_rows]

        unique, counts = np.unique(y, return_counts=True)
        dist_str = ", ".join([f"{'UP' if c == 1 else 'DOWN'}={n} ({n/len(y)*100:.1f}%)" for c, n in zip(unique, counts)])
        logger.info(f"Class distribution: {dist_str}")

        # Split train/validation
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        feature_names = feature_engineer.get_feature_names()
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)

        self._model = xgb.train(
            {**self.DEFAULT_PARAMS, **self.params},
            dtrain,
            num_boost_round=num_boost_round,
            evals=[(dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False
        )

        # Evaluate
        y_pred = self._model.predict(dval)
        y_pred_binary = (y_pred > 0.5).astype(int)
        accuracy = np.mean(y_pred_binary == y_val)

        up_mask = y_val == 1
        if np.sum(up_mask) > 0:
            precision_up = np.sum((y_pred_binary == 1) & up_mask) / max(np.sum(y_pred_binary == 1), 1)
            recall_up = np.sum((y_pred_binary == 1) & up_mask) / np.sum(up_mask)
            f1_up = 2 * precision_up * recall_up / max(precision_up + recall_up, 1e-10)
        else:
            precision_up = recall_up = f1_up = 0.0

        self._metrics = ModelMetrics(
            accuracy=round(accuracy, 4),
            precision_up=round(precision_up, 4),
            recall_up=round(recall_up, 4),
            f1_up=round(f1_up, 4),
            training_samples=len(X_train),
            validation_samples=len(X_val),
        )

        version_parts = self._version.replace("v", "").split(".")
        minor = int(version_parts[1]) + 1 if len(version_parts) > 1 else 1
        self._version = f"v0.{minor}.0"

        self._save_model()

        logger.info(f"Training complete (vectorized): accuracy={accuracy:.3f}, precision_up={precision_up:.3f}, f1_up={f1_up:.3f}")
        return self._metrics

    def train_from_features(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        validation_split: float = 0.2,
        num_boost_round: int = 100,
        early_stopping_rounds: int = 10,
        skip_save: bool = False,
        num_classes: int = 2
    ) -> 'ModelMetrics':
        """
        Train the model from pre-extracted features and targets.
        
        Supports binary (2-class: UP/DOWN) and multiclass (3-class: DOWN/FLAT/UP).
        For 3-class: y values are 0=DOWN, 1=FLAT, 2=UP.
        
        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target array (n_samples,)
            feature_names: Ordered list of feature names matching X columns
            validation_split: Fraction for validation
            num_boost_round: Boosting rounds
            early_stopping_rounds: Early stopping patience
            skip_save: If True, skip saving to DB (caller will handle saving)
            num_classes: 2 for binary, 3 for UP/FLAT/DOWN
            
        Returns:
            ModelMetrics with training results
        """
        if len(X) < 100:
            logger.warning(f"Insufficient training data: {len(X)} samples")
            return ModelMetrics()

        self._num_classes = num_classes
        logger.info(f"Training from pre-extracted features: {len(X)} samples, {len(feature_names)} features, {num_classes}-class")

        # Update feature names for this model
        self._feature_names = feature_names

        # Log class distribution
        unique, counts = np.unique(y.astype(int), return_counts=True)
        class_labels = {0: "DOWN", 1: "FLAT", 2: "UP"} if num_classes == 3 else {0: "DOWN", 1: "UP"}
        dist_parts = [f"{class_labels.get(int(c), c)}={n} ({n/len(y)*100:.1f}%)" for c, n in zip(unique, counts)]
        logger.info(f"Class distribution: {', '.join(dist_parts)}")

        # Configure params for multiclass if needed
        train_params = dict(self.params)
        if num_classes >= 3:
            train_params["objective"] = "multi:softprob"
            train_params["num_class"] = num_classes
            train_params["eval_metric"] = "mlogloss"

        # Split train/validation (time-ordered)
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)

        self._model = xgb.train(
            train_params,
            dtrain,
            num_boost_round=num_boost_round * 2,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False
        )

        # Evaluate
        y_pred_raw = self._model.predict(dval)

        if num_classes >= 3:
            # Multiclass: y_pred_raw shape = (n_samples, num_classes)
            # Classes: 0=DOWN, 1=FLAT, 2=UP
            y_pred = np.argmax(y_pred_raw, axis=1)
            accuracy = np.mean(y_pred == y_val)

            # Per-class metrics for UP (class 2) — most important for trading
            up_class = 2
            tp_up = np.sum((y_pred == up_class) & (y_val == up_class))
            fp_up = np.sum((y_pred == up_class) & (y_val != up_class))
            fn_up = np.sum((y_pred != up_class) & (y_val == up_class))
            precision_up = tp_up / (tp_up + fp_up) if (tp_up + fp_up) > 0 else 0
            recall_up = tp_up / (tp_up + fn_up) if (tp_up + fn_up) > 0 else 0
            f1_up = 2 * precision_up * recall_up / (precision_up + recall_up) if (precision_up + recall_up) > 0 else 0

            # Per-class metrics for DOWN (class 0)
            down_class = 0
            tp_dn = np.sum((y_pred == down_class) & (y_val == down_class))
            fp_dn = np.sum((y_pred == down_class) & (y_val != down_class))
            fn_dn = np.sum((y_pred != down_class) & (y_val == down_class))
            precision_down = tp_dn / (tp_dn + fp_dn) if (tp_dn + fp_dn) > 0 else 0

            # FLAT accuracy — how well does it identify no-trade zones
            flat_class = 1
            flat_correct = np.sum((y_pred == flat_class) & (y_val == flat_class))
            flat_total = np.sum(y_val == flat_class)
            flat_recall = flat_correct / flat_total if flat_total > 0 else 0

            logger.info(
                f"3-class eval: accuracy={accuracy:.3f}, "
                f"UP prec={precision_up:.3f} recall={recall_up:.3f}, "
                f"DOWN prec={precision_down:.3f}, FLAT recall={flat_recall:.3f}"
            )
        else:
            # Binary: y_pred_raw shape = (n_samples,)
            y_pred = (y_pred_raw > self.UP_THRESHOLD).astype(int)
            accuracy = np.mean(y_pred == y_val)

            tp_up = np.sum((y_pred == 1) & (y_val == 1))
            fp_up = np.sum((y_pred == 1) & (y_val == 0))
            fn_up = np.sum((y_pred == 0) & (y_val == 1))
            precision_up = tp_up / (tp_up + fp_up) if (tp_up + fp_up) > 0 else 0
            recall_up = tp_up / (tp_up + fn_up) if (tp_up + fn_up) > 0 else 0
            f1_up = 2 * precision_up * recall_up / (precision_up + recall_up) if (precision_up + recall_up) > 0 else 0

        importance_dict = self._model.get_score(importance_type="gain")
        sorted_features = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)[:10]
        top_features = [f[0] for f in sorted_features if f[0] in feature_names]

        self._metrics = ModelMetrics(
            accuracy=float(accuracy),
            precision_up=float(precision_up),
            recall_up=float(recall_up),
            f1_up=float(f1_up),
            training_samples=len(X_train),
            validation_samples=len(X_val),
            top_features=top_features,
            last_trained=datetime.now(timezone.utc).isoformat()
        )

        version_parts = self._version.replace("v", "").split(".")
        minor = int(version_parts[1]) + 1 if len(version_parts) > 1 else 1
        self._version = f"v0.{minor}.0"
        
        if not skip_save:
            self._save_model()

        logger.info(f"Training complete ({num_classes}-class): accuracy={accuracy:.3f}, precision_up={precision_up:.3f}, f1_up={f1_up:.3f}")
        return self._metrics
        
    def predict(
        self,
        bars: List[Dict],
        symbol: str = ""
    ) -> Optional[Prediction]:
        """
        Predict directional movement.
        
        Args:
            bars: OHLCV bars (most recent first)
            symbol: Ticker symbol
            
        Returns:
            Prediction with probabilities and direction
        """
        if self._model is None:
            logger.warning("Model not trained - using random prediction")
            return Prediction(
                symbol=symbol,
                direction="flat",
                probability_up=0.5,
                probability_down=0.5,
                confidence=0.0,
                model_version="untrained",
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            
        # Extract features
        feature_set = self._feature_engineer.extract_features(
            bars,
            symbol=symbol,
            include_target=False
        )
        
        if feature_set is None:
            return None
            
        # Convert to XGBoost DMatrix for prediction
        feature_vector = np.array([[
            feature_set.features.get(f, 0.0) 
            for f in self._feature_names
        ]], dtype=np.float32)
        
        dmatrix = xgb.DMatrix(feature_vector, feature_names=self._feature_names)
        
        # Predict (XGBoost binary:logistic outputs probability directly)
        prob_up = float(self._model.predict(dmatrix)[0])
        prob_down = 1 - prob_up
        
        # Determine direction using class-specific thresholds
        # Use lower threshold for "up" to improve recall
        if prob_up > self.UP_THRESHOLD:
            direction = "up"
            confidence = min((prob_up - self.UP_THRESHOLD) / (1 - self.UP_THRESHOLD), 1.0)
        elif prob_down > 0.55:
            direction = "down"
            confidence = (prob_down - 0.5) * 2
        else:
            direction = "flat"
            confidence = 0.2
            
        prediction = Prediction(
            symbol=symbol,
            direction=direction,
            probability_up=float(prob_up),
            probability_down=float(prob_down),
            confidence=float(confidence),
            model_version=self._version,
            feature_count=len(self._feature_names),
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Log prediction
        self._log_prediction(prediction, feature_set, bars)
        
        return prediction
        
    def _log_prediction(self, prediction: Prediction, features: FeatureSet, bars: List[Dict] = None):
        """Log prediction to database with price context for later verification"""
        if self._db is None:
            return
            
        try:
            # Get current price from bars if available
            current_price = None
            if bars and len(bars) > 0:
                current_price = bars[0].get("close")
            
            self._db[self.PREDICTIONS_COLLECTION].insert_one({
                "symbol": prediction.symbol,
                "prediction": prediction.to_dict(),
                "features_summary": {
                    "return_1": features.features.get("return_1", 0),
                    "rsi_14": features.features.get("rsi_14", 50),
                    "rvol_1": features.features.get("rvol_1", 1),
                    "trend_strength": features.features.get("trend_strength", 0)
                },
                "price_at_prediction": current_price,
                "forecast_horizon": self.forecast_horizon,
                "timestamp": prediction.timestamp,
                # Outcome fields - to be filled by verification job
                "outcome_verified": False,
                "actual_direction": None,
                "price_at_verification": None,
                "actual_return": None,
                "prediction_correct": None,
                "verified_at": None
            })
        except Exception as e:
            logger.warning(f"Could not log prediction: {e}")

    def verify_pending_predictions(self) -> Dict[str, Any]:
        """
        Verify pending predictions against actual price movements.
        Called periodically to update prediction outcomes.
        """
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        try:
            # Find unverified predictions older than forecast_horizon periods
            # For daily data, 5 days old; for 5-min data, 25 minutes old
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.forecast_horizon + 1)
            
            pending = list(self._db[self.PREDICTIONS_COLLECTION].find({
                "outcome_verified": False,
                "timestamp": {"$lt": cutoff_time.isoformat()}
            }).limit(100))
            
            verified_count = 0
            correct_count = 0
            
            for pred in pending:
                symbol = pred["symbol"]
                pred_time = pred["timestamp"]
                pred_direction = pred["prediction"]["direction"]
                pred_price = pred.get("price_at_prediction")
                
                if pred_price is None:
                    continue
                
                # Get price after forecast horizon from ib_historical_data (unified collection)
                # Find the first bar after (pred_time + forecast_horizon)
                target_time = datetime.fromisoformat(pred_time.replace("Z", "+00:00")) + timedelta(days=self.forecast_horizon)
                
                # Try to find by date string (YYYY-MM-DD format for daily bars)
                target_date_str = target_time.strftime("%Y-%m-%d")
                future_bar = self._db["ib_historical_data"].find_one(
                    {
                        "symbol": symbol,
                        "bar_size": "1 day",
                        "date": {"$gte": target_date_str}
                    },
                    sort=[("date", 1)]
                )
                
                if future_bar and "close" in future_bar:
                    future_price = future_bar["close"]
                    actual_return = (future_price - pred_price) / pred_price
                    
                    # Determine actual direction
                    if actual_return > 0:
                        actual_direction = "up"
                    elif actual_return < 0:
                        actual_direction = "down"
                    else:
                        actual_direction = "flat"
                    
                    # Check if prediction was correct
                    prediction_correct = (pred_direction == actual_direction) or \
                                        (pred_direction == "flat" and abs(actual_return) < 0.01)
                    
                    if prediction_correct:
                        correct_count += 1
                    
                    # Update the prediction record
                    self._db[self.PREDICTIONS_COLLECTION].update_one(
                        {"_id": pred["_id"]},
                        {"$set": {
                            "outcome_verified": True,
                            "actual_direction": actual_direction,
                            "price_at_verification": future_price,
                            "actual_return": actual_return,
                            "prediction_correct": prediction_correct,
                            "verified_at": datetime.now(timezone.utc).isoformat()
                        }}
                    )
                    verified_count += 1
            
            return {
                "success": True,
                "verified": verified_count,
                "correct": correct_count,
                "accuracy": correct_count / verified_count if verified_count > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error verifying predictions: {e}")
            return {"success": False, "error": str(e)}

    def get_prediction_accuracy(self, days: int = 30) -> Dict[str, Any]:
        """Get prediction accuracy statistics over a time period"""
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Get verified predictions
            verified = list(self._db[self.PREDICTIONS_COLLECTION].find({
                "outcome_verified": True,
                "timestamp": {"$gte": cutoff.isoformat()}
            }))
            
            if not verified:
                return {
                    "success": True,
                    "total_predictions": 0,
                    "verified_predictions": 0,
                    "accuracy": 0,
                    "by_direction": {}
                }
            
            total = len(verified)
            correct = sum(1 for p in verified if p.get("prediction_correct"))
            
            # Break down by predicted direction
            by_direction = {}
            for direction in ["up", "down", "flat"]:
                dir_preds = [p for p in verified if p["prediction"]["direction"] == direction]
                dir_correct = sum(1 for p in dir_preds if p.get("prediction_correct"))
                if dir_preds:
                    by_direction[direction] = {
                        "total": len(dir_preds),
                        "correct": dir_correct,
                        "accuracy": dir_correct / len(dir_preds)
                    }
            
            # Calculate average return when prediction was correct vs incorrect
            correct_returns = [p.get("actual_return", 0) for p in verified if p.get("prediction_correct")]
            incorrect_returns = [p.get("actual_return", 0) for p in verified if not p.get("prediction_correct")]
            
            return {
                "success": True,
                "total_predictions": total,
                "verified_predictions": total,
                "correct_predictions": correct,
                "accuracy": correct / total if total > 0 else 0,
                "by_direction": by_direction,
                "avg_return_when_correct": sum(correct_returns) / len(correct_returns) if correct_returns else 0,
                "avg_return_when_incorrect": sum(incorrect_returns) / len(incorrect_returns) if incorrect_returns else 0,
                "period_days": days
            }
            
        except Exception as e:
            logger.error(f"Error getting prediction accuracy: {e}")
            return {"success": False, "error": str(e)}
            
    def get_metrics(self) -> ModelMetrics:
        """Get current model metrics"""
        return self._metrics
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get comprehensive model info for training status dashboard"""
        return {
            "is_trained": self._model is not None,
            "version": self._version,
            "last_trained": self._metrics.last_trained if self._metrics else None,
            "accuracy": self._metrics.accuracy if self._metrics else None,
            "samples_trained": self._metrics.training_samples if self._metrics else 0,
            "model_name": self.model_name,
            "forecast_horizon": self.forecast_horizon,
            "feature_count": len(self._feature_names)
        }
        
    def get_status(self) -> Dict[str, Any]:
        """Get model status"""
        return {
            "model_name": self.model_name,
            "version": self._version,
            "trained": self._model is not None,
            "forecast_horizon": self.forecast_horizon,
            "feature_count": len(self._feature_names),
            "metrics": self._metrics.to_dict() if self._metrics else None,
            "db_connected": self._db is not None
        }


# Singleton
_timeseries_model: Optional[TimeSeriesGBM] = None


def get_timeseries_model() -> TimeSeriesGBM:
    """Get singleton instance"""
    global _timeseries_model
    if _timeseries_model is None:
        _timeseries_model = TimeSeriesGBM()
    return _timeseries_model


def init_timeseries_model(db=None, **kwargs) -> TimeSeriesGBM:
    """Initialize model with dependencies"""
    model = get_timeseries_model()
    if db is not None:
        model.set_db(db)
    return model
