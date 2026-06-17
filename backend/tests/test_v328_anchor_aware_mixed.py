"""v19.34.321 (v328 patch) — anchor-aware MIXED/UNKNOWN trading-mode regression.

Run on the DGX AFTER applying patch_v328_anchor_aware_mixed_mode.py:
    .venv/bin/python -m pytest backend/tests/test_v328_anchor_aware_mixed.py -q

Asserts the MIXED branch of mode_for_direction is anchor-aware (with-trend side
tradeable, counter-trend side defensive) while ALIGNED/PULLBACK paths are unchanged.
"""
from services.multi_tf_regime import mode_for_direction


def test_mixed_up_anchor_unlocks_longs_benches_shorts():
    # Strong daily anchor (91/UP) + neutral intraday → MIXED.
    assert mode_for_direction("MIXED", "long", 91) == "normal"
    assert mode_for_direction("MIXED", "short", 91) == "defensive"


def test_mixed_down_anchor_is_symmetric():
    assert mode_for_direction("MIXED", "long", 25) == "defensive"
    assert mode_for_direction("MIXED", "short", 25) == "normal"


def test_mixed_neutral_or_unknown_anchor_stays_cautious():
    assert mode_for_direction("MIXED", "long", 50) == "cautious"
    assert mode_for_direction("MIXED", "short", 55) == "cautious"
    assert mode_for_direction("MIXED", "long", None) == "cautious"


def test_aligned_and_pullback_paths_unchanged():
    assert mode_for_direction("ALIGNED_UP", "long", 91) == "aggressive"
    assert mode_for_direction("ALIGNED_UP", "long", 65) == "normal"
    assert mode_for_direction("ALIGNED_UP", "short", 91) == "defensive"
    assert mode_for_direction("ALIGNED_DOWN", "short", 25) == "aggressive"
    assert mode_for_direction("ALIGNED_DOWN", "long", 25) == "defensive"
    assert mode_for_direction("PULLBACK_IN_UPTREND", "long", 65) == "normal"
    assert mode_for_direction("PULLBACK_IN_UPTREND", "short", 65) == "cautious"
    assert mode_for_direction("BOUNCE_IN_DOWNTREND", "short", 35) == "normal"
    assert mode_for_direction("BOUNCE_IN_DOWNTREND", "long", 35) == "cautious"
