"""
Earnings Service - Fetches earnings data from Finnhub
Provides earnings calendar, historical earnings, beat/miss trends, and analysis
"""
import logging
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class EarningsService:
    """Service for fetching earnings data from Finnhub"""
    
    def __init__(self):
        self._finnhub_key = os.environ.get("FINNHUB_API_KEY")
        
        if self._finnhub_key:
            logger.info("Finnhub API key loaded for earnings")
        else:
            logger.warning("No Finnhub API key found for earnings")
    
    async def get_earnings_calendar(self, symbol: str) -> Dict:
        """
        Get earnings calendar for a symbol including upcoming and recent earnings.
        """
        if not self._finnhub_key:
            return {"available": False, "error": "No API key"}
        
        try:
            url = f"https://finnhub.io/api/v1/calendar/earnings"
            params = {
                "symbol": symbol.upper(),
                "token": self._finnhub_key
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                earnings = data.get("earningsCalendar", [])
                
                if earnings:
                    # Sort by date (most recent first)
                    earnings.sort(key=lambda x: x.get("date", ""), reverse=True)
                    
                    # Process earnings data
                    processed = []
                    for e in earnings[:8]:  # Last 8 quarters
                        eps_actual = e.get("epsActual")
                        eps_estimate = e.get("epsEstimate")
                        rev_actual = e.get("revenueActual")
                        rev_estimate = e.get("revenueEstimate")
                        
                        # Calculate surprise
                        eps_surprise = None
                        eps_surprise_pct = None
                        if eps_actual is not None and eps_estimate is not None and eps_estimate != 0:
                            eps_surprise = eps_actual - eps_estimate
                            eps_surprise_pct = (eps_surprise / abs(eps_estimate)) * 100
                        
                        rev_surprise = None
                        rev_surprise_pct = None
                        if rev_actual is not None and rev_estimate is not None and rev_estimate != 0:
                            rev_surprise = rev_actual - rev_estimate
                            rev_surprise_pct = (rev_surprise / abs(rev_estimate)) * 100
                        
                        # Determine beat/miss
                        eps_result = None
                        if eps_actual is not None and eps_estimate is not None:
                            if eps_actual > eps_estimate:
                                eps_result = "BEAT"
                            elif eps_actual < eps_estimate:
                                eps_result = "MISS"
                            else:
                                eps_result = "MET"
                        
                        rev_result = None
                        if rev_actual is not None and rev_estimate is not None:
                            if rev_actual > rev_estimate:
                                rev_result = "BEAT"
                            elif rev_actual < rev_estimate:
                                rev_result = "MISS"
                            else:
                                rev_result = "MET"
                        
                        processed.append({
                            "date": e.get("date"),
                            "quarter": e.get("quarter"),
                            "year": e.get("year"),
                            "hour": e.get("hour"),  # 'bmo' (before market open), 'amc' (after market close)
                            "eps_actual": eps_actual,
                            "eps_estimate": eps_estimate,
                            "eps_surprise": round(eps_surprise, 4) if eps_surprise is not None else None,
                            "eps_surprise_pct": round(eps_surprise_pct, 2) if eps_surprise_pct is not None else None,
                            "eps_result": eps_result,
                            "revenue_actual": rev_actual,
                            "revenue_estimate": rev_estimate,
                            "revenue_surprise": rev_surprise,
                            "revenue_surprise_pct": round(rev_surprise_pct, 2) if rev_surprise_pct is not None else None,
                            "revenue_result": rev_result,
                            "is_reported": eps_actual is not None
                        })
                    
                    # Calculate trends
                    reported = [e for e in processed if e["is_reported"]]
                    eps_beats = sum(1 for e in reported if e["eps_result"] == "BEAT")
                    eps_misses = sum(1 for e in reported if e["eps_result"] == "MISS")
                    rev_beats = sum(1 for e in reported if e["revenue_result"] == "BEAT")
                    rev_misses = sum(1 for e in reported if e["revenue_result"] == "MISS")
                    
                    # Find next earnings (unreported)
                    upcoming = [e for e in processed if not e["is_reported"]]
                    next_earnings = upcoming[0] if upcoming else None
                    
                    # Most recent reported
                    last_earnings = reported[0] if reported else None
                    
                    return {
                        "available": True,
                        "symbol": symbol.upper(),
                        "earnings_history": processed,
                        "next_earnings": next_earnings,
                        "last_earnings": last_earnings,
                        "trends": {
                            "total_quarters": len(reported),
                            "eps_beats": eps_beats,
                            "eps_misses": eps_misses,
                            "eps_beat_rate": round(eps_beats / len(reported) * 100, 1) if reported else 0,
                            "rev_beats": rev_beats,
                            "rev_misses": rev_misses,
                            "rev_beat_rate": round(rev_beats / len(reported) * 100, 1) if reported else 0,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    return {"available": False, "error": "No earnings data found"}
            else:
                return {"available": False, "error": f"API error: {resp.status_code}"}
                
        except Exception as e:
            logger.warning(f"Failed to get earnings calendar for {symbol}: {e}")
            return {"available": False, "error": str(e)}
    
    async def get_earnings_metrics(self, symbol: str) -> Dict:
        """
        Get EPS and earnings-related metrics for a symbol.
        """
        if not self._finnhub_key:
            return {"available": False, "error": "No API key"}
        
        try:
            url = f"https://finnhub.io/api/v1/stock/metric"
            params = {
                "symbol": symbol.upper(),
                "metric": "all",
                "token": self._finnhub_key
            }
            
            resp = requests.get(url, params=params, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                metrics = data.get("metric", {})
                
                if metrics:
                    # Extract earnings-related metrics
                    earnings_metrics = {
                        "eps_ttm": metrics.get("epsTTM"),
                        "eps_annual": metrics.get("epsAnnual"),
                        "eps_growth_3y": metrics.get("epsGrowth3Y"),
                        "eps_growth_5y": metrics.get("epsGrowth5Y"),
                        "eps_growth_quarterly_yoy": metrics.get("epsGrowthQuarterlyYoy"),
                        "eps_growth_ttm_yoy": metrics.get("epsGrowthTTMYoy"),
                        "pe_ratio": metrics.get("peBasicExclExtraTTM"),
                        "pe_ratio_annual": metrics.get("peAnnual"),
                        "forward_pe": metrics.get("forwardPE"),
                        "peg_ratio": metrics.get("pegRatio"),
                        "price_to_sales_ttm": metrics.get("psTTM"),
                        "revenue_per_share_ttm": metrics.get("revenuePerShareTTM"),
                        "revenue_growth_3y": metrics.get("revenueGrowth3Y"),
                        "revenue_growth_5y": metrics.get("revenueGrowth5Y"),
                        "revenue_growth_quarterly_yoy": metrics.get("revenueGrowthQuarterlyYoy"),
                        "net_income_growth_3y": metrics.get("netIncomeGrowth3Y"),
                        "net_income_growth_5y": metrics.get("netIncomeGrowth5Y"),
                        "gross_margin_ttm": metrics.get("grossMarginTTM"),
                        "operating_margin_ttm": metrics.get("operatingMarginTTM"),
                        "net_margin_ttm": metrics.get("netMarginTTM"),
                        "roe_ttm": metrics.get("roeTTM"),
                        "roa_ttm": metrics.get("roaTTM"),
                    }
                    
                    # Calculate earnings quality indicators
                    eps_growth = earnings_metrics.get("eps_growth_ttm_yoy")
                    rev_growth = earnings_metrics.get("revenue_growth_quarterly_yoy")
                    
                    growth_trend = "neutral"
                    if eps_growth is not None and rev_growth is not None:
                        if eps_growth > 10 and rev_growth > 10:
                            growth_trend = "accelerating"
                        elif eps_growth < -10 and rev_growth < -10:
                            growth_trend = "decelerating"
                        elif eps_growth > 0 and rev_growth > 0:
                            growth_trend = "growing"
                        elif eps_growth < 0 or rev_growth < 0:
                            growth_trend = "slowing"
                    
                    return {
                        "available": True,
                        "symbol": symbol.upper(),
                        "metrics": earnings_metrics,
                        "growth_trend": growth_trend,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    return {"available": False, "error": "No metrics found"}
            else:
                return {"available": False, "error": f"API error: {resp.status_code}"}
                
        except Exception as e:
            logger.warning(f"Failed to get earnings metrics for {symbol}: {e}")
            return {"available": False, "error": str(e)}
    
    async def get_earnings_analysis(self, symbol: str) -> Dict:
        """
        Get comprehensive earnings analysis combining calendar and metrics.
        """
        # Fetch both data sources
        calendar = await self.get_earnings_calendar(symbol)
        metrics = await self.get_earnings_metrics(symbol)
        
        analysis = {
            "symbol": symbol.upper(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "calendar_available": calendar.get("available", False),
            "metrics_available": metrics.get("available", False),
        }
        
        if calendar.get("available"):
            analysis["earnings_history"] = calendar.get("earnings_history", [])
            analysis["next_earnings"] = calendar.get("next_earnings")
            analysis["last_earnings"] = calendar.get("last_earnings")
            analysis["trends"] = calendar.get("trends", {})
        
        if metrics.get("available"):
            analysis["metrics"] = metrics.get("metrics", {})
            analysis["growth_trend"] = metrics.get("growth_trend", "neutral")
        
        # Generate earnings summary
        if calendar.get("available") or metrics.get("available"):
            analysis["available"] = True
            analysis["summary"] = self._generate_earnings_summary(calendar, metrics)
        else:
            analysis["available"] = False
            analysis["error"] = "No earnings data available"
        
        return analysis
    
    def _generate_earnings_summary(self, calendar: Dict, metrics: Dict) -> Dict:
        """Generate a summary of earnings performance"""
        summary = {
            "overall_rating": "neutral",
            "key_points": [],
            "risks": [],
            "opportunities": []
        }
        
        # Analyze beat/miss trend
        if calendar.get("available"):
            trends = calendar.get("trends", {})
            beat_rate = trends.get("eps_beat_rate", 0)
            
            if beat_rate >= 80:
                summary["overall_rating"] = "strong"
                summary["key_points"].append(f"Excellent track record: {beat_rate:.0f}% EPS beat rate")
            elif beat_rate >= 60:
                summary["overall_rating"] = "good"
                summary["key_points"].append(f"Solid earnings history: {beat_rate:.0f}% EPS beat rate")
            elif beat_rate >= 40:
                summary["overall_rating"] = "neutral"
                summary["key_points"].append(f"Mixed earnings: {beat_rate:.0f}% EPS beat rate")
            else:
                summary["overall_rating"] = "weak"
                summary["risks"].append(f"Weak earnings history: Only {beat_rate:.0f}% EPS beat rate")
            
            # Check last earnings
            last = calendar.get("last_earnings")
            if last:
                if last.get("eps_result") == "BEAT":
                    summary["key_points"].append(f"Beat EPS last quarter by {last.get('eps_surprise_pct', 0):.1f}%")
                elif last.get("eps_result") == "MISS":
                    summary["risks"].append(f"Missed EPS last quarter by {abs(last.get('eps_surprise_pct', 0)):.1f}%")
            
            # Check next earnings
            next_e = calendar.get("next_earnings")
            if next_e and next_e.get("date"):
                summary["key_points"].append(f"Next earnings: {next_e['date']} ({next_e.get('hour', 'TBD').upper()})")
        
        # Analyze growth metrics
        if metrics.get("available"):
            m = metrics.get("metrics", {})
            
            eps_growth = m.get("eps_growth_ttm_yoy")
            if eps_growth is not None:
                if eps_growth > 20:
                    summary["opportunities"].append(f"Strong EPS growth: {eps_growth:.1f}% YoY")
                elif eps_growth < -10:
                    summary["risks"].append(f"EPS declining: {eps_growth:.1f}% YoY")
            
            pe = m.get("pe_ratio")
            forward_pe = m.get("forward_pe")
            if pe and forward_pe:
                if forward_pe < pe * 0.8:
                    summary["opportunities"].append(f"Forward PE ({forward_pe:.1f}x) lower than current ({pe:.1f}x) - growth expected")
                elif forward_pe > pe * 1.2:
                    summary["risks"].append(f"Forward PE ({forward_pe:.1f}x) higher than current ({pe:.1f}x) - slowdown expected")
        
        return summary


# Global service instance
_earnings_service: Optional[EarningsService] = None


def get_earnings_service() -> EarningsService:
    """Get or create the earnings service instance"""
    global _earnings_service
    if _earnings_service is None:
        _earnings_service = EarningsService()
    return _earnings_service
