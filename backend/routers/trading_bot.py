"""
Trading Bot API Router
Endpoints for controlling the autonomous trading bot,
managing trades, and viewing trade explanations.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading-bot", tags=["trading-bot"])

# Service references (set during init)
_trading_bot = None
_trade_executor = None


class RiskParamsUpdate(BaseModel):
    max_risk_per_trade: Optional[float] = None
    max_daily_loss: Optional[float] = None
    starting_capital: Optional[float] = None
    max_position_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    min_risk_reward: Optional[float] = None


class BotConfigUpdate(BaseModel):
    mode: Optional[str] = None  # "autonomous", "confirmation", "paused"
    enabled_setups: Optional[List[str]] = None
    scan_interval: Optional[int] = None
    watchlist: Optional[List[str]] = None


class TradeAction(BaseModel):
    action: str  # "confirm", "reject", "close"
    reason: Optional[str] = None


class DemoTradeRequest(BaseModel):
    symbol: str = "NVDA"
    direction: str = "long"
    setup_type: str = "rubber_band"


class TradeSubmitRequest(BaseModel):
    symbol: str
    direction: str = "long"
    setup_type: str = "breakout"
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_prices: Optional[List[float]] = None
    half_size: bool = False
    source: str = "manual"


class StrategyConfigUpdate(BaseModel):
    trail_pct: Optional[float] = None
    close_at_eod: Optional[bool] = None
    scale_out_pcts: Optional[List[float]] = None
    timeframe: Optional[str] = None


def init_trading_bot_router(trading_bot, trade_executor):
    """Initialize router with service dependencies"""
    global _trading_bot, _trade_executor
    _trading_bot = trading_bot
    _trade_executor = trade_executor
    logger.info("Trading bot router initialized")


# ==================== BOT CONTROL ====================

@router.get("/status")
async def get_bot_status():
    """Get trading bot status and statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    status = _trading_bot.get_status()
    
    # Add account info if available
    if _trade_executor:
        account = await _trade_executor.get_account_info()
        status["account"] = account
    
    return {"success": True, **status}


@router.post("/start")
async def start_bot():
    """Start the trading bot"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotMode
    from services.enhanced_scanner import get_enhanced_scanner
    
    await _trading_bot.start()
    
    # Sync scanner auto-execute with bot mode on start
    bot_mode = _trading_bot.get_mode()
    scanner = get_enhanced_scanner()
    if scanner:
        if bot_mode == BotMode.AUTONOMOUS:
            scanner.enable_auto_execute(True, min_win_rate=0.55, min_priority="high")
        else:
            scanner.enable_auto_execute(False)
    
    return {"success": True, "message": "Trading bot started", "mode": bot_mode.value, "scanner_auto_execute": bot_mode == BotMode.AUTONOMOUS}


@router.post("/stop")
async def stop_bot():
    """Stop the trading bot"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    await _trading_bot.stop()
    return {"success": True, "message": "Trading bot stopped"}


@router.get("/executor/status")
async def get_executor_status():
    """Get trade executor status and current broker"""
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    return {
        "success": True,
        "mode": _trade_executor.get_mode().value,
        "broker": "alpaca" if _trade_executor.get_mode().value == "paper" else "interactive_brokers" if _trade_executor.get_mode().value == "live" else "simulated",
        "description": {
            "paper": "Orders routed to Alpaca paper trading",
            "live": "Orders routed to Interactive Brokers",
            "simulated": "No actual orders placed (simulation only)"
        }.get(_trade_executor.get_mode().value, "Unknown")
    }


@router.post("/executor/mode/{mode}")
async def set_executor_mode(mode: str):
    """
    Set trade execution mode/broker.
    
    Modes:
    - paper: Route orders to Alpaca paper trading
    - live: Route orders to Interactive Brokers (requires IB Gateway)
    - simulated: No actual orders, just simulate fills
    """
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    from services.trade_executor_service import ExecutorMode
    
    mode_lower = mode.lower()
    if mode_lower not in ["paper", "live", "simulated"]:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Use 'paper', 'live', or 'simulated'")
    
    try:
        executor_mode = ExecutorMode(mode_lower)
        _trade_executor.set_mode(executor_mode)
        
        return {
            "success": True,
            "mode": mode_lower,
            "broker": "alpaca" if mode_lower == "paper" else "interactive_brokers" if mode_lower == "live" else "simulated",
            "message": f"Trade execution now using {mode_lower} mode"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mode/{mode}")
async def set_bot_mode(mode: str):
    """Set bot operating mode (autonomous, confirmation, paused)"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotMode
    from services.enhanced_scanner import get_enhanced_scanner
    
    try:
        bot_mode = BotMode(mode.lower())
        _trading_bot.set_mode(bot_mode)
        
        # Sync scanner auto-execute with bot mode
        scanner = get_enhanced_scanner()
        if scanner:
            if bot_mode == BotMode.AUTONOMOUS:
                # Enable scanner auto-execute when bot is autonomous
                scanner.enable_auto_execute(True, min_win_rate=0.55, min_priority="high")
            else:
                # Disable scanner auto-execute for other modes
                scanner.enable_auto_execute(False)
        
        return {"success": True, "mode": bot_mode.value, "scanner_auto_execute": bot_mode == BotMode.AUTONOMOUS}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}. Use 'autonomous', 'confirmation', or 'paused'")


@router.post("/config")
async def update_bot_config(config: BotConfigUpdate):
    """Update bot configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotMode
    from services.enhanced_scanner import get_enhanced_scanner
    
    if config.mode:
        try:
            bot_mode = BotMode(config.mode.lower())
            _trading_bot.set_mode(bot_mode)
            
            # Sync scanner auto-execute with bot mode
            scanner = get_enhanced_scanner()
            if scanner:
                if bot_mode == BotMode.AUTONOMOUS:
                    scanner.enable_auto_execute(True, min_win_rate=0.55, min_priority="high")
                else:
                    scanner.enable_auto_execute(False)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {config.mode}")
    
    if config.enabled_setups:
        _trading_bot.set_enabled_setups(config.enabled_setups)
    
    if config.scan_interval:
        _trading_bot._scan_interval = config.scan_interval
    
    if config.watchlist:
        _trading_bot.set_watchlist(config.watchlist)
    
    return {"success": True, "message": "Configuration updated"}


@router.post("/risk-params")
async def update_risk_params(params: RiskParamsUpdate):
    """Update risk management parameters"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    updates = params.dict(exclude_none=True)
    _trading_bot.update_risk_params(**updates)
    
    return {"success": True, "risk_params": _trading_bot.get_status()["risk_params"]}


# ==================== TRADE MANAGEMENT ====================

@router.get("/trades/pending")
async def get_pending_trades():
    """Get all trades awaiting confirmation"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_pending_trades()
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/open")
async def get_open_trades():
    """Get all open positions"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_open_trades()
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/closed")
async def get_closed_trades(limit: int = Query(50, ge=1, le=500)):
    """Get closed trades history"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_closed_trades(limit=limit)
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/all")
async def get_all_trades():
    """Get all bot trades (pending, open, closed) for the AI Command Panel"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    summary = _trading_bot.get_all_trades_summary()
    return {"success": True, **summary}



@router.get("/trades")
async def get_trades_list():
    """
    Get a unified list of all trades (pending, open, closed).
    This is an alias endpoint for /trades/all for API consistency.
    """
    if not _trading_bot:
        return {
            "success": True,
            "pending": [],
            "open": [],
            "closed": [],
            "total": 0,
            "message": "Trading bot not initialized"
        }
    
    try:
        summary = _trading_bot.get_all_trades_summary()
        return {
            "success": True,
            "pending": summary.get("pending_trades", []),
            "open": summary.get("open_trades", []),
            "closed": summary.get("closed_trades", []),
            "total": summary.get("total_trades", 0),
            "daily_stats": summary.get("daily_stats", {})
        }
    except Exception as e:
        logger.error(f"Error getting trades: {e}")
        return {
            "success": False,
            "error": str(e),
            "pending": [],
            "open": [],
            "closed": []
        }



@router.post("/evaluate-trade")
async def ai_evaluate_trade(request: DemoTradeRequest):
    """Ask AI to evaluate a trade opportunity"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    if not hasattr(_trading_bot, '_ai_assistant') or not _trading_bot._ai_assistant:
        raise HTTPException(status_code=503, detail="AI assistant not connected to bot")
    
    trade_data = {
        "symbol": request.symbol.upper(),
        "direction": request.direction,
        "setup_type": request.setup_type,
        "timeframe": "intraday",
        "entry_price": 0,
        "stop_price": 0,
        "target_prices": [],
        "risk_amount": 0,
        "risk_reward_ratio": 0,
        "quality_score": 0,
        "quality_grade": "N/A"
    }
    
    result = await _trading_bot._ai_assistant.evaluate_bot_opportunity(trade_data)
    return result


@router.post("/trades/submit")
async def submit_trade(request: TradeSubmitRequest):
    """Submit a new trade for execution"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        symbol = request.symbol.upper()
        
        # Calculate position size based on risk params
        risk_params = _trading_bot.risk_params
        
        # Get current price if not provided
        entry_price = request.entry_price
        if not entry_price:
            # Try to get from Alpaca
            try:
                from services.alpaca_service import get_alpaca_service
                alpaca = get_alpaca_service()
                quote = alpaca.get_latest_quote(symbol)
                entry_price = float(quote.get('price', 0)) if quote else 0
            except Exception:
                entry_price = 0
        
        # Calculate shares based on risk
        stop_price = request.stop_price or (entry_price * 0.98 if request.direction == 'long' else entry_price * 1.02)
        risk_per_share = abs(entry_price - stop_price) if entry_price and stop_price else entry_price * 0.02
        
        if risk_per_share > 0:
            max_shares = int(risk_params.max_risk_per_trade / risk_per_share)
        else:
            max_shares = 100
        
        # Apply half size if requested
        if request.half_size:
            max_shares = max(1, max_shares // 2)
        
        # Create trade record
        trade_id = f"trade_{uuid.uuid4().hex[:8]}"
        trade = {
            "id": trade_id,
            "symbol": symbol,
            "direction": request.direction,
            "setup_type": request.setup_type,
            "status": "pending",
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_prices": request.target_prices or [entry_price * 1.03] if request.direction == 'long' else [entry_price * 0.97],
            "shares": max_shares,
            "risk_amount": risk_per_share * max_shares if risk_per_share else 0,
            "source": request.source,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "half_size": request.half_size
        }
        
        # Add to pending trades (it's a Dict keyed by trade_id)
        if not hasattr(_trading_bot, '_pending_trades') or _trading_bot._pending_trades is None:
            _trading_bot._pending_trades = {}
        
        # Create a BotTrade object if possible, otherwise use dict
        try:
            from services.trading_bot_service import BotTrade
            bot_trade = BotTrade(
                id=trade_id,
                symbol=symbol,
                direction=request.direction,
                setup_type=request.setup_type,
                entry_price=entry_price,
                stop_price=stop_price,
                target_prices=request.target_prices or ([entry_price * 1.03] if request.direction == 'long' else [entry_price * 0.97]),
                shares=max_shares,
                status="pending"
            )
            _trading_bot._pending_trades[trade_id] = bot_trade
        except Exception as e:
            logger.warning(f"Could not create BotTrade object: {e}")
            # Store as dict in a separate structure if needed
        
        # If in autonomous mode, execute immediately
        if _trading_bot._mode.value == "autonomous":
            # Execute the trade
            try:
                if _trade_executor:
                    result = await _trade_executor.execute_trade(trade)
                    trade["status"] = "open" if result.get("success") else "failed"
                    trade["execution_result"] = result
            except Exception as e:
                logger.error(f"Trade execution error: {e}")
                trade["status"] = "pending"
        
        logger.info(f"✅ Trade submitted: {symbol} {request.direction} - {max_shares} shares @ ${entry_price:.2f}")
        
        return {
            "success": True,
            "trade_id": trade_id,
            "trade": trade,
            "message": f"Trade submitted: {symbol} {request.direction.upper()} {max_shares} shares"
        }
        
    except Exception as e:
        logger.error(f"Failed to submit trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: str):
    """Get details of a specific trade including explanation"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trade = _trading_bot.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    return {"success": True, "trade": trade}


@router.post("/trades/{trade_id}/confirm")
async def confirm_trade(trade_id: str):
    """Confirm a pending trade for execution"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    success = await _trading_bot.confirm_trade(trade_id)
    
    if success:
        trade = _trading_bot.get_trade(trade_id)
        return {"success": True, "message": "Trade executed", "trade": trade}
    else:
        raise HTTPException(status_code=400, detail="Failed to execute trade or trade not found")


@router.post("/trades/{trade_id}/reject")
async def reject_trade(trade_id: str, reason: Optional[str] = None):
    """Reject a pending trade"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    success = await _trading_bot.reject_trade(trade_id)
    
    if success:
        return {"success": True, "message": "Trade rejected"}
    else:
        raise HTTPException(status_code=404, detail="Trade not found")


@router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: str, reason: Optional[str] = "manual"):
    """Close an open trade"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    success = await _trading_bot.close_trade(trade_id, reason=reason)
    
    if success:
        trade = _trading_bot.get_trade(trade_id)
        return {"success": True, "message": "Trade closed", "trade": trade}
    else:
        raise HTTPException(status_code=400, detail="Failed to close trade or trade not found")


# ==================== STATISTICS ====================

@router.get("/stats/daily")
async def get_daily_stats():
    """Get daily trading statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    stats = _trading_bot.get_daily_stats()
    return {"success": True, "stats": stats}


@router.get("/stats/performance")
async def get_performance_stats():
    """Get overall performance statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    # Get all closed trades
    closed = _trading_bot.get_closed_trades(limit=500)
    
    total_pnl = sum(t.get('realized_pnl', 0) for t in closed)
    winners = [t for t in closed if t.get('realized_pnl', 0) > 0]
    losers = [t for t in closed if t.get('realized_pnl', 0) < 0]
    
    return {
        "success": True,
        "stats": {
            "total_trades": len(closed),
            "total_pnl": total_pnl,
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": (len(winners) / len(closed) * 100) if closed else 0,
            "avg_win": sum(t.get('realized_pnl', 0) for t in winners) / len(winners) if winners else 0,
            "avg_loss": sum(t.get('realized_pnl', 0) for t in losers) / len(losers) if losers else 0,
            "largest_win": max((t.get('realized_pnl', 0) for t in winners), default=0),
            "largest_loss": min((t.get('realized_pnl', 0) for t in losers), default=0),
            "profit_factor": abs(sum(t.get('realized_pnl', 0) for t in winners) / sum(t.get('realized_pnl', 0) for t in losers)) if losers else 0
        }
    }


@router.get("/performance/equity-curve")
async def get_equity_curve(period: str = Query("today", enum=["today", "week", "month", "ytd", "all"])):
    """
    Get equity curve data for the bot performance chart.
    Returns cumulative P&L over time with trade markers.
    
    Period options:
    - today: Intraday (last 24 hours)
    - week: Last 7 days
    - month: Last 30 days
    - ytd: Year to date
    - all: All time
    """
    if not _trading_bot:
        return {
            "success": True,
            "equity_curve": [],
            "trade_markers": [],
            "summary": {
                "total_pnl": 0,
                "trades_count": 0,
                "win_rate": 0,
                "avg_r": 0,
                "best_trade": 0,
                "worst_trade": 0
            }
        }
    
    try:
        from datetime import timedelta
        
        # Get closed trades
        closed = _trading_bot.get_closed_trades(limit=1000)
        
        # Filter by period
        now = datetime.now(timezone.utc)
        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            cutoff = now - timedelta(days=7)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        elif period == "ytd":
            cutoff = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # all
            cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        
        # Filter and sort trades by close time
        filtered_trades = []
        for trade in closed:
            close_time_str = trade.get('closed_at') or trade.get('executed_at')
            if close_time_str:
                try:
                    close_time = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
                    if close_time >= cutoff:
                        filtered_trades.append({
                            **trade,
                            '_close_time': close_time
                        })
                except (ValueError, TypeError):
                    pass
        
        # Sort by close time
        filtered_trades.sort(key=lambda t: t['_close_time'])
        
        # Build equity curve
        cumulative_pnl = 0
        equity_curve = []
        trade_markers = []
        pnls = []
        
        for trade in filtered_trades:
            pnl = trade.get('realized_pnl', 0)
            cumulative_pnl += pnl
            pnls.append(pnl)
            
            timestamp = int(trade['_close_time'].timestamp() * 1000)  # JS timestamp
            equity_curve.append({
                "time": timestamp,
                "value": cumulative_pnl
            })
            
            trade_markers.append({
                "time": timestamp,
                "pnl": pnl,
                "symbol": trade.get('symbol', ''),
                "setup_type": trade.get('setup_type', ''),
                "is_win": pnl > 0
            })
        
        # Calculate summary stats
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        # Calculate average R-multiple from trades that have it
        r_multiples = [t.get('r_multiple', 0) for t in filtered_trades if t.get('r_multiple')]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        
        summary = {
            "total_pnl": cumulative_pnl,
            "trades_count": len(filtered_trades),
            "win_rate": (len(wins) / len(filtered_trades) * 100) if filtered_trades else 0,
            "avg_r": avg_r,
            "best_trade": max(pnls, default=0),
            "worst_trade": min(pnls, default=0)
        }
        
        return {
            "success": True,
            "period": period,
            "equity_curve": equity_curve,
            "trade_markers": trade_markers,
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"Error getting equity curve: {e}")
        return {
            "success": False,
            "error": str(e),
            "equity_curve": [],
            "trade_markers": [],
            "summary": {}
        }


@router.get("/thoughts")
async def get_bot_thoughts(limit: int = Query(10, ge=1, le=50)):
    """
    Get the bot's recent thoughts/reasoning in first person.
    Returns a stream of what the bot is "thinking" based on:
    - Recent trade decisions and reasoning
    - Setups being watched
    - Position monitoring updates
    
    Each thought has:
    - text: The thought in first person (e.g., "I detected a breakout on NVDA...")
    - timestamp: When the thought occurred
    - confidence: 0-100 confidence level
    - action_type: entry, exit, watching, monitoring, scanning, alert
    - symbol: Related ticker symbol (if any)
    """
    thoughts = []
    
    if not _trading_bot:
        return {
            "success": True,
            "thoughts": [{
                "text": "I'm currently offline. Start me to begin scanning for opportunities.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": 0,
                "action_type": "offline",
                "symbol": None
            }]
        }
    
    try:
        now = datetime.now(timezone.utc)
        
        # 1. Thoughts from pending trades (about to execute)
        for trade in _trading_bot.get_pending_trades()[:3]:
            symbol = trade.get('symbol', 'UNKNOWN')
            setup = trade.get('setup_type', 'trade')
            entry = trade.get('entry_price', 0)
            rr = trade.get('risk_reward_ratio', 0)
            
            thoughts.append({
                "text": f'"I\'m preparing to enter {symbol} on a {setup.replace("_", " ")} setup at ${entry:.2f}. Risk/Reward is {rr:.1f}:1. Awaiting confirmation."',
                "timestamp": trade.get('created_at', now.isoformat()),
                "confidence": 80,
                "action_type": "entry",
                "symbol": symbol
            })
        
        # 2. Thoughts from open trades (monitoring)
        for trade in _trading_bot.get_open_trades()[:3]:
            symbol = trade.get('symbol', 'UNKNOWN')
            pnl = trade.get('unrealized_pnl', 0)
            pnl_pct = trade.get('pnl_pct', 0)
            stop = trade.get('stop_price', 0)
            target = trade.get('target_prices', [0])[0] if trade.get('target_prices') else 0
            direction = 'up' if pnl >= 0 else 'down'
            
            thoughts.append({
                "text": f'"I\'m monitoring my {symbol} position. Currently {direction} {abs(pnl_pct):.1f}%. Stop at ${stop:.2f} is safe. {f"Target 1 at ${target:.2f}." if target else ""}"',
                "timestamp": trade.get('executed_at', now.isoformat()),
                "confidence": 60,
                "action_type": "monitoring",
                "symbol": symbol
            })
        
        # 3. Thoughts from recent closed trades (lessons learned)
        recent_closed = _trading_bot.get_closed_trades(limit=2)
        for trade in recent_closed:
            symbol = trade.get('symbol', 'UNKNOWN')
            pnl = trade.get('realized_pnl', 0)
            reason = trade.get('close_reason', 'manual')
            
            if pnl > 0:
                text = f'"I closed {symbol} for +${pnl:.2f}. {reason.replace("_", " ").title()} worked well."'
            else:
                text = f'"I closed {symbol} for -${abs(pnl):.2f}. {reason.replace("_", " ").title()}. Learning from this."'
            
            thoughts.append({
                "text": text,
                "timestamp": trade.get('closed_at', now.isoformat()),
                "confidence": 50,
                "action_type": "exit",
                "symbol": symbol
            })
        
        # 4. General status thought if bot is running
        if _trading_bot._running:
            mode = _trading_bot._mode.value
            regime = getattr(_trading_bot, '_current_regime', 'UNKNOWN')
            
            if regime == 'RISK_ON':
                regime_comment = "so I'm looking for aggressive breakout setups."
            elif regime == 'RISK_OFF':
                regime_comment = "so I'm being cautious and reducing position sizes."
            elif regime == 'CONFIRMED_DOWN':
                regime_comment = "so I'm favoring short setups and reducing long exposure."
            else:
                regime_comment = "so I'm using standard position sizing."
            
            thoughts.append({
                "text": f'"I\'m actively scanning for opportunities in {mode} mode. Market regime is {regime}, {regime_comment}"',
                "timestamp": now.isoformat(),
                "confidence": 50,
                "action_type": "scanning",
                "symbol": None
            })
        
        # Sort by timestamp (most recent first) and limit
        thoughts.sort(key=lambda t: t['timestamp'], reverse=True)
        
        return {
            "success": True,
            "thoughts": thoughts[:limit]
        }
        
    except Exception as e:
        logger.error(f"Error getting bot thoughts: {e}")
        return {
            "success": False,
            "error": str(e),
            "thoughts": []
        }


@router.get("/dashboard-data")
async def get_dashboard_data():
    """
    Get all data needed for the new bot-centric dashboard in one call.
    Reduces API calls from the frontend.
    
    Returns:
    - bot_status: Running state, mode, last action
    - today_pnl: Today's realized P&L
    - open_pnl: Unrealized P&L from open positions
    - open_trades: List of open positions
    - watching_setups: Setups the bot is watching
    - recent_thoughts: Bot's recent reasoning (3 most recent)
    - performance_summary: Win rate, avg R, etc.
    """
    if not _trading_bot:
        return {
            "success": True,
            "bot_status": {"running": False, "mode": "paused", "state": "offline"},
            "today_pnl": 0,
            "open_pnl": 0,
            "open_trades": [],
            "watching_setups": [],
            "recent_thoughts": [],
            "performance_summary": {}
        }
    
    try:
        # Bot status
        status = _trading_bot.get_status()
        daily_stats = status.get('daily_stats', {})
        
        # Calculate open P&L
        open_trades = _trading_bot.get_open_trades()
        open_pnl = sum(t.get('unrealized_pnl', 0) for t in open_trades)
        
        # Get pending trades (watching/about to enter)
        pending = _trading_bot.get_pending_trades()
        
        # Build bot status object
        bot_status = {
            "running": status.get('running', False),
            "mode": status.get('mode', 'paused'),
            "state": "hunting" if status.get('running') else "paused",
            "last_action": None  # Could be enhanced later
        }
        
        # Get thoughts (simplified - just 3 most recent)
        thoughts_response = await get_bot_thoughts(limit=3)
        recent_thoughts = thoughts_response.get('thoughts', [])
        
        # Performance summary
        closed = _trading_bot.get_closed_trades(limit=100)
        today_trades = [t for t in closed if _is_today(t.get('closed_at'))]
        
        wins = [t for t in today_trades if t.get('realized_pnl', 0) > 0]
        performance_summary = {
            "trades_today": len(today_trades),
            "win_rate": (len(wins) / len(today_trades) * 100) if today_trades else 0,
            "best_trade": max((t.get('realized_pnl', 0) for t in today_trades), default=0),
            "worst_trade": min((t.get('realized_pnl', 0) for t in today_trades), default=0)
        }
        
        return {
            "success": True,
            "bot_status": bot_status,
            "today_pnl": daily_stats.get('net_pnl', 0),
            "open_pnl": open_pnl,
            "open_trades": open_trades,
            "watching_setups": pending,
            "recent_thoughts": recent_thoughts,
            "performance_summary": performance_summary
        }
        
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def _is_today(timestamp_str: str) -> bool:
    """Helper to check if a timestamp is from today"""
    if not timestamp_str:
        return False
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        today = datetime.now(timezone.utc).date()
        return ts.date() == today
    except (ValueError, TypeError):
        return False


# ==================== REAL-TIME STREAMING ====================

@router.get("/stream")
async def stream_bot_updates():
    """
    Server-Sent Events stream for real-time bot updates.
    Streams: new trades, trade executions, P&L updates, status changes
    """
    async def event_generator():
        queue = asyncio.Queue()
        
        async def trade_callback(trade, event_type):
            await queue.put({"type": event_type, "trade": trade.to_dict()})
        
        if _trading_bot:
            _trading_bot.add_trade_callback(trade_callback)
        
        # Send initial connection message
        yield f"data: {json.dumps({'type': 'connected', 'timestamp': str(datetime.now())})}\n\n"
        
        try:
            while True:
                try:
                    # Wait for updates with timeout for heartbeat
                    update = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except asyncio.CancelledError:
            pass
    
    from datetime import datetime
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ==================== ACCOUNT INFO ====================

@router.get("/account")
async def get_account_info():
    """Get broker account information"""
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    account = await _trade_executor.get_account_info()
    positions = await _trade_executor.get_positions()
    
    return {
        "success": True,
        "account": account,
        "positions": positions
    }


@router.get("/positions")
async def get_broker_positions():
    """Get current positions from broker"""
    if not _trade_executor:
        raise HTTPException(status_code=503, detail="Trade executor not initialized")
    
    positions = await _trade_executor.get_positions()
    return {"success": True, "positions": positions}


# ==================== MANUAL CONTROLS ====================

@router.post("/scan-now")
async def trigger_manual_scan():
    """Manually trigger a scan for trade opportunities"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    await _trading_bot._scan_for_opportunities()
    
    return {
        "success": True,
        "message": "Scan completed",
        "pending_trades": len(_trading_bot.get_pending_trades()),
        "open_trades": len(_trading_bot.get_open_trades())
    }


@router.get("/strategy-configs")
async def get_strategy_configs():
    """Get all strategy configurations"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    configs = _trading_bot.get_strategy_configs()
    return {"success": True, "configs": configs}


@router.put("/strategy-configs/{strategy}")
async def update_strategy_config(strategy: str, config: StrategyConfigUpdate):
    """Update a specific strategy configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    updates = config.dict(exclude_none=True)
    success = _trading_bot.update_strategy_config(strategy, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy}' not found")
    
    return {"success": True, "message": f"Strategy '{strategy}' updated", "configs": _trading_bot.get_strategy_configs()}


@router.post("/demo-trade")
async def create_demo_trade(request: DemoTradeRequest):
    """
    Create a demo trade for testing purposes.
    This simulates finding a trade opportunity without requiring live market data.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    from services.trading_bot_service import BotTrade, TradeStatus, TradeDirection, TradeExplanation, STRATEGY_CONFIG, DEFAULT_STRATEGY_CONFIG
    import uuid
    from datetime import datetime, timezone
    
    symbol = request.symbol.upper()
    direction = TradeDirection.LONG if request.direction.lower() == "long" else TradeDirection.SHORT
    
    # Get strategy config
    strategy_cfg = STRATEGY_CONFIG.get(request.setup_type, DEFAULT_STRATEGY_CONFIG)
    from services.trading_bot_service import TradeTimeframe
    timeframe_val = strategy_cfg["timeframe"]
    timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
    trail_pct = strategy_cfg.get("trail_pct", 0.02)
    scale_pcts = strategy_cfg.get("scale_out_pcts", [0.33, 0.33, 0.34])
    close_at_eod = strategy_cfg.get("close_at_eod", True)
    
    # Get current price from Alpaca
    current_price = 100.0  # Default
    try:
        from services.alpaca_service import get_alpaca_service
        alpaca = get_alpaca_service()
        quote = await alpaca.get_quote(symbol)
        if quote and quote.get('price'):
            current_price = quote['price']
    except Exception as e:
        logger.warning(f"Could not get quote for {symbol}: {e}")
    
    # Calculate trade parameters - round to 2 decimals
    entry_price = round(current_price, 2)
    atr_estimate = round(current_price * 0.02, 2)  # Estimate 2% ATR
    
    if direction == TradeDirection.LONG:
        stop_price = round(entry_price - atr_estimate, 2)
        target_prices = [
            round(entry_price + atr_estimate * 1.5, 2),
            round(entry_price + atr_estimate * 2.5, 2),
            round(entry_price + atr_estimate * 4, 2)
        ]
    else:
        stop_price = round(entry_price + atr_estimate, 2)
        target_prices = [
            round(entry_price - atr_estimate * 1.5, 2),
            round(entry_price - atr_estimate * 2.5, 2),
            round(entry_price - atr_estimate * 4, 2)
        ]
    
    # Calculate position size
    risk_per_share = abs(entry_price - stop_price)
    max_shares = int(_trading_bot.risk_params.max_risk_per_trade / risk_per_share)
    shares = min(max_shares, int(_trading_bot.risk_params.starting_capital * 0.1 / entry_price))
    shares = max(shares, 1)
    
    risk_amount = shares * risk_per_share
    potential_reward = shares * abs(target_prices[0] - entry_price)
    risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0
    
    # Generate explanation
    explanation = TradeExplanation(
        summary=f"Demo {request.setup_type.replace('_', ' ').title()} setup on {symbol}. "
                f"{'Buying' if direction == TradeDirection.LONG else 'Shorting'} {shares} shares at ${entry_price:.2f}.",
        setup_identified=f"Demo {request.setup_type} pattern for testing",
        technical_reasons=[
            f"Setup type: {request.setup_type}",
            f"Current price: ${current_price:.2f}",
            "Demo trade for testing - not based on live analysis"
        ],
        fundamental_reasons=[],
        risk_analysis={
            "risk_per_share": f"${risk_per_share:.2f}",
            "total_risk": f"${risk_amount:.2f}",
            "max_risk_allowed": f"${_trading_bot.risk_params.max_risk_per_trade:.2f}",
            "risk_pct_of_capital": f"{(risk_amount / _trading_bot.risk_params.starting_capital * 100):.3f}%"
        },
        entry_logic=f"Demo entry at ${entry_price:.2f}",
        exit_logic=f"Stop at ${stop_price:.2f}, Target at ${target_prices[0]:.2f}",
        position_sizing_logic=f"Position: {shares} shares based on ${_trading_bot.risk_params.max_risk_per_trade:.0f} max risk",
        confidence_factors=["Demo trade for testing"],
        warnings=["This is a DEMO trade for testing purposes only"]
    )
    
    # Create trade
    trade = BotTrade(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        direction=direction,
        status=TradeStatus.PENDING,
        setup_type=request.setup_type,
        timeframe=timeframe_str,
        quality_score=75,
        quality_grade="B+",
        entry_price=entry_price,
        current_price=current_price,
        stop_price=stop_price,
        target_prices=target_prices,
        shares=shares,
        risk_amount=risk_amount,
        potential_reward=potential_reward,
        risk_reward_ratio=risk_reward_ratio,
        created_at=datetime.now(timezone.utc).isoformat(),
        estimated_duration=f"{timeframe_str.title()} - 30min-2hr",
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
    
    # Add to pending trades
    _trading_bot._pending_trades[trade.id] = trade
    
    return {
        "success": True,
        "message": f"Demo trade created for {symbol}",
        "trade": trade.to_dict()
    }


class SimulateClosedRequest(BaseModel):
    symbol: str = "AAPL"
    setup_type: str = "rubber_band"
    direction: str = "long"
    pnl: float = 150.0  # Positive = win, negative = loss
    close_reason: str = "target_hit"


@router.post("/demo/simulate-closed")
async def simulate_closed_trade(request: SimulateClosedRequest):
    """Simulate a fully closed trade for testing the learning loop"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    import random
    from services.trading_bot_service import BotTrade, TradeStatus, TradeDirection, TradeExplanation, STRATEGY_CONFIG, DEFAULT_STRATEGY_CONFIG, TradeTimeframe
    symbol = request.symbol.upper()
    direction = TradeDirection.LONG if request.direction.lower() == "long" else TradeDirection.SHORT
    strategy_cfg = STRATEGY_CONFIG.get(request.setup_type, DEFAULT_STRATEGY_CONFIG)
    timeframe_val = strategy_cfg["timeframe"]
    timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
    trail_pct = strategy_cfg.get("trail_pct", 0.02)
    
    entry_price = round(random.uniform(100, 500), 2)
    pnl = request.pnl
    shares = random.randint(50, 300)
    pnl_per_share = pnl / shares
    exit_price = round(entry_price + pnl_per_share, 2) if direction == TradeDirection.LONG else round(entry_price - pnl_per_share, 2)
    stop_price = round(entry_price - entry_price * 0.02, 2)
    
    trade = BotTrade(
        id=str(uuid.uuid4())[:8],
        symbol=symbol,
        direction=direction,
        status=TradeStatus.CLOSED,
        setup_type=request.setup_type,
        timeframe=timeframe_str,
        quality_score=random.randint(60, 90),
        quality_grade=random.choice(["A", "A-", "B+", "B", "B-"]),
        entry_price=entry_price,
        current_price=exit_price,
        stop_price=stop_price,
        target_prices=[round(entry_price * 1.03, 2), round(entry_price * 1.05, 2)],
        shares=shares,
        risk_amount=round(abs(entry_price - stop_price) * shares, 2),
        potential_reward=round(abs(pnl) * 1.5, 2),
        risk_reward_ratio=1.5,
        fill_price=entry_price,
        exit_price=exit_price,
        realized_pnl=round(pnl, 2),
        pnl_pct=round((pnl / (entry_price * shares)) * 100, 2),
        created_at=datetime.now(timezone.utc).isoformat(),
        executed_at=datetime.now(timezone.utc).isoformat(),
        closed_at=datetime.now(timezone.utc).isoformat(),
        close_reason=request.close_reason,
        close_at_eod=strategy_cfg.get("close_at_eod", True),
        estimated_duration=f"{timeframe_str} demo",
        trailing_stop_config={
            "trail_pct": trail_pct
        }
    )
    
    # Add to closed trades list
    _trading_bot._closed_trades.append(trade)
    
    # Update daily stats
    _trading_bot._daily_stats.trades_executed += 1
    _trading_bot._daily_stats.net_pnl += pnl
    _trading_bot._daily_stats.gross_pnl += pnl
    if pnl > 0:
        _trading_bot._daily_stats.trades_won += 1
    else:
        _trading_bot._daily_stats.trades_lost += 1
    total = _trading_bot._daily_stats.trades_won + _trading_bot._daily_stats.trades_lost
    _trading_bot._daily_stats.win_rate = (_trading_bot._daily_stats.trades_won / total * 100) if total > 0 else 0
    
    # Record performance for learning loop
    if hasattr(_trading_bot, '_perf_service') and _trading_bot._perf_service:
        _trading_bot._perf_service.record_trade(trade.to_dict())
    
    # Save to DB
    await _trading_bot._save_trade(trade)
    
    return {
        "success": True,
        "message": f"Simulated closed trade: {symbol} P&L=${pnl:.2f}",
        "trade": trade.to_dict()
    }



# ==================== POSITION IMPORT ====================

class ImportPositionRequest(BaseModel):
    """Request to import an existing IB position into bot management"""
    symbol: str
    shares: int
    entry_price: float
    stop_price: float
    direction: str = "long"  # "long" or "short"
    setup_type: str = "imported"
    target_prices: Optional[List[float]] = None
    notes: Optional[str] = None


@router.post("/import-position")
async def import_position(request: ImportPositionRequest):
    """
    Import an existing IB position into bot management.
    
    This allows the bot to manage stops for positions that were:
    - Opened manually in IB
    - Opened before the bot was restarted
    - Opened when the bot had connectivity issues
    
    The bot will then monitor the position and execute stop/target orders.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus
        
        # Validate direction
        direction = TradeDirection.LONG if request.direction.lower() == "long" else TradeDirection.SHORT
        
        # Calculate additional required fields
        risk_per_share = abs(request.entry_price - request.stop_price)
        risk_amount = risk_per_share * request.shares
        target_prices = request.target_prices or [request.entry_price * 1.03, request.entry_price * 1.06]
        reward_per_share = abs(target_prices[0] - request.entry_price)
        potential_reward = reward_per_share * request.shares
        risk_reward_ratio = (reward_per_share / risk_per_share) if risk_per_share > 0 else 2.0
        
        # Create trade object with ALL required fields
        trade = BotTrade(
            id=str(uuid.uuid4()),
            symbol=request.symbol.upper(),
            direction=direction,
            status=TradeStatus.OPEN,
            setup_type=request.setup_type,
            timeframe="imported",
            quality_score=70,
            quality_grade="B",
            entry_price=request.entry_price,
            current_price=request.entry_price,
            stop_price=request.stop_price,
            target_prices=target_prices,
            shares=request.shares,
            risk_amount=risk_amount,
            potential_reward=potential_reward,
            risk_reward_ratio=risk_reward_ratio
        )
        
        # Set additional fields
        trade.fill_price = request.entry_price
        trade.executed_at = datetime.now(timezone.utc).isoformat()
        trade.notes = f"[IMPORTED] Imported from IB - {request.notes or 'manual import'}"
        
        # Initialize trailing stop config
        trade.trailing_stop_config = {
            "mode": "initial",
            "current_stop": request.stop_price,
            "original_stop": request.stop_price,
            "highest_price": request.entry_price,
            "lowest_price": request.entry_price,
            "stop_adjustments": []
        }
        
        # Add to bot's open trades
        _trading_bot._open_trades[trade.id] = trade
        
        # Save to database for persistence
        await _trading_bot._save_trade(trade)
        
        logger.info(f"✅ Imported position: {trade.symbol} {trade.shares} shares {direction.value} @ ${trade.entry_price:.2f}, stop=${trade.stop_price:.2f}")
        
        return {
            "success": True,
            "message": f"Successfully imported {request.symbol} position into bot management",
            "trade": trade.to_dict(),
            "stop_monitoring": True
        }
        
    except Exception as e:
        logger.error(f"Failed to import position: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import position: {str(e)}")


@router.get("/sync-positions")
async def sync_with_ib_positions():
    """
    Sync bot's tracked trades with actual IB positions.
    
    This will:
    1. Update prices/P&L for tracked trades
    2. Identify orphaned trades (in bot but not in IB)
    3. Identify untracked positions (in IB but not in bot)
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from routers.ib import get_pushed_positions
        
        ib_positions = get_pushed_positions()
        ib_symbols = {p.get("symbol"): p for p in ib_positions if p.get("position", 0) != 0}
        
        bot_trades = _trading_bot._open_trades
        bot_symbols = {t.symbol: t for t in bot_trades.values()}
        
        # Find discrepancies
        orphaned = []  # In bot but not in IB
        untracked = []  # In IB but not in bot
        synced = []  # Matched positions
        
        # Check bot trades against IB
        for symbol, trade in bot_symbols.items():
            if symbol in ib_symbols:
                ib_pos = ib_symbols[symbol]
                synced.append({
                    "symbol": symbol,
                    "bot_shares": trade.shares,
                    "ib_shares": abs(ib_pos.get("position", 0)),
                    "bot_entry": trade.fill_price,
                    "ib_avg_cost": ib_pos.get("avgCost", 0),
                    "current_price": ib_pos.get("marketPrice", 0),
                    "stop_price": trade.stop_price
                })
            else:
                orphaned.append({
                    "symbol": symbol,
                    "shares": trade.shares,
                    "note": "Position not found in IB - may have been closed"
                })
        
        # Check IB positions not in bot
        for symbol, ib_pos in ib_symbols.items():
            if symbol not in bot_symbols:
                shares = ib_pos.get("position", 0)
                untracked.append({
                    "symbol": symbol,
                    "shares": abs(shares),
                    "direction": "long" if shares > 0 else "short",
                    "avg_cost": ib_pos.get("avgCost", 0),
                    "note": "Position not tracked by bot - no stop protection"
                })
        
        return {
            "success": True,
            "synced_positions": synced,
            "orphaned_trades": orphaned,
            "untracked_positions": untracked,
            "summary": {
                "bot_tracking": len(bot_trades),
                "ib_positions": len(ib_symbols),
                "synced": len(synced),
                "orphaned": len(orphaned),
                "untracked": len(untracked)
            }
        }
        
    except Exception as e:
        logger.error(f"Position sync error: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/clear-orphaned")
async def clear_orphaned_trades():
    """
    Remove trades from bot tracking that no longer exist in IB.
    
    This is useful after:
    - Manual closes in IB that the bot didn't track
    - App restarts where old phantom trades remain
    - Database sync issues
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from routers.ib import get_pushed_positions
        
        ib_positions = get_pushed_positions()
        ib_symbols = {p.get("symbol") for p in ib_positions if p.get("position", 0) != 0}
        
        # Find orphaned trades (in bot but not in IB)
        orphaned_ids = []
        orphaned_symbols = []
        
        for trade_id, trade in list(_trading_bot._open_trades.items()):
            if trade.symbol not in ib_symbols:
                orphaned_ids.append(trade_id)
                orphaned_symbols.append(trade.symbol)
        
        # Remove orphaned trades
        for trade_id in orphaned_ids:
            if trade_id in _trading_bot._open_trades:
                del _trading_bot._open_trades[trade_id]
        
        logger.info(f"🧹 Cleared {len(orphaned_ids)} orphaned trades: {orphaned_symbols[:10]}...")
        
        return {
            "success": True,
            "cleared_count": len(orphaned_ids),
            "cleared_symbols": orphaned_symbols,
            "remaining_trades": len(_trading_bot._open_trades),
            "message": f"Cleared {len(orphaned_ids)} orphaned trades that no longer exist in IB"
        }
        
    except Exception as e:
        logger.error(f"Failed to clear orphaned trades: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear orphaned trades: {str(e)}")

