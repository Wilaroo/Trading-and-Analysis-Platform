"""
RS Leadership Service — v19.34.322 (c3 / T7 of the regime-first funnel).

IBD-style multi-period Relative Strength rating for every symbol in the
qualified universe (`symbol_adv_cache`), plus a sector-relative RS diff
vs the symbol's home SPDR ETF.

    score   = Σ w_i × (close / close_lag_i − 1) / Σ w_i
              over lags [63d ×2, 126d, 189d, 252d] (adaptive — only the
              lags the symbol has history for; ≥64 daily closes required)
    rating  = percentile rank of score across the universe, 1..99

Persisted nightly to Mongo `rs_leadership` (one doc per symbol + a meta
doc) by the TradingScheduler job; loaded into an in-memory dict with a
15-min TTL for synchronous reads by the scanner / confidence gate.

SOFT signal by design (2026-04-30 doctrine): RS never hard-gates an
alert — it adds confluence points at the gate and ranks the Regime
Focus List. Symbols with thin history get rating=None (excluded from
the focus list, never penalized).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# (lag in trading days, weight) — IBD RS formula shape: most recent
# quarter double-weighted. Adaptive: missing lags just drop out.
RS_PERIODS = [(63, 2.0), (126, 1.0), (189, 1.0), (252, 1.0)]
RS_MIN_CLOSES = 64          # need at least the 63d lag + today
RS_MAX_DAILY_BARS = 260     # load window per symbol

# The 11 SPDR sector ETFs (sector-relative RS benchmark per symbol).
SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP",
               "XLU", "XLB", "XLRE", "XLC"]


def weighted_rs_score(closes: List[float]) -> Optional[float]:
    """Pure: weighted multi-period return from a chronological close series.

    `closes` oldest→newest. Returns None when history is too thin
    (< RS_MIN_CLOSES) or prices are degenerate.
    """
    if not closes or len(closes) < RS_MIN_CLOSES:
        return None
    last = closes[-1]
    if not last or last <= 0:
        return None
    acc = 0.0
    total_w = 0.0
    for lag, w in RS_PERIODS:
        if len(closes) > lag:
            base = closes[-1 - lag]
            if base and base > 0:
                acc += w * (last / base - 1.0)
                total_w += w
    if total_w <= 0:
        return None
    return acc / total_w


def percentile_ranks(scores: Dict[str, float]) -> Dict[str, int]:
    """Pure: map raw scores → 1..99 percentile rating across the universe."""
    if not scores:
        return {}
    items = sorted(scores.items(), key=lambda kv: kv[1])
    n = len(items)
    out: Dict[str, int] = {}
    if n == 1:
        out[items[0][0]] = 50
        return out
    for idx, (sym, _s) in enumerate(items):
        out[sym] = int(round(1 + 98 * idx / (n - 1)))
    return out


class RSLeadershipService:
    """Nightly compute + cached read of RS leadership ratings."""

    COLLECTION = "rs_leadership"
    RELOAD_TTL_S = 900          # in-memory cache reload interval
    COMPUTE_BATCH = 50          # parallel Mongo loads per batch

    def __init__(self, db=None):
        self.db = db
        self._ratings: Dict[str, Dict] = {}
        self._loaded_at: Optional[float] = None
        self._computing = False

    # ── reads ───────────────────────────────────────────────────────────

    def get_rating_cached(self, symbol: str) -> Optional[Dict]:
        """Sync read from the in-memory dict (None when unknown/not loaded)."""
        return self._ratings.get(symbol.upper())

    async def ensure_loaded(self) -> None:
        """(Re)load the in-memory ratings dict from Mongo when stale."""
        now = time.monotonic()
        if self._loaded_at is not None and (now - self._loaded_at) < self.RELOAD_TTL_S:
            return
        if self.db is None:
            self._loaded_at = now
            return
        try:
            cursor = self.db[self.COLLECTION].find(
                {"symbol": {"$exists": True}}, {"_id": 0})
            to_list = getattr(cursor, "to_list", None)
            if to_list is not None and asyncio.iscoroutinefunction(to_list):
                docs = await cursor.to_list(length=20000)
            else:
                docs = list(cursor)
            self._ratings = {d["symbol"]: d for d in docs if d.get("symbol")}
            self._loaded_at = now
            logger.info(f"[RS-LEADERSHIP] loaded {len(self._ratings)} ratings from Mongo")
        except Exception as e:
            logger.warning(f"[RS-LEADERSHIP] load failed: {e}")
            self._loaded_at = now  # don't hammer on failure

    async def get_rating(self, symbol: str) -> Optional[Dict]:
        await self.ensure_loaded()
        return self.get_rating_cached(symbol)

    def top_ratings(self, direction: str = "long", limit: int = 50) -> List[Dict]:
        """Sync ranked slice of the loaded ratings (desc for long, asc for short)."""
        rows = [r for r in self._ratings.values() if r.get("rs_rating") is not None]
        rows.sort(key=lambda r: r["rs_rating"], reverse=(direction != "short"))
        return rows[:limit]

    def stats(self) -> Dict:
        return {
            "loaded": len(self._ratings),
            "loaded_at_age_s": (None if self._loaded_at is None
                                else round(time.monotonic() - self._loaded_at, 1)),
            "computing": self._computing,
        }

    # ── nightly compute ─────────────────────────────────────────────────

    async def compute_all(self, max_symbols: int = 6000) -> Dict:
        """Compute RS ratings for the whole qualified universe and persist.

        Designed for the nightly scheduler job (17:30 ET) — Mongo reads
        only, no IB calls. Returns a summary dict.
        """
        if self.db is None:
            return {"success": False, "error": "no db"}
        if self._computing:
            return {"success": False, "error": "compute already running"}
        self._computing = True
        started = time.monotonic()
        try:
            symbols = await self._universe_symbols(max_symbols)
            if not symbols:
                return {"success": False, "error": "empty universe (symbol_adv_cache)"}

            # Sector ETF benchmark scores (for sector-relative diff).
            etf_scores: Dict[str, float] = {}
            for etf in SECTOR_ETFS:
                closes = await self._load_daily_closes(etf)
                s = weighted_rs_score(closes)
                if s is not None:
                    etf_scores[etf] = s

            # Sector tag per symbol (static map, instant).
            try:
                from services.sector_tag_service import get_sector_tag_service
                tag_svc = get_sector_tag_service(db=self.db)
                sector_map = tag_svc.tag_many(symbols)
            except Exception:
                sector_map = {}

            scores: Dict[str, float] = {}
            thin = 0
            for b_start in range(0, len(symbols), self.COMPUTE_BATCH):
                batch = symbols[b_start:b_start + self.COMPUTE_BATCH]
                results = await asyncio.gather(
                    *[self._load_daily_closes(s) for s in batch],
                    return_exceptions=True)
                for sym, closes in zip(batch, results):
                    if isinstance(closes, Exception) or not closes:
                        thin += 1
                        continue
                    s = weighted_rs_score(closes)
                    if s is None:
                        thin += 1
                    else:
                        scores[sym] = s
                await asyncio.sleep(0)  # yield the event loop between batches

            ranks = percentile_ranks(scores)
            now_iso = datetime.now(timezone.utc).isoformat()
            upserts = 0
            for sym, score in scores.items():
                etf = sector_map.get(sym)
                sector_rs_diff = (round(score - etf_scores[etf], 5)
                                  if etf and etf in etf_scores else None)
                doc = {
                    "symbol": sym,
                    "rs_rating": ranks.get(sym),
                    "rs_score": round(score, 5),
                    "sector": etf,
                    "sector_rs_diff": sector_rs_diff,
                    "computed_at": now_iso,
                }
                try:
                    res = self.db[self.COLLECTION].update_one(
                        {"symbol": sym}, {"$set": doc}, upsert=True)
                    if asyncio.iscoroutine(res):
                        await res
                    upserts += 1
                except Exception as e:
                    logger.debug(f"[RS-LEADERSHIP] upsert {sym} failed: {e}")

            # Meta doc + prune symbols that fell out of the universe.
            try:
                res = self.db[self.COLLECTION].update_one(
                    {"_id": "meta"},
                    {"$set": {"computed_at": now_iso, "universe_size": len(symbols),
                              "rated": len(scores), "thin_history": thin}},
                    upsert=True)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

            # Force in-memory reload on next read.
            self._loaded_at = None
            elapsed = round(time.monotonic() - started, 1)
            summary = {"success": True, "universe": len(symbols), "rated": len(scores),
                       "thin_history": thin, "etf_benchmarks": len(etf_scores),
                       "elapsed_s": elapsed}
            logger.info(f"[RS-LEADERSHIP] compute complete: {summary}")
            return summary
        except Exception as e:
            logger.error(f"[RS-LEADERSHIP] compute failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            self._computing = False

    # ── data loaders ────────────────────────────────────────────────────

    async def _universe_symbols(self, max_symbols: int) -> List[str]:
        try:
            cursor = self.db["symbol_adv_cache"].find(
                {}, {"_id": 0, "symbol": 1}).limit(max_symbols)
            to_list = getattr(cursor, "to_list", None)
            if to_list is not None and asyncio.iscoroutinefunction(to_list):
                docs = await cursor.to_list(length=max_symbols)
            else:
                docs = list(cursor)
            return sorted({d["symbol"].upper() for d in docs if d.get("symbol")})
        except Exception as e:
            logger.warning(f"[RS-LEADERSHIP] universe load failed: {e}")
            return []

    async def _load_daily_closes(self, symbol: str) -> List[float]:
        """Chronological daily closes (oldest→newest), deduped by date."""
        try:
            cursor = self.db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "date": 1, "close": 1},
            ).sort("date", -1).limit(RS_MAX_DAILY_BARS)
            to_list = getattr(cursor, "to_list", None)
            if to_list is not None and asyncio.iscoroutinefunction(to_list):
                bars = await cursor.to_list(length=RS_MAX_DAILY_BARS)
            else:
                bars = list(cursor)
            seen: Dict[str, float] = {}
            for b in bars:
                dk = str(b.get("date", ""))[:10]
                c = b.get("close")
                if len(dk) == 10 and dk not in seen and c and c > 0:
                    seen[dk] = float(c)
            return [seen[k] for k in sorted(seen.keys())]
        except Exception:
            return []


_rs_leadership_service: Optional[RSLeadershipService] = None


def get_rs_leadership_service(db=None) -> RSLeadershipService:
    global _rs_leadership_service
    if _rs_leadership_service is None:
        _rs_leadership_service = RSLeadershipService(db=db)
    elif db is not None and _rs_leadership_service.db is None:
        _rs_leadership_service.db = db
    return _rs_leadership_service
