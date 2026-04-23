"""
Tests for triple_barrier_labeler.validate_label_distribution.

The validator is wired into the training pipeline (both
train_full_universe and train_from_features) and emits warnings
when training labels are pathologically skewed — the likely root cause
of the "p_up_p95 = 0.424" collapse we saw on v20260422_233118.
"""
import numpy as np
import pytest

from services.ai_modules.triple_barrier_labeler import (
    label_distribution,
    validate_label_distribution,
)


# ── label_distribution (existing helper) ────────────────────────────────

def test_label_distribution_empty():
    d = label_distribution(np.array([], dtype=np.int64))
    assert d == {"down": 0.0, "flat": 0.0, "up": 0.0, "total": 0}


def test_label_distribution_balanced():
    labels = np.array([-1, -1, 0, 0, 1, 1], dtype=np.int64)
    d = label_distribution(labels)
    assert d["down"] == pytest.approx(1 / 3)
    assert d["flat"] == pytest.approx(1 / 3)
    assert d["up"] == pytest.approx(1 / 3)
    assert d["total"] == 6


# ── validate_label_distribution ──────────────────────────────────────────

def test_healthy_balanced_distribution():
    labels = np.concatenate([
        np.full(300, -1), np.full(300, 0), np.full(300, 1),
    ])
    result = validate_label_distribution(labels)
    assert result["status"] == "healthy"
    assert result["issues"] == []
    assert result["distribution"]["total"] == 900


def test_down_dominant_triggers_critical():
    """50/43/7 scenario from the Spark diagnostic — should be CRITICAL."""
    labels = np.concatenate([
        np.full(750, -1),   # 75% DOWN — triggers dominant_max_pct (>70%)
        np.full(180, 0),    # 18% FLAT
        np.full(70, 1),     # 7% UP  — below min_class_pct (10%)
    ])
    result = validate_label_distribution(labels)
    assert result["status"] == "critical"
    issues_text = " | ".join(result["issues"])
    assert "UP class only" in issues_text
    assert "DOWN" in issues_text and "dominate" in issues_text.lower()
    # At least one recommendation about class balance
    assert any("balanced" in r.lower() for r in result["recommendations"])


def test_flat_absorbing_signal_triggers_warning():
    """Wide barriers / long horizon → FLAT eats most samples."""
    labels = np.concatenate([
        np.full(150, -1),   # 15% DOWN
        np.full(700, 0),    # 70% FLAT  — triggers flat_max_pct AND dominant
        np.full(150, 1),    # 15% UP
    ])
    result = validate_label_distribution(labels)
    # 70% FLAT triggers both flat_max_pct (>55%) AND dominant (>70%? no, it's exactly 70% = not >70%)
    # So it's a warning, not critical
    assert result["status"] == "warning"
    assert any("FLAT" in i and "too wide" in i for i in result["issues"])
    assert any("sweep" in r.lower() for r in result["recommendations"])


def test_up_rare_triggers_warning():
    """UP underrepresented — model can't learn LONGs."""
    labels = np.concatenate([
        np.full(450, -1), np.full(450, 0), np.full(50, 1),
    ])
    result = validate_label_distribution(labels)
    assert result["status"] == "warning"
    assert any("UP" in i for i in result["issues"])


def test_empty_labels_return_critical():
    result = validate_label_distribution(np.array([], dtype=np.int64))
    assert result["status"] == "critical"
    assert "no labels" in result["issues"][0]


def test_custom_thresholds_respected():
    """Override thresholds to make a previously-healthy dist look broken."""
    labels = np.concatenate([
        np.full(300, -1), np.full(300, 0), np.full(300, 1),
    ])
    # Raise min_class_pct to 0.5 — no class can reach it with 3-way balance
    result = validate_label_distribution(labels, min_class_pct=0.5)
    assert result["status"] == "warning"
    assert len(result["issues"]) == 3  # all three classes below 50%


def test_recommendations_present_when_issues_exist():
    labels = np.concatenate([
        np.full(750, -1), np.full(200, 0), np.full(50, 1),
    ])
    result = validate_label_distribution(labels)
    assert result["status"] == "critical"
    assert len(result["recommendations"]) >= 1


def test_healthy_default_recommendation():
    labels = np.concatenate([
        np.full(300, -1), np.full(300, 0), np.full(300, 1),
    ])
    result = validate_label_distribution(labels)
    assert result["status"] == "healthy"
    assert any("healthy" in r.lower() for r in result["recommendations"])


def test_distribution_totals_match_labels_array():
    labels = np.array([-1, -1, 0, 1, 1, 1], dtype=np.int64)
    result = validate_label_distribution(labels)
    d = result["distribution"]
    assert d["total"] == 6
    assert d["down"] == pytest.approx(2 / 6)
    assert d["flat"] == pytest.approx(1 / 6)
    assert d["up"] == pytest.approx(3 / 6)
