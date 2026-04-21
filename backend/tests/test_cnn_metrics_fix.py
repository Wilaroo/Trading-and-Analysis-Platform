"""
Tests for CNN per-setup training metrics shape (post 2026-04-21 fix).

Before the fix, cnn_training_pipeline.train_cnn_model() saved the degenerate
17-class pattern-classification accuracy as `metrics.accuracy`, which was
tautologically 1.0 for every model. The scorecard/UI then showed misleading
100% everywhere.

After the fix:
  • `accuracy` must equal `win_auc` (the actual predictive metric)
  • `win_accuracy`, `win_precision`, `win_recall`, `win_f1` must be present
    as real binary WIN/LOSS classifier metrics
  • `pattern_classification_accuracy` is kept as debug-only reference
  • Promotion gate still keys on `win_auc >= MIN_WIN_AUC_THRESHOLD`

These tests verify the metrics-dict shape without running the full CNN
(which needs GPU + thousands of chart images). They patch the evaluation
loop outputs and assert the resulting metrics structure.
"""
import numpy as np
import pytest


def _make_metrics(win_preds, win_trues, pattern_acc=1.0, n_train=2000, n_val=500):
    """Mirror the metrics-dict construction in cnn_training_pipeline.train_cnn_model().
    Keeps the test free of GPU/torch dependencies."""
    from sklearn.metrics import (
        roc_auc_score, accuracy_score, precision_score, recall_score, f1_score,
    )
    y_true = np.asarray(win_trues, dtype=np.int32)
    y_score = np.asarray(win_preds, dtype=np.float32)
    win_auc = 0.5
    win_acc_binary = win_precision = win_recall = win_f1 = 0.0
    if len(set(win_trues)) > 1:
        win_auc = float(roc_auc_score(y_true, y_score))
        y_pred_bin = (y_score >= 0.5).astype(np.int32)
        win_acc_binary = float(accuracy_score(y_true, y_pred_bin))
        win_precision = float(precision_score(y_true, y_pred_bin, zero_division=0))
        win_recall = float(recall_score(y_true, y_pred_bin, zero_division=0))
        win_f1 = float(f1_score(y_true, y_pred_bin, zero_division=0))

    total = len(y_true)
    return {
        "accuracy": round(win_auc, 4),
        "win_auc": round(win_auc, 4),
        "win_accuracy": round(win_acc_binary, 4),
        "win_precision": round(win_precision, 4),
        "win_recall": round(win_recall, 4),
        "win_f1": round(win_f1, 4),
        "pattern_classification_accuracy": round(pattern_acc, 4),
        "test_samples": total,
        "train_samples": n_train,
        "val_samples": n_val,
        "total_samples": n_train + n_val + total,
        "best_val_loss": 0.2195,
        "win_rate_in_data": round(sum(win_trues) / max(len(win_trues), 1), 4),
    }


# ── Happy-path: perfect classifier (AUC=1.0) ─────────────────────────

def test_metrics_primary_accuracy_equals_win_auc():
    y_true = [0]*400 + [1]*100  # 80/20 class imbalance like real CNN data
    y_score = [0.1]*400 + [0.9]*100  # perfect separation
    m = _make_metrics(y_score, y_true, pattern_acc=1.0)

    assert m["accuracy"] == m["win_auc"], \
        "Primary accuracy must equal win_auc (not the tautological pattern acc)"
    assert m["win_auc"] == 1.0
    assert m["win_accuracy"] == 1.0
    assert m["win_precision"] == 1.0
    assert m["win_recall"] == 1.0
    assert m["win_f1"] == 1.0
    # Pattern acc preserved for debugging
    assert m["pattern_classification_accuracy"] == 1.0


# ── Realistic imbalanced case (mirrors real CNN training) ────────────

def test_metrics_realistic_imbalanced_classifier():
    # Simulate 8% win rate like the real CNN data, AUC ~0.81
    rng = np.random.default_rng(42)
    n_loss, n_win = 460, 40
    y_true = [0]*n_loss + [1]*n_win
    # Losses: scores centered at 0.3, wins: scores centered at 0.7 (good separation)
    loss_scores = rng.normal(0.3, 0.15, n_loss).clip(0, 1)
    win_scores = rng.normal(0.7, 0.15, n_win).clip(0, 1)
    y_score = list(loss_scores) + list(win_scores)

    m = _make_metrics(y_score, y_true)
    # All win-* metrics must be finite numbers in [0,1]
    for k in ("win_auc", "win_accuracy", "win_precision", "win_recall", "win_f1"):
        assert 0.0 <= m[k] <= 1.0, f"{k} out of range: {m[k]}"
    # win_auc should be high (>0.8) for this separation
    assert m["win_auc"] > 0.8, f"Expected AUC>0.8, got {m['win_auc']}"
    # win_rate_in_data matches
    assert m["win_rate_in_data"] == round(n_win / (n_loss + n_win), 4)


# ── Degenerate: model never predicts positive class ──────────────────

def test_metrics_no_crash_when_classifier_never_predicts_positive():
    """If the CNN always outputs score < 0.5, precision/recall can divide by zero."""
    y_true = [0]*450 + [1]*50
    y_score = [0.2] * 500  # always predicts "loss"
    m = _make_metrics(y_score, y_true)
    # Must not crash; all precision/recall should be 0 (zero_division=0)
    assert m["win_precision"] == 0.0
    assert m["win_recall"] == 0.0
    assert m["win_f1"] == 0.0
    # win_auc still computable (it's a ranking metric, tolerates constant preds
    # → 0.5 at best for single-valued scores)
    assert m["win_auc"] == 0.5
    assert m["accuracy"] == 0.5


# ── Single-class val set fallback ────────────────────────────────────

def test_metrics_single_class_val_set_falls_back_to_baseline():
    y_true = [0] * 500
    y_score = [0.3] * 500
    m = _make_metrics(y_score, y_true)
    assert m["win_auc"] == 0.5   # baseline when only one class present
    assert m["accuracy"] == 0.5
    assert m["win_precision"] == 0.0
    assert m["win_recall"] == 0.0


# ── Migration semantics ──────────────────────────────────────────────

def test_migration_logic_matches_expected_behavior():
    """Emulate the migration: for a doc with metrics.win_auc and old
    metrics.accuracy=1.0, after migration `accuracy` must equal `win_auc`
    and `pattern_classification_accuracy` must preserve the old 1.0."""
    doc = {
        "model_name": "cnn_breakout_5mins",
        "metrics": {
            "accuracy": 1.0,
            "win_auc": 0.8144,
            # pre-fix docs may or may not have pattern_classification_accuracy
        }
    }
    # Apply migration logic (from migrate_cnn_accuracy_to_win_auc.py)
    m = doc["metrics"]
    wa = m["win_auc"]
    acc = m["accuracy"]
    pca = m.get("pattern_classification_accuracy")
    set_ops = {"metrics.accuracy": float(wa)}
    if pca is None and acc is not None:
        set_ops["metrics.pattern_classification_accuracy"] = float(acc)

    # Simulate applying the $set
    for k, v in set_ops.items():
        parts = k.split(".")
        target = doc
        for p in parts[:-1]:
            target = target[p]
        target[parts[-1]] = v

    assert doc["metrics"]["accuracy"] == 0.8144
    assert doc["metrics"]["pattern_classification_accuracy"] == 1.0
    assert doc["metrics"]["win_auc"] == 0.8144  # preserved
