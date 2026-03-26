"""
Gap Fill Probability Model

For GAP_AND_GO setups: predicts whether a gap will FILL (price returns to
previous close) or CONTINUE (price extends in gap direction).

This is one of the most actionable models for intraday traders:
  - Gap fills mean you should fade the gap (counter-trend)
  - Gap continuations mean you should ride the gap (trend-following)

Features (9 gap-specific features):
  gap_size_pct           — Gap magnitude as % of previous close
  gap_direction          — 1 for gap up, -1 for gap down
  gap_volume_ratio       — Opening bar volume vs 20-day avg volume
  gap_vs_atr             — Gap size relative to 10-day ATR (how unusual)
  prior_day_trend        — Previous day's close vs open direction
  prior_day_range_pct    — Previous day's range as % of close
  premarket_momentum     — Proxy: first bar's close vs open direction
  gap_into_resistance    — Is the gap pushing into a recent high/low zone?
  earnings_gap_flag      — Is this gap likely earnings-related? (size > 3% ATR)

Target: GAP_FILL (1) vs GAP_CONTINUE (0)
  GAP_FILL: Price touches previous close within N bars
  GAP_CONTINUE: Price does NOT touch previous close within N bars
"""

import logging
import numpy as np
from typing import Dict, Optional

logger = logging.getLogger(__name__)

GAP_FEATURE_NAMES = [
    "gap_size_pct",
    "gap_direction",
    "gap_volume_ratio",
    "gap_vs_atr",
    "prior_day_trend",
    "prior_day_range_pct",
    "premarket_momentum",
    "gap_into_resistance",
    "earnings_gap_flag",
]


def compute_gap_features(
    today_open: float,
    today_close_bar1: float,
    today_volume_bar1: float,
    prev_day_open: float,
    prev_day_high: float,
    prev_day_low: float,
    prev_day_close: float,
    daily_closes: np.ndarray,
    daily_highs: np.ndarray,
    daily_lows: np.ndarray,
    daily_volumes: np.ndarray,
) -> Dict[str, float]:
    """
    Compute gap-specific features.

    Args:
        today_open: Today's opening price
        today_close_bar1: First intraday bar's close (proxy for premarket momentum)
        today_volume_bar1: First intraday bar's volume
        prev_day_*: Previous day's OHLC
        daily_*: Recent daily arrays (most-recent-first, at least 20 bars)
    """
    feats = {}

    if prev_day_close <= 0 or today_open <= 0:
        return {name: 0.0 for name in GAP_FEATURE_NAMES}

    # 1. Gap size as %
    gap_pct = (today_open - prev_day_close) / prev_day_close
    feats["gap_size_pct"] = gap_pct

    # 2. Gap direction
    feats["gap_direction"] = 1.0 if gap_pct > 0 else -1.0

    # 3. Volume ratio (opening bar vs 20-day avg)
    if len(daily_volumes) >= 20:
        avg_vol = np.mean(daily_volumes[:20])
        feats["gap_volume_ratio"] = today_volume_bar1 / avg_vol if avg_vol > 0 else 1.0
    else:
        feats["gap_volume_ratio"] = 1.0

    # 4. Gap vs ATR (how unusual is this gap?)
    if len(daily_highs) >= 10 and len(daily_lows) >= 10 and len(daily_closes) >= 11:
        atr_vals = []
        for i in range(min(10, len(daily_closes) - 1)):
            tr = max(
                daily_highs[i] - daily_lows[i],
                abs(daily_highs[i] - daily_closes[i + 1]),
                abs(daily_lows[i] - daily_closes[i + 1]),
            )
            atr_vals.append(tr)
        atr_10 = np.mean(atr_vals) if atr_vals else 1.0
        feats["gap_vs_atr"] = abs(gap_pct * prev_day_close) / atr_10 if atr_10 > 0 else 0.0
    else:
        feats["gap_vs_atr"] = 0.0

    # 5. Prior day trend (bullish or bearish candle)
    feats["prior_day_trend"] = 1.0 if prev_day_close > prev_day_open else -1.0

    # 6. Prior day range %
    feats["prior_day_range_pct"] = (prev_day_high - prev_day_low) / prev_day_close if prev_day_close > 0 else 0.0

    # 7. Premarket momentum (first bar close vs open direction)
    if today_close_bar1 > 0:
        feats["premarket_momentum"] = (today_close_bar1 - today_open) / today_open
    else:
        feats["premarket_momentum"] = 0.0

    # 8. Gap into resistance/support
    if len(daily_highs) >= 10:
        if gap_pct > 0:
            # Gap up: is today's open near the recent highs? (resistance)
            recent_high = np.max(daily_highs[:10])
            feats["gap_into_resistance"] = min(1.0, today_open / recent_high) if recent_high > 0 else 0.5
        else:
            # Gap down: is today's open near recent lows? (support)
            recent_low = np.min(daily_lows[:10])
            feats["gap_into_resistance"] = max(0.0, recent_low / today_open) if today_open > 0 else 0.5
    else:
        feats["gap_into_resistance"] = 0.5

    # 9. Earnings gap flag (gap > 3x ATR is likely earnings/catalyst)
    feats["earnings_gap_flag"] = 1.0 if feats["gap_vs_atr"] > 3.0 else 0.0

    # Sanitize
    for key in feats:
        val = feats[key]
        if np.isnan(val) or np.isinf(val):
            feats[key] = 0.0

    return feats


def compute_gap_fill_target(
    intraday_lows: np.ndarray,
    intraday_highs: np.ndarray,
    prev_close: float,
    gap_direction: float,
    max_bars: int = 78,
) -> Optional[int]:
    """
    Compute gap fill target.

    intraday_lows/highs: Intraday bars after the gap (chronological, oldest first)
    prev_close: Previous day's closing price
    gap_direction: 1.0 for gap up, -1.0 for gap down

    Returns: 1 (GAP_FILL) if price touches prev_close within max_bars, else 0.
    """
    if prev_close <= 0:
        return None

    n = min(len(intraday_lows), len(intraday_highs), max_bars)
    if n == 0:
        return None

    for i in range(n):
        if gap_direction > 0:
            # Gap up: fill means price drops to prev_close
            if intraday_lows[i] <= prev_close:
                return 1
        else:
            # Gap down: fill means price rises to prev_close
            if intraday_highs[i] >= prev_close:
                return 1

    return 0


GAP_MODEL_CONFIGS = {
    "5 mins":  {"max_bars": 78,  "model_name": "gap_fill_5min"},   # ~6.5 hours
    "1 min":   {"max_bars": 390, "model_name": "gap_fill_1min"},   # Full day
    "15 mins": {"max_bars": 26,  "model_name": "gap_fill_15min"},  # ~6.5 hours
}
