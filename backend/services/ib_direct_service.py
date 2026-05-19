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
        # v19.34.42 -- IB minTick cache (fixes Error 110 rejections).
        self._min_tick_cache: dict = {}

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
            # v19.34.28 Bug Y (2026-05-18) — replaced asyncio.to_thread wrapper.
            # Same deadlock pattern as L3-hotfix1: ib_async's qualifyContracts
            # internally calls loop.run_until_complete() on the main event
            # loop. Dispatching via to_thread causes the worker thread to
            # try to drive a loop the main thread owns → deadlock.
            # The async coroutine equivalent is qualifyContractsAsync.
            await self._ib.qualifyContractsAsync(contract)
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


    # ── v19.34.40 — Native MKT-close for EOD / manual / safety flatten ──
    # v19.34.42 -- IB minTick resolution + fp-safe price rounding
    async def _resolve_min_tick(self, contract) -> float:
        """Look up the contract's IB-reported minTick (cached, $0.01 fallback)."""
        try:
            key = (str(contract.symbol).upper(),
                   str(getattr(contract, "currency", "USD")).upper())
        except Exception:
            key = ("?", "USD")
        cache = self._min_tick_cache
        if key in cache:
            return cache[key]
        try:
            details = await self._ib.reqContractDetailsAsync(contract)
            if details:
                raw = getattr(details[0], "minTick", None)
                mt = float(raw) if raw is not None else 0.01
                if mt <= 0:
                    mt = 0.01
                cache[key] = mt
                logger.info("[v19.34.42 minTick] %s -> $%g", key[0], mt)
                return mt
        except Exception as exc:
            logger.warning(
                "[v19.34.42 minTick] reqContractDetailsAsync failed for "
                "%s: %s; defaulting to $0.01.", key[0], exc,
            )
        cache[key] = 0.01
        return 0.01

    @staticmethod
    def _round_to_tick(price: float, min_tick: float) -> float:
        """Round to nearest min_tick increment via Decimal (no fp artifacts)."""
        from decimal import Decimal, ROUND_HALF_UP
        try:
            mt = float(min_tick)
        except Exception:
            mt = 0.01
        if mt <= 0:
            return round(float(price), 4)
        p = Decimal(str(float(price)))
        t = Decimal(str(mt))
        return float((p / t).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * t)

    async def place_close_market(
        self,
        trade,
        *,
        wait_for_fill_s: float = 10.0,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """v19.34.40 — Native MKT-close on DGX-side ib_async socket.
        Hard-fails on disconnect; NEVER silent-simulates.
        """
        if not await self.ensure_connected():
            return {"success": False, "error": "ib_direct_not_connected",
                    "broker": "ib_direct", "simulated": False}
        if self.config.read_only:
            return {"success": False, "error": "ib_direct_read_only_mode",
                    "broker": "ib_direct", "simulated": False}
        if not self.is_authorized_to_trade():
            return {"success": False,
                    "error": "ib_direct_not_authorized_managed_accounts_empty",
                    "broker": "ib_direct", "simulated": False}

        try:
            symbol = str(trade.symbol).upper()
            direction = (getattr(trade.direction, "value", None)
                         or str(trade.direction)).lower()
            qty = int(getattr(trade, "remaining_shares", 0) or trade.shares)
            if qty <= 0:
                return {"success": False, "error": f"bad shares: {qty}",
                        "broker": "ib_direct", "simulated": False}
            action = "SELL" if direction == "long" else "BUY"
        except Exception as e:
            return {"success": False, "error": f"bad trade fields: {e}",
                    "broker": "ib_direct", "simulated": False}

        try:
            contract = Stock(symbol, exchange, currency)
            await self._ib.qualifyContractsAsync(contract)
            order = MarketOrder(action, qty)
            try:
                order.tif = "DAY"
            except Exception:
                pass
            close_trade = self._ib.placeOrder(contract, order)
            ib_order_id = int(close_trade.order.orderId)

            import asyncio as _asyncio
            deadline = _asyncio.get_event_loop().time() + max(0.5, float(wait_for_fill_s))
            ib_status = "submitted"
            filled_qty = 0
            avg_fill = 0.0
            while _asyncio.get_event_loop().time() < deadline:
                await _asyncio.sleep(0.25)
                status_obj = close_trade.orderStatus
                if status_obj is None:
                    continue
                ib_status = (status_obj.status or "submitted").lower()
                filled_qty = int(status_obj.filled or 0)
                avg_fill = float(status_obj.avgFillPrice or 0.0)
                if ib_status in ("filled", "cancelled", "apicancelled",
                                 "inactive", "rejected"):
                    break
                if filled_qty >= qty:
                    ib_status = "filled"
                    break

            if ib_status == "filled":
                status_out, success = "filled", True
            elif ib_status in ("cancelled", "apicancelled", "inactive", "rejected"):
                status_out, success = "rejected", False
            elif 0 < filled_qty < qty:
                status_out, success = "partial", True
            else:
                status_out, success = "submitted", False

            fill_price = avg_fill if filled_qty > 0 else None
            logger.info(
                "[v19.34.40 IB-DIRECT close] %s %s qty=%d -> order_id=%d "
                "status=%s filled=%d avg=%.4f",
                symbol, action, qty, ib_order_id, status_out,
                filled_qty, avg_fill,
            )
            return {
                "success": success,
                "order_id": ib_order_id,
                "ib_order_id": ib_order_id,
                "fill_price": fill_price,
                "filled_qty": filled_qty,
                "remaining_qty": max(0, qty - filled_qty),
                "status": status_out,
                "broker": "ib_direct",
                "simulated": False,
            }
        except Exception as e:
            logger.error(
                "[v19.34.40 IB-DIRECT close] place_close_market failed for "
                "%s: %s", getattr(trade, "symbol", "?"), e,
            )
            return {"success": False,
                    "error": f"ib_direct_close_error: {str(e)[:200]}",
                    "broker": "ib_direct", "simulated": False}


            fill_price = avg_fill if filled_qty > 0 else None
            logger.info(
                "[v19.34.40 IB-DIRECT close] %s %s qty=%d -> order_id=%d "
                "status=%s filled=%d avg=%.4f",
                symbol, action, qty, ib_order_id, status_out,
                filled_qty, avg_fill,
            )
            return {
                "success": success,
                "order_id": ib_order_id,
                "ib_order_id": ib_order_id,
                "fill_price": fill_price,
                "filled_qty": filled_qty,
                "remaining_qty": max(0, qty - filled_qty),
                "status": status_out,
                "broker": "ib_direct",
                "simulated": False,
            }
        except Exception as e:
            logger.error(
                "[v19.34.40 IB-DIRECT close] place_close_market failed for "
                "%s: %s", getattr(trade, "symbol", "?"), e,
            )
            return {"success": False,
                    "error": f"ib_direct_close_error: {str(e)[:200]}",
                    "broker": "ib_direct", "simulated": False}

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

    # ── v19.34.27 Patch L1 — Native ib_async bracket order placement ──────
    #
    # This is the load-bearing 75% of the IB_DIRECT_MIGRATION_PLAN. It
    # replaces `_ib_bracket`'s reliance on the Windows pusher's RPC bracket
    # contract with a synchronous `ib_async.bracketOrder()` call against
    # IB Gateway on this DGX-side socket (clientId=11).
    #
    # WHY THIS METHOD ELIMINATES TODAY'S BUG CLASS:
    #   1. NO pusher round-trip — eliminates bracket_submission_timeout
    #      (the EGO 1639-share naked stampede mode).
    #   2. NO simulated fallback on socket health — Patch J's fail-hard
    #      contract is preserved (returns success: False on any error),
    #      so no more SIM-* ID leakage into bot DB.
    #   3. Real IB orderIds — bot DB stops storing pusher-generated UUIDs
    #      that don't match anything in IB's working-orders feed.
    #   4. OCA semantics handled by ib_async — parent has transmit=False
    #      until last child queued, atomic activation.
    #
    # CONTRACT (matches `_ib_bracket` exactly so callers don't change):
    #   Returns dict with:
    #     success: bool
    #     entry_order_id: int (real IB orderId)
    #     stop_order_id: int
    #     target_order_id: int
    #     oca_group: str
    #     status: "submitted" | "filled" | "rejected" | "timeout"
    #     fill_price: float | None
    #     filled_qty: int
    #     broker: "ib_direct"
    #     simulated: False
    #     error: str (only on failure)
    #
    # Phase L2 (Saturday) adds the matching place_oca_stop_target,
    # place_entry, place_stop, get_positions_fresh, get_open_orders.
    async def place_bracket_order(
        self,
        trade,
        *,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
        wait_for_submission_s: float = 5.0,
    ) -> Dict[str, Any]:
        """Place an atomic OCA bracket (parent LMT + child STP + child LMT)
        via ib_async. Returns the same dict shape as `_ib_bracket` for
        drop-in compatibility in trade_executor_service.

        Args:
            trade: A BotTrade-shaped object with .symbol, .direction (.value
                'long'|'short'), .shares, .entry_price, .stop_price,
                .target_prices (list, first element used).
            wait_for_submission_s: How long to await the parent's
                `orderStatus` to flip past 'PendingSubmit'. Real fill is
                NOT awaited here — caller can subscribe to fills or query
                later. Pre-Patch-L1 the pusher's bracket waited up to 60s
                for a fill confirmation; ib-direct doesn't need this
                because orderIds are returned synchronously by ib_async.

        Returns:
            Dict — see CONTRACT comment above.
        """
        if not await self.ensure_connected():
            return {
                "success": False,
                "error": "ib_direct_not_connected",
                "broker": "ib_direct",
                "simulated": False,
            }
        if self.config.read_only:
            return {
                "success": False,
                "error": "ib_direct_read_only_mode",
                "broker": "ib_direct",
                "simulated": False,
            }
        if not self.is_authorized_to_trade():
            return {
                "success": False,
                "error": "ib_direct_not_authorized_managed_accounts_empty",
                "broker": "ib_direct",
                "simulated": False,
            }

        # Extract trade fields (defensive — handle missing/bad input).
        try:
            symbol = str(trade.symbol).upper()
            direction = (
                getattr(trade.direction, "value", None) or
                str(trade.direction)
            ).lower()
            if direction not in ("long", "short"):
                return {"success": False, "error": f"bad direction: {direction}",
                        "broker": "ib_direct", "simulated": False}
            qty = int(trade.shares)
            if qty <= 0:
                return {"success": False, "error": f"bad shares: {qty}",
                        "broker": "ib_direct", "simulated": False}
            entry_price = float(trade.entry_price)
            stop_price = float(trade.stop_price)
            targets = getattr(trade, "target_prices", None) or []
            if not targets:
                return {"success": False, "error": "no target_prices on trade",
                        "broker": "ib_direct", "simulated": False}
            target_price = float(targets[0])
        except Exception as e:
            return {"success": False, "error": f"bad trade fields: {e}",
                    "broker": "ib_direct", "simulated": False}

        # Action mapping. Long entry = BUY parent, SELL stop+target.
        # Short entry = SELL parent (SSHORT for IB short sell), BUY stop+target.
        if direction == "long":
            parent_action = "BUY"
            child_action = "SELL"
        else:
            parent_action = "SELL"   # ib_async's bracketOrder handles short via SELL
            child_action = "BUY"

        # v19.34.38 PRICE-BAND GUARD — reject LMT entries too far from market
        # (IB Error 202 protection: typically ~3% triggers IB auto-cancel).
        import os as _os38
        try:
            _band_pct = float(_os38.environ.get('IB_ENTRY_PRICE_BAND_PCT', '2.5'))
        except Exception:
            _band_pct = 2.5
        _cur_px = float(getattr(trade, 'current_price', 0) or 0)
        if _cur_px > 0 and _band_pct > 0:
            _dev_pct = abs(entry_price - _cur_px) / _cur_px * 100.0
            if _dev_pct > _band_pct:
                logger.warning(
                    "[v19.34.38 price-band] %s REJECTED: entry=$%.4f is %.2f%% from current $%.4f (threshold %.2f%%). Setup stale/aggressive — skip.",
                    symbol, entry_price, _dev_pct, _cur_px, _band_pct,
                )
                return {
                    "success": False,
                    "error": f"entry_too_aggressive:{_dev_pct:.2f}pct_from_market",
                    "broker": "ib_direct", "simulated": False,
                    "current_price": _cur_px, "entry_price": entry_price,
                    "deviation_pct": _dev_pct, "threshold_pct": _band_pct,
                }

        # v19.34.37 TWO-STEP MODE (default; rollback: IB_DIRECT_BRACKET_MODE=atomic)
        import os as _os
        _bracket_mode = (_os.environ.get('IB_DIRECT_BRACKET_MODE', 'two_step') or 'two_step').lower()
        if _bracket_mode == 'two_step':
            try:
                _parent_timeout_s = float(_os.environ.get('IB_DIRECT_BRACKET_PARENT_TIMEOUT_S', '30'))
            except Exception:
                _parent_timeout_s = 30.0
            return await self._place_bracket_two_step(
                trade=trade, symbol=symbol, direction=direction, qty=qty,
                entry_price=entry_price, stop_price=stop_price, target_price=target_price,
                parent_action=parent_action, child_action=child_action,
                sec_type=sec_type, exchange=exchange, currency=currency,
                parent_timeout_s=_parent_timeout_s,
            )

        try:
            # Qualify the contract first (off the event loop).
            contract = Stock(symbol, exchange, currency)
            import time as _bug_y_t
            _t0 = _bug_y_t.monotonic()
            print(f"[BUG-Y INSTR] {symbol} step1 qualifyContracts START t=0.000", flush=True)
            # v19.34.28 Bug Y (2026-05-18) — replaced asyncio.to_thread wrapper.
            # Same deadlock pattern as L3-hotfix1: ib_async's qualifyContracts
            # internally calls loop.run_until_complete() on the main event
            # loop. Dispatching via to_thread causes the worker thread to
            # try to drive a loop the main thread owns → deadlock.
            # The async coroutine equivalent is qualifyContractsAsync.
            await self._ib.qualifyContractsAsync(contract)
            print(f"[BUG-Y INSTR] {symbol} step1 qualifyContracts DONE  t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)

            # ib_async.bracketOrder constructs the three orders with
            # correct OCA group and transmit-sequencing. Parent's
            # transmit=False, stop's transmit=False, target's transmit=True
            # — atomic activation when the third is submitted.
            print(f"[BUG-Y INSTR] {symbol} step2 bracketOrder START t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            # v19.34.42 -- round to IB minTick (fixes Error 110).
            min_tick = await self._resolve_min_tick(contract)
            bracket = self._ib.bracketOrder(
                action=parent_action,
                quantity=qty,
                limitPrice=self._round_to_tick(entry_price, min_tick),
                takeProfitPrice=self._round_to_tick(target_price, min_tick),
                stopLossPrice=self._round_to_tick(stop_price, min_tick),
            )

            # ib_async's bracketOrder returns a 3-tuple-like object
            # (parent, takeProfit, stopLoss). Some versions return a list.
            try:
                parent_o = bracket.parent
                take_profit_o = bracket.takeProfit
                stop_loss_o = bracket.stopLoss
            except AttributeError:
                # Fall back to indexed access.
                parent_o, take_profit_o, stop_loss_o = (
                    bracket[0], bracket[1], bracket[2],
                )

            print(f"[BUG-Y INSTR] {symbol} step2 bracketOrder DONE  t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            # Submit all three. ib_async will respect each order's
            # transmit flag and IB activates them atomically.
            print(f"[BUG-Y INSTR] {symbol} step3 placeOrder(parent) START t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            parent_trade = self._ib.placeOrder(contract, parent_o)
            print(f"[BUG-Y INSTR] {symbol} step3 placeOrder(parent) DONE  t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            print(f"[BUG-Y INSTR] {symbol} step4 placeOrder(target) START t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            target_trade = self._ib.placeOrder(contract, take_profit_o)
            print(f"[BUG-Y INSTR] {symbol} step4 placeOrder(target) DONE  t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            print(f"[BUG-Y INSTR] {symbol} step5 placeOrder(stop) START t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            stop_trade = self._ib.placeOrder(contract, stop_loss_o)
            print(f"[BUG-Y INSTR] {symbol} step5 placeOrder(stop) DONE  t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)

            # Brief settle so the parent's orderStatus callback fires
            # at least to 'PendingSubmit' or 'Submitted'. We do NOT wait
            # for a fill — that's the caller's job via order_status
            # event or naked_position_sweep.
            #
            # v19.34.28 L3-hotfix1 (2026-05-18) — replaced
            # asyncio.to_thread(self._ib.sleep, 0.5) with plain
            # asyncio.sleep(0.5). ib_async's IB.sleep() internally
            # calls loop.run_until_complete(...) on the MAIN event loop.
            # Running it from a worker thread (via asyncio.to_thread)
            # caused wedge-watchdog trips: the worker tried to drive a
            # loop the main thread owns. Plain asyncio.sleep is the
            # correct cooperative yield. Forensic fingerprint that pinned
            # the bug: wedge duration == wait_for_submission_s (5.0s)
            # exactly — i.e. the wait_for timeout itself was the longest
            # the main loop could stay un-pumped.
            print(f"[BUG-Y INSTR] {symbol} step6 settle-sleep START t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            await asyncio.sleep(0.5)
            print(f"[BUG-Y INSTR] {symbol} step6 settle-sleep DONE  t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)

            print(f"[BUG-Y INSTR] {symbol} step7 read orderIds+orderStatus START t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            entry_id = int(parent_trade.order.orderId)
            stop_id = int(stop_trade.order.orderId)
            target_id = int(target_trade.order.orderId)
            oca_group = parent_o.ocaGroup or f"oca-{entry_id}"

            # Snapshot current parent status. Could be PendingSubmit,
            # Submitted, Filled, Cancelled.
            parent_status = (
                parent_trade.orderStatus.status
                if parent_trade.orderStatus
                else "submitted"
            ).lower()
            filled_qty = int(parent_trade.orderStatus.filled or 0) if parent_trade.orderStatus else 0
            avg_fill = (
                float(parent_trade.orderStatus.avgFillPrice or 0.0)
                if parent_trade.orderStatus else 0.0
            )

            # Map IB status → contract's status field.
            if parent_status == "filled":
                status_out = "filled"
            elif parent_status in ("cancelled", "apicancelled", "inactive"):
                status_out = "rejected"
            else:
                status_out = "submitted"

            logger.info(
                "[v19.34.27 PATCH-L1] place_bracket_order via ib_direct: "
                "%s %s qty=%d entry@%.4f stop@%.4f target@%.4f → "
                "entry_id=%d stop_id=%d target_id=%d oca=%s status=%s",
                symbol, parent_action, qty, entry_price, stop_price, target_price,
                entry_id, stop_id, target_id, oca_group, status_out,
            )

            print(f"[BUG-Y INSTR] {symbol} step7 read orderIds+orderStatus DONE t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            print(f"[BUG-Y INSTR] {symbol} step8 RETURN success t={_bug_y_t.monotonic()-_t0:.3f}", flush=True)
            return {
                "success": True,
                "entry_order_id": entry_id,
                "stop_order_id": stop_id,
                "target_order_id": target_id,
                "oca_group": oca_group,
                "status": status_out,
                "fill_price": avg_fill if filled_qty else None,
                "filled_qty": filled_qty,
                "broker": "ib_direct",
                "simulated": False,
            }
        except Exception as e:
            logger.error(
                "[v19.34.27 PATCH-L1] place_bracket_order failed for %s: %s",
                getattr(trade, "symbol", "?"), e,
            )
            return {
                "success": False,
                "error": f"ib_direct_bracket_error: {str(e)[:200]}",
                "broker": "ib_direct",
                "simulated": False,
            }

    # v19.34.37 — Two-step bracket helper
    async def _place_bracket_two_step(
        self, *, trade, symbol, direction, qty, entry_price, stop_price,
        target_price, parent_action, child_action, sec_type, exchange,
        currency, parent_timeout_s,
    ):
        """Safe two-step bracket: parent LMT alone first, then OCA
        stop+target sized to actual filled qty. Fixes wrong-direction
        phantoms (2026-05-19 incident)."""
        import time as _t
        try:
            contract = Stock(symbol, exchange, currency)
            await self._ib.qualifyContractsAsync(contract)

            # v19.34.39 — Fresh-price re-check at submit time.
            # Fetches LIVE market price from IB; if entry_price has drifted
            # > threshold% (alert went stale between scan & submit), abort.
            # Universal fix for all setups — no setup-level changes needed.
            import os as _os39
            try:
                _band_pct39 = float(_os39.environ.get('IB_ENTRY_PRICE_BAND_PCT', '2.5'))
            except Exception:
                _band_pct39 = 2.5
            _live_px = 0.0
            try:
                _tickers = await self._ib.reqTickersAsync(contract)
                if _tickers:
                    _tk = _tickers[0]
                    _live_px = float(_tk.marketPrice() or 0) or float(getattr(_tk, "last", 0) or 0) or float(getattr(_tk, "close", 0) or 0)
            except Exception as _px_err:
                logger.warning(
                    "[v19.34.39 live-price] %s could not fetch live price: %s — proceeding without guard.",
                    symbol, _px_err,
                )
            if _live_px > 0 and _band_pct39 > 0:
                _dev_pct = abs(entry_price - _live_px) / _live_px * 100.0
                if _dev_pct > _band_pct39:
                    logger.warning(
                        "[v19.34.39 live-price] %s REJECTED at submit: entry=$%.4f is %.2f%% from LIVE $%.4f (threshold %.2f%%). Alert stale — skip.",
                        symbol, entry_price, _dev_pct, _live_px, _band_pct39,
                    )
                    return {
                        "success": False,
                        "error": f"alert_stale:{_dev_pct:.2f}pct_from_live_market",
                        "entry_order_id": None, "stop_order_id": None,
                        "target_order_id": None, "oca_group": None,
                        "status": "rejected_stale_alert",
                        "fill_price": None, "filled_qty": 0,
                        "broker": "ib_direct", "simulated": False,
                        "current_price": _live_px, "entry_price": entry_price,
                        "deviation_pct": _dev_pct, "threshold_pct": _band_pct39,
                    }

            # v19.34.42 -- round entry to IB minTick.
            _mt_p = await self._resolve_min_tick(contract)
            parent_order = LimitOrder(parent_action, qty,
                                      self._round_to_tick(entry_price, _mt_p))
            try:
                parent_order.tif = "DAY"
                parent_order.transmit = True
            except Exception:
                pass
            parent_trade = self._ib.placeOrder(contract, parent_order)
            entry_id = int(parent_trade.order.orderId)
            logger.warning(
                "[v19.34.37 two-step] %s parent submitted: %s qty=%d LMT@%.4f id=%d timeout=%.1fs",
                symbol, parent_action, qty, entry_price, entry_id, parent_timeout_s,
            )

            deadline = _t.monotonic() + parent_timeout_s
            last_status = ""
            terminal_status = None
            filled_qty = 0
            avg_fill = 0.0
            while _t.monotonic() < deadline:
                st_obj = parent_trade.orderStatus
                status = (getattr(st_obj, "status", "") or "").lower()
                filled_qty = int(getattr(st_obj, "filled", 0) or 0)
                avg_fill = float(getattr(st_obj, "avgFillPrice", 0.0) or 0.0)
                if status != last_status:
                    logger.warning(
                        "[v19.34.37 two-step] %s parent status=%s filled=%d/%d",
                        symbol, status, filled_qty, qty,
                    )
                    last_status = status
                if status == "filled" and filled_qty > 0:
                    terminal_status = "filled"; break
                if status in ("cancelled", "apicancelled", "inactive"):
                    terminal_status = status; break
                await asyncio.sleep(0.5)

            if terminal_status != "filled" or filled_qty <= 0:
                try:
                    if terminal_status not in ("cancelled", "apicancelled", "inactive"):
                        self._ib.cancelOrder(parent_order)
                        logger.warning(
                            "[v19.34.37 two-step] %s parent timed out (status=%s filled=%d/%d) cancelled.",
                            symbol, terminal_status or "timeout", filled_qty, qty,
                        )
                except Exception as _e:
                    logger.error("[v19.34.37 two-step] %s cancel failed: %s", symbol, _e)
                return {
                    "success": False,
                    "error": f"parent_not_filled:{terminal_status or 'timeout'}",
                    "entry_order_id": entry_id, "stop_order_id": None,
                    "target_order_id": None, "oca_group": None,
                    "status": "rejected" if terminal_status in ("cancelled", "apicancelled", "inactive") else "timeout",
                    "fill_price": None, "filled_qty": filled_qty,
                    "broker": "ib_direct", "simulated": False,
                }

            if filled_qty != qty:
                logger.warning(
                    "[v19.34.37 two-step] %s PARTIAL parent fill %d/%d — sizing brackets to %d.",
                    symbol, filled_qty, qty, filled_qty,
                )
            _orig_shares = trade.shares
            trade.shares = filled_qty
            try:
                oca_result = await self.place_oca_stop_target(
                    trade, time_in_force="GTC", outside_rth=False,
                    sec_type=sec_type, exchange=exchange, currency=currency,
                )
            finally:
                trade.shares = _orig_shares

            if not oca_result.get("success"):
                logger.critical(
                    "[v19.34.37 two-step] %s parent FILLED (%dsh) but OCA attach failed: %s. NAKED.",
                    symbol, filled_qty, oca_result.get("error"),
                )
                return {
                    "success": True, "entry_order_id": entry_id,
                    "stop_order_id": None, "target_order_id": None,
                    "oca_group": None, "status": "filled_naked_brackets_missing",
                    "fill_price": avg_fill, "filled_qty": filled_qty,
                    "broker": "ib_direct", "simulated": False,
                    "errors": [oca_result.get("error", "oca_attach_failed")],
                }

            logger.warning(
                "[v19.34.37 two-step] %s COMPLETE entry=%d filled=%d@%.4f stop=%s target=%s oca=%s",
                symbol, entry_id, filled_qty, avg_fill,
                oca_result.get("stop_order_id"), oca_result.get("target_order_id"),
                oca_result.get("oca_group"),
            )
            return {
                "success": True, "entry_order_id": entry_id,
                "stop_order_id": oca_result.get("stop_order_id"),
                "target_order_id": oca_result.get("target_order_id"),
                "oca_group": oca_result.get("oca_group"),
                "status": "filled", "fill_price": avg_fill,
                "filled_qty": filled_qty, "broker": "ib_direct",
                "simulated": False, "partial_fill": filled_qty < qty,
            }
        except Exception as e:
            logger.error("[v19.34.37 two-step] failed for %s: %s", symbol, e)
            return {
                "success": False,
                "error": f"ib_direct_two_step_bracket_error: {str(e)[:200]}",
                "broker": "ib_direct", "simulated": False,
            }

    # ── v19.34.28 Patch L2a — Native ib-direct order placement (rest of family) ──
    #
    # L1 shipped `place_bracket_order`. L2a adds the remaining four
    # write-paths and two read-paths needed to fully replace the
    # Windows pusher's order RPC. All callers stay env-var gated by
    # BOT_ORDER_PATH in trade_executor_service so default behaviour
    # is unchanged until the operator flips the env var.
    #
    # Shared contract (drop-in compatibility with the pusher-RPC paths):
    #   - Returns {"success": bool, ...broker-specific fields...}
    #   - On socket failure / unauthorized → success=False with diagnostic
    #     error code (NO simulated fallback — Patch J contract).
    #   - "broker": "ib_direct", "simulated": False on every success.

    async def place_entry(
        self,
        trade,
        *,
        order_type: str = "LMT",
        limit_price: Optional[float] = None,
        time_in_force: str = "DAY",
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
        wait_for_fill_s: float = 10.0,
    ) -> Dict[str, Any]:
        """v19.34.28 L2a — Single-order entry (no brackets, no children).

        Mirrors the legacy `_ib_entry` pusher path. Used when the caller
        opts for the two-step entry+stop flow (vs the atomic bracket
        flow). The caller has already computed `order_type`,
        `limit_price` and `time_in_force` per setup style.

        Returns a dict shaped like the pusher's `_ib_entry` return:
          {success, order_id, ib_order_id, fill_price, filled_qty,
           status, broker, order_type, routing, simulated}
        """
        if not await self.ensure_connected():
            return {"success": False, "error": "ib_direct_not_connected",
                    "broker": "ib_direct", "simulated": False}
        if self.config.read_only:
            return {"success": False, "error": "ib_direct_read_only_mode",
                    "broker": "ib_direct", "simulated": False}
        if not self.is_authorized_to_trade():
            return {"success": False,
                    "error": "ib_direct_not_authorized_managed_accounts_empty",
                    "broker": "ib_direct", "simulated": False}

        try:
            symbol = str(trade.symbol).upper()
            direction = (getattr(trade.direction, "value", None)
                         or str(trade.direction)).lower()
            if direction not in ("long", "short"):
                return {"success": False, "error": f"bad direction: {direction}",
                        "broker": "ib_direct", "simulated": False}
            qty = int(trade.shares)
            if qty <= 0:
                return {"success": False, "error": f"bad shares: {qty}",
                        "broker": "ib_direct", "simulated": False}
            action = "BUY" if direction == "long" else "SELL"
            order_type_u = (order_type or "LMT").upper()
            tif_u = (time_in_force or "DAY").upper()
        except Exception as e:
            return {"success": False, "error": f"bad trade fields: {e}",
                    "broker": "ib_direct", "simulated": False}

        try:
            contract = Stock(symbol, exchange, currency)
            # v19.34.28 Bug Y (2026-05-18) — replaced asyncio.to_thread wrapper.
            # Same deadlock pattern as L3-hotfix1: ib_async's qualifyContracts
            # internally calls loop.run_until_complete() on the main event
            # loop. Dispatching via to_thread causes the worker thread to
            # try to drive a loop the main thread owns → deadlock.
            # The async coroutine equivalent is qualifyContractsAsync.
            await self._ib.qualifyContractsAsync(contract)

            if order_type_u == "MKT":
                order = MarketOrder(action, qty)
            else:
                if limit_price is None:
                    return {"success": False,
                            "error": "limit_price required for non-MKT order",
                            "broker": "ib_direct", "simulated": False}
                # v19.34.42 -- round limit price to IB minTick.
                min_tick_e = await self._resolve_min_tick(contract)
                order = LimitOrder(action, qty,
                                   self._round_to_tick(float(limit_price), min_tick_e))
            try:
                order.tif = tif_u
            except Exception:
                pass

            entry_trade = self._ib.placeOrder(contract, order)

            # Brief wait for `orderStatus` callback. We don't loop on fill —
            # the caller's manage loop will pick it up if it's still working.
            # v19.34.28 L3-hotfix1 (2026-05-18) — same fix as place_bracket_order:
            # replaced asyncio.to_thread(self._ib.sleep, ...) wedge with
            # plain asyncio.sleep. See place_bracket_order for full rationale.
            await asyncio.sleep(0.5)

            status_obj = entry_trade.orderStatus
            ib_order_id = int(entry_trade.order.orderId)
            ib_status = (status_obj.status if status_obj else "submitted").lower()
            filled_qty = int(status_obj.filled or 0) if status_obj else 0
            avg_fill = float(status_obj.avgFillPrice or 0.0) if status_obj else 0.0

            if ib_status == "filled":
                status_out = "filled"
            elif ib_status in ("cancelled", "apicancelled", "inactive", "rejected"):
                status_out = "rejected"
            elif filled_qty > 0 and filled_qty < qty:
                status_out = "partial"
            else:
                status_out = "submitted"

            logger.info(
                "[v19.34.28 PATCH-L2a] place_entry via ib_direct: %s %s qty=%d "
                "type=%s lmt=%s tif=%s → order_id=%d status=%s",
                symbol, action, qty, order_type_u, limit_price, tif_u,
                ib_order_id, status_out,
            )

            return {
                "success": status_out != "rejected",
                "order_id": ib_order_id,
                "ib_order_id": ib_order_id,
                "fill_price": avg_fill if filled_qty else None,
                "filled_qty": filled_qty,
                "remaining_qty": max(0, qty - filled_qty),
                "status": status_out,
                "broker": "ib_direct",
                "order_type": order_type_u,
                "routing": "SMART",
                "simulated": False,
            }
        except Exception as e:
            logger.error(
                "[v19.34.28 PATCH-L2a] place_entry failed for %s: %s",
                getattr(trade, "symbol", "?"), e,
            )
            return {"success": False,
                    "error": f"ib_direct_entry_error: {str(e)[:200]}",
                    "broker": "ib_direct", "simulated": False}

    async def place_stop(
        self,
        trade,
        *,
        time_in_force: str = "GTC",
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """v19.34.28 L2a — Standalone STP order (no OCA, no target).

        Mirrors legacy `_ib_stop`. Used by the two-step entry+stop flow
        after the entry has filled. Does NOT wait for fill — stops are
        resting orders.

        Returns: {success, order_id, stop_price, broker, simulated, status}
        """
        if not await self.ensure_connected():
            return {"success": False, "error": "ib_direct_not_connected",
                    "broker": "ib_direct", "simulated": False}
        if self.config.read_only:
            return {"success": False, "error": "ib_direct_read_only_mode",
                    "broker": "ib_direct", "simulated": False}
        if not self.is_authorized_to_trade():
            return {"success": False,
                    "error": "ib_direct_not_authorized_managed_accounts_empty",
                    "broker": "ib_direct", "simulated": False}

        try:
            symbol = str(trade.symbol).upper()
            direction = (getattr(trade.direction, "value", None)
                         or str(trade.direction)).lower()
            if direction not in ("long", "short"):
                return {"success": False, "error": f"bad direction: {direction}",
                        "broker": "ib_direct", "simulated": False}
            qty = int(trade.shares)
            if qty <= 0:
                return {"success": False, "error": f"bad shares: {qty}",
                        "broker": "ib_direct", "simulated": False}
            stop_px = float(trade.stop_price)
            # Stop is OPPOSITE side of the entry.
            action = "SELL" if direction == "long" else "BUY"
        except Exception as e:
            return {"success": False, "error": f"bad trade fields: {e}",
                    "broker": "ib_direct", "simulated": False}

        try:
            contract = Stock(symbol, exchange, currency)
            # v19.34.28 Bug Y (2026-05-18) — replaced asyncio.to_thread wrapper.
            # Same deadlock pattern as L3-hotfix1: ib_async's qualifyContracts
            # internally calls loop.run_until_complete() on the main event
            # loop. Dispatching via to_thread causes the worker thread to
            # try to drive a loop the main thread owns → deadlock.
            # The async coroutine equivalent is qualifyContractsAsync.
            await self._ib.qualifyContractsAsync(contract)
            # v19.34.42 -- round stop price to IB minTick.
            min_tick = await self._resolve_min_tick(contract)
            order = StopOrder(action, qty, self._round_to_tick(stop_px, min_tick))
            try:
                order.tif = (time_in_force or "GTC").upper()
            except Exception:
                pass
            stop_trade = self._ib.placeOrder(contract, order)
            stop_id = int(stop_trade.order.orderId)
            logger.info(
                "[v19.34.28 PATCH-L2a] place_stop via ib_direct: %s %s qty=%d "
                "stop@%.4f tif=%s → order_id=%d",
                symbol, action, qty, stop_px, time_in_force, stop_id,
            )
            return {
                "success": True,
                "order_id": stop_id,
                "stop_price": stop_px,
                "broker": "ib_direct",
                "simulated": False,
                "status": "submitted",
            }
        except Exception as e:
            logger.error(
                "[v19.34.28 PATCH-L2a] place_stop failed for %s: %s",
                getattr(trade, "symbol", "?"), e,
            )
            return {"success": False,
                    "error": f"ib_direct_stop_error: {str(e)[:200]}",
                    "broker": "ib_direct", "simulated": False}

    async def place_oca_stop_target(
        self,
        trade,
        *,
        time_in_force: str = "GTC",
        outside_rth: bool = False,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """v19.34.28 L2a — Attach OCA-linked STP+LMT to ALREADY-FILLED position.

        Mirrors legacy `attach_oca_stop_target`. No parent entry submitted
        (the position already exists at IB). The STP and LMT share an
        OCA group so IB auto-cancels the survivor when one fills.

        Failure semantics match the pusher path:
          - If STP submit fails → abort; LMT NOT submitted.
          - If LMT submit fails AFTER STP succeeded → return partial=True
            so the operator knows the stop is live but target is missing.

        Returns: {success, stop_order_id, target_order_id, oca_group,
                  stop_price, target_price, errors, broker, simulated, partial}
        """
        import uuid as _uuid
        if not await self.ensure_connected():
            return {"success": False, "error": "ib_direct_not_connected",
                    "broker": "ib_direct", "simulated": False}
        if self.config.read_only:
            return {"success": False, "error": "ib_direct_read_only_mode",
                    "broker": "ib_direct", "simulated": False}
        if not self.is_authorized_to_trade():
            return {"success": False,
                    "error": "ib_direct_not_authorized_managed_accounts_empty",
                    "broker": "ib_direct", "simulated": False}

        try:
            symbol = str(trade.symbol).upper()
            direction = (getattr(trade.direction, "value", None)
                         or str(trade.direction)).lower()
            if direction not in ("long", "short"):
                return {"success": False, "error": f"bad direction: {direction}",
                        "broker": "ib_direct", "simulated": False}
            qty = int(trade.shares)
            if qty <= 0:
                return {"success": False, "error": f"bad shares: {qty}",
                        "broker": "ib_direct", "simulated": False}
            stop_px = float(trade.stop_price)
            targets = getattr(trade, "target_prices", None) or []
            if not targets:
                return {"success": False, "error": "no target_prices on trade",
                        "broker": "ib_direct", "simulated": False}
            target_px = float(targets[0])
            # Exit side: opposite of entry.
            action = "SELL" if direction == "long" else "BUY"
            tif_u = (time_in_force or "GTC").upper()
            oca_group = f"ADOPT-OCA-{symbol}-{getattr(trade, 'id', 'x')}-{_uuid.uuid4().hex[:6]}"
        except Exception as e:
            return {"success": False, "error": f"bad trade fields: {e}",
                    "broker": "ib_direct", "simulated": False}

        try:
            contract = Stock(symbol, exchange, currency)
            # v19.34.28 Bug Y (2026-05-18) — replaced asyncio.to_thread wrapper.
            # Same deadlock pattern as L3-hotfix1: ib_async's qualifyContracts
            # internally calls loop.run_until_complete() on the main event
            # loop. Dispatching via to_thread causes the worker thread to
            # try to drive a loop the main thread owns → deadlock.
            # The async coroutine equivalent is qualifyContractsAsync.
            await self._ib.qualifyContractsAsync(contract)
            # v19.34.42 -- round stop & target to IB minTick.
            min_tick = await self._resolve_min_tick(contract)
            stop_px = self._round_to_tick(stop_px, min_tick)
            target_px = self._round_to_tick(target_px, min_tick)

            # 1) STP first. Refuse to submit target if stop fails — one-sided
            # exposure (target only, no stop) can flip the position on fill.
            stop_id = None
            try:
                stop_order = StopOrder(action, qty, stop_px)
                try:
                    stop_order.tif = tif_u
                    stop_order.ocaGroup = oca_group
                    stop_order.ocaType = 1  # CANCEL_WITH_BLOCK — IB auto-cancels survivor on fill
                    if outside_rth:
                        stop_order.outsideRth = True
                except Exception:
                    pass
                stop_trade = self._ib.placeOrder(contract, stop_order)
                stop_id = int(stop_trade.order.orderId)
            except Exception as e:
                logger.error(
                    "[v19.34.28 PATCH-L2a] place_oca_stop_target: STP submit "
                    "failed for %s: %s — target intentionally NOT submitted.",
                    symbol, e,
                )
                return {
                    "success": False,
                    "error": f"stop_submit_failed: {str(e)[:200]}",
                    "stop_order_id": None,
                    "target_order_id": None,
                    "oca_group": oca_group,
                    "broker": "ib_direct",
                    "simulated": False,
                }

            # 2) LMT target sharing the same OCA group.
            target_id = None
            target_error = None
            try:
                target_order = LimitOrder(action, qty, target_px)
                try:
                    target_order.tif = tif_u
                    target_order.ocaGroup = oca_group
                    target_order.ocaType = 1
                    if outside_rth:
                        target_order.outsideRth = True
                except Exception:
                    pass
                target_trade = self._ib.placeOrder(contract, target_order)
                target_id = int(target_trade.order.orderId)
            except Exception as e:
                target_error = str(e)[:200]
                logger.error(
                    "[v19.34.28 PATCH-L2a] place_oca_stop_target: LMT submit "
                    "failed for %s: %s. STP is live (%s) but target MISSING.",
                    symbol, e, stop_id,
                )

            logger.warning(
                "[v19.34.28 PATCH-L2a ADOPT-OCA] %s trade=%s: stop=%s ($%.2f) "
                "+ target=%s ($%.2f) oca=%s",
                symbol, getattr(trade, "id", "?"), stop_id, stop_px,
                target_id or "FAILED", target_px, oca_group,
            )

            return {
                "success": True,
                "stop_order_id": stop_id,
                "target_order_id": target_id,
                "stop_price": stop_px,
                "target_price": target_px,
                "oca_group": oca_group,
                "errors": [target_error] if target_error else [],
                "broker": "ib_direct",
                "simulated": False,
                "partial": target_id is None,
            }
        except Exception as e:
            logger.error(
                "[v19.34.28 PATCH-L2a] place_oca_stop_target failed for %s: %s",
                getattr(trade, "symbol", "?"), e,
            )
            return {"success": False,
                    "error": f"ib_direct_oca_error: {str(e)[:200]}",
                    "broker": "ib_direct", "simulated": False}

    # ── L2a read paths — fresh, authoritative state queries ──

    async def get_positions_fresh(self) -> List[Dict[str, Any]]:
        """v19.34.28 L2a — Force a fresh position pull from IB Gateway.

        Mitigates the ib_async event-driven cache staleness bug
        (Bug #3 in IB_DIRECT_MIGRATION_PLAN.md): if a position event
        is missed during a reconnect, `self._ib.positions()` returns
        stale data forever until another event arrives. This method
        cancels the position subscription and re-requests, awaiting the
        full re-broadcast before returning.

        Cost: one extra round-trip to IB Gateway per call (~50-200ms
        on local network). Callers should NOT poll this every scan —
        use sparingly (post-close, post-fill, periodic reconciler).
        """
        if not await self.ensure_connected():
            return []
        try:
            # cancelPositions clears the in-flight subscription; the next
            # reqPositions / reqPositionsAsync re-establishes it and the
            # event handlers refill the cache from scratch.
            try:
                await asyncio.to_thread(self._ib.cancelPositions)
            except Exception:
                pass
            # ib_async exposes reqPositionsAsync that returns the full
            # current snapshot when the subscription is reseeded.
            positions = None
            try:
                positions = await self._ib.reqPositionsAsync()
            except AttributeError:
                # Older ib_async builds — fall back to sync re-request +
                # a brief settle, then read the freshly-populated cache.
                await asyncio.to_thread(self._ib.reqPositions)
                await asyncio.sleep(0.5)
                positions = self._ib.positions()

            out: List[Dict[str, Any]] = []
            for p in positions or []:
                try:
                    out.append({
                        "account":   p.account,
                        "symbol":    p.contract.symbol if p.contract else None,
                        "sec_type":  p.contract.secType if p.contract else None,
                        "exchange":  p.contract.exchange if p.contract else None,
                        "position":  float(p.position),
                        "avg_cost":  float(p.avgCost),
                        "fresh":     True,
                    })
                except Exception:
                    continue
            return out
        except Exception as e:
            logger.error("[v19.34.28 PATCH-L2a] get_positions_fresh failed: %s", e)
            return []

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        """v19.34.28 L2a — Authoritative working-orders snapshot.

        Pulls ALL open orders on the account (every clientId) via
        `reqAllOpenOrders`, then enumerates `_ib.trades()`. Drop-in
        replacement for `_pushed_ib_data["orders"]` in the
        naked_position_sweep / working-order audit paths.

        Returns: list of {order_id, perm_id, symbol, action, qty,
                          order_type, limit_price, stop_price,
                          tif, oca_group, status, filled, remaining}
        """
        if not await self.ensure_connected():
            return []
        try:
            try:
                await asyncio.to_thread(self._ib.reqAllOpenOrders)
                # Brief settle for openOrder callbacks to land in cache.
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(
                    "[v19.34.28 PATCH-L2a] get_open_orders reqAllOpenOrders "
                    "soft-failed (continuing with cached trades): %s", e,
                )
            out: List[Dict[str, Any]] = []
            for t in list(self._ib.trades() or []):
                try:
                    o = t.order
                    s = t.orderStatus
                    c = t.contract
                    # isActive=False means filled / cancelled / rejected.
                    try:
                        is_active = bool(t.isActive())
                    except Exception:
                        is_active = True
                    if not is_active:
                        continue
                    out.append({
                        "order_id":   int(o.orderId),
                        "perm_id":    int(getattr(o, "permId", 0) or 0),
                        "symbol":     getattr(c, "symbol", None),
                        "sec_type":   getattr(c, "secType", None),
                        "action":     getattr(o, "action", None),
                        "qty":        float(getattr(o, "totalQuantity", 0) or 0),
                        "order_type": getattr(o, "orderType", None),
                        "limit_price": float(getattr(o, "lmtPrice", 0) or 0) or None,
                        "stop_price":  float(getattr(o, "auxPrice", 0) or 0) or None,
                        "tif":        getattr(o, "tif", None),
                        "oca_group":  getattr(o, "ocaGroup", None) or None,
                        "status":     getattr(s, "status", None) if s else None,
                        "filled":     float(getattr(s, "filled", 0) or 0) if s else 0.0,
                        "remaining":  float(getattr(s, "remaining", 0) or 0) if s else 0.0,
                    })
                except Exception:
                    continue
            return out
        except Exception as e:
            logger.error("[v19.34.28 PATCH-L2a] get_open_orders failed: %s", e)
            return []

    async def get_account_summary(self) -> Dict[str, Any]:
        """v19.34.28 L2a — Authoritative account summary from IB Gateway.

        Direct replacement for `_pushed_ib_data["account_fields"]` in
        the account_guard / P&L panels. Returns a flat dict keyed by
        IB field tag (NetLiquidation, BuyingPower, etc.) with values
        as floats where parseable, else strings.

        Returns: {success, account, fields: {tag: value, ...},
                  managed_accounts, fetched_at}
        """
        if not await self.ensure_connected():
            return {"success": False, "error": "ib_direct_not_connected",
                    "fields": {}, "managed_accounts": []}
        try:
            managed = list(self._ib.managedAccounts() or [])
            account = managed[0] if managed else ""
            fields: Dict[str, Any] = {}
            # `accountSummaryAsync` returns a list of AccountValue tuples.
            try:
                rows = await self._ib.accountSummaryAsync(account or "")
            except AttributeError:
                rows = await asyncio.to_thread(self._ib.accountSummary, account or "")
            for row in rows or []:
                tag = getattr(row, "tag", None) or (row[1] if len(row) > 1 else None)
                val = getattr(row, "value", None) or (row[2] if len(row) > 2 else None)
                if tag is None:
                    continue
                try:
                    fields[str(tag)] = float(val)
                except (TypeError, ValueError):
                    fields[str(tag)] = val
            return {
                "success": True,
                "account": account,
                "managed_accounts": managed,
                "fields": fields,
                "fetched_at": time.time(),
            }
        except Exception as e:
            logger.error("[v19.34.28 PATCH-L2a] get_account_summary failed: %s", e)
            return {"success": False, "error": str(e)[:200],
                    "fields": {}, "managed_accounts": []}

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
