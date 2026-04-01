"""
Trading Scheduler Service - Automated Daily/Weekly Tasks

Schedules and runs automated trading analysis tasks:
- Daily Analysis: Runs at 4:00 PM ET (market close)
- Weekly Report Generation: Runs Friday 4:30 PM ET
- Shadow Mode Updates: Runs every 5 minutes during market hours

Uses APScheduler for background job scheduling.
"""

import logging
import asyncio
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import os

logger = logging.getLogger(__name__)


class ScheduledTaskType(str, Enum):
    DAILY_ANALYSIS = "daily_analysis"
    WEEKLY_REPORT = "weekly_report"
    SHADOW_UPDATE = "shadow_update"
    EDGE_DECAY_CHECK = "edge_decay_check"
    LEARNING_SYNC = "learning_sync"
    IB_COLLECTION_RESUME = "ib_collection_resume"


@dataclass
class ScheduledTaskResult:
    """Result of a scheduled task execution"""
    task_type: str
    success: bool
    started_at: str
    completed_at: str
    duration_seconds: float
    result_summary: str
    error: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class TradingScheduler:
    """
    Manages scheduled trading analysis tasks.
    
    Tasks:
    1. Daily Analysis (4:00 PM ET): Run all Medium Learning services
    2. Weekly Report (Friday 4:30 PM): Generate weekly intelligence report
    3. Shadow Updates (5 min): Update shadow signal outcomes during market hours
    4. Edge Decay Check (Daily): Check for strategy decay
    """
    
    # Market hours (ET)
    MARKET_OPEN_HOUR = 9
    MARKET_OPEN_MINUTE = 30
    MARKET_CLOSE_HOUR = 16
    MARKET_CLOSE_MINUTE = 0
    
    def __init__(self):
        self._db = None
        self._task_log_col = None
        self._scheduler = None
        self._is_running = False
        
        # Service references
        self._medium_learning_services = {}
        self._weekly_report_service = None
        self._shadow_mode_service = None
        self._shadow_tracker = None
        self._edge_decay_service = None
        
        # Task callbacks
        self._task_callbacks: Dict[str, Callable] = {}
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._task_log_col = db['scheduled_task_logs']
            
    def set_services(
        self,
        calibration_service=None,
        context_performance_service=None,
        confirmation_validator_service=None,
        playbook_performance_service=None,
        edge_decay_service=None,
        weekly_report_service=None,
        shadow_mode_service=None,
        shadow_tracker=None
    ):
        """Wire up all services needed for scheduled tasks"""
        if calibration_service is not None:
            self._medium_learning_services['calibration'] = calibration_service
        if context_performance_service is not None:
            self._medium_learning_services['context_performance'] = context_performance_service
        if confirmation_validator_service is not None:
            self._medium_learning_services['confirmation'] = confirmation_validator_service
        if playbook_performance_service is not None:
            self._medium_learning_services['playbook'] = playbook_performance_service
        if edge_decay_service is not None:
            self._edge_decay_service = edge_decay_service
            self._medium_learning_services['edge_decay'] = edge_decay_service
        if weekly_report_service is not None:
            self._weekly_report_service = weekly_report_service
        if shadow_mode_service is not None:
            self._shadow_mode_service = shadow_mode_service
        if shadow_tracker is not None:
            self._shadow_tracker = shadow_tracker
            
    def start(self):
        """Start the scheduler"""
        if self._is_running:
            return
            
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger
            
            self._scheduler = AsyncIOScheduler(timezone='US/Eastern')
            
            # 1. Daily Analysis - 4:00 PM ET (Monday-Friday)
            self._scheduler.add_job(
                self._run_daily_analysis,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour=16,
                    minute=0,
                    timezone='US/Eastern'
                ),
                id='daily_analysis',
                name='Daily Analysis',
                replace_existing=True
            )
            
            # 2. Weekly Report - Friday 4:30 PM ET
            self._scheduler.add_job(
                self._run_weekly_report,
                CronTrigger(
                    day_of_week='fri',
                    hour=16,
                    minute=30,
                    timezone='US/Eastern'
                ),
                id='weekly_report',
                name='Weekly Report Generation',
                replace_existing=True
            )
            
            # 3. Shadow Signal Updates - Every 5 minutes during market hours
            self._scheduler.add_job(
                self._run_shadow_update,
                IntervalTrigger(minutes=5),
                id='shadow_update',
                name='Shadow Signal Update',
                replace_existing=True
            )
            
            # 4. Edge Decay Check - Daily at 4:15 PM ET
            self._scheduler.add_job(
                self._run_edge_decay_check,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour=16,
                    minute=15,
                    timezone='US/Eastern'
                ),
                id='edge_decay_check',
                name='Edge Decay Check',
                replace_existing=True
            )
            
            # 5. Learning Sync - Daily at 5:00 PM ET (after market close)
            self._scheduler.add_job(
                self._run_learning_sync,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour=17,
                    minute=0,
                    timezone='US/Eastern'
                ),
                id='learning_sync',
                name='Learning Connections Sync',
                replace_existing=True
            )
            
            # 6. IB Collection Auto-Resume - Daily at 2:15 AM ET (after IB Gateway restarts ~2:00 AM)
            self._scheduler.add_job(
                self._run_ib_collection_resume,
                CronTrigger(
                    hour=2,
                    minute=15,
                    timezone='US/Eastern'
                ),
                id='ib_collection_resume',
                name='IB Collection Auto-Resume',
                replace_existing=True
            )
            
            self._scheduler.start()
            self._is_running = True
            logger.info("Trading scheduler started")
            logger.info("  - Daily Analysis: 4:00 PM ET (Mon-Fri)")
            logger.info("  - Weekly Report: Friday 4:30 PM ET")
            logger.info("  - Shadow Updates: Every 5 min")
            logger.info("  - Edge Decay Check: 4:15 PM ET (Mon-Fri)")
            logger.info("  - Learning Sync: 5:00 PM ET (Mon-Fri)")
            logger.info("  - IB Collection Resume: 2:15 AM ET (Daily)")
            
        except ImportError:
            logger.warning("APScheduler not installed. Scheduler disabled.")
        except Exception as e:
            logger.error(f"Error starting scheduler: {e}")
            
    def stop(self):
        """Stop the scheduler"""
        if self._scheduler and self._is_running:
            self._scheduler.shutdown()
            self._is_running = False
            logger.info("Trading scheduler stopped")
            
    def is_market_hours(self) -> bool:
        """Check if current time is during market hours (ET)"""
        try:
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
            
            # Check if weekday
            if now.weekday() >= 5:  # Saturday or Sunday
                return False
                
            # Check time
            market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
            
            return market_open <= now <= market_close
        except Exception:
            return False
            
    async def _run_daily_analysis(self):
        """Run daily analysis (Medium Learning services)"""
        # Skip during training
        try:
            from services.focus_mode_manager import focus_mode_manager
            if focus_mode_manager.get_mode() != "live":
                return
        except Exception:
            pass

        start_time = datetime.now(timezone.utc)
        result = ScheduledTaskResult(
            task_type=ScheduledTaskType.DAILY_ANALYSIS.value,
            success=False,
            started_at=start_time.isoformat(),
            completed_at="",
            duration_seconds=0,
            result_summary=""
        )
        
        try:
            logger.info("Running scheduled daily analysis...")
            
            summaries = []
            
            # Run calibration analysis
            if 'calibration' in self._medium_learning_services:
                try:
                    recs = await self._medium_learning_services['calibration'].analyze_and_recommend(30)
                    summaries.append(f"Calibration: {len(recs)} recommendations")
                except Exception as e:
                    summaries.append(f"Calibration: Error - {e}")
                    
            # Update context performance
            if 'context_performance' in self._medium_learning_services:
                try:
                    svc = self._medium_learning_services['context_performance']
                    if svc._trade_outcomes_col is not None:
                        trades = list(svc._trade_outcomes_col.find({}).sort("created_at", -1).limit(500))
                        updated = await svc.update_context_performance(trades)
                        summaries.append(f"Context Performance: {updated} contexts updated")
                except Exception as e:
                    summaries.append(f"Context Performance: Error - {e}")
                    
            # Run confirmation validation
            if 'confirmation' in self._medium_learning_services:
                try:
                    report = await self._medium_learning_services['confirmation'].validate_confirmations(30)
                    summaries.append(f"Confirmations: {report.total_trades_analyzed} trades analyzed")
                except Exception as e:
                    summaries.append(f"Confirmations: Error - {e}")
                    
            # Update playbook performance
            if 'playbook' in self._medium_learning_services:
                try:
                    result_data = await self._medium_learning_services['playbook'].update_playbook_performance(lookback_days=90)
                    summaries.append(f"Playbooks: {result_data.get('playbooks_updated', 0)} updated")
                except Exception as e:
                    summaries.append(f"Playbooks: Error - {e}")
                    
            result.success = True
            result.result_summary = "; ".join(summaries)
            logger.info(f"Daily analysis complete: {result.result_summary}")
            
        except Exception as e:
            result.error = str(e)
            result.result_summary = f"Failed: {e}"
            logger.error(f"Daily analysis failed: {e}")
            
        finally:
            end_time = datetime.now(timezone.utc)
            result.completed_at = end_time.isoformat()
            result.duration_seconds = (end_time - start_time).total_seconds()
            self._log_task_result(result)
            
    async def _run_weekly_report(self):
        """Generate weekly intelligence report"""
        # Skip during training
        try:
            from services.focus_mode_manager import focus_mode_manager
            if focus_mode_manager.get_mode() != "live":
                return
        except Exception:
            pass

        start_time = datetime.now(timezone.utc)
        result = ScheduledTaskResult(
            task_type=ScheduledTaskType.WEEKLY_REPORT.value,
            success=False,
            started_at=start_time.isoformat(),
            completed_at="",
            duration_seconds=0,
            result_summary=""
        )
        
        try:
            logger.info("Running scheduled weekly report generation...")
            
            if self._weekly_report_service:
                report = await self._weekly_report_service.generate_weekly_report(force=True)
                result.success = True
                result.result_summary = f"Generated report {report.id} for Week {report.week_number}"
                logger.info(f"Weekly report generated: {report.id}")
            else:
                result.result_summary = "Weekly report service not configured"
                
        except Exception as e:
            result.error = str(e)
            result.result_summary = f"Failed: {e}"
            logger.error(f"Weekly report generation failed: {e}")
            
        finally:
            end_time = datetime.now(timezone.utc)
            result.completed_at = end_time.isoformat()
            result.duration_seconds = (end_time - start_time).total_seconds()
            self._log_task_result(result)
            
    async def _run_shadow_update(self):
        """Update shadow signal outcomes and shadow tracker decisions"""
        # Skip during training — free up event loop and DB resources
        try:
            from services.focus_mode_manager import focus_mode_manager
            if focus_mode_manager.get_mode() != "live":
                return
        except Exception:
            pass

        # Only run during market hours
        if not self.is_market_hours():
            return
            
        try:
            if self._shadow_mode_service:
                result = await self._shadow_mode_service.update_signal_outcomes()
                if result.get("updated", 0) > 0:
                    logger.info(f"Shadow signals updated: {result.get('updated')} outcomes resolved")
        except Exception as e:
            logger.warning(f"Shadow update error: {e}")
        
        # Also evaluate shadow tracker (AI consultation) pending decisions
        try:
            if self._shadow_tracker:
                result = await self._shadow_tracker.track_pending_outcomes()
                if result.get("updated", 0) > 0:
                    logger.info(f"Shadow tracker: {result.get('updated')} decision outcomes resolved")
        except Exception as e:
            logger.warning(f"Shadow tracker outcome error: {e}")
            
    async def _run_edge_decay_check(self):
        """Check for edge decay"""
        # Skip during training
        try:
            from services.focus_mode_manager import focus_mode_manager
            if focus_mode_manager.get_mode() != "live":
                return
        except Exception:
            pass

        start_time = datetime.now(timezone.utc)
        result = ScheduledTaskResult(
            task_type=ScheduledTaskType.EDGE_DECAY_CHECK.value,
            success=False,
            started_at=start_time.isoformat(),
            completed_at="",
            duration_seconds=0,
            result_summary=""
        )
        
        try:
            logger.info("Running scheduled edge decay check...")
            
            if self._edge_decay_service:
                report = await self._edge_decay_service.analyze_all_edges()
                
                result.success = True
                result.result_summary = (
                    f"Analyzed {report.total_edges_tracked} edges. "
                    f"Decaying: {report.edges_decaying}, "
                    f"Critical alerts: {len(report.critical_alerts)}"
                )
                
                if report.critical_alerts:
                    logger.warning(f"Edge decay critical alerts: {[a['edge'] for a in report.critical_alerts]}")
            else:
                result.result_summary = "Edge decay service not configured"
                
        except Exception as e:
            result.error = str(e)
            result.result_summary = f"Failed: {e}"
            logger.error(f"Edge decay check failed: {e}")
            
        finally:
            end_time = datetime.now(timezone.utc)
            result.completed_at = end_time.isoformat()
            result.duration_seconds = (end_time - start_time).total_seconds()
            self._log_task_result(result)
            
    async def _run_learning_sync(self):
        """
        Run daily learning connections sync.
        
        This synchronizes data between all learning systems:
        - Simulation results → Model retraining
        - Shadow decisions → Module weight calibration
        - Alert outcomes → Scanner threshold tuning
        - Predictions → Outcome verification
        """
        start_time = datetime.now(timezone.utc)
        result = ScheduledTaskResult(
            task_type=ScheduledTaskType.LEARNING_SYNC.value,
            success=False,
            started_at=start_time.isoformat(),
            completed_at="",
            duration_seconds=0,
            result_summary=""
        )
        
        try:
            logger.info("Running scheduled learning sync...")
            
            # Import here to avoid circular imports
            from services.learning_connectors_service import get_learning_connectors
            
            learning_connectors = get_learning_connectors()
            sync_result = await learning_connectors.run_full_sync()
            
            if sync_result.get("success"):
                # Count successful syncs
                sync_results = sync_result.get("sync_results", {})
                successful = sum(1 for r in sync_results.values() if r.get("success"))
                total = len(sync_results)
                
                result.success = True
                result.result_summary = (
                    f"Learning sync completed: {successful}/{total} connections synced. "
                    f"Timestamp: {sync_result.get('timestamp', 'N/A')}"
                )
                
                # Log individual results
                for conn_name, conn_result in sync_results.items():
                    if conn_result.get("success"):
                        logger.info(f"  ✓ {conn_name}: Success")
                    else:
                        logger.warning(f"  ✗ {conn_name}: {conn_result.get('error', 'Unknown error')}")
            else:
                result.result_summary = f"Sync failed: {sync_result.get('error', 'Unknown error')}"
                
        except Exception as e:
            result.error = str(e)
            result.result_summary = f"Learning sync failed: {e}"
            logger.error(f"Learning sync failed: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            end_time = datetime.now(timezone.utc)
            result.completed_at = end_time.isoformat()
            result.duration_seconds = (end_time - start_time).total_seconds()
            self._log_task_result(result)
            logger.info(f"Learning sync completed in {result.duration_seconds:.1f}s: {result.result_summary}")
    
    async def _run_ib_collection_resume(self):
        """
        Auto-resume IB historical data collection after IB Gateway restarts.
        
        IB Gateway typically restarts around 2:00 AM ET daily. This task runs at 2:15 AM ET
        to check if there are pending queue items and resume collection if:
        1. IB Gateway is connected
        2. There are pending items in the collection queue
        """
        start_time = datetime.now(timezone.utc)
        result = ScheduledTaskResult(
            task_type=ScheduledTaskType.IB_COLLECTION_RESUME.value,
            success=False,
            started_at=start_time.isoformat(),
            completed_at="",
            duration_seconds=0,
            result_summary=""
        )
        
        try:
            logger.info("Running scheduled IB collection auto-resume check...")
            
            # Import services
            from services.ib_service import get_ib_service
            from services.ib_historical_collector import get_historical_collector
            from services.historical_data_queue_service import get_historical_data_queue_service
            
            ib_service = get_ib_service()
            collector = get_historical_collector()
            
            # Check IB connection
            ib_connected = ib_service.is_connected if ib_service else False
            
            if not ib_connected:
                result.result_summary = "IB Gateway not connected - skipping resume"
                logger.info(result.result_summary)
                result.success = True  # Not a failure, just nothing to do
                return
            
            # Check for pending items in queue
            if self._db is None:
                result.result_summary = "Database not initialized"
                return
                
            queue_service = get_historical_data_queue_service(self._db)
            stats = queue_service.get_overall_queue_stats()
            pending_count = stats.get("pending", 0)
            
            if pending_count == 0:
                result.result_summary = "No pending items in queue - nothing to resume"
                logger.info(result.result_summary)
                result.success = True
                return
            
            # Resume collection
            logger.info(f"Found {pending_count} pending items - resuming collection...")
            resume_result = await collector.resume_monitoring()
            
            if resume_result.get("success"):
                result.success = True
                result.result_summary = f"Resumed collection: {pending_count} pending, {stats.get('completed', 0)} completed"
                logger.info(f"IB collection auto-resumed: {result.result_summary}")
            else:
                result.result_summary = f"Resume failed: {resume_result.get('error', 'Unknown error')}"
                logger.error(result.result_summary)
                
        except Exception as e:
            result.error = str(e)
            result.result_summary = f"Auto-resume failed: {e}"
            logger.error(f"IB collection auto-resume failed: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            end_time = datetime.now(timezone.utc)
            result.completed_at = end_time.isoformat()
            result.duration_seconds = (end_time - start_time).total_seconds()
            self._log_task_result(result)
            logger.info(f"IB collection resume check completed in {result.duration_seconds:.1f}s: {result.result_summary}")
            
    def _log_task_result(self, result: ScheduledTaskResult):
        """Log task result to database"""
        if self._task_log_col is not None:
            try:
                self._task_log_col.insert_one(result.to_dict())
            except Exception as e:
                logger.warning(f"Error logging task result: {e}")
                
    async def run_task_now(self, task_type: str) -> Dict[str, Any]:
        """Manually trigger a scheduled task"""
        if task_type == ScheduledTaskType.DAILY_ANALYSIS.value:
            await self._run_daily_analysis()
        elif task_type == ScheduledTaskType.WEEKLY_REPORT.value:
            await self._run_weekly_report()
        elif task_type == ScheduledTaskType.EDGE_DECAY_CHECK.value:
            await self._run_edge_decay_check()
        elif task_type == ScheduledTaskType.SHADOW_UPDATE.value:
            await self._run_shadow_update()
        elif task_type == ScheduledTaskType.LEARNING_SYNC.value:
            await self._run_learning_sync()
        elif task_type == ScheduledTaskType.IB_COLLECTION_RESUME.value:
            await self._run_ib_collection_resume()
        else:
            return {"success": False, "error": f"Unknown task type: {task_type}"}
            
        return {"success": True, "message": f"Task {task_type} triggered"}
        
    def get_task_history(self, task_type: str = None, limit: int = 20) -> list:
        """Get history of scheduled task executions"""
        if self._task_log_col is None:
            return []
            
        query = {}
        if task_type:
            query["task_type"] = task_type
            
        docs = list(
            self._task_log_col
            .find(query, {"_id": 0})
            .sort("started_at", -1)
            .limit(limit)
        )
        
        return docs
        
    def get_scheduled_jobs(self) -> list:
        """Get list of scheduled jobs"""
        if not self._scheduler:
            return []
            
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })
            
        return jobs
        
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status"""
        return {
            "is_running": self._is_running,
            "is_market_hours": self.is_market_hours(),
            "jobs": self.get_scheduled_jobs(),
            "services_configured": {
                "medium_learning": list(self._medium_learning_services.keys()),
                "weekly_report": self._weekly_report_service is not None,
                "shadow_mode": self._shadow_mode_service is not None,
                "edge_decay": self._edge_decay_service is not None
            }
        }


# Singleton
_trading_scheduler: Optional[TradingScheduler] = None


def get_trading_scheduler() -> TradingScheduler:
    global _trading_scheduler
    if _trading_scheduler is None:
        _trading_scheduler = TradingScheduler()
    return _trading_scheduler


def init_trading_scheduler(
    db=None,
    calibration_service=None,
    context_performance_service=None,
    confirmation_validator_service=None,
    playbook_performance_service=None,
    edge_decay_service=None,
    weekly_report_service=None,
    shadow_mode_service=None,
    shadow_tracker=None,
    start: bool = True
) -> TradingScheduler:
    scheduler = get_trading_scheduler()
    if db is not None:
        scheduler.set_db(db)
    scheduler.set_services(
        calibration_service=calibration_service,
        context_performance_service=context_performance_service,
        confirmation_validator_service=confirmation_validator_service,
        playbook_performance_service=playbook_performance_service,
        edge_decay_service=edge_decay_service,
        weekly_report_service=weekly_report_service,
        shadow_mode_service=shadow_mode_service,
        shadow_tracker=shadow_tracker
    )
    if start:
        scheduler.start()
    return scheduler
