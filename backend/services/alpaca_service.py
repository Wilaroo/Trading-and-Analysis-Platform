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
            paper=True
        )
        
        # Use IEX feed for free tier (SIP requires paid subscription)
        _data_client = StockHistoricalDataClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY
        )
        
        logger.info("Alpaca clients initialized successfully (using IEX feed for free tier)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Alpaca clients: {e}")
        return False


class AlpacaService:
    """Service for fetching market data from Alpaca"""
    
    def __init__(self):
        self._initialized = False
        self._quote_cache: Dict[str, Dict] = {}
        self._bars_cache: Dict[str, Dict] = {}
        self._cache_ttl = 15  # seconds for quotes
        self._bars_cache_ttl = 120  # seconds for bars
        
    def _ensure_initialized(self) -> bool:
        """Ensure clients are initialized"""
        if not self._initialized:
            self._initialized = _init_clients()
        return self._initialized
    
    async def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote for a symbol.
        Returns latest quote data including bid, ask, and last price.
        Note: Alpaca only supports stocks, not indices like VIX.
        """
        if not self._ensure_initialized():
            return None
        
        # Alpaca doesn't support indices - skip them
        symbol_upper = symbol.upper()
        if symbol_upper in ["VIX", "^VIX", "$VIX"]:
            return None  # Let fallback handle VIX
            
        # Check cache first
        cache_key = symbol_upper
        if cache_key in self._quote_cache:
            cached = self._quote_cache[cache_key]
            cache_age = (datetime.now(timezone.utc) - cached.get('_cached_at', datetime.min.replace(tzinfo=timezone.utc))).total_seconds()
            if cache_age < self._cache_ttl:
                return cached
        
        try:
            from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
            
            # Get latest quote (bid/ask)
            quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol.upper())
            quotes = _data_client.get_stock_latest_quote(quote_request)
            
            # Get latest trade (last price)
            trade_request = StockLatestTradeRequest(symbol_or_symbols=symbol.upper())
            trades = _data_client.get_stock_latest_trade(trade_request)
            
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
                    "_cached_at": datetime.now(timezone.utc)
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
        if not self._ensure_initialized():
            return {}
            
        if not symbols:
            return {}
            
        try:
            from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest
            
            symbols_upper = [s.upper() for s in symbols]
            
            # Batch request for quotes
            quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbols_upper)
            quotes = _data_client.get_stock_latest_quote(quote_request)
            
            # Batch request for trades
            trade_request = StockLatestTradeRequest(symbol_or_symbols=symbols_upper)
            trades = _data_client.get_stock_latest_trade(trade_request)
            
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
                        "_cached_at": now
                    }
                    
                    # Cache each result
                    self._quote_cache[symbol] = results[symbol]
            
            return results
            
        except Exception as e:
            logger.error(f"Alpaca batch quote error: {e}")
            return {}
    
    async def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get historical bars/candles for a symbol.
        
        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe - "1Min", "5Min", "15Min", "1Hour", "1Day"
            limit: Number of bars to return
        """
        if not self._ensure_initialized():
            return []
            
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
            
            # Use IEX feed for free tier
            request = StockBarsRequest(
                symbol_or_symbols=symbol.upper(),
                timeframe=tf,
                start=start,
                end=end,
                limit=limit,
                feed="iex"  # Use IEX for free tier
            )
            
            bars = _data_client.get_stock_bars(request)
            
            result = []
            # Access bars through .data attribute for BarSet
            bars_data = bars.data if hasattr(bars, 'data') else bars
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
            
            return result
            
        except Exception as e:
            logger.error(f"Alpaca bars error for {symbol}: {e}")
            return []
    
    async def get_account(self) -> Optional[Dict[str, Any]]:
        """Get Alpaca account information"""
        if not self._ensure_initialized():
            return None
            
        try:
            account = _trading_client.get_account()
            
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
        if not self._ensure_initialized():
            return self._get_default_watchlist()
        
        try:
            from alpaca.data.requests import MostActivesRequest
            from alpaca.data.enums import MostActivesBy
            
            # Get most active by volume
            request = MostActivesRequest(
                top=limit,
                by=MostActivesBy.VOLUME
            )
            
            most_actives = _data_client.get_stock_most_actives(request)
            
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
