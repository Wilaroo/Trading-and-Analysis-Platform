"""Regression test for Phase 8 DMatrix wrapping fix (2026-04-21).

Context:
  After fixing the FFD broadcast bug, Phase 8 started failing with
      TypeError: Expecting data to be a DMatrix object, got: <class 'numpy.ndarray'>
  because TimeSeriesGBM._model is an xgb.Booster (not XGBClassifier), so raw
  numpy arrays cannot be passed to .predict() — they must be wrapped in DMatrix
  with feature_names matching the trained model.

This test trains a tiny Booster and verifies:
  1. Calling .predict() on raw ndarray raises TypeError (pins XGBoost contract).
  2. Wrapping in DMatrix with feature_names works as the pipeline now does.
"""
import numpy as np
import pytest
import xgboost as xgb


@pytest.fixture(scope="module")
def tiny_booster():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((128, 6)).astype(np.float32)
    y = (X[:, 0] + X[:, 1] > 0).astype(np.int64)
    feature_names = [f"f{i}" for i in range(6)]
    dtrain = xgb.DMatrix(X, label=y, feature_names=feature_names)
    booster = xgb.train(
        {"objective": "binary:logistic", "max_depth": 2, "eta": 0.3,
         "verbosity": 0, "tree_method": "hist"},
        dtrain,
        num_boost_round=4,
    )
    return booster, feature_names


def test_booster_rejects_raw_ndarray(tiny_booster):
    """Confirms the XGBoost contract that caused the Phase 8 bug."""
    booster, _ = tiny_booster
    feats = np.zeros((3, 6), dtype=np.float32)
    with pytest.raises(TypeError, match="DMatrix"):
        booster.predict(feats)


def test_booster_accepts_dmatrix_with_feature_names(tiny_booster):
    """Confirms the fix applied in training_pipeline.py Phase 8."""
    booster, feature_names = tiny_booster
    feats = np.zeros((3, 6), dtype=np.float32)
    dm = xgb.DMatrix(feats, feature_names=feature_names)
    preds = booster.predict(dm)
    assert preds.shape == (3,)
    assert np.all((preds >= 0.0) & (preds <= 1.0))


def test_phase8_code_wraps_with_dmatrix():
    """Ensures training_pipeline.py Phase 8 uses DMatrix, not raw ndarray.

    Guards against a regression where someone simplifies the code back to
    sm._model.predict(model_feats) on a numpy array.
    """
    import pathlib
    src = pathlib.Path(
        __file__
    ).resolve().parent.parent / "services" / "ai_modules" / "training_pipeline.py"
    content = src.read_text()

    # Find the Phase 8 ensemble block
    phase8_marker = "BATCH predict through all sub-models at once"
    assert phase8_marker in content, "Phase 8 batch-predict comment missing"
    phase8_idx = content.index(phase8_marker)
    # Scope to the next ~60 lines (the ensemble batch block)
    phase8_block = content[phase8_idx: phase8_idx + 4000]

    # Sub-model predict must go through a DMatrix wrapper
    assert "DMatrix" in phase8_block, "Phase 8 missing DMatrix wrapper"
    assert "sm._model.predict(sub_dm)" in phase8_block, \
        "Sub-model predict should receive DMatrix (sub_dm), not raw ndarray"
    assert "setup_model._model.predict(setup_dm)" in phase8_block, \
        "Setup model predict should receive DMatrix (setup_dm), not raw ndarray"
    # Guard against regression: ensure we don't call predict(model_feats) directly
    assert "sm._model.predict(model_feats)" not in phase8_block, \
        "Regression: sub_model.predict(model_feats) passes ndarray to Booster"
    assert "setup_model._model.predict(model_feats)" not in phase8_block, \
        "Regression: setup_model.predict(model_feats) passes ndarray to Booster"
