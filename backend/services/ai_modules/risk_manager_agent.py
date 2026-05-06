"""
AI Risk Manager Agent - Pre-Trade Risk Assessment

Institutional-style risk assessment that evaluates multiple factors
before allowing a trade to proceed.

Factors assessed:
- Position sizing appropriateness
- Portfolio correlation
- Volatility environment
- News/catalyst risk
- Regime fit
- Historical performance context
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class RiskFactor:
    """A single risk factor assessment"""
    name: str = ""
    score: float = 0.0  # 0-10 (0=no risk, 10=extreme risk)
    weight: float = 1.0
    description: str = ""
    recommendation: str = ""


@dataclass
class RiskAssessment:
    """Complete risk assessment for a trade"""
    symbol: str = ""
    direction: str = ""
    
    # Individual factors
    factors: List[Dict] = field(default_factory=list)
    
    # Overall assessment
    total_risk_score: float = 0.0  # 0-10
    risk_level: str = ""  # "low", "moderate", "high", "extreme"
    
    # Recommendation
    recommendation: str = ""  # "proceed", "reduce_size", "pass", "block"
    size_adjustment: float = 1.0  # Multiplier (e.g., 0.5 = half size)
    reasoning: str = ""
    
    # Warnings
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)  # Hard stops
    
    # Metadata
    timestamp: str = ""
    assessment_time_ms: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class AIRiskManager:
    """
    Pre-trade risk assessment using multiple factors.
    
    Unlike simple rule-based checks, this provides a holistic
    risk view similar to institutional risk management.
    """
    
    # Risk thresholds
    LOW_RISK_MAX = 3.0
    MODERATE_RISK_MAX = 5.0
    HIGH_RISK_MAX = 7.0
    # Above 7.0 = extreme
    
    # Factor weights (must sum to 1.0)
    DEFAULT_WEIGHTS = {
        "position_sizing": 0.20,
        "correlation": 0.15,
        "volatility": 0.20,
        "news_risk": 0.15,
        "regime_fit": 0.15,
        "historical": 0.15
    }
    
    def __init__(self, config: Dict = None):
        self._config = config or {
            "max_risk_score": 7,
            "block_on_high_risk": True,
            "factors": list(self.DEFAULT_WEIGHTS.keys()),
            "weights": self.DEFAULT_WEIGHTS.copy()
        }
        self._portfolio_service = None
        self._learning_provider = None
        self._news_service = None
        
    def set_services(
        self,
        portfolio_service=None,
        learning_provider=None,
        news_service=None
    ):
        """Inject service dependencies"""
        self._portfolio_service = portfolio_service
        self._learning_provider = learning_provider
        self._news_service = news_service
        
    async def assess_risk(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        target_price: float,
        position_size_shares: int,
        account_value: float,
        setup: Dict,
        market_context: Dict,
        portfolio: Dict = None
    ) -> RiskAssessment:
        """
        Perform comprehensive risk assessment.
        """
        import time
        start_time = time.time()
        
        factors = []
        warnings = []
        blockers = []
        
        # Factor 1: Position Sizing Risk
        sizing_factor = self._assess_position_sizing(
            entry_price, stop_price, position_size_shares, account_value
        )
        factors.append(sizing_factor)
        if sizing_factor["score"] >= 8:
            blockers.append(sizing_factor["description"])
        elif sizing_factor["score"] >= 6:
            warnings.append(sizing_factor["description"])
            
        # Factor 2: Correlation Risk
        correlation_factor = await self._assess_correlation(
            symbol, direction, portfolio
        )
        factors.append(correlation_factor)
        if correlation_factor["score"] >= 7:
            warnings.append(correlation_factor["description"])
            
        # Factor 3: Volatility Risk
        volatility_factor = self._assess_volatility(
            symbol, market_context, setup
        )
        factors.append(volatility_factor)
        if volatility_factor["score"] >= 8:
            blockers.append("Extreme volatility - trading halted")
        elif volatility_factor["score"] >= 6:
            warnings.append(volatility_factor["description"])
            
        # Factor 4: News/Catalyst Risk
        news_factor = await self._assess_news_risk(
            symbol, setup
        )
        factors.append(news_factor)
        if news_factor["score"] >= 8:
            warnings.append("Major catalyst imminent - binary risk")
            
        # Factor 5: Regime Fit
        regime_factor = self._assess_regime_fit(
            direction, market_context, setup
        )
        factors.append(regime_factor)
        if regime_factor["score"] >= 7:
            warnings.append(regime_factor["description"])
            
        # Factor 6: Historical Performance
        historical_factor = await self._assess_historical(
            symbol, setup
        )
        factors.append(historical_factor)
        if historical_factor["score"] >= 7:
            warnings.append(historical_factor["description"])
            
        # Calculate weighted total
        weights = self._config.get("weights", self.DEFAULT_WEIGHTS)
        total_score = 0.0
        total_weight = 0.0
        
        for factor in factors:
            weight = weights.get(factor["name"], 0.1)
            total_score += factor["score"] * weight
            total_weight += weight
            
        if total_weight > 0:
            total_score = total_score / total_weight
        total_score = round(total_score, 1)
        
        # Determine risk level
        if total_score <= self.LOW_RISK_MAX:
            risk_level = "low"
        elif total_score <= self.MODERATE_RISK_MAX:
            risk_level = "moderate"
        elif total_score <= self.HIGH_RISK_MAX:
            risk_level = "high"
        else:
            risk_level = "extreme"
            
        # Determine recommendation
        recommendation, size_adjustment, reasoning = self._make_recommendation(
            total_score, risk_level, blockers, warnings, factors
        )
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        assessment = RiskAssessment(
            symbol=symbol.upper(),
            direction=direction,
            factors=factors,
            total_risk_score=total_score,
            risk_level=risk_level,
            recommendation=recommendation,
            size_adjustment=size_adjustment,
            reasoning=reasoning,
            warnings=warnings,
            blockers=blockers,
            timestamp=datetime.now(timezone.utc).isoformat(),
            assessment_time_ms=elapsed_ms
        )
        
        logger.info(
            f"Risk Assessment {symbol}: score={total_score}, level={risk_level}, "
            f"recommendation={recommendation}"
        )
        
        return assessment
        
    def _assess_position_sizing(
        self,
        entry_price: float,
        stop_price: float,
        shares: int,
        account_value: float
    ) -> Dict:
        """Assess position sizing risk"""
        risk_per_share = abs(entry_price - stop_price)
        total_risk = risk_per_share * shares
        risk_pct = (total_risk / account_value * 100) if account_value > 0 else 10
        
        position_value = entry_price * shares
        position_pct = (position_value / account_value * 100) if account_value > 0 else 100
        
        # Score calculation
        score = 0
        description = ""
        recommendation = ""
        
        # Risk percentage scoring
        if risk_pct > 3:
            score = 9
            description = f"Risk {risk_pct:.1f}% exceeds 3% max"
            recommendation = "Reduce position size significantly"
        elif risk_pct > 2:
            score = 7
            description = f"Risk {risk_pct:.1f}% is elevated"
            recommendation = "Consider reducing size"
        elif risk_pct > 1:
            score = 4
            description = f"Risk {risk_pct:.1f}% is acceptable"
            recommendation = "Position size appropriate"
        else:
            score = 2
            description = f"Risk {risk_pct:.1f}% is conservative"
            recommendation = "Could increase size if confident"
            
        # Position concentration penalty
        if position_pct > 20:
            score = min(10, score + 2)
            description += f". Position {position_pct:.0f}% of account"
            
        return {
            "name": "position_sizing",
            "score": min(10, score),
            "description": description,
            "recommendation": recommendation,
            "metrics": {
                "risk_pct": round(risk_pct, 2),
                "position_pct": round(position_pct, 2)
            }
        }
        
    async def _assess_correlation(
        self,
        symbol: str,
        direction: str,
        portfolio: Dict
    ) -> Dict:
        """Assess portfolio correlation risk"""
        if not portfolio:
            return {
                "name": "correlation",
                "score": 3,
                "description": "No portfolio data - assuming moderate correlation risk",
                "recommendation": "Monitor sector exposure"
            }
            
        open_positions = portfolio.get("positions", [])
        
        # Check if adding to existing position
        for pos in open_positions:
            if pos.get("symbol", "").upper() == symbol.upper():
                return {
                    "name": "correlation",
                    "score": 8,
                    "description": f"Already have position in {symbol}",
                    "recommendation": "Avoid doubling down or scale out first"
                }
                
        # Check sector concentration
        # Would need sector lookup service - using placeholder
        num_positions = len(open_positions)
        
        if num_positions >= 8:
            score = 7
            description = f"Already at {num_positions} positions - high concentration"
        elif num_positions >= 5:
            score = 5
            description = f"{num_positions} open positions - moderate concentration"
        else:
            score = 2
            description = f"{num_positions} positions - diversification ok"
            
        return {
            "name": "correlation",
            "score": score,
            "description": description,
            "recommendation": "Consider sector balance"
        }
        
    def _assess_volatility(
        self,
        symbol: str,
        market_context: Dict,
        setup: Dict
    ) -> Dict:
        """Assess volatility risk"""
        vix = market_context.get("vix", 15) or 15
        atr_pct = setup.get("atr_pct", 2) or 2
        
        # VIX scoring
        if vix > 35:
            vix_score = 9
            vix_desc = f"VIX {vix:.1f} - extreme fear"
        elif vix > 25:
            vix_score = 7
            vix_desc = f"VIX {vix:.1f} - elevated volatility"
        elif vix > 20:
            vix_score = 5
            vix_desc = f"VIX {vix:.1f} - above average"
        else:
            vix_score = 2
            vix_desc = f"VIX {vix:.1f} - normal"
            
        # ATR scoring
        if atr_pct > 5:
            atr_score = 8
        elif atr_pct > 3:
            atr_score = 5
        else:
            atr_score = 2
            
        # Combined score
        score = (vix_score * 0.6) + (atr_score * 0.4)
        
        recommendation = "Normal volatility conditions"
        if score >= 7:
            recommendation = "Widen stops or reduce size"
        elif score >= 5:
            recommendation = "Be prepared for larger swings"
            
        return {
            "name": "volatility",
            "score": round(score, 1),
            "description": vix_desc,
            "recommendation": recommendation,
            "metrics": {"vix": vix, "atr_pct": atr_pct}
        }
        
    async def _assess_news_risk(
        self,
        symbol: str,
        setup: Dict
    ) -> Dict:
        """Assess news and catalyst risk"""
        has_earnings = setup.get("earnings_pending", False)
        has_news = setup.get("pending_news", False) or setup.get("has_catalyst", False)
        
        score = 2  # Default low risk
        description = "No significant catalysts"
        recommendation = "Monitor for news"
        
        if has_earnings:
            score = 8
            description = "Earnings pending - binary event risk"
            recommendation = "Exit before earnings or reduce size"
        elif has_news:
            score = 5
            description = "Potential catalyst ahead"
            recommendation = "Stay alert for news"
            
        return {
            "name": "news_risk",
            "score": score,
            "description": description,
            "recommendation": recommendation
        }
        
    def _assess_regime_fit(
        self,
        direction: str,
        market_context: Dict,
        setup: Dict
    ) -> Dict:
        """Assess how well trade fits current market regime"""
        regime = market_context.get("regime", "NEUTRAL")
        trend = market_context.get("trend", "neutral").lower()
        
        score = 3  # Neutral default
        description = "Trade aligns with market conditions"
        
        # Risk-off regime penalties
        if regime == "RISK_OFF":
            if direction == "long":
                score = 7
                description = "Long in risk-off regime - fighting the tape"
            else:
                score = 3
                description = "Short aligns with risk-off regime"
        elif regime == "RISK_ON":
            if direction == "long":
                score = 2
                description = "Long in risk-on regime - favorable"
            else:
                score = 5
                description = "Short against risk-on trend - proceed carefully"
                
        # Trend alignment
        if direction == "long" and trend == "bearish":
            score = min(10, score + 2)
            description += ". Counter-trend trade."
        elif direction == "short" and trend == "bullish":
            score = min(10, score + 2)
            description += ". Counter-trend trade."
            
        return {
            "name": "regime_fit",
            "score": score,
            "description": description,
            "recommendation": "Consider regime in sizing"
        }
        
    async def _assess_historical(
        self,
        symbol: str,
        setup: Dict
    ) -> Dict:
        """Assess based on historical performance"""
        historical_wr = setup.get("historical_win_rate", 0.5)
        
        # Win rate scoring
        if historical_wr < 0.35:
            score = 8
            description = f"Poor historical win rate ({historical_wr*100:.0f}%)"
            recommendation = "Consider skipping this setup type"
        elif historical_wr < 0.45:
            score = 6
            description = f"Below average win rate ({historical_wr*100:.0f}%)"
            recommendation = "Require higher quality signals"
        elif historical_wr > 0.60:
            score = 2
            description = f"Strong historical edge ({historical_wr*100:.0f}%)"
            recommendation = "Setup type is working well"
        else:
            score = 4
            description = f"Average win rate ({historical_wr*100:.0f}%)"
            recommendation = "Standard position sizing"
            
        return {
            "name": "historical",
            "score": score,
            "description": description,
            "recommendation": recommendation
        }
        
    def _make_recommendation(
        self,
        total_score: float,
        risk_level: str,
        blockers: List[str],
        warnings: List[str],
        factors: List[Dict]
    ) -> tuple:
        """
        Make final recommendation based on assessment.
        
        Returns: (recommendation, size_adjustment, reasoning)
        """
        # Hard blockers
        if blockers:
            return (
                "block",
                0.0,
                f"BLOCKED: {blockers[0]}"
            )
            
        # Risk-based recommendations
        if risk_level == "extreme":
            if self._config.get("block_on_high_risk", True):
                return (
                    "block",
                    0.0,
                    f"Risk score {total_score}/10 exceeds threshold. Too risky to proceed."
                )
            else:
                return (
                    "reduce_size",
                    0.25,
                    f"Extreme risk ({total_score}/10). Reduced to 25% size."
                )
                
        elif risk_level == "high":
            return (
                "reduce_size",
                0.5,
                f"High risk ({total_score}/10). Recommended 50% size. {'; '.join(warnings[:2])}"
            )
            
        elif risk_level == "moderate":
            if warnings:
                return (
                    "proceed",
                    0.75,
                    f"Moderate risk ({total_score}/10). Consider 75% size. Watch: {warnings[0]}"
                )
            return (
                "proceed",
                1.0,
                f"Moderate risk ({total_score}/10). Standard position size acceptable."
            )
            
        else:  # low risk
            return (
                "proceed",
                1.0,
                f"Low risk ({total_score}/10). Full position size approved."
            )
            
    def update_config(self, config: Dict):
        """Update risk manager configuration"""
        self._config.update(config)


# Singleton
_ai_risk_manager: Optional[AIRiskManager] = None


def get_ai_risk_manager() -> AIRiskManager:
    """Get singleton instance"""
    global _ai_risk_manager
    if _ai_risk_manager is None:
        _ai_risk_manager = AIRiskManager()
    return _ai_risk_manager


def init_ai_risk_manager(config: Dict = None, **services) -> AIRiskManager:
    """Initialize AI Risk Manager with dependencies"""
    manager = get_ai_risk_manager()
    if config:
        manager.update_config(config)
    manager.set_services(**services)
    return manager
