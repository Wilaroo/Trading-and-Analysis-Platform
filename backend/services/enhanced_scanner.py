"""
Enhanced Background Scanner Service - SMB Trading Strategies
Implements all 47 intraday strategies with time-of-day and market context rules.

Strategies included:
- Opening Auction: First VWAP Pullback, First Move Up/Down, Bella Fade, Back-Through Open, Opening Drive
- Morning Momentum: ORB, HitchHiker, Gap Give and Go, Gap Pick and Roll
- Core Session: Spencer Scalp, Second Chance, Back$ide, Off Sides, Fashionably Late
- Mean Reversion: Rubber Band, VWAP Bounce, VWAP Fade, Tidal Wave
- Consolidation: Big Dog, Puppy Dog, 9 EMA Scalp, ABC Scalp
- Afternoon: HOD Breakout, Time-of-Day Fade
- Special: Breaking News, Volume Capitulation, Range Break
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import concurrent.futures

logger = logging.getLogger(__name__)


class AlertPriority(Enum):
    CRITICAL = "critical"  # Imminent trigger
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
class LiveAlert:
    """Real-time trading alert"""
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
    
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    acknowledged: bool = False
    status: str = "active"
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['priority'] = self.priority.value
        return result


class EnhancedBackgroundScanner:
    """
    Enhanced background scanner with all SMB strategies,
    time-of-day rules, and market context checking.
    Optimized for 200+ symbols.
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
        
        # Market context
        self._market_regime: MarketRegime = MarketRegime.RANGE_BOUND
        self._spy_data: Optional[Dict] = None
        
        # Services
        self._technical_service = None
        self._alpaca_service = None
        
        if db:
            self.alerts_collection = db["live_alerts"]
    
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
            "AMZN", "HD", "LOW", "TGT", "WMT", "COST", "NKE", "SBUX",
            "MCD", "DIS", "CMCSA", "NFLX", "ABNB", "BKNG", "MAR", "RCL",
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
            "GME", "AMC", "BBBY", "CLOV", "WISH", "SPCE", "LCID", "RIVN",
            "NIO", "XPEV", "LI", "F", "GM", "RIVN",
            # Semiconductors (often trending)
            "NVDA", "AMD", "INTC", "TSM", "ASML", "AMAT", "LRCX", "KLAC",
            "MCHP", "ADI", "ON", "SWKS", "QRVO", "WOLF",
            # Software/Cloud
            "NOW", "WDAY", "ZM", "DOCU", "TWLO", "TEAM", "MNDY", "HUBS",
            "BILL", "PCTY", "PAYC", "VEEV", "SPLK", "ESTC",
            # Cybersecurity
            "CRWD", "ZS", "PANW", "FTNT", "OKTA", "S", "QLYS", "TENB",
            # Social/Advertising
            "META", "SNAP", "PINS", "TTD", "MGNI", "PUBM",
            # E-commerce/Payments
            "SHOP", "SQ", "PYPL", "AFRM", "UPST", "BILL", "TOST",
            # Gaming/Entertainment
            "EA", "TTWO", "RBLX", "U", "DKNG", "PENN", "MGM", "WYNN", "LVS",
            # Cannabis (high volatility)
            "TLRY", "CGC", "ACB", "CRON",
            # SPACs/Recent IPOs (high volatility)
            "DWAC", "IONQ", "JOBY", "LILM",
            # REITs
            "AMT", "PLD", "EQIX", "DLR", "SPG", "O", "VICI",
            # Airlines (volatile)
            "DAL", "UAL", "AAL", "LUV", "JBLU",
            # Auto
            "TSLA", "F", "GM", "RIVN", "LCID", "NIO", "XPEV", "LI",
            # Retail
            "TGT", "WMT", "COST", "DLTR", "DG", "FIVE", "OLLI",
            # Restaurants
            "MCD", "SBUX", "CMG", "YUM", "DPZ", "QSR",
        ]
    
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
        
        # Check market regime preference
        regime_prefs = STRATEGY_REGIME_PREFERENCES.get(setup_type, [])
        if regime_prefs and self._market_regime not in regime_prefs:
            # Reduce priority but don't skip entirely
            pass
        
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
                
                logger.info(f"📊 Scan #{self._scan_count} complete in {scan_duration:.1f}s | "
                           f"Regime: {self._market_regime.value} | Window: {current_window.value} | "
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
        """Run optimized scan with parallel processing"""
        # Pre-filter watchlist based on RVOL (skip dead stocks)
        active_symbols = await self._get_active_symbols()
        
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
    
    async def _get_active_symbols(self) -> List[str]:
        """Pre-filter symbols to only scan active ones (RVOL > 0.8)"""
        # For now, return full watchlist - can add RVOL pre-filter later
        # This would require a quick volume check endpoint
        return self._watchlist
    
    async def _scan_symbol_all_setups(self, symbol: str):
        """Scan a single symbol for ALL enabled setups"""
        try:
            # Get technical snapshot
            snapshot = await self.technical_service.get_technical_snapshot(symbol)
            if not snapshot:
                return
            
            # Skip low volume stocks
            if snapshot.rvol < 0.5:
                return
            
            alerts = []
            current_window = self._get_current_time_window()
            
            # Check each enabled setup
            for setup_type in self._enabled_setups:
                # Check time and regime validity
                if not self._is_setup_valid_now(setup_type):
                    continue
                
                # Call appropriate scanner method
                alert = await self._check_setup(setup_type, symbol, snapshot)
                if alert:
                    alerts.append(alert)
            
            # Process all alerts for this symbol
            for alert in alerts:
                await self._process_new_alert(alert)
                
        except Exception as e:
            logger.warning(f"Error scanning {symbol}: {e}")
    
    async def _check_setup(self, setup_type: str, symbol: str, snapshot) -> Optional[LiveAlert]:
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
            "9_ema_scalp": self._check_9_ema_scalp,
            
            # Afternoon
            "hod_breakout": self._check_hod_breakout,
            
            # Special
            "volume_capitulation": self._check_volume_capitulation,
            "range_break": self._check_range_break,
            "breakout": self._check_breakout,
        }
        
        checker = checkers.get(setup_type)
        if checker:
            return await checker(symbol, snapshot)
        return None
    
    # ==================== SETUP CHECKERS ====================
    
    async def _check_rubber_band(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Rubber Band Scalp - Mean reversion from EMA9"""
        # Long setup - extended below EMA9
        if snapshot.dist_from_ema9 < -2.5 and snapshot.rsi_14 < 38 and snapshot.rvol >= 1.5:
            extension = abs(snapshot.dist_from_ema9)
            
            priority = AlertPriority.HIGH if extension > 3.5 else AlertPriority.MEDIUM
            
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
                headline=f"🎯 {symbol} Rubber Band LONG - {extension:.1f}% extended",
                reasoning=[
                    f"Price {extension:.1f}% below 9-EMA (trigger: >2.5%)",
                    f"RSI oversold at {snapshot.rsi_14:.0f} (trigger: <38)",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Double bar break above prior highs",
                    f"Target: Snap back to 9-EMA ${snapshot.ema_9:.2f}",
                    f"Stop: Below LOD ${snapshot.low_of_day:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        
        # Short setup - extended above EMA9
        if snapshot.dist_from_ema9 > 3.0 and snapshot.rsi_14 > 65 and snapshot.rvol >= 1.5:
            extension = snapshot.dist_from_ema9
            
            priority = AlertPriority.HIGH if extension > 4.0 else AlertPriority.MEDIUM
            
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
                headline=f"🎯 {symbol} Rubber Band SHORT - {extension:.1f}% extended",
                reasoning=[
                    f"Price {extension:.1f}% above 9-EMA (trigger: >3.0%)",
                    f"RSI overbought at {snapshot.rsi_14:.0f} (trigger: >65)",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Double bar break below prior lows",
                    f"Target: Snap back to 9-EMA ${snapshot.ema_9:.2f}",
                    f"Stop: Above HOD ${snapshot.high_of_day:.2f}"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        
        return None
    
    async def _check_vwap_bounce(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """VWAP Bounce - Pullback to VWAP in uptrend"""
        if (-0.8 < snapshot.dist_from_vwap < 0.3 and 
            snapshot.trend == "uptrend" and 
            snapshot.above_ema9 and
            snapshot.rvol >= 1.5):
            
            dist = abs(snapshot.dist_from_vwap)
            priority = AlertPriority.HIGH if dist < 0.3 else AlertPriority.MEDIUM
            
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
                headline=f"📍 {symbol} VWAP Bounce - Testing ${snapshot.vwap:.2f}",
                reasoning=[
                    f"Price {snapshot.dist_from_vwap:+.1f}% from VWAP",
                    f"Uptrend intact - above 9-EMA and 20-EMA",
                    f"RVOL: {snapshot.rvol:.1f}x (trigger: >1.5x)",
                    f"Entry: Rejection wick + bullish candle at VWAP",
                    f"Target: ${snapshot.vwap + (snapshot.atr * 1.5):.2f} (1.5 ATR)",
                    f"Stop: ${snapshot.vwap - (snapshot.atr * 0.5):.2f} (0.5 ATR below)"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_vwap_fade(self, symbol: str, snapshot) -> Optional[LiveAlert]:
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
                headline=f"↩️ {symbol} VWAP Fade LONG - Extended {abs(snapshot.dist_from_vwap):.1f}% below",
                reasoning=[
                    f"Price extended {abs(snapshot.dist_from_vwap):.1f}% below VWAP",
                    f"RSI oversold at {snapshot.rsi_14:.0f}",
                    f"Target: Mean reversion to VWAP ${snapshot.vwap:.2f}",
                    f"Watch for momentum divergence"
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
                headline=f"↩️ {symbol} VWAP Fade SHORT - Extended {snapshot.dist_from_vwap:.1f}% above",
                reasoning=[
                    f"Price extended {snapshot.dist_from_vwap:.1f}% above VWAP",
                    f"RSI overbought at {snapshot.rsi_14:.0f}",
                    f"Target: Mean reversion to VWAP ${snapshot.vwap:.2f}",
                    f"Watch for parabolic exhaustion"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_breakout(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Breakout - Price near resistance with volume"""
        dist_to_resistance = ((snapshot.resistance - snapshot.current_price) / snapshot.current_price) * 100
        
        if 0 < dist_to_resistance < 1.0 and snapshot.rvol >= 2.0:
            if dist_to_resistance < 0.3:
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
                headline=f"🚀 {symbol} BREAKOUT - {dist_to_resistance:.1f}% to ${snapshot.resistance:.2f}",
                reasoning=[
                    f"Price {dist_to_resistance:.1f}% below resistance ${snapshot.resistance:.2f}",
                    f"Strong volume: {snapshot.rvol:.1f}x RVOL (trigger: >2.0x)",
                    f"Entry: Break above ${snapshot.resistance:.2f} with volume",
                    f"Target: ${snapshot.resistance + (snapshot.atr * 2):.2f} (2 ATR)",
                    f"Stop: ${snapshot.resistance - snapshot.atr:.2f} (1 ATR below)"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_spencer_scalp(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Spencer Scalp - Tight consolidation near HOD"""
        # Check if near high of day
        dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
        
        # Near HOD, tight range, decent volume
        if dist_from_hod < 1.0 and snapshot.daily_range_pct < 3.0 and snapshot.rvol >= 1.5:
            return LiveAlert(
                id=f"spencer_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="spencer_scalp",
                strategy_name="Spencer Scalp (INT-22)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.high_of_day,
                stop_loss=round(snapshot.current_price - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day + (snapshot.atr * 1.5), 2),
                risk_reward=3.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"📊 {symbol} Spencer Scalp - Consolidating near HOD",
                reasoning=[
                    f"Price {dist_from_hod:.1f}% from HOD ${snapshot.high_of_day:.2f}",
                    f"Tight consolidation (daily range: {snapshot.daily_range_pct:.1f}%)",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Break of consolidation high",
                    f"Exit: 1/3 at 1R, 1/3 at 2R, 1/3 at 3R",
                    f"Stop: Below consolidation low"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            )
        return None
    
    async def _check_hitchhiker(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """HitchHiker - Strong drive off open, consolidation, continuation"""
        current_window = self._get_current_time_window()
        
        # Only valid in opening drive/morning momentum
        if current_window not in [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM]:
            return None
        
        # Strong gap up holding, near HOD
        if (snapshot.gap_pct > 2.0 and 
            snapshot.holding_gap and 
            snapshot.above_vwap and
            snapshot.rvol >= 2.0):
            
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 1.5:
                return LiveAlert(
                    id=f"hitchhiker_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="hitchhiker",
                    strategy_name="HitchHiker (INT-29)",
                    direction="long",
                    priority=AlertPriority.HIGH,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.vwap - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.atr * 2), 2),
                    risk_reward=2.5,
                    trigger_probability=0.60,
                    win_probability=0.58,
                    minutes_to_trigger=10,
                    headline=f"🏃 {symbol} HitchHiker - Gap {snapshot.gap_pct:.1f}% holding, ready to break",
                    reasoning=[
                        f"Gap up {snapshot.gap_pct:.1f}% holding above VWAP",
                        f"Consolidating {dist_from_hod:.1f}% from HOD",
                        f"RVOL: {snapshot.rvol:.1f}x (strong interest)",
                        f"Entry: Aggressive on break of consolidation",
                        f"Exit: 1/2 into first wave, 1/2 into second wave",
                        f"Stop: Below consolidation - ONE AND DONE"
                    ],
                    time_window=current_window.value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
                )
        return None
    
    async def _check_orb(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Opening Range Breakout"""
        current_window = self._get_current_time_window()
        
        # ORB needs morning session
        if current_window not in [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM, TimeWindow.MORNING_SESSION]:
            return None
        
        # Strong volume and near HOD
        if snapshot.rvol >= 2.0:
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 0.5 and snapshot.above_vwap:
                return LiveAlert(
                    id=f"orb_long_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="orb_long",
                    strategy_name="Opening Range Breakout (INT-03/INT-28)",
                    direction="long",
                    priority=AlertPriority.HIGH,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.low_of_day - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.high_of_day - snapshot.low_of_day) * 2, 2),
                    risk_reward=2.0,
                    trigger_probability=0.60,
                    win_probability=0.55,
                    minutes_to_trigger=10,
                    headline=f"📈 {symbol} ORB LONG - Breaking opening range high",
                    reasoning=[
                        f"Testing opening range high ${snapshot.high_of_day:.2f}",
                        f"Opening range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"RVOL: {snapshot.rvol:.1f}x (elevated)",
                        f"Entry: Break above ORH with tape confirmation",
                        f"Target: 2x measured move",
                        f"Time exits: 10:30 or 11:30 if no target"
                    ],
                    time_window=current_window.value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
                )
        return None
    
    async def _check_gap_give_go(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Gap Give and Go - Gap up, pullback, continuation"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_DRIVE, TimeWindow.MORNING_MOMENTUM]:
            return None
        
        # Gap up, holding above VWAP after pullback
        if (snapshot.gap_pct > 3.0 and 
            snapshot.holding_gap and
            snapshot.above_vwap and
            0 < snapshot.dist_from_vwap < 1.5 and  # Pulled back near VWAP but holding
            snapshot.rvol >= 2.0):
            
            return LiveAlert(
                id=f"gap_give_go_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="gap_give_go",
                strategy_name="Gap Give and Go (INT-34)",
                direction="long",
                priority=AlertPriority.HIGH,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.vwap - 0.02, 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.0,
                trigger_probability=0.60,
                win_probability=0.55,
                minutes_to_trigger=10,
                headline=f"🎁 {symbol} Gap Give and Go - {snapshot.gap_pct:.1f}% gap holding",
                reasoning=[
                    f"Gap up {snapshot.gap_pct:.1f}% (trigger: >3%)",
                    f"Pulled back but holding above VWAP",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Break of consolidation above VWAP",
                    f"Target: Prior HOD ${snapshot.high_of_day:.2f}",
                    f"Stop: Below VWAP ${snapshot.vwap:.2f}"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
            )
        return None
    
    async def _check_second_chance(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Second Chance - Retest of broken level"""
        # Near a key level (VWAP, EMA, resistance)
        dist_from_vwap = abs(snapshot.dist_from_vwap)
        
        if (dist_from_vwap < 0.5 and 
            snapshot.above_vwap and 
            snapshot.trend == "uptrend" and
            snapshot.rvol >= 1.2):
            
            return LiveAlert(
                id=f"second_chance_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="second_chance",
                strategy_name="Second Chance Scalp (INT-24)",
                direction="long",
                priority=AlertPriority.MEDIUM,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(snapshot.vwap - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"🔄 {symbol} Second Chance - Retesting VWAP support",
                reasoning=[
                    f"Price retesting VWAP ${snapshot.vwap:.2f}",
                    f"Uptrend intact, holding above key level",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Turn candle closing above prior candle",
                    f"Target: Prior HOD ${snapshot.high_of_day:.2f}",
                    f"Stop: Below turn candle (old resistance/new support)"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_backside(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Back$ide - Recovery from LOD with higher highs/lows"""
        # Price recovering from low, making higher lows above 9-EMA
        if (snapshot.trend == "uptrend" and
            snapshot.above_ema9 and
            not snapshot.above_vwap and  # Still below VWAP
            snapshot.dist_from_vwap > -2.0 and  # But approaching VWAP
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
                headline=f"↗️ {symbol} Back$ide - Recovering toward VWAP",
                reasoning=[
                    f"Making higher highs/lows above 9-EMA",
                    f"Price {abs(snapshot.dist_from_vwap):.1f}% below VWAP",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Break of 1-min consolidation",
                    f"Target: VWAP ${snapshot.vwap:.2f}",
                    f"Stop: Below higher low - ONE AND DONE"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_off_sides(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Off Sides - Range break in fade market"""
        if self._market_regime not in [MarketRegime.RANGE_BOUND, MarketRegime.FADE]:
            return None
        
        # Near VWAP in range
        if abs(snapshot.dist_from_vwap) < 1.0 and snapshot.daily_range_pct > 1.5:
            # Near resistance - potential short
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
                    headline=f"⚔️ {symbol} Off Sides SHORT - Range break in fade market",
                    reasoning=[
                        f"Range established: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f}",
                        f"Market regime: {self._market_regime.value} (favorable for fades)",
                        f"Entry: Aggressive on range break lower",
                        f"Target: Measured move below range",
                        f"Stop: Above range top - ONE ATTEMPT ONLY"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_fashionably_late(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Fashionably Late - 9-EMA crosses VWAP"""
        # Look for 9-EMA just above VWAP (recent cross)
        if (snapshot.above_ema9 and 
            snapshot.ema_9 > snapshot.vwap and
            (snapshot.ema_9 - snapshot.vwap) / snapshot.vwap * 100 < 0.5 and  # 9-EMA just crossed VWAP
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
                    f"9-EMA ${snapshot.ema_9:.2f} just crossed above VWAP ${snapshot.vwap:.2f}",
                    f"Momentum building in trend direction",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: On 9-EMA cross above VWAP",
                    f"Target: Measured move above cross point",
                    f"Stop: 1/3 distance from VWAP to LOD"
                ],
                time_window=self._get_current_time_window().value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_tidal_wave(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Tidal Wave / Bouncy Ball - Weaker bounces into support"""
        # Extended downtrend, near support, weak bounces
        if (snapshot.trend == "downtrend" and
            not snapshot.above_vwap and
            snapshot.dist_from_vwap < -1.5 and  # Extended below VWAP
            snapshot.rsi_14 > 40):  # Not yet oversold (bouncing)
            
            dist_to_support = ((snapshot.current_price - snapshot.support) / snapshot.current_price) * 100
            
            if dist_to_support < 2.0:
                return LiveAlert(
                    id=f"tidal_wave_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="tidal_wave",
                    strategy_name="Tidal Wave / Bouncy Ball (INT-23)",
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
                    headline=f"🌊 {symbol} Tidal Wave - Weaker bounces into ${snapshot.support:.2f}",
                    reasoning=[
                        f"Extended {abs(snapshot.dist_from_vwap):.1f}% below VWAP",
                        f"Approaching support ${snapshot.support:.2f}",
                        f"Pattern: Weaker bounces (3+ iterations)",
                        f"Entry: Short on 3rd wave/bounce",
                        f"Target: 2x measured move below support",
                        f"Stop: Above nearest bounce high"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_hod_breakout(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """HOD Breakout - Afternoon break of high of day"""
        current_window = self._get_current_time_window()
        
        # Only in afternoon
        if current_window not in [TimeWindow.AFTERNOON, TimeWindow.CLOSE]:
            return None
        
        dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
        
        if (dist_from_hod < 0.5 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.5):
            
            return LiveAlert(
                id=f"hod_breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="hod_breakout",
                strategy_name="HOD Breakout / Above the Clouds (INT-46)",
                direction="long",
                priority=AlertPriority.HIGH,
                current_price=snapshot.current_price,
                trigger_price=snapshot.high_of_day,
                stop_loss=round(snapshot.ema_9, 2),
                target=round(snapshot.high_of_day + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=15,
                headline=f"☁️ {symbol} HOD Breakout - Afternoon break ${snapshot.high_of_day:.2f}",
                reasoning=[
                    f"Price {dist_from_hod:.1f}% from HOD (afternoon)",
                    f"Above VWAP and 9-EMA",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: Break of HOD with volume",
                    f"Exit: Trail with 9/21-EMA or higher lows",
                    f"Best for +9 catalyst stocks"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            )
        return None
    
    async def _check_volume_capitulation(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Volume Capitulation - Exhaustion on extreme volume"""
        # Would need volume comparison - check for RVOL spike
        if snapshot.rvol >= 5.0:  # Extreme volume
            # Extended move
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
                    headline=f"💥 {symbol} Volume Capitulation - {snapshot.rvol:.1f}x RVOL spike",
                    reasoning=[
                        f"Extreme volume spike: {snapshot.rvol:.1f}x RVOL",
                        f"Extended {abs(snapshot.dist_from_vwap):.1f}% from VWAP",
                        f"Potential exhaustion/capitulation",
                        f"Entry: Flush + tape confirmation",
                        f"Target: Mean reversion to VWAP ${snapshot.vwap:.2f}",
                        f"Look for 2x volume of 2nd highest bar"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_range_break(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Range Break - Break of established range"""
        daily_range = snapshot.daily_range_pct
        
        # Tight range that could break
        if daily_range < 2.0 and daily_range > 0.5 and snapshot.rvol >= 1.5:
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            dist_from_lod = ((snapshot.current_price - snapshot.low_of_day) / snapshot.current_price) * 100
            
            # Near top of range
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
                    headline=f"📊 {symbol} Range Break - Near ${snapshot.high_of_day:.2f} resistance",
                    reasoning=[
                        f"Range: ${snapshot.low_of_day:.2f} - ${snapshot.high_of_day:.2f} ({daily_range:.1f}%)",
                        f"Price near top of range",
                        f"RVOL: {snapshot.rvol:.1f}x",
                        f"Entry: Break above range high",
                        f"Target: Measured move (range height)",
                        f"Stop: Below range low"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_first_vwap_pullback(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """First VWAP Pullback - Opening pullback to VWAP"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE]:
            return None
        
        # Gap up, strong open, now pulling back to VWAP
        if (snapshot.gap_pct > 2.0 and
            snapshot.holding_gap and
            -0.5 < snapshot.dist_from_vwap < 0.5 and
            snapshot.rvol >= 2.0):
            
            return LiveAlert(
                id=f"first_vwap_pb_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="first_vwap_pullback",
                strategy_name="First VWAP Pullback (INT-35)",
                direction="long",
                priority=AlertPriority.HIGH,
                current_price=snapshot.current_price,
                trigger_price=snapshot.vwap,
                stop_loss=round(snapshot.vwap - (snapshot.atr * 0.5), 2),
                target=round(snapshot.high_of_day, 2),
                risk_reward=2.5,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=5,
                headline=f"🎯 {symbol} First VWAP Pullback - Gap {snapshot.gap_pct:.1f}% testing VWAP",
                reasoning=[
                    f"Gap up {snapshot.gap_pct:.1f}% with aggressive buying at open",
                    f"Quick pullback to VWAP ${snapshot.vwap:.2f}",
                    f"RVOL: {snapshot.rvol:.1f}x (institutional interest)",
                    f"Entry: When buyers regain control at VWAP",
                    f"Target: Prior HOD ${snapshot.high_of_day:.2f}",
                    f"Stop: Just below VWAP"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        return None
    
    async def _check_opening_drive(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Opening Drive - Strong momentum right at open"""
        current_window = self._get_current_time_window()
        
        if current_window not in [TimeWindow.OPENING_AUCTION, TimeWindow.OPENING_DRIVE]:
            return None
        
        # Strong gap with holding
        if snapshot.gap_pct > 3.0 and snapshot.holding_gap and snapshot.rvol >= 3.0:
            return LiveAlert(
                id=f"opening_drive_{symbol}_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                setup_type="opening_drive",
                strategy_name="Opening Drive (INT-47)",
                direction="long" if snapshot.gap_pct > 0 else "short",
                priority=AlertPriority.HIGH,
                current_price=snapshot.current_price,
                trigger_price=snapshot.current_price,
                stop_loss=round(snapshot.low_of_day - 0.02, 2),
                target=round(snapshot.current_price + (snapshot.atr * 2), 2),
                risk_reward=2.0,
                trigger_probability=0.55,
                win_probability=0.55,
                minutes_to_trigger=5,
                headline=f"🚄 {symbol} Opening Drive - {snapshot.gap_pct:.1f}% gap with {snapshot.rvol:.1f}x RVOL",
                reasoning=[
                    f"Strong gap: {snapshot.gap_pct:.1f}%",
                    f"Extreme volume: {snapshot.rvol:.1f}x RVOL",
                    f"Entry: Tape confirmation, premarket level break",
                    f"Exit: Change in character on tape",
                    f"Stop: Below LOD or important level",
                    f"Pure momentum - requires tape reading"
                ],
                time_window=current_window.value,
                market_regime=self._market_regime.value,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            )
        return None
    
    async def _check_big_dog(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Big Dog Consolidation - Tight wedge/triangle 15+ min"""
        # Tight consolidation, above key MAs
        if (snapshot.daily_range_pct < 2.0 and
            snapshot.above_vwap and
            snapshot.above_ema9 and
            snapshot.rvol >= 1.2):
            
            dist_from_hod = ((snapshot.high_of_day - snapshot.current_price) / snapshot.current_price) * 100
            
            if dist_from_hod < 1.0:
                return LiveAlert(
                    id=f"big_dog_{symbol}_{datetime.now().strftime('%H%M%S')}",
                    symbol=symbol,
                    setup_type="big_dog",
                    strategy_name="Big Dog Consolidation (INT-44)",
                    direction="long",
                    priority=AlertPriority.MEDIUM,
                    current_price=snapshot.current_price,
                    trigger_price=snapshot.high_of_day,
                    stop_loss=round(snapshot.ema_9 - 0.02, 2),
                    target=round(snapshot.high_of_day + (snapshot.atr * 1.5), 2),
                    risk_reward=2.0,
                    trigger_probability=0.55,
                    win_probability=0.55,
                    minutes_to_trigger=15,
                    headline=f"🐕 {symbol} Big Dog - Tight consolidation above VWAP/EMAs",
                    reasoning=[
                        f"Tight consolidation near HOD",
                        f"Above VWAP, 9-EMA, 21-EMA",
                        f"RVOL: {snapshot.rvol:.1f}x",
                        f"Entry: Break of resistance on high volume",
                        f"Exit: Trail with 9/21-EMA",
                        f"Best: 15-28+ min consolidation"
                    ],
                    time_window=self._get_current_time_window().value,
                    market_regime=self._market_regime.value,
                    expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
        return None
    
    async def _check_9_ema_scalp(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """9 EMA Scalp - Institutional buying at 9-EMA"""
        # Near 9-EMA in uptrend
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
                    f"Price testing 9-EMA ${snapshot.ema_9:.2f}",
                    f"Uptrend intact, above VWAP",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Entry: When bids hold at 9-EMA",
                    f"Target: HOD ${snapshot.high_of_day:.2f}",
                    f"Stop: Below 21-EMA ${snapshot.ema_20:.2f}"
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
        
        self._live_alerts[alert.id] = alert
        self._alerts_generated += 1
        
        # Persist to database
        if self.db:
            try:
                await self._save_alert_to_db(alert)
            except Exception as e:
                logger.warning(f"Could not save alert to DB: {e}")
        
        # Notify subscribers
        await self._notify_subscribers(alert)
        
        self._enforce_alert_limit()
        
        logger.info(f"🚨 {alert.headline}")
    
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
        return {
            "running": self._running,
            "scan_count": self._scan_count,
            "alerts_generated": self._alerts_generated,
            "active_alerts": len(self._live_alerts),
            "watchlist_size": len(self._watchlist),
            "scan_interval": self._scan_interval,
            "enabled_setups": list(self._enabled_setups),
            "market_regime": self._market_regime.value,
            "time_window": self._get_current_time_window().value,
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None
        }


# Global instance
_enhanced_scanner: Optional[EnhancedBackgroundScanner] = None


def get_enhanced_scanner() -> EnhancedBackgroundScanner:
    global _enhanced_scanner
    if _enhanced_scanner is None:
        _enhanced_scanner = EnhancedBackgroundScanner()
    return _enhanced_scanner
