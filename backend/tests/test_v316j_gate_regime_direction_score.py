"""
v316j (c1) — Confidence-gate directional confirmation now reads multi_tf CONTEXT.

Verifies _score_regime_direction():
- ALIGNED_UP/DOWN → conviction-scaled bonus with-trend, hard counter-trend penalty.
- PULLBACK_IN_UPTREND / BOUNCE_IN_DOWNTREND → with-trend bonus, mild against penalty.
- MIXED → small intraday-bias lean only, no hard gate.
- multi_tf absent / UNKNOWN → legacy daily-composite fallback (unchanged behavior).
"""
from services.ai_modules.confidence_gate import (
    ConfidenceGate,
    MTF_ALIGNED_BONUS_MAX, MTF_ALIGNED_BONUS_MIN,
    MTF_PULLBACK_BONUS_MAX, MTF_PULLBACK_BONUS_MIN,
    MTF_COUNTER_PENALTY, MTF_COUNTER_SIZE_MULT,
    MTF_MILD_PENALTY, MTF_MIXED_LEAN_BONUS,
)


def _gate():
    return ConfidenceGate(db=None)


def _rd(context, ratio=1.0, lanes=4, up=4, down=0, intraday_bias="NEUTRAL"):
    return {
        "state": "HOLD", "composite_score": 50,
        "multi_tf": {
            "context": context,
            "intraday_bias": intraday_bias,
            "tf_alignment": {"dominant": "UP" if up >= down else "DOWN",
                             "ratio": ratio, "lanes_counted": lanes,
                             "up": up, "down": down, "neutral": lanes - up - down},
        },
    }


def test_aligned_up_long_gets_full_conviction_bonus():
    g = _gate()
    pts, mult, reasons = g._score_regime_direction(_rd("ALIGNED_UP", ratio=1.0), "HOLD", 50, "long")
    assert pts == MTF_ALIGNED_BONUS_MAX        # 4/4 lanes, ratio 1.0
    assert mult == 1.0
    assert any("ALIGNED_UP" in r and "LONG" in r for r in reasons)


def test_aligned_up_short_is_hard_counter_trend():
    g = _gate()
    pts, mult, reasons = g._score_regime_direction(_rd("ALIGNED_UP", ratio=1.0), "HOLD", 50, "short")
    assert pts == -MTF_COUNTER_PENALTY         # effectively blocks GO
    assert mult == MTF_COUNTER_SIZE_MULT
    assert any("counter-trend" in r for r in reasons)


def test_aligned_bonus_scales_with_conviction():
    g = _gate()
    strong, _, _ = g._score_regime_direction(_rd("ALIGNED_UP", ratio=1.0), "HOLD", 50, "long")
    weak, _, _ = g._score_regime_direction(_rd("ALIGNED_UP", ratio=0.5, up=2, lanes=4), "HOLD", 50, "long")
    assert strong > weak                       # proportional to regime strength
    assert weak >= MTF_ALIGNED_BONUS_MIN


def test_aligned_down_short_confirms_long_blocked():
    g = _gate()
    s_pts, _, _ = g._score_regime_direction(_rd("ALIGNED_DOWN", ratio=1.0, up=0, down=4), "HOLD", 50, "short")
    l_pts, l_mult, _ = g._score_regime_direction(_rd("ALIGNED_DOWN", ratio=1.0, up=0, down=4), "HOLD", 50, "long")
    assert s_pts == MTF_ALIGNED_BONUS_MAX
    assert l_pts == -MTF_COUNTER_PENALTY
    assert l_mult == MTF_COUNTER_SIZE_MULT


def test_pullback_in_uptrend_long_friendly_short_mild_penalty():
    g = _gate()
    l_pts, _, l_reasons = g._score_regime_direction(_rd("PULLBACK_IN_UPTREND", ratio=1.0), "HOLD", 50, "long")
    s_pts, s_mult, _ = g._score_regime_direction(_rd("PULLBACK_IN_UPTREND", ratio=1.0), "HOLD", 50, "short")
    assert l_pts == MTF_PULLBACK_BONUS_MAX     # buy-the-dip allowed
    assert any("buy-the-dip" in r for r in l_reasons)
    assert s_pts == -MTF_MILD_PENALTY          # mild, NOT the hard -25 gate
    assert s_pts > -MTF_COUNTER_PENALTY
    assert s_mult < 1.0


def test_bounce_in_downtrend_short_friendly():
    g = _gate()
    s_pts, _, _ = g._score_regime_direction(_rd("BOUNCE_IN_DOWNTREND", ratio=0.75, up=1, down=3), "HOLD", 50, "short")
    l_pts, _, _ = g._score_regime_direction(_rd("BOUNCE_IN_DOWNTREND", ratio=0.75, up=1, down=3), "HOLD", 50, "long")
    assert s_pts >= MTF_PULLBACK_BONUS_MIN
    assert l_pts == -MTF_MILD_PENALTY


def test_mixed_only_small_lean_no_hard_gate():
    g = _gate()
    up_long, m1, _ = g._score_regime_direction(_rd("MIXED", intraday_bias="UP"), "HOLD", 50, "long")
    up_short, m2, _ = g._score_regime_direction(_rd("MIXED", intraday_bias="UP"), "HOLD", 50, "short")
    assert up_long == MTF_MIXED_LEAN_BONUS
    assert up_short == 0                        # no penalty, no hard gate in MIXED
    assert m1 == 1.0 and m2 == 1.0


def test_no_multi_tf_falls_back_to_legacy():
    g = _gate()
    # Legacy CONFIRMED_UP + long → +20 (unchanged path)
    pts, _, reasons = g._score_regime_direction({"state": "CONFIRMED_UP"}, "CONFIRMED_UP", 72, "long")
    assert pts == 20
    assert any("strongly aligned with long" in r for r in reasons)


def test_unknown_context_falls_back_to_legacy_neutral():
    g = _gate()
    rd = {"multi_tf": {"context": "UNKNOWN", "tf_alignment": {"ratio": 0.0, "lanes_counted": 0}}}
    pts, _, reasons = g._score_regime_direction(rd, "HOLD", 54, "long")
    assert pts == 0
    assert any("no directional confirmation" in r for r in reasons)


def test_cold_multi_tf_zero_lanes_falls_back():
    g = _gate()
    # context present but no lanes counted (intraday cold) → legacy
    rd = {"multi_tf": {"context": "ALIGNED_UP", "tf_alignment": {"ratio": 0.0, "lanes_counted": 0}}}
    pts, _, reasons = g._score_regime_direction(rd, "HOLD", 50, "long")
    assert pts == 0
    assert any("no directional confirmation" in r for r in reasons)
