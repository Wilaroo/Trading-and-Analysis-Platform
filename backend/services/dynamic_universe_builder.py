"""Dynamic Universe Builder — v19.34.211
========================================

Composes a *priority-ranked daily scan universe* each premarket (and on a
periodic intraday cadence) instead of relying purely on the static
ADV-ranked `symbol_adv_cache` rotation.

Sources (every one degrades gracefully — a failure NEVER yields an empty
universe; we always fall back to liquid-core + whatever else succeeded):

  1. **Liquid core**   — top-N most-liquid names (`get_universe_ranked`,
                          intraday tier). Stable base, always present.
  2. **IB movers**     — `ib_service.run_scanner()` over TOP_PERC_GAIN,
                          TOP_PERC_LOSE, GAP_UP, GAP_DOWN, MOST_ACTIVE,
                          HOT_BY_VOLUME (fallback: `ib_data_provider`
                          MOST_ACTIVE derivation). Gated to the qualified
                          universe (ADV ≥ $2M).
  3. **Catalysts**     — today's earnings (`earnings_service`) + fresh-news
                          tickers (`news_service`). Gated to qualified.
  4. **Held + watchlist** — open `bot_trades` positions and operator's
                          manual smart-watchlist names. ALWAYS included,
                          top priority, exempt from the qualification gate.
  5. **Regime tilt**   — `market_regime_engine` state biases mover scoring
                          (CONFIRMED_UP favours gainers/gap-ups, CONFIRMED_
                          DOWN favours losers/gap-downs, HOLD stays neutral).

Output is persisted to the `daily_scan_universe` collection (one doc per ET
trading date) and consumed by:
  * `enhanced_scanner._scan_daily_setups` / `_scan_premarket_setups`
    (front-loads priority names every pass, keeps the v210 full-universe
    rotation underneath), and
  * `wave_scanner.get_scan_batch` (injects the top priority names into RTH
    Tier-1 so live scalps catch today's movers every ~15s).

Top findings are also pushed into today's game plan (`dynamic_movers`) so
the gameplan / briefings surface them.

Public API:
    b = get_dynamic_universe_builder(db)
    await b.maybe_rebuild()                 # cadence-gated (scanner calls this)
    await b.build(force=True)               # unconditional rebuild
    b.get_priority_symbols(limit=40)        # for Tier-1 / front-load
    b.get_doc()                             # full persisted doc
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# ── Scoring weights ──────────────────────────────────────────────────────
W_HELD = 100          # open position — never drop coverage of a name we hold
W_WATCHLIST = 60      # operator manual pin
W_CATALYST_EARNINGS = 30
W_CATALYST_NEWS = 18
W_MOVER_ALIGNED = 40  # mover list that agrees with the regime
W_MOVER_NEUTRAL = 25  # MOST_ACTIVE / HOT_BY_VOLUME (direction-agnostic)
W_MOVER_COUNTER = 12  # mover list that fights the regime
W_CORE_BASE = 8       # liquid-core presence

# IB scanner lists we pull every build (both directions; regime tilts scoring)
_MOVER_SCANS = [
    "TOP_PERC_GAIN", "TOP_PERC_LOSE",
    "GAP_UP", "GAP_DOWN",
    "MOST_ACTIVE", "HOT_BY_VOLUME",
]
_NEUTRAL_SCANS = {"MOST_ACTIVE", "HOT_BY_VOLUME"}
_BULLISH_SCANS = {"TOP_PERC_GAIN", "GAP_UP", "HIGH_OPEN_GAP"}
_BEARISH_SCANS = {"TOP_PERC_LOSE", "GAP_DOWN", "LOW_OPEN_GAP"}

# Config knobs (env-overridable on the scanner side, kept simple here)
CORE_LIMIT = 600          # liquid core size
MOVERS_PER_SCAN = 50      # rows per IB scan list
PRIORITY_LIMIT = 40       # top names injected into Tier-1 / gameplan
REBUILD_TTL_MIN = 45      # intraday rebuild cadence

_COLL = "daily_scan_universe"


def _et_trading_date() -> str:
    return datetime.now(_ET).strftime("%Y-%m-%d")


class DynamicUniverseBuilder:
    def __init__(self, db=None):
        self.db = db
        self._last_build: Optional[datetime] = None

    def set_db(self, db) -> None:
        self.db = db

    # ───────────────────────── read helpers ─────────────────────────
    def get_doc(self, date: Optional[str] = None) -> Optional[Dict]:
        if self.db is None:
            return None
        try:
            return self.db[_COLL].find_one({"_id": date or _et_trading_date()})
        except Exception as e:
            logger.debug(f"dynamic-universe get_doc failed: {e}")
            return None

    def get_priority_symbols(self, limit: int = PRIORITY_LIMIT) -> List[str]:
        doc = self.get_doc()
        if not doc:
            return []
        return list(doc.get("priority_symbols", []))[: int(limit)]

    def get_universe_symbols(self, limit: Optional[int] = None) -> List[str]:
        doc = self.get_doc()
        if not doc:
            return []
        syms = [s.get("symbol") for s in doc.get("symbols", []) if s.get("symbol")]
        return syms[: int(limit)] if limit else syms

    def is_fresh(self, ttl_min: int = REBUILD_TTL_MIN) -> bool:
        doc = self.get_doc()
        if not doc or not doc.get("built_at"):
            return False
        try:
            built = datetime.fromisoformat(doc["built_at"])
            if built.tzinfo is None:
                built = built.replace(tzinfo=timezone.utc)
        except Exception:
            return False
        return (datetime.now(timezone.utc) - built) < timedelta(minutes=ttl_min)

    # ───────────────────────── orchestration ────────────────────────
    async def maybe_rebuild(self, ttl_min: int = REBUILD_TTL_MIN) -> Optional[Dict]:
        """Rebuild only if there is no fresh doc for today's ET date."""
        if self.db is None:
            return None
        if self.is_fresh(ttl_min):
            return None
        try:
            return await self.build()
        except Exception as e:
            logger.warning(f"dynamic-universe maybe_rebuild failed: {e}")
            return None

    async def build(self, force: bool = False) -> Dict:
        """Compose + persist today's universe. Never raises for a single
        failed source; only a total DB failure propagates."""
        if self.db is None:
            raise RuntimeError("DynamicUniverseBuilder has no db")

        t0 = datetime.now(timezone.utc)
        date = _et_trading_date()

        regime_state, regime_score = await self._regime()
        qualified = self._qualified_set()

        # scores[symbol] = {"score": int, "sources": [..]}
        scores: Dict[str, Dict] = {}

        def add(symbol: str, pts: int, source: str):
            if not symbol:
                return
            sym = symbol.upper()
            ent = scores.setdefault(sym, {"score": 0, "sources": []})
            # v19.34.211b — count each distinct source ONCE. Catalyst feeds
            # (earnings/news) can list the same ticker multiple times; without
            # this guard the points double-count while the source tag dedupes,
            # inflating scores (e.g. VSCO reading 68 instead of 30).
            if source in ent["sources"]:
                return
            ent["score"] += pts
            ent["sources"].append(source)

        # 1. liquid core
        core = self._liquid_core(CORE_LIMIT)
        for i, sym in enumerate(core):
            # tiny rank bonus so the very top of the core edges out the tail
            add(sym, W_CORE_BASE + max(0, 12 - i // 50), "core")

        # 2. IB movers (gated to qualified)
        movers, degraded = await self._ib_movers()
        for sym, scans in movers.items():
            if sym not in qualified:
                continue
            for scan in scans:
                add(sym, self._mover_points(scan, regime_state), f"mover:{scan}")

        # 3. catalysts (gated to qualified)
        earnings_syms, news_syms = await self._catalysts()
        for sym in earnings_syms:
            if sym in qualified:
                add(sym, W_CATALYST_EARNINGS, "catalyst:earnings")
        for sym in news_syms:
            if sym in qualified:
                add(sym, W_CATALYST_NEWS, "catalyst:news")

        # 4. held + watchlist (always, exempt from gate)
        for sym in self._held_symbols():
            add(sym, W_HELD, "held")
        for sym in self._watchlist_symbols():
            add(sym, W_WATCHLIST, "watchlist")

        # rank
        ranked = sorted(
            ({"symbol": s, "score": v["score"], "sources": v["sources"]}
             for s, v in scores.items()),
            key=lambda d: d["score"],
            reverse=True,
        )

        # priority = top names that are actionable today (not pure-core)
        actionable = [
            d for d in ranked
            if any(not src.startswith("core") for src in d["sources"])
        ]
        priority_symbols = [d["symbol"] for d in actionable[:PRIORITY_LIMIT]]

        counts = {
            "core": len(core),
            "movers": sum(1 for d in ranked if any(x.startswith("mover") for x in d["sources"])),
            "catalysts": sum(1 for d in ranked if any(x.startswith("catalyst") for x in d["sources"])),
            "held": sum(1 for d in ranked if "held" in d["sources"]),
            "watchlist": sum(1 for d in ranked if "watchlist" in d["sources"]),
            "total": len(ranked),
        }

        doc = {
            "_id": date,
            "date": date,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "regime_state": regime_state,
            "regime_score": regime_score,
            "symbols": ranked,
            "priority_symbols": priority_symbols,
            "counts": counts,
            "degraded": degraded,
            "build_ms": int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
        }

        self.db[_COLL].update_one({"_id": date}, {"$set": doc}, upsert=True)
        self._last_build = datetime.now(timezone.utc)
        logger.info(
            f"📡 Dynamic universe built [{date}] regime={regime_state} "
            f"core={counts['core']} movers={counts['movers']} "
            f"catalysts={counts['catalysts']} held={counts['held']} "
            f"total={counts['total']} priority={len(priority_symbols)} "
            f"degraded={degraded} ({doc['build_ms']}ms)"
        )

        # connect top findings to the game plan / briefings (non-fatal)
        try:
            await self._push_to_gameplan(date, actionable[:PRIORITY_LIMIT], regime_state)
        except Exception as e:
            logger.debug(f"dynamic-universe gameplan push skipped: {e}")

        return doc

    # ───────────────────────── sources ──────────────────────────────
    def _qualified_set(self) -> Set[str]:
        try:
            from services.symbol_universe import get_universe
            return set(get_universe(self.db, tier="investment"))
        except Exception as e:
            logger.debug(f"qualified_set failed: {e}")
            return set()

    def _liquid_core(self, limit: int) -> List[str]:
        try:
            from services.symbol_universe import get_universe_ranked
            return get_universe_ranked(self.db, tier="intraday", limit=limit)
        except Exception as e:
            logger.debug(f"liquid_core failed: {e}")
            return []

    @staticmethod
    def _mover_points(scan: str, regime_state: str) -> int:
        if scan in _NEUTRAL_SCANS:
            return W_MOVER_NEUTRAL
        if regime_state == "CONFIRMED_UP":
            return W_MOVER_ALIGNED if scan in _BULLISH_SCANS else W_MOVER_COUNTER
        if regime_state == "CONFIRMED_DOWN":
            return W_MOVER_ALIGNED if scan in _BEARISH_SCANS else W_MOVER_COUNTER
        return W_MOVER_NEUTRAL  # HOLD / unknown → neutral

    async def _regime(self):
        try:
            from services.market_regime_engine import get_market_regime_engine
            eng = get_market_regime_engine(db=self.db)
            r = await eng.get_current_regime()
            return r.get("state", "HOLD"), float(r.get("composite_score", 50.0))
        except Exception as e:
            logger.debug(f"regime fetch failed: {e}")
            return "HOLD", 50.0

    async def _ib_movers(self):
        """Return ({symbol: [scan_types]}, degraded_bool)."""
        out: Dict[str, List[str]] = {}
        got_any = False
        try:
            from services.ib_service import get_ib_service
            ib = get_ib_service()
        except Exception as e:
            logger.debug(f"ib_service unavailable: {e}")
            ib = None

        if ib is not None:
            for scan in _MOVER_SCANS:
                try:
                    rows = await ib.run_scanner(scan_type=scan, max_results=MOVERS_PER_SCAN)
                    for row in (rows or []):
                        sym = (row.get("symbol") or "").upper()
                        if sym:
                            out.setdefault(sym, [])
                            if scan not in out[sym]:
                                out[sym].append(scan)
                            got_any = True
                except Exception as e:
                    logger.debug(f"run_scanner {scan} failed: {e}")

        if not got_any:
            # Fallback: derive MOST_ACTIVE from pushed/historical volume.
            try:
                from services.ib_data_provider import get_live_data_service
                prov = get_live_data_service()
                rows = await prov.get_most_active_stocks(limit=MOVERS_PER_SCAN)
                for row in (rows or []):
                    sym = (row.get("symbol") or "").upper()
                    if sym:
                        out.setdefault(sym, []).append("MOST_ACTIVE")
                        got_any = True
            except Exception as e:
                logger.debug(f"ib_data_provider fallback failed: {e}")

        return out, (not got_any)

    async def _catalysts(self):
        earnings_syms: List[str] = []
        news_syms: List[str] = []
        try:
            from services.earnings_service import get_earnings_service
            es = get_earnings_service()
            rows = await es.get_upcoming_earnings(days_ahead=1)
            earnings_syms = [(r.get("symbol") or "").upper() for r in (rows or []) if r.get("symbol")]
        except Exception as e:
            logger.debug(f"earnings catalyst failed: {e}")
        try:
            from services.news_service import get_news_service
            ns = get_news_service()
            rows = await ns.get_market_news(max_items=40)
            for r in (rows or []):
                for sym in self._extract_news_tickers(r):
                    news_syms.append(sym.upper())
        except Exception as e:
            logger.debug(f"news catalyst failed: {e}")
        return earnings_syms, news_syms

    @staticmethod
    def _extract_news_tickers(article: Dict) -> List[str]:
        for key in ("symbols", "tickers", "related"):
            v = article.get(key)
            if isinstance(v, list):
                return [str(x) for x in v if x]
            if isinstance(v, str) and v:
                return [t.strip() for t in v.split(",") if t.strip()]
        sym = article.get("symbol")
        return [sym] if sym else []

    def _held_symbols(self) -> List[str]:
        try:
            return [
                s for s in self.db["bot_trades"].distinct(
                    "symbol",
                    {"status": {"$in": ["open", "partial", "OPEN", "PARTIAL"]}},
                ) if s
            ]
        except Exception as e:
            logger.debug(f"held_symbols failed: {e}")
            return []

    def _watchlist_symbols(self) -> List[str]:
        try:
            from services.smart_watchlist_service import get_smart_watchlist
            wl = get_smart_watchlist()
            items = wl.get_watchlist()
            return [it.symbol for it in items if getattr(it, "is_sticky", False) or getattr(it, "source", "") == "manual"]
        except Exception as e:
            logger.debug(f"watchlist_symbols failed: {e}")
            return []

    async def _push_to_gameplan(self, date: str, top: List[Dict], regime_state: str):
        if not top:
            return
        from services.gameplan_service import get_gameplan_service
        gp = get_gameplan_service(self.db)
        # The journal gameplan router keys "today" by UTC date — match it so
        # the dynamic_movers land on the doc the frontend reads.
        gp_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        plan = await gp.get_game_plan(gp_date)
        if not plan:
            plan = await gp.create_game_plan(gp_date, auto_populate=False)
        movers = [
            {
                "symbol": d["symbol"],
                "score": d["score"],
                "sources": d["sources"],
                "label": ", ".join(s.split(":")[-1] for s in d["sources"][:3]),
            }
            for d in top
        ]
        await gp.update_game_plan(gp_date, {
            "dynamic_movers": movers,
            "dynamic_movers_regime": regime_state,
            "dynamic_movers_built_at": datetime.now(timezone.utc).isoformat(),
        })


# ── module singleton ─────────────────────────────────────────────────────
_instance: Optional[DynamicUniverseBuilder] = None


def get_dynamic_universe_builder(db=None) -> DynamicUniverseBuilder:
    global _instance
    if _instance is None:
        _instance = DynamicUniverseBuilder(db=db)
    elif db is not None and _instance.db is None:
        _instance.db = db
    return _instance
