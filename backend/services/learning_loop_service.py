"""
Learning Loop Service - Orchestrates the Three-Speed Learning Architecture

This is the main service that coordinates:
- Fast Learning: Real-time updates after every trade
- Medium Learning: End-of-day analysis and calibration  
- Slow Learning: Weekly backtesting and verification

It integrates with:
- TradeContextService: Captures context at trade time
- ExecutionTrackerService: Tracks execution quality
- GracefulDegradationService: Handles service failures

Data flows:
1. Scanner generates alert → Context captured
2. Trade executed → Execution tracked
3. Trade closed → Outcome recorded
4. EOD → Stats aggregated, profile updated
5. Weekly → Backtesting, calibration
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import asdict
import asyncio
import uuid

from models.learning_models import (
    TradeContext,
    ExecutionMetrics,
    TradeOutcome,
    LearningStats,
    TraderProfile,
    TiltState,
    CalibrationEntry,
    ContextDimension,
    MarketRegime,
    TimeOfDay
)
from services.trade_context_service import get_trade_context_service
from services.execution_tracker_service import get_execution_tracker
from services.graceful_degradation import get_degradation_service

logger = logging.getLogger(__name__)


class LearningLoopService:
    """
    Orchestrates the Three-Speed Learning Architecture.
    
    Collections used:
    - trade_outcomes: Complete trade records with context and execution
    - learning_stats: Aggregated statistics by context
    - calibration_log: History of threshold adjustments
    - trader_profile: Current trader profile for RAG
    """
    
    def __init__(self):
        self._db = None
        self._trade_outcomes_col = None
        self._learning_stats_col = None
        self._calibration_log_col = None
        self._trader_profile_col = None
        
        # Service dependencies
        self._context_service = None
        self._execution_tracker = None
        self._degradation_service = None
        
        # Current session tracking
        self._session_trades: List[str] = []  # Trade IDs in current session
        self._current_profile: Optional[TraderProfile] = None
        
        # Pending outcomes waiting for context
        self._pending_contexts: Dict[str, TradeContext] = {}
        
    def set_db(self, db):
        """Set MongoDB database connection"""
        self._db = db
        if db is not None:
            self._trade_outcomes_col = db['trade_outcomes']
            self._learning_stats_col = db['learning_stats']
            self._calibration_log_col = db['calibration_log']
            self._trader_profile_col = db['trader_profile']
            
            # Create indexes for efficient queries
            self._create_indexes()
            
    def _create_indexes(self):
        """Create MongoDB indexes for efficient queries"""
        try:
            # Trade outcomes indexes
            self._trade_outcomes_col.create_index([("symbol", 1), ("created_at", -1)])
            self._trade_outcomes_col.create_index([("setup_type", 1), ("outcome", 1)])
            self._trade_outcomes_col.create_index([("context.market_regime", 1), ("outcome", 1)])
            self._trade_outcomes_col.create_index([("context.time_of_day", 1), ("outcome", 1)])
            self._trade_outcomes_col.create_index([("reviewed", 1)])
            
            # Learning stats indexes
            self._learning_stats_col.create_index([("context_key", 1)], unique=True)
            self._learning_stats_col.create_index([("setup_type", 1)])
            
            # Calibration log indexes
            self._calibration_log_col.create_index([("parameter_name", 1), ("timestamp", -1)])
            
            logger.info("Learning loop MongoDB indexes created")
            
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
            
    def set_services(
        self,
        context_service=None,
        execution_tracker=None,
        degradation_service=None
    ):
        """Wire up service dependencies"""
        self._context_service = context_service or get_trade_context_service()
        self._execution_tracker = execution_tracker or get_execution_tracker()
        self._degradation_service = degradation_service or get_degradation_service()
        
    # ==================== FAST LEARNING ====================
    # Real-time updates after every trade
    
    async def capture_alert_context(
        self,
        alert_id: str,
        symbol: str,
        setup_type: str,
        alert_priority: str = "medium",
        tape_score: float = 0.0,
        tape_confirmation: bool = False,
        smb_score: int = 25,
        trade_grade: str = "B"
    ) -> TradeContext:
        """
        Capture and store context when a scanner alert is generated.
        This is called BEFORE any trade is taken.
        
        Returns the captured context for immediate use.
        """
        try:
            context = await self._context_service.capture_context(
                symbol=symbol,
                setup_type=setup_type,
                alert_priority=alert_priority,
                tape_score=tape_score,
                tape_confirmation=tape_confirmation,
                smb_score=smb_score,
                trade_grade=trade_grade
            )
            
            # Store for later association with trade
            self._pending_contexts[alert_id] = context
            
            logger.debug(f"Captured context for alert {alert_id}: regime={context.market_regime.value}, time={context.time_of_day.value}")
            
            return context
            
        except Exception as e:
            logger.error(f"Error capturing alert context: {e}")
            return TradeContext()
            
    def start_execution_tracking(
        self,
        trade_id: str,
        alert_id: str,
        intended_entry: float,
        intended_size: int,
        planned_r: float = 2.0
    ) -> ExecutionMetrics:
        """
        Start tracking execution for a trade.
        Called when a trade is submitted/initiated.
        """
        metrics = self._execution_tracker.start_tracking(
            trade_id=trade_id,
            intended_entry=intended_entry,
            intended_size=intended_size,
            planned_r=planned_r
        )
        
        # Link to alert context if available
        if alert_id in self._pending_contexts:
            # Context will be associated when trade is recorded
            pass
            
        return metrics
        
    def record_trade_entry(
        self,
        trade_id: str,
        actual_entry: float,
        actual_size: int,
        size_adjustment_reason: Optional[str] = None
    ):
        """Record actual entry execution"""
        self._execution_tracker.record_entry(
            trade_id=trade_id,
            actual_entry=actual_entry,
            actual_size=actual_size,
            size_adjustment_reason=size_adjustment_reason
        )
        
    def record_stop_adjustment(
        self,
        trade_id: str,
        old_stop: float,
        new_stop: float,
        reason: str = ""
    ):
        """Record a stop adjustment"""
        self._execution_tracker.record_stop_adjustment(
            trade_id=trade_id,
            old_stop=old_stop,
            new_stop=new_stop,
            reason=reason
        )
        
    def record_scale_out(
        self,
        trade_id: str,
        scale_price: float,
        scale_shares: int,
        r_captured: float
    ):
        """Record a scale-out"""
        self._execution_tracker.record_scale_out(
            trade_id=trade_id,
            scale_price=scale_price,
            scale_shares=scale_shares,
            r_captured=r_captured
        )
        
    async def record_trade_outcome(
        self,
        trade_id: str,
        alert_id: str,
        symbol: str,
        setup_type: str,
        strategy_name: str,
        direction: str,
        trade_style: str,
        entry_price: float,
        exit_price: float,
        stop_price: float,
        target_price: float,
        outcome: str,  # "won", "lost", "breakeven"
        pnl: float,
        entry_time: str,
        exit_time: str,
        confirmation_signals: List[str] = None,
        expected_hold_minutes: int = 30
    ) -> TradeOutcome:
        """
        Record complete trade outcome for learning.
        Called when a trade is closed.
        
        This triggers:
        1. Execution metrics finalization
        2. Context association
        3. Database storage
        4. Tilt state update
        5. Session tracking
        """
        # Get execution metrics
        exit_reason = "manual"  # Will be updated based on exit price vs stop/target
        if exit_price <= stop_price and direction == "long":
            exit_reason = "stop"
        elif exit_price >= target_price and direction == "long":
            exit_reason = "target"
        elif exit_price >= stop_price and direction == "short":
            exit_reason = "stop"
        elif exit_price <= target_price and direction == "short":
            exit_reason = "target"
            
        execution = self._execution_tracker.record_exit(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            entry_time=entry_time,
            expected_hold_minutes=expected_hold_minutes
        )
        
        if execution is None:
            execution = ExecutionMetrics()
            
        # Calculate actual R
        risk_per_share = abs(entry_price - stop_price)
        pnl_per_share = exit_price - entry_price if direction == "long" else entry_price - exit_price
        actual_r = pnl_per_share / risk_per_share if risk_per_share > 0 else 0
        
        planned_r = abs(target_price - entry_price) / risk_per_share if risk_per_share > 0 else 2.0
        
        execution.actual_r = actual_r
        execution.planned_r = planned_r
        execution.r_capture_percent = (actual_r / planned_r * 100) if planned_r > 0 else 0
        execution.calculate_quality_score()
        
        # Get context (from pending or capture fresh)
        context = self._pending_contexts.pop(alert_id, None)
        if context is None:
            # Capture context now (less ideal, but graceful degradation)
            context = await self._context_service.capture_context(
                symbol=symbol,
                setup_type=setup_type
            )
            
        # Create trade outcome record
        trade_outcome = TradeOutcome(
            id=str(uuid.uuid4()),
            alert_id=alert_id,
            bot_trade_id=trade_id,
            symbol=symbol,
            setup_type=setup_type,
            strategy_name=strategy_name,
            direction=direction,
            trade_style=trade_style,
            entry_price=entry_price,
            exit_price=exit_price,
            stop_price=stop_price,
            target_price=target_price,
            outcome=outcome,
            pnl=pnl,
            pnl_percent=(pnl / (entry_price * execution.position_size) * 100) if execution.position_size > 0 else 0,
            actual_r=actual_r,
            planned_r=planned_r,
            context=context,
            execution=execution,
            confirmation_signals=confirmation_signals or [],
            entry_time=entry_time,
            exit_time=exit_time
        )
        
        # Store in database
        await self._store_outcome(trade_outcome)
        
        # GAP 5: Update confidence gate log with trade outcome for auto-calibration
        try:
            from services.ai_modules.confidence_gate import get_confidence_gate
            gate = get_confidence_gate()
            await gate.record_trade_outcome(
                symbol=symbol,
                setup_type=setup_type,
                outcome=outcome,
                pnl=pnl,
            )
        except Exception as e:
            logger.debug(f"Could not update confidence gate outcome (non-critical): {e}")
        
        # Update tilt state
        await self._update_tilt_state(trade_outcome)
        
        # Track in session
        self._session_trades.append(trade_outcome.id)
        
        # Clean up execution tracker
        self._execution_tracker.finalize_and_remove(trade_id)
        
        logger.info(f"Recorded trade outcome: {symbol} {setup_type} - {outcome}, {actual_r:.2f}R, ${pnl:.2f}")
        
        return trade_outcome
        
    async def _store_outcome(self, outcome: TradeOutcome):
        """Store trade outcome in MongoDB"""
        if self._trade_outcomes_col is None:
            logger.warning("Trade outcomes collection not initialized")
            return
            
        try:
            doc = outcome.to_dict()
            # Remove MongoDB _id if present
            doc.pop('_id', None)
            
            self._trade_outcomes_col.insert_one(doc)
            logger.debug(f"Stored trade outcome {outcome.id}")
            
        except Exception as e:
            logger.error(f"Error storing trade outcome: {e}")
            
    async def _update_tilt_state(self, outcome: TradeOutcome):
        """Update tilt detection state based on latest trade"""
        if self._current_profile is None:
            self._current_profile = await self._load_trader_profile()
            
        tilt = self._current_profile.current_tilt_state
        
        # Update consecutive losses
        if outcome.outcome == "lost":
            tilt.consecutive_losses += 1
            tilt.losses_in_last_hour += 1
            tilt.pnl_last_hour += outcome.pnl
        else:
            tilt.consecutive_losses = 0
            
        # Update session stats
        self._current_profile.trades_today += 1
        self._current_profile.pnl_today += outcome.pnl
        
        # Detect tilt
        tilt.tilt_indicators = []
        
        if tilt.consecutive_losses >= 3:
            tilt.tilt_indicators.append(f"{tilt.consecutive_losses} consecutive losses")
        if tilt.losses_in_last_hour >= 3:
            tilt.tilt_indicators.append(f"{tilt.losses_in_last_hour} losses in last hour")
        if tilt.pnl_last_hour < -500:
            tilt.tilt_indicators.append(f"${abs(tilt.pnl_last_hour):.0f} loss in last hour")
            
        # Set tilt severity
        if len(tilt.tilt_indicators) >= 3 or tilt.consecutive_losses >= 5:
            tilt.is_tilted = True
            tilt.tilt_severity = "severe"
        elif len(tilt.tilt_indicators) >= 2 or tilt.consecutive_losses >= 3:
            tilt.is_tilted = True
            tilt.tilt_severity = "moderate"
        elif len(tilt.tilt_indicators) >= 1:
            tilt.is_tilted = True
            tilt.tilt_severity = "mild"
        else:
            tilt.is_tilted = False
            tilt.tilt_severity = "none"
            
        tilt.last_trade_time = outcome.exit_time
        
        # Save updated profile
        await self._save_trader_profile(self._current_profile)
        
        if tilt.is_tilted:
            logger.warning(f"Tilt detected: {tilt.tilt_severity} - {', '.join(tilt.tilt_indicators)}")
            
    # ==================== MEDIUM LEARNING ====================
    # End-of-day analysis and calibration
    
    async def run_daily_analysis(self) -> Dict[str, Any]:
        """
        Run end-of-day analysis.
        Called at market close (4:00 PM ET) or manually.
        
        This:
        1. Aggregates today's trades into stats
        2. Updates learning stats by context
        3. Calculates execution patterns
        4. Updates trader profile
        5. Detects edge decay
        6. Generates calibration recommendations
        """
        analysis = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "trades_analyzed": 0,
            "stats_updated": 0,
            "profile_updated": False,
            "calibration_recommendations": [],
            "edge_decay_warnings": [],
            "execution_insights": []
        }
        
        try:
            # Get today's trades
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
            if self._trade_outcomes_col is None:
                return analysis
                
            today_outcomes = list(self._trade_outcomes_col.find({
                "created_at": {"$gte": today_start.isoformat()},
                "reviewed": False
            }))
            
            analysis["trades_analyzed"] = len(today_outcomes)
            
            if not today_outcomes:
                return analysis
                
            # Convert to TradeOutcome objects
            outcomes = [TradeOutcome.from_dict(o) for o in today_outcomes]
            
            # 1. Update learning stats by context
            stats_updated = await self._update_learning_stats(outcomes)
            analysis["stats_updated"] = stats_updated
            
            # 2. Analyze execution patterns
            execution_analysis = self._execution_tracker.analyze_execution_patterns(today_outcomes)
            analysis["execution_insights"] = execution_analysis.get("recommendations", [])
            
            # 3. Update trader profile
            await self._update_trader_profile(outcomes)
            analysis["profile_updated"] = True
            
            # 4. Check for edge decay
            decay_warnings = await self._check_edge_decay()
            analysis["edge_decay_warnings"] = decay_warnings
            
            # 5. Generate calibration recommendations
            calibrations = await self._generate_calibration_recommendations(outcomes)
            analysis["calibration_recommendations"] = calibrations
            
            # Mark trades as reviewed
            self._trade_outcomes_col.update_many(
                {"id": {"$in": [o.id for o in outcomes]}},
                {"$set": {"reviewed": True}}
            )
            
            logger.info(f"Daily analysis complete: {analysis['trades_analyzed']} trades, "
                       f"{analysis['stats_updated']} stats updated")
            
        except Exception as e:
            logger.error(f"Error in daily analysis: {e}")
            
        return analysis
        
    async def _update_learning_stats(self, outcomes: List[TradeOutcome]) -> int:
        """Update aggregated learning stats by context"""
        if self._learning_stats_col is None:
            return 0
            
        updated_count = 0
        
        # Group outcomes by context key
        context_groups: Dict[str, List[TradeOutcome]] = {}
        
        for outcome in outcomes:
            # Generate context key
            key_parts = [outcome.setup_type]
            
            if outcome.context.market_regime:
                key_parts.append(outcome.context.market_regime.value)
            if outcome.context.time_of_day:
                key_parts.append(outcome.context.time_of_day.value)
                
            context_key = ":".join(key_parts)
            
            if context_key not in context_groups:
                context_groups[context_key] = []
            context_groups[context_key].append(outcome)
            
        # Update stats for each context
        for context_key, group_outcomes in context_groups.items():
            try:
                # Get existing stats or create new
                existing = self._learning_stats_col.find_one({"context_key": context_key})
                
                if existing:
                    stats = LearningStats.from_dict(existing)
                    # Get all outcomes for this context
                    all_outcomes_docs = list(self._trade_outcomes_col.find({
                        "setup_type": stats.setup_type,
                        "context.market_regime": stats.market_regime,
                        "context.time_of_day": stats.time_of_day
                    }))
                    all_outcomes = [TradeOutcome.from_dict(o) for o in all_outcomes_docs]
                else:
                    stats = LearningStats(context_key=context_key)
                    stats.setup_type = group_outcomes[0].setup_type
                    if group_outcomes[0].context.market_regime:
                        stats.market_regime = group_outcomes[0].context.market_regime.value
                    if group_outcomes[0].context.time_of_day:
                        stats.time_of_day = group_outcomes[0].context.time_of_day.value
                    all_outcomes = group_outcomes
                    
                # Recalculate stats
                stats.calculate_stats(all_outcomes)
                
                # Upsert to database
                self._learning_stats_col.update_one(
                    {"context_key": context_key},
                    {"$set": stats.to_dict()},
                    upsert=True
                )
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Error updating stats for {context_key}: {e}")
                
        return updated_count
        
    async def _update_trader_profile(self, recent_outcomes: List[TradeOutcome]):
        """Update trader profile based on recent trades"""
        profile = await self._load_trader_profile()
        
        # Update overall stats
        all_outcomes_docs = list(self._trade_outcomes_col.find({}).sort("created_at", -1).limit(500))
        all_outcomes = [TradeOutcome.from_dict(o) for o in all_outcomes_docs]
        
        if all_outcomes:
            profile.total_trades = len(all_outcomes)
            wins = sum(1 for o in all_outcomes if o.outcome == "won")
            losses = sum(1 for o in all_outcomes if o.outcome == "lost")
            profile.overall_win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
            
            # Calculate profit factor
            gross_profit = sum(o.pnl for o in all_outcomes if o.pnl > 0)
            gross_loss = abs(sum(o.pnl for o in all_outcomes if o.pnl < 0))
            profile.overall_profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
            
            # Calculate EV
            profile.overall_ev_r = sum(o.actual_r for o in all_outcomes) / len(all_outcomes) if all_outcomes else 0
            
        # Find best/worst setups
        setup_stats = await self._get_setup_stats()
        
        profile.best_setups = sorted(
            [s for s in setup_stats if s.get('total_trades', 0) >= 5],
            key=lambda x: x.get('win_rate', 0),
            reverse=True
        )[:5]
        
        profile.worst_setups = sorted(
            [s for s in setup_stats if s.get('total_trades', 0) >= 5],
            key=lambda x: x.get('win_rate', 1)
        )[:5]
        
        # Find best/worst hours
        hour_stats = await self._get_time_stats()
        
        profile.best_hours = sorted(
            [h for h in hour_stats if h.get('total_trades', 0) >= 5],
            key=lambda x: x.get('win_rate', 0),
            reverse=True
        )[:3]
        
        profile.worst_hours = sorted(
            [h for h in hour_stats if h.get('total_trades', 0) >= 5],
            key=lambda x: x.get('win_rate', 1)
        )[:3]
        
        # Execution tendencies
        slippages = [o.execution.entry_slippage_percent for o in all_outcomes if o.execution]
        r_captures = [o.execution.r_capture_percent for o in all_outcomes if o.execution and o.execution.r_capture_percent > 0]
        
        profile.avg_entry_slippage_percent = sum(slippages) / len(slippages) if slippages else 0
        profile.avg_r_capture_percent = sum(r_captures) / len(r_captures) if r_captures else 0
        
        profile.tends_to_chase = profile.avg_entry_slippage_percent > 0.2
        profile.tends_to_exit_early = profile.avg_r_capture_percent < 50
        
        profile.last_updated = datetime.now(timezone.utc).isoformat()
        
        await self._save_trader_profile(profile)
        self._current_profile = profile
        
    async def _get_setup_stats(self) -> List[Dict]:
        """Get win rate stats by setup type"""
        if self._learning_stats_col is None:
            return []
            
        stats = list(self._learning_stats_col.find({
            "market_regime": None,
            "time_of_day": None
        }))
        
        return [{
            "setup": s.get("setup_type"),
            "win_rate": s.get("win_rate", 0),
            "ev_r": s.get("expected_value_r", 0),
            "total_trades": s.get("total_trades", 0)
        } for s in stats]
        
    async def _get_time_stats(self) -> List[Dict]:
        """Get win rate stats by time of day"""
        if self._trade_outcomes_col is None:
            return []
            
        pipeline = [
            {"$group": {
                "_id": "$context.time_of_day",
                "total_trades": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$eq": ["$outcome", "won"]}, 1, 0]}},
                "total_pnl": {"$sum": "$pnl"}
            }}
        ]
        
        results = list(self._trade_outcomes_col.aggregate(pipeline))
        
        return [{
            "hour": r["_id"],
            "win_rate": r["wins"] / r["total_trades"] if r["total_trades"] > 0 else 0,
            "total_trades": r["total_trades"],
            "total_pnl": r["total_pnl"]
        } for r in results]
        
    async def _check_edge_decay(self) -> List[str]:
        """Check for edge decay in any setup/context"""
        warnings = []
        
        if self._learning_stats_col is None:
            return warnings
            
        stats = list(self._learning_stats_col.find({"edge_declining": True}))
        
        for stat in stats:
            warnings.append(
                f"{stat.get('setup_type', 'Unknown')} edge declining: "
                f"Recent win rate {stat.get('rolling_win_rate_10', 0)*100:.0f}% vs "
                f"overall {stat.get('win_rate', 0)*100:.0f}%"
            )
            
        return warnings
        
    async def _generate_calibration_recommendations(
        self,
        recent_outcomes: List[TradeOutcome]
    ) -> List[Dict]:
        """Generate recommendations for threshold adjustments"""
        recommendations = []
        
        # Check if any setup is significantly underperforming
        setup_groups: Dict[str, List[TradeOutcome]] = {}
        for outcome in recent_outcomes:
            if outcome.setup_type not in setup_groups:
                setup_groups[outcome.setup_type] = []
            setup_groups[outcome.setup_type].append(outcome)
            
        for setup_type, outcomes in setup_groups.items():
            if len(outcomes) >= 3:
                wins = sum(1 for o in outcomes if o.outcome == "won")
                win_rate = wins / len(outcomes)
                
                if win_rate < 0.4:
                    recommendations.append({
                        "type": "threshold_increase",
                        "parameter": f"{setup_type}_min_score",
                        "reason": f"Recent win rate only {win_rate*100:.0f}% for {setup_type}",
                        "suggested_action": "Increase minimum score threshold by 5-10%"
                    })
                    
        return recommendations
        
    # ==================== PROFILE MANAGEMENT ====================
    
    async def _load_trader_profile(self) -> TraderProfile:
        """Load trader profile from database"""
        if self._trader_profile_col is None:
            return TraderProfile()
            
        try:
            doc = self._trader_profile_col.find_one({"profile_id": "default"})
            if doc:
                doc.pop('_id', None)
                return TraderProfile.from_dict(doc)
        except Exception as e:
            logger.error(f"Error loading trader profile: {e}")
            
        return TraderProfile()
        
    async def _save_trader_profile(self, profile: TraderProfile):
        """Save trader profile to database"""
        if self._trader_profile_col is None:
            return
            
        try:
            doc = profile.to_dict()
            doc.pop('_id', None)
            
            self._trader_profile_col.update_one(
                {"profile_id": "default"},
                {"$set": doc},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error saving trader profile: {e}")
            
    async def get_trader_profile(self) -> TraderProfile:
        """Get current trader profile"""
        if self._current_profile is None:
            self._current_profile = await self._load_trader_profile()
        return self._current_profile
        
    def get_ai_context(self) -> str:
        """Get trader profile context for AI prompts"""
        if self._current_profile is None:
            return ""
        return self._current_profile.generate_ai_context()
        
    # ==================== STATS QUERIES ====================
    
    async def get_learning_stats(
        self,
        setup_type: Optional[str] = None,
        market_regime: Optional[str] = None,
        time_of_day: Optional[str] = None
    ) -> List[LearningStats]:
        """Query learning stats with optional filters"""
        if self._learning_stats_col is None:
            return []
            
        query = {}
        if setup_type:
            query["setup_type"] = setup_type
        if market_regime:
            query["market_regime"] = market_regime
        if time_of_day:
            query["time_of_day"] = time_of_day
            
        docs = list(self._learning_stats_col.find(query))
        return [LearningStats.from_dict(d) for d in docs]
        
    async def get_contextual_win_rate(
        self,
        setup_type: str,
        market_regime: Optional[str] = None,
        time_of_day: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get win rate for a specific context"""
        stats = await self.get_learning_stats(
            setup_type=setup_type,
            market_regime=market_regime,
            time_of_day=time_of_day
        )
        
        if not stats:
            return {"win_rate": 0.5, "sample_size": 0, "confidence": "low"}
            
        # Find most specific match
        best_match = max(stats, key=lambda s: s.total_trades)
        
        confidence = "low"
        if best_match.total_trades >= 30:
            confidence = "high"
        elif best_match.total_trades >= 10:
            confidence = "medium"
            
        return {
            "win_rate": best_match.win_rate,
            "expected_value_r": best_match.expected_value_r,
            "sample_size": best_match.total_trades,
            "confidence": confidence,
            "context_key": best_match.context_key
        }
        
    async def get_recent_outcomes(
        self,
        limit: int = 20,
        setup_type: Optional[str] = None
    ) -> List[TradeOutcome]:
        """Get recent trade outcomes"""
        if self._trade_outcomes_col is None:
            return []
            
        query = {}
        if setup_type:
            query["setup_type"] = setup_type
            
        docs = list(self._trade_outcomes_col.find(query).sort("created_at", -1).limit(limit))
        return [TradeOutcome.from_dict(d) for d in docs]
        
    def is_tilted(self) -> bool:
        """Check if trader is currently tilted"""
        if self._current_profile is None:
            return False
        return self._current_profile.current_tilt_state.is_tilted
        
    def get_tilt_severity(self) -> str:
        """Get current tilt severity"""
        if self._current_profile is None:
            return "none"
        return self._current_profile.current_tilt_state.tilt_severity


# Singleton instance
_learning_loop_service: Optional[LearningLoopService] = None


def get_learning_loop_service() -> LearningLoopService:
    """Get the singleton learning loop service"""
    global _learning_loop_service
    if _learning_loop_service is None:
        _learning_loop_service = LearningLoopService()
    return _learning_loop_service


def init_learning_loop_service(db=None) -> LearningLoopService:
    """Initialize the learning loop service with database"""
    service = get_learning_loop_service()
    if db is not None:
        service.set_db(db)
    service.set_services()
    return service
