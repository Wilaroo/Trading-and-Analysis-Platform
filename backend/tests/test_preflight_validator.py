"""
Tests for the pre-flight shape validator.

- Happy path: passes on the real codebase (post-fix), including all phases.
- Failure detection: validator reports mismatches when we inject bugs.
"""
import pytest


ALL_PHASES = [
    "generic", "setup", "short", "volatility", "exit",
    "sector", "gap_fill", "risk", "regime", "ensemble",
]


@pytest.fixture
def all_flags_on(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    monkeypatch.setenv("TB_USE_CUSUM", "1")


@pytest.fixture
def ffd_off(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")
    monkeypatch.setenv("TB_USE_CUSUM", "0")


# ── Happy path ──────────────────────────────────────────────────────────

def test_preflight_passes_all_phases_with_all_flags_on(all_flags_on):
    from services.ai_modules.preflight_validator import preflight_validate_shapes
    res = preflight_validate_shapes(ALL_PHASES)
    assert res["ok"], f"Preflight should pass. Failures: {res['failures'][:5]}"
    for p in ("base_invariant", "setup_long", "setup_short", "exit", "risk", "static_name_lists"):
        assert p in res["checked_phases"], f"{p} should be checked"
    assert res["duration_s"] < 15, f"Should be fast (<15s), took {res['duration_s']}s"


def test_preflight_passes_with_ffd_off(ffd_off):
    from services.ai_modules.preflight_validator import preflight_validate_shapes
    res = preflight_validate_shapes(ALL_PHASES)
    assert res["ok"], f"Preflight should pass with FFD off. Failures: {res['failures'][:5]}"


def test_preflight_only_runs_requested_phases(all_flags_on):
    from services.ai_modules.preflight_validator import preflight_validate_shapes
    res = preflight_validate_shapes(["setup"])
    assert res["ok"]
    assert "setup_long" in res["checked_phases"]
    assert "setup_short" not in res["checked_phases"]
    assert "exit" not in res["checked_phases"]
    assert "risk" not in res["checked_phases"]


# ── Negative: validator must catch the 2026-04-21 bug ──────────────────

def test_preflight_detects_ffd_name_mismatch(monkeypatch):
    """Reproduce the bug by stripping FFD from augmented_feature_names and
    assert the validator catches every setup with diff=+5."""
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    from services.ai_modules import feature_augmentors, preflight_validator

    monkeypatch.setattr(
        feature_augmentors, "augmented_feature_names", lambda names: list(names)
    )

    res = preflight_validator.preflight_validate_shapes(["setup", "short"])
    assert not res["ok"]
    assert len(res["failures"]) > 0
    setup_failures = [f for f in res["failures"] if f.get("phase", "").startswith("setup_")]
    assert len(setup_failures) > 0
    for f in setup_failures:
        if "diff" in f:
            assert f["diff"] == 5, f"Expected diff=+5 (missing FFD names), got {f}"


# ── Negative: validator must catch base invariant drift ────────────────

def test_preflight_detects_base_invariant_drift(monkeypatch):
    """If extract_features_bulk ever produces more cols than get_feature_names()
    (e.g., a hypothetical future mistake of adding FFD inline), Phase 3/5/7/etc
    would silently break. This test simulates that drift and asserts catch."""
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")
    from services.ai_modules.preflight_validator import preflight_validate_shapes
    from services.ai_modules.timeseries_features import get_feature_engineer
    import numpy as np

    fe = get_feature_engineer()
    original = fe.extract_features_bulk

    def bogus_bulk(bars):
        mat = original(bars)
        if mat is None:
            return None
        # Inject 5 fake columns → mimics silent FFD-injection drift
        return np.concatenate([mat, np.zeros((mat.shape[0], 5), dtype=mat.dtype)], axis=1)

    monkeypatch.setattr(fe, "extract_features_bulk", bogus_bulk)

    res = preflight_validate_shapes(["volatility"])  # any non-setup phase hits the invariant
    assert not res["ok"], "Should flag base invariant drift"
    base_fail = next((f for f in res["failures"] if f["phase"] == "base_invariant"), None)
    assert base_fail is not None
    assert base_fail["diff"] == 5
