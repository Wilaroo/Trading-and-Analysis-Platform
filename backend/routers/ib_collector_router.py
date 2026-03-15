"""
IB Historical Data Collector Router
====================================

API endpoints for managing historical data collection from IB Gateway.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional, List
import logging

from services.ib_historical_collector import get_ib_collector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ib-collector", tags=["ib-collector"])


@router.post("/start")
async def start_collection(
    symbols: Optional[List[str]] = None,
    bar_size: str = "5 mins",
    duration: str = "1 M",
    use_defaults: bool = True
):
    """
    Start a historical data collection job.
    
    - **symbols**: List of symbols to collect (optional, uses defaults if not provided)
    - **bar_size**: Bar size (1 min, 5 mins, 15 mins, 1 hour, 1 day)
    - **duration**: Duration per request (1 D, 2 D, 1 W, 1 M, etc.)
    - **use_defaults**: If true, use default symbol list when none provided
    """
    try:
        collector = get_ib_collector()
        result = await collector.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=use_defaults
        )
        return result
    except Exception as e:
        logger.error(f"Error starting collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick-collect")
async def quick_collect():
    """
    Start a quick collection with default symbols and 1-day data.
    Good for testing the connection.
    """
    try:
        collector = get_ib_collector()
        # Use fewer symbols for quick test
        quick_symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META"]
        result = await collector.start_collection(
            symbols=quick_symbols,
            bar_size="5 mins",
            duration="1 D",
            use_defaults=False
        )
        return result
    except Exception as e:
        logger.error(f"Error starting quick collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/full-collection")
async def full_collection(days: int = 30):
    """
    Start a comprehensive data collection for training.
    This collects multiple bar sizes for all default symbols.
    
    - **days**: Number of days of data to collect (affects duration)
    """
    try:
        collector = get_ib_collector()
        
        # Calculate duration based on days
        if days <= 7:
            duration = f"{days} D"
        elif days <= 30:
            duration = f"{days // 7 + 1} W"
        else:
            duration = f"{days // 30 + 1} M"
            
        result = await collector.start_collection(
            symbols=None,  # Use defaults
            bar_size="5 mins",
            duration=duration,
            use_defaults=True
        )
        return result
    except Exception as e:
        logger.error(f"Error starting full collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/full-market-collection")
async def full_market_collection(
    bar_size: str = "1 day",
    days: int = 30,
    min_price: float = 1.0,
    max_price: float = 1000.0
):
    """
    Start collection for ALL tradeable US stocks (8000+).
    
    ⚠️ This is a LONG-RUNNING job that can take several hours.
    Best to run overnight.
    
    - **bar_size**: Bar size (recommend "1 day" for full market - faster)
    - **days**: Number of days of data to collect
    - **min_price**: Minimum stock price filter (default $1)
    - **max_price**: Maximum stock price filter (default $1000)
    """
    try:
        collector = get_ib_collector()
        
        # Calculate duration based on days
        if days <= 7:
            duration = f"{days} D"
        elif days <= 30:
            duration = f"{days // 7 + 1} W"
        else:
            duration = f"{days // 30 + 1} M"
            
        result = await collector.start_full_market_collection(
            bar_size=bar_size,
            duration=duration,
            min_price=min_price,
            max_price=max_price
        )
        return result
    except Exception as e:
        logger.error(f"Error starting full market collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_collection():
    """Cancel the currently running collection job."""
    try:
        collector = get_ib_collector()
        result = collector.cancel_collection()
        return result
    except Exception as e:
        logger.error(f"Error cancelling collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_status(job_id: Optional[str] = None):
    """
    Get status of a collection job.
    If no job_id provided, returns current running job status.
    """
    try:
        collector = get_ib_collector()
        result = collector.get_job_status(job_id)
        return result
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats():
    """Get statistics about all collected historical data."""
    try:
        collector = get_ib_collector()
        result = collector.get_collection_stats()
        return result
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_job_history(limit: int = 10):
    """Get history of collection jobs."""
    try:
        collector = get_ib_collector()
        result = collector.get_job_history(limit)
        return result
    except Exception as e:
        logger.error(f"Error getting history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data/{symbol}")
async def get_symbol_data(
    symbol: str,
    bar_size: str = "5 mins",
    limit: int = 1000
):
    """
    Get collected historical data for a specific symbol.
    
    - **symbol**: Stock symbol (e.g., AAPL)
    - **bar_size**: Bar size to retrieve (default: 5 mins)
    - **limit**: Maximum number of bars to return (default: 1000)
    """
    try:
        collector = get_ib_collector()
        result = collector.get_symbol_data(symbol, bar_size, limit)
        return result
    except Exception as e:
        logger.error(f"Error getting symbol data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default-symbols")
async def get_default_symbols():
    """Get the list of default symbols for collection."""
    try:
        collector = get_ib_collector()
        symbols = collector.get_default_symbols()
        return {
            "success": True,
            "symbols": symbols,
            "count": len(symbols)
        }
    except Exception as e:
        logger.error(f"Error getting default symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/full-market-symbols")
async def get_full_market_symbols(min_price: float = 1.0, max_price: float = 1000.0):
    """
    Get the count of all tradeable US stocks.
    This fetches from Alpaca and caches the result.
    """
    try:
        collector = get_ib_collector()
        symbols = await collector.get_all_us_symbols(min_price, max_price)
        return {
            "success": True,
            "count": len(symbols),
            "sample": symbols[:20] if symbols else [],  # Show first 20 as sample
            "note": f"Full market: {len(symbols)} US stocks meeting criteria (${min_price}-${max_price})"
        }
    except Exception as e:
        logger.error(f"Error getting full market symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))
