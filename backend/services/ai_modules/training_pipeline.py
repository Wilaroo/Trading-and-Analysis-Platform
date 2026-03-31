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
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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


class TrainingPipelineStatus:
    """Track and persist pipeline training progress."""

    def __init__(self, db=None):
        self._db = db
        self._status = {
            "phase": "idle",
            "current_model": "",
            "models_completed": 0,
            "models_total": 0,
            "current_phase_progress": 0.0,
            "started_at": None,
            "errors": [],
            "completed_models": [],
        }

    def update(self, **kwargs):
        self._status.update(kwargs)
        if self._db:
            try:
                self._db["training_pipeline_status"].update_one(
                    {"_id": "pipeline"},
                    {"$set": {**self._status, "updated_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True,
                )
            except Exception:
                pass

    def get_status(self) -> Dict:
        return dict(self._status)

    def add_completed(self, model_name: str, accuracy: float):
        self._status["completed_models"].append({
            "name": model_name,
            "accuracy": accuracy,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        self._status["models_completed"] = len(self._status["completed_models"])
        self.update()

    def add_error(self, model_name: str, error: str):
        self._status["errors"].append({
            "model": model_name,
            "error": error,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        self.update()


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
            None,
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
            None,
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
    setup_specific = 16  # Long setup profiles
    short_specific = sum(len(v) for k, v in SETUP_TRAINING_PROFILES.items() if k.startswith("SHORT_"))
    volatility = len(BAR_SIZE_CONFIGS)  # 7
    exit_timing = len(ALL_SETUP_TYPES)  # 10
    sector_relative = 3  # daily, hourly, 5min
    gap_fill = 3  # 5min, 1min, 15min
    risk_of_ruin = 6  # 1min through daily
    return generic + setup_specific + short_specific + volatility + exit_timing + sector_relative + gap_fill + risk_of_ruin


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
        phases = ["generic", "setup", "short", "volatility", "exit", "sector", "gap_fill", "risk", "cnn"]
        # Note: "regime" and "ensemble" depend on Phase 1-7 models being trained first

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

                    # Load bars and train
                    bars_by_symbol = {}
                    for sym in symbols:
                        bars = await load_symbol_bars(db, sym, bs)
                        if len(bars) >= config["min_bars_per_symbol"]:
                            bars_by_symbol[sym] = bars

                    if len(bars_by_symbol) < 5:
                        logger.warning(f"Too few symbols with data for {bs}: {len(bars_by_symbol)}")
                        continue

                    logger.info(f"Training {model_name} on {len(bars_by_symbol)} symbols")
                    metrics = model.train(bars_by_symbol)

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

        # ── Phase 2: Setup-Specific Models ──
        if "setup" in phases:
            status.update(phase="setup_specific")
            logger.info("=== Phase 2: Training Setup-Specific Models ===")
            # Delegate to existing timeseries_service setup training
            # This is already implemented in the service
            logger.info("Setup-specific training deferred to existing service (trigger via API)")

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
                                future_return = (closes[i] - closes[i - fh]) / closes[i] if closes[i] > 0 else 0
                                # Invert: if future_return is negative (price went down), that's good for shorts
                                inverted_return = -future_return

                                if abs(inverted_return) < noise_thr:
                                    target = 1  # FLAT
                                elif inverted_return > 0:
                                    target = 2  # DOWN (good for short) → maps to "up" in model terms
                                else:
                                    target = 0  # UP (bad for short) → maps to "down" in model terms

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
                        metrics = model.train_from_features(
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

            # Preload regime data
            regime_provider = RegimeFeatureProvider(db)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, regime_provider.preload_index_daily)

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
                    metrics = model.train_from_features(
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

        # ── Phase 4: Exit Timing Models ──
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
                    metrics = model.train_from_features(
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
                    metrics = model.train_from_features(X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

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
                    metrics = model.train_from_features(X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

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
            logger.info("Regime-conditional training will split existing training data by detected regime "
                        "and train regime-specific variants. This runs after all base models.")

        # ── Phase 8: Ensemble Meta-Learner (depends on Phase 1-7) ──
        if "ensemble" in phases:
            status.update(phase="ensemble_meta")
            logger.info("=== Phase 8: Training Ensemble Meta-Learner ===")
            logger.info("Ensemble training requires Phase 1-7 models to be trained first "
                        "(needs their predictions as input features).")

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
