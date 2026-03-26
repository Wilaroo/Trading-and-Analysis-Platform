"""
Risk-of-Ruin Predictor

Predicts the probability of a trade hitting its stop-loss within N bars.
This is the inverse of a directional model — instead of asking "will it
go up?", it asks "how likely is it to go AGAINST me by X%?"

Critical for:
  - Entry timing: Wait for a better entry if risk-of-ruin is high
  - Position sizing: Reduce size when stop-hit probability is elevated
  - Trade filtering: Skip setups with >60% stop-hit probability

Features (8 risk-specific features):
  risk_atr_stop_distance    — Stop distance in ATR multiples
  risk_vol_regime           — Current vol regime (high vol = more risk)
  risk_adverse_streak       — Recent adverse price action (bars against you)
  risk_support_distance     — Distance to nearest support/resistance level
  risk_mean_reversion_pressure — How stretched is price from mean?
  risk_volume_exhaustion    — Is buying/selling volume drying up?
  risk_time_of_day          — Intraday risk varies by session (lunch = choppy)
  risk_recent_stop_runs     — How many stop-like wicks in recent bars?

Target: STOP_HIT (1) vs SURVIVED (0)
  Using 1.5x ATR as the default stop distance.
  STOP_HIT: Price moves 1.5x ATR against entry direction within N bars.
"""

import logging
import numpy as np
from typing import Dict, Optional

logger = logging.getLogger(__name__)

RISK_FEATURE_NAMES = [
    "risk_atr_stop_distance",
    "risk_vol_regime",
    "risk_adverse_streak",
    "risk_support_distance",
    "risk_mean_reversion_pressure",
    "risk_volume_exhaustion",
    "risk_time_of_day",
    "risk_recent_stop_runs",
]

# Default stop distance in ATR multiples
DEFAULT_STOP_ATR = 1.5


def compute_risk_features(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    direction: str = "up",
    stop_atr_multiple: float = DEFAULT_STOP_ATR,
    hour_of_day: float = 12.0,
) -> Dict[str, float]:
    """
    Compute risk-of-ruin features from OHLCV (most-recent-first).
    Needs at least 25 bars.
    """
    feats = {}
    n = len(closes)

    if n < 25:
        return {name: 0.0 for name in RISK_FEATURE_NAMES}

    current = closes[0]

    # ATR calculation
    atr_vals = []
    for i in range(min(10, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]),
            abs(lows[i] - closes[i + 1]),
        )
        atr_vals.append(tr)
    atr_10 = np.mean(atr_vals) if atr_vals else 0.01

    # 1. Stop distance in ATR multiples (how tight is the stop?)
    feats["risk_atr_stop_distance"] = stop_atr_multiple

    # 2. Vol regime (current ATR vs 20-bar ATR)
    atr_20_vals = []
    for i in range(min(20, n - 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i + 1]),
            abs(lows[i] - closes[i + 1]),
        )
        atr_20_vals.append(tr)
    atr_20 = np.mean(atr_20_vals) if atr_20_vals else atr_10
    feats["risk_vol_regime"] = atr_10 / atr_20 if atr_20 > 0 else 1.0

    # 3. Adverse streak: consecutive bars moving against the direction
    adverse_count = 0
    for i in range(min(10, n - 1)):
        if direction == "up" and closes[i] < closes[i + 1]:
            adverse_count += 1
        elif direction == "down" and closes[i] > closes[i + 1]:
            adverse_count += 1
        else:
            break
    feats["risk_adverse_streak"] = adverse_count / 10.0

    # 4. Distance to support/resistance
    if direction == "up":
        # Distance to nearest low (support)
        recent_lows = lows[:20]
        nearest_support = np.min(recent_lows)
        feats["risk_support_distance"] = (current - nearest_support) / atr_10 if atr_10 > 0 else 0
    else:
        # Distance to nearest high (resistance)
        recent_highs = highs[:20]
        nearest_resistance = np.max(recent_highs)
        feats["risk_support_distance"] = (nearest_resistance - current) / atr_10 if atr_10 > 0 else 0

    # 5. Mean reversion pressure (distance from 20-bar SMA in ATR units)
    sma_20 = np.mean(closes[:20])
    feats["risk_mean_reversion_pressure"] = abs(current - sma_20) / atr_10 if atr_10 > 0 else 0

    # 6. Volume exhaustion (is volume declining?)
    if len(volumes) >= 10:
        recent_vol = np.mean(volumes[:3])
        older_vol = np.mean(volumes[3:10])
        feats["risk_volume_exhaustion"] = 1.0 - (recent_vol / older_vol) if older_vol > 0 else 0.0
    else:
        feats["risk_volume_exhaustion"] = 0.0

    # 7. Time of day risk (normalized 0-1, higher around lunch = choppier)
    # Lunch hours (11:30-1:30) have wider spreads and more stop runs
    feats["risk_time_of_day"] = max(0, 1.0 - abs(hour_of_day - 12.5) / 4.0)

    # 8. Recent stop runs (wicks that exceed body by 2x = stop run signatures)
    stop_run_count = 0
    for i in range(min(10, n)):
        body = abs(closes[i] - (closes[i + 1] if i + 1 < n else closes[i]))
        if body > 0:
            upper_wick = highs[i] - max(closes[i], closes[i + 1] if i + 1 < n else closes[i])
            lower_wick = min(closes[i], closes[i + 1] if i + 1 < n else closes[i]) - lows[i]
            if direction == "up" and lower_wick > 2 * body:
                stop_run_count += 1
            elif direction == "down" and upper_wick > 2 * body:
                stop_run_count += 1
    feats["risk_recent_stop_runs"] = stop_run_count / 10.0

    # Sanitize
    for key in feats:
        val = feats[key]
        if np.isnan(val) or np.isinf(val):
            feats[key] = 0.0

    return feats


def compute_risk_target(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    current_idx: int,
    atr: float,
    direction: str = "up",
    stop_atr_multiple: float = DEFAULT_STOP_ATR,
    max_bars: int = 20,
) -> Optional[int]:
    """
    Compute risk-of-ruin target.

    Returns 1 (STOP_HIT) if price moves stop_atr_multiple * ATR against
    direction within max_bars, else 0 (SURVIVED).

    closes/highs/lows: chronological (oldest first)
    """
    n = len(closes)
    if current_idx + 1 >= n or atr <= 0:
        return None

    entry = closes[current_idx]
    stop_distance = stop_atr_multiple * atr

    end_idx = min(current_idx + max_bars + 1, n)

    for i in range(current_idx + 1, end_idx):
        if direction == "up":
            # Stop hit if price drops below entry - stop_distance
            if lows[i] <= entry - stop_distance:
                return 1
        else:
            # Stop hit if price rises above entry + stop_distance
            if highs[i] >= entry + stop_distance:
                return 1

    return 0


RISK_MODEL_CONFIGS = {
    "1 min":   {"max_bars": 30,  "model_name": "risk_of_ruin_1min"},
    "5 mins":  {"max_bars": 24,  "model_name": "risk_of_ruin_5min"},
    "15 mins": {"max_bars": 16,  "model_name": "risk_of_ruin_15min"},
    "30 mins": {"max_bars": 12,  "model_name": "risk_of_ruin_30min"},
    "1 hour":  {"max_bars": 8,   "model_name": "risk_of_ruin_1hour"},
    "1 day":   {"max_bars": 10,  "model_name": "risk_of_ruin_daily"},
}
