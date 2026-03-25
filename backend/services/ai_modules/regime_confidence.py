"""
Regime-Aware Prediction Confidence Adjustment (Layer 2)

After the model produces a raw prediction, this module adjusts confidence
based on whether the current market regime aligns with the setup's preferred
conditions.

Maps AI setup types → preferred market regimes, then boosts/dampens confidence.
"""

import logging
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


# Map AI setup types to preferred MarketRegimeEngine states.
# MarketRegimeEngine outputs: "confirmed_up", "confirmed_down", "hold"
# Scanner MarketRegime: "strong_uptrend", "range_bound", "volatile", "momentum", "fade", "strong_downtrend"
#
# We map to BOTH systems so the adjustment works regardless of data source.

SETUP_REGIME_PREFERENCES: Dict[str, Dict[str, Set[str]]] = {
    "SCALP": {
        "engine_states": {"confirmed_up", "confirmed_down"},  # Needs directional movement
        "scanner_regimes": {"strong_uptrend", "strong_downtrend", "momentum"},
    },
    "ORB": {
        "engine_states": {"confirmed_up", "confirmed_down"},
        "scanner_regimes": {"strong_uptrend", "strong_downtrend", "momentum"},
    },
    "GAP_AND_GO": {
        "engine_states": {"confirmed_up"},
        "scanner_regimes": {"strong_uptrend", "momentum"},
    },
    "VWAP": {
        "engine_states": {"confirmed_up", "hold"},  # Works in range + uptrend
        "scanner_regimes": {"range_bound", "strong_uptrend", "fade"},
    },
    "BREAKOUT": {
        "engine_states": {"confirmed_up"},
        "scanner_regimes": {"strong_uptrend", "momentum"},
    },
    "RANGE": {
        "engine_states": {"hold"},  # Range-bound market
        "scanner_regimes": {"range_bound"},
    },
    "MEAN_REVERSION": {
        "engine_states": {"hold"},
        "scanner_regimes": {"range_bound", "fade", "volatile"},
    },
    "REVERSAL": {
        "engine_states": {"confirmed_down", "hold"},  # Contrarian
        "scanner_regimes": {"volatile", "strong_downtrend", "fade"},
    },
    "TREND_CONTINUATION": {
        "engine_states": {"confirmed_up", "confirmed_down"},
        "scanner_regimes": {"strong_uptrend", "strong_downtrend", "momentum"},
    },
    "MOMENTUM": {
        "engine_states": {"confirmed_up"},
        "scanner_regimes": {"strong_uptrend", "momentum"},
    },
}

# Confidence multipliers
REGIME_BOOST = 1.15       # +15% when regime is favorable
REGIME_DAMPEN = 0.80      # -20% when regime is unfavorable
REGIME_NEUTRAL = 1.0      # No adjustment when no preference data


def adjust_confidence_for_regime(
    setup_type: str,
    raw_confidence: float,
    engine_state: Optional[str] = None,
    scanner_regime: Optional[str] = None,
) -> Dict:
    """
    Adjust prediction confidence based on market regime alignment.

    Args:
        setup_type: AI setup type (e.g., "SCALP", "BREAKOUT")
        raw_confidence: Raw model confidence [0, 1]
        engine_state: Current MarketRegimeEngine state ("confirmed_up"/"hold"/"confirmed_down")
        scanner_regime: Current scanner MarketRegime value ("strong_uptrend", etc.)

    Returns:
        Dict with adjusted_confidence, multiplier, regime_aligned, and reasoning.
    """
    setup_type = setup_type.upper()
    prefs = SETUP_REGIME_PREFERENCES.get(setup_type)

    if not prefs:
        return {
            "adjusted_confidence": raw_confidence,
            "multiplier": REGIME_NEUTRAL,
            "regime_aligned": None,
            "reasoning": f"No regime preferences for {setup_type}",
        }

    # Check alignment with either source
    aligned = False
    misaligned = False

    if engine_state:
        if engine_state in prefs["engine_states"]:
            aligned = True
        else:
            misaligned = True

    if scanner_regime:
        if scanner_regime in prefs["scanner_regimes"]:
            aligned = True
            misaligned = False  # Scanner override — more granular
        elif not aligned:
            misaligned = True

    if aligned:
        multiplier = REGIME_BOOST
        reasoning = (
            f"{setup_type} aligned with regime "
            f"({engine_state or scanner_regime}). Confidence boosted."
        )
    elif misaligned:
        multiplier = REGIME_DAMPEN
        reasoning = (
            f"{setup_type} misaligned with regime "
            f"({engine_state or scanner_regime}). Confidence dampened."
        )
    else:
        multiplier = REGIME_NEUTRAL
        reasoning = "No regime data available for adjustment."

    adjusted = min(1.0, max(0.0, raw_confidence * multiplier))

    return {
        "adjusted_confidence": round(adjusted, 4),
        "multiplier": multiplier,
        "regime_aligned": aligned if (aligned or misaligned) else None,
        "reasoning": reasoning,
    }
