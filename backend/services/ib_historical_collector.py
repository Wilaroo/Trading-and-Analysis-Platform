"""
IB Historical Data Collector Service
=====================================

Systematically collects historical data from IB Gateway to build a comprehensive
learning database for SentCom's AI systems.

Key Features:
1. Batch collection of historical OHLCV data for multiple symbols
2. Respects IB rate limits (1 request at a time, pacing)
3. Stores data in MongoDB for model training
4. Supports multiple bar sizes (1min, 5min, 15min, 1hour, 1day)
5. Background collection that can run overnight
6. Progress tracking and resume capability

IB Historical Data Limitations:
- 30 seconds or smaller bars: ~6 months history
- 1 minute bars: ~1 year history
- 5 minute bars: ~2 years history
- 1 day bars: ~20 years history
- Rate limit: ~10 requests per second (we use 1 per 2 seconds to be safe)
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
from pymongo import ASCENDING, DESCENDING

logger = logging.getLogger(__name__)


class CollectionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CollectionJob:
    """Represents a historical data collection job"""
    id: str
    symbols: List[str]
    bar_size: str
    duration: str
    start_time: str
    status: CollectionStatus = CollectionStatus.PENDING
    end_time: Optional[str] = None
    symbols_completed: int = 0
    symbols_failed: int = 0
    total_bars_collected: int = 0
    current_symbol: str = ""
    errors: List[str] = field(default_factory=list)
    progress_pct: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "status": self.status.value
        }


class IBHistoricalCollector:
    """
    Collects historical data from IB Gateway and stores in MongoDB.
    
    This service is designed to run in the background, collecting data
    overnight or during low-activity periods to build a comprehensive
    learning database.
    """
    
    COLLECTION_NAME = "ib_historical_data"
    JOBS_COLLECTION = "ib_collection_jobs"
    
    # IB rate limiting - be conservative to avoid disconnects
    REQUEST_DELAY_SECONDS = 2.0  # Wait between requests
    MAX_RETRIES = 3
    
    # Bar size configurations
    BAR_CONFIGS = {
        "1 min": {"max_duration": "1 D", "max_history_days": 365},
        "5 mins": {"max_duration": "2 D", "max_history_days": 730},
        "15 mins": {"max_duration": "1 W", "max_history_days": 730},
        "1 hour": {"max_duration": "1 M", "max_history_days": 1825},
        "1 day": {"max_duration": "1 Y", "max_history_days": 7300},
    }
    
    def __init__(self):
        self._db = None
        self._data_col = None
        self._jobs_col = None
        self._ib_service = None
        self._alpaca_service = None
        self._market_scanner = None  # Use existing market scanner for symbol universe
        self._running_job: Optional[CollectionJob] = None
        self._cancel_requested = False
        self._all_us_symbols: List[str] = []
        
        # Batch processing config
        self.BATCH_SIZE = 100  # Symbols per batch checkpoint
        self.BATCH_DELAY = 0.5  # Seconds between batch saves
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._data_col = db[self.COLLECTION_NAME]
            self._jobs_col = db[self.JOBS_COLLECTION]
            
            # Create indexes
            self._data_col.create_index([("symbol", 1), ("bar_size", 1), ("date", 1)], unique=True)
            self._data_col.create_index([("symbol", 1), ("bar_size", 1)])
            self._data_col.create_index([("collected_at", DESCENDING)])
            self._jobs_col.create_index([("start_time", DESCENDING)])
            self._jobs_col.create_index([("id", 1)], unique=True)
            
    def set_ib_service(self, ib_service):
        """Set IB service for data collection"""
        self._ib_service = ib_service
        
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service for fetching US stock universe"""
        self._alpaca_service = alpaca_service
        
    def set_market_scanner(self, market_scanner):
        """Set market scanner service for symbol universe (preferred)"""
        self._market_scanner = market_scanner
        logger.info("IB Collector: Using market scanner for symbol universe")
        
    async def get_all_us_symbols(self, min_price: float = 1.0, max_price: float = 1000.0) -> List[str]:
        """
        Fetch all tradeable US stocks using the market scanner service.
        
        Priority:
        1. Market Scanner (already has caching and Alpaca integration)
        2. Direct Alpaca API
        3. Fallback to default symbols
        
        Args:
            min_price: Minimum stock price filter
            max_price: Maximum stock price filter
            
        Returns:
            List of symbols meeting criteria
        """
        # Check cache first
        if self._all_us_symbols and len(self._all_us_symbols) > 100:
            return self._all_us_symbols
        
        symbols = []
        
        # Method 1: Use Market Scanner (preferred - already has caching)
        if self._market_scanner:
            try:
                universe = await self._market_scanner.get_symbol_universe()
                if universe and len(universe) > 100:
                    symbols = [s.get("symbol") for s in universe if s.get("symbol")]
                    logger.info(f"Got {len(symbols)} symbols from market scanner")
            except Exception as e:
                logger.warning(f"Market scanner failed: {e}")
        
        # Method 2: Try direct Alpaca
        if not symbols and self._alpaca_service:
            try:
                assets = await self._alpaca_service.get_all_assets()
                if assets:
                    for asset in assets:
                        if (asset.get("tradable") and 
                            asset.get("status") == "active" and
                            asset.get("exchange") in ["NYSE", "NASDAQ", "ARCA", "AMEX"]):
                            symbols.append(asset.get("symbol"))
                    logger.info(f"Got {len(symbols)} symbols from Alpaca")
            except Exception as e:
                logger.warning(f"Alpaca service failed: {e}")
        
        # Method 3: Try to load from database cache
        if not symbols and self._db is not None:
            try:
                cache = self._db["us_symbols"].find({}, {"symbol": 1, "_id": 0})
                cached_symbols = [doc.get("symbol") for doc in cache if doc.get("symbol")]
                if len(cached_symbols) > 100:
                    symbols = cached_symbols
                    logger.info(f"Got {len(symbols)} symbols from database cache")
            except Exception as e:
                logger.warning(f"Database cache failed: {e}")
        
        # Method 4: Fallback to default
        if not symbols:
            symbols = self.get_default_symbols()
            logger.info(f"Using {len(symbols)} default symbols")
        
        self._all_us_symbols = symbols
        return symbols
        
    def get_default_symbols(self) -> List[str]:
        """Get default symbols for data collection"""
        return [
            # Major indices ETFs
            "SPY", "QQQ", "IWM", "DIA",
            # Tech mega caps
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
            # Financials
            "JPM", "BAC", "GS", "MS", "WFC", "C",
            # Healthcare
            "JNJ", "UNH", "PFE", "ABBV", "MRK",
            # Consumer
            "WMT", "COST", "HD", "MCD", "NKE", "SBUX",
            # Energy
            "XOM", "CVX", "COP", "SLB",
            # Industrial
            "CAT", "BA", "GE", "HON", "UPS",
            # Semiconductors
            "AVGO", "QCOM", "INTC", "MU", "AMAT",
            # Other high-volume
            "COIN", "PLTR", "SOFI", "RIVN", "LCID", "NIO",
            # VIX products
            "VXX", "UVXY"
        ]
    
    async def start_full_market_collection(
        self,
        bar_size: str = "1 day",
        duration: str = "1 M",
        min_price: float = 1.0,
        max_price: float = 1000.0,
        batch_size: int = 500
    ) -> Dict[str, Any]:
        """
        Start collection for ALL tradeable US stocks.
        
        This is a long-running job that can take hours. It will:
        1. Fetch all US stock symbols from Alpaca
        2. Filter by price range
        3. Collect historical data in batches
        4. Can be paused/resumed
        
        Args:
            bar_size: Bar size (recommend "1 day" for full market)
            duration: Duration per request
            min_price: Minimum stock price filter
            max_price: Maximum stock price filter
            batch_size: How many symbols to process before saving checkpoint
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "Another collection job is already running",
                "current_job": self._running_job.to_dict()
            }
            
        # Get all US symbols
        logger.info("Fetching all US stock symbols...")
        symbols = await self.get_all_us_symbols(min_price, max_price)
        
        if not symbols:
            return {
                "success": False,
                "error": "Could not fetch US stock list. Check Alpaca connection."
            }
            
        logger.info(f"Starting full market collection for {len(symbols)} symbols")
        
        # Start collection with all symbols
        return await self.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=False
        )
    
    async def start_collection(
        self,
        symbols: List[str] = None,
        bar_size: str = "5 mins",
        duration: str = "1 M",
        use_defaults: bool = True
    ) -> Dict[str, Any]:
        """
        Start a historical data collection job.
        
        Args:
            symbols: List of symbols to collect (uses defaults if None)
            bar_size: Bar size (1 min, 5 mins, 15 mins, 1 hour, 1 day)
            duration: Duration per request (1 D, 2 D, 1 W, 1 M, etc.)
            use_defaults: If True and no symbols provided, use default list
            
        Returns:
            Job info dict
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "Another collection job is already running",
                "current_job": self._running_job.to_dict()
            }
            
        if bar_size not in self.BAR_CONFIGS:
            return {
                "success": False,
                "error": f"Invalid bar_size. Choose from: {list(self.BAR_CONFIGS.keys())}"
            }
            
        if symbols is None or len(symbols) == 0:
            if use_defaults:
                symbols = self.get_default_symbols()
            else:
                return {"success": False, "error": "No symbols provided"}
                
        # Create job
        job = CollectionJob(
            id=f"collect_{uuid.uuid4().hex[:8]}",
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            start_time=datetime.now(timezone.utc).isoformat()
        )
        
        self._running_job = job
        self._cancel_requested = False
        
        # Save job to database
        if self._jobs_col is not None:
            self._jobs_col.insert_one(job.to_dict())
            
        # Start collection in background
        asyncio.create_task(self._run_collection(job))
        
        return {
            "success": True,
            "job_id": job.id,
            "message": f"Started collecting {len(symbols)} symbols with {bar_size} bars",
            "symbols_count": len(symbols)
        }
        
    async def _run_collection(self, job: CollectionJob):
        """Run the collection job"""
        job.status = CollectionStatus.RUNNING
        self._update_job(job)
        
        try:
            total_symbols = len(job.symbols)
            
            for i, symbol in enumerate(job.symbols):
                if self._cancel_requested:
                    job.status = CollectionStatus.CANCELLED
                    break
                    
                job.current_symbol = symbol
                job.progress_pct = (i / total_symbols) * 100
                self._update_job(job)
                
                try:
                    bars_collected = await self._collect_symbol_data(
                        symbol, job.bar_size, job.duration
                    )
                    job.total_bars_collected += bars_collected
                    job.symbols_completed += 1
                    logger.info(f"Collected {bars_collected} bars for {symbol} ({i+1}/{total_symbols})")
                    
                except Exception as e:
                    job.symbols_failed += 1
                    job.errors.append(f"{symbol}: {str(e)}")
                    logger.error(f"Failed to collect {symbol}: {e}")
                    
                # Rate limit - wait between requests
                await asyncio.sleep(self.REQUEST_DELAY_SECONDS)
                
            # Job completed
            if job.status != CollectionStatus.CANCELLED:
                job.status = CollectionStatus.COMPLETED
                
        except Exception as e:
            job.status = CollectionStatus.FAILED
            job.errors.append(f"Job failed: {str(e)}")
            logger.error(f"Collection job failed: {e}")
            
        finally:
            job.end_time = datetime.now(timezone.utc).isoformat()
            job.progress_pct = 100.0
            job.current_symbol = ""
            self._update_job(job)
            self._running_job = None
            
    async def _collect_symbol_data(
        self, 
        symbol: str, 
        bar_size: str, 
        duration: str
    ) -> int:
        """
        Collect historical data for a single symbol.
        
        Returns number of bars collected.
        """
        if not self._ib_service:
            raise Exception("IB service not configured")
            
        bars_collected = 0
        retries = 0
        
        while retries < self.MAX_RETRIES:
            try:
                # Call IB service for historical data
                result = await self._ib_service.get_historical_data(
                    symbol=symbol,
                    duration=duration,
                    bar_size=bar_size
                )
                
                if result.get("success") and result.get("data"):
                    bars = result["data"]
                    
                    # Store in database
                    if self._data_col is not None:
                        for bar in bars:
                            try:
                                self._data_col.update_one(
                                    {
                                        "symbol": symbol,
                                        "bar_size": bar_size,
                                        "date": bar["date"]
                                    },
                                    {
                                        "$set": {
                                            "open": bar["open"],
                                            "high": bar["high"],
                                            "low": bar["low"],
                                            "close": bar["close"],
                                            "volume": bar["volume"],
                                            "collected_at": datetime.now(timezone.utc).isoformat()
                                        }
                                    },
                                    upsert=True
                                )
                                bars_collected += 1
                            except Exception as e:
                                # Duplicate key errors are fine
                                if "duplicate" not in str(e).lower():
                                    logger.warning(f"Error storing bar: {e}")
                                    
                    return bars_collected
                else:
                    error = result.get("error", "Unknown error")
                    if "pacing" in error.lower() or "limit" in error.lower():
                        # Rate limit hit, wait longer
                        await asyncio.sleep(10)
                        retries += 1
                    else:
                        raise Exception(error)
                        
            except Exception:
                retries += 1
                if retries >= self.MAX_RETRIES:
                    raise
                await asyncio.sleep(5)
                
        return bars_collected
        
    def _update_job(self, job: CollectionJob):
        """Update job in database"""
        if self._jobs_col is not None:
            self._jobs_col.update_one(
                {"id": job.id},
                {"$set": job.to_dict()},
                upsert=True
            )
            
    def cancel_collection(self) -> Dict[str, Any]:
        """Cancel the running collection job"""
        if not self._running_job:
            return {"success": False, "error": "No job running"}
            
        self._cancel_requested = True
        return {
            "success": True,
            "message": "Cancellation requested",
            "job_id": self._running_job.id
        }
        
    def get_job_status(self, job_id: str = None) -> Dict[str, Any]:
        """Get status of a collection job"""
        if job_id is None and self._running_job:
            return {
                "success": True,
                "job": self._running_job.to_dict()
            }
            
        if self._jobs_col is None:
            return {"success": False, "error": "Database not connected"}
            
        if job_id:
            job = self._jobs_col.find_one({"id": job_id}, {"_id": 0})
            if job:
                return {"success": True, "job": job}
            return {"success": False, "error": "Job not found"}
            
        # Return current running job
        if self._running_job:
            return {"success": True, "job": self._running_job.to_dict()}
        return {"success": True, "job": None, "message": "No job running"}
        
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about collected data"""
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            # Count by bar size
            pipeline = [
                {"$group": {
                    "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
                    "count": {"$sum": 1},
                    "earliest": {"$min": "$date"},
                    "latest": {"$max": "$date"}
                }},
                {"$group": {
                    "_id": "$_id.bar_size",
                    "symbols": {"$sum": 1},
                    "total_bars": {"$sum": "$count"}
                }}
            ]
            
            bar_stats = list(self._data_col.aggregate(pipeline))
            
            # Total unique symbols
            unique_symbols = self._data_col.distinct("symbol")
            
            # Recent collections
            recent = list(self._data_col.find(
                {},
                {"symbol": 1, "bar_size": 1, "collected_at": 1, "_id": 0}
            ).sort("collected_at", -1).limit(10))
            
            return {
                "success": True,
                "stats": {
                    "unique_symbols": len(unique_symbols),
                    "symbols_list": unique_symbols[:50],  # First 50
                    "by_bar_size": {s["_id"]: {"symbols": s["symbols"], "bars": s["total_bars"]} for s in bar_stats},
                    "total_bars": sum(s["total_bars"] for s in bar_stats),
                    "recent_collections": recent
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting collection stats: {e}")
            return {"success": False, "error": str(e)}
            
    def get_job_history(self, limit: int = 10) -> Dict[str, Any]:
        """Get history of collection jobs"""
        if self._jobs_col is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            jobs = list(self._jobs_col.find(
                {},
                {"_id": 0}
            ).sort("start_time", -1).limit(limit))
            
            return {
                "success": True,
                "jobs": jobs,
                "count": len(jobs)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
            
    def get_symbol_data(
        self,
        symbol: str,
        bar_size: str = "5 mins",
        limit: int = 1000
    ) -> Dict[str, Any]:
        """Get collected data for a symbol"""
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}
            
        try:
            bars = list(self._data_col.find(
                {"symbol": symbol.upper(), "bar_size": bar_size},
                {"_id": 0}
            ).sort("date", -1).limit(limit))
            
            return {
                "success": True,
                "symbol": symbol,
                "bar_size": bar_size,
                "bars": bars,
                "count": len(bars)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# SINGLETON PATTERN
# ============================================================================

_ib_collector: Optional[IBHistoricalCollector] = None


def get_ib_collector() -> IBHistoricalCollector:
    """Get the singleton instance"""
    global _ib_collector
    if _ib_collector is None:
        _ib_collector = IBHistoricalCollector()
    return _ib_collector


def init_ib_collector(db=None, ib_service=None, alpaca_service=None) -> IBHistoricalCollector:
    """Initialize the IB historical collector"""
    collector = get_ib_collector()
    collector.set_db(db)
    if ib_service:
        collector.set_ib_service(ib_service)
    if alpaca_service:
        collector.set_alpaca_service(alpaca_service)
    return collector
