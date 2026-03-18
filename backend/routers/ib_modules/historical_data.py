"""
Historical Data Endpoints for IB Router

Handles all historical data collection, storage, and index optimization.
These endpoints enable the IB Data Pusher to fulfill historical data requests.
"""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
from pymongo import UpdateOne
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IB Historical Data"])

# Service singleton
_historical_data_service = None


def _get_historical_data_service():
    """Get the historical data queue service, initializing if needed"""
    global _historical_data_service
    if _historical_data_service is None:
        try:
            from services.historical_data_queue_service import get_historical_data_queue_service
            _historical_data_service = get_historical_data_queue_service()
        except Exception as e:
            logger.warning(f"Historical data queue service not available: {e}")
    return _historical_data_service


@router.get("/historical-data/pending")
async def get_pending_historical_data_requests():
    """
    Get pending historical data requests for the IB Data Pusher to fulfill.
    Called by the local IB Data Pusher to check for work.
    """
    service = _get_historical_data_service()
    if not service:
        return {"success": True, "requests": []}
    
    try:
        requests = service.get_pending_requests(limit=10)
        return {"success": True, "requests": requests}
    except Exception as e:
        logger.error(f"Error getting pending historical data requests: {e}")
        return {"success": False, "requests": [], "error": str(e)}


@router.post("/historical-data/claim/{request_id}")
async def claim_historical_data_request(request_id: str):
    """
    Claim a historical data request (prevents duplicate processing).
    Called by IB Data Pusher before fetching data.
    """
    service = _get_historical_data_service()
    if not service:
        raise HTTPException(status_code=503, detail="Historical data service not available")
    
    try:
        success = service.claim_request(request_id)
        if success:
            return {"success": True, "message": f"Request {request_id} claimed"}
        else:
            raise HTTPException(status_code=409, detail=f"Request {request_id} already claimed or completed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming historical data request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/historical-data/result")
async def report_historical_data_result(request: Request):
    """
    Report the result of a historical data fetch.
    Called by IB Data Pusher after fetching data from IB Gateway.
    Accepts JSON body with: request_id, symbol, success, data, error, fetched_at
    
    This endpoint now IMMEDIATELY stores data to the main collection using
    bulk_write for optimal performance with large datasets.
    """
    service = _get_historical_data_service()
    if not service:
        raise HTTPException(status_code=503, detail="Historical data service not available")
    
    try:
        # Parse JSON body
        body = await request.json()
        request_id = body.get("request_id")
        symbol = body.get("symbol")
        success = body.get("success", False)
        data = body.get("data")
        error = body.get("error")
        bar_size = body.get("bar_size")
        status = body.get("status")  # New: detailed status (success, no_data, timeout, etc.)
        bar_count = body.get("bar_count", 0)
        
        if not request_id:
            raise HTTPException(status_code=400, detail="request_id is required")
        
        # If bar_size not provided in result, look it up from the original request
        if not bar_size:
            try:
                original_request = service.collection.find_one({"request_id": request_id})
                if original_request:
                    bar_size = original_request.get("bar_size", "1 day")
                    logger.info(f"Got bar_size '{bar_size}' from original request for {symbol}")
                else:
                    bar_size = "1 day"
            except Exception as e:
                logger.warning(f"Could not look up bar_size for {request_id}: {e}")
                bar_size = "1 day"
        
        # Store in queue (for tracking) - don't store data in queue to save space
        service.complete_request(
            request_id=request_id,
            success=success,
            data=None,  # Don't store raw data in queue - saves space and time
            error=error,
            status=status,
            bar_count=bar_count
        )
        
        # IMMEDIATELY store to main collection using BULK WRITE for performance
        bars_stored = 0
        if success and data:
            try:
                from services.ib_historical_collector import get_ib_collector
                collector = get_ib_collector()
                
                if collector._data_col is not None:
                    now = datetime.now(timezone.utc).isoformat()
                    
                    # Build bulk operations list
                    bulk_operations = []
                    for bar in data:
                        date_val = bar.get("date") or bar.get("time")
                        if not date_val:
                            continue
                        
                        bulk_operations.append(
                            UpdateOne(
                                {
                                    "symbol": symbol,
                                    "bar_size": bar_size,
                                    "date": date_val
                                },
                                {
                                    "$set": {
                                        "symbol": symbol,
                                        "bar_size": bar_size,
                                        "date": date_val,
                                        "open": bar.get("open"),
                                        "high": bar.get("high"),
                                        "low": bar.get("low"),
                                        "close": bar.get("close"),
                                        "volume": bar.get("volume"),
                                        "collected_at": now
                                    }
                                },
                                upsert=True
                            )
                        )
                    
                    # Execute bulk write in single operation
                    if bulk_operations:
                        result = collector._data_col.bulk_write(bulk_operations, ordered=False)
                        bars_stored = result.upserted_count + result.modified_count
                        logger.info(f"Bulk stored {bars_stored} bars for {symbol} (upserted: {result.upserted_count}, modified: {result.modified_count})")
                        
            except Exception as e:
                logger.warning(f"Bulk write error for {symbol}: {e}")
        
        return {
            "success": True, 
            "message": f"Result recorded for {request_id}",
            "bars_stored": bars_stored
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reporting historical data result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/historical-data/batch-result")
async def report_historical_data_batch_result(request: Request):
    """
    Report multiple historical data results in one call.
    Uses bulk_write for optimal MongoDB Atlas performance with large datasets.
    """
    service = _get_historical_data_service()
    if not service:
        raise HTTPException(status_code=503, detail="Historical data service not available")
    
    try:
        body = await request.json()
        results = body.get("results", [])
        
        if not results:
            return {"success": True, "processed": 0}
        
        from services.ib_historical_collector import get_ib_collector
        collector = get_ib_collector()
        
        processed = 0
        bars_stored = 0
        
        # Collect all bulk operations across all results
        all_bulk_operations = []
        now = datetime.now(timezone.utc).isoformat()
        
        for result in results:
            try:
                request_id = result.get("request_id")
                symbol = result.get("symbol")
                bar_size = result.get("bar_size", "1 day")
                success = result.get("success", False)
                data = result.get("data", [])
                error = result.get("error")
                status = result.get("status", "success" if success else "error")
                bar_count = result.get("bar_count", 0)
                
                # Update queue status - don't store raw data to save space
                service.complete_request(
                    request_id=request_id,
                    success=success,
                    data=None,  # Don't store raw data in queue
                    error=error,
                    status=status,
                    bar_count=bar_count
                )
                
                # Build bulk operations for bars
                if success and data and collector._data_col is not None:
                    for bar in data:
                        date_val = bar.get("date") or bar.get("time")
                        if not date_val:
                            continue
                        
                        all_bulk_operations.append(
                            UpdateOne(
                                {
                                    "symbol": symbol,
                                    "bar_size": bar_size,
                                    "date": date_val
                                },
                                {
                                    "$set": {
                                        "symbol": symbol,
                                        "bar_size": bar_size,
                                        "date": date_val,
                                        "open": bar.get("open"),
                                        "high": bar.get("high"),
                                        "low": bar.get("low"),
                                        "close": bar.get("close"),
                                        "volume": bar.get("volume"),
                                        "collected_at": now
                                    }
                                },
                                upsert=True
                            )
                        )
                
                processed += 1
                
            except Exception as e:
                logger.warning(f"Error processing batch result: {e}")
                continue
        
        # Execute all bulk operations in one call
        if all_bulk_operations and collector._data_col is not None:
            try:
                result = collector._data_col.bulk_write(all_bulk_operations, ordered=False)
                bars_stored = result.upserted_count + result.modified_count
                logger.info(f"Batch bulk stored {bars_stored} bars (upserted: {result.upserted_count}, modified: {result.modified_count})")
            except Exception as e:
                logger.warning(f"Batch bulk write error: {e}")
        
        return {
            "success": True,
            "processed": processed,
            "bars_stored": bars_stored
        }
        
    except Exception as e:
        logger.error(f"Error in batch result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/historical-data/optimize-indexes")
async def optimize_historical_data_indexes():
    """
    Create/verify optimal indexes for historical data collections.
    
    This endpoint ensures the MongoDB collections have the right indexes
    for efficient writes and queries. Should be run once before large-scale
    data collection to ensure optimal performance.
    
    Indexes created:
    - ib_historical_data: compound index on (symbol, bar_size, date) for fast upserts
    - historical_data_requests: indexes for queue operations
    """
    try:
        from services.ib_historical_collector import get_ib_collector
        collector = get_ib_collector()
        
        if collector._db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        results = {
            "indexes_created": [],
            "indexes_verified": [],
            "errors": []
        }
        
        # Optimize ib_historical_data collection
        data_col = collector._db["ib_historical_data"]
        try:
            # Primary compound index for fast upserts - this is the most critical index
            data_col.create_index(
                [("symbol", 1), ("bar_size", 1), ("date", 1)], 
                unique=True,
                name="symbol_barsize_date_unique",
                background=True  # Don't block other operations
            )
            results["indexes_created"].append("ib_historical_data: symbol_barsize_date_unique")
        except Exception as e:
            if "already exists" in str(e).lower():
                results["indexes_verified"].append("ib_historical_data: symbol_barsize_date_unique")
            else:
                results["errors"].append(f"ib_historical_data compound index: {str(e)}")
        
        try:
            # Secondary index for queries by symbol only
            data_col.create_index(
                [("symbol", 1)],
                name="symbol_only",
                background=True
            )
            results["indexes_created"].append("ib_historical_data: symbol_only")
        except Exception as e:
            if "already exists" in str(e).lower():
                results["indexes_verified"].append("ib_historical_data: symbol_only")
            else:
                results["errors"].append(f"ib_historical_data symbol index: {str(e)}")
        
        try:
            # Index for queries by bar_size
            data_col.create_index(
                [("bar_size", 1)],
                name="bar_size_only",
                background=True
            )
            results["indexes_created"].append("ib_historical_data: bar_size_only")
        except Exception as e:
            if "already exists" in str(e).lower():
                results["indexes_verified"].append("ib_historical_data: bar_size_only")
            else:
                results["errors"].append(f"ib_historical_data bar_size index: {str(e)}")
        
        try:
            # Index for time-based queries
            data_col.create_index(
                [("collected_at", -1)],
                name="collected_at_desc",
                background=True
            )
            results["indexes_created"].append("ib_historical_data: collected_at_desc")
        except Exception as e:
            if "already exists" in str(e).lower():
                results["indexes_verified"].append("ib_historical_data: collected_at_desc")
            else:
                results["errors"].append(f"ib_historical_data collected_at index: {str(e)}")
        
        # Optimize historical_data_requests queue collection
        queue_col = collector._db["historical_data_requests"]
        try:
            queue_col.create_index(
                [("status", 1), ("created_at", 1)],
                name="status_created",
                background=True
            )
            results["indexes_created"].append("historical_data_requests: status_created")
        except Exception as e:
            if "already exists" in str(e).lower():
                results["indexes_verified"].append("historical_data_requests: status_created")
            else:
                results["errors"].append(f"queue status_created index: {str(e)}")
        
        try:
            queue_col.create_index(
                [("symbol", 1), ("bar_size", 1), ("status", 1)],
                name="symbol_barsize_status",
                background=True
            )
            results["indexes_created"].append("historical_data_requests: symbol_barsize_status")
        except Exception as e:
            if "already exists" in str(e).lower():
                results["indexes_verified"].append("historical_data_requests: symbol_barsize_status")
            else:
                results["errors"].append(f"queue symbol_barsize_status index: {str(e)}")
        
        # Get collection stats
        try:
            data_stats = collector._db.command("collStats", "ib_historical_data")
            queue_stats = collector._db.command("collStats", "historical_data_requests")
            
            results["collection_stats"] = {
                "ib_historical_data": {
                    "count": data_stats.get("count", 0),
                    "size_mb": round(data_stats.get("size", 0) / (1024 * 1024), 2),
                    "index_count": data_stats.get("nindexes", 0),
                    "index_size_mb": round(data_stats.get("totalIndexSize", 0) / (1024 * 1024), 2)
                },
                "historical_data_requests": {
                    "count": queue_stats.get("count", 0),
                    "size_mb": round(queue_stats.get("size", 0) / (1024 * 1024), 2),
                    "index_count": queue_stats.get("nindexes", 0)
                }
            }
        except Exception as e:
            results["collection_stats"] = {"error": str(e)}
        
        return {
            "success": True,
            "message": "Index optimization complete",
            **results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error optimizing indexes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mongodb/diagnostics")
async def get_mongodb_diagnostics():
    """
    Get comprehensive MongoDB Atlas diagnostics and recommendations.
    
    This endpoint provides:
    - Connection settings analysis
    - Collection statistics
    - Index efficiency analysis
    - Performance recommendations for Atlas configuration
    """
    try:
        from services.ib_historical_collector import get_ib_collector
        collector = get_ib_collector()
        
        if collector._db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        
        diagnostics = {
            "connection": {},
            "collections": {},
            "indexes": {},
            "recommendations": []
        }
        
        # Get server info and connection details
        try:
            server_info = collector._db.client.server_info()
            diagnostics["connection"] = {
                "mongodb_version": server_info.get("version", "unknown"),
                "is_atlas": "mongodb.net" in str(collector._db.client.address) if collector._db.client.address else False,
                "max_pool_size": collector._db.client.options.pool_options.max_pool_size,
                "min_pool_size": collector._db.client.options.pool_options.min_pool_size,
                "server_selection_timeout_ms": collector._db.client.options.server_selection_timeout * 1000,
                "connect_timeout_ms": collector._db.client.options.connect_timeout * 1000 if collector._db.client.options.connect_timeout else None,
                "socket_timeout_ms": collector._db.client.options.socket_timeout * 1000 if collector._db.client.options.socket_timeout else None,
            }
        except Exception as e:
            diagnostics["connection"]["error"] = str(e)
        
        # Get detailed collection stats
        collections_to_check = ["ib_historical_data", "historical_data_requests", "symbol_adv_cache", "historical_bars"]
        
        for col_name in collections_to_check:
            try:
                if col_name in collector._db.list_collection_names():
                    stats = collector._db.command("collStats", col_name)
                    col = collector._db[col_name]
                    
                    # Get index info
                    indexes = list(col.list_indexes())
                    index_info = []
                    for idx in indexes:
                        index_info.append({
                            "name": idx.get("name"),
                            "keys": list(idx.get("key", {}).keys()),
                            "unique": idx.get("unique", False),
                            "sparse": idx.get("sparse", False)
                        })
                    
                    diagnostics["collections"][col_name] = {
                        "exists": True,
                        "count": stats.get("count", 0),
                        "size_mb": round(stats.get("size", 0) / (1024 * 1024), 2),
                        "storage_size_mb": round(stats.get("storageSize", 0) / (1024 * 1024), 2),
                        "avg_doc_size_bytes": stats.get("avgObjSize", 0),
                        "index_count": stats.get("nindexes", 0),
                        "total_index_size_mb": round(stats.get("totalIndexSize", 0) / (1024 * 1024), 2),
                        "indexes": index_info,
                        "capped": stats.get("capped", False),
                        "wired_tiger": {
                            "compression": stats.get("wiredTiger", {}).get("creationString", "").split("block_compressor=")[-1].split(",")[0] if stats.get("wiredTiger") else None
                        }
                    }
                else:
                    diagnostics["collections"][col_name] = {"exists": False}
            except Exception as e:
                diagnostics["collections"][col_name] = {"error": str(e)}
        
        # Analyze and provide recommendations
        recommendations = []
        
        # Check ib_historical_data collection
        hist_data = diagnostics["collections"].get("ib_historical_data", {})
        if hist_data.get("exists"):
            doc_count = hist_data.get("count", 0)
            index_size = hist_data.get("total_index_size_mb", 0)
            data_size = hist_data.get("size_mb", 0)
            
            # Check if index size is proportionally large
            if data_size > 0 and index_size / data_size > 0.5:
                recommendations.append({
                    "priority": "MEDIUM",
                    "area": "indexes",
                    "issue": f"Index size ({index_size:.0f}MB) is {(index_size/data_size*100):.0f}% of data size ({data_size:.0f}MB)",
                    "suggestion": "Consider if all indexes are necessary. Drop unused indexes to reduce storage and write overhead."
                })
            
            # Check document count for Atlas tier recommendations
            if doc_count > 5_000_000:
                recommendations.append({
                    "priority": "HIGH",
                    "area": "atlas_tier",
                    "issue": f"Collection has {doc_count:,} documents",
                    "suggestion": "For 5M+ documents, consider upgrading to M10+ cluster for dedicated resources and better write throughput."
                })
            elif doc_count > 1_000_000:
                recommendations.append({
                    "priority": "MEDIUM",
                    "area": "atlas_tier",
                    "issue": f"Collection has {doc_count:,} documents",
                    "suggestion": "M0/M2/M5 shared tiers have limited IOPS. Consider M10 dedicated cluster for sustained write performance."
                })
        
        # Check historical_data_requests queue
        queue_data = diagnostics["collections"].get("historical_data_requests", {})
        if queue_data.get("exists"):
            queue_size = queue_data.get("size_mb", 0)
            if queue_size > 100:
                recommendations.append({
                    "priority": "LOW",
                    "area": "cleanup",
                    "issue": f"Queue collection is {queue_size:.0f}MB",
                    "suggestion": "Consider purging old completed requests to reduce storage. Call /api/ib-collector/clear-completed endpoint."
                })
        
        # Check for historical_bars redundancy
        hist_bars = diagnostics["collections"].get("historical_bars", {})
        if hist_bars.get("exists") and hist_bars.get("count", 0) > 0:
            recommendations.append({
                "priority": "MEDIUM",
                "area": "cleanup",
                "issue": f"historical_bars collection exists with {hist_bars.get('count', 0):,} documents",
                "suggestion": "This appears redundant with ib_historical_data. Consider consolidating to reduce storage costs."
            })
        
        # Connection pool recommendations
        conn = diagnostics.get("connection", {})
        if conn.get("max_pool_size", 0) < 50:
            recommendations.append({
                "priority": "MEDIUM",
                "area": "connection",
                "issue": f"Connection pool max size is {conn.get('max_pool_size', 'unknown')}",
                "suggestion": "For high-throughput writes, consider increasing maxPoolSize to 100 in connection string: ?maxPoolSize=100"
            })
        
        # Atlas-specific recommendations
        recommendations.append({
            "priority": "INFO",
            "area": "atlas_settings",
            "issue": "Atlas Performance Advisor",
            "suggestion": "Check Atlas UI > Performance Advisor for slow query analysis and index suggestions."
        })
        
        recommendations.append({
            "priority": "INFO", 
            "area": "atlas_settings",
            "issue": "Write Concern",
            "suggestion": "For faster writes (with slight durability tradeoff), add ?w=1&journal=false to connection string. Current default is w=majority which waits for replication."
        })
        
        recommendations.append({
            "priority": "INFO",
            "area": "atlas_network",
            "issue": "Network Latency",
            "suggestion": "Ensure your IB Data Pusher runs in a region close to your Atlas cluster. Check Atlas > Network Access > Peering for VPC options if latency is high."
        })
        
        diagnostics["recommendations"] = recommendations
        
        return {
            "success": True,
            **diagnostics
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting MongoDB diagnostics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/historical-data/status/{request_id}")
async def get_historical_data_request_status(request_id: str):
    """Get the status of a historical data request"""
    service = _get_historical_data_service()
    if not service:
        raise HTTPException(status_code=503, detail="Historical data service not available")
    
    try:
        request = service.get_request(request_id)
        if request:
            return {"success": True, "request": request}
        else:
            raise HTTPException(status_code=404, detail=f"Request {request_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting historical data request status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
