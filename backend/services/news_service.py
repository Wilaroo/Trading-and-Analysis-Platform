"""
News Service - Fetches news from Finnhub and other sources
Provides real-time market news and ticker-specific headlines
"""
import logging
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class NewsService:
    """Service for fetching news from Finnhub and other sources"""
    
    def __init__(self, ib_service=None):
        self.ib_service = ib_service
        self._finnhub_key = os.environ.get("FINNHUB_API_KEY")
        
        if self._finnhub_key:
            logger.info("Finnhub API key loaded for news")
        else:
            logger.warning("No Finnhub API key found for news")
        
    def set_ib_service(self, ib_service):
        """Set the IB service for news fetching"""
        self.ib_service = ib_service
    
    async def get_ticker_news(self, symbol: str, max_items: int = 10) -> List[Dict]:
        """
        Fetch news for a specific ticker symbol using Finnhub.
        """
        if self._finnhub_key:
            try:
                # Finnhub company news endpoint
                url = f"https://finnhub.io/api/v1/company-news"
                
                # Get news from last 7 days
                today = datetime.now(timezone.utc).date()
                week_ago = today - timedelta(days=7)
                
                params = {
                    "symbol": symbol.upper(),
                    "from": week_ago.isoformat(),
                    "to": today.isoformat(),
                    "token": self._finnhub_key
                }
                
                resp = requests.get(url, params=params, timeout=10)
                
                if resp.status_code == 200:
                    news_items = resp.json()
                    
                    if news_items:
                        formatted_news = []
                        for item in news_items[:max_items]:
                            formatted_news.append({
                                "id": str(item.get("id", "")),
                                "symbol": symbol.upper(),
                                "headline": item.get("headline", ""),
                                "summary": item.get("summary", ""),
                                "source": item.get("source", "Finnhub"),
                                "timestamp": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat() if item.get("datetime") else datetime.now(timezone.utc).isoformat(),
                                "url": item.get("url"),
                                "image": item.get("image"),
                                "sentiment": self._analyze_sentiment(item.get("headline", "")),
                                "is_placeholder": False
                            })
                        
                        if formatted_news:
                            return formatted_news
                else:
                    logger.warning(f"Finnhub news request failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed to get Finnhub news for {symbol}: {e}")
        
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
        Fetch general market news headlines using Finnhub.
        """
        if self._finnhub_key:
            try:
                # Finnhub general market news
                url = f"https://finnhub.io/api/v1/news"
                params = {
                    "category": "general",
                    "token": self._finnhub_key
                }
                
                resp = requests.get(url, params=params, timeout=10)
                
                if resp.status_code == 200:
                    news_items = resp.json()
                    
                    if news_items:
                        formatted_news = []
                        seen_headlines = set()
                        
                        for item in news_items:
                            headline = item.get("headline", "")
                            # Deduplicate
                            if headline and headline not in seen_headlines:
                                seen_headlines.add(headline)
                                formatted_news.append({
                                    "id": str(item.get("id", "")),
                                    "headline": headline,
                                    "summary": item.get("summary", ""),
                                    "source": item.get("source", "Finnhub"),
                                    "timestamp": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat() if item.get("datetime") else datetime.now(timezone.utc).isoformat(),
                                    "url": item.get("url"),
                                    "image": item.get("image"),
                                    "category": item.get("category", "general"),
                                    "sentiment": self._analyze_sentiment(headline),
                                    "is_placeholder": False
                                })
                        
                        if formatted_news:
                            return formatted_news[:max_items]
                else:
                    logger.warning(f"Finnhub market news request failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed to get Finnhub market news: {e}")
        
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
        news = await self.get_market_news(max_items=20)
        
        if not news or (len(news) == 1 and news[0].get("is_placeholder")):
            return {
                "available": False,
                "message": "Market news unavailable. Check Finnhub API connection.",
                "headlines": [],
                "themes": []
            }
        
        # Extract key information
        headlines = [item.get("headline", "") for item in news if not item.get("is_placeholder")]
        
        # Theme extraction with expanded keywords
        themes = []
        theme_keywords = {
            "Fed": "Federal Reserve / Interest Rates",
            "interest rate": "Federal Reserve / Interest Rates",
            "Powell": "Federal Reserve / Interest Rates",
            "earnings": "Earnings Reports",
            "revenue": "Earnings Reports",
            "profit": "Earnings Reports",
            "inflation": "Inflation Data",
            "CPI": "Inflation Data",
            "PPI": "Inflation Data",
            "jobs": "Employment Data",
            "unemployment": "Employment Data",
            "payroll": "Employment Data",
            "AI": "AI / Technology",
            "artificial intelligence": "AI / Technology",
            "tech": "AI / Technology",
            "oil": "Energy / Oil",
            "energy": "Energy / Oil",
            "China": "China / Trade",
            "tariff": "China / Trade",
            "trade": "China / Trade",
            "recession": "Economic Outlook",
            "GDP": "Economic Outlook",
            "economy": "Economic Outlook",
            "rally": "Market Rally",
            "surge": "Market Rally",
            "record high": "Market Rally",
            "selloff": "Market Selloff",
            "drop": "Market Selloff",
            "plunge": "Market Selloff",
            "volatility": "Volatility",
            "VIX": "Volatility",
            "crypto": "Crypto / Bitcoin",
            "bitcoin": "Crypto / Bitcoin",
            "Trump": "Politics / Policy",
            "Biden": "Politics / Policy",
            "Congress": "Politics / Policy"
        }
        
        combined_text = " ".join(headlines).lower()
        for keyword, theme in theme_keywords.items():
            if keyword.lower() in combined_text and theme not in themes:
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
        
        # Get unique sources
        sources = list(set(item.get("source", "") for item in news if item.get("source")))
        
        return {
            "available": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "headline_count": len(headlines),
            "headlines": headlines[:12],
            "themes": themes[:6],
            "overall_sentiment": overall_sentiment,
            "sentiment_breakdown": {
                "bullish": bullish,
                "bearish": bearish,
                "neutral": len(sentiments) - bullish - bearish
            },
            "sources": sources[:5]
        }
    
    def _analyze_sentiment(self, text: str) -> str:
        """Simple keyword-based sentiment analysis"""
        if not text:
            return "neutral"
        
        text_lower = text.lower()
        
        bullish_words = ["surge", "rally", "jump", "gain", "rise", "soar", "boom", "bullish", 
                        "upgrade", "beat", "record", "high", "growth", "strong", "positive",
                        "optimistic", "outperform", "buy", "breakout", "all-time high"]
        bearish_words = ["drop", "fall", "plunge", "crash", "decline", "sink", "bearish",
                        "downgrade", "miss", "low", "weak", "negative", "concern", "fear",
                        "sell", "selloff", "warning", "risk", "recession", "layoff"]
        
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
                "summary": "Check API connection or try a different symbol.",
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
                "summary": "Check Finnhub API connection for live market news.",
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
