"""
Event Intervals — track each training sample's (entry_bar, exit_bar) span.

Reference: López de Prado, AFML Ch. 4 "Sample Weights". Mlfinlab equivalent:
`sample_weights.concurrency.num_concurrent_events` and
`sampling.concurrent.get_num_concurrent_events`.

We implement from scratch so we stay dependency-free and GPU-friendly.

Usage:
    from services.ai_modules.event_intervals import (
        build_event_intervals_from_triple_barrier,
        concurrency_weights,
        average_uniqueness,
    )

    # After labeling with triple_barrier_labels:
    intervals = build_event_intervals_from_triple_barrier(
        highs, lows, closes, entry_indices,
        pt_atr_mult, sl_atr_mult, max_bars, atr_period,
    )
    # intervals[i] = (entry_idx, exit_idx) for sample i

    weights = concurrency_weights(intervals)   # one scalar per sample in [0, 1]
    # Feed to XGBoost: DMatrix(..., weight=weights)
"""
from __future__ import annotations
import numpy as np
from typing import Tuple, List

from services.ai_modules.triple_barrier_labeler import atr as _atr


def build_event_intervals_from_triple_barrier(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    entry_indices: np.ndarray,
    pt_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.0,
    max_bars: int = 20,
    atr_period: int = 14,
) -> np.ndarray:
    """
    For each entry_index, determine which bar the triple-barrier hit (or time-out).

    Returns:
        intervals: int64 array shape (N, 2) of [entry_idx, exit_idx]
                   exit_idx is the first bar index where a barrier was breached,
                   or entry_idx + max_bars if time-exit.
    """
    highs = np.asarray(highs, dtype=np.float64)
    lows = np.asarray(lows, dtype=np.float64)
    closes = np.asarray(closes, dtype=np.float64)
    entry_indices = np.asarray(entry_indices, dtype=np.int64)

    n_bars = len(closes)
    n_events = len(entry_indices)
    intervals = np.empty((n_events, 2), dtype=np.int64)
    atr_series = _atr(highs, lows, closes, period=atr_period)

    for i, e in enumerate(entry_indices):
        if e < 0 or e >= n_bars:
            intervals[i] = [e, e]
            continue
        a = atr_series[e] if e < len(atr_series) else 0.0
        if a <= 0 or not np.isfinite(a):
            intervals[i] = [e, min(e + max_bars, n_bars - 1)]
            continue
        p0 = closes[e]
        pt = p0 + pt_atr_mult * a
        sl = p0 - sl_atr_mult * a
        end = min(e + max_bars, n_bars - 1)
        hit = end
        for j in range(e + 1, end + 1):
            if highs[j] >= pt or lows[j] <= sl:
                hit = j
                break
        intervals[i] = [e, hit]
    return intervals


def num_concurrent_events(intervals: np.ndarray, n_bars: int) -> np.ndarray:
    """For each bar, count how many event intervals contain it.

    Args:
        intervals: (N, 2) [entry_idx, exit_idx] inclusive
        n_bars:    total number of underlying bars

    Returns:
        count: int64 array shape (n_bars,)
    """
    count = np.zeros(n_bars, dtype=np.int64)
    for e, x in intervals:
        if e >= n_bars or x < 0:
            continue
        lo, hi = max(0, int(e)), min(n_bars - 1, int(x))
        count[lo:hi + 1] += 1
    return count


def average_uniqueness(intervals: np.ndarray, n_bars: int) -> np.ndarray:
    """
    Average uniqueness of each event: mean(1 / concurrent_count) across event life.
    Reference: AFML eq. 4.2.

    Returns:
        uniqueness: float32 array shape (N,), values in (0, 1]
    """
    conc = num_concurrent_events(intervals, n_bars).astype(np.float64)
    safe_conc = np.where(conc > 0, conc, 1.0)
    uniqueness = np.zeros(len(intervals), dtype=np.float32)
    for i, (e, x) in enumerate(intervals):
        e = int(max(0, e))
        x = int(min(n_bars - 1, x))
        if x < e:
            uniqueness[i] = 1.0
            continue
        uniqueness[i] = float(np.mean(1.0 / safe_conc[e:x + 1]))
    return uniqueness


def concurrency_weights(intervals: np.ndarray, n_bars: int = None) -> np.ndarray:
    """
    Convenience wrapper: returns sample weights = avg_uniqueness.
    Normalizes so mean(weights) = 1.0 (XGBoost expects this scaling).
    """
    if n_bars is None:
        n_bars = int(intervals.max()) + 2 if len(intervals) else 1
    w = average_uniqueness(intervals, n_bars)
    mean_w = float(w.mean()) if len(w) else 1.0
    if mean_w > 0:
        w = w / mean_w
    return w.astype(np.float32)


def max_event_interval_overlap(
    train_intervals: np.ndarray,
    test_intervals: np.ndarray,
) -> int:
    """
    Return the count of train events that overlap ANY test event.
    Used by the leakage auto-check in post_training_validator.
    """
    if len(train_intervals) == 0 or len(test_intervals) == 0:
        return 0
    test_min = int(test_intervals[:, 0].min())
    test_max = int(test_intervals[:, 1].max())
    overlaps = 0
    for e, x in train_intervals:
        if int(x) < test_min or int(e) > test_max:
            continue
        # Fine check
        for te, tx in test_intervals:
            if int(e) <= int(tx) and int(x) >= int(te):
                overlaps += 1
                break
    return overlaps
