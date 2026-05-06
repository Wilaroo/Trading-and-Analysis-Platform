"""
Sector/Industry Strength Analysis Service
Provides sector rotation analysis, industry strength rankings, and stock-to-sector correlation.
Integrates with the scanner, trading bot, and AI assistant.
"""
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class SectorStrength(Enum):
    """Sector strength classification"""
    HOT = "hot"           # Top 3 performing sectors
    STRONG = "strong"     # Above average
    NEUTRAL = "neutral"   # Average performance
    WEAK = "weak"         # Below average
    COLD = "cold"         # Bottom 3 performing sectors


@dataclass
class SectorData:
    """Sector performance data"""
    symbol: str
    name: str
    price: float = 0.0
    change_percent: float = 0.0
    change_5d: float = 0.0        # 5-day performance
    change_20d: float = 0.0       # 20-day performance (monthly)
    volume_ratio: float = 1.0     # Volume vs average
    strength: SectorStrength = SectorStrength.NEUTRAL
    rank: int = 0
    momentum_score: float = 0.0   # Combined momentum metric
    updated_at: str = ""
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['strength'] = self.strength.value
        return result


@dataclass
class IndustryData:
    """Industry-level performance data"""
    name: str
    sector: str
    avg_change: float = 0.0
    top_movers: List[str] = field(default_factory=list)
    laggards: List[str] = field(default_factory=list)
    momentum: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass 
class SectorContext:
    """Contextual sector data for a specific stock"""
    symbol: str
    sector: str
    industry: str
    sector_strength: SectorStrength
    sector_rank: int
    sector_change: float
    stock_vs_sector: float  # Stock performance relative to sector
    is_sector_leader: bool
    is_sector_laggard: bool
    sector_momentum: float
    recommendation: str
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['sector_strength'] = self.sector_strength.value
        return result


# Sector ETF mapping
SECTOR_ETFS = {
    "XLK": {"name": "Technology", "keywords": ["tech", "software", "semiconductor", "hardware"]},
    "XLF": {"name": "Financials", "keywords": ["bank", "insurance", "financial", "investment"]},
    "XLE": {"name": "Energy", "keywords": ["oil", "gas", "energy", "petroleum"]},
    "XLV": {"name": "Healthcare", "keywords": ["health", "pharma", "biotech", "medical"]},
    "XLI": {"name": "Industrials", "keywords": ["industrial", "aerospace", "defense", "machinery"]},
    "XLC": {"name": "Communication", "keywords": ["media", "telecom", "entertainment", "communication"]},
    "XLY": {"name": "Consumer Discretionary", "keywords": ["retail", "automotive", "restaurant", "luxury"]},
    "XLP": {"name": "Consumer Staples", "keywords": ["food", "beverage", "household", "tobacco"]},
    "XLU": {"name": "Utilities", "keywords": ["utility", "electric", "water", "power"]},
    "XLRE": {"name": "Real Estate", "keywords": ["reit", "real estate", "property"]},
    "XLB": {"name": "Materials", "keywords": ["chemical", "mining", "metal", "materials"]},
}

# Common stock to sector mapping (can be expanded)
STOCK_SECTORS = {
    # Technology
    "AAPL": ("XLK", "Consumer Electronics"),
    "MSFT": ("XLK", "Software"),
    "NVDA": ("XLK", "Semiconductors"),
    "AMD": ("XLK", "Semiconductors"),
    "INTC": ("XLK", "Semiconductors"),
    "GOOGL": ("XLC", "Internet"),
    "GOOG": ("XLC", "Internet"),
    "META": ("XLC", "Social Media"),
    "AMZN": ("XLY", "E-Commerce"),
    "TSLA": ("XLY", "Automotive"),
    "NFLX": ("XLC", "Entertainment"),
    # Financials
    "JPM": ("XLF", "Banks"),
    "BAC": ("XLF", "Banks"),
    "GS": ("XLF", "Investment Banking"),
    "MS": ("XLF", "Investment Banking"),
    "V": ("XLF", "Payment Processing"),
    "MA": ("XLF", "Payment Processing"),
    # Healthcare
    "JNJ": ("XLV", "Pharmaceuticals"),
    "UNH": ("XLV", "Health Insurance"),
    "PFE": ("XLV", "Pharmaceuticals"),
    "MRNA": ("XLV", "Biotech"),
    # Energy
    "XOM": ("XLE", "Oil & Gas"),
    "CVX": ("XLE", "Oil & Gas"),
    "COP": ("XLE", "Oil & Gas"),
    # Industrials
    "BA": ("XLI", "Aerospace"),
    "CAT": ("XLI", "Machinery"),
    "GE": ("XLI", "Conglomerate"),
    # Consumer
    "WMT": ("XLP", "Retail"),
    "COST": ("XLP", "Retail"),
    "KO": ("XLP", "Beverages"),
    "PEP": ("XLP", "Beverages"),
    "MCD": ("XLY", "Restaurants"),
    "NKE": ("XLY", "Apparel"),
    "HD": ("XLY", "Home Improvement"),
}


class SectorAnalysisService:
    """
    Provides sector rotation and industry strength analysis.
    Integrates with scanner for contextual alerts and AI for recommendations.
    """
    
    def __init__(self):
        self._alpaca_service = None
        self._sector_cache: Dict[str, SectorData] = {}
        self._last_update: Optional[datetime] = None
        self._cache_ttl = 300  # 5 minutes
        self._initialized = False
    
    def is_initialized(self) -> bool:
        """Check if service is properly initialized"""
        return self._initialized and self._alpaca_service is not None
    
    def set_alpaca_service(self, alpaca_service):
        """Set the Alpaca service reference"""
        self._alpaca_service = alpaca_service
        self._initialized = True
        logger.info("SectorAnalysisService initialized with Alpaca service")
    
    def _ensure_initialized(self) -> bool:
        """Ensure service is initialized before operations"""
        if not self.is_initialized():
            logger.warning("SectorAnalysisService not initialized - call set_alpaca_service() first")
            return False
        return True
    
    async def get_sector_rankings(self, force_refresh: bool = False) -> List[SectorData]:
        """
        Get current sector performance rankings.
        Returns sectors sorted by performance (best to worst).
        """
        if not self._ensure_initialized():
            return []
        
        # Check cache
        now = datetime.now(timezone.utc)
        if (not force_refresh and 
            self._last_update and 
            (now - self._last_update).total_seconds() < self._cache_ttl and
            self._sector_cache):
            return sorted(self._sector_cache.values(), key=lambda x: x.change_percent, reverse=True)
        
        try:
            # Fetch quotes for all sector ETFs
            etf_symbols = list(SECTOR_ETFS.keys())
            quotes = await self._alpaca_service.get_quotes_batch(etf_symbols)
            
            sectors = []
            for symbol, etf_info in SECTOR_ETFS.items():
                quote = quotes.get(symbol, {})
                if not quote:
                    continue
                
                change_pct = quote.get("change_percent", 0)
                
                sector_data = SectorData(
                    symbol=symbol,
                    name=etf_info["name"],
                    price=quote.get("price", 0),
                    change_percent=change_pct,
                    volume_ratio=quote.get("rvol", 1.0),
                    updated_at=now.isoformat()
                )
                sectors.append(sector_data)
            
            # Sort by performance and assign rankings/strength
            sectors.sort(key=lambda x: x.change_percent, reverse=True)
            
            for i, sector in enumerate(sectors):
                sector.rank = i + 1
                
                # Classify strength based on rank
                if i < 3:
                    sector.strength = SectorStrength.HOT
                elif i < 5:
                    sector.strength = SectorStrength.STRONG
                elif i >= len(sectors) - 3:
                    sector.strength = SectorStrength.COLD
                elif i >= len(sectors) - 5:
                    sector.strength = SectorStrength.WEAK
                else:
                    sector.strength = SectorStrength.NEUTRAL
                
                # Calculate momentum score (weighted recent performance)
                sector.momentum_score = sector.change_percent * 0.6 + sector.volume_ratio * 0.4
                
                # Update cache - use sector.symbol as key
                self._sector_cache[sector.symbol] = sector
            
            self._last_update = now
            return sectors
            
        except Exception as e:
            logger.error(f"Error fetching sector rankings: {e}")
            return list(self._sector_cache.values()) if self._sector_cache else []
    
    async def get_stock_sector_context(self, symbol: str) -> Optional[SectorContext]:
        """
        Get sector context for a specific stock.
        Returns sector strength, relative performance, and recommendation.
        """
        symbol = symbol.upper()
        
        # Get stock's sector
        sector_info = STOCK_SECTORS.get(symbol)
        if not sector_info:
            # Try to infer sector from other sources
            return None
        
        sector_etf, industry = sector_info
        
        # Get current sector rankings
        sectors = await self.get_sector_rankings()
        sector_data = self._sector_cache.get(sector_etf)
        
        if not sector_data:
            return None
        
        # Get stock's current performance
        try:
            quote = await self._alpaca_service.get_quote(symbol)
            stock_change = quote.get("change_percent", 0) if quote else 0
        except:
            stock_change = 0
        
        # Calculate stock vs sector performance
        stock_vs_sector = stock_change - sector_data.change_percent
        
        # Determine if leader/laggard within sector
        is_leader = stock_vs_sector > 1.0  # Outperforming sector by 1%+
        is_laggard = stock_vs_sector < -1.0  # Underperforming sector by 1%+
        
        # Generate recommendation
        recommendation = self._generate_recommendation(
            sector_strength=sector_data.strength,
            stock_vs_sector=stock_vs_sector,
            is_leader=is_leader,
            is_laggard=is_laggard
        )
        
        return SectorContext(
            symbol=symbol,
            sector=sector_data.name,
            industry=industry,
            sector_strength=sector_data.strength,
            sector_rank=sector_data.rank,
            sector_change=sector_data.change_percent,
            stock_vs_sector=round(stock_vs_sector, 2),
            is_sector_leader=is_leader,
            is_sector_laggard=is_laggard,
            sector_momentum=sector_data.momentum_score,
            recommendation=recommendation
        )
    
    def _generate_recommendation(self, sector_strength: SectorStrength, 
                                  stock_vs_sector: float,
                                  is_leader: bool, is_laggard: bool) -> str:
        """Generate actionable recommendation based on sector context"""
        
        if sector_strength == SectorStrength.HOT:
            if is_leader:
                return "STRONG BUY: Leading stock in hot sector - momentum play"
            elif is_laggard:
                return "CAUTION: Underperforming in hot sector - investigate why"
            else:
                return "BUY: Sector momentum favorable - ride the wave"
        
        elif sector_strength == SectorStrength.COLD:
            if is_leader:
                return "WATCH: Relative strength in weak sector - potential rotation"
            elif is_laggard:
                return "AVOID: Double negative - weak stock in weak sector"
            else:
                return "BEARISH: Sector headwinds likely to continue"
        
        elif sector_strength == SectorStrength.STRONG:
            if is_leader:
                return "BUY: Strong sector with leadership - favorable setup"
            else:
                return "NEUTRAL+: Sector supportive but stock is average"
        
        elif sector_strength == SectorStrength.WEAK:
            if is_laggard:
                return "SHORT CANDIDATE: Weak sector + weak stock"
            else:
                return "NEUTRAL-: Sector drag may limit upside"
        
        else:  # NEUTRAL
            if is_leader:
                return "OUTPERFORMER: Stock showing relative strength"
            elif is_laggard:
                return "UNDERPERFORMER: Stock lagging peers"
            else:
                return "NEUTRAL: No clear sector advantage"
    
    async def get_rotation_signals(self) -> Dict:
        """
        Detect sector rotation patterns.
        Returns rotation signals for the AI and scanner.
        """
        sectors = await self.get_sector_rankings()
        
        if len(sectors) < 5:
            return {"error": "Insufficient sector data"}
        
        hot_sectors = [s for s in sectors if s.strength == SectorStrength.HOT]
        cold_sectors = [s for s in sectors if s.strength == SectorStrength.COLD]
        
        # Detect rotation patterns
        rotation_type = "neutral"
        rotation_description = ""
        
        hot_names = [s.name for s in hot_sectors]
        cold_names = [s.name for s in cold_sectors]
        
        # Risk-on rotation (tech, discretionary leading)
        risk_on_sectors = {"Technology", "Consumer Discretionary", "Communication"}
        # Risk-off rotation (utilities, staples, healthcare leading)
        risk_off_sectors = {"Utilities", "Consumer Staples", "Healthcare", "Real Estate"}
        
        hot_risk_on = sum(1 for s in hot_sectors if s.name in risk_on_sectors)
        hot_risk_off = sum(1 for s in hot_sectors if s.name in risk_off_sectors)
        
        if hot_risk_on >= 2:
            rotation_type = "risk_on"
            rotation_description = "Risk-On: Growth and cyclical sectors leading. Favor aggressive plays."
        elif hot_risk_off >= 2:
            rotation_type = "risk_off"
            rotation_description = "Risk-Off: Defensive sectors leading. Reduce risk exposure."
        elif "Energy" in hot_names:
            rotation_type = "inflation"
            rotation_description = "Inflation Trade: Energy leading. Consider commodity-related plays."
        elif "Financials" in hot_names:
            rotation_type = "rate_sensitive"
            rotation_description = "Rate Sensitive: Financials leading. Watch Fed commentary."
        
        return {
            "rotation_type": rotation_type,
            "rotation_description": rotation_description,
            "hot_sectors": [s.to_dict() for s in hot_sectors],
            "cold_sectors": [s.to_dict() for s in cold_sectors],
            "all_sectors": [s.to_dict() for s in sectors],
            "trading_implications": self._get_trading_implications(rotation_type),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def _get_trading_implications(self, rotation_type: str) -> List[str]:
        """Get trading implications based on rotation type"""
        implications = {
            "risk_on": [
                "Favor long positions in tech and growth stocks",
                "Look for breakout setups in momentum names",
                "Consider adding to winners",
                "Reduce defensive positions"
            ],
            "risk_off": [
                "Reduce exposure to high-beta names",
                "Consider defensive stock positions",
                "Tighten stops on growth positions",
                "Look for short opportunities in weak sectors"
            ],
            "inflation": [
                "Favor energy and materials stocks",
                "Consider commodity-related plays",
                "Be cautious with rate-sensitive names",
                "Look for inflation beneficiaries"
            ],
            "rate_sensitive": [
                "Watch financial sector for leadership",
                "Consider bank stocks on pullbacks",
                "Monitor yield curve for signals",
                "Be cautious with high-duration tech"
            ],
            "neutral": [
                "No clear sector leadership",
                "Focus on stock-specific setups",
                "Maintain balanced exposure",
                "Wait for clearer signals"
            ]
        }
        return implications.get(rotation_type, implications["neutral"])
    
    async def enhance_alert_with_sector_context(self, alert: Dict) -> Dict:
        """
        Enhance a scanner alert with sector context.
        Called by the scanner before generating alerts.
        """
        symbol = alert.get("symbol", "")
        if not symbol:
            return alert
        
        context = await self.get_stock_sector_context(symbol)
        if not context:
            return alert
        
        # Add sector context to alert
        alert["sector_context"] = context.to_dict()
        
        # Adjust alert priority based on sector strength
        if context.sector_strength == SectorStrength.HOT and context.is_sector_leader:
            # Boost priority for leaders in hot sectors
            if alert.get("priority") == "medium":
                alert["priority"] = "high"
            alert["reasoning"] = alert.get("reasoning", []) + [
                f"Sector boost: {context.sector} is hot (rank #{context.sector_rank})",
                f"Relative strength: +{context.stock_vs_sector}% vs sector"
            ]
        elif context.sector_strength == SectorStrength.COLD and context.is_sector_laggard:
            # Reduce priority or flag as potential short
            alert["reasoning"] = alert.get("reasoning", []) + [
                f"Sector warning: {context.sector} is cold (rank #{context.sector_rank})",
                f"Relative weakness: {context.stock_vs_sector}% vs sector"
            ]
            if alert.get("direction") == "long":
                alert["warnings"] = alert.get("warnings", []) + ["Weak sector headwind"]
        
        alert["sector_recommendation"] = context.recommendation
        
        return alert
    
    def get_sector_for_symbol(self, symbol: str) -> Optional[Tuple[str, str]]:
        """Get sector ETF and industry for a symbol"""
        return STOCK_SECTORS.get(symbol.upper())
    
    async def get_sector_summary_for_ai(self) -> str:
        """
        Generate a concise sector summary for the AI assistant.
        """
        sectors = await self.get_sector_rankings()
        if not sectors:
            return "Sector data unavailable."
        
        rotation = await self.get_rotation_signals()
        
        hot = [s for s in sectors[:3]]
        cold = [s for s in sectors[-3:]]
        
        summary_parts = [
            f"**Sector Rotation**: {rotation.get('rotation_description', 'No clear pattern')}",
            "",
            "**Hot Sectors**:"
        ]
        
        for s in hot:
            summary_parts.append(f"  - {s.name} ({s.symbol}): {s.change_percent:+.2f}%")
        
        summary_parts.append("")
        summary_parts.append("**Cold Sectors**:")
        
        for s in cold:
            summary_parts.append(f"  - {s.name} ({s.symbol}): {s.change_percent:+.2f}%")
        
        summary_parts.append("")
        summary_parts.append("**Trading Implications**:")
        for impl in rotation.get("trading_implications", [])[:3]:
            summary_parts.append(f"  - {impl}")
        
        return "\n".join(summary_parts)


# Singleton instance
_sector_service: Optional[SectorAnalysisService] = None


def get_sector_analysis_service() -> SectorAnalysisService:
    """Get or create the sector analysis service singleton"""
    global _sector_service
    if _sector_service is None:
        _sector_service = SectorAnalysisService()
    return _sector_service
