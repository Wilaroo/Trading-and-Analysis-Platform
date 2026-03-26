"""
Multi-Timeframe Ensemble (Meta-Learner)

Stacks outputs from multiple timeframe models (daily, hourly, 5-min) as
input features for a final decision model. This captures "all timeframes
agree" signals which are historically the highest-probability setups.

Architecture:
  Layer 1: Individual timeframe models predict independently
    - daily_model  -> {prob_up, prob_down, confidence, direction}
    - hourly_model -> {prob_up, prob_down, confidence, direction}
    - 5min_model   -> {prob_up, prob_down, confidence, direction}

  Layer 2: Meta-learner combines these predictions
    Input features (per sub-model):
      - prob_up, prob_down, confidence
    Plus derived meta-features:
      - agreement_count   — How many models agree on direction
      - avg_confidence     — Average confidence across models
      - confidence_spread  — Max confidence - min confidence (divergence signal)
      - direction_entropy  — How much models disagree (0=perfect agreement)
      - bull_vote_pct     — % of models voting UP

    Output: Final UP/DOWN/FLAT with calibrated probability

Why? Individual models are noisy. When daily says UP, hourly says UP,
and 5-min says UP, the win rate is dramatically higher than any single
model alone.
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Sub-model timeframes to stack (in order of decreasing timeframe)
STACKED_TIMEFRAMES = ["1 day", "1 hour", "5 mins"]

# Per-sub-model features extracted from their predictions
_PER_MODEL_FEATURES = ["prob_up", "prob_down", "confidence"]

# Derived meta-features
_META_FEATURES = [
    "agreement_count",
    "avg_confidence",
    "confidence_spread",
    "direction_entropy",
    "bull_vote_pct",
]

# Build the full feature name list
ENSEMBLE_FEATURE_NAMES = []
for tf in STACKED_TIMEFRAMES:
    prefix = tf.replace(" ", "_")
    for feat in _PER_MODEL_FEATURES:
        ENSEMBLE_FEATURE_NAMES.append(f"stack_{prefix}_{feat}")
ENSEMBLE_FEATURE_NAMES.extend(_META_FEATURES)


def extract_ensemble_features(
    predictions: Dict[str, Dict[str, Any]],
) -> Dict[str, float]:
    """
    Extract meta-learner features from sub-model predictions.

    Args:
        predictions: Dict of timeframe -> prediction dict
            Each prediction dict has: prob_up, prob_down, confidence, direction

    Returns:
        Dict of ensemble feature name -> value
    """
    feats = {}

    confidences = []
    directions = []
    bull_count = 0

    for tf in STACKED_TIMEFRAMES:
        prefix = tf.replace(" ", "_")
        pred = predictions.get(tf, {})

        prob_up = float(pred.get("prob_up", 0.5))
        prob_down = float(pred.get("prob_down", 0.5))
        confidence = float(pred.get("confidence", 0.0))
        direction = pred.get("direction", "flat")

        feats[f"stack_{prefix}_prob_up"] = prob_up
        feats[f"stack_{prefix}_prob_down"] = prob_down
        feats[f"stack_{prefix}_confidence"] = confidence

        confidences.append(confidence)
        directions.append(direction)
        if direction == "up":
            bull_count += 1

    # Meta-features
    # Agreement: how many models agree on the most common direction
    if directions:
        from collections import Counter
        dir_counts = Counter(directions)
        most_common = dir_counts.most_common(1)[0][1]
        feats["agreement_count"] = most_common / len(STACKED_TIMEFRAMES)
    else:
        feats["agreement_count"] = 0.0

    feats["avg_confidence"] = np.mean(confidences) if confidences else 0.0
    feats["confidence_spread"] = (
        max(confidences) - min(confidences) if len(confidences) >= 2 else 0.0
    )

    # Direction entropy (Shannon entropy of direction distribution)
    if directions:
        from collections import Counter
        probs = [c / len(directions) for c in Counter(directions).values()]
        entropy = -sum(p * np.log2(p) for p in probs if p > 0)
        max_entropy = np.log2(3)  # max with 3 possible directions
        feats["direction_entropy"] = entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        feats["direction_entropy"] = 1.0

    feats["bull_vote_pct"] = bull_count / len(STACKED_TIMEFRAMES)

    return feats


# Ensemble model configs
ENSEMBLE_MODEL_CONFIGS = {
    # One per setup type — routes to the appropriate sub-models
    "SCALP":              {"model_name": "ensemble_scalp", "sub_timeframes": ["5 mins", "1 min"]},
    "ORB":                {"model_name": "ensemble_orb", "sub_timeframes": ["1 day", "5 mins"]},
    "GAP_AND_GO":         {"model_name": "ensemble_gap", "sub_timeframes": ["1 day", "5 mins"]},
    "BREAKOUT":           {"model_name": "ensemble_breakout", "sub_timeframes": ["1 day", "1 hour", "5 mins"]},
    "MEAN_REVERSION":     {"model_name": "ensemble_meanrev", "sub_timeframes": ["1 day", "1 hour", "5 mins"]},
    "MOMENTUM":           {"model_name": "ensemble_momentum", "sub_timeframes": ["1 day", "1 hour"]},
    "TREND_CONTINUATION": {"model_name": "ensemble_trend", "sub_timeframes": ["1 day", "1 hour", "5 mins"]},
    "REVERSAL":           {"model_name": "ensemble_reversal", "sub_timeframes": ["1 day", "1 hour", "5 mins"]},
    "RANGE":              {"model_name": "ensemble_range", "sub_timeframes": ["1 day", "1 hour", "5 mins"]},
    "VWAP":               {"model_name": "ensemble_vwap", "sub_timeframes": ["1 day", "5 mins"]},
}
