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


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a message to SentCom.
    
    Routes the message to the appropriate AI agent and returns
    a unified response in "we" voice.
    
    Supports:
    - Trade queries ("How's our NVDA position?")
    - Analysis requests ("What do we think about AAPL?")
    - Coaching ("Should we take profits here?")
    - Trade execution ("Buy 100 shares of TSLA")
    """
    try:
        service = _get_service()
        result = await service.chat(request.message, request.session_id)
        return ChatResponse(**result)
    except Exception as e:
        logger.error(f"SentCom chat error: {e}")
        return ChatResponse(
            success=False,
            response=f"We encountered an issue processing that request: {str(e)}",
            source="sentcom_error"
        )


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
