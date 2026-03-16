"""
Historical Data Queue Service

Manages a queue of historical data requests that the local IB Data Pusher fulfills.
This enables the cloud backend to request historical data from IB Gateway through
the user's local connection.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pymongo import MongoClient
from pymongo.database import Database
import logging
import uuid

logger = logging.getLogger(__name__)

# Global instance
_historical_data_queue_service = None


class HistoricalDataQueueService:
    """Service for managing historical data request queue"""
    
    def __init__(self, db: Database):
        self.db = db
        self.collection = db["historical_data_requests"]
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """Create indexes for efficient queries"""
        try:
            self.collection.create_index("request_id", unique=True)
            self.collection.create_index("status")
            self.collection.create_index("created_at")
            self.collection.create_index([("status", 1), ("created_at", 1)])
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
    
    def create_request(self, symbol: str, duration: str = "1 M", 
                       bar_size: str = "1 day", callback_id: str = None,
                       skip_if_pending: bool = True) -> str:
        """
        Create a new historical data request.
        
        Args:
            symbol: Stock symbol to fetch
            duration: Duration string (e.g., "1 M", "1 D", "1 Y")
            bar_size: Bar size string (e.g., "1 day", "1 hour", "5 mins")
            callback_id: Optional ID to associate with this request
            skip_if_pending: If True, don't create if there's already a pending/claimed request
            
        Returns:
            request_id for tracking (or existing request_id if skipping duplicate)
        """
        # Check for existing pending/claimed request for same symbol+bar_size
        if skip_if_pending:
            existing = self.collection.find_one({
                "symbol": symbol.upper(),
                "bar_size": bar_size,
                "status": {"$in": ["pending", "claimed"]}
            }, {"request_id": 1})
            
            if existing:
                logger.debug(f"Skipping duplicate request for {symbol} {bar_size} - already in queue")
                return existing["request_id"]
        
        request_id = f"hist_{uuid.uuid4().hex[:12]}"
        
        request = {
            "request_id": request_id,
            "symbol": symbol.upper(),
            "duration": duration,
            "bar_size": bar_size,
            "callback_id": callback_id,
            "status": "pending",
            "data": None,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "claimed_at": None,
            "completed_at": None
        }
        
        self.collection.insert_one(request)
        logger.info(f"Created historical data request: {request_id} for {symbol}")
        
        return request_id
    
    def get_pending_requests(self, limit: int = 10) -> List[Dict]:
        """Get pending requests for the IB Data Pusher to fulfill"""
        cursor = self.collection.find(
            {"status": "pending"},
            {"_id": 0}
        ).sort("created_at", 1).limit(limit)
        
        return list(cursor)
    
    def claim_request(self, request_id: str) -> bool:
        """
        Claim a request (mark as being processed).
        Returns False if already claimed/completed.
        """
        result = self.collection.update_one(
            {"request_id": request_id, "status": "pending"},
            {"$set": {
                "status": "claimed",
                "claimed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        return result.modified_count > 0
    
    def complete_request(self, request_id: str, success: bool, 
                         data: List[Dict] = None, error: str = None) -> bool:
        """
        Mark a request as completed with results.
        
        Args:
            request_id: The request ID
            success: Whether the fetch was successful
            data: List of bar data if successful
            error: Error message if failed
        """
        status = "completed" if success else "failed"
        
        result = self.collection.update_one(
            {"request_id": request_id},
            {"$set": {
                "status": status,
                "data": data,
                "error": error,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        if result.modified_count > 0:
            logger.info(f"Completed historical data request: {request_id} -> {status}")
        
        return result.modified_count > 0
    
    def get_request(self, request_id: str) -> Optional[Dict]:
        """Get a specific request by ID"""
        return self.collection.find_one(
            {"request_id": request_id},
            {"_id": 0}
        )
    
    def get_request_result(self, request_id: str, timeout: float = 60.0) -> Optional[Dict]:
        """
        Wait for a request to complete and return the result.
        
        Args:
            request_id: The request ID to wait for
            timeout: Maximum time to wait in seconds
            
        Returns:
            Request data with results, or None if timeout
        """
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            request = self.get_request(request_id)
            if request and request.get("status") in ["completed", "failed"]:
                return request
            time.sleep(0.5)
        
        return None
    
    def cleanup_old_requests(self, hours: int = 24):
        """Remove requests older than specified hours"""
        cutoff = datetime.now(timezone.utc).isoformat()
        # Simple cleanup - remove completed requests older than cutoff
        result = self.collection.delete_many({
            "status": {"$in": ["completed", "failed"]},
            "completed_at": {"$lt": cutoff}
        })
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} old historical data requests")
    
    def clear_pending_requests(self) -> Dict:
        """
        Clear all pending requests from the queue.
        Use this to reset the queue before starting a new collection type.
        
        Returns:
            Dict with count of cleared requests
        """
        try:
            result = self.collection.delete_many({
                "status": "pending"
            })
            logger.info(f"Cleared {result.deleted_count} pending requests from queue")
            return {
                "success": True,
                "cleared": result.deleted_count
            }
        except Exception as e:
            logger.error(f"Error clearing pending requests: {e}")
            return {
                "success": False,
                "error": str(e),
                "cleared": 0
            }
    
    # =========================================================================
    # ASYNC BATCH COLLECTION METHODS
    # =========================================================================
    
    def create_batch_requests(self, symbols: List[str], duration: str = "1 M",
                              bar_size: str = "1 day", job_id: str = None) -> Dict:
        """
        Create requests for multiple symbols in batch (fast, no blocking).
        
        Args:
            symbols: List of symbols to fetch
            duration: Duration string
            bar_size: Bar size string
            job_id: Optional job ID to group these requests
            
        Returns:
            Dict with batch stats
        """
        if not symbols:
            return {"created": 0, "request_ids": []}
        
        request_ids = []
        requests_to_insert = []
        
        for symbol in symbols:
            request_id = f"hist_{uuid.uuid4().hex[:12]}"
            request_ids.append(request_id)
            
            requests_to_insert.append({
                "request_id": request_id,
                "symbol": symbol.upper(),
                "duration": duration,
                "bar_size": bar_size,
                "job_id": job_id,  # Group by job for tracking
                "status": "pending",
                "data": None,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "claimed_at": None,
                "completed_at": None
            })
        
        # Batch insert for efficiency
        if requests_to_insert:
            self.collection.insert_many(requests_to_insert)
            logger.info(f"Created {len(requests_to_insert)} batch requests for job {job_id}")
        
        return {
            "created": len(request_ids),
            "request_ids": request_ids,
            "job_id": job_id
        }
    
    def get_job_progress(self, job_id: str) -> Dict:
        """
        Get progress for a batch job.
        
        Returns:
            Dict with pending, processing, completed, failed counts
        """
        pipeline = [
            {"$match": {"job_id": job_id}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        
        counts = {
            "pending": 0,
            "claimed": 0,
            "completed": 0,
            "failed": 0
        }
        
        for r in results:
            status = r["_id"]
            if status in counts:
                counts[status] = r["count"]
        
        total = sum(counts.values())
        done = counts["completed"] + counts["failed"]
        
        return {
            "job_id": job_id,
            "total": total,
            "pending": counts["pending"],
            "processing": counts["claimed"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "progress_pct": (done / total * 100) if total > 0 else 0,
            "is_complete": done == total and total > 0
        }
    
    def get_job_errors(self, job_id: str, limit: int = 20) -> List[Dict]:
        """Get failed requests for a job"""
        cursor = self.collection.find(
            {"job_id": job_id, "status": "failed"},
            {"_id": 0, "request_id": 1, "symbol": 1, "error": 1, "completed_at": 1}
        ).sort("completed_at", -1).limit(limit)
        
        return list(cursor)
    
    def get_job_completed_data(self, job_id: str = None) -> List[Dict]:
        """
        Get all completed data for a job (for storage).
        If job_id is None, returns all completed data across all jobs.
        """
        query = {"status": "completed", "data": {"$ne": None}}
        if job_id:
            query["job_id"] = job_id
            
        cursor = self.collection.find(
            query,
            {"_id": 0, "symbol": 1, "bar_size": 1, "data": 1, "request_id": 1}
        ).limit(100)  # Process in batches
        return list(cursor)
    
    def mark_data_stored(self, request_id: str):
        """Mark a request's data as stored (clear data to save space)"""
        self.collection.update_one(
            {"request_id": request_id},
            {"$set": {"data": None, "data_stored": True}}
        )
    
    def cancel_job(self, job_id: str) -> Dict:
        """
        Cancel pending requests for a job.
        Already claimed/completed requests are not affected.
        """
        result = self.collection.delete_many({
            "job_id": job_id,
            "status": "pending"
        })
        
        logger.info(f"Cancelled {result.deleted_count} pending requests for job {job_id}")
        
        return {
            "cancelled": result.deleted_count,
            "job_id": job_id
        }
    
    def get_overall_queue_stats(self) -> Dict:
        """Get overall queue statistics"""
        pipeline = [
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        
        stats = {
            "pending": 0,
            "claimed": 0,
            "completed": 0,
            "failed": 0,
            "total": 0
        }
        
        for r in results:
            status = r["_id"]
            if status in stats:
                stats[status] = r["count"]
            stats["total"] += r["count"]
        
        return stats

    def get_queue_stats_by_bar_size(self) -> Dict:
        """
        Get queue statistics broken down by bar_size.
        
        Returns:
            Dict with progress for each bar_size type being collected
        """
        pipeline = [
            {
                "$group": {
                    "_id": {
                        "bar_size": "$bar_size",
                        "status": "$status"
                    },
                    "count": {"$sum": 1}
                }
            },
            {
                "$group": {
                    "_id": "$_id.bar_size",
                    "statuses": {
                        "$push": {
                            "status": "$_id.status",
                            "count": "$count"
                        }
                    },
                    "total": {"$sum": "$count"}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        
        by_bar_size = []
        for r in results:
            bar_size = r["_id"]
            statuses = {s["status"]: s["count"] for s in r["statuses"]}
            
            pending = statuses.get("pending", 0)
            claimed = statuses.get("claimed", 0)
            completed = statuses.get("completed", 0)
            failed = statuses.get("failed", 0)
            total = r["total"]
            done = completed + failed
            
            by_bar_size.append({
                "bar_size": bar_size,
                "pending": pending,
                "in_progress": claimed,
                "completed": completed,
                "failed": failed,
                "total": total,
                "progress_pct": round((done / total * 100), 1) if total > 0 else 0,
                "is_active": pending > 0 or claimed > 0
            })
        
        # Sort so active collections appear first
        by_bar_size.sort(key=lambda x: (not x["is_active"], x["bar_size"]))
        
        return {
            "by_bar_size": by_bar_size,
            "active_collections": [b for b in by_bar_size if b["is_active"]]
        }

    def cancel_by_bar_size(self, bar_size: str) -> Dict:
        """
        Cancel all pending requests for a specific bar_size.
        
        Args:
            bar_size: The bar size to cancel (e.g., "5 mins", "1 day")
            
        Returns:
            Dict with count of cancelled requests
        """
        result = self.collection.delete_many({
            "bar_size": bar_size,
            "status": "pending"
        })
        
        logger.info(f"Cancelled {result.deleted_count} pending requests for bar_size={bar_size}")
        
        return {
            "success": True,
            "bar_size": bar_size,
            "cancelled": result.deleted_count
        }

    def clear_all_pending(self) -> Dict:
        """
        Clear ALL pending requests from the queue.
        Use with caution - cancels all active collections.
        """
        result = self.collection.delete_many({
            "status": "pending"
        })
        
        logger.info(f"Cleared ALL {result.deleted_count} pending requests")
        
        return {
            "success": True,
            "cancelled": result.deleted_count
        }


def init_historical_data_queue_service(db: Database):
    """Initialize the service with a database connection"""
    global _historical_data_queue_service
    _historical_data_queue_service = HistoricalDataQueueService(db)
    logger.info("Historical Data Queue Service initialized")
    return _historical_data_queue_service


def get_historical_data_queue_service() -> HistoricalDataQueueService:
    """Get the global service instance"""
    if _historical_data_queue_service is None:
        raise RuntimeError("Historical Data Queue Service not initialized")
    return _historical_data_queue_service
