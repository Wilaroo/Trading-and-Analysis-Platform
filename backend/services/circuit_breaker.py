"""
Circuit Breaker Service - Real-time Risk Controls

Implements automatic trading safeguards:
- Daily loss limit (dollar amount and percentage)
- Consecutive loss limit (tilt protection)
- Trade frequency limit (overtrading protection)
- Drawdown protection (account-level)
- Time-based restrictions (lunch hour, EOD)

When triggered, circuit breakers can:
1. Block new trades entirely
2. Reduce position sizes
3. Require manual override
4. Send alerts to the trader
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitBreakerType(str, Enum):
    """Types of circuit breakers"""
    DAILY_LOSS_DOLLAR = "daily_loss_dollar"
    DAILY_LOSS_PERCENT = "daily_loss_percent"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    TRADE_FREQUENCY = "trade_frequency"
    DRAWDOWN = "drawdown"
    TIME_RESTRICTION = "time_restriction"
    TILT_DETECTION = "tilt_detection"


class CircuitBreakerAction(str, Enum):
    """Actions when circuit breaker trips"""
    BLOCK_ALL = "block_all"           # No new trades allowed
    REDUCE_SIZE = "reduce_size"       # Reduce position size by X%
    REQUIRE_OVERRIDE = "require_override"  # Need manual confirmation
    WARN_ONLY = "warn_only"           # Just alert, don't block


@dataclass
class CircuitBreakerConfig:
    """Configuration for a single circuit breaker"""
    type: CircuitBreakerType
    enabled: bool = True
    threshold: float = 0.0
    action: CircuitBreakerAction = CircuitBreakerAction.WARN_ONLY
    size_reduction_pct: float = 50.0  # For REDUCE_SIZE action
    cooldown_minutes: int = 30        # Time before auto-reset
    
    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "enabled": self.enabled,
            "threshold": self.threshold,
            "action": self.action.value,
            "size_reduction_pct": self.size_reduction_pct,
            "cooldown_minutes": self.cooldown_minutes
        }


@dataclass
class CircuitBreakerState:
    """Current state of a circuit breaker"""
    type: CircuitBreakerType
    is_triggered: bool = False
    triggered_at: Optional[str] = None
    current_value: float = 0.0
    threshold: float = 0.0
    action: CircuitBreakerAction = CircuitBreakerAction.WARN_ONLY
    message: str = ""
    can_override: bool = True
    override_by: Optional[str] = None  # Who overrode it
    
    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "is_triggered": self.is_triggered,
            "triggered_at": self.triggered_at,
            "current_value": round(self.current_value, 2),
            "threshold": self.threshold,
            "action": self.action.value,
            "message": self.message,
            "can_override": self.can_override,
            "override_by": self.override_by
        }


@dataclass
class TradingPermission:
    """Result of checking if trading is allowed"""
    allowed: bool = True
    max_size_multiplier: float = 1.0  # 1.0 = full size, 0.5 = half size
    triggered_breakers: List[CircuitBreakerState] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requires_override: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "allowed": self.allowed,
            "max_size_multiplier": round(self.max_size_multiplier, 2),
            "triggered_breakers": [b.to_dict() for b in self.triggered_breakers],
            "warnings": self.warnings,
            "requires_override": self.requires_override
        }


class CircuitBreakerService:
    """
    Manages circuit breakers for trading risk control.
    
    Default circuit breakers:
    1. Daily loss limit: -$500 or -2% of account
    2. Consecutive losses: 3 in a row
    3. Trade frequency: Max 10 trades per hour
    4. Drawdown: -5% from daily high
    5. Tilt detection: Based on learning loop tilt state
    """
    
    # Default configurations
    DEFAULT_CONFIGS = {
        CircuitBreakerType.DAILY_LOSS_DOLLAR: CircuitBreakerConfig(
            type=CircuitBreakerType.DAILY_LOSS_DOLLAR,
            enabled=True,
            threshold=-500.0,
            action=CircuitBreakerAction.BLOCK_ALL,
            cooldown_minutes=0  # Resets at midnight
        ),
        CircuitBreakerType.DAILY_LOSS_PERCENT: CircuitBreakerConfig(
            type=CircuitBreakerType.DAILY_LOSS_PERCENT,
            enabled=True,
            threshold=-2.0,
            action=CircuitBreakerAction.BLOCK_ALL,
            cooldown_minutes=0
        ),
        CircuitBreakerType.CONSECUTIVE_LOSSES: CircuitBreakerConfig(
            type=CircuitBreakerType.CONSECUTIVE_LOSSES,
            enabled=True,
            threshold=3,
            action=CircuitBreakerAction.REDUCE_SIZE,
            size_reduction_pct=50.0,
            cooldown_minutes=60
        ),
        CircuitBreakerType.TRADE_FREQUENCY: CircuitBreakerConfig(
            type=CircuitBreakerType.TRADE_FREQUENCY,
            enabled=True,
            threshold=10,  # trades per hour
            action=CircuitBreakerAction.REQUIRE_OVERRIDE,
            cooldown_minutes=30
        ),
        CircuitBreakerType.DRAWDOWN: CircuitBreakerConfig(
            type=CircuitBreakerType.DRAWDOWN,
            enabled=True,
            threshold=-5.0,  # % from daily high
            action=CircuitBreakerAction.BLOCK_ALL,
            cooldown_minutes=0
        ),
        CircuitBreakerType.TILT_DETECTION: CircuitBreakerConfig(
            type=CircuitBreakerType.TILT_DETECTION,
            enabled=True,
            threshold=1,  # Any tilt detected
            action=CircuitBreakerAction.REDUCE_SIZE,
            size_reduction_pct=50.0,
            cooldown_minutes=30
        ),
        CircuitBreakerType.TIME_RESTRICTION: CircuitBreakerConfig(
            type=CircuitBreakerType.TIME_RESTRICTION,
            enabled=True,
            threshold=0,
            action=CircuitBreakerAction.WARN_ONLY,
            cooldown_minutes=0
        )
    }
    
    def __init__(self):
        self._configs: Dict[CircuitBreakerType, CircuitBreakerConfig] = dict(self.DEFAULT_CONFIGS)
        self._states: Dict[CircuitBreakerType, CircuitBreakerState] = {}
        self._learning_loop = None
        self._db = None
        
        # Trading session tracking
        self._daily_pnl: float = 0.0
        self._daily_high_pnl: float = 0.0
        self._consecutive_losses: int = 0
        self._trades_this_hour: int = 0
        self._last_hour_reset: datetime = datetime.now(timezone.utc)
        self._trade_times: List[datetime] = []
        
        # Initialize states
        for cb_type in CircuitBreakerType:
            self._states[cb_type] = CircuitBreakerState(type=cb_type)
            
    def set_services(self, learning_loop=None, db=None):
        """Wire up dependencies"""
        self._learning_loop = learning_loop
        self._db = db
        
    def configure(self, cb_type: CircuitBreakerType, config: Dict[str, Any]):
        """Update configuration for a circuit breaker"""
        if cb_type in self._configs:
            current = self._configs[cb_type]
            current.enabled = config.get("enabled", current.enabled)
            current.threshold = config.get("threshold", current.threshold)
            current.action = CircuitBreakerAction(config.get("action", current.action.value))
            current.size_reduction_pct = config.get("size_reduction_pct", current.size_reduction_pct)
            current.cooldown_minutes = config.get("cooldown_minutes", current.cooldown_minutes)
            
            logger.info(f"Circuit breaker {cb_type.value} configured: {current.to_dict()}")
            
    def get_configs(self) -> Dict[str, Dict]:
        """Get all circuit breaker configurations"""
        return {k.value: v.to_dict() for k, v in self._configs.items()}
        
    def record_trade_result(self, pnl: float, is_win: bool):
        """Record a trade result for circuit breaker tracking"""
        now = datetime.now(timezone.utc)
        
        # Update daily PnL
        self._daily_pnl += pnl
        if self._daily_pnl > self._daily_high_pnl:
            self._daily_high_pnl = self._daily_pnl
            
        # Update consecutive losses
        if is_win:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            
        # Track trade frequency
        self._trade_times.append(now)
        # Remove trades older than 1 hour
        hour_ago = now - timedelta(hours=1)
        self._trade_times = [t for t in self._trade_times if t > hour_ago]
        self._trades_this_hour = len(self._trade_times)
        
        # Check all circuit breakers
        self._check_all_breakers()
        
    def _check_all_breakers(self):
        """Check all circuit breakers and update states"""
        account_value = 100000.0  # TODO: Get from account service
        
        # 1. Daily Loss (Dollar)
        config = self._configs[CircuitBreakerType.DAILY_LOSS_DOLLAR]
        state = self._states[CircuitBreakerType.DAILY_LOSS_DOLLAR]
        state.current_value = self._daily_pnl
        state.threshold = config.threshold
        state.action = config.action
        
        if config.enabled and self._daily_pnl <= config.threshold:
            if not state.is_triggered:
                state.is_triggered = True
                state.triggered_at = datetime.now(timezone.utc).isoformat()
                state.message = f"Daily loss limit reached: ${self._daily_pnl:.2f}"
                logger.warning(state.message)
                
        # 2. Daily Loss (Percent)
        config = self._configs[CircuitBreakerType.DAILY_LOSS_PERCENT]
        state = self._states[CircuitBreakerType.DAILY_LOSS_PERCENT]
        daily_pct = (self._daily_pnl / account_value) * 100 if account_value > 0 else 0
        state.current_value = daily_pct
        state.threshold = config.threshold
        state.action = config.action
        
        if config.enabled and daily_pct <= config.threshold:
            if not state.is_triggered:
                state.is_triggered = True
                state.triggered_at = datetime.now(timezone.utc).isoformat()
                state.message = f"Daily loss % limit reached: {daily_pct:.2f}%"
                logger.warning(state.message)
                
        # 3. Consecutive Losses
        config = self._configs[CircuitBreakerType.CONSECUTIVE_LOSSES]
        state = self._states[CircuitBreakerType.CONSECUTIVE_LOSSES]
        state.current_value = self._consecutive_losses
        state.threshold = config.threshold
        state.action = config.action
        
        if config.enabled and self._consecutive_losses >= config.threshold:
            if not state.is_triggered:
                state.is_triggered = True
                state.triggered_at = datetime.now(timezone.utc).isoformat()
                state.message = f"Consecutive loss limit: {self._consecutive_losses} losses"
                logger.warning(state.message)
        elif self._consecutive_losses < config.threshold:
            state.is_triggered = False
            state.override_by = None
            
        # 4. Trade Frequency
        config = self._configs[CircuitBreakerType.TRADE_FREQUENCY]
        state = self._states[CircuitBreakerType.TRADE_FREQUENCY]
        state.current_value = self._trades_this_hour
        state.threshold = config.threshold
        state.action = config.action
        
        if config.enabled and self._trades_this_hour >= config.threshold:
            if not state.is_triggered:
                state.is_triggered = True
                state.triggered_at = datetime.now(timezone.utc).isoformat()
                state.message = f"Trade frequency limit: {self._trades_this_hour} trades this hour"
                logger.warning(state.message)
        elif self._trades_this_hour < config.threshold:
            state.is_triggered = False
            state.override_by = None
            
        # 5. Drawdown
        config = self._configs[CircuitBreakerType.DRAWDOWN]
        state = self._states[CircuitBreakerType.DRAWDOWN]
        drawdown_pct = ((self._daily_pnl - self._daily_high_pnl) / account_value) * 100 if account_value > 0 else 0
        state.current_value = drawdown_pct
        state.threshold = config.threshold
        state.action = config.action
        
        if config.enabled and drawdown_pct <= config.threshold:
            if not state.is_triggered:
                state.is_triggered = True
                state.triggered_at = datetime.now(timezone.utc).isoformat()
                state.message = f"Drawdown limit: {drawdown_pct:.2f}% from daily high"
                logger.warning(state.message)
                
    async def _check_tilt_breaker(self):
        """Check tilt detection from learning loop"""
        config = self._configs[CircuitBreakerType.TILT_DETECTION]
        state = self._states[CircuitBreakerType.TILT_DETECTION]
        
        if not config.enabled:
            return
            
        is_tilted = False
        tilt_severity = "none"
        
        if self._learning_loop:
            try:
                is_tilted = self._learning_loop.is_tilted()
                tilt_severity = self._learning_loop.get_tilt_severity()
            except Exception as e:
                logger.debug(f"Could not check tilt state: {e}")
                
        state.current_value = 1 if is_tilted else 0
        state.threshold = config.threshold
        state.action = config.action
        
        if is_tilted:
            if not state.is_triggered:
                state.is_triggered = True
                state.triggered_at = datetime.now(timezone.utc).isoformat()
                state.message = f"Tilt detected: {tilt_severity} severity"
                logger.warning(state.message)
        else:
            state.is_triggered = False
            state.override_by = None
            
    def _check_time_restriction(self) -> Optional[str]:
        """Check for time-based trading restrictions"""
        config = self._configs[CircuitBreakerType.TIME_RESTRICTION]
        state = self._states[CircuitBreakerType.TIME_RESTRICTION]
        
        if not config.enabled:
            return None
            
        now = datetime.now(ZoneInfo("America/New_York"))  # ET
        hour = now.hour
        minute = now.minute
        time_minutes = hour * 60 + minute
        
        warning = None
        
        # Lunch hour warning (11:30 AM - 1:30 PM ET)
        if 11 * 60 + 30 <= time_minutes <= 13 * 60 + 30:
            warning = "Lunch hour - reduced liquidity and choppy action"
            
        # Last 15 minutes warning
        elif time_minutes >= 15 * 60 + 45:
            warning = "Last 15 minutes - increased volatility"
            
        # After hours
        elif time_minutes >= 16 * 60:
            warning = "After hours - reduced liquidity"
            
        # Pre-market
        elif time_minutes < 9 * 60 + 30:
            warning = "Pre-market - reduced liquidity"
            
        if warning:
            state.is_triggered = True
            state.message = warning
        else:
            state.is_triggered = False
            
        return warning
        
    async def check_trading_permission(
        self,
        symbol: str = "",
        setup_type: str = "",
        tqs_score: float = 50.0
    ) -> TradingPermission:
        """
        Check if trading is currently allowed and get any restrictions.
        
        Returns TradingPermission with:
        - allowed: bool
        - max_size_multiplier: float (1.0 = full, 0.5 = half, etc.)
        - triggered_breakers: list of active circuit breakers
        - warnings: list of warning messages
        - requires_override: bool
        """
        permission = TradingPermission()
        
        # Check tilt state
        await self._check_tilt_breaker()
        
        # Check time restrictions
        time_warning = self._check_time_restriction()
        if time_warning:
            permission.warnings.append(time_warning)
            
        # Check all circuit breakers
        for cb_type, state in self._states.items():
            config = self._configs.get(cb_type)
            
            if not config or not config.enabled:
                continue
                
            if state.is_triggered and state.override_by is None:
                permission.triggered_breakers.append(state)
                
                if config.action == CircuitBreakerAction.BLOCK_ALL:
                    permission.allowed = False
                    
                elif config.action == CircuitBreakerAction.REDUCE_SIZE:
                    # Reduce size by configured percentage
                    reduction = config.size_reduction_pct / 100.0
                    permission.max_size_multiplier = min(
                        permission.max_size_multiplier,
                        1.0 - reduction
                    )
                    
                elif config.action == CircuitBreakerAction.REQUIRE_OVERRIDE:
                    permission.requires_override = True
                    
                elif config.action == CircuitBreakerAction.WARN_ONLY:
                    permission.warnings.append(state.message)
                    
        # Low TQS score warning
        if tqs_score < 50:
            permission.warnings.append(f"Low TQS score ({tqs_score:.1f}) - consider passing")
        if tqs_score < 35:
            permission.max_size_multiplier = min(permission.max_size_multiplier, 0.5)
            permission.warnings.append("Very low TQS - position size capped at 50%")
            
        return permission
        
    def override_breaker(self, cb_type: CircuitBreakerType, override_by: str = "manual"):
        """Override a triggered circuit breaker"""
        state = self._states.get(cb_type)
        if state and state.is_triggered:
            state.override_by = override_by
            logger.info(f"Circuit breaker {cb_type.value} overridden by {override_by}")
            
    def reset_breaker(self, cb_type: CircuitBreakerType):
        """Manually reset a circuit breaker"""
        state = self._states.get(cb_type)
        if state:
            state.is_triggered = False
            state.triggered_at = None
            state.override_by = None
            logger.info(f"Circuit breaker {cb_type.value} reset")
            
    def reset_daily(self):
        """Reset daily tracking (call at market open)"""
        self._daily_pnl = 0.0
        self._daily_high_pnl = 0.0
        self._consecutive_losses = 0
        
        # Reset daily breakers
        for cb_type in [
            CircuitBreakerType.DAILY_LOSS_DOLLAR,
            CircuitBreakerType.DAILY_LOSS_PERCENT,
            CircuitBreakerType.DRAWDOWN
        ]:
            self.reset_breaker(cb_type)
            
        logger.info("Circuit breakers: Daily counters reset")
        
    def get_status(self) -> Dict[str, Any]:
        """Get current status of all circuit breakers"""
        return {
            "breakers": {k.value: v.to_dict() for k, v in self._states.items()},
            "trading_metrics": {
                "daily_pnl": round(self._daily_pnl, 2),
                "daily_high_pnl": round(self._daily_high_pnl, 2),
                "consecutive_losses": self._consecutive_losses,
                "trades_this_hour": self._trades_this_hour
            },
            "any_triggered": any(s.is_triggered and s.override_by is None for s in self._states.values())
        }


# Singleton
_circuit_breaker_service: Optional[CircuitBreakerService] = None


def get_circuit_breaker_service() -> CircuitBreakerService:
    global _circuit_breaker_service
    if _circuit_breaker_service is None:
        _circuit_breaker_service = CircuitBreakerService()
    return _circuit_breaker_service


def init_circuit_breaker_service(learning_loop=None, db=None) -> CircuitBreakerService:
    service = get_circuit_breaker_service()
    service.set_services(learning_loop=learning_loop, db=db)
    return service
