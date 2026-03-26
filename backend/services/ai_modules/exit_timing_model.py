"""
Exit Timing Model

Predicts the optimal holding period for a trade — how many bars until
the move is exhausted (Maximum Favorable Excursion peak).

Instead of just predicting direction (UP/DOWN), this model predicts
WHEN to exit. It answers: "If this is a good entry, how long should
I hold before the edge decays?"

Target: Regression — bars_to_MFE (bars until max favorable excursion)
  For UP predictions: bars until price reaches its peak before declining
  For DOWN predictions: bars until price reaches its trough before rising

Features: Same base features + regime + MTF + 7 exit-specific features:
  mfe_10_pct       — MFE as % of price over next 10 bars (from training data)
  mae_10_pct       — MAE as % of price over next 10 bars (from training data)
  mfe_mae_ratio    — MFE/MAE ratio (reward/risk)
  streak_length    — Current directional streak (consecutive up/down bars)
  exhaustion_rsi   — How close RSI is to extreme (distance from 70 or 30)
  momentum_decay   — Rate of momentum decline (return_1 vs return_3)
  volume_climax    — Whether volume is spiking relative to recent average

Model per setup type (not per timeframe), since exit timing is more
about the trade structure than the bar size.
"""

import logging
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

EXIT_FEATURE_NAMES = [
    "mfe_10_pct",
    "mae_10_pct",
    "mfe_mae_ratio",
    "streak_length",
    "exhaustion_rsi",
    "momentum_decay",
    "volume_climax",
]


def compute_exit_features(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    direction: str = "up",
) -> Dict[str, float]:
    """
    Compute exit-timing features from OHLCV (most-recent-first).
    Needs at least 20 bars.
    """
    feats = {}
    n = len(closes)

    if n < 20:
        return {name: 0.0 for name in EXIT_FEATURE_NAMES}

    current = closes[0]

    # 1-2. MFE and MAE over last 10 bars (as % of current price)
    if n >= 11 and current > 0:
        window_highs = highs[:10]
        window_lows = lows[:10]
        if direction == "up":
            mfe = (np.max(window_highs) - current) / current
            mae = (current - np.min(window_lows)) / current
        else:
            mfe = (current - np.min(window_lows)) / current
            mae = (np.max(window_highs) - current) / current
        feats["mfe_10_pct"] = max(0, mfe)
        feats["mae_10_pct"] = max(0, mae)
    else:
        feats["mfe_10_pct"] = 0.0
        feats["mae_10_pct"] = 0.0

    # 3. MFE/MAE ratio (reward/risk from recent bars)
    feats["mfe_mae_ratio"] = (
        feats["mfe_10_pct"] / feats["mae_10_pct"]
        if feats["mae_10_pct"] > 0 else 1.0
    )

    # 4. Streak length: consecutive bars in same direction
    streak = 0
    for i in range(min(n - 1, 20)):
        if closes[i] > closes[i + 1]:
            if direction == "up":
                streak += 1
            else:
                break
        elif closes[i] < closes[i + 1]:
            if direction == "down":
                streak += 1
            else:
                break
        else:
            break
    feats["streak_length"] = streak / 10.0  # Normalized

    # 5. Exhaustion RSI: distance from overbought/oversold extremes
    if n >= 15:
        c = closes[:15][::-1]
        deltas = np.diff(c)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # Distance from exhaustion zone
        if direction == "up":
            feats["exhaustion_rsi"] = max(0, (rsi - 70) / 30)  # 0 at RSI=70, 1 at RSI=100
        else:
            feats["exhaustion_rsi"] = max(0, (30 - rsi) / 30)  # 0 at RSI=30, 1 at RSI=0
    else:
        feats["exhaustion_rsi"] = 0.0

    # 6. Momentum decay: how fast is the move losing steam?
    if n >= 4 and closes[1] > 0 and closes[3] > 0:
        ret_1 = abs((closes[0] - closes[1]) / closes[1])
        ret_3 = abs((closes[0] - closes[3]) / closes[3]) / 3  # Per-bar average
        feats["momentum_decay"] = (ret_1 / ret_3) - 1.0 if ret_3 > 0 else 0.0
    else:
        feats["momentum_decay"] = 0.0

    # 7. Volume climax: spike in volume
    if len(volumes) >= 20:
        recent_vol = volumes[0]
        avg_vol_20 = np.mean(volumes[:20])
        feats["volume_climax"] = (recent_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0
    else:
        feats["volume_climax"] = 1.0

    # Sanitize
    for key in feats:
        val = feats[key]
        if np.isnan(val) or np.isinf(val):
            feats[key] = 0.0

    return feats


def compute_exit_target(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    current_idx: int,
    max_horizon: int = 30,
    direction: str = "up",
) -> Optional[int]:
    """
    Compute exit target: bars until Maximum Favorable Excursion (MFE) peak.

    closes/highs/lows: full arrays, chronological (oldest first)
    current_idx: index of the current bar (entry point)
    direction: "up" for longs, "down" for shorts

    Returns: number of bars from entry to MFE peak (1 to max_horizon),
             or None if insufficient forward data.
    """
    n = len(closes)
    end = min(current_idx + max_horizon + 1, n)
    if end <= current_idx + 1:
        return None

    entry_price = closes[current_idx]
    if entry_price <= 0:
        return None

    forward_highs = highs[current_idx + 1: end]
    forward_lows = lows[current_idx + 1: end]

    if len(forward_highs) == 0:
        return None

    if direction == "up":
        # MFE = highest high reached
        mfe_idx = np.argmax(forward_highs)
    else:
        # MFE = lowest low reached
        mfe_idx = np.argmin(forward_lows)

    return int(mfe_idx) + 1  # 1-indexed (bars after entry)


# Configurable per setup type
EXIT_MODEL_CONFIGS = {
    "SCALP":              {"max_horizon": 12, "model_name": "exit_timing_scalp"},
    "ORB":                {"max_horizon": 24, "model_name": "exit_timing_orb"},
    "GAP_AND_GO":         {"max_horizon": 24, "model_name": "exit_timing_gap"},
    "VWAP":               {"max_horizon": 24, "model_name": "exit_timing_vwap"},
    "BREAKOUT":           {"max_horizon": 30, "model_name": "exit_timing_breakout"},
    "RANGE":              {"max_horizon": 20, "model_name": "exit_timing_range"},
    "MEAN_REVERSION":     {"max_horizon": 20, "model_name": "exit_timing_meanrev"},
    "REVERSAL":           {"max_horizon": 30, "model_name": "exit_timing_reversal"},
    "TREND_CONTINUATION": {"max_horizon": 30, "model_name": "exit_timing_trend"},
    "MOMENTUM":           {"max_horizon": 30, "model_name": "exit_timing_momentum"},
}
