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
        self._historical_bars_col = None
        self._historical_stats_col = None
        self._alpaca_service = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        if db is not None:
            self._historical_bars_col = db['historical_bars']
            self._historical_stats_col = db['historical_data_stats']
            
            # Create indexes for efficient querying
            self._historical_bars_col.create_index([
                ("symbol", 1),
                ("timeframe", 1),
                ("timestamp", 1)
            ], unique=True)
            self._historical_bars_col.create_index([("symbol", 1), ("timeframe", 1)])
            
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
        """Fetch bars from Alpaca API"""
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            from alpaca.data.historical.stock import StockHistoricalDataClient
            import os
            
            # Map timeframe
            tf_map = {
                "1Min": TimeFrame.Minute,
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
                "15Min": TimeFrame(15, TimeFrameUnit.Minute),
                "1Hour": TimeFrame.Hour,
                "1Day": TimeFrame.Day,
            }
            
            tf = tf_map.get(timeframe, TimeFrame.Day)
            
            # Create client
            client = StockHistoricalDataClient(
                api_key=os.environ.get("ALPACA_API_KEY", ""),
                secret_key=os.environ.get("ALPACA_SECRET_KEY", "")
            )
            
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start_dt,
                end=end_dt,
                feed="iex"
            )
            
            bars = client.get_stock_bars(request)
            
            result = []
            bars_data = bars.data if hasattr(bars, 'data') else bars
            
            if symbol in bars_data:
                for bar in bars_data[symbol]:
                    result.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": bar.timestamp.isoformat(),
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "volume": int(bar.volume),
                        "vwap": float(bar.vwap) if bar.vwap else None,
                        "trade_count": int(bar.trade_count) if bar.trade_count else None
                    })
                    
            return result
            
        except Exception as e:
            logger.error(f"Alpaca fetch error: {e}")
            return []
            
    async def _store_bars(
        self,
        symbol: str,
        timeframe: str,
        bars: List[Dict]
    ) -> int:
        """Store bars in MongoDB with upsert"""
        if self._historical_bars_col is None or not bars:
            return 0
            
        stored = 0
        for bar in bars:
            try:
                self._historical_bars_col.update_one(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": bar["timestamp"]
                    },
                    {"$set": bar},
                    upsert=True
                )
                stored += 1
            except Exception as e:
                logger.warning(f"Error storing bar: {e}")
                
        return stored
        
    async def _update_data_stats(self, symbol: str, timeframe: str):
        """Update statistics for stored data"""
        if self._historical_bars_col is None or self._historical_stats_col is None:
            return
            
        # Get first and last bars
        first_bar = self._historical_bars_col.find_one(
            {"symbol": symbol, "timeframe": timeframe},
            sort=[("timestamp", 1)]
        )
        last_bar = self._historical_bars_col.find_one(
            {"symbol": symbol, "timeframe": timeframe},
            sort=[("timestamp", -1)]
        )
        
        bar_count = self._historical_bars_col.count_documents({
            "symbol": symbol,
            "timeframe": timeframe
        })
        
        # Detect gaps (simplified)
        gaps = await self._detect_gaps(symbol, timeframe)
        
        stats = HistoricalDataStats(
            symbol=symbol,
            timeframe=timeframe,
            bar_count=bar_count,
            first_bar=first_bar["timestamp"] if first_bar else "",
            last_bar=last_bar["timestamp"] if last_bar else "",
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
        """Simple gap detection for daily bars"""
        if self._historical_bars_col is None or timeframe != "1Day":
            return 0
            
        # Get all timestamps
        bars = list(self._historical_bars_col.find(
            {"symbol": symbol, "timeframe": timeframe},
            {"timestamp": 1}
        ).sort("timestamp", 1))
        
        if len(bars) < 2:
            return 0
            
        gaps = 0
        for i in range(1, len(bars)):
            prev_ts = datetime.fromisoformat(bars[i-1]["timestamp"].replace("Z", "+00:00"))
            curr_ts = datetime.fromisoformat(bars[i]["timestamp"].replace("Z", "+00:00"))
            
            # Check if gap is more than 4 days (accounting for weekends)
            day_diff = (curr_ts - prev_ts).days
            if day_diff > 4:
                gaps += 1
                
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
        Get historical bars from stored data.
        
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
            
        query = {"symbol": symbol.upper(), "timeframe": timeframe}
        
        if start_date:
            query["timestamp"] = {"$gte": start_date}
        if end_date:
            if "timestamp" in query:
                query["timestamp"]["$lte"] = end_date
            else:
                query["timestamp"] = {"$lte": end_date}
                
        cursor = self._historical_bars_col.find(
            query,
            {"_id": 0}
        ).sort("timestamp", 1)
        
        if limit:
            cursor = cursor.limit(limit)
            
        return list(cursor)
        
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
        """Delete stored historical data"""
        if self._historical_bars_col is None:
            return {"success": False, "error": "Database not connected"}
            
        query = {"symbol": symbol.upper()}
        if timeframe:
            query["timeframe"] = timeframe
            
        result = self._historical_bars_col.delete_many(query)
        
        # Also delete stats
        if self._historical_stats_col is not None:
            self._historical_stats_col.delete_many(query)
            
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
