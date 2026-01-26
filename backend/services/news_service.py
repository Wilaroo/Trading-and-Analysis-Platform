"""
News Service - Fetches news from Interactive Brokers API
Provides ticker-specific news headlines and articles
"""
import logging
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class NewsService:
    """Service for fetching news from IB and other sources"""
    
    def __init__(self, ib_service=None):
        self.ib_service = ib_service
        
    def set_ib_service(self, ib_service):
        """Set the IB service for news fetching"""
        self.ib_service = ib_service
    
    async def get_ticker_news(self, symbol: str, max_items: int = 10) -> List[Dict]:
        """
        Fetch news for a specific ticker symbol.
        Uses IB API if connected, otherwise returns mock data for display testing.
        """
        if self.ib_service:
            try:
                news = await self.ib_service.get_news_for_symbol(symbol)
                if news:
                    return news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get IB news for {symbol}: {e}")
        
        # Return structured placeholder when IB not connected
        return self._get_placeholder_news(symbol, max_items)
    
    async def get_market_news(self, max_items: int = 20) -> List[Dict]:
        """
        Fetch general market news headlines.
        """
        if self.ib_service:
            try:
                news = await self.ib_service.get_general_news()
                if news:
                    return news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get general news: {e}")
        
        return self._get_placeholder_market_news(max_items)
    
    def _get_placeholder_news(self, symbol: str, max_items: int) -> List[Dict]:
        """Generate placeholder news when IB is not connected"""
        now = datetime.now(timezone.utc)
        
        return [
            {
                "id": f"{symbol}-news-1",
                "symbol": symbol,
                "headline": f"Connect to IB Gateway for live {symbol} news",
                "summary": "Real-time news requires an active connection to Interactive Brokers Gateway. Start IB Gateway and click 'Connect' to see live news.",
                "source": "System",
                "timestamp": now.isoformat(),
                "url": None,
                "sentiment": "neutral",
                "is_placeholder": True
            }
        ]
    
    def _get_placeholder_market_news(self, max_items: int) -> List[Dict]:
        """Generate placeholder market news"""
        now = datetime.now(timezone.utc)
        
        return [
            {
                "id": "market-news-1",
                "headline": "Connect to IB Gateway for live market news",
                "summary": "Real-time market news requires an active connection to Interactive Brokers Gateway.",
                "source": "System",
                "timestamp": now.isoformat(),
                "sentiment": "neutral",
                "is_placeholder": True
            }
        ]


# Global service instance
_news_service: Optional[NewsService] = None


def get_news_service() -> NewsService:
    """Get or create the news service instance"""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service


def init_news_service(ib_service) -> NewsService:
    """Initialize news service with IB service"""
    global _news_service
    _news_service = NewsService(ib_service)
    return _news_service
