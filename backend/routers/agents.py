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
    orchestrator = init_orchestrator(services=services)
    
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
async def get_agent_metrics():
    """Get performance metrics from all agents"""
    orchestrator = get_orchestrator()
    
    if not orchestrator:
        return {"error": "Agent system not initialized"}
    
    return {
        "success": True,
        "metrics": orchestrator.get_agent_metrics()
    }


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a session's context (useful for testing)"""
    orchestrator = get_orchestrator()
    
    if orchestrator:
        orchestrator.clear_session(session_id)
    
    return {"success": True, "message": f"Session {session_id} cleared"}


@router.get("/status")
async def get_agent_status():
    """Get status of the agent system"""
    orchestrator = get_orchestrator()
    llm = get_llm_provider()
    
    return {
        "success": True,
        "orchestrator_ready": orchestrator is not None,
        "llm_provider": llm.primary_provider if llm else None,
        "available_providers": llm.get_available_providers() if llm else [],
        "agents": ["router", "trade_executor", "coach"],
        "agents_coming_soon": ["analyst", "chat"]
    }


@router.post("/switch-provider/{provider}")
async def switch_llm_provider(provider: str):
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
