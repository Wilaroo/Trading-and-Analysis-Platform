"""
EV Tracking Service - SMB Capital Style Expected Value Calculator & Workflow

This service implements the SMB Capital trading workflow:
1. Idea Generation → 2. Filter/Grade → 3. Trade Plan → 4. Execution → 5. Review/EV

Core formula: EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)

The service tracks R-multiples per setup and gates future trades based on EV.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from pymongo import MongoClient
import os

logger = logging.getLogger(__name__)


class WorkflowState(Enum):
    """SMB-style workflow states for trade lifecycle"""
    IDEA_GEN = "idea_gen"         # Initial scan/idea generation
    FILTER_GRADE = "filter_grade" # Filter by catalyst, grade A/B/C
    TRADE_PLAN = "trade_plan"     # Define entry, stops, targets
    EXECUTION = "execution"       # Live trade execution
    REVIEW_EV = "review_ev"       # Post-trade review & EV update


class EVGate(Enum):
    """EV-based gates for trade sizing decisions"""
    A_SIZE = "A_SIZE"           # EV > 0.5R - Go big
    GREENLIGHT = "GREENLIGHT"   # EV > 0.2R - Standard size
    CAUTIOUS = "CAUTIOUS"       # EV > 0R - Reduced size
    REVIEW = "REVIEW"           # EV < 0R - Need analysis
    DROP = "DROP"               # EV < -0.2R - Remove from playbook


@dataclass
class TradeIdea:
    """SMB-style trade idea with full context"""
    id: str
    ticker: str
    catalyst_score: float      # 1-10 score
    direction: str             # "long" or "short"
    setup_type: str            # e.g., "rubber_band", "breakout"
    
    # Big Picture (PlayBook thesis)
    big_picture: str = ""
    intraday_fundamental: str = ""
    technical_thesis: str = ""
    tape_read: str = ""
    intuition: str = ""
    
    # Grading
    grade: str = "B"           # A/B/C
    grade_score: int = 0       # Numeric score for grade
    grade_reasons: List[str] = field(default_factory=list)
    
    # Trade Plan
    entry_trigger: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    trail_stop: float = 0.0
    risk_r: float = 1.0
    reward_r: float = 2.0
    reasons_to_sell: List[str] = field(default_factory=list)
    
    # Size based on EV and grade
    base_shares: int = 100
    adjusted_shares: int = 100  # Modified by EV gate
    
    # Historical EV for this setup
    historical_ev_r: float = 0.0
    ev_gate: str = "GREENLIGHT"
    
    # Workflow state
    state: WorkflowState = WorkflowState.IDEA_GEN
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    executed_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    
    # Outcome
    outcome: Optional[str] = None  # "won", "lost", "scratched"
    actual_r_multiple: Optional[float] = None
    pnl: float = 0.0


@dataclass  
class EVTrackingRecord:
    """Record for EV calculation per setup"""
    setup_type: str
    
    # R-multiple outcomes
    r_outcomes: List[float] = field(default_factory=list)
    
    # Calculated metrics
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 1.0
    expected_value_r: float = 0.0
    profit_factor: float = 0.0
    
    # EV trend tracking
    ev_history: List[dict] = field(default_factory=list)  # [{date, ev}]
    ev_improving: bool = False
    
    # Grade-specific win rates
    a_grade_trades: int = 0
    a_grade_wins: int = 0
    b_grade_trades: int = 0
    b_grade_wins: int = 0
    c_grade_trades: int = 0
    c_grade_wins: int = 0
    
    # SMB sizing recommendation
    ev_gate: EVGate = EVGate.GREENLIGHT
    size_multiplier: float = 1.0
    
    last_updated: str = ""


class EVTrackingService:
    """
    SMB Capital-style EV Tracking and Workflow Management
    
    Core responsibilities:
    1. Calculate Expected Value per setup using R-multiples
    2. Track trade ideas through SMB workflow states
    3. Gate trades based on historical EV
    4. Recommend position sizing based on edge quality
    """
    
    # SMB's 20 core setups
    SMB_SETUPS = [
        "changing_fundamentals",
        "breakout",
        "big_dawg",
        "technical_analysis",
        "opening_drive",
        "ipo_trade",
        "second_day",
        "elite_101",
        "return_pullback",
        "scalp",
        "stuffed",
        "multiple_timeframe_support",
        "dr_s",
        "market_play",
        "breaking_news",
        "bounce",
        "gap_and_go",
        "low_float",
        "stock_filters",
        "vwap_shark",
        # Our additional setups
        "rubber_band",
        "vwap_bounce",
        "vwap_fade",
        "orb",
        "hitchhiker",
        "spencer_scalp",
        "fashionably_late",
        "second_chance",
        "hod_breakout",
    ]
    
    def __init__(self, db=None):
        self.db = db
        self._ev_records: Dict[str, EVTrackingRecord] = {}
        self._active_ideas: Dict[str, TradeIdea] = {}
        
        # Initialize MongoDB collections
        if self.db is not None:
            self.ev_collection = self.db["ev_tracking"]
            self.ideas_collection = self.db["trade_ideas"]
            self._load_ev_records()
        else:
            self.ev_collection = None
            self.ideas_collection = None
        
        # Initialize EV records for all setups
        self._init_ev_records()
        
        logger.info("📊 EV Tracking Service initialized with SMB workflow")
    
    def _init_ev_records(self):
        """Initialize EV records for all SMB setups"""
        for setup in self.SMB_SETUPS:
            if setup not in self._ev_records:
                self._ev_records[setup] = EVTrackingRecord(setup_type=setup)
    
    def _load_ev_records(self):
        """Load EV records from database"""
        if self.ev_collection is None:
            return
        
        try:
            for doc in self.ev_collection.find():
                setup = doc.get("setup_type")
                if setup:
                    self._ev_records[setup] = EVTrackingRecord(
                        setup_type=setup,
                        r_outcomes=doc.get("r_outcomes", []),
                        total_trades=doc.get("total_trades", 0),
                        wins=doc.get("wins", 0),
                        losses=doc.get("losses", 0),
                        win_rate=doc.get("win_rate", 0.0),
                        avg_win_r=doc.get("avg_win_r", 0.0),
                        avg_loss_r=doc.get("avg_loss_r", 1.0),
                        expected_value_r=doc.get("expected_value_r", 0.0),
                        profit_factor=doc.get("profit_factor", 0.0),
                        ev_history=doc.get("ev_history", []),
                        a_grade_trades=doc.get("a_grade_trades", 0),
                        a_grade_wins=doc.get("a_grade_wins", 0),
                        b_grade_trades=doc.get("b_grade_trades", 0),
                        b_grade_wins=doc.get("b_grade_wins", 0),
                    )
            logger.info(f"Loaded EV records for {len(self._ev_records)} setups")
        except Exception as e:
            logger.warning(f"Could not load EV records: {e}")
    
    def _save_ev_record(self, setup_type: str):
        """Save EV record to database"""
        if self.ev_collection is None or setup_type not in self._ev_records:
            return
        
        record = self._ev_records[setup_type]
        try:
            self.ev_collection.update_one(
                {"setup_type": setup_type},
                {"$set": asdict(record)},
                upsert=True
            )
        except Exception as e:
            logger.warning(f"Could not save EV record: {e}")
    
    # ==================== EV CALCULATION (SMB Formula) ====================
    
    def calculate_ev(self, setup_type: str) -> float:
        """
        Calculate Expected Value using SMB's formula:
        EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)
        """
        if setup_type not in self._ev_records:
            return 0.0
        
        record = self._ev_records[setup_type]
        
        # Need minimum sample size
        if record.total_trades < 5:
            return 0.0
        
        # Calculate from R-outcomes
        wins_r = [r for r in record.r_outcomes if r > 0]
        losses_r = [r for r in record.r_outcomes if r <= 0]
        
        if wins_r:
            record.avg_win_r = sum(wins_r) / len(wins_r)
        if losses_r:
            record.avg_loss_r = abs(sum(losses_r) / len(losses_r))
        
        record.win_rate = record.wins / record.total_trades if record.total_trades > 0 else 0
        loss_rate = 1 - record.win_rate
        
        # SMB EV Formula
        record.expected_value_r = (record.win_rate * record.avg_win_r) - (loss_rate * record.avg_loss_r)
        
        # Calculate profit factor
        total_wins = sum(wins_r) if wins_r else 0
        total_losses = abs(sum(losses_r)) if losses_r else 1
        record.profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Update EV history
        record.ev_history.append({
            "date": datetime.now(timezone.utc).isoformat(),
            "ev": record.expected_value_r,
            "sample_size": record.total_trades
        })
        if len(record.ev_history) > 100:
            record.ev_history = record.ev_history[-100:]
        
        # Determine if EV is improving
        if len(record.ev_history) >= 10:
            recent_ev = sum(h["ev"] for h in record.ev_history[-5:]) / 5
            older_ev = sum(h["ev"] for h in record.ev_history[-10:-5]) / 5
            record.ev_improving = recent_ev > older_ev
        
        # Set EV gate for sizing
        record.ev_gate = self._determine_ev_gate(record.expected_value_r)
        record.size_multiplier = self._get_size_multiplier(record.ev_gate)
        
        record.last_updated = datetime.now(timezone.utc).isoformat()
        self._save_ev_record(setup_type)
        
        return record.expected_value_r
    
    def _determine_ev_gate(self, ev: float) -> EVGate:
        """Determine EV gate based on expected value"""
        if ev > 0.5:
            return EVGate.A_SIZE
        elif ev > 0.2:
            return EVGate.GREENLIGHT
        elif ev > 0:
            return EVGate.CAUTIOUS
        elif ev > -0.2:
            return EVGate.REVIEW
        else:
            return EVGate.DROP
    
    def _get_size_multiplier(self, gate: EVGate) -> float:
        """Get position size multiplier based on EV gate"""
        multipliers = {
            EVGate.A_SIZE: 1.5,      # 150% of base size
            EVGate.GREENLIGHT: 1.0,  # 100% standard
            EVGate.CAUTIOUS: 0.5,    # 50% reduced
            EVGate.REVIEW: 0.25,     # 25% minimal
            EVGate.DROP: 0.0         # Don't trade
        }
        return multipliers.get(gate, 1.0)
    
    # ==================== RECORD TRADE OUTCOME ====================
    
    def record_trade_outcome(
        self, 
        setup_type: str, 
        r_multiple: float, 
        grade: str = "B",
        outcome: str = "won"
    ):
        """
        Record a trade outcome for EV calculation.
        
        Args:
            setup_type: The setup/strategy type
            r_multiple: The R-multiple achieved (positive for wins, negative for losses)
            grade: Trade grade (A/B/C)
            outcome: "won", "lost", or "scratched"
        """
        if setup_type not in self._ev_records:
            self._ev_records[setup_type] = EVTrackingRecord(setup_type=setup_type)
        
        record = self._ev_records[setup_type]
        
        # Add R-multiple to history
        record.r_outcomes.append(r_multiple)
        if len(record.r_outcomes) > 200:  # Keep last 200 trades
            record.r_outcomes = record.r_outcomes[-200:]
        
        record.total_trades += 1
        
        if outcome == "won":
            record.wins += 1
        elif outcome == "lost":
            record.losses += 1
        
        # Track by grade
        if grade == "A":
            record.a_grade_trades += 1
            if outcome == "won":
                record.a_grade_wins += 1
        elif grade == "B":
            record.b_grade_trades += 1
            if outcome == "won":
                record.b_grade_wins += 1
        else:
            record.c_grade_trades += 1
            if outcome == "won":
                record.c_grade_wins += 1
        
        # Recalculate EV
        self.calculate_ev(setup_type)
        
        logger.info(f"📈 Recorded {outcome} ({r_multiple:+.2f}R) for {setup_type}. "
                   f"EV now: {record.expected_value_r:.2f}R, Gate: {record.ev_gate.value}")
    
    # ==================== SMB WORKFLOW STATE MACHINE ====================
    
    def create_idea(
        self,
        ticker: str,
        setup_type: str,
        direction: str,
        catalyst_score: float,
        big_picture: str = "",
        technical_thesis: str = ""
    ) -> TradeIdea:
        """
        Step 1: Create a new trade idea (Idea Generation)
        """
        idea_id = f"{ticker}_{setup_type}_{datetime.now().strftime('%H%M%S')}"
        
        # Get historical EV for this setup
        ev = self.calculate_ev(setup_type) if setup_type in self._ev_records else 0.0
        ev_record = self._ev_records.get(setup_type, EVTrackingRecord(setup_type=setup_type))
        
        idea = TradeIdea(
            id=idea_id,
            ticker=ticker,
            setup_type=setup_type,
            direction=direction,
            catalyst_score=catalyst_score,
            big_picture=big_picture,
            technical_thesis=technical_thesis,
            historical_ev_r=ev,
            ev_gate=ev_record.ev_gate.value if ev_record else "GREENLIGHT",
            state=WorkflowState.IDEA_GEN
        )
        
        self._active_ideas[idea_id] = idea
        
        logger.info(f"💡 Idea created: {ticker} {setup_type} (Catalyst: {catalyst_score}/10, EV: {ev:.2f}R)")
        return idea
    
    def filter_and_grade(self, idea_id: str, market_context_score: float = 0.5) -> Optional[TradeIdea]:
        """
        Step 2: Filter the idea and assign A/B/C grade
        
        Returns None if idea should be dropped.
        """
        if idea_id not in self._active_ideas:
            return None
        
        idea = self._active_ideas[idea_id]
        
        # Filter: Drop if catalyst score too low
        if idea.catalyst_score < 5:
            logger.info(f"❌ Idea {idea.ticker} dropped: Low catalyst score ({idea.catalyst_score}/10)")
            del self._active_ideas[idea_id]
            return None
        
        # Filter: Drop if EV gate is DROP
        if idea.ev_gate == "DROP":
            logger.info(f"❌ Idea {idea.ticker} dropped: Negative EV for {idea.setup_type}")
            del self._active_ideas[idea_id]
            return None
        
        # Grade the idea
        score = 0
        reasons = []
        
        # Catalyst strength (30 points max)
        if idea.catalyst_score >= 9:
            score += 30
            reasons.append(f"Strong catalyst ({idea.catalyst_score}/10)")
        elif idea.catalyst_score >= 7:
            score += 20
            reasons.append(f"Good catalyst ({idea.catalyst_score}/10)")
        else:
            score += 10
            reasons.append(f"Moderate catalyst ({idea.catalyst_score}/10)")
        
        # Historical EV (30 points max)
        if idea.historical_ev_r > 0.5:
            score += 30
            reasons.append(f"Strong EV: {idea.historical_ev_r:.2f}R")
        elif idea.historical_ev_r > 0.2:
            score += 20
            reasons.append(f"Positive EV: {idea.historical_ev_r:.2f}R")
        elif idea.historical_ev_r > 0:
            score += 10
            reasons.append(f"Marginal EV: {idea.historical_ev_r:.2f}R")
        
        # Market context (20 points max)
        if market_context_score > 0.7:
            score += 20
            reasons.append("Favorable market context")
        elif market_context_score > 0.4:
            score += 10
        
        # Projected R:R (20 points max)
        if idea.reward_r >= 3:
            score += 20
            reasons.append(f"Excellent R:R {idea.reward_r}:1")
        elif idea.reward_r >= 2:
            score += 15
            reasons.append(f"Good R:R {idea.reward_r}:1")
        
        # Determine grade
        if score >= 70:
            idea.grade = "A"
        elif score >= 45:
            idea.grade = "B"
        else:
            idea.grade = "C"
        
        idea.grade_score = score
        idea.grade_reasons = reasons
        idea.state = WorkflowState.FILTER_GRADE
        
        logger.info(f"📋 Graded {idea.ticker}: {idea.grade} ({score} points) - {', '.join(reasons[:3])}")
        return idea
    
    def create_trade_plan(
        self,
        idea_id: str,
        entry_trigger: float,
        stop_loss: float,
        target_1: float,
        target_2: float = None,
        reasons_to_sell: List[str] = None,
        base_shares: int = 100
    ) -> Optional[TradeIdea]:
        """
        Step 3: Create the trade plan with entries, stops, and targets
        """
        if idea_id not in self._active_ideas:
            return None
        
        idea = self._active_ideas[idea_id]
        
        idea.entry_trigger = entry_trigger
        idea.stop_loss = stop_loss
        idea.target_1 = target_1
        idea.target_2 = target_2 or target_1 * 1.5
        idea.reasons_to_sell = reasons_to_sell or [
            "Target hit",
            "Stop triggered",
            "Thesis invalidated",
            "Time stop (EOD)",
            "Tape deteriorates"
        ]
        
        # Calculate R-multiple
        risk = abs(entry_trigger - stop_loss)
        reward = abs(target_1 - entry_trigger)
        idea.risk_r = 1.0
        idea.reward_r = reward / risk if risk > 0 else 1.0
        
        # Adjust shares based on EV gate
        ev_record = self._ev_records.get(idea.setup_type, EVTrackingRecord(setup_type=idea.setup_type))
        idea.base_shares = base_shares
        idea.adjusted_shares = int(base_shares * ev_record.size_multiplier)
        
        # Additional sizing for A-grade trades
        if idea.grade == "A":
            idea.adjusted_shares = int(idea.adjusted_shares * 1.2)
        elif idea.grade == "C":
            idea.adjusted_shares = int(idea.adjusted_shares * 0.7)
        
        idea.state = WorkflowState.TRADE_PLAN
        
        logger.info(f"📝 Trade plan created: {idea.ticker} Entry ${entry_trigger:.2f}, "
                   f"Stop ${stop_loss:.2f}, Target ${target_1:.2f}, "
                   f"R:R {idea.reward_r:.1f}:1, Shares: {idea.adjusted_shares}")
        return idea
    
    def execute_trade(self, idea_id: str) -> Optional[TradeIdea]:
        """
        Step 4: Mark the idea as executed
        """
        if idea_id not in self._active_ideas:
            return None
        
        idea = self._active_ideas[idea_id]
        idea.state = WorkflowState.EXECUTION
        idea.executed_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"🎯 Executed: {idea.ticker} {idea.direction} x{idea.adjusted_shares} "
                   f"@ ${idea.entry_trigger:.2f}")
        return idea
    
    def review_trade(
        self,
        idea_id: str,
        outcome: str,
        exit_price: float,
        actual_pnl: float = 0.0
    ) -> Optional[TradeIdea]:
        """
        Step 5: Review the trade, record R-multiple, update EV
        """
        if idea_id not in self._active_ideas:
            return None
        
        idea = self._active_ideas[idea_id]
        
        # Calculate actual R-multiple
        risk = abs(idea.entry_trigger - idea.stop_loss)
        if idea.direction == "long":
            profit = exit_price - idea.entry_trigger
        else:
            profit = idea.entry_trigger - exit_price
        
        r_multiple = profit / risk if risk > 0 else 0
        
        idea.outcome = outcome
        idea.actual_r_multiple = r_multiple
        idea.pnl = actual_pnl
        idea.state = WorkflowState.REVIEW_EV
        idea.reviewed_at = datetime.now(timezone.utc).isoformat()
        
        # Record for EV calculation
        self.record_trade_outcome(
            setup_type=idea.setup_type,
            r_multiple=r_multiple,
            grade=idea.grade,
            outcome=outcome
        )
        
        # Get updated EV assessment
        ev_record = self._ev_records.get(idea.setup_type)
        ev_status = f"EV: {ev_record.expected_value_r:.2f}R" if ev_record else "N/A"
        ev_gate = ev_record.ev_gate.value if ev_record else "UNKNOWN"
        
        logger.info(f"📊 Review: {idea.ticker} {outcome.upper()} ({r_multiple:+.2f}R), "
                   f"Grade: {idea.grade}, Setup: {idea.setup_type}, "
                   f"{ev_status}, Gate: {ev_gate}")
        
        # Save to database
        if self.ideas_collection is not None:
            try:
                self.ideas_collection.insert_one(asdict(idea))
            except Exception as e:
                logger.warning(f"Could not save trade idea: {e}")
        
        # Clean up
        del self._active_ideas[idea_id]
        
        return idea
    
    # ==================== EV REPORTS ====================
    
    def get_ev_report(self, setup_type: str = None) -> Dict:
        """Get EV report for one or all setups"""
        if setup_type:
            if setup_type in self._ev_records:
                record = self._ev_records[setup_type]
                return {
                    "setup_type": setup_type,
                    "total_trades": record.total_trades,
                    "win_rate": record.win_rate,
                    "avg_win_r": record.avg_win_r,
                    "avg_loss_r": record.avg_loss_r,
                    "expected_value_r": record.expected_value_r,
                    "profit_factor": record.profit_factor,
                    "ev_gate": record.ev_gate.value,
                    "size_multiplier": record.size_multiplier,
                    "ev_improving": record.ev_improving,
                    "ev_trend": record.ev_history[-10:] if record.ev_history else [],
                    "a_grade_win_rate": record.a_grade_wins / record.a_grade_trades if record.a_grade_trades > 0 else 0,
                    "b_grade_win_rate": record.b_grade_wins / record.b_grade_trades if record.b_grade_trades > 0 else 0,
                    "recommendation": self._get_recommendation(record),
                    "min_sample_reached": record.total_trades >= 10
                }
            return {}
        
        # Return all setups
        return {
            setup: self.get_ev_report(setup) 
            for setup in self._ev_records.keys()
            if self._ev_records[setup].total_trades > 0
        }
    
    def _get_recommendation(self, record: EVTrackingRecord) -> str:
        """Get trading recommendation based on EV"""
        if record.total_trades < 10:
            return "TRACK - Need 10+ trades for reliable EV"
        
        if record.ev_gate == EVGate.A_SIZE:
            return "A-SIZE - Strong edge, increase position size"
        elif record.ev_gate == EVGate.GREENLIGHT:
            return "GREENLIGHT - Positive edge, continue trading"
        elif record.ev_gate == EVGate.CAUTIOUS:
            return "CAUTIOUS - Marginal edge, reduce size"
        elif record.ev_gate == EVGate.REVIEW:
            return "REVIEW - Needs analysis, minimal size"
        else:
            return "DROP - Remove from PlayBook"
    
    def get_playbook_summary(self) -> Dict:
        """Get PlayBook summary with EV status for all setups"""
        positive_ev = []
        negative_ev = []
        tracking = []
        
        for setup, record in self._ev_records.items():
            if record.total_trades < 10:
                tracking.append({
                    "setup": setup,
                    "trades": record.total_trades,
                    "status": "tracking"
                })
            elif record.expected_value_r > 0:
                positive_ev.append({
                    "setup": setup,
                    "ev_r": record.expected_value_r,
                    "win_rate": record.win_rate,
                    "gate": record.ev_gate.value,
                    "trades": record.total_trades
                })
            else:
                negative_ev.append({
                    "setup": setup,
                    "ev_r": record.expected_value_r,
                    "win_rate": record.win_rate,
                    "gate": record.ev_gate.value,
                    "trades": record.total_trades
                })
        
        # Sort by EV
        positive_ev.sort(key=lambda x: x["ev_r"], reverse=True)
        negative_ev.sort(key=lambda x: x["ev_r"])
        
        return {
            "positive_ev_setups": positive_ev,
            "negative_ev_setups": negative_ev,
            "tracking_setups": tracking,
            "total_setups_tracked": len(self._ev_records),
            "setups_with_edge": len(positive_ev),
            "setups_to_review": len(negative_ev)
        }


# Singleton instance
_ev_service: Optional[EVTrackingService] = None


def get_ev_service(db=None) -> EVTrackingService:
    """Get or create the EV tracking service singleton"""
    global _ev_service
    if _ev_service is None:
        _ev_service = EVTrackingService(db)
    return _ev_service
