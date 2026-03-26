"""
Smart Strategy Filter
=====================
Extracted from trading_bot_service.py for modularity.

Evaluates trades based on user's historical performance data:
- Win rate thresholds
- Cold-start bootstrap mode (0W/0L)
- Quality score gating for borderline setups
- Configurable thresholds

Used by TradingBotService._evaluate_strategy_filter()
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "enabled": True,
    "min_sample_size": 5,
    "skip_win_rate_threshold": 0.35,
    "reduce_size_threshold": 0.45,
    "require_higher_tqs_threshold": 0.50,
    "normal_threshold": 0.55,
    "size_reduction_pct": 0.5,
    "high_tqs_requirement": 75,
}


class SmartFilter:
    """
    Smart Strategy Filter — evaluates whether a trade should be taken
    based on historical performance data for the setup type.
    """

    def __init__(self, config: Dict = None):
        self._config = {**DEFAULT_CONFIG, **(config or {})}
        self._thoughts: List[Dict] = []
        self._max_thoughts = 100

    @property
    def config(self) -> Dict:
        return self._config.copy()

    def update_config(self, updates: Dict) -> Dict:
        for key, value in updates.items():
            if key in self._config:
                self._config[key] = value
                logger.info(f"Smart filter config updated: {key} = {value}")
        return self._config.copy()

    def evaluate(self, setup_type: str, quality_score: int, symbol: str, stats: Dict) -> Dict[str, Any]:
        """
        Core evaluation logic.

        Args:
            setup_type: The setup/strategy type (e.g. "breakout", "squeeze")
            quality_score: Trade quality score (0-100)
            symbol: Ticker symbol
            stats: Historical stats dict from get_strategy_historical_stats()

        Returns:
            dict with: action (PROCEED/REDUCE_SIZE/SKIP), reasoning, adjustment_pct, stats, win_rate
        """
        config = self._config

        if not config.get("enabled", True):
            return {"action": "PROCEED", "reasoning": "Smart filtering disabled"}

        if not stats.get("available"):
            return {
                "action": "PROCEED",
                "reasoning": f"No historical data for {setup_type} - proceeding with default sizing",
                "adjustment_pct": 1.0,
                "stats": stats,
            }

        sample_size = stats.get("sample_size", 0)
        win_rate = stats.get("win_rate", 0)
        expected_value = stats.get("expected_value", 0)

        # Not enough data to filter
        if sample_size < config["min_sample_size"]:
            return {
                "action": "PROCEED",
                "reasoning": f"Only {sample_size} trades on record for {setup_type} - need {config['min_sample_size']}+ to filter",
                "adjustment_pct": 1.0,
                "stats": stats,
            }

        # === COLD-START BOOTSTRAP MODE ===
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        completed_trades = wins + losses

        if completed_trades == 0:
            return {
                "action": "REDUCE_SIZE",
                "reasoning": (
                    f"Bootstrap mode for {symbol} {setup_type} - "
                    f"{sample_size} alerts detected but 0 completed trades. "
                    f"Taking with {config['size_reduction_pct']*100:.0f}% size to build history."
                ),
                "adjustment_pct": config["size_reduction_pct"],
                "stats": stats,
                "win_rate": 0,
                "bootstrap": True,
            }

        # === DECISION TREE ===

        # SKIP: Very low win rate
        if win_rate < config["skip_win_rate_threshold"]:
            reasoning = (
                f"Passing on {symbol} {setup_type} - "
                f"we're only {win_rate:.0%} historically ({wins}W/{losses}L on {sample_size} trades)"
            )
            if expected_value < 0:
                reasoning += f". Negative EV ({expected_value:.2f}R)"
            return {
                "action": "SKIP",
                "reasoning": reasoning,
                "adjustment_pct": 0,
                "stats": stats,
                "win_rate": win_rate,
            }

        # REDUCE_SIZE: Low win rate
        if win_rate < config["reduce_size_threshold"]:
            return {
                "action": "REDUCE_SIZE",
                "reasoning": (
                    f"Taking {symbol} {setup_type} with reduced size - "
                    f"we're {win_rate:.0%} historically ({sample_size} trades). "
                    f"Using {config['size_reduction_pct']*100:.0f}% position."
                ),
                "adjustment_pct": config["size_reduction_pct"],
                "stats": stats,
                "win_rate": win_rate,
            }

        # REQUIRE_HIGHER_TQS: Borderline
        if win_rate < config["normal_threshold"]:
            if quality_score < config["high_tqs_requirement"]:
                return {
                    "action": "SKIP",
                    "reasoning": (
                        f"Passing on {symbol} {setup_type} - "
                        f"we're {win_rate:.0%} on this setup and TQS ({quality_score}) "
                        f"doesn't meet threshold ({config['high_tqs_requirement']})"
                    ),
                    "adjustment_pct": 0,
                    "stats": stats,
                    "win_rate": win_rate,
                    "tqs_required": config["high_tqs_requirement"],
                }
            else:
                return {
                    "action": "PROCEED",
                    "reasoning": (
                        f"Taking {symbol} {setup_type} - "
                        f"borderline win rate ({win_rate:.0%}) but TQS is strong ({quality_score})"
                    ),
                    "adjustment_pct": 1.0,
                    "stats": stats,
                    "win_rate": win_rate,
                }

        # PROCEED: Good win rate
        reasoning = f"Taking {symbol} {setup_type} - we're {win_rate:.0%} historically ({wins}W/{losses}L)"
        if expected_value > 0.2:
            reasoning += f". Positive EV (+{expected_value:.2f}R)"
        return {
            "action": "PROCEED",
            "reasoning": reasoning,
            "adjustment_pct": 1.0,
            "stats": stats,
            "win_rate": win_rate,
        }

    def add_thought(self, thought: Dict):
        """Add a filter thought to the log."""
        thought["timestamp"] = datetime.now(timezone.utc).isoformat()
        thought["type"] = "strategy_filter"
        self._thoughts.insert(0, thought)
        if len(self._thoughts) > self._max_thoughts:
            self._thoughts = self._thoughts[:self._max_thoughts]
        logger.info(f"Strategy Filter: {thought.get('reasoning', '')[:100]}")

    def get_thoughts(self, limit: int = 10) -> List[Dict]:
        return self._thoughts[:limit]
