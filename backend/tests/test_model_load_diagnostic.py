"""
Tests for the startup model-load consistency diagnostic.

Purpose
-------
The 2026-04-24 latent bug (trained models in `timeseries_models` but empty
`_setup_models` in memory) went undetected for weeks because nothing
cross-checked the two sources. This diagnostic is the safety net.

Covers:
  1. Correctly detects missing models (trained but not loaded)
  2. Correctly reports clean state when everything is loaded
  3. Handles `_db=None` without crashing
  4. `by_setup` rows include every declared profile with correct status
  5. Distinguishes `missing_in_memory` from `not_trained`
  6. Endpoint wrapper returns 200 + success=True

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_model_load_diagnostic.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.timeseries_service import TimeSeriesAIService  # noqa: E402
from services.ai_modules.setup_training_config import (  # noqa: E402
    SETUP_TRAINING_PROFILES, get_model_name,
)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs
    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
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
    def __init__(self, ts_models_docs):
        self._cols = {"timeseries_models": _FakeCollection(ts_models_docs)}
    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCollection([]))


def _make_svc(ts_models_docs, preloaded: dict | None = None):
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    svc._setup_models = dict(preloaded or {})
    svc._ml_available = True
    svc._db = _FakeDB(ts_models_docs)
    return svc


def _fake_gbm(model_name: str, loaded: bool = True):
    gbm = MagicMock()
    gbm.model_name = model_name
    gbm._model = object() if loaded else None
    return gbm


# Pick a few representative profile names so tests don't depend on every
# profile being declared.
SCALP_1MIN = get_model_name("SCALP", "1 min")          # scalp_1min_predictor
SHORT_SCALP_1MIN = get_model_name("SHORT_SCALP", "1 min")
SHORT_VWAP_5MIN = get_model_name("SHORT_VWAP", "5 mins")


# ── Core diagnostic ──────────────────────────────────────────────────

def test_detects_models_trained_but_not_loaded():
    """The exact Phase-13 failure mode: DB says trained, memory says empty."""
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},
        {"name": SHORT_SCALP_1MIN, "model_data": "blob"},
        {"name": SHORT_VWAP_5MIN, "model_data": "blob"},
    ]
    svc = _make_svc(ts_docs, preloaded={})  # nothing loaded

    rep = svc.diagnose_model_load_consistency()

    assert rep["trained_in_db_count"] == 3
    assert rep["loaded_count"] == 0
    assert rep["missing_count"] == 3
    assert SCALP_1MIN in rep["missing_models"]
    assert SHORT_SCALP_1MIN in rep["missing_models"]
    assert SHORT_VWAP_5MIN in rep["missing_models"]


def test_clean_state_when_everything_loaded():
    ts_docs = [{"name": SCALP_1MIN, "model_data": "blob"}]
    preloaded = {("SCALP", "1 min"): _fake_gbm(SCALP_1MIN)}
    svc = _make_svc(ts_docs, preloaded=preloaded)

    rep = svc.diagnose_model_load_consistency()
    assert rep["missing_count"] == 0
    assert rep["loaded_count"] == 1
    assert rep["missing_models"] == []
    assert SCALP_1MIN in rep["loaded_in_memory"]


def test_partial_load_reports_only_the_missing_ones():
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},
        {"name": SHORT_SCALP_1MIN, "model_data": "blob"},
    ]
    preloaded = {("SCALP", "1 min"): _fake_gbm(SCALP_1MIN)}  # only scalp loaded
    svc = _make_svc(ts_docs, preloaded=preloaded)

    rep = svc.diagnose_model_load_consistency()
    assert rep["trained_in_db_count"] == 2
    assert rep["loaded_count"] == 1
    assert rep["missing_count"] == 1
    assert rep["missing_models"] == [SHORT_SCALP_1MIN]


def test_ignores_gbms_that_never_actually_loaded():
    """A GBM whose _model is None (failed deserialize) must NOT count as loaded."""
    ts_docs = [{"name": SCALP_1MIN, "model_data": "blob"}]
    preloaded = {("SCALP", "1 min"): _fake_gbm(SCALP_1MIN, loaded=False)}
    svc = _make_svc(ts_docs, preloaded=preloaded)

    rep = svc.diagnose_model_load_consistency()
    assert rep["loaded_count"] == 0
    assert rep["missing_count"] == 1


def test_by_setup_rows_cover_all_declared_profiles():
    svc = _make_svc([], preloaded={})
    rep = svc.diagnose_model_load_consistency()

    # Total rows should equal the sum of profile entries across all setup types
    expected_total = sum(
        len(profiles) for profiles in SETUP_TRAINING_PROFILES.values()
    )
    assert len(rep["by_setup"]) == expected_total

    # Every row has the required columns
    for row in rep["by_setup"]:
        assert {"setup_type", "bar_size", "model_name",
                "trained_in_db", "loaded_in_memory", "status"} <= set(row.keys())


def test_by_setup_status_values_distinguish_correctly():
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},             # trained but not loaded
        {"name": SHORT_SCALP_1MIN, "model_data": "blob"},       # trained AND loaded
    ]
    preloaded = {("SHORT_SCALP", "1 min"): _fake_gbm(SHORT_SCALP_1MIN)}
    svc = _make_svc(ts_docs, preloaded=preloaded)
    rep = svc.diagnose_model_load_consistency()

    by_name = {r["model_name"]: r for r in rep["by_setup"]}
    assert by_name[SCALP_1MIN]["status"] == "missing_in_memory"
    assert by_name[SHORT_SCALP_1MIN]["status"] == "loaded"

    # A setup we definitely haven't listed in ts_docs stays "not_trained"
    some_not_trained = next(r for r in rep["by_setup"] if r["status"] == "not_trained")
    assert some_not_trained["trained_in_db"] is False


def test_db_none_returns_structured_error_not_exception():
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    svc._setup_models = {}
    svc._ml_available = True
    svc._db = None
    rep = svc.diagnose_model_load_consistency()
    assert "error" in rep
    assert rep["missing_count"] == 0
    assert rep["trained_in_db_count"] == 0


# ── Endpoint wrapper ────────────────────────────────────────────────

def test_endpoint_returns_success_wrapped_report():
    from routers.ai_training import model_load_diagnostic
    from unittest.mock import patch

    svc = _make_svc(
        ts_models_docs=[{"name": SCALP_1MIN, "model_data": "blob"}],
        preloaded={},
    )
    with patch(
        "services.ai_modules.timeseries_service.get_timeseries_ai",
        return_value=svc,
    ):
        resp = model_load_diagnostic()

    assert resp["success"] is True
    assert resp["report"]["missing_count"] == 1
    assert SCALP_1MIN in resp["report"]["missing_models"]


def test_endpoint_surfaces_service_errors_as_500():
    from routers.ai_training import model_load_diagnostic
    from fastapi import HTTPException
    from unittest.mock import patch
    import pytest

    class _Broken:
        def diagnose_model_load_consistency(self):
            raise RuntimeError("boom")

    with patch(
        "services.ai_modules.timeseries_service.get_timeseries_ai",
        return_value=_Broken(),
    ):
        with pytest.raises(HTTPException) as exc:
            model_load_diagnostic()
    assert exc.value.status_code == 500
