"""
Real-Time Fundamental & Technical Data Service
Fetches live fundamental metrics from Finnhub and combines with Alpaca market data
Provides comprehensive stock analysis with actual real-time data
"""
import logging
import os
import requests
from typing import Dict, Optional, List, Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class FundamentalData:
    """Structured fundamental data for a stock"""
    symbol: str
    # Valuation
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    price_to_fcf: Optional[float] = None
    
    # Profitability
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    
    # Growth
    eps_growth_yoy: Optional[float] = None
    eps_growth_3y: Optional[float] = None
    eps_growth_5y: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    revenue_growth_3y: Optional[float] = None
    
    # Financial Health
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    
    # Per Share Data
    eps_ttm: Optional[float] = None
    book_value_per_share: Optional[float] = None
    revenue_per_share: Optional[float] = None
    fcf_per_share: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_per_share: Optional[float] = None
    payout_ratio: Optional[float] = None
    
    # Market Data
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    beta: Optional[float] = None
    
    # Price Levels
    high_52_week: Optional[float] = None
    low_52_week: Optional[float] = None
    
    # Metadata
    timestamp: Optional[str] = None
    source: str = "finnhub"


class FundamentalDataService:
    """Service for fetching real-time fundamental data from Finnhub"""
    
    def __init__(self):
        self._finnhub_key = os.environ.get("FINNHUB_API_KEY")
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl = 300  # 5 minutes cache for fundamentals (they don't change frequently)
        
        if self._finnhub_key:
            logger.info("FundamentalDataService initialized with Finnhub API")
        else:
            logger.warning("No Finnhub API key - fundamental data will be unavailable")
    
    async def get_fundamentals(self, symbol: str) -> Optional[FundamentalData]:
        """
        Fetch comprehensive fundamental data for a symbol from Finnhub.
        Returns structured FundamentalData object.
        """
        if not self._finnhub_key:
            logger.warning("No Finnhub API key configured")
            return None
        
        symbol = symbol.upper()
        
        # Validate symbol - skip obviously invalid ones
        if len(symbol) > 5 or len(symbol) < 1:
            return None
        if not symbol.isalpha():
            return None
        # Skip common words that aren't stocks
        invalid_symbols = {'SCALP', 'SETUP', 'TRADE', 'STOCK', 'ALERT', 'WATCH', 'TODAY', 
                          'SWING', 'RIGHT', 'ABOUT', 'WHICH', 'WHERE', 'WOULD', 'COULD',
                          'MIGHT', 'THINK', 'PRICE', 'LEVEL', 'TREND', 'CHART'}
        if symbol in invalid_symbols:
            return None
        
        # Check cache
        cache_key = f"fundamentals_{symbol}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cache_age = (datetime.now(timezone.utc) - cached.get('_cached_at', datetime.min.replace(tzinfo=timezone.utc))).total_seconds()
            if cache_age < self._cache_ttl:
                return cached.get('data')
        
        try:
            # Fetch basic financials (includes most ratios)
            url = "https://finnhub.io/api/v1/stock/metric"
            params = {
                "symbol": symbol,
                "metric": "all",
                "token": self._finnhub_key
            }
            
            resp = requests.get(url, params=params, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                metrics = data.get("metric", {})
                
                if not metrics:
                    logger.warning(f"No fundamental data returned for {symbol}")
                    return None
                
                # Parse into structured data
                fundamental_data = FundamentalData(
                    symbol=symbol,
                    # Valuation ratios
                    pe_ratio=metrics.get("peBasicExclExtraTTM") or metrics.get("peTTM"),
                    forward_pe=metrics.get("forwardPE") or metrics.get("peNormalizedAnnual"),
                    pb_ratio=metrics.get("pbQuarterly") or metrics.get("pbAnnual"),
                    ps_ratio=metrics.get("psTTM") or metrics.get("psAnnual"),
                    peg_ratio=metrics.get("pegRatio"),
                    ev_to_ebitda=metrics.get("evToEbitda") or metrics.get("enterpriseValueEBITDA"),
                    price_to_fcf=metrics.get("pfcfShareTTM"),
                    
                    # Profitability
                    roe=self._to_decimal(metrics.get("roeTTM") or metrics.get("roeRfy")),
                    roa=self._to_decimal(metrics.get("roaTTM") or metrics.get("roaRfy")),
                    roic=self._to_decimal(metrics.get("roicTTM") or metrics.get("roic5Y")),
                    gross_margin=self._to_decimal(metrics.get("grossMarginTTM") or metrics.get("grossMargin5Y")),
                    operating_margin=self._to_decimal(metrics.get("operatingMarginTTM") or metrics.get("operatingMargin5Y")),
                    net_margin=self._to_decimal(metrics.get("netProfitMarginTTM") or metrics.get("netProfitMargin5Y")),
                    
                    # Growth
                    eps_growth_yoy=self._to_decimal(metrics.get("epsGrowthTTMYoy") or metrics.get("epsGrowthQuarterlyYoy")),
                    eps_growth_3y=self._to_decimal(metrics.get("epsGrowth3Y")),
                    eps_growth_5y=self._to_decimal(metrics.get("epsGrowth5Y")),
                    revenue_growth_yoy=self._to_decimal(metrics.get("revenueGrowthTTMYoy") or metrics.get("revenueGrowthQuarterlyYoy")),
                    revenue_growth_3y=self._to_decimal(metrics.get("revenueGrowth3Y")),
                    
                    # Financial Health
                    debt_to_equity=metrics.get("totalDebtToEquityQuarterly") or metrics.get("totalDebtToEquityAnnual"),
                    current_ratio=metrics.get("currentRatioQuarterly") or metrics.get("currentRatioAnnual"),
                    quick_ratio=metrics.get("quickRatioQuarterly") or metrics.get("quickRatioAnnual"),
                    interest_coverage=metrics.get("interestCoverageAnnual") or metrics.get("interestCoverageTTM"),
                    
                    # Per Share Data
                    eps_ttm=metrics.get("epsTTM") or metrics.get("epsBasicExclExtraItemsTTM"),
                    book_value_per_share=metrics.get("bookValuePerShareQuarterly") or metrics.get("bookValuePerShareAnnual"),
                    revenue_per_share=metrics.get("revenuePerShareTTM") or metrics.get("revenuePerShareAnnual"),
                    fcf_per_share=metrics.get("freeCashFlowPerShareTTM"),
                    dividend_yield=self._to_decimal(metrics.get("dividendYieldIndicatedAnnual")),
                    dividend_per_share=metrics.get("dividendPerShareAnnual"),
                    payout_ratio=self._to_decimal(metrics.get("payoutRatioAnnual") or metrics.get("payoutRatioTTM")),
                    
                    # Market Data
                    market_cap=metrics.get("marketCapitalization"),
                    enterprise_value=metrics.get("enterpriseValue"),
                    beta=metrics.get("beta"),
                    
                    # Price Levels
                    high_52_week=metrics.get("52WeekHigh"),
                    low_52_week=metrics.get("52WeekLow"),
                    
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    source="finnhub"
                )
                
                # Cache the result
                self._cache[cache_key] = {
                    'data': fundamental_data,
                    '_cached_at': datetime.now(timezone.utc)
                }
                
                return fundamental_data
                
            elif resp.status_code == 429:
                logger.warning("Finnhub rate limit hit")
                return None
            else:
                logger.error(f"Finnhub API error {resp.status_code}: {resp.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {symbol}: {e}")
            return None
    
    def _to_decimal(self, value: Optional[float]) -> Optional[float]:
        """Convert percentage to decimal if needed (Finnhub returns some metrics as %, some as decimals)"""
        if value is None:
            return None
        # Finnhub returns ROE, margins, etc. as percentages (e.g., 15.5 for 15.5%)
        # We want them as decimals (0.155) for consistent display
        # If value is > 1 OR < -1, it's likely a percentage
        if abs(value) > 1:
            return value / 100
        return value
    
    async def get_company_profile(self, symbol: str) -> Optional[Dict]:
        """
        Fetch company profile information including sector, industry, market cap.
        """
        if not self._finnhub_key:
            return None
        
        try:
            url = "https://finnhub.io/api/v1/stock/profile2"
            params = {
                "symbol": symbol.upper(),
                "token": self._finnhub_key
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return {
                        "symbol": symbol.upper(),
                        "name": data.get("name"),
                        "exchange": data.get("exchange"),
                        "industry": data.get("finnhubIndustry"),
                        "ipo_date": data.get("ipo"),
                        "market_cap": data.get("marketCapitalization"),
                        "shares_outstanding": data.get("shareOutstanding"),
                        "logo": data.get("logo"),
                        "website": data.get("weburl"),
                        "country": data.get("country"),
                        "currency": data.get("currency"),
                    }
            return None
            
        except Exception as e:
            logger.error(f"Error fetching company profile for {symbol}: {e}")
            return None
    
    async def get_financial_statements(self, symbol: str, statement_type: str = "bs") -> Optional[Dict]:
        """
        Fetch financial statement data.
        statement_type: 'bs' (balance sheet), 'ic' (income), 'cf' (cash flow)
        """
        if not self._finnhub_key:
            return None
        
        try:
            url = "https://finnhub.io/api/v1/stock/financials-reported"
            params = {
                "symbol": symbol.upper(),
                "token": self._finnhub_key
            }
            
            resp = requests.get(url, params=params, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                return data
            return None
            
        except Exception as e:
            logger.error(f"Error fetching financial statements for {symbol}: {e}")
            return None
    
    async def analyze_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """
        Perform comprehensive fundamental analysis using real data.
        Returns scored analysis with signals, warnings, and recommendations.
        """
        fundamentals = await self.get_fundamentals(symbol)
        
        if not fundamentals:
            return {
                "available": False,
                "symbol": symbol.upper(),
                "error": "Unable to fetch fundamental data",
                "source": "finnhub"
            }
        
        # Initialize scoring
        value_score = 50  # Start neutral
        signals = []
        warnings = []
        
        # Analyze P/E Ratio
        if fundamentals.pe_ratio is not None:
            pe = fundamentals.pe_ratio
            if pe < 0:
                warnings.append(f"Negative P/E ({pe:.1f}) - Company is unprofitable")
                value_score -= 15
            elif pe < 12:
                signals.append(f"Low P/E ({pe:.1f}) - Potentially undervalued")
                value_score += 12
            elif pe < 18:
                signals.append(f"Fair P/E ({pe:.1f}) - Reasonably valued")
                value_score += 5
            elif pe < 25:
                warnings.append(f"Elevated P/E ({pe:.1f}) - May be richly valued")
                value_score -= 3
            else:
                warnings.append(f"High P/E ({pe:.1f}) - Expensive valuation")
                value_score -= 8
        
        # Analyze Forward P/E vs Current (growth expectations)
        if fundamentals.pe_ratio and fundamentals.forward_pe:
            if fundamentals.forward_pe < fundamentals.pe_ratio * 0.85:
                signals.append(f"Forward P/E ({fundamentals.forward_pe:.1f}) below current ({fundamentals.pe_ratio:.1f}) - Growth expected")
                value_score += 5
            elif fundamentals.forward_pe > fundamentals.pe_ratio * 1.15:
                warnings.append(f"Forward P/E ({fundamentals.forward_pe:.1f}) above current - Slowdown expected")
                value_score -= 5
        
        # Analyze P/B Ratio
        if fundamentals.pb_ratio is not None:
            pb = fundamentals.pb_ratio
            if pb < 1:
                signals.append(f"P/B ({pb:.2f}) below book value - Potential value play")
                value_score += 10
            elif pb < 3:
                signals.append(f"Reasonable P/B ({pb:.2f})")
                value_score += 2
            elif pb > 5:
                warnings.append(f"High P/B ({pb:.2f}) - Premium to assets")
                value_score -= 5
        
        # Analyze PEG Ratio
        if fundamentals.peg_ratio is not None:
            peg = fundamentals.peg_ratio
            if 0 < peg < 1:
                signals.append(f"Low PEG ({peg:.2f}) - Undervalued for growth")
                value_score += 15
            elif peg < 1.5:
                signals.append(f"Fair PEG ({peg:.2f})")
                value_score += 5
            elif peg > 2:
                warnings.append(f"High PEG ({peg:.2f}) - Expensive for growth rate")
                value_score -= 8
        
        # Analyze ROE
        if fundamentals.roe is not None:
            roe = fundamentals.roe
            if roe > 0.20:
                signals.append(f"Excellent ROE ({roe:.1%}) - High profitability")
                value_score += 12
            elif roe > 0.15:
                signals.append(f"Good ROE ({roe:.1%})")
                value_score += 8
            elif roe > 0.10:
                value_score += 2
            elif roe > 0:
                warnings.append(f"Low ROE ({roe:.1%}) - Below average returns")
                value_score -= 5
            else:
                warnings.append(f"Negative ROE ({roe:.1%}) - Losing money on equity")
                value_score -= 12
        
        # Analyze Debt-to-Equity
        if fundamentals.debt_to_equity is not None:
            de = fundamentals.debt_to_equity
            if de < 0.3:
                signals.append(f"Very low debt (D/E: {de:.2f}) - Conservative balance sheet")
                value_score += 8
            elif de < 0.7:
                signals.append(f"Healthy debt levels (D/E: {de:.2f})")
                value_score += 4
            elif de < 1.5:
                value_score += 0  # Neutral
            elif de < 2.5:
                warnings.append(f"Elevated debt (D/E: {de:.2f}) - Some leverage risk")
                value_score -= 5
            else:
                warnings.append(f"High debt (D/E: {de:.2f}) - Significant leverage")
                value_score -= 12
        
        # Analyze Margins
        if fundamentals.net_margin is not None:
            margin = fundamentals.net_margin
            if margin > 0.20:
                signals.append(f"Excellent net margin ({margin:.1%})")
                value_score += 8
            elif margin > 0.10:
                signals.append(f"Solid net margin ({margin:.1%})")
                value_score += 4
            elif margin > 0.05:
                value_score += 0
            elif margin > 0:
                warnings.append(f"Thin net margin ({margin:.1%})")
                value_score -= 3
            else:
                warnings.append(f"Negative net margin ({margin:.1%}) - Unprofitable")
                value_score -= 10
        
        # Analyze Current Ratio (liquidity)
        if fundamentals.current_ratio is not None:
            cr = fundamentals.current_ratio
            if cr > 2:
                signals.append(f"Strong liquidity (Current Ratio: {cr:.2f})")
                value_score += 5
            elif cr > 1.5:
                signals.append(f"Healthy liquidity (Current Ratio: {cr:.2f})")
                value_score += 2
            elif cr > 1:
                pass  # Neutral
            else:
                warnings.append(f"Weak liquidity (Current Ratio: {cr:.2f}) - May struggle short-term")
                value_score -= 8
        
        # Analyze EPS Growth
        if fundamentals.eps_growth_yoy is not None:
            growth = fundamentals.eps_growth_yoy
            if growth > 0.25:
                signals.append(f"Strong EPS growth ({growth:.1%} YoY)")
                value_score += 10
            elif growth > 0.10:
                signals.append(f"Solid EPS growth ({growth:.1%} YoY)")
                value_score += 5
            elif growth > 0:
                value_score += 1
            elif growth > -0.10:
                warnings.append(f"EPS declining ({growth:.1%} YoY)")
                value_score -= 5
            else:
                warnings.append(f"Significant EPS decline ({growth:.1%} YoY)")
                value_score -= 10
        
        # Analyze Dividend (if applicable)
        if fundamentals.dividend_yield is not None and fundamentals.dividend_yield > 0:
            div_yield = fundamentals.dividend_yield
            payout = fundamentals.payout_ratio
            
            if div_yield > 0.06:
                if payout and payout > 0.9:
                    warnings.append(f"High yield ({div_yield:.2%}) but unsustainable payout ({payout:.0%})")
                    value_score -= 3
                else:
                    signals.append(f"High dividend yield ({div_yield:.2%})")
                    value_score += 5
            elif div_yield > 0.02:
                signals.append(f"Dividend yield: {div_yield:.2%}")
                value_score += 2
        
        # Normalize score to 0-100
        value_score = max(0, min(100, value_score))
        
        # Determine overall assessment
        if value_score >= 75:
            assessment = "FUNDAMENTALLY STRONG"
            recommendation = "Consider for long-term investment"
        elif value_score >= 60:
            assessment = "SOLID FUNDAMENTALS"
            recommendation = "Worth further research"
        elif value_score >= 45:
            assessment = "MIXED FUNDAMENTALS"
            recommendation = "Proceed with caution"
        elif value_score >= 30:
            assessment = "WEAK FUNDAMENTALS"
            recommendation = "Higher risk profile"
        else:
            assessment = "FUNDAMENTAL CONCERNS"
            recommendation = "Significant risks present"
        
        # Build response
        return {
            "available": True,
            "symbol": symbol.upper(),
            "value_score": value_score,
            "assessment": assessment,
            "recommendation": recommendation,
            "signals": signals,
            "warnings": warnings,
            "metrics": {
                "valuation": {
                    "pe_ratio": fundamentals.pe_ratio,
                    "forward_pe": fundamentals.forward_pe,
                    "pb_ratio": fundamentals.pb_ratio,
                    "ps_ratio": fundamentals.ps_ratio,
                    "peg_ratio": fundamentals.peg_ratio,
                    "ev_to_ebitda": fundamentals.ev_to_ebitda
                },
                "profitability": {
                    "roe": f"{fundamentals.roe:.1%}" if fundamentals.roe else None,
                    "roa": f"{fundamentals.roa:.1%}" if fundamentals.roa else None,
                    "gross_margin": f"{fundamentals.gross_margin:.1%}" if fundamentals.gross_margin else None,
                    "operating_margin": f"{fundamentals.operating_margin:.1%}" if fundamentals.operating_margin else None,
                    "net_margin": f"{fundamentals.net_margin:.1%}" if fundamentals.net_margin else None
                },
                "growth": {
                    "eps_growth_yoy": f"{fundamentals.eps_growth_yoy:.1%}" if fundamentals.eps_growth_yoy else None,
                    "eps_growth_3y": f"{fundamentals.eps_growth_3y:.1%}" if fundamentals.eps_growth_3y else None,
                    "revenue_growth_yoy": f"{fundamentals.revenue_growth_yoy:.1%}" if fundamentals.revenue_growth_yoy else None
                },
                "financial_health": {
                    "debt_to_equity": fundamentals.debt_to_equity,
                    "current_ratio": fundamentals.current_ratio,
                    "quick_ratio": fundamentals.quick_ratio,
                    "interest_coverage": fundamentals.interest_coverage
                },
                "per_share": {
                    "eps_ttm": fundamentals.eps_ttm,
                    "book_value": fundamentals.book_value_per_share,
                    "dividend_yield": f"{fundamentals.dividend_yield:.2%}" if fundamentals.dividend_yield else None,
                    "payout_ratio": f"{fundamentals.payout_ratio:.0%}" if fundamentals.payout_ratio else None
                },
                "market_data": {
                    "market_cap_millions": round(fundamentals.market_cap, 2) if fundamentals.market_cap else None,
                    "beta": fundamentals.beta,
                    "52_week_high": fundamentals.high_52_week,
                    "52_week_low": fundamentals.low_52_week
                }
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "finnhub"
        }
    
    async def get_full_stock_analysis(self, symbol: str, include_technicals: bool = True) -> Dict[str, Any]:
        """
        Get comprehensive analysis combining fundamentals with technical data.
        This is the main entry point for full stock analysis.
        """
        result = {
            "symbol": symbol.upper(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fundamentals": None,
            "technicals": None,
            "company": None,
            "combined_score": None,
            "overall_verdict": None
        }
        
        # Fetch fundamental analysis
        fundamental_analysis = await self.analyze_fundamentals(symbol)
        if fundamental_analysis.get("available"):
            result["fundamentals"] = fundamental_analysis
        
        # Fetch company profile
        company = await self.get_company_profile(symbol)
        if company:
            result["company"] = company
        
        # Fetch technical data if requested
        if include_technicals:
            try:
                from services.scoring_engine import get_scoring_engine
                scoring_engine = get_scoring_engine()
                technical_analysis = await scoring_engine.analyze_ticker(symbol)
                if technical_analysis:
                    result["technicals"] = {
                        "score": technical_analysis.get("scores", {}).get("overall"),
                        "grade": technical_analysis.get("scores", {}).get("grade"),
                        "bias": technical_analysis.get("trading_summary", {}).get("bias"),
                        "direction": technical_analysis.get("trading_summary", {}).get("suggested_direction"),
                        "entry": technical_analysis.get("trading_summary", {}).get("entry"),
                        "stop_loss": technical_analysis.get("trading_summary", {}).get("stop_loss"),
                        "target": technical_analysis.get("trading_summary", {}).get("target"),
                        "indicators": technical_analysis.get("technicals", {})
                    }
            except Exception as e:
                logger.warning(f"Could not fetch technicals for {symbol}: {e}")
        
        # Calculate combined score
        if result["fundamentals"] and result["fundamentals"].get("available"):
            fundamental_score = result["fundamentals"].get("value_score", 50)
            
            if result["technicals"] and result["technicals"].get("score"):
                technical_score = result["technicals"]["score"]
                # Weight: 60% technicals (for trading), 40% fundamentals (for conviction)
                result["combined_score"] = round(technical_score * 0.6 + fundamental_score * 0.4)
            else:
                result["combined_score"] = fundamental_score
            
            # Generate overall verdict
            combined = result["combined_score"]
            if combined >= 75:
                result["overall_verdict"] = "STRONG BUY CANDIDATE"
            elif combined >= 60:
                result["overall_verdict"] = "POTENTIAL OPPORTUNITY"
            elif combined >= 45:
                result["overall_verdict"] = "NEUTRAL / WATCH"
            elif combined >= 30:
                result["overall_verdict"] = "CAUTION ADVISED"
            else:
                result["overall_verdict"] = "AVOID"
        
        return result


# Global service instance
_fundamental_service: Optional[FundamentalDataService] = None


def get_fundamental_data_service() -> FundamentalDataService:
    """Get or create the fundamental data service instance"""
    global _fundamental_service
    if _fundamental_service is None:
        _fundamental_service = FundamentalDataService()
    return _fundamental_service
