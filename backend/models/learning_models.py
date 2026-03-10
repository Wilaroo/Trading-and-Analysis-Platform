"""
Learning Models for Three-Speed Learning Architecture
Defines all dataclasses for trade context, execution metrics, outcomes, and learning stats.

These models support:
- Fast Learning: Real-time updates after every trade
- Medium Learning: End-of-day analysis and calibration
- Slow Learning: Weekly backtesting and verification
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum


class MarketRegime(str, Enum):
    """Market regime classification for contextual analysis"""
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    RANGE_BOUND = "range_bound"
    WEAK_DOWNTREND = "weak_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class TimeOfDay(str, Enum):
    """Trading session time periods"""
    PRE_MARKET = "pre_market"           # 4:00 - 9:30 AM ET
    OPENING_AUCTION = "opening_auction"  # 9:30 - 9:35 AM ET
    OPENING_DRIVE = "opening_drive"      # 9:35 - 10:00 AM ET
    MORNING_MOMENTUM = "morning_momentum" # 10:00 - 11:00 AM ET
    LATE_MORNING = "late_morning"        # 11:00 AM - 12:00 PM ET
    MIDDAY = "midday"                    # 12:00 - 2:00 PM ET
    AFTERNOON = "afternoon"              # 2:00 - 3:30 PM ET
    CLOSE = "close"                      # 3:30 - 4:00 PM ET
    AFTER_HOURS = "after_hours"          # 4:00 - 8:00 PM ET


class VolatilityRegime(str, Enum):
    """VIX-based volatility classification"""
    LOW = "low"           # VIX < 15
    NORMAL = "normal"     # VIX 15-20
    ELEVATED = "elevated" # VIX 20-30
    HIGH = "high"         # VIX 30-40
    EXTREME = "extreme"   # VIX > 40


class ContextDimension(str, Enum):
    """Dimensions for contextual win-rate tracking"""
    SETUP_TYPE = "setup_type"
    MARKET_REGIME = "market_regime"
    TIME_OF_DAY = "time_of_day"
    SECTOR = "sector"
    VIX_REGIME = "vix_regime"
    DAY_OF_WEEK = "day_of_week"
    TRADE_STYLE = "trade_style"
    TRADE_DIRECTION = "trade_direction"


@dataclass
class FundamentalContext:
    """Fundamental data snapshot at time of trade"""
    short_interest_percent: float = 0.0
    float_shares: int = 0
    institutional_ownership_percent: float = 0.0
    earnings_days_away: Optional[int] = None
    earnings_score: int = 0  # -10 to +10
    has_catalyst: bool = False
    catalyst_type: Optional[str] = None  # "earnings", "news", "sector_rotation"
    pe_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TechnicalContext:
    """Technical indicators snapshot at time of trade"""
    rsi: float = 50.0
    atr: float = 0.0
    atr_percent: float = 0.0
    vwap_distance_percent: float = 0.0  # % above/below VWAP
    ma_stack: str = "neutral"  # "bullish", "bearish", "neutral"
    support_distance_percent: float = 0.0
    resistance_distance_percent: float = 0.0
    relative_volume: float = 1.0
    squeeze_active: bool = False
    trend_strength: float = 0.0  # -1 to 1
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TradeContext:
    """
    Complete context snapshot at the time a trade alert is generated.
    This captures EVERYTHING about the market/stock state when the setup appeared.
    """
    # Market conditions
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    spy_change_percent: float = 0.0
    qqq_change_percent: float = 0.0
    vix_level: float = 20.0
    vix_regime: VolatilityRegime = VolatilityRegime.NORMAL
    
    # Timing
    time_of_day: TimeOfDay = TimeOfDay.MIDDAY
    day_of_week: int = 0  # 0=Monday, 4=Friday
    minutes_from_open: int = 0
    
    # Sector
    sector: str = "unknown"
    sector_performance_rank: int = 6  # 1-11 (1=best)
    sector_is_leader: bool = False
    
    # Symbol-specific fundamentals
    fundamentals: FundamentalContext = field(default_factory=FundamentalContext)
    
    # Symbol-specific technicals
    technicals: TechnicalContext = field(default_factory=TechnicalContext)
    
    # News/Sentiment
    news_sentiment: float = 0.0  # -1 to 1
    has_recent_news: bool = False
    news_headline: Optional[str] = None
    
    # Scanner/Alert metadata
    alert_priority: str = "medium"  # "critical", "high", "medium", "low"
    tape_score: float = 0.0
    tape_confirmation: bool = False
    smb_score: int = 25  # SMB 5-variable total (0-50)
    trade_grade: str = "B"  # A/B/C grade
    
    # Capture timestamp
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        # Convert enums to strings
        data['market_regime'] = self.market_regime.value
        data['vix_regime'] = self.vix_regime.value
        data['time_of_day'] = self.time_of_day.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeContext':
        """Reconstruct from dictionary"""
        if not data:
            return cls()
        
        # Convert string enums back
        data['market_regime'] = MarketRegime(data.get('market_regime', 'unknown'))
        data['vix_regime'] = VolatilityRegime(data.get('vix_regime', 'normal'))
        data['time_of_day'] = TimeOfDay(data.get('time_of_day', 'midday'))
        
        # Reconstruct nested dataclasses
        if 'fundamentals' in data and isinstance(data['fundamentals'], dict):
            data['fundamentals'] = FundamentalContext(**data['fundamentals'])
        if 'technicals' in data and isinstance(data['technicals'], dict):
            data['technicals'] = TechnicalContext(**data['technicals'])
            
        return cls(**data)


@dataclass
class ExecutionMetrics:
    """
    Tracks the quality of trade execution - entry, exit, and management.
    Used to identify areas for improvement in execution.
    """
    # Entry quality
    entry_price: float = 0.0
    intended_entry: float = 0.0  # What price we wanted
    entry_slippage: float = 0.0  # Actual - Intended (positive = worse)
    entry_slippage_percent: float = 0.0
    entry_timing_score: float = 0.5  # 0-1, did we enter at optimal point?
    chased_entry: bool = False  # Did we chase price higher/lower?
    
    # Exit quality
    exit_price: float = 0.0
    intended_exit: float = 0.0  # Target or stop
    exit_slippage: float = 0.0
    exit_slippage_percent: float = 0.0
    exit_reason: str = "unknown"  # "target", "stop", "trailing", "manual", "eod"
    
    # R-multiple analysis
    planned_r: float = 2.0  # What R we planned (target/risk)
    actual_r: float = 0.0   # What R we actually captured
    r_capture_percent: float = 0.0  # actual_r / planned_r * 100
    
    # Time management
    hold_time_minutes: int = 0
    expected_hold_time_minutes: int = 30
    exited_too_early: bool = False
    exited_too_late: bool = False
    
    # Scale-out tracking
    scaled_out: bool = False
    scale_out_count: int = 0
    scale_out_r_capture: List[float] = field(default_factory=list)  # R captured at each scale
    
    # Stop management
    stop_adjustments: int = 0
    moved_to_breakeven: bool = False
    trailing_activated: bool = False
    stopped_out: bool = False
    
    # Position sizing
    position_size: int = 0
    intended_size: int = 0
    size_adjustment_reason: Optional[str] = None  # "volatility", "conviction", "risk_limit"
    
    # Overall quality score (calculated)
    execution_quality_score: float = 0.5  # 0-1 composite score
    
    def calculate_quality_score(self) -> float:
        """Calculate overall execution quality score 0-1"""
        score = 0.5  # Start neutral
        
        # Entry quality (25% weight)
        if abs(self.entry_slippage_percent) < 0.1:
            score += 0.1  # Good entry
        elif abs(self.entry_slippage_percent) > 0.3:
            score -= 0.1  # Poor entry
        if self.chased_entry:
            score -= 0.05
            
        # R-capture (35% weight)
        if self.r_capture_percent >= 80:
            score += 0.15
        elif self.r_capture_percent >= 50:
            score += 0.05
        elif self.r_capture_percent < 30 and self.actual_r > 0:
            score -= 0.1  # Left money on table
            
        # Timing (15% weight)
        if not self.exited_too_early and not self.exited_too_late:
            score += 0.075
        elif self.exited_too_early:
            score -= 0.05
            
        # Stop management (15% weight)
        if self.moved_to_breakeven and not self.stopped_out:
            score += 0.075  # Good risk management
        if self.trailing_activated and self.actual_r > 0:
            score += 0.05
            
        # Scale-out effectiveness (10% weight)
        if self.scaled_out and len(self.scale_out_r_capture) > 0:
            avg_scale_r = sum(self.scale_out_r_capture) / len(self.scale_out_r_capture)
            if avg_scale_r > 1.0:
                score += 0.05
                
        self.execution_quality_score = max(0.0, min(1.0, score))
        return self.execution_quality_score
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ExecutionMetrics':
        if not data:
            return cls()
        return cls(**data)


@dataclass
class TradeOutcome:
    """
    Complete record of a trade with full context and execution details.
    This is what gets stored in the `trade_outcomes` collection for learning.
    """
    # Identifiers
    id: str = ""
    alert_id: str = ""  # Link to original scanner alert
    bot_trade_id: str = ""  # Link to trading bot trade
    
    # Basic trade info
    symbol: str = ""
    setup_type: str = ""
    strategy_name: str = ""
    direction: str = "long"  # "long" or "short"
    trade_style: str = "move_2_move"  # SMB style
    
    # Prices
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    
    # Result
    outcome: str = "pending"  # "won", "lost", "breakeven", "pending"
    pnl: float = 0.0
    pnl_percent: float = 0.0
    actual_r: float = 0.0
    planned_r: float = 2.0
    
    # Context at trade time
    context: TradeContext = field(default_factory=TradeContext)
    
    # Execution quality
    execution: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    
    # Confirmation signals that were present
    confirmation_signals: List[str] = field(default_factory=list)  # ["tape_confirmation", "sector_leader", "earnings_catalyst"]
    
    # Timestamps
    entry_time: str = ""
    exit_time: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Learning flags
    reviewed: bool = False  # Has this trade been reviewed in daily analysis?
    included_in_stats: bool = False  # Has this been aggregated into stats?
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        # Handle nested dataclasses
        data['context'] = self.context.to_dict() if isinstance(self.context, TradeContext) else self.context
        data['execution'] = self.execution.to_dict() if isinstance(self.execution, ExecutionMetrics) else self.execution
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeOutcome':
        if not data:
            return cls()
        
        # Reconstruct nested dataclasses
        if 'context' in data and isinstance(data['context'], dict):
            data['context'] = TradeContext.from_dict(data['context'])
        if 'execution' in data and isinstance(data['execution'], dict):
            data['execution'] = ExecutionMetrics.from_dict(data['execution'])
            
        return cls(**data)


@dataclass
class LearningStats:
    """
    Aggregated statistics for a specific context combination.
    E.g., "Bull Flag in strong uptrend during morning session" has its own stats.
    """
    # Context key (what this stat represents)
    context_key: str = ""  # e.g., "bull_flag:strong_uptrend:morning_momentum"
    setup_type: str = ""
    
    # Filters (what dimensions this stat covers)
    market_regime: Optional[str] = None
    time_of_day: Optional[str] = None
    sector: Optional[str] = None
    vix_regime: Optional[str] = None
    trade_direction: Optional[str] = None
    
    # Core metrics
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    
    # Rates
    win_rate: float = 0.0  # wins / (wins + losses)
    profit_factor: float = 0.0  # gross_profit / gross_loss
    
    # R-multiple stats
    total_r: float = 0.0
    avg_r_per_trade: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    expected_value_r: float = 0.0  # (win_rate * avg_win_r) - ((1-win_rate) * avg_loss_r)
    
    # P&L stats
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    max_win: float = 0.0
    max_loss: float = 0.0
    
    # Execution quality
    avg_entry_slippage: float = 0.0
    avg_r_capture_percent: float = 0.0
    
    # Confirmation signal effectiveness
    confirmation_signal_impact: Dict[str, float] = field(default_factory=dict)  # signal -> win_rate_delta
    
    # Rolling stats (last N trades)
    rolling_win_rate_10: float = 0.0  # Last 10 trades
    rolling_win_rate_20: float = 0.0  # Last 20 trades
    
    # Decay detection
    edge_score: float = 0.0  # Composite edge score
    edge_declining: bool = False  # Is edge declining over time?
    
    # Timestamps
    last_updated: str = ""
    last_trade_date: str = ""
    
    def calculate_stats(self, outcomes: List[TradeOutcome]):
        """Recalculate all stats from a list of outcomes"""
        if not outcomes:
            return
            
        self.total_trades = len(outcomes)
        self.wins = sum(1 for o in outcomes if o.outcome == "won")
        self.losses = sum(1 for o in outcomes if o.outcome == "lost")
        self.breakeven = sum(1 for o in outcomes if o.outcome == "breakeven")
        
        # Win rate
        decided = self.wins + self.losses
        self.win_rate = self.wins / decided if decided > 0 else 0.0
        
        # R-multiples
        win_rs = [o.actual_r for o in outcomes if o.outcome == "won" and o.actual_r > 0]
        loss_rs = [abs(o.actual_r) for o in outcomes if o.outcome == "lost"]
        
        self.avg_win_r = sum(win_rs) / len(win_rs) if win_rs else 0.0
        self.avg_loss_r = sum(loss_rs) / len(loss_rs) if loss_rs else 1.0
        
        self.total_r = sum(o.actual_r for o in outcomes)
        self.avg_r_per_trade = self.total_r / self.total_trades if self.total_trades > 0 else 0.0
        
        # Expected Value in R
        self.expected_value_r = (self.win_rate * self.avg_win_r) - ((1 - self.win_rate) * self.avg_loss_r)
        
        # Profit factor
        gross_profit = sum(o.pnl for o in outcomes if o.pnl > 0)
        gross_loss = abs(sum(o.pnl for o in outcomes if o.pnl < 0))
        self.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        
        # P&L
        self.total_pnl = sum(o.pnl for o in outcomes)
        self.avg_pnl = self.total_pnl / self.total_trades if self.total_trades > 0 else 0.0
        self.max_win = max((o.pnl for o in outcomes), default=0.0)
        self.max_loss = min((o.pnl for o in outcomes), default=0.0)
        
        # Execution quality
        slippages = [o.execution.entry_slippage_percent for o in outcomes if o.execution]
        r_captures = [o.execution.r_capture_percent for o in outcomes if o.execution and o.execution.r_capture_percent > 0]
        
        self.avg_entry_slippage = sum(slippages) / len(slippages) if slippages else 0.0
        self.avg_r_capture_percent = sum(r_captures) / len(r_captures) if r_captures else 0.0
        
        # Rolling stats
        sorted_outcomes = sorted(outcomes, key=lambda o: o.created_at, reverse=True)
        last_10 = sorted_outcomes[:10]
        last_20 = sorted_outcomes[:20]
        
        wins_10 = sum(1 for o in last_10 if o.outcome == "won")
        decided_10 = sum(1 for o in last_10 if o.outcome in ("won", "lost"))
        self.rolling_win_rate_10 = wins_10 / decided_10 if decided_10 > 0 else 0.0
        
        wins_20 = sum(1 for o in last_20 if o.outcome == "won")
        decided_20 = sum(1 for o in last_20 if o.outcome in ("won", "lost"))
        self.rolling_win_rate_20 = wins_20 / decided_20 if decided_20 > 0 else 0.0
        
        # Edge decay detection
        self.edge_declining = self.rolling_win_rate_10 < self.win_rate - 0.1
        
        self.last_updated = datetime.now(timezone.utc).isoformat()
        if outcomes:
            self.last_trade_date = max(o.created_at for o in outcomes)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'LearningStats':
        if not data:
            return cls()
        return cls(**data)


@dataclass
class TiltState:
    """Tracks trader emotional state for tilt detection"""
    consecutive_losses: int = 0
    losses_in_last_hour: int = 0
    pnl_last_hour: float = 0.0
    avg_time_between_trades_minutes: float = 30.0
    last_trade_time: Optional[str] = None
    
    # Tilt indicators
    is_tilted: bool = False
    tilt_severity: str = "none"  # "none", "mild", "moderate", "severe"
    tilt_indicators: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TraderProfile:
    """
    Summary of trader's patterns and characteristics for RAG injection.
    This gets embedded into AI prompts to provide personalized advice.
    """
    # Identity
    profile_id: str = "default"
    last_updated: str = ""
    
    # Best/Worst setups
    best_setups: List[Dict] = field(default_factory=list)  # [{"setup": "bull_flag", "win_rate": 0.68, "ev_r": 0.45}]
    worst_setups: List[Dict] = field(default_factory=list)
    
    # Time performance
    best_hours: List[Dict] = field(default_factory=list)  # [{"hour": "9:30-10:00", "win_rate": 0.62}]
    worst_hours: List[Dict] = field(default_factory=list)
    
    # Market condition performance
    best_regimes: List[str] = field(default_factory=list)  # ["strong_uptrend", "volatile"]
    worst_regimes: List[str] = field(default_factory=list)
    
    # Execution tendencies
    avg_entry_slippage_percent: float = 0.0
    avg_r_capture_percent: float = 0.0
    tends_to_chase: bool = False
    tends_to_exit_early: bool = False
    tends_to_overtrade: bool = False
    
    # Current state
    current_tilt_state: TiltState = field(default_factory=TiltState)
    trades_today: int = 0
    pnl_today: float = 0.0
    win_rate_today: float = 0.0
    
    # Overall stats
    total_trades: int = 0
    overall_win_rate: float = 0.0
    overall_profit_factor: float = 0.0
    overall_ev_r: float = 0.0
    
    def generate_ai_context(self) -> str:
        """Generate the context string to inject into AI prompts"""
        lines = []
        lines.append("You are advising a trader with these characteristics:")
        
        # Best setups
        if self.best_setups:
            best_str = ", ".join([f"{s['setup']} ({s['win_rate']*100:.0f}%)" for s in self.best_setups[:3]])
            lines.append(f"- Best setups: {best_str}")
            
        # Worst setups
        if self.worst_setups:
            worst_str = ", ".join([f"{s['setup']} ({s['win_rate']*100:.0f}%)" for s in self.worst_setups[:3]])
            lines.append(f"- Avoid: {worst_str}")
            
        # Best hours
        if self.best_hours:
            hours_str = ", ".join([f"{h['hour']} ({h['win_rate']*100:.0f}%)" for h in self.best_hours[:2]])
            lines.append(f"- Best hours: {hours_str}")
            
        # Execution tendencies
        if self.tends_to_chase:
            lines.append(f"- Tends to chase entries by avg {self.avg_entry_slippage_percent:.2f}%")
        if self.tends_to_exit_early:
            lines.append(f"- Exits too early, captures only {self.avg_r_capture_percent:.0f}% of move")
            
        # Best conditions
        if self.best_regimes:
            lines.append(f"- Performs best in {', '.join(self.best_regimes)} markets ({self.overall_win_rate*100:.0f}% win)")
            
        # Current state
        if self.current_tilt_state.is_tilted:
            lines.append(f"- Current state: {self.current_tilt_state.consecutive_losses} consecutive losses, possible tilt")
        elif self.trades_today > 0:
            lines.append(f"- Today: {self.trades_today} trades, {self.win_rate_today*100:.0f}% win rate, ${self.pnl_today:.0f} P&L")
            
        return "\n".join(lines)
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['current_tilt_state'] = self.current_tilt_state.to_dict()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TraderProfile':
        if not data:
            return cls()
        
        if 'current_tilt_state' in data and isinstance(data['current_tilt_state'], dict):
            data['current_tilt_state'] = TiltState(**data['current_tilt_state'])
            
        return cls(**data)


@dataclass
class CalibrationEntry:
    """Record of a threshold/parameter adjustment"""
    id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    parameter_name: str = ""  # e.g., "tape_score_threshold", "bull_flag_min_win_rate"
    old_value: float = 0.0
    new_value: float = 0.0
    adjustment_percent: float = 0.0
    
    reason: str = ""  # Why the adjustment was made
    context: str = ""  # What context triggered it
    
    # Performance that triggered adjustment
    triggering_win_rate: float = 0.0
    triggering_sample_size: int = 0
    
    # Bounded adjustment info
    max_daily_adjustment: float = 0.1  # Max 10% adjustment per day
    cumulative_daily_adjustment: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
