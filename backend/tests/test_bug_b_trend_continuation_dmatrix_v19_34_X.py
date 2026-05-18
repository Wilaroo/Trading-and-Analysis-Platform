"""v19.34.X (Feb 2026) — Bug B: Setup-specific XGBoost Booster
prediction must wrap features in DMatrix.

Before this fix, `predict_for_setup` called `model._model.predict(ndarray)`
directly. For sklearn-style wrappers that's fine; for raw `xgb.Booster`
objects (the type used by TREND_CONTINUATION's setup-specific model)
this crashed with:
    Setup model TREND_CONTINUATION prediction failed:
    ('Expecting data to be a DMatrix object, got: ', <class 'numpy.ndarray'>)

The setup was silently downgraded to the generic direction_predictor_5min
fallback — effectively no setup-specific inference for trend continuation
trades.

Fix: detect `xgb.Booster` and wrap in DMatrix before predict().
"""
from __future__ import annotations

import inspect


def test_predict_for_setup_handles_xgb_booster_via_dmatrix():
    """Source-level check — the Booster branch must exist and call
    `xgb.DMatrix(...)` before `model._model.predict(...)`.
    """
    from services.ai_modules import timeseries_service
    src = inspect.getsource(timeseries_service)
    # Must contain the Booster-detect + DMatrix-wrap branch.
    assert "isinstance(model._model, _xgb.Booster)" in src, (
        "predict_for_setup is missing the xgb.Booster detection branch."
    )
    assert "_xgb.DMatrix(" in src, (
        "predict_for_setup must wrap features in DMatrix for Booster models."
    )
    # And the ndarray path for sklearn-style wrappers must still exist.
    assert "pred_raw = model._model.predict(feature_vector)" in src, (
        "Non-Booster fallback path was removed."
    )


def test_xgboost_booster_requires_dmatrix_for_predict():
    """Sanity check on the underlying assumption — a raw Booster with
    multi:softprob objective trained on 3-class targets returns a
    (n, 3) probability matrix, but ONLY when fed a DMatrix. Calling
    predict() with a numpy ndarray raises a TypeError.
    """
    import numpy as np
    import xgboost as xgb

    # Tiny 3-class booster
    X = np.random.RandomState(0).rand(60, 4).astype(np.float32)
    y = np.random.RandomState(1).randint(0, 3, size=60)
    dtrain = xgb.DMatrix(X, label=y)
    booster = xgb.train(
        {"objective": "multi:softprob", "num_class": 3, "verbosity": 0},
        dtrain, num_boost_round=2,
    )

    feature_vector = np.array([X[0]])  # ndarray, NOT a DMatrix
    raised = False
    try:
        booster.predict(feature_vector)
    except (TypeError, ValueError, Exception) as e:
        msg = str(e)
        if "DMatrix" in msg:
            raised = True
    assert raised, (
        "Test premise broken: this XGBoost version no longer raises on "
        "ndarray-into-Booster.predict; the Bug B fix may be unnecessary."
    )

    # And the wrapped DMatrix path returns valid probabilities.
    dm = xgb.DMatrix(feature_vector, feature_names=[f"f{i}" for i in range(4)])
    pred = booster.predict(dm)
    assert pred.shape == (1, 3)
    # Probabilities sum to ~1
    assert abs(float(pred[0].sum()) - 1.0) < 1e-4
