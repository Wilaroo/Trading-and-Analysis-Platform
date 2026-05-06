"""
Portfolio Awareness Router - API endpoints for proactive portfolio suggestions
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from services.portfolio_awareness_service import get_portfolio_awareness_service, PortfolioAwarenessService
from services.alpaca_service import get_alpaca_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio-awareness", tags=["Portfolio Awareness"])

# Service instance
_service: Optional[PortfolioAwarenessService] = None

async def _get_service() -> PortfolioAwarenessService:
    global _service
    if _service is None:
        _service = get_portfolio_awareness_service()
        alpaca = get_alpaca_service()
        await _service.initialize(alpaca_service=alpaca)
    return _service


class DismissRequest(BaseModel):
    suggestion_id: str


@router.get("/suggestions")
async def get_suggestions():
    """
    Get all active portfolio suggestions
    Returns proactive AI recommendations based on current positions
    """
    try:
        service = await _get_service()
        suggestions = service.get_active_suggestions()
        return {
            "success": True,
            "suggestions": suggestions,
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"Error getting portfolio suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_portfolio():
    """
    Trigger a fresh portfolio analysis
    Generates new suggestions based on current market conditions
    """
    try:
        service = await _get_service()
        suggestions = await service.analyze_portfolio()
        return {
            "success": True,
            "suggestions": [s if isinstance(s, dict) else s.to_dict() for s in suggestions],
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"Error analyzing portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dismiss")
async def dismiss_suggestion(request: DismissRequest):
    """
    Dismiss a suggestion by ID
    Dismissed suggestions won't appear again until they expire
    """
    try:
        service = await _get_service()
        success = service.dismiss_suggestion(request.suggestion_id)
        return {
            "success": success,
            "suggestion_id": request.suggestion_id
        }
    except Exception as e:
        logger.error(f"Error dismissing suggestion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_portfolio_summary():
    """
    Get a summary of portfolio health and active suggestions
    """
    try:
        service = await _get_service()
        summary = service.get_portfolio_summary()
        return {
            "success": True,
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error getting portfolio summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start-monitoring")
async def start_monitoring():
    """
    Start background portfolio monitoring
    Will generate suggestions automatically
    """
    try:
        service = await _get_service()
        await service.start_monitoring()
        return {
            "success": True,
            "message": "Portfolio monitoring started"
        }
    except Exception as e:
        logger.error(f"Error starting monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop-monitoring")
async def stop_monitoring():
    """
    Stop background portfolio monitoring
    """
    try:
        service = await _get_service()
        await service.stop_monitoring()
        return {
            "success": True,
            "message": "Portfolio monitoring stopped"
        }
    except Exception as e:
        logger.error(f"Error stopping monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))
