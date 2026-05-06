"""
User Viewed Symbols Tracker
============================
Tracks symbols that users have interacted with (viewed charts, searched, discussed with AI).
These symbols get automatically added to Tier 1 scanning for personalized coverage.

Storage: MongoDB collection 'user_viewed_symbols'
TTL: 7 days (configurable)
"""

from datetime import datetime, timezone, timedelta
from typing import List, Set, Optional, Dict
import logging

logger = logging.getLogger(__name__)

# In-memory cache (refreshed periodically from DB)
_viewed_symbols_cache: Set[str] = set()
_last_cache_refresh: Optional[datetime] = None
_cache_ttl_seconds = 300  # Refresh cache every 5 minutes

# Database reference (set by init)
_db = None


def init_user_viewed_tracker(db):
    """Initialize with database connection"""
    global _db
    _db = db
    
    # Create TTL index for auto-expiration
    if _db is not None:
        try:
            _db["user_viewed_symbols"].create_index(
                "last_viewed",
                expireAfterSeconds=7 * 24 * 60 * 60  # 7 days TTL
            )
            logger.info("User viewed symbols tracker initialized with 7-day TTL")
        except Exception as e:
            logger.warning(f"Could not create TTL index: {e}")


def track_symbol_view(symbol: str, source: str = "unknown") -> bool:
    """
    Track that a user viewed/interacted with a symbol.
    
    Args:
        symbol: Stock symbol (e.g., "NVDA")
        source: Where the view came from ("chart", "search", "ai_chat", "watchlist", etc.)
    
    Returns:
        True if tracked successfully
    """
    global _viewed_symbols_cache
    
    symbol = symbol.upper().strip()
    
    # Basic validation
    if not symbol or len(symbol) > 10:
        return False
    
    # Validate against known universe — reject common English words and phantom symbols
    # that could leak through text extraction (e.g., "QUICK", "FAST", "RALLY")
    if not _is_valid_trackable_symbol(symbol):
        logger.debug(f"Rejected invalid symbol for tracking: {symbol} (source={source})")
        return False
    
    # Add to in-memory cache immediately
    _viewed_symbols_cache.add(symbol)
    
    # Persist to DB
    if _db is not None:
        try:
            _db["user_viewed_symbols"].update_one(
                {"symbol": symbol},
                {
                    "$set": {
                        "last_viewed": datetime.now(timezone.utc),
                        "last_source": source,
                    },
                    "$inc": {"view_count": 1},
                    "$addToSet": {"sources": source}
                },
                upsert=True
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to track symbol view: {e}")
    
    return False


def _is_valid_trackable_symbol(symbol: str) -> bool:
    """
    Validate that a symbol is a real ticker, not a common English word.
    Uses the index universe as the source of truth, with a blocklist fallback.
    """
    # Must be 1-5 uppercase alpha chars
    if not symbol.isalpha() or len(symbol) < 1 or len(symbol) > 5:
        return False
    
    # FIRST: check the known universe — most reliable. If it's a real ticker, allow it
    # even if it happens to also be a common English word (e.g., "FAST" = Fastenal)
    try:
        from data.index_symbols import is_valid_symbol
        if is_valid_symbol(symbol):
            return True
    except ImportError:
        pass
    
    # If NOT in our universe, block common English words that look like tickers
    _COMMON_WORD_BLOCKLIST = {
        "QUICK", "RALLY", "TRADE", "STOCK", "SHARE", "ALERT", "PRICE",
        "CLOSE", "ENTRY", "SHORT", "SMART", "SETUP", "BOOST", "CRASH", "TREND",
        "SURGE", "WATCH", "CLEAR", "BASED", "ABOUT", "ABOVE", "AFTER", "BEING",
        "BELOW", "EVERY", "FIRST", "GIVEN", "GOING", "GREAT", "SINCE", "STILL",
        "THINK", "THOSE", "THREE", "TODAY", "TOTAL", "UNDER", "UNTIL", "WHERE",
        "WHICH", "WHILE", "WORLD", "WOULD", "COULD", "MIGHT", "SHALL", "THEIR",
        "NEVER", "OTHER", "THESE", "RIGHT", "SMALL", "LARGE", "EARLY", "NIGHT",
        "QUITE", "REACH", "START", "PLACE", "POINT", "POWER", "STATE",
        "MONEY", "ORDER", "GROUP", "ALONG", "AMONG", "CHECK", "CLASS", "LEVEL",
        "MAJOR", "MODEL", "OFTEN", "PAPER", "TAKEN", "USING", "VALUE", "YOUNG",
        "BREAK", "CROSS", "KNOWN", "LOCAL", "MEANS", "NOTED", "RANGE", "SOUND",
        # Common trading jargon that isn't a real ticker
        "LONG", "SELL", "HOLD", "CALL", "PUTS", "STOP", "GAIN", "LOSS", "RISK",
        "BULL", "BEAR", "HIGH", "LOWS", "OPEN", "VWAP", "NEWS", "MOVE", "PLAY",
        "EDGE", "PLAN", "EXIT", "FADE", "FLAT", "FLOW", "FUEL", "HEAT",
        "IDEA", "JUMP", "KEEP", "KICK", "LEAD", "LEAN", "LOAD", "LOCK", "MISS",
        "MODE", "MOOD", "MUCH", "NICE", "NOTE", "PEAK", "PICK", "PILE", "PULL",
        "PUMP", "PUSH", "RATE", "REST", "RIDE", "RISE", "ROLL", "SAFE", "SAVE",
        "SCAN", "SHOW", "SIDE", "SIZE", "SKIP", "SLOW", "SNAP", "SOFT",
        "SPIN", "STEP", "SWAY", "TAKE", "TAPE", "TEST", "THIN", "TICK", "TILT",
        "TIME", "TONE", "TOPS", "TRIM", "TURN", "VERY", "VOID", "WAIT", "WAKE",
        "WALK", "WALL", "WARN", "WASH", "WAVE", "WEAK", "WIDE", "WILD", "WILL",
        "WIND", "WIPE", "WORK", "WRAP", "ZERO", "ZONE",
    }
    
    if symbol in _COMMON_WORD_BLOCKLIST:
        return False
    
    # For symbols NOT in our universe and not blocklisted:
    # Single-char symbols — only allow well-known ones
    if len(symbol) == 1:
        return symbol in {"X", "F", "C", "V", "U", "S", "O"}
    
    # 2-4 char symbols that passed the blocklist are likely valid tickers
    if len(symbol) <= 4:
        return True
    
    # 5-char symbols not in our universe are suspicious — reject
    return False


def track_multiple_symbols(symbols: List[str], source: str = "batch") -> int:
    """Track multiple symbols at once (e.g., from AI chat mentioning several tickers)"""
    count = 0
    for symbol in symbols:
        if track_symbol_view(symbol, source):
            count += 1
    return count


def get_viewed_symbols(max_count: int = 100, min_views: int = 1) -> List[str]:
    """
    Get recently viewed symbols for inclusion in Tier 1 scanning.
    
    Args:
        max_count: Maximum number of symbols to return
        min_views: Minimum view count to include
    
    Returns:
        List of symbols sorted by recency
    """
    global _viewed_symbols_cache, _last_cache_refresh
    
    now = datetime.now(timezone.utc)
    
    # Refresh cache if stale
    if (_last_cache_refresh is None or 
        (now - _last_cache_refresh).total_seconds() > _cache_ttl_seconds):
        _refresh_cache()
    
    # If DB is available, get fresh data
    if _db is not None:
        try:
            cursor = _db["user_viewed_symbols"].find(
                {"view_count": {"$gte": min_views}},
                {"symbol": 1, "_id": 0}
            ).sort("last_viewed", -1).limit(max_count)
            
            return [doc["symbol"] for doc in cursor]
        except Exception as e:
            logger.warning(f"Failed to fetch viewed symbols: {e}")
    
    # Fall back to in-memory cache
    return list(_viewed_symbols_cache)[:max_count]


def get_viewed_symbols_set() -> Set[str]:
    """Get viewed symbols as a set for fast membership checks"""
    global _viewed_symbols_cache, _last_cache_refresh
    
    now = datetime.now(timezone.utc)
    
    # Refresh cache if stale
    if (_last_cache_refresh is None or 
        (now - _last_cache_refresh).total_seconds() > _cache_ttl_seconds):
        _refresh_cache()
    
    return _viewed_symbols_cache.copy()


def _refresh_cache():
    """Refresh the in-memory cache from database"""
    global _viewed_symbols_cache, _last_cache_refresh
    
    if _db is not None:
        try:
            cursor = _db["user_viewed_symbols"].find(
                {},
                {"symbol": 1, "_id": 0}
            ).limit(500)
            
            _viewed_symbols_cache = {doc["symbol"] for doc in cursor}
            _last_cache_refresh = datetime.now(timezone.utc)
            logger.debug(f"Refreshed viewed symbols cache: {len(_viewed_symbols_cache)} symbols")
        except Exception as e:
            logger.warning(f"Failed to refresh viewed symbols cache: {e}")
            _last_cache_refresh = datetime.now(timezone.utc)


def get_view_stats() -> Dict:
    """Get statistics about user viewing patterns"""
    if _db is None:
        return {"available": False}
    
    try:
        total = _db["user_viewed_symbols"].count_documents({})
        
        # Top viewed
        top_viewed = list(_db["user_viewed_symbols"].find(
            {},
            {"symbol": 1, "view_count": 1, "_id": 0}
        ).sort("view_count", -1).limit(10))
        
        # Recent views (last hour)
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = _db["user_viewed_symbols"].count_documents({
            "last_viewed": {"$gte": one_hour_ago}
        })
        
        # By source
        pipeline = [
            {"$unwind": "$sources"},
            {"$group": {"_id": "$sources", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        by_source = list(_db["user_viewed_symbols"].aggregate(pipeline))
        
        return {
            "available": True,
            "total_tracked": total,
            "recent_hour": recent,
            "top_viewed": top_viewed,
            "by_source": {item["_id"]: item["count"] for item in by_source}
        }
    except Exception as e:
        logger.warning(f"Failed to get view stats: {e}")
        return {"available": False, "error": str(e)}


def clear_old_views(days: int = 7):
    """Manually clear views older than N days"""
    if _db is None:
        return 0
    
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = _db["user_viewed_symbols"].delete_many({
            "last_viewed": {"$lt": cutoff}
        })
        logger.info(f"Cleared {result.deleted_count} old symbol views")
        return result.deleted_count
    except Exception as e:
        logger.warning(f"Failed to clear old views: {e}")
        return 0


# Singleton accessor
_instance = None

def get_user_viewed_tracker():
    """Get the singleton tracker instance"""
    global _instance
    if _instance is None:
        _instance = {
            "track": track_symbol_view,
            "track_multiple": track_multiple_symbols,
            "get_symbols": get_viewed_symbols,
            "get_symbols_set": get_viewed_symbols_set,
            "get_stats": get_view_stats,
        }
    return _instance
