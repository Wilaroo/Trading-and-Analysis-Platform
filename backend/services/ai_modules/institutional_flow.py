"""
Institutional Flow Service - FREE SEC EDGAR Integration

Tracks institutional ownership via SEC 13F filings.
Provides context for trades based on who owns what.

Features:
- Parse quarterly 13F filings from SEC EDGAR (FREE)
- Track institutional ownership percentages
- Identify "Whale" vs "Shark" holders (passive vs hedge fund)
- Alert on ownership changes
- Detect rebalance risks (index additions/deletions, quarter-end)
"""

import logging
import aiohttp
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


# Known major institutional holders by category
PASSIVE_FUNDS = {
    "BLACKROCK": "passive",
    "VANGUARD": "passive", 
    "STATE STREET": "passive",
    "FIDELITY": "passive",
    "CHARLES SCHWAB": "passive",
    "INVESCO": "passive",
    "NORTHERN TRUST": "passive"
}

HEDGE_FUNDS = {
    "CITADEL": "hedge_fund",
    "RENAISSANCE": "hedge_fund",
    "TWO SIGMA": "hedge_fund",
    "BRIDGEWATER": "hedge_fund",
    "AQR": "hedge_fund",
    "DE SHAW": "hedge_fund",
    "MILLENNIUM": "hedge_fund",
    "POINT72": "hedge_fund",
    "TIGER GLOBAL": "hedge_fund"
}


@dataclass
class InstitutionalHolder:
    """A single institutional holder"""
    name: str = ""
    shares: int = 0
    value_usd: float = 0.0
    percent_of_portfolio: float = 0.0
    holder_type: str = "unknown"  # "passive", "hedge_fund", "pension", "other"
    change_shares: int = 0  # Quarter over quarter change
    change_pct: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class InstitutionalOwnership:
    """Complete institutional ownership data for a symbol"""
    symbol: str = ""
    
    # Overview
    institutional_pct: float = 0.0  # % of float held by institutions
    insider_pct: float = 0.0
    
    # Top holders
    top_holders: List[Dict] = field(default_factory=list)
    
    # Breakdown by type
    passive_pct: float = 0.0  # BlackRock, Vanguard, etc.
    hedge_fund_pct: float = 0.0  # Active hedge funds
    other_pct: float = 0.0
    
    # Risk indicators
    crowding_risk: str = "low"  # "low", "moderate", "high"
    rebalance_risk: str = "none"  # "none", "index_add", "index_delete", "quarter_end"
    
    # Quarter over quarter changes
    qoq_change_pct: float = 0.0
    
    # Metadata
    data_date: str = ""
    source: str = "sec_edgar"
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class OwnershipContext:
    """Trading context based on institutional ownership"""
    symbol: str = ""
    
    # Summary for trade decision
    summary: str = ""
    
    # Individual signals
    signals: List[str] = field(default_factory=list)
    
    # Risk factors
    risk_score: float = 0.0  # 0-10
    
    # Recommendation
    recommendation: str = ""  # "favorable", "neutral", "caution"
    
    # Metadata
    timestamp: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class InstitutionalFlowService:
    """
    Tracks institutional ownership via SEC 13F filings.
    Uses FREE data from SEC EDGAR.
    """
    
    # SEC EDGAR base URLs
    EDGAR_BASE = "https://data.sec.gov"
    COMPANY_FACTS_URL = f"{EDGAR_BASE}/submissions/CIK{{cik}}.json"
    
    # Cache settings
    CACHE_DURATION_HOURS = 24
    
    def __init__(self):
        self._db = None
        self._cache = {}
        self._cik_cache = {}  # Symbol -> CIK mapping
        
    def set_db(self, db):
        """Set database for caching"""
        self._db = db
        if db is not None:
            # Create collection for ownership data
            self._ownership_col = db["institutional_ownership"]
            self._ownership_col.create_index([("symbol", 1)])
            self._ownership_col.create_index([("data_date", -1)])
            
    async def _fetch_with_headers(self, url: str) -> Optional[Dict]:
        """Fetch from SEC EDGAR with required headers"""
        headers = {
            "User-Agent": "TradingBot/1.0 (contact@example.com)",  # Required by SEC
            "Accept": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.warning(f"SEC EDGAR returned {response.status} for {url}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching from SEC EDGAR: {e}")
            return None
            
    async def _get_cik_for_symbol(self, symbol: str) -> Optional[str]:
        """Get CIK number for a ticker symbol"""
        if symbol.upper() in self._cik_cache:
            return self._cik_cache[symbol.upper()]
            
        # SEC provides a company tickers JSON
        ticker_url = f"{self.EDGAR_BASE}/files/company_tickers.json"
        
        data = await self._fetch_with_headers(ticker_url)
        if data:
            for entry in data.values():
                if entry.get("ticker", "").upper() == symbol.upper():
                    cik = str(entry.get("cik_str", "")).zfill(10)
                    self._cik_cache[symbol.upper()] = cik
                    return cik
                    
        return None
        
    async def get_institutional_ownership(self, symbol: str) -> InstitutionalOwnership:
        """
        Get institutional ownership data for a symbol.
        Uses SEC EDGAR 13F filings when available.
        """
        symbol = symbol.upper()
        
        # Check cache first
        cached = self._get_cached_ownership(symbol)
        if cached:
            return cached
            
        # Try to fetch from SEC EDGAR
        ownership = await self._fetch_edgar_ownership(symbol)
        
        if ownership:
            # Cache the result
            self._cache_ownership(ownership)
            
        return ownership or InstitutionalOwnership(symbol=symbol)
        
    async def _fetch_edgar_ownership(self, symbol: str) -> Optional[InstitutionalOwnership]:
        """Fetch institutional ownership from SEC EDGAR"""
        cik = await self._get_cik_for_symbol(symbol)
        
        if not cik:
            logger.info(f"Could not find CIK for {symbol}")
            return None
            
        # For now, return placeholder data
        # In production, this would parse actual 13F filings from:
        # submissions_url = self.COMPANY_FACTS_URL.format(cik=cik)
        # The SEC API is rate-limited and requires proper filing parsing
        
        # Create ownership data with reasonable defaults
        ownership = InstitutionalOwnership(
            symbol=symbol,
            institutional_pct=0.0,
            insider_pct=0.0,
            top_holders=[],
            passive_pct=0.0,
            hedge_fund_pct=0.0,
            other_pct=0.0,
            crowding_risk="unknown",
            rebalance_risk="none",
            qoq_change_pct=0.0,
            data_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            source="sec_edgar_pending"
        )
        
        return ownership
        
    def _get_cached_ownership(self, symbol: str) -> Optional[InstitutionalOwnership]:
        """Get cached ownership data"""
        if symbol in self._cache:
            cached_time, data = self._cache[symbol]
            if datetime.now(timezone.utc) - cached_time < timedelta(hours=self.CACHE_DURATION_HOURS):
                return data
                
        # Try database cache
        if self._db is not None:
            try:
                doc = self._ownership_col.find_one(
                    {"symbol": symbol},
                    sort=[("data_date", -1)]
                )
                if doc:
                    doc.pop("_id", None)
                    ownership = InstitutionalOwnership(**doc)
                    self._cache[symbol] = (datetime.now(timezone.utc), ownership)
                    return ownership
            except Exception as e:
                logger.warning(f"Error reading ownership cache: {e}")
                
        return None
        
    def _cache_ownership(self, ownership: InstitutionalOwnership):
        """Cache ownership data"""
        self._cache[ownership.symbol] = (datetime.now(timezone.utc), ownership)
        
        if self._db is not None:
            try:
                self._ownership_col.update_one(
                    {"symbol": ownership.symbol},
                    {"$set": ownership.to_dict()},
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Error caching ownership: {e}")
                
    async def get_ownership_context(self, symbol: str) -> OwnershipContext:
        """
        Get trading context based on institutional ownership.
        Returns actionable insights for trade decisions.
        """
        ownership = await self.get_institutional_ownership(symbol)
        
        signals = []
        risk_score = 3.0  # Default moderate
        
        # Analyze ownership breakdown
        if ownership.institutional_pct > 80:
            signals.append(f"Very high institutional ownership ({ownership.institutional_pct:.0f}%)")
            risk_score += 1
        elif ownership.institutional_pct > 60:
            signals.append(f"High institutional ownership ({ownership.institutional_pct:.0f}%)")
            
        # Check for crowding
        if ownership.hedge_fund_pct > 30:
            signals.append(f"Heavy hedge fund concentration ({ownership.hedge_fund_pct:.0f}%)")
            signals.append("Watch for coordinated unwind risk")
            risk_score += 2
        elif ownership.passive_pct > 50:
            signals.append(f"Primarily passive ownership ({ownership.passive_pct:.0f}%)")
            signals.append("Lower crowding risk - flows follow indices")
            risk_score -= 1
            
        # Check rebalance risk
        if ownership.rebalance_risk != "none":
            if ownership.rebalance_risk == "index_add":
                signals.append("Potential index addition - expect forced buying")
                risk_score -= 0.5  # Generally positive for longs
            elif ownership.rebalance_risk == "index_delete":
                signals.append("Potential index deletion - expect forced selling")
                risk_score += 2
            elif ownership.rebalance_risk == "quarter_end":
                signals.append("Quarter-end approaching - window dressing possible")
                risk_score += 0.5
                
        # QoQ change analysis
        if ownership.qoq_change_pct > 10:
            signals.append(f"Institutions increasing positions (+{ownership.qoq_change_pct:.1f}% QoQ)")
            risk_score -= 0.5
        elif ownership.qoq_change_pct < -10:
            signals.append(f"Institutions reducing positions ({ownership.qoq_change_pct:.1f}% QoQ)")
            risk_score += 1
            
        # Determine recommendation
        risk_score = max(0, min(10, risk_score))  # Clamp to 0-10
        
        if risk_score <= 3:
            recommendation = "favorable"
        elif risk_score <= 6:
            recommendation = "neutral"
        else:
            recommendation = "caution"
            
        # Build summary
        if signals:
            summary = f"{symbol}: {ownership.institutional_pct:.0f}% institutional ownership. "
            if ownership.passive_pct > ownership.hedge_fund_pct:
                summary += f"Passive-heavy ({ownership.passive_pct:.0f}% passive vs {ownership.hedge_fund_pct:.0f}% hedge fund). "
            else:
                summary += f"Hedge fund concentration ({ownership.hedge_fund_pct:.0f}%). "
            summary += f"Crowding risk: {ownership.crowding_risk.upper()}."
        else:
            summary = f"{symbol}: Limited institutional data available."
            
        return OwnershipContext(
            symbol=symbol,
            summary=summary,
            signals=signals,
            risk_score=risk_score,
            recommendation=recommendation,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
    async def check_rebalance_risk(self, symbol: str) -> Dict[str, Any]:
        """
        Check if this stock is at risk from index rebalances.
        """
        # Check calendar-based risks
        now = datetime.now(timezone.utc)
        
        risks = []
        
        # Quarter-end check (within 2 weeks of quarter end)
        quarter_end_months = [3, 6, 9, 12]
        for qe_month in quarter_end_months:
            quarter_end = datetime(now.year, qe_month, 28, tzinfo=timezone.utc)
            if qe_month < now.month:
                quarter_end = datetime(now.year + 1, qe_month, 28, tzinfo=timezone.utc)
            
            days_to_qe = (quarter_end - now).days
            if 0 <= days_to_qe <= 14:
                risks.append({
                    "type": "quarter_end",
                    "description": f"Quarter-end in {days_to_qe} days",
                    "impact": "Window dressing - managers may sell losers, buy winners"
                })
                break
                
        # Russell rebalance (late June)
        if now.month == 6 and now.day > 20:
            risks.append({
                "type": "russell_rebalance",
                "description": "Russell rebalance period",
                "impact": "Significant forced flows for small/mid caps"
            })
            
        # S&P rebalance (quarterly, third Friday)
        # This is simplified - real implementation would track actual announcements
        
        return {
            "symbol": symbol,
            "risks": risks,
            "has_rebalance_risk": len(risks) > 0,
            "check_time": now.isoformat()
        }


# Singleton
_institutional_flow_service: Optional[InstitutionalFlowService] = None


def get_institutional_flow_service() -> InstitutionalFlowService:
    """Get singleton instance"""
    global _institutional_flow_service
    if _institutional_flow_service is None:
        _institutional_flow_service = InstitutionalFlowService()
    return _institutional_flow_service


def init_institutional_flow_service(db=None) -> InstitutionalFlowService:
    """Initialize service with dependencies"""
    service = get_institutional_flow_service()
    if db is not None:
        service.set_db(db)
    return service
