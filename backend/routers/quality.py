"""
Quality Factor API Router
Endpoints for Earnings Quality Factor analysis and scanning.

Based on Quantpedia research: https://quantpedia.com/strategies/earnings-quality-factor/
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone

router = APIRouter(prefix="/api/quality", tags=["Quality Factor"])

# Service instance (will be injected)
_quality_service = None
_ib_service = None


def init_quality_router(quality_service, ib_service=None):
    """Initialize the quality router with service"""
    global _quality_service, _ib_service
    _quality_service = quality_service
    _ib_service = ib_service


# ===================== Pydantic Models =====================

class QualityScanRequest(BaseModel):
    symbols: List[str] = Field(..., description="List of symbols to scan")
    min_quality_percentile: float = Field(default=70, description="Minimum quality percentile for high-quality")


class EnhanceOpportunitiesRequest(BaseModel):
    opportunities: List[dict] = Field(..., description="List of trading opportunities to enhance")


# ===================== Endpoints =====================

@router.get("/metrics/{symbol}")
async def get_quality_metrics(symbol: str, force_refresh: bool = False):
    """
    Get quality metrics for a single symbol.
    
    Returns the 4 quality factors:
    - Accruals (lower is better)
    - ROE (higher is better)
    - CF/A - Cash Flow to Assets (higher is better)
    - D/A - Debt to Assets (lower is better)
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    try:
        metrics = await _quality_service.get_quality_metrics(symbol, force_refresh)
        return {
            "success": True,
            "data": metrics.to_dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quality metrics: {str(e)}")


@router.get("/score/{symbol}")
async def get_quality_score(symbol: str):
    """
    Get composite quality score for a symbol.
    
    Returns:
    - Composite score (0-400)
    - Percentile rank (0-100)
    - Letter grade (A+ to F)
    - Quality classification (high/low quality)
    - Trading signal (LONG/SHORT/NEUTRAL)
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    try:
        metrics = await _quality_service.get_quality_metrics(symbol)
        score = _quality_service.calculate_quality_score(metrics)
        
        return {
            "success": True,
            "data": score.to_dict(),
            "metrics": metrics.to_dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating quality score: {str(e)}")


@router.post("/scan")
async def scan_quality_stocks(request: QualityScanRequest):
    """
    Scan a list of symbols for quality stocks.
    
    Returns high-quality (top 30%) and low-quality (bottom 30%) stocks
    based on the 4-factor composite quality score.
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    if not request.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    try:
        results = await _quality_service.scan_quality_stocks(
            request.symbols, 
            request.min_quality_percentile
        )
        
        return {
            "success": True,
            "data": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scanning quality stocks: {str(e)}")


@router.post("/enhance-opportunities")
async def enhance_opportunities_with_quality(request: EnhanceOpportunitiesRequest):
    """
    Enhance trading opportunities with quality scores.
    
    Adds quality grade, score, and signal to each opportunity.
    Useful for filtering momentum plays by earnings quality.
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    try:
        enhanced = await _quality_service.get_quality_enhanced_opportunities(
            request.opportunities
        )
        
        return {
            "success": True,
            "opportunities": enhanced
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error enhancing opportunities: {str(e)}")


@router.get("/scanner/high-quality")
async def scan_high_quality_stocks(
    limit: int = Query(default=20, description="Max results"),
    min_roe: float = Query(default=0.15, description="Minimum ROE"),
    max_debt_ratio: float = Query(default=0.50, description="Maximum D/A ratio")
):
    """
    Scan for high-quality stocks from the current scanner results.
    
    Combines quality metrics with scanner data to find
    quality momentum opportunities.
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    try:
        # Get symbols from IB scanner if available
        symbols = []
        
        if _ib_service:
            try:
                # Get top gainers as starting universe
                from services.data_cache import get_data_cache
                cache = get_data_cache()
                
                # Try to get cached scanner results
                cached_gainers = cache.get_scanner_cache("top_gainers")
                cached_active = cache.get_scanner_cache("most_active")
                
                if cached_gainers and cached_gainers.get("results"):
                    symbols.extend([r.get("symbol") for r in cached_gainers["results"] if r.get("symbol")])
                
                if cached_active and cached_active.get("results"):
                    symbols.extend([r.get("symbol") for r in cached_active["results"] if r.get("symbol")])
                
                # Remove duplicates
                symbols = list(set(symbols))[:50]  # Limit to 50 for performance
                
            except Exception as e:
                print(f"Error getting scanner symbols: {e}")
        
        # If no symbols from scanner, use a default watchlist
        if not symbols:
            symbols = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                "JPM", "V", "JNJ", "WMT", "PG", "UNH", "HD", "MA",
                "DIS", "PYPL", "NFLX", "ADBE", "CRM"
            ]
        
        # Scan for quality
        results = await _quality_service.scan_quality_stocks(symbols)
        
        # Filter high quality results
        high_quality = results.get("high_quality", [])
        
        # Apply additional filters
        filtered = []
        for stock in high_quality:
            components = stock.get("component_scores", {})
            
            # Check ROE score (higher score means higher ROE)
            if components.get("roe", 0) >= 50:  # Above median ROE
                # Check debt score (higher score means lower debt)
                if components.get("da", 0) >= 40:  # Below median debt
                    filtered.append(stock)
        
        return {
            "success": True,
            "scanner": "high_quality",
            "results": filtered[:limit],
            "total_scanned": results.get("universe_size", 0),
            "high_quality_count": len(results.get("high_quality", [])),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scanning high quality stocks: {str(e)}")


@router.get("/hedge/bear-market")
async def get_bear_market_hedge():
    """
    Get quality-based bear market hedge portfolio.
    
    Research shows quality stocks outperform in bear markets.
    Returns long (high quality) and short (low quality) lists.
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    try:
        # Get broad universe
        symbols = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "JPM", "BAC", "WFC", "GS", "MS",
            "JNJ", "PFE", "UNH", "MRK", "ABBV",
            "XOM", "CVX", "COP",
            "WMT", "COST", "TGT", "HD", "LOW",
            "DIS", "NFLX", "CMCSA",
            "T", "VZ",
            "BA", "CAT", "GE", "MMM"
        ]
        
        # Get all metrics
        all_metrics = []
        for symbol in symbols:
            try:
                metrics = await _quality_service.get_quality_metrics(symbol)
                if metrics.data_quality != "low":
                    all_metrics.append(metrics)
            except:
                continue
        
        # Calculate scores
        scores = []
        for metrics in all_metrics:
            score = _quality_service.calculate_quality_score(metrics, all_metrics)
            scores.append(score)
        
        # Get hedge portfolio
        hedge = _quality_service.get_bear_market_hedge_symbols(scores)
        
        return {
            "success": True,
            "data": hedge,
            "universe_size": len(all_metrics),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating hedge portfolio: {str(e)}")


@router.get("/leaderboard")
async def get_quality_leaderboard(
    symbols: str = Query(default="", description="Comma-separated symbols (empty for default universe)"),
    limit: int = Query(default=20, description="Number of results")
):
    """
    Get quality leaderboard - ranked list of stocks by quality score.
    """
    if not _quality_service:
        raise HTTPException(status_code=500, detail="Quality service not initialized")
    
    try:
        # Parse symbols or use default
        if symbols:
            symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        else:
            # Default universe - major stocks
            symbol_list = [
                "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
                "JPM", "V", "JNJ", "WMT", "PG", "UNH", "HD", "MA",
                "DIS", "PYPL", "NFLX", "ADBE", "CRM", "INTC", "AMD",
                "BA", "CAT", "GE", "MMM", "XOM", "CVX"
            ]
        
        # Scan and score
        results = await _quality_service.scan_quality_stocks(symbol_list)
        
        # Get all scores sorted
        all_scores = results.get("all_scores", [])
        
        return {
            "success": True,
            "leaderboard": all_scores[:limit],
            "universe_size": results.get("universe_size", 0),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating leaderboard: {str(e)}")
