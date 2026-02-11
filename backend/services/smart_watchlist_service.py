"""
Smart Watchlist Service
Hybrid auto-populated + manual watchlist with strategy-based expiration

Features:
- Auto-populated from scanner hits
- Manual add/remove capability
- Expiration based on strategy timeframe:
  - Scalp/Intraday: End of trading day
  - Swing/Position: 72 hours
- Max 50 symbols
- Tier 1 scan priority for all watchlist items
"""

from datetime import datetime, timezone, timedelta, time
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
from pymongo import MongoClient
from pymongo.collection import Collection
import os

logger = logging.getLogger(__name__)


class StrategyTimeframe(str, Enum):
    SCALP = "scalp"           # Expires end of day
    INTRADAY = "intraday"     # Expires end of day
    SWING = "swing"           # Expires in 72h
    POSITION = "position"     # Expires in 72h


@dataclass
class WatchlistItem:
    """Represents a watchlist entry"""
    symbol: str
    source: str  # "scanner" or "manual"
    added_at: datetime
    last_signal_at: Optional[datetime] = None
    signal_count: int = 0
    strategies_matched: List[str] = field(default_factory=list)
    timeframe: StrategyTimeframe = StrategyTimeframe.INTRADAY
    is_sticky: bool = False  # Manual adds are sticky
    score: int = 0
    notes: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "last_signal_at": self.last_signal_at.isoformat() if self.last_signal_at else None,
            "signal_count": self.signal_count,
            "strategies_matched": self.strategies_matched,
            "timeframe": self.timeframe.value,
            "is_sticky": self.is_sticky,
            "score": self.score,
            "notes": self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "WatchlistItem":
        return cls(
            symbol=data.get("symbol", ""),
            source=data.get("source", "scanner"),
            added_at=datetime.fromisoformat(data["added_at"]) if data.get("added_at") else datetime.now(timezone.utc),
            last_signal_at=datetime.fromisoformat(data["last_signal_at"]) if data.get("last_signal_at") else None,
            signal_count=data.get("signal_count", 0),
            strategies_matched=data.get("strategies_matched", []),
            timeframe=StrategyTimeframe(data.get("timeframe", "intraday")),
            is_sticky=data.get("is_sticky", False),
            score=data.get("score", 0),
            notes=data.get("notes", "")
        )


# Strategy to timeframe mapping
STRATEGY_TIMEFRAMES = {
    # Scalp strategies (expire end of day)
    "opening_range_breakout": StrategyTimeframe.SCALP,
    "orb_5min": StrategyTimeframe.SCALP,
    "orb_15min": StrategyTimeframe.SCALP,
    "first_5min_high_break": StrategyTimeframe.SCALP,
    "opening_reversal": StrategyTimeframe.SCALP,
    "gap_and_go": StrategyTimeframe.SCALP,
    "gap_fade": StrategyTimeframe.SCALP,
    "vwap_bounce": StrategyTimeframe.SCALP,
    "vwap_rejection": StrategyTimeframe.SCALP,
    "vwap_reclaim": StrategyTimeframe.SCALP,
    "red_to_green": StrategyTimeframe.SCALP,
    "green_to_red": StrategyTimeframe.SCALP,
    "abcd_scalp": StrategyTimeframe.SCALP,
    "momentum_ignition": StrategyTimeframe.SCALP,
    "tape_speed_up": StrategyTimeframe.SCALP,
    
    # Intraday strategies (expire end of day)
    "trend_continuation": StrategyTimeframe.INTRADAY,
    "pullback_entry": StrategyTimeframe.INTRADAY,
    "range_breakout": StrategyTimeframe.INTRADAY,
    "hod_breakout": StrategyTimeframe.INTRADAY,
    "lod_breakdown": StrategyTimeframe.INTRADAY,
    "midday_momentum": StrategyTimeframe.INTRADAY,
    "afternoon_breakout": StrategyTimeframe.INTRADAY,
    "power_hour_momentum": StrategyTimeframe.INTRADAY,
    "sector_rotation": StrategyTimeframe.INTRADAY,
    "relative_strength_play": StrategyTimeframe.INTRADAY,
    "relative_weakness_play": StrategyTimeframe.INTRADAY,
    "squeeze_breakout": StrategyTimeframe.INTRADAY,
    "volume_climax": StrategyTimeframe.INTRADAY,
    "failed_breakdown": StrategyTimeframe.INTRADAY,
    "failed_breakout": StrategyTimeframe.INTRADAY,
    
    # Swing strategies (expire in 72h)
    "daily_breakout": StrategyTimeframe.SWING,
    "weekly_breakout": StrategyTimeframe.SWING,
    "bull_flag": StrategyTimeframe.SWING,
    "bear_flag": StrategyTimeframe.SWING,
    "ascending_triangle": StrategyTimeframe.SWING,
    "descending_triangle": StrategyTimeframe.SWING,
    "cup_and_handle": StrategyTimeframe.SWING,
    "inverse_head_shoulders": StrategyTimeframe.SWING,
    "head_shoulders": StrategyTimeframe.SWING,
    "double_bottom": StrategyTimeframe.SWING,
    "double_top": StrategyTimeframe.SWING,
    "ema_crossover": StrategyTimeframe.SWING,
    "golden_cross": StrategyTimeframe.SWING,
    "death_cross": StrategyTimeframe.SWING,
    "52_week_high_breakout": StrategyTimeframe.SWING,
    "52_week_low_breakdown": StrategyTimeframe.SWING,
    "earnings_drift": StrategyTimeframe.SWING,
    "post_earnings_continuation": StrategyTimeframe.SWING,
    
    # Position strategies (expire in 72h)
    "trend_reversal": StrategyTimeframe.POSITION,
    "sector_momentum": StrategyTimeframe.POSITION,
    "relative_value": StrategyTimeframe.POSITION,
    "mean_reversion": StrategyTimeframe.POSITION,
    "institutional_accumulation": StrategyTimeframe.POSITION,
    "institutional_distribution": StrategyTimeframe.POSITION,
}


class SmartWatchlistService:
    """
    Manages the hybrid auto/manual watchlist with intelligent expiration
    """
    
    MAX_WATCHLIST_SIZE = 50
    SWING_EXPIRY_HOURS = 72
    
    def __init__(self, db: Collection = None):
        self._db = db
        self._watchlist: Dict[str, WatchlistItem] = {}
        self._blacklist: Dict[str, datetime] = {}  # Temp blacklist for manual removes
        self._blacklist_duration = timedelta(hours=24)
        
        # Initialize from database if available
        if self._db is not None:
            self._load_from_db()
    
    def _load_from_db(self):
        """Load watchlist from MongoDB"""
        try:
            items = self._db.find({"_type": "watchlist_item"})
            for item_data in items:
                item_data.pop("_id", None)
                item_data.pop("_type", None)
                item = WatchlistItem.from_dict(item_data)
                self._watchlist[item.symbol] = item
            logger.info(f"Loaded {len(self._watchlist)} watchlist items from database")
        except Exception as e:
            logger.error(f"Error loading watchlist from DB: {e}")
    
    def _save_item_to_db(self, item: WatchlistItem):
        """Save a single item to MongoDB"""
        if self._db is None:
            return
        try:
            data = item.to_dict()
            data["_type"] = "watchlist_item"
            self._db.update_one(
                {"symbol": item.symbol, "_type": "watchlist_item"},
                {"$set": data},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error saving watchlist item to DB: {e}")
    
    def _remove_item_from_db(self, symbol: str):
        """Remove an item from MongoDB"""
        if self._db is None:
            return
        try:
            self._db.delete_one({"symbol": symbol, "_type": "watchlist_item"})
        except Exception as e:
            logger.error(f"Error removing watchlist item from DB: {e}")
    
    def _get_market_close_today(self) -> datetime:
        """Get today's market close time (4 PM ET)"""
        now = datetime.now(timezone.utc)
        # Market closes at 4 PM ET = 21:00 UTC (during EST) or 20:00 UTC (during EDT)
        # Using 21:00 UTC as conservative estimate
        market_close = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if now > market_close:
            # If past close, next close is tomorrow
            market_close += timedelta(days=1)
        return market_close
    
    def _is_expired(self, item: WatchlistItem) -> bool:
        """Check if a watchlist item has expired"""
        if item.is_sticky:
            return False  # Manual adds never expire
        
        now = datetime.now(timezone.utc)
        reference_time = item.last_signal_at or item.added_at
        
        if item.timeframe in [StrategyTimeframe.SCALP, StrategyTimeframe.INTRADAY]:
            # Expires at end of trading day
            # If last signal was before today's close and we're past close, it's expired
            market_close = self._get_market_close_today()
            # If reference time is from a previous day, it's expired
            if reference_time.date() < now.date():
                return True
            # If it's past market close and reference is from today before close
            if now > market_close and reference_time < market_close:
                return True
            return False
        else:
            # Swing/Position: Expires in 72 hours
            expiry_time = reference_time + timedelta(hours=self.SWING_EXPIRY_HOURS)
            return now > expiry_time
    
    def _is_blacklisted(self, symbol: str) -> bool:
        """Check if symbol is temporarily blacklisted"""
        if symbol not in self._blacklist:
            return False
        
        blacklist_time = self._blacklist[symbol]
        if datetime.now(timezone.utc) > blacklist_time + self._blacklist_duration:
            del self._blacklist[symbol]
            return False
        return True
    
    def _enforce_max_size(self):
        """Ensure watchlist doesn't exceed max size by removing lowest scored non-sticky items"""
        if len(self._watchlist) <= self.MAX_WATCHLIST_SIZE:
            return
        
        # Sort by: sticky first, then by score descending
        sorted_items = sorted(
            self._watchlist.values(),
            key=lambda x: (x.is_sticky, x.score),
            reverse=True
        )
        
        # Keep only top MAX_WATCHLIST_SIZE
        to_remove = sorted_items[self.MAX_WATCHLIST_SIZE:]
        for item in to_remove:
            if not item.is_sticky:  # Double-check we're not removing manual adds
                del self._watchlist[item.symbol]
                self._remove_item_from_db(item.symbol)
                logger.debug(f"Removed {item.symbol} from watchlist (max size enforcement)")
    
    def cleanup_expired(self) -> List[str]:
        """Remove expired items from watchlist"""
        expired = []
        for symbol, item in list(self._watchlist.items()):
            if self._is_expired(item):
                expired.append(symbol)
                del self._watchlist[symbol]
                self._remove_item_from_db(symbol)
        
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired watchlist items: {expired[:5]}...")
        
        return expired
    
    # ==================== PUBLIC API ====================
    
    def add_scanner_hit(
        self,
        symbol: str,
        strategy: str,
        score: int = 50,
        notes: str = ""
    ) -> bool:
        """
        Add or update a symbol from scanner hit
        Returns True if added/updated, False if blacklisted
        """
        symbol = symbol.upper()
        
        # Check blacklist
        if self._is_blacklisted(symbol):
            logger.debug(f"Skipping {symbol} - blacklisted")
            return False
        
        # Determine timeframe from strategy
        timeframe = STRATEGY_TIMEFRAMES.get(strategy, StrategyTimeframe.INTRADAY)
        
        now = datetime.now(timezone.utc)
        
        if symbol in self._watchlist:
            # Update existing entry
            item = self._watchlist[symbol]
            item.last_signal_at = now
            item.signal_count += 1
            if strategy not in item.strategies_matched:
                item.strategies_matched.append(strategy)
            # Update score if higher
            if score > item.score:
                item.score = score
            # Update timeframe to longest (swing > intraday > scalp)
            timeframe_priority = {
                StrategyTimeframe.SCALP: 1,
                StrategyTimeframe.INTRADAY: 2,
                StrategyTimeframe.SWING: 3,
                StrategyTimeframe.POSITION: 4
            }
            if timeframe_priority[timeframe] > timeframe_priority[item.timeframe]:
                item.timeframe = timeframe
        else:
            # Create new entry
            item = WatchlistItem(
                symbol=symbol,
                source="scanner",
                added_at=now,
                last_signal_at=now,
                signal_count=1,
                strategies_matched=[strategy],
                timeframe=timeframe,
                is_sticky=False,
                score=score,
                notes=notes
            )
            self._watchlist[symbol] = item
        
        self._save_item_to_db(item)
        self._enforce_max_size()
        
        logger.debug(f"Scanner hit: {symbol} ({strategy}) - score {score}")
        return True
    
    def add_manual(self, symbol: str, notes: str = "") -> Dict:
        """Manually add a symbol to watchlist"""
        symbol = symbol.upper()
        
        # Remove from blacklist if present
        if symbol in self._blacklist:
            del self._blacklist[symbol]
        
        now = datetime.now(timezone.utc)
        
        if symbol in self._watchlist:
            # Convert to sticky if already exists
            item = self._watchlist[symbol]
            item.is_sticky = True
            item.source = "manual"
            if notes:
                item.notes = notes
        else:
            # Create new manual entry
            item = WatchlistItem(
                symbol=symbol,
                source="manual",
                added_at=now,
                is_sticky=True,
                score=50,  # Default score for manual adds
                notes=notes
            )
            self._watchlist[symbol] = item
        
        self._save_item_to_db(item)
        self._enforce_max_size()
        
        return {"success": True, "symbol": symbol, "message": f"Added {symbol} to watchlist"}
    
    def remove_manual(self, symbol: str) -> Dict:
        """Manually remove a symbol from watchlist"""
        symbol = symbol.upper()
        
        if symbol not in self._watchlist:
            return {"success": False, "message": f"{symbol} not in watchlist"}
        
        # Add to blacklist to prevent auto-re-adding
        self._blacklist[symbol] = datetime.now(timezone.utc)
        
        # Remove from watchlist
        del self._watchlist[symbol]
        self._remove_item_from_db(symbol)
        
        logger.info(f"Manually removed {symbol} from watchlist (blacklisted for 24h)")
        return {"success": True, "symbol": symbol, "message": f"Removed {symbol} from watchlist"}
    
    def get_watchlist(self, include_expired: bool = False) -> List[WatchlistItem]:
        """Get current watchlist, sorted by score"""
        # Cleanup expired first
        if not include_expired:
            self.cleanup_expired()
        
        items = sorted(
            self._watchlist.values(),
            key=lambda x: (x.is_sticky, x.score),
            reverse=True
        )
        return items
    
    def get_symbols(self) -> List[str]:
        """Get just the symbols for scanning (Tier 1)"""
        self.cleanup_expired()
        return list(self._watchlist.keys())
    
    def get_item(self, symbol: str) -> Optional[WatchlistItem]:
        """Get a specific watchlist item"""
        return self._watchlist.get(symbol.upper())
    
    def is_in_watchlist(self, symbol: str) -> bool:
        """Check if symbol is in watchlist"""
        return symbol.upper() in self._watchlist
    
    def get_stats(self) -> Dict:
        """Get watchlist statistics"""
        items = list(self._watchlist.values())
        
        manual_count = sum(1 for i in items if i.is_sticky)
        scanner_count = len(items) - manual_count
        
        by_timeframe = {
            "scalp": sum(1 for i in items if i.timeframe == StrategyTimeframe.SCALP),
            "intraday": sum(1 for i in items if i.timeframe == StrategyTimeframe.INTRADAY),
            "swing": sum(1 for i in items if i.timeframe == StrategyTimeframe.SWING),
            "position": sum(1 for i in items if i.timeframe == StrategyTimeframe.POSITION),
        }
        
        return {
            "total": len(items),
            "manual": manual_count,
            "scanner": scanner_count,
            "by_timeframe": by_timeframe,
            "max_size": self.MAX_WATCHLIST_SIZE,
            "blacklist_count": len(self._blacklist)
        }
    
    def to_api_response(self) -> Dict:
        """Format watchlist for API response"""
        items = self.get_watchlist()
        return {
            "watchlist": [item.to_dict() for item in items],
            "count": len(items),
            "stats": self.get_stats()
        }


# Singleton instance
_smart_watchlist: Optional[SmartWatchlistService] = None


def get_smart_watchlist(db: Collection = None) -> SmartWatchlistService:
    """Get or create the smart watchlist service"""
    global _smart_watchlist
    if _smart_watchlist is None:
        _smart_watchlist = SmartWatchlistService(db)
    return _smart_watchlist


def init_smart_watchlist(db: Collection) -> SmartWatchlistService:
    """Initialize the smart watchlist with database connection"""
    global _smart_watchlist
    _smart_watchlist = SmartWatchlistService(db)
    return _smart_watchlist
