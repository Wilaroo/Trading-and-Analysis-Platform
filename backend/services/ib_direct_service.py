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
import time
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

        # ── v19.34.54 (Feb 2026) — connection stability instrumentation ──
        # The clientId=11 socket has been flapping 1-3x/day. The
        # v19.34.52 drift guard fails-safe by SKIPping zero-closes when
        # direct IB is down, which is correct but means real external
        # closes go un-resolved during the disconnect window. We need:
        #   1. Disconnect-event handler so `is_connected()` flips
        #      immediately (don't wait for next call to notice).
        #   2. Background watchdog that auto-reconnects within ~30s
        #      of a drop (currently `ensure_connected()` is called
        #      lazily, so a drop persists until someone tries to use it).
        #   3. Drop / reconnect counters surfaced via `status()` so the
        #      operator can see flap frequency at a glance.
        self._drop_count_total: int = 0
        self._reconnect_count_total: int = 0
        self._reconnect_failures_total: int = 0
        self._last_drop_at: Optional[float] = None
        self._last_reconnect_at: Optional[float] = None
        self._last_drop_reason: Optional[str] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_started_at: Optional[float] = None
        # ── v19.34.58 (Feb 2026) — proactive heartbeat ──
        # `ib_async`'s `disconnectedEvent` only fires when the TCP
        # socket *closes cleanly*. Half-open / silently-broken sockets
        # (network drop, IB Gateway frozen, NAT idle eviction) leave
        # `_ib.isConnected()` returning True forever. The watchdog
        # now also pings IB with `reqCurrentTime()` every
        # `_HEARTBEAT_INTERVAL_S` seconds; if the ping fails or
        # exceeds the deadline, we flip ourselves to disconnected and
        # let the watchdog reconnect.
        self._last_heartbeat_ok_at: Optional[float] = None
        self._last_heartbeat_failed_at: Optional[float] = None
        self._heartbeat_failures_total: int = 0

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
                self._last_reconnect_at = time.time()
                logger.warning(
                    "v19.34.25 [IB-DIRECT] connected: %s:%d (clientId=%d, readonly=%s)",
                    self.config.host, self.config.port,
                    self.config.client_id, self.config.read_only,
                )

                # ── v19.34.54 — flap-detection event hook ──
                # `disconnectedEvent` fires when the socket drops for
                # ANY reason (Gateway restart, network blip, idle
                # timeout, "logged in elsewhere" kick). Without this,
                # `is_connected()` only learns about the drop on the
                # next call (because it polls `_ib.isConnected()`).
                # With this, we record the drop timestamp + reason so
                # the watchdog knows to reconnect AND `status()` can
                # surface flap frequency.
                try:
                    def _on_disconnect():
                        self._connected = False
                        self._authorized_to_trade = False
                        self._drop_count_total += 1
                        self._last_drop_at = time.time()
                        self._last_drop_reason = "disconnectedEvent"
                        logger.error(
                            "v19.34.54 [IB-DIRECT] socket dropped "
                            "(clientId=%d, drop #%d). Watchdog will "
                            "reconnect.",
                            self.config.client_id, self._drop_count_total,
                        )
                    self._ib.disconnectedEvent += _on_disconnect
                except Exception as _ev_err:
                    logger.warning(
                        "v19.34.54 [IB-DIRECT] could not register "
                        "disconnectedEvent handler: %s", _ev_err,
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

    # ── v19.34.54 — watchdog: keeps clientId=11 alive automatically ──
    #
    # Without this, drops persist until something calls
    # `ensure_connected()`. The drift reconciler runs every ~5s but
    # only calls direct IB when it's already considering a close —
    # plenty of time for v19.34.52 to skip a real external close
    # because the socket was momentarily down.
    #
    # The watchdog runs every `_WATCHDOG_INTERVAL_S` seconds. If the
    # socket is down, it calls `ensure_connected()`. Failures are
    # backed off (linearly) up to 5 minutes between attempts so we
    # don't hammer IB Gateway during extended outages.
    _WATCHDOG_INTERVAL_S = 15.0
    _WATCHDOG_MAX_BACKOFF_S = 300.0
    # v19.34.58 — heartbeat timing. Ping at 30s and require a response
    # within 5s. IB Gateway's `reqCurrentTime` typically returns in
    # well under 200ms; a 5s deadline is a generous "the socket is
    # dead, not just slow" threshold.
    _HEARTBEAT_INTERVAL_S = 30.0
    _HEARTBEAT_DEADLINE_S = 5.0

    async def _heartbeat_check(self) -> bool:
        """Send `reqCurrentTime` over the existing socket. Returns True
        if IB responded within the deadline. On failure, flips this
        service to disconnected so the watchdog reconnects.
        """
        if self._ib is None or not self._ib.isConnected():
            return False
        try:
            # `reqCurrentTimeAsync` returns a `datetime`. ib_async raises
            # on transport error. We additionally clamp with `wait_for`
            # to detect frozen / half-open sockets.
            await asyncio.wait_for(
                self._ib.reqCurrentTimeAsync(),
                timeout=self._HEARTBEAT_DEADLINE_S,
            )
            self._last_heartbeat_ok_at = time.time()
            return True
        except (asyncio.TimeoutError, Exception) as e:
            self._last_heartbeat_failed_at = time.time()
            self._heartbeat_failures_total += 1
            # Treat heartbeat failure as a silent socket drop so the
            # watchdog reconnects on the next iteration.
            self._connected = False
            self._authorized_to_trade = False
            self._drop_count_total += 1
            self._last_drop_at = time.time()
            self._last_drop_reason = f"heartbeat_failed:{type(e).__name__}"
            logger.error(
                "v19.34.58 [IB-DIRECT] heartbeat failed (%s: %s) — "
                "marking socket dropped. Watchdog will reconnect.",
                type(e).__name__, str(e)[:120],
            )
            return False

    async def _watchdog_loop(self) -> None:
        consecutive_failures = 0
        last_heartbeat_at = 0.0
        logger.info(
            "v19.34.54 [IB-DIRECT] watchdog started (interval=%ss, heartbeat=%ss)",
            self._WATCHDOG_INTERVAL_S, self._HEARTBEAT_INTERVAL_S,
        )
        while True:
            try:
                if self.is_connected():
                    consecutive_failures = 0
                    # v19.34.58 — send periodic heartbeat to detect
                    # half-open / silently-broken sockets that
                    # `disconnectedEvent` never reports.
                    now_ts = time.time()
                    if (now_ts - last_heartbeat_at) >= self._HEARTBEAT_INTERVAL_S:
                        last_heartbeat_at = now_ts
                        await self._heartbeat_check()
                else:
                    backoff = min(
                        self._WATCHDOG_INTERVAL_S * (consecutive_failures + 1),
                        self._WATCHDOG_MAX_BACKOFF_S,
                    )
                    if consecutive_failures > 0:
                        await asyncio.sleep(
                            backoff - self._WATCHDOG_INTERVAL_S,
                        )
                    logger.warning(
                        "v19.34.54 [IB-DIRECT] watchdog reconnecting "
                        "(attempt %d after %.0fs backoff)",
                        consecutive_failures + 1, backoff,
                    )
                    res = await self.connect()
                    if res.get("connected"):
                        self._reconnect_count_total += 1
                        consecutive_failures = 0
                        logger.warning(
                            "v19.34.54 [IB-DIRECT] watchdog reconnected "
                            "after %s. total drops=%d total reconnects=%d",
                            self._last_drop_reason or "unknown",
                            self._drop_count_total,
                            self._reconnect_count_total,
                        )
                    else:
                        self._reconnect_failures_total += 1
                        consecutive_failures += 1
                        logger.error(
                            "v19.34.54 [IB-DIRECT] reconnect failed "
                            "(consecutive=%d): %s",
                            consecutive_failures,
                            res.get("error") or self._last_connect_error,
                        )
            except asyncio.CancelledError:
                logger.info("v19.34.54 [IB-DIRECT] watchdog cancelled")
                raise
            except Exception as e:
                logger.exception(
                    "v19.34.54 [IB-DIRECT] watchdog iteration crashed: %s", e
                )
            await asyncio.sleep(self._WATCHDOG_INTERVAL_S)

    def start_watchdog(self) -> bool:
        """Start the background reconnect watchdog. Idempotent — safe
        to call multiple times. Returns True if a new task was spawned,
        False if one was already running."""
        if not IB_ASYNC_AVAILABLE:
            return False
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return False
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            return False
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(),
            name="ib_direct_watchdog_v19_34_54",
        )
        self._watchdog_started_at = time.time()
        return True

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
            # v19.34.54 — flap visibility
            "stability": {
                "drop_count_total": self._drop_count_total,
                "reconnect_count_total": self._reconnect_count_total,
                "reconnect_failures_total": self._reconnect_failures_total,
                "last_drop_at": self._last_drop_at,
                "last_drop_reason": self._last_drop_reason,
                "last_reconnect_at": self._last_reconnect_at,
                "watchdog_running": (
                    self._watchdog_task is not None
                    and not self._watchdog_task.done()
                ),
                "watchdog_started_at": self._watchdog_started_at,
                # v19.34.58 — heartbeat visibility
                "heartbeat_failures_total": self._heartbeat_failures_total,
                "last_heartbeat_ok_at": self._last_heartbeat_ok_at,
                "last_heartbeat_failed_at": self._last_heartbeat_failed_at,
            },
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

    async def cancel_all_open_orders_for_symbol(
        self, symbol: str, side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v19.34.44 — cancel every WORKING order for a (symbol[, side]).

        Operator-discovered 2026-02-XX during BMNR flatten-all attempt:
        IB Error 201 — `Your account has a minimum of 15 orders working
        on either the buy or sell side for this particular contract`.
        Pre-fix, the 19 BMNR fragments each owned an OCA stop+target
        bracket child at IB (~38 working SELL orders). The consolidator
        collapsed the DB-side rows but those zombie OCA children stayed
        WORKING at IB because their order_ids weren't stamped on the
        canonical trade. Result: every subsequent close MKT got
        rejected by IB's 15-order cap.

        This method does the brute-force "blow away every working order
        for this contract" scan that flatten-all needs as a pre-step.
        Iterates `self._ib.trades()` (which sees ALL working orders on
        this IB Gateway session, even those placed by the pusher's
        clientId), filters by symbol [+ side], and cancels each.

        Args:
          symbol: Stock symbol to cancel orders for (case-insensitive).
          side:   Optional 'BUY' or 'SELL' filter. None = both sides.

        Returns:
          {success, cancelled: [order_ids], skipped: [...], errors: [...]}
        """
        report: Dict[str, Any] = {
            "success": True, "symbol": symbol.upper(),
            "side_filter": (side or "").upper() or None,
            "cancelled": [], "skipped": [], "errors": [],
        }
        if not await self.ensure_connected():
            report["success"] = False
            report["error"] = "not connected"
            return report
        try:
            # v19.34.46 (2026-02-XX) — Operator-discovered: my v19.34.44
            # zombie-cancel was a no-op. IB Gateway segregates working
            # orders by clientId. `self._ib.trades()` only returns orders
            # placed by THIS clientId. The pusher's working orders
            # (clientId=15) are invisible to the direct service
            # (clientId=11) until we explicitly request them via
            # `reqAllOpenOrders()` (one-shot pull) or
            # `reqAutoOpenOrders(True)` (subscribe to all clients,
            # only valid for clientId=0). We use reqAllOpenOrders here
            # because clientId=11 isn't 0. After this returns, the
            # `_ib.trades()` cache contains every working order on the
            # account — including the pusher's ghost OCA children that
            # are blocking BMNR closes via the 15-order cap.
            try:
                await asyncio.to_thread(self._ib.reqAllOpenOrders)
                # Brief settle so callbacks populate self._ib.trades()
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(
                    "v19.34.46 [IB-DIRECT] reqAllOpenOrders failed for %s: %s",
                    symbol, e,
                )
                report["errors"].append({
                    "stage": "reqAllOpenOrders", "err": str(e)[:200],
                })

            sym_u = symbol.upper()
            side_u = (side or "").upper()
            for t in list(self._ib.trades() or []):
                try:
                    contract = getattr(t, "contract", None)
                    order = getattr(t, "order", None)
                    status_obj = getattr(t, "orderStatus", None)
                    if contract is None or order is None:
                        continue
                    csym = (getattr(contract, "symbol", "") or "").upper()
                    if csym != sym_u:
                        continue
                    caction = (getattr(order, "action", "") or "").upper()
                    if side_u and caction != side_u:
                        continue
                    # Status filter: cancel only orders that are still WORKING.
                    # IB's `isActive` covers Submitted/PreSubmitted/PendingSubmit etc.
                    # Defensive: if no status, attempt cancel anyway (cheap).
                    if status_obj is not None and hasattr(t, "isActive"):
                        try:
                            if not t.isActive():
                                report["skipped"].append({
                                    "order_id": int(order.orderId),
                                    "status": getattr(status_obj, "status", "?"),
                                    "reason": "not_active",
                                })
                                continue
                        except Exception:
                            pass
                    self._ib.cancelOrder(order)
                    report["cancelled"].append({
                        "order_id": int(order.orderId),
                        "action": caction,
                        "qty": float(getattr(order, "totalQuantity", 0) or 0),
                    })
                except Exception as inner:
                    report["errors"].append({
                        "order_id": int(getattr(getattr(t, "order", None), "orderId", 0) or 0),
                        "err": str(inner)[:200],
                    })
            return report
        except Exception as e:
            logger.error(
                "v19.34.44 [IB-DIRECT] cancel_all_open_orders_for_symbol "
                "%s failed: %s", symbol, e,
            )
            report["success"] = False
            report["error"] = str(e)[:200]
            return report


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
