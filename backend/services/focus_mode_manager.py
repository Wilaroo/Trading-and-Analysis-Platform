"""
Focus Mode Manager - Unified Resource Prioritization System

Manages different operational modes to optimize system resources:
- LIVE: Normal trading operations (default)
- COLLECTING: Historical data collection priority
- TRAINING: AI model training priority
- BACKTESTING: Simulation/backtest priority

When a focus mode is active:
- Non-essential services are paused or throttled
- Resources are dedicated to the priority task
- UI receives real-time status updates

Usage:
    from services.focus_mode_manager import focus_mode_manager
    
    # Set focus mode
    focus_mode_manager.set_mode('training', context={'timeframe': '30 mins'})
    
    # Check current mode
    mode = focus_mode_manager.get_mode()
    
    # Check if a task should run
    if focus_mode_manager.should_run_task('trading_bot_scan'):
        # Run the task
        pass
    
    # Reset to live mode
    focus_mode_manager.set_mode('live')
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable, List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class FocusMode(str, Enum):
    """Available focus modes"""
    LIVE = "live"              # Normal trading operations
    COLLECTING = "collecting"  # Historical data collection
    TRAINING = "training"      # AI model training
    BACKTESTING = "backtesting"  # Running simulations/backtests


# Task priority configuration for each mode
# Higher number = higher priority (0 = paused, 1-10 = throttled, 10 = full speed)
TASK_PRIORITIES = {
    FocusMode.LIVE: {
        # All tasks run normally in live mode
        'trading_bot_scan': 10,
        'ib_quote_streaming': 10,
        'ib_push_processing': 10,
        'websocket_updates': 10,
        'background_scanner': 8,
        'learning_loop': 5,
        'market_intel': 5,
        'shadow_signals': 5,
        'data_collection': 3,
        'ai_training': 0,  # Training doesn't run automatically in live mode
        'backtesting': 0,
    },
    FocusMode.COLLECTING: {
        # Data collection is priority
        'trading_bot_scan': 2,  # Reduced
        'ib_quote_streaming': 5,  # Reduced but needed for context
        'ib_push_processing': 3,
        'websocket_updates': 5,
        'background_scanner': 0,  # Paused
        'learning_loop': 0,  # Paused
        'market_intel': 0,  # Paused
        'shadow_signals': 0,  # Paused
        'data_collection': 10,  # Maximum priority
        'ai_training': 0,
        'backtesting': 0,
    },
    FocusMode.TRAINING: {
        # Training is priority - minimize IB usage
        'trading_bot_scan': 0,  # Paused
        'ib_quote_streaming': 2,  # Minimal
        'ib_push_processing': 0,  # Paused
        'websocket_updates': 3,  # Reduced
        'background_scanner': 0,  # Paused
        'learning_loop': 0,  # Paused
        'market_intel': 0,  # Paused
        'shadow_signals': 0,  # Paused
        'data_collection': 0,  # Paused
        'ai_training': 10,  # Maximum priority
        'backtesting': 0,
    },
    FocusMode.BACKTESTING: {
        # Backtesting is priority - no IB needed
        'trading_bot_scan': 0,  # Paused
        'ib_quote_streaming': 0,  # Paused
        'ib_push_processing': 0,  # Paused
        'websocket_updates': 3,  # Reduced for UI updates
        'background_scanner': 0,  # Paused
        'learning_loop': 0,  # Paused
        'market_intel': 0,  # Paused
        'shadow_signals': 0,  # Paused
        'data_collection': 0,  # Paused
        'ai_training': 0,
        'backtesting': 10,  # Maximum priority
    },
}

# Polling interval multipliers for each priority level
PRIORITY_INTERVAL_MULTIPLIERS = {
    0: None,   # Paused (infinite)
    1: 20.0,   # 20x slower
    2: 10.0,   # 10x slower
    3: 5.0,    # 5x slower
    4: 4.0,
    5: 3.0,    # 3x slower
    6: 2.5,
    7: 2.0,    # 2x slower
    8: 1.5,
    9: 1.2,
    10: 1.0,   # Normal speed
}


class FocusModeManager:
    """Manages system focus modes for resource prioritization."""
    
    def __init__(self):
        self._current_mode: FocusMode = FocusMode.LIVE
        self._mode_start_time: Optional[datetime] = None
        self._mode_context: Dict[str, Any] = {}
        self._active_job_id: Optional[str] = None
        self._callbacks_on_change: List[Callable] = []
        self._paused_services: List[str] = []
        
        # Progress tracking for active tasks
        self._progress: Dict[str, Any] = {
            'percent': 0,
            'message': '',
            'current_step': 0,
            'total_steps': 0,
            'details': {}
        }
    
    @property
    def mode(self) -> FocusMode:
        """Get current focus mode."""
        return self._current_mode
    
    def get_mode(self) -> str:
        """Get current focus mode as string."""
        return self._current_mode.value
    
    def set_mode(self, mode: str, context: Dict[str, Any] = None, job_id: str = None) -> Dict[str, Any]:
        """
        Set the system focus mode.
        
        Args:
            mode: One of 'live', 'collecting', 'training', 'backtesting'
            context: Optional context data (e.g., timeframe, job details)
            job_id: Optional job ID for tracking
            
        Returns:
            Status dict with success, message, and details
        """
        try:
            new_mode = FocusMode(mode.lower())
        except ValueError:
            return {
                'success': False,
                'error': f'Invalid mode: {mode}. Valid modes: {[m.value for m in FocusMode]}'
            }
        
        old_mode = self._current_mode
        
        if new_mode == old_mode and new_mode != FocusMode.LIVE:
            logger.warning(f"[FOCUS MODE] Already in {mode} mode")
            return {
                'success': False,
                'message': f'Already in {mode} mode',
                'current_mode': self._current_mode.value
            }
        
        # Update state
        self._current_mode = new_mode
        self._mode_start_time = datetime.now(timezone.utc) if new_mode != FocusMode.LIVE else None
        self._mode_context = context or {}
        self._active_job_id = job_id
        
        # Reset progress when entering a new mode
        self._progress = {
            'percent': 0,
            'message': f'Starting {mode} mode...',
            'current_step': 0,
            'total_steps': 0,
            'details': {}
        }
        
        # Determine which services to pause
        self._paused_services = self._get_paused_services(new_mode)
        
        logger.info(f"[FOCUS MODE] Changed: {old_mode.value} -> {new_mode.value}")
        logger.info(f"[FOCUS MODE] Paused services: {self._paused_services}")
        if context:
            logger.info(f"[FOCUS MODE] Context: {context}")
        
        # Notify subscribers
        for callback in self._callbacks_on_change:
            try:
                callback(old_mode.value, new_mode.value, context)
            except Exception as e:
                logger.error(f"Error in focus mode change callback: {e}")
        
        return {
            'success': True,
            'message': f'Focus mode set to {mode}',
            'previous_mode': old_mode.value,
            'current_mode': new_mode.value,
            'paused_services': self._paused_services,
            'context': self._mode_context,
            'start_time': self._mode_start_time.isoformat() if self._mode_start_time else None
        }
    
    def _get_paused_services(self, mode: FocusMode) -> List[str]:
        """Get list of services that should be paused in the given mode."""
        priorities = TASK_PRIORITIES.get(mode, {})
        return [task for task, priority in priorities.items() if priority == 0]
    
    def get_task_priority(self, task_name: str) -> int:
        """
        Get the priority level for a task in the current mode.
        
        Returns:
            Priority level 0-10 (0 = paused, 10 = full priority)
        """
        priorities = TASK_PRIORITIES.get(self._current_mode, {})
        
        # Direct match
        if task_name in priorities:
            return priorities[task_name]
        
        # Fuzzy match for task names containing keywords
        task_lower = task_name.lower()
        for key, priority in priorities.items():
            if key in task_lower or task_lower in key:
                return priority
        
        # Default: run at reduced priority in non-live modes
        return 10 if self._current_mode == FocusMode.LIVE else 5
    
    def should_run_task(self, task_name: str) -> bool:
        """
        Check if a task should run in the current focus mode.
        
        Returns:
            True if task should run, False if it should be paused
        """
        priority = self.get_task_priority(task_name)
        return priority > 0
    
    def get_interval_multiplier(self, task_name: str) -> float:
        """
        Get the polling interval multiplier for a task.
        
        Returns:
            Multiplier to apply to base polling interval (e.g., 2.0 = 2x slower)
            Returns None if task should be paused
        """
        priority = self.get_task_priority(task_name)
        return PRIORITY_INTERVAL_MULTIPLIERS.get(priority, 1.0)
    
    def get_adjusted_interval(self, base_interval_ms: int, task_name: str) -> Optional[int]:
        """
        Get adjusted polling interval for a task based on current focus mode.
        
        Args:
            base_interval_ms: Normal polling interval in milliseconds
            task_name: Name of the task
            
        Returns:
            Adjusted interval in ms, or None if task should be paused
        """
        multiplier = self.get_interval_multiplier(task_name)
        if multiplier is None:
            return None
        return int(base_interval_ms * multiplier)
    
    def update_progress(self, percent: int = None, message: str = None, 
                       current_step: int = None, total_steps: int = None,
                       details: Dict = None):
        """Update progress for the current focus mode task."""
        if percent is not None:
            self._progress['percent'] = min(100, max(0, percent))
        if message is not None:
            self._progress['message'] = message
        if current_step is not None:
            self._progress['current_step'] = current_step
        if total_steps is not None:
            self._progress['total_steps'] = total_steps
        if details is not None:
            self._progress['details'].update(details)
    
    def get_status(self) -> Dict[str, Any]:
        """Get complete focus mode status for API/UI."""
        elapsed = None
        if self._mode_start_time:
            elapsed = (datetime.now(timezone.utc) - self._mode_start_time).total_seconds()
        
        return {
            'mode': self._current_mode.value,
            'is_live': self._current_mode == FocusMode.LIVE,
            'start_time': self._mode_start_time.isoformat() if self._mode_start_time else None,
            'elapsed_seconds': elapsed,
            'context': self._mode_context,
            'job_id': self._active_job_id,
            'paused_services': self._paused_services,
            'progress': self._progress,
            'task_priorities': {
                task: self.get_task_priority(task) 
                for task in TASK_PRIORITIES.get(self._current_mode, {}).keys()
            }
        }
    
    def register_change_callback(self, callback: Callable):
        """Register a callback for mode changes. Callback receives (old_mode, new_mode, context)."""
        self._callbacks_on_change.append(callback)
        return lambda: self._callbacks_on_change.remove(callback)
    
    def reset_to_live(self, result: Dict = None) -> Dict[str, Any]:
        """
        Reset to live mode (convenience method).
        
        Args:
            result: Optional result from the completed task
        """
        response = self.set_mode('live')
        if result:
            response['completed_task_result'] = result
        return response


# Global singleton instance
focus_mode_manager = FocusModeManager()


def get_focus_mode_manager() -> FocusModeManager:
    """Get the global focus mode manager instance."""
    return focus_mode_manager
