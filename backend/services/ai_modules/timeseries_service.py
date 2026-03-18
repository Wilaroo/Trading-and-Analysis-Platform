"""
Time-Series AI Service - Directional Forecasting Integration

Integrates LightGBM directional forecasting into the AI modules system.
Provides predictions for the AI Trade Consultation.

Key Features:
- Direction prediction (up/down/flat)
- Probability-based confidence
- Auto-training from historical data
- Performance tracking

Note: Requires lightgbm to be installed. Will gracefully degrade if not available.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
import asyncio

logger = logging.getLogger(__name__)

# Try to import ML dependencies
ML_AVAILABLE = False
try:
    from .timeseries_gbm import (
        TimeSeriesGBM,
        Prediction,
        ModelMetrics,
        get_timeseries_model,
        init_timeseries_model
    )
    from .timeseries_features import get_feature_engineer
    ML_AVAILABLE = True
except ImportError as e:
    logger.warning(f"ML dependencies not available for timeseries_service: {e}")
    # Create placeholders
    TimeSeriesGBM = None
    Prediction = None
    ModelMetrics = None
    def get_timeseries_model():
        return None
    def init_timeseries_model(*args, **kwargs):
        return None
    def get_feature_engineer():
        return None

logger = logging.getLogger(__name__)


class TimeSeriesAIService:
    """
    High-level service for time-series AI predictions.
    
    Used by AI Trade Consultation to get directional forecasts.
    Note: Gracefully degrades if lightgbm is not installed.
    """
    
    # Minimum confidence to include in consultation
    MIN_CONFIDENCE_THRESHOLD = 0.3
    
    # Training configuration
    AUTO_TRAIN_INTERVAL_HOURS = 24
    MIN_BARS_FOR_TRAINING = 100
    
    def __init__(self):
        self._model = get_timeseries_model() if ML_AVAILABLE else None
        self._db = None
        self._historical_service = None
        self._last_train_time = None
        self._ml_available = ML_AVAILABLE
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if self._model:
            self._model.set_db(db)
        
    def set_historical_service(self, historical_service):
        """Set historical data service for training"""
        self._historical_service = historical_service
        
    async def get_forecast(
        self,
        symbol: str,
        bars: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Get directional forecast for a symbol.
        
        Args:
            symbol: Ticker symbol
            bars: Recent OHLCV bars (most recent first). If not provided, fetched from MongoDB.
            
        Returns:
            {
                "direction": "up" | "down" | "flat",
                "probability_up": 0.0-1.0,
                "probability_down": 0.0-1.0,
                "confidence": 0.0-1.0,
                "signal": str,
                "model_version": str,
                "usable": bool  # True if confidence > threshold
            }
        """
        # Check if ML is available
        if not self._ml_available or self._model is None:
            return self._empty_forecast(symbol, "ML not available - lightgbm not installed")
            
        # If no bars provided, fetch from MongoDB
        if not bars:
            bars = await self._get_bars_from_db_for_prediction(symbol)
            
        if not bars or len(bars) < 20:
            return self._empty_forecast(symbol, "Insufficient data")
            
        try:
            prediction = self._model.predict(bars, symbol)
            
            if prediction is None:
                return self._empty_forecast(symbol, "Prediction failed")
                
            # Build signal message
            signal = self._build_signal(prediction)
            
            # Determine if usable for consultation
            usable = prediction.confidence >= self.MIN_CONFIDENCE_THRESHOLD
            
            return {
                "direction": prediction.direction,
                "probability_up": prediction.probability_up,
                "probability_down": prediction.probability_down,
                "confidence": prediction.confidence,
                "signal": signal,
                "model_version": prediction.model_version,
                "usable": usable,
                "symbol": symbol,
                "timestamp": prediction.timestamp
            }
            
        except Exception as e:
            logger.error(f"Forecast error for {symbol}: {e}")
            return self._empty_forecast(symbol, f"Error: {str(e)[:50]}")
            
    def _build_signal(self, prediction: Prediction) -> str:
        """Build human-readable signal from prediction"""
        direction = prediction.direction
        confidence = prediction.confidence
        prob_up = prediction.probability_up
        
        if direction == "up":
            if confidence > 0.6:
                return f"Strong bullish signal ({prob_up*100:.0f}% up probability)"
            else:
                return f"Weak bullish signal ({prob_up*100:.0f}% up probability)"
        elif direction == "down":
            prob_down = prediction.probability_down
            if confidence > 0.6:
                return f"Strong bearish signal ({prob_down*100:.0f}% down probability)"
            else:
                return f"Weak bearish signal ({prob_down*100:.0f}% down probability)"
        else:
            return f"Neutral/unclear direction ({prob_up*100:.0f}% up)"
            
    def _empty_forecast(self, symbol: str, reason: str) -> Dict[str, Any]:
        """Return empty forecast"""
        return {
            "direction": "flat",
            "probability_up": 0.5,
            "probability_down": 0.5,
            "confidence": 0.0,
            "signal": reason,
            "model_version": "N/A",
            "usable": False,
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    async def train_model(
        self,
        symbols: List[str] = None,
        max_symbols: int = 100
    ) -> Dict[str, Any]:
        """
        Train/update the model with historical data from MongoDB.
        
        Args:
            symbols: List of symbols to train on (default: fetch from history)
            max_symbols: Maximum number of symbols to train on (default: 100)
            
        Returns:
            Training result with metrics
        """
        # Check if ML is available
        if not self._ml_available or self._model is None:
            return {"success": False, "error": "ML not available - lightgbm not installed"}
            
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        logger.info(f"Starting model training from MongoDB ib_historical_data (up to {max_symbols} symbols)...")
        
        try:
            # Get historical bars directly from MongoDB
            bars_by_symbol = {}
            
            if symbols is None:
                # Get symbols with most data from MongoDB
                symbols = await self._get_training_symbols_from_db(limit=max_symbols)
                
            logger.info(f"Training symbols: {len(symbols)} symbols queued")
            
            for symbol in symbols[:max_symbols]:  # Train on up to max_symbols
                bars = await self._get_historical_bars_from_db(symbol)
                if bars and len(bars) >= self.MIN_BARS_FOR_TRAINING:
                    bars_by_symbol[symbol] = bars
                    if len(bars_by_symbol) % 20 == 0:  # Log progress every 20 symbols
                        logger.info(f"  Loaded {len(bars_by_symbol)} symbols...")
                    
            if not bars_by_symbol:
                return {"success": False, "error": "No historical data available in MongoDB"}
                
            total_bars = sum(len(b) for b in bars_by_symbol.values())
            logger.info(f"Training on {len(bars_by_symbol)} symbols, {total_bars:,} total bars")
            
            # Train model
            metrics = self._model.train(bars_by_symbol)
            
            self._last_train_time = datetime.now(timezone.utc)
            
            return {
                "success": True,
                "metrics": metrics.to_dict(),
                "symbols_used": list(bars_by_symbol.keys()),
                "total_bars": total_bars,
                "samples": metrics.training_samples + metrics.validation_samples
            }
            
        except Exception as e:
            logger.error(f"Training error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
            
    async def _get_training_symbols_from_db(self, limit: int = 100) -> List[str]:
        """Get symbols with most historical data from MongoDB (unified ib_historical_data)"""
        if self._db is None:
            return []
            
        try:
            # Aggregate to find symbols with most bars in unified collection
            pipeline = [
                {"$match": {"bar_size": "1 day"}},  # Focus on daily bars for training
                {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gte": 100}}},  # At least 100 bars
                {"$sort": {"count": -1}},
                {"$limit": limit}
            ]
            result = list(self._db["ib_historical_data"].aggregate(pipeline))
            symbols = [r["_id"] for r in result]
            logger.info(f"Found {len(symbols)} symbols with sufficient data in ib_historical_data")
            return symbols
        except Exception as e:
            logger.error(f"Error getting training symbols: {e}")
            # Fallback to default list
            return [
                "NVDA", "TSLA", "ORCL", "AVGO", "MSFT", "GOOGL", "AAPL", 
                "META", "AMZN", "JPM", "ADBE", "V"
            ]
            
    async def _get_historical_bars_from_db(self, symbol: str) -> Optional[List[Dict]]:
        """Get historical bars for a symbol from unified ib_historical_data collection"""
        if self._db is None:
            return None
            
        try:
            # Fetch bars sorted by date (oldest first for proper training)
            # Training expects chronological order (oldest first)
            cursor = self._db["ib_historical_data"].find(
                {"symbol": symbol, "bar_size": "1 day"},
                {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1, 
                 "low": 1, "close": 1, "volume": 1}
            ).sort("date", 1)  # Ascending order (oldest first)
            
            bars = list(cursor)
            
            # Convert 'date' field to 'timestamp' for compatibility with model
            for bar in bars:
                bar['timestamp'] = bar.pop('date', None)
            
            return bars if bars else None
            
        except Exception as e:
            logger.warning(f"Could not get bars for {symbol} from DB: {e}")
            return None
            
    async def _get_training_symbols(self) -> List[str]:
        """Get symbols with sufficient historical data"""
        # Use DB method if available
        if self._db is not None:
            return await self._get_training_symbols_from_db()
            
        # Default list of liquid stocks
        default_symbols = [
            "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
            "TSLA", "AMD", "NFLX", "DIS", "BA", "JPM", "GS", "BAC",
            "XOM", "CVX", "PFE", "JNJ"
        ]
        return default_symbols
        
    async def _get_historical_bars(self, symbol: str) -> Optional[List[Dict]]:
        """Get historical bars for a symbol"""
        if self._historical_service is None:
            return None
            
        try:
            # Fetch last 200 bars (approx 1 week of 5-min bars)
            bars = await self._historical_service.get_bars(
                symbol,
                timeframe="5Min",
                limit=200
            )
            return bars if bars else None
        except Exception as e:
            logger.warning(f"Could not get bars for {symbol}: {e}")
            return None

    async def _get_bars_from_db_for_prediction(self, symbol: str) -> Optional[List[Dict]]:
        """Get historical bars from unified ib_historical_data for running a prediction"""
        if self._db is None:
            logger.warning("DB not connected, cannot fetch bars for prediction")
            return None
            
        try:
            # Fetch most recent 50 bars (sorted by date descending for most recent first)
            cursor = self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1, 
                 "low": 1, "close": 1, "volume": 1}
            ).sort("date", -1).limit(50)  # Most recent first
            
            bars = list(cursor)
            
            # Convert 'date' field to 'timestamp' for compatibility
            for bar in bars:
                bar['timestamp'] = bar.pop('date', None)
            
            if bars and len(bars) >= 20:
                logger.info(f"Fetched {len(bars)} bars from ib_historical_data for {symbol}")
                return bars
            else:
                logger.warning(f"Insufficient bars in ib_historical_data for {symbol}: {len(bars) if bars else 0}")
                return None
                
        except Exception as e:
            logger.warning(f"Could not get bars for {symbol} from DB for prediction: {e}")
            return None
            
    async def auto_train_if_needed(self):
        """Check and auto-train if interval has passed"""
        if self._last_train_time is None:
            # Never trained - train now
            return await self.train_model()
            
        hours_since_train = (
            datetime.now(timezone.utc) - self._last_train_time
        ).total_seconds() / 3600
        
        if hours_since_train >= self.AUTO_TRAIN_INTERVAL_HOURS:
            return await self.train_model()
            
        return {"success": True, "message": "Training not needed yet"}
        
    def get_consultation_context(
        self,
        forecast: Dict[str, Any],
        direction: str = "long"
    ) -> Dict[str, Any]:
        """
        Get context for AI Trade Consultation.
        
        Returns signals and risk adjustment based on forecast.
        """
        if not forecast.get("usable", False):
            return {
                "signal": "Time-series AI: No confident prediction",
                "risk_adjustment": 0.0,
                "align_with_trade": "neutral"
            }
            
        pred_direction = forecast.get("direction", "flat")
        confidence = forecast.get("confidence", 0)
        
        # Check if forecast aligns with trade direction
        if direction == "long":
            if pred_direction == "up":
                align = "favorable"
                adjustment = -0.2 * confidence  # Reduce risk (favorable)
                signal = f"Time-series AI supports long ({confidence*100:.0f}% confidence)"
            elif pred_direction == "down":
                align = "contrary"
                adjustment = 0.5 * confidence  # Increase risk (contrary)
                signal = f"Time-series AI contradicts long ({confidence*100:.0f}% down probability)"
            else:
                align = "neutral"
                adjustment = 0.0
                signal = "Time-series AI: Neutral/unclear direction"
        else:  # short
            if pred_direction == "down":
                align = "favorable"
                adjustment = -0.2 * confidence
                signal = f"Time-series AI supports short ({confidence*100:.0f}% confidence)"
            elif pred_direction == "up":
                align = "contrary"
                adjustment = 0.5 * confidence
                signal = f"Time-series AI contradicts short ({confidence*100:.0f}% up probability)"
            else:
                align = "neutral"
                adjustment = 0.0
                signal = "Time-series AI: Neutral/unclear direction"
                
        return {
            "signal": signal,
            "risk_adjustment": round(adjustment, 2),
            "align_with_trade": align,
            "forecast": forecast
        }
        
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        model_status = self._model.get_status()
        
        return {
            "service": "timeseries_ai",
            "model": model_status,
            "last_train": self._last_train_time.isoformat() if self._last_train_time else None,
            "historical_service_connected": self._historical_service is not None,
            "db_connected": self._db is not None
        }
        
    async def verify_pending_predictions(self) -> Dict[str, Any]:
        """
        Verify pending predictions against actual outcomes.
        Delegates to the underlying model.
        """
        try:
            result = self._model.verify_pending_predictions()
            return result
        except Exception as e:
            logger.error(f"Error verifying predictions: {e}")
            return {"success": False, "error": str(e)}


# Singleton
_timeseries_ai: Optional[TimeSeriesAIService] = None


def get_timeseries_ai() -> TimeSeriesAIService:
    """Get singleton instance"""
    global _timeseries_ai
    if _timeseries_ai is None:
        _timeseries_ai = TimeSeriesAIService()
    return _timeseries_ai


def init_timeseries_ai(db=None, historical_service=None) -> TimeSeriesAIService:
    """Initialize service with dependencies"""
    service = get_timeseries_ai()
    if db is not None:
        service.set_db(db)
    if historical_service is not None:
        service.set_historical_service(historical_service)
    return service
