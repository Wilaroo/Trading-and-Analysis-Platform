"""Integration: train_from_features with sample_weights (uniqueness weighting).

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_sample_weights_integration.py -v
"""
import numpy as np
import pytest

from services.ai_modules.timeseries_gbm import TimeSeriesGBM, _extract_symbol_worker
from services.ai_modules.event_intervals import concurrency_weights


def _synthetic_bars(n=500, seed=42):
    rng = np.random.default_rng(seed)
    closes = [100.0]
    for i in range(1, n):
        block = (i // 40) % 3
        drift = 0.3 if block == 0 else (-0.3 if block == 1 else 0.0)
        closes.append(max(1.0, closes[-1] + drift + rng.normal(0, 0.7)))
    closes = np.array(closes)
    highs = closes + np.abs(rng.normal(0, 0.4, n)) + 0.2
    lows = closes - np.abs(rng.normal(0, 0.4, n)) - 0.2
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return [{"open": float(o), "high": float(h), "low": float(l), "close": float(c),
             "volume": 100000, "date": f"2024-01-{(i % 28) + 1:02d}"}
            for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))]


def test_train_with_sample_weights_runs():
    """Train succeeds with uniqueness weights applied."""
    feats, tgts, weights = [], [], []
    for seed in (7, 11, 19):
        bars = _synthetic_bars(n=500, seed=seed)
        out = _extract_symbol_worker(("SYM_" + str(seed), bars, 50, 10))
        assert out is not None
        f, t, iv = out
        n_bars = int(iv[:, 1].max()) + 2 if len(iv) else 1
        w = concurrency_weights(iv, n_bars=n_bars)
        feats.append(f)
        tgts.append(t)
        weights.append(w)

    X = np.vstack(feats).astype(np.float32)
    y = np.concatenate(tgts).astype(np.int64)
    W = np.concatenate(weights).astype(np.float32)

    # Sample weights should have mean ~1.0 (normalization invariant)
    assert abs(W.mean() - 1.0) < 0.5

    m = TimeSeriesGBM(model_name="test_weighted_train")
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    metrics = m.train_from_features(
        X, y, feature_names,
        validation_split=0.25, num_boost_round=20,
        early_stopping_rounds=10, skip_save=True,
        num_classes=3, sample_weights=W,
    )
    assert metrics is not None
    assert metrics.training_samples > 0
    assert m._model is not None


def test_train_without_weights_still_works():
    """Backward compat: sample_weights=None still works."""
    feats, tgts = [], []
    for seed in (5, 13):
        bars = _synthetic_bars(n=400, seed=seed)
        out = _extract_symbol_worker(("SYM_" + str(seed), bars, 50, 10))
        assert out is not None
        feats.append(out[0])
        tgts.append(out[1])

    X = np.vstack(feats).astype(np.float32)
    y = np.concatenate(tgts).astype(np.int64)

    m = TimeSeriesGBM(model_name="test_unweighted_train")
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    metrics = m.train_from_features(
        X, y, feature_names, validation_split=0.25,
        num_boost_round=15, early_stopping_rounds=10,
        skip_save=True, num_classes=3, sample_weights=None,
    )
    assert metrics.training_samples > 0
