"""
Newsletter API Router
Endpoints for premarket newsletter generation and ticker-specific news
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List
from services.newsletter_service import get_newsletter_service
from services.news_service import get_news_service
from datetime import datetime, timezone

router = APIRouter(prefix="/api/newsletter", tags=["Newsletter"])


# ===================== Pydantic Models =====================

class GenerateNewsletterRequest(BaseModel):
    watchlist: Optional[List[str]] = Field(default=None, description="Custom watchlist symbols")
    include_scanner_data: bool = Field(default=True, description="Include top movers from scanner")


class NewsletterResponse(BaseModel):
    title: str
    date: str
    market_outlook: dict
    summary: str
    top_stories: List[dict]
    opportunities: List[dict]
    watchlist: List[dict]
    game_plan: Optional[str] = None
    risk_factors: Optional[List[str]] = None


# ===================== Newsletter Endpoints =====================

@router.get("/latest")
async def get_latest_newsletter():
    """
    Get the most recently generated newsletter.
    Returns a placeholder if no newsletter has been generated today.
    """
    # For now, return a prompt to generate
    # In a full implementation, this would fetch from MongoDB
    return {
        "title": "Generate Today's Briefing",
        "date": datetime.now(timezone.utc).isoformat(),
        "market_outlook": {
            "sentiment": "neutral",
            "key_levels": "Click Generate to analyze",
            "focus": "Awaiting AI analysis"
        },
        "summary": "Click the 'Generate' button to create today's premarket briefing with AI-powered market analysis, trade opportunities, and key levels.",
        "top_stories": [],
        "watchlist": [],
        "needs_generation": True
    }


@router.post("/generate")
async def generate_newsletter(request: GenerateNewsletterRequest = None):
    """
    Generate a new premarket newsletter using AI analysis.
    
    This endpoint:
    1. Gathers current market data from IB (if connected)
    2. Fetches real-time market intelligence via Perplexity
    3. Generates a daytrader-style premarket briefing
    """
    try:
        service = get_newsletter_service()
        
        # Get scanner data if requested
        top_movers = None
        if request and request.include_scanner_data:
            try:
                # Try to get top movers from IB scanner
                from services.ib_service import IBService
                ib_service = service.ib_service
                if ib_service:
                    status = ib_service.get_connection_status()
                    if status.get("connected"):
                        movers = await ib_service.run_scanner(
                            scan_type="TOP_PERC_GAIN",
                            max_results=20
                        )
                        if movers:
                            # Get quotes for movers
                            symbols = [m["symbol"] for m in movers]
                            quotes = await ib_service.get_quotes_batch(symbols)
                            quotes_map = {q["symbol"]: q for q in quotes}
                            top_movers = [
                                {**m, "quote": quotes_map.get(m["symbol"], {})}
                                for m in movers
                            ]
            except Exception:
                # Continue without scanner data
                pass
        
        # Generate the newsletter
        newsletter = await service.generate_premarket_newsletter(
            top_movers=top_movers,
            custom_watchlist=request.watchlist if request else None
        )
        
        return newsletter
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate newsletter: {str(e)}"
        )


# ===================== News Endpoints =====================

@router.get("/news/{symbol}")
async def get_ticker_news(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=50, description="Max news items")
):
    """
    Get news articles for a specific ticker symbol.
    
    Fetches news from IB API when connected, otherwise returns placeholder.
    """
    try:
        service = get_news_service()
        news = await service.get_ticker_news(symbol.upper(), max_items=limit)
        
        return {
            "symbol": symbol.upper(),
            "news": news,
            "count": len(news),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch news for {symbol}: {str(e)}"
        )


@router.get("/news")
async def get_market_news(
    limit: int = Query(default=20, ge=1, le=100, description="Max news items")
):
    """
    Get general market news headlines.
    """
    try:
        service = get_news_service()
        news = await service.get_market_news(max_items=limit)
        
        return {
            "news": news,
            "count": len(news),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch market news: {str(e)}"
        )
