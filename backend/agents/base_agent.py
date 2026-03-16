"""
Base Agent Class
All agents inherit from this base class which provides:
- LLM access via provider abstraction
- Service injection
- Logging and metrics
- Common utilities
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from agents.llm_provider import LLMProvider, LLMResponse, get_llm_provider

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Types of agents in the system"""
    ROUTER = "router"
    TRADE_EXECUTOR = "trade_executor"
    COACH = "coach"
    ANALYST = "analyst"
    CHAT = "chat"


@dataclass
class AgentResponse:
    """Standardized response from any agent"""
    success: bool
    content: Any  # Can be string, dict, or structured data
    agent_type: str
    latency_ms: float
    model_used: Optional[str] = None
    metadata: Optional[Dict] = None
    error: Optional[str] = None


class BaseAgent(ABC):
    """
    Base class for all agents.
    Provides common functionality and enforces consistent interface.
    """
    
    def __init__(self, 
                 agent_type: AgentType,
                 llm_provider: LLMProvider = None,
                 model: str = None):
        """
        Initialize base agent.
        
        Args:
            agent_type: Type of this agent
            llm_provider: LLM provider instance (uses global if not provided)
            model: Default model for this agent
        """
        self.agent_type = agent_type
        self.llm = llm_provider or get_llm_provider()
        self.default_model = model
        
        # Metrics tracking
        self._call_count = 0
        self._total_latency_ms = 0
        self._error_count = 0
        
        # Services (injected by orchestrator)
        self._services: Dict[str, Any] = {}
        
        logger.info(f"Agent initialized: {agent_type.value}")
    
    def inject_services(self, services: Dict[str, Any]):
        """
        Inject services this agent needs.
        Called by the orchestrator during setup.
        """
        self._services = services
        logger.debug(f"Services injected into {self.agent_type.value}: {list(services.keys())}")
    
    def get_service(self, name: str) -> Any:
        """Get an injected service by name"""
        service = self._services.get(name)
        if not service:
            logger.warning(f"Service '{name}' not found in {self.agent_type.value}")
        return service
    
    @abstractmethod
    async def process(self, input_data: Dict[str, Any]) -> AgentResponse:
        """
        Process input and return response.
        Each agent implements this differently.
        """
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent"""
        pass
    
    async def _call_llm(self, prompt: str, 
                       system_prompt: str = None,
                       model: str = None,
                       temperature: float = 0.7,
                       max_tokens: int = 1000) -> LLMResponse:
        """
        Helper to call LLM with consistent error handling.
        """
        model = model or self.default_model
        system_prompt = system_prompt or self.get_system_prompt()
        
        start = time.time()
        
        try:
            response = await self.llm.generate(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # Track metrics
            self._call_count += 1
            self._total_latency_ms += response.latency_ms or 0
            if not response.success:
                self._error_count += 1
            
            return response
            
        except Exception as e:
            self._error_count += 1
            logger.error(f"LLM call failed in {self.agent_type.value}: {e}")
            return LLMResponse(
                content="",
                model=model or "unknown",
                provider="unknown",
                success=False,
                error=str(e),
                latency_ms=(time.time() - start) * 1000
            )
    
    def _create_response(self, 
                        success: bool,
                        content: Any,
                        latency_ms: float,
                        model_used: str = None,
                        metadata: Dict = None,
                        error: str = None) -> AgentResponse:
        """Helper to create consistent agent responses"""
        return AgentResponse(
            success=success,
            content=content,
            agent_type=self.agent_type.value,
            latency_ms=latency_ms,
            model_used=model_used,
            metadata=metadata,
            error=error
        )
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get agent performance metrics"""
        avg_latency = self._total_latency_ms / self._call_count if self._call_count > 0 else 0
        return {
            "agent_type": self.agent_type.value,
            "call_count": self._call_count,
            "error_count": self._error_count,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate": round(self._error_count / self._call_count * 100, 2) if self._call_count > 0 else 0
        }


class DataFetcher:
    """
    Utility class for fetching data from services.
    Ensures all data comes from CODE, not LLM.
    """
    
    def __init__(self, services: Dict[str, Any]):
        self.services = services
    
    async def get_positions(self) -> List[Dict]:
        """Get positions from unified source (Trading Bot + IB)"""
        positions = []
        
        # First try sentcom service for unified positions
        try:
            from services.sentcom_service import get_sentcom_service
            sentcom = get_sentcom_service()
            if sentcom:
                raw_positions = await sentcom.get_our_positions()
                if raw_positions:
                    # Normalize keys to match expected format
                    for pos in raw_positions:
                        normalized = {
                            "symbol": pos.get("symbol"),
                            "position": pos.get("shares", pos.get("position", 0)),
                            "marketPrice": pos.get("current_price", pos.get("marketPrice", 0)),
                            "avgCost": pos.get("entry_price", pos.get("avgCost", 0)),
                            "unrealizedPNL": pos.get("pnl", pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0))),
                            "unrealized_pnl": pos.get("pnl", pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0))),
                            "direction": pos.get("direction", "long"),
                            "status": pos.get("status", "open"),
                            "trade_id": pos.get("trade_id"),
                            "source": pos.get("source", "unified"),
                        }
                        positions.append(normalized)
                    return positions
        except Exception as e:
            logger.warning(f"Sentcom positions error: {e}")
        
        # Fallback to IB pushed positions
        ib_router = self.services.get("ib_router")
        if ib_router:
            try:
                import routers.ib as ib_module
                return ib_module.get_pushed_positions()
            except Exception as e:
                logger.error(f"Error fetching IB positions: {e}")
        
        # Final fallback: try trading bot directly
        try:
            from services.trading_bot_service import get_trading_bot_service
            bot = get_trading_bot_service()
            if bot:
                return bot.get_open_trades() or []
        except Exception as e:
            logger.warning(f"Trading bot positions error: {e}")
        
        return []
    
    async def get_account_data(self) -> Dict:
        """Get account data from IB (CODE - verified data)"""
        try:
            import routers.ib as ib_module
            # Use the account summary endpoint
            account = await ib_module.get_account_summary()
            return account
        except Exception as e:
            logger.error(f"Error fetching account data: {e}")
            return {}
    
    async def get_scanner_alerts(self, limit: int = 10) -> List[Dict]:
        """Get scanner alerts (CODE - verified data)"""
        scanner = self.services.get("scanner")
        if scanner:
            try:
                alerts = scanner.get_live_alerts()
                return [
                    {
                        "symbol": a.symbol,
                        "setup_type": a.setup_type,
                        "direction": a.direction,
                        "current_price": a.current_price,
                        "stop_loss": a.stop_loss,
                        "target": a.target,
                        "trigger_probability": a.trigger_probability,
                        "priority": a.priority.value if a.priority else "medium"
                    }
                    for a in alerts[:limit]
                ]
            except Exception as e:
                logger.error(f"Error fetching scanner alerts: {e}")
        return []
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get quote for a symbol (CODE - verified data)"""
        try:
            import routers.ib as ib_module
            # First try pushed quotes (real-time from IB)
            quotes = ib_module.get_pushed_quotes()
            if symbol in quotes:
                return quotes.get(symbol)
            
            # Fall back to API call for quote
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://localhost:8001/api/ib/quote/{symbol}", timeout=5.0)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
        return None
    
    async def get_trade_history(self, symbol: str = None, limit: int = 20) -> List[Dict]:
        """Get trade history from database (CODE - verified data)"""
        db = self.services.get("db")
        if db is not None:
            try:
                query = {"symbol": symbol} if symbol else {}
                trades = list(db.trades.find(query, {"_id": 0}).sort("date", -1).limit(limit))
                return trades
            except Exception as e:
                logger.error(f"Error fetching trade history: {e}")
        return []
    
    async def get_performance_stats(self, symbol: str = None, setup_type: str = None) -> Dict:
        """Get performance stats from learning layer (CODE - verified data)"""
        perf_service = self.services.get("performance_analyzer")
        if perf_service is not None:
            try:
                # Use get_strategy_stats method
                stats = perf_service.get_strategy_stats()
                return {
                    "total_trades": stats.get("total_trades", 0),
                    "win_rate": stats.get("overall_win_rate", 0),
                    "avg_winner": stats.get("avg_win", 0),
                    "avg_loser": stats.get("avg_loss", 0),
                    "profit_factor": stats.get("profit_factor", 0)
                }
            except Exception as e:
                logger.error(f"Error fetching performance stats: {e}")
        
        # Return default stats if service not available
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_winner": 0,
            "avg_loser": 0,
            "profit_factor": 0
        }
