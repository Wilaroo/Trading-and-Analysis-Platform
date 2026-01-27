"""
Alpaca Market Data API Router
Provides REST endpoints for Alpaca market data.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/alpaca", tags=["Alpaca Market Data"])

# Service instance
_alpaca_service = None


def init_alpaca_router(alpaca_service):
    """Initialize the router with the Alpaca service"""
    global _alpaca_service
    _alpaca_service = alpaca_service


# ===================== Pydantic Models =====================

class QuoteResponse(BaseModel):
    symbol: str
    price: float
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    volume: int
    timestamp: str
    source: str


class BatchQuoteRequest(BaseModel):
    symbols: List[str]


class BarData(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None
    trade_count: Optional[int] = None


# ===================== Endpoints =====================

@router.get("/status")
async def get_alpaca_status():
    """Get Alpaca service status"""
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    return {
        "success": True,
        "status": _alpaca_service.get_status()
    }


@router.get("/quote/{symbol}")
async def get_quote(symbol: str):
    """
    Get real-time quote for a single symbol.
    
    Returns bid, ask, last price, and volume data.
    """
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    quote = await _alpaca_service.get_quote(symbol)
    
    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote not found for {symbol}")
    
    return {
        "success": True,
        "data": quote
    }


@router.post("/quotes")
async def get_quotes_batch(request: BatchQuoteRequest):
    """
    Get quotes for multiple symbols in a single request.
    
    More efficient than calling /quote/{symbol} multiple times.
    """
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    if not request.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    if len(request.symbols) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 symbols per request")
    
    quotes = await _alpaca_service.get_quotes_batch(request.symbols)
    
    return {
        "success": True,
        "count": len(quotes),
        "data": quotes
    }


@router.get("/bars/{symbol}")
async def get_bars(
    symbol: str,
    timeframe: str = Query(default="1Day", regex="^(1Min|5Min|15Min|1Hour|1Day)$"),
    limit: int = Query(default=100, ge=1, le=1000)
):
    """
    Get historical bars/candles for a symbol.
    
    Args:
        symbol: Stock symbol
        timeframe: Bar timeframe - 1Min, 5Min, 15Min, 1Hour, 1Day
        limit: Number of bars (1-1000)
    """
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    bars = await _alpaca_service.get_bars(symbol, timeframe, limit)
    
    return {
        "success": True,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "count": len(bars),
        "data": bars
    }


@router.get("/account")
async def get_account():
    """
    Get Alpaca account information.
    
    Returns cash balance, buying power, portfolio value, etc.
    """
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    account = await _alpaca_service.get_account()
    
    if not account:
        raise HTTPException(status_code=500, detail="Failed to fetch account info")
    
    return {
        "success": True,
        "data": account
    }


@router.delete("/cache")
async def clear_cache():
    """Clear the quote cache"""
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    _alpaca_service.clear_cache()
    
    return {
        "success": True,
        "message": "Cache cleared"
    }
