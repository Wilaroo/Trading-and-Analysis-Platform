"""
Quick Actions API Router
Provides endpoints for quick trading actions: Buy, Sell, Close Position, Add to Watchlist, Create Alert
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import logging

router = APIRouter(prefix="/api/quick-actions", tags=["Quick Actions"])

logger = logging.getLogger(__name__)

# Service references
_alpaca_service = None
_db = None
_trading_bot = None
_technical_service = None


def init_quick_actions_router(alpaca_service, db, trading_bot=None, technical_service=None):
    """Initialize router with required services"""
    global _alpaca_service, _db, _trading_bot, _technical_service
    _alpaca_service = alpaca_service
    _db = db
    _trading_bot = trading_bot
    _technical_service = technical_service


# ===================== Pydantic Models =====================

class ClosePositionRequest(BaseModel):
    symbol: str = Field(..., description="Symbol to close position for")
    quantity: Optional[int] = Field(default=None, description="Shares to close (None = all)")

class BuyRequest(BaseModel):
    symbol: str = Field(..., description="Symbol to buy")
    setup_type: str = Field(default="manual", description="Setup type for this trade")
    direction: str = Field(default="long", description="Trade direction: long or short")
    entry_price: Optional[float] = Field(default=None, description="Entry price (uses current if not provided)")
    stop_price: Optional[float] = Field(default=None, description="Stop loss price (calculated from ATR if not provided)")
    target_price: Optional[float] = Field(default=None, description="Target price (calculated from R:R if not provided)")
    use_half_size: bool = Field(default=False, description="Use half the normal position size")
    note: Optional[str] = Field(default=None, description="Optional note for the trade")

class SellRequest(BaseModel):
    symbol: str = Field(..., description="Symbol to sell")
    quantity: Optional[int] = Field(default=None, description="Shares to sell (None = all)")
    reason: str = Field(default="manual", description="Reason for selling")
    
class AddToWatchlistRequest(BaseModel):
    symbol: str = Field(..., description="Symbol to add")
    source: str = Field(default="manual", description="Source of addition")
    reason: Optional[str] = Field(default=None, description="Reason for adding")

class CreateAlertRequest(BaseModel):
    symbol: str = Field(..., description="Symbol for alert")
    alert_type: str = Field(default="price", description="Type: price, percent, volume")
    condition: str = Field(..., description="Condition: above, below, crosses")
    value: float = Field(..., description="Target value for alert")
    note: Optional[str] = Field(default=None, description="Optional note")


# ===================== Buy/Sell Actions =====================

@router.post("/buy")
async def execute_buy(request: BuyRequest):
    """
    Execute a buy order via trading bot with volatility-adjusted position sizing.
    Uses real-time technical data to calculate optimal stop and position size.
    """
    if _alpaca_service is None:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    symbol = request.symbol.upper()
    
    try:
        # Get current quote
        quote = await _alpaca_service.get_quote(symbol)
        if not quote or quote.get('price', 0) <= 0:
            raise HTTPException(status_code=400, detail=f"Cannot get price for {symbol}")
        
        current_price = quote.get('price')
        entry_price = request.entry_price or current_price
        
        # Get technical data for ATR-based sizing
        atr = current_price * 0.02  # Default 2%
        atr_percent = 2.0
        
        if _technical_service:
            try:
                tech_data = await _technical_service.get_technical_snapshot(symbol)
                if tech_data:
                    atr = tech_data.atr
                    atr_percent = tech_data.atr_percent
            except Exception as e:
                logger.warning(f"Could not get technical data for {symbol}: {e}")
        
        # Calculate stop price if not provided (using ATR)
        stop_price = request.stop_price
        if not stop_price:
            # Use ATR-based stop: 1.5x ATR for most setups
            stop_multiplier = {
                'rubber_band': 1.0,
                'squeeze': 1.5,
                'breakout': 1.5,
                'vwap_bounce': 1.0,
                'manual': 1.5
            }.get(request.setup_type, 1.5)
            
            if request.direction == 'long':
                stop_price = entry_price - (atr * stop_multiplier)
            else:
                stop_price = entry_price + (atr * stop_multiplier)
        
        # Calculate target if not provided (2:1 R:R minimum)
        target_price = request.target_price
        if not target_price:
            risk = abs(entry_price - stop_price)
            if request.direction == 'long':
                target_price = entry_price + (risk * 2.0)
            else:
                target_price = entry_price - (risk * 2.0)
        
        # Calculate position size
        risk_per_share = abs(entry_price - stop_price)
        
        # Volatility-adjusted max risk
        base_max_risk = 2500.0  # Default max risk per trade
        if atr_percent < 1.5:
            max_risk = base_max_risk * 1.3
        elif atr_percent < 2.5:
            max_risk = base_max_risk * 1.1
        elif atr_percent < 3.5:
            max_risk = base_max_risk
        elif atr_percent < 5.0:
            max_risk = base_max_risk * 0.8
        else:
            max_risk = base_max_risk * 0.6
        
        if request.use_half_size:
            max_risk = max_risk / 2
        
        shares = int(max_risk / risk_per_share) if risk_per_share > 0 else 0
        shares = max(shares, 1)
        
        # Calculate actual risk and R:R
        risk_amount = shares * risk_per_share
        potential_reward = shares * abs(target_price - entry_price)
        risk_reward = potential_reward / risk_amount if risk_amount > 0 else 0
        
        # Create trade alert for the trading bot
        trade_alert = {
            "symbol": symbol,
            "direction": request.direction,
            "setup_type": request.setup_type,
            "trigger_price": entry_price,
            "current_price": current_price,
            "stop_price": stop_price,
            "targets": [target_price, target_price * 1.5 if request.direction == 'long' else target_price * 0.5],
            "atr": atr,
            "atr_percent": atr_percent,
            "score": 70,  # Default score for manual trades
            "source": "quick_action",
            "note": request.note,
            "half_size": request.use_half_size
        }
        
        # If trading bot is available, submit the trade
        order_result = None
        if _trading_bot:
            try:
                # Submit to trading bot for execution
                result = await _trading_bot._evaluate_opportunity(trade_alert)
                if result:
                    order_result = {"submitted": True, "trade_id": result.id}
            except Exception as e:
                logger.warning(f"Could not submit to trading bot: {e}")
        
        # Record the trade in database
        if _db is not None:
            trade_record = {
                "symbol": symbol,
                "action": "buy",
                "direction": request.direction,
                "setup_type": request.setup_type,
                "shares": shares,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "risk_amount": risk_amount,
                "risk_reward": risk_reward,
                "atr": atr,
                "atr_percent": atr_percent,
                "use_half_size": request.use_half_size,
                "note": request.note,
                "created_at": datetime.now(timezone.utc),
                "status": "submitted" if order_result else "calculated"
            }
            _db["quick_trades"].insert_one(trade_record)
        
        return {
            "success": True,
            "action": "buy",
            "symbol": symbol,
            "direction": request.direction,
            "shares": shares,
            "entry_price": round(entry_price, 2),
            "stop_price": round(stop_price, 2),
            "target_price": round(target_price, 2),
            "risk_amount": round(risk_amount, 2),
            "risk_reward": round(risk_reward, 2),
            "atr": round(atr, 2),
            "atr_percent": round(atr_percent, 2),
            "volatility_adjusted": True,
            "half_size": request.use_half_size,
            "order_result": order_result,
            "message": f"Trade calculated: {shares} shares of {symbol} @ ${entry_price:.2f}, Stop: ${stop_price:.2f}, Target: ${target_price:.2f}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing buy for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to execute buy: {str(e)}")


@router.post("/sell")
async def execute_sell(request: SellRequest):
    """
    Execute a sell order to close or reduce a position.
    Returns position info and records the action (actual execution via trading bot).
    """
    if _alpaca_service is None:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    symbol = request.symbol.upper()
    
    try:
        # Get current positions
        positions = await _alpaca_service.get_positions()
        position = next((p for p in positions if p.get("symbol") == symbol), None)
        
        if not position:
            raise HTTPException(status_code=404, detail=f"No position found for {symbol}")
        
        current_qty = int(float(position.get("qty", 0)))
        sell_qty = request.quantity if request.quantity else current_qty
        
        if sell_qty > current_qty:
            raise HTTPException(status_code=400, detail=f"Cannot sell {sell_qty} shares, only have {current_qty}")
        
        # Get current price for P&L calculation
        quote = await _alpaca_service.get_quote(symbol)
        current_price = quote.get("price", 0) if quote else 0
        entry_price = float(position.get("avg_entry_price", 0))
        unrealized_pnl = (current_price - entry_price) * sell_qty if current_price and entry_price else 0
        
        # Record the sell intent in database
        if _db is not None:
            _db["quick_trades"].insert_one({
                "symbol": symbol,
                "action": "sell",
                "shares": sell_qty,
                "remaining_shares": current_qty - sell_qty,
                "current_price": current_price,
                "entry_price": entry_price,
                "unrealized_pnl": unrealized_pnl,
                "reason": request.reason,
                "created_at": datetime.now(timezone.utc),
                "status": "pending_execution"
            })
        
        return {
            "success": True,
            "action": "sell",
            "symbol": symbol,
            "quantity_to_sell": sell_qty,
            "remaining": current_qty - sell_qty,
            "current_price": round(current_price, 2),
            "entry_price": round(entry_price, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "reason": request.reason,
            "message": f"Sell {sell_qty} shares of {symbol} @ ${current_price:.2f} (Entry: ${entry_price:.2f}, P&L: ${unrealized_pnl:.2f})",
            "note": "Execute via trading bot or manually confirm",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing sell for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to execute sell: {str(e)}")


# ===================== Close Position =====================

@router.post("/close-position")
async def close_position(request: ClosePositionRequest):
    """
    Close a position via Alpaca.
    If quantity is None, closes entire position.
    """
    if _alpaca_service is None:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    symbol = request.symbol.upper()
    
    try:
        # Get current positions to verify we have this position
        positions = await _alpaca_service.get_positions()
        position = next((p for p in positions if p.get("symbol") == symbol), None)
        
        if not position:
            raise HTTPException(status_code=404, detail=f"No position found for {symbol}")
        
        current_qty = int(float(position.get("qty", 0)))
        close_qty = request.quantity if request.quantity else current_qty
        
        if close_qty > current_qty:
            raise HTTPException(status_code=400, detail=f"Cannot close {close_qty} shares, only have {current_qty}")
        
        # Place sell order to close position
        order_result = await _alpaca_service.place_order(
            symbol=symbol,
            qty=close_qty,
            side="sell",
            order_type="market",
            time_in_force="day"
        )
        
        return {
            "success": True,
            "action": "close_position",
            "symbol": symbol,
            "quantity_closed": close_qty,
            "remaining": current_qty - close_qty,
            "order": order_result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing position {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to close position: {str(e)}")


# ===================== Add to Watchlist =====================

@router.post("/add-to-watchlist")
def add_to_watchlist(request: AddToWatchlistRequest):
    """Add a symbol to the smart watchlist"""
    if _db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    symbol = request.symbol.upper()
    
    # Also track as viewed symbol for Tier 1 scanning
    try:
        from services.user_viewed_tracker import track_symbol_view
        track_symbol_view(symbol, source="watchlist_add")
    except Exception:
        pass  # Non-blocking
    
    try:
        # Check if already in watchlist
        existing = _db["smart_watchlist"].find_one({"symbol": symbol})
        
        if existing:
            # Update the existing entry
            _db["smart_watchlist"].update_one(
                {"symbol": symbol},
                {"$set": {
                    "updated_at": datetime.now(timezone.utc),
                    "source": request.source,
                    "reason": request.reason
                }}
            )
            return {
                "success": True,
                "action": "updated",
                "symbol": symbol,
                "message": f"{symbol} already in watchlist, updated entry"
            }
        
        # Add new entry
        watchlist_entry = {
            "symbol": symbol,
            "added_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "source": request.source,
            "reason": request.reason,
            "pinned": False,
            "priority": "medium"
        }
        
        _db["smart_watchlist"].insert_one(watchlist_entry)
        
        return {
            "success": True,
            "action": "added",
            "symbol": symbol,
            "message": f"{symbol} added to watchlist"
        }
        
    except Exception as e:
        logger.error(f"Error adding {symbol} to watchlist: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add to watchlist: {str(e)}")


@router.delete("/remove-from-watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    """Remove a symbol from the smart watchlist"""
    if _db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    symbol = symbol.upper()
    
    try:
        result = _db["smart_watchlist"].delete_one({"symbol": symbol})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"{symbol} not found in watchlist")
        
        return {
            "success": True,
            "action": "removed",
            "symbol": symbol,
            "message": f"{symbol} removed from watchlist"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing {symbol} from watchlist: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove from watchlist: {str(e)}")


# ===================== Price Alerts =====================

@router.post("/create-alert")
def create_alert(request: CreateAlertRequest):
    """Create a price or condition alert"""
    if _db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    symbol = request.symbol.upper()
    
    try:
        # Validate alert type
        valid_types = ["price", "percent", "volume"]
        if request.alert_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid alert type. Must be one of: {valid_types}")
        
        # Validate condition
        valid_conditions = ["above", "below", "crosses"]
        if request.condition not in valid_conditions:
            raise HTTPException(status_code=400, detail=f"Invalid condition. Must be one of: {valid_conditions}")
        
        alert_entry = {
            "symbol": symbol,
            "alert_type": request.alert_type,
            "condition": request.condition,
            "target_value": request.value,
            "note": request.note,
            "created_at": datetime.now(timezone.utc),
            "triggered": False,
            "triggered_at": None,
            "active": True
        }
        
        result = _db["price_alerts"].insert_one(alert_entry)
        
        # Format nice description
        if request.alert_type == "price":
            desc = f"Alert when {symbol} price is {request.condition} ${request.value:.2f}"
        elif request.alert_type == "percent":
            desc = f"Alert when {symbol} moves {request.condition} {request.value}%"
        else:
            desc = f"Alert when {symbol} volume is {request.condition} {request.value:,.0f}"
        
        return {
            "success": True,
            "action": "created",
            "alert_id": str(result.inserted_id),
            "symbol": symbol,
            "description": desc,
            "message": f"Alert created for {symbol}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating alert for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create alert: {str(e)}")


@router.get("/alerts")
def get_active_alerts():
    """Get all active alerts"""
    if _db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    try:
        alerts = list(_db["price_alerts"].find(
            {"active": True},
            {"_id": 0}
        ).sort("created_at", -1).limit(50))
        
        # Convert datetime objects to strings
        for alert in alerts:
            if alert.get("created_at"):
                alert["created_at"] = alert["created_at"].isoformat()
            if alert.get("triggered_at"):
                alert["triggered_at"] = alert["triggered_at"].isoformat()
        
        return {
            "success": True,
            "alerts": alerts,
            "count": len(alerts)
        }
        
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch alerts: {str(e)}")


@router.delete("/alerts/{symbol}")
def delete_alerts_for_symbol(symbol: str):
    """Delete all alerts for a symbol"""
    if _db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    symbol = symbol.upper()
    
    try:
        result = _db["price_alerts"].delete_many({"symbol": symbol})
        
        return {
            "success": True,
            "symbol": symbol,
            "deleted_count": result.deleted_count
        }
        
    except Exception as e:
        logger.error(f"Error deleting alerts for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete alerts: {str(e)}")
