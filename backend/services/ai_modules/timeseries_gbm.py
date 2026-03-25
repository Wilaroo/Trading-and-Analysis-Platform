"""
LightGBM Time-Series Forecasting Model

Predicts directional price movement (up/down/flat) using features
extracted from OHLCV data.

Key Features:
- Online learning capable (can update with new data)
- Probability outputs for confidence scoring
- Model persistence to MongoDB
- Performance tracking and evaluation
"""

import logging
import pickle
import base64
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import lightgbm as lgb

from .timeseries_features import (
    TimeSeriesFeatureEngineer,
    FeatureSet,
    get_feature_engineer
)

logger = logging.getLogger(__name__)


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
    LightGBM model for directional price forecasting.
    
    Predicts probability of price moving up/down over the forecast horizon.
    """
    
    MODEL_COLLECTION = "timeseries_models"
    MODEL_ARCHIVE_COLLECTION = "timeseries_model_archive"
    PREDICTIONS_COLLECTION = "timeseries_predictions"
    
    # Check for GPU availability
    GPU_AVAILABLE = False
    try:
        import torch
        GPU_AVAILABLE = torch.cuda.is_available()
        if GPU_AVAILABLE:
            GPU_NAME = torch.cuda.get_device_name(0)
            logger.info(f"GPU detected: {GPU_NAME} - Will use for applicable operations")
    except ImportError:
        pass
    
    # Auto-detect LightGBM GPU support
    LGBM_GPU_AVAILABLE = False
    try:
        import lightgbm as _lgbm
        # Try creating a small GPU booster to test support
        _test_params = {"device": "gpu", "gpu_platform_id": 0, "gpu_device_id": 0, "verbose": -1}
        _lgbm.Booster(_test_params)
        LGBM_GPU_AVAILABLE = True
        logger.info("LightGBM GPU support detected")
    except Exception:
        pass  # GPU not available or LightGBM not compiled with GPU support
    
    # Default model parameters - optimized for imbalanced classification
    DEFAULT_PARAMS = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 63,
        "learning_rate": 0.03,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.7,
        "bagging_freq": 5,
        "min_data_in_leaf": 50,
        "max_depth": 8,
        "is_unbalance": True,
        "verbose": -1,
        "n_jobs": -1,
        "seed": 42,
    }
    
    # GPU acceleration (auto-enabled if available)
    # To enable manually: reinstall lightgbm with GPU support:
    #   pip install lightgbm --config-settings=cmake.define.USE_GPU=ON
    if LGBM_GPU_AVAILABLE:
        DEFAULT_PARAMS["device"] = "gpu"
        DEFAULT_PARAMS["gpu_platform_id"] = 0
        DEFAULT_PARAMS["gpu_device_id"] = 0
        logger.info("LightGBM will use GPU acceleration")
    
    # Prediction threshold for "up" classification
    # Higher threshold = more precise but lower recall
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
        
        self._model: Optional[lgb.Booster] = None
        self._feature_engineer = get_feature_engineer()
        self._feature_names = self._feature_engineer.get_feature_names()
        
        # Database
        self._db = None
        
        # Metrics
        self._metrics = ModelMetrics()
        self._version = "v0.0.0"
        
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
                self._model = pickle.loads(model_bytes)
                self._version = doc.get("version", "v0.0.0")
                self._metrics = ModelMetrics(**doc.get("metrics", {}))
                loaded_name = doc.get("name", "unknown")
                logger.info(f"Loaded model '{loaded_name}' version {self._version} (requested: {self.model_name})")
                # Update model name to reflect what was actually loaded
                self.model_name = loaded_name
            else:
                logger.warning(f"No trained models found in database")
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
            
    def _save_model(self):
        """Save model to database with best-model protection.
        
        Logic:
        1. Always archive the new model (for learning/reference)
        2. Only promote to active if accuracy >= current active model
        3. If new model is worse, log it but keep the old active model
        """
        if self._db is None or self._model is None:
            return False
            
        try:
            model_bytes = pickle.dumps(self._model)
            model_data = base64.b64encode(model_bytes).decode("utf-8")
            new_accuracy = self._metrics.accuracy if self._metrics else 0
            
            model_doc = {
                "name": self.model_name,
                "model_id": self.model_name,
                "model_data": model_data,
                "version": self._version,
                "metrics": self._metrics.to_dict(),
                "params": self.params,
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
        
        # Extract features for all symbols
        all_features = []
        all_targets = []
        
        for symbol, bars in bars_by_symbol.items():
            if len(bars) < 50 + self.forecast_horizon:
                continue
            
            # Bars are in chronological order (oldest first)
            # We need 50 bars for features + forecast_horizon bars for target
            # Slide through leaving room for future target
            for i in range(len(bars) - 50 - self.forecast_horizon):
                # Window of 50 bars starting at position i
                window_bars = bars[i:i+50]
                
                # Reverse window to recent-first for feature extraction
                window_bars_recent_first = window_bars[::-1]
                
                feature_set = self._feature_engineer.extract_features(
                    window_bars_recent_first,
                    symbol=symbol,
                    include_target=False  # We calculate target ourselves
                )
                
                if feature_set is not None:
                    # Convert features to vector in consistent order
                    feature_vector = [
                        feature_set.features.get(f, 0.0) 
                        for f in self._feature_names
                    ]
                    
                    # Calculate forward-looking target
                    # Current price is the last bar in window (most recent in window)
                    current_price = bars[i + 49]["close"]
                    # Future price is forecast_horizon bars after the window
                    future_price = bars[i + 49 + self.forecast_horizon]["close"]
                    
                    # Calculate return (positive = price went up)
                    target_return = (future_price - current_price) / current_price
                    
                    # Binary classification: up (>0%) vs not-up
                    # Using 0% threshold for more balanced classes
                    target = 1 if target_return > 0 else 0
                    
                    all_features.append(feature_vector)
                    all_targets.append(target)
                    
        if len(all_features) < 100:
            logger.warning(f"Insufficient training data: {len(all_features)} samples")
            return ModelMetrics()
            
        logger.info(f"Extracted {len(all_features)} training samples")
        
        # Convert to numpy
        X = np.array(all_features)
        y = np.array(all_targets)
        
        # Log class distribution
        n_up = np.sum(y == 1)
        n_down = np.sum(y == 0)
        logger.info(f"Class distribution: UP={n_up} ({n_up/len(y)*100:.1f}%), DOWN={n_down} ({n_down/len(y)*100:.1f}%)")
        
        # Split train/validation
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # Create datasets
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=self._feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, feature_name=self._feature_names, reference=train_data)
        
        # Train model with more rounds
        callbacks = [lgb.early_stopping(early_stopping_rounds)]
        
        self._model = lgb.train(
            self.params,
            train_data,
            num_boost_round=num_boost_round * 2,  # More rounds for better learning
            valid_sets=[train_data, val_data],
            valid_names=["train", "val"],
            callbacks=callbacks
        )
        
        # Evaluate with dynamic threshold
        y_pred_proba = self._model.predict(X_val)
        
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
        importance = self._model.feature_importance(importance_type="gain")
        top_indices = np.argsort(importance)[-10:][::-1]
        top_features = [self._feature_names[i] for i in top_indices]
        
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

    def train_from_features(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        validation_split: float = 0.2,
        num_boost_round: int = 100,
        early_stopping_rounds: int = 10,
        skip_save: bool = False
    ) -> 'ModelMetrics':
        """
        Train the model from pre-extracted features and targets.
        
        Used by setup-specific training where filtering and feature enrichment
        happens outside of the GBM model.
        
        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target array (n_samples,)
            feature_names: Ordered list of feature names matching X columns
            validation_split: Fraction for validation
            num_boost_round: Boosting rounds
            early_stopping_rounds: Early stopping patience
            skip_save: If True, skip saving to DB (caller will handle saving)
            
        Returns:
            ModelMetrics with training results
        """
        if len(X) < 100:
            logger.warning(f"Insufficient training data: {len(X)} samples")
            return ModelMetrics()

        logger.info(f"Training from pre-extracted features: {len(X)} samples, {len(feature_names)} features")

        # Update feature names for this model
        self._feature_names = feature_names

        n_up = np.sum(y == 1)
        n_down = np.sum(y == 0)
        logger.info(f"Class distribution: UP={n_up} ({n_up/len(y)*100:.1f}%), DOWN={n_down} ({n_down/len(y)*100:.1f}%)")

        # Split train/validation (time-ordered)
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, feature_name=feature_names, reference=train_data)

        callbacks = [lgb.early_stopping(early_stopping_rounds)]

        self._model = lgb.train(
            self.params,
            train_data,
            num_boost_round=num_boost_round * 2,
            valid_sets=[train_data, val_data],
            valid_names=["train", "val"],
            callbacks=callbacks
        )

        # Evaluate
        y_pred_proba = self._model.predict(X_val)
        y_pred = (y_pred_proba > self.UP_THRESHOLD).astype(int)
        accuracy = np.mean(y_pred == y_val)

        tp_up = np.sum((y_pred == 1) & (y_val == 1))
        fp_up = np.sum((y_pred == 1) & (y_val == 0))
        fn_up = np.sum((y_pred == 0) & (y_val == 1))
        precision_up = tp_up / (tp_up + fp_up) if (tp_up + fp_up) > 0 else 0
        recall_up = tp_up / (tp_up + fn_up) if (tp_up + fn_up) > 0 else 0
        f1_up = 2 * precision_up * recall_up / (precision_up + recall_up) if (precision_up + recall_up) > 0 else 0

        importance = self._model.feature_importance(importance_type="gain")
        top_indices = np.argsort(importance)[-10:][::-1]
        top_features = [feature_names[i] for i in top_indices if i < len(feature_names)]

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

        logger.info(f"Setup training complete: accuracy={accuracy:.3f}, precision_up={precision_up:.3f}, f1_up={f1_up:.3f}")
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
            
        # Convert to vector
        feature_vector = np.array([[
            feature_set.features.get(f, 0.0) 
            for f in self._feature_names
        ]])
        
        # Predict
        prob_up = self._model.predict(feature_vector)[0]
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
