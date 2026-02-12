"""
Ticker Validation Utility
=========================
Centralized ticker validation to prevent:
1. False positives from common words (Target, AI, ALL, NOW)
2. Invalid/outdated tickers (CADE, MODG)
3. Non-stock symbols being processed

This module provides:
- Context-aware ticker detection
- Validation against known good symbols
- Caching of validation results
"""

import re
from typing import Optional, Set, List, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

# ===================== FALSE POSITIVE WORD LIST =====================
# Common words that match ticker patterns but are NOT stock references
# Organized by category for maintainability

FALSE_POSITIVE_WORDS = {
    # Common English words that are also tickers
    "ALL", "NOW", "IT", "ON", "BE", "SO", "GO", "DO", "AN", "AT", "BY",
    "FOR", "THE", "AND", "ARE", "CAN", "HOW", "HAS", "HAD", "YOU", "WAS",
    "NOT", "BUT", "OUT", "USE", "HER", "HIS", "NEW", "OLD", "BIG", "LOW",
    "HIGH", "GOOD", "BEST", "WELL", "ALSO", "JUST", "ONLY", "EVEN", "BACK",
    "OVER", "SUCH", "MORE", "MOST", "VERY", "MUCH", "MANY", "SOME", "THAN",
    "THEN", "THEM", "INTO", "FROM", "WITH", "THAT", "THIS", "WHAT", "WHEN",
    "WHERE", "WHICH", "WHO", "WHY", "WILL", "WOULD", "COULD", "SHOULD",
    
    # Trading/Finance terminology
    "SCALP", "SETUP", "TRADE", "STOCK", "ALERT", "WATCH", "TODAY", "SWING",
    "TREND", "CHART", "PRICE", "LEVEL", "ENTRY", "EXIT", "STOP", "GAIN",
    "LOSS", "HOLD", "LONG", "SHORT", "CALL", "PUT", "BEAR", "BULL", "PLAY",
    "DATA", "RISK", "EDGE", "FLOW", "TAPE", "BOOK", "FILL", "OPEN", "CLOSE",
    "BUY", "SELL", "WAYS", "FIND", "LOOK", "TELL", "HELP", "PLAN", "IDEA",
    "TAKE", "MAKE", "GIVE", "KNOW", "SHOW", "WAIT", "MOVE", "FREE", "FULL",
    "HALF", "PART", "LIKE", "LOVE", "HATE", "WANT", "NEED", "SURE", "TRUE",
    "REAL", "FAKE", "SAFE", "FAST", "SLOW", "EASY", "HARD", "LAST", "NEXT",
    "LATE", "SOON", "SAME", "MEAN", "TERM", "TYPE", "FORM", "SIZE", "COST",
    
    # Company names that get confused with words
    "TARGET",  # TGT is Target Corp, but "target" is commonly used (profit target, price target)
    
    # Technology/AI terms
    "AI",      # Commonly used to mean Artificial Intelligence, not C3.ai
    "API", "APP", "WEB", "NET", "TECH", "CODE", "HACK", "BYTE", "MEGA",
    "GIGA", "NANO", "CHIP", "CORE", "LINK", "NODE", "PORT", "HOST", "SYNC",
    "LOAD", "SAVE", "FILE", "PATH", "USER", "ADMIN", "ROOT", "HOME", "BASE",
    
    # Time-related
    "DAY", "WEEK", "MONTH", "YEAR", "TIME", "DATE", "HOUR", "MIN", "SEC",
    "AM", "PM", "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    
    # Directional/positional
    "UP", "DOWN", "LEFT", "RIGHT", "TOP", "BOT", "MID", "END", "START",
    "ABOVE", "BELOW", "NEAR", "FAR", "HERE", "THERE",
    
    # Quantities/numbers as words
    "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "TEN", "ZERO", "NONE",
    "FEW", "LOT", "LOTS", "TONS", "MAX", "MIN", "AVG",
    
    # Question words and pronouns
    "WHAT", "WHEN", "WHERE", "WHICH", "WHO", "WHY", "HOW",
    
    # Actions/verbs
    "RUN", "HIT", "CUT", "SET", "LET", "GOT", "GET", "PUT", "SAY", "SEE",
    "TRY", "ASK", "ADD", "END", "PAY", "WIN", "FIT", "FIX", "MIX", "DROP",
}

# ===================== KNOWN INVALID/DELISTED TICKERS =====================
# Tickers that were valid but are now delisted, merged, or changed
# Add tickers here as they become invalid

INVALID_TICKERS = {
    # Delisted or merged companies (as of Feb 2026)
    "CADE",   # Cadence Bank - merged/delisted
    "MODG",   # Topgolf Callaway - merged/restructured  
    "TWTR",   # Twitter - taken private (now X)
    "ATVI",   # Activision Blizzard - acquired by MSFT
    "VMW",    # VMware - acquired by Broadcom
    "SIRI",   # Sirius XM - restructured
    "INFO",   # IHS Markit - merged with S&P Global
    "WORK",   # Slack - acquired by Salesforce
    "FIT",    # Fitbit - acquired by Google
    "ZNGA",   # Zynga - acquired by Take-Two
    "DISCA", "DISCB", "DISCK",  # Discovery - merged with Warner
    "T",      # AT&T spun off Warner - may cause confusion
    
    # SPACs that never merged or were dissolved
    "IPOF", "IPOD", "IPOE",
    
    # Add more as discovered
}

# ===================== CONTEXT PATTERNS =====================
# Patterns that indicate a word is NOT being used as a ticker

CONTEXT_EXCLUSION_PATTERNS = [
    # "target" followed by price/profit context
    (r'\btarget\s+(?:price|profit|entry|exit|level|zone|area|range)\b', 'TARGET'),
    (r'\bprofit\s+target\b', 'TARGET'),
    (r'\bprice\s+target\b', 'TARGET'),
    (r'\bset\s+(?:a\s+)?target\b', 'TARGET'),
    (r'\bhit\s+(?:my|the|our)?\s*target\b', 'TARGET'),
    
    # "AI" in technology/concept context
    (r'\bAI\s+(?:model|system|tool|assistant|chatbot|agent|powered|generated|based)\b', 'AI'),
    (r'\b(?:artificial|machine)\s+(?:intelligence|learning)\b', 'AI'),
    (r'\busing\s+AI\b', 'AI'),
    (r'\bAI\s+(?:is|can|will|would|could|should|has|have)\b', 'AI'),
    (r'\bthe\s+AI\b', 'AI'),
    
    # "NOW" in time context
    (r'\bright\s+now\b', 'NOW'),
    (r'\bfor\s+now\b', 'NOW'),
    (r'\bnow\s+(?:that|is|are|was|were|I|we|you|it|this|the)\b', 'NOW'),
    (r'\b(?:by|until|from|since|before|after)\s+now\b', 'NOW'),
    
    # "ALL" in quantity context
    (r'\ball\s+(?:of|the|my|your|our|in|time|day|stocks|positions|trades)\b', 'ALL'),
    (r'\b(?:not|at)\s+all\b', 'ALL'),
    (r'\ball\s+(?:is|are|was|were)\b', 'ALL'),
    
    # "ON" as preposition
    (r'\bon\s+(?:the|a|my|your|this|that|it|track|fire|point|top|board|watch)\b', 'ON'),
    (r'\b(?:go|going|went|turn|hold|keep|hang|based|depends?)\s+on\b', 'ON'),
    
    # "IT" as pronoun
    (r'\bit\s+(?:is|was|will|would|could|should|has|looks|seems|appears)\b', 'IT'),
    (r'\b(?:if|when|that|and|but|so|because)\s+it\b', 'IT'),
    (r'\bmake\s+it\b', 'IT'),
]

# ===================== VALIDATION CACHE =====================
_validation_cache: dict = {}
_cache_ttl = 3600  # 1 hour


class TickerValidator:
    """
    Validates potential ticker symbols with context awareness.
    """
    
    def __init__(self, valid_symbols: Optional[Set[str]] = None):
        """
        Initialize validator with optional set of known valid symbols.
        If not provided, will be loaded from index_symbols.
        """
        self._valid_symbols = valid_symbols
        self._load_valid_symbols()
    
    def _load_valid_symbols(self):
        """Load valid symbols from index_symbols if not provided"""
        if self._valid_symbols is None:
            try:
                from data.index_symbols import get_all_symbols
                self._valid_symbols = set(get_all_symbols())
                logger.info(f"Loaded {len(self._valid_symbols)} valid symbols for validation")
            except ImportError:
                logger.warning("Could not import index_symbols, using empty validation set")
                self._valid_symbols = set()
    
    def is_valid_ticker(self, symbol: str, context: str = "") -> Tuple[bool, str]:
        """
        Check if a symbol is a valid ticker.
        
        Args:
            symbol: The potential ticker symbol
            context: The surrounding text for context-aware validation
            
        Returns:
            Tuple of (is_valid, reason)
        """
        symbol = symbol.upper().strip()
        
        # Basic format check
        if not symbol or len(symbol) > 5 or len(symbol) < 1:
            return False, "Invalid format"
        
        if not symbol.isalpha():
            return False, "Contains non-alphabetic characters"
        
        # Check against false positive words
        if symbol in FALSE_POSITIVE_WORDS:
            # But check context - maybe it IS being used as a ticker
            if context and self._is_ticker_context(symbol, context):
                pass  # Allow it
            else:
                return False, f"Common word, not a ticker reference"
        
        # Check against known invalid tickers
        if symbol in INVALID_TICKERS:
            return False, f"Delisted/invalid ticker"
        
        # Check context exclusion patterns
        if context:
            for pattern, excluded_symbol in CONTEXT_EXCLUSION_PATTERNS:
                if symbol == excluded_symbol and re.search(pattern, context, re.IGNORECASE):
                    return False, f"Context indicates non-ticker usage"
        
        # Validate against known good symbols (if we have them)
        if self._valid_symbols and symbol not in self._valid_symbols:
            # Allow some flexibility - might be a new IPO or lesser-known stock
            # But flag it as unverified
            return True, "Unverified ticker (not in known universe)"
        
        return True, "Valid ticker"
    
    def _is_ticker_context(self, symbol: str, context: str) -> bool:
        """
        Check if context suggests the word IS being used as a ticker.
        E.g., "$AI" or "AI stock" or "buy AI"
        """
        context_lower = context.lower()
        symbol_lower = symbol.lower()
        
        ticker_patterns = [
            rf'\${symbol}\b',  # $SYMBOL
            rf'\b{symbol_lower}\s+stock\b',  # SYMBOL stock
            rf'\b{symbol_lower}\s+shares?\b',  # SYMBOL shares
            rf'\bbuy\s+{symbol_lower}\b',  # buy SYMBOL
            rf'\bsell\s+{symbol_lower}\b',  # sell SYMBOL
            rf'\blong\s+{symbol_lower}\b',  # long SYMBOL
            rf'\bshort\s+{symbol_lower}\b',  # short SYMBOL
            rf'\b{symbol_lower}\s+(?:calls?|puts?)\b',  # SYMBOL calls/puts
            rf'\b{symbol_lower}\s+(?:is\s+)?(?:up|down)\s+\d',  # SYMBOL is up/down X%
        ]
        
        for pattern in ticker_patterns:
            if re.search(pattern, context, re.IGNORECASE):
                return True
        
        return False
    
    def extract_tickers(self, text: str) -> List[str]:
        """
        Extract valid tickers from text with context awareness.
        
        Args:
            text: The text to extract tickers from
            
        Returns:
            List of valid ticker symbols found
        """
        # Find all potential tickers (1-5 uppercase letters)
        potential_tickers = re.findall(r'\b([A-Z]{1,5})\b', text.upper())
        
        valid_tickers = []
        seen = set()
        
        for ticker in potential_tickers:
            if ticker in seen:
                continue
            seen.add(ticker)
            
            is_valid, reason = self.is_valid_ticker(ticker, text)
            if is_valid and "Unverified" not in reason:
                valid_tickers.append(ticker)
            elif is_valid:
                # Log unverified tickers for monitoring
                logger.debug(f"Unverified ticker found: {ticker}")
        
        return valid_tickers
    
    def filter_valid_symbols(self, symbols: List[str]) -> List[str]:
        """
        Filter a list of symbols to only include valid ones.
        
        Args:
            symbols: List of potential symbols
            
        Returns:
            List of valid symbols
        """
        return [s for s in symbols if self.is_valid_ticker(s.upper())[0]]


# ===================== GLOBAL INSTANCE =====================
_validator: Optional[TickerValidator] = None


def get_ticker_validator() -> TickerValidator:
    """Get or create the global ticker validator instance"""
    global _validator
    if _validator is None:
        _validator = TickerValidator()
    return _validator


def is_valid_ticker(symbol: str, context: str = "") -> bool:
    """Convenience function for quick ticker validation"""
    validator = get_ticker_validator()
    is_valid, _ = validator.is_valid_ticker(symbol, context)
    return is_valid


def extract_valid_tickers(text: str) -> List[str]:
    """Convenience function for extracting tickers from text"""
    validator = get_ticker_validator()
    return validator.extract_tickers(text)
