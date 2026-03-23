"""
Job Queue Manager - Background Task Queue System

Manages long-running jobs (training, data collection, backtesting) that can be:
- Submitted via API
- Executed by a worker process
- Monitored for progress
- Cancelled if needed

Jobs are stored in MongoDB for persistence and cross-process communication.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class JobType(str, Enum):
    """Types of background jobs"""
    TRAINING = "training"
    DATA_COLLECTION = "data_collection"
    BACKTEST = "backtest"
    CALIBRATION = "calibration"


class JobStatus(str, Enum):
    """Job status states"""
    PENDING = "pending"      # Waiting to be picked up
    RUNNING = "running"      # Currently executing
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"        # Finished with error
    CANCELLED = "cancelled"  # User cancelled


class JobQueueManager:
    """Manages the job queue in MongoDB.
    
    Works with both pymongo (sync) and motor (async) drivers.
    - pymongo: wraps calls in asyncio.to_thread to avoid blocking
    - motor: awaits calls directly (already async)
    """
    
    COLLECTION_NAME = "job_queue"
    
    def __init__(self, db=None):
        self._db = db
        self._collection = None
        self._is_motor = False
    
    def set_db(self, db):
        """Set the MongoDB database connection."""
        self._db = db
        self._collection = db[self.COLLECTION_NAME] if db is not None else None
        # Detect if this is a motor (async) or pymongo (sync) database
        self._is_motor = type(db).__module__.startswith('motor') if db is not None else False
        if self._is_motor:
            print("[JOB QUEUE] Using motor (async) driver")
        else:
            print("[JOB QUEUE] Using pymongo (sync) driver")
    
    @property
    def collection(self):
        """Get the jobs collection."""
        if self._collection is None and self._db is not None:
            self._collection = self._db[self.COLLECTION_NAME]
        return self._collection
    
    async def _run(self, method, *args, **kwargs):
        """Run a collection method, handling both motor and pymongo.
        
        - motor: method returns a coroutine, await it directly
        - pymongo: method is synchronous, wrap in asyncio.to_thread
        """
        if self._is_motor:
            return await method(*args, **kwargs)
        else:
            return await asyncio.to_thread(method, *args, **kwargs)
    
    async def _find_to_list(self, cursor):
        """Convert a cursor to a list, handling both drivers."""
        if self._is_motor:
            return await cursor.to_list(length=None)
        else:
            return await asyncio.to_thread(list, cursor)
    
    async def create_job(
        self,
        job_type: str,
        params: Dict[str, Any],
        priority: int = 5,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Create a new job in the queue.
        
        Args:
            job_type: Type of job (training, data_collection, backtest, calibration)
            params: Job-specific parameters
            priority: Job priority (1-10, higher = more urgent)
            metadata: Optional additional metadata
            
        Returns:
            Job document with ID
        """
        if self.collection is None:
            return {'success': False, 'error': 'Database not connected'}
        
        job_id = str(uuid.uuid4())[:8]  # Short ID for convenience
        
        job = {
            'job_id': job_id,
            'job_type': job_type,
            'params': params,
            'priority': priority,
            'status': JobStatus.PENDING.value,
            'progress': {
                'percent': 0,
                'message': 'Waiting to start...',
                'current_step': 0,
                'total_steps': 0,
                'details': {}
            },
            'result': None,
            'error': None,
            'metadata': metadata or {},
            'created_at': datetime.now(timezone.utc),
            'started_at': None,
            'completed_at': None,
            'worker_id': None
        }
        
        try:
            result = await self._run(self.collection.insert_one, job)
            print(f"[JOB QUEUE] Created job {job_id}: {job_type} (acknowledged={result.acknowledged})")
            
            # Remove MongoDB _id for response
            job.pop('_id', None)
            return {'success': True, 'job': job}
            
        except Exception as e:
            print(f"[JOB QUEUE] Error creating job: {e}")
            return {'success': False, 'error': str(e)}
    
    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        if self.collection is None:
            return None
            
        job = await self._run(
            self.collection.find_one,
            {'job_id': job_id},
            {'_id': 0}
        )
        return job
    
    async def get_pending_jobs(self, job_type: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending jobs, sorted by priority and creation time."""
        if self.collection is None:
            return []
        
        query = {'status': JobStatus.PENDING.value}
        if job_type:
            query['job_type'] = job_type
        
        cursor = self.collection.find(
            query,
            {'_id': 0}
        ).sort([
            ('priority', -1),  # Higher priority first
            ('created_at', 1)  # Older jobs first within same priority
        ]).limit(limit)
        
        return await self._find_to_list(cursor)
    
    async def get_next_job(self, job_types: List[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get and claim the next pending job.
        Uses atomic update to prevent race conditions.
        """
        if self.collection is None:
            return None
        
        query = {'status': JobStatus.PENDING.value}
        if job_types:
            query['job_type'] = {'$in': job_types}
        
        worker_id = str(uuid.uuid4())[:8]
        
        # Atomically find and update
        job = await self._run(
            self.collection.find_one_and_update,
            query,
            {
                '$set': {
                    'status': JobStatus.RUNNING.value,
                    'started_at': datetime.now(timezone.utc),
                    'worker_id': worker_id,
                    'progress.message': 'Starting...'
                }
            },
            sort=[('priority', -1), ('created_at', 1)],
            return_document=True
        )
        
        if job:
            job.pop('_id', None)
            logger.info(f"[JOB QUEUE] Worker {worker_id} claimed job {job['job_id']}")
        
        return job
    
    async def update_progress(
        self,
        job_id: str,
        percent: int = None,
        message: str = None,
        current_step: int = None,
        total_steps: int = None,
        details: Dict = None
    ) -> bool:
        """Update job progress."""
        if self.collection is None:
            return False
        
        update = {}
        if percent is not None:
            update['progress.percent'] = min(100, max(0, percent))
        if message is not None:
            update['progress.message'] = message
        if current_step is not None:
            update['progress.current_step'] = current_step
        if total_steps is not None:
            update['progress.total_steps'] = total_steps
        if details:
            for key, value in details.items():
                update[f'progress.details.{key}'] = value
        
        if not update:
            return True
        
        result = await self._run(
            self.collection.update_one,
            {'job_id': job_id},
            {'$set': update}
        )
        return result.modified_count > 0
    
    async def complete_job(self, job_id: str, result: Dict[str, Any]) -> bool:
        """Mark a job as completed with result."""
        if self.collection is None:
            return False
        
        update_result = await self._run(
            self.collection.update_one,
            {'job_id': job_id},
            {
                '$set': {
                    'status': JobStatus.COMPLETED.value,
                    'completed_at': datetime.now(timezone.utc),
                    'result': result,
                    'progress.percent': 100,
                    'progress.message': 'Completed'
                }
            }
        )
        
        if update_result.modified_count > 0:
            logger.info(f"[JOB QUEUE] Job {job_id} completed")
            return True
        return False
    
    async def fail_job(self, job_id: str, error: str) -> bool:
        """Mark a job as failed with error message."""
        if self.collection is None:
            return False
        
        update_result = await self._run(
            self.collection.update_one,
            {'job_id': job_id},
            {
                '$set': {
                    'status': JobStatus.FAILED.value,
                    'completed_at': datetime.now(timezone.utc),
                    'error': error,
                    'progress.message': f'Failed: {error}'
                }
            }
        )
        
        if update_result.modified_count > 0:
            logger.error(f"[JOB QUEUE] Job {job_id} failed: {error}")
            return True
        return False
    
    async def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a pending or running job."""
        if self.collection is None:
            return {'success': False, 'error': 'Database not connected'}
        
        job = await self.get_job(job_id)
        if not job:
            return {'success': False, 'error': 'Job not found'}
        
        if job['status'] in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]:
            return {'success': False, 'error': f"Cannot cancel job in {job['status']} status"}
        
        update_result = await self._run(
            self.collection.update_one,
            {'job_id': job_id},
            {
                '$set': {
                    'status': JobStatus.CANCELLED.value,
                    'completed_at': datetime.now(timezone.utc),
                    'progress.message': 'Cancelled by user'
                }
            }
        )
        
        if update_result.modified_count > 0:
            logger.info(f"[JOB QUEUE] Job {job_id} cancelled")
            return {'success': True, 'message': 'Job cancelled'}
        
        return {'success': False, 'error': 'Failed to cancel job'}
    
    async def get_recent_jobs(
        self,
        job_type: str = None,
        status: str = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent jobs with optional filtering."""
        if self.collection is None:
            return []
        
        query = {}
        if job_type:
            query['job_type'] = job_type
        if status:
            query['status'] = status
        
        cursor = self.collection.find(
            query,
            {'_id': 0}
        ).sort('created_at', -1).limit(limit)
        
        return await self._find_to_list(cursor)
    
    async def get_running_jobs(self) -> List[Dict[str, Any]]:
        """Get all currently running jobs."""
        if self.collection is None:
            return []
        
        cursor = self.collection.find(
            {'status': JobStatus.RUNNING.value},
            {'_id': 0}
        )
        return await self._find_to_list(cursor)
    
    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Remove completed/failed/cancelled jobs older than X days."""
        if self.collection is None:
            return 0
        
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = await self._run(
            self.collection.delete_many,
            {
                'status': {'$in': [
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value
                ]},
                'completed_at': {'$lt': cutoff}
            }
        )
        
        if result.deleted_count > 0:
            logger.info(f"[JOB QUEUE] Cleaned up {result.deleted_count} old jobs")
        
        return result.deleted_count
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get job queue statistics."""
        if self.collection is None:
            return {'error': 'Database not connected'}
        
        pipeline = [
            {
                '$group': {
                    '_id': '$status',
                    'count': {'$sum': 1}
                }
            }
        ]
        
        cursor = self.collection.aggregate(pipeline)
        results = await self._find_to_list(cursor)
        stats = {doc['_id']: doc['count'] for doc in results}
        
        return {
            'pending': stats.get(JobStatus.PENDING.value, 0),
            'running': stats.get(JobStatus.RUNNING.value, 0),
            'completed': stats.get(JobStatus.COMPLETED.value, 0),
            'failed': stats.get(JobStatus.FAILED.value, 0),
            'cancelled': stats.get(JobStatus.CANCELLED.value, 0),
            'total': sum(stats.values())
        }


# Global singleton instance
job_queue_manager = JobQueueManager()


def get_job_queue_manager() -> JobQueueManager:
    """Get the global job queue manager instance."""
    return job_queue_manager
