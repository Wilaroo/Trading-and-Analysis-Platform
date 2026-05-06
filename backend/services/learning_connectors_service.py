"""
Learning Connectors Service - Bridges Data Gaps for Continuous Improvement

This service creates the missing connections between SentCom's data sources
and its learning systems:

1. Simulation → Model Retraining: Auto-retrain Time-Series model from simulation data
2. Shadow Tracker → Module Calibration: Adjust AI module weights based on accuracy
3. Alert Outcomes → Scanner Tuning: Auto-calibrate scanner thresholds
4. Cross-System Feedback: Aggregate learning insights across all systems

The goal: Make SentCom continuously smarter without manual intervention.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ConnectionStatus:
    """Status of a learning connection"""
    name: str
    source: str
    destination: str
    is_connected: bool = False
    last_sync: str = ""
    records_synced: int = 0
    sync_frequency: str = ""  # "realtime", "hourly", "daily", "manual"
    health: str = "unknown"  # "healthy", "degraded", "disconnected"
    error_message: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ModuleCalibration:
    """Calibration data for an AI module"""
    module_name: str
    current_weight: float = 1.0
    recommended_weight: float = 1.0
    accuracy_30d: float = 0.0
    total_decisions: int = 0
    correct_decisions: int = 0
    avg_confidence: float = 0.0
    last_calibrated: str = ""
    calibration_reason: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass  
class SignalCalibration:
    """Calibration data for a signal/setup type"""
    setup_type: str
    current_threshold: float = 0.0
    recommended_threshold: float = 0.0
    win_rate_30d: float = 0.0
    total_alerts: int = 0
    profitable_alerts: int = 0
    avg_r_multiple: float = 0.0
    last_calibrated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class LearningMetrics:
    """Overall learning system metrics"""
    total_data_points: int = 0
    data_points_used_for_training: int = 0
    model_versions_created: int = 0
    calibrations_applied: int = 0
    accuracy_improvement_pct: float = 0.0
    last_full_sync: str = ""
    connections_healthy: int = 0
    connections_total: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class LearningConnectorsService:
    """
    Orchestrates learning connections across SentCom systems.
    
    Key responsibilities:
    1. Monitor data flow between systems
    2. Trigger auto-retraining when sufficient new data exists
    3. Calculate and apply module weight calibrations
    4. Tune scanner thresholds based on outcomes
    5. Provide visibility into learning health
    """
    
    COLLECTION_NAME = "learning_connectors"
    CALIBRATION_HISTORY = "calibration_history"
    
    def __init__(self):
        self._db = None
        self._connectors_col = None
        self._calibration_col = None
        
        # Service references (set via dependency injection)
        self._timeseries_ai = None
        self._shadow_tracker = None
        self._learning_loop = None
        self._scanner = None
        self._simulation_engine = None
        self._dynamic_thresholds = None  # NEW: DynamicThresholdService
        
        # Connection definitions
        self._connections: Dict[str, ConnectionStatus] = {}
        self._init_connections()
        
        # Calibration state
        self._module_weights: Dict[str, float] = {
            "debate_agents": 1.0,
            "risk_manager": 1.0,
            "institutional_flow": 1.0,
            "timeseries_ai": 1.0,
            "volume_anomaly": 1.0
        }
        
        # Thresholds for auto-actions
        self._min_samples_for_calibration = 50
        self._calibration_interval_hours = 24
        self._retrain_threshold_samples = 1000
        
    def _init_connections(self):
        """Initialize connection status trackers"""
        connections = [
            ConnectionStatus(
                name="simulation_to_timeseries",
                source="Historical Simulations",
                destination="Time-Series Model",
                sync_frequency="after_simulation"
            ),
            ConnectionStatus(
                name="shadow_to_weights",
                source="Shadow Tracker",
                destination="Module Weights",
                sync_frequency="daily"
            ),
            ConnectionStatus(
                name="outcomes_to_scanner",
                source="Alert Outcomes",
                destination="Scanner Thresholds",
                sync_frequency="daily"
            ),
            ConnectionStatus(
                name="trades_to_learning",
                source="Trade Journal",
                destination="Learning Loop",
                sync_frequency="realtime"
            ),
            ConnectionStatus(
                name="predictions_to_verification",
                source="Time-Series Predictions",
                destination="Outcome Verification",
                sync_frequency="hourly"
            ),
            ConnectionStatus(
                name="debate_to_tuning",
                source="Debate Outcomes",
                destination="Debate Weights",
                sync_frequency="weekly"
            ),
            ConnectionStatus(
                name="ib_historical_to_training",
                source="IB Gateway Historical",
                destination="Model Training Data",
                sync_frequency="on_demand"
            )
        ]
        
        for conn in connections:
            self._connections[conn.name] = conn
            
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._connectors_col = db[self.COLLECTION_NAME]
            self._calibration_col = db[self.CALIBRATION_HISTORY]
            
            # Create indexes
            self._connectors_col.create_index([("name", 1)], unique=True)
            self._calibration_col.create_index([("timestamp", -1)])
            self._calibration_col.create_index([("calibration_type", 1)])
            
            # Load saved connection states
            self._load_connection_states()
            
    def set_services(
        self,
        timeseries_ai=None,
        shadow_tracker=None,
        learning_loop=None,
        scanner=None,
        simulation_engine=None,
        dynamic_thresholds=None  # NEW
    ):
        """Set service dependencies"""
        self._timeseries_ai = timeseries_ai
        self._shadow_tracker = shadow_tracker
        self._learning_loop = learning_loop
        self._scanner = scanner
        self._simulation_engine = simulation_engine
        self._dynamic_thresholds = dynamic_thresholds
        
        # Update connection status based on available services
        self._update_connection_health()
        
    def _load_connection_states(self):
        """Load saved connection states from database"""
        if self._connectors_col is None:
            return
            
        try:
            for doc in self._connectors_col.find():
                name = doc.get("name")
                if name in self._connections:
                    self._connections[name].last_sync = doc.get("last_sync", "")
                    self._connections[name].records_synced = doc.get("records_synced", 0)
                    self._connections[name].health = doc.get("health", "unknown")
        except Exception as e:
            logger.error(f"Error loading connection states: {e}")
            
    def _update_connection_health(self):
        """Update connection health based on service availability"""
        # Simulation → Timeseries
        self._connections["simulation_to_timeseries"].is_connected = (
            self._simulation_engine is not None and self._timeseries_ai is not None
        )
        
        # Shadow → Weights
        self._connections["shadow_to_weights"].is_connected = (
            self._shadow_tracker is not None
        )
        
        # Outcomes → Scanner
        self._connections["outcomes_to_scanner"].is_connected = (
            self._scanner is not None and self._db is not None
        )
        
        # Trades → Learning
        self._connections["trades_to_learning"].is_connected = (
            self._learning_loop is not None
        )
        
        # Predictions → Verification
        self._connections["predictions_to_verification"].is_connected = (
            self._timeseries_ai is not None
        )
        
        # Debate → Tuning
        self._connections["debate_to_tuning"].is_connected = (
            self._shadow_tracker is not None
        )
        
        # IB Historical → Training (always available if DB connected)
        self._connections["ib_historical_to_training"].is_connected = (
            self._db is not None
        )
        
        # Update health status
        for conn in self._connections.values():
            if conn.is_connected:
                conn.health = "healthy" if conn.last_sync else "pending"
            else:
                conn.health = "disconnected"
                
    def _save_connection_state(self, name: str):
        """Save connection state to database"""
        if self._connectors_col is None:
            return
            
        conn = self._connections.get(name)
        if conn:
            try:
                self._connectors_col.update_one(
                    {"name": name},
                    {"$set": conn.to_dict()},
                    upsert=True
                )
            except Exception as e:
                logger.error(f"Error saving connection state: {e}")

    # =========================================================================
    # CONNECTION 1: Simulation → Time-Series Model Retraining
    # =========================================================================
    
    async def sync_simulation_to_model(self, job_id: str = None) -> Dict[str, Any]:
        """
        Extract training data from simulation results and retrain model.
        
        If job_id is provided, use that specific simulation.
        Otherwise, use all completed simulations not yet used for training.
        """
        conn = self._connections["simulation_to_timeseries"]
        
        if not conn.is_connected:
            return {"success": False, "error": "Connection not available"}
            
        try:
            # Get simulation trades for training
            if self._db is None:
                return {"success": False, "error": "Database not connected"}
                
            query = {"used_for_training": {"$ne": True}}
            if job_id:
                query["job_id"] = job_id
                
            trades_col = self._db["simulated_trades"]
            trades = list(trades_col.find(query).limit(10000))
            
            if len(trades) < self._min_samples_for_calibration:
                return {
                    "success": False, 
                    "error": f"Insufficient data: {len(trades)} trades (need {self._min_samples_for_calibration})"
                }
                
            # Extract features from trades for model training
            training_data = []
            for trade in trades:
                # Create training sample from trade context
                sample = {
                    "symbol": trade.get("symbol"),
                    "entry_time": trade.get("entry_time"),
                    "direction": trade.get("direction"),
                    "outcome": 1 if trade.get("pnl", 0) > 0 else 0,
                    "setup_type": trade.get("setup_type"),
                    "market_regime": trade.get("market_context", {}).get("regime", "unknown"),
                    # Add more features as available
                }
                training_data.append(sample)
                
            # Trigger model retraining
            if self._timeseries_ai:
                # Mark trades as used
                trade_ids = [t.get("_id") for t in trades if t.get("_id")]
                if trade_ids:
                    trades_col.update_many(
                        {"_id": {"$in": trade_ids}},
                        {"$set": {"used_for_training": True, "training_date": datetime.now(timezone.utc).isoformat()}}
                    )
                
                # Retrain model
                result = await self._timeseries_ai.train_model()
                
                # Update connection status
                conn.last_sync = datetime.now(timezone.utc).isoformat()
                conn.records_synced += len(trades)
                conn.health = "healthy"
                self._save_connection_state("simulation_to_timeseries")
                
                # Log calibration
                self._log_calibration("simulation_to_model", {
                    "trades_used": len(trades),
                    "job_id": job_id,
                    "result": result
                })
                
                return {
                    "success": True,
                    "trades_processed": len(trades),
                    "model_result": result
                }
            else:
                return {"success": False, "error": "Time-series AI not available"}
                
        except Exception as e:
            logger.error(f"Error syncing simulation to model: {e}")
            conn.health = "degraded"
            conn.error_message = str(e)
            return {"success": False, "error": str(e)}

    # =========================================================================
    # CONNECTION 2: Shadow Tracker → Module Weight Calibration
    # =========================================================================
    
    async def sync_shadow_to_weights(self) -> Dict[str, Any]:
        """
        Analyze shadow tracker accuracy per module and calibrate weights.
        Modules with higher accuracy get higher weight in final decisions.
        """
        conn = self._connections["shadow_to_weights"]
        
        if not conn.is_connected:
            return {"success": False, "error": "Connection not available"}
            
        try:
            if self._db is None:
                return {"success": False, "error": "Database not connected"}
                
            # Get shadow decisions from last 30 days
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            decisions_col = self._db["shadow_decisions"]
            
            decisions = list(decisions_col.find({
                "outcome_tracked": True,
                "trigger_time": {"$gte": cutoff.isoformat()}
            }))
            
            if len(decisions) < self._min_samples_for_calibration:
                return {
                    "success": False,
                    "error": f"Insufficient data: {len(decisions)} decisions"
                }
                
            # Calculate accuracy per module
            module_stats = {
                "debate_agents": {"correct": 0, "total": 0, "confidence_sum": 0},
                "risk_manager": {"correct": 0, "total": 0, "confidence_sum": 0},
                "institutional_flow": {"correct": 0, "total": 0, "confidence_sum": 0},
                "timeseries_ai": {"correct": 0, "total": 0, "confidence_sum": 0},
                "volume_anomaly": {"correct": 0, "total": 0, "confidence_sum": 0}
            }
            
            for decision in decisions:
                # Check each module's contribution
                modules_used = decision.get("modules_used", [])
                was_profitable = decision.get("would_have_pnl", 0) > 0
                
                # Debate agents
                if "debate" in modules_used or decision.get("debate_result"):
                    debate = decision.get("debate_result", {})
                    module_stats["debate_agents"]["total"] += 1
                    if debate.get("winner") == "bull" and was_profitable:
                        module_stats["debate_agents"]["correct"] += 1
                    elif debate.get("winner") == "bear" and not was_profitable:
                        module_stats["debate_agents"]["correct"] += 1
                    module_stats["debate_agents"]["confidence_sum"] += debate.get("confidence", 0.5)
                        
                # Risk manager
                if "risk" in modules_used or decision.get("risk_assessment"):
                    risk = decision.get("risk_assessment", {})
                    module_stats["risk_manager"]["total"] += 1
                    rec = risk.get("recommendation", "").lower()
                    if rec == "proceed" and was_profitable:
                        module_stats["risk_manager"]["correct"] += 1
                    elif rec in ["pass", "reduce"] and not was_profitable:
                        module_stats["risk_manager"]["correct"] += 1
                    module_stats["risk_manager"]["confidence_sum"] += (1 - risk.get("risk_score", 0.5))
                        
                # Time-series
                if "timeseries" in modules_used or decision.get("timeseries_forecast"):
                    ts = decision.get("timeseries_forecast", {})
                    module_stats["timeseries_ai"]["total"] += 1
                    if ts.get("direction") == "up" and was_profitable:
                        module_stats["timeseries_ai"]["correct"] += 1
                    elif ts.get("direction") == "down" and not was_profitable:
                        module_stats["timeseries_ai"]["correct"] += 1
                    module_stats["timeseries_ai"]["confidence_sum"] += ts.get("probability", 0.5)
                    
            # Calculate new weights based on accuracy
            calibrations = []
            for module_name, stats in module_stats.items():
                if stats["total"] >= 10:  # Minimum sample size per module
                    accuracy = stats["correct"] / stats["total"]
                    avg_confidence = stats["confidence_sum"] / stats["total"]
                    
                    # Weight formula: base + accuracy bonus + confidence factor
                    # Higher accuracy = higher weight (0.5 to 1.5 range)
                    new_weight = 0.5 + (accuracy * 1.0)
                    
                    # Clamp to reasonable range
                    new_weight = max(0.3, min(1.5, new_weight))
                    
                    old_weight = self._module_weights.get(module_name, 1.0)
                    
                    calibration = ModuleCalibration(
                        module_name=module_name,
                        current_weight=old_weight,
                        recommended_weight=new_weight,
                        accuracy_30d=accuracy,
                        total_decisions=stats["total"],
                        correct_decisions=stats["correct"],
                        avg_confidence=avg_confidence,
                        last_calibrated=datetime.now(timezone.utc).isoformat(),
                        calibration_reason=f"Accuracy {accuracy:.1%} over {stats['total']} decisions"
                    )
                    calibrations.append(calibration)
                    
                    # Apply new weight
                    self._module_weights[module_name] = new_weight
                    
            # Update connection status
            conn.last_sync = datetime.now(timezone.utc).isoformat()
            conn.records_synced += len(decisions)
            conn.health = "healthy"
            self._save_connection_state("shadow_to_weights")
            
            # Log calibration
            self._log_calibration("module_weights", {
                "decisions_analyzed": len(decisions),
                "calibrations": [c.to_dict() for c in calibrations]
            })
            
            # Save weights to database
            self._save_module_weights()
            
            return {
                "success": True,
                "decisions_analyzed": len(decisions),
                "calibrations": [c.to_dict() for c in calibrations],
                "new_weights": self._module_weights.copy()
            }
            
        except Exception as e:
            logger.error(f"Error syncing shadow to weights: {e}")
            conn.health = "degraded"
            conn.error_message = str(e)
            return {"success": False, "error": str(e)}
            
    def _save_module_weights(self):
        """Save module weights to database"""
        if self._connectors_col is None:
            return
            
        try:
            self._connectors_col.update_one(
                {"name": "module_weights"},
                {"$set": {
                    "name": "module_weights",
                    "weights": self._module_weights,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error saving module weights: {e}")
            
    def get_module_weights(self) -> Dict[str, float]:
        """Get current module weights"""
        return self._module_weights.copy()

    # =========================================================================
    # CONNECTION 3: Alert Outcomes → Scanner Threshold Calibration
    # =========================================================================
    
    async def sync_outcomes_to_scanner(self) -> Dict[str, Any]:
        """
        Analyze alert outcomes and calibrate scanner thresholds.
        Setup types with low win rates get higher thresholds (more selective).
        """
        conn = self._connections["outcomes_to_scanner"]
        
        if not conn.is_connected:
            return {"success": False, "error": "Connection not available"}
            
        try:
            if self._db is None:
                return {"success": False, "error": "Database not connected"}
                
            # Get alert outcomes from last 30 days
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            outcomes_col = self._db["alert_outcomes"]
            
            pipeline = [
                {"$match": {"timestamp": {"$gte": cutoff.isoformat()}}},
                {"$group": {
                    "_id": "$setup_type",
                    "total": {"$sum": 1},
                    "profitable": {"$sum": {"$cond": [{"$gt": ["$r_multiple", 0]}, 1, 0]}},
                    "avg_r": {"$avg": "$r_multiple"},
                    "total_r": {"$sum": "$r_multiple"}
                }}
            ]
            
            results = list(outcomes_col.aggregate(pipeline))
            
            if not results:
                return {"success": False, "error": "No outcome data found"}
                
            calibrations = []
            for result in results:
                setup_type = result["_id"]
                if setup_type and result["total"] >= 10:
                    win_rate = result["profitable"] / result["total"]
                    avg_r = result["avg_r"] or 0
                    
                    # Threshold adjustment logic:
                    # - Low win rate → raise threshold (be more selective)
                    # - High win rate → can lower threshold slightly
                    # - Negative avg R → definitely raise threshold
                    
                    # Get current threshold from scanner
                    current_threshold = self._get_current_threshold(setup_type)
                    
                    # Calculate recommended threshold
                    if avg_r < 0:
                        # Losing setup - increase threshold significantly
                        recommended = current_threshold * 1.3
                    elif win_rate < 0.4:
                        # Low win rate - increase threshold
                        recommended = current_threshold * 1.15
                    elif win_rate > 0.6 and avg_r > 0.5:
                        # Good setup - can slightly lower threshold
                        recommended = current_threshold * 0.95
                    else:
                        recommended = current_threshold
                        
                    # Clamp to reasonable range
                    recommended = max(0.5, min(2.0, recommended))
                    
                    calibration = SignalCalibration(
                        setup_type=setup_type,
                        current_threshold=current_threshold,
                        recommended_threshold=recommended,
                        win_rate_30d=win_rate,
                        total_alerts=result["total"],
                        profitable_alerts=result["profitable"],
                        avg_r_multiple=avg_r,
                        last_calibrated=datetime.now(timezone.utc).isoformat()
                    )
                    calibrations.append(calibration)
                    
            # ==== NEW: Actually apply calibrations to DynamicThresholdService ====
            applied_count = 0
            if self._dynamic_thresholds and calibrations:
                for cal in calibrations:
                    # Only apply if there's a meaningful change
                    if abs(cal.recommended_threshold - cal.current_threshold) > 0.05:
                        self._apply_setup_calibration(cal)
                        applied_count += 1
                        logger.info(
                            f"Applied threshold calibration for {cal.setup_type}: "
                            f"{cal.current_threshold:.2f} → {cal.recommended_threshold:.2f} "
                            f"(win_rate: {cal.win_rate_30d:.1%})"
                        )
                    
            # Update connection status
            conn.last_sync = datetime.now(timezone.utc).isoformat()
            conn.records_synced += sum(r["total"] for r in results)
            conn.health = "healthy"
            self._save_connection_state("outcomes_to_scanner")
            
            # Log calibration
            self._log_calibration("scanner_thresholds", {
                "setups_analyzed": len(results),
                "calibrations": [c.to_dict() for c in calibrations],
                "applied_count": applied_count
            })
            
            return {
                "success": True,
                "setups_analyzed": len(results),
                "calibrations": [c.to_dict() for c in calibrations],
                "applied_count": applied_count
            }
            
        except Exception as e:
            logger.error(f"Error syncing outcomes to scanner: {e}")
            conn.health = "degraded"
            conn.error_message = str(e)
            return {"success": False, "error": str(e)}
            
    def _get_current_threshold(self, setup_type: str) -> float:
        """Get current threshold for a setup type"""
        # First check if we have a stored custom threshold
        if self._db is not None:
            try:
                doc = self._connectors_col.find_one({"name": f"threshold_{setup_type}"})
                if doc and "value" in doc:
                    return doc["value"]
            except Exception:
                pass
                
        # Default thresholds by setup type
        defaults = {
            "gap_and_go": 1.0,
            "vwap_bounce": 1.0,
            "oversold_bounce": 1.0,
            "breakout": 1.0,
            "range_break": 1.0,
            "momentum_surge": 1.0,
            "bull_flag": 1.0,
            "orb_breakout": 1.0,
            "pullback_to_ema": 1.0
        }
        return defaults.get(setup_type, 1.0)
        
    def _apply_setup_calibration(self, calibration: 'SignalCalibration'):
        """
        Apply a calibration to both the database and DynamicThresholdService.
        
        This is where the learning loop actually CLOSES - calibrations get applied.
        """
        setup_type = calibration.setup_type
        new_threshold = calibration.recommended_threshold
        
        # 1. Store in database for persistence
        if self._connectors_col is not None:
            try:
                self._connectors_col.update_one(
                    {"name": f"threshold_{setup_type}"},
                    {"$set": {
                        "name": f"threshold_{setup_type}",
                        "value": new_threshold,
                        "win_rate_30d": calibration.win_rate_30d,
                        "total_alerts": calibration.total_alerts,
                        "avg_r_multiple": calibration.avg_r_multiple,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }},
                    upsert=True
                )
            except Exception as e:
                logger.error(f"Error saving threshold for {setup_type}: {e}")
                
        # 2. If DynamicThresholdService is available, also set there
        # This affects the TQS calculations in real-time
        if self._dynamic_thresholds:
            try:
                # Map the threshold to TQS adjustment
                # If threshold > 1.0, we need higher TQS (be more selective)
                # If threshold < 1.0, we can accept lower TQS
                
                # Store setup-specific threshold adjustment
                # This will be queried during TQS calculation
                tqs_adjustment = (new_threshold - 1.0) * 10  # Scale: 1.3 → +3, 0.95 → -0.5
                self._dynamic_thresholds._custom_thresholds[f"tqs_{setup_type}"] = tqs_adjustment
                
            except Exception as e:
                logger.warning(f"Could not set dynamic threshold for {setup_type}: {e}")

    # =========================================================================
    # CONNECTION 4: Predictions → Outcome Verification
    # =========================================================================
    
    async def sync_predictions_verification(self) -> Dict[str, Any]:
        """
        Trigger verification of pending predictions against actual outcomes.
        """
        conn = self._connections["predictions_to_verification"]
        
        if not conn.is_connected:
            return {"success": False, "error": "Connection not available"}
            
        try:
            if self._timeseries_ai is None:
                return {"success": False, "error": "Time-series AI not available"}
                
            result = await self._timeseries_ai.verify_pending_predictions()
            
            # Update connection status
            conn.last_sync = datetime.now(timezone.utc).isoformat()
            conn.records_synced += result.get("verified", 0)
            conn.health = "healthy"
            self._save_connection_state("predictions_to_verification")
            
            return {
                "success": True,
                "verified": result.get("verified", 0),
                "result": result
            }
            
        except Exception as e:
            logger.error(f"Error syncing predictions verification: {e}")
            conn.health = "degraded"
            conn.error_message = str(e)
            return {"success": False, "error": str(e)}

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    def _log_calibration(self, calibration_type: str, data: Dict[str, Any]):
        """Log calibration event to database"""
        if self._calibration_col is None:
            return
            
        try:
            self._calibration_col.insert_one({
                "calibration_type": calibration_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data
            })
        except Exception as e:
            logger.error(f"Error logging calibration: {e}")
            
    async def run_full_sync(self) -> Dict[str, Any]:
        """Run all learning connections"""
        results = {}
        
        # Run syncs in sequence to avoid overwhelming the system
        logger.info("Starting full learning sync...")
        
        # 1. Verify predictions first
        results["predictions_verification"] = await self.sync_predictions_verification()
        
        # 2. Shadow to weights
        results["shadow_to_weights"] = await self.sync_shadow_to_weights()
        
        # 3. Outcomes to scanner
        results["outcomes_to_scanner"] = await self.sync_outcomes_to_scanner()
        
        # 4. Simulation to model (only if we have new data)
        results["simulation_to_model"] = await self.sync_simulation_to_model()
        
        logger.info(f"Full learning sync complete: {results}")
        
        return {
            "success": True,
            "sync_results": results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    def get_connection_status(self) -> Dict[str, Any]:
        """Get status of all learning connections"""
        self._update_connection_health()
        
        connections = [conn.to_dict() for conn in self._connections.values()]
        healthy = sum(1 for c in self._connections.values() if c.health == "healthy")
        
        return {
            "connections": connections,
            "summary": {
                "total": len(connections),
                "healthy": healthy,
                "degraded": sum(1 for c in self._connections.values() if c.health == "degraded"),
                "disconnected": sum(1 for c in self._connections.values() if c.health == "disconnected"),
                "health_pct": (healthy / len(connections) * 100) if connections else 0
            }
        }
        
    def get_learning_metrics(self) -> LearningMetrics:
        """Get overall learning system metrics"""
        metrics = LearningMetrics()
        
        if self._db is not None:
            try:
                # Count data points
                metrics.total_data_points = (
                    self._db["simulated_trades"].count_documents({}) +
                    self._db["shadow_decisions"].count_documents({}) +
                    self._db["alert_outcomes"].count_documents({}) +
                    self._db["trade_outcomes"].count_documents({})
                )
                
                # Count used for training
                metrics.data_points_used_for_training = (
                    self._db["simulated_trades"].count_documents({"used_for_training": True})
                )
                
                # Count model versions
                if self._timeseries_ai:
                    status = self._timeseries_ai.get_status()
                    version_str = status.get("model", {}).get("version", "0.0.0")
                    try:
                        metrics.model_versions_created = int(version_str.replace("v", "").split(".")[1])
                    except (ValueError, IndexError):
                        metrics.model_versions_created = 0
                        
                # Count calibrations
                metrics.calibrations_applied = self._calibration_col.count_documents({}) if self._calibration_col else 0
                
            except Exception as e:
                logger.error(f"Error getting learning metrics: {e}")
                
        # Connection health
        status = self.get_connection_status()
        metrics.connections_healthy = status["summary"]["healthy"]
        metrics.connections_total = status["summary"]["total"]
        
        return metrics
        
    def get_calibration_history(self, calibration_type: str = None, limit: int = 20) -> List[Dict]:
        """Get calibration history"""
        if self._calibration_col is None:
            return []
            
        try:
            query = {}
            if calibration_type:
                query["calibration_type"] = calibration_type
                
            results = list(
                self._calibration_col.find(query, {"_id": 0})
                .sort("timestamp", -1)
                .limit(limit)
            )
            return results
        except Exception as e:
            logger.error(f"Error getting calibration history: {e}")
            return []


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_learning_connectors: Optional[LearningConnectorsService] = None


def get_learning_connectors() -> LearningConnectorsService:
    """Get the singleton instance"""
    global _learning_connectors
    if _learning_connectors is None:
        _learning_connectors = LearningConnectorsService()
    return _learning_connectors


def init_learning_connectors(
    db=None,
    timeseries_ai=None,
    shadow_tracker=None,
    learning_loop=None,
    scanner=None,
    simulation_engine=None,
    dynamic_thresholds=None
) -> LearningConnectorsService:
    """Initialize the learning connectors service"""
    service = get_learning_connectors()
    service.set_db(db)
    service.set_services(
        timeseries_ai=timeseries_ai,
        shadow_tracker=shadow_tracker,
        learning_loop=learning_loop,
        scanner=scanner,
        simulation_engine=simulation_engine,
        dynamic_thresholds=dynamic_thresholds
    )
    return service
