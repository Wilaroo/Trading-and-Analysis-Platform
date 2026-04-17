"""
Enhanced Background Scanner Service - SMB Trading Strategies
With RVOL Pre-filtering, Tape Reading Signals, Win-Rate Tracking, and Bot Auto-Execution

Features:
- 264 symbols with RVOL pre-filtering (skip dead stocks)
- 30+ SMB strategies with time-of-day and market context rules
- Tape reading confirmation signals (bid/ask spread, momentum, order flow)
- Strategy win-rate tracking per setup type
- Auto-execution wiring to Trading Bot for high-priority alerts
- SMB 5-Variable Scoring integration
- Trade Style classification (M2M/T2H/A+)
- Direction bias (Long/Short/Both) per setup

Data Source Hierarchy:
- QUOTES: IB pusher (primary) -> MongoDB latest bar (fallback)
- HISTORICAL BARS: ib_historical_data in MongoDB (same source as training)
- LEVEL 2: IB pusher (when available)
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from collections import defaultdict

# SMB Integration imports
try:
    from services.smb_integration import (
        TradeStyle, SetupDirection, SetupCategory,
        SETUP_REGISTRY, SMB_SETUP_ALIASES,
        get_setup_config, resolve_setup_name, get_default_trade_style,
        get_setup_direction, get_directional_setup_name,
        SMBVariableScore, calculate_smb_score,
        TRADE_STYLE_TARGETS, get_style_targets
    )
    SMB_INTEGRATION_AVAILABLE = True
except ImportError:
    SMB_INTEGRATION_AVAILABLE = False

logger = logging.getLogger(__name__)


class AlertPriority(Enum):
    CRITICAL = "critical"  # Imminent trigger - auto-execute candidate
    HIGH = "high"          # High probability setup
    MEDIUM = "medium"      # Good setup, watch closely
    LOW = "low"            # Early stage, monitor


class MarketRegime(Enum):
    STRONG_UPTREND = "strong_uptrend"
    STRONG_DOWNTREND = "strong_downtrend"
    RANGE_BOUND = "range_bound"
    VOLATILE = "volatile"
    MOMENTUM = "momentum"
    FADE = "fade"


class TimeWindow(Enum):
    OPENING_AUCTION = "opening_auction"      # 9:30-9:35
    OPENING_DRIVE = "opening_drive"          # 9:35-9:45
    MORNING_MOMENTUM = "morning_momentum"    # 9:45-10:00
    MORNING_SESSION = "morning_session"      # 10:00-10:45
    LATE_MORNING = "late_morning"            # 10:45-11:30
    MIDDAY = "midday"                        # 11:30-13:30
    AFTERNOON = "afternoon"                  # 13:30-15:00
    CLOSE = "close"                          # 15:00-16:00
    CLOSED = "closed"                        # Outside market hours


class TapeSignal(Enum):
    """Tape reading confirmation signals"""
    STRONG_BID = "strong_bid"           # Bids stacking, buyers aggressive
    STRONG_ASK = "strong_ask"           # Asks stacking, sellers aggressive
    MOMENTUM_UP = "momentum_up"         # Price moving up on volume
    MOMENTUM_DOWN = "momentum_down"     # Price moving down on volume
    ABSORPTION = "absorption"           # Large orders being absorbed
    EXHAUSTION = "exhaustion"           # Volume spike with reversal
    TIGHT_SPREAD = "tight_spread"       # Tight bid/ask = liquid
    WIDE_SPREAD = "wide_spread"         # Wide spread = illiquid/caution
    NEUTRAL = "neutral"


# Strategy time windows - when each strategy is valid
STRATEGY_TIME_WINDOWS = {
    # Opening Auction (9:30-9:35)
    "first_vwap_pullback": [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE],
    "first_move_up": [TimeWindow.OPENING_AUCTION],
    "first_move_down": [TimeWindow.OPENING_AUCTION],
    "bella_fade": [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE],
    "back_through_open": [TimeWindow.OPENING_AUCTION],
    "up_through_open": [TimeWindow.OPENING_AUCTION],
    "opening_drive": [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE],
    
    # Morning Momentum (9:35-10:00)
    "orb": [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION],
    "hitchhiker": [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM],
    "gap_give_go": [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM],
    "gap_pick_roll": [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM],
    
    # Core Session (10:00-13:30)
    "spencer_scalp": [TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    "second_chance": [TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    "backside": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    "off_sides": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    "fashionably_late": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    
    # Mean Reversion (All day)
    "rubber_band": [TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    "vwap_bounce": [TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    "vwap_fade": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    "tidal_wave": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    
    # Consolidation (Mid-session)
    "big_dog": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    "puppy_dog": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    "9_ema_scalp": [TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING],
    "abc_scalp": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY],
    
    # Afternoon (13:30-16:00)
    "hod_breakout": [TimeWindow.AFTERNOON, TimeWindow.CLOSE],
    "time_of_day_fade": [TimeWindow.CLOSE],
    
    # Special (Context dependent)
    "breaking_news": [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM, 
                      TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, 
                      TimeWindow.AFTERNOON, TimeWindow.CLOSE],
    "volume_capitulation": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    "range_break": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
    "breakout": [TimeWindow.MORNING_SESSION, TimeWindow.LATE_MORNING, TimeWindow.MIDDAY, TimeWindow.AFTERNOON],
}

# Strategy market regime preferences
STRATEGY_REGIME_PREFERENCES = {
    # Works in trending markets
    "spencer_scalp": [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND, MarketRegime.MOMENTUM],
    "hitchhiker": [MarketRegime.STRONG_UPTREND, MarketRegime.MOMENTUM],
    "gap_give_go": [MarketRegime.STRONG_UPTREND, MarketRegime.MOMENTUM],
    "backside": [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND],
    "second_chance": [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND, MarketRegime.MOMENTUM],
    "hod_breakout": [MarketRegime.STRONG_UPTREND, MarketRegime.MOMENTUM],
    "breakout": [MarketRegime.STRONG_UPTREND, MarketRegime.MOMENTUM],
    "9_ema_scalp": [MarketRegime.STRONG_UPTREND, MarketRegime.MOMENTUM],
    
    # Works in range/fade markets
    "off_sides": [MarketRegime.RANGE_BOUND, MarketRegime.FADE],
    "rubber_band": [MarketRegime.RANGE_BOUND, MarketRegime.FADE, MarketRegime.VOLATILE],
    "vwap_bounce": [MarketRegime.RANGE_BOUND, MarketRegime.STRONG_UPTREND],
    "vwap_fade": [MarketRegime.RANGE_BOUND, MarketRegime.FADE],
    "tidal_wave": [MarketRegime.STRONG_DOWNTREND, MarketRegime.FADE],
    "time_of_day_fade": [MarketRegime.RANGE_BOUND, MarketRegime.FADE],
    
    # Works in most conditions
    "orb": [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND, MarketRegime.MOMENTUM],
    "fashionably_late": [MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND],
    "volume_capitulation": [MarketRegime.VOLATILE, MarketRegime.STRONG_UPTREND, MarketRegime.STRONG_DOWNTREND],
    "breaking_news": [MarketRegime.MOMENTUM, MarketRegime.VOLATILE],
}


@dataclass
class TapeReading:
    """Tape reading analysis for a symbol"""
    symbol: str
    timestamp: str
    
    # Bid/Ask analysis
    bid_price: float
    ask_price: float
    spread: float
    spread_pct: float
    spread_signal: TapeSignal
    
    # Order flow
    bid_size: int
    ask_size: int
    imbalance: float  # Positive = more bids, negative = more asks
    imbalance_signal: TapeSignal
    
    # Momentum
    price_momentum: float  # Recent price change
    volume_momentum: float  # Volume vs average
    momentum_signal: TapeSignal
    
    # Overall tape confirmation
    overall_signal: TapeSignal
    tape_score: float  # -1 to 1, negative = bearish, positive = bullish
    confirmation_for_long: bool
    confirmation_for_short: bool
    
    # Level 2 data (if available)
    l2_available: bool = False
    l2_imbalance: float = 0.0
    l2_bid_depth: int = 0
    l2_ask_depth: int = 0
    
    # Monitoring: Would L2-based gate have blocked this?
    l2_gate_would_pass_long: bool = True
    l2_gate_would_pass_short: bool = True


@dataclass
class StrategyStats:
    """Win-rate and Expected Value tracking per strategy (SMB-style)"""
    setup_type: str
    total_alerts: int = 0
    alerts_triggered: int = 0
    alerts_won: int = 0
    alerts_lost: int = 0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_rr_achieved: float = 0.0
    last_updated: str = ""
    
    # R-Multiple tracking (SMB-style)
    r_outcomes: List[float] = field(default_factory=list)  # List of R-multiples achieved
    avg_win_r: float = 0.0  # Average win in R-multiples
    avg_loss_r: float = 1.0  # Average loss in R-multiples (typically 1R)
    expected_value_r: float = 0.0  # EV per trade in R-multiples
    
    # SMB workflow grade distribution
    a_grade_count: int = 0
    b_grade_count: int = 0
    c_grade_count: int = 0
    a_grade_win_rate: float = 0.0
    b_grade_win_rate: float = 0.0
    
    # EV trend (last 20 trades)
    ev_trend: List[float] = field(default_factory=list)
    ev_improving: bool = False
    
    def update_win_rate(self):
        """Recalculate win rate and Expected Value"""
        if self.alerts_triggered > 0:
            self.win_rate = self.alerts_won / self.alerts_triggered
        if self.alerts_lost > 0 and self.avg_loss != 0:
            self.profit_factor = (self.alerts_won * abs(self.avg_win)) / (self.alerts_lost * abs(self.avg_loss))
        
        # Calculate Expected Value in R-multiples (SMB formula)
        # EV = (win_rate × avg_win_R) – (loss_rate × avg_loss_R)
        self._calculate_expected_value()
        self.last_updated = datetime.now(timezone.utc).isoformat()
    
    def _calculate_expected_value(self):
        """Calculate EV using SMB Capital's formula: EV = (p_win × avg_win) – (p_loss × avg_loss)"""
        if len(self.r_outcomes) < 5:  # Need minimum sample size
            return
        
        wins_r = [r for r in self.r_outcomes if r > 0]
        losses_r = [r for r in self.r_outcomes if r <= 0]
        
        if wins_r:
            self.avg_win_r = sum(wins_r) / len(wins_r)
        if losses_r:
            self.avg_loss_r = abs(sum(losses_r) / len(losses_r))
        
        loss_rate = 1 - self.win_rate
        self.expected_value_r = (self.win_rate * self.avg_win_r) - (loss_rate * self.avg_loss_r)
        
        # Track EV trend (rolling 20)
        self.ev_trend.append(self.expected_value_r)
        if len(self.ev_trend) > 20:
            self.ev_trend = self.ev_trend[-20:]
        
        # Determine if EV is improving
        if len(self.ev_trend) >= 5:
            recent_avg = sum(self.ev_trend[-5:]) / 5
            older_avg = sum(self.ev_trend[:5]) / 5 if len(self.ev_trend) >= 10 else recent_avg
            self.ev_improving = recent_avg > older_avg
    
    def record_r_outcome(self, r_multiple: float, grade: str = "B"):
        """Record an R-multiple outcome for EV calculation"""
        self.r_outcomes.append(r_multiple)
        
        # Keep last 100 outcomes for memory efficiency
        if len(self.r_outcomes) > 100:
            self.r_outcomes = self.r_outcomes[-100:]
        
        # Track by grade
        if grade == "A":
            self.a_grade_count += 1
        elif grade == "B":
            self.b_grade_count += 1
        else:
            self.c_grade_count += 1
        
        self._calculate_expected_value()
    
    def get_ev_assessment(self) -> dict:
        """Get SMB-style EV assessment for this setup"""
        return {
            "setup_type": self.setup_type,
            "sample_size": len(self.r_outcomes),
            "win_rate": self.win_rate,
            "avg_win_r": self.avg_win_r,
            "avg_loss_r": self.avg_loss_r,
            "expected_value_r": self.expected_value_r,
            "ev_trend": self.ev_trend[-10:] if self.ev_trend else [],
            "ev_improving": self.ev_improving,
            "profit_factor": self.profit_factor,
            "is_positive_ev": self.expected_value_r > 0,
            "min_sample_reached": len(self.r_outcomes) >= 10,
            "recommendation": self._get_ev_recommendation()
        }
    
    def _get_ev_recommendation(self) -> str:
        """SMB-style recommendation based on EV"""
        if len(self.r_outcomes) < 10:
            return "TRACK - Need 10+ trades for reliable EV"
        
        if self.expected_value_r > 0.5:
            return "A-SIZE - Strong positive EV, increase position size"
        elif self.expected_value_r > 0.2:
            return "GREENLIGHT - Positive EV, continue trading this setup"
        elif self.expected_value_r > 0:
            return "CAUTIOUS - Marginal EV, consider refinements"
        elif self.expected_value_r > -0.2:
            return "REVIEW - Negative EV, needs analysis"
        else:
            return "DROP - Strong negative EV, remove from playbook"


@dataclass
class LiveAlert:
    """Real-time trading alert with tape confirmation and position sizing data"""
    id: str
    symbol: str
    setup_type: str
    strategy_name: str
    direction: str
    priority: AlertPriority
    
    current_price: float
    trigger_price: float
    stop_loss: float
    target: float
    risk_reward: float
    
    trigger_probability: float
    win_probability: float
    minutes_to_trigger: int
    
    headline: str
    reasoning: List[str]
    time_window: str
    market_regime: str
    
    # Tape reading confirmation
    tape_score: float = 0.0
    tape_confirmation: bool = False
    tape_signals: List[str] = field(default_factory=list)
    
    # Strategy stats
    strategy_win_rate: float = 0.0
    strategy_profit_factor: float = 0.0
    
    # SMB-style Expected Value and R-multiple tracking
    strategy_ev_r: float = 0.0           # Expected Value in R-multiples
    projected_r: float = 0.0             # Projected R-multiple if target hit
    risk_r: float = 1.0                  # Risk in R-multiples (1R = stop loss distance)
    
    # SMB-style trade grading (A/B/C based on edge quality)
    trade_grade: str = "B"               # "A" = best setup, "B" = standard, "C" = marginal
    grade_reasoning: List[str] = field(default_factory=list)
    
    # SMB workflow state
    workflow_state: str = "idea"         # "idea", "filtered", "planned", "executed", "reviewed"
    
    # Volatility-adjusted position sizing data
    atr: float = 0.0                    # Average True Range in dollars
    atr_percent: float = 0.0            # ATR as % of price
    suggested_shares: int = 0           # Pre-calculated position size
    suggested_risk: float = 0.0         # Pre-calculated risk amount
    volatility_regime: str = "normal"   # "low", "normal", "high", "extreme"
    
    # Auto-execution
    auto_execute_eligible: bool = False
    
    # NEW: SMB Integration fields
    trade_style: str = "intraday"     # scalp, intraday, multi_day, swing, position
    setup_category: str = "consolidation" # "trend_momentum", "catalyst_driven", "reversal", "consolidation", "specialized"
    direction_bias: str = "both"         # "long", "short", "both" - primary setup direction
    
    # SMB 5-Variable Score
    smb_score_total: int = 25            # 0-50 total score
    smb_big_picture: int = 5             # 1-10
    smb_fundamental: int = 5             # 1-10
    smb_technical: int = 5               # 1-10
    smb_tape: int = 5                    # 1-10
    smb_intuition: int = 5               # 1-10
    smb_is_a_plus: bool = False          # True if qualifies as A+ setup
    
    # Trade style targets
    target_r_multiple: float = 2.0       # Target R based on trade style
    exit_rule: str = ""                  # How to manage/exit based on style
    
    # Earnings catalyst score (if applicable)
    earnings_score: int = 0              # -10 to +10
    trading_approach: str = ""           # "max_conviction", "aggressive", "directional", "limited", "avoid"
    
    # ADV Scan Tier (Phase 4)
    scan_tier: str = "intraday"          # "intraday" (≥500K ADV), "swing" (≥100K), "investment" (≥50K)
    
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    acknowledged: bool = False
    status: str = "active"
    
    # Outcome tracking
    outcome: Optional[str] = None  # "won", "lost", "expired", "cancelled"
    actual_pnl: Optional[float] = None
    actual_r_multiple: Optional[float] = None  # Actual R-multiple achieved
    
    # NEW: TQS (Trade Quality Score) integration
    tqs_score: float = 0.0                # 0-100 overall score
    tqs_grade: str = ""                   # A/B/C/D/F
    tqs_action: str = ""                  # STRONG_BUY/BUY/HOLD/AVOID
    tqs_trade_style: str = ""             # Inferred trade style
    tqs_timeframe: str = ""               # Human-readable timeframe
    tqs_key_factors: List[str] = field(default_factory=list)
    tqs_concerns: List[str] = field(default_factory=list)
    tqs_is_high_quality: bool = False     # TQS >= 70 (highlighted in UI)
    
    # NEW: AI Integration fields
    ai_confidence: float = 0.0            # 0-100 AI confidence in trade direction
    ai_prediction: str = ""               # "bullish", "bearish", "neutral"
    ai_predicted_move_pct: float = 0.0    # Predicted % move in next 30 mins
    ai_agrees_with_direction: bool = False  # True if AI prediction matches alert direction
    ai_model_version: str = ""            # Version of AI model used
    
    def calculate_r_multiple(self) -> float:
        """Calculate the R-multiple for this alert (target/risk ratio)"""
        risk_per_share = abs(self.current_price - self.stop_loss)
        reward_per_share = abs(self.target - self.current_price)
        if risk_per_share > 0:
            self.projected_r = reward_per_share / risk_per_share
            self.risk_r = 1.0  # By definition, risk is 1R
        return self.projected_r
    
    def grade_trade(self, strategy_ev: float = 0.0, market_context_score: float = 0.5) -> str:
        """
        SMB-style trade grading based on edge quality.
        A = Best setups (high EV, strong context, tape confirmation)
        B = Standard setups (positive EV, decent context)
        C = Marginal setups (low EV or weak context)
        """
        score = 0
        reasons = []
        
        # 1. R:R ratio (SMB wants 2:1+)
        if self.risk_reward >= 3:
            score += 30
            reasons.append(f"Excellent R:R of {self.risk_reward:.1f}:1")
        elif self.risk_reward >= 2:
            score += 20
            reasons.append(f"Good R:R of {self.risk_reward:.1f}:1")
        elif self.risk_reward >= 1.5:
            score += 10
            reasons.append(f"Acceptable R:R of {self.risk_reward:.1f}:1")
        else:
            reasons.append(f"Low R:R of {self.risk_reward:.1f}:1")
        
        # 2. Strategy EV (positive EV is key)
        if strategy_ev > 0.5:
            score += 30
            reasons.append(f"Strong historical EV: {strategy_ev:.2f}R")
        elif strategy_ev > 0.2:
            score += 20
            reasons.append(f"Positive historical EV: {strategy_ev:.2f}R")
        elif strategy_ev > 0:
            score += 10
            reasons.append(f"Marginal EV: {strategy_ev:.2f}R")
        else:
            reasons.append(f"Negative/unknown EV: {strategy_ev:.2f}R")
        
        # 3. Tape confirmation
        if self.tape_confirmation and self.tape_score >= 70:
            score += 20
            reasons.append(f"Strong tape confirmation: {self.tape_score:.0f}")
        elif self.tape_confirmation:
            score += 10
            reasons.append(f"Tape confirms: {self.tape_score:.0f}")
        
        # 4. Priority/Catalyst strength
        if self.priority == AlertPriority.HIGH:
            score += 15
            reasons.append("High priority catalyst")
        elif self.priority == AlertPriority.MEDIUM:
            score += 10
        
        # 5. Market context alignment
        if market_context_score > 0.7:
            score += 10
            reasons.append("Favorable market context")
        
        # Determine grade
        if score >= 70:
            self.trade_grade = "A"
        elif score >= 45:
            self.trade_grade = "B"
        else:
            self.trade_grade = "C"
        
        self.grade_reasoning = reasons
        return self.trade_grade
    
    def populate_smb_fields(self, context: Dict = None):
        """
        Populate SMB integration fields based on setup configuration.
        Called when creating or updating alerts.
        """
        if not SMB_INTEGRATION_AVAILABLE:
            return
        
        try:
            # Get setup configuration
            config = get_setup_config(self.setup_type)
            if config:
                # Trade style and category
                self.trade_style = config.default_style.value
                self.setup_category = config.category.value
                self.direction_bias = config.direction.value
                
                # Get style-specific targets
                style_targets = get_style_targets(config.default_style)
                self.target_r_multiple = style_targets.get("target_r", 2.0)
                self.exit_rule = style_targets.get("exit_rule", "")
                
                # Override with context if available
                if context:
                    # Potentially upgrade to T2H or A+ based on context
                    recommended_style = get_default_trade_style(self.setup_type, context)
                    if recommended_style != config.default_style:
                        self.trade_style = recommended_style.value
                        style_targets = get_style_targets(recommended_style)
                        self.target_r_multiple = style_targets.get("target_r", 2.0)
                        self.exit_rule = style_targets.get("exit_rule", "")
                    
                    # SMB 5-Variable scoring
                    smb_score = context.get("smb_score")
                    if smb_score and isinstance(smb_score, SMBVariableScore):
                        self.smb_score_total = smb_score.total_score
                        self.smb_big_picture = smb_score.big_picture
                        self.smb_fundamental = smb_score.intraday_fundamental
                        self.smb_technical = smb_score.technical_level
                        self.smb_tape = smb_score.tape_reading
                        self.smb_intuition = smb_score.intuition
                        self.smb_is_a_plus = smb_score.is_a_plus
                        
                        if smb_score.is_a_plus:
                            self.trade_style = "multi_day"
                            self.target_r_multiple = 5.0
                    
                    # Earnings score if available
                    if "earnings_score" in context:
                        self.earnings_score = context["earnings_score"]
                        self.trading_approach = context.get("trading_approach", "")
                        
        except Exception as e:
            logger.warning(f"Error populating SMB fields for {self.setup_type}: {e}")
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['priority'] = self.priority.value
        return result


class EnhancedBackgroundScanner:
    """
    Enhanced background scanner with all SMB strategies,
    RVOL pre-filtering, tape reading, win-rate tracking,
    and Trading Bot auto-execution.
    """
    
    def __init__(self, db=None):
        self.db = db
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        
        # Optimized configuration for 200+ symbols
        self._scan_interval = 15  # Base interval between scan cycles (seconds)
        self._symbols_per_batch = 100  # Process 100 symbols per batch (up from 10)
        self._batch_delay = 0.1  # 100ms delay between batches (down from 1s)
        self._min_scan_interval = 10
        
        # RVOL pre-filter threshold
        self._min_rvol_filter = 0.8  # Skip stocks with RVOL < 0.8
        self._rvol_cache: Dict[str, Tuple[float, datetime]] = {}
        self._rvol_cache_ttl = 300  # 5 minutes
        
        # Average Daily Volume (ADV) filters - FIRST checkpoint before any scanning
        self._min_adv_general = 100_000      # Min ADV for general/swing setups
        self._min_adv_intraday = 500_000     # Min ADV for intraday/scalp setups
        self._min_adv_investment = 50_000    # Min ADV for investment tier
        self._adv_cache: Dict[str, Tuple[int, datetime]] = {}  # Cache ADV values with timestamp
        self._adv_cache_ttl = 900  # 15 minutes (reduced from 1 hour for faster re-checks)
        
        # --- Tiered Scanning System ---
        # Symbols are classified into 3 tiers based on ADV, each scanned at different frequencies
        # Tier 1 (Intraday): ADV ≥ 500K → scanned every cycle (~15s)
        # Tier 2 (Swing):    ADV ≥ 100K → scanned every 8th cycle (~2 min)
        # Tier 3 (Investment): ADV ≥ 50K → scanned at 11:00 AM and 3:45 PM ET only
        self._tier_cache: Dict[str, str] = {}  # symbol -> "intraday" | "swing" | "investment"
        self._tier_cache_ttl = 3600  # Reclassify every hour
        self._tier_cache_time: Optional[datetime] = None
        self._swing_scan_frequency = 8  # Every 8th cycle (~2 min at 15s base)
        self._investment_scan_times = [(11, 0), (15, 45)]  # 11:00 AM ET, 3:45 PM ET
        self._last_investment_scan_hour = -1  # Track to avoid duplicate investment scans
        
        # Symbol validation - known invalid/illiquid symbols that pass through due to data errors
        # These are symbols that should NEVER generate alerts
        self._blacklisted_symbols: Set[str] = {
            # Known illiquid REITs that slip through
            "ALEX", "AIV", "AKR", "CIO", "CLPR", "DEA", "DEI", "ELME", "GMRE", "GTY", "HIW",
            "JBGS", "MDV", "OFC", "OUT", "PDM", "PEB",
            # Very low volume small caps often with data issues
            "ALJJ", "ALOT", "AMTB", "AMYT", "ANTE", "APDN", "APTX", "AQMS", "ARAV", "ASXC",
            # Penny stocks / de-listed / halted that may appear
            "DWAC", "SOLO", "AYRO", "XL", "VLDR", "ARVL", "PTRA", "QS",
            # Known symbols with frequent data quality issues
            "GEO", "MPW", "INN",
        }
        
        # KNOWN LIQUID SYMBOLS - These ALWAYS bypass ADV API checks
        # Major stocks with guaranteed high liquidity - no need to verify via API
        # These will still respect intraday vs swing thresholds based on historical knowledge
        self._known_liquid_symbols: Set[str] = {
            # Mega caps - always liquid (>10M ADV typically)
            "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "NVDA", "TSLA", "BRK.B",
            "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "BAC",
            # Large tech
            "NFLX", "ADBE", "CRM", "ORCL", "CSCO", "INTC", "AMD", "QCOM", "TXN", "AVGO",
            "IBM", "NOW", "SNOW", "PANW", "CRWD", "ZS", "DDOG", "NET", "MDB", "TEAM",
            # Financials
            "GS", "MS", "C", "WFC", "AXP", "BLK", "SCHW", "CME", "ICE", "SPGI",
            "COF", "USB", "PNC", "TFC", "BK", "STT", "FITB", "KEY", "RF", "CFG",
            # Healthcare/Pharma
            "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY", "AMGN", "GILD",
            "ISRG", "VRTX", "REGN", "MRNA", "BIIB", "ZTS", "SYK", "BDX", "MDT", "EW",
            # Consumer
            "KO", "PEP", "COST", "MCD", "NKE", "SBUX", "TGT", "LOW", "TJX", "ROST",
            "YUM", "CMG", "DPZ", "LULU", "DECK", "ULTA", "EL", "CL", "KMB", "GIS",
            # Energy
            "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "VLO", "PSX", "OXY", "PXD",
            "DVN", "FANG", "HAL", "BKR", "KMI", "WMB", "OKE", "TRGP", "LNG", "ET",
            # Industrials
            "CAT", "DE", "UNP", "UPS", "FDX", "HON", "GE", "MMM", "LMT", "RTX",
            "BA", "GD", "NOC", "TDG", "ITW", "EMR", "ROK", "ETN", "PH", "IR",
            # ETFs - highest liquidity
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "EEM", "XLF", "XLE", "XLK",
            "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "VXX", "UVXY", "SQQQ",
            "TQQQ", "SPXU", "SPXS", "TNA", "TZA", "SOXL", "SOXS", "ARKK", "GLD", "SLV",
            # High volume momentum favorites
            "PLTR", "SOFI", "RIVN", "LCID", "NIO", "XPEV", "LI", "COIN", "HOOD", "RBLX",
            "SNAP", "PINS", "TWLO", "SQ", "PYPL", "SHOP", "ROKU", "ZM", "DOCU", "OKTA",
            "U", "UNITY", "ABNB", "DASH", "UBER", "LYFT", "GRAB", "SE", "MELI", "NU",
            # Biotech movers
            "MRNA", "BNTX", "NVAX", "SGEN", "EXAS", "DXCM", "ALGN", "HOLX", "ILMN", "BMRN",
            # Semiconductors
            "MU", "MRVL", "LRCX", "KLAC", "AMAT", "ASML", "TSM", "ON", "SWKS", "QRVO",
            # Recent IPO / high interest
            "ARM", "CART", "BIRK", "VRT", "SMCI", "CELH", "DUOL", "TOST", "BROS", "CAVA",
        }
        
        # Estimated ADV for known liquid symbols (used when API fails)
        # These are conservative estimates - actual ADV is typically higher
        self._known_liquid_adv: Dict[str, int] = {
            # ETFs - extremely high volume
            "SPY": 80_000_000, "QQQ": 50_000_000, "IWM": 25_000_000,
            "TQQQ": 30_000_000, "SQQQ": 20_000_000, "UVXY": 15_000_000,
            # Mega caps
            "AAPL": 60_000_000, "MSFT": 25_000_000, "AMZN": 30_000_000,
            "NVDA": 40_000_000, "TSLA": 80_000_000, "META": 15_000_000,
            "GOOGL": 20_000_000, "AMD": 40_000_000,
        }
        # Default for known liquid symbols not in the dict above
        self._known_liquid_default_adv = 2_000_000  # 2M shares/day minimum assumption
        
        # Intraday/scalp setups requiring higher volume
        self._intraday_setups = {
            "first_vwap_pullback", "first_move_up", "first_move_down", "bella_fade",
            "back_through_open", "up_through_open", "opening_drive",
            "orb", "hitchhiker", "spencer_scalp", "9_ema_scalp", "abc_scalp"
        }
        
        # Watchlist - expanded to 200+ symbols
        self._watchlist: List[str] = self._get_expanded_watchlist()
        
        # All available setups
        self._enabled_setups: Set[str] = {
            # Opening strategies
            "first_vwap_pullback", "first_move_up", "first_move_down", "bella_fade",
            "back_through_open", "up_through_open", "opening_drive",
            # Morning momentum
            "orb", "hitchhiker", "gap_give_go", "gap_pick_roll",
            # Core session
            "spencer_scalp", "second_chance", "backside", "off_sides", "fashionably_late",
            # Mean reversion
            "rubber_band", "vwap_bounce", "vwap_fade", "tidal_wave",
            "mean_reversion",  # NEW: RSI extreme + S/R snapback
            # Consolidation & Squeeze
            "big_dog", "puppy_dog", "9_ema_scalp", "abc_scalp",
            "squeeze",  # NEW: BB inside KC volatility compression
            # Afternoon
            "hod_breakout", "time_of_day_fade",
            # Special
            "breaking_news", "volume_capitulation", "range_break", "breakout",
            # NEW: Relative strength & gap plays
            "relative_strength",  # Leaders/laggards vs SPY
            "gap_fade",  # Fade failing gaps
            # Chart patterns
            "chart_pattern",  # Flags, pennants, triangles, H&S, wedges
        }
        
        # Alert management
        self._live_alerts: Dict[str, LiveAlert] = {}
        self._alert_subscribers: List[asyncio.Queue] = []
        self._max_alerts = 50
        
        # Stats
        self._scan_count = 0
        self._alerts_generated = 0
        self._last_scan_time: Optional[datetime] = None
        self._symbols_scanned_last = 0
        self._symbols_skipped_rvol = 0
        self._symbols_skipped_adv = 0  # Skipped due to low volume
        
        # Market context
        self._market_regime: MarketRegime = MarketRegime.RANGE_BOUND
        self._spy_data: Optional[Dict] = None
        
        # Strategy win-rate tracking
        self._strategy_stats: Dict[str, StrategyStats] = {}
        self._init_strategy_stats()
        
        # Auto-execution settings
        self._auto_execute_enabled = False
        self._auto_execute_min_win_rate = 0.55
        self._auto_execute_min_priority = AlertPriority.HIGH
        self._trading_bot = None
        
        # AI Assistant for proactive coaching notifications
        self._ai_assistant = None
        self._ai_notify_enabled = True  # Enable AI notifications for high-priority alerts
        self._ai_notify_min_priority = AlertPriority.HIGH  # Minimum priority to trigger AI notification
        
        # Services
        self._technical_service = None
        self._alpaca_service = None  # DEPRECATED: kept for interface compat, never used
        
        # DB collections - always initialize to None first
        self.alerts_collection = None
        self.stats_collection = None
        self.alert_outcomes_collection = None
        
        # Initialize collections if db is provided
        if db is not None:
            self._init_db_collections(db)
    
    def _init_db_collections(self, db):
        """Initialize database collections"""
        self.alerts_collection = db["live_alerts"]
        self.stats_collection = db["strategy_stats"]
        self.alert_outcomes_collection = db["alert_outcomes"]
        self._load_strategy_stats()
    
    def set_db(self, db):
        """Set database connection and initialize collections (used for late binding)"""
        self.db = db
        if db is not None:
            self._init_db_collections(db)
    
    def _init_strategy_stats(self):
        """Initialize strategy stats for all setups"""
        for setup in self._enabled_setups:
            self._strategy_stats[setup] = StrategyStats(setup_type=setup)
    
    def _load_strategy_stats(self):
        """Load strategy stats from database"""
        if self.stats_collection is not None:
            try:
                for doc in self.stats_collection.find():
                    setup_type = doc.get("setup_type")
                    if setup_type:
                        self._strategy_stats[setup_type] = StrategyStats(
                            setup_type=setup_type,
                            total_alerts=doc.get("total_alerts", 0),
                            alerts_triggered=doc.get("alerts_triggered", 0),
                            alerts_won=doc.get("alerts_won", 0),
                            alerts_lost=doc.get("alerts_lost", 0),
                            total_pnl=doc.get("total_pnl", 0.0),
                            avg_win=doc.get("avg_win", 0.0),
                            avg_loss=doc.get("avg_loss", 0.0),
                            win_rate=doc.get("win_rate", 0.0),
                            profit_factor=doc.get("profit_factor", 0.0),
                            avg_rr_achieved=doc.get("avg_rr_achieved", 0.0),
                            last_updated=doc.get("last_updated", "")
                        )
                logger.info(f"Loaded strategy stats for {len(self._strategy_stats)} setups")
            except Exception as e:
                logger.warning(f"Could not load strategy stats: {e}")
    
    def _save_strategy_stats(self, setup_type: str):
        """Save strategy stats to database"""
        if self.stats_collection is not None and setup_type in self._strategy_stats:
            stats = self._strategy_stats[setup_type]
            try:
                self.stats_collection.update_one(
                    {"setup_type": setup_type},
                    {"$set": asdict(stats)},
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Could not save strategy stats: {e}")
    
    # ==================== TRADING BOT INTEGRATION ====================
    
    def set_trading_bot(self, trading_bot):
        """Wire the trading bot for auto-execution"""
        self._trading_bot = trading_bot
        logger.info("Trading bot wired to scanner for auto-execution")
    
    def enable_auto_execute(self, enabled: bool = True, min_win_rate: float = 0.55, min_priority: str = "high"):
        """Enable/disable auto-execution of high-priority alerts"""
        self._auto_execute_enabled = enabled
        self._auto_execute_min_win_rate = min_win_rate
        self._auto_execute_min_priority = AlertPriority(min_priority)
        logger.info(f"Auto-execute {'enabled' if enabled else 'disabled'} (min_win_rate={min_win_rate}, min_priority={min_priority})")
    
    # ==================== AI ASSISTANT INTEGRATION ====================
    
    def set_ai_assistant(self, ai_assistant):
        """Wire the AI assistant for proactive coaching notifications"""
        self._ai_assistant = ai_assistant
        logger.info("AI assistant wired to scanner for proactive notifications")
    
    def enable_ai_notifications(self, enabled: bool = True, min_priority: str = "high"):
        """Enable/disable AI proactive notifications for scanner alerts"""
        self._ai_notify_enabled = enabled
        self._ai_notify_min_priority = AlertPriority(min_priority)
        logger.info(f"AI notifications {'enabled' if enabled else 'disabled'} (min_priority={min_priority})")
    
    async def _notify_ai_of_alert(self, alert: LiveAlert):
        """
        Send proactive AI coaching notification for high-priority alerts.
        Creates both a chat message in AI panel AND triggers toast notification.
        """
        if not self._ai_assistant or not self._ai_notify_enabled:
            return
        
        # Only notify for high-priority alerts
        priority_order = {AlertPriority.CRITICAL: 4, AlertPriority.HIGH: 3, AlertPriority.MEDIUM: 2, AlertPriority.LOW: 1}
        min_priority_val = priority_order.get(self._ai_notify_min_priority, 3)
        alert_priority_val = priority_order.get(alert.priority, 1)
        
        if alert_priority_val < min_priority_val:
            return
        
        try:
            # Generate coaching context for this alert
            coaching_data = {
                "symbol": alert.symbol,
                "setup_type": alert.setup_type,
                "direction": alert.direction,
                "current_price": alert.current_price,
                "trigger_price": alert.trigger_price,
                "stop_loss": alert.stop_loss,
                "target": alert.target,
                "risk_reward": alert.risk_reward,
                "win_rate": alert.strategy_win_rate,
                "tape_confirmation": alert.tape_confirmation,
                "headline": alert.headline,
                "reasoning": alert.reasoning[:3] if alert.reasoning else [],
                "time_window": alert.time_window,
                "market_regime": alert.market_regime,
                "priority": alert.priority.value
            }
            
            # Call AI to generate proactive coaching message
            if hasattr(self._ai_assistant, 'generate_scanner_coaching'):
                coaching_result = await self._ai_assistant.generate_scanner_coaching(coaching_data)
                if coaching_result.get("success"):
                    logger.info(f"🧠 AI coaching generated for {alert.symbol}: {coaching_result.get('summary', '')[:50]}...")
            else:
                # Fallback: use existing coaching alert method
                coaching_result = await self._ai_assistant.get_coaching_alert(
                    "scanner_opportunity",
                    coaching_data
                )
                logger.info(f"🧠 AI notified of {alert.symbol} opportunity")
                
        except Exception as e:
            logger.warning(f"AI notification failed for {alert.symbol}: {e}")
    
    def set_volume_filters(self, min_adv_general: int = 100_000, min_adv_intraday: int = 500_000):
        """
        Configure average daily volume (ADV) filters.
        
        Args:
            min_adv_general: Minimum ADV for general/swing setups (default 100K)
            min_adv_intraday: Minimum ADV for intraday/scalp setups (default 500K)
        """
        self._min_adv_general = min_adv_general
        self._min_adv_intraday = min_adv_intraday
        logger.info(f"Volume filters updated: General>={min_adv_general:,}, Intraday>={min_adv_intraday:,}")
    
    def get_volume_filter_config(self) -> Dict:
        """Get current volume filter configuration"""
        return {
            "min_adv_general": self._min_adv_general,
            "min_adv_intraday": self._min_adv_intraday,
            "intraday_setups": list(self._intraday_setups),
            "symbols_skipped_adv_last_scan": getattr(self, '_symbols_skipped_adv', 0),
            "blacklisted_symbols_count": len(self._blacklisted_symbols),
            "known_liquid_symbols_count": len(self._known_liquid_symbols),
            "adv_cache_ttl_seconds": self._adv_cache_ttl,
        }
    
    def add_to_blacklist(self, symbols: List[str]) -> Dict:
        """
        Add symbols to the blacklist. These symbols will never generate alerts.
        
        Args:
            symbols: List of symbols to blacklist
        
        Returns:
            Dict with added count and current blacklist size
        """
        added = 0
        for symbol in symbols:
            symbol = symbol.upper()
            if symbol not in self._blacklisted_symbols:
                self._blacklisted_symbols.add(symbol)
                added += 1
                # Clear any cached ADV for this symbol
                if symbol in self._adv_cache:
                    del self._adv_cache[symbol]
        
        logger.info(f"Added {added} symbols to scanner blacklist. Total: {len(self._blacklisted_symbols)}")
        return {
            "added": added,
            "total_blacklisted": len(self._blacklisted_symbols)
        }
    
    def remove_from_blacklist(self, symbols: List[str]) -> Dict:
        """
        Remove symbols from the blacklist.
        
        Args:
            symbols: List of symbols to remove
        
        Returns:
            Dict with removed count and current blacklist size
        """
        removed = 0
        for symbol in symbols:
            symbol = symbol.upper()
            if symbol in self._blacklisted_symbols:
                self._blacklisted_symbols.discard(symbol)
                removed += 1
        
        logger.info(f"Removed {removed} symbols from scanner blacklist. Total: {len(self._blacklisted_symbols)}")
        return {
            "removed": removed,
            "total_blacklisted": len(self._blacklisted_symbols)
        }
    
    def get_blacklist(self) -> List[str]:
        """Get the current blacklist of symbols"""
        return sorted(list(self._blacklisted_symbols))
    
    def is_blacklisted(self, symbol: str) -> bool:
        """Check if a symbol is blacklisted"""
        return symbol.upper() in self._blacklisted_symbols
    
    async def _auto_execute_alert(self, alert: LiveAlert):
        """Auto-execute an alert through the trading bot"""
        if not self._trading_bot or not self._auto_execute_enabled:
            return
        
        # Check eligibility
        if not alert.auto_execute_eligible:
            return
        
        try:
            logger.info(f"🤖 Auto-executing alert: {alert.headline}")
            
            # Create trade request for bot
            trade_request = {
                "symbol": alert.symbol,
                "direction": alert.direction,
                "setup_type": alert.setup_type,
                "entry_price": alert.current_price,
                "stop_loss": alert.stop_loss,
                "target": alert.target,
                "source": "scanner_auto_execute",
                "alert_id": alert.id
            }
            
            # Submit to trading bot
            if hasattr(self._trading_bot, 'submit_trade_from_scanner'):
                await self._trading_bot.submit_trade_from_scanner(trade_request)
            else:
                logger.warning("Trading bot does not have submit_trade_from_scanner method")
                
        except Exception as e:
            logger.error(f"Auto-execute failed: {e}")
    
    # ==================== POSITION SIZING HELPER ====================
    
    def _calculate_position_sizing(self, current_price: float, stop_loss: float, 
                                   direction: str, atr: float = 0, atr_percent: float = 0) -> Dict:
        """
        Calculate volatility-adjusted position sizing for an alert.
        
        Args:
            current_price: Current stock price
            stop_loss: Stop loss price
            direction: 'long' or 'short'
            atr: Average True Range in dollars
            atr_percent: ATR as percentage of price
        
        Returns:
            Dict with suggested_shares, suggested_risk, volatility_regime
        """
        # Default ATR if not provided
        if not atr or atr <= 0:
            atr = current_price * 0.02  # Default 2% ATR
            atr_percent = 2.0
        
        # Determine volatility regime
        if atr_percent < 1.5:
            volatility_regime = "low"
            vol_multiplier = 1.3
        elif atr_percent < 2.5:
            volatility_regime = "normal"
            vol_multiplier = 1.0
        elif atr_percent < 4.0:
            volatility_regime = "high"
            vol_multiplier = 0.75
        else:
            volatility_regime = "extreme"
            vol_multiplier = 0.5
        
        # Calculate risk per share
        risk_per_share = abs(current_price - stop_loss)
        if risk_per_share <= 0:
            risk_per_share = atr  # Fallback to ATR
        
        # Base max risk per trade
        base_max_risk = 2500.0
        adjusted_max_risk = base_max_risk * vol_multiplier
        
        # Calculate shares
        shares = int(adjusted_max_risk / risk_per_share) if risk_per_share > 0 else 0
        shares = max(shares, 1)
        
        # Cap based on position value (10% of capital)
        max_capital = 1_000_000  # Assumed capital
        max_position_value = max_capital * 0.10
        max_shares_by_capital = int(max_position_value / current_price)
        shares = min(shares, max_shares_by_capital)
        
        # Calculate actual risk
        risk_amount = shares * risk_per_share
        
        return {
            "suggested_shares": shares,
            "suggested_risk": round(risk_amount, 2),
            "volatility_regime": volatility_regime,
            "atr": round(atr, 2),
            "atr_percent": round(atr_percent, 2),
            "vol_multiplier": vol_multiplier
        }
    
    # ==================== EXPANDED WATCHLIST ====================
    
    def _get_expanded_watchlist(self) -> List[str]:
        """Get expanded 200+ symbol watchlist"""
        return [
            # Mega Cap Tech (Most Active)
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            # Large Cap Tech
            "AMD", "INTC", "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO",
            "TXN", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "SNPS", "CDNS",
            # Growth Tech
            "NFLX", "SHOP", "SQ", "COIN", "SNOW", "DDOG", "NET", "CRWD",
            "ZS", "OKTA", "PANW", "FTNT", "PLTR", "RBLX", "U", "HOOD",
            "SOFI", "UPST", "AFRM", "MELI", "SE", "GRAB", "BABA", "JD", "PDD",
            # Financials
            "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK", "AXP",
            "V", "MA", "PYPL", "COF", "DFS", "SYF",
            # Healthcare/Biotech
            "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "AMGN",
            "GILD", "BIIB", "MRNA", "BNTX", "REGN", "VRTX", "ISRG",
            # Consumer
            "HD", "LOW", "TGT", "WMT", "COST", "NKE", "SBUX",
            "MCD", "DIS", "CMCSA", "ABNB", "BKNG", "MAR", "RCL",
            # Energy
            "XOM", "CVX", "COP", "SLB", "EOG", "PXD", "DVN", "OXY",
            "MPC", "VLO", "PSX", "HAL", "BKR",
            # Industrials
            "BA", "CAT", "DE", "HON", "UPS", "FDX", "GE", "RTX", "LMT",
            "NOC", "GD", "MMM", "EMR",
            # Materials
            "LIN", "APD", "FCX", "NEM", "NUE", "CLF", "X", "AA",
            # ETFs (for market context and trading)
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI",
            "XLY", "XLP", "XLU", "XLRE", "XLC", "XLB",
            "ARKK", "ARKG", "ARKF", "SOXL", "SOXS", "TQQQ", "SQQQ",
            # High Volume Movers (frequently in play)
            "GME", "AMC", "CLOV", "WISH", "SPCE", "LCID", "RIVN",
            "NIO", "XPEV", "LI", "F", "GM",
            # Semiconductors (often trending)
            "TSM", "ASML", "MCHP", "ADI", "ON", "SWKS", "QRVO", "WOLF",
            # Software/Cloud
            "NOW", "WDAY", "ZM", "DOCU", "TWLO", "TEAM", "MNDY", "HUBS",
            "BILL", "PCTY", "PAYC", "VEEV", "SPLK", "ESTC",
            # Cybersecurity
            "S", "QLYS", "TENB",
            # Social/Advertising
            "SNAP", "PINS", "TTD", "MGNI", "PUBM",
            # E-commerce/Payments
            "TOST",
            # Gaming/Entertainment
            "EA", "TTWO", "DKNG", "PENN", "MGM", "WYNN", "LVS",
            # Cannabis (high volatility)
            "TLRY", "CGC", "ACB", "CRON",
            # SPACs/Recent IPOs (high volatility)
            "DWAC", "IONQ", "JOBY", "LILM",
            # REITs
            "AMT", "PLD", "EQIX", "DLR", "SPG", "O", "VICI",
            # Airlines (volatile)
            "DAL", "UAL", "AAL", "LUV", "JBLU",
            # Auto
            # Retail
            "DLTR", "DG", "FIVE", "OLLI",
            # Restaurants
            "CMG", "YUM", "DPZ", "QSR",
        ]
    
    # ==================== RVOL PRE-FILTERING & WAVE SCANNING ====================
    
    async def _get_active_symbols(self) -> List[str]:
        """
        Get symbols to scan using wave-based approach:
        - Tier 1: Smart Watchlist (always)
        - Tier 2: High RVOL pool
        - Tier 3: Rotating universe wave
        """
        active_symbols = []
        skipped = 0
        
        try:
            # Use wave scanner for tiered symbol selection
            from services.wave_scanner import get_wave_scanner
            wave_scanner = get_wave_scanner()
            
            batch = await wave_scanner.get_scan_batch()
            
            # Combine all tiers
            all_symbols = []
            all_symbols.extend(batch.get("tier1_watchlist", []))
            all_symbols.extend(batch.get("tier2_high_rvol", []))
            all_symbols.extend(batch.get("tier3_wave", []))
            
            # Remove duplicates while preserving order (Tier 1 priority)
            seen = set()
            for symbol in all_symbols:
                if symbol not in seen:
                    seen.add(symbol)
                    active_symbols.append(symbol)
            
            wave_info = batch.get("universe_progress", {})
            logger.debug(
                f"Wave scan batch: T1={len(batch.get('tier1_watchlist', []))} "
                f"T2={len(batch.get('tier2_high_rvol', []))} "
                f"T3={len(batch.get('tier3_wave', []))} "
                f"Wave={wave_info.get('current_wave', 0)}/{wave_info.get('total_waves', 0)} "
                f"({wave_info.get('progress_pct', 0)}%)"
            )
            
        except Exception as e:
            logger.warning(f"Wave scanner unavailable, falling back to static watchlist: {e}")
            # Fallback to static watchlist - prioritize IB data
            for symbol in self._watchlist:
                try:
                    # Check cache first
                    if symbol in self._rvol_cache:
                        cached_rvol, cached_time = self._rvol_cache[symbol]
                        if (datetime.now(timezone.utc) - cached_time).total_seconds() < self._rvol_cache_ttl:
                            if cached_rvol >= self._min_rvol_filter:
                                active_symbols.append(symbol)
                            else:
                                skipped += 1
                            continue
                    
                    # Quick quote check - IB first, then Alpaca
                    quote = await self._get_quote_with_ib_priority(symbol)
                    if quote and quote.get("price", 0) > 0:
                        active_symbols.append(symbol)
                        self._rvol_cache[symbol] = (1.0, datetime.now(timezone.utc))
                    else:
                        skipped += 1
                        self._rvol_cache[symbol] = (0.0, datetime.now(timezone.utc))
                        
                except Exception as e:
                    active_symbols.append(symbol)
        
        self._symbols_skipped_rvol = skipped
        return active_symbols
    
    # ==================== TAPE READING ====================
    
    async def _get_tape_reading(self, symbol: str, snapshot) -> TapeReading:
        """
        Analyze tape for confirmation signals, incorporating Level 2 if available.
        PRIORITIZES IB pushed data for real-time quotes, falls back to Alpaca.
        """
        try:
            # Get quote with IB priority
            quote = await self._get_quote_with_ib_priority(symbol)
            if not quote:
                quote = {}
            
            bid_price = quote.get("bid", snapshot.current_price * 0.999)
            ask_price = quote.get("ask", snapshot.current_price * 1.001)
            bid_size = quote.get("bid_size", 100)
            ask_size = quote.get("ask_size", 100)
            
            spread = ask_price - bid_price
            spread_pct = (spread / snapshot.current_price) * 100 if snapshot.current_price > 0 else 0
            
            # Try to get Level 2 data from IB pusher
            l2_imbalance = None
            l2_bid_depth = 0
            l2_ask_depth = 0
            l2_available = False
            
            try:
                from routers.ib import get_level2_for_symbol
                l2_data = get_level2_for_symbol(symbol)
                if l2_data:
                    l2_available = True
                    l2_imbalance = l2_data.get("imbalance", 0.0)
                    l2_bid_depth = l2_data.get("bid_total_size", 0)
                    l2_ask_depth = l2_data.get("ask_total_size", 0)
                    
                    # Override bid/ask sizes with L2 depth (more accurate)
                    if l2_bid_depth > 0:
                        bid_size = l2_bid_depth
                    if l2_ask_depth > 0:
                        ask_size = l2_ask_depth
            except Exception as e:
                logger.debug(f"L2 not available for {symbol}: {e}")
            
            # Spread signal
            if spread_pct < 0.05:
                spread_signal = TapeSignal.TIGHT_SPREAD
            elif spread_pct > 0.2:
                spread_signal = TapeSignal.WIDE_SPREAD
            else:
                spread_signal = TapeSignal.NEUTRAL
            
            # Order imbalance - prefer L2 if available
            if l2_imbalance is not None:
                imbalance = l2_imbalance
            else:
                total_size = bid_size + ask_size
                imbalance = (bid_size - ask_size) / total_size if total_size > 0 else 0
            
            if imbalance > 0.3:
                imbalance_signal = TapeSignal.STRONG_BID
            elif imbalance < -0.3:
                imbalance_signal = TapeSignal.STRONG_ASK
            else:
                imbalance_signal = TapeSignal.NEUTRAL
            
            # Momentum signal from RVOL and price action
            if snapshot.rvol >= 2.0 and snapshot.dist_from_ema9 > 0:
                momentum_signal = TapeSignal.MOMENTUM_UP
            elif snapshot.rvol >= 2.0 and snapshot.dist_from_ema9 < 0:
                momentum_signal = TapeSignal.MOMENTUM_DOWN
            elif snapshot.rvol >= 5.0:
                momentum_signal = TapeSignal.EXHAUSTION
            else:
                momentum_signal = TapeSignal.NEUTRAL
            
            # Calculate tape score (-1 to 1)
            tape_score = 0.0
            
            # Spread contribution (tight = good)
            if spread_signal == TapeSignal.TIGHT_SPREAD:
                tape_score += 0.2
            elif spread_signal == TapeSignal.WIDE_SPREAD:
                tape_score -= 0.2
            
            # Imbalance contribution
            tape_score += imbalance * 0.4  # -0.4 to +0.4
            
            # Momentum contribution
            if momentum_signal == TapeSignal.MOMENTUM_UP:
                tape_score += 0.3
            elif momentum_signal == TapeSignal.MOMENTUM_DOWN:
                tape_score -= 0.3
            
            # Overall signal
            if tape_score > 0.3:
                overall_signal = TapeSignal.STRONG_BID
            elif tape_score < -0.3:
                overall_signal = TapeSignal.STRONG_ASK
            else:
                overall_signal = TapeSignal.NEUTRAL
            
            # L2 Gate monitoring (not enforced yet, just tracked)
            # Gate would pass for LONG if: imbalance > 0 (more bids than asks)
            # Gate would pass for SHORT if: imbalance < 0 (more asks than bids)
            l2_gate_would_pass_long = True
            l2_gate_would_pass_short = True
            
            if l2_available:
                # Stricter L2 gate: require positive imbalance for longs
                l2_gate_would_pass_long = l2_imbalance > 0.1  # At least 10% more bids
                l2_gate_would_pass_short = l2_imbalance < -0.1  # At least 10% more asks
            
            return TapeReading(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc).isoformat(),
                bid_price=bid_price,
                ask_price=ask_price,
                spread=spread,
                spread_pct=spread_pct,
                spread_signal=spread_signal,
                bid_size=bid_size,
                ask_size=ask_size,
                imbalance=imbalance,
                imbalance_signal=imbalance_signal,
                price_momentum=snapshot.dist_from_ema9,
                volume_momentum=snapshot.rvol,
                momentum_signal=momentum_signal,
                overall_signal=overall_signal,
                tape_score=tape_score,
                confirmation_for_long=tape_score > 0.2,
                confirmation_for_short=tape_score < -0.2,
                l2_available=l2_available,
                l2_imbalance=l2_imbalance if l2_imbalance else 0.0,
                l2_bid_depth=l2_bid_depth,
                l2_ask_depth=l2_ask_depth,
                l2_gate_would_pass_long=l2_gate_would_pass_long,
                l2_gate_would_pass_short=l2_gate_would_pass_short
            )
            
        except Exception as e:
            logger.warning(f"Tape reading error for {symbol}: {e}")
            return TapeReading(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc).isoformat(),
                bid_price=snapshot.current_price,
                ask_price=snapshot.current_price,
                spread=0,
                spread_pct=0,
                spread_signal=TapeSignal.NEUTRAL,
                bid_size=0,
                ask_size=0,
                imbalance=0,
                imbalance_signal=TapeSignal.NEUTRAL,
                price_momentum=0,
                volume_momentum=1.0,
                momentum_signal=TapeSignal.NEUTRAL,
                overall_signal=TapeSignal.NEUTRAL,
                tape_score=0,
                confirmation_for_long=False,
                confirmation_for_short=False
            )
    
    # ==================== WIN-RATE TRACKING ====================
    
    def record_alert_outcome(self, alert_id: str, outcome: str, pnl: float = 0.0, exit_price: float = None):
        """
        Record the outcome of an alert for win-rate and EV tracking.
        SMB-style: Tracks R-multiples for Expected Value calculation.
        """
        if alert_id not in self._live_alerts:
            return
        
        alert = self._live_alerts[alert_id]
        setup_type = alert.setup_type.split("_")[0] if "_long" in alert.setup_type or "_short" in alert.setup_type else alert.setup_type
        
        if setup_type not in self._strategy_stats:
            self._strategy_stats[setup_type] = StrategyStats(setup_type=setup_type)
        
        stats = self._strategy_stats[setup_type]
        stats.alerts_triggered += 1
        
        # Calculate R-multiple for this trade
        r_multiple = 0.0
        risk_per_share = abs(alert.current_price - alert.stop_loss)
        
        if risk_per_share > 0 and exit_price is not None:
            if alert.direction == "long":
                profit_per_share = exit_price - alert.current_price
            else:
                profit_per_share = alert.current_price - exit_price
            r_multiple = profit_per_share / risk_per_share
        elif risk_per_share > 0 and pnl != 0:
            # Estimate R-multiple from PnL if exit_price not provided
            # This is approximate - assumes full position
            estimated_shares = abs(pnl) / risk_per_share if outcome == "lost" else abs(pnl) / (alert.target - alert.current_price) if alert.target != alert.current_price else 1
            r_multiple = pnl / (risk_per_share * max(estimated_shares, 1)) if estimated_shares > 0 else 0
        
        # Update stats based on outcome
        if outcome == "won":
            stats.alerts_won += 1
            stats.total_pnl += pnl
            if stats.alerts_won > 0:
                stats.avg_win = stats.total_pnl / stats.alerts_won if stats.total_pnl > 0 else stats.avg_win
            # R-multiple for wins should be positive
            if r_multiple <= 0:
                r_multiple = alert.risk_reward  # Use projected R:R as estimate
        elif outcome == "lost":
            stats.alerts_lost += 1
            stats.total_pnl += pnl  # pnl is negative for losses
            if stats.alerts_lost > 0:
                total_losses = stats.total_pnl - (stats.avg_win * stats.alerts_won) if stats.alerts_won > 0 else stats.total_pnl
                stats.avg_loss = total_losses / stats.alerts_lost
            # R-multiple for losses should be negative (typically -1R at stop)
            if r_multiple >= 0:
                r_multiple = -1.0  # Standard 1R loss
        
        # Record R-multiple for EV calculation
        stats.record_r_outcome(r_multiple, alert.trade_grade)
        
        stats.update_win_rate()
        self._save_strategy_stats(setup_type)
        
        # Update alert
        alert.outcome = outcome
        alert.actual_pnl = pnl
        alert.actual_r_multiple = r_multiple
        alert.workflow_state = "reviewed"
        
        # Save to outcomes collection with R-multiple data
        if self.alert_outcomes_collection is not None:
            try:
                self.alert_outcomes_collection.insert_one({
                    "alert_id": alert_id,
                    "symbol": alert.symbol,
                    "setup_type": setup_type,
                    "direction": alert.direction,
                    "outcome": outcome,
                    "pnl": pnl,
                    "r_multiple": r_multiple,
                    "trade_grade": alert.trade_grade,
                    "entry_price": alert.current_price,
                    "exit_price": exit_price,
                    "stop_loss": alert.stop_loss,
                    "target": alert.target,
                    "projected_rr": alert.risk_reward,
                    "created_at": alert.created_at,
                    "closed_at": datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                logger.warning(f"Could not save alert outcome: {e}")
        
        # Log with EV information
        ev_info = f"EV: {stats.expected_value_r:.2f}R" if len(stats.r_outcomes) >= 5 else "EV: tracking"
        logger.info(f"📊 Recorded {outcome} ({r_multiple:+.2f}R) for {setup_type}: Win rate {stats.win_rate:.1%}, {ev_info}")
    
    def get_strategy_ev(self, setup_type: str) -> dict:
        """Get SMB-style Expected Value assessment for a strategy"""
        if setup_type in self._strategy_stats:
            return self._strategy_stats[setup_type].get_ev_assessment()
        return {"setup_type": setup_type, "is_positive_ev": False, "recommendation": "NO_DATA"}
    
    def get_all_strategy_ev(self) -> dict:
        """Get EV assessments for all strategies"""
        return {
            setup: stats.get_ev_assessment() 
            for setup, stats in self._strategy_stats.items()
        }
    
    def get_strategy_stats(self, setup_type: str = None) -> Dict:
        """Get win-rate stats for a strategy or all strategies"""
        if setup_type:
            if setup_type in self._strategy_stats:
                return asdict(self._strategy_stats[setup_type])
            return {}
        
        return {k: asdict(v) for k, v in self._strategy_stats.items()}
    
    # ==================== MARKET CONTEXT ====================
    
    def _get_current_time_window(self) -> TimeWindow:
        """Determine current time window for strategy filtering"""
        now = datetime.now(timezone(timedelta(hours=-5)))  # EST
        hour = now.hour
        minute = now.minute
        total_minutes = hour * 60 + minute
        
        # Pre-market or after hours
        if total_minutes < 570:  # Before 9:30
            return TimeWindow.CLOSED
        if total_minutes >= 960:  # After 16:00
            return TimeWindow.CLOSED
        
        # Market hours
        if total_minutes < 575:  # 9:30-9:35
            return TimeWindow.OPENING_AUCTION
        if total_minutes < 585:  # 9:35-9:45
            return TimeWindow.OPENING_DRIVE
        if total_minutes < 600:  # 9:45-10:00
            return TimeWindow.MORNING_MOMENTUM
        if total_minutes < 645:  # 10:00-10:45
            return TimeWindow.MORNING_SESSION
        if total_minutes < 690:  # 10:45-11:30
            return TimeWindow.LATE_MORNING
        if total_minutes < 810:  # 11:30-13:30
            return TimeWindow.MIDDAY
        if total_minutes < 900:  # 13:30-15:00
            return TimeWindow.AFTERNOON
        return TimeWindow.CLOSE  # 15:00-16:00
    
    async def _update_market_context(self):
        """Update market regime based on SPY analysis"""
        try:
            spy_snapshot = await self.technical_service.get_technical_snapshot("SPY")
            if not spy_snapshot:
                return
            
            self._spy_data = spy_snapshot
            
            # Determine regime based on SPY characteristics
            dist_from_vwap = spy_snapshot.dist_from_vwap
            rsi = spy_snapshot.rsi_14
            daily_range = spy_snapshot.daily_range_pct
            trend = spy_snapshot.trend
            
            # High volatility
            if daily_range > 2.0:
                self._market_regime = MarketRegime.VOLATILE
            # Strong uptrend
            elif trend == "uptrend" and spy_snapshot.above_vwap and spy_snapshot.above_ema9:
                if rsi > 60:
                    self._market_regime = MarketRegime.MOMENTUM
                else:
                    self._market_regime = MarketRegime.STRONG_UPTREND
            # Strong downtrend
            elif trend == "downtrend" and not spy_snapshot.above_vwap:
                self._market_regime = MarketRegime.STRONG_DOWNTREND
            # Range bound / fade
            elif abs(dist_from_vwap) < 0.5 and daily_range < 1.0:
                self._market_regime = MarketRegime.FADE if rsi > 55 or rsi < 45 else MarketRegime.RANGE_BOUND
            else:
                self._market_regime = MarketRegime.RANGE_BOUND
            
            logger.debug(f"Market regime updated: {self._market_regime.value}")
            
        except Exception as e:
            logger.warning(f"Could not update market context: {e}")
    
    def _is_setup_valid_now(self, setup_type: str) -> bool:
        """Check if setup is valid for current time and market regime"""
        current_window = self._get_current_time_window()
        
        # Check time window
        valid_windows = STRATEGY_TIME_WINDOWS.get(setup_type, [])
        if valid_windows and current_window not in valid_windows:
            return False
        
        return True
    
    # ==================== SERVICE PROPERTIES ====================
    
    @property
    def technical_service(self):
        if self._technical_service is None:
            from services.realtime_technical_service import get_technical_service
            self._technical_service = get_technical_service()
        return self._technical_service
    
    @property
    def alpaca_service(self):
        """DEPRECATED: Alpaca removed from critical path. Returns None."""
        return None
    
    # ==================== IB DATA HELPERS ====================
    
    def _get_ib_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get quote from IB pushed data (non-async, fast).
        Prioritizes IB data over Alpaca for real-time accuracy.
        Returns None if IB data not available.
        """
        try:
            import routers.ib as ib_module
            if ib_module.is_pusher_connected():
                quotes = ib_module.get_pushed_quotes()
                symbol_upper = symbol.upper()
                if symbol_upper in quotes:
                    q = quotes[symbol_upper]
                    return {
                        "symbol": symbol_upper,
                        "price": q.get("last") or q.get("close") or 0,
                        "bid": q.get("bid") or 0,
                        "ask": q.get("ask") or 0,
                        "bid_size": q.get("bidSize") or q.get("bid_size") or 100,
                        "ask_size": q.get("askSize") or q.get("ask_size") or 100,
                        "volume": q.get("volume") or 0,
                        "high": q.get("high") or 0,
                        "low": q.get("low") or 0,
                        "open": q.get("open") or 0,
                        "close": q.get("close") or 0,
                        "source": "ib_pusher"
                    }
        except Exception as e:
            logger.debug(f"IB quote not available for {symbol}: {e}")
        return None
    
    def _is_ib_connected(self) -> bool:
        """Check if IB pusher is connected (non-async)."""
        try:
            import routers.ib as ib_module
            return ib_module.is_pusher_connected()
        except Exception:
            return False
    
    async def _get_quote_with_ib_priority(self, symbol: str) -> Optional[Dict]:
        """
        Get quote with IB pusher as primary source, MongoDB latest bar as fallback.
        100% IB data — no Alpaca fallback (eliminates train/serve data skew).
        """
        # Try IB first (fast, non-async)
        ib_quote = self._get_ib_quote(symbol)
        if ib_quote and ib_quote.get("price", 0) > 0:
            return ib_quote
        
        # Fallback: latest bar close from ib_historical_data
        try:
            if self.db is not None:
                bar = self.db["ib_historical_data"].find_one(
                    {"symbol": symbol.upper(), "bar_size": {"$in": ["5 mins", "1 min", "1 day"]}},
                    {"_id": 0, "close": 1, "open": 1, "high": 1, "low": 1, "volume": 1, "date": 1},
                    sort=[("date", -1)]
                )
                if bar and bar.get("close", 0) > 0:
                    return {
                        "symbol": symbol.upper(),
                        "price": bar["close"],
                        "bid": bar["close"],
                        "ask": bar["close"],
                        "volume": bar.get("volume", 0),
                        "high": bar.get("high", bar["close"]),
                        "low": bar.get("low", bar["close"]),
                        "open": bar.get("open", bar["close"]),
                        "close": bar["close"],
                        "source": "mongodb_bar"
                    }
        except Exception as e:
            logger.debug(f"MongoDB bar fallback failed for {symbol}: {e}")
        
        return None
    
    # ==================== LIFECYCLE ====================
    
    async def start(self):
        """Start the background scanner"""
        if self._running:
            logger.warning("Enhanced scanner already running")
            return
        
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(f"🚀 Enhanced scanner started - {len(self._watchlist)} symbols, {len(self._enabled_setups)} strategies")
    
    async def stop(self):
        """Stop the background scanner"""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        logger.info("⏹️ Enhanced scanner stopped")
    
    # ==================== MAIN SCAN LOOP ====================
    
    async def _scan_loop(self):
        """Main scanning loop with optimizations"""
        logger.info("Enhanced scan loop started")
        
        while self._running:
            try:
                # Check if collection mode is active — pause scanning to free backend resources
                try:
                    from services.collection_mode import is_active as _collection_active
                    if _collection_active():
                        if self._scan_count % 60 == 0:
                            logger.info("📦 Enhanced scanner paused — collection mode active")
                        await asyncio.sleep(60)
                        continue
                except Exception:
                    pass
                
                # Check focus mode — pause during training/backtesting
                try:
                    from services.focus_mode_manager import focus_mode_manager
                    if not focus_mode_manager.should_run_task('background_scanner'):
                        if self._scan_count % 60 == 0:
                            logger.info("Enhanced scanner paused — training/backtesting active (focus mode)")
                        await asyncio.sleep(60)
                        continue
                except Exception:
                    pass
                
                # Enforce minimum interval between scans
                if self._last_scan_time:
                    now = datetime.now(timezone.utc)
                    elapsed = (now - self._last_scan_time).total_seconds()
                    if elapsed < self._min_scan_interval:
                        await asyncio.sleep(self._min_scan_interval - elapsed)
                        continue
                
                # Update market context first
                await self._update_market_context()
                
                # Check if market is open
                current_window = self._get_current_time_window()
                if current_window == TimeWindow.CLOSED:
                    logger.debug("Market closed, skipping scan")
                    await asyncio.sleep(60)
                    continue
                
                # Run optimized scan
                scan_start = datetime.now()
                await self._run_optimized_scan()
                scan_duration = (datetime.now() - scan_start).total_seconds()
                
                self._last_scan_time = datetime.now(timezone.utc)
                self._scan_count += 1
                
                logger.info(
                    f"📊 Scan #{self._scan_count} in {scan_duration:.1f}s | "
                    f"Regime: {self._market_regime.value} | Window: {current_window.value} | "
                    f"Scanned: {self._symbols_scanned_last} | "
                    f"Skipped: ADV={self._symbols_skipped_adv}, RVOL={self._symbols_skipped_rvol} | "
                    f"Alerts: {len(self._live_alerts)}"
                )
                
                # Clean up expired alerts
                self._cleanup_expired_alerts()
                
                # Run daily/swing/position scans every 10th cycle
                if self._scan_count % 10 == 0:
                    await self._scan_daily_setups()
                
                # Wait for next scan
                await asyncio.sleep(self._scan_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Enhanced scan error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(10)
    
    async def _run_optimized_scan(self):
        """
        Run optimized scan with ADV as FIRST checkpoint and tiered frequency.
        
        Flow:
        1. Get candidate symbols from wave scanner
        2. FIRST FILTER: Check ADV (skip if < minimum investment threshold)
        3. TIER FILTER: Select symbols based on scan frequency tier
        4. SECOND FILTER: Check RVOL (skip if < threshold)
        5. Only then: Get full snapshot and run setup checks
        """
        # Reset counters
        self._symbols_skipped_rvol = 0
        self._symbols_skipped_adv = 0
        
        # Get candidate symbols from wave scanner
        all_candidates = await self._get_active_symbols()
        
        # FIRST CHECKPOINT: Pre-filter by ADV before ANY expensive operations
        adv_filtered_symbols = await self._prefilter_by_adv(all_candidates)
        
        # TIER FILTER: Select symbols for THIS cycle based on ADV tier
        tiered_symbols = self._get_symbols_for_cycle(adv_filtered_symbols)
        
        self._symbols_scanned_last = len(tiered_symbols)
        
        logger.debug(
            f"Scanning {len(tiered_symbols)} symbols this cycle "
            f"(from {len(adv_filtered_symbols)} ADV-qualified, {len(all_candidates)} total, "
            f"skipped ADV={self._symbols_skipped_adv})"
        )
        
        # Scan in batches with concurrent processing
        for i in range(0, len(tiered_symbols), self._symbols_per_batch):
            batch = tiered_symbols[i:i + self._symbols_per_batch]
            
            # Process batch concurrently
            tasks = [self._scan_symbol_all_setups(symbol) for symbol in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Small delay between batches
            if i + self._symbols_per_batch < len(tiered_symbols):
                await asyncio.sleep(self._batch_delay)
    
    async def _prefilter_by_adv(self, symbols: List[str]) -> List[str]:
        """
        Pre-filter symbols by Average Daily Volume (ADV).
        This is the FIRST checkpoint - runs BEFORE any other scanning.
        
        Uses cached ADV when available, fetches fresh data for unknown symbols.
        Symbols below minimum ADV are completely skipped (no further processing).
        
        FAIL CLOSED: If ADV data cannot be fetched, the symbol is REJECTED (not allowed through).
        This prevents illiquid or problematic symbols from generating alerts due to data errors.
        """
        now = datetime.now(timezone.utc)
        qualified_symbols = []
        symbols_needing_adv = []
        symbols_blacklisted = 0
        symbols_known_liquid = 0
        
        # Check cache first for quick filtering
        for symbol in symbols:
            # FIRST: Check blacklist - immediately reject known bad symbols
            if symbol in self._blacklisted_symbols:
                symbols_blacklisted += 1
                self._symbols_skipped_adv += 1
                continue
            
            # SECOND: Check known liquid whitelist - skip API check entirely
            if symbol in self._known_liquid_symbols:
                # Use known ADV or default high value
                known_adv = self._known_liquid_adv.get(symbol, self._known_liquid_default_adv)
                self._adv_cache[symbol] = (known_adv, now)
                qualified_symbols.append(symbol)
                symbols_known_liquid += 1
                continue
            
            # THIRD: Check cache
            if symbol in self._adv_cache:
                cached_adv, cached_time = self._adv_cache[symbol]
                if (now - cached_time).total_seconds() < self._adv_cache_ttl:
                    # Use cached value
                    if cached_adv >= self._min_adv_investment:  # Investment tier minimum (50K)
                        qualified_symbols.append(symbol)
                    else:
                        self._symbols_skipped_adv += 1
                    continue
            
            # Need to fetch ADV for this symbol
            symbols_needing_adv.append(symbol)
        
        # Batch fetch ADV for unknown symbols using IB data first, then Alpaca
        if symbols_needing_adv:
            try:
                # Get ADV data - try IB historical first, then Alpaca
                adv_data = await self._batch_fetch_adv_smart(symbols_needing_adv)
                
                for symbol in symbols_needing_adv:
                    adv = adv_data.get(symbol, 0)
                    self._adv_cache[symbol] = (adv, now)
                    
                    if adv >= self._min_adv_investment:  # Investment tier minimum (50K)
                        qualified_symbols.append(symbol)
                    else:
                        self._symbols_skipped_adv += 1
                        if adv == 0:
                            logger.debug(f"ADV filter blocked {symbol}: volume data unavailable")
                        
            except Exception as e:
                # On batch error, try to salvage what we can
                logger.warning(f"ADV batch fetch error: {e}")
                # For symbols we couldn't check, mark as needing recheck soon
                for symbol in symbols_needing_adv:
                    if symbol not in self._adv_cache:
                        # Cache with short TTL so we retry soon
                        self._adv_cache[symbol] = (0, now - timedelta(seconds=self._adv_cache_ttl - 120))
                        self._symbols_skipped_adv += 1
        
        if symbols_known_liquid > 0:
            logger.debug(f"Known liquid whitelist: {symbols_known_liquid} symbols auto-qualified")
        if symbols_blacklisted > 0:
            logger.debug(f"Blacklist filter blocked {symbols_blacklisted} known illiquid symbols")
        
        return qualified_symbols
    

    def _classify_symbol_tier(self, symbol: str) -> str:
        """Classify a symbol into an ADV-based scan tier.
        Returns: 'intraday' | 'swing' | 'investment'"""
        adv = 0
        if symbol in self._adv_cache:
            adv, _ = self._adv_cache[symbol]
        elif symbol in self._known_liquid_symbols:
            adv = self._known_liquid_adv.get(symbol, self._known_liquid_default_adv)
        
        if adv >= self._min_adv_intraday:
            return "intraday"
        elif adv >= self._min_adv_general:
            return "swing"
        else:
            return "investment"
    
    def _rebuild_tier_cache(self, symbols: List[str]):
        """Rebuild the tier classification cache for all qualified symbols"""
        self._tier_cache.clear()
        for symbol in symbols:
            self._tier_cache[symbol] = self._classify_symbol_tier(symbol)
        self._tier_cache_time = datetime.now(timezone.utc)
        
        tier_counts = {"intraday": 0, "swing": 0, "investment": 0}
        for tier in self._tier_cache.values():
            tier_counts[tier] += 1
        logger.info(
            f"Tier classification: {tier_counts['intraday']} intraday, "
            f"{tier_counts['swing']} swing, {tier_counts['investment']} investment"
        )
    
    def _is_investment_scan_window(self) -> bool:
        """Check if current time is within an investment tier scan window.
        Investment symbols only scan at 11:00 AM ET and 3:45 PM ET."""
        try:
            from zoneinfo import ZoneInfo
            et_now = datetime.now(ZoneInfo("America/New_York"))
            current_hour = et_now.hour
            current_minute = et_now.minute
            
            for scan_hour, scan_minute in self._investment_scan_times:
                # Allow a 5-minute window around scheduled time
                if current_hour == scan_hour and abs(current_minute - scan_minute) <= 5:
                    # Avoid duplicate scans in the same window
                    window_key = scan_hour * 100 + scan_minute
                    if self._last_investment_scan_hour != window_key:
                        self._last_investment_scan_hour = window_key
                        return True
            return False
        except Exception:
            return False
    
    def _get_symbols_for_cycle(self, all_qualified: List[str]) -> List[str]:
        """Get the symbols to scan THIS cycle based on tiered frequencies.
        
        Tier 1 (Intraday, ADV ≥500K): Every cycle (~15s)
        Tier 2 (Swing, ADV ≥100K): Every 8th cycle (~2 min)
        Tier 3 (Investment, ADV ≥50K): At 11:00 AM and 3:45 PM ET only
        """
        # Rebuild tier cache if stale
        now = datetime.now(timezone.utc)
        if (self._tier_cache_time is None or 
            (now - self._tier_cache_time).total_seconds() > self._tier_cache_ttl):
            self._rebuild_tier_cache(all_qualified)
        
        symbols_this_cycle = []
        
        for symbol in all_qualified:
            tier = self._tier_cache.get(symbol, self._classify_symbol_tier(symbol))
            
            if tier == "intraday":
                # Always scan intraday symbols
                symbols_this_cycle.append(symbol)
            elif tier == "swing":
                # Scan swing symbols every N-th cycle
                if self._scan_count % self._swing_scan_frequency == 0:
                    symbols_this_cycle.append(symbol)
            elif tier == "investment":
                # Only scan at scheduled ET times
                if self._is_investment_scan_window():
                    symbols_this_cycle.append(symbol)
        
        return symbols_this_cycle

    async def _batch_fetch_adv_smart(self, symbols: List[str]) -> Dict[str, int]:
        """
        Fetch ADV using IB-only data sources in priority order:
        1. symbol_adv_cache (pre-calculated from IB daily bars — fastest)
        2. IB historical data (live query from our collected bars)
        3. IB real-time (if pusher connected, use recent volume)
        
        FAIL CLOSED: No Alpaca/IEX fallback. Symbols without IB data get ADV=0.
        
        Returns dict of {symbol: avg_daily_volume}
        """
        adv_data = {}
        symbols_remaining = list(symbols)
        
        # === SOURCE 0: Pre-calculated ADV cache (IB daily bars) ===
        try:
            adv_from_cache = await self._get_adv_from_cache(symbols_remaining)
            for symbol, adv in adv_from_cache.items():
                if adv > 0:
                    adv_data[symbol] = adv
            symbols_remaining = [s for s in symbols_remaining if s not in adv_from_cache or adv_from_cache[s] <= 0]
            if adv_from_cache:
                logger.debug(f"ADV from IB cache: {len(adv_from_cache)} symbols")
        except Exception as e:
            logger.debug(f"ADV cache lookup failed: {e}")
        
        # === SOURCE 1: IB Historical Data (live query from MongoDB) ===
        if symbols_remaining:
            try:
                adv_from_db = await self._get_adv_from_ib_historical(symbols_remaining)
                for symbol, adv in adv_from_db.items():
                    if adv > 0:
                        adv_data[symbol] = adv
                symbols_remaining = [s for s in symbols_remaining if s not in adv_from_db or adv_from_db[s] <= 0]
                if adv_from_db:
                    logger.debug(f"ADV from IB historical DB: {len(adv_from_db)} symbols")
            except Exception as e:
                logger.debug(f"IB historical ADV lookup failed: {e}")
        
        # === SOURCE 2: IB Real-time Pushed Data ===
        if symbols_remaining:
            try:
                adv_from_ib_rt = self._get_adv_from_ib_realtime(symbols_remaining)
                for symbol, adv in adv_from_ib_rt.items():
                    if adv > 0:
                        adv_data[symbol] = adv
                        if symbol in symbols_remaining:
                            symbols_remaining.remove(symbol)
                if adv_from_ib_rt:
                    logger.debug(f"ADV from IB real-time: {len(adv_from_ib_rt)} symbols")
            except Exception as e:
                logger.debug(f"IB real-time ADV lookup failed: {e}")
        
        # FAIL CLOSED: Remaining symbols get ADV=0 (no Alpaca/IEX fallback)
        if symbols_remaining:
            logger.debug(f"ADV fail-closed: {len(symbols_remaining)} symbols with no IB data")
            for symbol in symbols_remaining:
                if symbol not in adv_data:
                    adv_data[symbol] = 0
        
        return adv_data
    
    async def _get_adv_from_cache(self, symbols: List[str]) -> Dict[str, int]:
        """
        Get ADV from the pre-calculated symbol_adv_cache collection.
        This is the fastest lookup — already computed from IB daily bars.
        """
        def _sync_lookup():
            adv_data = {}
            try:
                from database import get_database
                db = get_database()
                if db is None:
                    return adv_data
                cursor = db["symbol_adv_cache"].find(
                    {"symbol": {"$in": symbols}},
                    {"_id": 0, "symbol": 1, "avg_volume": 1}
                )
                for doc in cursor:
                    sym = doc.get("symbol", "")
                    vol = doc.get("avg_volume", 0)
                    if sym and vol > 0:
                        adv_data[sym] = int(vol)
            except Exception as e:
                logger.debug(f"Error reading symbol_adv_cache: {e}")
            return adv_data

        return await asyncio.to_thread(_sync_lookup)
    
    async def _get_adv_from_ib_historical(self, symbols: List[str]) -> Dict[str, int]:
        """
        Get ADV from our collected IB historical data in MongoDB.
        This uses data we've already collected from IB Gateway.
        Runs in a thread to avoid blocking the event loop.
        """
        def _sync_lookup():
            adv_data = {}
            try:
                from database import get_database
                db = get_database()
                if db is None:
                    return adv_data
                bars_col = db.get('ib_historical_data')
                if bars_col is None:
                    return adv_data
                cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
                for symbol in symbols:
                    try:
                        bars = list(bars_col.find(
                            {"symbol": symbol, "bar_size": "1 day", "date": {"$gte": cutoff}},
                            {"volume": 1}
                        ).limit(20))
                        if bars and len(bars) >= 5:
                            volumes = [b.get("volume", 0) for b in bars if b.get("volume", 0) > 0]
                            if volumes:
                                adv_data[symbol] = int(sum(volumes) / len(volumes))
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Error accessing ib_historical_data: {e}")
            return adv_data

        return await asyncio.to_thread(_sync_lookup)
    
    def _get_adv_from_ib_realtime(self, symbols: List[str]) -> Dict[str, int]:
        """
        Estimate ADV from IB real-time pushed data.
        Uses today's volume extrapolated to full day.
        """
        adv_data = {}
        
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            if not is_pusher_connected():
                return adv_data
            
            quotes = get_pushed_quotes()
            now = datetime.now(timezone.utc)
            
            # Calculate how far through the trading day we are (9:30 AM - 4:00 PM ET = 6.5 hours)
            # Rough estimate - adjust based on current time
            market_open_hour = 14  # 9:30 AM ET = 14:30 UTC
            market_close_hour = 21  # 4:00 PM ET = 21:00 UTC
            
            current_hour = now.hour + now.minute / 60.0
            if current_hour < market_open_hour:
                day_progress = 0.1  # Pre-market
            elif current_hour > market_close_hour:
                day_progress = 1.0  # After hours
            else:
                day_progress = (current_hour - market_open_hour) / (market_close_hour - market_open_hour)
                day_progress = max(0.1, min(1.0, day_progress))  # Clamp between 10% and 100%
            
            for symbol in symbols:
                if symbol in quotes:
                    quote = quotes[symbol]
                    today_volume = quote.get('volume', 0)
                    
                    if today_volume > 0 and day_progress > 0:
                        # Extrapolate to full day
                        estimated_adv = int(today_volume / day_progress)
                        # Only use if it seems reasonable (at least 50K)
                        if estimated_adv >= 50000:
                            adv_data[symbol] = estimated_adv
                            
        except Exception as e:
            logger.debug(f"Error getting IB real-time ADV: {e}")
        
        return adv_data
    
    async def _batch_fetch_adv(self, symbols: List[str]) -> Dict[str, int]:
        """
        Fetch average daily volume for multiple symbols efficiently.
        Returns dict of {symbol: avg_daily_volume}
        
        FAIL CLOSED: On any error, returns 0 for the symbol (not minimum threshold).
        This ensures symbols with data issues don't slip through.
        """
        adv_data = {}
        
        try:
            # Process symbols in parallel batches
            chunk_size = 20  # Smaller chunks for rate limit safety
            
            for i in range(0, len(symbols), chunk_size):
                chunk = symbols[i:i + chunk_size]
                
                # Fetch bars for each symbol in parallel
                tasks = []
                for symbol in chunk:
                    tasks.append(self._fetch_single_adv(symbol))
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for symbol, result in zip(chunk, results):
                    if isinstance(result, Exception):
                        # FAIL CLOSED: Default to 0 on error (will be filtered out)
                        adv_data[symbol] = self._adv_error_default
                        logger.debug(f"ADV fetch error for {symbol}, defaulting to 0: {result}")
                    else:
                        adv_data[symbol] = result
                
                # Small delay between chunks
                if i + chunk_size < len(symbols):
                    await asyncio.sleep(0.2)
                        
        except Exception as e:
            logger.warning(f"Batch ADV fetch failed: {e}")
            # FAIL CLOSED: Default all symbols to 0 (will be filtered out)
            for symbol in symbols:
                if symbol not in adv_data:
                    adv_data[symbol] = self._adv_error_default
        
        return adv_data
    
    async def _fetch_single_adv(self, symbol: str) -> int:
        """
        Fetch ADV (Average Daily Volume) for a single symbol from MongoDB.
        Uses ib_historical_data (same source as training) instead of Alpaca.
        """
        try:
            if self.db is not None:
                pipeline = [
                    {"$match": {"symbol": symbol.upper(), "bar_size": "1 day"}},
                    {"$sort": {"date": -1}},
                    {"$limit": 20},
                    {"$project": {"_id": 0, "volume": 1}},
                ]
                bars = list(self.db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
                if bars:
                    volumes = [bar.get("volume", 0) for bar in bars if bar.get("volume", 0) > 0]
                    return int(sum(volumes) / len(volumes)) if volumes else 0
            return 0
        except Exception as e:
            logger.debug(f"ADV fetch failed for {symbol}: {e}")
            return 0
    
    async def _scan_symbol_all_setups(self, symbol: str):
        """
        Scan a single symbol for ALL enabled setups with tape reading.
        
        NOTE: This method is only called for symbols that ALREADY passed ADV pre-filter.
        We still check for higher intraday threshold for scalp setups.
        """
        try:
            # Get technical snapshot
            snapshot = await self.technical_service.get_technical_snapshot(symbol)
            if not snapshot:
                return
            
            # Skip low RVOL stocks (second filter after ADV)
            if snapshot.rvol < self._min_rvol_filter:
                self._symbols_skipped_rvol += 1
                return
            
            # Update caches with fresh data
            now = datetime.now(timezone.utc)
            self._rvol_cache[symbol] = (snapshot.rvol, now)
            # Only update ADV cache from snapshot if we don't already have IB-sourced data
            if symbol not in self._adv_cache:
                self._adv_cache[symbol] = (int(snapshot.avg_volume), now)
            
            # Get tape reading for this symbol
            tape = await self._get_tape_reading(symbol, snapshot)
            
            alerts = []
            current_window = self._get_current_time_window()
            
            # Check each enabled setup
            for setup_type in self._enabled_setups:
                # Check time and regime validity
                if not self._is_setup_valid_now(setup_type):
                    continue
                
                # Intraday/scalp setups require HIGHER volume threshold
                # (General ADV threshold already passed in pre-filter)
                if setup_type in self._intraday_setups:
                    if snapshot.avg_volume < self._min_adv_intraday:
                        continue  # Skip intraday setup - needs more volume
                
                # Call appropriate scanner method
                alert = await self._check_setup(setup_type, symbol, snapshot, tape)
                if alert:
                    # Add strategy stats to alert
                    base_setup = setup_type.split("_long")[0].split("_short")[0]
                    if base_setup in self._strategy_stats:
                        stats = self._strategy_stats[base_setup]
                        alert.strategy_win_rate = stats.win_rate
                        alert.strategy_profit_factor = stats.profit_factor
                        # Add EV data (SMB-style)
                        alert.strategy_ev_r = stats.expected_value_r
                        # Calculate R-multiple for this alert
                        alert.calculate_r_multiple()
                        # Grade the trade based on EV and context
                        alert.grade_trade(strategy_ev=stats.expected_value_r, market_context_score=0.5)
                    
                    # Add tape reading to alert
                    alert.tape_score = tape.tape_score
                    alert.tape_confirmation = (tape.confirmation_for_long if alert.direction == "long" else tape.confirmation_for_short)
                    alert.tape_signals = [
                        tape.spread_signal.value,
                        tape.imbalance_signal.value,
                        tape.momentum_signal.value
                    ]
                    
                    # Check auto-execute eligibility
                    alert.auto_execute_eligible = (
                        self._auto_execute_enabled and
                        alert.priority.value in [AlertPriority.CRITICAL.value, AlertPriority.HIGH.value] and
                        alert.tape_confirmation and
                        alert.strategy_win_rate >= self._auto_execute_min_win_rate
                    )
                    
                    alerts.append(alert)
            
            # Process all alerts for this symbol - AI ENRICHMENT first, then TQS SCORING
            # GAP 2 FIX: AI enrichment runs first so TQS can incorporate AI model alignment
            for alert in alerts:
                # Add AI predictions to the alert (must run before TQS)
                await self._enrich_alert_with_ai(alert)
                
                # Calculate TQS for this alert (now has AI data available)
                await self._enrich_alert_with_tqs(alert)
                
                await self._process_new_alert(alert)
                
                # Auto-execute if eligible
                if alert.auto_execute_eligible:
                    await self._auto_execute_alert(alert)
                
        except Exception as e:
            logger.warning(f"Error scanning {symbol}: {e}")
    
    async def _check_setup(self, setup_type: str, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Route to specific setup checker"""
        checkers = {
            # Opening strategies
            "first_vwap_pullback": self._check_first_vwap_pullback,
            "opening_drive": self._check_opening_drive,
            
            # Morning momentum
            "orb": self._check_orb,
            "hitchhiker": self._check_hitchhiker,
            "gap_give_go": self._check_gap_give_go,
            
            # Core session
            "spencer_scalp": self._check_spencer_scalp,
            "second_chance": self._check_second_chance,
            "backside": self._check_backside,
            "off_sides": self._check_off_sides,
            "fashionably_late": self._check_fashionably_late,
            
            # Mean reversion
            "rubber_band": self._check_rubber_band,
            "vwap_bounce": self._check_vwap_bounce,
            "vwap_fade": self._check_vwap_fade,
            "tidal_wave": self._check_tidal_wave,
            
            # Consolidation
            "big_dog": self._check_big_dog,
            "puppy_dog": self._check_puppy_dog,
            "9_ema_scalp": self._check_9_ema_scalp,
            "abc_scalp": self._check_abc_scalp,
            
            # Afternoon
            "hod_breakout": self._check_hod_breakout,
            "approaching_hod": self._check_approaching_hod,
            
            # Special
            "volume_capitulation": self._check_volume_capitulation,
            "range_break": self._check_range_break,
            "breakout": self._check_breakout,
            
            # NEW setups
            "squeeze": self._check_squeeze,
            "mean_reversion": self._check_mean_reversion,
            "relative_strength": self._check_relative_strength,
            "gap_fade": self._check_gap_fade,
            "chart_pattern": self._check_chart_pattern,
        }
        
        checker = checkers.get(setup_type)
        if checker:
            return await checker(symbol, snapshot, tape)
        return None
    
    # ==================== SETUP CHECKERS (with tape reading) ====================
    
    async def _check_rubber_band(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Rubber Band Scalp - Mean reversion from EMA9"""
        # Long setup - extended below EMA9
        if snapshot.dist_from_ema9 < -2.5 and snapshot.rsi_14 < 38 and snapshot.rvol >= 1.5:
            extension = abs(snapshot.dist_from_ema9)
            
            # Higher priority with tape confirmation
            if tape.confirmation_for_long and extension > 3.5:
                priority = AlertPriority.CRITICAL
            elif extension > 3.5:
                priority = AlertPriority.HIGH
            else:
                priority = AlertPriority.MEDIUM
            
            # Calculate proper levels using S/R and ATR
            stop_loss = round(min(snapshot.low_of_day - 0.02, snapshot.support - (snapshot.atr * 0.25)), 2)
            target_1 = round(snapshot.ema_9, 2)  # Primary target: EMA9
            target_2 = round(snapshot.vwap, 2) if snapshot.vwap > snapshot.ema_9 else round(snapshot.ema_9 + snapshot.atr, 2)
            
            # Calculate R-multiple
            risk = snapshot.current_price - stop_loss
            reward = target_1 - snapshot.current_price
            r_multiple = round(reward / risk, 2) if risk > 0 else 2.0
            
            # Get historical EV
            ev_info = ""
            if "rubber_band" in self._strategy_stats:
                stats = self._strategy_stats["rubber_band"]
                if stats.win_rate > 0:
                    ev_info = f"Historical: {stats.win_rate:.0%} win, EV {stats.expected_value_r:.2f}R"
            
            return LiveAlert(
                id=f"rb_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="rubber_band_long",
                strategy_name="Rubber Band Long (INT-25)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.ema_9,
                stop_loss=stop_loss,
                target=target_1,
                risk_reward=r_multiple,
                trigger_probability=0.65,
                win_probability=0.62,
                minutes_to_trigger=10,
                headline=f"🎯 {symbol} Rubber Band LONG - {extension:.1f}% extended {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Extended {extension:.1f}% below 9-EMA ${snapshot.ema_9:.2f}",
                    f"RSI oversold at {snapshot.rsi_14:.0f}",
                    f"R:R = {r_multiple:.1f}:1 (Stop: ${stop_loss:.2f} below support, Target: ${target_1:.2f})",
                    f"Support at ${snapshot.support:.2f}, Resistance at ${snapshot.resistance:.2f}",
                    f"RVOL: {snapshot.rvol:.1f}x | Tape: {tape.overall_signal.value}",
                    ev_info if ev_info else f"Mean reversion to EMA9",
                    f"Entry: Double bar break above prior highs"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        
        # Short setup - extended above EMA9
        if snapshot.dist_from_ema9 > 3.0 and snapshot.rsi_14 > 65 and snapshot.rvol >= 1.5:
            extension = snapshot.dist_from_ema9
            
            if tape.confirmation_for_short and extension > 4.0:
                priority = AlertPriority.CRITICAL
            elif extension > 4.0:
                priority = AlertPriority.HIGH
            else:
                priority = AlertPriority.MEDIUM
            
            # Calculate proper levels using S/R and ATR
            stop_loss = round(max(snapshot.high_of_day + 0.02, snapshot.resistance + (snapshot.atr * 0.25)), 2)
            target_1 = round(snapshot.ema_9, 2)  # Primary target: EMA9
            target_2 = round(snapshot.vwap, 2) if snapshot.vwap < snapshot.ema_9 else round(snapshot.ema_9 - snapshot.atr, 2)
            
            # Calculate R-multiple
            risk = stop_loss - snapshot.current_price
            reward = snapshot.current_price - target_1
            r_multiple = round(reward / risk, 2) if risk > 0 else 2.0
            
            # Get historical EV
            ev_info = ""
            if "rubber_band" in self._strategy_stats:
                stats = self._strategy_stats["rubber_band"]
                if stats.win_rate > 0:
                    ev_info = f"Historical: {stats.win_rate:.0%} win, EV {stats.expected_value_r:.2f}R"
            
            return LiveAlert(
                id=f"rb_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="rubber_band_short",
                strategy_name="Rubber Band Short (INT-25)",
                direction="short",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.ema_9,
                stop_loss=stop_loss,
                target=target_1,
                risk_reward=r_multiple,
                trigger_probability=0.65,
                win_probability=0.58,
                minutes_to_trigger=10,
                headline=f"🎯 {symbol} Rubber Band SHORT - {extension:.1f}% extended {'✓ TAPE' if tape.confirmation_for_short else ''}",
                reasoning=[
                    f"Extended {extension:.1f}% above 9-EMA ${snapshot.ema_9:.2f}",
                    f"RSI overbought at {snapshot.rsi_14:.0f}",
                    f"R:R = {r_multiple:.1f}:1 (Stop: ${stop_loss:.2f} above resistance, Target: ${target_1:.2f})",
                    f"Support at ${snapshot.support:.2f}, Resistance at ${snapshot.resistance:.2f}",
                    f"RVOL: {snapshot.rvol:.1f}x | Tape: {tape.overall_signal.value}",
                    ev_info if ev_info else f"Mean reversion to EMA9",
                    f"Entry: Double bar break below prior lows"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        
        return None
    
    async def _check_vwap_bounce(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """VWAP Bounce - Pullback to VWAP in uptrend"""
        if (-0.8 < snapshot.dist_from_vwap < 0.3 and 
            snapshot.trend == "uptrend" and 
            snapshot.above_ema9 and
            snapshot.rvol >= 1.5):
            
            dist = abs(snapshot.dist_from_vwap)
            priority = AlertPriority.HIGH if dist < 0.3 and tape.confirmation_for_long else AlertPriority.MEDIUM
            
            return LiveAlert(
                id=f"vwap_bounce_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="vwap_bounce",
                strategy_name="VWAP Bounce (INT-06)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(snapshot.vwap - (snapshot.atr * 0.5), 2),
                target=round(snapshot.vwap + (snapshot.atr * 1.5), 2),
                risk_reward=3.0,
                trigger_probability=0.60,
                win_probability=0.60,
                minutes_to_trigger=10,
                headline=f"📍 {symbol} VWAP Bounce - ${snapshot.vwap:.2f} {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price {snapshot.dist_from_vwap:+.1f}% from VWAP",
                    f"Uptrend intact - above 9-EMA and 20-EMA",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value}",
                    f"Entry: Rejection wick + bullish candle at VWAP"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_vwap_fade(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """VWAP Reversion - Fade extended moves back to VWAP"""
        # Long fade - extended below VWAP
        if snapshot.dist_from_vwap < -2.5 and snapshot.rsi_14 < 35:
            return LiveAlert(
                id=f"vwap_fade_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="vwap_fade_long",
                strategy_name="VWAP Reversion Long (INT-07)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.low_of_day - 0.02, 2),
                target=round(snapshot.vwap, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"↩️ {symbol} VWAP Fade LONG - {abs(snapshot.dist_from_vwap):.1f}% below",
                reasoning=[
                    f"Extended {abs(snapshot.dist_from_vwap):.1f}% below VWAP",
                    f"RSI oversold at {snapshot.rsi_14:.0f}",
                    f"Tape: {tape.overall_signal.value}",
                    f"Target: Mean reversion to VWAP ${snapshot.vwap:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        
        # Short fade - extended above VWAP
        if snapshot.dist_from_vwap > 2.5 and snapshot.rsi_14 > 70:
            return LiveAlert(
                id=f"vwap_fade_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="vwap_fade_short",
                strategy_name="VWAP Reversion Short (INT-07)",
                direction="short",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.high_of_day + 0.02, 2),
                target=round(snapshot.vwap, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"↩️ {symbol} VWAP Fade SHORT - {snapshot.dist_from_vwap:.1f}% above",
                reasoning=[
                    f"Extended {snapshot.dist_from_vwap:.1f}% above VWAP",
                    f"RSI overbought at {snapshot.rsi_14:.0f}",
                    f"Tape: {tape.overall_signal.value}",
                    f"Target: Mean reversion to VWAP ${snapshot.vwap:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_breakout(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Breakout - Price breaking or about to break resistance with volume"""
        dist_to_resistance = ((snapshot.resistance - snapshot.current_price) / snapshot.current_price) * 100
        
        # CONFIRMED BREAKOUT: Price above resistance (dist_to_resistance < 0)
        if dist_to_resistance < 0 and dist_to_resistance > -1.5 and snapshot.rvol >= 1.8:
            breakout_pct = abs(dist_to_resistance)
            priority = AlertPriority.CRITICAL if tape.confirmation_for_long else AlertPriority.HIGH
            
            # Calculate R-multiple using S/R levels
            stop_loss = round(snapshot.resistance - snapshot.atr, 2)
            target = round(snapshot.current_price + (snapshot.atr * 2), 2)
            risk = snapshot.current_price - stop_loss
            reward = target - snapshot.current_price
            r_multiple = round(reward / risk, 2) if risk > 0 else 2.0
            
            # Get historical EV for breakout setups
            ev_info = ""
            if "breakout" in self._strategy_stats:
                stats = self._strategy_stats["breakout"]
                if stats.win_rate > 0:
                    ev_info = f"Historical: {stats.win_rate:.0%} win rate, {stats.expected_value_r:.2f}R EV"
            
            return LiveAlert(
                id=f"breakout_confirmed_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="breakout_confirmed",
                strategy_name="Breakout CONFIRMED (INT-02)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.resistance,
                stop_loss=stop_loss,
                target=target,
                risk_reward=r_multiple,
                trigger_probability=0.70,
                win_probability=0.58,
                minutes_to_trigger=0,
                headline=f"🚀 {symbol} BREAKOUT CONFIRMED - Broke ${snapshot.resistance:.2f} by {breakout_pct:.2f}% {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price ABOVE resistance by {breakout_pct:.2f}%",
                    f"Resistance was ${snapshot.resistance:.2f}, now ${snapshot.current_price:.2f}",
                    f"Strong volume: {snapshot.rvol:.1f}x RVOL",
                    f"R:R = {r_multiple:.1f}:1 (Stop: ${stop_loss:.2f}, Target: ${target:.2f})",
                    f"Tape: {tape.overall_signal.value}",
                    ev_info if ev_info else f"Support at ${snapshot.support:.2f}",
                    f"⚠️ Entry now or on pullback to ${snapshot.resistance:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        
        # APPROACHING BREAKOUT: Price below but near resistance
        if 0 < dist_to_resistance < 0.8 and snapshot.rvol >= 2.0:
            if dist_to_resistance < 0.3 and tape.confirmation_for_long:
                priority = AlertPriority.HIGH
                minutes = 2
            elif dist_to_resistance < 0.5:
                priority = AlertPriority.MEDIUM
                minutes = 5
            else:
                priority = AlertPriority.MEDIUM
                minutes = 10
            
            return LiveAlert(
                id=f"breakout_approaching_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="approaching_breakout",
                strategy_name="Approaching Breakout (INT-02)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.resistance,
                stop_loss=round(snapshot.resistance - snapshot.atr, 2),
                target=round(snapshot.resistance + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.52,
                minutes_to_trigger=minutes,
                headline=f"👀 {symbol} Approaching Breakout - {dist_to_resistance:.2f}% to ${snapshot.resistance:.2f} {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price {dist_to_resistance:.2f}% below resistance ${snapshot.resistance:.2f}",
                    f"Strong volume building: {snapshot.rvol:.1f}x RVOL",
                    f"Tape: {tape.overall_signal.value}",
                    f"⚠️ Wait for confirmed break above ${snapshot.resistance:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        return None
    
    async def _check_spencer_scalp(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Spencer Scalp - Tight consolidation near HOD"""
        dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
        
        if dist_from_hod < 1.0 and snapshot.daily_range_pct < 3.0 and snapshot.rvol >= 1.5:
            priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
            
            return LiveAlert(
                id=f"spencer_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="spencer_scalp",
                strategy_name="Spencer Scalp (INT-22)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.high_of_day,
                stop_loss=round(snapshot.current_price - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day + (snapshot.atr * 1.5), 2),
                risk_reward=3.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"📊 {symbol} Spencer Scalp - Near HOD {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price {dist_from_hod:.1f}% from HOD ${snapshot.high_of_day:.2f}",
                    f"Tight consolidation (range: {snapshot.daily_range_pct:.1f}%)",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value}",
                    f"Entry: Break of consolidation high"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        return None
    
    async def _check_hitchhiker(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """HitchHiker - Strong drive off open, consolidation, continuation"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM]:
            return None
        
        if (snapshot.gap_pct > 2.0 and 
            snapshot.holding_gap and 
            snapshot.above_vwap and
            snapshot.rvol >= 2.0):
            
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 1.5:
                priority = AlertPriority.CRITICAL if tape.confirmation_for_long else AlertPriority.HIGH
                
                return LiveAlert(
                    id=f"hitchhiker_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="hitchhiker",
                    strategy_name="HitchHiker (INT-29)",
                    direction="long",
                    priority=priority,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.vwap - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.atr * 2), 2),
                    risk_reward=2.5,
                    trigger_probability=0.60,
                    win_probability=0.58,
                    minutes_to_trigger=10,
                    headline=f"🏃 {symbol} HitchHiker - Gap {snapshot.gap_pct:.1f}% {'✓ TAPE' if tape.confirmation_for_long else ''}",
                    reasoning=[
                        f"Gap up {snapshot.gap_pct:.1f}% holding above VWAP",
                        f"Consolidating {dist_from_hod:.1f}% from HOD",
                        f"RVOL: {snapshot.rvol:.1f}x",
                        f"Tape: {tape.overall_signal.value}",
                        f"Entry: Aggressive on break of consolidation"
                    ],
                    time_window=current_window.value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
                )
        return None
    
    async def _check_orb(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Opening Range Breakout"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION]:
            return None
        
        if snapshot.rvol >= 2.0:
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            # CONFIRMED ORB: Price broke above opening range high
            if dist_from_hod < -0.1 and dist_from_hod > -1.5 and snapshot.above_vwap:
                priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
                breakout_pct = abs(dist_from_hod)
                
                return LiveAlert(
                    id=f"orb_long_confirmed_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="orb_long_confirmed",
                    strategy_name="ORB CONFIRMED (INT-03)",
                    direction="long",
                    priority=priority,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.current_price + (snapshot.high_of_day - snapshot.low_of_day) * 2, 2),
                    risk_reward=2.0,
                    trigger_probability=0.65,
                    win_probability=0.58,
                    minutes_to_trigger=0,
                    headline=f"🚀 {symbol} ORB BREAKOUT CONFIRMED - Broke ${snapshot.high_of_day:.2f} {'✓ TAPE' if tape.confirmation_for_long else ''}",
                    reasoning=[
                        f"Price ABOVE opening range high by {breakout_pct:.2f}%",
                        f"ORH was ${snapshot.high_of_day:.2f}, now ${snapshot.current_price:.2f}",
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"RVOL: {snapshot.rvol:.1f}x",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=current_window.value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
            
            # APPROACHING ORB: Price near opening range high
            if 0 < dist_from_hod < 0.5 and snapshot.above_vwap:
                priority = AlertPriority.MEDIUM
                
                return LiveAlert(
                    id=f"orb_long_approaching_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="approaching_orb",
                    strategy_name="Approaching ORB (INT-03)",
                    direction="long",
                    priority=priority,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.high_of_day - snapshot.low_of_day) * 2, 2),
                    risk_reward=2.0,
                    trigger_probability=0.50,
                    win_probability=0.52,
                    minutes_to_trigger=10,
                    headline=f"👀 {symbol} Approaching ORB - {dist_from_hod:.2f}% to ${snapshot.high_of_day:.2f} {'✓ TAPE' if tape.confirmation_for_long else ''}",
                    reasoning=[
                        f"Price {dist_from_hod:.2f}% below ORH ${snapshot.high_of_day:.2f}",
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"RVOL: {snapshot.rvol:.1f}x",
                        f"⚠️ Wait for confirmed break above ${snapshot.high_of_day:.2f}"
                    ],
                    time_window=current_window.value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_gap_give_go(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Gap Give and Go - Gap up, pullback, continuation"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM]:
            return None
        
        if (snapshot.gap_pct > 3.0 and 
            snapshot.holding_gap and
            snapshot.above_vwap and
            0 < snapshot.dist_from_vwap < 1.5 and
            snapshot.rvol >= 2.0):
            
            priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
            
            return LiveAlert(
                id=f"gap_give_go_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="gap_give_go",
                strategy_name="Gap Give and Go (INT-34)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.vwap - 0.02, 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.0,
                trigger_probability=0.60,
                win_probability=0.55,
                minutes_to_trigger=10,
                headline=f"🎁 {symbol} Gap Give and Go - {snapshot.gap_pct:.1f}% {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Gap up {snapshot.gap_pct:.1f}%",
                    f"Pulled back but holding VWAP",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
            )
        return None
    
    async def _check_second_chance(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Second Chance - Retest of broken level"""
        dist_from_vwap = abs(snapshot.dist_from_vwap)
        
        if (dist_from_vwap < 0.5 and 
            snapshot.above_vwap and 
            snapshot.trend == "uptrend" and
            snapshot.rvol >= 1.2):
            
            priority = AlertPriority.MEDIUM
            
            return LiveAlert(
                id=f"second_chance_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="second_chance",
                strategy_name="Second Chance Scalp (INT-24)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(snapshot.vwap - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"🔄 {symbol} Second Chance - Retesting VWAP",
                reasoning=[
                    f"Retesting VWAP ${snapshot.vwap:.2f}",
                    f"Uptrend intact",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_backside(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Back$ide - Recovery from LOD"""
        if (snapshot.trend == "uptrend" and
            snapshot.above_ema9 and
            not snapshot.above_vwap and
            snapshot.dist_from_vwap > -2.0 and
            snapshot.rvol >= 1.2):
            
            return LiveAlert(
                id=f"backside_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="backside",
                strategy_name="Back$ide Scalp (INT-32)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.ema_9 - 0.02, 2),
                target=round(snapshot.vwap, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"↗️ {symbol} Back$ide - Recovering to VWAP",
                reasoning=[
                    f"Higher highs/lows above 9-EMA",
                    f"Tape: {tape.overall_signal.value}",
                    f"Target: VWAP ${snapshot.vwap:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_off_sides(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Off Sides - Range break in fade market"""
        if self._market_regime not in [MarketRegime.RANGE_BOUND, MarketRegime.FADE]:
            return None
        
        if abs(snapshot.dist_from_vwap) < 1.0 and snapshot.daily_range_pct > 1.5:
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 1.0:
                return LiveAlert(
                    id=f"offsides_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="off_sides_short",
                    strategy_name="Off Sides Scalp (INT-33)",
                    direction="short",
                    priority=AlertPriority.MEDIUM,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.low_of_day,
                    stop_loss=round(snapshot.high_of_day + 0.01, 2),
                    target=round(snapshot.low_of_day - (snapshot.high_of_day - snapshot.low_of_day), 2),
                    risk_reward=1.5,
                    trigger_probability=0.50,
                    win_probability=0.52,
                    minutes_to_trigger=20,
                    headline=f"⚔️ {symbol} Off Sides SHORT - Range break",
                    reasoning=[
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"Regime: {self._market_regime.value}",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_fashionably_late(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Fashionably Late - 9-EMA crosses VWAP"""
        if (snapshot.above_ema9 and 
            snapshot.ema_9 > snapshot.vwap and
            (snapshot.ema_9 - snapshot.vwap) / snapshot.vwap * 100 < 0.5 and
            snapshot.trend == "uptrend" and
            snapshot.rvol >= 1.2):
            
            return LiveAlert(
                id=f"fashionably_late_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="fashionably_late",
                strategy_name="Fashionably Late (INT-26)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.vwap - (snapshot.atr * 0.33), 2),
                target=round(snapshot.vwap + (snapshot.vwap - snapshot.low_of_day), 2),
                risk_reward=3.0,
                trigger_probability=0.55,
                win_probability=0.60,
                minutes_to_trigger=15,
                headline=f"⏰ {symbol} Fashionably Late - 9-EMA crossing VWAP",
                reasoning=[
                    f"9-EMA just crossed VWAP",
                    f"Momentum building",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_tidal_wave(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Tidal Wave - Weaker bounces into support"""
        if (snapshot.trend == "downtrend" and
            not snapshot.above_vwap and
            snapshot.dist_from_vwap < -1.5 and
            snapshot.rsi_14 > 40):
            
            dist_to_support = ((snapshot.current_price - snapshot.support) / snapshot.current_price) * 100
            
            if dist_to_support < 2.0:
                return LiveAlert(
                    id=f"tidal_wave_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="tidal_wave",
                    strategy_name="Tidal Wave (INT-23)",
                    direction="short",
                    priority=AlertPriority.MEDIUM,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.support,
                    stop_loss=round(snapshot.current_price + (snapshot.atr * 0.5), 2),
                    target=round(snapshot.support - (snapshot.atr * 2), 2),
                    risk_reward=2.0,
                    trigger_probability=0.50,
                    win_probability=0.55,
                    minutes_to_trigger=20,
                    headline=f"🌊 {symbol} Tidal Wave - Weaker bounces",
                    reasoning=[
                        f"Extended below VWAP",
                        f"Approaching support ${snapshot.support:.2f}",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_hod_breakout(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """HOD Breakout - Afternoon break of high of day (confirmed breakout)"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.AFTERNOON, TimeWindow.CLOSE]:
            return None
        
        # Calculate if price is ABOVE HOD (actual breakout)
        # dist_from_hod > 0 means price is BELOW HOD
        # dist_from_hod < 0 means price is ABOVE HOD (breakout!)
        dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
        
        # Only alert on CONFIRMED breakout (price > HOD) with strong conditions
        # Price must be 0.1% to 1.5% above HOD (confirmed but not extended)
        if (dist_from_hod < -0.1 and dist_from_hod > -1.5 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.5):
            
            priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
            breakout_pct = abs(dist_from_hod)
            
            return LiveAlert(
                id=f"hod_breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="hod_breakout",
                strategy_name="HOD Breakout (INT-46)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.high_of_day,
                stop_loss=round(snapshot.ema_9, 2),
                target=round(snapshot.current_price + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.60,
                win_probability=0.58,
                minutes_to_trigger=0,
                headline=f"🚀 {symbol} HOD BREAKOUT CONFIRMED {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price broke HOD by {breakout_pct:.2f}%",
                    f"HOD was ${snapshot.high_of_day:.2f}, now ${snapshot.current_price:.2f}",
                    f"Afternoon session - momentum often continues",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        return None
    

    async def _check_approaching_hod(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Approaching HOD - Price near high of day, setting up for potential breakout"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.AFTERNOON, TimeWindow.CLOSE]:
            return None
        
        # dist_from_hod > 0 means price is BELOW HOD
        dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
        
        # Alert when within 0.3% to 0.8% of HOD (approaching but not there yet)
        if (dist_from_hod > 0.1 and dist_from_hod < 0.8 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.2):
            
            priority = AlertPriority.MEDIUM
            
            return LiveAlert(
                id=f"approaching_hod_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="approaching_hod",
                strategy_name="Approaching HOD",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.high_of_day,
                stop_loss=round(snapshot.ema_9, 2),
                target=round(snapshot.high_of_day + (snapshot.atr * 1.5), 2),
                risk_reward=2.0,
                trigger_probability=0.45,
                win_probability=0.50,
                minutes_to_trigger=10,
                headline=f"👀 {symbol} Approaching HOD - Watch for breakout",
                reasoning=[
                    f"Price {dist_from_hod:.2f}% below HOD ${snapshot.high_of_day:.2f}",
                    f"Current: ${snapshot.current_price:.2f}",
                    f"Above VWAP and EMA9",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"⚠️ Wait for confirmed break above ${snapshot.high_of_day:.2f}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
            )
        return None

    async def _check_volume_capitulation(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Volume Capitulation - Exhaustion on extreme volume"""
        if snapshot.rvol >= 5.0:
            if snapshot.dist_from_vwap > 5.0 or snapshot.dist_from_vwap < -5.0:
                direction = "short" if snapshot.dist_from_vwap > 0 else "long"
                
                return LiveAlert(
                    id=f"volume_cap_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="volume_capitulation",
                    strategy_name="Volume Capitulation (INT-45)",
                    direction=direction,
                    priority=AlertPriority.HIGH,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.current_price,
                    stop_loss=round(snapshot.high_of_day + 0.02, 2) if direction == "short" else round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.vwap, 2),
                    risk_reward=2.0,
                    trigger_probability=0.50,
                    win_probability=0.55,
                    minutes_to_trigger=10,
                    headline=f"💥 {symbol} Volume Capitulation - {snapshot.rvol:.1f}x RVOL",
                    reasoning=[
                        f"Extreme volume: {snapshot.rvol:.1f}x",
                        f"Extended {abs(snapshot.dist_from_vwap):.1f}% from VWAP",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_range_break(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Range Break - Break of established range"""
        daily_range = snapshot.daily_range_pct
        
        if daily_range < 2.0 and daily_range > 0.5 and snapshot.rvol >= 1.5:
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            # CONFIRMED: Price broke above range
            if dist_from_hod < -0.1 and dist_from_hod > -1.0:
                breakout_pct = abs(dist_from_hod)
                return LiveAlert(
                    id=f"range_break_confirmed_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="range_break_confirmed",
                    strategy_name="Range Break CONFIRMED (INT-21)",
                    direction="long",
                    priority=AlertPriority.HIGH,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.current_price + (snapshot.high_of_day - snapshot.low_of_day), 2),
                    risk_reward=1.5,
                    trigger_probability=0.60,
                    win_probability=0.55,
                    minutes_to_trigger=0,
                    headline=f"🚀 {symbol} Range Break CONFIRMED - Broke ${snapshot.high_of_day:.2f} by {breakout_pct:.2f}%",
                    reasoning=[
                        f"Price ABOVE range high by {breakout_pct:.2f}%",
                        f"Range was ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                )
            
            # APPROACHING: Near range high
            if 0 < dist_from_hod < 0.5:
                return LiveAlert(
                    id=f"range_break_approaching_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="approaching_range_break",
                    strategy_name="Approaching Range Break (INT-21)",
                    direction="long",
                    priority=AlertPriority.MEDIUM,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.high_of_day - snapshot.low_of_day), 2),
                    risk_reward=1.5,
                    trigger_probability=0.45,
                    win_probability=0.48,
                    minutes_to_trigger=20,
                    headline=f"👀 {symbol} Approaching Range Break - {dist_from_hod:.2f}% to ${snapshot.high_of_day:.2f}",
                    reasoning=[
                        f"Price {dist_from_hod:.2f}% below range high",
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"⚠️ Wait for break above ${snapshot.high_of_day:.2f}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                )
        return None
    
    # ==================== NEW SETUP CHECKERS ====================
    
    async def _check_squeeze(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Squeeze Detection: Bollinger Bands inside Keltner Channels = volatility compression"""
        if not hasattr(snapshot, 'squeeze_on') or not snapshot.squeeze_on:
            return None
        if snapshot.rvol < 1.0:
            return None
        
        direction = "long" if snapshot.squeeze_fire > 0 else "short"
        
        # Tighter BB width = more explosive
        if snapshot.bb_width < 3.0:
            priority = AlertPriority.CRITICAL
        elif snapshot.bb_width < 5.0:
            priority = AlertPriority.HIGH
        else:
            priority = AlertPriority.MEDIUM
        
        # Tape confirmation upgrades priority
        if direction == "long" and tape.confirmation_for_long and priority != AlertPriority.CRITICAL:
            priority = AlertPriority.HIGH
        elif direction == "short" and tape.confirmation_for_short and priority != AlertPriority.CRITICAL:
            priority = AlertPriority.HIGH
        
        stop = snapshot.bb_lower if direction == "long" else snapshot.bb_upper
        target = snapshot.current_price + (snapshot.atr * 2.5) if direction == "long" else snapshot.current_price - (snapshot.atr * 2.5)
        risk = abs(snapshot.current_price - stop)
        rr = abs(target - snapshot.current_price) / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"squeeze_{symbol}_{direction}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="squeeze",
            strategy_name=f"Squeeze Fire {direction.upper()}",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.bb_upper if direction == "long" else snapshot.bb_lower,
            stop_loss=round(stop, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.68,
            win_probability=0.62,
            minutes_to_trigger=10,
            headline=f"SQUEEZE {symbol} {direction.upper()} - BB Width {snapshot.bb_width:.1f}% {'+ TAPE' if (tape.confirmation_for_long if direction == 'long' else tape.confirmation_for_short) else ''}",
            reasoning=[
                f"Bollinger Bands INSIDE Keltner Channels = volatility squeeze",
                f"BB Width: {snapshot.bb_width:.1f}% (tight = explosive breakout imminent)",
                f"Momentum: {snapshot.squeeze_fire:+.2f} ({'bullish' if direction == 'long' else 'bearish'})",
                f"RVOL: {snapshot.rvol:.1f}x | RSI: {snapshot.rsi_14:.0f}",
                f"Tape: {tape.overall_signal.value} (score: {tape.tape_score:.2f})"
            ],
            time_window=self._get_current_time_window().value,
            market_regime=self._market_regime.value,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        )
    
    async def _check_mean_reversion(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Mean Reversion: RSI extreme + near support/resistance + volume"""
        # Long: oversold + near support
        is_oversold = snapshot.rsi_14 < 30 and snapshot.dist_from_ema20 < -3.0
        near_support = snapshot.current_price <= snapshot.support * 1.02
        
        # Short: overbought + near resistance
        is_overbought = snapshot.rsi_14 > 70 and snapshot.dist_from_ema20 > 3.0
        near_resistance = snapshot.current_price >= snapshot.resistance * 0.98
        
        if is_oversold and near_support:
            direction = "long"
            stop = snapshot.support - (snapshot.atr * 0.5)
            target = snapshot.ema_20
            priority = AlertPriority.HIGH if snapshot.rsi_14 < 25 else AlertPriority.MEDIUM
            if tape.confirmation_for_long:
                priority = AlertPriority.CRITICAL if priority == AlertPriority.HIGH else AlertPriority.HIGH
            
            risk = abs(snapshot.current_price - stop)
            rr = abs(target - snapshot.current_price) / risk if risk > 0 else 1
            
            return LiveAlert(
                id=f"mr_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="mean_reversion_long",
                strategy_name="Mean Reversion Long",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.support,
                stop_loss=round(stop, 2),
                target=round(target, 2),
                risk_reward=round(rr, 2),
                trigger_probability=0.60,
                win_probability=0.58,
                minutes_to_trigger=15,
                headline=f"MEAN REVERSION {symbol} LONG - RSI {snapshot.rsi_14:.0f} at support ${snapshot.support:.2f}",
                reasoning=[
                    f"RSI oversold at {snapshot.rsi_14:.0f} (extreme < 30)",
                    f"At support ${snapshot.support:.2f}",
                    f"Extended {abs(snapshot.dist_from_ema20):.1f}% below 20-EMA",
                    f"Target: Snap back to 20-EMA ${snapshot.ema_20:.2f}",
                    f"Tape: {tape.overall_signal.value} | RVOL: {snapshot.rvol:.1f}x"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        
        if is_overbought and near_resistance:
            direction = "short"
            stop = snapshot.resistance + (snapshot.atr * 0.5)
            target = snapshot.ema_20
            priority = AlertPriority.HIGH if snapshot.rsi_14 > 75 else AlertPriority.MEDIUM
            if tape.confirmation_for_short:
                priority = AlertPriority.CRITICAL if priority == AlertPriority.HIGH else AlertPriority.HIGH
            
            risk = abs(snapshot.current_price - stop)
            rr = abs(target - snapshot.current_price) / risk if risk > 0 else 1
            
            return LiveAlert(
                id=f"mr_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="mean_reversion_short",
                strategy_name="Mean Reversion Short",
                direction="short",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.resistance,
                stop_loss=round(stop, 2),
                target=round(target, 2),
                risk_reward=round(rr, 2),
                trigger_probability=0.60,
                win_probability=0.58,
                minutes_to_trigger=15,
                headline=f"MEAN REVERSION {symbol} SHORT - RSI {snapshot.rsi_14:.0f} at resistance ${snapshot.resistance:.2f}",
                reasoning=[
                    f"RSI overbought at {snapshot.rsi_14:.0f} (extreme > 70)",
                    f"At resistance ${snapshot.resistance:.2f}",
                    f"Extended {snapshot.dist_from_ema20:.1f}% above 20-EMA",
                    f"Target: Pullback to 20-EMA ${snapshot.ema_20:.2f}",
                    f"Tape: {tape.overall_signal.value} | RVOL: {snapshot.rvol:.1f}x"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        
        return None
    
    async def _check_relative_strength(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Relative Strength/Weakness vs SPY: find leaders and laggards"""
        if not hasattr(snapshot, 'rs_vs_spy'):
            return None
        
        rs = snapshot.rs_vs_spy
        if abs(rs) < 2.0 or snapshot.rvol < 1.0:
            return None
        
        if rs > 0:
            direction = "long"
            stop = snapshot.current_price - (snapshot.atr * 1.5)
            target = snapshot.current_price + (snapshot.atr * 3)
            priority = AlertPriority.HIGH if rs >= 4.0 else AlertPriority.MEDIUM
            label = "LEADER"
            reasoning = [
                f"Outperforming SPY by {rs:.1f}% today",
                f"RS leaders tend to continue in trend days",
                f"Trend: {snapshot.trend} | RSI: {snapshot.rsi_14:.0f}",
                f"{'Above VWAP' if snapshot.above_vwap else 'Below VWAP'} | RVOL: {snapshot.rvol:.1f}x",
                f"Play: Buy dips, ride the relative strength"
            ]
        else:
            direction = "short"
            stop = snapshot.current_price + (snapshot.atr * 1.5)
            target = snapshot.current_price - (snapshot.atr * 3)
            priority = AlertPriority.HIGH if abs(rs) >= 4.0 else AlertPriority.MEDIUM
            label = "LAGGARD"
            reasoning = [
                f"Underperforming SPY by {abs(rs):.1f}% today",
                f"RS laggards tend to continue underperforming",
                f"Trend: {snapshot.trend} | RSI: {snapshot.rsi_14:.0f}",
                f"{'Above VWAP' if snapshot.above_vwap else 'Below VWAP'} | RVOL: {snapshot.rvol:.1f}x",
                f"Play: Short rallies into resistance"
            ]
        
        risk = abs(snapshot.current_price - stop)
        rr = abs(target - snapshot.current_price) / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"rs_{label.lower()}_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=f"relative_strength_{label.lower()}",
            strategy_name=f"Relative Strength {label}",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.current_price,
            stop_loss=round(stop, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.55,
            win_probability=0.56,
            minutes_to_trigger=20,
            headline=f"RS {label} {symbol} {rs:+.1f}% vs SPY - {'Outperforming' if direction == 'long' else 'Underperforming'} market",
            reasoning=reasoning,
            time_window=self._get_current_time_window().value,
            market_regime=self._market_regime.value,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        )
    
    async def _check_gap_fade(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Gap Fade: gap that's failing — trade the fill back to previous close"""
        if abs(snapshot.gap_pct) < 2.0 or snapshot.rvol < 1.3:
            return None
        
        # Gap up but failing (below VWAP, not holding gap)
        if snapshot.gap_pct > 0 and not snapshot.holding_gap and not snapshot.above_vwap:
            direction = "short"
            stop = snapshot.high_of_day + (snapshot.atr * 0.3)
            target = snapshot.prev_close
            priority = AlertPriority.HIGH if snapshot.gap_pct >= 4.0 else AlertPriority.MEDIUM
            if tape.confirmation_for_short:
                priority = AlertPriority.CRITICAL if priority == AlertPriority.HIGH else AlertPriority.HIGH
            
            risk = abs(snapshot.current_price - stop)
            rr = abs(target - snapshot.current_price) / risk if risk > 0 else 1
            
            return LiveAlert(
                id=f"gap_fade_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="gap_fade",
                strategy_name="Gap Fade Short",
                direction="short",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(stop, 2),
                target=round(target, 2),
                risk_reward=round(rr, 2),
                trigger_probability=0.60,
                win_probability=0.57,
                minutes_to_trigger=15,
                headline=f"GAP FADE {symbol} SHORT - +{snapshot.gap_pct:.1f}% gap FAILING, target fill ${snapshot.prev_close:.2f}",
                reasoning=[
                    f"Gapped up {snapshot.gap_pct:.1f}% but FAILING to hold",
                    f"Below VWAP ${snapshot.vwap:.2f} — sellers taking control",
                    f"Target: Gap fill to prev close ${snapshot.prev_close:.2f}",
                    f"RVOL: {snapshot.rvol:.1f}x | Tape: {tape.overall_signal.value}",
                    f"Stop above HOD ${snapshot.high_of_day:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        
        # Gap down but recovering (above VWAP, holding)
        if snapshot.gap_pct < 0 and snapshot.holding_gap and snapshot.above_vwap:
            direction = "long"
            stop = snapshot.low_of_day - (snapshot.atr * 0.3)
            target = snapshot.prev_close
            priority = AlertPriority.HIGH if abs(snapshot.gap_pct) >= 4.0 else AlertPriority.MEDIUM
            if tape.confirmation_for_long:
                priority = AlertPriority.CRITICAL if priority == AlertPriority.HIGH else AlertPriority.HIGH
            
            risk = abs(snapshot.current_price - stop)
            rr = abs(target - snapshot.current_price) / risk if risk > 0 else 1
            
            return LiveAlert(
                id=f"gap_fade_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="gap_fade",
                strategy_name="Gap Recovery Long",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(stop, 2),
                target=round(target, 2),
                risk_reward=round(rr, 2),
                trigger_probability=0.60,
                win_probability=0.57,
                minutes_to_trigger=15,
                headline=f"GAP RECOVERY {symbol} LONG - {snapshot.gap_pct:.1f}% gap RECOVERING, target fill ${snapshot.prev_close:.2f}",
                reasoning=[
                    f"Gapped down {abs(snapshot.gap_pct):.1f}% but RECOVERING",
                    f"Above VWAP ${snapshot.vwap:.2f} — buyers stepping in",
                    f"Target: Gap fill to prev close ${snapshot.prev_close:.2f}",
                    f"RVOL: {snapshot.rvol:.1f}x | Tape: {tape.overall_signal.value}",
                    f"Stop below LOD ${snapshot.low_of_day:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        
        return None
    
    async def _check_chart_pattern(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Chart Pattern Detection - Flags, pennants, triangles, H&S, wedges"""
        try:
            from services.chart_pattern_service import get_chart_pattern_service
            pattern_service = get_chart_pattern_service()
            
            if not pattern_service.is_initialized():
                return None
            
            # Detect patterns for this symbol
            patterns = await pattern_service.detect_patterns(symbol)
            
            if not patterns:
                return None
            
            # Get the best pattern (highest score)
            best_pattern = patterns[0]
            
            # Only alert on strong patterns with good R:R
            if best_pattern.pattern_score < 60 or best_pattern.risk_reward < 1.5:
                return None
            
            # Determine priority based on pattern strength and breakout status
            if best_pattern.strength.value == "strong" and not best_pattern.breakout_pending:
                priority = AlertPriority.CRITICAL
            elif best_pattern.strength.value == "strong":
                priority = AlertPriority.HIGH
            elif best_pattern.strength.value == "moderate":
                priority = AlertPriority.MEDIUM
            else:
                priority = AlertPriority.LOW
            
            direction = best_pattern.direction if best_pattern.direction != "neutral" else "long"
            
            return LiveAlert(
                id=f"pattern_{best_pattern.pattern_type.value}_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="chart_pattern",
                strategy_name=best_pattern.pattern_type.value.replace('_', ' ').title(),
                direction=direction,
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=best_pattern.entry_price,
                stop_loss=best_pattern.stop_loss,
                target=best_pattern.target_price,
                risk_reward=best_pattern.risk_reward,
                trigger_probability=0.55,
                win_probability=0.58,
                minutes_to_trigger=30,
                headline=f"CHART PATTERN: {best_pattern.pattern_type.value.replace('_', ' ').upper()} on {symbol}",
                reasoning=best_pattern.reasoning + [
                    f"Pattern Score: {best_pattern.pattern_score}/100",
                    f"Volume Confirmed: {best_pattern.volume_confirmation}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
            )
        except Exception as e:
            logger.debug(f"Chart pattern check failed for {symbol}: {e}")
            return None
    
    async def _check_first_vwap_pullback(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """First VWAP Pullback - Opening pullback to VWAP"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE]:
            return None
        
        if (snapshot.gap_pct > 2.0 and
            snapshot.holding_gap and
            -0.5 < snapshot.dist_from_vwap < 0.5 and
            snapshot.rvol >= 2.0):
            
            priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
            
            return LiveAlert(
                id=f"first_vwap_pb_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="first_vwap_pullback",
                strategy_name="First VWAP Pullback (INT-35)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(snapshot.vwap - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.5,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=5,
                headline=f"🎯 {symbol} First VWAP Pullback - Gap {snapshot.gap_pct:.1f}% {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Gap up {snapshot.gap_pct:.1f}%",
                    f"Pulled back to VWAP",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        return None
    
    async def _check_opening_drive(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Opening Drive - Strong momentum at open"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE]:
            return None
        
        if snapshot.gap_pct > 3.0 and snapshot.holding_gap and snapshot.rvol >= 3.0:
            priority = AlertPriority.CRITICAL if tape.confirmation_for_long else AlertPriority.HIGH
            
            return LiveAlert(
                id=f"opening_drive_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="opening_drive",
                strategy_name="Opening Drive (INT-47)",
                direction="long" if snapshot.gap_pct > 0 else "short",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.low_of_day - 0.02, 2),
                target=round(snapshot.current_price + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=5,
                headline=f"🚄 {symbol} Opening Drive - {snapshot.gap_pct:.1f}% gap {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Strong gap: {snapshot.gap_pct:.1f}%",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        return None
    
    async def _check_big_dog(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Big Dog Consolidation - Tight wedge 15+ min"""
        if (snapshot.daily_range_pct < 2.0 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.2):
            
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 1.0:
                priority = AlertPriority.MEDIUM
                
                return LiveAlert(
                    id=f"big_dog_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="big_dog",
                    strategy_name="Big Dog Consolidation (INT-44)",
                    direction="long",
                    priority=priority,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.ema_9 - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.atr * 1.5), 2),
                    risk_reward=2.0,
                    trigger_probability=0.55,
                    win_probability=0.55,
                    minutes_to_trigger=15,
                    headline=f"🐕 {symbol} Big Dog - Tight consolidation",
                    reasoning=[
                        f"Tight range near HOD",
                        f"Above VWAP and 9-EMA",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_puppy_dog(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """Puppy Dog Consolidation - Smaller/faster version of Big Dog"""
        if (snapshot.daily_range_pct < 1.5 and
            snapshot.daily_range_pct > 0.5 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.5):
            
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 0.5:
                return LiveAlert(
                    id=f"puppy_dog_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="puppy_dog",
                    strategy_name="Puppy Dog Consolidation (INT-27)",
                    direction="long",
                    priority=AlertPriority.MEDIUM,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.current_price - (snapshot.atr * 0.3), 2),
                    target=round(snapshot.high_of_day + (snapshot.atr * 1.0), 2),
                    risk_reward=2.5,
                    trigger_probability=0.55,
                    win_probability=0.55,
                    minutes_to_trigger=10,
                    headline=f"🐶 {symbol} Puppy Dog - Quick consolidation break",
                    reasoning=[
                        f"Tight 5-10 min consolidation",
                        f"Higher RVOL than Big Dog",
                        f"Tape: {tape.overall_signal.value}",
                        f"Entry: Micro-break of consolidation"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
                )
        return None
    
    async def _check_9_ema_scalp(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """9 EMA Scalp - Institutional buying at 9-EMA"""
        if (abs(snapshot.dist_from_ema9) < 0.5 and
            snapshot.trend == "uptrend" and
            snapshot.above_vwap and
            snapshot.rvol >= 1.5):
            
            return LiveAlert(
                id=f"9ema_scalp_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="9_ema_scalp",
                strategy_name="9 EMA Scalp (INT-40)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.ema_9,
                stop_loss=round(snapshot.ema_20 - 0.02, 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=10,
                headline=f"📉 {symbol} 9-EMA Scalp - Testing ${snapshot.ema_9:.2f}",
                reasoning=[
                    f"Testing 9-EMA ${snapshot.ema_9:.2f}",
                    f"Uptrend, above VWAP",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_abc_scalp(self, symbol: str, snapshot, tape: TapeReading) -> Optional[LiveAlert]:
        """ABC Scalp - Three wave pattern"""
        # ABC pattern detection: A=impulse, B=pullback, C=continuation
        # Simplified: Look for pullback in uptrend that's finding support
        if (snapshot.trend == "uptrend" and
            snapshot.above_vwap and
            -1.0 < snapshot.dist_from_ema9 < 0.3 and  # Pulling back to 9-EMA
            snapshot.rsi_14 > 45 and snapshot.rsi_14 < 65 and  # Not oversold/overbought
            snapshot.rvol >= 1.2):
            
            return LiveAlert(
                id=f"abc_scalp_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="abc_scalp",
                strategy_name="ABC Scalp (INT-41)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.ema_9 - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"🔢 {symbol} ABC Scalp - Wave C setup",
                reasoning=[
                    f"A-B-C pattern forming",
                    f"Wave B pullback to 9-EMA",
                    f"RSI: {snapshot.rsi_14:.0f} (healthy)",
                    f"Tape: {tape.overall_signal.value}",
                    f"Entry: Break above Wave B high"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    

    # ==================== DAILY/SWING/POSITION SETUPS ====================
    # These run on a slower cadence (every 10th scan cycle) using daily bars from MongoDB
    
    async def _scan_daily_setups(self):
        """Scan for swing and position setups.
        
        Uses a hybrid approach:
        - RECENT daily bars from ib_historical_data (for 20-60 day patterns)
        - TODAY's live data from pushed quotes/snapshots (for current bar)
        This way even if historical data is a few days stale, we still get
        reasonable results by appending today's live bar.
        """
        try:
            if not self.db:
                return
            
            # Get today's live data from pushed quotes
            live_quotes = {}
            try:
                from routers.ib import get_pushed_quotes, get_pushed_positions, is_pusher_connected
                if is_pusher_connected():
                    live_quotes = get_pushed_quotes() or {}
            except Exception:
                pass
            
            if not live_quotes:
                logger.debug("Daily scan: no live quotes available, skipping")
                return
            
            # Get symbols with daily data (use ADV cache for filtering)
            symbols = list(self._symbol_adv_cache.keys())[:200]
            if not symbols:
                symbols = list(live_quotes.keys())[:200]
            
            scanned = 0
            alerts_found = 0
            for symbol in symbols:
                try:
                    # Get historical daily bars from MongoDB
                    bars = list(self.db["ib_historical_data"].find(
                        {"symbol": symbol, "bar_size": "1 day"},
                        {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
                    ).sort("date", -1).limit(60))
                    
                    if len(bars) < 15:
                        continue
                    
                    bars.reverse()  # Oldest first
                    
                    # Append today's live bar from pushed quotes
                    quote = live_quotes.get(symbol, {})
                    if quote:
                        last_price = quote.get("last") or quote.get("close") or 0
                        if last_price > 0:
                            today_bar = {
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "open": quote.get("open", last_price) or last_price,
                                "high": quote.get("high", last_price) or last_price,
                                "low": quote.get("low", last_price) or last_price,
                                "close": last_price,
                                "volume": quote.get("volume", 0) or 0,
                            }
                            # Only append if it's a different date than the last bar
                            last_bar_date = bars[-1].get("date", "")[:10] if bars else ""
                            today_date = today_bar["date"]
                            if today_date != last_bar_date:
                                bars.append(today_bar)
                            else:
                                # Update today's bar with live data
                                bars[-1] = today_bar
                    
                    # Run daily setup checks
                    for check in [
                        self._check_daily_squeeze,
                        self._check_trend_continuation,
                        self._check_daily_breakout,
                        self._check_base_breakout,
                        self._check_accumulation_entry,
                        self._check_breakdown_confirmed_daily,
                    ]:
                        try:
                            alert = await check(symbol, bars)
                            if alert:
                                await self._process_new_alert(alert)
                                alerts_found += 1
                        except Exception:
                            pass
                    
                    scanned += 1
                except Exception:
                    pass
            
            logger.info(f"📊 Daily scan: {scanned} symbols, {alerts_found} swing/position alerts found")
        except Exception as e:
            logger.error(f"Daily scan error: {e}")

    async def _check_daily_squeeze(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """Bollinger Bands inside Keltner Channels on DAILY bars = multi-day squeeze."""
        if len(bars) < 20:
            return None
        
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        
        # 20-period SMA and Bollinger Bands
        sma20 = sum(closes[-20:]) / 20
        std20 = (sum((c - sma20) ** 2 for c in closes[-20:]) / 20) ** 0.5
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_width = (bb_upper - bb_lower) / sma20 * 100 if sma20 > 0 else 999
        
        # Keltner Channels (20-period EMA + 1.5 * ATR)
        atrs = []
        for i in range(1, min(15, len(bars))):
            tr = max(
                highs[-(i)] - lows[-(i)],
                abs(highs[-(i)] - closes[-(i+1)]),
                abs(lows[-(i)] - closes[-(i+1)])
            )
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else 0
        kc_upper = sma20 + 1.5 * atr
        kc_lower = sma20 - 1.5 * atr
        
        # Squeeze: BB inside KC
        is_squeeze = bb_upper < kc_upper and bb_lower > kc_lower
        if not is_squeeze:
            return None
        
        # Adaptive BB width threshold: compare to stock's own historical BB width
        # Calculate median BB width over last 40 bars
        hist_widths = []
        for i in range(20, min(40, len(closes))):
            s = sum(closes[i-20:i]) / 20
            sd = (sum((c - s) ** 2 for c in closes[i-20:i]) / 20) ** 0.5
            w = (4 * sd) / s * 100 if s > 0 else 0
            hist_widths.append(w)
        
        if hist_widths:
            median_width = sorted(hist_widths)[len(hist_widths) // 2]
            # Squeeze is significant if current width is < 70% of historical median
            if bb_width > median_width * 0.7:
                return None  # Not tight enough relative to this stock's norm
        else:
            # Fallback: absolute threshold
            if bb_width > 15:
                return None
        
        # Determine direction from momentum (close vs SMA)
        momentum = closes[-1] - sma20
        direction = "long" if momentum > 0 else "short"
        
        current = closes[-1]
        stop = current * (0.95 if direction == "long" else 1.05)
        target = current * (1.10 if direction == "long" else 0.90)
        
        return LiveAlert(
            id=f"daily_squeeze_{symbol}_{direction}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="daily_squeeze",
            direction=direction,
            priority=AlertPriority.HIGH,
            trigger_price=current,
            stop_loss=round(stop, 2),
            target=round(target, 2),
            risk_reward=abs(target - current) / abs(current - stop) if abs(current - stop) > 0 else 0,
            headline=f"📊 {symbol} DAILY SQUEEZE ({direction.upper()}) - BB Width {bb_width:.1f}%",
            reasoning=[
                f"Daily Bollinger Bands INSIDE Keltner Channels = multi-day volatility squeeze",
                f"BB Width: {bb_width:.1f}% (tight = explosive breakout imminent)",
                f"Momentum: {'bullish' if momentum > 0 else 'bearish'} (close {'above' if momentum > 0 else 'below'} 20 SMA)",
                f"ATR: ${atr:.2f} | Swing trade — hold overnight",
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    async def _check_trend_continuation(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """Higher highs + higher lows on daily chart, pulling back to rising 20 EMA."""
        if len(bars) < 25:
            return None
        
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        
        # 20 EMA
        ema20 = closes[-20]
        multiplier = 2 / 21
        for c in closes[-19:]:
            ema20 = c * multiplier + ema20 * (1 - multiplier)
        
        # Check EMA is rising (current > 5 bars ago)
        ema20_5ago = closes[-25]
        for c in closes[-24:-5]:
            ema20_5ago = c * multiplier + ema20_5ago * (1 - multiplier)
        
        if ema20 <= ema20_5ago:
            return None  # EMA not rising
        
        # Check higher highs and higher lows (last 3 swings)
        recent_highs = [max(highs[i:i+5]) for i in range(-15, 0, 5)]
        recent_lows = [min(lows[i:i+5]) for i in range(-15, 0, 5)]
        
        hh = all(recent_highs[i] > recent_highs[i-1] for i in range(1, len(recent_highs)))
        hl = all(recent_lows[i] > recent_lows[i-1] for i in range(1, len(recent_lows)))
        
        if not (hh and hl):
            return None  # No uptrend structure
        
        # Price pulling back near 20 EMA (within 2%)
        current = closes[-1]
        dist_from_ema = (current - ema20) / ema20 * 100
        if dist_from_ema < -0.5 or dist_from_ema > 2.0:
            return None  # Not near EMA
        
        # ATR for stop
        atrs = []
        for i in range(1, min(15, len(bars))):
            tr = max(highs[-(i)] - lows[-(i)], abs(highs[-(i)] - closes[-(i+1)]), abs(lows[-(i)] - closes[-(i+1)]))
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else current * 0.02
        
        stop = round(ema20 - atr * 1.5, 2)
        target = round(current + atr * 3, 2)
        rr = abs(target - current) / abs(current - stop) if abs(current - stop) > 0 else 0
        
        return LiveAlert(
            id=f"trend_continuation_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="trend_continuation",
            direction="long",
            priority=AlertPriority.MEDIUM,
            trigger_price=current,
            stop_loss=stop,
            target=target,
            risk_reward=round(rr, 1),
            headline=f"📈 {symbol} Trend Continuation - Pullback to rising 20 EMA",
            reasoning=[
                f"Daily uptrend: Higher highs + higher lows confirmed",
                f"Price {dist_from_ema:.1f}% from rising 20 EMA (pullback entry zone)",
                f"EMA slope: rising (current ${ema20:.2f} > 5-bar-ago ${ema20_5ago:.2f})",
                f"ATR: ${atr:.2f} | R:R {rr:.1f}:1 | Swing hold",
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    async def _check_daily_breakout(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """Breaking above multi-day resistance on above-average volume."""
        if len(bars) < 20:
            return None
        
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        volumes = [b["volume"] for b in bars]
        
        current = closes[-1]
        prev_high = max(highs[-20:-1])  # 20-day high excluding today
        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else 0
        today_vol = volumes[-1]
        
        # Need to be above the 20-day high
        breakout_pct = (current - prev_high) / prev_high * 100 if prev_high > 0 else 0
        if breakout_pct < 0.5 or breakout_pct > 8:
            return None
        
        # Adaptive volume threshold: use ATR-based volatility to adjust
        # Higher volatility stocks need more volume confirmation
        atrs = []
        lows = [b["low"] for b in bars]
        for i in range(1, min(15, len(bars))):
            tr = max(highs[-(i)] - lows[-(i)], abs(highs[-(i)] - closes[-(i+1)]), abs(lows[-(i)] - closes[-(i+1)]))
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else current * 0.02
        atr_pct = (atr / current * 100) if current > 0 else 2
        
        # Low vol stocks (ATR < 2%) need 1.5x vol; high vol (ATR > 4%) need 1.2x
        vol_threshold = 1.5 if atr_pct < 2 else 1.3 if atr_pct < 4 else 1.2
        
        rvol = today_vol / avg_vol if avg_vol > 0 else 0
        if rvol < vol_threshold:
            return None
        
        # ATR for stop
        lows = [b["low"] for b in bars]
        atrs = []
        for i in range(1, min(15, len(bars))):
            tr = max(highs[-(i)] - lows[-(i)], abs(highs[-(i)] - closes[-(i+1)]), abs(lows[-(i)] - closes[-(i+1)]))
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else current * 0.02
        
        stop = round(prev_high - atr * 0.5, 2)  # Stop just below old resistance
        target = round(current + (current - stop) * 2, 2)
        rr = abs(target - current) / abs(current - stop) if abs(current - stop) > 0 else 0
        
        return LiveAlert(
            id=f"daily_breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="daily_breakout",
            direction="long",
            priority=AlertPriority.HIGH,
            trigger_price=current,
            stop_loss=stop,
            target=target,
            risk_reward=round(rr, 1),
            headline=f"🚀 {symbol} DAILY BREAKOUT - New 20-day high on {rvol:.1f}x volume",
            reasoning=[
                f"Price broke 20-day high ${prev_high:.2f} by {breakout_pct:.1f}%",
                f"Volume confirmation: {rvol:.1f}x average daily volume",
                f"Stop below old resistance ${stop:.2f} | Target ${target:.2f}",
                f"Swing trade — hold for follow-through",
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    async def _check_base_breakout(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """Multi-week tight consolidation breakout (position trade)."""
        if len(bars) < 40:
            return None
        
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        volumes = [b["volume"] for b in bars]
        
        # Calculate the stock's typical daily range for context
        daily_ranges = [(highs[i] - lows[i]) / closes[i] * 100 for i in range(-40, -1) if closes[i] > 0]
        avg_daily_range = sum(daily_ranges) / len(daily_ranges) if daily_ranges else 2
        
        # Check for tight range in last 20 bars (base)
        base_highs = highs[-20:-1]
        base_lows = lows[-20:-1]
        base_high = max(base_highs)
        base_low = min(base_lows)
        base_range_pct = (base_high - base_low) / base_low * 100 if base_low > 0 else 999
        
        # Adaptive tightness: base range should be < 5x the avg daily range
        # (e.g., if avg daily range is 3%, base should be < 15%)
        max_base_range = max(8, avg_daily_range * 5)
        if base_range_pct > max_base_range or base_range_pct < 2:
            return None
        
        current = closes[-1]
        # Need to break above the base
        if current <= base_high:
            return None
        
        breakout_pct = (current - base_high) / base_high * 100
        if breakout_pct < 0.5 or breakout_pct > 5:
            return None
        
        # Volume confirmation
        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else 0
        rvol = volumes[-1] / avg_vol if avg_vol > 0 else 0
        if rvol < 1.5:
            return None
        
        stop = round(base_low + (base_high - base_low) * 0.3, 2)  # Stop in lower third of base
        target = round(current + (base_high - base_low), 2)  # Measured move
        rr = abs(target - current) / abs(current - stop) if abs(current - stop) > 0 else 0
        
        return LiveAlert(
            id=f"base_breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="base_breakout",
            direction="long",
            priority=AlertPriority.HIGH,
            trigger_price=current,
            stop_loss=stop,
            target=target,
            risk_reward=round(rr, 1),
            headline=f"🏗️ {symbol} BASE BREAKOUT - {int(20)}-day base on {rvol:.1f}x volume",
            reasoning=[
                f"20-day consolidation base (range: {base_range_pct:.1f}%)",
                f"Broke above ${base_high:.2f} by {breakout_pct:.1f}%",
                f"Volume: {rvol:.1f}x average | Measured move target: ${target:.2f}",
                f"Position trade — multi-week hold expected",
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        )

    async def _check_accumulation_entry(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """Weekly oversold + volume increasing = accumulation zone entry (position)."""
        if len(bars) < 30:
            return None
        
        closes = [b["close"] for b in bars]
        volumes = [b["volume"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        
        # RSI(14) on daily
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            change = closes[-i] - closes[-(i+1)]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0.001
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        # Need RSI oversold (< 35)
        if rsi > 35:
            return None
        
        # Volume increasing (last 5 days avg > previous 10 days avg)
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
        prior_vol = sum(volumes[-15:-5]) / 10 if len(volumes) >= 15 else 0
        vol_increase = recent_vol / prior_vol if prior_vol > 0 else 0
        
        if vol_increase < 1.2:
            return None  # No volume accumulation
        
        # Check price is near 50-day low (within 10%)
        low_50 = min(lows[-50:]) if len(lows) >= 50 else min(lows)
        dist_from_low = (closes[-1] - low_50) / low_50 * 100 if low_50 > 0 else 999
        if dist_from_low > 10:
            return None
        
        current = closes[-1]
        stop = round(low_50 * 0.97, 2)  # 3% below 50-day low
        # ATR for target
        atrs = []
        for i in range(1, min(15, len(bars))):
            tr = max(highs[-(i)] - lows[-(i)], abs(highs[-(i)] - closes[-(i+1)]), abs(lows[-(i)] - closes[-(i+1)]))
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else current * 0.03
        target = round(current + atr * 5, 2)
        rr = abs(target - current) / abs(current - stop) if abs(current - stop) > 0 else 0
        
        return LiveAlert(
            id=f"accumulation_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="accumulation_entry",
            direction="long",
            priority=AlertPriority.MEDIUM,
            trigger_price=current,
            stop_loss=stop,
            target=target,
            risk_reward=round(rr, 1),
            headline=f"🔋 {symbol} ACCUMULATION - RSI {rsi:.0f} + volume building",
            reasoning=[
                f"Daily RSI oversold at {rsi:.0f}",
                f"Volume accumulating: {vol_increase:.1f}x increase vs prior 10 days",
                f"Price {dist_from_low:.1f}% from 50-day low ${low_50:.2f}",
                f"Position trade — weeks to months hold",
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
        )

    async def _check_breakdown_confirmed_daily(self, symbol: str, bars: list) -> Optional[LiveAlert]:
        """Confirmed breakdown below daily support on volume (short setup)."""
        if len(bars) < 20:
            return None
        
        closes = [b["close"] for b in bars]
        lows = [b["low"] for b in bars]
        highs = [b["high"] for b in bars]
        volumes = [b["volume"] for b in bars]
        
        current = closes[-1]
        prev_low = min(lows[-20:-1])  # 20-day low excluding today
        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else 0
        
        # Need to break below 20-day low
        breakdown_pct = (prev_low - current) / prev_low * 100 if prev_low > 0 else 0
        if breakdown_pct < 0.5 or breakdown_pct > 8:
            return None
        
        # Volume confirmation
        rvol = volumes[-1] / avg_vol if avg_vol > 0 else 0
        if rvol < 1.3:
            return None
        
        # ATR
        atrs = []
        for i in range(1, min(15, len(bars))):
            tr = max(highs[-(i)] - lows[-(i)], abs(highs[-(i)] - closes[-(i+1)]), abs(lows[-(i)] - closes[-(i+1)]))
            atrs.append(tr)
        atr = sum(atrs) / len(atrs) if atrs else current * 0.02
        
        stop = round(prev_low + atr * 0.5, 2)
        target = round(current - (stop - current) * 2, 2)
        rr = abs(current - target) / abs(stop - current) if abs(stop - current) > 0 else 0
        
        return LiveAlert(
            id=f"breakdown_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="breakdown_confirmed",
            direction="short",
            priority=AlertPriority.HIGH,
            trigger_price=current,
            stop_loss=stop,
            target=target,
            risk_reward=round(rr, 1),
            headline=f"📉 {symbol} BREAKDOWN - Below 20-day low on {rvol:.1f}x volume",
            reasoning=[
                f"Price broke 20-day low ${prev_low:.2f} by {breakdown_pct:.1f}%",
                f"Volume confirmation: {rvol:.1f}x average",
                f"Stop above old support ${stop:.2f} | Target ${target:.2f}",
                f"Short swing trade",
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        )

    # ==================== ALERT MANAGEMENT ====================
    
    async def _process_new_alert(self, alert: LiveAlert):
        """Process a new alert — enforces per-symbol dedup (max 1 active per symbol)"""
        # Check for duplicate: same symbol + same setup_type
        for existing in self._live_alerts.values():
            if (existing.symbol == alert.symbol and 
                existing.setup_type == alert.setup_type and
                existing.status == "active"):
                return
        
        # Per-symbol dedup: if another active alert exists for this symbol,
        # only keep the higher priority one (replaces if new is better)
        existing_for_symbol = [
            (aid, a) for aid, a in self._live_alerts.items()
            if a.symbol == alert.symbol and a.status == "active"
        ]
        if existing_for_symbol:
            priority_order = {
                AlertPriority.CRITICAL: 0, AlertPriority.HIGH: 1,
                AlertPriority.MEDIUM: 2, AlertPriority.LOW: 3
            }
            best_existing = min(existing_for_symbol, key=lambda x: priority_order.get(x[1].priority, 4))
            new_prio = priority_order.get(alert.priority, 4)
            existing_prio = priority_order.get(best_existing[1].priority, 4)
            if new_prio >= existing_prio:
                # New alert is same or lower priority — skip it
                return
            else:
                # New alert is higher priority — replace the existing one
                del self._live_alerts[best_existing[0]]
                logger.info(f"Dedup: Replaced {best_existing[1].setup_type} with higher-priority {alert.setup_type} for {alert.symbol}")
        
        # Update strategy stats
        base_setup = alert.setup_type.split("_long")[0].split("_short")[0]
        if base_setup in self._strategy_stats:
            self._strategy_stats[base_setup].total_alerts += 1
        
        # === SMB INTEGRATION: Populate SMB fields ===
        try:
            context = {
                "market_regime": self._market_regime.value,
                "tape_score": alert.tape_score if hasattr(alert, 'tape_score') else 5
            }
            alert.populate_smb_fields(context)
            logger.debug(f"SMB fields populated for {alert.symbol}: style={alert.trade_style}, grade={alert.trade_grade}")
        except Exception as e:
            logger.debug(f"Could not populate SMB fields: {e}")
        
        # === DMA DIRECTIONAL FILTER ===
        # Swing trades: require alignment with EMA50
        # Investment trades: require alignment with SMA200
        try:
            trade_style = alert.trade_style or "intraday"
            direction = getattr(alert, 'direction_bias', 'long')
            
            if trade_style in ("swing", "multi_day", "position"):
                snapshot = await self.technical_service.get_technical_snapshot(alert.symbol)
                if snapshot and hasattr(snapshot, 'ema_50') and snapshot.ema_50 > 0:
                    price = snapshot.last or alert.trigger_price
                    if direction == "long" and price < snapshot.ema_50:
                        logger.info(f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} LONG swing — price ${price:.2f} below EMA50 ${snapshot.ema_50:.2f}")
                        return
                    elif direction == "short" and price > snapshot.ema_50:
                        logger.info(f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} SHORT swing — price ${price:.2f} above EMA50 ${snapshot.ema_50:.2f}")
                        return
                
                # Investment: also check SMA200
                if trade_style == "position":
                    if snapshot and hasattr(snapshot, 'sma_200') and snapshot.sma_200 > 0:
                        price = snapshot.last or alert.trigger_price
                        if direction == "long" and price < snapshot.sma_200:
                            logger.info(f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} LONG investment — price ${price:.2f} below SMA200 ${snapshot.sma_200:.2f}")
                            return
                        elif direction == "short" and price > snapshot.sma_200:
                            logger.info(f"DMA Filter: Skipping {alert.symbol} {alert.setup_type} SHORT investment — price ${price:.2f} above SMA200 ${snapshot.sma_200:.2f}")
                            return
        except Exception as e:
            logger.debug(f"DMA filter check: {e}")
        
        # === LEARNING LOOP: Capture context (Phase 1) ===
        try:
            from services.learning_loop_service import get_learning_loop_service
            learning_loop = get_learning_loop_service()
            if learning_loop:
                await learning_loop.capture_alert_context(
                    alert_id=alert.id,
                    symbol=alert.symbol,
                    setup_type=alert.setup_type,
                    alert_priority=alert.priority.value,
                    tape_score=alert.tape_score,
                    tape_confirmation=alert.tape_confirmation,
                    smb_score=alert.smb_score_total,
                    trade_grade=alert.trade_grade
                )
        except Exception as e:
            logger.debug(f"Could not capture learning context: {e}")
        
        # Set scan tier from ADV classification
        alert.scan_tier = self._tier_cache.get(alert.symbol, self._classify_symbol_tier(alert.symbol))
        
        self._live_alerts[alert.id] = alert
        self._alerts_generated += 1
        
        # === AUTO-POPULATE SMART WATCHLIST ===
        try:
            from services.smart_watchlist_service import get_smart_watchlist
            smart_wl = get_smart_watchlist()
            if smart_wl:
                # Calculate score based on alert properties
                score = 50
                if alert.priority.value == "critical":
                    score += 30
                elif alert.priority.value == "high":
                    score += 20
                if alert.tape_confirmation:
                    score += 10
                if alert.strategy_win_rate and alert.strategy_win_rate > 0.6:
                    score += 10
                
                smart_wl.add_scanner_hit(
                    symbol=alert.symbol,
                    strategy=alert.setup_type,
                    score=min(100, score),
                    notes=alert.headline
                )
        except Exception as e:
            logger.debug(f"Could not add to smart watchlist: {e}")
        
        # === SECTOR CONTEXT ENHANCEMENT ===
        # Add sector strength context to alert
        try:
            from services.sector_analysis_service import get_sector_analysis_service
            sector_service = get_sector_analysis_service()
            sector_context = await sector_service.get_stock_sector_context(alert.symbol)
            
            if sector_context:
                # Add sector context to reasoning
                sector_note = f"Sector: {sector_context.sector} (Rank #{sector_context.sector_rank}, {sector_context.sector_strength.value})"
                if sector_context.is_sector_leader:
                    sector_note += " - SECTOR LEADER"
                elif sector_context.is_sector_laggard:
                    sector_note += " - Sector Laggard"
                
                # Add to reasoning list
                alert.reasoning.append(sector_note)
                
                # Boost priority for leaders in hot sectors (for longs)
                if (sector_context.sector_strength.value == "hot" and 
                    sector_context.is_sector_leader and 
                    alert.direction == "long" and
                    alert.priority != AlertPriority.CRITICAL):
                    # Upgrade priority
                    if alert.priority == AlertPriority.MEDIUM:
                        alert.priority = AlertPriority.HIGH
                    alert.reasoning.append(f"Priority boost: Leading in HOT sector (+{sector_context.stock_vs_sector}% vs sector)")
                
                # Warn about headwinds for longs in cold sectors
                elif (sector_context.sector_strength.value == "cold" and 
                      alert.direction == "long"):
                    alert.reasoning.append(f"Warning: {sector_context.sector} sector is COLD - headwind risk")
        except Exception as e:
            logger.debug(f"Could not add sector context: {e}")
        
        # === SENTIMENT ANALYSIS ENHANCEMENT ===
        # Add news sentiment to alert for high-priority setups
        if alert.priority.value in ["critical", "high"]:
            try:
                from services.sentiment_analysis_service import get_sentiment_service
                sentiment_service = get_sentiment_service()
                sentiment = await sentiment_service.analyze_sentiment(alert.symbol, use_ai=False)
                
                if sentiment:
                    sentiment_desc = f"Sentiment: {sentiment.overall_sentiment.value} ({sentiment.sentiment_score:+.2f})"
                    alert.reasoning.append(sentiment_desc)
                    
                    # Confirm or warn based on sentiment vs direction alignment
                    if alert.direction == "long" and sentiment.sentiment_score > 0.3:
                        alert.reasoning.append("News sentiment supports bullish thesis")
                    elif alert.direction == "short" and sentiment.sentiment_score < -0.3:
                        alert.reasoning.append("News sentiment supports bearish thesis")
                    elif alert.direction == "long" and sentiment.sentiment_score < -0.3:
                        alert.reasoning.append("WARNING: Bearish news sentiment - proceed with caution")
                    elif alert.direction == "short" and sentiment.sentiment_score > 0.3:
                        alert.reasoning.append("WARNING: Bullish news sentiment - proceed with caution")
            except Exception as e:
                logger.debug(f"Could not add sentiment context: {e}")
        
        # Persist to database
        if self.db is not None:
            try:
                await self._save_alert_to_db(alert)
            except Exception as e:
                logger.warning(f"Could not save alert to DB: {e}")
        
        # Notify subscribers
        await self._notify_subscribers(alert)
        
        # === PROACTIVE AI COACHING NOTIFICATION ===
        # Notify AI assistant of high-priority opportunities for coaching
        if alert.priority.value in ["critical", "high"]:
            try:
                await self._notify_ai_of_alert(alert)
            except Exception as e:
                logger.debug(f"AI notification skipped: {e}")
        
        self._enforce_alert_limit()
        
        tape_indicator = "✓ TAPE" if alert.tape_confirmation else ""
        logger.info(f"🚨 {alert.headline} | WR: {alert.strategy_win_rate:.0%} {tape_indicator}")
    
    async def _save_alert_to_db(self, alert: LiveAlert):
        if self.alerts_collection is not None:
            await asyncio.to_thread(
                self.alerts_collection.update_one,
                {"id": alert.id},
                {"$set": alert.to_dict()},
                upsert=True
            )
    
    async def _notify_subscribers(self, alert: LiveAlert):
        alert_data = alert.to_dict()
        for queue in self._alert_subscribers:
            try:
                queue.put_nowait(alert_data)
            except asyncio.QueueFull:
                pass
    
    def _cleanup_expired_alerts(self):
        now = datetime.now(timezone.utc)
        expired = []
        
        for alert_id, alert in self._live_alerts.items():
            if alert.expires_at:
                try:
                    expires = datetime.fromisoformat(alert.expires_at.replace('Z', '+00:00'))
                    if now > expires:
                        expired.append(alert_id)
                except:
                    pass
        
        for alert_id in expired:
            del self._live_alerts[alert_id]
    
    def _enforce_alert_limit(self):
        if len(self._live_alerts) > self._max_alerts:
            sorted_alerts = sorted(
                self._live_alerts.items(),
                key=lambda x: x[1].created_at,
                reverse=True
            )
            self._live_alerts = dict(sorted_alerts[:self._max_alerts])
    
    # ==================== PUBLIC API ====================
    
    def get_live_alerts(self, priority: AlertPriority = None) -> List[LiveAlert]:
        alerts = list(self._live_alerts.values())
        
        if priority:
            alerts = [a for a in alerts if a.priority == priority]
        
        priority_order = {
            AlertPriority.CRITICAL: 0,
            AlertPriority.HIGH: 1,
            AlertPriority.MEDIUM: 2,
            AlertPriority.LOW: 3
        }
        alerts.sort(key=lambda x: (priority_order.get(x.priority, 4), x.created_at), reverse=True)
        
        return alerts
    
    def get_alert_by_id(self, alert_id: str) -> Optional[LiveAlert]:
        return self._live_alerts.get(alert_id)
    
    def dismiss_alert(self, alert_id: str) -> bool:
        if alert_id in self._live_alerts:
            self._live_alerts[alert_id].acknowledged = True
            self._live_alerts[alert_id].status = "dismissed"
            return True
        return False
    
    def get_alerts_for_symbol(self, symbol: str) -> List[LiveAlert]:
        """Get all live alerts for a specific symbol"""
        symbol = symbol.upper()
        return [a for a in self._live_alerts.values() if a.symbol == symbol]

    def get_daily_swing_alerts(self) -> list:
        """Get only daily/swing/position setup alerts (not intraday)."""
        DAILY_SETUPS = {
            'daily_squeeze', 'trend_continuation', 'daily_breakout',
            'base_breakout', 'accumulation_entry', 'breakdown_confirmed',
            'relative_strength_position', 'earnings_momentum', 'sector_rotation',
            'gap_fade_daily', 'squeeze',
        }
        alerts = [
            a for a in self._live_alerts.values()
            if a.setup_type in DAILY_SETUPS and a.status == "active"
        ]
        alerts.sort(key=lambda x: x.created_at, reverse=True)
        return alerts

    
    def set_watchlist(self, symbols: List[str]):
        self._watchlist = [s.upper() for s in symbols]
        logger.info(f"Watchlist updated: {len(self._watchlist)} symbols")
    
    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        self._alert_subscribers.append(queue)
        return queue
    
    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self._alert_subscribers:
            self._alert_subscribers.remove(queue)
    
    async def _enrich_alert_with_tqs(self, alert: LiveAlert) -> None:
        """
        Calculate TQS for an alert and add the scores.
        High-quality alerts (TQS >= 70) are flagged for UI highlighting.
        """
        try:
            from services.tqs.tqs_engine import get_tqs_engine
            tqs_engine = get_tqs_engine()
            
            # Determine trade style from alert
            trade_style = alert.trade_style or "trade_2_hold"
            
            # Calculate TQS with all available context
            # GAP 2 FIX: Pass AI model alignment data so Context Quality pillar can score it
            ai_dir = getattr(alert, 'ai_prediction', None)
            ai_conf = getattr(alert, 'ai_confidence', None)
            if ai_conf is not None:
                ai_conf = ai_conf / 100.0  # Convert 0-100 to 0.0-1.0
            ai_agrees = getattr(alert, 'ai_agrees_with_direction', None)
            
            tqs_result = await tqs_engine.calculate_tqs(
                symbol=alert.symbol,
                setup_type=alert.setup_type,
                direction=alert.direction,
                trade_style=trade_style,
                tape_score=alert.tape_score,
                tape_confirmation=alert.tape_confirmation,
                smb_grade=alert.trade_grade,
                smb_5var_score=alert.smb_score_total,
                risk_reward=alert.risk_reward,
                alert_priority=alert.priority.value if hasattr(alert.priority, 'value') else str(alert.priority),
                ai_model_direction=ai_dir,
                ai_model_confidence=ai_conf,
                ai_model_agrees=ai_agrees,
            )
            
            if tqs_result:
                # Populate alert with TQS data
                alert.tqs_score = tqs_result.score
                alert.tqs_grade = tqs_result.grade
                alert.tqs_action = tqs_result.action
                alert.tqs_trade_style = tqs_result.trade_style
                alert.tqs_timeframe = tqs_result.trade_timeframe
                alert.tqs_key_factors = tqs_result.key_factors[:3] if tqs_result.key_factors else []
                alert.tqs_concerns = tqs_result.concerns[:3] if tqs_result.concerns else []
                
                # Flag high-quality alerts (TQS >= 70)
                alert.tqs_is_high_quality = tqs_result.score >= 70
                
                logger.debug(
                    f"TQS for {alert.symbol} {alert.setup_type}: "
                    f"{tqs_result.score:.0f} ({tqs_result.grade}) - {tqs_result.action} "
                    f"[{tqs_result.trade_style}: {tqs_result.trade_timeframe}]"
                )
                
        except Exception as e:
            logger.warning(f"Could not calculate TQS for alert {alert.symbol}: {e}")
            # Leave TQS fields at defaults (0, empty)
    
    async def _enrich_alert_with_ai(self, alert: LiveAlert) -> None:
        """
        Add AI predictions to the alert.
        Uses Time-Series AI to predict direction and confidence.
        """
        try:
            from services.ai_modules.timeseries_service import get_timeseries_ai
            ts_service = get_timeseries_ai()
            
            if not ts_service:
                return
            
            # Get AI prediction for this symbol using get_forecast method
            prediction = await ts_service.get_forecast(alert.symbol)
            
            if prediction and prediction.get("usable"):
                # Extract prediction details
                direction = prediction.get("direction", "neutral")
                confidence = prediction.get("confidence", 0.0) * 100  # Convert to 0-100
                prob_up = prediction.get("probability_up", 0.5)
                prob_down = prediction.get("probability_down", 0.5)
                # Estimate predicted move based on direction probabilities
                predicted_move = (prob_up - prob_down) * 2  # Simple estimate
                
                # Populate alert with AI data
                alert.ai_confidence = round(confidence, 1)
                alert.ai_prediction = direction
                alert.ai_predicted_move_pct = round(predicted_move, 2)
                alert.ai_model_version = prediction.get("model_version", "v1.0")
                
                # Check if AI agrees with alert direction
                alert_is_long = alert.direction.lower() in ["long", "buy", "bullish"]
                ai_is_bullish = direction.lower() in ["up", "bullish", "long"]
                
                if alert_is_long:
                    alert.ai_agrees_with_direction = ai_is_bullish
                else:
                    alert.ai_agrees_with_direction = not ai_is_bullish
                
                logger.debug(
                    f"AI for {alert.symbol}: {direction} ({confidence:.0f}% confidence), "
                    f"predicted move: {predicted_move:+.2f}%, "
                    f"agrees with {alert.direction}: {alert.ai_agrees_with_direction}"
                )
                
        except Exception as e:
            logger.warning(f"Could not get AI prediction for alert {alert.symbol}: {e}")
            # Leave AI fields at defaults
    
    def get_stats(self) -> Dict:
        # Get wave scanner info if available
        wave_info = {}
        try:
            from services.wave_scanner import get_wave_scanner
            wave_scanner = get_wave_scanner()
            wave_info = wave_scanner.get_stats()
        except:
            pass
        
        return {
            "running": self._running,
            "scan_count": self._scan_count,
            "alerts_generated": self._alerts_generated,
            "active_alerts": len(self._live_alerts),
            "watchlist_size": wave_info.get("universe_stats", {}).get("total_unique", len(self._watchlist)),
            "symbols_scanned_last": self._symbols_scanned_last,
            "symbols_skipped_adv": self._symbols_skipped_adv,
            "symbols_skipped_rvol": self._symbols_skipped_rvol,
            "scan_interval": self._scan_interval,
            "enabled_setups": list(self._enabled_setups),
            "market_regime": self._market_regime.value,
            "time_window": self._get_current_time_window().value,
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "auto_execute_enabled": self._auto_execute_enabled,
            "min_rvol_filter": self._min_rvol_filter,
            "min_adv_general": self._min_adv_general,
            "min_adv_intraday": self._min_adv_intraday,
            "adv_cache_size": len(self._adv_cache),
            "adv_cache_ttl_seconds": self._adv_cache_ttl,
            "wave_scanner": wave_info,
            # Whitelist and blacklist stats
            "known_liquid_symbols_count": len(self._known_liquid_symbols),
            "blacklisted_symbols_count": len(self._blacklisted_symbols),
        }


# Global instance
_enhanced_scanner: Optional[EnhancedBackgroundScanner] = None


def get_enhanced_scanner() -> EnhancedBackgroundScanner:
    global _enhanced_scanner
    if _enhanced_scanner is None:
        _enhanced_scanner = EnhancedBackgroundScanner()
    return _enhanced_scanner
