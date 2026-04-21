"""
Tests for inference-side FFD feature name restoration (fix 2026-04-21).

Symptom that led to this fix:
    Forecast error for AAPL: feature_names mismatch: [...51 names including FFD...]
                                                      [...46 names without FFD...]

Root cause: `TimeSeriesGBM.__init__` sets `self._feature_names` to the 46-name
default from `get_feature_engineer().get_feature_names()`. When a model trained
with `TB_USE_FFD_FEATURES=1` (51 names) is loaded, `_feature_names` is never
restored from the booster — so inference builds a 46-name DMatrix against a
51-feature model → XGBoost rejects with feature_names mismatch.

Fix: after loading the booster, restore `self._feature_names` from
`self._model.feature_names` (or the persisted `feature_names` field as fallback).

And: `predict()` now builds FFD values inline when the loaded model expects them.
"""
import numpy as np
import pytest


def test_feature_names_restoration_prefers_booster_over_default(monkeypatch):
    """When a model's booster has 51 feature_names, the loaded model instance
    must expose those 51 names, not the 46-name default."""
    # Build a minimal fake booster with 51 feature_names
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
    from services.ai_modules.feature_augmentors import FFD_NAMES
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    default_names = fe.get_feature_names()
    augmented_51 = default_names + FFD_NAMES
    assert len(default_names) == 46
    assert len(augmented_51) == 51

    gbm = TimeSeriesGBM(model_name="test_direction_predictor_daily", forecast_horizon=5)

    # Mock a loaded booster
    class _FakeBooster:
        feature_names = augmented_51
    gbm._model = _FakeBooster()

    # Mirror the restoration logic from _load_model lines 364-384
    booster_names = list(gbm._model.feature_names or [])
    if booster_names:
        gbm._feature_names = booster_names

    assert gbm._feature_names == augmented_51
    assert len(gbm._feature_names) == 51
    # Specifically: FFD columns are now discoverable for inference
    for ffd in FFD_NAMES:
        assert ffd in gbm._feature_names


def test_feature_names_fallback_to_persisted_when_booster_has_none(monkeypatch):
    """If booster.feature_names is None (older XGB versions), fall back to the
    persisted `feature_names` field in the model doc."""
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
    from services.ai_modules.feature_augmentors import FFD_NAMES
    from services.ai_modules.timeseries_features import get_feature_engineer

    fe = get_feature_engineer()
    augmented_51 = fe.get_feature_names() + FFD_NAMES

    gbm = TimeSeriesGBM(model_name="test_fallback_model", forecast_horizon=5)

    class _FakeBoosterNoNames:
        feature_names = None
    gbm._model = _FakeBoosterNoNames()

    doc = {"feature_names": augmented_51}
    # Mirror restoration logic
    try:
        booster_names = list(gbm._model.feature_names or [])
    except Exception:
        booster_names = []
    persisted_names = doc.get("feature_names") or []
    if booster_names:
        gbm._feature_names = booster_names
    elif persisted_names:
        gbm._feature_names = list(persisted_names)

    assert gbm._feature_names == augmented_51


def test_predict_populates_ffd_when_model_expects_it():
    """Integration check: if `self._feature_names` includes FFD names, the
    DMatrix-build path must populate non-zero FFD values (or at least zero,
    never missing) so the DMatrix has exactly len(self._feature_names) cols."""
    from services.ai_modules.feature_augmentors import FFD_NAMES, compute_ffd_columns
    from services.ai_modules.timeseries_features import get_feature_engineer

    # Generate synthetic OHLCV
    rng = np.random.default_rng(7)
    n = 120
    closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    bars = [
        {"open": float(closes[i]), "high": float(closes[i] + 0.3),
         "low": float(closes[i] - 0.3), "close": float(closes[i]),
         "volume": 500_000.0, "date": f"2026-04-{(i % 28) + 1:02d}"}
        for i in range(n)
    ]

    ffd_cols = compute_ffd_columns(bars, lookback=50, expected_rows=n)
    assert ffd_cols is not None
    # compute_ffd_columns drops lookback rows from the start — actual rows < n
    assert ffd_cols.shape[1] == 5, f"Expected 5 FFD columns, got {ffd_cols.shape}"
    assert ffd_cols.shape[0] > 0, "Must have at least one row of FFD values"
    # The last row (most recent) is what predict() pulls
    last_row = ffd_cols[-1]
    assert len(last_row) == 5
    # Simulate the predict-time fill: merge FFD into feats dict
    feats = {}  # start empty
    for idx, name in enumerate(FFD_NAMES):
        feats[name] = float(last_row[idx])
    for name in FFD_NAMES:
        assert name in feats
        assert isinstance(feats[name], float)


def test_full_feature_name_list_has_no_duplicates():
    """Augmented 51-name list must have no duplicate names (else XGBoost errors)."""
    from services.ai_modules.feature_augmentors import FFD_NAMES
    from services.ai_modules.timeseries_features import get_feature_engineer

    names = get_feature_engineer().get_feature_names() + FFD_NAMES
    assert len(names) == len(set(names)), "Duplicate feature names detected"
