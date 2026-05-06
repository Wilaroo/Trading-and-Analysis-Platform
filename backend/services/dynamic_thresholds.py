"""
Dynamic Threshold Service - Adaptive Thresholds Based on Context

Implements context-aware threshold adjustments:
- Win-rate thresholds by market regime
- Tape score requirements by time of day
- Minimum TQS scores by volatility
- Setup-specific gating based on historical performance

Thresholds adapt based on:
1. Current market regime (trending vs choppy)
2. Time of day (morning vs midday vs close)
3. VIX level (low vs high volatility)
4. Your historical performance in similar conditions
5. Recent streak (hot hand vs cold streak)
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ThresholdType(str, Enum):
    """Types of dynamic thresholds"""
    MIN_TQS_SCORE = "min_tqs_score"
    MIN_WIN_RATE = "min_win_rate"
    MIN_TAPE_SCORE = "min_tape_score"
    MIN_EXPECTED_VALUE = "min_expected_value"
    MAX_CONSECUTIVE_TRADES = "max_consecutive_trades"
    MIN_SAMPLE_SIZE = "min_sample_size"


@dataclass
class ThresholdContext:
    """Context for threshold calculation"""
    market_regime: str = "unknown"
    time_of_day: str = "midday"
    vix_level: float = 18.0
    setup_type: str = "unknown"
    recent_win_rate: float = 0.5
    consecutive_losses: int = 0
    trades_today: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "market_regime": self.market_regime,
            "time_of_day": self.time_of_day,
            "vix_level": round(self.vix_level, 1),
            "setup_type": self.setup_type,
            "recent_win_rate": round(self.recent_win_rate, 3),
            "consecutive_losses": self.consecutive_losses,
            "trades_today": self.trades_today
        }


@dataclass
class DynamicThreshold:
    """A single dynamic threshold with its adjustments"""
    type: ThresholdType
    base_value: float
    current_value: float
    adjustments: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "base_value": round(self.base_value, 2),
            "current_value": round(self.current_value, 2),
            "adjustments": self.adjustments
        }


@dataclass
class ThresholdCheckResult:
    """Result of checking a trade against thresholds"""
    passes: bool = True
    thresholds_checked: List[DynamicThreshold] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    context_used: ThresholdContext = None
    
    def to_dict(self) -> Dict:
        return {
            "passes": self.passes,
            "thresholds_checked": [t.to_dict() for t in self.thresholds_checked],
            "failures": self.failures,
            "warnings": self.warnings,
            "context_used": self.context_used.to_dict() if self.context_used else None
        }


class DynamicThresholdService:
    """
    Calculates context-aware thresholds for trade gating.
    
    Base thresholds (adjusted by context):
    - Min TQS Score: 50 (range: 35-70 based on conditions)
    - Min Win Rate: 45% (range: 35%-55% based on sample size)
    - Min Tape Score: 4 (range: 2-7 based on time of day)
    - Min EV: 0.1R (range: 0-0.3R based on setup quality)
    """
    
    # Base thresholds
    BASE_THRESHOLDS = {
        ThresholdType.MIN_TQS_SCORE: 50.0,
        ThresholdType.MIN_WIN_RATE: 0.45,
        ThresholdType.MIN_TAPE_SCORE: 4.0,
        ThresholdType.MIN_EXPECTED_VALUE: 0.1,
        ThresholdType.MAX_CONSECUTIVE_TRADES: 5,
        ThresholdType.MIN_SAMPLE_SIZE: 10
    }
    
    # Regime adjustments for TQS threshold
    REGIME_TQS_ADJUSTMENTS = {
        "strong_uptrend": -5,    # Lower threshold in strong trends
        "weak_uptrend": -2,
        "range_bound": +5,       # Higher threshold in choppy markets
        "weak_downtrend": +2,
        "strong_downtrend": +5,  # Higher threshold, trend against most setups
        "volatile": +8,          # Much higher in volatile markets
        "unknown": 0
    }
    
    # Time-of-day adjustments for tape score
    TIME_TAPE_ADJUSTMENTS = {
        "pre_market": +2,        # Require stronger tape in pre-market
        "opening_auction": +1,
        "opening_drive": -1,     # Lower threshold during opening drive
        "morning_momentum": 0,
        "late_morning": +1,
        "midday": +2,            # Require stronger tape during midday
        "afternoon": 0,
        "close": +1,
        "after_hours": +3
    }
    
    # VIX-based TQS adjustments
    VIX_TQS_ADJUSTMENTS = {
        (0, 12): +5,      # Very low VIX - be more selective
        (12, 15): 0,
        (15, 20): -3,     # Sweet spot
        (20, 25): 0,
        (25, 30): +5,
        (30, 40): +10,    # High VIX - much more selective
        (40, 100): +15    # Extreme VIX - very selective
    }
    
    def __init__(self):
        self._learning_loop = None
        self._custom_thresholds: Dict[str, float] = {}
        
    def set_services(self, learning_loop=None):
        """Wire up dependencies"""
        self._learning_loop = learning_loop
        
    def set_custom_threshold(self, threshold_type: ThresholdType, value: float):
        """Override a base threshold"""
        self._custom_thresholds[threshold_type.value] = value
        logger.info(f"Custom threshold set: {threshold_type.value} = {value}")
        
    def get_base_threshold(self, threshold_type: ThresholdType) -> float:
        """Get base threshold (custom or default)"""
        return self._custom_thresholds.get(
            threshold_type.value,
            self.BASE_THRESHOLDS.get(threshold_type, 50.0)
        )
        
    async def calculate_thresholds(
        self,
        context: ThresholdContext
    ) -> Dict[str, DynamicThreshold]:
        """
        Calculate all thresholds for a given context.
        
        Returns dict of threshold type -> DynamicThreshold
        """
        thresholds = {}
        
        # 1. TQS Score threshold
        tqs_threshold = self._calculate_tqs_threshold(context)
        thresholds[ThresholdType.MIN_TQS_SCORE.value] = tqs_threshold
        
        # 2. Win Rate threshold
        wr_threshold = await self._calculate_win_rate_threshold(context)
        thresholds[ThresholdType.MIN_WIN_RATE.value] = wr_threshold
        
        # 3. Tape Score threshold
        tape_threshold = self._calculate_tape_threshold(context)
        thresholds[ThresholdType.MIN_TAPE_SCORE.value] = tape_threshold
        
        # 4. Expected Value threshold
        ev_threshold = self._calculate_ev_threshold(context)
        thresholds[ThresholdType.MIN_EXPECTED_VALUE.value] = ev_threshold
        
        return thresholds
        
    def _calculate_tqs_threshold(self, context: ThresholdContext) -> DynamicThreshold:
        """Calculate dynamic TQS score threshold"""
        base = self.get_base_threshold(ThresholdType.MIN_TQS_SCORE)
        current = base
        adjustments = []
        
        # 1. Market regime adjustment
        regime_adj = self.REGIME_TQS_ADJUSTMENTS.get(context.market_regime, 0)
        if regime_adj != 0:
            current += regime_adj
            adjustments.append({
                "reason": f"Market regime ({context.market_regime})",
                "adjustment": regime_adj
            })
            
        # 2. VIX adjustment
        for (low, high), adj in self.VIX_TQS_ADJUSTMENTS.items():
            if low <= context.vix_level < high:
                if adj != 0:
                    current += adj
                    adjustments.append({
                        "reason": f"VIX level ({context.vix_level:.1f})",
                        "adjustment": adj
                    })
                break
                
        # 3. Consecutive losses adjustment (tilt protection)
        if context.consecutive_losses >= 2:
            tilt_adj = context.consecutive_losses * 3
            current += tilt_adj
            adjustments.append({
                "reason": f"Consecutive losses ({context.consecutive_losses})",
                "adjustment": tilt_adj
            })
            
        # 4. Recent performance adjustment
        if context.recent_win_rate < 0.4:
            perf_adj = 5
            current += perf_adj
            adjustments.append({
                "reason": f"Cold streak ({context.recent_win_rate*100:.0f}% win rate)",
                "adjustment": perf_adj
            })
        elif context.recent_win_rate > 0.65:
            perf_adj = -3
            current += perf_adj
            adjustments.append({
                "reason": f"Hot streak ({context.recent_win_rate*100:.0f}% win rate)",
                "adjustment": perf_adj
            })
            
        # Clamp to reasonable range
        current = max(35, min(80, current))
        
        return DynamicThreshold(
            type=ThresholdType.MIN_TQS_SCORE,
            base_value=base,
            current_value=current,
            adjustments=adjustments
        )
        
    async def _calculate_win_rate_threshold(self, context: ThresholdContext) -> DynamicThreshold:
        """Calculate dynamic win rate threshold"""
        base = self.get_base_threshold(ThresholdType.MIN_WIN_RATE)
        current = base
        adjustments = []
        
        # Get historical data for this setup if available
        sample_size = 0
        if self._learning_loop:
            try:
                stats = await self._learning_loop.get_contextual_win_rate(
                    setup_type=context.setup_type,
                    market_regime=context.market_regime
                )
                sample_size = stats.get("sample_size", 0)
            except Exception:
                pass
                
        # 1. Sample size adjustment
        # Require higher win rate with smaller sample (less confidence)
        if sample_size < 10:
            size_adj = 0.05
            current += size_adj
            adjustments.append({
                "reason": f"Small sample size ({sample_size} trades)",
                "adjustment": f"+{size_adj*100:.0f}%"
            })
        elif sample_size >= 50:
            size_adj = -0.03
            current += size_adj
            adjustments.append({
                "reason": f"Large sample size ({sample_size} trades)",
                "adjustment": f"{size_adj*100:.0f}%"
            })
            
        # 2. Market regime adjustment
        if context.market_regime in ["range_bound", "volatile"]:
            regime_adj = 0.05
            current += regime_adj
            adjustments.append({
                "reason": f"Choppy market ({context.market_regime})",
                "adjustment": f"+{regime_adj*100:.0f}%"
            })
            
        # 3. Time of day adjustment
        if context.time_of_day == "midday":
            time_adj = 0.05
            current += time_adj
            adjustments.append({
                "reason": "Midday (reduced edge)",
                "adjustment": f"+{time_adj*100:.0f}%"
            })
            
        # Clamp to reasonable range
        current = max(0.35, min(0.60, current))
        
        return DynamicThreshold(
            type=ThresholdType.MIN_WIN_RATE,
            base_value=base,
            current_value=current,
            adjustments=adjustments
        )
        
    def _calculate_tape_threshold(self, context: ThresholdContext) -> DynamicThreshold:
        """Calculate dynamic tape score threshold"""
        base = self.get_base_threshold(ThresholdType.MIN_TAPE_SCORE)
        current = base
        adjustments = []
        
        # 1. Time of day adjustment
        time_adj = self.TIME_TAPE_ADJUSTMENTS.get(context.time_of_day, 0)
        if time_adj != 0:
            current += time_adj
            adjustments.append({
                "reason": f"Time of day ({context.time_of_day})",
                "adjustment": time_adj
            })
            
        # 2. Market regime adjustment
        if context.market_regime in ["range_bound", "volatile"]:
            regime_adj = 1
            current += regime_adj
            adjustments.append({
                "reason": f"Choppy market ({context.market_regime})",
                "adjustment": regime_adj
            })
        elif context.market_regime in ["strong_uptrend", "strong_downtrend"]:
            regime_adj = -1
            current += regime_adj
            adjustments.append({
                "reason": f"Strong trend ({context.market_regime})",
                "adjustment": regime_adj
            })
            
        # Clamp to reasonable range
        current = max(2, min(8, current))
        
        return DynamicThreshold(
            type=ThresholdType.MIN_TAPE_SCORE,
            base_value=base,
            current_value=current,
            adjustments=adjustments
        )
        
    def _calculate_ev_threshold(self, context: ThresholdContext) -> DynamicThreshold:
        """Calculate dynamic expected value threshold"""
        base = self.get_base_threshold(ThresholdType.MIN_EXPECTED_VALUE)
        current = base
        adjustments = []
        
        # 1. Consecutive losses adjustment
        if context.consecutive_losses >= 2:
            loss_adj = context.consecutive_losses * 0.05
            current += loss_adj
            adjustments.append({
                "reason": f"Consecutive losses ({context.consecutive_losses})",
                "adjustment": f"+{loss_adj:.2f}R"
            })
            
        # 2. Market regime adjustment
        if context.market_regime == "volatile":
            vol_adj = 0.1
            current += vol_adj
            adjustments.append({
                "reason": "Volatile market",
                "adjustment": f"+{vol_adj:.2f}R"
            })
            
        # Clamp to reasonable range
        current = max(0, min(0.5, current))
        
        return DynamicThreshold(
            type=ThresholdType.MIN_EXPECTED_VALUE,
            base_value=base,
            current_value=current,
            adjustments=adjustments
        )
        
    async def check_trade(
        self,
        tqs_score: float,
        win_rate: float,
        tape_score: float,
        expected_value: float,
        context: ThresholdContext
    ) -> ThresholdCheckResult:
        """
        Check if a trade passes all dynamic thresholds.
        
        Returns ThresholdCheckResult with pass/fail and details.
        """
        result = ThresholdCheckResult(context_used=context)
        
        # Calculate current thresholds
        thresholds = await self.calculate_thresholds(context)
        
        # Check TQS score
        tqs_threshold = thresholds.get(ThresholdType.MIN_TQS_SCORE.value)
        if tqs_threshold:
            result.thresholds_checked.append(tqs_threshold)
            if tqs_score < tqs_threshold.current_value:
                result.passes = False
                result.failures.append(
                    f"TQS score {tqs_score:.1f} below threshold {tqs_threshold.current_value:.1f}"
                )
            elif tqs_score < tqs_threshold.current_value + 5:
                result.warnings.append(
                    f"TQS score {tqs_score:.1f} just above threshold {tqs_threshold.current_value:.1f}"
                )
                
        # Check win rate
        wr_threshold = thresholds.get(ThresholdType.MIN_WIN_RATE.value)
        if wr_threshold:
            result.thresholds_checked.append(wr_threshold)
            if win_rate < wr_threshold.current_value:
                # Win rate failure is a warning, not blocking
                result.warnings.append(
                    f"Win rate {win_rate*100:.0f}% below threshold {wr_threshold.current_value*100:.0f}%"
                )
                
        # Check tape score
        tape_threshold = thresholds.get(ThresholdType.MIN_TAPE_SCORE.value)
        if tape_threshold:
            result.thresholds_checked.append(tape_threshold)
            if tape_score < tape_threshold.current_value:
                result.warnings.append(
                    f"Tape score {tape_score:.1f} below threshold {tape_threshold.current_value:.1f}"
                )
                
        # Check expected value
        ev_threshold = thresholds.get(ThresholdType.MIN_EXPECTED_VALUE.value)
        if ev_threshold:
            result.thresholds_checked.append(ev_threshold)
            if expected_value < ev_threshold.current_value:
                result.warnings.append(
                    f"Expected value {expected_value:.2f}R below threshold {ev_threshold.current_value:.2f}R"
                )
                
        return result
        
    def get_threshold_summary(self) -> Dict[str, Any]:
        """Get summary of all threshold configurations"""
        return {
            "base_thresholds": {k.value: v for k, v in self.BASE_THRESHOLDS.items()},
            "custom_overrides": self._custom_thresholds,
            "regime_adjustments": self.REGIME_TQS_ADJUSTMENTS,
            "time_adjustments": self.TIME_TAPE_ADJUSTMENTS,
            "vix_adjustments": {f"{low}-{high}": adj for (low, high), adj in self.VIX_TQS_ADJUSTMENTS.items()}
        }


# Singleton
_dynamic_threshold_service: Optional[DynamicThresholdService] = None


def get_dynamic_threshold_service() -> DynamicThresholdService:
    global _dynamic_threshold_service
    if _dynamic_threshold_service is None:
        _dynamic_threshold_service = DynamicThresholdService()
    return _dynamic_threshold_service


def init_dynamic_threshold_service(learning_loop=None) -> DynamicThresholdService:
    service = get_dynamic_threshold_service()
    service.set_services(learning_loop=learning_loop)
    return service
