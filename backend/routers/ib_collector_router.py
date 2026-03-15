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


@router.get("/data-status")
async def get_data_status(
    bar_size: str = "1 day",
    days_threshold: int = 7
):
    """
    Check what historical data already exists.
    
    Returns count of symbols with recent data vs total expected symbols.
    Use this to understand what will be skipped during collection.
    
    - **bar_size**: Bar size to check (default "1 day")
    - **days_threshold**: Consider data "recent" if collected within this many days
    """
    try:
        collector = get_ib_collector()
        
        # Get symbols with recent data
        symbols_with_data = collector.get_symbols_with_recent_data(bar_size, days_threshold)
        
        # Get total expected symbols (default list)
        default_symbols = collector.get_default_symbols()
        
        # Calculate overlap
        overlap = len(set(s.upper() for s in default_symbols) & symbols_with_data)
        
        return {
            "success": True,
            "bar_size": bar_size,
            "days_threshold": days_threshold,
            "symbols_with_recent_data": len(symbols_with_data),
            "default_symbols_count": len(default_symbols),
            "would_be_skipped": overlap,
            "would_collect": len(default_symbols) - overlap,
            "message": f"{overlap} of {len(default_symbols)} default symbols already have recent {bar_size} data"
        }
    except Exception as e:
        logger.error(f"Error getting data status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_collection(
    symbols: Optional[List[str]] = None,
    bar_size: str = "5 mins",
    duration: str = "1 M",
    use_defaults: bool = True,
    skip_recent: bool = True,
    recent_days_threshold: int = 7,
    force_refresh: bool = False
):
    """
    Start a historical data collection job.
    
    - **symbols**: List of symbols to collect (optional, uses defaults if not provided)
    - **bar_size**: Bar size (1 min, 5 mins, 15 mins, 1 hour, 1 day)
    - **duration**: Duration per request (1 D, 2 D, 1 W, 1 M, etc.)
    - **use_defaults**: If true, use default symbol list when none provided
    - **skip_recent**: Skip symbols that already have data within recent_days_threshold
    - **recent_days_threshold**: Days to consider data "recent" (default 7)
    - **force_refresh**: Ignore existing data and re-collect everything
    """
    try:
        collector = get_ib_collector()
        result = await collector.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=use_defaults,
            skip_recent=skip_recent,
            recent_days_threshold=recent_days_threshold,
            force_refresh=force_refresh
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


@router.post("/resume")
async def resume_collection():
    """
    Resume monitoring and storing data for pending requests.
    
    Use this after your machine wakes up from sleep - it restarts
    the background task that stores completed data from the queue
    to the main database.
    """
    try:
        collector = get_ib_collector()
        
        # Get queue stats to see if there's work to do
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        stats = queue_service.get_overall_queue_stats()
        
        if stats["pending"] == 0 and stats["claimed"] == 0:
            return {
                "success": True,
                "message": "No pending work to resume",
                "stats": stats
            }
        
        # Create a minimal job to resume monitoring
        result = await collector.resume_monitoring()
        return result
        
    except Exception as e:
        logger.error(f"Error resuming collection: {e}")
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


@router.get("/queue-progress")
async def get_queue_progress(job_id: Optional[str] = None):
    """
    Get real-time progress from the data request queue.
    
    This is the primary endpoint for tracking async collection progress.
    It shows pending, processing, completed, and failed counts directly
    from the queue that your local IB Data Pusher is processing.
    
    - **job_id**: Optional job ID. If not provided, returns overall queue stats.
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        if job_id:
            progress = queue_service.get_job_progress(job_id)
            errors = queue_service.get_job_errors(job_id, limit=10)
            return {
                "success": True,
                **progress,
                "recent_errors": errors
            }
        else:
            # Return overall queue stats
            stats = queue_service.get_overall_queue_stats()
            return {
                "success": True,
                **stats
            }
    except Exception as e:
        logger.error(f"Error getting queue progress: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/queue-cancel")
async def cancel_queue_job(job_id: str):
    """
    Cancel pending requests for a specific job.
    
    This cancels only pending requests - already claimed/completed
    requests are not affected.
    
    - **job_id**: The job ID to cancel
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        result = queue_service.cancel_job(job_id)
        
        # Also signal the collector to stop monitoring
        collector = get_ib_collector()
        collector.cancel_collection()
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"Error cancelling queue job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-pending")
async def clear_pending_queue():
    """
    Clear ALL pending requests from the queue.
    
    Use this to reset the queue before starting a fresh collection.
    This will NOT delete:
    - Already collected data (stored in historical_ohlcv collection)
    - Completed requests
    - Currently processing (claimed) requests
    
    Only removes items waiting to be processed.
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        # First cancel any running collection
        collector = get_ib_collector()
        collector.cancel_collection()
        
        # Clear the pending queue
        result = queue_service.clear_pending_requests()
        
        return result
    except Exception as e:
        logger.error(f"Error clearing pending queue: {e}")
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


@router.get("/filter-preview")
async def preview_ib_filter():
    """
    Preview what symbols would be filtered out as IB-incompatible.
    
    Shows counts of:
    - OTC/Pink Sheet stocks
    - ADRs (foreign stocks)
    - Warrants, Rights, Units
    - Preferred shares
    """
    try:
        collector = get_ib_collector()
        
        # Get all symbols from universe
        all_symbols = []
        if collector._db is not None:
            cursor = collector._db["us_symbols"].find({}, {"symbol": 1, "exchange": 1, "_id": 0})
            all_data = list(cursor)
            all_symbols = [doc["symbol"] for doc in all_data if doc.get("symbol")]
            
            # Count by exchange
            exchange_counts = {}
            for doc in all_data:
                ex = doc.get("exchange", "UNKNOWN")
                exchange_counts[ex] = exchange_counts.get(ex, 0) + 1
        
        # Apply filter and count exclusions
        filtered = collector.filter_ib_compatible_symbols(all_symbols)
        excluded_count = len(all_symbols) - len(filtered)
        
        # Sample of excluded symbols
        excluded = [s for s in all_symbols if s not in set(filtered)][:50]
        
        return {
            "success": True,
            "total_symbols": len(all_symbols),
            "ib_compatible": len(filtered),
            "excluded": excluded_count,
            "exchange_breakdown": exchange_counts,
            "excluded_sample": excluded,
            "note": f"Filtering removes {excluded_count} OTC/ADR/warrant symbols"
        }
    except Exception as e:
        logger.error(f"Error previewing filter: {e}")
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
    include_investment: bool = True,
    skip_recent: bool = True,
    recent_days_threshold: int = 7,
    force_refresh: bool = False
):
    """
    Execute the smart tiered collection.
    
    Collects data matching your bot's ADV requirements:
    - **Intraday** (1min, 5min): High-ADV stocks (>= 500K) - fast in/out
    - **Swing** (15min, 1hour): Medium-ADV stocks (>= 100K) - multi-day holds
    - **Investment** (1day): All tradeable stocks (>= 50K) - position trades
    
    **Duplicate Prevention:**
    - `skip_recent=True` (default): Skips symbols collected within `recent_days_threshold` days
    - `force_refresh=True`: Ignores existing data and re-collects everything
    
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
            include_investment=include_investment,
            skip_recent=skip_recent,
            recent_days_threshold=recent_days_threshold,
            force_refresh=force_refresh
        )
        return result
    except Exception as e:
        logger.error(f"Error running smart collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))
