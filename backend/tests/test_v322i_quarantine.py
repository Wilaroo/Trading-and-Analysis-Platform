"""
test_v322i_quarantine.py — contract tests for the PBO quarantine sweep.

What we guard:
  1. `TimeSeriesGBM._load_model` honors the `quarantined` flag on the
     exact-name doc AND does NOT fall through to a stand-in model
     (the pre-existing fallback chain would otherwise silently serve
     `direction_predictor_daily` for a quarantined exit-timing model).
  2. The fallback queries exclude quarantined docs.
  3. `predict()` with no model returns the neutral flat prediction
     (confidence 0.0) — the intended degraded behaviour.
  4. Healthy promotion `$unset`s the quarantine fields.
  5. Every other timeseries_models load path filters quarantined docs
     (timeseries_service ×2, ensemble_live_inference, confidence_gate).
  6. `select_quarantine_targets` (sweep script): default scope flags only
     negative-edge gate failers; strict flags all gate failers.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent     # backend/
sys.path.insert(0, str(ROOT))

SWEEP_PATH = ROOT.parent / "scripts" / "quarantine_pbo_sweep.py"


# ───────────────────────── fakes ─────────────────────────

def _match(doc, filt):
    for k, v in (filt or {}).items():
        if isinstance(v, dict):
            for op, arg in v.items():
                dv = doc.get(k)
                if op == "$exists" and (k in doc) != arg:
                    return False
                if op == "$ne" and dv == arg:
                    return False
                if op == "$gt" and not (dv is not None and dv > arg):
                    return False
        elif doc.get(k) != v:
            return False
    return True


class _FakeCol:
    def __init__(self, docs):
        self.docs = list(docs)

    def find_one(self, filt=None, proj=None, sort=None):
        matches = [d for d in self.docs if _match(d, filt)]
        if sort:
            key, direction = sort[0]
            matches.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return dict(matches[0]) if matches else None


class _FakeDB:
    def __init__(self, models):
        self._cols = {"timeseries_models": _FakeCol(models)}

    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = _FakeCol([])
        return self._cols[name]


def _gbm(model_name, docs):
    from services.ai_modules.timeseries_gbm import TimeSeriesGBM
    g = TimeSeriesGBM(model_name=model_name)
    g.set_db(_FakeDB(docs))      # triggers _load_model against the fakes
    return g


# ───────────────────────── tests ─────────────────────────

def test_quarantined_model_serves_nothing_no_fallback():
    """Quarantined exact match → _model stays None even though another
    loadable doc exists (the fallback chain must NOT kick in)."""
    docs = [
        {"name": "exit_timing_breakout", "quarantined": True,
         "quarantine_reason": "pbo_sweep v322i: PBO 1.00 > 0.20",
         "model_data": "QQ==", "model_format": "xgboost_json"},
        {"name": "direction_predictor_daily", "model_data": "QQ==",
         "model_format": "xgboost_json", "updated_at": "2026-06-11"},
    ]
    g = _gbm("exit_timing_breakout", docs)
    assert g._model is None, (
        "BUG: quarantined model fell through to a stand-in model")


def test_fallbacks_exclude_quarantined_docs():
    """Missing model + ONLY quarantined candidates → nothing loads."""
    docs = [
        {"name": "direction_predictor_daily", "quarantined": True,
         "model_data": "QQ==", "model_format": "xgboost_json",
         "updated_at": "2026-06-11"},
        {"name": "scalp_1min_predictor", "quarantined": True,
         "model_data": "QQ==", "model_format": "xgboost_json",
         "updated_at": "2026-06-10"},
    ]
    g = _gbm("nonexistent_model", docs)
    assert g._model is None, (
        "BUG: fallback loaded a quarantined doc")


def test_predict_without_model_is_neutral():
    g = _gbm("exit_timing_breakout",
             [{"name": "exit_timing_breakout", "quarantined": True}])
    p = g.predict([], symbol="TEST")
    assert p is not None and p.direction == "flat"
    assert p.confidence == 0.0
    assert abs(p.probability_up - 0.5) < 1e-9


def test_promotion_unsets_quarantine_fields():
    src = (ROOT / "services" / "ai_modules" / "timeseries_gbm.py").read_text()
    assert '"$unset": {"quarantined": "", "quarantine_reason": "",' in src, (
        "promotion no longer lifts the quarantine flag")


def test_all_load_paths_filter_quarantined():
    svc = (ROOT / "services" / "ai_modules" / "timeseries_service.py").read_text()
    assert svc.count("quarantined") >= 3, (
        "timeseries_service load paths missing quarantine filtering")
    assert "skipping legacy setup model" in svc, (
        "legacy setup_type_models loader bypasses the quarantine flag")
    ens = (ROOT / "services" / "ai_modules" / "ensemble_live_inference.py").read_text()
    assert 'ensemble_quarantined' in ens
    gate = (ROOT / "services" / "ai_modules" / "confidence_gate.py").read_text()
    assert '"quarantined": {"$ne": True}' in gate


def test_sweep_target_selection():
    spec = importlib.util.spec_from_file_location("sweep", SWEEP_PATH)
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    rows = [
        {"name": "toxic", "pbo": 1.00, "edge": -0.008, "folds": 14},   # both fail
        {"name": "fragile", "pbo": 0.29, "edge": +0.008, "folds": 14}, # PBO-only
        {"name": "zero_edge", "pbo": 0.00, "edge": 0.0, "folds": 14},  # edge-only
        {"name": "honest", "pbo": 0.00, "edge": +0.120, "folds": 14},  # passes
    ]
    default = {r["name"] for r in sweep.select_quarantine_targets(rows)}
    assert default == {"toxic", "zero_edge"}, default
    strict = {r["name"] for r in sweep.select_quarantine_targets(rows, strict=True)}
    assert strict == {"toxic", "fragile", "zero_edge"}, strict
