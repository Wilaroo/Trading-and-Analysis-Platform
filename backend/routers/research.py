"""
Web Research API Routes
Endpoints for AI assistant web research capabilities
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel, Field
from services.web_research_service import get_web_research_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])


# ===================== REQUEST/RESPONSE MODELS =====================

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)
    search_type: str = Field(default="general", pattern="^(general|news|financial)$")

class TickerResearchRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    include_sec: bool = Field(default=False)
    include_deep_dive: bool = Field(default=False)


# ===================== ENDPOINTS =====================

@router.post("/search")
async def search_web(request: SearchRequest):
    """
    General web search using Tavily
    
    - **query**: Search query (2-500 chars)
    - **max_results**: Number of results (1-10)
    - **search_type**: general, news, or financial
    """
    try:
        service = get_web_research_service()
        
        if request.search_type == "news":
            result = await service.search_news(request.query, request.max_results)
        elif request.search_type == "financial":
            result = await service.search_financial_news(request.query, request.max_results)
        else:
            result = await service.search(request.query, request.max_results)
        
        return result.to_dict()
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news")
async def get_news(
    query: str = Query(..., min_length=2, description="News search query"),
    limit: int = Query(default=5, ge=1, le=10, description="Max results")
):
    """Get latest news articles for a topic or ticker"""
    try:
        service = get_web_research_service()
        result = await service.search_news(query, max_results=limit)
        return result.to_dict()
    except Exception as e:
        logger.error(f"News search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ticker/{ticker}")
async def research_ticker(
    ticker: str,
    deep_dive: bool = Query(default=False, description="Include comprehensive deep dive")
):
    """
    Research a specific stock ticker
    
    - **ticker**: Stock symbol (e.g., AAPL, NVDA)
    - **deep_dive**: Include all sources (SEC, analysts, etc.)
    """
    try:
        service = get_web_research_service()
        ticker = ticker.upper()
        
        if deep_dive:
            result = await service.deep_dive(ticker)
        else:
            result = await service.research_ticker(ticker)
            # Convert ResearchResponse objects to dicts
            result = {k: v.to_dict() if hasattr(v, 'to_dict') else v for k, v in result.items()}
        
        return {
            "ticker": ticker,
            "research": result
        }
        
    except Exception as e:
        logger.error(f"Ticker research failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sec/{ticker}")
async def get_sec_filings(
    ticker: str,
    filing_types: Optional[str] = Query(
        default="10-K,10-Q,8-K",
        description="Comma-separated filing types"
    ),
    limit: int = Query(default=10, ge=1, le=20)
):
    """Get SEC EDGAR filings for a ticker"""
    try:
        service = get_web_research_service()
        types = [t.strip() for t in filing_types.split(",")]
        result = await service.sec.search_filings(ticker.upper(), filing_types=types, limit=limit)
        return result.to_dict()
    except Exception as e:
        logger.error(f"SEC search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/finviz/{ticker}")
async def get_finviz_data(ticker: str):
    """Get Finviz stock overview and news"""
    try:
        service = get_web_research_service()
        result = await service.finviz.get_stock_overview(ticker.upper())
        return result.to_dict()
    except Exception as e:
        logger.error(f"Finviz scrape failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/breaking-news")
async def get_breaking_news(
    topics: Optional[str] = Query(
        default=None,
        description="Comma-separated topics to filter"
    )
):
    """Get breaking market news"""
    try:
        service = get_web_research_service()
        topic_list = [t.strip() for t in topics.split(",")] if topics else None
        result = await service.get_breaking_news(topic_list)
        return result.to_dict()
    except Exception as e:
        logger.error(f"Breaking news failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyst/{ticker}")
async def get_analyst_ratings(ticker: str):
    """Get analyst ratings and price targets"""
    try:
        service = get_web_research_service()
        result = await service.yahoo.get_analyst_ratings(ticker.upper())
        return result.to_dict()
    except Exception as e:
        logger.error(f"Analyst ratings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================== AGENT SKILLS ENDPOINTS =====================

@router.get("/skills/company-info/{ticker}")
async def get_company_info_skill(ticker: str):
    """
    AGENT SKILL: Get comprehensive company information
    
    Combines multiple FREE sources first, then uses Tavily only if needed.
    Results are cached for 1 hour to minimize credit usage.
    
    Returns: Company profile, fundamentals, news, and analyst sentiment
    """
    try:
        service = get_web_research_service()
        result = await service.get_company_info(ticker.upper())
        return result
    except Exception as e:
        logger.error(f"Company info skill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills/stock-analysis/{ticker}")
async def get_stock_analysis_skill(
    ticker: str,
    analysis_type: str = Query(
        default="comprehensive",
        description="Analysis depth: quick (0 credits), news (1 credit), comprehensive (1-2 credits)"
    )
):
    """
    AGENT SKILL: Get stock analysis and trading context
    
    - **quick**: Price context and basic data only (FREE)
    - **news**: News-focused analysis (1 Tavily credit)
    - **comprehensive**: Full analysis with all sources (1-2 credits)
    
    Results are cached for 10 minutes.
    """
    try:
        if analysis_type not in ["quick", "news", "comprehensive"]:
            analysis_type = "comprehensive"
        
        service = get_web_research_service()
        result = await service.get_stock_analysis(ticker.upper(), analysis_type)
        return result
    except Exception as e:
        logger.error(f"Stock analysis skill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills/market-context")
async def get_market_context_skill():
    """
    AGENT SKILL: Get current market context and sentiment
    
    Returns market indices, news themes, market regime, and trading recommendations.
    Results are cached for 15 minutes. Uses ~1 Tavily credit per fresh call.
    """
    try:
        service = get_web_research_service()
        result = await service.get_market_context()
        return result
    except Exception as e:
        logger.error(f"Market context skill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_research_stats():
    """
    Get research service statistics including cache hit rate and credit usage
    
    Useful for monitoring Tavily credit consumption.
    """
    try:
        service = get_web_research_service()
        return service.get_cache_stats()
    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================== CREDIT BUDGET ENDPOINTS =====================

@router.get("/budget")
async def get_credit_budget():
    """
    Get full Tavily credit budget status
    
    Returns:
    - credits_used: Credits used this month
    - credits_remaining: Credits left
    - monthly_limit: Total monthly allowance (default: 1000 for free tier)
    - usage_percent: Percentage of budget used
    - status_level: ok, low, medium, high, critical
    - daily_average: Average daily usage
    - projected_monthly_usage: Projected usage by month end
    - on_track: Whether projected usage is within budget
    - recent_usage: Last 10 usage records
    """
    try:
        service = get_web_research_service()
        return service.get_credit_budget_status()
    except Exception as e:
        logger.error(f"Budget retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/budget/limit")
async def set_credit_limit(new_limit: int = Query(..., ge=100, le=100000, description="New monthly credit limit")):
    """
    Update the monthly credit limit
    
    Use this when upgrading from free tier (1000) to paid tier.
    
    - **new_limit**: New monthly credit allowance (100-100000)
    """
    try:
        service = get_web_research_service()
        return service.set_credit_limit(new_limit)
    except Exception as e:
        logger.error(f"Set limit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
