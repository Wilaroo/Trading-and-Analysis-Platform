"""
Scheduler Router - API for scheduled tasks management
"""

from fastapi import APIRouter, Query
from typing import Optional
import logging

from services.trading_scheduler import get_trading_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scheduler", tags=["Scheduler"])


@router.get("/status")
def get_scheduler_status():
    """Get scheduler status and configured services"""
    scheduler = get_trading_scheduler()
    return {"success": True, **scheduler.get_status()}


@router.get("/jobs")
def get_scheduled_jobs():
    """Get list of scheduled jobs with next run times"""
    scheduler = get_trading_scheduler()
    jobs = scheduler.get_scheduled_jobs()
    return {"success": True, "jobs": jobs}


@router.post("/run/{task_type}")
async def run_task_now(task_type: str):
    """Manually trigger a scheduled task"""
    scheduler = get_trading_scheduler()
    result = await scheduler.run_task_now(task_type)
    return result


@router.get("/history")
def get_task_history(
    task_type: Optional[str] = Query(None),
    limit: int = Query(20)
):
    """Get history of scheduled task executions"""
    scheduler = get_trading_scheduler()
    history = scheduler.get_task_history(task_type, limit)
    return {"success": True, "history": history, "count": len(history)}


@router.post("/start")
def start_scheduler():
    """Start the scheduler"""
    scheduler = get_trading_scheduler()
    scheduler.start()
    return {"success": True, "message": "Scheduler started"}


@router.post("/stop")
def stop_scheduler():
    """Stop the scheduler"""
    scheduler = get_trading_scheduler()
    scheduler.stop()
    return {"success": True, "message": "Scheduler stopped"}
