"""
Tests for the pre-flight shape validator.

- Happy path: passes on the real codebase (post-fix).
- Failure detection: when we inject a bad name list, validator reports failures.
"""
import numpy as np
import pytest


def test_preflight_passes_with_ffd_on(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    monkeypatch.setenv("TB_USE_CUSUM", "0")
    from services.ai_modules.preflight_validator import preflight_validate_shapes

    res = preflight_validate_shapes(["setup", "short"])
    assert res["ok"], f"Preflight should pass. Failures: {res['failures'][:3]}"
    assert "setup_long" in res["checked_phases"]
    assert "setup_short" in res["checked_phases"]
    assert res["duration_s"] < 15, f"Should be fast (<15s), took {res['duration_s']}s"


def test_preflight_passes_with_ffd_off(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")
    monkeypatch.setenv("TB_USE_CUSUM", "0")
    from services.ai_modules.preflight_validator import preflight_validate_shapes

    res = preflight_validate_shapes(["setup", "short"])
    assert res["ok"], f"Preflight should pass with FFD off. Failures: {res['failures'][:3]}"


def test_preflight_passes_with_all_flags_on(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    monkeypatch.setenv("TB_USE_CUSUM", "1")
    from services.ai_modules.preflight_validator import preflight_validate_shapes

    res = preflight_validate_shapes(["setup", "short"])
    assert res["ok"], f"Preflight should pass with all flags on. Failures: {res['failures'][:3]}"


def test_preflight_detects_name_mismatch(monkeypatch):
    """Simulate the 2026-04-21 bug: inject an un-augmented base_names list
    and assert the validator catches the mismatch."""
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")

    # Monkey-patch augmented_feature_names to strip FFD → reproduces old bug
    from services.ai_modules import feature_augmentors, preflight_validator

    original = feature_augmentors.augmented_feature_names
    monkeypatch.setattr(
        preflight_validator.__name__ + ".augmented_feature_names"
        if hasattr(preflight_validator, "augmented_feature_names")
        else "services.ai_modules.feature_augmentors.augmented_feature_names",
        lambda names: list(names),  # strip FFD suffix
    )
    # Also patch the import site inside preflight_validator's inner funcs
    # by monkey-patching the module-level import path used at call time:
    monkeypatch.setattr(
        feature_augmentors, "augmented_feature_names", lambda names: list(names)
    )

    res = preflight_validator.preflight_validate_shapes(["setup"])
    assert not res["ok"], "Should fail when augmented_feature_names is broken"
    assert len(res["failures"]) > 0
    # Every failure should show diff = +5 (FFD columns in X not in names)
    for f in res["failures"]:
        if "diff" in f:
            assert f["diff"] == 5, f"Expected diff=+5 (missing FFD names), got {f}"

    # Restore
    monkeypatch.setattr(feature_augmentors, "augmented_feature_names", original)
