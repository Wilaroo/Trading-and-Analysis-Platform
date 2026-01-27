"""
Scheduler Service for TradeCommand
Handles scheduled tasks like pre-market briefing generation.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Callable, Any
import threading

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Scheduler for automated tasks like pre-market briefings.
    Uses asyncio for non-blocking execution.
    """
    
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._premarket_callback: Optional[Callable] = None
        self._last_premarket_run: Optional[datetime] = None
        self._premarket_cache: Optional[Dict] = None
        
    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start the scheduler"""
        if self._running:
            return
            
        self._running = True
        self._loop = loop or asyncio.get_event_loop()
        logger.info("Scheduler service started")
        
    def stop(self):
        """Stop the scheduler and cancel all tasks"""
        self._running = False
        for task_name, task in self._tasks.items():
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled task: {task_name}")
        self._tasks.clear()
        logger.info("Scheduler service stopped")
        
    def register_premarket_callback(self, callback: Callable):
        """Register the callback function for pre-market briefing generation"""
        self._premarket_callback = callback
        logger.info("Pre-market callback registered")
        
    async def schedule_premarket_briefing(self, target_hour: int = 6, target_minute: int = 30):
        """
        Schedule pre-market briefing to run daily at specified time (EST/EDT).
        Default: 6:30 AM ET
        """
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                
                # Convert to Eastern Time (approximately)
                # ET is UTC-5 (EST) or UTC-4 (EDT)
                # Using a simple approximation - production should use pytz
                et_offset = -5  # EST (winter)
                # Check if it's daylight saving (roughly March-November)
                if now.month >= 3 and now.month < 11:
                    et_offset = -4  # EDT
                    
                et_now = now + timedelta(hours=et_offset)
                
                # Calculate next run time
                next_run = et_now.replace(
                    hour=target_hour, 
                    minute=target_minute, 
                    second=0, 
                    microsecond=0
                )
                
                # If we've already passed the target time today, schedule for tomorrow
                if et_now >= next_run:
                    next_run += timedelta(days=1)
                    
                # Calculate wait time
                wait_seconds = (next_run - et_now).total_seconds()
                
                logger.info(f"Pre-market briefing scheduled for {next_run.strftime('%Y-%m-%d %H:%M')} ET (waiting {wait_seconds/3600:.1f} hours)")
                
                # Wait until target time
                await asyncio.sleep(wait_seconds)
                
                # Execute the pre-market generation
                if self._premarket_callback:
                    await self._run_premarket_generation()
                    
            except asyncio.CancelledError:
                logger.info("Pre-market scheduler task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in pre-market scheduler: {e}")
                # Wait 5 minutes before retrying
                await asyncio.sleep(300)
                
    async def _run_premarket_generation(self):
        """Execute the pre-market briefing generation"""
        try:
            logger.info("Running scheduled pre-market briefing generation...")
            
            if self._premarket_callback:
                result = await self._premarket_callback()
                self._last_premarket_run = datetime.now(timezone.utc)
                self._premarket_cache = result
                logger.info(f"Pre-market briefing generated successfully at {self._last_premarket_run}")
                return result
            else:
                logger.warning("No pre-market callback registered")
                return None
                
        except Exception as e:
            logger.error(f"Error generating pre-market briefing: {e}")
            return None
            
    async def generate_premarket_now(self) -> Optional[Dict]:
        """Manually trigger pre-market briefing generation"""
        return await self._run_premarket_generation()
        
    def get_cached_premarket(self) -> Optional[Dict]:
        """Get the cached pre-market briefing if available"""
        return self._premarket_cache
        
    def get_last_run_time(self) -> Optional[datetime]:
        """Get the last time pre-market was generated"""
        return self._last_premarket_run
        
    def get_status(self) -> Dict:
        """Get scheduler status"""
        return {
            "running": self._running,
            "tasks": list(self._tasks.keys()),
            "last_premarket_run": self._last_premarket_run.isoformat() if self._last_premarket_run else None,
            "has_premarket_cache": self._premarket_cache is not None,
            "premarket_callback_registered": self._premarket_callback is not None
        }
        
    def start_premarket_schedule(self, target_hour: int = 6, target_minute: int = 30):
        """Start the pre-market briefing schedule"""
        if "premarket" in self._tasks:
            logger.warning("Pre-market schedule already running")
            return
            
        if not self._loop:
            logger.error("Scheduler not started - call start() first")
            return
            
        task = self._loop.create_task(
            self.schedule_premarket_briefing(target_hour, target_minute)
        )
        self._tasks["premarket"] = task
        logger.info(f"Pre-market schedule started for {target_hour}:{target_minute:02d} ET")


# Singleton instance
_scheduler_service: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    """Get the singleton scheduler service"""
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service


def init_scheduler_service() -> SchedulerService:
    """Initialize the scheduler service"""
    global _scheduler_service
    _scheduler_service = SchedulerService()
    return _scheduler_service
