"""
Wave-Based Scanner
Tiered scanning system for large symbol universes

Tier Structure:
- Tier 1: User Watchlist (always scanned every cycle)
- Tier 2: High RVOL filtered symbols (~200, scanned every cycle)
- Tier 3: Full universe in rotating waves (200 per cycle)

Scan Cycle:
  Each cycle: Tier1 + Tier2 + Wave[N] from Tier3
  Full universe coverage: ~12-15 cycles (6-12 minutes)
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple
import asyncio
import logging

from services.smart_watchlist_service import get_smart_watchlist, SmartWatchlistService
from services.index_universe import get_index_universe, IndexUniverseManager
from services.alpaca_service import get_alpaca_service

logger = logging.getLogger(__name__)


class WaveScanner:
    """
    Wave-based scanning system for efficient coverage of large symbol universes
    """
    
    def __init__(
        self,
        watchlist_service: SmartWatchlistService = None,
        universe_manager: IndexUniverseManager = None,
        alpaca_service = None
    ):
        self._watchlist = watchlist_service or get_smart_watchlist()
        self._universe = universe_manager or get_index_universe()
        self._alpaca = alpaca_service or get_alpaca_service()
        
        # Configuration
        self._wave_size = 200
        self._min_rvol_threshold = 0.5  # Minimum RVOL to be considered "active"
        self._rvol_cache: Dict[str, Tuple[float, datetime]] = {}
        self._rvol_cache_ttl = 300  # 5 minutes
        
        # State
        self._current_wave = 0
        self._last_full_scan_complete: Optional[datetime] = None
        self._scan_stats = {
            "total_scans": 0,
            "symbols_scanned": 0,
            "alerts_generated": 0,
            "last_scan_duration": 0
        }
        
        # High RVOL pool (Tier 2)
        self._high_rvol_pool: List[str] = []
        self._last_rvol_refresh: Optional[datetime] = None
        self._rvol_refresh_interval = 600  # Refresh RVOL pool every 10 minutes
    
    async def get_scan_batch(self) -> Dict[str, List[str]]:
        """
        Get the next batch of symbols to scan, organized by tier
        
        Returns:
            {
                "tier1_watchlist": [...],  # User watchlist (always included)
                "tier2_high_rvol": [...],  # High RVOL symbols
                "tier3_wave": [...],       # Current wave from full universe
                "wave_number": int,
                "total_symbols": int
            }
        """
        # Tier 1: User Watchlist (always scan)
        tier1 = self._watchlist.get_symbols()
        
        # Tier 2: High RVOL pool (refresh periodically)
        await self._refresh_rvol_pool_if_needed()
        tier2 = self._high_rvol_pool[:200]  # Cap at 200
        
        # Tier 3: Next wave from universe
        tier3, wave_num = self._universe.get_next_wave(self._wave_size)
        
        # Check if we completed a full universe scan
        if wave_num == 0 and self._current_wave > 0:
            self._last_full_scan_complete = datetime.now(timezone.utc)
            logger.info(f"🔄 Full universe scan complete - starting new cycle")
        
        self._current_wave = wave_num
        
        # Remove duplicates across tiers (Tier 1 has priority)
        tier1_set = set(tier1)
        tier2 = [s for s in tier2 if s not in tier1_set]
        tier2_set = set(tier2)
        tier3 = [s for s in tier3 if s not in tier1_set and s not in tier2_set]
        
        total = len(tier1) + len(tier2) + len(tier3)
        
        return {
            "tier1_watchlist": tier1,
            "tier2_high_rvol": tier2,
            "tier3_wave": tier3,
            "wave_number": wave_num,
            "total_symbols": total,
            "universe_progress": self._universe.get_wave_info(self._wave_size)
        }
    
    async def _refresh_rvol_pool_if_needed(self):
        """Refresh the high RVOL pool if cache is stale"""
        now = datetime.now(timezone.utc)
        
        if (self._last_rvol_refresh and 
            (now - self._last_rvol_refresh).total_seconds() < self._rvol_refresh_interval):
            return
        
        logger.info("Refreshing high RVOL pool...")
        
        # Get priority symbols from universe (most liquid)
        priority_symbols = self._universe.get_priority_symbols(count=500)
        
        # Batch check RVOL
        high_rvol = []
        
        # Process in batches of 50 to avoid rate limits
        for i in range(0, len(priority_symbols), 50):
            batch = priority_symbols[i:i+50]
            try:
                quotes = await self._alpaca.get_quotes_batch(batch)
                
                for symbol, quote in quotes.items():
                    if quote:
                        # Estimate RVOL from available data
                        # In real implementation, would compare to avg volume
                        volume = quote.get("volume", 0)
                        if volume > 100000:  # Basic liquidity filter
                            high_rvol.append(symbol)
                            self._rvol_cache[symbol] = (1.0, now)
                
                # Small delay between batches
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"Error fetching RVOL batch: {e}")
                # On error, include the symbols anyway
                high_rvol.extend(batch)
        
        self._high_rvol_pool = high_rvol
        self._last_rvol_refresh = now
        logger.info(f"High RVOL pool refreshed: {len(high_rvol)} symbols")
    
    async def get_symbol_rvol(self, symbol: str) -> float:
        """Get RVOL for a symbol (with caching)"""
        now = datetime.now(timezone.utc)
        
        # Check cache
        if symbol in self._rvol_cache:
            rvol, cached_at = self._rvol_cache[symbol]
            if (now - cached_at).total_seconds() < self._rvol_cache_ttl:
                return rvol
        
        # Fetch fresh data
        try:
            quote = await self._alpaca.get_quote(symbol)
            if quote:
                # This is a simplified RVOL - real implementation would compare to avg
                rvol = 1.0 if quote.get("volume", 0) > 100000 else 0.5
                self._rvol_cache[symbol] = (rvol, now)
                return rvol
        except Exception as e:
            logger.debug(f"Error getting RVOL for {symbol}: {e}")
        
        return 0.0
    
    def record_scan_complete(self, symbols_scanned: int, alerts: int, duration_ms: int):
        """Record scan statistics"""
        self._scan_stats["total_scans"] += 1
        self._scan_stats["symbols_scanned"] += symbols_scanned
        self._scan_stats["alerts_generated"] += alerts
        self._scan_stats["last_scan_duration"] = duration_ms
    
    def get_stats(self) -> Dict:
        """Get scanner statistics"""
        return {
            "scan_stats": self._scan_stats,
            "current_wave": self._current_wave,
            "last_full_scan": self._last_full_scan_complete.isoformat() if self._last_full_scan_complete else None,
            "universe_stats": self._universe.get_stats(),
            "watchlist_count": len(self._watchlist.get_symbols()),
            "high_rvol_pool_size": len(self._high_rvol_pool),
            "rvol_cache_size": len(self._rvol_cache)
        }
    
    def get_scan_config(self) -> Dict:
        """Get scanner configuration"""
        return {
            "wave_size": self._wave_size,
            "min_rvol_threshold": self._min_rvol_threshold,
            "rvol_cache_ttl": self._rvol_cache_ttl,
            "rvol_refresh_interval": self._rvol_refresh_interval,
            "tier_description": {
                "tier1": "User Watchlist - Always scanned (auto + manual symbols)",
                "tier2": "High RVOL Pool - Most active symbols, refreshed every 10min",
                "tier3": f"Universe Waves - {self._wave_size} symbols per cycle, rotating"
            }
        }


# Singleton
_wave_scanner: Optional[WaveScanner] = None


def get_wave_scanner() -> WaveScanner:
    """Get or create the wave scanner"""
    global _wave_scanner
    if _wave_scanner is None:
        _wave_scanner = WaveScanner()
    return _wave_scanner


def init_wave_scanner(
    watchlist_service: SmartWatchlistService = None,
    universe_manager: IndexUniverseManager = None,
    alpaca_service = None
) -> WaveScanner:
    """Initialize the wave scanner with dependencies"""
    global _wave_scanner
    _wave_scanner = WaveScanner(watchlist_service, universe_manager, alpaca_service)
    return _wave_scanner
