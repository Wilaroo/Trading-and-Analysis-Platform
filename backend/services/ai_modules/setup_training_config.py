"""
Setup Training Configuration

Per-setup-type training parameters. Each setup has its own forecast horizon,
noise threshold, and class weight settings tuned to its trading characteristics.

These configs control:
  - forecast_horizon: How many DAILY bars ahead to predict (matches the setup's hold time)
  - noise_threshold: Minimum |return| to count as a real move (class boundary for 3-class)
  - scale_pos_weight: Corrects for class imbalance in UP vs DOWN labels
  - min_samples: Minimum pattern matches required to train
  - num_boost_round: LightGBM boosting iterations (more = slower but potentially better)
  - num_classes: 2 for binary UP/DOWN, 3 for UP/FLAT/DOWN
  - training_bar_sizes: List of bar sizes to train on. More bar sizes = more data.
    Forecast horizon is automatically scaled for each bar size.

BAR_SIZE_BARS_PER_DAY maps bar sizes to how many bars fit in one trading day (6.5 hours).
This is used to convert the daily forecast_horizon to bar-equivalent horizons.
"""

# How many bars fit in one trading day (6.5 market hours)
BAR_SIZE_BARS_PER_DAY = {
    "1 day": 1,
    "1 hour": 7,     # ~6.5 hours/day → 7 bars
    "30 mins": 13,    # 6.5 * 2 = 13
    "15 mins": 26,    # 6.5 * 4 = 26
    "5 mins": 78,     # 6.5 * 12 = 78
}


def get_bar_horizon(daily_horizon: int, bar_size: str) -> int:
    """Convert a daily forecast_horizon to the equivalent number of bars for a given bar_size."""
    bars_per_day = BAR_SIZE_BARS_PER_DAY.get(bar_size, 1)
    return max(1, daily_horizon * bars_per_day)


SETUP_TRAINING_CONFIGS = {
    # ------- High-frequency / Short-hold setups -------
    "SCALP": {
        "forecast_horizon": 2,       # 2 days — scalps resolve fast
        "noise_threshold": 0.002,    # 0.2% — tighter since moves are smaller
        "scale_pos_weight": 1.0,     # Neutral — scalps are roughly 50/50
        "min_samples": 50,
        "num_boost_round": 150,
        "num_classes": 3,
        "training_bar_sizes": ["1 day", "1 hour"],  # Scalps benefit from intraday data
    },
    "ORB": {
        "forecast_horizon": 3,       # 3 days
        "noise_threshold": 0.004,    # 0.4%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 120,
        "num_classes": 3,
        "training_bar_sizes": ["1 day", "1 hour"],
    },

    # ------- Medium-hold setups -------
    "BREAKOUT": {
        "forecast_horizon": 5,       # 5 days
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.1,
        "min_samples": 50,
        "num_boost_round": 150,
        "num_classes": 3,
        "training_bar_sizes": ["1 day"],
    },
    "GAP_AND_GO": {
        "forecast_horizon": 3,       # 3 days
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.1,
        "min_samples": 50,
        "num_boost_round": 120,
        "num_classes": 3,
        "training_bar_sizes": ["1 day", "1 hour"],
    },
    "RANGE": {
        "forecast_horizon": 5,       # 5 days
        "noise_threshold": 0.004,    # 0.4%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 150,
        "num_classes": 3,
        "training_bar_sizes": ["1 day"],
    },
    "VWAP": {
        "forecast_horizon": 3,       # 3 days
        "noise_threshold": 0.003,    # 0.3%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 120,
        "num_classes": 3,
        "training_bar_sizes": ["1 day", "1 hour"],
    },
    "MEAN_REVERSION": {
        "forecast_horizon": 5,       # 5 days
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 150,
        "num_classes": 3,
        "training_bar_sizes": ["1 day"],
    },

    # ------- Longer-hold / Trend setups -------
    "MOMENTUM": {
        "forecast_horizon": 7,       # 7 days
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.2,
        "min_samples": 50,
        "num_boost_round": 200,
        "num_classes": 3,
        "training_bar_sizes": ["1 day"],
    },
    "TREND_CONTINUATION": {
        "forecast_horizon": 7,       # 7 days
        "noise_threshold": 0.005,    # 0.5%
        "scale_pos_weight": 1.15,
        "min_samples": 50,
        "num_boost_round": 200,
        "num_classes": 3,
        "training_bar_sizes": ["1 day"],
    },
    "REVERSAL": {
        "forecast_horizon": 5,       # 5 days
        "noise_threshold": 0.006,    # 0.6%
        "scale_pos_weight": 1.0,
        "min_samples": 50,
        "num_boost_round": 150,
        "num_classes": 3,
        "training_bar_sizes": ["1 day"],
    },
}

# Default config for any setup type not explicitly listed
DEFAULT_TRAINING_CONFIG = {
    "forecast_horizon": 5,
    "noise_threshold": 0.005,   # 0.5%
    "scale_pos_weight": 1.0,
    "min_samples": 50,
    "num_boost_round": 150,
    "num_classes": 3,
    "training_bar_sizes": ["1 day"],
}


def get_setup_config(setup_type: str) -> dict:
    """Get training config for a setup type, with defaults as fallback."""
    return SETUP_TRAINING_CONFIGS.get(setup_type.upper(), DEFAULT_TRAINING_CONFIG.copy())
