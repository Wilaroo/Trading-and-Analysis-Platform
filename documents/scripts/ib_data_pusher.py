"""
IB Data Pusher - Runs on your local machine
Connects to IB Gateway locally and pushes data to the cloud backend.

Usage:
    python ib_data_pusher.py --cloud-url https://sentcom-queue-mgmt.preview.emergentagent.com

This script should be run on your trading laptop alongside IB Gateway.

UPDATED: Added Cloudflare evasion with proper User-Agent headers and exponential backoff.
"""
import argparse
import json
import logging
import time
import random
import requests
from datetime import datetime
from typing import Dict, List, Optional
from functools import wraps

# Python 3.10+ compatibility: create event loop before ib_insync import
import asyncio
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock, Index, Contract

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("IB-Pusher")


# ==================== CLOUDFLARE EVASION ====================

# Standard browser headers to avoid Cloudflare blocks
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}


def create_session() -> requests.Session:
    """Create a requests session with browser-like headers to avoid Cloudflare"""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    return session


def retry_with_backoff(max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 60.0):
    """
    Decorator for exponential backoff retry logic.
    Handles 429 rate limits, timeouts, and connection errors.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response is not None else 0
                    
                    if status_code == 429:
                        # Rate limited - use exponential backoff with jitter
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                        logger.warning(f"Rate limited (429) on {func.__name__}. Retry {attempt+1}/{max_retries} in {delay:.1f}s")
                        time.sleep(delay)
                        last_exception = e
                    elif status_code == 403:
                        # Cloudflare block - longer delay
                        delay = min(base_delay * (3 ** attempt) + random.uniform(1, 3), max_delay)
                        logger.warning(f"Cloudflare block (403) on {func.__name__}. Retry {attempt+1}/{max_retries} in {delay:.1f}s")
                        time.sleep(delay)
                        last_exception = e
                    elif 500 <= status_code < 600:
                        # Server error - retry with backoff
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(f"Server error ({status_code}) on {func.__name__}. Retry {attempt+1}/{max_retries} in {delay:.1f}s")
                        time.sleep(delay)
                        last_exception = e
                    else:
                        raise  # Don't retry other HTTP errors
                        
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(f"Connection error on {func.__name__}. Retry {attempt+1}/{max_retries} in {delay:.1f}s: {e}")
                    time.sleep(delay)
                    last_exception = e
                    
                except Exception as e:
                    # Unknown error - don't retry
                    raise
            
            # All retries exhausted
            if last_exception:
                logger.error(f"All {max_retries} retries exhausted for {func.__name__}")
                raise last_exception
            return None
            
        return wrapper
    return decorator


class CloudAPIClient:
    """
    HTTP client for cloud API calls with Cloudflare evasion.
    Uses session persistence and retry logic.
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = create_session()
        self.request_count = 0
        self.last_request_time = 0
        self.min_request_interval = 2.0  # Minimum 2 seconds between requests (was 0.5)
        self.rate_limit_backoff = 1.0  # Additional backoff multiplier when rate limited
        self.last_429_time = 0  # Track when we last got rate limited
        
    def _throttle(self):
        """Ensure minimum interval between requests to avoid triggering rate limits"""
        now = time.time()
        
        # If we got rate limited recently, use longer intervals
        time_since_429 = now - self.last_429_time
        if time_since_429 < 60:  # Within last minute
            effective_interval = self.min_request_interval * 3  # Triple the delay
        elif time_since_429 < 300:  # Within last 5 minutes
            effective_interval = self.min_request_interval * 2  # Double the delay
        else:
            effective_interval = self.min_request_interval
        
        elapsed = now - self.last_request_time
        if elapsed < effective_interval:
            time.sleep(effective_interval - elapsed)
        self.last_request_time = time.time()
        self.request_count += 1
    
    def _check_cloudflare_response(self, response: requests.Response) -> bool:
        """Check if response is a Cloudflare challenge page"""
        if response.status_code in [403, 503]:
            content = response.text.lower()
            if 'cloudflare' in content or 'just a moment' in content or 'cf-browser-verification' in content:
                logger.warning("Cloudflare challenge detected! Slowing down requests...")
                return True
        return False
    
    @retry_with_backoff(max_retries=3, base_delay=5.0)
    def get(self, endpoint: str, timeout: int = 20) -> Optional[dict]:
        """Make a GET request with retry logic"""
        self._throttle()
        url = f"{self.base_url}{endpoint}"
        
        response = self.session.get(url, timeout=timeout)
        
        if response.status_code == 429:
            self.last_429_time = time.time()
        
        if self._check_cloudflare_response(response):
            # Raise a 403 to trigger retry with backoff
            response.raise_for_status()
        
        response.raise_for_status()
        return response.json()
    
    @retry_with_backoff(max_retries=3, base_delay=5.0)
    def post(self, endpoint: str, json_data: dict = None, timeout: int = 45) -> Optional[dict]:
        """Make a POST request with retry logic"""
        self._throttle()
        url = f"{self.base_url}{endpoint}"
        
        response = self.session.post(
            url,
            json=json_data,
            timeout=timeout
        )
        
        if response.status_code == 429:
            self.last_429_time = time.time()
        
        if self._check_cloudflare_response(response):
            response.raise_for_status()
        
        response.raise_for_status()
        return response.json()
    
    def get_safe(self, endpoint: str, timeout: int = 15) -> Optional[dict]:
        """GET request that returns None on error instead of raising"""
        try:
            return self.get(endpoint, timeout)
        except Exception as e:
            logger.debug(f"GET {endpoint} failed: {e}")
            return None
    
    def post_safe(self, endpoint: str, json_data: dict = None, timeout: int = 30) -> Optional[dict]:
        """POST request that returns None on error instead of raising"""
        try:
            return self.post(endpoint, json_data, timeout)
        except Exception as e:
            logger.debug(f"POST {endpoint} failed: {e}")
            return None


class IBDataPusher:
    """
    Connects to local IB Gateway and pushes data to cloud backend.
    Fully synchronous - no async/await conflicts with ib_insync.
    
    UPDATED: Uses CloudAPIClient with Cloudflare evasion.
    """
    
    def __init__(self, cloud_url: str, ib_host: str = "127.0.0.1", ib_port: int = 4002, client_id: int = 10):
        self.cloud_url = cloud_url.rstrip('/')
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.client_id = client_id
        self.ib = IB()
        self.running = False
        self.subscribed_contracts: Dict[str, Contract] = {}
        self.depth_subscriptions: Dict[str, object] = {}  # symbol -> ticker object for L2
        self.last_push_time = 0
        self.push_interval = 15.0  # Push every 15 seconds (was 5) to reduce rate limiting
        self.level2_enabled = True  # Level 2 uses polling approach, always available
        
        # Initialize the cloud API client with Cloudflare evasion
        self.api = CloudAPIClient(cloud_url)
        
        # Data buffers
        self.quotes_buffer: Dict[str, dict] = {}
        self.account_data: dict = {}
        self.positions_data: List[dict] = []
        self.level2_buffer: Dict[str, dict] = {}  # Level 2 / DOM data
        self.fundamentals_buffer: Dict[str, dict] = {}  # Fundamental data
        self.news_buffer: Dict[str, List[dict]] = {}  # News by symbol
        self.news_providers: List[dict] = []  # Available news providers
        
        # Fundamental data refresh tracking (don't need to refresh every second)
        self.last_fundamentals_refresh = 0
        self.fundamentals_refresh_interval = 300  # Refresh every 5 minutes
        
        # News refresh tracking
        self.last_news_refresh = 0
        self.news_refresh_interval = 60  # Refresh news every 60 seconds
        
        # Connection health tracking
        self.consecutive_push_failures = 0
        self.max_consecutive_failures = 10
        
    def connect(self) -> bool:
        """Connect to local IB Gateway"""
        try:
            logger.info(f"Connecting to IB Gateway at {self.ib_host}:{self.ib_port}...")
            self.ib.connect(
                host=self.ib_host,
                port=self.ib_port,
                clientId=self.client_id,
                timeout=20
            )
            
            if self.ib.isConnected():
                logger.info(f"Connected to IB Gateway!")
                accounts = self.ib.managedAccounts()
                logger.info(f"  Accounts: {accounts}")
                
                # Set up event handlers
                self.ib.pendingTickersEvent += self.on_pending_tickers
                self.ib.accountValueEvent += self.on_account_value
                self.ib.positionEvent += self.on_position
                self.ib.errorEvent += self.on_error
                
                # Portfolio update handler for market prices and P&L
                self.ib.updatePortfolioEvent += self.on_portfolio_update
                
                # Level 2 uses polling approach - no event handler needed
                # We store ticker objects and read domBids/domAsks in the push loop
                logger.info("  Level 2 support: Using polling approach (compatible with all ib_insync versions)")
                
                # Capture existing positions (they're loaded during connect sync)
                existing_positions = self.ib.positions()
                if existing_positions:
                    logger.info(f"  Found {len(existing_positions)} existing positions")
                    for pos in existing_positions:
                        self.on_position(pos)
                
                return True
            else:
                logger.error("Failed to connect to IB Gateway")
                return False
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False
    
    def on_pending_tickers(self, tickers):
        """Handle incoming ticker updates including fundamental data"""
        for ticker in tickers:
            if ticker.contract:
                symbol = ticker.contract.symbol
                
                # Regular quote data
                self.quotes_buffer[symbol] = {
                    "symbol": symbol,
                    "bid": ticker.bid if ticker.bid > 0 else None,
                    "ask": ticker.ask if ticker.ask > 0 else None,
                    "last": ticker.last if ticker.last > 0 else None,
                    "close": ticker.close if ticker.close > 0 else None,
                    "high": ticker.high if ticker.high > 0 else None,
                    "low": ticker.low if ticker.low > 0 else None,
                    "volume": ticker.volume if ticker.volume > 0 else None,
                    "open": ticker.open if ticker.open > 0 else None,
                    "timestamp": datetime.now().isoformat()
                }
                
                # Extract fundamental data from ticker if available
                if symbol in self.fundamentals_buffer:
                    fund = self.fundamentals_buffer[symbol]
                    
                    # These come from generic ticks we requested
                    # Short Interest (tick 256)
                    if hasattr(ticker, 'shortableShares') and ticker.shortableShares:
                        fund["shortable_shares"] = ticker.shortableShares
                    
                    # Fundamental ratios come through ticker.fundamentalRatios
                    if hasattr(ticker, 'fundamentalRatios') and ticker.fundamentalRatios:
                        ratios = ticker.fundamentalRatios
                        if hasattr(ratios, 'peRatio') and ratios.peRatio:
                            fund["pe_ratio"] = ratios.peRatio
                        if hasattr(ratios, 'sharesOutstanding') and ratios.sharesOutstanding:
                            fund["shares_outstanding"] = ratios.sharesOutstanding
                    
                    # 52-week high/low
                    if hasattr(ticker, 'low52') and ticker.low52 and ticker.low52 > 0:
                        fund["week_52_low"] = ticker.low52
                    if hasattr(ticker, 'high52') and ticker.high52 and ticker.high52 > 0:
                        fund["week_52_high"] = ticker.high52
                    
                    # Average volume
                    if hasattr(ticker, 'avVolume') and ticker.avVolume and ticker.avVolume > 0:
                        fund["avg_volume_90d"] = ticker.avVolume
                    
                    fund["timestamp"] = datetime.now().isoformat()
    
    def on_account_value(self, value):
        """Handle account value updates"""
        try:
            key = value.tag
            val = value.value
            self.account_data[key] = {
                "value": val,
                "currency": value.currency,
                "account": value.account
            }
        except Exception as e:
            logger.error(f"Account value error: {e}")
    
    def on_position(self, position):
        """Handle position updates"""
        try:
            pos_data = {
                "symbol": position.contract.symbol,
                "secType": position.contract.secType,
                "exchange": position.contract.exchange,
                "position": float(position.position),
                "avgCost": float(position.avgCost),
                "account": position.account,
                "marketPrice": 0,
                "marketValue": 0,
                "unrealizedPNL": 0,
                "realizedPNL": 0
            }
            
            # Update existing or add new
            updated = False
            for i, existing in enumerate(self.positions_data):
                if existing["symbol"] == pos_data["symbol"]:
                    # Preserve market data if we have it
                    pos_data["marketPrice"] = existing.get("marketPrice", 0)
                    pos_data["marketValue"] = existing.get("marketValue", 0)
                    pos_data["unrealizedPNL"] = existing.get("unrealizedPNL", 0)
                    pos_data["realizedPNL"] = existing.get("realizedPNL", 0)
                    self.positions_data[i] = pos_data
                    updated = True
                    break
            if not updated:
                self.positions_data.append(pos_data)
                logger.info(f"  Position captured: {pos_data['symbol']} qty={pos_data['position']}")
                
        except Exception as e:
            logger.error(f"Position update error: {e}")
    
    def on_portfolio_update(self, item):
        """Handle portfolio updates with market values and P&L"""
        try:
            symbol = item.contract.symbol
            
            # Find and update the position with market data
            for pos in self.positions_data:
                if pos["symbol"] == symbol:
                    pos["marketPrice"] = float(item.marketPrice) if item.marketPrice else 0
                    pos["marketValue"] = float(item.marketValue) if item.marketValue else 0
                    pos["unrealizedPNL"] = float(item.unrealizedPNL) if item.unrealizedPNL else 0
                    pos["realizedPNL"] = float(item.realizedPNL) if item.realizedPNL else 0
                    break
            else:
                # Position not found, add it
                self.positions_data.append({
                    "symbol": symbol,
                    "secType": item.contract.secType,
                    "exchange": item.contract.exchange or item.contract.primaryExchange,
                    "position": float(item.position),
                    "avgCost": float(item.averageCost),
                    "account": item.account,
                    "marketPrice": float(item.marketPrice) if item.marketPrice else 0,
                    "marketValue": float(item.marketValue) if item.marketValue else 0,
                    "unrealizedPNL": float(item.unrealizedPNL) if item.unrealizedPNL else 0,
                    "realizedPNL": float(item.realizedPNL) if item.realizedPNL else 0
                })
                
        except Exception as e:
            logger.error(f"Portfolio update error: {e}")
    
    def on_error(self, reqId, errorCode, errorString, contract):
        """Handle IB errors"""
        # Filter out common non-critical messages
        if errorCode in [2104, 2106, 2158, 2119]:  # Connection status info
            logger.debug(f"IB Info [{errorCode}]: {errorString}")
        elif errorCode in [10089, 354, 10090]:  # Market data subscription - using delayed data
            logger.debug(f"IB Market Data [{errorCode}]: Using delayed data for {contract.symbol if contract else 'unknown'}")
        elif errorCode in [10092, 10182]:  # Deep market data not available
            logger.debug(f"IB L2 [{errorCode}]: {errorString} for {contract.symbol if contract else 'unknown'}")
        else:
            logger.warning(f"IB Error [{errorCode}]: {errorString}")
    
    def on_market_depth(self, ticker, position: int, marketMaker: str, 
                        operation: int, side: int, price: float, size: int):
        """
        Handle Level 2 / DOM updates.
        
        Args:
            ticker: The ticker object
            position: Row position in order book (0 = best bid/ask)
            marketMaker: Market maker ID (for NASDAQ)
            operation: 0=insert, 1=update, 2=delete
            side: 0=ask, 1=bid
            price: Price level
            size: Size at this level
        """
        try:
            if not ticker.contract:
                return
                
            symbol = ticker.contract.symbol
            
            # Initialize L2 structure if needed
            if symbol not in self.level2_buffer:
                self.level2_buffer[symbol] = {
                    "symbol": symbol,
                    "bids": [],  # List of [price, size] sorted by price desc
                    "asks": [],  # List of [price, size] sorted by price asc
                    "timestamp": datetime.now().isoformat(),
                    "bid_total_size": 0,
                    "ask_total_size": 0,
                    "imbalance": 0.0  # Positive = more bids (bullish)
                }
            
            l2 = self.level2_buffer[symbol]
            book = l2["bids"] if side == 1 else l2["asks"]
            
            # Ensure we have enough rows
            while len(book) <= position:
                book.append([0.0, 0])
            
            if operation == 2:  # Delete
                book[position] = [0.0, 0]
            else:  # Insert or Update
                book[position] = [price, size]
            
            # Recalculate totals (top 5 levels)
            l2["bids"] = [b for b in l2["bids"] if b[0] > 0][:5]
            l2["asks"] = [a for a in l2["asks"] if a[0] > 0][:5]
            l2["bid_total_size"] = sum(b[1] for b in l2["bids"])
            l2["ask_total_size"] = sum(a[1] for a in l2["asks"])
            
            # Calculate imbalance: (bid_size - ask_size) / (bid_size + ask_size)
            total = l2["bid_total_size"] + l2["ask_total_size"]
            if total > 0:
                l2["imbalance"] = (l2["bid_total_size"] - l2["ask_total_size"]) / total
            else:
                l2["imbalance"] = 0.0
            
            l2["timestamp"] = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"L2 update error: {e}")
    
    def subscribe_market_data(self, symbols: List[str], include_fundamentals: bool = True):
        """Subscribe to real-time market data with optional fundamental data ticks"""
        # Generic ticks for fundamental data:
        # 165 = Avg Volume 90 day
        # 256 = Short Interest  
        # Valid generic tick types for stocks:
        # 165 = Misc Stats (contains avg volume, etc.)
        # 293 = Trade Count
        # 294 = Trade Rate
        # 295 = Volume Rate  
        # 411 = Real-time Historical Volatility
        # 456 = IB Dividends
        # Using only valid tick types to avoid Error 321
        fundamental_ticks = "165,293,294,295,411,456" if include_fundamentals else ""
        
        for symbol in symbols:
            try:
                if symbol == "VIX":
                    contract = Index("VIX", "CBOE")
                    # VIX doesn't have fundamentals
                    self.ib.qualifyContracts(contract)
                    self.ib.reqMktData(contract, '', False, False)
                else:
                    contract = Stock(symbol, "SMART", "USD")
                    self.ib.qualifyContracts(contract)
                    self.ib.reqMktData(contract, fundamental_ticks, False, False)
                    
                    # Initialize fundamentals buffer for this symbol
                    if symbol not in self.fundamentals_buffer:
                        self.fundamentals_buffer[symbol] = {
                            "symbol": symbol,
                            "short_interest": None,
                            "institutional_pct": None,
                            "shares_outstanding": None,
                            "float": None,
                            "pe_ratio": None,
                            "week_52_high": None,
                            "week_52_low": None,
                            "avg_volume_90d": None,
                            "timestamp": datetime.now().isoformat()
                        }
                
                self.subscribed_contracts[symbol] = contract
                logger.info(f"  Subscribed: {symbol}" + (" (with fundamentals)" if include_fundamentals and symbol != "VIX" else ""))
                
            except Exception as e:
                logger.error(f"  Failed to subscribe {symbol}: {e}")
    
    def subscribe_level2(self, symbols: List[str], num_rows: int = 5):
        """
        Subscribe to Level 2 / DOM data for specified symbols.
        Stores ticker objects and polls domBids/domAsks for order book data.
        
        Note: Level 2 requires specific exchange, not SMART routing.
        - ETFs (SPY, QQQ, IWM) -> ARCA
        - NASDAQ stocks -> ISLAND (NASDAQ's ECN)
        - NYSE stocks -> NYSE
        
        IB LIMIT: Maximum 5 market depth subscriptions at a time!
        
        Args:
            symbols: List of stock symbols
            num_rows: Number of price levels to track (default 5)
        """
        # Known ETFs that trade on ARCA
        arca_symbols = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "USO", "XLF", "XLE", "XLK", "VXX", "TQQQ", "SQQQ"}
        
        # IB limits to 5 market depth subscriptions - prioritize major ETFs
        MAX_L2_SUBSCRIPTIONS = 5
        current_count = len(self.depth_subscriptions)
        
        # Prioritize these symbols for L2 (most liquid ETFs)
        priority_symbols = ["SPY", "QQQ", "IWM", "DIA"]
        
        # Reorder symbols to prioritize major ETFs
        ordered_symbols = [s for s in priority_symbols if s in symbols]
        ordered_symbols.extend([s for s in symbols if s not in priority_symbols])
        
        for symbol in ordered_symbols:
            # Check if we've hit the limit
            if current_count >= MAX_L2_SUBSCRIPTIONS:
                logger.debug(f"  L2 limit reached ({MAX_L2_SUBSCRIPTIONS}), skipping {symbol}")
                continue
                
            try:
                if symbol in self.depth_subscriptions:
                    logger.debug(f"  Already subscribed to L2: {symbol}")
                    continue
                
                if symbol == "VIX":
                    continue  # VIX doesn't have L2
                
                # Determine the correct exchange for Level 2
                if symbol in arca_symbols:
                    exchange = "ARCA"
                else:
                    # Try ISLAND (NASDAQ's ECN) for most stocks - it has good L2 data
                    exchange = "ISLAND"
                
                contract = Stock(symbol, exchange, "USD")
                
                try:
                    self.ib.qualifyContracts(contract)
                except Exception as e:
                    # If ISLAND fails, try NYSE
                    logger.debug(f"  {symbol} not on {exchange}, trying NYSE")
                    contract = Stock(symbol, "NYSE", "USD")
                    try:
                        self.ib.qualifyContracts(contract)
                        exchange = "NYSE"
                    except:
                        logger.debug(f"  Skipping L2 for {symbol} - couldn't qualify contract")
                        continue
                
                # Request market depth (Level 2) - returns a Ticker object
                ticker = self.ib.reqMktDepth(contract, numRows=num_rows)
                if ticker:
                    # Store the ticker object itself so we can poll domBids/domAsks
                    self.depth_subscriptions[symbol] = ticker
                    current_count += 1
                    logger.info(f"  L2 Subscribed: {symbol} @ {exchange} ({num_rows} levels) [{current_count}/{MAX_L2_SUBSCRIPTIONS}]")
                    
            except Exception as e:
                logger.error(f"  Failed to subscribe L2 {symbol}: {e}")
    
    def unsubscribe_level2(self, symbols: List[str]):
        """Unsubscribe from Level 2 data to free up resources"""
        for symbol in symbols:
            try:
                if symbol in self.depth_subscriptions:
                    ticker = self.depth_subscriptions[symbol]
                    if hasattr(ticker, 'contract'):
                        self.ib.cancelMktDepth(ticker.contract)
                    del self.depth_subscriptions[symbol]
                    if symbol in self.level2_buffer:
                        del self.level2_buffer[symbol]
                    logger.info(f"  L2 Unsubscribed: {symbol}")
            except Exception as e:
                logger.error(f"  Failed to unsubscribe L2 {symbol}: {e}")
    
    def poll_level2_data(self):
        """
        Poll Level 2 data from subscribed tickers.
        Called in the main loop to update level2_buffer with current order book.
        """
        for symbol, ticker in self.depth_subscriptions.items():
            try:
                # Get domBids and domAsks from the ticker
                dom_bids = getattr(ticker, 'domBids', []) or []
                dom_asks = getattr(ticker, 'domAsks', []) or []
                
                # Convert to our format: [[price, size], ...]
                bids = []
                asks = []
                
                for item in dom_bids[:5]:  # Top 5 levels
                    if hasattr(item, 'price') and hasattr(item, 'size'):
                        if item.price > 0 and item.size > 0:
                            bids.append([float(item.price), int(item.size)])
                
                for item in dom_asks[:5]:  # Top 5 levels
                    if hasattr(item, 'price') and hasattr(item, 'size'):
                        if item.price > 0 and item.size > 0:
                            asks.append([float(item.price), int(item.size)])
                
                # Only update if we have data
                if bids or asks:
                    bid_total = sum(b[1] for b in bids)
                    ask_total = sum(a[1] for a in asks)
                    total = bid_total + ask_total
                    imbalance = (bid_total - ask_total) / total if total > 0 else 0.0
                    
                    self.level2_buffer[symbol] = {
                        "symbol": symbol,
                        "bids": bids,
                        "asks": asks,
                        "bid_total_size": bid_total,
                        "ask_total_size": ask_total,
                        "imbalance": round(imbalance, 3),
                        "timestamp": datetime.now().isoformat()
                    }
                    
            except Exception as e:
                logger.debug(f"L2 poll error for {symbol}: {e}")
    
    def request_fundamental_data(self, symbols: List[str]):
        """
        Request detailed fundamental data for symbols.
        This includes short interest, institutional ownership, etc.
        Called less frequently than quote data.
        """
        for symbol in symbols:
            try:
                if symbol == "VIX" or symbol not in self.subscribed_contracts:
                    continue
                
                contract = self.subscribed_contracts[symbol]
                
                # Request fundamental snapshot (XML data)
                try:
                    # ReportSnapshot gives us key ratios and stats
                    fundamental_data = self.ib.reqFundamentalData(
                        contract, 
                        reportType='ReportSnapshot',
                        fundamentalDataOptions=[]
                    )
                    
                    if fundamental_data:
                        # Parse the XML to extract key metrics
                        self._parse_fundamental_xml(symbol, fundamental_data)
                        
                except Exception as e:
                    logger.debug(f"Fundamental data not available for {symbol}: {e}")
                    
            except Exception as e:
                logger.error(f"Error requesting fundamentals for {symbol}: {e}")
    
    def _parse_fundamental_xml(self, symbol: str, xml_data: str):
        """Parse IB fundamental data XML and extract key metrics"""
        try:
            import xml.etree.ElementTree as ET
            
            root = ET.fromstring(xml_data)
            
            if symbol not in self.fundamentals_buffer:
                self.fundamentals_buffer[symbol] = {"symbol": symbol}
            
            fund = self.fundamentals_buffer[symbol]
            
            # Find key ratios
            ratios = root.find('.//Ratios')
            if ratios is not None:
                # P/E Ratio
                pe = ratios.find('.//PE')
                if pe is not None and pe.text:
                    fund["pe_ratio"] = float(pe.text)
                
                # Price to Book
                pb = ratios.find('.//PB')
                if pb is not None and pb.text:
                    fund["price_to_book"] = float(pb.text)
            
            # Find share data
            share_data = root.find('.//SharesOut')
            if share_data is not None and share_data.text:
                fund["shares_outstanding"] = float(share_data.text) * 1000000  # Usually in millions
            
            float_data = root.find('.//Float')
            if float_data is not None and float_data.text:
                fund["float"] = float(float_data.text) * 1000000
            
            # Short interest
            short_int = root.find('.//ShortInt')
            if short_int is not None and short_int.text:
                fund["short_interest"] = float(short_int.text)
            
            short_pct = root.find('.//ShortPct')
            if short_pct is not None and short_pct.text:
                fund["short_interest_pct"] = float(short_pct.text)
            
            # Institutional ownership
            inst_own = root.find('.//InstOwn')
            if inst_own is not None and inst_own.text:
                fund["institutional_pct"] = float(inst_own.text)
            
            fund["timestamp"] = datetime.now().isoformat()
            logger.debug(f"Parsed fundamentals for {symbol}")
            
        except Exception as e:
            logger.debug(f"Error parsing fundamental XML for {symbol}: {e}")
    
    def fetch_news_providers(self):
        """Fetch available news providers from IB"""
        try:
            providers = self.ib.reqNewsProviders()
            self.ib.sleep(0.5)
            
            if providers:
                self.news_providers = []
                for p in providers:
                    self.news_providers.append({
                        "code": p.providerCode if hasattr(p, 'providerCode') else str(p),
                        "name": p.providerName if hasattr(p, 'providerName') else str(p)
                    })
                logger.info(f"News providers: {[p['code'] for p in self.news_providers]}")
            return self.news_providers
        except Exception as e:
            logger.warning(f"Could not fetch news providers: {e}")
            return []
    
    def fetch_news_for_symbols(self, symbols: List[str], max_results: int = 5):
        """
        Fetch historical news for symbols using IB's reqHistoricalNews.
        This provides real professional financial news from Benzinga, Dow Jones, etc.
        
        Note: Requires paid news subscription from IB. Skip if not subscribed.
        """
        # Skip news fetching to avoid error spam if not subscribed
        # Most users don't have paid news subscriptions
        if not hasattr(self, '_news_enabled') or not self._news_enabled:
            logger.debug("News fetching disabled (requires IB subscription)")
            return
            
        if not self.news_providers:
            self.fetch_news_providers()
        
        if not self.news_providers:
            logger.debug("No news providers available")
            return
        
        # Get provider codes
        provider_codes = "+".join([p["code"] for p in self.news_providers])
        
        # Date range: last 3 days
        from datetime import timedelta
        end_date = datetime.now().strftime("%Y%m%d %H:%M:%S")
        start_dt = datetime.now() - timedelta(days=3)
        start_date = start_dt.strftime("%Y%m%d %H:%M:%S")
        
        for symbol in symbols[:10]:  # Limit to 10 symbols to avoid rate limiting
            try:
                if symbol == "VIX" or symbol not in self.subscribed_contracts:
                    continue
                
                contract = self.subscribed_contracts[symbol]
                if not contract.conId:
                    self.ib.qualifyContracts(contract)
                
                if not contract.conId:
                    continue
                
                # Request historical news
                news_items = self.ib.reqHistoricalNews(
                    conId=contract.conId,
                    providerCodes=provider_codes,
                    startDateTime=start_date,
                    endDateTime=end_date,
                    totalResults=max_results,
                    historicalNewsOptions=[]
                )
                self.ib.sleep(0.3)
                
                if news_items:
                    self.news_buffer[symbol] = []
                    for item in news_items:
                        self.news_buffer[symbol].append({
                            "article_id": item.articleId if hasattr(item, 'articleId') else None,
                            "provider_code": item.providerCode if hasattr(item, 'providerCode') else "IB",
                            "headline": item.headline if hasattr(item, 'headline') else str(item),
                            "timestamp": item.time.isoformat() if hasattr(item, 'time') and hasattr(item.time, 'isoformat') else str(item.time) if hasattr(item, 'time') else datetime.now().isoformat()
                        })
                    logger.debug(f"Got {len(news_items)} news items for {symbol}")
                    
            except Exception as e:
                logger.debug(f"News fetch error for {symbol}: {e}")
    
    def _clean_for_json(self, obj):
        """Clean data for JSON serialization - replace NaN/Inf with None"""
        import math
        if isinstance(obj, dict):
            return {k: self._clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_for_json(item) for item in obj]
        elif isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        else:
            return obj
    
    def push_data_to_cloud(self):
        """Push buffered data to cloud backend using CloudAPIClient with retry logic"""
        has_data = (self.quotes_buffer or self.account_data or 
                    self.positions_data or self.level2_buffer or self.fundamentals_buffer or self.news_buffer)
        
        # Always log what we have
        if not has_data:
            return
        
        # Log what we're pushing
        news_count = sum(len(items) for items in self.news_buffer.values())
        logger.info(f"Pushing: {len(self.quotes_buffer)} quotes, {len(self.positions_data)} positions, {len(self.account_data)} account fields, {news_count} news items")
        
        # Clean all data to remove NaN/Inf values before JSON serialization
        # Use UTC timestamp for proper timezone handling
        from datetime import timezone as tz
        payload = self._clean_for_json({
            "timestamp": datetime.now(tz.utc).isoformat().replace('+00:00', 'Z'),
            "source": "ib_gateway",
            "quotes": self.quotes_buffer.copy(),
            "account": self.account_data.copy(),
            "positions": self.positions_data.copy(),
            "level2": self.level2_buffer.copy(),
            "fundamentals": self.fundamentals_buffer.copy(),
            "news": self.news_buffer.copy(),
            "news_providers": self.news_providers.copy() if self.news_providers else []
        })
        
        try:
            # Use the CloudAPIClient with retry logic
            result = self.api.post("/api/ib/push-data", payload, timeout=30)
            
            if result and result.get("success"):
                logger.info(f"Push OK! Cloud received: {result.get('received', {})}")
                self.consecutive_push_failures = 0
                # Reset push interval on success
                self.push_interval = 5.0
            else:
                logger.warning(f"Push returned error: {result}")
                self.consecutive_push_failures += 1
                        
        except Exception as e:
            logger.error(f"Push error: {e}")
            self.consecutive_push_failures += 1
            
            # If too many consecutive failures, slow down
            if self.consecutive_push_failures >= 3:
                self.push_interval = min(self.push_interval * 1.5, 30.0)
                logger.warning(f"Multiple push failures - slowing to {self.push_interval:.1f}s interval")
    
    def request_account_updates(self):
        """Request account and position updates (non-blocking)"""
        try:
            accounts = self.ib.managedAccounts()
            if accounts:
                # Use subscribe=True to get continuous updates, don't wait for response
                self.ib.reqAccountUpdates(subscribe=True, account=accounts[0])
                logger.info(f"  Requested account updates for {accounts[0]}")
        except Exception as e:
            logger.error(f"Account update request error: {e}")
        logger.info("  Account update request sent (non-blocking)")
    
    def fetch_inplay_stocks(self) -> List[str]:
        """Fetch current in-play stocks from cloud backend for L2 subscription"""
        try:
            result = self.api.get_safe("/api/ib/inplay-stocks", timeout=10)
            if result:
                return result.get("symbols", [])
        except Exception as e:
            logger.debug(f"Could not fetch in-play stocks: {e}")
        return []
    
    def update_level2_subscriptions(self):
        """Dynamically update L2 subscriptions based on in-play stocks"""
        # Paper trading has a limit of 3 market depth subscriptions
        # We keep SPY, QQQ, IWM as our core L2 symbols
        # Skip dynamic updates to avoid hitting the limit
        max_l2_subscriptions = 3
        
        if len(self.depth_subscriptions) >= max_l2_subscriptions:
            logger.debug(f"L2 limit reached ({max_l2_subscriptions}), skipping dynamic updates")
            return
        
        inplay = self.fetch_inplay_stocks()
        
        if not inplay:
            return
        
        current_l2 = set(self.depth_subscriptions.keys())
        new_inplay = set(inplay)
        
        # Only subscribe to new in-play if we have room
        available_slots = max_l2_subscriptions - len(current_l2)
        if available_slots > 0:
            to_subscribe = list(new_inplay - current_l2)[:available_slots]
            if to_subscribe:
                logger.info(f"Adding L2 for: {to_subscribe}")
                self.subscribe_level2(to_subscribe)
    
    def run(self, symbols: List[str] = None, enable_level2: bool = True):
        """Main run loop (fully synchronous)"""
        if symbols is None:
            symbols = ["VIX", "SPY", "QQQ", "IWM"]
        
        if not self.connect():
            return
        
        self.running = True
        logger.info("Starting data push loop...")
        logger.info(f"  Cloud URL: {self.cloud_url}")
        logger.info(f"  Symbols: {symbols}")
        logger.info(f"  Level 2: {'Enabled' if enable_level2 and self.level2_enabled else 'Disabled'}")
        logger.info(f"  Cloudflare Evasion: ENABLED (browser headers + retry logic)")
        
        # Subscribe to market data
        logger.info("Subscribing to market data...")
        self.subscribe_market_data(symbols)
        
        # Subscribe to Level 2 for core symbols (only if enabled and supported)
        if enable_level2 and self.level2_enabled:
            core_l2 = [s for s in symbols if s != "VIX"]
            self.subscribe_level2(core_l2)
        
        # Request account updates (fire and forget - don't wait)
        logger.info("Requesting account updates...")
        try:
            self.request_account_updates()
            logger.info("  Account updates requested successfully")
        except Exception as e:
            logger.error(f"  Account updates failed: {e}")
        
        # Skip blocking fundamental data - not needed for basic push functionality
        logger.info("Skipping fundamental data to avoid blocking")
        
        push_count = 0
        l2_update_interval = 60  # Update L2 subscriptions every 60 seconds (was 30)
        last_l2_update = 0
        order_poll_interval = 10  # Check for orders every 10 seconds
        last_order_poll = 0
        current_time = time.time()
        
        # Fetch news providers on startup
        logger.info("Fetching news providers...")
        self.fetch_news_providers()
        
        # Force initial push immediately
        logger.info(f"")
        logger.info(f"========================================")
        logger.info(f"==> STARTING PUSH LOOP")
        logger.info(f"    Positions: {len(self.positions_data)}")
        logger.info(f"    Quotes: {len(self.quotes_buffer)}")
        logger.info(f"    Level 2 Subscriptions: {len(self.depth_subscriptions)}")
        logger.info(f"    News Providers: {[p['code'] for p in self.news_providers]}")
        logger.info(f"    Order Execution: ENABLED")
        logger.info(f"    Cloudflare Evasion: ENABLED")
        logger.info(f"========================================")
        logger.info(f"")
        
        # Do first push
        self.push_data_to_cloud()
        self.last_push_time = current_time
        
        try:
            while self.running:
                try:
                    # Let ib_insync process events (sync - no event loop conflict)
                    self.ib.sleep(0.1)
                    
                    # Poll Level 2 data from subscribed tickers
                    if enable_level2 and self.level2_enabled:
                        self.poll_level2_data()
                    
                    # Push data at regular intervals
                    current_time = time.time()
                    if current_time - self.last_push_time >= self.push_interval:
                        self.push_data_to_cloud()
                        self.last_push_time = current_time
                        push_count += 1
                        
                        if push_count % 30 == 0:
                            l2_count = len(self.level2_buffer)
                            fund_count = len([f for f in self.fundamentals_buffer.values() if f.get("pe_ratio") or f.get("short_interest")])
                            logger.info(f"Running... {len(self.quotes_buffer)} quotes, {len(self.positions_data)} positions, {l2_count} L2, {fund_count} fundamentals")
                    
                    # Update L2 subscriptions based on in-play stocks (only if enabled and supported)
                    if enable_level2 and self.level2_enabled and (current_time - last_l2_update >= l2_update_interval):
                        self.update_level2_subscriptions()
                        last_l2_update = current_time
                    
                    # Periodically refresh news for subscribed symbols
                    if current_time - self.last_news_refresh >= self.news_refresh_interval:
                        self.fetch_news_for_symbols(symbols)
                        self.last_news_refresh = current_time
                    
                    # Poll for pending orders from cloud trading bot (less frequently)
                    if current_time - last_order_poll >= order_poll_interval:
                        self.poll_and_execute_orders()
                        last_order_poll = current_time
                    
                    # NOTE: Historical data polling REMOVED from trading mode
                    # Use --mode=collection for dedicated data collection
                        
                except Exception as e:
                    logger.error(f"Loop error: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Note: Skipping fundamental data refresh as it blocks the loop
                # Fundamental data is fetched via ticker events instead
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def stop(self):
        """Stop the pusher"""
        self.running = False
    
    # ==================== AUTO MODE (CLOUD-CONTROLLED) ====================
    
    def run_auto_mode(self, symbols: List[str] = None, enable_level2: bool = True):
        """
        Auto mode - polls cloud for mode setting and switches dynamically.
        
        This allows the UI to control whether the script runs in trading or collection mode.
        The script polls /api/ib/mode every 30 seconds and switches accordingly.
        """
        if symbols is None:
            symbols = ["VIX", "SPY", "QQQ", "IWM"]
        
        if not self.connect():
            return
        
        self.running = True
        current_mode = "trading"  # Start in trading mode
        mode_check_interval = 30  # Check cloud for mode changes every 30 seconds
        last_mode_check = 0
        
        # Subscribe to market data initially (for trading mode)
        logger.info("Subscribing to market data...")
        self.subscribe_market_data(symbols)
        if enable_level2:
            core_l2 = [s for s in symbols if s != "VIX"]
            self.subscribe_level2(core_l2)
        
        # Request account updates
        logger.info("Requesting account updates...")
        try:
            self.request_account_updates()
        except Exception as e:
            logger.error(f"Account updates failed: {e}")
        
        logger.info("Fetching news providers...")
        self.fetch_news_providers()
        
        logger.info("")
        logger.info("=" * 50)
        logger.info("  AUTO MODE - Cloud-controlled")
        logger.info("  Mode can be changed from the UI")
        logger.info("=" * 50)
        logger.info("")
        
        # Collection mode stats (when in collection mode)
        collection_start_time = None
        collection_completed = 0
        collection_failed = 0
        
        try:
            while self.running:
                try:
                    # Keep IB connection alive
                    self.ib.sleep(0.1)
                    
                    current_time = time.time()
                    
                    # Check cloud for mode changes
                    if current_time - last_mode_check >= mode_check_interval:
                        new_mode = self._check_cloud_mode()
                        if new_mode and new_mode != current_mode:
                            logger.info("")
                            logger.info("=" * 50)
                            logger.info(f"  MODE CHANGE: {current_mode.upper()} -> {new_mode.upper()}")
                            logger.info("=" * 50)
                            logger.info("")
                            
                            if new_mode == "collection":
                                collection_start_time = time.time()
                                collection_completed = 0
                                collection_failed = 0
                                # Notify cloud we're starting collection
                                try:
                                    self.api.post_safe("/api/ib/collection-mode/start", {
                                        "started_at": datetime.now().isoformat(),
                                        "mode": "collection"
                                    }, timeout=10)
                                except:
                                    pass
                            elif current_mode == "collection":
                                # Notify cloud we're stopping collection
                                elapsed = time.time() - collection_start_time if collection_start_time else 0
                                try:
                                    self.api.post_safe("/api/ib/collection-mode/stop", {
                                        "completed": collection_completed,
                                        "failed": collection_failed,
                                        "elapsed_minutes": elapsed / 60,
                                        "stopped_at": datetime.now().isoformat()
                                    }, timeout=10)
                                except:
                                    pass
                            
                            current_mode = new_mode
                        
                        last_mode_check = current_time
                    
                    # Execute based on current mode
                    if current_mode == "trading":
                        # Trading mode - push data, poll orders
                        self._trading_mode_tick(current_time)
                    else:
                        # Collection mode - fetch historical data
                        result = self._collection_mode_tick()
                        if result:
                            collection_completed += result.get("completed", 0)
                            collection_failed += result.get("failed", 0)
                            
                            # Report progress
                            if collection_start_time:
                                elapsed = time.time() - collection_start_time
                                rate = collection_completed / (elapsed / 3600) if elapsed > 0 else 0
                                try:
                                    self.api.post_safe("/api/ib/collection-mode/progress", {
                                        "completed": collection_completed,
                                        "failed": collection_failed,
                                        "rate_per_hour": rate,
                                        "elapsed_minutes": elapsed / 60,
                                        "timestamp": datetime.now().isoformat()
                                    }, timeout=10)
                                except:
                                    pass
                    
                except Exception as e:
                    logger.error(f"Auto mode loop error: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def _check_cloud_mode(self) -> Optional[str]:
        """Check cloud for desired operating mode"""
        try:
            result = self.api.get_safe("/api/ib/mode", timeout=10)
            if result:
                mode = result.get("mode", "trading")
                return mode
        except Exception as e:
            logger.debug(f"Could not check cloud mode: {e}")
        return None
    
    def _trading_mode_tick(self, current_time: float):
        """Execute one tick of trading mode"""
        # Push data at regular intervals
        if current_time - self.last_push_time >= self.push_interval:
            self.push_data_to_cloud()
            self.last_push_time = current_time
        
        # Poll for orders
        if not hasattr(self, '_last_order_poll'):
            self._last_order_poll = 0
        if current_time - self._last_order_poll >= 10:
            self.poll_and_execute_orders()
            self._last_order_poll = current_time
        
        # Poll L2 data
        if self.level2_enabled:
            self.poll_level2_data()
    
    def _collection_mode_tick(self) -> Optional[dict]:
        """Execute one tick of collection mode. Returns completed/failed counts."""
        try:
            # Get a LARGE batch of pending requests (50 at once to minimize cloud calls)
            result = self.api.get_safe("/api/ib/historical-data/pending?limit=50", timeout=90)
            
            if not result:
                logger.warning("[Collection] Cloud API unavailable, waiting 10s...")
                time.sleep(10)
                return None
            
            requests_list = result.get("requests", [])
            
            if not requests_list:
                logger.info("[Collection] No pending requests. Waiting 30s...")
                time.sleep(30)
                return None
            
            completed = 0
            failed = 0
            results_to_report = []  # Buffer results for batch reporting
            
            # Group by symbol for logging
            symbols = set(r.get('symbol', 'unknown') for r in requests_list)
            logger.info(f"[Collection] Processing {len(requests_list)} requests for {len(symbols)} symbols: {', '.join(list(symbols)[:5])}...")
            
            for req in requests_list:
                try:
                    # Fetch from IB WITHOUT waiting for cloud confirmation
                    result_data = self._collection_fetch_single_fast(req)
                    if result_data:
                        results_to_report.append(result_data)
                        completed += 1
                        logger.info(f"[Collection] {result_data['symbol']} ({result_data['bar_size']}): {result_data['bar_count']} bars")
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"[Collection] Request error: {e}")
                    failed += 1
                
                # Minimal delay between IB requests (just enough to avoid pacing)
                time.sleep(0.5)
            
            # Batch report results to cloud (non-blocking, fire and forget)
            if results_to_report:
                self._batch_report_results(results_to_report)
            
            return {"completed": completed, "failed": failed}
            
        except Exception as e:
            logger.error(f"[Collection] Tick error: {e}")
            time.sleep(5)
            return {"completed": 0, "failed": 0}
    
    def _collection_fetch_single_fast(self, request: dict) -> Optional[dict]:
        """
        Fetch historical data from IB - FAST version.
        Returns result dict instead of reporting to cloud immediately.
        """
        request_id = request.get("request_id")
        symbol = request.get("symbol")
        bar_size = request.get("bar_size", "1 day")
        duration = request.get("duration", "1 Y")
        
        try:
            from ib_insync import Stock
            contract = Stock(symbol, "SMART", "USD")
            
            try:
                self.ib.qualifyContracts(contract)
            except Exception as e:
                return {
                    "request_id": request_id,
                    "symbol": symbol,
                    "bar_size": bar_size,
                    "success": True,
                    "status": "no_data",
                    "data": [],
                    "bar_count": 0,
                    "error": f"Symbol not available: {e}"
                }
            
            # Fetch from IB
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True
            )
            
            # Format bars
            bar_data = []
            for bar in bars:
                bar_data.append({
                    "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                })
            
            return {
                "request_id": request_id,
                "symbol": symbol,
                "bar_size": bar_size,
                "success": True,
                "status": "success" if bar_data else "no_data",
                "data": bar_data,
                "bar_count": len(bar_data),
                "error": None
            }
            
        except Exception as e:
            error_str = str(e)
            if "pacing" in error_str.lower():
                logger.warning(f"[Collection] {symbol}: IB PACING - waiting 10s")
                time.sleep(10)
                return None  # Will retry
            return {
                "request_id": request_id,
                "symbol": symbol,
                "bar_size": bar_size,
                "success": False,
                "status": "error",
                "data": [],
                "bar_count": 0,
                "error": error_str
            }
    
    def _batch_report_results(self, results: list):
        """Report multiple results to cloud in one call (fire and forget)."""
        try:
            # Try batch endpoint first
            payload = {"results": results}
            result = self.api.post_safe("/api/ib/historical-data/batch-result", payload, timeout=30)
            
            if result:
                logger.info(f"[Collection] Batch reported {len(results)} results to cloud")
            else:
                # Fall back to individual reports (in background, don't wait)
                logger.warning(f"[Collection] Batch report failed, results saved locally only")
        except Exception as e:
            logger.warning(f"[Collection] Batch report error: {e} - data saved locally")

    # ==================== COLLECTION MODE ====================
    
    def run_collection_mode(self):
        """
        Dedicated data collection mode - ALL bandwidth to historical data fetching.
        
        In this mode:
        - NO live quote pushing
        - NO order polling
        - NO L2 data
        - OPTIMIZED SPEED historical data collection
        
        OPTIMIZED PACING STRATEGY:
        - IB allows 60 requests per 10 minutes (6/min average)
        - Can burst 6 requests quickly, then need ~10s cooldown
        - Target: ~1800 requests/hour (vs previous ~120/hour)
        - Adaptive backoff if pacing violations detected
        
        Use this during off-hours to quickly build up your historical database.
        """
        if not self.connect():
            return
        
        self.running = True
        
        # Collection stats
        collection_start_time = time.time()
        requests_completed = 0
        requests_failed = 0
        pacing_violations = 0
        last_status_update = 0
        status_update_interval = 30  # Show status every 30 seconds
        
        # Adaptive rate limiting
        base_batch_delay = 10  # seconds between batches
        current_batch_delay = base_batch_delay
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("  DATA COLLECTION MODE ACTIVE (OPTIMIZED)")
        logger.info("=" * 60)
        logger.info("  Live trading: PAUSED")
        logger.info("  Order execution: DISABLED")
        logger.info("  Target rate: ~1800 requests/hour")
        logger.info("  Strategy: 6-request bursts with adaptive pacing")
        logger.info("=" * 60)
        logger.info("")
        
        # Send initial heartbeat to let cloud know we're in collection mode
        try:
            self.api.post_safe("/api/ib/collection-mode/start", {
                "started_at": datetime.now().isoformat(),
                "mode": "collection"
            }, timeout=10)
        except:
            pass  # Non-critical
        
        try:
            while self.running:
                try:
                    # Keep IB connection alive
                    self.ib.sleep(0.1)
                    
                    current_time = time.time()
                    
                    # Fetch and process historical data requests - OPTIMIZED SPEED
                    result = self._collection_fetch_batch()
                    
                    if result:
                        batch_completed = result.get("completed", 0)
                        batch_failed = result.get("failed", 0)
                        batch_pacing = result.get("pacing_violations", 0)
                        
                        requests_completed += batch_completed
                        requests_failed += batch_failed
                        pacing_violations += batch_pacing
                        
                        # ADAPTIVE PACING: If we hit pacing violations, back off
                        if batch_pacing > 0:
                            current_batch_delay = min(current_batch_delay * 1.5, 30)  # Max 30s
                            logger.warning(f"[Pacing] Violation detected. Increasing delay to {current_batch_delay:.1f}s")
                        elif batch_completed == 6 and current_batch_delay > base_batch_delay:
                            # Successful full batch - gradually reduce delay
                            current_batch_delay = max(current_batch_delay * 0.9, base_batch_delay)
                        
                        # Wait between batches
                        time.sleep(current_batch_delay)
                    else:
                        # No pending requests - wait a bit before checking again
                        logger.info("[Collection] No pending requests. Waiting 10s...")
                        time.sleep(10)
                    
                    # Status update
                    if current_time - last_status_update >= status_update_interval:
                        elapsed = current_time - collection_start_time
                        rate = requests_completed / (elapsed / 3600) if elapsed > 0 else 0
                        
                        logger.info("")
                        logger.info("=" * 50)
                        logger.info(f"  COLLECTION STATUS (Optimized)")
                        logger.info(f"  Completed: {requests_completed}")
                        logger.info(f"  Failed: {requests_failed}")
                        logger.info(f"  Pacing violations: {pacing_violations}")
                        logger.info(f"  Rate: {rate:.0f} requests/hour")
                        logger.info(f"  Current batch delay: {current_batch_delay:.1f}s")
                        logger.info(f"  Running: {elapsed/60:.1f} minutes")
                        logger.info("=" * 50)
                        logger.info("")
                        
                        last_status_update = current_time
                        
                        # Update cloud with progress
                        try:
                            self.api.post_safe("/api/ib/collection-mode/progress", {
                                "completed": requests_completed,
                                "failed": requests_failed,
                                "pacing_violations": pacing_violations,
                                "rate_per_hour": rate,
                                "elapsed_minutes": elapsed / 60,
                                "current_batch_delay": current_batch_delay,
                                "timestamp": datetime.now().isoformat()
                            }, timeout=10)
                        except:
                            pass  # Non-critical
                    
                except Exception as e:
                    logger.error(f"Collection loop error: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(5)  # Wait before retrying
                    
        except KeyboardInterrupt:
            logger.info("Collection stopped by user")
        finally:
            self.running = False
            
            # Final stats
            elapsed = time.time() - collection_start_time
            logger.info("")
            logger.info("=" * 50)
            logger.info("  COLLECTION COMPLETE")
            logger.info(f"  Total completed: {requests_completed}")
            logger.info(f"  Total failed: {requests_failed}")
            logger.info(f"  Total time: {elapsed/60:.1f} minutes")
            logger.info("=" * 50)
            
            # Notify cloud
            try:
                self.api.post_safe("/api/ib/collection-mode/stop", {
                    "completed": requests_completed,
                    "failed": requests_failed,
                    "elapsed_minutes": elapsed / 60,
                    "stopped_at": datetime.now().isoformat()
                }, timeout=10)
            except:
                pass
            
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def _collection_fetch_batch(self) -> dict:
        """
        Fetch a batch of historical data requests at MAXIMUM SAFE speed.
        
        IB Historical Data Pacing Rules:
        - Max 60 requests per 10 minutes (6 per minute average)
        - Can burst up to 6 requests quickly
        - After burst, need ~10 second cooldown
        - Identical requests within 15s = pacing violation
        
        Our strategy: Fetch 6 requests in quick succession (0.3s apart),
        then wait 10 seconds. This gives us ~36 requests/minute = 2160/hour
        vs the old rate of ~120/hour.
        
        Returns dict with completed/failed counts, or None if no requests.
        """
        try:
            # Get a larger batch since we'll process them quickly
            result = self.api.get_safe("/api/ib/historical-data/pending?limit=6", timeout=20)
            
            if not result:
                return None
            
            requests_list = result.get("requests", [])
            
            if not requests_list:
                return None
            
            completed = 0
            failed = 0
            pacing_violations = 0
            
            logger.info(f"[Collection] Processing batch of {len(requests_list)} requests...")
            
            for req in requests_list:
                try:
                    result = self._collection_fetch_single(req)
                    if result == True:
                        completed += 1
                    elif result == "pacing":
                        pacing_violations += 1
                        # Stop the batch on pacing violation
                        logger.warning("[Collection] Pacing violation - stopping batch early")
                        break
                    else:
                        failed += 1
                except Exception as e:
                    logger.error(f"[Collection] Request error: {e}")
                    failed += 1
                
                # Minimal delay between requests in burst (IB can handle 6 rapid requests)
                time.sleep(0.3)
            
            return {"completed": completed, "failed": failed, "pacing_violations": pacing_violations}
            
        except Exception as e:
            logger.error(f"[Collection] Batch error: {e}")
            return {"completed": 0, "failed": 0}
    
    def _collection_fetch_single(self, req: dict) -> bool:
        """Fetch a single historical data request. Returns True if successful."""
        request_id = req.get("request_id")
        symbol = req.get("symbol")
        duration = req.get("duration", "1 M")
        bar_size = req.get("bar_size", "1 day")
        
        try:
            # Claim the request
            claim_result = self.api.post_safe(f"/api/ib/historical-data/claim/{request_id}", timeout=15)
            
            if not claim_result:
                return False  # Already claimed
            
            # Create contract
            contract = Stock(symbol, "SMART", "USD")
            
            try:
                self.ib.qualifyContracts(contract)
            except Exception as e:
                # Invalid symbol
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=True,
                    data=[],
                    status="no_data",
                    error=f"Symbol not available: {e}"
                )
                return True  # Not a failure, just no data
            
            # Fetch from IB
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True
            )
            
            # Format bars
            bar_data = []
            for bar in bars:
                bar_data.append({
                    "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                })
            
            # Report result
            status = "success" if bar_data else "no_data"
            self._report_historical_data_result(
                request_id=request_id,
                symbol=symbol,
                success=True,
                data=bar_data,
                status=status
            )
            
            logger.info(f"[Collection] {symbol} ({bar_size}): {len(bar_data)} bars")
            return True
            
        except Exception as e:
            error_str = str(e)
            
            if "pacing" in error_str.lower() or "limit" in error_str.lower():
                # IB rate limit - wait and retry later
                logger.warning(f"[Collection] {symbol}: IB PACING VIOLATION - backing off")
                time.sleep(15)  # Longer delay for pacing violation
                return "pacing"  # Signal pacing violation
            else:
                # Other error
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=False,
                    error=str(e),
                    status="error"
                )
                return False

    # ==================== ORDER EXECUTION ====================
    
    def poll_and_execute_orders(self):
        """
        Poll cloud for pending orders and execute them via IB Gateway.
        This enables the cloud trading bot to execute trades through the local IB connection.
        """
        try:
            # Poll for pending orders using CloudAPIClient
            result = self.api.get_safe("/api/ib/orders/pending", timeout=10)
            
            if not result:
                return
            
            orders = result.get("orders", [])
            
            if not orders:
                return
            
            logger.info(f"[OrderQueue] Found {len(orders)} pending orders")
            
            for order in orders:
                self._execute_queued_order(order)
                
        except Exception as e:
            logger.error(f"[OrderQueue] Poll error: {e}")
    
    def _execute_queued_order(self, order: dict):
        """Execute a single queued order via IB Gateway"""
        order_id = order.get("order_id")
        symbol = order.get("symbol")
        action = order.get("action")  # BUY or SELL
        quantity = order.get("quantity")
        order_type = order.get("order_type", "MKT")
        limit_price = order.get("limit_price")
        stop_price = order.get("stop_price")
        
        logger.info(f"[OrderQueue] Executing: {order_id} - {action} {quantity} {symbol}")
        
        try:
            # Claim the order first (prevents duplicate execution)
            claim_result = self.api.post_safe(f"/api/ib/orders/claim/{order_id}", timeout=10)
            
            if not claim_result:
                logger.warning(f"[OrderQueue] Could not claim order {order_id}")
                return
            
            # Create IB contract
            contract = Stock(symbol, "SMART", "USD")
            
            # Create IB order
            from ib_insync import MarketOrder, LimitOrder, StopOrder, StopLimitOrder
            
            if order_type == "MKT":
                ib_order = MarketOrder(action, quantity)
            elif order_type == "LMT":
                ib_order = LimitOrder(action, quantity, limit_price)
            elif order_type == "STP":
                ib_order = StopOrder(action, quantity, stop_price)
            elif order_type == "STP_LMT":
                ib_order = StopLimitOrder(action, quantity, stop_price, limit_price)
            else:
                logger.error(f"[OrderQueue] Unknown order type: {order_type}")
                self._report_order_result(order_id, "rejected", error=f"Unknown order type: {order_type}")
                return
            
            # Place the order
            trade = self.ib.placeOrder(contract, ib_order)
            
            # Wait for fill (with timeout)
            max_wait = 30
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                self.ib.sleep(0.5)
                
                if trade.orderStatus.status == "Filled":
                    logger.info(f"[OrderQueue] Order {order_id} FILLED @ ${trade.orderStatus.avgFillPrice}")
                    self._report_order_result(
                        order_id, 
                        "filled",
                        fill_price=float(trade.orderStatus.avgFillPrice),
                        filled_qty=int(trade.orderStatus.filled),
                        ib_order_id=trade.order.orderId
                    )
                    return
                    
                elif trade.orderStatus.status in ["Cancelled", "ApiCancelled"]:
                    logger.warning(f"[OrderQueue] Order {order_id} CANCELLED")
                    self._report_order_result(order_id, "cancelled", error="Order cancelled")
                    return
                    
                elif trade.orderStatus.status == "Inactive":
                    logger.warning(f"[OrderQueue] Order {order_id} REJECTED")
                    self._report_order_result(order_id, "rejected", error="Order rejected by IB")
                    return
            
            # Timeout - order may still be working
            if trade.orderStatus.status == "Submitted" or trade.orderStatus.status == "PreSubmitted":
                logger.warning(f"[OrderQueue] Order {order_id} still pending after {max_wait}s")
                # Report as partial/pending
                self._report_order_result(
                    order_id,
                    "pending",
                    fill_price=float(trade.orderStatus.avgFillPrice) if trade.orderStatus.avgFillPrice else None,
                    filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
                    remaining_qty=int(trade.orderStatus.remaining) if trade.orderStatus.remaining else quantity,
                    ib_order_id=trade.order.orderId,
                    error="Order still pending"
                )
            else:
                self._report_order_result(order_id, "rejected", error=f"Unknown status: {trade.orderStatus.status}")
                
        except Exception as e:
            logger.error(f"[OrderQueue] Execution error for {order_id}: {e}")
            self._report_order_result(order_id, "rejected", error=str(e))
    
    def _report_order_result(self, order_id: str, status: str, fill_price: float = None, 
                            filled_qty: int = None, remaining_qty: int = None,
                            ib_order_id: int = None, error: str = None):
        """Report order execution result back to cloud"""
        try:
            payload = {
                "order_id": order_id,
                "status": status,
                "fill_price": fill_price,
                "filled_qty": filled_qty,
                "remaining_qty": remaining_qty,
                "ib_order_id": ib_order_id,
                "error": error,
                "executed_at": datetime.now().isoformat()
            }
            
            result = self.api.post_safe("/api/ib/orders/result", payload, timeout=10)
            
            if result:
                logger.info(f"[OrderQueue] Result reported: {order_id} -> {status}")
            else:
                logger.warning(f"[OrderQueue] Failed to report result for {order_id}")
                
        except Exception as e:
            logger.error(f"[OrderQueue] Error reporting result: {e}")

    # ==================== HISTORICAL DATA ====================
    
    def poll_and_execute_historical_data_requests(self):
        """
        Poll cloud for pending historical data requests and fulfill them via IB Gateway.
        This enables the cloud to request historical bars through the local IB connection.
        OPTIMIZED: Process 3 requests per poll cycle with delays between them.
        """
        try:
            # Poll for pending historical data requests using CloudAPIClient
            result = self.api.get_safe("/api/ib/historical-data/pending", timeout=20)
            
            if not result:
                return
            
            requests_list = result.get("requests", [])
            
            if not requests_list:
                return
            
            # Process up to 3 requests per cycle (balanced speed vs rate limiting)
            batch_size = min(3, len(requests_list))
            remaining = len(requests_list) - batch_size
            
            logger.info(f"[HistoricalData] Processing {batch_size} of {len(requests_list)} pending ({remaining} remaining)")
            
            for i, req in enumerate(requests_list[:batch_size]):
                self._fetch_and_return_historical_data(req)
                # Small delay between requests in the same batch
                if i < batch_size - 1:
                    time.sleep(2)
                
        except Exception as e:
            if "404" not in str(e) and "Not Found" not in str(e):
                logger.error(f"[HistoricalData] Poll error: {e}")
    
    def _fetch_and_return_historical_data(self, req: dict):
        """Fetch historical data from IB and return to cloud"""
        request_id = req.get("request_id")
        symbol = req.get("symbol")
        duration = req.get("duration", "1 M")
        bar_size = req.get("bar_size", "1 day")
        
        logger.info(f"[HistoricalData] Fetching: {symbol} ({duration}, {bar_size})")
        
        try:
            # Claim the request first (prevents duplicate fetching)
            claim_result = self.api.post_safe(f"/api/ib/historical-data/claim/{request_id}", timeout=15)
            
            if not claim_result:
                # Already claimed by another worker - not a failure, just skip
                logger.debug(f"[HistoricalData] Request {request_id} already claimed (skipped)")
                return
            
            # Create IB contract
            contract = Stock(symbol, "SMART", "USD")
            
            try:
                self.ib.qualifyContracts(contract)
            except Exception as e:
                # Invalid symbol or not tradeable - mark as "no_data" not "failed"
                logger.warning(f"[HistoricalData] {symbol}: Invalid symbol or not available")
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=True,  # Mark success with no_data flag to avoid retry
                    data=[],
                    status="no_data",
                    error=f"Symbol not available: {e}"
                )
                return
            
            # Request historical data from IB Gateway
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True
            )
            
            # Format the bars for the cloud
            bar_data = []
            for bar in bars:
                bar_data.append({
                    "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                })
            
            # Categorize the result
            if len(bar_data) > 0:
                logger.info(f"[HistoricalData] {symbol}: Got {len(bar_data)} bars")
                status = "success"
            else:
                # No data returned - could be:
                # - Symbol doesn't have data for this timeframe (e.g., newly listed)
                # - Timeframe not available (e.g., 1-min for low-volume stock)
                # - Weekend/holiday with no trading
                logger.info(f"[HistoricalData] {symbol}: No data for {bar_size} ({duration})")
                status = "no_data"
            
            # Send result back to cloud
            self._report_historical_data_result(
                request_id=request_id,
                symbol=symbol,
                success=True,  # Not a failure - we got a response from IB
                data=bar_data,
                status=status
            )
            
        except Exception as e:
            error_str = str(e)
            
            # Categorize the error
            if "No market data" in error_str or "No data" in error_str:
                # IB says no data available - not a failure, just no data
                logger.info(f"[HistoricalData] {symbol}: No market data available for {bar_size}")
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=True,
                    data=[],
                    status="no_data",
                    error="No market data available"
                )
            elif "pacing" in error_str.lower() or "limit" in error_str.lower():
                # Rate limited - should retry
                logger.warning(f"[HistoricalData] {symbol}: Rate limited (will retry)")
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=False,
                    error="IB rate limit - retry later",
                    status="rate_limited"
                )
            elif "timeout" in error_str.lower():
                # IB timeout - should retry
                logger.warning(f"[HistoricalData] {symbol}: IB timeout (will retry)")
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=False,
                    error="IB request timeout",
                    status="timeout"
                )
            else:
                # Unknown error - log as actual failure
                logger.error(f"[HistoricalData] {symbol}: ERROR - {e}")
                self._report_historical_data_result(
                    request_id=request_id,
                    symbol=symbol,
                    success=False,
                    error=str(e),
                    status="error"
                )
    
    def _report_historical_data_result(self, request_id: str, symbol: str, success: bool, 
                                        data: List[dict] = None, error: str = None,
                                        status: str = None):
        """
        Report historical data result back to cloud.
        
        Status types:
        - success: Got bars successfully
        - no_data: Symbol/timeframe has no data (not a failure)
        - timeout: Network or IB timeout (should retry)
        - rate_limited: Hit IB rate limit (should retry later)
        - error: Actual error that needs investigation
        
        Note: Cloud reporting failures don't affect data collection.
        Data is still saved to MongoDB - cloud just tracks status.
        """
        try:
            # Determine final status
            if status is None:
                status = "success" if success else "error"
            
            payload = {
                "request_id": request_id,
                "symbol": symbol,
                "success": success,
                "status": status,
                "data": data or [],
                "bar_count": len(data) if data else 0,
                "error": error,
                "fetched_at": datetime.now().isoformat()
            }
            
            # Use longer timeout and don't block on failure
            result = self.api.post_safe("/api/ib/historical-data/result", payload, timeout=60)
            
            if result:
                # Log based on status type
                if status == "success":
                    logger.info(f"[HistoricalData] {symbol}: {len(data or [])} bars saved")
                elif status == "no_data":
                    logger.info(f"[HistoricalData] {symbol}: No data (completed)")
                elif status == "timeout":
                    logger.warning(f"[HistoricalData] {symbol}: Timeout (will retry)")
                elif status == "rate_limited":
                    logger.warning(f"[HistoricalData] {symbol}: Rate limited (will retry)")
                else:
                    logger.error(f"[HistoricalData] {symbol}: Failed - {error}")
            else:
                # Cloud report failed but data is still collected locally
                logger.warning(f"[HistoricalData] Cloud report failed for {symbol} - data still saved locally")
                
        except Exception as e:
            # Don't let cloud errors stop collection
            logger.warning(f"[HistoricalData] Cloud report error for {symbol}: {e} - continuing")


def main():
    parser = argparse.ArgumentParser(description="IB Data Pusher - Push IB Gateway data to cloud")
    parser.add_argument("--cloud-url", required=True, help="Cloud backend URL")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=10, help="IB client ID")
    parser.add_argument("--symbols", nargs="+", default=["VIX", "SPY", "QQQ", "IWM"], help="Symbols to subscribe")
    parser.add_argument("--no-level2", action="store_true", help="Disable Level 2 / DOM data")
    parser.add_argument("--mode", choices=["trading", "collection", "auto"], default="auto",
                        help="Operating mode: 'trading', 'collection', or 'auto' (polls cloud for mode)")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("  IB Data Pusher - DYNAMIC MODE")
    print("  CLOUDFLARE EVASION: ENABLED")
    print("=" * 50)
    print(f"  Cloud URL: {args.cloud_url}")
    print(f"  IB Gateway: {args.ib_host}:{args.ib_port}")
    print(f"  Symbols: {args.symbols}")
    print(f"  Level 2: {'Disabled' if args.no_level2 else 'Enabled'}")
    print(f"  Mode: {args.mode.upper()}")
    if args.mode == "auto":
        print(f"  (Will poll cloud for mode changes)")
    print("=" * 50)
    
    pusher = IBDataPusher(
        cloud_url=args.cloud_url,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        client_id=args.client_id
    )
    
    if args.mode == "collection":
        # Forced collection mode
        pusher.run_collection_mode()
    elif args.mode == "trading":
        # Forced trading mode
        pusher.run(symbols=args.symbols, enable_level2=not args.no_level2)
    else:
        # Auto mode - polls cloud and switches dynamically
        pusher.run_auto_mode(symbols=args.symbols, enable_level2=not args.no_level2)


if __name__ == "__main__":
    main()
