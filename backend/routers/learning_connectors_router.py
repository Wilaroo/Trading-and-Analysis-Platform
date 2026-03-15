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
    simulation_engine=None
):
    """Initialize the learning connectors service with dependencies"""
    init_learning_connectors(
        db=db,
        timeseries_ai=timeseries_ai,
        shadow_tracker=shadow_tracker,
        learning_loop=learning_loop,
        scanner=scanner,
        simulation_engine=simulation_engine
    )


@router.get("/connections")
async def get_connection_status():
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


@router.get("/metrics")
async def get_learning_metrics():
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
async def get_module_weights():
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
async def get_calibration_history(
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
