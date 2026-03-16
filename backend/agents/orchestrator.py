"""
Agent Orchestrator
Routes requests to the appropriate agent and manages the multi-agent system.

Phase 1 AI Prompt Intelligence Plan:
- SCANNER: Find trade opportunities via market scanner
- QUICK_QUOTE: Get quick price quotes for symbols
- RISK_CHECK: Analyze current risk exposure

Phase 2 AI Prompt Intelligence Plan:
- Context-aware responses (time-of-day, regime, positions)
- Integrated ContextAwarenessService for smarter AI
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from agents.base_agent import AgentType, AgentResponse, DataFetcher
from agents.llm_provider import LLMProvider, get_llm_provider, init_llm_provider
from agents.router_agent import RouterAgent, Intent
from agents.trade_executor_agent import TradeExecutorAgent
from agents.coach_agent import CoachAgent
from agents.analyst_agent import AnalystAgent

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationResult:
    """Result from the orchestrator"""
    success: bool
    response: str
    agent_used: str
    intent: str
    total_latency_ms: float
    routing_latency_ms: float
    agent_latency_ms: float
    metadata: Dict = None
    requires_confirmation: bool = False
    pending_trade: Dict = None


class AgentOrchestrator:
    """
    Main orchestrator for the multi-agent system.
    
    Routes requests to specialized agents:
    - Router: Classifies intent
    - TradeExecutor: Executes trades safely
    - Coach: Provides personalized guidance
    - Analyst: Market analysis and stock research
    - Scanner: Find trade opportunities (NEW in Phase 1)
    - QuickQuote: Fast price lookups (NEW in Phase 1)
    - RiskCheck: Portfolio risk analysis (NEW in Phase 1)
    """
    
    def __init__(self, llm_provider: LLMProvider = None):
        self.llm = llm_provider or get_llm_provider()
        
        # Initialize agents
        self.router = RouterAgent(self.llm)
        self.trade_executor = TradeExecutorAgent(self.llm)
        self.coach = CoachAgent(self.llm)
        self.analyst = AnalystAgent(self.llm)
        
        # Agent registry
        self._agents = {
            AgentType.ROUTER: self.router,
            AgentType.TRADE_EXECUTOR: self.trade_executor,
            AgentType.COACH: self.coach,
            AgentType.ANALYST: self.analyst,
        }
        
        # Session context for multi-turn conversations
        self._session_contexts: Dict[str, Dict] = {}
        
        # Services (injected)
        self._services: Dict[str, Any] = {}
        
        # Data fetcher for scanner/quote/risk handlers
        self._data_fetcher: Optional[DataFetcher] = None
        
        logger.info("AgentOrchestrator initialized with Phase 1 AI Prompt Intelligence")
    
    def inject_services(self, services: Dict[str, Any]):
        """
        Inject services into the orchestrator and relevant agents.
        
        Services map:
        - ib_router: IB data access
        - scanner: Market scanner
        - order_queue: Order execution queue
        - db: MongoDB database
        - performance_analyzer: Performance stats
        - learning_service: Trading patterns/learning
        - context_awareness: Phase 2 context-aware service
        """
        self._services = services
        
        # Create data fetcher for orchestrator-level handlers (scanner, quote, risk)
        # This is critical - without it, many handlers will fail
        self._data_fetcher = DataFetcher(services)
        logger.info(f"DataFetcher initialized with services: {list(services.keys())}")
        
        # Inject into trade executor (needs positions, order queue)
        self.trade_executor.inject_services({
            "ib_router": services.get("ib_router"),
            "order_queue": services.get("order_queue"),
            "db": services.get("db")
        })
        
        # Inject into coach (needs everything for guidance + learning services + context awareness)
        self.coach.inject_services({
            "ib_router": services.get("ib_router"),
            "scanner": services.get("scanner"),
            "db": services.get("db"),
            "performance_analyzer": services.get("performance_analyzer"),
            "learning_service": services.get("learning_service"),
            # Three-Speed Learning Architecture services
            "learning_context_provider": services.get("learning_context_provider"),
            "learning_loop_service": services.get("learning_loop_service"),
            # Phase 2: Context Awareness
            "context_awareness": services.get("context_awareness")
        })
        
        # Inject into analyst (needs market data services + TQS)
        self.analyst.inject_services({
            "ib_router": services.get("ib_router"),
            "scanner": services.get("scanner"),
            "technical_service": services.get("technical_service"),
            "sector_service": services.get("sector_service"),
            "sentiment_service": services.get("sentiment_service"),
            "db": services.get("db"),
            "tqs_engine": services.get("tqs_engine")  # Trade Quality Score
        })
        
        logger.info(f"Services injected: {list(services.keys())}")
    
    async def process(self, message: str, session_id: str = "default", 
                      chat_history: List[Dict] = None) -> OrchestrationResult:
        """
        Process a user message through the multi-agent system.
        
        Flow:
        1. Router classifies intent
        2. Route to appropriate agent with conversation context
        3. Agent processes with verified data
        4. Return response
        
        Args:
            message: User's message
            session_id: Session ID for context persistence
            chat_history: Recent chat history for conversational context
        """
        start = time.time()
        
        # Get session context
        context = self._get_session_context(session_id)
        
        # Update conversation history from chat_history if provided
        if chat_history:
            context["conversation_history"] = chat_history[-10:]  # Keep last 10 messages
        
        # Step 1: Route the request
        routing_start = time.time()
        routing_result = await self.router.process({
            "message": message,
            "context": context,
            "conversation_history": context.get("conversation_history", [])
        })
        routing_latency = (time.time() - routing_start) * 1000
        
        if not routing_result.success:
            return OrchestrationResult(
                success=False,
                response="I couldn't understand that request. Please try again.",
                agent_used="router",
                intent="unknown",
                total_latency_ms=(time.time() - start) * 1000,
                routing_latency_ms=routing_latency,
                agent_latency_ms=0,
                metadata={"error": routing_result.error}
            )
        
        # Extract routing info
        intent_str = routing_result.content.get("intent", "general_chat")
        symbols = routing_result.content.get("symbols", [])
        action = routing_result.content.get("action")
        
        try:
            intent = Intent(intent_str)
        except ValueError:
            intent = Intent.GENERAL_CHAT
        
        logger.info(f"Routed to {intent.value} (symbols={symbols}, action={action})")
        
        # Step 2: Route to appropriate agent
        agent_start = time.time()
        
        if intent == Intent.TRADE_EXECUTE:
            # Check if this is a confirmation
            is_confirmation = context.get("awaiting_confirmation", False)
            
            agent_response = await self.trade_executor.process({
                "message": message,
                "symbols": symbols,
                "action": action,
                "confirmed": is_confirmation,
                "context": context
            })
            
            # Update context based on response
            if agent_response.content.get("requires_confirmation"):
                context["awaiting_confirmation"] = True
                context["pending_trade"] = agent_response.content.get("pending_trade")
                context["previous_intent"] = "trade_execute"
            else:
                # Clear confirmation state
                context["awaiting_confirmation"] = False
                context["pending_trade"] = None
            
        elif intent in [Intent.POSITION_QUERY, Intent.COACHING, Intent.TRADE_QUERY]:
            agent_response = await self.coach.process({
                "message": message,
                "query_type": self._map_intent_to_query_type(intent),
                "symbol": symbols[0] if symbols else None,
                "conversation_history": context.get("conversation_history", [])
            })
            
            # Clear any pending trade confirmation
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        elif intent == Intent.ANALYSIS:
            # Route to analyst agent for market analysis
            agent_response = await self.analyst.process({
                "message": message,
                "symbol": symbols[0] if symbols else None,
                "symbols": symbols,
                "analysis_type": "full",
                "conversation_history": context.get("conversation_history", [])
            })
            
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        elif intent == Intent.MARKET_INFO:
            # General market overview - use coach agent
            agent_response = await self.coach.process({
                "message": message,
                "query_type": "market_context",
                "symbol": symbols[0] if symbols else None,
                "conversation_history": context.get("conversation_history", [])
            })
            
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        elif intent == Intent.SCANNER:
            # NEW Phase 1: Handle scanner/find trades requests
            agent_response = await self._handle_scanner_request(message, symbols)
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        elif intent == Intent.QUICK_QUOTE:
            # NEW Phase 1: Handle quick quote requests
            agent_response = await self._handle_quick_quote(message, symbols)
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        elif intent == Intent.RISK_CHECK:
            # NEW Phase 1: Handle risk check requests
            agent_response = await self._handle_risk_check(message)
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
            
        else:
            # Default to coach for general conversation
            agent_response = await self.coach.process({
                "message": message,
                "query_type": "general",
                "symbol": symbols[0] if symbols else None,
                "conversation_history": context.get("conversation_history", [])
            })
            
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        agent_latency = (time.time() - agent_start) * 1000
        
        # Save updated context
        self._save_session_context(session_id, context)
        
        # Build response
        response_text = agent_response.content.get("message", str(agent_response.content))
        
        return OrchestrationResult(
            success=agent_response.success,
            response=response_text,
            agent_used=agent_response.agent_type,
            intent=intent.value,
            total_latency_ms=(time.time() - start) * 1000,
            routing_latency_ms=routing_latency,
            agent_latency_ms=agent_latency,
            metadata={
                "symbols": symbols,
                "action": action,
                "routing_method": routing_result.content.get("method"),
                "model_used": agent_response.model_used
            },
            requires_confirmation=agent_response.content.get("requires_confirmation", False),
            pending_trade=agent_response.content.get("pending_trade")
        )
    
    # ========== Phase 1 AI Prompt Intelligence Handlers ==========
    
    async def _handle_scanner_request(self, message: str, symbols: List[str]) -> AgentResponse:
        """
        Handle SCANNER intent: Find trade opportunities
        
        Examples: "find me a trade", "what setups are forming", "any opportunities"
        """
        start = time.time()
        
        # Safety check for data fetcher
        if not self._data_fetcher:
            return AgentResponse(
                success=True,
                content={"message": "## Scanner Results\n\n**We're still initializing our scanner.** We'll have trade opportunities ready once we're fully connected."},
                agent_type="scanner_handler",
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only"
            )
        
        try:
            # Get scanner alerts from the enhanced scanner
            alerts = await self._data_fetcher.get_scanner_alerts(limit=10)
            
            if not alerts:
                response_text = """## Scanner Results

**No active setups at the moment.**

The scanner continuously monitors the market for:
- Momentum breakouts
- VWAP bounces
- ORB (Opening Range Breakout) patterns
- Mean reversion setups
- Gap and Go plays

Check back soon or run a market-wide scan for more opportunities."""
                
                return AgentResponse(
                    success=True,
                    content={"message": response_text},
                    agent_type="scanner_handler",
                    latency_ms=(time.time() - start) * 1000,
                    model_used="code_only"
                )
            
            # Format alerts for display
            response_lines = ["## Scanner Results\n"]
            response_lines.append(f"Found **{len(alerts)} active setups**:\n")
            
            # Group alerts by priority
            high_priority = [a for a in alerts if a.get("priority") in ["critical", "high"]]
            medium_priority = [a for a in alerts if a.get("priority") == "medium"]
            
            if high_priority:
                response_lines.append("### 🔥 High Priority Setups\n")
                for alert in high_priority[:5]:
                    direction = "📈" if alert.get("direction") == "long" else "📉"
                    rr = self._calc_risk_reward(alert)
                    response_lines.append(
                        f"- **{alert['symbol']}** {direction} | {alert.get('setup_type', 'unknown').replace('_', ' ').title()}\n"
                        f"  - Entry: ${alert.get('current_price', 0):.2f} | Stop: ${alert.get('stop_loss', 0):.2f} | Target: ${alert.get('target', 0):.2f}\n"
                        f"  - R:R = {rr:.1f}:1 | Probability: {alert.get('trigger_probability', 0):.0%}\n"
                    )
            
            if medium_priority:
                response_lines.append("\n### 📊 Other Active Setups\n")
                for alert in medium_priority[:5]:
                    direction = "📈" if alert.get("direction") == "long" else "📉"
                    response_lines.append(
                        f"- **{alert['symbol']}** {direction} | {alert.get('setup_type', 'unknown').replace('_', ' ').title()} @ ${alert.get('current_price', 0):.2f}\n"
                    )
            
            response_lines.append("\n*Say \"analyze [SYMBOL]\" for detailed analysis on any setup.*")
            
            return AgentResponse(
                success=True,
                content={"message": "\n".join(response_lines), "alerts": alerts},
                agent_type="scanner_handler",
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only"
            )
            
        except Exception as e:
            logger.error(f"Scanner handler error: {e}")
            return AgentResponse(
                success=False,
                content={"message": f"Unable to fetch scanner results: {str(e)}"},
                agent_type="scanner_handler",
                latency_ms=(time.time() - start) * 1000,
                error=str(e)
            )
    
    async def _handle_quick_quote(self, message: str, symbols: List[str]) -> AgentResponse:
        """
        Handle QUICK_QUOTE intent: Get fast price quotes
        
        Examples: "price of NVDA", "where's AAPL", "TSLA quote"
        """
        start = time.time()
        
        if not symbols:
            return AgentResponse(
                success=False,
                content={"message": "Please specify a stock symbol. Example: 'price of NVDA'"},
                agent_type="quote_handler",
                latency_ms=(time.time() - start) * 1000,
                error="No symbol provided"
            )
        
        # Safety check for data fetcher
        if not self._data_fetcher:
            return AgentResponse(
                success=True,
                content={"message": f"## {symbols[0]} Quote\n\n**We're still connecting to our data feeds.** We'll have real-time quotes ready shortly."},
                agent_type="quote_handler",
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only"
            )
        
        try:
            quotes_data = []
            for symbol in symbols[:5]:  # Limit to 5 symbols
                quote = await self._data_fetcher.get_quote(symbol)
                if quote:
                    # Get price - prefer last, then close, then midpoint of bid/ask
                    price = quote.get("last", 0) or quote.get("close", 0)
                    bid = quote.get("bid", 0) or 0
                    ask = quote.get("ask", 0) or 0
                    
                    # If no last/close price, use midpoint of bid/ask
                    if price == 0 and bid > 0 and ask > 0:
                        price = (bid + ask) / 2
                    
                    quotes_data.append({
                        "symbol": symbol,
                        "price": price,
                        "bid": bid,
                        "ask": ask,
                        "change": quote.get("change", 0) or 0,
                        "change_pct": quote.get("changePercent", quote.get("change_pct", 0)) or 0,
                        "volume": quote.get("volume", 0) or 0
                    })
            
            if not quotes_data:
                return AgentResponse(
                    success=False,
                    content={"message": f"Could not fetch quote for {', '.join(symbols)}. Market may be closed or symbol invalid."},
                    agent_type="quote_handler",
                    latency_ms=(time.time() - start) * 1000,
                    error="No quote data"
                )
            
            # Format response
            if len(quotes_data) == 1:
                q = quotes_data[0]
                emoji = "🟢" if q["change_pct"] >= 0 else "🔴"
                response_text = f"""## {q['symbol']} Quote

**Price**: ${q['price']:.2f} {emoji} {q['change_pct']:+.2f}%
**Bid/Ask**: ${q['bid']:.2f} / ${q['ask']:.2f}
**Volume**: {q['volume']:,.0f}

*Data from IB Gateway (real-time)*"""
            else:
                response_lines = ["## Quick Quotes\n"]
                for q in quotes_data:
                    emoji = "🟢" if q["change_pct"] >= 0 else "🔴"
                    response_lines.append(f"**{q['symbol']}**: ${q['price']:.2f} {emoji} {q['change_pct']:+.2f}%")
                response_text = "\n".join(response_lines)
            
            return AgentResponse(
                success=True,
                content={"message": response_text, "quotes": quotes_data},
                agent_type="quote_handler",
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only"
            )
            
        except Exception as e:
            logger.error(f"Quote handler error: {e}")
            return AgentResponse(
                success=False,
                content={"message": f"Error fetching quote: {str(e)}"},
                agent_type="quote_handler",
                latency_ms=(time.time() - start) * 1000,
                error=str(e)
            )
    
    async def _handle_risk_check(self, message: str) -> AgentResponse:
        """
        Handle RISK_CHECK intent: Analyze current portfolio risk
        
        Examples: "what's my risk exposure", "how much am I risking", "portfolio risk"
        """
        start = time.time()
        
        # Safety check for data fetcher
        if not self._data_fetcher:
            return AgentResponse(
                success=True,
                content={"message": "## Risk Check\n\n**We're still initializing.** We'll be able to check your risk exposure once we're fully connected."},
                agent_type="risk_handler",
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only"
            )
        
        try:
            # Get positions
            positions = await self._data_fetcher.get_positions()
            
            if not positions:
                return AgentResponse(
                    success=True,
                    content={"message": "## Risk Check\n\n**No open positions.** Your risk exposure is currently $0."},
                    agent_type="risk_handler",
                    latency_ms=(time.time() - start) * 1000,
                    model_used="code_only"
                )
            
            # Calculate risk metrics
            total_exposure = 0
            total_unrealized_pnl = 0
            long_exposure = 0
            short_exposure = 0
            position_risks = []
            
            for pos in positions:
                shares = float(pos.get("position", pos.get("shares", 0)) or 0)
                price = float(pos.get("marketPrice", pos.get("current_price", 0)) or 0)
                avg_cost = float(pos.get("avgCost", pos.get("averageCost", 0)) or 0)
                pnl = float(pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)) or 0)
                
                position_value = abs(shares * price)
                total_exposure += position_value
                total_unrealized_pnl += pnl
                
                if shares > 0:
                    long_exposure += position_value
                else:
                    short_exposure += position_value
                
                # Calculate position-level risk (% from cost basis)
                pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
                
                position_risks.append({
                    "symbol": pos.get("symbol", "?"),
                    "shares": shares,
                    "value": position_value,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "is_long": shares > 0
                })
            
            # Sort by absolute value (largest positions first)
            position_risks.sort(key=lambda x: abs(x["value"]), reverse=True)
            
            # Get account data for context
            account_data = await self._data_fetcher.get_account_data()
            net_liq = account_data.get("NetLiquidation", account_data.get("net_liquidation", 0))
            # Note: buying_power available if needed in future iterations
            
            # Calculate concentration risk
            if total_exposure > 0:
                largest_position_pct = (position_risks[0]["value"] / total_exposure * 100) if position_risks else 0
            else:
                largest_position_pct = 0
            
            # Format response
            response_lines = ["## Risk Analysis\n"]
            
            # Overall metrics
            response_lines.append("### Portfolio Summary")
            response_lines.append(f"- **Total Exposure**: ${total_exposure:,.2f}")
            response_lines.append(f"- **Long Exposure**: ${long_exposure:,.2f}")
            response_lines.append(f"- **Short Exposure**: ${short_exposure:,.2f}")
            response_lines.append(f"- **Net Exposure**: ${long_exposure - short_exposure:,.2f}")
            response_lines.append(f"- **Unrealized P&L**: ${total_unrealized_pnl:,.2f}")
            if net_liq > 0:
                exposure_pct = (total_exposure / net_liq) * 100
                response_lines.append(f"- **Exposure % of Account**: {exposure_pct:.1f}%")
            response_lines.append("")
            
            # Risk warnings
            warnings = []
            if largest_position_pct > 30:
                warnings.append(f"⚠️ **Concentration Risk**: Largest position is {largest_position_pct:.1f}% of exposure")
            if net_liq > 0 and total_exposure > net_liq:
                warnings.append("⚠️ **Leverage Warning**: Exposure exceeds account value")
            
            losers = [p for p in position_risks if p["pnl"] < 0]
            big_losers = [p for p in losers if p["pnl_pct"] < -5]
            if big_losers:
                symbols = ", ".join([p["symbol"] for p in big_losers[:3]])
                warnings.append(f"⚠️ **Drawdown Alert**: {symbols} down more than 5%")
            
            if warnings:
                response_lines.append("### Risk Warnings")
                for w in warnings:
                    response_lines.append(w)
                response_lines.append("")
            
            # Position breakdown
            response_lines.append("### Position Breakdown")
            for p in position_risks[:5]:
                emoji = "🟢" if p["pnl"] >= 0 else "🔴"
                direction = "Long" if p["is_long"] else "Short"
                response_lines.append(
                    f"- **{p['symbol']}** ({direction}): ${p['value']:,.0f} | P&L: ${p['pnl']:,.2f} ({p['pnl_pct']:+.1f}%) {emoji}"
                )
            
            if len(position_risks) > 5:
                response_lines.append(f"  _...and {len(position_risks) - 5} more positions_")
            
            return AgentResponse(
                success=True,
                content={
                    "message": "\n".join(response_lines),
                    "risk_metrics": {
                        "total_exposure": total_exposure,
                        "long_exposure": long_exposure,
                        "short_exposure": short_exposure,
                        "unrealized_pnl": total_unrealized_pnl,
                        "position_count": len(positions),
                        "largest_position_pct": largest_position_pct,
                        "warnings": warnings
                    }
                },
                agent_type="risk_handler",
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only"
            )
            
        except Exception as e:
            logger.error(f"Risk handler error: {e}")
            return AgentResponse(
                success=False,
                content={"message": f"Error analyzing risk: {str(e)}"},
                agent_type="risk_handler",
                latency_ms=(time.time() - start) * 1000,
                error=str(e)
            )
    
    def _calc_risk_reward(self, alert: Dict) -> float:
        """Calculate risk:reward ratio for an alert"""
        try:
            entry = alert.get("current_price", 0)
            stop = alert.get("stop_loss", 0)
            target = alert.get("target", 0)
            
            if entry and stop and target:
                risk = abs(entry - stop)
                reward = abs(target - entry)
                if risk > 0:
                    return reward / risk
        except Exception:
            pass
        return 0.0
    
    # ========== End Phase 1 Handlers ==========
    
    def _get_session_context(self, session_id: str) -> Dict:
        """Get or create session context"""
        if session_id not in self._session_contexts:
            self._session_contexts[session_id] = {
                "awaiting_confirmation": False,
                "pending_trade": None,
                "previous_intent": None,
                "conversation_history": []
            }
        return self._session_contexts[session_id]
    
    def _save_session_context(self, session_id: str, context: Dict):
        """Save session context"""
        self._session_contexts[session_id] = context
    
    def _map_intent_to_query_type(self, intent: Intent) -> str:
        """Map intent to coach query type"""
        mapping = {
            Intent.POSITION_QUERY: "position",
            Intent.COACHING: "performance",
            Intent.TRADE_QUERY: "trade_decision",
        }
        return mapping.get(intent, "general")
    
    def get_agent_metrics(self) -> Dict[str, Any]:
        """Get metrics from all agents"""
        return {
            "router": self.router.get_metrics(),
            "trade_executor": self.trade_executor.get_metrics(),
            "coach": self.coach.get_metrics(),
            "analyst": self.analyst.get_metrics(),
        }
    
    def clear_session(self, session_id: str):
        """Clear a session's context"""
        if session_id in self._session_contexts:
            del self._session_contexts[session_id]


# Singleton instance
_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Get the global orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


def init_orchestrator(services: Dict[str, Any] = None, 
                     llm_provider: LLMProvider = None) -> AgentOrchestrator:
    """Initialize the global orchestrator with services"""
    global _orchestrator
    _orchestrator = AgentOrchestrator(llm_provider=llm_provider)
    if services:
        _orchestrator.inject_services(services)
    return _orchestrator
