"""Unit tests for Phase 1 foundational modules.

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_phase1_foundation.py -v
"""
import numpy as np
import pytest

from services.ai_modules.event_intervals import (
    build_event_intervals_from_triple_barrier,
    num_concurrent_events,
    average_uniqueness,
    concurrency_weights,
    max_event_interval_overlap,
)
from services.ai_modules.purged_cpcv import (
    PurgedKFold,
    CombinatorialPurgedKFold,
    cpcv_stability,
)
from services.ai_modules.deflated_sharpe import (
    expected_max_sharpe,
    deflated_sharpe_ratio,
    sharpe_with_moments,
)
from services.ai_modules.model_scorecard import (
    ModelScorecard,
    compute_composite,
    compute_red_lines,
    compute_sortino,
    compute_calmar,
    compute_turnover,
    compute_regime_stability,
    finalize_scorecard,
)


# ─── Event Intervals ───────────────────────────────────────

def _synthetic_bars(n=300, seed=7):
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(0, 0.6, n))
    highs = closes + np.abs(rng.normal(0, 0.4, n)) + 0.2
    lows = closes - np.abs(rng.normal(0, 0.4, n)) - 0.2
    return highs, lows, closes


def test_event_intervals_shape_and_bounds():
    h, l, c = _synthetic_bars(200)
    entries = np.arange(50, 180)
    iv = build_event_intervals_from_triple_barrier(
        h, l, c, entries, pt_atr_mult=2.0, sl_atr_mult=1.0, max_bars=10
    )
    assert iv.shape == (len(entries), 2)
    assert (iv[:, 0] <= iv[:, 1]).all()
    # Exit must be within max_bars of entry
    assert ((iv[:, 1] - iv[:, 0]) <= 10).all()


def test_concurrent_event_count_sums_correctly():
    # Two events, same span
    iv = np.array([[10, 20], [15, 25]], dtype=np.int64)
    conc = num_concurrent_events(iv, 30)
    # Bars 10-14: 1 event; 15-20: 2 events; 21-25: 1 event
    assert conc[12] == 1
    assert conc[18] == 2
    assert conc[23] == 1


def test_average_uniqueness_inverse_to_overlap():
    # 2 perfectly overlapping events → each has uniqueness = 0.5
    iv = np.array([[0, 9], [0, 9]], dtype=np.int64)
    u = average_uniqueness(iv, 10)
    assert np.allclose(u, 0.5, atol=0.01)
    # 2 non-overlapping events → each has uniqueness = 1.0
    iv2 = np.array([[0, 4], [5, 9]], dtype=np.int64)
    u2 = average_uniqueness(iv2, 10)
    assert np.allclose(u2, 1.0, atol=0.01)


def test_concurrency_weights_normalized_to_mean_1():
    iv = np.array([[0, 9], [0, 9], [5, 14]], dtype=np.int64)
    w = concurrency_weights(iv, n_bars=15)
    assert np.isclose(w.mean(), 1.0, atol=0.01)
    # More unique event has higher weight
    assert w[2] > w[0]


def test_max_event_overlap_detects_leakage():
    train_iv = np.array([[0, 9], [10, 19]], dtype=np.int64)
    test_iv = np.array([[8, 12]], dtype=np.int64)   # overlaps both
    n = max_event_interval_overlap(train_iv, test_iv)
    assert n == 2


# ─── Purged CV ─────────────────────────────────────────────

def test_purged_kfold_no_overlap():
    iv = np.array([[i, i + 5] for i in range(0, 100, 5)], dtype=np.int64)
    splitter = PurgedKFold(iv, n_splits=5, embargo_bars=2)
    for train_idx, test_idx in splitter.split():
        # No train event may overlap any test event
        overlaps = max_event_interval_overlap(iv[train_idx], iv[test_idx])
        assert overlaps == 0


def test_cpcv_num_combinations():
    iv = np.array([[i, i + 3] for i in range(60)], dtype=np.int64)
    cv = CombinatorialPurgedKFold(iv, n_splits=6, n_test_splits=2, embargo_bars=1)
    assert cv.num_combinations() == 15  # C(6,2)
    n = sum(1 for _ in cv.split())
    assert n == 15


def test_cpcv_stability_summary():
    stats = cpcv_stability([1.2, 0.8, 1.5, -0.3, 1.1, 0.9, 1.3])
    assert stats["n"] == 7
    assert 0.5 < stats["mean"] < 1.2
    assert 0 < stats["negative_pct"] < 1.0


# ─── Deflated Sharpe ───────────────────────────────────────

def test_expected_max_sharpe_grows_with_N():
    v = 0.5
    e_2 = expected_max_sharpe(2, v)
    e_100 = expected_max_sharpe(100, v)
    e_1000 = expected_max_sharpe(1000, v)
    assert e_2 < e_100 < e_1000


def test_deflated_sharpe_strong_genuine_alpha_is_significant():
    r = deflated_sharpe_ratio(
        sharpe_observed=2.0, num_trials=10, trial_variance=0.3,
        sample_length=500, skewness=0.0, kurtosis=3.0,
    )
    assert r["p_value"] > 0.95
    assert r["is_significant"]


def test_deflated_sharpe_lucky_result_is_flagged():
    # High Sharpe but huge number of trials → should NOT be significant
    r = deflated_sharpe_ratio(
        sharpe_observed=1.0, num_trials=1000, trial_variance=0.5,
        sample_length=60, skewness=0.0, kurtosis=3.0,
    )
    # Not a strict test — depends on parameters — but p_value should be < 0.95
    assert r["p_value"] < 0.95


def test_sharpe_with_moments():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.02, 500)
    m = sharpe_with_moments(r, annualization=252)
    assert m["n"] == 500
    assert m["sharpe"] != 0
    assert -2 < m["skew"] < 2
    assert 2 < m["kurt"] < 6


# ─── Scorecard ─────────────────────────────────────────────

def test_composite_grade_F_for_empty():
    # Empty scorecard: zero DSR/Sortino/edge/robust/PF → composite is low,
    # but the drawdown factor rewards 0% max_DD (= 0.15 out of 0.15). That's
    # still below the F→D cutoff of 35, so grade stays F.
    sc = ModelScorecard()
    score, grade = compute_composite(sc)
    assert score < 35.0
    assert grade == "F"


def test_composite_grade_A_for_excellent():
    sc = ModelScorecard(
        deflated_sharpe=2.0, sortino=3.0, max_drawdown_pct=10.0,
        ai_vs_setup_edge_pp=10.0, walk_forward_efficiency=1.0,
        profit_factor=2.5, is_statistically_significant=True,
    )
    score, grade = compute_composite(sc)
    assert score >= 80
    assert grade == "A"


def test_red_lines_trigger():
    sc = ModelScorecard(num_trades=10, sortino=-0.5, max_drawdown_pct=60, dsr_p_value=0.5)
    fails = compute_red_lines(sc)
    assert "trades<30" in fails
    assert "sortino<0" in fails
    assert any("drawdown" in f for f in fails)
    assert any("dsr_p" in f for f in fails)


def test_sortino_ignores_upside():
    # Returns with big upside spikes — Sortino should not be inflated
    r = np.array([0.02, 0.03, 0.10, -0.01, -0.02, 0.02, 0.05, -0.005])
    s = compute_sortino(r)
    assert s > 0
    assert np.isfinite(s)


def test_calmar_basic():
    assert compute_calmar(30, 10) == 3.0
    assert compute_calmar(20, 0) == 0.0


def test_regime_stability_high_for_uniform():
    s_uniform = compute_regime_stability([1.0, 1.0, 1.0, 1.0])
    s_volatile = compute_regime_stability([1.0, -0.5, 2.0, 0.1])
    assert s_uniform > s_volatile


def test_finalize_scorecard_wires_composite_and_redlines():
    sc = ModelScorecard(
        num_trades=50, sortino=1.5, max_drawdown_pct=12,
        deflated_sharpe=1.0, ai_vs_setup_edge_pp=5,
        walk_forward_efficiency=0.8, profit_factor=1.5,
        dsr_p_value=0.96, is_statistically_significant=True,
    )
    sc2 = finalize_scorecard(sc)
    assert sc2.composite_score > 0
    assert sc2.composite_grade in {"A", "B", "C", "D", "F"}
    assert isinstance(sc2.red_line_failures, list)
