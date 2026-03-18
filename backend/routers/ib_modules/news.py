"""
News Endpoints for IB Router

Handles news-related functionality including IB news providers,
historical news, and news articles.
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["IB News"])

# Service references (will be set during init)
_ib_service = None
_news_service = None


def init_news_services(ib_service, news_service):
    """Initialize the services for this router"""
    global _ib_service, _news_service
    _ib_service = ib_service
    _news_service = news_service


@router.get("/news/providers")
async def get_news_providers():
    """
    Get list of subscribed IB news providers.
    Returns provider codes like BZ (Benzinga), FLY (Fly), DJ (Dow Jones), etc.
    Use these codes to understand what news sources are available.
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        providers = await _ib_service.get_news_providers()
        
        # Map codes to names for better readability
        provider_names = {
            "BZ": "Benzinga",
            "FLY": "Fly on the Wall",
            "DJ": "Dow Jones",
            "BRFG": "Briefing.com",
            "BRFUPDN": "Briefing.com Upgrades/Downgrades",
            "MT": "Midnight Trader",
            "RTN": "Reuters",
            "DJNL": "DJ Newswires",
        }
        
        enriched = []
        for p in providers:
            code = p.get("code", "")
            enriched.append({
                "code": code,
                "name": provider_names.get(code, p.get("name", code)),
                "raw_name": p.get("name", "")
            })
        
        return {
            "success": True,
            "providers": enriched,
            "count": len(enriched),
            "note": "These are the news providers you're subscribed to via IB"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching news providers: {str(e)}")


@router.get("/news/historical/{symbol}")
async def get_historical_news(
    symbol: str,
    max_results: int = 10,
    days_back: int = 7,
    providers: str = None
):
    """
    Get historical news for a ticker using IB's reqHistoricalNews API.
    
    This is the proper IB news API that returns professional financial news.
    
    Args:
        symbol: Stock symbol (e.g., AAPL, NVDA)
        max_results: Maximum number of news items (default 10, max 50)
        days_back: How many days back to search (default 7)
        providers: Comma-separated provider codes (e.g., "BZ,FLY"). If empty, uses all subscribed.
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        # Parse provider codes if provided
        provider_codes = None
        if providers:
            provider_codes = [p.strip() for p in providers.split(",")]
        
        # Calculate date range
        end_date = datetime.now(timezone.utc).strftime("%Y%m%d %H:%M:%S")
        start_dt = datetime.now(timezone.utc) - timedelta(days=days_back)
        start_date = start_dt.strftime("%Y%m%d %H:%M:%S")
        
        news = await _ib_service.get_historical_news(
            symbol=symbol.upper(),
            provider_codes=provider_codes,
            total_results=min(max_results, 50),
            start_date=start_date,
            end_date=end_date
        )
        
        return {
            "success": True,
            "symbol": symbol.upper(),
            "news": news,
            "count": len(news),
            "date_range": {
                "start": start_date,
                "end": end_date
            },
            "providers_used": provider_codes if provider_codes else "all_subscribed",
            "source": "ib_historical_news"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching historical news: {str(e)}")


@router.get("/news/article/{provider_code}/{article_id}")
async def get_news_article(provider_code: str, article_id: str):
    """
    Get full news article content from IB.
    
    Args:
        provider_code: The news provider (e.g., BZ, FLY, DJ)
        article_id: The article ID from historical news endpoint
    """
    if not _ib_service:
        raise HTTPException(status_code=500, detail="IB service not initialized")
    
    try:
        article = await _ib_service.get_news_article(provider_code, article_id)
        return {
            "success": True,
            "provider_code": provider_code,
            "article_id": article_id,
            "article": article
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching article: {str(e)}")


@router.get("/news/{symbol}")
async def get_ticker_news(symbol: str):
    """Get news headlines for a specific ticker symbol (uses NewsService with IB priority)"""
    if not _news_service:
        raise HTTPException(status_code=500, detail="News service not initialized")
    
    try:
        news = await _news_service.get_ticker_news(symbol.upper(), max_items=15)
        return {
            "symbol": symbol.upper(),
            "news": news,
            "count": len(news),
            "source": news[0].get("source_type", "unknown") if news else "none"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching news: {str(e)}")


@router.get("/news")
async def get_market_news():
    """Get general market news headlines"""
    if not _news_service:
        raise HTTPException(status_code=500, detail="News service not initialized")
    
    try:
        news = await _news_service.get_market_news(max_items=20)
        return {
            "news": news,
            "count": len(news)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching news: {str(e)}")
