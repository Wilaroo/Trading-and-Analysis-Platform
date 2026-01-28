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
    GET_STATUS = "get_status"
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
    GET_NEWS = "get_news"
    GET_NEWS_ARTICLE = "get_news_article"
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
        
        logger.info(f"IB Worker Thread started (thread id: {threading.get_ident()})")
        
        last_heartbeat = time.time()
        last_keepalive = time.time()
        heartbeat_interval = 3  # seconds - process event loop frequently
        keepalive_interval = 30  # seconds - request account info to keep connection active
        reconnect_attempts = 0
        max_reconnect_attempts = 3
        
        while self._running:
            try:
                # Wait for a request with timeout to allow checking _running flag
                try:
                    request: IBRequest = self.request_queue.get(timeout=0.5)
                    # Process the request
                    response = self._process_request(request)
                    
                    # Send response back if response queue provided
                    if request.response_queue:
                        request.response_queue.put(response)
                except queue.Empty:
                    pass
                
                # Periodic heartbeat to process IB's event loop (every 3 seconds)
                if self.ib and self.is_connected and time.time() - last_heartbeat > heartbeat_interval:
                    try:
                        # ib.sleep() processes IB's event loop - critical for keeping connection alive
                        self.ib.sleep(0.1)
                        last_heartbeat = time.time()
                    except Exception as e:
                        logger.warning(f"Heartbeat sleep error: {e}")
                
                # Periodic keep-alive request (every 30 seconds) - actually request data to prove connection works
                if self.ib and self.is_connected and time.time() - last_keepalive > keepalive_interval:
                    try:
                        # Request current time from IB server - lightweight keep-alive
                        server_time = self.ib.reqCurrentTime()
                        actual_connected = self.ib.isConnected()
                        
                        if actual_connected and server_time:
                            logger.debug(f"IB keep-alive OK: server_time={server_time}, connected={actual_connected}")
                            reconnect_attempts = 0  # Reset reconnect counter on successful keep-alive
                        elif not actual_connected:
                            logger.warning(f"IB keep-alive: connection lost, attempting reconnect...")
                            self.is_connected = False
                            
                            # Attempt auto-reconnect
                            if reconnect_attempts < max_reconnect_attempts:
                                reconnect_attempts += 1
                                logger.info(f"Auto-reconnect attempt {reconnect_attempts}/{max_reconnect_attempts}")
                                try:
                                    self.ib.disconnect()
                                    time.sleep(1)
                                    self.ib.connect(
                                        host=IB_HOST,
                                        port=IB_PORT,
                                        clientId=IB_CLIENT_ID,
                                        timeout=15
                                    )
                                    if self.ib.isConnected():
                                        self.is_connected = True
                                        logger.info("Auto-reconnect successful!")
                                        reconnect_attempts = 0
                                except Exception as reconnect_err:
                                    logger.error(f"Auto-reconnect failed: {reconnect_err}")
                        
                        last_keepalive = time.time()
                    except Exception as e:
                        logger.warning(f"Keep-alive error: {e}")
                        # Don't immediately mark as disconnected - let the next keep-alive verify
                        last_keepalive = time.time()
                    
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
            
            elif request.command == IBCommand.GET_STATUS:
                return self._do_get_status()
            
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
            
            elif request.command == IBCommand.RUN_SCANNER:
                return self._do_run_scanner(request.params)
            
            elif request.command == IBCommand.GET_QUOTES_BATCH:
                return self._do_get_quotes_batch(request.params.get("symbols", []))
            
            elif request.command == IBCommand.GET_FUNDAMENTALS:
                return self._do_get_fundamentals(request.params.get("symbol"))
            
            elif request.command == IBCommand.GET_NEWS:
                return self._do_get_news(request.params.get("symbol"))
            
            elif request.command == IBCommand.GET_NEWS_ARTICLE:
                return self._do_get_news_article(request.params.get("article_id"))
            
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
                logger.info("Already connected to IB, returning success")
                self.is_connected = True  # Ensure flag is set
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
            logger.info(f"Successfully connected to IB Gateway. Account: {IB_ACCOUNT_ID}, is_connected flag set to True")
            
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
    
    def _do_get_status(self) -> IBResponse:
        """Get connection status from within the worker thread"""
        try:
            connected = False
            if self.ib is not None:
                connected = self.ib.isConnected()
                self.is_connected = connected  # Keep flag in sync
                logger.debug(f"IB status check: ib.isConnected()={connected}, flag={self.is_connected}")
            else:
                connected = False
                self.is_connected = False
                logger.debug("IB status check: ib object is None")
            
            return IBResponse(success=True, data={"connected": connected})
        except Exception as e:
            logger.error(f"Error checking IB status: {e}")
            self.is_connected = False
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
            from ib_insync import Stock, Index
            
            # Handle VIX and other indices differently
            symbol_upper = symbol.upper()
            if symbol_upper in ["VIX", "VXX", "VIXM"]:
                # VIX is an index on CBOE
                contract = Index("VIX", "CBOE")
            else:
                contract = Stock(symbol_upper, "SMART", "USD")
            
            self.ib.qualifyContracts(contract)
            
            ticker = self.ib.reqMktData(contract, "", True, False)
            self.ib.sleep(1)  # Wait for data
            
            if ticker:
                return IBResponse(success=True, data={
                    "symbol": symbol_upper,
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
    
    def _do_run_scanner(self, params: Dict) -> IBResponse:
        """Run IB market scanner"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import ScannerSubscription
            
            scan_type = params.get("scan_type", "TOP_PERC_GAIN")
            instrument = params.get("instrument", "STK")
            location = params.get("location", "STK.US.MAJOR")
            max_results = params.get("max_results", 50)
            
            logger.info(f"Running scanner: {scan_type}, location: {location}, max: {max_results}")
            
            # Create scanner subscription with relaxed filters
            sub = ScannerSubscription(
                instrument=instrument,
                locationCode=location,
                scanCode=scan_type,
                numberOfRows=max_results,
                abovePrice=1.0,  # Relaxed from 5.0
                belowPrice=10000.0,
                aboveVolume=50000,  # Relaxed from 100000
            )
            
            # Run the scan
            scan_results = self.ib.reqScannerData(sub)
            
            logger.info(f"Scanner returned {len(scan_results) if scan_results else 0} results")
            
            if not scan_results:
                logger.warning("Scanner returned no results")
                return IBResponse(success=True, data=[])
            
            results = []
            for item in scan_results:
                try:
                    contract = item.contractDetails.contract
                    results.append({
                        "symbol": contract.symbol,
                        "sec_type": contract.secType,
                        "exchange": contract.primaryExchange or contract.exchange,
                        "currency": contract.currency,
                        "rank": item.rank,
                        "distance": getattr(item, 'distance', None),
                        "benchmark": getattr(item, 'benchmark', None),
                        "projection": getattr(item, 'projection', None),
                        "legs_str": getattr(item, 'legsStr', None),
                    })
                except Exception as item_err:
                    logger.error(f"Error processing scanner item: {item_err}")
                    continue
            
            logger.info(f"Processed {len(results)} scanner results")
            return IBResponse(success=True, data=results)
            
        except Exception as e:
            logger.error(f"Error running scanner: {e}")
            return IBResponse(success=False, error=str(e))
    
    def _do_get_quotes_batch(self, symbols: List[str]) -> IBResponse:
        """Get quotes for multiple symbols - handles delayed data"""
        if not self.ib or not self.ib.isConnected():
            logger.error("Not connected to IB for batch quotes")
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import Stock
            import math
            
            all_quotes = []
            batch_size = 5
            symbols_to_process = symbols[:30]
            
            logger.info(f"Starting batch quotes for {len(symbols_to_process)} symbols")
            
            for i in range(0, len(symbols_to_process), batch_size):
                batch_symbols = symbols_to_process[i:i + batch_size]
                logger.info(f"Processing batch {i // batch_size + 1}: {batch_symbols}")
                
                for symbol in batch_symbols:
                    try:
                        contract = Stock(symbol.upper(), "SMART", "USD")
                        
                        qualified = self.ib.qualifyContracts(contract)
                        if not qualified:
                            logger.warning(f"Could not qualify contract for {symbol}")
                            # Still add with empty data
                            all_quotes.append({
                                "symbol": symbol.upper(),
                                "price": 0, "bid": 0, "ask": 0, "volume": 0,
                                "change": 0, "change_percent": 0,
                                "high": 0, "low": 0, "open": 0, "prev_close": 0,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
                            continue
                        
                        # Request market data (will get delayed if no real-time subscription)
                        ticker = self.ib.reqMktData(contract, "", True, False)
                        self.ib.sleep(0.5)
                        
                        # Helper to safely get numeric value (handle NaN)
                        def safe_float(val, default=0.0):
                            if val is None:
                                return default
                            try:
                                f = float(val)
                                if math.isnan(f) or math.isinf(f):
                                    return default
                                return f
                            except (ValueError, TypeError):
                                return default
                        
                        def safe_int(val, default=0):
                            if val is None:
                                return default
                            try:
                                f = float(val)
                                if math.isnan(f) or math.isinf(f):
                                    return default
                                return int(f)
                            except (ValueError, TypeError):
                                return default
                        
                        # Extract values safely
                        price = safe_float(ticker.last) or safe_float(ticker.close) or safe_float(ticker.bid)
                        prev_close = safe_float(ticker.close) or price
                        change = (price - prev_close) if price and prev_close else 0
                        change_pct = (change / prev_close * 100) if prev_close and prev_close > 0 else 0
                        
                        quote_data = {
                            "symbol": symbol.upper(),
                            "price": round(price, 2),
                            "bid": round(safe_float(ticker.bid), 2),
                            "ask": round(safe_float(ticker.ask), 2),
                            "volume": safe_int(ticker.volume),
                            "change": round(change, 2),
                            "change_percent": round(change_pct, 2),
                            "high": round(safe_float(ticker.high), 2),
                            "low": round(safe_float(ticker.low), 2),
                            "open": round(safe_float(ticker.open), 2),
                            "prev_close": round(prev_close, 2),
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                        all_quotes.append(quote_data)
                        
                        if price > 0:
                            logger.debug(f"Got quote for {symbol}: ${price}")
                        else:
                            logger.debug(f"Got empty quote for {symbol} (no API subscription)")
                            
                    except Exception as e:
                        logger.error(f"Error getting quote for {symbol}: {e}")
                        # Add empty quote
                        all_quotes.append({
                            "symbol": symbol.upper(),
                            "price": 0, "bid": 0, "ask": 0, "volume": 0,
                            "change": 0, "change_percent": 0,
                            "high": 0, "low": 0, "open": 0, "prev_close": 0,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                
                self.ib.sleep(0.3)
            
            logger.info(f"Batch quotes complete: {len(all_quotes)} quotes")
            return IBResponse(success=True, data=all_quotes)
            
        except Exception as e:
            logger.error(f"Error in batch quotes: {e}")
            import traceback
            traceback.print_exc()
            return IBResponse(success=False, error=str(e))
    
    def _do_get_fundamentals(self, symbol: str) -> IBResponse:
        """Get fundamental data for a symbol"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import Stock
            
            contract = Stock(symbol.upper(), "SMART", "USD")
            self.ib.qualifyContracts(contract)
            
            # Get fundamental data - this returns XML string
            fundamentals = self.ib.reqFundamentalData(contract, "ReportSnapshot")
            
            # Basic parsing of key metrics (IB returns XML)
            data = {
                "symbol": symbol.upper(),
                "raw_data": fundamentals[:1000] if fundamentals else None,  # Truncate for response
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            return IBResponse(success=True, data=data)
            
        except Exception as e:
            logger.error(f"Error getting fundamentals: {e}")
            return IBResponse(success=False, error=str(e))
    
    def _do_get_news(self, symbol: str = None) -> IBResponse:
        """Get news headlines - optionally filtered by symbol"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            from ib_insync import Stock
            
            news_items = []
            
            if symbol:
                # Get news for specific symbol by subscribing to market data
                contract = Stock(symbol.upper(), "SMART", "USD")
                self.ib.qualifyContracts(contract)
                
                # Request market data with news
                ticker = self.ib.reqMktData(contract, "mdoff,258", snapshot=False, regulatorySnapshot=False)
                self.ib.sleep(2)  # Wait for news ticks
                
                # Get news ticks from the ticker
                if hasattr(ticker, 'newsTicks') and ticker.newsTicks:
                    for tick in ticker.newsTicks:
                        news_items.append({
                            "id": f"{symbol}-{tick.timeStamp.timestamp() if hasattr(tick.timeStamp, 'timestamp') else tick.timeStamp}",
                            "symbol": symbol.upper(),
                            "headline": tick.headline if hasattr(tick, 'headline') else str(tick),
                            "source": tick.providerCode if hasattr(tick, 'providerCode') else "IB",
                            "timestamp": tick.timeStamp.isoformat() if hasattr(tick.timeStamp, 'isoformat') else str(tick.timeStamp),
                            "article_id": tick.articleId if hasattr(tick, 'articleId') else None
                        })
                
                # Cancel market data
                self.ib.cancelMktData(contract)
            else:
                # Get general news bulletins
                bulletins = self.ib.newsBulletins()
                for bulletin in bulletins:
                    news_items.append({
                        "id": str(bulletin.msgId) if hasattr(bulletin, 'msgId') else str(len(news_items)),
                        "headline": bulletin.message if hasattr(bulletin, 'message') else str(bulletin),
                        "source": "IB Bulletin",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "type": bulletin.msgType if hasattr(bulletin, 'msgType') else "news"
                    })
            
            return IBResponse(success=True, data=news_items)
            
        except Exception as e:
            logger.error(f"Error getting news: {e}")
            return IBResponse(success=False, error=str(e))
    
    def _do_get_news_article(self, article_id: str) -> IBResponse:
        """Get full news article content"""
        if not self.ib or not self.ib.isConnected():
            return IBResponse(success=False, error="Not connected to IB")
        
        try:
            # IB requires provider code and article ID
            # This is a simplified implementation
            return IBResponse(success=True, data={
                "article_id": article_id,
                "content": "Full article content requires IB news subscription",
                "note": "Use the headline link to read the full article"
            })
            
        except Exception as e:
            logger.error(f"Error getting news article: {e}")
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
        self._busy = False  # Flag to indicate heavy operation in progress
        self._busy_operation = None  # Name of the busy operation
        self._busy_lock = threading.Lock()  # Thread-safe access to busy flag
        self._instance_id = id(self)  # For debugging singleton integrity
        logger.info(f"IBService instance created: id={self._instance_id}")
        
    def _ensure_worker_running(self):
        """Ensure the worker thread is running"""
        with self._lock:
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = IBWorkerThread(self._request_queue)
                self._worker_thread.start()
                time.sleep(0.5)  # Give the thread time to start
    
    def is_busy(self) -> tuple:
        """Check if a heavy operation is in progress (thread-safe)"""
        with self._busy_lock:
            return self._busy, self._busy_operation
    
    def set_busy(self, busy: bool, operation: str = None):
        """Set the busy flag (thread-safe)"""
        with self._busy_lock:
            self._busy = busy
            self._busy_operation = operation if busy else None
            logger.info(f"IBService busy flag set: busy={busy}, operation={operation}, instance={self._instance_id}")
    
    def wait_if_busy(self, timeout: float = 30.0) -> bool:
        """
        Wait for the service to become available if currently busy.
        Returns True if service is available, False if timeout.
        Used by lower-priority operations to wait for heavy operations to complete.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._busy_lock:
                if not self._busy:
                    return True
            time.sleep(0.5)
        return False
    
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
        """Get current connection status - fast path using flag"""
        is_connected = False
        
        # Use the flag directly for fast response (don't queue a command)
        # The flag is kept in sync by the heartbeat and other operations
        if self._worker_thread and self._worker_thread.is_alive():
            is_connected = self._worker_thread.is_connected
            logger.debug(f"get_connection_status: using flag, connected={is_connected}")
        else:
            logger.debug("get_connection_status: worker thread not alive")
        
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
    
    async def run_scanner(
        self,
        scan_type: str = "TOP_PERC_GAIN",
        instrument: str = "STK",
        location: str = "STK.US.MAJOR",
        max_results: int = 50
    ) -> List[Dict]:
        """Run IB market scanner
        
        Scan types include:
        - TOP_PERC_GAIN: Top % gainers
        - TOP_PERC_LOSE: Top % losers
        - MOST_ACTIVE: Most active by volume
        - HOT_BY_VOLUME: Hot by volume
        - HIGH_OPEN_GAP: High opening gap
        - LOW_OPEN_GAP: Low opening gap
        - GAP_UP: Gap up stocks
        - GAP_DOWN: Gap down stocks
        - TOP_TRADE_COUNT: Most trades
        - HIGH_VS_13W_HL: Near 13-week high
        - LOW_VS_13W_HL: Near 13-week low
        - HIGH_VS_52W_HL: Near 52-week high
        - LOW_VS_52W_HL: Near 52-week low
        """
        response = self._send_request(
            IBCommand.RUN_SCANNER,
            {
                "scan_type": scan_type,
                "instrument": instrument,
                "location": location,
                "max_results": max_results
            },
            timeout=60.0
        )
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_quotes_batch(self, symbols: List[str]) -> List[Dict]:
        """Get quotes for multiple symbols"""
        response = self._send_request(
            IBCommand.GET_QUOTES_BATCH,
            {"symbols": symbols},
            timeout=90.0  # Increased timeout for batch processing
        )
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_fundamentals(self, symbol: str) -> Dict:
        """Get fundamental data for a symbol"""
        response = self._send_request(
            IBCommand.GET_FUNDAMENTALS,
            {"symbol": symbol},
            timeout=30.0
        )
        if not response.success:
            raise ConnectionError(response.error)
        return response.data
    
    async def get_news_for_symbol(self, symbol: str) -> List[Dict]:
        """Get news headlines for a specific symbol"""
        response = self._send_request(
            IBCommand.GET_NEWS,
            {"symbol": symbol},
            timeout=15.0
        )
        if not response.success:
            return []  # Return empty list on failure
        return response.data or []
    
    async def get_general_news(self) -> List[Dict]:
        """Get general market news"""
        response = self._send_request(
            IBCommand.GET_NEWS,
            {"symbol": None},
            timeout=15.0
        )
        if not response.success:
            return []
        return response.data or []
    
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
