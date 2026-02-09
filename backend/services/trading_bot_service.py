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
"""
import os
import asyncio
import logging
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
    # Setup type -> (timeframe, trail_pct, scale_out_pcts)
    "rubber_band": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,  # 1% tight trail for scalps
        "scale_out_pcts": [0.5, 0.3, 0.2],  # More aggressive scale-out
        "close_at_eod": True
    },
    "vwap_bounce": {
        "timeframe": TradeTimeframe.SCALP,
        "trail_pct": 0.01,
        "scale_out_pcts": [0.5, 0.3, 0.2],
        "close_at_eod": True
    },
    "breakout": {
        "timeframe": TradeTimeframe.INTRADAY,
        "trail_pct": 0.015,  # 1.5% trail for intraday
        "scale_out_pcts": [0.33, 0.33, 0.34],
        "close_at_eod": True
    },
    "squeeze": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,  # 2.5% wider trail for swings
        "scale_out_pcts": [0.25, 0.25, 0.5],  # Keep more for runner
        "close_at_eod": False  # Hold overnight
    },
    "trend_continuation": {
        "timeframe": TradeTimeframe.SWING,
        "trail_pct": 0.025,
        "scale_out_pcts": [0.25, 0.25, 0.5],
        "close_at_eod": False
    },
    "position_trade": {
        "timeframe": TradeTimeframe.POSITION,
        "trail_pct": 0.03,  # 3% widest trail for positions
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
    """Risk management parameters"""
    max_risk_per_trade: float = 2500.0      # Maximum $ risk per trade
    max_daily_loss: float = 5000.0           # Maximum daily loss before stopping
    starting_capital: float = 1000000.0      # Account capital for position sizing
    max_position_pct: float = 10.0           # Maximum % of capital per position
    max_open_positions: int = 5              # Maximum concurrent positions
    min_risk_reward: float = 1.5             # Minimum risk/reward ratio
    max_slippage_pct: float = 0.5           # Maximum acceptable slippage %


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


@dataclass
class BotTrade:
    """Complete bot trade record"""
    id: str
    symbol: str
    direction: TradeDirection
    status: TradeStatus
    
    # Setup details
    setup_type: str
    timeframe: str = "intraday"  # scalp, intraday, swing, position
    quality_score: int = 0
    quality_grade: str = ""
    
    # Price levels
    entry_price: float
    current_price: float
    stop_price: float
    target_prices: List[float]
    
    # Position details
    shares: int
    risk_amount: float
    potential_reward: float
    risk_reward_ratio: float
    
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
    
    # Order IDs (from broker)
    entry_order_id: Optional[str] = None
    stop_order_id: Optional[str] = None
    target_order_ids: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        d = asdict(self)
        d['direction'] = self.direction.value if isinstance(self.direction, TradeDirection) else self.direction
        d['status'] = self.status.value if isinstance(self.status, TradeStatus) else self.status
        d['timeframe'] = self.timeframe
        d['close_at_eod'] = self.close_at_eod
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
        self._mode = BotMode.CONFIRMATION  # Start in confirmation mode for safety
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        
        # Risk parameters
        self.risk_params = RiskParameters()
        
        # State
        self._pending_trades: Dict[str, BotTrade] = {}
        self._open_trades: Dict[str, BotTrade] = {}
        self._closed_trades: List[BotTrade] = []
        self._daily_stats = DailyStats(date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        # Configuration
        self._enabled_setups = ["rubber_band", "breakout", "vwap_bounce", "squeeze"]
        self._scan_interval = 30  # seconds
        self._watchlist: List[str] = []
        
        # Services (injected)
        self._alert_system = None
        self._trading_intelligence = None
        self._alpaca_service = None
        self._trade_executor = None
        self._db = None
        
        # Callbacks for real-time updates
        self._trade_callbacks: List[callable] = []
        
        logger.info("TradingBotService initialized")
    
    def set_services(self, alert_system, trading_intelligence, alpaca_service, trade_executor, db):
        """Inject service dependencies"""
        self._alert_system = alert_system
        self._trading_intelligence = trading_intelligence
        self._alpaca_service = alpaca_service
        self._trade_executor = trade_executor
        self._db = db
        logger.info("TradingBotService services configured")
    
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
    
    def get_mode(self) -> BotMode:
        return self._mode
    
    def update_risk_params(self, **kwargs):
        """Update risk parameters"""
        for key, value in kwargs.items():
            if hasattr(self.risk_params, key):
                setattr(self.risk_params, key, value)
                logger.info(f"Risk param updated: {key} = {value}")
    
    def set_watchlist(self, symbols: List[str]):
        """Set symbols to scan"""
        self._watchlist = [s.upper() for s in symbols]
    
    def set_enabled_setups(self, setups: List[str]):
        """Set which setup types to trade"""
        self._enabled_setups = setups
    
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
    
    # ==================== BOT CONTROL ====================
    
    async def start(self):
        """Start the trading bot"""
        if self._running:
            return
        
        self._running = True
        self._mode = BotMode.CONFIRMATION if self._mode == BotMode.PAUSED else self._mode
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info(f"Trading bot started in {self._mode.value} mode")
    
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
    
    async def _scan_loop(self):
        """Main scanning loop"""
        while self._running:
            try:
                # Check if daily loss limit hit
                if self._daily_stats.net_pnl <= -self.risk_params.max_daily_loss:
                    if not self._daily_stats.daily_limit_hit:
                        self._daily_stats.daily_limit_hit = True
                        logger.warning(f"Daily loss limit hit: ${self._daily_stats.net_pnl:.2f}")
                    await asyncio.sleep(60)
                    continue
                
                # Skip if paused
                if self._mode == BotMode.PAUSED:
                    await asyncio.sleep(self._scan_interval)
                    continue
                
                # Scan for opportunities
                await self._scan_for_opportunities()
                
                # Update open positions
                await self._update_open_positions()
                
                # Check for EOD close on scalp/intraday trades
                await self._check_eod_close()
                
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
            
            await asyncio.sleep(self._scan_interval)
    
    # ==================== OPPORTUNITY SCANNING ====================
    
    async def _scan_for_opportunities(self):
        """Scan for trade opportunities using alert system"""
        if not self._alert_system:
            return
        
        # Check max open positions
        if len(self._open_trades) >= self.risk_params.max_open_positions:
            return
        
        try:
            # Get alerts from existing system
            alerts = await self._get_trade_alerts()
            
            for alert in alerts:
                # Skip if already have position in this symbol
                if any(t.symbol == alert.get('symbol') for t in self._open_trades.values()):
                    continue
                
                # Skip if pending trade exists
                if any(t.symbol == alert.get('symbol') for t in self._pending_trades.values()):
                    continue
                
                # Evaluate and create trade opportunity
                trade = await self._evaluate_opportunity(alert)
                
                if trade:
                    if self._mode == BotMode.AUTONOMOUS:
                        # Execute immediately
                        await self._execute_trade(trade)
                    else:
                        # Add to pending for confirmation
                        self._pending_trades[trade.id] = trade
                        await self._notify_trade_update(trade, "pending")
                    
        except Exception as e:
            logger.error(f"Scan error: {e}")
    
    async def _get_trade_alerts(self) -> List[Dict]:
        """Get trade alerts from alert system"""
        alerts = []
        
        try:
            # Use background scanner alerts if available
            from services.background_scanner import get_background_scanner
            scanner = get_background_scanner()
            
            # Get current alerts - method is get_live_alerts
            scanner_alerts = scanner.get_live_alerts()
            
            for alert in scanner_alerts:
                # Convert LiveAlert to dict
                alert_dict = {
                    'symbol': alert.symbol,
                    'setup_type': alert.setup_type,
                    'direction': alert.direction,
                    'current_price': alert.current_price,
                    'trigger_price': alert.trigger_price,
                    'stop_price': alert.stop_loss,
                    'targets': [alert.target],
                    'score': int(alert.trigger_probability * 100),
                    'trigger_probability': alert.trigger_probability,
                    'headline': alert.headline,
                    'technical_reasons': alert.reasoning,
                    'warnings': []
                }
                
                if alert_dict.get('setup_type') in self._enabled_setups:
                    alerts.append(alert_dict)
            
        except Exception as e:
            logger.error(f"Error getting alerts: {e}")
        
        return alerts[:10]  # Limit to top 10
    
    async def _evaluate_opportunity(self, alert: Dict) -> Optional[BotTrade]:
        """Evaluate an alert and create a trade if it meets criteria"""
        try:
            symbol = alert.get('symbol')
            setup_type = alert.get('setup_type')
            direction_str = alert.get('direction', 'long')
            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT
            
            # Get current price
            current_price = alert.get('current_price', 0)
            if not current_price and self._alpaca_service:
                quote = await self._alpaca_service.get_quote(symbol)
                current_price = quote.get('price', 0) if quote else 0
            
            if not current_price:
                return None
            
            # Get trade parameters from alert
            entry_price = alert.get('trigger_price', current_price)
            stop_price = alert.get('stop_price', 0)
            target_prices = alert.get('targets', [])
            
            # Calculate stop if not provided
            if not stop_price:
                atr = alert.get('atr', current_price * 0.02)  # Default 2% ATR
                stop_price = entry_price - atr if direction == TradeDirection.LONG else entry_price + atr
            
            # Calculate targets if not provided
            if not target_prices:
                risk = abs(entry_price - stop_price)
                if direction == TradeDirection.LONG:
                    target_prices = [entry_price + risk * 1.5, entry_price + risk * 2.5, entry_price + risk * 4]
                else:
                    target_prices = [entry_price - risk * 1.5, entry_price - risk * 2.5, entry_price - risk * 4]
            
            # Calculate position size
            shares, risk_amount = self._calculate_position_size(entry_price, stop_price, direction)
            
            if shares <= 0:
                return None
            
            # Calculate risk/reward
            primary_target = target_prices[0] if target_prices else entry_price
            potential_reward = abs(primary_target - entry_price) * shares
            risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0
            
            # Check minimum risk/reward
            if risk_reward_ratio < self.risk_params.min_risk_reward:
                logger.debug(f"Skipping {symbol}: R:R {risk_reward_ratio:.2f} below minimum {self.risk_params.min_risk_reward}")
                return None
            
            # Get quality score
            quality_score = alert.get('score', 70)
            quality_grade = self._score_to_grade(quality_score)
            
            # Generate explanation
            explanation = self._generate_explanation(alert, shares, entry_price, stop_price, target_prices)
            
            # Get strategy config for this setup type
            strategy_cfg = STRATEGY_CONFIG.get(setup_type, DEFAULT_STRATEGY_CONFIG)
            timeframe_val = strategy_cfg["timeframe"]
            timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
            trail_pct = strategy_cfg.get("trail_pct", 0.02)
            scale_pcts = strategy_cfg.get("scale_out_pcts", [0.33, 0.33, 0.34])
            close_at_eod = strategy_cfg.get("close_at_eod", True)
            
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
            return trade
            
        except Exception as e:
            logger.error(f"Error evaluating opportunity: {e}")
            return None
    
    def _calculate_position_size(self, entry_price: float, stop_price: float, direction: TradeDirection) -> Tuple[int, float]:
        """
        Calculate position size based on risk management rules.
        Returns (shares, risk_amount)
        """
        # Calculate risk per share
        risk_per_share = abs(entry_price - stop_price)
        
        if risk_per_share <= 0:
            return 0, 0
        
        # Calculate max shares based on max risk per trade
        max_shares_by_risk = int(self.risk_params.max_risk_per_trade / risk_per_share)
        
        # Calculate max shares based on max position size
        max_position_value = self.risk_params.starting_capital * (self.risk_params.max_position_pct / 100)
        max_shares_by_capital = int(max_position_value / entry_price)
        
        # Take the minimum
        shares = min(max_shares_by_risk, max_shares_by_capital)
        
        # Ensure at least 1 share
        shares = max(shares, 1)
        
        # Calculate actual risk
        risk_amount = shares * risk_per_share
        
        # Cap risk at max per trade
        if risk_amount > self.risk_params.max_risk_per_trade:
            shares = int(self.risk_params.max_risk_per_trade / risk_per_share)
            risk_amount = shares * risk_per_share
        
        return shares, risk_amount
    
    def _score_to_grade(self, score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90: return "A+"
        if score >= 80: return "A"
        if score >= 70: return "B+"
        if score >= 60: return "B"
        if score >= 50: return "C"
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
    
    def _generate_explanation(self, alert: Dict, shares: int, entry: float, stop: float, targets: List[float]) -> TradeExplanation:
        """Generate detailed explanation for the trade"""
        symbol = alert.get('symbol', '')
        setup_type = alert.get('setup_type', '')
        direction = alert.get('direction', 'long')
        
        risk_per_share = abs(entry - stop)
        total_risk = shares * risk_per_share
        target_1_profit = abs(targets[0] - entry) * shares if targets else 0
        
        return TradeExplanation(
            summary=f"{setup_type.replace('_', ' ').title()} setup identified on {symbol}. "
                    f"{'Buying' if direction == 'long' else 'Shorting'} {shares} shares at ${entry:.2f} "
                    f"with stop at ${stop:.2f} and target at ${targets[0]:.2f}.",
            
            setup_identified=alert.get('headline', f"{setup_type} pattern detected"),
            
            technical_reasons=alert.get('technical_reasons', [
                f"Setup type: {setup_type}",
                f"Score: {alert.get('score', 'N/A')}/100",
                f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%"
            ]),
            
            fundamental_reasons=alert.get('fundamental_reasons', []),
            
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
            
            confidence_factors=[
                f"Quality score: {alert.get('score', 0)}/100",
                f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%",
                f"Risk/Reward: {abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
            ],
            
            warnings=alert.get('warnings', [])
        )
    
    # ==================== TRADE EXECUTION ====================
    
    async def _execute_trade(self, trade: BotTrade):
        """Execute a trade via the trade executor"""
        if not self._trade_executor:
            logger.error("Trade executor not configured")
            return
        
        try:
            # Execute entry order
            result = await self._trade_executor.execute_entry(trade)
            
            if result.get('success'):
                trade.status = TradeStatus.OPEN
                trade.fill_price = result.get('fill_price', trade.entry_price)
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')
                
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
                
                logger.info(f"Trade executed: {trade.symbol} {trade.shares} @ ${trade.fill_price:.2f}")
            else:
                trade.status = TradeStatus.REJECTED
                logger.warning(f"Trade rejected: {result.get('error')}")
                
        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            trade.status = TradeStatus.REJECTED
    
    async def confirm_trade(self, trade_id: str) -> bool:
        """Confirm a pending trade for execution"""
        if trade_id not in self._pending_trades:
            return False
        
        trade = self._pending_trades[trade_id]
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
        """Update P&L for open positions"""
        if not self._alpaca_service:
            return
        
        for trade_id, trade in list(self._open_trades.items()):
            try:
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
        Close trades marked close_at_eod near market close (3:50 PM ET).
        Scalp and intraday trades must be closed before end of day.
        """
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        
        now_et = datetime.now(ZoneInfo("America/New_York"))
        
        # Only run on weekdays during market hours
        if now_et.weekday() >= 5:
            return
        
        # Close at 3:50 PM ET (10 min before market close)
        eod_hour = 15
        eod_minute = 50
        
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return
        
        # After 4:00 PM, stop checking (market closed)
        if now_et.hour >= 16:
            return
        
        for trade_id, trade in list(self._open_trades.items()):
            if trade.close_at_eod:
                logger.info(f"EOD CLOSE: Closing {trade.symbol} ({trade.timeframe}) - close_at_eod=True")
                await self.close_trade(trade_id, reason="eod_close")

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
                        
                        # Update daily stats
                        if trade.realized_pnl > 0:
                            self._daily_stats.trades_won += 1
                            self._daily_stats.largest_win = max(self._daily_stats.largest_win, trade.realized_pnl)
                        else:
                            self._daily_stats.trades_lost += 1
                            self._daily_stats.largest_loss = min(self._daily_stats.largest_loss, trade.realized_pnl)
                        
                        self._daily_stats.net_pnl += trade.realized_pnl
                        total = self._daily_stats.trades_won + self._daily_stats.trades_lost
                        self._daily_stats.win_rate = (self._daily_stats.trades_won / total * 100) if total > 0 else 0
                        
                        # Move to closed trades
                        del self._open_trades[trade.id]
                        self._closed_trades.append(trade)
                        
                        await self._notify_trade_update(trade, "closed")
                        await self._save_trade(trade)
                        
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
            
            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0
            
            # Update daily stats
            self._daily_stats.net_pnl += trade.realized_pnl
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
            trades_col = self._db["bot_trades"]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            # Load open trades
            cursor = trades_col.find({"status": "open"})
            for doc in cursor:
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


# Singleton instance
_trading_bot_service: Optional[TradingBotService] = None


def get_trading_bot_service() -> TradingBotService:
    """Get or create the trading bot service singleton"""
    global _trading_bot_service
    if _trading_bot_service is None:
        _trading_bot_service = TradingBotService()
    return _trading_bot_service
