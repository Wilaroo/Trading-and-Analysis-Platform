"""v19.34.367 — P1-MULTI-TF multi-bar-size shadow logging regression test.

Verifies ConfidenceGate._get_live_prediction now emits an additive `regime_shadows`
list across 1min/5min/15min while keeping the single `regime_shadow` (5min) for
backward-compat, and that the PRIMARY prediction fields are unchanged. Also verifies
the env kill-switch PWIRE_MULTI_TF_SHADOW=0 falls back to the single 5min record.

Run (DGX): .venv/bin/python -m pytest backend/tests/test_v367_multi_tf_shadow.py -q
"""
import asyncio
import os

import pytest


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def __iter__(self):
        return iter(self._rows)


class _Coll:
    def __init__(self, rows):
        self._rows = rows

    def find(self, *a, **k):
        return _Cursor(list(self._rows))


class _FakeDB:
    def __init__(self):
        bars = [{"date": f"2026-06-{(i % 28) + 1:02d}", "open": 100.0 + i, "high": 101.0 + i,
                 "low": 99.0 + i, "close": 100.5 + i, "volume": 1_000_000 + i} for i in range(60)]
        self._coll = _Coll(bars)

    def __getitem__(self, name):
        return self._coll


class _FakeTS:
    def __init__(self):
        self._db = _FakeDB()

    def predict_for_setup(self, symbol, bars, setup_type):
        return {"direction": "long", "confidence": 0.7, "probability_up": 0.62,
                "probability_down": 0.38, "model_used": "primary_5min", "model_type": "gbm",
                "model_metrics": {}}

    def predict_with_named_model(self, symbol, bars, name):
        return {"direction": "long", "probability_up": 0.6, "probability_down": 0.4,
                "confidence": 0.6, "model_used": name}

    def classify_current_regime(self, *a, **k):
        return "high_vol"


def _run(env_value):
    import services.ai_modules.timeseries_service as tss
    from services.ai_modules.confidence_gate import ConfidenceGate

    orig_get = tss.get_timeseries_ai
    orig_env = os.environ.get("PWIRE_MULTI_TF_SHADOW")
    fake = _FakeTS()
    tss.get_timeseries_ai = lambda: fake
    if env_value is None:
        os.environ.pop("PWIRE_MULTI_TF_SHADOW", None)
    else:
        os.environ["PWIRE_MULTI_TF_SHADOW"] = env_value
    try:
        gate = ConfidenceGate(db=fake._db)
        return asyncio.run(gate._get_live_prediction("AAPL", "BREAKOUT", "long"))
    finally:
        tss.get_timeseries_ai = orig_get
        if orig_env is None:
            os.environ.pop("PWIRE_MULTI_TF_SHADOW", None)
        else:
            os.environ["PWIRE_MULTI_TF_SHADOW"] = orig_env


def test_multi_tf_on_emits_three_bar_sizes():
    res = _run("1")
    assert res["has_prediction"] is True
    # primary prediction path unchanged
    assert res["direction"] == "long"
    assert res["model_used"] == "primary_5min"
    # backward-compat single record is the 5min primary
    assert res["regime_shadow"]["bar_size"] == "5 mins"
    # additive multi-tf list across the three timeframes
    shadows = res.get("regime_shadows")
    assert isinstance(shadows, list) and len(shadows) == 3
    assert {s["bar_size"] for s in shadows} == {"1 min", "5 mins", "15 mins"}
    # every record is a well-formed pwire_v1 shadow
    for s in shadows:
        assert s["shadow_version"] == "pwire_v1"
        assert s["regime"] == "high_vol"


def test_multi_tf_off_falls_back_to_single():
    res = _run("0")
    assert res["has_prediction"] is True
    assert res["regime_shadow"]["bar_size"] == "5 mins"
    shadows = res.get("regime_shadows")
    # only the primary 5min record (no extra timeframes)
    assert isinstance(shadows, list) and len(shadows) == 1
    assert shadows[0]["bar_size"] == "5 mins"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
