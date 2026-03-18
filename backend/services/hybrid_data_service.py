"""
Hybrid Data Fetcher Service
===========================
Provides historical market data for backtesting with intelligent source selection:
1. Check MongoDB cache first
2. If IB Gateway connected -> use IB (free, consistent with live trading)
3. If IB unavailable -> fall back to Alpaca (24/7 availability)

Features:
- Rate limiting for both IB and Alpaca to stay within API limits
- Automatic caching of all fetched data
- Works regardless of app/IB Gateway running status
- Background job queue for large batch requests
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
from collections import deque
import time
import os

logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Token bucket rate limiter"""
    max_requests: int
    period_seconds: int
    tokens: int = field(init=False)
    last_refill: float = field(init=False)
    request_times: deque = field(default_factory=deque)
    
    def __post_init__(self):
        self.tokens = self.max_requests
        self.last_refill = time.time()
        self.request_times = deque(maxlen=self.max_requests * 2)
    
    def can_request(self) -> bool:
        """Check if a request can be made"""
        now = time.time()
        
        # Remove old requests from tracking
        cutoff = now - self.period_seconds
        while self.request_times and self.request_times[0] < cutoff:
            self.request_times.popleft()
        
        return len(self.request_times) < self.max_requests
    
    def record_request(self):
        """Record that a request was made"""
        self.request_times.append(time.time())
    
    def wait_time(self) -> float:
        """Get time to wait before next request is allowed"""
        if self.can_request():
            return 0
        
        if not self.request_times:
            return 0
        
        oldest = self.request_times[0]
        return max(0, oldest + self.period_seconds - time.time())


@dataclass
class DataFetchResult:
    """Result of a data fetch operation"""
    success: bool
    source: str  # 'cache', 'ib', 'alpaca', 'error'
    bars: List[Dict] = field(default_factory=list)
    bar_count: int = 0
    from_cache: bool = False
    error: str = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class HybridDataService:
    """
    Intelligent data fetcher that automatically selects the best data source.
    
    Priority:
    1. MongoDB cache (instant, free)
    2. IB Gateway (free if connected, consistent with live)
    3. Alpaca (fallback, 24/7 availability)
    """
    
    # Rate limits (conservative to stay well within limits)
    IB_RATE_LIMIT = 6  # requests per minute (IB allows ~60/10min = 6/min)
    IB_RATE_PERIOD = 60  # seconds
    
    ALPACA_RATE_LIMIT = 150  # requests per minute (Alpaca allows 200/min)
    ALPACA_RATE_PERIOD = 60  # seconds
    
    # Supported timeframes
    TIMEFRAMES = {
        "1min": {"ib_bar_size": "1 min", "ib_duration_per_day": "1 D", "alpaca_tf": "1Min"},
        "5min": {"ib_bar_size": "5 mins", "ib_duration_per_day": "1 D", "alpaca_tf": "5Min"},
        "15min": {"ib_bar_size": "15 mins", "ib_duration_per_day": "2 D", "alpaca_tf": "15Min"},
        "1hour": {"ib_bar_size": "1 hour", "ib_duration_per_day": "5 D", "alpaca_tf": "1Hour"},
        "1day": {"ib_bar_size": "1 day", "ib_duration_per_day": "1 Y", "alpaca_tf": "1Day"},
    }
    
    # Cache TTLs
    CACHE_TTL_DAILY = 86400 * 30  # 30 days for daily bars
    CACHE_TTL_INTRADAY = 86400 * 7  # 7 days for intraday bars
    
    def __init__(self):
        self._db = None
        self._bars_collection = None
        self._cache_stats_collection = None
        self._ib_service = None
        self._alpaca_service = None
        
        # Rate limiters
        self._ib_rate_limiter = RateLimiter(
            max_requests=self.IB_RATE_LIMIT,
            period_seconds=self.IB_RATE_PERIOD
        )
        self._alpaca_rate_limiter = RateLimiter(
            max_requests=self.ALPACA_RATE_LIMIT,
            period_seconds=self.ALPACA_RATE_PERIOD
        )
        
        # Stats tracking
        self._stats = {
            "cache_hits": 0,
            "ib_fetches": 0,
            "alpaca_fetches": 0,
            "ib_rate_limited": 0,
            "alpaca_rate_limited": 0,
            "errors": 0
        }
        
    def set_db(self, db):
        """Set MongoDB connection - now uses unified ib_historical_data collection"""
        self._db = db
        if db is not None:
            # Use unified ib_historical_data collection
            self._bars_collection = db['ib_historical_data']
            self._cache_stats_collection = db['data_cache_stats']
            
            # Indexes already exist on ib_historical_data (created by optimize-indexes endpoint)
            logger.info("HybridDataService: MongoDB connected (using ib_historical_data)")
            
    def set_ib_service(self, ib_service):
        """Set IB service reference"""
        self._ib_service = ib_service
        logger.info("HybridDataService: IB service connected")
        
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service reference"""
        self._alpaca_service = alpaca_service
        logger.info("HybridDataService: Alpaca service connected")
    
    def _is_ib_connected(self) -> bool:
        """Check if IB Gateway is connected"""
        if self._ib_service is None:
            return False
        try:
            status = self._ib_service.get_connection_status()
            return status.get("connected", False)
        except Exception:
            return False
    
    def _normalize_timeframe(self, tf: str) -> str:
        """Normalize timeframe string"""
        tf_lower = tf.lower().replace(" ", "").replace("-", "")
        
        # Handle common variations
        mappings = {
            "1m": "1min", "1min": "1min", "1minute": "1min",
            "5m": "5min", "5min": "5min", "5minute": "5min", "5mins": "5min",
            "15m": "15min", "15min": "15min", "15minute": "15min", "15mins": "15min",
            "1h": "1hour", "1hour": "1hour", "1hr": "1hour", "60min": "1hour",
            "1d": "1day", "1day": "1day", "daily": "1day", "d": "1day",
        }
        
        return mappings.get(tf_lower, "1day")
    
    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1day",
        start_date: str = None,
        end_date: str = None,
        days_back: int = 365,
        force_refresh: bool = False,
        preferred_source: Literal["auto", "ib", "alpaca", "cache"] = "auto"
    ) -> DataFetchResult:
        """
        Get historical bars for a symbol with intelligent source selection.
        
        Args:
            symbol: Stock symbol (e.g., "SPY")
            timeframe: Bar timeframe ("1min", "5min", "15min", "1hour", "1day")
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            days_back: Days to look back if dates not specified
            force_refresh: Bypass cache and fetch fresh data
            preferred_source: Force a specific data source
            
        Returns:
            DataFetchResult with bars and metadata
        """
        symbol = symbol.upper()
        timeframe = self._normalize_timeframe(timeframe)
        
        if timeframe not in self.TIMEFRAMES:
            return DataFetchResult(
                success=False,
                source="error",
                error=f"Unsupported timeframe: {timeframe}. Supported: {list(self.TIMEFRAMES.keys())}"
            )
        
        # Calculate date range
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                end_dt = datetime.now(timezone.utc)
        else:
            end_dt = datetime.now(timezone.utc)
            
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                start_dt = end_dt - timedelta(days=days_back)
        else:
            start_dt = end_dt - timedelta(days=days_back)
        
        # Step 1: Check cache first (unless force_refresh or specific source requested)
        if not force_refresh and preferred_source in ["auto", "cache"]:
            cached = await self._get_from_cache(symbol, timeframe, start_dt, end_dt)
            if cached["success"]:
                self._stats["cache_hits"] += 1
                logger.info(f"Cache hit for {symbol} {timeframe}: {cached['bar_count']} bars")
                return DataFetchResult(
                    success=True,
                    source="cache",
                    bars=cached["bars"],
                    bar_count=cached["bar_count"],
                    from_cache=True
                )
        
        # Step 2: Try IB if connected (or if preferred)
        if preferred_source in ["auto", "ib"]:
            if self._is_ib_connected():
                if self._ib_rate_limiter.can_request():
                    ib_result = await self._fetch_from_ib(symbol, timeframe, start_dt, end_dt)
                    if ib_result["success"]:
                        self._stats["ib_fetches"] += 1
                        # Cache the data
                        await self._cache_bars(symbol, timeframe, ib_result["bars"])
                        return DataFetchResult(
                            success=True,
                            source="ib",
                            bars=ib_result["bars"],
                            bar_count=len(ib_result["bars"])
                        )
                else:
                    self._stats["ib_rate_limited"] += 1
                    wait_time = self._ib_rate_limiter.wait_time()
                    logger.warning(f"IB rate limited, need to wait {wait_time:.1f}s")
        
        # Step 3: Fall back to Alpaca
        if preferred_source in ["auto", "alpaca"]:
            if self._alpaca_rate_limiter.can_request():
                alpaca_result = await self._fetch_from_alpaca(symbol, timeframe, start_dt, end_dt)
                if alpaca_result["success"]:
                    self._stats["alpaca_fetches"] += 1
                    # Cache the data
                    await self._cache_bars(symbol, timeframe, alpaca_result["bars"])
                    return DataFetchResult(
                        success=True,
                        source="alpaca",
                        bars=alpaca_result["bars"],
                        bar_count=len(alpaca_result["bars"])
                    )
            else:
                self._stats["alpaca_rate_limited"] += 1
                wait_time = self._alpaca_rate_limiter.wait_time()
                logger.warning(f"Alpaca rate limited, need to wait {wait_time:.1f}s")
        
        # All sources failed
        self._stats["errors"] += 1
        return DataFetchResult(
            success=False,
            source="error",
            error="Unable to fetch data from any source. IB disconnected and Alpaca unavailable or rate limited."
        )
    
    async def _get_from_cache(
        self,
        symbol: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime
    ) -> Dict[str, Any]:
        """Get bars from MongoDB cache"""
        if self._bars_collection is None:
            return {"success": False, "bars": [], "bar_count": 0}
        
        try:
            # Note: Cache TTL can be used in future for invalidation logic
            # For now, we rely on coverage-based freshness check
            
            query = {
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": {
                    "$gte": start_dt.isoformat(),
                    "$lte": end_dt.isoformat()
                }
            }
            
            bars = list(self._bars_collection.find(query, {"_id": 0}).sort("timestamp", 1))
            
            # Check if we have enough data (at least 80% of expected bars)
            if bars:
                # Rough estimate of expected bars
                days = (end_dt - start_dt).days
                if timeframe == "1day":
                    expected = days * 0.7  # ~70% trading days
                elif timeframe == "1hour":
                    expected = days * 6.5  # ~6.5 hours per day
                else:
                    expected = days * 78  # ~78 5-min bars per day
                
                coverage = len(bars) / max(expected, 1)
                
                if coverage >= 0.8:
                    return {"success": True, "bars": bars, "bar_count": len(bars)}
            
            return {"success": False, "bars": [], "bar_count": 0}
            
        except Exception as e:
            logger.error(f"Cache read error: {e}")
            return {"success": False, "bars": [], "bar_count": 0}
    
    async def _fetch_from_ib(
        self,
        symbol: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime
    ) -> Dict[str, Any]:
        """Fetch historical data from IB Gateway"""
        if self._ib_service is None:
            return {"success": False, "bars": [], "error": "IB service not configured"}
        
        try:
            self._ib_rate_limiter.record_request()
            
            tf_config = self.TIMEFRAMES[timeframe]
            bar_size = tf_config["ib_bar_size"]
            
            # Calculate duration string for IB
            days = (end_dt - start_dt).days
            if days <= 1:
                duration = "1 D"
            elif days <= 7:
                duration = f"{days} D"
            elif days <= 30:
                duration = f"{days // 7 + 1} W"
            elif days <= 365:
                duration = f"{days // 30 + 1} M"
            else:
                duration = f"{days // 365 + 1} Y"
            
            # Fetch from IB
            result = await self._ib_service.get_historical_data(
                symbol=symbol,
                duration=duration,
                bar_size=bar_size
            )
            
            if result.get("success") and result.get("bars"):
                # Normalize bar format
                bars = []
                for bar in result["bars"]:
                    bars.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": bar.get("date", bar.get("timestamp", "")),
                        "open": float(bar.get("open", 0)),
                        "high": float(bar.get("high", 0)),
                        "low": float(bar.get("low", 0)),
                        "close": float(bar.get("close", 0)),
                        "volume": int(bar.get("volume", 0)),
                        "source": "ib"
                    })
                
                return {"success": True, "bars": bars}
            
            return {"success": False, "bars": [], "error": result.get("error", "Unknown IB error")}
            
        except Exception as e:
            logger.error(f"IB fetch error for {symbol}: {e}")
            return {"success": False, "bars": [], "error": str(e)}
    
    async def _fetch_from_alpaca(
        self,
        symbol: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime
    ) -> Dict[str, Any]:
        """Fetch historical data from Alpaca"""
        try:
            self._alpaca_rate_limiter.record_request()
            
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            from alpaca.data.historical.stock import StockHistoricalDataClient
            
            api_key = os.environ.get("ALPACA_API_KEY", "")
            secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
            
            if not api_key or not secret_key:
                return {"success": False, "bars": [], "error": "Alpaca API keys not configured"}
            
            # Map timeframe
            tf_config = self.TIMEFRAMES[timeframe]
            alpaca_tf = tf_config["alpaca_tf"]
            
            tf_map = {
                "1Min": TimeFrame.Minute,
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
                "15Min": TimeFrame(15, TimeFrameUnit.Minute),
                "1Hour": TimeFrame.Hour,
                "1Day": TimeFrame.Day,
            }
            
            tf = tf_map.get(alpaca_tf, TimeFrame.Day)
            
            # Create client
            client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
            
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start_dt,
                end=end_dt,
                feed="iex"  # Free tier
            )
            
            response = client.get_stock_bars(request)
            
            bars = []
            bars_data = response.data if hasattr(response, 'data') else response
            
            if symbol in bars_data:
                for bar in bars_data[symbol]:
                    bars.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": bar.timestamp.isoformat(),
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "volume": int(bar.volume),
                        "vwap": float(bar.vwap) if bar.vwap else None,
                        "source": "alpaca"
                    })
            
            return {"success": True, "bars": bars}
            
        except Exception as e:
            logger.error(f"Alpaca fetch error for {symbol}: {e}")
            return {"success": False, "bars": [], "error": str(e)}
    
    async def _cache_bars(self, symbol: str, timeframe: str, bars: List[Dict]):
        """Store bars in MongoDB cache"""
        if self._bars_collection is None or not bars:
            return
        
        now = datetime.now(timezone.utc).isoformat()
        
        for bar in bars:
            try:
                bar_doc = {**bar, "cached_at": now}
                self._bars_collection.update_one(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": bar["timestamp"]
                    },
                    {"$set": bar_doc},
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Error caching bar: {e}")
    
    async def prefetch_symbols(
        self,
        symbols: List[str],
        timeframe: str = "1day",
        days_back: int = 365
    ) -> Dict[str, Any]:
        """
        Prefetch historical data for multiple symbols.
        Respects rate limits by queuing requests appropriately.
        
        Returns summary of fetch results.
        """
        results = {
            "total": len(symbols),
            "success": 0,
            "failed": 0,
            "cached": 0,
            "details": []
        }
        
        for symbol in symbols:
            result = await self.get_bars(
                symbol=symbol,
                timeframe=timeframe,
                days_back=days_back
            )
            
            if result.success:
                results["success"] += 1
                if result.from_cache:
                    results["cached"] += 1
            else:
                results["failed"] += 1
            
            results["details"].append({
                "symbol": symbol,
                "success": result.success,
                "source": result.source,
                "bar_count": result.bar_count,
                "error": result.error
            })
            
            # Small delay between requests to be nice to APIs
            await asyncio.sleep(0.5)
        
        return results
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get service status and statistics"""
        return {
            "db_connected": self._db is not None,
            "ib_connected": self._is_ib_connected(),
            "alpaca_configured": bool(os.environ.get("ALPACA_API_KEY")),
            "ib_rate_limit": {
                "can_request": self._ib_rate_limiter.can_request(),
                "wait_time": self._ib_rate_limiter.wait_time()
            },
            "alpaca_rate_limit": {
                "can_request": self._alpaca_rate_limiter.can_request(),
                "wait_time": self._alpaca_rate_limiter.wait_time()
            },
            "stats": self._stats,
            "supported_timeframes": list(self.TIMEFRAMES.keys())
        }
    
    async def get_cached_symbols(self) -> List[str]:
        """Get list of symbols with cached data"""
        if self._bars_collection is None:
            return []
        return self._bars_collection.distinct("symbol")
    
    async def get_cache_stats(self, symbol: str = None) -> List[Dict]:
        """Get cache statistics for symbols"""
        if self._bars_collection is None:
            return []
        
        pipeline = [
            {"$group": {
                "_id": {"symbol": "$symbol", "timeframe": "$timeframe"},
                "bar_count": {"$sum": 1},
                "first_bar": {"$min": "$timestamp"},
                "last_bar": {"$max": "$timestamp"},
                "last_cached": {"$max": "$cached_at"}
            }},
            {"$project": {
                "_id": 0,
                "symbol": "$_id.symbol",
                "timeframe": "$_id.timeframe",
                "bar_count": 1,
                "first_bar": 1,
                "last_bar": 1,
                "last_cached": 1
            }}
        ]
        
        if symbol:
            pipeline.insert(0, {"$match": {"symbol": symbol.upper()}})
        
        return list(self._bars_collection.aggregate(pipeline))
    
    async def clear_cache(self, symbol: str = None, timeframe: str = None) -> Dict[str, Any]:
        """Clear cached data"""
        if self._bars_collection is None:
            return {"success": False, "error": "Database not connected"}
        
        query = {}
        if symbol:
            query["symbol"] = symbol.upper()
        if timeframe:
            query["timeframe"] = self._normalize_timeframe(timeframe)
        
        result = self._bars_collection.delete_many(query)
        
        return {
            "success": True,
            "deleted_count": result.deleted_count
        }


# Singleton instance
_hybrid_data_service: Optional[HybridDataService] = None


def get_hybrid_data_service() -> HybridDataService:
    """Get singleton instance of HybridDataService"""
    global _hybrid_data_service
    if _hybrid_data_service is None:
        _hybrid_data_service = HybridDataService()
    return _hybrid_data_service


def init_hybrid_data_service(
    db=None,
    ib_service=None,
    alpaca_service=None
) -> HybridDataService:
    """Initialize the hybrid data service with dependencies"""
    service = get_hybrid_data_service()
    if db is not None:
        service.set_db(db)
    if ib_service is not None:
        service.set_ib_service(ib_service)
    if alpaca_service is not None:
        service.set_alpaca_service(alpaca_service)
    return service
