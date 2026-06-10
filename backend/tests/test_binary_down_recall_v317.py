"""
v19.34.317 — binary-model DOWN-metric regression.

The class-collapse gate rejects when min(recall_up, recall_down) < floor. The
binary eval branch never computed recall_down (defaulted to 0.0), so EVERY
2-class model (vol_predictor_*, gap_fill_*, ...) was permanently rejected.
These tests pin the per-class confusion-matrix math the fix relies on.
"""
import numpy as np


def _binary_metrics(y_pred, y_val):
    """Mirror of the fixed binary eval block in timeseries_gbm.train_from_features."""
    tp_up = np.sum((y_pred == 1) & (y_val == 1))
    fp_up = np.sum((y_pred == 1) & (y_val == 0))
    fn_up = np.sum((y_pred == 0) & (y_val == 1))
    recall_up = tp_up / (tp_up + fn_up) if (tp_up + fn_up) > 0 else 0.0

    tp_dn = np.sum((y_pred == 0) & (y_val == 0))
    fp_dn = np.sum((y_pred == 0) & (y_val == 1))
    fn_dn = np.sum((y_pred == 1) & (y_val == 0))
    recall_down = tp_dn / (tp_dn + fn_dn) if (tp_dn + fn_dn) > 0 else 0.0
    return float(recall_up), float(recall_down)


def test_healthy_two_sided_model_has_nonzero_down_recall():
    # Balanced predictions tracking truth → both recalls high, gate should PASS
    y_val = np.array([1, 0, 1, 0, 1, 0, 1, 0])
    y_pred = np.array([1, 0, 1, 0, 1, 0, 0, 1])
    ru, rd = _binary_metrics(y_pred, y_val)
    assert ru > 0.1 and rd > 0.1
    assert min(ru, rd) >= 0.10  # passes the v312 floor


def test_genuinely_collapsed_model_still_rejected():
    # Predicts UP for everything → recall_down truly 0 → gate SHOULD reject
    y_val = np.array([1, 0, 1, 0, 1, 0])
    y_pred = np.ones_like(y_val)
    ru, rd = _binary_metrics(y_pred, y_val)
    assert ru == 1.0
    assert rd == 0.0
    assert min(ru, rd) < 0.10


def test_old_bug_repro_down_never_computed_defaults_zero():
    # Demonstrates the pre-fix failure mode: if recall_down is omitted it
    # defaults 0.0, and a perfectly good two-sided model is wrongly rejected.
    y_val = np.array([1, 0, 1, 0])
    y_pred = np.array([1, 0, 1, 0])  # 100% correct
    ru, rd = _binary_metrics(y_pred, y_val)
    assert ru == 1.0 and rd == 1.0           # with the fix: both perfect
    legacy_rd = 0.0                          # pre-fix default
    assert min(ru, legacy_rd) < 0.10         # would have been (wrongly) rejected
    assert min(ru, rd) >= 0.10               # now correctly passes
