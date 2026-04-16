"""
Medium Learning Router - Phase 5 APIs

Endpoints for daily analysis, calibration, and performance tracking.
"""

from fastapi import APIRouter, Query
from typing import Optional, Dict, Any, List
import logging

from services.medium_learning.calibration_service import get_calibration_service
from services.medium_learning.context_performance_service import get_context_performance_service
from services.medium_learning.confirmation_validator_service import get_confirmation_validator_service
from services.medium_learning.playbook_performance_service import get_playbook_performance_service
from services.medium_learning.edge_decay_service import get_edge_decay_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/medium-learning", tags=["Medium Learning - Phase 5"])


# ==================== CALIBRATION ENDPOINTS ====================

@router.get("/calibration/config")
async def get_calibration_config():
    """
    Get current calibration configuration.
    
    Returns TQS thresholds, setup overrides, and regime adjustments.
    """
    try:
        service = get_calibration_service()
        config = await service.get_config()
        
        return {
            "success": True,
            "config": config.to_dict()
        }
    except Exception as e:
        logger.error(f"Error getting calibration config: {e}")
        return {"success": False, "error": str(e)}


@router.post("/calibration/analyze")
async def analyze_and_recommend(
    lookback_days: int = Query(30, description="Days to look back")
):
    """
    Analyze recent trades and generate calibration recommendations.
    
    Compares actual performance against thresholds and suggests adjustments.
    """
    try:
        service = get_calibration_service()
        recommendations = await service.analyze_and_recommend(lookback_days)
        
        return {
            "success": True,
            "recommendations": [r.to_dict() for r in recommendations],
            "count": len(recommendations)
        }
    except Exception as e:
        logger.error(f"Error analyzing calibrations: {e}")
        return {"success": False, "error": str(e)}


@router.post("/calibration/apply/{recommendation_id}")
async def apply_recommendation(recommendation_id: str):
    """
    Apply a specific calibration recommendation.
    
    Updates the threshold configuration based on the recommendation.
    """
    try:
        service = get_calibration_service()
        result = await service.apply_recommendation(recommendation_id)
        
        return result
    except Exception as e:
        logger.error(f"Error applying recommendation: {e}")
        return {"success": False, "error": str(e)}


@router.get("/calibration/history")
async def get_calibration_history(
    limit: int = Query(50, description="Max records to return"),
    applied_only: bool = Query(False, description="Only show applied recommendations")
):
    """
    Get calibration recommendation history.
    """
    try:
        service = get_calibration_service()
        history = await service.get_history(limit, applied_only)
        
        return {
            "success": True,
            "history": [h.to_dict() for h in history],
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting calibration history: {e}")
        return {"success": False, "error": str(e)}


# ==================== CONTEXT PERFORMANCE ENDPOINTS ====================

@router.post("/context-performance/update")
async def update_context_performance():
    """
    Update context performance statistics from recent trades.
    """
    try:
        service = get_context_performance_service()
        
        # Get recent trades from DB
        if service._trade_outcomes_col is not None:
            trades = list(service._trade_outcomes_col.find({}).sort("created_at", -1).limit(500))
        else:
            trades = []
            
        updated = await service.update_context_performance(trades)
        
        return {
            "success": True,
            "contexts_updated": updated
        }
    except Exception as e:
        logger.error(f"Error updating context performance: {e}")
        return {"success": False, "error": str(e)}


@router.get("/context-performance/report")
async def generate_performance_report(
    report_type: str = Query("weekly", description="Report type: daily, weekly, monthly"),
    lookback_days: Optional[int] = Query(None, description="Override lookback period")
):
    """
    Generate comprehensive performance report by context.
    
    Includes heat maps, best/worst contexts, and recommendations.
    """
    try:
        service = get_context_performance_service()
        report = await service.generate_performance_report(report_type, lookback_days)
        
        return {
            "success": True,
            "report": report.to_dict()
        }
    except Exception as e:
        logger.error(f"Error generating performance report: {e}")
        return {"success": False, "error": str(e)}


@router.get("/context-performance/lookup")
async def lookup_context_performance(
    setup_type: Optional[str] = Query(None),
    market_regime: Optional[str] = Query(None),
    time_of_day: Optional[str] = Query(None)
):
    """
    Look up performance for a specific context combination.
    """
    try:
        service = get_context_performance_service()
        perf = await service.get_performance(setup_type, market_regime, time_of_day)
        
        if perf:
            return {
                "success": True,
                "performance": perf.to_dict()
            }
        else:
            return {
                "success": True,
                "performance": None,
                "message": "No data for this context"
            }
    except Exception as e:
        logger.error(f"Error looking up context: {e}")
        return {"success": False, "error": str(e)}


@router.get("/context-performance/all")
async def get_all_context_performance():
    """
    Get all context performance records.
    """
    try:
        service = get_context_performance_service()
        all_perf = await service.get_all_performances()
        
        return {
            "success": True,
            "contexts": [p.to_dict() for p in all_perf],
            "count": len(all_perf)
        }
    except Exception as e:
        logger.error(f"Error getting all context performance: {e}")
        return {"success": False, "error": str(e)}


# ==================== CONFIRMATION VALIDATION ENDPOINTS ====================

@router.post("/confirmation/validate")
async def validate_confirmations(
    lookback_days: int = Query(30, description="Days to look back")
):
    """
    Validate effectiveness of all confirmation signals.
    
    Compares trades with vs without each confirmation type.
    """
    try:
        service = get_confirmation_validator_service()
        report = await service.validate_confirmations(lookback_days)
        
        return {
            "success": True,
            "report": report.to_dict()
        }
    except Exception as e:
        logger.error(f"Error validating confirmations: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confirmation/stats/{confirmation_type}")
async def get_confirmation_stats(confirmation_type: str):
    """
    Get stats for a specific confirmation type.
    """
    try:
        service = get_confirmation_validator_service()
        stats = await service.get_confirmation_stats(confirmation_type)
        
        if stats:
            return {
                "success": True,
                "stats": stats.to_dict()
            }
        else:
            return {
                "success": True,
                "stats": None,
                "message": "No stats for this confirmation type"
            }
    except Exception as e:
        logger.error(f"Error getting confirmation stats: {e}")
        return {"success": False, "error": str(e)}


@router.get("/confirmation/all")
async def get_all_confirmation_stats():
    """
    Get stats for all confirmation types.
    """
    try:
        service = get_confirmation_validator_service()
        all_stats = await service.get_all_stats()
        
        return {
            "success": True,
            "stats": [s.to_dict() for s in all_stats],
            "confirmation_types": service.CONFIRMATION_TYPES
        }
    except Exception as e:
        logger.error(f"Error getting all confirmation stats: {e}")
        return {"success": False, "error": str(e)}


# ==================== PLAYBOOK PERFORMANCE ENDPOINTS ====================

@router.post("/playbook/update")
async def update_playbook_performance(
    lookback_days: int = Query(90, description="Days to look back")
):
    """
    Update performance stats for all playbooks based on trades.
    """
    try:
        service = get_playbook_performance_service()
        result = await service.update_playbook_performance(lookback_days=lookback_days)
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"Error updating playbook performance: {e}")
        return {"success": False, "error": str(e)}


@router.get("/playbook/report")
async def generate_playbook_report(
    lookback_days: int = Query(90, description="Days to look back")
):
    """
    Generate playbook-performance linkage report.
    
    Shows how well theoretical playbooks translate to real results.
    """
    try:
        service = get_playbook_performance_service()
        report = await service.generate_linkage_report(lookback_days)
        
        return {
            "success": True,
            "report": report.to_dict()
        }
    except Exception as e:
        logger.error(f"Error generating playbook report: {e}")
        return {"success": False, "error": str(e)}


@router.get("/playbook/{setup_type}")
async def get_playbook_performance(setup_type: str):
    """
    Get performance for a specific playbook/strategy.
    """
    try:
        service = get_playbook_performance_service()
        perf = await service.get_performance(setup_type)
        
        if perf:
            return {
                "success": True,
                "performance": perf.to_dict()
            }
        else:
            return {
                "success": True,
                "performance": None,
                "message": "No performance data for this playbook"
            }
    except Exception as e:
        logger.error(f"Error getting playbook performance: {e}")
        return {"success": False, "error": str(e)}


@router.get("/playbook")
async def get_all_playbook_performance():
    """
    Get performance for all playbooks.
    """
    try:
        service = get_playbook_performance_service()
        all_perf = await service.get_all_performance()
        
        return {
            "success": True,
            "playbooks": [p.to_dict() for p in all_perf],
            "count": len(all_perf)
        }
    except Exception as e:
        logger.error(f"Error getting all playbook performance: {e}")
        return {"success": False, "error": str(e)}


# ==================== EDGE DECAY ENDPOINTS ====================

@router.post("/edge-decay/analyze")
async def analyze_edge_decay():
    """
    Analyze all trading edges for signs of decay.
    
    Compares recent performance against historical baselines.
    """
    try:
        service = get_edge_decay_service()
        report = await service.analyze_all_edges()
        
        return {
            "success": True,
            "report": report.to_dict()
        }
    except Exception as e:
        logger.error(f"Error analyzing edge decay: {e}")
        return {"success": False, "error": str(e)}


@router.get("/edge-decay/{edge_name}")
async def get_edge_metrics(edge_name: str):
    """
    Get decay metrics for a specific edge/strategy.
    """
    try:
        service = get_edge_decay_service()
        metrics = await service.get_edge_metrics(edge_name)
        
        if metrics:
            return {
                "success": True,
                "metrics": metrics.to_dict()
            }
        else:
            return {
                "success": True,
                "metrics": None,
                "message": "No metrics for this edge"
            }
    except Exception as e:
        logger.error(f"Error getting edge metrics: {e}")
        return {"success": False, "error": str(e)}


@router.get("/edge-decay/decaying/list")
async def get_decaying_edges():
    """
    Get all edges currently showing decay.
    """
    try:
        service = get_edge_decay_service()
        decaying = await service.get_decaying_edges()
        
        return {
            "success": True,
            "decaying_edges": [e.to_dict() for e in decaying],
            "count": len(decaying)
        }
    except Exception as e:
        logger.error(f"Error getting decaying edges: {e}")
        return {"success": False, "error": str(e)}


@router.get("/edge-decay")
async def get_all_edge_metrics():
    """
    Get metrics for all tracked edges.
    """
    try:
        service = get_edge_decay_service()
        all_metrics = await service.get_all_metrics()
        
        return {
            "success": True,
            "edges": [m.to_dict() for m in all_metrics],
            "count": len(all_metrics)
        }
    except Exception as e:
        logger.error(f"Error getting all edge metrics: {e}")
        return {"success": False, "error": str(e)}


# ==================== COMBINED ENDPOINTS ====================

@router.post("/daily-analysis")
async def run_daily_analysis():
    """
    Run complete end-of-day analysis.
    
    This triggers:
    1. Calibration analysis
    2. Context performance update
    3. Confirmation validation
    4. Playbook performance update
    5. Edge decay analysis
    
    Should be called at market close (4:00 PM ET).
    """
    results = {
        "success": True,
        "timestamp": "",
        "calibration": {},
        "context_performance": {},
        "confirmations": {},
        "playbooks": {},
        "edge_decay": {}
    }
    
    from datetime import datetime, timezone
    results["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    try:
        # 1. Calibration
        cal_service = get_calibration_service()
        recommendations = await cal_service.analyze_and_recommend(30)
        results["calibration"] = {
            "recommendations_count": len(recommendations),
            "recommendations": [r.to_dict() for r in recommendations[:5]]  # Top 5
        }
        
        # 2. Context Performance
        ctx_service = get_context_performance_service()
        if ctx_service._trade_outcomes_col is not None:
            trades = list(ctx_service._trade_outcomes_col.find({}).sort("created_at", -1).limit(500))
        else:
            trades = []
        updated = await ctx_service.update_context_performance(trades)
        results["context_performance"] = {"contexts_updated": updated}
        
        # 3. Confirmations
        conf_service = get_confirmation_validator_service()
        conf_report = await conf_service.validate_confirmations(30)
        results["confirmations"] = {
            "trades_analyzed": conf_report.total_trades_analyzed,
            "most_effective": conf_report.most_effective,
            "least_effective": conf_report.least_effective
        }
        
        # 4. Playbooks
        pb_service = get_playbook_performance_service()
        pb_result = await pb_service.update_playbook_performance(lookback_days=90)
        results["playbooks"] = pb_result
        
        # 5. Edge Decay
        edge_service = get_edge_decay_service()
        edge_report = await edge_service.analyze_all_edges()
        results["edge_decay"] = {
            "total_edges": edge_report.total_edges_tracked,
            "decaying": edge_report.edges_decaying,
            "critical_alerts": edge_report.critical_alerts,
            "warnings": edge_report.warnings
        }
        
    except Exception as e:
        logger.error(f"Error in daily analysis: {e}")
        results["success"] = False
        results["error"] = str(e)
        
    return results


@router.get("/status")
def get_medium_learning_status():
    """
    Get status of all Medium Learning services.
    """
    try:
        return {
            "success": True,
            "services": {
                "calibration": get_calibration_service().get_stats(),
                "context_performance": get_context_performance_service().get_stats(),
                "confirmation_validator": get_confirmation_validator_service().get_service_stats(),
                "playbook_performance": get_playbook_performance_service().get_stats(),
                "edge_decay": get_edge_decay_service().get_stats()
            }
        }
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return {"success": False, "error": str(e)}
