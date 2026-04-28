"""
Shadow Tracker Service - AI Decision Logging Without Execution

Extends shadow mode to track ALL AI module decisions for learning and analysis.
This is the persistence layer that logs:
- Bull/Bear debate outcomes
- AI Risk Manager assessments
- Institutional flow signals
- Time series predictions

All decisions are logged whether or not they result in actual trades.
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ShadowDecision:
    """A shadow-tracked AI decision"""
    id: str = ""
    
    # What triggered this decision
    symbol: str = ""
    trigger_type: str = ""  # "trade_opportunity", "position_review", "manual_query"
    trigger_time: str = ""
    
    # Market context at decision time
    price_at_decision: float = 0.0
    market_regime: str = ""
    vix_level: float = 0.0
    
    # Module contributions
    debate_result: Dict = field(default_factory=dict)  # {bull_score, bear_score, winner, reasoning}
    risk_assessment: Dict = field(default_factory=dict)  # {risk_score, factors, recommendation}
    institutional_context: Dict = field(default_factory=dict)  # {ownership_pct, flow_signal, etc}
    timeseries_forecast: Dict = field(default_factory=dict)  # {direction, probability, horizon}
    
    # Final decision
    combined_recommendation: str = ""  # "proceed", "pass", "reduce_size"
    confidence_score: float = 0.0
    reasoning: str = ""
    
    # Execution tracking
    was_executed: bool = False
    execution_reason: str = ""  # Why it was/wasn't executed
    trade_id: str = ""  # If executed, link to actual trade
    
    # Outcome tracking (for learning)
    outcome_tracked: bool = False
    outcome_time: str = ""
    outcome_price: float = 0.0
    would_have_pnl: float = 0.0
    would_have_r: float = 0.0
    actual_outcome: str = ""  # If executed, what happened
    
    # Metadata
    created_at: str = ""
    modules_used: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ShadowDecision":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ModulePerformance:
    """Performance metrics for a single AI module"""
    module_name: str = ""
    total_decisions: int = 0
    decisions_followed: int = 0  # Recommendation was followed
    decisions_correct: int = 0  # Outcome matched recommendation
    accuracy_rate: float = 0.0
    avg_confidence: float = 0.0
    avg_r_when_followed: float = 0.0
    avg_r_when_ignored: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class ShadowTracker:
    """
    Tracks all AI module decisions for learning and analysis.
    
    Key features:
    - Log every AI decision regardless of execution
    - Track outcomes to measure module accuracy
    - Compare "what would have happened" scenarios
    - Generate performance reports per module
    """
    
    COLLECTION_NAME = "shadow_decisions"
    PERFORMANCE_COLLECTION = "shadow_module_performance"
    
    def __init__(self):
        self._db = None
        self._decisions_col = None
        self._performance_col = None
        self._alpaca_service = None
        # 2026-04-28f: IB pusher quote source. Phase 4 retired Alpaca,
        # so without this the outcome tracker silently dies — every
        # decision sits in `outcome_tracked: false` forever, which
        # operator confirmed live (6,751 decisions / 0 outcomes).
        self._ib_data_provider = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._decisions_col = db[self.COLLECTION_NAME]
            self._performance_col = db[self.PERFORMANCE_COLLECTION]
            
            # Create indexes
            self._decisions_col.create_index([("symbol", 1), ("trigger_time", -1)])
            self._decisions_col.create_index([("outcome_tracked", 1)])
            self._decisions_col.create_index([("was_executed", 1)])
            self._decisions_col.create_index([("created_at", -1)])
            
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service for price tracking (legacy — superseded
        by IB pusher quotes after Phase 4. Kept for backward compat.)"""
        self._alpaca_service = alpaca_service

    def set_ib_data_provider(self, ib_data_provider):
        """Set the IB pusher quote source (preferred). Used by
        `_get_current_price` for outcome tracking after Phase 4
        retired Alpaca."""
        self._ib_data_provider = ib_data_provider
        
    async def log_decision(
        self,
        symbol: str,
        trigger_type: str,
        price_at_decision: float,
        market_regime: str = "",
        vix_level: float = 0.0,
        debate_result: Dict = None,
        risk_assessment: Dict = None,
        institutional_context: Dict = None,
        timeseries_forecast: Dict = None,
        combined_recommendation: str = "",
        confidence_score: float = 0.0,
        reasoning: str = "",
        was_executed: bool = False,
        execution_reason: str = "",
        trade_id: str = ""
    ) -> ShadowDecision:
        """
        Log an AI decision with all module contributions.
        """
        modules_used = []
        if debate_result:
            modules_used.append("debate_agents")
        if risk_assessment:
            modules_used.append("ai_risk_manager")
        if institutional_context:
            modules_used.append("institutional_flow")
        if timeseries_forecast:
            modules_used.append("timeseries_ai")
            
        decision = ShadowDecision(
            id=f"sd_{uuid.uuid4().hex[:12]}",
            symbol=symbol.upper(),
            trigger_type=trigger_type,
            trigger_time=datetime.now(timezone.utc).isoformat(),
            price_at_decision=price_at_decision,
            market_regime=market_regime,
            vix_level=vix_level,
            debate_result=debate_result or {},
            risk_assessment=risk_assessment or {},
            institutional_context=institutional_context or {},
            timeseries_forecast=timeseries_forecast or {},
            combined_recommendation=combined_recommendation,
            confidence_score=confidence_score,
            reasoning=reasoning,
            was_executed=was_executed,
            execution_reason=execution_reason,
            trade_id=trade_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            modules_used=modules_used
        )
        
        if self._decisions_col is not None:
            self._decisions_col.insert_one(decision.to_dict())
            logger.info(f"Shadow: Logged decision for {symbol} - {combined_recommendation} (executed={was_executed})")
            
        return decision
        
    async def update_outcome(
        self,
        decision_id: str,
        outcome_price: float,
        entry_price: float = None,
        stop_price: float = None,
        target_price: float = None,
        actual_outcome: str = ""
    ) -> Dict[str, Any]:
        """
        Update a decision with its outcome for learning.
        """
        if self._decisions_col is None:
            return {"success": False, "error": "Database not connected"}
            
        decision_doc = self._decisions_col.find_one({"id": decision_id})
        if not decision_doc:
            return {"success": False, "error": "Decision not found"}
            
        decision = ShadowDecision.from_dict(decision_doc)
        
        # Calculate would-have P&L if we have entry/stop/target
        entry = entry_price or decision.price_at_decision
        would_have_pnl = outcome_price - entry
        would_have_r = 0.0
        
        if stop_price and entry:
            risk = abs(entry - stop_price)
            if risk > 0:
                would_have_r = would_have_pnl / risk
                
        self._decisions_col.update_one(
            {"id": decision_id},
            {"$set": {
                "outcome_tracked": True,
                "outcome_time": datetime.now(timezone.utc).isoformat(),
                "outcome_price": outcome_price,
                "would_have_pnl": would_have_pnl,
                "would_have_r": would_have_r,
                "actual_outcome": actual_outcome
            }}
        )
        
        return {
            "success": True,
            "decision_id": decision_id,
            "would_have_pnl": would_have_pnl,
            "would_have_r": would_have_r
        }
        
    async def track_pending_outcomes(
        self, batch_size: int = 50, max_batches: int = 1
    ) -> Dict[str, Any]:
        """
        Check pending decisions and update outcomes.
        Call this periodically during market hours.

        2026-04-28f: now supports `batch_size` (default 50) and
        `max_batches` (default 1) so an operator can drain a backlog
        with a single curl. Old behaviour preserved when called with
        no args.
        """
        if self._decisions_col is None:
            return {"updated": 0, "pending_checked": 0, "batches": 0}

        total_updated = 0
        total_checked = 0
        batches_run = 0
        # Find decisions that haven't been tracked yet and are at least 1 hour old
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

        for _batch_idx in range(max_batches):
            pending = list(self._decisions_col.find({
                "outcome_tracked": False,
                "trigger_time": {"$lt": cutoff.isoformat()}
            }).limit(batch_size))

            if not pending:
                break
            batches_run += 1
            for doc in pending:
                try:
                    symbol = doc.get("symbol")
                    current_price = await self._get_current_price(symbol)

                    if current_price:
                        await self.update_outcome(
                            decision_id=doc.get("id"),
                            outcome_price=current_price
                        )
                        total_updated += 1
                except Exception as e:
                    logger.warning(f"Shadow: Failed to track outcome for {doc.get('id')}: {e}")
            total_checked += len(pending)

        return {
            "updated": total_updated,
            "pending_checked": total_checked,
            "batches": batches_run,
        }
        
    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol. Prefers IB pusher quote
        (post Phase-4); falls back to Alpaca legacy path if IB
        provider isn't injected."""
        # 2026-04-28f: IB pusher path — primary source after Phase 4
        # retired Alpaca. Without this the outcome tracker silently
        # never updated 6,751 shadow decisions on DGX.
        if self._ib_data_provider is not None:
            try:
                quote = await self._ib_data_provider.get_quote(symbol)
                if quote:
                    price = quote.get("price") or quote.get("last_price") or quote.get("close")
                    if price and float(price) > 0:
                        return float(price)
            except Exception as e:
                logger.warning(f"Shadow: IB pusher price fetch failed for {symbol}: {e}")

        # Legacy Alpaca path
        if self._alpaca_service is None:
            return None
        try:
            quote = await self._alpaca_service.get_quote(symbol)
            if quote:
                return quote.get("last_price") or quote.get("close", 0)
        except Exception as e:
            logger.warning(f"Shadow: Could not get price for {symbol}: {e}")
        return None
        
    async def get_decisions(
        self,
        symbol: str = None,
        module: str = None,
        was_executed: bool = None,
        recommendation: str = None,
        limit: int = 50
    ) -> List[ShadowDecision]:
        """Get shadow decisions with filters"""
        if self._decisions_col is None:
            return []
            
        query = {}
        if symbol:
            query["symbol"] = symbol.upper()
        if module:
            query["modules_used"] = module
        if was_executed is not None:
            query["was_executed"] = was_executed
        if recommendation:
            query["combined_recommendation"] = recommendation
            
        docs = list(
            self._decisions_col
            .find(query)
            .sort("created_at", -1)
            .limit(limit)
        )
        
        return [ShadowDecision.from_dict(d) for d in docs]
        
    async def get_module_performance(self, module: str, days: int = 30) -> ModulePerformance:
        """
        Calculate performance metrics for a specific module.
        """
        if self._decisions_col is None:
            return ModulePerformance(module_name=module)
            
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get all decisions using this module
        decisions = list(self._decisions_col.find({
            "modules_used": module,
            "outcome_tracked": True,
            "created_at": {"$gte": cutoff.isoformat()}
        }))
        
        if not decisions:
            return ModulePerformance(module_name=module)
            
        total = len(decisions)
        followed = sum(1 for d in decisions if d.get("was_executed"))
        
        # Calculate accuracy based on whether recommendation was correct
        correct = 0
        r_when_followed = []
        r_when_ignored = []
        confidences = []
        
        for d in decisions:
            recommendation = d.get("combined_recommendation", "")
            outcome_r = d.get("would_have_r", 0)
            
            # Determine if recommendation was correct
            if recommendation == "proceed" and outcome_r > 0:
                correct += 1
            elif recommendation == "pass" and outcome_r < 0:
                correct += 1
                
            # Track R by execution status
            if d.get("was_executed"):
                r_when_followed.append(outcome_r)
            else:
                r_when_ignored.append(outcome_r)
                
            confidences.append(d.get("confidence_score", 0))
            
        return ModulePerformance(
            module_name=module,
            total_decisions=total,
            decisions_followed=followed,
            decisions_correct=correct,
            accuracy_rate=correct / total if total > 0 else 0,
            avg_confidence=sum(confidences) / len(confidences) if confidences else 0,
            avg_r_when_followed=sum(r_when_followed) / len(r_when_followed) if r_when_followed else 0,
            avg_r_when_ignored=sum(r_when_ignored) / len(r_when_ignored) if r_when_ignored else 0
        )
        
    async def get_all_performance(self, days: int = 30) -> Dict[str, ModulePerformance]:
        """Get performance for all modules"""
        modules = ["debate_agents", "ai_risk_manager", "institutional_flow", "timeseries_ai"]
        results = {}
        
        for module in modules:
            results[module] = await self.get_module_performance(module, days)
            
        return results
        
    async def generate_learning_report(self, days: int = 30) -> Dict[str, Any]:
        """
        Generate a comprehensive learning report.
        Shows which modules are adding value and which need adjustment.
        """
        performance = await self.get_all_performance(days)
        
        # Analyze performance
        best_module = max(performance.values(), key=lambda p: p.accuracy_rate, default=None)
        worst_module = min(performance.values(), key=lambda p: p.accuracy_rate, default=None)
        
        # Recommendations
        recommendations = []
        for name, perf in performance.items():
            if perf.total_decisions < 10:
                recommendations.append(f"{name}: Insufficient data ({perf.total_decisions} decisions)")
            elif perf.accuracy_rate < 0.45:
                recommendations.append(f"{name}: Consider disabling (accuracy {perf.accuracy_rate*100:.1f}%)")
            elif perf.accuracy_rate > 0.60:
                recommendations.append(f"{name}: High performing (accuracy {perf.accuracy_rate*100:.1f}%)")
                
        # Compare followed vs ignored
        value_analysis = []
        for name, perf in performance.items():
            if perf.decisions_followed > 5 and perf.total_decisions - perf.decisions_followed > 5:
                diff = perf.avg_r_when_followed - perf.avg_r_when_ignored
                if diff > 0.5:
                    value_analysis.append(f"{name}: Following recommendations adds {diff:.2f}R on average")
                elif diff < -0.5:
                    value_analysis.append(f"{name}: Ignoring recommendations would be better by {-diff:.2f}R")
                    
        return {
            "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "period_days": days,
            "module_performance": {k: v.to_dict() for k, v in performance.items()},
            "best_module": best_module.module_name if best_module else None,
            "worst_module": worst_module.module_name if worst_module else None,
            "recommendations": recommendations,
            "value_analysis": value_analysis
        }
        
    def get_stats(self) -> Dict[str, Any]:
        """Get quick stats for dashboard — cached for 30s to avoid hammering MongoDB"""
        now = __import__('time').monotonic()

        # Return cached stats if fresh (< 30 seconds old)
        if hasattr(self, '_stats_cache') and hasattr(self, '_stats_cache_time'):
            if now - self._stats_cache_time < 30:
                return self._stats_cache

        stats = {
            "total_decisions": 0,
            "executed_decisions": 0,
            "shadow_only": 0,
            "outcomes_tracked": 0,
            "outcomes_pending": 0,
            "wins": 0,
            "win_rate": 0,
            "avg_confidence": 0.0,
            "db_connected": self._db is not None
        }

        if self._decisions_col is None:
            return stats

        try:
            # Single aggregation pipeline instead of 4+ count_documents calls
            pipeline = [
                {"$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "executed": {"$sum": {"$cond": ["$was_executed", 1, 0]}},
                    "tracked": {"$sum": {"$cond": ["$outcome_tracked", 1, 0]}},
                    "wins": {"$sum": {"$cond": [
                        {"$and": ["$outcome_tracked", {"$gt": ["$would_have_pnl", 0]}]},
                        1, 0
                    ]}},
                    "avg_conf": {"$avg": "$confidence_score"},
                }}
            ]
            result = list(self._decisions_col.aggregate(pipeline))
            if result:
                r = result[0]
                total = r.get("total", 0)
                executed = r.get("executed", 0)
                tracked = r.get("tracked", 0)
                wins = r.get("wins", 0)
                avg_conf = r.get("avg_conf", 0) or 0

                stats.update({
                    "total_decisions": total,
                    "executed_decisions": executed,
                    "shadow_only": total - executed,
                    "outcomes_tracked": tracked,
                    "outcomes_pending": total - tracked,
                    "wins": wins,
                    "win_rate": round((wins / tracked * 100) if tracked > 0 else 0, 1),
                    "avg_confidence": round(avg_conf, 2),
                })
        except Exception as e:
            logger.warning(f"Shadow stats aggregation error: {e}")

        # Cache it
        self._stats_cache = stats
        self._stats_cache_time = now
        return stats


# Singleton instance
_shadow_tracker: Optional[ShadowTracker] = None


def get_shadow_tracker() -> ShadowTracker:
    """Get singleton instance of Shadow Tracker"""
    global _shadow_tracker
    if _shadow_tracker is None:
        _shadow_tracker = ShadowTracker()
    return _shadow_tracker


def init_shadow_tracker(db=None, alpaca_service=None, ib_data_provider=None) -> ShadowTracker:
    """Initialize Shadow Tracker with dependencies"""
    tracker = get_shadow_tracker()
    if db is not None:
        tracker.set_db(db)
    if alpaca_service is not None:
        tracker.set_alpaca_service(alpaca_service)
    if ib_data_provider is not None:
        tracker.set_ib_data_provider(ib_data_provider)
    return tracker
