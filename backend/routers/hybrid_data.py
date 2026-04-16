"""
Hybrid Data API Router
======================
API endpoints for the hybrid data fetching service.
Provides historical market data from IB (primary) or Alpaca (fallback).
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["Hybrid Data"])

# Service instance (will be injected)
_hybrid_data_service = None


def init_hybrid_data_router(service):
    """Initialize router with the hybrid data service"""
    global _hybrid_data_service
    _hybrid_data_service = service


# ===================== Pydantic Models =====================

class BarsRequest(BaseModel):
    """Request for historical bars"""
    symbol: str = Field(..., description="Stock symbol (e.g., SPY)")
    timeframe: str = Field("1day", description="Timeframe: 1min, 5min, 15min, 1hour, 1day")
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    days_back: int = Field(365, description="Days to look back if dates not specified")
    force_refresh: bool = Field(False, description="Bypass cache and fetch fresh data")
    preferred_source: Literal["auto", "ib", "alpaca", "cache"] = Field(
        "auto", description="Preferred data source"
    )


class PrefetchRequest(BaseModel):
    """Request to prefetch data for multiple symbols"""
    symbols: List[str] = Field(..., description="List of symbols to prefetch")
    timeframe: str = Field("1day", description="Timeframe for all symbols")
    days_back: int = Field(365, description="Days to look back")


class CacheClearRequest(BaseModel):
    """Request to clear cached data"""
    symbol: Optional[str] = Field(None, description="Symbol to clear (all if not specified)")
    timeframe: Optional[str] = Field(None, description="Timeframe to clear (all if not specified)")


# ===================== Endpoints =====================

@router.get("/status")
def get_data_service_status():
    """
    Get hybrid data service status including connection status and rate limits.
    """
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    return _hybrid_data_service.get_service_status()


@router.post("/bars")
async def get_historical_bars(request: BarsRequest):
    """
    Get historical bars for a symbol.
    
    Automatically selects the best data source:
    1. MongoDB cache (if available)
    2. IB Gateway (if connected)
    3. Alpaca (fallback, 24/7)
    """
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    result = await _hybrid_data_service.get_bars(
        symbol=request.symbol,
        timeframe=request.timeframe,
        start_date=request.start_date,
        end_date=request.end_date,
        days_back=request.days_back,
        force_refresh=request.force_refresh,
        preferred_source=request.preferred_source
    )
    
    return {
        "success": result.success,
        "symbol": request.symbol.upper(),
        "timeframe": request.timeframe,
        "source": result.source,
        "from_cache": result.from_cache,
        "bar_count": result.bar_count,
        "bars": result.bars if result.success else [],
        "error": result.error
    }


@router.get("/bars/{symbol}")
async def get_bars_simple(
    symbol: str,
    timeframe: str = Query("1day", description="Timeframe"),
    days: int = Query(365, description="Days to look back"),
    force_refresh: bool = Query(False, description="Bypass cache")
):
    """
    Simple GET endpoint for historical bars.
    """
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    result = await _hybrid_data_service.get_bars(
        symbol=symbol,
        timeframe=timeframe,
        days_back=days,
        force_refresh=force_refresh
    )
    
    return {
        "success": result.success,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "source": result.source,
        "from_cache": result.from_cache,
        "bar_count": result.bar_count,
        "bars": result.bars if result.success else [],
        "error": result.error
    }


@router.post("/prefetch")
async def prefetch_symbols(request: PrefetchRequest, background_tasks: BackgroundTasks):
    """
    Prefetch historical data for multiple symbols.
    Runs in background to not block the API.
    
    Use this to pre-warm the cache before running backtests.
    """
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    # For small requests, do it synchronously
    if len(request.symbols) <= 5:
        result = await _hybrid_data_service.prefetch_symbols(
            symbols=request.symbols,
            timeframe=request.timeframe,
            days_back=request.days_back
        )
        return {
            "success": True,
            "mode": "sync",
            "result": result
        }
    
    # For larger requests, queue as background task
    async def do_prefetch():
        try:
            await _hybrid_data_service.prefetch_symbols(
                symbols=request.symbols,
                timeframe=request.timeframe,
                days_back=request.days_back
            )
        except Exception as e:
            logger.error(f"Prefetch error: {e}")
    
    background_tasks.add_task(do_prefetch)
    
    return {
        "success": True,
        "mode": "background",
        "message": f"Prefetching {len(request.symbols)} symbols in background",
        "symbols": request.symbols
    }


@router.get("/cache/symbols")
async def get_cached_symbols():
    """Get list of symbols with cached data."""
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    symbols = await _hybrid_data_service.get_cached_symbols()
    return {
        "success": True,
        "count": len(symbols),
        "symbols": symbols
    }


@router.get("/cache/stats")
async def get_cache_stats(symbol: Optional[str] = None):
    """Get cache statistics for all or specific symbols."""
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    stats = await _hybrid_data_service.get_cache_stats(symbol)
    return {
        "success": True,
        "stats": stats
    }


@router.delete("/cache")
async def clear_cache(request: CacheClearRequest):
    """Clear cached historical data."""
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    result = await _hybrid_data_service.clear_cache(
        symbol=request.symbol,
        timeframe=request.timeframe
    )
    
    return result


@router.get("/timeframes")
def get_supported_timeframes():
    """Get list of supported timeframes."""
    if not _hybrid_data_service:
        raise HTTPException(status_code=500, detail="Hybrid data service not initialized")
    
    status = _hybrid_data_service.get_service_status()
    return {
        "success": True,
        "timeframes": status["supported_timeframes"],
        "description": {
            "1min": "1 minute bars (intraday)",
            "5min": "5 minute bars (intraday)",
            "15min": "15 minute bars (intraday)",
            "1hour": "1 hour bars",
            "1day": "Daily bars"
        }
    }
