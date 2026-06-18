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
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# v379 — grade-rank ladder for the borderline-band quality gate. Covers both
# the percentile-calibrated grades (A/B/C/D/F from
# grade_calibration.calibrate_grade) and the legacy static "+" grades, so the
# comparison is robust to whichever path calibrate_grade returns.
_GRADE_RANK = {"A+": 7, "A": 6, "B+": 5, "B": 4, "C+": 3, "C": 2, "D": 1, "F": 0}

DEFAULT_CONFIG = {
    "enabled": True,
    "min_sample_size": 5,
    "skip_win_rate_threshold": 0.35,
    "reduce_size_threshold": 0.45,
    "require_higher_tqs_threshold": 0.50,
    "normal_threshold": 0.55,
    "size_reduction_pct": 0.5,
    # v379 — borderline-band setups (0.45<=win_rate<normal) now fire when the
    # alert's CALIBRATED TQS GRADE clears this floor (default "B"), instead of
    # comparing the raw composite TQS to an absolute 75 it can never reach (the
    # composite is a 5-pillar average capped ~68; see grade_calibration.py).
    # Env-tunable + reversible. `high_tqs_requirement` is kept ONLY as a
    # crash / no-reference fallback inside the borderline branch.
    "borderline_min_grade": os.environ.get("SMART_FILTER_BORDERLINE_MIN_GRADE", "B"),
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
        # v379 — judge THIS instance's quality by the CALIBRATED GRADE
        # (consistent with the grade system), not the raw composite TQS. The
        # composite is a 5-pillar average crushed into ~48-68
        # (grade_calibration.py), so the legacy absolute
        # `quality_score < high_tqs_requirement (75)` test was unreachable and
        # hard-blocked EVERY borderline setup. PROCEED when the calibrated grade
        # clears `borderline_min_grade` (default "B"). Falls back to the
        # absolute high_tqs_requirement only if calibration is unavailable.
        if win_rate < config["normal_threshold"]:
            min_grade = config.get("borderline_min_grade", "B")
            grade = None
            try:
                from services.tqs.grade_calibration import calibrate_grade
                grade = calibrate_grade(quality_score)
                quality_ok = _GRADE_RANK.get(grade, -1) >= _GRADE_RANK.get(min_grade, 4)
                gate_desc = f"grade {grade} vs {min_grade} floor"
            except Exception as _grade_err:
                logger.warning(
                    "[smart_filter] calibrate_grade failed (%s) — absolute TQS fallback",
                    _grade_err,
                )
                quality_ok = quality_score >= config["high_tqs_requirement"]
                gate_desc = f"TQS {quality_score} vs {config['high_tqs_requirement']} floor"
            if not quality_ok:
                return {
                    "action": "SKIP",
                    "reasoning": (
                        f"Passing on {symbol} {setup_type} - "
                        f"we're {win_rate:.0%} on this setup and its quality "
                        f"({gate_desc}) is below the bar for borderline setups"
                    ),
                    "adjustment_pct": 0,
                    "stats": stats,
                    "win_rate": win_rate,
                    "tqs_grade": grade,
                    "min_grade": min_grade,
                }
            else:
                return {
                    "action": "PROCEED",
                    "reasoning": (
                        f"Taking {symbol} {setup_type} - "
                        f"borderline win rate ({win_rate:.0%}) but quality is strong "
                        f"({gate_desc})"
                    ),
                    "adjustment_pct": 1.0,
                    "stats": stats,
                    "win_rate": win_rate,
                    "tqs_grade": grade,
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
