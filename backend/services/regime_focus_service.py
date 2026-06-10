"""
Regime Focus Service — v19.34.322 (the funnel's "find the right stocks" stage).

Assembles the **Regime Focus List**: the ranked candidates that satisfy the
full top-down funnel —

    Market regime (multi-TF modes)  →  Sector regime (11 SPDR buckets)
        →  RS leadership (1..99 rating)  →  long/short focus candidates

LONGS : rs_rating ≥ RS_FOCUS_LONG_MIN AND home-sector regime ∈ {strong, rotating_in}
SHORTS: rs_rating ≤ RS_FOCUS_SHORT_MAX AND home-sector regime ∈ {weak, rotating_out}

SOFT funnel by design: the list PROMOTES scan cadence (focus symbols are
scanned every cycle regardless of ADV tier) and feeds gate confluence —
it never blocks anything. Cached 5 min.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FOCUS_TTL_S = 300
RS_FOCUS_LONG_MIN = 80
RS_FOCUS_SHORT_MAX = 20
FOCUS_TOP_N = 40

LONG_SECTOR_REGIMES = {"strong", "rotating_in"}
SHORT_SECTOR_REGIMES = {"weak", "rotating_out"}


def build_focus_list(ratings: Dict[str, Dict],
                     sector_regime_by_etf: Dict[str, str],
                     modes: Optional[Dict[str, str]] = None,
                     market_context: str = "UNKNOWN",
                     top_n: int = FOCUS_TOP_N) -> Dict:
    """Pure: assemble the focus list from pre-fetched inputs (unit-testable).

    `ratings`  — symbol → rs_leadership doc ({rs_rating, sector, sector_rs_diff}).
    `sector_regime_by_etf` — ETF → regime label string (e.g. "strong").
    `modes`    — multi_tf modes {"long": "aggressive", "short": "defensive"}.
    """
    modes = modes or {}
    longs: List[Dict] = []
    shorts: List[Dict] = []

    for sym, doc in ratings.items():
        rs = doc.get("rs_rating")
        if rs is None:
            continue
        etf = doc.get("sector")
        sector_regime = sector_regime_by_etf.get(etf, "unknown") if etf else "unknown"

        if rs >= RS_FOCUS_LONG_MIN and sector_regime in LONG_SECTOR_REGIMES:
            longs.append({
                "symbol": sym, "rs_rating": rs, "sector": etf,
                "sector_regime": sector_regime,
                "sector_rs_diff": doc.get("sector_rs_diff"),
                "reasons": [f"RS {rs} leader", f"{etf} sector {sector_regime}"],
            })
        elif rs <= RS_FOCUS_SHORT_MAX and sector_regime in SHORT_SECTOR_REGIMES:
            shorts.append({
                "symbol": sym, "rs_rating": rs, "sector": etf,
                "sector_regime": sector_regime,
                "sector_rs_diff": doc.get("sector_rs_diff"),
                "reasons": [f"RS {rs} laggard", f"{etf} sector {sector_regime}"],
            })

    # Strongest leaders in the strongest sectors first / weakest laggards first.
    longs.sort(key=lambda r: (-r["rs_rating"], r["symbol"]))
    shorts.sort(key=lambda r: (r["rs_rating"], r["symbol"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_context": market_context,
        "modes": modes,
        "longs": longs[:top_n],
        "shorts": shorts[:top_n],
        "universe_rated": len(ratings),
        "thresholds": {"rs_long_min": RS_FOCUS_LONG_MIN,
                       "rs_short_max": RS_FOCUS_SHORT_MAX, "top_n": top_n},
    }


class RegimeFocusService:
    """Cached assembly of the Regime Focus List from live services."""

    def __init__(self, db=None):
        self.db = db
        self._cache: Optional[Dict] = None
        self._cached_at: Optional[float] = None
        self._focus_symbols: Dict[str, str] = {}  # symbol → "long"/"short"

    def get_focus_symbols_cached(self) -> Dict[str, str]:
        """Sync read for the scanner's cadence-promotion path."""
        return dict(self._focus_symbols)

    async def get_focus_list(self, force: bool = False) -> Dict:
        now = time.monotonic()
        if (not force and self._cache is not None and self._cached_at is not None
                and (now - self._cached_at) < FOCUS_TTL_S):
            return self._cache

        # 1) RS leadership ratings (Mongo-backed, 15-min in-memory TTL).
        ratings: Dict[str, Dict] = {}
        try:
            from services.rs_leadership_service import get_rs_leadership_service
            rs_svc = get_rs_leadership_service(db=self.db)
            await rs_svc.ensure_loaded()
            ratings = rs_svc._ratings
        except Exception as e:
            logger.debug(f"[FOCUS] rs ratings unavailable: {e}")

        # 2) Sector regimes (market-wide single pass, 5-min TTL inside).
        sector_regime_by_etf: Dict[str, str] = {}
        try:
            from services.sector_regime_classifier import get_sector_regime_classifier
            sec = get_sector_regime_classifier(db=self.db)
            res = await sec.classify_all_sectors()
            for etf, snap in (res.sectors or {}).items():
                regime = getattr(snap, "regime", None)
                if regime is not None:
                    sector_regime_by_etf[etf] = regime.value
        except Exception as e:
            logger.debug(f"[FOCUS] sector regimes unavailable: {e}")

        # 3) Market multi-TF context + per-direction modes.
        market_context = "UNKNOWN"
        modes: Dict[str, str] = {}
        try:
            from routers.market_regime import _market_regime_engine
            if _market_regime_engine is not None:
                rd = await _market_regime_engine.get_current_regime()
                mtf = (rd or {}).get("multi_tf") or {}
                market_context = mtf.get("context") or "UNKNOWN"
                modes = mtf.get("modes") or {}
        except Exception as e:
            logger.debug(f"[FOCUS] market regime unavailable: {e}")

        focus = build_focus_list(ratings, sector_regime_by_etf, modes, market_context)
        self._cache = focus
        self._cached_at = now
        self._focus_symbols = {
            **{r["symbol"]: "long" for r in focus["longs"]},
            **{r["symbol"]: "short" for r in focus["shorts"]},
        }
        logger.info(
            f"[FOCUS] rebuilt: {len(focus['longs'])} longs / {len(focus['shorts'])} shorts "
            f"(context={market_context}, rated={focus['universe_rated']})")
        return focus


_regime_focus_service: Optional[RegimeFocusService] = None


def get_regime_focus_service(db=None) -> RegimeFocusService:
    global _regime_focus_service
    if _regime_focus_service is None:
        _regime_focus_service = RegimeFocusService(db=db)
    elif db is not None and _regime_focus_service.db is None:
        _regime_focus_service.db = db
    return _regime_focus_service
