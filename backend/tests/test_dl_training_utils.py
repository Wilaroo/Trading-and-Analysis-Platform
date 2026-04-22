"""Tests for backend/services/ai_modules/dl_training_utils.py.

Covers the pure-numpy pieces that close the 4 gaps in TFT/CNN-LSTM training:
  1. Class-weighted CrossEntropy (compute_balanced_class_weights)
  2. Sample uniqueness weights (compute_sample_weights_from_intervals)
  3. Purged chronological split (purged_chronological_split)
  4. DL scorecard builder (build_dl_scorecard)

Plus a leakage-catching regression test for the purged split, and a
class-imbalance smoke test for balanced weights.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_dl_training_utils.py -v
"""
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_modules.dl_training_utils import (  # noqa: E402
    compute_balanced_class_weights,
    compute_sample_weights_from_intervals,
    purged_chronological_split,
    build_dl_scorecard,
    dl_cpcv_folds_from_env,
    run_cpcv_accuracy_stability,
)


# ── compute_balanced_class_weights ──────────────────────────────────────

def test_balanced_class_weights_inverse_frequency():
    # 70% class 0, 10% class 1, 20% class 2 — rare class should get most weight
    y = np.array([0] * 70 + [1] * 10 + [2] * 20, dtype=np.int64)
    w = compute_balanced_class_weights(y, num_classes=3, clip_ratio=5.0)
    assert w.shape == (3,)
    # Scaled so min is 1.0
    assert abs(w.min() - 1.0) < 1e-6
    # Majority class gets lowest weight
    assert w[0] == w.min()
    # Rare class gets the highest weight (possibly clipped)
    assert w[1] >= w[2] >= w[0]
    # Ratio math: raw 70/10 = 7 → should be clipped at 5.0
    assert abs(w[1] - 5.0) < 1e-6


def test_balanced_class_weights_uniform_input():
    # Equal class sizes → all weights equal to 1
    y = np.array([0] * 30 + [1] * 30 + [2] * 30, dtype=np.int64)
    w = compute_balanced_class_weights(y)
    assert np.allclose(w, 1.0)


def test_balanced_class_weights_missing_class_gets_clip():
    # Class 2 entirely absent from training → max weight (clip)
    y = np.array([0] * 50 + [1] * 50, dtype=np.int64)
    w = compute_balanced_class_weights(y, num_classes=3, clip_ratio=5.0)
    assert abs(w[2] - 5.0) < 1e-6


def test_balanced_class_weights_empty_safe():
    w = compute_balanced_class_weights(np.array([], dtype=np.int64), num_classes=3)
    assert np.allclose(w, 1.0)


# ── compute_per_sample_class_weights ───────────────────────────────────

def test_per_sample_class_weights_mean_is_one():
    # 70% class 0, 10% class 1, 20% class 2
    y = np.array([0] * 70 + [1] * 10 + [2] * 20, dtype=np.int64)
    from services.ai_modules.dl_training_utils import compute_per_sample_class_weights
    w = compute_per_sample_class_weights(y, num_classes=3, clip_ratio=5.0)
    assert w.shape == (100,)
    # Normalized to mean == 1.0 so the absolute loss scale is preserved
    assert abs(float(w.mean()) - 1.0) < 1e-5
    # Rare class samples weigh more than majority class samples
    assert w[75] > w[0]  # sample 75 is class 1; sample 0 is class 0
    assert w[85] > w[0]  # sample 85 is class 2


def test_per_sample_class_weights_uniform_input():
    y = np.array([0] * 30 + [1] * 30 + [2] * 30, dtype=np.int64)
    from services.ai_modules.dl_training_utils import compute_per_sample_class_weights
    w = compute_per_sample_class_weights(y)
    assert np.allclose(w, 1.0)


def test_per_sample_class_weights_empty_safe():
    from services.ai_modules.dl_training_utils import compute_per_sample_class_weights
    w = compute_per_sample_class_weights(np.array([], dtype=np.int64), num_classes=3)
    assert len(w) == 0


# ── compute_sample_weights_from_intervals ───────────────────────────────

def test_sample_weights_unique_events_all_ones():
    # 3 non-overlapping events on a 100-bar axis → perfect uniqueness = 1.0
    intervals = np.array([[0, 5], [20, 30], [60, 80]], dtype=np.int64)
    w = compute_sample_weights_from_intervals([intervals], [100])
    assert len(w) == 3
    assert np.allclose(w, 1.0, atol=1e-5)


def test_sample_weights_overlapping_events_down_weighted():
    # 3 events heavily overlap on bars [0..10]; 1 standalone event at 50
    intervals = np.array(
        [[0, 10], [0, 10], [0, 10], [50, 55]], dtype=np.int64
    )
    w = compute_sample_weights_from_intervals([intervals], [100])
    # Mean should be 1.0 (normalized)
    assert abs(float(w.mean()) - 1.0) < 1e-5
    # The standalone event should have higher weight than the overlapping ones
    assert w[3] > w[0]
    assert w[3] > w[1]


def test_sample_weights_multi_symbol_concat():
    s1 = np.array([[0, 5], [20, 30]], dtype=np.int64)
    s2 = np.array([[0, 5]], dtype=np.int64)
    w = compute_sample_weights_from_intervals([s1, s2], [50, 50])
    assert len(w) == 3
    # Everyone is non-overlapping within their symbol → all 1.0 (post-normalize)
    assert np.allclose(w, 1.0, atol=1e-5)


def test_sample_weights_empty_returns_empty():
    w = compute_sample_weights_from_intervals([], [])
    assert len(w) == 0


# ── purged_chronological_split ──────────────────────────────────────────

def test_purged_split_removes_leaky_train_events():
    # 100 samples; last 20 → val. Make one train event whose exit bar leaks past
    # the val-window entry, so the purge should drop it. Global-axis intervals.
    n = 100
    intervals = np.array(
        [[i, i + 2] for i in range(100)], dtype=np.int64
    )
    # Force sample 79 to leak 10 bars into the val window
    intervals[79] = [79, 100]

    train_idx, val_idx = purged_chronological_split(
        intervals=intervals, n_samples=n, split_frac=0.8, embargo_bars=5,
    )
    assert len(val_idx) == 20
    # 79 was the last train sample; its exit leaks past val_min_entry-embargo → purged
    assert 79 not in set(train_idx.tolist())
    # Samples far back (e.g. 0, 1) survive
    assert 0 in set(train_idx.tolist())


def test_purged_split_no_intervals_falls_back_chronological():
    train_idx, val_idx = purged_chronological_split(
        intervals=None, n_samples=100, split_frac=0.8,
    )
    assert len(train_idx) == 80
    assert len(val_idx) == 20
    assert train_idx[0] == 0 and train_idx[-1] == 79
    assert val_idx[0] == 80 and val_idx[-1] == 99


def test_purged_split_misaligned_intervals_falls_back():
    # If intervals shape doesn't match n_samples, don't purge
    intervals = np.array([[0, 5]], dtype=np.int64)  # 1 row, but 100 samples
    train_idx, val_idx = purged_chronological_split(
        intervals=intervals, n_samples=100, split_frac=0.8,
    )
    assert len(train_idx) == 80
    assert len(val_idx) == 20


def test_purged_split_tiny_dataset_returns_empty():
    train_idx, val_idx = purged_chronological_split(None, n_samples=1, split_frac=0.8)
    assert len(train_idx) == 0 and len(val_idx) == 0


# ── build_dl_scorecard ──────────────────────────────────────────────────

def test_build_dl_scorecard_populates_edge_and_grade():
    sc = build_dl_scorecard(
        model_name="tft_multi_tf",
        version="v1",
        num_samples=5000,
        best_val_acc=0.56,
        majority_baseline=0.45,
        class_counts={"down": 1000, "flat": 2250, "up": 1750},
        cpcv_stability={"mean": 0.54, "std": 0.02, "negative_pct": 0.0, "n": 15},
        bar_size="multi_tf",
        trade_side="both",
    )
    assert sc["hit_rate"] == 0.56
    assert sc["majority_baseline"] == 0.45
    # (0.56 - 0.45) * 100 = 11pp
    assert abs(sc["ai_vs_setup_edge_pp"] - 11.0) < 1e-6
    assert sc["num_trades"] == 5000
    assert sc["cpcv_sharpe_mean"] == 0.54
    assert sc["cpcv_n_folds"] == 15
    assert sc["composite_grade"] == "A"  # 11pp >> 5pp threshold
    assert sc["scorecard_source"] == "dl_classifier_training"


def test_build_dl_scorecard_grade_f_when_below_baseline():
    sc = build_dl_scorecard(
        model_name="cnn_lstm_chart",
        version="v1",
        num_samples=1000,
        best_val_acc=0.40,
        majority_baseline=0.50,
        class_counts={"down": 100, "flat": 500, "up": 400},
    )
    # Below baseline → F
    assert sc["composite_grade"] == "F"
    assert sc["ai_vs_setup_edge_pp"] < 0


# ── dl_cpcv_folds_from_env ──────────────────────────────────────────────

def test_dl_cpcv_folds_defaults_to_zero(monkeypatch):
    monkeypatch.delenv("TB_DL_CPCV_FOLDS", raising=False)
    assert dl_cpcv_folds_from_env() == 0


def test_dl_cpcv_folds_reads_env(monkeypatch):
    monkeypatch.setenv("TB_DL_CPCV_FOLDS", "5")
    assert dl_cpcv_folds_from_env() == 5


def test_dl_cpcv_folds_invalid_value_defaults_zero(monkeypatch):
    monkeypatch.setenv("TB_DL_CPCV_FOLDS", "not-a-number")
    assert dl_cpcv_folds_from_env() == 0


def test_dl_cpcv_folds_negative_clamped_to_zero(monkeypatch):
    monkeypatch.setenv("TB_DL_CPCV_FOLDS", "-3")
    assert dl_cpcv_folds_from_env() == 0


# ── run_cpcv_accuracy_stability ─────────────────────────────────────────

def test_run_cpcv_accuracy_stability_integrates_with_purged_cpcv():
    # 150 non-overlapping events on a 1500-bar axis — clears the n_splits*20 guard
    intervals = np.array([[i * 10, i * 10 + 3] for i in range(150)], dtype=np.int64)

    calls = []
    def train_eval(tr, te):
        calls.append((len(tr), len(te)))
        return 0.4 + 0.3 * (len(tr) / (len(tr) + len(te) + 1))

    stab = run_cpcv_accuracy_stability(
        train_eval, intervals=intervals, n_samples=150,
        n_splits=5, n_test_splits=2, embargo_bars=2,
    )
    # C(5, 2) = 10 folds; some may drop if purging empties a side
    assert stab["n"] >= 5
    assert len(calls) >= 5
    assert stab["mean"] > 0.4
    assert stab["mean"] < 0.7


def test_run_cpcv_skips_when_too_few_samples():
    stab = run_cpcv_accuracy_stability(
        lambda tr, te: 1.0, intervals=np.array([[0, 1]]), n_samples=1,
    )
    assert stab["n"] == 0
    assert stab["scores"] == []
