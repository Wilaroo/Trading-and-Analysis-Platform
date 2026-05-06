"""
Context Awareness Service
=========================
Phase 2 AI Prompt Intelligence Plan

Provides context-aware data for AI agents to make smarter, more relevant responses:
1. Time-of-day awareness (pre-market, market open, midday, close, after-hours)
2. Market regime awareness (RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN)
3. Position awareness (user's open positions, exposure, P&L)

This service aggregates context from multiple sources and provides
tailored recommendations based on the current trading environment.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TradingSession(str, Enum):
    """Trading session phases"""
    PRE_MARKET = "pre_market"           # 4:00 AM - 9:30 AM ET
    MARKET_OPEN = "market_open"         # 9:30 AM - 10:30 AM ET
    MORNING = "morning"                 # 10:30 AM - 12:00 PM ET
    MIDDAY = "midday"                   # 12:00 PM - 2:00 PM ET
    AFTERNOON = "afternoon"             # 2:00 PM - 3:30 PM ET
    MARKET_CLOSE = "market_close"       # 3:30 PM - 4:00 PM ET
    AFTER_HOURS = "after_hours"         # 4:00 PM - 8:00 PM ET
    OVERNIGHT = "overnight"             # 8:00 PM - 4:00 AM ET
    WEEKEND = "weekend"                 # Saturday/Sunday


@dataclass
class SessionContext:
    """Time-based trading session context"""
    session: TradingSession
    session_name: str
    time_until_next_session: str
    trading_advice: str
    risk_level: str  # "high", "medium", "low"
    strategy_suggestions: List[str] = field(default_factory=list)
    avoid_strategies: List[str] = field(default_factory=list)


@dataclass
class RegimeContext:
    """Market regime context"""
    state: str  # RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
    score: float
    risk_level: float
    confidence: float
    recommendation: str
    position_sizing_multiplier: float
    favored_strategies: List[str] = field(default_factory=list)
    trading_implications: Dict = field(default_factory=dict)


@dataclass
class PositionContext:
    """User's position context"""
    has_positions: bool
    position_count: int
    total_exposure: float
    long_exposure: float
    short_exposure: float
    unrealized_pnl: float
    largest_position: Optional[Dict] = None
    at_risk_positions: List[Dict] = field(default_factory=list)
    profitable_positions: List[Dict] = field(default_factory=list)
    concentration_warning: Optional[str] = None


@dataclass 
class FullContext:
    """Complete trading context for AI agents"""
    session: SessionContext
    regime: RegimeContext
    positions: PositionContext
    combined_advice: str
    risk_factors: List[str] = field(default_factory=list)
    opportunities: List[str] = field(default_factory=list)


class ContextAwarenessService:
    """
    Provides context-aware data for smarter AI responses.
    
    Usage:
        context_service = ContextAwarenessService(regime_engine, data_fetcher)
        full_context = await context_service.get_full_context()
        
        # Use in prompts:
        prompt = f"Given the current context: {full_context.combined_advice}..."
    """
    
    def __init__(self, regime_engine=None, db=None):
        self._regime_engine = regime_engine
        self._db = db
        
    def set_regime_engine(self, engine):
        """Set the market regime engine"""
        self._regime_engine = engine
        
    def set_db(self, db):
        """Set the database connection"""
        self._db = db
    
    # ========== Time-of-Day Awareness ==========
    
    def get_session_context(self) -> SessionContext:
        """
        Get the current trading session context.
        Returns advice tailored to the time of day.
        """
        now = datetime.now(timezone.utc)
        # Convert to Eastern Time (US markets)
        # UTC-5 (EST) or UTC-4 (EDT) - simplified to UTC-5 for consistency
        et_hour = (now.hour - 5) % 24
        et_minute = now.minute
        et_weekday = now.weekday()
        
        # Check for weekend
        if et_weekday >= 5:  # Saturday = 5, Sunday = 6
            return SessionContext(
                session=TradingSession.WEEKEND,
                session_name="Weekend",
                time_until_next_session=self._time_until_market_open(now),
                trading_advice="Markets are closed. Use this time to review your trading week, update your game plan, and prepare for Monday.",
                risk_level="low",
                strategy_suggestions=["Review trade journal", "Backtest strategies", "Study market structure"],
                avoid_strategies=["No live trading on weekends"]
            )
        
        # Determine session based on Eastern Time
        current_time = et_hour * 60 + et_minute  # Minutes from midnight ET
        
        if current_time < 4 * 60:  # Before 4 AM ET
            session = TradingSession.OVERNIGHT
            session_name = "Overnight"
            advice = "Markets are closed. Review any overnight developments when pre-market opens at 4 AM ET."
            risk = "low"
            suggestions = ["Check futures", "Review overnight news"]
            avoid = ["No trading available"]
            
        elif current_time < 9 * 60 + 30:  # 4:00 AM - 9:30 AM ET
            session = TradingSession.PRE_MARKET
            session_name = "Pre-Market"
            advice = "Pre-market session. Liquidity is lower - use wider stops. Watch for gap setups and news catalysts. Finalize your watchlist."
            risk = "medium"
            suggestions = ["Gap analysis", "News-driven setups", "Build watchlist", "Check earnings/economic calendar"]
            avoid = ["Large positions", "Tight stops (low liquidity)"]
            
        elif current_time < 10 * 60 + 30:  # 9:30 AM - 10:30 AM ET
            session = TradingSession.MARKET_OPEN
            session_name = "Market Open (Power Hour)"
            advice = "MARKET OPEN - Highest volatility period. ORB setups active. Wait for price discovery (first 5-15 min) then look for momentum plays. This is prime scalping time."
            risk = "high"
            suggestions = ["ORB (Opening Range Breakout)", "Gap and Go", "First pullback to VWAP", "Momentum scalps"]
            avoid = ["Counter-trend trades", "Swing entries (wait for confirmation)"]
            
        elif current_time < 12 * 60:  # 10:30 AM - 12:00 PM ET
            session = TradingSession.MORNING
            session_name = "Morning Session"
            advice = "Late morning - volatility settling. Good for continuation trades. VWAP becomes more reliable as an indicator."
            risk = "medium"
            suggestions = ["Trend continuation", "VWAP bounce/fade", "Range breakouts", "Second chance entries"]
            avoid = ["Forcing trades in choppy action"]
            
        elif current_time < 14 * 60:  # 12:00 PM - 2:00 PM ET
            session = TradingSession.MIDDAY
            session_name = "Midday Lull"
            advice = "MIDDAY - Typically low volume/choppy. Many pro traders take a break. Best for reviewing morning trades, not initiating new ones. Wait for afternoon momentum."
            risk = "low"
            suggestions = ["Review morning trades", "Adjust stops on winners", "Prepare afternoon watchlist"]
            avoid = ["New position entries", "Breakout trades (likely false)"]
            
        elif current_time < 15 * 60 + 30:  # 2:00 PM - 3:30 PM ET
            session = TradingSession.AFTERNOON
            session_name = "Afternoon Session"
            advice = "Afternoon - Volume picking up. Institutions rebalancing. Good for trend resumption trades. Watch for late-day momentum."
            risk = "medium"
            suggestions = ["Trend continuation", "Breakout trades (with volume)", "Swing entries for overnight holds"]
            avoid = ["Mean reversion (strong trends often continue)"]
            
        elif current_time < 16 * 60:  # 3:30 PM - 4:00 PM ET
            session = TradingSession.MARKET_CLOSE
            session_name = "Market Close (Power Hour)"
            advice = "MARKET CLOSE - High volume period. Institutions closing/opening positions. MOC (Market on Close) orders create volatility. Either ride momentum or flatten for the day."
            risk = "high"
            suggestions = ["Momentum trades with tight stops", "Close intraday positions", "Swing entries if strong trend"]
            avoid = ["Counter-trend trades", "New scalps (too close to close)"]
            
        elif current_time < 20 * 60:  # 4:00 PM - 8:00 PM ET
            session = TradingSession.AFTER_HOURS
            session_name = "After Hours"
            advice = "After-hours session. Low liquidity - wide spreads. Only trade on significant news/earnings. Otherwise, review the day and prepare for tomorrow."
            risk = "medium"
            suggestions = ["Earnings plays (with caution)", "React to material news"]
            avoid = ["Regular trading (low liquidity)", "Tight stops"]
            
        else:  # 8:00 PM - midnight ET
            session = TradingSession.OVERNIGHT
            session_name = "Overnight"
            advice = "Markets closed. Review your trades, update your journal, and rest. Preparation for tomorrow is more valuable than screen time."
            risk = "low"
            suggestions = ["Trade review", "Journal entries", "Tomorrow's prep"]
            avoid = ["No trading available"]
        
        return SessionContext(
            session=session,
            session_name=session_name,
            time_until_next_session=self._get_time_until_next(current_time),
            trading_advice=advice,
            risk_level=risk,
            strategy_suggestions=suggestions,
            avoid_strategies=avoid
        )
    
    def _time_until_market_open(self, now: datetime) -> str:
        """Calculate time until next market open (9:30 AM ET Monday-Friday)"""
        # Simplified calculation
        et_weekday = now.weekday()
        if et_weekday == 5:  # Saturday
            return "~53 hours until market open"
        elif et_weekday == 6:  # Sunday
            return "~29 hours until market open"
        return "Market opens at 9:30 AM ET"
    
    def _get_time_until_next(self, current_minutes: int) -> str:
        """Get time until next trading session"""
        session_starts = {
            4 * 60: "Pre-Market",
            9 * 60 + 30: "Market Open",
            10 * 60 + 30: "Morning Session",
            12 * 60: "Midday",
            14 * 60: "Afternoon",
            15 * 60 + 30: "Market Close",
            16 * 60: "After Hours"
        }
        
        for start_time, name in sorted(session_starts.items()):
            if current_minutes < start_time:
                mins_until = start_time - current_minutes
                hours = mins_until // 60
                mins = mins_until % 60
                if hours > 0:
                    return f"{hours}h {mins}m until {name}"
                return f"{mins}m until {name}"
        
        return "Market close in progress"
    
    # ========== Market Regime Awareness ==========
    
    async def get_regime_context(self) -> RegimeContext:
        """
        Get the current market regime context.
        Returns recommendations based on market conditions.
        """
        if not self._regime_engine:
            return RegimeContext(
                state="UNKNOWN",
                score=50,
                risk_level=50,
                confidence=0,
                recommendation="Market regime data unavailable. Trade with normal caution.",
                position_sizing_multiplier=1.0,
                favored_strategies=[]
            )
        
        try:
            regime_data = await self._regime_engine.get_current_regime()
            
            state = regime_data.get("state", "HOLD")
            score = regime_data.get("composite_score", 50)
            risk_level = regime_data.get("risk_level", 50)
            confidence = regime_data.get("confidence", 50)
            
            # Determine position sizing multiplier based on regime
            multipliers = {
                "RISK_ON": 1.0,
                "CONFIRMED_UP": 1.0,
                "CAUTION": 0.75,
                "HOLD": 0.75,
                "RISK_OFF": 0.5,
                "CONFIRMED_DOWN": 0.25
            }
            multiplier = multipliers.get(state, 0.75)
            
            # Get trading implications
            implications = regime_data.get("trading_implications", {})
            favored = implications.get("favored_strategies", [])
            
            return RegimeContext(
                state=state,
                score=score,
                risk_level=risk_level,
                confidence=confidence,
                recommendation=regime_data.get("recommendation", ""),
                position_sizing_multiplier=multiplier,
                favored_strategies=favored,
                trading_implications=implications
            )
            
        except Exception as e:
            logger.error(f"Error getting regime context: {e}")
            return RegimeContext(
                state="ERROR",
                score=50,
                risk_level=50,
                confidence=0,
                recommendation=f"Error fetching regime data: {str(e)}",
                position_sizing_multiplier=0.75
            )
    
    # ========== Position Awareness ==========
    
    async def get_position_context(self) -> PositionContext:
        """
        Get the user's current position context.
        Returns exposure analysis and risk warnings.
        """
        try:
            # Import here to avoid circular imports
            import routers.ib as ib_module
            positions = ib_module.get_pushed_positions()
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            positions = []
        
        if not positions:
            return PositionContext(
                has_positions=False,
                position_count=0,
                total_exposure=0,
                long_exposure=0,
                short_exposure=0,
                unrealized_pnl=0
            )
        
        total_exposure = 0
        long_exposure = 0
        short_exposure = 0
        unrealized_pnl = 0
        largest_position = None
        largest_value = 0
        at_risk = []
        profitable = []
        
        for pos in positions:
            shares = float(pos.get("position", pos.get("shares", 0)) or 0)
            price = float(pos.get("marketPrice", pos.get("current_price", 0)) or 0)
            avg_cost = float(pos.get("avgCost", pos.get("averageCost", 0)) or 0)
            pnl = float(pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)) or 0)
            
            position_value = abs(shares * price)
            total_exposure += position_value
            unrealized_pnl += pnl
            
            if shares > 0:
                long_exposure += position_value
            else:
                short_exposure += position_value
            
            # Track largest position
            if position_value > largest_value:
                largest_value = position_value
                largest_position = {
                    "symbol": pos.get("symbol", "?"),
                    "shares": shares,
                    "value": position_value,
                    "pnl": pnl,
                    "pnl_pct": ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
                }
            
            # Categorize positions
            pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            pos_info = {
                "symbol": pos.get("symbol", "?"),
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "value": position_value
            }
            
            if pnl < 0 and pnl_pct < -3:  # Down more than 3%
                at_risk.append(pos_info)
            elif pnl > 0:
                profitable.append(pos_info)
        
        # Check for concentration risk
        concentration_warning = None
        if largest_position and total_exposure > 0:
            largest_pct = (largest_position["value"] / total_exposure) * 100
            if largest_pct > 40:
                concentration_warning = f"High concentration: {largest_position['symbol']} is {largest_pct:.0f}% of your exposure"
            elif largest_pct > 30:
                concentration_warning = f"Elevated concentration: {largest_position['symbol']} is {largest_pct:.0f}% of your exposure"
        
        return PositionContext(
            has_positions=True,
            position_count=len(positions),
            total_exposure=total_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            unrealized_pnl=unrealized_pnl,
            largest_position=largest_position,
            at_risk_positions=sorted(at_risk, key=lambda x: x["pnl"])[:3],
            profitable_positions=sorted(profitable, key=lambda x: -x["pnl"])[:3],
            concentration_warning=concentration_warning
        )
    
    # ========== Combined Context ==========
    
    async def get_full_context(self) -> FullContext:
        """
        Get the complete trading context combining all awareness types.
        """
        session_ctx = self.get_session_context()
        regime_ctx = await self.get_regime_context()
        position_ctx = await self.get_position_context()
        
        # Build combined advice based on all context
        combined_advice = self._build_combined_advice(session_ctx, regime_ctx, position_ctx)
        
        # Identify risk factors
        risk_factors = self._identify_risk_factors(session_ctx, regime_ctx, position_ctx)
        
        # Identify opportunities
        opportunities = self._identify_opportunities(session_ctx, regime_ctx, position_ctx)
        
        return FullContext(
            session=session_ctx,
            regime=regime_ctx,
            positions=position_ctx,
            combined_advice=combined_advice,
            risk_factors=risk_factors,
            opportunities=opportunities
        )
    
    def _build_combined_advice(self, session: SessionContext, 
                               regime: RegimeContext, 
                               positions: PositionContext) -> str:
        """Build combined trading advice from all context sources."""
        
        lines = []
        
        # Session-based advice
        lines.append(f"**Current Session**: {session.session_name}")
        lines.append(f"- {session.trading_advice}")
        
        # Regime-based advice
        if regime.state != "UNKNOWN":
            regime_emoji = {
                "RISK_ON": "🟢", "CONFIRMED_UP": "🟢",
                "CAUTION": "🟡", "HOLD": "🟡",
                "RISK_OFF": "🟠",
                "CONFIRMED_DOWN": "🔴"
            }.get(regime.state, "⚪")
            
            lines.append(f"\n**Market Regime**: {regime_emoji} {regime.state} (Score: {regime.score:.0f})")
            lines.append(f"- {regime.recommendation}")
            lines.append(f"- Position Sizing: {regime.position_sizing_multiplier * 100:.0f}% of normal")
        
        # Position-based advice
        if positions.has_positions:
            pnl_emoji = "🟢" if positions.unrealized_pnl >= 0 else "🔴"
            lines.append(f"\n**Open Positions**: {positions.position_count} | P&L: {pnl_emoji} ${positions.unrealized_pnl:,.2f}")
            
            if positions.concentration_warning:
                lines.append(f"- ⚠️ {positions.concentration_warning}")
            
            if positions.at_risk_positions:
                at_risk_symbols = [p["symbol"] for p in positions.at_risk_positions]
                lines.append(f"- ⚠️ At-risk positions: {', '.join(at_risk_symbols)}")
        else:
            lines.append("\n**Open Positions**: None - clean slate for new opportunities")
        
        return "\n".join(lines)
    
    def _identify_risk_factors(self, session: SessionContext,
                               regime: RegimeContext,
                               positions: PositionContext) -> List[str]:
        """Identify current risk factors to consider."""
        risks = []
        
        # Session risks
        if session.session in [TradingSession.MARKET_OPEN, TradingSession.MARKET_CLOSE]:
            risks.append("High volatility period - use wider stops or smaller size")
        if session.session == TradingSession.MIDDAY:
            risks.append("Midday chop - higher chance of false breakouts")
        if session.session in [TradingSession.PRE_MARKET, TradingSession.AFTER_HOURS]:
            risks.append("Low liquidity - wider spreads, harder fills")
        
        # Regime risks
        if regime.state in ["CONFIRMED_DOWN", "RISK_OFF"]:
            risks.append("Bearish regime - longs have headwind")
        if regime.confidence < 50:
            risks.append("Mixed market signals - lower conviction environment")
        
        # Position risks
        if positions.concentration_warning:
            risks.append(positions.concentration_warning)
        if positions.at_risk_positions:
            risks.append(f"{len(positions.at_risk_positions)} position(s) underwater - manage risk")
        if positions.total_exposure > 100000:  # Arbitrary threshold
            risks.append("High total exposure - consider reducing")
        
        return risks
    
    def _identify_opportunities(self, session: SessionContext,
                                regime: RegimeContext,
                                positions: PositionContext) -> List[str]:
        """Identify current opportunities."""
        opps = []
        
        # Session opportunities
        if session.session == TradingSession.MARKET_OPEN:
            opps.append("ORB setups active - prime momentum trading window")
        if session.session == TradingSession.AFTERNOON:
            opps.append("Afternoon momentum often continues - trend plays viable")
        
        # Regime opportunities
        if regime.state in ["RISK_ON", "CONFIRMED_UP"]:
            opps.append("Bullish regime - momentum longs have tailwind")
        if regime.favored_strategies:
            opps.append(f"Favored strategies: {', '.join(regime.favored_strategies[:3])}")
        
        # Position opportunities
        if not positions.has_positions:
            opps.append("No positions - full buying power available for best setups")
        if positions.profitable_positions:
            profitable_syms = [p["symbol"] for p in positions.profitable_positions]
            opps.append(f"Winners running: {', '.join(profitable_syms)} - consider adding on strength")
        
        return opps
    
    # ========== Prompt Enhancement ==========
    
    async def get_context_for_prompt(self) -> str:
        """
        Get a formatted context string to inject into AI prompts.
        This is the primary method for agents to use.
        """
        full_ctx = await self.get_full_context()
        
        lines = [
            "=== CURRENT TRADING CONTEXT ===",
            "",
            f"**Session**: {full_ctx.session.session_name} ({full_ctx.session.risk_level} risk period)",
            f"**Regime**: {full_ctx.regime.state} (Score: {full_ctx.regime.score:.0f}/100, Confidence: {full_ctx.regime.confidence:.0f}%)",
        ]
        
        if full_ctx.positions.has_positions:
            pnl_str = f"${full_ctx.positions.unrealized_pnl:,.2f}"
            lines.append(f"**Positions**: {full_ctx.positions.position_count} open | Exposure: ${full_ctx.positions.total_exposure:,.0f} | P&L: {pnl_str}")
        else:
            lines.append("**Positions**: None")
        
        lines.append("")
        lines.append("**Session Advice**: " + full_ctx.session.trading_advice)
        lines.append("**Regime Advice**: " + full_ctx.regime.recommendation)
        
        if full_ctx.risk_factors:
            lines.append("")
            lines.append("**Risk Factors**:")
            for risk in full_ctx.risk_factors[:3]:
                lines.append(f"  - {risk}")
        
        if full_ctx.opportunities:
            lines.append("")
            lines.append("**Opportunities**:")
            for opp in full_ctx.opportunities[:3]:
                lines.append(f"  - {opp}")
        
        lines.append("")
        lines.append("=== END CONTEXT ===")
        
        return "\n".join(lines)


# Singleton instance
_context_service: Optional[ContextAwarenessService] = None


def get_context_awareness_service() -> ContextAwarenessService:
    """Get the singleton context awareness service."""
    global _context_service
    if _context_service is None:
        _context_service = ContextAwarenessService()
    return _context_service


def init_context_awareness_service(regime_engine=None, db=None) -> ContextAwarenessService:
    """Initialize the context awareness service with dependencies."""
    global _context_service
    _context_service = ContextAwarenessService(regime_engine, db)
    return _context_service
