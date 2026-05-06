"""
Execution Tracker Service - Tracks trade execution quality

This service monitors and records how well trades are executed:
- Entry quality (slippage, timing, chasing)
- Exit quality (R-capture, timing, scale-outs)
- Stop management (adjustments, trailing stops)

Used to identify execution patterns and areas for improvement.
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from models.learning_models import ExecutionMetrics

logger = logging.getLogger(__name__)


class ExecutionTrackerService:
    """Tracks and analyzes trade execution quality"""
    
    def __init__(self):
        self._db = None
        self._alpaca_service = None
        
        # Track active trade executions
        self._active_executions: Dict[str, ExecutionMetrics] = {}
        
    def set_services(self, db=None, alpaca_service=None):
        """Wire up dependencies"""
        self._db = db
        self._alpaca_service = alpaca_service
        
    def start_tracking(
        self,
        trade_id: str,
        intended_entry: float,
        intended_size: int,
        planned_r: float = 2.0
    ) -> ExecutionMetrics:
        """
        Start tracking execution for a new trade.
        Called when a trade is initiated/submitted.
        """
        metrics = ExecutionMetrics()
        metrics.intended_entry = intended_entry
        metrics.intended_size = intended_size
        metrics.planned_r = planned_r
        
        self._active_executions[trade_id] = metrics
        logger.debug(f"Started execution tracking for trade {trade_id}")
        
        return metrics
        
    def record_entry(
        self,
        trade_id: str,
        actual_entry: float,
        actual_size: int,
        size_adjustment_reason: Optional[str] = None
    ) -> Optional[ExecutionMetrics]:
        """
        Record the actual entry execution.
        Called when a trade fill is confirmed.
        """
        metrics = self._active_executions.get(trade_id)
        if metrics is None:
            # Create new metrics if tracking wasn't started
            metrics = ExecutionMetrics()
            metrics.intended_entry = actual_entry
            metrics.intended_size = actual_size
            self._active_executions[trade_id] = metrics
            
        metrics.entry_price = actual_entry
        metrics.position_size = actual_size
        
        # Calculate entry slippage
        if metrics.intended_entry > 0:
            metrics.entry_slippage = actual_entry - metrics.intended_entry
            metrics.entry_slippage_percent = (metrics.entry_slippage / metrics.intended_entry) * 100
            
            # Detect if entry was chased (bought higher than intended for longs)
            if metrics.entry_slippage_percent > 0.2:  # More than 0.2% slippage
                metrics.chased_entry = True
                
        if size_adjustment_reason:
            metrics.size_adjustment_reason = size_adjustment_reason
            
        # Calculate entry timing score based on slippage
        if abs(metrics.entry_slippage_percent) < 0.1:
            metrics.entry_timing_score = 0.9
        elif abs(metrics.entry_slippage_percent) < 0.2:
            metrics.entry_timing_score = 0.7
        elif abs(metrics.entry_slippage_percent) < 0.3:
            metrics.entry_timing_score = 0.5
        else:
            metrics.entry_timing_score = 0.3
            
        logger.debug(f"Recorded entry for trade {trade_id}: ${actual_entry:.2f}, slippage: {metrics.entry_slippage_percent:.2f}%")
        
        return metrics
        
    def record_stop_adjustment(
        self,
        trade_id: str,
        old_stop: float,
        new_stop: float,
        reason: str = ""
    ):
        """Record a stop adjustment"""
        metrics = self._active_executions.get(trade_id)
        if metrics is None:
            return
            
        metrics.stop_adjustments += 1
        
        if reason == "breakeven":
            metrics.moved_to_breakeven = True
        elif reason == "trailing":
            metrics.trailing_activated = True
            
    def record_scale_out(
        self,
        trade_id: str,
        scale_price: float,
        scale_shares: int,
        r_captured: float
    ):
        """Record a partial exit / scale-out"""
        metrics = self._active_executions.get(trade_id)
        if metrics is None:
            return
            
        metrics.scaled_out = True
        metrics.scale_out_count += 1
        metrics.scale_out_r_capture.append(r_captured)
        
        logger.debug(f"Recorded scale-out for trade {trade_id}: {scale_shares} shares at ${scale_price:.2f}, {r_captured:.2f}R")
        
    def record_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        entry_time: str,
        expected_hold_minutes: int = 30
    ) -> Optional[ExecutionMetrics]:
        """
        Record the final exit and calculate execution quality.
        Called when a trade is closed.
        """
        metrics = self._active_executions.get(trade_id)
        if metrics is None:
            logger.warning(f"No execution tracking found for trade {trade_id}")
            return None
            
        metrics.exit_price = exit_price
        metrics.exit_reason = exit_reason
        
        # Calculate exit slippage (vs intended target or stop)
        if metrics.intended_exit > 0:
            metrics.exit_slippage = exit_price - metrics.intended_exit
            metrics.exit_slippage_percent = (metrics.exit_slippage / metrics.intended_exit) * 100
            
        # Check if stopped out
        if exit_reason in ("stop", "stop_loss", "trailing_stop"):
            metrics.stopped_out = True
            
        # Calculate actual R-multiple
        if metrics.entry_price > 0:
            risk_per_share = abs(metrics.entry_price - metrics.intended_exit) if metrics.intended_exit > 0 else 1.0
            if risk_per_share == 0:
                risk_per_share = metrics.entry_price * 0.02  # Default 2% risk
                
            pnl_per_share = exit_price - metrics.entry_price
            metrics.actual_r = pnl_per_share / risk_per_share if risk_per_share > 0 else 0
            
            # Calculate R-capture percentage
            if metrics.planned_r > 0:
                metrics.r_capture_percent = (metrics.actual_r / metrics.planned_r) * 100
                
        # Calculate hold time
        try:
            entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            exit_dt = datetime.now(timezone.utc)
            metrics.hold_time_minutes = int((exit_dt - entry_dt).total_seconds() / 60)
            
            metrics.expected_hold_time_minutes = expected_hold_minutes
            
            # Detect early/late exits
            if metrics.actual_r > 0:  # Winning trade
                if metrics.hold_time_minutes < expected_hold_minutes * 0.3:
                    metrics.exited_too_early = True
            else:  # Losing trade
                if metrics.hold_time_minutes > expected_hold_minutes * 2:
                    metrics.exited_too_late = True
                    
        except Exception as e:
            logger.warning(f"Error calculating hold time: {e}")
            
        # Calculate overall execution quality score
        metrics.calculate_quality_score()
        
        logger.info(f"Execution quality for trade {trade_id}: {metrics.execution_quality_score:.2f} "
                   f"(R: {metrics.actual_r:.2f}, R-capture: {metrics.r_capture_percent:.0f}%)")
        
        return metrics
        
    def get_metrics(self, trade_id: str) -> Optional[ExecutionMetrics]:
        """Get execution metrics for a trade"""
        return self._active_executions.get(trade_id)
        
    def finalize_and_remove(self, trade_id: str) -> Optional[ExecutionMetrics]:
        """Get final metrics and remove from active tracking"""
        metrics = self._active_executions.pop(trade_id, None)
        return metrics
        
    def analyze_execution_patterns(self, outcomes: List[Dict]) -> Dict[str, Any]:
        """
        Analyze execution patterns across multiple trades.
        Used for daily/weekly analysis to identify improvement areas.
        """
        if not outcomes:
            return {}
            
        analysis = {
            "total_trades": len(outcomes),
            "entry_analysis": {},
            "exit_analysis": {},
            "timing_analysis": {},
            "recommendations": []
        }
        
        # Entry analysis
        slippages = []
        chase_count = 0
        for outcome in outcomes:
            exec_data = outcome.get('execution', {})
            if exec_data:
                slippages.append(exec_data.get('entry_slippage_percent', 0))
                if exec_data.get('chased_entry', False):
                    chase_count += 1
                    
        if slippages:
            analysis["entry_analysis"] = {
                "avg_slippage_percent": sum(slippages) / len(slippages),
                "max_slippage_percent": max(slippages),
                "chase_rate": chase_count / len(outcomes),
                "negative_slippage_rate": sum(1 for s in slippages if s < 0) / len(slippages)
            }
            
            if analysis["entry_analysis"]["chase_rate"] > 0.3:
                analysis["recommendations"].append(
                    "You're chasing entries too often (>30%). Consider using limit orders or waiting for pullbacks."
                )
            if analysis["entry_analysis"]["avg_slippage_percent"] > 0.2:
                analysis["recommendations"].append(
                    f"Average entry slippage is high ({analysis['entry_analysis']['avg_slippage_percent']:.2f}%). "
                    "Review your entry timing and order types."
                )
                
        # Exit analysis
        r_captures = []
        early_exits = 0
        late_exits = 0
        
        for outcome in outcomes:
            exec_data = outcome.get('execution', {})
            if exec_data:
                r_cap = exec_data.get('r_capture_percent', 0)
                if r_cap > 0:
                    r_captures.append(r_cap)
                if exec_data.get('exited_too_early', False):
                    early_exits += 1
                if exec_data.get('exited_too_late', False):
                    late_exits += 1
                    
        if r_captures:
            analysis["exit_analysis"] = {
                "avg_r_capture_percent": sum(r_captures) / len(r_captures),
                "full_target_hit_rate": sum(1 for r in r_captures if r >= 80) / len(r_captures),
                "early_exit_rate": early_exits / len(outcomes),
                "late_exit_rate": late_exits / len(outcomes)
            }
            
            if analysis["exit_analysis"]["avg_r_capture_percent"] < 50:
                analysis["recommendations"].append(
                    f"Average R-capture is low ({analysis['exit_analysis']['avg_r_capture_percent']:.0f}%). "
                    "You're leaving money on the table. Consider using trailing stops."
                )
            if analysis["exit_analysis"]["early_exit_rate"] > 0.4:
                analysis["recommendations"].append(
                    "You're exiting too early on >40% of winning trades. Trust your thesis and let winners run."
                )
                
        # Timing analysis
        hold_times = []
        for outcome in outcomes:
            exec_data = outcome.get('execution', {})
            if exec_data:
                hold_time = exec_data.get('hold_time_minutes', 0)
                if hold_time > 0:
                    hold_times.append(hold_time)
                    
        if hold_times:
            analysis["timing_analysis"] = {
                "avg_hold_minutes": sum(hold_times) / len(hold_times),
                "min_hold_minutes": min(hold_times),
                "max_hold_minutes": max(hold_times)
            }
            
        return analysis


# Singleton instance
_execution_tracker: Optional[ExecutionTrackerService] = None


def get_execution_tracker() -> ExecutionTrackerService:
    """Get the singleton execution tracker service"""
    global _execution_tracker
    if _execution_tracker is None:
        _execution_tracker = ExecutionTrackerService()
    return _execution_tracker


def init_execution_tracker(db=None, alpaca_service=None) -> ExecutionTrackerService:
    """Initialize the execution tracker with dependencies"""
    service = get_execution_tracker()
    service.set_services(db=db, alpaca_service=alpaca_service)
    return service
