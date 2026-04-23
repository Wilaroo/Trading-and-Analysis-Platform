"""
Historical Data Service - Phase 6 Slow Learning

Downloads and caches historical market data from Alpaca for backtesting.
Stores data in MongoDB for offline analysis.

Features:
- Bulk historical data download
- Data caching and management
- Multiple timeframe support
- Data quality validation
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class HistoricalDataRequest:
    """Request for historical data download"""
    symbol: str = ""
    timeframe: str = "1Day"  # 1Min, 5Min, 15Min, 1Hour, 1Day
    start_date: str = ""
    end_date: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class HistoricalDataStats:
    """Statistics about stored historical data"""
    symbol: str = ""
    timeframe: str = ""
    bar_count: int = 0
    first_bar: str = ""
    last_bar: str = ""
    data_quality: str = "good"  # good, gaps, incomplete
    gaps_detected: int = 0
    last_updated: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class HistoricalDataService:
    """
    Manages historical market data for backtesting.
    
    Uses Alpaca for data source, stores in MongoDB for persistence.
    Supports multiple timeframes and handles data gaps.
    """
    
    SUPPORTED_TIMEFRAMES = ["1Min", "5Min", "15Min", "1Hour", "1Day"]
    
    def __init__(self):
        self._db = None
        self._historical_bars_col = None  # Now points to ib_historical_data
        self._historical_stats_col = None
        self._alpaca_service = None
        
    def set_db(self, db):
        """Set database connection - now uses unified ib_historical_data collection"""
        self._db = db
        if db is not None:
            # Use unified ib_historical_data collection
            self._historical_bars_col = db['ib_historical_data']
            self._historical_stats_col = db['historical_data_stats']
            
            # Indexes already exist on ib_historical_data (created by optimize-indexes endpoint)
            
    def set_alpaca_service(self, alpaca_service):
        """Set Alpaca service for data fetching"""
        self._alpaca_service = alpaca_service
        
    async def download_historical_data(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start_date: str = None,
        end_date: str = None,
        days_back: int = 365
    ) -> Dict[str, Any]:
        """
        Download and store historical data for a symbol.
        
        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            days_back: Days to look back if dates not specified
            
        Returns:
            Download result with bar count and status
        """
        if self._alpaca_service is None:
            return {"success": False, "error": "Alpaca service not configured"}
            
        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            return {"success": False, "error": f"Unsupported timeframe: {timeframe}"}
            
        # Calculate date range
        if end_date:
            end_dt = datetime.fromisoformat(end_date)
        else:
            end_dt = datetime.now(timezone.utc)
            
        if start_date:
            start_dt = datetime.fromisoformat(start_date)
        else:
            start_dt = end_dt - timedelta(days=days_back)
            
        symbol = symbol.upper()
        
        try:
            # Fetch data in chunks to handle large date ranges
            all_bars = []
            chunk_days = 30 if timeframe in ["1Min", "5Min"] else 365
            
            current_start = start_dt
            while current_start < end_dt:
                chunk_end = min(current_start + timedelta(days=chunk_days), end_dt)
                
                # Use Alpaca to fetch bars
                bars = await self._fetch_bars_from_alpaca(
                    symbol, timeframe, current_start, chunk_end
                )
                all_bars.extend(bars)
                
                current_start = chunk_end
                
            # Store in MongoDB
            stored_count = await self._store_bars(symbol, timeframe, all_bars)
            
            # Update stats
            await self._update_data_stats(symbol, timeframe)
            
            return {
                "success": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "bars_fetched": len(all_bars),
                "bars_stored": stored_count,
                "date_range": {
                    "start": start_dt.strftime("%Y-%m-%d"),
                    "end": end_dt.strftime("%Y-%m-%d")
                }
            }
            
        except Exception as e:
            logger.error(f"Error downloading historical data for {symbol}: {e}")
            return {"success": False, "error": str(e)}
            
    async def _fetch_bars_from_alpaca(
        self,
        symbol: str,
        timeframe: str,
        start_dt: datetime,
        end_dt: datetime
    ) -> List[Dict]:
        """Fetch bars from the IB-backed data provider.

        DEPRECATED NAME kept for BC. Alpaca has been fully removed from the
        live-data path — this now reads `ib_historical_data` via
        IBDataProvider. The upstream collector populates that collection.
        """
        try:
            from services.ib_data_provider import get_live_data_service
            live = get_live_data_service()
            # IBDataProvider.get_bars returns newest-first slice bounded by limit.
            # Derive a reasonable limit from the requested date range.
            span_days = max(1, int((end_dt - start_dt).total_seconds() / 86400))
            limit_map = {"1Min": span_days * 390, "5Min": span_days * 78,
                         "15Min": span_days * 26, "30Min": span_days * 13,
                         "1Hour": span_days * 7, "1Day": span_days + 5}
            limit = min(limit_map.get(timeframe, 1000), 10000)
            bars = await live.get_bars(symbol=symbol, timeframe=timeframe, limit=limit)
            # Filter to requested window (IBDataProvider returns oldest→newest).
            filtered = []
            for b in bars:
                try:
                    ts = datetime.fromisoformat(str(b["timestamp"]).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=start_dt.tzinfo)
                    if start_dt <= ts <= end_dt:
                        filtered.append({**b, "symbol": symbol, "timeframe": timeframe})
                except Exception:
                    continue
            return filtered
        except Exception as e:
            logger.error(f"IB historical fetch error: {e}")
            return []
            
    async def _store_bars(
        self,
        symbol: str,
        timeframe: str,
        bars: List[Dict]
    ) -> int:
        """Store bars in unified ib_historical_data collection with upsert"""
        if self._historical_bars_col is None or not bars:
            return 0
        
        # Map timeframe to bar_size
        bar_size_map = {"1Day": "1 day", "1day": "1 day", "5Min": "5 mins", "5min": "5 mins", 
                        "15Min": "15 mins", "1Hour": "1 hour"}
        bar_size = bar_size_map.get(timeframe, "1 day")
        is_daily = "day" in bar_size.lower()
            
        stored = 0
        for bar in bars:
            try:
                timestamp = bar.get("timestamp", "")
                date_str = timestamp[:10] if is_daily and isinstance(timestamp, str) else timestamp
                
                self._historical_bars_col.update_one(
                    {
                        "symbol": symbol,
                        "bar_size": bar_size,
                        "date": date_str
                    },
                    {"$set": {
                        "symbol": symbol,
                        "bar_size": bar_size,
                        "date": date_str,
                        "open": bar.get("open"),
                        "high": bar.get("high"),
                        "low": bar.get("low"),
                        "close": bar.get("close"),
                        "volume": bar.get("volume"),
                        "source": "alpaca",
                        "collected_at": datetime.now(timezone.utc).isoformat()
                    }},
                    upsert=True
                )
                stored += 1
            except Exception as e:
                logger.warning(f"Error storing bar: {e}")
                
        return stored
        
    async def _update_data_stats(self, symbol: str, timeframe: str):
        """Update statistics for stored data using unified ib_historical_data schema"""
        if self._historical_bars_col is None or self._historical_stats_col is None:
            return
        
        # Map timeframe to bar_size
        bar_size_map = {"1Day": "1 day", "1day": "1 day", "5Min": "5 mins", "5min": "5 mins", 
                        "15Min": "15 mins", "1Hour": "1 hour"}
        bar_size = bar_size_map.get(timeframe, "1 day")
            
        # Get first and last bars using new schema
        first_bar = self._historical_bars_col.find_one(
            {"symbol": symbol, "bar_size": bar_size},
            sort=[("date", 1)]
        )
        last_bar = self._historical_bars_col.find_one(
            {"symbol": symbol, "bar_size": bar_size},
            sort=[("date", -1)]
        )
        
        bar_count = self._historical_bars_col.count_documents({
            "symbol": symbol,
            "bar_size": bar_size
        })
        
        # Detect gaps (simplified)
        gaps = await self._detect_gaps(symbol, timeframe)
        
        stats = HistoricalDataStats(
            symbol=symbol,
            timeframe=timeframe,
            bar_count=bar_count,
            first_bar=first_bar.get("date", "") if first_bar else "",
            last_bar=last_bar.get("date", "") if last_bar else "",
            data_quality="good" if gaps == 0 else "gaps",
            gaps_detected=gaps,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        self._historical_stats_col.update_one(
            {"symbol": symbol, "timeframe": timeframe},
            {"$set": stats.to_dict()},
            upsert=True
        )
        
    async def _detect_gaps(self, symbol: str, timeframe: str) -> int:
        """Simple gap detection for daily bars using unified schema"""
        if self._historical_bars_col is None or timeframe != "1Day":
            return 0
            
        # Get all dates using new schema
        bars = list(self._historical_bars_col.find(
            {"symbol": symbol, "bar_size": "1 day"},
            {"date": 1}
        ).sort("date", 1))
        
        if len(bars) < 2:
            return 0
            
        gaps = 0
        for i in range(1, len(bars)):
            # Use date field from new schema
            prev_date = bars[i-1].get("date", "")
            curr_date = bars[i].get("date", "")
            
            try:
                prev_dt = datetime.fromisoformat(prev_date[:10] if len(prev_date) > 10 else prev_date)
                curr_dt = datetime.fromisoformat(curr_date[:10] if len(curr_date) > 10 else curr_date)
                
                # Check if gap is more than 4 days (accounting for weekends)
                day_diff = (curr_dt - prev_dt).days
                if day_diff > 4:
                    gaps += 1
            except Exception:
                continue
                
        return gaps
        
    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start_date: str = None,
        end_date: str = None,
        limit: int = None
    ) -> List[Dict]:
        """
        Get historical bars from unified ib_historical_data collection.
        
        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe
            start_date: Filter start date
            end_date: Filter end date
            limit: Max bars to return
            
        Returns:
            List of bar dictionaries
        """
        if self._historical_bars_col is None:
            return []
        
        # Map timeframe to bar_size
        bar_size_map = {"1Day": "1 day", "1day": "1 day", "5Min": "5 mins", "5min": "5 mins", 
                        "15Min": "15 mins", "1Hour": "1 hour"}
        bar_size = bar_size_map.get(timeframe, "1 day")
            
        query = {"symbol": symbol.upper(), "bar_size": bar_size}
        
        if start_date:
            query["date"] = {"$gte": start_date}
        if end_date:
            if "date" in query:
                query["date"]["$lte"] = end_date
            else:
                query["date"] = {"$lte": end_date}
                
        cursor = self._historical_bars_col.find(
            query,
            {"_id": 0}
        ).sort("date", 1)
        
        if limit:
            cursor = cursor.limit(limit)
        
        # Convert to old format for compatibility
        bars = []
        for bar in cursor:
            bars.append({
                "symbol": bar.get("symbol"),
                "timestamp": bar.get("date"),
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": bar.get("volume"),
                "timeframe": timeframe
            })
            
        return bars
        
    async def get_data_stats(self, symbol: str = None) -> List[HistoricalDataStats]:
        """Get statistics about stored historical data"""
        if self._historical_stats_col is None:
            return []
            
        query = {}
        if symbol:
            query["symbol"] = symbol.upper()
            
        docs = list(self._historical_stats_col.find(query, {"_id": 0}))
        return [HistoricalDataStats(**d) for d in docs]
        
    async def get_available_symbols(self) -> List[str]:
        """Get list of symbols with stored historical data"""
        if self._historical_bars_col is None:
            return []
            
        return self._historical_bars_col.distinct("symbol")
        
    async def delete_data(
        self,
        symbol: str,
        timeframe: str = None
    ) -> Dict[str, Any]:
        """Delete stored historical data from unified ib_historical_data"""
        if self._historical_bars_col is None:
            return {"success": False, "error": "Database not connected"}
        
        # Map timeframe to bar_size for unified schema
        query = {"symbol": symbol.upper()}
        if timeframe:
            bar_size_map = {"1Day": "1 day", "1day": "1 day", "5Min": "5 mins", "5min": "5 mins", 
                            "15Min": "15 mins", "1Hour": "1 hour"}
            bar_size = bar_size_map.get(timeframe, "1 day")
            query["bar_size"] = bar_size
            
        result = self._historical_bars_col.delete_many(query)
        
        # Also delete stats
        if self._historical_stats_col is not None:
            stats_query = {"symbol": symbol.upper()}
            if timeframe:
                stats_query["timeframe"] = timeframe
            self._historical_stats_col.delete_many(stats_query)
            
        return {
            "success": True,
            "deleted_count": result.deleted_count
        }
        
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        symbols = 0
        total_bars = 0
        
        if self._historical_bars_col is not None:
            symbols = len(self._historical_bars_col.distinct("symbol"))
            total_bars = self._historical_bars_col.count_documents({})
            
        return {
            "db_connected": self._db is not None,
            "alpaca_connected": self._alpaca_service is not None,
            "symbols_stored": symbols,
            "total_bars": total_bars
        }


# Singleton
_historical_data_service: Optional[HistoricalDataService] = None


def get_historical_data_service() -> HistoricalDataService:
    global _historical_data_service
    if _historical_data_service is None:
        _historical_data_service = HistoricalDataService()
    return _historical_data_service


def init_historical_data_service(db=None, alpaca_service=None) -> HistoricalDataService:
    service = get_historical_data_service()
    if db is not None:
        service.set_db(db)
    if alpaca_service is not None:
        service.set_alpaca_service(alpaca_service)
    return service
