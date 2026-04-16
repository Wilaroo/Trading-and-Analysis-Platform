"""
Collection Mode Endpoints for IB Router

Handles collection mode tracking and priority collection system.
These endpoints enable the IB Data Pusher to report status and 
allow the UI to control data collection priority.
"""
from fastapi import APIRouter
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IB Collection Mode"])

# ===================== COLLECTION MODE TRACKING =====================

# In-memory storage for collection mode status
_collection_mode_status = {
    "active": False,
    "started_at": None,
    "completed": 0,
    "failed": 0,
    "rate_per_hour": 0,
    "elapsed_minutes": 0,
    "last_update": None
}

# Priority collection flag - when True, script prioritizes historical data over live quotes
# This replaces the old "mode toggle" system with a simpler priority-based approach
_priority_collection = {
    "enabled": False,
    "set_by": "default",
    "set_at": None,
    "auto_disable_when_empty": True  # Automatically disable when queue is empty
}


def get_historical_data_queue_stats():
    """Get historical data queue statistics"""
    try:
        from server import db
        # db is synchronous pymongo, not async motor
        pending = db.historical_data_requests.count_documents({"status": "pending"})
        completed = db.historical_data_requests.count_documents({"status": "completed"})
        failed = db.historical_data_requests.count_documents({"status": "failed"})
        total = db.historical_data_requests.count_documents({})
        
        return {
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "total": total,
            "progress_pct": round((completed / total) * 100, 1) if total > 0 else 0
        }
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return {"pending": 0, "completed": 0, "failed": 0, "total": 0, "progress_pct": 0}


@router.post("/collection-mode/start")
def start_collection_mode(data: dict):
    """Called when collection mode starts"""
    global _collection_mode_status
    _collection_mode_status = {
        "active": True,
        "started_at": data.get("started_at"),
        "completed": 0,
        "failed": 0,
        "rate_per_hour": 0,
        "elapsed_minutes": 0,
        "last_update": datetime.now(timezone.utc).isoformat()
    }
    logger.info("Collection mode STARTED")
    return {"success": True, "message": "Collection mode started"}


@router.post("/collection-mode/progress")
def update_collection_progress(data: dict):
    """Called periodically with collection progress"""
    global _collection_mode_status
    _collection_mode_status.update({
        "active": True,
        "completed": data.get("completed", 0),
        "failed": data.get("failed", 0),
        "rate_per_hour": data.get("rate_per_hour", 0),
        "elapsed_minutes": data.get("elapsed_minutes", 0),
        "last_update": datetime.now(timezone.utc).isoformat()
    })
    return {"success": True}


@router.post("/collection-mode/stop")
def stop_collection_mode(data: dict):
    """Called when collection mode stops"""
    global _collection_mode_status
    _collection_mode_status.update({
        "active": False,
        "completed": data.get("completed", 0),
        "failed": data.get("failed", 0),
        "elapsed_minutes": data.get("elapsed_minutes", 0),
        "stopped_at": data.get("stopped_at"),
        "last_update": datetime.now(timezone.utc).isoformat()
    })
    logger.info(f"Collection mode STOPPED - Completed: {data.get('completed')}, Failed: {data.get('failed')}")
    return {"success": True, "message": "Collection mode stopped"}


@router.get("/collection-mode/status")
async def get_collection_mode_status():
    """Get current collection mode status for UI"""
    # Also get queue stats
    try:
        queue_stats = await get_historical_data_queue_stats()
    except:
        queue_stats = {"pending": 0, "completed": 0, "failed": 0, "total": 0}
    
    return {
        "collection_mode": _collection_mode_status,
        "queue": queue_stats
    }


# ===================== PRIORITY COLLECTION (SIMPLIFIED SYSTEM) =====================

@router.get("/mode")
async def get_current_mode():
    """
    Get the current operating settings for the local script.
    
    SIMPLIFIED SYSTEM:
    - Script always runs in "trading" mode (live quotes + orders work)
    - When priority_collection=True, script prioritizes historical data fetches
    - Script still pushes quotes, just less frequently during priority collection
    
    The local ib_data_pusher.py polls this endpoint to adjust its behavior.
    """
    global _priority_collection
    
    # Check if we should auto-disable priority (queue empty)
    try:
        queue_stats = await get_historical_data_queue_stats()
        pending = queue_stats.get("pending", 0)
        
        # Auto-disable priority when queue is empty
        if _priority_collection["enabled"] and _priority_collection["auto_disable_when_empty"]:
            if pending == 0:
                _priority_collection["enabled"] = False
                _priority_collection["set_by"] = "auto_completed"
                _priority_collection["set_at"] = datetime.now(timezone.utc).isoformat()
                logger.info("Priority collection auto-disabled: queue empty")
    except:
        pending = 0
    
    return {
        "mode": "trading",  # Always trading mode now
        "priority_collection": _priority_collection["enabled"],
        "pending_requests": pending,
        "set_by": _priority_collection["set_by"],
        "set_at": _priority_collection["set_at"],
        "collection_active": _collection_mode_status.get("active", False)
    }


@router.post("/mode/set")
def set_operating_mode(data: dict):
    """
    LEGACY ENDPOINT - Now redirects to priority collection.
    Kept for backwards compatibility with existing scripts.
    """
    global _priority_collection
    
    new_mode = data.get("mode", "trading")
    
    # Map old mode values to new priority system
    if new_mode == "collection":
        _priority_collection["enabled"] = True
    else:
        _priority_collection["enabled"] = False
    
    _priority_collection["set_by"] = "ui_legacy"
    _priority_collection["set_at"] = datetime.now(timezone.utc).isoformat()
    
    logger.info(f"Priority collection set to: {_priority_collection['enabled']} (via legacy mode/set)")
    
    return {
        "success": True,
        "mode": "trading",
        "priority_collection": _priority_collection["enabled"],
        "message": f"Priority collection {'enabled' if _priority_collection['enabled'] else 'disabled'}."
    }


@router.post("/priority-collection/enable")
async def enable_priority_collection():
    """
    Enable priority collection mode.
    
    When enabled:
    - Script fetches historical data more aggressively
    - Live quote push frequency is reduced (but still works)
    - Orders still execute immediately
    - Auto-disables when queue is empty
    """
    global _priority_collection
    
    _priority_collection = {
        "enabled": True,
        "set_by": "ui",
        "set_at": datetime.now(timezone.utc).isoformat(),
        "auto_disable_when_empty": True
    }
    
    logger.info("Priority collection ENABLED via UI")
    
    # Get queue stats for feedback
    try:
        queue_stats = await get_historical_data_queue_stats()
        pending = queue_stats.get("pending", 0)
    except:
        pending = 0
    
    return {
        "success": True,
        "priority_collection": True,
        "pending_requests": pending,
        "message": f"Priority collection enabled. {pending} requests in queue."
    }


@router.post("/priority-collection/disable")
def disable_priority_collection():
    """
    Disable priority collection, return to normal trading mode.
    """
    global _priority_collection
    
    _priority_collection = {
        "enabled": False,
        "set_by": "ui",
        "set_at": datetime.now(timezone.utc).isoformat(),
        "auto_disable_when_empty": True
    }
    
    logger.info("Priority collection DISABLED via UI")
    
    return {
        "success": True,
        "priority_collection": False,
        "message": "Priority collection disabled. Normal trading mode active."
    }


@router.get("/priority-collection/status")
async def get_priority_collection_status():
    """
    Get current priority collection status with queue info.
    """
    try:
        queue_stats = await get_historical_data_queue_stats()
    except:
        queue_stats = {"pending": 0, "completed": 0, "failed": 0, "total": 0}
    
    return {
        "priority_collection": _priority_collection["enabled"],
        "set_by": _priority_collection["set_by"],
        "set_at": _priority_collection["set_at"],
        "auto_disable_when_empty": _priority_collection["auto_disable_when_empty"],
        "queue": queue_stats,
        "collection_progress": _collection_mode_status
    }


@router.get("/mode/status")
async def get_mode_status():
    """
    Get full status including priority collection state.
    Used by the UI to show current state.
    """
    try:
        queue_stats = await get_historical_data_queue_stats()
    except:
        queue_stats = {"pending": 0, "completed": 0, "failed": 0, "total": 0}
    
    return {
        "mode": "trading",  # Always trading now
        "priority_collection": _priority_collection["enabled"],
        "set_by": _priority_collection["set_by"],
        "set_at": _priority_collection["set_at"],
        "actual_state": {
            "collection_active": _collection_mode_status.get("active", False),
            "last_update": _collection_mode_status.get("last_update"),
            "completed": _collection_mode_status.get("completed", 0),
            "rate_per_hour": _collection_mode_status.get("rate_per_hour", 0)
        },
        "queue": queue_stats
    }
