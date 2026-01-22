"""
Notifications Router - Handles earnings notifications and alerts
"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Will be initialized from main server
notification_service = None

def init_notification_service(service):
    global notification_service
    notification_service = service


class NotificationResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


@router.get("")
async def get_notifications(unread_only: bool = False, limit: int = 50):
    """Get all notifications or just unread ones"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    if unread_only:
        notifications = await notification_service.get_pending_notifications(limit)
    else:
        notifications = await notification_service.get_all_notifications(limit)
    
    return {
        "notifications": notifications,
        "count": len(notifications),
        "unread_count": len([n for n in notifications if not n.get("read")])
    }


@router.get("/check-earnings")
async def check_earnings_notifications():
    """Check for new earnings notifications on watchlist stocks"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    new_notifications = await notification_service.check_earnings_notifications()
    
    return {
        "new_notifications": new_notifications,
        "count": len(new_notifications),
        "message": f"Found {len(new_notifications)} new earnings notifications"
    }


@router.get("/earnings-summary")
async def get_earnings_summary():
    """Get summary of upcoming earnings for watchlist stocks"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    summary = await notification_service.get_watchlist_earnings_summary()
    return summary


@router.post("/{notification_key}/read")
async def mark_notification_read(notification_key: str):
    """Mark a notification as read"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    success = await notification_service.mark_notification_read(notification_key)
    
    if not success:
        raise HTTPException(404, "Notification not found")
    
    return {"success": True, "message": "Notification marked as read"}


@router.post("/mark-all-read")
async def mark_all_notifications_read():
    """Mark all notifications as read"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    count = await notification_service.mark_all_read()
    
    return {"success": True, "message": f"Marked {count} notifications as read"}


@router.delete("/{notification_key}")
async def delete_notification(notification_key: str):
    """Delete a notification"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    success = await notification_service.delete_notification(notification_key)
    
    if not success:
        raise HTTPException(404, "Notification not found")
    
    return {"success": True, "message": "Notification deleted"}


@router.delete("/cleanup/{days}")
async def cleanup_old_notifications(days: int = 30):
    """Clean up notifications older than specified days"""
    if not notification_service:
        raise HTTPException(500, "Notification service not initialized")
    
    count = await notification_service.clear_old_notifications(days)
    
    return {"success": True, "message": f"Deleted {count} old notifications"}
