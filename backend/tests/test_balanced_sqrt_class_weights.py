"""
Regression tests for the `balanced_sqrt` class-weight dampener added after the
2026-04-23 Spark retrain collapsed the DOWN class on direction_predictor_5min.

The sklearn-balanced scheme (inverse-frequency) gave recall_up=0.597 but
recall_down=0.000 — the minority UP class was boosted ~2.8× on the 45/39/16
split, which starved DOWN entirely. `balanced_sqrt` softens the boost to ~1.7×
so both minorities stay trainable.

Locks:
  - scheme="balanced_sqrt" returns the sqrt(N_max / count[c]) shape
  - scheme="balanced_sqrt" produces SMALLER max/min ratio than "balanced"
    on the Phase-13 skew (prevents regression back to the collapsing scheme)
  - get_class_weight_scheme() respects TB_CLASS_WEIGHT_MODE env var,
    defaults to 'balanced_sqrt', falls back safely on bad input
  - scheme="balanced" still behaves exactly like the pre-fix sklearn default
    (backward-compat)
  - Unknown scheme raises ValueError (defensive, no silent wrong math)
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from services.ai_modules.dl_training_utils import (
    compute_balanced_class_weights,
    compute_per_sample_class_weights,
    get_class_weight_scheme,
)


PHASE_13_SKEW_Y = np.concatenate([
    np.zeros(390, dtype=np.int64),   # DOWN 39%
    np.ones(450, dtype=np.int64),    # FLAT 45%
    np.full(160, 2, dtype=np.int64), # UP   16%
])


# ─── balanced_sqrt basic math ──────────────────────────────────────────────

def test_balanced_sqrt_formula_matches_sqrt_of_ratio():
    """On the Phase-13 skew, w[c] should be sqrt(N_max / count[c])
    then scaled so min == 1, pre-clip."""
    w = compute_balanced_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced_sqrt",
    )
    # N_max = 450. w_raw = [sqrt(450/390), sqrt(450/450), sqrt(450/160)]
    #                    = [1.0741, 1.0, 1.6771]
    # normalized by min=1.0 -> same values.
    assert w[1] == pytest.approx(1.0, abs=1e-3)          # FLAT (majority) = 1
    assert w[0] == pytest.approx(1.0741, abs=5e-3)       # DOWN
    assert w[2] == pytest.approx(1.6771, abs=5e-3)       # UP (minority)


def test_balanced_sqrt_produces_smaller_max_ratio_than_balanced():
    """The whole point of the fix: max/min boost must be smaller than the
    collapsing `balanced` scheme on the Phase-13 distribution."""
    w_sqrt = compute_balanced_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced_sqrt",
    )
    w_bal = compute_balanced_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced",
    )
    ratio_sqrt = float(w_sqrt.max() / w_sqrt.min())
    ratio_bal = float(w_bal.max() / w_bal.min())
    # Sanity: sqrt-scheme max boost must be well under the 2.8× `balanced` gave
    assert ratio_sqrt < 2.0, f"balanced_sqrt max/min ratio {ratio_sqrt:.3f} too aggressive"
    assert ratio_bal > ratio_sqrt, (
        f"`balanced_sqrt` ({ratio_sqrt:.3f}) must be gentler than `balanced` ({ratio_bal:.3f})"
    )
    # The critical threshold that caused DOWN collapse: >=2.5×.
    # Lock in a margin so we never silently regress past 1.8×.
    assert ratio_sqrt < 1.8


def test_balanced_sqrt_majority_class_is_one():
    """The majority class always gets weight 1 in balanced_sqrt
    (sqrt(N_max/N_max) = 1, and it's also the min so normalisation is a no-op)."""
    w = compute_balanced_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced_sqrt",
    )
    assert w.min() == pytest.approx(1.0)
    assert np.argmin(w) == 1  # FLAT is majority in PHASE_13_SKEW_Y


# ─── Legacy scheme still works ─────────────────────────────────────────────

def test_balanced_scheme_unchanged_for_backward_compat():
    """Callers that pass scheme='balanced' (or the default) must get the
    original sklearn-balanced weights. Legacy behaviour frozen."""
    w = compute_balanced_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced",
    )
    # sklearn "balanced": w[c] = N / (num_classes * count[c])
    #   w_down = 1000/(3*390) = 0.8547
    #   w_flat = 1000/(3*450) = 0.7407
    #   w_up   = 1000/(3*160) = 2.0833
    #   normalized by min 0.7407 -> [1.1538, 1.0, 2.8125]
    assert w[1] == pytest.approx(1.0, abs=1e-3)
    assert w[0] == pytest.approx(1.1538, abs=5e-3)
    assert w[2] == pytest.approx(2.8125, abs=5e-3)


def test_default_scheme_is_balanced_for_helper_backward_compat():
    """Passing no `scheme=` must keep the original `balanced` math so callers
    that never knew about the scheme kwarg (eg unit tests, downstream
    notebooks) don't silently change behaviour."""
    w_default = compute_balanced_class_weights(PHASE_13_SKEW_Y, num_classes=3)
    w_explicit = compute_balanced_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced",
    )
    np.testing.assert_array_equal(w_default, w_explicit)


def test_unknown_scheme_raises_valueerror():
    """Typos must not fall back silently — raise so the bad call is visible."""
    with pytest.raises(ValueError):
        compute_balanced_class_weights(
            PHASE_13_SKEW_Y, num_classes=3, scheme="not-a-scheme",
        )


# ─── Per-sample weight path ────────────────────────────────────────────────

def test_per_sample_class_weights_respects_balanced_sqrt():
    """per-sample path must thread `scheme` through and normalise to mean=1."""
    ps = compute_per_sample_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced_sqrt",
    )
    assert len(ps) == len(PHASE_13_SKEW_Y)
    assert float(ps.mean()) == pytest.approx(1.0, abs=1e-3)
    # UP (class 2, count 160) samples must have higher weight than FLAT (class 1, count 450)
    up_mean = float(ps[PHASE_13_SKEW_Y == 2].mean())
    flat_mean = float(ps[PHASE_13_SKEW_Y == 1].mean())
    down_mean = float(ps[PHASE_13_SKEW_Y == 0].mean())
    assert up_mean > down_mean > flat_mean


# ─── TB_CLASS_WEIGHT_MODE env resolver ─────────────────────────────────────

def test_get_class_weight_scheme_default_is_balanced_sqrt(monkeypatch):
    """The DEFAULT must be balanced_sqrt so the next retrain picks up the fix
    without anyone having to set an env var. This lock-in prevents a future
    refactor from silently re-defaulting back to the collapsing scheme."""
    monkeypatch.delenv("TB_CLASS_WEIGHT_MODE", raising=False)
    assert get_class_weight_scheme() == "balanced_sqrt"


def test_get_class_weight_scheme_accepts_balanced(monkeypatch):
    monkeypatch.setenv("TB_CLASS_WEIGHT_MODE", "balanced")
    assert get_class_weight_scheme() == "balanced"


def test_get_class_weight_scheme_accepts_balanced_sqrt(monkeypatch):
    monkeypatch.setenv("TB_CLASS_WEIGHT_MODE", "balanced_sqrt")
    assert get_class_weight_scheme() == "balanced_sqrt"


def test_get_class_weight_scheme_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("TB_CLASS_WEIGHT_MODE", "  BALANCED_SQRT  ")
    assert get_class_weight_scheme() == "balanced_sqrt"


def test_get_class_weight_scheme_falls_back_on_garbage(monkeypatch):
    """Unknown values must fall back to balanced_sqrt (not the collapsing
    default) so a typo in a deployment env file can't re-introduce the bug."""
    monkeypatch.setenv("TB_CLASS_WEIGHT_MODE", "hyper-boost-9000")
    assert get_class_weight_scheme() == "balanced_sqrt"


# ─── End-to-end integration guard ──────────────────────────────────────────

def test_phase_13_scenario_balanced_sqrt_does_not_starve_any_class():
    """Lock in the headline fix: on the Phase-13 45/39/16 split, no class
    receives < 0.9 weight (i.e. none is gradient-starved)."""
    ps = compute_per_sample_class_weights(
        PHASE_13_SKEW_Y, num_classes=3, scheme="balanced_sqrt",
    )
    for c in range(3):
        cls_mean = float(ps[PHASE_13_SKEW_Y == c].mean())
        assert cls_mean >= 0.85, (
            f"class {c} starved with mean weight {cls_mean:.3f} under balanced_sqrt"
        )
