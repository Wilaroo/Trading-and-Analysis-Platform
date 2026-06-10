"""
Test for v19.34.312 ABSOLUTE class-collapse gate in TimeSeriesGBM._save_model.

A freshly trained 2-class model that ignores one class (min per-class recall
< floor) must NOT be promoted to the live inference collection, even on
first-train (no active model) — the case that let gap_fill (0.98 acc /
recall_down 0.00) and vol_predictor (always HIGH_VOL) ship as "edge".
"""
import numpy as np
import pytest
import xgboost as xgb

from services.ai_modules.timeseries_gbm import TimeSeriesGBM, ModelMetrics


class _Col:
    def __init__(self, find_one_result=None):
        self.find_one_result = find_one_result
        self.inserts = []
        self.updates = []

    def insert_one(self, doc):
        self.inserts.append(doc)

    def update_one(self, q, update, upsert=False):
        self.updates.append((q, update, upsert))
        class _R:
            modified_count = 1
        return _R()

    def find_one(self, q, proj=None):
        return self.find_one_result


class _DB:
    def __init__(self, active=None):
        self.cols = {
            "timeseries_models": _Col(find_one_result=active),
            "timeseries_model_archive": _Col(),
        }

    def __getitem__(self, name):
        return self.cols[name]


def _make_gbm(metrics, active=None):
    g = TimeSeriesGBM.__new__(TimeSeriesGBM)
    X = np.random.rand(40, 3)
    y = np.array([0, 1] * 20)
    booster = xgb.train({"objective": "binary:logistic", "verbosity": 0},
                        xgb.DMatrix(X, label=y), num_boost_round=1)
    g._model = booster
    g.model_name = "vol_predictor_5min"
    g._metrics = metrics
    g._version = "v_test"
    g._num_classes = 2
    g.params = {"objective": "binary:logistic"}
    g._feature_names = ["f0", "f1", "f2"]
    g.forecast_horizon = 5
    g._db = _DB(active=active)
    g._loaded = False
    g._load_model = lambda: setattr(g, "_loaded", True)
    return g


def test_collapsed_first_train_is_rejected_not_promoted():
    m = ModelMetrics(accuracy=0.98, recall_up=1.0, recall_down=0.0,
                     f1_up=0.99, f1_down=0.0)
    g = _make_gbm(m, active=None)  # first-train: no active model
    result = g._save_model()
    assert result == "rejected_class_collapse"
    # archived, but NOT promoted to the live collection
    assert len(g._db["timeseries_model_archive"].inserts) == 1
    assert g._db["timeseries_models"].updates == []  # no promote upsert


def test_healthy_two_sided_model_promotes():
    m = ModelMetrics(accuracy=0.61, recall_up=0.55, recall_down=0.58,
                     f1_up=0.57, f1_down=0.59)
    g = _make_gbm(m, active=None)
    result = g._save_model()
    assert result == "promoted"
    assert len(g._db["timeseries_models"].updates) == 1  # promoted


def test_collapse_keeps_existing_active():
    m = ModelMetrics(accuracy=0.95, recall_up=0.9, recall_down=0.02,
                     f1_up=0.9, f1_down=0.03)
    active = {"metrics": {"recall_up": 0.5, "recall_down": 0.5,
                          "f1_up": 0.5, "f1_down": 0.5, "accuracy": 0.6},
              "version": "v_old"}
    g = _make_gbm(m, active=active)
    result = g._save_model()
    assert result == "rejected_class_collapse"
    assert g._db["timeseries_models"].updates == []  # active untouched
    assert g._loaded is True  # reloaded existing active
