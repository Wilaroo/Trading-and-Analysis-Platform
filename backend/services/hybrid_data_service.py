"""
Hybrid Data Fetcher Service
===========================
Provides historical market data for backtesting with intelligent source selection:
1. Check MongoDB cache first (ib_historical_data — 177M+ rows)
2. If IB Gateway connected -> use IB (free, consistent with live trading)
3. No Alpaca fallback (removed to eliminate train/serve data skew)

Features:
- Rate limiting for IB to stay within API limits
- Automatic caching of all fetched data
- Works regardless of IB Gateway running status
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


def _estimate_fallback_bar_count(timeframe: str, start_dt: datetime, end_dt: datetime) -> int:
    """How many bars should we grab for a stale-data fallback?
    Mirrors the coverage math in `_get_from_cache` so the fallback chart has
    roughly the same density the user asked for."""
    days = max((end_dt - start_dt).days, 1)
    if timeframe == "1day":
        return max(int(days * 0.7), 30)
    if timeframe == "1hour":
        return max(int(days * 6.5), 40)
    # default intraday (1min/5min/15min/30min): assume 78 5-min bars/day
    return max(int(days * 78), 200)


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
    # Freshness / quality flags — let the UI show "partial" or "stale" warnings
    # instead of silently pretending the data is live.
    stale: bool = False
    stale_reason: Optional[str] = None
    latest_available_date: Optional[str] = None
    partial: bool = False
    coverage: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class HybridDataService:
    """
    Intelligent data fetcher — 100% IB sourced.
    
    Priority:
    1. MongoDB cache (instant, free — ib_historical_data collection)
    2. IB Gateway (free if connected, consistent with live)
    """
    
    # Rate limits (conservative to stay well within limits)
    IB_RATE_LIMIT = 6  # requests per minute (IB allows ~60/10min = 6/min)
    IB_RATE_PERIOD = 60  # seconds
    
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
        
        # Rate limiters
        self._ib_rate_limiter = RateLimiter(
            max_requests=self.IB_RATE_LIMIT,
            period_seconds=self.IB_RATE_PERIOD
        )
        
        # Stats tracking
        self._stats = {
            "cache_hits": 0,
            "ib_fetches": 0,
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
        """DEPRECATED: Alpaca removed from data pipeline. Kept for interface compat."""
        pass
    
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
                    from_cache=True,
                    stale=cached.get("stale", False),
                    stale_reason=cached.get("stale_reason"),
                    latest_available_date=cached.get("latest_available_date"),
                    partial=cached.get("partial", False),
                    coverage=cached.get("coverage"),
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
                    wait_time = self._ib_rate_limiter.wait_time()
                    logger.warning(f"IB rate limited, need to wait {wait_time:.1f}s")
        
        # All sources exhausted. Note: in this deployment the backend does NOT
        # directly connect to IB Gateway — the Windows pusher does that, and
        # historical bars land in `ib_historical_data` via the collector. So
        # "IB disconnected" is almost always the wrong diagnosis; the real
        # cause is that `ib_historical_data` has no bars matching
        # {symbol, bar_size, date-window}.
        self._stats["errors"] += 1
        return DataFetchResult(
            success=False,
            source="error",
            error=(
                f"No bars found for {symbol} {timeframe} in ib_historical_data "
                f"(backend reads pusher+cache, not direct IB). "
                f"Run a backfill or check /api/ib/pusher-health."
            ),
        )
    
    async def _get_from_cache(
        self,
        symbol: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime
    ) -> Dict[str, Any]:
        """Get bars from MongoDB ib_historical_data collection"""
        if self._bars_collection is None:
            return {"success": False, "bars": [], "bar_count": 0}
        
        try:
            tf_config = self.TIMEFRAMES.get(timeframe, {})
            bar_size = tf_config.get("ib_bar_size", "1 day")
            
            # Query ib_historical_data using its actual field names
            query = {
                "symbol": symbol,
                "bar_size": bar_size,
                "date": {
                    "$gte": start_dt.strftime("%Y-%m-%d") if timeframe == "1day" else start_dt.isoformat(),
                    "$lte": end_dt.strftime("%Y-%m-%d") if timeframe == "1day" else end_dt.isoformat()
                }
            }
            
            bars = list(self._bars_collection.find(query, {"_id": 0}).sort("date", 1))

            # Normalize field names for compatibility
            for bar in bars:
                if "date" in bar and "timestamp" not in bar:
                    bar["timestamp"] = bar["date"]

            # STALENESS FALLBACK: if the requested window is empty but the
            # collection has bars for this (symbol, bar_size) from an older
            # period, return the most recent slice instead of falling through
            # to the "no cached data" error path. The user would rather see
            # a stale chart with a warning than a blank panel — especially
            # important when the IB historical collector has stopped writing
            # fresh bars but live pusher quotes keep the app "feeling" live.
            if not bars:
                fallback_count = _estimate_fallback_bar_count(timeframe, start_dt, end_dt)
                stale_bars = list(
                    self._bars_collection
                        .find({"symbol": symbol, "bar_size": bar_size}, {"_id": 0})
                        .sort("date", -1)
                        .limit(fallback_count)
                )
                if stale_bars:
                    stale_bars.reverse()  # chronological order for chart
                    for bar in stale_bars:
                        if "date" in bar and "timestamp" not in bar:
                            bar["timestamp"] = bar["date"]
                    latest_date = stale_bars[-1].get("date")
                    logger.warning(
                        f"[hybrid_data] No {symbol} {timeframe} bars in requested "
                        f"window [{start_dt.date()} → {end_dt.date()}]. "
                        f"Returning last {len(stale_bars)} bars (latest={latest_date}) "
                        f"as STALE fallback — historical collector has not run recently."
                    )
                    return {
                        "success": True,
                        "bars": stale_bars,
                        "bar_count": len(stale_bars),
                        "stale": True,
                        "stale_reason": "no_bars_in_requested_window",
                        "latest_available_date": latest_date,
                    }

            # Check how much data we have vs what's expected
            if bars:
                days = (end_dt - start_dt).days
                if timeframe == "1day":
                    expected = max(days * 0.7, 1)
                elif timeframe == "1hour":
                    expected = max(days * 6.5, 1)
                else:
                    expected = max(days * 78, 1)

                coverage = len(bars) / expected

                # Full-coverage hit — return as a normal cache hit.
                if coverage >= 0.8:
                    return {"success": True, "bars": bars, "bar_count": len(bars)}

                # Partial coverage — still return what we have rather than
                # falling through to the "IB disconnected" dead-end.
                # In this deployment the backend does NOT talk to IB directly
                # (the Windows pusher does), so an empty return = blank chart
                # for the user every time there's a cache gap. Better to show
                # partial data and log the shortfall.
                logger.info(
                    f"[hybrid_data] Partial cache hit for {symbol} {timeframe}: "
                    f"{len(bars)} bars / ~{int(expected)} expected "
                    f"({coverage*100:.0f}% coverage). Returning partial data."
                )
                return {
                    "success": True,
                    "bars": bars,
                    "bar_count": len(bars),
                    "partial": True,
                    "coverage": coverage,
                }

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
            "ib_rate_limit": {
                "can_request": self._ib_rate_limiter.can_request(),
                "wait_time": self._ib_rate_limiter.wait_time()
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
    
    # ------------------------------------------------------------------
    # Phase 1 — Live Data Architecture
    # On-demand latest-session fetch via Windows pusher RPC + TTL cache.
    # ------------------------------------------------------------------

    # Bar-size → IB duration to request for a "latest session" slice.
    # Values are deliberately modest (1-2 D) because this path is meant to
    # TOP UP the historical Mongo store with the most recent bars, not
    # replace the backfill collectors.
    _LATEST_SESSION_DURATION = {
        "1 min": "1 D",
        "5 mins": "2 D",
        "15 mins": "5 D",
        "30 mins": "5 D",
        "1 hour": "10 D",
        "1 day": "1 M",
    }

    async def fetch_latest_session_bars(
        self,
        symbol: str,
        bar_size: str,
        *,
        active_view: bool = False,
        use_rth: bool = False,
    ) -> Dict[str, Any]:
        """
        Return the freshest available bars for (symbol, bar_size) by asking
        the Windows pusher RPC. Uses `live_bar_cache` to avoid hammering IB
        during rapid multi-panel refreshes.

        Returns:
            {
                success: bool,
                bars: [...],
                source: "cache" | "pusher_rpc" | "none",
                market_state: "rth" | "extended" | "overnight" | "weekend",
                fetched_at: ISO ts,
                cache_hit: bool,
            }
        """
        from .ib_pusher_rpc import get_pusher_rpc_client
        from .live_bar_cache import (
            classify_market_state,
            get_live_bar_cache,
        )

        symbol_u = symbol.upper()
        state = classify_market_state()
        cache = get_live_bar_cache()

        # 1) Cache lookup
        if cache is not None:
            cached = cache.get(symbol_u, bar_size)
            if cached:
                return {
                    "success": True,
                    "bars": cached.get("bars", []),
                    "source": "cache",
                    "market_state": cached.get("market_state", state),
                    "fetched_at": cached.get("fetched_at"),
                    "cache_hit": True,
                }

        # 2) Cache miss — call pusher RPC (sync client, wrap in to_thread)
        rpc = get_pusher_rpc_client()
        if not rpc.is_configured():
            return {
                "success": False,
                "bars": [],
                "source": "none",
                "market_state": state,
                "cache_hit": False,
                "error": "pusher_rpc_disabled_or_unconfigured",
            }

        # Skip the RPC if this symbol isn't in the pusher's active
        # subscription list. The pusher would otherwise have to qualify
        # the contract + request historical bars on-demand — which is
        # slow (5-10s), often fails ("[RPC] latest-bars XLE failed"),
        # and clogs the RPC queue causing latency spikes for the symbols
        # that ARE subscribed (RPC p95 was 4848ms in the 2026-04-29
        # afternoon screenshot from this exact issue).
        #
        # Operator's intent: the scanner must still work for the full
        # 1500-4000 symbol universe, but the LIVE RPC path is only for
        # the 14 quote-subscribed symbols. Everything else uses the
        # `ib_historical_data` Mongo cache (refreshed by the 4 turbo
        # collectors on Windows). Caller falls back gracefully when we
        # return `success=False, error="not_in_pusher_subscriptions"`.
        try:
            # v19.30.7 (2026-05-02 evening): wrap in asyncio.to_thread.
            # Pre-fix this sync call held the pusher RPC's
            # threading.Lock (`_request -> with self._lock:`) and
            # blocked the event loop for 5+s under chart-polling
            # storm. Captured by wedge-watchdog (v19.30.6) as the
            # SMOKING-GUN frame of an active 5s+ wedge — same wedge
            # class as v19.30.2 bar_poll fix, different call site.
            # The pusher_rpc module's own header docstring mandates
            # "Call from async paths via asyncio.to_thread"; this
            # finishes honoring that contract for hybrid_data_service.
            subs = await asyncio.to_thread(rpc.subscriptions, False) or set()
        except Exception:
            subs = set()
        if subs and symbol_u not in subs:
            return {
                "success": False,
                "bars": [],
                "source": "none",
                "market_state": state,
                "cache_hit": False,
                "error": "not_in_pusher_subscriptions",
                "pusher_subs_count": len(subs),
            }

        duration = self._LATEST_SESSION_DURATION.get(bar_size, "1 D")
        bars = await asyncio.to_thread(
            rpc.latest_bars,
            symbol_u,
            bar_size,
            duration,
            use_rth,
        )

        if bars is None:
            return {
                "success": False,
                "bars": [],
                "source": "none",
                "market_state": state,
                "cache_hit": False,
                "error": "pusher_rpc_unreachable",
            }

        # 3) Cache it
        cached_doc = None
        if cache is not None:
            cached_doc = cache.put(
                symbol_u,
                bar_size,
                bars,
                active_view=active_view,
                market_state=state,
            )

        return {
            "success": True,
            "bars": bars,
            "source": "pusher_rpc",
            "market_state": state,
            "fetched_at": (cached_doc or {}).get("fetched_at"),
            "cache_hit": False,
        }

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

    async def fetch_latest_session_bars_batch(
        self,
        symbols: List[str],
        bar_size: str,
        active_view: bool = False,
        use_rth: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Parallel fanout of `fetch_latest_session_bars()`.

        Hits the pusher's /rpc/latest-bars-batch (single round-trip,
        symbols fetched concurrently on the IB side via asyncio.gather).
        Each successful symbol's bars are written into `live_bar_cache`
        so the next per-symbol read is a cache hit.

        Returns a `{symbol: bars_list}` dict — symbols that failed are
        omitted. Callers should treat missing symbols as "no fresh data
        available, fall back to Mongo".
        """
        if not symbols:
            return {}

        # 1. Try to satisfy from live_bar_cache first — anything fresh skips
        #    the network round-trip entirely.
        from services.live_bar_cache import get_live_bar_cache
        cache = get_live_bar_cache()
        ttl = self._cache_ttl_for(active_view=active_view)

        out: Dict[str, List[Dict[str, Any]]] = {}
        misses: List[str] = []
        for sym in symbols:
            cached = cache.get(sym, bar_size, ttl_seconds=ttl)
            if cached:
                out[sym] = cached
            else:
                misses.append(sym)

        if not misses:
            return out

        # 2. Fanout the misses in a single batch RPC call.
        try:
            from services.ib_pusher_rpc import get_pusher_rpc_client, is_live_bar_rpc_enabled
        except Exception as e:
            logger.debug(f"Cannot import pusher RPC client: {e}")
            return out

        if not is_live_bar_rpc_enabled():
            return out
        client = get_pusher_rpc_client()
        if not client.is_configured():
            return out

        # ib_pusher_rpc's HTTP client is sync; offload to a thread so we
        # don't block the FastAPI event loop while the pusher fans out.
        try:
            import asyncio as _asyncio
            batch = await _asyncio.to_thread(
                client.latest_bars_batch,
                misses, bar_size,
                "1 D",      # duration
                use_rth,
                "TRADES",
            )
        except Exception as e:
            logger.debug(f"latest_bars_batch failed: {e}")
            return out

        if not batch:
            return out

        # 3. Cache and return.
        for sym, bars in batch.items():
            if bars:
                cache.put(sym, bar_size, bars)
                out[sym] = bars
        return out

    @staticmethod
    def _cache_ttl_for(active_view: bool = False) -> int:
        """Match the TTL plan used by `fetch_latest_session_bars()` — the
        single source of truth lives in that method, but for the batch
        fanout we want the same numbers without coupling. Pulled from
        the same env vars."""
        if active_view:
            return int(os.environ.get("LIVE_BAR_TTL_ACTIVE_S", "30"))
        # During RTH / extended-hours we honor the regular TTL.
        return int(os.environ.get("LIVE_BAR_TTL_RTH_S", "30"))


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
