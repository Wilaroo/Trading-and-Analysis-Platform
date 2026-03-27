"""
Short Setup-Specific Feature Engineering

Mirror of setup_features.py but optimized for SHORT setups.
Each extractor emphasizes bearish signals:
- Price weakness relative to key levels (below VWAP, below EMAs)
- Bearish candle patterns (bearish engulfing, shooting stars)
- Volume on down moves vs up moves
- Breakdown patterns instead of breakout patterns
- Overbought conditions that precede shorts

Setup types:
  SHORT_BREAKDOWN  - Inverse of BREAKOUT (breakdown below support)
  SHORT_MOMENTUM   - Inverse of MOMENTUM (bearish momentum acceleration)
  SHORT_REVERSAL   - Bearish reversal from highs/overbought
  SHORT_GAP_FADE   - Inverse of GAP_AND_GO (gap up fails, fades)
  SHORT_VWAP       - Inverse of VWAP (rejection from VWAP above)
  SHORT_MEAN_REVERSION - Overbought mean reversion (short the stretch)
  SHORT_SCALP      - Quick short scalps on intraday weakness
  SHORT_ORB        - Opening range breakdown
  SHORT_TREND      - Short trend continuation (bear trend)
  SHORT_RANGE      - Range breakdown
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


def _compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(len(closes) - 1):
        diff = closes[i] - closes[i + 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    if len(gains) < period:
        return 50.0
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ========================================================================
# SHORT-SPECIFIC FEATURE EXTRACTORS
# ========================================================================

def short_breakdown_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_BREAKDOWN features (inverse of BREAKOUT):
    - support_proximity: How close price is to recent lows (support)
    - breakdown_below_support: Has price broken below key support?
    - volume_on_breakdown: Volume surge on the breakdown bar
    - consecutive_lower_lows: Count of lower lows (distribution)
    - range_expansion_down: Downward range expansion relative to ATR
    - upper_wick_rejection: Rejection from highs (seller control)
    """
    f = {}
    n = len(closes)

    atr = _compute_atr(highs, lows, closes)

    # Distance from 20-bar LOW (support) — close to zero = at support, negative = broken below
    if n >= 20:
        low_20 = np.min(lows[:20])
        f['dist_from_support'] = _safe_div(closes[0] - low_20, low_20, 0)
    else:
        f['dist_from_support'] = 0

    # Consecutive lower lows (bearish structure)
    lower_low_streak = 0
    for i in range(min(n - 1, 15)):
        if lows[i] < lows[i + 1]:
            lower_low_streak += 1
        else:
            break
    f['lower_low_streak'] = lower_low_streak

    # Consecutive lower highs
    lower_high_streak = 0
    for i in range(min(n - 1, 15)):
        if highs[i] < highs[i + 1]:
            lower_high_streak += 1
        else:
            break
    f['lower_high_streak'] = lower_high_streak

    # Volume on down bars vs up bars (distribution pattern)
    if n >= 10:
        down_vol = sum(volumes[i] for i in range(10) if closes[i] < opens[i])
        up_vol = sum(volumes[i] for i in range(10) if closes[i] >= opens[i])
        f['down_vs_up_volume'] = _safe_div(down_vol, max(up_vol, 1), 1.0)
    else:
        f['down_vs_up_volume'] = 1.0

    # Breakdown magnitude relative to ATR
    if atr > 0:
        f['breakdown_magnitude'] = _safe_div(lows[0] - closes[0], atr, 0) * -1
    else:
        f['breakdown_magnitude'] = 0

    # Upper wick ratio (rejection from highs = bearish)
    bar_range = highs[0] - lows[0]
    if bar_range > 0:
        upper_wick = highs[0] - max(opens[0], closes[0])
        f['upper_wick_ratio'] = _safe_div(upper_wick, bar_range, 0)
    else:
        f['upper_wick_ratio'] = 0

    return f


def short_momentum_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_MOMENTUM features (inverse of MOMENTUM):
    - bearish_momentum_accel: Rate of downward momentum increase
    - consecutive_down_bars: Streak of down closes
    - ema_stack_bearish: Are EMAs in bearish order (9 < 21 < 50)?
    - volume_momentum_bearish: Volume increasing on down moves
    - rsi_declining: RSI trending down
    - price_below_all_emas: Count of EMAs price is below
    """
    f = {}
    n = len(closes)

    # Bearish momentum acceleration
    ret3 = (closes[0] - closes[3]) / closes[3] if n > 3 and closes[3] > 0 else 0
    ret10 = (closes[0] - closes[10]) / closes[10] if n > 10 and closes[10] > 0 else 0
    f['bearish_momentum_accel'] = ret10 - ret3  # Positive = accelerating downward

    # Consecutive down bars
    down_streak = 0
    for i in range(min(n - 1, 15)):
        if closes[i] < closes[i + 1]:
            down_streak += 1
        else:
            break
    f['down_streak'] = down_streak

    # Bearish EMA stack
    ema9 = _ema(closes[:9], 9) if n >= 9 else closes[0]
    ema21 = _ema(closes[:21], 21) if n >= 21 else closes[0]
    sma50 = np.mean(closes[:50]) if n >= 50 else closes[0]

    if n >= 50:
        f['ema_stack_bearish'] = 1.0 if ema9 < ema21 < sma50 else (0.5 if ema9 < ema21 else 0.0)
    else:
        f['ema_stack_bearish'] = 0.0

    # Count of EMAs price is BELOW
    below_count = sum([closes[0] < ema9, closes[0] < ema21, closes[0] < sma50])
    f['below_ema_count'] = below_count / 3.0

    # Volume on down moves vs up moves (last 5 bars)
    if n >= 5:
        down_vol = sum(volumes[i] for i in range(5) if closes[i] < opens[i])
        up_vol = sum(volumes[i] for i in range(5) if closes[i] >= opens[i])
        f['bearish_vol_alignment'] = _safe_div(down_vol, max(up_vol, 1), 1.0)
    else:
        f['bearish_vol_alignment'] = 1.0

    # RSI slope (declining)
    if n >= 20:
        rsi_now = _compute_rsi(closes)
        rsi_5ago = _compute_rsi(closes[5:])
        f['rsi_decline'] = (rsi_5ago - rsi_now) / 100.0  # Positive = RSI declining
    else:
        f['rsi_decline'] = 0.0

    return f


def short_reversal_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_REVERSAL features (bearish reversal from overbought/high):
    - overbought_rsi: RSI > 70 signals overbought
    - distance_from_high: How far from recent high (just peaked?)
    - bearish_engulfing: Current bar engulfs prior bullish bar
    - volume_climax: Extreme volume on final push up (exhaustion)
    - upper_tail_rejection: Long upper wicks = seller rejection
    - momentum_divergence: Price making new highs but momentum weakening
    """
    f = {}
    n = len(closes)

    # RSI overbought level
    rsi = _compute_rsi(closes) if n >= 15 else 50
    f['overbought_rsi'] = max(0, (rsi - 50)) / 50.0  # 0 to 1, higher = more overbought

    # Distance from recent high (negative = just off the high)
    if n >= 10:
        high_10 = np.max(highs[:10])
        f['dist_from_recent_high'] = _safe_div(closes[0] - high_10, high_10, 0)
    else:
        f['dist_from_recent_high'] = 0

    # Bearish engulfing detection
    if n >= 2:
        prior_bullish = closes[1] > opens[1]
        current_bearish = closes[0] < opens[0]
        current_engulfs = opens[0] >= closes[1] and closes[0] <= opens[1]
        f['bearish_engulfing'] = 1.0 if (prior_bullish and current_bearish and current_engulfs) else 0.0
    else:
        f['bearish_engulfing'] = 0.0

    # Shooting star detection (long upper wick, small body at bottom)
    bar_range = highs[0] - lows[0]
    if bar_range > 0:
        upper_wick = highs[0] - max(opens[0], closes[0])
        body = abs(closes[0] - opens[0])
        f['shooting_star'] = 1.0 if (upper_wick > 2 * body and closes[0] < opens[0]) else 0.0
    else:
        f['shooting_star'] = 0.0

    # Volume climax (exhaustion): current volume vs 10-bar avg
    if n >= 10:
        avg_vol = np.mean(volumes[1:10])
        f['volume_climax'] = _safe_div(volumes[0], avg_vol, 1.0)
    else:
        f['volume_climax'] = 1.0

    # Momentum divergence: price near high but RSI declining
    if n >= 20:
        price_near_high = 1.0 if closes[0] > np.percentile(closes[:20], 80) else 0.0
        rsi_declining = 1.0 if _compute_rsi(closes) < _compute_rsi(closes[5:]) else 0.0
        f['bearish_divergence'] = price_near_high * rsi_declining
    else:
        f['bearish_divergence'] = 0.0

    return f


def short_gap_fade_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_GAP_FADE features (inverse of GAP_AND_GO):
    Gap up but fails to hold — fades back down.
    - gap_up_size: Size of the gap up
    - gap_fill_pct: How much of the gap has already filled (more = fading)
    - post_gap_weakness: Price action weakness after gap
    - gap_rejection_volume: Volume on the fade vs gap bar
    - failed_breakout: Gapped above resistance but fell back
    """
    f = {}
    n = len(closes)

    # Gap up size
    if n >= 2:
        gap = opens[0] - closes[1]
        gap_pct = _safe_div(gap, closes[1], 0)
    else:
        gap = 0
        gap_pct = 0
    f['gap_up_size'] = max(0, gap_pct)  # Only positive gaps (gap up)

    # Gap fill percentage (how much of the gap has filled)
    if gap > 0 and n >= 2:
        fill = opens[0] - closes[0]  # How far price dropped from open
        f['gap_fill_pct'] = _safe_div(fill, gap, 0)
    else:
        f['gap_fill_pct'] = 0

    # Post-gap weakness: close below open on gap day
    f['post_gap_bearish'] = 1.0 if (closes[0] < opens[0] and gap_pct > 0.005) else 0.0

    # Volume comparison: fade volume vs gap volume
    atr = _compute_atr(highs, lows, closes)
    if n >= 5 and atr > 0:
        f['gap_vs_atr'] = _safe_div(abs(gap), atr, 0)
    else:
        f['gap_vs_atr'] = 0

    # Rejection: gapped up but made a lower close than previous close
    if n >= 2:
        f['gap_rejection'] = 1.0 if (gap_pct > 0.003 and closes[0] < closes[1]) else 0.0
    else:
        f['gap_rejection'] = 0.0

    # Volume on the fade
    if n >= 5:
        f['fade_volume_ratio'] = _safe_div(volumes[0], np.mean(volumes[1:5]), 1.0)
    else:
        f['fade_volume_ratio'] = 1.0

    return f


def short_vwap_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_VWAP features (inverse of VWAP):
    Price approaching VWAP from below or rejecting from VWAP above.
    - price_vs_vwap: Distance below VWAP (negative = below)
    - vwap_rejection_count: How many times price tested and failed VWAP
    - volume_below_vwap: Volume concentrated below VWAP
    - vwap_slope: VWAP trending down
    - below_vwap_duration: How long price has been below VWAP
    """
    f = {}
    n = len(closes)

    # Approximate VWAP from available data
    if n >= 10:
        cum_vol = np.cumsum(volumes[:n])
        cum_pv = np.cumsum(closes[:n] * volumes[:n])
        vwap = cum_pv[-1] / cum_vol[-1] if cum_vol[-1] > 0 else closes[0]

        # Distance from VWAP (negative = below)
        f['price_vs_vwap'] = _safe_div(closes[0] - vwap, vwap, 0)

        # Duration below VWAP
        below_count = 0
        for i in range(min(n, 20)):
            local_vwap = cum_pv[i] / cum_vol[i] if cum_vol[i] > 0 else closes[i]
            if closes[i] < local_vwap:
                below_count += 1
        f['below_vwap_duration'] = below_count

        # VWAP slope (declining VWAP = bearish)
        if n >= 20:
            vwap_recent = cum_pv[4] / cum_vol[4] if cum_vol[4] > 0 else closes[4]
            vwap_older = cum_pv[14] / cum_vol[14] if cum_vol[14] > 0 else closes[14]
            f['vwap_slope'] = _safe_div(vwap_recent - vwap_older, vwap_older, 0)
        else:
            f['vwap_slope'] = 0

        # Volume below VWAP vs above
        vol_below = sum(volumes[i] for i in range(min(n, 20)) if closes[i] < vwap)
        vol_above = sum(volumes[i] for i in range(min(n, 20)) if closes[i] >= vwap)
        f['vol_below_vwap_ratio'] = _safe_div(vol_below, max(vol_above, 1), 1.0)
    else:
        f['price_vs_vwap'] = 0
        f['below_vwap_duration'] = 0
        f['vwap_slope'] = 0
        f['vol_below_vwap_ratio'] = 1.0

    # Rejection from VWAP: high touched VWAP area but closed below
    if n >= 10:
        cum_vol_last = np.cumsum(volumes[:n])
        cum_pv_last = np.cumsum(closes[:n] * volumes[:n])
        vwap_val = cum_pv_last[-1] / cum_vol_last[-1] if cum_vol_last[-1] > 0 else closes[0]
        atr = _compute_atr(highs, lows, closes)
        near_vwap = abs(highs[0] - vwap_val) < atr * 0.3 if atr > 0 else False
        f['vwap_rejection'] = 1.0 if (near_vwap and closes[0] < vwap_val) else 0.0
    else:
        f['vwap_rejection'] = 0.0

    return f


def short_mean_reversion_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_MEAN_REVERSION features (short the overbought stretch):
    - zscore_high: Z-score of price (positive = extended above mean)
    - bb_upper_touch: Price near upper Bollinger Band
    - rsi_overbought: RSI above 70
    - overextension_duration: How long price has been above 1.5 std
    - deceleration: Price momentum slowing down at highs
    - vol_at_extreme_high: Volume pattern at the extreme high
    """
    f = {}
    n = len(closes)
    lookback = min(20, n)

    # Z-score (positive = above mean = overbought)
    if lookback >= 10:
        mean_p = np.mean(closes[:lookback])
        std_p = np.std(closes[:lookback])
        f['zscore_high'] = _safe_div(closes[0] - mean_p, std_p, 0) if std_p > 0 else 0
    else:
        f['zscore_high'] = 0

    # Upper Bollinger Band position
    if n >= 20:
        sma20 = np.mean(closes[:20])
        std20 = np.std(closes[:20])
        upper_bb = sma20 + 2 * std20
        f['bb_upper_position'] = _safe_div(closes[0] - sma20, upper_bb - sma20, 0) if std20 > 0 else 0
    else:
        f['bb_upper_position'] = 0

    # RSI overbought
    rsi = _compute_rsi(closes) if n >= 15 else 50
    f['rsi_overbought_level'] = max(0, rsi - 50) / 50.0

    # Duration above 1-std
    if lookback >= 10:
        mean_p = np.mean(closes[:lookback])
        std_p = np.std(closes[:lookback])
        duration = 0
        if std_p > 0:
            for i in range(min(n, 10)):
                if closes[i] > mean_p + std_p:
                    duration += 1
                else:
                    break
        f['overextension_duration'] = duration
    else:
        f['overextension_duration'] = 0

    # Momentum deceleration at highs
    if n >= 5:
        recent_change = (closes[0] - closes[2]) / closes[2] if closes[2] > 0 else 0
        prior_change = (closes[2] - closes[4]) / closes[4] if closes[4] > 0 else 0
        f['momentum_deceleration'] = prior_change - recent_change  # Positive = slowing
    else:
        f['momentum_deceleration'] = 0

    # Volume at extreme
    if n >= 10:
        f['vol_at_high'] = _safe_div(volumes[0], np.mean(volumes[1:10]), 1.0)
    else:
        f['vol_at_high'] = 1.0

    return f


def short_scalp_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_SCALP features (quick short scalps on intraday weakness):
    - bearish_body_dominance: Red candle body vs total range
    - selling_pressure: Volume on down ticks
    - intrabar_weakness: Close near low of bar
    - speed_of_decline: Price change velocity downward
    - micro_resistance: Repeated rejection from a price level
    """
    f = {}
    n = len(closes)

    # Bearish body dominance
    bar_range = highs[0] - lows[0]
    body = closes[0] - opens[0]  # Negative = bearish
    f['bearish_body'] = _safe_div(abs(min(0, body)), bar_range, 0.5) if bar_range > 0 else 0

    # Close position within bar (0 = at low, 1 = at high)
    f['close_at_low'] = 1.0 - (_safe_div(closes[0] - lows[0], bar_range, 0.5) if bar_range > 0 else 0.5)

    # Speed of decline
    if n >= 3:
        decline = opens[0] - closes[0]  # Positive if price dropped
        f['decline_speed'] = _safe_div(max(0, decline), volumes[0], 0) * 1e6
    else:
        f['decline_speed'] = 0

    # Recent bearish candle ratio (% of last 5 bars that are red)
    if n >= 5:
        red_bars = sum(1 for i in range(5) if closes[i] < opens[i])
        f['red_bar_ratio'] = red_bars / 5.0
    else:
        f['red_bar_ratio'] = 0.5

    # Volatility clustering on downside
    if n >= 10:
        down_ranges = [(highs[i] - lows[i]) for i in range(5) if closes[i] < opens[i]]
        up_ranges = [(highs[i] - lows[i]) for i in range(5) if closes[i] >= opens[i]]
        avg_down = np.mean(down_ranges) if down_ranges else 0
        avg_up = np.mean(up_ranges) if up_ranges else 0.01
        f['downside_vol_expansion'] = _safe_div(avg_down, avg_up, 1.0)
    else:
        f['downside_vol_expansion'] = 1.0

    # Bid-ask spread proxy (wide spread = less liquid, harder to short)
    total_wicks = bar_range - abs(body) if bar_range > 0 else 0
    f['spread_proxy'] = _safe_div(total_wicks, bar_range, 0.5) if bar_range > 0 else 0.5

    return f


def short_orb_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_ORB features (opening range breakdown):
    - orb_low_break: Price broke below opening range low
    - opening_range_size: Size of the opening range
    - volume_on_breakdown: Volume when breaking below OR low
    - pre_break_consolidation: Consolidation at OR low before break
    - first_bar_bearish: First bar of day was red (bearish open)
    """
    f = {}
    n = len(closes)

    # Opening range (first 3-6 bars approximation)
    or_bars = min(6, n)
    if or_bars >= 3:
        or_high = np.max(highs[:or_bars])
        or_low = np.min(lows[:or_bars])
        or_range = or_high - or_low

        # Break below OR low
        f['below_or_low'] = 1.0 if closes[0] < or_low else 0.0

        # Distance below OR low
        f['dist_below_or'] = _safe_div(or_low - closes[0], or_range, 0) if or_range > 0 else 0

        # OR range size relative to price
        f['or_range_pct'] = _safe_div(or_range, closes[0], 0)

        # Volume on breakdown vs OR average
        or_avg_vol = np.mean(volumes[:or_bars])
        f['breakdown_vol_ratio'] = _safe_div(volumes[0], or_avg_vol, 1.0)
    else:
        f['below_or_low'] = 0
        f['dist_below_or'] = 0
        f['or_range_pct'] = 0
        f['breakdown_vol_ratio'] = 1.0

    # First bar bearish
    if n >= 1:
        f['first_bar_bearish'] = 1.0 if closes[-1] < opens[-1] else 0.0 if n > 1 else (1.0 if closes[0] < opens[0] else 0.0)
    else:
        f['first_bar_bearish'] = 0.0

    return f


def short_trend_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_TREND features (bearish trend continuation):
    - trend_strength_bearish: Strength of the downtrend
    - price_below_emas: Price below all key moving averages
    - pullback_into_resistance: Price pulled back to resistance (EMA) and failed
    - lower_highs_count: Count of lower highs (supply zone structure)
    - bearish_macd: MACD histogram negative and deepening
    """
    f = {}
    n = len(closes)

    # Bearish trend strength: % of last 20 bars where close < open
    if n >= 20:
        bearish_bars = sum(1 for i in range(20) if closes[i] < opens[i])
        f['bearish_trend_strength'] = bearish_bars / 20.0
    else:
        f['bearish_trend_strength'] = 0.5

    # Price below key EMAs
    ema9 = _ema(closes[:9], 9) if n >= 9 else closes[0]
    ema21 = _ema(closes[:21], 21) if n >= 21 else closes[0]
    sma50 = np.mean(closes[:50]) if n >= 50 else closes[0]
    sma200 = np.mean(closes[:200]) if n >= 200 else closes[0]

    below_count = sum([
        closes[0] < ema9,
        closes[0] < ema21,
        closes[0] < sma50,
        closes[0] < sma200
    ])
    f['below_ma_count'] = below_count / 4.0

    # Pullback into EMA21 resistance and failed
    if n >= 21:
        touched_ema21 = abs(highs[0] - ema21) < _compute_atr(highs, lows, closes) * 0.3
        rejected = closes[0] < ema21
        f['ema21_rejection'] = 1.0 if (touched_ema21 and rejected) else 0.0
    else:
        f['ema21_rejection'] = 0.0

    # Lower highs count
    lower_highs = 0
    for i in range(min(n - 1, 10)):
        if highs[i] < highs[i + 1]:
            lower_highs += 1
    f['lower_highs_count'] = lower_highs

    # MACD histogram (bearish)
    if n >= 26:
        ema12 = _ema(closes[:12], 12)
        ema26 = _ema(closes[:26], 26)
        macd_line = ema12 - ema26
        f['macd_bearish'] = -macd_line / closes[0] if closes[0] > 0 else 0  # Positive = bearish
    else:
        f['macd_bearish'] = 0

    return f


def short_range_features(opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    SHORT_RANGE features (range breakdown):
    - range_low_proximity: How close to the bottom of the range
    - range_break_volume: Volume on the breakdown
    - time_in_range: How long price consolidated in range
    - breakdown_momentum: Speed of the breakdown
    - false_breakout_above: Failed to break above range (trap)
    """
    f = {}
    n = len(closes)

    # Define range from last 20 bars
    lookback = min(20, n)
    if lookback >= 10:
        range_high = np.max(highs[:lookback])
        range_low = np.min(lows[:lookback])
        range_size = range_high - range_low

        # Position within range (0 = at low, 1 = at high)
        f['range_position'] = _safe_div(closes[0] - range_low, range_size, 0.5) if range_size > 0 else 0.5

        # Broke below range
        f['below_range'] = 1.0 if closes[0] < range_low else 0.0

        # Time in range (how many bars within the range)
        in_range = sum(1 for i in range(lookback) if lows[i] >= range_low * 0.99 and highs[i] <= range_high * 1.01)
        f['time_in_range'] = in_range / lookback

        # Volume on breakdown
        avg_vol = np.mean(volumes[:lookback])
        f['breakdown_vol_surge'] = _safe_div(volumes[0], avg_vol, 1.0)
    else:
        f['range_position'] = 0.5
        f['below_range'] = 0.0
        f['time_in_range'] = 0
        f['breakdown_vol_surge'] = 1.0

    # False breakout above (bull trap preceding short)
    if n >= 5:
        recent_high = np.max(highs[:5])
        if lookback >= 10:
            range_high_20 = np.max(highs[:lookback])
            f['failed_upbreak'] = 1.0 if (recent_high > range_high_20 and closes[0] < range_high_20) else 0.0
        else:
            f['failed_upbreak'] = 0.0
    else:
        f['failed_upbreak'] = 0.0

    return f


# ========================================================================
# REGISTRY & API
# ========================================================================

SHORT_SETUP_FEATURE_EXTRACTORS = {
    'SHORT_BREAKDOWN': short_breakdown_features,
    'SHORT_MOMENTUM': short_momentum_features,
    'SHORT_REVERSAL': short_reversal_features,
    'SHORT_GAP_FADE': short_gap_fade_features,
    'SHORT_VWAP': short_vwap_features,
    'SHORT_MEAN_REVERSION': short_mean_reversion_features,
    'SHORT_SCALP': short_scalp_features,
    'SHORT_ORB': short_orb_features,
    'SHORT_TREND': short_trend_features,
    'SHORT_RANGE': short_range_features,
}


def get_short_setup_features(setup_type: str, opens, highs, lows, closes, volumes) -> Dict[str, float]:
    """
    Extract short-specific features for a given setup type.
    Returns dict of feature_name -> value (5-8 features per setup).
    """
    extractor = SHORT_SETUP_FEATURE_EXTRACTORS.get(setup_type.upper())
    if not extractor:
        return {}

    try:
        features = extractor(opens, highs, lows, closes, volumes)
        for k, v in features.items():
            if np.isnan(v) or np.isinf(v):
                features[k] = 0.0
        return features
    except Exception as e:
        logger.error(f"Error extracting {setup_type} short features: {e}")
        return {}


def get_short_setup_feature_names(setup_type: str) -> List[str]:
    """Get ordered list of feature names for a short setup type."""
    dummy = np.ones(50)
    features = get_short_setup_features(setup_type, dummy, dummy, dummy, dummy, dummy)
    return sorted(features.keys())
