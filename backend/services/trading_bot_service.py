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
    quality_score: int
    quality_grade: str
    
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
    
    # Execution details
    fill_price: Optional[float] = None
    exit_price: Optional[float] = None
    
    # P&L
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    pnl_pct: float = 0.0
    
    # Timing
    created_at: str = ""
    executed_at: Optional[str] = None
    closed_at: Optional[str] = None
    estimated_duration: str = ""  # e.g., "30min-2hr" for scalp
    
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
            
            # Create trade
            trade = BotTrade(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                direction=direction,
                status=TradeStatus.PENDING,
                setup_type=setup_type,
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
                explanation=explanation
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
                
                # Calculate unrealized P&L
                if trade.direction == TradeDirection.LONG:
                    trade.unrealized_pnl = (trade.current_price - trade.fill_price) * trade.shares
                else:
                    trade.unrealized_pnl = (trade.fill_price - trade.current_price) * trade.shares
                
                trade.pnl_pct = (trade.unrealized_pnl / (trade.fill_price * trade.shares)) * 100
                
                await self._notify_trade_update(trade, "updated")
                
            except Exception as e:
                logger.error(f"Error updating position {trade_id}: {e}")
    
    async def close_trade(self, trade_id: str, reason: str = "manual") -> bool:
        """Close an open trade"""
        if trade_id not in self._open_trades:
            return False
        
        trade = self._open_trades[trade_id]
        
        try:
            if self._trade_executor:
                result = await self._trade_executor.close_position(trade)
                if result.get('success'):
                    trade.exit_price = result.get('fill_price', trade.current_price)
            else:
                trade.exit_price = trade.current_price
            
            # Calculate realized P&L
            if trade.direction == TradeDirection.LONG:
                trade.realized_pnl = (trade.exit_price - trade.fill_price) * trade.shares
            else:
                trade.realized_pnl = (trade.fill_price - trade.exit_price) * trade.shares
            
            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.unrealized_pnl = 0
            
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
            
            logger.info(f"Trade closed: {trade.symbol} P&L: ${trade.realized_pnl:.2f}")
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
        if not self._db:
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
        if not self._db:
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
                explanation=None,  # TODO: deserialize explanation
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
