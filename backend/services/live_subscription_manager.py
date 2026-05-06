"""
Live Subscription Manager — Phase 2
===================================
Ref-counted dynamic watchlist sitting in front of the Windows pusher RPC.
Multiple frontend consumers (ChartPanel, EnhancedTickerModal, Scanner top-10,
etc.) can independently subscribe to the same symbol; we only call the pusher
when ref-count crosses 0/1 boundaries, so they don't step on each other.

Why a manager and not a raw passthrough?
    * ref-counting — ChartPanel and Scanner both watching SPY shouldn't let
      one's unmount kill the other's live feed
    * heartbeat TTL — if a browser tab crashes, its subs would leak forever;
      expire stale entries after 5 minutes without renewal
    * cap enforcement — IB's client has a ~100 L1 sub ceiling; we default to
      a safety margin of 60, env-overridable via MAX_LIVE_SUBSCRIPTIONS
    * observability — single source of truth the UI + /api/live/subscriptions
      read from

All operations are sync + thread-safe via a single lock. Fast enough for the
call volumes we expect (dozens of subs/unsubs per minute, not thousands).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


DEFAULT_MAX_SUBSCRIPTIONS = 60           # safety margin under IB's ~100
DEFAULT_HEARTBEAT_TTL_SECONDS = 300      # 5 min since last touch → auto-expire
HEARTBEAT_SWEEP_SECONDS = 30             # background sweep cadence


def _max_subs() -> int:
    try:
        return max(1, int(os.environ.get("MAX_LIVE_SUBSCRIPTIONS", DEFAULT_MAX_SUBSCRIPTIONS)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_SUBSCRIPTIONS


def _ttl_seconds() -> int:
    try:
        return max(30, int(os.environ.get("LIVE_SUB_HEARTBEAT_TTL_S", DEFAULT_HEARTBEAT_TTL_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_HEARTBEAT_TTL_SECONDS


@dataclass
class _SubState:
    symbol: str
    ref_count: int = 0
    first_subscribed_at: float = field(default_factory=time.time)
    last_heartbeat_at: float = field(default_factory=time.time)
    last_unsubscribe_at: Optional[float] = None
    pusher_ok: bool = False  # did the last pusher forward succeed?

    def touch(self) -> None:
        self.last_heartbeat_at = time.time()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ref_count": self.ref_count,
            "first_subscribed_at": datetime.fromtimestamp(
                self.first_subscribed_at, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "last_heartbeat_at": datetime.fromtimestamp(
                self.last_heartbeat_at, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "pusher_ok": self.pusher_ok,
            "age_seconds": round(time.time() - self.first_subscribed_at, 2),
            "idle_seconds": round(time.time() - self.last_heartbeat_at, 2),
        }


class LiveSubscriptionManager:
    """Thread-safe ref-counted subscription manager."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: Dict[str, _SubState] = {}
        self._sweep_thread: Optional[threading.Thread] = None
        self._sweep_started = False

    # ---- public API -------------------------------------------------------

    def subscribe(self, symbol: str) -> Dict[str, Any]:
        """Increment ref-count for `symbol`. If crossing 0→1, forward to
        pusher. Returns a dict with fields {accepted, newly_subscribed,
        ref_count, active_subscriptions, reason}."""
        sym = (symbol or "").upper().strip()
        if not sym:
            return {"accepted": False, "reason": "empty_symbol"}

        from services.ib_pusher_rpc import get_pusher_rpc_client

        with self._lock:
            state = self._states.get(sym)
            if state is None:
                # New symbol — enforce cap before creating
                active = self._count_active_locked()
                if active >= _max_subs():
                    logger.warning(
                        "live_sub cap hit: active=%s, max=%s — rejecting %s",
                        active, _max_subs(), sym,
                    )
                    return {
                        "accepted": False,
                        "reason": "cap_reached",
                        "active_subscriptions": active,
                        "max_subscriptions": _max_subs(),
                    }
                state = _SubState(symbol=sym)
                self._states[sym] = state

            newly_subscribed = state.ref_count == 0
            state.ref_count += 1
            state.touch()

        # Forward to pusher OUTSIDE the lock (network I/O can be slow)
        pusher_ok = True
        if newly_subscribed:
            client = get_pusher_rpc_client()
            if client.is_configured():
                # Note: we call this sync — caller wraps in asyncio.to_thread
                resp = client._request(                              # noqa: SLF001
                    "POST", "/rpc/subscribe",
                    json_body={"symbols": [sym]},
                    timeout=6.0,
                )
                pusher_ok = bool(resp and resp.get("success"))
            else:
                pusher_ok = False

            with self._lock:
                if sym in self._states:
                    self._states[sym].pusher_ok = pusher_ok

        with self._lock:
            current = self._states.get(sym)
            rc = current.ref_count if current else 0
            active = self._count_active_locked()

        self._ensure_sweep_started()

        return {
            "accepted": True,
            "newly_subscribed": newly_subscribed,
            "ref_count": rc,
            "active_subscriptions": active,
            "pusher_ok": pusher_ok,
            "symbol": sym,
        }

    def unsubscribe(self, symbol: str) -> Dict[str, Any]:
        """Decrement ref-count. If crossing 1→0, forward unsubscribe to pusher.
        Returns {accepted, fully_unsubscribed, ref_count}."""
        sym = (symbol or "").upper().strip()
        if not sym:
            return {"accepted": False, "reason": "empty_symbol"}

        from services.ib_pusher_rpc import get_pusher_rpc_client

        with self._lock:
            state = self._states.get(sym)
            if state is None or state.ref_count <= 0:
                return {
                    "accepted": False,
                    "reason": "not_subscribed",
                    "ref_count": 0,
                    "symbol": sym,
                }
            state.ref_count -= 1
            fully = state.ref_count <= 0
            if fully:
                state.last_unsubscribe_at = time.time()
                # Keep state briefly for observability; actual removal happens
                # on next sweep or on next subscribe re-use.
                del self._states[sym]

        pusher_ok = True
        if fully:
            client = get_pusher_rpc_client()
            if client.is_configured():
                resp = client._request(                              # noqa: SLF001
                    "POST", "/rpc/unsubscribe",
                    json_body={"symbols": [sym]},
                    timeout=6.0,
                )
                pusher_ok = bool(resp and resp.get("success"))
            else:
                pusher_ok = False

        return {
            "accepted": True,
            "fully_unsubscribed": fully,
            "ref_count": 0 if fully else state.ref_count,
            "pusher_ok": pusher_ok,
            "symbol": sym,
        }

    def heartbeat(self, symbol: str) -> Dict[str, Any]:
        """Renew the last_heartbeat_at for a symbol — prevents auto-expire.
        Returns {accepted, ref_count}."""
        sym = (symbol or "").upper().strip()
        with self._lock:
            state = self._states.get(sym)
            if state is None or state.ref_count <= 0:
                return {"accepted": False, "reason": "not_subscribed", "symbol": sym}
            state.touch()
            return {"accepted": True, "ref_count": state.ref_count, "symbol": sym}

    def list_subscriptions(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active_count": self._count_active_locked(),
                "max_subscriptions": _max_subs(),
                "heartbeat_ttl_seconds": _ttl_seconds(),
                "subscriptions": [s.snapshot() for s in self._states.values()],
            }

    def sweep_expired(self, now: Optional[float] = None) -> List[str]:
        """Remove subscriptions whose last_heartbeat_at is older than TTL.
        Returns list of expired symbols. Also forwards unsubscribe to pusher
        for each."""
        from services.ib_pusher_rpc import get_pusher_rpc_client

        cutoff = (now or time.time()) - _ttl_seconds()
        expired: List[str] = []
        with self._lock:
            for sym, state in list(self._states.items()):
                if state.last_heartbeat_at < cutoff:
                    expired.append(sym)
                    del self._states[sym]

        if expired:
            logger.info("live_sub sweep: expiring %s stale subscriptions: %s",
                        len(expired), expired)
            client = get_pusher_rpc_client()
            if client.is_configured():
                client._request(                                    # noqa: SLF001
                    "POST", "/rpc/unsubscribe",
                    json_body={"symbols": expired},
                    timeout=8.0,
                )

        return expired

    # ---- internals --------------------------------------------------------

    def _count_active_locked(self) -> int:
        return sum(1 for s in self._states.values() if s.ref_count > 0)

    def _ensure_sweep_started(self) -> None:
        with self._lock:
            if self._sweep_started:
                return
            self._sweep_started = True

        def _loop():
            while True:
                try:
                    time.sleep(HEARTBEAT_SWEEP_SECONDS)
                    self.sweep_expired()
                except Exception as exc:
                    logger.warning("live_sub sweep error: %s", exc)

        t = threading.Thread(target=_loop, name="live-sub-sweep", daemon=True)
        t.start()
        self._sweep_thread = t


# Module-level singleton
_manager: Optional[LiveSubscriptionManager] = None


def get_live_subscription_manager() -> LiveSubscriptionManager:
    global _manager
    if _manager is None:
        _manager = LiveSubscriptionManager()
    return _manager


def reset_live_subscription_manager() -> None:
    """Test-only: reset singleton between test cases."""
    global _manager
    _manager = None
