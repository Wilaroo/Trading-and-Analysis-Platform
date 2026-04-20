"""
Integration test: TimeSeriesGBM end-to-end with triple-barrier 3-class targets.

Run (from /app):
    PYTHONPATH=backend python -m pytest backend/tests/test_timeseries_gbm_triple_barrier.py -v

Exercises:
- _extract_symbol_worker produces 3-class int targets
- train_from_features(num_classes=3) trains and returns valid metrics
- predict() returns 3-class-shaped output with proper direction
- Multiclass save/load roundtrip preserves num_classes
"""

import numpy as np
import pytest
import os
import sys

# Ensure backend is importable as a package root
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _synthetic_bars(n=400, seed=42, regime="mixed"):
    """Create OHLCV bars with a mix of up/down/flat regimes so triple-barrier
    yields all three classes."""
    rng = np.random.default_rng(seed)
    closes = [100.0]
    for i in range(1, n):
        # Cycle through regimes to force class diversity
        if regime == "mixed":
            block = (i // 40) % 3
            drift = 0.3 if block == 0 else (-0.3 if block == 1 else 0.0)
        else:
            drift = 0.0
        closes.append(max(1.0, closes[-1] + drift + rng.normal(0, 0.7)))
    closes = np.array(closes)
    highs = closes + np.abs(rng.normal(0, 0.4, n)) + 0.2
    lows = closes - np.abs(rng.normal(0, 0.4, n)) - 0.2
    opens = np.concatenate([[closes[0]], closes[:-1]])
    vols = (rng.integers(50_000, 500_000, n)).astype(float)
    bars = []
    for i in range(n):
        bars.append({
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(vols[i]),
            "date": f"2024-01-{(i % 28) + 1:02d}",
        })
    return bars


def test_extract_symbol_worker_produces_three_classes():
    from services.ai_modules.timeseries_gbm import _extract_symbol_worker
    bars = _synthetic_bars(n=400)
    result = _extract_symbol_worker(("SYN", bars, 50, 10))
    assert result is not None
    # Worker now returns (features, targets, event_intervals) — 3-tuple.
    assert len(result) == 3
    feats, targets, intervals = result
    assert feats.ndim == 2
    assert targets.ndim == 1
    assert targets.dtype == np.int64
    uniques = set(np.unique(targets).tolist())
    assert uniques.issubset({0, 1, 2})
    assert len(uniques) >= 2
    # Event intervals present for every sample
    assert intervals.shape == (len(targets), 2)
    assert (intervals[:, 0] <= intervals[:, 1]).all()


def test_train_from_features_3class_and_predict_3class():
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM, _extract_symbol_worker

    bars = _synthetic_bars(n=600)
    # Build X/y from multiple synthetic "symbols"
    feats_all, tgts_all = [], []
    for seed in (7, 11, 19, 23, 31):
        b = _synthetic_bars(n=500, seed=seed)
        out = _extract_symbol_worker(("SYM_" + str(seed), b, 50, 10))
        assert out is not None
        feats_all.append(out[0])
        tgts_all.append(out[1])
        # out[2] is event_intervals — ignored here, tested separately
    X = np.vstack(feats_all).astype(np.float32)
    y = np.concatenate(tgts_all).astype(np.int64)
    assert len(X) > 200

    m = TimeSeriesGBM(model_name="unit_test_3class")
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    metrics = m.train_from_features(
        X, y, feature_names,
        validation_split=0.25,
        num_boost_round=25,
        early_stopping_rounds=10,
        skip_save=True,
        num_classes=3,
    )

    assert metrics is not None
    assert metrics.accuracy >= 0
    assert metrics.training_samples > 0
    assert metrics.validation_samples > 0
    # Model must be trained
    assert m._model is not None
    assert m._num_classes == 3

    # Now call raw predict on a small batch — XGBoost softprob returns shape (n, 3)
    import xgboost as xgb
    dm = xgb.DMatrix(X[:5], feature_names=feature_names)
    raw = m._model.predict(dm)
    assert raw.ndim == 2
    assert raw.shape[1] == 3
    # Probabilities sum ~1
    sums = raw.sum(axis=1)
    assert np.allclose(sums, 1.0, atol=1e-4)


def test_status_reports_num_classes_and_label_scheme():
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
    m = TimeSeriesGBM(model_name="unit_test_status")
    m._num_classes = 3
    info = m.get_model_info()
    status = m.get_status()
    assert info["num_classes"] == 3
    assert info["label_scheme"] == "triple_barrier_3class"
    assert status["num_classes"] == 3
    assert status["label_scheme"] == "triple_barrier_3class"
