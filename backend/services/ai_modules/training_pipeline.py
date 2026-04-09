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
import gc
import os
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
    "1 min":   {"forecast_horizon": 30, "min_bars_per_symbol": 200, "max_symbols": 2500, "max_bars": 50000},   # 50K ≈ 125 trading days
    "5 mins":  {"forecast_horizon": 12, "min_bars_per_symbol": 200, "max_symbols": 2500, "max_bars": 50000},   # 50K ≈ 640 trading days
    "15 mins": {"forecast_horizon": 8,  "min_bars_per_symbol": 150, "max_symbols": 2500, "max_bars": 50000},
    "30 mins": {"forecast_horizon": 6,  "min_bars_per_symbol": 150, "max_symbols": 2500, "max_bars": 50000},
    "1 hour":  {"forecast_horizon": 6,  "min_bars_per_symbol": 100, "max_symbols": 2500, "max_bars": 50000},
    "1 day":   {"forecast_horizon": 5,  "min_bars_per_symbol": 100, "max_symbols": 2500, "max_bars": 10000},   # 10K ≈ 40 years
    "1 week":  {"forecast_horizon": 4,  "min_bars_per_symbol": 50,  "max_symbols": 2500, "max_bars": 5000},
}

# How many symbols to load at once before extracting and discarding raw bars.
# Controls peak RAM: 25 symbols × ~15MB each = ~375MB of raw bar dicts at a time.
# Kept conservative to leave headroom on 16GB systems.
STREAM_BATCH_SIZE = 50

# Max symbols for setup-specific phases (2, 2.5, 4).
# These phases accumulate features for 10+ model types simultaneously,
# so memory = symbols × models × features. 750 symbols provides ample
# training data (~21M samples per model) while keeping peak RAM under 90GB.
SETUP_PHASE_MAX_SYMBOLS = 750

# Max parallel worker processes for feature extraction.
# Cap at 8 to limit memory overhead from forked processes (each worker copies parent memory).
# On DGX Spark (20+ cores), uncapped cpu_count()//2 causes 10+ workers × ~4GB each = swap pressure.
MAX_EXTRACT_WORKERS = min(8, max(1, os.cpu_count() // 2))


# ── Symbol Cache ──────────────────────────────────────────────
# Avoids re-running expensive $group aggregations on 177M rows
# for the same (bar_size, min_bars) combo across multiple phases.
_symbol_cache: Dict[str, List[str]] = {}


async def get_cached_symbols(db, bar_size: str, min_bars: int, max_symbols: int = 2500) -> List[str]:
    """get_available_symbols with per-bar-size caching."""
    key = f"{bar_size}|{min_bars}"
    if key not in _symbol_cache:
        _symbol_cache[key] = await get_available_symbols(db, bar_size, min_bars)
    return _symbol_cache[key][:max_symbols]


def clear_symbol_cache():
    """Clear at the start/end of a full pipeline run."""
    _symbol_cache.clear()


# ── NVMe Disk Cache ──────────────────────────────────────────
# Caches bar data and feature matrices on disk (NVMe) to avoid
# redundant MongoDB queries and CPU-heavy feature extraction
# across phases. Cleared at the start of each pipeline run.
import pickle as _pickle
import os as _os

CACHE_BASE_DIR = "/tmp/training_cache"
BAR_CACHE_DIR = f"{CACHE_BASE_DIR}/bars"
FEATURE_CACHE_DIR = f"{CACHE_BASE_DIR}/features"


def _sanitize_bar_size(bar_size: str) -> str:
    """Convert bar_size to a safe directory name."""
    return bar_size.replace(" ", "_")


def _init_disk_cache():
    """Create cache directories on NVMe."""
    for d in (BAR_CACHE_DIR, FEATURE_CACHE_DIR):
        _os.makedirs(d, exist_ok=True)


def _clear_disk_cache():
    """Wipe cache at start of a fresh pipeline run."""
    import shutil
    if _os.path.exists(CACHE_BASE_DIR):
        shutil.rmtree(CACHE_BASE_DIR, ignore_errors=True)
    _init_disk_cache()
    logger.info("[CACHE] Cleared NVMe disk cache")


def _bar_cache_path(symbol: str, bar_size: str) -> str:
    bs_dir = f"{BAR_CACHE_DIR}/{_sanitize_bar_size(bar_size)}"
    _os.makedirs(bs_dir, exist_ok=True)
    return f"{bs_dir}/{symbol}.pkl"


def _feature_cache_path(symbol: str, bar_size: str) -> str:
    bs_dir = f"{FEATURE_CACHE_DIR}/{_sanitize_bar_size(bar_size)}"
    _os.makedirs(bs_dir, exist_ok=True)
    return f"{bs_dir}/{symbol}.npy"


def _cache_bars_to_disk(symbol: str, bar_size: str, bars: List[Dict]):
    """Write bars to NVMe as pickle."""
    try:
        path = _bar_cache_path(symbol, bar_size)
        with open(path, "wb") as f:
            _pickle.dump(bars, f, protocol=_pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass


def _load_bars_from_disk(symbol: str, bar_size: str) -> Optional[List[Dict]]:
    """Load bars from NVMe cache. Returns None on miss."""
    path = _bar_cache_path(symbol, bar_size)
    if not _os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return _pickle.load(f)
    except Exception:
        return None


def _cache_features_to_disk(symbol: str, bar_size: str, features: np.ndarray):
    """Write feature matrix to NVMe as .npy."""
    try:
        path = _feature_cache_path(symbol, bar_size)
        np.save(path, features)
    except Exception:
        pass


def _load_features_from_disk(symbol: str, bar_size: str) -> Optional[np.ndarray]:
    """Load feature matrix from NVMe cache. Returns None on miss."""
    path = _feature_cache_path(symbol, bar_size)
    if not _os.path.exists(path):
        return None
    try:
        return np.load(path)
    except Exception:
        return None


def cached_extract_features_bulk(feature_engineer, bars, symbol: str, bar_size: str):
    """Extract features with NVMe disk caching."""
    cached = _load_features_from_disk(symbol, bar_size)
    if cached is not None:
        return cached
    result = feature_engineer.extract_features_bulk(bars)
    if result is not None:
        _cache_features_to_disk(symbol, bar_size, result)
    return result


def _check_resume_model(db, model_name: str, max_age_hours: float = 24.0) -> Optional[Dict]:
    """Check if model was recently trained and can be skipped.
    
    Returns dict with accuracy/samples if resumable, None otherwise.
    """
    try:
        doc = db["timeseries_models"].find_one(
            {"name": model_name},
            {"saved_at": 1, "metrics": 1, "_id": 0}
        )
        if doc and "saved_at" in doc:
            saved_at = datetime.fromisoformat(doc["saved_at"])
            age_hours = (datetime.now(timezone.utc) - saved_at).total_seconds() / 3600
            if age_hours < max_age_hours:
                metrics = doc.get("metrics", {})
                accuracy = metrics.get("accuracy", 0)
                samples = metrics.get("training_samples", 0)
                logger.info(
                    f"[RESUME] Skipping {model_name} — trained {age_hours:.1f}h ago "
                    f"(accuracy={accuracy:.4f}, samples={samples:,})"
                )
                return {"accuracy": accuracy, "samples": samples, "age_hours": age_hours}
    except Exception as e:
        logger.warning(f"[RESUME] Error checking model {model_name}: {e}")
    return None


# ── Multiprocessing Workers (must be at module scope for pickle) ────────

def _extract_setup_long_worker(args):
    """Phase 2 worker: extract base + setup features for one symbol across all setup types."""
    symbol, bars, setup_configs = args
    # setup_configs: list of (setup_type, forecast_horizon, noise_threshold)
    from services.ai_modules.timeseries_features import TimeSeriesFeatureEngineer
    from services.ai_modules.setup_features import get_setup_features, get_setup_feature_names

    try:
        fe = TimeSeriesFeatureEngineer(50)
        base_matrix = fe.extract_features_bulk(bars)
        if base_matrix is None:
            return None

        closes = np.array([b["close"] for b in bars], dtype=np.float32)
        highs = np.array([b["high"] for b in bars], dtype=np.float32)
        lows = np.array([b["low"] for b in bars], dtype=np.float32)
        volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
        opens = np.array([b.get("open", 0) for b in bars], dtype=np.float32)

        results = {}
        for setup_type, fh, noise_thr in setup_configs:
            feat_names = get_setup_feature_names(setup_type)
            n_setup = len(feat_names)
            n_base = base_matrix.shape[1]

            max_rows = len(bars) - 50 - fh
            if max_rows <= 0:
                continue

            X_buf = np.empty((max_rows, n_base + n_setup), dtype=np.float32)
            y_buf = np.empty(max_rows, dtype=np.float32)
            valid = 0

            for i in range(50, len(bars) - fh):
                row_idx = i - 49
                if row_idx >= len(base_matrix):
                    break

                o_win = opens[max(0, i - 49): i + 1][::-1]
                h_win = highs[max(0, i - 49): i + 1][::-1]
                l_win = lows[max(0, i - 49): i + 1][::-1]
                c_win = closes[max(0, i - 49): i + 1][::-1]
                v_win = volumes[max(0, i - 49): i + 1][::-1]

                sf = get_setup_features(setup_type, o_win, h_win, l_win, c_win, v_win)
                setup_vec = np.array([sf.get(f, 0.0) for f in feat_names], dtype=np.float32)

                X_buf[valid, :n_base] = base_matrix[row_idx]
                X_buf[valid, n_base:] = setup_vec

                fr = (closes[i + fh] - closes[i]) / closes[i] if closes[i] > 0 else 0
                if abs(fr) < noise_thr:
                    y_buf[valid] = 1
                elif fr > 0:
                    y_buf[valid] = 2
                else:
                    y_buf[valid] = 0
                valid += 1

            if valid > 0:
                results[(setup_type, fh)] = (X_buf[:valid].copy(), y_buf[:valid].copy())
        return results
    except Exception as e:
        logger.warning(f"Setup worker error for {symbol}: {e}")
        return None


def _extract_setup_short_worker(args):
    """Phase 2.5 worker: extract base + short-setup features for one symbol."""
    symbol, bars, setup_configs = args
    from services.ai_modules.timeseries_features import TimeSeriesFeatureEngineer
    from services.ai_modules.short_setup_features import get_short_setup_features, get_short_setup_feature_names

    try:
        fe = TimeSeriesFeatureEngineer(50)
        base_matrix = fe.extract_features_bulk(bars)
        if base_matrix is None:
            return None

        closes = np.array([b["close"] for b in bars], dtype=np.float32)
        highs = np.array([b["high"] for b in bars], dtype=np.float32)
        lows = np.array([b["low"] for b in bars], dtype=np.float32)
        volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
        opens = np.array([b.get("open", 0) for b in bars], dtype=np.float32)

        results = {}
        for setup_type, fh, noise_thr in setup_configs:
            feat_names = get_short_setup_feature_names(setup_type)
            n_setup = len(feat_names)
            n_base = base_matrix.shape[1]

            max_rows = len(bars) - 50 - fh
            if max_rows <= 0:
                continue

            X_buf = np.empty((max_rows, n_base + n_setup), dtype=np.float32)
            y_buf = np.empty(max_rows, dtype=np.float32)
            valid = 0

            for i in range(50, len(bars) - fh):
                row_idx = i - 49
                if row_idx >= len(base_matrix):
                    break

                c_win = closes[max(0, i - 49): i + 1][::-1]
                h_win = highs[max(0, i - 49): i + 1][::-1]
                l_win = lows[max(0, i - 49): i + 1][::-1]
                v_win = volumes[max(0, i - 49): i + 1][::-1]
                o_win = opens[max(0, i - 49): i + 1][::-1]

                sf = get_short_setup_features(setup_type, o_win, h_win, l_win, c_win, v_win)
                short_vec = np.array([sf.get(f, 0.0) for f in feat_names], dtype=np.float32)

                X_buf[valid, :n_base] = base_matrix[row_idx]
                X_buf[valid, n_base:] = short_vec

                fr = (closes[i + fh] - closes[i]) / closes[i] if closes[i] > 0 else 0
                inv_fr = -fr
                if abs(inv_fr) < noise_thr:
                    y_buf[valid] = 1
                elif inv_fr > 0:
                    y_buf[valid] = 2
                else:
                    y_buf[valid] = 0
                valid += 1

            if valid > 0:
                results[(setup_type, fh)] = (X_buf[:valid].copy(), y_buf[:valid].copy())
        return results
    except Exception as e:
        logger.warning(f"Short setup worker error for {symbol}: {e}")
        return None


def _extract_exit_worker(args):
    """Phase 4 worker: extract base + exit features for one symbol."""
    symbol, bars, exit_configs = args
    from services.ai_modules.timeseries_features import TimeSeriesFeatureEngineer
    from services.ai_modules.exit_features import compute_exit_features, compute_exit_target, EXIT_FEATURE_NAMES

    try:
        fe = TimeSeriesFeatureEngineer(50)
        base_matrix = fe.extract_features_bulk(bars)
        if base_matrix is None:
            return None

        closes = np.array([b["close"] for b in bars], dtype=np.float32)
        highs = np.array([b["high"] for b in bars], dtype=np.float32)
        lows = np.array([b["low"] for b in bars], dtype=np.float32)
        volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
        n_base = base_matrix.shape[1]
        n_exit = len(EXIT_FEATURE_NAMES)

        results = {}
        for setup_type, max_horizon in exit_configs:
            max_rows = len(bars) - 50 - max_horizon
            if max_rows <= 0:
                continue

            X_buf = np.empty((max_rows, n_base + n_exit), dtype=np.float32)
            y_buf = np.empty(max_rows, dtype=np.float32)
            valid = 0

            for i in range(50, len(bars) - max_horizon):
                row_idx = i - 49
                if row_idx >= len(base_matrix):
                    break

                c_win = closes[i - 49: i + 1][::-1]
                h_win = highs[i - 49: i + 1][::-1]
                l_win = lows[i - 49: i + 1][::-1]
                v_win = volumes[i - 49: i + 1][::-1]
                direction = "up" if closes[i] > closes[max(0, i - 3)] else "down"

                ef = compute_exit_features(c_win, h_win, l_win, v_win, direction)
                exit_vec = np.array([ef.get(f, 0.0) for f in EXIT_FEATURE_NAMES], dtype=np.float32)

                target = compute_exit_target(closes, highs, lows, i, max_horizon, direction)
                if target is None:
                    continue

                X_buf[valid, :n_base] = base_matrix[row_idx]
                X_buf[valid, n_base:] = exit_vec
                y_buf[valid] = target
                valid += 1

            if valid > 0:
                results[setup_type] = (X_buf[:valid].copy(), y_buf[:valid].copy())
        return results
    except Exception as e:
        logger.warning(f"Exit worker error for {symbol}: {e}")
        return None


def _extract_risk_worker(args):
    """Phase 6 worker: extract base + risk features for one symbol."""
    symbol, bars, risk_configs = args
    from services.ai_modules.timeseries_features import TimeSeriesFeatureEngineer
    from services.ai_modules.risk_features import compute_risk_features, compute_risk_target, RISK_FEATURE_NAMES

    try:
        fe = TimeSeriesFeatureEngineer(50)
        base_matrix = fe.extract_features_bulk(bars)
        if base_matrix is None:
            return None

        closes = np.array([b["close"] for b in bars], dtype=np.float32)
        highs = np.array([b["high"] for b in bars], dtype=np.float32)
        lows = np.array([b["low"] for b in bars], dtype=np.float32)
        volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
        n_base = base_matrix.shape[1]
        n_risk = len(RISK_FEATURE_NAMES)

        results = {}
        for bs_label, max_bars_horizon in risk_configs:
            max_rows = len(bars) - 50 - max_bars_horizon
            if max_rows <= 0:
                continue

            X_buf = np.empty((max_rows, n_base + n_risk), dtype=np.float32)
            y_buf = np.empty(max_rows, dtype=np.float32)
            valid = 0

            for i in range(50, len(bars) - max_bars_horizon):
                row_idx = i - 49
                if row_idx >= len(base_matrix):
                    break

                c_win = closes[i - 24: i + 1][::-1]
                h_win = highs[i - 24: i + 1][::-1]
                l_win = lows[i - 24: i + 1][::-1]
                v_win = volumes[i - 24: i + 1][::-1]

                direction = "up" if closes[i] > closes[max(0, i - 3)] else "down"
                rf = compute_risk_features(c_win, h_win, l_win, v_win, direction)
                risk_vec = np.array([rf.get(f, 0.0) for f in RISK_FEATURE_NAMES], dtype=np.float32)

                atr_vals = []
                for j in range(max(0, i - 10), i):
                    tr = max(highs[j] - lows[j],
                             abs(highs[j] - closes[j - 1]) if j > 0 else 0,
                             abs(lows[j] - closes[j - 1]) if j > 0 else 0)
                    atr_vals.append(tr)
                atr = np.mean(atr_vals) if atr_vals else 0.01

                target = compute_risk_target(closes, highs, lows, i, atr, direction, max_bars=max_bars_horizon)
                if target is None:
                    continue

                X_buf[valid, :n_base] = base_matrix[row_idx]
                X_buf[valid, n_base:] = risk_vec
                y_buf[valid] = target
                valid += 1

            if valid > 0:
                results[bs_label] = (X_buf[:valid].copy(), y_buf[:valid].copy())
        return results
    except Exception as e:
        logger.warning(f"Risk worker error for {symbol}: {e}")
        return None

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
    "gap_fill": {"label": "Gap Fill Probability", "order": 7, "expected_models": 7, "phase_num": "5.5"},
    "risk_of_ruin": {"label": "Risk-of-Ruin", "order": 8, "expected_models": 6, "phase_num": "6"},
    "regime_conditional": {"label": "Regime-Conditional", "order": 9, "expected_models": 28, "phase_num": "7"},
    "ensemble_meta": {"label": "Ensemble Meta-Learner", "order": 10, "expected_models": 10, "phase_num": "8"},
    "cnn_patterns": {"label": "CNN Chart Patterns", "order": 11, "expected_models": 13, "phase_num": "9"},
    "deep_learning": {"label": "Deep Learning (VAE/TFT/CNN-LSTM)", "order": 12, "expected_models": 3, "phase_num": "11"},
    "finbert_sentiment": {"label": "FinBERT Sentiment", "order": 13, "expected_models": 1, "phase_num": "12"},
    "auto_validation": {"label": "Auto-Validation", "order": 14, "expected_models": 34, "phase_num": "13"},
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
    """Get symbols that have enough bars for training, ranked by ADV (most liquid first).
    
    Uses a two-step approach to avoid expensive full-collection aggregation:
    1. Get top symbols from symbol_adv_cache (small, fast, indexed)
    2. Verify bar counts only for those candidates
    """
    try:
        logger.info(f"[get_available_symbols] Querying symbols for bar_size={bar_size}, min_bars={min_bars}")
        
        loop = asyncio.get_event_loop()
        
        def _run_query():
            # Step 1: Get top symbols by ADV from the cache (fast — small collection)
            # Fetch more candidates than we need to account for some lacking enough bars
            candidate_limit = 5000  # Get all qualifying symbols from ADV cache
            adv_cursor = db["symbol_adv_cache"].find(
                {}, {"_id": 0, "symbol": 1, "avg_volume": 1}
            ).sort("avg_volume", -1).limit(candidate_limit)
            adv_ranked = list(adv_cursor)
            
            if not adv_ranked:
                # Fallback: no ADV data — use the old aggregation approach
                logger.warning("[get_available_symbols] No ADV cache data, falling back to aggregation")
                pipeline = [
                    {"$match": {"bar_size": bar_size}},
                    {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                    {"$match": {"count": {"$gte": min_bars}}},
                ]
                symbols_with_bars = list(db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True, maxTimeMS=120000))
                return [r["_id"] for r in symbols_with_bars]
            
            candidate_symbols = [d["symbol"] for d in adv_ranked]
            logger.info(f"[get_available_symbols] {len(candidate_symbols)} ADV candidates, verifying bar counts...")
            
            # Step 2: Verify bar counts in batches using aggregation (faster than per-symbol count)
            verified = []
            batch_size = 150  # Small enough to avoid Atlas timeouts
            for batch_start in range(0, len(candidate_symbols), batch_size):
                batch = candidate_symbols[batch_start:batch_start + batch_size]
                try:
                    pipeline = [
                        {"$match": {"bar_size": bar_size, "symbol": {"$in": batch}}},
                        {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                        {"$match": {"count": {"$gte": min_bars}}},
                    ]
                    results = list(db["ib_historical_data"].aggregate(
                        pipeline, allowDiskUse=True, maxTimeMS=30000
                    ))
                    batch_qualified = {r["_id"] for r in results}
                    # Maintain ADV ranking order
                    for sym in batch:
                        if sym in batch_qualified:
                            verified.append(sym)
                except Exception as e:
                    # Fallback to per-symbol count for failed batches
                    logger.warning(f"[get_available_symbols] Batch aggregation failed, using per-symbol fallback: {e}")
                    for sym in batch:
                        try:
                            count = db["ib_historical_data"].count_documents(
                                {"symbol": sym, "bar_size": bar_size},
                                maxTimeMS=5000
                            )
                            if count >= min_bars:
                                verified.append(sym)
                        except Exception:
                            continue
            
            logger.info(f"[get_available_symbols] {len(verified)} symbols verified with >= {min_bars} bars")
            return verified
        
        results = await asyncio.wait_for(
            loop.run_in_executor(TRAINING_POOL, _run_query),
            timeout=600  # 10 minute timeout for full symbol verification
        )
        logger.info(f"[get_available_symbols] Found {len(results)} symbols for {bar_size} (ranked by ADV)")
        return results
    except asyncio.TimeoutError:
        logger.error(f"[get_available_symbols] Timeout querying symbols for {bar_size}")
        return []
    except Exception as e:
        logger.error(f"Failed to get symbols for {bar_size}: {e}")
        return []


async def load_symbol_bars(db, symbol: str, bar_size: str, max_bars: int = 0) -> List[Dict]:
    """Load bars for a symbol+bar_size, sorted chronologically (oldest first).
    
    Uses NVMe disk cache: first call queries MongoDB + writes to disk,
    subsequent calls (from later phases) load from disk.
    
    Args:
        max_bars: If > 0, only load the most recent N bars (saves memory).
                  If 0, auto-resolve from BAR_SIZE_CONFIGS (never truly unlimited).
                  The query fetches newest-first then reverses to chronological order.
    """
    try:
        # Check NVMe disk cache first
        cached_bars = _load_bars_from_disk(symbol, bar_size)
        if cached_bars is not None:
            return cached_bars

        loop = asyncio.get_event_loop()
        
        # Auto-resolve max_bars from config when 0 (prevents unbounded queries on 1-min data)
        effective_max = max_bars
        if effective_max <= 0:
            effective_max = BAR_SIZE_CONFIGS.get(bar_size, {}).get("max_bars", 50000)
            if effective_max <= 0:
                effective_max = 50000  # Hard safety cap
        
        def _run_query():
            query = {"symbol": symbol, "bar_size": bar_size}
            projection = {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            
            # Always use reverse-sort (newest first) + reverse — much faster on large collections
            rows = list(db["ib_historical_data"].find(query, projection)
                       .sort("date", -1).limit(effective_max).max_time_ms(90000))
            rows.reverse()
            return rows
        
        bars = await asyncio.wait_for(
            loop.run_in_executor(TRAINING_POOL, _run_query),
            timeout=90
        )
        # Write to NVMe disk cache for reuse by later phases
        if bars:
            _cache_bars_to_disk(symbol, bar_size, bars)
        return bars
    except asyncio.TimeoutError:
        logger.warning(f"Timeout loading bars for {symbol}/{bar_size}")
        return []
    except Exception as e:
        logger.warning(f"Failed to load bars for {symbol}/{bar_size}: {e}")
        return []


async def load_symbols_parallel(db, symbols: List[str], bar_size: str, min_bars: int = 100, batch_size: int = 20, max_bars: int = 0) -> Dict[str, List[Dict]]:
    """Load bars for multiple symbols in parallel batches.
    
    Args:
        db: MongoDB database
        symbols: List of symbols to load
        bar_size: Bar size string
        min_bars: Minimum bars required per symbol
        batch_size: Number of symbols to load in parallel
        max_bars: If > 0, cap bars per symbol (most recent N bars)
        
    Returns:
        Dict of symbol -> bars for symbols with enough data
    """
    bars_by_symbol = {}
    total_batches = (len(symbols) + batch_size - 1) // batch_size
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        batch_num = i // batch_size + 1
        
        # Load batch in parallel
        tasks = [load_symbol_bars(db, sym, bar_size, max_bars=max_bars) for sym in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for sym, bars in zip(batch, results):
            if isinstance(bars, Exception):
                continue
            if len(bars) >= min_bars:
                bars_by_symbol[sym] = bars
        
        logger.info(f"[load_symbols_parallel] Batch {batch_num}/{total_batches} complete ({len(bars_by_symbol)} symbols loaded)")
    
    return bars_by_symbol


async def stream_load_and_extract(
    db,
    symbols: List[str],
    bar_size: str,
    min_bars: int,
    forecast_horizon: int,
    lookback: int = 50,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Stream-load symbols in batches, extract features, discard raw bars.

    Memory-efficient: only one batch of raw bars is in RAM at a time.
    Accumulated feature arrays are float32 (~60% smaller than Python dicts).

    Returns:
        (X, y) numpy arrays or (None, None) if insufficient data
    """
    from services.ai_modules.timeseries_gbm import _extract_symbol_worker
    from concurrent.futures import ProcessPoolExecutor, as_completed

    n_workers = MAX_EXTRACT_WORKERS
    all_features = []
    all_targets = []
    total_samples = 0
    symbols_processed = 0

    pool = ProcessPoolExecutor(max_workers=n_workers)
    try:
        for batch_start in range(0, len(symbols), STREAM_BATCH_SIZE):
            batch_symbols = symbols[batch_start:batch_start + STREAM_BATCH_SIZE]

            # Load only this batch of bars
            _max_bars = BAR_SIZE_CONFIGS.get(bar_size, {}).get("max_bars", 50000)
            batch_bars = await load_symbols_parallel(
                db, batch_symbols, bar_size, min_bars=min_bars,
                batch_size=50, max_bars=_max_bars
            )

            if not batch_bars:
                symbols_processed += len(batch_symbols)
                continue

            # Prepare worker args
            worker_args = []
            for symbol, bars in batch_bars.items():
                if len(bars) >= lookback + forecast_horizon:
                    worker_args.append((symbol, bars, lookback, forecast_horizon))

            # Parallel feature extraction across CPU cores
            chunk_results = []
            try:
                futures = {pool.submit(_extract_symbol_worker, args): args[0] for args in worker_args}
                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=300)
                        if result is not None:
                            chunk_results.append(result)
                    except Exception as e:
                        logger.warning(f"Worker failed for {futures[future]}: {e}")
            except Exception as e:
                logger.warning(f"Multiprocess failed ({e}), falling back to single-process")
                for args in worker_args:
                    try:
                        result = _extract_symbol_worker(args)
                        if result is not None:
                            chunk_results.append(result)
                    except Exception:
                        pass

            # Accumulate compact numpy arrays
            for feat_matrix, targets in chunk_results:
                all_features.append(feat_matrix)
                all_targets.append(targets)
                total_samples += len(feat_matrix)

            symbols_processed += len(batch_symbols)

            # Free raw bars for this batch — the big memory savings
            del batch_bars, worker_args, chunk_results
            gc.collect()

            logger.info(
                f"[Stream extract] {symbols_processed}/{len(symbols)} symbols, "
                f"{total_samples:,} samples accumulated"
            )
    finally:
        pool.shutdown(wait=True)

    if not all_features:
        return None, None

    X = np.vstack(all_features).astype(np.float32)
    y = np.concatenate(all_targets).astype(np.float32)
    del all_features, all_targets
    gc.collect()

    # Filter out any rows with all zeros (failed extraction)
    valid_rows = np.any(X != 0, axis=1)
    X = X[valid_rows]
    y = y[valid_rows]

    logger.info(f"[Stream extract] Complete: {len(X):,} valid samples from {symbols_processed} symbols")
    return X, y


def count_total_models() -> int:
    """Count total models that will be trained."""
    from services.ai_modules.setup_training_config import get_all_profile_count, SETUP_TRAINING_PROFILES
    generic = len(BAR_SIZE_CONFIGS)  # 7
    setup_long = sum(len(v) for k, v in SETUP_TRAINING_PROFILES.items() if not k.startswith("SHORT_"))  # 17
    setup_short = sum(len(v) for k, v in SETUP_TRAINING_PROFILES.items() if k.startswith("SHORT_"))  # 17
    volatility = len(BAR_SIZE_CONFIGS)  # 7
    exit_timing = len(ALL_SETUP_TYPES)  # 10
    sector_relative = 3  # daily, hourly, 5min
    gap_fill = 7  # one per timeframe
    risk_of_ruin = 6  # 1min through daily
    regime_conditional = generic * len(["bull_trend", "bear_trend", "range_bound", "high_vol"])  # 7 * 4 = 28
    ensemble = len(ALL_SETUP_TYPES)  # 10
    cnn_models = 13  # CNN chart pattern models
    dl_models = 3  # VAE Regime, TFT, CNN-LSTM
    finbert = 1    # FinBERT Sentiment pipeline
    return (generic + setup_long + setup_short + volatility + exit_timing +
            sector_relative + gap_fill + risk_of_ruin + regime_conditional + ensemble +
            cnn_models + dl_models + finbert)


async def run_training_pipeline(
    db,
    phases: List[str] = None,
    bar_sizes: List[str] = None,
    max_symbols_override: int = None,
    force_retrain: bool = False,
    resume_max_age_hours: float = 24.0,
) -> Dict[str, Any]:
    """
    Run the full training pipeline.

    Args:
        db: MongoDB database instance
        phases: Which phases to run. Default: all.
            Options: "generic", "setup", "volatility", "regime", "exit", "ensemble"
        bar_sizes: Which bar sizes to train. Default: all.
        max_symbols_override: Override max symbols per bar_size.
        force_retrain: If True, retrain all models even if recently trained.
        resume_max_age_hours: Skip models trained within this many hours (default 24h).

    Returns:
        Dict with training results summary.
    """
    if phases is None:
        phases = ["generic", "setup", "short", "volatility", "exit", "sector", "gap_fill", "risk", "regime", "ensemble", "cnn", "dl", "finbert", "validate"]
        # Note: "regime" and "ensemble" depend on Phase 1-7 models being trained first
        # "validate" runs 5-Phase Auto-Validation on setup_specific + ensemble models
        # "dl" trains Phase 5 deep learning models (VAE, TFT, CNN-LSTM)
        # "finbert" runs FinBERT news collection + sentiment scoring

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
        # Clear symbol cache at start of pipeline run
        clear_symbol_cache()
        _clear_disk_cache()
        
        import time as _time
        _pipeline_start = _time.monotonic()

        if force_retrain:
            logger.info("[PIPELINE] force_retrain=True — all models will be retrained")
        else:
            logger.info(f"[PIPELINE] Resume enabled — skipping models trained within {resume_max_age_hours}h")

        # Canonical model name mapping — must match timeseries_service.py SUPPORTED_TIMEFRAMES
        DIRECTIONAL_MODEL_NAMES = {
            "1 min": "direction_predictor_1min",
            "5 mins": "direction_predictor_5min",
            "15 mins": "direction_predictor_15min",
            "30 mins": "direction_predictor_30min",
            "1 hour": "direction_predictor_1hour",
            "1 day": "direction_predictor_daily",
            "1 week": "direction_predictor_weekly",
        }

        def _phase_memory_cleanup(phase_name: str):
            """Force garbage collection between phases to prevent memory accumulation.
            
            Python's gc.collect() frees Python objects, but glibc's malloc keeps
            freed pages in its internal free-list. malloc_trim(0) forces glibc
            to return unused memory pages to the OS, preventing swap buildup
            across phase transitions.
            """
            gc.collect()
            
            # Force glibc to release freed memory back to OS
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)
            except Exception:
                pass  # Not Linux or libc not available
            
            gc.collect()  # Second pass after malloc_trim
            
            try:
                with open('/proc/meminfo') as f:
                    for line in f:
                        if line.startswith('MemAvailable:'):
                            avail_gb = int(line.split()[1]) // 1024 // 1024
                            logger.info(f"[MEMORY] After {phase_name}: {avail_gb}GB available")
                            if avail_gb < 30:
                                logger.warning(f"[MEMORY] LOW MEMORY after {phase_name}: {avail_gb}GB available! "
                                              f"Sleeping 10s for OS to reclaim pages...")
                                import time
                                time.sleep(10)
                                gc.collect()
                                try:
                                    libc.malloc_trim(0)
                                except Exception:
                                    pass
                                # Re-check
                                with open('/proc/meminfo') as f2:
                                    for line2 in f2:
                                        if line2.startswith('MemAvailable:'):
                                            avail_gb2 = int(line2.split()[1]) // 1024 // 1024
                                            logger.info(f"[MEMORY] After recovery sleep: {avail_gb2}GB available")
                                            break
                            break
            except Exception:
                pass

        # ── Shared Data: Pre-load once, reuse across phases ──
        _shared_regime_provider = None
        _shared_spy_data = None

        async def _get_shared_regime_data():
            """Load RegimeFeatureProvider once, reuse in Phase 3 and Phase 7."""
            nonlocal _shared_regime_provider, _shared_spy_data
            if _shared_regime_provider is None:
                from services.ai_modules.regime_features import RegimeFeatureProvider
                _shared_regime_provider = RegimeFeatureProvider(db)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(TRAINING_POOL, _shared_regime_provider.preload_index_daily)
                _shared_spy_data = _shared_regime_provider._data.get("spy", {})
                logger.info("[SHARED] RegimeFeatureProvider loaded (shared across Phase 3 + Phase 7)")
            return _shared_regime_provider, _shared_spy_data

        # ── Phase 1: Generic Directional Models (Full Universe) ──
        if "generic" in phases:
            status.update(phase="generic_directional")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 1: Training Generic Directional Models (Full Universe) === [{int(_p_elapsed//60)}m elapsed]")
            try:
                from services.ai_modules.timeseries_service import TimeSeriesAIService

                ts_service = TimeSeriesAIService()
                ts_service.set_db(db)

                for bs in bar_sizes:
                    config = BAR_SIZE_CONFIGS.get(bs)
                    if not config:
                        continue
                    model_name = DIRECTIONAL_MODEL_NAMES.get(bs, f"direction_predictor_{bs.replace(' ', '_')}")
                    status.update(current_model=model_name)

                    # Pipeline resume: skip if recently trained
                    if not force_retrain:
                        resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                        if resumed:
                            results["models_trained"].append({
                                "name": model_name, "accuracy": resumed["accuracy"],
                                "samples": resumed["samples"], "resumed": True,
                            })
                            results["total_samples"] += resumed["samples"]
                            status.add_completed(model_name, resumed["accuracy"])
                            continue

                    logger.info(f"[Phase 1] Training {model_name} via Full Universe...")

                    def _phase1_progress(pct, msg):
                        """Callback: push batch progress to DB so WS broadcasts to UI."""
                        status.update(
                            current_phase_progress=pct,
                            current_model=f"{model_name} — {msg}",
                        )

                    result = await ts_service.train_full_universe(
                        bar_size=bs,
                        symbol_batch_size=500,
                        max_bars_per_symbol=0,  # Auto-resolve from TIMEFRAME_SETTINGS (50K for intraday, 10K for daily)
                        progress_callback=_phase1_progress,
                    )

                    if result.get("success"):
                        acc = result.get("metrics", {}).get("accuracy", 0)
                        samples = result.get("training_samples", 0)
                        results["models_trained"].append({
                            "name": model_name,
                            "accuracy": acc,
                            "samples": samples,
                        })
                        results["total_samples"] += samples
                        status.add_completed(model_name, acc)
                        logger.info(f"[Phase 1] {model_name}: {acc*100:.1f}% accuracy, {samples:,} samples")
                    else:
                        error = result.get("error", "Training failed")
                        results["models_failed"].append({"name": model_name, "reason": error})
                        status.add_error(model_name, error)
                        logger.warning(f"[Phase 1] {model_name} failed: {error}")

                    gc.collect()

            except Exception as e:
                logger.error(f"Phase 1 Full Universe error: {e}", exc_info=True)
                results["models_failed"].append({"name": "generic_directional", "reason": str(e)})

        # ── Phase 2: Setup-Specific Models (Long) ──
        if "setup" in phases:
            _phase_memory_cleanup("Phase 1")
            status.update(phase="setup_specific")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 2: Training Setup-Specific Models (Long) === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.setup_features import get_setup_feature_names
            from services.ai_modules.setup_training_config import get_setup_profiles, get_model_name
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from collections import defaultdict
            from concurrent.futures import ProcessPoolExecutor, as_completed

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()
            n_workers = MAX_EXTRACT_WORKERS

            # Group all (setup_type, profile) pairs by bar_size so bars are loaded ONCE per bar_size
            profiles_by_bs = defaultdict(list)
            for setup_type in ALL_SETUP_TYPES:
                for profile in get_setup_profiles(setup_type):
                    profiles_by_bs[profile["bar_size"]].append((setup_type, profile))

            for bs, st_profiles in profiles_by_bs.items():
                bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                max_sym = max_symbols_override or min(SETUP_PHASE_MAX_SYMBOLS, bs_config.get("max_symbols", 2500))
                symbols = await get_cached_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                symbols = symbols[:max_sym]
                if not symbols:
                    continue

                # Build setup_configs for the worker: all setup types that share this bar_size
                setup_configs = [(st, p["forecast_horizon"], p.get("noise_threshold", 0.003)) for st, p in st_profiles]
                max_fh = max(fh for _, fh, _ in setup_configs)
                min_required = 70 + max_fh

                # Per-model accumulators {(setup_type, fh): {"X": [], "y": [], ...}}
                model_accum = {}
                for st, profile in st_profiles:
                    key = (st, profile["forecast_horizon"])
                    model_name = get_model_name(st, bs)
                    feat_names = get_setup_feature_names(st)
                    combined_names = base_names + [f"setup_{n}" for n in feat_names]
                    model_accum[key] = {
                        "X": [], "y": [], "model_name": model_name,
                        "combined_names": combined_names,
                        "num_boost": profile.get("num_boost_round", 150),
                        "fh": profile["forecast_horizon"],
                    }
                    status.update(current_model=model_name)

                # Stream-load in batches, multiprocess extraction across all setup types at once
                total_syms = len(symbols)
                pool = ProcessPoolExecutor(max_workers=n_workers)
                try:
                    for sb_start in range(0, total_syms, STREAM_BATCH_SIZE):
                        sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                        sb_end = min(sb_start + STREAM_BATCH_SIZE, total_syms)
                        status.update(
                            current_model=f"{bs} setups — loading symbols {sb_start+1}-{sb_end}/{total_syms}",
                            current_phase_progress=(sb_end / total_syms) * 100,
                        )
                        batch_bars = await load_symbols_parallel(
                            db, sb_syms, bs, min_bars=min_required, batch_size=50,
                            max_bars=bs_config.get("max_bars", 50000)
                        )
                        if not batch_bars:
                            continue

                        worker_args = [
                            (sym, bars, setup_configs)
                            for sym, bars in batch_bars.items()
                            if len(bars) >= min_required
                        ]

                        chunk_results = []
                        try:
                            futures = {pool.submit(_extract_setup_long_worker, a): a[0] for a in worker_args}
                            for future in as_completed(futures):
                                try:
                                    res = future.result(timeout=300)
                                    if res:
                                        chunk_results.append(res)
                                except Exception as e:
                                    logger.warning(f"Setup worker failed for {futures[future]}: {e}")
                        except Exception as e:
                            logger.warning(f"ProcessPool failed ({e}), falling back to sequential")
                            for a in worker_args:
                                try:
                                    res = _extract_setup_long_worker(a)
                                    if res:
                                        chunk_results.append(res)
                                except Exception:
                                    pass

                        for res_dict in chunk_results:
                            for key, (X_chunk, y_chunk) in res_dict.items():
                                if key in model_accum:
                                    model_accum[key]["X"].append(X_chunk)
                                    model_accum[key]["y"].append(y_chunk)

                        del batch_bars, worker_args, chunk_results
                    gc.collect()
                finally:
                    pool.shutdown(wait=True)

                # Train each model from accumulated numpy arrays
                for key, data in model_accum.items():
                    model_name = data["model_name"]
                    status.update(current_model=model_name)
                    try:
                        # Pipeline resume
                        if not force_retrain:
                            resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                            if resumed:
                                results["models_trained"].append({
                                    "name": model_name, "accuracy": resumed["accuracy"],
                                    "samples": resumed["samples"], "resumed": True,
                                })
                                results["total_samples"] += resumed["samples"]
                                status.add_completed(model_name, resumed["accuracy"])
                                continue

                        if not data["X"]:
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        X = np.vstack(data["X"]).astype(np.float32)
                        y = np.concatenate(data["y"]).astype(np.float32)
                        del data["X"], data["y"]

                        if len(X) < MIN_TRAINING_SAMPLES:
                            logger.warning(f"Insufficient training data for {model_name}: {len(X)}")
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        logger.info(
                            f"Training {model_name}: {len(X):,} samples, {len(data['combined_names'])} features, "
                            f"UP={np.sum(y==2)}, FLAT={np.sum(y==1)}, DOWN={np.sum(y==0)}"
                        )

                        model = TimeSeriesGBM(model_name=model_name, forecast_horizon=data["fh"])
                        model.set_db(db)
                        metrics = await _run_in_thread(
                            model.train_from_features,
                            X, y, data["combined_names"],
                            num_boost_round=data["num_boost"],
                            early_stopping_rounds=15,
                            num_classes=3,
                        )

                        del X, y
                        gc.collect()

                        if metrics and metrics.accuracy > 0:
                            results["models_trained"].append({
                                "name": model_name, "accuracy": metrics.accuracy,
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

                del model_accum
                gc.collect()

        # ── Phase 2.5: Short Setup-Specific Models ──
        if "short" in phases:
            _phase_memory_cleanup("Phase 2")
            status.update(phase="short_setup_specific")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 2.5: Training SHORT Setup-Specific Models === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.short_setup_features import get_short_setup_feature_names
            from services.ai_modules.setup_training_config import get_setup_profiles, get_model_name
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from collections import defaultdict
            from concurrent.futures import ProcessPoolExecutor, as_completed

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()
            n_workers = MAX_EXTRACT_WORKERS

            # Group by bar_size (same optimization as Phase 2)
            profiles_by_bs = defaultdict(list)
            for setup_type in ALL_SHORT_SETUP_TYPES:
                for profile in get_setup_profiles(setup_type):
                    profiles_by_bs[profile["bar_size"]].append((setup_type, profile))

            for bs, st_profiles in profiles_by_bs.items():
                bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                max_sym = max_symbols_override or min(SETUP_PHASE_MAX_SYMBOLS, bs_config.get("max_symbols", 2500))
                symbols = await get_cached_symbols(db, bs, 100)
                symbols = symbols[:max_sym]
                if not symbols:
                    continue

                setup_configs = [(st, p["forecast_horizon"], p.get("noise_threshold", 0.003)) for st, p in st_profiles]
                max_fh = max(fh for _, fh, _ in setup_configs)
                min_required = 70 + max_fh

                model_accum = {}
                for st, profile in st_profiles:
                    key = (st, profile["forecast_horizon"])
                    model_name = get_model_name(st, bs)
                    feat_names = get_short_setup_feature_names(st)
                    combined_names = base_names + [f"short_{n}" for n in feat_names]
                    model_accum[key] = {
                        "X": [], "y": [], "model_name": model_name,
                        "combined_names": combined_names,
                        "num_boost": profile.get("num_boost_round", 150),
                        "fh": profile["forecast_horizon"],
                    }
                    status.update(current_model=model_name)

                pool = ProcessPoolExecutor(max_workers=n_workers)
                try:
                    for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                        sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                        sb_end = min(sb_start + STREAM_BATCH_SIZE, len(symbols))
                        status.update(
                            current_model=f"{bs} short setups — symbols {sb_start+1}-{sb_end}/{len(symbols)}",
                            current_phase_progress=(sb_end / len(symbols)) * 100,
                        )
                        batch_bars = await load_symbols_parallel(
                            db, sb_syms, bs, min_bars=min_required, batch_size=50,
                            max_bars=bs_config.get("max_bars", 50000)
                        )
                        if not batch_bars:
                            continue

                        worker_args = [
                            (sym, bars, setup_configs)
                            for sym, bars in batch_bars.items()
                            if len(bars) >= min_required
                        ]

                        chunk_results = []
                        try:
                            futures = {pool.submit(_extract_setup_short_worker, a): a[0] for a in worker_args}
                            for future in as_completed(futures):
                                try:
                                    res = future.result(timeout=300)
                                    if res:
                                        chunk_results.append(res)
                                except Exception as e:
                                    logger.warning(f"Short worker failed for {futures[future]}: {e}")
                        except Exception as e:
                            logger.warning(f"ProcessPool failed ({e}), falling back to sequential")
                            for a in worker_args:
                                try:
                                    res = _extract_setup_short_worker(a)
                                    if res:
                                        chunk_results.append(res)
                                except Exception:
                                    pass

                        for res_dict in chunk_results:
                            for key, (X_chunk, y_chunk) in res_dict.items():
                                if key in model_accum:
                                    model_accum[key]["X"].append(X_chunk)
                                    model_accum[key]["y"].append(y_chunk)

                        del batch_bars, worker_args, chunk_results
                    gc.collect()
                finally:
                    pool.shutdown(wait=True)

                for key, data in model_accum.items():
                    model_name = data["model_name"]
                    status.update(current_model=model_name)
                    try:
                        # Pipeline resume
                        if not force_retrain:
                            resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                            if resumed:
                                results["models_trained"].append({
                                    "name": model_name, "accuracy": resumed["accuracy"],
                                    "samples": resumed["samples"], "resumed": True,
                                })
                                results["total_samples"] += resumed["samples"]
                                status.add_completed(model_name, resumed["accuracy"])
                                continue

                        if not data["X"]:
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        X = np.vstack(data["X"]).astype(np.float32)
                        y = np.concatenate(data["y"]).astype(np.float32)
                        del data["X"], data["y"]

                        if len(X) < MIN_TRAINING_SAMPLES:
                            logger.warning(f"Insufficient short training data for {model_name}: {len(X)}")
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        logger.info(
                            f"Training {model_name}: {len(X):,} samples, {len(data['combined_names'])} features, "
                            f"DOWN(good)={np.sum(y==2)}, FLAT={np.sum(y==1)}, UP(bad)={np.sum(y==0)}"
                        )

                        model = TimeSeriesGBM(model_name=model_name, forecast_horizon=data["fh"])
                        model.set_db(db)
                        metrics = await _run_in_thread(
                            model.train_from_features,
                            X, y, data["combined_names"],
                            num_boost_round=data["num_boost"],
                            early_stopping_rounds=15,
                            num_classes=3,
                        )

                        del X, y
                        gc.collect()

                        if metrics and metrics.accuracy > 0:
                            results["models_trained"].append({
                                "name": model_name, "accuracy": metrics.accuracy,
                                "samples": metrics.training_samples, "direction": "short",
                            })
                            results["total_samples"] += metrics.training_samples
                            status.add_completed(model_name, metrics.accuracy)
                        else:
                            results["models_failed"].append({"name": model_name, "reason": "Low accuracy or no metrics"})

                    except Exception as e:
                        logger.error(f"Failed to train {model_name}: {e}")
                        results["models_failed"].append({"name": model_name, "reason": str(e)})
                        status.add_error(model_name, str(e))

                del model_accum
                gc.collect()

        # ── Phase 3: Volatility Prediction Models ──
        if "volatility" in phases:
            _phase_memory_cleanup("Phase 2.5")
            status.update(phase="volatility_prediction")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 3: Training Volatility Prediction Models === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.volatility_model import (
                VOL_MODEL_CONFIGS, VOL_FEATURE_NAMES,
                compute_vol_specific_features, compute_vol_target,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from services.ai_modules.regime_features import REGIME_FEATURE_NAMES

            regime_provider, _ = await _get_shared_regime_data()

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            for bs in bar_sizes:
                vol_config = VOL_MODEL_CONFIGS.get(bs)
                if not vol_config:
                    continue

                model_name = vol_config["model_name"]
                fh = vol_config["forecast_horizon"]
                status.update(current_model=model_name)

                # Pipeline resume
                if not force_retrain:
                    resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                    if resumed:
                        results["models_trained"].append({
                            "name": model_name, "accuracy": resumed["accuracy"],
                            "samples": resumed["samples"], "resumed": True,
                        })
                        results["total_samples"] += resumed["samples"]
                        status.add_completed(model_name, resumed["accuracy"])
                        continue

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    max_sym = max_symbols_override or bs_config.get("max_symbols", 500)
                    symbols = await get_cached_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    symbols = symbols[:max_sym]

                    if not symbols:
                        continue

                    combined_names = base_names + [f"vol_{n}" for n in VOL_FEATURE_NAMES] + REGIME_FEATURE_NAMES
                    
                    # Stream-load symbols in batches to limit RAM
                    min_required = 70 + fh
                    all_X = []
                    all_y = []

                    for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                        sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                        sb_end = min(sb_start + STREAM_BATCH_SIZE, len(symbols))
                        status.update(
                            current_model=f"vol_{bs} — symbols {sb_start+1}-{sb_end}/{len(symbols)}",
                            current_phase_progress=(sb_end / len(symbols)) * 100,
                        )
                        batch_bars = await load_symbols_parallel(
                            db, sb_syms, bs, min_bars=min_required, batch_size=50,
                            max_bars=bs_config.get("max_bars", 50000)
                        )

                        n_vol = len(VOL_FEATURE_NAMES)
                        n_regime = len(REGIME_FEATURE_NAMES)

                        for sym, bars in batch_bars.items():

                            closes = np.array([b["close"] for b in bars], dtype=np.float32)
                            highs = np.array([b["high"] for b in bars], dtype=np.float32)
                            lows = np.array([b["low"] for b in bars], dtype=np.float32)
                            volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
                            opens = np.array([b.get("open", 0) for b in bars], dtype=np.float32)

                            # Bulk-extract base features ONCE for this symbol (NVMe cached)
                            base_matrix = cached_extract_features_bulk(feature_engineer, bars, sym, bs)
                            if base_matrix is None:
                                continue

                            n_base = base_matrix.shape[1]
                            max_rows = len(bars) - 50 - fh
                            if max_rows <= 0:
                                continue

                            X_buf = np.empty((max_rows, n_base + n_vol + n_regime), dtype=np.float32)
                            y_buf = np.empty(max_rows, dtype=np.float32)
                            valid = 0

                            for i in range(50, len(bars) - fh):
                                row_idx = i - 49
                                if row_idx >= len(base_matrix):
                                    break

                                # Vol-specific features
                                c_window = closes[i - 49: i + 1][::-1]
                                h_window = highs[i - 49: i + 1][::-1]
                                l_window = lows[i - 49: i + 1][::-1]
                                v_window = volumes[i - 49: i + 1][::-1]
                                o_window = opens[i - 49: i + 1][::-1]
                                vol_feats = compute_vol_specific_features(c_window, h_window, l_window, o_window, v_window)

                                # Regime features
                                bar_date = str(bars[i].get("date", ""))
                                regime_feats = regime_provider.get_regime_features_for_date(bar_date)

                                # Target
                                target = compute_vol_target(closes, fh, i)
                                if target is None:
                                    continue

                                X_buf[valid, :n_base] = base_matrix[row_idx]
                                X_buf[valid, n_base:n_base + n_vol] = [vol_feats.get(f, 0.0) for f in VOL_FEATURE_NAMES]
                                X_buf[valid, n_base + n_vol:] = [regime_feats.get(f, 0.0) for f in REGIME_FEATURE_NAMES]
                                y_buf[valid] = target
                                valid += 1

                            if valid > 0:
                                all_X.append(X_buf[:valid].copy())
                                all_y.append(y_buf[:valid].copy())

                        del batch_bars
                        gc.collect()

                    if len(all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient vol training data for {bs}: {len(all_X)}")
                        continue

                    X = np.vstack(all_X).astype(np.float32)
                    y = np.concatenate(all_y).astype(np.float32)
                    del all_X, all_y
                    logger.info(f"Training {model_name}: {len(X)} samples, {len(combined_names)} features")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=fh)
                    model.set_db(db)
                    metrics = await _run_in_thread(
                        model.train_from_features,
                        X, y, combined_names,
                        num_boost_round=150,
                        early_stopping_rounds=15,
                    )

                    del X, y
                    gc.collect()

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
            _phase_memory_cleanup("Phase 3")
            status.update(phase="exit_timing")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 4: Training Exit Timing Models === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.exit_timing_model import EXIT_MODEL_CONFIGS, EXIT_FEATURE_NAMES
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from concurrent.futures import ProcessPoolExecutor, as_completed

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()
            n_workers = MAX_EXTRACT_WORKERS

            # All exit models use "1 day" bars — load once
            bs = "1 day"
            bs_config = BAR_SIZE_CONFIGS.get(bs, {})
            symbols = await get_cached_symbols(db, bs, 100)
            max_sym = max_symbols_override or bs_config.get("max_symbols", 500)
            symbols = symbols[:max_sym]
            combined_names = base_names + [f"exit_{n}" for n in EXIT_FEATURE_NAMES]

            if symbols:
                exit_configs = [(st, cfg["max_horizon"]) for st, cfg in EXIT_MODEL_CONFIGS.items()]
                max_horizon = max(h for _, h in exit_configs)
                min_required = 70 + max_horizon

                model_accum = {}
                for st, cfg in EXIT_MODEL_CONFIGS.items():
                    model_accum[st] = {"X": [], "y": [], "model_name": cfg["model_name"], "max_horizon": cfg["max_horizon"]}
                    status.update(current_model=cfg["model_name"])

                pool = ProcessPoolExecutor(max_workers=n_workers)
                try:
                    for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                        sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                        sb_end = min(sb_start + STREAM_BATCH_SIZE, len(symbols))
                        status.update(
                            current_model=f"exit_{bs} — symbols {sb_start+1}-{sb_end}/{len(symbols)}",
                            current_phase_progress=(sb_end / len(symbols)) * 100,
                        )
                        batch_bars = await load_symbols_parallel(
                            db, sb_syms, bs, min_bars=min_required, batch_size=50,
                            max_bars=bs_config.get("max_bars", 50000)
                        )
                        if not batch_bars:
                            continue

                        worker_args = [
                            (sym, bars, exit_configs)
                            for sym, bars in batch_bars.items()
                            if len(bars) >= min_required
                        ]

                        chunk_results = []
                        try:
                            futures = {pool.submit(_extract_exit_worker, a): a[0] for a in worker_args}
                            for future in as_completed(futures):
                                try:
                                    res = future.result(timeout=300)
                                    if res:
                                        chunk_results.append(res)
                                except Exception as e:
                                    logger.warning(f"Exit worker failed for {futures[future]}: {e}")
                        except Exception as e:
                            logger.warning(f"ProcessPool failed ({e}), falling back to sequential")
                            for a in worker_args:
                                try:
                                    res = _extract_exit_worker(a)
                                    if res:
                                        chunk_results.append(res)
                                except Exception:
                                    pass

                        for res_dict in chunk_results:
                            for st_key, (X_chunk, y_chunk) in res_dict.items():
                                if st_key in model_accum:
                                    model_accum[st_key]["X"].append(X_chunk)
                                    model_accum[st_key]["y"].append(y_chunk)

                        del batch_bars, worker_args, chunk_results
                    gc.collect()
                finally:
                    pool.shutdown(wait=True)

                for st_key, data in model_accum.items():
                    model_name = data["model_name"]
                    max_h = data["max_horizon"]
                    status.update(current_model=model_name)
                    try:
                        # Pipeline resume
                        if not force_retrain:
                            resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                            if resumed:
                                results["models_trained"].append({
                                    "name": model_name, "accuracy": resumed["accuracy"],
                                    "samples": resumed["samples"], "resumed": True,
                                })
                                results["total_samples"] += resumed["samples"]
                                status.add_completed(model_name, resumed["accuracy"])
                                continue

                        if not data["X"]:
                            results["models_failed"].append({"name": model_name, "reason": "Insufficient data"})
                            continue

                        X = np.vstack(data["X"]).astype(np.float32)
                        y_raw = np.concatenate(data["y"]).astype(np.float32)
                        del data["X"], data["y"]

                        if len(X) < MIN_TRAINING_SAMPLES:
                            logger.warning(f"Insufficient exit training data for {st_key}: {len(X)}")
                            continue

                        # Bucket into classes: QUICK (1-5), MEDIUM (6-15), EXTENDED (16+)
                        y_classes = np.zeros(len(y_raw), dtype=np.float32)
                        y_classes[y_raw <= 5] = 0
                        y_classes[(y_raw > 5) & (y_raw <= 15)] = 1
                        y_classes[y_raw > 15] = 2

                        logger.info(
                            f"Training {model_name}: {len(X):,} samples, "
                            f"Quick={np.sum(y_classes==0)}, Med={np.sum(y_classes==1)}, Ext={np.sum(y_classes==2)}"
                        )

                        model = TimeSeriesGBM(model_name=model_name, forecast_horizon=max_h)
                        model.set_db(db)
                        metrics = await _run_in_thread(
                            model.train_from_features,
                            X, y_classes, combined_names,
                            num_boost_round=150, early_stopping_rounds=15, num_classes=3,
                        )

                        del X, y_raw, y_classes
                        gc.collect()

                        if metrics and metrics.accuracy > 0:
                            results["models_trained"].append({
                                "name": model_name, "accuracy": metrics.accuracy,
                                "samples": metrics.training_samples,
                            })
                            results["total_samples"] += metrics.training_samples
                            status.add_completed(model_name, metrics.accuracy)

                    except Exception as e:
                        logger.error(f"Failed to train {model_name}: {e}")
                        results["models_failed"].append({"name": model_name, "reason": str(e)})
                        status.add_error(model_name, str(e))

                del model_accum
                gc.collect()

        # ── Phase 5: Sector-Relative Models ──
        if "sector" in phases:
            _phase_memory_cleanup("Phase 4")
            status.update(phase="sector_relative")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 5: Training Sector-Relative Models === [{int(_p_elapsed//60)}m elapsed]")
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

                # Pipeline resume
                if not force_retrain:
                    resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                    if resumed:
                        results["models_trained"].append({
                            "name": model_name, "accuracy": resumed["accuracy"],
                            "samples": resumed["samples"], "resumed": True,
                        })
                        results["total_samples"] += resumed["samples"]
                        status.add_completed(model_name, resumed["accuracy"])
                        continue

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    symbols = await get_cached_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    max_sym = max_symbols_override or bs_config.get("max_symbols", 500)
                    symbols = symbols[:max_sym]

                    # Preload sector ETF bars
                    sector_etf_bars = {}
                    for etf in sector_mapper.get_all_sector_etfs():
                        etf_bars = await load_symbol_bars(db, etf, bs)
                        if len(etf_bars) >= 50:
                            sector_etf_bars[etf] = {
                                "closes": np.array([b["close"] for b in etf_bars], dtype=np.float32),
                                "volumes": np.array([b.get("volume", 0) for b in etf_bars], dtype=np.float32),
                            }

                    combined_names = base_names + [f"secrel_{n}" for n in SECTOR_REL_FEATURE_NAMES]
                    n_sec = len(SECTOR_REL_FEATURE_NAMES)
                    
                    # Stream-load symbols in batches to limit RAM
                    min_required = 70 + fh
                    all_X = []
                    all_y = []

                    for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                        sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                        sb_end = min(sb_start + STREAM_BATCH_SIZE, len(symbols))
                        status.update(
                            current_model=f"sector_{bs} — symbols {sb_start+1}-{sb_end}/{len(symbols)}",
                            current_phase_progress=(sb_end / len(symbols)) * 100,
                        )
                        batch_bars = await load_symbols_parallel(
                            db, sb_syms, bs, min_bars=min_required, batch_size=50,
                            max_bars=bs_config.get("max_bars", 50000)
                        )

                        for sym, bars in batch_bars.items():
                            sector_etf = sector_mapper.get_sector_etf(sym)
                            if sector_etf is None or sector_etf not in sector_etf_bars:
                                continue

                            stock_closes = np.array([b["close"] for b in bars], dtype=np.float32)
                            stock_volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
                            sec_data = sector_etf_bars[sector_etf]
                            sec_closes = sec_data["closes"]
                            sec_volumes = sec_data["volumes"]

                            min_len = min(len(stock_closes), len(sec_closes))
                            if min_len < 70 + fh:
                                continue

                            # Bulk-extract base features ONCE for this symbol (NVMe cached)
                            base_matrix = cached_extract_features_bulk(feature_engineer, bars, sym, bs)
                            if base_matrix is None:
                                continue

                            n_base = base_matrix.shape[1]
                            max_rows = min_len - 50 - fh
                            if max_rows <= 0:
                                continue

                            X_buf = np.empty((max_rows, n_base + n_sec), dtype=np.float32)
                            y_buf = np.empty(max_rows, dtype=np.float32)
                            valid = 0

                            for i in range(50, min_len - fh):
                                row_idx = i - 49
                                if row_idx >= len(base_matrix):
                                    break

                                # Sector-relative features
                                sc = stock_closes[max(0, i - 24): i + 1][::-1]
                                sv = stock_volumes[max(0, i - 24): i + 1][::-1]
                                ec = sec_closes[max(0, i - 24): i + 1][::-1]
                                ev = sec_volumes[max(0, i - 24): i + 1][::-1]

                                sec_feats = compute_sector_relative_features(sc, sv, ec, ev)

                                target = compute_sector_relative_target(stock_closes, sec_closes, i, fh)
                                if target is None:
                                    continue

                                X_buf[valid, :n_base] = base_matrix[row_idx]
                                X_buf[valid, n_base:] = [sec_feats.get(f, 0.0) for f in SECTOR_REL_FEATURE_NAMES]
                                y_buf[valid] = target
                                valid += 1

                            if valid > 0:
                                all_X.append(X_buf[:valid].copy())
                                all_y.append(y_buf[:valid].copy())

                        del batch_bars
                        gc.collect()

                    if len(all_X) < 1 or sum(len(x) for x in all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient sector-relative data for {bs}: {sum(len(x) for x in all_X) if all_X else 0}")
                        continue

                    X = np.vstack(all_X).astype(np.float32)
                    y = np.concatenate(all_y).astype(np.float32)
                    del all_X, all_y
                    logger.info(f"Training {model_name}: {len(X)} samples")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=fh)
                    model.set_db(db)
                    metrics = await _run_in_thread(model.train_from_features, X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

                    del X, y
                    gc.collect()

                    if metrics and metrics.accuracy > 0:
                        results["models_trained"].append({"name": model_name, "accuracy": metrics.accuracy, "samples": metrics.training_samples})
                        results["total_samples"] += metrics.training_samples
                        status.add_completed(model_name, metrics.accuracy)

                except Exception as e:
                    logger.error(f"Failed to train {model_name}: {e}")
                    results["models_failed"].append({"name": model_name, "reason": str(e)})
                    status.add_error(model_name, str(e))

        # ── Phase 5.5: Gap Fill Probability Models ──
        if "gap_fill" in phases:
            _phase_memory_cleanup("Phase 5")
            status.update(phase="gap_fill")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 5.5: Training Gap Fill Probability Models === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.gap_fill_model import (
                GAP_MODEL_CONFIGS, GAP_FEATURE_NAMES,
                compute_gap_features, compute_gap_fill_target,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()
            combined_names = base_names + [f"gap_{n}" for n in GAP_FEATURE_NAMES]

            for bs, gap_config in GAP_MODEL_CONFIGS.items():
                model_name = gap_config["model_name"]
                max_bars = gap_config["max_bars"]
                status.update(current_model=model_name)

                # Pipeline resume
                if not force_retrain:
                    resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                    if resumed:
                        results["models_trained"].append({
                            "name": model_name, "accuracy": resumed["accuracy"],
                            "samples": resumed["samples"], "resumed": True,
                        })
                        results["total_samples"] += resumed["samples"]
                        status.add_completed(model_name, resumed["accuracy"])
                        continue

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    symbols = await get_cached_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    max_sym = max_symbols_override or bs_config.get("max_symbols", 500)
                    symbols = symbols[:max_sym]

                    min_required = 70 + max_bars
                    all_X = []
                    all_y = []

                    for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                        sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                        sb_end = min(sb_start + STREAM_BATCH_SIZE, len(symbols))
                        status.update(
                            current_model=f"risk_{bs} — symbols {sb_start+1}-{sb_end}/{len(symbols)}",
                            current_phase_progress=(sb_end / len(symbols)) * 100,
                        )
                        batch_bars = await load_symbols_parallel(
                            db, sb_syms, bs, min_bars=min_required, batch_size=50,
                            max_bars=bs_config.get("max_bars", 50000)
                        )
                        if not batch_bars:
                            continue

                        for sym, bars in batch_bars.items():
                            if len(bars) < min_required:
                                continue

                            # Bulk-extract base features (NVMe cached)
                            base_matrix = cached_extract_features_bulk(feature_engineer, bars, sym, bs)
                            if base_matrix is None:
                                continue

                            n_base = base_matrix.shape[1]
                            n_gap = len(GAP_FEATURE_NAMES)
                            closes = np.array([b["close"] for b in bars], dtype=np.float32)
                            opens = np.array([b["open"] for b in bars], dtype=np.float32)
                            volumes = np.array([b.get("volume", 0) for b in bars], dtype=np.float32)
                            highs = np.array([b["high"] for b in bars], dtype=np.float32)
                            lows = np.array([b["low"] for b in bars], dtype=np.float32)

                            # Compute 20-day rolling average volume
                            avg_vol_20 = np.convolve(volumes, np.ones(20) / 20, mode='full')[:len(volumes)]

                            # ATR proxy (10-period)
                            tr = np.maximum(highs - lows, np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1)))
                            atr_10 = np.convolve(tr, np.ones(10) / 10, mode='full')[:len(tr)]

                            gap_max_rows = len(bars) - 50 - max_bars
                            if gap_max_rows <= 0:
                                continue

                            X_buf = np.empty((gap_max_rows, n_base + n_gap), dtype=np.float32)
                            y_buf = np.empty(gap_max_rows, dtype=np.float32)
                            valid = 0

                            for i in range(50, len(bars) - max_bars):
                                # Check for a gap (open != previous close)
                                if i < 1:
                                    continue
                                prev_close = closes[i - 1]
                                today_open = opens[i]
                                gap_pct = abs(today_open - prev_close) / prev_close if prev_close > 0 else 0

                                # Only train on meaningful gaps (> 0.2%)
                                if gap_pct < 0.002:
                                    continue

                                # Compute gap-specific features
                                gap_feats = compute_gap_features(
                                    today_open=today_open,
                                    today_close_bar1=closes[i],
                                    today_volume_bar1=volumes[i],
                                    prev_day_open=opens[i - 1],
                                    prev_day_close=prev_close,
                                    prev_day_high=highs[i - 1],
                                    prev_day_low=lows[i - 1],
                                    avg_volume_20=avg_vol_20[i] if avg_vol_20[i] > 0 else 1.0,
                                    atr_10=atr_10[i] if atr_10[i] > 0 else 0.01,
                                    recent_high_20=float(np.max(highs[max(0, i - 20):i])),
                                    recent_low_20=float(np.min(lows[max(0, i - 20):i])),
                                )

                                # Compute target: did the gap fill?
                                target = compute_gap_fill_target(
                                    prev_close=prev_close,
                                    gap_direction=1 if today_open > prev_close else -1,
                                    intraday_highs=highs[i:i + max_bars],
                                    intraday_lows=lows[i:i + max_bars],
                                    max_bars=max_bars,
                                )

                                # Base features row
                                row_idx = i - 49
                                if row_idx < 0 or row_idx >= len(base_matrix):
                                    continue

                                X_buf[valid, :n_base] = base_matrix[row_idx]
                                X_buf[valid, n_base:] = [gap_feats.get(f, 0.0) for f in GAP_FEATURE_NAMES]
                                y_buf[valid] = float(target)
                                valid += 1

                            if valid > 0:
                                all_X.append(X_buf[:valid].copy())
                                all_y.append(y_buf[:valid].copy())

                        del batch_bars
                        gc.collect()

                    if len(all_X) < 1 or sum(len(x) for x in all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient gap fill data for {bs}: {sum(len(x) for x in all_X) if all_X else 0} samples")
                        continue

                    X = np.vstack(all_X).astype(np.float32)
                    y = np.concatenate(all_y).astype(np.float32)
                    fill_pct = float(np.mean(y)) * 100
                    del all_X, all_y
                    logger.info(f"Training {model_name}: {len(X):,} samples, gap_fill={fill_pct:.1f}%")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=max_bars)
                    model.set_db(db)
                    metrics = await _run_in_thread(model.train_from_features, X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

                    del X, y
                    gc.collect()

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
            _phase_memory_cleanup("Phase 5.5")
            status.update(phase="risk_of_ruin")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 6: Training Risk-of-Ruin Models === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.risk_of_ruin_model import RISK_MODEL_CONFIGS, RISK_FEATURE_NAMES
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer
            from concurrent.futures import ProcessPoolExecutor, as_completed

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()
            combined_names = base_names + [f"risk_{n}" for n in RISK_FEATURE_NAMES]
            n_workers = MAX_EXTRACT_WORKERS

            for bs in bar_sizes:
                risk_config = RISK_MODEL_CONFIGS.get(bs)
                if not risk_config:
                    continue

                model_name = risk_config["model_name"]
                max_bars_horizon = risk_config["max_bars"]
                status.update(current_model=model_name)

                # Pipeline resume
                if not force_retrain:
                    resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                    if resumed:
                        results["models_trained"].append({
                            "name": model_name, "accuracy": resumed["accuracy"],
                            "samples": resumed["samples"], "resumed": True,
                        })
                        results["total_samples"] += resumed["samples"]
                        status.add_completed(model_name, resumed["accuracy"])
                        continue

                try:
                    bs_config = BAR_SIZE_CONFIGS.get(bs, {})
                    symbols = await get_cached_symbols(db, bs, bs_config.get("min_bars_per_symbol", 100))
                    max_sym = max_symbols_override or bs_config.get("max_symbols", 500)
                    symbols = symbols[:max_sym]

                    min_required = 70 + max_bars_horizon
                    risk_configs_list = [(bs, max_bars_horizon)]
                    all_X = []
                    all_y = []

                    pool = ProcessPoolExecutor(max_workers=n_workers)
                    try:
                        for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                            sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                            sb_end = min(sb_start + STREAM_BATCH_SIZE, len(symbols))
                            status.update(
                                current_model=f"regime_{bs} — symbols {sb_start+1}-{sb_end}/{len(symbols)}",
                                current_phase_progress=(sb_end / len(symbols)) * 100,
                            )
                            batch_bars = await load_symbols_parallel(
                                db, sb_syms, bs, min_bars=min_required, batch_size=50,
                                max_bars=bs_config.get("max_bars", 50000)
                            )
                            if not batch_bars:
                                continue

                            worker_args = [
                                (sym, bars, risk_configs_list)
                                for sym, bars in batch_bars.items()
                                if len(bars) >= min_required
                            ]

                            chunk_results = []
                            try:
                                futures = {pool.submit(_extract_risk_worker, a): a[0] for a in worker_args}
                                for future in as_completed(futures):
                                    try:
                                        res = future.result(timeout=300)
                                        if res:
                                            chunk_results.append(res)
                                    except Exception as e:
                                        logger.warning(f"Risk worker failed for {futures[future]}: {e}")
                            except Exception as e:
                                logger.warning(f"ProcessPool failed ({e}), falling back to sequential")
                                for a in worker_args:
                                    try:
                                        res = _extract_risk_worker(a)
                                        if res:
                                            chunk_results.append(res)
                                    except Exception:
                                        pass

                            for res_dict in chunk_results:
                                for key, (X_chunk, y_chunk) in res_dict.items():
                                    all_X.append(X_chunk)
                                    all_y.append(y_chunk)

                            del batch_bars, worker_args, chunk_results
                            gc.collect()
                    finally:
                        pool.shutdown(wait=True)

                    if not all_X or sum(len(x) for x in all_X) < MIN_TRAINING_SAMPLES:
                        logger.warning(f"Insufficient risk data for {bs}")
                        continue

                    X = np.vstack(all_X).astype(np.float32)
                    y = np.concatenate(all_y).astype(np.float32)
                    del all_X, all_y
                    logger.info(f"Training {model_name}: {len(X):,} samples, stop_hit={int(np.sum(y==1))} ({float(np.mean(y))*100:.1f}%)")

                    model = TimeSeriesGBM(model_name=model_name, forecast_horizon=max_bars_horizon)
                    model.set_db(db)
                    metrics = await _run_in_thread(model.train_from_features, X, y, combined_names, num_boost_round=150, early_stopping_rounds=15)

                    del X, y
                    gc.collect()

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
            _phase_memory_cleanup("Phase 6")
            status.update(phase="regime_conditional")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 7: Training Regime-Conditional Models === [{int(_p_elapsed//60)}m elapsed]")
            from services.ai_modules.regime_conditional_model import (
                ALL_REGIMES, classify_regime_for_date, get_regime_model_name,
                MIN_REGIME_SAMPLES,
            )
            from services.ai_modules.timeseries_gbm import TimeSeriesGBM
            from services.ai_modules.timeseries_features import get_feature_engineer

            feature_engineer = get_feature_engineer()
            base_names = feature_engineer.get_feature_names()

            # Reuse shared SPY/regime data from Phase 3
            _, spy_data = await _get_shared_regime_data()

            if not spy_data or spy_data.get("closes") is None or len(spy_data.get("closes", [])) < 30:
                logger.warning("Insufficient SPY data for regime classification — skipping Phase 7")
            else:
                # Train regime-conditional variants of Generic Directional models
                for bs in bar_sizes:
                    config = BAR_SIZE_CONFIGS.get(bs)
                    if not config:
                        continue

                    base_model_name = DIRECTIONAL_MODEL_NAMES.get(bs, f"direction_predictor_{bs.replace(' ', '_')}")
                    fh = config["forecast_horizon"]

                    try:
                        max_sym = max_symbols_override or min(1500, config["max_symbols"])
                        symbols = await get_cached_symbols(db, bs, config["min_bars_per_symbol"])
                        symbols = symbols[:max_sym]

                        if not symbols:
                            continue

                        # Collect all samples and classify by regime
                        regime_samples = {r: {"X": [], "y": []} for r in ALL_REGIMES}

                        # Stream-load symbols in batches to limit RAM
                        min_required = 70 + fh

                        for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                            sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                            batch_bars = await load_symbols_parallel(
                                db, sb_syms, bs, min_bars=min_required, batch_size=50,
                                max_bars=BAR_SIZE_CONFIGS.get(bs, {}).get("max_bars", 50000)
                            )

                            for sym, bars in batch_bars.items():

                                closes = np.array([b["close"] for b in bars], dtype=np.float32)

                                # Bulk-extract base features ONCE for this symbol (NVMe cached)
                                base_matrix = cached_extract_features_bulk(feature_engineer, bars, sym, bs)
                                if base_matrix is None:
                                    continue

                                n_base = base_matrix.shape[1]
                                max_rows = len(bars) - 50 - fh
                                if max_rows <= 0:
                                    continue

                                X_buf = np.empty((max_rows, n_base), dtype=np.float32)
                                y_buf = np.empty(max_rows, dtype=np.float32)
                                r_buf = []
                                valid = 0

                                for i in range(50, len(bars) - fh):
                                    row_idx = i - 49
                                    if row_idx >= len(base_matrix):
                                        break

                                    # Classify regime at this date
                                    bar_date = str(bars[i].get("date", ""))
                                    regime = classify_regime_for_date(spy_data, bar_date)

                                    # Target: future return (binary UP/DOWN)
                                    future_return = (closes[i + fh] - closes[i]) / closes[i] if closes[i] > 0 else 0
                                    target = 1 if future_return > 0 else 0

                                    X_buf[valid] = base_matrix[row_idx]
                                    y_buf[valid] = target
                                    r_buf.append(regime)
                                    valid += 1

                                if valid > 0:
                                    X_sym = X_buf[:valid]
                                    y_sym = y_buf[:valid]
                                    for regime in ALL_REGIMES:
                                        mask = np.array([r == regime for r in r_buf], dtype=bool)
                                        if mask.any():
                                            regime_samples[regime]["X"].append(X_sym[mask].copy())
                                            regime_samples[regime]["y"].append(y_sym[mask].copy())

                            del batch_bars
                            gc.collect()

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

                            X = np.vstack(X_list).astype(np.float32)
                            y = np.concatenate(y_list).astype(np.float32)
                            regime_model_name = get_regime_model_name(base_model_name, regime)
                            status.update(current_model=regime_model_name)

                            # Pipeline resume
                            if not force_retrain:
                                resumed = _check_resume_model(db, regime_model_name, resume_max_age_hours)
                                if resumed:
                                    results["models_trained"].append({
                                        "name": regime_model_name, "accuracy": resumed["accuracy"],
                                        "samples": resumed["samples"], "resumed": True,
                                    })
                                    results["total_samples"] += resumed["samples"]
                                    status.add_completed(regime_model_name, resumed["accuracy"])
                                    del X, y
                                    gc.collect()
                                    continue

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

                            del X, y
                            gc.collect()

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
            _phase_memory_cleanup("Phase 7")
            status.update(phase="ensemble_meta")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 8: Training Ensemble Meta-Learner === [{int(_p_elapsed//60)}m elapsed]")
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
                tf_model_name = DIRECTIONAL_MODEL_NAMES.get(tf, f"direction_predictor_{tf.replace(' ', '_')}")
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

                symbols = await get_cached_symbols(db, anchor_bs, 100)
                max_sym = max_symbols_override or min(1500, BAR_SIZE_CONFIGS.get(anchor_bs, {}).get("max_symbols", 2500))
                symbols = symbols[:max_sym]

                for setup_type, ens_config in ENSEMBLE_MODEL_CONFIGS.items():
                    model_name = ens_config["model_name"]
                    status.update(current_model=model_name)

                    # Pipeline resume
                    if not force_retrain:
                        resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                        if resumed:
                            results["models_trained"].append({
                                "name": model_name, "accuracy": resumed["accuracy"],
                                "samples": resumed["samples"], "resumed": True,
                            })
                            results["total_samples"] += resumed["samples"]
                            status.add_completed(model_name, resumed["accuracy"])
                            continue

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

                        # Pre-compute column mappings from bulk features → each sub-model's expected order
                        # This avoids per-bar dict lookups (the old bottleneck)
                        sub_model_col_maps = {}
                        for tf, sm in sub_models.items():
                            if sm._feature_names and base_names:
                                base_name_to_idx = {name: idx for idx, name in enumerate(base_names)}
                                col_map = [base_name_to_idx.get(f, -1) for f in sm._feature_names]
                                sub_model_col_maps[tf] = col_map

                        setup_col_map = None
                        if setup_model and setup_model._feature_names and base_names:
                            base_name_to_idx = {name: idx for idx, name in enumerate(base_names)}
                            setup_col_map = [base_name_to_idx.get(f, -1) for f in setup_model._feature_names]

                        # Stream-load symbols in batches to limit RAM
                        min_required = 70 + anchor_fh
                        lb = feature_engineer.lookback  # 50

                        for sb_start in range(0, len(symbols), STREAM_BATCH_SIZE):
                            sb_syms = symbols[sb_start:sb_start + STREAM_BATCH_SIZE]
                            batch_bars = await load_symbols_parallel(
                                db, sb_syms, anchor_bs, min_bars=min_required, batch_size=50,
                                max_bars=BAR_SIZE_CONFIGS.get(anchor_bs, {}).get("max_bars", 50000)
                            )

                            for sym, bars in batch_bars.items():
                                closes = np.array([b["close"] for b in bars], dtype=np.float32)
                                
                                # VECTORIZED bulk feature extraction (NVMe cached)
                                bulk_features = cached_extract_features_bulk(feature_engineer, bars, sym, anchor_bs)
                                if bulk_features is None or len(bulk_features) == 0:
                                    continue
                                
                                n_usable = min(len(bulk_features), len(bars) - lb - anchor_fh)
                                if n_usable <= 0:
                                    continue
                                
                                features_matrix = bulk_features[:n_usable]  # (n_usable, n_base_features)
                                
                                # BATCH predict through all sub-models at once (replaces per-bar predict loop)
                                sub_raw_preds = {}
                                for tf, sm in sub_models.items():
                                    col_map = sub_model_col_maps.get(tf)
                                    if col_map is None:
                                        continue
                                    try:
                                        # Build feature matrix in sub-model's expected column order
                                        model_feats = np.zeros((n_usable, len(col_map)), dtype=np.float32)
                                        for ci, src_idx in enumerate(col_map):
                                            if 0 <= src_idx < features_matrix.shape[1]:
                                                model_feats[:, ci] = features_matrix[:, src_idx]
                                        
                                        sub_raw_preds[tf] = sm._model.predict(model_feats)  # Batch predict!
                                    except Exception:
                                        pass
                                
                                # Batch predict setup model
                                setup_raw_preds = None
                                if setup_model and setup_col_map:
                                    try:
                                        model_feats = np.zeros((n_usable, len(setup_col_map)), dtype=np.float32)
                                        for ci, src_idx in enumerate(setup_col_map):
                                            if 0 <= src_idx < features_matrix.shape[1]:
                                                model_feats[:, ci] = features_matrix[:, src_idx]
                                        setup_raw_preds = setup_model._model.predict(model_feats)
                                    except Exception:
                                        pass
                                
                                # Now iterate per-sample for ensemble feature assembly (fast — just dict ops)
                                for i in range(n_usable):
                                    bar_idx = lb + i - 1  # Map back to bars index
                                    if bar_idx + anchor_fh >= len(closes) or closes[bar_idx] <= 0:
                                        continue
                                    
                                    # Parse sub-model predictions for this sample
                                    predictions = {}
                                    for tf, raw_pred_batch in sub_raw_preds.items():
                                        try:
                                            raw_pred = raw_pred_batch[i] if raw_pred_batch.ndim >= 1 else raw_pred_batch
                                            
                                            if hasattr(raw_pred_batch, 'ndim') and raw_pred_batch.ndim == 2:
                                                probs = raw_pred
                                                prob_up = float(probs[2]) if len(probs) > 2 else float(probs[-1])
                                                prob_down = float(probs[0])
                                                conf = float(max(probs) - 1.0 / len(probs))
                                                direction = "up" if np.argmax(probs) == 2 else (
                                                    "down" if np.argmax(probs) == 0 else "flat"
                                                )
                                            else:
                                                prob_up = float(raw_pred) if np.isscalar(raw_pred) else float(raw_pred)
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
                                    
                                    # Parse setup model prediction for this sample
                                    setup_preds = []
                                    if setup_raw_preds is not None:
                                        try:
                                            raw_pred = setup_raw_preds[i] if setup_raw_preds.ndim >= 1 else setup_raw_preds
                                            
                                            if hasattr(setup_raw_preds, 'ndim') and setup_raw_preds.ndim == 2:
                                                probs = raw_pred
                                                prob_up = float(probs[2]) if len(probs) > 2 else float(probs[-1])
                                                prob_down = float(probs[0])
                                                conf = float(max(probs) - 1.0 / len(probs))
                                                direction = "up" if np.argmax(probs) == 2 else (
                                                    "down" if np.argmax(probs) == 0 else "flat"
                                                )
                                            else:
                                                prob_up = float(raw_pred) if np.isscalar(raw_pred) else float(raw_pred)
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
                                        (closes[bar_idx + anchor_fh] - closes[bar_idx]) / closes[bar_idx]
                                    )
                                    if future_return > 0.003:
                                        target = 2  # UP
                                    elif future_return < -0.003:
                                        target = 0  # DOWN
                                    else:
                                        target = 1  # FLAT
                                    
                                    all_X.append(feat_vec)
                                    all_y.append(target)
                                
                                del bulk_features, features_matrix

                            del batch_bars
                            gc.collect()

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

                        del all_X, all_y, X, y
                        gc.collect()

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
            _phase_memory_cleanup("Phase 8")
            status.update(phase="cnn_patterns")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 9: Training CNN Chart Pattern Models === [{int(_p_elapsed//60)}m elapsed]")
            try:
                from services.ai_modules.cnn_training_pipeline import run_cnn_training

                async def cnn_progress(pct, msg):
                    status.update(current_model=msg)

                cnn_result = await asyncio.wait_for(
                    run_cnn_training(
                        db=db,
                        setup_type="ALL",
                        progress_callback=cnn_progress,
                    ),
                    timeout=7200  # 2 hours max for CNN training
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

            except asyncio.TimeoutError:
                logger.error("[CNN] Phase 9 TIMED OUT after 2 hours — skipping")
                results["cnn_training"] = {"error": "Timed out (>2 hours)"}
            except Exception as e:
                logger.error(f"CNN phase failed: {e}", exc_info=True)
                results["cnn_training"] = {"error": str(e)}

        # ── Phase 11: Deep Learning Models (VAE Regime + TFT + CNN-LSTM) ──
        if "dl" in phases:
            _phase_memory_cleanup("Phase 9")
            status.update(phase="deep_learning")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 11: Training Deep Learning Models === [{int(_p_elapsed//60)}m elapsed]")

            dl_models_config = [
                {
                    "name": "vae_regime_detector",
                    "class": "VAERegimeModel",
                    "module": "services.ai_modules.vae_regime",
                    "kwargs": {"epochs": 100, "batch_size": 256},
                },
                {
                    "name": "tft_multi_timeframe",
                    "class": "TFTModel",
                    "module": "services.ai_modules.temporal_fusion_transformer",
                    "kwargs": {"max_symbols": 500, "epochs": 50, "batch_size": 512},
                },
                {
                    "name": "cnn_lstm_chart",
                    "class": "CNNLSTMModel",
                    "module": "services.ai_modules.cnn_lstm_model",
                    "kwargs": {"max_symbols": 200, "epochs": 30, "batch_size": 256},
                },
            ]

            for dl_cfg in dl_models_config:
                model_name = dl_cfg["name"]
                status.update(current_model=model_name)

                # Pipeline resume
                if not force_retrain:
                    resumed = _check_resume_model(db, model_name, resume_max_age_hours)
                    if resumed:
                        results["models_trained"].append({
                            "name": model_name, "accuracy": resumed["accuracy"],
                            "samples": resumed["samples"], "resumed": True, "type": "dl",
                        })
                        results["total_samples"] += resumed["samples"]
                        status.add_completed(model_name, resumed["accuracy"])
                        continue

                try:
                    import importlib
                    mod = importlib.import_module(dl_cfg["module"])
                    ModelClass = getattr(mod, dl_cfg["class"])
                    dl_instance = ModelClass()
                    logger.info(f"[DL] Training {model_name}...")
                    dl_result = await asyncio.wait_for(
                        dl_instance.train(db=db, **dl_cfg["kwargs"]),
                        timeout=7200  # 2 hours max per DL model
                    )

                    if dl_result.get("success"):
                        acc = dl_result.get("accuracy", dl_result.get("reconstruction_error", 0))
                        results["models_trained"].append({
                            "name": model_name, "accuracy": acc, "type": "dl"
                        })
                        status.add_completed(model_name, acc)
                        logger.info(f"[DL] {model_name} trained successfully")
                    else:
                        error = dl_result.get("error", "Unknown DL training error")
                        results["models_failed"].append({
                            "name": model_name, "reason": error, "type": "dl"
                        })
                        status.add_error(model_name, error)
                        logger.warning(f"[DL] {model_name} failed: {error}")

                    del dl_instance
                    gc.collect()
                    # Release CUDA memory between DL models to prevent OOM
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                            logger.info(f"[DL] Released CUDA memory after {model_name}")
                    except Exception:
                        pass

                except asyncio.TimeoutError:
                    logger.error(f"[DL] {model_name} TIMED OUT after 2 hours — skipping")
                    results["models_failed"].append({
                        "name": model_name, "reason": "Timed out (>2 hours)", "type": "dl"
                    })
                    status.add_error(model_name, "Timed out (>2 hours)")
                    # Still clean up GPU memory
                    try:
                        del dl_instance
                        gc.collect()
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"[DL] {model_name} error: {e}", exc_info=True)
                    results["models_failed"].append({
                        "name": model_name, "reason": str(e), "type": "dl"
                    })
                    status.add_error(model_name, str(e))

        # ── Phase 12: FinBERT Sentiment Analysis ──
        if "finbert" in phases:
            _phase_memory_cleanup("Phase 11")
            status.update(phase="finbert_sentiment")
            _p_elapsed = _time.monotonic() - _pipeline_start
            logger.info(f"=== Phase 12: FinBERT Sentiment Analysis === [{int(_p_elapsed//60)}m elapsed]")
            status.update(current_model="finbert_news_collection")
            try:
                from services.ai_modules.finbert_sentiment import FinnhubNewsCollector, FinBERTSentiment

                # Step 1: Collect news
                collector = FinnhubNewsCollector(db=db)
                logger.info("[FINBERT] Collecting news from Finnhub...")
                
                # Reuse cached symbol list from earlier phases (no slow 178M doc aggregation)
                symbols = await get_cached_symbols(db, "1 day", min_bars=50, max_symbols=100)
                
                if symbols:
                    collect_result = await collector.collect_news(symbols=symbols, days_back=30)
                    new_articles = collect_result.get("new_articles_stored", 0)
                    logger.info(f"[FINBERT] Collected {new_articles} new articles")
                else:
                    logger.warning("[FINBERT] No symbols found for news collection")

                # Step 2: Score unscored articles
                status.update(current_model="finbert_scoring")
                scorer = FinBERTSentiment(db=db)
                logger.info("[FINBERT] Scoring articles...")
                score_result = await scorer.score_unscored_articles(batch_size=64, max_articles=10000)
                scored = score_result.get("scored", 0)
                logger.info(f"[FINBERT] Scored {scored} articles")

                results["models_trained"].append({
                    "name": "finbert_sentiment", "accuracy": scored, "type": "finbert"
                })
                status.add_completed("finbert_sentiment", 1.0)

            except Exception as e:
                logger.error(f"[FINBERT] Phase failed: {e}", exc_info=True)
                results["models_failed"].append({
                    "name": "finbert_sentiment", "reason": str(e), "type": "finbert"
                })
                status.add_error("finbert_sentiment", str(e))

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 13: Auto-Validation (5-Phase pipeline on Trade Signal Generators)
        # ══════════════════════════════════════════════════════════════════════
        if "validate" in phases and len(results["models_trained"]) > 0:
            phase_key = "auto_validation"
            status.start_phase(phase_key, 34)  # 17 long + 17 short setup types
            status.update(phase=phase_key, current_model="Initializing validation...")
            logger.info("Phase 13: Starting Auto-Validation of Trade Signal Generators")

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
                    logger.info(f"[VALIDATE] Phase 13: Validating {setup_type}/{bar_size}")

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
                    f"Phase 13 Auto-Validation complete: {validated_count} validated, "
                    f"{promoted_count} promoted, {rejected_count} rejected"
                )

            except ImportError as e:
                logger.error(f"Phase 13 skipped — missing dependencies: {e}")
                status.end_phase(phase_key)
                results["validation_summary"] = {"error": f"Dependencies missing: {e}"}
            except Exception as e:
                logger.error(f"Phase 13 Auto-Validation error: {e}", exc_info=True)
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
        _total_elapsed = _time.monotonic() - _pipeline_start
        _total_hrs = int(_total_elapsed // 3600)
        _total_min = int((_total_elapsed % 3600) // 60)
        logger.info(
            f"Training pipeline complete: {len(results['models_trained'])} trained, "
            f"{len(results['models_failed'])} failed, {results['total_samples']:,} total samples "
            f"[Total time: {_total_hrs}h{_total_min:02d}m]"
        )

    except Exception as e:
        logger.error(f"Training pipeline error: {e}")
        results["error"] = str(e)
        status.update(phase="error", current_model=str(e))
    finally:
        clear_symbol_cache()
        # Keep NVMe cache on disk (useful for debugging) — it gets cleared on next run start

    return results
