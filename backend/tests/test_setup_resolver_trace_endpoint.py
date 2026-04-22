"""
Tests for GET /api/ai-training/setup-resolver-trace.

This diagnostic endpoint reveals how a scanner-emitted setup_type routes to
a trained model — the fix that unblocked the 3 promoted SHORT_* models.

Strategy: test the router function directly with a stubbed timeseries service
so we don't need a live FastAPI server or MongoDB.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_setup_resolver_trace_endpoint.py -v
"""
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

from routers.ai_training import setup_resolver_trace  # noqa: E402


class _StubService:
    """Stand-in for TimeSeriesAIService with a known _setup_models dict."""
    def __init__(self, loaded_keys):
        self._setup_models = {k: object() for k in loaded_keys}


def _patch_service(loaded_keys):
    return patch(
        "services.ai_modules.timeseries_service.get_timeseries_ai",
        return_value=_StubService(loaded_keys),
    )


# Common set of loaded models mirroring Spark post-retrain
LOADED = {
    "SCALP", "VWAP", "REVERSAL", "BREAKOUT", "ORB",
    "SHORT_SCALP", "SHORT_VWAP", "SHORT_REVERSAL",
    "SHORT_ORB", "SHORT_BREAKDOWN",
}


def test_single_trace_short_scalp_variant_resolves_to_SHORT_SCALP():
    with _patch_service(LOADED):
        r = setup_resolver_trace(setup="rubber_band_scalp_short")
    assert r["success"] is True
    t = r["trace"]
    assert t["input"] == "rubber_band_scalp_short"
    assert t["normalized"] == "RUBBER_BAND_SCALP_SHORT"
    assert t["resolved_key"] == "SHORT_SCALP"
    assert t["resolved_loaded"] is True
    assert t["match_step"] == "short_family"
    assert t["will_use_general"] is False


def test_single_trace_exact_match_flagged_as_exact():
    with _patch_service(LOADED):
        r = setup_resolver_trace(setup="SCALP")
    t = r["trace"]
    assert t["resolved_key"] == "SCALP"
    assert t["match_step"] == "exact"
    assert t["resolved_loaded"] is True


def test_single_trace_legacy_vwap_bounce_flagged():
    with _patch_service(LOADED):
        r = setup_resolver_trace(setup="vwap_bounce")
    t = r["trace"]
    assert t["resolved_key"] == "VWAP"
    assert t["match_step"] == "legacy_vwap_alias"


def test_single_trace_long_strip_flagged():
    with _patch_service(LOADED):
        r = setup_resolver_trace(setup="reversal_long")
    t = r["trace"]
    assert t["resolved_key"] == "REVERSAL"
    assert t["match_step"] == "long_base_strip"


def test_single_trace_unknown_setup_flagged_as_fallback():
    with _patch_service(LOADED):
        r = setup_resolver_trace(setup="totally_unknown_setup_blah")
    t = r["trace"]
    assert t["resolved_loaded"] is False
    assert t["will_use_general"] is True
    assert t["match_step"] == "fallback"


def test_batch_reports_coverage_rate():
    inputs = [
        "rubber_band_scalp_short",     # → SHORT_SCALP (loaded)
        "vwap_reclaim_short",          # → SHORT_VWAP (loaded)
        "totally_unknown_setup",       # → fallback (not loaded)
        "SCALP",                        # → exact (loaded)
    ]
    with _patch_service(LOADED):
        r = setup_resolver_trace(batch=",".join(inputs))
    assert r["count"] == 4
    assert r["coverage_rate"] == 0.75  # 3/4 loaded
    keys = [t["resolved_key"] for t in r["traces"]]
    assert keys == ["SHORT_SCALP", "SHORT_VWAP", "TOTALLY_UNKNOWN_SETUP", "SCALP"]


def test_batch_handles_whitespace_and_empty_items():
    with _patch_service(LOADED):
        r = setup_resolver_trace(batch=" SCALP ,, vwap_reclaim_short , ")
    assert r["count"] == 2
    assert r["traces"][0]["resolved_key"] == "SCALP"
    assert r["traces"][1]["resolved_key"] == "SHORT_VWAP"


def test_missing_params_returns_400():
    from fastapi import HTTPException
    with _patch_service(LOADED):
        with pytest.raises(HTTPException) as exc:
            setup_resolver_trace()
    assert exc.value.status_code == 400


def test_loaded_models_count_reflects_stub():
    with _patch_service(LOADED):
        r = setup_resolver_trace(setup="SCALP")
    assert r["loaded_models_count"] == len(LOADED)


def test_no_short_models_loaded_falls_back_to_base():
    """When only long models are loaded, short alerts should still resolve to
    base names (best available). `match_step` is 'family_substring' because
    the resolver found a base-name match via substring, not via exact or
    short_family."""
    long_only = {"SCALP", "VWAP", "REVERSAL"}
    with _patch_service(long_only):
        r = setup_resolver_trace(setup="rubber_band_scalp_short")
    t = r["trace"]
    assert t["resolved_key"] == "SCALP"
    assert t["resolved_loaded"] is True
    # match_step should NOT be short_family since there's no SHORT_* model
    assert t["match_step"] != "short_family"
