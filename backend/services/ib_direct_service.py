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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ib_async is the maintained successor to ib_insync (which was archived
# in 2024 after the original maintainer passed away). Same API surface.
try:
    from ib_async import IB, Stock, MarketOrder, LimitOrder, StopOrder, StopLimitOrder, Order
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


def clamp_protective_qty(requested_qty, live_abs):
    """v19.34.235 (Part B) — clamp a protective/closing-order qty to the live
    IB position.

    Returns (qty, clamped: bool). It only ever SHRINKS the order to a
    confirmed, smaller live position (0 < live < requested); it NEVER grows
    one and NEVER touches the requested value when the live size is unknown
    (`live_abs=None`) — fail-open. This is the guard that stops a stale
    `trade.shares` (e.g. SOXX 43) from arming a closing order larger than the
    position actually holds (17) and flipping it on fill (2026-06-03).
    """
    req = int(abs(requested_qty or 0))
    if live_abs is None:
        return req, False
    live = int(abs(live_abs))
    if 0 < live < req:
        return live, True
    return req, False




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
        # ── v19.34.154 — per-order IB errorEvent capture ──────────────
        # ib_async fires `errorEvent(reqId, errorCode, errorString,
        # contract)` for every IB Error message. Pre-v154 we ignored
        # them, so an async LMT rejection (Error 201 Reg-T, 202 cancelled,
        # 203 invalid, 110 price band, etc.) silently cancelled the
        # bracket leg while `place_oca_stop_target` had already returned
        # success=True. This dict maps `reqId` (= IB orderId) to a
        # bounded list of `(error_code, error_msg, ts)` tuples. Cleared
        # opportunistically when the buffer grows past
        # `_ORDER_ERROR_CAP_PER_ORDER`. `place_oca_stop_target`'s new
        # post-place polling and the bracket-attach governor read from
        # this dict to classify rejections as permanent (e.g. Reg-T)
        # vs transient.
        self._order_errors: Dict[int, list] = {}
        self._ORDER_ERROR_CAP_PER_ORDER = 16
        self._ORDER_ERROR_RETENTION_S = 300  # 5-min ring buffer

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

    # ── v19.34.154 — order-error capture helpers ─────────────────────
    def get_order_errors(self, order_id: int, *, drain: bool = False) -> list:
        """Return errorEvent callbacks captured for this IB orderId.

        Each entry is `(error_code:int, error_msg:str, ts:float)`. If
        `drain=True`, also clears the buffer for that order so the
        caller can poll repeatedly without reprocessing old events.
        Empty list if nothing captured.
        """
        try:
            oid = int(order_id)
        except (TypeError, ValueError):
            return []
        # Best-effort retention prune: drop entries older than the
        # retention window so the per-order buffer doesn't accumulate
        # stale messages on long-lived orders (GTC stops).
        now = time.time()
        retention = float(self._ORDER_ERROR_RETENTION_S)
        buf = self._order_errors.get(oid, [])
        if buf:
            fresh = [e for e in buf if (now - e[2]) <= retention]
            if len(fresh) != len(buf):
                self._order_errors[oid] = fresh
                buf = fresh
        if not buf:
            return []
        snapshot = list(buf)
        if drain:
            self._order_errors.pop(oid, None)
        return snapshot

    def has_permanent_failure_error(self, order_id: int) -> Optional[int]:
        """Returns the IB error code if the captured error history for
        this order contains a PERMANENT-failure code, else None.

        Permanent codes (will NOT clear without operator action):
          • 201 — REG-T margin call (15-order cap / would lead to call)
          • 203 — security not available for trading (HTB restriction)
          • 320 — server error processing message (often duplicate id)
          • 321 — server error validating request (malformed order)
          • 110 — price doesn't conform to variable tick (rounding bug)
          • 103 — duplicate order id
        Other codes (200, 202, 399, etc.) are transient and may resolve.
        """
        PERMANENT_CODES = {201, 203, 320, 321, 110, 103}
        for code, _msg, _ts in self.get_order_errors(order_id):
            if code in PERMANENT_CODES:
                return code
        return None



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

                # v19.34.190 — Master-clientId config guard. The bot can only
                # cancel orders it OWNS, UNLESS its clientId matches the IB
                # Gateway's "Master API client ID" (which grants cross-session
                # / orphaned-order cancel authority). 2026-05-29: brackets
                # placed by a prior process became un-cancellable (IB Error
                # 10147 + PendingCancel→Submitted flap) after restarts, until
                # the operator set Gateway Master API client ID = 11. That
                # Gateway setting lives OUTSIDE this repo (jts.ini on the
                # Windows box) and is lost on a Gateway reinstall/reset. We
                # can't read it via the API, but we CAN warn loudly if this
                # client's id drifts from the documented master value, which
                # is the only thing that must stay in sync on our side.
                # See runbook: memory/runbooks/ib_gateway_master_clientid.md
                _expected_master = _env_int("IB_EXPECTED_MASTER_CLIENT_ID", 11)
                if self.config.client_id != _expected_master:
                    logger.warning(
                        "v19.34.190 [IB-DIRECT] ⚠️ clientId=%d != documented "
                        "Master API client ID=%d. The bot may be UNABLE to "
                        "cancel orphaned/cross-session bracket orders after a "
                        "restart (IB Error 10147). Set IB_DIRECT_CLIENT_ID=%d "
                        "AND the Gateway's Master API client ID=%d to match. "
                        "See runbook: ib_gateway_master_clientid.md",
                        self.config.client_id, _expected_master,
                        _expected_master, _expected_master,
                    )
                else:
                    logger.info(
                        "v19.34.190 [IB-DIRECT] clientId=%d matches documented "
                        "master — cross-session/orphaned-order cancels enabled "
                        "(requires Gateway Master API client ID=%d).",
                        self.config.client_id, _expected_master,
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

                # v19.34.154 — register the errorEvent handler. ib_async
                # signature: errorEvent(reqId, errorCode, errorString, contract).
                # We stash by reqId (= IB orderId) so post-place polling
                # and the bracket-attach governor can classify each
                # rejection. We DO NOT log every event here at INFO —
                # IB sprays informational codes (2104/2106/2158
                # "market data farm connection ok", etc.) that aren't
                # actionable; the governor / poll logic filters by code.
                try:
                    def _on_error(reqId, errorCode, errorString, contract=None):
                        try:
                            rid = int(reqId)
                        except (TypeError, ValueError):
                            return
                        if rid <= 0:
                            return  # Non-order error (connection-level).
                        try:
                            ec = int(errorCode)
                        except (TypeError, ValueError):
                            ec = -1
                        ts = time.time()
                        buf = self._order_errors.setdefault(rid, [])
                        buf.append((ec, str(errorString)[:240], ts))
                        # Cap per-order buffer to avoid runaway memory if
                        # an order generates a storm of error callbacks
                        # (we've observed Reg-T error 201 firing 5×/order
                        # on cancel storms).
                        if len(buf) > self._ORDER_ERROR_CAP_PER_ORDER:
                            del buf[: len(buf) - self._ORDER_ERROR_CAP_PER_ORDER]
                    self._ib.errorEvent += _on_error
                except Exception as _err_ev_err:
                    logger.warning(
                        "v19.34.154 [IB-DIRECT] could not register "
                        "errorEvent handler: %s", _err_ev_err,
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

    # ── v19.34.176 — IB-native industry / category lookup (Stage A) ──
    # Used by `sector_tag_service` to replace the Finnhub-based industry
    # fallback. IB's reqContractDetails returns a `category`/`industry`/
    # `subcategory` triple sourced from Reuters classifications. Free-form
    # strings — same shape as Finnhub — fed back through the existing
    # `_industry_to_etf` resolver, so the GICS→SPDR mapping is unchanged.
    async def get_contract_industry(self, symbol: str) -> Optional[Dict[str, str]]:
        """Return ``{'industry': str, 'category': str, 'subcategory': str}``
        for ``symbol`` via IB ``reqContractDetailsAsync``, or ``None`` on
        miss / error. Safe to call frequently — the IB call is async and
        ungated (sector tagging is a one-time-per-symbol lookup; results
        are persisted to ``symbol_adv_cache.sector`` by the caller).
        """
        if not self._connected or not self._ib:
            return None
        try:
            from ib_async import Stock
        except ImportError:
            return None
        try:
            contract = Stock(symbol.upper(), "SMART", "USD")
            details = await self._ib.reqContractDetailsAsync(contract)
            if not details:
                return None
            cd = details[0]
            out = {
                "industry":    (getattr(cd, "industry", "") or "").strip(),
                "category":    (getattr(cd, "category", "") or "").strip(),
                "subcategory": (getattr(cd, "subcategory", "") or "").strip(),
            }
            # Empty triple → useless; signal None so caller can try
            # Finnhub fallback instead of caching empty data.
            if not any(out.values()):
                return None
            return out
        except Exception as exc:
            logger.debug(
                "[v19.34.176 get_contract_industry] %s lookup failed: %s",
                symbol, exc,
            )
            return None

    async def get_fundamental_report(
        self,
        symbol: str,
        report_type: str = "ReportSnapshot",
        timeout: float = 20.0,
    ) -> Optional[str]:
        """v19.34.202 — fetch an IB Reuters fundamental XML report for ``symbol``
        via the live clientId-11 socket (``reqFundamentalDataAsync``). Returns
        the raw XML string, or ``None`` on miss / not-subscribed / error.

        ``ReportSnapshot`` (~10KB) carries valuation + ``<SharesOut
        TotalFloat=...>`` (shares-outstanding text + float attribute) — the
        cheap report the fundamentals cache uses. ``ReportsOwnership`` is
        multi-MB (thousands of holders); callers must gate it tightly. The
        legacy ``ib_service`` ReportSnapshot path is dead on this deploy
        (worker usually disconnected → all cached fundamentals came from
        Finnhub), which is why this routes through ``ib_direct`` instead.
        """
        if not self._connected or not self._ib:
            return None
        try:
            from ib_async import Stock
        except ImportError:
            return None
        try:
            contract = Stock(symbol.upper(), "SMART", "USD")
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                return None
            xml = await asyncio.wait_for(
                self._ib.reqFundamentalDataAsync(qualified[0], report_type),
                timeout=timeout,
            )
            return xml or None
        except Exception as exc:
            logger.debug(
                "[v19.34.202 get_fundamental_report] %s/%s failed: %s",
                symbol, report_type, exc,
            )
            return None

    async def get_historical_data(
        self,
        symbol: str,
        duration: str = "1 Y",
        bar_size: str = "1 day",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
        timeout: float = 60.0,
    ) -> List[Dict[str, Any]]:
        """Fetch historical bars over the LIVE ib_async socket (reqHistoricalDataAsync).

        The legacy ib_service historical path is dead on this deploy (worker
        disconnected), so IB-direct is the only working source. VIX is a CBOE
        index — a Stock contract returns 0 bars, so it's qualified as
        Index('VIX','CBOE'). Returns chronological [{date, open, high, low,
        close, volume}, ...]; empty list on miss/not-subscribed/error.
        """
        if not self._connected or not self._ib:
            return []
        try:
            from ib_async import Stock, Index
        except ImportError:
            return []
        try:
            sym_u = symbol.upper()
            # Index / market-internals instruments need an IND contract on their
            # native exchange — a Stock contract silently returns 0 bars.
            _ALIAS = {
                "TICK": "TICK-NYSE", "TICKQ": "TICK-NASD", "TICKA": "TICK-AMEX",
                "TRIN": "TRIN-NYSE", "TRINQ": "TRIN-NASD",
            }
            _INDEX = {
                "VIX": ("VIX", "CBOE"),
                "TICK-NYSE": ("TICK-NYSE", "NYSE"),
                "TICK-NASD": ("TICK-NASD", "NASDAQ"),
                "TICK-AMEX": ("TICK-AMEX", "AMEX"),
                "TRIN-NYSE": ("TRIN-NYSE", "NYSE"),
                "TRIN-NASD": ("TRIN-NASD", "NASDAQ"),
                "AD-NYSE": ("AD-NYSE", "NYSE"),
            }
            sym_u = _ALIAS.get(sym_u, sym_u)
            if sym_u in _INDEX:
                isym, iexch = _INDEX[sym_u]
                contract = Index(isym, iexch)
            else:
                contract = Stock(sym_u, "SMART", "USD")
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                return []
            bars = await asyncio.wait_for(
                self._ib.reqHistoricalDataAsync(
                    qualified[0], endDateTime="", durationStr=duration,
                    barSizeSetting=bar_size, whatToShow=what_to_show,
                    useRTH=use_rth, formatDate=1,
                ),
                timeout=timeout,
            )
            out = []
            for b in (bars or []):
                d = getattr(b, "date", None)
                out.append({
                    "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                    "open": float(b.open), "high": float(b.high),
                    "low": float(b.low), "close": float(b.close),
                    "volume": float(getattr(b, "volume", 0) or 0),
                })
            return out
        except Exception as exc:
            logger.debug("[get_historical_data] %s %s/%s failed: %s",
                         symbol, duration, bar_size, exc)
            return []



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

    # ── v19.34.153 (P0 EOD ghost-flatten) ────────────────────────────────
    # Minimal raw MKT-close path used by EOD ghost-flatten + T-2 escalation.
    # Differs from `place_close_market` in that it takes raw (symbol, qty,
    # action) — NOT a `BotTrade` object — because by definition ghost
    # positions exist at IB but NOT in `bot._open_trades`, so there is no
    # `BotTrade` to feed `place_close_market`.
    #
    # Behaviour:
    #   1. Cancel ALL working orders for the symbol (eliminates the OCA-
    #      race / Reg-T storm that broke the 4:01 PM 2026-05-XX session).
    #   2. Submit a single DAY MKT order for the requested qty/action.
    #   3. Optionally wait for terminal status (default 8s) so the caller
    #      can decide whether to escalate or alarm.
    async def place_emergency_mkt_close(
        self,
        symbol: str,
        qty: int,
        action: str,                # "BUY" (cover short) | "SELL" (close long)
        *,
        wait_for_fill_s: float = 8.0,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
        cancel_working_first: bool = True,
    ) -> Dict[str, Any]:
        """v19.34.153 — Raw emergency MKT close for ghost positions.
        Returns the same dict shape as `place_close_market`.
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

        sym = str(symbol).upper().strip()
        try:
            q = int(abs(int(qty)))
        except (TypeError, ValueError):
            return {"success": False, "error": f"bad qty: {qty}",
                    "broker": "ib_direct", "simulated": False}
        if q <= 0:
            return {"success": False, "error": f"non-positive qty: {qty}",
                    "broker": "ib_direct", "simulated": False}
        act = (action or "").upper().strip()
        if act not in ("BUY", "SELL"):
            return {"success": False, "error": f"bad action: {action}",
                    "broker": "ib_direct", "simulated": False}

        # Step 1 — cancel any working orders on this symbol so the MKT
        # doesn't collide with a half-attached bracket / dangling stop.
        cancelled_ids: List[int] = []
        if cancel_working_first:
            try:
                for t in list(self._ib.trades()):
                    try:
                        if (str(t.contract.symbol).upper() != sym):
                            continue
                        st = (t.orderStatus.status or "").lower() if t.orderStatus else ""
                        if st in ("filled", "cancelled", "apicancelled",
                                  "inactive", "rejected"):
                            continue
                        self._ib.cancelOrder(t.order)
                        cancelled_ids.append(int(t.order.orderId))
                    except Exception:
                        continue
                if cancelled_ids:
                    logger.info(
                        "[v19.34.153 EMERGENCY-MKT] %s: cancelled %d working "
                        "order(s) pre-flatten: %s",
                        sym, len(cancelled_ids), cancelled_ids,
                    )
                    # Give IB a moment to register the cancels.
                    await asyncio.sleep(0.4)
            except Exception as cancel_err:
                logger.warning(
                    "[v19.34.153 EMERGENCY-MKT] %s: pre-cancel sweep failed: %s",
                    sym, cancel_err,
                )

        # Step 2 — submit MKT.
        try:
            contract = Stock(sym, exchange, currency)
            await self._ib.qualifyContractsAsync(contract)
            order = MarketOrder(act, q)
            try:
                order.tif = "DAY"
            except Exception:
                pass
            close_trade = self._ib.placeOrder(contract, order)
            ib_order_id = int(close_trade.order.orderId)

            deadline = asyncio.get_event_loop().time() + max(0.5, float(wait_for_fill_s))
            ib_status = "submitted"
            filled_qty = 0
            avg_fill = 0.0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.25)
                status_obj = close_trade.orderStatus
                if status_obj is None:
                    continue
                ib_status = (status_obj.status or "submitted").lower()
                filled_qty = int(status_obj.filled or 0)
                avg_fill = float(status_obj.avgFillPrice or 0.0)
                if ib_status in ("filled", "cancelled", "apicancelled",
                                 "inactive", "rejected"):
                    break
                if filled_qty >= q:
                    ib_status = "filled"
                    break

            if ib_status == "filled":
                status_out, success = "filled", True
            elif ib_status in ("cancelled", "apicancelled", "inactive", "rejected"):
                status_out, success = "rejected", False
            elif 0 < filled_qty < q:
                status_out, success = "partial", True
            else:
                status_out, success = "submitted", False

            logger.warning(
                "[v19.34.153 EMERGENCY-MKT] %s %s qty=%d -> order_id=%d "
                "status=%s filled=%d avg=%.4f cancelled_pre=%s",
                sym, act, q, ib_order_id, status_out,
                filled_qty, avg_fill, cancelled_ids,
            )
            return {
                "success": success,
                "order_id": ib_order_id,
                "ib_order_id": ib_order_id,
                "fill_price": (avg_fill if filled_qty > 0 else None),
                "filled_qty": filled_qty,
                "remaining_qty": max(0, q - filled_qty),
                "status": status_out,
                "broker": "ib_direct",
                "simulated": False,
                "cancelled_pre_flatten": cancelled_ids,
                "symbol": sym,
                "action": act,
                "qty": q,
            }
        except Exception as e:
            logger.error(
                "[v19.34.153 EMERGENCY-MKT] place_emergency_mkt_close failed "
                "for %s %s %d: %s", sym, act, q, e,
            )
            return {"success": False,
                    "error": f"ib_direct_emergency_mkt_error: {str(e)[:200]}",
                    "broker": "ib_direct", "simulated": False,
                    "cancelled_pre_flatten": cancelled_ids,
                    "symbol": sym, "action": act, "qty": q}

    async def place_close_limit(
        self,
        trade,
        *,
        limit_price: float,
        wait_for_fill_s: float = 10.0,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """v19.34.72 — Native LMT-close on DGX-side ib_async socket.

        Mirrors `place_close_market` contract; differs only in that a
        LimitOrder is submitted instead of MarketOrder. Used by the V5
        Close panel when the operator wants to exit at a specific price
        (e.g., capture a small mean-reversion bounce rather than slip
        through the book).

        Hard-fails on disconnect; NEVER silent-simulates.
        Returns same dict shape as place_close_market.
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
            lmt = float(limit_price)
            if lmt <= 0:
                return {"success": False, "error": f"bad limit_price: {limit_price}",
                        "broker": "ib_direct", "simulated": False}
        except Exception:
            return {"success": False, "error": f"bad limit_price: {limit_price}",
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
            order = LimitOrder(action, qty, lmt)
            try:
                order.tif = "DAY"
            except Exception:
                pass
            close_trade_obj = self._ib.placeOrder(contract, order)
            ib_order_id = int(close_trade_obj.order.orderId)

            import asyncio as _asyncio
            deadline = _asyncio.get_event_loop().time() + max(0.5, float(wait_for_fill_s))
            ib_status = "submitted"
            filled_qty = 0
            avg_fill = 0.0
            while _asyncio.get_event_loop().time() < deadline:
                await _asyncio.sleep(0.25)
                status_obj = close_trade_obj.orderStatus
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
                # LMT partial — return success=True, caller will book the
                # filled slice. Unfilled remainder stays working at IB
                # until the LMT cancels or fills, OR caller cancels it.
                status_out, success = "partial", True
            else:
                # LMT may legitimately not fill within the wait window
                # (price never traded). Surface as "working" + success=False
                # so caller can decide whether to leave it resting or cancel.
                status_out, success = "working", False

            fill_price = avg_fill if filled_qty > 0 else None
            logger.info(
                "[v19.34.72 IB-DIRECT close_lmt] %s %s qty=%d lmt=%.4f -> "
                "order_id=%d status=%s filled=%d avg=%.4f",
                symbol, action, qty, lmt, ib_order_id, status_out,
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
                "limit_price": lmt,
                "broker": "ib_direct",
                "simulated": False,
            }
        except Exception as e:
            logger.error(
                "[v19.34.72 IB-DIRECT close_lmt] place_close_limit failed for "
                "%s: %s", getattr(trade, "symbol", "?"), e,
            )
            return {"success": False,
                    "error": f"ib_direct_close_lmt_error: {str(e)[:200]}",
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

    # ── v19.34.64 (2026-05-20) — OCA-race-safe close helpers ──────────────
    #
    # The bug this addresses: pre-v19.34.64 `_cancel_ib_bracket_orders`
    # fired cancel requests and returned immediately, then the close MKT
    # was placed. In the ~50-200ms IB-side propagation window, an OCA
    # child whose trigger price was being touched could fill before its
    # cancel registered. Both the OCA child AND the MKT close then filled
    # at IB, doubling the trade — for a short-2215 position with
    # STOP_BUY 2215 active, IB ended at LONG 2215 after BUY 4430 cleared.
    # 2026-05-20 incident: IBIT/SOFI/RBLX all direction-flipped on EOD
    # close this way; bot saw status=filled (its own MKT order DID fill)
    # and booked them CLOSED, then 2-3 min later the orphan-reconciler
    # re-adopted the inverted positions.
    #
    # These two helpers give the close path the primitives to (a) wait
    # for terminal cancel-confirmation before submitting the MKT close,
    # and (b) verify the post-close IB position is actually flat.

    async def wait_for_orders_terminal(
        self,
        order_ids: List[int],
        timeout_s: float = 4.0,
        poll_iv_s: float = 0.1,
    ) -> Dict[str, Any]:
        """v19.34.64 — Poll until every order_id reaches a terminal status.

        Terminal statuses: 'Cancelled', 'ApiCancelled', 'Filled',
        'Inactive', 'Rejected'.

        Returns a partition of the input set:
          {
            cancelled:        [oid, ...],   # safe — child stood down
            filled:           [oid, ...],   # BAD — OCA fired during wait
            other_terminal:   [oid, ...],   # rejected/inactive — also safe
            timeout:          [oid, ...],   # never reached terminal → caller
                                            # should treat as `filled` risk
            unknown:          [oid, ...],   # not in local trades cache —
                                            # may be already-cancelled and
                                            # garbage-collected → safe
          }

        Caller decision matrix:
          - if filled or timeout is non-empty → ABORT the MKT close. The
            position has likely already been exited (filled) or is at
            high risk of race (timeout). The bracket-fill will be
            ingested via the normal exec-details path.
          - if only cancelled/other_terminal/unknown → safe to submit
            close MKT; cancels confirmed by IB.
        """
        if not await self.ensure_connected():
            return {"cancelled": [], "filled": [], "other_terminal": [],
                    "timeout": list(order_ids), "unknown": []}

        target_ids = {int(oid) for oid in order_ids if oid is not None}
        if not target_ids:
            return {"cancelled": [], "filled": [], "other_terminal": [],
                    "timeout": [], "unknown": []}

        terminal_cancel = {"cancelled", "apicancelled"}
        terminal_fill = {"filled"}
        terminal_other = {"inactive", "rejected"}

        result: Dict[str, Any] = {
            "cancelled": [], "filled": [], "other_terminal": [],
            "timeout": [], "unknown": [],
        }
        pending = set(target_ids)

        deadline = asyncio.get_event_loop().time() + max(0.1, float(timeout_s))
        while pending and asyncio.get_event_loop().time() < deadline:
            try:
                trades = list(self._ib.trades())
            except Exception:
                trades = []
            trades_by_id = {int(t.order.orderId): t for t in trades
                            if t.order is not None}

            # Walk pending; if found and terminal, classify and remove.
            for oid in list(pending):
                t = trades_by_id.get(oid)
                if t is None:
                    continue  # not seen yet — keep polling
                status = (t.orderStatus.status or "").lower() if t.orderStatus else ""
                if status in terminal_cancel:
                    result["cancelled"].append(oid)
                    pending.discard(oid)
                elif status in terminal_fill:
                    result["filled"].append(oid)
                    pending.discard(oid)
                elif status in terminal_other:
                    result["other_terminal"].append(oid)
                    pending.discard(oid)
            if not pending:
                break
            await asyncio.sleep(poll_iv_s)

        # Anything still pending — partition between "never seen in trades
        # cache" (likely already cancelled & GC'd → unknown/safe) and
        # "seen but didn't reach terminal" (timeout/unsafe). We treat
        # never-seen as unknown to avoid false negatives; a non-existent
        # orderId can't fill, so it's safe in practice.
        if pending:
            try:
                trades = list(self._ib.trades())
            except Exception:
                trades = []
            trade_ids_seen = {int(t.order.orderId) for t in trades
                              if t.order is not None}
            for oid in pending:
                if oid in trade_ids_seen:
                    result["timeout"].append(oid)
                else:
                    result["unknown"].append(oid)

        return result

    async def verify_position_flat(
        self,
        symbol: str,
        expected_remaining: int = 0,
        tolerance: int = 0,
    ) -> Dict[str, Any]:
        """v19.34.64 — Post-close authoritative position check.

        After the bot's MKT close polls status=filled, this confirms
        IB's actual `positions()` for `symbol` matches the expected
        post-close remaining (default: zero / fully closed). If the
        absolute mismatch exceeds `tolerance`, the close double-filled
        (OCA + MKT both landed) and the bot's "closed" record is
        misleading.

        Returns:
          {
            is_flat:        bool,
            ib_position:    int,             # signed (+ long, - short)
            expected:       int,
            divergence:     int,             # ib_position - expected
            avg_cost:       float | None,
            checked_at:     iso8601 str,
          }
        """
        if not await self.ensure_connected():
            return {"is_flat": False, "ib_position": 0,
                    "expected": int(expected_remaining), "divergence": 0,
                    "avg_cost": None,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "error": "ib_direct_not_connected"}
        try:
            sym = str(symbol).upper()
            positions = await asyncio.to_thread(self._ib.positions)
            match = None
            for p in positions:
                if p.contract and p.contract.symbol == sym:
                    match = p
                    break
            ib_qty = int(match.position) if match else 0
            avg_cost = float(match.avgCost) if match else None
            divergence = ib_qty - int(expected_remaining)
            is_flat = abs(divergence) <= int(tolerance)
            return {
                "is_flat": is_flat,
                "ib_position": ib_qty,
                "expected": int(expected_remaining),
                "divergence": divergence,
                "avg_cost": avg_cost,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(
                "[v19.34.64 IB-DIRECT] verify_position_flat(%s) failed: %s",
                symbol, e,
            )
            return {"is_flat": False, "ib_position": 0,
                    "expected": int(expected_remaining), "divergence": 0,
                    "avg_cost": None,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(e)[:200]}

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
            # v19.34.283 — marketable-limit entry: anchor to LIVE price + a small
            # offset THROUGH the market (instead of the passive alert trigger) so
            # fast/breakout setups actually fill. Capped by IB_ENTRY_MARKETABLE_
            # SLIP_PCT (default 0.25%) so a bad print can't fill arbitrarily far.
            # Falls back to the trigger price if live is unavailable. The staleness
            # band above still skips genuinely blown setups.
            _entry_px = entry_price
            try:
                _slip = float(_os39.environ.get('IB_ENTRY_MARKETABLE_SLIP_PCT', '0.25')) / 100.0
            except Exception:
                _slip = 0.0025
            if _live_px > 0 and _slip > 0:
                _entry_px = _live_px * (1.0 + _slip) if parent_action == "BUY" else _live_px * (1.0 - _slip)
                logger.warning(
                    "[v19.34.283 marketable] %s %s marketable-limit @ %.4f (live %.4f +/- %.2f%%, trigger was %.4f)",
                    symbol, parent_action, _entry_px, _live_px, _slip * 100.0, entry_price,
                )
            parent_order = LimitOrder(parent_action, qty,
                                      self._round_to_tick(_entry_px, _mt_p))
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
                    terminal_status = "filled"
                    break
                if status in ("cancelled", "apicancelled", "inactive"):
                    terminal_status = status
                    break
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
            # v19.34.283 — preserve original $risk / R: shift stop + all targets by
            # the fill-vs-trigger delta (pure translation keeps every risk/reward
            # distance intact, multi-target scale-outs included).
            try:
                if avg_fill and avg_fill > 0 and entry_price and entry_price > 0:
                    _delta = avg_fill - entry_price
                    if abs(_delta) > 1e-9:
                        if getattr(trade, "stop_price", None):
                            trade.stop_price = round(float(trade.stop_price) + _delta, 4)
                        _tps = getattr(trade, "target_prices", None) or []
                        if _tps:
                            trade.target_prices = [round(float(t) + _delta, 4) for t in _tps]
                        logger.warning(
                            "[v19.34.283 R-preserve] %s fill=%.4f trigger=%.4f delta=%.4f -> stop=%s targets=%s",
                            symbol, avg_fill, entry_price, _delta,
                            getattr(trade, "stop_price", None), getattr(trade, "target_prices", None),
                        )
            except Exception as _ra_err:
                logger.warning("[v19.34.283 R-preserve] %s skipped: %s", symbol, _ra_err)
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
        stop_price: Optional[float] = None,
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
            elif order_type_u in ("STP", "STP_LMT", "STOP", "STOP_LIMIT"):
                # v19.34.43 -- Breakout entry. Activates only when
                # market trades through `stop_price`.
                if stop_price is None:
                    return {"success": False,
                            "error": "stop_price required for STP / STP_LMT entry",
                            "broker": "ib_direct", "simulated": False}
                min_tick = await self._resolve_min_tick(contract)
                stop_px_r = self._round_to_tick(float(stop_price), min_tick)
                if order_type_u in ("STP_LMT", "STOP_LIMIT"):
                    if limit_price is None:
                        return {"success": False,
                                "error": "limit_price required for STP_LMT entry",
                                "broker": "ib_direct", "simulated": False}
                    lmt_px_r = self._round_to_tick(float(limit_price), min_tick)
                    order = StopLimitOrder(action, qty, lmt_px_r, stop_px_r)
                else:
                    order = StopOrder(action, qty, stop_px_r)
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

    async def live_position_abs(self, symbol: str):
        """v19.34.235 (Part B) — return |live IB position| for `symbol` as an
        int, or None when it can't be read confidently (get_positions raised,
        empty snapshot, or the symbol is absent). Returning None on absence is
        deliberate: the clamp must only ever SHRINK a closing order to a
        confirmed, present position — never down to 0 on a snapshot gap."""
        try:
            positions = await self.get_positions()
        except Exception as e:
            logger.debug("[v19.34.235 clamp] get_positions failed for %s: %s", symbol, e)
            return None
        if not positions:
            return None
        s = (symbol or "").upper()
        signed = 0.0
        found = False
        for p in positions:
            if (p.get("symbol") or "").upper() == s and p.get("sec_type") in (None, "STK"):
                signed += float(p.get("position") or 0.0)
                found = True
        return int(abs(signed)) if found else None

    # ── M0 (2026-06) — laddered server-side scale-out ────────────────────
    #
    # Design (operator-approved): 3-leg OCA — 40% @ +1R, 30% @ +2R, 30%
    # "runner" with a far cap (+4R scalp / +6R intraday). Each leg is its
    # OWN OCA pair (stop_i + target_i, same qty, ocaType=1) so a target
    # fill cancels exactly its own stop and never disturbs the other
    # legs' protection. Group names keep the `ADOPT-OCA-{sym}-{trade_id}`
    # convention (+ `-L{i}` suffix) so the v322k orphan reconciler can
    # prove ownership via the embedded trade-id token.
    #
    # BE-move / trailing for the surviving legs is done by
    # services/m0_ladder_manager.py via `modify_stop_price` (in-place IB
    # order modification — same orderId, new auxPrice — which does NOT
    # cancel the OCA group).

    def _m0_ladder_plan(self, trade, qty: int, stop_px: float) -> Optional[List[Dict[str, Any]]]:
        """Pure planning: return per-leg dicts or None for legacy single pair.

        Gates (all must pass):
          • M0_LADDER_ENABLED != false  (default true)
          • trade style ∈ M0_LADDER_STYLES (default "scalp,intraday")
          • policy tp_ladder has ≥ 2 rungs
          • qty ≥ M0_LADDER_MIN_SHARES (default 10)
          • risk distance > 0
        """
        if (os.environ.get("M0_LADDER_ENABLED", "true").strip().lower()
                in ("false", "0", "no", "off")):
            return None
        styles = {
            s.strip().lower()
            for s in (os.environ.get("M0_LADDER_STYLES", "scalp,intraday")).split(",")
            if s.strip()
        }
        # M0b (2026-06-11) — STRICT style gate. get_policy_for_trade falls
        # back to DEFAULT_POLICY (intraday) when trade_style is unset, which
        # laddered an adopted CASY whose legacy fields said "swing". The
        # ladder now requires (a) an EXPLICIT trade_style in the eligible
        # set, and (b) no legacy horizon field (timeframe / trade_type /
        # scan_tier) contradicting it with a known NON-eligible style.
        _LEGACY_MAP = {"move_2_move": "scalp", "trade_2_hold": "intraday",
                       "a_plus": "multi_day", "investment": "position"}
        _KNOWN = {"scalp", "intraday", "multi_day", "swing", "position", "investment"}
        _style_raw = getattr(trade, "trade_style", None)
        _style = str(getattr(_style_raw, "value", None) or _style_raw or "").strip().lower()
        _style = _LEGACY_MAP.get(_style, _style)
        if _style not in styles:
            return None
        for _f in ("timeframe", "trade_type", "scan_tier"):
            _v_raw = getattr(trade, _f, None)
            _v = str(getattr(_v_raw, "value", None) or _v_raw or "").strip().lower()
            _v = _LEGACY_MAP.get(_v, _v)
            if _v in _KNOWN and _v not in styles:
                logger.info(
                    "[M0b] %s ladder skipped — %s=%s contradicts trade_style=%s",
                    getattr(trade, "symbol", "?"), _f, _v, _style,
                )
                return None
        from services.order_policy_registry import get_policy
        policy = get_policy(_style)
        rungs = list(policy.tp_ladder or [])
        if len(rungs) < 2:
            return None
        try:
            min_shares = int(os.environ.get("M0_LADDER_MIN_SHARES", "10") or 10)
        except (TypeError, ValueError):
            min_shares = 10
        if qty < max(min_shares, len(rungs)):
            return None

        entry = float(getattr(trade, "fill_price", 0) or 0) or float(
            getattr(trade, "entry_price", 0) or 0)
        if entry <= 0:
            return None
        risk = abs(entry - float(stop_px))
        if risk <= 0:
            return None
        direction = (getattr(trade.direction, "value", None) or str(trade.direction)).lower()
        explicit = [float(t) for t in (getattr(trade, "target_prices", None) or [])
                    if t is not None]

        # Qty split — round per rung, drop trailing zero rungs, force ≥1,
        # last rung absorbs the rounding drift so sum == qty exactly
        # (mirrors the v19.34.103 pusher-ladder accounting).
        rung_qtys = [int(round(qty * float(r.pct_of_position))) for r in rungs]
        while rung_qtys and rung_qtys[-1] == 0 and len(rung_qtys) > 1:
            rung_qtys.pop()
            rungs = rungs[: len(rung_qtys)]
        rung_qtys = [max(q, 1) for q in rung_qtys]
        drift = qty - sum(rung_qtys)
        if drift != 0:
            rung_qtys[-1] = rung_qtys[-1] + drift
        if rung_qtys[-1] < 1 or len(rungs) < 2:
            return None

        # M0a (2026-06-11) — first live session: the scanner's SINGLE far
        # target (typically ~2.5R) landed as leg 1 while legs 2-3 used
        # R-math → inverted ladders (C: L1@145.36 "1R" vs L2@143.26 2R).
        # Explicit targets are now used ONLY when the scanner supplied a
        # FULL monotonic ladder: at least as many targets as rungs, every
        # price strictly walking AWAY from entry in the trade direction.
        # Anything else → pure R-math for ALL legs.
        use_explicit = False
        if len(explicit) >= len(rungs):
            seq = explicit[: len(rungs)]
            if direction == "long":
                use_explicit = seq[0] > entry and all(
                    a < b for a, b in zip(seq, seq[1:]))
            else:
                use_explicit = seq[0] < entry and all(
                    a > b for a, b in zip(seq, seq[1:]))

        legs: List[Dict[str, Any]] = []
        for i, (rung, lq) in enumerate(zip(rungs, rung_qtys)):
            if use_explicit:
                tpx = explicit[i]
            else:
                tpx = (entry + float(rung.r_multiple) * risk if direction == "long"
                       else entry - float(rung.r_multiple) * risk)
            legs.append({
                "idx": i,
                "qty": int(lq),
                "target_px": round(float(tpx), 4),
                "r_multiple": float(rung.r_multiple),
            })
        return legs

    async def _m0_place_oca_ladder(
        self, *, trade, symbol: str, qty: int, stop_px: float,
        legs: List[Dict[str, Any]], action: str, tif_u: str,
        outside_rth: bool, exchange: str, currency: str,
    ) -> Dict[str, Any]:
        """Place the per-leg OCA pairs at IB.

        Failure semantics (same catastrophe contract as the single pair):
          • ANY stop leg fails to submit or permanent-rejects → cancel
            EVERYTHING placed, return success=False — caller treats the
            position as naked and emergency-flattens.
          • A target leg fails → its stop stays live (leg is stop-only),
            partial=True so the reconciler can re-attach later.
        """
        import uuid as _uuid
        trade_id = getattr(trade, "id", "x")
        try:
            contract = Stock(symbol, exchange, currency)
            await self._ib.qualifyContractsAsync(contract)
            min_tick = await self._resolve_min_tick(contract)
            stop_px_t = self._round_to_tick(float(stop_px), min_tick)

            placed: List[Dict[str, Any]] = []   # per-leg runtime records
            all_orders = []                      # (order_obj) for rollback

            # Phase 1 — ALL stop legs first (full protection before any TP).
            for leg in legs:
                grp = f"ADOPT-OCA-{symbol}-{trade_id}-L{leg['idx'] + 1}-{_uuid.uuid4().hex[:6]}"
                stop_order = StopOrder(action, int(leg["qty"]), stop_px_t)
                try:
                    stop_order.tif = tif_u
                    stop_order.ocaGroup = grp
                    stop_order.ocaType = 1
                    if outside_rth:
                        stop_order.outsideRth = True
                except Exception:
                    pass
                try:
                    st = self._ib.placeOrder(contract, stop_order)
                    placed.append({
                        **leg,
                        "oca_group": grp,
                        "stop_order_id": int(st.order.orderId),
                        "stop_px": stop_px_t,
                        "_stop_order": stop_order,
                        "_stop_trade": st,
                        "target_order_id": None,
                        "status": "working",
                    })
                    all_orders.append(stop_order)
                except Exception as e:
                    logger.error(
                        "[M0] %s stop leg L%d submit failed: %s — cancelling "
                        "%d already-placed leg(s); caller must flatten.",
                        symbol, leg["idx"] + 1, e, len(all_orders),
                    )
                    for o in all_orders:
                        try:
                            self._ib.cancelOrder(o)
                        except Exception:
                            pass
                    return {
                        "success": False,
                        "error": f"m0_stop_submit_failed_L{leg['idx'] + 1}: {str(e)[:160]}",
                        "stop_order_id": None, "target_order_id": None,
                        "oca_group": None, "broker": "ib_direct", "simulated": False,
                    }

            # Phase 2 — target legs (same group as their stop).
            target_errors: List[str] = []
            for rec in placed:
                tpx_t = self._round_to_tick(float(rec["target_px"]), min_tick)
                rec["target_px"] = tpx_t
                tgt_order = LimitOrder(action, int(rec["qty"]), tpx_t)
                try:
                    tgt_order.tif = tif_u
                    tgt_order.ocaGroup = rec["oca_group"]
                    tgt_order.ocaType = 1
                    if outside_rth:
                        tgt_order.outsideRth = True
                except Exception:
                    pass
                try:
                    tt = self._ib.placeOrder(contract, tgt_order)
                    rec["target_order_id"] = int(tt.order.orderId)
                    rec["_tgt_trade"] = tt
                    all_orders.append(tgt_order)
                except Exception as e:
                    target_errors.append(f"L{rec['idx'] + 1}: {str(e)[:120]}")
                    logger.error(
                        "[M0] %s target leg L%d submit failed: %s — leg is "
                        "STOP-ONLY (still protected).", symbol, rec["idx"] + 1, e,
                    )

            # Phase 3 — brief async-rejection poll (mirrors v19.34.154).
            try:
                poll_s = float(os.environ.get("IB_BRACKET_POLL_S", "1.5"))
            except (TypeError, ValueError):
                poll_s = 1.5
            deadline = asyncio.get_event_loop().time() + max(0.2, poll_s)
            stop_perm_reject = None
            while asyncio.get_event_loop().time() < deadline and stop_perm_reject is None:
                await asyncio.sleep(0.15)
                for rec in placed:
                    perm = self.has_permanent_failure_error(rec["stop_order_id"])
                    if perm is not None:
                        stop_perm_reject = (rec["idx"], perm)
                        break
            if stop_perm_reject is not None:
                _idx, _code = stop_perm_reject
                logger.critical(
                    "[M0] %s stop leg L%d PERMANENT-REJECTED (code=%s) — "
                    "cancelling whole ladder; caller must flatten.",
                    symbol, _idx + 1, _code,
                )
                for o in all_orders:
                    try:
                        self._ib.cancelOrder(o)
                    except Exception:
                        pass
                return {
                    "success": False,
                    "error": f"m0_stop_permanent_reject_L{_idx + 1}_code_{_code}",
                    "stop_order_id": None, "target_order_id": None,
                    "oca_group": None, "broker": "ib_direct", "simulated": False,
                }

            # Persist leg state ON the trade so every consumer (manage
            # loop, persistence, close/EOD cancel paths) sees it.
            clean_legs = [
                {k: v for k, v in rec.items() if not k.startswith("_")}
                for rec in placed
            ]
            try:
                if not isinstance(getattr(trade, "scale_out_config", None), dict):
                    trade.scale_out_config = {}
                trade.scale_out_config["m0_legs"] = clean_legs
                trade.scale_out_config["m0_ib_stop_px"] = stop_px_t
                trade.scale_out_config["scale_out_pcts"] = [
                    round(rec["qty"] / max(qty, 1), 4) for rec in placed
                ]
                # All child ids into target_order_ids so EVERY existing
                # close/EOD/decay cancel path (which iterates
                # stop_order_id + target_order_id + target_order_ids)
                # cancels the full ladder with zero changes.
                _extra_ids = [str(r["target_order_id"]) for r in placed
                              if r.get("target_order_id")]
                _extra_ids += [str(r["stop_order_id"]) for r in placed[1:]]
                trade.target_order_ids = _extra_ids
            except Exception as _persist_err:
                logger.warning("[M0] %s could not stamp m0_legs on trade: %s",
                               symbol, _persist_err)

            ladder_str = " ".join(
                f"L{r['idx'] + 1}:{r['qty']}@{r['target_px']}" for r in placed
            )
            logger.warning(
                "[M0 LADDER] %s trade=%s %d legs placed: stop@%.4f ×%dsh total "
                "| %s | tif=%s partial=%s",
                symbol, trade_id, len(placed), stop_px_t, qty, ladder_str,
                tif_u, bool(target_errors),
            )
            return {
                "success": True,
                "stop_order_id": placed[0]["stop_order_id"],
                "target_order_id": placed[0]["target_order_id"],
                "oca_group": placed[0]["oca_group"],
                "stop_order_ids": [r["stop_order_id"] for r in placed],
                "target_order_ids": [r["target_order_id"] for r in placed],
                "oca_groups": [r["oca_group"] for r in placed],
                "legs": clean_legs,
                "stop_price": stop_px_t,
                "target_price": placed[0]["target_px"],
                "partial": bool(target_errors),
                "errors": target_errors,
                "broker": "ib_direct",
                "simulated": False,
                "m0_ladder": True,
            }
        except Exception as e:
            logger.error("[M0] ladder placement failed for %s: %s", symbol, e)
            return {
                "success": False,
                "error": f"m0_ladder_error: {str(e)[:200]}",
                "stop_order_id": None, "target_order_id": None,
                "oca_group": None, "broker": "ib_direct", "simulated": False,
            }

    async def modify_stop_price(self, order_id: int, new_stop_px: float) -> Dict[str, Any]:
        """M0 — modify a live STP order's trigger price IN PLACE.

        Re-submits the SAME order (same orderId) with a new auxPrice —
        IB treats this as a modification, NOT a cancel/replace, so the
        order's OCA group stays intact (cancelling an OCA member would
        nuke the whole group). Used by m0_ladder_manager for BE-moves
        and runner trailing.
        """
        if not await self.ensure_connected():
            return {"success": False, "error": "ib_direct_not_connected"}
        if self.config.read_only:
            return {"success": False, "error": "ib_direct_read_only_mode"}
        if not self.is_authorized_to_trade():
            return {"success": False, "error": "ib_direct_not_authorized"}
        try:
            order_id = int(order_id)
            target = None
            for t in list(self._ib.trades() or []):
                try:
                    if int(t.order.orderId) == order_id and t.isActive():
                        target = t
                        break
                except Exception:
                    continue
            if target is None:
                return {"success": False, "error": "order_not_open",
                        "order_id": order_id}
            min_tick = await self._resolve_min_tick(target.contract)
            new_px = self._round_to_tick(float(new_stop_px), min_tick)
            old_px = float(getattr(target.order, "auxPrice", 0) or 0)
            if abs(new_px - old_px) < (min_tick or 0.01) / 2:
                return {"success": True, "order_id": order_id,
                        "unchanged": True, "stop_price": old_px}
            target.order.auxPrice = new_px
            self._ib.placeOrder(target.contract, target.order)
            logger.info("[M0 STOP-MODIFY] order=%d %.4f -> %.4f",
                        order_id, old_px, new_px)
            return {"success": True, "order_id": order_id,
                    "old_stop": old_px, "stop_price": new_px}
        except Exception as e:
            return {"success": False, "error": f"modify_failed: {str(e)[:160]}",
                    "order_id": order_id}

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
            # v19.34.235 (Part B) — clamp the protective qty to the live IB
            # position so a stale `trade.shares` can never arm a closing order
            # larger than the position holds (SOXX Sell-43-vs-17 flip hazard).
            _live_abs = await self.live_position_abs(symbol)
            qty, _did_clamp = clamp_protective_qty(qty, _live_abs)
            if _did_clamp:
                logger.warning(
                    "[v19.34.235 clamp] %s OCA protective qty %d -> %d (live IB position) "
                    "— prevented oversized closing order / flip.",
                    symbol, int(trade.shares), qty,
                )
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

        # ── M0 (2026-06) — laddered scale-out branch ─────────────────────
        # When the trade's order policy carries a multi-rung tp_ladder
        # (scalp/intraday since M0) and the position is big enough to
        # split, place PER-LEG OCA pairs instead of one full-qty pair:
        # leg_i = (stop_i, target_i) sharing their own OCA group, all at
        # the same initial stop price. A target fill cancels ONLY its own
        # leg's stop — legs 2..n stay protected; m0_ladder_manager then
        # moves the surviving stops (BE after leg 1, trail after leg 2)
        # via in-place modify. Falls through to the legacy single pair
        # when disabled / style not eligible / position too small.
        try:
            _m0_legs = self._m0_ladder_plan(trade, qty, stop_px)
        except Exception as _m0_plan_err:
            logger.warning("[M0] ladder plan failed for %s (%s) — legacy single pair",
                           symbol, _m0_plan_err)
            _m0_legs = None
        if _m0_legs:
            return await self._m0_place_oca_ladder(
                trade=trade, symbol=symbol, qty=qty, stop_px=stop_px,
                legs=_m0_legs, action=action, tif_u=tif_u,
                outside_rth=outside_rth, exchange=exchange, currency=currency,
            )

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

            # ── v19.34.154 — post-place polling for async rejections ──
            # `placeOrder` returns immediately; IB can still reject the
            # leg asynchronously (Reg-T 201, price band 110, HTB 203,
            # OCA-conflict 202, etc.) within the next ~100-2000ms. Pre-
            # v154 we ignored this window and stamped success=True with
            # both order_ids, then the reconciler later spammed
            # re-attaches when the LMT vanished. Now: poll for up to
            # `IB_BRACKET_POLL_S` (default 1.5s) checking BOTH
            # `orderStatus` and our v154 errorEvent buffer for terminal
            # rejects. Classify each leg.
            try:
                poll_s = float(os.environ.get("IB_BRACKET_POLL_S", "1.5"))
            except (TypeError, ValueError):
                poll_s = 1.5
            poll_deadline = asyncio.get_event_loop().time() + max(0.2, poll_s)

            def _leg_terminal_status(orderstatus_obj) -> Optional[str]:
                if orderstatus_obj is None:
                    return None
                st = (orderstatus_obj.status or "").lower()
                if st in ("cancelled", "apicancelled", "inactive", "rejected"):
                    return st
                return None

            stop_status = "working"
            target_status = "working" if target_id else "submit_failed"
            stop_error_code: Optional[int] = None
            target_error_code: Optional[int] = None

            while asyncio.get_event_loop().time() < poll_deadline:
                await asyncio.sleep(0.15)
                # Stop leg
                if stop_status == "working":
                    perm = self.has_permanent_failure_error(stop_id) if stop_id else None
                    term = _leg_terminal_status(getattr(stop_trade, "orderStatus", None)) if stop_id else None
                    if perm is not None:
                        stop_status = "permanent_reject"
                        stop_error_code = perm
                    elif term:
                        stop_status = f"terminal_{term}"
                # Target leg
                if target_id and target_status == "working":
                    perm = self.has_permanent_failure_error(target_id)
                    term = _leg_terminal_status(getattr(target_trade, "orderStatus", None))
                    if perm is not None:
                        target_status = "permanent_reject"
                        target_error_code = perm
                    elif term:
                        target_status = f"terminal_{term}"
                # Bail early if BOTH legs reached a non-working state.
                if stop_status != "working" and target_status not in ("working",):
                    break

            # Final classification of permanent_failure: any leg with a
            # permanent IB error code is bracket-blocking.
            permanent_failure = bool(
                stop_error_code in {201, 203, 320, 321, 110, 103}
                or target_error_code in {201, 203, 320, 321, 110, 103}
            )

            # If STP terminal-rejected, cancel the TP (don't leave a
            # one-sided target — operator choice 5B: STP-leg reject is
            # CATASTROPHIC, caller will fire emergency MKT flatten).
            if (stop_status != "working" and stop_status != "submitted"
                    and stop_status not in ("",) and target_id):
                try:
                    self._ib.cancelOrder(target_trade.order)
                    logger.error(
                        "[v19.34.154] %s: STP terminal-rejected (%s code=%s); "
                        "cancelled TP order %s to prevent one-sided exposure.",
                        symbol, stop_status, stop_error_code, target_id,
                    )
                    target_status = "cancelled_after_stop_fail"
                except Exception as ce:
                    logger.warning(
                        "[v19.34.154] %s: cancelOrder for TP after STP fail "
                        "raised: %s", symbol, ce,
                    )

            logger.warning(
                "[v19.34.154 PLACE-OCA] %s trade=%s: stop=%s ($%.2f) status=%s "
                "err=%s + target=%s ($%.2f) status=%s err=%s oca=%s "
                "permanent_failure=%s",
                symbol, getattr(trade, "id", "?"),
                stop_id, stop_px, stop_status, stop_error_code,
                target_id or "FAILED", target_px, target_status, target_error_code,
                oca_group, permanent_failure,
            )

            # success=True ONLY if STP is working AND (TP is working OR
            # target_status acknowledges a non-permanent submit-failure
            # the caller can retry). STP being terminal-rejected always
            # → success=False so reconciler emergency-flattens the
            # naked position. Use PER-LEG checks (not the global
            # permanent_failure) so a TP-only Error 201 still allows
            # the STP to live and the overall result to be partial=True.
            stp_perm = isinstance(stop_error_code, int) and stop_error_code in {201, 203, 320, 321, 110, 103}
            tgt_perm = isinstance(target_error_code, int) and target_error_code in {201, 203, 320, 321, 110, 103}
            stp_alive = stop_status == "working" and not stp_perm
            tp_alive = (target_status == "working") and not tgt_perm
            overall_success = stp_alive
            partial = stp_alive and not tp_alive

            return {
                "success": overall_success,
                "stop_order_id": stop_id,
                "target_order_id": target_id if tp_alive else None,
                "stop_price": stop_px,
                "target_price": target_px,
                "oca_group": oca_group,
                "errors": [e for e in [target_error] if e],
                "broker": "ib_direct",
                "simulated": False,
                "partial": partial,
                # v19.34.154 new fields:
                "stop_status": stop_status,
                "target_status": target_status,
                "stop_error_code": stop_error_code,
                "target_error_code": target_error_code,
                "permanent_failure": permanent_failure,
                "stop_terminal_reject": not stp_alive,
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
