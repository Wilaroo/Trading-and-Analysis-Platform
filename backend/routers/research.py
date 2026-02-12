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
