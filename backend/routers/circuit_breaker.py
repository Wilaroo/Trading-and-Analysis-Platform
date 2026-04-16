"""
Circuit Breaker API Router
Endpoints for monitoring and controlling trading circuit breakers
"""
from fastapi import APIRouter
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/circuit-breaker", tags=["circuit-breaker"])

# Circuit breaker state (in-memory for now)
_circuit_breaker_state = {
    "enabled": True,
    "triggered": False,
    "trigger_reason": None,
    "triggered_at": None,
    "daily_loss_limit": 0.01,  # 1% of account
    "max_drawdown_limit": 0.05,  # 5% max drawdown
    "max_consecutive_losses": 3,
    "current_consecutive_losses": 0,
    "current_daily_loss_pct": 0.0,
    "current_drawdown_pct": 0.0,
    "trades_blocked": 0,
    "last_check": None
}


def init_circuit_breaker_router(trading_bot=None):
    """Initialize circuit breaker with trading bot reference"""
    global _trading_bot
    _trading_bot = trading_bot
    logger.info("Circuit breaker router initialized")


@router.get("/status")
def get_circuit_breaker_status():
    """
    Get the current status of trading circuit breakers.
    
    Circuit breakers protect against:
    - Daily loss limits (default 1% of account)
    - Maximum drawdown (default 5%)
    - Consecutive losing trades (default 3)
    """
    try:
        # Update state from trading bot if available
        if '_trading_bot' in globals() and _trading_bot:
            daily_stats = _trading_bot._daily_stats
            risk_params = _trading_bot.risk_params
            
            # Calculate current loss percentage
            if risk_params.starting_capital > 0:
                current_loss_pct = abs(min(0, daily_stats.net_pnl)) / risk_params.starting_capital
            else:
                current_loss_pct = 0
            
            _circuit_breaker_state.update({
                "current_daily_loss_pct": round(current_loss_pct * 100, 2),
                "daily_loss_limit": risk_params.max_daily_loss_pct,
                "triggered": daily_stats.daily_limit_hit,
                "current_consecutive_losses": daily_stats.trades_lost,  # Using trades_lost instead of losing_trades
                "last_check": datetime.now(timezone.utc).isoformat()
            })
            
            if daily_stats.daily_limit_hit:
                _circuit_breaker_state["trigger_reason"] = f"Daily loss limit hit: {daily_stats.net_pnl:.2f}"
                _circuit_breaker_state["triggered_at"] = datetime.now(timezone.utc).isoformat()
        
        return {
            "success": True,
            **_circuit_breaker_state,
            "limits": {
                "daily_loss_pct": _circuit_breaker_state["daily_loss_limit"],
                "max_drawdown_pct": _circuit_breaker_state["max_drawdown_limit"],
                "max_consecutive_losses": _circuit_breaker_state["max_consecutive_losses"]
            },
            "current": {
                "daily_loss_pct": _circuit_breaker_state["current_daily_loss_pct"],
                "drawdown_pct": _circuit_breaker_state["current_drawdown_pct"],
                "consecutive_losses": _circuit_breaker_state["current_consecutive_losses"]
            }
        }
    except Exception as e:
        logger.error(f"Error getting circuit breaker status: {e}")
        return {
            "success": False,
            "error": str(e),
            "enabled": True,
            "triggered": False
        }


@router.post("/reset")
def reset_circuit_breaker():
    """Reset the circuit breaker after it has been triggered"""
    _circuit_breaker_state.update({
        "triggered": False,
        "trigger_reason": None,
        "triggered_at": None,
        "current_consecutive_losses": 0,
        "trades_blocked": 0
    })
    
    # Also reset trading bot daily limit if available
    if '_trading_bot' in globals() and _trading_bot:
        _trading_bot._daily_stats.daily_limit_hit = False
    
    return {
        "success": True,
        "message": "Circuit breaker reset successfully",
        "state": _circuit_breaker_state
    }


@router.post("/configure")
def configure_circuit_breaker(
    daily_loss_limit: float = None,
    max_drawdown_limit: float = None,
    max_consecutive_losses: int = None
):
    """Configure circuit breaker limits"""
    if daily_loss_limit is not None:
        _circuit_breaker_state["daily_loss_limit"] = daily_loss_limit
    if max_drawdown_limit is not None:
        _circuit_breaker_state["max_drawdown_limit"] = max_drawdown_limit
    if max_consecutive_losses is not None:
        _circuit_breaker_state["max_consecutive_losses"] = max_consecutive_losses
    
    return {
        "success": True,
        "message": "Circuit breaker configured",
        "limits": {
            "daily_loss_pct": _circuit_breaker_state["daily_loss_limit"],
            "max_drawdown_pct": _circuit_breaker_state["max_drawdown_limit"],
            "max_consecutive_losses": _circuit_breaker_state["max_consecutive_losses"]
        }
    }
