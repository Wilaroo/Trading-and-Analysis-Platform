"""
Autonomous Trading Bot Service
Scans for opportunities, evaluates trades, calculates position sizing,
executes trades, and manages open positions with full explanation logging.

Features:
- Real-time opportunity scanning using existing alert system
- Trade scoring and evaluation using TradingIntelligenceService
- Position sizing based on risk management rules
- Autonomous or confirmation-based trade execution
- Trade explanation generation for every decision
- P&L tracking and daily statistics
- Session persistence (trades, stats, config survive restarts)
- EOD auto-close (closes all positions at configurable time)
"""
import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
import json

logger = logging.getLogger(__name__)


class BotMode(str, Enum):
    """Bot operating mode"""
    AUTONOMOUS = "autonomous"      # Execute trades without confirmation
    CONFIRMATION = "confirmation"  # Require user approval before execution
    PAUSED = "paused"             # Don't scan or execute


class TradeStatus(str, Enum):
    """Status of a bot trade"""
    PENDING = "pending"           # Awaiting confirmation (in confirmation mode)
    OPEN = "open"                # Position is open
    PARTIAL = "partial"          # Partially filled or partially closed
    CLOSED = "closed"            # Position fully closed
    CANCELLED = "cancelled"      # Trade was cancelled before execution
    REJECTED = "rejected"        # Trade rejected by user or system


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeTimeframe(str, Enum):
    """Trade timeframe classification"""
    SCALP = "scalp"           # Minutes to 1 hour, close at EOD
    INTRADAY = "intraday"     # 1-4 hours, close at EOD
    SWING = "swing"           # 1-5 days, hold overnight
    POSITION = "position"     # Weeks to months, hold overnight


# Strategy-based configuration
STRATEGY_CONFIG = {
    # ==================== OPENING STRATEGIES ====================
    "first_vwap_pullback": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "opening_drive": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "first_move_up": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    "first_move_down": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    "bella_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    
    # ==================== MORNING MOMENTUM ====================
    "orb": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "orb_long": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "orb_short": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "hitchhiker": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],  # ONE AND DONE style
        "close_at_eod": True
    },
    "gap_give_go": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "gap_pick_roll": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== CORE SESSION ====================
    "spencer_scalp": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.33, 0.33, 0.34],  # 1R, 2R, 3R scale
        "close_at_eod": True
    },
    "second_chance": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "backside": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],  # ONE AND DONE
        "close_at_eod": True
    },
    "off_sides": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],  # ONE ATTEMPT ONLY
        "close_at_eod": True
    },
    "off_sides_short": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    "fashionably_late": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== MEAN REVERSION ====================
    "rubber_band": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "rubber_band_long": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "rubber_band_short": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_bounce": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_fade_long": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "vwap_fade_short": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "tidal_wave": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== CONSOLIDATION ====================
    "big_dog": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "puppy_dog": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "9_ema_scalp": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "abc_scalp": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    
    # ==================== AFTERNOON ====================
    "hod_breakout": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "time_of_day_fade": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.5],
        "close_at_eod": True
    },
    
    # ==================== SPECIAL ====================
    "breaking_news": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "volume_capitulation": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "range_break": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "range_break_long": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "breakout": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    
    # ==================== SWING/POSITION ====================
    "squeeze": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "trend_continuation": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "position_trade": {
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.03,
        "scale_out_pcts": [0.2, 0.3, 0.5],
        "close_at_eod": False
    }
}

# Default config for unknown setups
DEFAULT_STRATEGY_CONFIG = {
    "timeframe": TradeTimeframe.INTRADAY,
    "trail_pct": 0.02,
    "scale_out_pcts": [0.33, 0.33, 0.34],
    "close_at_eod": True
}


@dataclass
class RiskParameters:
    """Risk management parameters with volatility-adjusted sizing"""
    max_risk_per_trade: float = 2500.0      # Maximum $ risk per trade
    max_daily_loss_pct: float = 1.0          # Maximum daily loss as % of account (1% = stop trading)
    max_daily_loss: float = 0.0              # Calculated from account value (set dynamically)
    starting_capital: float = 100000.0       # Account capital for position sizing (updated from IB)
    max_position_pct: float = 50.0           # Maximum % of capital per position (user requested 50%)
    max_open_positions: int = 10             # Maximum concurrent positions (unlimited = high number)
    min_risk_reward: float = 0.8             # Minimum risk/reward ratio (lowered to allow more trades)
    max_slippage_pct: float = 0.5           # Maximum acceptable slippage %
    
    # Trading hours (Eastern Time)
    trading_start_hour: int = 7              # Start trading at 7:30 AM ET
    trading_start_minute: int = 30
    trading_end_hour: int = 17               # Stop trading at 5:00 PM ET
    trading_end_minute: int = 0
    
    # Volatility-adjusted position sizing
    use_volatility_sizing: bool = True       # Enable ATR-based position sizing
    base_atr_multiplier: float = 1.5         # Stop distance = ATR * multiplier
    volatility_scale_factor: float = 1.0     # Scale position size by volatility (1.0 = neutral)
    min_atr_multiplier: float = 1.0          # Minimum stop distance in ATRs
    max_atr_multiplier: float = 3.0          # Maximum stop distance in ATRs


@dataclass
class TradeExplanation:
    """Detailed explanation of trade logic"""
    summary: str
    setup_identified: str
    technical_reasons: List[str]
    fundamental_reasons: List[str]
    risk_analysis: Dict[str, Any]
    entry_logic: str
    exit_logic: str
    position_sizing_logic: str
    confidence_factors: List[str]
    warnings: List[str]
    ai_evaluation: str = ""
    ai_verdict: str = ""


@dataclass
class BotTrade:
    """Complete bot trade record"""
    id: str
    symbol: str
    direction: TradeDirection
    status: TradeStatus
    
    # Setup details
    setup_type: str
    timeframe: str
    quality_score: int
    quality_grade: str
    
    # Price levels (required fields before defaults)
    entry_price: float
    current_price: float
    stop_price: float
    target_prices: List[float]
    
    # Position details (required)
    shares: int
    risk_amount: float
    potential_reward: float
    risk_reward_ratio: float
    
    # SMB Integration fields (with defaults)
    trade_style: str = "trade_2_hold"  # "move_2_move", "trade_2_hold", "a_plus"
    smb_grade: str = "B"              # A+, A, B+, B, C, D
    tape_score: int = 5               # 1-10
    target_r_multiple: float = 2.0    # Target R based on trade style
    direction_bias: str = "both"      # Setup's primary direction
    
    # Scale-out tracking (with defaults)
    original_shares: int = 0  # Original position size before scale-outs
    remaining_shares: int = 0  # Shares still held after scale-outs
    scale_out_config: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "targets_hit": [],  # List of target indices that have been hit
        "scale_out_pcts": [0.33, 0.33, 0.34],  # Percentage to sell at each target
        "partial_exits": []  # List of {target_idx, shares_sold, price, pnl, timestamp}
    })
    
    # Trailing stop configuration
    trailing_stop_config: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "mode": "original",  # "original", "breakeven", "trailing"
        "original_stop": 0.0,  # Original stop price
        "current_stop": 0.0,   # Current effective stop price
        "trail_pct": 0.02,     # Trail by 2% from high (for longs) or low (for shorts)
        "trail_atr_mult": 1.5, # Alternative: trail by 1.5x ATR
        "high_water_mark": 0.0,  # Highest price since T2 hit (for longs)
        "low_water_mark": 0.0,   # Lowest price since T2 hit (for shorts)
        "stop_adjustments": []   # History of stop adjustments
    })
    
    # Execution details
    fill_price: Optional[float] = None
    exit_price: Optional[float] = None
    
    # P&L
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0  # Cumulative from all scale-outs + final exit
    pnl_pct: float = 0.0
    
    # Commission tracking (IB tiered: ~$0.005/share, $1.00 min per order)
    commission_per_share: float = 0.005
    commission_min: float = 1.00
    total_commissions: float = 0.0  # Running total of all commissions for this trade
    net_pnl: float = 0.0  # realized_pnl - total_commissions
    
    # Timing
    created_at: str = ""
    executed_at: Optional[str] = None
    closed_at: Optional[str] = None
    estimated_duration: str = ""  # e.g., "30min-2hr" for scalp
    
    # Close reason (manual, stop_loss, target_hit, target_1, target_2, target_3, eod_close, etc.)
    close_reason: Optional[str] = None
    
    # EOD close flag (from strategy config)
    close_at_eod: bool = True
    
    # Explanation
    explanation: Optional[TradeExplanation] = None
    
    # Notes for tracking (e.g., [SIMULATED], error messages, etc.)
    notes: Optional[str] = None
    
    # Market regime at time of trade entry
    market_regime: str = "UNKNOWN"  # RISK_ON, CAUTION, RISK_OFF, CONFIRMED_DOWN
    regime_score: float = 50.0      # Composite score at entry (0-100)
    regime_position_multiplier: float = 1.0  # Position size adjustment applied
    
    # Order IDs (from broker)
    entry_order_id: Optional[str] = None
    stop_order_id: Optional[str] = None
    target_order_ids: List[str] = field(default_factory=list)
    
    # === RICHER TRADE LOGGING ===
    
    # Pattern variant: granular SMB setup name (e.g., "spencer_scalp", "vwap_bounce")
    # while setup_type holds the broad AI category (e.g., "SCALP", "VWAP")
    setup_variant: str = ""
    
    # Entry context: signals and conditions that aligned for this trade
    entry_context: Dict[str, Any] = field(default_factory=dict)
    
    # MFE (Maximum Favorable Excursion) - best unrealized profit during trade
    mfe_price: float = 0.0    # Best favorable price since fill
    mfe_pct: float = 0.0      # MFE as % from entry
    mfe_r: float = 0.0        # MFE in R-multiples (relative to risk)
    
    # MAE (Maximum Adverse Excursion) - worst unrealized loss during trade
    mae_price: float = 0.0    # Worst adverse price since fill
    mae_pct: float = 0.0      # MAE as % from entry (always negative)
    mae_r: float = 0.0        # MAE in R-multiples (always negative)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        d = asdict(self)
        d['direction'] = self.direction.value if isinstance(self.direction, TradeDirection) else self.direction
        d['status'] = self.status.value if isinstance(self.status, TradeStatus) else self.status
        d['timeframe'] = self.timeframe
        d['close_at_eod'] = self.close_at_eod
        # Ensure regime fields are included
        d['market_regime'] = self.market_regime
        d['regime_score'] = self.regime_score
        d['regime_position_multiplier'] = self.regime_position_multiplier
        # Ensure richer logging fields are included
        d['setup_variant'] = self.setup_variant
        d['entry_context'] = self.entry_context
        d['mfe_price'] = self.mfe_price
        d['mfe_pct'] = self.mfe_pct
        d['mfe_r'] = self.mfe_r
        d['mae_price'] = self.mae_price
        d['mae_pct'] = self.mae_pct
        d['mae_r'] = self.mae_r
        d['total_commissions'] = self.total_commissions
        d['net_pnl'] = self.net_pnl
        return d


@dataclass
class DailyStats:
    """Daily trading statistics"""
    date: str
    trades_executed: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    win_rate: float = 0.0
    daily_limit_hit: bool = False


class TradingBotService:
    """
    Main trading bot service that orchestrates scanning, evaluation,
    execution, and position management.
    """
    
    def __init__(self):
        self._mode = BotMode.AUTONOMOUS  # Start in autonomous mode for auto-trading
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        
        # Risk parameters
        self.risk_params = RiskParameters()
        
        # State
        self._pending_trades: Dict[str, BotTrade] = {}
        self._open_trades: Dict[str, BotTrade] = {}
        self._closed_trades: List[BotTrade] = []
        self._daily_stats = DailyStats(date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        # Configuration - Enable all major strategies for autonomous trading
        self._enabled_setups = [
            # Opening strategies
            "first_vwap_pullback", "opening_drive", "first_move_up", "first_move_down", "bella_fade",
            # Morning momentum
            "orb", "orb_long", "orb_short", "hitchhiker", "gap_give_go", "gap_pick_roll",
            # Core session
            "spencer_scalp", "second_chance", "backside", "off_sides", "fashionably_late",
            # Mean reversion
            "rubber_band", "vwap_bounce", "vwap_fade", "tidal_wave",
            # Consolidation
            "big_dog", "puppy_dog", "nine_ema_scalp", "abc_scalp", "9_ema_scalp",
            # Afternoon
            "hod_breakout", "time_of_day_fade",
            # Special
            "breaking_news", "volume_capitulation", "range_break", "breakout",
            # New strategies
            "squeeze", "relative_strength", "relative_strength_leader", "relative_strength_laggard",
            "mean_reversion", "gap_fade", "chart_pattern"
        ]
        self._scan_interval = 30  # seconds - faster scanning for autonomous trading
        self._watchlist: List[str] = []
        
        # EOD Auto-Close Configuration
        self._eod_close_enabled = True
        self._eod_close_hour = 15  # 3 PM ET
        self._eod_close_minute = 57  # 3:57 PM ET
        self._eod_close_executed_today = False
        self._last_eod_check_date = None
        
        # Services (injected)
        self._alert_system = None
        self._trading_intelligence = None
        self._alpaca_service = None
        self._trade_executor = None
        self._db = None
        
        # Enhanced intelligence services (lazy loaded)
        self._web_research = None
        self._market_intelligence = None
        self._technical_service = None
        self._quality_service = None
        self._news_service = None
        
        # Learning Loop integration (Phase 1)
        self._learning_loop = None
        
        # Market Regime Engine integration
        self._market_regime_engine = None
        self._current_regime = "RISK_ON"  # Default to risk-on
        self._regime_position_multipliers = {
            "RISK_ON": 1.0,           # Full position sizing
            "CAUTION": 0.75,          # Reduce by 25%
            "RISK_OFF": 0.5,          # Reduce by 50%
            "CONFIRMED_DOWN": 0.25    # Reduce by 75% for longs, normal for shorts
        }
        
        # Regime Performance Tracking
        self._regime_performance_service = None
        
        # Trade Journal Service (auto-record trades)
        self._trade_journal = None
        
        # AI Trade Consultation (Phase 2 Integration)
        self._ai_consultation = None
        
        # Strategy Promotion Service (SIM → PAPER → LIVE lifecycle)
        self._strategy_promotion_service = None
        
        # Callbacks for real-time updates
        self._trade_callbacks: List[callable] = []
        
        # =====================================================================
        # SMART STRATEGY FILTERING - Win rate based trade filtering
        # =====================================================================
        # Stores recent "skipped trade" reasoning to show in Bot's Thoughts
        self._strategy_filter_thoughts: List[Dict] = []  # [{text, timestamp, symbol, setup_type, win_rate, action}]
        self._max_filter_thoughts = 20  # Keep last 20 filtered trade reasons
        
        # Enhanced scanner reference for strategy stats
        self._enhanced_scanner = None
        
        # AI Confidence Gate (pre-trade regime + model consensus check)
        self._confidence_gate = None
        
        # Smart filtering (delegated to SmartFilter module)
        from services.smart_filter import SmartFilter
        self._smart_filter = SmartFilter()
        self._smart_filter_config = self._smart_filter.config
        
        logger.info("TradingBotService initialized in AUTONOMOUS mode")
    
    def set_services(self, alert_system, trading_intelligence, alpaca_service, trade_executor, db):
        """Inject service dependencies"""
        self._alert_system = alert_system
        self._trading_intelligence = trading_intelligence
        self._alpaca_service = alpaca_service
        self._trade_executor = trade_executor
        self._db = db
        logger.info("TradingBotService services configured")
        
        # Restore bot state from database on startup
        asyncio.create_task(self._restore_state())
    
    def set_market_regime_engine(self, regime_engine):
        """Set market regime engine for regime-aware position sizing"""
        self._market_regime_engine = regime_engine
        logger.info("TradingBotService: Market Regime Engine connected")
    
    def set_regime_performance_service(self, performance_service):
        """Set regime performance service for trade logging"""
        self._regime_performance_service = performance_service
        logger.info("TradingBotService: Regime Performance Service connected")
    
    def set_enhanced_scanner(self, scanner):
        """Set enhanced scanner for strategy stats access (Smart Strategy Filtering)"""
        self._enhanced_scanner = scanner
        logger.info("TradingBotService: Enhanced Scanner connected for Smart Strategy Filtering")
    
    def set_trade_journal(self, journal_service):
        """Set trade journal service for auto-recording trades"""
        self._trade_journal = journal_service
        logger.info("TradingBotService: Trade Journal connected for auto-recording")
    
    def set_ai_consultation(self, ai_consultation):
        """
        Set AI Trade Consultation service for pre-trade analysis.
        
        When enabled, every trade runs through:
        - Bull/Bear Debate
        - AI Risk Manager
        - Institutional Flow analysis
        - Volume anomaly detection
        
        In Shadow Mode: AI analyzes and logs but doesn't block trades
        In Live Mode: AI can block or reduce trade sizes
        """
        self._ai_consultation = ai_consultation
        logger.info("TradingBotService: AI Trade Consultation connected")
        if ai_consultation:
            status = ai_consultation.get_status()
            logger.info(f"  - Shadow Mode: {status.get('shadow_mode', True)}")
            logger.info(f"  - Modules enabled: {status.get('modules_enabled', {})}")
    
    def set_strategy_promotion_service(self, promotion_service):
        """
        Set Strategy Promotion Service for SIM → PAPER → LIVE lifecycle management.
        
        When connected, the trading bot will:
        - Check each strategy's phase before executing trades
        - LIVE strategies: Execute real trades
        - PAPER strategies: Record paper trades (no real execution)
        - SIMULATION strategies: Skip real-time trading entirely
        """
        self._strategy_promotion_service = promotion_service
        logger.info("TradingBotService: Strategy Promotion Service connected")
        if promotion_service:
            phases = promotion_service.get_all_phases()
            live_count = sum(1 for p in phases.values() if p == "live")
            paper_count = sum(1 for p in phases.values() if p == "paper")
            logger.info(f"  - Tracking {len(phases)} strategies: {live_count} LIVE, {paper_count} PAPER")

    def set_confidence_gate(self, confidence_gate):
        """
        Set AI Confidence Gate for pre-trade regime + model consensus evaluation.

        Flow: Setup Detected → Smart Filter → **Confidence Gate** → Position Sizing → Execute
        
        The gate evaluates:
        - Current market regime (rule-based + AI)
        - Model consensus for this setup type
        - Returns GO / REDUCE / SKIP with position multiplier
        """
        self._confidence_gate = confidence_gate
        logger.info("TradingBotService: AI Confidence Gate connected")
        logger.info("  - Pre-trade flow: Smart Filter → Confidence Gate → Position Sizing → Execute")

    @staticmethod
    def _calculate_commission(shares: int, per_share: float = 0.005, minimum: float = 1.00) -> float:
        """
        Calculate commission for an order.
        IB Tiered: ~$0.005/share, $1.00 min, capped at 1% of trade value.
        """
        return max(minimum, round(shares * per_share, 2))

    def _apply_commission(self, trade, shares: int):
        """Add commission for an order (entry or exit) to the trade's running total."""
        commission = self._calculate_commission(shares, trade.commission_per_share, trade.commission_min)
        trade.total_commissions = round(trade.total_commissions + commission, 2)
        trade.net_pnl = round(trade.realized_pnl - trade.total_commissions, 2)
        return commission
    
    # ==================== SMART STRATEGY FILTERING ====================
    
    def get_strategy_historical_stats(self, setup_type: str) -> Dict[str, Any]:
        """
        Get user's historical performance stats for a specific setup type.
        Used for Smart Strategy Filtering - adjusts trade decisions based on past performance.
        
        Returns:
            dict with win_rate, sample_size, avg_r, expected_value, recommendation
        """
        if not self._enhanced_scanner:
            return {"available": False, "reason": "Scanner not connected"}
        
        try:
            # Get base setup type (remove _long/_short suffix for stats lookup)
            base_setup = setup_type.split("_long")[0].split("_short")[0]
            
            # Try to get stats from enhanced scanner
            stats = self._enhanced_scanner.get_strategy_stats(base_setup)
            
            if not stats:
                return {
                    "available": False,
                    "reason": "No historical data",
                    "setup_type": base_setup
                }
            
            sample_size = stats.get("alerts_triggered", 0) or stats.get("total_alerts", 0)
            win_rate = stats.get("win_rate", 0)
            avg_r = stats.get("avg_rr_achieved", 0)
            expected_value = stats.get("expected_value_r", 0)
            
            return {
                "available": True,
                "setup_type": base_setup,
                "win_rate": win_rate,
                "sample_size": sample_size,
                "avg_r": avg_r,
                "expected_value": expected_value,
                "profit_factor": stats.get("profit_factor", 0),
                "total_pnl": stats.get("total_pnl", 0),
                "wins": stats.get("alerts_won", 0),
                "losses": stats.get("alerts_lost", 0)
            }
            
        except Exception as e:
            logger.warning(f"Could not get strategy stats for {setup_type}: {e}")
            return {"available": False, "reason": str(e)}
    
    def _evaluate_strategy_filter(self, setup_type: str, quality_score: int, symbol: str) -> Dict[str, Any]:
        """
        Evaluate if a trade should be filtered based on historical performance.
        Delegates to the SmartFilter module for the actual decision logic.
        """
        stats = self.get_strategy_historical_stats(setup_type)
        return self._smart_filter.evaluate(setup_type, quality_score, symbol, stats)
    
    def _add_filter_thought(self, thought: Dict):
        """Add a strategy filter reasoning to the thoughts list"""
        self._smart_filter.add_thought(thought)
        # Also keep local reference for backward compat
        self._strategy_filter_thoughts = self._smart_filter.get_thoughts(self._max_filter_thoughts)
    
    def get_filter_thoughts(self, limit: int = 10) -> List[Dict]:
        """Get recent strategy filter thoughts for Bot's Brain display"""
        return self._smart_filter.get_thoughts(limit)
    
    def get_smart_filter_config(self) -> Dict:
        """Get current smart filter configuration"""
        return self._smart_filter.config
    
    def update_smart_filter_config(self, updates: Dict) -> Dict:
        """Update smart filter configuration"""
        result = self._smart_filter.update_config(updates)
        self._smart_filter_config = result
        return result
    
    async def _update_market_regime(self):
        """Fetch current market regime for position sizing adjustments"""
        if self._market_regime_engine is None:
            return
        
        try:
            regime_data = await self._market_regime_engine.get_current_regime()
            new_regime = regime_data.get("state", "RISK_ON")
            
            if new_regime != self._current_regime:
                old_regime = self._current_regime
                self._current_regime = new_regime
                multiplier = self._regime_position_multipliers.get(new_regime, 1.0)
                logger.info(f"🌡️ Market regime changed: {old_regime} -> {new_regime} (position multiplier: {multiplier}x)")
            
        except Exception as e:
            logger.warning(f"Could not fetch market regime: {e}")
    
    def _get_current_session(self) -> str:
        """Get current trading session (for AI consultation context)"""
        from datetime import time as dt_time
        now_utc = datetime.now(timezone.utc)
        # Convert to ET (rough approximation)
        et_hour = (now_utc.hour - 5) % 24
        
        if et_hour < 9 or (et_hour == 9 and now_utc.minute < 30):
            return "pre_market"
        elif et_hour >= 16:
            return "post_market"
        elif et_hour == 9 and now_utc.minute < 45:
            return "open"
        elif et_hour == 15 and now_utc.minute >= 30:
            return "power_hour"
        elif et_hour < 12:
            return "morning"
        elif et_hour < 15:
            return "afternoon"
        else:
            return "closing"
    
    async def _get_account_value(self) -> float:
        """Get current account value from Alpaca"""
        try:
            if self._alpaca_service:
                account = await self._alpaca_service.get_account()
                return float(account.get("portfolio_value", 100000)) if account else 100000
        except Exception as e:
            logger.warning(f"Could not get account value: {e}")
        return 100000  # Default fallback
    
    async def _restore_state(self):
        """Restore bot state from MongoDB on startup - COMPREHENSIVE SESSION PERSISTENCE"""
        try:
            if self._db is None:
                return
            
            # === 1. RESTORE BOT STATE ===
            state = await asyncio.to_thread(self._db.bot_state.find_one, {"_id": "bot_state"})
            if state:
                was_running = state.get("running", False)
                saved_mode = state.get("mode", "confirmation")
                saved_watchlist = state.get("watchlist", [])
                saved_setups = state.get("enabled_setups", [])
                saved_risk_params = state.get("risk_params", {})
                
                # Restore mode - but prefer AUTONOMOUS if that's the default
                if saved_mode in ["autonomous", "confirmation", "paused"]:
                    self._mode = BotMode(saved_mode)
                
                # Restore watchlist
                if saved_watchlist:
                    self._watchlist = saved_watchlist
                    logger.info(f"📋 Restored watchlist: {', '.join(saved_watchlist[:5])}{'...' if len(saved_watchlist) > 5 else ''}")
                
                # Restore enabled setups only if more than defaults were saved
                if saved_setups and len(saved_setups) > 10:
                    self._enabled_setups = saved_setups
                    logger.info(f"🎯 Restored {len(saved_setups)} strategies")
                else:
                    logger.info(f"🎯 Using default {len(self._enabled_setups)} strategies")
                
                # Restore risk parameters
                if saved_risk_params:
                    if "max_risk_per_trade" in saved_risk_params:
                        self.risk_params.max_risk_per_trade = saved_risk_params["max_risk_per_trade"]
                    if "max_daily_loss" in saved_risk_params:
                        self.risk_params.max_daily_loss = saved_risk_params["max_daily_loss"]
                    if "max_daily_loss_pct" in saved_risk_params:
                        self.risk_params.max_daily_loss_pct = saved_risk_params["max_daily_loss_pct"]
                    if "max_open_positions" in saved_risk_params:
                        self.risk_params.max_open_positions = saved_risk_params["max_open_positions"]
                    if "max_position_pct" in saved_risk_params:
                        self.risk_params.max_position_pct = saved_risk_params["max_position_pct"]
                    if "min_risk_reward" in saved_risk_params:
                        self.risk_params.min_risk_reward = saved_risk_params["min_risk_reward"]
                    if "starting_capital" in saved_risk_params:
                        self.risk_params.starting_capital = saved_risk_params["starting_capital"]
                    logger.info(f"💰 Restored risk params: max_risk=${self.risk_params.max_risk_per_trade:,.0f}, max_positions={self.risk_params.max_open_positions}, min_rr={self.risk_params.min_risk_reward}")
            
            # === 2. RESTORE EOD CONFIG ===
            eod_config = await asyncio.to_thread(self._db.bot_config.find_one, {"_id": "eod_config"})
            if eod_config:
                self._eod_close_enabled = eod_config.get("enabled", True)
                self._eod_close_hour = eod_config.get("close_hour", 15)
                self._eod_close_minute = eod_config.get("close_minute", 57)
                logger.info(f"⏰ Restored EOD config: {self._eod_close_hour}:{self._eod_close_minute:02d} PM ET, enabled={self._eod_close_enabled}")
            
            # === 3. RESTORE DAILY STATS ===
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily_stats = await asyncio.to_thread(self._db.daily_stats.find_one, {"date": today_str})
            if daily_stats:
                self._daily_stats = DailyStats(
                    date=today_str,
                    trades_executed=daily_stats.get("trades_executed", 0),
                    trades_won=daily_stats.get("trades_won", 0),
                    trades_lost=daily_stats.get("trades_lost", 0),
                    gross_pnl=daily_stats.get("gross_pnl", 0.0),
                    net_pnl=daily_stats.get("net_pnl", 0.0),
                    largest_win=daily_stats.get("largest_win", 0.0),
                    largest_loss=daily_stats.get("largest_loss", 0.0),
                    win_rate=daily_stats.get("win_rate", 0.0),
                    daily_limit_hit=daily_stats.get("daily_limit_hit", False)
                )
                logger.info(f"📊 Restored daily stats: P&L=${self._daily_stats.net_pnl:+,.2f}, Trades={self._daily_stats.trades_executed}")
            
            # === 4. RESTORE OPEN TRADES ===
            await self._restore_open_trades()
            
            # === 5. RESTORE CLOSED TRADES (recent) ===
            await self._restore_closed_trades()
            
            # === 6. AUTO-RESTART if bot was running ===
            if state and state.get("running", False):
                logger.info("🔄 Bot was running before restart - auto-resuming...")
                await self.start()
            
            logger.info(f"✅ Session restored: mode={self._mode.value}, running={self._running}, open_trades={len(self._open_trades)}, closed_trades={len(self._closed_trades)}")
            
        except Exception as e:
            logger.warning(f"Could not restore bot state: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    async def _restore_closed_trades(self):
        """Restore recent closed trades for history display"""
        try:
            if self._db is None:
                return
            
            # Restore last 100 closed trades
            closed_trades = await asyncio.to_thread(
                lambda: list(self._db.bot_trades.find({"status": "closed"}).sort("closed_at", -1).limit(100))
            )
            
            for trade_doc in closed_trades:
                try:
                    # Create trade object from stored data
                    direction = trade_doc.get("direction", "long")
                    if isinstance(direction, str):
                        direction = TradeDirection.LONG if direction.lower() == "long" else TradeDirection.SHORT
                    
                    trade = BotTrade(
                        id=trade_doc.get("id", str(uuid.uuid4())[:8]),
                        symbol=trade_doc.get("symbol", "UNKNOWN"),
                        direction=direction,
                        status=TradeStatus.CLOSED,
                        setup_type=trade_doc.get("setup_type", "unknown"),
                        timeframe=trade_doc.get("timeframe", "daily"),
                        quality_score=trade_doc.get("quality_score", 50),
                        quality_grade=trade_doc.get("quality_grade", "B"),
                        entry_price=trade_doc.get("entry_price", 0),
                        current_price=trade_doc.get("exit_price", trade_doc.get("entry_price", 0)),
                        stop_price=trade_doc.get("stop_price", 0),
                        target_prices=trade_doc.get("target_prices", []),
                        shares=trade_doc.get("shares", 0),
                        risk_amount=trade_doc.get("risk_amount", 0),
                        potential_reward=trade_doc.get("potential_reward", 0),
                        risk_reward_ratio=trade_doc.get("risk_reward_ratio", 0)
                    )
                    trade.fill_price = trade_doc.get("fill_price", trade_doc.get("entry_price", 0))
                    trade.exit_price = trade_doc.get("exit_price", 0)
                    trade.realized_pnl = trade_doc.get("realized_pnl", 0)
                    trade.close_reason = trade_doc.get("close_reason", trade_doc.get("exit_reason", "unknown"))
                    trade.closed_at = trade_doc.get("closed_at")
                    
                    self._closed_trades.append(trade)
                except Exception as e:
                    logger.debug(f"Could not restore closed trade: {e}")
            
            if self._closed_trades:
                logger.info(f"📚 Restored {len(self._closed_trades)} closed trades from history")
                
        except Exception as e:
            logger.warning(f"Could not restore closed trades: {e}")
    
    async def _restore_open_trades(self):
        """Restore open trades from database - CRITICAL for persistence across restarts"""
        try:
            if self._db is None:
                return
            
            # Find all trades with open or pending status
            open_trades = await asyncio.to_thread(
                lambda: list(self._db.bot_trades.find({"status": {"$in": ["open", "pending", "filled"]}}))
            )
            
            restored_count = 0
            for trade_doc in open_trades:
                try:
                    # Get all required fields with defaults for missing data
                    symbol = trade_doc.get("symbol", "UNKNOWN")
                    entry_price = trade_doc.get("entry_price", 0) or trade_doc.get("fill_price", 0)
                    stop_price = trade_doc.get("stop_price", 0)
                    target_prices = trade_doc.get("target_prices", [entry_price * 1.02])
                    shares = trade_doc.get("shares", 0)
                    risk_amount = trade_doc.get("risk_amount", 0)
                    
                    # Calculate missing fields
                    if not target_prices:
                        target_prices = [entry_price * 1.02, entry_price * 1.05]
                    
                    risk_per_share = abs(entry_price - stop_price) if stop_price else entry_price * 0.02
                    if risk_amount == 0:
                        risk_amount = risk_per_share * shares
                    
                    reward_per_share = abs(target_prices[0] - entry_price) if target_prices else entry_price * 0.04
                    potential_reward = reward_per_share * shares
                    risk_reward_ratio = (reward_per_share / risk_per_share) if risk_per_share > 0 else 2.0
                    
                    # Reconstruct BotTrade object with ALL required fields
                    trade = BotTrade(
                        id=str(trade_doc.get("id", trade_doc.get("_id", str(uuid.uuid4())))),
                        symbol=symbol,
                        direction=TradeDirection(trade_doc.get("direction", "long")),
                        status=TradeStatus(trade_doc.get("status", "open")),
                        setup_type=trade_doc.get("setup_type", "restored"),
                        timeframe=trade_doc.get("timeframe", "intraday"),
                        quality_score=trade_doc.get("quality_score", 70),
                        quality_grade=trade_doc.get("quality_grade", "B"),
                        entry_price=entry_price,
                        current_price=trade_doc.get("current_price", entry_price),
                        stop_price=stop_price,
                        target_prices=target_prices,
                        shares=shares,
                        risk_amount=risk_amount,
                        potential_reward=potential_reward,
                        risk_reward_ratio=risk_reward_ratio
                    )
                    
                    # Restore optional fields via direct assignment
                    trade.fill_price = trade_doc.get("fill_price", entry_price)
                    trade.executed_at = trade_doc.get("executed_at")
                    trade.entry_order_id = trade_doc.get("entry_order_id")
                    trade.stop_order_id = trade_doc.get("stop_order_id")
                    trade.notes = trade_doc.get("notes", "") or trade_doc.get("rationale", "")
                    trade.market_regime = trade_doc.get("market_regime", "UNKNOWN")
                    trade.regime_score = trade_doc.get("regime_score", 50.0)
                    
                    # Restore trailing stop config
                    if trade_doc.get("trailing_stop_config"):
                        trade.trailing_stop_config = trade_doc["trailing_stop_config"]
                    else:
                        # Initialize trailing stop with current stop
                        trade.trailing_stop_config["current_stop"] = stop_price
                        trade.trailing_stop_config["original_stop"] = stop_price
                    
                    # Restore richer trade logging fields
                    trade.setup_variant = trade_doc.get("setup_variant", "")
                    trade.entry_context = trade_doc.get("entry_context", {})
                    trade.mfe_price = trade_doc.get("mfe_price", trade.fill_price)
                    trade.mfe_pct = trade_doc.get("mfe_pct", 0.0)
                    trade.mfe_r = trade_doc.get("mfe_r", 0.0)
                    trade.mae_price = trade_doc.get("mae_price", trade.fill_price)
                    trade.mae_pct = trade_doc.get("mae_pct", 0.0)
                    trade.mae_r = trade_doc.get("mae_r", 0.0)
                    
                    # Add to appropriate dict
                    if trade.status == TradeStatus.PENDING:
                        self._pending_trades[trade.id] = trade
                    else:
                        self._open_trades[trade.id] = trade
                    
                    restored_count += 1
                    logger.info(f"📥 Restored trade: {trade.symbol} {trade.direction.value} {trade.shares} shares @ ${trade.fill_price:.2f}, stop=${trade.stop_price:.2f}")
                    
                except Exception as e:
                    logger.warning(f"Failed to restore trade {trade_doc.get('symbol')}: {e}")
            
            if restored_count > 0:
                logger.info(f"✅ Restored {restored_count} open trades from database")
            else:
                logger.info("📭 No open trades to restore from database")
            
            # Schedule position reconciliation after a short delay (allow IB pusher to connect)
            # This ensures our restored state matches actual IB positions
            asyncio.create_task(self._delayed_reconciliation())
                
        except Exception as e:
            logger.warning(f"Could not restore open trades: {e}")
    
    async def _delayed_reconciliation(self):
        """Run position reconciliation after startup delay to allow IB connection"""
        try:
            # Wait for IB pusher to potentially connect
            await asyncio.sleep(10)
            
            from routers.ib import is_pusher_connected
            if is_pusher_connected():
                logger.info("🔄 Running startup position reconciliation...")
                report = await self.reconcile_positions_with_ib()
                
                if report.get("discrepancies"):
                    disc_count = len(report["discrepancies"])
                    logger.warning(f"⚠️ Found {disc_count} position discrepancies on startup!")
                    for d in report["discrepancies"]:
                        logger.warning(f"   - {d['message']}")
                    logger.info("💡 Run /api/trading-bot/positions/sync-all to auto-fix discrepancies")
                else:
                    logger.info("✅ Position reconciliation: All positions in sync with IB")
            else:
                logger.info("⏳ IB pusher not connected - skipping startup reconciliation")
        except Exception as e:
            logger.debug(f"Startup reconciliation skipped: {e}")
    
    async def _save_state(self):
        """Save bot state to MongoDB - COMPREHENSIVE SESSION PERSISTENCE"""
        try:
            if self._db is None:
                return
            
            # Build state and stats documents first (lightweight, no IO)
            state_doc = {
                "running": self._running,
                "mode": self._mode.value,
                "watchlist": self._watchlist,
                "enabled_setups": self._enabled_setups,
                "risk_params": {
                    "max_risk_per_trade": self.risk_params.max_risk_per_trade,
                    "max_daily_loss": self.risk_params.max_daily_loss,
                    "max_daily_loss_pct": self.risk_params.max_daily_loss_pct,
                    "max_open_positions": self.risk_params.max_open_positions,
                    "max_position_pct": self.risk_params.max_position_pct,
                    "min_risk_reward": self.risk_params.min_risk_reward,
                    "starting_capital": self.risk_params.starting_capital
                },
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            stats_doc = {
                "trades_executed": self._daily_stats.trades_executed,
                "trades_won": self._daily_stats.trades_won,
                "trades_lost": self._daily_stats.trades_lost,
                "gross_pnl": self._daily_stats.gross_pnl,
                "net_pnl": self._daily_stats.net_pnl,
                "largest_win": self._daily_stats.largest_win,
                "largest_loss": self._daily_stats.largest_loss,
                "win_rate": self._daily_stats.win_rate,
                "daily_limit_hit": self._daily_stats.daily_limit_hit,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            stats_date = self._daily_stats.date

            # Run all DB writes in a thread to avoid blocking
            def _sync_save():
                self._db.bot_state.update_one(
                    {"_id": "bot_state"}, {"$set": state_doc}, upsert=True
                )
                self._db.daily_stats.update_one(
                    {"date": stats_date}, {"$set": stats_doc}, upsert=True
                )
                self._persist_all_open_trades()

            await asyncio.to_thread(_sync_save)
            
            logger.info(f"💾 Session saved: running={self._running}, P&L=${self._daily_stats.net_pnl:+,.2f}, open_trades={len(self._open_trades)}")
        except Exception as e:
            logger.warning(f"Could not save bot state: {e}")
    
    def _persist_trade(self, trade: 'BotTrade'):
        """
        Persist a single trade to MongoDB.
        Called whenever a trade's state changes (created, filled, updated, closed).
        This is CRITICAL for data consistency and session persistence.
        """
        if self._db is None:
            logger.warning("Cannot persist trade - no database connection")
            return
        
        try:
            trade_dict = trade.to_dict()
            
            # Ensure status is stored as string value
            if isinstance(trade_dict.get("status"), TradeStatus):
                trade_dict["status"] = trade_dict["status"].value
            if isinstance(trade_dict.get("direction"), TradeDirection):
                trade_dict["direction"] = trade_dict["direction"].value
            
            # Add metadata
            trade_dict["last_updated"] = datetime.now(timezone.utc).isoformat()
            
            # Upsert to MongoDB
            self._db.bot_trades.update_one(
                {"id": trade.id},
                {"$set": trade_dict},
                upsert=True
            )
            
            logger.debug(f"💾 Trade persisted: {trade.symbol} ({trade.id}) status={trade.status.value if hasattr(trade.status, 'value') else trade.status}")
            
        except Exception as e:
            logger.error(f"Failed to persist trade {trade.id}: {e}")
    
    def _persist_all_open_trades(self):
        """Persist all open trades - call this periodically or on shutdown"""
        if self._db is None:
            return
        
        for trade in self._open_trades.values():
            self._persist_trade(trade)
        
        logger.info(f"💾 Persisted {len(self._open_trades)} open trades")
    
    # ==================== INTELLIGENCE SERVICE PROPERTIES ====================
    
    @property
    def web_research(self):
        """Lazy load web research service"""
        if self._web_research is None:
            try:
                from services.web_research_service import get_web_research_service
                self._web_research = get_web_research_service()
            except Exception as e:
                logger.warning(f"Web research service not available: {e}")
        return self._web_research
    
    @property
    def market_intelligence(self):
        """Lazy load market intelligence service"""
        if self._market_intelligence is None:
            try:
                from services.ai_market_intelligence import get_ai_market_intelligence
                self._market_intelligence = get_ai_market_intelligence()
            except Exception as e:
                logger.warning(f"Market intelligence service not available: {e}")
        return self._market_intelligence
    
    @property
    def technical_service(self):
        """Lazy load technical analysis service"""
        if self._technical_service is None:
            try:
                from services.realtime_technical_service import get_technical_service
                self._technical_service = get_technical_service()
            except Exception as e:
                logger.warning(f"Technical service not available: {e}")
        return self._technical_service
    
    @property
    def quality_service(self):
        """Lazy load quality scoring service"""
        if self._quality_service is None:
            try:
                from services.quality_service import get_quality_service
                self._quality_service = get_quality_service()
            except Exception as e:
                logger.warning(f"Quality service not available: {e}")
        return self._quality_service
    
    @property
    def news_service(self):
        """Lazy load news service"""
        if self._news_service is None:
            try:
                from services.news_service import get_news_service
                self._news_service = get_news_service()
            except Exception as e:
                logger.warning(f"News service not available: {e}")
        return self._news_service
    
    def add_trade_callback(self, callback: callable):
        """Add callback for trade updates"""
        self._trade_callbacks.append(callback)
    
    async def _notify_trade_update(self, trade: BotTrade, event_type: str):
        """Notify callbacks of trade updates"""
        for callback in self._trade_callbacks:
            try:
                await callback(trade, event_type)
            except Exception as e:
                logger.error(f"Trade callback error: {e}")
    
    # ==================== CONFIGURATION ====================
    
    def set_mode(self, mode: BotMode):
        """Set operating mode"""
        self._mode = mode
        logger.info(f"Bot mode changed to: {mode.value}")
        # Persist state asynchronously
        asyncio.create_task(self._save_state())
    
    def get_mode(self) -> BotMode:
        return self._mode
    
    def update_risk_params(self, **kwargs):
        """Update risk parameters and persist to MongoDB"""
        for key, value in kwargs.items():
            if hasattr(self.risk_params, key):
                setattr(self.risk_params, key, value)
                logger.info(f"Risk param updated: {key} = {value}")
        
        # Persist state after updating risk params
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save_state())
            else:
                loop.run_until_complete(self._save_state())
        except Exception:
            pass  # State will be saved on next start/stop
    
    def set_watchlist(self, symbols: List[str]):
        """Set symbols to scan"""
        self._watchlist = [s.upper() for s in symbols]
        # Schedule state save (non-blocking)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save_state())
            else:
                loop.run_until_complete(self._save_state())
        except Exception:
            pass  # State will be saved on next start/stop
    
    def set_enabled_setups(self, setups: List[str]):
        """Set which setup types to trade"""
        self._enabled_setups = setups
        # Schedule state save (non-blocking)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._save_state())
            else:
                loop.run_until_complete(self._save_state())
        except Exception:
            pass  # State will be saved on next start/stop
    
    def get_strategy_configs(self) -> Dict[str, Any]:
        """Get all strategy configurations"""
        result = {}
        for key, config in STRATEGY_CONFIG.items():
            result[key] = {
                "timeframe": config["timeframe"].value if isinstance(config["timeframe"], TradeTimeframe) else config["timeframe"],
                "trail_pct": config["trail_pct"],
                "scale_out_pcts": config["scale_out_pcts"],
                "close_at_eod": config["close_at_eod"]
            }
        return result
    
    def update_strategy_config(self, strategy: str, updates: Dict[str, Any]) -> bool:
        """Update a specific strategy configuration"""
        if strategy not in STRATEGY_CONFIG:
            return False
        config = STRATEGY_CONFIG[strategy]
        if "trail_pct" in updates:
            config["trail_pct"] = float(updates["trail_pct"])
        if "close_at_eod" in updates:
            config["close_at_eod"] = bool(updates["close_at_eod"])
        if "scale_out_pcts" in updates:
            pcts = updates["scale_out_pcts"]
            if isinstance(pcts, list) and len(pcts) >= 2:
                config["scale_out_pcts"] = [float(p) for p in pcts]
        if "timeframe" in updates:
            try:
                config["timeframe"] = TradeTimeframe(updates["timeframe"])
            except ValueError:
                pass
        logger.info(f"Strategy config updated: {strategy} -> {config}")
        return True
    
    def get_bot_context_for_ai(self) -> str:
        """Build a context string about bot state for the AI assistant"""
        lines = []
        lines.append("=== TRADING BOT STATUS ===")
        lines.append(f"Running: {self._running} | Mode: {self._mode.value}")
        lines.append(f"Capital: ${self.risk_params.starting_capital:,.0f} | Max Risk/Trade: ${self.risk_params.max_risk_per_trade:,.0f}")
        
        # Daily stats
        ds = self._daily_stats
        lines.append(f"\nToday's Stats: {ds.trades_executed} trades | {ds.trades_won}W/{ds.trades_lost}L | P&L: ${ds.gross_pnl:+,.2f}")
        if ds.trades_executed > 0:
            lines.append(f"Win Rate: {ds.win_rate:.0f}%")
        
        # Pending trades
        if self._pending_trades:
            lines.append(f"\nPENDING TRADES ({len(self._pending_trades)}):")
            for t in self._pending_trades.values():
                lines.append(f"  {t.symbol} {t.direction.value.upper()} | {t.setup_type} ({t.timeframe}) | Entry: ${t.entry_price:.2f} | Stop: ${t.stop_price:.2f} | R:R {t.risk_reward_ratio:.1f}:1 | Grade: {t.quality_grade}")
        
        # Open trades
        if self._open_trades:
            lines.append(f"\nOPEN TRADES ({len(self._open_trades)}):")
            for t in self._open_trades.values():
                pnl_str = f"${t.unrealized_pnl:+,.2f}" if t.unrealized_pnl else "N/A"
                lines.append(f"  {t.symbol} {t.direction.value.upper()} | {t.setup_type} ({t.timeframe}) | Entry: ${t.entry_price:.2f} | Current: ${t.current_price:.2f} | P&L: {pnl_str} | EOD Close: {t.close_at_eod}")
        
        # Closed trades (last 10)
        if self._closed_trades:
            recent_closed = self._closed_trades[-10:]
            lines.append(f"\nRECENT CLOSED TRADES ({len(self._closed_trades)} total, showing last {len(recent_closed)}):")
            for t in reversed(recent_closed):
                lines.append(f"  {t.symbol} {t.direction.value.upper()} | {t.setup_type} ({t.timeframe}) | P&L: ${t.realized_pnl:+,.2f} ({t.pnl_pct:+.1f}%) | Reason: {t.close_reason or 'N/A'}")
        
        # Strategy configs summary
        lines.append("\nSTRATEGY CONFIGS:")
        for key, cfg in STRATEGY_CONFIG.items():
            tf = cfg["timeframe"].value if isinstance(cfg["timeframe"], TradeTimeframe) else cfg["timeframe"]
            lines.append(f"  {key}: {tf} | trail {cfg['trail_pct']*100:.1f}% | EOD close: {cfg['close_at_eod']}")
        
        return "\n".join(lines)
    
    def get_all_trades_summary(self) -> Dict:
        """Get all trades for the AI Command Panel"""
        pending = [t.to_dict() for t in self._pending_trades.values()]
        open_trades = [t.to_dict() for t in self._open_trades.values()]
        closed = [t.to_dict() for t in self._closed_trades]
        return {
            "pending": pending,
            "open": open_trades,
            "closed": closed,
            "daily_stats": asdict(self._daily_stats)
        }
    
    # ==================== BOT CONTROL ====================
    
    def is_within_trading_hours(self) -> bool:
        """Check if current time is within allowed trading hours (Eastern Time)"""
        try:
            from datetime import timezone
            import pytz
            
            et_tz = pytz.timezone('America/New_York')
            now_et = datetime.now(et_tz)
            
            start_time = now_et.replace(
                hour=self.risk_params.trading_start_hour,
                minute=self.risk_params.trading_start_minute,
                second=0,
                microsecond=0
            )
            end_time = now_et.replace(
                hour=self.risk_params.trading_end_hour,
                minute=self.risk_params.trading_end_minute,
                second=0,
                microsecond=0
            )
            
            # Check if it's a weekday (Monday=0, Sunday=6)
            if now_et.weekday() >= 5:  # Saturday or Sunday
                return False
            
            return start_time <= now_et <= end_time
        except Exception as e:
            logger.warning(f"Error checking trading hours: {e}")
            return True  # Default to allowing trades if timezone check fails
    
    def update_account_value_from_ib(self, account_value: float):
        """Update risk parameters based on current account value from IB"""
        if account_value > 0:
            self.risk_params.starting_capital = account_value
            # Calculate max daily loss as 1% of account
            self.risk_params.max_daily_loss = account_value * (self.risk_params.max_daily_loss_pct / 100.0)
            logger.info(f"Updated account value: ${account_value:,.2f}, max daily loss: ${self.risk_params.max_daily_loss:,.2f}")
    
    async def start(self):
        """Start the trading bot"""
        if self._running:
            return
        
        self._running = True
        self._mode = BotMode.AUTONOMOUS if self._mode == BotMode.PAUSED else self._mode
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(f"🤖 Trading bot started in {self._mode.value} mode")
        logger.info(f"📊 Trading hours: {self.risk_params.trading_start_hour}:{self.risk_params.trading_start_minute:02d} - {self.risk_params.trading_end_hour}:{self.risk_params.trading_end_minute:02d} ET")
        logger.info(f"💰 Max position: {self.risk_params.max_position_pct}% of account, Max daily loss: {self.risk_params.max_daily_loss_pct}%")
        
        # Persist state
        await self._save_state()
    
    async def stop(self):
        """Stop the trading bot"""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        logger.info("Trading bot stopped")
        
        # Persist state
        await self._save_state()
    
    async def _scan_loop(self):
        """Main scanning loop - runs when bot is active"""
        scan_count = 0
        print(f"🤖 [TradingBot] Scan loop started - interval: {self._scan_interval}s")
        while self._running:
            try:
                # Update account value from IB if connected
                await self._update_account_from_ib()
                
                # Check daily loss limit (1% of account)
                if self.risk_params.max_daily_loss > 0 and self._daily_stats.net_pnl <= -self.risk_params.max_daily_loss:
                    if not self._daily_stats.daily_limit_hit:
                        self._daily_stats.daily_limit_hit = True
                        print(f"🛑 [TradingBot] Daily loss limit hit: ${self._daily_stats.net_pnl:.2f}")
                    await asyncio.sleep(60)
                    continue
                
                # Check trading hours (7:30 AM - 5:00 PM ET)
                if not self.is_within_trading_hours():
                    if scan_count % 60 == 0:  # Log every ~30 min
                        print("⏰ [TradingBot] Outside trading hours (7:30 AM - 5:00 PM ET)")
                    await asyncio.sleep(self._scan_interval)
                    scan_count += 1
                    continue
                
                # Skip if paused
                if self._mode == BotMode.PAUSED:
                    await asyncio.sleep(self._scan_interval)
                    continue
                
                # Log scan activity periodically
                scan_count += 1
                if scan_count % 10 == 1:  # Log every 10th scan (~5 min)
                    mode_str = "🟢 AUTO" if self._mode == BotMode.AUTONOMOUS else "🟡 CONFIRM"
                    open_count = len(self._open_trades)
                    pending_count = len(self._pending_trades)
                    pnl_str = f"${self._daily_stats.net_pnl:+,.2f}" if self._daily_stats.net_pnl != 0 else "$0"
                    print(f"[TradingBot] Scan #{scan_count} | {mode_str} | Open: {open_count} | Pending: {pending_count} | P&L: {pnl_str}")
                
                # Scan for opportunities
                await self._scan_for_opportunities()
                
                # Update open positions
                await self._update_open_positions()
                
                # Check for EOD close on scalp/intraday trades
                await self._check_eod_close()
                
            except Exception as e:
                print(f"❌ [TradingBot] Scan loop error: {e}")
            
            await asyncio.sleep(self._scan_interval)
    
    async def _update_account_from_ib(self):
        """Update account value from IB pushed data"""
        try:
            import routers.ib as ib_module
            ib_data = ib_module.get_pushed_data()
            if ib_data.get("connected"):
                account = ib_data.get("account", {})
                # Try to get NetLiquidation from account data (handles nested dict format)
                net_liq_data = account.get("NetLiquidation-S") or account.get("NetLiquidation")
                if net_liq_data:
                    try:
                        # Handle nested dict format: {"value": "997162.22", "currency": "USD", ...}
                        if isinstance(net_liq_data, dict):
                            value = float(net_liq_data.get("value", 0))
                        else:
                            value = float(net_liq_data)
                        
                        if value > 0 and abs(value - self.risk_params.starting_capital) > 100:  # Only update if changed by more than $100
                            self.update_account_value_from_ib(value)
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Could not parse NetLiquidation: {e}")
        except Exception as e:
            logger.debug(f"Could not update account from IB: {e}")
    
    # ==================== OPPORTUNITY SCANNING ====================
    
    async def _scan_for_opportunities(self):
        """Scan for trade opportunities using alert system"""
        if not self._alert_system:
            print("⚠️ [TradingBot] No alert system configured - skipping scan")
            return
        
        # Check max open positions
        if len(self._open_trades) >= self.risk_params.max_open_positions:
            return
        
        try:
            # Get alerts from existing system
            alerts = await self._get_trade_alerts()
            
            if alerts:
                print(f"📡 [TradingBot] Found {len(alerts)} eligible alerts to evaluate")
            
            for alert in alerts:
                symbol = alert.get('symbol', 'UNKNOWN')
                setup = alert.get('setup_type', 'unknown')
                
                # Skip if already have position in this symbol
                if any(t.symbol == alert.get('symbol') for t in self._open_trades.values()):
                    continue
                
                # Skip if pending trade exists
                if any(t.symbol == alert.get('symbol') for t in self._pending_trades.values()):
                    continue
                
                # Evaluate and create trade opportunity
                print(f"🔍 [TradingBot] Evaluating {symbol} {setup}...")
                trade = await self._evaluate_opportunity(alert)
                
                # Yield to event loop to prevent blocking (keeps WebSocket alive)
                await asyncio.sleep(0)
                
                if trade:
                    print(f"✅ [TradingBot] Trade created for {symbol}: {trade.direction.value} {trade.shares} shares @ ${trade.entry_price:.2f}")
                    if self._mode == BotMode.AUTONOMOUS:
                        # Execute immediately
                        print(f"🚀 [TradingBot] AUTONOMOUS MODE: Executing {symbol} trade...")
                        await self._execute_trade(trade)
                    else:
                        # Add to pending for confirmation
                        self._pending_trades[trade.id] = trade
                        await self._notify_trade_update(trade, "pending")
                        print(f"⏸️ [TradingBot] Added {symbol} to pending trades")
                else:
                    print(f"❌ [TradingBot] {symbol} {setup} did not meet criteria")
                    
        except Exception as e:
            print(f"❌ [TradingBot] Scan error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _get_trade_alerts(self) -> List[Dict]:
        """Get trade alerts from enhanced scanner"""
        alerts = []
        
        try:
            # Use enhanced scanner (primary) - same instance as live scanner API
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            
            # Get current live alerts
            scanner_alerts = scanner.get_live_alerts()
            print(f"📊 [TradingBot] Scanner ID: {id(scanner)}, has {len(scanner_alerts)} raw alerts, running: {scanner._running}")
            
            # Debug: show live alerts dict size
            print(f"   Live alerts dict size: {len(scanner._live_alerts)}")
            
            for alert in scanner_alerts:
                # Convert LiveAlert to dict format for trading bot
                alert_dict = {
                    'symbol': alert.symbol,
                    'setup_type': alert.setup_type,
                    'direction': alert.direction,
                    'current_price': alert.current_price,
                    'trigger_price': alert.trigger_price,
                    'stop_price': alert.stop_loss,
                    'targets': [alert.target] if alert.target else [],
                    'score': int((alert.trigger_probability or 0.5) * 100),
                    'trigger_probability': alert.trigger_probability or 0.5,
                    'headline': alert.headline,
                    'technical_reasons': alert.reasoning or [],
                    'warnings': [],
                    'priority': alert.priority.value if alert.priority else 'medium',
                    'tape_confirmation': alert.tape_confirmation,
                    'strategy_win_rate': alert.strategy_win_rate,
                    'auto_execute_eligible': alert.auto_execute_eligible
                }
                
                # Check if setup is enabled
                base_setup = alert.setup_type.split("_long")[0].split("_short")[0]
                if base_setup in self._enabled_setups or alert.setup_type in self._enabled_setups:
                    alerts.append(alert_dict)
                    print(f"   ✅ {alert.symbol} {alert.setup_type} passed filter")
                else:
                    print(f"   ⏭️ {alert.symbol} {alert.setup_type} not in enabled setups")
            
        except Exception as e:
            print(f"❌ [TradingBot] Error getting alerts: {e}")
            import traceback
            traceback.print_exc()
        
        if alerts:
            print(f"✅ [TradingBot] {len(alerts)} alerts ready for evaluation")
        
        return alerts[:20]  # Top 20 alerts
    
    async def _evaluate_opportunity(self, alert: Dict) -> Optional[BotTrade]:
        """Evaluate an alert and create a trade if it meets criteria"""
        try:
            symbol = alert.get('symbol')
            setup_type = alert.get('setup_type')
            direction_str = alert.get('direction', 'long')
            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT
            
            # Get current price - try IB pushed data first, then Alpaca
            current_price = alert.get('current_price', 0)
            if not current_price:
                try:
                    from routers.ib import get_pushed_quotes, is_pusher_connected
                    if is_pusher_connected():
                        quotes = get_pushed_quotes()
                        if symbol in quotes:
                            q = quotes[symbol]
                            current_price = q.get('last') or q.get('close') or 0
                except Exception:
                    pass
            
            # Fallback to Alpaca
            if not current_price and self._alpaca_service:
                quote = await self._alpaca_service.get_quote(symbol)
                current_price = quote.get('price', 0) if quote else 0
            
            if not current_price:
                print(f"   ❌ No price available for {symbol}")
                return None
            
            print(f"   📈 {symbol}: price=${current_price:.2f}")
            
            # ==================== SMART STRATEGY FILTERING ====================
            # Check user's historical performance on this setup type BEFORE proceeding
            # This is the core "learning from your trades" feature
            strategy_filter = self._evaluate_strategy_filter(
                setup_type=setup_type,
                quality_score=alert.get('score', 70),
                symbol=symbol
            )
            
            filter_action = strategy_filter.get("action", "PROCEED")
            filter_reasoning = strategy_filter.get("reasoning", "")
            filter_adjustment = strategy_filter.get("adjustment_pct", 1.0)
            filter_win_rate = strategy_filter.get("win_rate", 0)
            
            # Log the filter decision
            if filter_action != "PROCEED" or (filter_win_rate and filter_win_rate > 0):
                self._add_filter_thought({
                    "text": filter_reasoning,
                    "symbol": symbol,
                    "setup_type": setup_type,
                    "win_rate": filter_win_rate,
                    "action": filter_action,
                    "stats": strategy_filter.get("stats", {})
                })
            
            # SKIP: Don't take this trade based on poor historical performance
            if filter_action == "SKIP":
                print(f"   📊 [SMART FILTER] {filter_reasoning}")
                return None
            
            # Note: REDUCE_SIZE is handled later in position sizing
            
            # ==================== AI CONFIDENCE GATE ====================
            # Check current market conditions: regime + AI classification + model consensus
            # This runs AFTER the smart filter (historical) and BEFORE position sizing
            confidence_gate_result = None
            confidence_multiplier = 1.0
            
            if hasattr(self, '_confidence_gate') and self._confidence_gate is not None:
                try:
                    confidence_gate_result = await self._confidence_gate.evaluate(
                        symbol=symbol,
                        setup_type=setup_type,
                        direction=direction.value if hasattr(direction, 'value') else str(direction),
                        quality_score=alert.get('score', 70),
                        entry_price=alert.get('trigger_price', current_price),
                        stop_price=alert.get('stop_price', 0),
                        regime_engine=self._market_regime_engine,
                    )
                    
                    gate_decision = confidence_gate_result.get("decision", "GO")
                    gate_confidence = confidence_gate_result.get("confidence_score", 50)
                    gate_reasoning = confidence_gate_result.get("reasoning", [])
                    confidence_multiplier = confidence_gate_result.get("position_multiplier", 1.0)
                    gate_mode = confidence_gate_result.get("trading_mode", "normal")
                    
                    # Log to filter thoughts for visibility in UI
                    reasoning_summary = "; ".join(gate_reasoning[:2]) if gate_reasoning else "No reasoning"
                    self._add_filter_thought({
                        "text": f"🧠 [CONFIDENCE GATE] {gate_decision} ({gate_confidence}% conf, {gate_mode} mode) — {reasoning_summary}",
                        "symbol": symbol,
                        "setup_type": setup_type,
                        "action": f"GATE_{gate_decision}",
                        "confidence_score": gate_confidence,
                        "trading_mode": gate_mode,
                    })
                    
                    if gate_decision == "SKIP":
                        print(f"   🧠 [CONFIDENCE GATE] SKIP ({gate_confidence}% conf) — {reasoning_summary}")
                        return None
                    elif gate_decision == "REDUCE":
                        print(f"   🧠 [CONFIDENCE GATE] REDUCE ({gate_confidence}% conf, {confidence_multiplier:.0%} size) — {reasoning_summary}")
                    else:
                        print(f"   🧠 [CONFIDENCE GATE] GO ({gate_confidence}% conf) — {reasoning_summary}")
                        
                except Exception as e:
                    logger.warning(f"Confidence gate error (proceeding anyway): {e}")
                    print(f"   ⚠️ Confidence gate error: {str(e)[:100]}")
            
            # ==================== ENHANCED INTELLIGENCE GATHERING ====================
            # Gather all available real-time data to make informed decision
            intelligence = await self._gather_trade_intelligence(symbol, alert)
            
            # Apply intelligence adjustments to scoring
            score_adjustment = self._calculate_intelligence_adjustment(intelligence)
            
            # Extract ATR from intelligence for volatility-adjusted sizing
            atr = alert.get('atr', 0)
            atr_percent = alert.get('atr_percent', 0)
            
            # Try to get real ATR from technical data if not in alert
            if not atr and intelligence.get('technicals'):
                tech = intelligence['technicals']
                atr = tech.get('atr', current_price * 0.02)
                atr_percent = tech.get('atr_percent', 2.0)
            elif not atr:
                # Default to 2% of price
                atr = current_price * 0.02
                atr_percent = 2.0
            
            # Get trade parameters from alert
            entry_price = alert.get('trigger_price', current_price)
            stop_price = alert.get('stop_price', 0)
            target_prices = alert.get('targets', [])
            
            # Calculate ATR-based stop if not provided
            if not stop_price:
                stop_price = self.calculate_atr_based_stop(entry_price, direction, atr, setup_type)
            
            # Calculate targets if not provided (using ATR-based risk)
            if not target_prices:
                risk = abs(entry_price - stop_price)
                if direction == TradeDirection.LONG:
                    target_prices = [entry_price + risk * 1.5, entry_price + risk * 2.5, entry_price + risk * 4]
                else:
                    target_prices = [entry_price - risk * 1.5, entry_price - risk * 2.5, entry_price - risk * 4]
            
            # Calculate position size with volatility adjustment
            shares, risk_amount = self._calculate_position_size(entry_price, stop_price, direction, atr, atr_percent)
            
            # ==================== SMART STRATEGY FILTER SIZE ADJUSTMENT ====================
            # Apply size reduction if strategy filter recommended it
            if filter_action == "REDUCE_SIZE" and filter_adjustment < 1.0:
                original_shares = shares
                shares = max(1, int(shares * filter_adjustment))
                risk_amount = risk_amount * filter_adjustment
                print(f"   📊 [SMART FILTER] Reduced size: {original_shares} -> {shares} shares ({filter_adjustment*100:.0f}%)")
            
            # ==================== CONFIDENCE GATE SIZE ADJUSTMENT ====================
            # Apply size reduction from confidence gate (regime + model consensus)
            if confidence_multiplier < 1.0:
                original_shares = shares
                shares = max(1, int(shares * confidence_multiplier))
                risk_amount = risk_amount * confidence_multiplier
                gate_conf = confidence_gate_result.get("confidence_score", 0) if confidence_gate_result else 0
                print(f"   🧠 [CONFIDENCE GATE] Reduced size: {original_shares} -> {shares} shares ({confidence_multiplier*100:.0f}%, {gate_conf}% conf)")
            
            if shares <= 0:
                print(f"   ❌ Position size = 0 (entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f})")
                return None
            
            print(f"   📊 {symbol}: {shares} shares, entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f}")
            
            # Calculate risk/reward
            primary_target = target_prices[0] if target_prices else entry_price
            potential_reward = abs(primary_target - entry_price) * shares
            risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0
            
            # Check minimum risk/reward
            if risk_reward_ratio < self.risk_params.min_risk_reward:
                print(f"   ❌ R:R {risk_reward_ratio:.2f} < {self.risk_params.min_risk_reward} min required")
                return None
            
            print(f"   ✅ {symbol}: R:R={risk_reward_ratio:.2f}, target=${primary_target:.2f}, reward=${potential_reward:.2f}")
            
            # Get quality score with intelligence adjustment
            base_score = alert.get('score', 70)
            quality_score = min(100, max(0, base_score + score_adjustment))
            quality_grade = self._score_to_grade(quality_score)
            
            # Generate explanation with intelligence data
            explanation = self._generate_explanation(alert, shares, entry_price, stop_price, target_prices, intelligence)
            
            # Get strategy config for this setup type
            strategy_cfg = STRATEGY_CONFIG.get(setup_type, DEFAULT_STRATEGY_CONFIG)
            timeframe_val = strategy_cfg["timeframe"]
            timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
            trail_pct = strategy_cfg.get("trail_pct", 0.02)
            scale_pcts = strategy_cfg.get("scale_out_pcts", [0.33, 0.33, 0.34])
            close_at_eod = strategy_cfg.get("close_at_eod", True)
            
            # Get current market regime for position sizing and logging
            current_regime = self._current_regime or "UNKNOWN"
            regime_score = 50.0
            regime_multiplier = self._regime_position_multipliers.get(current_regime, 1.0)
            
            # Adjust regime multiplier for shorts in CONFIRMED_DOWN (they benefit)
            if current_regime == "CONFIRMED_DOWN" and direction == TradeDirection.SHORT:
                regime_multiplier = 1.0
            elif current_regime == "RISK_ON" and direction == TradeDirection.SHORT:
                regime_multiplier = 0.7  # Counter-trend shorts reduced
            
            # Try to get regime score from engine
            if self._market_regime_engine is not None:
                try:
                    regime_data = await self._market_regime_engine.get_current_regime()
                    regime_score = regime_data.get("composite_score", 50.0)
                except Exception:
                    pass
            
            # Create trade
            trade = BotTrade(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                direction=direction,
                status=TradeStatus.PENDING,
                setup_type=setup_type,
                timeframe=timeframe_str,
                quality_score=quality_score,
                quality_grade=quality_grade,
                # SMB Integration fields (from alert or defaults)
                trade_style=alert.get("trade_style", "trade_2_hold"),
                smb_grade=alert.get("smb_grade", quality_grade),
                tape_score=alert.get("tape_score", 5),
                target_r_multiple=alert.get("target_r_multiple", risk_reward_ratio),
                direction_bias=alert.get("direction_bias", "both"),
                entry_price=entry_price,
                current_price=current_price,
                stop_price=stop_price,
                target_prices=target_prices,
                shares=shares,
                risk_amount=risk_amount,
                potential_reward=potential_reward,
                risk_reward_ratio=risk_reward_ratio,
                created_at=datetime.now(timezone.utc).isoformat(),
                estimated_duration=self._estimate_duration(setup_type),
                explanation=explanation,
                close_at_eod=close_at_eod,
                # Market regime at entry
                market_regime=current_regime,
                regime_score=regime_score,
                regime_position_multiplier=regime_multiplier,
                # Richer trade logging
                setup_variant=alert.get("strategy_name", alert.get("setup_variant", setup_type)),
                entry_context=self._build_entry_context(
                    alert, intelligence, current_regime, regime_score,
                    filter_action, filter_win_rate, atr, atr_percent,
                    confidence_gate_result=confidence_gate_result
                ),
                scale_out_config={
                    "enabled": True,
                    "targets_hit": [],
                    "scale_out_pcts": scale_pcts,
                    "partial_exits": []
                },
                trailing_stop_config={
                    "enabled": True,
                    "mode": "original",
                    "original_stop": stop_price,
                    "current_stop": stop_price,
                    "trail_pct": trail_pct,
                    "trail_atr_mult": 1.5,
                    "high_water_mark": 0.0,
                    "low_water_mark": 0.0,
                    "stop_adjustments": []
                }
            )
            
            logger.info(f"Trade opportunity created: {symbol} {direction.value} {shares} shares @ ${entry_price:.2f}")
            print(f"   🎯 Trade object created: {trade.id} {symbol} {direction.value}")
            
            # ==================== AI TRADE CONSULTATION (Phase 2) ====================
            # Run pre-trade analysis through AI modules (Debate, Risk, Institutional, Volume)
            ai_consultation_result = None
            if hasattr(self, '_ai_consultation') and self._ai_consultation:
                try:
                    # Build market context for AI modules
                    market_context = {
                        "regime": current_regime,
                        "vix": intelligence.get("market_data", {}).get("vix", 0),
                        "trend": intelligence.get("market_data", {}).get("trend", "neutral"),
                        "technicals": intelligence.get("technicals", {}),
                        "session": self._get_current_session()
                    }
                    
                    # Build portfolio context
                    portfolio_context = {
                        "account_value": await self._get_account_value(),
                        "open_positions": len(self._open_trades),
                        "positions": [t.to_dict() for t in self._open_trades.values()]
                    }
                    
                    # Get bars for volume analysis
                    bars = intelligence.get("bars", [])
                    
                    # Run AI consultation
                    ai_consultation_result = await self._ai_consultation.consult_on_trade(
                        trade=trade.to_dict(),
                        market_context=market_context,
                        portfolio=portfolio_context,
                        bars=bars
                    )
                    
                    # Log consultation result
                    if ai_consultation_result:
                        consult_rec = ai_consultation_result.get("reasoning", "No AI analysis")
                        shadow_mode = ai_consultation_result.get("shadow_logged", False)
                        decision_id = ai_consultation_result.get("shadow_decision_id", "")
                        
                        print(f"   🧠 [AI Consultation] {consult_rec[:100]}")
                        
                        # Apply AI consultation recommendations
                        if not ai_consultation_result.get("proceed", True):
                            # AI modules blocked this trade
                            print(f"   ❌ [AI BLOCKED] {ai_consultation_result.get('reasoning', '')}")
                            logger.info(f"AI Consultation BLOCKED trade {symbol}: {consult_rec}")
                            
                            # Track shadow decision
                            if shadow_mode and decision_id:
                                trade.explanation.ai_shadow_decision_id = decision_id
                            
                            return None
                        
                        # Apply size adjustment if recommended
                        size_adj = ai_consultation_result.get("size_adjustment", 1.0)
                        if size_adj < 1.0:
                            original_shares = trade.shares
                            trade.shares = max(1, int(trade.shares * size_adj))
                            trade.risk_amount = trade.risk_amount * size_adj
                            trade.potential_reward = trade.potential_reward * size_adj
                            print(f"   📉 [AI SIZE ADJ] {original_shares} -> {trade.shares} shares ({size_adj*100:.0f}%)")
                        
                        # Store shadow decision ID for outcome tracking
                        if shadow_mode and decision_id:
                            if not hasattr(trade, 'ai_shadow_decision_id'):
                                trade.ai_shadow_decision_id = decision_id
                        
                        # Store consultation results in explanation
                        if trade.explanation:
                            trade.explanation.ai_consultation = {
                                "proceed": ai_consultation_result.get("proceed", True),
                                "size_adjustment": size_adj,
                                "reasoning": consult_rec[:300],
                                "shadow_decision_id": decision_id
                            }
                            
                except Exception as e:
                    logger.warning(f"AI Consultation failed (proceeding anyway): {e}")
                    print(f"   ⚠️ AI Consultation error: {str(e)[:100]}")
            
            # AI evaluation - enrich trade with AI analysis (legacy)
            if hasattr(self, '_ai_assistant') and self._ai_assistant:
                try:
                    ai_result = await self._ai_assistant.evaluate_bot_opportunity(trade.to_dict())
                    if ai_result.get("success") and trade.explanation:
                        trade.explanation.ai_evaluation = ai_result.get("analysis", "")
                        trade.explanation.ai_verdict = ai_result.get("verdict", "CAUTION")
                        if ai_result.get("verdict") == "REJECT":
                            print(f"   🤖 AI REJECTED trade: {ai_result.get('analysis', '')[:150]}")
                            logger.info(f"AI REJECTED trade {symbol}: {ai_result.get('analysis', '')[:100]}")
                            # In AUTONOMOUS mode, ignore AI rejections and proceed with trade
                            if self._mode != BotMode.AUTONOMOUS:
                                return None
                            else:
                                print("   ⚠️ Overriding AI rejection in AUTONOMOUS mode")
                except Exception as e:
                    logger.warning(f"AI evaluation failed (proceeding anyway): {e}")
            
            print(f"   ✅ Returning trade object {trade.id}")
            return trade
            
        except Exception as e:
            print(f"   ❌ Exception in _evaluate_opportunity: {e}")
            logger.error(f"Error evaluating opportunity: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _calculate_position_size(self, entry_price: float, stop_price: float, direction: TradeDirection, atr: float = None, atr_percent: float = None) -> Tuple[int, float]:
        """
        Calculate position size based on risk management rules with volatility and market regime adjustment.
        
        Args:
            entry_price: Entry price for the trade
            stop_price: Stop loss price
            direction: LONG or SHORT
            atr: Average True Range in dollars (optional, for volatility adjustment)
            atr_percent: ATR as percentage of price (optional)
        
        Returns:
            (shares, risk_amount)
        """
        # Calculate risk per share
        risk_per_share = abs(entry_price - stop_price)
        
        if risk_per_share <= 0:
            return 0, 0
        
        # Volatility-adjusted sizing
        adjusted_max_risk = self.risk_params.max_risk_per_trade
        volatility_multiplier = 1.0
        
        if self.risk_params.use_volatility_sizing and atr_percent:
            # Adjust position size based on volatility
            # Lower volatility (ATR% < 2%) = can take larger position
            # Higher volatility (ATR% > 4%) = should take smaller position
            # Normal volatility (2-3%) = standard sizing
            if atr_percent < 1.5:
                volatility_multiplier = 1.3  # Low vol - can size up
            elif atr_percent < 2.5:
                volatility_multiplier = 1.1  # Normal-low vol
            elif atr_percent < 3.5:
                volatility_multiplier = 1.0  # Normal vol
            elif atr_percent < 5.0:
                volatility_multiplier = 0.8  # High vol - size down
            else:
                volatility_multiplier = 0.6  # Very high vol - significant reduction
            
            # Apply volatility scale factor
            volatility_multiplier *= self.risk_params.volatility_scale_factor
            adjusted_max_risk = self.risk_params.max_risk_per_trade * volatility_multiplier
        
        # =====================================================================
        # MARKET REGIME ADJUSTMENT
        # =====================================================================
        # Adjust position sizing based on current market regime
        regime_multiplier = 1.0
        
        if self._current_regime:
            base_regime_multiplier = self._regime_position_multipliers.get(self._current_regime, 1.0)
            
            # For CONFIRMED_DOWN regime, allow normal sizing for SHORT trades
            # since shorts benefit from down markets
            if self._current_regime == "CONFIRMED_DOWN" and direction == TradeDirection.SHORT:
                regime_multiplier = 1.0  # Full sizing for shorts in down market
            # For RISK_ON regime, slightly reduce short sizing (counter-trend)
            elif self._current_regime == "RISK_ON" and direction == TradeDirection.SHORT:
                regime_multiplier = 0.7  # Reduce shorts in up market (counter-trend)
            else:
                regime_multiplier = base_regime_multiplier
            
            adjusted_max_risk *= regime_multiplier
            
            if regime_multiplier < 1.0:
                logger.debug(f"Position size adjusted by regime ({self._current_regime}): {regime_multiplier:.0%}")
        # =====================================================================
        
        # Calculate max shares based on adjusted risk per trade
        max_shares_by_risk = int(adjusted_max_risk / risk_per_share)
        
        # Calculate max shares based on max position size
        max_position_value = self.risk_params.starting_capital * (self.risk_params.max_position_pct / 100)
        max_shares_by_capital = int(max_position_value / entry_price)
        
        # Take the minimum
        shares = min(max_shares_by_risk, max_shares_by_capital)
        
        # Ensure at least 1 share
        shares = max(shares, 1)
        
        # Calculate actual risk
        risk_amount = shares * risk_per_share
        
        # Cap risk at max per trade (using adjusted max)
        if risk_amount > adjusted_max_risk:
            shares = int(adjusted_max_risk / risk_per_share)
            risk_amount = shares * risk_per_share
        
        return shares, risk_amount
    
    def calculate_atr_based_stop(self, entry_price: float, direction: TradeDirection, atr: float, setup_type: str = None) -> float:
        """
        Calculate stop loss based on ATR with setup-specific adjustments.
        
        Args:
            entry_price: Entry price for the trade
            direction: LONG or SHORT
            atr: Average True Range in dollars
            setup_type: Optional setup type for custom multiplier
        
        Returns:
            Stop price
        """
        # Setup-specific ATR multipliers
        setup_multipliers = {
            'rubber_band': 1.0,      # Tighter stops for mean reversion
            'squeeze': 1.5,          # Medium stops for squeeze plays
            'breakout': 1.5,         # Standard stops for breakouts
            'vwap_bounce': 1.0,      # Tight stops for VWAP plays
            'gap_fade': 1.25,        # Moderate stops for gap fades
            'relative_strength': 1.5, # Standard stops
            'mean_reversion': 1.0,   # Tight stops for MR
            'orb': 1.25,             # Moderate stops for ORB
        }
        
        multiplier = setup_multipliers.get(setup_type, self.risk_params.base_atr_multiplier)
        
        # Clamp multiplier within bounds
        multiplier = max(self.risk_params.min_atr_multiplier, 
                        min(multiplier, self.risk_params.max_atr_multiplier))
        
        stop_distance = atr * multiplier
        
        if direction == TradeDirection.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
    
    def _score_to_grade(self, score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B+"
        if score >= 60:
            return "B"
        if score >= 50:
            return "C"
        return "F"
    
    def _estimate_duration(self, setup_type: str) -> str:
        """Estimate trade duration based on setup type"""
        durations = {
            "rubber_band": "30min - 2hr",
            "breakout": "1hr - 4hr",
            "vwap_bounce": "15min - 1hr",
            "squeeze": "2hr - 1day"
        }
        return durations.get(setup_type, "1hr - 4hr")
    
    # ==================== ENHANCED INTELLIGENCE GATHERING ====================
    
    async def _gather_trade_intelligence(self, symbol: str, alert: Dict) -> Dict[str, Any]:
        """
        Gather comprehensive intelligence for trade evaluation.
        This is what makes the bot "smart" - it uses the same data sources as the AI assistant.
        """
        intelligence = {
            "symbol": symbol,
            "gathered_at": datetime.now(timezone.utc).isoformat(),
            "news": None,
            "technicals": None,
            "market_context": None,
            "quality_metrics": None,
            "warnings": [],
            "enhancements": []
        }
        
        try:
            # Run intelligence gathering in parallel for speed
            tasks = []
            
            # 1. Get recent news (critical for informed trading)
            if self.web_research:
                tasks.append(self._get_news_intelligence(symbol))
            else:
                tasks.append(asyncio.coroutine(lambda: None)())
            
            # 2. Get technical analysis
            if self.technical_service:
                tasks.append(self._get_technical_intelligence(symbol))
            else:
                tasks.append(asyncio.coroutine(lambda: None)())
            
            # 3. Get quality metrics
            if self.quality_service:
                tasks.append(self._get_quality_intelligence(symbol))
            else:
                tasks.append(asyncio.coroutine(lambda: None)())
            
            # Execute all in parallel with timeout
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=10.0  # 10 second max for intelligence gathering
                )
                
                if len(results) > 0 and results[0] and not isinstance(results[0], Exception):
                    intelligence["news"] = results[0]
                if len(results) > 1 and results[1] and not isinstance(results[1], Exception):
                    intelligence["technicals"] = results[1]
                if len(results) > 2 and results[2] and not isinstance(results[2], Exception):
                    intelligence["quality_metrics"] = results[2]
                    
            except asyncio.TimeoutError:
                intelligence["warnings"].append("Intelligence gathering timed out - proceeding with basic data")
                logger.warning(f"Intelligence gathering timeout for {symbol}")
            
            # Analyze gathered intelligence for warnings and enhancements
            self._analyze_intelligence(intelligence, alert)
            
        except Exception as e:
            logger.error(f"Intelligence gathering error for {symbol}: {e}")
            intelligence["warnings"].append(f"Error gathering intelligence: {str(e)}")
        
        return intelligence
    
    async def _get_news_intelligence(self, symbol: str) -> Optional[Dict]:
        """Get recent news that could impact the trade - prioritizes IB news"""
        try:
            # Try unified news service first (prioritizes IB historical news)
            try:
                from services.news_service import get_news_service
                news_service = get_news_service()
                news_items = await news_service.get_ticker_news(symbol, max_items=5)
                
                if news_items and not news_items[0].get("is_placeholder"):
                    headlines = [n.get("headline", "") for n in news_items]
                    sentiments = [n.get("sentiment", "neutral") for n in news_items]
                    
                    # Count sentiment
                    bullish = sentiments.count("bullish")
                    bearish = sentiments.count("bearish")
                    
                    if bullish > bearish:
                        overall_sentiment = "bullish"
                    elif bearish > bullish:
                        overall_sentiment = "bearish"
                    else:
                        overall_sentiment = "neutral"
                    
                    return {
                        "has_news": True,
                        "summary": f"Found {len(news_items)} recent news items for {symbol}",
                        "headlines": headlines[:5],
                        "sentiment": overall_sentiment,
                        "source": news_items[0].get("source_type", "unknown"),
                        "key_topics": []
                    }
            except Exception as e:
                logger.debug(f"News service failed, falling back to Tavily: {e}")
            
            # Fallback to Tavily for web search if news service fails
            result = await self.web_research.tavily.search_financial(
                f"{symbol} stock news latest",
                max_results=3
            )
            
            news_data = {
                "has_news": len(result.results) > 0,
                "summary": result.answer[:500] if result.answer else None,
                "headlines": [r.title for r in result.results[:3]],
                "sentiment": self._analyze_news_sentiment(result),
                "key_topics": self._extract_news_topics(result),
                "source": "tavily"
            }
            
            return news_data
            
        except Exception as e:
            logger.warning(f"News intelligence error for {symbol}: {e}")
            return None
    
    async def _get_technical_intelligence(self, symbol: str) -> Optional[Dict]:
        """Get real-time technical analysis"""
        try:
            snapshot = await self.technical_service.get_technical_snapshot(symbol)
            
            if not snapshot:
                return None
            
            # Determine volume trend based on RVOL
            volume_trend = "normal"
            if snapshot.rvol >= 2.0:
                volume_trend = "high"
            elif snapshot.rvol < 0.5:
                volume_trend = "low"
            
            # Generate signals based on technical conditions
            signals = []
            if snapshot.above_vwap and snapshot.above_ema9:
                signals.append("bullish_structure")
            if snapshot.rsi_14 > 70:
                signals.append("overbought")
            elif snapshot.rsi_14 < 30:
                signals.append("oversold")
            if snapshot.extended_from_ema9:
                signals.append("extended")
            if snapshot.holding_gap:
                signals.append("gap_hold")
            
            return {
                "trend": snapshot.trend or "neutral",
                "momentum": snapshot.rsi_14 or 50,
                "support_levels": [snapshot.support] if snapshot.support else [],
                "resistance_levels": [snapshot.resistance] if snapshot.resistance else [],
                "volume_trend": volume_trend,
                "signals": signals
            }
            
        except Exception as e:
            logger.warning(f"Technical intelligence error for {symbol}: {e}")
            return None
    
    async def _get_quality_intelligence(self, symbol: str) -> Optional[Dict]:
        """Get quality score and metrics"""
        try:
            # Get quality metrics first
            metrics = await self.quality_service.get_quality_metrics(symbol)
            
            if not metrics or metrics.data_quality == "low":
                return None
            
            # Calculate the quality score
            score = self.quality_service.calculate_quality_score(metrics)
            
            # Build strengths and weaknesses based on scores
            strengths = []
            weaknesses = []
            
            if score.accruals_score and score.accruals_score > 60:
                strengths.append("Low earnings manipulation risk")
            elif score.accruals_score and score.accruals_score < 40:
                weaknesses.append("High accruals concern")
                
            if score.roe_score and score.roe_score > 60:
                strengths.append("Strong return on equity")
            elif score.roe_score and score.roe_score < 40:
                weaknesses.append("Weak profitability")
                
            if score.cfa_score and score.cfa_score > 60:
                strengths.append("Good cash flow generation")
            elif score.cfa_score and score.cfa_score < 40:
                weaknesses.append("Poor cash conversion")
                
            if score.da_score and score.da_score > 60:
                strengths.append("Conservative leverage")
            elif score.da_score and score.da_score < 40:
                weaknesses.append("High debt levels")
            
            return {
                "quality_score": score.percentile_rank or 50,
                "grade": score.grade or "C",
                "strengths": strengths,
                "weaknesses": weaknesses
            }
            
        except Exception as e:
            logger.warning(f"Quality intelligence error for {symbol}: {e}")
            return None
    
    def _analyze_news_sentiment(self, news_result) -> str:
        """Analyze sentiment from news results"""
        if not news_result or not news_result.answer:
            return "neutral"
        
        answer_lower = news_result.answer.lower()
        
        # Positive indicators
        positive = ["surge", "rally", "gain", "beat", "upgrade", "buy", "bullish", "strong", "positive"]
        negative = ["drop", "fall", "miss", "downgrade", "sell", "bearish", "weak", "negative", "crash"]
        
        pos_count = sum(1 for word in positive if word in answer_lower)
        neg_count = sum(1 for word in negative if word in answer_lower)
        
        if pos_count > neg_count + 1:
            return "positive"
        elif neg_count > pos_count + 1:
            return "negative"
        return "neutral"
    
    def _extract_news_topics(self, news_result) -> List[str]:
        """Extract key topics from news"""
        topics = []
        if news_result and news_result.answer:
            answer_lower = news_result.answer.lower()
            
            topic_map = {
                "earnings": ["earnings", "revenue", "profit", "quarterly"],
                "analyst": ["analyst", "upgrade", "downgrade", "rating", "target"],
                "product": ["product", "launch", "announce", "release"],
                "legal": ["lawsuit", "legal", "sec", "investigation"],
                "merger": ["merger", "acquisition", "deal", "buyout"],
                "macro": ["fed", "rate", "inflation", "economy"]
            }
            
            for topic, keywords in topic_map.items():
                if any(kw in answer_lower for kw in keywords):
                    topics.append(topic)
        
        return topics[:3]  # Top 3 topics
    
    def _analyze_intelligence(self, intelligence: Dict, alert: Dict):
        """Analyze gathered intelligence and add warnings/enhancements"""
        warnings = intelligence["warnings"]
        enhancements = intelligence["enhancements"]
        
        # News analysis
        news = intelligence.get("news")
        if news:
            if news.get("sentiment") == "negative":
                warnings.append("⚠️ Negative news sentiment detected")
            elif news.get("sentiment") == "positive":
                enhancements.append("✅ Positive news sentiment")
            
            topics = news.get("key_topics", [])
            if "earnings" in topics:
                warnings.append("⚠️ Earnings-related news - volatility likely")
            if "legal" in topics:
                warnings.append("⚠️ Legal/regulatory news detected")
            if "analyst" in topics:
                enhancements.append("✅ Analyst coverage - increased visibility")
        
        # Technical analysis
        technicals = intelligence.get("technicals")
        if technicals:
            direction = alert.get("direction", "long")
            trend = technicals.get("trend", "neutral")
            
            # Check if trade aligns with trend
            if direction == "long" and trend == "down":
                warnings.append("⚠️ Trading against downtrend")
            elif direction == "short" and trend == "up":
                warnings.append("⚠️ Shorting against uptrend")
            elif (direction == "long" and trend == "up") or (direction == "short" and trend == "down"):
                enhancements.append("✅ Trade aligns with trend")
            
            # RSI extremes
            rsi = technicals.get("momentum", 50)
            if rsi > 70 and direction == "long":
                warnings.append(f"⚠️ RSI overbought ({rsi:.0f})")
            elif rsi < 30 and direction == "short":
                warnings.append(f"⚠️ RSI oversold ({rsi:.0f})")
            
            # Volume
            vol_trend = technicals.get("volume_trend", "normal")
            if vol_trend == "high":
                enhancements.append("✅ High volume confirms move")
            elif vol_trend == "low":
                warnings.append("⚠️ Low volume - watch for false breakout")
        
        # Quality metrics
        quality = intelligence.get("quality_metrics")
        if quality:
            score = quality.get("quality_score", 50)
            if score >= 80:
                enhancements.append(f"✅ High quality setup ({score}/100)")
            elif score < 50:
                warnings.append(f"⚠️ Low quality score ({score}/100)")
    
    def _calculate_intelligence_adjustment(self, intelligence: Dict) -> int:
        """
        Calculate score adjustment based on intelligence.
        Returns a value to add/subtract from the base quality score.
        """
        adjustment = 0
        
        # News sentiment
        news = intelligence.get("news")
        if news:
            sentiment = news.get("sentiment", "neutral")
            if sentiment == "positive":
                adjustment += 5
            elif sentiment == "negative":
                adjustment -= 10  # Negative news is more impactful
        
        # Technical alignment
        technicals = intelligence.get("technicals")
        if technicals:
            vol_trend = technicals.get("volume_trend", "normal")
            if vol_trend == "high":
                adjustment += 5
            elif vol_trend == "low":
                adjustment -= 5
        
        # Warnings count
        warnings = intelligence.get("warnings", [])
        adjustment -= len(warnings) * 3  # Each warning reduces score
        
        # Enhancements count
        enhancements = intelligence.get("enhancements", [])
        adjustment += len(enhancements) * 2  # Each enhancement increases score
        
        return adjustment
    
    def _build_entry_context(
        self, alert: Dict, intelligence: Dict, regime: str,
        regime_score: float, filter_action: str, filter_win_rate: float,
        atr: float, atr_percent: float, confidence_gate_result: Dict = None
    ) -> Dict[str, Any]:
        """
        Build rich entry context capturing WHY this trade was taken.
        This snapshot records the conditions and signals at the moment of entry
        for post-trade analysis and AI learning.
        """
        ctx = {}
        
        # 1. Setup identification
        ctx["scanner_setup_type"] = alert.get("setup_type", "")
        ctx["strategy_name"] = alert.get("strategy_name", "")
        ctx["setup_category"] = alert.get("setup_category", "")
        ctx["score"] = alert.get("score", 0)
        ctx["trigger_probability"] = alert.get("trigger_probability", 0)
        ctx["tape_confirmation"] = alert.get("tape_confirmation", False)
        ctx["priority"] = alert.get("priority", "medium")
        if isinstance(ctx["priority"], type) and hasattr(ctx["priority"], "value"):
            ctx["priority"] = ctx["priority"].value
        
        # 2. Market regime context
        ctx["market_regime"] = regime
        ctx["regime_score"] = regime_score
        
        # 3. Strategy filter context (smart filter)
        ctx["filter_action"] = filter_action
        ctx["filter_win_rate"] = filter_win_rate
        ctx["strategy_win_rate"] = alert.get("strategy_win_rate", 0)
        
        # 4. Volatility context
        ctx["atr"] = round(atr, 4) if atr else 0
        ctx["atr_percent"] = round(atr_percent, 2) if atr_percent else 0
        ctx["rvol"] = alert.get("rvol", 0) or alert.get("relative_volume", 0)
        
        # 5. Technical signals from intelligence
        if intelligence:
            tech = intelligence.get("technicals") or {}
            ctx["technicals"] = {
                "trend": tech.get("trend", ""),
                "rsi": tech.get("momentum", 0),
                "vwap_relation": tech.get("vwap_relation", ""),
                "volume_trend": tech.get("volume_trend", ""),
                "support_nearby": tech.get("near_support", False),
                "resistance_nearby": tech.get("near_resistance", False),
            }
            
            # News/catalyst
            if intelligence.get("news"):
                ctx["catalyst"] = {
                    "has_catalyst": True,
                    "headline_count": len(intelligence["news"]) if isinstance(intelligence["news"], list) else 1,
                }
            
            # Institutional signals
            if intelligence.get("institutional"):
                inst = intelligence["institutional"]
                ctx["institutional"] = {
                    "dark_pool_signal": inst.get("dark_pool_signal", ""),
                    "block_trade_alert": inst.get("block_trade_alert", False),
                }
        
        # 6. Time context
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
        ctx["entry_time_et"] = now_et.strftime("%H:%M:%S")
        ctx["time_window"] = self._classify_time_window(now_et)
        
        # 7. AI prediction context (if available)
        if hasattr(self, '_last_ai_prediction') and self._last_ai_prediction:
            pred = self._last_ai_prediction
            if pred.get("symbol") == alert.get("symbol"):
                ctx["ai_prediction"] = {
                    "direction": pred.get("direction", ""),
                    "confidence": pred.get("confidence", 0),
                    "regime_aligned": pred.get("regime_adjustment", {}).get("regime_aligned"),
                }
        
        # 8. Confidence gate context (regime + AI + model consensus)
        if confidence_gate_result:
            ctx["confidence_gate"] = {
                "decision": confidence_gate_result.get("decision", ""),
                "confidence_score": confidence_gate_result.get("confidence_score", 0),
                "position_multiplier": confidence_gate_result.get("position_multiplier", 1.0),
                "trading_mode": confidence_gate_result.get("trading_mode", ""),
                "ai_regime": confidence_gate_result.get("ai_regime", ""),
                "reasoning": confidence_gate_result.get("reasoning", [])[:3],
            }
        
        return ctx
    
    @staticmethod
    def _classify_time_window(now_et) -> str:
        """Classify the current ET time into a trading time window."""
        h, m = now_et.hour, now_et.minute
        t = h * 60 + m
        if t < 9 * 60 + 30:
            return "pre_market"
        elif t < 9 * 60 + 45:
            return "opening_auction"
        elif t < 10 * 60:
            return "opening_drive"
        elif t < 10 * 60 + 30:
            return "morning_momentum"
        elif t < 11 * 60 + 30:
            return "morning_session"
        elif t < 12 * 60:
            return "late_morning"
        elif t < 13 * 60 + 30:
            return "midday"
        elif t < 15 * 60:
            return "afternoon"
        elif t < 16 * 60:
            return "power_hour"
        else:
            return "after_hours"
    

    def _generate_explanation(self, alert: Dict, shares: int, entry: float, stop: float, targets: List[float], intelligence: Dict = None) -> TradeExplanation:
        """Generate detailed explanation for the trade with intelligence data"""
        symbol = alert.get('symbol', '')
        setup_type = alert.get('setup_type', '')
        direction = alert.get('direction', 'long')
        
        risk_per_share = abs(entry - stop)
        total_risk = shares * risk_per_share
        target_1_profit = abs(targets[0] - entry) * shares if targets else 0
        
        # Build technical reasons from alert + intelligence
        technical_reasons = alert.get('technical_reasons', [
            f"Setup type: {setup_type}",
            f"Score: {alert.get('score', 'N/A')}/100",
            f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%"
        ])
        
        # Add intelligence-based technical factors
        if intelligence and intelligence.get('technicals'):
            tech = intelligence['technicals']
            if tech.get('trend'):
                technical_reasons.append(f"Trend: {tech['trend']}")
            if tech.get('momentum'):
                technical_reasons.append(f"RSI: {tech['momentum']:.0f}")
            if tech.get('volume_trend'):
                technical_reasons.append(f"Volume: {tech['volume_trend']}")
        
        # Build fundamental reasons from intelligence
        fundamental_reasons = alert.get('fundamental_reasons', [])
        if intelligence and intelligence.get('news'):
            news = intelligence['news']
            if news.get('sentiment'):
                fundamental_reasons.append(f"News sentiment: {news['sentiment']}")
            if news.get('key_topics'):
                fundamental_reasons.append(f"Key topics: {', '.join(news['key_topics'])}")
            if news.get('summary'):
                fundamental_reasons.append(f"Latest: {news['summary'][:100]}...")
        
        # Combine warnings from alert and intelligence
        all_warnings = alert.get('warnings', []).copy()
        if intelligence:
            all_warnings.extend(intelligence.get('warnings', []))
        
        # Build confidence factors
        confidence_factors = [
            f"Quality score: {alert.get('score', 0)}/100",
            f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%",
            f"Risk/Reward: {abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
        ]
        
        # Add intelligence enhancements as confidence factors
        if intelligence and intelligence.get('enhancements'):
            confidence_factors.extend(intelligence['enhancements'])
        
        return TradeExplanation(
            summary=f"{setup_type.replace('_', ' ').title()} setup identified on {symbol}. "
                    f"{'Buying' if direction == 'long' else 'Shorting'} {shares} shares at ${entry:.2f} "
                    f"with stop at ${stop:.2f} and target at ${targets[0]:.2f}.",
            
            setup_identified=alert.get('headline', f"{setup_type} pattern detected"),
            
            technical_reasons=technical_reasons,
            
            fundamental_reasons=fundamental_reasons,
            
            risk_analysis={
                "risk_per_share": f"${risk_per_share:.2f}",
                "total_risk": f"${total_risk:.2f}",
                "max_risk_allowed": f"${self.risk_params.max_risk_per_trade:.2f}",
                "risk_pct_of_capital": f"{(total_risk / self.risk_params.starting_capital * 100):.2f}%",
                "risk_reward_ratio": f"{abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
            },
            
            entry_logic=f"Enter at ${entry:.2f} when price reaches trigger level. "
                       f"Current price is ${alert.get('current_price', 0):.2f}.",
            
            exit_logic=f"Stop loss at ${stop:.2f} ({(risk_per_share/entry*100):.1f}% from entry). "
                      f"Primary target at ${targets[0]:.2f} ({(abs(targets[0]-entry)/entry*100):.1f}% gain). "
                      f"Consider scaling out at subsequent targets.",
            
            position_sizing_logic=f"Position size: {shares} shares (${shares * entry:,.2f} value). "
                                 f"Based on max risk ${self.risk_params.max_risk_per_trade:,.0f} "
                                 f"÷ risk per share ${risk_per_share:.2f} = {int(self.risk_params.max_risk_per_trade/risk_per_share)} max shares. "
                                 f"Capped at {self.risk_params.max_position_pct}% of capital.",
            
            confidence_factors=confidence_factors,
            
            warnings=all_warnings
        )
    
    # ==================== TRADE EXECUTION ====================
    
    async def _execute_trade(self, trade: BotTrade):
        """
        Execute a trade via the trade executor.
        
        Strategy Phase Check (SIM → PAPER → LIVE):
        - LIVE: Execute real trade via broker
        - PAPER: Record paper trade, do not execute
        - SIMULATION: Skip entirely (not ready for real-time)
        
        In AUTONOMOUS mode with IB data:
        - Uses live IB prices for decision-making
        - Currently executes in SIMULATED mode (orders tracked but not sent to broker)
        - Full IB order execution requires local IB Gateway order routing (future enhancement)
        """
        print(f"   📤 [_execute_trade] Starting execution for {trade.symbol}")
        
        # === STRATEGY PHASE CHECK ===
        # This is the gate that controls which strategies execute real trades
        if self._strategy_promotion_service:
            should_execute, phase_reason, should_paper = self._strategy_promotion_service.should_execute_trade(trade.setup_type)
            
            if not should_execute:
                if should_paper:
                    # PAPER PHASE: Record the trade without executing
                    logger.info(f"📝 [PAPER TRADE] {trade.symbol} {trade.direction.value.upper()} - {phase_reason}")
                    trade.notes = (trade.notes or "") + f" [PAPER: {phase_reason}]"
                    
                    # Record paper trade for tracking
                    try:
                        paper_trade_id = await self._strategy_promotion_service.record_paper_trade(
                            strategy_name=trade.setup_type,
                            symbol=trade.symbol,
                            direction=trade.direction.value,
                            entry_price=trade.entry_price,
                            stop_price=trade.stop_price,
                            target_price=trade.target_prices[0] if trade.target_prices else trade.entry_price * 1.02,
                            notes=f"Would have traded: {trade.shares} shares | R:R={trade.risk_reward_ratio:.1f}"
                        )
                        logger.info(f"📝 Paper trade recorded: {paper_trade_id}")
                        
                        # Add to filter thoughts for visibility
                        self._add_filter_thought({
                            "text": f"📝 PAPER: {trade.symbol} {trade.setup_type} ({trade.direction.value}) - Strategy not yet LIVE",
                            "symbol": trade.symbol,
                            "setup_type": trade.setup_type,
                            "action": "PAPER_TRACKED",
                            "phase": "paper"
                        })
                    except Exception as e:
                        logger.warning(f"Failed to record paper trade: {e}")
                    
                    # Mark trade as not executed (for UI feedback)
                    trade.status = TradeStatus.CANCELLED
                    trade.close_reason = "paper_phase"
                    await self._save_trade(trade)
                    return
                else:
                    # SIMULATION PHASE: Skip entirely
                    logger.info(f"⏭️ [SKIPPED] {trade.symbol} {trade.direction.value.upper()} - {phase_reason}")
                    trade.notes = (trade.notes or "") + f" [SKIPPED: {phase_reason}]"
                    trade.status = TradeStatus.CANCELLED
                    trade.close_reason = "simulation_phase"
                    await self._save_trade(trade)
                    return
            else:
                # LIVE PHASE: Proceed with execution
                logger.info(f"🚀 [LIVE STRATEGY] {trade.symbol} {trade.setup_type} - Executing real trade")
        
        if not self._trade_executor:
            print("   ❌ Trade executor not configured")
            logger.error("Trade executor not configured")
            return
        
        try:
            # Log execution mode
            executor_mode = self._trade_executor.get_mode() if self._trade_executor else "unknown"
            print(f"   📤 [_execute_trade] Executor mode: {executor_mode.value if hasattr(executor_mode, 'value') else executor_mode}")
            logger.info(f"[TradingBot] Executing {trade.symbol} {trade.direction.value.upper()} | Mode: {executor_mode.value}")
            
            # Start execution tracking (Phase 1 Learning)
            if hasattr(self, '_learning_loop') and self._learning_loop:
                try:
                    # Use target_prices instead of targets
                    planned_r = (trade.target_prices[0] / trade.entry_price - 1) if trade.target_prices else 2.0
                    self._learning_loop.start_execution_tracking(
                        trade_id=trade.id,
                        alert_id=getattr(trade, 'alert_id', trade.id),
                        intended_entry=trade.entry_price,
                        intended_size=trade.shares,
                        planned_r=planned_r
                    )
                except Exception as e:
                    logger.warning(f"Failed to start execution tracking: {e}")
            
            # Execute entry order
            print("   📤 [_execute_trade] Calling trade_executor.execute_entry...")
            result = await self._trade_executor.execute_entry(trade)
            print(f"   📤 [_execute_trade] Result: {result}")
            
            if result.get('success'):
                trade.status = TradeStatus.OPEN
                trade.fill_price = result.get('fill_price', trade.entry_price)
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')
                
                # Initialize MFE/MAE at fill price (starting point)
                trade.mfe_price = trade.fill_price
                trade.mae_price = trade.fill_price
                
                # Track entry commission
                entry_commission = self._apply_commission(trade, trade.shares)
                
                # Mark if simulated
                if result.get('simulated'):
                    trade.notes = (trade.notes or "") + " [SIMULATED]"
                else:
                    broker = result.get('broker', 'unknown')
                    trade.notes = (trade.notes or "") + f" [LIVE-{broker.upper()}]"
                
                print(f"   💰 Entry commission: ${entry_commission:.2f} ({trade.shares} shares @ ${trade.commission_per_share}/share)")
                
                # Record actual entry (Phase 1 Learning)
                if hasattr(self, '_learning_loop') and self._learning_loop:
                    try:
                        self._learning_loop.record_trade_entry(
                            trade_id=trade.id,
                            actual_entry=trade.fill_price,
                            actual_size=trade.shares
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record entry: {e}")
                
                # Place stop and target orders
                stop_result = await self._trade_executor.place_stop_order(trade)
                if stop_result.get('success'):
                    trade.stop_order_id = stop_result.get('order_id')
                
                # Move to open trades
                if trade.id in self._pending_trades:
                    del self._pending_trades[trade.id]
                self._open_trades[trade.id] = trade
                
                # Update stats
                self._daily_stats.trades_executed += 1
                
                await self._notify_trade_update(trade, "executed")
                await self._save_trade(trade)
                
                # Auto-record to Trade Journal
                await self._log_trade_to_journal(trade, "entry")
                
                sim_tag = " (SIMULATED)" if result.get('simulated') else ""
                logger.info(f"✅ Trade executed{sim_tag}: {trade.symbol} {trade.shares} @ ${trade.fill_price:.2f}")
            
            elif result.get('status') == 'timeout':
                # TIMEOUT HANDLING: Order may still execute - save as pending for sync
                trade.status = TradeStatus.OPEN  # Assume it went through
                trade.fill_price = trade.entry_price  # Use intended price
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')
                trade.notes = (trade.notes or "") + " [TIMEOUT-NEEDS-SYNC]"
                
                # Initialize MFE/MAE
                trade.mfe_price = trade.fill_price
                trade.mae_price = trade.fill_price
                
                # Move to open trades so bot tracks it
                if trade.id in self._pending_trades:
                    del self._pending_trades[trade.id]
                self._open_trades[trade.id] = trade
                
                # Update stats
                self._daily_stats.trades_executed += 1
                
                await self._save_trade(trade)
                
                logger.warning(f"⚠️ Trade timeout but saved for sync: {trade.symbol} {trade.shares} shares - will verify with IB")
            
            else:
                trade.status = TradeStatus.REJECTED
                logger.warning(f"Trade rejected: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            trade.status = TradeStatus.REJECTED
    
    async def confirm_trade(self, trade_id: str) -> bool:
        """
        Confirm a pending trade for execution.
        
        Before executing:
        1. Check if the alert is stale (expired based on timeframe)
        2. Recalculate entry price, shares, and risk based on current market price
        """
        if trade_id not in self._pending_trades:
            return False
        
        trade = self._pending_trades[trade_id]
        
        # === STALE ALERT CHECK ===
        # Scalps/intraday: 5 min timeout. Swings: 15 min. Investment: 60 min.
        stale_thresholds = {
            "scalp": 300,      # 5 min
            "day": 600,        # 10 min
            "swing": 900,      # 15 min
            "investment": 3600, # 60 min
        }
        max_age_seconds = stale_thresholds.get(trade.timeframe, 600)  # Default 10 min
        
        if trade.created_at:
            try:
                created = datetime.fromisoformat(trade.created_at.replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - created).total_seconds()
                if age > max_age_seconds:
                    logger.info(f"Stale alert: {trade.symbol} {trade.setup_type} is {age:.0f}s old (max {max_age_seconds}s for {trade.timeframe})")
                    trade.status = TradeStatus.REJECTED
                    trade.notes = (trade.notes or "") + f" [EXPIRED: {age:.0f}s old]"
                    del self._pending_trades[trade_id]
                    await self._notify_trade_update(trade, "expired")
                    return False
            except Exception as e:
                logger.warning(f"Could not check alert age: {e}")
        
        # === PRICE RECALCULATION ===
        # Get current market price and recalculate position
        current_price = None
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            if is_pusher_connected():
                quotes = get_pushed_quotes()
                if trade.symbol in quotes:
                    q = quotes[trade.symbol]
                    current_price = q.get('last') or q.get('close')
        except Exception:
            pass
        
        if not current_price and self._alpaca_service:
            try:
                quote = await self._alpaca_service.get_quote(trade.symbol)
                current_price = quote.get('price') if quote else None
            except Exception:
                pass
        
        if current_price and current_price != trade.entry_price:
            old_entry = trade.entry_price
            old_shares = trade.shares
            trade.entry_price = current_price
            
            # Recalculate shares based on new entry and original stop
            if trade.stop_price and trade.stop_price != trade.entry_price:
                risk_per_share = abs(trade.entry_price - trade.stop_price)
                if risk_per_share > 0:
                    risk_amount = self.risk_params.max_risk_per_trade
                    new_shares = max(1, int(risk_amount / risk_per_share))
                    trade.shares = new_shares
                    trade.remaining_shares = new_shares
                    trade.original_shares = new_shares
            
            # Recalculate targets proportionally
            if hasattr(trade, 'scale_out_config') and trade.scale_out_config.get('target_prices'):
                old_targets = trade.scale_out_config['target_prices']
                if old_entry and old_entry != 0:
                    ratio = current_price / old_entry
                    trade.scale_out_config['target_prices'] = [round(t * ratio, 2) for t in old_targets]
            
            logger.info(
                f"Price recalc on confirm: {trade.symbol} entry ${old_entry:.2f}→${current_price:.2f}, "
                f"shares {old_shares}→{trade.shares}"
            )
            print(f"   🔄 [CONFIRM] Price adjusted: ${old_entry:.2f}→${current_price:.2f}, shares {old_shares}→{trade.shares}")
        
        await self._execute_trade(trade)
        return trade.status == TradeStatus.OPEN
    
    async def reject_trade(self, trade_id: str) -> bool:
        """Reject a pending trade"""
        if trade_id not in self._pending_trades:
            return False
        
        trade = self._pending_trades[trade_id]
        trade.status = TradeStatus.REJECTED
        del self._pending_trades[trade_id]
        await self._notify_trade_update(trade, "rejected")
        return True
    
    # ==================== POSITION MANAGEMENT ====================
    
    async def _update_open_positions(self):
        """Update P&L for open positions - uses IB data first, then Alpaca"""
        for trade_id, trade in list(self._open_trades.items()):
            try:
                quote = None
                
                # Try IB pushed data first
                try:
                    from routers.ib import get_pushed_quotes, is_pusher_connected
                    if is_pusher_connected():
                        quotes = get_pushed_quotes()
                        if trade.symbol in quotes:
                            q = quotes[trade.symbol]
                            quote = {'price': q.get('last') or q.get('close') or 0}
                except Exception:
                    pass
                
                # Fallback to Alpaca
                if not quote and self._alpaca_service:
                    quote = await self._alpaca_service.get_quote(trade.symbol)
                
                if not quote:
                    continue
                
                trade.current_price = quote.get('price', trade.current_price)
                
                # Initialize remaining_shares if not set
                if trade.remaining_shares == 0:
                    trade.remaining_shares = trade.shares
                    trade.original_shares = trade.shares
                
                # Initialize trailing stop config if not set
                if trade.trailing_stop_config.get('original_stop', 0) == 0:
                    trade.trailing_stop_config['original_stop'] = trade.stop_price
                    trade.trailing_stop_config['current_stop'] = trade.stop_price
                    trade.trailing_stop_config['mode'] = 'original'
                
                # Calculate unrealized P&L on remaining shares
                if trade.direction == TradeDirection.LONG:
                    trade.unrealized_pnl = (trade.current_price - trade.fill_price) * trade.remaining_shares
                else:
                    trade.unrealized_pnl = (trade.fill_price - trade.current_price) * trade.remaining_shares
                
                # === MFE/MAE TRACKING ===
                # Track from moment of fill for the full trade lifecycle
                if trade.fill_price and trade.fill_price > 0:
                    risk_per_share = abs(trade.fill_price - trade.stop_price) if trade.stop_price else trade.fill_price * 0.02
                    if risk_per_share == 0:
                        risk_per_share = trade.fill_price * 0.02  # Fallback: 2% of entry
                    
                    if trade.direction == TradeDirection.LONG:
                        # MFE: highest price since fill
                        if trade.current_price > trade.mfe_price or trade.mfe_price == 0:
                            trade.mfe_price = trade.current_price
                            trade.mfe_pct = ((trade.mfe_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mfe_r = (trade.mfe_price - trade.fill_price) / risk_per_share
                        # MAE: lowest price since fill
                        if trade.current_price < trade.mae_price or trade.mae_price == 0:
                            trade.mae_price = trade.current_price
                            trade.mae_pct = ((trade.mae_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mae_r = (trade.mae_price - trade.fill_price) / risk_per_share
                    else:  # SHORT
                        # MFE: lowest price since fill (favorable for shorts)
                        if trade.current_price < trade.mfe_price or trade.mfe_price == 0:
                            trade.mfe_price = trade.current_price
                            trade.mfe_pct = ((trade.fill_price - trade.mfe_price) / trade.fill_price) * 100
                            trade.mfe_r = (trade.fill_price - trade.mfe_price) / risk_per_share
                        # MAE: highest price since fill (adverse for shorts)
                        if trade.current_price > trade.mae_price or trade.mae_price == 0:
                            trade.mae_price = trade.current_price
                            trade.mae_pct = -((trade.mae_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mae_r = -(trade.mae_price - trade.fill_price) / risk_per_share
                
                # Include realized P&L from partial exits
                total_value = trade.remaining_shares * trade.fill_price
                if total_value > 0:
                    trade.pnl_pct = ((trade.unrealized_pnl + trade.realized_pnl) / (trade.original_shares * trade.fill_price)) * 100
                
                # Update trailing stop if enabled
                if trade.trailing_stop_config.get('enabled', True):
                    await self._update_trailing_stop(trade)
                
                # Automatic stop-loss monitoring using current_stop (which may be trailing)
                effective_stop = trade.trailing_stop_config.get('current_stop', trade.stop_price)
                stop_hit = False
                if trade.direction == TradeDirection.LONG:
                    if trade.current_price <= effective_stop:
                        stop_hit = True
                        logger.warning(f"STOP HIT: {trade.symbol} price ${trade.current_price:.2f} <= stop ${effective_stop:.2f} (mode: {trade.trailing_stop_config.get('mode')})")
                else:  # SHORT
                    if trade.current_price >= effective_stop:
                        stop_hit = True
                        logger.warning(f"STOP HIT: {trade.symbol} price ${trade.current_price:.2f} >= stop ${effective_stop:.2f} (mode: {trade.trailing_stop_config.get('mode')})")
                
                if stop_hit:
                    stop_mode = trade.trailing_stop_config.get('mode', 'original')
                    reason = f"stop_loss_{stop_mode}" if stop_mode != 'original' else "stop_loss"
                    logger.info(f"Auto-closing {trade.symbol} due to {stop_mode} stop trigger")
                    await self.close_trade(trade_id, reason=reason)
                    continue
                
                # Automatic target profit-taking with scale-out
                if trade.target_prices and trade.scale_out_config.get('enabled', True):
                    await self._check_and_execute_scale_out(trade)
                
                await self._notify_trade_update(trade, "updated")
                
            except Exception as e:
                logger.error(f"Error updating position {trade_id}: {e}")

    async def _check_eod_close(self):
        """
        Close ALL open positions near market close (default: 3:57 PM ET).
        This is a critical risk management feature to avoid overnight exposure.
        
        Configurable via:
        - self._eod_close_enabled: Enable/disable EOD close
        - self._eod_close_hour: Hour in ET (24-hour format, default 15 = 3 PM)
        - self._eod_close_minute: Minute (default 57)
        """
        if not self._eod_close_enabled:
            return
        
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        
        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_str = now_et.strftime("%Y-%m-%d")
        
        # Reset the executed flag if it's a new day
        if self._last_eod_check_date != today_str:
            self._eod_close_executed_today = False
            self._last_eod_check_date = today_str
        
        # Skip if already executed today
        if self._eod_close_executed_today:
            return
        
        # Only run on weekdays during market hours
        if now_et.weekday() >= 5:
            return
        
        # Check if we're in the EOD close window (3:57-3:59 PM ET)
        eod_hour = self._eod_close_hour
        eod_minute = self._eod_close_minute
        
        # Not yet time to close
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return
        
        # After 4:00 PM, stop checking (market closed)
        if now_et.hour >= 16:
            return
        
        # Time to close all positions!
        open_count = len(self._open_trades)
        if open_count == 0:
            self._eod_close_executed_today = True
            return
        
        logger.info(f"🔔 EOD AUTO-CLOSE: Closing all {open_count} open positions at {now_et.strftime('%H:%M:%S')} ET")
        
        closed_count = 0
        total_pnl = 0.0
        
        for trade_id, trade in list(self._open_trades.items()):
            try:
                logger.info(f"  📤 EOD CLOSE: {trade.symbol} - {trade.direction.value} {trade.remaining_shares} shares")
                result = await self.close_trade(trade_id, reason="eod_auto_close")
                if result.get("success"):
                    closed_count += 1
                    total_pnl += result.get("realized_pnl", 0)
                else:
                    logger.error(f"  ❌ Failed to close {trade.symbol}: {result.get('error')}")
            except Exception as e:
                logger.error(f"  ❌ Error closing {trade.symbol}: {e}")
        
        self._eod_close_executed_today = True
        
        # Persist the EOD close event
        if self._db:
            eod_event = {
                "event_type": "eod_auto_close",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "date": today_str,
                "positions_closed": closed_count,
                "total_pnl": total_pnl,
                "close_time_et": now_et.strftime("%H:%M:%S")
            }
            await asyncio.to_thread(self._db.bot_events.insert_one, eod_event)
        
        logger.info(f"✅ EOD AUTO-CLOSE COMPLETE: Closed {closed_count} positions, Total P&L: ${total_pnl:+,.2f}")

    async def _update_trailing_stop(self, trade: BotTrade):
        """
        Update trailing stop based on targets hit:
        - Target 1 hit: Move stop to breakeven (entry price)
        - Target 2 hit: Start trailing stop (follows price by trail_pct)
        """
        targets_hit = trade.scale_out_config.get('targets_hit', [])
        trailing_config = trade.trailing_stop_config
        current_mode = trailing_config.get('mode', 'original')
        
        # Check if we need to upgrade stop mode
        if 1 in targets_hit and current_mode == 'original':
            # Target 2 hit (index 1) - start trailing
            self._activate_trailing_stop(trade)
        elif 0 in targets_hit and current_mode == 'original':
            # Target 1 hit (index 0) - move to breakeven
            self._move_stop_to_breakeven(trade)
        
        # Update trailing stop if in trailing mode
        if current_mode == 'trailing':
            self._update_trail_position(trade)
    
    def _move_stop_to_breakeven(self, trade: BotTrade):
        """Move stop to breakeven (entry price) after Target 1 hit"""
        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)
        new_stop = trade.fill_price  # Breakeven = entry price
        
        # Only move stop if it's an improvement
        if trade.direction == TradeDirection.LONG:
            if new_stop > old_stop:
                trailing_config['current_stop'] = round(new_stop, 2)
                trailing_config['mode'] = 'breakeven'
                self._record_stop_adjustment(trade, old_stop, new_stop, 'breakeven')
                logger.info(f"BREAKEVEN STOP: {trade.symbol} stop moved from ${old_stop:.2f} to ${new_stop:.2f}")
        else:  # SHORT
            if new_stop < old_stop:
                trailing_config['current_stop'] = round(new_stop, 2)
                trailing_config['mode'] = 'breakeven'
                self._record_stop_adjustment(trade, old_stop, new_stop, 'breakeven')
                logger.info(f"BREAKEVEN STOP: {trade.symbol} stop moved from ${old_stop:.2f} to ${new_stop:.2f}")
    
    def _activate_trailing_stop(self, trade: BotTrade):
        """Activate trailing stop after Target 2 hit"""
        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)
        
        # Initialize high/low water mark
        if trade.direction == TradeDirection.LONG:
            trailing_config['high_water_mark'] = trade.current_price
            # Calculate initial trailing stop
            trail_pct = trailing_config.get('trail_pct', 0.02)
            new_stop = round(trade.current_price * (1 - trail_pct), 2)
            # Don't move stop down
            new_stop = max(new_stop, old_stop)
        else:  # SHORT
            trailing_config['low_water_mark'] = trade.current_price
            trail_pct = trailing_config.get('trail_pct', 0.02)
            new_stop = round(trade.current_price * (1 + trail_pct), 2)
            # Don't move stop up
            new_stop = min(new_stop, old_stop)
        
        trailing_config['current_stop'] = new_stop
        trailing_config['mode'] = 'trailing'
        
        if new_stop != old_stop:
            self._record_stop_adjustment(trade, old_stop, new_stop, 'trailing_activated')
            logger.info(f"TRAILING STOP ACTIVATED: {trade.symbol} stop at ${new_stop:.2f} (trailing {trail_pct*100:.1f}%)")
    
    def _update_trail_position(self, trade: BotTrade):
        """Update the trailing stop position based on price movement"""
        trailing_config = trade.trailing_stop_config
        trail_pct = trailing_config.get('trail_pct', 0.02)
        old_stop = trailing_config.get('current_stop', trade.stop_price)
        
        if trade.direction == TradeDirection.LONG:
            # Update high water mark
            high_water = trailing_config.get('high_water_mark', trade.current_price)
            if trade.current_price > high_water:
                trailing_config['high_water_mark'] = trade.current_price
                # Calculate new trailing stop
                new_stop = round(trade.current_price * (1 - trail_pct), 2)
                # Only move stop up (never down for longs)
                if new_stop > old_stop:
                    trailing_config['current_stop'] = new_stop
                    self._record_stop_adjustment(trade, old_stop, new_stop, 'trail_up')
                    logger.info(f"TRAILING STOP MOVED: {trade.symbol} stop raised to ${new_stop:.2f} (high: ${trade.current_price:.2f})")
        else:  # SHORT
            # Update low water mark
            low_water = trailing_config.get('low_water_mark', trade.current_price)
            if trade.current_price < low_water:
                trailing_config['low_water_mark'] = trade.current_price
                # Calculate new trailing stop
                new_stop = round(trade.current_price * (1 + trail_pct), 2)
                # Only move stop down (never up for shorts)
                if new_stop < old_stop:
                    trailing_config['current_stop'] = new_stop
                    self._record_stop_adjustment(trade, old_stop, new_stop, 'trail_down')
                    logger.info(f"TRAILING STOP MOVED: {trade.symbol} stop lowered to ${new_stop:.2f} (low: ${trade.current_price:.2f})")
    
    def _record_stop_adjustment(self, trade: BotTrade, old_stop: float, new_stop: float, reason: str):
        """Record a stop adjustment in the trailing stop history"""
        adjustment = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'old_stop': old_stop,
            'new_stop': new_stop,
            'reason': reason,
            'price_at_adjustment': trade.current_price
        }
        trade.trailing_stop_config.setdefault('stop_adjustments', []).append(adjustment)


    async def _check_and_execute_scale_out(self, trade: BotTrade):
        """
        Check if any target prices are hit and execute scale-out sells.
        Sells 1/3 at Target 1, 1/3 at Target 2, keeps 1/3 for Target 3 (runner).
        """
        if not trade.target_prices or trade.remaining_shares <= 0:
            return
        
        targets_hit = trade.scale_out_config.get('targets_hit', [])
        scale_out_pcts = trade.scale_out_config.get('scale_out_pcts', [0.33, 0.33, 0.34])
        
        for i, target in enumerate(trade.target_prices):
            if i in targets_hit:
                continue  # Already sold at this target
            
            # Check if target is hit
            target_hit = False
            if trade.direction == TradeDirection.LONG:
                if trade.current_price >= target:
                    target_hit = True
            else:  # SHORT
                if trade.current_price <= target:
                    target_hit = True
            
            if target_hit:
                # Calculate shares to sell at this target
                pct_to_sell = scale_out_pcts[i] if i < len(scale_out_pcts) else 0.34
                
                # For last target, sell all remaining
                if i == len(trade.target_prices) - 1:
                    shares_to_sell = trade.remaining_shares
                else:
                    shares_to_sell = max(1, int(trade.original_shares * pct_to_sell))
                    shares_to_sell = min(shares_to_sell, trade.remaining_shares)
                
                if shares_to_sell <= 0:
                    continue
                
                logger.info(f"TARGET {i+1} HIT: {trade.symbol} - Scaling out {shares_to_sell} shares at ${trade.current_price:.2f}")
                
                # Execute partial exit
                exit_result = await self._execute_partial_exit(trade, shares_to_sell, target, i)
                
                if exit_result.get('success'):
                    fill_price = exit_result.get('fill_price', trade.current_price)
                    
                    # Calculate P&L for this scale-out
                    if trade.direction == TradeDirection.LONG:
                        partial_pnl = (fill_price - trade.fill_price) * shares_to_sell
                    else:
                        partial_pnl = (trade.fill_price - fill_price) * shares_to_sell
                    
                    # Update trade state
                    trade.remaining_shares -= shares_to_sell
                    trade.realized_pnl += partial_pnl
                    
                    # Track commission for partial exit
                    scale_commission = self._apply_commission(trade, shares_to_sell)
                    
                    targets_hit.append(i)
                    trade.scale_out_config['targets_hit'] = targets_hit
                    
                    # Record the partial exit
                    partial_exit_record = {
                        'target_idx': i + 1,
                        'target_price': target,
                        'shares_sold': shares_to_sell,
                        'fill_price': fill_price,
                        'pnl': partial_pnl,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                    trade.scale_out_config.setdefault('partial_exits', []).append(partial_exit_record)
                    
                    logger.info(f"Scale-out complete: {trade.symbol} T{i+1} - Sold {shares_to_sell} @ ${fill_price:.2f}, P&L: ${partial_pnl:.2f}, Remaining: {trade.remaining_shares}")
                    
                    await self._notify_trade_update(trade, f"scale_out_t{i+1}")
                    
                    # If all shares sold, close the trade
                    if trade.remaining_shares <= 0:
                        trade.status = TradeStatus.CLOSED
                        trade.closed_at = datetime.now(timezone.utc).isoformat()
                        trade.close_reason = f"target_{i+1}_complete"
                        trade.exit_price = fill_price
                        trade.unrealized_pnl = 0
                        
                        # Update daily stats with net P&L (after commissions)
                        if trade.net_pnl > 0:
                            self._daily_stats.trades_won += 1
                            self._daily_stats.largest_win = max(self._daily_stats.largest_win, trade.net_pnl)
                        else:
                            self._daily_stats.trades_lost += 1
                            self._daily_stats.largest_loss = min(self._daily_stats.largest_loss, trade.net_pnl)
                        
                        self._daily_stats.net_pnl += trade.net_pnl
                        total = self._daily_stats.trades_won + self._daily_stats.trades_lost
                        self._daily_stats.win_rate = (self._daily_stats.trades_won / total * 100) if total > 0 else 0
                        
                        # Move to closed trades
                        del self._open_trades[trade.id]
                        self._closed_trades.append(trade)
                        
                        await self._notify_trade_update(trade, "closed")
                        await self._save_trade(trade)
                        
                        # Log to regime performance tracking
                        await self._log_trade_to_regime_performance(trade)
                        
                        logger.info(f"Trade fully closed at Target {i+1}: {trade.symbol} Total P&L: ${trade.realized_pnl:.2f}")
                        return
    
    async def _execute_partial_exit(self, trade: BotTrade, shares: int, target_price: float, target_idx: int) -> Dict:
        """Execute a partial position exit (scale-out)"""
        if not self._trade_executor:
            # Simulated exit
            return {
                'success': True,
                'fill_price': trade.current_price,
                'shares': shares,
                'simulated': True
            }
        
        try:
            # Use trade executor to sell partial position
            result = await self._trade_executor.execute_partial_exit(trade, shares)
            return result
        except Exception as e:
            logger.error(f"Partial exit error: {e}")
            # Fall back to simulated
            return {
                'success': True,
                'fill_price': trade.current_price,
                'shares': shares,
                'simulated': True
            }

    
    async def close_trade(self, trade_id: str, reason: str = "manual") -> bool:
        """Close an open trade (sells remaining shares)"""
        if trade_id not in self._open_trades:
            return False
        
        trade = self._open_trades[trade_id]
        
        # Use remaining shares if we've done partial exits, otherwise use original shares
        shares_to_close = trade.remaining_shares if trade.remaining_shares > 0 else trade.shares
        
        try:
            if self._trade_executor and shares_to_close > 0:
                # Update trade.shares temporarily for the executor
                original_shares = trade.shares
                trade.shares = shares_to_close
                
                result = await self._trade_executor.close_position(trade)
                
                trade.shares = original_shares  # Restore
                
                if result.get('success'):
                    trade.exit_price = result.get('fill_price', trade.current_price)
            else:
                trade.exit_price = trade.current_price
            
            # Calculate realized P&L for remaining shares and add to cumulative
            if shares_to_close > 0:
                if trade.direction == TradeDirection.LONG:
                    final_pnl = (trade.exit_price - trade.fill_price) * shares_to_close
                else:
                    final_pnl = (trade.fill_price - trade.exit_price) * shares_to_close
                trade.realized_pnl += final_pnl
                
                # Track exit commission
                exit_commission = self._apply_commission(trade, shares_to_close)
                logger.info(f"Exit commission: ${exit_commission:.2f} | Total commissions: ${trade.total_commissions:.2f} | Net P&L: ${trade.net_pnl:.2f}")
            
            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0
            
            # Update daily stats with net P&L (after commissions)
            self._daily_stats.net_pnl += trade.net_pnl
            if trade.realized_pnl > 0:
                self._daily_stats.trades_won += 1
                self._daily_stats.largest_win = max(self._daily_stats.largest_win, trade.realized_pnl)
            else:
                self._daily_stats.trades_lost += 1
                self._daily_stats.largest_loss = min(self._daily_stats.largest_loss, trade.realized_pnl)
            
            # Calculate win rate
            total = self._daily_stats.trades_won + self._daily_stats.trades_lost
            self._daily_stats.win_rate = (self._daily_stats.trades_won / total * 100) if total > 0 else 0
            
            # Move to closed trades
            del self._open_trades[trade_id]
            self._closed_trades.append(trade)
            
            await self._notify_trade_update(trade, "closed")
            await self._save_trade(trade)
            
            # Auto-record exit to Trade Journal
            await self._log_trade_to_journal(trade, "exit")
            
            # Record performance for learning loop
            if hasattr(self, '_perf_service') and self._perf_service:
                try:
                    self._perf_service.record_trade(trade.to_dict())
                except Exception as e:
                    logger.warning(f"Failed to record trade performance: {e}")
            
            # NEW: Record to Learning Loop (Phase 1)
            if hasattr(self, '_learning_loop') and self._learning_loop:
                try:
                    outcome = "won" if trade.realized_pnl > 0 else ("lost" if trade.realized_pnl < 0 else "breakeven")
                    asyncio.create_task(self._learning_loop.record_trade_outcome(
                        trade_id=trade.id,
                        alert_id=getattr(trade, 'alert_id', trade.id),
                        symbol=trade.symbol,
                        setup_type=trade.setup_type,
                        strategy_name=trade.setup_type,
                        direction=trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction),
                        trade_style=getattr(trade, 'trade_style', 'move_2_move'),
                        entry_price=trade.fill_price,
                        exit_price=trade.exit_price,
                        stop_price=trade.stop_loss,
                        target_price=trade.targets[0] if trade.targets else trade.fill_price * 1.02,
                        outcome=outcome,
                        pnl=trade.realized_pnl,
                        entry_time=trade.opened_at,
                        exit_time=trade.closed_at,
                        confirmation_signals=getattr(trade, 'confirmation_signals', [])
                    ))
                except Exception as e:
                    logger.warning(f"Failed to record trade to learning loop: {e}")
            
            # Log to regime performance tracking
            await self._log_trade_to_regime_performance(trade)
            
            logger.info(f"Trade closed ({reason}): {trade.symbol} P&L: ${trade.realized_pnl:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Error closing trade: {e}")
            return False
    
    # ==================== DATA ACCESS ====================
    
    def get_status(self) -> Dict:
        """Get bot status summary"""
        return {
            "running": self._running,
            "mode": self._mode.value,
            "risk_params": {
                "max_risk_per_trade": self.risk_params.max_risk_per_trade,
                "max_daily_loss": self.risk_params.max_daily_loss,
                "starting_capital": self.risk_params.starting_capital,
                "max_position_pct": self.risk_params.max_position_pct,
                "max_open_positions": self.risk_params.max_open_positions,
                "min_risk_reward": self.risk_params.min_risk_reward
            },
            "enabled_setups": self._enabled_setups,
            "strategy_configs": self.get_strategy_configs(),
            "pending_trades": len(self._pending_trades),
            "open_trades": len(self._open_trades),
            "daily_stats": asdict(self._daily_stats)
        }
    
    def get_pending_trades(self) -> List[Dict]:
        """Get all pending trades awaiting confirmation"""
        return [t.to_dict() for t in self._pending_trades.values()]
    
    def get_open_trades(self) -> List[Dict]:
        """Get all open positions"""
        return [t.to_dict() for t in self._open_trades.values()]
    
    def get_closed_trades(self, limit: int = 50) -> List[Dict]:
        """Get closed trades history"""
        return [t.to_dict() for t in self._closed_trades[-limit:]]
    
    def get_trade(self, trade_id: str) -> Optional[Dict]:
        """Get a specific trade by ID"""
        if trade_id in self._pending_trades:
            return self._pending_trades[trade_id].to_dict()
        if trade_id in self._open_trades:
            return self._open_trades[trade_id].to_dict()
        for trade in self._closed_trades:
            if trade.id == trade_id:
                return trade.to_dict()
        return None
    
    def get_daily_stats(self) -> Dict:
        """Get daily trading statistics"""
        return asdict(self._daily_stats)
    
    async def reconcile_positions_with_ib(self) -> Dict:
        """
        Reconcile bot's internal trades with actual IB positions.
        Returns a report of discrepancies and optionally syncs them.
        
        This is critical for:
        1. Session persistence - ensuring state matches reality after restart
        2. Detecting manual trades made outside the bot
        3. Catching missed fills or order execution issues
        """
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bot_positions": [],
            "ib_positions": [],
            "discrepancies": [],
            "synced": False,
            "actions_taken": []
        }
        
        try:
            # Get IB positions from pushed data
            from routers.ib import _pushed_ib_data, is_pusher_connected
            
            if not is_pusher_connected():
                report["error"] = "IB pusher not connected - cannot reconcile"
                return report
            
            ib_positions = _pushed_ib_data.get("positions", [])
            
            # Convert to comparable format
            ib_pos_map = {}
            for pos in ib_positions:
                symbol = pos.get("symbol", pos.get("contract", {}).get("symbol", ""))
                if symbol:
                    qty = float(pos.get("position", pos.get("qty", 0)))
                    ib_pos_map[symbol] = {
                        "symbol": symbol,
                        "qty": qty,
                        "avg_cost": float(pos.get("avgCost", pos.get("avg_cost", 0))),
                        "market_value": float(pos.get("marketValue", pos.get("market_value", 0))),
                        "unrealized_pnl": float(pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)))
                    }
                    report["ib_positions"].append(ib_pos_map[symbol])
            
            # Get bot's open trades
            bot_pos_map = {}
            for trade in self._open_trades.values():
                symbol = trade.symbol
                # Account for direction
                qty = trade.remaining_shares if trade.direction == TradeDirection.LONG else -trade.remaining_shares
                bot_pos_map[symbol] = {
                    "symbol": symbol,
                    "qty": qty,
                    "trade_id": trade.id,
                    "fill_price": trade.fill_price,
                    "direction": trade.direction.value
                }
                report["bot_positions"].append(bot_pos_map[symbol])
            
            # Find discrepancies
            all_symbols = set(ib_pos_map.keys()) | set(bot_pos_map.keys())
            
            for symbol in all_symbols:
                ib_pos = ib_pos_map.get(symbol)
                bot_pos = bot_pos_map.get(symbol)
                
                if ib_pos and not bot_pos:
                    # Position exists in IB but not tracked by bot
                    report["discrepancies"].append({
                        "type": "untracked_position",
                        "symbol": symbol,
                        "ib_qty": ib_pos["qty"],
                        "bot_qty": 0,
                        "message": f"{symbol}: Position in IB ({ib_pos['qty']} shares) not tracked by bot"
                    })
                
                elif bot_pos and not ib_pos:
                    # Bot thinks we have a position but IB doesn't show it
                    report["discrepancies"].append({
                        "type": "phantom_position",
                        "symbol": symbol,
                        "ib_qty": 0,
                        "bot_qty": bot_pos["qty"],
                        "trade_id": bot_pos["trade_id"],
                        "message": f"{symbol}: Bot tracking position ({bot_pos['qty']} shares) but not in IB - may have been closed"
                    })
                
                elif ib_pos and bot_pos:
                    # Both have position - check if quantities match
                    ib_qty = ib_pos["qty"]
                    bot_qty = bot_pos["qty"]
                    
                    if abs(ib_qty - bot_qty) > 0.1:  # Allow small floating point differences
                        report["discrepancies"].append({
                            "type": "quantity_mismatch",
                            "symbol": symbol,
                            "ib_qty": ib_qty,
                            "bot_qty": bot_qty,
                            "trade_id": bot_pos["trade_id"],
                            "message": f"{symbol}: IB shows {ib_qty} shares, bot tracking {bot_qty} shares"
                        })
            
            report["synced"] = len(report["discrepancies"]) == 0
            
            if report["discrepancies"]:
                logger.warning(f"Position reconciliation found {len(report['discrepancies'])} discrepancies")
                for d in report["discrepancies"]:
                    logger.warning(f"  - {d['message']}")
            else:
                logger.info("Position reconciliation: All positions match ✓")
            
            return report
            
        except Exception as e:
            logger.error(f"Position reconciliation error: {e}")
            report["error"] = str(e)
            return report
    
    async def sync_position_from_ib(self, symbol: str, auto_create_trade: bool = False) -> Dict:
        """
        Sync a single position from IB to the bot's tracking.
        Use this to import positions that were opened manually or outside the bot.
        
        Args:
            symbol: Stock symbol to sync
            auto_create_trade: If True, automatically create a bot trade entry for untracked positions
        
        Returns:
            Dict with sync result
        """
        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected
            
            if not is_pusher_connected():
                return {"success": False, "error": "IB pusher not connected"}
            
            ib_positions = _pushed_ib_data.get("positions", [])
            ib_pos = None
            
            for pos in ib_positions:
                pos_symbol = pos.get("symbol", pos.get("contract", {}).get("symbol", ""))
                if pos_symbol.upper() == symbol.upper():
                    ib_pos = pos
                    break
            
            if not ib_pos:
                return {"success": False, "error": f"No IB position found for {symbol}"}
            
            qty = float(ib_pos.get("position", ib_pos.get("qty", 0)))
            avg_cost = float(ib_pos.get("avgCost", ib_pos.get("avg_cost", 0)))
            
            # Check if bot already tracks this
            existing_trade = None
            for trade in self._open_trades.values():
                if trade.symbol.upper() == symbol.upper():
                    existing_trade = trade
                    break
            
            if existing_trade:
                # Update existing trade
                existing_trade.remaining_shares = abs(qty)
                existing_trade.shares = abs(qty)
                existing_trade.fill_price = avg_cost
                logger.info(f"Updated existing trade for {symbol}: {qty} shares @ ${avg_cost:.2f}")
                return {
                    "success": True,
                    "action": "updated",
                    "trade_id": existing_trade.id,
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost
                }
            
            elif auto_create_trade:
                # Create new trade entry for this position
                direction = TradeDirection.LONG if qty > 0 else TradeDirection.SHORT
                
                # Calculate price levels
                target_1 = avg_cost * 1.05 if direction == TradeDirection.LONG else avg_cost * 0.95
                target_2 = avg_cost * 1.10 if direction == TradeDirection.LONG else avg_cost * 0.90
                target_3 = avg_cost * 1.15 if direction == TradeDirection.LONG else avg_cost * 0.85
                stop = avg_cost * 0.95 if direction == TradeDirection.LONG else avg_cost * 1.05
                
                risk_per_share = abs(avg_cost - stop)
                reward_per_share = abs(target_2 - avg_cost)
                
                # Generate unique ID
                import uuid
                trade_id = str(uuid.uuid4())[:8]
                
                # Create a synthetic trade with all required fields
                trade = BotTrade(
                    id=trade_id,
                    symbol=symbol.upper(),
                    direction=direction,
                    status=TradeStatus.OPEN,  # Use OPEN for active positions
                    setup_type="imported_from_ib",
                    timeframe="daily",
                    quality_score=50,
                    quality_grade="B",
                    entry_price=avg_cost,
                    current_price=avg_cost,
                    stop_price=stop,
                    target_prices=[target_1, target_2, target_3],
                    shares=int(abs(qty)),
                    risk_amount=risk_per_share * abs(qty),
                    potential_reward=reward_per_share * abs(qty),
                    risk_reward_ratio=reward_per_share / risk_per_share if risk_per_share > 0 else 2.0
                )
                trade.fill_price = avg_cost
                trade.remaining_shares = int(abs(qty))
                trade.original_shares = int(abs(qty))
                trade.entry_time = datetime.now(timezone.utc)
                trade.notes = "Imported from IB - position existed before bot tracking"
                
                self._open_trades[trade.id] = trade
                
                # Save to MongoDB using the persist method (handles enum serialization)
                await asyncio.to_thread(self._persist_trade, trade)
                
                logger.info(f"Created new trade for imported position: {symbol} {int(abs(qty))} shares @ ${avg_cost:.2f}")
                return {
                    "success": True,
                    "action": "created",
                    "trade_id": trade.id,
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Position {symbol} not tracked by bot. Set auto_create_trade=True to import it."
                }
                
        except Exception as e:
            import traceback
            logger.error(f"Error syncing position {symbol}: {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}
    
    async def close_phantom_position(self, trade_id: str, reason: str = "not_in_ib") -> Dict:
        """
        Close a bot trade that no longer exists in IB.
        This handles cases where positions were manually closed or stopped out.
        """
        try:
            if trade_id not in self._open_trades:
                return {"success": False, "error": f"Trade {trade_id} not found in open trades"}
            
            trade = self._open_trades[trade_id]
            
            # Move to closed trades
            trade.status = TradeStatus.CLOSED
            trade.exit_time = datetime.now(timezone.utc)
            trade.exit_reason = reason
            
            # We don't know the actual exit price, use current price if available or fill price
            if trade.current_price and trade.current_price > 0:
                trade.exit_price = trade.current_price
            else:
                trade.exit_price = trade.fill_price  # Assume breakeven if no price
            
            # Calculate final P&L
            if trade.direction == TradeDirection.LONG:
                trade.realized_pnl = (trade.exit_price - trade.fill_price) * trade.remaining_shares
            else:
                trade.realized_pnl = (trade.fill_price - trade.exit_price) * trade.remaining_shares
            
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0
            
            # Move from open to closed
            del self._open_trades[trade_id]
            self._closed_trades.append(trade)
            
            # Update MongoDB
            update_doc = {
                "status": TradeStatus.CLOSED.value,
                "exit_time": trade.exit_time.isoformat(),
                "exit_price": trade.exit_price,
                "exit_reason": trade.exit_reason,
                "realized_pnl": trade.realized_pnl,
                "unrealized_pnl": 0,
                "remaining_shares": 0
            }
            await asyncio.to_thread(
                self._db.bot_trades.update_one,
                {"id": trade_id}, {"$set": update_doc}
            )
            
            logger.info(f"Closed phantom trade {trade.symbol} ({trade_id}): reason={reason}, P&L=${trade.realized_pnl:.2f}")
            
            return {
                "success": True,
                "trade_id": trade_id,
                "symbol": trade.symbol,
                "action": "closed",
                "reason": reason,
                "realized_pnl": trade.realized_pnl
            }
            
        except Exception as e:
            logger.error(f"Error closing phantom position {trade_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def full_position_sync(self) -> Dict:
        """
        Comprehensive position sync that:
        1. Imports untracked IB positions
        2. Closes phantom positions (bot has, IB doesn't)
        3. Fixes quantity mismatches
        4. Fixes direction mismatches
        
        Returns detailed report of all actions taken.
        """
        report = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "imported": [],
            "closed_phantom": [],
            "updated": [],
            "errors": []
        }
        
        try:
            # First get reconciliation report
            recon = await self.reconcile_positions_with_ib()
            
            if recon.get("error"):
                report["success"] = False
                report["error"] = recon["error"]
                return report
            
            for disc in recon.get("discrepancies", []):
                disc_type = disc["type"]
                symbol = disc["symbol"]
                
                try:
                    if disc_type == "untracked_position":
                        # Import from IB
                        result = await self.sync_position_from_ib(symbol, auto_create_trade=True)
                        if result.get("success"):
                            report["imported"].append({
                                "symbol": symbol,
                                "qty": disc["ib_qty"],
                                "trade_id": result.get("trade_id")
                            })
                        else:
                            report["errors"].append({"symbol": symbol, "error": result.get("error"), "type": "import"})
                    
                    elif disc_type == "phantom_position":
                        # Close the phantom trade
                        trade_id = disc.get("trade_id")
                        if trade_id:
                            result = await self.close_phantom_position(trade_id, reason="closed_outside_bot")
                            if result.get("success"):
                                report["closed_phantom"].append({
                                    "symbol": symbol,
                                    "trade_id": trade_id,
                                    "realized_pnl": result.get("realized_pnl", 0)
                                })
                            else:
                                report["errors"].append({"symbol": symbol, "error": result.get("error"), "type": "close_phantom"})
                    
                    elif disc_type == "quantity_mismatch":
                        # Update the trade quantity to match IB
                        trade_id = disc.get("trade_id")
                        ib_qty = disc["ib_qty"]
                        
                        if trade_id and trade_id in self._open_trades:
                            trade = self._open_trades[trade_id]
                            old_qty = trade.remaining_shares
                            
                            # Check if direction changed (long to short or vice versa)
                            ib_direction = TradeDirection.LONG if ib_qty > 0 else TradeDirection.SHORT
                            
                            if ib_direction != trade.direction:
                                # Direction flipped - this is a significant change
                                # Close the old trade and create new one
                                await self.close_phantom_position(trade_id, reason="direction_changed")
                                result = await self.sync_position_from_ib(symbol, auto_create_trade=True)
                                report["updated"].append({
                                    "symbol": symbol,
                                    "action": "direction_changed",
                                    "old_direction": trade.direction.value,
                                    "new_direction": ib_direction.value,
                                    "new_qty": abs(ib_qty)
                                })
                            else:
                                # Same direction, just quantity changed
                                trade.remaining_shares = abs(ib_qty)
                                trade.shares = abs(ib_qty)
                                
                                # Update MongoDB
                                update_doc = {
                                    "remaining_shares": abs(ib_qty),
                                    "shares": abs(ib_qty)
                                }
                                await asyncio.to_thread(
                                    self._db.bot_trades.update_one,
                                    {"id": trade_id}, {"$set": update_doc}
                                )
                                
                                report["updated"].append({
                                    "symbol": symbol,
                                    "trade_id": trade_id,
                                    "old_qty": old_qty,
                                    "new_qty": abs(ib_qty),
                                    "action": "quantity_updated"
                                })
                
                except Exception as e:
                    report["errors"].append({"symbol": symbol, "error": str(e), "type": disc_type})
            
            # Final reconciliation check
            final_recon = await self.reconcile_positions_with_ib()
            report["final_synced"] = final_recon.get("synced", False)
            report["remaining_discrepancies"] = len(final_recon.get("discrepancies", []))
            
            logger.info(f"Full position sync complete: imported={len(report['imported'])}, closed={len(report['closed_phantom'])}, updated={len(report['updated'])}, errors={len(report['errors'])}")
            
            return report
            
        except Exception as e:
            logger.error(f"Full position sync error: {e}")
            report["success"] = False
            report["error"] = str(e)
            return report
    
    # ==================== REGIME PERFORMANCE LOGGING ====================
    
    async def _log_trade_to_regime_performance(self, trade: BotTrade):
        """
        Log a closed trade to the regime performance tracking service.
        This allows analysis of strategy performance across different market regimes.
        """
        if self._regime_performance_service is None:
            logger.debug("Regime performance service not available - skipping trade logging")
            return
        
        try:
            # Build trade data for logging
            trade_data = {
                "trade_id": trade.id,
                "setup_type": trade.setup_type,
                "market_regime": trade.market_regime,
                "direction": trade.direction.value if hasattr(trade.direction, 'value') else trade.direction,
                "realized_pnl": trade.realized_pnl,
                "shares": trade.shares,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "regime_score": trade.regime_score,
                "regime_position_multiplier": trade.regime_position_multiplier,
                "risk_amount": trade.risk_amount,
                "closed_at": trade.closed_at
            }
            
            # Log to the regime performance service
            await self._regime_performance_service.log_trade(trade_data)
            
            logger.info(f"📊 Trade logged to regime performance: {trade.symbol} {trade.setup_type} "
                       f"in {trade.market_regime} regime, P&L: ${trade.realized_pnl:.2f}")
            
        except Exception as e:
            logger.error(f"Error logging trade to regime performance: {e}")
    
    # ==================== PERSISTENCE ====================
    
    async def _save_trade(self, trade: BotTrade):
        """Save trade to database"""
        if self._db is None:
            return
        
        try:
            trades_col = self._db["bot_trades"]
            trade_dict = trade.to_dict()
            trade_dict['_id'] = trade.id
            
            await asyncio.to_thread(
                lambda: trades_col.replace_one(
                    {"_id": trade.id},
                    trade_dict,
                    upsert=True
                )
            )
        except Exception as e:
            logger.error(f"Error saving trade: {e}")
    
    async def load_trades_from_db(self):
        """Load trades from database on startup"""
        if self._db is None:
            return
        
        try:
            def _sync_load():
                trades_col = self._db["bot_trades"]
                return list(trades_col.find({"status": "open"}))

            docs = await asyncio.to_thread(_sync_load)
            for doc in docs:
                doc.pop('_id', None)
                trade = self._dict_to_trade(doc)
                if trade:
                    self._open_trades[trade.id] = trade
            
            logger.info(f"Loaded {len(self._open_trades)} open trades from database")
            
        except Exception as e:
            logger.error(f"Error loading trades: {e}")
    
    def _dict_to_trade(self, d: Dict) -> Optional[BotTrade]:
        """Convert dictionary to BotTrade"""
        try:
            return BotTrade(
                id=d.get('id', ''),
                symbol=d.get('symbol', ''),
                direction=TradeDirection(d.get('direction', 'long')),
                status=TradeStatus(d.get('status', 'pending')),
                setup_type=d.get('setup_type', ''),
                timeframe=d.get('timeframe', 'intraday'),
                quality_score=d.get('quality_score', 0),
                quality_grade=d.get('quality_grade', ''),
                entry_price=d.get('entry_price', 0),
                current_price=d.get('current_price', 0),
                stop_price=d.get('stop_price', 0),
                target_prices=d.get('target_prices', []),
                shares=d.get('shares', 0),
                risk_amount=d.get('risk_amount', 0),
                potential_reward=d.get('potential_reward', 0),
                risk_reward_ratio=d.get('risk_reward_ratio', 0),
                fill_price=d.get('fill_price'),
                exit_price=d.get('exit_price'),
                unrealized_pnl=d.get('unrealized_pnl', 0),
                realized_pnl=d.get('realized_pnl', 0),
                pnl_pct=d.get('pnl_pct', 0),
                created_at=d.get('created_at', ''),
                executed_at=d.get('executed_at'),
                closed_at=d.get('closed_at'),
                estimated_duration=d.get('estimated_duration', ''),
                close_at_eod=d.get('close_at_eod', True),
                explanation=None,
                entry_order_id=d.get('entry_order_id'),
                stop_order_id=d.get('stop_order_id'),
                target_order_ids=d.get('target_order_ids', [])
            )
        except Exception as e:
            logger.error(f"Error deserializing trade: {e}")
            return None
    
    # ==================== SCANNER AUTO-EXECUTION ====================
    
    async def submit_trade_from_scanner(self, trade_request: Dict):
        """
        Submit a trade from the enhanced scanner for auto-execution.
        Called when a high-priority alert with tape confirmation is detected.
        """
        try:
            symbol = trade_request.get('symbol')
            direction = trade_request.get('direction', 'long')
            setup_type = trade_request.get('setup_type')
            entry_price = trade_request.get('entry_price')
            stop_loss = trade_request.get('stop_loss')
            target = trade_request.get('target')
            alert_id = trade_request.get('alert_id')
            
            logger.info(f"🤖 Scanner auto-submit: {symbol} {direction.upper()} {setup_type}")
            
            # Create alert dict for existing evaluation flow
            alert = {
                'symbol': symbol,
                'setup_type': setup_type,
                'direction': direction,
                'current_price': entry_price,
                'trigger_price': entry_price,
                'stop_price': stop_loss,
                'targets': [target],
                'score': 80,  # Auto-execute alerts are pre-screened
                'trigger_probability': 0.65,
                'headline': f"Auto-execute: {setup_type} on {symbol}",
                'technical_reasons': [
                    f"Tape confirmed {setup_type} setup",
                    "Auto-executed from scanner alert"
                ],
                'warnings': [],
                'source': 'scanner_auto_execute',
                'alert_id': alert_id
            }
            
            # Evaluate and create trade
            trade = await self._evaluate_opportunity(alert)
            
            if trade:
                if self._mode == BotMode.AUTONOMOUS:
                    # Direct execution
                    await self._execute_trade(trade)
                    logger.info(f"✅ Auto-executed: {trade.symbol} {trade.direction.value.upper()}")
                else:
                    # Add to pending for confirmation
                    self._pending_trades[trade.id] = trade
                    await self._notify_trade_update(trade, "pending")
                    logger.info(f"⏳ Auto-submit pending confirmation: {trade.symbol}")
                
                return {"success": True, "trade_id": trade.id}
            else:
                logger.warning(f"Scanner auto-submit rejected: {symbol} did not pass evaluation")
                return {"success": False, "reason": "Failed evaluation"}
                
        except Exception as e:
            logger.error(f"Scanner auto-submit error: {e}")
            return {"success": False, "reason": str(e)}

    async def _log_trade_to_journal(self, trade: BotTrade, action: str = "entry"):
        """
        Auto-record a trade to the Trade Journal.
        
        Args:
            trade: The BotTrade object
            action: "entry" for new trades, "exit" for closed trades
        """
        if not self._trade_journal:
            logger.debug("Trade journal not configured - skipping auto-record")
            return
        
        try:
            # Get current market regime for context
            regime = self._current_regime or "UNKNOWN"
            
            # Build journal entry based on action type
            if action == "entry":
                journal_entry = {
                    "symbol": trade.symbol,
                    "direction": trade.direction.value.upper(),
                    "entry_price": trade.fill_price or trade.entry_price,
                    "entry_date": (trade.executed_at or datetime.now(timezone.utc).isoformat())[:10],
                    "shares": trade.shares,
                    "stop_loss": trade.stop_price,
                    "target": trade.target_prices[0] if trade.target_prices else None,
                    "setup_type": trade.setup_type or "bot_trade",
                    "setup_variant": trade.setup_variant,
                    "strategy": trade.setup_type or "Auto-Trade",
                    "market_regime": regime,
                    "entry_context": trade.entry_context,
                    "notes": f"[AUTO-RECORDED by Trading Bot]\nSetup: {trade.setup_type} ({trade.setup_variant})\nReason: {trade.notes or 'Bot execution'}",
                    "status": "open",
                    "tags": ["auto-recorded", "trading-bot", regime.lower()],
                    "bot_trade_id": trade.id,
                }
                
                result = await self._trade_journal.log_trade(journal_entry)
                if result.get("success"):
                    logger.info(f"📓 Auto-recorded ENTRY to journal: {trade.symbol} {trade.direction.value}")
                else:
                    logger.warning(f"Failed to record entry: {result.get('error', 'Unknown error')}")
                
            elif action == "exit":
                # For exits, we update the existing trade entry if possible
                # First try to find the existing journal entry by bot_trade_id
                try:
                    existing = await asyncio.to_thread(
                        self._trade_journal.db.trades.find_one,
                        {"bot_trade_id": trade.id}
                    )
                    
                    if existing:
                        # Update the existing entry with exit data + MFE/MAE
                        update_data = {
                            "exit_price": trade.exit_price,
                            "exit_date": (trade.closed_at or datetime.now(timezone.utc).isoformat())[:10],
                            "pnl": trade.realized_pnl,
                            "pnl_percent": trade.pnl_pct,
                            "status": "closed",
                            "exit_reason": trade.close_reason or "closed",
                            "mfe_price": trade.mfe_price,
                            "mfe_pct": round(trade.mfe_pct, 2),
                            "mfe_r": round(trade.mfe_r, 2),
                            "mae_price": trade.mae_price,
                            "mae_pct": round(trade.mae_pct, 2),
                            "mae_r": round(trade.mae_r, 2),
                            "notes": existing.get("notes", "") + (
                                f"\n\n[EXIT] Reason: {trade.close_reason or 'closed'}, "
                                f"P&L: ${trade.realized_pnl:+,.2f}\n"
                                f"MFE: {trade.mfe_pct:+.2f}% ({trade.mfe_r:+.2f}R) | "
                                f"MAE: {trade.mae_pct:+.2f}% ({trade.mae_r:+.2f}R)"
                            ),
                        }
                        
                        await asyncio.to_thread(
                            self._trade_journal.db.trades.update_one,
                            {"_id": existing["_id"]}, {"$set": update_data}
                        )
                        logger.info(f"📓 Auto-recorded EXIT to journal: {trade.symbol} P&L: ${trade.realized_pnl:+,.2f}")
                    else:
                        # No existing entry found, create a complete closed trade entry
                        journal_entry = {
                            "symbol": trade.symbol,
                            "direction": trade.direction.value.upper(),
                            "entry_price": trade.fill_price,
                            "entry_date": (trade.executed_at or datetime.now(timezone.utc).isoformat())[:10],
                            "exit_price": trade.exit_price,
                            "exit_date": (trade.closed_at or datetime.now(timezone.utc).isoformat())[:10],
                            "shares": trade.shares,
                            "pnl": trade.realized_pnl,
                            "pnl_percent": trade.pnl_pct,
                            "status": "closed",
                            "setup_type": trade.setup_type or "bot_trade",
                            "setup_variant": trade.setup_variant,
                            "strategy": trade.setup_type or "Auto-Trade",
                            "market_regime": regime,
                            "entry_context": trade.entry_context,
                            "mfe_price": trade.mfe_price,
                            "mfe_pct": round(trade.mfe_pct, 2),
                            "mfe_r": round(trade.mfe_r, 2),
                            "mae_price": trade.mae_price,
                            "mae_pct": round(trade.mae_pct, 2),
                            "mae_r": round(trade.mae_r, 2),
                            "notes": (
                                f"[AUTO-RECORDED by Trading Bot]\n"
                                f"Exit Reason: {trade.close_reason or 'closed'}\n"
                                f"MFE: {trade.mfe_pct:+.2f}% ({trade.mfe_r:+.2f}R) | "
                                f"MAE: {trade.mae_pct:+.2f}% ({trade.mae_r:+.2f}R)"
                            ),
                            "tags": ["auto-recorded", "trading-bot", regime.lower()],
                            "bot_trade_id": trade.id,
                        }
                        
                        await self._trade_journal.log_trade(journal_entry)
                        logger.info(f"📓 Auto-recorded complete trade to journal: {trade.symbol} P&L: ${trade.realized_pnl:+,.2f}")
                        
                except Exception as e:
                    logger.error(f"Error finding/updating journal entry: {e}")
                
        except Exception as e:
            logger.error(f"Failed to auto-record trade to journal: {e}")



# Singleton instance
_trading_bot_service: Optional[TradingBotService] = None


def get_trading_bot_service() -> TradingBotService:
    """Get or create the trading bot service singleton"""
    global _trading_bot_service
    if _trading_bot_service is None:
        _trading_bot_service = TradingBotService()
    return _trading_bot_service
