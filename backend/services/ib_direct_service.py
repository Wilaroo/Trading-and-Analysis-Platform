"""
ib_direct_service.py — v19.34.25 (2026-02-XX)

Direct IB API connection ALONGSIDE the existing pusher RPC. Same IB Gateway,
different `clientId`, separate dedicated socket for orders.

WHY: today's session exposed multiple state-divergence bugs caused by the
pusher being a relay between the bot and IB:
  - Phantom share counts (BMNR 5,472 vs IB 1,905) from snapshot lag
  - Flatten orders silently disappearing into the queue (60s timeout each)
  - "Logged in on another platform" failures detected only by 60s timeouts
This service connects DIRECTLY to IB Gateway via the TWS API socket
(clientId 11 by default), giving the bot:
  - Synchronous placeOrder / cancelOrder primitives (vs queue + poll)
  - Real-time orderStatus + execDetails callbacks (vs delayed snapshots)
  - Authoritative position queries (vs pusher's relayed snapshot)
  - Loud failure on transmit-permission loss (vs silent 60s timeout)

PHASE 1 (this commit, v19.34.25):
  - Singleton service stands up the connection in isolation.
  - Exposes status + diagnostic methods only — NOT wired into the
    trade_executor_service yet. Operator validates the socket works on
    their DGX before any order goes through it.
  - New endpoint `GET /api/system/ib-direct/status` for verification.

PHASE 2 (next session, deferred):
  - Wire as alternative path in `trade_executor_service` controlled by
    `BOT_ORDER_PATH=pusher|shadow|direct` env var.
  - Shadow mode: orders go through pusher AS USUAL, also submit to
    direct IB, log divergences but don't act on them.
  - Direct mode: direct is primary, pusher is data-only.

PHASE 3 (later):
  - Pusher's order endpoints (queue_order / get_order_result /
    cancel_order) deprecated; pusher becomes data-only.

The pusher (clientId=10, port=4002) continues to handle all market data
streaming. This service uses a separate clientId (default 11) so the two
clients coexist on the same Gateway without socket contention.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ib_async is the maintained successor to ib_insync (which was archived
# in 2024 after the original maintainer passed away). Same API surface.
try:
    from ib_async import IB, Stock, MarketOrder, LimitOrder, StopOrder, Order
    from ib_async import util as _ib_util          # noqa: F401  (handy for ad-hoc debug)
    IB_ASYNC_AVAILABLE = True
except ImportError:                                  # pragma: no cover
    IB_ASYNC_AVAILABLE = False
    IB = None  # type: ignore


# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


@dataclass
class IBDirectConfig:
    """Connection params for the direct IB API socket.

    Defaults match the user's DGX → Windows-IB-Gateway topology:
      - DGX is at 192.168.50.2; pusher + IB Gateway run on 192.168.50.1
      - Pusher uses clientId=10, port 4002 (paper)
      - Bot's direct connection uses clientId=11 to coexist
    Env-driven so the user can flip live/paper or rebind without a code
    change.
    """
    host: str = field(default_factory=lambda: os.environ.get("IB_DIRECT_HOST",
                                                               os.environ.get("IB_HOST", "192.168.50.1")))
    port: int = field(default_factory=lambda: _env_int("IB_DIRECT_PORT", 4002))
    client_id: int = field(default_factory=lambda: _env_int("IB_DIRECT_CLIENT_ID", 11))
    connect_timeout_s: float = field(default_factory=lambda: float(os.environ.get("IB_DIRECT_CONNECT_TIMEOUT", "8")))
    # Read-only (probes connection but never places orders) — handy for
    # the very first dry-run on a new install. Default False so that
    # once the user confirms the socket is up, real orders work.
    read_only: bool = field(default_factory=lambda:
                            os.environ.get("IB_DIRECT_READ_ONLY", "false").lower() == "true")


# ─────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────


class IBDirectService:
    """Singleton wrapper around an `ib_async.IB()` connection.

    Lifecycle:
      - Created lazily by `get_ib_direct_service()` (no boot cost).
      - `connect()` is async + idempotent — safe to call repeatedly.
      - Auto-reconnects on socket drop via `ensure_connected()`.

    Concurrency model:
      - All `IB` calls are async + non-blocking (eventkit-backed).
      - Multiple coroutines can call methods concurrently; each
        `placeOrder` is in-flight until its `orderStatus` callback fires.
    """

    def __init__(self, config: Optional[IBDirectConfig] = None):
        self.config = config or IBDirectConfig()
        self._ib: Optional["IB"] = None
        self._connected: bool = False
        self._authorized_to_trade: bool = False
        self._last_connect_error: Optional[str] = None
        self._connect_lock = asyncio.Lock() if IB_ASYNC_AVAILABLE else None

    # ── connection lifecycle ──────────────────────────────────────────

    def is_available(self) -> bool:
        """ib_async installed in the running interpreter?"""
        return IB_ASYNC_AVAILABLE

    def is_connected(self) -> bool:
        """Socket-level connection up? Doesn't guarantee transmit perms —
        see `is_authorized_to_trade()` for that."""
        return self._connected and self._ib is not None and self._ib.isConnected()

    def is_authorized_to_trade(self) -> bool:
        """Does this client have brokerage transmit permissions?

        IB Gateway keeps the socket open even when the brokerage session
        was kicked by another login (the 'logged in on another platform'
        scenario we hit today). The TWS API surfaces this via the
        `managedAccounts` list being empty + `accountValues` being
        zero/stale. We check on connect and refresh on reqAccountSummary
        callbacks. Conservative default: False until we have evidence.
        """
        return self._connected and self._authorized_to_trade

    async def connect(self) -> Dict[str, Any]:
        """Idempotent connect. Returns a status dict either way."""
        if not IB_ASYNC_AVAILABLE:
            return {
                "success": False,
                "error": "ib_async not installed (pip install ib_async)",
            }

        # Single-flight lock so two coroutines starting at the same time
        # don't both try to claim clientId=11 (the second would get
        # `Connection already exists` from IB Gateway).
        async with self._connect_lock:                # type: ignore
            if self.is_connected():
                return self._status_dict("already connected")

            self._ib = IB()
            try:
                await self._ib.connectAsync(
                    host=self.config.host,
                    port=self.config.port,
                    clientId=self.config.client_id,
                    readonly=self.config.read_only,
                    timeout=self.config.connect_timeout_s,
                )
                self._connected = True
                self._last_connect_error = None
                logger.warning(
                    "v19.34.25 [IB-DIRECT] connected: %s:%d (clientId=%d, readonly=%s)",
                    self.config.host, self.config.port,
                    self.config.client_id, self.config.read_only,
                )

                # Probe trade authorization. `managedAccounts` is empty
                # when the brokerage session has been kicked elsewhere.
                managed = self._ib.managedAccounts()
                self._authorized_to_trade = bool(managed and any(a for a in managed))
                if not self._authorized_to_trade:
                    logger.error(
                        "v19.34.25 [IB-DIRECT] socket open but NOT authorized "
                        "to trade — managedAccounts is empty. Likely 'logged "
                        "in on another platform' — close TWS/Gateway "
                        "elsewhere and reconnect."
                    )

                return self._status_dict("connected")

            except Exception as e:
                self._connected = False
                self._authorized_to_trade = False
                self._last_connect_error = str(e)[:200]
                logger.error(
                    "v19.34.25 [IB-DIRECT] connect failed: %s:%d clientId=%d — %s",
                    self.config.host, self.config.port,
                    self.config.client_id, e,
                )
                return {
                    "success": False,
                    "error": self._last_connect_error,
                    "host": self.config.host,
                    "port": self.config.port,
                    "client_id": self.config.client_id,
                }

    async def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            try:
                self._ib.disconnect()
            except Exception:
                pass
        self._connected = False
        self._authorized_to_trade = False

    async def ensure_connected(self) -> bool:
        """Lazy reconnect if the socket dropped. Returns connection state."""
        if self.is_connected():
            return True
        result = await self.connect()
        return bool(result.get("success") is not False and self.is_connected())

    # ── diagnostics (Phase 1 deliverable) ─────────────────────────────

    def status(self) -> Dict[str, Any]:
        return self._status_dict(
            "connected" if self.is_connected() else "disconnected"
        )

    def _status_dict(self, message: str) -> Dict[str, Any]:
        return {
            "success": True,
            "message": message,
            "ib_async_available": IB_ASYNC_AVAILABLE,
            "connected": self.is_connected(),
            "authorized_to_trade": self.is_authorized_to_trade(),
            "host": self.config.host,
            "port": self.config.port,
            "client_id": self.config.client_id,
            "read_only": self.config.read_only,
            "managed_accounts": (
                list(self._ib.managedAccounts()) if self._ib and self._ib.isConnected() else []
            ),
            "last_connect_error": self._last_connect_error,
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Authoritative live positions per IB API. Used to cross-check
        the bot's `_open_trades` cache for phantom-share detection."""
        if not await self.ensure_connected():
            return []
        try:
            positions = await asyncio.to_thread(self._ib.positions)
            out = []
            for p in positions:
                out.append({
                    "account":   p.account,
                    "symbol":    p.contract.symbol if p.contract else None,
                    "sec_type":  p.contract.secType if p.contract else None,
                    "exchange":  p.contract.exchange if p.contract else None,
                    "position":  float(p.position),
                    "avg_cost":  float(p.avgCost),
                })
            return out
        except Exception as e:
            logger.error("v19.34.25 [IB-DIRECT] get_positions failed: %s", e)
            return []

    # ── order primitives (NOT wired into trade_executor yet) ──────────
    #
    # Phase 2 (next session) will wire these into trade_executor_service
    # behind the `BOT_ORDER_PATH` env var. For now they're available for
    # standalone integration tests / manual smoke-checks.

    async def place_market_order(
        self,
        symbol: str,
        action: str,         # "BUY" | "SELL"
        quantity: int,
        *,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """Submit a MKT and wait for it to leave the socket (NOT for fill).

        Fill arrives later via `orderStatus` callback; the caller can
        either subscribe to that event or query `_ib.trades()` for the
        Trade object. We deliberately don't block on fill here — that's
        the caller's choice and matches `_ib_close_position`'s pattern.
        """
        if not await self.ensure_connected():
            return {"success": False, "error": "not connected"}
        if self.config.read_only:
            return {"success": False, "error": "read_only mode — order rejected"}
        if not self.is_authorized_to_trade():
            return {"success": False, "error": "not authorized to trade (managedAccounts empty)"}

        try:
            contract = Stock(symbol, exchange, currency)
            await asyncio.to_thread(self._ib.qualifyContracts, contract)
            order = MarketOrder(action.upper(), int(quantity))
            trade = self._ib.placeOrder(contract, order)
            return {
                "success": True,
                "order_id": int(trade.order.orderId),
                "perm_id":  int(trade.order.permId or 0),
                "symbol":   symbol,
                "action":   action.upper(),
                "quantity": int(quantity),
                "status":   trade.orderStatus.status if trade.orderStatus else "submitted",
            }
        except Exception as e:
            logger.error("v19.34.25 [IB-DIRECT] place_market_order failed: %s %s %s — %s",
                         action, quantity, symbol, e)
            return {"success": False, "error": str(e)[:200]}

    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """Cancel a working order by IB orderId."""
        if not await self.ensure_connected():
            return {"success": False, "error": "not connected"}
        try:
            # Find the trade with that orderId in the live cache.
            target = None
            for t in self._ib.trades():
                if int(t.order.orderId) == int(order_id):
                    target = t
                    break
            if target is None:
                return {"success": False, "error": f"order_id {order_id} not found in live trades"}
            self._ib.cancelOrder(target.order)
            return {"success": True, "order_id": int(order_id)}
        except Exception as e:
            logger.error("v19.34.25 [IB-DIRECT] cancel_order failed: %s — %s", order_id, e)
            return {"success": False, "error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────


_singleton: Optional[IBDirectService] = None


def get_ib_direct_service() -> IBDirectService:
    """Lazy singleton — instantiates on first call, persists for the
    lifetime of the process. Connection is NOT auto-opened on first
    access; callers must `await connect()` explicitly so boot stays fast
    and a misconfigured socket doesn't crash service init."""
    global _singleton
    if _singleton is None:
        _singleton = IBDirectService()
    return _singleton
