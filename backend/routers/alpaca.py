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
def get_alpaca_status():
    """Get Alpaca service status"""
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    return {
        "success": True,
        "status": _alpaca_service.get_status()
    }


@router.get("/quote/{symbol}")
async def get_quote(symbol: str, prefer_ib: bool = True):
    """
    Get real-time quote for a single symbol.
    
    By default, tries IB pushed data first, falls back to Alpaca.
    Set prefer_ib=false to force Alpaca.
    
    Returns bid, ask, last price, and volume data.
    """
    symbol_upper = symbol.upper()
    
    # Try IB pushed data first (if preferred)
    if prefer_ib:
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            
            if is_pusher_connected():
                quotes = get_pushed_quotes()
                if symbol_upper in quotes:
                    q = quotes[symbol_upper]
                    return {
                        "success": True,
                        "data": {
                            "symbol": symbol_upper,
                            "price": q.get("last") or q.get("close") or 0,
                            "bid": q.get("bid") or 0,
                            "ask": q.get("ask") or 0,
                            "bid_size": q.get("bid_size") or 0,
                            "ask_size": q.get("ask_size") or 0,
                            "volume": q.get("volume") or 0,
                            "timestamp": q.get("timestamp", ""),
                            "source": "ib_pusher"
                        }
                    }
        except Exception:
            pass  # Fall through to Alpaca
    
    # Fallback to Alpaca
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


@router.get("/rvol/{symbol}")
async def get_rvol(symbol: str):
    """
    Get Relative Volume (RVOL) for a symbol.
    
    RVOL = Current Volume / 20-day Average Volume (time-adjusted)
    
    Returns:
        rvol: Float (e.g., 2.5 means 2.5x normal volume)
        rvol_status: exceptional (5x+), high (3x+), strong (2x+), in_play (1.5x+), normal
    """
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    rvol = await _alpaca_service.calculate_rvol(symbol.upper())
    
    if rvol is None:
        raise HTTPException(status_code=404, detail=f"Could not calculate RVOL for {symbol}")
    
    rvol_status = (
        'exceptional' if rvol >= 5 else
        'high' if rvol >= 3 else
        'strong' if rvol >= 2 else
        'in_play' if rvol >= 1.5 else
        'normal'
    )
    
    return {
        "success": True,
        "data": {
            "symbol": symbol.upper(),
            "rvol": rvol,
            "rvol_status": rvol_status,
            "description": f"{rvol}x average volume"
        }
    }


@router.post("/quotes/with-rvol")
async def get_quotes_with_rvol(request: BatchQuoteRequest):
    """
    Get quotes with RVOL for multiple symbols.
    
    More expensive than /quotes but includes relative volume analysis.
    Limited to 10 symbols per request to avoid rate limits.
    """
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    if not request.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    if len(request.symbols) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 symbols per request for RVOL calculation")
    
    quotes = await _alpaca_service.get_quotes_with_rvol(request.symbols)
    
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
def clear_cache():
    """Clear the quote cache"""
    if not _alpaca_service:
        raise HTTPException(status_code=500, detail="Alpaca service not initialized")
    
    _alpaca_service.clear_cache()
    
    return {
        "success": True,
        "message": "Cache cleared"
    }
