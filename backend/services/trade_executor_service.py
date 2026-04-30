"""
Trade Executor Service
Handles order execution via Interactive Brokers (primary) and Alpaca (fallback).
Manages order placement, monitoring, and cancellation.

Architecture:
- IB Gateway: Primary broker (user's local paper account DUN615665)
- Alpaca: Fallback broker (paper trading)
- Simulated: Development/testing mode

Note: Since IB Gateway runs locally and the cloud can't directly connect,
orders are currently simulated in the cloud. The trading bot uses live IB data
for decisions but actual order execution requires the local IB connection.
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
    Default: IB Gateway (user's paper account DUN615665)
    """
    
    def __init__(self):
        # Default to IB Gateway (LIVE mode connects to IB)
        self._mode = ExecutorMode.LIVE
        self._alpaca_client = None
        self._ib_client = None
        self._initialized = False
        
        logger.info("TradeExecutorService initialized (default: IB Gateway)")
    
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
        """Initialize Alpaca trading client.

        DEPRECATED: Alpaca has been removed from the trading path. If mode is
        set to PAPER (Alpaca), we raise loudly so the user notices instead of
        silently routing orders to a different broker. Use ExecutorMode.LIVE
        (IB Gateway paper/live account) instead.
        """
        raise RuntimeError(
            "Alpaca execution path is disabled. Use ExecutorMode.LIVE (IB) — "
            "IB Gateway supports both paper and live trading via the configured "
            "account (e.g. DUN615665 for paper)."
        )
    
    def _init_ib(self):
        """
        Initialize Interactive Brokers client.
        
        IB Gateway runs locally on user's machine. The cloud backend
        communicates via the pusher/order-queue system.
        When pusher is connected, orders are routed through the queue
        to the local IB Gateway for real execution (paper account).
        """
        try:
            import routers.ib as ib_module
            if ib_module.is_pusher_connected():
                logger.info("IB pusher connected - LIVE order routing via order queue enabled")
                logger.info("Orders will be queued and executed by local IB Gateway (paper account)")
                # Keep LIVE mode — orders go through the queue to the local IB Gateway
                self._mode = ExecutorMode.LIVE
            else:
                # Try direct IB connection (only works if running locally)
                try:
                    from services.ib_service import get_ib_service
                    self._ib_client = get_ib_service()
                    logger.info("IB trading client initialized via direct IB Service")
                except Exception:
                    # No pusher and no direct connection — simulate
                    self._mode = ExecutorMode.SIMULATED
                    logger.info("No IB connection available - using SIMULATED mode for orders")
        except Exception as e:
            logger.warning(f"IB initialization: {e}")
            self._mode = ExecutorMode.SIMULATED
            logger.info("Using SIMULATED mode for orders")
    
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
        """
        Execute entry via Interactive Brokers with SMART routing.
        
        Order type selection:
        - Scalp setups (< 5min timeframe): IOC LIMIT at ask + buffer
        - Intraday setups: DAY LIMIT at ask + buffer  
        - Swing/position: DAY LIMIT at ask + wider buffer
        
        All orders use IB SMART routing for best execution.
        """
        try:
            from routers.ib import queue_order, get_order_result, is_pusher_connected
            
            if not is_pusher_connected():
                logger.warning("IB pusher not connected - falling back to simulation")
                return await self._simulate_entry(trade)
            
            action = "BUY" if trade.direction.value == "long" else "SELL"
            
            # Determine order type based on setup
            setup_type = getattr(trade, 'setup_type', '').lower() if hasattr(trade, 'setup_type') else ''
            scalp_setups = {'scalp', 'nine_ema_scalp', 'spencer_scalp', 'abc_scalp'}
            is_scalp = any(s in setup_type for s in scalp_setups)
            
            # Calculate limit price with buffer
            entry_price = trade.entry_price
            if entry_price and entry_price > 0:
                if is_scalp:
                    # Tight buffer for scalps — 0.02% above ask
                    buffer = max(entry_price * 0.0002, 0.01)
                    order_type = "LMT"
                    time_in_force = "IOC"  # Immediate or Cancel for scalps
                else:
                    # Standard buffer — 0.05% above ask
                    buffer = max(entry_price * 0.0005, 0.01)
                    order_type = "LMT"
                    time_in_force = "DAY"
                
                if action == "BUY":
                    limit_price = round(entry_price + buffer, 2)
                else:
                    limit_price = round(entry_price - buffer, 2)
            else:
                # Fallback to market order if no price
                order_type = "MKT"
                limit_price = None
                time_in_force = "DAY"
            
            order_id = queue_order({
                "symbol": trade.symbol,
                "action": action,
                "quantity": trade.shares,
                "order_type": order_type,
                "limit_price": limit_price,
                "stop_price": None,
                "time_in_force": time_in_force,
                "exchange": "SMART",
                "trade_id": trade.id
            })
            
            logger.info(f"Order queued for IB: {order_id} - {action} {trade.shares} {trade.symbol} @ {order_type} {limit_price or 'MKT'} ({time_in_force}, SMART)")
            
            # Wait for execution result
            timeout = 10.0 if is_scalp else 60.0
            result = await asyncio.to_thread(get_order_result, order_id, timeout)
            
            if result:
                order_result = result.get("result", {})
                status = order_result.get("status", "unknown")
                
                if status == "filled":
                    return {
                        "success": True,
                        "order_id": order_id,
                        "ib_order_id": order_result.get("ib_order_id"),
                        "fill_price": order_result.get("fill_price", trade.entry_price),
                        "filled_qty": order_result.get("filled_qty", trade.shares),
                        "status": "filled",
                        "broker": "interactive_brokers",
                        "order_type": order_type,
                        "routing": "SMART"
                    }
                elif status == "partial":
                    return {
                        "success": True,
                        "order_id": order_id,
                        "fill_price": order_result.get("fill_price", trade.entry_price),
                        "filled_qty": order_result.get("filled_qty", 0),
                        "remaining_qty": order_result.get("remaining_qty", 0),
                        "status": "partial",
                        "broker": "interactive_brokers",
                        "order_type": order_type
                    }
                else:
                    return {
                        "success": False,
                        "error": order_result.get("error", f"Order {status}"),
                        "order_id": order_id,
                        "status": status
                    }
            else:
                logger.warning(f"Timeout waiting for order {order_id} - may still execute")
                return {
                    "success": False,
                    "error": "Timeout waiting for order execution",
                    "order_id": order_id,
                    "status": "timeout"
                }
                
        except Exception as e:
            logger.error(f"IB order execution error: {e}")
            return {"success": False, "error": str(e)}
    
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
            
            order = await asyncio.to_thread(
                lambda: self._alpaca_client.submit_order(order_request)
            )
            
            return {
                "success": True,
                "order_id": str(order.id),
                "stop_price": stop_price
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
        """Place stop via IB using order queue"""
        try:
            from routers.ib import queue_order, get_order_result, is_pusher_connected
            
            if not is_pusher_connected():
                logger.warning("IB pusher not connected - simulating stop order")
                return await self._simulate_stop(trade)
            
            # Stop order is opposite side
            action = "SELL" if trade.direction.value == "long" else "BUY"
            
            order_id = queue_order({
                "symbol": trade.symbol,
                "action": action,
                "quantity": trade.shares,
                "order_type": "STP",
                "limit_price": None,
                "stop_price": trade.stop_price,
                "time_in_force": "GTC",
                "trade_id": f"STOP-{trade.id}"
            })
            
            logger.info(f"Stop order queued: {order_id} - {action} {trade.shares} {trade.symbol} @ ${trade.stop_price}")
            
            # Don't wait for stop orders to fill - they stay open
            return {
                "success": True,
                "order_id": order_id,
                "stop_price": trade.stop_price,
                "broker": "interactive_brokers"
            }
            
        except Exception as e:
            logger.error(f"IB stop order error: {e}")
            return {"success": False, "error": str(e)}

    # ==================== BRACKET ORDERS (Phase 3 — 2026-04-22) ====================

    async def place_bracket_order(self, trade) -> Dict[str, Any]:
        """Place an atomic IB bracket order (parent + OCA stop + OCA target).

        Replaces the sequential entry→stop flow that left positions naked
        during bot restarts. Entry, stop, and target are submitted to IB as
        a single atomic batch (parent transmit=False, stop transmit=False,
        target transmit=True → IB activates all three together). Once parent
        fills, stop+target live at IB as GTC — they survive bot crashes,
        pusher disconnects, and even extended offline periods.

        See `/app/memory/IB_BRACKET_ORDER_MIGRATION.md` for the full spec and
        `/app/memory/PUSHER_BRACKET_SPEC.md` for the pusher contract.

        Returns:
            dict with success, entry_order_id, stop_order_id, target_order_id,
            oca_group, fill info (if parent filled during wait window).

        Falls back to legacy two-step flow if the pusher doesn't support
        bracket payloads yet (during migration window).
        """
        if self._mode == ExecutorMode.SIMULATED:
            return await self._simulate_bracket(trade)

        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}

        try:
            if self._mode == ExecutorMode.PAPER:
                # Alpaca bracket not implemented yet — fall through to legacy entry+stop
                logger.info("Alpaca bracket not wired — using legacy two-step flow")
                return {"success": False, "error": "alpaca_bracket_not_implemented"}
            else:
                return await self._ib_bracket(trade)
        except Exception as e:
            logger.error(f"Bracket order error: {e}")
            return {"success": False, "error": str(e)}

    async def _simulate_bracket(self, trade) -> Dict[str, Any]:
        """Simulated bracket — no broker calls."""
        return {
            "success": True,
            "entry_order_id": f"SIM-ENTRY-{trade.id}",
            "stop_order_id": f"SIM-STOP-{trade.id}",
            "target_order_id": f"SIM-TGT-{trade.id}",
            "oca_group": f"SIM-OCA-{trade.id}",
            "fill_price": trade.entry_price,
            "filled_qty": trade.shares,
            "status": "filled",
            "simulated": True,
        }

    async def _ib_bracket(self, trade) -> Dict[str, Any]:
        """Atomic IB bracket via the Windows pusher's `type=bracket` payload.

        Pusher contract (see PUSHER_BRACKET_SPEC.md):
          Request  : {"type": "bracket", "parent": {...}, "stop": {...}, "target": {...}}
          Response : {"status": "filled"|"working"|"rejected", "entry_order_id",
                     "stop_order_id", "target_order_id", "oca_group", "fill_price", ...}

        If pusher returns `bracket_not_supported`, we fall back to legacy
        entry+stop path so the migration can ship in two halves.
        """
        try:
            from routers.ib import queue_order, get_order_result, is_pusher_connected

            if not is_pusher_connected():
                logger.warning("IB pusher not connected — falling back to simulation")
                return await self._simulate_bracket(trade)

            action = "BUY" if trade.direction.value == "long" else "SELL"
            child_action = "SELL" if action == "BUY" else "BUY"

            # Scalp detection — controls parent TIF and limit offset
            setup_type = (getattr(trade, "setup_type", "") or "").lower()
            is_scalp = any(s in setup_type for s in
                           {"scalp", "nine_ema_scalp", "spencer_scalp", "abc_scalp"})

            # Parent limit price with conservative offset (marketable but not aggressive)
            entry_price = trade.entry_price
            if entry_price and entry_price > 0:
                buffer = max(entry_price * (0.0002 if is_scalp else 0.0005), 0.01)
                limit_price = round(
                    entry_price + buffer if action == "BUY" else entry_price - buffer, 2
                )
            else:
                limit_price = entry_price

            # Target price — use first scale-out target, else 2R default
            target_price = None
            if hasattr(trade, "target_prices") and trade.target_prices:
                target_price = float(trade.target_prices[0])
            elif trade.stop_price and trade.entry_price:
                risk = abs(trade.entry_price - trade.stop_price)
                target_price = round(
                    trade.entry_price + 2 * risk if action == "BUY"
                    else trade.entry_price - 2 * risk, 2
                )

            if target_price is None or trade.stop_price is None:
                return {"success": False,
                        "error": "bracket_missing_stop_or_target", "fallback": "legacy"}

            payload = {
                "type": "bracket",
                "trade_id": trade.id,
                "symbol": trade.symbol,
                "parent": {
                    "action": action,
                    "quantity": trade.shares,
                    "order_type": "LMT",
                    "limit_price": limit_price,
                    "time_in_force": "DAY",
                    "exchange": "SMART",
                },
                "stop": {
                    "action": child_action,
                    "quantity": trade.shares,
                    "order_type": "STP",
                    "stop_price": float(trade.stop_price),
                    "time_in_force": "GTC",
                    "outside_rth": True,
                },
                "target": {
                    "action": child_action,
                    "quantity": trade.shares,
                    "order_type": "LMT",
                    "limit_price": float(target_price),
                    "time_in_force": "GTC",
                    "outside_rth": True,
                },
            }

            order_id = queue_order(payload)
            logger.info(
                f"Bracket queued: {order_id} — {action} {trade.shares} {trade.symbol} "
                f"parent@{limit_price} stop@{trade.stop_price} target@{target_price}"
            )

            # Wait for parent fill confirmation
            timeout = 10.0 if is_scalp else 60.0
            result = await asyncio.to_thread(get_order_result, order_id, timeout)

            if not result:
                logger.warning(f"Bracket timeout for {order_id} — may still execute")
                return {
                    "success": False, "error": "bracket_submission_timeout",
                    "entry_order_id": order_id, "status": "timeout",
                }

            r = result.get("result", {}) or {}

            # Pusher signals it doesn't yet support bracket payload (Phase 2 pending)
            if r.get("error") == "bracket_not_supported" or r.get("status") == "bracket_not_supported":
                logger.warning("Pusher does not support bracket payloads — falling back to legacy entry+stop")
                return {"success": False, "error": "bracket_not_supported", "fallback": "legacy"}

            status = r.get("status", "unknown")
            if status in ("filled", "working", "submitted", "partial"):
                return {
                    "success": True,
                    "entry_order_id": r.get("entry_order_id") or r.get("parent_id") or order_id,
                    "stop_order_id": r.get("stop_order_id") or r.get("stop_id"),
                    "target_order_id": r.get("target_order_id") or r.get("target_id"),
                    "oca_group": r.get("oca_group"),
                    "fill_price": r.get("fill_price", trade.entry_price),
                    "filled_qty": r.get("filled_qty", trade.shares if status == "filled" else 0),
                    "status": status,
                    "broker": "interactive_brokers",
                    "order_type": "bracket",
                }
            return {
                "success": False,
                "error": r.get("error", f"Bracket {status}"),
                "entry_order_id": order_id,
                "status": status,
            }

        except Exception as e:
            logger.error(f"IB bracket execution error: {e}")
            return {"success": False, "error": str(e)}

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

    # ==================== PARTIAL EXIT (SCALE-OUT) ====================
    
    async def execute_partial_exit(self, trade, shares: int) -> Dict[str, Any]:
        """Execute a partial position exit (scale-out at target)"""
        if self._mode == ExecutorMode.SIMULATED:
            return {
                "success": True,
                "order_id": f"SIM-PARTIAL-{trade.id}",
                "fill_price": trade.current_price,
                "shares": shares,
                "simulated": True
            }
        
        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}
        
        try:
            if self._mode == ExecutorMode.PAPER:
                from alpaca.trading.requests import MarketOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                
                # Sell partial position (opposite side)
                side = OrderSide.SELL if trade.direction.value == "long" else OrderSide.BUY
                
                order_request = MarketOrderRequest(
                    symbol=trade.symbol,
                    qty=shares,
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
                    "fill_price": fill_price,
                    "shares": shares
                }
                
        except Exception as e:
            logger.error(f"Partial exit error: {e}")
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
            
            elif self._mode == ExecutorMode.LIVE:
                # Close via IB order queue
                return await self._ib_close_position(trade)
                
        except Exception as e:
            logger.error(f"Close position error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _ib_close_position(self, trade) -> Dict[str, Any]:
        """Close position via IB using order queue.

        2026-04-30 v19.13 — cancels the bracket's stop/target children
        BEFORE submitting the close MKT. Pre-fix, a race could leave
        the local close + the IB bracket child both filling within the
        same tick → double-exit (long → short / short → long). Even if
        the cancel fails for some reason, we still attempt the close —
        the cancel just narrows the race window. If a child filled in
        the milliseconds before our cancel landed, the close will then
        fail at IB with an "insufficient quantity" rejection instead
        of doubling the position.
        """
        try:
            from routers.ib import queue_order, get_order_result, is_pusher_connected

            if not is_pusher_connected():
                logger.warning("IB pusher not connected - simulating close")
                return {
                    "success": True,
                    "order_id": f"SIM-CLOSE-{trade.id}",
                    "fill_price": trade.current_price,
                    "simulated": True
                }

            # v19.13 — cancel bracket children first. Best-effort; we
            # never block the close on cancellation outcome (IB will
            # reject a redundant close if the child already filled).
            await self._cancel_ib_bracket_orders(trade)

            # Close order is opposite side
            action = "SELL" if trade.direction.value == "long" else "BUY"
            
            order_id = queue_order({
                "symbol": trade.symbol,
                "action": action,
                "quantity": trade.shares,
                "order_type": "MKT",
                "limit_price": None,
                "stop_price": None,
                "time_in_force": "DAY",
                "trade_id": f"CLOSE-{trade.id}"
            })
            
            logger.info(f"Close order queued: {order_id} - {action} {trade.shares} {trade.symbol}")
            
            # Wait for execution result in thread (blocking call — don't freeze event loop)
            result = await asyncio.to_thread(get_order_result, order_id, 60.0)
            
            if result:
                order_result = result.get("result", {})
                status = order_result.get("status", "unknown")
                
                if status == "filled":
                    return {
                        "success": True,
                        "order_id": order_id,
                        "fill_price": order_result.get("fill_price", trade.current_price),
                        "broker": "interactive_brokers"
                    }
                else:
                    return {
                        "success": False,
                        "error": order_result.get("error", f"Close order {status}"),
                        "order_id": order_id
                    }
            else:
                return {
                    "success": False,
                    "error": "Timeout waiting for close order execution",
                    "order_id": order_id
                }
                
        except Exception as e:
            logger.error(f"IB close position error: {e}")
            return {"success": False, "error": str(e)}
    
    async def _cancel_ib_bracket_orders(self, trade) -> None:
        """v19.13 — cancel the IB bracket's stop + target children for `trade`.

        Best-effort: failures are logged at WARNING (NOT raised) because
        the caller is about to submit a close MKT regardless — and IB
        will reject duplicate fills, so the worst outcome of a cancel
        miss is a benign IB-side rejection on the close, not a doubled
        position.

        Looks up order IDs from THREE possible places (legacy fields):
          - `trade.stop_order_id`     — set in trade_execution.py:318
          - `trade.target_order_id`   — set in trade_execution.py:319 (singular)
          - `trade.target_order_ids`  — Alpaca legacy list field on the dataclass

        Empty / non-numeric IDs are skipped silently (e.g.,
        `SIM-STOP-<uuid>` from simulated/paper modes).
        """
        try:
            from routers.ib import cancel_order as _ib_cancel_order
        except Exception as e:
            logger.warning(
                f"v19.13: could not import IB cancel_order — skipping bracket "
                f"cancellation for {trade.symbol}: {e}"
            )
            return

        # Collect IDs from all three slots, dedupe, filter to int-castable.
        candidates = []
        for raw in (
            getattr(trade, "stop_order_id", None),
            getattr(trade, "target_order_id", None),
            *(getattr(trade, "target_order_ids", []) or []),
        ):
            if raw is None or raw == "":
                continue
            try:
                candidates.append(int(raw))
            except (TypeError, ValueError):
                # Sim/paper IDs like "SIM-STOP-<uuid>" land here — skip.
                continue

        # Dedupe while preserving order
        seen = set()
        ordered = [c for c in candidates if not (c in seen or seen.add(c))]

        for oid in ordered:
            try:
                # Use the singleton IB service already wired into the
                # app at startup. Avoids HTTP round-trip back through
                # the router for an in-process cancel.
                from routers.ib import _ib_service
                if _ib_service is not None:
                    ok = await _ib_service.cancel_order(oid)
                    if not ok:
                        logger.warning(
                            f"v19.13: IB cancel returned False for order_id={oid} "
                            f"({trade.symbol}) — child may have already filled or "
                            f"been cancelled."
                        )
                else:
                    logger.warning(
                        f"v19.13: IB service unavailable for cancel order_id={oid} "
                        f"({trade.symbol})"
                    )
            except Exception as e:
                logger.warning(
                    f"v19.13: bracket cancel raised for order_id={oid} "
                    f"({trade.symbol}): {type(e).__name__}: {e}"
                )

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
