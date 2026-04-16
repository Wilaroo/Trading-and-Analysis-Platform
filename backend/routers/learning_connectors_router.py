"""
Learning Connectors Router - API endpoints for learning system visibility and control
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import logging

from services.learning_connectors_service import get_learning_connectors, init_learning_connectors

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/learning-connectors", tags=["learning-connectors"])


def init_learning_connectors_router(
    db=None,
    timeseries_ai=None,
    shadow_tracker=None,
    learning_loop=None,
    scanner=None,
    simulation_engine=None,
    dynamic_thresholds=None
):
    """Initialize the learning connectors service with dependencies"""
    init_learning_connectors(
        db=db,
        timeseries_ai=timeseries_ai,
        shadow_tracker=shadow_tracker,
        learning_loop=learning_loop,
        scanner=scanner,
        simulation_engine=simulation_engine,
        dynamic_thresholds=dynamic_thresholds
    )


@router.get("/connections")
def get_connection_status():
    """Get status of all learning connections"""
    try:
        service = get_learning_connectors()
        status = service.get_connection_status()
        
        return {
            "success": True,
            **status
        }
    except Exception as e:
        logger.error(f"Error getting connection status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def get_status():
    """Get overall learning connectors status (alias for /connections)"""
    try:
        service = get_learning_connectors()
        status = service.get_connection_status()
        
        return {
            "success": True,
            **status
        }
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
def get_learning_metrics():
    """Get overall learning system metrics"""
    try:
        service = get_learning_connectors()
        metrics = service.get_learning_metrics()
        
        return {
            "success": True,
            "metrics": metrics.to_dict()
        }
    except Exception as e:
        logger.error(f"Error getting learning metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weights")
def get_module_weights():
    """Get current AI module weights"""
    try:
        service = get_learning_connectors()
        weights = service.get_module_weights()
        
        return {
            "success": True,
            "weights": weights
        }
    except Exception as e:
        logger.error(f"Error getting module weights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calibration-history")
def get_calibration_history(
    calibration_type: Optional[str] = None,
    limit: int = 20
):
    """Get calibration history"""
    try:
        service = get_learning_connectors()
        history = service.get_calibration_history(calibration_type, limit)
        
        return {
            "success": True,
            "history": history,
            "count": len(history)
        }
    except Exception as e:
        logger.error(f"Error getting calibration history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/all")
async def run_full_sync():
    """Run full learning sync across all connections"""
    try:
        service = get_learning_connectors()
        result = await service.run_full_sync()
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"Error running full sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/simulation-to-model")
async def sync_simulation_to_model(job_id: Optional[str] = None):
    """Sync simulation data to time-series model"""
    try:
        service = get_learning_connectors()
        result = await service.sync_simulation_to_model(job_id)
        
        return {
            "success": result.get("success", False),
            **result
        }
    except Exception as e:
        logger.error(f"Error syncing simulation to model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/shadow-to-weights")
async def sync_shadow_to_weights():
    """Calibrate module weights based on shadow tracker accuracy"""
    try:
        service = get_learning_connectors()
        result = await service.sync_shadow_to_weights()
        
        return {
            "success": result.get("success", False),
            **result
        }
    except Exception as e:
        logger.error(f"Error syncing shadow to weights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/outcomes-to-scanner")
async def sync_outcomes_to_scanner():
    """Calibrate scanner thresholds based on alert outcomes"""
    try:
        service = get_learning_connectors()
        result = await service.sync_outcomes_to_scanner()
        
        return {
            "success": result.get("success", False),
            **result
        }
    except Exception as e:
        logger.error(f"Error syncing outcomes to scanner: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/verify-predictions")
async def sync_verify_predictions():
    """Verify pending time-series predictions"""
    try:
        service = get_learning_connectors()
        result = await service.sync_predictions_verification()
        
        return {
            "success": result.get("success", False),
            **result
        }
    except Exception as e:
        logger.error(f"Error verifying predictions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync/run-all-calibrations")
async def run_all_calibrations():
    """
    Run all calibration syncs at once:
    - Shadow tracker → Module weights
    - Alert outcomes → Scanner thresholds
    - Predictions → Verification
    
    This is meant to be called after market close or on weekends.
    """
    try:
        service = get_learning_connectors()
        results = {}
        
        # 1. Shadow to weights
        try:
            results["shadow_to_weights"] = await service.sync_shadow_to_weights()
        except Exception as e:
            results["shadow_to_weights"] = {"success": False, "error": str(e)}
            
        # 2. Outcomes to scanner (auto-applies thresholds)
        try:
            results["outcomes_to_scanner"] = await service.sync_outcomes_to_scanner()
        except Exception as e:
            results["outcomes_to_scanner"] = {"success": False, "error": str(e)}
            
        # 3. Predictions verification
        try:
            results["predictions_verification"] = await service.sync_predictions_verification()
        except Exception as e:
            results["predictions_verification"] = {"success": False, "error": str(e)}
            
        # Summary
        all_success = all(r.get("success", False) for r in results.values())
        applied_calibrations = results.get("outcomes_to_scanner", {}).get("applied_count", 0)
        
        return {
            "success": all_success,
            "results": results,
            "applied_calibrations": applied_calibrations,
            "message": f"Calibrations complete. {applied_calibrations} threshold(s) applied."
        }
    except Exception as e:
        logger.error(f"Error running all calibrations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/thresholds")
async def get_applied_thresholds():
    """Get all currently applied setup thresholds"""
    try:
        service = get_learning_connectors()
        
        def _fetch_thresholds():
            thresholds = {}
            if service._connectors_col is not None:
                docs = list(service._connectors_col.find({"name": {"$regex": "^threshold_"}}))
                for doc in docs:
                    setup_type = doc["name"].replace("threshold_", "")
                    thresholds[setup_type] = {
                        "value": doc.get("value", 1.0),
                        "win_rate_30d": doc.get("win_rate_30d", 0),
                        "total_alerts": doc.get("total_alerts", 0),
                        "avg_r_multiple": doc.get("avg_r_multiple", 0),
                        "updated_at": doc.get("updated_at", "")
                    }
            return thresholds

        import asyncio
        thresholds = await asyncio.to_thread(_fetch_thresholds)
                
        return {
            "success": True,
            "thresholds": thresholds,
            "description": "Values > 1.0 mean 'be more selective', < 1.0 mean 'can be less selective'"
        }
    except Exception as e:
        logger.error(f"Error getting thresholds: {e}")
        raise HTTPException(status_code=500, detail=str(e))

