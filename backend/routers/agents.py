"""
Agents API Router
Exposes the multi-agent system via REST API.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

from agents import (
    get_orchestrator,
    init_orchestrator,
    get_llm_provider
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Global services reference (injected during init)
_services: Dict[str, Any] = {}


class ChatRequest(BaseModel):
    """Request to the agent system"""
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    """Response from the agent system"""
    success: bool
    response: str
    agent_used: str
    intent: str
    latency_ms: float
    requires_confirmation: bool = False
    pending_trade: Optional[Dict] = None
    metadata: Optional[Dict] = None


def init_agents_router(services: Dict[str, Any]):
    """
    Initialize the agents router with services.
    
    Required services:
    - ib_router: IB data access
    - scanner: Market scanner  
    - order_queue: Order execution
    - db: MongoDB
    - performance_analyzer: Performance stats
    - learning_service: Learning layer
    """
    global _services
    _services = services
    
    # Initialize the orchestrator with services
    _ = init_orchestrator(services=services)
    
    logger.info("Agents router initialized with services")


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest):
    """
    Send a message to the agent system.
    
    The orchestrator will:
    1. Route to the appropriate agent (Router Agent)
    2. Process with verified data (specialized agents)
    3. Return personalized response
    
    For trade execution:
    - First response asks for confirmation
    - Reply "yes" to execute
    """
    orchestrator = get_orchestrator()
    
    if not orchestrator:
        raise HTTPException(
            status_code=500,
            detail="Agent system not initialized"
        )
    
    try:
        result = await orchestrator.process(
            message=request.message,
            session_id=request.session_id
        )
        
        return ChatResponse(
            success=result.success,
            response=result.response,
            agent_used=result.agent_used,
            intent=result.intent,
            latency_ms=result.total_latency_ms,
            requires_confirmation=result.requires_confirmation,
            pending_trade=result.pending_trade,
            metadata=result.metadata
        )
        
    except Exception as e:
        logger.error(f"Agent chat error: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.get("/metrics")
def get_agent_metrics():
    """Get performance metrics from all agents"""
    orchestrator = get_orchestrator()
    
    if not orchestrator:
        return {"error": "Agent system not initialized"}
    
    return {
        "success": True,
        "metrics": orchestrator.get_agent_metrics()
    }


@router.delete("/session/{session_id}")
def clear_session(session_id: str):
    """Clear a session's context (useful for testing)"""
    orchestrator = get_orchestrator()
    
    if orchestrator:
        orchestrator.clear_session(session_id)
    
    return {"success": True, "message": f"Session {session_id} cleared"}


@router.get("/status")
def get_agent_status():
    """Get status of the agent system"""
    orchestrator = get_orchestrator()
    llm = get_llm_provider()
    
    return {
        "success": True,
        "orchestrator_ready": orchestrator is not None,
        "llm_provider": llm.primary_provider if llm else None,
        "available_providers": llm.get_available_providers() if llm else [],
        "agents": ["router", "trade_executor", "coach", "analyst"],
        "agents_coming_soon": ["chat"]
    }


@router.post("/switch-provider/{provider}")
def switch_llm_provider(provider: str):
    """Switch the LLM provider (ollama, openai, anthropic)"""
    llm = get_llm_provider()
    
    if not llm:
        raise HTTPException(status_code=500, detail="LLM provider not initialized")
    
    available = llm.get_available_providers()
    if provider not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}. Available: {available}"
        )
    
    try:
        llm.switch_provider(provider)
        return {
            "success": True,
            "message": f"Switched to {provider}",
            "current_provider": llm.primary_provider
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# BriefMe Agent instance
_brief_me_agent = None


def get_brief_me_agent():
    """Get or create the BriefMeAgent instance."""
    global _brief_me_agent
    
    if _brief_me_agent is None:
        from agents.brief_me_agent import BriefMeAgent
        from routers.ib import get_pushed_ib_data
        from services.news_service import get_news_service
        from database import get_database
        
        llm = get_llm_provider()
        _brief_me_agent = BriefMeAgent(llm_provider=llm)
        
        # Inject MongoDB for historical data access (uses unified ib_historical_data)
        db = get_database()
        _brief_me_agent.set_db(db)
        
        # Inject services (now including news_service)
        _brief_me_agent.inject_services(
            context_service=_services.get("context_service"),
            learning_provider=_services.get("learning_provider"),
            trading_bot=_services.get("trading_bot"),
            scanner_service=_services.get("scanner"),
            regime_performance_service=_services.get("regime_performance_service"),
            market_intel_service=_services.get("market_intel_service"),
            alpaca_service=_services.get("alpaca_service"),
            ib_pushed_data=get_pushed_ib_data(),
            news_service=get_news_service()  # NEW: Inject news service for real news/catalysts
        )
        
        logger.info("BriefMeAgent initialized with IB data (primary), Alpaca (fallback), and ib_historical_data")
    
    return _brief_me_agent


class BriefMeRequest(BaseModel):
    """Request for market briefing"""
    detail_level: str = "quick"  # "quick" or "detailed"


class BriefMeResponse(BaseModel):
    """Response with market briefing"""
    success: bool
    detail_level: str
    generated_at: str
    summary: Any  # Can be string (quick) or dict (detailed)
    data: Optional[Dict] = None
    error: Optional[str] = None


@router.post("/brief-me", response_model=BriefMeResponse)
async def generate_market_brief(request: BriefMeRequest):
    """
    Generate a personalized market briefing.
    
    detail_level options:
    - "quick": 2-3 sentence summary
    - "detailed": Full report with sections (Market Overview, Bot Status, Insights, Opportunities, Recommendation)
    
    The briefing is personalized based on:
    - Current market regime
    - Your bot's state and performance
    - Your historical trading patterns
    - Top scanner opportunities
    """
    try:
        agent = get_brief_me_agent()
        
        if not agent:
            raise HTTPException(
                status_code=500,
                detail="BriefMe agent not initialized"
            )
        
        result = await agent.generate_brief(detail_level=request.detail_level)
        
        return BriefMeResponse(
            success=result.get("success", False),
            detail_level=result.get("detail_level", request.detail_level),
            generated_at=result.get("generated_at", ""),
            summary=result.get("summary", ""),
            data=result.get("data"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.error(f"Brief Me generation error: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
