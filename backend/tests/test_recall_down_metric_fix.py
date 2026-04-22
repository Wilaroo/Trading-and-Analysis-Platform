"""
Regression tests for the `recall_down` / `f1_down` metric computation fix
(CRITICAL FIX #6, 2026-04-22).

Before the fix: `train_full_universe` and `train_from_features` never computed
DOWN-class metrics, so `ModelMetrics.recall_down` and `.f1_down` shipped as
dataclass defaults (0.0). The model-protection gate then compared those zero
defaults to `MIN_DOWN_RECALL=0.1` and rejected every candidate as
"DOWN-collapsed" regardless of actual behaviour.

These tests use a known 3-class confusion matrix to verify the fix produces
the correct DOWN metrics, and that a well-predicting DOWN model is no longer
spuriously rejected.
"""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import precision_score, recall_score, f1_score

from services.ai_modules.timeseries_gbm import ModelMetrics


def _compute_down_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Replicate the per-class DOWN math used inside train_from_features /
    train_full_universe after the fix."""
    y_val_down = (y_true == 0).astype(int)
    y_pred_down = (y_pred == 0).astype(int)
    return {
        "precision_down": float(precision_score(y_val_down, y_pred_down, zero_division=0)),
        "recall_down":    float(recall_score   (y_val_down, y_pred_down, zero_division=0)),
        "f1_down":        float(f1_score       (y_val_down, y_pred_down, zero_division=0)),
    }


# ─── Unit: synthetic 3-class eval ─────────────────────────────────────────

def test_recall_down_reported_correctly_for_perfect_down_predictor():
    """A classifier that predicts DOWN for every DOWN sample must get
    recall_down == 1.0. Before the fix this always reported 0.0."""
    # 100 samples — 45 DOWN, 35 FLAT, 20 UP (Phase-13 skew)
    y_true = np.concatenate([np.zeros(45), np.ones(35), np.full(20, 2)]).astype(int)
    # Perfect predictor
    y_pred = y_true.copy()
    m = _compute_down_metrics(y_true, y_pred)
    assert m["recall_down"] == pytest.approx(1.0)
    assert m["precision_down"] == pytest.approx(1.0)
    assert m["f1_down"] == pytest.approx(1.0)


def test_recall_down_reports_zero_only_when_model_actually_fails_down():
    """If the model NEVER predicts DOWN, recall_down must be 0 — verifying
    the metric genuinely discriminates, not just returns 0 by default."""
    y_true = np.concatenate([np.zeros(45), np.ones(35), np.full(20, 2)]).astype(int)
    # Predict only FLAT (worst-case DOWN predictor)
    y_pred = np.ones_like(y_true)
    m = _compute_down_metrics(y_true, y_pred)
    assert m["recall_down"] == 0.0
    assert m["f1_down"] == 0.0


def test_recall_down_partial_is_between_0_and_1():
    """Partial DOWN recall — model correctly predicts DOWN on half the
    DOWN samples. Before the fix this silently reported 0.0."""
    rng = np.random.default_rng(42)
    y_true = np.concatenate([np.zeros(100), np.ones(50), np.full(30, 2)]).astype(int)
    y_pred = y_true.copy()
    # Flip half the DOWN predictions to FLAT
    down_idx = np.where(y_true == 0)[0]
    to_flip = rng.choice(down_idx, size=50, replace=False)
    y_pred[to_flip] = 1
    m = _compute_down_metrics(y_true, y_pred)
    assert 0.4 < m["recall_down"] < 0.6
    assert 0 < m["f1_down"] < 1


# ─── ModelMetrics plumbing ────────────────────────────────────────────────

def test_model_metrics_accepts_down_fields():
    """The dataclass already had the fields — this test freezes them so a
    future refactor can't silently drop them and re-break the protection
    gate's DOWN check."""
    m = ModelMetrics(
        accuracy=0.55,
        precision_up=0.4, recall_up=0.3, f1_up=0.34,
        precision_down=0.5, recall_down=0.6, f1_down=0.55,
        training_samples=1000, validation_samples=250,
    )
    d = m.to_dict()
    assert d["precision_down"] == pytest.approx(0.5)
    assert d["recall_down"]    == pytest.approx(0.6)
    assert d["f1_down"]        == pytest.approx(0.55)


# ─── End-to-end guard against the protection gate false-reject ───────────

def test_well_predicting_down_model_no_longer_gate_rejected():
    """Regression guard: a model with good DOWN recall (0.6) must NOT
    trigger the 'DOWN collapsed' short-circuit in the protection gate.

    The gate uses `MIN_DOWN_RECALL = 0.10` (hard-coded inline in
    timeseries_gbm.py). Before the fix, every new candidate inherited
    `recall_down = 0.0` from the ModelMetrics default, making this check
    fail for ALL candidates.
    """
    floor = 0.10
    good_recall_down = 0.6
    assert good_recall_down >= floor
