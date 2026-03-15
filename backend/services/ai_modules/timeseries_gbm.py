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
from datetime import datetime, timezone
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
    PREDICTIONS_COLLECTION = "timeseries_predictions"
    
    # Default model parameters
    DEFAULT_PARAMS = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "n_jobs": -1,
        "seed": 42
    }
    
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
        """Load model from database"""
        if self._db is None:
            return
            
        try:
            doc = self._db[self.MODEL_COLLECTION].find_one({"name": self.model_name})
            if doc and "model_data" in doc:
                model_bytes = base64.b64decode(doc["model_data"])
                self._model = pickle.loads(model_bytes)
                self._version = doc.get("version", "v0.0.0")
                self._metrics = ModelMetrics(**doc.get("metrics", {}))
                logger.info(f"Loaded model {self.model_name} {self._version}")
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
            
    def _save_model(self):
        """Save model to database"""
        if self._db is None or self._model is None:
            return False
            
        try:
            model_bytes = pickle.dumps(self._model)
            model_data = base64.b64encode(model_bytes).decode("utf-8")
            
            self._db[self.MODEL_COLLECTION].update_one(
                {"name": self.model_name},
                {"$set": {
                    "name": self.model_name,
                    "model_data": model_data,
                    "version": self._version,
                    "metrics": self._metrics.to_dict(),
                    "params": self.params,
                    "feature_names": self._feature_names,
                    "forecast_horizon": self.forecast_horizon,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
            logger.info(f"Saved model {self.model_name} {self._version}")
            return True
        except Exception as e:
            logger.error(f"Could not save model: {e}")
            return False
            
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
            bars_by_symbol: Dict of symbol -> list of OHLCV bars
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
            if len(bars) < 50:
                continue
                
            # Slide through bars to create training samples
            for i in range(len(bars) - self.forecast_horizon - 50):
                window_bars = bars[i:i+50]
                
                feature_set = self._feature_engineer.extract_features(
                    window_bars,
                    symbol=symbol,
                    include_target=True,
                    forecast_horizon=self.forecast_horizon
                )
                
                if feature_set and feature_set.target is not None:
                    # Convert features to vector in consistent order
                    feature_vector = [
                        feature_set.features.get(f, 0.0) 
                        for f in self._feature_names
                    ]
                    
                    # Binary classification: up vs not-up
                    target = 1 if feature_set.target > 0.5 else 0
                    
                    all_features.append(feature_vector)
                    all_targets.append(target)
                    
        if len(all_features) < 100:
            logger.warning(f"Insufficient training data: {len(all_features)} samples")
            return ModelMetrics()
            
        logger.info(f"Extracted {len(all_features)} training samples")
        
        # Convert to numpy
        X = np.array(all_features)
        y = np.array(all_targets)
        
        # Split train/validation
        split_idx = int(len(X) * (1 - validation_split))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]
        
        # Create datasets
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=self._feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, feature_name=self._feature_names, reference=train_data)
        
        # Train model
        callbacks = [lgb.early_stopping(early_stopping_rounds)]
        
        self._model = lgb.train(
            self.params,
            train_data,
            num_boost_round=num_boost_round,
            valid_sets=[train_data, val_data],
            valid_names=["train", "val"],
            callbacks=callbacks
        )
        
        # Evaluate
        y_pred_proba = self._model.predict(X_val)
        y_pred = (y_pred_proba > 0.5).astype(int)
        
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
        
        # Determine direction
        if prob_up > 0.55:
            direction = "up"
            confidence = (prob_up - 0.5) * 2  # Scale to 0-1
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
        self._log_prediction(prediction, feature_set)
        
        return prediction
        
    def _log_prediction(self, prediction: Prediction, features: FeatureSet):
        """Log prediction to database"""
        if self._db is None:
            return
            
        try:
            self._db[self.PREDICTIONS_COLLECTION].insert_one({
                "symbol": prediction.symbol,
                "prediction": prediction.to_dict(),
                "features_summary": {
                    "return_1": features.features.get("return_1", 0),
                    "rsi_14": features.features.get("rsi_14", 50),
                    "rvol_1": features.features.get("rvol_1", 1),
                    "trend_strength": features.features.get("trend_strength", 0)
                },
                "timestamp": prediction.timestamp
            })
        except Exception as e:
            logger.warning(f"Could not log prediction: {e}")
            
    def get_metrics(self) -> ModelMetrics:
        """Get current model metrics"""
        return self._metrics
        
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
