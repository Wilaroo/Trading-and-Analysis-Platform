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
    Start collection for ALL tradeable US stocks (12,000+).
    
    ⚠️ This is a LONG-RUNNING job that can take 10+ hours.
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


@router.post("/liquid-collection")
async def liquid_collection(
    bar_size: str = "1 day",
    days: int = 30,
    min_adv: int = 100_000
):
    """
    Start collection for LIQUID US stocks only (~800 stocks).
    
    ✅ RECOMMENDED: Much faster than full market (2-3 hours vs 10+ hours).
    Focuses on stocks with high trading volume that are actually tradeable.
    
    - **bar_size**: Bar size (default "1 day")
    - **days**: Number of days of data to collect
    - **min_adv**: Minimum average daily volume (default 100,000)
    
    Time estimates:
    - ~1,500 symbols × 3 seconds = ~1.25 hours for 1 day bars
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
            
        result = await collector.start_liquid_collection(
            bar_size=bar_size,
            duration=duration,
            min_adv=min_adv
        )
        return result
    except Exception as e:
        logger.error(f"Error starting liquid collection: {e}")
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



@router.get("/liquid-symbols")
async def get_liquid_symbols(min_adv: int = 100_000):
    """
    Get the count of liquid US stocks (filtered by ADV).
    
    - **min_adv**: Minimum average daily volume (default 100,000)
    """
    try:
        collector = get_ib_collector()
        symbols = await collector.get_liquid_symbols(min_adv=min_adv)
        
        # Estimate collection time
        time_per_symbol = 3  # seconds
        total_seconds = len(symbols) * time_per_symbol
        hours = total_seconds / 3600
        
        return {
            "success": True,
            "count": len(symbols),
            "sample": symbols[:20] if symbols else [],
            "min_adv": min_adv,
            "estimated_time": f"{hours:.1f} hours for 1-day bars",
            "note": f"Liquid stocks: {len(symbols)} symbols with ADV >= {min_adv:,}"
        }
    except Exception as e:
        logger.error(f"Error getting liquid symbols: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/build-adv-cache")
async def build_adv_cache(batch_size: int = 100):
    """
    Build/refresh the ADV (Average Daily Volume) cache for all US stocks.
    
    This enables accurate filtering by liquidity. The cache stores the 20-day
    average volume for each symbol.
    
    ⚠️ This is a LONG-RUNNING operation (30-60 minutes for full market).
    Run once to initialize, then periodically to refresh.
    
    - **batch_size**: Number of symbols to process per Alpaca API call
    """
    try:
        collector = get_ib_collector()
        result = await collector.build_adv_cache(batch_size=batch_size)
        return result
    except Exception as e:
        logger.error(f"Error building ADV cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/adv-cache-stats")
async def get_adv_cache_stats():
    """
    Get statistics about the ADV cache.
    
    Shows how many symbols are cached and breakdown by ADV threshold.
    """
    try:
        collector = get_ib_collector()
        stats = await collector.get_adv_cache_stats()
        return {"success": True, **stats}
    except Exception as e:
        logger.error(f"Error getting ADV cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/smart-collection-plan")
async def get_smart_collection_plan(
    include_intraday: bool = True,
    include_swing: bool = True,
    include_investment: bool = True
):
    """
    Get a smart collection plan that matches ADV requirements to trading styles.
    
    This shows what will be collected for each tier:
    - **Intraday** (1min, 5min): ADV >= 500K stocks only
    - **Swing** (15min, 1hour): ADV >= 100K stocks
    - **Investment** (1day): ADV >= 50K stocks (broadest)
    
    This approach saves significant time by not collecting high-frequency
    data for illiquid stocks that wouldn't be traded intraday anyway.
    """
    try:
        collector = get_ib_collector()
        plan = await collector.start_smart_collection(
            include_intraday=include_intraday,
            include_swing=include_swing,
            include_investment=include_investment
        )
        return plan
    except Exception as e:
        logger.error(f"Error getting smart collection plan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/smart-collection-run")
async def run_smart_collection(
    days: int = 30,
    include_intraday: bool = True,
    include_swing: bool = True,
    include_investment: bool = True
):
    """
    Execute the smart tiered collection.
    
    Collects data matching your bot's ADV requirements:
    - **Intraday** (1min, 5min): High-ADV stocks (>= 500K) - fast in/out
    - **Swing** (15min, 1hour): Medium-ADV stocks (>= 100K) - multi-day holds
    - **Investment** (1day): All tradeable stocks (>= 50K) - position trades
    
    ⚠️ LONG-RUNNING: Check /api/ib-collector/status for progress
    """
    try:
        collector = get_ib_collector()
        
        # Calculate duration
        if days <= 7:
            duration = f"{days} D"
        elif days <= 30:
            duration = f"{days // 7 + 1} W"
        else:
            duration = f"{days // 30 + 1} M"
        
        result = await collector.run_smart_collection(
            duration=duration,
            include_intraday=include_intraday,
            include_swing=include_swing,
            include_investment=include_investment
        )
        return result
    except Exception as e:
        logger.error(f"Error running smart collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))
