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
    # Check if we have a cached newsletter from today
    service = get_newsletter_service()
    if hasattr(service, '_cached_newsletter') and service._cached_newsletter:
        cached = service._cached_newsletter
        # Check if it's from today
        if cached.get('date'):
            try:
                cached_date = datetime.fromisoformat(cached['date'].replace('Z', '+00:00')).date()
                if cached_date == datetime.now(timezone.utc).date():
                    return cached
            except:
                pass
    
    # Return a placeholder prompting auto-generation
    return {
        "title": "Market Intelligence",
        "date": datetime.now(timezone.utc).isoformat(),
        "market_outlook": {
            "sentiment": "neutral",
            "key_levels": "Awaiting market data",
            "focus": "Connect IB Gateway to auto-generate"
        },
        "summary": "Connect to IB Gateway to automatically generate today's market intelligence briefing.",
        "top_stories": [],
        "watchlist": [],
        "opportunities": [],
        "needs_generation": True
    }


@router.post("/auto-generate")
async def auto_generate_market_intelligence():
    """
    Auto-generate market intelligence when IB Gateway connects.
    This provides a comprehensive morning briefing covering:
    - Market sentiment and overnight developments
    - News, politics, and world events affecting markets
    - Top movers and trade opportunities
    - Key levels and risk factors
    """
    try:
        service = get_newsletter_service()
        
        # Gather comprehensive market data
        top_movers = None
        market_context = {}
        
        try:
            from services.ib_service import IBService
            ib_service = service.ib_service
            if ib_service:
                status = ib_service.get_connection_status()
                if status.get("connected"):
                    # Get multiple scanner types for comprehensive view
                    gainers = await ib_service.run_scanner("TOP_PERC_GAIN", limit=10)
                    losers = await ib_service.run_scanner("TOP_PERC_LOSE", limit=10)
                    active = await ib_service.run_scanner("MOST_ACTIVE", limit=10)
                    
                    # Combine all movers
                    all_symbols = set()
                    top_movers = []
                    
                    for scanner_results, category in [(gainers, 'gainer'), (losers, 'loser'), (active, 'active')]:
                        if scanner_results:
                            for m in scanner_results[:5]:
                                if m.get('symbol') and m['symbol'] not in all_symbols:
                                    all_symbols.add(m['symbol'])
                                    m['category'] = category
                                    top_movers.append(m)
                    
                    # Get quotes for all movers
                    if top_movers:
                        symbols = [m["symbol"] for m in top_movers]
                        quotes = await ib_service.get_quotes_batch(symbols)
                        quotes_map = {q["symbol"]: q for q in quotes}
                        top_movers = [
                            {**m, "quote": quotes_map.get(m["symbol"], {})}
                            for m in top_movers
                        ]
                    
                    # Get market context (indices)
                    indices = ["SPY", "QQQ", "DIA", "IWM", "VIX"]
                    index_quotes = await ib_service.get_quotes_batch(indices)
                    market_context["indices"] = {q["symbol"]: q for q in index_quotes if q.get("price")}
                    
        except Exception as e:
            print(f"Error gathering market data: {e}")
        
        # Generate the newsletter with comprehensive context
        newsletter = await service.generate_premarket_newsletter(
            top_movers=top_movers,
            market_context=market_context
        )
        
        # Cache it for today
        service._cached_newsletter = newsletter
        
        return newsletter
        
    except Exception as e:
        print(f"Error auto-generating newsletter: {e}")
        return {
            "title": "Market Intelligence",
            "date": datetime.now(timezone.utc).isoformat(),
            "market_outlook": {
                "sentiment": "neutral",
                "key_levels": "Data unavailable",
                "focus": "Error generating briefing"
            },
            "summary": f"Unable to generate market intelligence: {str(e)}. Check IB Gateway connection and Perplexity API key.",
            "top_stories": [],
            "watchlist": [],
            "opportunities": [],
            "error": str(e)
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
