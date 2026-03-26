"""
AI Training Pipeline API Router

Endpoints to trigger bulk model training, monitor progress,
and view results. All training runs asynchronously in the background.
"""

import logging
import asyncio
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-training", tags=["AI Training"])

# Global training task reference
_training_task: Optional[asyncio.Task] = None
_last_result = None


class TrainingRequest(BaseModel):
    phases: Optional[List[str]] = None  # e.g., ["generic", "volatility", "exit"]
    bar_sizes: Optional[List[str]] = None  # e.g., ["1 day", "5 mins"]
    max_symbols: Optional[int] = None


@router.post("/start")
async def start_training(request: TrainingRequest):
    """
    Start the bulk training pipeline in the background.
    Returns immediately with a task ID.
    """
    global _training_task, _last_result

    if _training_task and not _training_task.done():
        return {
            "success": False,
            "error": "Training already in progress",
            "status": "running",
        }

    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        from services.ai_modules.training_pipeline import run_training_pipeline

        async def _run():
            global _last_result
            _last_result = await run_training_pipeline(
                db=mongo_db,
                phases=request.phases,
                bar_sizes=request.bar_sizes,
                max_symbols_override=request.max_symbols,
            )

        _training_task = asyncio.create_task(_run())

        return {
            "success": True,
            "message": "Training pipeline started",
            "phases": request.phases or ["generic", "setup", "volatility", "exit"],
            "bar_sizes": request.bar_sizes or "all",
        }

    except Exception as e:
        logger.error(f"Failed to start training: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_training_status():
    """Get current training pipeline status."""
    global _training_task, _last_result

    try:
        from server import db as mongo_db

        # Check pipeline status from DB
        status_doc = None
        if mongo_db:
            status_doc = mongo_db["training_pipeline_status"].find_one(
                {"_id": "pipeline"}, {"_id": 0}
            )

        task_status = "idle"
        if _training_task:
            if _training_task.done():
                task_status = "completed"
                if _training_task.exception():
                    task_status = "failed"
            else:
                task_status = "running"

        return {
            "success": True,
            "task_status": task_status,
            "pipeline_status": status_doc,
            "last_result": _last_result,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/stop")
async def stop_training():
    """Cancel the running training pipeline."""
    global _training_task

    if _training_task and not _training_task.done():
        _training_task.cancel()
        return {"success": True, "message": "Training cancelled"}

    return {"success": False, "message": "No training in progress"}


@router.get("/models")
async def list_trained_models():
    """List all trained models with their metrics."""
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        models = list(mongo_db["timeseries_models"].find(
            {},
            {"_id": 0, "model_data": 0}  # Exclude heavy binary data
        ).sort("promoted_at", -1))

        return {
            "success": True,
            "count": len(models),
            "models": models,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-readiness")
async def check_data_readiness():
    """
    Check how much training data is available per bar size.
    Helps decide when to start training.
    """
    try:
        from server import db as mongo_db
        if mongo_db is None:
            raise HTTPException(status_code=503, detail="Database not connected")

        pipeline = [
            {"$group": {
                "_id": "$bar_size",
                "total_bars": {"$sum": 1},
                "unique_symbols": {"$addToSet": "$symbol"},
            }},
            {"$project": {
                "_id": 0,
                "bar_size": "$_id",
                "total_bars": 1,
                "symbol_count": {"$size": "$unique_symbols"},
            }},
            {"$sort": {"total_bars": -1}},
        ]

        results = list(mongo_db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))

        total_bars = sum(r["total_bars"] for r in results)

        return {
            "success": True,
            "total_bars": total_bars,
            "by_bar_size": results,
            "recommendation": (
                "Ready for training" if total_bars > 1_000_000
                else "Collecting more data recommended"
            ),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
