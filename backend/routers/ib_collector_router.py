"""
IB Historical Data Collector Router
====================================

API endpoints for managing historical data collection from IB Gateway.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional, List
import logging

from services.ib_historical_collector import get_ib_collector, IBHistoricalCollector

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


@router.get("/data-coverage")
async def get_data_coverage():
    """
    Get comprehensive data coverage summary (cached for performance).
    
    Returns:
    - Per-tier coverage (Intraday, Swing, Investment)
    - Per-timeframe coverage (symbols count, total bars)
    - Missing/needed data identification
    - ADV cache status
    
    Use this to understand your data coverage and identify gaps.
    Note: Results are cached for 30 seconds to improve performance.
    """
    import time
    
    # Simple in-memory cache
    cache_key = "_data_coverage_cache"
    cache_time_key = "_data_coverage_cache_time"
    cache_ttl = 15  # 15 seconds cache - fast enough for real-time feedback
    
    # Check cache
    if hasattr(get_data_coverage, cache_key):
        cached_time = getattr(get_data_coverage, cache_time_key, 0)
        if time.time() - cached_time < cache_ttl:
            return getattr(get_data_coverage, cache_key)
    
    try:
        collector = get_ib_collector()
        db = collector._db
        
        if db is None:
            return {"success": False, "error": "Database not initialized"}
        
        data_col = db["ib_historical_data"]
        adv_col = db["symbol_adv_cache"]
        
        # Get ADV cache stats (fast - just count)
        total_adv_symbols = adv_col.count_documents({})
        
        # Define tiers and their timeframes
        tiers = {
            "intraday": {
                "min_adv": 500_000,
                "timeframes": ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
                "description": "500K+ shares/day"
            },
            "swing": {
                "min_adv": 100_000,
                "max_adv": 500_000,
                "timeframes": ["5 mins", "30 mins", "1 hour", "1 day"],
                "description": "100K-500K shares/day"
            },
            "investment": {
                "min_adv": 50_000,
                "max_adv": 100_000,
                "timeframes": ["1 hour", "1 day", "1 week"],
                "description": "50K-100K shares/day"
            }
        }
        
        all_timeframes = ["1 min", "5 mins", "15 mins", "30 mins", "1 hour", "1 day", "1 week"]
        
        # OPTIMIZED: Single aggregation for all timeframes
        pipeline = [
            {"$group": {
                "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
                "bar_count": {"$sum": 1}
            }},
            {"$group": {
                "_id": "$_id.bar_size",
                "symbol_count": {"$sum": 1},
                "total_bars": {"$sum": "$bar_count"}
            }}
        ]
        
        tf_results = {r["_id"]: r for r in data_col.aggregate(pipeline, allowDiskUse=True)}
        
        timeframe_stats = []
        for tf in all_timeframes:
            r = tf_results.get(tf, {})
            timeframe_stats.append({
                "timeframe": tf,
                "symbols": r.get("symbol_count", 0),
                "total_bars": r.get("total_bars", 0)
            })
        
        # OPTIMIZED: Get tier counts in single query each
        tier_stats = []
        total_gaps = 0
        
        for tier_name, tier_config in tiers.items():
            adv_query = {"avg_volume": {"$gte": tier_config["min_adv"]}}
            if "max_adv" in tier_config:
                adv_query["avg_volume"]["$lt"] = tier_config["max_adv"]
            
            tier_symbol_count = adv_col.count_documents(adv_query)
            
            # Get symbols in tier (limit to avoid huge queries)
            tier_symbols = [doc["symbol"] for doc in adv_col.find(adv_query, {"symbol": 1}).limit(5000)]
            
            timeframe_coverage = []
            for tf in tier_config["timeframes"]:
                # Count distinct symbols with data for this timeframe
                symbols_with_data_count = len(data_col.distinct("symbol", {
                    "symbol": {"$in": tier_symbols},
                    "bar_size": tf
                }))
                
                coverage_pct = (symbols_with_data_count / tier_symbol_count * 100) if tier_symbol_count > 0 else 0
                missing = tier_symbol_count - symbols_with_data_count
                
                if missing > 0:
                    total_gaps += 1
                
                timeframe_coverage.append({
                    "timeframe": tf,
                    "symbols_with_data": symbols_with_data_count,
                    "symbols_needed": tier_symbol_count,
                    "coverage_pct": round(coverage_pct, 1),
                    "missing": missing,
                    "needs_fill": missing > 0
                })
            
            tier_stats.append({
                "tier": tier_name,
                "description": tier_config["description"],
                "total_symbols": tier_symbol_count,
                "timeframes": timeframe_coverage
            })
        
        result = {
            "success": True,
            "adv_cache": {
                "total_symbols": total_adv_symbols,
                "status": "ready" if total_adv_symbols > 0 else "empty"
            },
            "by_timeframe": timeframe_stats,
            "by_tier": tier_stats,
            "total_gaps": total_gaps
        }
        
        # Cache the result
        setattr(get_data_coverage, cache_key, result)
        setattr(get_data_coverage, cache_time_key, time.time())
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting data coverage: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fill-gaps")
async def fill_gaps(
    tier_filter: Optional[str] = None,
    max_symbols: int = None,
    use_max_lookback: bool = True
):
    """
    Smart Gap Filler - Automatically collects ONLY missing data with MAXIMUM lookback.
    
    Analyzes the current data coverage and starts a collection job
    targeting only the symbols/timeframes that have gaps.
    
    By default, uses maximum IB lookback per timeframe to get the most data possible:
    - 1 min: 1 week (~5 trading days of minute bars)
    - 5 mins: 1 month (~25 trading days)
    - 15 mins: 3 months
    - 30 mins: 6 months
    - 1 hour: 1 year
    - 1 day: 8 years
    - 1 week: 20 years
    
    - **tier_filter**: Limit to specific tier ("intraday", "swing", "investment", or None for all)
    - **max_symbols**: Maximum symbols to process (None = all symbols with gaps)
    - **use_max_lookback**: Use maximum IB lookback per timeframe (default True)
    
    Returns:
    - Summary of gaps found
    - Collection job info for each tier/timeframe combination
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        
        if db is None:
            return {"success": False, "error": "Database not initialized"}
        
        adv_col = db["symbol_adv_cache"]  # Fixed: match get_adv_cache_stats()
        data_col = db["ib_historical_data"]  # Fixed: matches COLLECTION_NAME
        
        # Define tiers and their timeframes (same as coverage endpoint)
        tiers = {
            "intraday": {
                "min_adv": 500_000,
                "timeframes": ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
                "description": "500K+ shares/day"
            },
            "swing": {
                "min_adv": 100_000,
                "max_adv": 500_000,
                "timeframes": ["5 mins", "30 mins", "1 hour", "1 day"],
                "description": "100K-500K shares/day"
            },
            "investment": {
                "min_adv": 50_000,
                "max_adv": 100_000,
                "timeframes": ["1 hour", "1 day", "1 week"],
                "description": "50K-100K shares/day"
            }
        }
        
        # Filter tiers if specified
        if tier_filter and tier_filter in tiers:
            tiers = {tier_filter: tiers[tier_filter]}
        
        gaps_found = []
        symbols_to_collect = {}  # {tier: {timeframe: [symbols]}}
        
        for tier_name, tier_config in tiers.items():
            # Get symbols in this ADV tier
            adv_query = {"avg_volume": {"$gte": tier_config["min_adv"]}}
            if "max_adv" in tier_config:
                adv_query["avg_volume"]["$lt"] = tier_config["max_adv"]
            
            # Get all symbols in tier, or limit if specified
            cursor = adv_col.find(adv_query, {"symbol": 1})
            if max_symbols:
                cursor = cursor.limit(max_symbols)
            tier_symbols = [doc["symbol"] for doc in cursor]
            
            if not tier_symbols:
                continue
            
            symbols_to_collect[tier_name] = {}
            
            for tf in tier_config["timeframes"]:
                # Find symbols that DON'T have data for this timeframe
                symbols_with_data = set(data_col.distinct("symbol", {
                    "symbol": {"$in": tier_symbols},
                    "bar_size": tf
                }))
                
                missing_symbols = [s for s in tier_symbols if s not in symbols_with_data]
                
                if missing_symbols:
                    # If max_symbols set, limit per timeframe; otherwise collect all
                    symbols_to_queue = missing_symbols[:max_symbols] if max_symbols else missing_symbols
                    symbols_to_collect[tier_name][tf] = symbols_to_queue
                    gaps_found.append({
                        "tier": tier_name,
                        "timeframe": tf,
                        "missing_count": len(missing_symbols),
                        "will_collect": len(symbols_to_queue)
                    })
        
        if not gaps_found:
            return {
                "success": True,
                "message": "No gaps found! Your data coverage is complete.",
                "gaps_found": 0,
                "jobs_started": 0
            }
        
        # Start collection for each gap
        # We'll use the per-stock collection approach for efficiency
        total_symbols = set()
        for tier_name, timeframes in symbols_to_collect.items():
            for tf, symbols in timeframes.items():
                total_symbols.update(symbols)
        
        # Start a per-stock collection with ONLY the missing symbols and MAX lookback
        job_result = await collector.run_per_stock_collection(
            skip_recent=False,  # We already filtered to missing only
            max_symbols=len(total_symbols) if max_symbols else None,
            specific_symbols=list(total_symbols),
            use_max_lookback=use_max_lookback  # Use maximum IB lookback per timeframe
        )
        
        return {
            "success": True,
            "message": f"Started filling {len(gaps_found)} gaps across {len(total_symbols)} symbols",
            "gaps_found": len(gaps_found),
            "gap_details": gaps_found,
            "total_unique_symbols": len(total_symbols),
            "collection_job": job_result
        }
        
    except Exception as e:
        logger.error(f"Error filling gaps: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/incremental-update")
async def incremental_update(
    max_symbols: int = None,
    max_days_lookback: int = 7
):
    """
    Smart Incremental Update - Only fetch NEW bars since last collection.
    
    This is the preferred endpoint for nightly/routine updates after initial
    data collection is complete. It:
    
    1. Checks the latest bar date for each symbol/timeframe in the database
    2. Calculates how many days of new data are needed
    3. Only fetches the missing days (not the full historical lookback)
    
    Example: If you have daily data for AAPL through March 15, and today is March 17,
    it will only fetch 2 days of data (March 16-17), not 30 days.
    
    - **max_symbols**: Limit update to this many symbols (None = all)
    - **max_days_lookback**: Maximum days to look back for any symbol (default 7, prevents huge fetches)
    
    Returns:
    - Analysis of what needs updating
    - Collection job for incremental data
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        
        if db is None:
            return {"success": False, "error": "Database not initialized"}
        
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service(db)
        
        # Analyze what incremental data is needed
        analysis = collector.calculate_incremental_needs()
        if not analysis.get("success"):
            return analysis
        
        needs_update = analysis.get("needs_update", {})
        
        if not needs_update:
            return {
                "success": True,
                "message": "All data is up to date! Nothing to fetch.",
                "summary": analysis.get("summary", {}),
                "total_symbols_in_db": analysis.get("total_symbols_in_db", 0)
            }
        
        # Limit symbols if requested
        symbols_to_update = list(needs_update.keys())
        if max_symbols and len(symbols_to_update) > max_symbols:
            symbols_to_update = symbols_to_update[:max_symbols]
        
        # Queue incremental requests
        total_queued = 0
        timeframe_counts = {}
        
        for symbol in symbols_to_update:
            symbol_needs = needs_update[symbol]
            for bar_size, days_needed in symbol_needs.items():
                # Cap at max_days_lookback
                actual_days = min(days_needed, max_days_lookback)
                
                # Get appropriate duration string
                duration = collector.get_safe_duration(bar_size, actual_days)
                
                # Queue the request
                queue_service.create_request(
                    symbol=symbol,
                    bar_size=bar_size,
                    duration=duration
                )
                total_queued += 1
                
                # Track counts
                if bar_size not in timeframe_counts:
                    timeframe_counts[bar_size] = 0
                timeframe_counts[bar_size] += 1
        
        # Start monitoring if we have items
        if total_queued > 0:
            await collector.resume_monitoring()
        
        # Calculate estimated time
        estimated_seconds = total_queued * collector.REQUEST_DELAY_SECONDS
        estimated_minutes = round(estimated_seconds / 60, 1)
        
        return {
            "success": True,
            "message": f"Incremental update started: {total_queued} requests for {len(symbols_to_update)} symbols",
            "analysis_summary": analysis.get("summary", {}),
            "symbols_updated": len(symbols_to_update),
            "total_requests": total_queued,
            "timeframe_breakdown": timeframe_counts,
            "max_days_lookback": max_days_lookback,
            "estimated_minutes": estimated_minutes,
            "note": "Only fetching NEW data since last collection - not re-fetching historical data"
        }
        
    except Exception as e:
        logger.error(f"Error in incremental update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/incremental-analysis")
async def get_incremental_analysis():
    """
    Preview what incremental data would be fetched.
    
    Use this to see what the incremental-update endpoint would collect
    without actually starting a collection.
    """
    try:
        collector = get_ib_collector()
        return collector.calculate_incremental_needs()
    except Exception as e:
        logger.error(f"Error in incremental analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gap-analysis")
async def get_gap_analysis(tier_filter: Optional[str] = None):
    """
    Preview what gaps exist without starting a collection.
    
    Use this to see what the fill-gaps endpoint would collect.
    
    - **tier_filter**: Limit to specific tier ("intraday", "swing", "investment", or None for all)
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        
        if db is None:
            return {"success": False, "error": "Database not initialized"}
        
        adv_col = db["symbol_adv_cache"]  # Fixed: match get_adv_cache_stats()
        data_col = db["ib_historical_data"]  # Fixed: matches COLLECTION_NAME
        
        # Define tiers
        tiers = {
            "intraday": {
                "min_adv": 500_000,
                "timeframes": ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
                "description": "500K+ shares/day"
            },
            "swing": {
                "min_adv": 100_000,
                "max_adv": 500_000,
                "timeframes": ["5 mins", "30 mins", "1 hour", "1 day"],
                "description": "100K-500K shares/day"
            },
            "investment": {
                "min_adv": 50_000,
                "max_adv": 100_000,
                "timeframes": ["1 hour", "1 day", "1 week"],
                "description": "50K-100K shares/day"
            }
        }
        
        if tier_filter and tier_filter in tiers:
            tiers = {tier_filter: tiers[tier_filter]}
        
        gap_analysis = []
        total_missing = 0
        
        for tier_name, tier_config in tiers.items():
            adv_query = {"avg_volume": {"$gte": tier_config["min_adv"]}}
            if "max_adv" in tier_config:
                adv_query["avg_volume"]["$lt"] = tier_config["max_adv"]
            
            tier_symbols = [doc["symbol"] for doc in adv_col.find(adv_query, {"symbol": 1})]
            tier_total = len(tier_symbols)
            
            if tier_total == 0:
                continue
            
            tier_gaps = {
                "tier": tier_name,
                "description": tier_config["description"],
                "total_symbols": tier_total,
                "timeframes": []
            }
            
            for tf in tier_config["timeframes"]:
                symbols_with_data = set(data_col.distinct("symbol", {
                    "symbol": {"$in": tier_symbols},
                    "bar_size": tf
                }))
                
                missing_count = tier_total - len(symbols_with_data)
                coverage_pct = (len(symbols_with_data) / tier_total * 100) if tier_total > 0 else 0
                
                tier_gaps["timeframes"].append({
                    "timeframe": tf,
                    "has_data": len(symbols_with_data),
                    "missing": missing_count,
                    "coverage_pct": round(coverage_pct, 1),
                    "needs_fill": missing_count > 0
                })
                
                total_missing += missing_count
            
            gap_analysis.append(tier_gaps)
        
        return {
            "success": True,
            "total_gaps": total_missing,
            "needs_fill": total_missing > 0,
            "estimated_time_minutes": total_missing * 2,  # ~2 seconds per request
            "analysis": gap_analysis
        }
        
    except Exception as e:
        logger.error(f"Error analyzing gaps: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/adv-distribution")
async def get_adv_distribution():
    """
    Get the distribution of symbols by ADV (Average Daily Volume).
    
    Useful for understanding how many symbols fall into each liquidity tier.
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        
        if db is None:
            return {"success": False, "error": "Database not initialized"}
        
        adv_col = db["symbol_adv_cache"]
        
        # Count by ADV ranges
        distribution = {
            "1M+": adv_col.count_documents({"avg_volume": {"$gte": 1_000_000}}),
            "500K-1M": adv_col.count_documents({"avg_volume": {"$gte": 500_000, "$lt": 1_000_000}}),
            "250K-500K": adv_col.count_documents({"avg_volume": {"$gte": 250_000, "$lt": 500_000}}),
            "100K-250K": adv_col.count_documents({"avg_volume": {"$gte": 100_000, "$lt": 250_000}}),
            "50K-100K": adv_col.count_documents({"avg_volume": {"$gte": 50_000, "$lt": 100_000}}),
            "10K-50K": adv_col.count_documents({"avg_volume": {"$gte": 10_000, "$lt": 50_000}}),
            "<10K": adv_col.count_documents({"avg_volume": {"$lt": 10_000}}),
        }
        
        # Get total
        total = adv_col.count_documents({})
        
        # Get top 20 by ADV
        top_symbols = list(adv_col.find({}, {"symbol": 1, "avg_volume": 1, "_id": 0}).sort("avg_volume", -1).limit(20))
        
        # Get sample of 500K+ symbols
        high_volume = list(adv_col.find({"avg_volume": {"$gte": 500_000}}, {"symbol": 1, "avg_volume": 1, "_id": 0}).sort("avg_volume", -1).limit(50))
        
        return {
            "success": True,
            "total_symbols": total,
            "distribution": distribution,
            "tier_summary": {
                "intraday_500k_plus": distribution["1M+"] + distribution["500K-1M"],
                "swing_100k_500k": distribution["250K-500K"] + distribution["100K-250K"],
                "investment_50k_100k": distribution["50K-100K"]
            },
            "top_20_by_adv": top_symbols,
            "sample_500k_plus": high_volume
        }
        
    except Exception as e:
        logger.error(f"Error getting ADV distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild-adv-from-ib")
async def rebuild_adv_from_ib():
    """
    Rebuild the ADV cache using ACTUAL IB historical data.
    
    This recalculates average daily volume for all symbols using the
    daily bar data from IB Gateway (consolidated tape volume, not IEX).
    
    This fixes the issue where Alpaca IEX data underreports volume by ~95%.
    
    Returns:
    - New tier counts with accurate ADV data
    - Distribution breakdown
    """
    try:
        collector = get_ib_collector()
        result = await collector.rebuild_adv_from_ib_data()
        return result
    except Exception as e:
        logger.error(f"Error rebuilding ADV: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/failure-analysis")
async def get_failure_analysis():
    """
    Analyze failures in the historical data queue.
    
    Breaks down failures by:
    - Status type (timeout, rate_limited, no_data, error)
    - Timeframe
    - Common error messages
    
    Helps distinguish between:
    - True failures (errors that need fixing)
    - No data (symbol/timeframe has no data - expected for some cases)
    - Timeouts (network issues - retry later)
    - Rate limits (IB pacing - retry later)
    """
    try:
        collector = get_ib_collector()
        db = collector._db
        
        if db is None:
            return {"success": False, "error": "Database not initialized"}
        
        from services.historical_data_queue_service import get_historical_data_queue_service
        service = get_historical_data_queue_service()
        
        # Aggregate by result_status
        pipeline = [
            {"$match": {"status": {"$in": ["completed", "failed"]}}},
            {"$group": {
                "_id": {
                    "status": "$status",
                    "result_status": {"$ifNull": ["$result_status", "$status"]}
                },
                "count": {"$sum": 1}
            }}
        ]
        
        status_counts = list(service.collection.aggregate(pipeline))
        
        # Organize results
        breakdown = {
            "success": 0,
            "no_data": 0,
            "timeout": 0,
            "rate_limited": 0,
            "error": 0,
            "unknown": 0
        }
        
        for item in status_counts:
            result_status = item["_id"].get("result_status", "unknown")
            internal_status = item["_id"].get("status", "unknown")
            count = item["count"]
            
            if result_status in breakdown:
                breakdown[result_status] += count
            elif internal_status == "completed":
                breakdown["success"] += count
            elif internal_status == "failed":
                breakdown["error"] += count
            else:
                breakdown["unknown"] += count
        
        # Get sample of actual errors (not timeouts or no_data)
        error_samples = list(service.collection.find(
            {"status": "failed", "result_status": {"$nin": ["timeout", "rate_limited", "no_data"]}},
            {"symbol": 1, "bar_size": 1, "error": 1, "_id": 0}
        ).limit(10))
        
        # Get symbols with no data (for reference)
        no_data_samples = list(service.collection.find(
            {"result_status": "no_data"},
            {"symbol": 1, "bar_size": 1, "_id": 0}
        ).limit(10))
        
        return {
            "success": True,
            "breakdown": breakdown,
            "summary": {
                "true_failures": breakdown["error"],
                "retry_needed": breakdown["timeout"] + breakdown["rate_limited"],
                "no_data_available": breakdown["no_data"],
                "successful": breakdown["success"]
            },
            "explanation": {
                "success": "Data fetched and stored successfully",
                "no_data": "Symbol/timeframe has no data available (not a failure)",
                "timeout": "Network timeout - should be retried",
                "rate_limited": "IB rate limit hit - will retry automatically",
                "error": "Actual errors that may need investigation"
            },
            "error_samples": error_samples,
            "no_data_samples": no_data_samples
        }
        
    except Exception as e:
        logger.error(f"Error analyzing failures: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry-failed")
async def retry_failed_requests(
    max_retries: int = 100,
    status_filter: Optional[str] = None
):
    """
    Re-queue failed requests for retry.
    
    This resets failed requests back to 'pending' status so they can be
    processed again by the IB Data Pusher.
    
    - **max_retries**: Maximum number of failed requests to retry (default 100)
    - **status_filter**: Only retry specific failure types (timeout, rate_limited, error)
    
    Returns:
    - Count of requests reset for retry
    """
    try:
        from services.historical_data_queue_service import get_historical_data_queue_service
        service = get_historical_data_queue_service()
        
        # Build query for failed requests
        query = {"status": "failed"}
        
        if status_filter:
            query["result_status"] = status_filter
        
        # Find failed requests
        failed_requests = list(service.collection.find(
            query,
            {"request_id": 1, "symbol": 1, "bar_size": 1, "result_status": 1}
        ).limit(max_retries))
        
        if not failed_requests:
            return {
                "success": True,
                "message": "No failed requests to retry",
                "retried": 0
            }
        
        # Reset them to pending
        request_ids = [r["request_id"] for r in failed_requests]
        
        from datetime import datetime, timezone
        result = service.collection.update_many(
            {"request_id": {"$in": request_ids}},
            {"$set": {
                "status": "pending",
                "error": None,
                "result_status": None,
                "retry_at": datetime.now(timezone.utc).isoformat(),
                "retried_from": "manual_retry"
            }}
        )
        
        # Resume monitoring to process them
        collector = get_ib_collector()
        await collector.resume_monitoring()
        
        return {
            "success": True,
            "message": f"Reset {result.modified_count} failed requests for retry",
            "retried": result.modified_count,
            "sample": [{"symbol": r["symbol"], "bar_size": r.get("bar_size")} for r in failed_requests[:5]]
        }
        
    except Exception as e:
        logger.error(f"Error retrying failed requests: {e}")
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


@router.post("/per-stock-collection")
async def per_stock_collection(
    lookback_days: int = 30,
    skip_recent: bool = True,
    recent_days_threshold: int = 7,
    max_symbols: int = None
):
    """
    Start per-stock multi-timeframe collection.
    
    Collects ALL applicable timeframes for each stock before moving to the next:
    - TSLA (500K+ ADV): Gets 1min, 5min, 15min, 1hr, 1day
    - Then AAPL: Gets 1min, 5min, 15min, 1hr, 1day
    - Lower volume stocks get fewer timeframes based on their tier
    
    **Timeframes by ADV Tier:**
    - **Intraday (500K+ shares/day)**: 1 min, 5 min, 15 min, 1 hr, 1 day
    - **Swing (100K+ shares/day)**: 5 min, 30 min, 1 hr, 1 day
    - **Investment (50K+ shares/day)**: 1 hr, 1 day, 1 week
    
    Args:
        lookback_days: How many days of history to fetch (default 30)
        skip_recent: Skip symbols collected within recent_days_threshold (default True)
        recent_days_threshold: Days threshold for "recent" data (default 7)
        max_symbols: Limit number of symbols to process (default None = all)
    
    Returns:
        Collection job info with queue details
    
    Example:
        POST /api/ib-collector/per-stock-collection?lookback_days=30&max_symbols=100
    """
    try:
        collector = get_ib_collector()  # Use initialized singleton
        result = await collector.run_per_stock_collection(
            lookback_days=lookback_days,
            skip_recent=skip_recent,
            recent_days_threshold=recent_days_threshold,
            max_symbols=max_symbols
        )
        return result
    except Exception as e:
        logger.error(f"Error starting per-stock collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== MULTI-TIMEFRAME COLLECTION ====================

@router.post("/multi-timeframe-collection")
async def multi_timeframe_collection(
    lookback_days: int = 30,
    skip_recent: bool = True,
    recent_days_threshold: int = 7,
    max_symbols: int = None
):
    """
    Start multi-timeframe data collection using per-stock approach.
    
    **NEW: Per-Stock Collection**
    Each stock gets ALL its applicable timeframes collected before moving to the next:
    - TSLA (500K+ ADV): 1min → 5min → 15min → 1hr → 1day ✓ then next stock
    - AAPL (500K+ ADV): 1min → 5min → 15min → 1hr → 1day ✓ then next stock
    - XYZ (100K ADV): 5min → 30min → 1hr → 1day ✓ then next stock
    
    **Timeframes by ADV Tier:**
    - **Intraday (500K+ shares/day)**: 1 min, 5 min, 15 min, 1 hr, 1 day
    - **Swing (100K+ shares/day)**: 5 min, 30 min, 1 hr, 1 day
    - **Investment (50K+ shares/day)**: 1 hr, 1 day, 1 week
    
    **Args:**
    - `lookback_days`: How many days of history to fetch (default 30)
    - `skip_recent`: Skip symbols collected within recent_days_threshold (default True)
    - `recent_days_threshold`: Days threshold for "recent" data (default 7)
    - `max_symbols`: Limit number of symbols (default None = all)
    
    ⚠️ LONG-RUNNING: Check /api/ib-collector/queue-progress for real-time progress
    """
    try:
        collector = get_ib_collector()
        
        # Use the new per-stock collection approach
        result = await collector.run_per_stock_collection(
            lookback_days=lookback_days,
            skip_recent=skip_recent,
            recent_days_threshold=recent_days_threshold,
            max_symbols=max_symbols
        )
        
        return result
        
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
