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
        
        # Extracted modules (Phase: refactoring)
        from services.stop_manager import StopManager
        from services.trade_intelligence import TradeIntelligence
        from services.trade_execution import TradeExecution
        from services.position_reconciler import PositionReconciler
        from services.position_manager import PositionManager
        from services.bot_persistence import BotPersistence
        from services.opportunity_evaluator import OpportunityEvaluator
        from services.scanner_integration import ScannerIntegration
        self._stop_manager = StopManager()
        self._trade_intel = TradeIntelligence()
        self._trade_execution = TradeExecution()
        self._position_reconciler = PositionReconciler()
        self._position_manager = PositionManager()
        self._persistence = BotPersistence()
        self._opportunity_evaluator = OpportunityEvaluator()
        self._scanner_integration = ScannerIntegration()
        
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
        """Restore bot state — delegated to BotPersistence module."""
        await self._persistence.restore_state(self)
    
    async def _restore_closed_trades(self):
        """Restore closed trades — delegated to BotPersistence module."""
        await self._persistence.restore_closed_trades(self)
    
    async def _restore_open_trades(self):
        """Restore open trades — delegated to BotPersistence module."""
        await self._persistence.restore_open_trades(self)

    async def _delayed_reconciliation(self):
        """Startup reconciliation — delegated to BotPersistence module."""
        await self._persistence.delayed_reconciliation(self)
    
    async def _save_state(self):
        """Save bot state — delegated to BotPersistence module."""
        await self._persistence.save_state(self)

    def _persist_trade(self, trade: 'BotTrade'):
        """Persist a single trade — delegated to BotPersistence module."""
        self._persistence.persist_trade(trade, self)

    def _persist_all_open_trades(self):
        """Persist all open trades — delegated to BotPersistence module."""
        self._persistence.persist_all_open_trades(self)
    
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
        """Evaluate an alert — delegated to OpportunityEvaluator module."""
        return await self._opportunity_evaluator.evaluate_opportunity(alert, self)

    def _calculate_position_size(self, entry_price: float, stop_price: float, direction: TradeDirection, atr: float = None, atr_percent: float = None) -> Tuple[int, float]:
        """Position sizing — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.calculate_position_size(entry_price, stop_price, direction, self, atr, atr_percent)

    def calculate_atr_based_stop(self, entry_price: float, direction: TradeDirection, atr: float, setup_type: str = None) -> float:
        """ATR-based stop — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.calculate_atr_based_stop(entry_price, direction, atr, setup_type, self)

    def _score_to_grade(self, score: int) -> str:
        """Score to grade — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.score_to_grade(score)

    def _estimate_duration(self, setup_type: str) -> str:
        """Duration estimate — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.estimate_duration(setup_type)
    
    # ==================== ENHANCED INTELLIGENCE GATHERING ====================
    
    async def _gather_trade_intelligence(self, symbol: str, alert: Dict) -> Dict[str, Any]:
        """Delegates to TradeIntelligence module."""
        self._trade_intel.set_services(
            web_research=self.web_research,
            technical_service=self._realtime_tech,
            quality_service=getattr(self, '_quality_service', None),
        )
        return await self._trade_intel.gather(symbol, alert)

    def _analyze_news_sentiment(self, news_result) -> str:
        """Delegates to TradeIntelligence module."""
        return self._trade_intel._analyze_news_sentiment(news_result)

    def _extract_news_topics(self, news_result) -> List[str]:
        """Delegates to TradeIntelligence module."""
        return self._trade_intel._extract_news_topics(news_result)

    def _analyze_intelligence(self, intelligence: Dict, alert: Dict):
        """Delegates to TradeIntelligence module."""
        self._trade_intel.analyze(intelligence, alert)

    def _calculate_intelligence_adjustment(self, intelligence: Dict) -> int:
        """Delegates to TradeIntelligence module."""
        return self._trade_intel.calculate_adjustment(intelligence)

    def _build_entry_context(
        self, alert: Dict, intelligence: Dict, regime: str,
        regime_score: float, filter_action: str, filter_win_rate: float,
        atr: float, atr_percent: float, confidence_gate_result: Dict = None
    ) -> Dict[str, Any]:
        """Entry context — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.build_entry_context(
            alert, intelligence, regime, regime_score,
            filter_action, filter_win_rate, atr, atr_percent,
            confidence_gate_result=confidence_gate_result
        )

    @staticmethod
    def _classify_time_window(now_et) -> str:
        """Time window classification — delegated to OpportunityEvaluator module."""
        from services.opportunity_evaluator import OpportunityEvaluator
        return OpportunityEvaluator.classify_time_window(now_et)

    def _generate_explanation(self, alert: Dict, shares: int, entry: float, stop: float, targets: List[float], intelligence: Dict = None) -> TradeExplanation:
        """Explanation generation — delegated to OpportunityEvaluator module."""
        return self._opportunity_evaluator.generate_explanation(alert, shares, entry, stop, targets, intelligence, self)
    
    # ==================== TRADE EXECUTION ====================
    
    async def _execute_trade(self, trade: BotTrade):
        """Execute a trade — delegated to TradeExecution module."""
        await self._trade_execution.execute_trade(trade, self)
    
    async def confirm_trade(self, trade_id: str) -> bool:
        """Confirm a pending trade — delegated to TradeExecution module."""
        return await self._trade_execution.confirm_trade(trade_id, self)
    
    async def reject_trade(self, trade_id: str) -> bool:
        """Reject a pending trade — delegated to TradeExecution module."""
        return await self._trade_execution.reject_trade(trade_id, self)
    
    # ==================== POSITION MANAGEMENT ====================
    
    async def _update_open_positions(self):
        """Update open positions — delegated to PositionManager module."""
        await self._position_manager.update_open_positions(self)

    async def _check_eod_close(self):
        """EOD auto-close — delegated to PositionManager module."""
        await self._position_manager.check_eod_close(self)

    async def _update_trailing_stop(self, trade: BotTrade):
        """Delegates to StopManager module."""
        await self._stop_manager.update_trailing_stop(trade)

    def _move_stop_to_breakeven(self, trade: BotTrade):
        """Delegates to StopManager module."""
        self._stop_manager._move_stop_to_breakeven(trade)

    def _activate_trailing_stop(self, trade: BotTrade):
        """Delegates to StopManager module."""
        self._stop_manager._activate_trailing_stop(trade)

    def _update_trail_position(self, trade: BotTrade):
        """Delegates to StopManager module."""
        self._stop_manager._update_trail_position(trade)

    def _record_stop_adjustment(self, trade: BotTrade, old_stop: float, new_stop: float, reason: str):
        """Delegates to StopManager module."""
        self._stop_manager._record_stop_adjustment(trade, old_stop, new_stop, reason)


    async def _check_and_execute_scale_out(self, trade: BotTrade):
        """Scale-out check — delegated to PositionManager module."""
        await self._position_manager.check_and_execute_scale_out(trade, self)
    
    async def _execute_partial_exit(self, trade: BotTrade, shares: int, target_price: float, target_idx: int) -> Dict:
        """Partial exit — delegated to PositionManager module."""
        return await self._position_manager.execute_partial_exit(trade, shares, target_price, target_idx, self)

    
    async def close_trade(self, trade_id: str, reason: str = "manual") -> bool:
        """Close an open trade — delegated to PositionManager module."""
        return await self._position_manager.close_trade(trade_id, self, reason=reason)
    
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
        """Reconcile bot positions with IB — delegated to PositionReconciler module."""
        return await self._position_reconciler.reconcile_positions_with_ib(self)
    
    async def sync_position_from_ib(self, symbol: str, auto_create_trade: bool = False) -> Dict:
        """Sync a single IB position — delegated to PositionReconciler module."""
        return await self._position_reconciler.sync_position_from_ib(symbol, self, auto_create_trade)
    
    async def close_phantom_position(self, trade_id: str, reason: str = "not_in_ib") -> Dict:
        """Close a phantom position — delegated to PositionReconciler module."""
        return await self._position_reconciler.close_phantom_position(trade_id, self, reason)
    
    async def full_position_sync(self) -> Dict:
        """Full IB position sync — delegated to PositionReconciler module."""
        return await self._position_reconciler.full_position_sync(self)
    
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
        """Save trade to database — delegated to BotPersistence module."""
        await self._persistence.save_trade(trade, self)

    async def load_trades_from_db(self):
        """Load trades from database — delegated to BotPersistence module."""
        await self._persistence.load_trades_from_db(self)

    def _dict_to_trade(self, d: Dict) -> Optional[BotTrade]:
        """Convert dict to BotTrade — delegated to BotPersistence module."""
        return self._persistence.dict_to_trade(d)
    
    # ==================== SCANNER AUTO-EXECUTION ====================
    
    async def submit_trade_from_scanner(self, trade_request: Dict):
        """Scanner auto-submit — delegated to ScannerIntegration module."""
        return await self._scanner_integration.submit_trade_from_scanner(trade_request, self)

    async def _log_trade_to_journal(self, trade: BotTrade, action: str = "entry"):
        """Journal auto-logging — delegated to ScannerIntegration module."""
        await self._scanner_integration.log_trade_to_journal(trade, self, action)



# Singleton instance
_trading_bot_service: Optional[TradingBotService] = None


def get_trading_bot_service() -> TradingBotService:
    """Get or create the trading bot service singleton"""
    global _trading_bot_service
    if _trading_bot_service is None:
        _trading_bot_service = TradingBotService()
    return _trading_bot_service
