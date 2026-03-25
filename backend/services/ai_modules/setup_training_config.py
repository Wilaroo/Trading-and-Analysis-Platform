"""
Setup Training Configuration — Profile-Based Architecture

Each setup type has one or more timeframe PROFILES. Each profile defines
a model that is independently trained and stored:

  - bar_size: The timeframe to train on (e.g., "5 mins", "1 day")
  - forecast_horizon: Bars ahead to predict (native to that bar_size)
  - noise_threshold: Minimum |return| to count as a real move
  - Other LightGBM params

A separate model is trained and stored for each (setup_type, bar_size) combo.
Model names follow: {setup_type}_{slug}_predictor  (e.g. scalp_5min_predictor)

Intraday setups use 1-min / 5-min bars with horizons measured in minutes/hours.
Swing setups use daily bars with horizons measured in days.
Some setups have both intraday AND swing profiles.
"""


def bar_size_to_slug(bar_size: str) -> str:
    """Convert bar_size like '5 mins' to a slug like '5min' for model naming."""
    return bar_size.replace(" ", "").replace("mins", "min")


def get_model_name(setup_type: str, bar_size: str) -> str:
    """Generate model name for a (setup_type, bar_size) combo."""
    slug = bar_size_to_slug(bar_size)
    return f"{setup_type.lower()}_{slug}_predictor"


SETUP_TRAINING_PROFILES = {
    # ===== Intraday-Only Setups =====
    # max_symbols/max_bars_per_symbol: Use ALL ADV-qualified data
    # Batch sizes in TIMEFRAME_SETTINGS handle memory management
    "SCALP": [
        {
            "bar_size": "1 min",
            "forecast_horizon": 30,
            "noise_threshold": 0.0008,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "max_symbols": 2500,
            "max_bars_per_symbol": 2500,
            "description": "30-min scalp on 1-min bars",
        },
        {
            "bar_size": "5 mins",
            "forecast_horizon": 12,
            "noise_threshold": 0.0015,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "max_symbols": 2500,
            "max_bars_per_symbol": 5000,
            "description": "1-hour scalp on 5-min bars",
        },
    ],
    "ORB": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 12,
            "noise_threshold": 0.002,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 120,
            "num_classes": 3,
            "max_symbols": 2500,
            "max_bars_per_symbol": 5000,
            "description": "1-hour ORB on 5-min bars",
        },
    ],
    "GAP_AND_GO": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 12,
            "noise_threshold": 0.002,
            "scale_pos_weight": 1.1,
            "min_samples": 50,
            "num_boost_round": 120,
            "num_classes": 3,
            "max_symbols": 2500,
            "max_bars_per_symbol": 5000,
            "description": "1-hour gap continuation on 5-min bars",
        },
    ],
    "VWAP": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 12,
            "noise_threshold": 0.0015,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 120,
            "num_classes": 3,
            "max_symbols": 2500,
            "max_bars_per_symbol": 5000,
            "description": "1-hour VWAP bounce/fade on 5-min bars",
        },
    ],

    # ===== Dual: Intraday + Swing =====
    "BREAKOUT": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 24,
            "noise_threshold": 0.002,
            "scale_pos_weight": 1.1,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "2-hour intraday breakout on 5-min bars",
        },
        {
            "bar_size": "1 day",
            "forecast_horizon": 5,
            "noise_threshold": 0.005,
            "scale_pos_weight": 1.1,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "5-day swing breakout on daily bars",
        },
    ],
    "RANGE": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 36,
            "noise_threshold": 0.002,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "3-hour intraday range break on 5-min bars",
        },
        {
            "bar_size": "1 day",
            "forecast_horizon": 5,
            "noise_threshold": 0.004,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "5-day swing range trade on daily bars",
        },
    ],
    "MEAN_REVERSION": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 36,
            "noise_threshold": 0.0015,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "3-hour intraday mean reversion on 5-min bars",
        },
        {
            "bar_size": "1 day",
            "forecast_horizon": 5,
            "noise_threshold": 0.005,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "5-day swing mean reversion on daily bars",
        },
    ],
    "REVERSAL": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 60,
            "noise_threshold": 0.002,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "5-hour intraday reversal on 5-min bars",
        },
        {
            "bar_size": "1 day",
            "forecast_horizon": 5,
            "noise_threshold": 0.006,
            "scale_pos_weight": 1.0,
            "min_samples": 50,
            "num_boost_round": 150,
            "num_classes": 3,
            "description": "5-day swing reversal on daily bars",
        },
    ],

    # ===== Swing / Position (with optional intraday) =====
    "TREND_CONTINUATION": [
        {
            "bar_size": "5 mins",
            "forecast_horizon": 78,
            "noise_threshold": 0.002,
            "scale_pos_weight": 1.15,
            "min_samples": 50,
            "num_boost_round": 200,
            "num_classes": 3,
            "description": "Full-day intraday trend continuation on 5-min bars",
        },
        {
            "bar_size": "1 day",
            "forecast_horizon": 7,
            "noise_threshold": 0.005,
            "scale_pos_weight": 1.15,
            "min_samples": 50,
            "num_boost_round": 200,
            "num_classes": 3,
            "description": "1-week swing trend continuation on daily bars",
        },
    ],
    "MOMENTUM": [
        {
            "bar_size": "1 hour",
            "forecast_horizon": 14,
            "noise_threshold": 0.003,
            "scale_pos_weight": 1.2,
            "min_samples": 50,
            "num_boost_round": 200,
            "num_classes": 3,
            "description": "2-day momentum on hourly bars",
        },
        {
            "bar_size": "1 day",
            "forecast_horizon": 7,
            "noise_threshold": 0.005,
            "scale_pos_weight": 1.2,
            "min_samples": 50,
            "num_boost_round": 200,
            "num_classes": 3,
            "description": "1-week momentum on daily bars",
        },
    ],
}


# Fallback for unknown setup types
DEFAULT_PROFILE = {
    "bar_size": "1 day",
    "forecast_horizon": 5,
    "noise_threshold": 0.005,
    "scale_pos_weight": 1.0,
    "min_samples": 50,
    "num_boost_round": 150,
    "num_classes": 3,
    "description": "Default 5-day prediction on daily bars",
}


def get_setup_profiles(setup_type: str) -> list:
    """Get ALL training profiles for a setup type."""
    return SETUP_TRAINING_PROFILES.get(setup_type.upper(), [DEFAULT_PROFILE.copy()])


def get_setup_profile(setup_type: str, bar_size: str) -> dict:
    """Get a specific profile for a (setup_type, bar_size) combo."""
    for p in get_setup_profiles(setup_type):
        if p["bar_size"] == bar_size:
            return p
    return DEFAULT_PROFILE.copy()


def get_all_profile_count() -> int:
    """Total number of models across all setups."""
    return sum(len(profiles) for profiles in SETUP_TRAINING_PROFILES.values())


# ===== ADV (Average Daily Volume) Thresholds for Training =====
# Symbols must meet these minimum volume requirements to be included in training.
# Thresholds are keyed by bar_size since liquidity needs scale with timeframe.
#
# User-defined tiers:
#   50K+ ADV  → investment/position
#   100K+ ADV → investment/position/swing
#   500K+ ADV → investment/position/swing/intraday/scalp

ADV_THRESHOLDS = {
    "1 min":   500_000,   # Intraday/scalp — needs highest liquidity
    "5 mins":  500_000,   # Intraday/scalp
    "15 mins": 500_000,   # Intraday
    "30 mins": 500_000,   # Intraday
    "1 hour":  500_000,   # Intraday (short swing)
    "1 day":   100_000,   # Swing
    "1 week":   50_000,   # Position/investment
}

# Default for unknown bar sizes
ADV_THRESHOLD_DEFAULT = 100_000


def get_adv_threshold(bar_size: str) -> int:
    """Get the minimum ADV threshold for a given bar_size."""
    return ADV_THRESHOLDS.get(bar_size, ADV_THRESHOLD_DEFAULT)
