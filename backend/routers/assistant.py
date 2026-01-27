"""
AI Assistant API Router
Endpoints for the intelligent trading assistant.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid

router = APIRouter(prefix="/api/assistant", tags=["AI Assistant"])

# Service instance
_assistant_service = None


def init_assistant_router(assistant_service):
    """Initialize the router with the assistant service"""
    global _assistant_service
    _assistant_service = assistant_service


# ===================== Pydantic Models =====================

class ChatRequest(BaseModel):
    message: str = Field(..., description="User message")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation continuity")


class AnalyzeTradeRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    action: str = Field(..., description="BUY or SELL")
    session_id: Optional[str] = Field(default=None)


class ProviderRequest(BaseModel):
    provider: str = Field(..., description="LLM provider: emergent, openai, perplexity")


# ===================== Endpoints =====================

@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Chat with the AI assistant.
    
    The assistant has access to:
    - Your learned trading strategies and rules
    - Quality scores and market data
    - Your trading history
    
    It will provide analytical responses and enforce your trading rules.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Generate session ID if not provided
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    
    result = await _assistant_service.chat(request.message, session_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Chat failed"))
    
    return result


@router.post("/analyze-trade")
async def analyze_trade(request: AnalyzeTradeRequest):
    """
    Get AI analysis of a potential trade.
    
    The assistant will:
    - Check against your learned strategies
    - Verify trading rules aren't violated
    - Assess quality score
    - Provide risk/reward assessment
    - Give a recommendation
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    session_id = request.session_id or f"trade_{uuid.uuid4().hex[:8]}"
    
    result = await _assistant_service.analyze_trade(
        request.symbol.upper(),
        request.action.upper(),
        session_id
    )
    
    return result


@router.get("/premarket-briefing")
async def get_premarket_briefing(session_id: Optional[str] = None):
    """
    Get AI-generated pre-market briefing.
    
    Includes:
    - Market sentiment
    - Key levels to watch
    - Relevant strategies for today
    - Trading rules reminder
    - Setup ideas
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    session_id = session_id or f"briefing_{datetime.now().strftime('%Y%m%d')}"
    
    result = await _assistant_service.get_premarket_briefing(session_id)
    
    return result


@router.get("/review-patterns")
async def review_trading_patterns(session_id: Optional[str] = None):
    """
    Get AI analysis of your trading patterns.
    
    The assistant will analyze your behavior and suggest improvements.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    session_id = session_id or f"review_{uuid.uuid4().hex[:8]}"
    
    result = await _assistant_service.review_trading_patterns(session_id)
    
    return result


@router.get("/suggestions")
async def get_suggestions():
    """
    Get suggested requests based on your usage patterns.
    
    Returns frequently used request types to help you get started.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    suggestions = _assistant_service.get_suggested_requests()
    
    return {
        "suggestions": suggestions
    }


@router.get("/history/{session_id}")
async def get_conversation_history(session_id: str):
    """Get conversation history for a session"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    history = _assistant_service.get_conversation_history(session_id)
    
    return {
        "session_id": session_id,
        "messages": history,
        "count": len(history)
    }


@router.delete("/history/{session_id}")
async def clear_conversation(session_id: str):
    """Clear conversation history for a session"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    _assistant_service.clear_conversation(session_id)
    
    return {"success": True, "message": f"Conversation {session_id} cleared"}


@router.get("/sessions")
async def get_sessions(user_id: str = "default"):
    """Get all conversation sessions for a user"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    sessions = _assistant_service.get_all_sessions(user_id)
    
    return {
        "sessions": sessions,
        "count": len(sessions)
    }


@router.get("/providers")
async def get_available_providers():
    """Get available LLM providers"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    providers = _assistant_service.get_available_providers()
    current = _assistant_service.provider.value
    
    return {
        "current": current,
        "available": providers
    }


@router.post("/providers")
async def set_provider(request: ProviderRequest):
    """Switch LLM provider"""
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    success = _assistant_service.set_provider(request.provider)
    
    if not success:
        raise HTTPException(status_code=400, detail=f"Invalid or unavailable provider: {request.provider}")
    
    return {
        "success": True,
        "provider": request.provider
    }


@router.get("/status")
async def get_assistant_status():
    """Get assistant service status"""
    if not _assistant_service:
        return {
            "status": "not_initialized",
            "ready": False
        }
    
    providers = _assistant_service.get_available_providers()
    
    return {
        "status": "ready" if providers else "no_providers",
        "ready": len(providers) > 0,
        "current_provider": _assistant_service.provider.value,
        "available_providers": providers,
        "features": {
            "chat": True,
            "trade_analysis": True,
            "premarket_briefing": True,
            "pattern_review": True,
            "conversation_memory": True
        }
    }
