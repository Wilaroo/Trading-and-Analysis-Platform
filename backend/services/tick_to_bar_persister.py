"""
Live Tick → Mongo Bar Persister
================================
As the Windows IB pusher streams quote snapshots into the DGX backend
(via POST /api/ib/push-data), this service builds rolling intraday OHLCV
bars in memory and upserts them into `ib_historical_data` on bar-close.

Why?
    Operator quote (2026-04-27): "we shouldn't need to be constantly
    backfilling. there has to be a better way to get a cache live data."

    Today's bars only exist if `smart-backfill` was run for that symbol
    today. The chart's "PARTIAL · 50% COVERAGE" badge surfaces the symptom.
    Root cause: pusher's tick stream is only used in-memory (quotes_buffer)
    — never persisted into `ib_historical_data`. Backfilling re-fetches
    bars from IB even though the data already flowed through us live.

    Fix: piggy-back on the existing 10s push cycle. For every subscribed
    symbol, sample (last_price, cumulative_volume) into rolling 1-min,
    5-min, 15-min and 1-hour buckets. When a bucket window closes, upsert
    the OHLCV bar into `ib_historical_data` with source="live_tick" so
    `smart-backfill` (initial seed + gap-fill only now) can tell live-built
    bars apart from `reqHistoricalData`-fetched bars.

Design notes:
    * Stateless across restarts. Bars in flight at restart time are
      simply dropped — backfill catches them on next reconciliation.
    * IB convention: `quote.volume` is cumulative session volume (not
      incremental). Per-bar volume = volume_at_close - volume_at_open
      within the bucket window.
    * `bar_size` strings match the existing collector format:
      "1 min" / "5 mins" / "15 mins" / "1 hour".
    * Date format: ISO 8601 with the bucket-open timestamp (UTC). Same
      shape `enhanced_scanner` and `smart-backfill` already write so the
      compound index `(symbol, bar_size, date)` doesn't need a new
      variant.
    * `source="live_tick"` makes the live-built bars distinguishable
      from `reqHistoricalData` bars so we don't double-count or
      misattribute volume mismatches.
    * Defensive: skips quotes with last_price <= 0 (IB sentinel for
      "no print yet today"), skips ETFs/indices that don't trade
      (e.g. VIX), and never raises into the push-data hot path.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------- Bar size config ----------------

# bar_size string → window length in seconds. The 4 timeframes the
# scanner / training pipeline already trains on. Daily bars are NOT
# built here — those still come from the EOD historical collector.
_BAR_WINDOWS_SEC: Dict[str, int] = {
    "1 min": 60,
    "5 mins": 5 * 60,
    "15 mins": 15 * 60,
    "1 hour": 60 * 60,
}


def _bucket_open(now: datetime, window_sec: int) -> datetime:
    """Return the UTC bucket-open timestamp for `now` at `window_sec`.

    Aligned to whole-minute boundaries (RTH alignment is the operator's
    concern; we just bucket on wall-clock so 1-min bars line up with
    IB's 9:30:00, 9:31:00, ... and so on)."""
    epoch = int(now.replace(tzinfo=timezone.utc).timestamp())
    bucket_epoch = (epoch // window_sec) * window_sec
    return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)


class _BarBuilder:
    """In-memory rolling OHLCV bucket for a single (symbol, bar_size)."""

    __slots__ = (
        "symbol",
        "bar_size",
        "window_sec",
        "bucket_open",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "open_volume",
        "close_volume",
    )

    def __init__(self, symbol: str, bar_size: str, window_sec: int) -> None:
        self.symbol = symbol
        self.bar_size = bar_size
        self.window_sec = window_sec
        self.bucket_open: Optional[datetime] = None
        self.open_price: Optional[float] = None
        self.high_price: Optional[float] = None
        self.low_price: Optional[float] = None
        self.close_price: Optional[float] = None
        # Volume is IB-cumulative; bar volume is the delta within the window.
        self.open_volume: Optional[float] = None
        self.close_volume: Optional[float] = None

    def is_started(self) -> bool:
        return self.bucket_open is not None

    def reset(self, bucket_open_ts: datetime, last: float, volume: Optional[float]) -> None:
        self.bucket_open = bucket_open_ts
        self.open_price = last
        self.high_price = last
        self.low_price = last
        self.close_price = last
        self.open_volume = volume
        self.close_volume = volume

    def absorb(self, last: float, volume: Optional[float]) -> None:
        """Absorb an in-window tick — update high/low/close + close_volume."""
        if self.open_price is None:
            # Started in middle of window with bad init; treat this as the open.
            self.open_price = last
            self.high_price = last
            self.low_price = last
        else:
            if last > (self.high_price or last):
                self.high_price = last
            if last < (self.low_price or last):
                self.low_price = last
        self.close_price = last
        if volume is not None:
            self.close_volume = volume
            if self.open_volume is None:
                self.open_volume = volume

    def finalize_bar(self) -> Optional[Dict]:
        """Return the OHLCV doc for the closed bucket, or None if empty."""
        if (
            self.bucket_open is None
            or self.open_price is None
            or self.close_price is None
        ):
            return None
        # Per-bar volume = end - start. IB resets volume at session open
        # (9:30 ET), so a same-day delta is always >= 0 unless the IB feed
        # glitched (rare, but defensively clamp to 0).
        if self.open_volume is not None and self.close_volume is not None:
            bar_vol = max(0, int(self.close_volume - self.open_volume))
        else:
            bar_vol = 0
        return {
            "symbol": self.symbol,
            "bar_size": self.bar_size,
            "date": self.bucket_open.isoformat(),
            "open": round(float(self.open_price), 4),
            "high": round(float(self.high_price), 4),
            "low": round(float(self.low_price), 4),
            "close": round(float(self.close_price), 4),
            "volume": bar_vol,
            "source": "live_tick",
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }


class TickToBarPersister:
    """Builds 1m/5m/15m/1h bars from live tick quotes and upserts on close."""

    # Symbols we never build bars for (no real prints). Indices and
    # synthetic instruments — they flow as quotes but their "volume" is
    # always zero and IB historical bars are sourced separately.
    _SKIP_SYMBOLS = {"VIX"}

    def __init__(self, db=None) -> None:
        self._db = db
        # (symbol, bar_size) → _BarBuilder
        self._builders: Dict[Tuple[str, str], _BarBuilder] = {}
        self._lock = threading.Lock()
        # Stats for /api/ib/pusher-health-style introspection.
        self._bars_persisted_total: int = 0
        self._bars_persisted_by_size: Dict[str, int] = {}
        self._last_persist_ts: Optional[float] = None
        # Ticks observed (for debugging — increments each on_quote call).
        self._ticks_observed_total: int = 0

    # ---------- DB late-binding (server.py wires after Mongo connect) -----
    def set_db(self, db) -> None:
        self._db = db

    # ---------- public API used by routers/ib.py::receive_pushed_ib_data --
    def on_push(self, quotes: Dict[str, dict]) -> int:
        """
        Absorb one push-data batch. Called from routers.ib for every push.
        Returns the number of bars finalized & upserted on this call (so
        the route can log it cheaply at debug level).
        """
        if not quotes:
            return 0
        now = datetime.now(timezone.utc)
        finalized: list = []
        with self._lock:
            for symbol, q in quotes.items():
                if not symbol or symbol in self._SKIP_SYMBOLS:
                    continue
                if not isinstance(q, dict):
                    continue
                last = q.get("last")
                if last is None or last <= 0:
                    continue
                volume = q.get("volume")
                self._ticks_observed_total += 1
                for bar_size, window_sec in _BAR_WINDOWS_SEC.items():
                    bucket = _bucket_open(now, window_sec)
                    key = (symbol, bar_size)
                    b = self._builders.get(key)
                    if b is None:
                        b = _BarBuilder(symbol, bar_size, window_sec)
                        self._builders[key] = b

                    if not b.is_started():
                        b.reset(bucket, float(last), float(volume) if volume else None)
                        continue

                    if bucket > b.bucket_open:
                        # Window rolled over → finalize previous bar, start
                        # a new bucket whose open == the latest tick. We
                        # carry close_volume forward as the new open_volume
                        # so per-bar volume math is continuous.
                        bar = b.finalize_bar()
                        if bar is not None:
                            finalized.append(bar)
                        b.reset(
                            bucket,
                            float(last),
                            float(volume) if volume else b.close_volume,
                        )
                    else:
                        b.absorb(float(last), float(volume) if volume else None)

        if finalized:
            self._upsert_bars(finalized)
        return len(finalized)

    def stats(self) -> Dict:
        """Return introspection stats (read by /api/ib/tick-persister-stats)."""
        with self._lock:
            return {
                "active_builders": len(self._builders),
                "bars_persisted_total": self._bars_persisted_total,
                "bars_persisted_by_size": dict(self._bars_persisted_by_size),
                "ticks_observed_total": self._ticks_observed_total,
                "last_persist_ts": self._last_persist_ts,
                "bar_sizes": list(_BAR_WINDOWS_SEC.keys()),
            }

    # ---------- internal helpers ----------------------------------------
    def _upsert_bars(self, bars: list) -> None:
        if self._db is None:
            return
        try:
            col = self._db["ib_historical_data"]
        except Exception as exc:
            logger.debug(f"tick_to_bar: cannot reach ib_historical_data: {exc}")
            return
        now_ts = datetime.now(timezone.utc).timestamp()
        for bar in bars:
            try:
                col.update_one(
                    {
                        "symbol": bar["symbol"],
                        "bar_size": bar["bar_size"],
                        "date": bar["date"],
                    },
                    {"$set": bar},
                    upsert=True,
                )
                self._bars_persisted_total += 1
                self._bars_persisted_by_size[bar["bar_size"]] = (
                    self._bars_persisted_by_size.get(bar["bar_size"], 0) + 1
                )
                self._last_persist_ts = now_ts
            except Exception as exc:
                logger.warning(
                    f"tick_to_bar: upsert {bar.get('symbol')} "
                    f"{bar.get('bar_size')} {bar.get('date')} failed: {exc}"
                )


# ---------------- Module-level singleton ----------------

_persister: Optional[TickToBarPersister] = None
_singleton_lock = threading.Lock()


def get_tick_to_bar_persister() -> TickToBarPersister:
    """Get or create the global tick→bar persister."""
    global _persister
    with _singleton_lock:
        if _persister is None:
            _persister = TickToBarPersister()
    return _persister


def init_tick_to_bar_persister(db) -> TickToBarPersister:
    """Initialize the singleton with a DB handle (called from server.py)."""
    persister = get_tick_to_bar_persister()
    persister.set_db(db)
    return persister
