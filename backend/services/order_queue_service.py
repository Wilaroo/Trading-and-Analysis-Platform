"""
Order Queue Service - MongoDB backed order queue for remote execution
Replaces the in-memory order queue for persistence and reliability
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from enum import Enum
from pymongo import MongoClient, DESCENDING
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"      # Claimed by pusher but not yet executing
    EXECUTING = "executing"
    FILLED = "filled"
    PARTIALLY_FILLED = "partial"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    TIMEOUT = "timeout"


class QueuedOrder(BaseModel):
    """Order queued for remote execution"""
    order_id: str
    symbol: str
    action: str  # BUY or SELL
    quantity: int
    order_type: str = "MKT"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "DAY"
    trade_id: Optional[str] = None
    status: str = "pending"
    queued_at: str = None
    claimed_at: Optional[str] = None
    executed_at: Optional[str] = None
    fill_price: Optional[float] = None
    filled_qty: Optional[int] = None
    ib_order_id: Optional[int] = None
    error: Optional[str] = None
    attempts: int = 0


class OrderQueueService:
    """MongoDB-backed order queue for remote trade execution"""
    
    def __init__(self):
        self._db = None
        self._collection = None
        self._initialized = False
        
    def initialize(self, db=None):
        """Initialize with MongoDB connection"""
        if self._initialized:
            return
            
        try:
            if db is not None:
                self._db = db
            else:
                mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
                db_name = os.environ.get("DB_NAME", "trading_bot")
                client = MongoClient(mongo_url)
                self._db = client[db_name]
            
            self._collection = self._db.order_queue
            
            # Create indexes for efficient queries
            self._collection.create_index("status")
            self._collection.create_index("order_id", unique=True)
            self._collection.create_index([("queued_at", DESCENDING)])
            self._collection.create_index("symbol")
            
            self._initialized = True
            logger.info("OrderQueueService initialized with MongoDB")
            
        except Exception as e:
            logger.error(f"Failed to initialize OrderQueueService: {e}")
            raise
    
    def queue_order(self, order: Dict[str, Any]) -> str:
        """Queue an order for execution by local pusher. Returns order_id."""
        if not self._initialized:
            self.initialize()
            
        order_id = str(uuid.uuid4())[:8]
        
        order_doc = {
            "order_id": order_id,
            "symbol": order.get("symbol", "").upper(),
            "action": order.get("action", "BUY").upper(),
            "quantity": order.get("quantity", 0),
            "order_type": order.get("order_type", "MKT"),
            "limit_price": order.get("limit_price"),
            "stop_price": order.get("stop_price"),
            "time_in_force": order.get("time_in_force", "DAY"),
            "trade_id": order.get("trade_id"),
            "status": OrderStatus.PENDING.value,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "claimed_at": None,
            "executed_at": None,
            "fill_price": None,
            "filled_qty": None,
            "ib_order_id": None,
            "error": None,
            "attempts": 0
        }
        
        self._collection.insert_one(order_doc)
        logger.info(f"Order {order_id} queued: {order_doc['symbol']} {order_doc['action']} {order_doc['quantity']}")
        
        return order_id
    
    def get_pending_orders(self) -> List[Dict]:
        """Get all pending orders waiting for execution"""
        if not self._initialized:
            self.initialize()
            
        orders = list(self._collection.find(
            {"status": {"$in": [OrderStatus.PENDING.value, OrderStatus.CLAIMED.value]}},
            {"_id": 0}
        ).sort("queued_at", 1))
        
        return orders
    
    def claim_order(self, order_id: str) -> Optional[Dict]:
        """
        Claim an order for execution (prevents double execution).
        Returns the order if successfully claimed, None if already claimed.
        """
        if not self._initialized:
            self.initialize()
            
        result = self._collection.find_one_and_update(
            {"order_id": order_id, "status": OrderStatus.PENDING.value},
            {
                "$set": {
                    "status": OrderStatus.CLAIMED.value,
                    "claimed_at": datetime.now(timezone.utc).isoformat()
                },
                "$inc": {"attempts": 1}
            },
            return_document=True
        )
        
        if result:
            result.pop("_id", None)
            logger.info(f"Order {order_id} claimed for execution")
            
        return result
    
    def update_order_status(self, order_id: str, status: str, 
                           fill_price: float = None, filled_qty: int = None,
                           ib_order_id: int = None, error: str = None) -> bool:
        """Update order status after execution attempt"""
        if not self._initialized:
            self.initialize()
            
        update = {
            "status": status,
            "executed_at": datetime.now(timezone.utc).isoformat()
        }
        
        if fill_price is not None:
            update["fill_price"] = fill_price
        if filled_qty is not None:
            update["filled_qty"] = filled_qty
        if ib_order_id is not None:
            update["ib_order_id"] = ib_order_id
        if error is not None:
            update["error"] = error
            
        result = self._collection.update_one(
            {"order_id": order_id},
            {"$set": update}
        )
        
        if result.modified_count > 0:
            logger.info(f"Order {order_id} status updated to {status}")
            return True
        return False
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """Get a specific order by ID"""
        if not self._initialized:
            self.initialize()
            
        order = self._collection.find_one({"order_id": order_id}, {"_id": 0})
        return order
    
    def get_orders_by_status(self, status: str) -> List[Dict]:
        """Get all orders with a specific status"""
        if not self._initialized:
            self.initialize()
            
        return list(self._collection.find({"status": status}, {"_id": 0}))
    
    def get_recent_orders(self, limit: int = 50) -> List[Dict]:
        """Get most recent orders across all statuses"""
        if not self._initialized:
            self.initialize()
            
        return list(self._collection.find(
            {}, {"_id": 0}
        ).sort("queued_at", DESCENDING).limit(limit))
    
    def get_queue_status(self) -> Dict:
        """Get summary of order queue status"""
        if not self._initialized:
            self.initialize()
            
        pipeline = [
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        status_counts = {doc["_id"]: doc["count"] for doc in self._collection.aggregate(pipeline)}
        
        return {
            "pending": status_counts.get("pending", 0) + status_counts.get("claimed", 0),
            "executing": status_counts.get("executing", 0),
            "filled": status_counts.get("filled", 0),
            "rejected": status_counts.get("rejected", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "total": sum(status_counts.values())
        }
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order"""
        if not self._initialized:
            self.initialize()
            
        result = self._collection.update_one(
            {"order_id": order_id, "status": {"$in": ["pending", "claimed"]}},
            {"$set": {
                "status": OrderStatus.CANCELLED.value,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "error": "Cancelled by user"
            }}
        )
        
        return result.modified_count > 0
    
    def expire_stale_orders(self, max_age_minutes: int = 30):
        """Expire orders that have been pending too long"""
        if not self._initialized:
            self.initialize()
            
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
        
        result = self._collection.update_many(
            {
                "status": {"$in": ["pending", "claimed"]},
                "queued_at": {"$lt": cutoff}
            },
            {"$set": {
                "status": OrderStatus.EXPIRED.value,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "error": f"Order expired after {max_age_minutes} minutes"
            }}
        )
        
        if result.modified_count > 0:
            logger.info(f"Expired {result.modified_count} stale orders")
        
        return result.modified_count
    
    def cleanup_old_orders(self, days: int = 7):
        """Remove completed orders older than specified days"""
        if not self._initialized:
            self.initialize()
            
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        result = self._collection.delete_many({
            "status": {"$in": ["filled", "rejected", "cancelled", "expired"]},
            "executed_at": {"$lt": cutoff}
        })
        
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} old orders")
        
        return result.deleted_count


# Singleton instance
_order_queue_service: Optional[OrderQueueService] = None


def get_order_queue_service() -> OrderQueueService:
    """Get the singleton order queue service"""
    global _order_queue_service
    if _order_queue_service is None:
        _order_queue_service = OrderQueueService()
    return _order_queue_service


def init_order_queue_service(db=None):
    """Initialize the order queue service with optional DB"""
    service = get_order_queue_service()
    service.initialize(db)
    return service
