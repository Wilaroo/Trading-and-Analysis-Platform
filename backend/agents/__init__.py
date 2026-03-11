"""
Agents Module
Multi-agent system for trading application.

Architecture:
- Router Agent: Fast intent classification
- Trade Executor Agent: Safe trade execution (LLM parses, CODE executes)
- Coach Agent: Personalized guidance from learning layers
- Analyst Agent: Market analysis and stock research
- Chat Agent: General conversation (TBD)

All agents use the LLM Provider abstraction for easy provider swapping.
Learning is powered by the existing Three-Speed Learning Architecture:
- Fast: LearningLoopService (real-time trade tracking)
- Medium: CalibrationService, ContextPerformanceService, EdgeDecayService
- Slow: BacktestEngine, ShadowModeService
- Provider: LearningContextProvider (aggregates all insights for AI)
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

from agents.analyst_agent import (
    AnalystAgent,
    AnalysisContext
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
    
    # Analyst
    "AnalystAgent",
    "AnalysisContext",
    
    # Orchestrator
    "AgentOrchestrator",
    "OrchestrationResult",
    "get_orchestrator",
    "init_orchestrator",
]
