"""
News Service - Fetches news from IB Gateway (primary), Finnhub (fallback), and other sources
Provides real-time market news and ticker-specific headlines

Priority order for ticker news:
1. IB Gateway Historical News (reqHistoricalNews) - Professional financial news, unlimited
2. Finnhub Company News - Good backup, rate limited
3. IB Real-time News Ticks - Fallback if historical fails

Priority order for market news:
1. Finnhub General News - Best for broad market news
2. IB News Bulletins - Exchange bulletins
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
    """Service for fetching news - prioritizes IB Gateway, falls back to Finnhub"""
    
    def __init__(self, ib_service=None):
        self.ib_service = ib_service
        self._finnhub_key = os.environ.get("FINNHUB_API_KEY")
        self._news_providers_cache = None
        self._providers_cache_time = None
        
        if self._finnhub_key:
            logger.info("Finnhub API key loaded for news (fallback)")
        else:
            logger.warning("No Finnhub API key found for news fallback")
        
    def set_ib_service(self, ib_service):
        """Set the IB service for news fetching"""
        self.ib_service = ib_service
        self._news_providers_cache = None  # Reset cache when service changes
    
    async def get_news_providers(self) -> List[Dict]:
        """
        Get list of subscribed IB news providers.
        Checks pushed data first, then IB service, cached for 5 minutes.
        """
        # Check cache
        if self._news_providers_cache and self._providers_cache_time:
            cache_age = (datetime.now(timezone.utc) - self._providers_cache_time).total_seconds()
            if cache_age < 300:  # 5 minute cache
                return self._news_providers_cache
        
        # Check pushed data first (from IB Data Pusher)
        try:
            from routers.ib import _pushed_ib_data
            pushed_providers = _pushed_ib_data.get("news_providers", [])
            if pushed_providers:
                self._news_providers_cache = pushed_providers
                self._providers_cache_time = datetime.now(timezone.utc)
                logger.info(f"Using pushed news providers: {[p.get('code') for p in pushed_providers]}")
                return pushed_providers
        except Exception as e:
            logger.debug(f"Could not check pushed providers: {e}")
        
        # Fallback to direct IB service
        if not self.ib_service:
            return []
        
        try:
            providers = await self.ib_service.get_news_providers()
            if providers:
                self._news_providers_cache = providers
                self._providers_cache_time = datetime.now(timezone.utc)
                logger.info(f"IB News Providers: {[p.get('code') for p in providers]}")
            return providers
        except Exception as e:
            logger.warning(f"Failed to get news providers: {e}")
            return []
    
    async def get_ticker_news(self, symbol: str, max_items: int = 10) -> List[Dict]:
        """
        Fetch news for a specific ticker symbol.
        
        Priority:
        1. IB Pushed News (from local data pusher) - Real-time from your IB subscription
        2. IB Historical News (reqHistoricalNews) - Best quality, no rate limits
        3. Finnhub Company News - Good fallback
        4. IB Real-time Ticks - Last resort
        """
        symbol = symbol.upper()
        
        # === PRIORITY 0: Check pushed news from IB Data Pusher ===
        try:
            from routers.ib import _pushed_ib_data
            pushed_news = _pushed_ib_data.get("news", {})
            
            if pushed_news.get(symbol):
                # Check if pusher data is fresh (within 5 minutes)
                last_update = _pushed_ib_data.get("last_update")
                is_fresh = False
                if last_update:
                    try:
                        last_dt = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
                        age_seconds = (datetime.now(timezone.utc) - last_dt).total_seconds()
                        is_fresh = age_seconds < 300  # 5 minutes
                    except:
                        pass
                
                if is_fresh:
                    formatted_news = []
                    for item in pushed_news[symbol][:max_items]:
                        formatted_news.append({
                            "id": item.get("article_id", ""),
                            "article_id": item.get("article_id"),
                            "provider_code": item.get("provider_code"),
                            "symbol": symbol,
                            "headline": item.get("headline", ""),
                            "summary": "",
                            "source": self._get_provider_name(item.get("provider_code", "IB")),
                            "timestamp": item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "url": None,
                            "sentiment": self._analyze_sentiment(item.get("headline", "")),
                            "source_type": "ib_pushed",
                            "is_placeholder": False
                        })
                    
                    if formatted_news:
                        logger.info(f"Got {len(formatted_news)} pushed IB news for {symbol}")
                        return formatted_news
        except Exception as e:
            logger.debug(f"Could not check pushed news: {e}")
        
        # === PRIORITY 1: IB Historical News ===
        if self.ib_service:
            try:
                news = await self.ib_service.get_historical_news(
                    symbol=symbol,
                    total_results=max_items
                )
                
                if news and len(news) > 0:
                    # Format and enrich with sentiment
                    formatted_news = []
                    for item in news[:max_items]:
                        formatted_news.append({
                            "id": item.get("id", item.get("article_id", "")),
                            "article_id": item.get("article_id"),
                            "provider_code": item.get("provider_code"),
                            "symbol": symbol,
                            "headline": item.get("headline", ""),
                            "summary": "",  # IB doesn't provide summary in headlines
                            "source": self._get_provider_name(item.get("provider_code", "IB")),
                            "timestamp": item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "url": None,  # Would need article fetch to get URL
                            "sentiment": self._analyze_sentiment(item.get("headline", "")),
                            "source_type": "ib_historical",
                            "is_placeholder": False
                        })
                    
                    if formatted_news:
                        logger.info(f"Got {len(formatted_news)} IB historical news for {symbol}")
                        return formatted_news
                        
            except Exception as e:
                logger.warning(f"IB historical news failed for {symbol}: {e}")
        
        # === PRIORITY 2: Finnhub Company News ===
        if self._finnhub_key:
            try:
                url = "https://finnhub.io/api/v1/company-news"
                
                today = datetime.now(timezone.utc).date()
                week_ago = today - timedelta(days=7)
                
                params = {
                    "symbol": symbol,
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
                                "symbol": symbol,
                                "headline": item.get("headline", ""),
                                "summary": item.get("summary", ""),
                                "source": item.get("source", "Finnhub"),
                                "timestamp": datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc).isoformat() if item.get("datetime") else datetime.now(timezone.utc).isoformat(),
                                "url": item.get("url"),
                                "image": item.get("image"),
                                "sentiment": self._analyze_sentiment(item.get("headline", "")),
                                "source_type": "finnhub",
                                "is_placeholder": False
                            })
                        
                        if formatted_news:
                            logger.info(f"Got {len(formatted_news)} Finnhub news for {symbol}")
                            return formatted_news
                else:
                    logger.warning(f"Finnhub news request failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed to get Finnhub news for {symbol}: {e}")
        
        # === PRIORITY 3: IB Real-time News Ticks (fallback) ===
        if self.ib_service:
            try:
                news = await self.ib_service.get_news_for_symbol(symbol)
                if news:
                    for item in news:
                        item["sentiment"] = self._analyze_sentiment(item.get("headline", ""))
                        item["is_placeholder"] = False
                    return news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get IB realtime news for {symbol}: {e}")
        
        # === No news available ===
        return self._get_placeholder_news(symbol, max_items)
    
    async def get_market_news(self, max_items: int = 20) -> List[Dict]:
        """
        Fetch general market news headlines.
        Uses Finnhub as primary (better for broad market news).
        """
        # === PRIORITY 1: Finnhub General News ===
        if self._finnhub_key:
            try:
                url = "https://finnhub.io/api/v1/news"
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
                                    "source_type": "finnhub",
                                    "is_placeholder": False
                                })
                        
                        if formatted_news:
                            return formatted_news[:max_items]
                else:
                    logger.warning(f"Finnhub market news request failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Failed to get Finnhub market news: {e}")
        
        # === PRIORITY 2: IB News Bulletins ===
        if self.ib_service:
            try:
                news = await self.ib_service.get_general_news()
                if news:
                    for item in news:
                        item["sentiment"] = self._analyze_sentiment(item.get("headline", ""))
                        item["is_placeholder"] = False
                    return news[:max_items]
            except Exception as e:
                logger.warning(f"Failed to get general news from IB: {e}")
        
        return self._get_placeholder_market_news(max_items)
    
    async def get_news_article(self, provider_code: str, article_id: str) -> Dict:
        """
        Get full news article content from IB.
        
        Args:
            provider_code: The news provider (e.g., "BZ", "FLY", "DJ")
            article_id: The article ID from historical news
        
        Returns:
            Dict with article content
        """
        if not self.ib_service:
            return {"error": "IB service not available"}
        
        try:
            return await self.ib_service.get_news_article(provider_code, article_id)
        except Exception as e:
            logger.error(f"Failed to get news article: {e}")
            return {"error": str(e)}
    
    async def get_market_summary(self) -> Dict:
        """
        Get a summary of today's market news for the AI assistant.
        Returns structured data with key headlines and themes.
        """
        news = await self.get_market_news(max_items=20)
        
        if not news or (len(news) == 1 and news[0].get("is_placeholder")):
            return {
                "available": False,
                "message": "Market news unavailable. Check API connections.",
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
    
    def _get_provider_name(self, code: str) -> str:
        """Convert provider code to human-readable name"""
        provider_names = {
            "BZ": "Benzinga",
            "FLY": "Fly on the Wall",
            "DJ": "Dow Jones",
            "BRFG": "Briefing.com",
            "BRFUPDN": "Briefing.com Upgrades/Downgrades",
            "MT": "Midnight Trader",
            "TWTR": "Twitter/X",
            "RTN": "Reuters",
            "DJNL": "DJ Newswires",
        }
        return provider_names.get(code, code)
    
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
                "summary": "Check IB Gateway connection or try a different symbol.",
                "source": "System",
                "timestamp": now.isoformat(),
                "url": None,
                "sentiment": "neutral",
                "source_type": "placeholder",
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
                "summary": "Check Finnhub API or IB Gateway connection for live market news.",
                "source": "System",
                "timestamp": now.isoformat(),
                "sentiment": "neutral",
                "source_type": "placeholder",
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
