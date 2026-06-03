"""
Catalyst Classifier Service  (v19.34.232, task B)

Answers the one question that decides gap behavior: WHY is this stock gapping?
Returns a single CATEGORICAL tag so the Game Plan / Mission Control can separate
gap-and-go (real catalyst → trends) from unexplained drift (→ fade-prone).

    tag ∈ {earnings, analyst, news, sympathy, no_catalyst}

Composes EXISTING plumbing (no new integration):
  • earnings  → the `earnings_calendar` Mongo collection (kept fresh by the
                EarningsService scheduler; Finnhub-sourced). ZERO hot-path API calls.
  • analyst   → recent ticker headlines hit analyst-action keywords.
  • news      → any other material recent headline (NewsService: IB-first, unlimited).
  • sympathy  → no stock-specific catalyst, but the symbol's sector regime is moving
                in the gap's direction (light v1 — uses the sector classifier).
  • no_catalyst → nothing found (the fade-prone gaps).

Informational only in v1 — it does NOT change sizing/bias yet. Env-gated by
CATALYST_TAGGING_ENABLED (default ON); every path is try/except fail-open so a
Finnhub/news hiccup never blocks an alert.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_TAGS = ("earnings", "analyst", "news", "sympathy", "no_catalyst")

# Analyst-action keywords (self-contained — avoids importing the heavy sentiment
# module just for two lists).
_ANALYST_KW = [
    "upgrade", "downgrade", "outperform", "underperform", "overweight",
    "underweight", "price target", "pt raised", "pt cut", "initiated",
    "initiates coverage", "reiterated", "reiterates", "raised to", "cut to",
    "strong buy", "analyst",
]


def _enabled() -> bool:
    v = os.environ.get("CATALYST_TAGGING_ENABLED", "1")
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def _no_catalyst() -> Dict:
    return {"tag": "no_catalyst", "confidence": 0.4, "source": None,
            "headline": None,
            "summary": "No identifiable catalyst — unexplained gap (fade-prone)."}


class CatalystClassifierService:
    def __init__(self, db=None, news_service=None,
                 sector_classifier=None, sector_tagger=None):
        self.db = db
        self._news = news_service
        self._sector = sector_classifier      # async classify_for_symbol(symbol)
        self._sector_tag = sector_tagger      # sync tag_symbol(symbol) -> ETF
        self._news_cache: Dict[str, Tuple[float, List[str]]] = {}
        self._news_ttl = int(os.environ.get("CATALYST_NEWS_TTL_SEC", "1800"))
        self._earn_cache: Optional[Tuple[float, Dict[str, Dict]]] = None
        self._earn_ttl = int(os.environ.get("CATALYST_EARN_TTL_SEC", "1800"))

    # ── earnings (Mongo, no API call) ─────────────────────────────────────
    def _earnings_today(self) -> Dict[str, Dict]:
        now = time.time()
        if self._earn_cache and now - self._earn_cache[0] < self._earn_ttl:
            return self._earn_cache[1]
        out: Dict[str, Dict] = {}
        if self.db is not None:
            try:
                today = datetime.now(timezone.utc).date()
                yest = today - timedelta(days=1)
                tomo = today + timedelta(days=1)
                cur = self.db["earnings_calendar"].find(
                    {"date": {"$gte": f"{yest.isoformat()}T00:00:00",
                              "$lt": f"{tomo.isoformat()}T00:00:00"}},
                    {"symbol": 1, "hour": 1, "date": 1, "_id": 0},
                )
                for d in cur:
                    s = (d.get("symbol") or "").upper().strip()
                    if s:
                        out[s] = {"hour": d.get("hour"),
                                  "date": (d.get("date") or "")[:10]}
            except Exception as e:
                logger.debug("[catalyst] earnings_calendar read failed: %s", e)
        self._earn_cache = (now, out)
        return out

    # ── news (cached) ─────────────────────────────────────────────────────
    async def _recent_headlines(self, symbol: str) -> List[str]:
        now = time.time()
        c = self._news_cache.get(symbol)
        if c and now - c[0] < self._news_ttl:
            return c[1]
        heads: List[str] = []
        if self._news is not None:
            try:
                items = await self._news.get_ticker_news(symbol, max_items=8) or []
                heads = [(i.get("headline") or "").strip()
                         for i in items if (i.get("headline") or "").strip()]
            except Exception as e:
                logger.debug("[catalyst] news fetch failed %s: %s", symbol, e)
        self._news_cache[symbol] = (now, heads)
        return heads

    @staticmethod
    def _analyst_headline(headlines: List[str]) -> Optional[str]:
        for h in headlines:
            hl = h.lower()
            if any(kw in hl for kw in _ANALYST_KW):
                return h
        return None

    # ── sympathy (sector moving in gap direction) ─────────────────────────
    async def _sector_sympathy(self, symbol: str, direction: str) -> Tuple[bool, Optional[str]]:
        if self._sector is None:
            return (False, None)
        try:
            regime = await self._sector.classify_for_symbol(symbol)
            rv = str(getattr(regime, "value", regime)).lower()
            etf = None
            if self._sector_tag is not None:
                try:
                    etf = self._sector_tag.tag_symbol(symbol)
                except Exception:
                    etf = None
            up = ("up" in rv) or ("bull" in rv) or ("strong" in rv)
            down = ("down" in rv) or ("bear" in rv) or ("weak" in rv)
            if (direction == "long" and up) or (direction == "short" and down):
                return (True, etf or "its sector")
        except Exception as e:
            logger.debug("[catalyst] sector check failed %s: %s", symbol, e)
        return (False, None)

    # ── main ──────────────────────────────────────────────────────────────
    async def classify(self, symbol: str, direction: str = "long",
                       gap_pct: float = 0.0) -> Dict:
        symbol = (symbol or "").upper().strip()
        if not symbol or not _enabled():
            return _no_catalyst()

        # 1) earnings
        em = self._earnings_today()
        if symbol in em:
            hour = (em[symbol].get("hour") or "").lower()
            when = {"bmo": "before open", "amc": "after close",
                    "dmh": "during hours"}.get(hour, "today")
            return {"tag": "earnings", "confidence": 0.9, "source": "earnings_calendar",
                    "headline": None,
                    "summary": f"Earnings {when} ({em[symbol].get('date')})."}

        # 2/3) analyst / news
        heads = await self._recent_headlines(symbol)
        if heads:
            ah = self._analyst_headline(heads)
            if ah:
                return {"tag": "analyst", "confidence": 0.75, "source": "news",
                        "headline": ah, "summary": f"Analyst action: {ah}"}
            return {"tag": "news", "confidence": 0.7, "source": "news",
                    "headline": heads[0], "summary": heads[0]}

        # 4) sympathy
        moving, etf = await self._sector_sympathy(symbol, direction)
        if moving:
            return {"tag": "sympathy", "confidence": 0.5, "source": "sector",
                    "headline": None,
                    "summary": f"No stock-specific catalyst; {etf} is moving {direction}."}

        # 5) nothing
        return _no_catalyst()


_singleton: Optional[CatalystClassifierService] = None


def get_catalyst_classifier_service(db=None, news_service=None,
                                    sector_classifier=None, sector_tagger=None):
    global _singleton
    if _singleton is None:
        _singleton = CatalystClassifierService(
            db=db, news_service=news_service,
            sector_classifier=sector_classifier, sector_tagger=sector_tagger)
    return _singleton
