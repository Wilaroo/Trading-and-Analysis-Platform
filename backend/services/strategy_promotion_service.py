"""
Strategy Promotion Service - Autonomous Learning Loop

Implements the full autonomous loop:
1. SIMULATION: Strategy runs on historical data
2. PAPER: Strategy runs in real-time but trades are not executed (tracked separately)
3. LIVE: Strategy executes real trades

Strategies automatically progress through phases based on performance:
- Simulation → Paper: If simulation shows positive edge (win rate > 50%, avg R > 0.5)
- Paper → Live: If paper trading confirms edge (win rate > 52%, avg R > 0.3, N > 20 trades)
- Live → Demoted: If live performance degrades significantly

Human approval required for:
- Final promotion to LIVE (safety gate)
- Demotion from LIVE to PAPER
"""

import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class StrategyPhase(str, Enum):
    """Strategy lifecycle phase"""
    SIMULATION = "simulation"    # Testing on historical data
    PAPER = "paper"              # Real-time tracking without execution
    LIVE = "live"                # Real money execution
    DEMOTED = "demoted"          # Was live, now demoted due to poor performance
    DISABLED = "disabled"        # Manually disabled


@dataclass
class PhaseRequirements:
    """Requirements to progress to next phase"""
    min_trades: int = 20
    min_win_rate: float = 0.50
    min_avg_r: float = 0.3
    min_profit_factor: float = 1.2
    max_drawdown_pct: float = 0.15
    min_days_in_phase: int = 5


@dataclass
class StrategyPerformance:
    """Performance metrics for a strategy in a phase"""
    strategy_name: str
    phase: StrategyPhase
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_r_multiple: float = 0.0
    total_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    days_in_phase: int = 0
    phase_start_date: str = ""
    last_trade_date: str = ""
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "phase": self.phase.value
        }
        
    def meets_requirements(self, req: PhaseRequirements) -> tuple:
        """Check if performance meets promotion requirements"""
        issues = []
        
        if self.total_trades < req.min_trades:
            issues.append(f"Need {req.min_trades} trades, have {self.total_trades}")
        if self.win_rate < req.min_win_rate:
            issues.append(f"Win rate {self.win_rate:.1%} < {req.min_win_rate:.1%}")
        if self.avg_r_multiple < req.min_avg_r:
            issues.append(f"Avg R {self.avg_r_multiple:.2f} < {req.min_avg_r}")
        if self.profit_factor < req.min_profit_factor:
            issues.append(f"Profit factor {self.profit_factor:.2f} < {req.min_profit_factor}")
        if self.max_drawdown_pct > req.max_drawdown_pct:
            issues.append(f"Drawdown {self.max_drawdown_pct:.1%} > {req.max_drawdown_pct:.1%}")
        if self.days_in_phase < req.min_days_in_phase:
            issues.append(f"Only {self.days_in_phase} days in phase, need {req.min_days_in_phase}")
            
        return len(issues) == 0, issues


@dataclass
class PromotionCandidate:
    """A strategy eligible for promotion"""
    strategy_name: str
    current_phase: StrategyPhase
    target_phase: StrategyPhase
    performance: StrategyPerformance
    meets_requirements: bool
    issues: List[str] = field(default_factory=list)
    requires_human_approval: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "strategy_name": self.strategy_name,
            "current_phase": self.current_phase.value,
            "target_phase": self.target_phase.value,
            "performance": self.performance.to_dict(),
            "meets_requirements": self.meets_requirements,
            "issues": self.issues,
            "requires_human_approval": self.requires_human_approval
        }


class StrategyPromotionService:
    """
    Manages strategy lifecycle through Simulation → Paper → Live phases.
    
    Usage:
        service = get_strategy_promotion_service()
        service.set_db(db)
        
        # Check for promotion candidates
        candidates = await service.get_promotion_candidates()
        
        # Promote a strategy (auto or with approval)
        await service.promote_strategy("bull_flag", StrategyPhase.PAPER)
    """
    
    COLLECTION_NAME = "strategy_phases"
    PAPER_TRADES_COLLECTION = "paper_trades"
    
    # Requirements for each phase transition
    PROMOTION_REQUIREMENTS = {
        # Simulation → Paper
        (StrategyPhase.SIMULATION, StrategyPhase.PAPER): PhaseRequirements(
            min_trades=50,
            min_win_rate=0.48,
            min_avg_r=0.3,
            min_profit_factor=1.1,
            max_drawdown_pct=0.20,
            min_days_in_phase=0  # Simulations don't have real days
        ),
        # Paper → Live (stricter)
        (StrategyPhase.PAPER, StrategyPhase.LIVE): PhaseRequirements(
            min_trades=20,
            min_win_rate=0.52,
            min_avg_r=0.4,
            min_profit_factor=1.3,
            max_drawdown_pct=0.12,
            min_days_in_phase=5
        )
    }
    
    def __init__(self):
        self._db = None
        self._phases_col = None
        self._paper_trades_col = None
        self._strategy_phases: Dict[str, StrategyPhase] = {}
        self._paper_account_mode = True  # When True, all strategies execute as LIVE (for IB paper account testing)
        
    def set_db(self, db):
        """Set database connection"""
        if db is None:
            return
            
        self._db = db
        self._phases_col = db[self.COLLECTION_NAME]
        self._paper_trades_col = db[self.PAPER_TRADES_COLLECTION]
        
        # Create indexes
        self._phases_col.create_index("strategy_name", unique=True)
        self._paper_trades_col.create_index([("strategy_name", 1), ("timestamp", -1)])
        self._paper_trades_col.create_index("timestamp")
        
        # Load existing phases
        self._load_phases()
        logger.info("StrategyPromotionService connected to database")
        
    def _load_phases(self):
        """Load strategy phases from database"""
        if self._phases_col is None:
            return
            
        try:
            for doc in self._phases_col.find():
                name = doc.get("strategy_name")
                phase = doc.get("phase", "simulation")
                if name:
                    self._strategy_phases[name] = StrategyPhase(phase)
        except Exception as e:
            logger.error(f"Error loading strategy phases: {e}")
            
    def get_strategy_phase(self, strategy_name: str) -> StrategyPhase:
        """Get current phase for a strategy (default: SIMULATION)"""
        return self._strategy_phases.get(strategy_name, StrategyPhase.SIMULATION)
        
    def set_strategy_phase(self, strategy_name: str, phase: StrategyPhase, reason: str = ""):
        """Set phase for a strategy"""
        self._strategy_phases[strategy_name] = phase
        
        if self._phases_col is not None:
            self._phases_col.update_one(
                {"strategy_name": strategy_name},
                {"$set": {
                    "strategy_name": strategy_name,
                    "phase": phase.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "reason": reason
                },
                "$push": {
                    "history": {
                        "phase": phase.value,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "reason": reason
                    }
                }},
                upsert=True
            )
            
        logger.info(f"Strategy '{strategy_name}' phase set to {phase.value}: {reason}")
        
    def record_paper_trade(
        self,
        strategy_name: str,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float = None,
        stop_price: float = None,
        target_price: float = None,
        r_multiple: float = None,
        outcome: str = "open",
        notes: str = ""
    ) -> str:
        """
        Record a paper trade (simulated real-time trade).
        
        This is called when the trading bot would have taken a trade
        but the strategy is in PAPER phase.
        """
        if self._paper_trades_col is None:
            return ""
            
        trade_id = f"paper_{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}"
        
        trade = {
            "trade_id": trade_id,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "r_multiple": r_multiple,
            "outcome": outcome,  # "open", "win", "loss", "breakeven"
            "notes": notes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "closed_at": None
        }
        
        self._paper_trades_col.insert_one(trade)
        logger.info(f"Paper trade recorded: {trade_id} ({strategy_name} {direction} {symbol})")
        
        return trade_id
        
    def close_paper_trade(
        self,
        trade_id: str,
        exit_price: float,
        r_multiple: float,
        outcome: str
    ):
        """Close an open paper trade"""
        if self._paper_trades_col is None:
            return
            
        self._paper_trades_col.update_one(
            {"trade_id": trade_id},
            {"$set": {
                "exit_price": exit_price,
                "r_multiple": r_multiple,
                "outcome": outcome,
                "closed_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
    def get_strategy_performance(
        self,
        strategy_name: str,
        phase: StrategyPhase = None,
        days: int = 30
    ) -> StrategyPerformance:
        """
        Get performance metrics for a strategy.
        
        For SIMULATION phase: Uses simulation_results collection
        For PAPER phase: Uses paper_trades collection
        For LIVE phase: Uses trade_outcomes collection
        """
        if phase is None:
            phase = self.get_strategy_phase(strategy_name)
            
        perf = StrategyPerformance(
            strategy_name=strategy_name,
            phase=phase,
            phase_start_date=datetime.now(timezone.utc).isoformat()
        )
        
        if self._db is None:
            return perf
            
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        try:
            if phase == StrategyPhase.SIMULATION:
                # Get from simulation results
                trades = list(self._db["simulation_results"].find({
                    "setup_type": strategy_name,
                    "timestamp": {"$gte": cutoff.isoformat()}
                }))
            elif phase == StrategyPhase.PAPER:
                # Get from paper trades
                trades = list(self._paper_trades_col.find({
                    "strategy_name": strategy_name,
                    "outcome": {"$ne": "open"},
                    "timestamp": {"$gte": cutoff.isoformat()}
                }))
            else:  # LIVE
                # Get from real trade outcomes
                trades = list(self._db["trade_outcomes"].find({
                    "setup_type": strategy_name,
                    "timestamp": {"$gte": cutoff.isoformat()}
                }))
                
            if trades:
                perf.total_trades = len(trades)
                perf.winning_trades = len([t for t in trades if t.get("r_multiple", 0) > 0 or t.get("outcome") == "win"])
                perf.losing_trades = perf.total_trades - perf.winning_trades
                perf.win_rate = perf.winning_trades / perf.total_trades if perf.total_trades > 0 else 0
                
                r_multiples = [t.get("r_multiple", 0) for t in trades if t.get("r_multiple") is not None]
                if r_multiples:
                    perf.avg_r_multiple = sum(r_multiples) / len(r_multiples)
                    perf.total_r = sum(r_multiples)
                    
                    # Profit factor
                    wins = sum(r for r in r_multiples if r > 0)
                    losses = abs(sum(r for r in r_multiples if r < 0))
                    perf.profit_factor = wins / losses if losses > 0 else wins if wins > 0 else 0
                    
                # Get phase start date
                phase_doc = self._phases_col.find_one({"strategy_name": strategy_name})
                if phase_doc and "history" in phase_doc:
                    for h in reversed(phase_doc["history"]):
                        if h.get("phase") == phase.value:
                            perf.phase_start_date = h.get("timestamp", "")
                            start = datetime.fromisoformat(perf.phase_start_date.replace('Z', '+00:00'))
                            perf.days_in_phase = (datetime.now(timezone.utc) - start).days
                            break
                            
                if trades:
                    perf.last_trade_date = max(t.get("timestamp", "") for t in trades)
                    
        except Exception as e:
            logger.error(f"Error getting performance for {strategy_name}: {e}")
            
        return perf
        
    def get_promotion_candidates(self) -> List[PromotionCandidate]:
        """
        Find strategies eligible for promotion to next phase.
        
        Returns list of candidates with their performance and requirements status.
        """
        candidates = []
        
        # Get all strategies with phases
        all_strategies = set(self._strategy_phases.keys())
        
        # Also check simulation results for strategies not yet tracked
        if self._db is not None:
            sim_strategies = self._db["simulation_results"].distinct("setup_type")
            all_strategies.update(s for s in sim_strategies if s)
            
        for strategy_name in all_strategies:
            current_phase = self.get_strategy_phase(strategy_name)
            
            # Determine target phase
            if current_phase == StrategyPhase.SIMULATION:
                target_phase = StrategyPhase.PAPER
            elif current_phase == StrategyPhase.PAPER:
                target_phase = StrategyPhase.LIVE
            else:
                continue  # Already live or demoted
                
            # Get requirements
            req_key = (current_phase, target_phase)
            requirements = self.PROMOTION_REQUIREMENTS.get(req_key)
            if not requirements:
                continue
                
            # Get performance
            perf = self.get_strategy_performance(strategy_name, current_phase)
            
            # Check requirements
            meets, issues = perf.meets_requirements(requirements)
            
            candidate = PromotionCandidate(
                strategy_name=strategy_name,
                current_phase=current_phase,
                target_phase=target_phase,
                performance=perf,
                meets_requirements=meets,
                issues=issues,
                requires_human_approval=(target_phase == StrategyPhase.LIVE)
            )
            
            candidates.append(candidate)
            
        # Sort by readiness (those meeting requirements first)
        candidates.sort(key=lambda c: (not c.meets_requirements, c.strategy_name))
        
        return candidates
        
    def promote_strategy(
        self,
        strategy_name: str,
        target_phase: StrategyPhase,
        force: bool = False,
        approved_by: str = "system"
    ) -> Dict[str, Any]:
        """
        Promote a strategy to the next phase.
        
        Args:
            strategy_name: Name of the strategy
            target_phase: Target phase to promote to
            force: Skip requirement checks (for manual overrides)
            approved_by: Who approved this promotion
            
        Returns:
            Success status and details
        """
        current_phase = self.get_strategy_phase(strategy_name)
        
        # Validate transition
        valid_transitions = {
            StrategyPhase.SIMULATION: [StrategyPhase.PAPER],
            StrategyPhase.PAPER: [StrategyPhase.LIVE, StrategyPhase.SIMULATION],
            StrategyPhase.LIVE: [StrategyPhase.PAPER, StrategyPhase.DEMOTED],
            StrategyPhase.DEMOTED: [StrategyPhase.SIMULATION, StrategyPhase.PAPER]
        }
        
        if target_phase not in valid_transitions.get(current_phase, []):
            return {
                "success": False,
                "error": f"Invalid transition: {current_phase.value} → {target_phase.value}"
            }
            
        # Check requirements (unless forced)
        if not force:
            req_key = (current_phase, target_phase)
            requirements = self.PROMOTION_REQUIREMENTS.get(req_key)
            
            if requirements:
                perf = self.get_strategy_performance(strategy_name, current_phase)
                meets, issues = perf.meets_requirements(requirements)
                
                if not meets:
                    return {
                        "success": False,
                        "error": "Requirements not met",
                        "issues": issues,
                        "performance": perf.to_dict()
                    }
                    
        # Perform promotion
        reason = f"Promoted by {approved_by}" + (" (forced)" if force else "")
        self.set_strategy_phase(strategy_name, target_phase, reason)
        
        logger.info(f"🎉 Strategy '{strategy_name}' promoted: {current_phase.value} → {target_phase.value}")
        
        return {
            "success": True,
            "strategy_name": strategy_name,
            "previous_phase": current_phase.value,
            "new_phase": target_phase.value,
            "promoted_by": approved_by,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    def demote_strategy(
        self,
        strategy_name: str,
        reason: str = "Performance degradation"
    ) -> Dict[str, Any]:
        """Demote a strategy (usually from LIVE to PAPER or DEMOTED)"""
        current_phase = self.get_strategy_phase(strategy_name)
        
        if current_phase == StrategyPhase.LIVE:
            target = StrategyPhase.PAPER
        elif current_phase == StrategyPhase.PAPER:
            target = StrategyPhase.SIMULATION
        else:
            return {"success": False, "error": "Strategy not in a demotable phase"}
            
        self.set_strategy_phase(strategy_name, target, f"Demoted: {reason}")
        
        logger.warning(f"⚠️ Strategy '{strategy_name}' demoted: {current_phase.value} → {target.value}")
        
        return {
            "success": True,
            "strategy_name": strategy_name,
            "previous_phase": current_phase.value,
            "new_phase": target.value,
            "reason": reason
        }
        
    def get_all_phases(self) -> Dict[str, str]:
        """Get current phase for all tracked strategies"""
        return {name: phase.value for name, phase in self._strategy_phases.items()}
        
    def is_strategy_live(self, strategy_name: str) -> bool:
        """Check if a strategy is in LIVE phase"""
        return self.get_strategy_phase(strategy_name) == StrategyPhase.LIVE
        
    def is_strategy_paper(self, strategy_name: str) -> bool:
        """Check if a strategy is in PAPER phase"""
        return self.get_strategy_phase(strategy_name) == StrategyPhase.PAPER
        
    def should_execute_trade(self, strategy_name: str) -> tuple:
        """
        Determine if a trade should be executed for real.
        
        In paper_account_mode, ALL strategies execute as LIVE (for testing on IB paper account).
        When switching to real money, set paper_account_mode=False to enforce promotion gates.
        
        Returns:
            (should_execute: bool, reason: str, should_paper_track: bool)
        """
        # Paper account mode: bypass all promotion checks, execute everything
        if self._paper_account_mode:
            return True, "Paper account mode — all strategies execute as LIVE", False
        
        phase = self.get_strategy_phase(strategy_name)
        
        if phase == StrategyPhase.LIVE:
            return True, "Strategy is LIVE", False
        elif phase == StrategyPhase.PAPER:
            return False, "Strategy is in PAPER phase - tracking only", True
        elif phase == StrategyPhase.SIMULATION:
            return False, "Strategy is in SIMULATION phase - not ready for real-time", False
        else:
            return False, f"Strategy is {phase.value} - not trading", False
    
    def set_paper_account_mode(self, enabled: bool):
        """Toggle paper account mode. When enabled, all strategies bypass promotion checks."""
        self._paper_account_mode = enabled
        logger.info(f"Paper account mode: {'ENABLED — all strategies trade as LIVE' if enabled else 'DISABLED — promotion gates enforced'}")
    
    @property
    def is_paper_account_mode(self) -> bool:
        return self._paper_account_mode


# Singleton
_strategy_promotion_service: Optional[StrategyPromotionService] = None


def get_strategy_promotion_service() -> StrategyPromotionService:
    """Get singleton instance"""
    global _strategy_promotion_service
    if _strategy_promotion_service is None:
        _strategy_promotion_service = StrategyPromotionService()
    return _strategy_promotion_service


def init_strategy_promotion_service(db=None) -> StrategyPromotionService:
    """Initialize with database"""
    service = get_strategy_promotion_service()
    if db is not None:
        service.set_db(db)
    return service
