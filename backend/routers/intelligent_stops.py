"""
Intelligent Stop Router - Advanced stop loss API endpoints
============================================================

Provides endpoints for the Intelligent Stop Manager that combines:
- Volume profile analysis
- Sector/market correlation
- Setup-based rules
- Regime context
- Stop hunt risk assessment
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import pandas as pd

from services.intelligent_stop_manager import (
    IntelligentStopManager, 
    get_intelligent_stop_manager,
    init_intelligent_stop_manager,
    SETUP_STOP_RULES,
    TrailingMode,
    StopUrgency
)

router = APIRouter(prefix="/api/intelligent-stops", tags=["intelligent-stops"])

# Manager instance
_manager: IntelligentStopManager = None


def get_manager() -> IntelligentStopManager:
    """Get or initialize the manager"""
    global _manager
    if _manager is None:
        _manager = get_intelligent_stop_manager()
    return _manager


class IntelligentStopRequest(BaseModel):
    """Request for intelligent stop calculation"""
    symbol: str
    entry_price: float
    current_price: float
    direction: str  # 'long' or 'short'
    setup_type: str
    position_size: int
    atr: float
    # Optional enhanced inputs
    swing_low: Optional[float] = None
    swing_high: Optional[float] = None
    support_levels: Optional[List[float]] = None
    resistance_levels: Optional[List[float]] = None
    float_shares: Optional[float] = None
    avg_volume: Optional[float] = None
    # Risk parameters
    max_risk_dollars: Optional[float] = None
    max_risk_percent: Optional[float] = 0.02
    account_balance: Optional[float] = None


class IntelligentStopResponse(BaseModel):
    """Response with intelligent stop calculation"""
    success: bool
    # Primary stop
    stop_price: float
    stop_distance_pct: float
    stop_distance_atr: float
    # Reasoning
    primary_factor: str
    factors_considered: List[str]
    confidence: float
    # Alerts
    urgency: str
    warnings: List[str]
    # Trailing
    trailing_mode: str
    trailing_trigger_price: float
    breakeven_trigger_price: float
    # Layered exits
    layered_stops: List[Dict]
    scale_out_plan: List[Dict]
    # Context
    volume_profile_support: Optional[float]
    sector_adjustment: float
    regime_adjustment: float
    setup_rules: str
    # Metadata
    calculated_at: str
    valid_until: str


@router.post("/calculate", response_model=IntelligentStopResponse)
async def calculate_intelligent_stop(request: IntelligentStopRequest):
    """
    Calculate an intelligent stop loss using all available factors.
    
    This endpoint combines:
    - **Setup-based rules**: Different setups need different stop strategies
    - **Volume profile**: Support/resistance based on volume distribution
    - **Sector correlation**: Adjusts stops based on relative strength
    - **Regime context**: Widens/tightens based on market conditions
    - **Stop hunt protection**: Avoids obvious stop zones
    - **Layered exits**: Multiple stop levels for partial exits
    - **Scale-out plan**: Profit-taking targets based on R-multiples
    
    The response includes:
    - Primary stop price with confidence score
    - Trailing stop behavior and triggers
    - Layered stops for partial exits
    - Scale-out profit targets
    - Warnings and urgency level
    """
    manager = get_manager()
    
    try:
        result = await manager.calculate_intelligent_stop(
            symbol=request.symbol,
            entry_price=request.entry_price,
            current_price=request.current_price,
            direction=request.direction,
            setup_type=request.setup_type,
            position_size=request.position_size,
            atr=request.atr,
            swing_low=request.swing_low,
            swing_high=request.swing_high,
            support_levels=request.support_levels,
            resistance_levels=request.resistance_levels,
            float_shares=request.float_shares,
            avg_volume=request.avg_volume,
            max_risk_dollars=request.max_risk_dollars,
            max_risk_percent=request.max_risk_percent,
            account_balance=request.account_balance
        )
        
        return IntelligentStopResponse(
            success=True,
            stop_price=result.stop_price,
            stop_distance_pct=result.stop_distance_pct,
            stop_distance_atr=result.stop_distance_atr,
            primary_factor=result.primary_factor,
            factors_considered=result.factors_considered,
            confidence=result.confidence,
            urgency=result.urgency.value,
            warnings=result.warnings,
            trailing_mode=result.trailing_mode.value,
            trailing_trigger_price=result.trailing_trigger_price,
            breakeven_trigger_price=result.breakeven_trigger_price,
            layered_stops=result.layered_stops,
            scale_out_plan=result.scale_out_plan,
            volume_profile_support=result.volume_profile_support,
            sector_adjustment=result.sector_adjustment,
            regime_adjustment=result.regime_adjustment,
            setup_rules=result.setup_rules,
            calculated_at=result.calculated_at,
            valid_until=result.valid_until
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/setup-rules")
async def get_setup_rules():
    """
    Get all available setup-based stop rules.
    
    Each setup type has specific rules for:
    - Initial stop distance (ATR multiplier)
    - Trailing mode and parameters
    - Break-even trigger
    - Scale-out levels
    """
    rules = {}
    for name, rule in SETUP_STOP_RULES.items():
        rules[name] = {
            "setup_type": rule.setup_type,
            "description": rule.description,
            "initial_stop_atr_mult": rule.initial_stop_atr_mult,
            "trailing_mode": rule.trailing_mode.value,
            "trailing_atr_mult": rule.trailing_atr_mult,
            "breakeven_r_target": rule.breakeven_r_target,
            "scale_out_levels": rule.scale_out_levels,
            "min_stop_distance_pct": rule.min_stop_distance_pct,
            "max_stop_distance_pct": rule.max_stop_distance_pct,
            "use_swing_levels": rule.use_swing_levels,
            "use_volume_profile": rule.use_volume_profile,
            "respect_regime": rule.respect_regime
        }
    
    return {
        "success": True,
        "setup_rules": rules,
        "available_setups": list(rules.keys())
    }


@router.get("/trailing-modes")
async def get_trailing_modes():
    """
    Get all available trailing stop modes.
    """
    return {
        "success": True,
        "modes": [
            {
                "id": mode.value,
                "name": mode.name.replace("_", " ").title(),
                "description": {
                    "none": "Static stop - no trailing",
                    "atr": "Trail by ATR distance from current price",
                    "percent": "Trail by percentage from high/low",
                    "chandelier": "Trail from highest high (longs) or lowest low (shorts)",
                    "breakeven_plus": "Move to break-even after profit target, then small trail",
                    "parabolic": "Accelerating trail that tightens as profit grows"
                }.get(mode.value, "")
            }
            for mode in TrailingMode
        ]
    }


@router.get("/urgency-levels")
async def get_urgency_levels():
    """
    Get all urgency levels and their meanings.
    """
    return {
        "success": True,
        "levels": [
            {
                "id": "normal",
                "name": "Normal",
                "description": "Standard stop behavior, no immediate action needed",
                "action": "Monitor normally"
            },
            {
                "id": "caution",
                "name": "Caution",
                "description": "Consider tightening stop or reducing position",
                "action": "Watch closely, may tighten"
            },
            {
                "id": "high_alert",
                "name": "High Alert",
                "description": "Actively tighten stop, potential reversal",
                "action": "Tighten stop immediately"
            },
            {
                "id": "emergency",
                "name": "Emergency",
                "description": "Execute stop immediately if possible",
                "action": "Exit position NOW"
            }
        ]
    }


@router.post("/analyze-trade")
async def analyze_trade_stop(
    symbol: str,
    entry_price: float,
    current_price: float,
    stop_price: float,
    direction: str,
    setup_type: str,
    atr: float
):
    """
    Analyze an existing trade's stop placement.
    
    Returns recommendations for improving the stop based on
    current market conditions and intelligent analysis.
    """
    manager = get_manager()
    
    try:
        # Calculate what the intelligent stop would be
        optimal = await manager.calculate_intelligent_stop(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            setup_type=setup_type,
            position_size=100,  # Dummy for analysis
            atr=atr
        )
        
        # Compare current vs optimal
        current_distance_pct = abs(stop_price - entry_price) / entry_price
        optimal_distance_pct = optimal.stop_distance_pct
        
        recommendations = []
        
        if direction == 'long':
            if stop_price > optimal.stop_price + atr * 0.3:
                recommendations.append({
                    "type": "too_tight",
                    "severity": "warning",
                    "message": f"Stop may be too tight. Consider moving to ${optimal.stop_price:.2f}",
                    "suggested_stop": optimal.stop_price
                })
            elif stop_price < optimal.stop_price - atr * 0.5:
                recommendations.append({
                    "type": "too_wide",
                    "severity": "info",
                    "message": f"Stop is wider than optimal. Could tighten to ${optimal.stop_price:.2f}",
                    "suggested_stop": optimal.stop_price
                })
        else:
            if stop_price < optimal.stop_price - atr * 0.3:
                recommendations.append({
                    "type": "too_tight",
                    "severity": "warning",
                    "message": f"Stop may be too tight. Consider moving to ${optimal.stop_price:.2f}",
                    "suggested_stop": optimal.stop_price
                })
            elif stop_price > optimal.stop_price + atr * 0.5:
                recommendations.append({
                    "type": "too_wide",
                    "severity": "info",
                    "message": f"Stop is wider than optimal. Could tighten to ${optimal.stop_price:.2f}",
                    "suggested_stop": optimal.stop_price
                })
        
        # Check for warnings from optimal calculation
        for warning in optimal.warnings:
            recommendations.append({
                "type": "context_warning",
                "severity": "caution",
                "message": warning
            })
        
        # Add trailing recommendation
        if optimal.trailing_mode != TrailingMode.NONE:
            pnl_pct = (current_price - entry_price) / entry_price * 100 if direction == 'long' else (entry_price - current_price) / entry_price * 100
            if pnl_pct > 0:
                recommendations.append({
                    "type": "trailing",
                    "severity": "info",
                    "message": f"Consider trailing stop ({optimal.trailing_mode.value}). Current P&L: {pnl_pct:.1f}%"
                })
        
        return {
            "success": True,
            "current_stop": {
                "price": stop_price,
                "distance_pct": round(current_distance_pct * 100, 2),
                "distance_atr": round(abs(stop_price - entry_price) / atr, 2)
            },
            "optimal_stop": {
                "price": optimal.stop_price,
                "distance_pct": round(optimal_distance_pct * 100, 2),
                "distance_atr": optimal.stop_distance_atr,
                "confidence": optimal.confidence
            },
            "urgency": optimal.urgency.value,
            "recommendations": recommendations,
            "factors_considered": optimal.factors_considered
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/volume-profile/{symbol}")
async def get_volume_profile(
    symbol: str,
    bars: int = Query(50, description="Number of bars to analyze")
):
    """
    Get volume profile analysis for a symbol.
    
    Returns:
    - POC (Point of Control): Highest volume price
    - VAH/VAL: Value Area High/Low (70% of volume)
    - HVN: High Volume Nodes (support/resistance)
    - LVN: Low Volume Nodes (fast movement zones)
    """
    manager = get_manager()
    
    # Try to get historical data
    if manager._data_service:
        try:
            df = await manager._data_service.get_historical_bars(symbol, bars)
            if df is not None and len(df) >= 20:
                profile = manager._calculate_volume_profile(df)
                return {
                    "success": True,
                    "symbol": symbol,
                    "profile": {
                        "poc": profile.poc,
                        "vah": profile.vah,
                        "val": profile.val,
                        "hvn_levels": profile.hvn_levels,
                        "lvn_levels": profile.lvn_levels,
                        "total_volume": profile.total_volume,
                        "analysis_period": profile.analysis_period
                    }
                }
        except Exception:
            pass
    
    return {
        "success": False,
        "error": "Historical data not available. Volume profile requires price/volume data.",
        "symbol": symbol
    }
