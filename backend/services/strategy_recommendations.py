"""
Strategy Recommendation Service
Maps market contexts to appropriate trading strategies
"""
from typing import Dict, List, Optional

# Strategy mappings by market context
CONTEXT_STRATEGY_MAP = {
    "TRENDING": {
        "primary": [
            "INT-01",  # Trend Momentum Continuation
            "INT-02",  # Intraday Breakout (Range High)
            "INT-05",  # Pullback in Trend (Buy the Dip)
            "INT-10",  # Bull/Bear Flag Intraday
            "INT-14",  # News/Earnings Momentum
            "INT-15",  # Break of Premarket High/Low
            "INT-16",  # High-of-Day (HOD) Break Scalps
            "SWG-01",  # Daily Trend Following
            "SWG-04",  # Pullback After Breakout (Retest)
            "SWG-05",  # Moving Average Crossover Swing
        ],
        "secondary": [
            "INT-03",  # Opening Range Breakout (ORB)
            "INT-04",  # Gap-and-Go
            "INT-06",  # VWAP Bounce
            "INT-18",  # Index-Correlated Trend Riding
            "SWG-02",  # Breakout from Multi-Week Base
            "SWG-09",  # Sector/ETF Relative Strength
        ],
        "aggressive_only": [
            "INT-04",  # Gap-and-Go (needs high volatility)
            "INT-14",  # News/Earnings Momentum
            "INT-16",  # HOD Break Scalps
        ],
        "trade_styles": ["Breakout Confirmation", "Pullback Continuation", "Momentum Trading"]
    },
    "CONSOLIDATION": {
        "primary": [
            "INT-09",  # Scalping Micro-Moves
            "INT-12",  # Pivot Point Intraday Strategy
            "INT-13",  # Intraday Range Trading
            "INT-17",  # Range-to-Trend Transition
            "INT-19",  # Liquidity-Grab Stop-Hunt Reversal
            "SWG-03",  # Range Trading on Daily
            "SWG-13",  # Volatility Contraction Pattern (VCP)
        ],
        "secondary": [
            "INT-02",  # Intraday Breakout (watch for breakout)
            "INT-03",  # Opening Range Breakout
            "SWG-02",  # Breakout from Multi-Week Base (watch for setup)
            "SWG-11",  # Pairs Trading / Relative Value
        ],
        "avoid": [
            "INT-01",  # Trend Momentum (no trend)
            "INT-04",  # Gap-and-Go (low volatility)
            "INT-14",  # News Momentum (low volume)
        ],
        "trade_styles": ["Range Trading", "Scalping", "Rubber Band Setup", "Breakout Watch"]
    },
    "MEAN_REVERSION": {
        "primary": [
            "INT-07",  # VWAP Reversion (Fade to VWAP)
            "INT-08",  # Mean Reversion After Exhaustion Spike
            "INT-11",  # Reversal at Key Level
            "INT-20",  # Time-of-Day Fade (Late-Day Reversal)
            "SWG-06",  # RSI/Stochastic Mean-Reversion
            "SWG-10",  # Shorting Failed Breakouts
            "SWG-14",  # Gap-Fill Swing
        ],
        "secondary": [
            "INT-06",  # VWAP Bounce (if reverting to VWAP)
            "INT-12",  # Pivot Point Strategy
            "INT-19",  # Liquidity-Grab Stop-Hunt Reversal
            "SWG-03",  # Range Trading on Daily
            "SWG-11",  # Pairs Trading / Relative Value
        ],
        "aggressive_only": [
            "INT-07",  # VWAP Reversion (needs quick execution)
            "INT-08",  # Exhaustion Spike (high risk)
            "SWG-10",  # Shorting Failed Breakouts (short bias)
        ],
        "trade_styles": ["VWAP Reversion", "Exhaustion Reversal", "Key Level Reversal"]
    }
}

# Strategy risk levels
STRATEGY_RISK = {
    "INT-01": "Medium", "INT-02": "Medium", "INT-03": "Medium", "INT-04": "High",
    "INT-05": "Low", "INT-06": "Low", "INT-07": "High", "INT-08": "High",
    "INT-09": "Low", "INT-10": "Medium", "INT-11": "High", "INT-12": "Low",
    "INT-13": "Low", "INT-14": "High", "INT-15": "Medium", "INT-16": "Medium",
    "INT-17": "Medium", "INT-18": "Medium", "INT-19": "High", "INT-20": "Medium",
    "SWG-01": "Low", "SWG-02": "Medium", "SWG-03": "Low", "SWG-04": "Low",
    "SWG-05": "Low", "SWG-06": "Medium", "SWG-07": "Medium", "SWG-08": "Low",
    "SWG-09": "Low", "SWG-10": "High", "SWG-11": "Medium", "SWG-12": "Low",
    "SWG-13": "Medium", "SWG-14": "Medium", "SWG-15": "Low",
    "INV-01": "Low", "INV-02": "Low", "INV-03": "Low", "INV-04": "Low",
    "INV-05": "Low", "INV-06": "Medium", "INV-07": "Low", "INV-08": "Medium",
    "INV-09": "Low", "INV-10": "Low", "INV-11": "Medium", "INV-12": "Low",
    "INV-13": "Low", "INV-14": "Low", "INV-15": "Low"
}


class StrategyRecommendationService:
    """Service for intelligent strategy recommendations based on market context"""
    
    def __init__(self):
        self.context_map = CONTEXT_STRATEGY_MAP
        self.risk_levels = STRATEGY_RISK
    
    def get_recommended_strategies(
        self, 
        market_context: str, 
        sub_type: str = None,
        include_secondary: bool = True,
        max_risk: str = "High"  # Low, Medium, High
    ) -> Dict:
        """
        Get recommended strategies for a market context
        """
        context = market_context.upper()
        if context not in self.context_map:
            return {"primary": [], "secondary": [], "avoid": [], "trade_styles": []}
        
        config = self.context_map[context]
        
        # Filter by risk level
        risk_order = ["Low", "Medium", "High"]
        max_risk_idx = risk_order.index(max_risk) if max_risk in risk_order else 2
        
        def filter_by_risk(strategies):
            result = []
            for s in strategies:
                risk = self.risk_levels.get(s, "Medium")
                if risk_order.index(risk) <= max_risk_idx:
                    result.append(s)
            return result
        
        primary = filter_by_risk(config.get("primary", []))
        secondary = filter_by_risk(config.get("secondary", [])) if include_secondary else []
        
        # If aggressive sub-type, include aggressive strategies
        aggressive_only = []
        if sub_type == "AGGRESSIVE":
            aggressive_only = filter_by_risk(config.get("aggressive_only", []))
        
        return {
            "primary": primary,
            "secondary": secondary,
            "aggressive_only": aggressive_only,
            "avoid": config.get("avoid", []),
            "trade_styles": config.get("trade_styles", []),
            "all_recommended": list(set(primary + secondary + aggressive_only))
        }
    
    def filter_scan_results(
        self, 
        scan_results: List[Dict],
        market_contexts: Dict[str, Dict],
        smart_filter: bool = True
    ) -> List[Dict]:
        """
        Filter and annotate scan results based on market context
        """
        enhanced_results = []
        
        for result in scan_results:
            symbol = result.get("symbol", "")
            context_data = market_contexts.get(symbol, {})
            market_context = context_data.get("market_context", "")
            sub_type = context_data.get("sub_type")
            
            # Get recommended strategies for this context
            if market_context:
                recommendations = self.get_recommended_strategies(market_context, sub_type)
                recommended_ids = set(recommendations.get("all_recommended", []))
                avoid_ids = set(recommendations.get("avoid", []))
            else:
                recommended_ids = set()
                avoid_ids = set()
            
            # Annotate matched strategies
            matched = result.get("matched_strategies", [])
            annotated_matches = []
            context_match_count = 0
            
            for strategy_id in matched:
                is_recommended = strategy_id in recommended_ids
                is_avoid = strategy_id in avoid_ids
                
                if is_recommended:
                    context_match_count += 1
                
                annotated_matches.append({
                    "id": strategy_id,
                    "is_context_match": is_recommended,
                    "is_avoid": is_avoid,
                    "risk": self.risk_levels.get(strategy_id, "Medium")
                })
            
            # Calculate context alignment score
            if matched:
                context_alignment = round(context_match_count / len(matched) * 100)
            else:
                context_alignment = 0
            
            # Enhanced result
            enhanced = {
                **result,
                "market_context": market_context,
                "context_sub_type": sub_type,
                "context_confidence": context_data.get("confidence", 0),
                "annotated_strategies": annotated_matches,
                "context_match_count": context_match_count,
                "context_alignment": context_alignment,
                "recommended_styles": recommendations.get("trade_styles", []) if market_context else [],
                "strategies_to_avoid": list(avoid_ids & set(matched))
            }
            
            # Apply smart filter if enabled - prioritize context-aligned results
            if smart_filter:
                # Add context bonus to score
                enhanced["smart_score"] = result.get("score", 0) + (context_alignment * 0.5)
            else:
                enhanced["smart_score"] = result.get("score", 0)
            
            enhanced_results.append(enhanced)
        
        # Sort by smart score if filtering is enabled
        if smart_filter:
            enhanced_results.sort(key=lambda x: x["smart_score"], reverse=True)
        
        return enhanced_results
    
    def get_top_strategies_for_context(
        self, 
        market_context: str,
        all_strategies: Dict,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get the top recommended strategies with full details for a context
        """
        recommendations = self.get_recommended_strategies(market_context)
        primary_ids = recommendations.get("primary", [])
        
        result = []
        for category, strategies in all_strategies.items():
            for strategy in strategies:
                if strategy["id"] in primary_ids:
                    result.append({
                        **strategy,
                        "priority": "primary" if strategy["id"] in primary_ids else "secondary",
                        "risk": self.risk_levels.get(strategy["id"], "Medium")
                    })
        
        return result[:limit]
    
    def get_context_strategy_matrix(self) -> Dict:
        """
        Return a matrix showing which strategies work best for each context
        """
        matrix = {}
        
        for context, config in self.context_map.items():
            all_strats = set(config.get("primary", []) + config.get("secondary", []))
            matrix[context] = {
                "count": len(all_strats),
                "primary_count": len(config.get("primary", [])),
                "trade_styles": config.get("trade_styles", []),
                "top_3": config.get("primary", [])[:3]
            }
        
        return matrix


# Singleton instance
_strategy_service: Optional[StrategyRecommendationService] = None

def get_strategy_recommendation_service() -> StrategyRecommendationService:
    """Get or create the strategy recommendation service singleton"""
    global _strategy_service
    if _strategy_service is None:
        _strategy_service = StrategyRecommendationService()
    return _strategy_service
