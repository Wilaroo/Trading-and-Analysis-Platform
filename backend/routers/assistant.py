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
            "conversation_memory": True,
            # New coaching features
            "rule_check": True,
            "position_sizing": True,
            "coaching_alerts": True,
            "trade_review": True,
            "daily_summary": True,
            "setup_analysis": True
        }
    }


# ===================== COACHING ENDPOINTS =====================

class RuleCheckRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    action: str = Field(..., description="BUY or SELL")
    entry_price: Optional[float] = Field(default=None, description="Planned entry price")
    position_size: Optional[float] = Field(default=None, description="Number of shares")
    stop_loss: Optional[float] = Field(default=None, description="Stop loss price")


class PositionSizingRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    entry_price: float = Field(..., description="Entry price")
    stop_loss: float = Field(..., description="Stop loss price")
    account_size: Optional[float] = Field(default=None, description="Account size for % calculation")


class CoachingAlertRequest(BaseModel):
    alert_type: str = Field(..., description="Type: market_open, regime_change, losing_streak, overtrading, position_risk, rule_reminder")
    data: Optional[dict] = Field(default=None, description="Context data for the alert")


class TradeReviewRequest(BaseModel):
    symbol: str
    action: str
    entry_price: float
    exit_price: float
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    shares: Optional[int] = None
    pnl: Optional[float] = None
    notes: Optional[str] = None


class SetupAnalysisRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    setup_type: Optional[str] = Field(default=None, description="Type: gap_up, breakout, pullback, reversal, etc.")
    chart_notes: Optional[str] = Field(default=None, description="Your observations about the chart")


@router.post("/coach/check-rules")
async def check_rule_violations(request: RuleCheckRequest):
    """
    Check a trade idea against your trading rules BEFORE taking the trade.
    
    Returns:
    - Rule violations (critical issues)
    - Warnings (concerns to consider)
    - Passed checks (rules you're following)
    - Position sizing recommendation
    - Overall verdict: PROCEED, CAUTION, or DO NOT TRADE
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.check_rule_violations(
        symbol=request.symbol,
        action=request.action,
        entry_price=request.entry_price,
        position_size=request.position_size,
        stop_loss=request.stop_loss
    )
    
    return result


@router.post("/coach/position-size")
async def get_position_sizing(request: PositionSizingRequest):
    """
    Get AI-powered position sizing recommendation based on:
    - Your trading rules
    - Current market regime
    - Stock volatility (ATR)
    - Risk management best practices
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_position_sizing_guidance(
        symbol=request.symbol,
        entry_price=request.entry_price,
        stop_loss=request.stop_loss,
        account_size=request.account_size
    )
    
    return result


@router.post("/coach/alert")
async def get_coaching_alert(request: CoachingAlertRequest):
    """
    Get proactive coaching alerts for various situations:
    
    Alert types:
    - market_open: Morning coaching tips
    - market_regime_change: Strategy adjustment guidance (include previous_regime, current_regime in data)
    - losing_streak: Support after losses (include consecutive_losses in data)
    - overtrading: Trading frequency warning (include trade_count in data)
    - position_risk: Position size warning (include symbol, shares, exposure in data)
    - rule_reminder: Random rule reminder
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_coaching_alert(
        context_type=request.alert_type,
        data=request.data
    )
    
    return result


@router.post("/coach/review-trade")
async def review_completed_trade(request: TradeReviewRequest):
    """
    Get AI coaching review of a completed trade.
    
    The coach will analyze:
    - Strategy alignment
    - Rule compliance
    - Execution quality
    - Lessons learned
    - Pattern alerts
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    trade_data = {
        "symbol": request.symbol,
        "action": request.action,
        "entry_price": request.entry_price,
        "exit_price": request.exit_price,
        "entry_time": request.entry_time,
        "exit_time": request.exit_time,
        "shares": request.shares,
        "pnl": request.pnl,
        "notes": request.notes
    }
    
    result = await _assistant_service.get_trade_review(trade_data)
    
    return result


@router.get("/coach/daily-summary")
async def get_daily_coaching_summary():
    """
    Get end-of-day coaching summary with:
    - Today's performance review
    - Rule compliance assessment
    - Pattern observations
    - Tomorrow's focus areas
    - Key coaching message
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_daily_coaching_summary()
    
    return result


@router.post("/coach/analyze-setup")
async def analyze_trade_setup(request: SetupAnalysisRequest):
    """
    Get coaching analysis of a trade setup before entry.
    
    Includes:
    - Setup quality rating
    - Strategy match from knowledge base
    - Market regime fit
    - Entry criteria to watch
    - Risk management guidance
    - Warning flags
    - Trade/Wait/Pass verdict
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.analyze_setup(
        symbol=request.symbol,
        setup_type=request.setup_type,
        chart_notes=request.chart_notes
    )
    
    return result


@router.get("/coach/morning-briefing")
async def get_morning_coaching():
    """
    Quick morning coaching briefing with:
    - Current market regime
    - Best strategies for today
    - Key rule reminder
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_coaching_alert("market_open", {})
    
    return result


@router.get("/coach/rule-reminder")
async def get_random_rule_reminder():
    """
    Get a random trading rule reminder from your knowledge base.
    Good for periodic reminders during trading.
    """
    if not _assistant_service:
        raise HTTPException(status_code=500, detail="Assistant service not initialized")
    
    result = await _assistant_service.get_coaching_alert("rule_reminder", {})
    
    return result
