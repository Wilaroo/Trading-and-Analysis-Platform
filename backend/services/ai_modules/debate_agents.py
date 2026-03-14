"""
Bull/Bear Debate Agents - Multi-Agent Trade Deliberation

Implements institutional-style "red team" analysis where AI agents
argue opposing viewpoints before trade decisions.

Bull Agent: Argues for the trade opportunity
Bear Agent: Argues against / identifies risks
Arbiter: Synthesizes debate and makes recommendation
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class DebateResult:
    """Result of a bull/bear debate"""
    symbol: str = ""
    setup_type: str = ""
    direction: str = ""  # "long" or "short"
    
    # Bull's case
    bull_score: float = 0.0  # 0-1
    bull_arguments: List[str] = field(default_factory=list)
    bull_confidence: float = 0.0
    
    # Bear's case  
    bear_score: float = 0.0  # 0-1
    bear_arguments: List[str] = field(default_factory=list)
    bear_confidence: float = 0.0
    
    # Arbiter's verdict
    winner: str = ""  # "bull", "bear", "tie"
    final_recommendation: str = ""  # "proceed", "pass", "reduce_size"
    reasoning: str = ""
    combined_confidence: float = 0.0
    
    # Metadata
    debate_rounds: int = 0
    debate_time_ms: int = 0
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class BullAgent:
    """
    The Bull Agent - Argues FOR the trade opportunity.
    
    Focuses on:
    - Technical setup strength
    - Favorable conditions
    - Risk/reward attractiveness
    - Momentum and trend alignment
    """
    
    def __init__(self, llm_service=None):
        self._llm = llm_service
        
    async def make_case(
        self,
        symbol: str,
        setup: Dict,
        market_context: Dict,
        technical_data: Dict
    ) -> Dict[str, Any]:
        """
        Build the bullish case for this trade.
        """
        arguments = []
        score = 0.0
        factors = 0
        
        # Factor 1: Technical Setup Quality
        tqs_score = setup.get("tqs_score", 0) or setup.get("quality_score", 0)
        if tqs_score >= 70:
            arguments.append(f"Strong setup quality (TQS: {tqs_score})")
            score += 0.2
        elif tqs_score >= 60:
            arguments.append(f"Acceptable setup quality (TQS: {tqs_score})")
            score += 0.1
        factors += 1
        
        # Factor 2: Risk/Reward
        rr_ratio = setup.get("risk_reward", 0)
        if rr_ratio >= 3:
            arguments.append(f"Excellent risk/reward ratio ({rr_ratio:.1f}:1)")
            score += 0.25
        elif rr_ratio >= 2:
            arguments.append(f"Good risk/reward ratio ({rr_ratio:.1f}:1)")
            score += 0.15
        factors += 1
        
        # Factor 3: Trend Alignment
        trend = market_context.get("trend", "").lower()
        direction = setup.get("direction", "long")
        if (trend == "bullish" and direction == "long") or (trend == "bearish" and direction == "short"):
            arguments.append(f"Trade aligns with {trend} market trend")
            score += 0.15
        factors += 1
        
        # Factor 4: Volume Confirmation
        rvol = technical_data.get("rvol", 1.0) or technical_data.get("relative_volume", 1.0)
        if rvol >= 1.5:
            arguments.append(f"Strong volume confirmation (RVOL: {rvol:.1f}x)")
            score += 0.15
        elif rvol >= 1.0:
            arguments.append(f"Adequate volume (RVOL: {rvol:.1f}x)")
            score += 0.05
        factors += 1
        
        # Factor 5: Regime Fit
        regime = market_context.get("regime", "UNKNOWN")
        if regime == "RISK_ON":
            arguments.append("Risk-on regime favors taking quality setups")
            score += 0.1
        elif regime == "NEUTRAL":
            arguments.append("Neutral regime allows selective trading")
            score += 0.05
        factors += 1
        
        # Factor 6: Setup-specific strengths
        confirmations = setup.get("confirmations", [])
        if len(confirmations) >= 3:
            arguments.append(f"Multiple confirmations present ({len(confirmations)})")
            score += 0.1
        factors += 1
        
        # Factor 7: Near key level
        distance_to_entry = setup.get("distance_to_entry_pct", 0)
        if distance_to_entry is not None and 0 < distance_to_entry < 1:
            arguments.append(f"Price near entry zone ({distance_to_entry:.1f}%)")
            score += 0.05
        factors += 1
        
        # Normalize score to 0-1
        max_possible = factors * 0.2  # Approximate max
        normalized_score = min(1.0, score / max_possible) if max_possible > 0 else 0
        
        # Calculate confidence based on argument strength
        confidence = min(1.0, len([a for a in arguments if "strong" in a.lower() or "excellent" in a.lower()]) * 0.2 + 0.4)
        
        return {
            "score": round(normalized_score, 2),
            "arguments": arguments,
            "confidence": round(confidence, 2)
        }


class BearAgent:
    """
    The Bear Agent - Argues AGAINST the trade opportunity.
    
    Focuses on:
    - Risk factors and red flags
    - Unfavorable conditions
    - Historical failure patterns
    - Overexposure concerns
    """
    
    def __init__(self, llm_service=None, learning_provider=None):
        self._llm = llm_service
        self._learning = learning_provider
        
    async def make_case(
        self,
        symbol: str,
        setup: Dict,
        market_context: Dict,
        technical_data: Dict,
        portfolio: Dict = None
    ) -> Dict[str, Any]:
        """
        Build the bearish case against this trade.
        """
        arguments = []
        score = 0.0
        factors = 0
        
        # Factor 1: Regime Risk
        regime = market_context.get("regime", "UNKNOWN")
        if regime == "RISK_OFF":
            arguments.append("Risk-off regime - reduced edge on new trades")
            score += 0.25
        factors += 1
        
        # Factor 2: VIX/Volatility Risk
        vix = market_context.get("vix", 0) or technical_data.get("vix", 0)
        if vix and vix > 25:
            arguments.append(f"Elevated VIX ({vix:.1f}) increases stop-out risk")
            score += 0.2
        elif vix and vix > 20:
            arguments.append(f"VIX above comfort zone ({vix:.1f})")
            score += 0.1
        factors += 1
        
        # Factor 3: Setup Weakness
        tqs_score = setup.get("tqs_score", 0) or setup.get("quality_score", 0)
        if tqs_score < 55:
            arguments.append(f"Below-average setup quality (TQS: {tqs_score})")
            score += 0.2
        factors += 1
        
        # Factor 4: Historical Win Rate Concern
        historical_wr = setup.get("historical_win_rate", 0.5)
        if historical_wr < 0.45:
            arguments.append(f"Poor historical win rate on this setup ({historical_wr*100:.0f}%)")
            score += 0.25
        elif historical_wr < 0.5:
            arguments.append(f"Below-average win rate historically ({historical_wr*100:.0f}%)")
            score += 0.1
        factors += 1
        
        # Factor 5: Portfolio Concentration
        if portfolio:
            sector = setup.get("sector", "")
            sector_exposure = portfolio.get("sector_exposure", {}).get(sector, 0)
            if sector_exposure > 0.3:
                arguments.append(f"High sector concentration ({sector}: {sector_exposure*100:.0f}%)")
                score += 0.15
                
            # Position count
            open_positions = portfolio.get("open_positions", 0)
            max_positions = portfolio.get("max_positions", 5)
            if open_positions >= max_positions - 1:
                arguments.append(f"Near position limit ({open_positions}/{max_positions})")
                score += 0.1
        factors += 1
        
        # Factor 6: Time of Day Risk
        session = market_context.get("session", "")
        if session in ["pre_market", "post_market"]:
            arguments.append("Extended hours trading increases risk")
            score += 0.15
        elif session == "power_hour":
            arguments.append("Power hour volatility can whipsaw stops")
            score += 0.05
        factors += 1
        
        # Factor 7: News/Catalyst Risk
        has_news = setup.get("has_pending_news", False) or setup.get("earnings_pending", False)
        if has_news:
            arguments.append("Pending news/earnings creates binary risk")
            score += 0.2
        factors += 1
        
        # Factor 8: Poor R:R
        rr_ratio = setup.get("risk_reward", 2)
        if rr_ratio < 1.5:
            arguments.append(f"Insufficient risk/reward ({rr_ratio:.1f}:1)")
            score += 0.2
        factors += 1
        
        # Normalize
        max_possible = factors * 0.2
        normalized_score = min(1.0, score / max_possible) if max_possible > 0 else 0
        
        # Confidence based on number of significant concerns
        major_concerns = len([a for a in arguments if "poor" in a.lower() or "high" in a.lower() or "risk" in a.lower()])
        confidence = min(1.0, major_concerns * 0.15 + 0.3)
        
        return {
            "score": round(normalized_score, 2),
            "arguments": arguments,
            "confidence": round(confidence, 2),
            "major_concerns": major_concerns
        }


class ArbiterAgent:
    """
    The Arbiter - Synthesizes bull/bear debate and makes final recommendation.
    
    Uses configurable thresholds to determine:
    - Whether to proceed with trade
    - Whether to reduce size
    - Whether to pass entirely
    """
    
    def __init__(self, config: Dict = None):
        self._config = config or {
            "min_bull_score": 0.4,
            "min_bear_score": 0.4,
            "require_consensus": False,
            "bull_margin_to_proceed": 0.15,  # Bull must lead by this much
            "bear_margin_to_pass": 0.2  # Bear must lead by this much to pass
        }
        
    def arbitrate(
        self,
        bull_case: Dict,
        bear_case: Dict,
        setup: Dict
    ) -> Dict[str, Any]:
        """
        Make final recommendation based on debate.
        """
        bull_score = bull_case.get("score", 0)
        bear_score = bear_case.get("score", 0)
        bull_args = bull_case.get("arguments", [])
        bear_args = bear_case.get("arguments", [])
        
        # Determine winner
        score_diff = bull_score - bear_score
        
        if score_diff > self._config["bull_margin_to_proceed"]:
            winner = "bull"
            recommendation = "proceed"
            reasoning = f"Bull case prevails ({bull_score:.2f} vs {bear_score:.2f}). "
            reasoning += f"Key strengths: {bull_args[0] if bull_args else 'N/A'}. "
            if bear_args:
                reasoning += f"Monitor: {bear_args[0]}"
        elif score_diff < -self._config["bear_margin_to_pass"]:
            winner = "bear"
            recommendation = "pass"
            reasoning = f"Bear case prevails ({bear_score:.2f} vs {bull_score:.2f}). "
            reasoning += f"Key concerns: {bear_args[0] if bear_args else 'N/A'}. "
            reasoning += "Risk outweighs opportunity."
        else:
            winner = "tie"
            # In a tie, suggest reduced size
            if bull_score >= self._config["min_bull_score"]:
                recommendation = "reduce_size"
                reasoning = f"Close debate ({bull_score:.2f} vs {bear_score:.2f}). "
                reasoning += "Consider reduced position size to manage uncertainty."
            else:
                recommendation = "pass"
                reasoning = f"Neither case is compelling ({bull_score:.2f} vs {bear_score:.2f}). "
                reasoning += "Wait for clearer opportunity."
                
        # Calculate combined confidence
        combined_confidence = (bull_case.get("confidence", 0.5) + bear_case.get("confidence", 0.5)) / 2
        
        return {
            "winner": winner,
            "recommendation": recommendation,
            "reasoning": reasoning,
            "combined_confidence": round(combined_confidence, 2),
            "bull_score": bull_score,
            "bear_score": bear_score
        }


class DebateAgents:
    """
    Orchestrates the Bull/Bear Debate process.
    
    Usage:
        debate = DebateAgents()
        result = await debate.run_debate(symbol, setup, market_context, technical_data)
    """
    
    def __init__(self, llm_service=None, learning_provider=None, config: Dict = None):
        self._bull = BullAgent(llm_service)
        self._bear = BearAgent(llm_service, learning_provider)
        self._arbiter = ArbiterAgent(config)
        self._config = config or {}
        
    async def run_debate(
        self,
        symbol: str,
        setup: Dict,
        market_context: Dict,
        technical_data: Dict,
        portfolio: Dict = None,
        rounds: int = 1
    ) -> DebateResult:
        """
        Run a full bull/bear debate on a trade opportunity.
        
        Args:
            symbol: The ticker symbol
            setup: Setup details (type, entry, stop, target, TQS, etc.)
            market_context: Current market regime, VIX, trends
            technical_data: Technical indicators for the symbol
            portfolio: Current portfolio state (optional)
            rounds: Number of debate rounds (future: multi-round debates)
            
        Returns:
            DebateResult with full debate outcome
        """
        import time
        start_time = time.time()
        
        # Run bull and bear cases in parallel
        bull_case = await self._bull.make_case(symbol, setup, market_context, technical_data)
        bear_case = await self._bear.make_case(symbol, setup, market_context, technical_data, portfolio)
        
        # Arbiter makes final call
        verdict = self._arbiter.arbitrate(bull_case, bear_case, setup)
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        result = DebateResult(
            symbol=symbol.upper(),
            setup_type=setup.get("setup_type", "unknown"),
            direction=setup.get("direction", "long"),
            bull_score=bull_case.get("score", 0),
            bull_arguments=bull_case.get("arguments", []),
            bull_confidence=bull_case.get("confidence", 0),
            bear_score=bear_case.get("score", 0),
            bear_arguments=bear_case.get("arguments", []),
            bear_confidence=bear_case.get("confidence", 0),
            winner=verdict.get("winner", "tie"),
            final_recommendation=verdict.get("recommendation", "pass"),
            reasoning=verdict.get("reasoning", ""),
            combined_confidence=verdict.get("combined_confidence", 0.5),
            debate_rounds=rounds,
            debate_time_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        logger.info(f"Debate {symbol}: {result.winner} wins, recommendation={result.final_recommendation}")
        
        return result
        
    def update_config(self, config: Dict):
        """Update arbiter configuration"""
        self._arbiter._config.update(config)
        self._config.update(config)


# Singleton instance
_debate_agents: Optional[DebateAgents] = None


def get_debate_agents() -> DebateAgents:
    """Get singleton instance of Debate Agents"""
    global _debate_agents
    if _debate_agents is None:
        _debate_agents = DebateAgents()
    return _debate_agents


def init_debate_agents(llm_service=None, learning_provider=None, config: Dict = None) -> DebateAgents:
    """Initialize Debate Agents with dependencies"""
    global _debate_agents
    _debate_agents = DebateAgents(llm_service, learning_provider, config)
    return _debate_agents
