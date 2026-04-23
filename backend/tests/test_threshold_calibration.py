"""
Tests for the per-model threshold calibration (P1 2026-04-23).

Covers:
  - Pure math on synthetic probability distributions
  - Bounds enforcement (floor/ceiling)
  - Fallbacks when inputs are empty / malformed / NaN
  - ModelMetrics round-trip (stored + loaded from DB dict)
  - get_effective_threshold consumer helper
"""
import numpy as np
import pytest

from services.ai_modules.threshold_calibration import (
    calibrate_threshold,
    calibrate_thresholds_from_probs,
    get_effective_threshold,
    DEFAULT_FLOOR,
    DEFAULT_CEILING,
    NEUTRAL_THRESHOLD,
)
from services.ai_modules.timeseries_gbm import ModelMetrics


# ── calibrate_threshold ──────────────────────────────────────────────────

def test_calibrate_threshold_empty_returns_neutral():
    assert calibrate_threshold(np.array([])) == NEUTRAL_THRESHOLD


def test_calibrate_threshold_none_returns_neutral():
    assert calibrate_threshold(None) == NEUTRAL_THRESHOLD


def test_calibrate_threshold_all_nan_returns_neutral():
    assert calibrate_threshold(np.array([np.nan, np.nan, np.nan])) == NEUTRAL_THRESHOLD


def test_calibrate_threshold_uniform_values_returns_that_value():
    vals = np.array([0.48] * 100)
    assert calibrate_threshold(vals) == pytest.approx(0.48, abs=0.01)


def test_calibrate_threshold_floor_applied():
    """A uniform value of 0.30 should clamp UP to floor (0.45)."""
    vals = np.array([0.30] * 100)
    assert calibrate_threshold(vals) == DEFAULT_FLOOR


def test_calibrate_threshold_ceiling_applied():
    """A uniform value of 0.90 should clamp DOWN to ceiling (0.60)."""
    vals = np.array([0.90] * 100)
    assert calibrate_threshold(vals) == DEFAULT_CEILING


def test_calibrate_threshold_p80_matches_percentile():
    """For a well-formed distribution, return ~p80 of values."""
    vals = np.linspace(0.30, 0.70, 200)  # uniform 0.30 → 0.70
    thr = calibrate_threshold(vals, percentile=80)
    # p80 = ~0.62 raw → clamped to ceiling 0.60
    assert thr == pytest.approx(0.60, abs=0.01)


def test_calibrate_threshold_nan_values_filtered():
    vals = np.array([0.4, np.nan, 0.5, np.inf, 0.55, 0.48])
    thr = calibrate_threshold(vals, percentile=50)
    assert thr == pytest.approx(0.49, abs=0.02)


# ── calibrate_thresholds_from_probs (multiclass) ────────────────────────

def test_3class_calibration_generic_collapse_scenario():
    """Mimics the Spark diagnostic output: UP probs peak around 0.42."""
    # P(DOWN), P(FLAT), P(UP) columns
    n = 1000
    rng = np.random.default_rng(42)
    p_down = rng.uniform(0.40, 0.55, n)
    p_flat = rng.uniform(0.35, 0.45, n)
    p_up = rng.uniform(0.15, 0.45, n)
    # Normalize each row to sum to 1
    mat = np.column_stack([p_down, p_flat, p_up])
    mat = mat / mat.sum(axis=1, keepdims=True)

    up_thr, down_thr = calibrate_thresholds_from_probs(mat, num_classes=3)
    # UP p80 is well below 0.45 → clamped to floor
    assert up_thr == DEFAULT_FLOOR
    # DOWN is stronger → should be higher
    assert down_thr >= up_thr


def test_3class_calibration_healthy_model():
    """A well-calibrated model has UP probs spread up to 0.70."""
    rng = np.random.default_rng(7)
    p_up = rng.uniform(0.30, 0.70, 500)
    p_down = rng.uniform(0.20, 0.40, 500)
    p_flat = 1.0 - p_up - p_down
    mat = np.column_stack([p_down, p_flat, p_up])

    up_thr, down_thr = calibrate_thresholds_from_probs(mat, num_classes=3)
    # p80 of a 0.30-0.70 uniform is ~0.62 → clamped to ceiling 0.60
    assert up_thr == DEFAULT_CEILING
    assert DEFAULT_FLOOR <= down_thr <= DEFAULT_CEILING


def test_2class_calibration_binary_path():
    """Legacy binary model: y_pred_proba is 1D = P(UP)."""
    p_up = np.linspace(0.30, 0.70, 200)
    up_thr, down_thr = calibrate_thresholds_from_probs(p_up, num_classes=2)
    assert DEFAULT_FLOOR <= up_thr <= DEFAULT_CEILING
    assert DEFAULT_FLOOR <= down_thr <= DEFAULT_CEILING


def test_calibration_empty_matrix_returns_neutral():
    up_thr, down_thr = calibrate_thresholds_from_probs(np.zeros((0, 3)))
    assert up_thr == NEUTRAL_THRESHOLD
    assert down_thr == NEUTRAL_THRESHOLD


def test_calibration_none_returns_neutral():
    up_thr, down_thr = calibrate_thresholds_from_probs(None)
    assert up_thr == NEUTRAL_THRESHOLD
    assert down_thr == NEUTRAL_THRESHOLD


def test_calibration_bad_shape_returns_neutral():
    # 2D but only 2 columns when num_classes=3 — unexpected
    mat = np.array([[0.5, 0.5], [0.5, 0.5]])
    up_thr, down_thr = calibrate_thresholds_from_probs(mat, num_classes=3)
    assert up_thr == NEUTRAL_THRESHOLD
    assert down_thr == NEUTRAL_THRESHOLD


# ── ModelMetrics round-trip ──────────────────────────────────────────────

def test_modelmetrics_default_thresholds_are_neutral():
    m = ModelMetrics()
    d = m.to_dict()
    assert d["calibrated_up_threshold"] == 0.50
    assert d["calibrated_down_threshold"] == 0.50


def test_modelmetrics_stores_and_roundtrips_thresholds():
    m = ModelMetrics(calibrated_up_threshold=0.48, calibrated_down_threshold=0.58)
    d = m.to_dict()
    assert d["calibrated_up_threshold"] == 0.48
    assert d["calibrated_down_threshold"] == 0.58
    # Load back from dict
    m2 = ModelMetrics(**d)
    assert m2.calibrated_up_threshold == 0.48
    assert m2.calibrated_down_threshold == 0.58


def test_modelmetrics_loads_from_legacy_dict_without_calibration_fields():
    """Old models saved before this fix won't have the fields — fall back to default."""
    legacy = {"accuracy": 0.52, "precision_up": 0.4, "recall_up": 0.3}
    m = ModelMetrics(**legacy)
    assert m.calibrated_up_threshold == 0.50  # default applied
    assert m.calibrated_down_threshold == 0.50


# ── get_effective_threshold consumer ─────────────────────────────────────

def test_get_effective_threshold_long_reads_up():
    metrics = {"calibrated_up_threshold": 0.47, "calibrated_down_threshold": 0.58}
    assert get_effective_threshold(metrics, "long") == 0.47
    assert get_effective_threshold(metrics, "up") == 0.47
    assert get_effective_threshold(metrics, "buy") == 0.47


def test_get_effective_threshold_short_reads_down():
    metrics = {"calibrated_up_threshold": 0.47, "calibrated_down_threshold": 0.58}
    assert get_effective_threshold(metrics, "short") == 0.58
    assert get_effective_threshold(metrics, "down") == 0.58


def test_get_effective_threshold_none_metrics_is_neutral():
    assert get_effective_threshold(None, "long") == NEUTRAL_THRESHOLD


def test_get_effective_threshold_missing_field_is_neutral():
    assert get_effective_threshold({"accuracy": 0.5}, "long") == NEUTRAL_THRESHOLD


def test_get_effective_threshold_zero_value_is_neutral():
    """A stored 0.0 indicates the field was never calibrated — use neutral."""
    assert get_effective_threshold({"calibrated_up_threshold": 0.0}, "long") == NEUTRAL_THRESHOLD


def test_get_effective_threshold_above_ceiling_clamped():
    assert get_effective_threshold(
        {"calibrated_up_threshold": 0.99}, "long"
    ) == DEFAULT_CEILING


def test_get_effective_threshold_below_floor_clamped():
    assert get_effective_threshold(
        {"calibrated_up_threshold": 0.10}, "long"
    ) == DEFAULT_FLOOR


def test_get_effective_threshold_unknown_direction_neutral():
    metrics = {"calibrated_up_threshold": 0.47, "calibrated_down_threshold": 0.58}
    assert get_effective_threshold(metrics, "flat") == NEUTRAL_THRESHOLD
    assert get_effective_threshold(metrics, None) == NEUTRAL_THRESHOLD
