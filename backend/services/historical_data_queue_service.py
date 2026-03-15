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
                       bar_size: str = "1 day", callback_id: str = None) -> str:
        """
        Create a new historical data request.
        
        Args:
            symbol: Stock symbol to fetch
            duration: Duration string (e.g., "1 M", "1 D", "1 Y")
            bar_size: Bar size string (e.g., "1 day", "1 hour", "5 mins")
            callback_id: Optional ID to associate with this request
            
        Returns:
            request_id for tracking
        """
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
