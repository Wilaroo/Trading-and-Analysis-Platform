"""
Advanced Target Variable System

Replaces the simple binary UP/DOWN classification with richer target
variables that preserve more information from the price data.

Target Types:

1. REGRESSION — Predict actual forward return magnitude
   - More information-rich than classification
   - Allows post-hoc thresholding (adjust signal sensitivity without retraining)
   - LightGBM regression output → threshold into UP/FLAT/DOWN

2. RISK_ADJUSTED (R-Multiple) — Forward return normalized by ATR
   - return_in_R = forward_return / ATR
   - Makes targets comparable across different volatility regimes
   - A 2% move in a low-vol stock is very different from 2% in a high-vol stock
   - Directly maps to position sizing decisions

3. ASYMMETRIC_REGIME — Different thresholds per market regime
   - Bull regime: lower bar for longs (0.3% threshold) vs shorts (0.8%)
   - Bear regime: lower bar for shorts (0.3%) vs longs (0.8%)
   - Range regime: symmetric thresholds (0.5%)
   - High-vol regime: wider thresholds (1.0%) to filter noise

Usage in training pipeline:
  target_config = get_target_config("regression", bar_size="5 mins")
  target_value = compute_advanced_target(
      closes, current_idx, forecast_horizon, target_config, regime="bull_trend"
  )
"""

import logging
import numpy as np
from typing import Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TargetConfig:
    """Configuration for target variable computation."""
    target_type: str  # "classification", "regression", "r_multiple", "asymmetric"
    forecast_horizon: int = 5
    # Classification thresholds
    up_threshold: float = 0.005  # 0.5% default
    down_threshold: float = -0.005
    # R-multiple settings
    atr_period: int = 10
    # Asymmetric regime thresholds
    regime_thresholds: Optional[Dict[str, Dict[str, float]]] = None
    # Number of output classes for classification
    num_classes: int = 2  # 2=binary, 3=three-class


# Default asymmetric thresholds per regime
DEFAULT_REGIME_THRESHOLDS = {
    "bull_trend": {
        "up_threshold": 0.003,    # Lower bar for longs in bull market
        "down_threshold": -0.008,  # Higher bar for shorts (don't short easily)
        "flat_zone": 0.003,        # Narrow flat zone
    },
    "bear_trend": {
        "up_threshold": 0.008,    # Higher bar for longs (don't buy easily)
        "down_threshold": -0.003,  # Lower bar for shorts in bear market
        "flat_zone": 0.003,
    },
    "range_bound": {
        "up_threshold": 0.005,    # Symmetric in range
        "down_threshold": -0.005,
        "flat_zone": 0.005,
    },
    "high_vol": {
        "up_threshold": 0.010,    # Wider thresholds in high vol (more noise)
        "down_threshold": -0.010,
        "flat_zone": 0.010,
    },
}

# Preset target configs per use case
TARGET_PRESETS = {
    "classification_binary": TargetConfig(
        target_type="classification",
        num_classes=2,
        up_threshold=0.005,
        down_threshold=-0.005,
    ),
    "classification_3class": TargetConfig(
        target_type="classification",
        num_classes=3,
        up_threshold=0.005,
        down_threshold=-0.005,
    ),
    "regression": TargetConfig(
        target_type="regression",
    ),
    "r_multiple": TargetConfig(
        target_type="r_multiple",
        atr_period=10,
    ),
    "asymmetric": TargetConfig(
        target_type="asymmetric",
        num_classes=3,
        regime_thresholds=DEFAULT_REGIME_THRESHOLDS,
    ),
}


def compute_forward_return(
    closes: np.ndarray,
    current_idx: int,
    forecast_horizon: int,
) -> Optional[float]:
    """
    Compute raw forward return.
    closes: chronological array (oldest first)
    Returns: (future_price - current_price) / current_price
    """
    n = len(closes)
    if current_idx + forecast_horizon >= n:
        return None
    current = closes[current_idx]
    future = closes[current_idx + forecast_horizon]
    if current <= 0:
        return None
    return (future - current) / current


def compute_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    current_idx: int,
    period: int = 10,
) -> float:
    """
    Compute ATR at current_idx.
    Arrays: chronological (oldest first)
    """
    if current_idx < period:
        return 0.01  # Fallback

    atr_vals = []
    for i in range(current_idx - period, current_idx):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]) if i > 0 else highs[i] - lows[i],
            abs(lows[i] - closes[i - 1]) if i > 0 else highs[i] - lows[i],
        )
        atr_vals.append(tr)

    return np.mean(atr_vals) if atr_vals else 0.01


def compute_r_multiple(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    current_idx: int,
    forecast_horizon: int,
    atr_period: int = 10,
) -> Optional[float]:
    """
    Compute forward return as R-multiple (return / ATR).

    A +2R means the stock moved 2x its ATR in the favorable direction.
    This normalizes returns across volatility regimes.
    """
    forward_return = compute_forward_return(closes, current_idx, forecast_horizon)
    if forward_return is None:
        return None

    atr = compute_atr(highs, lows, closes, current_idx, atr_period)
    if atr <= 0:
        return None

    current_price = closes[current_idx]
    if current_price <= 0:
        return None

    # Convert return to R-multiple
    return_in_dollars = forward_return * current_price
    return return_in_dollars / atr


def compute_advanced_target(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    current_idx: int,
    config: TargetConfig,
    regime: str = "range_bound",
) -> Optional[Any]:
    """
    Compute the target variable based on the configuration.

    Returns:
      - For "regression": float (raw forward return)
      - For "r_multiple": float (R-multiple)
      - For "classification": int (0=DOWN, 1=UP or 0=DOWN, 1=FLAT, 2=UP)
      - For "asymmetric": int (0=DOWN, 1=FLAT, 2=UP with regime-adjusted thresholds)
      - None if insufficient data
    """
    forecast_horizon = config.forecast_horizon

    if config.target_type == "regression":
        return compute_forward_return(closes, current_idx, forecast_horizon)

    elif config.target_type == "r_multiple":
        return compute_r_multiple(
            closes, highs, lows, current_idx,
            forecast_horizon, config.atr_period,
        )

    elif config.target_type == "classification":
        ret = compute_forward_return(closes, current_idx, forecast_horizon)
        if ret is None:
            return None

        if config.num_classes == 2:
            return 1 if ret > config.up_threshold else 0
        else:  # 3-class
            if ret > config.up_threshold:
                return 2  # UP
            elif ret < config.down_threshold:
                return 0  # DOWN
            else:
                return 1  # FLAT

    elif config.target_type == "asymmetric":
        ret = compute_forward_return(closes, current_idx, forecast_horizon)
        if ret is None:
            return None

        # Get regime-specific thresholds
        thresholds = (config.regime_thresholds or DEFAULT_REGIME_THRESHOLDS).get(
            regime,
            DEFAULT_REGIME_THRESHOLDS["range_bound"],
        )

        up_thresh = thresholds["up_threshold"]
        down_thresh = thresholds["down_threshold"]

        if ret > up_thresh:
            return 2  # UP
        elif ret < down_thresh:
            return 0  # DOWN
        else:
            return 1  # FLAT

    return None


def get_target_config(preset: str, **overrides) -> TargetConfig:
    """Get a target configuration by preset name with optional overrides."""
    if preset not in TARGET_PRESETS:
        logger.warning(f"Unknown target preset '{preset}', using classification_binary")
        preset = "classification_binary"

    config = TARGET_PRESETS[preset]

    # Apply overrides
    if "forecast_horizon" in overrides:
        config = TargetConfig(**{**config.__dict__, **overrides})

    return config


# Per-bar-size default forecast horizons
BAR_SIZE_FORECAST_HORIZONS = {
    "1 min":   30,
    "5 mins":  12,
    "15 mins": 8,
    "30 mins": 6,
    "1 hour":  6,
    "1 day":   5,
    "1 week":  4,
}


def get_target_config_for_bar_size(
    preset: str,
    bar_size: str,
) -> TargetConfig:
    """Get target config with bar-size-appropriate forecast horizon."""
    fh = BAR_SIZE_FORECAST_HORIZONS.get(bar_size, 5)
    config = get_target_config(preset)
    config.forecast_horizon = fh
    return config
