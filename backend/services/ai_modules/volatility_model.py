"""
Volatility Prediction Model

Predicts whether volatility over the next N bars will be above or below
the recent average. Critical for:
  - Dynamic position sizing (smaller size in high-vol, larger in low-vol)
  - Stop distance calibration (wider stops in high-vol regimes)
  - Trade filtering (avoid entries just before vol spikes)

Target: Binary — HIGH_VOL (1) vs LOW_VOL (0)
  HIGH_VOL = next-N-bar realized vol > trailing 20-bar vol
  LOW_VOL  = next-N-bar realized vol <= trailing 20-bar vol

Features: Same base 46 + regime 24 + MTF 8 + 6 vol-specific features:
  vol_rank_20      — Current vol percentile over 20 bars
  vol_rank_50      — Current vol percentile over 50 bars
  vol_acceleration — Rate of change in vol (5-bar vs 10-bar)
  range_expansion  — Recent range expansion/contraction ratio
  gap_frequency    — How often gaps occurred in last 10 bars
  volume_vol_corr  — Correlation between volume and price volatility

Model stored in: volatility_models collection
"""

import logging
import numpy as np
import pickle
import base64
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)

VOL_FEATURE_NAMES = [
    "vol_rank_20",
    "vol_rank_50",
    "vol_acceleration",
    "range_expansion",
    "gap_frequency",
    "volume_vol_corr",
]


def compute_vol_specific_features(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    opens: np.ndarray,
    volumes: np.ndarray,
) -> Dict[str, float]:
    """
    Compute volatility-specific features from OHLCV arrays (most-recent-first).
    Needs at least 50 bars.
    """
    feats = {}
    n = len(closes)

    if n < 50:
        return {name: 0.0 for name in VOL_FEATURE_NAMES}

    # Helper: compute realized vol (std of returns) for a window
    def _realized_vol(c, period):
        if len(c) < period + 1:
            return 0.0
        rets = np.diff(c[:period + 1]) / c[1:period + 1]
        rets = rets[np.isfinite(rets)]
        return float(np.std(rets)) if len(rets) > 0 else 0.0

    current_vol = _realized_vol(closes, 10)

    # 1. Vol rank over 20 bars: what percentile is current vol?
    vol_history_20 = [_realized_vol(closes[i:], 10) for i in range(min(20, n - 10))]
    if vol_history_20:
        feats["vol_rank_20"] = sum(1 for v in vol_history_20 if v <= current_vol) / len(vol_history_20)
    else:
        feats["vol_rank_20"] = 0.5

    # 2. Vol rank over 50 bars
    vol_history_50 = [_realized_vol(closes[i:], 10) for i in range(min(50, n - 10))]
    if vol_history_50:
        feats["vol_rank_50"] = sum(1 for v in vol_history_50 if v <= current_vol) / len(vol_history_50)
    else:
        feats["vol_rank_50"] = 0.5

    # 3. Vol acceleration: 5-bar vol vs 10-bar vol
    vol_5 = _realized_vol(closes, 5)
    vol_10 = _realized_vol(closes, 10)
    feats["vol_acceleration"] = (vol_5 / vol_10 - 1.0) if vol_10 > 0 else 0.0

    # 4. Range expansion: recent 5-bar avg range vs 20-bar avg range
    ranges = highs[:20] - lows[:20]
    if len(ranges) >= 20:
        recent_range = np.mean(ranges[:5])
        avg_range = np.mean(ranges[:20])
        feats["range_expansion"] = (recent_range / avg_range) if avg_range > 0 else 1.0
    else:
        feats["range_expansion"] = 1.0

    # 5. Gap frequency: proportion of last 10 bars with gaps > 0.5%
    gap_count = 0
    for i in range(min(10, n - 1)):
        if opens is not None and closes[i + 1] > 0:
            gap = abs(opens[i] - closes[i + 1]) / closes[i + 1]
            if gap > 0.005:
                gap_count += 1
    feats["gap_frequency"] = gap_count / min(10, n - 1)

    # 6. Volume-volatility correlation: are volume spikes predicting vol spikes?
    if n >= 20:
        vol_series = [abs(closes[i] - closes[i + 1]) / closes[i + 1]
                      for i in range(min(20, n - 1)) if closes[i + 1] > 0]
        vol_arr = np.array(vol_series[:min(len(vol_series), len(volumes[:20]))])
        vol_v = volumes[:len(vol_arr)]
        if len(vol_arr) >= 5 and np.std(vol_arr) > 0 and np.std(vol_v) > 0:
            feats["volume_vol_corr"] = float(np.corrcoef(vol_arr, vol_v)[0, 1])
            if np.isnan(feats["volume_vol_corr"]):
                feats["volume_vol_corr"] = 0.0
        else:
            feats["volume_vol_corr"] = 0.0
    else:
        feats["volume_vol_corr"] = 0.0

    # Sanitize
    for key in feats:
        if np.isnan(feats[key]) or np.isinf(feats[key]):
            feats[key] = 0.0

    return feats


def compute_vol_target(
    closes: np.ndarray,
    forecast_horizon: int,
    current_idx: int,
) -> Optional[int]:
    """
    Compute volatility target for a sample.

    Returns 1 (HIGH_VOL) if forward realized vol > trailing 20-bar vol, else 0.
    closes: full close array (chronological, oldest first)
    current_idx: index of the current bar (end of lookback window)
    """
    n = len(closes)
    if current_idx + forecast_horizon >= n or current_idx < 20:
        return None

    # Trailing 20-bar realized vol
    trailing = closes[current_idx - 19: current_idx + 1]
    trailing_rets = np.diff(trailing) / trailing[:-1]
    trailing_rets = trailing_rets[np.isfinite(trailing_rets)]
    trailing_vol = np.std(trailing_rets) if len(trailing_rets) > 1 else 0

    # Forward realized vol
    forward = closes[current_idx: current_idx + forecast_horizon + 1]
    forward_rets = np.diff(forward) / forward[:-1]
    forward_rets = forward_rets[np.isfinite(forward_rets)]
    forward_vol = np.std(forward_rets) if len(forward_rets) > 1 else 0

    if trailing_vol == 0:
        return 0

    return 1 if forward_vol > trailing_vol else 0


# Model configuration per timeframe
VOL_MODEL_CONFIGS = {
    "1 min":  {"forecast_horizon": 30, "model_name": "vol_predictor_1min"},
    "5 mins": {"forecast_horizon": 12, "model_name": "vol_predictor_5min"},
    "15 mins": {"forecast_horizon": 8, "model_name": "vol_predictor_15min"},
    "30 mins": {"forecast_horizon": 6, "model_name": "vol_predictor_30min"},
    "1 hour": {"forecast_horizon": 6, "model_name": "vol_predictor_1hour"},
    "1 day":  {"forecast_horizon": 5, "model_name": "vol_predictor_daily"},
    "1 week": {"forecast_horizon": 4, "model_name": "vol_predictor_weekly"},
}
