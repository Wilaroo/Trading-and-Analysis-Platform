"""
Interactive Brokers Integration Service
Connects to IB Gateway/TWS for real-time data and paper trading
"""
import asyncio
import logging
from typing import Optional, List, Dict, Callable, Any
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# IB Configuration
IB_HOST = os.environ.get("IB_HOST", "127.0.0.1")
IB_PORT = int(os.environ.get("IB_PORT", "4002"))
IB_CLIENT_ID = int(os.environ.get("IB_CLIENT_ID", "1"))
IB_ACCOUNT_ID = os.environ.get("IB_ACCOUNT_ID", "")


class IBService:
    """Interactive Brokers connection and trading service"""
    
    def __init__(self):
        self.ib = None
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 30
        self.market_data_subscriptions: Dict[str, Any] = {}
        self.price_callbacks: List[Callable] = []
        self._connection_lock = asyncio.Lock()
        
    async def connect(self) -> bool:
        """Connect to Interactive Brokers Gateway/TWS"""
        async with self._connection_lock:
            if self.is_connected and self.ib and self.ib.isConnected():
                return True
                
            try:
                from ib_insync import IB, util
                
                # Enable nested event loops for Jupyter/async compatibility
                import nest_asyncio
                nest_asyncio.apply()
                
                if self.ib is None:
                    self.ib = IB()
                
                logger.info(f"Connecting to IB at {IB_HOST}:{IB_PORT} with client ID {IB_CLIENT_ID}")
                
                await self.ib.connectAsync(
                    host=IB_HOST,
                    port=IB_PORT,
                    clientId=IB_CLIENT_ID,
                    timeout=10
                )
                
                self.is_connected = True
                self.reconnect_attempts = 0
                
                # Set up disconnection handler
                self.ib.disconnectedEvent += self._on_disconnect
                
                # Set up error handler
                self.ib.errorEvent += self._on_error
                
                logger.info(f"Successfully connected to IB Gateway. Account: {IB_ACCOUNT_ID}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to IB: {e}")
                self.is_connected = False
                return False
    
    def _on_disconnect(self):
        """Handle disconnection events"""
        logger.warning("Disconnected from Interactive Brokers")
        self.is_connected = False
        # Schedule reconnection
        asyncio.create_task(self._attempt_reconnect())
    
    def _on_error(self, reqId, errorCode, errorString, contract):
        """Handle IB error events"""
        # Common non-critical error codes to ignore
        ignore_codes = [2104, 2106, 2158, 2119]  # Market data farm connection messages
        if errorCode not in ignore_codes:
            logger.warning(f"IB Error {errorCode}: {errorString} (reqId: {reqId})")
    
    async def _attempt_reconnect(self):
        """Attempt to reconnect with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max reconnection attempts exceeded")
            return
        
        self.reconnect_attempts += 1
        delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), 300)
        
        logger.info(f"Attempting reconnect in {delay}s (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        await asyncio.sleep(delay)
        
        await self.connect()
    
    async def disconnect(self):
        """Disconnect from Interactive Brokers"""
        if self.ib and self.ib.isConnected():
            # Cancel all market data subscriptions
            for symbol, ticker in self.market_data_subscriptions.items():
                try:
                    self.ib.cancelMktData(ticker.contract)
                except:
                    pass
            self.market_data_subscriptions.clear()
            
            self.ib.disconnect()
            self.is_connected = False
            logger.info("Disconnected from IB")
    
    def get_connection_status(self) -> Dict:
        """Get current connection status"""
        return {
            "connected": self.is_connected and self.ib and self.ib.isConnected() if self.ib else False,
            "host": IB_HOST,
            "port": IB_PORT,
            "client_id": IB_CLIENT_ID,
            "account_id": IB_ACCOUNT_ID,
            "reconnect_attempts": self.reconnect_attempts
        }
    
    async def get_account_summary(self) -> Dict:
        """Retrieve account summary information"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        account_values = self.ib.accountValues(IB_ACCOUNT_ID)
        
        summary = {
            "account_id": IB_ACCOUNT_ID,
            "net_liquidation": 0.0,
            "buying_power": 0.0,
            "cash": 0.0,
            "total_cash_value": 0.0,
            "available_funds": 0.0,
            "excess_liquidity": 0.0,
            "gross_position_value": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        value_mapping = {
            "NetLiquidation": "net_liquidation",
            "BuyingPower": "buying_power",
            "CashBalance": "cash",
            "TotalCashValue": "total_cash_value",
            "AvailableFunds": "available_funds",
            "ExcessLiquidity": "excess_liquidity",
            "GrossPositionValue": "gross_position_value",
            "RealizedPnL": "realized_pnl",
            "UnrealizedPnL": "unrealized_pnl"
        }
        
        for av in account_values:
            if av.tag in value_mapping and av.currency == "USD":
                try:
                    summary[value_mapping[av.tag]] = float(av.value)
                except (ValueError, TypeError):
                    pass
        
        return summary
    
    async def get_positions(self) -> List[Dict]:
        """Get all current positions"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        positions = []
        for pos in self.ib.positions():
            if pos.account == IB_ACCOUNT_ID:
                positions.append({
                    "symbol": pos.contract.symbol,
                    "sec_type": pos.contract.secType,
                    "exchange": pos.contract.exchange,
                    "currency": pos.contract.currency,
                    "quantity": float(pos.position),
                    "avg_cost": float(pos.avgCost),
                    "market_value": float(pos.position) * float(pos.avgCost)
                })
        
        return positions
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get real-time quote for a symbol"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            return None
        
        try:
            from ib_insync import Stock
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            await self.ib.qualifyContractsAsync(contract)
            
            # Request market data snapshot
            ticker = self.ib.reqMktData(contract, "", True, False)
            
            # Wait briefly for data
            await asyncio.sleep(0.5)
            
            # Get ticker data
            if ticker:
                return {
                    "symbol": symbol.upper(),
                    "price": ticker.last if ticker.last else ticker.close,
                    "bid": ticker.bid if ticker.bid else 0,
                    "ask": ticker.ask if ticker.ask else 0,
                    "bid_size": ticker.bidSize if ticker.bidSize else 0,
                    "ask_size": ticker.askSize if ticker.askSize else 0,
                    "volume": ticker.volume if ticker.volume else 0,
                    "high": ticker.high if ticker.high else 0,
                    "low": ticker.low if ticker.low else 0,
                    "open": ticker.open if ticker.open else 0,
                    "close": ticker.close if ticker.close else 0,
                    "change": (ticker.last - ticker.close) if ticker.last and ticker.close else 0,
                    "change_percent": ((ticker.last - ticker.close) / ticker.close * 100) if ticker.last and ticker.close and ticker.close != 0 else 0,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "IB"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None
    
    async def subscribe_market_data(self, symbol: str, callback: Callable = None) -> bool:
        """Subscribe to streaming market data for a symbol"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            return False
        
        try:
            from ib_insync import Stock
            
            if symbol.upper() in self.market_data_subscriptions:
                return True  # Already subscribed
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            await self.ib.qualifyContractsAsync(contract)
            
            ticker = self.ib.reqMktData(contract, "", False, False)
            self.market_data_subscriptions[symbol.upper()] = ticker
            
            if callback:
                self.price_callbacks.append(callback)
            
            logger.info(f"Subscribed to market data for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error subscribing to {symbol}: {e}")
            return False
    
    async def unsubscribe_market_data(self, symbol: str) -> bool:
        """Unsubscribe from market data for a symbol"""
        if symbol.upper() in self.market_data_subscriptions:
            try:
                ticker = self.market_data_subscriptions[symbol.upper()]
                self.ib.cancelMktData(ticker.contract)
                del self.market_data_subscriptions[symbol.upper()]
                logger.info(f"Unsubscribed from market data for {symbol}")
                return True
            except Exception as e:
                logger.error(f"Error unsubscribing from {symbol}: {e}")
        return False
    
    async def place_order(
        self,
        symbol: str,
        action: str,  # "BUY" or "SELL"
        quantity: int,
        order_type: str = "MKT",  # "MKT", "LMT", "STP", "STP_LMT"
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> Optional[Dict]:
        """Place an order"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        try:
            from ib_insync import Stock, MarketOrder, LimitOrder, StopOrder, StopLimitOrder
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            await self.ib.qualifyContractsAsync(contract)
            
            # Create order based on type
            if order_type == "MKT":
                order = MarketOrder(action.upper(), quantity)
            elif order_type == "LMT":
                if limit_price is None:
                    raise ValueError("Limit price required for limit orders")
                order = LimitOrder(action.upper(), quantity, limit_price)
            elif order_type == "STP":
                if stop_price is None:
                    raise ValueError("Stop price required for stop orders")
                order = StopOrder(action.upper(), quantity, stop_price)
            elif order_type == "STP_LMT":
                if stop_price is None or limit_price is None:
                    raise ValueError("Both stop and limit prices required for stop-limit orders")
                order = StopLimitOrder(action.upper(), quantity, limit_price, stop_price)
            else:
                raise ValueError(f"Unsupported order type: {order_type}")
            
            # Place the order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait briefly for order acknowledgment
            await asyncio.sleep(0.5)
            
            return {
                "order_id": trade.order.orderId,
                "perm_id": trade.order.permId,
                "symbol": symbol.upper(),
                "action": action.upper(),
                "quantity": quantity,
                "order_type": order_type,
                "limit_price": limit_price,
                "stop_price": stop_price,
                "status": trade.orderStatus.status,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining,
                "avg_fill_price": trade.orderStatus.avgFillPrice,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            raise
    
    async def cancel_order(self, order_id: int) -> bool:
        """Cancel an open order"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        try:
            for trade in self.ib.openTrades():
                if trade.order.orderId == order_id:
                    self.ib.cancelOrder(trade.order)
                    logger.info(f"Cancelled order {order_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    async def get_open_orders(self) -> List[Dict]:
        """Get all open orders"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        orders = []
        for trade in self.ib.openTrades():
            orders.append({
                "order_id": trade.order.orderId,
                "perm_id": trade.order.permId,
                "symbol": trade.contract.symbol,
                "action": trade.order.action,
                "quantity": trade.order.totalQuantity,
                "order_type": trade.order.orderType,
                "limit_price": trade.order.lmtPrice,
                "stop_price": trade.order.auxPrice,
                "status": trade.orderStatus.status,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining,
                "avg_fill_price": trade.orderStatus.avgFillPrice
            })
        
        return orders
    
    async def get_executions(self) -> List[Dict]:
        """Get today's executions/fills"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        executions = []
        for fill in self.ib.fills():
            executions.append({
                "exec_id": fill.execution.execId,
                "order_id": fill.execution.orderId,
                "symbol": fill.contract.symbol,
                "side": fill.execution.side,
                "shares": fill.execution.shares,
                "price": fill.execution.price,
                "time": fill.execution.time.isoformat() if fill.execution.time else None,
                "commission": fill.commissionReport.commission if fill.commissionReport else 0
            })
        
        return executions
    
    async def get_historical_data(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "5 mins"
    ) -> List[Dict]:
        """Get historical bar data"""
        if not self.is_connected or not self.ib or not self.ib.isConnected():
            raise ConnectionError("Not connected to IB")
        
        try:
            from ib_insync import Stock
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            await self.ib.qualifyContractsAsync(contract)
            
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True
            )
            
            return [
                {
                    "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                }
                for bar in bars
            ]
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return []


# Singleton instance
_ib_service: Optional[IBService] = None


def get_ib_service() -> IBService:
    """Get or create the IB service singleton"""
    global _ib_service
    if _ib_service is None:
        _ib_service = IBService()
    return _ib_service
