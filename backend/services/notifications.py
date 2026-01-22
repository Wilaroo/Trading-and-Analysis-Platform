"""
Notification Service - Handles earnings notifications and alerts
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from pymongo import MongoClient
import os

class NotificationService:
    """Service for managing earnings notifications and alerts"""
    
    def __init__(self, db):
        self.db = db
        self.notifications_col = db["notifications"]
        self.watchlists_col = db["watchlists"]
        self.earnings_col = db["earnings"]
    
    async def check_earnings_notifications(self) -> List[Dict]:
        """Check for upcoming earnings on watchlist stocks"""
        # Get all watchlist symbols
        watchlist_items = list(self.watchlists_col.find({}, {"_id": 0, "symbol": 1}))
        watchlist_symbols = [item["symbol"] for item in watchlist_items]
        
        if not watchlist_symbols:
            return []
        
        # Get earnings in the next 7 days
        today = datetime.now(timezone.utc).date()
        week_from_now = today + timedelta(days=7)
        
        # Find upcoming earnings for watchlist stocks
        upcoming_earnings = list(self.earnings_col.find({
            "symbol": {"$in": watchlist_symbols},
            "earnings_date": {
                "$gte": today.isoformat(),
                "$lte": week_from_now.isoformat()
            }
        }, {"_id": 0}))
        
        # Create notifications for any that haven't been notified
        notifications = []
        for earning in upcoming_earnings:
            notification_key = f"{earning['symbol']}_{earning['earnings_date']}"
            
            # Check if already notified
            existing = self.notifications_col.find_one({"key": notification_key})
            if not existing:
                notification = {
                    "key": notification_key,
                    "type": "earnings_upcoming",
                    "symbol": earning["symbol"],
                    "earnings_date": earning.get("earnings_date"),
                    "time": earning.get("time", "N/A"),
                    "eps_estimate": earning.get("eps_estimate"),
                    "message": f"{earning['symbol']} has earnings on {earning.get('earnings_date')} ({earning.get('time', 'TBD')})",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "read": False,
                    "priority": "high" if earning.get("implied_volatility", {}).get("iv_rank", 0) > 70 else "medium"
                }
                
                # Store notification
                self.notifications_col.insert_one(notification)
                notifications.append({k: v for k, v in notification.items() if k != "_id"})
        
        return notifications
    
    async def get_pending_notifications(self, limit: int = 20) -> List[Dict]:
        """Get pending (unread) notifications"""
        notifications = list(self.notifications_col.find(
            {"read": False},
            {"_id": 0}
        ).sort("created_at", -1).limit(limit))
        
        return notifications
    
    async def get_all_notifications(self, limit: int = 50) -> List[Dict]:
        """Get all notifications"""
        notifications = list(self.notifications_col.find(
            {},
            {"_id": 0}
        ).sort("created_at", -1).limit(limit))
        
        return notifications
    
    async def mark_notification_read(self, notification_key: str) -> bool:
        """Mark a notification as read"""
        result = self.notifications_col.update_one(
            {"key": notification_key},
            {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count > 0
    
    async def mark_all_read(self) -> int:
        """Mark all notifications as read"""
        result = self.notifications_col.update_many(
            {"read": False},
            {"$set": {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count
    
    async def delete_notification(self, notification_key: str) -> bool:
        """Delete a notification"""
        result = self.notifications_col.delete_one({"key": notification_key})
        return result.deleted_count > 0
    
    async def clear_old_notifications(self, days: int = 30) -> int:
        """Clear notifications older than specified days"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = self.notifications_col.delete_many({
            "created_at": {"$lt": cutoff}
        })
        return result.deleted_count
    
    async def create_price_alert_notification(
        self, 
        symbol: str, 
        price: float, 
        change_percent: float,
        alert_type: str = "price_move"
    ) -> Dict:
        """Create a price alert notification"""
        notification = {
            "key": f"price_{symbol}_{datetime.now(timezone.utc).timestamp()}",
            "type": alert_type,
            "symbol": symbol,
            "price": price,
            "change_percent": change_percent,
            "message": f"{symbol} moved {change_percent:+.2f}% to ${price:.2f}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "read": False,
            "priority": "high" if abs(change_percent) >= 5 else "medium"
        }
        
        self.notifications_col.insert_one(notification)
        return {k: v for k, v in notification.items() if k != "_id"}
    
    async def get_watchlist_earnings_summary(self) -> Dict:
        """Get a summary of upcoming earnings for watchlist stocks"""
        watchlist_items = list(self.watchlists_col.find({}, {"_id": 0, "symbol": 1}))
        watchlist_symbols = [item["symbol"] for item in watchlist_items]
        
        if not watchlist_symbols:
            return {
                "watchlist_count": 0,
                "upcoming_earnings": [],
                "earnings_this_week": 0,
                "earnings_next_week": 0,
                "high_iv_earnings": 0
            }
        
        today = datetime.now(timezone.utc).date()
        week_from_now = today + timedelta(days=7)
        two_weeks = today + timedelta(days=14)
        
        # Get all upcoming earnings for watchlist
        all_upcoming = list(self.earnings_col.find({
            "symbol": {"$in": watchlist_symbols},
            "earnings_date": {"$gte": today.isoformat()}
        }, {"_id": 0}).sort("earnings_date", 1))
        
        # Categorize
        this_week = [e for e in all_upcoming if e.get("earnings_date", "") <= week_from_now.isoformat()]
        next_week = [e for e in all_upcoming 
                    if week_from_now.isoformat() < e.get("earnings_date", "") <= two_weeks.isoformat()]
        high_iv = [e for e in all_upcoming 
                  if e.get("implied_volatility", {}).get("iv_rank", 0) > 70]
        
        return {
            "watchlist_count": len(watchlist_symbols),
            "upcoming_earnings": all_upcoming[:10],  # Top 10 upcoming
            "earnings_this_week": len(this_week),
            "earnings_next_week": len(next_week),
            "high_iv_earnings": len(high_iv),
            "symbols_this_week": [e["symbol"] for e in this_week],
            "symbols_next_week": [e["symbol"] for e in next_week]
        }


# Singleton instance
_notification_service: Optional[NotificationService] = None

def get_notification_service(db=None) -> NotificationService:
    """Get or create the notification service singleton"""
    global _notification_service
    if _notification_service is None and db is not None:
        _notification_service = NotificationService(db)
    return _notification_service
