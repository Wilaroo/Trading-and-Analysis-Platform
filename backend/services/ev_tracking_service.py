"""
EV Tracking Service - SMB Capital Style Expected Value Calculator & Workflow

This service implements the SMB Capital trading workflow:
1. Idea Generation → 2. Filter/Grade → 3. Trade Plan → 4. Execution → 5. Review/EV

Core formula: EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)

The service tracks R-multiples per setup and gates future trades based on EV.
Integrates with S/R levels, targets, and stops for accurate R-multiple projections.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


# ==================== R-MULTIPLE CALCULATION UTILITIES ====================

@dataclass
class TradeLevels:
    """
    Key price levels for R-multiple calculation.
    Based on Support/Resistance analysis and ATR for volatility-adjusted stops.
    """
    entry_price: float
    stop_loss: float
    target_1: float                    # Primary target (1-2R typically)
    target_2: Optional[float] = None   # Extended target (2-3R)
    target_3: Optional[float] = None   # Runner target (3R+)
    
    # Key technical levels that inform the targets
    support: Optional[float] = None
    resistance: Optional[float] = None
    vwap: Optional[float] = None
    ema_9: Optional[float] = None
    ema_20: Optional[float] = None
    high_of_day: Optional[float] = None
    low_of_day: Optional[float] = None
    atr: Optional[float] = None
    
    def calculate_r_multiple(self, target_price: float = None) -> float:
        """
        Calculate R-multiple for a given target price.
        R = (target - entry) / (entry - stop)
        """
        if target_price is None:
            target_price = self.target_1
        
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return 0.0
        
        reward = abs(target_price - self.entry_price)
        return reward / risk
    
    def get_projected_r_at_targets(self) -> Dict[str, float]:
        """Get R-multiple at each target level"""
        results = {
            "target_1_r": self.calculate_r_multiple(self.target_1),
        }
        if self.target_2:
            results["target_2_r"] = self.calculate_r_multiple(self.target_2)
        if self.target_3:
            results["target_3_r"] = self.calculate_r_multiple(self.target_3)
        return results
    
    def get_risk_in_dollars(self, shares: int = 100) -> float:
        """Calculate dollar risk for position sizing"""
        return abs(self.entry_price - self.stop_loss) * shares
    
    def get_reward_in_dollars(self, shares: int = 100, target: str = "target_1") -> float:
        """Calculate dollar reward at target"""
        target_price = getattr(self, target, self.target_1)
        return abs(target_price - self.entry_price) * shares


def calculate_levels_from_technical(
    current_price: float,
    support: float,
    resistance: float,
    atr: float,
    direction: str,
    vwap: float = None,
    ema_9: float = None,
    high_of_day: float = None,
    low_of_day: float = None,
    setup_type: str = "default"
) -> TradeLevels:
    """
    Calculate entry, stop, and targets from technical levels.
    
    For LONG trades:
    - Stop: Below support or below entry by 1-1.5 ATR
    - Target 1: At resistance or VWAP (whichever is closer)
    - Target 2: Above resistance by 1 ATR or at next key level
    
    For SHORT trades:
    - Stop: Above resistance or above entry by 1-1.5 ATR
    - Target 1: At support or VWAP (whichever is closer)
    - Target 2: Below support by 1 ATR
    """
    levels = TradeLevels(
        entry_price=current_price,
        stop_loss=current_price,
        target_1=current_price,
        support=support,
        resistance=resistance,
        vwap=vwap,
        ema_9=ema_9,
        high_of_day=high_of_day,
        low_of_day=low_of_day,
        atr=atr
    )
    
    if direction == "long":
        # LONG: Stop below support or entry, target at/above resistance
        
        # Stop loss options (pick the tightest logical one)
        stop_options = [
            support - (atr * 0.25),        # Just below support
            current_price - atr,           # 1 ATR below entry
            low_of_day - 0.02 if low_of_day else current_price - atr,  # Below LOD
        ]
        levels.stop_loss = max(stop_options)  # Use the highest (tightest) stop
        
        # Target options based on setup type
        if setup_type in ["rubber_band", "vwap_bounce", "mean_reversion"]:
            # Mean reversion targets EMA or VWAP
            target_options = [
                ema_9 if ema_9 and ema_9 > current_price else None,
                vwap if vwap and vwap > current_price else None,
                current_price + (atr * 1.5),
            ]
        elif setup_type in ["breakout", "breakout_confirmed"]:
            # Breakout targets extension above resistance
            target_options = [
                resistance + (atr * 1.5) if resistance else None,
                current_price + (atr * 2),
                high_of_day + (atr * 0.5) if high_of_day else None,
            ]
        else:
            # Default: target resistance or 2 ATR
            target_options = [
                resistance if resistance and resistance > current_price else None,
                current_price + (atr * 2),
            ]
        
        # Pick the first valid target
        levels.target_1 = next((t for t in target_options if t and t > current_price), current_price + atr)
        levels.target_2 = levels.target_1 + atr  # Extended target
        levels.target_3 = levels.target_1 + (atr * 2)  # Runner target
        
    else:  # SHORT
        # SHORT: Stop above resistance or entry, target at/below support
        
        stop_options = [
            resistance + (atr * 0.25),      # Just above resistance
            current_price + atr,            # 1 ATR above entry
            high_of_day + 0.02 if high_of_day else current_price + atr,  # Above HOD
        ]
        levels.stop_loss = min(stop_options)  # Use the lowest (tightest) stop
        
        if setup_type in ["rubber_band", "vwap_fade", "mean_reversion"]:
            target_options = [
                ema_9 if ema_9 and ema_9 < current_price else None,
                vwap if vwap and vwap < current_price else None,
                current_price - (atr * 1.5),
            ]
        elif setup_type in ["breakdown"]:
            target_options = [
                support - (atr * 1.5) if support else None,
                current_price - (atr * 2),
                low_of_day - (atr * 0.5) if low_of_day else None,
            ]
        else:
            target_options = [
                support if support and support < current_price else None,
                current_price - (atr * 2),
            ]
        
        levels.target_1 = next((t for t in target_options if t and t < current_price), current_price - atr)
        levels.target_2 = levels.target_1 - atr
        levels.target_3 = levels.target_1 - (atr * 2)
    
    return levels


def calculate_projected_ev(
    win_rate: float,
    levels: TradeLevels,
    partial_target_1_pct: float = 0.5,  # Take 50% off at target 1
    avg_loss_r: float = 1.0              # Typically lose 1R at stop
) -> Dict[str, float]:
    """
    Calculate projected EV using actual price levels and partial target management.
    
    SMB Capital approach:
    - Take partial profits at Target 1 (typically 50%)
    - Trail remaining position to Target 2 or beyond
    - Average win is weighted by partial management
    
    Formula: EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)
    
    Where avg_win_R considers:
    - Probability of reaching each target
    - Partial profit taking strategy
    """
    r_at_target_1 = levels.calculate_r_multiple(levels.target_1)
    r_at_target_2 = levels.calculate_r_multiple(levels.target_2) if levels.target_2 else r_at_target_1 * 1.5
    
    # Weighted average R for wins (accounting for partial profits)
    # Assume: 50% at T1, 30% at T2, 20% trails to breakeven or small gain
    avg_win_r = (
        (r_at_target_1 * partial_target_1_pct) +  # 50% at T1
        (r_at_target_2 * 0.3) +                    # 30% reaches T2
        (r_at_target_1 * 0.5 * 0.2)               # 20% trails to ~0.5 T1
    )
    
    loss_rate = 1 - win_rate
    ev = (win_rate * avg_win_r) - (loss_rate * avg_loss_r)
    
    return {
        "projected_ev_r": ev,
        "r_at_target_1": r_at_target_1,
        "r_at_target_2": r_at_target_2,
        "avg_win_r": avg_win_r,
        "win_rate": win_rate,
        "risk_r": avg_loss_r
    }


# ==================== WORKFLOW STATE MACHINE ====================


class WorkflowState(Enum):
    """SMB-style workflow states for trade lifecycle"""
    IDEA_GEN = "idea_gen"         # Initial scan/idea generation
    FILTER_GRADE = "filter_grade" # Filter by catalyst, grade A/B/C
    TRADE_PLAN = "trade_plan"     # Define entry, stops, targets
    EXECUTION = "execution"       # Live trade execution
    REVIEW_EV = "review_ev"       # Post-trade review & EV update


class EVGate(Enum):
    """
    SMB-style EV gates for trade grading and sizing decisions.
    Based on SMB Capital's EV Calculator thresholds.
    """
    A_TRADE = "A_TRADE"         # EV ≥ 2.5R - Excellent edge, full size+
    B_TRADE = "B_TRADE"         # EV 1.0-2.5R - Solid edge, full size
    C_TRADE = "C_TRADE"         # EV 0.5-1.0R - Marginal edge, reduced size
    D_TRADE = "D_TRADE"         # EV 0-0.5R - Poor edge, minimal size
    F_TRADE = "F_TRADE"         # EV < 0R - Negative edge, don't trade


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
    ev_gate: EVGate = EVGate.B_TRADE
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
    
    Now integrated with smb_integration.py for:
    - Setup name resolution (aliases)
    - Trade style classification (M2M/T2H/A+)
    - Direction bias (long/short/both)
    - 5-Variable scoring
    """
    
    # Import setup registry from SMB integration module
    # This provides canonical setup names with alias resolution
    @staticmethod
    def _get_all_setups() -> list:
        """Get all setups from the SMB integration registry"""
        try:
            from services.smb_integration import SETUP_REGISTRY, SMB_SETUP_ALIASES
            # Return all canonical names plus aliases for backwards compatibility
            all_setups = list(SETUP_REGISTRY.keys())
            return all_setups
        except ImportError:
            # Fallback to hardcoded list if import fails
            return EVTrackingService._FALLBACK_SETUPS
    
    # Fallback setups if smb_integration not available
    _FALLBACK_SETUPS = [
        # Opening
        "first_vwap_pullback", "first_move_up", "first_move_down", "bella_fade",
        "back_through_open", "up_through_open", "opening_drive",
        # Morning momentum
        "orb", "hitchhiker", "gap_give_go", "gap_pick_roll",
        # Core session
        "spencer_scalp", "second_chance", "backside", "off_sides", "fashionably_late",
        # Mean reversion
        "rubber_band", "rubber_band_long", "rubber_band_short",
        "vwap_bounce", "vwap_fade", "tidal_wave", "mean_reversion",
        # Consolidation
        "big_dog", "puppy_dog", "9_ema_scalp", "abc_scalp", "squeeze",
        # Afternoon
        "hod_breakout", "lod_breakdown", "time_of_day_fade",
        # Special
        "breaking_news", "volume_capitulation", "range_break", 
        "breakout", "breakdown", "relative_strength", "relative_weakness",
        "gap_fade", "chart_pattern",
    ]
    
    @staticmethod
    def resolve_setup_name(name: str) -> str:
        """Resolve alias to canonical setup name"""
        try:
            from services.smb_integration import resolve_setup_name
            return resolve_setup_name(name)
        except ImportError:
            return name.lower()
    
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
        """Initialize EV records for all setups from SMB registry"""
        all_setups = self._get_all_setups()
        for setup in all_setups:
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
        """
        Determine EV gate based on expected value.
        SMB Capital thresholds based on their EV Calculator:
        - A trade: EV ≥ 2.5R (excellent edge)
        - B trade: EV 1.0-2.5R (solid edge)
        - C trade: EV 0.5-1.0R (marginal edge) - exclusive of 0.5
        - D trade: EV 0-0.5R (poor edge) - inclusive of 0.5
        - F trade: EV < 0R (negative edge)
        """
        if ev >= 2.5:
            return EVGate.A_TRADE
        elif ev >= 1.0:
            return EVGate.B_TRADE
        elif ev > 0.5:  # Changed from >= to > to match SMB (0.5 is D, not C)
            return EVGate.C_TRADE
        elif ev >= 0:
            return EVGate.D_TRADE
        else:
            return EVGate.F_TRADE
    
    def _get_size_multiplier(self, gate: EVGate) -> float:
        """
        Get position size multiplier based on EV gate.
        A trades get more size, D/F trades get reduced or no size.
        """
        multipliers = {
            EVGate.A_TRADE: 1.5,     # 150% - Go big on best setups
            EVGate.B_TRADE: 1.0,     # 100% - Standard size
            EVGate.C_TRADE: 0.75,    # 75% - Slightly reduced
            EVGate.D_TRADE: 0.5,     # 50% - Reduced size
            EVGate.F_TRADE: 0.0      # 0% - Don't trade negative EV
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
        """Get trading recommendation based on EV (SMB Capital style)"""
        if record.total_trades < 10:
            return "TRACK - Need 10+ trades for reliable EV"
        
        if record.ev_gate == EVGate.A_TRADE:
            return "A TRADE - Excellent edge (EV≥2.5R), increase position size"
        elif record.ev_gate == EVGate.B_TRADE:
            return "B TRADE - Solid edge (EV 1.0-2.5R), standard position size"
        elif record.ev_gate == EVGate.C_TRADE:
            return "C TRADE - Marginal edge (EV 0.5-1.0R), reduced position size"
        elif record.ev_gate == EVGate.D_TRADE:
            return "D TRADE - Poor edge (EV 0-0.5R), minimal size or review"
        else:
            return "F TRADE - Negative EV, remove from PlayBook"
    
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
