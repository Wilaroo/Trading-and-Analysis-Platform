"""
AI Modules Router - API endpoints for institutional-grade AI features

Provides endpoints for:
- Module configuration and toggles
- Shadow mode management
- Bull/Bear debate execution
- AI Risk assessment
- Performance reports
- Institutional flow analysis
- Volume anomaly detection
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-modules", tags=["ai-modules"])

# Service references (injected at startup)
_module_config = None
_shadow_tracker = None
_debate_agents = None
_ai_risk_manager = None
_institutional_flow = None
_volume_anomaly = None
_ai_consultation = None


def inject_services(
    module_config, 
    shadow_tracker, 
    debate_agents, 
    ai_risk_manager,
    institutional_flow=None,
    volume_anomaly=None,
    ai_consultation=None
):
    """Inject service dependencies"""
    global _module_config, _shadow_tracker, _debate_agents, _ai_risk_manager
    global _institutional_flow, _volume_anomaly, _ai_consultation
    _module_config = module_config
    _shadow_tracker = shadow_tracker
    _debate_agents = debate_agents
    _ai_risk_manager = ai_risk_manager
    _institutional_flow = institutional_flow
    _volume_anomaly = volume_anomaly
    _ai_consultation = ai_consultation


# =====================
# Request/Response Models
# =====================

class ModuleToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Enable or disable the module")


class ShadowModeRequest(BaseModel):
    shadow_mode: bool = Field(..., description="Enable or disable shadow mode")


class ModuleSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    shadow_mode: Optional[bool] = None
    confidence_threshold: Optional[float] = None
    custom_settings: Optional[Dict[str, Any]] = None


class DebateRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    setup: Dict[str, Any] = Field(..., description="Setup details")
    market_context: Dict[str, Any] = Field(default_factory=dict, description="Market context")
    technical_data: Dict[str, Any] = Field(default_factory=dict, description="Technical indicators")
    portfolio: Optional[Dict[str, Any]] = Field(None, description="Current portfolio state")


class RiskAssessmentRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    direction: str = Field(..., description="Trade direction (long/short)")
    entry_price: float = Field(..., description="Entry price")
    stop_price: float = Field(..., description="Stop loss price")
    target_price: float = Field(..., description="Target price")
    position_size_shares: int = Field(..., description="Number of shares")
    account_value: float = Field(..., description="Total account value")
    setup: Dict[str, Any] = Field(default_factory=dict, description="Setup details")
    market_context: Dict[str, Any] = Field(default_factory=dict, description="Market context")
    portfolio: Optional[Dict[str, Any]] = Field(None, description="Current portfolio")


# =====================
# Configuration Endpoints
# =====================

@router.get("/config")
async def get_module_config():
    """Get complete AI module configuration"""
    if not _module_config:
        raise HTTPException(status_code=503, detail="Module config not initialized")
    
    return {
        "success": True,
        "config": _module_config.get_full_config()
    }


@router.get("/status")
async def get_module_status():
    """Get quick status summary for UI"""
    if not _module_config:
        raise HTTPException(status_code=503, detail="Module config not initialized")
    
    status = _module_config.get_status_summary()
    
    # Add shadow tracker stats if available
    if _shadow_tracker:
        status["shadow_stats"] = _shadow_tracker.get_stats()
    
    return {
        "success": True,
        "status": status
    }


@router.post("/toggle/{module_name}")
async def toggle_module(module_name: str, request: ModuleToggleRequest):
    """Enable or disable a specific AI module"""
    if not _module_config:
        raise HTTPException(status_code=503, detail="Module config not initialized")
    
    result = _module_config.toggle_module(module_name, request.enabled)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return {
        "success": True,
        "module": module_name,
        "enabled": request.enabled
    }


@router.post("/shadow-mode")
async def set_global_shadow_mode(request: ShadowModeRequest):
    """Set global shadow mode (affects all modules)"""
    if not _module_config:
        raise HTTPException(status_code=503, detail="Module config not initialized")
    
    result = _module_config.set_shadow_mode(module=None, shadow_mode=request.shadow_mode)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return {
        "success": True,
        "global_shadow_mode": request.shadow_mode
    }


@router.post("/shadow-mode/{module_name}")
async def set_module_shadow_mode(module_name: str, request: ShadowModeRequest):
    """Set shadow mode for a specific module"""
    if not _module_config:
        raise HTTPException(status_code=503, detail="Module config not initialized")
    
    result = _module_config.set_shadow_mode(module=module_name, shadow_mode=request.shadow_mode)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return {
        "success": True,
        "module": module_name,
        "shadow_mode": request.shadow_mode
    }


@router.put("/settings/{module_name}")
async def update_module_settings(module_name: str, request: ModuleSettingsRequest):
    """Update settings for a specific module"""
    if not _module_config:
        raise HTTPException(status_code=503, detail="Module config not initialized")
    
    settings = request.model_dump(exclude_none=True)
    result = _module_config.update_module_settings(module_name, settings)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result


# =====================
# Debate Agent Endpoints
# =====================

@router.post("/debate/run")
async def run_debate(request: DebateRequest):
    """Run a bull/bear debate on a trade opportunity"""
    if not _debate_agents:
        raise HTTPException(status_code=503, detail="Debate agents not initialized")
    
    if not _module_config or not _module_config.is_debate_enabled():
        return {
            "success": False,
            "error": "Debate agents module is disabled",
            "enabled": False
        }
    
    try:
        result = await _debate_agents.run_debate(
            symbol=request.symbol,
            setup=request.setup,
            market_context=request.market_context,
            technical_data=request.technical_data,
            portfolio=request.portfolio
        )
        
        # Log to shadow tracker if enabled
        if _shadow_tracker and _module_config.is_shadow_mode("debate_agents"):
            await _shadow_tracker.log_decision(
                symbol=request.symbol,
                trigger_type="debate_request",
                price_at_decision=request.setup.get("entry_price", 0),
                market_regime=request.market_context.get("regime", ""),
                debate_result=result.to_dict(),
                combined_recommendation=result.final_recommendation,
                confidence_score=result.combined_confidence,
                reasoning=result.reasoning,
                was_executed=False,
                execution_reason="Manual debate request"
            )
        
        return {
            "success": True,
            "debate_result": result.to_dict(),
            "shadow_mode": _module_config.is_shadow_mode("debate_agents")
        }
        
    except Exception as e:
        logger.error(f"Debate error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================
# Risk Manager Endpoints
# =====================

@router.post("/risk/assess")
async def assess_risk(request: RiskAssessmentRequest):
    """Perform comprehensive risk assessment for a trade"""
    if not _ai_risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not initialized")
    
    if not _module_config or not _module_config.is_risk_manager_enabled():
        return {
            "success": False,
            "error": "AI Risk Manager module is disabled",
            "enabled": False
        }
    
    try:
        result = await _ai_risk_manager.assess_risk(
            symbol=request.symbol,
            direction=request.direction,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            target_price=request.target_price,
            position_size_shares=request.position_size_shares,
            account_value=request.account_value,
            setup=request.setup,
            market_context=request.market_context,
            portfolio=request.portfolio
        )
        
        # Log to shadow tracker if enabled
        if _shadow_tracker and _module_config.is_shadow_mode("ai_risk_manager"):
            await _shadow_tracker.log_decision(
                symbol=request.symbol,
                trigger_type="risk_assessment",
                price_at_decision=request.entry_price,
                market_regime=request.market_context.get("regime", ""),
                risk_assessment=result.to_dict(),
                combined_recommendation=result.recommendation,
                confidence_score=1.0 - (result.total_risk_score / 10),
                reasoning=result.reasoning,
                was_executed=False,
                execution_reason="Manual risk assessment"
            )
        
        return {
            "success": True,
            "assessment": result.to_dict(),
            "shadow_mode": _module_config.is_shadow_mode("ai_risk_manager")
        }
        
    except Exception as e:
        logger.error(f"Risk assessment error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================
# Shadow Tracker Endpoints
# =====================

@router.get("/shadow/decisions")
async def get_shadow_decisions(
    symbol: str = Query(None, description="Filter by symbol"),
    module: str = Query(None, description="Filter by module"),
    was_executed: bool = Query(None, description="Filter by execution status"),
    limit: int = Query(50, ge=1, le=200)
):
    """Get shadow-tracked decisions"""
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")
    
    decisions = await _shadow_tracker.get_decisions(
        symbol=symbol,
        module=module,
        was_executed=was_executed,
        limit=limit
    )
    
    return {
        "success": True,
        "decisions": [d.to_dict() for d in decisions],
        "count": len(decisions)
    }


@router.get("/shadow/performance")
async def get_shadow_performance(
    days: int = Query(30, ge=1, le=365)
):
    """Get performance metrics for all AI modules"""
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")
    
    performance = await _shadow_tracker.get_all_performance(days)
    
    return {
        "success": True,
        "period_days": days,
        "performance": {k: v.to_dict() for k, v in performance.items()}
    }


@router.get("/shadow/report")
async def get_learning_report(
    days: int = Query(30, ge=1, le=365)
):
    """Generate comprehensive learning report"""
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")
    
    report = await _shadow_tracker.generate_learning_report(days)
    
    return {
        "success": True,
        "report": report
    }


@router.post("/shadow/track-outcomes")
async def track_pending_outcomes():
    """Trigger outcome tracking for pending decisions"""
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")
    
    result = await _shadow_tracker.track_pending_outcomes()
    
    return {
        "success": True,
        "updated": result.get("updated", 0),
        "checked": result.get("pending_checked", 0)
    }


@router.get("/shadow/stats")
async def get_shadow_stats():
    """Get quick stats from shadow tracker"""
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")
    
    return {
        "success": True,
        "stats": _shadow_tracker.get_stats()
    }


# =====================
# Institutional Flow Endpoints
# =====================

@router.get("/institutional/ownership/{symbol}")
async def get_institutional_ownership(symbol: str):
    """Get institutional ownership data for a symbol"""
    if not _institutional_flow:
        raise HTTPException(status_code=503, detail="Institutional flow service not initialized")
    
    if not _module_config or not _module_config.is_institutional_flow_enabled():
        return {
            "success": False,
            "error": "Institutional Flow module is disabled",
            "enabled": False
        }
    
    try:
        ownership = await _institutional_flow.get_institutional_ownership(symbol)
        return {
            "success": True,
            "ownership": ownership.to_dict()
        }
    except Exception as e:
        logger.error(f"Institutional ownership error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutional/context/{symbol}")
async def get_ownership_context(symbol: str):
    """Get trading context based on institutional ownership"""
    if not _institutional_flow:
        raise HTTPException(status_code=503, detail="Institutional flow service not initialized")
    
    if not _module_config or not _module_config.is_institutional_flow_enabled():
        return {
            "success": False,
            "error": "Institutional Flow module is disabled",
            "enabled": False
        }
    
    try:
        context = await _institutional_flow.get_ownership_context(symbol)
        return {
            "success": True,
            "context": context.to_dict()
        }
    except Exception as e:
        logger.error(f"Ownership context error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutional/rebalance-risk/{symbol}")
async def check_rebalance_risk(symbol: str):
    """Check for rebalance risks affecting a symbol"""
    if not _institutional_flow:
        raise HTTPException(status_code=503, detail="Institutional flow service not initialized")
    
    try:
        risk = await _institutional_flow.check_rebalance_risk(symbol)
        return {
            "success": True,
            "risk": risk
        }
    except Exception as e:
        logger.error(f"Rebalance risk error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================
# Volume Anomaly Endpoints
# =====================

class VolumeAnalysisRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    bars: List[Dict[str, Any]] = Field(..., description="OHLCV bars (most recent first)")
    direction: str = Field("long", description="Trade direction for context")


@router.post("/volume/analyze")
async def analyze_volume(request: VolumeAnalysisRequest):
    """Analyze volume profile and detect anomalies"""
    if not _volume_anomaly:
        raise HTTPException(status_code=503, detail="Volume anomaly service not initialized")
    
    try:
        context = _volume_anomaly.get_volume_context_for_trade(
            symbol=request.symbol,
            bars=request.bars,
            direction=request.direction
        )
        return {
            "success": True,
            "analysis": context
        }
    except Exception as e:
        logger.error(f"Volume analysis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/volume/anomalies")
async def get_recent_anomalies(
    symbol: str = Query(None, description="Filter by symbol"),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200)
):
    """Get recent volume anomalies"""
    if not _volume_anomaly:
        raise HTTPException(status_code=503, detail="Volume anomaly service not initialized")
    
    try:
        anomalies = _volume_anomaly.get_recent_anomalies(
            symbol=symbol,
            hours=hours,
            limit=limit
        )
        return {
            "success": True,
            "anomalies": [a.to_dict() for a in anomalies],
            "count": len(anomalies)
        }
    except Exception as e:
        logger.error(f"Get anomalies error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class VolumeDetectionRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    current_volume: int = Field(..., description="Current bar volume")
    historical_volumes: List[int] = Field(..., description="Historical volumes")
    current_price: float = Field(..., description="Current price")
    open_price: float = Field(..., description="Open price")
    high_price: float = Field(None, description="High price (optional)")
    low_price: float = Field(None, description="Low price (optional)")


@router.post("/volume/detect")
async def detect_anomaly(request: VolumeDetectionRequest):
    """Detect volume anomaly for current bar"""
    if not _volume_anomaly:
        raise HTTPException(status_code=503, detail="Volume anomaly service not initialized")
    
    try:
        anomaly = _volume_anomaly.detect_anomaly(
            symbol=request.symbol,
            current_volume=request.current_volume,
            historical_volumes=request.historical_volumes,
            current_price=request.current_price,
            open_price=request.open_price,
            high_price=request.high_price,
            low_price=request.low_price
        )
        
        if anomaly:
            # Log to database
            _volume_anomaly.log_anomaly(anomaly)
            
            return {
                "success": True,
                "anomaly_detected": True,
                "anomaly": anomaly.to_dict()
            }
        
        return {
            "success": True,
            "anomaly_detected": False,
            "anomaly": None
        }
    except Exception as e:
        logger.error(f"Detect anomaly error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================
# Trade Consultation Endpoints
# =====================

@router.get("/consultation/status")
async def get_consultation_status():
    """Get AI Trade Consultation status"""
    if not _ai_consultation:
        return {
            "success": True,
            "status": {
                "enabled": False,
                "reason": "AI Consultation service not initialized"
            }
        }
    
    return {
        "success": True,
        "status": _ai_consultation.get_status()
    }


class ConsultationRequest(BaseModel):
    trade: Dict[str, Any] = Field(..., description="Trade object")
    market_context: Dict[str, Any] = Field(default_factory=dict, description="Market context")
    portfolio: Optional[Dict[str, Any]] = Field(None, description="Portfolio state")
    bars: Optional[List[Dict[str, Any]]] = Field(None, description="OHLCV bars for volume analysis")


@router.post("/consultation/run")
async def run_consultation(request: ConsultationRequest):
    """
    Run AI consultation on a trade (manual testing endpoint).
    
    This runs the same analysis that happens automatically when the trading bot
    evaluates a trade opportunity.
    """
    if not _ai_consultation:
        raise HTTPException(status_code=503, detail="AI Consultation not initialized")
    
    try:
        result = await _ai_consultation.consult_on_trade(
            trade=request.trade,
            market_context=request.market_context,
            portfolio=request.portfolio,
            bars=request.bars
        )
        
        return {
            "success": True,
            "consultation": result
        }
        
    except Exception as e:
        logger.error(f"Consultation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================
# Time-Series AI Endpoints
# =====================

# Service reference
_timeseries_ai = None


def inject_timeseries_service(timeseries_ai):
    """Inject timeseries AI service"""
    global _timeseries_ai
    _timeseries_ai = timeseries_ai


class TimeSeriesForecastRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    bars: List[Dict[str, Any]] = Field(..., description="OHLCV bars (most recent first)")


@router.post("/timeseries/forecast")
async def get_timeseries_forecast(request: TimeSeriesForecastRequest):
    """Get directional forecast for a symbol"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    if not _module_config or not _module_config.is_timeseries_enabled():
        return {
            "success": False,
            "error": "Time-Series AI module is disabled",
            "enabled": False
        }
    
    try:
        forecast = await _timeseries_ai.get_forecast(
            symbol=request.symbol,
            bars=request.bars
        )
        
        return {
            "success": True,
            "forecast": forecast
        }
        
    except Exception as e:
        logger.error(f"Forecast error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeseries/status")
async def get_timeseries_status():
    """Get time-series AI model status"""
    if not _timeseries_ai:
        return {
            "success": True,
            "status": {
                "service": "timeseries_ai",
                "initialized": False
            }
        }
    
    return {
        "success": True,
        "status": _timeseries_ai.get_status()
    }


class TrainRequest(BaseModel):
    symbols: Optional[List[str]] = Field(None, description="Symbols to train on")


@router.post("/timeseries/train")
async def train_timeseries_model(request: TrainRequest):
    """Train/update the time-series model"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        result = await _timeseries_ai.train_model(symbols=request.symbols)
        
        return {
            "success": result.get("success", False),
            "result": result
        }
        
    except Exception as e:
        logger.error(f"Training error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeseries/metrics")
async def get_model_metrics():
    """Get model performance metrics"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    status = _timeseries_ai.get_status()
    
    return {
        "success": True,
        "metrics": status.get("model", {}).get("metrics")
    }
