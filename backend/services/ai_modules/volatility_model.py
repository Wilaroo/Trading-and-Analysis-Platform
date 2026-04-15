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


def compute_vol_targets_batch(
    closes: np.ndarray,
    forecast_horizon: int,
    start_idx: int = 50,
) -> np.ndarray:
    """
    Vectorized batch computation of volatility targets for ALL valid bars.

    Same math as compute_vol_target but computed in one shot using sliding windows.
    Returns float32 array of length (n_valid,) where n_valid = len(closes) - start_idx - forecast_horizon.
    Values: 1.0 (HIGH_VOL), 0.0 (LOW_VOL), or -1.0 (invalid, trailing_vol==0).
    The caller should filter out -1.0 entries.

    closes: chronological (oldest first).
    """
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(closes)
    n_valid = n - start_idx - forecast_horizon
    if n_valid <= 0 or start_idx < 20:
        return np.array([], dtype=np.float32)

    # Trailing 20-bar realized vol for each position i in [start_idx, start_idx + n_valid)
    # trailing window for bar i = closes[i-19:i+1] (20 elements)
    trail_wins = sliding_window_view(closes, 20)  # (n-19, 20)
    # trail_wins[k] = closes[k:k+20], last element = closes[k+19]
    # For bar i, k = i - 19 → trail_wins[i-19]
    with np.errstate(divide='ignore', invalid='ignore'):
        trail_rets = np.diff(trail_wins, axis=1) / np.where(trail_wins[:, :-1] != 0, trail_wins[:, :-1], 1.0)
    trail_rets = np.where(np.isfinite(trail_rets), trail_rets, 0.0)
    trail_vol_all = np.std(trail_rets, axis=1)  # (n-19,)

    # Forward (fh+1)-bar realized vol for each position
    fwd_wins = sliding_window_view(closes, forecast_horizon + 1)  # (n-fh, fh+1)
    with np.errstate(divide='ignore', invalid='ignore'):
        fwd_rets = np.diff(fwd_wins, axis=1) / np.where(fwd_wins[:, :-1] != 0, fwd_wins[:, :-1], 1.0)
    fwd_rets = np.where(np.isfinite(fwd_rets), fwd_rets, 0.0)
    fwd_vol_all = np.std(fwd_rets, axis=1)  # (n-fh,)

    # Select slices for our output range [start_idx, start_idx + n_valid)
    trail_slice = trail_vol_all[start_idx - 19: start_idx - 19 + n_valid]  # trailing vols
    fwd_slice = fwd_vol_all[start_idx: start_idx + n_valid]  # forward vols

    actual_n = min(len(trail_slice), len(fwd_slice))
    if actual_n <= 0:
        return np.array([], dtype=np.float32)

    trail_slice = trail_slice[:actual_n]
    fwd_slice = fwd_slice[:actual_n]

    targets = np.where(trail_slice > 0,
                       np.where(fwd_slice > trail_slice, 1.0, 0.0),
                       0.0).astype(np.float32)
    return targets


def compute_vol_features_batch(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    opens: np.ndarray,
    volumes: np.ndarray,
    lookback: int = 50,
) -> np.ndarray:
    """
    Vectorized batch computation of 6 vol-specific features for ALL valid bars.

    Same math as compute_vol_specific_features but for all bars at once.
    Arrays: chronological (oldest first), length N.
    Returns: (M, 6) float32 array where M = N - lookback.
    features[j] corresponds to bar index (lookback + j).

    Feature order matches VOL_FEATURE_NAMES:
      [vol_rank_20, vol_rank_50, vol_acceleration, range_expansion, gap_frequency, volume_vol_corr]
    """
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(closes)
    n_out = n - lookback
    if n_out <= 0 or n < lookback:
        return np.empty((0, 6), dtype=np.float32)

    features = np.full((n_out, 6), 0.0, dtype=np.float32)

    # === Pre-compute rolling realized vols (10-bar and 5-bar) ===
    if n >= 11:
        win11 = sliding_window_view(closes, 11)  # (n-10, 11)
        with np.errstate(divide='ignore', invalid='ignore'):
            r11 = np.diff(win11, axis=1) / np.where(win11[:, :-1] != 0, win11[:, :-1], 1.0)
        r11 = np.where(np.isfinite(r11), r11, 0.0)
        all_10bv = np.std(r11, axis=1).astype(np.float32)  # (n-10,)
    else:
        all_10bv = np.zeros(max(0, n - 10), dtype=np.float32)

    if n >= 6:
        win6 = sliding_window_view(closes, 6)
        with np.errstate(divide='ignore', invalid='ignore'):
            r6 = np.diff(win6, axis=1) / np.where(win6[:, :-1] != 0, win6[:, :-1], 1.0)
        r6 = np.where(np.isfinite(r6), r6, 0.0)
        all_5bv = np.std(r6, axis=1).astype(np.float32)
    else:
        all_5bv = np.zeros(max(0, n - 5), dtype=np.float32)

    # === Feature 1: vol_rank_20 (rolling percentile over 20 vols) ===
    # For output j, bar_i = lookback + j, vol_idx = bar_i - 10
    # Window of 20 vols ending at vol_idx → sliding_window_view(all_10bv, 20)
    if len(all_10bv) >= 20:
        vw20 = sliding_window_view(all_10bv, 20)  # shape: (len(all_10bv)-19, 20)
        ranks_20 = np.mean(vw20 <= vw20[:, -1:], axis=1)  # (len-19,)
        # Map: for output j, vol_idx = lookback+j-10, k20 = vol_idx-19 = lookback+j-29
        j_idx = np.arange(n_out)
        k20 = lookback + j_idx - 29
        valid = (k20 >= 0) & (k20 < len(ranks_20))
        features[valid, 0] = ranks_20[k20[valid]]
        features[~valid, 0] = 0.5
    else:
        features[:, 0] = 0.5

    # === Feature 2: vol_rank_50 ===
    # Original uses min(50, n-10) where n=lookback=50, giving 40 vols from the 50-bar window.
    # Each vol is shifted by 1 bar → all_10bv[i-49:i-9] (40 values) for bar i.
    if len(all_10bv) >= 40:
        vw40 = sliding_window_view(all_10bv, 40)
        ranks_50 = np.mean(vw40 <= vw40[:, -1:], axis=1)
        j_idx = np.arange(n_out)
        k40 = lookback + j_idx - 49
        valid = (k40 >= 0) & (k40 < len(ranks_50))
        features[valid, 1] = ranks_50[k40[valid]]
        features[~valid, 1] = 0.5
    else:
        features[:, 1] = 0.5

    # === Feature 3: vol_acceleration (5-bar vol / 10-bar vol - 1) ===
    j_idx = np.arange(n_out)
    v5_idx = lookback + j_idx - 5  # index into all_5bv
    v10_idx = lookback + j_idx - 10  # index into all_10bv
    v5_ok = (v5_idx >= 0) & (v5_idx < len(all_5bv))
    v10_ok = (v10_idx >= 0) & (v10_idx < len(all_10bv))
    both_ok = v5_ok & v10_ok
    if both_ok.any():
        v5 = all_5bv[v5_idx[both_ok]]
        v10 = all_10bv[v10_idx[both_ok]]
        with np.errstate(divide='ignore', invalid='ignore'):
            acc = np.where(v10 > 0, v5 / v10 - 1.0, 0.0)
        acc = np.where(np.isfinite(acc), acc, 0.0)
        features[both_ok, 2] = acc

    # === Feature 4: range_expansion (5-bar avg range / 20-bar avg range) ===
    ranges_all = highs - lows
    if n >= 5:
        rm5 = np.convolve(ranges_all, np.ones(5, dtype=np.float32) / 5, mode='valid')  # (n-4,)
    else:
        rm5 = np.array([], dtype=np.float32)
    if n >= 20:
        rm20 = np.convolve(ranges_all, np.ones(20, dtype=np.float32) / 20, mode='valid')  # (n-19,)
    else:
        rm20 = np.array([], dtype=np.float32)

    if len(rm5) > 0 and len(rm20) > 0:
        # rm5[k] = mean(ranges[k:k+5]), for bar i → k = i-4
        # rm20[k] = mean(ranges[k:k+20]), for bar i → k = i-19
        r5_idx = lookback + j_idx - 4
        r20_idx = lookback + j_idx - 19
        r5_ok = (r5_idx >= 0) & (r5_idx < len(rm5))
        r20_ok = (r20_idx >= 0) & (r20_idx < len(rm20))
        rng_ok = r5_ok & r20_ok
        if rng_ok.any():
            r5v = rm5[r5_idx[rng_ok]]
            r20v = rm20[r20_idx[rng_ok]]
            with np.errstate(divide='ignore', invalid='ignore'):
                re = np.where(r20v > 0, r5v / r20v, 1.0)
            features[rng_ok, 3] = np.where(np.isfinite(re), re, 1.0)
    features[features[:, 3] == 0.0, 3] = 1.0  # default

    # === Feature 5: gap_frequency (fraction of last 10 bars with gap > 0.5%) ===
    if n >= 2:
        with np.errstate(divide='ignore', invalid='ignore'):
            gap_pct = np.abs(opens[1:] - closes[:-1]) / np.where(closes[:-1] > 0, closes[:-1], 1.0)
        gap_pct = np.where(np.isfinite(gap_pct), gap_pct, 0.0)
        is_gap = (gap_pct > 0.005).astype(np.float32)
        if len(is_gap) >= 10:
            gsum = np.convolve(is_gap, np.ones(10, dtype=np.float32), mode='valid')  # (len-9,)
            # gsum[k] = count of gaps in is_gap[k:k+10]
            # For bar i: the 10 most recent gaps end at bar i → is_gap[i-10:i]
            # is_gap[k] = gap from close[k] to open[k+1] → gap AT bar k+1
            # Gaps at bars i, i-1, ..., i-9 → is_gap[i-1], ..., is_gap[i-10]
            # = is_gap[i-10:i] → gsum[i-10]
            g_idx = lookback + j_idx - 10
            g_ok = (g_idx >= 0) & (g_idx < len(gsum))
            if g_ok.any():
                features[g_ok, 4] = gsum[g_idx[g_ok]] / 10.0

    # === Feature 6: volume_vol_corr (rolling corr of abs-return and volume, 20-bar) ===
    if n >= 21:
        with np.errstate(divide='ignore', invalid='ignore'):
            abs_ret = np.abs(np.diff(closes)) / np.where(closes[:-1] > 0, closes[:-1], 1.0)
        abs_ret = np.where(np.isfinite(abs_ret), abs_ret, 0.0)  # (n-1,)

        if len(abs_ret) >= 20 and len(volumes) >= 20:
            # abs_ret[k] = |close[k+1]-close[k]|/close[k] = return AT bar k+1
            # For bar i, 20 abs returns: abs_ret[i-20:i] paired with volumes[i-19:i+1]
            ar_wins = sliding_window_view(abs_ret, 20)  # (len(abs_ret)-19, 20)
            vol_wins = sliding_window_view(volumes, 20)  # (n-19, 20)

            # ar_wins[k] = abs_ret[k:k+20], represents returns at bars k+1..k+20
            # vol_wins[k] = volumes[k:k+20], represents volumes at bars k..k+19
            # For bar i: abs_ret window = abs_ret[i-20:i] → ar_wins[i-20]
            #            volume window = volumes[i-19:i+1] → vol_wins[i-19]
            # ar_wins[i-20] pairs with vol_wins[i-19] ← off by 1 in start index

            # Compute correlation: use standardized dot product
            min_len_corr = min(len(ar_wins), len(vol_wins))
            if min_len_corr > 0:
                # Align: ar_wins[k] corresponds to bar k+20, vol_wins[k+1] corresponds to bar k+20
                # So ar_wins[k] pairs with vol_wins[k+1]
                ar_aligned = ar_wins[:min_len_corr - 1]  # (m, 20)
                vol_aligned = vol_wins[1:min_len_corr]  # (m, 20)

                ar_mean = np.mean(ar_aligned, axis=1, keepdims=True)
                vol_mean = np.mean(vol_aligned, axis=1, keepdims=True)
                ar_centered = ar_aligned - ar_mean
                vol_centered = vol_aligned - vol_mean
                ar_std = np.std(ar_aligned, axis=1)
                vol_std = np.std(vol_aligned, axis=1)

                with np.errstate(divide='ignore', invalid='ignore'):
                    corr_all = np.sum(ar_centered * vol_centered, axis=1) / (20 * ar_std * vol_std)
                corr_all = np.where(np.isfinite(corr_all), corr_all, 0.0).astype(np.float32)

                # corr_all[k] = corr for ar_wins[k] / vol_wins[k+1]
                # ar_wins[k] represents bar k+20. vol_wins[k+1] represents bar k+20.
                # So corr_all[k] is the vol-vol-corr for bar k+20.
                # For output j: bar_i = lookback + j, k = bar_i - 20
                c_idx = lookback + j_idx - 20
                c_ok = (c_idx >= 0) & (c_idx < len(corr_all))
                if c_ok.any():
                    features[c_ok, 5] = corr_all[c_idx[c_ok]]

    # Sanitize NaN/Inf
    features = np.where(np.isfinite(features), features, 0.0).astype(np.float32)
    return features


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
