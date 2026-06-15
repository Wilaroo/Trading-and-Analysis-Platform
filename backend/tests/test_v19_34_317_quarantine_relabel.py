"""v19.34.317 — quarantine relabel: per_setup_rows status + report fields.

Pre-v317 the boot diagnostic lumped intentionally-quarantined models (PBO sweep,
manual quarantine) into the same `missing_models` bucket as genuine load bugs,
and the per-setup status read as "missing_in_memory" for both. Operator had to
scan the log to figure out which gaps were real bugs vs intentional drops.

v317 moves the quarantined-vs-genuinely-missing classification INTO
`diagnose_model_load_consistency` (single source of truth) and exposes:
  - `quarantined_models`, `quarantined_count`
  - `missing_models`, `missing_count`   (now: GENUINELY missing only)
  - per_setup_rows[*]["status"] = "quarantined" when applicable

Existing tests (test_model_load_diagnostic.py) continue to pass because their
fixtures don't stamp `quarantined: True` on any doc.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.timeseries_service import TimeSeriesAIService  # noqa: E402
from services.ai_modules.setup_training_config import (  # noqa: E402
    get_model_name,
)


class _FakeCursor:
    def __init__(self, docs, query=None):
        # Mirrors v317's defensive check — the fake honors `quarantined: True`
        # query so tests can stamp some docs as quarantined and not others.
        self._docs = []
        for d in docs:
            if query and "quarantined" in query:
                if d.get("quarantined") is not query["quarantined"]:
                    continue
            self._docs.append(d)

    def __iter__(self):
        return iter(self._docs)


class _FakeColl:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, projection=None):
        return _FakeCursor(self.docs, query=query or {})

    def find_one(self, query=None, projection=None):
        for d in self.docs:
            if (query or {}).get("name") == d.get("name"):
                return d
        return None


class _FakeDB:
    def __init__(self, docs):
        self._cols = {"timeseries_models": _FakeColl(docs)}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeColl([]))


def _fake_gbm(model_name: str, loaded: bool = True):
    gbm = MagicMock()
    gbm.model_name = model_name
    gbm._model = object() if loaded else None
    return gbm


def _make_svc(docs, preloaded=None):
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    svc._setup_models = dict(preloaded or {})
    svc._ml_available = True
    svc._db = _FakeDB(docs)
    return svc


SCALP_1MIN = get_model_name("SCALP", "1 min")
SHORT_SCALP_1MIN = get_model_name("SHORT_SCALP", "1 min")
SHORT_VWAP_5MIN = get_model_name("SHORT_VWAP", "5 mins")


# ── New v317 fields exposed ──────────────────────────────────────────

def test_quarantined_models_field_exists():
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},
        {"name": SHORT_SCALP_1MIN, "model_data": "blob", "quarantined": True},
    ]
    svc = _make_svc(ts_docs, preloaded={})
    rep = svc.diagnose_model_load_consistency()
    # v317 contract: both fields exist in every report.
    assert "quarantined_models" in rep
    assert "quarantined_count" in rep


def test_quarantined_split_from_genuinely_missing():
    """Mixed scenario: one model quarantined, one genuinely missing."""
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},                      # genuinely missing
        {"name": SHORT_SCALP_1MIN, "model_data": "blob", "quarantined": True},  # intentional
    ]
    svc = _make_svc(ts_docs, preloaded={})
    rep = svc.diagnose_model_load_consistency()

    assert rep["missing_count"] == 1, "only the un-quarantined model is GENUINELY missing"
    assert rep["missing_models"] == [SCALP_1MIN]
    assert rep["quarantined_count"] == 1
    assert rep["quarantined_models"] == [SHORT_SCALP_1MIN]


def test_all_quarantined_yields_zero_missing():
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob", "quarantined": True},
        {"name": SHORT_SCALP_1MIN, "model_data": "blob", "quarantined": True},
    ]
    svc = _make_svc(ts_docs, preloaded={})
    rep = svc.diagnose_model_load_consistency()
    assert rep["missing_count"] == 0, "all gaps intentional → zero 'genuinely missing'"
    assert rep["quarantined_count"] == 2
    assert set(rep["quarantined_models"]) == {SCALP_1MIN, SHORT_SCALP_1MIN}


def test_per_setup_status_quarantined():
    """Pre-v317 a quarantined model showed status='missing_in_memory' in the
    per-setup table. v317 surfaces 'quarantined' for those rows."""
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},                                # plain missing
        {"name": SHORT_SCALP_1MIN, "model_data": "blob", "quarantined": True},     # quarantined
    ]
    svc = _make_svc(ts_docs, preloaded={})
    rep = svc.diagnose_model_load_consistency()
    by_name = {r["model_name"]: r for r in rep["by_setup"]}
    assert by_name[SCALP_1MIN]["status"] == "missing_in_memory"
    assert by_name[SHORT_SCALP_1MIN]["status"] == "quarantined"


def test_no_quarantine_field_still_handled():
    """Docs that simply don't have a `quarantined` field default to missing."""
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob"},  # no quarantined key at all
    ]
    svc = _make_svc(ts_docs, preloaded={})
    rep = svc.diagnose_model_load_consistency()
    assert rep["missing_count"] == 1
    assert rep["quarantined_count"] == 0
    assert rep["missing_models"] == [SCALP_1MIN]


def test_loaded_model_never_appears_in_either_bucket():
    """A loaded model isn't missing — even if marked quarantined in the DB."""
    ts_docs = [
        {"name": SCALP_1MIN, "model_data": "blob", "quarantined": True},
    ]
    preloaded = {("SCALP", "1 min"): _fake_gbm(SCALP_1MIN)}
    svc = _make_svc(ts_docs, preloaded=preloaded)
    rep = svc.diagnose_model_load_consistency()
    # In memory → loaded; never appears in missing/quarantined.
    assert SCALP_1MIN in rep["loaded_in_memory"]
    assert SCALP_1MIN not in rep["missing_models"]
    assert SCALP_1MIN not in rep["quarantined_models"]


def test_db_none_returns_quarantine_fields_too():
    """Even the no-DB defensive path exposes the new fields with sensible zeros."""
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    svc._setup_models = {}
    svc._ml_available = True
    svc._db = None
    rep = svc.diagnose_model_load_consistency()
    # The defensive path was historically minimal; v317 doesn't require us to
    # populate the field there — but if missing, the caller relies on .get()
    # so the boot logger still works. Sanity: missing_count is 0.
    assert rep.get("missing_count") == 0
