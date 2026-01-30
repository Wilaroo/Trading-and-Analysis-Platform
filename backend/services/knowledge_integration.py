"""
Knowledge Integration Service
Integrates learned knowledge from the knowledge base into scoring and market intelligence.
Queries the knowledge base and enhances stock analysis with learned strategies.
Also integrates real-time news for comprehensive market analysis.
"""
import logging
from typing import Optional, Dict, List, Any
from services.knowledge_service import get_knowledge_service
from services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


class KnowledgeIntegrationService:
    """
    Service that bridges the knowledge base with the scoring engine
    and market intelligence generation. Includes news integration.
    """
    
    def __init__(self):
        self.knowledge = get_knowledge_service()
        self.llm = get_llm_service()
        self._news_service = None
    
    @property
    def news_service(self):
        """Lazy load news service"""
        if self._news_service is None:
            from services.news_service import get_news_service
            self._news_service = get_news_service()
        return self._news_service
    
    async def get_market_news_context(self) -> Dict:
        """
        Get current market news context for intelligence generation.
        """
        try:
            summary = await self.news_service.get_market_summary()
            return summary
        except Exception as e:
            logger.warning(f"Error getting market news: {e}")
            return {"available": False}
    
    def get_applicable_strategies(self, stock_data: Dict) -> List[Dict]:
        """
        Find strategies from the knowledge base that apply to the current stock situation.
        
        Args:
            stock_data: Dictionary containing stock metrics like:
                - rvol, gap_percent, vwap_position, current_price, prev_close
                - rsi, macd, trend, market_regime, etc.
        
        Returns:
            List of applicable strategies with relevance scores
        """
        applicable = []
        
        # Get all strategies from knowledge base
        all_strategies = self.knowledge.get_strategies()
        
        # Define conditions based on stock_data
        rvol = stock_data.get("rvol", 1.0)
        gap_pct = stock_data.get("gap_percent", 0)
        vwap_pos = stock_data.get("vwap_position", "UNKNOWN")
        rsi = stock_data.get("rsi_14", 50)
        current_price = stock_data.get("current_price", 0)
        ma_9 = stock_data.get("ema_9", 0)
        ma_20 = stock_data.get("sma_20", 0)
        ma_50 = stock_data.get("sma_50", 0)
        
        # Determine market conditions
        is_high_volume = rvol >= 2.0
        is_gapper = abs(gap_pct) >= 4.0
        is_above_vwap = vwap_pos == "ABOVE"
        is_oversold = rsi < 30
        is_overbought = rsi > 70
        is_trending_up = ma_9 > ma_20 > ma_50 if all([ma_9, ma_20, ma_50]) else False
        is_trending_down = ma_9 < ma_20 < ma_50 if all([ma_9, ma_20, ma_50]) else False
        
        for strategy in all_strategies:
            relevance_score = 0
            reasons = []
            
            title_lower = strategy.get("title", "").lower()
            content_lower = strategy.get("content", "").lower()
            tags = [t.lower() for t in strategy.get("tags", [])]
            
            # Check for momentum strategies
            if "momentum" in title_lower or "momentum" in tags:
                if is_high_volume:
                    relevance_score += 30
                    reasons.append("High RVOL supports momentum")
                if is_gapper:
                    relevance_score += 20
                    reasons.append("Gap aligns with momentum play")
                if is_trending_up or is_trending_down:
                    relevance_score += 20
                    reasons.append("Clear trend present")
            
            # Check for mean reversion strategies
            if "mean-reversion" in title_lower or "mean reversion" in content_lower or "reversion" in tags:
                if is_oversold:
                    relevance_score += 35
                    reasons.append("RSI oversold - mean reversion candidate")
                if is_overbought:
                    relevance_score += 35
                    reasons.append("RSI overbought - mean reversion candidate")
            
            # Check for VWAP strategies
            if "vwap" in title_lower or "vwap" in content_lower:
                if vwap_pos != "UNKNOWN":
                    relevance_score += 25
                    reasons.append(f"VWAP position: {vwap_pos}")
            
            # Check for moving average strategies
            if "moving average" in title_lower or "crossover" in content_lower:
                if is_trending_up or is_trending_down:
                    relevance_score += 30
                    reasons.append("MA alignment detected")
            
            # Check for breakout strategies
            if "breakout" in title_lower or "breakout" in content_lower:
                if is_high_volume and is_gapper:
                    relevance_score += 40
                    reasons.append("Volume + gap supports breakout")
            
            # Check for gap strategies
            if "gap" in title_lower or "gap" in tags:
                if is_gapper:
                    relevance_score += 35
                    reasons.append(f"Gap of {gap_pct:.1f}% detected")
            
            # Check for value strategies
            if "value" in title_lower or "value" in tags:
                pe_ratio = stock_data.get("pe_ratio", 0)
                if pe_ratio > 0 and pe_ratio < 15:
                    relevance_score += 25
                    reasons.append(f"Low P/E ratio: {pe_ratio}")
            
            # Add strategy if relevant
            if relevance_score >= 20:
                applicable.append({
                    "id": strategy.get("id"),
                    "title": strategy.get("title"),
                    "content": strategy.get("content", "")[:200],
                    "type": strategy.get("type"),
                    "category": strategy.get("category"),
                    "tags": strategy.get("tags", []),
                    "relevance_score": relevance_score,
                    "reasons": reasons,
                    "confidence": strategy.get("confidence", 70)
                })
                
                # Increment usage count
                if strategy.get("id"):
                    self.knowledge.increment_usage(strategy["id"])
        
        # Sort by relevance score
        applicable.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        return applicable[:10]  # Return top 10 applicable strategies
    
    def get_strategy_recommendations(self, stock_data: Dict, market_data: Dict = None) -> Dict:
        """
        Get comprehensive strategy recommendations for a stock.
        
        Returns:
            Dictionary with recommended strategies, trade ideas, and confidence levels
        """
        market_data = market_data or {}
        applicable = self.get_applicable_strategies(stock_data)
        
        if not applicable:
            return {
                "recommendations": [],
                "trade_bias": "NEUTRAL",
                "confidence": 30,
                "summary": "No strongly applicable strategies found in knowledge base."
            }
        
        # Determine overall trade bias
        long_score = 0
        short_score = 0
        
        for strat in applicable:
            content = strat.get("content", "").lower()
            relevance = strat.get("relevance_score", 0)
            
            if "long" in content or "buy" in content or "bullish" in content:
                long_score += relevance
            if "short" in content or "sell" in content or "bearish" in content:
                short_score += relevance
        
        # Also factor in stock data
        vwap_pos = stock_data.get("vwap_position", "")
        if vwap_pos == "ABOVE":
            long_score += 20
        elif vwap_pos == "BELOW":
            short_score += 20
        
        gap_pct = stock_data.get("gap_percent", 0)
        if gap_pct > 0:
            long_score += 15
        elif gap_pct < 0:
            short_score += 15
        
        if long_score > short_score + 30:
            trade_bias = "LONG"
        elif short_score > long_score + 30:
            trade_bias = "SHORT"
        else:
            trade_bias = "NEUTRAL"
        
        # Calculate overall confidence
        avg_confidence = sum(s["confidence"] for s in applicable) / len(applicable) if applicable else 50
        top_relevance = applicable[0]["relevance_score"] if applicable else 0
        confidence = min(90, int((avg_confidence + top_relevance) / 2))
        
        # Build summary
        top_strategies = [s["title"] for s in applicable[:3]]
        summary = f"Top applicable strategies: {', '.join(top_strategies)}. "
        summary += f"Trade bias: {trade_bias} with {confidence}% confidence."
        
        return {
            "recommendations": applicable,
            "trade_bias": trade_bias,
            "confidence": confidence,
            "summary": summary,
            "long_score": long_score,
            "short_score": short_score
        }
    
    def enhance_market_intelligence(self, opportunities: List[Dict], market_regime: str = "neutral") -> Dict:
        """
        Enhance market intelligence with learned knowledge.
        
        Args:
            opportunities: List of stock opportunities from scanner
            market_regime: Current market regime (bullish, bearish, neutral)
        
        Returns:
            Enhanced intelligence with strategy recommendations
        """
        enhanced_opportunities = []
        strategy_insights = []
        
        for opp in opportunities[:10]:
            symbol = opp.get("symbol", "")
            
            # Build stock_data from opportunity
            stock_data = {
                "symbol": symbol,
                "current_price": opp.get("price") or opp.get("quote", {}).get("price", 0),
                "gap_percent": opp.get("gap_percent") or opp.get("quote", {}).get("change_percent", 0),
                "rvol": opp.get("rvol", 1.0),
                "vwap_position": "ABOVE" if opp.get("change_percent", 0) > 0 else "BELOW",
                "rsi_14": opp.get("rsi", 50)
            }
            
            # Get strategy recommendations
            recommendations = self.get_strategy_recommendations(stock_data, {"regime": market_regime})
            
            enhanced_opp = {
                **opp,
                "learned_strategies": recommendations["recommendations"][:3],
                "kb_trade_bias": recommendations["trade_bias"],
                "kb_confidence": recommendations["confidence"]
            }
            enhanced_opportunities.append(enhanced_opp)
            
            # Collect unique strategy insights
            for rec in recommendations["recommendations"][:2]:
                if rec["title"] not in [s["title"] for s in strategy_insights]:
                    strategy_insights.append({
                        "title": rec["title"],
                        "relevance": rec["relevance_score"],
                        "applicable_to": [symbol]
                    })
                else:
                    # Add symbol to existing insight
                    for insight in strategy_insights:
                        if insight["title"] == rec["title"]:
                            insight["applicable_to"].append(symbol)
        
        # Sort insights by how many stocks they apply to
        strategy_insights.sort(key=lambda x: len(x["applicable_to"]), reverse=True)
        
        return {
            "opportunities": enhanced_opportunities,
            "top_strategy_insights": strategy_insights[:5],
            "market_regime": market_regime,
            "knowledge_base_stats": self.knowledge.get_stats()
        }
    
    def generate_ai_trade_recommendation(self, stock_data: Dict) -> Optional[Dict]:
        """
        Use LLM to generate a trade recommendation based on stock data
        and applicable strategies from the knowledge base.
        """
        if not self.llm.is_available:
            return None
        
        # Get applicable strategies
        applicable = self.get_applicable_strategies(stock_data)
        
        if not applicable:
            return None
        
        # Build context for LLM
        strategies_text = "\n".join([
            f"- {s['title']}: {s['content'][:150]}... (Relevance: {s['relevance_score']})"
            for s in applicable[:5]
        ])
        
        symbol = stock_data.get("symbol", "UNKNOWN")
        price = stock_data.get("current_price", 0)
        rvol = stock_data.get("rvol", 1.0)
        gap = stock_data.get("gap_percent", 0)
        vwap_pos = stock_data.get("vwap_position", "UNKNOWN")
        
        prompt = f"""Based on my trading knowledge base and current stock metrics, provide a trade recommendation.

STOCK: {symbol}
Current Price: ${price:.2f}
RVOL: {rvol:.1f}x
Gap %: {gap:+.1f}%
VWAP Position: {vwap_pos}

APPLICABLE STRATEGIES FROM MY KNOWLEDGE BASE:
{strategies_text}

Provide a JSON response with:
{{
    "direction": "LONG" or "SHORT" or "NEUTRAL",
    "confidence": 0-100,
    "entry": suggested entry price or "market",
    "stop_loss": suggested stop price,
    "target": suggested target price,
    "reasoning": 1-2 sentence explanation referencing the applicable strategies,
    "risk_warning": any key risks to watch
}}"""

        system_prompt = """You are a trading analyst. Provide actionable trade recommendations based on the stock data and applicable strategies. Be specific with price levels. Return ONLY valid JSON."""
        
        try:
            result = self.llm.generate_json(prompt, system_prompt, max_tokens=500)
            result["symbol"] = symbol
            result["source"] = "knowledge_base_ai"
            return result
        except Exception as e:
            logger.error(f"Error generating AI recommendation: {e}")
            return None
    
    def get_rules_for_situation(self, situation: str) -> List[Dict]:
        """
        Get applicable trading rules for a specific situation.
        
        Args:
            situation: e.g., "gap_up", "high_rvol", "oversold", "earnings"
        
        Returns:
            List of applicable rules from knowledge base
        """
        # Search for rules related to the situation
        rules = self.knowledge.search(
            query=situation,
            type="rule",
            limit=10
        )
        
        # Also get strategies as secondary source
        strategies = self.knowledge.search(
            query=situation,
            type="strategy",
            limit=5
        )
        
        return {
            "rules": rules,
            "related_strategies": strategies
        }
    
    def get_knowledge_summary_for_symbol(self, symbol: str, stock_data: Dict = None) -> Dict:
        """
        Get a complete knowledge-based summary for a symbol.
        """
        stock_data = stock_data or {}
        stock_data["symbol"] = symbol
        
        # Get applicable strategies
        strategies = self.get_applicable_strategies(stock_data)
        
        # Get recommendations
        recommendations = self.get_strategy_recommendations(stock_data)
        
        # Get AI recommendation if available
        ai_rec = None
        if self.llm.is_available and strategies:
            ai_rec = self.generate_ai_trade_recommendation(stock_data)
        
        return {
            "symbol": symbol,
            "applicable_strategies": strategies,
            "trade_bias": recommendations["trade_bias"],
            "confidence": recommendations["confidence"],
            "summary": recommendations["summary"],
            "ai_recommendation": ai_rec,
            "knowledge_stats": self.knowledge.get_stats()
        }


# Singleton instance
_knowledge_integration: Optional[KnowledgeIntegrationService] = None

def get_knowledge_integration() -> KnowledgeIntegrationService:
    """Get the singleton knowledge integration service"""
    global _knowledge_integration
    if _knowledge_integration is None:
        _knowledge_integration = KnowledgeIntegrationService()
    return _knowledge_integration
