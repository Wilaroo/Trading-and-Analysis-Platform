"""
Scheduler API Router
Endpoints for managing scheduled tasks like pre-market briefing.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

router = APIRouter(prefix="/api/scheduler", tags=["Scheduler"])

# Service instances
_scheduler_service = None
_assistant_service = None
_newsletter_service = None


def init_scheduler_router(scheduler_service, assistant_service=None, newsletter_service=None):
    """Initialize the router with services"""
    global _scheduler_service, _assistant_service, _newsletter_service
    _scheduler_service = scheduler_service
    _assistant_service = assistant_service
    _newsletter_service = newsletter_service
    
    # Register the pre-market callback
    if scheduler_service and newsletter_service:
        async def premarket_callback():
            return await newsletter_service.generate_newsletter()
        scheduler_service.register_premarket_callback(premarket_callback)


# ===================== Pydantic Models =====================

class ScheduleConfig(BaseModel):
    hour: int = Field(default=6, ge=0, le=23, description="Hour in ET (0-23)")
    minute: int = Field(default=30, ge=0, le=59, description="Minute (0-59)")


# ===================== Endpoints =====================

@router.get("/status")
async def get_scheduler_status():
    """Get the current status of the scheduler"""
    if not _scheduler_service:
        raise HTTPException(status_code=500, detail="Scheduler service not initialized")
    
    status = _scheduler_service.get_status()
    
    return {
        "success": True,
        "scheduler": status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.post("/premarket/schedule")
async def start_premarket_schedule(config: Optional[ScheduleConfig] = None):
    """
    Start the pre-market briefing schedule.
    
    Default: Runs daily at 6:30 AM ET.
    The scheduler will automatically generate a market briefing every trading day.
    """
    if not _scheduler_service:
        raise HTTPException(status_code=500, detail="Scheduler service not initialized")
    
    hour = config.hour if config else 6
    minute = config.minute if config else 30
    
    try:
        _scheduler_service.start_premarket_schedule(hour, minute)
        
        return {
            "success": True,
            "message": f"Pre-market briefing scheduled for {hour}:{minute:02d} ET daily",
            "schedule": {
                "hour": hour,
                "minute": minute,
                "timezone": "ET (Eastern Time)"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start schedule: {str(e)}")


@router.post("/premarket/generate-now")
async def generate_premarket_now():
    """
    Manually trigger pre-market briefing generation now.
    
    Useful for testing or when you need an immediate update.
    """
    if not _scheduler_service:
        raise HTTPException(status_code=500, detail="Scheduler service not initialized")
    
    try:
        result = await _scheduler_service.generate_premarket_now()
        
        if result:
            return {
                "success": True,
                "message": "Pre-market briefing generated successfully",
                "briefing": result,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        else:
            return {
                "success": False,
                "message": "Failed to generate briefing - callback not available",
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate briefing: {str(e)}")


@router.get("/premarket/latest")
async def get_latest_premarket():
    """
    Get the latest cached pre-market briefing.
    
    Returns the most recently generated briefing without triggering a new generation.
    """
    if not _scheduler_service:
        raise HTTPException(status_code=500, detail="Scheduler service not initialized")
    
    cached = _scheduler_service.get_cached_premarket()
    last_run = _scheduler_service.get_last_run_time()
    
    if cached:
        return {
            "success": True,
            "briefing": cached,
            "generated_at": last_run.isoformat() if last_run else None,
            "is_cached": True
        }
    else:
        return {
            "success": True,
            "briefing": None,
            "message": "No cached briefing available. Generate one using /premarket/generate-now",
            "is_cached": False
        }


@router.delete("/premarket/stop")
async def stop_premarket_schedule():
    """
    Stop the pre-market briefing schedule.
    
    The scheduler will no longer automatically generate briefings.
    """
    if not _scheduler_service:
        raise HTTPException(status_code=500, detail="Scheduler service not initialized")
    
    _scheduler_service.stop()
    
    return {
        "success": True,
        "message": "Pre-market schedule stopped"
    }
