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
from pydantic import BaseModel, ConfigDict

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
    """Order queued for remote execution.

    `model_config` allows extra fields (e.g. bracket-order payload fields
    `type`, `parent`, `stop`, `target`, `oca_group`) to pass through the
    model without being silently dropped.
    """
    model_config = ConfigDict(extra="allow")

    order_id: str
    symbol: str
    action: Optional[str] = None  # BUY or SELL (optional for bracket type; nested under parent)
    quantity: Optional[int] = None  # Optional for bracket type; nested under parent
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
    # Bracket-order fields (atomic IB native bracket)
    type: Optional[str] = None  # "bracket" for atomic bracket orders
    parent: Optional[Dict[str, Any]] = None
    stop: Optional[Dict[str, Any]] = None
    target: Optional[Dict[str, Any]] = None
    oca_group: Optional[str] = None


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
        """Queue an order for execution by local pusher. Returns order_id.

        Supports both:
          - Regular orders: flat dict with symbol/action/quantity/order_type/etc.
          - Bracket orders: {"type": "bracket", "symbol": ..., "parent": {...},
                             "stop": {...}, "target": {...}, "trade_id": ...}
        """
        if not self._initialized:
            self.initialize()

        order_id = str(uuid.uuid4())[:8]
        is_bracket = order.get("type") == "bracket"

        order_doc = {
            "order_id": order_id,
            "symbol": order.get("symbol", "").upper(),
            # For bracket orders, action/quantity live inside `parent`;
            # leave top-level None so the pusher consults `parent` directly.
            "action": (order.get("action", "BUY").upper()
                       if not is_bracket and order.get("action")
                       else None if is_bracket else "BUY"),
            "quantity": order.get("quantity", 0) if not is_bracket else None,
            "order_type": order.get("order_type", "MKT") if not is_bracket else "bracket",
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
            "attempts": 0,
        }

        # Preserve bracket payload fields so they reach the Windows pusher
        # via /api/ib/orders/pending. Without this, atomic bracket orders
        # silently degrade to legacy entry-only submissions.
        if is_bracket:
            order_doc["type"] = "bracket"
            order_doc["parent"] = order.get("parent")
            order_doc["stop"] = order.get("stop")
            order_doc["target"] = order.get("target")
            if order.get("oca_group"):
                order_doc["oca_group"] = order.get("oca_group")

        self._collection.insert_one(order_doc)
        # Remove _id that MongoDB added to the dict so callers don't leak ObjectId
        order_doc.pop("_id", None)

        if is_bracket:
            parent = order_doc.get("parent") or {}
            logger.info(
                f"Bracket order {order_id} queued: {order_doc['symbol']} "
                f"{parent.get('action', '?')} {parent.get('quantity', '?')} "
                f"(parent+stop+target)"
            )
        else:
            logger.info(
                f"Order {order_id} queued: {order_doc['symbol']} "
                f"{order_doc['action']} {order_doc['quantity']}"
            )

        return order_id
    
    def get_pending_orders(self) -> List[Dict]:
        """Get all pending orders waiting for execution.
        
        Also auto-expires CLAIMED orders older than 5 minutes — these are
        orders that were claimed but never completed (e.g., pusher restarted
        mid-execution). Without this cleanup they loop forever.
        """
        if not self._initialized:
            self.initialize()

        # Auto-expire stale CLAIMED orders (claimed > 5 min ago, never completed)
        try:
            from datetime import timedelta
            stale_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            expired = self._collection.update_many(
                {
                    "status": OrderStatus.CLAIMED.value,
                    "claimed_at": {"$lt": stale_cutoff},
                },
                {"$set": {
                    "status": OrderStatus.EXPIRED.value,
                    "expired_at": datetime.now(timezone.utc).isoformat(),
                    "error": "Auto-expired: claimed but never completed within 5 minutes",
                }},
            )
            if expired.modified_count > 0:
                logger.warning(f"Auto-expired {expired.modified_count} stale CLAIMED orders")
        except Exception as e:
            logger.debug(f"Stale order cleanup error: {e}")

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
    
    def reconcile_dead_letters(
        self,
        *,
        pending_timeout_sec: int = 120,
        claimed_timeout_sec: int = 120,
        executing_timeout_sec: int = 300,
    ) -> Dict[str, Any]:
        """Dead-letter the order queue.

        Any order that has been stuck in a pre-fill state longer than its
        per-status timeout is transitioned to `TIMEOUT` with a structured
        reason. This handles:

          * PENDING too long       → pusher offline / Windows PC unreachable
          * CLAIMED too long       → pusher grabbed but crashed mid-submit
          * EXECUTING too long     → silent broker reject or ACK-never-arrived

        Returns a summary:
            {
              "timed_out": int,
              "by_status": {"pending": n, "claimed": n, "executing": n},
              "orders": [ {order_id, symbol, prior_status, age_sec, reason}, ... ],
              "ran_at": "2026-04-23T..."
            }
        """
        if not self._initialized:
            self.initialize()

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Windows: (status, timestamp-field-to-compare, cutoff_iso, reason_template)
        windows = [
            ("pending", "queued_at",   pending_timeout_sec,
             "no pusher pickup within {sec}s — broker/pusher offline"),
            ("claimed", "claimed_at",  claimed_timeout_sec,
             "pusher claimed but never executed within {sec}s — pusher crash"),
            ("executing", "executed_at", executing_timeout_sec,
             "broker ACK/fill never arrived within {sec}s — silent reject"),
        ]

        timed_out_docs: List[Dict[str, Any]] = []
        by_status: Dict[str, int] = {}

        for status, ts_field, timeout_sec, reason_fmt in windows:
            cutoff_iso = (now - timedelta(seconds=timeout_sec)).isoformat()
            # Fetch candidates FIRST so we can log which orders were dead-lettered.
            candidates = list(self._collection.find(
                {
                    "status": status,
                    ts_field: {"$ne": None, "$lt": cutoff_iso},
                },
                {"_id": 0, "order_id": 1, "symbol": 1, "trade_id": 1,
                 ts_field: 1, "queued_at": 1},
            ))
            if not candidates:
                by_status[status] = 0
                continue

            reason = reason_fmt.format(sec=timeout_sec)
            ids = [c["order_id"] for c in candidates]
            res = self._collection.update_many(
                {"order_id": {"$in": ids}, "status": status},
                {"$set": {
                    "status": OrderStatus.TIMEOUT.value,
                    "executed_at": now_iso,
                    "timed_out_at": now_iso,
                    "error": f"dead-letter: {reason}",
                }},
            )
            modified = int(getattr(res, "modified_count", 0) or 0)
            by_status[status] = modified

            for c in candidates:
                ts = c.get(ts_field) or c.get("queued_at")
                try:
                    age_sec = int((now - datetime.fromisoformat(ts)).total_seconds()) if ts else None
                except Exception:
                    age_sec = None
                timed_out_docs.append({
                    "order_id": c.get("order_id"),
                    "symbol": c.get("symbol"),
                    "trade_id": c.get("trade_id"),
                    "prior_status": status,
                    "age_sec": age_sec,
                    "reason": reason,
                })

            if modified:
                logger.warning(
                    "[OrderQueue] Dead-lettered %d %s order(s) (timeout=%ss): %s",
                    modified, status, timeout_sec,
                    ",".join(ids[:10]) + ("…" if len(ids) > 10 else ""),
                )

        return {
            "timed_out": sum(by_status.values()),
            "by_status": by_status,
            "orders": timed_out_docs,
            "ran_at": now_iso,
        }

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
