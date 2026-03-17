"""
IB Data Pusher - Runs on your local machine
Connects to IB Gateway locally and pushes data to the cloud backend.

Usage:
    python ib_data_pusher.py --cloud-url https://data-pipeline-test-6.preview.emergentagent.com

This script should be run on your trading laptop alongside IB Gateway.
"""
import argparse
import json
import logging
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional

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


class IBDataPusher:
    """
    Connects to local IB Gateway and pushes data to cloud backend.
    Fully synchronous — no async/await conflicts with ib_insync.
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
        self.push_interval = 2.0  # Push every 2 seconds (reduced from 1 to lower load)
        self.level2_enabled = True  # Level 2 uses polling approach, always available
        
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
        elif errorCode in [10089, 354, 10090]:  # Market data subscription — using delayed data
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
        
        Args:
            symbols: List of stock symbols
            num_rows: Number of price levels to track (default 5)
        """
        # Known ETFs that trade on ARCA
        arca_symbols = {"SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "USO", "XLF", "XLE", "XLK", "VXX", "TQQQ", "SQQQ"}
        
        for symbol in symbols:
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
                    logger.info(f"  L2 Subscribed: {symbol} @ {exchange} ({num_rows} levels)")
                    
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
        """
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
        """Push buffered data to cloud backend (synchronous)"""
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
            response = requests.post(
                f"{self.cloud_url}/api/ib/push-data",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10  # Increased timeout for slower connections
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.info(f"Push OK! Cloud received: {result.get('received', {})}")
                else:
                    logger.warning(f"Push returned error: {result}")
            else:
                logger.warning(f"Push failed: HTTP {response.status_code} - {response.text[:200]}")
                        
        except requests.Timeout:
            logger.warning("Push timeout - retrying on next cycle")
        except Exception as e:
            logger.error(f"Push error: {e}")
    
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
            response = requests.get(
                f"{self.cloud_url}/api/ib/inplay-stocks",
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
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
        l2_update_interval = 30
        last_l2_update = 0
        order_poll_interval = 2  # Check for orders every 2 seconds
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
        logger.info(f"========================================")
        logger.info(f"")
        
        # Do first push
        self.push_data_to_cloud()
        self.last_push_time = current_time
        
        try:
            while self.running:
                try:
                    # Let ib_insync process events (sync — no event loop conflict)
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
                    
                    # Poll for pending orders from cloud trading bot
                    if current_time - last_order_poll >= order_poll_interval:
                        self.poll_and_execute_orders()
                        self.poll_and_execute_historical_data_requests()
                        last_order_poll = current_time
                        
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
    
    # ==================== ORDER EXECUTION ====================
    
    def poll_and_execute_orders(self):
        """
        Poll cloud for pending orders and execute them via IB Gateway.
        This enables the cloud trading bot to execute trades through the local IB connection.
        """
        try:
            # Poll for pending orders
            response = requests.get(
                f"{self.cloud_url}/api/ib/orders/pending",
                timeout=5
            )
            
            if response.status_code != 200:
                return
            
            result = response.json()
            orders = result.get("orders", [])
            
            if not orders:
                return
            
            logger.info(f"[OrderQueue] Found {len(orders)} pending orders")
            
            for order in orders:
                self._execute_queued_order(order)
                
        except requests.Timeout:
            pass  # Silent timeout, will retry next cycle
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
            claim_response = requests.post(
                f"{self.cloud_url}/api/ib/orders/claim/{order_id}",
                timeout=5
            )
            
            if claim_response.status_code != 200:
                logger.warning(f"[OrderQueue] Could not claim order {order_id}: {claim_response.text}")
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
            
            response = requests.post(
                f"{self.cloud_url}/api/ib/orders/result",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            if response.status_code == 200:
                logger.info(f"[OrderQueue] Result reported: {order_id} -> {status}")
            else:
                logger.warning(f"[OrderQueue] Failed to report result: {response.text}")
                
        except Exception as e:
            logger.error(f"[OrderQueue] Error reporting result: {e}")

    # ==================== HISTORICAL DATA ====================
    
    def poll_and_execute_historical_data_requests(self):
        """
        Poll cloud for pending historical data requests and fulfill them via IB Gateway.
        This enables the cloud to request historical bars through the local IB connection.
        """
        try:
            # Poll for pending historical data requests
            response = requests.get(
                f"{self.cloud_url}/api/ib/historical-data/pending",
                timeout=5
            )
            
            if response.status_code != 200:
                return
            
            result = response.json()
            requests_list = result.get("requests", [])
            
            if not requests_list:
                return
            
            logger.info(f"[HistoricalData] Found {len(requests_list)} pending requests")
            
            for req in requests_list:
                self._fetch_and_return_historical_data(req)
                
        except requests.Timeout:
            pass  # Silent timeout, will retry next cycle
        except requests.exceptions.ConnectionError:
            pass  # Server might not have this endpoint yet
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
            claim_response = requests.post(
                f"{self.cloud_url}/api/ib/historical-data/claim/{request_id}",
                timeout=5
            )
            
            if claim_response.status_code != 200:
                logger.warning(f"[HistoricalData] Could not claim request {request_id}")
                return
            
            # Create IB contract
            contract = Stock(symbol, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            
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
            
            logger.info(f"[HistoricalData] Got {len(bar_data)} bars for {symbol}")
            
            # Send result back to cloud
            self._report_historical_data_result(
                request_id=request_id,
                symbol=symbol,
                success=True,
                data=bar_data
            )
            
        except Exception as e:
            logger.error(f"[HistoricalData] Error fetching {symbol}: {e}")
            self._report_historical_data_result(
                request_id=request_id,
                symbol=symbol,
                success=False,
                error=str(e)
            )
    
    def _report_historical_data_result(self, request_id: str, symbol: str, success: bool, 
                                        data: List[dict] = None, error: str = None):
        """Report historical data result back to cloud"""
        try:
            payload = {
                "request_id": request_id,
                "symbol": symbol,
                "success": success,
                "data": data or [],
                "error": error,
                "fetched_at": datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{self.cloud_url}/api/ib/historical-data/result",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"[HistoricalData] Result reported: {symbol} -> {'success' if success else 'failed'}")
            else:
                logger.warning(f"[HistoricalData] Failed to report result: {response.text}")
                
        except Exception as e:
            logger.error(f"[HistoricalData] Error reporting result: {e}")


def main():
    parser = argparse.ArgumentParser(description="IB Data Pusher - Push IB Gateway data to cloud")
    parser.add_argument("--cloud-url", required=True, help="Cloud backend URL")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=10, help="IB client ID")
    parser.add_argument("--symbols", nargs="+", default=["VIX", "SPY", "QQQ", "IWM"], help="Symbols to subscribe")
    parser.add_argument("--no-level2", action="store_true", help="Disable Level 2 / DOM data")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("  IB Data Pusher")
    print("=" * 50)
    print(f"  Cloud URL: {args.cloud_url}")
    print(f"  IB Gateway: {args.ib_host}:{args.ib_port}")
    print(f"  Symbols: {args.symbols}")
    print(f"  Level 2: {'Disabled' if args.no_level2 else 'Enabled'}")
    print("=" * 50)
    
    pusher = IBDataPusher(
        cloud_url=args.cloud_url,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        client_id=args.client_id
    )
    
    pusher.run(symbols=args.symbols, enable_level2=not args.no_level2)


if __name__ == "__main__":
    main()
