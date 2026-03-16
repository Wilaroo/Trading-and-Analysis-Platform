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


@router.get("/queue-progress-detailed")
async def get_queue_progress_detailed():
    """
    Get detailed queue progress broken down by bar_size.
    
    Returns progress for each type of data being collected (1 min, 5 mins, 1 day, etc.)
    so you can see exactly what's happening with each collection type.
    
    Response includes:
    - **by_bar_size**: List of progress for each bar_size
    - **active_collections**: Only bar_sizes with pending/in-progress work
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        detailed = queue_service.get_queue_stats_by_bar_size()
        overall = queue_service.get_overall_queue_stats()
        
        return {
            "success": True,
            "overall": overall,
            **detailed
        }
    except Exception as e:
        logger.error(f"Error getting detailed queue progress: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/cancel-by-barsize")
async def cancel_collection_by_barsize(bar_size: str):
    """
    Cancel all pending requests for a specific bar_size.
    
    Use this to cancel a specific collection without affecting others.
    For example, cancel "5 mins" collection while letting "1 day" continue.
    
    - **bar_size**: The bar size to cancel (e.g., "5 mins", "1 day", "1 min")
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        result = queue_service.cancel_by_bar_size(bar_size)
        
        return result
    except Exception as e:
        logger.error(f"Error cancelling collection for bar_size {bar_size}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all-pending")
async def cancel_all_pending_collections():
    """
    Cancel ALL pending collections across all bar_sizes.
    
    Use this to completely clear the queue and start fresh.
    Already completed data is NOT affected.
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        result = queue_service.clear_all_pending()
        
        # Also signal collector to stop
        collector = get_ib_collector()
        collector.cancel_collection()
        
        return result
    except Exception as e:
        logger.error(f"Error cancelling all pending collections: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resumable-collections")
async def get_resumable_collections():
    """
    Get collections that can be resumed.
    
    Returns bar_sizes that have partial data collected but are not currently active.
    These can be resumed to continue where they left off.
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        resumable = queue_service.get_resumable_collections()
        
        return {
            "success": True,
            "resumable": resumable,
            "count": len(resumable)
        }
    except Exception as e:
        logger.error(f"Error getting resumable collections: {e}")
        return {"success": False, "error": str(e)}



@router.post("/clear-stuck")
async def clear_stuck_items(bar_size: str = None, older_than_minutes: int = 10):
    """
    Clear items that have been stuck in 'claimed' status for too long.
    
    These are items that IB Gateway claimed but never completed - likely failed silently.
    They will be marked as 'failed' so they can be retried on resume.
    
    - **bar_size**: Optional - only clear stuck items for this bar_size
    - **older_than_minutes**: Clear items claimed longer than this (default 10 min)
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        
        result = queue_service.clear_stuck_items(bar_size, older_than_minutes)
        
        return result
    except Exception as e:
        logger.error(f"Error clearing stuck items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume-collection")
async def resume_barsize_collection(
    bar_size: str,
    retry_failed: bool = True,
    collection_type: str = "smart"
):
    """
    Resume a previously cancelled/paused collection.
    
    This will:
    1. Get the list of symbols that have already been collected for this bar_size
    2. Get the original symbol list based on collection_type
    3. Queue only the symbols that haven't been collected yet
    4. Optionally retry failed symbols
    
    - **bar_size**: The bar size to resume (e.g., "5 mins", "1 day")
    - **retry_failed**: If True, also retry symbols that previously failed
    - **collection_type**: How to determine the full symbol list (smart, liquid, full_market)
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        collector = get_ib_collector()
        
        # Get symbols already completed
        completed_symbols = set(queue_service.get_completed_symbols(bar_size))
        
        # Get failed symbols if we're retrying them
        failed_symbols = []
        if retry_failed:
            failed_symbols = queue_service.get_failed_symbols(bar_size)
            # Clear the failed entries so they can be re-queued
            queue_service.clear_failed_for_retry(bar_size)
        
        # Determine ADV threshold based on bar size
        adv_thresholds = {
            "1 min": 500_000,
            "5 mins": 500_000,
            "15 mins": 100_000,
            "1 hour": 100_000,
            "1 day": 50_000,
            "1 week": 50_000
        }
        
        # Get the full symbol list based on collection type
        if collection_type == "full_market":
            all_symbols = await collector.get_all_us_symbols(min_price=1.0, max_price=1000.0)
        elif collection_type == "smart":
            min_adv = adv_thresholds.get(bar_size, 100_000)
            all_symbols = await collector.get_liquid_symbols(min_adv=min_adv)
        else:  # liquid
            all_symbols = await collector.get_liquid_symbols(min_adv=100_000)
        
        # Filter out already completed symbols
        symbols_to_collect = [s for s in all_symbols if s not in completed_symbols]
        
        # Add back failed symbols if retrying
        if retry_failed and failed_symbols:
            # Add failed symbols that aren't already in the list
            for sym in failed_symbols:
                if sym not in symbols_to_collect:
                    symbols_to_collect.append(sym)
        
        if not symbols_to_collect:
            return {
                "success": True,
                "message": "Nothing to resume - all symbols already collected",
                "completed": len(completed_symbols),
                "remaining": 0
            }
        
        # Determine duration based on bar_size (use reasonable defaults)
        duration_map = {
            "1 min": "1 D",
            "5 mins": "1 W",
            "15 mins": "1 M",
            "1 hour": "1 M",
            "1 day": "1 M",
            "1 week": "6 M"
        }
        duration = duration_map.get(bar_size, "1 M")
        
        logger.info(f"Resuming {bar_size} collection: {len(symbols_to_collect)} symbols to collect ({len(completed_symbols)} already done)")
        
        # Start collection for remaining symbols
        result = await collector.start_collection(
            symbols=symbols_to_collect,
            bar_size=bar_size,
            duration=duration,
            use_defaults=False,
            skip_recent=False,  # Don't skip - we've already filtered
            force_refresh=False
        )
        
        if result.get("success"):
            result["resumed"] = True
            result["already_completed"] = len(completed_symbols)
            result["retrying_failed"] = len(failed_symbols) if retry_failed else 0
            result["new_to_collect"] = len(symbols_to_collect)
        
        return result
        
    except Exception as e:
        logger.error(f"Error resuming collection for {bar_size}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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



# ==================== MULTI-TIMEFRAME COLLECTION ====================

@router.post("/multi-timeframe-collection")
async def multi_timeframe_collection(
    bar_size: str = "1 min",
    lookback: str = "30_days",
    collection_type: str = "liquid",
    skip_recent: bool = True,
    recent_days_threshold: int = 7,
    force_refresh: bool = False,
    max_symbols: int = 5000
):
    """
    Start a multi-timeframe data collection with flexible bar sizes and lookback periods.
    
    **Bar Sizes (prioritized for intraday strategies):**
    - `1 min` - Best for scalping, 1-day lookback max efficient
    - `5 mins` - Good for intraday momentum, up to 1-week lookback
    - `15 mins` - Swing trading intraday, up to 1-month lookback  
    - `1 hour` - Swing trading, up to 6-month lookback
    - `1 day` - Position/investment, up to 5-year lookback
    - `1 week` - Long-term investment, up to 5-year lookback
    
    **Lookback Periods:**
    - `1_day` - Last trading day
    - `1_week` - Last 7 days
    - `30_days` - Last month (default)
    - `6_months` - Last 6 months
    - `1_year` - Last year
    - `2_years` - Last 2 years
    - `5_years` - Last 5 years
    
    **Collection Types:**
    - `liquid` - Only liquid stocks (ADV >= 100K), faster
    - `full_market` - All tradeable stocks, slower
    - `smart` - ADV-matched to bar size (recommended)
    
    **IB Data Limitations:**
    - 1 min bars: Max ~365 days history
    - 5 min bars: Max ~730 days history  
    - 1 day bars: Max ~7300 days (20 years) history
    
    ⚠️ LONG-RUNNING: Check /api/ib-collector/queue-progress for real-time progress
    """
    try:
        collector = get_ib_collector()
        
        # Validate bar_size
        valid_bar_sizes = ["1 min", "5 mins", "15 mins", "1 hour", "1 day", "1 week"]
        if bar_size not in valid_bar_sizes:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid bar_size. Choose from: {valid_bar_sizes}"
            )
        
        # Map lookback to IB duration string
        lookback_map = {
            "1_day": "1 D",
            "1_week": "1 W",
            "30_days": "1 M",
            "6_months": "6 M",
            "1_year": "1 Y",
            "2_years": "2 Y",
            "5_years": "5 Y"
        }
        
        if lookback not in lookback_map:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid lookback. Choose from: {list(lookback_map.keys())}"
            )
        
        duration = lookback_map[lookback]
        
        # Determine ADV threshold based on bar size (smart matching)
        adv_thresholds = {
            "1 min": 500_000,    # High liquidity for scalping
            "5 mins": 500_000,   # High liquidity for intraday
            "15 mins": 100_000,  # Medium for swing
            "1 hour": 100_000,   # Medium for swing
            "1 day": 50_000,     # Lower for investment
            "1 week": 50_000     # Lower for investment
        }
        
        # Get symbols based on collection type
        if collection_type == "full_market":
            symbols = await collector.get_all_us_symbols(min_price=1.0, max_price=1000.0)
        elif collection_type == "smart":
            # Use ADV matched to bar size
            min_adv = adv_thresholds.get(bar_size, 100_000)
            symbols = await collector.get_liquid_symbols(min_adv=min_adv)
        else:  # liquid (default)
            symbols = await collector.get_liquid_symbols(min_adv=100_000)
        
        # Limit symbols if specified
        if max_symbols and len(symbols) > max_symbols:
            symbols = symbols[:max_symbols]
        
        logger.info(f"Multi-timeframe collection: {len(symbols)} symbols, {bar_size} bars, {lookback} lookback")
        
        # Start collection
        result = await collector.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=False,
            skip_recent=skip_recent,
            recent_days_threshold=recent_days_threshold,
            force_refresh=force_refresh
        )
        
        # Add metadata to result
        if result.get("success"):
            result["collection_config"] = {
                "bar_size": bar_size,
                "lookback": lookback,
                "duration": duration,
                "collection_type": collection_type,
                "symbols_requested": len(symbols)
            }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting multi-timeframe collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeframe-stats")
async def get_timeframe_stats():
    """
    Get statistics about collected data broken down by timeframe/bar_size.
    
    Returns counts and date ranges for each bar_size in the database.
    """
    try:
        collector = get_ib_collector()
        
        if collector._db is None:
            return {
                "success": False,
                "error": "Database not available"
            }
        
        # Aggregate stats by bar_size
        pipeline = [
            {
                "$group": {
                    "_id": "$bar_size",
                    "symbol_count": {"$addToSet": "$symbol"},
                    "total_bars": {"$sum": 1},
                    "min_date": {"$min": "$date"},
                    "max_date": {"$max": "$date"},
                    "latest_collection": {"$max": "$collected_at"}
                }
            },
            {
                "$project": {
                    "bar_size": "$_id",
                    "unique_symbols": {"$size": "$symbol_count"},
                    "total_bars": 1,
                    "date_range": {
                        "start": "$min_date",
                        "end": "$max_date"
                    },
                    "latest_collection": 1,
                    "_id": 0
                }
            },
            {"$sort": {"bar_size": 1}}
        ]
        
        stats = list(collector._db["ib_historical_data"].aggregate(pipeline))
        
        # Calculate total
        total_bars = sum(s.get("total_bars", 0) for s in stats)
        
        # Get overall unique symbol count
        unique_symbols = collector._db["ib_historical_data"].distinct("symbol")
        
        return {
            "success": True,
            "by_timeframe": stats,
            "total": {
                "unique_symbols": len(unique_symbols),
                "total_bars": total_bars,
                "timeframes_collected": len(stats)
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting timeframe stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collection-presets")
async def get_collection_presets():
    """
    Get recommended collection presets for different trading styles.
    
    Returns pre-configured settings optimized for:
    - Scalping (1min, 1-day lookback)
    - Day Trading (5min, 1-week lookback)
    - Swing Trading (1day, 30-day lookback)
    - Position Trading (1day, 1-year lookback)
    - Long-term Analysis (1day, 5-year lookback)
    """
    presets = [
        {
            "name": "Scalping",
            "description": "High-frequency intraday data for scalp trades",
            "bar_size": "1 min",
            "lookback": "1_day",
            "collection_type": "smart",
            "estimated_symbols": "~500 (ADV >= 500K)",
            "estimated_time": "~25 mins",
            "use_case": "Testing scalp entry/exit timing"
        },
        {
            "name": "Day Trading",
            "description": "Intraday momentum and pattern recognition",
            "bar_size": "5 mins",
            "lookback": "1_week",
            "collection_type": "smart",
            "estimated_symbols": "~500 (ADV >= 500K)",
            "estimated_time": "~25 mins",
            "use_case": "Gap and Go, VWAP strategies"
        },
        {
            "name": "Swing (Intraday)",
            "description": "15-minute bars for multi-day swing analysis",
            "bar_size": "15 mins",
            "lookback": "30_days",
            "collection_type": "smart",
            "estimated_symbols": "~1,500 (ADV >= 100K)",
            "estimated_time": "~1.5 hours",
            "use_case": "Swing entry optimization"
        },
        {
            "name": "Swing (Daily)",
            "description": "Daily bars for swing trade backtesting",
            "bar_size": "1 day",
            "lookback": "30_days",
            "collection_type": "liquid",
            "estimated_symbols": "~1,500",
            "estimated_time": "~1.5 hours",
            "use_case": "Standard swing trade testing"
        },
        {
            "name": "Position Trading",
            "description": "1-year daily history for position trades",
            "bar_size": "1 day",
            "lookback": "1_year",
            "collection_type": "liquid",
            "estimated_symbols": "~1,500",
            "estimated_time": "~1.5 hours",
            "use_case": "Longer-term trend following"
        },
        {
            "name": "Long-term Analysis",
            "description": "5-year daily history for comprehensive backtesting",
            "bar_size": "1 day",
            "lookback": "5_years",
            "collection_type": "liquid",
            "estimated_symbols": "~1,500",
            "estimated_time": "~2 hours",
            "use_case": "Full market cycle analysis"
        },
        {
            "name": "Weekly Investment",
            "description": "Weekly bars for investment-grade backtesting",
            "bar_size": "1 week",
            "lookback": "5_years",
            "collection_type": "full_market",
            "estimated_symbols": "~5,000",
            "estimated_time": "~4 hours",
            "use_case": "Buy-and-hold strategy testing"
        }
    ]
    
    return {
        "success": True,
        "presets": presets,
        "notes": [
            "Times are estimates based on IB Gateway rate limits (~3 sec/symbol)",
            "Smart collection matches ADV to bar size (more liquid for intraday)",
            "Larger lookbacks for intraday bars may hit IB data limits"
        ]
    }
