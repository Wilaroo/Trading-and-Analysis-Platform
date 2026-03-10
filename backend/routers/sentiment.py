"""
Sentiment Analysis API Router
Provides endpoints for news sentiment analysis.
"""
from fastapi import APIRouter, HTTPException
from typing import List
import logging

from services.sentiment_analysis_service import get_sentiment_service

router = APIRouter(prefix="/api/sentiment", tags=["Sentiment Analysis"])
logger = logging.getLogger(__name__)


def _ensure_initialized():
    """Ensure sentiment service is initialized with dependencies"""
    service = get_sentiment_service()
    if not service.is_initialized():
        try:
            from services.news_service import get_news_service
            from services.llm_service import get_llm_service
            news = get_news_service()
            llm = get_llm_service()
            service.set_services(news_service=news, llm_service=llm)
        except Exception as e:
            logger.warning(f"Could not fully initialize sentiment service: {e}")
    return service


@router.get("/analyze/{symbol}")
async def analyze_sentiment(symbol: str, deep: bool = False):
    """
    Analyze sentiment for a symbol.
    
    Args:
        symbol: Stock symbol to analyze
        deep: If true, use AI for deeper analysis (slower but more accurate)
    """
    try:
        service = _ensure_initialized()
        result = await service.analyze_sentiment(symbol.upper(), use_ai=deep)
        
        return {
            "success": True,
            **result.to_dict()
        }
    except Exception as e:
        logger.error(f"Error analyzing sentiment for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market")
async def get_market_sentiment():
    """
    Get overall market sentiment from major indices.
    """
    try:
        service = _ensure_initialized()
        result = await service.get_market_sentiment()
        
        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"Error getting market sentiment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch")
async def analyze_batch(symbols: List[str], deep: bool = False):
    """
    Analyze sentiment for multiple symbols.
    """
    try:
        service = _ensure_initialized()
        results = []
        
        for symbol in symbols[:10]:  # Limit to 10 symbols
            try:
                result = await service.analyze_sentiment(symbol.upper(), use_ai=deep)
                results.append(result.to_dict())
            except Exception as e:
                logger.warning(f"Could not analyze {symbol}: {e}")
        
        return {
            "success": True,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        logger.error(f"Error in batch sentiment analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_sentiment_summary(symbols: str = "AAPL,MSFT,NVDA,TSLA,GOOGL"):
    """
    Get a formatted sentiment summary for display.
    """
    try:
        service = _ensure_initialized()
        symbol_list = [s.strip().upper() for s in symbols.split(",")]
        
        results = []
        for symbol in symbol_list[:5]:
            try:
                result = await service.analyze_sentiment(symbol, use_ai=False)
                results.append(result)
            except:
                pass
        
        summary = service.get_sentiment_summary_for_ai(results)
        
        return {
            "success": True,
            "summary": summary,
            "count": len(results)
        }
    except Exception as e:
        logger.error(f"Error getting sentiment summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
