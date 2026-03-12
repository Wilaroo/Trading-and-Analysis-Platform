"""
Agent Orchestrator
Routes requests to the appropriate agent and manages the multi-agent system.
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from agents.base_agent import AgentType, AgentResponse
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
    - Chat: General conversation (to be added)
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
        
        logger.info("AgentOrchestrator initialized with Analyst agent")
    
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
        """
        self._services = services
        
        # Inject into trade executor (needs positions, order queue)
        self.trade_executor.inject_services({
            "ib_router": services.get("ib_router"),
            "order_queue": services.get("order_queue"),
            "db": services.get("db")
        })
        
        # Inject into coach (needs everything for guidance + learning services)
        self.coach.inject_services({
            "ib_router": services.get("ib_router"),
            "scanner": services.get("scanner"),
            "db": services.get("db"),
            "performance_analyzer": services.get("performance_analyzer"),
            "learning_service": services.get("learning_service"),
            # NEW: Three-Speed Learning Architecture services
            "learning_context_provider": services.get("learning_context_provider"),
            "learning_loop_service": services.get("learning_loop_service")
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
    
    async def process(self, message: str, session_id: str = "default") -> OrchestrationResult:
        """
        Process a user message through the multi-agent system.
        
        Flow:
        1. Router classifies intent
        2. Route to appropriate agent
        3. Agent processes with verified data
        4. Return response
        """
        start = time.time()
        
        # Get session context
        context = self._get_session_context(session_id)
        
        # Step 1: Route the request
        routing_start = time.time()
        routing_result = await self.router.process({
            "message": message,
            "context": context
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
                "symbol": symbols[0] if symbols else None
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
                "analysis_type": "full"
            })
            
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
        
        elif intent == Intent.MARKET_INFO:
            # General market overview - use coach agent
            agent_response = await self.coach.process({
                "message": message,
                "query_type": "market_context",
                "symbol": symbols[0] if symbols else None
            })
            
            context["awaiting_confirmation"] = False
            context["pending_trade"] = None
            
        else:
            # Default to coach for general conversation
            agent_response = await self.coach.process({
                "message": message,
                "query_type": "general",
                "symbol": symbols[0] if symbols else None
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
