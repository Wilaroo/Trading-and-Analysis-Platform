"""
Learning Dashboard API Router
Endpoints for strategy performance, AI analysis, and auto-tuning.
Extended with Three-Speed Learning Architecture endpoints (Phase 1).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services.learning_loop_service import get_learning_loop_service

router = APIRouter(prefix="/api/learning", tags=["learning-dashboard"])

_perf_service = None


def init_learning_dashboard(perf_service):
    global _perf_service
    _perf_service = perf_service


class RecommendationAction(BaseModel):
    action: str  # "apply" or "dismiss"


@router.get("/strategy-stats")
def get_strategy_stats():
    """Get per-strategy performance statistics"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    stats = _perf_service.get_strategy_stats()
    return {"success": True, "stats": stats}


@router.get("/recent-trades")
def get_recent_trades(strategy: Optional[str] = None, limit: int = 20):
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
def get_recommendations():
    """Get pending tuning recommendations"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    recs = _perf_service.get_pending_recommendations()
    return {"success": True, "recommendations": recs}


@router.post("/recommendations/{rec_id}")
def handle_recommendation(rec_id: str, body: RecommendationAction):
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
def get_tuning_history(limit: int = 20):
    """Get audit trail of tuning actions"""
    if not _perf_service:
        raise HTTPException(status_code=503, detail="Performance service not initialized")
    history = _perf_service.get_tuning_history(limit=limit)
    return {"success": True, "history": history}


# ==================== THREE-SPEED LEARNING ARCHITECTURE (Phase 1) ====================

@router.get("/loop/stats")
async def get_learning_loop_stats(
    setup_type: Optional[str] = None,
    market_regime: Optional[str] = None,
    time_of_day: Optional[str] = None
):
    """
    Get aggregated learning statistics by context.
    
    Query params:
    - setup_type: Filter by setup type (e.g., "bull_flag", "vwap_bounce")
    - market_regime: Filter by market regime (e.g., "strong_uptrend", "range_bound")
    - time_of_day: Filter by time (e.g., "morning_momentum", "afternoon")
    """
    learning_loop = get_learning_loop_service()
    
    stats = await learning_loop.get_learning_stats(
        setup_type=setup_type,
        market_regime=market_regime,
        time_of_day=time_of_day
    )
    
    return {
        "success": True,
        "stats": [s.to_dict() for s in stats],
        "count": len(stats)
    }


@router.get("/loop/contextual-winrate")
async def get_contextual_win_rate(
    setup_type: str,
    market_regime: Optional[str] = None,
    time_of_day: Optional[str] = None
):
    """
    Get win rate for a specific setup in a specific context.
    Returns confidence level based on sample size.
    """
    learning_loop = get_learning_loop_service()
    
    result = await learning_loop.get_contextual_win_rate(
        setup_type=setup_type,
        market_regime=market_regime,
        time_of_day=time_of_day
    )
    
    return {"success": True, **result}


@router.get("/loop/outcomes")
async def get_trade_outcomes(
    setup_type: Optional[str] = None,
    limit: int = 20
):
    """Get recent trade outcomes with full context and execution data"""
    learning_loop = get_learning_loop_service()
    
    outcomes = await learning_loop.get_recent_outcomes(
        limit=limit,
        setup_type=setup_type
    )
    
    return {
        "success": True,
        "outcomes": [o.to_dict() for o in outcomes],
        "count": len(outcomes)
    }


@router.get("/loop/multiplier-stats")
async def get_multiplier_aware_stats(
    setup_type: Optional[str] = None,
    days_back: int = 30,
):
    """NIA-scoped per-layer cohort lift for the liquidity-aware
    execution layers (stop_guard, target_snap, vp_path). Used by the
    SentComIntelligencePanel to show per-setup-type whether the new
    layers are pulling their weight in live trading.
    """
    learning_loop = get_learning_loop_service()
    stats = await learning_loop.get_multiplier_aware_stats(
        setup_type=setup_type, days_back=days_back,
    )
    return {"success": True, **stats}


@router.get("/loop/profile")
async def get_trader_profile():
    """
    Get current trader profile for RAG injection.
    Shows best/worst setups, hours, execution tendencies.
    """
    learning_loop = get_learning_loop_service()
    
    profile = await learning_loop.get_trader_profile()
    
    return {
        "success": True,
        "profile": profile.to_dict(),
        "ai_context": profile.generate_ai_context()
    }


@router.get("/loop/tilt-status")
def get_tilt_status():
    """Check if trader is currently tilted (based on recent performance)"""
    learning_loop = get_learning_loop_service()
    
    return {
        "success": True,
        "is_tilted": learning_loop.is_tilted(),
        "severity": learning_loop.get_tilt_severity()
    }


@router.post("/loop/daily-analysis")
async def run_daily_analysis():
    """
    Manually trigger end-of-day analysis.
    This is usually auto-triggered at market close.
    
    Performs:
    - Aggregates today's trades into stats
    - Updates trader profile
    - Checks for edge decay
    - Generates calibration recommendations
    """
    learning_loop = get_learning_loop_service()
    
    result = await learning_loop.run_daily_analysis()
    
    return {
        "success": True,
        "analysis": result
    }


@router.get("/loop/health")
def get_learning_system_health():
    """Get health status of the learning system and its services"""
    from services.graceful_degradation import get_degradation_service
    
    degradation = get_degradation_service()
    system_health = degradation.get_system_health()
    
    return {
        "success": True,
        "health": system_health.to_dict()
    }

