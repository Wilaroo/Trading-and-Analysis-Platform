"""
quote_tick_bus.py — In-memory L1 quote tick pub/sub (v19.34, 2026-05-04)

Goal
----
Operator wants the trading bot's manage-loop to react to mid-bar L1
quote moves instead of waiting for the 5s pusher poll OR the next
manage-loop iteration. Stop-trigger checks should fire on the freshest
tick available, so a stop that's hit at 9:31:13 is closed at 9:31:13
instead of at the next manage tick (~5-15s later).

Design
------
- One in-memory `defaultdict[symbol, set[asyncio.Queue]]` keyed by
  uppercase symbol. Subscribers create their own queue and register
  it with `subscribe(symbol)`.
- Producer (`publish(symbol, tick)`) iterates the subscriber set for
  that symbol and tries to put_nowait. If a queue is full (slow
  consumer), the OLDEST tick is popped and the new one is enqueued
  in its place — "latest-N drop" policy. Tick streams are stateless;
  the most recent quote is what matters, so dropping the older queued
  tick is correct + safe.
- No DB. No persistence. Restarts wipe state — that's by design;
  subscribers re-register on bot start.
- Drop counters per symbol so the operator can monitor backpressure
  via `GET /api/quote-tick-bus/health`.

Concurrency
-----------
- Producer runs from `routers.ib.receive_pushed_ib_data` which is
  itself running on the FastAPI event loop. No locking needed —
  asyncio is single-threaded.
- Subscribers each have their own `asyncio.Queue` so a slow consumer
  cannot block the producer or other subscribers.

Feature flag
------------
- `QUOTE_TICK_BUS_ENABLED=false` (env) → all `publish/subscribe` calls
  become no-ops. Default ON because the bus itself does no I/O.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Any, AsyncIterator, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Per-subscriber queue size. Holds at most this many pending ticks
# before the latest-drop policy kicks in. 8 is enough for ~8 RTH ticks
# of buffering — beyond that the consumer is too far behind to still
# care about the older ticks anyway.
DEFAULT_QUEUE_SIZE = 8


def _is_enabled() -> bool:
    val = os.environ.get("QUOTE_TICK_BUS_ENABLED", "true").strip().lower()
    return val not in ("0", "false", "no", "off")


class QuoteTickBus:
    """In-memory L1 quote tick pub/sub. One singleton per process."""

    def __init__(self):
        self._subs: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        # Per-symbol counters, exposed via /health.
        self._publish_counts: Dict[str, int] = defaultdict(int)
        self._drop_counts: Dict[str, int] = defaultdict(int)
        self._last_publish_ts: Dict[str, float] = {}
        # Process-global counters.
        self._publish_total = 0
        self._drop_total = 0

    # ────────────────────────────────────────────────────────────
    # Producer
    # ────────────────────────────────────────────────────────────
    def publish(self, symbol: str, tick: Dict[str, Any]) -> int:
        """Publish a single tick to all subscribers of `symbol`.
        Returns number of subscribers that received the tick (those
        that hit the latest-N drop policy still count as received —
        they'll see the freshest tick on their next get())."""
        if not _is_enabled():
            return 0
        sym_u = (symbol or "").upper()
        if not sym_u:
            return 0
        subs = self._subs.get(sym_u)
        self._publish_counts[sym_u] += 1
        self._publish_total += 1
        self._last_publish_ts[sym_u] = time.time()
        if not subs:
            return 0
        delivered = 0
        for q in tuple(subs):  # tuple() so concurrent subscribe/unsubscribe is safe
            try:
                q.put_nowait(tick)
                delivered += 1
            except asyncio.QueueFull:
                # Latest-N drop: pop oldest, enqueue freshest.
                try:
                    q.get_nowait()
                    q.put_nowait(tick)
                    delivered += 1
                    self._drop_counts[sym_u] += 1
                    self._drop_total += 1
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Race: queue emptied or filled again between calls.
                    # Skip this subscriber for this tick — next tick covers.
                    pass
        return delivered

    def publish_quotes(self, quotes: Dict[str, Dict[str, Any]]) -> int:
        """Convenience: publish a batch of `{symbol: tick}` in one call.
        Returns the total subscriber-deliveries. Used by the pusher
        intake so a single push of N quotes results in one publish call."""
        if not _is_enabled() or not quotes:
            return 0
        total = 0
        for sym, tick in quotes.items():
            total += self.publish(sym, tick)
        return total

    # ────────────────────────────────────────────────────────────
    # Consumer
    # ────────────────────────────────────────────────────────────
    def subscribe(
        self, symbol: str, queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> Tuple[asyncio.Queue, str]:
        """Register a new subscriber for `symbol`. Returns the
        subscriber's queue + the normalized symbol so the caller has
        the canonical key for `unsubscribe`.

        Caller is responsible for cleaning up via `unsubscribe(symbol, q)`
        when done. Recommended pattern:

            q, sym_u = bus.subscribe("AAPL")
            try:
                while running:
                    tick = await asyncio.wait_for(q.get(), timeout=10)
                    handle(tick)
            finally:
                bus.unsubscribe(sym_u, q)
        """
        sym_u = (symbol or "").upper()
        if not sym_u:
            raise ValueError("symbol required")
        q: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._subs[sym_u].add(q)
        logger.info(
            f"[v19.34 TICK-BUS] subscribe sym={sym_u} "
            f"size={queue_size} subscribers={len(self._subs[sym_u])}"
        )
        return q, sym_u

    def unsubscribe(self, symbol: str, q: asyncio.Queue) -> bool:
        """Remove a subscriber. Returns True when removed, False when
        no matching subscription was found."""
        sym_u = (symbol or "").upper()
        subs = self._subs.get(sym_u)
        if not subs:
            return False
        if q in subs:
            subs.discard(q)
            if not subs:
                # Cleanup the empty slot so health reports don't leak.
                self._subs.pop(sym_u, None)
            logger.info(
                f"[v19.34 TICK-BUS] unsubscribe sym={sym_u} "
                f"subscribers={len(subs)}"
            )
            return True
        return False

    async def stream(
        self, symbol: str, queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Async generator wrapper. Auto-handles unsubscribe on
        cancellation. Use:

            async for tick in bus.stream("AAPL"):
                handle(tick)
        """
        q, sym_u = self.subscribe(symbol, queue_size=queue_size)
        try:
            while True:
                tick = await q.get()
                yield tick
        finally:
            self.unsubscribe(sym_u, q)

    # ────────────────────────────────────────────────────────────
    # Monitoring
    # ────────────────────────────────────────────────────────────
    def health(self) -> Dict[str, Any]:
        """Snapshot of bus state for `/api/quote-tick-bus/health`."""
        per_symbol = []
        now = time.time()
        for sym, subs in self._subs.items():
            last_ts = self._last_publish_ts.get(sym)
            per_symbol.append({
                "symbol": sym,
                "subscribers": len(subs),
                "publishes": self._publish_counts.get(sym, 0),
                "drops": self._drop_counts.get(sym, 0),
                "last_publish_age_s": (
                    round(now - last_ts, 2) if last_ts else None
                ),
            })
        # Sort by publishes desc so the busiest symbols surface first.
        per_symbol.sort(key=lambda r: r["publishes"], reverse=True)
        return {
            "enabled": _is_enabled(),
            "publish_total": self._publish_total,
            "drop_total": self._drop_total,
            "drop_rate_pct": (
                round(100.0 * self._drop_total / self._publish_total, 3)
                if self._publish_total else 0.0
            ),
            "active_symbols": len(self._subs),
            "total_subscribers": sum(len(s) for s in self._subs.values()),
            "per_symbol": per_symbol,
        }

    def reset_for_tests(self) -> None:
        """Wipe state for unit tests. Never call from production."""
        self._subs.clear()
        self._publish_counts.clear()
        self._drop_counts.clear()
        self._last_publish_ts.clear()
        self._publish_total = 0
        self._drop_total = 0


# Singleton — services/routers grab via `get_quote_tick_bus()`.
_BUS: Optional[QuoteTickBus] = None


def get_quote_tick_bus() -> QuoteTickBus:
    global _BUS
    if _BUS is None:
        _BUS = QuoteTickBus()
    return _BUS
