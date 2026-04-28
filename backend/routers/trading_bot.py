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


@router.get("/multiplier-analytics")
async def get_multiplier_analytics(
    days_back: int = Query(default=30, ge=1, le=365),
    only_closed: bool = Query(default=True),
):
    """A/B-style analytics for the liquidity-aware execution layers.

    Slices `bot_trades` over the last `days_back` days into "snap fired"
    vs "snap didn't fire" cohorts for the stop-guard, target-snap, and
    VP-path multiplier. Returns mean R-multiple, win rate, and sample
    size per cohort so the operator can tell at a glance whether each
    layer is moving live P&L. Used by the SmartLevelsAnalyticsCard.
    """
    if _trading_bot is None or getattr(_trading_bot, "_db", None) is None:
        raise HTTPException(status_code=503, detail="trading bot not initialized")
    try:
        from services.multiplier_analytics_service import compute_multiplier_analytics
        return compute_multiplier_analytics(
            _trading_bot._db, days_back=days_back, only_closed=only_closed,
        )
    except Exception as e:
        logger.error(f"multiplier analytics failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/execution-health")
async def get_execution_health(
    hours: int = Query(24, ge=1, le=8760,
                       description="Window size in hours (1 — 8760 = 1 year)."),
    flag_trades: bool = Query(
        False, description="If true, also persist stop_honored flag onto trade docs."),
):
    """Return Trade Execution Health report.

    Scans closed bot_trades in the window and flags stop-execution failures
    (losers that blew past 1.5R = their intended stop wasn't honored at IB).

    Alert levels:
      - `ok`                 : failure rate < 5%
      - `warning`            : 5% — 15% (investigate)
      - `critical`           : > 15% (stop trading, fix stop orders)
      - `insufficient_data`  : < 5 closed trades in window
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.trade_execution_health import TradeExecutionHealth
    health = TradeExecutionHealth(db)
    report = health.audit_recent_trades(hours=hours)
    flagged = health.flag_trade_docs(hours=hours) if flag_trades else 0

    return {
        "success": True,
        "report": report.to_dict(),
        "flagged_docs": flagged,
    }


@router.get("/trade-autopsy/{trade_id}")
async def get_trade_autopsy(trade_id: str):
    """Full forensic view for any closed trade (2026-04-21).

    Assembles bot_trades + gate_decisions + live_alerts into one dict so you
    can see exactly why a losing trade fired: entry/exit, realized R,
    stop-honor status, layer-by-layer gate vote, P(win), and the scanner
    context at entry.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.trade_autopsy import TradeAutopsy
    autopsy = TradeAutopsy(db).autopsy(trade_id)
    if autopsy is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return {"success": True, "autopsy": autopsy}


@router.get("/recent-losses")
async def get_recent_losses(limit: int = Query(20, ge=1, le=200)):
    """List the worst recent losing trades for triage-by-autopsy workflow."""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    db = _trading_bot._db
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    from services.trade_autopsy import TradeAutopsy
    losses = TradeAutopsy(db).recent_losses(limit=limit)
    return {"success": True, "count": len(losses), "losses": losses}


@router.post("/positions/protect-orphans")
async def protect_orphan_positions(
    risk_pct: float = Query(0.01, ge=0.001, le=0.10,
                            description="Emergency stop distance as pct of avg cost when no intended stop is known"),
    dry_run: bool = Query(True, description="Default to dry-run for safety; pass false to actually place stops"),
):
    """Place emergency STP orders on IB positions that have no working stop.

    Phase 4 of the IB bracket migration (see IB_BRACKET_ORDER_MIGRATION.md).
    Invoke at startup or after suspected stop failures to close the naked-
    position gap that caused the PD/GNW imported_from_ib losses.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    if not hasattr(_trading_bot, "_position_reconciler") or not _trading_bot._position_reconciler:
        raise HTTPException(status_code=503, detail="Position reconciler not initialized")

    report = await _trading_bot._position_reconciler.protect_orphan_positions(
        _trading_bot, risk_pct=risk_pct, dry_run=dry_run,
    )
    return {"success": True, "report": report}


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
def get_executor_status():
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
def set_executor_mode(mode: str):
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
def set_bot_mode(mode: str):
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
def update_bot_config(config: BotConfigUpdate):
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
def update_risk_params(params: RiskParamsUpdate):
    """Update risk management parameters"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    updates = params.dict(exclude_none=True)
    _trading_bot.update_risk_params(**updates)
    
    return {"success": True, "risk_params": _trading_bot.get_status()["risk_params"]}


# ==================== EOD AUTO-CLOSE ====================

class EODConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    close_hour: Optional[int] = None  # 0-23 in ET
    close_minute: Optional[int] = None  # 0-59


@router.get("/eod-config")
def get_eod_config():
    """Get EOD auto-close configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    return {
        "success": True,
        "eod_config": {
            "enabled": _trading_bot._eod_close_enabled,
            "close_hour": _trading_bot._eod_close_hour,
            "close_minute": _trading_bot._eod_close_minute,
            "close_time_et": f"{_trading_bot._eod_close_hour}:{_trading_bot._eod_close_minute:02d} PM ET",
            "executed_today": _trading_bot._eod_close_executed_today,
            "last_check_date": _trading_bot._last_eod_check_date
        }
    }


@router.post("/eod-config")
def update_eod_config(config: EODConfigUpdate):
    """Update EOD auto-close configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    if config.enabled is not None:
        _trading_bot._eod_close_enabled = config.enabled
    
    if config.close_hour is not None:
        if not 0 <= config.close_hour <= 23:
            raise HTTPException(status_code=400, detail="close_hour must be 0-23")
        _trading_bot._eod_close_hour = config.close_hour
    
    if config.close_minute is not None:
        if not 0 <= config.close_minute <= 59:
            raise HTTPException(status_code=400, detail="close_minute must be 0-59")
        _trading_bot._eod_close_minute = config.close_minute
    
    # Persist config to database
    if _trading_bot._db:
        _trading_bot._db.bot_config.update_one(
            {"_id": "eod_config"},
            {"$set": {
                "enabled": _trading_bot._eod_close_enabled,
                "close_hour": _trading_bot._eod_close_hour,
                "close_minute": _trading_bot._eod_close_minute,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
    
    return {
        "success": True,
        "eod_config": {
            "enabled": _trading_bot._eod_close_enabled,
            "close_hour": _trading_bot._eod_close_hour,
            "close_minute": _trading_bot._eod_close_minute,
            "close_time_et": f"{_trading_bot._eod_close_hour}:{_trading_bot._eod_close_minute:02d} PM ET"
        },
        "message": "EOD configuration updated"
    }


@router.post("/eod-close-now")
async def trigger_eod_close_now():
    """
    Manually trigger EOD close of all positions.
    Use this to close all positions immediately regardless of time.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    open_count = len(_trading_bot._open_trades)
    if open_count == 0:
        return {"success": True, "message": "No open positions to close", "closed_count": 0}
    
    closed_count = 0
    total_pnl = 0.0
    results = []
    
    for trade_id, trade in list(_trading_bot._open_trades.items()):
        try:
            result = await _trading_bot.close_trade(trade_id, reason="manual_eod_close")
            if result.get("success"):
                closed_count += 1
                pnl = result.get("realized_pnl", 0)
                total_pnl += pnl
                results.append({
                    "symbol": trade.symbol,
                    "shares": trade.remaining_shares,
                    "pnl": pnl,
                    "status": "closed"
                })
            else:
                results.append({
                    "symbol": trade.symbol,
                    "error": result.get("error"),
                    "status": "failed"
                })
        except Exception as e:
            results.append({
                "symbol": trade.symbol,
                "error": str(e),
                "status": "error"
            })
    
    return {
        "success": True,
        "message": f"Closed {closed_count} of {open_count} positions",
        "closed_count": closed_count,
        "total_pnl": total_pnl,
        "results": results
    }


# ==================== TRADE MANAGEMENT ====================

@router.get("/trades/pending")
def get_pending_trades():
    """Get all trades awaiting confirmation"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_pending_trades()
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/open")
def get_open_trades():
    """Get all open positions"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_open_trades()
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/closed")
def get_closed_trades(limit: int = Query(50, ge=1, le=500)):
    """Get closed trades history"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trades = _trading_bot.get_closed_trades(limit=limit)
    return {"success": True, "count": len(trades), "trades": trades}


@router.get("/trades/all")
def get_all_trades():
    """Get all bot trades (pending, open, closed) for the AI Command Panel"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    summary = _trading_bot.get_all_trades_summary()
    return {"success": True, **summary}


@router.delete("/trades/{symbol}")
def delete_trade_by_symbol(symbol: str):
    """
    Delete a trade from bot_trades by symbol. 
    Use for removing erroneous or imported trades that should not be in the system.
    Removes from both in-memory tracking and MongoDB.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    symbol = symbol.upper()
    removed = []
    
    # Remove from in-memory open trades
    to_remove = [tid for tid, t in _trading_bot._open_trades.items() if t.symbol.upper() == symbol]
    for tid in to_remove:
        del _trading_bot._open_trades[tid]
        removed.append({"id": tid, "source": "open_trades"})
    
    # Remove from in-memory closed trades
    before = len(_trading_bot._closed_trades)
    _trading_bot._closed_trades = [t for t in _trading_bot._closed_trades if t.symbol.upper() != symbol]
    closed_removed = before - len(_trading_bot._closed_trades)
    if closed_removed > 0:
        removed.append({"count": closed_removed, "source": "closed_trades"})
    
    # Remove from MongoDB bot_trades
    if _trading_bot._db is not None:
        result = _trading_bot._db.bot_trades.delete_many({"symbol": symbol})
        if result.deleted_count > 0:
            removed.append({"count": result.deleted_count, "source": "mongodb_bot_trades"})
        
        # Also remove any confidence gate logs for this symbol (prevent learning)
        cg_result = _trading_bot._db.confidence_gate_log.delete_many({"symbol": symbol})
        if cg_result.deleted_count > 0:
            removed.append({"count": cg_result.deleted_count, "source": "confidence_gate_log"})
    
    if not removed:
        return {"success": True, "message": f"No trades found for {symbol}", "removed": []}
    
    return {"success": True, "message": f"Deleted all {symbol} trade data", "removed": removed}



@router.get("/positions/reconcile")
async def reconcile_positions():
    """
    Compare bot's tracked positions with actual IB positions.
    Returns discrepancies that need attention.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        report = await _trading_bot.reconcile_positions_with_ib()
        return {
            "success": True,
            **report
        }
    except Exception as e:
        logger.error(f"Reconciliation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/sync/{symbol}")
async def sync_position(symbol: str, auto_create: bool = False):
    """
    Sync a specific position from IB to the bot's tracking.
    
    Args:
        symbol: Stock symbol to sync
        auto_create: If True, create a new trade entry for untracked positions
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        result = await _trading_bot.sync_position_from_ib(symbol, auto_create_trade=auto_create)
        return result
    except Exception as e:
        logger.error(f"Sync error for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/sync-all")
async def sync_all_positions():
    """
    Full position sync - imports untracked positions, closes phantoms, fixes mismatches.
    This is the comprehensive sync that should be run on startup or when positions drift.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        report = await _trading_bot.full_position_sync()
        return report
    except Exception as e:
        logger.error(f"Full sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/positions/close-phantom/{trade_id}")
async def close_phantom_trade(trade_id: str, reason: str = "manual_close"):
    """
    Close a specific phantom trade (one that bot tracks but IB doesn't have).
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        result = await _trading_bot.close_phantom_position(trade_id, reason=reason)
        return result
    except Exception as e:
        logger.error(f"Close phantom error for {trade_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/trades")
def get_trades_list():
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
def get_trade(trade_id: str):
    """Get details of a specific trade including explanation"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    trade = _trading_bot.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    return {"success": True, "trade": trade}


@router.post("/trades/{trade_id}/confirm")
async def confirm_trade(trade_id: str):
    """Confirm a pending trade for execution.

    Returns 200 for any correctly-handled outcome (executed, simulated,
    vetoed by guardrail, paper-phase) with the trade's actual status in
    the response. Returns 404 only when the trade doesn't exist, 400 for
    genuine rejections (stale alert, broker error).
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")

    # Capture existence up-front so we can distinguish 404 vs 400 after the call
    existed_before = trade_id in _trading_bot._pending_trades or _trading_bot.get_trade(trade_id) is not None

    success = await _trading_bot.confirm_trade(trade_id)
    trade = _trading_bot.get_trade(trade_id)

    if success:
        # Trade was legitimately handled — surface the actual outcome so the
        # UI can show "Executed" / "Simulated" / "Paper" / "Vetoed" accurately.
        status = trade.get("status") if isinstance(trade, dict) else getattr(trade, "status", None)
        status_str = getattr(status, "value", status) if status is not None else "unknown"

        messages = {
            "open": "Trade executed — position open",
            "partial": "Trade partially filled",
            "simulated": "Trade skipped — strategy in SIMULATION phase",
            "paper": "Trade logged — strategy in PAPER phase (not sent to broker)",
            "vetoed": "Trade vetoed by pre-trade guardrail",
        }
        return {
            "success": True,
            "status": status_str,
            "message": messages.get(status_str, f"Trade handled: {status_str}"),
            "trade": trade,
        }

    # Not handled — distinguish "never existed" from "existed but rejected"
    if not existed_before:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Trade existed but was rejected (stale alert, broker error, etc.)
    status = trade.get("status") if isinstance(trade, dict) else getattr(trade, "status", None)
    status_str = getattr(status, "value", status) if status is not None else "rejected"
    notes = trade.get("notes") if isinstance(trade, dict) else getattr(trade, "notes", "")
    raise HTTPException(
        status_code=400,
        detail={
            "error": "Trade rejected",
            "status": status_str,
            "reason": notes or "Rejected by execution pipeline",
        },
    )


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



@router.post("/close-by-symbol")
async def close_by_symbol(request: dict):
    """Close all open trades for a given symbol (used by chat server)."""
    if not _trading_bot:
        return {"success": False, "error": "Trading bot not initialized"}
    
    symbol = request.get("symbol", "").upper()
    reason = request.get("reason", "chat_requested")
    
    if not symbol:
        return {"success": False, "error": "No symbol provided"}
    
    # Find open trades for this symbol
    closed = []
    for trade_id, trade in list(_trading_bot._open_trades.items()):
        if trade.symbol.upper() == symbol:
            try:
                success = await _trading_bot.close_trade(trade_id, reason=reason)
                if success:
                    closed.append(trade_id)
            except Exception as e:
                logger.error(f"Error closing {symbol} trade {trade_id}: {e}")
    
    if closed:
        return {
            "success": True,
            "message": f"Closed {len(closed)} {symbol} position(s)",
            "trade_ids": closed
        }
    else:
        return {
            "success": False, 
            "error": f"No open bot trades found for {symbol}. It may be a manual position — close it in TWS directly."
        }


@router.post("/quick-order")
async def quick_order(request: dict):
    """Place a quick market order (used by chat server)."""
    if not _trading_bot:
        return {"success": False, "error": "Trading bot not initialized"}
    
    symbol = request.get("symbol", "").upper()
    action = request.get("action", "").lower()
    shares = request.get("shares", 0)
    reason = request.get("reason", "chat_requested")
    
    if not symbol or not action:
        return {"success": False, "error": "Symbol and action required"}
    
    # For now, log the intent — full execution through the standard pipeline
    # This prevents the chat from bypassing risk checks
    return {
        "success": True,
        "message": f"Order intent logged: {action} {shares} {symbol}. Use the scanner pipeline for execution with full risk checks."
    }


# ==================== STATISTICS ====================

@router.get("/stats/daily")
def get_daily_stats():
    """Get daily trading statistics"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    stats = _trading_bot.get_daily_stats()
    return {"success": True, "stats": stats}


@router.get("/stats/performance")
def get_performance_stats():
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
def get_equity_curve(period: str = Query("today", enum=["today", "week", "month", "ytd", "all"])):
    """
    Get equity curve data for the bot performance chart.
    Returns cumulative P&L over time with trade markers.
    Includes both realized P&L (closed trades) and unrealized P&L (open positions).
    
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
                "realized_pnl": 0,
                "unrealized_pnl": 0,
                "trades_count": 0,
                "win_rate": 0,
                "avg_r": 0,
                "best_trade": 0,
                "worst_trade": 0,
                "open_positions": 0
            }
        }
    
    try:
        from datetime import timedelta
        
        # Get closed trades
        closed = _trading_bot.get_closed_trades(limit=1000)
        
        # Get open positions for unrealized P&L
        open_trades = _trading_bot.get_all_trades_summary()
        open_positions = open_trades.get('open', [])
        
        # Calculate total unrealized P&L from open positions
        total_unrealized_pnl = sum(pos.get('unrealized_pnl', 0) for pos in open_positions)
        
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
        
        # Build equity curve from closed trades
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
        
        # Add current point with unrealized P&L if we have open positions
        if open_positions:
            current_timestamp = int(now.timestamp() * 1000)
            current_total = cumulative_pnl + total_unrealized_pnl
            
            equity_curve.append({
                "time": current_timestamp,
                "value": current_total,
                "is_live": True,
                "unrealized": total_unrealized_pnl
            })
            
            # Add markers for open positions (different style)
            for pos in open_positions:
                entry_time_str = pos.get('entry_time')
                if entry_time_str:
                    try:
                        entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                        if entry_time >= cutoff:
                            trade_markers.append({
                                "time": int(entry_time.timestamp() * 1000),
                                "pnl": pos.get('unrealized_pnl', 0),
                                "symbol": pos.get('symbol', ''),
                                "setup_type": pos.get('setup_type', ''),
                                "is_open": True,
                                "is_win": pos.get('unrealized_pnl', 0) > 0
                            })
                    except (ValueError, TypeError):
                        pass
        
        # Calculate summary stats
        wins = [p for p in pnls if p > 0]
        
        # Calculate average R-multiple from trades that have it
        r_multiples = [t.get('r_multiple', 0) for t in filtered_trades if t.get('r_multiple')]
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0
        
        summary = {
            "total_pnl": cumulative_pnl + total_unrealized_pnl,
            "realized_pnl": cumulative_pnl,
            "unrealized_pnl": total_unrealized_pnl,
            "trades_count": len(filtered_trades),
            "win_rate": (len(wins) / len(filtered_trades) * 100) if filtered_trades else 0,
            "avg_r": avg_r,
            "best_trade": max(pnls, default=0),
            "worst_trade": min(pnls, default=0),
            "open_positions": len(open_positions)
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
    - STOP AUDIT WARNINGS for risky stop placements
    
    Each thought has:
    - text: The thought in first person (e.g., "I detected a breakout on NVDA...")
    - timestamp: When the thought occurred
    - confidence: 0-100 confidence level
    - action_type: entry, exit, watching, monitoring, scanning, alert, stop_warning
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
        
        # 0. STOP AUDIT WARNINGS (highest priority - show first)
        stop_audit = await audit_position_stops()
        if stop_audit.get("success") and stop_audit.get("warnings"):
            for warning in stop_audit["warnings"][:3]:  # Max 3 stop warnings
                severity = warning.get("severity", "info")
                symbol = warning.get("symbol", "UNKNOWN")
                message = warning.get("message", "")
                
                # Color-code by severity
                if severity == "critical":
                    emoji = "🚨"
                    confidence = 95
                elif severity == "warning":
                    emoji = "⚠️"
                    confidence = 80
                else:
                    emoji = "💡"
                    confidence = 60
                
                thoughts.append({
                    "text": f'{emoji} "{message}"',
                    "timestamp": now.isoformat(),
                    "confidence": confidence,
                    "action_type": "stop_warning",
                    "symbol": symbol,
                    "severity": severity
                })
        
        # 0.5. SMART STRATEGY FILTER THOUGHTS (High priority - trade filtering reasoning)
        filter_thoughts = _trading_bot.get_filter_thoughts(limit=5)
        for ft in filter_thoughts:
            action = ft.get("action", "PROCEED")
            text = ft.get("text", "")
            symbol = ft.get("symbol", None)
            win_rate = ft.get("win_rate", 0)
            
            # Color-code by action type
            if action == "SKIP":
                confidence = 85
                action_type = "filter_skip"
            elif action == "REDUCE_SIZE":
                confidence = 70
                action_type = "filter_reduce"
            else:
                confidence = 60
                action_type = "filter_proceed"
            
            thoughts.append({
                "text": f'"{text}"',
                "timestamp": ft.get("timestamp", now.isoformat()),
                "confidence": confidence,
                "action_type": action_type,
                "symbol": symbol,
                "win_rate": win_rate,
                "filter_action": action
            })
        
        # 1. Thoughts from pending trades (about to execute)
        for trade in _trading_bot.get_pending_trades()[:3]:
            symbol = trade.get('symbol', 'UNKNOWN')
            setup = trade.get('setup_type', 'trade')
            entry = trade.get('entry_price', 0)
            rr = trade.get('risk_reward_ratio', 0)
            
            thoughts.append({
                "text": f'"We\'re preparing to enter {symbol} on a {setup.replace("_", " ")} setup at ${entry:.2f}. Risk/Reward is {rr:.1f}:1. Awaiting confirmation."',
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
                "text": f'"We\'re monitoring our {symbol} position. Currently {direction} {abs(pnl_pct):.1f}%. Our stop at ${stop:.2f} is safe. {f"Target 1 at ${target:.2f}." if target else ""}"',
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
                text = f'"We closed {symbol} for +${pnl:.2f}. {reason.replace("_", " ").title()} worked well for us."'
            else:
                text = f'"We closed {symbol} for -${abs(pnl):.2f}. {reason.replace("_", " ").title()}. We\'re learning from this."'
            
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
                regime_comment = "so we're looking for aggressive breakout setups."
            elif regime == 'RISK_OFF':
                regime_comment = "so we're being cautious and reducing position sizes."
            elif regime == 'CONFIRMED_DOWN':
                regime_comment = "so we're favoring short setups and reducing long exposure."
            else:
                regime_comment = "so we're using standard position sizing."
            
            thoughts.append({
                "text": f'"We\'re actively scanning for opportunities in {mode} mode. Market regime is {regime}, {regime_comment}"',
                "timestamp": now.isoformat(),
                "confidence": 50,
                "action_type": "scanning",
                "symbol": None
            })
        
        # Sort by timestamp (most recent first) and limit
        # Handle None timestamps by using epoch as fallback
        thoughts.sort(key=lambda t: t['timestamp'] or '1970-01-01T00:00:00', reverse=True)
        
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

@router.get("/audit-stops")
async def audit_position_stops():
    """
    Audit all open positions for risky stop placements.
    
    Analyzes each open position using the Smart Stop System to detect:
    - Stops that are too tight (will get stopped out easily)
    - Stops near round numbers ($50, $100, etc.) - easy hunting targets
    - Stops below obvious support levels - institutional hunting zones
    - Stops that don't account for current volatility/regime
    
    Returns warnings with severity levels and suggested improvements.
    This is automatically included in the bot's "thoughts" stream.
    """
    if not _trading_bot:
        return {
            "success": True,
            "warnings": [],
            "positions_audited": 0,
            "healthy_positions": 0,
            "message": "Trading bot not initialized"
        }
    
    try:
        from services.smart_stop_service import get_smart_stop_service
        smart_stop = get_smart_stop_service()
        
        open_trades = _trading_bot.get_open_trades()
        warnings = []
        healthy_count = 0
        
        for trade in open_trades:
            symbol = trade.get('symbol', '')
            entry_price = trade.get('fill_price') or trade.get('entry_price', 0)
            current_price = trade.get('current_price', entry_price)
            stop_price = trade.get('stop_price', 0)
            direction = trade.get('direction', 'long')
            setup_type = trade.get('setup_type', 'default')
            
            if not entry_price or not stop_price:
                continue
            
            # Estimate ATR as 2% of price if not available
            atr = entry_price * 0.02
            
            # Analyze using intelligent stop service
            try:
                analysis = await smart_stop.calculate_intelligent_stop(
                    symbol=symbol,
                    entry_price=entry_price,
                    current_price=current_price,
                    direction=direction,
                    setup_type=setup_type,
                    position_size=trade.get('shares', 100),
                    atr=atr
                )
                
                optimal_stop = analysis.stop_price
                hunt_risk = analysis.hunt_risk
                urgency = analysis.urgency.value
                
                # Check for problems
                problems = []
                
                # 1. Check if stop is too tight
                stop_distance = abs(stop_price - entry_price)
                min_distance = atr * 0.75  # Minimum 0.75 ATR
                if stop_distance < min_distance:
                    problems.append({
                        "type": "too_tight",
                        "severity": "critical",
                        "message": f"Stop for {symbol} is too tight (${stop_distance:.2f} vs min ${min_distance:.2f}). High probability of getting stopped out on normal volatility."
                    })
                
                # 2. Check if stop is near round number
                round_numbers = [n for n in [50, 100, 150, 200, 250, 300, 400, 500] if abs(stop_price - n) < n * 0.01]
                if round_numbers:
                    problems.append({
                        "type": "round_number",
                        "severity": "warning",
                        "message": f"{symbol} stop at ${stop_price:.2f} is near ${round_numbers[0]} - a common stop hunting target. Consider moving it."
                    })
                
                # 3. Check hunt risk
                if hunt_risk == "HIGH":
                    problems.append({
                        "type": "hunt_risk",
                        "severity": "warning",
                        "message": f"{symbol} has HIGH stop hunt risk. Your stop at ${stop_price:.2f} may be vulnerable. Optimal: ${optimal_stop:.2f}"
                    })
                
                # 4. Check urgency
                if urgency in ["high_alert", "emergency"]:
                    problems.append({
                        "type": "urgency",
                        "severity": "critical",
                        "message": f"{symbol} position needs attention! Urgency: {urgency.upper()}. Consider tightening or exiting."
                    })
                
                # 5. Check if stop is much worse than optimal
                if direction == 'long' and stop_price > optimal_stop + atr * 0.5:
                    problems.append({
                        "type": "suboptimal",
                        "severity": "info",
                        "message": f"{symbol} stop could be tighter. Current: ${stop_price:.2f}, Suggested: ${optimal_stop:.2f} (+{((optimal_stop - stop_price)/entry_price*100):.1f}% better risk)"
                    })
                elif direction == 'short' and stop_price < optimal_stop - atr * 0.5:
                    problems.append({
                        "type": "suboptimal",
                        "severity": "info",
                        "message": f"{symbol} stop could be tighter. Current: ${stop_price:.2f}, Suggested: ${optimal_stop:.2f}"
                    })
                
                if problems:
                    for problem in problems:
                        warnings.append({
                            "symbol": symbol,
                            "current_stop": stop_price,
                            "optimal_stop": optimal_stop,
                            "entry_price": entry_price,
                            "current_price": current_price,
                            "hunt_risk": hunt_risk,
                            **problem
                        })
                else:
                    healthy_count += 1
                    
            except Exception as e:
                logger.debug(f"Could not analyze stop for {symbol}: {e}")
                healthy_count += 1  # Assume healthy if we can't analyze
        
        # Sort warnings by severity (critical first, then warning, then info)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        warnings.sort(key=lambda w: severity_order.get(w.get("severity", "info"), 2))
        
        return {
            "success": True,
            "warnings": warnings,
            "positions_audited": len(open_trades),
            "healthy_positions": healthy_count,
            "positions_with_issues": len(open_trades) - healthy_count,
            "summary": {
                "critical": len([w for w in warnings if w.get("severity") == "critical"]),
                "warning": len([w for w in warnings if w.get("severity") == "warning"]),
                "info": len([w for w in warnings if w.get("severity") == "info"])
            }
        }
        
    except Exception as e:
        logger.error(f"Error auditing position stops: {e}")
        return {
            "success": False,
            "error": str(e),
            "warnings": []
        }


@router.post("/fix-stop/{trade_id}")
async def fix_stop_to_recommended(trade_id: str):
    """
    One-Click Stop Fix: Automatically adjust a risky stop to the recommended level.
    
    Uses the Smart Stop System to calculate the optimal stop price and updates
    the trade's stop price. This is the quick fix for stop audit warnings.
    
    Args:
        trade_id: The ID of the trade to fix
    
    Returns:
        Updated trade with new stop price and explanation of the fix
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        from services.smart_stop_service import get_smart_stop_service
        smart_stop = get_smart_stop_service()
        
        # Find the trade
        trade = None
        for t_id, t in _trading_bot._open_trades.items():
            if t.id == trade_id or t_id == trade_id:
                trade = t
                break
        
        if not trade:
            raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
        
        symbol = trade.symbol
        entry_price = trade.fill_price or trade.entry_price
        current_price = trade.current_price
        stop_price = trade.stop_price
        direction = trade.direction.value if hasattr(trade.direction, 'value') else trade.direction
        setup_type = trade.setup_type
        
        # Estimate ATR as 2% of price if not available
        atr = entry_price * 0.02
        
        # Calculate intelligent stop
        analysis = await smart_stop.calculate_intelligent_stop(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            direction=direction,
            setup_type=setup_type,
            position_size=trade.shares,
            atr=atr
        )
        
        new_stop = analysis.stop_price
        old_stop = stop_price
        
        # Update the trade's stop price
        trade.stop_price = new_stop
        
        # Update trailing stop config as well
        if hasattr(trade, 'trailing_stop_config') and trade.trailing_stop_config:
            trade.trailing_stop_config['current_stop'] = new_stop
            trade.trailing_stop_config['stop_adjustments'] = trade.trailing_stop_config.get('stop_adjustments', [])
            trade.trailing_stop_config['stop_adjustments'].append({
                'from': old_stop,
                'to': new_stop,
                'reason': 'one_click_fix',
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        
        # Persist the updated trade
        _trading_bot._persist_trade(trade)
        
        # Calculate improvement
        if direction == 'long':
            improvement_pct = ((new_stop - old_stop) / entry_price * 100)
            improvement_desc = f"Tightened stop by {abs(improvement_pct):.1f}%" if new_stop > old_stop else f"Loosened stop by {abs(improvement_pct):.1f}%"
        else:
            improvement_pct = ((old_stop - new_stop) / entry_price * 100)
            improvement_desc = f"Tightened stop by {abs(improvement_pct):.1f}%" if new_stop < old_stop else f"Loosened stop by {abs(improvement_pct):.1f}%"
        
        logger.info(f"🔧 One-Click Stop Fix: {symbol} stop adjusted from ${old_stop:.2f} to ${new_stop:.2f} ({improvement_desc})")
        
        return {
            "success": True,
            "trade_id": trade.id,
            "symbol": symbol,
            "old_stop": old_stop,
            "new_stop": new_stop,
            "improvement": improvement_desc,
            "analysis": {
                "hunt_risk": analysis.hunt_risk,
                "urgency": analysis.urgency.value,
                "factors_considered": analysis.factors_considered[:3] if analysis.factors_considered else []
            },
            "message": f"Stop for {symbol} fixed: ${old_stop:.2f} → ${new_stop:.2f}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fixing stop for trade {trade_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fix stop: {str(e)}")


@router.post("/fix-all-risky-stops")
async def fix_all_risky_stops():
    """
    Fix ALL risky stops in one click.
    
    Runs the stop audit, identifies all positions with critical or warning issues,
    and automatically adjusts their stops to optimal levels.
    
    Returns a summary of all fixes applied.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    try:
        # First run the audit to identify issues
        audit_result = await audit_position_stops()
        
        if not audit_result.get("success") or not audit_result.get("warnings"):
            return {
                "success": True,
                "message": "No risky stops to fix",
                "fixes_applied": 0,
                "positions_checked": audit_result.get("positions_audited", 0)
            }
        
        # Filter to critical and warning level issues only
        risky_warnings = [
            w for w in audit_result["warnings"]
            if w.get("severity") in ["critical", "warning"]
        ]
        
        if not risky_warnings:
            return {
                "success": True,
                "message": "No critical or warning-level stop issues to fix",
                "fixes_applied": 0,
                "positions_checked": audit_result.get("positions_audited", 0)
            }
        
        # Group warnings by symbol (one fix per symbol)
        symbols_to_fix = {}
        for warning in risky_warnings:
            symbol = warning.get("symbol")
            if symbol and symbol not in symbols_to_fix:
                symbols_to_fix[symbol] = warning
        
        # Apply fixes
        fixes = []
        errors = []
        
        for symbol, warning in symbols_to_fix.items():
            # Find the trade for this symbol
            trade = None
            for t in _trading_bot._open_trades.values():
                if t.symbol == symbol:
                    trade = t
                    break
            
            if not trade:
                errors.append({"symbol": symbol, "error": "Trade not found"})
                continue
            
            try:
                # Fix this trade's stop
                fix_result = await fix_stop_to_recommended(trade.id)
                if fix_result.get("success"):
                    fixes.append({
                        "symbol": symbol,
                        "old_stop": fix_result["old_stop"],
                        "new_stop": fix_result["new_stop"],
                        "improvement": fix_result["improvement"]
                    })
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
        
        logger.info(f"🔧 Bulk Stop Fix: Applied {len(fixes)} fixes, {len(errors)} errors")
        
        return {
            "success": True,
            "message": f"Fixed {len(fixes)} risky stops",
            "fixes_applied": len(fixes),
            "fixes": fixes,
            "errors": errors if errors else None,
            "positions_checked": audit_result.get("positions_audited", 0)
        }
        
    except Exception as e:
        logger.error(f"Error fixing all risky stops: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fix stops: {str(e)}")


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
def get_strategy_configs():
    """Get all strategy configurations"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    configs = _trading_bot.get_strategy_configs()
    return {"success": True, "configs": configs}


@router.put("/strategy-configs/{strategy}")
def update_strategy_config(strategy: str, config: StrategyConfigUpdate):
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
def sync_with_ib_positions():
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
def clear_orphaned_trades():
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


# ==================== SMART STRATEGY FILTERING ENDPOINTS ====================

@router.get("/smart-filter/config")
def get_smart_filter_config():
    """Get the current Smart Strategy Filter configuration"""
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    return {
        "success": True,
        "config": _trading_bot.get_smart_filter_config()
    }


@router.post("/smart-filter/config")
def update_smart_filter_config(updates: Dict[str, Any]):
    """
    Update Smart Strategy Filter configuration.
    
    Available settings:
    - enabled: bool - Enable/disable smart filtering
    - min_sample_size: int - Minimum trades needed to filter (default: 5)
    - skip_win_rate_threshold: float - Skip if win rate below this (default: 0.35)
    - reduce_size_threshold: float - Reduce size if below this (default: 0.45)
    - require_higher_tqs_threshold: float - Require higher TQS if below (default: 0.50)
    - normal_threshold: float - Normal trading above this (default: 0.55)
    - size_reduction_pct: float - Size reduction percentage (default: 0.5)
    - high_tqs_requirement: int - TQS required for borderline (default: 75)
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    new_config = _trading_bot.update_smart_filter_config(updates)
    
    return {
        "success": True,
        "message": "Smart filter config updated",
        "config": new_config
    }


@router.get("/smart-filter/thoughts")
def get_filter_thoughts(limit: int = Query(10, ge=1, le=50)):
    """
    Get recent strategy filter thoughts/reasoning.
    
    These show when the bot skipped or modified trades based on historical performance.
    Example: "Passing on NVDA breakout - you're only 38% on breakouts historically"
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    thoughts = _trading_bot.get_filter_thoughts(limit=limit)
    
    return {
        "success": True,
        "thoughts": thoughts,
        "count": len(thoughts)
    }


@router.get("/smart-filter/strategy-stats/{setup_type}")
def get_strategy_stats(setup_type: str):
    """
    Get user's historical performance stats for a specific setup type.
    
    Returns win rate, sample size, average R, expected value, etc.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    stats = _trading_bot.get_strategy_historical_stats(setup_type)
    
    return {
        "success": True,
        **stats
    }


@router.get("/smart-filter/all-strategy-stats")
def get_all_strategy_stats():
    """
    Get user's historical performance stats for ALL setup types.
    Useful for the Learning Dashboard to show strategy performance breakdown.
    """
    if not _trading_bot:
        raise HTTPException(status_code=503, detail="Trading bot not initialized")
    
    if not _trading_bot._enhanced_scanner:
        return {
            "success": False,
            "error": "Enhanced scanner not connected",
            "stats": {}
        }
    
    try:
        all_stats = _trading_bot._enhanced_scanner.get_strategy_stats()
        return {
            "success": True,
            "stats": all_stats,
            "count": len(all_stats)
        }
    except Exception as e:
        logger.error(f"Error getting all strategy stats: {e}")
        return {
            "success": False,
            "error": str(e),
            "stats": {}
        }


