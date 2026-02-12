"""
Web Research Service - Tavily Search + Custom Financial Scrapers + Agent Skills
Provides internet access and research capabilities for the AI assistant

Features:
- Tavily web search with intelligent caching (minimize credit usage)
- Agent Skills: Specialized tools for company info, stock analysis
- Custom scrapers for SEC EDGAR, Yahoo Finance, Finviz
- Smart caching with different TTLs based on data type
"""

import os
import asyncio
import aiohttp
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from bs4 import BeautifulSoup
import re
import json
import hashlib

logger = logging.getLogger(__name__)

# ===================== CACHE CONFIGURATION =====================

# Different TTLs based on data freshness requirements
CACHE_TTL = {
    "search": 300,           # 5 min - general web search
    "news": 180,             # 3 min - news is more time-sensitive
    "company_info": 3600,    # 1 hour - company fundamentals don't change often
    "stock_analysis": 600,   # 10 min - analysis/sentiment
    "sec_filings": 86400,    # 24 hours - SEC filings are static
    "analyst_ratings": 3600, # 1 hour - ratings don't change often
    "deep_dive": 900,        # 15 min - comprehensive research
}

# ===================== DATA MODELS =====================

@dataclass
class SearchResult:
    """Individual search result"""
    title: str
    url: str
    content: str
    source: str = ""
    published_date: Optional[str] = None
    score: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

@dataclass
class ResearchResponse:
    """Complete research response"""
    query: str
    results: List[SearchResult]
    synthesis: Optional[str] = None
    answer: Optional[str] = None  # Tavily's built-in answer
    response_time_ms: float = 0.0
    source_type: str = "tavily"  # tavily, sec, yahoo, finviz
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "synthesis": self.synthesis,
            "answer": self.answer,
            "response_time_ms": self.response_time_ms,
            "source_type": self.source_type,
            "timestamp": self.timestamp
        }


# ===================== INTELLIGENT CACHE =====================

class IntelligentCache:
    """
    Smart cache with variable TTLs based on data type.
    Minimizes API calls and Tavily credit usage.
    """
    
    def __init__(self):
        self._cache: Dict[str, Tuple[Any, float, str]] = {}  # key -> (result, timestamp, data_type)
        self._hit_count = 0
        self._miss_count = 0
    
    def _generate_key(self, *args) -> str:
        """Generate a unique cache key from arguments"""
        key_str = ":".join(str(arg) for arg in args)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, data_type: str, *args) -> Optional[Any]:
        """Get from cache if not expired"""
        key = self._generate_key(data_type, *args)
        
        if key in self._cache:
            result, timestamp, cached_type = self._cache[key]
            ttl = CACHE_TTL.get(data_type, 300)
            
            if time.time() - timestamp < ttl:
                self._hit_count += 1
                logger.debug(f"Cache HIT for {data_type}: {args[:2]}...")
                return result
            else:
                # Expired, remove
                del self._cache[key]
        
        self._miss_count += 1
        return None
    
    def set(self, data_type: str, result: Any, *args):
        """Store result in cache"""
        key = self._generate_key(data_type, *args)
        self._cache[key] = (result, time.time(), data_type)
        logger.debug(f"Cache SET for {data_type}: {args[:2]}...")
    
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        total = self._hit_count + self._miss_count
        return {
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_rate": f"{(self._hit_count / total * 100):.1f}%" if total > 0 else "N/A",
            "entries": len(self._cache)
        }
    
    def clear_expired(self):
        """Remove expired entries"""
        now = time.time()
        expired_keys = []
        
        for key, (result, timestamp, data_type) in self._cache.items():
            ttl = CACHE_TTL.get(data_type, 300)
            if now - timestamp >= ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
        
        return len(expired_keys)


# Global intelligent cache instance
_global_cache = IntelligentCache()


# ===================== TAVILY SERVICE =====================

class TavilySearchService:
    """Tavily API integration for web search with intelligent caching"""
    
    def __init__(self):
        self.api_key = os.environ.get("TAVILY_API_KEY", "")
        self._client = None
        self._credit_used = 0  # Track credits used this session
        
    def _get_client(self):
        """Lazy initialization of Tavily client"""
        if self._client is None and self.api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
                logger.info("Tavily client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Tavily client: {e}")
        return self._client
    
    def get_credit_usage(self) -> int:
        """Get estimated credits used this session"""
        return self._credit_used
    
    async def search(
        self,
        query: str,
        search_depth: str = "advanced",
        topic: str = "general",
        max_results: int = 5,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        include_answer: bool = True,
        data_type: str = "search",  # Used for cache TTL
    ) -> ResearchResponse:
        """
        Execute search with Tavily API - uses intelligent caching
        
        Args:
            query: Search query
            search_depth: "basic" or "advanced"
            topic: "general", "news", or "finance"
            max_results: Max results (1-10)
            include_domains: Prioritize these domains
            exclude_domains: Exclude these domains
            include_answer: Include Tavily's AI answer
            data_type: Cache category for TTL selection
        """
        start_time = time.time()
        
        # Check intelligent cache first
        cache_key_args = (query, search_depth, topic, max_results)
        cached = _global_cache.get(data_type, *cache_key_args)
        if cached:
            logger.info(f"🎯 Cache HIT for '{query[:50]}...' (saved 1 credit)")
            return cached
        
        client = self._get_client()
        if not client:
            return ResearchResponse(
                query=query,
                results=[],
                answer="Tavily API key not configured",
                source_type="tavily"
            )
        
        try:
            # Build search params
            search_params = {
                "query": query,
                "search_depth": search_depth,
                "topic": topic,
                "max_results": min(max_results, 10),
                "include_answer": include_answer,
            }
            
            if include_domains:
                search_params["include_domains"] = include_domains[:5]
            if exclude_domains:
                search_params["exclude_domains"] = exclude_domains[:5]
            
            # Execute search in thread pool (Tavily SDK is sync)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.search(**search_params)
            )
            
            # Track credit usage (basic=1, advanced=2)
            self._credit_used += 2 if search_depth == "advanced" else 1
            
            response_time = (time.time() - start_time) * 1000
            
            # Transform results
            results = []
            for item in response.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", "")[:1500],  # Truncate
                    source=item.get("source", ""),
                    published_date=item.get("published_date"),
                    score=item.get("score", 0.0)
                ))
            
            research_response = ResearchResponse(
                query=query,
                results=results,
                answer=response.get("answer"),
                response_time_ms=response_time,
                source_type="tavily"
            )
            
            # Store in intelligent cache
            _global_cache.set(data_type, research_response, *cache_key_args)
            
            logger.info(f"✅ Tavily search: '{query[:50]}...' ({len(results)} results, {response_time:.0f}ms, ~{self._credit_used} credits used)")
            return research_response
            
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return ResearchResponse(
                query=query,
                results=[],
                answer=f"Search failed: {str(e)}",
                response_time_ms=(time.time() - start_time) * 1000,
                source_type="tavily"
            )

    async def search_news(self, query: str, max_results: int = 5) -> ResearchResponse:
        """Search specifically for news articles"""
        return await self.search(
            query=query,
            topic="news",
            max_results=max_results,
            search_depth="advanced"
        )

    async def search_financial(
        self,
        query: str,
        max_results: int = 5
    ) -> ResearchResponse:
        """Search with financial domain focus"""
        financial_domains = [
            "reuters.com", "bloomberg.com", "wsj.com", "cnbc.com",
            "marketwatch.com", "finance.yahoo.com", "seekingalpha.com",
            "fool.com", "investopedia.com", "barrons.com"
        ]
        return await self.search(
            query=query,
            topic="news",
            max_results=max_results,
            include_domains=financial_domains,
            search_depth="advanced"
        )


# ===================== CUSTOM SCRAPERS =====================

class SECEdgarScraper:
    """Scraper for SEC EDGAR filings"""
    
    BASE_URL = "https://www.sec.gov"
    SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
    
    async def search_filings(
        self,
        ticker: str,
        filing_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> ResearchResponse:
        """
        Search SEC EDGAR for company filings
        
        Args:
            ticker: Stock ticker symbol
            filing_types: Filter by type (10-K, 10-Q, 8-K, etc.)
            limit: Max results
        """
        import time
        start_time = time.time()
        
        if filing_types is None:
            filing_types = ["10-K", "10-Q", "8-K"]
        
        results = []
        
        try:
            async with aiohttp.ClientSession() as session:
                # Use SEC full-text search API
                search_url = f"https://efts.sec.gov/LATEST/search-index?q={ticker}&dateRange=custom&startdt=2024-01-01&enddt=2025-12-31&forms={','.join(filing_types)}"
                
                headers = {
                    "User-Agent": "TradeCommand Research Bot (contact@example.com)",
                    "Accept": "application/json"
                }
                
                async with session.get(search_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        for hit in data.get("hits", {}).get("hits", [])[:limit]:
                            source = hit.get("_source", {})
                            filing_url = f"{self.BASE_URL}/cgi-bin/browse-edgar?action=getcompany&CIK={source.get('ciks', [''])[0]}&type={source.get('form', '')}&dateb=&owner=include&count=10"
                            
                            results.append(SearchResult(
                                title=f"{source.get('form', 'Filing')} - {source.get('display_names', [ticker])[0]}",
                                url=filing_url,
                                content=source.get("file_description", "SEC Filing"),
                                source="SEC EDGAR",
                                published_date=source.get("file_date")
                            ))
        except Exception as e:
            logger.error(f"SEC EDGAR search failed: {e}")
            # Fallback to basic filing info
            results.append(SearchResult(
                title=f"SEC Filings for {ticker}",
                url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=include&count=40",
                content=f"View all SEC filings for {ticker} on EDGAR",
                source="SEC EDGAR"
            ))
        
        return ResearchResponse(
            query=f"SEC filings for {ticker}",
            results=results,
            response_time_ms=(time.time() - start_time) * 1000,
            source_type="sec_edgar"
        )


class YahooFinanceScraper:
    """Scraper for Yahoo Finance data"""
    
    async def get_stock_news(self, ticker: str, limit: int = 5) -> ResearchResponse:
        """Get latest news for a stock from Yahoo Finance"""
        import time
        start_time = time.time()
        
        results = []
        
        try:
            url = f"https://finance.yahoo.com/quote/{ticker}/news"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'lxml')
                        
                        # Find news articles
                        articles = soup.find_all('h3', class_=re.compile(r'.*title.*', re.I))[:limit]
                        
                        for article in articles:
                            link = article.find('a')
                            if link:
                                title = link.get_text(strip=True)
                                href = link.get('href', '')
                                if href.startswith('/'):
                                    href = f"https://finance.yahoo.com{href}"
                                
                                results.append(SearchResult(
                                    title=title,
                                    url=href,
                                    content=f"Yahoo Finance news article about {ticker}",
                                    source="Yahoo Finance"
                                ))
        except Exception as e:
            logger.error(f"Yahoo Finance scrape failed: {e}")
        
        # Always include direct link
        if not results:
            results.append(SearchResult(
                title=f"{ticker} News & Analysis",
                url=f"https://finance.yahoo.com/quote/{ticker}/news",
                content=f"Latest news and analysis for {ticker}",
                source="Yahoo Finance"
            ))
        
        return ResearchResponse(
            query=f"Yahoo Finance news for {ticker}",
            results=results,
            response_time_ms=(time.time() - start_time) * 1000,
            source_type="yahoo_finance"
        )

    async def get_analyst_ratings(self, ticker: str) -> ResearchResponse:
        """Get analyst ratings summary"""
        import time
        start_time = time.time()
        
        results = []
        
        try:
            url = f"https://finance.yahoo.com/quote/{ticker}/analysis"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'lxml')
                        
                        # Extract recommendation summary
                        rec_section = soup.find(string=re.compile(r'Recommendation', re.I))
                        if rec_section:
                            parent = rec_section.find_parent('section')
                            if parent:
                                text = parent.get_text(separator=' ', strip=True)[:500]
                                results.append(SearchResult(
                                    title=f"{ticker} Analyst Recommendations",
                                    url=url,
                                    content=text,
                                    source="Yahoo Finance"
                                ))
        except Exception as e:
            logger.error(f"Yahoo analyst ratings scrape failed: {e}")
        
        if not results:
            results.append(SearchResult(
                title=f"{ticker} Analyst Ratings",
                url=f"https://finance.yahoo.com/quote/{ticker}/analysis",
                content=f"View analyst ratings and price targets for {ticker}",
                source="Yahoo Finance"
            ))
        
        return ResearchResponse(
            query=f"Analyst ratings for {ticker}",
            results=results,
            response_time_ms=(time.time() - start_time) * 1000,
            source_type="yahoo_finance"
        )


class FinvizScraper:
    """Scraper for Finviz stock data"""
    
    async def get_stock_overview(self, ticker: str) -> ResearchResponse:
        """Get stock overview from Finviz"""
        import time
        start_time = time.time()
        
        results = []
        
        try:
            url = f"https://finviz.com/quote.ashx?t={ticker}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = BeautifulSoup(html, 'lxml')
                        
                        # Extract key stats table
                        stats = {}
                        table = soup.find('table', class_='snapshot-table2')
                        if table:
                            cells = table.find_all('td')
                            for i in range(0, len(cells) - 1, 2):
                                key = cells[i].get_text(strip=True)
                                val = cells[i + 1].get_text(strip=True)
                                stats[key] = val
                        
                        # Format key metrics
                        key_metrics = []
                        for metric in ['P/E', 'Forward P/E', 'PEG', 'P/S', 'P/B', 'EPS (ttm)', 
                                      'Target Price', 'RSI (14)', 'Rel Volume', 'Avg Volume']:
                            if metric in stats:
                                key_metrics.append(f"{metric}: {stats[metric]}")
                        
                        if key_metrics:
                            results.append(SearchResult(
                                title=f"{ticker} Key Metrics (Finviz)",
                                url=url,
                                content=" | ".join(key_metrics),
                                source="Finviz"
                            ))
                        
                        # Extract news headlines
                        news_table = soup.find('table', id='news-table')
                        if news_table:
                            rows = news_table.find_all('tr')[:5]
                            for row in rows:
                                link = row.find('a')
                                if link:
                                    results.append(SearchResult(
                                        title=link.get_text(strip=True),
                                        url=link.get('href', ''),
                                        content="Finviz news",
                                        source="Finviz"
                                    ))
        except Exception as e:
            logger.error(f"Finviz scrape failed: {e}")
        
        if not results:
            results.append(SearchResult(
                title=f"{ticker} Stock Overview",
                url=f"https://finviz.com/quote.ashx?t={ticker}",
                content=f"View detailed stock data and charts for {ticker}",
                source="Finviz"
            ))
        
        return ResearchResponse(
            query=f"Finviz overview for {ticker}",
            results=results,
            response_time_ms=(time.time() - start_time) * 1000,
            source_type="finviz"
        )


# ===================== UNIFIED RESEARCH SERVICE =====================

class WebResearchService:
    """
    Unified web research service combining Tavily + custom scrapers
    Main interface for the AI assistant
    """
    
    def __init__(self):
        self.tavily = TavilySearchService()
        self.sec = SECEdgarScraper()
        self.yahoo = YahooFinanceScraper()
        self.finviz = FinvizScraper()
        
        # Research cache (MongoDB will be used in production)
        self._research_cache: Dict[str, Dict] = {}
    
    async def search(self, query: str, max_results: int = 5) -> ResearchResponse:
        """General web search using Tavily"""
        return await self.tavily.search(query, max_results=max_results)
    
    async def search_news(self, query: str, max_results: int = 5) -> ResearchResponse:
        """Search for news articles"""
        return await self.tavily.search_news(query, max_results=max_results)
    
    async def search_financial_news(self, query: str, max_results: int = 5) -> ResearchResponse:
        """Search financial news sources"""
        return await self.tavily.search_financial(query, max_results=max_results)
    
    async def research_ticker(self, ticker: str) -> Dict[str, ResearchResponse]:
        """
        Comprehensive research on a single ticker
        Combines multiple data sources
        """
        ticker = ticker.upper()
        
        # Run all research in parallel
        results = await asyncio.gather(
            self.tavily.search_financial(f"{ticker} stock news analysis", max_results=5),
            self.yahoo.get_stock_news(ticker, limit=5),
            self.finviz.get_stock_overview(ticker),
            return_exceptions=True
        )
        
        research = {}
        sources = ["tavily_news", "yahoo_news", "finviz_overview"]
        
        for source, result in zip(sources, results):
            if isinstance(result, Exception):
                logger.error(f"Research source {source} failed: {result}")
                research[source] = ResearchResponse(
                    query=f"{ticker} {source}",
                    results=[],
                    answer=f"Error: {str(result)}"
                )
            else:
                research[source] = result
        
        return research
    
    async def deep_dive(self, ticker: str) -> Dict[str, Any]:
        """
        Full deep dive research on a ticker
        Returns comprehensive data from all sources
        """
        ticker = ticker.upper()
        
        # Gather all research
        research = await asyncio.gather(
            self.tavily.search_financial(f"{ticker} stock news latest", max_results=5),
            self.tavily.search(f"{ticker} earnings report analysis", max_results=3),
            self.tavily.search(f"{ticker} analyst price target upgrade downgrade", max_results=3),
            self.sec.search_filings(ticker, limit=5),
            self.yahoo.get_stock_news(ticker),
            self.yahoo.get_analyst_ratings(ticker),
            self.finviz.get_stock_overview(ticker),
            return_exceptions=True
        )
        
        labels = [
            "news", "earnings", "analyst_actions", 
            "sec_filings", "yahoo_news", "analyst_ratings", "finviz_overview"
        ]
        
        deep_dive_data = {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": {}
        }
        
        for label, result in zip(labels, research):
            if isinstance(result, Exception):
                deep_dive_data["sources"][label] = {"error": str(result)}
            else:
                deep_dive_data["sources"][label] = result.to_dict()
        
        return deep_dive_data
    
    async def get_breaking_news(self, topics: Optional[List[str]] = None) -> ResearchResponse:
        """Get breaking market news"""
        if topics is None:
            topics = ["stock market", "earnings", "fed", "economy"]
        
        query = f"breaking financial news {' '.join(topics[:3])}"
        return await self.tavily.search_news(query, max_results=10)


# ===================== SINGLETON =====================

_web_research_service: Optional[WebResearchService] = None

def get_web_research_service() -> WebResearchService:
    """Get singleton instance of web research service"""
    global _web_research_service
    if _web_research_service is None:
        _web_research_service = WebResearchService()
    return _web_research_service
