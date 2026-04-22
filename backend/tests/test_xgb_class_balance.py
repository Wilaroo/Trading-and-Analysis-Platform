"""
Test for the XGBoost class-balance fix in TimeSeriesGBM.train_from_features.

Why this test exists
--------------------
Phase 13 revalidation (2026-04-23) rejected 10/10 LONG setups because the AI
filter (Phase 1 of post_training_validator) returned `trades=0` — the 3-class
softprob models were collapsing to always predict DOWN/FLAT. Root cause: no
per-class balancing. The fix (2026-04-24) merges sklearn-balanced per-sample
class weights into the DMatrix `weight=` vector inside
`TimeSeriesGBM.train_from_features`.

This test proves the plumbing:
1. With `apply_class_balance=True` (default), minority-class samples are
   weighted higher than majority-class samples.
2. With `apply_class_balance=False`, behavior matches the legacy uniform path.
3. Uniqueness weights + class weights MULTIPLY and re-normalize to mean==1.

We don't train a real XGBoost model here — we validate that the weight vector
reaching the DMatrix is the one we expect. That's the logic change; everything
else in `train_from_features` is unmodified.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_xgb_class_balance.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.dl_training_utils import (  # noqa: E402
    compute_per_sample_class_weights,
)


def _skewed_y(n_total: int = 500, down_frac: float = 0.6, flat_frac: float = 0.3):
    """Generate a class-skewed label array (DOWN dominant, UP rare)."""
    n_down = int(n_total * down_frac)
    n_flat = int(n_total * flat_frac)
    n_up = n_total - n_down - n_flat
    y = np.concatenate([
        np.zeros(n_down, dtype=np.int64),
        np.ones(n_flat, dtype=np.int64),
        np.full(n_up, 2, dtype=np.int64),
    ])
    np.random.default_rng(7).shuffle(y)
    return y


def test_class_balance_weights_boost_minority():
    """
    Replicates the Phase-13 failure pattern: 60% DOWN / 30% FLAT / 10% UP.
    After class balancing, UP samples should end up with ~3× the weight of
    DOWN samples so gradient pressure is restored toward the rare class.
    """
    y = _skewed_y(500, down_frac=0.6, flat_frac=0.3)
    w = compute_per_sample_class_weights(y, num_classes=3, clip_ratio=5.0)

    # Mean is normalized to 1.0
    assert abs(float(w.mean()) - 1.0) < 1e-5

    down_mean = float(w[y == 0].mean())
    flat_mean = float(w[y == 1].mean())
    up_mean = float(w[y == 2].mean())

    # Majority weighs least, rare weighs most
    assert down_mean < flat_mean < up_mean

    # UP class (10% of the data) should weigh roughly 5× DOWN (60%)
    # before clip: 6.0, after clip(5.0): 5.0 — we require ≥3.5× with buffer
    assert up_mean / down_mean >= 3.5, f"UP/DOWN ratio = {up_mean / down_mean:.2f}"


def test_train_from_features_wires_class_balance_into_dmatrix():
    """
    Integration-style: call `train_from_features(apply_class_balance=True)`
    with a stubbed xgb.DMatrix and xgb.train. Assert the DMatrix weight= arg
    reflects class-balancing (minority class samples have higher weights).

    This is the single critical plumbing check — if the weights don't reach
    DMatrix, the fix is a no-op.
    """
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM

    y = _skewed_y(500, down_frac=0.6, flat_frac=0.3)
    X = np.random.default_rng(11).normal(size=(len(y), 8)).astype(np.float32)
    feature_names = [f"feat_{i}" for i in range(8)]

    gbm = TimeSeriesGBM(model_name="test_class_balance")

    captured_weights = {}

    def dmatrix_stub(X_arr, label=None, weight=None, feature_names=None):
        # First call is train, second is val — capture both
        key = "train" if "train" not in captured_weights else "val"
        captured_weights[key] = {
            "weight": np.asarray(weight) if weight is not None else None,
            "label": np.asarray(label),
        }
        m = MagicMock()
        m.num_row = MagicMock(return_value=len(X_arr))
        return m

    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=np.ones((100, 3)) / 3.0)
    fake_model.num_boosted_rounds = MagicMock(return_value=10)
    fake_model.best_iteration = 5

    with patch("services.ai_modules.timeseries_gbm.xgb.DMatrix", side_effect=dmatrix_stub), \
         patch("services.ai_modules.timeseries_gbm.xgb.train", return_value=fake_model), \
         patch.object(gbm, "_save_model", return_value=True):
        gbm.train_from_features(
            X=X, y=y, feature_names=feature_names,
            num_classes=3, apply_class_balance=True,
            num_boost_round=10, early_stopping_rounds=5,
        )

    assert "train" in captured_weights, "xgb.DMatrix was never called with training data"
    tw = captured_weights["train"]
    assert tw["weight"] is not None, "weight= was not passed to DMatrix"
    w = tw["weight"]
    y_train = tw["label"]

    # Minority class (2=UP) should have visibly higher mean weight than
    # majority class (0=DOWN) in the split that reached the DMatrix.
    if np.any(y_train == 0) and np.any(y_train == 2):
        down_mean = float(w[y_train == 0].mean())
        up_mean = float(w[y_train == 2].mean())
        assert up_mean > down_mean, (
            f"UP weight {up_mean:.3f} should exceed DOWN weight {down_mean:.3f} "
            "when apply_class_balance=True"
        )


def test_train_from_features_class_balance_off_keeps_uniform():
    """With apply_class_balance=False and no sample_weights, the DMatrix
    weight= should be None (legacy uniform behavior)."""
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM

    y = _skewed_y(500, down_frac=0.6, flat_frac=0.3)
    X = np.random.default_rng(11).normal(size=(len(y), 8)).astype(np.float32)
    feature_names = [f"feat_{i}" for i in range(8)]

    gbm = TimeSeriesGBM(model_name="test_class_balance_off")

    captured_weights = {}

    def dmatrix_stub(X_arr, label=None, weight=None, feature_names=None):
        key = "train" if "train" not in captured_weights else "val"
        captured_weights[key] = {"weight": weight, "label": np.asarray(label)}
        m = MagicMock()
        m.num_row = MagicMock(return_value=len(X_arr))
        return m

    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=np.ones((100, 3)) / 3.0)
    fake_model.num_boosted_rounds = MagicMock(return_value=10)
    fake_model.best_iteration = 5

    with patch("services.ai_modules.timeseries_gbm.xgb.DMatrix", side_effect=dmatrix_stub), \
         patch("services.ai_modules.timeseries_gbm.xgb.train", return_value=fake_model), \
         patch.object(gbm, "_save_model", return_value=True):
        gbm.train_from_features(
            X=X, y=y, feature_names=feature_names,
            num_classes=3, apply_class_balance=False,
            num_boost_round=10, early_stopping_rounds=5,
        )

    assert captured_weights["train"]["weight"] is None, (
        "weight= should be None when apply_class_balance=False and no sample_weights"
    )


def test_train_from_features_blends_uniqueness_with_class_balance():
    """When BOTH sample_weights and class balance are on, the resulting
    weight vector should be the element-wise product, then mean-normalized.
    """
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM

    y = _skewed_y(400, down_frac=0.6, flat_frac=0.3)
    X = np.random.default_rng(11).normal(size=(len(y), 8)).astype(np.float32)
    feature_names = [f"feat_{i}" for i in range(8)]

    # Uniqueness weights: some events are more unique than others
    rng = np.random.default_rng(3)
    uniqueness = rng.uniform(0.5, 1.5, size=len(y)).astype(np.float32)
    uniqueness = uniqueness / uniqueness.mean()  # normalize

    gbm = TimeSeriesGBM(model_name="test_blend")

    captured_weights = {}

    def dmatrix_stub(X_arr, label=None, weight=None, feature_names=None):
        key = "train" if "train" not in captured_weights else "val"
        captured_weights[key] = {
            "weight": np.asarray(weight) if weight is not None else None,
            "label": np.asarray(label),
        }
        m = MagicMock()
        m.num_row = MagicMock(return_value=len(X_arr))
        return m

    fake_model = MagicMock()
    fake_model.predict = MagicMock(return_value=np.ones((80, 3)) / 3.0)
    fake_model.num_boosted_rounds = MagicMock(return_value=10)
    fake_model.best_iteration = 5

    with patch("services.ai_modules.timeseries_gbm.xgb.DMatrix", side_effect=dmatrix_stub), \
         patch("services.ai_modules.timeseries_gbm.xgb.train", return_value=fake_model), \
         patch.object(gbm, "_save_model", return_value=True):
        gbm.train_from_features(
            X=X, y=y, feature_names=feature_names,
            num_classes=3, apply_class_balance=True,
            sample_weights=uniqueness,
            num_boost_round=10, early_stopping_rounds=5,
        )

    w = captured_weights["train"]["weight"]
    # Blended weights must be ~mean-1 across the train portion
    assert abs(float(w.mean()) - 1.0) < 0.15  # train split drifts slightly from full-set norm
    # Still have class-imbalance skew in the blend
    y_train = captured_weights["train"]["label"]
    if np.any(y_train == 0) and np.any(y_train == 2):
        assert float(w[y_train == 2].mean()) > float(w[y_train == 0].mean())
