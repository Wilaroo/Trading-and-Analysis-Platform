"""
Background Scanner Service
Runs continuously in the background, scanning for trade setups
and pushing alerts without blocking the main application.

Features:
- Non-blocking async execution
- Configurable scan intervals
- Rate-limited API calls
- Database-persisted alerts
- SSE push notifications
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import uuid

logger = logging.getLogger(__name__)


class AlertPriority(str, Enum):
    CRITICAL = "critical"    # Trigger imminent (< 2 mins)
    HIGH = "high"           # Setting up now
    MEDIUM = "medium"       # On watch
    LOW = "low"             # Developing


@dataclass
class LiveAlert:
    """A live trade alert from the background scanner"""
    id: str
    symbol: str
    setup_type: str
    direction: str
    priority: AlertPriority
    
    # Key info
    current_price: float
    trigger_price: float
    stop_loss: float
    target: float
    risk_reward: float
    
    # Probabilities
    trigger_probability: float
    win_probability: float
    
    # Timing
    minutes_to_trigger: int
    
    # Context
    headline: str
    reasoning: List[str]
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    acknowledged: bool = False
    status: str = "active"  # active, triggered, expired, dismissed
    
    def to_dict(self) -> Dict:
        return asdict(self)


class BackgroundScannerService:
    """
    Background scanner that runs independently of the main app.
    Uses asyncio for non-blocking execution.
    """
    
    def __init__(self, db=None):
        self.db = db
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        
        # Configuration
        self._scan_interval = 90  # seconds between scans
        self._watchlist: List[str] = []
        self._enabled_setups: Set[str] = {
            "rubber_band", "breakout", "vwap_bounce",  # Original setups
            "squeeze", "gap_play", "orb", "relative_strength", "mean_reversion"  # New setups
        }
        
        # Alert management
        self._live_alerts: Dict[str, LiveAlert] = {}
        self._alert_subscribers: List[asyncio.Queue] = []
        self._max_alerts = 20
        
        # Rate limiting
        self._last_scan_time: Optional[datetime] = None
        self._min_scan_interval = 30  # Minimum seconds between scans
        self._symbols_per_batch = 5   # Scan in batches to avoid overload
        self._batch_delay = 2         # Seconds between batches
        
        # Services (lazy loaded)
        self._technical_service = None
        self._alert_system = None
        
        # Stats
        self._scan_count = 0
        self._alerts_generated = 0
        
        if db is not None:
            self.alerts_collection = db["live_alerts"]
    
    @property
    def technical_service(self):
        if self._technical_service is None:
            from services.realtime_technical_service import get_technical_service
            self._technical_service = get_technical_service()
        return self._technical_service
    
    @property
    def alert_system(self):
        if self._alert_system is None:
            from services.alert_system import get_alert_system
            self._alert_system = get_alert_system()
        return self._alert_system
    
    # ==================== LIFECYCLE ====================
    
    async def start(self):
        """Start the background scanner"""
        if self._running:
            logger.warning("Background scanner already running")
            return
        
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("🔄 Background scanner started")
    
    async def stop(self):
        """Stop the background scanner"""
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        logger.info("⏹️ Background scanner stopped")
    
    def is_running(self) -> bool:
        return self._running
    
    # ==================== MAIN SCAN LOOP ====================
    
    async def _scan_loop(self):
        """Main scanning loop - runs in background"""
        logger.info("Background scan loop started")
        
        while self._running:
            try:
                # Check if enough time has passed
                now = datetime.now(timezone.utc)
                if self._last_scan_time:
                    elapsed = (now - self._last_scan_time).total_seconds()
                    if elapsed < self._min_scan_interval:
                        await asyncio.sleep(self._min_scan_interval - elapsed)
                        continue
                
                # Run scan
                await self._run_scan()
                self._last_scan_time = datetime.now(timezone.utc)
                self._scan_count += 1
                
                # Clean up expired alerts
                self._cleanup_expired_alerts()
                
                # Wait for next scan
                await asyncio.sleep(self._scan_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Background scan error: {e}")
                await asyncio.sleep(10)  # Wait before retry on error
    
    async def _run_scan(self):
        """Execute a single scan cycle"""
        watchlist = self._watchlist or self._get_default_watchlist()
        
        logger.debug(f"Running background scan on {len(watchlist)} symbols")
        
        # Scan in batches to avoid overwhelming APIs
        for i in range(0, len(watchlist), self._symbols_per_batch):
            batch = watchlist[i:i + self._symbols_per_batch]
            
            for symbol in batch:
                try:
                    await self._scan_symbol(symbol)
                except Exception as e:
                    logger.warning(f"Error scanning {symbol}: {e}")
                
                # Yield to event loop to prevent blocking WebSocket connections
                await asyncio.sleep(0)
            
            # Small delay between batches
            if i + self._symbols_per_batch < len(watchlist):
                await asyncio.sleep(self._batch_delay)
    
    async def _scan_symbol(self, symbol: str):
        """Scan a single symbol for setups"""
        # Get technical snapshot
        snapshot = await self.technical_service.get_technical_snapshot(symbol)
        if not snapshot:
            return
        
        # Check for various setups
        alerts = []
        
        # Rubber Band Long
        if "rubber_band" in self._enabled_setups:
            if snapshot.dist_from_ema9 < -2.5 and snapshot.rsi_14 < 38:
                alert = self._create_rubber_band_alert(symbol, snapshot, "long")
                if alert:
                    alerts.append(alert)
        
            # Rubber Band Short
            if snapshot.dist_from_ema9 > 3.0 and snapshot.rsi_14 > 65:
                alert = self._create_rubber_band_alert(symbol, snapshot, "short")
                if alert:
                    alerts.append(alert)
        
        # Breakout
        if "breakout" in self._enabled_setups:
            dist_to_resistance = ((snapshot.resistance - snapshot.current_price) / snapshot.current_price) * 100
            if 0 < dist_to_resistance < 1.0 and snapshot.rvol >= 2.0:
                alert = self._create_breakout_alert(symbol, snapshot)
                if alert:
                    alerts.append(alert)
        
        # VWAP Bounce
        if "vwap_bounce" in self._enabled_setups:
            if -0.8 < snapshot.dist_from_vwap < 0.3 and snapshot.trend == "uptrend" and snapshot.rvol >= 1.5:
                alert = self._create_vwap_bounce_alert(symbol, snapshot)
                if alert:
                    alerts.append(alert)
        
        # Squeeze Detection (Bollinger Bands inside Keltner Channels)
        if "squeeze" in self._enabled_setups:
            if snapshot.squeeze_on and snapshot.rvol >= 1.2:
                alert = self._create_squeeze_alert(symbol, snapshot)
                if alert:
                    alerts.append(alert)
        
        # Gap & Go / Gap Fade
        if "gap_play" in self._enabled_setups:
            if abs(snapshot.gap_pct) >= 2.0 and snapshot.rvol >= 1.5:
                alert = self._create_gap_play_alert(symbol, snapshot)
                if alert:
                    alerts.append(alert)
        
        # Opening Range Breakout
        if "orb" in self._enabled_setups:
            if snapshot.or_breakout in ("above", "below") and snapshot.rvol >= 1.3:
                alert = self._create_orb_alert(symbol, snapshot)
                if alert:
                    alerts.append(alert)
        
        # Relative Strength / Weakness vs SPY
        if "relative_strength" in self._enabled_setups:
            if abs(snapshot.rs_vs_spy) >= 2.0 and snapshot.rvol >= 1.2:
                alert = self._create_relative_strength_alert(symbol, snapshot)
                if alert:
                    alerts.append(alert)
        
        # Mean Reversion
        if "mean_reversion" in self._enabled_setups:
            is_oversold = snapshot.rsi_14 < 30 and snapshot.dist_from_ema20 < -3.0
            is_overbought = snapshot.rsi_14 > 70 and snapshot.dist_from_ema20 > 3.0
            near_support = snapshot.current_price <= snapshot.support * 1.02
            near_resistance = snapshot.current_price >= snapshot.resistance * 0.98
            if (is_oversold and near_support) or (is_overbought and near_resistance):
                alert = self._create_mean_reversion_alert(symbol, snapshot, "long" if is_oversold else "short")
                if alert:
                    alerts.append(alert)
        
        # Process new alerts
        for alert in alerts:
            await self._process_new_alert(alert)
    
    # ==================== ALERT CREATION ====================
    
    def _create_rubber_band_alert(self, symbol: str, snapshot, direction: str) -> Optional[LiveAlert]:
        """Create a rubber band setup alert"""
        if direction == "long":
            extension = abs(snapshot.dist_from_ema9)
            trigger_price = snapshot.ema_9
            stop_loss = snapshot.current_price - (snapshot.atr * 0.75)
            target = snapshot.ema_9 + (snapshot.atr * 0.5)
            
            # Determine priority based on how close to trigger
            if extension < 3.0:
                priority = AlertPriority.HIGH
                minutes = 5
            elif extension < 4.0:
                priority = AlertPriority.MEDIUM
                minutes = 15
            else:
                priority = AlertPriority.LOW
                minutes = 30
            
            headline = f"🎯 {symbol} Rubber Band LONG - {extension:.1f}% extended below EMA9"
            reasoning = [
                f"Price extended {extension:.1f}% below 9 EMA",
                f"RSI oversold at {snapshot.rsi_14:.0f}",
                f"RVOL: {snapshot.rvol:.1f}x",
                f"Target: Snap back to EMA9 (${trigger_price:.2f})"
            ]
        else:
            extension = snapshot.dist_from_ema9
            trigger_price = snapshot.ema_9
            stop_loss = snapshot.current_price + (snapshot.atr * 0.75)
            target = snapshot.ema_9 - (snapshot.atr * 0.5)
            
            if extension > 4.0:
                priority = AlertPriority.HIGH
                minutes = 5
            elif extension > 3.5:
                priority = AlertPriority.MEDIUM
                minutes = 15
            else:
                priority = AlertPriority.LOW
                minutes = 30
            
            headline = f"🎯 {symbol} Rubber Band SHORT - {extension:.1f}% extended above EMA9"
            reasoning = [
                f"Price extended {extension:.1f}% above 9 EMA",
                f"RSI overbought at {snapshot.rsi_14:.0f}",
                f"RVOL: {snapshot.rvol:.1f}x",
                f"Target: Snap back to EMA9 (${trigger_price:.2f})"
            ]
        
        risk = abs(snapshot.current_price - stop_loss)
        reward = abs(target - snapshot.current_price)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"rb_{symbol}_{direction}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=f"rubber_band_{direction}",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=trigger_price,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.65 if priority == AlertPriority.HIGH else 0.50,
            win_probability=0.62,
            minutes_to_trigger=minutes,
            headline=headline,
            reasoning=reasoning,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        )
    
    def _create_breakout_alert(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Create a breakout alert"""
        dist_to_breakout = ((snapshot.resistance - snapshot.current_price) / snapshot.current_price) * 100
        
        if dist_to_breakout < 0.3:
            priority = AlertPriority.CRITICAL
            minutes = 2
        elif dist_to_breakout < 0.6:
            priority = AlertPriority.HIGH
            minutes = 5
        else:
            priority = AlertPriority.MEDIUM
            minutes = 15
        
        stop_loss = snapshot.resistance - snapshot.atr
        target = snapshot.resistance + (snapshot.atr * 2)
        
        risk = abs(snapshot.resistance - stop_loss)
        reward = abs(target - snapshot.resistance)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"breakout_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="breakout",
            direction="long",
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.resistance,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.70 if priority == AlertPriority.CRITICAL else 0.55,
            win_probability=0.55,
            minutes_to_trigger=minutes,
            headline=f"🚀 {symbol} BREAKOUT - {dist_to_breakout:.1f}% from resistance ${snapshot.resistance:.2f}",
            reasoning=[
                f"Price {dist_to_breakout:.1f}% below resistance at ${snapshot.resistance:.2f}",
                f"Strong volume: {snapshot.rvol:.1f}x RVOL",
                "Above VWAP" if snapshot.above_vwap else "Testing VWAP",
                "Watch for volume surge on break"
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        )
    
    def _create_vwap_bounce_alert(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Create a VWAP bounce alert"""
        dist = abs(snapshot.dist_from_vwap)
        
        if dist < 0.3:
            priority = AlertPriority.HIGH
            minutes = 5
        else:
            priority = AlertPriority.MEDIUM
            minutes = 15
        
        stop_loss = snapshot.vwap - (snapshot.atr * 0.5)
        target = snapshot.vwap + (snapshot.atr * 1.5)
        
        risk = abs(snapshot.vwap - stop_loss)
        reward = abs(target - snapshot.vwap)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"vwap_{symbol}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="vwap_bounce",
            direction="long",
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.vwap,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.60,
            win_probability=0.60,
            minutes_to_trigger=minutes,
            headline=f"📍 {symbol} VWAP Bounce - Testing ${snapshot.vwap:.2f}",
            reasoning=[
                f"Price {snapshot.dist_from_vwap:+.1f}% from VWAP",
                "Uptrend intact (above EMAs)",
                f"RVOL: {snapshot.rvol:.1f}x",
                "Looking for bounce off VWAP support"
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        )
    
    # ==================== NEW SETUP ALERT CREATION ====================
    
    def _create_squeeze_alert(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Squeeze Detection: BB inside KC = volatility compression about to explode"""
        # Direction based on momentum (squeeze fire)
        direction = "long" if snapshot.squeeze_fire > 0 else "short"
        
        # Priority based on BB width (tighter = more explosive)
        if snapshot.bb_width < 3.0:
            priority = AlertPriority.CRITICAL
            minutes = 5
        elif snapshot.bb_width < 5.0:
            priority = AlertPriority.HIGH
            minutes = 10
        else:
            priority = AlertPriority.MEDIUM
            minutes = 20
        
        if direction == "long":
            stop_loss = snapshot.bb_lower
            target = snapshot.current_price + (snapshot.atr * 2.5)
        else:
            stop_loss = snapshot.bb_upper
            target = snapshot.current_price - (snapshot.atr * 2.5)
        
        risk = abs(snapshot.current_price - stop_loss)
        reward = abs(target - snapshot.current_price)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"squeeze_{symbol}_{direction}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="squeeze",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.bb_upper if direction == "long" else snapshot.bb_lower,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.72 if priority == AlertPriority.CRITICAL else 0.60,
            win_probability=0.65,
            minutes_to_trigger=minutes,
            headline=f"SQUEEZE {symbol} {direction.upper()} - BB Width {snapshot.bb_width:.1f}% | Momentum {'bullish' if direction == 'long' else 'bearish'}",
            reasoning=[
                "Bollinger Bands INSIDE Keltner Channels = volatility compression",
                f"BB Width: {snapshot.bb_width:.1f}% (tighter = more explosive move)",
                f"Squeeze momentum: {snapshot.squeeze_fire:+.2f} ({'bullish' if snapshot.squeeze_fire > 0 else 'bearish'})",
                f"RVOL: {snapshot.rvol:.1f}x | RSI: {snapshot.rsi_14:.0f}",
                "Expect sharp directional move when squeeze fires"
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        )
    
    def _create_gap_play_alert(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Gap & Go or Gap Fade based on gap characteristics"""
        gap = snapshot.gap_pct
        holding = snapshot.holding_gap
        
        # Gap & Go: gap up + holding + volume = continuation
        # Gap Fade: gap up + failing + reversal candle = fade
        if gap > 0:
            if holding and snapshot.above_vwap:
                # Gap & Go Long
                setup = "gap_go"
                direction = "long"
                stop_loss = max(snapshot.vwap, snapshot.low_of_day)
                target = snapshot.current_price + (abs(gap) / 100 * snapshot.prev_close * 0.5)
                headline = f"GAP & GO {symbol} +{gap:.1f}% - Holding above VWAP"
                reasoning = [
                    f"Gapped up {gap:.1f}% and HOLDING the gap",
                    f"Trading above VWAP (${snapshot.vwap:.2f})",
                    f"RVOL: {snapshot.rvol:.1f}x confirms institutional interest",
                    f"Look for continuation above high of day ${snapshot.high_of_day:.2f}"
                ]
            else:
                # Gap Fade Short
                setup = "gap_fade"
                direction = "short"
                stop_loss = snapshot.high_of_day + (snapshot.atr * 0.3)
                target = snapshot.prev_close
                headline = f"GAP FADE {symbol} +{gap:.1f}% - Losing gap, fading to fill"
                reasoning = [
                    f"Gapped up {gap:.1f}% but FAILING to hold",
                    "Below VWAP — sellers in control",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Target: Gap fill to prev close ${snapshot.prev_close:.2f}"
                ]
        else:
            if not holding and not snapshot.above_vwap:
                # Gap Down continuation (short)
                setup = "gap_go"
                direction = "short"
                stop_loss = snapshot.vwap
                target = snapshot.current_price - (abs(gap) / 100 * snapshot.prev_close * 0.5)
                headline = f"GAP DOWN {symbol} {gap:.1f}% - Selling continues"
                reasoning = [
                    f"Gapped down {gap:.1f}% and failing to recover",
                    "Below VWAP — no buyer support",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    "Look for continuation below low of day"
                ]
            else:
                # Gap Down Reversal (long)
                setup = "gap_fade"
                direction = "long"
                stop_loss = snapshot.low_of_day - (snapshot.atr * 0.3)
                target = snapshot.prev_close
                headline = f"GAP REVERSAL {symbol} {gap:.1f}% - Recovering, gap fill possible"
                reasoning = [
                    f"Gapped down {gap:.1f}% but RECOVERING",
                    "Reclaiming VWAP — buyers stepping in",
                    f"RVOL: {snapshot.rvol:.1f}x",
                    f"Target: Gap fill to prev close ${snapshot.prev_close:.2f}"
                ]
        
        priority = AlertPriority.HIGH if abs(gap) >= 4.0 else AlertPriority.MEDIUM
        risk = abs(snapshot.current_price - stop_loss)
        reward = abs(target - snapshot.current_price)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"gap_{symbol}_{setup}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=setup,
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.high_of_day if direction == "long" else snapshot.low_of_day,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.65,
            win_probability=0.58,
            minutes_to_trigger=10,
            headline=headline,
            reasoning=reasoning,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        )
    
    def _create_orb_alert(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Opening Range Breakout: price breaks above/below first 30-min range"""
        direction = "long" if snapshot.or_breakout == "above" else "short"
        or_range = snapshot.or_high - snapshot.or_low
        or_range_pct = (or_range / snapshot.or_low * 100) if snapshot.or_low > 0 else 0
        
        if direction == "long":
            stop_loss = snapshot.or_high - (or_range * 0.5)  # Mid-range stop
            target = snapshot.or_high + or_range  # 1x range extension
            trigger = snapshot.or_high
        else:
            stop_loss = snapshot.or_low + (or_range * 0.5)
            target = snapshot.or_low - or_range
            trigger = snapshot.or_low
        
        # Higher priority for tight ranges (more explosive)
        if or_range_pct < 1.0:
            priority = AlertPriority.CRITICAL
            minutes = 3
        elif or_range_pct < 2.0:
            priority = AlertPriority.HIGH
            minutes = 5
        else:
            priority = AlertPriority.MEDIUM
            minutes = 10
        
        risk = abs(snapshot.current_price - stop_loss)
        reward = abs(target - snapshot.current_price)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"orb_{symbol}_{direction}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="orb",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=round(trigger, 2),
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.68 if priority == AlertPriority.CRITICAL else 0.55,
            win_probability=0.60,
            minutes_to_trigger=minutes,
            headline=f"ORB {symbol} {direction.upper()} - Broke {'above' if direction == 'long' else 'below'} 30-min range",
            reasoning=[
                f"Opening Range: ${snapshot.or_low:.2f} - ${snapshot.or_high:.2f} ({or_range_pct:.1f}% range)",
                f"Price broke {'above' if direction == 'long' else 'below'} at ${trigger:.2f}",
                f"RVOL: {snapshot.rvol:.1f}x confirms participation",
                f"Target: {or_range_pct:.1f}% range extension to ${target:.2f}",
                f"{'Above VWAP — trend aligned' if snapshot.above_vwap and direction == 'long' else 'Below VWAP — trend aligned' if not snapshot.above_vwap and direction == 'short' else 'Counter-trend — use tighter stops'}"
            ],
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        )
    
    def _create_relative_strength_alert(self, symbol: str, snapshot) -> Optional[LiveAlert]:
        """Relative Strength/Weakness vs SPY: leaders and laggards"""
        rs = snapshot.rs_vs_spy
        
        if rs > 0:
            # Outperforming SPY — relative strength leader
            direction = "long"
            strength_type = "leader"
            stop_loss = snapshot.current_price - (snapshot.atr * 1.5)
            target = snapshot.current_price + (snapshot.atr * 3)
            headline = f"RS LEADER {symbol} +{rs:.1f}% vs SPY - Outperforming market"
            reasoning = [
                f"Outperforming SPY by {rs:.1f}% today",
                "Relative strength leaders tend to continue outperforming",
                f"Trend: {snapshot.trend} | RSI: {snapshot.rsi_14:.0f}",
                f"RVOL: {snapshot.rvol:.1f}x | {'Above VWAP' if snapshot.above_vwap else 'Below VWAP'}",
                "Play: Buy dips, ride the relative strength"
            ]
        else:
            # Underperforming SPY — relative weakness laggard
            direction = "short"
            strength_type = "laggard"
            stop_loss = snapshot.current_price + (snapshot.atr * 1.5)
            target = snapshot.current_price - (snapshot.atr * 3)
            headline = f"RS LAGGARD {symbol} {rs:.1f}% vs SPY - Underperforming market"
            reasoning = [
                f"Underperforming SPY by {abs(rs):.1f}% today",
                "Relative weakness laggards tend to continue underperforming",
                f"Trend: {snapshot.trend} | RSI: {snapshot.rsi_14:.0f}",
                f"RVOL: {snapshot.rvol:.1f}x | {'Above VWAP' if snapshot.above_vwap else 'Below VWAP'}",
                "Play: Short rallies, ride the weakness"
            ]
        
        priority = AlertPriority.HIGH if abs(rs) >= 4.0 else AlertPriority.MEDIUM
        risk = abs(snapshot.current_price - stop_loss)
        reward = abs(target - snapshot.current_price)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"rs_{symbol}_{strength_type}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type=f"relative_strength_{strength_type}",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.current_price,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.55,
            win_probability=0.58,
            minutes_to_trigger=15,
            headline=headline,
            reasoning=reasoning,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        )
    
    def _create_mean_reversion_alert(self, symbol: str, snapshot, direction: str) -> Optional[LiveAlert]:
        """Mean Reversion: RSI extreme + near support/resistance + volume divergence"""
        if direction == "long":
            # Oversold bounce at support
            stop_loss = snapshot.support - (snapshot.atr * 0.5)
            target = snapshot.ema_20
            headline = f"MEAN REVERSION {symbol} LONG - RSI {snapshot.rsi_14:.0f} at support ${snapshot.support:.2f}"
            reasoning = [
                f"RSI extremely oversold at {snapshot.rsi_14:.0f}",
                f"Price near support ${snapshot.support:.2f}",
                f"Extended {abs(snapshot.dist_from_ema20):.1f}% below 20 EMA — snapback likely",
                f"RVOL: {snapshot.rvol:.1f}x",
                f"Target: Reversion to 20 EMA at ${snapshot.ema_20:.2f}"
            ]
        else:
            # Overbought reversal at resistance
            stop_loss = snapshot.resistance + (snapshot.atr * 0.5)
            target = snapshot.ema_20
            headline = f"MEAN REVERSION {symbol} SHORT - RSI {snapshot.rsi_14:.0f} at resistance ${snapshot.resistance:.2f}"
            reasoning = [
                f"RSI extremely overbought at {snapshot.rsi_14:.0f}",
                f"Price near resistance ${snapshot.resistance:.2f}",
                f"Extended {snapshot.dist_from_ema20:.1f}% above 20 EMA — pullback likely",
                f"RVOL: {snapshot.rvol:.1f}x",
                f"Target: Reversion to 20 EMA at ${snapshot.ema_20:.2f}"
            ]
        
        priority = AlertPriority.HIGH if snapshot.rsi_14 < 25 or snapshot.rsi_14 > 75 else AlertPriority.MEDIUM
        risk = abs(snapshot.current_price - stop_loss)
        reward = abs(target - snapshot.current_price)
        rr = reward / risk if risk > 0 else 1
        
        return LiveAlert(
            id=f"mr_{symbol}_{direction}_{datetime.now().strftime('%H%M%S')}",
            symbol=symbol,
            setup_type="mean_reversion",
            direction=direction,
            priority=priority,
            current_price=snapshot.current_price,
            trigger_price=snapshot.support if direction == "long" else snapshot.resistance,
            stop_loss=round(stop_loss, 2),
            target=round(target, 2),
            risk_reward=round(rr, 2),
            trigger_probability=0.62,
            win_probability=0.60,
            minutes_to_trigger=15,
            headline=headline,
            reasoning=reasoning,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        )
    
    # ==================== ALERT MANAGEMENT ====================
    
    async def _process_new_alert(self, alert: LiveAlert):
        """Process a new alert - check for duplicates, store, and notify"""
        # Check for duplicate (same symbol + setup type within last hour)
        for existing in self._live_alerts.values():
            if (existing.symbol == alert.symbol and 
                existing.setup_type == alert.setup_type and
                existing.status == "active"):
                # Update existing instead of creating new
                return
        
        # Add to live alerts
        self._live_alerts[alert.id] = alert
        self._alerts_generated += 1
        
        # Persist to database
        if self.db is not None:
            try:
                await self._save_alert_to_db(alert)
            except Exception as e:
                logger.warning(f"Could not save alert to DB: {e}")
        
        # Notify subscribers (SSE)
        await self._notify_subscribers(alert)
        
        # Limit total alerts
        self._enforce_alert_limit()
        
        logger.info(f"🚨 New alert: {alert.headline}")
    
    async def _save_alert_to_db(self, alert: LiveAlert):
        """Save alert to MongoDB"""
        if self.alerts_collection is not None:
            await asyncio.to_thread(
                self.alerts_collection.update_one,
                {"id": alert.id},
                {"$set": alert.to_dict()},
                upsert=True
            )
    
    async def _notify_subscribers(self, alert: LiveAlert):
        """Notify all SSE subscribers of new alert"""
        alert_data = alert.to_dict()
        for queue in self._alert_subscribers:
            try:
                queue.put_nowait(alert_data)
            except asyncio.QueueFull:
                pass  # Skip if queue is full
    
    def _cleanup_expired_alerts(self):
        """Remove expired alerts"""
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
            self._live_alerts[alert_id].status = "expired"
            del self._live_alerts[alert_id]
    
    def _enforce_alert_limit(self):
        """Keep only the most recent alerts"""
        if len(self._live_alerts) > self._max_alerts:
            # Sort by created_at and remove oldest
            sorted_alerts = sorted(
                self._live_alerts.items(),
                key=lambda x: x[1].created_at,
                reverse=True
            )
            self._live_alerts = dict(sorted_alerts[:self._max_alerts])
    
    # ==================== PUBLIC API ====================
    
    def get_live_alerts(self, priority: AlertPriority = None) -> List[LiveAlert]:
        """Get current live alerts, optionally filtered by priority"""
        alerts = list(self._live_alerts.values())
        
        if priority:
            alerts = [a for a in alerts if a.priority == priority]
        
        # Sort by priority then time
        priority_order = {
            AlertPriority.CRITICAL: 0,
            AlertPriority.HIGH: 1,
            AlertPriority.MEDIUM: 2,
            AlertPriority.LOW: 3
        }
        alerts.sort(key=lambda x: (priority_order.get(x.priority, 4), x.created_at), reverse=True)
        
        return alerts
    
    def get_alert_by_id(self, alert_id: str) -> Optional[LiveAlert]:
        """Get a specific alert by ID"""
        return self._live_alerts.get(alert_id)
    
    def dismiss_alert(self, alert_id: str) -> bool:
        """Dismiss/acknowledge an alert"""
        if alert_id in self._live_alerts:
            self._live_alerts[alert_id].acknowledged = True
            self._live_alerts[alert_id].status = "dismissed"
            return True
        return False
    
    def set_watchlist(self, symbols: List[str]):
        """Set the watchlist for scanning"""
        self._watchlist = [s.upper() for s in symbols]
        logger.info(f"Watchlist updated: {len(self._watchlist)} symbols")
    
    def set_scan_interval(self, seconds: int):
        """Set the scan interval (minimum 30 seconds)"""
        self._scan_interval = max(30, seconds)
    
    def enable_setup(self, setup_type: str):
        """Enable a setup type for scanning"""
        self._enabled_setups.add(setup_type)
    
    def disable_setup(self, setup_type: str):
        """Disable a setup type"""
        self._enabled_setups.discard(setup_type)
    
    def subscribe(self) -> asyncio.Queue:
        """Subscribe to real-time alert notifications (for SSE)"""
        queue = asyncio.Queue(maxsize=50)
        self._alert_subscribers.append(queue)
        return queue
    
    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from notifications"""
        if queue in self._alert_subscribers:
            self._alert_subscribers.remove(queue)
    
    def get_stats(self) -> Dict:
        """Get scanner statistics"""
        return {
            "running": self._running,
            "scan_count": self._scan_count,
            "alerts_generated": self._alerts_generated,
            "active_alerts": len(self._live_alerts),
            "watchlist_size": len(self._watchlist or self._get_default_watchlist()),
            "scan_interval": self._scan_interval,
            "enabled_setups": list(self._enabled_setups),
            "last_scan": self._last_scan_time.isoformat() if self._last_scan_time else None
        }
    
    def _get_default_watchlist(self) -> List[str]:
        """Default watchlist for scanning"""
        return [
            "NVDA", "TSLA", "AMD", "META", "AAPL", "MSFT", "GOOGL", "AMZN",
            "SPY", "QQQ", "NFLX", "COIN", "SQ", "SHOP", "BA"
        ]


# Global instance
_background_scanner: Optional[BackgroundScannerService] = None


def get_background_scanner() -> BackgroundScannerService:
    """Get or create the background scanner"""
    global _background_scanner
    if _background_scanner is None:
        _background_scanner = BackgroundScannerService()
    return _background_scanner
