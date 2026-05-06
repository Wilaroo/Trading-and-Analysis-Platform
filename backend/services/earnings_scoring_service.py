"""
SMB Capital Earnings Scoring Service

Implements the -10 to +10 earnings catalyst scoring system from SMB Capital.
Scores are based on the "Big Three" (Revenue, EPS, Margins) vs analyst expectations,
plus guidance quality and modifiers.

Key Rules:
- Score in under 3 minutes
- Revenue beat % is typically 60-70% of EPS beat %
- Management track record can adjust score ±1-2 points
- Competitor comparison can adjust score ±1-2 points
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class GuidanceDirection(Enum):
    """Direction of guidance change"""
    RAISED = "raised"
    LOWERED = "lowered"
    REITERATED = "reiterated"
    NONE = "none"


class TradingApproach(Enum):
    """Trading approach based on catalyst score"""
    MAX_CONVICTION = "max_conviction"  # ±10
    AGGRESSIVE = "aggressive"          # ±9
    DIRECTIONAL = "directional"        # ±8
    LIMITED = "limited"                # ±7
    AVOID = "avoid"                    # ±6 and below


@dataclass
class EarningsData:
    """Raw earnings data for scoring"""
    symbol: str
    report_date: str
    
    # EPS
    eps_actual: float
    eps_estimate: float
    
    # Revenue (in millions)
    revenue_actual: float
    revenue_estimate: float
    
    # Margins
    margin_actual: Optional[float] = None
    margin_previous: Optional[float] = None
    
    # Guidance
    q_guidance_provided: bool = False
    q_guidance_direction: GuidanceDirection = GuidanceDirection.NONE
    q_guidance_vs_estimate: float = 0.0  # % above/below consensus
    
    fy_guidance_provided: bool = False
    fy_guidance_direction: GuidanceDirection = GuidanceDirection.NONE
    fy_guidance_vs_estimate: float = 0.0  # % above/below consensus
    
    # Revenue guidance (important per SMB)
    revenue_guidance_provided: bool = False
    revenue_guidance_direction: GuidanceDirection = GuidanceDirection.NONE
    
    @property
    def eps_surprise_pct(self) -> float:
        """EPS surprise as percentage"""
        if self.eps_estimate == 0:
            return 0.0
        return ((self.eps_actual - self.eps_estimate) / abs(self.eps_estimate)) * 100
    
    @property
    def revenue_surprise_pct(self) -> float:
        """Revenue surprise as percentage"""
        if self.revenue_estimate == 0:
            return 0.0
        return ((self.revenue_actual - self.revenue_estimate) / self.revenue_estimate) * 100
    
    @property
    def margin_trend(self) -> str:
        """Margin trend: expanding, contracting, or flat"""
        if self.margin_actual is None or self.margin_previous is None:
            return "unknown"
        diff = self.margin_actual - self.margin_previous
        if diff > 0.5:
            return "expanding"
        elif diff < -0.5:
            return "contracting"
        return "flat"
    
    @property
    def is_double_beat(self) -> bool:
        """Both EPS and Revenue beat"""
        return self.eps_surprise_pct > 0 and self.revenue_surprise_pct > 0
    
    @property
    def is_double_miss(self) -> bool:
        """Both EPS and Revenue miss"""
        return self.eps_surprise_pct < 0 and self.revenue_surprise_pct < 0


@dataclass
class EarningsScore:
    """Complete earnings catalyst score with reasoning"""
    symbol: str
    base_score: int = 0           # -10 to +10 from Big Three
    modifier_adjustment: int = 0   # -2 to +2 from modifiers
    final_score: int = 0          # base_score + modifier_adjustment
    
    # Component scores
    eps_score: int = 0
    revenue_score: int = 0
    margin_score: int = 0
    guidance_score: int = 0
    
    # Direction
    direction: str = "neutral"    # "bullish", "bearish", "neutral"
    
    # Trading implications
    trading_approach: TradingApproach = TradingApproach.AVOID
    suggested_setups: List[str] = field(default_factory=list)
    avoid_setups: List[str] = field(default_factory=list)
    
    # Reasoning
    base_score_reasoning: List[str] = field(default_factory=list)
    modifier_reasoning: List[str] = field(default_factory=list)
    
    # Raw data reference
    eps_surprise_pct: float = 0.0
    revenue_surprise_pct: float = 0.0
    guidance_summary: str = ""
    
    # Metadata
    scored_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scoring_time_seconds: float = 0.0  # Should be < 180 (3 min)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result["trading_approach"] = self.trading_approach.value
        return result


# ==================== SCORING THRESHOLDS ====================

# EPS surprise thresholds (from SMB)
EPS_THRESHOLDS = {
    "extreme": 50.0,      # ±10
    "exponential": 15.0,  # ±9
    "above_avg": 5.0,     # ±8
    "inline": 2.0,        # ±7
}

# Revenue surprise thresholds (typically 60-70% of EPS)
REVENUE_THRESHOLDS = {
    "extreme": 15.0,      # ±10
    "exponential": 8.0,   # ±9
    "above_avg": 4.0,     # ±8
    "inline": 2.0,        # ±7
}


def calculate_earnings_score(
    data: EarningsData,
    management_track_record: str = "neutral",  # "under_promise", "over_promise", "neutral"
    competitor_comparison: str = "similar",     # "better", "worse", "similar"
    quarter_position: int = 1                   # 1-4, which quarter (affects guidance weight)
) -> EarningsScore:
    """
    Calculate earnings catalyst score using SMB methodology.
    
    Steps:
    1. Calculate base score from Big Three (EPS, Revenue, Margins)
    2. Adjust for guidance
    3. Apply modifiers (management track record, competitor comparison)
    4. Determine trading approach and suggested setups
    
    Should complete in under 3 minutes.
    """
    import time
    start_time = time.time()
    
    score = EarningsScore(symbol=data.symbol)
    score.eps_surprise_pct = data.eps_surprise_pct
    score.revenue_surprise_pct = data.revenue_surprise_pct
    
    # Determine direction
    if data.eps_surprise_pct > 0:
        score.direction = "bullish"
        direction_multiplier = 1
    elif data.eps_surprise_pct < 0:
        score.direction = "bearish"
        direction_multiplier = -1
    else:
        score.direction = "neutral"
        direction_multiplier = 0
    
    # ==================== BASE SCORE CALCULATION ====================
    
    eps_pct = abs(data.eps_surprise_pct)
    rev_pct = abs(data.revenue_surprise_pct)
    
    # Step 1: EPS Score (0-4 points)
    if eps_pct >= EPS_THRESHOLDS["extreme"]:
        score.eps_score = 4
        score.base_score_reasoning.append(f"EXTREME EPS surprise: {data.eps_surprise_pct:+.1f}%")
    elif eps_pct >= EPS_THRESHOLDS["exponential"]:
        score.eps_score = 3
        score.base_score_reasoning.append(f"Exponential EPS surprise: {data.eps_surprise_pct:+.1f}%")
    elif eps_pct >= EPS_THRESHOLDS["above_avg"]:
        score.eps_score = 2
        score.base_score_reasoning.append(f"Above-avg EPS surprise: {data.eps_surprise_pct:+.1f}%")
    elif eps_pct >= EPS_THRESHOLDS["inline"]:
        score.eps_score = 1
        score.base_score_reasoning.append(f"Inline EPS: {data.eps_surprise_pct:+.1f}%")
    else:
        score.eps_score = 0
        score.base_score_reasoning.append(f"Neutral EPS: {data.eps_surprise_pct:+.1f}%")
    
    # Step 2: Revenue Score (0-3 points)
    if rev_pct >= REVENUE_THRESHOLDS["extreme"]:
        score.revenue_score = 3
        score.base_score_reasoning.append(f"EXTREME Revenue surprise: {data.revenue_surprise_pct:+.1f}%")
    elif rev_pct >= REVENUE_THRESHOLDS["exponential"]:
        score.revenue_score = 2
        score.base_score_reasoning.append(f"Exponential Revenue: {data.revenue_surprise_pct:+.1f}%")
    elif rev_pct >= REVENUE_THRESHOLDS["above_avg"]:
        score.revenue_score = 1
        score.base_score_reasoning.append(f"Above-avg Revenue: {data.revenue_surprise_pct:+.1f}%")
    else:
        score.revenue_score = 0
        score.base_score_reasoning.append(f"Inline/miss Revenue: {data.revenue_surprise_pct:+.1f}%")
    
    # Step 3: Margin Score (0-1 point)
    if data.margin_trend == "expanding":
        score.margin_score = 1
        score.base_score_reasoning.append("Margins expanding")
    elif data.margin_trend == "contracting":
        score.margin_score = -1
        score.base_score_reasoning.append("Margins contracting (negative)")
    else:
        score.margin_score = 0
    
    # Step 4: Guidance Score (0-2 points)
    guidance_parts = []
    
    if data.fy_guidance_provided:
        if data.fy_guidance_direction == GuidanceDirection.RAISED:
            score.guidance_score += 1
            guidance_parts.append("FY guidance raised")
        elif data.fy_guidance_direction == GuidanceDirection.LOWERED:
            score.guidance_score -= 1
            guidance_parts.append("FY guidance lowered")
    
    if data.q_guidance_provided:
        if data.q_guidance_direction == GuidanceDirection.RAISED:
            score.guidance_score += 1
            guidance_parts.append("Q guidance raised")
        elif data.q_guidance_direction == GuidanceDirection.LOWERED:
            score.guidance_score -= 1
            guidance_parts.append("Q guidance lowered")
    
    # Extra weight for BOTH quarterly AND full year (SMB rule for ±9)
    if (data.q_guidance_provided and data.fy_guidance_provided and
        data.q_guidance_direction == GuidanceDirection.RAISED and
        data.fy_guidance_direction == GuidanceDirection.RAISED):
        score.guidance_score += 1
        guidance_parts.append("BOTH Q and FY guidance raised (+bonus)")
    
    # Revenue guidance is especially important (ON vs NXPI example)
    if data.revenue_guidance_provided:
        if data.revenue_guidance_direction == GuidanceDirection.RAISED:
            score.guidance_score += 1
            guidance_parts.append("Revenue guidance raised (key indicator)")
        elif data.revenue_guidance_direction == GuidanceDirection.LOWERED:
            score.guidance_score -= 1
            guidance_parts.append("Revenue guidance lowered (warning)")
    
    if guidance_parts:
        score.base_score_reasoning.append("Guidance: " + ", ".join(guidance_parts))
        score.guidance_summary = ", ".join(guidance_parts)
    else:
        score.guidance_summary = "No guidance provided"
        score.base_score_reasoning.append("No guidance provided")
    
    # Calculate base score (5-10 scale mapped from components)
    component_total = score.eps_score + score.revenue_score + score.margin_score + score.guidance_score
    
    # Map to 5-10 scale
    if component_total >= 8:
        raw_base = 10
    elif component_total >= 6:
        raw_base = 9
    elif component_total >= 4:
        raw_base = 8
    elif component_total >= 2:
        raw_base = 7
    elif component_total >= 0:
        raw_base = 6 if data.is_double_beat or data.is_double_miss else 5
    else:
        raw_base = 5
    
    # Apply direction
    score.base_score = raw_base * direction_multiplier
    
    # ==================== MODIFIER ADJUSTMENTS ====================
    
    # Management track record modifier
    if management_track_record == "under_promise":
        score.modifier_adjustment += 1
        score.modifier_reasoning.append("Management consistently under-promises and over-delivers (+1)")
    elif management_track_record == "over_promise":
        score.modifier_adjustment -= 1
        score.modifier_reasoning.append("Management tends to over-promise and under-deliver (-1)")
    
    # Competitor comparison modifier (ON vs NXPI example)
    if competitor_comparison == "better":
        score.modifier_adjustment += 1
        score.modifier_reasoning.append("Outperformed key competitor (+1)")
    elif competitor_comparison == "worse":
        score.modifier_adjustment -= 1
        score.modifier_reasoning.append("Underperformed key competitor (-1)")
    
    # Quarter position affects guidance weight
    if quarter_position == 1 and not data.fy_guidance_provided:
        # Q1 without full year guidance is less meaningful
        score.modifier_reasoning.append("Q1 without FY guidance - less conviction")
    
    # Guidance without revenue growth (ON example)
    if (score.guidance_score > 0 and 
        data.revenue_guidance_direction != GuidanceDirection.RAISED and
        data.fy_guidance_direction == GuidanceDirection.RAISED):
        score.modifier_adjustment -= 1
        score.modifier_reasoning.append("Guided up on efficiency but not revenue growth (-1)")
    
    # Final score
    score.final_score = score.base_score + (score.modifier_adjustment * direction_multiplier)
    
    # Clamp to -10 to +10
    score.final_score = max(-10, min(10, score.final_score))
    
    # ==================== TRADING APPROACH ====================
    
    abs_score = abs(score.final_score)
    
    if abs_score >= 10:
        score.trading_approach = TradingApproach.MAX_CONVICTION
        if score.final_score > 0:
            score.suggested_setups = ["opening_drive", "back_through_open", "hod_breakout"]
            score.avoid_setups = ["gap_fade", "bella_fade", "time_of_day_fade"]
        else:
            score.suggested_setups = ["opening_drive", "lod_breakdown", "gap_pick_roll"]
            score.avoid_setups = ["gap_give_go", "vwap_bounce"]
    
    elif abs_score >= 9:
        score.trading_approach = TradingApproach.AGGRESSIVE
        if score.final_score > 0:
            score.suggested_setups = ["back_through_open", "hitchhiker", "hod_breakout", "orb"]
            score.avoid_setups = ["gap_fade", "off_sides"]
        else:
            score.suggested_setups = ["gap_pick_roll", "tidal_wave", "lod_breakdown"]
            score.avoid_setups = ["gap_give_go", "rubber_band_long"]
    
    elif abs_score >= 8:
        score.trading_approach = TradingApproach.DIRECTIONAL
        if score.final_score > 0:
            score.suggested_setups = ["gap_give_go", "second_chance", "vwap_bounce"]
            score.avoid_setups = ["bella_fade"]
        else:
            score.suggested_setups = ["gap_pick_roll", "second_chance", "vwap_fade"]
            score.avoid_setups = ["gap_give_go"]
    
    elif abs_score >= 7:
        score.trading_approach = TradingApproach.LIMITED
        score.suggested_setups = ["wait_for_clear_setup"]
        score.avoid_setups = ["aggressive_momentum_plays"]
    
    else:
        score.trading_approach = TradingApproach.AVOID
        score.suggested_setups = ["rubber_band", "off_sides"]  # Fade plays only
        score.avoid_setups = ["directional_plays", "momentum_plays"]
    
    # Calculate scoring time
    score.scoring_time_seconds = time.time() - start_time
    
    logger.info(f"📊 Earnings Score for {data.symbol}: {score.final_score:+d} "
               f"(base: {score.base_score:+d}, mod: {score.modifier_adjustment:+d}) "
               f"- {score.trading_approach.value}")
    
    return score


# ==================== SCORE INTERPRETATION ====================

SCORE_DESCRIPTIONS = {
    10: {
        "name": "Black Swan (Bullish)",
        "characteristics": [
            "Everything looks perfect",
            "Massive hype - everyone is talking about it",
            "Expectations through the roof",
            "Stock price already reflects good news"
        ],
        "approach": "Max conviction long, watch for 'sell the news'",
        "example": "NVDA 05/24/2023"
    },
    9: {
        "name": "Exponential Positive",
        "characteristics": [
            "Strongly positive expectations",
            "Analyst upgrades and bullish sentiment",
            "Media is very optimistic",
            "High retail interest"
        ],
        "approach": "Back-through-open, buy above PM high, trend to HOD"
    },
    8: {
        "name": "Double Beat with Guidance",
        "characteristics": [
            "Positive expectations",
            "Analyst consensus for good report",
            "Media coverage positive",
            "Stock already run up ahead of earnings"
        ],
        "approach": "Gap Give and Go, directional bias, fade dips"
    },
    7: {
        "name": "Double Beat (Inline)",
        "characteristics": [
            "Slightly positive expectations",
            "Consensus for beat",
            "Not much hype yet",
            "Stock moved up a little"
        ],
        "approach": "Limited - only if trade 'falls in lap'"
    },
    6: {
        "name": "Slight Beat",
        "characteristics": [
            "Minimal surprise",
            "Analysts mostly correct",
            "Low volatility expected"
        ],
        "approach": "Avoid or fade extremes only"
    },
    5: {
        "name": "Neutral",
        "characteristics": [
            "Neutral expectations",
            "Mixed analyst consensus",
            "Not much media coverage",
            "Stock range-bound",
            "Low retail interest"
        ],
        "approach": "AVOID - high trap probability"
    },
    -5: {
        "name": "Neutral (Bearish Lean)",
        "characteristics": ["Same as neutral"],
        "approach": "AVOID"
    },
    -6: {
        "name": "Slight Miss",
        "characteristics": [
            "Minimal negative surprise",
            "Analysts mostly correct"
        ],
        "approach": "Avoid or fade extremes only"
    },
    -7: {
        "name": "Double Miss (Inline)",
        "characteristics": [
            "Slightly negative expectations",
            "Consensus for miss",
            "Not much hype yet",
            "Stock moved down a little"
        ],
        "approach": "Limited short opportunities"
    },
    -8: {
        "name": "Double Miss with Guidance",
        "characteristics": [
            "Negative expectations",
            "Analyst consensus for bad report",
            "Media coverage negative",
            "Stock already run down ahead of earnings"
        ],
        "approach": "Gap Pick and Roll, fade bounces"
    },
    -9: {
        "name": "Exponential Negative",
        "characteristics": [
            "Strongly negative expectations",
            "Analyst downgrades and bearish sentiment",
            "Media very pessimistic",
            "High retail pessimism",
            "Stock price likely at trough"
        ],
        "approach": "Short below PM low, trend to LOD"
    },
    -10: {
        "name": "Black Swan (Bearish)",
        "characteristics": [
            "Everything looks terrible",
            "Massive pessimism - everyone talking about it",
            "Expectations through the floor",
            "Stock price already reflects bad news"
        ],
        "approach": "Max conviction short, watch for capitulation bounce"
    }
}


def get_score_description(score: int) -> Dict:
    """Get human-readable description for a score"""
    # Round to nearest category
    if score > 0:
        rounded = min(10, max(5, score))
    elif score < 0:
        rounded = max(-10, min(-5, score))
    else:
        rounded = 5
    
    return SCORE_DESCRIPTIONS.get(rounded, SCORE_DESCRIPTIONS[5])


def format_score_for_display(score: EarningsScore) -> str:
    """Format earnings score for UI display"""
    desc = get_score_description(score.final_score)
    
    lines = [
        f"## {score.symbol} Earnings Score: {score.final_score:+d}",
        f"**{desc['name']}**",
        "",
        "### Base Score Breakdown:",
    ]
    
    for reason in score.base_score_reasoning:
        lines.append(f"- {reason}")
    
    if score.modifier_reasoning:
        lines.append("")
        lines.append("### Modifiers Applied:")
        for mod in score.modifier_reasoning:
            lines.append(f"- {mod}")
    
    lines.append("")
    lines.append(f"### Trading Approach: **{score.trading_approach.value.upper()}**")
    
    if score.suggested_setups:
        lines.append(f"**Suggested Setups:** {', '.join(score.suggested_setups)}")
    
    if score.avoid_setups:
        lines.append(f"**Avoid:** {', '.join(score.avoid_setups)}")
    
    return "\n".join(lines)


# ==================== SERVICE CLASS ====================

class EarningsScoringService:
    """
    Service for scoring earnings catalysts and tracking historical scores.
    """
    
    def __init__(self, db=None):
        self.db = db
        self._scores_cache: Dict[str, EarningsScore] = {}
        
        if db is not None:
            self.scores_collection = db["earnings_scores"]
            self._load_recent_scores()
        else:
            self.scores_collection = None
        
        logger.info("📊 Earnings Scoring Service initialized")
    
    def _load_recent_scores(self):
        """Load recent scores from database"""
        if self.scores_collection is None:
            return
        
        try:
            # Load last 50 scores
            for doc in self.scores_collection.find().sort("scored_at", -1).limit(50):
                symbol = doc.get("symbol")
                if symbol:
                    self._scores_cache[symbol] = EarningsScore(
                        symbol=symbol,
                        base_score=doc.get("base_score", 0),
                        modifier_adjustment=doc.get("modifier_adjustment", 0),
                        final_score=doc.get("final_score", 0),
                        direction=doc.get("direction", "neutral"),
                        trading_approach=TradingApproach(doc.get("trading_approach", "avoid")),
                        suggested_setups=doc.get("suggested_setups", []),
                        scored_at=doc.get("scored_at", "")
                    )
            logger.info(f"Loaded {len(self._scores_cache)} cached earnings scores")
        except Exception as e:
            logger.warning(f"Could not load earnings scores: {e}")
    
    def score_earnings(
        self,
        data: EarningsData,
        management_track_record: str = "neutral",
        competitor_comparison: str = "similar",
        quarter_position: int = 1
    ) -> EarningsScore:
        """
        Score an earnings report and cache the result.
        """
        score = calculate_earnings_score(
            data=data,
            management_track_record=management_track_record,
            competitor_comparison=competitor_comparison,
            quarter_position=quarter_position
        )
        
        # Cache
        self._scores_cache[data.symbol] = score
        
        # Save to database
        if self.scores_collection is not None:
            try:
                self.scores_collection.update_one(
                    {"symbol": data.symbol, "report_date": data.report_date},
                    {"$set": score.to_dict()},
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Could not save earnings score: {e}")
        
        return score
    
    def get_cached_score(self, symbol: str) -> Optional[EarningsScore]:
        """Get cached score for a symbol"""
        return self._scores_cache.get(symbol)
    
    def get_trading_approach(self, symbol: str) -> TradingApproach:
        """Get trading approach for a symbol based on earnings"""
        score = self._scores_cache.get(symbol)
        if score:
            return score.trading_approach
        return TradingApproach.AVOID  # Default to avoid if unknown


# Singleton
_earnings_service: Optional[EarningsScoringService] = None


def get_earnings_service(db=None) -> EarningsScoringService:
    """Get or create earnings scoring service singleton"""
    global _earnings_service
    if _earnings_service is None:
        _earnings_service = EarningsScoringService(db)
    return _earnings_service
