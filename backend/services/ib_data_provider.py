"""
IBDataProvider — central source of truth for live + historical market data.

This is the ONLY way any part of the app should read quotes, bars, positions,
or account info. It implements the exact same public interface that the
legacy `AlpacaService` used, so every caller keeps working transparently
while now being backed by:

    Live quotes       → routers.ib._pushed_ib_data["quotes"]  (IB pusher)
    Live positions    → routers.ib._pushed_ib_data["positions"]
    Live account      → routers.ib._pushed_ib_data["account"]
    Historical bars   → MongoDB `ib_historical_data` (178M+ rows)
    Most actives      → aggregated from ib_historical_data volume
    RVol              → ib_historical_data 20-day volume baseline

Design rules:
    • NEVER falls back to Alpaca. If IB pusher is stale → surface staleness
      in the response (`source`, `age_s`, `stale=True`) so callers can
      decide whether to act or pause. Silent-drift bugs are not allowed.
    • Read-only. Never mutates pusher state.
    • All methods are async-safe — in-memory reads are fast and synchronous,
      Mongo reads go through asyncio.to_thread so we never block the loop.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# How many seconds a pusher heartbeat can lag before we call it "dead".
# Scanner + bot should pause / freeze when the pusher is dead.
PUSHER_DEAD_THRESHOLD_S = 30

# Map Alpaca-style timeframe strings → ib_historical_data bar_size values.
# Keeps old callers working without any edits.
_TIMEFRAME_TO_BAR_SIZE = {
    "1Min": "1 min",
    "5Min": "5 mins",
    "15Min": "15 mins",
    "30Min": "30 mins",
    "1Hour": "1 hour",
    "1Day": "1 day",
    "1Week": "1 week",
    # Pass-through for callers that already use IB bar_size strings
    "1 min": "1 min",
    "5 mins": "5 mins",
    "15 mins": "15 mins",
    "30 mins": "30 mins",
    "1 hour": "1 hour",
    "1 day": "1 day",
    "1 week": "1 week",
}


def _normalise_bar_size(timeframe: str) -> str:
    """Accept either 'Alpaca-style' ('1Day', '5Min') or IB-native ('1 day')."""
    return _TIMEFRAME_TO_BAR_SIZE.get(timeframe, "1 day")


class IBDataProvider:
    """IB-first market data provider. Drop-in replacement for AlpacaService."""

    # Kept for BC — some callers import DISABLED to short-circuit guards.
    DISABLED = False

    def __init__(self):
        self._db = None
        self._cache_ttl = 10
        self._quote_cache: Dict[str, Dict[str, Any]] = {}

    # ── Mongo wiring ──────────────────────────────────────────
    def set_db(self, db):
        """Wire the MongoDB handle for historical-bar reads."""
        self._db = db

    def _get_db(self):
        if self._db is not None:
            return self._db
        try:
            from database import get_database
            self._db = get_database()
        except Exception:
            pass
        return self._db

    # ── Pusher state helpers ──────────────────────────────────
    @staticmethod
    def _pushed_state() -> Dict[str, Any]:
        """Return the live pusher dict (empty dict if pusher module not loaded)."""
        try:
            from routers.ib import _pushed_ib_data
            return _pushed_ib_data or {}
        except Exception:
            return {}

    @staticmethod
    def _pusher_age_s() -> Optional[float]:
        state = IBDataProvider._pushed_state()
        last = state.get("last_update")
        if not last:
            return None
        try:
            # last_update is stored server-side as UTC ISO on /push-data
            t = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t).total_seconds()
        except Exception:
            return None

    @classmethod
    def is_pusher_fresh(cls) -> bool:
        age = cls._pusher_age_s()
        return age is not None and age < PUSHER_DEAD_THRESHOLD_S

    @classmethod
    def is_pusher_dead(cls) -> bool:
        age = cls._pusher_age_s()
        return age is None or age >= PUSHER_DEAD_THRESHOLD_S

    # ── Quotes ────────────────────────────────────────────────
    async def get_quote(self, symbol: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Live quote for a symbol from the IB pusher.

        Returns None if the pusher has no quote for this symbol. The caller
        must treat None as "no live data — do not trade".
        """
        if not symbol:
            return None
        sym = symbol.upper()
        state = self._pushed_state()
        quotes = state.get("quotes") or {}
        q = quotes.get(sym)
        if not q:
            return None

        price = q.get("price") or q.get("last")
        if not price or price <= 0:
            return None

        age = self._pusher_age_s()
        return {
            "symbol": sym,
            "price": float(price),
            "bid": float(q.get("bid") or 0),
            "ask": float(q.get("ask") or 0),
            "bid_size": int(q.get("bid_size") or 0),
            "ask_size": int(q.get("ask_size") or 0),
            "volume": int(q.get("volume") or 0),
            "change": float(q.get("change") or 0),
            "change_pct": float(q.get("change_pct") or q.get("changePct") or 0),
            "timestamp": state.get("last_update") or datetime.now(timezone.utc).isoformat(),
            "source": "ib_pusher",
            "age_s": age,
            "stale": (age is not None and age >= PUSHER_DEAD_THRESHOLD_S),
            "_cached_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Alias kept for BC with AlpacaService."""
        return await self.get_quote(symbol)

    async def get_quotes_batch(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batched live quotes. The pusher dict is already batched in memory."""
        out: Dict[str, Dict[str, Any]] = {}
        if not symbols:
            return out
        for s in symbols:
            q = await self.get_quote(s)
            if q:
                out[s.upper()] = q
        return out

    # ── RVol ──────────────────────────────────────────────────
    async def calculate_rvol(self, symbol: str) -> Optional[float]:
        """Current volume / 20-day average, time-of-day adjusted."""
        try:
            quote = await self.get_quote(symbol, force_refresh=True)
            if not quote:
                return None
            current_volume = quote.get("volume", 0)
            if not current_volume:
                return None

            bars = await self.get_bars(symbol, timeframe="1Day", limit=20)
            if not bars or len(bars) < 5:
                return None

            volumes = [b.get("volume", 0) for b in bars if b.get("volume", 0) > 0]
            if not volumes:
                return None
            avg_volume = sum(volumes) / len(volumes)
            if avg_volume == 0:
                return None

            try:
                import pytz
                et = pytz.timezone("US/Eastern")
                now_et = datetime.now(et)
                market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
                if now_et < market_open:
                    time_fraction = 1.0
                else:
                    minutes_since_open = (now_et - market_open).total_seconds() / 60
                    time_fraction = min(minutes_since_open / 390, 1.0)
            except Exception:
                time_fraction = 1.0

            expected_volume = avg_volume * time_fraction if time_fraction > 0 else avg_volume
            if expected_volume <= 0:
                return None
            return round(current_volume / expected_volume, 2)
        except Exception as e:
            logger.debug(f"RVol calc error for {symbol}: {e}")
            return None

    async def get_quotes_with_rvol(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Quotes + RVol for up to 10 symbols (rvol calc is mongo-heavy)."""
        quotes = await self.get_quotes_batch(symbols)

        async def add_rvol(sym: str):
            rvol = await self.calculate_rvol(sym)
            if sym in quotes and rvol is not None:
                quotes[sym]["rvol"] = rvol
                quotes[sym]["rvol_status"] = (
                    "exceptional" if rvol >= 5 else
                    "high" if rvol >= 3 else
                    "strong" if rvol >= 2 else
                    "in_play" if rvol >= 1.5 else
                    "normal"
                )

        await asyncio.gather(*[add_rvol(s.upper()) for s in symbols[:10]])
        return quotes

    # ── Historical bars ───────────────────────────────────────
    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 100,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Historical bars from ib_historical_data (178M-row collection)."""
        if not symbol:
            return []
        sym = symbol.upper()
        bar_size = _normalise_bar_size(timeframe)
        db = self._get_db()
        if db is None:
            return []

        def _fetch():
            try:
                cursor = db["ib_historical_data"].find(
                    {"symbol": sym, "bar_size": bar_size},
                    {"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "vwap": 1},
                    sort=[("date", -1)],
                    limit=int(limit),
                )
                docs = list(cursor)
            except Exception as e:
                logger.debug(f"ib_historical_data read failed for {sym} {bar_size}: {e}")
                return []
            # Oldest first (standard chart order)
            docs.reverse()
            out = []
            for d in docs:
                out.append({
                    "timestamp": str(d.get("date", "")),
                    "open": float(d.get("open") or 0),
                    "high": float(d.get("high") or 0),
                    "low": float(d.get("low") or 0),
                    "close": float(d.get("close") or 0),
                    "volume": int(d.get("volume") or 0),
                    "vwap": float(d["vwap"]) if d.get("vwap") is not None else None,
                    "trade_count": None,
                    "source": "ib_historical_data",
                })
            return out

        return await asyncio.to_thread(_fetch)

    async def get_historical_bars(
        self, symbol: str, timeframe: str = "1Day", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Alias kept for BC with AlpacaService."""
        return await self.get_bars(symbol, timeframe=timeframe, limit=limit)

    # ── Account & positions ───────────────────────────────────
    async def get_account(self) -> Optional[Dict[str, Any]]:
        state = self._pushed_state()
        acct = state.get("account") or {}
        if not acct:
            return None
        # Normalise IB keys to the shape legacy callers expect.
        return {
            "account_id": acct.get("account") or acct.get("account_id"),
            "status": acct.get("status") or "ACTIVE",
            "currency": acct.get("currency") or "USD",
            "cash": float(acct.get("TotalCashValue") or acct.get("cash") or 0),
            "portfolio_value": float(acct.get("NetLiquidation") or acct.get("portfolio_value") or 0),
            "buying_power": float(acct.get("BuyingPower") or acct.get("buying_power") or 0),
            "equity": float(acct.get("NetLiquidation") or acct.get("equity") or 0),
            "last_equity": float(acct.get("PreviousDayEquityWithLoanValue") or acct.get("last_equity") or 0),
            "pattern_day_trader": bool(acct.get("pattern_day_trader") or False),
            "trading_blocked": False,
            "transfers_blocked": False,
            "account_blocked": False,
            "daytrade_count": int(acct.get("DayTradesRemaining") or 0),
            "daytrading_buying_power": float(acct.get("DayTradingBuyingPower") or 0),
            "source": "ib_pusher",
            "age_s": self._pusher_age_s(),
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        state = self._pushed_state()
        positions = state.get("positions") or []
        out = []
        age = self._pusher_age_s()
        for p in positions:
            qty = float(p.get("position") or p.get("qty") or 0)
            if qty == 0:
                continue  # skip flat positions
            avg_entry = float(p.get("avgCost") or p.get("avg_entry_price") or 0)
            market_price = float(p.get("marketPrice") or p.get("market_price") or p.get("current_price") or 0)
            market_value = float(p.get("marketValue") or p.get("market_value") or (qty * market_price))
            cost_basis = float(p.get("cost_basis") or (qty * avg_entry))
            unrealized_pl = float(p.get("unrealizedPNL") or p.get("unrealized_pl") or (market_value - cost_basis))
            out.append({
                "symbol": (p.get("symbol") or "").upper(),
                "qty": qty,
                "avg_entry_price": avg_entry,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "unrealized_pl": unrealized_pl,
                "unrealized_plpc": (unrealized_pl / cost_basis) if cost_basis else 0,
                "current_price": market_price,
                "side": "long" if qty > 0 else "short",
                "change_today": float(p.get("change_today") or 0),
                "source": "ib_pusher",
                "age_s": age,
            })
        return out

    # ── Housekeeping ──────────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        age = self._pusher_age_s()
        return {
            "service": "ib_data_provider",
            "initialized": True,
            "pusher_last_update": self._pushed_state().get("last_update"),
            "pusher_age_s": age,
            "pusher_fresh": age is not None and age < PUSHER_DEAD_THRESHOLD_S,
            "dead_threshold_s": PUSHER_DEAD_THRESHOLD_S,
            "quote_symbols_cached": len(self._pushed_state().get("quotes") or {}),
            "positions_count": len(self._pushed_state().get("positions") or []),
        }

    def clear_cache(self):
        self._quote_cache.clear()

    # ── Scanner-style helpers (kept for BC) ───────────────────
    async def get_most_active_stocks(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Top-volume symbols from today's pushed quotes, fallback to mongo."""
        state = self._pushed_state()
        quotes = state.get("quotes") or {}
        if quotes:
            ranked = sorted(
                [(s, int(q.get("volume") or 0)) for s, q in quotes.items()],
                key=lambda x: x[1], reverse=True,
            )[:limit]
            if ranked and ranked[0][1] > 0:
                return [{"symbol": s, "name": s, "volume": v, "scan_type": "MOST_ACTIVE_LIVE"} for s, v in ranked]

        # Fallback: aggregate yesterday's daily volume from ib_historical_data
        db = self._get_db()
        if db is None:
            return self._get_default_watchlist()

        def _agg():
            cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
            pipeline = [
                {"$match": {"bar_size": "1 day", "date": {"$gte": cutoff}}},
                {"$sort": {"date": -1}},
                {"$group": {"_id": "$symbol", "volume": {"$first": "$volume"}}},
                {"$sort": {"volume": -1}},
                {"$limit": limit},
            ]
            try:
                return list(db["ib_historical_data"].aggregate(pipeline, allowDiskUse=True, maxTimeMS=8000))
            except Exception:
                return []

        rows = await asyncio.to_thread(_agg)
        if not rows:
            return self._get_default_watchlist()
        return [
            {"symbol": r["_id"], "name": r["_id"], "volume": int(r.get("volume") or 0), "scan_type": "MOST_ACTIVE_HISTORICAL"}
            for r in rows
        ]

    async def get_all_assets(self) -> List[str]:
        """Distinct symbol universe from ib_historical_data."""
        db = self._get_db()
        if db is None:
            return []
        def _distinct():
            try:
                return db["ib_historical_data"].distinct("symbol", {"bar_size": "1 day"}, maxTimeMS=10000)
            except Exception:
                return []
        return await asyncio.to_thread(_distinct)

    def _get_default_watchlist(self) -> List[Dict[str, Any]]:
        default = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
            "SPY", "QQQ", "NFLX", "DIS", "BA", "JPM", "V", "MA", "UNH",
            "PFE", "MRNA", "XOM", "CVX", "COST", "WMT", "HD", "LOW",
            "CRM", "ORCL", "INTC", "MU", "QCOM",
        ]
        return [{"symbol": s, "name": s, "volume": 0, "scan_type": "DEFAULT_WATCHLIST"} for s in default]


# ── Singleton wiring ─────────────────────────────────────────
_ib_data_provider: Optional[IBDataProvider] = None


def get_live_data_service() -> IBDataProvider:
    """Canonical accessor — prefer this name in new code."""
    global _ib_data_provider
    if _ib_data_provider is None:
        _ib_data_provider = IBDataProvider()
    return _ib_data_provider


def init_live_data_service(db=None) -> IBDataProvider:
    svc = get_live_data_service()
    if db is not None:
        svc.set_db(db)
    return svc
