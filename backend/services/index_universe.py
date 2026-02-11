"""
Index Universe Manager
======================
Manages symbol lists based on ETF constituents:
- SPY (S&P 500) - Tier 1 Priority
- QQQ (Nasdaq-100) - Tier 1 Priority  
- IWM (Russell 2000) - Tier 3 Rotating

Supports wave-based scanning with volume filtering.
"""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging

# Import ETF-based symbol lists
from data.index_symbols import (
    SPY_SYMBOLS,
    QQQ_SYMBOLS, 
    IWM_SYMBOLS,
    ETF_SYMBOLS,
    VOLUME_FILTERS,
    UNIVERSE_METADATA,
    get_tier1_symbols,
    get_tier3_symbols,
    get_universe_stats,
    is_rebalance_due,
    get_next_rebalance_date
)

logger = logging.getLogger(__name__)


class IndexType(str, Enum):
    SPY = "spy"           # S&P 500 large caps (Tier 1)
    QQQ = "qqq"           # Nasdaq-100 tech (Tier 1)
    IWM = "iwm"           # Russell 2000 small caps (Tier 3)
    ETF = "etf"           # Key ETFs (always scanned)
    TIER1 = "tier1"       # Combined SPY + QQQ + ETFs
    TIER3 = "tier3"       # IWM only (rotating)
    CUSTOM = "custom"


@dataclass
class IndexUniverse:
    """Container for index symbols with metadata"""
    index_type: IndexType
    symbols: List[str]
    last_updated: datetime
    priority: int  # 1 = highest (always scanned), 3 = lowest (rotating)
    
    @property
    def count(self) -> int:
        return len(self.symbols)


class IndexUniverseManager:
    """
    Manages the full trading universe with ETF-based organization
    and volume filtering support.
    """
    
    def __init__(self):
        self._indices: Dict[IndexType, IndexUniverse] = {}
        self._wave_position: int = 0
        self._wave_size: int = 200
        
        # Volume filtering settings
        self._volume_filters = VOLUME_FILTERS
        
        # Initialize with ETF-based lists
        self._load_indices()
        
        # Check for rebalance
        if is_rebalance_due():
            logger.warning(
                f"⚠️ QUARTERLY REBALANCE DUE! "
                f"Symbol lists may be stale. Next rebalance: {get_next_rebalance_date()}"
            )
    
    def _load_indices(self):
        """Load index constituent lists from ETF data"""
        now = datetime.now(timezone.utc)
        
        # SPY (S&P 500) - Tier 1
        self._indices[IndexType.SPY] = IndexUniverse(
            index_type=IndexType.SPY,
            symbols=list(set(SPY_SYMBOLS)),
            last_updated=now,
            priority=1
        )
        
        # QQQ (Nasdaq-100) - Tier 1
        self._indices[IndexType.QQQ] = IndexUniverse(
            index_type=IndexType.QQQ,
            symbols=list(set(QQQ_SYMBOLS)),
            last_updated=now,
            priority=1
        )
        
        # IWM (Russell 2000) - Tier 3
        self._indices[IndexType.IWM] = IndexUniverse(
            index_type=IndexType.IWM,
            symbols=list(set(IWM_SYMBOLS)),
            last_updated=now,
            priority=3
        )
        
        # ETFs - Always scanned
        self._indices[IndexType.ETF] = IndexUniverse(
            index_type=IndexType.ETF,
            symbols=list(set(ETF_SYMBOLS)),
            last_updated=now,
            priority=1
        )
        
        # Tier 1 Combined (SPY + QQQ + ETFs)
        self._indices[IndexType.TIER1] = IndexUniverse(
            index_type=IndexType.TIER1,
            symbols=get_tier1_symbols(),
            last_updated=now,
            priority=1
        )
        
        # Tier 3 (IWM excluding Tier 1)
        self._indices[IndexType.TIER3] = IndexUniverse(
            index_type=IndexType.TIER3,
            symbols=get_tier3_symbols(),
            last_updated=now,
            priority=3
        )
        
        stats = get_universe_stats()
        logger.info(
            f"Loaded ETF-based universe: "
            f"SPY={stats['spy_count']}, "
            f"QQQ={stats['qqq_count']}, "
            f"IWM={stats['iwm_count']}, "
            f"Tier1={stats['tier1_count']}, "
            f"Tier3={stats['tier3_count']}, "
            f"Total={stats['total_unique']}"
        )
    
    # ==================== VOLUME FILTERING ====================
    
    def get_volume_threshold(self, setup_type: str = "general") -> int:
        """
        Get minimum avg daily volume threshold for a setup type
        
        Args:
            setup_type: 'general', 'intraday', or 'scalp'
        
        Returns:
            Minimum ADV required
        """
        if setup_type in ["intraday", "scalp", "opening", "opening_drive"]:
            return self._volume_filters.get("intraday_min_adv", 500_000)
        return self._volume_filters.get("general_min_adv", 100_000)
    
    def filter_by_volume(
        self, 
        symbols: List[str], 
        volume_data: Dict[str, int],
        setup_type: str = "general"
    ) -> List[str]:
        """
        Filter symbols by average daily volume
        
        Args:
            symbols: List of symbols to filter
            volume_data: Dict of {symbol: avg_daily_volume}
            setup_type: Type of setup to determine threshold
            
        Returns:
            Filtered list of symbols meeting volume requirements
        """
        threshold = self.get_volume_threshold(setup_type)
        
        filtered = []
        for symbol in symbols:
            adv = volume_data.get(symbol, 0)
            if adv >= threshold:
                filtered.append(symbol)
        
        return filtered
    
    # ==================== PUBLIC API ====================
    
    def get_full_universe(self) -> List[str]:
        """Get all unique symbols across all indices"""
        all_symbols: Set[str] = set()
        all_symbols.update(self._indices[IndexType.SPY].symbols)
        all_symbols.update(self._indices[IndexType.QQQ].symbols)
        all_symbols.update(self._indices[IndexType.IWM].symbols)
        all_symbols.update(self._indices[IndexType.ETF].symbols)
        return list(all_symbols)
    
    def get_index_symbols(self, index_type: IndexType) -> List[str]:
        """Get symbols for a specific index/tier"""
        if index_type in self._indices:
            return self._indices[index_type].symbols
        return []
    
    def get_tier1_symbols(self) -> List[str]:
        """Get Tier 1 symbols (SPY + QQQ + ETFs) - always scanned"""
        return self._indices[IndexType.TIER1].symbols
    
    def get_tier3_symbols(self) -> List[str]:
        """Get Tier 3 symbols (IWM only) - rotating batches"""
        return self._indices[IndexType.TIER3].symbols
    
    def get_universe_count(self) -> int:
        """Get total unique symbol count"""
        return len(self.get_full_universe())
    
    def get_wave(self, wave_number: int, wave_size: int = 200) -> List[str]:
        """Get a specific wave of Tier 3 symbols for scanning"""
        tier3_symbols = self.get_tier3_symbols()
        start_idx = wave_number * wave_size
        end_idx = start_idx + wave_size
        return tier3_symbols[start_idx:end_idx]
    
    def get_next_wave(self, wave_size: int = 200) -> tuple[List[str], int]:
        """Get next wave of Tier 3 symbols and advance position"""
        tier3_symbols = self.get_tier3_symbols()
        total_waves = max(1, (len(tier3_symbols) + wave_size - 1) // wave_size)
        
        current_wave = self._wave_position
        start_idx = current_wave * wave_size
        end_idx = min(start_idx + wave_size, len(tier3_symbols))
        
        symbols = tier3_symbols[start_idx:end_idx] if start_idx < len(tier3_symbols) else []
        
        # Advance to next wave (wrap around)
        self._wave_position = (self._wave_position + 1) % total_waves
        
        return symbols, current_wave
    
    def reset_wave_position(self):
        """Reset wave position to start"""
        self._wave_position = 0
    
    def get_wave_info(self, wave_size: int = 200) -> Dict:
        """Get information about wave scanning progress"""
        tier3_count = len(self.get_tier3_symbols())
        total_waves = max(1, (tier3_count + wave_size - 1) // wave_size)
        
        return {
            "tier1_count": len(self.get_tier1_symbols()),
            "tier3_count": tier3_count,
            "total_symbols": self.get_universe_count(),
            "wave_size": wave_size,
            "total_waves": total_waves,
            "current_wave": self._wave_position,
            "tier3_scanned": min(self._wave_position * wave_size, tier3_count),
            "progress_pct": round(self._wave_position / total_waves * 100, 1) if total_waves > 0 else 0
        }
    
    def get_priority_symbols(self, count: int = 200) -> List[str]:
        """
        Get high-priority symbols (SPY + QQQ)
        Returns most liquid stocks first
        """
        priority = []
        
        # ETFs first (market context)
        priority.extend(self.get_index_symbols(IndexType.ETF)[:15])
        
        # QQQ (most liquid tech)
        priority.extend(self.get_index_symbols(IndexType.QQQ)[:100])
        
        # Fill with SPY top names
        remaining = count - len(priority)
        if remaining > 0:
            spy = self.get_index_symbols(IndexType.SPY)
            priority.extend(spy[:remaining])
        
        return list(dict.fromkeys(priority))[:count]  # Remove duplicates, keep order
    
    def get_stats(self) -> Dict:
        """Get universe statistics"""
        stats = get_universe_stats()
        stats["wave_info"] = self.get_wave_info()
        stats["volume_filters"] = self._volume_filters
        stats["rebalance_due"] = is_rebalance_due()
        stats["next_rebalance"] = get_next_rebalance_date()
        return stats
    
    # ==================== LEGACY COMPATIBILITY ====================
    # Keep these for backward compatibility
    
    @property
    def sp500_count(self) -> int:
        return self._indices[IndexType.SPY].count
    
    @property
    def nasdaq1000_count(self) -> int:
        return self._indices[IndexType.QQQ].count
    
    @property
    def russell2000_count(self) -> int:
        return self._indices[IndexType.IWM].count


# Singleton
_universe_manager: Optional[IndexUniverseManager] = None


def get_index_universe() -> IndexUniverseManager:
    """Get or create the index universe manager"""
    global _universe_manager
    if _universe_manager is None:
        _universe_manager = IndexUniverseManager()
    return _universe_manager
