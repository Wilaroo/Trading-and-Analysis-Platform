"""
Time-Series AI Service - Directional Forecasting Integration

Integrates XGBoost directional forecasting into the AI modules system.
Provides predictions for the AI Trade Consultation.

Key Features:
- Direction prediction (up/down/flat)
- Probability-based confidence
- Auto-training from historical data
- Performance tracking
- Training Priority Mode - pauses non-essential tasks during training

Note: Requires xgboost to be installed. Will gracefully degrade if not available.
"""

import logging
import os
import base64
import io
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
import asyncio

logger = logging.getLogger(__name__)

# Import training mode manager
try:
    from services.training_mode import training_mode_manager
except ImportError:
    training_mode_manager = None

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
    
    # Memory-safe settings per timeframe
    # Optimized for DGX Spark (128GB unified memory + XGBoost GPU)
    # Larger batches = faster training with more data loaded at once
    # IMPORTANT: We keep max_bars high to use ALL available data - only batch_size is reduced
    # This ensures we don't lose training data, just process fewer symbols at a time
    TIMEFRAME_SETTINGS = {
        "1 min": {"batch_size": 25, "max_bars": 50000, "is_intraday": True},     # 50K bars ≈ 125 trading days
        "5 mins": {"batch_size": 50, "max_bars": 50000, "is_intraday": True},    # 50K bars ≈ 640 trading days
        "15 mins": {"batch_size": 75, "max_bars": 50000, "is_intraday": True},   # 50K bars ≈ 1920 trading days
        "30 mins": {"batch_size": 100, "max_bars": 50000, "is_intraday": True},  # 50K bars
        "1 hour": {"batch_size": 200, "max_bars": 50000, "is_intraday": False},  # 50K bars
        "1 day": {"batch_size": 500, "max_bars": 10000, "is_intraday": False},   # 10K bars ≈ 40 years
        "1 week": {"batch_size": 500, "max_bars": 5000, "is_intraday": False},   # 5K bars ≈ 96 years
    }
    
    # Training defaults — PRODUCTION settings
    # Use ALL ADV-qualified symbols — no artificial ceiling
    # ADV thresholds in setup_training_config.py are the real filter
    # Batch processing prevents OOM on intraday timeframes
    DEFAULT_MAX_SYMBOLS = 99999   # Effectively uncapped — ADV filter is the real gate
    DEFAULT_MAX_BARS_PER_SYMBOL = 99999  # Use all available bars per symbol
    
    # Setup types that have enough strategies to justify a dedicated model
    SETUP_TYPES = {
        "MOMENTUM": {"description": "Trend-following momentum plays", "min_strategies": 35},
        "SCALP": {"description": "Quick scalp trades on micro-moves", "min_strategies": 12},
        "BREAKOUT": {"description": "Price breakout from consolidation", "min_strategies": 6},
        "GAP_AND_GO": {"description": "Gap continuation plays", "min_strategies": 4},
        "RANGE": {"description": "Range-bound mean reversion", "min_strategies": 4},
        "REVERSAL": {"description": "Trend reversal/counter-trend", "min_strategies": 3},
        "TREND_CONTINUATION": {"description": "Continuation after pullback", "min_strategies": 3},
        "ORB": {"description": "Opening Range Breakout", "min_strategies": 2},
        "VWAP": {"description": "VWAP bounce/fade plays", "min_strategies": 3},
        "MEAN_REVERSION": {"description": "Statistical mean reversion", "min_strategies": 1},
    }
    
    def __init__(self):
        self._model = get_timeseries_model() if ML_AVAILABLE else None
        self._models = {}  # Cache for multi-timeframe models
        self._setup_models = {}  # Cache for setup-type-specific models
        self._db = None
        self._historical_service = None
        self._last_train_time = None
        self._ml_available = ML_AVAILABLE
        self._training_in_progress = False
        self._training_status = {}
        self._stop_training = False  # Flag to stop training early
        # Cache for available data (expensive aggregation query)
        self._available_data_cache = None
        self._available_data_cache_time = None
        self._cache_ttl_seconds = 3600  # Cache for 1 hour
        
    def set_db(self, db):
        """Set database connection and load any saved models"""
        self._db = db
        if self._model:
            self._model.set_db(db)
        # Auto-load models from DB on startup
        if db is not None and self._ml_available:
            self.reload_models_from_db()
            self._load_setup_models_from_db()
    
    def reload_models_from_db(self):
        """Reload all trained models from MongoDB.
        
        Called after external training (worker process) saves new models,
        so the server picks up the latest versions without a restart.
        """
        if self._db is None or not self._ml_available:
            return {"reloaded": 0}
        
        reloaded = 0
        # Check both ai_models and timeseries_models collections
        collections_to_check = ["ai_models", "timeseries_models"]
        
        for bar_size, config in self.SUPPORTED_TIMEFRAMES.items():
            model_name = config["model_name"]
            try:
                doc = None
                for col_name in collections_to_check:
                    doc = self._db[col_name].find_one({"name": model_name})
                    if doc and "model_data" in doc:
                        break
                    doc = None
                
                if doc and "model_data" in doc:
                    model_bytes = base64.b64decode(doc["model_data"])
                    model_format = doc.get("model_format", "pickle")
                    
                    # Create or update the cached model
                    from .timeseries_gbm import TimeSeriesGBM, ModelMetrics
                    if bar_size not in self._models:
                        self._models[bar_size] = TimeSeriesGBM(model_name=model_name)
                        self._models[bar_size].set_db(self._db)
                    
                    if model_format == "xgboost_json":
                        # New XGBoost JSON format
                        import xgboost as xgb
                        booster = xgb.Booster()
                        booster.load_model(bytearray(model_bytes))
                        self._models[bar_size]._model = booster
                    else:
                        # Legacy LightGBM pickle — skip (needs retraining)
                        logger.warning(f"Legacy LightGBM model found for {model_name}, needs retraining with XGBoost")
                        continue
                    
                    self._models[bar_size]._version = doc.get("version", "v0.0.0")
                    if doc.get("metrics"):
                        self._models[bar_size]._metrics = ModelMetrics(**doc.get("metrics", {}))
                    reloaded += 1
                    logger.info(f"Reloaded model {model_name} {doc.get('version', '?')} from DB")
            except Exception as e:
                logger.warning(f"Could not reload model {model_name}: {e}")
        
        # Also try to load the default model via GBM's own loader
        if self._model is None:
            try:
                from .timeseries_gbm import TimeSeriesGBM
                default_model = TimeSeriesGBM(model_name="direction_predictor")
                default_model.set_db(self._db)
                if default_model._model is not None:
                    self._model = default_model
                    reloaded += 1
                    logger.info("Loaded default direction_predictor model from DB")
            except Exception as e:
                logger.warning(f"Could not load default model: {e}")
        elif self._model._db is not None:
            self._model._load_model()
            if self._model._model is not None:
                reloaded += 1
        
        logger.info(f"Reloaded {reloaded} models from database")
        return {"reloaded": reloaded}

        
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
            return self._empty_forecast(symbol, "ML not available - xgboost not installed")
            
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
            return {"success": False, "error": "ML not available - xgboost not installed"}
            
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
        
        # ENTER TRAINING MODE - Pause non-essential background tasks
        if training_mode_manager:
            training_mode_manager.enter_training_mode(training_type='single', timeframe=bar_size)
            logger.info(f"[TRAINING MODE] Entered for {bar_size}")
        
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
            
            # Log training to history for tracking improvement over time
            await self._log_training_history(
                bar_size=bar_size,
                model_name=model_name,
                metrics=metrics,
                symbols_used=len(bars_by_symbol),
                total_bars=total_bars
            )
            
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
            # EXIT TRAINING MODE - Resume background tasks
            if training_mode_manager:
                training_mode_manager.exit_training_mode()
                logger.info(f"[TRAINING MODE] Exited for {bar_size}")
    
    async def _train_model_internal(
        self,
        bar_size: str = "1 day",
        max_symbols: int = None,
        max_bars_per_symbol: int = None
    ) -> Dict[str, Any]:
        """
        Internal training method used by train_all_timeframes.
        Does NOT manage training mode (caller handles that).
        """
        if max_symbols is None:
            max_symbols = self.DEFAULT_MAX_SYMBOLS
        if max_bars_per_symbol is None:
            max_bars_per_symbol = self.DEFAULT_MAX_BARS_PER_SYMBOL
            
        model_config = self.SUPPORTED_TIMEFRAMES[bar_size]
        model_name = model_config["model_name"]
        
        logger.info(f"[FULL TRAIN] Starting internal training for {bar_size}...")
        
        try:
            model = TimeSeriesGBM(model_name=model_name)
            model.set_db(self._db)
            
            logger.info(f"[FULL TRAIN] Fetching symbols for {bar_size}...")
            symbols = await self._get_training_symbols_from_db(bar_size=bar_size, limit=max_symbols)
            logger.info(f"[FULL TRAIN] Found {len(symbols)} symbols for {bar_size}")
            
            bars_by_symbol = {}
            loaded_count = 0
            for symbol in symbols:
                bars = await self._get_historical_bars_from_db(symbol, bar_size=bar_size, max_bars=max_bars_per_symbol)
                if bars and len(bars) >= self.MIN_BARS_FOR_TRAINING:
                    bars_by_symbol[symbol] = bars
                    loaded_count += 1
                    if loaded_count % 25 == 0:
                        logger.info(f"[FULL TRAIN] {bar_size}: Loaded {loaded_count} symbols...")
            
            if not bars_by_symbol:
                logger.warning(f"[FULL TRAIN] No data available for {bar_size}")
                return {"success": False, "error": f"No data for {bar_size}"}
            
            total_bars = sum(len(b) for b in bars_by_symbol.values())
            symbols_used = len(bars_by_symbol)
            logger.info(f"[FULL TRAIN] Training {bar_size} model on {symbols_used} symbols, {total_bars:,} bars...")
            
            metrics = model.train(bars_by_symbol)
            self._models[bar_size] = model
            
            # Update training status
            self._training_status[bar_size] = {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "message": f"{metrics.accuracy*100:.1f}% accuracy" if metrics else "Completed"
            }
            
            # Log to history with correct parameters
            await self._log_training_history(
                bar_size=bar_size, 
                model_name=model_name, 
                metrics=metrics, 
                symbols_used=symbols_used,
                total_bars=total_bars
            )
            
            accuracy = getattr(metrics, 'accuracy', None) if metrics else None
            logger.info(f"[FULL TRAIN] ✓ Completed {bar_size}: {accuracy*100:.1f}% accuracy" if accuracy else f"[FULL TRAIN] ✓ Completed {bar_size}")
            
            return {
                "success": True,
                "total_bars": total_bars,
                "samples": total_bars,
                "symbols_used": symbols_used,
                "metrics": {"accuracy": accuracy} if metrics else {}
            }
        except Exception as e:
            logger.error(f"[FULL TRAIN] Error training {bar_size}: {e}", exc_info=True)
            self._training_status[bar_size] = {
                "status": "error",
                "message": str(e)
            }
            return {"success": False, "error": str(e)}
            
    async def train_all_timeframes(
        self,
        max_symbols: int = None,
        max_bars_per_symbol: int = None,
        timeframes: List[str] = None
    ) -> Dict[str, Any]:
        """
        Train models for all (or specified) timeframes sequentially.
        
        Args:
            max_symbols: Max symbols per timeframe (default: 50)
            max_bars_per_symbol: Max bars per symbol (default: 500)
            timeframes: List of specific timeframes to train (default: all)
            
        Returns:
            Combined results for all timeframes
        """
        if not self._ml_available:
            return {"success": False, "error": "ML not available - xgboost not installed"}
        
        if timeframes is None:
            timeframes = list(self.SUPPORTED_TIMEFRAMES.keys())
        
        # ENTER TRAINING MODE for full training
        if training_mode_manager:
            training_mode_manager.enter_training_mode(training_type='full', timeframe='all')
            logger.info(f"[TRAINING MODE] Entered for FULL training ({len(timeframes)} timeframes)")
        
        results = {}
        overall_success = True
        total_bars_trained = 0
        total_samples = 0
        completed_count = 0
        
        logger.info("=" * 60)
        logger.info(f"[FULL TRAIN] Starting training for {len(timeframes)} timeframes")
        logger.info(f"[FULL TRAIN] Settings: max_symbols={max_symbols or self.DEFAULT_MAX_SYMBOLS}, max_bars={max_bars_per_symbol or self.DEFAULT_MAX_BARS_PER_SYMBOL}")
        logger.info("=" * 60)
        
        self._training_in_progress = True
        
        try:
            for idx, tf in enumerate(timeframes, 1):
                if tf not in self.SUPPORTED_TIMEFRAMES:
                    results[tf] = {"success": False, "error": f"Unsupported timeframe: {tf}"}
                    continue
                
                logger.info("")
                logger.info(f"[FULL TRAIN] === Training {idx}/{len(timeframes)}: {tf} ===")
                
                self._training_status[tf] = {
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "message": "Loading data..."
                }
                
                try:
                    result = await self._train_model_internal(
                        bar_size=tf,
                        max_symbols=max_symbols,
                        max_bars_per_symbol=max_bars_per_symbol
                    )
                    results[tf] = result
                    
                    if result.get("success"):
                        total_bars_trained += result.get("total_bars", 0)
                        total_samples += result.get("samples", 0)
                        completed_count += 1
                        logger.info(f"[FULL TRAIN] ✓ {tf} completed ({completed_count}/{len(timeframes)})")
                    else:
                        logger.warning(f"[FULL TRAIN] ✗ {tf} failed: {result.get('error', 'Unknown error')}")
                        overall_success = False
                        
                except Exception as e:
                    logger.error(f"[FULL TRAIN] Exception training {tf}: {e}", exc_info=True)
                    results[tf] = {"success": False, "error": str(e)}
                    overall_success = False
                
                # Small delay between timeframes to prevent memory buildup
                if idx < len(timeframes):
                    logger.info("[FULL TRAIN] Pausing 2s before next timeframe...")
                    await asyncio.sleep(2)
                    
        except Exception as e:
            logger.error(f"[FULL TRAIN] Fatal error: {e}", exc_info=True)
            overall_success = False
        finally:
            self._training_in_progress = False
            # EXIT TRAINING MODE
            if training_mode_manager:
                training_mode_manager.exit_training_mode()
                logger.info("[TRAINING MODE] Exited for FULL training")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"[FULL TRAIN] COMPLETE: {completed_count}/{len(timeframes)} models trained")
        logger.info(f"[FULL TRAIN] Total bars: {total_bars_trained:,}")
        logger.info("=" * 60)
        
        return {
            "success": overall_success,
            "timeframes_trained": completed_count,
            "total_timeframes": len(timeframes),
            "total_bars_trained": total_bars_trained,
            "total_samples": total_samples,
            "results": results
        }

    async def train_full_universe(
        self,
        bar_size: str = "1 day",
        symbol_batch_size: int = 500,
        max_bars_per_symbol: int = 0,
        progress_callback = None
    ) -> Dict[str, Any]:
        """
        Train on the FULL UNIVERSE of symbols using chunked loading.
        
        This method processes symbols in batches to avoid memory overload:
        1. Get ALL symbols with data for this timeframe
        2. Process symbols in batches of `symbol_batch_size`
        3. Extract features from each batch (features are small, bars are large)
        4. Accumulate features, discard raw bars to free memory
        5. Train model on all accumulated features
        
        Optimized for DGX Spark (128GB unified memory + XGBoost GPU):
        - Vectorized feature extraction (extract_features_bulk)
        - Feature caching (skip recomputation on subsequent runs)
        - Large batch sizes (500 symbols at once)
        - Per-timeframe max_bars from TIMEFRAME_SETTINGS
        
        Args:
            bar_size: Timeframe to train (e.g., "1 day")
            symbol_batch_size: How many symbols to load at once (default: 500 — 128GB handles this easily)
            max_bars_per_symbol: Max bars per symbol. 0 = use TIMEFRAME_SETTINGS default.
            progress_callback: Optional callback for progress updates
            
        Returns:
            Training result with metrics
        """
        import gc
        import sys
        import traceback
        import numpy as np
        
        print(f"[FULL UNIVERSE] ===== train_full_universe ENTERED for {bar_size} =====", flush=True)
        sys.stdout.flush()
        
        if not self._ml_available:
            return {"success": False, "error": "ML not available - xgboost not installed"}
            
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
            
        if bar_size not in self.SUPPORTED_TIMEFRAMES:
            return {"success": False, "error": f"Unsupported bar_size: {bar_size}"}
        
        # Resolve per-timeframe max_bars from TIMEFRAME_SETTINGS if not explicitly set
        if max_bars_per_symbol <= 0:
            tf_settings = self.TIMEFRAME_SETTINGS.get(bar_size, {})
            max_bars_per_symbol = tf_settings.get("max_bars", 50000)
            # For intraday timeframes, cap higher to get more training data
            # while still avoiding the 100K+ hang: 50K bars ≈ 125 trading days of 1-min
            if tf_settings.get("is_intraday", False) and max_bars_per_symbol < 50000:
                max_bars_per_symbol = 50000
        
        model_config = self.SUPPORTED_TIMEFRAMES[bar_size]
        model_name = model_config["model_name"]
        
        # Enter training mode
        if training_mode_manager:
            training_mode_manager.enter_training_mode(training_type='full_universe', timeframe=bar_size)
            logger.info(f"[FULL UNIVERSE] Entered training mode for {bar_size}")
        
        self._training_in_progress = True
        self._training_status[bar_size] = {
            "status": "running",
            "phase": "initializing",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "message": "Starting full universe training..."
        }
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Step 1: Get ALL symbols with data for this timeframe
            logger.info("")
            logger.info("=" * 70)
            logger.info(f"[FULL UNIVERSE] Starting training for {bar_size}")
            # Log advanced-feature flag state so retrain logs are self-documenting.
            _cusum_on = os.environ.get("TB_USE_CUSUM", "0")
            _ffd_on = os.environ.get("TB_USE_FFD_FEATURES", "0")
            logger.info(
                f"[FULL UNIVERSE] Flags: TB_USE_CUSUM={_cusum_on} "
                f"TB_USE_FFD_FEATURES={_ffd_on}  (triple-barrier labels: ALWAYS ON)"
            )
            logger.info(f"[FULL UNIVERSE] Batch size: {symbol_batch_size} symbols, Max bars: {max_bars_per_symbol}")
            logger.info("=" * 70)
            sys.stdout.flush()
            
            self._training_status[bar_size]["phase"] = "fetching_symbols"
            self._training_status[bar_size]["message"] = "Fetching all symbols..."
            
            logger.info("[FULL UNIVERSE] Step 1: Fetching symbols...")
            sys.stdout.flush()
            
            all_symbols = await self._get_all_symbols_for_timeframe(bar_size)
            total_symbols = len(all_symbols)
            
            logger.info(f"[FULL UNIVERSE] Found {total_symbols:,} symbols")
            sys.stdout.flush()
            
            if total_symbols == 0:
                return {"success": False, "error": f"No symbols found for {bar_size}"}
            
            # Production mode - train on ALL symbols
            # For testing with fewer symbols, pass a smaller symbol_batch_size or max_symbols parameter
            logger.info(f"[FULL UNIVERSE] Will process {total_symbols:,} symbols with {bar_size} data")
            sys.stdout.flush()
            
            # Step 2: Create model and feature engineer
            logger.info("[FULL UNIVERSE] Step 2: Creating model and feature engineer...")
            sys.stdout.flush()
            
            model = TimeSeriesGBM(model_name=model_name)
            model.set_db(self._db)
            feature_engineer = model._feature_engineer
            feature_names = model._feature_names
            forecast_horizon = model.forecast_horizon
            
            logger.info(f"[FULL UNIVERSE] Model created: {model_name}, forecast_horizon={forecast_horizon}")
            sys.stdout.flush()
            
            # Step 3: Process symbols in batches, accumulating features as numpy chunks
            # MEMORY OPTIMIZATION: Store features as numpy float32 arrays (4 bytes/float)
            # instead of Python lists of float objects (28 bytes/float = 9x overhead).
            # For 43M samples x 46 features: ~8 GB (numpy) vs ~74 GB (Python lists).
            feature_chunks = []   # List of numpy arrays, vstacked once at the end
            target_chunks = []    # List of numpy arrays
            total_samples = 0
            symbols_processed = 0
            symbols_with_data = 0
            total_bars_processed = 0
            
            self._training_status[bar_size]["phase"] = "loading_data"
            self._training_status[bar_size]["total_symbols"] = total_symbols
            
            num_batches = (total_symbols + symbol_batch_size - 1) // symbol_batch_size
            
            logger.info(f"[FULL UNIVERSE] Step 3: Processing {num_batches} batches...")
            sys.stdout.flush()
            
            import time as _time
            _phase1_start = _time.monotonic()
            
            for batch_idx in range(num_batches):
                batch_start = batch_idx * symbol_batch_size
                batch_end = min(batch_start + symbol_batch_size, total_symbols)
                batch_symbols = all_symbols[batch_start:batch_end]
                
                batch_feat_parts = []   # numpy arrays for this batch
                batch_tgt_parts = []
                
                logger.info(f"[FULL UNIVERSE] Processing batch {batch_idx + 1}/{num_batches} ({batch_start + 1}-{batch_end} of {total_symbols})")
                sys.stdout.flush()
                
                sym_count_in_batch = 0
                cache_hits_batch = 0
                for symbol in batch_symbols:
                    sym_count_in_batch += 1
                    try:
                        # Check feature cache first (skip expensive extraction if cached)
                        cached = model._load_features_from_cache(symbol, bar_size)
                        if cached and cached.get("features") and cached.get("targets"):
                            batch_feat_parts.append(np.array(cached["features"], dtype=np.float32))
                            batch_tgt_parts.append(np.array(cached["targets"], dtype=np.float32))
                            symbols_with_data += 1
                            cache_hits_batch += 1
                            if sym_count_in_batch % 50 == 0:
                                logger.info(f"[FULL UNIVERSE]   {sym_count_in_batch}/{len(batch_symbols)} in batch (cache hits: {cache_hits_batch})")
                                sys.stdout.flush()
                            continue
                        
                        # Load bars for this symbol — with timeout to prevent infinite hangs
                        try:
                            bars = await asyncio.wait_for(
                                self._get_historical_bars_from_db(
                                    symbol, 
                                    bar_size=bar_size,
                                    max_bars=max_bars_per_symbol
                                ),
                                timeout=120  # 2 min max per symbol query
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"[FULL UNIVERSE] TIMEOUT loading {symbol} ({bar_size}) — skipping")
                            continue
                        
                        if not bars or len(bars) < 50 + forecast_horizon:
                            continue
                        
                        symbols_with_data += 1
                        total_bars_processed += len(bars)
                        
                        # VECTORIZED feature extraction (10-50x faster than per-window loop)
                        bulk_features = feature_engineer.extract_features_bulk(bars)

                        if bulk_features is not None and len(bulk_features) > forecast_horizon:
                            # Phase 2B: FFD augmentation (flag-gated). When ON, bulk_features
                            # grows from 46 → 51 cols. feature_names must be kept in sync (done
                            # once below after the first successful augmentation).
                            from .feature_augmentors import augment_features, ffd_enabled
                            if ffd_enabled():
                                bulk_features, _ = augment_features(
                                    bulk_features, feature_engineer.get_feature_names(),
                                    bars, lookback=feature_engineer.lookback,
                                    cache_key=f"{symbol}_{bar_size}",
                                )

                            highs = np.array([b.get("high", 0.0) for b in bars], dtype=np.float64)
                            lows = np.array([b.get("low", 0.0) for b in bars], dtype=np.float64)
                            closes = np.array([b.get("close", 0) for b in bars], dtype=np.float64)
                            closes = np.where(closes == 0, 1.0, closes)
                            lb = feature_engineer.lookback  # 50
                            n_usable = min(len(bulk_features), len(closes) - lb - forecast_horizon + 1)

                            if n_usable > 0:
                                # Triple-barrier labels (replaces legacy returns>0 binary path)
                                from .triple_barrier_labeler import triple_barrier_labels, label_to_class_index
                                from .cusum_filter import cusum_enabled, filter_entry_indices

                                base_idx = lb - 1
                                entry_indices = np.arange(base_idx, base_idx + n_usable)

                                # CUSUM event filter (flag-gated)
                                if cusum_enabled():
                                    filtered = filter_entry_indices(
                                        entry_indices, closes, bar_size=bar_size,
                                        target_events_per_year=100,
                                        min_distance=max(1, forecast_horizon // 2),
                                    )
                                    if len(filtered) >= 50:
                                        entry_indices = filtered

                                raw_labels = triple_barrier_labels(
                                    highs, lows, closes,
                                    entry_indices=entry_indices,
                                    pt_atr_mult=2.0,
                                    sl_atr_mult=1.0,
                                    max_bars=forecast_horizon,
                                    atr_period=14,
                                )
                                symbol_targets_np = np.array(
                                    [label_to_class_index(int(lbl)) for lbl in raw_labels],
                                    dtype=np.int64,
                                )

                                # Map entry bars → feature rows and align
                                chosen_rows = entry_indices - base_idx
                                chosen_rows = chosen_rows[(chosen_rows >= 0) & (chosen_rows < len(bulk_features))]
                                symbol_features_np = bulk_features[chosen_rows].astype(np.float32)
                                symbol_targets_np = symbol_targets_np[: len(symbol_features_np)]

                                batch_feat_parts.append(symbol_features_np)
                                batch_tgt_parts.append(symbol_targets_np.astype(np.float32))

                                # Save to feature cache (lists needed for JSON serialization)
                                model._save_features_to_cache(
                                    symbol, symbol_features_np.tolist(),
                                    symbol_targets_np.astype(int).tolist(), bar_size
                                )
                                del symbol_features_np, symbol_targets_np
                        
                        # Clear bars from memory after processing
                        del bars
                        
                        # Per-symbol progress logging (every 10 symbols)
                        if sym_count_in_batch % 10 == 0:
                            _elapsed = _time.monotonic() - _phase1_start
                            _total_done = batch_start + sym_count_in_batch
                            _rate = _total_done / _elapsed if _elapsed > 0 else 0
                            _remaining = (total_symbols - _total_done) / _rate if _rate > 0 else 0
                            _eta_min = int(_remaining // 60)
                            _eta_sec = int(_remaining % 60)
                            logger.info(
                                f"[FULL UNIVERSE]   {sym_count_in_batch}/{len(batch_symbols)} in batch "
                                f"({symbols_with_data} with data, {total_bars_processed:,} bars) "
                                f"[{_total_done}/{total_symbols} total, ETA {_eta_min}m{_eta_sec:02d}s]"
                            )
                            sys.stdout.flush()
                            
                            # Push mid-batch progress to UI every 100 symbols
                            if progress_callback and sym_count_in_batch % 100 == 0:
                                try:
                                    mid_pct = (batch_start + sym_count_in_batch) / total_symbols * 100
                                    progress_callback(
                                        mid_pct,
                                        f"{batch_start + sym_count_in_batch}/{total_symbols} symbols ({total_bars_processed:,} bars, ETA {_eta_min}m{_eta_sec:02d}s)"
                                    )
                                except Exception:
                                    pass
                        
                    except Exception as e:
                        logger.warning(f"[FULL UNIVERSE] Error processing {symbol}: {e}")
                        continue
                
                # Consolidate batch into a single numpy chunk and accumulate
                if batch_feat_parts:
                    batch_X = np.vstack(batch_feat_parts)
                    batch_y = np.concatenate(batch_tgt_parts)
                    batch_samples = len(batch_X)
                    feature_chunks.append(batch_X)
                    target_chunks.append(batch_y)
                    total_samples += batch_samples
                else:
                    batch_samples = 0
                
                symbols_processed = batch_end
                
                # Update status
                progress_pct = (symbols_processed / total_symbols) * 100
                self._training_status[bar_size].update({
                    "message": f"Loaded {symbols_processed:,}/{total_symbols:,} symbols ({progress_pct:.1f}%)",
                    "symbols_processed": symbols_processed,
                    "symbols_with_data": symbols_with_data,
                    "samples_collected": total_samples,
                    "bars_processed": total_bars_processed
                })
                
                # Push progress to pipeline DB (drives WS → UI updates)
                if progress_callback:
                    try:
                        progress_callback(
                            progress_pct,
                            f"Batch {batch_idx + 1}/{num_batches} ({symbols_processed:,}/{total_symbols:,} symbols, {total_bars_processed:,} bars)"
                        )
                    except Exception:
                        pass
                
                _batch_elapsed = _time.monotonic() - _phase1_start
                _batch_elapsed_min = int(_batch_elapsed // 60)
                _batch_elapsed_sec = int(_batch_elapsed % 60)
                logger.info(
                    f"[FULL UNIVERSE] Batch {batch_idx + 1}/{num_batches} complete: "
                    f"{batch_samples:,} samples, Total: {total_samples:,} samples "
                    f"[Elapsed: {_batch_elapsed_min}m{_batch_elapsed_sec:02d}s]"
                )
                sys.stdout.flush()
                
                # Force garbage collection after each batch
                del batch_feat_parts, batch_tgt_parts
                gc.collect()
                
                # Log memory usage periodically for monitoring
                try:
                    import psutil
                    process = psutil.Process()
                    mem_mb = process.memory_info().rss / 1024 / 1024
                    logger.info(f"[FULL UNIVERSE] Memory usage: {mem_mb:.0f} MB")
                    
                    # Emergency stop if memory usage is too high (>100GB on 128GB Spark)
                    if mem_mb > 100000:
                        logger.warning(f"[FULL UNIVERSE] HIGH MEMORY WARNING: {mem_mb:.0f} MB - stopping early to prevent crash")
                        break
                except ImportError:
                    pass  # psutil not installed
                
                sys.stdout.flush()
                
                # Small delay to prevent overwhelming the system
                await asyncio.sleep(0.5)
                
                # Check for stop request
                if self._stop_training:
                    logger.warning("[FULL UNIVERSE] Training stopped by user request")
                    self._stop_training = False  # Reset flag
                    return {
                        "success": False,
                        "error": "Training stopped by user",
                        "partial_progress": {
                            "symbols_processed": symbols_with_data,
                            "samples_collected": total_samples,
                            "bars_processed": total_bars_processed
                        }
                    }
            
            # Step 4: Train the model on accumulated features
            logger.info(f"[FULL UNIVERSE] Step 4: Training model on {total_samples:,} samples...")
            sys.stdout.flush()
            
            if total_samples < 100:
                return {
                    "success": False, 
                    "error": f"Insufficient training data: {total_samples} samples (need 100+)"
                }
            
            logger.info("")
            logger.info("[FULL UNIVERSE] Feature extraction complete!")
            logger.info(f"[FULL UNIVERSE] Total samples: {total_samples:,}")
            logger.info(f"[FULL UNIVERSE] Symbols with data: {symbols_with_data:,}")
            logger.info(f"[FULL UNIVERSE] Total bars processed: {total_bars_processed:,}")
            logger.info("")
            logger.info("[FULL UNIVERSE] Starting XGBoost GPU training...")
            sys.stdout.flush()
            
            self._training_status[bar_size]["phase"] = "training"
            self._training_status[bar_size]["message"] = f"Training on {total_samples:,} samples..."
            
            # Combine numpy chunks into final arrays (single allocation, no Python list overhead)
            X = np.vstack(feature_chunks).astype(np.float32)
            y = np.concatenate(target_chunks).astype(np.int64)

            logger.info(f"[FULL UNIVERSE] Arrays created: X shape={X.shape}, y shape={y.shape}")
            sys.stdout.flush()

            # Keep feature_names aligned with X when FFD columns were appended.
            from .feature_augmentors import ffd_enabled, FFD_NAMES
            if ffd_enabled() and X.shape[1] == len(feature_names) + len(FFD_NAMES):
                feature_names = list(feature_names) + list(FFD_NAMES)
                logger.info(f"[FULL UNIVERSE] Extended feature_names to {len(feature_names)} (FFD ON)")

            # Free the chunk lists
            del feature_chunks
            del target_chunks
            gc.collect()

            # 3-class distribution (triple-barrier: 0=DOWN, 1=FLAT, 2=UP)
            n_down = int(np.sum(y == 0))
            n_flat = int(np.sum(y == 1))
            n_up = int(np.sum(y == 2))
            total = len(y)
            logger.info(
                f"[FULL UNIVERSE] Class distribution: DOWN={n_down:,} ({n_down/total*100:.1f}%), "
                f"FLAT={n_flat:,} ({n_flat/total*100:.1f}%), "
                f"UP={n_up:,} ({n_up/total*100:.1f}%)"
            )
            sys.stdout.flush()

            # Train/validation split
            validation_split = 0.2
            split_idx = int(len(X) * (1 - validation_split))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]

            logger.info(f"[FULL UNIVERSE] Training samples: {len(X_train):,}, Validation: {len(X_val):,}")
            sys.stdout.flush()

            # Create XGBoost DMatrix datasets
            import xgboost as xgb
            logger.info("[FULL UNIVERSE] Creating XGBoost DMatrix datasets...")
            sys.stdout.flush()

            dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
            dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)

            # XGBoost GPU parameters — multiclass for 3-class triple-barrier targets.
            xgb_params = {
                'objective': 'multi:softprob',
                'num_class': 3,
                'eval_metric': 'mlogloss',
                'tree_method': 'hist',
                'device': 'cuda',
                'max_depth': 8,
                'learning_rate': 0.05,
                'colsample_bytree': 0.8,
                'subsample': 0.8,
                'max_bin': 256,
                'verbosity': 1,
            }

            logger.info("[FULL UNIVERSE] Starting XGBoost train() [3-class multi:softprob]...")
            sys.stdout.flush()

            trained_model = xgb.train(
                xgb_params,
                dtrain,
                num_boost_round=300,
                evals=[(dtrain, "train"), (dval, "val")],
                early_stopping_rounds=20,
                verbose_eval=50
            )

            logger.info("[FULL UNIVERSE] XGBoost training complete!")
            sys.stdout.flush()

            # Evaluate (3-class)
            y_pred_proba = trained_model.predict(dval)   # shape (N, 3)
            y_pred = np.argmax(y_pred_proba, axis=1)

            accuracy = float(np.mean(y_pred == y_val))

            # UP-class metrics (class idx 2) — keep existing metric schema
            from sklearn.metrics import precision_score, recall_score, f1_score
            y_val_up = (y_val == 2).astype(int)
            y_pred_up = (y_pred == 2).astype(int)
            precision_up = float(precision_score(y_val_up, y_pred_up, zero_division=0))
            recall_up = float(recall_score(y_val_up, y_pred_up, zero_division=0))
            f1_up = float(f1_score(y_val_up, y_pred_up, zero_division=0))
            
            logger.info("")
            logger.info("[FULL UNIVERSE] ✓ Training complete!")
            logger.info(f"[FULL UNIVERSE] Accuracy: {accuracy*100:.2f}%")
            logger.info(f"[FULL UNIVERSE] Precision: {precision_up*100:.2f}%, Recall: {recall_up*100:.2f}%, F1: {f1_up*100:.2f}%")
            sys.stdout.flush()
            
            # Save model — mark as 3-class triple-barrier so metadata persists correctly.
            model._model = trained_model
            model._num_classes = 3
            model._feature_names = list(feature_names)
            model._version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            
            from .timeseries_gbm import ModelMetrics
            model._metrics = ModelMetrics(
                accuracy=accuracy,
                precision_up=precision_up,
                recall_up=recall_up,
                f1_up=f1_up,
                training_samples=len(X_train),
                validation_samples=len(X_val),
                last_trained=datetime.now(timezone.utc).isoformat()
            )
            
            logger.info("[FULL UNIVERSE] Saving model...")
            sys.stdout.flush()
            
            save_result = model._save_model()
            if save_result == "promoted":
                logger.info("[FULL UNIVERSE] Model saved and promoted as active!")
            elif save_result == "archived":
                logger.info("[FULL UNIVERSE] Model saved to archive (existing active model has better accuracy).")
            else:
                logger.warning("[FULL UNIVERSE] Model save failed! Model is in memory only.")
            
            self._models[bar_size] = model
            
            # Log training history
            try:
                await self._log_training_history(
                    bar_size=bar_size,
                    model_name=model_name,
                    metrics=model._metrics,
                    symbols_used=symbols_with_data,
                    total_bars=total_bars_processed
                )
            except Exception as hist_err:
                logger.warning(f"[FULL UNIVERSE] Could not log training history: {hist_err}")
            
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            self._training_status[bar_size] = {
                "status": "completed",
                "phase": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "message": f"Full universe trained: {accuracy*100:.1f}% accuracy",
                "elapsed_seconds": elapsed
            }
            
            logger.info("")
            logger.info("=" * 70)
            logger.info(f"[FULL UNIVERSE] COMPLETE for {bar_size}")
            logger.info(f"[FULL UNIVERSE] Elapsed time: {elapsed/60:.1f} minutes")
            logger.info("=" * 70)
            sys.stdout.flush()
            
            return {
                "success": True,
                "bar_size": bar_size,
                "model_name": model_name,
                "accuracy": accuracy,
                "precision": precision_up,
                "recall": recall_up,
                "f1": f1_up,
                "training_samples": len(X_train),
                "validation_samples": len(X_val),
                "symbols_processed": symbols_with_data,
                "total_bars": total_bars_processed,
                "elapsed_seconds": elapsed
            }
            
        except Exception as e:
            logger.error(f"[FULL UNIVERSE] Fatal error: {e}", exc_info=True)
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            self._training_status[bar_size] = {
                "status": "error",
                "message": str(e)
            }
            return {"success": False, "error": str(e)}
            
        finally:
            self._training_in_progress = False
            if training_mode_manager:
                training_mode_manager.exit_training_mode()
            gc.collect()
    
    async def train_full_universe_all_timeframes(
        self,
        symbol_batch_size: int = 500,
        max_bars_per_symbol: int = 99999,
        timeframes: List[str] = None
    ) -> Dict[str, Any]:
        """
        Train FULL UNIVERSE on ALL timeframes sequentially.
        
        This is the comprehensive training that uses all 178M+ bars.
        Expected runtime: 8-12 hours on DGX Spark (first run), faster with cached features.
        
        Args:
            symbol_batch_size: Symbols per batch (default: 500 — 128GB Spark handles this easily)
            max_bars_per_symbol: Max bars per symbol (default: 99999 — use ALL available data)
            timeframes: Specific timeframes or all if None
        """
        import sys
        import gc
        import traceback
        
        # IMMEDIATE logging with flush to ensure we see output
        print("[FULL UNIVERSE ALL] ===== FUNCTION ENTERED =====", flush=True)
        sys.stdout.flush()
        sys.stderr.flush()
        
        try:
            if timeframes is None:
                # Train ALL 7 timeframes - order from most to least data
                timeframes = ["1 day", "1 hour", "5 mins", "15 mins", "30 mins", "1 min", "1 week"]
            
            logger.info("")
            logger.info("#" * 70)
            logger.info("# FULL UNIVERSE TRAINING - ALL TIMEFRAMES")
            logger.info(f"# Timeframes: {timeframes}")
            logger.info(f"# Batch size: {symbol_batch_size}, Max bars: {max_bars_per_symbol}")
            logger.info("# This may take 1-3 hours...")
            logger.info("#" * 70)
            sys.stdout.flush()
            
            # Force GC before starting
            gc.collect()
            logger.info("[FULL UNIVERSE ALL] Initial GC completed")
            sys.stdout.flush()
            
            results = {}
            total_elapsed = 0
            completed_count = 0
            
            for idx, tf in enumerate(timeframes, 1):
                logger.info("")
                logger.info(f">>> Starting timeframe {idx}/{len(timeframes)}: {tf}")
                sys.stdout.flush()
                
                try:
                    # Force GC before each timeframe
                    gc.collect()
                    
                    # Use timeframe-specific settings for memory safety
                    # Key insight: Use small batch sizes (few symbols at a time) but ALL bars per symbol
                    tf_settings = self.TIMEFRAME_SETTINGS.get(tf, {})
                    tf_batch_size = tf_settings.get("batch_size", symbol_batch_size)
                    tf_max_bars = tf_settings.get("max_bars", 10000)  # Default high to use all data
                    is_intraday = tf_settings.get("is_intraday", False)
                    
                    # For batch_size: use the smaller of user-provided and timeframe-specific (memory safety)
                    # For max_bars: use the LARGER value to ensure we don't miss data (unless user explicitly wants less)
                    actual_batch_size = min(symbol_batch_size, tf_batch_size)
                    actual_max_bars = max(max_bars_per_symbol, tf_max_bars)  # Use MORE bars, not fewer
                    
                    logger.info(f">>> Settings for {tf}: batch_size={actual_batch_size} (process {actual_batch_size} symbols at a time)")
                    logger.info(f">>> Settings for {tf}: max_bars={actual_max_bars} per symbol (using ALL available data)")
                    logger.info(f">>> Intraday timeframe: {is_intraday}")
                    sys.stdout.flush()
                    
                    result = await self.train_full_universe(
                        bar_size=tf,
                        symbol_batch_size=actual_batch_size,
                        max_bars_per_symbol=actual_max_bars
                    )
                    
                    results[tf] = result
                    
                    if result.get("success"):
                        completed_count += 1
                        elapsed = result.get("elapsed_seconds", 0)
                        total_elapsed += elapsed
                        logger.info(f">>> ✓ {tf} complete: {result.get('accuracy', 0)*100:.1f}% accuracy in {elapsed/60:.1f} min")
                    else:
                        logger.error(f">>> ✗ {tf} failed: {result.get('error', 'Unknown')}")
                    
                except Exception as tf_error:
                    logger.error(f">>> EXCEPTION training {tf}: {tf_error}")
                    traceback.print_exc()
                    results[tf] = {"success": False, "error": str(tf_error)}
                
                sys.stdout.flush()
                
                # Force GC after each timeframe
                gc.collect()
                
                # Log memory after GC
                try:
                    import psutil
                    process = psutil.Process()
                    mem_mb = process.memory_info().rss / 1024 / 1024
                    logger.info(f">>> Memory after GC: {mem_mb:.0f} MB")
                except ImportError:
                    pass
                
                # Longer pause between timeframes - even longer for intraday
                if idx < len(timeframes):
                    next_tf = timeframes[idx] if idx < len(timeframes) else None
                    next_is_intraday = self.TIMEFRAME_SETTINGS.get(next_tf, {}).get("is_intraday", False)
                    pause_seconds = 10 if next_is_intraday else 5
                    logger.info(f">>> Pausing {pause_seconds} seconds before next timeframe...")
                    await asyncio.sleep(pause_seconds)
            
            logger.info("")
            logger.info("#" * 70)
            logger.info("# FULL UNIVERSE TRAINING COMPLETE")
            logger.info(f"# Timeframes trained: {completed_count}/{len(timeframes)}")
            logger.info(f"# Total elapsed: {total_elapsed/60:.1f} minutes")
            logger.info("#" * 70)
            sys.stdout.flush()
            
            return {
                "success": completed_count > 0,
                "timeframes_trained": completed_count,
                "total_timeframes": len(timeframes),
                "total_elapsed_seconds": total_elapsed,
                "results": results
            }
            
        except Exception as e:
            logger.error(f"[FULL UNIVERSE ALL] FATAL ERROR: {e}")
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            return {"success": False, "error": str(e)}
    
    async def _get_all_symbols_for_timeframe(self, bar_size: str) -> List[str]:
        """Get ALL symbols that have data for a specific timeframe.
        Runs MongoDB query in thread pool to avoid blocking the event loop."""
        if self._db is None:
            return []
        
        def _blocking_query():
            """This runs in a thread pool"""
            try:
                pipeline = [
                    {"$match": {"bar_size": bar_size}},
                    {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                    {"$match": {"count": {"$gte": self.MIN_BARS_FOR_TRAINING}}},
                    {"$sort": {"count": -1}}  # Most data first
                ]
                
                result = list(self._db["ib_historical_data"].aggregate(
                    pipeline, 
                    allowDiskUse=True,
                    maxTimeMS=120000  # 2 minute timeout for large queries
                ))
                
                return [r["_id"] for r in result]
            except Exception as e:
                logger.error(f"Error in blocking query for {bar_size}: {e}")
                return []
        
        try:
            # Run blocking MongoDB query in thread pool
            logger.info(f"[FULL UNIVERSE] Fetching symbols for {bar_size} (running in thread pool)...")
            loop = asyncio.get_event_loop()
            symbols = await loop.run_in_executor(None, _blocking_query)
            logger.info(f"[FULL UNIVERSE] Found {len(symbols)} symbols for {bar_size}")
            return symbols
            
        except Exception as e:
            logger.error(f"Error getting symbols for {bar_size}: {e}")
            return []

    
    def get_training_status(self) -> Dict[str, Any]:
        """Get current training status for all timeframes"""
        return {
            "training_in_progress": self._training_in_progress,
            "timeframe_status": self._training_status,
            "supported_timeframes": list(self.SUPPORTED_TIMEFRAMES.keys()),
            "last_train_time": self._last_train_time.isoformat() if self._last_train_time else None
        }
    
    def get_available_timeframe_data(self) -> Dict[str, Any]:
        """Get info about available data for each timeframe from the database.
        Returns hardcoded fallback IMMEDIATELY to prevent UI blocking.
        Background refresh can update the cache later."""
        import time
        
        # HARDCODED FALLBACK - Known data as of March 2026
        # This ensures data always shows even if DB is slow/unavailable
        FALLBACK_DATA = {
            "success": True,
            "timeframes": {
                "5 mins": {"bar_count": 8520175, "symbol_count": 3969, "model_name": "direction_predictor_5min", "description": "Intraday scalping"},
                "1 hour": {"bar_count": 7637648, "symbol_count": 4622, "model_name": "direction_predictor_1hour", "description": "Swing trading"},
                "1 day": {"bar_count": 6953754, "symbol_count": 9399, "model_name": "direction_predictor_daily", "description": "Position trades"},
                "15 mins": {"bar_count": 6107242, "symbol_count": 3964, "model_name": "direction_predictor_15min", "description": "Short-term swings"},
                "1 min": {"bar_count": 5058804, "symbol_count": 2701, "model_name": "direction_predictor_1min", "description": "Ultra-short scalping"},
                "30 mins": {"bar_count": 4075607, "symbol_count": 2603, "model_name": "direction_predictor_30min", "description": "Intraday swings"},
                "1 week": {"bar_count": 689605, "symbol_count": 1181, "model_name": "direction_predictor_weekly", "description": "Long-term trends"}
            },
            "total_bars": 39042835,
            "cached": True,
            "cache_source": "fallback"
        }
        
        # Check memory cache first (fastest)
        current_time = time.time()
        if (self._available_data_cache is not None and 
            self._available_data_cache_time is not None and
            current_time - self._available_data_cache_time < self._cache_ttl_seconds):
            logger.debug("Returning memory-cached available data")
            return self._available_data_cache
        
        # ALWAYS return fallback immediately - don't wait for DB
        # This prevents the UI from showing "0 bars" while waiting for slow queries
        logger.info("Returning fallback data immediately (39M bars)")
        self._available_data_cache = FALLBACK_DATA
        self._available_data_cache_time = current_time
        return FALLBACK_DATA
            
    async def _get_training_symbols_from_db(self, bar_size: str = "1 day", limit: int = None) -> List[str]:
        """Get ALL ADV-qualified symbols with sufficient historical data for a specific bar_size.
        
        The ADV (Average Daily Volume) threshold is the ONLY filter — no artificial symbol cap.
        ADV thresholds ensure models only train on liquid stocks:
          - 500K+ ADV for intraday (1min, 5min, 15min, 30min, 1hr)
          - 100K+ ADV for swing (1day)
          - 50K+ ADV for position (1week)
        
        Runs MongoDB query in thread pool to avoid blocking the event loop."""
        if self._db is None:
            return []
        
        from services.ai_modules.setup_training_config import get_adv_threshold
        adv_threshold = get_adv_threshold(bar_size)
        
        def _blocking_query():
            """This runs in a thread pool"""
            try:
                # Step 1: Get ADV-qualified symbols from cache — this IS the filter
                adv_qualified = set()
                adv_cursor = self._db["symbol_adv_cache"].find(
                    {"avg_volume": {"$gte": adv_threshold}},
                    {"_id": 0, "symbol": 1}
                )
                for doc in adv_cursor:
                    adv_qualified.add(doc["symbol"])
                
                if not adv_qualified:
                    logger.warning(f"No symbols meet ADV threshold {adv_threshold:,} for {bar_size}")
                    return []
                
                logger.info(
                    f"ADV filter: {len(adv_qualified)} symbols >= {adv_threshold:,} volume "
                    f"(threshold for {bar_size})"
                )
                
                # Step 2: From those, find symbols with enough bars — no artificial limit
                pipeline = [
                    {"$match": {"bar_size": bar_size, "symbol": {"$in": list(adv_qualified)}}},
                    {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                    {"$match": {"count": {"$gte": self.MIN_BARS_FOR_TRAINING}}},
                    {"$sort": {"count": -1}},
                ]
                # Only apply limit if explicitly set (not the default uncapped value)
                if limit and limit < 99999:
                    pipeline.append({"$limit": limit})
                
                result = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
                return [r["_id"] for r in result]
            except Exception as e:
                logger.error(f"Error in blocking query for training symbols {bar_size}: {e}")
                return []
            
        try:
            loop = asyncio.get_event_loop()
            symbols = await loop.run_in_executor(None, _blocking_query)
            logger.info(
                f"Found {len(symbols)} ADV-filtered symbols with sufficient {bar_size} data "
                f"(ADV >= {adv_threshold:,})"
            )
            return symbols if symbols else [
                "NVDA", "TSLA", "ORCL", "AVGO", "MSFT", "GOOGL", "AAPL", 
                "META", "AMZN", "JPM", "ADBE", "V"
            ]
        except Exception as e:
            logger.error(f"Error getting training symbols for {bar_size}: {e}")
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
        """Get historical bars for a symbol from unified ib_historical_data collection.
        Runs MongoDB query in thread pool to avoid blocking the event loop."""
        if self._db is None:
            return None
        
        if max_bars is None:
            max_bars = self.DEFAULT_MAX_BARS_PER_SYMBOL
        
        def _blocking_query():
            """This runs in a thread pool.
            Uses reverse-sort (newest first) + reverse for large limits.
            This is much faster than ascending sort on huge collections because
            MongoDB can walk backward from the index tip."""
            try:
                query = {"symbol": symbol, "bar_size": bar_size}
                projection = {"_id": 0, "symbol": 1, "date": 1, "open": 1, "high": 1, 
                     "low": 1, "close": 1, "volume": 1}
                
                if max_bars > 5000:
                    # Reverse-sort trick: fetch newest N bars descending, then reverse
                    cursor = self._db["ib_historical_data"].find(
                        query, projection
                    ).sort("date", -1).limit(max_bars).batch_size(10000).max_time_ms(90000)
                    bars = list(cursor)
                    bars.reverse()  # Back to chronological order
                else:
                    cursor = self._db["ib_historical_data"].find(
                        query, projection
                    ).sort("date", 1).limit(max_bars).batch_size(10000).max_time_ms(90000)
                    bars = list(cursor)
                
                # Convert 'date' field to 'timestamp' for compatibility with model
                for bar in bars:
                    bar['timestamp'] = bar.pop('date', None)
                
                return bars if bars else None
            except Exception as e:
                logger.warning(f"Could not get {bar_size} bars for {symbol} from DB: {e}")
                return None
            
        try:
            # Run blocking MongoDB query in thread pool
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _blocking_query)
            
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
    
    async def _log_training_history(
        self,
        bar_size: str,
        model_name: str,
        metrics,
        symbols_used: int,
        total_bars: int
    ):
        """Log training run to history for tracking model improvement over time"""
        if self._db is None:
            return
            
        try:
            history_record = {
                "timestamp": datetime.now(timezone.utc),
                "bar_size": bar_size,
                "model_name": model_name,
                "accuracy": metrics.accuracy,
                "precision_up": metrics.precision_up,
                "recall_up": metrics.recall_up,
                "f1_up": metrics.f1_up,
                "training_samples": metrics.training_samples,
                "validation_samples": metrics.validation_samples,
                "symbols_used": symbols_used,
                "total_bars": total_bars,
                "top_features": metrics.top_features[:5] if metrics.top_features else [],
                "version": getattr(metrics, 'last_trained', None)
            }
            
            self._db["model_training_history"].insert_one(history_record)
            logger.info(f"Logged training history for {model_name}: {metrics.accuracy*100:.1f}% accuracy")
            
        except Exception as e:
            logger.warning(f"Could not log training history: {e}")
    
    def get_training_history(self, bar_size: str = None, limit: int = 20) -> List[Dict]:
        """Get training history for tracking model improvement"""
        if self._db is None:
            return []
            
        try:
            query = {}
            if bar_size:
                query["bar_size"] = bar_size
                
            history = list(
                self._db["model_training_history"]
                .find(query, {"_id": 0})
                .sort("timestamp", -1)
                .limit(limit)
            )
            return history
        except Exception as e:
            logger.warning(f"Could not get training history: {e}")
            return []
            
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
        model_status = self._model.get_status() if self._model else {}
        
        # Setup models status
        setup_status = {}
        for st, model in self._setup_models.items():
            try:
                # Convert tuple keys to strings for JSON serialization
                key = f"{st[0]}_{st[1]}" if isinstance(st, tuple) else str(st)
                s = model.get_status()
                setup_status[key] = {
                    "trained": s.get("trained", False),
                    "version": s.get("version"),
                    "accuracy": s.get("metrics", {}).get("accuracy"),
                    "training_samples": s.get("metrics", {}).get("training_samples"),
                }
            except Exception:
                key = f"{st[0]}_{st[1]}" if isinstance(st, tuple) else str(st)
                setup_status[key] = {"trained": False}
        
        return {
            "service": "timeseries_ai",
            "model": model_status,
            "setup_models": setup_status,
            "setup_models_count": len(self._setup_models),
            "last_train": self._last_train_time.isoformat() if self._last_train_time else None,
            "historical_service_connected": self._historical_service is not None,
            "db_connected": self._db is not None
        }
    
    # ===================== SETUP-SPECIFIC MODEL METHODS =====================
    
    def _load_setup_models_from_db(self):
        """Load all setup-specific models from MongoDB on startup.
        Models are keyed by (setup_type, bar_size) in the DB and cached
        as self._setup_models[(setup_type, bar_size)]."""
        if self._db is None or not self._ml_available:
            return
        
        col = self._db["setup_type_models"]
        loaded = 0
        for doc in col.find({"model_data": {"$exists": True}}):
            try:
                setup_type = doc.get("setup_type")
                bar_size = doc.get("bar_size", "1 day")
                if not setup_type:
                    continue
                model_bytes = base64.b64decode(doc["model_data"])
                model_format = doc.get("model_format", "pickle")
                
                from services.ai_modules.setup_training_config import get_model_name
                model_name = doc.get("model_name") or get_model_name(setup_type, bar_size)
                gbm = TimeSeriesGBM(model_name=model_name)
                gbm.set_db(self._db)
                
                if model_format == "xgboost_json":
                    import xgboost as xgb
                    booster = xgb.Booster()
                    booster.load_model(bytearray(model_bytes))
                    gbm._model = booster
                else:
                    # Legacy LightGBM pickle — skip (needs retraining)
                    logger.warning(f"Legacy LightGBM model found for setup {setup_type}, needs retraining")
                    continue
                
                gbm._version = doc.get("version", "v0.0.0")
                if doc.get("metrics"):
                    gbm._metrics = ModelMetrics(**doc["metrics"])
                if doc.get("feature_names"):
                    gbm._feature_names = doc["feature_names"]
                
                # Store with compound key (setup_type, bar_size)
                cache_key = (setup_type, bar_size)
                self._setup_models[cache_key] = gbm
                # Also keep legacy single-key for backward compat with predict_for_setup
                if setup_type not in self._setup_models:
                    self._setup_models[setup_type] = gbm
                loaded += 1
                logger.info(f"Loaded setup model: {setup_type}/{bar_size} ({doc.get('version', '?')})")
            except Exception as e:
                logger.warning(f"Could not load setup model {doc.get('setup_type')}/{doc.get('bar_size')}: {e}")
        
        if loaded:
            logger.info(f"Loaded {loaded} setup-specific models from database")

        # Fallback: also scan `timeseries_models` for models that training wrote
        # there directly (via TimeSeriesGBM._save_model → MODEL_COLLECTION). The
        # legacy `setup_type_models` loop above only catches the old schema;
        # anything trained by the current training_pipeline ends up in
        # `timeseries_models`, keyed by model_name. Without this fallback, models
        # like `short_scalp_1min_predictor` sit in the DB but `_setup_models`
        # stays empty → every predict_for_setup call falls through to the
        # general model. (Latent bug found 2026-04-24 when revalidator had 17
        # trained models but `_setup_models` had 0 loaded at runtime.)
        from services.ai_modules.setup_training_config import (
            SETUP_TRAINING_PROFILES, get_model_name,
        )
        ts_col = self._db["timeseries_models"]
        ts_loaded = 0
        for setup_type, profiles in SETUP_TRAINING_PROFILES.items():
            for profile in profiles:
                bar_size = profile.get("bar_size")
                if not bar_size:
                    continue
                cache_key = (setup_type, bar_size)
                if cache_key in self._setup_models:
                    continue  # Already loaded via legacy path
                model_name = get_model_name(setup_type, bar_size)
                doc = ts_col.find_one({"name": model_name, "model_data": {"$exists": True}})
                if not doc:
                    continue
                try:
                    gbm = TimeSeriesGBM(model_name=model_name)
                    gbm.set_db(self._db)  # triggers _load_model() which handles xgboost_json_zlib
                    if gbm._model is None:
                        logger.warning(f"Failed to load {model_name} from timeseries_models (model=None after set_db)")
                        continue
                    self._setup_models[cache_key] = gbm
                    # Legacy single-key compat so predict_for_setup() direct
                    # dict lookups hit. Only first profile per setup claims the
                    # bare-setup key (matches the existing _load loop behaviour).
                    if setup_type not in self._setup_models:
                        self._setup_models[setup_type] = gbm
                    ts_loaded += 1
                    logger.info(
                        f"Loaded setup model from timeseries_models: "
                        f"{setup_type}/{bar_size} (name={model_name}, v={gbm._version})"
                    )
                except Exception as e:
                    logger.warning(f"Could not load {model_name} from timeseries_models: {e}")

        if ts_loaded:
            logger.info(f"Loaded {ts_loaded} additional setup models from timeseries_models")

        # Startup consistency diagnostic — catches "trained in DB, not loaded
        # in memory" mismatches immediately. If this warning fires on boot,
        # something in the load path is broken and shorts/longs aren't actually
        # reaching predict_for_setup.
        try:
            diag = self.diagnose_model_load_consistency()
            if diag["missing_count"] > 0:
                logger.warning(
                    f"Model load consistency: {diag['loaded_count']}/{diag['trained_in_db_count']} "
                    f"trained models reachable. MISSING: {diag['missing_models']}"
                )
            else:
                logger.info(
                    f"Model load consistency OK: {diag['loaded_count']}/{diag['trained_in_db_count']} "
                    "trained models loaded into memory."
                )
        except Exception as e:
            logger.warning(f"Could not run model load consistency diagnostic: {e}")

    def diagnose_model_load_consistency(self) -> Dict[str, Any]:
        """
        Cross-check `timeseries_models` (source of truth — what was trained and
        persisted) against `_setup_models` (what's reachable from
        predict_for_setup at runtime).

        Returns a report structure with:
          - trained_in_db: list of model_names found in timeseries_models
          - loaded_in_memory: list of model_names that resolved into _setup_models
          - missing_models: trained but not loaded (the latent-bug signal)
          - extra_models: loaded but not in timeseries_models (corrupt cache / stale load)
          - by_setup: per-(setup, bar) detail

        This runs automatically at startup and is exposed via
        /api/ai-training/model-load-diagnostic for on-demand inspection.
        """
        from services.ai_modules.setup_training_config import (
            SETUP_TRAINING_PROFILES, get_model_name,
        )
        report: Dict[str, Any] = {
            "trained_in_db": [],
            "loaded_in_memory": [],
            "missing_models": [],
            "extra_models": [],
            "by_setup": [],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

        if self._db is None:
            report["error"] = "db is None — no consistency check possible"
            report["trained_in_db_count"] = 0
            report["loaded_count"] = 0
            report["missing_count"] = 0
            return report

        # What the DB says was trained
        trained_names = set()
        try:
            for doc in self._db["timeseries_models"].find(
                {"model_data": {"$exists": True}},
                {"_id": 0, "name": 1},
            ):
                n = doc.get("name")
                if n:
                    trained_names.add(n)
        except Exception as e:
            report["error"] = f"timeseries_models scan failed: {e}"

        # What the in-memory dict holds (compound keys + legacy keys)
        loaded_model_names = set()
        for key, gbm in self._setup_models.items():
            if gbm is None or getattr(gbm, "_model", None) is None:
                continue
            name = getattr(gbm, "model_name", None)
            if name:
                loaded_model_names.add(name)

        # Restrict to declared SETUP_TRAINING_PROFILES — we don't flag the
        # general direction_predictor or oddball one-off models here.
        profile_expected = set()
        per_setup_rows = []
        for setup_type, profiles in SETUP_TRAINING_PROFILES.items():
            for profile in profiles:
                bar = profile.get("bar_size")
                if not bar:
                    continue
                model_name = get_model_name(setup_type, bar)
                profile_expected.add(model_name)
                is_trained = model_name in trained_names
                is_loaded = model_name in loaded_model_names
                per_setup_rows.append({
                    "setup_type": setup_type,
                    "bar_size": bar,
                    "model_name": model_name,
                    "trained_in_db": is_trained,
                    "loaded_in_memory": is_loaded,
                    "status": (
                        "loaded" if is_loaded and is_trained
                        else "missing_in_memory" if is_trained and not is_loaded
                        else "not_trained"
                    ),
                })

        trained_in_profiles = trained_names & profile_expected
        missing = sorted(trained_in_profiles - loaded_model_names)
        # "extra" = loaded but not expected from any profile (rare; possible
        # with cross-profile legacy naming). Don't over-fire — only flag if
        # it's a profile model we can't explain.
        extra = sorted(loaded_model_names - trained_names)

        report["trained_in_db"] = sorted(trained_in_profiles)
        report["loaded_in_memory"] = sorted(loaded_model_names & profile_expected)
        report["missing_models"] = missing
        report["extra_models"] = extra
        report["by_setup"] = per_setup_rows
        report["trained_in_db_count"] = len(trained_in_profiles)
        report["loaded_count"] = len(loaded_model_names & profile_expected)
        report["missing_count"] = len(missing)
        return report
    
    def get_setup_models_status(self) -> Dict[str, Any]:
        """Get status of all setup-specific models, organized by profile.
        Checks MongoDB for trained models if not found in memory cache.
        """
        from services.ai_modules.setup_training_config import (
            get_setup_profiles, get_model_name, get_all_profile_count
        )
        
        models = {}
        total_profiles = 0
        trained_count = 0
        
        for st_name, st_config in self.SETUP_TYPES.items():
            profiles = get_setup_profiles(st_name)
            profile_statuses = []
            
            for profile in profiles:
                total_profiles += 1
                bar_size = profile["bar_size"]
                cache_key = (st_name, bar_size)
                model = self._setup_models.get(cache_key)
                
                if model and model._model is not None:
                    trained_count += 1
                    metrics = model._metrics
                    profile_statuses.append({
                        "bar_size": bar_size,
                        "trained": True,
                        "description": profile.get("description", ""),
                        "version": model._version,
                        "model_name": get_model_name(st_name, bar_size),
                        "accuracy": metrics.accuracy if metrics else None,
                        "training_samples": metrics.training_samples if metrics else 0,
                        "validation_samples": metrics.validation_samples if metrics else 0,
                        "trained_at": metrics.last_trained if metrics else None,
                        "forecast_horizon": profile["forecast_horizon"],
                        "noise_threshold": profile["noise_threshold"],
                        "num_classes": int(getattr(model, "_num_classes", profile.get("num_classes", 3))),
                        "label_scheme": "triple_barrier_3class" if int(getattr(model, "_num_classes", 3)) >= 3 else "binary",
                    })
                else:
                    # Check MongoDB for trained model not yet loaded into memory
                    model_name = get_model_name(st_name, bar_size)
                    db_model = None
                    if self._db is not None:
                        try:
                            db_model = self._db["timeseries_models"].find_one(
                                {"name": model_name},
                                {"_id": 0, "metrics": 1, "version": 1, "saved_at": 1, "num_classes": 1, "label_scheme": 1}
                            )
                        except Exception:
                            pass
                    
                    if db_model and db_model.get("metrics"):
                        trained_count += 1
                        m = db_model["metrics"]
                        nc = int(db_model.get("num_classes", profile.get("num_classes", 3)))
                        profile_statuses.append({
                            "bar_size": bar_size,
                            "trained": True,
                            "description": profile.get("description", ""),
                            "version": db_model.get("version", "unknown"),
                            "model_name": model_name,
                            "accuracy": m.get("accuracy"),
                            "training_samples": m.get("training_samples", 0),
                            "validation_samples": m.get("validation_samples", 0),
                            "trained_at": m.get("last_trained") or db_model.get("saved_at"),
                            "forecast_horizon": profile["forecast_horizon"],
                            "noise_threshold": profile["noise_threshold"],
                            "num_classes": nc,
                            "label_scheme": db_model.get("label_scheme") or ("triple_barrier_3class" if nc >= 3 else "binary"),
                        })
                    else:
                        profile_statuses.append({
                            "bar_size": bar_size,
                            "trained": False,
                            "description": profile.get("description", ""),
                            "model_name": model_name,
                            "forecast_horizon": profile["forecast_horizon"],
                            "noise_threshold": profile["noise_threshold"],
                            "num_classes": profile.get("num_classes", 3),
                            "label_scheme": "triple_barrier_3class",
                        })
            
            models[st_name] = {
                "description": st_config["description"],
                "profiles": profile_statuses,
                "profiles_trained": sum(1 for p in profile_statuses if p["trained"]),
                "profiles_total": len(profile_statuses),
            }
        
        training_status = {}
        for k, v in self._training_status.items():
            if k.startswith("setup_"):
                training_status[k] = v
        
        return {
            "total_setup_types": len(self.SETUP_TYPES),
            "total_profiles": total_profiles,
            "models_trained": trained_count,
            "models": models,
            "training_status": training_status,
        }
    
    async def train_setup_model(
        self,
        setup_type: str,
        bar_size: str = None,
        max_symbols: int = None,
        max_bars_per_symbol: int = None,
    ) -> Dict[str, Any]:
        """
        Train a model for one (setup_type, bar_size) profile.
        
        If bar_size is None, trains ALL profiles for that setup type and
        returns a combined result. If bar_size is specified, trains only
        that specific profile.
        """
        if not self._ml_available:
            return {"success": False, "error": "ML not available - xgboost not installed"}
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        setup_type = setup_type.upper()
        if setup_type not in self.SETUP_TYPES and setup_type not in [
            "PULLBACK", "VWAP_FADE", "FLAG", "PIVOT", "SWING", "VWAP_BOUNCE"
        ]:
            return {"success": False, "error": f"Unknown setup type: {setup_type}"}
        
        effective_type = setup_type
        if setup_type in ("VWAP_BOUNCE", "VWAP_FADE"):
            effective_type = "VWAP"
        
        from services.ai_modules.setup_training_config import (
            get_setup_profiles, get_setup_profile, get_model_name
        )
        
        if bar_size is None:
            # Train ALL profiles for this setup type
            profiles = get_setup_profiles(effective_type)
            results = {}
            completed = 0
            for idx, profile in enumerate(profiles):
                pbar = profile["bar_size"]
                logger.info(f"[SETUP TRAIN] {effective_type} profile {idx+1}/{len(profiles)}: {pbar}")
                result = await self._train_single_setup_profile(
                    effective_type, profile, max_symbols, max_bars_per_symbol
                )
                results[pbar] = result
                if result.get("success"):
                    completed += 1
            
            return {
                "success": completed > 0,
                "setup_type": effective_type,
                "profiles_trained": completed,
                "profiles_total": len(profiles),
                "results": results,
            }
        else:
            # Train single specified profile
            profile = get_setup_profile(effective_type, bar_size)
            return await self._train_single_setup_profile(
                effective_type, profile, max_symbols, max_bars_per_symbol
            )
    
    async def _train_single_setup_profile(
        self,
        setup_type: str,
        profile: dict,
        max_symbols: int = None,
        max_bars_per_symbol: int = None,
    ) -> Dict[str, Any]:
        """
        Train one model for a specific (setup_type, bar_size) profile.
        
        This is the core training loop: loads bars for the profile's bar_size,
        scans for setup patterns, extracts features, and trains a LightGBM model.
        """
        from services.ai_modules.setup_training_config import get_model_name
        
        bar_size = profile["bar_size"]
        forecast_horizon = profile["forecast_horizon"]
        noise_threshold = profile["noise_threshold"]
        class_weight = profile["scale_pos_weight"]
        min_samples = profile["min_samples"]
        num_boost_round = profile["num_boost_round"]
        num_classes = profile.get("num_classes", 3)
        
        if max_symbols is None:
            max_symbols = self.DEFAULT_MAX_SYMBOLS
        if max_bars_per_symbol is None:
            max_bars_per_symbol = max(self.DEFAULT_MAX_BARS_PER_SYMBOL, 50 + forecast_horizon + 100)
        
        model_name = get_model_name(setup_type, bar_size)
        status_key = f"setup_{setup_type}_{bar_size}"
        cache_key = (setup_type, bar_size)
        
        logger.info(
            f"[SETUP TRAIN] {setup_type}/{bar_size}: horizon={forecast_horizon}, "
            f"threshold={noise_threshold*100:.2f}%, weight={class_weight}, "
            f"rounds={num_boost_round}, classes={num_classes}, model={model_name}"
        )
        
        self._training_in_progress = True
        self._training_status[status_key] = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "message": f"Loading data for {setup_type}/{bar_size}..."
        }
        
        try:
            import numpy as np
            from services.ai_modules.setup_pattern_detector import detect_setup
            from services.ai_modules.setup_features import get_setup_features, get_setup_feature_names
            from services.ai_modules.regime_features import (
                RegimeFeatureProvider, REGIME_FEATURE_NAMES
            )
            from services.ai_modules.multi_timeframe_features import (
                MultiTimeframeFeatureProvider, MTF_FEATURE_NAMES
            )
            
            # Create a dedicated GBM model
            model = TimeSeriesGBM(model_name=model_name, forecast_horizon=forecast_horizon)
            model.set_db(self._db)
            
            if class_weight != 1.0:
                model.params["scale_pos_weight"] = class_weight
                model.params.pop("is_unbalance", None)
            
            # Layer 1: Preload index daily bars for regime context features
            regime_provider = RegimeFeatureProvider(self._db)
            index_bar_count = await asyncio.get_event_loop().run_in_executor(
                None, regime_provider.preload_index_daily
            )
            regime_available = index_bar_count >= 25
            if regime_available:
                logger.info(f"[SETUP TRAIN] Regime features enabled ({index_bar_count} index bars)")
            else:
                logger.warning("[SETUP TRAIN] Regime features disabled (insufficient index data)")
            
            # Layer 2: Multi-timeframe features (only for intraday bar sizes)
            is_intraday = bar_size in ("1 min", "5 mins", "15 mins", "30 mins", "1 hour")
            mtf_provider = None
            mtf_available = False
            
            # Get training symbols for this bar_size
            symbols = await self._get_training_symbols_from_db(bar_size=bar_size, limit=max_symbols)
            logger.info(f"[SETUP TRAIN] {setup_type}/{bar_size}: {len(symbols)} symbols")
            
            if is_intraday:
                mtf_provider = MultiTimeframeFeatureProvider(self._db)
                mtf_loaded = await asyncio.get_event_loop().run_in_executor(
                    None, mtf_provider.preload_daily_bars, symbols
                )
                mtf_available = mtf_loaded > 0
                if mtf_available:
                    logger.info(f"[SETUP TRAIN] MTF features enabled ({mtf_loaded} daily bars)")
                else:
                    logger.warning("[SETUP TRAIN] MTF features disabled (no daily bars)")
            
            self._training_status[status_key]["message"] = f"Loading {len(symbols)} symbols..."
            
            all_feature_chunks = []
            all_target_list = []
            total_samples = 0
            total_bars_scanned = 0
            total_matches = 0
            noise_filtered = 0
            feature_engineer = get_feature_engineer()
            
            base_feature_names = feature_engineer.get_feature_names()
            setup_feature_names = get_setup_feature_names(setup_type)
            regime_feat_names = REGIME_FEATURE_NAMES if regime_available else []
            mtf_feat_names = MTF_FEATURE_NAMES if mtf_available else []
            combined_feature_names = (
                base_feature_names
                + [f"setup_{n}" for n in setup_feature_names]
                + regime_feat_names
                + mtf_feat_names
            )
            
            loaded = 0
            for symbol in symbols:
                bars = await self._get_historical_bars_from_db(
                    symbol, bar_size=bar_size, max_bars=max_bars_per_symbol
                )
                if not bars or len(bars) < 50 + forecast_horizon:
                    continue
                loaded += 1
                
                if loaded % 50 == 0:
                    self._training_status[status_key]["message"] = (
                        f"Scanning {loaded}/{len(symbols)} symbols... "
                        f"({total_matches} patterns, {noise_filtered} noise-filtered)"
                    )
                
                opens_arr = np.array([b.get('open', 0) for b in bars], dtype=np.float32)
                highs_arr = np.array([b.get('high', 0) for b in bars], dtype=np.float32)
                lows_arr = np.array([b.get('low', 0) for b in bars], dtype=np.float32)
                closes_arr = np.array([b.get('close', 0) for b in bars], dtype=np.float32)
                volumes_arr = np.array([b.get('volume', 0) for b in bars], dtype=np.float32)
                
                closes_arr = np.where(closes_arr == 0, 1, closes_arr)
                opens_arr = np.where(opens_arr == 0, closes_arr, opens_arr)
                volumes_arr = np.where(volumes_arr == 0, 1, volumes_arr)
                
                # Pre-compute ALL base features in one vectorized pass per symbol
                # instead of calling extract_features() per matched bar
                bulk_features = feature_engineer.extract_features_bulk(bars)
                if bulk_features is None:
                    continue
                
                # Collect matched positions for this symbol
                symbol_matches = []
                for i in range(len(bars) - 50 - forecast_horizon):
                    total_bars_scanned += 1
                    
                    w_opens = opens_arr[i:i+50][::-1]
                    w_highs = highs_arr[i:i+50][::-1]
                    w_lows = lows_arr[i:i+50][::-1]
                    w_closes = closes_arr[i:i+50][::-1]
                    w_volumes = volumes_arr[i:i+50][::-1]
                    
                    is_match, confidence, direction = detect_setup(
                        setup_type, w_opens, w_highs, w_lows, w_closes, w_volumes
                    )
                    
                    if not is_match:
                        continue
                    
                    total_matches += 1
                    
                    current_price = closes_arr[i + 49]
                    future_price = closes_arr[i + 49 + forecast_horizon]
                    target_return = (future_price - current_price) / current_price if current_price > 0 else 0
                    
                    if num_classes >= 3:
                        if target_return > noise_threshold:
                            target = 2  # UP
                        elif target_return < -noise_threshold:
                            target = 0  # DOWN
                        else:
                            target = 1  # FLAT
                    else:
                        if abs(target_return) < noise_threshold:
                            noise_filtered += 1
                            continue
                        target = 1 if target_return > 0 else 0
                    
                    symbol_matches.append((i, target, w_opens, w_highs, w_lows, w_closes, w_volumes))
                
                if not symbol_matches:
                    del bulk_features, bars
                    continue
                
                # Build combined feature vectors for all matches in this symbol
                for i, target, w_opens, w_highs, w_lows, w_closes, w_volumes in symbol_matches:
                    # Index into precomputed bulk features (replaces slow extract_features() call)
                    if i >= len(bulk_features):
                        continue
                    base_vector = bulk_features[i]
                    
                    setup_feats = get_setup_features(setup_type, w_opens, w_highs, w_lows, w_closes, w_volumes)
                    setup_vector = np.array([setup_feats.get(f, 0.0) for f in setup_feature_names], dtype=np.float32)
                    
                    # Layer 1: Add regime context features
                    if regime_available:
                        bar_date = str(bars[i + 49].get("timestamp", bars[i + 49].get("date", "")))
                        regime_feats = regime_provider.get_regime_features_for_date(bar_date)
                        regime_vector = np.array([regime_feats.get(f, 0.0) for f in REGIME_FEATURE_NAMES], dtype=np.float32)
                    else:
                        regime_vector = np.array([], dtype=np.float32)
                    
                    # Layer 2: Add multi-timeframe context features (intraday only)
                    if mtf_available:
                        bar_date = str(bars[i + 49].get("timestamp", bars[i + 49].get("date", "")))
                        mtf_feats = mtf_provider.get_mtf_features(symbol, bar_date)
                        mtf_vector = np.array([mtf_feats.get(f, 0.0) for f in MTF_FEATURE_NAMES], dtype=np.float32)
                    else:
                        mtf_vector = np.array([], dtype=np.float32)
                    
                    combined = np.concatenate([base_vector, setup_vector, regime_vector, mtf_vector])
                    all_feature_chunks.append(combined)
                    all_target_list.append(target)
                    total_samples += 1
                
                del bulk_features, bars, symbol_matches
            
            if total_samples < min_samples:
                msg = (f"Insufficient {setup_type}/{bar_size} patterns: "
                       f"{total_samples} usable of {total_matches} detected "
                       f"({noise_filtered} noise-filtered). Need {min_samples}+.")
                logger.warning(f"[SETUP TRAIN] {msg}")
                self._training_status[status_key] = {"status": "error", "message": msg}
                return {"success": False, "error": msg}
            
            logger.info(
                f"[SETUP TRAIN] {setup_type}/{bar_size}: {total_samples} usable from "
                f"{total_matches} detected ({noise_filtered} noise-filtered), "
                f"{loaded} symbols, {total_bars_scanned:,} bars"
            )
            
            self._training_status[status_key]["message"] = (
                f"Training {total_samples:,} patterns..."
            )
            
            X = np.vstack(all_feature_chunks).astype(np.float32)
            y = np.array(all_target_list, dtype=np.float32)
            del all_feature_chunks, all_target_list
            
            unique, counts = np.unique(y.astype(int), return_counts=True)
            class_labels = {0: "DOWN", 1: "FLAT", 2: "UP"} if num_classes >= 3 else {0: "DOWN", 1: "UP"}
            dist_parts = [f"{class_labels.get(int(c), c)}={n} ({n/len(y)*100:.1f}%)" for c, n in zip(unique, counts)]
            logger.info(f"[SETUP TRAIN] {setup_type}/{bar_size} class dist: {', '.join(dist_parts)}")
            
            metrics = model.train_from_features(
                X, y, combined_feature_names,
                skip_save=True,
                num_boost_round=num_boost_round,
                num_classes=num_classes
            )
            
            # Model protection: compare against previous model for same (setup, bar_size)
            should_promote = True
            existing_doc = self._db["setup_type_models"].find_one(
                {"setup_type": setup_type, "bar_size": bar_size},
                {"metrics": 1, "version": 1, "_id": 0}
            )
            if existing_doc and existing_doc.get("metrics"):
                existing_acc = existing_doc["metrics"].get("accuracy", 0)
                new_acc = metrics.accuracy
                if new_acc < existing_acc:
                    should_promote = False
                    logger.warning(
                        f"Model protection: NEW {setup_type}/{bar_size} ({new_acc:.4f}) "
                        f"< EXISTING ({existing_acc:.4f}). Keeping existing."
                    )
                else:
                    logger.info(
                        f"Model {setup_type}/{bar_size}: {existing_acc:.4f} -> {new_acc:.4f}. Promoting."
                    )
            
            if should_promote:
                self._setup_models[cache_key] = model
                self._setup_models[setup_type] = model  # legacy compat
                
                await self._save_setup_model_to_db(
                    setup_type, model, metrics, bar_size, loaded,
                    sum_bars=total_bars_scanned,
                    extra_meta={
                        "patterns_found": total_matches,
                        "noise_filtered": noise_filtered,
                        "usable_samples": total_samples,
                        "setup_features": [f"setup_{n}" for n in setup_feature_names],
                        "regime_features": regime_feat_names,
                        "regime_enabled": regime_available,
                        "total_features": len(combined_feature_names),
                        "num_classes": num_classes,
                        "profile": profile,
                    }
                )
            
            self._training_status[status_key] = {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "message": (
                    f"{metrics.accuracy*100:.1f}% accuracy, {total_samples:,} samples, "
                    f"horizon={forecast_horizon} bars"
                )
            }
            
            logger.info(
                f"[SETUP TRAIN] {setup_type}/{bar_size} complete: "
                f"{metrics.accuracy*100:.1f}% accuracy, {total_samples} samples"
            )
            
            return {
                "success": True,
                "setup_type": setup_type,
                "bar_size": bar_size,
                "model_name": model_name,
                "metrics": metrics.to_dict(),
                "symbols_used": loaded,
                "total_bars_scanned": total_bars_scanned,
                "patterns_found": total_matches,
                "noise_filtered": noise_filtered,
                "usable_samples": total_samples,
                "training_samples": metrics.training_samples,
                "validation_samples": metrics.validation_samples,
                "total_features": len(combined_feature_names),
                "forecast_horizon": forecast_horizon,
                "description": profile.get("description", ""),
            }
        except Exception as e:
            logger.error(f"[SETUP TRAIN] Error training {setup_type}/{bar_size}: {e}", exc_info=True)
            self._training_status[status_key] = {"status": "error", "message": str(e)}
            return {"success": False, "error": str(e)}
        finally:
            self._training_in_progress = False
    
    async def train_all_setup_models(
        self,
        max_symbols: int = None,
        max_bars_per_symbol: int = None,
    ) -> Dict[str, Any]:
        """Train ALL profiles for ALL setup types sequentially."""
        if not self._ml_available:
            return {"success": False, "error": "ML not available"}
        if self._db is None:
            return {"success": False, "error": "Database not connected"}
        
        from services.ai_modules.setup_training_config import get_setup_profiles
        
        results = {}
        total_profiles = 0
        completed = 0
        
        for setup_type in self.SETUP_TYPES:
            if self._stop_training:
                logger.info(f"[SETUP TRAIN] Stopped early after {completed} profiles")
                break
            
            profiles = get_setup_profiles(setup_type)
            setup_results = {}
            
            for profile in profiles:
                total_profiles += 1
                bar_size = profile["bar_size"]
                logger.info(f"[SETUP TRAIN ALL] {setup_type}/{bar_size} (profile {total_profiles})")
                
                result = await self._train_single_setup_profile(
                    setup_type=setup_type,
                    profile=profile,
                    max_symbols=max_symbols,
                    max_bars_per_symbol=max_bars_per_symbol,
                )
                setup_results[bar_size] = result
                if result.get("success"):
                    completed += 1
            
            results[setup_type] = setup_results
        
        return {
            "success": True,
            "total_profiles": total_profiles,
            "trained": completed,
            "failed": total_profiles - completed,
            "results": results,
        }
    
    async def _save_setup_model_to_db(self, setup_type, model, metrics, bar_size, symbols_used, sum_bars=0, extra_meta=None):
        """Save a setup-specific model to MongoDB using compound key (setup_type, bar_size)."""
        import asyncio
        from services.ai_modules.setup_training_config import get_model_name
        col = self._db["setup_type_models"]
        
        # Serialize model using XGBoost native JSON format
        import xgboost as xgb
        buffer = io.BytesIO()
        model._model.save_model(buffer)
        model_bytes = buffer.getvalue()
        model_b64 = base64.b64encode(model_bytes).decode('utf-8')
        
        # Serialize feature names so predictions use the right features
        feature_names = model._feature_names if hasattr(model, '_feature_names') else []
        
        doc = {
            "setup_type": setup_type,
            "bar_size": bar_size,
            "model_name": get_model_name(setup_type, bar_size),
            "model_data": model_b64,
            "model_format": "xgboost_json",
            "engine": "xgboost",
            "version": model._version,
            "metrics": metrics.to_dict() if metrics else {},
            "symbols_used": symbols_used,
            "total_bars": sum_bars,
            "feature_names": feature_names,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if extra_meta:
            doc.update(extra_meta)
        
        # Compound key: (setup_type, bar_size)
        await asyncio.to_thread(
            col.update_one,
            {"setup_type": setup_type, "bar_size": bar_size},
            {"$set": doc},
            upsert=True,
        )
        logger.info(f"Saved setup model {setup_type}/{bar_size} to DB")
    
    @staticmethod
    def _resolve_setup_model_key(setup_type: str, available_keys) -> str:
        """
        Map a scanner-emitted setup_type to the best matching trained-model key.

        Scanner emits fine-grained names like "rubber_band_scalp_short" or
        "vwap_reclaim_long". Training uses aggregate names like "SHORT_SCALP",
        "SHORT_VWAP", "SCALP", "VWAP". This resolver picks the most specific
        matching model that is actually loaded.

        Priority (first match wins):
          1. exact uppercase match (legacy direct lookup)
          2. short-side: try SHORT_<family> for known families
          3. base-name without _LONG / _SHORT suffix
          4. fallback to input (caller will miss → general model)

        Keeps routing logic in one place so future taxonomy changes don't
        fan out across the service.
        """
        if not setup_type:
            return setup_type
        raw = setup_type.upper()
        available = set(available_keys) if available_keys is not None else set()

        # 1. Direct hit
        if raw in available:
            return raw

        # Manual legacy remaps (existing behavior)
        legacy_remap = {"VWAP_BOUNCE": "VWAP", "VWAP_FADE": "VWAP"}
        if raw in legacy_remap and legacy_remap[raw] in available:
            return legacy_remap[raw]

        is_short = raw.endswith("_SHORT")
        is_long = raw.endswith("_LONG")
        base = raw
        if is_short:
            base = raw[:-6]
        elif is_long:
            base = raw[:-5]

        # 2. Short-side family routing. Substring-based so the 3 promoted
        # aggregate shorts (SHORT_SCALP / SHORT_VWAP / SHORT_REVERSAL) catch
        # scanner-specific short variants like RUBBER_BAND_SCALP_SHORT.
        if is_short:
            family_map = [
                ("SCALP", "SHORT_SCALP"),
                ("VWAP", "SHORT_VWAP"),
                ("REVERSAL", "SHORT_REVERSAL"),
                ("ORB", "SHORT_ORB"),
                ("BREAKDOWN", "SHORT_BREAKDOWN"),
                ("GAP", "SHORT_GAP_FADE"),
                ("RANGE", "SHORT_RANGE"),
                ("MEAN_REVERSION", "SHORT_MEAN_REVERSION"),
                ("MOMENTUM", "SHORT_MOMENTUM"),
                ("TREND", "SHORT_TREND"),
            ]
            # Try exact SHORT_<base> first
            short_exact = f"SHORT_{base}"
            if short_exact in available:
                return short_exact
            for fam_key, model_key in family_map:
                if fam_key in base and model_key in available:
                    return model_key

        # 3. Long-side / generic: strip direction suffix and try base
        if base in available:
            return base

        # Also try family substring for long-side (e.g. RUBBER_BAND_SCALP_LONG → SCALP)
        for fam_key in ("SCALP", "VWAP", "REVERSAL", "BREAKOUT", "ORB",
                        "RANGE", "MOMENTUM", "MEAN_REVERSION", "TREND"):
            if fam_key in base and fam_key in available:
                return fam_key

        # 4. No mapping — return raw (caller will fall back to general model)
        return raw

    def predict_for_setup(self, symbol: str, bars: list, setup_type: str) -> Optional[Dict]:
        """
        Make a prediction using the setup-specific model if available,
        otherwise fall back to the general model.
        
        For setup models, we must extract BOTH base features AND setup-specific
        features to match the training feature set. Regime features are also
        included if the model was trained with them.
        
        Layer 2: After raw prediction, adjusts confidence based on current
        market regime alignment with the setup's preferences.
        """
        import numpy as np
        effective_type = self._resolve_setup_model_key(setup_type, self._setup_models.keys())
        
        # Try setup-specific model first
        model = self._setup_models.get(effective_type)
        if model and model._model is not None:
            try:
                # Extract base features
                feature_set = model._feature_engineer.extract_features(
                    bars, symbol=symbol, include_target=False
                )
                if feature_set is None:
                    logger.warning(f"Could not extract base features for {symbol}")
                    # Fall through to general model
                else:
                    # Extract setup-specific features from the bar data
                    from .setup_features import get_setup_features
                    if len(bars) >= 20:
                        opens = np.array([b.get("open", 0) for b in bars])
                        highs = np.array([b.get("high", 0) for b in bars])
                        lows = np.array([b.get("low", 0) for b in bars])
                        closes = np.array([b.get("close", 0) for b in bars])
                        volumes = np.array([b.get("volume", 0) for b in bars])
                        setup_feats = get_setup_features(effective_type, opens, highs, lows, closes, volumes)
                    else:
                        setup_feats = {}
                    
                    # Combine base + setup features in training order
                    combined = {}
                    combined.update(feature_set.features)
                    # Prefix setup features to match training naming
                    for k, v in setup_feats.items():
                        combined[f"setup_{k}"] = v
                    
                    # Layer 1: Add regime features if model expects them
                    from .regime_features import REGIME_FEATURE_NAMES
                    model_expects_regime = any(
                        f in model._feature_names for f in REGIME_FEATURE_NAMES
                    )
                    if model_expects_regime:
                        try:
                            from .regime_features import compute_regime_features_from_bars
                            if self._db is not None:
                                def _query_index_bars(symbol):
                                    bars = list(self._db["ib_historical_data"].find(
                                        {"symbol": symbol, "bar_size": "1 day"},
                                        {"_id": 0, "close": 1, "high": 1, "low": 1, "date": 1}
                                    ).sort("date", -1).limit(3000))
                                    seen = {}
                                    for b in bars:
                                        dk = str(b.get("date", ""))[:10]
                                        if len(dk) == 10 and dk not in seen:
                                            seen[dk] = b
                                    real = sorted(seen.values(), key=lambda x: str(x["date"])[:10], reverse=True)
                                    if len(real) < 25:
                                        return None, None, None
                                    return (
                                        np.array([b["close"] for b in real], dtype=float),
                                        np.array([b["high"] for b in real], dtype=float),
                                        np.array([b["low"] for b in real], dtype=float),
                                    )
                                spy_c, spy_h, spy_l = _query_index_bars("SPY")
                                qqq_c, qqq_h, qqq_l = _query_index_bars("QQQ")
                                iwm_c, iwm_h, iwm_l = _query_index_bars("IWM")
                                if spy_c is not None:
                                    regime_feats = compute_regime_features_from_bars(
                                        spy_c, spy_h, spy_l,
                                        qqq_c, qqq_h, qqq_l,
                                        iwm_c, iwm_h, iwm_l,
                                    )
                                    combined.update(regime_feats)
                        except Exception as e:
                            logger.debug(f"Regime features for prediction failed: {e}")
                    
                    # Layer 2: Add MTF features if model expects them
                    from .multi_timeframe_features import MTF_FEATURE_NAMES
                    model_expects_mtf = any(
                        f in model._feature_names for f in MTF_FEATURE_NAMES
                    )
                    if model_expects_mtf:
                        try:
                            from .multi_timeframe_features import compute_mtf_features_from_daily_bars
                            if self._db is not None:
                                daily_bars = list(self._db["ib_historical_data"].find(
                                    {"symbol": symbol, "bar_size": "1 day"},
                                    {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
                                ).sort("date", -1).limit(3000))
                                seen_dates = {}
                                for b in daily_bars:
                                    dk = str(b.get("date", ""))[:10]
                                    if len(dk) == 10 and dk not in seen_dates:
                                        seen_dates[dk] = b
                                real_daily = sorted(seen_dates.values(), key=lambda x: str(x["date"])[:10], reverse=True)
                                if len(real_daily) >= 25:
                                    mtf_feats = compute_mtf_features_from_daily_bars(
                                        np.array([b["close"] for b in real_daily], dtype=float),
                                        np.array([b["high"] for b in real_daily], dtype=float),
                                        np.array([b["low"] for b in real_daily], dtype=float),
                                        np.array([b.get("volume", 0) for b in real_daily], dtype=float),
                                        np.array([b.get("open", 0) for b in real_daily], dtype=float),
                                    )
                                    combined.update(mtf_feats)
                        except Exception as e:
                            logger.debug(f"MTF features for prediction failed: {e}")
                    
                    # Build feature vector matching model's expected feature order
                    feature_vector = np.array([[
                        combined.get(f, 0.0) for f in model._feature_names
                    ]])
                    
                    # Predict using the setup model directly
                    pred_raw = model._model.predict(feature_vector)
                    
                    if len(pred_raw.shape) > 1 and pred_raw.shape[1] >= 3:
                        # 3-class: pred_raw shape = (1, 3) → [P(DOWN), P(FLAT), P(UP)]
                        prob_down = float(pred_raw[0][0])
                        prob_flat = float(pred_raw[0][1])
                        prob_up = float(pred_raw[0][2])
                        
                        # Direction = highest probability class
                        max_class = int(np.argmax(pred_raw[0]))
                        if max_class == 2:
                            direction = "up"
                            confidence = prob_up
                        elif max_class == 0:
                            direction = "down"
                            confidence = prob_down
                        else:
                            direction = "flat"
                            confidence = prob_flat
                    else:
                        # Binary: pred_raw shape = (1,) → P(UP)
                        prob_up = float(pred_raw[0]) if pred_raw.ndim == 1 else float(pred_raw[0][0])
                        prob_down = 1 - prob_up
                        prob_flat = 0.0
                        
                        if prob_up > model.UP_THRESHOLD:
                            direction = "up"
                            confidence = min((prob_up - model.UP_THRESHOLD) / (1 - model.UP_THRESHOLD), 1.0)
                        elif prob_down > 0.55:
                            direction = "down"
                            confidence = (prob_down - 0.5) * 2
                        else:
                            direction = "flat"
                            confidence = 0.2
                    
                    # Layer 2: Regime-aware confidence adjustment
                    regime_adjustment = None
                    try:
                        from .regime_confidence import adjust_confidence_for_regime
                        from services.service_registry import get_service_optional
                        
                        engine_state = None
                        scanner_regime = None
                        
                        # Try MarketRegimeEngine
                        regime_engine = get_service_optional('market_regime_engine')
                        if regime_engine and hasattr(regime_engine, 'current_state'):
                            engine_state = regime_engine.current_state.value
                        
                        # Try scanner's regime
                        scanner = get_service_optional('enhanced_scanner')
                        if scanner and hasattr(scanner, '_market_regime'):
                            scanner_regime = scanner._market_regime.value
                        
                        if engine_state or scanner_regime:
                            regime_adjustment = adjust_confidence_for_regime(
                                effective_type, confidence,
                                engine_state=engine_state,
                                scanner_regime=scanner_regime,
                            )
                            confidence = regime_adjustment["adjusted_confidence"]
                    except Exception as e:
                        logger.debug(f"Regime confidence adjustment skipped: {e}")
                    
                    result = {
                        "symbol": symbol,
                        "direction": direction,
                        "probability_up": prob_up,
                        "probability_down": prob_down,
                        "probability_flat": prob_flat,
                        "confidence": float(confidence),
                        "model_version": model._version,
                        "feature_count": len(model._feature_names),
                        "model_used": f"{effective_type.lower()}_predictor",
                        "model_type": "setup_specific",
                        "num_classes": 3 if prob_flat > 0 else 2,
                    }
                    
                    # Include regime context in result
                    if regime_adjustment:
                        result["regime_adjustment"] = regime_adjustment
                    
                    return result
            except Exception as e:
                logger.warning(f"Setup model {effective_type} prediction failed: {e}")
        
        # Fall back to general model
        if self._model and self._model._model is not None:
            try:
                prediction = self._model.predict(bars, symbol=symbol)
                if prediction:
                    result = prediction.to_dict() if hasattr(prediction, 'to_dict') else prediction
                    result["model_used"] = "general"
                    result["model_type"] = "general"
                    return result
            except Exception as e:
                logger.warning(f"General model prediction failed: {e}")
        
        return None
        
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
