"""
Coach Agent
Provides personalized trading guidance based on YOUR data and learning layers.
Uses the larger model for reasoning but all data comes from CODE.

Integrates with Three-Speed Learning Architecture:
- LearningLoopService: Trade outcomes, execution tracking, trader profile
- LearningContextProvider: Aggregates TQS, edge decay, calibration, RAG
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentType, AgentResponse, DataFetcher
from agents.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class TradingContext:
    """Context for coaching, built from verified data"""
    positions: List[Dict]
    total_pnl: float
    winning_positions: int
    losing_positions: int
    largest_winner: Optional[Dict]
    largest_loser: Optional[Dict]
    portfolio_exposure: float
    performance_stats: Dict
    similar_past_trades: List[Dict]
    mistake_patterns: List[str]
    market_regime: str
    # New: Learning context from Three-Speed Architecture
    learning_insights: str = ""
    trader_profile: Dict = None
    session_summary: Dict = None


class CoachAgent(BaseAgent):
    """
    Trading coach agent - provides personalized guidance.
    
    Data Flow:
    1. CODE fetches all position/performance data via DataFetcher
    2. LearningContextProvider builds personalized insights (TQS, edge decay, etc.)
    3. LearningLoopService provides trader profile and session stats
    4. LLM reasons over verified data
    5. LLM provides personalized guidance
    
    The LLM never invents numbers - it explains and advises based on real data.
    """
    
    def __init__(self, llm_provider: LLMProvider = None):
        super().__init__(
            agent_type=AgentType.COACH,
            llm_provider=llm_provider,
            model="gpt-oss:120b-cloud"  # Larger model for quality reasoning
        )
        
        self.data_fetcher: Optional[DataFetcher] = None
        # Learning services from Three-Speed Architecture
        self._learning_context_provider = None
        self._learning_loop_service = None
        # Phase 2: Context Awareness Service
        self._context_awareness = None
    
    def inject_services(self, services: Dict[str, Any]):
        """Inject services and create data fetcher"""
        super().inject_services(services)
        self.data_fetcher = DataFetcher(services)
        
        # Wire up learning services
        self._learning_context_provider = services.get("learning_context_provider")
        self._learning_loop_service = services.get("learning_loop_service")
        
        # Wire up context awareness service (Phase 2)
        self._context_awareness = services.get("context_awareness")
        
        if self._learning_context_provider:
            logger.info("Coach Agent: LearningContextProvider connected")
        if self._learning_loop_service:
            logger.info("Coach Agent: LearningLoopService connected")
        if self._context_awareness:
            logger.info("Coach Agent: ContextAwarenessService connected (Phase 2)")
    
    def get_system_prompt(self) -> str:
        """System prompt for coaching - now context-aware (Phase 2) with Team Brain 'we' voice"""
        return """You are part of a trading team. You speak as "we" - the human trader and AI working together as partners.

VOICE: Always use "we", "our", "us" - never "I recommend you" or "your positions". We're a team.

Examples:
- "We're up 2.4% on NVDA today"
- "Our pullback win rate is 67%"  
- "We should consider trailing this winner"
- "Based on our history, we tend to get stopped out on tight stops"

CRITICAL RULES:
1. ONLY reference numbers that appear in the VERIFIED DATA section below
2. NEVER invent or estimate any numbers
3. Reference OUR specific patterns and history (not "your" patterns)
4. Be encouraging but honest about areas for improvement
5. Give actionable advice based on OUR actual performance
6. Consider the CURRENT TRADING CONTEXT (time of day, market regime, open positions)

CONTEXT-AWARE COACHING (Phase 2):
- Adjust advice based on the current trading session (pre-market, open, midday, close)
- Factor in the market regime (bullish/bearish/neutral) when recommending trades
- Consider the trader's existing positions before suggesting new entries
- Warn about timing-specific risks (e.g., midday chop, close volatility)

Your coaching should:
- Reference their specific win rate, not general statistics
- Point out patterns in THEIR trading (from the data provided)
- Suggest improvements based on THEIR mistakes
- Celebrate THEIR wins with specific examples
- Warn about THEIR common pitfalls
- Consider current market conditions in all advice

Keep responses concise but insightful. Use their actual numbers."""
    
    async def process(self, input_data: Dict[str, Any]) -> AgentResponse:
        """
        Process a coaching request.
        
        Flow:
        1. Fetch all relevant data from CODE
        2. Build coaching context from learning layers
        3. Have LLM reason over verified data (or provide raw data if LLM unavailable)
        4. Return personalized guidance
        
        Supports conversation_history for multi-turn context.
        """
        start = time.time()
        message = input_data.get("message", "")
        query_type = input_data.get("query_type", "general")  # general, position, performance, trade_decision, market_context
        symbol = input_data.get("symbol")
        conversation_history = input_data.get("conversation_history", [])
        
        # Handle market overview requests separately
        if query_type == "market_context":
            return await self._handle_market_overview(message, start, conversation_history)
        
        # Step 1: Fetch verified data from CODE
        context = await self._build_coaching_context(symbol)
        
        # For position queries, return data even if LLM is unavailable
        if query_type == "position":
            # Build position summary from CODE (no LLM needed)
            position_text = self._format_positions_for_display(context)
            model_used = "code_only"
            
            # Try to get LLM commentary (but don't fail if unavailable)
            try:
                prompt = self._build_coaching_prompt(message, context, query_type)
                response = await self._call_llm(
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=800
                )
                if response.success:
                    position_text = response.content
                    model_used = response.model
            except Exception as e:
                logger.warning(f"LLM unavailable for position commentary: {e}")
            
            return self._create_response(
                success=True,
                content={
                    "message": position_text,
                    "context_used": {
                        "positions_count": len(context.positions),
                        "total_pnl": context.total_pnl,
                        "performance_available": bool(context.performance_stats)
                    },
                    "positions": context.positions  # Include raw position data
                },
                latency_ms=(time.time() - start) * 1000,
                model_used=model_used,
                metadata={"query_type": query_type}
            )
        
        # Step 2: Build prompt with verified data (async to include trading context)
        prompt = await self._build_coaching_prompt_async(message, context, query_type, conversation_history)
        
        # Step 3: Get LLM guidance (reasoning over verified data)
        response = await self._call_llm(
            prompt=prompt,
            temperature=0.7,
            max_tokens=1500
        )
        
        if not response.success:
            # Return basic info when LLM is unavailable
            # Also include session info from context awareness
            session_info = ""
            if self._context_awareness:
                try:
                    session_ctx = self._context_awareness.get_session_context()
                    session_info = f"\n**Current Session**: {session_ctx.session_name}\n- {session_ctx.trading_advice}"
                except Exception:
                    pass
            
            basic_response = f"""**Connection Status**: Your local trading system appears to be offline.

**Portfolio Summary (from last sync)**:
- Total Positions: {len(context.positions)}
- Total P&L: ${context.total_pnl:,.2f}
- Winning: {context.winning_positions} | Losing: {context.losing_positions}
{session_info}

Please ensure your local IB Gateway and data pusher are running."""
            
            return self._create_response(
                success=True,  # Still success - we provided useful info
                content={"message": basic_response},
                latency_ms=(time.time() - start) * 1000,
                error=response.error,
                metadata={"llm_available": False, "context_aware": bool(session_info)}
            )
        
        return self._create_response(
            success=True,
            content={
                "message": response.content,
                "context_used": {
                    "positions_count": len(context.positions),
                    "total_pnl": context.total_pnl,
                    "performance_available": bool(context.performance_stats)
                }
            },
            latency_ms=(time.time() - start) * 1000,
            model_used=response.model,
            metadata={"query_type": query_type}
        )
    
    async def _handle_market_overview(self, message: str, start: float, 
                                       conversation_history: List = None) -> AgentResponse:
        """Handle 'what's happening in the market' type questions"""
        import httpx
        import os
        
        # Fetch market regime data via API (most reliable)
        regime_data = {}
        try:
            async with httpx.AsyncClient() as client:
                # Use internal API call
                resp = await client.get("http://localhost:8001/api/market-regime/current", timeout=5.0)
                if resp.status_code == 200:
                    regime_data = resp.json()
        except Exception as e:
            logger.warning(f"Could not fetch regime data via API: {e}")
            # Fallback to direct engine call
            try:
                from services.market_regime_engine import get_regime_engine
                engine = get_regime_engine()
                if engine:
                    regime_data = engine.get_current_state() or {}
            except Exception as e2:
                logger.warning(f"Could not fetch regime from engine: {e2}")
        
        # Fetch index data from IB if available
        index_data = {}
        try:
            if self._ib_router:
                quotes = await self._ib_router.get_quotes(["SPY", "QQQ", "IWM", "DIA"])
                for q in quotes:
                    sym = q.get("symbol", "")
                    index_data[sym] = {
                        "price": q.get("last", q.get("close", 0)),
                        "change": q.get("change", 0),
                        "change_pct": q.get("changePercent", 0)
                    }
        except Exception as e:
            logger.debug(f"Could not fetch index quotes: {e}")
        
        # Build market overview text
        regime_state = regime_data.get("state", "UNKNOWN")
        regime_score = regime_data.get("composite_score", 50)
        risk_level = regime_data.get("risk_level", 50)
        recommendation = regime_data.get("recommendation", "No recommendation available")
        
        # Format regime display
        regime_emoji = {
            "RISK_ON": "🟢",
            "CAUTION": "🟡", 
            "HOLD": "🟡",
            "RISK_OFF": "🟠",
            "CONFIRMED_DOWN": "🔴"
        }.get(regime_state, "⚪")
        
        overview = f"""## Market Overview

### Market Regime: {regime_emoji} {regime_state}
- **Composite Score**: {regime_score}/100
- **Risk Level**: {risk_level}%

"""
        # Add index data if available
        if index_data:
            overview += "### Major Indices\n"
            for sym in ["SPY", "QQQ", "IWM", "DIA"]:
                if sym in index_data:
                    d = index_data[sym]
                    emoji = "🟢" if d["change_pct"] >= 0 else "🔴"
                    overview += f"- **{sym}**: ${d['price']:.2f} {emoji} {d['change_pct']:+.2f}%\n"
            overview += "\n"
        
        # Add regime signals from signal_blocks
        signal_blocks = regime_data.get("signal_blocks", {})
        if signal_blocks:
            overview += "### Regime Signals\n"
            for key in ["trend", "breadth", "ftd", "volume_vix"]:
                if key in signal_blocks:
                    block = signal_blocks[key]
                    score = block.get("score", 50)
                    score_emoji = "🟢" if score >= 60 else "🟡" if score >= 40 else "🔴"
                    display_name = key.replace('_', '/').upper() if key == "volume_vix" else key.upper()
                    overview += f"- **{display_name}**: {score}/100 {score_emoji}\n"
            overview += "\n"
        
        # Add trading implications if available
        implications = regime_data.get("trading_implications", {})
        if implications:
            overview += "### Trading Implications\n"
            overview += f"- **Position Sizing**: {implications.get('position_sizing', 'Normal')}\n"
            overview += f"- **Risk Tolerance**: {implications.get('risk_tolerance', 'Normal')}\n"
            favored = implications.get('favored_strategies', [])
            if favored:
                overview += f"- **Favored Strategies**: {', '.join(favored[:3])}\n"
            overview += "\n"
        
        # Add recommendation
        overview += f"### Recommendation\n{recommendation}\n"
        
        # Try to get LLM commentary on the market
        try:
            prompt = f"""Based on this market data, provide a brief 2-3 sentence market outlook:

Market Regime: {regime_state} (Score: {regime_score}/100)
Risk Level: {risk_level}%
Recommendation: {recommendation}

What should a trader focus on today? Be concise and actionable."""

            response = await self._call_llm(prompt=prompt, temperature=0.7, max_tokens=200)
            if response.success and response.content:
                overview += f"\n### AI Insight\n{response.content}\n"
        except Exception as e:
            logger.debug(f"LLM commentary not available: {e}")
        
        return self._create_response(
            success=True,
            content={"message": overview},
            latency_ms=(time.time() - start) * 1000,
            model_used="code_hybrid",
            metadata={"query_type": "market_context"}
        )
    
    def _format_positions_for_display(self, context: TradingContext) -> str:
        """Format positions as text (no LLM needed)"""
        if not context.positions:
            return """**Your Current Positions**: None

You have no open positions at this time."""
        
        lines = ["**Your Current Positions**:\n"]
        for pos in context.positions:
            symbol = pos.get("symbol", "?")
            shares = pos.get("position", pos.get("shares", 0))
            price = pos.get("marketPrice", pos.get("current_price", 0))
            avg_cost = pos.get("avgCost", pos.get("averageCost", 0))
            pnl = pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0))
            pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
            
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{emoji} **{symbol}**: {shares:,.0f} shares @ ${avg_cost:.2f} → ${price:.2f} | P&L: ${pnl:,.2f} ({pnl_pct:+.1f}%)")
        
        lines.append("\n**Portfolio Summary**:")
        lines.append(f"- Total P&L: ${context.total_pnl:,.2f}")
        lines.append(f"- Winners: {context.winning_positions} | Losers: {context.losing_positions}")
        lines.append(f"- Exposure: ${context.portfolio_exposure:,.2f}")
        
        return "\n".join(lines)
    
    async def _build_coaching_context(self, symbol: str = None) -> TradingContext:
        """
        Build coaching context from CODE (verified data only).
        Integrates with Three-Speed Learning Architecture for personalized insights.
        """
        # Fetch positions from IB
        positions = await self.data_fetcher.get_positions()
        
        # Calculate position metrics from CODE
        total_pnl = 0
        winning = 0
        losing = 0
        largest_winner = None
        largest_loser = None
        largest_win_pnl = 0
        largest_loss_pnl = 0
        
        for pos in positions:
            pnl = float(pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)))
            total_pnl += pnl
            
            if pnl > 0:
                winning += 1
                if pnl > largest_win_pnl:
                    largest_win_pnl = pnl
                    largest_winner = pos
            elif pnl < 0:
                losing += 1
                if pnl < largest_loss_pnl:
                    largest_loss_pnl = pnl
                    largest_loser = pos
        
        # Calculate exposure
        portfolio_exposure = sum(
            abs(float(p.get("position", 0)) * float(p.get("marketPrice", 0)))
            for p in positions
        )
        
        # Fetch performance stats from learning layer
        performance_stats = await self.data_fetcher.get_performance_stats(symbol=symbol)
        
        # Fetch similar past trades if symbol provided
        similar_trades = []
        if symbol:
            similar_trades = await self.data_fetcher.get_trade_history(symbol=symbol, limit=5)
        
        # Get mistake patterns from learning layer
        mistake_patterns = await self._get_mistake_patterns()
        
        # Detect market regime
        market_regime = await self._detect_market_regime()
        
        # ===== NEW: Get personalized learning insights from Three-Speed Architecture =====
        learning_insights = ""
        trader_profile = None
        session_summary = None
        
        # 1. Get full learning context from LearningContextProvider
        if self._learning_context_provider:
            try:
                # Get personalized insights (TQS, edge decay, RAG)
                learning_insights = await self._learning_context_provider.build_full_learning_context(
                    user_query=symbol or "",
                    symbol=symbol,
                    include_tqs=bool(symbol),
                    include_performance=True,
                    include_edge_decay=True,
                    include_confirmations=True,
                    include_rag=bool(symbol)
                )
                logger.debug(f"Got learning insights: {len(learning_insights)} chars")
            except Exception as e:
                logger.warning(f"Could not get learning context: {e}")
        
        # 2. Get trader profile from LearningLoopService
        if self._learning_loop_service:
            try:
                profile = await self._learning_loop_service.get_trader_profile()
                if profile:
                    trader_profile = {
                        "win_rate": getattr(profile, 'overall_win_rate', 0),
                        "avg_r": getattr(profile, 'avg_r_multiple', 0),
                        "best_setups": getattr(profile, 'best_setups', []),
                        "worst_setups": getattr(profile, 'worst_setups', []),
                        "tilt_state": getattr(profile, 'tilt_state', None),
                        "hot_streak": getattr(profile, 'hot_streak', 0),
                        "cold_streak": getattr(profile, 'cold_streak', 0)
                    }
                    logger.debug(f"Got trader profile: win_rate={trader_profile.get('win_rate')}")
            except Exception as e:
                logger.warning(f"Could not get trader profile: {e}")
            
            # Note: session_summary could be populated from learning_loop_service 
            # when get_session_summary() is implemented in a future iteration
        
        return TradingContext(
            positions=positions,
            total_pnl=total_pnl,
            winning_positions=winning,
            losing_positions=losing,
            largest_winner=largest_winner,
            largest_loser=largest_loser,
            portfolio_exposure=portfolio_exposure,
            performance_stats=performance_stats,
            similar_past_trades=similar_trades,
            mistake_patterns=mistake_patterns,
            market_regime=market_regime,
            learning_insights=learning_insights,
            trader_profile=trader_profile,
            session_summary=session_summary
        )
    
    async def _get_mistake_patterns(self) -> List[str]:
        """Get common mistake patterns from learning layer"""
        # This would integrate with the learning service
        # For now, return empty - will connect to actual service
        learning_service = self.get_service("learning_service")
        if learning_service is not None:
            try:
                patterns = await learning_service.get_mistake_patterns()
                return patterns
            except (ValueError, TypeError, AttributeError):
                pass
        return []
    
    async def _detect_market_regime(self) -> str:
        """Detect current market regime"""
        # This would integrate with market analysis
        # For now, return a default
        return "unknown"
    
    async def _get_trading_context(self) -> str:
        """Get current trading context from ContextAwarenessService (Phase 2)"""
        if not self._context_awareness:
            return ""
        
        try:
            context_str = await self._context_awareness.get_context_for_prompt()
            return context_str
        except Exception as e:
            logger.warning(f"Could not get trading context: {e}")
            return ""
    
    async def _build_coaching_prompt_async(self, message: str, context: TradingContext, 
                                           query_type: str, conversation_history: List = None) -> str:
        """Build prompt with verified data for LLM (async version with context awareness)"""
        
        # Get trading context (Phase 2)
        trading_context = await self._get_trading_context()
        
        # Build the rest of the prompt synchronously
        return self._build_coaching_prompt_with_context(
            message, context, query_type, trading_context, conversation_history
        )
    
    def _build_coaching_prompt(self, message: str, context: TradingContext, query_type: str) -> str:
        """Build prompt with verified data for LLM (sync fallback, no context awareness)"""
        return self._build_coaching_prompt_with_context(message, context, query_type, "", [])
    
    def _build_coaching_prompt_with_context(self, message: str, context: TradingContext, 
                                             query_type: str, trading_context: str = "",
                                             conversation_history: List = None) -> str:
        """Build prompt with verified data, optional trading context, and conversation history for LLM"""
        
        # Build conversation context from history
        conversation_text = ""
        if conversation_history:
            conversation_text = "\n=== RECENT CONVERSATION CONTEXT ===\n"
            for msg in conversation_history[-6:]:  # Last 6 messages for context
                role = msg.get("role", "user")
                content = msg.get("content", "")[:300]  # Truncate long messages
                if role == "user":
                    conversation_text += f"Trader: {content}\n"
                else:
                    conversation_text += f"SentCom: {content}\n"
            conversation_text += "\n"
        
        # Build position summary
        positions_text = ""
        if context.positions:
            positions_text = "YOUR CURRENT POSITIONS (VERIFIED FROM IB):\n"
            for pos in context.positions:
                symbol = pos.get("symbol", "?")
                shares = pos.get("position", pos.get("shares", 0)) or 0
                price = pos.get("marketPrice", pos.get("current_price", 0)) or 0
                avg_cost = pos.get("avgCost", pos.get("averageCost", 0)) or 0
                pnl = pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)) or 0
                
                positions_text += f"  - {symbol}: {shares:,.0f} shares @ ${avg_cost:.2f} avg | "
                positions_text += f"Current: ${price:.2f} | P&L: ${pnl:,.2f}\n"
        else:
            positions_text = "YOUR CURRENT POSITIONS: None\n"
        
        # Build performance summary
        perf_text = ""
        if context.performance_stats:
            stats = context.performance_stats
            perf_text = f"""
YOUR PERFORMANCE STATS (VERIFIED):
  - Total Trades: {stats.get('total_trades', 'N/A')}
  - Win Rate: {stats.get('win_rate', 'N/A')}%
  - Average Winner: ${stats.get('avg_winner', 'N/A')}
  - Average Loser: ${stats.get('avg_loser', 'N/A')}
  - Profit Factor: {stats.get('profit_factor', 'N/A')}
"""
        
        # Build similar trades section
        similar_text = ""
        if context.similar_past_trades:
            similar_text = "\nSIMILAR PAST TRADES:\n"
            for trade in context.similar_past_trades[:3]:
                similar_text += f"  - {trade.get('symbol')} on {trade.get('date', '?')}: "
                similar_text += f"P&L ${trade.get('pnl', 0):,.2f}\n"
        
        # Build mistake patterns section
        mistakes_text = ""
        if context.mistake_patterns:
            mistakes_text = "\nYOUR COMMON PATTERNS TO WATCH:\n"
            for pattern in context.mistake_patterns[:3]:
                mistakes_text += f"  - {pattern}\n"
        
        # Portfolio summary
        total_pnl = context.total_pnl if context.total_pnl is not None else 0
        winning = context.winning_positions if context.winning_positions is not None else 0
        losing = context.losing_positions if context.losing_positions is not None else 0
        exposure = context.portfolio_exposure if context.portfolio_exposure is not None else 0
        
        summary = f"""
PORTFOLIO SUMMARY (VERIFIED):
  - Total Unrealized P&L: ${total_pnl:,.2f}
  - Winning Positions: {winning}
  - Losing Positions: {losing}
  - Portfolio Exposure: ${exposure:,.2f}
"""
        
        if context.largest_winner:
            w = context.largest_winner
            summary += f"  - Largest Winner: {w.get('symbol')} (+${w.get('unrealizedPNL', 0):,.2f})\n"
        if context.largest_loser:
            loser = context.largest_loser
            summary += f"  - Largest Loser: {loser.get('symbol')} (${loser.get('unrealizedPNL', 0):,.2f})\n"
        
        # NEW: Add trader profile from Three-Speed Learning
        profile_text = ""
        if context.trader_profile:
            p = context.trader_profile
            profile_text = f"""
YOUR TRADER PROFILE (FROM LEARNING SYSTEM):
  - Overall Win Rate: {p.get('win_rate', 0):.1f}%
  - Average R-Multiple: {p.get('avg_r', 0):.2f}
  - Best Setups: {', '.join(p.get('best_setups', [])[:3]) or 'N/A'}
  - Worst Setups: {', '.join(p.get('worst_setups', [])[:3]) or 'N/A'}
"""
            if p.get('hot_streak'):
                profile_text += f"  - 🔥 Hot Streak: {p['hot_streak']} wins in a row\n"
            if p.get('cold_streak'):
                profile_text += f"  - ❄️ Cold Streak: {p['cold_streak']} losses in a row\n"
            if p.get('tilt_state'):
                profile_text += f"  - ⚠️ Tilt State: {p['tilt_state']}\n"
        
        # NEW: Add session summary
        session_text = ""
        if context.session_summary:
            s = context.session_summary
            session_text = f"""
TODAY'S SESSION:
  - Trades: {s.get('trades', 0)} | PnL: ${s.get('pnl', 0):,.2f}
  - Win Rate: {s.get('win_rate', 0):.0f}%
"""
        
        # NEW: Include learning insights from LearningContextProvider
        learning_text = ""
        if context.learning_insights:
            learning_text = f"\n{context.learning_insights}\n"
        
        # Phase 2: Include trading context (time-of-day, regime, positions awareness)
        context_section = ""
        if trading_context:
            context_section = f"""
{trading_context}

"""
        
        # Combine into full prompt
        prompt = f"""=== VERIFIED DATA (DO NOT MODIFY THESE NUMBERS) ===

{positions_text}
{summary}
{profile_text}
{session_text}
{perf_text}
{similar_text}
{mistakes_text}
{learning_text}
{context_section}
{conversation_text}=== USER QUESTION ===
{message}

=== YOUR TASK ===
Provide personalized coaching based ONLY on the verified data above.
Reference their specific numbers and patterns.
Use insights from the learning system to personalize your advice.
IMPORTANT: Factor in the current trading context (session, regime, positions) when giving advice.
If there's conversation context, maintain conversational continuity and reference previous discussion points.
Be conversational, direct, and insightful. Speak as "we" - we're a team."""
        
        return prompt
    
    async def get_in_trade_guidance(self, symbol: str, entry_price: float, 
                                    current_price: float, position_size: int) -> Dict:
        """
        Get real-time guidance for an active trade.
        All numbers come from parameters (CODE), LLM only advises.
        """
        start = time.time()
        
        # Calculate metrics from CODE
        pnl = (current_price - entry_price) * position_size
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        
        # Fetch context
        performance_stats = await self.data_fetcher.get_performance_stats(symbol=symbol)
        similar_trades = await self.data_fetcher.get_trade_history(symbol=symbol, limit=5)
        
        # Build guidance prompt
        prompt = f"""=== ACTIVE TRADE (VERIFIED DATA) ===

Symbol: {symbol}
Entry Price: ${entry_price:.2f}
Current Price: ${current_price:.2f}
Position Size: {position_size:,} shares
Current P&L: ${pnl:,.2f} ({pnl_pct:+.1f}%)

YOUR HISTORY WITH {symbol}:
{self._format_trade_history(similar_trades)}

YOUR OVERALL STATS:
- Win Rate: {performance_stats.get('win_rate', 'N/A')}%
- Avg Winner Exit: {performance_stats.get('avg_winner_r', 'N/A')}R

=== QUESTION ===
Based on my actual trading data, what should I do with this position right now?
Consider my historical patterns and tendencies.

Keep response under 150 words. Be specific and actionable."""
        
        response = await self._call_llm(
            prompt=prompt,
            temperature=0.7,
            max_tokens=300
        )
        
        return {
            "success": response.success,
            "guidance": response.content if response.success else "Unable to generate guidance",
            "trade_metrics": {
                "symbol": symbol,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "position_size": position_size
            },
            "latency_ms": (time.time() - start) * 1000
        }
    
    def _format_trade_history(self, trades: List[Dict]) -> str:
        """Format trade history for prompt"""
        if not trades:
            return "No previous trades in this symbol."
        
        lines = []
        for t in trades[:5]:
            lines.append(f"  - {t.get('date', '?')}: {t.get('result', '?')} | P&L: ${t.get('pnl', 0):,.2f}")
        
        return "\n".join(lines)
