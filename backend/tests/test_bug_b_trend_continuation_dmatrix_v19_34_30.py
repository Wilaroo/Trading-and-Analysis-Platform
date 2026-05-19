import inspect
def test_predict_for_setup_handles_xgb_booster_via_dmatrix():
    from services.ai_modules import timeseries_service
    src = inspect.getsource(timeseries_service)
    assert "isinstance(model._model, _xgb.Booster)" in src
    assert "_xgb.DMatrix(" in src

def test_xgboost_booster_requires_dmatrix():
    import numpy as np, xgboost as xgb
    X = np.random.RandomState(0).rand(60, 4).astype(np.float32)
    y = np.random.RandomState(1).randint(0, 3, size=60)
    booster = xgb.train(
        {"objective": "multi:softprob", "num_class": 3, "verbosity": 0},
        xgb.DMatrix(X, label=y), num_boost_round=2,
    )
    raised = False
    try: booster.predict(np.array([X[0]]))
    except Exception as e:
        if "DMatrix" in str(e): raised = True
    assert raised
