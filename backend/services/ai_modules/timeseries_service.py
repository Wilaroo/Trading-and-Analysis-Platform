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
    Supports multiple timeframe models for different trading styles.
    Note: Gracefully degrades if lightgbm is not installed.
    """
    
    # Minimum confidence to include in consultation
    MIN_CONFIDENCE_THRESHOLD = 0.3
    
    # Training configuration
    AUTO_TRAIN_INTERVAL_HOURS = 24
    MIN_BARS_FOR_TRAINING = 100
    
    # Supported timeframes for multi-model training
    SUPPORTED_TIMEFRAMES = {
        "1 min": {"model_name": "direction_predictor_1min", "description": "Ultra-short scalping"},
        "5 mins": {"model_name": "direction_predictor_5min", "description": "Intraday scalping"},
        "15 mins": {"model_name": "direction_predictor_15min", "description": "Short-term swings"},
        "30 mins": {"model_name": "direction_predictor_30min", "description": "Intraday swings"},
        "1 hour": {"model_name": "direction_predictor_1hour", "description": "Swing trading"},
        "1 day": {"model_name": "direction_predictor_daily", "description": "Position trades"},
        "1 week": {"model_name": "direction_predictor_weekly", "description": "Long-term trends"},
    }
    
    # Default max symbols (removed hard limit of 100)
    DEFAULT_MAX_SYMBOLS = 1000
    DEFAULT_MAX_BARS_PER_SYMBOL = 10000
    
    def __init__(self):
        self._model = get_timeseries_model() if ML_AVAILABLE else None
        self._models = {}  # Cache for multi-timeframe models
        self._db = None
        self._historical_service = None
        self._last_train_time = None
        self._ml_available = ML_AVAILABLE
        self._training_in_progress = False
        self._training_status = {}
        
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
        max_symbols: int = None,
        bar_size: str = "1 day",
        max_bars_per_symbol: int = None
    ) -> Dict[str, Any]:
        """
        Train/update a model for a specific timeframe with historical data from MongoDB.
        
        Args:
            symbols: List of symbols to train on (default: fetch from history)
            max_symbols: Maximum number of symbols (default: 1000, no hard cap)
            bar_size: Bar size/timeframe to train on (default: "1 day")
            max_bars_per_symbol: Max bars per symbol for memory management (default: 10000)
            
        Returns:
            Training result with metrics
        """
        # Check if ML is available
        if not self._ml_available:
            return {"success": False, "error": "ML not available - lightgbm not installed"}
            
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        # Use defaults if not specified
        if max_symbols is None:
            max_symbols = self.DEFAULT_MAX_SYMBOLS
        if max_bars_per_symbol is None:
            max_bars_per_symbol = self.DEFAULT_MAX_BARS_PER_SYMBOL
            
        # Validate bar_size
        if bar_size not in self.SUPPORTED_TIMEFRAMES:
            return {
                "success": False, 
                "error": f"Unsupported bar_size: {bar_size}. Supported: {list(self.SUPPORTED_TIMEFRAMES.keys())}"
            }
        
        # Get or create model for this timeframe
        model_config = self.SUPPORTED_TIMEFRAMES[bar_size]
        model_name = model_config["model_name"]
        
        logger.info(f"Starting {model_name} training from MongoDB ({bar_size} bars, up to {max_symbols} symbols)...")
        
        # Mark training in progress
        self._training_in_progress = True
        self._training_status[bar_size] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "message": "Loading data..."
        }
        
        try:
            # Create a dedicated model for this timeframe
            model = TimeSeriesGBM(model_name=model_name)
            model.set_db(self._db)
            
            # Get historical bars directly from MongoDB
            bars_by_symbol = {}
            
            if symbols is None:
                # Get symbols with most data from MongoDB for this bar_size
                symbols = await self._get_training_symbols_from_db(
                    bar_size=bar_size, 
                    limit=max_symbols
                )
                
            logger.info(f"Training symbols: {len(symbols)} symbols queued for {bar_size}")
            
            self._training_status[bar_size]["message"] = f"Loading data for {len(symbols)} symbols..."
            
            loaded_count = 0
            for symbol in symbols:
                bars = await self._get_historical_bars_from_db(
                    symbol, 
                    bar_size=bar_size,
                    max_bars=max_bars_per_symbol
                )
                if bars and len(bars) >= self.MIN_BARS_FOR_TRAINING:
                    bars_by_symbol[symbol] = bars
                    loaded_count += 1
                    if loaded_count % 50 == 0:
                        logger.info(f"  Loaded {loaded_count} symbols...")
                        self._training_status[bar_size]["message"] = f"Loaded {loaded_count}/{len(symbols)} symbols..."
                    
            if not bars_by_symbol:
                self._training_status[bar_size] = {
                    "status": "error",
                    "message": f"No historical data available for {bar_size}"
                }
                return {"success": False, "error": f"No historical data available for {bar_size}"}
                
            total_bars = sum(len(b) for b in bars_by_symbol.values())
            logger.info(f"Training {model_name} on {len(bars_by_symbol)} symbols, {total_bars:,} total bars")
            
            self._training_status[bar_size]["message"] = f"Training on {total_bars:,} bars..."
            
            # Train model
            metrics = model.train(bars_by_symbol)
            
            self._last_train_time = datetime.now(timezone.utc)
            
            # Cache the trained model
            self._models[bar_size] = model
            
            # Update status
            self._training_status[bar_size] = {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "message": f"Trained with {metrics.accuracy*100:.1f}% accuracy"
            }
            
            return {
                "success": True,
                "bar_size": bar_size,
                "model_name": model_name,
                "metrics": metrics.to_dict(),
                "symbols_used": len(bars_by_symbol),
                "symbol_list": list(bars_by_symbol.keys())[:50],  # First 50 for display
                "total_bars": total_bars,
                "training_samples": metrics.training_samples,
                "validation_samples": metrics.validation_samples,
                "samples": metrics.training_samples + metrics.validation_samples
            }
            
        except Exception as e:
            logger.error(f"Training error for {bar_size}: {e}", exc_info=True)
            self._training_status[bar_size] = {
                "status": "error",
                "message": str(e)
            }
            return {"success": False, "error": str(e)}
        finally:
            self._training_in_progress = False
            
    async def train_all_timeframes(
        self,
        max_symbols: int = None,
        max_bars_per_symbol: int = None,
        timeframes: List[str] = None
    ) -> Dict[str, Any]:
        """
        Train models for all (or specified) timeframes sequentially.
        
        Args:
            max_symbols: Max symbols per timeframe (default: 1000)
            max_bars_per_symbol: Max bars per symbol (default: 10000)
            timeframes: List of specific timeframes to train (default: all)
            
        Returns:
            Combined results for all timeframes
        """
        if not self._ml_available:
            return {"success": False, "error": "ML not available - lightgbm not installed"}
        
        if timeframes is None:
            timeframes = list(self.SUPPORTED_TIMEFRAMES.keys())
        
        results = {}
        overall_success = True
        total_bars_trained = 0
        total_samples = 0
        
        logger.info(f"Starting multi-timeframe training for {len(timeframes)} timeframes...")
        
        for tf in timeframes:
            if tf not in self.SUPPORTED_TIMEFRAMES:
                results[tf] = {"success": False, "error": f"Unsupported timeframe: {tf}"}
                continue
                
            logger.info(f"Training {tf} model...")
            result = await self.train_model(
                bar_size=tf,
                max_symbols=max_symbols,
                max_bars_per_symbol=max_bars_per_symbol
            )
            results[tf] = result
            
            if result.get("success"):
                total_bars_trained += result.get("total_bars", 0)
                total_samples += result.get("samples", 0)
            else:
                overall_success = False
        
        return {
            "success": overall_success,
            "timeframes_trained": len([r for r in results.values() if r.get("success")]),
            "total_timeframes": len(timeframes),
            "total_bars_trained": total_bars_trained,
            "total_samples": total_samples,
            "results": results
        }
    
    def get_training_status(self) -> Dict[str, Any]:
        """Get current training status for all timeframes"""
        return {
            "training_in_progress": self._training_in_progress,
            "timeframe_status": self._training_status,
            "supported_timeframes": list(self.SUPPORTED_TIMEFRAMES.keys()),
            "last_train_time": self._last_train_time.isoformat() if self._last_train_time else None
        }
    
    def get_available_timeframe_data(self) -> Dict[str, Any]:
        """Get info about available data for each timeframe from the database"""
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        try:
            pipeline = [
                {"$group": {"_id": "$bar_size", "count": {"$sum": 1}, "symbols": {"$addToSet": "$symbol"}}},
                {"$project": {"_id": 1, "count": 1, "symbol_count": {"$size": "$symbols"}}},
                {"$sort": {"count": -1}}
            ]
            result = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
            
            timeframe_data = {}
            for r in result:
                bar_size = r["_id"]
                if bar_size in self.SUPPORTED_TIMEFRAMES:
                    timeframe_data[bar_size] = {
                        "bar_count": r["count"],
                        "symbol_count": r["symbol_count"],
                        "model_name": self.SUPPORTED_TIMEFRAMES[bar_size]["model_name"],
                        "description": self.SUPPORTED_TIMEFRAMES[bar_size]["description"]
                    }
            
            return {
                "success": True,
                "timeframes": timeframe_data,
                "total_bars": sum(t["bar_count"] for t in timeframe_data.values())
            }
        except Exception as e:
            logger.error(f"Error getting timeframe data: {e}")
            return {"success": False, "error": str(e)}
            
    async def _get_training_symbols_from_db(self, bar_size: str = "1 day", limit: int = 1000) -> List[str]:
        """Get symbols with most historical data from MongoDB for a specific bar_size"""
        if self._db is None:
            return []
            
        try:
            # Aggregate to find symbols with most bars for this timeframe
            pipeline = [
                {"$match": {"bar_size": bar_size}},
                {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gte": self.MIN_BARS_FOR_TRAINING}}},
                {"$sort": {"count": -1}},
                {"$limit": limit}
            ]
            result = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
            symbols = [r["_id"] for r in result]
            logger.info(f"Found {len(symbols)} symbols with sufficient {bar_size} data")
            return symbols
        except Exception as e:
            logger.error(f"Error getting training symbols for {bar_size}: {e}")
            # Fallback to default list
            return [
                "NVDA", "TSLA", "ORCL", "AVGO", "MSFT", "GOOGL", "AAPL", 
                "META", "AMZN", "JPM", "ADBE", "V"
            ]
            
    async def _get_historical_bars_from_db(
        self, 
        symbol: str, 
        bar_size: str = "1 day",
        max_bars: int = None
    ) -> Optional[List[Dict]]:
        """Get historical bars for a symbol from unified ib_historical_data collection"""
        if self._db is None:
            return None
        
        if max_bars is None:
            max_bars = self.DEFAULT_MAX_BARS_PER_SYMBOL
            
        try:
            # Fetch bars sorted by date (oldest first for proper training)
            cursor = self._db["ib_historical_data"].find(
                {"symbol": symbol, "bar_size": bar_size},
                {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1, 
                 "low": 1, "close": 1, "volume": 1}
            ).sort("date", 1).limit(max_bars)  # Ascending order (oldest first), limited
            
            bars = list(cursor)
            
            # Convert 'date' field to 'timestamp' for compatibility with model
            for bar in bars:
                bar['timestamp'] = bar.pop('date', None)
            
            return bars if bars else None
            
        except Exception as e:
            logger.warning(f"Could not get {bar_size} bars for {symbol} from DB: {e}")
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
