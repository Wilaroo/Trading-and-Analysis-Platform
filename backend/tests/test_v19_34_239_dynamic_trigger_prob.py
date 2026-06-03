"""
v19.34.239 — dynamic `trigger_probability`.

Each detector stamps a hardcoded per-setup `trigger_probability` constant; we
treat it as a CALIBRATED BASE and let live distance-to-trigger + RVOL move it,
clamped to [0.15, 0.90]. The recompute is wired into the single enrichment
chokepoint `_apply_setup_context`, so all 53 detectors get it for free.

These tests cover the pure helper `compute_live_trigger_probability` (the math)
since the chokepoint wiring is a one-line application of it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.enhanced_scanner import compute_live_trigger_probability  # noqa: E402


def test_base_passthrough_at_neutral():
    # Neutral distance (0.7-1.2% band) + neutral RVOL (1.0-2.0x) → ~0 delta.
    assert abs(compute_live_trigger_probability(0.55, 1.0, 1.5) - 0.55) < 1e-9


def test_close_and_high_rvol_lifts():
    # Very close to trigger (<0.3%) + strong RVOL (>=4) → +0.12 +0.12 = +0.24.
    out = compute_live_trigger_probability(0.50, 0.1, 5.0)
    assert out > 0.50
    assert abs(out - 0.74) < 1e-9


def test_far_and_low_rvol_drops():
    # Far from trigger (>2%) + thin RVOL (<1) → -0.12 -0.06 = -0.18.
    out = compute_live_trigger_probability(0.50, 3.0, 0.4)
    assert out < 0.50
    assert abs(out - 0.32) < 1e-9


def test_upper_clamp():
    assert compute_live_trigger_probability(0.90, 0.05, 6.0) == 0.90


def test_lower_clamp():
    assert compute_live_trigger_probability(0.15, 5.0, 0.1) == 0.15


def test_identity_preserved_across_setups():
    # Two setups with different bases keep their ordering after the SAME
    # live deltas (identity preserved — the base is calibrated per-setup).
    a = compute_live_trigger_probability(0.40, 0.5, 3.0)
    b = compute_live_trigger_probability(0.65, 0.5, 3.0)
    assert b > a


def test_garbage_base_defaults_safely():
    out = compute_live_trigger_probability(None, 0.6, 1.5)
    assert 0.15 <= out <= 0.90


def test_none_inputs_do_not_crash():
    out = compute_live_trigger_probability(0.55, None, None)
    assert 0.15 <= out <= 0.90
