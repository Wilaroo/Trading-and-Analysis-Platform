"""
Quick Actions API Router
Provides endpoints for quick trading actions: Close Position, Add to Watchlist, Create Alert
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import os
import logging

router = APIRouter(prefix="/api/quick-actions", tags=["Quick Actions"])

logger = logging.getLogger(__name__)

# Service references
_alpaca_service = None
_db = None


def init_quick_actions_router(alpaca_service, db):
    """Initialize router with required services"""
    global _alpaca_service, _db
    _alpaca_service = alpaca_service
    _db = db


# ===================== Pydantic Models =====================

class ClosePositionRequest(BaseModel):
    symbol: str = Field(..., description="Symbol to close position for")
    quantity: Optional[int] = Field(default=None, description="Shares to close (None = all)")
    
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
async def add_to_watchlist(request: AddToWatchlistRequest):
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
async def remove_from_watchlist(symbol: str):
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
async def create_alert(request: CreateAlertRequest):
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
async def get_active_alerts():
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
async def delete_alerts_for_symbol(symbol: str):
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
