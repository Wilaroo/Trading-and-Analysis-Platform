"""
TradeCommand Unified Trading Intelligence System
Deep integration of all trading knowledge: strategies, patterns, rules, scoring, and predictive logic
Provides comprehensive trade analysis, scoring, and AI-powered recommendations
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)


# ==================== ENUMS ====================

class TradeBias(Enum):
    STRONG_LONG = "strong_long"      # High confidence long
    LONG = "long"                     # Standard long
    SLIGHT_LONG = "slight_long"       # Lean long
    NEUTRAL = "neutral"               # No bias
    SLIGHT_SHORT = "slight_short"     # Lean short
    SHORT = "short"                   # Standard short
    STRONG_SHORT = "strong_short"     # High confidence short


class MarketCondition(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGE_BOUND = "range_bound"
    VOLATILE = "volatile"
    CHOPPY = "choppy"
    BREAKOUT = "breakout"
    MEAN_REVERSION = "mean_reversion"


class SetupQuality(Enum):
    A_PLUS = "A+"    # 90-100: Perfect setup, max size
    A = "A"          # 80-89: Excellent setup, full size
    B_PLUS = "B+"    # 70-79: Good setup, standard size
    B = "B"          # 60-69: Acceptable setup, reduced size
    C = "C"          # 50-59: Marginal setup, minimum size or skip
    F = "F"          # Below 50: Do not trade


class TimeOfDay(Enum):
    PREMARKET = "premarket"              # Before 9:30
    OPENING_AUCTION = "opening_auction"  # 9:30-9:35
    OPENING_DRIVE = "opening_drive"      # 9:35-9:45
    MORNING_MOMENTUM = "morning_momentum" # 9:45-10:00
    PRIME_TIME = "prime_time"            # 10:00-10:45
    LATE_MORNING = "late_morning"        # 10:45-11:30
    MIDDAY = "midday"                    # 11:30-1:30
    AFTERNOON = "afternoon"              # 1:30-3:00
    POWER_HOUR = "power_hour"            # 3:00-4:00


# ==================== DATA CLASSES ====================

@dataclass
class TradeSetup:
    """Complete trade setup with all parameters"""
    symbol: str
    strategy: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_price: float
    targets: List[float]
    position_size: float
    risk_amount: float
    quality_score: int
    quality_grade: SetupQuality
    confidence: float
    reasoning: List[str]
    warnings: List[str]
    chart_patterns: List[str]
    time_validity: str
    invalidation: str


@dataclass
class MarketAnalysis:
    """Comprehensive market analysis"""
    regime: MarketCondition
    bias: TradeBias
    strength_score: int  # 0-100
    vix_level: str  # "low", "normal", "elevated", "high"
    breadth: str  # "positive", "neutral", "negative"
    sector_leaders: List[str]
    sector_laggards: List[str]
    key_levels: Dict[str, float]
    recommended_strategies: List[str]
    avoid_strategies: List[str]
    position_sizing: str
    notes: List[str]


@dataclass 
class PatternMatch:
    """Chart pattern identification with scoring"""
    pattern_name: str
    pattern_type: str  # "continuation" or "reversal"
    bias: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0-1
    breakout_probability: float
    expected_move: float  # percentage
    entry_trigger: str
    stop_level: str
    target_calculation: str
    invalidation: str
    reliability_notes: str


# ==================== SCORING MATRICES ====================

# Strategy-Pattern Synergy Matrix
# Which chart patterns work best with which strategies
STRATEGY_PATTERN_SYNERGY = {
    "spencer_scalp": {
        "best_patterns": ["bull_flag", "ascending_triangle", "cup_and_handle", "bull_pennant"],
        "synergy_bonus": 15,
        "pattern_description": "Tight consolidation near HOD aligns with these continuation patterns"
    },
    "rubber_band": {
        "best_patterns": ["falling_wedge", "double_bottom", "inverse_head_shoulders"],
        "synergy_bonus": 12,
        "pattern_description": "Mean reversion benefits from reversal pattern confirmation"
    },
    "hitchhiker": {
        "best_patterns": ["bull_flag", "ascending_channel", "bull_pennant"],
        "synergy_bonus": 15,
        "pattern_description": "Early momentum continuation confirmed by flag/pennant"
    },
    "gap_give_and_go": {
        "best_patterns": ["bull_flag", "ascending_triangle"],
        "synergy_bonus": 12,
        "pattern_description": "Gap continuation with consolidation pattern"
    },
    "backside": {
        "best_patterns": ["double_bottom", "falling_wedge", "inverse_head_shoulders", "rounding_bottom"],
        "synergy_bonus": 15,
        "pattern_description": "Reversal trade confirmed by reversal patterns"
    },
    "off_sides": {
        "best_patterns": ["double_top", "double_bottom", "rectangle"],
        "synergy_bonus": 12,
        "pattern_description": "Range fade benefits from range-bound patterns"
    },
    "second_chance": {
        "best_patterns": ["bull_flag", "ascending_triangle", "cup_and_handle"],
        "synergy_bonus": 10,
        "pattern_description": "Retest entry aligned with continuation patterns"
    },
    "tidal_wave": {
        "best_patterns": ["head_shoulders", "double_top", "rising_wedge"],
        "synergy_bonus": 15,
        "pattern_description": "Exhaustion fade confirmed by reversal patterns"
    },
    "breaking_news": {
        "best_patterns": ["breakout", "gap_and_go"],
        "synergy_bonus": 10,
        "pattern_description": "Catalyst-driven moves don't rely heavily on patterns"
    },
    "wyckoff_spring": {
        "best_patterns": ["wyckoff_accumulation", "falling_wedge", "double_bottom"],
        "synergy_bonus": 20,
        "pattern_description": "Wyckoff spring is itself a pattern - perfect alignment"
    }
}

# Volume-Strategy Alignment
VOLUME_REQUIREMENTS = {
    "spencer_scalp": {"min_rvol": 1.5, "ideal_rvol": 2.5, "consolidation_vol": "decreasing"},
    "rubber_band": {"min_rvol": 2.0, "ideal_rvol": 5.0, "snapback_vol": "top_5"},
    "hitchhiker": {"min_rvol": 2.0, "ideal_rvol": 3.0, "consolidation_vol": "decreasing"},
    "gap_give_and_go": {"min_rvol": 2.0, "ideal_rvol": 3.0, "consolidation_vol": "decreasing"},
    "breaking_news": {"min_rvol": 3.0, "ideal_rvol": 5.0, "spike_required": True},
    "off_sides": {"min_rvol": 1.5, "ideal_rvol": 2.0, "range_vol": "equal_bars"},
    "backside": {"min_rvol": 1.5, "ideal_rvol": 2.0, "reversal_vol": "increasing"},
    "tidal_wave": {"min_rvol": 2.0, "ideal_rvol": 3.0, "exhaustion_vol": "climactic"},
    "volume_capitulation": {"min_rvol": 3.0, "ideal_rvol": 5.0, "spike_2x_second": True}
}

# Time-Strategy Scoring Matrix
TIME_STRATEGY_SCORES = {
    TimeOfDay.OPENING_AUCTION: {
        "first_vwap_pullback": 100, "bella_fade": 95, "first_move_up": 90,
        "first_move_down": 90, "back_through_open": 95, "opening_drive": 85
    },
    TimeOfDay.OPENING_DRIVE: {
        "gap_give_and_go": 100, "hitchhiker": 100, "orb": 95,
        "spencer_scalp": 70, "first_vwap_pullback": 80
    },
    TimeOfDay.MORNING_MOMENTUM: {
        "spencer_scalp": 95, "second_chance": 90, "9_ema_scalp": 85,
        "abc_scalp": 80, "trend_momentum": 90
    },
    TimeOfDay.PRIME_TIME: {
        "spencer_scalp": 100, "backside": 95, "fashionably_late": 95,
        "second_chance": 90, "off_sides": 90, "big_dog_consolidation": 85
    },
    TimeOfDay.LATE_MORNING: {
        "backside": 90, "second_chance": 90, "range_break": 85,
        "fashionably_late": 90, "off_sides": 85
    },
    TimeOfDay.MIDDAY: {
        "mean_reversion": 90, "vwap_fade": 90, "off_sides": 85,
        "rubber_band": 80, "range_break": 70
    },
    TimeOfDay.AFTERNOON: {
        "second_chance": 85, "trend_continuation": 80, "hod_breakout": 75,
        "spencer_scalp": 50  # Only ranging stocks
    },
    TimeOfDay.POWER_HOUR: {
        "hod_breakout": 100, "time_of_day_fade": 90, "moc_imbalance": 95,
        "range_break": 80
    }
}

# Market Regime Strategy Scores
REGIME_STRATEGY_SCORES = {
    MarketCondition.TRENDING_UP: {
        "spencer_scalp": 95, "hitchhiker": 100, "gap_give_and_go": 95,
        "trend_momentum": 100, "9_ema_scalp": 90, "second_chance": 85,
        "backside": 80, "off_sides": 30, "rubber_band": 40, "tidal_wave": 20
    },
    MarketCondition.TRENDING_DOWN: {
        "tidal_wave": 95, "backside_inverse": 90, "off_sides_short": 85,
        "short_scalps": 90, "spencer_scalp": 30, "hitchhiker": 20,
        "gap_give_and_go": 25, "rubber_band": 40
    },
    MarketCondition.VOLATILE: {
        "range_break": 90, "second_chance": 85, "off_sides": 80,
        "spencer_scalp": 70, "rubber_band": 75, "hitchhiker": 65
    },
    MarketCondition.RANGE_BOUND: {
        "off_sides": 100, "rubber_band": 95, "mean_reversion": 95,
        "vwap_fade": 90, "backside": 85, "spencer_scalp": 40,
        "hitchhiker": 30, "gap_give_and_go": 35
    },
    MarketCondition.BREAKOUT: {
        "orb": 100, "hitchhiker": 100, "spencer_scalp": 95,
        "gap_give_and_go": 95, "range_break": 90, "second_chance": 80,
        "off_sides": 20, "rubber_band": 30
    },
    MarketCondition.MEAN_REVERSION: {
        "off_sides": 100, "vwap_fade": 95, "rubber_band": 100,
        "backside": 90, "mean_reversion": 95, "spencer_scalp": 40,
        "hitchhiker": 30, "breakout": 25
    }
}


# ==================== MAIN INTELLIGENCE CLASS ====================

class TradingIntelligenceSystem:
    """
    Unified Trading Intelligence System
    Integrates strategies, patterns, rules, and scoring for comprehensive trade analysis
    """
    
    def __init__(self):
        self._init_knowledge_bases()
        
    def _init_knowledge_bases(self):
        """Initialize all knowledge bases"""
        # Lazy load services
        self._chart_pattern_service = None
        self._detailed_pattern_service = None
        self._trading_rules_engine = None
        
    @property
    def chart_patterns(self):
        if self._chart_pattern_service is None:
            from services.chart_patterns import get_chart_pattern_service
            self._chart_pattern_service = get_chart_pattern_service()
        return self._chart_pattern_service
    
    @property
    def detailed_patterns(self):
        if self._detailed_pattern_service is None:
            from services.chart_patterns_detailed import get_detailed_pattern_service
            self._detailed_pattern_service = get_detailed_pattern_service()
        return self._detailed_pattern_service
    
    @property
    def trading_rules(self):
        if self._trading_rules_engine is None:
            from services.trading_rules import get_trading_rules_engine
            self._trading_rules_engine = get_trading_rules_engine()
        return self._trading_rules_engine

    # ==================== SETUP SCORING ====================
    
    def score_trade_setup(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        current_price: float,
        rvol: float = 1.0,
        catalyst_score: int = 0,
        market_regime: MarketCondition = MarketCondition.VOLATILE,
        time_of_day: TimeOfDay = TimeOfDay.PRIME_TIME,
        detected_patterns: List[str] = None,
        technical_alignment: Dict = None
    ) -> Dict:
        """
        Comprehensive trade setup scoring system
        Returns detailed score breakdown and trade recommendation
        """
        score_breakdown = {
            "base_score": 50,
            "volume_score": 0,
            "time_score": 0,
            "regime_score": 0,
            "pattern_score": 0,
            "catalyst_score": 0,
            "technical_score": 0,
            "risk_reward_score": 0,
            "avoidance_deductions": 0,
            "synergy_bonus": 0
        }
        
        warnings = []
        reasoning = []
        
        strategy_key = strategy.lower().replace(" ", "_").replace("-", "_")
        
        # 1. VOLUME SCORING (0-15 points)
        vol_req = VOLUME_REQUIREMENTS.get(strategy_key, {"min_rvol": 1.5, "ideal_rvol": 3.0})
        if rvol >= vol_req.get("ideal_rvol", 3.0):
            score_breakdown["volume_score"] = 15
            reasoning.append(f"Excellent RVOL {rvol:.1f}x (ideal for {strategy})")
        elif rvol >= vol_req.get("min_rvol", 1.5):
            score_breakdown["volume_score"] = 10
            reasoning.append(f"Good RVOL {rvol:.1f}x meets minimum requirement")
        elif rvol >= 1.0:
            score_breakdown["volume_score"] = 5
            warnings.append(f"RVOL {rvol:.1f}x below minimum {vol_req.get('min_rvol')}x")
        else:
            score_breakdown["volume_score"] = -10
            warnings.append(f"RVOL {rvol:.1f}x too low - stock not In Play")
        
        # 2. TIME OF DAY SCORING (0-15 points)
        time_scores = TIME_STRATEGY_SCORES.get(time_of_day, {})
        time_match = time_scores.get(strategy_key, 50)
        score_breakdown["time_score"] = int((time_match / 100) * 15)
        
        if time_match >= 90:
            reasoning.append(f"Optimal time window for {strategy}")
        elif time_match >= 70:
            reasoning.append(f"Good time window for {strategy}")
        elif time_match < 50:
            warnings.append(f"Suboptimal time for {strategy} - consider waiting")
        
        # 3. MARKET REGIME SCORING (0-20 points)
        regime_scores = REGIME_STRATEGY_SCORES.get(market_regime, {})
        regime_match = regime_scores.get(strategy_key, 50)
        score_breakdown["regime_score"] = int((regime_match / 100) * 20)
        
        if regime_match >= 90:
            reasoning.append(f"Market regime ({market_regime.value}) ideal for {strategy}")
        elif regime_match >= 70:
            reasoning.append(f"Market regime supports {strategy}")
        elif regime_match < 40:
            warnings.append(f"Market regime ({market_regime.value}) unfavorable for {strategy}")
            score_breakdown["regime_score"] -= 5  # Extra penalty
        
        # 4. CHART PATTERN SCORING (0-15 points)
        if detected_patterns:
            synergy = STRATEGY_PATTERN_SYNERGY.get(strategy_key, {})
            best_patterns = synergy.get("best_patterns", [])
            
            pattern_matches = [p for p in detected_patterns if p.lower().replace(" ", "_") in best_patterns]
            
            if pattern_matches:
                score_breakdown["pattern_score"] = 15
                score_breakdown["synergy_bonus"] = synergy.get("synergy_bonus", 10)
                reasoning.append(f"Pattern alignment: {', '.join(pattern_matches)} synergize with {strategy}")
            elif detected_patterns:
                score_breakdown["pattern_score"] = 8
                reasoning.append(f"Chart patterns detected: {', '.join(detected_patterns)}")
        
        # 5. CATALYST SCORING (0-15 points)
        if catalyst_score != 0:
            abs_catalyst = abs(catalyst_score)
            if abs_catalyst >= 8:
                score_breakdown["catalyst_score"] = 15
                reasoning.append(f"Strong catalyst score {catalyst_score}: high conviction setup")
            elif abs_catalyst >= 6:
                score_breakdown["catalyst_score"] = 10
                reasoning.append(f"Good catalyst score {catalyst_score}")
            elif abs_catalyst >= 3:
                score_breakdown["catalyst_score"] = 5
            
            # Check catalyst-direction alignment
            if (catalyst_score > 0 and direction == "short") or (catalyst_score < 0 and direction == "long"):
                warnings.append("Trading against catalyst direction")
                score_breakdown["catalyst_score"] -= 5
        
        # 6. TECHNICAL ALIGNMENT SCORING (0-10 points)
        if technical_alignment:
            tech_score = 0
            if technical_alignment.get("above_vwap") and direction == "long":
                tech_score += 3
                reasoning.append("Price above VWAP - bullish intraday bias")
            elif technical_alignment.get("below_vwap") and direction == "short":
                tech_score += 3
                reasoning.append("Price below VWAP - bearish intraday bias")
            
            if technical_alignment.get("above_9ema") and direction == "long":
                tech_score += 3
            elif technical_alignment.get("below_9ema") and direction == "short":
                tech_score += 3
            
            if technical_alignment.get("higher_highs_higher_lows") and direction == "long":
                tech_score += 4
                reasoning.append("HH/HL structure confirms uptrend")
            elif technical_alignment.get("lower_highs_lower_lows") and direction == "short":
                tech_score += 4
                reasoning.append("LH/LL structure confirms downtrend")
            
            score_breakdown["technical_score"] = min(tech_score, 10)
        
        # 7. RISK/REWARD SCORING (0-10 points)
        risk = abs(entry_price - stop_price)
        if risk > 0:
            # Estimate target based on strategy
            estimated_target = entry_price + (risk * 2) if direction == "long" else entry_price - (risk * 2)
            rr_ratio = 2.0  # Minimum acceptable
            
            if rr_ratio >= 3:
                score_breakdown["risk_reward_score"] = 10
                reasoning.append(f"Excellent R:R ratio of {rr_ratio:.1f}")
            elif rr_ratio >= 2:
                score_breakdown["risk_reward_score"] = 7
            elif rr_ratio >= 1.5:
                score_breakdown["risk_reward_score"] = 4
                warnings.append(f"R:R ratio {rr_ratio:.1f} below ideal 2:1")
            else:
                score_breakdown["risk_reward_score"] = 0
                warnings.append(f"Poor R:R ratio {rr_ratio:.1f}")
        
        # 8. AVOIDANCE RULE DEDUCTIONS
        avoidance_rules = self.trading_rules.avoidance_rules.get("strategy_specific", {}).get(strategy_key, [])
        # This would be checked against actual conditions - placeholder for now
        
        # CALCULATE FINAL SCORE
        total_score = (
            score_breakdown["base_score"] +
            score_breakdown["volume_score"] +
            score_breakdown["time_score"] +
            score_breakdown["regime_score"] +
            score_breakdown["pattern_score"] +
            score_breakdown["catalyst_score"] +
            score_breakdown["technical_score"] +
            score_breakdown["risk_reward_score"] +
            score_breakdown["synergy_bonus"] +
            score_breakdown["avoidance_deductions"]
        )
        
        # Determine grade
        if total_score >= 90:
            grade = SetupQuality.A_PLUS
            position_recommendation = "Maximum position size - A+ setup"
        elif total_score >= 80:
            grade = SetupQuality.A
            position_recommendation = "Full position size - A setup"
        elif total_score >= 70:
            grade = SetupQuality.B_PLUS
            position_recommendation = "Standard position size - B+ setup"
        elif total_score >= 60:
            grade = SetupQuality.B
            position_recommendation = "Reduced position size - B setup"
        elif total_score >= 50:
            grade = SetupQuality.C
            position_recommendation = "Minimum position or skip - C setup"
        else:
            grade = SetupQuality.F
            position_recommendation = "DO NOT TRADE - F setup"
        
        return {
            "symbol": symbol,
            "strategy": strategy,
            "direction": direction,
            "total_score": total_score,
            "grade": grade.value,
            "position_recommendation": position_recommendation,
            "score_breakdown": score_breakdown,
            "reasoning": reasoning,
            "warnings": warnings,
            "trade_or_skip": "TRADE" if total_score >= 60 else "SKIP"
        }
    
    # ==================== MARKET ANALYSIS ====================
    
    def analyze_market_conditions(
        self,
        spy_trend: str = "neutral",
        vix_level: float = 15.0,
        market_breadth: str = "neutral",
        rvol_market: float = 1.0,
        gaps_filling: bool = False,
        breakouts_working: bool = True
    ) -> MarketAnalysis:
        """
        Comprehensive market regime analysis
        """
        # Determine regime
        if spy_trend == "strong_up" and breakouts_working:
            regime = MarketCondition.TRENDING_UP
            bias = TradeBias.STRONG_LONG
        elif spy_trend == "strong_down":
            regime = MarketCondition.TRENDING_DOWN
            bias = TradeBias.STRONG_SHORT
        elif gaps_filling and not breakouts_working:
            regime = MarketCondition.MEAN_REVERSION
            bias = TradeBias.NEUTRAL
        elif breakouts_working and rvol_market > 2:
            regime = MarketCondition.BREAKOUT
            bias = TradeBias.LONG if spy_trend != "down" else TradeBias.SHORT
        elif vix_level > 25:
            regime = MarketCondition.VOLATILE
            bias = TradeBias.NEUTRAL
        elif rvol_market < 0.8:
            regime = MarketCondition.CHOPPY
            bias = TradeBias.NEUTRAL
        else:
            regime = MarketCondition.RANGE_BOUND
            bias = TradeBias.NEUTRAL
        
        # Get recommended strategies for this regime
        regime_scores = REGIME_STRATEGY_SCORES.get(regime, {})
        recommended = [s for s, score in regime_scores.items() if score >= 80]
        avoid = [s for s, score in regime_scores.items() if score < 40]
        
        # Position sizing recommendation
        if regime in [MarketCondition.CHOPPY, MarketCondition.VOLATILE]:
            position_sizing = "Reduced 50%"
        elif regime in [MarketCondition.TRENDING_UP, MarketCondition.BREAKOUT]:
            position_sizing = "Full size on longs"
        elif regime == MarketCondition.TRENDING_DOWN:
            position_sizing = "Full size on shorts"
        else:
            position_sizing = "Normal sizing"
        
        # VIX assessment
        if vix_level < 12:
            vix_assessment = "low"
        elif vix_level < 20:
            vix_assessment = "normal"
        elif vix_level < 30:
            vix_assessment = "elevated"
        else:
            vix_assessment = "high"
        
        # Strength score
        strength = 50
        if spy_trend == "strong_up":
            strength += 30
        elif spy_trend == "up":
            strength += 15
        elif spy_trend == "down":
            strength -= 15
        elif spy_trend == "strong_down":
            strength -= 30
        
        if breakouts_working:
            strength += 10
        if market_breadth == "positive":
            strength += 10
        elif market_breadth == "negative":
            strength -= 10
        
        strength = max(0, min(100, strength))
        
        return MarketAnalysis(
            regime=regime,
            bias=bias,
            strength_score=strength,
            vix_level=vix_assessment,
            breadth=market_breadth,
            sector_leaders=[],
            sector_laggards=[],
            key_levels={},
            recommended_strategies=recommended,
            avoid_strategies=avoid,
            position_sizing=position_sizing,
            notes=[
                f"Market regime: {regime.value}",
                f"Trading bias: {bias.value}",
                f"VIX at {vix_level} ({vix_assessment})"
            ]
        )
    
    # ==================== PATTERN-STRATEGY MATCHING ====================
    
    def match_patterns_to_strategies(
        self,
        detected_patterns: List[str],
        direction: str = "long"
    ) -> List[Dict]:
        """
        Given detected chart patterns, recommend the best strategies
        """
        recommendations = []
        
        for strategy_key, synergy in STRATEGY_PATTERN_SYNERGY.items():
            best_patterns = synergy.get("best_patterns", [])
            matches = [p for p in detected_patterns if p.lower().replace(" ", "_") in best_patterns]
            
            if matches:
                # Check direction alignment
                strategy_direction = "both"
                if strategy_key in ["spencer_scalp", "hitchhiker", "gap_give_and_go"]:
                    strategy_direction = "long"  # Primarily long strategies
                elif strategy_key in ["tidal_wave"]:
                    strategy_direction = "both"  # Works both ways
                
                if strategy_direction == "both" or strategy_direction == direction:
                    recommendations.append({
                        "strategy": strategy_key.replace("_", " ").title(),
                        "matching_patterns": matches,
                        "synergy_score": synergy.get("synergy_bonus", 10),
                        "explanation": synergy.get("pattern_description", ""),
                        "direction": direction
                    })
        
        # Sort by synergy score
        recommendations.sort(key=lambda x: x["synergy_score"], reverse=True)
        
        return recommendations
    
    # ==================== TRADE VALIDATION ====================
    
    def validate_trade_idea(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        rvol: float,
        time_of_day: TimeOfDay,
        market_regime: MarketCondition,
        catalyst_score: int = 0,
        against_spy_trend: bool = False
    ) -> Dict:
        """
        Complete trade validation with go/no-go decision
        """
        blockers = []
        warnings = []
        confirmations = []
        
        strategy_key = strategy.lower().replace(" ", "_")
        
        # 1. Check universal avoidance rules
        if against_spy_trend:
            blockers.append("BLOCKER: Trading against SPY/market trend")
        
        if rvol < 1.0:
            blockers.append("BLOCKER: Stock not In Play (RVOL < 1.0)")
        
        # 2. Check strategy-specific avoidance
        avoidance = self.trading_rules.avoidance_rules.get("strategy_specific", {}).get(strategy_key, [])
        
        # 3. Check time restrictions
        time_restrictions = self.trading_rules.time_rules.get("strategy_time_restrictions", {}).get(strategy, {})
        
        if strategy_key == "hitchhiker" and time_of_day not in [TimeOfDay.OPENING_AUCTION, TimeOfDay.OPENING_DRIVE]:
            blockers.append("BLOCKER: HitchHiker must setup before 9:59 AM")
        
        if strategy_key == "gap_give_and_go" and time_of_day not in [TimeOfDay.OPENING_AUCTION, TimeOfDay.OPENING_DRIVE]:
            blockers.append("BLOCKER: Gap Give and Go must trigger before 9:45 AM")
        
        if strategy_key == "spencer_scalp" and time_of_day == TimeOfDay.POWER_HOUR:
            warnings.append("WARNING: Spencer Scalp after 3 PM - only for ranging stocks")
        
        # 4. Check regime alignment
        regime_scores = REGIME_STRATEGY_SCORES.get(market_regime, {})
        regime_score = regime_scores.get(strategy_key, 50)
        
        if regime_score < 40:
            warnings.append(f"WARNING: {strategy} not ideal for {market_regime.value} market")
        elif regime_score >= 80:
            confirmations.append(f"Market regime ({market_regime.value}) ideal for {strategy}")
        
        # 5. Check volume
        vol_req = VOLUME_REQUIREMENTS.get(strategy_key, {"min_rvol": 1.5})
        if rvol < vol_req.get("min_rvol", 1.5):
            warnings.append(f"WARNING: RVOL {rvol:.1f}x below minimum {vol_req.get('min_rvol')}x")
        elif rvol >= vol_req.get("ideal_rvol", 3.0):
            confirmations.append(f"Excellent volume: RVOL {rvol:.1f}x")
        
        # 6. Risk calculation
        risk_per_share = abs(entry_price - stop_price)
        risk_percent = (risk_per_share / entry_price) * 100
        
        if risk_percent > 5:
            warnings.append(f"WARNING: Risk per share {risk_percent:.1f}% exceeds 5% threshold")
        
        # 7. Catalyst alignment
        if catalyst_score != 0:
            if (catalyst_score > 0 and direction == "long") or (catalyst_score < 0 and direction == "short"):
                confirmations.append(f"Catalyst ({catalyst_score}) aligned with {direction} direction")
            else:
                warnings.append(f"WARNING: Catalyst ({catalyst_score}) opposes {direction} direction")
        
        # FINAL DECISION
        if blockers:
            decision = "NO TRADE"
            confidence = 0
        elif len(warnings) >= 3:
            decision = "HIGH RISK"
            confidence = 30
        elif len(warnings) >= 2:
            decision = "CAUTION"
            confidence = 50
        elif len(confirmations) >= 2 and len(warnings) == 0:
            decision = "STRONG GO"
            confidence = 90
        elif len(confirmations) >= 1:
            decision = "GO"
            confidence = 70
        else:
            decision = "NEUTRAL"
            confidence = 50
        
        return {
            "symbol": symbol,
            "strategy": strategy,
            "direction": direction,
            "decision": decision,
            "confidence": confidence,
            "blockers": blockers,
            "warnings": warnings,
            "confirmations": confirmations,
            "risk_per_share": risk_per_share,
            "risk_percent": risk_percent,
            "recommendation": self._get_recommendation_text(decision, strategy, direction, confirmations, warnings)
        }
    
    def _get_recommendation_text(
        self,
        decision: str,
        strategy: str,
        direction: str,
        confirmations: List[str],
        warnings: List[str]
    ) -> str:
        """Generate human-readable recommendation"""
        if decision == "NO TRADE":
            return f"❌ DO NOT TAKE THIS TRADE. Critical blockers identified that violate trading rules."
        elif decision == "STRONG GO":
            return f"✅ STRONG {direction.upper()} setup via {strategy}. Multiple confirmations align. Execute with full size."
        elif decision == "GO":
            return f"✅ Valid {direction.upper()} setup via {strategy}. Proceed with standard position size."
        elif decision == "CAUTION":
            return f"⚠️ Proceed with CAUTION. Some warnings present. Consider reduced position size."
        elif decision == "HIGH RISK":
            return f"⚠️ HIGH RISK trade. Multiple warnings. Only take if you have strong conviction and use minimum size."
        else:
            return f"🔸 Neutral setup. No strong edge either way. Wait for better conditions."
    
    # ==================== AI CONTEXT GENERATION ====================
    
    def get_comprehensive_context_for_ai(
        self,
        symbol: str = None,
        strategy: str = None,
        pattern: str = None,
        market_analysis: bool = False
    ) -> str:
        """
        Generate comprehensive context for AI assistant
        """
        context_parts = []
        
        context_parts.append("=== TRADECOMMAND INTELLIGENCE SYSTEM ===\n")
        
        # 1. If strategy requested, provide full strategy knowledge
        if strategy:
            strategy_key = strategy.lower().replace(" ", "_")
            context_parts.append(f"\n## {strategy.upper()} STRATEGY ANALYSIS\n")
            
            # Get synergy info
            synergy = STRATEGY_PATTERN_SYNERGY.get(strategy_key, {})
            if synergy:
                context_parts.append(f"Best Chart Patterns: {', '.join(synergy.get('best_patterns', []))}")
                context_parts.append(f"Pattern Synergy: {synergy.get('pattern_description', '')}")
            
            # Get volume requirements
            vol_req = VOLUME_REQUIREMENTS.get(strategy_key, {})
            if vol_req:
                context_parts.append(f"\nVolume Requirements:")
                context_parts.append(f"- Minimum RVOL: {vol_req.get('min_rvol', 'N/A')}x")
                context_parts.append(f"- Ideal RVOL: {vol_req.get('ideal_rvol', 'N/A')}x")
            
            # Get time scores
            context_parts.append(f"\nOptimal Trading Windows:")
            for tod, scores in TIME_STRATEGY_SCORES.items():
                if strategy_key in scores and scores[strategy_key] >= 80:
                    context_parts.append(f"- {tod.value}: {scores[strategy_key]}% alignment")
        
        # 2. If pattern requested, provide full pattern knowledge
        if pattern:
            pattern_id = pattern.lower().replace(" ", "_")
            detailed = self.detailed_patterns.get_formatted_for_ai(pattern_id)
            if detailed and "No detailed analysis" not in detailed:
                context_parts.append(detailed)
            else:
                # Fall back to basic pattern
                basic = self.chart_patterns.get_pattern(pattern_id)
                if basic:
                    context_parts.append(f"\n## {pattern.upper()} PATTERN")
                    context_parts.append(f"Type: {basic['pattern_type']} | Bias: {basic['bias']}")
                    context_parts.append(f"Entry: {basic['entry']}")
                    context_parts.append(f"Stop: {basic['stop']}")
                    context_parts.append(f"Target: {basic['target']}")
        
        # 3. If market analysis requested, provide regime guidance
        if market_analysis:
            context_parts.append("\n## MARKET REGIME STRATEGIES\n")
            for regime, strategies in REGIME_STRATEGY_SCORES.items():
                top_strategies = sorted(strategies.items(), key=lambda x: x[1], reverse=True)[:3]
                context_parts.append(f"\n{regime.value.upper()}:")
                for strat, score in top_strategies:
                    context_parts.append(f"  - {strat}: {score}% fit")
        
        # 4. Add scoring system explanation
        context_parts.append("\n## SETUP SCORING SYSTEM")
        context_parts.append("""
Setup Quality Grades:
- A+ (90-100): Perfect setup - MAX position size
- A (80-89): Excellent setup - FULL position size  
- B+ (70-79): Good setup - STANDARD position size
- B (60-69): Acceptable setup - REDUCED position size
- C (50-59): Marginal setup - MINIMUM size or SKIP
- F (<50): DO NOT TRADE

Score Components:
- Volume (0-15 pts): RVOL vs strategy requirements
- Time (0-15 pts): Time of day alignment
- Regime (0-20 pts): Market condition fit
- Pattern (0-15 pts): Chart pattern synergy
- Catalyst (0-15 pts): News/catalyst strength
- Technical (0-10 pts): MA/VWAP alignment
- R:R (0-10 pts): Risk/reward quality
- Synergy Bonus: Pattern-strategy alignment bonus
""")
        
        return "\n".join(context_parts)
    
    # ==================== PREDICTIVE ANALYSIS ====================
    
    def predict_trade_outcome(
        self,
        setup_score: int,
        pattern_reliability: float,
        regime_alignment: float,
        volume_strength: float
    ) -> Dict:
        """
        Predict probability of trade success based on historical factors
        """
        # Base probability from setup score
        base_prob = setup_score / 100
        
        # Adjust for pattern reliability (Bulkowski stats)
        pattern_factor = pattern_reliability  # e.g., 0.67 for bull flag
        
        # Adjust for regime
        regime_factor = regime_alignment / 100
        
        # Adjust for volume
        if volume_strength >= 3.0:
            vol_factor = 1.1
        elif volume_strength >= 2.0:
            vol_factor = 1.0
        elif volume_strength >= 1.5:
            vol_factor = 0.9
        else:
            vol_factor = 0.7
        
        # Combined probability (weighted average)
        success_probability = (
            base_prob * 0.3 +
            pattern_factor * 0.3 +
            regime_factor * 0.25 +
            (vol_factor - 0.7) / 0.4 * 0.15  # Normalize vol factor
        )
        
        success_probability = max(0.1, min(0.95, success_probability))
        
        # Expected value calculation
        # Assuming 2:1 R:R on winners, 1:1 on losers
        expected_value = (success_probability * 2) - ((1 - success_probability) * 1)
        
        return {
            "success_probability": round(success_probability * 100, 1),
            "expected_value_per_r": round(expected_value, 2),
            "confidence_level": "HIGH" if success_probability > 0.7 else "MEDIUM" if success_probability > 0.5 else "LOW",
            "trade_worthiness": "FAVORABLE" if expected_value > 0.5 else "MARGINAL" if expected_value > 0 else "UNFAVORABLE",
            "factors": {
                "setup_contribution": round(base_prob * 30, 1),
                "pattern_contribution": round(pattern_factor * 30, 1),
                "regime_contribution": round(regime_factor * 25, 1),
                "volume_contribution": round((vol_factor - 0.7) / 0.4 * 15, 1)
            }
        }


# ==================== SINGLETON ====================

_trading_intelligence: Optional[TradingIntelligenceSystem] = None

def get_trading_intelligence() -> TradingIntelligenceSystem:
    """Get singleton trading intelligence system"""
    global _trading_intelligence
    if _trading_intelligence is None:
        _trading_intelligence = TradingIntelligenceSystem()
    return _trading_intelligence
