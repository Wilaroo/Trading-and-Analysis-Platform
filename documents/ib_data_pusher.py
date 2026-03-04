"""
IB Data Pusher - Runs on your local machine
Connects to IB Gateway locally and pushes data to the cloud backend.

Usage:
    python ib_data_pusher.py --cloud-url https://trader-nexus-2.preview.emergentagent.com

This script should be run on your trading laptop alongside IB Gateway.
"""
import asyncio
import argparse
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp
from ib_insync import IB, Stock, Index, Contract, util

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
    """
    
    def __init__(self, cloud_url: str, ib_host: str = "127.0.0.1", ib_port: int = 4002, client_id: int = 10):
        self.cloud_url = cloud_url.rstrip('/')
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.client_id = client_id
        self.ib = IB()
        self.running = False
        self.subscribed_contracts: Dict[str, Contract] = {}
        self.last_push_time = 0
        self.push_interval = 1.0  # Push every 1 second
        
        # Data buffers
        self.quotes_buffer: Dict[str, dict] = {}
        self.account_data: dict = {}
        self.positions_data: List[dict] = []
        
    async def connect(self) -> bool:
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
                logger.info(f"✓ Connected to IB Gateway!")
                accounts = self.ib.managedAccounts()
                logger.info(f"  Accounts: {accounts}")
                
                # Set up event handlers
                self.ib.pendingTickersEvent += self.on_pending_tickers
                self.ib.accountValueEvent += self.on_account_value
                self.ib.positionEvent += self.on_position
                self.ib.errorEvent += self.on_error
                
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
                    "timestamp": datetime.now().isoformat()
                }
    
    def on_account_value(self, value):
        """Handle account value updates"""
        if value.tag in ["NetLiquidation", "TotalCashValue", "GrossPositionValue", "BuyingPower"]:
            self.account_data[value.tag] = {
                "value": float(value.value) if value.value else 0,
                "currency": value.currency,
                "account": value.account
            }
    
    def on_position(self, position):
        """Handle position updates"""
        pos_data = {
            "symbol": position.contract.symbol,
            "secType": position.contract.secType,
            "quantity": float(position.position),
            "avgCost": float(position.avgCost),
            "account": position.account
        }
        
        # Update or add position
        for i, p in enumerate(self.positions_data):
            if p["symbol"] == pos_data["symbol"]:
                self.positions_data[i] = pos_data
                return
        self.positions_data.append(pos_data)
    
    def on_error(self, reqId, errorCode, errorString, contract):
        """Handle IB errors"""
        # Ignore common non-critical errors
        if errorCode in [2104, 2106, 2158, 2119]:  # Market data farm messages
            return
        logger.warning(f"IB Error {errorCode}: {errorString}")
    
    async def subscribe_market_data(self, symbols: List[str]):
        """Subscribe to market data for symbols"""
        for symbol in symbols:
            if symbol in self.subscribed_contracts:
                continue
                
            try:
                # Determine contract type
                if symbol == "VIX":
                    contract = Index(symbol, "CBOE")
                else:
                    contract = Stock(symbol, "SMART", "USD")
                
                self.ib.qualifyContracts(contract)
                self.ib.reqMktData(contract, "", False, False)
                self.subscribed_contracts[symbol] = contract
                logger.info(f"  Subscribed to {symbol}")
                
            except Exception as e:
                logger.error(f"  Failed to subscribe to {symbol}: {e}")
    
    async def push_data_to_cloud(self):
        """Push buffered data to cloud backend"""
        if not self.quotes_buffer and not self.account_data and not self.positions_data:
            return
            
        payload = {
            "timestamp": datetime.now().isoformat(),
            "source": "ib_gateway",
            "quotes": self.quotes_buffer.copy(),
            "account": self.account_data.copy(),
            "positions": self.positions_data.copy()
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.cloud_url}/api/ib/push-data",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("success"):
                            logger.debug(f"Pushed {len(self.quotes_buffer)} quotes, {len(self.positions_data)} positions")
                    else:
                        logger.warning(f"Push failed: HTTP {response.status}")
                        
        except asyncio.TimeoutError:
            logger.warning("Push timeout - cloud backend may be slow")
        except Exception as e:
            logger.error(f"Push error: {e}")
    
    async def request_account_updates(self):
        """Request account and position updates"""
        try:
            accounts = self.ib.managedAccounts()
            if accounts:
                self.ib.reqAccountUpdates(True, accounts[0])
                logger.info(f"  Requested account updates for {accounts[0]}")
        except Exception as e:
            logger.error(f"Account update request error: {e}")
    
    async def run(self, symbols: List[str] = None):
        """Main run loop"""
        if symbols is None:
            symbols = ["VIX", "SPY", "QQQ", "IWM"]  # Default symbols
        
        if not await self.connect():
            return
        
        self.running = True
        logger.info("Starting data push loop...")
        logger.info(f"  Cloud URL: {self.cloud_url}")
        logger.info(f"  Symbols: {symbols}")
        
        # Subscribe to market data
        await self.subscribe_market_data(symbols)
        
        # Request account updates
        await self.request_account_updates()
        
        try:
            while self.running:
                # Let ib_insync process events
                self.ib.sleep(0.1)
                
                # Push data at regular intervals
                current_time = time.time()
                if current_time - self.last_push_time >= self.push_interval:
                    await self.push_data_to_cloud()
                    self.last_push_time = current_time
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")
    
    def stop(self):
        """Stop the pusher"""
        self.running = False


async def main():
    parser = argparse.ArgumentParser(description="IB Data Pusher - Push IB Gateway data to cloud")
    parser.add_argument("--cloud-url", required=True, help="Cloud backend URL")
    parser.add_argument("--ib-host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--ib-port", type=int, default=4002, help="IB Gateway port")
    parser.add_argument("--client-id", type=int, default=10, help="IB client ID")
    parser.add_argument("--symbols", nargs="+", default=["VIX", "SPY", "QQQ", "IWM"], help="Symbols to subscribe")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("  IB Data Pusher")
    print("=" * 50)
    print(f"  Cloud URL: {args.cloud_url}")
    print(f"  IB Gateway: {args.ib_host}:{args.ib_port}")
    print(f"  Symbols: {args.symbols}")
    print("=" * 50)
    
    pusher = IBDataPusher(
        cloud_url=args.cloud_url,
        ib_host=args.ib_host,
        ib_port=args.ib_port,
        client_id=args.client_id
    )
    
    await pusher.run(symbols=args.symbols)


if __name__ == "__main__":
    asyncio.run(main())
