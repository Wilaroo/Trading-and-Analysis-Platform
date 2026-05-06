"""
Regime-Conditional Models

Instead of training one model per timeframe that must handle ALL market
conditions, this module trains separate models per market regime:
  - BULL_TREND:   SPY above 20-SMA, RSI > 50, positive momentum
  - BEAR_TREND:   SPY below 20-SMA, RSI < 50, negative momentum
  - RANGE_BOUND:  SPY near 20-SMA, RSI 40-60, low directional momentum
  - HIGH_VOL:     ATR expansion > 1.3x normal (fear/panic regime)

Why? A breakout model trained on 2 years of mixed data is mediocre at
everything. A breakout model trained ONLY on bull-trend periods becomes
highly specialized and accurate for that regime.

At prediction time:
  1. Detect current regime from SPY/QQQ/IWM data
  2. Route to the regime-specific model
  3. Fallback to generic model if regime model isn't trained yet

Architecture:
  For each (setup_type, bar_size) combination, we train 4 regime variants:
  e.g., "breakout_5min_bull", "breakout_5min_bear", etc.

  Total models = existing 23 x 4 regimes = 92 regime-conditional models
  (In practice, some regimes may have too little data to train — that's OK,
   they fall back to the generic model.)
"""

import logging
import numpy as np
from typing import Dict

logger = logging.getLogger(__name__)

# Regime definitions
REGIME_BULL = "bull_trend"
REGIME_BEAR = "bear_trend"
REGIME_RANGE = "range_bound"
REGIME_HIGHVOL = "high_vol"

ALL_REGIMES = [REGIME_BULL, REGIME_BEAR, REGIME_RANGE, REGIME_HIGHVOL]


def classify_regime(
    spy_closes: np.ndarray,
    spy_highs: np.ndarray,
    spy_lows: np.ndarray,
) -> str:
    """
    Classify current market regime from SPY daily bars (most-recent-first).
    Needs at least 25 bars.

    Returns one of: "bull_trend", "bear_trend", "range_bound", "high_vol"
    """
    n = len(spy_closes)
    if n < 25:
        return REGIME_RANGE  # Default when insufficient data

    current = spy_closes[0]
    sma_20 = np.mean(spy_closes[:20])

    # RSI
    if n >= 15:
        c = spy_closes[:15][::-1]
        deltas = np.diff(c)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.0001
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
    else:
        rsi = 50

    # 5-bar momentum
    mom = (spy_closes[0] - spy_closes[4]) / spy_closes[4] if n > 4 and spy_closes[4] > 0 else 0

    # ATR expansion: 5-day ATR vs 20-day ATR
    def _atr(period):
        vals = []
        for i in range(min(period, n - 1)):
            tr = max(
                spy_highs[i] - spy_lows[i],
                abs(spy_highs[i] - spy_closes[i + 1]) if i + 1 < n else spy_highs[i] - spy_lows[i],
                abs(spy_lows[i] - spy_closes[i + 1]) if i + 1 < n else spy_highs[i] - spy_lows[i],
            )
            vals.append(tr)
        return np.mean(vals) if vals else 0

    atr_5 = _atr(5)
    atr_20 = _atr(20)
    vol_expansion = atr_5 / atr_20 if atr_20 > 0 else 1.0

    # Decision tree for regime classification
    # Priority 1: High vol overrides everything (fear/crash)
    if vol_expansion > 1.3:
        return REGIME_HIGHVOL

    # Priority 2: Trend classification
    trend_dist = (current - sma_20) / sma_20 if sma_20 > 0 else 0

    if trend_dist > 0.01 and rsi > 50 and mom > 0:
        return REGIME_BULL
    elif trend_dist < -0.01 and rsi < 50 and mom < 0:
        return REGIME_BEAR
    else:
        return REGIME_RANGE


def classify_regime_for_date(
    spy_data: Dict,
    date_str: str,
) -> str:
    """
    Classify regime at a specific historical date.

    spy_data: Dict with "dates", "closes", "highs", "lows", "date_to_idx" keys
              (as produced by RegimeFeatureProvider._data["spy"])
    date_str: Date string "YYYY-MM-DD"
    """
    clean_date = date_str[:10]
    idx = spy_data.get("date_to_idx", {}).get(clean_date)

    if idx is None:
        for i in range(len(spy_data.get("dates", [])) - 1, -1, -1):
            if spy_data["dates"][i] <= clean_date:
                idx = i
                break

    if idx is None or idx < 25:
        return REGIME_RANGE

    window = min(25, idx + 1)
    start = idx - window + 1
    c = spy_data["closes"][start: idx + 1][::-1]
    h = spy_data["highs"][start: idx + 1][::-1]
    lo = spy_data["lows"][start: idx + 1][::-1]

    return classify_regime(c, h, lo)


def get_regime_model_name(base_model_name: str, regime: str) -> str:
    """Generate regime-specific model name."""
    return f"{base_model_name}_{regime}"


def get_all_regime_model_names(base_model_name: str) -> Dict[str, str]:
    """Get all regime variant model names for a base model."""
    return {r: get_regime_model_name(base_model_name, r) for r in ALL_REGIMES}


# Minimum samples needed to train a regime-specific model
# If fewer samples are available, we skip that regime and fall back to generic
MIN_REGIME_SAMPLES = 100

# Feature that gets added to each sample identifying the regime
# (even generic models get this so they have regime awareness)
REGIME_LABEL_FEATURE = "regime_label_encoded"


def encode_regime(regime: str) -> float:
    """Encode regime as numeric feature."""
    mapping = {
        REGIME_BULL: 1.0,
        REGIME_BEAR: -1.0,
        REGIME_RANGE: 0.0,
        REGIME_HIGHVOL: 0.5,
    }
    return mapping.get(regime, 0.0)
