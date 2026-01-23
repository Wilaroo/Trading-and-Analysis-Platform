"""
Interactive Brokers Integration Service
Connects to IB Gateway/TWS for real-time data and paper trading

This implementation uses a dedicated thread for all IB operations to avoid
asyncio event loop conflicts between FastAPI and ib_insync on Windows.
Communication between FastAPI and the IB thread uses thread-safe queues.
"""
import threading
import queue
import logging
import os
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dotenv import load_dotenv
from dataclasses import dataclass
from enum import Enum

load_dotenv()

logger = logging.getLogger(__name__)

# IB Configuration
IB_HOST = os.environ.get("IB_HOST", "127.0.0.1")
IB_PORT = int(os.environ.get("IB_PORT", "4002"))
IB_CLIENT_ID = int(os.environ.get("IB_CLIENT_ID", "1"))
IB_ACCOUNT_ID = os.environ.get("IB_ACCOUNT_ID", "")


class IBCommand(Enum):
    """Commands that can be sent to the IB thread"""
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    GET_ACCOUNT_SUMMARY = "get_account_summary"
    GET_POSITIONS = "get_positions"
    GET_QUOTE = "get_quote"
    GET_QUOTES_BATCH = "get_quotes_batch"
    PLACE_ORDER = "place_order"
    CANCEL_ORDER = "cancel_order"
    GET_OPEN_ORDERS = "get_open_orders"
    GET_EXECUTIONS = "get_executions"
    GET_HISTORICAL_DATA = "get_historical_data"
    RUN_SCANNER = "run_scanner"
    GET_FUNDAMENTALS = "get_fundamentals"
    SHUTDOWN = "shutdown"


@dataclass
class IBRequest:
    """Request to send to the IB thread"""
    command: IBCommand
    params: Dict[str, Any] = None
    response_queue: queue.Queue = None


@dataclass
class IBResponse:
    """Response from the IB thread"""
    success: bool
    data: Any = None
    error: str = None


class IBWorkerThread(threading.Thread):
    """
    Dedicated thread for all Interactive Brokers operations.
    This thread owns the asyncio event loop and the ib_insync connection.
    """
    
    def __init__(self, request_queue: queue.Queue):
        super().__init__(daemon=True, name="IBWorkerThread")
        self.request_queue = request_queue
        self.ib = None
        self.is_connected = False
        self._running = True
        self._loop = None
        
    def run(self):
        """Main thread loop - processes commands from the queue"""
        import asyncio
        
        # Create a new event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        logger.info("IB Worker Thread started")
        
        while self._running:
            try:
                # Wait for a request with timeout to allow checking _running flag
                try:
                    request: IBRequest = self.request_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Process the request
                response = self._process_request(request)
                
                # Send response back if response queue provided
                if request.response_queue:
                    request.response_queue.put(response)
                    
            except Exception as e:
                logger.error(f"Error in IB worker thread: {e}")
        
        # Cleanup
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
        
        self._loop.close()
        logger.info("IB Worker Thread stopped")
    
    def _process_request(self, request: IBRequest) -> IBResponse:
        """Process a single request synchronously"""
        try:
            if request.command == IBCommand.SHUTDOWN:
                self._running = False
                return IBResponse(success=True)
            
            elif request.command == IBCommand.CONNECT:
                return self._do_connect()
            
            elif request.command == IBCommand.DISCONNECT:
                return self._do_disconnect()
            
            elif request.command == IBCommand.GET_ACCOUNT_SUMMARY:
                return self._do_get_account_summary()
            
            elif request.command == IBCommand.GET_POSITIONS:
                return self._do_get_positions()
            
            elif request.command == IBCommand.GET_QUOTE:
                return self._do_get_quote(request.params.get("symbol"))
            
            elif request.command == IBCommand.PLACE_ORDER:
                return self._do_place_order(request.params)
            
            elif request.command == IBCommand.CANCEL_ORDER:
                return self._do_cancel_order(request.params.get("order_id"))
            
            elif request.command == IBCommand.GET_OPEN_ORDERS:
                return self._do_get_open_orders()
            
            elif request.command == IBCommand.GET_EXECUTIONS:
                return self._do_get_executions()
            
            elif request.command == IBCommand.GET_HISTORICAL_DATA:
                return self._do_get_historical_data(request.params)
            
            else:
                return IBResponse(success=False, error=f"Unknown command: {request.command}")
                
        except Exception as e:
            logger.error(f"Error processing {request.command}: {e}")
            return IBResponse(success=False, error=str(e))
    
    def _do_connect(self) -> IBResponse:
        """Connect to IB Gateway"""
        try:
            from ib_insync import IB, util
            
            if self.ib and self.ib.isConnected():
                return IBResponse(success=True, data={"message": "Already connected"})
            
            if self.ib is None:
                self.ib = IB()
            
            logger.info(f"Connecting to IB at {IB_HOST}:{IB_PORT} with client ID {IB_CLIENT_ID}")
            
            # Use synchronous connect in this thread
            self.ib.connect(
                host=IB_HOST,
                port=IB_PORT,
                clientId=IB_CLIENT_ID,
                timeout=15
            )
            
            self.is_connected = True
            logger.info(f"Successfully connected to IB Gateway. Account: {IB_ACCOUNT_ID}")
            
            return IBResponse(success=True, data={"message": "Connected successfully"})
            
        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            self.is_connected = False
            return IBResponse(success=False, error=str(e))
    
    def _do_disconnect(self) -> IBResponse:
        """Disconnect from IB Gateway"""
        try:
            if self.ib and self.ib.isConnected():
                self.ib.disconnect()
            self.is_connected = False
            logger.info("Disconnected from IB")
            return IBResponse(success=True)
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_get_account_summary(self) -> IBResponse:
        """Get account summary"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
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
            
            return IBResponse(success=True, data=summary)
            
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_get_positions(self) -> IBResponse:
        """Get all positions"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            positions = []
            for pos in self.ib.positions():
                if pos.account == IB_ACCOUNT_ID or not IB_ACCOUNT_ID:
                    positions.append({
                        "symbol": pos.contract.symbol,
                        "sec_type": pos.contract.secType,
                        "exchange": pos.contract.exchange,
                        "currency": pos.contract.currency,
                        "quantity": float(pos.position),
                        "avg_cost": float(pos.avgCost),
                        "market_value": float(pos.position) * float(pos.avgCost)
                    })
            
            return IBResponse(success=True, data=positions)
            
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_get_quote(self, symbol: str) -> IBResponse:
        """Get quote for a symbol"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import Stock
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            self.ib.qualifyContracts(contract)
            
            ticker = self.ib.reqMktData(contract, "", True, False)
            self.ib.sleep(1)  # Wait for data
            
            if ticker:
                return IBResponse(success=True, data={
                    "symbol": symbol.upper(),
                    "price": ticker.last if ticker.last else ticker.close,
                    "bid": ticker.bid if ticker.bid else 0,
                    "ask": ticker.ask if ticker.ask else 0,
                    "volume": ticker.volume if ticker.volume else 0,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
            return IBResponse(success=False, error="No data received")
            
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_place_order(self, params: Dict) -> IBResponse:
        """Place an order"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import Stock, MarketOrder, LimitOrder, StopOrder, StopLimitOrder
            
            symbol = params.get("symbol")
            action = params.get("action")
            quantity = params.get("quantity")
            order_type = params.get("order_type", "MKT")
            limit_price = params.get("limit_price")
            stop_price = params.get("stop_price")
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            self.ib.qualifyContracts(contract)
            
            # Create order based on type
            if order_type == "MKT":
                order = MarketOrder(action.upper(), quantity)
            elif order_type == "LMT":
                if limit_price is None:
                    return IBResponse(success=False, error="Limit price required")
                order = LimitOrder(action.upper(), quantity, limit_price)
            elif order_type == "STP":
                if stop_price is None:
                    return IBResponse(success=False, error="Stop price required")
                order = StopOrder(action.upper(), quantity, stop_price)
            elif order_type == "STP_LMT":
                if stop_price is None or limit_price is None:
                    return IBResponse(success=False, error="Both stop and limit prices required")
                order = StopLimitOrder(action.upper(), quantity, limit_price, stop_price)
            else:
                return IBResponse(success=False, error=f"Unsupported order type: {order_type}")
            
            # Place the order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for order acknowledgment
            self.ib.sleep(2)
            
            return IBResponse(success=True, data={
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
            })
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return IBResponse(success=False, error=str(e))
    
    def _do_cancel_order(self, order_id: int) -> IBResponse:
        """Cancel an order"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            for trade in self.ib.openTrades():
                if trade.order.orderId == order_id:
                    self.ib.cancelOrder(trade.order)
                    logger.info(f"Cancelled order {order_id}")
                    return IBResponse(success=True)
            return IBResponse(success=False, error="Order not found")
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_get_open_orders(self) -> IBResponse:
        """Get all open orders"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
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
            
            return IBResponse(success=True, data=orders)
            
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_get_executions(self) -> IBResponse:
        """Get today's executions"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
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
            
            return IBResponse(success=True, data=executions)
            
        except Exception as e:
            return IBResponse(success=False, error=str(e))
    
    def _do_get_historical_data(self, params: Dict) -> IBResponse:
        """Get historical data"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import Stock
            
            symbol = params.get("symbol")
            duration = params.get("duration", "1 D")
            bar_size = params.get("bar_size", "5 mins")
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            self.ib.qualifyContracts(contract)
            
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True
            )
            
            return IBResponse(success=True, data=[
                {
                    "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                }
                for bar in bars
            ])
            
        except Exception as e:
            return IBResponse(success=False, error=str(e))


class IBService:
    """
    Interactive Brokers service that communicates with the IB worker thread.
    All methods are async-safe and can be called from FastAPI endpoints.
    """
    
    def __init__(self):
        self._request_queue = queue.Queue()
        self._worker_thread: Optional[IBWorkerThread] = None
        self._lock = threading.Lock()
        
    def _ensure_worker_running(self):
        """Ensure the worker thread is running"""
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = IBWorkerThread(self._request_queue)
                self._worker_thread.start()
                time.sleep(0.5)  # Give the thread time to start
    
    def _send_request(self, command: IBCommand, params: Dict = None, timeout: float = 30.0) -> IBResponse:
        """Send a request to the worker thread and wait for response"""
        self._ensure_worker_running()
        
        response_queue = queue.Queue()
        request = IBRequest(
            command=command,
            params=params or {},
            response_queue=response_queue
        )
        
        self._request_queue.put(request)
        
        try:
            response = response_queue.get(timeout=timeout)
            return response
        except queue.Empty:
            return IBResponse(success=False, error="Timeout waiting for IB response")
    
    def get_connection_status(self) -> Dict:
        """Get current connection status"""
        is_connected = False
        if self._worker_thread and self._worker_thread.is_alive():
            is_connected = self._worker_thread.is_connected
        
        return {
            "connected": is_connected,
            "host": IB_HOST,
            "port": IB_PORT,
            "client_id": IB_CLIENT_ID,
            "account_id": IB_ACCOUNT_ID
        }
    
    async def connect(self) -> bool:
        """Connect to IB Gateway"""
        response = self._send_request(IBCommand.CONNECT, timeout=20.0)
        return response.success
    
    async def disconnect(self):
        """Disconnect from IB Gateway"""
        self._send_request(IBCommand.DISCONNECT)
    
    async def get_account_summary(self) -> Dict:
        """Get account summary"""
        response = self._send_request(IBCommand.GET_ACCOUNT_SUMMARY)
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_positions(self) -> List[Dict]:
        """Get all positions"""
        response = self._send_request(IBCommand.GET_POSITIONS)
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get quote for a symbol"""
        response = self._send_request(IBCommand.GET_QUOTE, {"symbol": symbol})
        if not response.success:
            return None
        return response.data
    
    async def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> Optional[Dict]:
        """Place an order"""
        response = self._send_request(
            IBCommand.PLACE_ORDER,
            {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "order_type": order_type,
                "limit_price": limit_price,
                "stop_price": stop_price
            },
            timeout=30.0
        )
        if not response.success:
            raise Exception(response.error)
        return response.data
    
    async def cancel_order(self, order_id: int) -> bool:
        """Cancel an order"""
        response = self._send_request(IBCommand.CANCEL_ORDER, {"order_id": order_id})
        return response.success
    
    async def get_open_orders(self) -> List[Dict]:
        """Get open orders"""
        response = self._send_request(IBCommand.GET_OPEN_ORDERS)
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_executions(self) -> List[Dict]:
        """Get today's executions"""
        response = self._send_request(IBCommand.GET_EXECUTIONS)
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_historical_data(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "5 mins"
    ) -> List[Dict]:
        """Get historical data"""
        response = self._send_request(
            IBCommand.GET_HISTORICAL_DATA,
            {"symbol": symbol, "duration": duration, "bar_size": bar_size}
        )
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    def shutdown(self):
        """Shutdown the worker thread"""
        if self._worker_thread and self._worker_thread.is_alive():
            self._send_request(IBCommand.SHUTDOWN)
            self._worker_thread.join(timeout=5.0)


# Singleton instance
_ib_service: Optional[IBService] = None


def get_ib_service() -> IBService:
    """Get or create the IB service singleton"""
    global _ib_service
    if _ib_service is None:
        _ib_service = IBService()
    return _ib_service
