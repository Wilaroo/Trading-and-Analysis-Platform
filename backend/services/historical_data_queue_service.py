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
            Dict with progress for each bar_size type being collected,
            including estimated time remaining based on completion rate.
            
        Note: Automatically clears items stuck in 'claimed' status for > 10 minutes.
        """
        from datetime import datetime, timedelta, timezone
        
        # Auto-clear stuck items (claimed for more than 10 minutes)
        self._auto_clear_stuck_items(older_than_minutes=10)
        
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
            
            # Calculate estimated time remaining
            eta_seconds = None
            eta_display = None
            symbols_per_minute = None
            
            if pending > 0 or claimed > 0:
                # Get recent completions to calculate rate
                eta_result = self._calculate_eta_for_bar_size(bar_size, pending + claimed)
                eta_seconds = eta_result.get("eta_seconds")
                eta_display = eta_result.get("eta_display")
                symbols_per_minute = eta_result.get("symbols_per_minute")
            
            by_bar_size.append({
                "bar_size": bar_size,
                "pending": pending,
                "in_progress": claimed,
                "completed": completed,
                "failed": failed,
                "total": total,
                "progress_pct": round((done / total * 100), 1) if total > 0 else 0,
                "is_active": pending > 0 or claimed > 0,
                "eta_seconds": eta_seconds,
                "eta_display": eta_display,
                "symbols_per_minute": symbols_per_minute
            })
        
        # Sort so active collections appear first
        by_bar_size.sort(key=lambda x: (not x["is_active"], x["bar_size"]))
        
        return {
            "by_bar_size": by_bar_size,
            "active_collections": [b for b in by_bar_size if b["is_active"]]
        }

    def _auto_clear_stuck_items(self, older_than_minutes: int = 10):
        """
        Automatically clear items stuck in 'claimed' status for too long.
        Called internally when checking progress.
        """
        from datetime import datetime, timedelta, timezone
        
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
            
            # Find and update stuck items
            result = self.collection.update_many(
                {
                    "status": "claimed",
                    "claimed_at": {"$lt": cutoff.isoformat()}
                },
                {"$set": {"status": "failed", "error": f"Auto-cleared: stuck > {older_than_minutes} min"}}
            )
            
            if result.modified_count > 0:
                logger.info(f"Auto-cleared {result.modified_count} stuck items (claimed > {older_than_minutes} min)")
        except Exception as e:
            logger.warning(f"Error auto-clearing stuck items: {e}")

    def _calculate_eta_for_bar_size(self, bar_size: str, remaining: int) -> Dict:
        """
        Calculate estimated time remaining for a bar_size based on recent completion rate.
        
        Uses the last 50 completions to calculate average time per symbol.
        """
        from datetime import datetime, timedelta, timezone
        
        # Get recent completed items with timestamps
        recent_completions = list(self.collection.find(
            {
                "bar_size": bar_size,
                "status": "completed",
                "completed_at": {"$exists": True}
            },
            {"completed_at": 1, "_id": 0}
        ).sort("completed_at", -1).limit(50))
        
        if len(recent_completions) < 2:
            # Not enough data - use IB Gateway default rate (~3 seconds per symbol)
            default_rate = 3.0  # seconds per symbol
            eta_seconds = int(remaining * default_rate)
            return {
                "eta_seconds": eta_seconds,
                "eta_display": self._format_eta(eta_seconds),
                "symbols_per_minute": round(60 / default_rate, 1),
                "rate_source": "default"
            }
        
        # Calculate time span of recent completions
        timestamps = [c["completed_at"] for c in recent_completions if c.get("completed_at")]
        
        if len(timestamps) < 2:
            default_rate = 3.0
            eta_seconds = int(remaining * default_rate)
            return {
                "eta_seconds": eta_seconds,
                "eta_display": self._format_eta(eta_seconds),
                "symbols_per_minute": round(60 / default_rate, 1),
                "rate_source": "default"
            }
        
        # Parse timestamps if they're strings
        parsed_timestamps = []
        for ts in timestamps:
            if isinstance(ts, str):
                try:
                    parsed_timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
                except (ValueError, TypeError):
                    pass
            elif isinstance(ts, datetime):
                parsed_timestamps.append(ts)
        
        if len(parsed_timestamps) < 2:
            default_rate = 3.0
            eta_seconds = int(remaining * default_rate)
            return {
                "eta_seconds": eta_seconds,
                "eta_display": self._format_eta(eta_seconds),
                "symbols_per_minute": round(60 / default_rate, 1),
                "rate_source": "default"
            }
        
        # Calculate rate
        newest = max(parsed_timestamps)
        oldest = min(parsed_timestamps)
        time_span = (newest - oldest).total_seconds()
        
        if time_span <= 0:
            default_rate = 3.0
            eta_seconds = int(remaining * default_rate)
            return {
                "eta_seconds": eta_seconds,
                "eta_display": self._format_eta(eta_seconds),
                "symbols_per_minute": round(60 / default_rate, 1),
                "rate_source": "default"
            }
        
        symbols_completed = len(parsed_timestamps)
        seconds_per_symbol = time_span / symbols_completed
        symbols_per_minute = round(60 / seconds_per_symbol, 1) if seconds_per_symbol > 0 else 0
        
        # Calculate ETA
        eta_seconds = int(remaining * seconds_per_symbol)
        
        return {
            "eta_seconds": eta_seconds,
            "eta_display": self._format_eta(eta_seconds),
            "symbols_per_minute": symbols_per_minute,
            "rate_source": "calculated",
            "sample_size": symbols_completed
        }

    def _format_eta(self, seconds: int) -> str:
        """Format seconds into human-readable time remaining"""
        if seconds is None or seconds <= 0:
            return "calculating..."
        
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            if secs > 0:
                return f"{minutes}m {secs}s"
            return f"{minutes}m"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours}h"

    def cancel_by_bar_size(self, bar_size: str) -> Dict:
        """
        Cancel all pending requests for a specific bar_size.
        Already completed data is preserved.
        
        Args:
            bar_size: The bar size to cancel (e.g., "5 mins", "1 day")
            
        Returns:
            Dict with count of cancelled requests and saved data info
        """
        # First get counts before cancelling
        completed_count = self.collection.count_documents({
            "bar_size": bar_size,
            "status": "completed"
        })
        
        # Cancel pending
        pending_result = self.collection.delete_many({
            "bar_size": bar_size,
            "status": "pending"
        })
        
        # Also clear any stuck "claimed" items (mark as failed or delete)
        stuck_result = self.collection.delete_many({
            "bar_size": bar_size,
            "status": "claimed"
        })
        
        total_cancelled = pending_result.deleted_count + stuck_result.deleted_count
        
        logger.info(f"Cancelled {pending_result.deleted_count} pending + {stuck_result.deleted_count} stuck for bar_size={bar_size}, {completed_count} already saved")
        
        return {
            "success": True,
            "bar_size": bar_size,
            "cancelled": total_cancelled,
            "pending_cancelled": pending_result.deleted_count,
            "stuck_cleared": stuck_result.deleted_count,
            "saved": completed_count,
            "message": f"Cancelled {total_cancelled} ({pending_result.deleted_count} pending + {stuck_result.deleted_count} stuck). {completed_count} symbols already collected and saved."
        }

    def clear_stuck_items(self, bar_size: str = None, older_than_minutes: int = 10) -> Dict:
        """
        Clear items that have been 'claimed' for too long (stuck).
        
        Args:
            bar_size: Optional - only clear for specific bar_size
            older_than_minutes: Clear items claimed longer than this (default 10 min)
            
        Returns:
            Dict with count of cleared items
        """
        from datetime import datetime, timedelta, timezone
        
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        
        query = {
            "status": "claimed",
            "claimed_at": {"$lt": cutoff.isoformat()}
        }
        
        if bar_size:
            query["bar_size"] = bar_size
        
        # Mark as failed instead of deleting (so we know they need retry)
        result = self.collection.update_many(
            query,
            {"$set": {"status": "failed", "error": "Stuck - timed out after claim"}}
        )
        
        logger.info(f"Cleared {result.modified_count} stuck items (claimed > {older_than_minutes} min)")
        
        return {
            "success": True,
            "cleared": result.modified_count,
            "bar_size": bar_size or "all"
        }

    def get_resumable_collections(self) -> List[Dict]:
        """
        Get collections that can be resumed (have completed work but no pending items).
        
        Returns:
            List of bar_sizes that have partial data but are not currently collecting
        """
        stats = self.get_queue_stats_by_bar_size()
        
        resumable = []
        for item in stats.get("by_bar_size", []):
            # Resumable if: has completed work, not 100% done, and not currently active
            if (item["completed"] > 0 and 
                item["progress_pct"] < 100 and 
                not item["is_active"]):
                resumable.append({
                    "bar_size": item["bar_size"],
                    "completed": item["completed"],
                    "failed": item["failed"],
                    "total": item["total"],
                    "progress_pct": item["progress_pct"],
                    "remaining": item["total"] - item["completed"] - item["failed"]
                })
        
        return resumable

    def get_failed_symbols(self, bar_size: str) -> List[str]:
        """
        Get symbols that failed for a specific bar_size.
        These can be retried in a resume operation.
        """
        failed_docs = self.collection.find(
            {"bar_size": bar_size, "status": "failed"},
            {"symbol": 1, "_id": 0}
        )
        return [doc["symbol"] for doc in failed_docs]

    def get_completed_symbols(self, bar_size: str) -> List[str]:
        """
        Get symbols that have already been completed for a bar_size.
        Used to determine what NOT to re-collect on resume.
        """
        completed_docs = self.collection.find(
            {"bar_size": bar_size, "status": "completed"},
            {"symbol": 1, "_id": 0}
        )
        return [doc["symbol"] for doc in completed_docs]

    def clear_failed_for_retry(self, bar_size: str) -> int:
        """
        Clear failed requests so they can be retried.
        Returns count of cleared failures.
        """
        result = self.collection.delete_many({
            "bar_size": bar_size,
            "status": "failed"
        })
        logger.info(f"Cleared {result.deleted_count} failed requests for bar_size={bar_size}")
        return result.deleted_count

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
