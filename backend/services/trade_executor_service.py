"""
Trade Executor Service
Handles order execution via Alpaca (paper trading) and Interactive Brokers (live trading).
Manages order placement, monitoring, and cancellation.
"""
import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Alpaca configuration
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


class ExecutorMode(str, Enum):
    PAPER = "paper"    # Alpaca paper trading
    LIVE = "live"      # Interactive Brokers live trading
    SIMULATED = "simulated"  # No actual orders, just simulate


class TradeExecutorService:
    """
    Handles order execution and management.
    Supports paper trading via Alpaca and live trading via IB.
    """
    
    def __init__(self):
        self._mode = ExecutorMode.PAPER
        self._alpaca_client = None
        self._ib_client = None
        self._initialized = False
        
        logger.info("TradeExecutorService initialized")
    
    def _ensure_initialized(self) -> bool:
        """Initialize broker clients"""
        if self._initialized:
            return True
        
        try:
            if self._mode == ExecutorMode.PAPER:
                self._init_alpaca()
            elif self._mode == ExecutorMode.LIVE:
                self._init_ib()
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize executor: {e}")
            return False
    
    def _init_alpaca(self):
        """Initialize Alpaca trading client"""
        if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
            raise ValueError("Alpaca API credentials not configured")
        
        from alpaca.trading.client import TradingClient
        
        self._alpaca_client = TradingClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            paper=True  # Always use paper for safety
        )
        
        logger.info("Alpaca trading client initialized (paper mode)")
    
    def _init_ib(self):
        """Initialize Interactive Brokers client"""
        # TODO: Implement IB integration for live trading
        logger.warning("IB live trading not yet implemented")
        raise NotImplementedError("IB live trading coming soon")
    
    def set_mode(self, mode: ExecutorMode):
        """Set execution mode"""
        self._mode = mode
        self._initialized = False
        logger.info(f"Executor mode set to: {mode.value}")
    
    def get_mode(self) -> ExecutorMode:
        return self._mode
    
    # ==================== ORDER EXECUTION ====================
    
    async def execute_entry(self, trade) -> Dict[str, Any]:
        """
        Execute entry order for a trade.
        Returns dict with success, order_id, fill_price, etc.
        """
        if self._mode == ExecutorMode.SIMULATED:
            return await self._simulate_entry(trade)
        
        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}
        
        try:
            if self._mode == ExecutorMode.PAPER:
                return await self._alpaca_entry(trade)
            else:
                return await self._ib_entry(trade)
                
        except Exception as e:
            logger.error(f"Entry execution error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _alpaca_entry(self, trade) -> Dict[str, Any]:
        """Execute entry via Alpaca"""
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        try:
            side = OrderSide.BUY if trade.direction.value == "long" else OrderSide.SELL
            
            # Use market order for immediate execution
            order_request = MarketOrderRequest(
                symbol=trade.symbol,
                qty=trade.shares,
                side=side,
                time_in_force=TimeInForce.DAY
            )
            
            # Submit order
            order = await asyncio.to_thread(
                lambda: self._alpaca_client.submit_order(order_request)
            )
            
            # Wait for fill (with timeout)
            filled_order = await self._wait_for_fill(order.id, timeout=30)
            
            if filled_order and filled_order.filled_avg_price:
                return {
                    "success": True,
                    "order_id": str(order.id),
                    "fill_price": float(filled_order.filled_avg_price),
                    "filled_qty": int(filled_order.filled_qty or trade.shares),
                    "status": str(filled_order.status)
                }
            else:
                return {
                    "success": True,
                    "order_id": str(order.id),
                    "fill_price": trade.entry_price,  # Use expected price if not yet filled
                    "filled_qty": trade.shares,
                    "status": "submitted"
                }
                
        except Exception as e:
            logger.error(f"Alpaca entry error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _wait_for_fill(self, order_id: str, timeout: int = 30):
        """Wait for order to fill with timeout"""
        from alpaca.trading.enums import OrderStatus
        
        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < timeout:
            try:
                order = await asyncio.to_thread(
                    lambda: self._alpaca_client.get_order_by_id(order_id)
                )
                
                if order.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]:
                    return order
                elif order.status in [OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED]:
                    logger.warning(f"Order {order_id} failed: {order.status}")
                    return None
                    
            except Exception as e:
                logger.error(f"Error checking order status: {e}")
            
            await asyncio.sleep(1)
        
        logger.warning(f"Order {order_id} timed out waiting for fill")
        return None
    
    async def _simulate_entry(self, trade) -> Dict[str, Any]:
        """Simulate order execution without actually placing orders"""
        await asyncio.sleep(0.5)  # Simulate latency
        return {
            "success": True,
            "order_id": f"SIM-{trade.id}",
            "fill_price": trade.entry_price,
            "filled_qty": trade.shares,
            "status": "filled",
            "simulated": True
        }
    
    async def _ib_entry(self, trade) -> Dict[str, Any]:
        """Execute entry via Interactive Brokers"""
        # TODO: Implement IB order execution
        return {"success": False, "error": "IB not implemented"}
    
    # ==================== STOP ORDERS ====================
    
    async def place_stop_order(self, trade) -> Dict[str, Any]:
        """Place stop loss order for an open position"""
        if self._mode == ExecutorMode.SIMULATED:
            return await self._simulate_stop(trade)
        
        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}
        
        try:
            if self._mode == ExecutorMode.PAPER:
                return await self._alpaca_stop(trade)
            else:
                return await self._ib_stop(trade)
                
        except Exception as e:
            logger.error(f"Stop order error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _alpaca_stop(self, trade) -> Dict[str, Any]:
        """Place stop order via Alpaca"""
        from alpaca.trading.requests import StopOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        
        try:
            # Stop order is opposite side to close position
            side = OrderSide.SELL if trade.direction.value == "long" else OrderSide.BUY
            
            # Round stop price to 2 decimal places (Alpaca requirement)
            stop_price = round(trade.stop_price, 2)
            
            order_request = StopOrderRequest(
                symbol=trade.symbol,
                qty=trade.shares,
                side=side,
                stop_price=stop_price,
                time_in_force=TimeInForce.GTC  # Good till cancelled
            )
                side=side,
                stop_price=trade.stop_price,
                time_in_force=TimeInForce.GTC  # Good till cancelled
            )
            
            order = await asyncio.to_thread(
                lambda: self._alpaca_client.submit_order(order_request)
            )
            
            return {
                "success": True,
                "order_id": str(order.id),
                "stop_price": trade.stop_price
            }
            
        except Exception as e:
            logger.error(f"Alpaca stop order error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _simulate_stop(self, trade) -> Dict[str, Any]:
        """Simulate stop order"""
        return {
            "success": True,
            "order_id": f"SIM-STOP-{trade.id}",
            "stop_price": trade.stop_price,
            "simulated": True
        }
    
    async def _ib_stop(self, trade) -> Dict[str, Any]:
        """Place stop via IB"""
        return {"success": False, "error": "IB not implemented"}
    
    # ==================== TARGET ORDERS ====================
    
    async def place_target_order(self, trade, target_price: float, shares: int) -> Dict[str, Any]:
        """Place limit order at target price"""
        if self._mode == ExecutorMode.SIMULATED:
            return {
                "success": True,
                "order_id": f"SIM-TGT-{trade.id}",
                "target_price": target_price,
                "simulated": True
            }
        
        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}
        
        try:
            if self._mode == ExecutorMode.PAPER:
                from alpaca.trading.requests import LimitOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                
                side = OrderSide.SELL if trade.direction.value == "long" else OrderSide.BUY
                
                order_request = LimitOrderRequest(
                    symbol=trade.symbol,
                    qty=shares,
                    side=side,
                    limit_price=target_price,
                    time_in_force=TimeInForce.GTC
                )
                
                order = await asyncio.to_thread(
                    lambda: self._alpaca_client.submit_order(order_request)
                )
                
                return {
                    "success": True,
                    "order_id": str(order.id),
                    "target_price": target_price
                }
                
        except Exception as e:
            logger.error(f"Target order error: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== CLOSE POSITION ====================
    
    async def close_position(self, trade) -> Dict[str, Any]:
        """Close an open position immediately"""
        if self._mode == ExecutorMode.SIMULATED:
            return {
                "success": True,
                "order_id": f"SIM-CLOSE-{trade.id}",
                "fill_price": trade.current_price,
                "simulated": True
            }
        
        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}
        
        try:
            if self._mode == ExecutorMode.PAPER:
                # Cancel any open orders first
                await self._cancel_related_orders(trade)
                
                # Submit market order to close
                from alpaca.trading.requests import MarketOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                
                side = OrderSide.SELL if trade.direction.value == "long" else OrderSide.BUY
                
                order_request = MarketOrderRequest(
                    symbol=trade.symbol,
                    qty=trade.shares,
                    side=side,
                    time_in_force=TimeInForce.DAY
                )
                
                order = await asyncio.to_thread(
                    lambda: self._alpaca_client.submit_order(order_request)
                )
                
                # Wait for fill
                filled_order = await self._wait_for_fill(order.id, timeout=30)
                
                fill_price = float(filled_order.filled_avg_price) if filled_order and filled_order.filled_avg_price else trade.current_price
                
                return {
                    "success": True,
                    "order_id": str(order.id),
                    "fill_price": fill_price
                }
                
        except Exception as e:
            logger.error(f"Close position error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _cancel_related_orders(self, trade):
        """Cancel stop and target orders for a trade"""
        if not self._alpaca_client:
            return
        
        try:
            # Cancel stop order
            if trade.stop_order_id:
                await asyncio.to_thread(
                    lambda: self._alpaca_client.cancel_order_by_id(trade.stop_order_id)
                )
            
            # Cancel target orders
            for order_id in trade.target_order_ids:
                try:
                    await asyncio.to_thread(
                        lambda: self._alpaca_client.cancel_order_by_id(order_id)
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.warning(f"Error cancelling related orders: {e}")
    
    # ==================== ACCOUNT INFO ====================
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get current account information"""
        if self._mode == ExecutorMode.SIMULATED:
            return {
                "buying_power": 1000000,
                "cash": 1000000,
                "equity": 1000000,
                "positions": [],
                "simulated": True
            }
        
        if not self._ensure_initialized():
            return {}
        
        try:
            if self._mode == ExecutorMode.PAPER:
                account = await asyncio.to_thread(
                    lambda: self._alpaca_client.get_account()
                )
                
                return {
                    "buying_power": float(account.buying_power),
                    "cash": float(account.cash),
                    "equity": float(account.equity),
                    "portfolio_value": float(account.portfolio_value),
                    "currency": account.currency
                }
                
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return {}
    
    async def get_positions(self) -> list:
        """Get current positions from broker"""
        if self._mode == ExecutorMode.SIMULATED:
            return []
        
        if not self._ensure_initialized():
            return []
        
        try:
            if self._mode == ExecutorMode.PAPER:
                positions = await asyncio.to_thread(
                    lambda: self._alpaca_client.get_all_positions()
                )
                
                return [
                    {
                        "symbol": p.symbol,
                        "qty": int(p.qty),
                        "side": "long" if int(p.qty) > 0 else "short",
                        "avg_entry_price": float(p.avg_entry_price),
                        "current_price": float(p.current_price),
                        "unrealized_pnl": float(p.unrealized_pl),
                        "unrealized_pnl_pct": float(p.unrealized_plpc) * 100
                    }
                    for p in positions
                ]
                
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []


# Singleton instance
_trade_executor: Optional[TradeExecutorService] = None


def get_trade_executor() -> TradeExecutorService:
    """Get or create the trade executor singleton"""
    global _trade_executor
    if _trade_executor is None:
        _trade_executor = TradeExecutorService()
    return _trade_executor
