"""
Data Cache Service
Stores last known good data from IB Gateway with timestamps.
No mock data - only real verified data is stored and served.
"""
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import asyncio

class DataCache:
    """
    Caches real data from IB Gateway with timestamps.
    When IB is disconnected, serves cached data with last_updated timestamp.
    Automatically refreshes when connection is restored.
    """
    
    def __init__(self):
        # Cache storage with timestamps
        self._historical_cache: Dict[str, Dict[str, Any]] = {}  # {symbol_duration_barsize: {data, timestamp}}
        self._quote_cache: Dict[str, Dict[str, Any]] = {}  # {symbol: {data, timestamp}}
        self._account_cache: Dict[str, Any] = {}  # {data, timestamp}
        self._positions_cache: List[Dict[str, Any]] = []
        self._positions_timestamp: Optional[datetime] = None
        self._short_interest_cache: Dict[str, Dict[str, Any]] = {}  # {symbol: {data, timestamp}}
        self._news_cache: Dict[str, Dict[str, Any]] = {}  # {symbol: {data, timestamp}}
        
        # Connection state tracking
        self._last_connected: Optional[datetime] = None
        self._pending_refresh: List[str] = []  # Symbols that need refresh
        
    def _cache_key(self, symbol: str, duration: str = "", bar_size: str = "") -> str:
        """Generate cache key"""
        return f"{symbol.upper()}_{duration}_{bar_size}".strip("_")
    
    # ==================== Historical Data ====================
    
    def cache_historical(self, symbol: str, duration: str, bar_size: str, bars: List[Dict]) -> None:
        """Cache historical bar data"""
        key = self._cache_key(symbol, duration, bar_size)
        self._historical_cache[key] = {
            "symbol": symbol.upper(),
            "duration": duration,
            "bar_size": bar_size,
            "bars": bars,
            "count": len(bars),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "is_cached": False  # Fresh data
        }
    
    def get_cached_historical(self, symbol: str, duration: str, bar_size: str) -> Optional[Dict[str, Any]]:
        """Get cached historical data if available"""
        key = self._cache_key(symbol, duration, bar_size)
        cached = self._historical_cache.get(key)
        if cached:
            # Mark as cached data (not fresh)
            result = cached.copy()
            result["is_cached"] = True
            return result
        return None
    
    # ==================== Quote Data ====================
    
    def cache_quote(self, symbol: str, quote_data: Dict[str, Any]) -> None:
        """Cache quote data"""
        self._quote_cache[symbol.upper()] = {
            "data": quote_data,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "is_cached": False
        }
    
    def get_cached_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached quote if available"""
        cached = self._quote_cache.get(symbol.upper())
        if cached:
            result = cached["data"].copy()
            result["last_updated"] = cached["last_updated"]
            result["is_cached"] = True
            return result
        return None
    
    def cache_quotes_batch(self, quotes: List[Dict[str, Any]]) -> None:
        """Cache multiple quotes"""
        for quote in quotes:
            if "symbol" in quote:
                self.cache_quote(quote["symbol"], quote)
    
    # ==================== Account Data ====================
    
    def cache_account(self, account_data: Dict[str, Any]) -> None:
        """Cache account summary"""
        self._account_cache = {
            "data": account_data,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "is_cached": False
        }
    
    def get_cached_account(self) -> Optional[Dict[str, Any]]:
        """Get cached account data"""
        if self._account_cache:
            result = self._account_cache["data"].copy()
            result["last_updated"] = self._account_cache["last_updated"]
            result["is_cached"] = True
            return result
        return None
    
    # ==================== Positions ====================
    
    def cache_positions(self, positions: List[Dict[str, Any]]) -> None:
        """Cache positions"""
        self._positions_cache = positions
        self._positions_timestamp = datetime.now(timezone.utc)
    
    def get_cached_positions(self) -> Optional[Dict[str, Any]]:
        """Get cached positions"""
        if self._positions_cache is not None and self._positions_timestamp:
            return {
                "positions": self._positions_cache,
                "last_updated": self._positions_timestamp.isoformat(),
                "is_cached": True
            }
        return None
    
    # ==================== Short Interest ====================
    
    def cache_short_interest(self, symbol: str, data: Dict[str, Any]) -> None:
        """Cache short interest data for a symbol"""
        self._short_interest_cache[symbol.upper()] = {
            "data": data,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    
    def get_cached_short_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached short interest"""
        cached = self._short_interest_cache.get(symbol.upper())
        if cached:
            result = cached["data"].copy()
            result["last_updated"] = cached["last_updated"]
            result["is_cached"] = True
            return result
        return None
    
    # ==================== News ====================
    
    def cache_news(self, symbol: str, news: List[Dict[str, Any]]) -> None:
        """Cache news for a symbol"""
        self._news_cache[symbol.upper()] = {
            "data": news,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
    
    def get_cached_news(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached news"""
        cached = self._news_cache.get(symbol.upper())
        if cached:
            return {
                "news": cached["data"],
                "last_updated": cached["last_updated"],
                "is_cached": True
            }
        return None
    
    # ==================== Connection Management ====================
    
    def on_connected(self) -> None:
        """Called when IB Gateway connects - triggers refresh of stale data"""
        self._last_connected = datetime.now(timezone.utc)
        # Mark all cached data as needing refresh
        self._pending_refresh = list(self._quote_cache.keys())
    
    def on_disconnected(self) -> None:
        """Called when IB Gateway disconnects"""
        pass  # Data remains cached
    
    def get_pending_refresh(self) -> List[str]:
        """Get list of symbols needing refresh"""
        return self._pending_refresh.copy()
    
    def mark_refreshed(self, symbol: str) -> None:
        """Mark a symbol as refreshed"""
        if symbol.upper() in self._pending_refresh:
            self._pending_refresh.remove(symbol.upper())
    
    # ==================== Cache Stats ====================
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "historical_entries": len(self._historical_cache),
            "quote_entries": len(self._quote_cache),
            "has_account_data": bool(self._account_cache),
            "positions_count": len(self._positions_cache) if self._positions_cache else 0,
            "short_interest_entries": len(self._short_interest_cache),
            "news_entries": len(self._news_cache),
            "last_connected": self._last_connected.isoformat() if self._last_connected else None,
            "pending_refresh_count": len(self._pending_refresh)
        }
    
    def clear_cache(self) -> None:
        """Clear all cached data"""
        self._historical_cache.clear()
        self._quote_cache.clear()
        self._account_cache.clear()
        self._positions_cache = []
        self._positions_timestamp = None
        self._short_interest_cache.clear()
        self._news_cache.clear()
        self._pending_refresh.clear()


# Singleton instance
_data_cache: Optional[DataCache] = None

def get_data_cache() -> DataCache:
    """Get the singleton data cache instance"""
    global _data_cache
    if _data_cache is None:
        _data_cache = DataCache()
    return _data_cache
