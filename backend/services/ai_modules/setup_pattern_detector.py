"""
Setup Pattern Detector

Identifies trading setup patterns from OHLCV bar data.
Each detector returns True/False for whether a bar qualifies as that setup type.
Used to filter training data so each setup model only learns from relevant examples.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def _safe_div(a, b, default=0.0):
    """Safe division avoiding zero/nan."""
    if b == 0 or np.isnan(b) or np.isinf(b):
        return default
    result = a / b
    return default if np.isnan(result) or np.isinf(result) else result


def _ema(data: np.ndarray, period: int) -> float:
    if len(data) < period:
        return np.mean(data) if len(data) > 0 else 0
    multiplier = 2 / (period + 1)
    ema_val = data[-1]
    for price in reversed(data[:-1]):
        ema_val = (price * multiplier) + (ema_val * (1 - multiplier))
    return ema_val


def _compute_atr(highs, lows, closes, period=14):
    """Compute ATR from arrays (most recent first)."""
    if len(closes) < period + 1:
        return np.mean(highs[:period] - lows[:period]) if len(highs) >= period else 0
    tr_vals = []
    for i in range(period):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i + 1]) if i + 1 < len(closes) else hl
        lc = abs(lows[i] - closes[i + 1]) if i + 1 < len(closes) else hl
        tr_vals.append(max(hl, hc, lc))
    return np.mean(tr_vals)


def _compute_rsi(closes, period=14):
    """Compute RSI from close array (most recent first)."""
    if len(closes) < period + 1:
        return 50.0
    # Bars are most-recent-first, so deltas[i] = closes[i] - closes[i+1]
    deltas = np.diff(closes[:period + 1])  # This gives recent-to-old diffs
    # deltas[0] = closes[0] - closes[1] (most recent change)
    # For RSI we want price changes: each bar vs prior bar
    # Since bars are newest-first, deltas are already in correct direction
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _bb_width(closes, period=20):
    """Bollinger Band width as fraction of SMA."""
    if len(closes) < period:
        return 0.04
    sma = np.mean(closes[:period])
    std = np.std(closes[:period])
    if sma == 0:
        return 0
    return (4 * std) / sma  # 2 std above + 2 std below


def _bb_position(closes, period=20):
    """Where price sits within Bollinger Bands (0=lower, 1=upper)."""
    if len(closes) < period:
        return 0.5
    sma = np.mean(closes[:period])
    std = np.std(closes[:period])
    if std == 0:
        return 0.5
    upper = sma + 2 * std
    lower = sma - 2 * std
    return _safe_div(closes[0] - lower, upper - lower, 0.5)


def _consecutive_direction(closes, direction='up', max_look=10):
    """Count consecutive up or down bars."""
    count = 0
    limit = min(len(closes) - 1, max_look)
    for i in range(limit):
        if direction == 'up' and closes[i] > closes[i + 1]:
            count += 1
        elif direction == 'down' and closes[i] < closes[i + 1]:
            count += 1
        else:
            break
    return count


# ========================================================================
# PATTERN DETECTORS
# Each returns (is_match: bool, confidence: float 0-1, direction: str)
# ========================================================================

def detect_breakout(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    BREAKOUT: Price breaks out of consolidation zone.
    - Tight Bollinger Bands (consolidation) followed by range expansion
    - Volume surge confirms the breakout
    """
    if len(closes) < lookback + 5:
        return False, 0.0, 'neutral'

    # Check for prior consolidation: BB width over last 5-20 bars should have been low
    prior_bb_widths = []
    for offset in range(3, min(lookback, len(closes) - 20)):
        w = _bb_width(closes[offset:offset + 20])
        prior_bb_widths.append(w)

    if not prior_bb_widths:
        return False, 0.0, 'neutral'

    avg_prior_bb = np.mean(prior_bb_widths)
    current_bb = _bb_width(closes[:20]) if len(closes) >= 20 else avg_prior_bb

    # Range expansion: current bar range vs ATR
    atr = _compute_atr(highs, lows, closes)
    current_range = highs[0] - lows[0]
    range_expansion = _safe_div(current_range, atr, 1.0)

    # Volume surge
    avg_vol = np.mean(volumes[1:11]) if len(volumes) > 10 else volumes[0]
    rvol = _safe_div(volumes[0], avg_vol, 1.0)

    # New high/low breakout
    recent_high = np.max(highs[1:lookback]) if len(highs) > lookback else highs[1]
    recent_low = np.min(lows[1:lookback]) if len(lows) > lookback else lows[1]
    breaks_high = closes[0] > recent_high
    breaks_low = closes[0] < recent_low

    # Scoring
    score = 0.0
    if avg_prior_bb < 0.06:  # Prior consolidation (tight bands)
        score += 0.25
    if range_expansion > 1.5:  # Range expansion
        score += 0.25
    if rvol > 1.3:  # Volume confirmation
        score += 0.25
    if breaks_high or breaks_low:  # Price breakout
        score += 0.25

    direction = 'bullish' if breaks_high or closes[0] > opens[0] else 'bearish'
    is_match = score >= 0.5
    return is_match, score, direction


def detect_momentum(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    MOMENTUM: Strong directional trend with follow-through.
    - RSI showing directional bias
    - Price above/below moving averages
    - MACD confirmation
    - Multiple consecutive bars in same direction
    """
    if len(closes) < max(lookback, 26):
        return False, 0.0, 'neutral'

    rsi = _compute_rsi(closes)
    ema9 = _ema(closes[:9], 9)
    ema21 = _ema(closes[:21], 21)

    # MACD
    ema12 = _ema(closes[:26], 12)
    ema26 = _ema(closes[:26], 26)
    macd = ema12 - ema26

    # Consecutive direction
    up_streak = _consecutive_direction(closes, 'up')
    down_streak = _consecutive_direction(closes, 'down')

    # Trend strength: higher highs + higher lows or vice versa
    hh_count = sum(1 for i in range(min(5, len(highs) - 1)) if highs[i] > highs[i + 1])
    ll_count = sum(1 for i in range(min(5, len(lows) - 1)) if lows[i] < lows[i + 1])

    # Bullish momentum
    bull_score = 0.0
    if rsi > 55: bull_score += 0.2
    if closes[0] > ema9: bull_score += 0.15
    if closes[0] > ema21: bull_score += 0.15
    if macd > 0: bull_score += 0.15
    if up_streak >= 2: bull_score += 0.15
    if hh_count >= 3: bull_score += 0.2

    # Bearish momentum
    bear_score = 0.0
    if rsi < 45: bear_score += 0.2
    if closes[0] < ema9: bear_score += 0.15
    if closes[0] < ema21: bear_score += 0.15
    if macd < 0: bear_score += 0.15
    if down_streak >= 2: bear_score += 0.15
    if ll_count >= 3: bear_score += 0.2

    score = max(bull_score, bear_score)
    direction = 'bullish' if bull_score > bear_score else 'bearish'
    is_match = score >= 0.5
    return is_match, score, direction


def detect_scalp(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    SCALP: Quick in-and-out on high volatility + high volume bars.
    - High relative volume
    - Above-average intraday range
    - Tight spreads implied by body/range ratio
    """
    if len(closes) < lookback:
        return False, 0.0, 'neutral'

    # Relative volume
    avg_vol = np.mean(volumes[1:lookback]) if len(volumes) > lookback else volumes[0]
    rvol = _safe_div(volumes[0], avg_vol, 1.0)

    # Range vs average
    ranges = highs[:lookback] - lows[:lookback]
    avg_range = np.mean(ranges[1:]) if len(ranges) > 1 else ranges[0]
    current_range = ranges[0]
    range_ratio = _safe_div(current_range, avg_range, 1.0)

    # Volatility ratio
    if len(closes) >= 11:
        recent_vol = np.std(np.diff(np.log(np.maximum(closes[:6], 0.01))))
        avg_vol_stat = np.std(np.diff(np.log(np.maximum(closes[:lookback], 0.01))))
        vol_ratio = _safe_div(recent_vol, avg_vol_stat, 1.0)
    else:
        vol_ratio = 1.0

    score = 0.0
    if rvol > 1.3: score += 0.3
    if range_ratio > 1.2: score += 0.25
    if vol_ratio > 1.2: score += 0.25
    # Body/range ratio — active trading produces decisive candles
    body = abs(closes[0] - opens[0])
    bar_range = highs[0] - lows[0]
    if bar_range > 0 and body / bar_range > 0.4:
        score += 0.2

    direction = 'bullish' if closes[0] > opens[0] else 'bearish'
    is_match = score >= 0.5
    return is_match, score, direction


def detect_gap_and_go(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    GAP_AND_GO: Gap opening with continuation in the gap direction.
    - Gap > 1% from prior close
    - Volume surge on gap bar
    - Price continues in gap direction (doesn't fill)
    """
    if len(closes) < 3:
        return False, 0.0, 'neutral'

    # Gap size
    gap = _safe_div(opens[0] - closes[1], closes[1], 0.0)
    abs_gap = abs(gap)

    # Volume surge
    avg_vol = np.mean(volumes[1:min(11, len(volumes))]) if len(volumes) > 1 else volumes[0]
    rvol = _safe_div(volumes[0], avg_vol, 1.0)

    # Continuation: close in gap direction
    if gap > 0:
        continuation = closes[0] > opens[0]  # Bullish gap, bullish close
        gap_held = closes[0] > closes[1]     # Didn't fill the gap
    else:
        continuation = closes[0] < opens[0]  # Bearish gap, bearish close
        gap_held = closes[0] < closes[1]

    score = 0.0
    if abs_gap > 0.01: score += 0.3    # 1%+ gap
    if abs_gap > 0.02: score += 0.1    # 2%+ gap bonus
    if rvol > 1.5: score += 0.2        # Volume surge
    if continuation: score += 0.2       # Price follows gap
    if gap_held: score += 0.2           # Gap doesn't fill

    direction = 'bullish' if gap > 0 else 'bearish'
    is_match = score >= 0.5 and abs_gap > 0.005
    return is_match, score, direction


def detect_range(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    RANGE: Price oscillating in a defined range (no trend).
    - Low trend strength
    - Moderate/stable Bollinger Band width
    - RSI near neutral (35-65)
    - Price bouncing between support/resistance
    """
    if len(closes) < lookback:
        return False, 0.0, 'neutral'

    rsi = _compute_rsi(closes)
    bb_w = _bb_width(closes)
    bb_pos = _bb_position(closes)

    # Trend strength (ADX-like)
    if len(highs) >= 14:
        up_moves = np.diff(highs[:14])
        down_moves = -np.diff(lows[:14])
        plus_dm = np.sum(np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0))
        minus_dm = np.sum(np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0))
        total_dm = plus_dm + minus_dm
        trend_str = abs(plus_dm - minus_dm) / total_dm if total_dm > 0 else 0
    else:
        trend_str = 0.5

    # Support/resistance bounces: price reversing near range extremes
    high_20 = np.max(highs[:lookback])
    low_20 = np.min(lows[:lookback])
    range_20 = high_20 - low_20
    position_in_range = _safe_div(closes[0] - low_20, range_20, 0.5)

    # Near boundary?
    near_support = position_in_range < 0.25
    near_resistance = position_in_range > 0.75

    score = 0.0
    if trend_str < 0.3: score += 0.3           # Low trend
    if 35 < rsi < 65: score += 0.2              # Neutral RSI
    if 0.02 < bb_w < 0.08: score += 0.2         # Moderate BB width
    if near_support or near_resistance: score += 0.15
    # Check oscillation: alternating up/down bars
    if len(closes) >= 5:
        directions = [1 if closes[i] > closes[i+1] else -1 for i in range(4)]
        alternating = sum(1 for i in range(3) if directions[i] != directions[i+1])
        if alternating >= 2: score += 0.15

    direction = 'bullish' if near_support else ('bearish' if near_resistance else 'neutral')
    is_match = score >= 0.5
    return is_match, score, direction


def detect_reversal(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    REVERSAL: Trend reversal after extreme conditions.
    - RSI extreme (< 30 or > 70)
    - Candlestick reversal patterns (hammer, engulfing)
    - Against the prevailing short-term trend
    - Volume confirmation
    """
    if len(closes) < lookback:
        return False, 0.0, 'neutral'

    rsi = _compute_rsi(closes)

    # Candlestick patterns
    body = abs(closes[0] - opens[0])
    bar_range = highs[0] - lows[0]

    # Hammer (long lower wick)
    lower_wick = min(opens[0], closes[0]) - lows[0]
    upper_wick = highs[0] - max(opens[0], closes[0])
    is_hammer = bar_range > 0 and lower_wick > 2 * body and upper_wick < body

    # Engulfing
    if len(closes) >= 2:
        prev_body = abs(closes[1] - opens[1])
        bull_engulf = closes[0] > opens[0] and closes[1] < opens[1] and body > prev_body
        bear_engulf = closes[0] < opens[0] and closes[1] > opens[1] and body > prev_body
    else:
        bull_engulf = bear_engulf = False

    # Prior trend (were we trending before this bar?)
    if len(closes) >= 6:
        prior_return = (closes[1] - closes[5]) / closes[5] if closes[5] > 0 else 0
    else:
        prior_return = 0

    # Volume
    avg_vol = np.mean(volumes[1:11]) if len(volumes) > 10 else volumes[0]
    rvol = _safe_div(volumes[0], avg_vol, 1.0)

    # Bullish reversal (was in downtrend, now reversing up)
    bull_score = 0.0
    if rsi < 30: bull_score += 0.3
    elif rsi < 40: bull_score += 0.15
    if is_hammer or bull_engulf: bull_score += 0.25
    if prior_return < -0.03: bull_score += 0.25  # Was in downtrend
    if rvol > 1.2: bull_score += 0.2

    # Bearish reversal
    bear_score = 0.0
    if rsi > 70: bear_score += 0.3
    elif rsi > 60: bear_score += 0.15
    if bear_engulf: bear_score += 0.25
    if prior_return > 0.03: bear_score += 0.25  # Was in uptrend
    if rvol > 1.2: bear_score += 0.2

    score = max(bull_score, bear_score)
    direction = 'bullish' if bull_score > bear_score else 'bearish'
    is_match = score >= 0.5
    return is_match, score, direction


def detect_trend_continuation(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    TREND_CONTINUATION: Pullback to moving average in an existing trend, then bounce.
    - Strong existing trend
    - Pullback to EMA 9 or 21
    - Higher highs/lower lows pattern continues
    - Volume decreases on pullback, increases on continuation
    """
    if len(closes) < max(lookback, 21):
        return False, 0.0, 'neutral'

    ema9 = _ema(closes[:9], 9)
    ema21 = _ema(closes[:21], 21)

    # Distance from EMAs (normalized)
    ema9_dist = _safe_div(closes[0] - ema9, ema9, 0)
    ema21_dist = _safe_div(closes[0] - ema21, ema21, 0)

    # Trend over longer period
    if len(closes) >= 15:
        long_return = (closes[0] - closes[14]) / closes[14] if closes[14] > 0 else 0
    else:
        long_return = 0

    # Higher highs pattern
    hh_count = sum(1 for i in range(min(5, len(highs) - 1)) if highs[i] > highs[i + 1])
    hl_count = sum(1 for i in range(min(5, len(lows) - 1)) if lows[i] > lows[i + 1])

    # Pullback: recent bars pulled back toward EMA
    if len(closes) >= 4:
        was_extended = abs(_safe_div(closes[2] - ema9, ema9, 0)) > abs(ema9_dist)
        pulled_back = abs(ema9_dist) < 0.01  # Near EMA now
    else:
        was_extended = False
        pulled_back = False

    # Volume pattern: declining on pullback
    if len(volumes) >= 4:
        pullback_vol = np.mean(volumes[1:3])
        trend_vol = np.mean(volumes[3:6]) if len(volumes) >= 6 else pullback_vol
        vol_declining = pullback_vol < trend_vol
    else:
        vol_declining = False

    # Bullish continuation
    bull_score = 0.0
    if long_return > 0.02: bull_score += 0.25
    if closes[0] > ema21: bull_score += 0.15
    if pulled_back and was_extended: bull_score += 0.2
    if hh_count >= 3 and hl_count >= 3: bull_score += 0.2  # Higher highs + higher lows
    if vol_declining: bull_score += 0.1
    if closes[0] > opens[0]: bull_score += 0.1  # Bounce candle

    # Bearish continuation
    bear_score = 0.0
    if long_return < -0.02: bear_score += 0.25
    if closes[0] < ema21: bear_score += 0.15
    ll_count = sum(1 for i in range(min(5, len(lows) - 1)) if lows[i] < lows[i + 1])
    lh_count = sum(1 for i in range(min(5, len(highs) - 1)) if highs[i] < highs[i + 1])
    if pulled_back and was_extended: bear_score += 0.2
    if ll_count >= 3 and lh_count >= 3: bear_score += 0.2
    if vol_declining: bear_score += 0.1
    if closes[0] < opens[0]: bear_score += 0.1

    score = max(bull_score, bear_score)
    direction = 'bullish' if bull_score > bear_score else 'bearish'
    is_match = score >= 0.5
    return is_match, score, direction


def detect_orb(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    ORB (Opening Range Breakout): Price breaks out of early session range.
    - Works best on intraday timeframes
    - For daily bars: approximated as breakout of prior day's range
    - Volume confirms the breakout
    """
    if len(closes) < 5:
        return False, 0.0, 'neutral'

    # Use prior bar as "opening range" proxy
    prior_high = highs[1]
    prior_low = lows[1]
    prior_range = prior_high - prior_low

    # Current bar breaks the range
    breaks_above = closes[0] > prior_high
    breaks_below = closes[0] < prior_low

    # How much above/below
    if breaks_above:
        extension = _safe_div(closes[0] - prior_high, prior_range, 0)
    elif breaks_below:
        extension = _safe_div(prior_low - closes[0], prior_range, 0)
    else:
        extension = 0

    # Volume
    avg_vol = np.mean(volumes[1:6]) if len(volumes) > 5 else volumes[0]
    rvol = _safe_div(volumes[0], avg_vol, 1.0)

    # Gap into range (opens near prior high/low)
    opens_near_range = (abs(opens[0] - prior_high) < prior_range * 0.3 or
                        abs(opens[0] - prior_low) < prior_range * 0.3)

    score = 0.0
    if breaks_above or breaks_below: score += 0.35
    if extension > 0.5: score += 0.15
    if rvol > 1.3: score += 0.25
    if opens_near_range: score += 0.15
    if abs(closes[0] - opens[0]) / (highs[0] - lows[0] + 0.001) > 0.5: score += 0.1

    direction = 'bullish' if breaks_above else ('bearish' if breaks_below else 'neutral')
    is_match = score >= 0.5 and (breaks_above or breaks_below)
    return is_match, score, direction


def detect_vwap(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    VWAP: Price interaction with volume-weighted average price.
    - Computed from OHLCV data
    - Bounce off VWAP / VWAP reclaim
    - Volume confirms at VWAP level
    """
    if len(closes) < lookback:
        return False, 0.0, 'neutral'

    # Compute cumulative VWAP from available bars
    typical_prices = (highs[:lookback] + lows[:lookback] + closes[:lookback]) / 3
    cum_tp_vol = np.cumsum(typical_prices * volumes[:lookback])
    cum_vol = np.cumsum(volumes[:lookback])
    # Most recent VWAP
    vwap = cum_tp_vol[0] / cum_vol[0] if cum_vol[0] > 0 else closes[0]
    # Use a rolling VWAP approximation
    vwap_rolling = cum_tp_vol[-1] / cum_vol[-1] if cum_vol[-1] > 0 else closes[0]

    # Distance from VWAP
    vwap_dist = _safe_div(closes[0] - vwap_rolling, vwap_rolling, 0)

    # Price crossing VWAP
    if len(closes) >= 2:
        was_below = closes[1] < vwap_rolling
        was_above = closes[1] > vwap_rolling
        now_above = closes[0] > vwap_rolling
        now_below = closes[0] < vwap_rolling
        cross_up = was_below and now_above
        cross_down = was_above and now_below
    else:
        cross_up = cross_down = False

    # Near VWAP (within 0.5%)
    near_vwap = abs(vwap_dist) < 0.005

    # Bounce off VWAP
    if len(closes) >= 3:
        approached_vwap = abs(_safe_div(closes[1] - vwap_rolling, vwap_rolling, 1)) < 0.003
        bounced_away = abs(vwap_dist) > 0.003
        vwap_bounce = approached_vwap and bounced_away
    else:
        vwap_bounce = False

    # Volume at VWAP interaction
    avg_vol = np.mean(volumes[1:6]) if len(volumes) > 5 else volumes[0]
    rvol = _safe_div(volumes[0], avg_vol, 1.0)

    score = 0.0
    if cross_up or cross_down: score += 0.3
    if near_vwap or vwap_bounce: score += 0.25
    if rvol > 1.2: score += 0.2
    if abs(closes[0] - opens[0]) / (highs[0] - lows[0] + 0.001) > 0.5: score += 0.15
    if vwap_bounce: score += 0.1

    direction = 'bullish' if (cross_up or closes[0] > vwap_rolling) else 'bearish'
    is_match = score >= 0.5
    return is_match, score, direction


def detect_mean_reversion(opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    MEAN_REVERSION: Price at statistical extremes, likely to revert.
    - Price > 2 std devs from mean (BB position extreme)
    - RSI extreme but not as severe as reversal
    - Volume exhaustion (declining volume at extreme)
    - CCI extreme
    """
    if len(closes) < lookback:
        return False, 0.0, 'neutral'

    rsi = _compute_rsi(closes)
    bb_pos = _bb_position(closes)

    # CCI
    if len(closes) >= 20:
        tp = (highs[:20] + lows[:20] + closes[:20]) / 3
        sma_tp = np.mean(tp)
        mean_dev = np.mean(np.abs(tp - sma_tp))
        cci = (tp[0] - sma_tp) / (0.015 * mean_dev) if mean_dev > 0 else 0
    else:
        cci = 0

    # Z-score of current price
    if len(closes) >= lookback:
        mean_price = np.mean(closes[:lookback])
        std_price = np.std(closes[:lookback])
        z_score = _safe_div(closes[0] - mean_price, std_price, 0)
    else:
        z_score = 0

    # Volume exhaustion (declining at extreme)
    if len(volumes) >= 5:
        vol_trend = (volumes[0] - volumes[2]) / volumes[2] if volumes[2] > 0 else 0
        vol_exhaustion = vol_trend < -0.1  # Volume declining
    else:
        vol_exhaustion = False

    # Overextended high
    high_score = 0.0
    if bb_pos > 0.9: high_score += 0.3
    if rsi > 65: high_score += 0.2
    if cci > 100: high_score += 0.15
    if z_score > 1.5: high_score += 0.15
    if vol_exhaustion: high_score += 0.2

    # Overextended low
    low_score = 0.0
    if bb_pos < 0.1: low_score += 0.3
    if rsi < 35: low_score += 0.2
    if cci < -100: low_score += 0.15
    if z_score < -1.5: low_score += 0.15
    if vol_exhaustion: low_score += 0.2

    score = max(high_score, low_score)
    # Direction is the EXPECTED reversion direction (opposite of extreme)
    direction = 'bearish' if high_score > low_score else 'bullish'
    is_match = score >= 0.5
    return is_match, score, direction


# ========================================================================
# REGISTRY
# ========================================================================

SETUP_DETECTORS = {
    'MOMENTUM': detect_momentum,
    'SCALP': detect_scalp,
    'BREAKOUT': detect_breakout,
    'GAP_AND_GO': detect_gap_and_go,
    'RANGE': detect_range,
    'REVERSAL': detect_reversal,
    'TREND_CONTINUATION': detect_trend_continuation,
    'ORB': detect_orb,
    'VWAP': detect_vwap,
    'MEAN_REVERSION': detect_mean_reversion,
}


def detect_setup(setup_type: str, opens, highs, lows, closes, volumes, lookback=20) -> Tuple[bool, float, str]:
    """
    Run pattern detection for a given setup type.
    
    Returns: (is_match, confidence, direction)
    """
    detector = SETUP_DETECTORS.get(setup_type.upper())
    if not detector:
        logger.warning(f"Unknown setup type: {setup_type}")
        return False, 0.0, 'neutral'
    return detector(opens, highs, lows, closes, volumes, lookback)


def scan_bars_for_setup(
    setup_type: str,
    bars: List[Dict],
    min_lookback: int = 30,
    stride: int = 1
) -> List[int]:
    """
    Scan a list of bars (most recent first) and return indices where the setup pattern was detected.
    
    Args:
        setup_type: Setup type name
        bars: OHLCV bars (most recent first)
        min_lookback: Minimum bars needed for detection
        stride: Check every N-th bar (1 = every bar)
        
    Returns:
        List of bar indices where the pattern was detected
    """
    if len(bars) < min_lookback:
        return []

    opens = np.array([b.get('open', 0) for b in bars], dtype=float)
    highs = np.array([b.get('high', 0) for b in bars], dtype=float)
    lows = np.array([b.get('low', 0) for b in bars], dtype=float)
    closes = np.array([b.get('close', 0) for b in bars], dtype=float)
    volumes = np.array([b.get('volume', 0) for b in bars], dtype=float)

    # Replace zeros
    closes = np.where(closes == 0, 1, closes)
    opens = np.where(opens == 0, closes, opens)
    volumes = np.where(volumes == 0, 1, volumes)

    matching_indices = []
    max_check = len(bars) - min_lookback

    for i in range(0, max_check, stride):
        is_match, confidence, direction = detect_setup(
            setup_type,
            opens[i:], highs[i:], lows[i:], closes[i:], volumes[i:],
            lookback=min(min_lookback, len(closes) - i)
        )
        if is_match:
            matching_indices.append(i)

    return matching_indices
