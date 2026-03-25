"""
Setup Training Configuration

Per-setup-type training parameters. Each setup has its own forecast horizon,
noise threshold, and class weight settings tuned to its trading characteristics.

These configs control:
  - forecast_horizon: How many bars ahead to predict (matches the setup's hold time)
  - noise_threshold: Minimum |return| to count as a real move (filters out noise)
  - scale_pos_weight: Corrects for class imbalance in UP vs DOWN labels
  - min_samples: Minimum pattern matches required to train
  - num_boost_round: LightGBM boosting iterations (more = slower but potentially better)
"""


SETUP_TRAINING_CONFIGS = {
    # ------- High-frequency / Short-hold setups -------
    "SCALP": {
        "forecast_horizon": 2,       # 2 bars — scalps resolve fast
        "noise_threshold": 0.002,    # 0.2% — tighter since moves are smaller
        "scale_pos_weight": 1.0,     # Neutral — scalps are roughly 50/50
        "min_samples": 50,
        "num_boost_round": 150,
    },
    "ORB": {
        "forecast_horizon": 3,       # 3 bars — opening range plays resolve in 1-3 days
        "noise_threshold": 0.004,    # 0.4%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 120,
    },

    # ------- Medium-hold setups -------
    "BREAKOUT": {
        "forecast_horizon": 5,       # 5 bars — breakouts need time to follow through
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.1,     # Slight upward bias — breakouts tend to continue
        "min_samples": 50,
        "num_boost_round": 150,
    },
    "GAP_AND_GO": {
        "forecast_horizon": 3,       # 3 bars — gap fills or extends within days
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.1,
        "min_samples": 50,
        "num_boost_round": 120,
    },
    "RANGE": {
        "forecast_horizon": 5,       # 5 bars — mean reversion within range
        "noise_threshold": 0.004,    # 0.4% — ranges have smaller moves
        "scale_pos_weight": 1.0,     # Neutral — up and down are equal in ranges
        "min_samples": 50,
        "num_boost_round": 150,
    },
    "VWAP": {
        "forecast_horizon": 3,       # 3 bars — VWAP bounces are short-term
        "noise_threshold": 0.003,    # 0.3%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 120,
    },
    "MEAN_REVERSION": {
        "forecast_horizon": 5,       # 5 bars — reversion takes time
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.0,     # Neutral — reversion is symmetric
        "min_samples": 50,
        "num_boost_round": 150,
    },

    # ------- Longer-hold / Trend setups -------
    "MOMENTUM": {
        "forecast_horizon": 7,       # 7 bars — momentum persists over a week+
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.2,     # Upward bias — momentum is directional
        "min_samples": 50,
        "num_boost_round": 200,
    },
    "TREND_CONTINUATION": {
        "forecast_horizon": 7,       # 7 bars — continuation after pullback
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.15,
        "min_samples": 50,
        "num_boost_round": 200,
    },
    "REVERSAL": {
        "forecast_horizon": 5,       # 5 bars — reversals resolve in ~1 week
        "noise_threshold": 0.006,    # 0.6% — reversals should be decisive
        "scale_pos_weight": 1.0,     # Neutral — could go either way
        "min_samples": 50,
        "num_boost_round": 150,
    },
}

# Default config for any setup type not explicitly listed
DEFAULT_TRAINING_CONFIG = {
    "forecast_horizon": 5,
    "noise_threshold": 0.005,   # 0.5%
    "scale_pos_weight": 1.0,
    "min_samples": 50,
    "num_boost_round": 150,
}


def get_setup_config(setup_type: str) -> dict:
    """Get training config for a setup type, with defaults as fallback."""
    return SETUP_TRAINING_CONFIGS.get(setup_type.upper(), DEFAULT_TRAINING_CONFIG.copy())
