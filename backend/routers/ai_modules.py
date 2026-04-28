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
import time as _time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-modules", tags=["ai-modules"])

# Simple response cache for expensive endpoints (30s TTL)
_endpoint_cache = {}
_CACHE_TTL = 30

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
    

# ==================== AGGREGATED ENDPOINTS ====================

@router.get("/insights-summary")
def get_insights_summary():
    """
    Single aggregated endpoint for AI Insights panel.
    Returns shadow decisions, performance, timeseries status, predictions in ONE call.
    Replaces 5 separate API calls on the frontend.
    """
    result = {
        "success": True,
        "shadow_decisions": [],
        "shadow_performance": None,
        "timeseries_status": None,
        "prediction_accuracy": None,
        "recent_predictions": [],
    }
    
    # Shadow decisions
    try:
        if _shadow_tracker:
            decisions = _shadow_tracker.get_decisions(limit=10)
            result["shadow_decisions"] = decisions if decisions else []
    except Exception as e:
        logging.debug(f"Shadow decisions error: {e}")
    
    # Shadow performance
    try:
        if _shadow_tracker:
            perf = _shadow_tracker.get_performance(days=7)
            result["shadow_performance"] = perf
    except Exception as e:
        logging.debug(f"Shadow performance error: {e}")
    
    # Timeseries status
    try:
        from server import db as model_db
        if model_db:
            ts_model = model_db.get("timeseries_models")
            if ts_model:
                count = model_db["timeseries_models"].count_documents({})
                result["timeseries_status"] = {"model_count": count, "status": "active" if count > 0 else "no_models"}
    except Exception as e:
        logging.debug(f"Timeseries status error: {e}")
    
    # Prediction accuracy
    try:
        from server import db as model_db
        if model_db:
            predictions_col = model_db.get("timeseries_predictions")
            if predictions_col:
                from datetime import datetime, timezone, timedelta
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                pipeline = [
                    {"$match": {"created_at": {"$gte": cutoff.isoformat()}, "verified": True}},
                    {"$group": {
                        "_id": None,
                        "total": {"$sum": 1},
                        "correct": {"$sum": {"$cond": ["$correct", 1, 0]}},
                    }}
                ]
                agg = list(model_db["timeseries_predictions"].aggregate(pipeline))
                if agg:
                    total = agg[0].get("total", 0)
                    correct = agg[0].get("correct", 0)
                    result["prediction_accuracy"] = {
                        "total": total,
                        "correct": correct,
                        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
                    }
    except Exception as e:
        logging.debug(f"Prediction accuracy error: {e}")
    
    # Recent predictions
    try:
        from server import db as model_db
        if model_db:
            preds = list(model_db["timeseries_predictions"].find(
                {}, {"_id": 0}
            ).sort("created_at", -1).limit(10))
            result["recent_predictions"] = preds
    except Exception as e:
        logging.debug(f"Recent predictions error: {e}")
    
    return result

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
def get_module_config():
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
    
    # Add shadow tracker stats if available — run in thread to avoid blocking event loop
    if _shadow_tracker:
        import asyncio
        status["shadow_stats"] = await asyncio.to_thread(_shadow_tracker.get_stats)
    
    return {
        "success": True,
        "status": status
    }


@router.post("/toggle/{module_name}")
def toggle_module(module_name: str, request: ModuleToggleRequest):
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
def set_global_shadow_mode(request: ShadowModeRequest):
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
def set_module_shadow_mode(module_name: str, request: ShadowModeRequest):
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
def update_module_settings(module_name: str, request: ModuleSettingsRequest):
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
def set_ai_advisor_weight(request: AIAdvisorConfigRequest):
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
def get_ai_advisor_status():
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
def get_agent_data_service_status():
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
    """Get your personal Trading Report Card — cached 30s."""
    cache_key = f"report_card_{days}"
    cached = _endpoint_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]
    
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

        result = await asyncio.to_thread(_build_report_card)
        _endpoint_cache[cache_key] = {"data": result, "ts": _time.time()}
        return result
        
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
async def track_pending_outcomes(
    batch_size: int = Query(50, ge=1, le=500, description="Outcomes processed per batch"),
    max_batches: int = Query(1, ge=1, le=1000, description="Max batches per call (1=legacy)"),
    drain: bool = Query(False, description="If true, override max_batches to 1000 to drain the entire backlog in one call"),
):
    """Trigger outcome tracking for pending decisions.

    Defaults preserve legacy behaviour (1 batch of 50). Pass
    `?drain=true` (or `?max_batches=N`) to bulk-process a backlog —
    yields to the event loop between batches so other endpoints stay
    responsive during the drain.
    """
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")

    effective_max_batches = 1000 if drain else max_batches
    result = await _shadow_tracker.track_pending_outcomes(
        batch_size=batch_size,
        max_batches=effective_max_batches,
    )

    return {
        "success": True,
        "updated": result.get("updated", 0),
        "checked": result.get("pending_checked", 0),
        "batches": result.get("batches", 0),
        "drain": drain,
        "batch_size": batch_size,
        "max_batches": effective_max_batches,
    }


@router.get("/shadow/stats")
def get_shadow_stats():
    """Get quick stats from shadow tracker — cached 30s"""
    cache_key = "shadow_stats"
    cached = _endpoint_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]
    
    if not _shadow_tracker:
        raise HTTPException(status_code=503, detail="Shadow tracker not initialized")
    
    result = {
        "success": True,
        "stats": _shadow_tracker.get_stats()
    }
    _endpoint_cache[cache_key] = {"data": result, "ts": _time.time()}
    return result


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
def analyze_volume(request: VolumeAnalysisRequest):
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
def get_recent_anomalies(
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
def detect_anomaly(request: VolumeDetectionRequest):
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
def get_consultation_status():
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
def get_timeseries_training_status():
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
def reload_models():
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
def get_training_mode_status():
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
def get_available_timeframe_data():
    """Get info about available data for each timeframe in the database"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    return _timeseries_ai.get_available_timeframe_data()


@router.get("/timeseries/training-history")
def get_training_history(bar_size: str = None, limit: int = 20):
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
def get_model_metrics():
    """Get model performance metrics"""
    if not _timeseries_ai:
        raise HTTPException(status_code=503, detail="Time-series AI not initialized")
    
    status = _timeseries_ai.get_status()
    
    return {
        "success": True,
        "metrics": status.get("model", {}).get("metrics")
    }


@router.post("/timeseries/verify-predictions")
def verify_predictions():
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
def get_prediction_accuracy(days: int = 30):
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
def get_recent_predictions(limit: int = 20, verified_only: bool = False):
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
def get_training_status():
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
def update_training_settings(
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
def stop_training():
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
def get_setup_models_status():
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
def get_adv_stats():
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
def get_validation_history(
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
def get_model_baselines():
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
def get_latest_validations():
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


@router.get("/validation/summary")
def get_validation_summary():
    """
    High-signal dashboard summary of model validation quality across time windows.

    Returns:
      - Decision counts for last 24h / 7d / 30d / all-time
      - Top 5 promoted models by win rate × sharpe
      - Top rejection reasons grouped by category
      - Current promotion rate (trend indicator)
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:
            raise HTTPException(status_code=503, detail="AI service not initialized")

        from datetime import datetime, timezone, timedelta
        db = _timeseries_ai._db
        col = db["model_validations"]
        now = datetime.now(timezone.utc)

        def _window(hours: int):
            cutoff = (now - timedelta(hours=hours)).isoformat()
            cursor = col.find(
                {"validated_at": {"$gte": cutoff}},
                {"_id": 0, "status": 1, "reason": 1, "validated_at": 1},
            )
            promoted = rejected = other = 0
            for r in cursor:
                s = (r.get("status") or "").lower()
                if s == "promoted":
                    promoted += 1
                elif s.startswith("reject"):
                    rejected += 1
                else:
                    other += 1
            total = promoted + rejected + other
            rate = round((promoted / total) * 100, 1) if total else 0.0
            return {"total": total, "promoted": promoted, "rejected": rejected, "other": other, "promotion_rate_pct": rate}

        windows = {
            "last_24h": _window(24),
            "last_7d": _window(24 * 7),
            "last_30d": _window(24 * 30),
            "all_time": _window(24 * 365 * 10),  # effectively "all"
        }

        # --- Top 5 promoted performers ---
        # Compute simple score = win_rate * sharpe (guarded against None/NaN)
        top_promoted = []
        for r in col.find(
            {"status": "promoted"},
            {"_id": 0, "setup_type": 1, "bar_size": 1, "validated_at": 1,
             "ai_comparison": 1, "reason": 1},
        ).sort("validated_at", -1).limit(200):
            ai = r.get("ai_comparison") or {}
            wr = ai.get("ai_filtered_win_rate") or 0
            sh = ai.get("ai_filtered_sharpe") or 0
            trades = ai.get("ai_filtered_trades") or 0
            if trades < 10 or wr <= 0 or sh <= 0:
                continue  # exclude low-signal promotions
            score = (wr / 100.0) * sh
            top_promoted.append({
                "setup_type": r.get("setup_type"),
                "bar_size": r.get("bar_size"),
                "win_rate": round(wr, 1),
                "sharpe": round(sh, 2),
                "trades": trades,
                "score": round(score, 3),
                "validated_at": r.get("validated_at"),
            })
        top_promoted.sort(key=lambda x: x["score"], reverse=True)
        top_promoted = top_promoted[:5]

        # --- Rejection reason categorization ---
        # Bucket reasons into buckets so the UI can show top failure modes.
        # Order matters: more specific buckets first. Needles are matched as
        # case-insensitive substrings against the reason text.
        BUCKETS = [
            ("monte_carlo_broken", ["monte carlo", "degenerate", "mc simulation"]),
            ("weak_walk_forward", ["walk-forward", "efficiency", "out-of-sample", "oos "]),
            ("no_ai_edge", ["ai filter adds", "ai edge", "ai improvement"]),
            ("low_sharpe", ["sharpe"]),
            ("low_win_rate", ["win rate", "win_rate"]),
            ("insufficient_trades", ["insufficient", "too few", "min trades", "statistical significance"]),
            ("regression", ["regression", "baseline"]),
            ("validator_bug", ["fail-open", "pre-fix", "legacy"]),
            ("other", []),
        ]
        reason_counts = {b[0]: 0 for b in BUCKETS}
        sample_reasons = {b[0]: None for b in BUCKETS}
        for r in col.find(
            {"status": {"$regex": "^reject", "$options": "i"}},
            {"_id": 0, "reason": 1, "rejected_reason": 1},
        ):
            reason = (r.get("reason") or r.get("rejected_reason") or "").lower()
            bucket = "other"
            for name, needles in BUCKETS:
                if name == "other":
                    continue
                if any(n in reason for n in needles):
                    bucket = name
                    break
            reason_counts[bucket] += 1
            if sample_reasons[bucket] is None:
                sample_reasons[bucket] = (r.get("reason") or r.get("rejected_reason") or "")[:140]

        rejection_summary = [
            {"bucket": name, "count": reason_counts[name], "sample": sample_reasons[name]}
            for name in reason_counts
            if reason_counts[name] > 0
        ]
        rejection_summary.sort(key=lambda x: x["count"], reverse=True)

        return {
            "success": True,
            "generated_at": now.isoformat(),
            "windows": windows,
            "top_promoted": top_promoted,
            "rejection_summary": rejection_summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting validation summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/validation/batch-history")
def get_batch_validation_history(limit: int = 10):
    """
    Get batch validation results (Phases 4-5: Multi-Strategy + Market-Wide).
    """
    try:
        if not _timeseries_ai or _timeseries_ai._db is None:            raise HTTPException(status_code=503, detail="AI service not initialized")
        
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


# ====================================================================
# Phase 5: Deep Learning Model Training Endpoints
# ====================================================================

class DLTrainRequest(BaseModel):
    """Request for deep learning model training"""
    max_symbols: Optional[int] = Field(default=500, description="Max symbols to train on")
    epochs: Optional[int] = Field(default=50, description="Training epochs")
    batch_size: Optional[int] = Field(default=256, description="Batch size")


# ====================================================================
# Phase 5c: FinBERT Sentiment Analysis Endpoints
# ====================================================================

class FinBERTCollectRequest(BaseModel):
    """Request to collect news from Finnhub."""
    symbols: List[str] = Field(default=[], description="Symbols to collect news for (empty = use universe)")
    days_back: int = Field(default=30, description="Days of history to fetch")


class FinBERTScoreRequest(BaseModel):
    """Request to score unscored articles with FinBERT."""
    batch_size: int = Field(default=64, description="Scoring batch size")
    max_articles: int = Field(default=10000, description="Max articles to score per run")


@router.post("/finbert/collect-news")
async def finbert_collect_news(request: FinBERTCollectRequest = None):
    """
    Collect financial news from Finnhub for given symbols.
    Requires FINNHUB_API_KEY in backend .env.
    """
    try:
        from services.ai_modules.finbert_sentiment import FinnhubNewsCollector

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        symbols = (request.symbols if request and request.symbols else [])
        days_back = request.days_back if request and request.days_back else 30

        # If no symbols provided, pull the top-traded universe from DB
        if not symbols:
            pipeline = [
                {"$match": {"bar_size": "1 day"}},
                {"$group": {"_id": "$symbol", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gte": 50}}},
                {"$sort": {"count": -1}},
                {"$limit": 100},
            ]
            symbols = [r["_id"] for r in model_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True)]

        if not symbols:
            return {"success": False, "error": "No symbols to collect news for"}

        collector = FinnhubNewsCollector(db=model_db)
        result = await collector.collect_news(symbols=symbols, days_back=days_back)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FinBERT news collection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finbert/score-articles")
async def finbert_score_articles(request: FinBERTScoreRequest = None):
    """Score all unscored news articles using ProsusAI/FinBERT."""
    try:
        from services.ai_modules.finbert_sentiment import FinBERTSentiment

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        batch_size = request.batch_size if request and request.batch_size else 64
        max_articles = request.max_articles if request and request.max_articles else 10000

        scorer = FinBERTSentiment(db=model_db)
        result = await scorer.score_unscored_articles(batch_size=batch_size, max_articles=max_articles)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FinBERT scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finbert/stats")
def finbert_stats():
    """Get news collection and sentiment scoring statistics."""
    try:
        from services.ai_modules.finbert_sentiment import FinnhubNewsCollector, FinBERTSentiment

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            return {"success": False, "error": "Database not available"}

        collector = FinnhubNewsCollector(db=model_db)
        collection_stats = collector.get_collection_stats()

        # Top symbols by article count
        top_symbols = list(model_db["news_sentiment"].aggregate([
            {"$group": {"_id": "$symbol", "count": {"$sum": 1}, "avg_score": {"$avg": "$score"}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]))
        top_symbols_clean = [
            {"symbol": s["_id"], "articles": s["count"], "avg_score": s.get("avg_score", 0)}
            for s in top_symbols
        ]

        return {
            "success": True,
            "collection": collection_stats,
            "top_symbols": top_symbols_clean,
        }

    except Exception as e:
        logger.error(f"FinBERT stats failed: {e}")
        return {"success": False, "error": str(e)}


@router.get("/finbert/sentiment/{symbol}")
def finbert_symbol_sentiment(symbol: str, lookback_days: int = 5):
    """Get aggregated FinBERT sentiment for a specific symbol."""
    try:
        from services.ai_modules.finbert_sentiment import FinBERTSentiment

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        scorer = FinBERTSentiment(db=model_db)
        result = scorer.get_symbol_sentiment(symbol.upper(), lookback_days=lookback_days)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FinBERT sentiment lookup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finbert/market-sentiment")
def finbert_market_sentiment(lookback_days: int = 3):
    """Get broad market sentiment across all scored articles."""
    try:
        from services.ai_modules.finbert_sentiment import FinBERTSentiment

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        scorer = FinBERTSentiment(db=model_db)
        result = scorer.get_market_sentiment(lookback_days=lookback_days)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FinBERT market sentiment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/finbert/run-pipeline")
async def finbert_run_full_pipeline(request: FinBERTCollectRequest = None):
    """
    Queue a background job to collect news + score with FinBERT.
    Uses the worker job queue so it doesn't block the API.
    """
    try:
        from services.job_queue_manager import job_queue_manager, JobType

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        symbols = (request.symbols if request and request.symbols else [])
        days_back = request.days_back if request and request.days_back else 30

        result = await job_queue_manager.create_job(
            job_type=JobType.FINBERT_ANALYSIS.value,
            params={
                "symbols": symbols,
                "days_back": days_back,
                "score_after_collect": True,
                "batch_size": 64,
                "max_articles": 10000,
            },
            priority=5,
        )

        return {
            "success": result.get("success", False),
            "job_id": result.get("job", {}).get("job_id"),
            "message": f"FinBERT pipeline queued (collect {days_back}d news then score)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FinBERT pipeline enqueue failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dl/train-vae-regime")
async def train_vae_regime(request: DLTrainRequest = None):
    """Train the VAE Regime Detection model on SPY + sector ETF data."""
    try:
        from services.ai_modules.vae_regime import VAERegimeModel

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        vae = VAERegimeModel(db=model_db)
        result = await vae.train(
            db=model_db,
            epochs=request.epochs if request and request.epochs else 100,
            batch_size=request.batch_size if request and request.batch_size else 256,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"VAE Regime training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dl/train-tft")
async def train_tft(request: DLTrainRequest = None):
    """Train the Temporal Fusion Transformer on multi-timeframe data."""
    try:
        from services.ai_modules.temporal_fusion_transformer import TFTModel

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        tft = TFTModel(db=model_db)
        result = await tft.train(
            db=model_db,
            max_symbols=request.max_symbols if request and request.max_symbols else 500,
            epochs=request.epochs if request and request.epochs else 50,
            batch_size=request.batch_size if request and request.batch_size else 512,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TFT training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dl/train-cnn-lstm")
async def train_cnn_lstm(request: DLTrainRequest = None):
    """Train the CNN-LSTM temporal chart pattern model."""
    try:
        from services.ai_modules.cnn_lstm_model import CNNLSTMModel

        model_db = _timeseries_ai._db if _timeseries_ai else None
        if model_db is None:
            raise HTTPException(status_code=503, detail="Database not available")

        model = CNNLSTMModel(db=model_db)
        result = await model.train(
            db=model_db,
            max_symbols=request.max_symbols if request and request.max_symbols else 200,
            epochs=request.epochs if request and request.epochs else 30,
            batch_size=request.batch_size if request and request.batch_size else 256,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CNN-LSTM training failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dl/train-all")
async def train_all_dl_models(request: DLTrainRequest = None):
    """Train ALL Phase 5 deep learning models sequentially."""
    model_db = _timeseries_ai._db if _timeseries_ai else None
    if model_db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    results = {}
    errors = []

    # 1. VAE Regime (fastest — uses only SPY + sector ETFs)
    try:
        from services.ai_modules.vae_regime import VAERegimeModel
        logger.info("[DL TRAIN ALL] Starting VAE Regime training...")
        vae = VAERegimeModel(db=model_db)
        results["vae_regime"] = await vae.train(db=model_db, epochs=100)
    except Exception as e:
        errors.append(f"VAE: {e}")
        results["vae_regime"] = {"success": False, "error": str(e)}

    # 2. TFT (medium — multi-timeframe data)
    try:
        from services.ai_modules.temporal_fusion_transformer import TFTModel
        logger.info("[DL TRAIN ALL] Starting TFT training...")
        tft = TFTModel(db=model_db)
        max_syms = request.max_symbols if request and request.max_symbols else 500
        results["tft"] = await tft.train(db=model_db, max_symbols=max_syms, epochs=50)
    except Exception as e:
        errors.append(f"TFT: {e}")
        results["tft"] = {"success": False, "error": str(e)}

    # 3. CNN-LSTM (longest — sequential pattern extraction)
    try:
        from services.ai_modules.cnn_lstm_model import CNNLSTMModel
        logger.info("[DL TRAIN ALL] Starting CNN-LSTM training...")
        cnn_lstm = CNNLSTMModel(db=model_db)
        max_syms = request.max_symbols if request and request.max_symbols else 200
        results["cnn_lstm"] = await cnn_lstm.train(db=model_db, max_symbols=max_syms, epochs=30)
    except Exception as e:
        errors.append(f"CNN-LSTM: {e}")
        results["cnn_lstm"] = {"success": False, "error": str(e)}

    return {
        "success": len(errors) == 0,
        "results": results,
        "errors": errors if errors else None,
        "models_trained": sum(1 for r in results.values() if r.get("success")),
        "total_models": 3,
    }


@router.get("/dl/status")
def dl_model_status():
    """Get status of all Phase 5 deep learning models + FinBERT."""
    model_db = _timeseries_ai._db if _timeseries_ai else None
    if model_db is None:
        return {"models": {}, "total_loaded": 0, "expected_models": []}

    status = {}
    try:
        docs = list(model_db["dl_models"].find({}, {"_id": 0, "model_data": 0}))
        for doc in docs:
            status[doc.get("name", "unknown")] = {
                "model_type": doc.get("model_type"),
                "version": doc.get("version"),
                "accuracy": doc.get("accuracy"),
                "training_samples": doc.get("training_samples"),
                "updated_at": doc.get("updated_at"),
            }
    except Exception as e:
        logger.error(f"Error fetching DL model status: {e}")

    # FinBERT collection stats
    finbert_stats = {}
    try:
        from services.ai_modules.finbert_sentiment import FinnhubNewsCollector
        collector = FinnhubNewsCollector(db=model_db)
        finbert_stats = collector.get_collection_stats()
    except Exception:
        pass

    return {
        "models": status,
        "total_loaded": len(status),
        "expected_models": ["vae_regime_detector", "tft_multi_timeframe", "cnn_lstm_chart"],
        "finbert": finbert_stats,
    }
