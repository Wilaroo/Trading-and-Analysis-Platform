"""
Setup-Specific Feature Engineering

Extends the base 46 features with 5-8 additional features per setup type.
These features are relevant to the specific trading pattern and help the model
learn setup-specific nuances.
"""

import numpy as np
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


def _safe_div(a, b, default=0.0):
    if b == 0 or np.isnan(b) or np.isinf(b):
        return default
    r = a / b
    return default if np.isnan(r) or np.isinf(r) else r


def _ema(data: np.ndarray, period: int) -> float:
    if len(data) < period:
        return np.mean(data) if len(data) > 0 else 0
    m = 2 / (period + 1)
    e = data[-1]
    for p in reversed(data[:-1]):
        e = (p * m) + (e * (1 - m))
    return e


def _compute_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return np.mean(highs[:period] - lows[:period]) if len(highs) >= period else 0.01
    tr_vals = []
    for i in range(period):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i + 1]) if i + 1 < len(closes) else hl
        lc = abs(lows[i] - closes[i + 1]) if i + 1 < len(closes) else hl
        tr_vals.append(max(hl, hc, lc))
    return np.mean(tr_vals)


# ========================================================================
# SETUP-SPECIFIC FEATURE EXTRACTORS
# Each returns a dict of feature_name -> value
# ========================================================================

def breakout_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    BREAKOUT-specific features:
    - consolidation_days: How many bars of consolidation before this bar
    - range_contraction_ratio: Current range contraction vs average
    - volume_at_break: Volume ratio at breakout vs consolidation period
    - distance_from_20d_high: How far price is from 20-day high
    - breakout_magnitude: Size of breakout relative to ATR
    """
    f = {}
    n = len(closes)

    # Consolidation days: count bars where range was below average
    atr = _compute_atr(highs, lows, closes)
    consol_days = 0
    for i in range(1, min(30, n)):
        if (highs[i] - lows[i]) < atr * 0.8:
            consol_days += 1
        else:
            break
    f['consol_days'] = consol_days

    # Range contraction: ratio of recent 5-bar avg range to 20-bar avg range
    if n >= 20:
        recent_range = np.mean(highs[:5] - lows[:5])
        avg_range = np.mean(highs[:20] - lows[:20])
        f['range_contraction'] = _safe_div(recent_range, avg_range, 1.0)
    else:
        f['range_contraction'] = 1.0

    # Volume at break vs consolidation
    if n >= 10:
        break_vol = volumes[0]
        consol_vol = np.mean(volumes[1:10])
        f['vol_at_break'] = _safe_div(break_vol, consol_vol, 1.0)
    else:
        f['vol_at_break'] = 1.0

    # Distance from N-day high
    if n >= 20:
        high_20 = np.max(highs[:20])
        f['dist_from_high'] = _safe_div(closes[0] - high_20, high_20, 0)
    else:
        f['dist_from_high'] = 0

    # Breakout magnitude
    f['break_magnitude'] = _safe_div(highs[0] - lows[0], atr, 1.0) if atr > 0 else 1.0

    # Squeeze indicator: BB width relative to its own 20-bar average
    if n >= 40:
        bb_widths = []
        for i in range(20):
            if i + 20 <= n:
                sma = np.mean(closes[i:i+20])
                std = np.std(closes[i:i+20])
                bb_widths.append(4 * std / sma if sma > 0 else 0)
        if bb_widths:
            current_bbw = bb_widths[0] if bb_widths else 0.04
            avg_bbw = np.mean(bb_widths)
            f['squeeze_ratio'] = _safe_div(current_bbw, avg_bbw, 1.0)
        else:
            f['squeeze_ratio'] = 1.0
    else:
        f['squeeze_ratio'] = 1.0

    return f


def momentum_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    MOMENTUM-specific features:
    - momentum_acceleration: Rate of change of momentum
    - consecutive_up_days: Streak of up bars
    - trend_alignment: EMA 9 vs 21 vs 50 alignment
    - momentum_vs_volume: Are volume and momentum aligned?
    - rsi_slope: Direction RSI is heading
    """
    f = {}
    n = len(closes)

    # Momentum acceleration: return_3 minus return_10
    ret3 = (closes[0] - closes[3]) / closes[3] if n > 3 and closes[3] > 0 else 0
    ret10 = (closes[0] - closes[10]) / closes[10] if n > 10 and closes[10] > 0 else 0
    f['momentum_accel'] = ret3 - ret10

    # Consecutive up/down days
    up_streak = 0
    for i in range(min(n - 1, 15)):
        if closes[i] > closes[i + 1]:
            up_streak += 1
        else:
            break
    down_streak = 0
    for i in range(min(n - 1, 15)):
        if closes[i] < closes[i + 1]:
            down_streak += 1
        else:
            break
    f['up_streak'] = up_streak
    f['down_streak'] = down_streak

    # Trend alignment: how many EMAs price is above
    ema9 = _ema(closes[:9], 9) if n >= 9 else closes[0]
    ema21 = _ema(closes[:21], 21) if n >= 21 else closes[0]
    sma50 = np.mean(closes[:50]) if n >= 50 else closes[0]
    above_count = sum([closes[0] > ema9, closes[0] > ema21, closes[0] > sma50])
    f['trend_alignment'] = above_count / 3.0  # 0 to 1

    # EMA stack: are EMAs in order? (9 > 21 > 50 for bullish)
    if n >= 50:
        f['ema_stack'] = 1.0 if ema9 > ema21 > sma50 else (-1.0 if ema9 < ema21 < sma50 else 0.0)
    else:
        f['ema_stack'] = 0.0

    # Volume-momentum alignment
    if n >= 5:
        price_dir = 1 if closes[0] > closes[4] else -1
        vol_dir = 1 if volumes[0] > np.mean(volumes[1:5]) else -1
        f['vol_momentum_align'] = 1.0 if price_dir == vol_dir else -1.0
    else:
        f['vol_momentum_align'] = 0.0

    # RSI slope (approximate)
    if n >= 20:
        # RSI at current and 5 bars ago
        from services.ai_modules.setup_pattern_detector import _compute_rsi
        rsi_now = _compute_rsi(closes)
        rsi_5ago = _compute_rsi(closes[5:])
        f['rsi_slope'] = (rsi_now - rsi_5ago) / 100.0
    else:
        f['rsi_slope'] = 0.0

    return f


def scalp_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SCALP-specific features:
    - intrabar_volatility: Range relative to close
    - tick_intensity: Volume per unit of range
    - body_dominance: Body vs wick ratio
    - speed: Price change per volume unit
    - microstructure_score: Combined scalp-friendliness score
    """
    f = {}
    n = len(closes)

    # Intrabar volatility
    f['intrabar_vol'] = _safe_div(highs[0] - lows[0], closes[0], 0)

    # Tick intensity: volume / range (high = lots of trading in tight range)
    bar_range = highs[0] - lows[0]
    f['tick_intensity'] = _safe_div(volumes[0], bar_range * 1000, 0) if bar_range > 0 else 0

    # Body dominance
    body = abs(closes[0] - opens[0])
    f['body_dominance'] = _safe_div(body, bar_range, 0.5) if bar_range > 0 else 0.5

    # Speed: absolute return per volume
    if n >= 2:
        abs_return = abs(closes[0] - closes[1])
        f['price_speed'] = _safe_div(abs_return, volumes[0], 0) * 1e6  # Scaled
    else:
        f['price_speed'] = 0

    # Recent volatility clustering
    if n >= 10:
        recent_ranges = (highs[:5] - lows[:5]) / np.maximum(closes[:5], 0.01)
        older_ranges = (highs[5:10] - lows[5:10]) / np.maximum(closes[5:10], 0.01)
        f['vol_clustering'] = _safe_div(np.mean(recent_ranges), np.mean(older_ranges), 1.0)
    else:
        f['vol_clustering'] = 1.0

    # Bid-ask spread proxy: ratio of wicks to body
    total_wicks = bar_range - body
    f['spread_proxy'] = _safe_div(total_wicks, bar_range, 0.5) if bar_range > 0 else 0.5

    return f


def gap_and_go_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    GAP_AND_GO-specific features:
    - gap_size_pct: Gap size as percentage
    - gap_vs_atr: Gap size relative to ATR
    - gap_fill_pct: How much of the gap was filled during the bar
    - post_gap_momentum: Price action after the gap
    - gap_volume_ratio: Volume on gap bar vs average
    """
    f = {}
    n = len(closes)

    # Gap size
    if n >= 2:
        gap = opens[0] - closes[1]
        gap_pct = _safe_div(gap, closes[1], 0)
    else:
        gap = 0
        gap_pct = 0
    f['gap_size_pct'] = gap_pct

    # Gap vs ATR
    atr = _compute_atr(highs, lows, closes)
    f['gap_vs_atr'] = _safe_div(abs(gap), atr, 0)

    # Gap fill: how much of the gap was filled
    if n >= 2 and gap != 0:
        if gap > 0:  # Bullish gap
            fill_amount = max(0, opens[0] - lows[0])
            f['gap_fill_pct'] = _safe_div(fill_amount, gap, 0)
        else:  # Bearish gap
            fill_amount = max(0, highs[0] - opens[0])
            f['gap_fill_pct'] = _safe_div(fill_amount, abs(gap), 0)
    else:
        f['gap_fill_pct'] = 0

    # Post-gap momentum: close vs open (did price continue in gap direction?)
    if gap_pct > 0:
        f['post_gap_momentum'] = _safe_div(closes[0] - opens[0], opens[0], 0)
    elif gap_pct < 0:
        f['post_gap_momentum'] = _safe_div(opens[0] - closes[0], opens[0], 0)
    else:
        f['post_gap_momentum'] = 0

    # Volume ratio
    if n >= 10:
        avg_vol = np.mean(volumes[1:10])
        f['gap_vol_ratio'] = _safe_div(volumes[0], avg_vol, 1.0)
    else:
        f['gap_vol_ratio'] = 1.0

    # Prior day range context
    if n >= 2:
        prior_range = highs[1] - lows[1]
        f['gap_vs_prior_range'] = _safe_div(abs(gap), prior_range, 0) if prior_range > 0 else 0
    else:
        f['gap_vs_prior_range'] = 0

    return f


def range_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    RANGE-specific features:
    - range_width: Width of the trading range
    - position_in_range: Where price sits (0=bottom, 1=top)
    - range_touches: How many times price touched support/resistance
    - range_duration: How long the range has persisted
    - mean_revert_strength: Tendency to revert within range
    """
    f = {}
    n = len(closes)
    lookback = min(30, n)

    # Range definition
    range_high = np.max(highs[:lookback])
    range_low = np.min(lows[:lookback])
    range_width = range_high - range_low
    f['range_width_pct'] = _safe_div(range_width, np.mean(closes[:lookback]), 0)

    # Position in range
    f['range_position'] = _safe_div(closes[0] - range_low, range_width, 0.5)

    # Support/resistance touches
    tolerance = range_width * 0.1
    support_touches = 0
    resistance_touches = 0
    for i in range(lookback):
        if lows[i] < range_low + tolerance:
            support_touches += 1
        if highs[i] > range_high - tolerance:
            resistance_touches += 1
    f['support_touches'] = support_touches / lookback
    f['resistance_touches'] = resistance_touches / lookback

    # Range duration: how many bars price stayed within range
    range_bars = 0
    for i in range(lookback):
        if lows[i] >= range_low - tolerance and highs[i] <= range_high + tolerance:
            range_bars += 1
    f['range_duration'] = range_bars / lookback

    # Mean revert strength: correlation between position and next-bar return
    if lookback >= 10:
        positions = [(closes[i] - range_low) / range_width if range_width > 0 else 0.5 for i in range(lookback - 1)]
        returns = [(closes[i] - closes[i+1]) / closes[i+1] if closes[i+1] > 0 else 0 for i in range(lookback - 1)]
        if len(positions) > 2 and np.std(positions) > 0 and np.std(returns) > 0:
            corr = np.corrcoef(positions, returns)[0, 1]
            f['mean_revert_str'] = -corr  # Negative correlation = mean reverting
        else:
            f['mean_revert_str'] = 0
    else:
        f['mean_revert_str'] = 0

    return f


def reversal_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    REVERSAL-specific features:
    - prior_trend_strength: How strong was the prior trend
    - exhaustion_volume: Volume pattern suggesting exhaustion
    - reversal_candle_score: Quality of reversal candlestick
    - divergence_score: Price vs momentum divergence
    - extension_from_mean: How far price extended before reversing
    """
    f = {}
    n = len(closes)

    # Prior trend: return over last 10 bars
    if n >= 11:
        f['prior_trend'] = _safe_div(closes[1] - closes[10], closes[10], 0)
    else:
        f['prior_trend'] = 0

    # Exhaustion volume: current volume vs recent trend
    if n >= 10:
        recent_vols = volumes[:5]
        prior_vols = volumes[5:10]
        f['vol_exhaustion'] = _safe_div(np.mean(recent_vols), np.mean(prior_vols), 1.0)
    else:
        f['vol_exhaustion'] = 1.0

    # Reversal candle score
    body = abs(closes[0] - opens[0])
    bar_range = highs[0] - lows[0]
    lower_wick = min(opens[0], closes[0]) - lows[0]
    upper_wick = highs[0] - max(opens[0], closes[0])

    # Hammer score
    hammer_score = 0
    if bar_range > 0:
        if lower_wick > 2 * body and upper_wick < body:
            hammer_score = 1.0  # Bullish hammer
        elif upper_wick > 2 * body and lower_wick < body:
            hammer_score = -1.0  # Shooting star
    f['reversal_candle'] = hammer_score

    # Divergence: price making new low but RSI not
    if n >= 20:
        from services.ai_modules.setup_pattern_detector import _compute_rsi
        rsi_now = _compute_rsi(closes)
        rsi_10ago = _compute_rsi(closes[10:])
        price_lower = closes[0] < closes[10]
        rsi_higher = rsi_now > rsi_10ago
        price_higher = closes[0] > closes[10]
        rsi_lower = rsi_now < rsi_10ago
        f['bull_divergence'] = 1.0 if (price_lower and rsi_higher) else 0.0
        f['bear_divergence'] = 1.0 if (price_higher and rsi_lower) else 0.0
    else:
        f['bull_divergence'] = 0.0
        f['bear_divergence'] = 0.0

    # Extension from mean
    if n >= 20:
        mean_20 = np.mean(closes[:20])
        std_20 = np.std(closes[:20])
        f['extension_zscore'] = _safe_div(closes[0] - mean_20, std_20, 0) if std_20 > 0 else 0
    else:
        f['extension_zscore'] = 0

    return f


def trend_continuation_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    TREND_CONTINUATION-specific features:
    - pullback_depth: How deep the pullback was relative to the trend
    - trend_duration: How long the trend has been active
    - pullback_volume_ratio: Volume during pullback vs trend
    - bounce_strength: Strength of the bounce off support
    - trend_angle: Slope of the trend
    """
    f = {}
    n = len(closes)

    # Pullback depth: how much price pulled back from recent swing high/low
    if n >= 15:
        recent_high = np.max(highs[:10])
        recent_low = np.min(lows[:10])
        trend_range = recent_high - recent_low
        if trend_range > 0:
            # If in uptrend, pullback is how far from high
            f['pullback_depth'] = _safe_div(recent_high - closes[0], trend_range, 0)
        else:
            f['pullback_depth'] = 0
    else:
        f['pullback_depth'] = 0

    # Trend duration: consecutive bars making HH+HL or LL+LH
    hh_hl = 0
    for i in range(min(n - 1, 20)):
        if highs[i] > highs[i + 1] and lows[i] > lows[i + 1]:
            hh_hl += 1
        else:
            break
    f['trend_duration'] = hh_hl

    # Pullback volume ratio
    if n >= 8:
        pullback_vol = np.mean(volumes[:3])
        trend_vol = np.mean(volumes[3:8])
        f['pullback_vol_ratio'] = _safe_div(pullback_vol, trend_vol, 1.0)
    else:
        f['pullback_vol_ratio'] = 1.0

    # Bounce strength: current bar's close relative to its open and range
    body = closes[0] - opens[0]
    bar_range = highs[0] - lows[0]
    f['bounce_strength'] = _safe_div(body, bar_range, 0) if bar_range > 0 else 0

    # Trend angle: slope of closes over lookback
    if n >= 10:
        x = np.arange(min(n, 20))
        y = closes[:len(x)]
        slope = np.polyfit(x, y, 1)[0]
        f['trend_angle'] = _safe_div(slope, np.mean(y), 0) * 100  # Normalized %
    else:
        f['trend_angle'] = 0

    return f


def orb_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    ORB (Opening Range Breakout)-specific features:
    - opening_range_size: Size of the opening range
    - breakout_distance: How far price moved past the range
    - time_to_break: How many bars before breakout
    - or_volume_ratio: Volume during range vs breakout
    - range_vs_atr: Opening range relative to ATR
    """
    f = {}
    n = len(closes)

    # Opening range (prior bar as proxy)
    if n >= 2:
        or_high = highs[1]
        or_low = lows[1]
        or_range = or_high - or_low
    else:
        or_range = 0
        or_high = highs[0]
        or_low = lows[0]

    f['or_range_size'] = _safe_div(or_range, closes[0], 0) if closes[0] > 0 else 0

    # Breakout distance
    if closes[0] > or_high:
        f['break_distance'] = _safe_div(closes[0] - or_high, or_range, 0) if or_range > 0 else 0
    elif closes[0] < or_low:
        f['break_distance'] = _safe_div(or_low - closes[0], or_range, 0) if or_range > 0 else 0
    else:
        f['break_distance'] = 0

    # Volume comparison
    if n >= 2:
        f['or_vol_ratio'] = _safe_div(volumes[0], volumes[1], 1.0)
    else:
        f['or_vol_ratio'] = 1.0

    # Range vs ATR
    atr = _compute_atr(highs, lows, closes)
    f['or_vs_atr'] = _safe_div(or_range, atr, 1.0) if atr > 0 else 1.0

    # Close position relative to opening range
    if or_range > 0:
        f['close_vs_or'] = _safe_div(closes[0] - or_low, or_range, 0.5)
    else:
        f['close_vs_or'] = 0.5

    # Follow-through: did price extend beyond the breakout bar?
    if n >= 3:
        f['follow_through'] = _safe_div(closes[0] - closes[1], closes[1], 0)
    else:
        f['follow_through'] = 0

    return f


def vwap_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    VWAP-specific features:
    - vwap_distance: Distance from VWAP
    - vwap_slope: VWAP trend direction
    - price_vs_vwap_history: How often price was above VWAP recently
    - vwap_bounce_count: Number of VWAP touches/bounces
    - volume_at_vwap: Volume when near VWAP
    """
    f = {}
    n = len(closes)
    lookback = min(20, n)

    # Compute VWAP
    tp = (highs[:lookback] + lows[:lookback] + closes[:lookback]) / 3
    cum_tp_vol = np.cumsum(tp * volumes[:lookback])
    cum_vol = np.cumsum(volumes[:lookback])

    # VWAP at various points
    vwap_values = []
    for i in range(lookback):
        if cum_vol[i] > 0:
            vwap_values.append(cum_tp_vol[i] / cum_vol[i])
        else:
            vwap_values.append(closes[i])
    vwap_now = vwap_values[0] if vwap_values else closes[0]

    # Distance from VWAP
    f['vwap_distance'] = _safe_div(closes[0] - vwap_now, vwap_now, 0)

    # VWAP slope
    if len(vwap_values) >= 5:
        f['vwap_slope'] = _safe_div(vwap_values[0] - vwap_values[4], vwap_values[4], 0)
    else:
        f['vwap_slope'] = 0

    # Price above VWAP ratio
    above_count = sum(1 for i in range(lookback) if closes[i] > vwap_values[i])
    f['above_vwap_ratio'] = above_count / lookback

    # VWAP touch count
    touches = 0
    tolerance = np.mean(highs[:lookback] - lows[:lookback]) * 0.3
    for i in range(lookback):
        if abs(closes[i] - vwap_values[i]) < tolerance:
            touches += 1
    f['vwap_touches'] = touches / lookback

    # Volume at VWAP vs away from VWAP
    near_vwap_vol = []
    away_vwap_vol = []
    for i in range(lookback):
        if abs(closes[i] - vwap_values[i]) < tolerance:
            near_vwap_vol.append(volumes[i])
        else:
            away_vwap_vol.append(volumes[i])
    if near_vwap_vol and away_vwap_vol:
        f['vol_at_vwap'] = _safe_div(np.mean(near_vwap_vol), np.mean(away_vwap_vol), 1.0)
    else:
        f['vol_at_vwap'] = 1.0

    return f


def mean_reversion_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    MEAN_REVERSION-specific features:
    - zscore: Current Z-score from 20-period mean
    - reversion_speed: Historical speed of mean reversion
    - extreme_duration: How long price has been at extreme
    - volume_at_extreme: Volume pattern at extreme
    - bb_squeeze_release: Bollinger Band behavior
    """
    f = {}
    n = len(closes)
    lookback = min(20, n)

    # Z-score
    if lookback >= 10:
        mean_p = np.mean(closes[:lookback])
        std_p = np.std(closes[:lookback])
        f['zscore'] = _safe_div(closes[0] - mean_p, std_p, 0) if std_p > 0 else 0
    else:
        f['zscore'] = 0

    # Historical reversion speed: avg bars to return to mean after extreme
    if n >= 40:
        mean_20 = np.mean(closes[:20])
        std_20 = np.std(closes[:20])
        # Look for past extremes and measure reversion
        revert_bars = []
        i = 1
        while i < n - 20:
            local_mean = np.mean(closes[i:i+20])
            local_std = np.std(closes[i:i+20])
            if local_std > 0 and abs(closes[i] - local_mean) > 1.5 * local_std:
                # Found extreme, count bars to revert
                for j in range(i - 1, max(i - 10, 0), -1):
                    if abs(closes[j] - local_mean) < 0.5 * local_std:
                        revert_bars.append(i - j)
                        break
            i += 5
        f['reversion_speed'] = np.mean(revert_bars) if revert_bars else 5.0
    else:
        f['reversion_speed'] = 5.0

    # Duration at extreme
    extreme_threshold = 1.5
    if lookback >= 10:
        mean_p = np.mean(closes[:lookback])
        std_p = np.std(closes[:lookback])
        duration = 0
        if std_p > 0:
            for i in range(min(n, 10)):
                if abs(closes[i] - mean_p) > extreme_threshold * std_p:
                    duration += 1
                else:
                    break
        f['extreme_duration'] = duration
    else:
        f['extreme_duration'] = 0

    # Volume at extreme vs normal
    if n >= 10:
        f['vol_at_extreme'] = _safe_div(volumes[0], np.mean(volumes[1:10]), 1.0)
    else:
        f['vol_at_extreme'] = 1.0

    # Rate of price change (is it slowing down = ready to revert?)
    if n >= 5:
        recent_change = abs(closes[0] - closes[2]) / closes[2] if closes[2] > 0 else 0
        prior_change = abs(closes[2] - closes[4]) / closes[4] if closes[4] > 0 else 0
        f['change_deceleration'] = _safe_div(prior_change - recent_change, prior_change, 0) if prior_change > 0 else 0
    else:
        f['change_deceleration'] = 0

    return f


# ========================================================================
# REGISTRY & API
# ========================================================================

SETUP_FEATURE_EXTRACTORS = {
    'MOMENTUM': momentum_features,
    'SCALP': scalp_features,
    'BREAKOUT': breakout_features,
    'GAP_AND_GO': gap_and_go_features,
    'RANGE': range_features,
    'REVERSAL': reversal_features,
    'TREND_CONTINUATION': trend_continuation_features,
    'ORB': orb_features,
    'VWAP': vwap_features,
    'MEAN_REVERSION': mean_reversion_features,
}

# Import short setup extractors and merge
try:
    from services.ai_modules.short_setup_features import SHORT_SETUP_FEATURE_EXTRACTORS
    SETUP_FEATURE_EXTRACTORS.update(SHORT_SETUP_FEATURE_EXTRACTORS)
except ImportError:
    pass


def get_setup_features(setup_type: str, opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    Extract setup-specific features for a given setup type.
    
    Returns dict of feature_name -> value (5-8 features per setup).
    """
    extractor = SETUP_FEATURE_EXTRACTORS.get(setup_type.upper())
    if not extractor:
        return {}
    
    try:
        features = extractor(opens, highs, lows, closes, volumes)
        # Sanitize NaN/Inf
        for k, v in features.items():
            if np.isnan(v) or np.isinf(v):
                features[k] = 0.0
        return features
    except Exception as e:
        logger.error(f"Error extracting {setup_type} features: {e}")
        return {}


def get_setup_feature_names(setup_type: str) -> List[str]:
    """Get ordered list of feature names for a setup type."""
    # Create dummy data to get feature names
    dummy = np.ones(50)
    features = get_setup_features(setup_type, dummy, dummy, dummy, dummy, dummy)
    return sorted(features.keys())
