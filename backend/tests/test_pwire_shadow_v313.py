"""
v19.34.313 — P-WIRE shadow-mode regression tests.

These run WITHOUT the DGX DB/hardware: they validate the additive plumbing,
the unchanged live path, and the shadow-record contract with stubs. The full
data-backed proof runs on the DGX via scripts/pwire_shadow_verify.py.
"""
import types

import pytest


def test_methods_exist_on_service():
    from services.ai_modules.timeseries_service import TimeSeriesAIService
    for m in ("predict_with_named_model", "_get_shadow_model",
              "classify_current_regime", "predict_for_setup"):
        assert hasattr(TimeSeriesAIService, m), f"missing {m}"


def test_predict_for_setup_signature_has_override():
    import inspect
    from services.ai_modules.timeseries_service import TimeSeriesAIService
    sig = inspect.signature(TimeSeriesAIService.predict_for_setup)
    assert "model_name_override" in sig.parameters
    assert sig.parameters["model_name_override"].default is None


def test_override_routes_to_named_model(monkeypatch):
    """override=None must NOT touch the named-model path; a set override MUST."""
    from services.ai_modules.timeseries_service import TimeSeriesAIService
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    called = {"named": 0}

    def fake_named(self, symbol, bars, model_name):
        called["named"] += 1
        return {"model_used": model_name, "direction": "up"}

    monkeypatch.setattr(TimeSeriesAIService, "predict_with_named_model", fake_named)

    # override set → routes to named model, short-circuits before setup resolution
    out = TimeSeriesAIService.predict_for_setup(
        svc, "AAPL", [], "BREAKOUT", model_name_override="direction_predictor_5min_bull_trend"
    )
    assert called["named"] == 1
    assert out["model_used"] == "direction_predictor_5min_bull_trend"


def test_predict_with_named_model_missing_returns_none(monkeypatch):
    from services.ai_modules.timeseries_service import TimeSeriesAIService
    svc = TimeSeriesAIService.__new__(TimeSeriesAIService)
    monkeypatch.setattr(TimeSeriesAIService, "_get_shadow_model", lambda self, n: None)
    assert TimeSeriesAIService.predict_with_named_model(svc, "AAPL", [], "nope") is None


def test_shadow_disabled_returns_none(monkeypatch):
    import services.ai_modules.confidence_gate as cg
    monkeypatch.setattr(cg, "PWIRE_SHADOW_ENABLED", False)
    gate = cg.ConfidenceGate.__new__(cg.ConfidenceGate)
    out = gate._compute_regime_shadow(object(), "AAPL", "BREAKOUT", [], "5 mins", {})
    assert out is None


def test_shadow_record_contract(monkeypatch):
    """With a stub ts_ai, the shadow record carries every required field."""
    import services.ai_modules.confidence_gate as cg
    monkeypatch.setattr(cg, "PWIRE_SHADOW_ENABLED", True)

    ts = types.SimpleNamespace()
    ts.classify_current_regime = lambda: "bull_trend"

    def fake_named(symbol, bars, name):
        if name.endswith("_bull_trend"):
            return {"model_used": name, "direction": "up", "probability_up": 0.7,
                    "probability_down": 0.3, "confidence": 0.6, "feature_count": 51}
        return {"model_used": name, "direction": "down", "probability_up": 0.45,
                "probability_down": 0.55, "confidence": 0.2, "feature_count": 51}

    ts.predict_with_named_model = fake_named

    gate = cg.ConfidenceGate.__new__(cg.ConfidenceGate)
    bars = [{"date": "2026-06-10T15:55:00", "close": 123.45} for _ in range(60)]
    rec = gate._compute_regime_shadow(ts, "AAPL", "BREAKOUT", bars, "5 mins",
                                      {"model_used": "breakout_predictor"})

    assert rec is not None
    assert rec["shadow_version"] == "pwire_v1"
    assert rec["regime"] == "bull_trend"
    assert rec["regime_model_available"] is True
    assert rec["generic_base"]["model_name"] == "direction_predictor_5min"
    assert rec["regime_specialized"]["model_name"] == "direction_predictor_5min_bull_trend"
    # regime leg pUp=0.7 → ev_proxy +0.4 ; generic leg pUp=0.45 → ev_proxy -0.10
    assert rec["regime_specialized"]["ev_proxy"] == pytest.approx(0.4)
    assert rec["generic_base"]["ev_proxy"] == pytest.approx(-0.10)
    assert rec["directions_agree"] is False  # generic=down vs regime=up
    assert rec["decision_model"] == "breakout_predictor"
    assert len(rec["input_hash"]) == 16


def test_unknown_bar_size_returns_none(monkeypatch):
    import services.ai_modules.confidence_gate as cg
    monkeypatch.setattr(cg, "PWIRE_SHADOW_ENABLED", True)
    ts = types.SimpleNamespace(classify_current_regime=lambda: "bull_trend",
                               predict_with_named_model=lambda *a: None)
    gate = cg.ConfidenceGate.__new__(cg.ConfidenceGate)
    assert gate._compute_regime_shadow(ts, "AAPL", "BREAKOUT", [{}], "3 mins", {}) is None
