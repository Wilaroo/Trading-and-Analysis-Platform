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
    # Subscription-set TTL. Pusher subscriptions change rarely (operator
    # adds a watchlist symbol, scanner promotes a Tier-2 stock, etc.), so
    # 30s is a reasonable freshness bound that still keeps us from
    # hammering /rpc/subscriptions on every latest_bars call.
    _SUBSCRIPTIONS_TTL_SEC: float = 30.0

    def __init__(self) -> None:
        self._session = requests.Session()
        self._lock = threading.Lock()
        # Track consecutive failures to auto-suppress noisy logs
        self._consecutive_failures = 0
        self._last_success_ts: Optional[float] = None
        # Rolling window of recent RPC latencies (last 50 successful calls)
        # used by /api/ib/pusher-health → PusherHeartbeatTile so the
        # operator can see RPC perf at a glance.
        from collections import deque
        self._latency_ms_window: deque = deque(maxlen=50)
        self._call_count_total: int = 0
        self._success_count_total: int = 0
        # Subscription-set cache: lets `latest_bars` short-circuit calls
        # for symbols the pusher isn't tracking (avoids noisy IB
        # reqHistoricalData timeouts on the Windows side). None = unknown,
        # empty set = pusher reachable but tracking nothing.
        self._subs_cache: Optional[set] = None
        self._subs_cache_ts: float = 0.0

    # ---- public latency stats ----------------------------------------------
    def latency_stats(self) -> Dict[str, Any]:
        """Return rolling latency stats for the heartbeat tile."""
        samples = list(self._latency_ms_window)
        if samples:
            sorted_s = sorted(samples)
            avg = round(sum(samples) / len(samples), 1)
            # p95 — last 5% of sorted samples; for 50-element window ≈ index 47
            p95_idx = max(0, int(len(sorted_s) * 0.95) - 1)
            p95 = round(sorted_s[p95_idx], 1)
            last = round(samples[-1], 1)
        else:
            avg = p95 = last = None
        return {
            "rpc_latency_ms_avg": avg,
            "rpc_latency_ms_p95": p95,
            "rpc_latency_ms_last": last,
            "rpc_sample_size": len(samples),
            "rpc_call_count_total": self._call_count_total,
            "rpc_success_count_total": self._success_count_total,
            "rpc_consecutive_failures": self._consecutive_failures,
            "rpc_last_success_ts": self._last_success_ts,
        }

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
        import time as _t
        _start = _t.time()
        self._call_count_total += 1
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
            self._last_success_ts = _t.time()
            self._success_count_total += 1
            # Record latency for the heartbeat tile.
            self._latency_ms_window.append((_t.time() - _start) * 1000.0)
            # Bust the subscription-set cache on any subscribe/unsubscribe
            # call so the next latest_bars gate sees the fresh set
            # immediately (instead of waiting up to TTL seconds).
            if path in ("/rpc/subscribe", "/rpc/unsubscribe"):
                self._subs_cache = None
                self._subs_cache_ts = 0.0
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

    def account_snapshot(self) -> Optional[Dict[str, Any]]:
        """Fetch the pusher's latest account snapshot on demand.

        Returns a dict like {success, source, account, timestamp} or None
        if the RPC fails. Callers use this as a fallback for the V5
        equity pill when the push-loop's account_data is stale/empty.
        """
        return self._request("GET", "/rpc/account-snapshot", timeout=5.0)

    def subscriptions(self, force_refresh: bool = False) -> Optional[set]:
        """
        Return the set of symbols currently subscribed on the pusher.

        Cached for `_SUBSCRIPTIONS_TTL_SEC` (30s) so we don't hit
        /rpc/subscriptions on every per-symbol latest_bars call. Returns
        None on RPC failure (callers should treat that as "unknown" and
        NOT gate, to preserve current behaviour when the pusher is down).
        """
        import time as _t
        now = _t.time()
        if (
            not force_refresh
            and self._subs_cache is not None
            and (now - self._subs_cache_ts) < self._SUBSCRIPTIONS_TTL_SEC
        ):
            return self._subs_cache

        # Bumped from 3.0s → 8.0s (2026-04-29 afternoon-13). Under load
        # the pusher's RPC server can take >3s to answer when it's
        # simultaneously qualifying contracts for unsubscribed symbols,
        # which caused the gate to fall through and DGX to fire MORE
        # latest-bars requests for unsubscribed symbols, compounding the
        # problem. 8s gives the pusher headroom while staying well under
        # the 18s latest-bars timeout.
        resp = self._request("GET", "/rpc/subscriptions", timeout=8.0)
        if not resp or not resp.get("success"):
            return None
        symbols = resp.get("symbols") or []
        try:
            subs = {str(s).upper().strip() for s in symbols if s}
        except Exception:
            return None
        self._subs_cache = subs
        self._subs_cache_ts = now
        return subs

    def is_pusher_subscribed(self, symbol: str) -> Optional[bool]:
        """
        Tri-state membership check:
            True  = symbol is currently subscribed on the pusher
            False = pusher reachable, symbol is NOT subscribed
            None  = pusher unreachable or older endpoint missing
                    (callers should NOT gate; preserves prior behaviour)
        """
        subs = self.subscriptions()
        if subs is None:
            return None
        return symbol.upper().strip() in subs

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
        or None on failure / when the pusher isn't tracking the symbol.

        Subscription gate (added 2026-04-28): if the pusher is reachable
        and the symbol is NOT in `/rpc/subscriptions`, return None
        immediately. This avoids the IB Gateway pacing storm we'd
        otherwise trigger by asking the pusher to reqHistoricalData on
        symbols it isn't streaming (HD/ARKK/COP/SHOP would time out
        every scan cycle, ~10s each, polluting the pusher's loop).
        Callers already treat None as "fall back to Mongo cache", so the
        contract is preserved.
        """
        sym_u = symbol.upper().strip()
        gate = self.is_pusher_subscribed(sym_u)
        if gate is False:
            logger.debug(
                "pusher RPC skipping latest_bars(%s): not in pusher subscription set",
                sym_u,
            )
            return None
        body = {
            "symbol": sym_u,
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

    def latest_bars_batch(
        self,
        symbols: List[str],
        bar_size: str,
        duration: str = "1 D",
        use_rth: bool = False,
        what_to_show: str = "TRADES",
    ) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        """Parallel fanout — POSTs to /rpc/latest-bars-batch which fires
        all per-symbol fetches in a single asyncio.gather on the pusher
        side. Returns ``{symbol: bars_list}`` for successful symbols and
        omits failures (callers can detect a missing key).

        Speedup vs sequential `latest_bars()` calls: ~5-10× on warm
        qualified-contract caches (1.2s × N → ~300ms total)."""
        cleaned = [s.upper().strip() for s in (symbols or []) if s]
        if not cleaned:
            return {}

        # Subscription gate (added 2026-04-28). Filter the batch down to
        # symbols the pusher is actually tracking. Unsubscribed symbols
        # would otherwise trigger reqHistoricalData → IB pacing timeouts
        # → Read timed out warnings on the Windows side. If the
        # subscription set is unknown (older pusher / RPC down), fall
        # through to the original behaviour to preserve compatibility.
        subs = self.subscriptions()
        if subs is not None:
            filtered = [s for s in cleaned if s in subs]
            if len(filtered) != len(cleaned):
                skipped = [s for s in cleaned if s not in subs]
                logger.debug(
                    "pusher RPC latest_bars_batch skipping %d unsubscribed symbols: %s",
                    len(skipped), skipped[:8],
                )
            cleaned = filtered
            if not cleaned:
                return {}

        body = {
            "symbols": cleaned,
            "bar_size": bar_size,
            "duration": duration,
            "use_rth": bool(use_rth),
            "what_to_show": what_to_show,
        }
        # Generous client-side timeout, scales with batch size.
        timeout = max(_DEFAULT_LATEST_BARS_TIMEOUT, 1.5 * len(cleaned))
        resp = self._request(
            "POST", "/rpc/latest-bars-batch",
            json_body=body,
            timeout=timeout,
        )
        if not resp or not resp.get("success"):
            return None
        out: Dict[str, List[Dict[str, Any]]] = {}
        for entry in resp.get("results") or []:
            if entry.get("success") and entry.get("bars"):
                out[entry["symbol"]] = entry["bars"]
        return out

    def quote_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        body = {"symbol": symbol.upper()}
        resp = self._request("POST", "/rpc/quote-snapshot", json_body=body, timeout=5.0)
        if not resp or not resp.get("success"):
            return None
        return resp.get("quote")

    # ---- subscription management (added 2026-04-30 v17) -----------------
    #
    # The DGX-side pusher rotation service uses these to swap symbols in
    # and out of the pusher's live IB Level-1 subscription set. Both
    # methods are idempotent on the pusher side — re-subscribing a symbol
    # that's already streamed is a no-op there.
    #
    # Symbols are normalised to UPPER + stripped before sending so the
    # diff math we do on the DGX side stays canonical with what the
    # pusher reports back via /rpc/subscriptions.
    #
    # Both methods bust the local subscription-set cache automatically
    # (see _request hook) so the next subscriptions() call returns the
    # fresh post-mutation set.

    def subscribe_symbols(self, symbols: set) -> Optional[Dict[str, Any]]:
        """Ask the pusher to add ``symbols`` to its IB Level-1 subscription
        set. Returns the pusher's JSON response (typically containing
        ``success`` + ``added`` + ``current_count``) or None on failure.
        """
        if not symbols:
            return {"success": True, "added": [], "skipped": []}
        try:
            payload = sorted({str(s).upper().strip() for s in symbols if s})
        except Exception as e:
            logger.warning("subscribe_symbols normalisation failed: %s: %s",
                           type(e).__name__, e, exc_info=True)
            return None
        return self._request(
            "POST", "/rpc/subscribe",
            json_body={"symbols": payload},
            timeout=15.0,  # IB contract qualification can take a few seconds per batch
        )

    def unsubscribe_symbols(self, symbols: set) -> Optional[Dict[str, Any]]:
        """Ask the pusher to drop ``symbols`` from its IB Level-1
        subscription set. Returns the pusher's JSON response or None on
        failure. Safe to call with symbols not currently subscribed (the
        pusher treats unknowns as a no-op)."""
        if not symbols:
            return {"success": True, "removed": []}
        try:
            payload = sorted({str(s).upper().strip() for s in symbols if s})
        except Exception as e:
            logger.warning("unsubscribe_symbols normalisation failed: %s: %s",
                           type(e).__name__, e, exc_info=True)
            return None
        return self._request(
            "POST", "/rpc/unsubscribe",
            json_body={"symbols": payload},
            timeout=10.0,
        )

    def get_subscribed_set(self, force_refresh: bool = True) -> Optional[set]:
        """Convenience alias for ``subscriptions()`` with refresh-by-default
        semantics — the rotation service always wants the freshest read
        before doing diff math."""
        return self.subscriptions(force_refresh=force_refresh)

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


def get_account_snapshot() -> Optional[Dict[str, Any]]:
    """Module-level helper for backend services that need on-demand account
    data when the push-loop's `_pushed_ib_data["account"]` is empty.
    Returns None if the pusher RPC is disabled / unreachable.
    """
    return get_pusher_rpc_client().account_snapshot()
