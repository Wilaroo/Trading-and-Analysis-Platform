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
    IB_PUSHER_RPC_MAX_CONCURRENT - Max in-flight HTTP requests to the
                          pusher (default 4). IB Gateway allows ≤6
                          concurrent reqHistoricalData per client ID;
                          the pusher uses client ID 15 alone during RTH,
                          so 4 leaves 2 slots for the pusher's internal
                          quote/account-snapshot ops without risking an
                          IB pacing violation.
    IB_PUSHER_RPC_CIRCUIT_THRESHOLD - Failure count within the rolling
                          10s window that flips the circuit OPEN (default 5).
    IB_PUSHER_RPC_CIRCUIT_OPEN_S - How long the circuit stays OPEN before
                          it transitions to HALF_OPEN and tries one test
                          request (default 30s).

Design notes:
    * Purely sync. Call from async paths via asyncio.to_thread.
    * Short timeouts (6s default) — pusher RPC path is supposed to be
      a last-mile accelerator, not a liability.
    * Single shared requests.Session for keep-alive / connection reuse.
    * Bounded concurrency via threading.Semaphore (default 4) so a flood
      of concurrent chart panels can't overwhelm the pusher.
    * Circuit breaker (closed → open → half_open). Once the pusher dies
      or starts pacing-violating IB Gateway, we stop hammering it for
      30s instead of spamming retries that prolong the outage.
    * In-flight dedup on read paths (latest_bars / latest_bars_batch /
      subscriptions) — multiple chart panels asking for the same symbol
      simultaneously coalesce into a single HTTP request. Materially
      reduces the request volume on busy mornings.
    * Every call returns either the parsed JSON dict or None on any
      failure. Never raises. Callers must treat None as "pusher unreachable,
      fall back to cache." This is the FAIL-OPEN contract: the chart UI
      keeps rendering off Mongo cache during a pusher outage.
"""

from __future__ import annotations

import json as _json
import logging
import os
import threading
import time as _t
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ─── Throttling / circuit breaker config ─────────────────────────────────────

_REQUEST_SEMAPHORE_SIZE = _env_int("IB_PUSHER_RPC_MAX_CONCURRENT", 4)
_CIRCUIT_FAILURE_THRESHOLD = _env_int("IB_PUSHER_RPC_CIRCUIT_THRESHOLD", 5)
_CIRCUIT_FAILURE_WINDOW_S = _env_float("IB_PUSHER_RPC_CIRCUIT_WINDOW_S", 10.0)
_CIRCUIT_OPEN_DURATION_S = _env_float("IB_PUSHER_RPC_CIRCUIT_OPEN_S", 30.0)
_SEMAPHORE_ACQUIRE_TIMEOUT_S = _env_float("IB_PUSHER_RPC_ACQUIRE_TIMEOUT_S", 2.0)

# Circuit states (string consts so they serialise cleanly in /pusher-health)
_CIRCUIT_CLOSED = "closed"
_CIRCUIT_OPEN = "open"
_CIRCUIT_HALF_OPEN = "half_open"


class _PusherRPCClient:
    # Subscription-set TTL. Pusher subscriptions change rarely (operator
    # adds a watchlist symbol, scanner promotes a Tier-2 stock, etc.), so
    # 30s is a reasonable freshness bound that still keeps us from
    # hammering /rpc/subscriptions on every latest_bars call.
    _SUBSCRIPTIONS_TTL_SEC: float = 30.0

    def __init__(self) -> None:
        self._session = requests.Session()
        # Bounded-concurrency semaphore replaces the previous single
        # threading.Lock. The lock serialised every call (effectively
        # capacity 1); the semaphore allows up to N parallel calls
        # (default 4) so chart-panel + scanner traffic doesn't queue
        # behind a slow latest_bars fetch.
        self._request_semaphore = threading.Semaphore(_REQUEST_SEMAPHORE_SIZE)
        # Track consecutive failures to auto-suppress noisy logs
        self._consecutive_failures = 0
        self._last_success_ts: Optional[float] = None
        # Rolling window of recent RPC latencies (last 50 successful calls)
        # used by /api/ib/pusher-health → PusherHeartbeatTile so the
        # operator can see RPC perf at a glance.
        self._latency_ms_window: deque = deque(maxlen=50)
        self._call_count_total: int = 0
        self._success_count_total: int = 0
        # Subscription-set cache: lets `latest_bars` short-circuit calls
        # for symbols the pusher isn't tracking (avoids noisy IB
        # reqHistoricalData timeouts on the Windows side). None = unknown,
        # empty set = pusher reachable but tracking nothing.
        self._subs_cache: Optional[set] = None
        self._subs_cache_ts: float = 0.0

        # ─── Circuit breaker state ──────────────────────────────────────
        self._circuit_lock = threading.Lock()
        self._circuit_state: str = _CIRCUIT_CLOSED
        self._circuit_opened_at: float = 0.0
        # Rolling timestamp window of recent failures. We open the circuit
        # when len(failures within last _CIRCUIT_FAILURE_WINDOW_S) >= threshold.
        self._failure_window: deque = deque(maxlen=_CIRCUIT_FAILURE_THRESHOLD * 2)
        self._circuit_short_circuit_total: int = 0
        self._semaphore_timeout_total: int = 0

        # ─── In-flight dedup state ──────────────────────────────────────
        # Coalesces concurrent identical idempotent calls (latest_bars(SPY)
        # fired by 3 chart panels at the same moment → 1 HTTP request to
        # the pusher). Keyed by (method, path, json_body_hash).
        self._dedup_lock = threading.Lock()
        self._in_flight_calls: Dict[Tuple[str, str, str], Tuple[threading.Event, List[Optional[Dict[str, Any]]]]] = {}
        self._dedup_coalesced_total: int = 0

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
        # Snapshot circuit state under the lock so the response is internally
        # consistent (avoids a torn read where state="open" but opened_at=0).
        with self._circuit_lock:
            circuit_state = self._circuit_state
            circuit_opened_at = self._circuit_opened_at
            recent_failures = len(self._failure_window)
        circuit_open_remaining_s: Optional[float] = None
        if circuit_state == _CIRCUIT_OPEN:
            circuit_open_remaining_s = max(
                0.0,
                round(_CIRCUIT_OPEN_DURATION_S - (_t.time() - circuit_opened_at), 1),
            )
        return {
            "rpc_latency_ms_avg": avg,
            "rpc_latency_ms_p95": p95,
            "rpc_latency_ms_last": last,
            "rpc_sample_size": len(samples),
            "rpc_call_count_total": self._call_count_total,
            "rpc_success_count_total": self._success_count_total,
            "rpc_consecutive_failures": self._consecutive_failures,
            "rpc_last_success_ts": self._last_success_ts,
            # ─── v19.30.11 — throttle / circuit breaker / dedup metrics ──
            "rpc_max_concurrent": _REQUEST_SEMAPHORE_SIZE,
            "rpc_circuit_state": circuit_state,
            "rpc_circuit_open_remaining_s": circuit_open_remaining_s,
            "rpc_circuit_recent_failures": recent_failures,
            "rpc_circuit_short_circuit_total": self._circuit_short_circuit_total,
            "rpc_semaphore_timeout_total": self._semaphore_timeout_total,
            "rpc_dedup_coalesced_total": self._dedup_coalesced_total,
        }

    # ---- circuit breaker helpers -------------------------------------------

    def _circuit_check(self) -> bool:
        """Return True if a request may proceed, False if the circuit is
        currently open. On expiry the circuit transitions to HALF_OPEN
        and lets exactly one test request through.
        """
        now = _t.time()
        with self._circuit_lock:
            if self._circuit_state == _CIRCUIT_OPEN:
                if now - self._circuit_opened_at >= _CIRCUIT_OPEN_DURATION_S:
                    self._circuit_state = _CIRCUIT_HALF_OPEN
                    logger.info(
                        "pusher RPC circuit breaker: HALF_OPEN — testing recovery"
                    )
                    return True
                return False
            return True  # closed or half_open

    def _circuit_record_success(self) -> None:
        """Recovery confirmed (HALF_OPEN) or steady-state success (CLOSED)."""
        with self._circuit_lock:
            if self._circuit_state == _CIRCUIT_HALF_OPEN:
                logger.info(
                    "pusher RPC circuit breaker: CLOSED (recovered after %.1fs)",
                    _t.time() - self._circuit_opened_at,
                )
            self._circuit_state = _CIRCUIT_CLOSED
            self._circuit_opened_at = 0.0
            self._failure_window.clear()

    def _circuit_record_failure(self) -> None:
        """Bump the rolling failure window. Open the circuit if the
        window threshold is exceeded (CLOSED) or if the half-open test
        request failed (HALF_OPEN).
        """
        now = _t.time()
        with self._circuit_lock:
            self._failure_window.append(now)
            cutoff = now - _CIRCUIT_FAILURE_WINDOW_S
            while self._failure_window and self._failure_window[0] < cutoff:
                self._failure_window.popleft()

            if self._circuit_state == _CIRCUIT_HALF_OPEN:
                self._circuit_state = _CIRCUIT_OPEN
                self._circuit_opened_at = now
                logger.warning(
                    "pusher RPC circuit breaker: OPEN (recovery test failed; "
                    "blocking for %ds)",
                    int(_CIRCUIT_OPEN_DURATION_S),
                )
            elif (
                self._circuit_state == _CIRCUIT_CLOSED
                and len(self._failure_window) >= _CIRCUIT_FAILURE_THRESHOLD
            ):
                self._circuit_state = _CIRCUIT_OPEN
                self._circuit_opened_at = now
                logger.warning(
                    "pusher RPC circuit breaker: OPEN "
                    "(%d failures in %.0fs; blocking for %ds — fail-open, "
                    "callers fall back to Mongo cache)",
                    len(self._failure_window),
                    _CIRCUIT_FAILURE_WINDOW_S,
                    int(_CIRCUIT_OPEN_DURATION_S),
                )

    # ---- dedup helper ------------------------------------------------------

    def _dedup_key(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]],
    ) -> Tuple[str, str, str]:
        """Stable key for in-flight dedup. JSON body sorted so the same
        logical request hashes identically across callers."""
        if json_body is None:
            body_key = ""
        else:
            try:
                body_key = _json.dumps(json_body, sort_keys=True, default=str)
            except Exception:
                # Fall back to a unique key per call — disables dedup for
                # this one request but never breaks the call path.
                body_key = f"_unhashable_{id(json_body)}"
        return (method, path, body_key)

    def _request_with_dedup(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        """Same as `_request`, but coalesces concurrent identical calls
        into a single HTTP round-trip. Use this for IDEMPOTENT reads
        only (latest_bars, latest_bars_batch, subscriptions, account_snapshot).
        Subscribe / unsubscribe must use plain `_request` since each
        call has independent semantics.
        """
        key = self._dedup_key(method, path, json_body)
        leader: bool
        with self._dedup_lock:
            existing = self._in_flight_calls.get(key)
            if existing is not None:
                event, holder = existing
                self._dedup_coalesced_total += 1
                leader = False
            else:
                event = threading.Event()
                holder = [None]
                self._in_flight_calls[key] = (event, holder)
                leader = True

        if not leader:
            # Follower — wait up to 1.5× the request timeout for the
            # leader's response. If the leader takes longer than that,
            # bail out fail-open (None). This bounds tail latency for
            # followers when the leader is stuck on a slow IB call.
            event.wait(timeout=timeout * 1.5)
            return holder[0]

        # We're the leader — make the actual HTTP request.
        try:
            holder[0] = self._request(
                method, path, json_body=json_body, timeout=timeout
            )
        finally:
            event.set()
            with self._dedup_lock:
                self._in_flight_calls.pop(key, None)
        return holder[0]

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

        # ─── Circuit breaker gate ───────────────────────────────────────
        # Fail-open: short-circuit returns None so callers fall back to
        # Mongo cache instead of stalling on a doomed pusher round-trip.
        if not self._circuit_check():
            self._circuit_short_circuit_total += 1
            return None

        # ─── Concurrency cap ────────────────────────────────────────────
        # Acquire a semaphore slot with a bounded wait — under heavy
        # concurrent load (chart-mount storm + scanner tick + bar_poll),
        # the slowest callers get a None instead of piling up indefinitely.
        if not self._request_semaphore.acquire(timeout=_SEMAPHORE_ACQUIRE_TIMEOUT_S):
            self._semaphore_timeout_total += 1
            return None

        url = f"{base}{path}"
        _start = _t.time()
        self._call_count_total += 1
        try:
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
                self._circuit_record_failure()
                return None
            self._consecutive_failures = 0
            self._last_success_ts = _t.time()
            self._success_count_total += 1
            self._circuit_record_success()
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
            self._circuit_record_failure()
            return None
        except Exception as exc:
            logger.warning("pusher RPC %s %s unexpected error: %s", method, path, exc)
            self._consecutive_failures += 1
            self._circuit_record_failure()
            return None
        finally:
            self._request_semaphore.release()

    # ---- public API -------------------------------------------------------

    def health(self) -> Optional[Dict[str, Any]]:
        return self._request_with_dedup("GET", "/rpc/health", timeout=3.0)

    def account_snapshot(self) -> Optional[Dict[str, Any]]:
        """Fetch the pusher's latest account snapshot on demand.

        Returns a dict like {success, source, account, timestamp} or None
        if the RPC fails. Callers use this as a fallback for the V5
        equity pill when the push-loop's account_data is stale/empty.

        v19.30.11 (2026-05-01) — dedup-wrapped: the V5 HUD account pill,
        the SystemBanner, and the briefing endpoint can all call this
        within the same tick; coalesce them into one HTTP round-trip.
        """
        return self._request_with_dedup("GET", "/rpc/account-snapshot", timeout=5.0)

    def subscriptions(self, force_refresh: bool = False) -> Optional[set]:
        """
        Return the set of symbols currently subscribed on the pusher.

        Cached for `_SUBSCRIPTIONS_TTL_SEC` (30s) so we don't hit
        /rpc/subscriptions on every per-symbol latest_bars call. Returns
        None on RPC failure (callers should treat that as "unknown" and
        NOT gate, to preserve current behaviour when the pusher is down).
        """
        now = _t.time()
        if (
            not force_refresh
            and self._subs_cache is not None
            and (now - self._subs_cache_ts) < self._SUBSCRIPTIONS_TTL_SEC
        ):
            return self._subs_cache

        # v19.30.2 (2026-05-02): timeout dropped from 8.0s → 3.0s.
        # The 8s budget was set 2026-04-29 to give the pusher headroom
        # while it qualified contracts; in practice when the Windows
        # pusher is FULLY OFF (operator power-cycle, IB Gateway down,
        # etc.) every call burns the full 8s × N pools = 24-36s loop
        # wedge. py-spy proved this on Spark 2026-05-02. Subscription
        # state changes rarely (operator action), so a 3s budget is
        # plenty when pusher is healthy and fails-fast when it's not.
        # The 30s `_subs_cache` TTL still smooths the steady-state
        # call rate, so this bound only matters on cold cache or
        # `force_refresh=True`.
        # v19.30.11 (2026-05-01) — dedup-wrapped: cold-cache races
        # (multiple services init in parallel) coalesce into one fetch.
        resp = self._request_with_dedup("GET", "/rpc/subscriptions", timeout=3.0)
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
        # v19.30.11 — dedup-wrapped: chart panel + scanner + bar_poll
        # firing for the same symbol within a few hundred ms coalesce.
        resp = self._request_with_dedup(
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
        # v19.30.11 — dedup-wrapped: dedup key includes the sorted symbol
        # tuple so identical batch requests coalesce.
        resp = self._request_with_dedup(
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
        # v19.30.11 — dedup-wrapped: V5 watchlist + scanner cards can both
        # ask for AAPL quote at the same tick; coalesce.
        resp = self._request_with_dedup(
            "POST", "/rpc/quote-snapshot", json_body=body, timeout=5.0
        )
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
