"""
Bull/Bear Debate Agents - Multi-Agent Trade Deliberation

Implements institutional-style "red team" analysis where AI agents
argue opposing viewpoints before trade decisions.

Bull Agent: Argues for the trade opportunity
Bear Agent: Argues against / identifies risks
Time-Series Advisor: Provides AI model's directional forecast
Arbiter: Synthesizes debate and makes recommendation

Enhanced (March 2026): Time-Series AI now participates in the debate
as a weighted advisor, closing the learning loop.
"""

import logging
import asyncio
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
    
    # Time-Series AI Advisor (NEW)
    ai_advisor_score: float = 0.0  # 0-1 (how much AI supports the trade direction)
    ai_advisor_signal: str = ""  # Human-readable signal
    ai_advisor_confidence: float = 0.0
    ai_advisor_direction: str = ""  # "up", "down", "flat"
    ai_forecast_used: bool = False  # Was AI forecast available?
    
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
    
    Enhanced (March 2026): Now receives historical context from AgentDataService.
    
    Focuses on:
    - Technical setup strength
    - Favorable conditions
    - Risk/reward attractiveness
    - Momentum and trend alignment
    - Historical success on this symbol/setup (NEW)
    """
    
    def __init__(self, llm_service=None):
        self._llm = llm_service
        
    async def make_case(
        self,
        symbol: str,
        setup: Dict,
        market_context: Dict,
        technical_data: Dict,
        historical_context: Dict = None
    ) -> Dict[str, Any]:
        """
        Build the bullish case for this trade.
        
        Args:
            historical_context: Optional dict with symbol_context, setup_context, insights
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
        
        # ===== NEW: Historical Context Factors =====
        if historical_context:
            # Factor 8: User's historical success on this symbol
            sym_ctx = historical_context.get("symbol_context", {})
            if sym_ctx.get("total_trades", 0) >= 5:
                win_rate = sym_ctx.get("win_rate", 0)
                if win_rate >= 0.6:
                    arguments.append(f"Strong track record on {symbol}: {win_rate*100:.0f}% win rate ({sym_ctx['total_trades']} trades)")
                    score += 0.15
                elif win_rate >= 0.5:
                    arguments.append(f"Positive history on {symbol}: {win_rate*100:.0f}% win rate")
                    score += 0.05
                factors += 1
                
                # Check average R-multiple
                avg_r = sym_ctx.get("avg_r_multiple", 0)
                if avg_r >= 1.5:
                    arguments.append(f"Historically profitable: avg {avg_r:.1f}R on {symbol}")
                    score += 0.1
                    factors += 1
            
            # Factor 9: Setup type historical performance
            setup_ctx = historical_context.get("setup_context", {})
            setup_type = setup.get("setup_type", "")
            if setup_ctx.get("sample_size_adequate", False):
                setup_wr = setup_ctx.get("win_rate", 0)
                if setup_wr >= 0.55:
                    arguments.append(f"{setup_type} setups have {setup_wr*100:.0f}% historical win rate")
                    score += 0.1
                    factors += 1
                    
                # Check if current regime matches best regime for this setup
                best_regime = setup_ctx.get("best_regime", "")
                if best_regime and best_regime == regime:
                    arguments.append(f"Current {regime} regime is historically best for {setup_type}")
                    score += 0.1
                    factors += 1
            
            # Factor 10: Use insights from AgentDataService
            insights = historical_context.get("insights", [])
            for insight in insights:
                if "strong" in insight.lower() or "positive" in insight.lower() or "%" in insight and "60" in insight:
                    arguments.append(f"Historical: {insight}")
                    score += 0.05
                    break  # Only use one insight
        
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
    
    Enhanced (March 2026): Now receives historical context from AgentDataService.
    
    Focuses on:
    - Risk factors and red flags
    - Unfavorable conditions
    - Historical failure patterns (NEW)
    - Overexposure concerns
    - User's poor track record on symbol/setup (NEW)
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
        portfolio: Dict = None,
        historical_context: Dict = None
    ) -> Dict[str, Any]:
        """
        Build the bearish case against this trade.
        
        Args:
            historical_context: Optional dict with symbol_context, setup_context, insights
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
        
        # Factor 4: Historical Win Rate Concern (use historical_context if available)
        historical_wr = setup.get("historical_win_rate", 0.5)
        if historical_context:
            setup_ctx = historical_context.get("setup_context", {})
            if setup_ctx.get("sample_size_adequate", False):
                historical_wr = setup_ctx.get("win_rate", historical_wr)
                
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
        
        # ===== NEW: Historical Context Factors for Bear Case =====
        if historical_context:
            # Factor 9: User's poor track record on this symbol
            sym_ctx = historical_context.get("symbol_context", {})
            if sym_ctx.get("total_trades", 0) >= 5:
                win_rate = sym_ctx.get("win_rate", 0.5)
                if win_rate <= 0.4:
                    arguments.append(f"Poor track record on {symbol}: only {win_rate*100:.0f}% win rate ({sym_ctx['total_trades']} trades)")
                    score += 0.2
                    factors += 1
                    
                # Check if avg R is negative
                avg_r = sym_ctx.get("avg_r_multiple", 0)
                if avg_r < 0:
                    arguments.append(f"Historically losing money on {symbol}: avg {avg_r:.1f}R")
                    score += 0.15
                    factors += 1
                    
                # Worst trade warning
                worst_r = sym_ctx.get("worst_trade_r", 0)
                if worst_r < -2:
                    arguments.append(f"Large loss history on {symbol}: worst trade {worst_r:.1f}R")
                    score += 0.1
                    factors += 1
            
            # Factor 10: Setup type poor performance
            setup_ctx = historical_context.get("setup_context", {})
            setup_type = setup.get("setup_type", "")
            if setup_ctx.get("sample_size_adequate", False):
                setup_wr = setup_ctx.get("win_rate", 0.5)
                if setup_wr < 0.45:
                    arguments.append(f"{setup_type} setups have poor {setup_wr*100:.0f}% win rate historically")
                    score += 0.15
                    factors += 1
                    
                # Check if current regime is worst for this setup
                worst_regime = setup_ctx.get("worst_regime", "")
                if worst_regime and worst_regime == regime:
                    arguments.append(f"Current {regime} regime is historically worst for {setup_type}")
                    score += 0.15
                    factors += 1
            
            # Factor 11: Use warning insights from AgentDataService
            insights = historical_context.get("insights", [])
            for insight in insights:
                if "caution" in insight.lower() or "warning" in insight.lower() or "only" in insight.lower():
                    arguments.append(f"Historical: {insight}")
                    score += 0.1
                    break  # Only use one insight
        
        # Normalize
        max_possible = factors * 0.2
        normalized_score = min(1.0, score / max_possible) if max_possible > 0 else 0
        
        # Confidence based on number of significant concerns
        major_concerns = len([a for a in arguments if "poor" in a.lower() or "high" in a.lower() or "risk" in a.lower() or "only" in a.lower()])
        confidence = min(1.0, major_concerns * 0.15 + 0.3)
        
        return {
            "score": round(normalized_score, 2),
            "arguments": arguments,
            "confidence": round(confidence, 2),
            "major_concerns": major_concerns
        }


class TimeSeriesAdvisor:
    """
    Time-Series AI Advisor - Provides machine learning model's directional forecast.
    
    This closes the learning loop by incorporating the trained model's predictions
    directly into the debate process. The model learns from historical outcomes
    and provides probabilistic directional forecasts.
    
    Contribution:
    - Supports Bull when predicting UP for long trades (or DOWN for shorts)
    - Supports Bear when predicting contrary to trade direction
    - Neutral when confidence is low or direction is flat
    """
    
    # Weight of AI advisor in final decision (0-1)
    # Start conservative, increase as model accuracy improves
    DEFAULT_WEIGHT = 0.15  # 15% influence on final score
    
    def __init__(self, weight: float = None):
        self._weight = weight if weight is not None else self.DEFAULT_WEIGHT
        
    def evaluate_forecast(
        self,
        forecast: Dict[str, Any],
        trade_direction: str = "long"
    ) -> Dict[str, Any]:
        """
        Evaluate how the AI forecast supports or contradicts the trade.
        
        Args:
            forecast: Time-Series AI forecast with direction, probability, confidence
            trade_direction: "long" or "short"
            
        Returns:
            {
                "score": 0-1 (how much this supports the trade),
                "signal": human-readable signal,
                "confidence": model confidence,
                "supports_trade": "supports" | "contradicts" | "neutral",
                "ai_direction": "up" | "down" | "flat"
            }
        """
        if not forecast or not forecast.get("usable", False):
            return {
                "score": 0.5,  # Neutral
                "signal": "AI forecast unavailable or low confidence",
                "confidence": 0.0,
                "supports_trade": "neutral",
                "ai_direction": "flat",
                "contribution_to_bull": 0.0,
                "contribution_to_bear": 0.0
            }
            
        ai_direction = forecast.get("direction", "flat")
        confidence = forecast.get("confidence", 0)
        prob_up = forecast.get("probability_up", 0.5)
        prob_down = forecast.get("probability_down", 0.5)
        
        # Determine alignment with trade
        if trade_direction == "long":
            if ai_direction == "up":
                # AI supports the long trade
                supports = "supports"
                score = 0.5 + (prob_up - 0.5) * confidence  # 0.5-1.0 range
                signal = f"AI predicts UP ({prob_up*100:.0f}%) - supports long"
                bull_contribution = confidence * self._weight
                bear_contribution = 0.0
            elif ai_direction == "down":
                # AI contradicts the long trade
                supports = "contradicts"
                score = 0.5 - (prob_down - 0.5) * confidence  # 0.0-0.5 range
                signal = f"AI predicts DOWN ({prob_down*100:.0f}%) - contradicts long"
                bull_contribution = 0.0
                bear_contribution = confidence * self._weight
            else:
                # AI is neutral
                supports = "neutral"
                score = 0.5
                signal = "AI prediction unclear/neutral"
                bull_contribution = 0.0
                bear_contribution = 0.0
        else:  # short
            if ai_direction == "down":
                # AI supports the short trade
                supports = "supports"
                score = 0.5 + (prob_down - 0.5) * confidence
                signal = f"AI predicts DOWN ({prob_down*100:.0f}%) - supports short"
                bull_contribution = confidence * self._weight
                bear_contribution = 0.0
            elif ai_direction == "up":
                # AI contradicts the short trade
                supports = "contradicts"
                score = 0.5 - (prob_up - 0.5) * confidence
                signal = f"AI predicts UP ({prob_up*100:.0f}%) - contradicts short"
                bull_contribution = 0.0
                bear_contribution = confidence * self._weight
            else:
                supports = "neutral"
                score = 0.5
                signal = "AI prediction unclear/neutral"
                bull_contribution = 0.0
                bear_contribution = 0.0
                
        return {
            "score": round(max(0, min(1, score)), 2),
            "signal": signal,
            "confidence": round(confidence, 2),
            "supports_trade": supports,
            "ai_direction": ai_direction,
            "contribution_to_bull": round(bull_contribution, 3),
            "contribution_to_bear": round(bear_contribution, 3),
            "weight_used": self._weight
        }
        
    def set_weight(self, weight: float):
        """Update the AI advisor weight (0-1)"""
        self._weight = max(0, min(1, weight))


class ArbiterAgent:
    """
    The Arbiter - Synthesizes bull/bear debate and makes final recommendation.
    
    Enhanced: Now factors in Time-Series AI advisor contribution.
    
    Uses configurable thresholds to determine:
    - Whether to proceed with trade
    - Whether to reduce size
    - Whether to pass entirely
    """
    
    DEFAULT_CONFIG = {
        "min_bull_score": 0.4,
        "min_bear_score": 0.4,
        "require_consensus": False,
        "bull_margin_to_proceed": 0.15,
        "bear_margin_to_pass": 0.2,
        "ai_advisor_weight": 0.15
    }
    
    def __init__(self, config: Dict = None):
        # Merge provided config with defaults
        self._config = {**self.DEFAULT_CONFIG}
        if config:
            self._config.update(config)
        
    def arbitrate(
        self,
        bull_case: Dict,
        bear_case: Dict,
        setup: Dict,
        ai_advisor_result: Dict = None
    ) -> Dict[str, Any]:
        """
        Make final recommendation based on debate.
        
        Args:
            bull_case: Bull agent's arguments and score
            bear_case: Bear agent's arguments and score
            setup: Trade setup details
            ai_advisor_result: Optional Time-Series AI advisor evaluation
        """
        bull_score = bull_case.get("score", 0)
        bear_score = bear_case.get("score", 0)
        bull_args = bull_case.get("arguments", [])
        bear_args = bear_case.get("arguments", [])
        
        # Apply AI advisor contributions if available
        ai_signal = ""
        if ai_advisor_result and ai_advisor_result.get("confidence", 0) > 0:
            bull_contribution = ai_advisor_result.get("contribution_to_bull", 0)
            bear_contribution = ai_advisor_result.get("contribution_to_bear", 0)
            
            # Add AI contributions to scores
            bull_score += bull_contribution
            bear_score += bear_contribution
            
            ai_signal = ai_advisor_result.get("signal", "")
            supports = ai_advisor_result.get("supports_trade", "neutral")
            
            logger.info(
                f"AI Advisor: {supports} trade | Bull +{bull_contribution:.3f}, Bear +{bear_contribution:.3f}"
            )
        
        # Determine winner
        score_diff = bull_score - bear_score
        
        if score_diff > self._config["bull_margin_to_proceed"]:
            winner = "bull"
            recommendation = "proceed"
            reasoning = f"Bull case prevails ({bull_score:.2f} vs {bear_score:.2f}). "
            reasoning += f"Key strengths: {bull_args[0] if bull_args else 'N/A'}. "
            if ai_signal and "supports" in ai_signal.lower():
                reasoning += f"AI confirms: {ai_signal}. "
            elif bear_args:
                reasoning += f"Monitor: {bear_args[0]}"
        elif score_diff < -self._config["bear_margin_to_pass"]:
            winner = "bear"
            recommendation = "pass"
            reasoning = f"Bear case prevails ({bear_score:.2f} vs {bull_score:.2f}). "
            reasoning += f"Key concerns: {bear_args[0] if bear_args else 'N/A'}. "
            if ai_signal and "contradicts" in ai_signal.lower():
                reasoning += f"AI agrees: {ai_signal}. "
            reasoning += "Risk outweighs opportunity."
        else:
            winner = "tie"
            # In a tie, suggest reduced size
            if bull_score >= self._config["min_bull_score"]:
                recommendation = "reduce_size"
                reasoning = f"Close debate ({bull_score:.2f} vs {bear_score:.2f}). "
                if ai_signal:
                    reasoning += f"AI says: {ai_signal}. "
                reasoning += "Consider reduced position size to manage uncertainty."
            else:
                recommendation = "pass"
                reasoning = f"Neither case is compelling ({bull_score:.2f} vs {bear_score:.2f}). "
                reasoning += "Wait for clearer opportunity."
                
        # Calculate combined confidence (include AI if available)
        confidences = [bull_case.get("confidence", 0.5), bear_case.get("confidence", 0.5)]
        if ai_advisor_result and ai_advisor_result.get("confidence", 0) > 0:
            confidences.append(ai_advisor_result.get("confidence", 0.5))
        combined_confidence = sum(confidences) / len(confidences)
        
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
    
    Enhanced (March 2026):
    - Now includes Time-Series AI Advisor for ML-based input
    - Now fetches historical context from AgentDataService
    
    Usage:
        debate = DebateAgents()
        result = await debate.run_debate(symbol, setup, market_context, technical_data, ai_forecast=forecast)
    """
    
    def __init__(self, llm_service=None, learning_provider=None, config: Dict = None, data_service=None):
        self._bull = BullAgent(llm_service)
        self._bear = BearAgent(llm_service, learning_provider)
        self._ai_advisor = TimeSeriesAdvisor(
            weight=config.get("ai_advisor_weight", 0.15) if config else 0.15
        )
        self._arbiter = ArbiterAgent(config)
        self._config = config or {}
        self._data_service = data_service  # AgentDataService for historical context
        
    def set_data_service(self, data_service):
        """Set the AgentDataService for historical context"""
        self._data_service = data_service
        
    async def run_debate(
        self,
        symbol: str,
        setup: Dict,
        market_context: Dict,
        technical_data: Dict,
        portfolio: Dict = None,
        rounds: int = 1,
        ai_forecast: Dict = None,
        historical_context: Dict = None
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
            ai_forecast: Time-Series AI forecast (optional, enhances debate)
            historical_context: Pre-fetched historical context (optional)
            
        Returns:
            DebateResult with full debate outcome including AI advisor input
        """
        import time
        start_time = time.time()
        
        direction = setup.get("direction", "long")
        setup_type = setup.get("setup_type", "")
        
        # Fetch historical context if not provided and service is available
        if historical_context is None and self._data_service:
            try:
                historical_context = await asyncio.to_thread(
                    self._data_service.build_agent_context,
                    symbol=symbol,
                    setup_type=setup_type,
                    direction=direction
                )
                logger.info(f"Fetched historical context for {symbol}: {len(historical_context.get('insights', []))} insights")
            except Exception as e:
                logger.warning(f"Could not fetch historical context for {symbol}: {e}")
                historical_context = None
        
        # Run bull and bear cases (now with historical context)
        bull_case = await self._bull.make_case(
            symbol, setup, market_context, technical_data, 
            historical_context=historical_context
        )
        bear_case = await self._bear.make_case(
            symbol, setup, market_context, technical_data, portfolio,
            historical_context=historical_context
        )
        
        # Get AI Advisor's evaluation if forecast available
        ai_advisor_result = None
        if ai_forecast:
            ai_advisor_result = self._ai_advisor.evaluate_forecast(ai_forecast, direction)
            logger.info(
                f"AI Advisor for {symbol}: {ai_advisor_result.get('supports_trade')} "
                f"(confidence: {ai_advisor_result.get('confidence', 0):.0%})"
            )
        
        # Arbiter makes final call (now with AI advisor input)
        verdict = self._arbiter.arbitrate(bull_case, bear_case, setup, ai_advisor_result)
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        result = DebateResult(
            symbol=symbol.upper(),
            setup_type=setup.get("setup_type", "unknown"),
            direction=direction,
            bull_score=verdict.get("bull_score", bull_case.get("score", 0)),
            bull_arguments=bull_case.get("arguments", []),
            bull_confidence=bull_case.get("confidence", 0),
            bear_score=verdict.get("bear_score", bear_case.get("score", 0)),
            bear_arguments=bear_case.get("arguments", []),
            bear_confidence=bear_case.get("confidence", 0),
            # AI Advisor fields
            ai_advisor_score=ai_advisor_result.get("score", 0) if ai_advisor_result else 0,
            ai_advisor_signal=ai_advisor_result.get("signal", "") if ai_advisor_result else "",
            ai_advisor_confidence=ai_advisor_result.get("confidence", 0) if ai_advisor_result else 0,
            ai_advisor_direction=ai_advisor_result.get("ai_direction", "") if ai_advisor_result else "",
            ai_forecast_used=ai_forecast is not None and ai_forecast.get("usable", False),
            # Arbiter fields
            winner=verdict.get("winner", "tie"),
            final_recommendation=verdict.get("recommendation", "pass"),
            reasoning=verdict.get("reasoning", ""),
            combined_confidence=verdict.get("combined_confidence", 0.5),
            debate_rounds=rounds,
            debate_time_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Add historical context to result if available
        if historical_context:
            # Include insights in reasoning
            insights = historical_context.get("insights", [])
            if insights and result.reasoning:
                result.reasoning += f" Historical insights: {', '.join(insights[:2])}"
        
        logger.info(
            f"Debate {symbol}: {result.winner} wins, recommendation={result.final_recommendation}"
            + (f", AI: {ai_advisor_result.get('supports_trade')}" if ai_advisor_result else "")
        )
        
        return result
        
    def set_ai_advisor_weight(self, weight: float):
        """Update AI advisor weight (0-1)"""
        self._ai_advisor.set_weight(weight)
        
    def update_config(self, config: Dict):
        """Update arbiter configuration"""
        self._arbiter._config.update(config)
        self._config.update(config)
        if "ai_advisor_weight" in config:
            self._ai_advisor.set_weight(config["ai_advisor_weight"])


# Singleton instance
_debate_agents: Optional[DebateAgents] = None


def get_debate_agents() -> DebateAgents:
    """Get singleton instance of Debate Agents"""
    global _debate_agents
    if _debate_agents is None:
        _debate_agents = DebateAgents()
    return _debate_agents


def init_debate_agents(llm_service=None, learning_provider=None, config: Dict = None, data_service=None) -> DebateAgents:
    """Initialize Debate Agents with dependencies"""
    global _debate_agents
    _debate_agents = DebateAgents(llm_service, learning_provider, config, data_service)
    return _debate_agents


def set_debate_data_service(data_service) -> None:
    """Set the AgentDataService on existing debate agents instance"""
    global _debate_agents
    if _debate_agents:
        _debate_agents.set_data_service(data_service)
