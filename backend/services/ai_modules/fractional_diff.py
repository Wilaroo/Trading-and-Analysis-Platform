"""
Fractional Differentiation — preserve memory while achieving stationarity.

Reference: López de Prado, AFML Ch. 5 "Fractionally Differentiated Features".
Mlfinlab equivalent: `features.fracdiff.frac_diff_ffd` (we implement natively).

Motivation:
    Integer differentiation (first-difference = returns) destroys price memory.
    Raw prices have memory but are non-stationary — ML models hate them.
    Fractional differentiation (d ∈ (0, 1)) sits in between: stationary AND
    retains long-range correlation.

Two algorithms:
    1. frac_diff (standard):          expanding window, higher memory preserved
    2. frac_diff_ffd (fixed-width):   O(N*w) memory, better for ML features
                                      ↑ preferred for production

Adaptive d:
    For each series, binary-search the SMALLEST d that passes an ADF
    stationarity test. Lower d = more memory preserved. This matches López de
    Prado's "lowest d that passes" recommendation.

Usage:
    from services.ai_modules.fractional_diff import frac_diff_ffd, find_min_d

    d_opt = find_min_d(closes, adf_threshold=-2.87)
    ffd = frac_diff_ffd(closes, d=d_opt, threshold=1e-4)
    # Use `ffd` as a feature column alongside returns/prices.
"""
from __future__ import annotations
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.stattools import adfuller
    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False


def _get_weights(d: float, size: int) -> np.ndarray:
    """Binomial weights for fractional differentiation (expanding window)."""
    w = [1.0]
    for k in range(1, size):
        w_k = -w[-1] * (d - k + 1) / k
        w.append(w_k)
    return np.array(w[::-1], dtype=np.float64)


def _get_weights_ffd(d: float, threshold: float = 1e-4, max_size: int = 500) -> np.ndarray:
    """
    Fixed-width window weights — truncate when weight magnitude < threshold.
    This gives O(N*w) memory where w is typically ~50-200 for reasonable
    thresholds.
    """
    w = [1.0]
    for k in range(1, max_size):
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        w.append(w_k)
    return np.array(w[::-1], dtype=np.float64)


def frac_diff_ffd(
    series: np.ndarray,
    d: float,
    threshold: float = 1e-4,
) -> np.ndarray:
    """
    Fixed-Width Window Fractional Differentiation (FFD).

    Args:
        series:    1-D input series (prices, log-prices, etc.)
        d:         fractional differentiation order (0 < d < 1)
        threshold: drop weights below this magnitude → sets window size

    Returns:
        ffd:  same-length array. Values before the weight-window length are NaN.
    """
    series = np.asarray(series, dtype=np.float64)
    if len(series) < 2:
        return np.full_like(series, np.nan)

    w = _get_weights_ffd(d, threshold=threshold)
    w_size = len(w)

    out = np.full(len(series), np.nan, dtype=np.float64)
    for i in range(w_size - 1, len(series)):
        window = series[i - w_size + 1 : i + 1]
        if np.isnan(window).any():
            continue
        out[i] = float(np.dot(w, window))
    return out


def find_min_d(
    series: np.ndarray,
    adf_threshold: float = -2.87,   # 5% critical value
    threshold: float = 1e-4,
    d_low: float = 0.0,
    d_high: float = 1.0,
    n_iter: int = 15,
) -> float:
    """
    Binary-search the LOWEST d such that frac_diff_ffd(series, d) passes ADF.

    Args:
        series:         1-D input (usually log-prices)
        adf_threshold:  ADF test statistic must be below this to be "stationary"
        n_iter:         bisection iterations

    Returns:
        d_opt:  smallest d passing ADF. If nothing passes, returns d_high.
    """
    if not _HAS_STATSMODELS:
        logger.warning("statsmodels not available — returning default d=0.4")
        return 0.4

    series = np.asarray(series, dtype=np.float64)
    if len(series) < 100:
        return 0.4

    def _passes(d: float) -> bool:
        try:
            ffd = frac_diff_ffd(series, d, threshold=threshold)
            valid = ffd[~np.isnan(ffd)]
            if len(valid) < 50:
                return False
            stat, _, _, _, _, _ = adfuller(valid, maxlag=1, regression="c", autolag=None)
            return stat < adf_threshold
        except Exception:
            return False

    # If even d=1 doesn't pass, the series is hopeless — return 1.0
    if not _passes(d_high):
        return float(d_high)
    # If d=0 already passes, use 0 (already stationary)
    if _passes(d_low):
        return float(d_low)

    lo, hi = d_low, d_high
    for _ in range(n_iter):
        mid = (lo + hi) / 2
        if _passes(mid):
            hi = mid
        else:
            lo = mid
        if abs(hi - lo) < 0.01:
            break
    return float(hi)


def compute_ffd_features(
    closes: np.ndarray,
    d_cache: Optional[dict] = None,
    cache_key: Optional[str] = None,
    d_values: Optional[list] = None,
) -> dict:
    """
    Build a small family of FFD features for feature_engineer consumption.

    Returns dict:
        "ffd_close_adaptive":   FFD of log(close) using adaptive d
        "ffd_close_03":         FFD of log(close) with d=0.3
        "ffd_close_05":         FFD of log(close) with d=0.5
        "ffd_close_07":         FFD of log(close) with d=0.7
        "ffd_optimal_d":        the adaptive d found for this series
    """
    closes = np.asarray(closes, dtype=np.float64)
    closes = np.where(closes <= 0, 1e-8, closes)
    log_c = np.log(closes)

    # Adaptive d
    d_opt = None
    if d_cache is not None and cache_key in d_cache:
        d_opt = d_cache[cache_key]
    else:
        d_opt = find_min_d(log_c)
        if d_cache is not None and cache_key:
            d_cache[cache_key] = d_opt

    if d_values is None:
        d_values = [0.3, 0.5, 0.7]

    out = {
        "ffd_close_adaptive": frac_diff_ffd(log_c, d_opt),
        "ffd_optimal_d": float(d_opt),
    }
    for d in d_values:
        out[f"ffd_close_{int(d * 10):02d}"] = frac_diff_ffd(log_c, d)
    return out
