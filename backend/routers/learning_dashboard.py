"""
Learning Dashboard API Router
Endpoints for strategy performance, AI analysis, and auto-tuning.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/learning", tags=["learning-dashboard"])

_perf_service = None


def init_learning_dashboard(perf_service):
    global _perf_service
    _perf_service = perf_service


class RecommendationAction(BaseModel):
    action: str  # "apply" or "dismiss"


@router.get("/strategy-stats")
async def get_strategy_stats():
    """Get per-strategy performance statistics"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    stats = _perf_service.get_strategy_stats()
    return {"success": True, "stats": stats}


@router.get("/recent-trades")
async def get_recent_trades(strategy: Optional[str] = None, limit: int = 20):
    """Get recent trade records for performance analysis"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    trades = _perf_service.get_recent_trades(strategy=strategy, limit=limit)
    return {"success": True, "trades": trades, "count": len(trades)}


@router.post("/analyze")
async def analyze_performance():
    """Trigger AI analysis of strategy performance"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    result = await _perf_service.analyze_performance()
    return result


@router.get("/recommendations")
async def get_recommendations():
    """Get pending tuning recommendations"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    recs = _perf_service.get_pending_recommendations()
    return {"success": True, "recommendations": recs}


@router.post("/recommendations/{rec_id}")
async def handle_recommendation(rec_id: str, body: RecommendationAction):
    """Apply or dismiss a recommendation"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    
    if body.action == "apply":
        return _perf_service.apply_recommendation(rec_id)
    elif body.action == "dismiss":
        return _perf_service.dismiss_recommendation(rec_id)
    else:
        raise HTTPException(status_code=400, detail="Action must be 'apply' or 'dismiss'")


@router.get("/tuning-history")
async def get_tuning_history(limit: int = 20):
    """Get audit trail of tuning actions"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    history = _perf_service.get_tuning_history(limit=limit)
    return {"success": True, "history": history}
