"""
Smart Stop Router - Unified Smart Stop Loss API
=================================================

A single, comprehensive API for all stop loss needs. Combines:
- 6 stop calculation modes (original, atr_dynamic, anti_hunt, volatility_adjusted, layered, chandelier)
- 8 setup-based rule sets (breakout, pullback, momentum, etc.)
- Full intelligent analysis (volume profile, sector correlation, regime context, hunt detection)

Endpoints:
- POST /calculate - Simple stop calculation with specific mode
- POST /intelligent-calculate - Full multi-factor intelligent stop
- POST /analyze-trade - Analyze existing trade's stop placement
- GET /modes - List all stop modes
- GET /setup-rules - List all setup-based rules
- GET /trailing-modes - List trailing stop modes
- GET /urgency-levels - List urgency level descriptions
- GET /recommend/{symbol} - Get recommended mode for a symbol
- GET /compare - Compare all stop modes for a setup
- GET /volume-profile/{symbol} - Get volume profile analysis
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from enum import Enum
import pandas as pd

from services.smart_stop_service import (
    SmartStopService, SmartStopConfig, StopMode, TrailingMode, StopUrgency,
    get_smart_stop_service, init_smart_stop_service, SETUP_STOP_RULES
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
def calculate_smart_stop(request: SmartStopRequest):
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
        
        result = _service.calculate_stop(
            entry_price=request.entry_price,
            direction=request.direction,
            symbol=request.symbol,
            atr=request.atr,
            support_level=request.support_level,
            resistance_level=request.resistance_level,
            swing_low=request.swing_low,
            swing_high=request.swing_high,
            volatility_regime=request.volatility_regime or "normal",
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
def get_stop_modes():
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
def recommend_stop_mode(
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
def compare_stop_modes(
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
            result = _service.calculate_stop(
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



# ============================================================================
# INTELLIGENT STOP ENDPOINTS (Merged from intelligent_stops_router)
# ============================================================================

class IntelligentStopRequest(BaseModel):
    """Request for full intelligent stop calculation"""
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


class IntelligentStopResponse(BaseModel):
    """Response from intelligent stop calculation"""
    success: bool
    # Primary stop
    stop_price: float
    stop_distance_pct: float
    stop_distance_atr: float
    # Reasoning
    stop_mode: str
    primary_factor: str
    factors_considered: List[str]
    confidence: float
    # Risk assessment
    hunt_risk: str
    hunt_risk_score: int
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
    setup_rules_used: str
    # Anti-hunt
    obvious_zones_avoided: List[Any]
    anti_hunt_buffer_applied: float
    # Metadata
    symbol: str
    entry_price: float
    direction: str
    calculated_at: str
    valid_until: str


@router.post("/intelligent-calculate", response_model=IntelligentStopResponse)
async def calculate_intelligent_stop(request: IntelligentStopRequest):
    """
    Calculate an intelligent stop loss using ALL available factors.
    
    This is the most comprehensive stop calculation that combines:
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
    if _service is None:
        init_smart_stop_router()
    
    try:
        result = await _service.calculate_intelligent_stop(
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
            max_risk_percent=request.max_risk_percent
        )
        
        return IntelligentStopResponse(
            success=True,
            stop_price=result.stop_price,
            stop_distance_pct=result.stop_distance_pct,
            stop_distance_atr=result.stop_distance_atr,
            stop_mode=result.stop_mode,
            primary_factor=result.primary_factor,
            factors_considered=result.factors_considered,
            confidence=result.confidence,
            hunt_risk=result.hunt_risk,
            hunt_risk_score=result.hunt_risk_score,
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
            setup_rules_used=result.setup_rules_used,
            obvious_zones_avoided=result.obvious_zones_avoided,
            anti_hunt_buffer_applied=result.anti_hunt_buffer_applied,
            symbol=result.symbol,
            entry_price=result.entry_price,
            direction=result.direction,
            calculated_at=result.calculated_at,
            valid_until=result.valid_until
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/setup-rules")
def get_setup_rules():
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
            "scale_out_r_targets": rule.scale_out_r_targets,
            "min_stop_pct": rule.min_stop_pct,
            "max_stop_pct": rule.max_stop_pct,
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
def get_trailing_modes():
    """
    Get all available trailing stop modes with descriptions.
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
def get_urgency_levels():
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
    symbol: str = Query(..., description="Stock symbol"),
    entry_price: float = Query(..., description="Trade entry price"),
    current_price: float = Query(..., description="Current price"),
    stop_price: float = Query(..., description="Current stop price"),
    direction: str = Query(..., description="Trade direction: long or short"),
    setup_type: str = Query("default", description="Setup type"),
    atr: float = Query(..., description="ATR value")
):
    """
    Analyze an existing trade's stop placement.
    
    Returns recommendations for improving the stop based on
    current market conditions and intelligent analysis.
    """
    if _service is None:
        init_smart_stop_router()
    
    try:
        # Calculate what the intelligent stop would be
        optimal = await _service.calculate_intelligent_stop(
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
    if _service is None:
        init_smart_stop_router()
    
    # Try to get historical data from data service
    if _service._data_service:
        try:
            df = await _service._data_service.get_historical_bars(symbol, bars)
            if df is not None and len(df) >= 20:
                profile = _service._calculate_volume_profile(df)
                return {
                    "success": True,
                    "symbol": symbol,
                    "profile": {
                        "poc": profile.poc,
                        "vah": profile.vah,
                        "val": profile.val,
                        "hvn_levels": profile.hvn_levels,
                        "lvn_levels": profile.lvn_levels,
                        "total_volume": profile.total_volume
                    }
                }
        except Exception:
            pass
    
    return {
        "success": False,
        "error": "Historical data not available. Volume profile requires price/volume data.",
        "symbol": symbol
    }


@router.post("/calculate-trailing-stop")
def calculate_trailing_stop(
    symbol: str = Query(..., description="Ticker symbol"),
    entry_price: float = Query(..., description="Original entry price"),
    current_price: float = Query(..., description="Current market price"),
    current_stop: float = Query(..., description="Current stop price"),
    highest_price: float = Query(None, description="Highest price since entry (for longs)"),
    lowest_price: float = Query(None, description="Lowest price since entry (for shorts)"),
    direction: str = Query("long", description="Position direction"),
    trailing_mode: str = Query("atr", description="Trailing mode: atr, percent, chandelier, parabolic"),
    atr: float = Query(None, description="ATR value (optional, will estimate if not provided)")
):
    """
    Calculate optimal trailing stop based on position movement.
    
    Uses the smart stop service to determine if stop should be trailed
    and where to place it.
    
    Returns:
    - new_stop: Suggested new stop price
    - should_trail: Whether stop should be moved
    - reasoning: Explanation of the recommendation
    - lock_in_profit: How much profit would be locked in
    """
    if _service is None:
        raise HTTPException(status_code=503, detail="Smart stop service not available")
    
    try:
        # Estimate ATR if not provided
        if atr is None:
            atr = entry_price * 0.02  # 2% estimate
        
        # Calculate P&L
        if direction == 'long':
            pnl_pct = (current_price - entry_price) / entry_price * 100
            peak_price = highest_price or current_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
            peak_price = lowest_price or current_price
        
        # Calculate new trailing stop
        new_stop = current_stop
        should_trail = False
        reasoning = "No adjustment needed"
        
        # Determine trailing based on mode
        if trailing_mode == "atr":
            # ATR-based trailing: trail by 2 ATR from peak
            if direction == 'long':
                trail_stop = peak_price - (atr * 2.0)
                if trail_stop > current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"ATR trail: Move stop to ${trail_stop:.2f} (2 ATR from ${peak_price:.2f} high)"
            else:
                trail_stop = peak_price + (atr * 2.0)
                if trail_stop < current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"ATR trail: Move stop to ${trail_stop:.2f} (2 ATR from ${peak_price:.2f} low)"
        
        elif trailing_mode == "percent":
            # Percentage-based trailing: trail by 3%
            trail_pct = 0.03
            if direction == 'long':
                trail_stop = peak_price * (1 - trail_pct)
                if trail_stop > current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"Percent trail: Move stop to ${trail_stop:.2f} (3% from ${peak_price:.2f} high)"
            else:
                trail_stop = peak_price * (1 + trail_pct)
                if trail_stop < current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"Percent trail: Move stop to ${trail_stop:.2f} (3% from ${peak_price:.2f} low)"
        
        elif trailing_mode == "chandelier":
            # Chandelier: 3 ATR from peak
            if direction == 'long':
                trail_stop = peak_price - (atr * 3.0)
                if trail_stop > current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"Chandelier: Move stop to ${trail_stop:.2f} (3 ATR from ${peak_price:.2f} high)"
            else:
                trail_stop = peak_price + (atr * 3.0)
                if trail_stop < current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"Chandelier: Move stop to ${trail_stop:.2f} (3 ATR from ${peak_price:.2f} low)"
        
        elif trailing_mode == "parabolic":
            # Parabolic: acceleration factor increases with profit
            base_mult = 2.0
            acceleration = min(pnl_pct / 10, 1.0)  # Accelerate up to 1x reduction
            effective_mult = base_mult - acceleration
            
            if direction == 'long':
                trail_stop = peak_price - (atr * effective_mult)
                if trail_stop > current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"Parabolic: Move stop to ${trail_stop:.2f} ({effective_mult:.1f} ATR - tightening with profit)"
            else:
                trail_stop = peak_price + (atr * effective_mult)
                if trail_stop < current_stop:
                    new_stop = trail_stop
                    should_trail = True
                    reasoning = f"Parabolic: Move stop to ${trail_stop:.2f} ({effective_mult:.1f} ATR - tightening with profit)"
        
        # Break-even check: if profitable but not trailing, consider B/E
        if not should_trail and pnl_pct >= 1.5:  # 1.5R or more
            be_stop = entry_price + (atr * 0.1) if direction == 'long' else entry_price - (atr * 0.1)
            if (direction == 'long' and be_stop > current_stop) or (direction == 'short' and be_stop < current_stop):
                new_stop = be_stop
                should_trail = True
                reasoning = f"Break-even: Move stop to ${be_stop:.2f} to lock in profit"
        
        # Calculate profit that would be locked in
        if direction == 'long':
            lock_in_profit = (new_stop - entry_price) / entry_price * 100
        else:
            lock_in_profit = (entry_price - new_stop) / entry_price * 100
        
        return {
            "success": True,
            "symbol": symbol,
            "current_stop": current_stop,
            "new_stop": round(new_stop, 2),
            "should_trail": should_trail,
            "reasoning": reasoning,
            "pnl_pct": round(pnl_pct, 2),
            "lock_in_profit_pct": round(max(lock_in_profit, 0), 2),
            "trailing_mode": trailing_mode,
            "peak_price": peak_price
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/auto-trail-positions")
def auto_trail_all_positions():
    """
    Analyze all open positions and suggest trailing stop adjustments.
    
    This is a batch endpoint that:
    1. Gets all open positions from the trading bot
    2. Calculates optimal trailing stop for each
    3. Returns recommendations for stop adjustments
    
    Note: This does NOT automatically move stops - it only suggests.
    """
    if _service is None:
        raise HTTPException(status_code=503, detail="Smart stop service not available")
    
    try:
        # Import trading bot to get positions
        from services.trading_bot_service import get_trading_bot_service
        bot = get_trading_bot_service()
        
        # Get open positions/trades
        open_trades = bot.get_open_trades() if bot else []
        
        if not open_trades:
            return {
                "success": True,
                "message": "No open positions to analyze",
                "recommendations": []
            }
        
        recommendations = []
        
        for trade in open_trades:
            try:
                symbol = trade.get('symbol')
                entry_price = trade.get('entry_price') or trade.get('fill_price')
                current_price = trade.get('current_price') or entry_price
                current_stop = trade.get('stop_price')
                direction = trade.get('direction', 'long')
                
                if not all([symbol, entry_price, current_stop]):
                    continue
                
                # Estimate ATR
                atr = entry_price * 0.02
                
                # Calculate P&L
                if direction == 'long':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    peak_price = max(current_price, entry_price)
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                    peak_price = min(current_price, entry_price)
                
                # Only suggest trailing if profitable
                if pnl_pct <= 0:
                    continue
                
                # Calculate trailing stop
                if direction == 'long':
                    trail_stop = peak_price - (atr * 2.0)
                    if trail_stop > current_stop:
                        lock_in = (trail_stop - entry_price) / entry_price * 100
                        recommendations.append({
                            "symbol": symbol,
                            "direction": direction,
                            "current_stop": current_stop,
                            "suggested_stop": round(trail_stop, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "lock_in_profit_pct": round(max(lock_in, 0), 2),
                            "reasoning": f"{symbol} up {pnl_pct:.1f}% - trail stop to ${trail_stop:.2f} to lock gains",
                            "priority": "high" if pnl_pct >= 3 else "medium"
                        })
                else:
                    trail_stop = peak_price + (atr * 2.0)
                    if trail_stop < current_stop:
                        lock_in = (entry_price - trail_stop) / entry_price * 100
                        recommendations.append({
                            "symbol": symbol,
                            "direction": direction,
                            "current_stop": current_stop,
                            "suggested_stop": round(trail_stop, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "lock_in_profit_pct": round(max(lock_in, 0), 2),
                            "reasoning": f"{symbol} (short) up {pnl_pct:.1f}% - trail stop to ${trail_stop:.2f} to lock gains",
                            "priority": "high" if pnl_pct >= 3 else "medium"
                        })
            
            except Exception:
                continue
        
        return {
            "success": True,
            "positions_analyzed": len(open_trades),
            "recommendations": sorted(recommendations, key=lambda x: x.get('pnl_pct', 0), reverse=True),
            "message": f"{len(recommendations)} positions could benefit from trailing stops"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
