"""
Market Regime Router
====================
API endpoints for the Market Regime Engine.

TO DEPLOY:
----------
In server.py, add:
    from routers.market_regime import router as market_regime_router, init_market_regime_engine
    init_market_regime_engine(market_regime_engine)
    app.include_router(market_regime_router)
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/market-regime", tags=["market-regime"])

# Will be initialized from main server
_market_regime_engine = None


def init_market_regime_engine(engine):
    """Initialize the market regime engine reference."""
    global _market_regime_engine
    _market_regime_engine = engine


class RefreshResponse(BaseModel):
    """Response model for refresh endpoint."""
    success: bool
    message: str


@router.get("/current")
async def get_current_regime(force_refresh: bool = Query(False, description="Force refresh bypassing cache")):
    """
    Get the current market regime analysis.
    
    Returns:
    - state: CONFIRMED_UP | HOLD | CONFIRMED_DOWN
    - composite_score: 0-100 overall bullishness score
    - risk_level: 0-100 risk level (inverse of composite)
    - confidence: 0-100 confidence in the signal
    - signal_blocks: Detailed breakdown of each signal block
    - recommendation: Trading guidance based on current regime
    - trading_implications: Specific trading adjustments
    
    Cache TTL: 30 minutes (unless force_refresh=true)
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        regime = await _market_regime_engine.get_current_regime(force_refresh=force_refresh)
        return regime
    except Exception as e:
        raise HTTPException(500, f"Error calculating regime: {str(e)}")


@router.get("/state")
async def get_market_state():
    """
    Get just the market state without full analysis.
    Lightweight endpoint for quick checks.
    
    Returns:
    - state: CONFIRMED_UP | HOLD | CONFIRMED_DOWN
    - composite_score: 0-100
    - risk_level: 0-100
    - last_updated: timestamp
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        regime = await _market_regime_engine.get_current_regime()
        return {
            "state": regime.get("state"),
            "composite_score": regime.get("composite_score"),
            "risk_level": regime.get("risk_level"),
            "confidence": regime.get("confidence"),
            "recommendation": regime.get("recommendation"),
            "last_updated": regime.get("last_updated")
        }
    except Exception as e:
        raise HTTPException(500, f"Error getting state: {str(e)}")


@router.get("/signals/{block}")
async def get_signal_block(block: str):
    """
    Get detailed analysis for a specific signal block.
    
    Args:
        block: trend | breadth | ftd | volume_vix
    
    Returns:
        Detailed signal block data including individual indicators
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    valid_blocks = ["trend", "breadth", "ftd", "volume_vix"]
    if block not in valid_blocks:
        raise HTTPException(400, f"Invalid block. Must be one of: {', '.join(valid_blocks)}")
    
    try:
        regime = await _market_regime_engine.get_current_regime()
        signal_blocks = regime.get("signal_blocks", {})
        
        if block not in signal_blocks:
            raise HTTPException(404, f"Signal block '{block}' not found")
        
        return {
            "block": block,
            "data": signal_blocks[block],
            "weight": signal_blocks[block].get("weight", 0),
            "contribution": round(
                signal_blocks[block].get("score", 0) * signal_blocks[block].get("weight", 0), 
                1
            )
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error getting signal block: {str(e)}")


@router.get("/history")
async def get_regime_history(days: int = Query(30, ge=1, le=365, description="Number of days of history")):
    """
    Get historical regime data.
    
    Args:
        days: Number of days of history to retrieve (1-365, default 30)
    
    Returns:
        List of daily regime snapshots
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        history = await _market_regime_engine.get_history(days)
        return {
            "days_requested": days,
            "records_found": len(history),
            "history": history
        }
    except Exception as e:
        raise HTTPException(500, f"Error getting history: {str(e)}")


@router.get("/state-changes")
async def get_state_changes(days: int = Query(30, ge=1, le=365)):
    """
    Get only the regime state changes (transitions between states).
    Useful for identifying market turning points.
    
    Args:
        days: Number of days to look back
    
    Returns:
        List of state change events with before/after states
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        changes = await _market_regime_engine.get_state_changes(days)
        return {
            "days_requested": days,
            "state_changes_found": len(changes),
            "changes": changes
        }
    except Exception as e:
        raise HTTPException(500, f"Error getting state changes: {str(e)}")


@router.post("/refresh")
async def force_refresh_regime():
    """
    Force a refresh of the market regime calculation.
    Bypasses cache and recalculates all signal blocks.
    
    Returns:
        Fresh regime analysis
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        regime = await _market_regime_engine.get_current_regime(force_refresh=True)
        return {
            "success": True,
            "message": "Regime refreshed successfully",
            "regime": regime
        }
    except Exception as e:
        raise HTTPException(500, f"Error refreshing regime: {str(e)}")


@router.get("/trading-implications")
async def get_trading_implications():
    """
    Get specific trading implications based on current regime.
    Includes position sizing, favored/avoided strategies, and risk tolerance.
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        regime = await _market_regime_engine.get_current_regime()
        return {
            "state": regime.get("state"),
            "implications": regime.get("trading_implications"),
            "recommendation": regime.get("recommendation")
        }
    except Exception as e:
        raise HTTPException(500, f"Error getting implications: {str(e)}")


@router.get("/summary")
async def get_regime_summary():
    """
    Get a concise summary of the current market regime.
    Ideal for display in UI widgets or quick reference.
    """
    if not _market_regime_engine:
        raise HTTPException(503, "Market Regime Engine not initialized")
    
    try:
        regime = await _market_regime_engine.get_current_regime()
        
        # Extract key metrics from signal blocks
        signal_blocks = regime.get("signal_blocks", {})
        
        return {
            "state": regime.get("state"),
            "state_display": _get_state_display(regime.get("state")),
            "composite_score": regime.get("composite_score"),
            "risk_level": regime.get("risk_level"),
            "confidence": regime.get("confidence"),
            "signal_scores": {
                "trend": signal_blocks.get("trend", {}).get("score", 0),
                "breadth": signal_blocks.get("breadth", {}).get("score", 0),
                "ftd": signal_blocks.get("ftd", {}).get("score", 0),
                "volume_vix": signal_blocks.get("volume_vix", {}).get("score", 0)
            },
            "recommendation": regime.get("recommendation"),
            "last_updated": regime.get("last_updated")
        }
    except Exception as e:
        raise HTTPException(500, f"Error getting summary: {str(e)}")


def _get_state_display(state: str) -> dict:
    """Get display properties for a state."""
    displays = {
        "CONFIRMED_UP": {
            "label": "Confirmed Up",
            "color": "green",
            "icon": "trending-up",
            "emoji": "🟢"
        },
        "HOLD": {
            "label": "Hold / Neutral",
            "color": "yellow",
            "icon": "minus",
            "emoji": "🟡"
        },
        "CONFIRMED_DOWN": {
            "label": "Confirmed Down",
            "color": "red",
            "icon": "trending-down",
            "emoji": "🔴"
        }
    }
    return displays.get(state, displays["HOLD"])
