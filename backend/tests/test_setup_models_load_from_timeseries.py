"""
Regression test for the `_load_setup_models_from_db` fix (2026-04-24).

Context
-------
On Spark, the `timeseries_models` collection had 17 trained setup-specific
models (including 3 promoted shorts with real edge), but the live service's
`_setup_models` in-memory dict was EMPTY. Every `predict_for_setup` call was
silently falling through to the general direction_predictor model — the
promoted edge was unreachable from the live trading path.

Root cause: the loader only iterated the legacy `setup_type_models` collection.
Training, however, writes to `timeseries_models` (TimeSeriesGBM.MODEL_COLLECTION).
The two collections had drifted out of sync during the XGBoost migration.

Fix: after the legacy loop, scan every declared `SETUP_TRAINING_PROFILES` entry
and try to load from `timeseries_models` via the existing
`TimeSeriesGBM.set_db()` → `_load_model()` path (which handles xgboost_json_zlib
deserialization, feature_names restore, num_classes restore).

This test stubs the DB + TimeSeriesGBM to prove:
  1. Models present in `timeseries_models` but absent from `setup_type_models`
     get loaded into `_setup_models`.
  2. Cache keys are set as both `(setup_type, bar_size)` tuples AND bare
     `setup_type` strings (legacy compat for `predict_for_setup`).
  3. Models that fail to load (model=None after set_db) don't pollute the dict.
  4. Models absent from both collections are silently skipped.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_setup_models_load_from_timeseries.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.timeseries_service import TimeSeriesAIService  # noqa: E402


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    """Minimal mongo-like collection stub."""
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, projection=None):
        return _FakeCursor(self.docs)

    def find_one(self, query=None, projection=None):
        name = (query or {}).get("name")
        for d in self.docs:
            if d.get("name") == name:
                return d
        return None


class _FakeDB:
    def __init__(self, setup_type_models_docs, timeseries_models_docs):
        self._cols = {
            "setup_type_models": _FakeCollection(setup_type_models_docs),
            "timeseries_models": _FakeCollection(timeseries_models_docs),
        }

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCollection([]))


def _make_ts_model_doc(name: str) -> dict:
    return {
        "name": name,
        "model_data": "stub-base64-not-really-used-because-gbm-is-mocked",
        "model_format": "xgboost_json_zlib",
        "version": "v0.1.0",
    }


def _make_service_with_fake_db(ts_models_docs, setup_type_models_docs=None):
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    svc._setup_models = {}
    svc._ml_available = True
    svc._db = _FakeDB(setup_type_models_docs or [], ts_models_docs)
    return svc


def test_loader_picks_up_models_from_timeseries_models():
    """Main regression: models in timeseries_models get loaded into _setup_models."""
    # Simulate Spark state: setup_type_models is empty, timeseries_models has
    # the known-promoted SHORT_* models + one long model.
    ts_docs = [
        _make_ts_model_doc("short_scalp_1min_predictor"),
        _make_ts_model_doc("short_vwap_5min_predictor"),
        _make_ts_model_doc("short_reversal_5min_predictor"),
        _make_ts_model_doc("scalp_1min_predictor"),
    ]
    svc = _make_service_with_fake_db(ts_docs)

    # Stub TimeSeriesGBM so `set_db` succeeds and `_model` is not None (simulates
    # a successful xgboost_json_zlib load). We don't actually need a real XGBoost
    # model for this regression — we only care about the wiring.
    def fake_gbm_factory(*args, **kwargs):
        gbm = MagicMock()
        gbm._model = object()  # non-None → load succeeded
        gbm._version = "v0.1.0"
        gbm.set_db = MagicMock()
        return gbm

    with patch(
        "services.ai_modules.timeseries_service.TimeSeriesGBM",
        side_effect=fake_gbm_factory,
    ):
        svc._load_setup_models_from_db()

    # Models should now be reachable via both compound and legacy keys
    assert ("SHORT_SCALP", "1 min") in svc._setup_models
    assert ("SHORT_VWAP", "5 mins") in svc._setup_models
    assert ("SHORT_REVERSAL", "5 mins") in svc._setup_models
    assert "SHORT_SCALP" in svc._setup_models   # legacy compat for predict_for_setup
    assert "SHORT_VWAP" in svc._setup_models
    assert "SHORT_REVERSAL" in svc._setup_models


def test_loader_skips_missing_models_silently():
    """Setup profiles with no matching timeseries_models doc must not crash."""
    svc = _make_service_with_fake_db([])  # empty DB

    def fake_gbm_factory(*args, **kwargs):
        gbm = MagicMock()
        gbm._model = object()
        gbm._version = "v0.1.0"
        gbm.set_db = MagicMock()
        return gbm

    with patch(
        "services.ai_modules.timeseries_service.TimeSeriesGBM",
        side_effect=fake_gbm_factory,
    ):
        svc._load_setup_models_from_db()

    # No models loaded — dict is still empty, no exception raised
    assert svc._setup_models == {}


def test_loader_skips_models_that_fail_to_deserialize():
    """If gbm.set_db() can't actually populate _model (e.g. bad blob), don't
    register the broken gbm in _setup_models."""
    ts_docs = [_make_ts_model_doc("scalp_1min_predictor")]
    svc = _make_service_with_fake_db(ts_docs)

    def fake_gbm_factory(*args, **kwargs):
        gbm = MagicMock()
        gbm._model = None  # Load failed
        gbm._version = "v0.0.0"
        gbm.set_db = MagicMock()
        return gbm

    with patch(
        "services.ai_modules.timeseries_service.TimeSeriesGBM",
        side_effect=fake_gbm_factory,
    ):
        svc._load_setup_models_from_db()

    # scalp/1min should NOT be in the cache because it failed to deserialize
    assert ("SCALP", "1 min") not in svc._setup_models
    assert "SCALP" not in svc._setup_models


def test_loader_does_not_duplicate_when_legacy_loaded_first():
    """If the legacy setup_type_models loop already loaded (SCALP, '1 min'),
    the timeseries_models fallback must not re-load and overwrite it."""
    svc = _make_service_with_fake_db(
        ts_models_docs=[_make_ts_model_doc("scalp_1min_predictor")],
        setup_type_models_docs=[],  # empty → legacy loop does nothing
    )

    # Pre-populate as if legacy loop had found the model
    sentinel = MagicMock()
    sentinel._model = object()
    sentinel._version = "legacy"
    svc._setup_models[("SCALP", "1 min")] = sentinel
    svc._setup_models["SCALP"] = sentinel

    def fake_gbm_factory(*args, **kwargs):
        gbm = MagicMock()
        gbm._model = object()
        gbm._version = "v_NEWER"
        gbm.set_db = MagicMock()
        return gbm

    with patch(
        "services.ai_modules.timeseries_service.TimeSeriesGBM",
        side_effect=fake_gbm_factory,
    ):
        svc._load_setup_models_from_db()

    # The legacy-loaded sentinel must still be there, not overwritten
    assert svc._setup_models[("SCALP", "1 min")] is sentinel
    assert svc._setup_models["SCALP"] is sentinel


def test_loader_early_exits_when_db_missing():
    """If _db is None, loader is a no-op (not an exception)."""
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    svc._setup_models = {}
    svc._ml_available = True
    svc._db = None
    # Should NOT raise
    svc._load_setup_models_from_db()
    assert svc._setup_models == {}
