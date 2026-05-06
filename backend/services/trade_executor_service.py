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
from datetime import datetime
from typing import Dict, Optional, Any
from enum import Enum

from services.bracket_tif import bracket_tif

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

    def _kill_switch_refusal(self, method_name: str, trade) -> Optional[Dict[str, Any]]:
        """v19.34.26 — Executor-layer kill-switch guard.

        Today's incident (2026-02-XX): six bracket entries (UPS, ADBE,
        AMDL, XOP, TSLG, TEAM) fired at IB between 2:45-2:54 PM ET while
        the kill-switch was demonstrably active (`v19_34_25_persistence_test`
        latch set + UI banner visible). Order history confirmed each had
        full OCA brackets attached, meaning they went through
        `place_bracket_order` — but some upstream code path in the bot's
        autonomous flow had skipped `safety_guardrails.check_can_enter()`.

        Fix: every executor entry-creating method calls this helper at
        its very top. Bypass-proof because every order path traverses the
        executor — guarding here catches anything the bot layer missed.
        Returns a refusal dict if the latch is active (caller must early-
        return), else None.

        Defensive: importing/calling guardrails fails open (returns None)
        rather than blocking the executor on a guardrail import error.
        Worst case = same behaviour as pre-v19.34.26.
        """
        try:
            from services.safety_guardrails import get_safety_guardrails
            guard = get_safety_guardrails()
            if guard._kill_switch_active_unsafe():
                symbol = getattr(trade, "symbol", "?") if trade is not None else "?"
                logger.error(
                    "v19.34.26 [EXECUTOR-GUARD] %s REFUSED for %s — "
                    "kill_switch_active=True (reason: %s). Order NOT submitted.",
                    method_name, symbol, guard.state.kill_switch_reason,
                )
                return {
                    "success": False,
                    "error": "kill_switch_active",
                    "reason": guard.state.kill_switch_reason or "kill-switch tripped",
                    "refused_at": "executor_layer",
                    "method": method_name,
                }
        except Exception as e:
            logger.warning("v19.34.26 [EXECUTOR-GUARD] guardrail check failed in %s: %s "
                           "— allowing through (fail-open)", method_name, e)
        return None

    # ── v19.34.27 — Direct IB shadow mode ────────────────────────────
    #
    # `BOT_ORDER_PATH` env var controls the routing:
    #   "pusher"  (default) — orders go through the Windows pusher only.
    #   "shadow"            — pusher remains primary; AFTER the pusher
    #                         confirms, we cross-check the IB-direct
    #                         socket's authoritative positions to detect
    #                         silent-failure scenarios (pusher said
    #                         success, IB doesn't actually have the
    #                         position). Divergences are LOGGED ONLY.
    #   "direct"            — Phase 3 (future). Direct is primary,
    #                         pusher is data-only.
    #
    # In shadow mode we deliberately do NOT submit a parallel order
    # through the direct socket — that would duplicate at the broker.
    # Instead we observe IB's position-snapshot N seconds after the
    # primary submit and warn if it disagrees with what we just
    # ordered. This catches the v19.34.15a "pusher reported filled but
    # IB shows nothing" race fingerprint without risking double-fills.
    _SHADOW_OBSERVE_DELAY_S = 4.0
    _SHADOW_DIVERGENCE_COUNTERS: Dict[str, int] = {
        "missing_at_ib": 0,        # primary said filled, IB shows < expected
        "extra_at_ib": 0,          # primary said filled, IB shows > expected
        "direction_mismatch": 0,   # primary went long, IB shows short (or v.v.)
        "auth_lost": 0,            # IB direct socket up but managedAccounts empty
        "observed_ok": 0,          # primary + IB direct agree
        "skipped_socket_down": 0,  # IB direct socket unreachable
    }

    def _order_path_mode(self) -> str:
        """Return the active BOT_ORDER_PATH ('pusher'|'shadow'|'direct')."""
        v = (os.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower()
        return v if v in ("pusher", "shadow", "direct") else "pusher"

    def _maybe_schedule_shadow_observe(
        self,
        trade,
        primary_result: Dict[str, Any],
        *,
        action: str,                  # "BUY" | "SELL" — primary order action
        intent: str,                  # "bracket" | "close" | "partial_exit" | ...
        expected_signed_delta: int,   # signed share delta the primary intends at IB
    ) -> None:
        """Fire-and-forget shadow observation if BOT_ORDER_PATH=shadow.

        Schedules a coroutine that, after `_SHADOW_OBSERVE_DELAY_S`,
        cross-checks the direct IB socket's positions against what the
        primary said it did. Counters bump on divergence; a single
        WARNING line is logged per observation so the operator can grep
        the log when a pusher silent-failure is suspected.

        NEVER raises into the caller. NEVER waits for the observation
        (would defeat the point of being shadow).
        """
        if self._order_path_mode() != "shadow":
            return
        if not (primary_result and primary_result.get("success")):
            # Primary failed — nothing to compare against.
            return
        try:
            asyncio.create_task(self._shadow_observe(
                symbol=getattr(trade, "symbol", "?"),
                trade_id=getattr(trade, "id", None),
                action=action,
                intent=intent,
                expected_signed_delta=int(expected_signed_delta),
                primary_result=primary_result,
            ))
        except Exception as e:
            logger.debug(f"shadow_observe schedule failed: {e}")

    async def _shadow_observe(
        self,
        *,
        symbol: str,
        trade_id: Optional[str],
        action: str,
        intent: str,
        expected_signed_delta: int,
        primary_result: Dict[str, Any],
    ) -> None:
        """Compare primary submission vs IB direct's authoritative state."""
        await asyncio.sleep(self._SHADOW_OBSERVE_DELAY_S)
        try:
            from services.ib_direct_service import get_ib_direct_service
            svc = get_ib_direct_service()
        except Exception as e:
            logger.debug(f"[SHADOW] {symbol} import failed: {e}")
            return

        if not (svc.is_available() and svc.is_connected()):
            self._SHADOW_DIVERGENCE_COUNTERS["skipped_socket_down"] += 1
            logger.debug(
                f"[SHADOW] {symbol} skipped: IB-direct socket not connected. "
                f"Operator can `POST /api/system/ib-direct/connect` to enable."
            )
            return

        if not svc.is_authorized_to_trade():
            self._SHADOW_DIVERGENCE_COUNTERS["auth_lost"] += 1
            logger.warning(
                f"[SHADOW v19.34.27] {symbol} {intent} {action} {trade_id}: "
                f"IB-direct socket open but managedAccounts is EMPTY. "
                f"Brokerage session likely kicked elsewhere ('logged in on "
                f"another platform'). Pusher may be receiving stale data."
            )
            return

        try:
            positions = await svc.get_positions()
        except Exception as e:
            logger.debug(f"[SHADOW] {symbol} get_positions failed: {e}")
            return

        ib_signed = 0.0
        for p in positions or []:
            if (p.get("symbol") or "").upper() == symbol.upper():
                ib_signed += float(p.get("position") or 0)
        ib_signed_int = int(round(ib_signed))

        # We can't perfectly compute the expected post-submit position
        # without knowing the bot's pre-submit position cache (and we
        # deliberately don't reach into that here to keep this read-
        # only). Instead, sanity-check on direction + magnitude.
        # Direction: a BUY should leave IB with a non-negative or
        # increased position; a SELL with non-positive or decreased.
        delta_dir = 1 if expected_signed_delta > 0 else (-1 if expected_signed_delta < 0 else 0)

        # Detect "primary said filled, IB shows nothing/wrong-side"
        # — the v19.34.15a fingerprint.
        if intent == "bracket" and primary_result.get("status") == "filled":
            if ib_signed_int == 0:
                self._SHADOW_DIVERGENCE_COUNTERS["missing_at_ib"] += 1
                logger.error(
                    f"[SHADOW DIVERGENCE v19.34.27] {symbol} {intent} {action} "
                    f"trade={trade_id}: pusher reported FILLED but IB direct "
                    f"shows ZERO position {self._SHADOW_OBSERVE_DELAY_S}s "
                    f"later. Likely silent pusher fail — operator should "
                    f"verify in TWS."
                )
                return
            if delta_dir != 0 and ((ib_signed_int > 0) != (delta_dir > 0)):
                self._SHADOW_DIVERGENCE_COUNTERS["direction_mismatch"] += 1
                logger.error(
                    f"[SHADOW DIVERGENCE v19.34.27] {symbol} {intent} {action} "
                    f"trade={trade_id}: expected {delta_dir:+d} delta but "
                    f"IB shows {ib_signed_int:+d}. Direction mismatch."
                )
                return

        # All good — primary and IB direct agree on the broad shape.
        self._SHADOW_DIVERGENCE_COUNTERS["observed_ok"] += 1
        logger.info(
            f"[SHADOW] {symbol} {intent} {action} trade={trade_id}: "
            f"IB direct concurs (signed_position={ib_signed_int:+d})"
        )

    @classmethod
    def shadow_stats(cls) -> Dict[str, Any]:
        """Read the shadow-divergence counters for UI surfacing.

        Returned dict is a snapshot — counters keep ticking after this
        call. UI uses these to decorate the IB-LIVE chip tooltip.
        """
        return {
            "order_path": (os.environ.get("BOT_ORDER_PATH", "pusher") or "pusher").strip().lower(),
            "counters": dict(cls._SHADOW_DIVERGENCE_COUNTERS),
        }

    async def execute_entry(self, trade) -> Dict[str, Any]:
        """
        Execute entry order for a trade.
        Returns dict with success, order_id, fill_price, etc.
        """
        # v19.34.26 — bypass-proof kill-switch refusal at the executor
        # layer. See _kill_switch_refusal docstring for the today's
        # incident this prevents.
        _refusal = self._kill_switch_refusal("execute_entry", trade)
        if _refusal is not None:
            return _refusal

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
        from alpaca.trading.requests import MarketOrderRequest
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
            from routers.ib import queue_order, is_pusher_connected
            
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

    # ==================== OCA STOP+TARGET (POST-FILL) ====================

    async def attach_oca_stop_target(self, trade) -> Dict[str, Any]:
        """v19.34.28 — Attach an OCA-linked stop + target bracket to an
        ALREADY-FILLED position.

        Used by the reconciler's `_spawn_excess_slice` when it adopts
        phantom IB shares into a new BotTrade — the position already
        exists at IB, so a normal `place_bracket_order` (with a parent
        entry) would open a second, unintended fill. Instead we submit
        just the STP + LMT legs, both sharing a single `oca_group`
        string so IB auto-cancels the survivor when one fills.

        Contract (mirrors `bracket_reissue_service.submit_oca_pair`):
          - STP covers trade.shares at trade.stop_price
          - LMT covers trade.shares at trade.target_prices[0]
          - Both flagged with the same oca_group
          - TIF derived from trade_style/timeframe (GTC for swing,
            DAY for intraday/scalp) via bracket_tif.bracket_tif()

        Return:
          {success, stop_order_id, target_order_id, oca_group, errors}

        Failure modes (best-effort, operator-visible):
          - Pusher offline → simulate both ids; return success=True so the
            reconciler still adopts. Downstream manage loop will retry.
          - STP submit fails → abort; target NOT submitted (we never want
            a target without a stop — one-sided exposure is WORSE than
            no protection because it can flip the position on fill).
          - LMT submit fails AFTER STP succeeded → return partial success;
            stop is protecting, target is missing. Operator is warned
            in the log so they can add the target in TWS manually.

        This method does NOT wait for either leg to fill (they're
        resting orders designed to live for the trade's lifetime). It
        returns as soon as both IDs are allocated.
        """
        if self._mode == ExecutorMode.SIMULATED:
            return {
                "success": True,
                "stop_order_id": f"SIM-STP-{trade.id}",
                "target_order_id": f"SIM-TGT-{trade.id}",
                "oca_group": f"SIM-OCA-{trade.id}",
                "simulated": True,
            }

        if not self._ensure_initialized():
            return {"success": False, "error": "Executor not initialized"}

        if self._mode != ExecutorMode.LIVE:
            # PAPER (Alpaca) doesn't support OCA the same way — fall back
            # to stop-only for now. Alpaca bracket support is tracked
            # separately (see `alpaca_bracket_not_implemented` path).
            logger.info("attach_oca_stop_target: non-LIVE mode — falling back to stop-only")
            stop = await self.place_stop_order(trade)
            return {
                "success": bool(stop.get("success")),
                "stop_order_id": stop.get("order_id"),
                "target_order_id": None,
                "oca_group": None,
                "errors": [] if stop.get("success") else [stop.get("error", "stop-only-fallback")],
                "fallback": "stop_only_non_live",
            }

        try:
            from routers.ib import queue_order, is_pusher_connected
            import uuid as _uuid

            if not is_pusher_connected():
                logger.warning(
                    "attach_oca_stop_target: pusher offline for %s — "
                    "returning simulated ids; reconciler will retry on next scan.",
                    trade.symbol,
                )
                return {
                    "success": True,
                    "stop_order_id": f"SIM-STP-{trade.id}",
                    "target_order_id": f"SIM-TGT-{trade.id}",
                    "oca_group": f"SIM-OCA-{trade.id}",
                    "simulated": True,
                    "pusher_offline": True,
                }

            # Determine target price — first scale-out level if present.
            target_price = None
            if hasattr(trade, "target_prices") and trade.target_prices:
                try:
                    target_price = float(trade.target_prices[0])
                except (TypeError, ValueError):
                    target_price = None
            if target_price is None or trade.stop_price is None:
                return {
                    "success": False,
                    "error": "attach_oca_stop_target: missing stop_price or target_price",
                    "stop_order_id": None,
                    "target_order_id": None,
                    "oca_group": None,
                }

            action = "SELL" if trade.direction.value == "long" else "BUY"
            qty = int(trade.shares)

            # TIF per trade style (swing → GTC+outside_rth, intraday → DAY).
            leg_tif, leg_outside_rth = bracket_tif(
                getattr(trade, "trade_style", None),
                getattr(trade, "timeframe", None),
            )

            oca_group = f"ADOPT-OCA-{trade.symbol}-{trade.id}-{_uuid.uuid4().hex[:6]}"

            # 1) STP first. If this fails we do NOT submit the target —
            # one-sided exposure (target only, no stop) is worse than
            # no bracket because it can flip the position on fill.
            try:
                stop_id = queue_order({
                    "symbol": trade.symbol,
                    "action": action,
                    "quantity": qty,
                    "order_type": "STP",
                    "limit_price": None,
                    "stop_price": float(trade.stop_price),
                    "time_in_force": leg_tif,
                    "outside_rth": leg_outside_rth,
                    "oca_group": oca_group,
                    "trade_id": f"ADOPT-STOP-{trade.id}",
                })
            except Exception as e:
                logger.error(
                    f"attach_oca_stop_target: STP submit failed for "
                    f"{trade.symbol} (trade {trade.id}): {e} — target "
                    f"intentionally NOT submitted to avoid one-sided exposure."
                )
                return {
                    "success": False,
                    "error": f"stop_submit_failed: {e}",
                    "stop_order_id": None,
                    "target_order_id": None,
                    "oca_group": oca_group,
                }

            # 2) LMT target.
            target_id = None
            target_error = None
            try:
                target_id = queue_order({
                    "symbol": trade.symbol,
                    "action": action,
                    "quantity": qty,
                    "order_type": "LMT",
                    "limit_price": float(target_price),
                    "stop_price": None,
                    "time_in_force": leg_tif,
                    "outside_rth": leg_outside_rth,
                    "oca_group": oca_group,
                    "trade_id": f"ADOPT-TGT-{trade.id}",
                })
            except Exception as e:
                target_error = str(e)[:200]
                logger.error(
                    f"attach_oca_stop_target: LMT target submit failed for "
                    f"{trade.symbol} (trade {trade.id}): {e}. STOP IS LIVE "
                    f"({stop_id}) but target is MISSING — operator should "
                    f"place a manual LMT at ${target_price:.2f} or accept "
                    f"stop-only exposure."
                )

            logger.warning(
                f"[v19.34.28 ADOPT-OCA] {trade.symbol} trade {trade.id}: "
                f"attached stop={stop_id} (${trade.stop_price:.2f}) + "
                f"target={target_id or 'FAILED'} (${target_price:.2f}) "
                f"oca={oca_group}"
            )

            return {
                "success": True,
                "stop_order_id": stop_id,
                "target_order_id": target_id,
                "target_price": float(target_price),
                "stop_price": float(trade.stop_price),
                "oca_group": oca_group,
                "errors": [target_error] if target_error else [],
                "broker": "interactive_brokers",
                "partial": target_id is None,  # True = stop-only survived
            }

        except Exception as e:
            logger.error(f"attach_oca_stop_target error for {trade.symbol}: {e}")
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
        # v19.34.26 — Executor-layer kill-switch refusal. Today's incident
        # (UPS/ADBE/AMDL/XOP/TSLG/TEAM brackets fired with kill-switch on)
        # routed through THIS exact method. This single-line guard would
        # have prevented all six. See `_kill_switch_refusal` docstring.
        _refusal = self._kill_switch_refusal("place_bracket_order", trade)
        if _refusal is not None:
            return _refusal

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

            # v19.34.5 — classification-aware TIF for stop/target legs.
            # Intraday/scalp trades get DAY TIF (legs die at EOD with the parent),
            # swing/multi-day/position trades get GTC + outside_rth=True (must
            # survive overnight to provide stop protection). See
            # services/bracket_tif.py for the full decision tree and the bug
            # this fixes (forensic write-up in CHANGELOG 2026-05-04 EVE).
            _bracket_leg_tif, _bracket_leg_outside_rth = bracket_tif(
                getattr(trade, "trade_style", None),
                getattr(trade, "timeframe", None),
            )

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
                    "time_in_force": _bracket_leg_tif,
                    "outside_rth": _bracket_leg_outside_rth,
                },
                "target": {
                    "action": child_action,
                    "quantity": trade.shares,
                    "order_type": "LMT",
                    "limit_price": float(target_price),
                    "time_in_force": _bracket_leg_tif,
                    "outside_rth": _bracket_leg_outside_rth,
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
                primary_result = {
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
                # v19.34.27 — shadow-observe IB direct after pusher confirms.
                signed_delta = int(trade.shares) if action == "BUY" else -int(trade.shares)
                self._maybe_schedule_shadow_observe(
                    trade, primary_result,
                    action=action, intent="bracket",
                    expected_signed_delta=signed_delta,
                )
                return primary_result
            # ── v19.34.15a (2026-05-06) — Naked-position safety net.
            # Pre-fix this branch hard-rejected on ANY non-success status,
            # including ambiguous values like "unknown" or empty/missing
            # (pusher payload was malformed, network glitch mid-confirm,
            # IB-side queue lag). Operator forensic 2026-05-06 traced the
            # 4879-naked-share UPS bug to this exact path: parent leg
            # filled at IB but the bracket children's status came back as
            # `unknown`, which we read as "rejected", so the bot wrote
            # off the trade — leaving the parent fill orphaned at IB
            # without a stop or target.
            #
            # Safer: ambiguous statuses route through the SAME timeout
            # handler as a no-result timeout. trade_execution.py L631-655
            # then stamps `status=OPEN [TIMEOUT-NEEDS-SYNC]` and the
            # v19.34.15b drift loop catches any silent fill within ~30s.
            if status in ("unknown", "", None):
                logger.warning(
                    f"[v19.34.15a] Bracket status AMBIGUOUS for {trade.symbol} "
                    f"order {order_id} (status={status!r}, raw={r}). "
                    f"Routing through TIMEOUT handler to avoid the naked-position "
                    f"race that orphaned 4879sh UPS on 2026-05-06."
                )
                return {
                    "success": False,
                    "error": "bracket_status_ambiguous_v19_34_15a",
                    "entry_order_id": order_id,
                    "status": "timeout",
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
        """Execute a partial position exit (scale-out at target).

        v19.34.24 (2026-02-XX) — Added the missing ExecutorMode.LIVE branch.
        Pre-fix this method only handled SIMULATED + PAPER (Alpaca, which is
        disabled). When the manage loop detected a target hit on a LIVE-mode
        trade and called into the executor, the function fell off the end of
        the try block and implicitly returned None. The caller in
        `position_manager.execute_partial_exit` then did `result.get('success')`
        on None, raising AttributeError that was swallowed by the broader
        manage-loop guard. Net effect: scale-outs silently no-op'd in LIVE
        mode, and reconciled positions (which never get an IB-side OCA
        bracket) had no way to fire targets at all.

        Operator-discovered via FDX 2026-02-XX: price spiked through PT
        $374.44 + $375.08, both reconciled legs sat unrealized at +$5,228
        because neither path could close them — no IB bracket existed AND
        the local fire-the-target path was broken for LIVE.

        For LIVE we route a standalone MKT through the IB pusher queue
        (mirroring `_ib_close_position` but without the bracket-cancel
        prelude). Bracket cleanup is handled separately by the v19.34.7
        `bracket_reissue_service.reissue_bracket_for_trade` call in
        `position_manager.check_and_execute_scale_out` *after* the partial
        fill succeeds — so we deliberately do NOT cancel children here.
        """
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

            elif self._mode == ExecutorMode.LIVE:
                # v19.34.24 — IB live partial exit via the pusher order
                # queue. Standalone MKT for `shares` qty in the closing
                # direction; bracket child re-issue is handled by the
                # caller after this returns success.
                return await self._ib_partial_exit(trade, shares)

        except Exception as e:
            logger.error(f"Partial exit error: {e}")
            return {"success": False, "error": str(e)}

        # Defensive: unhandled mode (should be unreachable). Pre-v19.34.24
        # this path silently returned None and the caller crashed on
        # `.get('success')`. Now we surface the bug explicitly.
        logger.error(
            f"execute_partial_exit: unhandled ExecutorMode {self._mode!r} "
            f"for {trade.symbol} {shares}sh — returning explicit failure."
        )
        return {
            "success": False,
            "error": f"unhandled_executor_mode_{self._mode}",
        }

    async def _ib_partial_exit(self, trade, shares: int) -> Dict[str, Any]:
        """v19.34.24 (2026-02-XX) — IB live partial exit via order queue.

        Submits a standalone MKT for `shares` quantity in the closing
        direction (long → SELL, short → BUY). Mirrors `_ib_close_position`
        without the `_cancel_ib_bracket_orders` prelude — bracket child
        cleanup after a partial fill is the caller's responsibility (handled
        by `bracket_reissue_service.reissue_bracket_for_trade` in
        `position_manager.check_and_execute_scale_out`, v19.34.7).

        Returns the same shape as `_ib_close_position`:
          - success → {success: True, order_id, fill_price, broker, shares}
          - reject  → {success: False, error, order_id}
          - timeout → {success: False, error: "Timeout waiting...", order_id}

        On pusher disconnect we simulate (same fall-back semantics as
        `_ib_close_position` so the local state mutation in the caller
        stays consistent with paper-mode behaviour).
        """
        try:
            from routers.ib import queue_order, get_order_result, is_pusher_connected

            if not is_pusher_connected():
                logger.warning(
                    f"v19.34.24 partial-exit: IB pusher not connected — "
                    f"simulating partial fill for {trade.symbol} ({shares}sh)"
                )
                return {
                    "success": True,
                    "order_id": f"SIM-PARTIAL-{trade.id}",
                    "fill_price": trade.current_price,
                    "shares": shares,
                    "simulated": True,
                }

            action = "SELL" if trade.direction.value == "long" else "BUY"

            order_id = queue_order({
                "symbol": trade.symbol,
                "action": action,
                "quantity": shares,
                "order_type": "MKT",
                "limit_price": None,
                "stop_price": None,
                "time_in_force": "DAY",
                "trade_id": f"PARTIAL-{trade.id}",
            })

            logger.info(
                f"v19.34.24 partial-exit queued: {order_id} — {action} "
                f"{shares} {trade.symbol} (target hit on trade {trade.id})"
            )

            # Wait for fill in a worker thread so the FastAPI event loop
            # stays responsive (matches `_ib_close_position` pattern).
            result = await asyncio.to_thread(get_order_result, order_id, 60.0)

            if not result:
                return {
                    "success": False,
                    "error": "Timeout waiting for partial-exit order execution",
                    "order_id": order_id,
                    "shares": 0,
                }

            order_result = result.get("result", {}) or {}
            status = order_result.get("status", "unknown")

            if status == "filled":
                return {
                    "success": True,
                    "order_id": order_id,
                    "fill_price": order_result.get("fill_price", trade.current_price),
                    "shares": shares,
                    "broker": "interactive_brokers",
                }

            return {
                "success": False,
                "error": order_result.get("error", f"Partial exit {status}"),
                "order_id": order_id,
                "shares": 0,
            }

        except Exception as e:
            logger.error(f"v19.34.24 IB partial-exit error: {e}")
            return {"success": False, "error": str(e), "shares": 0}

    
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
                    primary_result = {
                        "success": True,
                        "order_id": order_id,
                        "fill_price": order_result.get("fill_price", trade.current_price),
                        "broker": "interactive_brokers"
                    }
                    # v19.34.27 — close inverts the position, so signed
                    # delta is the OPPOSITE of the trade's direction.
                    closing_action = "SELL" if trade.direction.value == "long" else "BUY"
                    signed_delta = -int(trade.shares) if closing_action == "SELL" else int(trade.shares)
                    self._maybe_schedule_shadow_observe(
                        trade, primary_result,
                        action=closing_action, intent="close",
                        expected_signed_delta=signed_delta,
                    )
                    return primary_result
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
            pass
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
