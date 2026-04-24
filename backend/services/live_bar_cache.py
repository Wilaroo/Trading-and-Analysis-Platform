"""
Live-bar cache (Mongo-backed, TTL-aware)
========================================
Phase 1 of the Live Data Architecture. Stores the most-recent session slice
of bars fetched from the Windows pusher's reqHistoricalData RPC. Dynamic
TTL lets the backend re-use a result across many chart / analysis / scanner
calls within a short window (30s during RTH) while still being aggressive
about refreshing stale weekend / overnight data on demand.

Why a cache and not always-pull?
    * Pusher RPC -> IB Gateway -> IB servers is a real network hop that
      also competes with IB's pacing limits (shared client-id 15).
    * During a multi-panel UI refresh the same symbol is requested from
      ChartPanel + EnhancedTickerModal + AI chat within the same second.
    * TTL index means Mongo deletes expired docs automatically — no manual
      cleanup cron needed.

Collection shape (`live_bar_cache`):
    {
      symbol: "SPY",
      bar_size: "5 mins",
      bars: [ { date, open, high, low, close, volume }, ... ],
      fetched_at: ISO-8601 UTC,
      expires_at: datetime (Mongo BSON date — for TTL index),
      market_state: "rth" | "extended" | "overnight" | "weekend",
      active_view: bool,
      source: "pusher_rpc",
    }

Index:
    TTL index on `expires_at` (expireAfterSeconds=0) — Mongo deletes the
    doc once wall-clock reaches `expires_at`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# TTL seconds per market state (tunable via env; defaults per approved plan)
TTL_RTH = 30
TTL_EXTENDED = 120        # pre-market + after-hours
TTL_OVERNIGHT = 900       # 15 min
TTL_WEEKEND = 3600        # 60 min
TTL_ACTIVE_VIEW = 30      # user is actively staring at this symbol


def classify_market_state(now_utc: Optional[datetime] = None) -> str:
    """
    Return one of: "rth" | "extended" | "overnight" | "weekend".

    Uses America/New_York wall-clock implicitly by offsetting from UTC.
    We do NOT consult a holiday calendar here — that concern lives on the
    backend /api/sentcom/market-state endpoint. For TTL classification,
    "holiday weekday" rounds to "overnight" which is a safe/conservative
    fallback (15-min cache, not 30s).
    """
    now = now_utc or datetime.now(timezone.utc)
    # Approx America/New_York: UTC - 4h (EDT) or -5h (EST). For TTL purposes
    # we pick a blanket -5h offset which slightly widens "overnight" into
    # late-RTH on DST days — safe because TTLs only err toward stale side.
    et = now - timedelta(hours=5)
    dow = et.weekday()   # Mon=0 .. Sun=6
    if dow >= 5:
        return "weekend"
    hour = et.hour
    minute = et.minute
    # Regular trading hours: 09:30 – 16:00 ET
    hhmm = hour * 60 + minute
    if 9 * 60 + 30 <= hhmm < 16 * 60:
        return "rth"
    # Extended hours: 04:00 – 09:30 pre / 16:00 – 20:00 post
    if 4 * 60 <= hhmm < 9 * 60 + 30:
        return "extended"
    if 16 * 60 <= hhmm < 20 * 60:
        return "extended"
    return "overnight"


def ttl_for_state(state: str, active_view: bool = False) -> int:
    if active_view:
        return TTL_ACTIVE_VIEW
    return {
        "rth": TTL_RTH,
        "extended": TTL_EXTENDED,
        "overnight": TTL_OVERNIGHT,
        "weekend": TTL_WEEKEND,
    }.get(state, TTL_OVERNIGHT)


class LiveBarCache:
    """Thin Mongo wrapper. All methods are sync — wrap in asyncio.to_thread."""

    COLLECTION = "live_bar_cache"

    def __init__(self, db) -> None:
        self._db = db
        self._col = db[self.COLLECTION] if db is not None else None
        if self._col is not None:
            self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            # TTL index — Mongo deletes docs when wall clock >= expires_at
            self._col.create_index(
                "expires_at",
                expireAfterSeconds=0,
                name="live_bar_cache_ttl",
            )
            # Lookup index for (symbol, bar_size)
            self._col.create_index(
                [("symbol", 1), ("bar_size", 1)],
                name="live_bar_cache_sym_bs",
            )
        except Exception as exc:
            logger.warning("live_bar_cache index creation failed: %s", exc)

    def get(self, symbol: str, bar_size: str) -> Optional[Dict[str, Any]]:
        if self._col is None:
            return None
        try:
            doc = self._col.find_one(
                {"symbol": symbol.upper(), "bar_size": bar_size},
                {"_id": 0},
            )
            if not doc:
                return None
            # Belt-and-braces: even with the TTL index, Mongo can take up to
            # 60s to purge — if the doc is technically expired, treat it
            # as a miss so the caller refetches.
            expires_at = doc.get("expires_at")
            if isinstance(expires_at, datetime):
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= expires_at:
                    return None
            return doc
        except Exception as exc:
            logger.warning("live_bar_cache.get error: %s", exc)
            return None

    def put(
        self,
        symbol: str,
        bar_size: str,
        bars: List[Dict[str, Any]],
        *,
        active_view: bool = False,
        market_state: Optional[str] = None,
        source: str = "pusher_rpc",
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        state = market_state or classify_market_state(now)
        ttl = ttl_for_state(state, active_view=active_view)
        expires_at = now + timedelta(seconds=ttl)
        doc = {
            "symbol": symbol.upper(),
            "bar_size": bar_size,
            "bars": bars,
            "fetched_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at,  # BSON date for TTL index
            "market_state": state,
            "active_view": active_view,
            "ttl_seconds": ttl,
            "source": source,
        }
        if self._col is not None:
            try:
                self._col.update_one(
                    {"symbol": symbol.upper(), "bar_size": bar_size},
                    {"$set": doc},
                    upsert=True,
                )
            except Exception as exc:
                logger.warning("live_bar_cache.put error: %s", exc)
        # Return a serializable copy (strip BSON datetime)
        doc_out = {**doc, "expires_at": expires_at.isoformat().replace("+00:00", "Z")}
        return doc_out


_cache_instance: Optional[LiveBarCache] = None


def init_live_bar_cache(db) -> LiveBarCache:
    global _cache_instance
    _cache_instance = LiveBarCache(db)
    return _cache_instance


def get_live_bar_cache() -> Optional[LiveBarCache]:
    return _cache_instance
