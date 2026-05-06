"""
Training Mode Manager - Prioritizes AI Training

When training mode is active:
- Pauses non-essential background tasks
- Frees up CPU/GPU resources
- Maintains only essential services (health, WebSocket, database)

Usage:
    from services.training_mode import training_mode_manager
    
    # Start training mode
    training_mode_manager.enter_training_mode()
    
    # Check if in training mode
    if training_mode_manager.is_training_active():
        # Skip non-essential task
        pass
    
    # Exit training mode
    training_mode_manager.exit_training_mode()
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Callable, List

logger = logging.getLogger(__name__)


class TrainingModeManager:
    """Manages training priority mode to optimize resources during AI training."""
    
    def __init__(self):
        self._training_active = False
        self._training_start_time: Optional[datetime] = None
        self._training_type: Optional[str] = None  # 'quick', 'full', 'single'
        self._current_timeframe: Optional[str] = None
        self._paused_tasks: List[str] = []
        self._callbacks_on_enter: List[Callable] = []
        self._callbacks_on_exit: List[Callable] = []
    
    def is_training_active(self) -> bool:
        """Check if training mode is currently active."""
        return self._training_active
    
    def enter_training_mode(self, training_type: str = 'single', timeframe: str = None) -> dict:
        """
        Enter training mode - pauses non-essential background tasks.
        
        Args:
            training_type: 'quick', 'full', or 'single'
            timeframe: The timeframe being trained (e.g., '1 day')
        """
        if self._training_active:
            logger.warning("Training mode already active")
            return {"success": False, "message": "Training already in progress"}
        
        self._training_active = True
        self._training_start_time = datetime.now(timezone.utc)
        self._training_type = training_type
        self._current_timeframe = timeframe
        
        logger.info(f"[TRAINING MODE] ACTIVATED - Type: {training_type}, Timeframe: {timeframe}")
        logger.info("[TRAINING MODE] Pausing non-essential background tasks...")
        
        # Execute enter callbacks
        for callback in self._callbacks_on_enter:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in training mode enter callback: {e}")
        
        self._paused_tasks = [
            'trading_bot_scan_loop',
            'background_scanner',
            'learning_loop_scheduler',
            'market_intel_scheduler',
            'shadow_signal_updates',
            'ib_data_pusher_processing'
        ]
        
        return {
            "success": True,
            "message": "Training mode activated",
            "paused_tasks": self._paused_tasks,
            "start_time": self._training_start_time.isoformat()
        }
    
    def exit_training_mode(self, result: dict = None) -> dict:
        """
        Exit training mode - resumes normal background operations.
        
        Args:
            result: Optional training result to include in response
        """
        if not self._training_active:
            logger.warning("Training mode not active")
            return {"success": False, "message": "Training mode not active"}
        
        elapsed = None
        if self._training_start_time:
            elapsed = (datetime.now(timezone.utc) - self._training_start_time).total_seconds()
        
        logger.info(f"[TRAINING MODE] DEACTIVATED - Elapsed: {elapsed:.1f}s")
        logger.info("[TRAINING MODE] Resuming background tasks...")
        
        # Execute exit callbacks
        for callback in self._callbacks_on_exit:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in training mode exit callback: {e}")
        
        response = {
            "success": True,
            "message": "Training mode deactivated",
            "elapsed_seconds": elapsed,
            "training_type": self._training_type,
            "timeframe": self._current_timeframe,
            "result": result
        }
        
        # Reset state
        self._training_active = False
        self._training_start_time = None
        self._training_type = None
        self._current_timeframe = None
        self._paused_tasks = []
        
        return response
    
    def get_status(self) -> dict:
        """Get current training mode status."""
        elapsed = None
        if self._training_active and self._training_start_time:
            elapsed = (datetime.now(timezone.utc) - self._training_start_time).total_seconds()
        
        return {
            "training_active": self._training_active,
            "training_type": self._training_type,
            "current_timeframe": self._current_timeframe,
            "elapsed_seconds": elapsed,
            "paused_tasks": self._paused_tasks,
            "start_time": self._training_start_time.isoformat() if self._training_start_time else None
        }
    
    def register_enter_callback(self, callback: Callable):
        """Register a callback to run when training mode is entered."""
        self._callbacks_on_enter.append(callback)
    
    def register_exit_callback(self, callback: Callable):
        """Register a callback to run when training mode is exited."""
        self._callbacks_on_exit.append(callback)
    
    def should_skip_task(self, task_name: str) -> bool:
        """
        Check if a background task should be skipped due to training mode.
        
        Use this in background task loops:
            if training_mode_manager.should_skip_task('trading_bot_scan'):
                await asyncio.sleep(5)  # Short sleep and retry
                continue
        """
        if not self._training_active:
            return False
        
        # Tasks that should be skipped during training
        skip_tasks = {
            'trading_bot_scan',
            'trading_bot_scan_loop',
            'background_scanner',
            'learning_loop',
            'learning_loop_scheduler',
            'market_intel',
            'market_intel_scheduler',
            'shadow_signal',
            'shadow_signal_updates',
            'edge_decay_check',
            'daily_analysis',
            'ib_push_processing'
        }
        
        should_skip = task_name.lower() in skip_tasks or any(
            skip in task_name.lower() for skip in ['scan', 'scheduler', 'shadow', 'intel']
        )
        
        if should_skip:
            logger.debug(f"[TRAINING MODE] Skipping task: {task_name}")
        
        return should_skip


# Global singleton instance
training_mode_manager = TrainingModeManager()


def get_training_mode_manager() -> TrainingModeManager:
    """Get the global training mode manager instance."""
    return training_mode_manager
