"""
Purged K-Fold + Combinatorial Purged K-Fold (CPCV) for time-series ML.

Reference: López de Prado, AFML Ch. 7 "Cross-Validation". Mlfinlab equivalents:
    mlfinlab.cross_validation.PurgedKFold
    mlfinlab.cross_validation.CombinatorialPurgedKFold

Implemented from scratch — no runtime mlfinlab dependency.

Purpose:
- Standard K-Fold leaks in time-series because event labels overlap across folds
  (a sample's label looks T bars into the future; if T+k ends up in the test fold,
  train leaks into test).
- PurgedKFold removes training events whose [entry, exit] overlaps test events.
- Embargo adds a buffer after each test fold (serial correlation).
- CPCV generates multiple train/test combinations → distribution of OOS metrics
  (stability/fragility) instead of a single point estimate.

Usage:
    splitter = PurgedKFold(event_intervals, n_splits=5, embargo_bars=10)
    for train_idx, test_idx in splitter.split():
        X_tr, X_te = X[train_idx], X[test_idx]
        ...

    cpcv = CombinatorialPurgedKFold(event_intervals, n_splits=6, n_test_splits=2, embargo_bars=10)
    oos_scores = []
    for train_idx, test_idx in cpcv.split():
        ...
    # len(oos_scores) == C(6, 2) == 15 train/test combos
"""
from __future__ import annotations
import numpy as np
from itertools import combinations
from typing import Iterator, Tuple


class PurgedKFold:
    """Time-ordered K-fold with purging + embargo."""

    def __init__(
        self,
        event_intervals: np.ndarray,
        n_splits: int = 5,
        embargo_bars: int = 0,
    ):
        if n_splits < 2:
            raise ValueError("n_splits >= 2 required")
        self.intervals = np.asarray(event_intervals, dtype=np.int64)
        assert self.intervals.ndim == 2 and self.intervals.shape[1] == 2
        self.n_splits = int(n_splits)
        self.embargo = int(embargo_bars)
        self.n_events = len(self.intervals)

    def _purge(self, train_idx: np.ndarray, test_idx: np.ndarray) -> np.ndarray:
        if len(train_idx) == 0 or len(test_idx) == 0:
            return train_idx
        t_entry = self.intervals[test_idx, 0]
        t_exit = self.intervals[test_idx, 1]
        t_min, t_max = int(t_entry.min()), int(t_exit.max() + self.embargo)

        keep = []
        for i in train_idx:
            e, x = int(self.intervals[i, 0]), int(self.intervals[i, 1])
            # Train event entirely before test window (respecting embargo-before too)
            if x < t_min - self.embargo:
                keep.append(i)
                continue
            # Train event entirely after test window + embargo buffer
            if e > t_max:
                keep.append(i)
                continue
            # Otherwise overlaps → purge
        return np.array(keep, dtype=np.int64)

    def split(self) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        indices = np.arange(self.n_events)
        fold_sizes = np.full(self.n_splits, self.n_events // self.n_splits)
        fold_sizes[: self.n_events % self.n_splits] += 1
        current = 0
        for fs in fold_sizes:
            test_idx = indices[current : current + fs]
            train_idx = np.concatenate([indices[:current], indices[current + fs :]])
            train_idx = self._purge(train_idx, test_idx)
            yield train_idx, test_idx
            current += fs


class CombinatorialPurgedKFold:
    """
    CPCV: divide into N groups, hold out K at a time. Yields C(N, K) folds.

    With N=6, K=2 → 15 train/test combos → distribution of OOS outcomes.
    """

    def __init__(
        self,
        event_intervals: np.ndarray,
        n_splits: int = 6,
        n_test_splits: int = 2,
        embargo_bars: int = 0,
    ):
        if n_splits < 2 or n_test_splits < 1 or n_test_splits >= n_splits:
            raise ValueError("Invalid splits config")
        self.intervals = np.asarray(event_intervals, dtype=np.int64)
        self.n_splits = int(n_splits)
        self.n_test_splits = int(n_test_splits)
        self.embargo = int(embargo_bars)
        self.n_events = len(self.intervals)

    def num_combinations(self) -> int:
        from math import comb
        return comb(self.n_splits, self.n_test_splits)

    def _purge(self, train_idx, test_idx):
        if len(train_idx) == 0 or len(test_idx) == 0:
            return train_idx
        t_entry = self.intervals[test_idx, 0]
        t_exit = self.intervals[test_idx, 1]
        t_min, t_max = int(t_entry.min()), int(t_exit.max() + self.embargo)
        keep = []
        for i in train_idx:
            e, x = int(self.intervals[i, 0]), int(self.intervals[i, 1])
            if x < t_min - self.embargo or e > t_max:
                keep.append(i)
        return np.array(keep, dtype=np.int64)

    def split(self) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        indices = np.arange(self.n_events)
        fold_sizes = np.full(self.n_splits, self.n_events // self.n_splits)
        fold_sizes[: self.n_events % self.n_splits] += 1
        boundaries = np.cumsum(np.concatenate([[0], fold_sizes]))
        groups = [indices[boundaries[i] : boundaries[i + 1]] for i in range(self.n_splits)]
        for test_group_ids in combinations(range(self.n_splits), self.n_test_splits):
            test_idx = np.concatenate([groups[g] for g in test_group_ids])
            train_groups = [g for i, g in enumerate(groups) if i not in test_group_ids]
            train_idx = np.concatenate(train_groups) if train_groups else np.array([], dtype=np.int64)
            train_idx = self._purge(train_idx, test_idx)
            yield train_idx, test_idx


def cpcv_stability(oos_scores: list) -> dict:
    """Summarize CPCV distribution — central tendency + fragility."""
    if not oos_scores:
        return {"mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0,
                "p05": 0.0, "p95": 0.0, "negative_pct": 0.0, "n": 0}
    arr = np.asarray(oos_scores, dtype=np.float64)
    return {
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std()),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "p05": float(np.percentile(arr, 5)),
        "p95": float(np.percentile(arr, 95)),
        "negative_pct": float((arr < 0).sum() / len(arr)),
        "n": int(len(arr)),
    }
