"""
AI Market Intelligence Service
Aggregates ALL available data sources to provide comprehensive context
for the AI assistant:

- Real-time technical analysis (from Alpaca bars)
- Fundamental data (from Finnhub)
- Trade alerts (scalp, swing, position)
- Market regime and context
- User's trading rules and strategies
- Pattern detection

This is the AI's "brain" for market analysis.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MarketIntelligenceContext:
    """Complete market intelligence context for AI"""
    timestamp: str
    
    # Market regime
    market_regime: str  # "bull", "bear", "choppy", "trending"
    spy_trend: str
    vix_level: str
    
    # Active alerts
    scalp_alerts_now: List[Dict]
    scalp_alerts_watch: List[Dict]
    swing_alerts_today: List[Dict]
    swing_alerts_week: List[Dict]
    
    # Forming setups count
    total_setups_forming: int
    
    # Best opportunities
    best_scalp: Optional[Dict]
    best_swing: Optional[Dict]
    
    # Time of day context
    trading_session: str  # "pre_market", "opening", "midday", "power_hour", "after_hours"
    time_recommendation: str


class AIMarketIntelligenceService:
    """
    Central service that aggregates all market intelligence
    for the AI assistant.
    """
    
    def __init__(self):
        self._alert_system = None
        self._technical_service = None
        self._fundamental_service = None
        self._scanner = None
        
    @property
    def alert_system(self):
        if self._alert_system is None:
            from services.alert_system import get_alert_system
            self._alert_system = get_alert_system()
        return self._alert_system
    
    @property
    def technical_service(self):
        if self._technical_service is None:
            from services.realtime_technical_service import get_technical_service
            self._technical_service = get_technical_service()
        return self._technical_service
    
    @property
    def fundamental_service(self):
        if self._fundamental_service is None:
            from services.fundamental_data_service import get_fundamental_data_service
            self._fundamental_service = get_fundamental_data_service()
        return self._fundamental_service
    
    async def get_full_context_for_ai(self, symbols: List[str] = None) -> str:
        """
        Get comprehensive market intelligence context for AI.
        This is the main method that aggregates ALL data sources.
        """
        context_parts = []
        
        # 1. TIME AND SESSION CONTEXT
        session_context = self._get_session_context()
        context_parts.append(session_context)
        
        # 2. RUN ALERT SCAN (if symbols provided)
        if symbols:
            try:
                results = await self.alert_system.scan_all_setups(
                    symbols=symbols,
                    include_scalp=True,
                    include_intraday=True,
                    include_swing=True
                )
                
                alert_context = self._format_alert_results(results)
                if alert_context:
                    context_parts.append(alert_context)
            except Exception as e:
                logger.warning(f"Could not scan for alerts: {e}")
        
        # 3. GET EXISTING ALERTS
        try:
            scalp_alerts = self.alert_system.get_scalp_alerts()
            swing_alerts = self.alert_system.get_swing_alerts()
            
            if scalp_alerts.get("setting_up_now") or scalp_alerts.get("on_watch_today"):
                context_parts.append(self._format_scalp_alerts(scalp_alerts))
            
            if swing_alerts.get("setting_up_today") or swing_alerts.get("setting_up_this_week"):
                context_parts.append(self._format_swing_alerts(swing_alerts))
        except Exception as e:
            logger.warning(f"Could not get existing alerts: {e}")
        
        # 4. TECHNICAL SNAPSHOTS FOR KEY SYMBOLS
        key_symbols = symbols[:5] if symbols else ["SPY", "QQQ", "NVDA", "TSLA", "AAPL"]
        try:
            for symbol in key_symbols[:3]:  # Limit to 3 for context size
                snapshot = await self.technical_service.get_technical_snapshot(symbol)
                if snapshot:
                    context_parts.append(self.technical_service.get_snapshot_for_ai(snapshot))
        except Exception as e:
            logger.warning(f"Could not get technical snapshots: {e}")
        
        # Combine all context
        full_context = "\n\n".join([c for c in context_parts if c])
        
        return full_context if full_context else "No market intelligence data available at this time."
    
    def _get_session_context(self) -> str:
        """Get trading session context"""
        now = datetime.now(timezone.utc)
        hour = now.hour - 5  # Convert to ET (approximate)
        
        if hour < 4:
            session = "after_hours"
            recommendation = "After hours - low liquidity, avoid trading unless specific catalyst"
        elif hour < 9.5:
            session = "pre_market"
            recommendation = "Pre-market - watch for gaps and catalysts, prepare watchlist"
        elif hour < 10:
            session = "opening"
            recommendation = "Opening volatility - HitchHiker and ORB setups optimal"
        elif hour < 11.5:
            session = "morning"
            recommendation = "Morning session - best for momentum and breakout trades"
        elif hour < 14:
            session = "midday"
            recommendation = "Midday lull - reduce size 50%, favor mean reversion (Rubber Band)"
        elif hour < 15.5:
            session = "afternoon"
            recommendation = "Afternoon - momentum returning, watch for trend continuations"
        else:
            session = "power_hour"
            recommendation = "Power hour - increased volatility, good for scalps but be cautious"
        
        return f"""
=== TRADING SESSION CONTEXT ===
Current Time: {now.strftime('%H:%M UTC')} ({session.upper()})
Recommendation: {recommendation}
"""
    
    def _format_alert_results(self, results: Dict) -> str:
        """Format fresh scan results"""
        context = "=== FRESH SCAN RESULTS ===\n"
        
        scalp_now = results.get("scalp_now", [])
        scalp_watch = results.get("scalp_watch", [])
        swing_today = results.get("swing_today", [])
        swing_week = results.get("swing_week", [])
        
        if scalp_now:
            context += "\n🔴 SCALP - SETTING UP NOW:\n"
            for alert in scalp_now[:3]:
                context += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()} ({alert.direction.upper()})
  Score: {alert.overall_score} | Win: {alert.win_probability:.0%} | R:R: {alert.risk_reward:.1f}
  Entry: ${alert.trigger_price:.2f} | Stop: ${alert.stop_loss:.2f} | Target: ${alert.target_1:.2f}
  {alert.reasoning.summary[:150]}...
"""
        
        if scalp_watch:
            context += "\n🟡 SCALP - ON WATCH TODAY:\n"
            for alert in scalp_watch[:3]:
                context += f"• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()} (Score: {alert.overall_score})\n"
        
        if swing_today:
            context += "\n📊 SWING - SETTING UP TODAY:\n"
            for alert in swing_today[:3]:
                context += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()}
  Score: {alert.overall_score} | Fundamentals: {alert.fundamental_score}/100
  Win: {alert.win_probability:.0%} | Target: ${alert.target_1:.2f}
"""
        
        if swing_week:
            context += "\n📅 SWING - THIS WEEK:\n"
            for alert in swing_week[:2]:
                context += f"• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()} (Score: {alert.overall_score})\n"
        
        return context
    
    def _format_scalp_alerts(self, alerts: Dict) -> str:
        """Format scalp alerts for AI context"""
        context = "=== SCALP TRADING ALERTS ===\n"
        
        now_alerts = alerts.get("setting_up_now", [])
        watch_alerts = alerts.get("on_watch_today", [])
        
        if now_alerts:
            context += "\n🔴 SETTING UP NOW (Immediate opportunities):\n"
            for alert in now_alerts[:3]:
                context += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()}
  Direction: {alert.direction.upper()}
  Score: {alert.overall_score} | Win Prob: {alert.win_probability:.0%}
  Entry: ${alert.current_price:.2f} → Target: ${alert.target_1:.2f}
  Why: {', '.join(alert.reasoning.technical_reasons[:2])}
"""
        else:
            context += "\nNo scalp setups ready right now.\n"
        
        if watch_alerts:
            context += "\n🟡 ON WATCH FOR LATER TODAY:\n"
            for alert in watch_alerts[:3]:
                context += f"• {alert.symbol}: {alert.setup_type.replace('_', ' ').title()} - developing\n"
        
        return context
    
    def _format_swing_alerts(self, alerts: Dict) -> str:
        """Format swing alerts for AI context"""
        context = "=== SWING TRADING ALERTS ===\n"
        
        today_alerts = alerts.get("setting_up_today", [])
        week_alerts = alerts.get("setting_up_this_week", [])
        
        if today_alerts:
            context += "\n📊 SETTING UP TODAY:\n"
            for alert in today_alerts[:3]:
                context += f"""
• {alert.symbol} - {alert.setup_type.replace('_', ' ').title()}
  Direction: {alert.direction.upper()}
  Overall Score: {alert.overall_score} | Fundamental Score: {alert.fundamental_score}
  Win Prob: {alert.win_probability:.0%} | R:R: {alert.risk_reward:.1f}
  Key Levels: Entry ${alert.current_price:.2f}, Stop ${alert.stop_loss:.2f}, Target ${alert.target_1:.2f}
"""
        
        if week_alerts:
            context += "\n📅 SETTING UP THIS WEEK:\n"
            for alert in week_alerts[:3]:
                context += f"• {alert.symbol}: {alert.setup_type.replace('_', ' ').title()} (Score: {alert.overall_score})\n"
        
        return context
    
    async def get_symbol_deep_dive(self, symbol: str) -> str:
        """
        Get deep-dive analysis for a specific symbol.
        Combines technicals + fundamentals + alerts.
        """
        context_parts = []
        symbol = symbol.upper()
        
        # 1. Technical snapshot
        try:
            snapshot = await self.technical_service.get_technical_snapshot(symbol)
            if snapshot:
                context_parts.append(self.technical_service.get_snapshot_for_ai(snapshot))
        except Exception as e:
            logger.warning(f"Could not get technicals for {symbol}: {e}")
        
        # 2. Fundamental analysis
        try:
            analysis = await self.fundamental_service.analyze_fundamentals(symbol)
            if analysis.get("available"):
                context_parts.append(f"""
=== FUNDAMENTAL ANALYSIS: {symbol} ===
Value Score: {analysis.get('value_score')}/100
Assessment: {analysis.get('assessment')}

Bullish Signals: {'; '.join(analysis.get('signals', [])[:3])}
Warnings: {'; '.join(analysis.get('warnings', [])[:3])}

Key Metrics:
- P/E: {analysis.get('metrics', {}).get('valuation', {}).get('pe_ratio')}
- ROE: {analysis.get('metrics', {}).get('profitability', {}).get('roe')}
- D/E: {analysis.get('metrics', {}).get('financial_health', {}).get('debt_to_equity')}
""")
        except Exception as e:
            logger.warning(f"Could not get fundamentals for {symbol}: {e}")
        
        # 3. Check for active setups
        try:
            market_data = await self.alert_system._get_enhanced_market_data(symbol)
            if market_data:
                in_play = await self.alert_system.check_in_play(symbol, market_data)
                context_parts.append(f"""
=== IN-PLAY STATUS: {symbol} ===
Is In Play: {"YES ✓" if in_play.is_in_play else "NO ✗"}
Score: {in_play.score}/100
RVOL: {in_play.rvol:.1f}x | Gap: {in_play.gap_pct:+.1f}%

Reasons: {', '.join(in_play.reasons[:3]) if in_play.reasons else 'None'}
Concerns: {', '.join(in_play.disqualifiers[:2]) if in_play.disqualifiers else 'None'}
""")
        except Exception as e:
            logger.warning(f"Could not check in-play for {symbol}: {e}")
        
        return "\n\n".join(context_parts) if context_parts else f"Limited data available for {symbol}"
    
    async def scan_and_get_best_opportunities(
        self, 
        symbols: List[str] = None,
        timeframe: str = "scalp"  # "scalp", "swing", "all"
    ) -> str:
        """
        Scan symbols and return best opportunities.
        """
        symbols = symbols or self._get_default_watchlist()
        
        try:
            results = await self.alert_system.scan_all_setups(
                symbols=symbols,
                include_scalp=(timeframe in ["scalp", "all"]),
                include_intraday=(timeframe in ["scalp", "all"]),
                include_swing=(timeframe in ["swing", "all"]),
                include_position=False
            )
            
            return self._format_alert_results(results)
            
        except Exception as e:
            logger.error(f"Error scanning: {e}")
            return "Unable to scan for opportunities at this time."
    
    def _get_default_watchlist(self) -> List[str]:
        """Default watchlist for scanning"""
        return [
            "NVDA", "TSLA", "AMD", "META", "AAPL", "MSFT", "GOOGL", "AMZN",
            "SPY", "QQQ", "NFLX", "BA", "COIN", "SQ", "SHOP"
        ]


# Global instance
_ai_intelligence: Optional[AIMarketIntelligenceService] = None


def get_ai_market_intelligence() -> AIMarketIntelligenceService:
    """Get or create the AI market intelligence service"""
    global _ai_intelligence
    if _ai_intelligence is None:
        _ai_intelligence = AIMarketIntelligenceService()
    return _ai_intelligence
