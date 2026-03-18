"""
Fundamental Quality Service - 15% of TQS Score

Evaluates fundamental factors:
- Catalyst presence (earnings, news, sector rotation)
- Short interest (squeeze potential)
- Float size (supply/demand dynamics)
- Institutional ownership
- Earnings proximity and score
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FundamentalQualityScore:
    """Result of fundamental quality evaluation"""
    score: float = 50.0  # 0-100
    grade: str = "C"
    
    # Component scores (0-100 each)
    catalyst_score: float = 50.0
    short_interest_score: float = 50.0
    float_score: float = 50.0
    institutional_score: float = 50.0
    earnings_score: float = 50.0
    
    # Raw values
    has_catalyst: bool = False
    catalyst_type: str = ""
    short_interest_pct: float = 0.0
    float_shares_millions: float = 0.0
    institutional_pct: float = 0.0
    days_to_earnings: Optional[int] = None
    earnings_catalyst_score: int = 0  # -10 to +10
    
    # Reasoning
    factors: list = None
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = []
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "components": {
                "catalyst": round(self.catalyst_score, 1),
                "short_interest": round(self.short_interest_score, 1),
                "float": round(self.float_score, 1),
                "institutional": round(self.institutional_score, 1),
                "earnings": round(self.earnings_score, 1)
            },
            "raw_values": {
                "has_catalyst": self.has_catalyst,
                "catalyst_type": self.catalyst_type,
                "short_interest_pct": round(self.short_interest_pct, 2),
                "float_shares_millions": round(self.float_shares_millions, 1),
                "institutional_pct": round(self.institutional_pct, 1),
                "days_to_earnings": self.days_to_earnings,
                "earnings_catalyst_score": self.earnings_catalyst_score
            },
            "factors": self.factors
        }


class FundamentalQualityService:
    """Evaluates fundamental quality - 15% of TQS"""
    
    def __init__(self):
        self._ib_service = None
        self._news_service = None
        self._db = None
        
    def set_services(self, ib_service=None, news_service=None, db=None):
        """Wire up dependencies"""
        self._ib_service = ib_service
        self._news_service = news_service
        self._db = db
        
    async def calculate_score(
        self,
        symbol: str,
        direction: str = "long",
        # Pre-fetched data (optional)
        has_catalyst: Optional[bool] = None,
        catalyst_type: Optional[str] = None,
        short_interest_pct: Optional[float] = None,
        float_shares: Optional[int] = None,
        institutional_pct: Optional[float] = None,
        days_to_earnings: Optional[int] = None,
        earnings_catalyst_score: Optional[int] = None,
        has_recent_news: Optional[bool] = None,
        news_sentiment: Optional[float] = None
    ) -> FundamentalQualityScore:
        """
        Calculate fundamental quality score (0-100).
        
        Components:
        - Catalyst presence (30%): News, earnings, sector rotation
        - Short interest (20%): Squeeze potential for longs
        - Float analysis (20%): Supply/demand
        - Institutional ownership (15%): Smart money
        - Earnings proximity (15%): Risk/opportunity
        """
        result = FundamentalQualityScore()
        is_long = direction.lower() == "long"
        
        # Fetch fundamental data if not provided
        if self._ib_service:
            try:
                ib_data = await self._ib_service.get_fundamentals(symbol)
                if ib_data and ib_data.get("success"):
                    fund = ib_data.get("data", {})
                    if short_interest_pct is None:
                        short_interest_pct = fund.get("short_interest_percent", 0)
                    if float_shares is None:
                        float_shares = fund.get("float_shares", 0)
                    if institutional_pct is None:
                        institutional_pct = fund.get("institutional_ownership_percent", 0)
            except Exception as e:
                logger.debug(f"Could not fetch IB data for {symbol}: {e}")
                
        # Check earnings calendar
        if self._db and days_to_earnings is None:
            try:
                from datetime import datetime, timezone, timedelta
                earnings_col = self._db.get("earnings_calendar")
                if earnings_col:
                    now = datetime.now(timezone.utc)
                    upcoming = earnings_col.find_one({
                        "symbol": symbol,
                        "date": {"$gte": now.isoformat(), "$lte": (now + timedelta(days=14)).isoformat()}
                    })
                    if upcoming:
                        earnings_date = datetime.fromisoformat(upcoming["date"].replace("Z", "+00:00"))
                        days_to_earnings = (earnings_date - now).days
                        earnings_catalyst_score = upcoming.get("earnings_score", 0)
            except Exception as e:
                logger.debug(f"Could not check earnings: {e}")
                
        # Use defaults
        short_interest_pct = short_interest_pct if short_interest_pct is not None else 5.0
        float_shares = float_shares if float_shares is not None else 100_000_000
        institutional_pct = institutional_pct if institutional_pct is not None else 50.0
        has_catalyst = has_catalyst if has_catalyst is not None else False
        catalyst_type = catalyst_type if catalyst_type else ""
        earnings_catalyst_score = earnings_catalyst_score if earnings_catalyst_score is not None else 0
        has_recent_news = has_recent_news if has_recent_news is not None else False
        news_sentiment = news_sentiment if news_sentiment is not None else 0.0
        
        result.short_interest_pct = short_interest_pct
        result.float_shares_millions = float_shares / 1_000_000
        result.institutional_pct = institutional_pct
        result.has_catalyst = has_catalyst
        result.catalyst_type = catalyst_type
        result.days_to_earnings = days_to_earnings
        result.earnings_catalyst_score = earnings_catalyst_score
        
        # 1. Catalyst Score (30% weight)
        if has_catalyst:
            if catalyst_type == "earnings":
                if earnings_catalyst_score >= 7:
                    result.catalyst_score = 95
                    result.factors.append(f"Strong earnings catalyst (score: {earnings_catalyst_score}) (++)")
                elif earnings_catalyst_score >= 4:
                    result.catalyst_score = 80
                    result.factors.append("Positive earnings catalyst (+)")
                elif earnings_catalyst_score > 0:
                    result.catalyst_score = 65
                else:
                    result.catalyst_score = 50
            elif catalyst_type == "news":
                if news_sentiment > 0.5:
                    result.catalyst_score = 85
                    result.factors.append("Strong positive news catalyst (+)")
                elif news_sentiment > 0:
                    result.catalyst_score = 70
                    result.factors.append("Positive news catalyst (+)")
                elif news_sentiment < -0.3:
                    result.catalyst_score = 35
                    result.factors.append("Negative news catalyst (-)")
                else:
                    result.catalyst_score = 55
            elif catalyst_type == "sector_rotation":
                result.catalyst_score = 75
                result.factors.append("Sector rotation catalyst (+)")
            else:
                result.catalyst_score = 70
        elif has_recent_news:
            if is_long and news_sentiment > 0.3:
                result.catalyst_score = 65
                result.factors.append("Recent positive news (+)")
            elif not is_long and news_sentiment < -0.3:
                result.catalyst_score = 65
                result.factors.append("Recent negative news supports short (+)")
            else:
                result.catalyst_score = 50
        else:
            result.catalyst_score = 40
            result.factors.append("No clear catalyst (-)")
            
        # 2. Short Interest Score (20% weight)
        # High SI is bullish for longs (squeeze), bearish for shorts (crowded)
        if is_long:
            if short_interest_pct >= 20:
                result.short_interest_score = 95
                result.factors.append(f"High short interest {short_interest_pct:.1f}% - squeeze potential (++)")
            elif short_interest_pct >= 15:
                result.short_interest_score = 85
                result.factors.append(f"Elevated short interest {short_interest_pct:.1f}% (+)")
            elif short_interest_pct >= 10:
                result.short_interest_score = 70
            elif short_interest_pct >= 5:
                result.short_interest_score = 55
            else:
                result.short_interest_score = 45
        else:  # short
            if short_interest_pct >= 25:
                result.short_interest_score = 30
                result.factors.append(f"Very high SI {short_interest_pct:.1f}% - crowded short (-)")
            elif short_interest_pct >= 15:
                result.short_interest_score = 45
                result.factors.append(f"High SI {short_interest_pct:.1f}% - some squeeze risk (-)")
            elif short_interest_pct >= 8:
                result.short_interest_score = 65
            else:
                result.short_interest_score = 80
                result.factors.append(f"Low SI {short_interest_pct:.1f}% - room to run short (+)")
                
        # 3. Float Score (20% weight)
        # Low float = more volatile, better for momentum
        float_millions = result.float_shares_millions
        
        if float_millions <= 20:
            result.float_score = 90
            result.factors.append(f"Low float ({float_millions:.0f}M) - high movement potential (+)")
        elif float_millions <= 50:
            result.float_score = 80
        elif float_millions <= 100:
            result.float_score = 65
        elif float_millions <= 300:
            result.float_score = 50
        elif float_millions <= 500:
            result.float_score = 40
        else:
            result.float_score = 35
            result.factors.append(f"Large float ({float_millions:.0f}M) - harder to move (-)")
            
        # 4. Institutional Ownership Score (15% weight)
        # 30-70% is ideal - smart money but not over-owned
        if 40 <= institutional_pct <= 70:
            result.institutional_score = 80
            result.factors.append(f"Good institutional ownership ({institutional_pct:.0f}%) (+)")
        elif 30 <= institutional_pct < 40:
            result.institutional_score = 70
        elif 70 < institutional_pct <= 85:
            result.institutional_score = 60
        elif institutional_pct > 85:
            result.institutional_score = 45
            result.factors.append(f"Over-owned by institutions ({institutional_pct:.0f}%) (-)")
        elif 15 <= institutional_pct < 30:
            result.institutional_score = 55
        else:
            result.institutional_score = 40
            result.factors.append(f"Low institutional ownership ({institutional_pct:.0f}%) (-)")
            
        # 5. Earnings Proximity Score (15% weight)
        if days_to_earnings is not None:
            if days_to_earnings <= 2:
                # Right before earnings - high risk
                if earnings_catalyst_score >= 5:
                    result.earnings_score = 70
                    result.factors.append(f"Earnings in {days_to_earnings} days - high conviction play")
                else:
                    result.earnings_score = 35
                    result.factors.append(f"Earnings in {days_to_earnings} days - binary event risk (-)")
            elif days_to_earnings <= 7:
                if earnings_catalyst_score >= 3:
                    result.earnings_score = 65
                    result.factors.append(f"Earnings approaching in {days_to_earnings} days")
                else:
                    result.earnings_score = 50
            elif days_to_earnings <= 14:
                result.earnings_score = 55
            else:
                result.earnings_score = 60
        else:
            result.earnings_score = 60  # No earnings soon - neutral
            
        # Calculate weighted total
        result.score = (
            result.catalyst_score * 0.30 +
            result.short_interest_score * 0.20 +
            result.float_score * 0.20 +
            result.institutional_score * 0.15 +
            result.earnings_score * 0.15
        )
        
        # Assign grade
        if result.score >= 85:
            result.grade = "A"
        elif result.score >= 75:
            result.grade = "B+"
        elif result.score >= 65:
            result.grade = "B"
        elif result.score >= 55:
            result.grade = "C+"
        elif result.score >= 45:
            result.grade = "C"
        elif result.score >= 35:
            result.grade = "D"
        else:
            result.grade = "F"
            
        return result


# Singleton
_fundamental_quality_service: Optional[FundamentalQualityService] = None


def get_fundamental_quality_service() -> FundamentalQualityService:
    global _fundamental_quality_service
    if _fundamental_quality_service is None:
        _fundamental_quality_service = FundamentalQualityService()
    return _fundamental_quality_service
