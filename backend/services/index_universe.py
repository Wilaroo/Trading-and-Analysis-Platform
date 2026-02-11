"""
Index Universe Manager
Manages symbol lists for major indices:
- S&P 500 (~500 symbols)
- Nasdaq 1000 (~1000 symbols)
- Russell 2000 (~2000 symbols)

Supports wave-based scanning with tiered priority
"""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging

# Import expanded symbol lists
from data.index_symbols import (
    SP500_SYMBOLS, 
    NASDAQ1000_SYMBOLS, 
    RUSSELL2000_SYMBOLS, 
    ETF_SYMBOLS
)

logger = logging.getLogger(__name__)


class IndexType(str, Enum):
    SP500 = "sp500"
    NASDAQ1000 = "nasdaq1000"
    RUSSELL2000 = "russell2000"
    ETF = "etf"
    CUSTOM = "custom"


@dataclass
class IndexUniverse:
    """Container for index symbols with metadata"""
    index_type: IndexType
    symbols: List[str]
    last_updated: datetime
    
    @property
    def count(self) -> int:
        return len(self.symbols)


class IndexUniverseManager:
    """
    Manages the full trading universe across major indices
    with support for wave-based scanning
    """
    
    def __init__(self):
        self._indices: Dict[IndexType, IndexUniverse] = {}
        self._wave_position: int = 0
        self._wave_size: int = 200
        
        # Initialize with imported lists
        self._load_indices()
    
    def _load_indices(self):
        """Load index constituent lists from data module"""
        now = datetime.now(timezone.utc)
        
        # S&P 500
        self._indices[IndexType.SP500] = IndexUniverse(
            index_type=IndexType.SP500,
            symbols=list(set(SP500_SYMBOLS)),
            last_updated=now
        )
        
        # Nasdaq 1000
        self._indices[IndexType.NASDAQ1000] = IndexUniverse(
            index_type=IndexType.NASDAQ1000,
            symbols=list(set(NASDAQ1000_SYMBOLS)),
            last_updated=now
        )
        
        # Russell 2000
        self._indices[IndexType.RUSSELL2000] = IndexUniverse(
            index_type=IndexType.RUSSELL2000,
            symbols=list(set(RUSSELL2000_SYMBOLS)),
            last_updated=now
        )
        
        # ETFs
        self._indices[IndexType.ETF] = IndexUniverse(
            index_type=IndexType.ETF,
            symbols=list(set(ETF_SYMBOLS)),
            last_updated=now
        )
        
        logger.info(
            f"Loaded index universe: "
            f"SP500={self._indices[IndexType.SP500].count}, "
            f"NASDAQ1000={self._indices[IndexType.NASDAQ1000].count}, "
            f"RUSSELL2000={self._indices[IndexType.RUSSELL2000].count}, "
            f"ETFs={self._indices[IndexType.ETF].count}, "
            f"Total unique={self.get_universe_count()}"
        )
    
    # ==================== PUBLIC API ====================
    
    def get_full_universe(self) -> List[str]:
        """Get all unique symbols across all indices"""
        all_symbols: Set[str] = set()
        for index in self._indices.values():
            all_symbols.update(index.symbols)
        return list(all_symbols)
    
    def get_index_symbols(self, index_type: IndexType) -> List[str]:
        """Get symbols for a specific index"""
        if index_type in self._indices:
            return self._indices[index_type].symbols
        return []
    
    def get_universe_count(self) -> int:
        """Get total unique symbol count"""
        return len(self.get_full_universe())
    
    def get_wave(self, wave_number: int, wave_size: int = 200) -> List[str]:
        """Get a specific wave of symbols for scanning"""
        all_symbols = self.get_full_universe()
        start_idx = wave_number * wave_size
        end_idx = start_idx + wave_size
        return all_symbols[start_idx:end_idx]
    
    def get_next_wave(self, wave_size: int = 200) -> tuple[List[str], int]:
        """Get next wave and advance position"""
        all_symbols = self.get_full_universe()
        total_waves = (len(all_symbols) + wave_size - 1) // wave_size
        
        current_wave = self._wave_position
        start_idx = current_wave * wave_size
        end_idx = min(start_idx + wave_size, len(all_symbols))
        
        symbols = all_symbols[start_idx:end_idx]
        
        # Advance to next wave (wrap around)
        self._wave_position = (self._wave_position + 1) % total_waves
        
        return symbols, current_wave
    
    def reset_wave_position(self):
        """Reset wave position to start"""
        self._wave_position = 0
    
    def get_wave_info(self, wave_size: int = 200) -> Dict:
        """Get information about wave scanning progress"""
        total_symbols = self.get_universe_count()
        total_waves = (total_symbols + wave_size - 1) // wave_size
        
        return {
            "total_symbols": total_symbols,
            "wave_size": wave_size,
            "total_waves": total_waves,
            "current_wave": self._wave_position,
            "symbols_scanned": min(self._wave_position * wave_size, total_symbols),
            "progress_pct": round(self._wave_position / total_waves * 100, 1) if total_waves > 0 else 0
        }
    
    def get_priority_symbols(self, count: int = 200) -> List[str]:
        """
        Get high-priority symbols (most liquid/active)
        Returns Nasdaq 100 + top ETFs
        """
        priority = []
        
        # ETFs first (market context)
        priority.extend(self.get_index_symbols(IndexType.ETF)[:20])
        
        # Nasdaq 100 (most liquid tech)
        priority.extend(self.get_index_symbols(IndexType.NASDAQ100))
        
        # Fill with S&P 500 top names
        remaining = count - len(priority)
        if remaining > 0:
            sp500 = self.get_index_symbols(IndexType.SP500)
            priority.extend(sp500[:remaining])
        
        return list(dict.fromkeys(priority))[:count]  # Remove duplicates, keep order
    
    def get_stats(self) -> Dict:
        """Get universe statistics"""
        return {
            "sp500": self._indices[IndexType.SP500].count,
            "nasdaq100": self._indices[IndexType.NASDAQ100].count,
            "russell2000": self._indices[IndexType.RUSSELL2000].count,
            "etfs": self._indices[IndexType.ETF].count,
            "total_unique": self.get_universe_count(),
            "wave_info": self.get_wave_info()
        }


# Singleton
_universe_manager: Optional[IndexUniverseManager] = None


def get_index_universe() -> IndexUniverseManager:
    """Get or create the index universe manager"""
    global _universe_manager
    if _universe_manager is None:
        _universe_manager = IndexUniverseManager()
    return _universe_manager
