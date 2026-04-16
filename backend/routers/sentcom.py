"""
SentCom Router - Sentient Command API Endpoints
Unified AI command center for the trading team.

Endpoints:
- GET /api/sentcom/status - Current operational status
- GET /api/sentcom/stream - Unified message stream (thoughts + chat + alerts)
- POST /api/sentcom/chat - Send a message to SentCom
- GET /api/sentcom/context - Current market context
- GET /api/sentcom/positions - Our current positions
- GET /api/sentcom/setups - Setups we're watching
- GET /api/sentcom/alerts - Recent alerts
"""
import logging
import os
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from services.sentcom_service import get_sentcom_service, SentComService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sentcom", tags=["SentCom"])


class ChatRequest(BaseModel):
    """Chat message request"""
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    """Chat response"""
    success: bool
    response: str
    agent_used: Optional[str] = None
    intent: Optional[str] = None
    latency_ms: Optional[float] = None
    requires_confirmation: bool = False
    pending_trade: Optional[dict] = None
    source: str = "sentcom"


def _get_service() -> SentComService:
    """Get SentCom service instance"""
    return get_sentcom_service()


@router.get("/status")
async def get_status():
    """
    Get SentCom operational status.
    
    Returns:
    - connected: Whether we're connected to the broker
    - state: Current operational state (active, watching, paused, offline)
    - regime: Current market regime
    - positions_count: Number of open positions
    - watching_count: Number of setups being watched
    - order_pipeline: Order counts (pending, executing, filled)
    """
    try:
        service = _get_service()
        status = await service.get_status()
        return {
            "success": True,
            "status": status.to_dict()
        }
    except Exception as e:
        logger.error(f"Error getting SentCom status: {e}")
        return {
            "success": False,
            "error": str(e),
            "status": {
                "connected": False,
                "state": "error",
                "regime": None,
                "positions_count": 0,
                "watching_count": 0,
                "order_pipeline": {"pending": 0, "executing": 0, "filled": 0}
            }
        }


@router.get("/stream")
async def get_stream(limit: int = Query(20, ge=1, le=100)):
    """
    Get unified SentCom message stream.
    
    Combines:
    - Bot execution thoughts
    - Chat history
    - Filter decisions (smart strategy filtering)
    - System status messages
    
    All messages use "we" voice.
    
    Returns list of messages sorted by timestamp (newest first).
    """
    try:
        service = _get_service()
        messages = await service.get_unified_stream(limit=limit)
        return {
            "success": True,
            "messages": [m.to_dict() for m in messages],
            "count": len(messages)
        }
    except Exception as e:
        logger.error(f"Error getting SentCom stream: {e}")
        return {
            "success": False,
            "error": str(e),
            "messages": [],
            "count": 0
        }



@router.post("/chat-test")
async def chat_test(request: ChatRequest):
    """Quick diagnostic: tests LLM directly, bypasses orchestrator"""
    import time
    import asyncio
    import requests as sync_requests
    start = time.time()
    print(f"[CHAT-TEST] Endpoint reached: {request.message}", flush=True)
    try:
        ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
        
        def _sync_call():
            r = sync_requests.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a helpful trading assistant. Be brief."},
                        {"role": "user", "content": request.message}
                    ],
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 200}
                },
                timeout=30
            )
            return r.json()
        
        data = await asyncio.to_thread(_sync_call)
        content = data.get("message", {}).get("content", "")
        latency = (time.time() - start) * 1000
        print(f"[CHAT-TEST] Success in {latency:.0f}ms: {content[:80]}", flush=True)
        return {
            "success": True,
            "response": content,
            "model": model,
            "latency_ms": latency
        }
    except Exception as e:
        print(f"[CHAT-TEST] Error: {type(e).__name__}: {e}", flush=True)
        return {"success": False, "error": f"{type(e).__name__}: {e}", "latency_ms": (time.time() - start) * 1000}


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Proxy to dedicated chat server (port 8002).
    Uses async httpx — doesn't block any threads.
    """
    import httpx
    
    chat_url = os.environ.get("CHAT_SERVER_URL", "http://127.0.0.1:8002")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{chat_url}/chat",
                json={"message": request.message, "session_id": request.session_id},
            )
            return r.json()
    except httpx.ConnectError:
        return {
            "success": False,
            "response": "Chat server is starting up. Please try again in a few seconds.",
            "source": "sentcom_proxy"
        }
    except httpx.TimeoutException:
        return {
            "success": False,
            "response": "Our AI took too long to respond. Please try again.",
            "source": "sentcom_timeout"
        }
    except Exception as e:
        return {
            "success": False,
            "response": f"Chat error: {e}",
            "source": "sentcom_error"
        }


@router.get("/chat/history")
async def get_chat_history(limit: int = Query(50, ge=1, le=100)):
    """
    Get persisted chat history.
    
    Returns recent chat messages for display in the SentCom panel.
    Messages are loaded from MongoDB for persistence across sessions.
    """
    try:
        service = _get_service()
        # Return the in-memory chat history (already loaded from MongoDB)
        history = service._chat_history[-limit:] if service._chat_history else []
        return {
            "success": True,
            "messages": history,
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        return {
            "success": False,
            "error": str(e),
            "messages": [],
            "count": 0
        }


@router.get("/context")
async def get_context():
    """
    Get current market context for SentCom display.
    
    Returns:
    - regime: Current market regime (RISK_ON, RISK_OFF, etc.)
    - spy_trend: SPY trend direction
    - vix: Current VIX level
    - sector_flow: Leading/lagging sectors
    - market_open: Whether market is currently open
    """
    try:
        service = _get_service()
        context = await service.get_market_context()
        return {
            "success": True,
            "context": context
        }
    except Exception as e:
        logger.error(f"Error getting market context: {e}")
        return {
            "success": False,
            "error": str(e),
            "context": {
                "regime": "UNKNOWN",
                "spy_trend": None,
                "vix": None,
                "market_open": False
            }
        }


@router.get("/positions")
async def get_positions():
    """
    Get our current positions with P&L.
    
    Returns list of positions with:
    - symbol, shares, entry_price, current_price
    - pnl (dollar amount), pnl_percent
    - stop_price, target_prices
    - status, entry_time
    """
    try:
        service = _get_service()
        positions = await service.get_our_positions()
        
        # Calculate totals
        total_pnl = sum(p.get("pnl", 0) for p in positions)
        
        return {
            "success": True,
            "positions": positions,
            "count": len(positions),
            "total_pnl": round(total_pnl, 2)
        }
    except Exception as e:
        logger.error(f"Error getting positions: {e}")
        return {
            "success": False,
            "error": str(e),
            "positions": [],
            "count": 0,
            "total_pnl": 0
        }


@router.get("/setups")
async def get_setups():
    """
    Get setups we're currently watching.
    
    Returns list of setups with:
    - symbol, setup_type, trigger_price
    - current_price, risk_reward, confidence
    """
    try:
        service = _get_service()
        setups = await service.get_setups_watching()
        return {
            "success": True,
            "setups": setups,
            "count": len(setups)
        }
    except Exception as e:
        logger.error(f"Error getting setups: {e}")
        return {
            "success": False,
            "error": str(e),
            "setups": [],
            "count": 0
        }


@router.get("/alerts")
async def get_alerts(limit: int = Query(10, ge=1, le=50)):
    """
    Get recent alerts and notifications.
    
    Returns alerts about:
    - Positions approaching stops
    - Positions hitting targets
    - Strong runners
    - Market regime changes
    """
    try:
        service = _get_service()
        alerts = await service.get_recent_alerts(limit=limit)
        return {
            "success": True,
            "alerts": alerts,
            "count": len(alerts)
        }
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        return {
            "success": False,
            "error": str(e),
            "alerts": [],
            "count": 0
        }


@router.get("/health")
async def health_check():
    """SentCom health check endpoint"""
    try:
        service = _get_service()
        status = await service.get_status()
        return {
            "healthy": True,
            "connected": status.connected,
            "state": status.state
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e)
        }


@router.get("/learning/insights")
async def get_learning_insights(symbol: str = Query(None)):
    """
    Get learning insights for the trader or a specific symbol.
    
    Provides:
    - Trader profile (strengths, weaknesses)
    - Recent patterns and behaviors
    - Strategy performance data
    - Symbol-specific insights (if symbol provided)
    - AI recommendations based on learning
    """
    try:
        service = _get_service()
        insights = await service.get_learning_insights(symbol)
        return {
            "success": True,
            "insights": insights
        }
    except Exception as e:
        logger.error(f"Error getting learning insights: {e}")
        return {
            "success": False,
            "error": str(e),
            "insights": {"available": False}
        }



# ===================== Dynamic Risk Management =====================

class RiskAssessmentRequest(BaseModel):
    """Risk assessment request"""
    symbol: Optional[str] = None
    setup_type: Optional[str] = None


@router.get("/risk")
async def get_risk_status():
    """
    Get current dynamic risk status.
    
    Returns:
    - enabled: Whether dynamic risk is enabled
    - multiplier: Current position size multiplier (0.25x - 2.0x)
    - risk_level: Current risk level (minimal, reduced, normal, elevated, maximum)
    - position_size: Effective position size
    - override_active: Whether a manual override is active
    """
    try:
        service = _get_service()
        context = await service.get_market_context()
        risk_data = context.get("dynamic_risk")
        
        if risk_data:
            return {
                "success": True,
                **risk_data
            }
        else:
            return {
                "success": True,
                "enabled": False,
                "multiplier": 1.0,
                "risk_level": "normal",
                "message": "Dynamic risk engine not available"
            }
    except Exception as e:
        logger.error(f"Error getting risk status: {e}")
        return {
            "success": False,
            "error": str(e),
            "multiplier": 1.0
        }


@router.post("/risk/assess")
async def assess_risk(request: RiskAssessmentRequest):
    """
    Perform a risk assessment for a potential trade.
    
    Args:
        symbol: Optional stock symbol for stock-specific scoring
        setup_type: Optional setup type for learning layer scoring
    
    Returns:
        Complete risk assessment with multiplier, factor breakdown, and explanation
    """
    try:
        service = _get_service()
        assessment = await service.get_risk_assessment(
            symbol=request.symbol,
            setup_type=request.setup_type
        )
        return assessment
    except Exception as e:
        logger.error(f"Error performing risk assessment: {e}")
        return {
            "success": False,
            "error": str(e),
            "multiplier": 1.0,
            "explanation": "Assessment failed"
        }
