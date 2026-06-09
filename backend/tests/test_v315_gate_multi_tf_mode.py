"""
v315 — Confidence-gate consumes multi-timeframe context per direction.
Verifies _update_trading_mode prefers multi_tf.modes[direction] and falls back
to the legacy daily-composite mapping when multi_tf is absent/UNKNOWN.
"""
from services.ai_modules.confidence_gate import ConfidenceGate, TradingMode


def _gate():
    return ConfidenceGate(db=None)


def _regime_with_context(context, modes):
    return {"state": "HOLD", "composite_score": 50,
            "multi_tf": {"context": context, "modes": modes,
                         "tf_alignment": {"dominant": "UP", "ratio": 0.5}}}


def test_pullback_long_is_normal_short_is_cautious():
    g = _gate()
    rd = _regime_with_context("PULLBACK_IN_UPTREND",
                              {"long": "normal", "short": "cautious"})
    g._update_trading_mode("HOLD", "unknown", 50, rd, "long")
    assert g._trading_mode == TradingMode.NORMAL
    g._update_trading_mode("HOLD", "unknown", 50, rd, "short")
    assert g._trading_mode == TradingMode.CAUTIOUS


def test_aligned_down_short_aggressive_long_defensive():
    g = _gate()
    rd = _regime_with_context("ALIGNED_DOWN",
                              {"long": "defensive", "short": "aggressive"})
    g._update_trading_mode("HOLD", "unknown", 50, rd, "short")
    assert g._trading_mode == TradingMode.AGGRESSIVE
    g._update_trading_mode("HOLD", "unknown", 50, rd, "long")
    assert g._trading_mode == TradingMode.DEFENSIVE


def test_no_multi_tf_falls_back_to_legacy_neutral_cautious():
    g = _gate()
    # No multi_tf → neutral daily score 48 → legacy CAUTIOUS
    g._update_trading_mode("HOLD", "unknown", 48, {"state": "HOLD"}, "long")
    assert g._trading_mode == TradingMode.CAUTIOUS


def test_unknown_context_falls_back_to_legacy():
    g = _gate()
    rd = {"multi_tf": {"context": "UNKNOWN", "modes": {}}}
    # Legacy: CONFIRMED_UP score 72 → AGGRESSIVE
    g._update_trading_mode("CONFIRMED_UP", "unknown", 72, rd, "long")
    assert g._trading_mode == TradingMode.AGGRESSIVE
