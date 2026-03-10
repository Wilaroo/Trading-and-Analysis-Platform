"""
TQS Engine - Trade Quality Score Master Service

Combines all 5 quality pillars into a unified 0-100 score:
- Setup Quality (25%): Pattern, win rate, EV, tape confirmation
- Technical Quality (25%): Trend, RSI, S/R, volatility, volume
- Fundamental Quality (15%): Catalyst, SI, float, institutional
- Context Quality (20%): Regime, time, sector, VIX
- Execution Quality (15%): Your history, tilt, tendencies

The TQS provides:
1. A single score to quickly assess any trade idea
2. Detailed breakdown by pillar for deep analysis
3. Specific factors and warnings
4. Grade-based recommendations
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.tqs.setup_quality import SetupQualityService, SetupQualityScore, get_setup_quality_service
from services.tqs.technical_quality import TechnicalQualityService, TechnicalQualityScore, get_technical_quality_service
from services.tqs.fundamental_quality import FundamentalQualityService, FundamentalQualityScore, get_fundamental_quality_service
from services.tqs.context_quality import ContextQualityService, ContextQualityScore, get_context_quality_service
from services.tqs.execution_quality import ExecutionQualityService, ExecutionQualityScore, get_execution_quality_service

logger = logging.getLogger(__name__)


@dataclass
class TQSResult:
    """Complete Trade Quality Score result"""
    # Overall
    score: float = 50.0  # 0-100
    grade: str = "C"
    action: str = "HOLD"  # STRONG_BUY, BUY, HOLD, AVOID, STRONG_AVOID
    
    # Pillar scores
    setup_score: SetupQualityScore = None
    technical_score: TechnicalQualityScore = None
    fundamental_score: FundamentalQualityScore = None
    context_score: ContextQualityScore = None
    execution_score: ExecutionQualityScore = None
    
    # Quick reference
    pillar_grades: Dict[str, str] = field(default_factory=dict)
    
    # Combined insights
    key_factors: List[str] = field(default_factory=list)  # Top positive factors
    concerns: List[str] = field(default_factory=list)     # Top negative factors
    warnings: List[str] = field(default_factory=list)     # Critical warnings
    
    # Metadata
    symbol: str = ""
    setup_type: str = ""
    direction: str = "long"
    calculated_at: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "action": self.action,
            "symbol": self.symbol,
            "setup_type": self.setup_type,
            "direction": self.direction,
            "pillar_scores": {
                "setup": round(self.setup_score.score, 1) if self.setup_score else 50,
                "technical": round(self.technical_score.score, 1) if self.technical_score else 50,
                "fundamental": round(self.fundamental_score.score, 1) if self.fundamental_score else 50,
                "context": round(self.context_score.score, 1) if self.context_score else 50,
                "execution": round(self.execution_score.score, 1) if self.execution_score else 50
            },
            "pillar_grades": self.pillar_grades,
            "breakdown": {
                "setup": self.setup_score.to_dict() if self.setup_score else None,
                "technical": self.technical_score.to_dict() if self.technical_score else None,
                "fundamental": self.fundamental_score.to_dict() if self.fundamental_score else None,
                "context": self.context_score.to_dict() if self.context_score else None,
                "execution": self.execution_score.to_dict() if self.execution_score else None
            },
            "key_factors": self.key_factors,
            "concerns": self.concerns,
            "warnings": self.warnings,
            "calculated_at": self.calculated_at
        }
        
    def to_summary(self) -> Dict:
        """Condensed version for quick display"""
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "action": self.action,
            "pillar_scores": {
                "setup": round(self.setup_score.score, 1) if self.setup_score else 50,
                "technical": round(self.technical_score.score, 1) if self.technical_score else 50,
                "fundamental": round(self.fundamental_score.score, 1) if self.fundamental_score else 50,
                "context": round(self.context_score.score, 1) if self.context_score else 50,
                "execution": round(self.execution_score.score, 1) if self.execution_score else 50
            },
            "top_factor": self.key_factors[0] if self.key_factors else None,
            "top_concern": self.concerns[0] if self.concerns else None,
            "has_warnings": len(self.warnings) > 0
        }


class TQSEngine:
    """
    Trade Quality Score Engine - Master scorer combining all 5 pillars.
    
    Weights:
    - Setup Quality: 25%
    - Technical Quality: 25%
    - Fundamental Quality: 15%
    - Context Quality: 20%
    - Execution Quality: 15%
    
    Total: 100%
    """
    
    # Pillar weights
    WEIGHTS = {
        "setup": 0.25,
        "technical": 0.25,
        "fundamental": 0.15,
        "context": 0.20,
        "execution": 0.15
    }
    
    # Action thresholds
    ACTION_THRESHOLDS = {
        "STRONG_BUY": 80,
        "BUY": 65,
        "HOLD": 50,
        "AVOID": 35,
        "STRONG_AVOID": 0
    }
    
    def __init__(self):
        self._setup_service = get_setup_quality_service()
        self._technical_service = get_technical_quality_service()
        self._fundamental_service = get_fundamental_quality_service()
        self._context_service = get_context_quality_service()
        self._execution_service = get_execution_quality_service()
        
        # External service dependencies
        self._learning_loop = None
        self._alpaca_service = None
        self._ib_service = None
        self._technical_analysis_service = None
        self._sector_service = None
        self._scanner = None
        
    def set_services(
        self,
        learning_loop=None,
        alpaca_service=None,
        ib_service=None,
        technical_service=None,
        sector_service=None,
        scanner=None
    ):
        """Wire up all dependencies"""
        self._learning_loop = learning_loop
        self._alpaca_service = alpaca_service
        self._ib_service = ib_service
        self._technical_analysis_service = technical_service
        self._sector_service = sector_service
        self._scanner = scanner
        
        # Wire up sub-services
        self._setup_service.set_services(
            learning_loop=learning_loop,
            scanner=scanner
        )
        self._technical_service.set_services(
            technical_service=technical_service,
            alpaca_service=alpaca_service
        )
        self._fundamental_service.set_services(
            ib_service=ib_service
        )
        self._context_service.set_services(
            alpaca_service=alpaca_service,
            sector_service=sector_service,
            ib_service=ib_service
        )
        self._execution_service.set_services(
            learning_loop=learning_loop
        )
        
    async def calculate_tqs(
        self,
        symbol: str,
        setup_type: str,
        direction: str = "long",
        # Optional pre-fetched data for performance
        tape_score: float = 0.0,
        tape_confirmation: bool = False,
        smb_grade: str = "B",
        smb_5var_score: int = 25,
        risk_reward: float = 2.0,
        alert_priority: str = "medium",
        # Context overrides
        market_regime: Optional[str] = None,
        time_of_day: Optional[str] = None,
        # Execution context
        planned_position_size: int = 100,
        account_value: float = 100000.0
    ) -> TQSResult:
        """
        Calculate complete Trade Quality Score for a trade idea.
        
        Returns a TQSResult with:
        - Overall score (0-100) and grade (A/B/C/D/F)
        - Action recommendation (STRONG_BUY/BUY/HOLD/AVOID/STRONG_AVOID)
        - Detailed breakdown by pillar
        - Key factors, concerns, and warnings
        """
        result = TQSResult()
        result.symbol = symbol
        result.setup_type = setup_type
        result.direction = direction
        result.calculated_at = datetime.now(timezone.utc).isoformat()
        
        try:
            # Calculate all 5 pillar scores (could parallelize these)
            
            # 1. Setup Quality (25%)
            result.setup_score = await self._setup_service.calculate_score(
                setup_type=setup_type,
                symbol=symbol,
                tape_score=tape_score,
                tape_confirmation=tape_confirmation,
                smb_grade=smb_grade,
                smb_5var_score=smb_5var_score,
                risk_reward=risk_reward,
                alert_priority=alert_priority
            )
            result.pillar_grades["setup"] = result.setup_score.grade
            
            # 2. Technical Quality (25%)
            result.technical_score = await self._technical_service.calculate_score(
                symbol=symbol,
                direction=direction,
                setup_type=setup_type
            )
            result.pillar_grades["technical"] = result.technical_score.grade
            
            # 3. Fundamental Quality (15%)
            result.fundamental_score = await self._fundamental_service.calculate_score(
                symbol=symbol,
                direction=direction
            )
            result.pillar_grades["fundamental"] = result.fundamental_score.grade
            
            # 4. Context Quality (20%)
            result.context_score = await self._context_service.calculate_score(
                symbol=symbol,
                direction=direction,
                setup_type=setup_type,
                market_regime=market_regime,
                time_of_day=time_of_day
            )
            result.pillar_grades["context"] = result.context_score.grade
            
            # 5. Execution Quality (15%)
            result.execution_score = await self._execution_service.calculate_score(
                symbol=symbol,
                setup_type=setup_type,
                direction=direction,
                planned_position_size=planned_position_size,
                account_value=account_value
            )
            result.pillar_grades["execution"] = result.execution_score.grade
            
            # Calculate weighted total
            result.score = (
                result.setup_score.score * self.WEIGHTS["setup"] +
                result.technical_score.score * self.WEIGHTS["technical"] +
                result.fundamental_score.score * self.WEIGHTS["fundamental"] +
                result.context_score.score * self.WEIGHTS["context"] +
                result.execution_score.score * self.WEIGHTS["execution"]
            )
            
            # Assign overall grade
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
                
            # Determine action
            if result.score >= self.ACTION_THRESHOLDS["STRONG_BUY"]:
                result.action = "STRONG_BUY"
            elif result.score >= self.ACTION_THRESHOLDS["BUY"]:
                result.action = "BUY"
            elif result.score >= self.ACTION_THRESHOLDS["HOLD"]:
                result.action = "HOLD"
            elif result.score >= self.ACTION_THRESHOLDS["AVOID"]:
                result.action = "AVOID"
            else:
                result.action = "STRONG_AVOID"
                
            # Collect key factors and concerns
            all_factors = []
            all_factors.extend(result.setup_score.factors)
            all_factors.extend(result.technical_score.factors)
            all_factors.extend(result.fundamental_score.factors)
            all_factors.extend(result.context_score.factors)
            all_factors.extend(result.execution_score.factors)
            
            # Separate positive and negative
            for factor in all_factors:
                if "(+)" in factor or "(++)" in factor:
                    result.key_factors.append(factor.replace("(+)", "").replace("(++)", "").strip())
                elif "(-)" in factor or "(--)" in factor:
                    result.concerns.append(factor.replace("(-)", "").replace("(--)", "").strip())
                    
            # Collect warnings (from execution primarily)
            result.warnings.extend(result.execution_score.warnings)
            
            # Override action if there are severe warnings
            if any("SEVERE" in w or "stepping away" in w.lower() for w in result.warnings):
                if result.action in ["STRONG_BUY", "BUY"]:
                    result.action = "HOLD"
                    result.concerns.insert(0, "Downgraded due to tilt - take a break")
                    
            logger.info(f"TQS calculated for {symbol} {setup_type}: {result.score:.1f} ({result.grade}) -> {result.action}")
            
        except Exception as e:
            logger.error(f"Error calculating TQS for {symbol}: {e}")
            # Return default scores on error
            result.concerns.append(f"Error calculating score: {str(e)}")
            
        return result
        
    async def batch_calculate(
        self,
        opportunities: List[Dict]
    ) -> List[TQSResult]:
        """
        Calculate TQS for multiple opportunities.
        
        Each opportunity dict should have:
        - symbol: str
        - setup_type: str
        - direction: str (optional, default "long")
        - Other optional parameters
        """
        results = []
        
        for opp in opportunities:
            try:
                result = await self.calculate_tqs(
                    symbol=opp.get("symbol", ""),
                    setup_type=opp.get("setup_type", "unknown"),
                    direction=opp.get("direction", "long"),
                    tape_score=opp.get("tape_score", 0),
                    tape_confirmation=opp.get("tape_confirmation", False),
                    smb_grade=opp.get("smb_grade", "B"),
                    smb_5var_score=opp.get("smb_5var_score", 25),
                    risk_reward=opp.get("risk_reward", 2.0),
                    alert_priority=opp.get("alert_priority", "medium")
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Error in batch TQS for {opp.get('symbol')}: {e}")
                # Create empty result with error
                error_result = TQSResult()
                error_result.symbol = opp.get("symbol", "")
                error_result.concerns.append(f"Error: {str(e)}")
                results.append(error_result)
                
        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        
        return results
        
    def get_threshold_guidance(self, score: float) -> Dict[str, Any]:
        """Get guidance on what a particular score means"""
        if score >= 80:
            return {
                "action": "STRONG_BUY",
                "confidence": "High",
                "sizing": "Full position (100%)",
                "guidance": "Excellent setup - all systems go. Execute with confidence."
            }
        elif score >= 65:
            return {
                "action": "BUY",
                "confidence": "Medium-High",
                "sizing": "Standard position (75-100%)",
                "guidance": "Good setup with some minor concerns. Proceed with normal risk management."
            }
        elif score >= 50:
            return {
                "action": "HOLD",
                "confidence": "Medium",
                "sizing": "Reduced position (50-75%)",
                "guidance": "Mixed signals. Consider waiting for better entry or reduced size."
            }
        elif score >= 35:
            return {
                "action": "AVOID",
                "confidence": "Low",
                "sizing": "Paper trade only",
                "guidance": "Below threshold. Multiple concerns. Skip unless conviction is very high."
            }
        else:
            return {
                "action": "STRONG_AVOID",
                "confidence": "Very Low",
                "sizing": "Do not trade",
                "guidance": "Poor setup. Do not trade. Wait for better opportunities."
            }


# Singleton
_tqs_engine: Optional[TQSEngine] = None


def get_tqs_engine() -> TQSEngine:
    """Get the singleton TQS engine"""
    global _tqs_engine
    if _tqs_engine is None:
        _tqs_engine = TQSEngine()
    return _tqs_engine


def init_tqs_engine(
    learning_loop=None,
    alpaca_service=None,
    ib_service=None,
    technical_service=None,
    sector_service=None,
    scanner=None
) -> TQSEngine:
    """Initialize the TQS engine with dependencies"""
    engine = get_tqs_engine()
    engine.set_services(
        learning_loop=learning_loop,
        alpaca_service=alpaca_service,
        ib_service=ib_service,
        technical_service=technical_service,
        sector_service=sector_service,
        scanner=scanner
    )
    return engine
