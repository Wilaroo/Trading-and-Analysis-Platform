"""
Interactive Brokers API Router
Endpoints for IB connection, account info, trading, and market data
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from services.ib_service import IBService
from services.feature_engine import get_feature_engine

router = APIRouter(prefix="/api/ib", tags=["Interactive Brokers"])

# Service instance (will be injected)
_ib_service: Optional[IBService] = None


def init_ib_service(service: IBService):
    """Initialize the IB service for this router"""
    global _ib_service
    _ib_service = service


# ===================== Pydantic Models =====================

class OrderRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol")
    action: str = Field(..., description="BUY or SELL")
    quantity: int = Field(..., gt=0, description="Number of shares")
    order_type: str = Field(default="MKT", description="Order type: MKT, LMT, STP, STP_LMT")
    limit_price: Optional[float] = Field(default=None, description="Limit price for LMT orders")
    stop_price: Optional[float] = Field(default=None, description="Stop price for STP orders")


class SubscribeRequest(BaseModel):
    symbol: str = Field(..., description="Stock symbol to subscribe")


# ===================== Connection Endpoints =====================

@router.get("/status")
async def get_connection_status():
    """Get IB connection status"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    return _ib_service.get_connection_status()


@router.post("/connect")
async def connect_to_ib():
    """Connect to Interactive Brokers Gateway/TWS"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    success = await _ib_service.connect()
    
    if success:
        return {"status": "connected", "message": "Successfully connected to IB"}
    else:
        raise HTTPException(
            status_code=503,
            detail="Failed to connect to IB Gateway. Make sure IB Gateway is running on port 4002."
        )


@router.post("/disconnect")
async def disconnect_from_ib():
    """Disconnect from Interactive Brokers"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    await _ib_service.disconnect()
    return {"status": "disconnected", "message": "Disconnected from IB"}


# ===================== Account Endpoints =====================

@router.get("/account/summary")
async def get_account_summary():
    """Get account summary including balances and P&L"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        return await _ib_service.get_account_summary()
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching account summary: {str(e)}")


@router.get("/account/positions")
async def get_positions():
    """Get all current positions"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        positions = await _ib_service.get_positions()
        return {"positions": positions, "count": len(positions)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positions: {str(e)}")


# ===================== Market Data Endpoints =====================

@router.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """Get real-time quote for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        quote = await _ib_service.get_quote(symbol)
        if quote:
            return quote
        else:
            raise HTTPException(status_code=404, detail=f"No quote available for {symbol}")
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quote: {str(e)}")


@router.post("/subscribe")
async def subscribe_market_data(request: SubscribeRequest):
    """Subscribe to streaming market data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        success = await _ib_service.subscribe_market_data(request.symbol)
        if success:
            return {"status": "subscribed", "symbol": request.symbol.upper()}
        else:
            raise HTTPException(status_code=503, detail="Failed to subscribe - not connected to IB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error subscribing: {str(e)}")


@router.post("/unsubscribe")
async def unsubscribe_market_data(request: SubscribeRequest):
    """Unsubscribe from market data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    success = await _ib_service.unsubscribe_market_data(request.symbol)
    return {"status": "unsubscribed" if success else "not_found", "symbol": request.symbol.upper()}


@router.get("/historical/{symbol}")
async def get_historical_data(
    symbol: str,
    duration: str = "1 D",
    bar_size: str = "5 mins"
):
    """Get historical bar data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        bars = await _ib_service.get_historical_data(symbol, duration, bar_size)
        return {"symbol": symbol.upper(), "bars": bars, "count": len(bars)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching historical data: {str(e)}")


# ===================== Trading Endpoints =====================

@router.post("/order")
async def place_order(request: OrderRequest):
    """Place a new order"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    # Validate action
    if request.action.upper() not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="Action must be BUY or SELL")
    
    # Validate order type
    valid_order_types = ["MKT", "LMT", "STP", "STP_LMT"]
    if request.order_type.upper() not in valid_order_types:
        raise HTTPException(status_code=400, detail=f"Order type must be one of: {valid_order_types}")
    
    # Validate prices based on order type
    if request.order_type.upper() == "LMT" and request.limit_price is None:
        raise HTTPException(status_code=400, detail="Limit price required for limit orders")
    
    if request.order_type.upper() == "STP" and request.stop_price is None:
        raise HTTPException(status_code=400, detail="Stop price required for stop orders")
    
    if request.order_type.upper() == "STP_LMT" and (request.stop_price is None or request.limit_price is None):
        raise HTTPException(status_code=400, detail="Both stop and limit prices required for stop-limit orders")
    
    try:
        result = await _ib_service.place_order(
            symbol=request.symbol,
            action=request.action,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            stop_price=request.stop_price
        )
        return result
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error placing order: {str(e)}")


@router.delete("/order/{order_id}")
async def cancel_order(order_id: int):
    """Cancel an open order"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        success = await _ib_service.cancel_order(order_id)
        if success:
            return {"status": "cancelled", "order_id": order_id}
        else:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found or already filled")
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling order: {str(e)}")


@router.get("/orders/open")
async def get_open_orders():
    """Get all open orders"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        orders = await _ib_service.get_open_orders()
        return {"orders": orders, "count": len(orders)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")


@router.get("/executions")
async def get_executions():
    """Get today's executions/fills"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        executions = await _ib_service.get_executions()
        return {"executions": executions, "count": len(executions)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching executions: {str(e)}")


# ===================== Scanner Endpoints =====================

class ScannerRequest(BaseModel):
    scan_type: str = Field(default="TOP_PERC_GAIN", description="Scanner type")
    max_results: int = Field(default=50, ge=1, le=100, description="Max results")


@router.post("/scanner")
async def run_market_scanner(request: ScannerRequest):
    """
    Run IB market scanner to find trade opportunities.
    
    Available scan types:
    - TOP_PERC_GAIN: Top % gainers
    - TOP_PERC_LOSE: Top % losers
    - MOST_ACTIVE: Most active by volume
    - HOT_BY_VOLUME: Hot by volume
    - HIGH_OPEN_GAP: High opening gap (gap up)
    - LOW_OPEN_GAP: Low opening gap (gap down)
    - TOP_TRADE_COUNT: Most trades
    - HIGH_VS_13W_HL: Near 13-week high
    - LOW_VS_13W_HL: Near 13-week low
    - HIGH_VS_52W_HL: Near 52-week high
    - LOW_VS_52W_HL: Near 52-week low
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        results = await _ib_service.run_scanner(
            scan_type=request.scan_type,
            max_results=request.max_results
        )
        return {"results": results, "count": len(results), "scan_type": request.scan_type}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running scanner: {str(e)}")


@router.post("/quotes/batch")
async def get_batch_quotes(symbols: List[str]):
    """Get real-time quotes for multiple symbols"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    if len(symbols) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 symbols per request")
    
    try:
        quotes = await _ib_service.get_quotes_batch(symbols)
        return {"quotes": quotes, "count": len(quotes)}
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quotes: {str(e)}")


@router.get("/fundamentals/{symbol}")
async def get_fundamentals(symbol: str):
    """Get fundamental data for a symbol"""
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        data = await _ib_service.get_fundamentals(symbol)
        return data
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching fundamentals: {str(e)}")

