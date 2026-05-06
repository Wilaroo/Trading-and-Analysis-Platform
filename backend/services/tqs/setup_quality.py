"""
Setup Quality Service - 25% of TQS Score

Evaluates the quality of the trade setup itself:
- Pattern clarity and strength
- Historical win rate for this setup
- Expected Value (EV) in R-multiples
- Tape reading confirmation
- SMB grade (A/B/C)
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SetupQualityScore:
    """Result of setup quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"  # A/B/C/D/F
    
    # Component scores (0-100 each)
    pattern_score: float = 50.0
    win_rate_score: float = 50.0
    ev_score: float = 50.0
    tape_score: float = 50.0
    smb_score: float = 50.0
    
    # Raw values
    win_rate: float = 0.5
    expected_value_r: float = 0.0
    tape_confirmation: bool = False
    smb_grade: str = "B"
    
    # Reasoning
    factors: list = None
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "pattern": round(self.pattern_score, 1),
                "win_rate": round(self.win_rate_score, 1),
                "expected_value": round(self.ev_score, 1),
                "tape": round(self.tape_score, 1),
                "smb": round(self.smb_score, 1)
            },
            "raw_values": {
                "win_rate": round(self.win_rate, 3),
                "expected_value_r": round(self.expected_value_r, 2),
                "tape_confirmation": self.tape_confirmation,
                "smb_grade": self.smb_grade
            },
            "factors": self.factors
        }


class SetupQualityService:
    """Evaluates setup quality - 25% of TQS"""
    
    # Setup type quality rankings (based on SMB methodology)
    SETUP_BASE_SCORES = {
        # Tier 1 - High probability setups
        "first_vwap_pullback": 85,
        "opening_drive": 80,
        "orb": 80,  # Opening Range Breakout
        "bull_flag": 78,
        "bear_flag": 78,
        "vwap_bounce": 75,
        "vwap_fade": 75,
        
        # Tier 2 - Solid setups
        "rubber_band": 72,
        "breakout": 70,
        "squeeze": 70,
        "gap_and_go": 68,
        "gap_fade": 68,
        "hitchhiker": 68,
        "second_chance": 65,
        
        # Tier 3 - Context dependent
        "mean_reversion": 62,
        "relative_strength": 60,
        "hod_breakout": 60,
        "range_break": 58,
        "pennant": 58,
        "triangle": 55,
        
        # Tier 4 - Lower probability
        "wedge": 52,
        "double_bottom": 50,
        "double_top": 50,
        "head_shoulders": 48,
        
        # Default
        "unknown": 50
    }
    
    def __init__(self):
        self._learning_loop = None
        self._scanner = None
        
    def set_services(self, learning_loop=None, scanner=None):
        """Wire up dependencies"""
        self._learning_loop = learning_loop
        self._scanner = scanner
        
    async def calculate_score(
        self,
        setup_type: str,
        symbol: str,
        tape_score: float = 0.0,
        tape_confirmation: bool = False,
        smb_grade: str = "B",
        smb_5var_score: int = 25,
        risk_reward: float = 2.0,
        alert_priority: str = "medium"
    ) -> SetupQualityScore:
        """
        Calculate setup quality score (0-100).
        
        Components:
        - Pattern base score (20%): Inherent setup quality
        - Historical win rate (25%): Your actual performance
        - Expected Value (20%): Risk-adjusted return
        - Tape confirmation (20%): Order flow support
        - SMB grade (15%): Overall setup grade
        """
        result = SetupQualityScore()
        result.tape_confirmation = tape_confirmation
        result.smb_grade = smb_grade
        
        # 1. Pattern Base Score (20% weight)
        base_setup = setup_type.lower().replace("_long", "").replace("_short", "")
        pattern_base = self.SETUP_BASE_SCORES.get(base_setup, 50)
        result.pattern_score = pattern_base
        
        if pattern_base >= 75:
            result.factors.append(f"High-quality {base_setup} pattern (+)")
        elif pattern_base < 55:
            result.factors.append(f"Lower probability {base_setup} setup (-)")
            
        # 2. Historical Win Rate Score (25% weight)
        win_rate = 0.5  # Default
        ev_r = 0.0
        
        if self._learning_loop:
            try:
                stats = await self._learning_loop.get_contextual_win_rate(setup_type=base_setup)
                if stats.get("sample_size", 0) >= 5:
                    win_rate = stats.get("win_rate", 0.5)
                    ev_r = stats.get("expected_value_r", 0.0)
            except Exception as e:
                logger.debug(f"Could not get learning stats: {e}")
                
        result.win_rate = win_rate
        result.expected_value_r = ev_r
        
        # Convert win rate to score (40% = 0, 50% = 50, 60% = 75, 70%+ = 100)
        if win_rate >= 0.70:
            result.win_rate_score = 100
            result.factors.append(f"Excellent win rate: {win_rate*100:.0f}% (++)")
        elif win_rate >= 0.60:
            result.win_rate_score = 75 + (win_rate - 0.60) * 250
            result.factors.append(f"Good win rate: {win_rate*100:.0f}% (+)")
        elif win_rate >= 0.50:
            result.win_rate_score = 50 + (win_rate - 0.50) * 250
        elif win_rate >= 0.40:
            result.win_rate_score = (win_rate - 0.40) * 500
            result.factors.append(f"Below average win rate: {win_rate*100:.0f}% (-)")
        else:
            result.win_rate_score = 0
            result.factors.append(f"Poor win rate: {win_rate*100:.0f}% (--)")
            
        # 3. Expected Value Score (20% weight)
        # EV of 0.5R+ is good, 1R+ is excellent
        if ev_r >= 1.0:
            result.ev_score = 100
            result.factors.append(f"Excellent EV: {ev_r:.2f}R (++)")
        elif ev_r >= 0.5:
            result.ev_score = 70 + (ev_r - 0.5) * 60
            result.factors.append(f"Positive EV: {ev_r:.2f}R (+)")
        elif ev_r >= 0.2:
            result.ev_score = 50 + (ev_r - 0.2) * 66.67
        elif ev_r >= 0:
            result.ev_score = 30 + ev_r * 100
        else:
            result.ev_score = max(0, 30 + ev_r * 30)
            result.factors.append(f"Negative EV: {ev_r:.2f}R (-)")
            
        # 4. Tape Confirmation Score (20% weight)
        # tape_score is typically 0-10 from scanner
        normalized_tape = min(tape_score / 10.0, 1.0) * 100 if tape_score > 0 else 30
        
        if tape_confirmation:
            result.tape_score = max(normalized_tape, 80)
            result.factors.append("Tape reading confirms setup (+)")
        else:
            result.tape_score = min(normalized_tape, 60)
            if tape_score < 4:
                result.factors.append("Weak tape reading (-)")
                
        # 5. SMB Grade Score (15% weight)
        smb_grade_scores = {"A+": 100, "A": 95, "B+": 80, "B": 65, "C+": 50, "C": 35, "D": 20, "F": 0}
        result.smb_score = smb_grade_scores.get(smb_grade, 65)
        
        # Also factor in 5-variable score (0-50 scale)
        if smb_5var_score >= 40:
            result.smb_score = min(100, result.smb_score + 15)
            result.factors.append(f"Strong SMB 5-var score: {smb_5var_score}/50 (+)")
        elif smb_5var_score < 20:
            result.smb_score = max(0, result.smb_score - 15)
            result.factors.append(f"Weak SMB 5-var score: {smb_5var_score}/50 (-)")
            
        # Bonus for alert priority
        if alert_priority == "critical":
            result.pattern_score = min(100, result.pattern_score + 10)
            result.factors.append("Critical priority alert (+)")
        elif alert_priority == "high":
            result.pattern_score = min(100, result.pattern_score + 5)
            
        # R:R bonus
        if risk_reward >= 3.0:
            result.ev_score = min(100, result.ev_score + 10)
            result.factors.append(f"Excellent R:R of {risk_reward:.1f}:1 (+)")
        elif risk_reward < 1.5:
            result.ev_score = max(0, result.ev_score - 10)
            result.factors.append(f"Poor R:R of {risk_reward:.1f}:1 (-)")
            
        # Calculate weighted total
        result.score = (
            result.pattern_score * 0.20 +
            result.win_rate_score * 0.25 +
            result.ev_score * 0.20 +
            result.tape_score * 0.20 +
            result.smb_score * 0.15
        )
        
        # Assign grade
        if result.score >= 85:
            result.grade = "A"
        elif result.score >= 75:
            result.grade = "B+"
        elif result.score >= 65:
            result.grade = "B"
        elif result.score >= 55:
            result.grade = "C+"
        elif result.score >= 45:
            result.grade = "C"
        elif result.score >= 35:
            result.grade = "D"
        else:
            result.grade = "F"
            
        return result


# Singleton
_setup_quality_service: Optional[SetupQualityService] = None


def get_setup_quality_service() -> SetupQualityService:
    global _setup_quality_service
    if _setup_quality_service is None:
        _setup_quality_service = SetupQualityService()
    return _setup_quality_service
