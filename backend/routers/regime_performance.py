"""
Regime Performance API Router
==============================
API endpoints for regime-based strategy performance analysis.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regime-performance", tags=["Regime Performance"])

# Service instance (will be injected)
_regime_performance_service = None


def init_regime_performance_router(service):
    """Initialize router with the regime performance service"""
    global _regime_performance_service
    _regime_performance_service = service


@router.get("/summary")
async def get_regime_summary():
    """
    Get overall performance summary grouped by market regime.
    
    Shows aggregate stats for each regime (RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN).
    """
    if not _regime_performance_service:
        raise HTTPException(status_code=500, detail="Regime performance service not initialized")
    
    summary = await _regime_performance_service.get_regime_summary()
    return {
        "success": True,
        **summary
    }


@router.get("/strategies")
async def get_strategy_performance(
    strategy_name: Optional[str] = Query(None, description="Filter by strategy name"),
    market_regime: Optional[str] = Query(None, description="Filter by regime")
):
    """
    Get strategy performance data segmented by regime.
    
    Can filter by specific strategy, specific regime, or get all combinations.
    """
    if not _regime_performance_service:
        raise HTTPException(status_code=500, detail="Regime performance service not initialized")
    
    results = await _regime_performance_service.get_strategy_regime_performance(
        strategy_name=strategy_name,
        market_regime=market_regime
    )
    
    return {
        "success": True,
        "count": len(results),
        "performance": results
    }


@router.get("/best-for-regime/{regime}")
async def get_best_strategies_for_regime(
    regime: str,
    min_trades: int = Query(5, description="Minimum trades required"),
    sort_by: str = Query("expectancy", description="Sort by: expectancy, win_rate, profit_factor, total_pnl")
):
    """
    Get the best performing strategies for a specific market regime.
    
    Useful for strategy selection based on current market conditions.
    
    Regimes:
    - RISK_ON: Bull market, full risk appetite
    - CAUTION: Mixed signals, reduce exposure
    - RISK_OFF: Bearish signals, defensive positioning  
    - CONFIRMED_DOWN: Confirmed downtrend, favor shorts
    """
    if not _regime_performance_service:
        raise HTTPException(status_code=500, detail="Regime performance service not initialized")
    
    if regime.upper() not in ["RISK_ON", "CAUTION", "RISK_OFF", "CONFIRMED_DOWN"]:
        raise HTTPException(status_code=400, detail=f"Invalid regime: {regime}")
    
    results = await _regime_performance_service.get_best_strategies_for_regime(
        market_regime=regime.upper(),
        min_trades=min_trades,
        sort_by=sort_by
    )
    
    return {
        "success": True,
        "regime": regime.upper(),
        "count": len(results),
        "best_strategies": results
    }


@router.get("/position-sizing-impact")
async def get_position_sizing_impact():
    """
    Analyze the impact of regime-based position sizing.
    
    Shows how reducing position sizes in adverse regimes affected overall P&L.
    Compares trades taken at full size vs reduced size.
    """
    if not _regime_performance_service:
        raise HTTPException(status_code=500, detail="Regime performance service not initialized")
    
    analysis = await _regime_performance_service.get_position_sizing_impact()
    return {
        "success": True,
        **analysis
    }


@router.get("/recommendations")
async def get_regime_recommendations():
    """
    Get strategy recommendations based on historical regime performance.
    
    Returns suggested strategies for each regime based on past performance data.
    """
    if not _regime_performance_service:
        raise HTTPException(status_code=500, detail="Regime performance service not initialized")
    
    recommendations = {}
    
    for regime in ["RISK_ON", "CAUTION", "RISK_OFF", "CONFIRMED_DOWN"]:
        try:
            best = await _regime_performance_service.get_best_strategies_for_regime(
                market_regime=regime,
                min_trades=3,
                sort_by="expectancy"
            )
            
            recommendations[regime] = {
                "top_strategies": [s["strategy_name"] for s in best[:5]],
                "suggested_position_size": {
                    "RISK_ON": "100%",
                    "CAUTION": "75%",
                    "RISK_OFF": "50%",
                    "CONFIRMED_DOWN": "25% longs / 100% shorts"
                }.get(regime, "100%"),
                "notes": {
                    "RISK_ON": "Full position sizes, favor momentum and breakout strategies",
                    "CAUTION": "Reduce size, use tighter stops, favor mean reversion",
                    "RISK_OFF": "Half size on longs, consider defensive sectors",
                    "CONFIRMED_DOWN": "Minimal longs, favor shorts and mean reversion bounces"
                }.get(regime, "")
            }
        except Exception as e:
            recommendations[regime] = {"error": str(e)}
    
    return {
        "success": True,
        "recommendations": recommendations
    }
