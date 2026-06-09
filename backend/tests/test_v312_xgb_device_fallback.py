"""v19.34.312 — XGBoost device probe + CPU fallback for timeseries_service.

Regression guard for the cudaErrorNoDevice crash that killed every
direction_predictor model (hardcoded device='cuda' on a box where XGBoost
can't see the GPU). The deterministic guarantee is the XGB_DEVICE override;
the auto-probe is a best-effort convenience whose return value is
XGBoost-build-dependent, so we don't assert on it here.
"""
import os
import importlib

import services.ai_modules.timeseries_service as ts


def _reset():
    ts._XGB_DEVICE = None


def test_env_override_cpu():
    _reset()
    os.environ["XGB_DEVICE"] = "cpu"
    try:
        assert ts._xgb_device() == "cpu"
    finally:
        os.environ.pop("XGB_DEVICE", None)
        _reset()


def test_env_override_cuda():
    _reset()
    os.environ["XGB_DEVICE"] = "cuda"
    try:
        assert ts._xgb_device() == "cuda"
    finally:
        os.environ.pop("XGB_DEVICE", None)
        _reset()


def test_result_is_cached():
    _reset()
    os.environ["XGB_DEVICE"] = "cpu"
    try:
        d1 = ts._xgb_device()
        os.environ["XGB_DEVICE"] = "cuda"  # change after first call
        d2 = ts._xgb_device()              # must still be cached cpu
        assert d1 == d2 == "cpu"
    finally:
        os.environ.pop("XGB_DEVICE", None)
        _reset()


def test_probe_returns_valid_device():
    _reset()
    os.environ.pop("XGB_DEVICE", None)
    d = ts._xgb_device()
    assert d in ("cpu", "cuda")  # never raises, always a valid device
    _reset()
