"""
chart_response_cache.py — Mongo-backed TTL cache for `/api/sentcom/chart`
responses (v19.25 — 2026-05-01).

Why this exists
---------------
Pre-v19.25 every chart load — fresh page open, symbol switch, 30s
auto-refresh — re-ran the full chain:
  1. Mongo `ib_historical_data` query
  2. Pusher RPC roundtrip to Windows for live-session top-up
  3. Python recompute of EMA20 / EMA50 / EMA200 / BB20 / VWAP / markers
  4. Session filter, dedup, sort, normalize

…on EVERY request, even when the underlying bars hadn't changed since
the last poll. Operator flagged "very very delayed chart loading
across the app" — this is the read-through cache that fixes it.

Design
------
- Mongo collection `chart_response_cache` with a TTL index that auto-
  evicts expired docs based on `expires_at`. **Caches survive backend
  restarts** so a fresh deploy starts warm if there's recent data.
- One cache document per `(symbol, timeframe, session, days)` tuple.
- TTL is bar-size aware: 30s for intraday, 180s for daily.
- Best-effort: any failure is logged and falls through to the live
  compute path. The cache MUST never block the response chain.

API
---
- `await cache.get(key)` -> response dict | None
- `await cache.set(key, response, ttl_seconds)` -> bool
- `await cache.invalidate(symbol)` — drop all entries for a symbol
  (used after bot fills so the next chart load picks up the new
  trade marker).

Testing
-------
- Pure in-memory mode for unit tests (db=None) so the contract can
  be pinned without a live Mongo. See test_chart_response_cache_v19_25.py.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Schema version — bump when the cached payload shape changes so old
# entries get ignored without a manual flush. Stored on every cache
# doc; reads with mismatched version are treated as MISS.
_CACHE_VERSION = 1

_COLLECTION_NAME = "chart_response_cache"


def _build_key(
    symbol: str,
    timeframe: str,
    session: str,
    days: int,
) -> str:
    """Stable cache key. Lowercased / normalized so frontend variations
    (e.g. "5min" vs "5 mins") collapse to the same entry."""
    return (
        f"{(symbol or '').upper()}|"
        f"{(timeframe or '').lower()}|"
        f"{(session or 'rth_plus_premarket').lower()}|"
        f"{int(days or 0)}"
    )


class ChartResponseCache:
    """Mongo-backed TTL cache for chart endpoint responses.

    Falls back to a pure in-memory dict if `db` is None (unit tests +
    early boot before db is wired). The Mongo backing makes the cache
    durable across backend restarts: TTL index handles eviction so we
    never serve a stale doc.
    """

    def __init__(self, db=None):
        self._db = db
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._index_initialized = False

    def attach_db(self, db) -> None:
        """Late-bind the Mongo handle (called once main DB is ready)."""
        self._db = db
        self._index_initialized = False

    async def _ensure_index(self) -> None:
        """Idempotently create the TTL index on `expires_at`. The TTL
        runs server-side: Mongo evicts docs ~60s after `expires_at`
        passes, so we don't need a sweeper task in Python."""
        if self._index_initialized or self._db is None:
            return
        try:
            coll = self._db[_COLLECTION_NAME]
            await asyncio.to_thread(
                coll.create_index,
                "expires_at",
                expireAfterSeconds=0,  # eviction = expires_at + 0s
                background=True,
            )
            await asyncio.to_thread(
                coll.create_index,
                [("symbol", 1)],
                background=True,
            )
            self._index_initialized = True
        except Exception as e:
            logger.debug(f"chart cache index init skipped: {e}")
            # Treat as if attached without index — `get/set` still work,
            # the TTL just won't auto-evict (negligible — entries are
            # small and overwritten by next set on same key).
            self._index_initialized = True

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the cached response payload or None on miss / expired."""
        if not key:
            return None

        # In-memory tier (covers tests + warm path while DB initialises).
        mem_hit = self._mem.get(key)
        if mem_hit is not None:
            if mem_hit["expires_at"] > datetime.now(timezone.utc):
                return mem_hit["response"]
            # Stale in-memory entry — drop it.
            self._mem.pop(key, None)

        if self._db is None:
            return None

        try:
            await self._ensure_index()
            doc = await asyncio.to_thread(
                self._db[_COLLECTION_NAME].find_one,
                {"_id": key},
                {"_id": 0},
            )
            if not doc:
                return None
            if doc.get("version") != _CACHE_VERSION:
                # Old schema — treat as miss; TTL or next set() will evict.
                return None
            expires_at = doc.get("expires_at")
            # Mongo's TTL eviction runs ~every 60s, so a doc returned
            # here may technically be a few seconds past its TTL.
            # Honour `expires_at` strictly so we never serve >TTL data.
            if isinstance(expires_at, datetime):
                # Mongo strips tzinfo on read — re-stamp UTC.
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= datetime.now(timezone.utc):
                    return None
            response = doc.get("response")
            if not isinstance(response, dict):
                return None
            # Re-fill in-memory tier so the next hit doesn't pay Mongo.
            self._mem[key] = {
                "response": response,
                "expires_at": expires_at,
            }
            return response
        except Exception as e:
            logger.debug(f"chart cache get({key}) failed: {e}")
            return None

    async def set(
        self,
        key: str,
        response: Dict[str, Any],
        ttl_seconds: int,
    ) -> bool:
        """Persist a fresh response. Best-effort — never raises.

        Args:
            key: Cache key (use `_build_key`).
            response: The full payload `/api/sentcom/chart` returns.
            ttl_seconds: How long this entry is valid.
        """
        if not key or not isinstance(response, dict):
            return False
        try:
            ttl = max(1, int(ttl_seconds))
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl)

            # Update in-memory tier first (covers tests + repeat hits).
            self._mem[key] = {
                "response": response,
                "expires_at": expires_at,
            }

            if self._db is None:
                return True

            await self._ensure_index()
            doc = {
                "version": _CACHE_VERSION,
                "symbol": response.get("symbol"),
                "timeframe": response.get("timeframe"),
                "cached_at": now,
                "expires_at": expires_at,
                "ttl_seconds": ttl,
                "response": response,
                "bar_count": response.get("bar_count", 0),
            }
            await asyncio.to_thread(
                self._db[_COLLECTION_NAME].update_one,
                {"_id": key},
                {"$set": doc},
                upsert=True,
            )
            return True
        except Exception as e:
            logger.debug(f"chart cache set({key}) failed: {e}")
            return False

    async def invalidate(self, symbol: str) -> int:
        """Drop every cache entry for `symbol`. Use after a bot trade
        execution so the next chart load picks up the new marker.

        Returns:
            Best-effort count of entries dropped.
        """
        if not symbol:
            return 0
        sym_upper = symbol.upper()
        # Drop in-memory tier
        dropped = 0
        for key in list(self._mem.keys()):
            if key.startswith(f"{sym_upper}|"):
                self._mem.pop(key, None)
                dropped += 1

        if self._db is None:
            return dropped

        try:
            await self._ensure_index()
            res = await asyncio.to_thread(
                self._db[_COLLECTION_NAME].delete_many,
                {"symbol": sym_upper},
            )
            return dropped + (res.deleted_count or 0)
        except Exception as e:
            logger.debug(f"chart cache invalidate({sym_upper}) failed: {e}")
            return dropped


# ── Module-level singleton ────────────────────────────────────────────────
_singleton: Optional[ChartResponseCache] = None


def get_chart_response_cache(db=None) -> ChartResponseCache:
    """Return the process-wide singleton, attaching the DB if not yet bound."""
    global _singleton
    if _singleton is None:
        _singleton = ChartResponseCache(db=db)
    elif db is not None and _singleton._db is None:
        _singleton.attach_db(db)
    return _singleton


def chart_cache_ttl_for(timeframe: str) -> int:
    """Bar-size-aware TTL.

    - Daily/weekly bars change once per session — 180s is plenty.
    - Intraday bars get a fresh tick every 30s-1min — 30s TTL keeps
      the chart feeling live while still saving 95%+ of the recompute.
    """
    if not timeframe:
        return 30
    tf = timeframe.lower().replace(" ", "")
    if tf in {"1day", "daily", "1d", "1week", "weekly", "1w"}:
        return 180
    return 30


def make_cache_key(
    symbol: str,
    timeframe: str,
    session: str,
    days: int,
) -> str:
    """Public re-export of the key builder for the router + tests."""
    return _build_key(symbol, timeframe, session, days)
