"""
Regression tests for the class-collapse-aware Model Protection gate
(2026-04-22, timeseries_gbm.py ~L462-L540).

CONTEXT
-------
Before this fix, the protection gate used raw accuracy: `new.accuracy > active.accuracy`.
That gate REJECTED the class-balance fix we shipped for train_full_universe
because the new balanced model (accuracy 43.5%, UP recall ~0.30) scored lower
than the collapsed active model (accuracy 53.5%, UP recall ~0.003) — the
collapsed model "wins" accuracy by predicting the majority class every bar.

New gate:
  - Escape hatch: if active is collapsed (UP recall < 0.05), promote ANY new
    model whose UP recall beats active AND DOWN recall ≥ 10%.
  - Normal path: require new UP recall ≥ 10% AND new DOWN recall ≥ 10% AND
    new macro-F1 ≥ 0.92 × active macro-F1.

These tests exercise the source-level behavior of the protection logic
WITHOUT needing a live Mongo, by mocking `_db` and `_metrics`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

# Bring in the target module. The class is heavy, so we stub out the XGBoost
# training machinery and only exercise `_save_model` from the active-promotion
# decision point onward.
from services.ai_modules.timeseries_gbm import TimeSeriesGBM  # noqa: E402


# ─── Helpers ────────────────────────────────────────────────────────────────

def _mk_metrics(accuracy, recall_up, recall_down, f1_up, f1_down):
    """Build a minimal ModelMetrics-like stand-in that has .to_dict()."""
    d = {
        "accuracy": accuracy,
        "recall_up": recall_up,
        "recall_down": recall_down,
        "f1_up": f1_up,
        "f1_down": f1_down,
        "precision_up": 0.3, "precision_down": 0.3,
    }
    class _M:
        def __init__(self, dd): self._dd = dd
        @property
        def accuracy(self): return self._dd["accuracy"]
        def to_dict(self): return dict(self._dd)
    return _M(d)


def _mk_gbm(new_metrics, active_metrics):
    """Build a GBM instance with mocked DB + pre-trained model bytes."""
    gbm = object.__new__(TimeSeriesGBM)
    gbm.model_name = "direction_predictor_5min"
    gbm._version = "v_new"
    gbm._num_classes = 3
    gbm._metrics = new_metrics
    gbm._feature_names = ["f1", "f2"]
    gbm.forecast_horizon = 12
    gbm.params = {}
    # Stub trained model — save_model writes fake bytes to the tempfile path
    mock_model = MagicMock()
    def _fake_save(path):
        with open(path, "wb") as fp:
            fp.write(b"\x00" * 128)
    mock_model.save_model.side_effect = _fake_save
    gbm._model = mock_model

    # DB double
    mock_db = MagicMock()
    mock_archive = MagicMock()
    mock_active = MagicMock()
    mock_db.__getitem__.side_effect = lambda k: (
        mock_archive if k == TimeSeriesGBM.MODEL_ARCHIVE_COLLECTION else mock_active
    )
    if active_metrics is not None:
        mock_active.find_one.return_value = {
            "metrics": active_metrics,
            "version": "v_active",
        }
    else:
        mock_active.find_one.return_value = None
    gbm._db = mock_db
    gbm._load_model = MagicMock()  # no-op on reload path
    return gbm, mock_active


# ─── Escape hatch: active is collapsed ──────────────────────────────────────

def test_promote_when_active_is_collapsed_and_new_improves_up_recall():
    """Matches the real Phase 13 v2 scenario.

    Active: accuracy 53.5%, UP recall ~0 (class-collapsed).
    New: accuracy 43.5%, UP recall 0.30, DOWN recall 0.55.
    Old gate → REJECT. New gate → PROMOTE.
    """
    new = _mk_metrics(0.4346, 0.30, 0.55, 0.25, 0.50)
    active = {"accuracy": 0.5351, "recall_up": 0.003, "recall_down": 0.80,
              "f1_up": 0.005, "f1_down": 0.60}
    gbm, mock_active = _mk_gbm(new, active)
    result = gbm._save_model()
    assert result == "promoted", "class-balance fix must beat a collapsed model"
    # And the active collection must have been updated
    assert mock_active.update_one.called


def test_reject_when_active_collapsed_but_new_also_has_low_down_recall():
    """Escape hatch still requires DOWN recall ≥ 10%."""
    new = _mk_metrics(0.40, 0.20, 0.05, 0.18, 0.06)
    active = {"accuracy": 0.50, "recall_up": 0.01, "recall_down": 0.80,
              "f1_up": 0.02, "f1_down": 0.55}
    gbm, mock_active = _mk_gbm(new, active)
    assert gbm._save_model() == "archived"
    assert not mock_active.update_one.called


# ─── Normal path: UP / DOWN recall floors ───────────────────────────────────

def test_reject_new_with_up_recall_below_floor_when_active_is_healthy():
    """Active has healthy recall — don't regress."""
    new = _mk_metrics(0.58, 0.05, 0.50, 0.08, 0.50)
    active = {"accuracy": 0.55, "recall_up": 0.25, "recall_down": 0.55,
              "f1_up": 0.28, "f1_down": 0.52}
    gbm, _ = _mk_gbm(new, active)
    assert gbm._save_model() == "archived"


def test_reject_new_with_down_recall_below_floor():
    new = _mk_metrics(0.58, 0.30, 0.05, 0.28, 0.06)
    active = {"accuracy": 0.55, "recall_up": 0.25, "recall_down": 0.55,
              "f1_up": 0.28, "f1_down": 0.52}
    gbm, _ = _mk_gbm(new, active)
    assert gbm._save_model() == "archived"


def test_reject_new_with_macro_f1_below_92_percent_floor():
    """New passes recall floors but collapses on F1 → reject."""
    new = _mk_metrics(0.55, 0.12, 0.15, 0.15, 0.25)
    active = {"accuracy": 0.52, "recall_up": 0.30, "recall_down": 0.50,
              "f1_up": 0.40, "f1_down": 0.50}
    gbm, _ = _mk_gbm(new, active)
    assert gbm._save_model() == "archived"


def test_promote_when_new_slightly_lower_accuracy_but_better_macro_f1():
    """Real-world case: class-balance costs ~2pp accuracy but lifts macro-F1."""
    new = _mk_metrics(0.50, 0.30, 0.45, 0.32, 0.48)
    active = {"accuracy": 0.52, "recall_up": 0.28, "recall_down": 0.48,
              "f1_up": 0.30, "f1_down": 0.46}
    gbm, mock_active = _mk_gbm(new, active)
    assert gbm._save_model() == "promoted"
    assert mock_active.update_one.called


def test_promote_when_no_active_model_exists():
    """First-time training: always promote."""
    new = _mk_metrics(0.45, 0.25, 0.40, 0.24, 0.38)
    gbm, mock_active = _mk_gbm(new, active_metrics=None)
    assert gbm._save_model() == "promoted"
    assert mock_active.update_one.called


def test_new_metrics_missing_recall_fields_treated_as_zero_safely():
    """Old archived metrics that predate recall tracking shouldn't crash."""
    new = _mk_metrics(0.55, 0.20, 0.40, 0.22, 0.38)
    active = {"accuracy": 0.40}
    gbm, _ = _mk_gbm(new, active)
    # Legacy active defaults to recall_up=0 (treated as collapsed),
    # so escape hatch promotes the new model.
    assert gbm._save_model() == "promoted"


def test_promote_when_active_has_tiny_up_recall_and_zero_down_recall():
    """Regression for Spark scenario (2026-04-23): active direction_predictor_5min
    had UP recall 0.069 (just above the OLD 0.05 hatch) and DOWN recall 0.0.
    The old escape hatch (`cur_recall_up < 0.05`) missed this and would force
    the retrained model through the strict macro-F1 floor. The new hatch
    triggers on EITHER class below MIN_{UP,DOWN}_RECALL — covering this case.
    """
    new = _mk_metrics(0.50, 0.22, 0.35, 0.25, 0.33)
    active = {"accuracy": 0.5350, "recall_up": 0.069, "recall_down": 0.0,
              "f1_up": 0.12, "f1_down": 0.0}
    gbm, mock_active = _mk_gbm(new, active)
    assert gbm._save_model() == "promoted"
    assert mock_active.update_one.called


def test_reject_when_active_collapsed_and_new_fails_floors():
    """Active is class-collapsed but the new candidate also misses the floors.
    We must not promote garbage just because active is garbage."""
    new = _mk_metrics(0.50, 0.08, 0.50, 0.10, 0.48)
    active = {"accuracy": 0.5350, "recall_up": 0.069, "recall_down": 0.0,
              "f1_up": 0.12, "f1_down": 0.0}
    gbm, mock_active = _mk_gbm(new, active)
    assert gbm._save_model() == "archived"
    assert not mock_active.update_one.called
