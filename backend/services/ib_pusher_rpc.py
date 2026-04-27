"""
IB Pusher RPC Client (DGX side)
================================
Thin HTTP client that the DGX backend uses to ask the Windows pusher for
live/extended-hours IB data that the Windows pusher fetches via its
reqHistoricalData / reqMktData calls. This is how DGX gets bars IB hasn't
pushed yet (after-hours, weekend-of-close, or active-view symbol refreshes)
without opening its own IB connection.

Config:
    IB_PUSHER_RPC_URL  - Base URL of the pusher RPC server (e.g.
                         http://192.168.50.1:8765). Required to enable.
    ENABLE_LIVE_BAR_RPC - "true" / "false" (default "true"). Kill-switch
                          so the DGX can fall back to pure Mongo cache
                          without redeploying if the pusher RPC breaks.

Design notes:
    * Purely sync. Call from async paths via asyncio.to_thread.
    * Short timeouts (6s default) — pusher RPC path is supposed to be
      a last-mile accelerator, not a liability.
    * Single shared requests.Session for keep-alive / connection reuse.
    * Every call returns either the parsed JSON dict or None on any
      failure. Never raises. Callers must treat None as "pusher unreachable,
      fall back to cache."
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT = 6.0
_DEFAULT_LATEST_BARS_TIMEOUT = 20.0


def _is_enabled() -> bool:
    val = os.environ.get("ENABLE_LIVE_BAR_RPC", "true").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _base_url() -> Optional[str]:
    url = os.environ.get("IB_PUSHER_RPC_URL", "").strip().rstrip("/")
    return url or None


class _PusherRPCClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._lock = threading.Lock()
        # Track consecutive failures to auto-suppress noisy logs
        self._consecutive_failures = 0
        self._last_success_ts: Optional[float] = None

    # ---- internal helpers -------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        if not _is_enabled():
            return None
        base = _base_url()
        if not base:
            return None
        url = f"{base}{path}"
        try:
            with self._lock:
                resp = self._session.request(
                    method=method,
                    url=url,
                    json=json_body,
                    timeout=timeout,
                )
            if resp.status_code >= 400:
                # 404 probably means pusher RPC is deployed but this endpoint
                # is older/missing — do not spam on every fetch.
                if self._consecutive_failures < 3:
                    logger.warning(
                        "pusher RPC %s %s returned %s: %s",
                        method, path, resp.status_code, resp.text[:200],
                    )
                self._consecutive_failures += 1
                return None
            self._consecutive_failures = 0
            import time as _t
            self._last_success_ts = _t.time()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            if self._consecutive_failures < 3:
                logger.info("pusher RPC %s %s unreachable: %s", method, path, exc)
            self._consecutive_failures += 1
            return None
        except Exception as exc:
            logger.warning("pusher RPC %s %s unexpected error: %s", method, path, exc)
            self._consecutive_failures += 1
            return None

    # ---- public API -------------------------------------------------------

    def health(self) -> Optional[Dict[str, Any]]:
        return self._request("GET", "/rpc/health", timeout=3.0)

    def latest_bars(
        self,
        symbol: str,
        bar_size: str,
        duration: str = "1 D",
        use_rth: bool = False,
        what_to_show: str = "TRADES",
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Ask the pusher to run reqHistoricalData with endDateTime="" (i.e.
        "give me the current / latest-session slice"). Returns bars list
        or None on failure.
        """
        body = {
            "symbol": symbol.upper(),
            "bar_size": bar_size,
            "duration": duration,
            "use_rth": bool(use_rth),
            "what_to_show": what_to_show,
        }
        resp = self._request(
            "POST", "/rpc/latest-bars",
            json_body=body,
            timeout=_DEFAULT_LATEST_BARS_TIMEOUT,
        )
        if not resp:
            return None
        if not resp.get("success"):
            return None
        bars = resp.get("bars") or []
        return bars if isinstance(bars, list) else None

    def quote_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        body = {"symbol": symbol.upper()}
        resp = self._request("POST", "/rpc/quote-snapshot", json_body=body, timeout=5.0)
        if not resp or not resp.get("success"):
            return None
        return resp.get("quote")

    def is_configured(self) -> bool:
        return _is_enabled() and bool(_base_url())

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": _is_enabled(),
            "url": _base_url(),
            "consecutive_failures": self._consecutive_failures,
            "last_success_ts": self._last_success_ts,
        }


# Module-level singleton
_client_instance: Optional[_PusherRPCClient] = None


def get_pusher_rpc_client() -> _PusherRPCClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = _PusherRPCClient()
    return _client_instance


def is_live_bar_rpc_enabled() -> bool:
    """Public kill-switch reader. Honored by callers (e.g. the scanner's
    realtime_technical_service) that want to skip a live RPC call when the
    operator has explicitly turned it off via `ENABLE_LIVE_BAR_RPC=false`."""
    return _is_enabled()
