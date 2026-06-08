"""
Real-Time Technical Analysis Service
Calculates live technical indicators from IB data (MongoDB + IB Pusher):
- VWAP, EMA (9, 20, 50, 200), RSI, RVOL, ATR
- Support/Resistance levels
- Gap percentage, price momentum
- Pattern detection

Data Sources (100% IB — zero external API dependencies):
- Intraday bars: ib_historical_data collection in MongoDB
- Daily bars: ib_historical_data collection in MongoDB
- Real-time quotes: IB Pusher (via routers/ib.py)
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class TechnicalSnapshot:
    """Complete technical analysis snapshot for a symbol"""
    symbol: str
    timestamp: str
    
    # Price data
    current_price: float
    open: float
    high: float
    low: float
    prev_close: float
    
    # Volume analysis
    volume: int
    avg_volume: float
    rvol: float  # Relative volume
    
    # Moving averages
    vwap: float
    ema_9: float
    ema_20: float
    ema_50: float
    sma_200: float
    
    # Distance from key levels (as percentage)
    dist_from_vwap: float
    dist_from_ema9: float
    dist_from_ema20: float
    
    # Momentum indicators
    rsi_14: float
    rsi_trend: str  # "oversold", "neutral", "overbought"
    
    # Volatility
    atr: float
    atr_percent: float
    daily_range_pct: float
    
    # Gap analysis
    gap_pct: float
    gap_direction: str  # "up", "down", "flat"
    holding_gap: bool
    
    # Key levels
    resistance: float
    support: float
    high_of_day: float
    low_of_day: float
    
    # Position analysis
    above_vwap: bool
    above_ema9: bool
    above_ema20: bool
    trend: str  # "uptrend", "downtrend", "sideways"
    
    # Setup indicators
    extended_from_ema9: bool
    extension_pct: float
    
    # Bollinger Bands (20-period, 2 std dev)
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float  # (upper - lower) / middle * 100
    
    # Keltner Channels (20-period, 1.5 ATR)
    kc_upper: float
    kc_middle: float
    kc_lower: float
    
    # Squeeze state
    squeeze_on: bool  # BB inside KC = volatility compression
    squeeze_fire: float  # Momentum histogram value (positive = bullish fire)
    
    # Opening Range (first 30 min)
    or_high: float
    or_low: float
    or_breakout: str  # "above", "below", "inside"
    
    # Relative strength vs SPY
    rs_vs_spy: float  # Today's % change vs SPY's % change (positive = outperforming)
    
    # Source tracking
    bars_used: int
    data_quality: str  # "real" | "warming" (1-4 real bars) | "proxy" (daily-anchored, no intraday yet)
    # NEW (Feb-2026): Tracks which data path produced these intraday bars.
    #   "live_only"    — entire 5-min window came from pusher RPC live bars
    #   "live_extended" — pusher RPC bars appended onto Mongo backfill bars
    #   "mongo_only"   — Mongo `ib_historical_data` only (RPC unavailable / disabled)
    data_source: str = "mongo_only"
    # v19.34.289 F2 — minute-level intraday-bar freshness. The day-level
    # _check_staleness (and its live-quote bypass) let hours-stale intraday bars
    # feed VWAP/RSI/EMA while a fresh quote made them look "real". These track
    # the trailing bar's COLLECTED age (UTC, tz-safe) so the auto-exec gate can
    # block stale-indicator alerts (info-only — the alert still surfaces).
    intraday_bar_age_min: Optional[float] = None
    intraday_stale: bool = False


class RealTimeTechnicalService:
    """
    Service for calculating real-time technical indicators
    using 100% IB-sourced data to eliminate train/serve data skew.
    
    Data sources (all IB):
    - Current quotes: IB Pusher (real-time via routers/ib.py)
    - Daily bars: ib_historical_data in MongoDB
    - Intraday bars: ib_historical_data in MongoDB
    """
    
    def __init__(self):
        self._db = None
        self._cache: Dict[str, TechnicalSnapshot] = {}
        self._cache_ttl = 120  # 2 minute cache for technical data
        self._spy_change_pct: float = 0.0  # Cached SPY daily % change
        self._spy_cache_time: Optional[datetime] = None
    
    def set_db(self, db):
        """Set MongoDB connection for historical data access"""
        self._db = db
    
    def _get_intraday_bars_from_db(self, symbol: str, bar_size: str = "5 mins", limit: int = 78) -> Optional[List[Dict]]:
        """Get recent intraday bars from ib_historical_data (same source as training).
        Returns bars in chronological order (oldest first).
        NOTE: Sync function — caller should use asyncio.to_thread() if needed."""
        if self._db is None:
            return None
        try:
            pipeline = [
                {"$match": {"symbol": symbol.upper(), "bar_size": bar_size}},
                {"$sort": {"date": -1}},
                {"$limit": limit},
                {"$project": {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "collected_at": 1}},
            ]
            bars = list(self._db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True))
            if bars and len(bars) >= 5:
                bars.reverse()  # Chronological order (oldest first)
                # Rename 'date' to 'timestamp' for compatibility with indicator calculations
                for bar in bars:
                    bar['timestamp'] = bar.pop('date', None)
                return bars
        except Exception as e:
            logger.debug(f"Error fetching intraday bars for {symbol}: {e}")
        return None

    async def _get_live_intraday_bars(
        self, symbol: str, bar_size: str = "5 mins"
    ) -> Optional[List[Dict]]:
        """
        Fetch the freshest intraday bars from the Windows pusher RPC via
        `HybridDataService.fetch_latest_session_bars()` (which itself reads
        from `live_bar_cache` first, then falls back to a live RPC call).

        Returns bars in chronological order (oldest first), normalized to
        the same shape as `_get_intraday_bars_from_db()` (i.e. each bar has
        a 'timestamp' key). Returns ``None`` if the pusher RPC is disabled,
        unconfigured, or unreachable — in which case the caller should fall
        back to the Mongo path.
        """
        try:
            from services.ib_pusher_rpc import is_live_bar_rpc_enabled, get_pusher_rpc_client
            from services.hybrid_data_service import get_hybrid_data_service
        except Exception as e:
            logger.debug(f"live-bar imports failed for {symbol}: {e}")
            return None

        # Cheap kill-switch + config check before doing any network work.
        if not is_live_bar_rpc_enabled():
            return None
        try:
            if not get_pusher_rpc_client().is_configured():
                return None
        except Exception:
            return None

        try:
            hds = get_hybrid_data_service()
            result = await hds.fetch_latest_session_bars(
                symbol.upper(), bar_size, active_view=False, use_rth=False
            )
        except Exception as e:
            logger.debug(f"fetch_latest_session_bars failed for {symbol}: {e}")
            return None

        if not result or not result.get("success"):
            return None

        bars = result.get("bars") or []
        if not bars:
            return None

        # Normalize to the same shape as _get_intraday_bars_from_db. Pusher
        # RPC returns bars with a `date` field; rename to `timestamp` so
        # downstream indicator calc doesn't care about the source.
        normalized: List[Dict] = []
        for bar in bars:
            ts = bar.get("timestamp") or bar.get("date")
            if ts is None:
                continue
            normalized.append({
                "timestamp": ts,
                "open": bar.get("open", 0),
                "high": bar.get("high", 0),
                "low": bar.get("low", 0),
                "close": bar.get("close", 0),
                "volume": bar.get("volume", 0),
            })
        # Pusher RPC returns chronological asc already, but defend against
        # ordering surprises.
        normalized.sort(key=lambda b: str(b["timestamp"]))
        return normalized or None

    @staticmethod
    def _merge_live_into_history(
        mongo_bars: Optional[List[Dict]],
        live_bars: Optional[List[Dict]],
    ) -> Tuple[Optional[List[Dict]], str]:
        """
        Combine Mongo-historical bars with live-pusher bars by timestamp.

        Live bars override matching Mongo timestamps (live wins on overlap)
        and any newer live bars are appended. Returns the merged list and
        the appropriate `data_source` label for `TechnicalSnapshot`.
        """
        if not live_bars and not mongo_bars:
            return (None, "mongo_only")
        if not mongo_bars:
            return (live_bars, "live_only")
        if not live_bars:
            return (mongo_bars, "mongo_only")

        # Index Mongo bars by timestamp for O(1) override.
        merged: Dict[str, Dict] = {str(b["timestamp"]): b for b in mongo_bars}
        for b in live_bars:
            merged[str(b["timestamp"])] = b
        out = sorted(merged.values(), key=lambda b: str(b["timestamp"]))
        return (out, "live_extended")

    def _check_staleness(self, bars: Optional[List[Dict]], max_age_hours: int = 24) -> bool:
        """Check if bars are fresh enough for trading decisions.
        
        Two-layer freshness check:
        Layer 1: If IB Pusher has a live quote for the symbol → NEVER stale
        Layer 2: Check bar age using TRADING DAYS (accounts for weekends/holidays)
                 3 trading days threshold instead of calendar hours
        
        Returns True if bars are STALE (too old), False if fresh."""
        if not bars:
            return True  # No data = stale
        try:
            latest_bar = bars[-1]  # Last bar (most recent)
            latest_ts = latest_bar.get('timestamp') or latest_bar.get('date')
            if latest_ts is None:
                return True
            
            # Parse the date (handle IB's various formats)
            if isinstance(latest_ts, str):
                # IB format: "20260407 09:35:00" or "20260407" or ISO
                ts = latest_ts.strip()
                if 'T' in ts:
                    latest_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                elif len(ts) >= 8 and ts[:8].isdigit():
                    # IB format: YYYYMMDD or YYYYMMDD HH:MM:SS
                    date_part = ts[:8]
                    latest_dt = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=timezone.utc)
                    if len(ts) > 8:
                        try:
                            latest_dt = datetime.strptime(ts[:17], "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                else:
                    # Try YYYY-MM-DD
                    latest_dt = datetime.strptime(ts[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            elif isinstance(latest_ts, datetime):
                latest_dt = latest_ts if latest_ts.tzinfo else latest_ts.replace(tzinfo=timezone.utc)
            else:
                return True
            
            # Count trading days elapsed (exclude weekends)
            now = datetime.now(timezone.utc)
            days_elapsed = 0
            check_date = latest_dt.date()
            today = now.date()
            from datetime import timedelta as td
            while check_date < today:
                check_date += td(days=1)
                if check_date.weekday() < 5:  # Mon-Fri
                    days_elapsed += 1
            
            # Convert max_age_hours to trading days threshold
            # 24h = 1 trading day, 72h (default) = 3 trading days
            max_trading_days = max(1, max_age_hours // 24)
            return days_elapsed > max_trading_days
            
        except Exception:
            return True  # Error parsing = treat as stale
    
    def _get_daily_bars_from_db(self, symbol: str, limit: int = 50) -> Optional[List[Dict]]:
        """Get daily bars from ib_historical_data (fast, no API call).
        NOTE: This is a sync function called from async context.
        The caller should use asyncio.to_thread() if needed."""
        if self._db is None:
            return None
        try:
            bars = list(self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
            ).sort("date", -1).limit(limit))
            
            if bars and len(bars) >= 10:
                # Reverse to chronological order (oldest first)
                bars.reverse()
                # Rename 'date' to 'timestamp' for compatibility
                for bar in bars:
                    bar['timestamp'] = bar.pop('date', None)
                return bars
        except Exception as e:
            logger.debug(f"Error fetching daily bars for {symbol}: {e}")
        return None

    def _flag_daily_data_gap(self, symbol: str) -> None:
        """v19.34.288 F3 (hybrid-C): record a missing-daily-bars gap so the
        smart-backfill sweep can PRIORITIZE healing it. Telemetry only,
        idempotent per (symbol, day), never raises — a flag hiccup must never
        break the scan path. The actual re-queue happens inside
        ib_historical_collector.smart_backfill (which owns the request schema
        + correct end_date), which reads these flags and queues them first."""
        if self._db is None:
            return
        try:
            now = datetime.now(timezone.utc)
            self._db["data_gap_events"].update_one(
                {"symbol": symbol.upper(), "kind": "daily_missing",
                 "day": now.strftime("%Y-%m-%d")},
                {"$set": {"last_seen": now, "source": "realtime_technical_service"},
                 "$inc": {"hits": 1},
                 "$setOnInsert": {"first_seen": now}},
                upsert=True,
            )
        except Exception:
            pass

    def _intraday_collected_age_min(self, bars):
        """v19.34.289 F2 — minutes since the trailing intraday bar was COLLECTED
        (written to Mongo). Uses `collected_at` (always UTC ISO, written by the
        collectors + tick persister) so it is TIMEZONE-SAFE — unlike the bar
        `date`, which can be ET or UTC depending on the pusher. Returns None when
        absent (e.g. a fresh live-overlay bar, or a legacy row) → caller treats
        the symbol as fresh (fail-open, never a false block)."""
        if not bars:
            return None
        ca = bars[-1].get("collected_at")
        if not ca:
            return None
        try:
            if isinstance(ca, datetime):
                dt = ca if ca.tzinfo else ca.replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
            return round(age, 2) if age >= 0 else None
        except Exception:
            return None

    def _rth_time_fraction(self, today_bar: Optional[Dict] = None) -> float:
        """v19.34.290 F1 — fraction of the RTH session elapsed (0..1], used to
        de-bias intraday RVOL. Returns 1.0 (NO de-bias) before the open, after the
        close, on error, OR when the 'today' daily bar is not actually today's ET
        session — so a COMPLETE prior-day volume is never scaled up into a false
        high RVOL (guards the F7 stale-today-bar case). Mirrors
        ib_data_provider.calculate_rvol."""
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
            if today_bar is not None:
                ts = str(today_bar.get("timestamp") or "")[:10].replace("/", "-")
                if len(ts) == 8 and ts.isdigit():
                    ts = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                if ts and ts != now_et.strftime("%Y-%m-%d"):
                    return 1.0  # daily bar is a complete prior session
            market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            if now_et < market_open or now_et >= market_close:
                return 1.0
            minutes_since_open = (now_et - market_open).total_seconds() / 60.0
            return max(min(minutes_since_open / 390.0, 1.0), 1.0 / 390.0)
        except Exception:
            return 1.0

    def _filter_current_session(self, bars):
        """v19.34.292 F5 — keep only intraday bars from the most recent session
        (the trailing bar's ET calendar date) so VWAP / short EMAs / HOD-LOD
        reflect ONLY the current session. The 78-bar by-recency window could
        otherwise blend PRIOR sessions into 'today' (esp. pre-market / low-volume
        days). ISO timestamps are converted UTC→ET before taking the date (so an
        evening extended-hours bar past UTC-midnight isn't mis-bucketed); IB-format
        'YYYYMMDD ...' already carries the ET trading date. Fail-open: returns the
        input unchanged if dates can't be determined."""
        if not bars or len(bars) < 2:
            return bars
        try:
            from zoneinfo import ZoneInfo
            _ET = ZoneInfo("America/New_York")

            def _et_date(b):
                ts = str(b.get("timestamp") or b.get("date") or "").strip().replace("/", "-")
                if not ts:
                    return ""
                if "T" in ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(_ET).strftime("%Y-%m-%d")
                if len(ts) >= 8 and ts[:8].isdigit():
                    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                return ts[:10]

            latest_day = _et_date(bars[-1])
            if not latest_day:
                return bars
            same = [b for b in bars if _et_date(b) == latest_day]
            return same if same else bars
        except Exception:
            return bars

    def _get_ib_quote(self, symbol: str) -> Optional[Dict]:
        """Try to get quote from IB pushed data (non-async)"""
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            if is_pusher_connected():
                quotes = get_pushed_quotes()
                if symbol.upper() in quotes:
                    q = quotes[symbol.upper()]
                    return {
                        "symbol": symbol.upper(),
                        "price": q.get("last") or q.get("close") or 0,
                        "bid": q.get("bid") or 0,
                        "ask": q.get("ask") or 0,
                        "volume": q.get("volume") or 0,
                        "source": "ib_pusher"
                    }
        except Exception:
            pass
        return None
    
    async def _get_spy_change(self) -> float:
        """Get SPY's daily % change (cached for 2 min). Uses 100% IB data."""
        now = datetime.now(timezone.utc)
        if self._spy_cache_time and (now - self._spy_cache_time).total_seconds() < 120:
            return self._spy_change_pct
        try:
            # Get SPY daily bars from MongoDB (IB data)
            daily_bars = await asyncio.to_thread(self._get_daily_bars_from_db, "SPY", 3)
            if daily_bars and len(daily_bars) >= 2:
                prev_close = daily_bars[-2]["close"]
                
                # Use IB Pusher for current price if available
                ib_quote = self._get_ib_quote("SPY")
                if ib_quote and ib_quote.get("price", 0) > 0:
                    price = ib_quote["price"]
                else:
                    # Fallback to latest bar close
                    price = daily_bars[-1]["close"]
                
                self._spy_change_pct = ((price - prev_close) / prev_close) * 100
                self._spy_cache_time = now
        except Exception:
            pass
        return self._spy_change_pct
    
    async def get_technical_snapshot(
        self, symbol: str, force_refresh: bool = False,
        mongo_only: bool = False, max_age_sec: Optional[float] = None,
    ) -> Optional[TechnicalSnapshot]:
        """
        Get comprehensive technical snapshot for a symbol.
        Uses 100% IB data to match training data (eliminates train/serve skew):
        - Quotes: IB Pusher (real-time)
        - Intraday bars: ib_historical_data (MongoDB, 5-min)
        - Daily bars: ib_historical_data (MongoDB, 1-day)

        Args:
            mongo_only: when True, skip the pusher live-bar RPC overlay.
                Used by the v18 bar poll service which polls 1,000s of
                symbols every 30-60s and would otherwise overwhelm the
                pusher's IB historical-data API (causing the
                "[RPC] latest-bars X failed" cascade we saw 2026-04-30).
                Mongo bars are typically <60s lagged from the always-on
                turbo collectors — fine for slow setups.
        """
        symbol = symbol.upper()
        
        # Use centralized ticker validation
        from utils.ticker_validator import is_valid_ticker
        if not is_valid_ticker(symbol):
            return None
        
        # Check cache. v19.34.291 F4: callers on the decision path pass a tighter
        # `max_age_sec` so auto-exec never runs on a snapshot up to the global
        # 120s TTL stale; other callers (e.g. bar-poll over 1000s of symbols)
        # keep the default TTL to avoid a re-fetch storm.
        effective_ttl = max_age_sec if max_age_sec is not None else self._cache_ttl
        if not force_refresh and symbol in self._cache:
            cached = self._cache[symbol]
            cache_age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached.timestamp.replace('Z', '+00:00'))).total_seconds()
            if cache_age < effective_ttl:
                return cached
        
        try:
            # Get intraday bars (5-min) from MongoDB — same source as training
            intraday_bars = await asyncio.to_thread(self._get_intraday_bars_from_db, symbol, "5 mins", 78)

            # Live-bar overlay (Feb-2026): when the IB pusher RPC is up, we
            # prefer the freshest 5-min bars from `live_bar_cache` /
            # pusher RPC. Pusher bars OVERWRITE matching Mongo timestamps
            # and any newer bars are appended on top. This keeps the indicator
            # warm-up (200-period EMA, 14-RSI etc.) intact while making sure
            # the trailing edge of the series is real-time, not stale.
            #
            # 2026-04-30 v19.1 — caller can opt out via `mongo_only=True`
            # (used by bar_poll_service to avoid pusher RPC bombardment).
            if mongo_only:
                intraday_source = "mongo_only_caller_request"
            else:
                live_bars = await self._get_live_intraday_bars(symbol, "5 mins")
                intraday_bars, intraday_source = self._merge_live_into_history(
                    intraday_bars, live_bars
                )

            # Staleness check: skip symbol if intraday data is too old
            # BUT: if IB Pusher has a live quote, bars are fine for indicator calc
            ib_quote = self._get_ib_quote(symbol)
            ib_pusher_live = ib_quote and ib_quote.get("price", 0) > 0

            if not ib_pusher_live and self._check_staleness(intraday_bars):
                logger.debug(f"Stale or missing intraday data for {symbol}, no live IB quote — skipping")
                intraday_bars = None  # Will use fallback estimates
                intraday_source = "mongo_only"
            
            # Get daily bars for ATR, average volume, daily levels from MongoDB
            daily_bars = await asyncio.to_thread(self._get_daily_bars_from_db, symbol, 50)
            
            # Get current quote - IB Pusher ONLY (no stale MongoDB fallback)
            if ib_pusher_live:
                quote = ib_quote
            else:
                # No live IB data = no scan. Scanner requires real-time prices.
                return None
            
            if not quote or not daily_bars:
                # v19.34.288 F3 (hybrid-C): a missing daily history for a
                # universe symbol is a DATA-PIPELINE GAP — never paper over it
                # with fabricated levels. Fail closed (skip this cycle, no
                # alert) AND flag the gap so smart-backfill prioritizes healing
                # it. Only flag the genuine daily-gap case (live price present).
                if quote and not daily_bars:
                    self._flag_daily_data_gap(symbol)
                logger.warning(f"Insufficient data for {symbol}")
                return None
            
            current_price = quote.get("price", 0)
            if current_price <= 0:
                return None
            
            # Calculate all indicators
            spy_change = await self._get_spy_change()
            # v19.34.292 F5 — session-anchor: drop prior-session bars so VWAP /
            # short EMAs / HOD-LOD reflect ONLY the current session (the 78-bar
            # by-recency window could otherwise blend yesterday into 'today').
            intraday_bars = self._filter_current_session(intraday_bars)
            snapshot = self._calculate_snapshot(
                symbol=symbol,
                current_price=current_price,
                intraday_bars=intraday_bars,
                daily_bars=daily_bars,
                quote=quote,
                spy_change_pct=spy_change
            )
            # Stamp which data path produced the intraday bars so callers
            # (e.g. the LiveAlertCard UI) can prove freshness at a glance.
            snapshot.data_source = intraday_source

            # v19.34.289 F2 — minute-level intraday freshness gate. A live quote
            # only proves PRICE is fresh; the mongo intraday bars feeding
            # VWAP/RSI/EMA can be stale if the collectors stalled. During RTH, if
            # the trailing bar was COLLECTED longer than
            # SCANNER_INTRADAY_MAX_BAR_AGE_MIN ago, flag the snapshot stale so the
            # auto-exec gate blocks it (info-only). collected_at is UTC (tz-safe);
            # a fresh live-overlay bar has no collected_at → treated as fresh.
            try:
                import os as _os
                from services.live_bar_cache import classify_market_state
                age_min = self._intraday_collected_age_min(intraday_bars)
                snapshot.intraday_bar_age_min = age_min
                _max_age = float(_os.environ.get("SCANNER_INTRADAY_MAX_BAR_AGE_MIN", "15"))
                if (age_min is not None and age_min > _max_age
                        and classify_market_state() == "rth"):
                    snapshot.intraday_stale = True
            except Exception:
                pass

            # Cache the result
            self._cache[symbol] = snapshot

            return snapshot
            
        except Exception as e:
            logger.error(f"Error calculating technicals for {symbol}: {e}")
            return None
    
    def _calculate_snapshot(
        self,
        symbol: str,
        current_price: float,
        intraday_bars: List[Dict],
        daily_bars: List[Dict],
        quote: Dict,
        spy_change_pct: float = 0.0
    ) -> TechnicalSnapshot:
        """Calculate all technical indicators from bar data"""
        
        # === DAILY DATA ANALYSIS ===
        if daily_bars:
            # Previous close
            prev_close = daily_bars[-2]["close"] if len(daily_bars) >= 2 else daily_bars[-1]["open"]
            
            # Today's OHLC
            today = daily_bars[-1]
            open_price = today["open"]
            high_of_day = today["high"]
            low_of_day = today["low"]
            daily_volume = today["volume"]
            
            # Calculate average volume (20-day)
            volumes = [bar["volume"] for bar in daily_bars[-21:-1]] if len(daily_bars) > 21 else [bar["volume"] for bar in daily_bars[:-1]]
            avg_volume = sum(volumes) / len(volumes) if volumes else daily_volume
            
            # RVOL — v19.34.290 F1: time-of-day-adjusted. `daily_volume` is the
            # PARTIAL cumulative volume so far today; dividing it by a FULL-day
            # 20-day average understated RVOL intraday (a 5x mover read ~0.3 at
            # 10:00 ET) — and RVOL gates nearly every setup. Scale the baseline by
            # the fraction of the session elapsed so RVOL means "vs the typical
            # pace at THIS time of day". Env kill-switch SCANNER_TOD_RVOL=false
            # reverts to the raw full-day ratio without a patch. Mirrors
            # ib_data_provider.calculate_rvol.
            import os as _os
            if _os.environ.get("SCANNER_TOD_RVOL", "true").lower() in ("1", "true", "yes"):
                _tf = self._rth_time_fraction(today)
            else:
                _tf = 1.0
            _expected_vol = avg_volume * _tf
            rvol = daily_volume / _expected_vol if _expected_vol > 0 else 1.0
            
            # Calculate ATR (14-period)
            atr = self._calculate_atr(daily_bars, 14)
            atr_percent = (atr / current_price) * 100 if current_price > 0 else 0
            
            # Gap calculation
            gap_pct = ((open_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            gap_direction = "up" if gap_pct > 0.5 else "down" if gap_pct < -0.5 else "flat"
            holding_gap = current_price > prev_close if gap_pct > 0 else current_price < prev_close if gap_pct < 0 else True
            
            # Calculate SMAs/EMAs from daily data
            ema_50 = self._calculate_ema([bar["close"] for bar in daily_bars], 50)
            sma_200 = self._calculate_sma([bar["close"] for bar in daily_bars], 200)
            
            # Support/Resistance from daily data
            resistance, support = self._calculate_sr_levels(daily_bars[-20:])
            
        else:
            # Fallback values
            prev_close = current_price * 0.99
            open_price = current_price
            high_of_day = current_price * 1.01
            low_of_day = current_price * 0.99
            daily_volume = 0
            avg_volume = 1000000
            rvol = 1.0
            atr = current_price * 0.02
            atr_percent = 2.0
            gap_pct = 0
            gap_direction = "flat"
            holding_gap = True
            ema_50 = current_price
            sma_200 = current_price
            resistance = current_price * 1.03
            support = current_price * 0.97
        
        # === INTRADAY DATA ANALYSIS ===
        if intraday_bars and len(intraday_bars) >= 5:
            # Calculate intraday VWAP
            vwap = self._calculate_vwap(intraday_bars)
            
            # Calculate short-term EMAs from intraday data
            closes = [bar["close"] for bar in intraday_bars]
            ema_9 = self._calculate_ema(closes, 9)
            ema_20 = self._calculate_ema(closes, 20)
            
            # Calculate RSI from intraday closes
            rsi_14 = self._calculate_rsi(closes, 14)
            
            # Update high/low of day if intraday data is more recent
            intraday_high = max(bar["high"] for bar in intraday_bars)
            intraday_low = min(bar["low"] for bar in intraday_bars)
            high_of_day = max(high_of_day, intraday_high)
            low_of_day = min(low_of_day, intraday_low)
            
            data_quality = "real"
            bars_used = len(intraday_bars)
            
        elif intraday_bars and len(intraday_bars) >= 1:
            # WARMING (v19.34.288 F3): 1-4 real bars. A short VWAP/EMA computed
            # from the REAL bars that exist is a real measurement, NOT a
            # fabrication. RSI needs >=15 closes; if we have fewer, fall back to
            # a REAL daily RSI rather than the old hardcoded 50.
            closes = [bar["close"] for bar in intraday_bars]
            vwap = self._calculate_vwap(intraday_bars)
            ema_9 = self._calculate_ema(closes, 9)
            ema_20 = self._calculate_ema(closes, 20)
            if len(closes) >= 15:
                rsi_14 = self._calculate_rsi(closes, 14)
            else:
                rsi_14 = self._calculate_rsi([bar["close"] for bar in daily_bars], 14)
            intraday_high = max(bar["high"] for bar in intraday_bars)
            intraday_low = min(bar["low"] for bar in intraday_bars)
            high_of_day = max(high_of_day, intraday_high)
            low_of_day = min(low_of_day, intraday_low)
            data_quality = "warming"
            bars_used = len(intraday_bars)

        else:
            # REAL PROXY (v19.34.288 F3): no intraday bars yet (pre-open / thin
            # tape). DO NOT fabricate (old code used current_price*0.998, *0.99,
            # *0.985, rsi=50). Anchor to REAL daily values instead: today's
            # session open as the VWAP anchor, prior close for the short EMAs,
            # and a REAL daily RSI. All measured, all labeled data_quality=
            # "proxy" so downstream (UI / learning) can see it traded on a proxy.
            vwap = open_price if open_price > 0 else prev_close
            ema_9 = prev_close
            ema_20 = prev_close
            rsi_14 = self._calculate_rsi([bar["close"] for bar in daily_bars], 14)
            data_quality = "proxy"
            bars_used = 0
        
        # === CALCULATED METRICS ===
        
        # Distance from key levels
        dist_from_vwap = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0
        dist_from_ema9 = ((current_price - ema_9) / ema_9) * 100 if ema_9 > 0 else 0
        dist_from_ema20 = ((current_price - ema_20) / ema_20) * 100 if ema_20 > 0 else 0
        
        # Position analysis
        above_vwap = current_price > vwap
        above_ema9 = current_price > ema_9
        above_ema20 = current_price > ema_20
        
        # === Trend determination (v19.34.166 — tolerance + macro context) ===
        # The original classifier (pre-v166) used strict binary `>` against
        # EMA9/EMA20, which flips uptrend↔downtrend tick-by-tick when price
        # hovers within pennies of the EMAs. On 2026-05-27 the audit found
        # SPY classified as "downtrend" while sitting $0.07 below EMA9 on a
        # +0.48% gap-up day with price 7% above EMA50/SMA200 — clearly a
        # consolidation in an uptrend, not a downtrend. That misclass
        # poisoned the scanner's `_market_regime` (80% of alerts tagged
        # `strong_downtrend`) and silenced every setup that requires
        # `trend == "uptrend"` (incl. 9_ema_scalp dormant since 2026-04-07).
        #
        # v166 fix has two pieces (per operator decision Q1c):
        #   1. Tolerance band (Q2b = 0.25%): distances within ±0.25% of an
        #      EMA count as "at" — neither above nor below — so micro-noise
        #      doesn't flip the classification.
        #   2. Macro-context override: if price > EMA50 AND EMA50 > SMA200
        #      (strong long-term uptrend structure), we never return
        #      "downtrend"; the strongest classification a noisy intraday
        #      print can earn in that posture is "sideways". Symmetric
        #      check for the bear side.
        _TREND_TOLERANCE_PCT = 0.25  # v166 — operator-approved Q2b
        _at_ema9  = abs(dist_from_ema9)  <= _TREND_TOLERANCE_PCT
        _at_ema20 = abs(dist_from_ema20) <= _TREND_TOLERANCE_PCT
        # "Effective" above/below treats anything inside the tolerance band
        # as neither above nor below — that's the noise-suppression layer.
        _eff_above_ema9  = above_ema9  and not _at_ema9
        _eff_above_ema20 = above_ema20 and not _at_ema20
        _eff_below_ema9  = (not above_ema9)  and not _at_ema9
        _eff_below_ema20 = (not above_ema20) and not _at_ema20

        # Macro structure — > EMA50 + EMA50 > SMA200 = secular uptrend
        _macro_uptrend   = (current_price > ema_50 > 0) and (ema_50 > sma_200 > 0)
        _macro_downtrend = (current_price < ema_50) and (ema_50 < sma_200) \
            and ema_50 > 0 and sma_200 > 0

        if _eff_above_ema9 and _eff_above_ema20 and ema_9 > ema_20:
            trend = "uptrend"
        elif _eff_below_ema9 and _eff_below_ema20 and ema_9 < ema_20:
            # Macro-context veto: a fractional intraday print below EMA9/20
            # in an otherwise-strong secular uptrend is consolidation, not
            # a downtrend. Bug discovered 2026-05-27 — SPY case.
            trend = "sideways" if _macro_uptrend else "downtrend"
        else:
            trend = "sideways"
        # If we DID say "uptrend" but macro structure is clearly bearish,
        # downgrade to "sideways" (the inverse of the macro-up veto above).
        if trend == "uptrend" and _macro_downtrend:
            trend = "sideways"
        
        # Extension analysis (for rubber band setups)
        extended_from_ema9 = abs(dist_from_ema9) > 2.0
        
        # === BOLLINGER BANDS (20-period, 2 std dev) from daily closes ===
        daily_closes = [bar["close"] for bar in daily_bars] if daily_bars else [current_price]
        bb_middle = self._calculate_sma(daily_closes, 20)
        bb_std = self._calculate_std(daily_closes, 20)
        bb_upper = bb_middle + (2 * bb_std)
        bb_lower = bb_middle - (2 * bb_std)
        bb_width = ((bb_upper - bb_lower) / bb_middle * 100) if bb_middle > 0 else 0
        
        # === KELTNER CHANNELS (20-period, 1.5 ATR) ===
        kc_middle = bb_middle  # Same 20-period SMA
        kc_upper = kc_middle + (1.5 * atr)
        kc_lower = kc_middle - (1.5 * atr)
        
        # === SQUEEZE DETECTION ===
        squeeze_on = bb_upper < kc_upper and bb_lower > kc_lower
        # Momentum: use difference between price and midline, normalized
        squeeze_fire = ((current_price - bb_middle) / atr) if atr > 0 else 0
        
        # === OPENING RANGE (first 30 min = first 6 five-min bars) ===
        or_high = high_of_day
        or_low = low_of_day
        or_breakout = "inside"
        if intraday_bars and len(intraday_bars) >= 6:
            or_bars = intraday_bars[:6]
            or_high = max(bar["high"] for bar in or_bars)
            or_low = min(bar["low"] for bar in or_bars)
            if current_price > or_high:
                or_breakout = "above"
            elif current_price < or_low:
                or_breakout = "below"
            else:
                or_breakout = "inside"
        
        # === RELATIVE STRENGTH vs SPY ===
        stock_change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
        rs_vs_spy = stock_change_pct - spy_change_pct
        
        # RSI interpretation
        if rsi_14 < 30:
            rsi_trend = "oversold"
        elif rsi_14 > 70:
            rsi_trend = "overbought"
        else:
            rsi_trend = "neutral"
        
        # Daily range
        daily_range_pct = ((high_of_day - low_of_day) / low_of_day) * 100 if low_of_day > 0 else 0
        
        return TechnicalSnapshot(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            current_price=round(current_price, 2),
            open=round(open_price, 2),
            high=round(high_of_day, 2),
            low=round(low_of_day, 2),
            prev_close=round(prev_close, 2),
            volume=daily_volume,
            avg_volume=round(avg_volume),
            rvol=round(rvol, 2),
            vwap=round(vwap, 2),
            ema_9=round(ema_9, 2),
            ema_20=round(ema_20, 2),
            ema_50=round(ema_50, 2),
            sma_200=round(sma_200, 2),
            dist_from_vwap=round(dist_from_vwap, 2),
            dist_from_ema9=round(dist_from_ema9, 2),
            dist_from_ema20=round(dist_from_ema20, 2),
            rsi_14=round(rsi_14, 1),
            rsi_trend=rsi_trend,
            atr=round(atr, 2),
            atr_percent=round(atr_percent, 2),
            daily_range_pct=round(daily_range_pct, 2),
            gap_pct=round(gap_pct, 2),
            gap_direction=gap_direction,
            holding_gap=holding_gap,
            resistance=round(resistance, 2),
            support=round(support, 2),
            high_of_day=round(high_of_day, 2),
            low_of_day=round(low_of_day, 2),
            above_vwap=above_vwap,
            above_ema9=above_ema9,
            above_ema20=above_ema20,
            trend=trend,
            extended_from_ema9=extended_from_ema9,
            extension_pct=round(dist_from_ema9, 2),
            bb_upper=round(bb_upper, 2),
            bb_middle=round(bb_middle, 2),
            bb_lower=round(bb_lower, 2),
            bb_width=round(bb_width, 2),
            kc_upper=round(kc_upper, 2),
            kc_middle=round(kc_middle, 2),
            kc_lower=round(kc_lower, 2),
            squeeze_on=squeeze_on,
            squeeze_fire=round(squeeze_fire, 3),
            or_high=round(or_high, 2),
            or_low=round(or_low, 2),
            or_breakout=or_breakout,
            rs_vs_spy=round(rs_vs_spy, 2),
            bars_used=bars_used,
            data_quality=data_quality
        )
    
    def _calculate_vwap(self, bars: List[Dict]) -> float:
        """Calculate VWAP from bar data"""
        if not bars:
            return 0
        
        total_volume = 0
        total_vp = 0
        
        for bar in bars:
            typical_price = (bar["high"] + bar["low"] + bar["close"]) / 3
            volume = bar["volume"]
            total_vp += typical_price * volume
            total_volume += volume
        
        return total_vp / total_volume if total_volume > 0 else bars[-1]["close"]
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate EMA from price list"""
        if not prices or len(prices) < period:
            return prices[-1] if prices else 0
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # Start with SMA
        
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Calculate SMA from price list"""
        if not prices:
            return 0
        if len(prices) < period:
            return sum(prices) / len(prices)
        return sum(prices[-period:]) / period
    
    def _calculate_std(self, prices: List[float], period: int) -> float:
        """Calculate standard deviation from price list"""
        if not prices or len(prices) < 2:
            return 0
        subset = prices[-period:] if len(prices) >= period else prices
        mean = sum(subset) / len(subset)
        variance = sum((p - mean) ** 2 for p in subset) / len(subset)
        return variance ** 0.5
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI from price list"""
        if len(prices) < period + 1:
            return 50  # Neutral default
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_atr(self, bars: List[Dict], period: int = 14) -> float:
        """Calculate ATR from daily bars"""
        if len(bars) < 2:
            return 0
        
        true_ranges = []
        for i in range(1, len(bars)):
            high = bars[i]["high"]
            low = bars[i]["low"]
            prev_close = bars[i-1]["close"]
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return sum(true_ranges) / len(true_ranges) if true_ranges else 0
        
        return sum(true_ranges[-period:]) / period
    
    def _calculate_sr_levels(self, bars: List[Dict]) -> Tuple[float, float]:
        """Calculate support and resistance from recent bars"""
        if not bars:
            return (0, 0)
        
        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]
        
        # Simple approach: recent high/low as R/S
        resistance = max(highs)
        support = min(lows)
        
        return (resistance, support)
    
    async def get_batch_snapshots(
        self, symbols: List[str], *, mongo_only: bool = False,
    ) -> Dict[str, TechnicalSnapshot]:
        """Get technical snapshots for multiple symbols.

        Args:
            mongo_only: forwarded to ``get_technical_snapshot`` — see
                that docstring for rationale (avoids pusher RPC bombardment
                from the v18 bar poll service).
        """
        results = {}

        for symbol in symbols:
            snapshot = await self.get_technical_snapshot(
                symbol, mongo_only=mongo_only,
            )
            if snapshot:
                results[symbol] = snapshot

        return results
    
    def snapshot_to_dict(self, snapshot: TechnicalSnapshot) -> Dict[str, Any]:
        """Convert snapshot to dictionary for API response"""
        return {
            "symbol": snapshot.symbol,
            "timestamp": snapshot.timestamp,
            "price": {
                "current": snapshot.current_price,
                "open": snapshot.open,
                "high": snapshot.high,
                "low": snapshot.low,
                "prev_close": snapshot.prev_close
            },
            "volume": {
                "current": snapshot.volume,
                "average": snapshot.avg_volume,
                "rvol": snapshot.rvol
            },
            "moving_averages": {
                "vwap": snapshot.vwap,
                "ema_9": snapshot.ema_9,
                "ema_20": snapshot.ema_20,
                "ema_50": snapshot.ema_50,
                "sma_200": snapshot.sma_200
            },
            "distances": {
                "from_vwap": snapshot.dist_from_vwap,
                "from_ema9": snapshot.dist_from_ema9,
                "from_ema20": snapshot.dist_from_ema20
            },
            "momentum": {
                "rsi": snapshot.rsi_14,
                "rsi_trend": snapshot.rsi_trend
            },
            "volatility": {
                "atr": snapshot.atr,
                "atr_percent": snapshot.atr_percent,
                "daily_range_pct": snapshot.daily_range_pct
            },
            "gap": {
                "percent": snapshot.gap_pct,
                "direction": snapshot.gap_direction,
                "holding": snapshot.holding_gap
            },
            "levels": {
                "resistance": snapshot.resistance,
                "support": snapshot.support,
                "high_of_day": snapshot.high_of_day,
                "low_of_day": snapshot.low_of_day
            },
            "position": {
                "above_vwap": snapshot.above_vwap,
                "above_ema9": snapshot.above_ema9,
                "above_ema20": snapshot.above_ema20,
                "trend": snapshot.trend
            },
            "setup_indicators": {
                "extended_from_ema9": snapshot.extended_from_ema9,
                "extension_pct": snapshot.extension_pct
            },
            "bollinger_bands": {
                "upper": snapshot.bb_upper,
                "middle": snapshot.bb_middle,
                "lower": snapshot.bb_lower,
                "width": snapshot.bb_width
            },
            "keltner_channels": {
                "upper": snapshot.kc_upper,
                "middle": snapshot.kc_middle,
                "lower": snapshot.kc_lower
            },
            "squeeze": {
                "on": snapshot.squeeze_on,
                "fire": snapshot.squeeze_fire
            },
            "opening_range": {
                "high": snapshot.or_high,
                "low": snapshot.or_low,
                "breakout": snapshot.or_breakout
            },
            "relative_strength": {
                "vs_spy": snapshot.rs_vs_spy
            },
            "data_quality": snapshot.data_quality,
            "bars_used": snapshot.bars_used
        }
    
    def get_snapshot_for_ai(self, snapshot: TechnicalSnapshot) -> str:
        """Format snapshot as context for AI assistant"""
        return f"""
=== TECHNICAL SNAPSHOT: {snapshot.symbol} ===
Price: ${snapshot.current_price} (Open: ${snapshot.open}, H: ${snapshot.high}, L: ${snapshot.low})
Change from prev close: {((snapshot.current_price - snapshot.prev_close) / snapshot.prev_close * 100):.1f}%

VOLUME:
- Today: {snapshot.volume:,} | Avg: {snapshot.avg_volume:,.0f}
- RVOL: {snapshot.rvol:.1f}x {"🔥 HIGH" if snapshot.rvol >= 2 else "📊 Normal" if snapshot.rvol >= 1 else "⚠️ Low"}

KEY LEVELS:
- VWAP: ${snapshot.vwap} ({snapshot.dist_from_vwap:+.1f}% {"above" if snapshot.above_vwap else "below"})
- EMA 9: ${snapshot.ema_9} ({snapshot.dist_from_ema9:+.1f}%)
- EMA 20: ${snapshot.ema_20} ({snapshot.dist_from_ema20:+.1f}%)
- Resistance: ${snapshot.resistance} | Support: ${snapshot.support}

INDICATORS:
- RSI(14): {snapshot.rsi_14:.0f} ({snapshot.rsi_trend})
- ATR: ${snapshot.atr} ({snapshot.atr_percent:.1f}%)
- Trend: {snapshot.trend.upper()}

GAP: {snapshot.gap_pct:+.1f}% ({snapshot.gap_direction}) {"✓ Holding" if snapshot.holding_gap else "✗ Failed"}

SETUP STATUS:
- Extended from EMA9: {"YES" if snapshot.extended_from_ema9 else "No"} ({snapshot.extension_pct:+.1f}%)
- Position: {"Bullish (above key MAs)" if snapshot.above_vwap and snapshot.above_ema9 else "Bearish (below key MAs)" if not snapshot.above_vwap and not snapshot.above_ema9 else "Mixed"}

SQUEEZE: {"ON - Volatility compressed, breakout imminent" if snapshot.squeeze_on else "OFF"} | Momentum: {snapshot.squeeze_fire:+.2f}
BB Width: {snapshot.bb_width:.2f}% | BB: ${snapshot.bb_lower}-${snapshot.bb_upper} | KC: ${snapshot.kc_lower}-${snapshot.kc_upper}

OPENING RANGE: ${snapshot.or_low} - ${snapshot.or_high} | Status: {snapshot.or_breakout.upper()}

RELATIVE STRENGTH vs SPY: {snapshot.rs_vs_spy:+.1f}% {"(Outperforming)" if snapshot.rs_vs_spy > 1 else "(Underperforming)" if snapshot.rs_vs_spy < -1 else "(In-line)"}
"""


# Global instance
_technical_service: Optional[RealTimeTechnicalService] = None


def get_technical_service() -> RealTimeTechnicalService:
    """Get or create the technical service"""
    global _technical_service
    if _technical_service is None:
        _technical_service = RealTimeTechnicalService()
        # Inject MongoDB for historical data access
        try:
            from database import get_database
            db = get_database()
            _technical_service.set_db(db)
            logger.info("RealTimeTechnicalService initialized with ib_historical_data")
        except Exception as e:
            logger.warning(f"Could not inject database into technical service: {e}")
    return _technical_service
