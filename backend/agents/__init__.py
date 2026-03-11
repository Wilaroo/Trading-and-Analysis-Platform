"""
Agents Module
Multi-agent system for trading application.

Architecture:
- Router Agent: Fast intent classification
- Trade Executor Agent: Safe trade execution (LLM parses, CODE executes)
- Coach Agent: Personalized guidance from learning layers
- Analyst Agent: Market analysis (TBD)
- Chat Agent: General conversation (TBD)

All agents use the LLM Provider abstraction for easy provider swapping.
"""

from agents.llm_provider import (
    LLMProvider,
    LLMResponse,
    LLMProviderType,
    get_llm_provider,
    init_llm_provider
)

from agents.base_agent import (
    BaseAgent,
    AgentType,
    AgentResponse,
    DataFetcher
)

from agents.router_agent import (
    RouterAgent,
    Intent,
    RoutingResult
)

from agents.trade_executor_agent import (
    TradeExecutorAgent,
    TradeIntent,
    TradeOrder
)

from agents.coach_agent import (
    CoachAgent,
    TradingContext
)

from agents.orchestrator import (
    AgentOrchestrator,
    OrchestrationResult,
    get_orchestrator,
    init_orchestrator
)

__all__ = [
    # LLM Provider
    "LLMProvider",
    "LLMResponse", 
    "LLMProviderType",
    "get_llm_provider",
    "init_llm_provider",
    
    # Base
    "BaseAgent",
    "AgentType",
    "AgentResponse",
    "DataFetcher",
    
    # Router
    "RouterAgent",
    "Intent",
    "RoutingResult",
    
    # Trade Executor
    "TradeExecutorAgent",
    "TradeIntent",
    "TradeOrder",
    
    # Coach
    "CoachAgent",
    "TradingContext",
    
    # Orchestrator
    "AgentOrchestrator",
    "OrchestrationResult",
    "get_orchestrator",
    "init_orchestrator",
]
