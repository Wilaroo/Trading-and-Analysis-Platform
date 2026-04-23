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


# Calendar days per IB duration string — used for chaining step calculations
DURATION_TO_CALENDAR_DAYS = {
    "1 D": 1, "2 D": 2, "3 D": 3, "5 D": 5,
    "1 W": 7, "2 W": 14,
    "1 M": 30, "2 M": 60, "3 M": 90, "6 M": 180,
    "1 Y": 365, "2 Y": 730, "5 Y": 1825, "8 Y": 2920,
    "10 Y": 3650, "20 Y": 7300,
}


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
    
    # IB rate limiting - optimized while staying within IB limits
    # IB Pacing: ~60 requests per 10 minutes = 6/min minimum spacing
    # 1 second = 60/min, well within limits but faster than ultra-conservative 2s
    REQUEST_DELAY_SECONDS = 1.0  # Optimized: was 2.0, now 1.0 (still safe)
    MAX_RETRIES = 3
    MAX_BARS_PER_REQUEST = 2000  # IB limit
    
    # Bar size configurations with IB Gateway limits
    # max_duration: Maximum duration string for a single request (based on 2000 bar limit)
    # max_history_days: How far back IB allows for this bar size
    # bars_per_day: Approximate bars generated per trading day (6.5 hours = 390 mins)
    BAR_CONFIGS = {
        "1 min": {
            "max_duration": "1 W",       # 2000 bars ÷ 390/day = ~5 trading days = ~1 week
            "max_history_days": 180,     # IB limit: ~6 months max for 1-min bars
            "bars_per_day": 390,         # 6.5 hours * 60 mins
        },
        "5 mins": {
            "max_duration": "1 M",       # 2000 bars ÷ 78/day = ~25 trading days = ~1 month
            "max_history_days": 730,     # IB limit: ~2 years max history
            "bars_per_day": 78,          # 6.5 hours * 12 bars/hour
        },
        "15 mins": {
            "max_duration": "3 M",       # 2000 bars ÷ 26/day = ~77 trading days = ~3 months
            "max_history_days": 730,     # IB limit: ~2 years
            "bars_per_day": 26,          # 6.5 hours * 4 bars/hour
        },
        "30 mins": {
            "max_duration": "6 M",       # 2000 bars ÷ 13/day = ~154 trading days = ~6 months
            "max_history_days": 730,     # IB limit: ~2 years
            "bars_per_day": 13,          # 6.5 hours * 2 bars/hour
        },
        "1 hour": {
            "max_duration": "1 Y",       # 2000 bars ÷ 7/day = ~285 trading days = ~1 year
            "max_history_days": 1825,    # IB limit: ~5 years
            "bars_per_day": 7,           # ~7 bars per trading day
        },
        "1 day": {
            "max_duration": "8 Y",       # 2000 bars = 2000 days = ~8 years
            "max_history_days": 7300,    # IB limit: ~20 years
            "bars_per_day": 1,
        },
        "1 week": {
            "max_duration": "20 Y",      # 2000 bars = 2000 weeks = ~38 years (but IB caps at ~20)
            "max_history_days": 7300,    # IB limit: ~20 years
            "bars_per_day": 0.2,         # 1 bar per week
        },
    }
    
    # Timeframes to collect based on stock's liquidity tier
    TIER_TIMEFRAMES = {
        "intraday": ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],      # $50M+ dollar vol/day
        "swing": ["5 mins", "30 mins", "1 hour", "1 day"],                   # $10M+ dollar vol/day
        "investment": ["1 hour", "1 day", "1 week"],                         # $2M+ dollar vol/day
    }
    
    # Dollar volume thresholds (avg_shares × price)
    DOLLAR_VOL_THRESHOLDS = {
        "intraday": 50_000_000,   # $50M/day
        "swing": 10_000_000,      # $10M/day
        "investment": 2_000_000,  # $2M/day
    }
    
    # ATR% thresholds (ATR/price as decimal)
    ATR_PCT_THRESHOLDS = {
        "min": 0.015,   # 1.5% — minimum movement to trade profitably
        "max": 0.10,    # 10% — maximum before it's untradeable chaos
    }
    
    # Legacy share volume thresholds (fallback if dollar volume not computed)
    ADV_THRESHOLDS = {
        "intraday": 500_000,
        "swing": 100_000,
        "investment": 50_000,
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
        
    def get_symbols_with_recent_data(
        self, 
        bar_size: str = "1 day", 
        days_threshold: int = 7
    ) -> set:
        """
        Get symbols that already have recent historical data.
        
        Args:
            bar_size: The bar size to check
            days_threshold: Consider data "recent" if collected within this many days
            
        Returns:
            Set of symbols that already have recent data
        """
        if self._data_col is None:
            return set()
            
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        
        try:
            # Bounded aggregation: maxTimeMS ensures we fail fast rather than
            # block the FastAPI event loop indefinitely on a slow cluster.
            pipeline = [
                {
                    "$match": {
                        "bar_size": bar_size,
                        "collected_at": {"$gte": cutoff.isoformat()}
                    }
                },
                {
                    "$group": {
                        "_id": "$symbol"
                    }
                }
            ]

            result = list(self._data_col.aggregate(
                pipeline, allowDiskUse=True, maxTimeMS=30000
            ))
            symbols_with_data = {doc["_id"] for doc in result}

            logger.info(f"Found {len(symbols_with_data)} symbols with recent {bar_size} data (last {days_threshold} days)")
            return symbols_with_data
            
        except Exception as e:
            logger.warning(f"Error checking for symbols with recent data: {e}")
            return set()
            
    def filter_symbols_needing_collection(
        self,
        symbols: List[str],
        bar_size: str = "1 day",
        days_threshold: int = 7,
        force_refresh: bool = False
    ) -> List[str]:
        """
        Filter symbols to only those that need collection.
        
        Args:
            symbols: List of symbols to potentially collect
            bar_size: Bar size to collect
            days_threshold: Skip symbols with data newer than this many days
            force_refresh: If True, collect all symbols regardless of existing data
            
        Returns:
            List of symbols that actually need collection
        """
        if force_refresh:
            logger.info(f"Force refresh enabled - collecting all {len(symbols)} symbols")
            return symbols
            
        symbols_with_data = self.get_symbols_with_recent_data(bar_size, days_threshold)
        
        if not symbols_with_data:
            logger.info("No existing data found - collecting all symbols")
            return symbols
            
        # Filter out symbols that already have recent data
        symbols_to_collect = [s for s in symbols if s.upper() not in symbols_with_data]
        
        skipped = len(symbols) - len(symbols_to_collect)
        if skipped > 0:
            logger.info(f"Skipping {skipped} symbols with recent data. Collecting {len(symbols_to_collect)} symbols.")
            
        return symbols_to_collect
        
    async def get_all_us_symbols(self, min_price: float = 1.0, max_price: float = 1000.0, filter_ib_compatible: bool = True) -> List[str]:
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
        
        # Apply IB compatibility filter
        if filter_ib_compatible and symbols:
            symbols = self.filter_ib_compatible_symbols(symbols)
        
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
    
    async def build_adv_cache(self, batch_size: int = 100) -> Dict[str, Any]:
        """
        DEPRECATED: Redirects to rebuild_adv_from_ib_data() which uses IB daily bars.
        The old Alpaca IEX-based ADV was inaccurate (IEX underreports volume by ~95%).
        """
        logger.warning("build_adv_cache() is deprecated — redirecting to rebuild_adv_from_ib_data()")
        return await self.rebuild_adv_from_ib_data()
        
    async def rebuild_adv_from_ib_data(self) -> Dict[str, Any]:
        """
        Rebuild the ADV cache with dollar volume and ATR% from IB historical bars.
        
        Computes for each symbol:
        - avg_volume: Average share volume (last 20 trading days)
        - avg_dollar_volume: avg_volume × latest close price
        - atr_pct: Average True Range as % of price (14-day ATR / close)
        - latest_close: Most recent daily close price
        
        Returns:
            Summary of rebuild operation with new tier counts
        """
        if self._db is None:
            return {"success": False, "error": "Database not available"}
        
        if self._data_col is None:
            return {"success": False, "error": "Historical data collection not initialized"}
        
        logger.info("=" * 60)
        logger.info("REBUILDING ADV CACHE — DOLLAR VOLUME + ATR%")
        logger.info("=" * 60)
        
        try:
            # Aggregate: get last 20 daily bars per symbol with OHLCV
            pipeline = [
                {"$match": {"bar_size": "1 day"}},
                {"$sort": {"date": -1}},
                {"$group": {
                    "_id": "$symbol",
                    "volumes": {"$push": "$volume"},
                    "highs": {"$push": "$high"},
                    "lows": {"$push": "$low"},
                    "closes": {"$push": "$close"},
                    "bar_count": {"$sum": 1},
                    "latest_date": {"$first": "$date"},
                }},
                {"$project": {
                    "symbol": "$_id",
                    "_id": 0,
                    "bar_count": 1,
                    "latest_date": 1,
                    "recent_volumes": {"$slice": ["$volumes", 20]},
                    "recent_highs": {"$slice": ["$highs", 20]},
                    "recent_lows": {"$slice": ["$lows", 20]},
                    "recent_closes": {"$slice": ["$closes", 20]},
                    "latest_close": {"$arrayElemAt": ["$closes", 0]},
                }},
                {"$project": {
                    "symbol": 1,
                    "bar_count": 1,
                    "latest_date": 1,
                    "latest_close": 1,
                    "avg_volume": {"$avg": "$recent_volumes"},
                    "days_used": {"$size": "$recent_volumes"},
                    "recent_highs": 1,
                    "recent_lows": 1,
                    "recent_closes": 1,
                }}
            ]
            
            logger.info("Calculating ADV + ATR from IB daily bars...")
            results = list(self._data_col.aggregate(pipeline, allowDiskUse=True))
            logger.info(f"Calculated metrics for {len(results)} symbols")
            
            if not results:
                return {"success": False, "error": "No daily bar data found"}
            
            adv_cache_col = self._db["symbol_adv_cache"]
            
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            
            updated = 0
            skipped_atr = 0
            tier_counts = {"intraday": 0, "swing": 0, "investment": 0, "skip": 0}
            
            for r in results:
                symbol = r.get("symbol")
                avg_vol = r.get("avg_volume", 0)
                latest_close = r.get("latest_close", 0)
                
                if not symbol or avg_vol is None or not latest_close or latest_close <= 0:
                    continue
                
                # Compute dollar volume
                avg_dollar_volume = avg_vol * latest_close
                
                # Compute ATR% (14-day ATR / close price)
                highs = r.get("recent_highs", [])
                lows = r.get("recent_lows", [])
                closes = r.get("recent_closes", [])
                
                atr_pct = 0
                if len(highs) >= 2 and len(lows) >= 2 and len(closes) >= 2:
                    true_ranges = []
                    n = min(len(highs), len(lows), len(closes), 14)
                    for i in range(n - 1):
                        h = highs[i] or 0
                        l = lows[i] or 0
                        prev_c = closes[i + 1] or 0
                        if h > 0 and l > 0 and prev_c > 0:
                            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                            true_ranges.append(tr)
                    
                    if true_ranges and latest_close > 0:
                        atr = sum(true_ranges) / len(true_ranges)
                        atr_pct = atr / latest_close
                
                # Determine tier
                tier = self.get_symbol_tier(avg_vol, avg_dollar_volume, atr_pct)
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
                
                if tier == "skip" and atr_pct > 0 and (atr_pct < self.ATR_PCT_THRESHOLDS["min"] or atr_pct > self.ATR_PCT_THRESHOLDS["max"]):
                    skipped_atr += 1
                
                # Upsert into ADV cache
                adv_cache_col.update_one(
                    {"symbol": symbol},
                    {"$set": {
                        "symbol": symbol,
                        "avg_volume": avg_vol,
                        "avg_dollar_volume": round(avg_dollar_volume, 2),
                        "atr_pct": round(atr_pct, 6),
                        "latest_close": round(latest_close, 2),
                        "tier": tier,
                        "source": "ib_historical_recalc",
                        "days_used": r.get("days_used", 0),
                        "bar_count": r.get("bar_count", 0),
                        "latest_date": r.get("latest_date"),
                        "updated_at": now
                    }},
                    upsert=True
                )
                updated += 1
            
            # Create index on dollar volume for fast tier queries
            adv_cache_col.create_index([("avg_dollar_volume", -1)])
            adv_cache_col.create_index([("tier", 1)])
            
            logger.info("=" * 60)
            logger.info("ADV CACHE REBUILD COMPLETE (DOLLAR VOLUME + ATR%)")
            logger.info(f"  Total symbols updated: {updated}")
            logger.info(f"  Intraday ($50M+): {tier_counts.get('intraday', 0)}")
            logger.info(f"  Swing ($10M-$50M): {tier_counts.get('swing', 0)}")
            logger.info(f"  Investment ($2M-$10M): {tier_counts.get('investment', 0)}")
            logger.info(f"  Skipped (low $vol or ATR out of range): {tier_counts.get('skip', 0)}")
            logger.info(f"  Skipped by ATR filter: {skipped_atr}")
            logger.info("=" * 60)
            
            return {
                "success": True,
                "message": f"Rebuilt ADV cache with dollar volume + ATR% for {updated} symbols",
                "symbols_updated": updated,
                "tier_summary": tier_counts,
                "skipped_by_atr": skipped_atr,
                "thresholds": {
                    "dollar_volume": self.DOLLAR_VOL_THRESHOLDS,
                    "atr_pct": self.ATR_PCT_THRESHOLDS,
                },
            }
            
        except Exception as e:
            logger.error(f"Error rebuilding ADV cache: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    async def get_adv_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the ADV cache"""
        if self._db is None:
            return {"cached": False, "count": 0}
            
        try:
            adv_col = self._db["symbol_adv_cache"]
            total = adv_col.count_documents({})
            
            # Count by ADV threshold (matching scanner service thresholds)
            adv_50k = adv_col.count_documents({"avg_volume": {"$gte": 50_000}})    # Investment
            adv_100k = adv_col.count_documents({"avg_volume": {"$gte": 100_000}})  # Swing
            adv_500k = adv_col.count_documents({"avg_volume": {"$gte": 500_000}})  # Intraday
            adv_1m = adv_col.count_documents({"avg_volume": {"$gte": 1_000_000}})
            
            return {
                "cached": total > 0,
                "total_symbols": total,
                "adv_50k_plus": adv_50k,
                "adv_100k_plus": adv_100k,
                "adv_500k_plus": adv_500k,
                "adv_1m_plus": adv_1m
            }
        except Exception as e:
            return {"cached": False, "error": str(e)}
    
    # Exchanges supported by IB Gateway (exclude OTC/Pink Sheets)
    SUPPORTED_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}
    
    # Known problematic symbol patterns to exclude
    EXCLUDED_PATTERNS = [
        # OTC ADRs typically end in Y or F
        lambda s: len(s) >= 5 and s[-1] in ('Y', 'F') and not s.endswith('SPY') and not s.endswith('QQQ'),
        # Warrants
        lambda s: '.WS' in s or s.endswith('W') and len(s) >= 5,
        # Rights
        lambda s: '.RT' in s or s.endswith('R') and len(s) >= 5,
        # Units
        lambda s: '.U' in s or s.endswith('U') and len(s) >= 5,
        # Preferred shares with complex symbols
        lambda s: '.PR' in s,
        # When-issued
        lambda s: '.WI' in s,
    ]
    
    def filter_ib_compatible_symbols(self, symbols: List[str]) -> List[str]:
        """
        Filter symbols to only include those compatible with IB Gateway.
        
        Excludes:
        - OTC/Pink Sheet stocks
        - Foreign ADRs (typically end in Y or F)
        - Warrants, Rights, Units
        - Delisted stocks
        
        Args:
            symbols: List of symbols to filter
            
        Returns:
            Filtered list of IB-compatible symbols
        """
        if not symbols:
            return []
            
        filtered = []
        excluded_count = 0
        excluded_reasons = {
            "otc_exchange": 0,
            "adr_pattern": 0,
            "warrant": 0,
            "rights": 0,
            "units": 0,
            "preferred": 0,
            "other": 0
        }
        
        # Get exchange info from database if available
        exchange_map = {}
        if self._db is not None:
            try:
                cursor = self._db["us_symbols"].find(
                    {"symbol": {"$in": symbols}},
                    {"symbol": 1, "exchange": 1, "_id": 0}
                )
                exchange_map = {doc["symbol"]: doc.get("exchange", "") for doc in cursor}
            except Exception as e:
                logger.debug(f"Could not fetch exchange data: {e}")
        
        for symbol in symbols:
            exclude = False
            reason = None
            
            # Check exchange (exclude OTC)
            exchange = exchange_map.get(symbol, "")
            if exchange and exchange.upper() == "OTC":
                exclude = True
                reason = "otc_exchange"
            
            # Check for ADR patterns (end in Y or F, length >= 5)
            elif len(symbol) >= 5 and symbol[-1] in ('Y', 'F'):
                # Exclude unless it's a known ETF
                known_etfs = {'SPY', 'QQQ', 'IWF', 'VTV', 'ARKF', 'IUSG', 'SCHF', 'SLYV'}
                if symbol not in known_etfs and not symbol.startswith('X'):  # XL* sector ETFs
                    exclude = True
                    reason = "adr_pattern"
            
            # Check for warrants
            elif '.WS' in symbol or (symbol.endswith('W') and len(symbol) >= 5):
                exclude = True
                reason = "warrant"
            
            # Check for rights
            elif '.RT' in symbol:
                exclude = True
                reason = "rights"
            
            # Check for units
            elif '.U' in symbol:
                exclude = True
                reason = "units"
            
            # Check for preferred shares with complex symbols
            elif '.PR' in symbol:
                exclude = True
                reason = "preferred"
            
            if exclude:
                excluded_count += 1
                if reason:
                    excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            else:
                filtered.append(symbol)
        
        logger.info(f"Symbol filtering: {len(symbols)} -> {len(filtered)} ({excluded_count} excluded)")
        if excluded_count > 0:
            reasons_str = ", ".join([f"{k}:{v}" for k, v in excluded_reasons.items() if v > 0])
            logger.info(f"  Exclusion breakdown: {reasons_str}")
        
        return filtered

    async def get_liquid_symbols(self, min_adv: int = 100_000, filter_ib_compatible: bool = True) -> List[str]:
        """
        Get liquid US stocks filtered by Average Daily Volume (ADV).
        
        Uses ADV cache (built from Alpaca data) as primary source.
        
        Args:
            min_adv: Minimum average daily volume (default 100K for broad coverage)
            
        Returns:
            List of liquid symbols meeting ADV criteria
        """
        liquid_symbols = []
        
        # Method 1: Check ADV cache (PREFERRED - built from actual volume data)
        if self._db is not None:
            try:
                # Look for symbols with ADV data
                cursor = self._db["symbol_adv_cache"].find(
                    {"avg_volume": {"$gte": min_adv}},
                    {"symbol": 1, "_id": 0}
                ).limit(15000)
                liquid_symbols = [doc["symbol"] for doc in cursor if doc.get("symbol")]
                
                if liquid_symbols:
                    logger.info(f"Got {len(liquid_symbols)} liquid symbols from ADV cache (min_adv={min_adv:,})")
                    # Apply IB compatibility filter
                    if filter_ib_compatible:
                        liquid_symbols = self.filter_ib_compatible_symbols(liquid_symbols)
                    return liquid_symbols
            except Exception as e:
                logger.debug(f"ADV cache not available: {e}")
        
        # Method 2: Fall back to market scanner if cache empty
        if self._market_scanner is not None:
            try:
                # Get the full symbol universe from market scanner
                universe = await self._market_scanner.get_symbol_universe()
                
                if universe:
                    # Filter by ADV if volume data is available
                    for sym_data in universe:
                        symbol = sym_data.get("symbol")
                        # Check if we have volume data
                        avg_volume = sym_data.get("avg_volume", 0) or sym_data.get("adv", 0)
                        
                        if avg_volume >= min_adv:
                            liquid_symbols.append(symbol)
                        elif avg_volume == 0:
                            # No volume data - include based on exchange (major exchanges are liquid)
                            exchange = sym_data.get("exchange", "")
                            if exchange in ["NASDAQ", "NYSE", "ARCA", "BATS"]:
                                liquid_symbols.append(symbol)
                    
                    if liquid_symbols:
                        logger.info(f"Got {len(liquid_symbols)} symbols from market scanner (ADV >= {min_adv:,})")
                        return liquid_symbols
                        
            except Exception as e:
                logger.warning(f"Market scanner fetch failed: {e}")
        
        # Method 3: Fall back to curated list (known liquid stocks)
        liquid_symbols = self._get_known_liquid_symbols()
        logger.info(f"Using {len(liquid_symbols)} known liquid symbols as fallback")
        
        # Apply IB compatibility filter if requested
        if filter_ib_compatible and liquid_symbols:
            liquid_symbols = self.filter_ib_compatible_symbols(liquid_symbols)
        
        return liquid_symbols
    
    def _get_known_liquid_symbols(self) -> List[str]:
        """
        Curated list of ~1,500+ known liquid US stocks.
        These stocks typically have ADV > 500,000 and are suitable for active trading.
        """
        # Major ETFs (50)
        etfs = [
            "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "VEA", "VWO", "EFA",
            "IEMG", "VNQ", "BND", "AGG", "LQD", "TLT", "GLD", "SLV", "USO", "UNG",
            "XLF", "XLE", "XLK", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB",
            "ARKK", "ARKG", "ARKW", "ARKF", "ARKQ", "SOXL", "SOXS", "TQQQ", "SQQQ",
            "UVXY", "VXX", "SVXY", "SPXU", "SPXS", "TNA", "TZA", "FAS", "FAZ",
            "HYG", "JNK", "EMB", "VIG", "SCHD", "VYM", "DVY", "JEPI", "JEPQ",
            "XBI", "IBB", "XOP", "OIH", "KRE", "XHB", "ITB", "KWEB", "FXI", "EWZ"
        ]
        
        # Full S&P 500 components (500)
        sp500 = [
            # Top 100 by market cap
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "UNH",
            "JNJ", "JPM", "V", "PG", "XOM", "HD", "CVX", "MA", "ABBV", "MRK",
            "LLY", "AVGO", "PEP", "KO", "COST", "TMO", "MCD", "WMT", "CSCO", "ACN",
            "ABT", "DHR", "NEE", "DIS", "VZ", "ADBE", "WFC", "PM", "TXN", "CRM",
            "NKE", "BMY", "RTX", "ORCL", "COP", "QCOM", "UPS", "HON", "T", "LOW",
            "MS", "INTC", "UNP", "CAT", "IBM", "BA", "INTU", "SPGI", "GS", "DE",
            "AMD", "BLK", "GILD", "AXP", "AMAT", "MDLZ", "CVS", "SBUX", "PLD", "ADI",
            "LMT", "ISRG", "MMC", "AMT", "SYK", "CI", "MO", "NOW", "ZTS", "CB",
            "TJX", "LRCX", "BKNG", "ADP", "SO", "REGN", "VRTX", "BSX", "PGR", "FISV",
            "CME", "SCHW", "BDX", "CL", "EOG", "MU", "ITW", "SNPS", "CDNS", "NOC",
            # 101-200
            "DUK", "SHW", "ICE", "CSX", "PNC", "ETN", "MCK", "FDX", "AON", "KLAC",
            "EQIX", "APD", "EMR", "TGT", "NSC", "AZO", "ORLY", "FCX", "PSA", "AEP",
            "PXD", "HUM", "MCHP", "GD", "ADSK", "MPC", "MSI", "WM", "TRV", "EW",
            "JCI", "SLB", "F", "GM", "OXY", "KMB", "MNST", "D", "HLT", "ROP",
            "CMG", "NXPI", "MAR", "AIG", "STZ", "FTNT", "IQV", "PAYX", "TEL", "A",
            "GIS", "EXC", "BIIB", "HES", "KHC", "YUM", "PCAR", "SYY", "CTSH", "AFL",
            "DOW", "VLO", "ROST", "PSX", "HAL", "WELL", "KMI", "ON", "IDXX", "MSCI",
            "WMB", "DVN", "EL", "CTAS", "CARR", "DXCM", "DD", "ODFL", "DHI", "GWW",
            "HSY", "WBD", "FAST", "EXR", "KEYS", "CPRT", "VRSK", "VMC", "ANSS", "CSGP",
            "IT", "CDW", "FANG", "AME", "MTD", "XYL", "TSCO", "BRO", "DOV", "HPQ",
            # 201-300
            "RMD", "WAT", "GPN", "LH", "FTV", "CHD", "BR", "IRM", "STE", "PTC",
            "HOLX", "TRGP", "WAB", "PKI", "ALGN", "MOH", "WST", "CINF", "MKC", "AVB",
            "NTRS", "MTB", "HBAN", "RF", "FE", "DTE", "VTR", "ARE", "LDOS", "CFG",
            "DGX", "TDY", "BIO", "NDAQ", "TER", "LKQ", "EXPD", "COO", "ATO", "FMC",
            "NI", "KEY", "JBHT", "POOL", "DPZ", "ETSY", "FICO", "SBNY", "URI", "TECH",
            "PKG", "AES", "J", "IP", "CCL", "BBY", "CPB", "AKAM", "TYL", "GL",
            "AAL", "UAL", "DAL", "LUV", "ALK", "JBLU", "SAVE", "HA", "SKYW",
            "K", "SJM", "HRL", "CAG", "LW", "BG", "ADM", "TSN", "HRL", "PPC",
            "CLX", "CL", "CHD", "SPB", "EL", "COTY", "TPR", "CPRI", "PVH", "RL",
            "NVR", "LEN", "DHI", "PHM", "TOL", "MTH", "MDC", "KBH", "TMHC", "MHO",
            # 301-400
            "HPE", "NTAP", "WDC", "STX", "PSTG", "DELL", "NCR", "ZBRA", "JNPR", "ANET",
            "FFIV", "SWKS", "MRVL", "WOLF", "CRUS", "SLAB", "LSCC", "RMBS", "MPWR",
            "LNT", "EVRG", "CMS", "WEC", "ES", "AEE", "CNP", "PNW", "OGE", "NRG",
            "HWM", "TXT", "GE", "LHX", "HII", "LDOS", "SAIC", "BWA", "LEA", "ALV",
            "BEN", "TROW", "IVZ", "JHG", "SEIC", "FHI", "EV", "AMG", "APAM", "CG",
            "TFC", "ZION", "SIVB", "SBNY", "CMA", "FCNCA", "FRC", "PACW", "WAL", "EWBC",
            "MLM", "VMC", "MAS", "FND", "BLDR", "OC", "EXP", "USG", "GMS", "TREX",
            "EMN", "CE", "ALB", "FMC", "IFF", "PPG", "RPM", "SHW", "AXTA", "CABOT",
            "SEE", "IP", "PKG", "GPK", "SLGN", "BLL", "CCK", "ATR", "SON", "WRK",
            "FLEX", "JBL", "SANM", "PLXS", "TTMI", "BDC", "APH", "TEL", "GRMN"
        ]
        
        # NASDAQ 100 + high-growth tech (100)
        nasdaq_growth = [
            "NFLX", "PYPL", "CMCSA", "PDD", "ABNB", "MELI", "WDAY", "TEAM", "ZS", "DDOG",
            "MDB", "NET", "CRWD", "PANW", "OKTA", "ZM", "DOCU", "SPLK", "SNOW", "PLTR",
            "U", "RBLX", "COIN", "HOOD", "SOFI", "UPST", "AFRM", "BILL", "HUBS", "TWLO",
            "RIVN", "LCID", "NIO", "XPEV", "LI", "GRAB", "SE", "SHOP", "SQ", "LSPD",
            "MARA", "RIOT", "BITF", "HUT", "CLSK", "CIFR", "IREN", "BTBT", "GREE", "CAN",
            "ROKU", "TTD", "MGNI", "APPS", "PUBM", "DV", "IAS", "ZETA", "BRZE", "SEMR",
            "CFLT", "MNDY", "PATH", "AI", "GTLB", "ESTC", "NEWR", "SUMO", "FROG", "PD",
            "APP", "BMBL", "MTCH", "PINS", "SNAP", "TWTR", "RDDT", "HOOD", "CPNG", "DUOL",
            "DOCN", "LIDR", "IONQ", "RGTI", "QBTS", "QUBT", "ARQQ", "FORM", "LASR",
            "LAZR", "VLDR", "INVZ", "AEYE", "OUST", "MVIS", "CINT"
        ]
        
        # High-volume speculative/meme stocks (80)
        high_volume = [
            "AMC", "GME", "BBBY", "SNDL", "TLRY", "CGC", "ACB", "CRON", "OGI", "HEXO",
            "SPCE", "PLUG", "FCEL", "BLDP", "BE", "CHPT", "QS", "GOEV", "FSR", "WKHS",
            "RIDE", "NKLA", "HYLN", "ARVL", "REE", "FFIE", "MULN", "PTRA", "LEV", "EVGO",
            "ATER", "BBIG", "PROG", "CLOV", "WISH", "SKLZ", "SDC", "ROOT", "LMND", "OPEN",
            "RDFN", "CVNA", "CARG", "VRM", "STNE", "PAGS", "NU", "PSFE", "AFRM", "UPST",
            "SOFI", "LC", "UWMC", "RKT", "GHLD", "TREE", "LDI", "COOP", "ESSC", "TMTG",
            "DWAC", "CFVI", "NKLA", "GOEV", "REE", "VLDR", "LAZR", "OUST", "INVZ", "AEYE",
            "BB", "NOK", "EXPR", "KOSS", "NAKD", "CENN", "PRTY", "BGFV", "DKNG", "PENN"
        ]
        
        # Biotech & Healthcare (80)
        biotech = [
            "MRNA", "BNTX", "NVAX", "SGEN", "ALNY", "INCY", "BMRN", "EXEL", "SRPT", "RARE",
            "IONS", "UTHR", "NBIX", "SGEN", "FOLD", "HALO", "ARWR", "PTCT", "XLRN", "BLUE",
            "EDIT", "CRSP", "NTLA", "BEAM", "VERV", "PRME", "RXRX", "DNA", "DNAY", "TWST",
            "CERS", "IOVA", "AGEN", "FATE", "KITE", "JUNO", "CELG", "GILD", "AMGN", "BIIB",
            "ILMN", "EXAS", "GH", "NVTA", "PACB", "BNGO", "TWST", "CDNA", "MYGN", "NEO",
            "HZNP", "JAZZ", "LGND", "SUPN", "PRGO", "PAHC", "CTLT", "WST", "TFX", "HOLX",
            "DXCM", "PODD", "TNDM", "IRTC", "OFIX", "NUVA", "GMED", "LIVN", "PEN", "INSP",
            "VEEV", "CNC", "MOH", "HUM", "UNH", "ANTM", "CI", "CVS", "WBA", "RAD"
        ]
        
        # Financials & REITs (80)
        financials = [
            "C", "BAC", "WFC", "USB", "PNC", "TFC", "CFG", "KEY", "RF", "FITB",
            "ZION", "CMA", "HBAN", "MTB", "NTRS", "STT", "BK", "ALLY", "COF", "DFS",
            "AXP", "SYF", "PYPL", "V", "MA", "GPN", "FIS", "FISV", "FLT", "WU",
            "MET", "PRU", "ALL", "HIG", "LNC", "CINF", "GL", "AIZ", "KMPR", "PFG",
            "O", "VICI", "DLR", "CCI", "SBAC", "SPG", "AVB", "EQR", "MAA", "UDR",
            "PSA", "EXR", "CUBE", "LSI", "COLD", "REXR", "PLD", "DRE", "FR", "STAG",
            "WPC", "ADC", "NNN", "STOR", "EPRT", "SRC", "FCPT", "GTY", "PINE", "GOOD",
            "AMH", "INVH", "RDFN", "Z", "ZG", "RDFN", "OPEN", "OPAD", "COMP", "RMAX"
        ]
        
        # Energy & Materials (60)
        energy_materials = [
            "XOM", "CVX", "COP", "EOG", "PXD", "DVN", "FANG", "OXY", "HES", "MRO",
            "APA", "MTDR", "PR", "CTRA", "OVV", "SM", "RRC", "AR", "SWN", "EQT",
            "SLB", "HAL", "BKR", "NOV", "FTI", "HP", "OII", "RIG", "DO", "VAL",
            "VLO", "MPC", "PSX", "DINO", "PBF", "HFC", "DK", "CVI", "PAR", "PARR",
            "LIN", "APD", "ECL", "SHW", "PPG", "NEM", "FCX", "NUE", "STLD", "CLF",
            "AA", "ATI", "CMC", "RS", "SCHN", "ZEUS", "X", "ARNC", "CENX", "KALU"
        ]
        
        # Industrials & Defense (60)
        industrials = [
            "GE", "HON", "MMM", "CAT", "DE", "EMR", "ETN", "ROK", "AME", "ROP",
            "IR", "PH", "ITW", "DOV", "GNRC", "CMI", "PCAR", "AGCO", "OSK", "TEX",
            "BA", "LMT", "RTX", "NOC", "GD", "LHX", "HII", "TDG", "TXT", "HWM",
            "UPS", "FDX", "XPO", "JBHT", "KNX", "WERN", "LSTR", "ODFL", "SAIA", "OLD",
            "CSX", "UNP", "NSC", "KSU", "CP", "CNI", "WAB", "TRN", "GBX", "RAIL",
            "AAL", "UAL", "DAL", "LUV", "ALK", "JBLU", "SAVE", "HA", "SKYW", "MESA"
        ]
        
        # Combine all lists and remove duplicates
        all_symbols = (etfs + sp500 + nasdaq_growth + high_volume + 
                       biotech + financials + energy_materials + industrials)
        unique_symbols = list(dict.fromkeys(all_symbols))  # Preserve order, remove dupes
        
        return unique_symbols
    
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
    
    async def start_liquid_collection(
        self,
        bar_size: str = "1 day",
        duration: str = "1 M",
        min_adv: int = 100_000
    ) -> Dict[str, Any]:
        """
        Start collection for LIQUID US stocks only (filtered by ADV).
        
        This is faster than full market (~2-3 hours vs 10+ hours) and focuses
        on stocks that are actually tradeable with good liquidity.
        
        Args:
            bar_size: Bar size (default "1 day")
            duration: Duration per request (default "1 M" = 1 month)
            min_adv: Minimum average daily volume (default 100K)
            
        Returns:
            Job info dict
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "Another collection job is already running",
                "current_job": self._running_job.to_dict()
            }
            
        # Get liquid symbols
        logger.info(f"Fetching liquid US stocks (ADV >= {min_adv:,})...")
        symbols = await self.get_liquid_symbols(min_adv=min_adv)
        
        if not symbols:
            return {
                "success": False,
                "error": "Could not fetch liquid stock list."
            }
            
        logger.info(f"Starting liquid collection for {len(symbols)} symbols (ADV >= {min_adv:,})")
        
        # Start collection
        return await self.start_collection(
            symbols=symbols,
            bar_size=bar_size,
            duration=duration,
            use_defaults=False
        )
    
    async def start_smart_collection(
        self,
        duration: str = "1 M",
        include_intraday: bool = True,
        include_swing: bool = True,
        include_investment: bool = True
    ) -> Dict[str, Any]:
        """
        Smart multi-timeframe collection that matches ADV filters to trading styles.
        
        This collects different bar sizes for different liquidity tiers:
        - Intraday bars (1min, 5min): Only for high-ADV stocks (>= 500K) 
        - Swing bars (15min, 1hour): For medium-ADV stocks (>= 100K)
        - Investment bars (1day): For all tradeable stocks (>= 50K)
        
        This approach:
        1. Saves time by not collecting intraday data for illiquid stocks
        2. Matches your bot's actual ADV requirements per trading style
        3. Still provides comprehensive coverage for each use case
        
        Args:
            duration: Duration per request (default "1 M" = 1 month)
            include_intraday: Collect 1min/5min for intraday-worthy stocks
            include_swing: Collect 15min/1hour for swing-worthy stocks  
            include_investment: Collect 1day for investment-worthy stocks
            
        Returns:
            Collection plan with time estimates
        """
        # ADV thresholds (share volume, not dollar volume)
        # These match typical scanner filters for tradeable stocks
        ADV_INTRADAY = 500_000    # 500K shares/day - liquid enough for scalping/day trading
        ADV_SWING = 100_000       # 100K shares/day - liquid enough for swing trades  
        ADV_INVESTMENT = 50_000   # 50K shares/day - minimum for any position
        
        # Get symbol counts for each tier
        intraday_symbols = await self.get_liquid_symbols(min_adv=ADV_INTRADAY) if include_intraday else []
        swing_symbols = await self.get_liquid_symbols(min_adv=ADV_SWING) if include_swing else []
        investment_symbols = await self.get_liquid_symbols(min_adv=ADV_INVESTMENT) if include_investment else []
        
        # Build collection plan
        time_per_request = 3  # seconds
        
        plan = {
            "intraday": {
                "bar_sizes": ["1 min", "5 mins"],
                "adv_threshold": ADV_INTRADAY,
                "symbol_count": len(intraday_symbols),
                "requests": len(intraday_symbols) * 2,
                "estimated_hours": (len(intraday_symbols) * 2 * time_per_request) / 3600
            },
            "swing": {
                "bar_sizes": ["15 mins", "1 hour"],
                "adv_threshold": ADV_SWING,
                "symbol_count": len(swing_symbols),
                "requests": len(swing_symbols) * 2,
                "estimated_hours": (len(swing_symbols) * 2 * time_per_request) / 3600
            },
            "investment": {
                "bar_sizes": ["1 day"],
                "adv_threshold": ADV_INVESTMENT,
                "symbol_count": len(investment_symbols),
                "requests": len(investment_symbols),
                "estimated_hours": (len(investment_symbols) * time_per_request) / 3600
            }
        }
        
        total_requests = (
            plan["intraday"]["requests"] + 
            plan["swing"]["requests"] + 
            plan["investment"]["requests"]
        )
        total_hours = (
            plan["intraday"]["estimated_hours"] + 
            plan["swing"]["estimated_hours"] + 
            plan["investment"]["estimated_hours"]
        )
        
        return {
            "success": True,
            "mode": "smart_tiered_collection",
            "plan": plan,
            "total_requests": total_requests,
            "total_estimated_hours": round(total_hours, 1),
            "note": "Smart collection matches ADV requirements to trading styles",
            "ready_to_start": False,
            "start_endpoint": "POST /api/ib-collector/start-smart-collection-run"
        }
    
    async def run_smart_collection(
        self,
        duration: str = "1 M",
        include_intraday: bool = True,
        include_swing: bool = True,
        include_investment: bool = True,
        skip_recent: bool = True,
        recent_days_threshold: int = 7,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Execute the smart tiered collection plan.
        
        Runs all tiers sequentially: intraday -> swing -> investment
        Automatically skips symbols that already have recent data.
        
        Args:
            skip_recent: If True, skip symbols with data collected within recent_days_threshold
            recent_days_threshold: Days threshold for considering data "recent"
            force_refresh: If True, collect all symbols regardless of existing data
        """
        # Redirect to per-stock collection (the new standard approach)
        logger.info("Smart collection now uses per-stock multi-timeframe approach")
        return await self.run_per_stock_collection(
            lookback_days=30,
            skip_recent=skip_recent,
            recent_days_threshold=recent_days_threshold,
            max_symbols=None
        )
    
    def get_safe_duration(self, bar_size: str, lookback_days: int) -> str:
        """
        Calculate a safe IB duration string based on 2000 bar limit.
        
        IB Max Bars Per Request: 2000
        
        Calculated limits (bars ÷ bars_per_day):
        - 1 min:   2000 ÷ 390 = ~5 days   → max "1 W"
        - 5 mins:  2000 ÷ 78  = ~25 days  → max "1 M"
        - 15 mins: 2000 ÷ 26  = ~77 days  → max "3 M"
        - 30 mins: 2000 ÷ 13  = ~154 days → max "6 M"
        - 1 hour:  2000 ÷ 7   = ~285 days → max "1 Y"
        - 1 day:   2000 bars  = ~8 years  → max "8 Y"
        - 1 week:  2000 bars  = ~38 years → max "20 Y" (IB cap)
        
        Args:
            bar_size: The bar size string (e.g., "1 min", "5 mins")
            lookback_days: Desired lookback in trading days
            
        Returns:
            Safe IB duration string (e.g., "1 D", "1 W", "1 M")
        """
        bar_config = self.BAR_CONFIGS.get(bar_size, {})
        max_history = bar_config.get("max_history_days", 365)
        effective_lookback = min(lookback_days, max_history)
        
        if bar_size == "1 min":
            # Max ~5 trading days per request (2000 bars ÷ 390 bars/day)
            if effective_lookback >= 5:
                return "1 W"
            elif effective_lookback >= 2:
                return f"{effective_lookback + 2} D"  # Add buffer for weekends
            return "1 D"
            
        elif bar_size == "5 mins":
            # Max ~25 trading days per request
            if effective_lookback >= 20:
                return "1 M"
            elif effective_lookback >= 10:
                return "2 W"
            elif effective_lookback >= 5:
                return "1 W"
            return f"{effective_lookback + 2} D"
            
        elif bar_size == "15 mins":
            # Max ~77 trading days per request
            if effective_lookback >= 60:
                return "3 M"
            elif effective_lookback >= 40:
                return "2 M"
            elif effective_lookback >= 20:
                return "1 M"
            elif effective_lookback >= 10:
                return "2 W"
            return "1 W"
            
        elif bar_size == "30 mins":
            # Max ~154 trading days per request
            if effective_lookback >= 120:
                return "6 M"
            elif effective_lookback >= 60:
                return "3 M"
            elif effective_lookback >= 40:
                return "2 M"
            elif effective_lookback >= 20:
                return "1 M"
            return "2 W"
            
        elif bar_size == "1 hour":
            # Max ~285 trading days per request
            if effective_lookback >= 200:
                return "1 Y"
            elif effective_lookback >= 120:
                return "6 M"
            elif effective_lookback >= 60:
                return "3 M"
            elif effective_lookback >= 20:
                return "1 M"
            return "2 W"
            
        elif bar_size == "1 day":
            # Max ~2000 trading days per request (~8 years)
            if effective_lookback >= 1260:
                return "5 Y"
            elif effective_lookback >= 504:
                return "2 Y"
            elif effective_lookback >= 252:
                return "1 Y"
            elif effective_lookback >= 126:
                return "6 M"
            elif effective_lookback >= 63:
                return "3 M"
            elif effective_lookback >= 22:
                return "1 M"
            return f"{effective_lookback} D"
            
        elif bar_size == "1 week":
            # Max 2000 weeks (~38 years), but IB caps history at ~20 years
            if effective_lookback >= 2520:
                return "10 Y"
            elif effective_lookback >= 1260:
                return "5 Y"
            elif effective_lookback >= 504:
                return "2 Y"
            elif effective_lookback >= 252:
                return "1 Y"
            return "6 M"
            
        else:
            return bar_config.get("max_duration", "1 D")

    def get_max_duration_for_bar_size(self, bar_size: str) -> str:
        """
        Get the maximum IB duration string for a given bar size.
        This maximizes data per request while respecting IB's 2000 bar limit.
        
        Returns the max_duration from BAR_CONFIGS which is calculated as:
        - 2000 bars ÷ bars_per_day = max trading days per request
        """
        bar_config = self.BAR_CONFIGS.get(bar_size, {})
        return bar_config.get("max_duration", "1 M")
    
    def get_max_lookback_days(self, bar_size: str) -> int:
        """
        Get the maximum lookback days IB allows for a given bar size.
        Use this to request the maximum history available.
        """
        bar_config = self.BAR_CONFIGS.get(bar_size, {})
        return bar_config.get("max_history_days", 365)

    def generate_chain_requests(
        self,
        bar_size: str,
        earliest_existing_date: str = None,
    ) -> list:
        """
        Generate a list of chained (duration, end_date) pairs that cover
        the maximum IB lookback for a given bar size.

        If the symbol already has data starting at `earliest_existing_date`,
        chains are generated ONLY for the missing window between that date
        and the max lookback start — avoiding redundant fetches.

        Returns:
            List of dicts with keys: duration, end_date (IB format string)
            Empty list if existing data already covers the full lookback.
        """
        config = self.BAR_CONFIGS.get(bar_size)
        if not config:
            return []

        max_duration = config["max_duration"]
        max_lookback_days = config["max_history_days"]
        step_days = DURATION_TO_CALENDAR_DAYS.get(max_duration, 30)

        now = datetime.now(timezone.utc)
        max_lookback_start = now - timedelta(days=max_lookback_days)

        # Determine where to start chaining backward from
        if earliest_existing_date:
            # Parse the earliest date we already have
            if isinstance(earliest_existing_date, str):
                try:
                    chain_from = datetime.fromisoformat(
                        earliest_existing_date.replace("Z", "+00:00")
                    )
                except ValueError:
                    try:
                        chain_from = datetime.strptime(
                            earliest_existing_date[:10], "%Y-%m-%d"
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        chain_from = now
            elif isinstance(earliest_existing_date, datetime):
                chain_from = earliest_existing_date
            else:
                chain_from = now

            if chain_from.tzinfo is None:
                chain_from = chain_from.replace(tzinfo=timezone.utc)
        else:
            # No existing data — chain backward from now
            chain_from = now

        # If existing data already goes back far enough, nothing to do
        if chain_from <= max_lookback_start:
            return []

        chains = []
        current_end = chain_from

        while current_end > max_lookback_start:
            # IB endDateTime format: "YYYYMMDD-HH:MM:SS UTC"
            end_date_str = current_end.strftime("%Y%m%d-%H:%M:%S") + " UTC"
            chains.append({
                "duration": max_duration,
                "end_date": end_date_str,
            })
            current_end -= timedelta(days=step_days)

        return chains

    
    def get_symbol_tier(self, avg_volume: float, avg_dollar_volume: float = None, atr_pct: float = None) -> str:
        """Determine which tier a symbol belongs to.
        
        Uses dollar volume (preferred) with ATR% filtering.
        Falls back to share volume if dollar volume not available.
        """
        # ATR% filter — skip symbols outside tradeable range
        if atr_pct is not None:
            if atr_pct < self.ATR_PCT_THRESHOLDS["min"] or atr_pct > self.ATR_PCT_THRESHOLDS["max"]:
                return "skip"
        
        # Use dollar volume if available
        if avg_dollar_volume is not None and avg_dollar_volume > 0:
            if avg_dollar_volume >= self.DOLLAR_VOL_THRESHOLDS["intraday"]:
                return "intraday"
            elif avg_dollar_volume >= self.DOLLAR_VOL_THRESHOLDS["swing"]:
                return "swing"
            elif avg_dollar_volume >= self.DOLLAR_VOL_THRESHOLDS["investment"]:
                return "investment"
            return "skip"
        
        # Fallback to share volume
        if avg_volume >= self.ADV_THRESHOLDS["intraday"]:
            return "intraday"
        elif avg_volume >= self.ADV_THRESHOLDS["swing"]:
            return "swing"
        elif avg_volume >= self.ADV_THRESHOLDS["investment"]:
            return "investment"
        return "skip"
    
    async def run_per_stock_collection(
        self,
        lookback_days: int = 30,
        skip_recent: bool = True,
        recent_days_threshold: int = 7,
        max_symbols: int = None,
        specific_symbols: List[str] = None,
        use_max_lookback: bool = False,
        only_bar_sizes: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Collect ALL applicable timeframes for each stock before moving to the next.
        
        This approach ensures complete data per symbol:
        - TSLA (500K+ ADV): 1min, 3min, 5min, 15min, 30min, 1hr, 1day collected
        - Then AAPL: 1min, 3min, 5min, 15min, 30min, 1hr, 1day collected
        - etc.
        
        A stock with 100K ADV would only get: 15min, 30min, 1hr, 1day
        A stock with 50K ADV would only get: 1day, 1week
        
        Args:
            lookback_days: How many days of history to fetch (ignored if use_max_lookback=True)
            skip_recent: Skip symbols that were collected within recent_days_threshold
            recent_days_threshold: Days threshold for "recent" data
            max_symbols: Limit number of symbols (None = all)
            specific_symbols: Optional list of specific symbols to collect (overrides ADV query)
            use_max_lookback: If True, use maximum IB lookback per timeframe (maximizes data per request)
            
        Returns:
            Collection job info
        """
        logger.info("=" * 60)
        logger.info("STARTING PER-STOCK MULTI-TIMEFRAME COLLECTION")
        logger.info(f"Lookback: {lookback_days} days | Skip recent: {skip_recent}")
        logger.info("=" * 60)
        
        # Ensure DB is connected
        if self._db is None:
            return {"success": False, "error": "Database not initialized. Call init_ib_collector first."}
        
        # Run all heavy DB queries in a thread to avoid blocking the event loop
        adv_col = self._db["symbol_adv_cache"]
        data_col = self._data_col
        thresholds = self.ADV_THRESHOLDS
        tier_timeframes = self.TIER_TIMEFRAMES
        get_tier = self.get_symbol_tier
        get_safe_dur = self.get_safe_duration
        allowed_bar_sizes = set(only_bar_sizes) if only_bar_sizes else None
        
        def _build_queue():
            """Sync function to build the collection queue — runs in thread"""
            # If specific_symbols provided, only get those
            if specific_symbols:
                symbols_with_adv = list(adv_col.find(
                    {"symbol": {"$in": list(specific_symbols)}, "avg_volume": {"$gte": thresholds["investment"]}},
                    {"symbol": 1, "avg_volume": 1}
                ).sort("avg_volume", -1))
            else:
                symbols_with_adv = list(adv_col.find(
                    {"avg_volume": {"$gte": thresholds["investment"]}},
                    {"symbol": 1, "avg_volume": 1}
                ).sort("avg_volume", -1))
            
            if not symbols_with_adv:
                return None, None, None, None
            
            if max_symbols:
                symbols_with_adv_limited = symbols_with_adv[:max_symbols]
            else:
                symbols_with_adv_limited = symbols_with_adv
            
            # Count by tier
            tier_counts = {"intraday": 0, "swing": 0, "investment": 0}
            for sym_data in symbols_with_adv_limited:
                tier = get_tier(sym_data.get("avg_volume", 0))
                if tier in tier_counts:
                    tier_counts[tier] += 1
            
            # ── Pre-fetch earliest dates for chaining (one aggregation) ──
            earliest_dates = {}  # (symbol, bar_size) -> earliest_date_str
            if use_max_lookback and data_col is not None:
                logger.info("Querying earliest bar dates for smart chaining ...")
                pipeline = [
                    {"$group": {
                        "_id": {"symbol": "$symbol", "bar_size": "$bar_size"},
                        "earliest": {"$min": "$date"},
                    }}
                ]
                for doc in data_col.aggregate(pipeline, allowDiskUse=True):
                    _id = doc.get("_id", {})
                    sym = _id.get("symbol")
                    bs = _id.get("bar_size")
                    if sym and bs:
                        earliest_dates[(sym, bs)] = doc["earliest"]
                logger.info(f"Found existing data for {len(earliest_dates)} (symbol, bar_size) combos")
            
            # Build queue entries: each entry is (symbol, bar_size, duration, end_date)
            queue_entries = []
            chain_stats = {"single_requests": 0, "chained_requests": 0, "skipped_full_coverage": 0}
            
            for sym_data in symbols_with_adv_limited:
                symbol = sym_data["symbol"]
                avg_volume = sym_data.get("avg_volume", 0)
                tier = get_tier(avg_volume)
                
                if tier == "skip":
                    continue
                
                timeframes = tier_timeframes.get(tier, ["1 day"])
                
                # Filter to specific bar sizes if requested
                if allowed_bar_sizes:
                    timeframes = [tf for tf in timeframes if tf in allowed_bar_sizes]
                
                for bar_size in timeframes:
                    if use_max_lookback:
                        # ── CHAINING MODE: generate multiple requests to cover max lookback ──
                        earliest = earliest_dates.get((symbol, bar_size))
                        chains = generate_chains(bar_size, earliest)
                        
                        if not chains:
                            chain_stats["skipped_full_coverage"] += 1
                            continue
                        
                        for chain in chains:
                            queue_entries.append((symbol, bar_size, chain["duration"], chain["end_date"]))
                        chain_stats["chained_requests"] += len(chains)
                    else:
                        # ── SINGLE REQUEST MODE (original behavior) ──
                        duration = get_safe_dur(bar_size, lookback_days)
                        
                        if skip_recent and data_col is not None:
                            existing = data_col.find_one({
                                "symbol": symbol,
                                "bar_size": bar_size,
                                "collected_at": {"$gte": (datetime.now(timezone.utc) - timedelta(days=recent_days_threshold)).isoformat()}
                            })
                            if existing:
                                continue
                        
                        queue_entries.append((symbol, bar_size, duration, None))
                        chain_stats["single_requests"] += 1
            
            return symbols_with_adv_limited, tier_counts, queue_entries, chain_stats
        
        # Reference the chain generator from the class instance
        generate_chains = self.generate_chain_requests
        
        symbols_with_adv, tier_counts, queue_entries, chain_stats = await asyncio.to_thread(_build_queue)
        
        if symbols_with_adv is None:
            return {"success": False, "error": "No symbols found with sufficient ADV. Run ADV cache refresh first."}
        
        logger.info(f"Found {len(symbols_with_adv)} symbols to process")
        logger.info(f"Tier breakdown: {tier_counts}")
        if use_max_lookback:
            logger.info(f"Chaining stats: {chain_stats}")
        
        # Queue all requests (create_request has built-in dedup via skip_if_pending)
        from services.historical_data_queue_service import get_historical_data_queue_service
        queue_service = get_historical_data_queue_service()
        total_queued = 0
        
        for symbol, bar_size, duration, end_date in queue_entries:
            queue_service.create_request(
                symbol=symbol,
                bar_size=bar_size,
                duration=duration,
                end_date=end_date,
            )
            total_queued += 1
        
        # Auto-dedup: clean up any duplicates that slipped through
        # (e.g., from chained requests with slightly different end_dates)
        dedup_result = queue_service.deduplicate_queue()
        dedup_removed = dedup_result.get("duplicates_removed", 0)
        if dedup_removed > 0:
            logger.info(f"Auto-dedup removed {dedup_removed} duplicate queue entries")
            total_queued -= dedup_removed
        
        logger.info(f"Queued {total_queued} requests across {len(symbols_with_adv)} symbols")
        
        # Calculate estimated time (chained requests take ~3-4s each via pusher)
        seconds_per_request = 3.5 if use_max_lookback else self.REQUEST_DELAY_SECONDS
        estimated_seconds = total_queued * seconds_per_request
        estimated_hours = round(estimated_seconds / 3600, 1)
        if estimated_hours >= 24:
            estimated_display = f"{estimated_hours / 24:.1f} days ({estimated_hours} hours)"
        elif estimated_hours >= 1:
            estimated_display = f"{estimated_hours} hours"
        else:
            estimated_display = f"{int(estimated_seconds / 60)} minutes"
        
        result = {
            "success": True,
            "message": f"Per-stock collection queued: {total_queued} requests for {len(symbols_with_adv)} symbols",
            "symbols": len(symbols_with_adv),
            "tier_counts": tier_counts,
            "total_requests": total_queued,
            "timeframes_by_tier": self.TIER_TIMEFRAMES,
            "estimated_time": estimated_display,
            "estimated_hours": estimated_hours,
            "rate_per_minute": int(60 / self.REQUEST_DELAY_SECONDS),
            "use_max_lookback": use_max_lookback,
            "note": "Collection processes queue in order - each stock gets all its timeframes before moving to next"
        }
        
        if use_max_lookback:
            result["chaining"] = {
                "enabled": True,
                "chained_requests": chain_stats.get("chained_requests", 0),
                "skipped_full_coverage": chain_stats.get("skipped_full_coverage", 0),
                "explanation": "Requests are chained backward in time using end_date to cover the full IB lookback window",
            }
        
        return result
    
    async def start_collection(
        self,
        symbols: List[str] = None,
        bar_size: str = "5 mins",
        duration: str = "1 M",
        use_defaults: bool = True,
        skip_recent: bool = True,
        recent_days_threshold: int = 7,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Start a historical data collection job.
        
        Args:
            symbols: List of symbols to collect (uses defaults if None)
            bar_size: Bar size (1 min, 5 mins, 15 mins, 1 hour, 1 day)
            duration: Duration per request (1 D, 2 D, 1 W, 1 M, etc.)
            use_defaults: If True and no symbols provided, use default list
            skip_recent: If True, skip symbols that already have recent data
            recent_days_threshold: Consider data "recent" if collected within this many days
            force_refresh: If True, collect all symbols regardless of existing data
            
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
        
        original_count = len(symbols)
        
        # Filter out symbols with recent data (unless force_refresh)
        if skip_recent and not force_refresh:
            symbols = self.filter_symbols_needing_collection(
                symbols=symbols,
                bar_size=bar_size,
                days_threshold=recent_days_threshold,
                force_refresh=force_refresh
            )
            
        if not symbols:
            return {
                "success": True,
                "message": f"All {original_count} symbols already have recent data (within {recent_days_threshold} days). Nothing to collect.",
                "skipped": original_count,
                "collected": 0
            }
                
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
        """
        Run the collection job using async batch approach.
        
        Instead of blocking for each symbol, we:
        1. Create all requests in batch (fast)
        2. Start a background task to monitor and store results
        3. The local IB Data Pusher processes them at its own pace
        """
        job.status = CollectionStatus.RUNNING
        self._update_job(job)
        
        try:
            from services.historical_data_queue_service import get_historical_data_queue_service
            queue_service = get_historical_data_queue_service()
            
            total_symbols = len(job.symbols)
            logger.info(f"Starting async collection for {total_symbols} symbols (job: {job.id})")
            
            # Create all requests in batch (fast, no blocking!)
            batch_result = queue_service.create_batch_requests(
                symbols=job.symbols,
                duration=job.duration,
                bar_size=job.bar_size,
                job_id=job.id
            )
            
            logger.info(f"Created {batch_result['created']} requests in queue for job {job.id}")
            
            # Now monitor progress and store completed data
            await self._monitor_and_store_results(job, queue_service)
                
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
    
    async def _monitor_and_store_results(self, job: CollectionJob, queue_service):
        """
        Monitor queue progress and store completed data to the database.
        This runs in the background while the local pusher processes requests.
        """
        from datetime import datetime, timezone
        
        last_completed = 0
        stall_count = 0
        max_stall_checks = 60  # After 60 checks with no progress (5 mins), consider it stalled
        
        while True:
            # Check if cancellation was requested
            if self._cancel_requested:
                queue_service.cancel_job(job.id)
                job.status = CollectionStatus.CANCELLED
                logger.info(f"Job {job.id} cancelled")
                break
            
            # Get current progress from queue
            progress = queue_service.get_job_progress(job.id)
            
            # Update job stats
            job.symbols_completed = progress["completed"]
            job.symbols_failed = progress["failed"]
            job.progress_pct = progress["progress_pct"]
            
            # Store any newly completed data
            await self._store_completed_data(job, queue_service)
            
            # Check if done
            if progress["is_complete"]:
                # Get final error list
                errors = queue_service.get_job_errors(job.id, limit=50)
                job.errors = [f"{e['symbol']}: {e.get('error', 'Unknown')}" for e in errors]
                
                if job.symbols_failed == 0:
                    job.status = CollectionStatus.COMPLETED
                    logger.info(f"Job {job.id} completed successfully: {job.symbols_completed} symbols")
                    # Check if auto-training is enabled
                    await self._trigger_auto_training_if_enabled()
                else:
                    job.status = CollectionStatus.COMPLETED  # Still "completed" but with errors
                    logger.info(f"Job {job.id} completed with {job.symbols_failed} failures")
                    # Still trigger training even with some failures
                    await self._trigger_auto_training_if_enabled()
                break
            
            # Check for stalls (no progress)
            if progress["completed"] == last_completed and progress["pending"] > 0:
                stall_count += 1
                if stall_count >= max_stall_checks:
                    logger.warning(f"Job {job.id} stalled - no progress for 5 minutes")
                    # Don't fail - just note it. Pusher might be temporarily offline
                    job.errors.append("Collection stalled - is your local IB Data Pusher running?")
            else:
                stall_count = 0
                last_completed = progress["completed"]
            
            # Update job in DB
            self._update_job(job)
            
            # Wait before next check
            await asyncio.sleep(5)
    
    async def _store_completed_data(self, job: CollectionJob, queue_service):
        """Store completed bar data from the queue to the main database"""
        if self._data_col is None:
            return
        
        # Get completed requests that have data
        completed = queue_service.get_job_completed_data(job.id)
        
        for item in completed:
            symbol = item.get("symbol")
            bar_size = item.get("bar_size", job.bar_size)
            bars = item.get("data", [])
            
            if not bars:
                continue
            
            for bar in bars:
                try:
                    self._data_col.update_one(
                        {
                            "symbol": symbol,
                            "bar_size": bar_size,
                            "date": bar.get("date") or bar.get("time")
                        },
                        {
                            "$set": {
                                "open": bar.get("open"),
                                "high": bar.get("high"),
                                "low": bar.get("low"),
                                "close": bar.get("close"),
                                "volume": bar.get("volume"),
                                "collected_at": datetime.now(timezone.utc).isoformat()
                            }
                        },
                        upsert=True
                    )
                    job.total_bars_collected += 1
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        logger.warning(f"Error storing bar for {symbol}: {e}")
            
            # Mark this data as processed by clearing it from queue
            # (The queue will auto-cleanup old completed requests)
            
    async def _collect_symbol_data(
        self, 
        symbol: str, 
        bar_size: str, 
        duration: str
    ) -> int:
        """
        Collect historical data for a single symbol via the IB Data Pusher queue.
        
        The cloud backend queues the request, and the local IB Data Pusher
        fulfills it by fetching from IB Gateway.
        
        Returns number of bars collected.
        """
        bars_collected = 0
        retries = 0
        
        while retries < self.MAX_RETRIES:
            try:
                # Use the historical data queue instead of direct IB connection
                from services.historical_data_queue_service import get_historical_data_queue_service
                
                try:
                    queue_service = get_historical_data_queue_service()
                except Exception as e:
                    logger.warning(f"Historical data queue not available: {e}")
                    raise Exception("Historical data queue service not available - is the backend properly initialized?")
                
                # Create request in queue
                request_id = queue_service.create_request(
                    symbol=symbol,
                    duration=duration,
                    bar_size=bar_size
                )
                
                logger.info(f"Created historical data request {request_id} for {symbol}")
                
                # Wait for IB Data Pusher to fulfill the request (max 180 seconds - IB can be slow)
                result = queue_service.get_request_result(request_id, timeout=180.0)
                
                if result is None:
                    raise Exception("Timeout waiting for IB Data Pusher response - is your local app running?")
                
                if result.get("status") == "completed" and result.get("data"):
                    bars = result["data"]
                    
                    # Store in database
                    if self._data_col is not None:
                        for bar in bars:
                            try:
                                self._data_col.update_one(
                                    {
                                        "symbol": symbol,
                                        "bar_size": bar_size,
                                        "date": bar.get("date") or bar.get("time")
                                    },
                                    {
                                        "$set": {
                                            "open": bar.get("open"),
                                            "high": bar.get("high"),
                                            "low": bar.get("low"),
                                            "close": bar.get("close"),
                                            "volume": bar.get("volume"),
                                            "collected_at": datetime.now(timezone.utc).isoformat()
                                        }
                                    },
                                    upsert=True
                                )
                                bars_collected += 1
                            except Exception as e:
                                if "duplicate" not in str(e).lower():
                                    logger.warning(f"Error storing bar for {symbol}: {e}")
                                    
                    return bars_collected
                elif result.get("status") == "failed":
                    error = result.get("error", "Unknown error from IB Data Pusher")
                    raise Exception(error)
                else:
                    logger.warning(f"No data returned for {symbol}")
                    return 0
                        
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
    
    async def resume_monitoring(self) -> Dict[str, Any]:
        """
        Resume monitoring the queue and storing completed data.
        
        Use this after your machine wakes up from sleep - it restarts
        the background task that processes completed requests.
        """
        if self._running_job and self._running_job.status == CollectionStatus.RUNNING:
            return {
                "success": False,
                "error": "A job is already running",
                "job_id": self._running_job.id
            }
        
        try:
            from services.historical_data_queue_service import get_historical_data_queue_service
            queue_service = get_historical_data_queue_service()
            
            # Get current queue state
            stats = queue_service.get_overall_queue_stats()
            
            if stats["pending"] == 0 and stats["claimed"] == 0:
                return {
                    "success": True,
                    "message": "No pending work - collection complete",
                    "stats": stats
                }
            
            # Create a resume job
            job = CollectionJob(
                id=f"resume_{uuid.uuid4().hex[:8]}",
                symbols=[],  # We don't need the full list, we monitor the queue
                bar_size="1 day",
                duration="1 M",
                start_time=datetime.now(timezone.utc).isoformat()
            )
            job.status = CollectionStatus.RUNNING
            
            self._running_job = job
            self._cancel_requested = False
            
            # Save job
            if self._jobs_col is not None:
                self._jobs_col.insert_one(job.to_dict())
            
            # Start monitoring in background
            asyncio.create_task(self._resume_monitor_loop(job, queue_service))
            
            return {
                "success": True,
                "message": f"Resumed monitoring - {stats['pending']} pending, {stats['claimed']} processing",
                "job_id": job.id,
                "stats": stats
            }
            
        except Exception as e:
            logger.error(f"Error resuming monitoring: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _resume_monitor_loop(self, job: CollectionJob, queue_service):
        """Monitor loop for resumed collection - just stores completed data"""
        try:
            logger.info(f"Starting resume monitor loop for job {job.id}")
            
            while True:
                if self._cancel_requested:
                    job.status = CollectionStatus.CANCELLED
                    break
                
                # Get progress
                stats = queue_service.get_overall_queue_stats()
                
                # Store any completed data
                await self._store_all_completed_data(queue_service)
                
                # Update job stats
                job.symbols_completed = stats["completed"]
                job.symbols_failed = stats["failed"]
                total = stats["pending"] + stats["claimed"] + stats["completed"] + stats["failed"]
                done = stats["completed"] + stats["failed"]
                job.progress_pct = (done / total * 100) if total > 0 else 100
                
                self._update_job(job)
                
                # Check if done
                if stats["pending"] == 0 and stats["claimed"] == 0:
                    job.status = CollectionStatus.COMPLETED
                    logger.info(f"Resume job {job.id} complete: {stats['completed']} completed, {stats['failed']} failed")
                    break
                
                await asyncio.sleep(5)
                
        except Exception as e:
            job.status = CollectionStatus.FAILED
            job.errors.append(str(e))
            logger.error(f"Resume monitor error: {e}")
            
        finally:
            job.end_time = datetime.now(timezone.utc).isoformat()
            self._update_job(job)
            self._running_job = None
    
    async def _store_all_completed_data(self, queue_service):
        """Store all completed data from queue to main database"""
        if self._data_col is None:
            return
        
        # Get completed requests with data
        completed = queue_service.get_job_completed_data(None)  # Get all completed
        
        stored_count = 0
        for item in completed:
            symbol = item.get("symbol")
            bar_size = item.get("bar_size", "1 day")
            bars = item.get("data", [])
            request_id = item.get("request_id")
            
            if not bars:
                continue
            
            for bar in bars:
                try:
                    self._data_col.update_one(
                        {
                            "symbol": symbol,
                            "bar_size": bar_size,
                            "date": bar.get("date") or bar.get("time")
                        },
                        {
                            "$set": {
                                "open": bar.get("open"),
                                "high": bar.get("high"),
                                "low": bar.get("low"),
                                "close": bar.get("close"),
                                "volume": bar.get("volume"),
                                "collected_at": datetime.now(timezone.utc).isoformat()
                            }
                        },
                        upsert=True
                    )
                    stored_count += 1
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        logger.warning(f"Error storing bar for {symbol}: {e}")
            
            # Mark this data as stored to avoid re-processing
            if request_id:
                queue_service.mark_data_stored(request_id)
        
        if stored_count > 0:
            logger.info(f"Stored {stored_count} bars from completed requests")
        
        
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
        """Get statistics about collected data.

        Optimized for very large collections:
        - Total bars: estimated_document_count() (reads collection metadata, instant).
        - Unique symbol count: DISTINCT_SCAN on the compound index (fast).
        - Per-bar-size symbol count: one DISTINCT_SCAN per bar size (fast).
        Avoids full-collection $group aggregations that scan every document
        and time out on 178M+ row collections.
        """
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}

        try:
            # Fast total count from collection metadata (instant, no scan)
            total_bars = self._data_col.estimated_document_count()

            # Unique symbol count from index (fast DISTINCT_SCAN)
            try:
                unique_count = len(self._data_col.distinct("symbol", maxTimeMS=10000))
            except Exception:
                unique_count = 0

            # Per-bar-size: DISTINCT_SCAN on the compound (symbol, bar_size, date)
            # index for each known bar size. One short index scan each.
            bar_stats = {}
            for bs in self.BAR_CONFIGS.keys():
                try:
                    syms = self._data_col.distinct(
                        "symbol", {"bar_size": bs}, maxTimeMS=10000
                    )
                    if syms:
                        bar_stats[bs] = {"symbols": len(syms)}
                except Exception as e:
                    logger.debug(f"distinct failed for {bs}: {e}")

            return {
                "success": True,
                "stats": {
                    "unique_symbols": unique_count,
                    "by_bar_size": bar_stats,
                    "total_bars": total_bars,
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

    async def _trigger_auto_training_if_enabled(self):
        """Check if auto-training is enabled and trigger training after data collection"""
        try:
            if self._db is None:
                return
            
            # Check auto-training settings
            settings_col = self._db["system_settings"]
            settings = settings_col.find_one({"key": "auto_training"})
            
            if not settings or not settings.get("value", {}).get("after_collection"):
                logger.info("Auto-training after collection is disabled")
                return
            
            logger.info("Auto-training triggered after data collection...")
            
            # Import and trigger training
            from services.ai_modules.timeseries_service import get_timeseries_ai
            ts_service = get_timeseries_ai()
            
            if ts_service:
                result = await ts_service.train_model()
                if result.get("success"):
                    logger.info(f"Auto-training completed: {result.get('message', 'Success')}")
                    
                    # Log to training history
                    history_col = self._db["training_history"]
                    history_col.insert_one({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "trigger": "after_collection",
                        "success": True,
                        "result": result
                    })
                else:
                    logger.warning(f"Auto-training failed: {result.get('error', 'Unknown')}")
            else:
                logger.warning("TimeSeriesService not available for auto-training")
                
        except Exception as e:
            logger.error(f"Error triggering auto-training: {e}")
    
    def get_latest_bar_dates(self, bar_size: str = None) -> Dict[str, Any]:
        """
        Get the latest bar date for each symbol/timeframe combination.
        Used to determine what incremental data to fetch.

        Fast path: leverages the compound index (symbol, bar_size, date) via
        MongoDB's DISTINCT_SCAN — enumerates distinct symbols and per-symbol
        bar_sizes using index-only operations, then does O(log n) index-backed
        `find_one().sort('date', -1)` lookups per pair. Completes in seconds
        even on the 178M-row ib_historical_data collection (previously this
        method ran a $group aggregation that scanned every document and took
        multi-minute wall-time, blocking the FastAPI event loop).

        Returns:
            Dict with symbol -> {timeframe: {latest_date}}
        """
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}

        try:
            # 1) Distinct symbols — DISTINCT_SCAN on the compound index.
            if bar_size:
                symbols = self._data_col.distinct("symbol", {"bar_size": bar_size})
            else:
                symbols = self._data_col.distinct("symbol")

            by_symbol: Dict[str, Dict[str, Any]] = {}
            for sym in symbols:
                # 2) For each symbol, distinct bar_sizes — also DISTINCT_SCAN.
                if bar_size:
                    sizes = [bar_size]
                else:
                    sizes = self._data_col.distinct("bar_size", {"symbol": sym})

                for tf in sizes:
                    # 3) Index-backed newest-bar lookup — O(log n), uses the
                    # compound (symbol, bar_size, date) index directly.
                    latest_doc = self._data_col.find_one(
                        {"symbol": sym, "bar_size": tf},
                        {"_id": 0, "date": 1},
                        sort=[("date", -1)],
                    )
                    if not latest_doc:
                        continue
                    by_symbol.setdefault(sym, {})[tf] = {
                        "latest_date": latest_doc.get("date"),
                    }

            return {
                "success": True,
                "total_symbols": len(by_symbol),
                "by_symbol": by_symbol,
            }

        except Exception as e:
            logger.error(f"Error getting latest bar dates: {e}")
            return {"success": False, "error": str(e)}
    
    def calculate_incremental_needs(self) -> Dict[str, Any]:
        """
        Analyze what incremental data needs to be fetched.
        
        Compares latest bar dates against today to determine how many
        days of new data to fetch per symbol/timeframe.
        
        Returns:
            Dict with symbols needing updates and recommended lookback per timeframe
        """
        if self._data_col is None:
            return {"success": False, "error": "Database not connected"}
        
        try:
            from datetime import datetime, timezone, timedelta
            
            today = datetime.now(timezone.utc).date()
            
            # Get latest dates for all data
            latest_data = self.get_latest_bar_dates()
            if not latest_data.get("success"):
                return latest_data
            
            by_symbol = latest_data.get("by_symbol", {})
            
            # Calculate days since last bar for each symbol/timeframe
            needs_update = {}
            summary = {
                "up_to_date": 0,
                "needs_1_day": 0,
                "needs_2_7_days": 0,
                "needs_8_30_days": 0,
                "needs_30_plus_days": 0
            }
            
            for symbol, timeframes in by_symbol.items():
                symbol_needs = {}
                for tf, data in timeframes.items():
                    latest_str = data.get("latest_date", "")
                    if latest_str:
                        try:
                            # Parse the date string
                            if "T" in latest_str:
                                latest_date = datetime.fromisoformat(latest_str.replace("Z", "+00:00")).date()
                            else:
                                latest_date = datetime.strptime(latest_str[:10], "%Y-%m-%d").date()
                            
                            days_behind = (today - latest_date).days
                            
                            if days_behind <= 1:
                                summary["up_to_date"] += 1
                            elif days_behind <= 7:
                                summary["needs_2_7_days"] += 1
                                symbol_needs[tf] = days_behind + 1  # Add 1 day buffer
                            elif days_behind <= 30:
                                summary["needs_8_30_days"] += 1
                                symbol_needs[tf] = days_behind + 1
                            else:
                                summary["needs_30_plus_days"] += 1
                                symbol_needs[tf] = min(days_behind + 1, 365)  # Cap at 1 year
                        except Exception as e:
                            logger.warning(f"Could not parse date {latest_str}: {e}")
                            symbol_needs[tf] = 30  # Default to 30 days
                
                if symbol_needs:
                    needs_update[symbol] = symbol_needs
            
            return {
                "success": True,
                "total_symbols_in_db": len(by_symbol),
                "symbols_needing_update": len(needs_update),
                "summary": summary,
                "needs_update": needs_update
            }
            
        except Exception as e:
            logger.error(f"Error calculating incremental needs: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # SMART BACKFILL — tier-aware + gap-aware + chained lookback
    # ------------------------------------------------------------------
    TIMEFRAMES_BY_TIER = {
        "intraday":   ["1 min", "5 mins", "15 mins", "1 hour", "1 day"],
        "swing":      ["5 mins", "30 mins", "1 hour", "1 day"],
        "investment": ["1 hour", "1 day", "1 week"],
    }
    # Conservative IB single-request max durations per bar_size (calendar days)
    MAX_DAYS_PER_REQUEST = {
        "1 min":   5,
        "5 mins":  30,
        "15 mins": 90,
        "30 mins": 90,
        "1 hour":  365,
        "1 day":   730,
        "1 week":  1825,
    }
    DURATION_STRING = {
        "1 min":   "5 D",
        "5 mins":  "1 M",
        "15 mins": "3 M",
        "30 mins": "3 M",
        "1 hour":  "1 Y",
        "1 day":   "2 Y",
        "1 week":  "5 Y",
    }

    def _smart_backfill_sync(self, dry_run: bool, tier_filter: Optional[str],
                             freshness_days: int) -> Dict[str, Any]:
        """Blocking implementation — must be wrapped in asyncio.to_thread."""
        from datetime import datetime, timedelta, timezone
        import uuid
        from collections import Counter

        if self._db is None or self._data_col is None:
            return {"success": False, "error": "database not initialized"}

        adv = self._db["symbol_adv_cache"]
        queue = self._db["historical_data_requests"]

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        # 1) Classify qualified symbols by dollar-volume tier (fallback to
        # stored `tier` field if the doc has it, from rebuild_adv_from_ib).
        min_dv = self.DOLLAR_VOL_THRESHOLDS["investment"]
        qualified: Dict[str, List[str]] = {"intraday": [], "swing": [], "investment": []}
        for doc in adv.find({"avg_dollar_volume": {"$gte": min_dv}},
                            {"_id": 0, "symbol": 1, "avg_dollar_volume": 1, "tier": 1}):
            sym = doc.get("symbol")
            if not sym:
                continue
            tier = doc.get("tier")
            if tier not in self.TIMEFRAMES_BY_TIER:
                dv = doc.get("avg_dollar_volume", 0) or 0
                if   dv >= self.DOLLAR_VOL_THRESHOLDS["intraday"]:   tier = "intraday"
                elif dv >= self.DOLLAR_VOL_THRESHOLDS["swing"]:      tier = "swing"
                elif dv >= self.DOLLAR_VOL_THRESHOLDS["investment"]: tier = "investment"
                else:
                    continue
            if tier_filter and tier != tier_filter:
                continue
            qualified[tier].append(sym)

        tier_counts = {t: len(syms) for t, syms in qualified.items()}

        # 2) Plan each (symbol, bar_size): measure gap, chain if needed.
        to_queue: List[tuple] = []
        skipped_fresh = 0
        skipped_already_queued = 0

        for tier, syms in qualified.items():
            for sym in syms:
                for bs in self.TIMEFRAMES_BY_TIER[tier]:
                    # Dedupe against pending/claimed requests already there.
                    if queue.find_one({"symbol": sym, "bar_size": bs,
                                        "status": {"$in": ["pending", "claimed"]}},
                                       {"_id": 1}):
                        skipped_already_queued += 1
                        continue
                    # Find the newest existing bar.
                    last_doc = self._data_col.find_one(
                        {"symbol": sym, "bar_size": bs},
                        {"_id": 0, "date": 1},
                        sort=[("date", -1)],
                    )
                    if last_doc and last_doc.get("date"):
                        try:
                            s = last_doc["date"].split("T")[0] if "T" in last_doc["date"] else last_doc["date"]
                            last_dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                            days_behind = (now_dt.date() - last_dt.date()).days
                        except Exception:
                            days_behind = None
                    else:
                        days_behind = None  # no data → full lookback

                    if days_behind is None:
                        # No prior data — one request at max duration.
                        to_queue.append((sym, bs, self.DURATION_STRING[bs], tier, ""))
                        continue
                    if days_behind <= freshness_days:
                        skipped_fresh += 1
                        continue
                    # Chain requests walking back in time from "now".
                    remaining = days_behind
                    max_per = self.MAX_DAYS_PER_REQUEST[bs]
                    end_anchor = now_dt
                    first_chunk = True
                    while remaining > 0:
                        take = min(remaining, max_per)
                        dur = f"{take} D"
                        # First chunk uses end_date="" (latest). Later chunks
                        # anchor to the walked-back date.
                        if first_chunk:
                            end_str = ""
                            first_chunk = False
                        else:
                            end_str = end_anchor.strftime("%Y%m%d-%H:%M:%S")
                        to_queue.append((sym, bs, dur, tier, end_str))
                        end_anchor = end_anchor - timedelta(days=take)
                        remaining -= take

        by_bar_size = Counter(t[1] for t in to_queue)

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "tier_counts": tier_counts,
                "would_queue": len(to_queue),
                "skipped_fresh": skipped_fresh,
                "skipped_already_queued": skipped_already_queued,
                "by_bar_size": dict(by_bar_size),
            }

        # 3) Queue it.
        queued = 0
        if to_queue:
            docs = []
            for sym, bs, dur, tier, end in to_queue:
                docs.append({
                    "request_id": f"hist_{uuid.uuid4().hex[:12]}",
                    "symbol": sym, "duration": dur, "bar_size": bs,
                    "end_date": end, "callback_id": None,
                    "status": "pending", "data": None, "error": None,
                    "created_at": now_iso, "claimed_at": None, "completed_at": None,
                    "tier": tier,
                })
            # Bulk insert in chunks of 2000.
            for i in range(0, len(docs), 2000):
                queue.insert_many(docs[i:i + 2000], ordered=False)
            queued = len(docs)

        return {
            "success": True,
            "dry_run": False,
            "tier_counts": tier_counts,
            "queued": queued,
            "skipped_fresh": skipped_fresh,
            "skipped_already_queued": skipped_already_queued,
            "by_bar_size": dict(by_bar_size),
            "ran_at": now_iso,
        }

    async def smart_backfill(self, dry_run: bool = False,
                             tier_filter: Optional[str] = None,
                             freshness_days: int = 2) -> Dict[str, Any]:
        """Async wrapper — heavy loops run in a thread so the event loop stays free.
        Persists non-dry-run results to `ib_smart_backfill_history` so the UI can
        show the last run's summary without re-running the whole plan."""
        import asyncio
        result = await asyncio.to_thread(
            self._smart_backfill_sync, dry_run, tier_filter, freshness_days
        )
        # Persist non-dry-run outcomes for the "Last Backfill" UI card.
        if not dry_run and result.get("success") and self._db is not None:
            try:
                hist = self._db["ib_smart_backfill_history"]
                hist.insert_one({
                    "ran_at": result.get("ran_at"),
                    "tier_filter": tier_filter,
                    "freshness_days": freshness_days,
                    "tier_counts": result.get("tier_counts"),
                    "queued": result.get("queued", 0),
                    "skipped_fresh": result.get("skipped_fresh", 0),
                    "skipped_already_queued": result.get("skipped_already_queued", 0),
                    "by_bar_size": result.get("by_bar_size", {}),
                })
                hist.create_index([("ran_at", -1)])
            except Exception as e:
                logger.warning(f"Could not persist smart_backfill history: {e}")
        return result

    def get_last_smart_backfill(self) -> Dict[str, Any]:
        """Return the most recent smart_backfill run summary (for UI card)."""
        if self._db is None:
            return {"success": False, "error": "database not initialized"}
        try:
            doc = self._db["ib_smart_backfill_history"].find_one(
                {}, {"_id": 0}, sort=[("ran_at", -1)]
            )
            return {"success": True, "last_run": doc}
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
