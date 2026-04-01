"""
Bulk Training Pipeline

Orchestrates training for ALL model types:
  1. Generic directional models (7, one per timeframe)
  2. Setup-specific models (16, per setup+timeframe)
  3. Volatility prediction models (7, one per timeframe)  [NEW]
  4. Regime-conditional models (up to 92, per model+regime) [NEW]
  5. Exit timing models (10, per setup type)                [NEW]
  6. Ensemble meta-learner (10, per setup type)             [NEW]

Reads directly from MongoDB Atlas ib_historical_data collection.
Does NOT modify any data — read-only pipeline.

Features:
  - Batch symbol processing with memory management
  - Progress tracking via training_pipeline_status collection
  - Per-model accuracy gating (new model must beat old to be promoted)
  - Regime-aware data splitting for regime-conditional models
  - Walk-forward validation (train on past, validate on future)

Usage:
  Called from the backend API endpoint, not as a standalone script.
  See routers/ai_training.py for the trigger endpoint.
"""

import logging
import asyncio
import concurrent.futures
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Dedicated thread pool for CPU-intensive ML training + training DB reads.
# ALL training I/O uses this pool, keeping the default asyncio pool 100% free
# for FastAPI endpoints (push-data, health, etc.)
TRAINING_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=3)


async def _run_in_thread(func, *args, **kwargs):
    """Run a blocking ML function in the dedicated TRAINING_POOL."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(TRAINING_POOL, lambda: func(*args, **kwargs))

# ── Constants ──────────────────────────────────────────────

# Bar sizes and their training configs
BAR_SIZE_CONFIGS = {
    "1 min":   {"forecast_horizon": 30, "min_bars_per_symbol": 200, "max_symbols": 500},
    "5 mins":  {"forecast_horizon": 12, "min_bars_per_symbol": 200, "max_symbols": 1000},
    "15 mins": {"forecast_horizon": 8,  "min_bars_per_symbol": 150, "max_symbols": 1000},
    "30 mins": {"forecast_horizon": 6,  "min_bars_per_symbol": 150, "max_symbols": 1000},
    "1 hour":  {"forecast_horizon": 6,  "min_bars_per_symbol": 100, "max_symbols": 2000},
    "1 day":   {"forecast_horizon": 5,  "min_bars_per_symbol": 100, "max_symbols": 5000},
    "1 week":  {"forecast_horizon": 4,  "min_bars_per_symbol": 50,  "max_symbols": 5000},
}

# Setup types defined in the system
ALL_SETUP_TYPES = [
    "SCALP", "ORB", "GAP_AND_GO", "VWAP", "BREAKOUT",
    "RANGE", "MEAN_REVERSION", "REVERSAL", "TREND_CONTINUATION", "MOMENTUM",
]

# Short setup types (inverse of longs)
ALL_SHORT_SETUP_TYPES = [
    "SHORT_SCALP", "SHORT_ORB", "SHORT_GAP_FADE", "SHORT_VWAP", "SHORT_BREAKDOWN",
    "SHORT_RANGE", "SHORT_MEAN_REVERSION", "SHORT_REVERSAL", "SHORT_MOMENTUM", "SHORT_TREND",
]

# Minimum training samples to proceed with training
MIN_TRAINING_SAMPLES = 200

# Phase configuration for progress tracking
PHASE_CONFIGS = {
    "generic_directional": {"label": "Generic Directional", "order": 1, "expected_models": 7, "phase_num": "1"},
    "setup_specific": {"label": "Setup-Specific (Long)", "order": 2, "expected_models": 17, "phase_num": "2"},
    "short_setup_specific": {"label": "Setup-Specific (Short)", "order": 3, "expected_models": 17, "phase_num": "2.5"},
    "volatility_prediction": {"label": "Volatility Prediction", "order": 4, "expected_models": 7, "phase_num": "3"},
    "exit_timing": {"label": "Exit Timing", "order": 5, "expected_models": 10, "phase_num": "4"},
    "sector_relative": {"label": "Sector-Relative", "order": 6, "expected_models": 3, "phase_num": "5"},
    "risk_of_ruin": {"label": "Risk-of-Ruin", "order": 7, "expected_models": 6, "phase_num": "6"},
    "regime_conditional": {"label": "Regime-Conditional", "order": 8, "expected_models": 28, "phase_num": "7"},
    "ensemble_meta": {"label": "Ensemble Meta-Learner", "order": 9, "expected_models": 10, "phase_num": "8"},
    "cnn_patterns": {"label": "CNN Chart Patterns", "order": 10, "expected_models": 13, "phase_num": "9"},
    "auto_validation": {"label": "Auto-Validation", "order": 11, "expected_models": 34, "phase_num": "10"},
}


class TrainingPipelineStatus:
    """Track and persist pipeline training progress with per-phase granularity."""

    def __init__(self, db=None):
        self._db = db
        self._current_phase = None
        self._status = {
            "phase": "idle",
            "current_model": "",
            "models_completed": 0,
            "models_total": 0,
            "current_phase_progress": 0.0,
            "started_at": None,
            "errors": [],
            "completed_models": [],
            "phase_history": {},
        }

    def update(self, **kwargs):
        new_phase = kwargs.get("phase")
        if new_phase and new_phase != self._current_phase:
            # Auto-end previous phase
            if self._current_phase and self._current_phase in self._status["phase_history"]:
                ph = self._status["phase_history"][self._current_phase]
                if ph["status"] == "running":
                    ph["status"] = "done"
                    ph["ended_at"] = datetime.now(timezone.utc).isoformat()
                    started = datetime.fromisoformat(ph["started_at"])
                    ph["elapsed_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()

            # Auto-start new phase (if it's a real training phase)
            if new_phase in PHASE_CONFIGS:
                config = PHASE_CONFIGS[new_phase]
                self._status["phase_history"][new_phase] = {
                    "label": config["label"],
                    "order": config["order"],
                    "phase_num": config["phase_num"],
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "ended_at": None,
                    "expected_models": config["expected_models"],
                    "models_trained": 0,
                    "models_failed": 0,
                    "total_accuracy": 0.0,
                    "avg_accuracy": 0.0,
                    "elapsed_seconds": 0,
                }

            self._current_phase = new_phase

        self._status.update(kwargs)
        self._persist()

    def get_status(self) -> Dict:
        return dict(self._status)

    def start_phase(self, phase_key: str, expected_models: int):
        """Explicitly start a phase (used by validation and other manual phases)."""
        self.update(phase=phase_key)
        ph = self._status["phase_history"].get(phase_key)
        if ph:
            ph["expected_models"] = expected_models

    def end_phase(self, phase_key: str):
        """Explicitly end a phase."""
        ph = self._status["phase_history"].get(phase_key)
        if ph and ph["status"] == "running":
            ph["status"] = "done"
            ph["ended_at"] = datetime.now(timezone.utc).isoformat()
            try:
                started = datetime.fromisoformat(ph["started_at"])
                ph["elapsed_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
            except Exception:
                pass
        self._persist()

    def add_completed(self, model_name: str, accuracy: float):
        self._status["completed_models"].append({
            "name": model_name,
            "accuracy": accuracy,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        self._status["models_completed"] = len(self._status["completed_models"])

        ph = self._status["phase_history"].get(self._current_phase)
        if ph:
            ph["models_trained"] += 1
            ph["total_accuracy"] += accuracy
            ph["avg_accuracy"] = ph["total_accuracy"] / ph["models_trained"]

        self._persist()

    def model_done(self, phase_key: str, model_name: str, accuracy: float = 0, extra: dict = None):
        """Record a model completion for a specific phase (used by validation)."""
        self.add_completed(model_name, accuracy)

    def model_failed(self, phase_key: str, model_name: str, error: str):
        """Record a model failure for a specific phase."""
        self.add_error(model_name, error)

    def add_error(self, model_name: str, error: str):
        self._status["errors"].append({
            "model": model_name,
            "error": error,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        ph = self._status["phase_history"].get(self._current_phase)
        if ph:
            ph["models_failed"] += 1
        self._persist()

    def _persist(self):
        """Persist status to MongoDB — runs in background thread to avoid blocking the event loop."""
        if self._db is not None:
            try:
                status_copy = {**self._status, "updated_at": datetime.now(timezone.utc).isoformat()}
                # Deep copy phase_history to avoid mutation during write
                if "phase_history" in status_copy:
                    status_copy["phase_history"] = {
                        k: dict(v) for k, v in status_copy["phase_history"].items()
                    }
                TRAINING_POOL.submit(self._do_persist, status_copy)
            except Exception:
                pass

    def _do_persist(self, status_snapshot):
        """Actual DB write — runs in TRAINING_POOL thread."""
        try:
            self._db["training_pipeline_status"].update_one(
                {"_id": "pipeline"},
                {"$set": status_snapshot},
                upsert=True,
            )
        except Exception:
            pass


async def get_available_symbols(db, bar_size: str, min_bars: int = 100) -> List[str]:
    """Get symbols that have enough bars for training."""
    try:
        pipeline = [
            {"$match": {"bar_size": bar_size}},
            {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gte": min_bars}}},
            {"$sort": {"count": -1}},
        ]

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            TRAINING_POOL,
            lambda: list(db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
        )
        return [r["_id"] for r in results]
    except Exception as e:
        logger.error(f"Failed to get symbols for {bar_size}: {e}")
        return []


async def load_symbol_bars(db, symbol: str, bar_size: str) -> List[Dict]:
    """Load all bars for a symbol+bar_size, sorted chronologically (oldest first)."""
    try:
        loop = asyncio.get_event_loop()
        bars = await loop.run_in_executor(
            TRAINING_POOL,
            lambda: list(db["ib_historical_data"].find(
                {"symbol": symbol, "bar_size": bar_size},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            ).sort("date", 1))
        )
        return bars
    except Exception as e:
        logger.warning(f"Failed to load bars for {symbol}/{bar_size}: {e}")
        return []


def count_total_models() -> int:
    """Count total models that will be trained."""
    from services.ai_modules.setup_training_config import get_all_profile_count, SETUP_TRAINING_PROFILES
    generic = len(BAR_SIZE_CONFIGS)  # 7
    setup_long = sum(len(v) for k, v in SETUP_TRAINING_PROFILES.items() if not k.startswith("SHORT_"))  # 17
    setup_short = sum(len(v) for k, v in SETUP_TRAINING_PROFILES.items() if k.startswith("SHORT_"))  # 17
    volatility = len(BAR_SIZE_CONFIGS)  # 7
    exit_timing = len(ALL_SETUP_TYPES)  # 10
    sector_relative = 3  # daily, hourly, 5min
    gap_fill = 3  # 5min, 1min, 15min
    risk_of_ruin = 6  # 1min through daily
    regime_conditional = generic * len(["bull_trend", "bear_trend", "range_bound", "high_vol"])  # 7 * 4 = 28
    ensemble = len(ALL_SETUP_TYPES)  # 10
    return (generic + setup_long + setup_short + volatility + exit_timing +
            sector_relative + gap_fill + risk_of_ruin + regime_conditional + ensemble)


async def run_training_pipeline(
    db,
    phases: List[str] = None,
    bar_sizes: List[str] = None,
    max_symbols_override: int = None,
) -> Dict[str, Any]:
    """
    Run the full training pipeline.

    Args:
        db: MongoDB database instance
        phases: Which phases to run. Default: all.
            Options: "generic", "setup", "volatility", "regime", "exit", "ensemble"
        bar_sizes: Which bar sizes to train. Default: all.
        max_symbols_override: Override max symbols per bar_size.

    Returns:
        Dict with training results summary.
    """
    if phases is None:
        phases = ["generic", "setup", "short", "volatility", "exit", "sector", "gap_fill", "risk", "regime", "ensemble", "cnn", "validate"]
        # Note: "regime" and "ensemble" depend on Phase 1-7 models being trained first
        # "validate" runs 5-Phase Auto-Validation on setup_specific + ensemble models

    if bar_sizes is None:
        bar_sizes = list(BAR_SIZE_CONFIGS.keys())

    status = TrainingPipelineStatus(db)
    total = count_total_models()

    status.update(
        phase="starting",
        models_total=total,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "phases_requested": phases,
        "models_trained": [],
        "models_failed": [],
        "total_samples": 0,
    }

    try:
        # ── Phase 1: Generic Directional Models ──
        if "generic" in phases:
            status.update(phase="generic_directional")
            logger.info("=== Phase 1: Training Generic Directional Models ===")
            for bs in bar_sizes:
                config = BAR_SIZE_CONFIGS.get(bs)
                if not config:
                    continue
                model_name = f"direction_predictor_{bs.replace(' ', '_')}"
                status.update(current_model=model_name)
                try:
                    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
                    from services.ai_modules.timeseries_features import get_feature_engineer

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=config["forecast_horizon"])
                    model.set_db(db)

                    max_sym = max_symbols_override or config["max_symbols"]
                    symbols = await get_available_symbols(db, bs, config["min_bars_per_symbol"])
                    symbols = symbols[:max_sym]

                    if not symbols:
                        logger.warning(f"No symbols available for {bs}")
                        continue

                    bars_by_symbol = {}
                    for sym in symbols:
                        bars = await load_symbol_bars(db, sym, bs)
                        if len(bars) >= config["min_bars_per_symbol"]:
                            bars_by_symbol[sym] = bars

                    if len(bars_by_symbol) < 5:
                        logger.warning(f"Too few symbols with data for {bs}: {len(bars_by_symbol)}")
                        continue

                    logger.info(f"Training {model_name} on {len(bars_by_symbol)} symbols")
                    metrics = await _run_in_thread(model.train, bars_by_symbol)

                    if metrics and metrics.accuracy > 0:
                        results["models_trained"].append({
                            "name": model_name,
                            "accuracy": metrics.accuracy,
                            "samples": metrics.training_samples,
                        })
                        results["total_samples"] += metrics.training_samples
                        status.add_completed(model_name, metrics.accuracy)
                    else:
                        results["models_failed"].append({"name": model_name, "reason": "Low accuracy or no metrics"})

                except Exception as e:
                    logger.error(f"Failed to train {model_name}: {e}")
                    results["models_failed"].append({"name": model_name, "reason": str(e)})
                    status.add_error(model_name, str(e))

        # ── Phase 2: Setup-Specific Models (Long) ──
        if "setup" in phases:
            status.update(phase="setup_specific")
            logger.info("=== Phase 2: Training Setup-Specific Models (Long) ===")
            from services.ai_modules.setup_features import get_setup_features, get_setup_feature_names
            from services.ai_modules.setup_training_config import get_setup_profiles, get_model_name
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            for setup_type in ALL_SETUP_TYPES:
                profiles = get_setup_profiles(setup_type)
                for profile in profiles:
                    bs = profile["bar_size"]
                    fh = profile["forecast_horizon"]
                    noise_thr = profile.get("noise_threshold", 0.003)
                    num_boost = profile.get("num_boost_round", 150)
                    model_name = get_model_name(setup_type, bs)
                    status.update(current_model=model_name)

                    try:
                        bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                        max_sym = max_symbols_override or bs_config.get("max_symbols", 2500)
                        symbols = await get_available_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                        symbols = symbols[:max_sym]

                        if not symbols:
                            logger.warning(f"No symbols available for {model_name}")
                            continue

                        # Get setup-specific feature names
                        setup_feat_names = get_setup_feature_names(setup_type)
                        combined_names = base_names + [f"setup_{n}" for n in setup_feat_names]

                        all_X = []
                        all_y = []

                        for sym in symbols:
                            bars = await load_symbol_bars(db, sym, bs)
                            if len(bars) < 70 + fh:
                                continue

                            closes = np.array([b["close"] for b in bars], dtype=float)
                            highs = np.array([b["high"] for b in bars], dtype=float)
                            lows = np.array([b["low"] for b in bars], dtype=float)
                            volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)
                            opens = np.array([b.get("open", 0) for b in bars], dtype=float)

                            for i in range(50, len(bars) - fh):
                                # Base features
                                window = bars[i - 49: i + 1][::-1]
                                fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                                if fs is None:
                                    continue
                                base_vec = [fs.features.get(f, 0.0) for f in base_names]

                                # Setup-specific features
                                o_window = opens[max(0, i - 49): i + 1][::-1]
                                h_window = highs[max(0, i - 49): i + 1][::-1]
                                l_window = lows[max(0, i - 49): i + 1][::-1]
                                c_window = closes[max(0, i - 49): i + 1][::-1]
                                v_window = volumes[max(0, i - 49): i + 1][::-1]

                                setup_feats = get_setup_features(setup_type, o_window, h_window, l_window, c_window, v_window)
                                setup_vec = [setup_feats.get(f, 0.0) for f in setup_feat_names]

                                # Target: future return over forecast horizon (forward-looking)
                                future_return = (closes[i + fh] - closes[i]) / closes[i] if closes[i] > 0 else 0

                                if abs(future_return) < noise_thr:
                                    target = 1  # FLAT
                                elif future_return > 0:
                                    target = 2  # UP
                                else:
                                    target = 0  # DOWN

                                all_X.append(base_vec + setup_vec)
                                all_y.append(target)

                        if len(all_X) < MIN_TRAINING_SAMPLES:
                            logger.warning(f"Insufficient training data for {model_name}: {len(all_X)}")
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        X = np.array(all_X)
                        y = np.array(all_y)
                        logger.info(
                            f"Training {model_name}: {len(X)} samples, {len(combined_names)} features, "
                            f"UP={np.sum(y==2)}, FLAT={np.sum(y==1)}, DOWN={np.sum(y==0)}"
                        )

                        model = TimeSeriesGBM(model_name=model_name, forecast_horizon=fh)
                        model.set_db(db)
                        metrics = await _run_in_thread(
                            model.train_from_features,
                            X, y, combined_names,
                            num_boost_round=num_boost,
                            early_stopping_rounds=15,
                            num_classes=3,
                        )

                        if metrics and metrics.accuracy > 0:
                            results["models_trained"].append({
                                "name": model_name,
                                "accuracy": metrics.accuracy,
                                "samples": metrics.training_samples,
                            })
                            results["total_samples"] += metrics.training_samples
                            status.add_completed(model_name, metrics.accuracy)
                        else:
                            results["models_failed"].append({"name": model_name, "reason": "Low accuracy or no metrics"})

                    except Exception as e:
                        logger.error(f"Failed to train {model_name}: {e}")
                        results["models_failed"].append({"name": model_name, "reason": str(e)})
                        status.add_error(model_name, str(e))

        # ── Phase 2.5: Short Setup-Specific Models ──
        if "short" in phases:
            status.update(phase="short_setup_specific")
            logger.info("=== Phase 2.5: Training SHORT Setup-Specific Models ===")
            from services.ai_modules.short_setup_features import get_short_setup_features, get_short_setup_feature_names
            from services.ai_modules.setup_training_config import get_setup_profiles, get_model_name
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from services.ai_modules.advanced_targets import compute_advanced_target

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            for setup_type in ALL_SHORT_SETUP_TYPES:
                profiles = get_setup_profiles(setup_type)
                for profile in profiles:
                    bs = profile["bar_size"]
                    fh = profile["forecast_horizon"]
                    noise_thr = profile.get("noise_threshold", 0.003)
                    num_boost = profile.get("num_boost_round", 150)
                    model_name = get_model_name(setup_type, bs)
                    max_sym = profile.get("max_symbols", 2500)
                    max_bars = profile.get("max_bars_per_symbol", 5000)
                    status.update(current_model=model_name)

                    try:
                        symbols = await get_available_symbols(db, bs, 100)
                        symbols = symbols[:max_sym]

                        if not symbols:
                            logger.warning(f"No symbols available for {model_name}")
                            continue

                        # Get short-specific feature names
                        short_feat_names = get_short_setup_feature_names(setup_type)
                        combined_names = base_names + [f"short_{n}" for n in short_feat_names]

                        all_X = []
                        all_y = []

                        for sym in symbols:
                            bars = await load_symbol_bars(db, sym, bs)
                            if len(bars) < 70 + fh:
                                continue
                            bars = bars[:max_bars]

                            closes = np.array([b["close"] for b in bars], dtype=float)
                            highs = np.array([b["high"] for b in bars], dtype=float)
                            lows = np.array([b["low"] for b in bars], dtype=float)
                            volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)
                            opens = np.array([b.get("open", 0) for b in bars], dtype=float)

                            for i in range(50, len(bars) - fh):
                                # Base features
                                window = bars[i - 49: i + 1][::-1]
                                fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                                if fs is None:
                                    continue
                                base_vec = [fs.features.get(f, 0.0) for f in base_names]

                                # Short-specific features
                                c_window = closes[max(0, i - 49): i + 1][::-1]
                                h_window = highs[max(0, i - 49): i + 1][::-1]
                                l_window = lows[max(0, i - 49): i + 1][::-1]
                                v_window = volumes[max(0, i - 49): i + 1][::-1]
                                o_window = opens[max(0, i - 49): i + 1][::-1]

                                short_feats = get_short_setup_features(setup_type, o_window, h_window, l_window, c_window, v_window)
                                short_vec = [short_feats.get(f, 0.0) for f in short_feat_names]

                                # Target: For SHORT models, "positive outcome" = price goes DOWN
                                # Use inverted return: positive return = price dropped
                                future_return = (closes[i + fh] - closes[i]) / closes[i] if closes[i] > 0 else 0
                                # Invert: if future_return is negative (price went down), that's good for shorts
                                inverted_return = -future_return

                                if abs(inverted_return) < noise_thr:
                                    target = 1  # FLAT
                                elif inverted_return > 0:
                                    target = 2  # DOWN (good for short)
                                else:
                                    target = 0  # UP (bad for short)

                                all_X.append(base_vec + short_vec)
                                all_y.append(target)

                        if len(all_X) < MIN_TRAINING_SAMPLES:
                            logger.warning(f"Insufficient short training data for {model_name}: {len(all_X)}")
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        X = np.array(all_X)
                        y = np.array(all_y)
                        logger.info(
                            f"Training {model_name}: {len(X)} samples, {len(combined_names)} features, "
                            f"DOWN(good)={np.sum(y==2)}, FLAT={np.sum(y==1)}, UP(bad)={np.sum(y==0)}"
                        )

                        model = TimeSeriesGBM(model_name=model_name, forecast_horizon=fh)
                        model.set_db(db)
                        metrics = await _run_in_thread(
                            model.train_from_features,
                            X, y, combined_names,
                            num_boost_round=num_boost,
                            early_stopping_rounds=15,
                            num_classes=3,
                        )

                        if metrics and metrics.accuracy > 0:
                            results["models_trained"].append({
                                "name": model_name,
                                "accuracy": metrics.accuracy,
                                "samples": metrics.training_samples,
                                "direction": "short",
                            })
                            results["total_samples"] += metrics.training_samples
                            status.add_completed(model_name, metrics.accuracy)
                        else:
                            results["models_failed"].append({"name": model_name, "reason": "Low accuracy or no metrics"})

                    except Exception as e:
                        logger.error(f"Failed to train {model_name}: {e}")
                        results["models_failed"].append({"name": model_name, "reason": str(e)})
                        status.add_error(model_name, str(e))

        # ── Phase 3: Volatility Prediction Models ──
        if "volatility" in phases:
            status.update(phase="volatility_prediction")
            logger.info("=== Phase 3: Training Volatility Prediction Models ===")
            from services.ai_modules.volatility_model import (
                VOL_MODEL_CONFIGS, VOL_FEATURE_NAMES,
                compute_vol_specific_features, compute_vol_target,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from services.ai_modules.regime_features import (
                RegimeFeatureProvider, REGIME_FEATURE_NAMES,
            )

            regime_provider = RegimeFeatureProvider(db)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(TRAINING_POOL, regime_provider.preload_index_daily)

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            for bs in bar_sizes:
                vol_config = VOL_MODEL_CONFIGS.get(bs)
                if not vol_config:
                    continue

                model_name = vol_config["model_name"]
                fh = vol_config["forecast_horizon"]
                status.update(current_model=model_name)

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    max_sym = max_symbols_override or bs_config.get("max_symbols", 500)
                    symbols = await get_available_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    symbols = symbols[:max_sym]

                    if not symbols:
                        continue

                    combined_names = base_names + [f"vol_{n}" for n in VOL_FEATURE_NAMES] + REGIME_FEATURE_NAMES
                    all_X = []
                    all_y = []

                    for sym in symbols:
                        bars = await load_symbol_bars(db, sym, bs)
                        if len(bars) < 70 + fh:
                            continue

                        closes = np.array([b["close"] for b in bars], dtype=float)
                        highs = np.array([b["high"] for b in bars], dtype=float)
                        lows = np.array([b["low"] for b in bars], dtype=float)
                        volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)
                        opens = np.array([b.get("open", 0) for b in bars], dtype=float)

                        for i in range(50, len(bars) - fh):
                            # Base features
                            window = bars[i - 49: i + 1][::-1]
                            fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                            if fs is None:
                                continue
                            base_vec = [fs.features.get(f, 0.0) for f in base_names]

                            # Vol-specific features
                            c_window = closes[i - 49: i + 1][::-1]
                            h_window = highs[i - 49: i + 1][::-1]
                            l_window = lows[i - 49: i + 1][::-1]
                            v_window = volumes[i - 49: i + 1][::-1]
                            o_window = opens[i - 49: i + 1][::-1]
                            vol_feats = compute_vol_specific_features(c_window, h_window, l_window, o_window, v_window)
                            vol_vec = [vol_feats.get(f, 0.0) for f in VOL_FEATURE_NAMES]

                            # Regime features
                            bar_date = str(bars[i].get("date", ""))
                            regime_feats = regime_provider.get_regime_features_for_date(bar_date)
                            regime_vec = [regime_feats.get(f, 0.0) for f in REGIME_FEATURE_NAMES]

                            # Target
                            target = compute_vol_target(closes, fh, i)
                            if target is None:
                                continue

                            all_X.append(base_vec + vol_vec + regime_vec)
                            all_y.append(target)

                    if len(all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient vol training data for {bs}: {len(all_X)}")
                        continue

                    X = np.array(all_X)
                    y = np.array(all_y)
                    logger.info(f"Training {model_name}: {len(X)} samples, {len(combined_names)} features")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=fh)
                    model.set_db(db)
                    metrics = await _run_in_thread(
                        model.train_from_features,
                        X, y, combined_names,
                        num_boost_round=150,
                        early_stopping_rounds=15,
                    )

                    if metrics and metrics.accuracy > 0:
                        results["models_trained"].append({
                            "name": model_name,
                            "accuracy": metrics.accuracy,
                            "samples": metrics.training_samples,
                        })
                        results["total_samples"] += metrics.training_samples
                        status.add_completed(model_name, metrics.accuracy)

                except Exception as e:
                    logger.error(f"Failed to train {model_name}: {e}")
                    results["models_failed"].append({"name": model_name, "reason": str(e)})
                    status.add_error(model_name, str(e))
        if "exit" in phases:
            status.update(phase="exit_timing")
            logger.info("=== Phase 4: Training Exit Timing Models ===")
            from services.ai_modules.exit_timing_model import (
                EXIT_MODEL_CONFIGS, EXIT_FEATURE_NAMES,
                compute_exit_features, compute_exit_target,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            for setup_type, exit_config in EXIT_MODEL_CONFIGS.items():
                model_name = exit_config["model_name"]
                max_horizon = exit_config["max_horizon"]
                status.update(current_model=model_name)

                try:
                    # Exit timing uses daily bars by default (setup-level decision)
                    bs = "1 day"
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    symbols = await get_available_symbols(db, bs, 100)
                    symbols = symbols[:2000]

                    if not symbols:
                        continue

                    combined_names = base_names + [f"exit_{n}" for n in EXIT_FEATURE_NAMES]
                    all_X = []
                    all_y = []

                    for sym in symbols:
                        bars = await load_symbol_bars(db, sym, bs)
                        if len(bars) < 70 + max_horizon:
                            continue

                        closes = np.array([b["close"] for b in bars], dtype=float)
                        highs = np.array([b["high"] for b in bars], dtype=float)
                        lows = np.array([b["low"] for b in bars], dtype=float)
                        volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)

                        for i in range(50, len(bars) - max_horizon):
                            # Base features
                            window = bars[i - 49: i + 1][::-1]
                            fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                            if fs is None:
                                continue
                            base_vec = [fs.features.get(f, 0.0) for f in base_names]

                            # Exit-specific features
                            c_window = closes[i - 49: i + 1][::-1]
                            h_window = highs[i - 49: i + 1][::-1]
                            l_window = lows[i - 49: i + 1][::-1]
                            v_window = volumes[i - 49: i + 1][::-1]

                            # Determine likely direction from recent momentum
                            direction = "up" if closes[i] > closes[max(0, i - 3)] else "down"

                            exit_feats = compute_exit_features(c_window, h_window, l_window, v_window, direction)
                            exit_vec = [exit_feats.get(f, 0.0) for f in EXIT_FEATURE_NAMES]

                            # Target: bars to MFE
                            target = compute_exit_target(closes, highs, lows, i, max_horizon, direction)
                            if target is None:
                                continue

                            all_X.append(base_vec + exit_vec)
                            all_y.append(target)

                    if len(all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient exit training data for {setup_type}: {len(all_X)}")
                        continue

                    X = np.array(all_X)
                    y = np.array(all_y, dtype=float)

                    # Bucket into classes for classification (easier than regression for LightGBM)
                    # Classes: QUICK (1-5 bars), MEDIUM (6-15 bars), EXTENDED (16+ bars)
                    y_classes = np.zeros_like(y, dtype=int)
                    y_classes[y <= 5] = 0  # QUICK exit
                    y_classes[(y > 5) & (y <= 15)] = 1  # MEDIUM hold
                    y_classes[y > 15] = 2  # EXTENDED hold

                    logger.info(
                        f"Training {model_name}: {len(X)} samples, "
                        f"Quick={np.sum(y_classes==0)}, Med={np.sum(y_classes==1)}, Ext={np.sum(y_classes==2)}"
                    )

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=max_horizon)
                    model.set_db(db)
                    metrics = await _run_in_thread(
                        model.train_from_features,
                        X, y_classes, combined_names,
                        num_boost_round=150,
                        early_stopping_rounds=15,
                        num_classes=3,
                    )

                    if metrics and metrics.accuracy > 0:
                        results["models_trained"].append({
                            "name": model_name,
                            "accuracy": metrics.accuracy,
                            "samples": metrics.training_samples,
                        })
                        results["total_samples"] += metrics.training_samples
                        status.add_completed(model_name, metrics.accuracy)

                except Exception as e:
                    logger.error(f"Failed to train {model_name}: {e}")
                    results["models_failed"].append({"name": model_name, "reason": str(e)})
                    status.add_error(model_name, str(e))

        # ── Phase 5: Sector-Relative Models ──
        if "sector" in phases:
            status.update(phase="sector_relative")
            logger.info("=== Phase 5: Training Sector-Relative Models ===")
            from services.ai_modules.sector_relative_model import (
                SECTOR_MODEL_CONFIGS, SECTOR_REL_FEATURE_NAMES,
                compute_sector_relative_features, compute_sector_relative_target,
                SectorMapper,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()
            sector_mapper = SectorMapper(db)

            for bs, sec_config in SECTOR_MODEL_CONFIGS.items():
                model_name = sec_config["model_name"]
                fh = sec_config["forecast_horizon"]
                status.update(current_model=model_name)

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    symbols = await get_available_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    symbols = symbols[:1000]

                    # Preload sector ETF bars
                    sector_etf_bars = {}
                    for etf in sector_mapper.get_all_sector_etfs():
                        etf_bars = await load_symbol_bars(db, etf, bs)
                        if len(etf_bars) >= 50:
                            sector_etf_bars[etf] = {
                                "closes": np.array([b["close"] for b in etf_bars], dtype=float),
                                "volumes": np.array([b.get("volume", 0) for b in etf_bars], dtype=float),
                            }

                    combined_names = base_names + [f"secrel_{n}" for n in SECTOR_REL_FEATURE_NAMES]
                    all_X = []
                    all_y = []

                    for sym in symbols:
                        sector_etf = sector_mapper.get_sector_etf(sym)
                        if sector_etf is None or sector_etf not in sector_etf_bars:
                            continue

                        bars = await load_symbol_bars(db, sym, bs)
                        if len(bars) < 70 + fh:
                            continue

                        stock_closes = np.array([b["close"] for b in bars], dtype=float)
                        stock_volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)
                        sec_data = sector_etf_bars[sector_etf]
                        sec_closes = sec_data["closes"]
                        sec_volumes = sec_data["volumes"]

                        min_len = min(len(stock_closes), len(sec_closes))
                        if min_len < 70 + fh:
                            continue

                        for i in range(50, min_len - fh):
                            # Base features
                            window = bars[i - 49: i + 1][::-1]
                            fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                            if fs is None:
                                continue
                            base_vec = [fs.features.get(f, 0.0) for f in base_names]

                            # Sector-relative features
                            sc = stock_closes[max(0, i - 24): i + 1][::-1]
                            sv = stock_volumes[max(0, i - 24): i + 1][::-1]
                            ec = sec_closes[max(0, i - 24): i + 1][::-1]
                            ev = sec_volumes[max(0, i - 24): i + 1][::-1]

                            sec_feats = compute_sector_relative_features(sc, sv, ec, ev)
                            sec_vec = [sec_feats.get(f, 0.0) for f in SECTOR_REL_FEATURE_NAMES]

                            target = compute_sector_relative_target(stock_closes, sec_closes, i, fh)
                            if target is None:
                                continue

                            all_X.append(base_vec + sec_vec)
                            all_y.append(target)

                    if len(all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient sector-relative data for {bs}: {len(all_X)}")
                        continue

                    X = np.array(all_X)
                    y = np.array(all_y)
                    logger.info(f"Training {model_name}: {len(X)} samples")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=fh)
                    model.set_db(db)
                    metrics = await _run_in_thread(model.train_from_features, X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

                    if metrics and metrics.accuracy > 0:
                        results["models_trained"].append({"name": model_name, "accuracy": metrics.accuracy, "samples": metrics.training_samples})
                        results["total_samples"] += metrics.training_samples
                        status.add_completed(model_name, metrics.accuracy)

                except Exception as e:
                    logger.error(f"Failed to train {model_name}: {e}")
                    results["models_failed"].append({"name": model_name, "reason": str(e)})
                    status.add_error(model_name, str(e))

        # ── Phase 6: Risk-of-Ruin Models ──
        if "risk" in phases:
            status.update(phase="risk_of_ruin")
            logger.info("=== Phase 6: Training Risk-of-Ruin Models ===")
            from services.ai_modules.risk_of_ruin_model import (
                RISK_MODEL_CONFIGS, RISK_FEATURE_NAMES,
                compute_risk_features, compute_risk_target,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            for bs in bar_sizes:
                risk_config = RISK_MODEL_CONFIGS.get(bs)
                if not risk_config:
                    continue

                model_name = risk_config["model_name"]
                max_bars = risk_config["max_bars"]
                status.update(current_model=model_name)

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    symbols = await get_available_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    symbols = symbols[:1000]

                    combined_names = base_names + [f"risk_{n}" for n in RISK_FEATURE_NAMES]
                    all_X = []
                    all_y = []

                    for sym in symbols:
                        bars = await load_symbol_bars(db, sym, bs)
                        if len(bars) < 70 + max_bars:
                            continue

                        closes = np.array([b["close"] for b in bars], dtype=float)
                        highs = np.array([b["high"] for b in bars], dtype=float)
                        lows = np.array([b["low"] for b in bars], dtype=float)
                        volumes = np.array([b.get("volume", 0) for b in bars], dtype=float)

                        for i in range(50, len(bars) - max_bars):
                            window = bars[i - 49: i + 1][::-1]
                            fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                            if fs is None:
                                continue
                            base_vec = [fs.features.get(f, 0.0) for f in base_names]

                            c_window = closes[i - 24: i + 1][::-1]
                            h_window = highs[i - 24: i + 1][::-1]
                            l_window = lows[i - 24: i + 1][::-1]
                            v_window = volumes[i - 24: i + 1][::-1]

                            direction = "up" if closes[i] > closes[max(0, i - 3)] else "down"
                            risk_feats = compute_risk_features(c_window, h_window, l_window, v_window, direction)
                            risk_vec = [risk_feats.get(f, 0.0) for f in RISK_FEATURE_NAMES]

                            # Compute ATR for stop distance
                            atr_vals = []
                            for j in range(max(0, i - 10), i):
                                tr = max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]) if j > 0 else 0, abs(lows[j] - closes[j - 1]) if j > 0 else 0)
                                atr_vals.append(tr)
                            atr = np.mean(atr_vals) if atr_vals else 0.01

                            target = compute_risk_target(closes, highs, lows, i, atr, direction, max_bars=max_bars)
                            if target is None:
                                continue

                            all_X.append(base_vec + risk_vec)
                            all_y.append(target)

                    if len(all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient risk data for {bs}: {len(all_X)}")
                        continue

                    X = np.array(all_X)
                    y = np.array(all_y)
                    logger.info(f"Training {model_name}: {len(X)} samples, stop_hit={np.sum(y==1)} ({np.mean(y)*100:.1f}%)")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=max_bars)
                    model.set_db(db)
                    metrics = await _run_in_thread(model.train_from_features, X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

                    if metrics and metrics.accuracy > 0:
                        results["models_trained"].append({"name": model_name, "accuracy": metrics.accuracy, "samples": metrics.training_samples})
                        results["total_samples"] += metrics.training_samples
                        status.add_completed(model_name, metrics.accuracy)

                except Exception as e:
                    logger.error(f"Failed to train {model_name}: {e}")
                    results["models_failed"].append({"name": model_name, "reason": str(e)})
                    status.add_error(model_name, str(e))

        # ── Phase 7: Regime-Conditional (depends on Phase 1-6) ──
        if "regime" in phases:
            status.update(phase="regime_conditional")
            logger.info("=== Phase 7: Training Regime-Conditional Models ===")
            from services.ai_modules.regime_conditional_model import (
                ALL_REGIMES, classify_regime_for_date, get_regime_model_name,
                MIN_REGIME_SAMPLES,
            )
            from services.ai_modules.regime_features import RegimeFeatureProvider
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            # Preload SPY daily data for regime classification
            regime_provider = RegimeFeatureProvider(db)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(TRAINING_POOL, regime_provider.preload_index_daily)
            spy_data = regime_provider._data.get("spy", {})

            if not spy_data or spy_data.get("closes") is None or len(spy_data.get("closes", [])) < 30:
                logger.warning("Insufficient SPY data for regime classification — skipping Phase 7")
            else:
                # Train regime-conditional variants of Generic Directional models
                for bs in bar_sizes:
                    config = BAR_SIZE_CONFIGS.get(bs)
                    if not config:
                        continue

                    base_model_name = f"direction_predictor_{bs.replace(' ', '_')}"
                    fh = config["forecast_horizon"]

                    try:
                        max_sym = max_symbols_override or config["max_symbols"]
                        symbols = await get_available_symbols(db, bs, config["min_bars_per_symbol"])
                        symbols = symbols[:max_sym]

                        if not symbols:
                            continue

                        # Collect all samples and classify by regime
                        regime_samples = {r: {"X": [], "y": []} for r in ALL_REGIMES}

                        for sym in symbols:
                            bars = await load_symbol_bars(db, sym, bs)
                            if len(bars) < 70 + fh:
                                continue

                            closes = np.array([b["close"] for b in bars], dtype=float)

                            for i in range(50, len(bars) - fh):
                                window = bars[i - 49: i + 1][::-1]
                                fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                                if fs is None:
                                    continue
                                base_vec = [fs.features.get(f, 0.0) for f in base_names]

                                # Classify regime at this date
                                bar_date = str(bars[i].get("date", ""))
                                regime = classify_regime_for_date(spy_data, bar_date)

                                # Target: future return (binary UP/DOWN)
                                future_return = (closes[i + fh] - closes[i]) / closes[i] if closes[i] > 0 else 0
                                target = 1 if future_return > 0 else 0

                                regime_samples[regime]["X"].append(base_vec)
                                regime_samples[regime]["y"].append(target)

                        # Train one model per regime
                        for regime in ALL_REGIMES:
                            X_list = regime_samples[regime]["X"]
                            y_list = regime_samples[regime]["y"]

                            if len(X_list) < MIN_REGIME_SAMPLES:
                                logger.info(
                                    f"Skipping {base_model_name}_{regime}: only {len(X_list)} samples "
                                    f"(need {MIN_REGIME_SAMPLES})"
                                )
                                continue

                            X = np.array(X_list)
                            y = np.array(y_list)
                            regime_model_name = get_regime_model_name(base_model_name, regime)
                            status.update(current_model=regime_model_name)

                            logger.info(
                                f"Training {regime_model_name}: {len(X)} samples, "
                                f"UP={np.sum(y==1)}, DOWN={np.sum(y==0)}"
                            )

                            model = TimeSeriesGBM(model_name=regime_model_name, forecast_horizon=fh)
                            model.set_db(db)
                            metrics = await _run_in_thread(
                                model.train_from_features,
                                X, y, base_names,
                                num_boost_round=150,
                                early_stopping_rounds=15,
                                num_classes=2,
                            )

                            if metrics and metrics.accuracy > 0:
                                results["models_trained"].append({
                                    "name": regime_model_name,
                                    "accuracy": metrics.accuracy,
                                    "samples": metrics.training_samples,
                                    "regime": regime,
                                })
                                results["total_samples"] += metrics.training_samples
                                status.add_completed(regime_model_name, metrics.accuracy)
                            else:
                                results["models_failed"].append({
                                    "name": regime_model_name,
                                    "reason": "Low accuracy or no metrics",
                                })

                    except Exception as e:
                        logger.error(f"Regime training failed for {bs}: {e}")
                        results["models_failed"].append({"name": f"regime_{bs}", "reason": str(e)})
                        status.add_error(f"regime_{bs}", str(e))

        # ── Phase 8: Ensemble Meta-Learner (depends on Phase 1-7) ──
        if "ensemble" in phases:
            status.update(phase="ensemble_meta")
            logger.info("=== Phase 8: Training Ensemble Meta-Learner ===")
            from services.ai_modules.ensemble_model import (
                ENSEMBLE_MODEL_CONFIGS, ENSEMBLE_FEATURE_NAMES,
                extract_ensemble_features, STACKED_TIMEFRAMES,
            )
            from services.ai_modules.setup_training_config import (
                get_setup_profiles as _get_ens_profiles,
                get_model_name as _get_ens_model_name,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            # Load generic sub-models for each stacked timeframe
            sub_models = {}
            for tf in STACKED_TIMEFRAMES:
                tf_model_name = f"direction_predictor_{tf.replace(' ', '_')}"
                tf_fh = BAR_SIZE_CONFIGS.get(tf, {}).get("forecast_horizon", 5)
                m = TimeSeriesGBM(model_name=tf_model_name, forecast_horizon=tf_fh)
                m.set_db(db)
                if m._model is not None:
                    sub_models[tf] = m
                    logger.info(f"Loaded sub-model: {tf_model_name}")
                else:
                    logger.warning(f"Sub-model {tf_model_name} not trained — ensemble will use neutral predictions")

            if not sub_models:
                logger.warning("No sub-models available — skipping ensemble training")
            else:
                # Use daily bars as anchor timeframe for ensemble training
                anchor_bs = "1 day"
                anchor_fh = BAR_SIZE_CONFIGS.get(anchor_bs, {}).get("forecast_horizon", 5)

                symbols = await get_available_symbols(db, anchor_bs, 100)
                symbols = symbols[:3000]

                for setup_type, ens_config in ENSEMBLE_MODEL_CONFIGS.items():
                    model_name = ens_config["model_name"]
                    status.update(current_model=model_name)

                    try:
                        # Load setup-specific model if daily variant exists
                        setup_model = None
                        setup_profiles = _get_ens_profiles(setup_type)
                        for prof in setup_profiles:
                            if prof["bar_size"] == anchor_bs:
                                sname = _get_ens_model_name(setup_type, anchor_bs)
                                sm = TimeSeriesGBM(model_name=sname, forecast_horizon=prof["forecast_horizon"])
                                sm.set_db(db)
                                if sm._model is not None:
                                    setup_model = sm
                                    logger.info(f"Loaded setup sub-model: {sname}")
                                break

                        all_X = []
                        all_y = []

                        for sym in symbols:
                            bars = await load_symbol_bars(db, sym, anchor_bs)
                            if len(bars) < 70 + anchor_fh:
                                continue

                            closes = np.array([b["close"] for b in bars], dtype=float)

                            for i in range(50, len(bars) - anchor_fh):
                                window = bars[i - 49: i + 1][::-1]
                                fs = feature_engineer.extract_features(window, symbol=sym, include_target=False)
                                if fs is None:
                                    continue

                                # Get raw predictions from each sub-model (no DB logging)
                                predictions = {}
                                for tf, sm in sub_models.items():
                                    try:
                                        feat_vec = np.array([[
                                            fs.features.get(f, 0.0) for f in sm._feature_names
                                        ]])
                                        raw_pred = sm._model.predict(feat_vec)

                                        if hasattr(raw_pred, 'ndim') and raw_pred.ndim == 2:
                                            probs = raw_pred[0]
                                            prob_up = float(probs[2]) if len(probs) > 2 else float(probs[-1])
                                            prob_down = float(probs[0])
                                            conf = float(max(probs) - 1.0 / len(probs))
                                            direction = "up" if np.argmax(probs) == 2 else (
                                                "down" if np.argmax(probs) == 0 else "flat"
                                            )
                                        else:
                                            prob_up = float(raw_pred[0])
                                            prob_down = 1.0 - prob_up
                                            conf = abs(prob_up - 0.5) * 2
                                            direction = "up" if prob_up > 0.52 else (
                                                "down" if prob_down > 0.55 else "flat"
                                            )

                                        predictions[tf] = {
                                            "prob_up": prob_up,
                                            "prob_down": prob_down,
                                            "confidence": max(0, conf),
                                            "direction": direction,
                                        }
                                    except Exception:
                                        pass

                                # Get setup model prediction (raw, no DB logging)
                                setup_preds = []
                                if setup_model:
                                    try:
                                        feat_vec = np.array([[
                                            fs.features.get(f, 0.0)
                                            for f in setup_model._feature_names
                                        ]])
                                        raw_pred = setup_model._model.predict(feat_vec)

                                        if hasattr(raw_pred, 'ndim') and raw_pred.ndim == 2:
                                            probs = raw_pred[0]
                                            prob_up = float(probs[2]) if len(probs) > 2 else float(probs[-1])
                                            prob_down = float(probs[0])
                                            conf = float(max(probs) - 1.0 / len(probs))
                                            direction = "up" if np.argmax(probs) == 2 else (
                                                "down" if np.argmax(probs) == 0 else "flat"
                                            )
                                        else:
                                            prob_up = float(raw_pred[0])
                                            prob_down = 1.0 - prob_up
                                            conf = abs(prob_up - 0.5) * 2
                                            direction = "up" if prob_up > 0.52 else (
                                                "down" if prob_down > 0.55 else "flat"
                                            )

                                        setup_preds.append({
                                            "prob_up": prob_up,
                                            "prob_down": prob_down,
                                            "confidence": max(0, conf),
                                            "direction": direction,
                                        })
                                    except Exception:
                                        pass

                                # Extract ensemble features from stacked predictions
                                ens_feats = extract_ensemble_features(
                                    predictions, setup_preds or None
                                )
                                feat_vec = [ens_feats.get(f, 0.0) for f in ENSEMBLE_FEATURE_NAMES]

                                # Target: future return over daily forecast horizon
                                future_return = (
                                    (closes[i + anchor_fh] - closes[i]) / closes[i]
                                    if closes[i] > 0 else 0
                                )
                                if future_return > 0.003:
                                    target = 2  # UP
                                elif future_return < -0.003:
                                    target = 0  # DOWN
                                else:
                                    target = 1  # FLAT

                                all_X.append(feat_vec)
                                all_y.append(target)

                        if len(all_X) < MIN_TRAINING_SAMPLES:
                            logger.warning(f"Insufficient ensemble data for {model_name}: {len(all_X)}")
                            results["models_failed"].append({
                                "name": model_name, "reason": "Insufficient data",
                            })
                            continue

                        X = np.array(all_X)
                        y = np.array(all_y)
                        logger.info(
                            f"Training {model_name}: {len(X)} samples, "
                            f"UP={np.sum(y==2)}, FLAT={np.sum(y==1)}, DOWN={np.sum(y==0)}"
                        )

                        model = TimeSeriesGBM(model_name=model_name, forecast_horizon=anchor_fh)
                        model.set_db(db)
                        metrics = await _run_in_thread(
                            model.train_from_features,
                            X, y, ENSEMBLE_FEATURE_NAMES,
                            num_boost_round=120,
                            early_stopping_rounds=15,
                            num_classes=3,
                        )

                        if metrics and metrics.accuracy > 0:
                            results["models_trained"].append({
                                "name": model_name,
                                "accuracy": metrics.accuracy,
                                "samples": metrics.training_samples,
                                "type": "ensemble",
                            })
                            results["total_samples"] += metrics.training_samples
                            status.add_completed(model_name, metrics.accuracy)
                        else:
                            results["models_failed"].append({
                                "name": model_name,
                                "reason": "Low accuracy or no metrics",
                            })

                    except Exception as e:
                        logger.error(f"Ensemble training failed for {model_name}: {e}")
                        results["models_failed"].append({"name": model_name, "reason": str(e)})
                        status.add_error(model_name, str(e))

        # ── Phase 9: CNN Chart Pattern Training ──
        if "cnn" in phases:
            status.update(phase="cnn_patterns")
            logger.info("=== Phase 9: Training CNN Chart Pattern Models ===")
            try:
                from services.ai_modules.cnn_training_pipeline import run_cnn_training

                async def cnn_progress(pct, msg):
                    status.update(current_model=msg)

                cnn_result = await run_cnn_training(
                    db=db,
                    setup_type="ALL",
                    progress_callback=cnn_progress,
                )

                if cnn_result.get("success"):
                    cnn_trained = cnn_result.get("trained", 0)
                    cnn_skipped = cnn_result.get("skipped", 0)
                    logger.info(f"CNN training complete: {cnn_trained} trained, {cnn_skipped} skipped")
                    results["cnn_training"] = {
                        "trained": cnn_trained,
                        "skipped": cnn_skipped,
                        "elapsed": cnn_result.get("elapsed_seconds", 0),
                        "gpu_info": cnn_result.get("gpu_info", {}),
                    }
                    for model_name, model_result in cnn_result.get("models", {}).items():
                        if model_result.get("success"):
                            acc = model_result.get("metrics", {}).get("accuracy", 0)
                            results["models_trained"].append({"name": model_name, "accuracy": acc, "type": "cnn"})
                            status.add_completed(model_name, acc)
                        else:
                            results["models_failed"].append({"name": model_name, "reason": model_result.get("error", ""), "type": "cnn"})
                else:
                    logger.warning(f"CNN training failed: {cnn_result.get('error', 'Unknown')}")
                    results["cnn_training"] = {"error": cnn_result.get("error")}

            except Exception as e:
                logger.error(f"CNN phase failed: {e}", exc_info=True)
                results["cnn_training"] = {"error": str(e)}

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 10: Auto-Validation (5-Phase pipeline on Trade Signal Generators)
        # ══════════════════════════════════════════════════════════════════════
        if "validate" in phases and len(results["models_trained"]) > 0:
            phase_key = "auto_validation"
            status.start_phase(phase_key, 34)  # 17 long + 17 short setup types
            status.update(phase=phase_key, current_model="Initializing validation...")
            logger.info("Phase 10: Starting Auto-Validation of Trade Signal Generators")

            try:
                from services.ai_modules.post_training_validator import validate_trained_model, run_batch_validation
                from services.slow_learning.advanced_backtest_engine import get_advanced_backtest_engine

                backtest_engine = get_advanced_backtest_engine()

                # Get timeseries service for model rollback capability
                timeseries_service = None
                try:
                    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
                    timeseries_service = TimeSeriesGBM.get_instance() if hasattr(TimeSeriesGBM, 'get_instance') else None
                except Exception:
                    logger.warning("Could not get timeseries service for validation rollback — continuing without rollback support")

                # Determine which setup types were actually trained in this run
                trained_model_names = [m["name"] if isinstance(m, dict) else m for m in results["models_trained"]]
                trained_long_setups = [n.split("/")[0] for n in trained_model_names if "/" in n and not n.startswith("SHORT_") and n.split("/")[0] in ALL_SETUP_TYPES]
                trained_short_setups = [n.split("/")[0] for n in trained_model_names if "/" in n and n.startswith("SHORT_")]
                all_trained_setups = list(set(trained_long_setups + trained_short_setups))

                if not all_trained_setups:
                    # Fall back to all known setup types if we can't parse from results
                    all_trained_setups = ALL_SETUP_TYPES + ALL_SHORT_SETUP_TYPES

                validated_count = 0
                validation_results = []
                promoted_count = 0
                rejected_count = 0

                # Per-model validation (Phases 1-3: AI Comparison, Monte Carlo, Walk-Forward)
                for setup_type in all_trained_setups:
                    if status._status.get("phase") == "cancelled":
                        break

                    # Find the bar_size this model was trained on (default to "5 mins")
                    bar_size = "5 mins"
                    for m in results["models_trained"]:
                        m_name = m["name"] if isinstance(m, dict) else m
                        if m_name.startswith(f"{setup_type}/"):
                            bar_size = m_name.split("/")[1] if "/" in m_name else "5 mins"
                            break

                    status.update(current_model=f"Validating {setup_type}/{bar_size}")
                    logger.info(f"[VALIDATE] Phase 10: Validating {setup_type}/{bar_size}")

                    try:
                        training_result = {"metrics": {"accuracy": 0}}
                        # Find accuracy from training results
                        for m in results["models_trained"]:
                            m_name = m["name"] if isinstance(m, dict) else m
                            if m_name.startswith(f"{setup_type}/"):
                                if isinstance(m, dict):
                                    training_result["metrics"]["accuracy"] = m.get("accuracy", 0)
                                break

                        val_result = await validate_trained_model(
                            db=db,
                            timeseries_service=timeseries_service,
                            backtest_engine=backtest_engine,
                            setup_type=setup_type,
                            bar_size=bar_size,
                            training_result=training_result,
                        )
                        validation_results.append(val_result)
                        if val_result.get("status") == "promoted":
                            promoted_count += 1
                        else:
                            rejected_count += 1
                        validated_count += 1
                        status.model_done(phase_key, f"val_{setup_type}",
                                          accuracy=val_result.get("training_accuracy", 0),
                                          extra={"phases_passed": val_result.get("phases_passed", 0), "status": val_result.get("status", "unknown")})
                    except Exception as e:
                        logger.error(f"[VALIDATE] Failed to validate {setup_type}: {e}")
                        status.model_failed(phase_key, f"val_{setup_type}", str(e))
                        rejected_count += 1

                # Batch validation (Phases 4-5: Multi-Strategy + Market-Wide)
                if len(all_trained_setups) >= 2:
                    status.update(current_model="Batch validation (Multi-Strategy + Market-Wide)")
                    try:
                        # Only validate the base (non-SHORT) setup types for batch
                        base_setups = [s for s in all_trained_setups if not s.startswith("SHORT_")]
                        if len(base_setups) >= 2:
                            batch_result = await run_batch_validation(
                                db=db,
                                backtest_engine=backtest_engine,
                                trained_setup_types=base_setups[:10],  # Cap at 10 for performance
                            )
                            results["batch_validation"] = {
                                "multi_strategy": batch_result.get("multi_strategy"),
                                "market_wide_count": len(batch_result.get("market_wide", [])),
                                "duration_seconds": batch_result.get("total_duration_seconds", 0),
                            }
                    except Exception as e:
                        logger.error(f"[VALIDATE] Batch validation failed: {e}")
                        results["batch_validation"] = {"error": str(e)}

                status.end_phase(phase_key)
                results["validation_summary"] = {
                    "total_validated": validated_count,
                    "promoted": promoted_count,
                    "rejected": rejected_count,
                    "results": [{
                        "setup_type": r.get("setup_type"),
                        "status": r.get("status"),
                        "phases_passed": r.get("phases_passed", 0),
                    } for r in validation_results],
                }
                logger.info(
                    f"Phase 10 Auto-Validation complete: {validated_count} validated, "
                    f"{promoted_count} promoted, {rejected_count} rejected"
                )

            except ImportError as e:
                logger.error(f"Phase 10 skipped — missing dependencies: {e}")
                status.end_phase(phase_key)
                results["validation_summary"] = {"error": f"Dependencies missing: {e}"}
            except Exception as e:
                logger.error(f"Phase 10 Auto-Validation error: {e}", exc_info=True)
                status.end_phase(phase_key)
                results["validation_summary"] = {"error": str(e)}

        # ── Done ──
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        results["summary"] = {
            "models_trained": len(results["models_trained"]),
            "models_failed": len(results["models_failed"]),
            "total_samples": results["total_samples"],
        }
        status.update(phase="completed", current_model="")
        logger.info(
            f"Training pipeline complete: {len(results['models_trained'])} trained, "
            f"{len(results['models_failed'])} failed, {results['total_samples']:,} total samples"
        )

    except Exception as e:
        logger.error(f"Training pipeline error: {e}")
        results["error"] = str(e)
        status.update(phase="error", current_model=str(e))

    return results
