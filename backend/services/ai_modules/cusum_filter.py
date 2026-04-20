"""
CUSUM Event Filter — volatility-aware sampling.

Reference: López de Prado, AFML Ch. 2 "Symmetric CUSUM Filter".
Mlfinlab equivalent: `filters.filters.cusum_filter` (we implement natively).

Motivation:
    Labeling every bar wastes compute and dilutes signal with redundant,
    low-information samples. CUSUM detects only the bars where price has
    moved meaningfully since the last event — these are the informative
    entry points a discretionary trader would actually consider.

Expected impact (AFML reports):
    • 70-90% fewer training samples
    • 3-8pp accuracy improvement (less noise, more signal)
    • Models make fewer, higher-conviction predictions

Algorithm (Symmetric CUSUM):
    1. Compute log returns r[i] = ln(close[i] / close[i-1])
    2. Maintain running sums:
           S_pos[i] = max(0, S_pos[i-1] + r[i] - mean_shift)
           S_neg[i] = min(0, S_neg[i-1] + r[i] - mean_shift)
    3. Emit event when |S| exceeds threshold h, then reset that side.

Threshold calibration:
    We auto-tune h so events fire at a target density (events/year).
    Default: 100 events/year/symbol (tunable via config).

Usage:
    from services.ai_modules.cusum_filter import cusum_events, calibrate_h

    bars = [...]                            # OHLCV list
    closes = np.array([b["close"] for b in bars])
    h = calibrate_h(closes, target_events_per_year=100, bars_per_year=252*390)
    event_idx = cusum_events(closes, h)
    # event_idx = array of bar indices where CUSUM fired

Environment flag:
    TB_USE_CUSUM_SAMPLING=1  enables CUSUM event filtering globally in the
                             training pipeline. Default: 0 (off → all bars).
"""
from __future__ import annotations
import numpy as np
from typing import Optional
import os


def _log_returns(closes: np.ndarray) -> np.ndarray:
    closes = np.asarray(closes, dtype=np.float64)
    closes = np.where(closes <= 0, 1e-8, closes)
    return np.diff(np.log(closes))


def cusum_events(
    closes: np.ndarray,
    h: float,
    mean_shift: float = 0.0,
) -> np.ndarray:
    """
    Symmetric CUSUM event detector.

    Args:
        closes:     Close price series (len N).
        h:          Threshold (in log-return units).
        mean_shift: Optional drift adjustment (default 0).

    Returns:
        event_idx:  int64 array of BAR INDICES (relative to `closes`) where
                    CUSUM fired. Index 0 never fires (no prior return).
    """
    if len(closes) < 2:
        return np.array([], dtype=np.int64)
    returns = _log_returns(closes)

    events = []
    s_pos = 0.0
    s_neg = 0.0
    for i, r in enumerate(returns):
        r_adj = r - mean_shift
        s_pos = max(0.0, s_pos + r_adj)
        s_neg = min(0.0, s_neg + r_adj)
        if s_pos >= h:
            # Bar index in `closes` is i+1 (returns[i] = close[i+1]/close[i])
            events.append(i + 1)
            s_pos = 0.0
            s_neg = 0.0
        elif s_neg <= -h:
            events.append(i + 1)
            s_pos = 0.0
            s_neg = 0.0
    return np.array(events, dtype=np.int64)


def calibrate_h(
    closes: np.ndarray,
    target_events_per_year: int = 100,
    bars_per_year: int = 252 * 390,   # intraday minutes; override for other frames
    h_low: float = 1e-4,
    h_high: float = 0.5,
    n_iter: int = 30,
) -> float:
    """
    Binary-search threshold h so CUSUM fires ~target events per year.

    Args:
        closes:                close price series
        target_events_per_year: events/year density target
        bars_per_year:         how many bars = 1 year at this timeframe
                               (252 days × 390 min for 1-min bars;
                                252 × 78 for 5-min; 252 × 65 for hourly;
                                252 for daily)
        h_low, h_high:         search bounds
        n_iter:                bisection iterations

    Returns:
        h:  threshold achieving ~target density
    """
    if len(closes) < 2:
        return 0.01
    n_bars = len(closes)
    years = max(n_bars / bars_per_year, 1e-6)
    target_n = int(target_events_per_year * years)
    if target_n < 1:
        target_n = 1

    lo, hi = h_low, h_high
    best_h = (lo + hi) / 2
    for _ in range(n_iter):
        mid = (lo + hi) / 2
        n = len(cusum_events(closes, mid))
        if n > target_n:
            lo = mid   # too many events → raise threshold
        else:
            hi = mid   # too few → lower threshold
        best_h = mid
        if abs(hi - lo) < 1e-6:
            break
    return float(best_h)


def bars_per_year_for(bar_size: str) -> int:
    """Rough mapping from bar_size string to bars-per-year for calibration."""
    s = (bar_size or "").lower().strip()
    if s == "1 min":
        return 252 * 390
    if s == "5 mins":
        return 252 * 78
    if s == "15 mins":
        return 252 * 26
    if s == "30 mins":
        return 252 * 13
    if s == "1 hour":
        return 252 * 7
    if s == "4 hours":
        return 252 * 2
    if s == "1 day":
        return 252
    if s == "1 week":
        return 52
    return 252 * 78   # sensible default


def cusum_enabled() -> bool:
    """Feature flag: env var TB_USE_CUSUM_SAMPLING=1."""
    return os.environ.get("TB_USE_CUSUM_SAMPLING", "0") in ("1", "true", "True", "YES")


def filter_entry_indices(
    entry_indices: np.ndarray,
    closes: np.ndarray,
    bar_size: str = "5 mins",
    target_events_per_year: int = 100,
    min_distance: int = 1,
) -> np.ndarray:
    """
    Filter a dense array of candidate entry indices down to CUSUM-only events.

    Args:
        entry_indices: candidate bars (e.g. arange(50, N-fh))
        closes:        close price series
        bar_size:      for bars_per_year calibration
        target_events_per_year: density target
        min_distance:  minimum spacing between events (bars)

    Returns:
        filtered: int64 array — subset of entry_indices where CUSUM fired
    """
    if len(entry_indices) == 0 or len(closes) < 2:
        return np.asarray(entry_indices, dtype=np.int64)

    bpy = bars_per_year_for(bar_size)
    h = calibrate_h(closes, target_events_per_year, bars_per_year=bpy)
    ev = cusum_events(closes, h)

    if len(ev) == 0:
        return np.asarray(entry_indices, dtype=np.int64)   # fallback to all

    # Enforce min_distance
    if min_distance > 1 and len(ev) > 1:
        keep = [ev[0]]
        for i in ev[1:]:
            if i - keep[-1] >= min_distance:
                keep.append(i)
        ev = np.array(keep, dtype=np.int64)

    # Intersection with the candidate entry_indices (we only care about events
    # within the labeling-eligible window).
    entry_set = set(entry_indices.tolist())
    filtered = np.array([i for i in ev.tolist() if i in entry_set], dtype=np.int64)
    return filtered
