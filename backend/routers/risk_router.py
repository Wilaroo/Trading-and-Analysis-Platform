"""
Risk Management API Router - Phase 3A & 3B Endpoints

Provides API access to:
- Circuit Breakers (risk controls)
- Position Sizing (TQS-based)
- Health Monitoring (system status)
- Dynamic Thresholds (context-aware gating)
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from services.circuit_breaker import get_circuit_breaker_service, CircuitBreakerType
from services.position_sizer import get_position_sizer_service
from services.health_monitor import get_health_monitor_service
from services.dynamic_thresholds import get_dynamic_threshold_service, ThresholdContext, ThresholdType

router = APIRouter(prefix="/api/risk", tags=["risk-management"])


# ==================== CIRCUIT BREAKERS ====================

@router.get("/circuit-breakers/status")
def get_circuit_breaker_status():
    """Get current status of all circuit breakers"""
    service = get_circuit_breaker_service()
    return {
        "success": True,
        "status": service.get_status()
    }


@router.get("/circuit-breakers/configs")
def get_circuit_breaker_configs():
    """Get configuration for all circuit breakers"""
    service = get_circuit_breaker_service()
    return {
        "success": True,
        "configs": service.get_configs()
    }


class CircuitBreakerConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    threshold: Optional[float] = None
    action: Optional[str] = None
    size_reduction_pct: Optional[float] = None
    cooldown_minutes: Optional[int] = None


@router.post("/circuit-breakers/{breaker_type}/configure")
def configure_circuit_breaker(breaker_type: str, config: CircuitBreakerConfigUpdate):
    """Update configuration for a specific circuit breaker"""
    try:
        cb_type = CircuitBreakerType(breaker_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid breaker type: {breaker_type}")
    
    service = get_circuit_breaker_service()
    service.configure(cb_type, config.dict(exclude_none=True))
    
    return {
        "success": True,
        "message": f"Circuit breaker {breaker_type} configured",
        "new_config": service.get_configs().get(breaker_type)
    }


@router.post("/circuit-breakers/{breaker_type}/override")
def override_circuit_breaker(breaker_type: str, override_by: str = "manual"):
    """Override a triggered circuit breaker"""
    try:
        cb_type = CircuitBreakerType(breaker_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid breaker type: {breaker_type}")
    
    service = get_circuit_breaker_service()
    service.override_breaker(cb_type, override_by)
    
    return {
        "success": True,
        "message": f"Circuit breaker {breaker_type} overridden by {override_by}"
    }


@router.post("/circuit-breakers/{breaker_type}/reset")
def reset_circuit_breaker(breaker_type: str):
    """Reset a circuit breaker"""
    try:
        cb_type = CircuitBreakerType(breaker_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid breaker type: {breaker_type}")
    
    service = get_circuit_breaker_service()
    service.reset_breaker(cb_type)
    
    return {
        "success": True,
        "message": f"Circuit breaker {breaker_type} reset"
    }


@router.post("/circuit-breakers/reset-daily")
def reset_daily_circuit_breakers():
    """Reset all daily circuit breaker counters"""
    service = get_circuit_breaker_service()
    service.reset_daily()
    
    return {
        "success": True,
        "message": "Daily circuit breaker counters reset"
    }


@router.get("/circuit-breakers/check-permission")
async def check_trading_permission(
    symbol: str = "",
    setup_type: str = "",
    tqs_score: float = 50.0
):
    """Check if trading is currently allowed"""
    service = get_circuit_breaker_service()
    permission = await service.check_trading_permission(symbol, setup_type, tqs_score)
    
    return {
        "success": True,
        "permission": permission.to_dict()
    }


# ==================== POSITION SIZING ====================

@router.get("/position-sizing/config")
def get_position_sizing_config():
    """Get current position sizing configuration"""
    service = get_position_sizer_service()
    return {
        "success": True,
        "config": service.get_config()
    }


class PositionSizingConfigUpdate(BaseModel):
    mode: Optional[str] = None
    max_risk_per_trade_pct: Optional[float] = None
    max_risk_per_trade_dollar: Optional[float] = None
    max_position_pct: Optional[float] = None
    tqs_min_score: Optional[float] = None
    tqs_base_score: Optional[float] = None
    tqs_max_score: Optional[float] = None
    tqs_min_multiplier: Optional[float] = None
    tqs_max_multiplier: Optional[float] = None
    volatility_adjust: Optional[bool] = None
    kelly_fraction: Optional[float] = None


@router.post("/position-sizing/configure")
def configure_position_sizing(config: PositionSizingConfigUpdate):
    """Update position sizing configuration"""
    service = get_position_sizer_service()
    service.configure(config.dict(exclude_none=True))
    
    return {
        "success": True,
        "config": service.get_config()
    }


class PositionSizeRequest(BaseModel):
    entry_price: float
    stop_price: float
    account_value: float
    tqs_score: float = 50.0
    atr_percent: float = 2.0
    win_rate: float = 0.5
    avg_win_r: float = 1.5
    avg_loss_r: float = 1.0


@router.post("/position-sizing/calculate")
async def calculate_position_size(request: PositionSizeRequest):
    """Calculate optimal position size"""
    service = get_position_sizer_service()
    
    # Check circuit breaker constraint
    cb_service = get_circuit_breaker_service()
    permission = await cb_service.check_trading_permission(tqs_score=request.tqs_score)
    
    result = await service.calculate_size(
        entry_price=request.entry_price,
        stop_price=request.stop_price,
        account_value=request.account_value,
        tqs_score=request.tqs_score,
        atr_percent=request.atr_percent,
        win_rate=request.win_rate,
        avg_win_r=request.avg_win_r,
        avg_loss_r=request.avg_loss_r,
        circuit_breaker_multiplier=permission.max_size_multiplier
    )
    
    return {
        "success": True,
        "position_size": result.to_dict()
    }


@router.get("/position-sizing/table")
def get_sizing_table(
    entry_price: float = Query(gt=0),
    stop_price: float = Query(gt=0),
    account_value: float = Query(gt=0, default=100000)
):
    """Get position size table for different TQS scores"""
    service = get_position_sizer_service()
    table = service.get_sizing_table(entry_price, stop_price, account_value)
    
    return {
        "success": True,
        "table": table
    }


# ==================== HEALTH MONITORING ====================

@router.get("/health/report")
async def get_health_report():
    """Get complete system health report"""
    service = get_health_monitor_service()
    report = await service.generate_report()
    
    return {
        "success": True,
        "report": report.to_dict()
    }


@router.get("/health/quick-status")
def get_quick_health_status():
    """Get quick health status summary"""
    service = get_health_monitor_service()
    return {
        "success": True,
        "status": service.get_quick_status()
    }


@router.get("/health/component/{component}")
async def check_component_health(component: str):
    """Check health of a specific component"""
    service = get_health_monitor_service()
    health = await service.check_component(component)
    
    return {
        "success": True,
        "component": health.to_dict()
    }


# ==================== DYNAMIC THRESHOLDS ====================

@router.get("/thresholds/summary")
def get_threshold_summary():
    """Get summary of all threshold configurations"""
    service = get_dynamic_threshold_service()
    return {
        "success": True,
        "summary": service.get_threshold_summary()
    }


class ThresholdContextRequest(BaseModel):
    market_regime: str = "unknown"
    time_of_day: str = "midday"
    vix_level: float = 18.0
    setup_type: str = "unknown"
    recent_win_rate: float = 0.5
    consecutive_losses: int = 0
    trades_today: int = 0


@router.post("/thresholds/calculate")
async def calculate_thresholds(request: ThresholdContextRequest):
    """Calculate dynamic thresholds for a given context"""
    service = get_dynamic_threshold_service()
    
    context = ThresholdContext(
        market_regime=request.market_regime,
        time_of_day=request.time_of_day,
        vix_level=request.vix_level,
        setup_type=request.setup_type,
        recent_win_rate=request.recent_win_rate,
        consecutive_losses=request.consecutive_losses,
        trades_today=request.trades_today
    )
    
    thresholds = await service.calculate_thresholds(context)
    
    return {
        "success": True,
        "context": context.to_dict(),
        "thresholds": {k: v.to_dict() for k, v in thresholds.items()}
    }


class TradeCheckRequest(BaseModel):
    tqs_score: float
    win_rate: float = 0.5
    tape_score: float = 5.0
    expected_value: float = 0.2
    market_regime: str = "unknown"
    time_of_day: str = "midday"
    vix_level: float = 18.0
    setup_type: str = "unknown"
    recent_win_rate: float = 0.5
    consecutive_losses: int = 0
    trades_today: int = 0


@router.post("/thresholds/check-trade")
async def check_trade_against_thresholds(request: TradeCheckRequest):
    """Check if a trade passes all dynamic thresholds"""
    service = get_dynamic_threshold_service()
    
    context = ThresholdContext(
        market_regime=request.market_regime,
        time_of_day=request.time_of_day,
        vix_level=request.vix_level,
        setup_type=request.setup_type,
        recent_win_rate=request.recent_win_rate,
        consecutive_losses=request.consecutive_losses,
        trades_today=request.trades_today
    )
    
    result = await service.check_trade(
        tqs_score=request.tqs_score,
        win_rate=request.win_rate,
        tape_score=request.tape_score,
        expected_value=request.expected_value,
        context=context
    )
    
    return {
        "success": True,
        "result": result.to_dict()
    }


@router.post("/thresholds/{threshold_type}/set-custom")
def set_custom_threshold(threshold_type: str, value: float = Query()):
    """Set a custom override for a base threshold"""
    try:
        t_type = ThresholdType(threshold_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid threshold type: {threshold_type}")
    
    service = get_dynamic_threshold_service()
    service.set_custom_threshold(t_type, value)
    
    return {
        "success": True,
        "message": f"Custom threshold set: {threshold_type} = {value}"
    }
