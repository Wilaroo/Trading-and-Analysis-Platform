"""
Smart Stop Router - API endpoints for smart stop loss calculations
===================================================================

Provides endpoints for:
- Calculating smart stops with various modes
- Detecting stop hunt patterns
- Getting recommended stop mode for a symbol
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum

from services.smart_stop_service import (
    SmartStopService, SmartStopConfig, StopMode,
    get_smart_stop_service, init_smart_stop_service
)

router = APIRouter(prefix="/api/smart-stops", tags=["smart-stops"])

# Initialize service
_service: SmartStopService = None


def init_smart_stop_router():
    """Initialize the smart stop service"""
    global _service
    _service = get_smart_stop_service()


class StopModeEnum(str, Enum):
    original = "original"
    atr_dynamic = "atr_dynamic"
    anti_hunt = "anti_hunt"
    volatility_adjusted = "volatility_adjusted"
    layered = "layered"
    chandelier = "chandelier"


class SmartStopRequest(BaseModel):
    """Request for smart stop calculation"""
    symbol: str
    entry_price: float
    direction: str  # 'long' or 'short'
    atr: Optional[float] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    swing_low: Optional[float] = None
    swing_high: Optional[float] = None
    volatility_regime: Optional[str] = "normal"
    mode: Optional[StopModeEnum] = StopModeEnum.atr_dynamic


class SmartStopResponse(BaseModel):
    """Response with calculated smart stop"""
    success: bool
    stop_price: float
    stop_mode: str
    stop_reasoning: str
    buffer_applied: float
    anti_hunt_buffer: float
    hunt_risk: str
    layered_stops: Optional[List[Dict]] = None
    obvious_zones_avoided: Optional[List[float]] = None
    constraint_applied: Optional[str] = None
    symbol: str
    entry_price: float
    direction: str


@router.post("/calculate", response_model=SmartStopResponse)
async def calculate_smart_stop(request: SmartStopRequest):
    """
    Calculate a smart stop loss for a trade.
    
    Modes:
    - **original**: Traditional stop below support/swing low with small buffer (HIGH hunt risk)
    - **atr_dynamic**: ATR-based stop with 1.5x ATR buffer (MEDIUM hunt risk)
    - **anti_hunt**: Places stop BEYOND obvious levels with extra buffer (LOW hunt risk)
    - **volatility_adjusted**: Widens in high vol, tightens in low vol
    - **layered**: Multiple stop levels for partial exits (hardest to fully hunt)
    - **chandelier**: ATR-based trailing stop from recent high/low
    """
    if _service is None:
        init_smart_stop_router()
    
    try:
        # Convert string mode to enum
        mode = StopMode(request.mode.value) if request.mode else StopMode.ATR_DYNAMIC
        
        result = _service.calculate_smart_stop(
            entry_price=request.entry_price,
            direction=request.direction,
            symbol=request.symbol,
            atr=request.atr,
            support_level=request.support_level,
            resistance_level=request.resistance_level,
            swing_low=request.swing_low,
            swing_high=request.swing_high,
            current_volatility_regime=request.volatility_regime or "normal",
            mode=mode
        )
        
        return SmartStopResponse(
            success=True,
            stop_price=result.get('stop_price', 0),
            stop_mode=result.get('stop_mode', 'unknown'),
            stop_reasoning=result.get('stop_reasoning', ''),
            buffer_applied=result.get('buffer_applied', 0),
            anti_hunt_buffer=result.get('anti_hunt_buffer', 0),
            hunt_risk=result.get('hunt_risk', 'UNKNOWN'),
            layered_stops=result.get('layered_stops'),
            obvious_zones_avoided=result.get('obvious_zones_avoided'),
            constraint_applied=result.get('constraint_applied'),
            symbol=result.get('symbol', request.symbol),
            entry_price=result.get('entry_price', request.entry_price),
            direction=result.get('direction', request.direction)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/modes")
async def get_stop_modes():
    """
    Get all available smart stop modes with descriptions.
    """
    return {
        "success": True,
        "modes": [
            {
                "id": "original",
                "name": "Original/Traditional",
                "description": "Traditional stop below support/swing low with small buffer",
                "hunt_risk": "HIGH",
                "best_for": "High-volume, liquid stocks in calm markets"
            },
            {
                "id": "atr_dynamic",
                "name": "ATR Dynamic",
                "description": "ATR-based stop with 1.5x ATR buffer from entry",
                "hunt_risk": "MEDIUM",
                "best_for": "General purpose - good balance of protection vs room to breathe"
            },
            {
                "id": "anti_hunt",
                "name": "Anti-Hunt",
                "description": "Places stop BEYOND obvious levels (support, round numbers) with extra buffer",
                "hunt_risk": "LOW",
                "best_for": "Low-float stocks, pre/after hours, or when you suspect manipulation"
            },
            {
                "id": "volatility_adjusted",
                "name": "Volatility Adjusted",
                "description": "Widens stops in high volatility, tightens in low volatility",
                "hunt_risk": "LOW to MEDIUM",
                "best_for": "Adapting to changing market conditions"
            },
            {
                "id": "layered",
                "name": "Layered",
                "description": "Multiple stop levels for partial exits (40%/30%/30% at progressively deeper levels)",
                "hunt_risk": "LOW",
                "best_for": "Larger positions where you want to survive brief sweeps"
            },
            {
                "id": "chandelier",
                "name": "Chandelier Exit",
                "description": "ATR-based stop trailing from recent high (longs) or low (shorts)",
                "hunt_risk": "MEDIUM",
                "best_for": "Trend-following trades where you want to let winners run"
            }
        ]
    }


@router.get("/recommend/{symbol}")
async def recommend_stop_mode(
    symbol: str,
    float_shares: Optional[float] = Query(None, description="Float shares (if known)"),
    avg_volume: Optional[float] = Query(None, description="Average daily volume"),
    volatility_regime: Optional[str] = Query("normal", description="Current volatility regime"),
    time_of_day: Optional[str] = Query("regular", description="Trading session: premarket, regular, afterhours")
):
    """
    Get recommended stop mode for a symbol based on its characteristics.
    
    Low float/volume stocks get ANTI_HUNT recommendation.
    High volatility gets VOLATILITY_ADJUSTED.
    Pre/after hours gets ANTI_HUNT.
    """
    if _service is None:
        init_smart_stop_router()
    
    recommended_mode = _service.get_recommended_mode(
        symbol=symbol,
        float_shares=float_shares,
        avg_volume=avg_volume,
        volatility_regime=volatility_regime or "normal",
        time_of_day=time_of_day or "regular"
    )
    
    mode_descriptions = {
        StopMode.ORIGINAL: "Traditional stop placement - only for very liquid stocks in calm markets",
        StopMode.ATR_DYNAMIC: "ATR-based dynamic stop - good general-purpose choice",
        StopMode.ANTI_HUNT: "Anti-hunt stop - recommended due to potential manipulation risk",
        StopMode.VOLATILITY_ADJUSTED: "Volatility-adjusted stop - adapts to current market conditions",
        StopMode.LAYERED: "Layered stops - for large positions needing extra protection",
        StopMode.CHANDELIER: "Chandelier exit - for trend-following trades"
    }
    
    reasons = []
    if float_shares and float_shares < 10_000_000:
        reasons.append("Low float stock - higher manipulation risk")
    if avg_volume and avg_volume < 500_000:
        reasons.append("Low average volume - easier to push price")
    if volatility_regime in ['high', 'extreme']:
        reasons.append(f"{volatility_regime.capitalize()} volatility - wider stops needed")
    if time_of_day in ['premarket', 'afterhours']:
        reasons.append(f"{time_of_day.capitalize()} session - thinner liquidity")
    
    if not reasons:
        reasons.append("Standard liquid stock in normal conditions")
    
    return {
        "success": True,
        "symbol": symbol,
        "recommended_mode": recommended_mode.value,
        "description": mode_descriptions.get(recommended_mode, ""),
        "reasons": reasons,
        "input_characteristics": {
            "float_shares": float_shares,
            "avg_volume": avg_volume,
            "volatility_regime": volatility_regime,
            "time_of_day": time_of_day
        }
    }


@router.get("/compare")
async def compare_stop_modes(
    entry_price: float = Query(..., description="Entry price"),
    direction: str = Query(..., description="Trade direction: long or short"),
    atr: float = Query(..., description="ATR value"),
    support: Optional[float] = Query(None, description="Support level"),
    resistance: Optional[float] = Query(None, description="Resistance level")
):
    """
    Compare all stop modes for a given trade setup.
    
    Useful for understanding how different modes would place stops
    and choosing the best one for your risk tolerance.
    """
    if _service is None:
        init_smart_stop_router()
    
    results = {}
    
    for mode in StopMode:
        try:
            result = _service.calculate_smart_stop(
                entry_price=entry_price,
                direction=direction,
                symbol="COMPARE",
                atr=atr,
                support_level=support,
                resistance_level=resistance,
                mode=mode
            )
            
            risk_pct = abs(entry_price - result['stop_price']) / entry_price * 100
            
            results[mode.value] = {
                'stop_price': result['stop_price'],
                'risk_percent': round(risk_pct, 2),
                'buffer_applied': result.get('buffer_applied', 0),
                'hunt_risk': result.get('hunt_risk', 'UNKNOWN'),
                'reasoning': result.get('stop_reasoning', '')
            }
        except Exception as e:
            results[mode.value] = {'error': str(e)}
    
    # Sort by stop price (widest to tightest for longs)
    sorted_modes = sorted(
        [(k, v) for k, v in results.items() if 'stop_price' in v],
        key=lambda x: x[1]['stop_price'],
        reverse=(direction == 'long')
    )
    
    return {
        "success": True,
        "entry_price": entry_price,
        "direction": direction,
        "atr": atr,
        "comparison": results,
        "ranked_by_protection": [m[0] for m in sorted_modes]
    }
