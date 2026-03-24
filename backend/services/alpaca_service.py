"""
Alpaca Market Data Service
Provides real-time market data using Alpaca's free API.
Falls back gracefully when IB Gateway market data subscriptions are unavailable.
"""
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import asyncio

logger = logging.getLogger(__name__)

# Alpaca configuration from environment
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# Data feed - use "iex" for free tier, "sip" for paid
ALPACA_DATA_FEED = os.environ.get("ALPACA_DATA_FEED", "iex")

# Global clients
_trading_client = None
_data_client = None
_stream_client = None


def _init_clients():
    """Initialize Alpaca clients lazily"""
    global _trading_client, _data_client
    
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        logger.warning("Alpaca API keys not configured")
        return False
    
    try:
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.enums import DataFeed
        
        _trading_client = TradingClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            paper=True,
            raw_data=False
        )
        
        _data_client = StockHistoricalDataClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            raw_data=False
        )
        
        logger.info("Alpaca clients initialized successfully (using IEX feed for free tier)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Alpaca clients: {e}")
        return False


# Default timeout for Alpaca SDK calls (seconds)
ALPACA_CALL_TIMEOUT = 10


class AlpacaService:
    """Service for fetching market data from Alpaca"""
    
    def __init__(self):
        self._initialized = False
        self._quote_cache: Dict[str, Dict] = {}
        self._bars_cache: Dict[str, Dict] = {}
        self._cache_ttl = 10  # seconds for quotes (reduced from 15)
        self._bars_cache_ttl = 60  # seconds for bars (reduced from 120)
        
    async def _ensure_initialized_async(self) -> bool:
        """Ensure clients are initialized (non-blocking)"""
        if not self._initialized:
            try:
                self._initialized = await asyncio.wait_for(
                    asyncio.to_thread(_init_clients),
                    timeout=ALPACA_CALL_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("Alpaca client initialization timed out")
                return False
        return self._initialized
    
    def _ensure_initialized(self) -> bool:
        """Sync fallback for non-async contexts"""
        if not self._initialized:
            self._initialized = _init_clients()
        return self._initialized
    
    async def get_quote(self, symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote for a symbol.
        Returns latest quote data including bid, ask, and last price.
        
        Args:
            symbol: Stock symbol
            force_refresh: If True, bypass cache and fetch fresh data
        
        Note: Alpaca only supports stocks, not indices like VIX.
        """
        if not await self._ensure_initialized_async():
            return None
        
        # Alpaca doesn't support indices - skip them
        symbol_upper = symbol.upper()
        if symbol_upper in ["VIX", "^VIX", "$VIX"]:
            return None  # Let fallback handle VIX
            
        # Check cache first (unless force_refresh)
        cache_key = symbol_upper
        if not force_refresh and cache_key in self._quote_cache:
            cached = self._quote_cache[cache_key]
            cached_at_str = cached.get('_cached_at', '')
            try:
                cached_at = datetime.fromisoformat(cached_at_str) if cached_at_str else datetime.min.replace(tzinfo=timezone.utc)
                cache_age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                if cache_age < self._cache_ttl:
                    return cached
            except (ValueError, TypeError):
                pass  # Invalid cache, will fetch fresh data
        
        try:
            from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
            
            # Get latest quote (bid/ask) — run sync SDK call in thread with timeout
            quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol.upper())
            quotes = await asyncio.wait_for(
                asyncio.to_thread(_data_client.get_stock_latest_quote, quote_request),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            # Get latest trade (last price) — run sync SDK call in thread with timeout
            trade_request = StockLatestTradeRequest(symbol_or_symbols=symbol.upper())
            trades = await asyncio.wait_for(
                asyncio.to_thread(_data_client.get_stock_latest_trade, trade_request),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            if symbol.upper() in quotes:
                quote = quotes[symbol.upper()]
                trade = trades.get(symbol.upper())
                
                # Calculate mid price and spread
                bid = float(quote.bid_price) if quote.bid_price else 0
                ask = float(quote.ask_price) if quote.ask_price else 0
                last = float(trade.price) if trade else (bid + ask) / 2 if bid and ask else 0
                
                result = {
                    "symbol": symbol.upper(),
                    "price": last,
                    "bid": bid,
                    "ask": ask,
                    "bid_size": int(quote.bid_size) if quote.bid_size else 0,
                    "ask_size": int(quote.ask_size) if quote.ask_size else 0,
                    "volume": int(trade.size) if trade else 0,
                    "timestamp": quote.timestamp.isoformat() if quote.timestamp else datetime.now(timezone.utc).isoformat(),
                    "source": "alpaca",
                    "_cached_at": datetime.now(timezone.utc).isoformat()
                }
                
                # Cache the result
                self._quote_cache[cache_key] = result
                return result
                
        except Exception as e:
            logger.error(f"Alpaca quote error for {symbol}: {e}")
            
        return None
    
    async def get_quotes_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get quotes for multiple symbols in a single request.
        More efficient than calling get_quote() multiple times.
        """
        if not await self._ensure_initialized_async():
            return {}
            
        if not symbols:
            return {}
            
        try:
            from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
            
            symbols_upper = [s.upper() for s in symbols]
            
            # Batch request for quotes — run sync SDK call in thread with timeout
            quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbols_upper)
            quotes = await asyncio.wait_for(
                asyncio.to_thread(_data_client.get_stock_latest_quote, quote_request),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            # Batch request for trades — run sync SDK call in thread with timeout
            trade_request = StockLatestTradeRequest(symbol_or_symbols=symbols_upper)
            trades = await asyncio.wait_for(
                asyncio.to_thread(_data_client.get_stock_latest_trade, trade_request),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            results = {}
            now = datetime.now(timezone.utc)
            
            for symbol in symbols_upper:
                if symbol in quotes:
                    quote = quotes[symbol]
                    trade = trades.get(symbol)
                    
                    bid = float(quote.bid_price) if quote.bid_price else 0
                    ask = float(quote.ask_price) if quote.ask_price else 0
                    last = float(trade.price) if trade else (bid + ask) / 2 if bid and ask else 0
                    
                    results[symbol] = {
                        "symbol": symbol,
                        "price": last,
                        "bid": bid,
                        "ask": ask,
                        "bid_size": int(quote.bid_size) if quote.bid_size else 0,
                        "ask_size": int(quote.ask_size) if quote.ask_size else 0,
                        "volume": int(trade.size) if trade else 0,
                        "timestamp": quote.timestamp.isoformat() if quote.timestamp else now.isoformat(),
                        "source": "alpaca",
                        "_cached_at": now.isoformat()
                    }
                    
                    # Cache each result
                    self._quote_cache[symbol] = results[symbol]
            
            return results
            
        except Exception as e:
            logger.error(f"Alpaca batch quote error: {e}")
            return {}
    
    async def calculate_rvol(self, symbol: str) -> Optional[float]:
        """
        Calculate Relative Volume (RVOL) for a symbol.
        RVOL = Current Volume / 20-day Average Volume at this time of day
        
        Returns:
            Float representing RVOL (e.g., 2.5 means 2.5x normal volume)
            None if calculation fails
        """
        try:
            # Get current day's volume from snapshot
            quote = await self.get_quote(symbol, force_refresh=True)
            if not quote:
                return None
            
            current_volume = quote.get('volume', 0)
            if not current_volume:
                return None
            
            # Get 20-day historical bars to calculate average volume
            bars = await self.get_bars(symbol, timeframe="1Day", limit=20)
            if not bars or len(bars) < 5:
                return None
            
            # Calculate average daily volume
            volumes = [bar.get('volume', 0) for bar in bars if bar.get('volume', 0) > 0]
            if not volumes:
                return None
            
            avg_volume = sum(volumes) / len(volumes)
            if avg_volume == 0:
                return None
            
            # Calculate time-of-day adjustment
            # Market is open 9:30 AM - 4:00 PM ET (6.5 hours = 390 minutes)
            from datetime import datetime
            import pytz
            
            et = pytz.timezone('US/Eastern')
            now_et = datetime.now(et)
            market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            
            if now_et < market_open:
                # Pre-market - use full day comparison
                time_fraction = 1.0
            else:
                minutes_since_open = (now_et - market_open).total_seconds() / 60
                time_fraction = min(minutes_since_open / 390, 1.0)  # Cap at 1.0
            
            # Adjusted average volume for time of day
            expected_volume = avg_volume * time_fraction if time_fraction > 0 else avg_volume
            
            # Calculate RVOL
            rvol = current_volume / expected_volume if expected_volume > 0 else 0
            
            return round(rvol, 2)
            
        except Exception as e:
            logger.warning(f"RVOL calculation error for {symbol}: {e}")
            return None
    
    async def get_quotes_with_rvol(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get quotes for multiple symbols with RVOL calculated.
        More expensive than get_quotes_batch but includes relative volume.
        """
        # First get basic quotes
        quotes = await self.get_quotes_batch(symbols)
        
        # Then calculate RVOL for each (in parallel)
        async def add_rvol(symbol: str):
            rvol = await self.calculate_rvol(symbol)
            if symbol in quotes and rvol is not None:
                quotes[symbol]['rvol'] = rvol
                quotes[symbol]['rvol_status'] = (
                    'exceptional' if rvol >= 5 else
                    'high' if rvol >= 3 else
                    'strong' if rvol >= 2 else
                    'in_play' if rvol >= 1.5 else
                    'normal'
                )
        
        # Calculate RVOL in parallel for efficiency
        await asyncio.gather(*[add_rvol(s) for s in symbols[:10]])  # Limit to 10 to avoid rate limits
        
        return quotes
    
    async def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get historical bars with caching.
        
        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe (1Min, 5Min, 1Hour, 1Day)
            limit: Number of bars to fetch
            force_refresh: If True, bypass cache and fetch fresh data
        """
        if not await self._ensure_initialized_async():
            return []
        
        # Check bars cache (unless force_refresh)
        cache_key = f"{symbol.upper()}_{timeframe}_{limit}"
        if not force_refresh and cache_key in self._bars_cache:
            cached = self._bars_cache[cache_key]
            cached_at_str = cached.get('_cached_at', '')
            try:
                cached_at = datetime.fromisoformat(cached_at_str) if cached_at_str else datetime.min.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                if age < self._bars_cache_ttl:
                    return cached.get('bars', [])
            except (ValueError, TypeError):
                pass  # Invalid cache, will fetch fresh data
            
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            
            # Map timeframe string to Alpaca TimeFrame
            tf_map = {
                "1Min": TimeFrame.Minute,
                "5Min": TimeFrame(5, TimeFrameUnit.Minute),
                "15Min": TimeFrame(15, TimeFrameUnit.Minute),
                "1Hour": TimeFrame.Hour,
                "1Day": TimeFrame.Day,
            }
            
            tf = tf_map.get(timeframe, TimeFrame.Day)
            
            # Calculate start date based on limit and timeframe
            end = datetime.now(timezone.utc)
            if timeframe == "1Day":
                start = end - timedelta(days=limit + 10)  # Extra buffer for weekends
            elif timeframe == "1Hour":
                start = end - timedelta(hours=limit + 24)
            else:
                start = end - timedelta(minutes=limit * 5 + 60)
            
            # Use IEX feed for free tier — run sync SDK call in thread with timeout
            request = StockBarsRequest(
                symbol_or_symbols=symbol.upper(),
                timeframe=tf,
                start=start,
                end=end,
                limit=limit,
                feed="iex"  # Use IEX for free tier
            )
            
            bars = await asyncio.wait_for(
                asyncio.to_thread(_data_client.get_stock_bars, request),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            result = []
            # Access bars through .data attribute for BarSet
            bars_data = bars.data if hasattr(bars, 'data') else bars
            logger.info(f"Got bars for {symbol}: {len(bars_data.get(symbol.upper(), []))} bars")
            if symbol.upper() in bars_data:
                for bar in bars_data[symbol.upper()]:
                    result.append({
                        "timestamp": bar.timestamp.isoformat(),
                        "open": float(bar.open),
                        "high": float(bar.high),
                        "low": float(bar.low),
                        "close": float(bar.close),
                        "volume": int(bar.volume),
                        "vwap": float(bar.vwap) if bar.vwap else None,
                        "trade_count": int(bar.trade_count) if bar.trade_count else None
                    })
            
            # Cache bars
            self._bars_cache[cache_key] = {'bars': result, '_cached_at': datetime.now(timezone.utc).isoformat()}
            
            return result
            
        except Exception as e:
            logger.error(f"Alpaca bars error for {symbol}: {e}")
            return []
    
    async def get_account(self) -> Optional[Dict[str, Any]]:
        """Get Alpaca account information"""
        if not await self._ensure_initialized_async():
            return None
            
        try:
            account = await asyncio.wait_for(
                asyncio.to_thread(_trading_client.get_account),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            return {
                "account_id": account.id,
                "status": account.status.value if hasattr(account.status, 'value') else str(account.status),
                "currency": account.currency,
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
                "buying_power": float(account.buying_power),
                "equity": float(account.equity),
                "last_equity": float(account.last_equity),
                "pattern_day_trader": account.pattern_day_trader,
                "trading_blocked": account.trading_blocked,
                "transfers_blocked": account.transfers_blocked,
                "account_blocked": account.account_blocked,
                "daytrade_count": account.daytrade_count,
                "daytrading_buying_power": float(account.daytrading_buying_power) if account.daytrading_buying_power else 0,
            }
            
        except Exception as e:
            logger.error(f"Alpaca account error: {e}")
            return None
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions from Alpaca paper trading account"""
        if not await self._ensure_initialized_async():
            return []
        
        try:
            positions = await asyncio.wait_for(
                asyncio.to_thread(_trading_client.get_all_positions),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            result = []
            for pos in positions:
                result.append({
                    "symbol": pos.symbol,
                    "qty": float(pos.qty),
                    "avg_entry_price": float(pos.avg_entry_price),
                    "market_value": float(pos.market_value),
                    "cost_basis": float(pos.cost_basis),
                    "unrealized_pl": float(pos.unrealized_pl),
                    "unrealized_plpc": float(pos.unrealized_plpc),
                    "current_price": float(pos.current_price),
                    "side": pos.side.value if hasattr(pos.side, 'value') else str(pos.side),
                    "change_today": float(pos.change_today) if pos.change_today else 0.0
                })
            
            logger.debug(f"Retrieved {len(result)} positions from Alpaca")
            return result
            
        except Exception as e:
            logger.warning(f"Error fetching positions from Alpaca: {e}")
            return []
    
    def get_status(self) -> Dict[str, Any]:
        """Get service status"""
        initialized = self._ensure_initialized()
        
        return {
            "service": "alpaca",
            "initialized": initialized,
            "api_key_configured": bool(ALPACA_API_KEY),
            "base_url": ALPACA_BASE_URL,
            "data_feed": ALPACA_DATA_FEED,
            "cache_size": len(self._quote_cache)
        }
    
    def clear_cache(self):
        """Clear the quote cache"""
        self._quote_cache.clear()
    
    async def get_most_active_stocks(self, limit: int = 30) -> List[Dict[str, Any]]:
        """
        Get most active stocks by volume from Alpaca.
        Uses Alpaca's most active screener endpoint.
        Falls back to a default watchlist of popular stocks if screener unavailable.
        """
        if not await self._ensure_initialized_async():
            return self._get_default_watchlist()
        
        try:
            from alpaca.data.requests import MostActivesRequest
            from alpaca.data.enums import MostActivesBy
            
            # Get most active by volume
            request = MostActivesRequest(
                top=limit,
                by=MostActivesBy.VOLUME
            )
            
            most_actives = await asyncio.wait_for(
                asyncio.to_thread(_data_client.get_stock_most_actives, request),
                timeout=ALPACA_CALL_TIMEOUT
            )
            
            result = []
            for stock in most_actives.most_actives:
                result.append({
                    "symbol": stock.symbol,
                    "name": stock.symbol,  # Alpaca doesn't return company name
                    "volume": int(stock.volume) if stock.volume else 0,
                    "trade_count": int(stock.trade_count) if stock.trade_count else 0,
                    "scan_type": "MOST_ACTIVE"
                })
            
            logger.info(f"Alpaca most actives returned {len(result)} stocks")
            return result if result else self._get_default_watchlist()
            
        except Exception as e:
            logger.warning(f"Alpaca most actives error: {e}, using default watchlist")
            return self._get_default_watchlist()
    
    def _get_default_watchlist(self) -> List[Dict[str, Any]]:
        """Return a default watchlist of popular, highly-traded stocks"""
        default_symbols = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
            "SPY", "QQQ", "NFLX", "DIS", "BA", "JPM", "V", "MA", "UNH",
            "PFE", "MRNA", "XOM", "CVX", "COST", "WMT", "HD", "LOW",
            "CRM", "ORCL", "INTC", "MU", "QCOM"
        ]
        return [
            {"symbol": s, "name": s, "volume": 0, "scan_type": "DEFAULT_WATCHLIST"}
            for s in default_symbols
        ]


# Singleton instance
_alpaca_service: Optional[AlpacaService] = None


def get_alpaca_service() -> AlpacaService:
    """Get the singleton Alpaca service"""
    global _alpaca_service
    if _alpaca_service is None:
        _alpaca_service = AlpacaService()
    return _alpaca_service


def init_alpaca_service() -> AlpacaService:
    """Initialize and return the Alpaca service"""
    global _alpaca_service
    _alpaca_service = AlpacaService()
    return _alpaca_service
