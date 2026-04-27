"""
Wave-Based Scanner — Canonical Universe Edition
================================================
Tiered scanning over the SAME universe the AI training pipeline trains on
(`services/symbol_universe.py`). This guarantees the scanner only fires
alerts on symbols the AI has models for.

Tier Structure:
- Tier 1: User Smart Watchlist + recently-viewed (always scanned every cycle)
- Tier 2: Top-N most-liquid symbols from the canonical INTRADAY tier
          (avg_dollar_volume ≥ $50M), refreshed every 10 min from MongoDB
- Tier 3: Rotating waves through the canonical SWING tier (≥ $10M ADV,
          super-set of intraday). Full coverage in ~12-15 cycles.

Phase-3 IB-only mandate: NO Alpaca. RVOL/priority is sourced from
`symbol_adv_cache` (populated by IB collector). Live quotes, when needed,
go through `services.ib_data_provider.get_live_data_service()`.

Refactored 2026-02 for Scanner Universe Alignment audit:
the wave scanner used to pull from `index_universe` (SPY/QQQ/IWM ETF
constituents) which had no overlap guarantee with `symbol_universe`.
That meant the scanner could fire on symbols the AI had no models for,
and conversely could miss $50M+ stocks that weren't in any of those ETFs.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

from services.smart_watchlist_service import get_smart_watchlist, SmartWatchlistService
from services.symbol_universe import get_universe, get_universe_stats
from services.user_viewed_tracker import get_viewed_symbols

logger = logging.getLogger(__name__)


class WaveScanner:
    """
    Wave-based scanner sourcing all tiers from the canonical AI-training
    universe (`symbol_universe.py`).
    """

    def __init__(
        self,
        watchlist_service: SmartWatchlistService = None,
        db=None,
    ):
        self._watchlist = watchlist_service or get_smart_watchlist()
        self._db = db

        # Configuration
        self._wave_size = 200
        self._tier2_pool_size = 200  # Top-N most-liquid intraday symbols

        # State
        self._current_wave = 0
        self._last_full_scan_complete: Optional[datetime] = None
        self._scan_stats = {
            "total_scans": 0,
            "symbols_scanned": 0,
            "alerts_generated": 0,
            "last_scan_duration": 0,
        }

        # Tier 2 = perma-liquid pool (top-N by ADV from canonical universe)
        self._tier2_pool: List[str] = []
        self._last_tier2_refresh: Optional[datetime] = None
        self._tier2_refresh_interval = 600  # 10 min

        # Tier 3 = ordered roster of canonical swing-tier symbols, refreshed
        # alongside Tier 2 so universe drift (new IPOs / re-classified
        # tickers) is picked up automatically.
        self._tier3_roster: List[str] = []
        self._last_tier3_refresh: Optional[datetime] = None

    # ---- DB late-binding (server.py wires db after MongoDB connect) ----
    def set_db(self, db) -> None:
        """Late-bind MongoDB so server.py can hand it in after init."""
        self._db = db
        # Force a refresh next call.
        self._last_tier2_refresh = None
        self._last_tier3_refresh = None

    # ---- Universe sourcing ---------------------------------------------
    def _refresh_universe_pools_if_needed(self) -> None:
        """Pull the latest canonical universe slices from MongoDB."""
        now = datetime.now(timezone.utc)

        if (
            self._last_tier2_refresh
            and (now - self._last_tier2_refresh).total_seconds()
            < self._tier2_refresh_interval
        ):
            return

        if self._db is None:
            logger.warning(
                "WaveScanner has no db handle yet; tiers 2/3 will be empty."
            )
            self._tier2_pool = []
            self._tier3_roster = []
            return

        try:
            # Tier 2 — top-N intraday symbols ranked by avg_dollar_volume desc
            cursor = (
                self._db["symbol_adv_cache"]
                .find(
                    {
                        "avg_dollar_volume": {"$gte": 50_000_000},
                        "unqualifiable": {"$ne": True},
                    },
                    {"symbol": 1, "avg_dollar_volume": 1, "_id": 0},
                )
                .sort("avg_dollar_volume", -1)
                .limit(self._tier2_pool_size)
            )
            self._tier2_pool = [d["symbol"] for d in cursor if d.get("symbol")]

            # Tier 3 — full canonical swing universe (super-set of intraday)
            # ordered by ADV desc so wave 0 covers the most-liquid names first.
            cursor = (
                self._db["symbol_adv_cache"]
                .find(
                    {
                        "avg_dollar_volume": {"$gte": 10_000_000},
                        "unqualifiable": {"$ne": True},
                    },
                    {"symbol": 1, "_id": 0},
                )
                .sort("avg_dollar_volume", -1)
            )
            self._tier3_roster = [d["symbol"] for d in cursor if d.get("symbol")]

            self._last_tier2_refresh = now
            self._last_tier3_refresh = now

            logger.info(
                "WaveScanner pools refreshed from canonical universe: "
                f"Tier2={len(self._tier2_pool)}, "
                f"Tier3={len(self._tier3_roster)}"
            )
        except Exception as e:
            logger.error(f"WaveScanner refresh failed: {e}")

    # ---- Public API ----------------------------------------------------
    async def get_scan_batch(self) -> Dict[str, List[str]]:
        """
        Get the next batch of symbols to scan, organized by tier.

        Returns:
            {
                "tier1_watchlist": [...],  # Smart watchlist + recently viewed
                "tier2_high_rvol": [...],  # Top-N most-liquid (ADV-ranked)
                "tier3_wave": [...],       # Current wave from canonical universe
                "wave_number": int,
                "total_symbols": int,
                "universe_progress": {...},
            }
        """
        # Tier 1: User watchlist + recently viewed
        tier1 = list(self._watchlist.get_symbols())
        try:
            viewed = get_viewed_symbols(max_count=50)
            tier1.extend(viewed)
            seen = set()
            tier1 = [s for s in tier1 if not (s in seen or seen.add(s))]
        except Exception as e:
            logger.debug(f"Could not load viewed symbols: {e}")

        # Refresh canonical pools (10-min cache)
        self._refresh_universe_pools_if_needed()

        # Tier 2: Top-N perma-liquid (ADV-ranked) intraday symbols
        tier2 = list(self._tier2_pool)

        # Tier 3: Next wave from canonical swing-tier roster
        wave_num = self._current_wave
        total_waves = max(1, (len(self._tier3_roster) + self._wave_size - 1) // self._wave_size)
        start = wave_num * self._wave_size
        end = min(start + self._wave_size, len(self._tier3_roster))
        tier3 = self._tier3_roster[start:end] if start < len(self._tier3_roster) else []

        # Advance wave (wrap on completion)
        next_wave = (wave_num + 1) % total_waves
        if next_wave == 0 and wave_num != 0:
            self._last_full_scan_complete = datetime.now(timezone.utc)
            logger.info("🔄 Full canonical-universe wave scan complete.")
        self._current_wave = next_wave

        # Dedupe across tiers (Tier 1 has priority)
        tier1_set = set(tier1)
        tier2 = [s for s in tier2 if s not in tier1_set]
        tier2_set = set(tier2)
        tier3 = [s for s in tier3 if s not in tier1_set and s not in tier2_set]

        total = len(tier1) + len(tier2) + len(tier3)
        progress_pct = round(wave_num / total_waves * 100, 1) if total_waves > 0 else 0

        return {
            "tier1_watchlist": tier1,
            "tier2_high_rvol": tier2,
            "tier3_wave": tier3,
            "wave_number": wave_num,
            "total_symbols": total,
            "universe_progress": {
                "tier2_pool_size": len(self._tier2_pool),
                "tier3_roster_size": len(self._tier3_roster),
                "wave_size": self._wave_size,
                "current_wave": wave_num,
                "total_waves": total_waves,
                "tier3_scanned": min((wave_num + 1) * self._wave_size, len(self._tier3_roster)),
                "progress_pct": progress_pct,
            },
        }

    def record_scan_complete(self, symbols_scanned: int, alerts: int, duration_ms: int):
        """Record scan statistics."""
        self._scan_stats["total_scans"] += 1
        self._scan_stats["symbols_scanned"] += symbols_scanned
        self._scan_stats["alerts_generated"] += alerts
        self._scan_stats["last_scan_duration"] = duration_ms

    def get_stats(self) -> Dict:
        """Get scanner statistics."""
        # Pull a fresh canonical-universe snapshot for diagnostics.
        try:
            universe_stats = get_universe_stats(self._db) if self._db is not None else {}
        except Exception as e:
            logger.debug(f"universe_stats unavailable: {e}")
            universe_stats = {}

        return {
            "scan_stats": self._scan_stats,
            "current_wave": self._current_wave,
            "last_full_scan": (
                self._last_full_scan_complete.isoformat()
                if self._last_full_scan_complete
                else None
            ),
            "universe_stats": universe_stats,
            "watchlist_count": len(self._watchlist.get_symbols()),
            "tier2_pool_size": len(self._tier2_pool),
            "tier3_roster_size": len(self._tier3_roster),
            "source": "canonical_symbol_universe",
        }

    def get_scan_config(self) -> Dict:
        """Get scanner configuration."""
        return {
            "wave_size": self._wave_size,
            "tier2_pool_size": self._tier2_pool_size,
            "tier2_refresh_interval_sec": self._tier2_refresh_interval,
            "source": "services/symbol_universe.py (canonical AI-training universe)",
            "tier_description": {
                "tier1": "Smart Watchlist + recently-viewed (operator override)",
                "tier2": (
                    f"Top {self._tier2_pool_size} most-liquid intraday symbols "
                    "(avg_dollar_volume ≥ $50M), ADV-ranked"
                ),
                "tier3": (
                    f"Canonical swing-tier roster (≥ $10M ADV) in waves of "
                    f"{self._wave_size} symbols, full coverage every "
                    f"~{max(1, len(self._tier3_roster)//self._wave_size)} cycles"
                ),
            },
        }


# Singleton
_wave_scanner: Optional[WaveScanner] = None


def get_wave_scanner() -> WaveScanner:
    """Get or create the wave scanner."""
    global _wave_scanner
    if _wave_scanner is None:
        _wave_scanner = WaveScanner()
    return _wave_scanner


def init_wave_scanner(
    watchlist_service: SmartWatchlistService = None,
    db=None,
) -> WaveScanner:
    """Initialize the wave scanner with dependencies (called from server.py)."""
    global _wave_scanner
    _wave_scanner = WaveScanner(watchlist_service=watchlist_service, db=db)
    return _wave_scanner
