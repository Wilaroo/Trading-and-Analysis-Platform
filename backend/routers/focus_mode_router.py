"""
Focus Mode Router - API endpoints for focus mode and job queue management

Endpoints:
- GET/POST /api/focus-mode - Get/set current focus mode
- POST /api/jobs - Create a new job
- GET /api/jobs - List jobs
- GET /api/jobs/{job_id} - Get job status
- DELETE /api/jobs/{job_id} - Cancel a job
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging

from services.focus_mode_manager import focus_mode_manager, FocusMode
from services.job_queue_manager import job_queue_manager, JobType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Focus Mode & Jobs"])


# === Request/Response Models ===

class SetFocusModeRequest(BaseModel):
    mode: str = Field(..., description="Focus mode: live, collecting, training, backtesting")
    context: Optional[Dict[str, Any]] = Field(None, description="Optional context (e.g., timeframe)")
    job_id: Optional[str] = Field(None, description="Optional job ID to associate")


class CreateJobRequest(BaseModel):
    job_type: str = Field(..., description="Job type: training, data_collection, backtest, calibration")
    params: Dict[str, Any] = Field(default_factory=dict, description="Job-specific parameters")
    priority: int = Field(5, ge=1, le=10, description="Job priority (1-10)")
    auto_start: bool = Field(True, description="Automatically set focus mode for this job")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")


# === Focus Mode Endpoints ===

@router.get("/focus-mode")
async def get_focus_mode():
    """Get current focus mode status."""
    return {
        "success": True,
        **focus_mode_manager.get_status()
    }


@router.post("/focus-mode")
async def set_focus_mode(request: SetFocusModeRequest):
    """Set the system focus mode."""
    result = focus_mode_manager.set_mode(
        mode=request.mode,
        context=request.context,
        job_id=request.job_id
    )
    return result


@router.post("/focus-mode/reset")
async def reset_focus_mode():
    """Reset to live mode."""
    return focus_mode_manager.reset_to_live()


@router.get("/focus-mode/task-priority/{task_name}")
async def get_task_priority(task_name: str):
    """Get priority for a specific task in current mode."""
    priority = focus_mode_manager.get_task_priority(task_name)
    should_run = focus_mode_manager.should_run_task(task_name)
    multiplier = focus_mode_manager.get_interval_multiplier(task_name)
    
    return {
        "task_name": task_name,
        "current_mode": focus_mode_manager.get_mode(),
        "priority": priority,
        "should_run": should_run,
        "interval_multiplier": multiplier
    }


# === Job Queue Endpoints ===

@router.post("/jobs")
async def create_job(request: CreateJobRequest):
    """
    Create a new background job.
    
    Job types:
    - training: AI model training
    - data_collection: Historical data collection
    - backtest: Run a backtest simulation
    - calibration: Calibrate trading parameters
    """
    # Validate job type
    try:
        JobType(request.job_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job_type: {request.job_type}. Valid types: {[j.value for j in JobType]}"
        )
    
    # Create the job
    result = await job_queue_manager.create_job(
        job_type=request.job_type,
        params=request.params,
        priority=request.priority,
        metadata=request.metadata
    )
    
    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error', 'Failed to create job'))
    
    job = result['job']
    
    # Auto-start: Set appropriate focus mode
    if request.auto_start:
        mode_map = {
            'training': 'training',
            'data_collection': 'collecting',
            'backtest': 'backtesting',
            'calibration': 'training'  # Calibration uses training mode
        }
        mode = mode_map.get(request.job_type, 'live')
        
        if mode != 'live':
            focus_mode_manager.set_mode(
                mode=mode,
                context=request.params,
                job_id=job['job_id']
            )
            job['focus_mode_set'] = mode
    
    return {
        "success": True,
        "job": job
    }


@router.get("/jobs")
async def list_jobs(
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20
):
    """List recent jobs with optional filtering."""
    jobs = await job_queue_manager.get_recent_jobs(
        job_type=job_type,
        status=status,
        limit=limit
    )
    
    stats = await job_queue_manager.get_queue_stats()
    
    return {
        "success": True,
        "jobs": jobs,
        "stats": stats
    }


@router.get("/jobs/running")
async def get_running_jobs():
    """Get all currently running jobs."""
    jobs = await job_queue_manager.get_running_jobs()
    return {
        "success": True,
        "running_jobs": jobs,
        "count": len(jobs)
    }


@router.get("/jobs/pending")
async def get_pending_jobs(job_type: Optional[str] = None, limit: int = 10):
    """Get pending jobs waiting to be processed."""
    jobs = await job_queue_manager.get_pending_jobs(job_type=job_type, limit=limit)
    return {
        "success": True,
        "pending_jobs": jobs,
        "count": len(jobs)
    }


@router.get("/jobs/stats")
async def get_queue_stats():
    """Get job queue statistics."""
    stats = await job_queue_manager.get_queue_stats()
    return {
        "success": True,
        "stats": stats
    }


@router.post("/jobs/cleanup")
async def cleanup_old_jobs(days: int = 7):
    """Remove old completed/failed/cancelled jobs."""
    deleted = await job_queue_manager.cleanup_old_jobs(days=days)
    return {
        "success": True,
        "deleted_count": deleted,
        "message": f"Removed {deleted} jobs older than {days} days"
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get status of a specific job."""
    job = await job_queue_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    return {
        "success": True,
        "job": job
    }


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a pending or running job."""
    result = await job_queue_manager.cancel_job(job_id)
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed to cancel job'))
    
    # If this was the active job, reset focus mode
    status = focus_mode_manager.get_status()
    if status.get('job_id') == job_id:
        focus_mode_manager.reset_to_live()
        result['focus_mode_reset'] = True
    
    return result


@router.post("/jobs/{job_id}/progress")
async def update_job_progress(
    job_id: str,
    percent: Optional[int] = None,
    message: Optional[str] = None,
    current_step: Optional[int] = None,
    total_steps: Optional[int] = None
):
    """Update job progress (used by worker)."""
    success = await job_queue_manager.update_progress(
        job_id=job_id,
        percent=percent,
        message=message,
        current_step=current_step,
        total_steps=total_steps
    )
    
    # Also update focus mode progress if this is the active job
    status = focus_mode_manager.get_status()
    if status.get('job_id') == job_id:
        focus_mode_manager.update_progress(
            percent=percent,
            message=message,
            current_step=current_step,
            total_steps=total_steps
        )
    
    return {"success": success}
