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
- Agent historical context (NEW)
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import logging
import asyncio

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
_agent_data_service = None  # NEW: AgentDataService


def inject_services(
    module_config, 
    shadow_tracker, 
    debate_agents, 
    ai_risk_manager,
    institutional_flow=None,
    volume_anomaly=None,
    ai_consultation=None,
    agent_data_service=None  # NEW
):
    """Inject service dependencies"""
    global _module_config, _shadow_tracker, _debate_agents, _ai_risk_manager
    global _institutional_flow, _volume_anomaly, _ai_consultation, _agent_data_service
    _module_config = module_config
    _shadow_tracker = shadow_tracker
    _debate_agents = debate_agents
    _ai_risk_manager = ai_risk_manager
    _institutional_flow = institutional_flow
    _volume_anomaly = volume_anomaly
    _ai_consultation = ai_consultation
    _agent_data_service = agent_data_service
    
    # Connect data service to debate agents
    if _debate_agents and _agent_data_service:
        _debate_agents.set_data_service(_agent_data_service)
        logger.info("AgentDataService connected to DebateAgents")


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
    ai_forecast: Optional[Dict[str, Any]] = Field(None, description="Time-Series AI forecast (optional)")


class AIAdvisorConfigRequest(BaseModel):
    weight: float = Field(..., ge=0.0, le=1.0, description="AI advisor weight (0-1)")


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
    """
    Run a bull/bear debate on a trade opportunity.
    
    Enhanced: Now accepts optional ai_forecast parameter to include
    Time-Series AI predictions in the debate.
    """
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
            portfolio=request.portfolio,
            ai_forecast=request.ai_forecast  # Pass AI forecast to debate
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


@router.post("/debate/ai-advisor-weight")
async def set_ai_advisor_weight(request: AIAdvisorConfigRequest):
    """
    Set the AI advisor weight in the debate process.
    
    The AI advisor weight determines how much the Time-Series AI predictions
    influence the final debate outcome. 
    
    - 0.0 = AI has no influence
    - 0.15 = Default (15% influence)
    - 0.30 = High influence
    - 1.0 = Maximum (AI dominates)
    
    Start conservative and increase as model accuracy improves.
    """
    if not _debate_agents:
        raise HTTPException(status_code=503, detail="Debate agents not initialized")
    
    try:
        _debate_agents.set_ai_advisor_weight(request.weight)
        return {
            "success": True,
            "message": f"AI advisor weight set to {request.weight:.0%}",
            "new_weight": request.weight
        }
    except Exception as e:
        logger.error(f"Error setting AI advisor weight: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debate/ai-advisor-status")
async def get_ai_advisor_status():
    """
    Get the current AI advisor configuration and status.
    """
    if not _debate_agents:
        raise HTTPException(status_code=503, detail="Debate agents not initialized")
    
    return {
        "success": True,
        "ai_advisor": {
            "enabled": True,
            "current_weight": _debate_agents._ai_advisor._weight,
            "description": "Time-Series AI predictions now influence Bull/Bear debate",
            "how_it_works": {
                "supports_trade": "Adds to Bull's score when AI agrees with trade direction",
                "contradicts_trade": "Adds to Bear's score when AI disagrees with trade direction",
                "neutral": "No contribution when AI has low confidence"
            }
        }
    }


@router.get("/agent-context/{symbol}")
async def get_agent_context(
    symbol: str,
    setup_type: str = Query("", description="Setup type for context"),
    direction: str = Query("long", description="Trade direction")
):
    """
    Get historical context for a symbol that agents use in debate.
    
    Returns:
    - Symbol trading history (win rate, avg R, trade count)
    - Setup type performance
    - User's overall stats
    - Actionable insights
    
    This is the same data that Bull/Bear agents now receive during debates.
    """
    if not _agent_data_service:
        return {
            "success": False,
            "error": "AgentDataService not initialized",
            "context": None
        }
    
    try:
        context = await asyncio.to_thread(
            _agent_data_service.build_agent_context,
            symbol=symbol.upper(),
            setup_type=setup_type,
            direction=direction
        )
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "context": context
        }
    except Exception as e:
        logger.error(f"Error getting agent context for {symbol}: {e}")
        return {
            "success": False,
            "error": str(e),
            "context": None
        }


@router.get("/agent-context/status")
async def get_agent_data_service_status():
    """Get status of the AgentDataService"""
    return {
        "success": True,
        "service": "AgentDataService",
        "initialized": _agent_data_service is not None,
        "connected_to_debate": _debate_agents is not None and _debate_agents._data_service is not None,
        "description": "Provides historical context to Bull/Bear agents during debates"
    }


@router.get("/report-card")
async def get_trading_report_card(days: int = 90):
    """
    Get your personal Trading Report Card.
    
    Shows your historical performance by symbol, setup type, and conditions.
    This is the same data that AI agents use to make decisions about your trades.
    
    Args:
        days: Number of days of history to analyze (default 90)
    """
    if not _agent_data_service:
        return {
            "success": False,
            "error": "AgentDataService not initialized"
        }
    
    try:
        def _build_report_card():
            """Run all DB-heavy work in a thread to avoid blocking the event loop."""
            user_stats = _agent_data_service.get_user_trading_stats(days)
            
            symbol_performance = []
            if _agent_data_service._db is not None:
                try:
                    symbols = _agent_data_service._db["trade_outcomes"].distinct("symbol")
                    for symbol in symbols[:20]:
                        if symbol:
                            ctx = _agent_data_service.get_symbol_context(symbol, days)
                            if ctx.total_trades >= 1:
                                symbol_performance.append(ctx.to_dict())
                    symbol_performance.sort(key=lambda x: x["total_trades"], reverse=True)
                except Exception as e:
                    logger.warning(f"Error getting symbol performance: {e}")
            
            setup_performance = []
            if _agent_data_service._db is not None:
                try:
                    setup_types = _agent_data_service._db["alert_outcomes"].distinct("setup_type")
                    for setup_type in setup_types:
                        if setup_type:
                            ctx = _agent_data_service.get_setup_type_context(setup_type, days)
                            if ctx.total_alerts >= 1:
                                setup_performance.append(ctx.to_dict())
                    setup_performance.sort(key=lambda x: x["traded_count"], reverse=True)
                except Exception as e:
                    logger.warning(f"Error getting setup performance: {e}")
            
            insights = []
            if user_stats.get("total_trades", 0) >= 5:
                wr = user_stats.get("win_rate", 0)
                if wr >= 0.55:
                    insights.append(f"Strong overall performance: {wr*100:.0f}% win rate")
                elif wr >= 0.5:
                    insights.append(f"Solid win rate at {wr*100:.0f}%")
                elif wr >= 0.45:
                    insights.append(f"Win rate needs improvement: {wr*100:.0f}%")
                else:
                    insights.append(f"Focus on selectivity - current win rate is {wr*100:.0f}%")
            
            if symbol_performance:
                best_symbol = max(
                    [s for s in symbol_performance if s["total_trades"] >= 3],
                    key=lambda x: x["win_rate"],
                    default=None
                )
                if best_symbol and best_symbol["win_rate"] >= 0.5:
                    insights.append(f"Your best symbol is {best_symbol['symbol']}: {best_symbol['win_rate']*100:.0f}% win rate")
            
            if setup_performance:
                best_setup = max(
                    [s for s in setup_performance if s["traded_count"] >= 3],
                    key=lambda x: x["win_rate"],
                    default=None
                )
                if best_setup and best_setup["win_rate"] >= 0.5:
                    insights.append(f"Your best setup is {best_setup['setup_type']}: {best_setup['win_rate']*100:.0f}% win rate")
            
            avg_r = user_stats.get("avg_r_multiple", 0)
            if avg_r != 0:
                if avg_r >= 1.0:
                    insights.append(f"Excellent avg R-multiple: {avg_r:.2f}R per trade")
                elif avg_r >= 0.5:
                    insights.append(f"Good avg R-multiple: {avg_r:.2f}R per trade")
                elif avg_r > 0:
                    insights.append(f"Avg R-multiple is positive but low: {avg_r:.2f}R")
                else:
                    insights.append(f"Avg R-multiple is negative: {avg_r:.2f}R - review your stops")
            
            return {
                "success": True,
                "period_days": days,
                "overall_stats": user_stats,
                "by_symbol": symbol_performance[:10],
                "by_setup": setup_performance[:10],
                "insights": insights,
                "has_data": user_stats.get("total_trades", 0) > 0
            }

        return await asyncio.to_thread(_build_report_card)
        
    except Exception as e:
        logger.error(f"Error generating report card: {e}")
        return {
            "success": False,
            "error": str(e)
        }


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
    bars: Optional[List[Dict[str, Any]]] = Field(None, description="OHLCV bars (most recent first). If not provided, will fetch from MongoDB.")


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
    
    try:
        import asyncio
        status = await asyncio.to_thread(_timeseries_ai.get_status)

        # Deep sanitize: convert any non-string dict keys to strings
        def _sanitize_dict(d):
            if not isinstance(d, dict):
                return d
            return {str(k): _sanitize_dict(v) for k, v in d.items()}

        status = _sanitize_dict(status)
        return {"success": True, "status": status}
    except Exception as e:
        return {
            "success": True,
            "status": {
                "service": "timeseries_ai",
                "initialized": True,
                "error": str(e)
            }
        }


@router.get("/timeseries/model-history")
async def get_model_history(limit: int = 20):
    """Get archived model training history for analysis and comparison.
    Shows all trained models (including ones that weren't promoted to active).
    """
    if not _timeseries_ai:
        return {"success": False, "error": "Timeseries AI not initialized", "models": []}
    
    from services.ai_modules.timeseries_gbm import get_timeseries_model
    model = get_timeseries_model()
    if not model:
        return {"success": False, "error": "No timeseries model", "models": []}
    
    history = await asyncio.to_thread(model.get_model_history, limit)
    
    # Get current active model info
    active_version = model._version if model._model else "none"
    active_accuracy = model._metrics.accuracy if model._metrics else 0
    
    return {
        "success": True,
        "active_model": {
            "version": active_version,
            "accuracy": active_accuracy
        },
        "archived_models": history,
        "total_archived": len(history)
    }


class TrainRequest(BaseModel):
    symbols: Optional[List[str]] = Field(None, description="Symbols to train on")
    max_symbols: Optional[int] = Field(None, description="Maximum number of symbols (default: 1000)")
    bar_size: Optional[str] = Field("1 day", description="Bar size/timeframe to train on")
    max_bars_per_symbol: Optional[int] = Field(None, description="Max bars per symbol (default: 10000)")


class TrainAllRequest(BaseModel):
    max_symbols: Optional[int] = Field(None, description="Maximum symbols per timeframe (default: 1000)")
    max_bars_per_symbol: Optional[int] = Field(None, description="Max bars per symbol (default: 10000)")
    timeframes: Optional[List[str]] = Field(None, description="Specific timeframes to train (default: all)")


@router.post("/timeseries/train")
async def train_timeseries_model(request: Optional[TrainRequest] = None):
    """
    Train/update a time-series model for a specific timeframe.
    
    Enqueues a background job via the worker process.
    Returns a job_id for progress polling via GET /api/jobs/{job_id}.
    """
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed",
            "install_command": "pip install xgboost"
        }
    
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.job_queue_manager import job_queue_manager
        
        bar_size = request.bar_size if request and request.bar_size else "1 day"
        max_symbols = request.max_symbols if request and request.max_symbols else None
        max_bars_per_symbol = request.max_bars_per_symbol if request and request.max_bars_per_symbol else None
        symbols = request.symbols if request and request.symbols else None
        
        result = await job_queue_manager.create_job(
            job_type="training",
            params={
                "bar_size": bar_size,
                "max_symbols": max_symbols,
                "max_bars_per_symbol": max_bars_per_symbol,
                "symbols": symbols,
            },
            priority=8,
            metadata={"description": f"Train {bar_size} model"}
        )
        
        if result.get("success"):
            job = result["job"]
            return {
                "success": True,
                "job_id": job["job_id"],
                "message": f"Training {bar_size} model queued. Poll /api/jobs/{job['job_id']} for progress.",
                "bar_size": bar_size,
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to enqueue job")}
        
    except Exception as e:
        logger.error(f"Training error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeseries/train-all")
async def train_all_timeframe_models(request: Optional[TrainAllRequest] = None):
    """
    Train models for all timeframes sequentially via the worker.
    
    Enqueues a background job. Returns a job_id for progress polling.
    """
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed",
            "install_command": "pip install xgboost"
        }
    
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.job_queue_manager import job_queue_manager
        
        max_symbols = request.max_symbols if request and request.max_symbols else None
        max_bars_per_symbol = request.max_bars_per_symbol if request and request.max_bars_per_symbol else None
        timeframes = request.timeframes if request and request.timeframes else None
        
        result = await job_queue_manager.create_job(
            job_type="training",
            params={
                "all_timeframes": True,
                "max_symbols": max_symbols,
                "max_bars_per_symbol": max_bars_per_symbol,
                "timeframes": timeframes,
            },
            priority=7,
            metadata={"description": "Train all timeframes"}
        )
        
        if result.get("success"):
            job = result["job"]
            return {
                "success": True,
                "job_id": job["job_id"],
                "message": f"Training all timeframes queued. Poll /api/jobs/{job['job_id']} for progress.",
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to enqueue job")}
        
    except Exception as e:
        logger.error(f"Train-all error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



class FullUniverseTrainRequest(BaseModel):
    """Request for full universe training"""
    bar_size: Optional[str] = Field(default="1 day", description="Timeframe to train")
    symbol_batch_size: Optional[int] = Field(default=500, description="Symbols to process per batch (128GB Spark)")
    max_bars_per_symbol: Optional[int] = Field(default=99999, description="Max bars per symbol (99999 = use all)")


class FullUniverseAllRequest(BaseModel):
    """Request for full universe training on all timeframes"""
    symbol_batch_size: Optional[int] = Field(default=500, description="Symbols to process per batch (128GB Spark)")
    max_bars_per_symbol: Optional[int] = Field(default=99999, description="Max bars per symbol (99999 = use all)")
    timeframes: Optional[List[str]] = Field(default=None, description="Specific timeframes or all")


@router.post("/timeseries/train-full-universe")
async def train_full_universe_single(request: Optional[FullUniverseTrainRequest] = None):
    """
    Train on the FULL UNIVERSE of symbols for a single timeframe via the worker.
    
    Returns a job_id for progress polling.
    """
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed",
            "install_command": "pip install xgboost"
        }
    
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.job_queue_manager import job_queue_manager
        
        bar_size = request.bar_size if request and request.bar_size else "1 day"
        max_bars_per_symbol = request.max_bars_per_symbol if request and request.max_bars_per_symbol else 99999
        symbol_batch_size = request.symbol_batch_size if request and request.symbol_batch_size else 500
        
        result = await job_queue_manager.create_job(
            job_type="training",
            params={
                "bar_size": bar_size,
                "full_universe": True,
                "max_bars_per_symbol": max_bars_per_symbol,
                "symbol_batch_size": symbol_batch_size,
            },
            priority=6,
            metadata={"description": f"Full universe training ({bar_size})"}
        )
        
        if result.get("success"):
            job = result["job"]
            return {
                "success": True,
                "job_id": job["job_id"],
                "message": f"Full universe training queued for {bar_size}. Poll /api/jobs/{job['job_id']} for progress.",
                "settings": {
                    "bar_size": bar_size,
                    "max_bars_per_symbol": max_bars_per_symbol
                }
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to enqueue job")}
        
    except Exception as e:
        logger.error(f"Full universe training error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeseries/train-full-universe-all")
async def train_full_universe_all_timeframes(
    request: Optional[FullUniverseAllRequest] = None
):
    """
    Train FULL UNIVERSE on ALL 7 timeframes via the worker.
    
    Returns a job_id for progress polling.
    Expected runtime: 1-3 hours.
    """
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed",
            "install_command": "pip install xgboost"
        }
    
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.job_queue_manager import job_queue_manager
        
        max_bars_per_symbol = request.max_bars_per_symbol if request and request.max_bars_per_symbol else 99999
        symbol_batch_size = request.symbol_batch_size if request and request.symbol_batch_size else 500
        timeframes = request.timeframes if request and request.timeframes else None
        
        result = await job_queue_manager.create_job(
            job_type="training",
            params={
                "full_universe": True,
                "all_timeframes": True,
                "max_bars_per_symbol": max_bars_per_symbol,
                "symbol_batch_size": symbol_batch_size,
                "timeframes": timeframes,
            },
            priority=5,
            metadata={"description": "Full universe all timeframes training"}
        )
        
        if result.get("success"):
            job = result["job"]
            return {
                "success": True,
                "job_id": job["job_id"],
                "message": f"Full universe all-TF training queued. Poll /api/jobs/{job['job_id']} for progress.",
                "settings": {
                    "max_bars_per_symbol": max_bars_per_symbol,
                    "timeframes": timeframes or "ALL"
                }
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to enqueue job")}
        
    except Exception as e:
        logger.error(f"Full universe all-timeframes error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/timeseries/training-status")
async def get_timeseries_training_status():
    """Get current training status for all timeframe models"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    # Include training mode status
    training_mode_status = None
    try:
        from services.training_mode import training_mode_manager
        training_mode_status = training_mode_manager.get_status()
    except ImportError:
        pass
    
    return {
        "success": True,
        "status": _timeseries_ai.get_training_status(),
        "training_mode": training_mode_status
    }


@router.post("/timeseries/reload-models")
async def reload_models():
    """Reload all trained models from MongoDB.
    
    Call this after the worker process finishes training to pick up 
    the latest model versions without restarting the server.
    """
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    result = _timeseries_ai.reload_models_from_db()
    return {
        "success": True,
        **result
    }


@router.get("/training-mode/status")
async def get_training_mode_status():
    """Get current training mode status (paused tasks, elapsed time, etc.)"""
    try:
        from services.training_mode import training_mode_manager
        return {
            "success": True,
            **training_mode_manager.get_status()
        }
    except ImportError:
        return {
            "success": False,
            "error": "Training mode manager not available",
            "training_active": False
        }


@router.get("/timeseries/available-data")
async def get_available_timeframe_data():
    """Get info about available data for each timeframe in the database"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    return _timeseries_ai.get_available_timeframe_data()


@router.get("/timeseries/training-history")
async def get_training_history(bar_size: str = None, limit: int = 20):
    """
    Get training history for tracking model improvement over time.
    
    Args:
        bar_size: Optional filter by timeframe (e.g., "1 day", "5 mins")
        limit: Max records to return (default: 20)
    """
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    history = _timeseries_ai.get_training_history(bar_size=bar_size, limit=limit)
    
    return {
        "success": True,
        "history": history,
        "count": len(history)
    }


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


@router.post("/timeseries/verify-predictions")
async def verify_predictions():
    """Verify pending predictions against actual outcomes"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        # Get the model instance and call verify
        from services.ai_modules.timeseries_gbm import get_timeseries_model
        model = get_timeseries_model()
        result = model.verify_pending_predictions()
        
        return {
            "success": result.get("success", False),
            "result": result
        }
    except Exception as e:
        logger.error(f"Verification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeseries/prediction-accuracy")
async def get_prediction_accuracy(days: int = 30):
    """Get prediction accuracy statistics over a time period"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.ai_modules.timeseries_gbm import get_timeseries_model
        model = get_timeseries_model()
        result = model.get_prediction_accuracy(days=days)
        
        return {
            "success": result.get("success", False),
            "accuracy": result
        }
    except Exception as e:
        logger.error(f"Accuracy query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeseries/predictions")
async def get_recent_predictions(limit: int = 20, verified_only: bool = False):
    """Get recent predictions with optional filtering"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.ai_modules.timeseries_gbm import get_timeseries_model
        model = get_timeseries_model()
        
        if model._db is None:
            raise HTTPException(status_code=503, detail="Database not connected")
        
        query = {}
        if verified_only:
            query["outcome_verified"] = True
        
        predictions = list(model._db["timeseries_predictions"].find(
            query,
            {"_id": 0}
        ).sort("timestamp", -1).limit(limit))
        
        return {
            "success": True,
            "predictions": predictions,
            "count": len(predictions)
        }
    except Exception as e:
        logger.error(f"Predictions query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================
# Training Status & Automation Endpoints
# =====================

@router.get("/training-status")
async def get_training_status():
    """
    Get comprehensive training status including:
    - Last training time
    - Model version
    - Training history
    - Auto-training settings
    - ML availability status
    """
    # Check if ML is available
    from services.ai_modules import ML_AVAILABLE
    
    if not ML_AVAILABLE:
        return {
            "success": True,
            "ml_available": False,
            "model": {
                "is_trained": False,
                "version": "N/A",
                "last_trained": None,
                "accuracy": None,
                "samples_trained": 0
            },
            "auto_training": {"enabled": False, "after_collection": False, "schedule": None},
            "history": [],
            "next_scheduled": None,
            "ml_message": "ML libraries not installed. Run 'pip install xgboost' locally to enable AI training."
        }
    
    try:
        from services.ai_modules.timeseries_gbm import get_timeseries_model
        model = get_timeseries_model()
        
        if model is None:
            return {
                "success": True,
                "ml_available": True,
                "model": {
                    "is_trained": False,
                    "version": "v1.0",
                    "last_trained": None,
                    "accuracy": None,
                    "samples_trained": 0
                },
                "auto_training": {"enabled": False, "after_collection": False, "schedule": None},
                "history": [],
                "next_scheduled": None
            }
        
        # Get model status
        model_info = model.get_model_info() if hasattr(model, 'get_model_info') else {}
        
        # Get training history from database
        training_history = []
        db = model._db
        if db is not None:
            try:
                history_col = db["training_history"]
                history = list(history_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(10))
                training_history = history
            except Exception:
                pass  # Collection might not exist yet
        
        # Get auto-training settings
        auto_settings = {"enabled": False, "after_collection": False, "schedule": None}
        if db is not None:
            try:
                settings_col = db["system_settings"]
                settings = settings_col.find_one({"key": "auto_training"}, {"_id": 0})
                if settings:
                    auto_settings = settings.get("value", auto_settings)
            except Exception:
                pass  # Collection might not exist yet
        
        return {
            "success": True,
            "ml_available": True,
            "model": {
                "is_trained": model_info.get("is_trained", False),
                "version": model_info.get("version", "v1.0"),
                "last_trained": model_info.get("last_trained"),
                "accuracy": model_info.get("accuracy"),
                "samples_trained": model_info.get("samples_trained", 0)
            },
            "auto_training": auto_settings,
            "history": training_history,
            "next_scheduled": None  # Will be populated if scheduler is configured
        }
    except Exception as e:
        logger.error(f"Error getting training status: {e}")
        return {
            "success": False,
            "error": str(e),
            "model": {"is_trained": False, "version": "unknown"},
            "auto_training": {"enabled": False},
            "history": []
        }


@router.post("/training-settings")
async def update_training_settings(
    auto_train_enabled: bool = False,
    train_after_collection: bool = False,
    schedule_time: Optional[str] = None
):
    """
    Update auto-training settings.
    
    - auto_train_enabled: Enable/disable all auto-training
    - train_after_collection: Trigger training after data collection completes
    - schedule_time: Time for nightly training (e.g., "23:00")
    """
    try:
        from services.ai_modules.timeseries_gbm import get_timeseries_model
        model = get_timeseries_model()
        
        if model._db is None:
            raise HTTPException(status_code=503, detail="Database not connected")
        
        settings_col = model._db["system_settings"]
        
        settings = {
            "enabled": auto_train_enabled,
            "after_collection": train_after_collection,
            "schedule": schedule_time
        }
        
        settings_col.update_one(
            {"key": "auto_training"},
            {"$set": {"key": "auto_training", "value": settings, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )
        
        return {
            "success": True,
            "settings": settings,
            "message": "Training settings updated"
        }
    except Exception as e:
        logger.error(f"Error updating training settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


from datetime import datetime, timezone


@router.post("/timeseries/stop-training")
async def stop_training():
    """
    Stop any running training job.
    Note: Progress is NOT saved - training must complete to save the model.
    """
    try:
        if not _timeseries_ai:
            raise HTTPException(status_code=503, detail="Time-series AI not initialized")
        
        # Check if training is running
        status = _timeseries_ai.get_training_status()
        was_running = status.get("training_in_progress", False)
        
        # Set stop flag
        _timeseries_ai._stop_training = True
        
        # Exit training mode
        try:
            from services.training_mode import training_mode_manager
            training_mode_manager.exit_training_mode()
        except ImportError:
            pass
        
        return {
            "success": True,
            "message": "Training stop requested" if was_running else "No training was running",
            "was_running": was_running,
            "note": "Progress is NOT saved - only completed training saves the model"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping training: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# =====================
# Setup-Specific Model Endpoints
# =====================

class SetupTrainRequest(BaseModel):
    setup_type: str = Field(..., description="Setup type to train (e.g., MOMENTUM, BREAKOUT)")
    bar_size: Optional[str] = Field(None, description="Specific bar size profile to train (omit to train all profiles)")
    max_symbols: Optional[int] = Field(None, description="Max symbols to train on")
    max_bars_per_symbol: Optional[int] = Field(None, description="Max bars per symbol")


class SetupTrainAllRequest(BaseModel):
    max_symbols: Optional[int] = Field(None, description="Max symbols to train on")
    max_bars_per_symbol: Optional[int] = Field(None, description="Max bars per symbol")


class SetupPredictRequest(BaseModel):
    symbol: str = Field(..., description="Ticker symbol")
    setup_type: str = Field(..., description="Setup type (e.g., MOMENTUM, BREAKOUT)")
    bars: Optional[List[Dict[str, Any]]] = Field(None, description="OHLCV bars (most recent first). If not provided, fetched from DB.")


@router.get("/timeseries/setups/status")
async def get_setup_models_status():
    """
    Get the status of all setup-specific AI models.
    
    Returns each of the 10 setup types with their training status,
    accuracy, version, and training sample count.
    """
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    return {
        "success": True,
        **_timeseries_ai.get_setup_models_status()
    }


@router.post("/timeseries/setups/train")
async def train_setup_model(request: SetupTrainRequest):
    """
    Train a model specialized for a specific trading setup type.
    
    Enqueues a background job via the worker process.
    Returns a job_id for progress polling via GET /api/jobs/{job_id}.
    
    Supported setup types:
    MOMENTUM, SCALP, BREAKOUT, GAP_AND_GO, RANGE, REVERSAL,
    TREND_CONTINUATION, ORB, VWAP, MEAN_REVERSION
    """
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed",
            "install_command": "pip install xgboost"
        }
    
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    # Validate setup type
    setup_upper = request.setup_type.upper()
    if setup_upper not in _timeseries_ai.SETUP_TYPES:
        return {
            "success": False,
            "error": f"Unknown setup type: {setup_upper}. Valid: {list(_timeseries_ai.SETUP_TYPES.keys())}"
        }
    
    try:
        from services.job_queue_manager import job_queue_manager
        
        result = await job_queue_manager.create_job(
            job_type="setup_training",
            params={
                "setup_type": setup_upper,
                "bar_size": request.bar_size,  # None = train all profiles
                "max_symbols": request.max_symbols,
                "max_bars_per_symbol": request.max_bars_per_symbol,
            },
            priority=7,
            metadata={"description": f"Train {setup_upper} setup model"}
        )
        
        if result.get("success"):
            job = result["job"]
            return {
                "success": True,
                "job_id": job["job_id"],
                "message": f"Training {setup_upper} model queued. Poll /api/jobs/{job['job_id']} for progress.",
                "setup_type": setup_upper,
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to enqueue job")}
    
    except Exception as e:
        logger.error(f"Setup model training error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeseries/setups/train-all")
async def train_all_setup_models(request: Optional[SetupTrainAllRequest] = None):
    """
    Train models for ALL setup types sequentially via the worker.
    
    Enqueues a single background job that trains all 10 setup types.
    Returns a job_id for progress polling via GET /api/jobs/{job_id}.
    """
    from services.ai_modules import ML_AVAILABLE
    if not ML_AVAILABLE:
        return {
            "success": False,
            "ml_not_available": True,
            "error": "ML libraries not installed",
            "install_command": "pip install xgboost"
        }
    
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        from services.job_queue_manager import job_queue_manager
        
        max_symbols = request.max_symbols if request and request.max_symbols else None
        max_bars_per_symbol = request.max_bars_per_symbol if request and request.max_bars_per_symbol else None
        
        result = await job_queue_manager.create_job(
            job_type="setup_training",
            params={
                "setup_type": "ALL",
                "bar_size": None,  # Train all profiles for all setups
                "max_symbols": max_symbols,
                "max_bars_per_symbol": max_bars_per_symbol,
            },
            priority=6,
            metadata={"description": "Train all setup-specific models"}
        )
        
        if result.get("success"):
            job = result["job"]
            return {
                "success": True,
                "job_id": job["job_id"],
                "message": f"Training all setup models queued. Poll /api/jobs/{job['job_id']} for progress.",
                "setup_types": list(_timeseries_ai.SETUP_TYPES.keys()),
                "total_types": len(_timeseries_ai.SETUP_TYPES),
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to enqueue job")}
    
    except Exception as e:
        logger.error(f"Train all setup models error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/timeseries/setups/predict")
async def predict_for_setup(request: SetupPredictRequest):
    """
    Get a prediction using a setup-specific model.
    
    If a setup-specific model exists, it will be used.
    Otherwise, falls back to the general model.
    
    Args:
        symbol: Ticker symbol
        setup_type: Trading setup type
        bars: Optional OHLCV bars (most recent first). Fetched from DB if not provided.
    """
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    try:
        bars = request.bars
        
        # Fetch bars from DB if not provided
        if not bars:
            bars = await _timeseries_ai._get_bars_from_db_for_prediction(request.symbol.upper())
        
        if not bars or len(bars) < 20:
            return {
                "success": False,
                "error": f"Insufficient data for {request.symbol} (need 20+ bars, got {len(bars) if bars else 0})"
            }
        
        prediction = _timeseries_ai.predict_for_setup(
            symbol=request.symbol.upper(),
            bars=bars,
            setup_type=request.setup_type
        )
        
        if prediction is None:
            return {
                "success": False,
                "error": "Prediction failed - no trained models available"
            }
        
        return {
            "success": True,
            "prediction": prediction,
            "symbol": request.symbol.upper(),
            "setup_type": request.setup_type.upper(),
        }
        
    except Exception as e:
        logger.error(f"Setup prediction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ===== ADV (Average Daily Volume) Cache Endpoints =====

@router.get("/adv/stats")
async def get_adv_stats():
    """
    Get ADV cache statistics and threshold breakdown.
    Shows how many symbols qualify at each training tier.
    """
    from services.ai_modules.setup_training_config import ADV_THRESHOLDS
    
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        db = _timeseries_ai._db
        total = db.symbol_adv_cache.count_documents({})
        
        # Source breakdown
        sources = list(db.symbol_adv_cache.aggregate([
            {"$group": {"_id": "$source", "count": {"$sum": 1}}}
        ]))
        
        # Sample of most recent update
        sample = db.symbol_adv_cache.find_one(
            {}, {"_id": 0, "updated_at": 1, "source": 1}
        )
        
        return {
            "success": True,
            "total_symbols": total,
            "thresholds": {
                "50k_position": db.symbol_adv_cache.count_documents({"avg_volume": {"$gte": 50_000}}),
                "100k_swing": db.symbol_adv_cache.count_documents({"avg_volume": {"$gte": 100_000}}),
                "500k_intraday": db.symbol_adv_cache.count_documents({"avg_volume": {"$gte": 500_000}}),
            },
            "adv_config": ADV_THRESHOLDS,
            "sources": {s["_id"] or "unknown": s["count"] for s in sources},
            "last_updated": sample.get("updated_at") if sample else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting ADV stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/adv/recalculate")
async def recalculate_adv_cache():
    """
    Recalculate the ADV cache from actual IB historical daily bar data.
    This is a heavy operation that runs in a background thread.
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        db = _timeseries_ai._db
        
        import sys
        sys.path.insert(0, '/app/backend')
        from scripts.recalculate_adv_cache import recalculate_adv_cache as do_recalc
        
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(
            None, lambda: do_recalc(db, lookback_days=20, min_bars=10, verbose=False)
        )
        
        return {
            "success": True,
            "message": "ADV cache recalculated from IB daily bars",
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Error recalculating ADV cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ===== Model Validation History Endpoint =====

@router.get("/validation/history")
async def get_validation_history(
    setup_type: str = None,
    limit: int = 50,
):
    """
    Get model validation history showing 5-phase results per profile.
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        db = _timeseries_ai._db
        query = {}
        if setup_type:
            query["setup_type"] = setup_type.upper()
        
        records = list(db["model_validations"].find(
            query, {"_id": 0}
        ).sort("validated_at", -1).limit(limit))
        
        # Summary stats
        total = len(records)
        promoted = sum(1 for r in records if r.get("status") == "promoted")
        rejected = sum(1 for r in records if r.get("status") == "rejected")
        
        return {
            "success": True,
            "total": total,
            "promoted": promoted,
            "rejected": rejected,
            "records": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting validation history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validation/baselines")
async def get_model_baselines():
    """
    Get current baseline metrics for all models.
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        db = _timeseries_ai._db
        baselines = list(db["model_baselines"].find({}, {"_id": 0}).sort("setup_type", 1))
        
        return {
            "success": True,
            "total": len(baselines),
            "baselines": baselines,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting model baselines: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validation/latest")
async def get_latest_validations():
    """
    Get the most recent validation for each (setup_type, bar_size) combo.
    Used by the frontend to display per-card validation status.
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        db = _timeseries_ai._db
        
        # Aggregate: group by (setup_type, bar_size), take the latest
        pipeline = [
            {"$sort": {"validated_at": -1}},
            {"$group": {
                "_id": {"setup_type": "$setup_type", "bar_size": "$bar_size"},
                "latest": {"$first": "$$ROOT"},
            }},
            {"$replaceRoot": {"newRoot": "$latest"}},
            {"$project": {"_id": 0}},
        ]
        records = list(db["model_validations"].aggregate(pipeline))
        
        # Index by "SETUP_TYPE/bar_size" for easy frontend lookup
        indexed = {}
        for r in records:
            key = f"{r.get('setup_type', '')}/{r.get('bar_size', '')}"
            indexed[key] = r
        
        return {
            "success": True,
            "total": len(records),
            "validations": indexed,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting latest validations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validation/batch-history")
async def get_batch_validation_history(limit: int = 10):
    """
    Get batch validation results (Phases 4-5: Multi-Strategy + Market-Wide).
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")
        
        db = _timeseries_ai._db
        records = list(db["batch_validations"].find(
            {}, {"_id": 0}
        ).sort("validated_at", -1).limit(limit))
        
        return {
            "success": True,
            "total": len(records),
            "records": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting batch validation history: {e}")
        raise HTTPException(status_code=500, detail=str(e))
