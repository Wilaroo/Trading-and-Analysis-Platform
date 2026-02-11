"""
Enhanced Background Scanner Service - SMB Trading Strategies
With RVOL Pre-filtering, Tape Reading Signals, Win-Rate Tracking, and Bot Auto-Execution

Features:
- 264 symbols with RVOL pre-filtering (skip dead stocks)
- 30+ SMB strategies with time-of-day and market context rules
- Tape reading confirmation signals (bid/ask spread, momentum, order flow)
- Strategy win-rate tracking per setup type
- Auto-execution wiring to Trading Bot for high-priority alerts
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from collections import defaultdict

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


@dataclass
class StrategyStats:
    """Win-rate tracking per strategy"""
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
    
    def update_win_rate(self):
        """Recalculate win rate"""
        if self.alerts_triggered > 0:
            self.win_rate = self.alerts_won / self.alerts_triggered
        if self.alerts_lost > 0 and self.avg_loss != 0:
            self.profit_factor = (self.alerts_won * abs(self.avg_win)) / (self.alerts_lost * abs(self.avg_loss))
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class LiveAlert:
    """Real-time trading alert with tape confirmation"""
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
    
    # Auto-execution
    auto_execute_eligible: bool = False
    
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    acknowledged: bool = False
    status: str = "active"
    
    # Outcome tracking
    outcome: Optional[str] = None  # "won", "lost", "expired", "cancelled"
    actual_pnl: Optional[float] = None
    
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
        self._scan_interval = 60  # seconds between full scans
        self._symbols_per_batch = 10  # Increased for speed
        self._batch_delay = 1  # Reduced delay
        self._min_scan_interval = 30
        
        # RVOL pre-filter threshold
        self._min_rvol_filter = 0.8  # Skip stocks with RVOL < 0.8
        self._rvol_cache: Dict[str, Tuple[float, datetime]] = {}
        self._rvol_cache_ttl = 300  # 5 minutes
        
        # Average Daily Volume (ADV) filters
        self._min_adv_general = 100_000      # Min ADV for general/swing setups
        self._min_adv_intraday = 500_000     # Min ADV for intraday/scalp setups
        self._adv_cache: Dict[str, int] = {}  # Cache ADV values
        
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
            # Consolidation
            "big_dog", "puppy_dog", "9_ema_scalp", "abc_scalp",
            # Afternoon
            "hod_breakout", "time_of_day_fade",
            # Special
            "breaking_news", "volume_capitulation", "range_break", "breakout"
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
        self._alpaca_service = None
        
        # DB collections
        if db:
            self.alerts_collection = db["live_alerts"]
            self.stats_collection = db["strategy_stats"]
            self.alert_outcomes_collection = db["alert_outcomes"]
            self._load_strategy_stats()
    
    def _init_strategy_stats(self):
        """Initialize strategy stats for all setups"""
        for setup in self._enabled_setups:
            self._strategy_stats[setup] = StrategyStats(setup_type=setup)
    
    def _load_strategy_stats(self):
        """Load strategy stats from database"""
        if self.stats_collection:
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
        if self.stats_collection and setup_type in self._strategy_stats:
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
            # Fallback to static watchlist
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
                    
                    # Quick RVOL check via Alpaca
                    quote = await self.alpaca_service.get_quote(symbol)
                    if quote:
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
        """Analyze tape for confirmation signals"""
        try:
            quote = await self.alpaca_service.get_quote(symbol)
            
            bid_price = quote.get("bid", snapshot.current_price * 0.999)
            ask_price = quote.get("ask", snapshot.current_price * 1.001)
            bid_size = quote.get("bid_size", 100)
            ask_size = quote.get("ask_size", 100)
            
            spread = ask_price - bid_price
            spread_pct = (spread / snapshot.current_price) * 100 if snapshot.current_price > 0 else 0
            
            # Spread signal
            if spread_pct < 0.05:
                spread_signal = TapeSignal.TIGHT_SPREAD
            elif spread_pct > 0.2:
                spread_signal = TapeSignal.WIDE_SPREAD
            else:
                spread_signal = TapeSignal.NEUTRAL
            
            # Order imbalance
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
                confirmation_for_short=tape_score < -0.2
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
    
    def record_alert_outcome(self, alert_id: str, outcome: str, pnl: float = 0.0):
        """Record the outcome of an alert for win-rate tracking"""
        if alert_id not in self._live_alerts:
            return
        
        alert = self._live_alerts[alert_id]
        setup_type = alert.setup_type.split("_")[0] if "_long" in alert.setup_type or "_short" in alert.setup_type else alert.setup_type
        
        if setup_type not in self._strategy_stats:
            self._strategy_stats[setup_type] = StrategyStats(setup_type=setup_type)
        
        stats = self._strategy_stats[setup_type]
        stats.alerts_triggered += 1
        
        if outcome == "won":
            stats.alerts_won += 1
            stats.total_pnl += pnl
            # Update average win
            if stats.alerts_won > 0:
                stats.avg_win = stats.total_pnl / stats.alerts_won if stats.total_pnl > 0 else stats.avg_win
        elif outcome == "lost":
            stats.alerts_lost += 1
            stats.total_pnl += pnl  # pnl is negative for losses
            # Update average loss
            if stats.alerts_lost > 0:
                total_losses = stats.total_pnl - (stats.avg_win * stats.alerts_won) if stats.alerts_won > 0 else stats.total_pnl
                stats.avg_loss = total_losses / stats.alerts_lost
        
        stats.update_win_rate()
        self._save_strategy_stats(setup_type)
        
        # Update alert
        alert.outcome = outcome
        alert.actual_pnl = pnl
        
        # Save to outcomes collection
        if self.alert_outcomes_collection:
            try:
                self.alert_outcomes_collection.insert_one({
                    "alert_id": alert_id,
                    "symbol": alert.symbol,
                    "setup_type": setup_type,
                    "direction": alert.direction,
                    "outcome": outcome,
                    "pnl": pnl,
                    "entry_price": alert.current_price,
                    "stop_loss": alert.stop_loss,
                    "target": alert.target,
                    "created_at": alert.created_at,
                    "closed_at": datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                logger.warning(f"Could not save alert outcome: {e}")
        
        logger.info(f"📊 Recorded {outcome} for {setup_type}: Win rate now {stats.win_rate:.1%}")
    
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
        if self._alpaca_service is None:
            from services.alpaca_service import get_alpaca_service
            self._alpaca_service = get_alpaca_service()
        return self._alpaca_service
    
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
                now = datetime.now(timezone.utc)
                if self._last_scan_time:
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
                
                logger.info(f"📊 Scan #{self._scan_count} in {scan_duration:.1f}s | "
                           f"Regime: {self._market_regime.value} | Window: {current_window.value} | "
                           f"Scanned: {self._symbols_scanned_last} | Skipped: {self._symbols_skipped_rvol} | "
                           f"Alerts: {len(self._live_alerts)}")
                
                # Clean up expired alerts
                self._cleanup_expired_alerts()
                
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
        """Run optimized scan with RVOL pre-filtering and parallel processing"""
        # Pre-filter watchlist based on RVOL (skip dead stocks)
        active_symbols = await self._get_active_symbols()
        self._symbols_scanned_last = len(active_symbols)
        
        logger.debug(f"Scanning {len(active_symbols)} active symbols (filtered from {len(self._watchlist)})")
        
        # Scan in larger batches with concurrent processing
        for i in range(0, len(active_symbols), self._symbols_per_batch):
            batch = active_symbols[i:i + self._symbols_per_batch]
            
            # Process batch concurrently
            tasks = [self._scan_symbol_all_setups(symbol) for symbol in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Small delay between batches
            if i + self._symbols_per_batch < len(active_symbols):
                await asyncio.sleep(self._batch_delay)
    
    async def _scan_symbol_all_setups(self, symbol: str):
        """Scan a single symbol for ALL enabled setups with tape reading"""
        try:
            # Get technical snapshot
            snapshot = await self.technical_service.get_technical_snapshot(symbol)
            if not snapshot:
                return
            
            # Skip low volume stocks (RVOL filter)
            if snapshot.rvol < self._min_rvol_filter:
                self._symbols_skipped_rvol += 1
                return
            
            # Update caches
            self._rvol_cache[symbol] = (snapshot.rvol, datetime.now(timezone.utc))
            self._adv_cache[symbol] = int(snapshot.avg_volume)
            
            # Get tape reading for this symbol
            tape = await self._get_tape_reading(symbol, snapshot)
            
            alerts = []
            current_window = self._get_current_time_window()
            
            # Check each enabled setup
            for setup_type in self._enabled_setups:
                # Check time and regime validity
                if not self._is_setup_valid_now(setup_type):
                    continue
                
                # ADV filter - intraday/scalp setups require higher volume
                if setup_type in self._intraday_setups:
                    if snapshot.avg_volume < self._min_adv_intraday:
                        continue  # Skip this setup for this symbol (low volume)
                else:
                    if snapshot.avg_volume < self._min_adv_general:
                        continue  # Skip this setup for this symbol (low volume)
                
                # Call appropriate scanner method
                alert = await self._check_setup(setup_type, symbol, snapshot, tape)
                if alert:
                    # Add strategy stats to alert
                    base_setup = setup_type.split("_long")[0].split("_short")[0]
                    if base_setup in self._strategy_stats:
                        stats = self._strategy_stats[base_setup]
                        alert.strategy_win_rate = stats.win_rate
                        alert.strategy_profit_factor = stats.profit_factor
                    
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
            
            # Process all alerts for this symbol
            for alert in alerts:
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
            
            # Special
            "volume_capitulation": self._check_volume_capitulation,
            "range_break": self._check_range_break,
            "breakout": self._check_breakout,
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
            
            return LiveAlert(
                id=f"rb_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="rubber_band_long",
                strategy_name="Rubber Band Long (INT-25)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.ema_9,
                stop_loss=round(snapshot.low_of_day - 0.02, 2),
                target=round(snapshot.ema_9, 2),
                risk_reward=2.0,
                trigger_probability=0.65,
                win_probability=0.62,
                minutes_to_trigger=10,
                headline=f"🎯 {symbol} Rubber Band LONG - {extension:.1f}% extended {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price {extension:.1f}% below 9-EMA (trigger: >2.5%)",
                    f"RSI oversold at {snapshot.rsi_14:.0f} (trigger: <38)",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value} (score: {tape.tape_score:.2f})",
                    f"Entry: Double bar break above prior highs",
                    f"Target: Snap back to 9-EMA ${snapshot.ema_9:.2f}"
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
            
            return LiveAlert(
                id=f"rb_short_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="rubber_band_short",
                strategy_name="Rubber Band Short (INT-25)",
                direction="short",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.ema_9,
                stop_loss=round(snapshot.high_of_day + 0.02, 2),
                target=round(snapshot.ema_9, 2),
                risk_reward=2.0,
                trigger_probability=0.65,
                win_probability=0.58,
                minutes_to_trigger=10,
                headline=f"🎯 {symbol} Rubber Band SHORT - {extension:.1f}% extended {'✓ TAPE' if tape.confirmation_for_short else ''}",
                reasoning=[
                    f"Price {extension:.1f}% above 9-EMA (trigger: >3.0%)",
                    f"RSI overbought at {snapshot.rsi_14:.0f} (trigger: >65)",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Tape: {tape.overall_signal.value} (score: {tape.tape_score:.2f})",
                    f"Entry: Double bar break below prior lows",
                    f"Target: Snap back to 9-EMA ${snapshot.ema_9:.2f}"
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
        """Breakout - Price near resistance with volume"""
        dist_to_resistance = ((snapshot.resistance - snapshot.current_price) / snapshot.current_price) * 100
        
        if 0 < dist_to_resistance < 1.0 and snapshot.rvol >= 2.0:
            if dist_to_resistance < 0.3 and tape.confirmation_for_long:
                priority = AlertPriority.CRITICAL
                minutes = 2
            elif dist_to_resistance < 0.6:
                priority = AlertPriority.HIGH
                minutes = 5
            else:
                priority = AlertPriority.MEDIUM
                minutes = 10
            
            return LiveAlert(
                id=f"breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="breakout",
                strategy_name="Intraday Breakout (INT-02)",
                direction="long",
                priority=priority,
                current_price=snapshot.current_price,
                trigger_price=snapshot.resistance,
                stop_loss=round(snapshot.resistance - snapshot.atr, 2),
                target=round(snapshot.resistance + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.70 if priority == AlertPriority.CRITICAL else 0.55,
                win_probability=0.55,
                minutes_to_trigger=minutes,
                headline=f"🚀 {symbol} BREAKOUT - {dist_to_resistance:.1f}% to ${snapshot.resistance:.2f} {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price {dist_to_resistance:.1f}% below resistance",
                    f"Strong volume: {snapshot.rvol:.1f}x RVOL",
                    f"Tape: {tape.overall_signal.value} (score: {tape.tape_score:.2f})",
                    f"Entry: Break above ${snapshot.resistance:.2f} with volume"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
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
            
            if dist_from_hod < 0.5 and snapshot.above_vwap:
                priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
                
                return LiveAlert(
                    id=f"orb_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="orb_long",
                    strategy_name="Opening Range Breakout (INT-03)",
                    direction="long",
                    priority=priority,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.high_of_day - snapshot.low_of_day) * 2, 2),
                    risk_reward=2.0,
                    trigger_probability=0.60,
                    win_probability=0.55,
                    minutes_to_trigger=10,
                    headline=f"📈 {symbol} ORB LONG {'✓ TAPE' if tape.confirmation_for_long else ''}",
                    reasoning=[
                        f"Testing ORH ${snapshot.high_of_day:.2f}",
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"RVOL: {snapshot.rvol:.1f}x",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=current_window.value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
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
        """HOD Breakout - Afternoon break of high of day"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.AFTERNOON, TimeWindow.CLOSE]:
            return None
        
        dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
        
        if (dist_from_hod < 0.5 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.5):
            
            priority = AlertPriority.HIGH if tape.confirmation_for_long else AlertPriority.MEDIUM
            
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
                target=round(snapshot.high_of_day + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"☁️ {symbol} HOD Breakout - Afternoon {'✓ TAPE' if tape.confirmation_for_long else ''}",
                reasoning=[
                    f"Price {dist_from_hod:.1f}% from HOD",
                    f"Afternoon session",
                    f"Tape: {tape.overall_signal.value}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
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
            
            if dist_from_hod < 0.5:
                return LiveAlert(
                    id=f"range_break_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="range_break_long",
                    strategy_name="Range Break (INT-21)",
                    direction="long",
                    priority=AlertPriority.MEDIUM,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.high_of_day - snapshot.low_of_day), 2),
                    risk_reward=1.5,
                    trigger_probability=0.50,
                    win_probability=0.50,
                    minutes_to_trigger=20,
                    headline=f"📊 {symbol} Range Break - Near resistance",
                    reasoning=[
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"Tape: {tape.overall_signal.value}"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
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
    
    # ==================== ALERT MANAGEMENT ====================
    
    async def _process_new_alert(self, alert: LiveAlert):
        """Process a new alert"""
        # Check for duplicate
        for existing in self._live_alerts.values():
            if (existing.symbol == alert.symbol and 
                existing.setup_type == alert.setup_type and
                existing.status == "active"):
                return
        
        # Update strategy stats
        base_setup = alert.setup_type.split("_long")[0].split("_short")[0]
        if base_setup in self._strategy_stats:
            self._strategy_stats[base_setup].total_alerts += 1
        
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
        
        # Persist to database
        if self.db:
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
        if self.alerts_collection:
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
            "watchlist_size": len(self._watchlist),
            "symbols_scanned_last": self._symbols_scanned_last,
            "symbols_skipped_rvol": self._symbols_skipped_rvol,
            "scan_interval": self._scan_interval,
            "enabled_setups": list(self._enabled_setups),
            "market_regime": self._market_regime.value,
            "time_window": self._get_current_time_window().value,
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None,
            "auto_execute_enabled": self._auto_execute_enabled,
            "min_rvol_filter": self._min_rvol_filter,
            "wave_scanner": wave_info
        }


# Global instance
_enhanced_scanner: Optional[EnhancedBackgroundScanner] = None


def get_enhanced_scanner() -> EnhancedBackgroundScanner:
    global _enhanced_scanner
    if _enhanced_scanner is None:
        _enhanced_scanner = EnhancedBackgroundScanner()
    return _enhanced_scanner
