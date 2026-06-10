"""
v320 Tier-1a — CPCV (Combinatorial Purged Cross-Validation) wired into GBM models.

Synthetic pinning tests — container/DGX-safe: no DB, no IB, no GPU required.

Pins:
  1. ModelMetrics carries the new cpcv_* fields (and they persist via to_dict()).
  2. _cpcv_fallback_intervals produces consecutive [i, i+horizon] intervals.
  3. CombinatorialPurgedKFold yields C(6,2)=15 folds with ZERO train/test index
     overlap and full purge+embargo separation.
  4. run_gbm_cpcv on SIGNAL data → high OOS accuracy, positive edge, LOW PBO.
  5. run_gbm_cpcv on PURE NOISE → ~zero edge, HIGH PBO (overfit detector works).
  6. Env kill-switch TB_GBM_CPCV=0 and small-sample guard both skip cleanly.
  7. Mismatched event_intervals fall back to conservative intervals (no crash).
  8. train_from_features populates cpcv metrics end-to-end (3-class and binary).

Run (DGX, from backend/):  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_gbm_cpcv_v320.py -v
Run (container):           cd /app/backend && python -m pytest tests/test_gbm_cpcv_v320.py -v
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ai_modules.timeseries_gbm import (  # noqa: E402
    ModelMetrics,
    TimeSeriesGBM,
    _cpcv_fallback_intervals,
    run_gbm_cpcv,
)
from services.ai_modules.purged_cpcv import CombinatorialPurgedKFold  # noqa: E402


PARAMS_3C = {
    "objective": "multi:softprob",
    "num_class": 3,
    "eval_metric": "mlogloss",
    "tree_method": "hist",
    "device": "cpu",
    "max_depth": 4,
    "learning_rate": 0.1,
    "verbosity": 0,
    "seed": 42,
}


def _signal_data(n=2400, n_feat=10, seed=7):
    """3-class data with a real learnable signal in features 0/1."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, n_feat)).astype(np.float32)
    latent = X[:, 0] + 0.6 * X[:, 1] + 0.25 * rng.normal(size=n)
    y = np.where(latent > 0.45, 2, np.where(latent < -0.45, 0, 1)).astype(np.int64)
    return X, y


def _noise_data(n=2400, n_feat=10, seed=11):
    """3-class data with NO learnable signal at all."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, n_feat)).astype(np.float32)
    y = rng.integers(0, 3, size=n).astype(np.int64)
    return X, y


# ── 1. dataclass fields ──────────────────────────────────────────────────────

def test_metrics_dataclass_has_cpcv_fields():
    d = ModelMetrics().to_dict()
    for k in ("cpcv_n_folds", "cpcv_oos_acc_mean", "cpcv_oos_acc_std",
              "cpcv_oos_acc_p05", "cpcv_oos_acc_min", "cpcv_edge_mean", "cpcv_pbo"):
        assert k in d, f"missing ModelMetrics field {k}"
    assert d["cpcv_n_folds"] == 0
    assert d["cpcv_pbo"] == 0.0


# ── 2. fallback intervals ────────────────────────────────────────────────────

def test_fallback_intervals_shape_and_horizon():
    iv = _cpcv_fallback_intervals(100, 5)
    assert iv.shape == (100, 2)
    assert int(iv[0, 0]) == 0 and int(iv[0, 1]) == 5
    assert np.all(iv[:, 1] - iv[:, 0] == 5)
    # horizon floor of 1
    iv0 = _cpcv_fallback_intervals(10, 0)
    assert np.all(iv0[:, 1] - iv0[:, 0] == 1)


# ── 3. splitter integrity (purge + embargo) ──────────────────────────────────

def test_cpcv_no_train_test_overlap_after_purge():
    embargo = 5
    iv = _cpcv_fallback_intervals(600, 5)
    splitter = CombinatorialPurgedKFold(iv, n_splits=6, n_test_splits=2, embargo_bars=embargo)
    n_folds = 0
    for tr, te in splitter.split():
        n_folds += 1
        assert len(np.intersect1d(tr, te)) == 0, "train/test share indices"
        t_min = int(iv[te, 0].min())
        t_max = int(iv[te, 1].max()) + embargo
        for j in tr:
            e, x = int(iv[j, 0]), int(iv[j, 1])
            assert x < t_min - embargo or e > t_max, (
                f"purge/embargo violated: train event [{e},{x}] inside test window "
                f"[{t_min - embargo},{t_max}]"
            )
    assert n_folds == 15, f"C(6,2) should be 15 folds, got {n_folds}"


# ── 4/5. signal vs noise → PBO behaves like an overfit detector ──────────────

def test_run_gbm_cpcv_signal_low_pbo(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV_BOOST_ROUNDS", "40")
    X, y = _signal_data()
    res = run_gbm_cpcv(X, y, None, None, PARAMS_3C, num_boost_round=40,
                       num_classes=3, forecast_horizon=5, model_name="t_signal")
    assert res["cpcv_n_folds"] == 14  # C(6,2)=15 minus the {first,last} combo whose span-purge empties train
    assert res["cpcv_oos_acc_mean"] > 0.55, f"signal model should learn, got {res}"
    assert res["cpcv_edge_mean"] > 0.05, f"signal model should beat baseline, got {res}"
    assert res["cpcv_pbo"] <= 0.2, f"signal model should have LOW PBO, got {res}"


def test_run_gbm_cpcv_noise_high_pbo(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV_BOOST_ROUNDS", "40")
    X, y = _noise_data()
    res = run_gbm_cpcv(X, y, None, None, PARAMS_3C, num_boost_round=40,
                       num_classes=3, forecast_horizon=5, model_name="t_noise")
    assert res["cpcv_n_folds"] == 14  # C(6,2)=15 minus the {first,last} combo whose span-purge empties train
    assert abs(res["cpcv_edge_mean"]) < 0.06, f"noise model should have ~no edge, got {res}"
    assert res["cpcv_pbo"] >= 0.3, f"noise model should have HIGH PBO, got {res}"


# ── 6. guards ────────────────────────────────────────────────────────────────

def test_run_gbm_cpcv_env_kill_switch(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV", "0")
    X, y = _signal_data(n=1200)
    res = run_gbm_cpcv(X, y, None, None, PARAMS_3C, num_boost_round=40,
                       num_classes=3, forecast_horizon=5)
    assert res["cpcv_n_folds"] == 0


def test_run_gbm_cpcv_too_few_samples():
    X, y = _signal_data(n=120)  # < n_splits * 50 = 300
    res = run_gbm_cpcv(X, y, None, None, PARAMS_3C, num_boost_round=40,
                       num_classes=3, forecast_horizon=5)
    assert res["cpcv_n_folds"] == 0


def test_run_gbm_cpcv_max_rows_subsample(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV_BOOST_ROUNDS", "30")
    monkeypatch.setenv("TB_GBM_CPCV_MAX_ROWS", "800")  # force subsampling
    X, y = _signal_data(n=2400)
    res = run_gbm_cpcv(X, y, None, None, PARAMS_3C, num_boost_round=30,
                       num_classes=3, forecast_horizon=5, model_name="t_subsample")
    assert res["cpcv_n_folds"] == 14  # C(6,2)=15 minus the {first,last} combo whose span-purge empties train
    assert res["cpcv_oos_acc_mean"] > 0.5  # still learns on the sample


# ── 7. bad intervals fall back gracefully ────────────────────────────────────

def test_run_gbm_cpcv_mismatched_intervals_uses_fallback(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV_BOOST_ROUNDS", "30")
    X, y = _signal_data(n=1200)
    bad_iv = _cpcv_fallback_intervals(50, 5)  # wrong length on purpose
    res = run_gbm_cpcv(X, y, None, bad_iv, PARAMS_3C, num_boost_round=30,
                       num_classes=3, forecast_horizon=5, model_name="t_badiv")
    assert res["cpcv_n_folds"] == 14  # no crash, fallback used


# ── 8. end-to-end through train_from_features ────────────────────────────────

def test_train_from_features_populates_cpcv_metrics(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV_BOOST_ROUNDS", "30")
    X, y = _signal_data(n=1500)
    names = [f"f{i}" for i in range(X.shape[1])]
    m = TimeSeriesGBM(model_name="test_cpcv_v320", forecast_horizon=5)
    m.params["device"] = "cpu"
    iv = _cpcv_fallback_intervals(len(X), 5)
    metrics = m.train_from_features(
        X, y, names, skip_save=True, num_boost_round=40,
        early_stopping_rounds=10, num_classes=3, event_intervals=iv,
    )
    assert metrics.cpcv_n_folds == 14  # 15 combos minus the fully-purged {first,last} span
    assert 0.0 <= metrics.cpcv_pbo <= 1.0
    assert metrics.cpcv_oos_acc_mean > 0.5
    d = metrics.to_dict()  # persisted to timeseries_models.metrics via _save_model
    assert d["cpcv_n_folds"] == 14
    assert d["cpcv_oos_acc_mean"] == pytest.approx(metrics.cpcv_oos_acc_mean)


def test_train_from_features_binary_cpcv(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV_BOOST_ROUNDS", "30")
    rng = np.random.default_rng(3)
    X = rng.normal(size=(1500, 8)).astype(np.float32)
    y = (X[:, 0] + 0.3 * rng.normal(size=1500) > 0).astype(np.int64)
    names = [f"f{i}" for i in range(8)]
    m = TimeSeriesGBM(model_name="test_cpcv_bin_v320", forecast_horizon=3)
    m.params["device"] = "cpu"
    metrics = m.train_from_features(
        X, y, names, skip_save=True, num_boost_round=40,
        early_stopping_rounds=10, num_classes=2,
    )
    assert metrics.cpcv_n_folds == 14  # 15 combos minus the fully-purged {first,last} span
    assert metrics.cpcv_oos_acc_mean > 0.6


def test_train_from_features_cpcv_disabled_still_trains(monkeypatch):
    monkeypatch.setenv("TB_GBM_CPCV", "0")
    X, y = _signal_data(n=800)
    names = [f"f{i}" for i in range(X.shape[1])]
    m = TimeSeriesGBM(model_name="test_cpcv_off_v320", forecast_horizon=5)
    m.params["device"] = "cpu"
    metrics = m.train_from_features(
        X, y, names, skip_save=True, num_boost_round=30,
        early_stopping_rounds=10, num_classes=3,
    )
    assert metrics.cpcv_n_folds == 0          # CPCV skipped
    assert metrics.accuracy > 0.0             # final model still trained


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
