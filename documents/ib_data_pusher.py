"""
IB Data Pusher - Runs on your local machine
Connects to IB Gateway locally and pushes data to the cloud backend.

Usage:
    python ib_data_pusher.py --cloud-url https://playbook-drc-gen.preview.emergentagent.com

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
        self.depth_subscriptions: Dict[str, int] = {}  # symbol -> reqId for L2
        self.last_push_time = 0
        self.push_interval = 1.0  # Push every 1 second
        
        # Data buffers
        self.quotes_buffer: Dict[str, dict] = {}
        self.account_data: dict = {}
        self.positions_data: List[dict] = []
        self.level2_buffer: Dict[str, dict] = {}  # Level 2 / DOM data
        
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
                self.ib.updateMktDepthEvent += self.on_market_depth
                
                return True
            else:
                logger.error("Failed to connect to IB Gateway")
                return False
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False
    
    def on_pending_tickers(self, tickers):
        """Handle incoming ticker updates"""
        for ticker in tickers:
            if ticker.contract:
                symbol = ticker.contract.symbol
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
                "account": position.account
            }
            
            # Update existing or add new
            updated = False
            for i, existing in enumerate(self.positions_data):
                if existing["symbol"] == pos_data["symbol"]:
                    self.positions_data[i] = pos_data
                    updated = True
                    break
            if not updated:
                self.positions_data.append(pos_data)
                
        except Exception as e:
            logger.error(f"Position update error: {e}")
    
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
    
    def subscribe_market_data(self, symbols: List[str]):
        """Subscribe to real-time market data (skips symbols without live subscriptions)"""
        for symbol in symbols:
            try:
                if symbol == "VIX":
                    contract = Index("VIX", "CBOE")
                else:
                    contract = Stock(symbol, "SMART", "USD")
                
                self.ib.qualifyContracts(contract)
                self.ib.reqMktData(contract, '', False, False)
                self.subscribed_contracts[symbol] = contract
                logger.info(f"  Subscribed: {symbol}")
                
            except Exception as e:
                logger.error(f"  Failed to subscribe {symbol}: {e}")
    
    def subscribe_level2(self, symbols: List[str], num_rows: int = 5):
        """
        Subscribe to Level 2 / DOM data for specified symbols.
        Only subscribe to in-play stocks to minimize data volume.
        
        Args:
            symbols: List of stock symbols
            num_rows: Number of price levels to track (default 5)
        """
        for symbol in symbols:
            try:
                if symbol in self.depth_subscriptions:
                    logger.debug(f"  Already subscribed to L2: {symbol}")
                    continue
                
                if symbol == "VIX":
                    continue  # VIX doesn't have L2
                
                contract = Stock(symbol, "SMART", "USD")
                self.ib.qualifyContracts(contract)
                
                # Request market depth (Level 2)
                ticker = self.ib.reqMktDepth(contract, numRows=num_rows)
                if ticker:
                    self.depth_subscriptions[symbol] = id(ticker)
                    logger.info(f"  L2 Subscribed: {symbol} ({num_rows} levels)")
                    
            except Exception as e:
                logger.error(f"  Failed to subscribe L2 {symbol}: {e}")
    
    def unsubscribe_level2(self, symbols: List[str]):
        """Unsubscribe from Level 2 data to free up resources"""
        for symbol in symbols:
            try:
                if symbol in self.depth_subscriptions:
                    if symbol in self.subscribed_contracts:
                        contract = self.subscribed_contracts[symbol]
                        self.ib.cancelMktDepth(contract)
                    del self.depth_subscriptions[symbol]
                    if symbol in self.level2_buffer:
                        del self.level2_buffer[symbol]
                    logger.info(f"  L2 Unsubscribed: {symbol}")
            except Exception as e:
                logger.error(f"  Failed to unsubscribe L2 {symbol}: {e}")
    
    def push_data_to_cloud(self):
        """Push buffered data to cloud backend (synchronous)"""
        if not self.quotes_buffer and not self.account_data and not self.positions_data and not self.level2_buffer:
            return
            
        payload = {
            "timestamp": datetime.now().isoformat(),
            "source": "ib_gateway",
            "quotes": self.quotes_buffer.copy(),
            "account": self.account_data.copy(),
            "positions": self.positions_data.copy(),
            "level2": self.level2_buffer.copy()  # Add Level 2 data
        }
        
        try:
            response = requests.post(
                f"{self.cloud_url}/api/ib/push-data",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    l2_count = len(self.level2_buffer)
                    logger.debug(f"Pushed {len(self.quotes_buffer)} quotes, {len(self.positions_data)} positions, {l2_count} L2")
            else:
                logger.warning(f"Push failed: HTTP {response.status_code}")
                        
        except requests.Timeout:
            logger.warning("Push timeout - cloud backend may be slow")
        except Exception as e:
            logger.error(f"Push error: {e}")
    
    def request_account_updates(self):
        """Request account and position updates"""
        try:
            accounts = self.ib.managedAccounts()
            if accounts:
                self.ib.reqAccountUpdates(accounts[0])
                logger.info(f"  Requested account updates for {accounts[0]}")
        except Exception as e:
            logger.error(f"Account update request error: {e}")
    
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
        inplay = self.fetch_inplay_stocks()
        
        if not inplay:
            return
        
        current_l2 = set(self.depth_subscriptions.keys())
        new_inplay = set(inplay)
        
        # Subscribe to new in-play stocks
        to_subscribe = new_inplay - current_l2
        if to_subscribe:
            logger.info(f"Adding L2 for: {list(to_subscribe)}")
            self.subscribe_level2(list(to_subscribe))
        
        # Unsubscribe from stocks no longer in-play (keep core symbols)
        core_symbols = {"SPY", "QQQ", "IWM"}
        to_unsubscribe = current_l2 - new_inplay - core_symbols
        if to_unsubscribe:
            logger.info(f"Removing L2 for: {list(to_unsubscribe)}")
            self.unsubscribe_level2(list(to_unsubscribe))
    
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
        logger.info(f"  Level 2: {'Enabled' if enable_level2 else 'Disabled'}")
        
        # Subscribe to market data
        self.subscribe_market_data(symbols)
        
        # Subscribe to Level 2 for core symbols
        if enable_level2:
            core_l2 = [s for s in symbols if s != "VIX"]
            self.subscribe_level2(core_l2)
        
        # Request account updates
        self.request_account_updates()
        
        push_count = 0
        l2_update_interval = 30  # Check for in-play changes every 30 seconds
        last_l2_update = 0
        
        try:
            while self.running:
                # Let ib_insync process events (sync — no event loop conflict)
                self.ib.sleep(0.1)
                
                # Push data at regular intervals
                current_time = time.time()
                if current_time - self.last_push_time >= self.push_interval:
                    self.push_data_to_cloud()
                    self.last_push_time = current_time
                    push_count += 1
                    
                    if push_count % 30 == 0:
                        l2_count = len(self.level2_buffer)
                        logger.info(f"Running... {len(self.quotes_buffer)} quotes, {len(self.positions_data)} positions, {l2_count} L2")
                
                # Update L2 subscriptions based on in-play stocks
                if enable_level2 and (current_time - last_l2_update >= l2_update_interval):
                    self.update_level2_subscriptions()
                    last_l2_update = current_time
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def stop(self):
        """Stop the pusher"""
        self.running = False


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
