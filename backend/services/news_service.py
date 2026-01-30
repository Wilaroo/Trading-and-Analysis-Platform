"""
News Service - Fetches news from Alpaca API and other sources
Provides real-time market news and ticker-specific headlines
"""
import logging
import os
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class NewsService:
    """Service for fetching news from Alpaca and other sources"""
    
    def __init__(self, ib_service=None):
        self.ib_service = ib_service
        self._news_client = None
        self._init_alpaca_news()
        
    def _init_alpaca_news(self):
        """Initialize Alpaca news client"""
        try:
            api_key = os.environ.get("ALPACA_API_KEY")
            secret_key = os.environ.get("ALPACA_SECRET_KEY")
            
            if api_key and secret_key:
                from alpaca.data.historical.news import NewsClient
                self._news_client = NewsClient(api_key=api_key, secret_key=secret_key)
                logger.info("Alpaca NewsClient initialized")
            else:
                logger.warning("Alpaca credentials not found for news")
        except Exception as e:
            logger.warning(f"Failed to initialize Alpaca news client: {e}")
            self._news_client = None
        
    def set_ib_service(self, ib_service):
        """Set the IB service for news fetching"""
        self.ib_service = ib_service
    
    async def get_ticker_news(self, symbol: str, max_items: int = 10) -> List[Dict]:
        """
        Fetch news for a specific ticker symbol using Alpaca.
        """
        # Try Alpaca first
        if self._news_client:
            try:
                from alpaca.data.requests import NewsRequest
                
                request = NewsRequest(
                    symbols=[symbol.upper()],
                    start=datetime.now(timezone.utc) - timedelta(days=3),
                    end=datetime.now(timezone.utc),
                    limit=max_items
                )
                
                news_items = self._news_client.get_news(request)
                
                if news_items and hasattr(news_items, 'news'):
                    formatted_news = []
                    for item in news_items.news[:max_items]:
                        formatted_news.append({
                            "id": str(item.id) if hasattr(item, 'id') else None,
                            "symbol": symbol.upper(),
                            "headline": item.headline if hasattr(item, 'headline') else "",
                            "summary": item.summary if hasattr(item, 'summary') else "",
                            "source": item.source if hasattr(item, 'source') else "Alpaca",
                            "timestamp": item.created_at.isoformat() if hasattr(item, 'created_at') else datetime.now(timezone.utc).isoformat(),
                            "url": item.url if hasattr(item, 'url') else None,
                            "sentiment": self._analyze_sentiment(item.headline if hasattr(item, 'headline') else ""),
                            "is_placeholder": False
                        })
                    
                    if formatted_news:
                        return formatted_news
            except Exception as e:
                logger.warning(f"Failed to get Alpaca news for {symbol}: {e}")
        
        # Fallback to IB if available
        if self.ib_service:
            try:
                news = await self.ib_service.get_news_for_symbol(symbol)
                if news:
                    return news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get IB news for {symbol}: {e}")
        
        # Return structured placeholder when nothing available
        return self._get_placeholder_news(symbol, max_items)
    
    async def get_market_news(self, max_items: int = 20) -> List[Dict]:
        """
        Fetch general market news headlines using Alpaca.
        Covers major indices and market-moving news.
        """
        if self._news_client:
            try:
                from alpaca.data.requests import NewsRequest
                
                # Get general market news by not specifying symbols
                # or by using major ETFs/indices
                request = NewsRequest(
                    symbols=["SPY", "QQQ", "IWM", "DIA"],  # Major market ETFs
                    start=datetime.now(timezone.utc) - timedelta(days=1),
                    end=datetime.now(timezone.utc),
                    limit=max_items,
                    include_content=False
                )
                
                news_items = self._news_client.get_news(request)
                
                if news_items and hasattr(news_items, 'news'):
                    formatted_news = []
                    seen_headlines = set()
                    
                    for item in news_items.news:
                        headline = item.headline if hasattr(item, 'headline') else ""
                        # Deduplicate
                        if headline and headline not in seen_headlines:
                            seen_headlines.add(headline)
                            formatted_news.append({
                                "id": str(item.id) if hasattr(item, 'id') else None,
                                "headline": headline,
                                "summary": item.summary if hasattr(item, 'summary') else "",
                                "source": item.source if hasattr(item, 'source') else "Alpaca",
                                "timestamp": item.created_at.isoformat() if hasattr(item, 'created_at') else datetime.now(timezone.utc).isoformat(),
                                "url": item.url if hasattr(item, 'url') else None,
                                "symbols": list(item.symbols) if hasattr(item, 'symbols') else [],
                                "sentiment": self._analyze_sentiment(headline),
                                "is_placeholder": False
                            })
                    
                    if formatted_news:
                        return formatted_news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get Alpaca market news: {e}")
        
        # Fallback to IB if available
        if self.ib_service:
            try:
                news = await self.ib_service.get_general_news()
                if news:
                    return news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get general news from IB: {e}")
        
        return self._get_placeholder_market_news(max_items)
    
    async def get_market_summary(self) -> Dict:
        """
        Get a summary of today's market news for the AI assistant.
        Returns structured data with key headlines and themes.
        """
        news = await self.get_market_news(max_items=15)
        
        if not news or (len(news) == 1 and news[0].get("is_placeholder")):
            return {
                "available": False,
                "message": "Market news unavailable. Check Alpaca API connection.",
                "headlines": [],
                "themes": []
            }
        
        # Extract key information
        headlines = [item.get("headline", "") for item in news if not item.get("is_placeholder")]
        
        # Simple theme extraction
        themes = []
        theme_keywords = {
            "Fed": "Federal Reserve / Interest Rates",
            "earnings": "Earnings Reports",
            "inflation": "Inflation Data",
            "jobs": "Employment Data",
            "AI": "AI / Technology",
            "oil": "Energy / Oil",
            "China": "China / Trade",
            "recession": "Economic Outlook",
            "rally": "Market Rally",
            "selloff": "Market Selloff",
            "volatility": "Volatility"
        }
        
        combined_text = " ".join(headlines).lower()
        for keyword, theme in theme_keywords.items():
            if keyword.lower() in combined_text:
                themes.append(theme)
        
        # Sentiment summary
        sentiments = [item.get("sentiment", "neutral") for item in news]
        bullish = sentiments.count("bullish")
        bearish = sentiments.count("bearish")
        
        if bullish > bearish * 2:
            overall_sentiment = "bullish"
        elif bearish > bullish * 2:
            overall_sentiment = "bearish"
        else:
            overall_sentiment = "mixed"
        
        return {
            "available": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "headline_count": len(headlines),
            "headlines": headlines[:10],
            "themes": list(set(themes))[:5],
            "overall_sentiment": overall_sentiment,
            "sentiment_breakdown": {
                "bullish": bullish,
                "bearish": bearish,
                "neutral": len(sentiments) - bullish - bearish
            },
            "sources": list(set(item.get("source", "") for item in news if item.get("source")))
        }
    
    def _analyze_sentiment(self, text: str) -> str:
        """Simple keyword-based sentiment analysis"""
        if not text:
            return "neutral"
        
        text_lower = text.lower()
        
        bullish_words = ["surge", "rally", "jump", "gain", "rise", "soar", "boom", "bullish", 
                        "upgrade", "beat", "record", "high", "growth", "strong", "positive"]
        bearish_words = ["drop", "fall", "plunge", "crash", "decline", "sink", "bearish",
                        "downgrade", "miss", "low", "weak", "negative", "concern", "fear", "sell"]
        
        bullish_count = sum(1 for word in bullish_words if word in text_lower)
        bearish_count = sum(1 for word in bearish_words if word in text_lower)
        
        if bullish_count > bearish_count:
            return "bullish"
        elif bearish_count > bullish_count:
            return "bearish"
        return "neutral"
    
    def _get_placeholder_news(self, symbol: str, max_items: int) -> List[Dict]:
        """Generate placeholder news when no data available"""
        now = datetime.now(timezone.utc)
        
        return [
            {
                "id": f"{symbol}-news-placeholder",
                "symbol": symbol,
                "headline": f"No recent news available for {symbol}",
                "summary": "Check Alpaca API connection or try a different symbol.",
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
                "id": "market-news-placeholder",
                "headline": "Market news unavailable",
                "summary": "Check Alpaca API connection for live market news.",
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


def init_news_service(ib_service=None) -> NewsService:
    """Initialize news service with optional IB service"""
    global _news_service
    _news_service = NewsService(ib_service)
    return _news_service
