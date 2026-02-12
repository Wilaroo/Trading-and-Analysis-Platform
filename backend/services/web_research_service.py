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
            search_depth="advanced",
            data_type="news"  # 3 min cache
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
            search_depth="advanced",
            data_type="news"  # 3 min cache
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
    
    # ===================== AGENT SKILLS =====================
    # Specialized tools that combine Tavily with free data sources
    # These are designed to minimize credit usage while maximizing value
    
    async def get_company_info(self, ticker: str) -> Dict[str, Any]:
        """
        AGENT SKILL: Get comprehensive company information
        
        Combines multiple FREE sources first, then uses Tavily only if needed.
        This minimizes credit usage while providing rich context.
        
        Returns:
            Company profile, fundamentals, recent news, and analyst sentiment
        """
        ticker = ticker.upper()
        start_time = time.time()
        
        # Check cache first (1 hour TTL for company info)
        cached = _global_cache.get("company_info", ticker)
        if cached:
            logger.info(f"🎯 Agent Skill cache HIT: get_company_info({ticker})")
            return cached
        
        result = {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profile": {},
            "fundamentals": {},
            "recent_news": [],
            "analyst_sentiment": {},
            "sources_used": [],
            "tavily_credits_used": 0
        }
        
        try:
            # Step 1: Get fundamentals from Finnhub (FREE)
            try:
                from services.fundamental_data_service import get_fundamental_data_service
                fund_service = get_fundamental_data_service()
                fundamentals = await fund_service.get_fundamentals(ticker)
                
                if fundamentals and fundamentals.get("available"):
                    result["fundamentals"] = fundamentals.get("data", {})
                    result["profile"] = {
                        "name": fundamentals.get("data", {}).get("name"),
                        "industry": fundamentals.get("data", {}).get("industry"),
                        "sector": fundamentals.get("data", {}).get("sector"),
                        "market_cap": fundamentals.get("data", {}).get("market_cap")
                    }
                    result["sources_used"].append("finnhub_fundamentals")
            except Exception as e:
                logger.warning(f"Finnhub fundamentals failed: {e}")
            
            # Step 2: Get news from Finnhub (FREE)
            try:
                from services.news_service import get_news_service
                news_service = get_news_service()
                news = await news_service.get_stock_news(ticker, limit=5)
                
                if news:
                    result["recent_news"] = [
                        {"headline": n.get("headline"), "source": n.get("source"), "datetime": n.get("datetime")}
                        for n in news[:5]
                    ]
                    result["sources_used"].append("finnhub_news")
            except Exception as e:
                logger.warning(f"Finnhub news failed: {e}")
            
            # Step 3: Get Finviz overview (FREE scraper)
            try:
                finviz_data = await self.finviz.get_stock_overview(ticker)
                if finviz_data and finviz_data.results:
                    for r in finviz_data.results:
                        if "Key Metrics" in r.title:
                            # Parse the metrics string
                            metrics = {}
                            for pair in r.content.split(" | "):
                                if ":" in pair:
                                    k, v = pair.split(":", 1)
                                    metrics[k.strip()] = v.strip()
                            result["fundamentals"].update(metrics)
                    result["sources_used"].append("finviz")
            except Exception as e:
                logger.warning(f"Finviz scrape failed: {e}")
            
            # Step 4: Only use Tavily if we're missing critical data
            needs_tavily = (
                not result["profile"].get("name") or 
                not result["recent_news"] or
                len(result["fundamentals"]) < 3
            )
            
            if needs_tavily:
                # Single targeted search to fill gaps
                tavily_result = await self.tavily.search(
                    f"{ticker} company profile business overview",
                    max_results=3,
                    search_depth="basic",  # Use basic to save credits
                    data_type="company_info"
                )
                result["tavily_credits_used"] = 1
                
                if tavily_result.answer:
                    result["profile"]["description"] = tavily_result.answer[:500]
                    result["sources_used"].append("tavily")
            
            # Step 5: Get analyst sentiment from Yahoo (FREE scraper)
            try:
                analyst_data = await self.yahoo.get_analyst_ratings(ticker)
                if analyst_data and analyst_data.results:
                    result["analyst_sentiment"]["summary"] = analyst_data.results[0].content[:300] if analyst_data.results[0].content else "N/A"
                    result["sources_used"].append("yahoo_analyst")
            except Exception as e:
                logger.warning(f"Yahoo analyst scrape failed: {e}")
            
        except Exception as e:
            logger.error(f"get_company_info failed for {ticker}: {e}")
            result["error"] = str(e)
        
        result["response_time_ms"] = (time.time() - start_time) * 1000
        
        # Cache the result (1 hour TTL)
        _global_cache.set("company_info", result, ticker)
        
        logger.info(f"✅ Agent Skill: get_company_info({ticker}) - {len(result['sources_used'])} sources, {result['tavily_credits_used']} Tavily credits")
        return result
    
    async def get_stock_analysis(self, ticker: str, analysis_type: str = "comprehensive") -> Dict[str, Any]:
        """
        AGENT SKILL: Get stock analysis and trading context
        
        Analysis types:
        - "quick": Just price context and basic news (0 credits)
        - "news": News-focused analysis (1 credit)
        - "comprehensive": Full analysis with all sources (1-2 credits)
        
        Returns:
            Price action context, news sentiment, technical signals, and trading recommendations
        """
        ticker = ticker.upper()
        start_time = time.time()
        
        # Check cache (10 min TTL for analysis)
        cache_key = f"{ticker}:{analysis_type}"
        cached = _global_cache.get("stock_analysis", cache_key)
        if cached:
            logger.info(f"🎯 Agent Skill cache HIT: get_stock_analysis({ticker}, {analysis_type})")
            return cached
        
        result = {
            "ticker": ticker,
            "analysis_type": analysis_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price_context": {},
            "news_sentiment": {},
            "technical_signals": {},
            "trading_context": {},
            "sources_used": [],
            "tavily_credits_used": 0
        }
        
        try:
            # Step 1: Get real-time technicals (FREE - from our service)
            try:
                from services.realtime_technical_service import get_technical_service
                tech_service = get_technical_service()
                snapshot = await tech_service.get_technical_snapshot(ticker)
                
                if snapshot:
                    result["price_context"] = {
                        "current_price": snapshot.get("price"),
                        "change_percent": snapshot.get("change_percent"),
                        "volume": snapshot.get("volume"),
                        "rvol": snapshot.get("rvol"),
                        "vwap": snapshot.get("vwap"),
                        "day_high": snapshot.get("high"),
                        "day_low": snapshot.get("low")
                    }
                    result["technical_signals"] = {
                        "rsi": snapshot.get("rsi"),
                        "macd_signal": snapshot.get("macd_signal"),
                        "above_vwap": snapshot.get("above_vwap"),
                        "distance_from_hod": snapshot.get("distance_from_hod")
                    }
                    result["sources_used"].append("realtime_technicals")
            except Exception as e:
                logger.warning(f"Technical service failed: {e}")
            
            # Step 2: Get scanner context (FREE - from our enhanced scanner)
            try:
                from services.enhanced_scanner import get_enhanced_scanner
                scanner = get_enhanced_scanner()
                alerts = scanner.get_alerts_for_symbol(ticker)
                
                if alerts:
                    result["trading_context"]["active_setups"] = [
                        {"setup": a.setup_type, "direction": a.direction, "priority": a.priority.value}
                        for a in alerts[:3]
                    ]
                    result["sources_used"].append("scanner")
            except Exception as e:
                logger.debug(f"Scanner context not available: {e}")
            
            # Step 3: Get news based on analysis type
            if analysis_type in ["news", "comprehensive"]:
                # Use Tavily for fresh news (1 credit)
                news_result = await self.tavily.search_financial(
                    f"{ticker} stock news today latest",
                    max_results=5,
                    search_depth="basic" if analysis_type == "news" else "advanced"
                )
                result["tavily_credits_used"] += 1 if analysis_type == "news" else 2
                
                if news_result.answer:
                    result["news_sentiment"]["summary"] = news_result.answer
                
                result["news_sentiment"]["headlines"] = [
                    {"title": r.title, "source": r.source}
                    for r in news_result.results[:5]
                ]
                result["sources_used"].append("tavily_news")
            
            # Step 4: For comprehensive, add analyst context
            if analysis_type == "comprehensive":
                try:
                    analyst_data = await self.yahoo.get_analyst_ratings(ticker)
                    if analyst_data and analyst_data.results:
                        result["trading_context"]["analyst_view"] = analyst_data.results[0].content[:200]
                        result["sources_used"].append("yahoo_analyst")
                except Exception as e:
                    logger.debug(f"Analyst data not available: {e}")
        
        except Exception as e:
            logger.error(f"get_stock_analysis failed for {ticker}: {e}")
            result["error"] = str(e)
        
        result["response_time_ms"] = (time.time() - start_time) * 1000
        
        # Cache the result
        _global_cache.set("stock_analysis", result, cache_key)
        
        logger.info(f"✅ Agent Skill: get_stock_analysis({ticker}, {analysis_type}) - {len(result['sources_used'])} sources, {result['tavily_credits_used']} credits")
        return result
    
    async def get_market_context(self) -> Dict[str, Any]:
        """
        AGENT SKILL: Get current market context and sentiment
        
        This is designed to be called once at the start of a trading session.
        Uses aggressive caching (15 min) to minimize credit usage.
        
        Returns:
            Market indices, sector performance, major news themes, and trading environment
        """
        start_time = time.time()
        
        # Check cache (15 min TTL)
        cached = _global_cache.get("deep_dive", "market_context")
        if cached:
            logger.info(f"🎯 Agent Skill cache HIT: get_market_context()")
            return cached
        
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "indices": {},
            "sector_leaders": [],
            "news_themes": [],
            "market_regime": "unknown",
            "trading_environment": {},
            "sources_used": [],
            "tavily_credits_used": 0
        }
        
        try:
            # Step 1: Get index data from Alpaca (FREE)
            try:
                from services.alpaca_service import get_alpaca_service
                alpaca = get_alpaca_service()
                
                for symbol in ["SPY", "QQQ", "IWM", "DIA"]:
                    quote = await alpaca.get_quote(symbol)
                    if quote:
                        result["indices"][symbol] = {
                            "price": quote.get("price"),
                            "change_percent": quote.get("change_percent")
                        }
                result["sources_used"].append("alpaca_indices")
            except Exception as e:
                logger.warning(f"Alpaca indices failed: {e}")
            
            # Step 2: Get market news summary (1 credit)
            try:
                news_result = await self.tavily.search(
                    "stock market today major news Fed earnings economy",
                    max_results=5,
                    search_depth="basic",
                    data_type="news"
                )
                result["tavily_credits_used"] = 1
                
                if news_result.answer:
                    result["news_themes"].append(news_result.answer[:300])
                
                for r in news_result.results[:3]:
                    result["news_themes"].append(r.title)
                
                result["sources_used"].append("tavily_market_news")
            except Exception as e:
                logger.warning(f"Market news search failed: {e}")
            
            # Step 3: Determine market regime from index data
            spy_change = result["indices"].get("SPY", {}).get("change_percent", 0)
            qqq_change = result["indices"].get("QQQ", {}).get("change_percent", 0)
            
            if spy_change > 1 and qqq_change > 1:
                result["market_regime"] = "strong_uptrend"
            elif spy_change < -1 and qqq_change < -1:
                result["market_regime"] = "strong_downtrend"
            elif abs(spy_change) < 0.3 and abs(qqq_change) < 0.3:
                result["market_regime"] = "range_bound"
            else:
                result["market_regime"] = "mixed"
            
            result["trading_environment"] = {
                "bias": "bullish" if spy_change > 0.5 else "bearish" if spy_change < -0.5 else "neutral",
                "volatility": "high" if abs(spy_change) > 1.5 else "normal",
                "recommendation": self._get_regime_recommendation(result["market_regime"])
            }
            
        except Exception as e:
            logger.error(f"get_market_context failed: {e}")
            result["error"] = str(e)
        
        result["response_time_ms"] = (time.time() - start_time) * 1000
        
        # Cache for 15 minutes
        _global_cache.set("deep_dive", result, "market_context")
        
        logger.info(f"✅ Agent Skill: get_market_context() - {result['market_regime']}, {result['tavily_credits_used']} credits")
        return result
    
    def _get_regime_recommendation(self, regime: str) -> str:
        """Get trading recommendation based on market regime"""
        recommendations = {
            "strong_uptrend": "Favor long setups (Spencer, HitchHiker, ORB). Avoid shorts.",
            "strong_downtrend": "Favor short setups (Tidal Wave, Off Sides). Avoid longs.",
            "range_bound": "Reduce size 50%. Focus on mean reversion (Rubber Band, VWAP fades).",
            "mixed": "Be selective. Wait for clearer direction or trade both sides carefully.",
            "unknown": "Gather more data before committing to directional trades."
        }
        return recommendations.get(regime, recommendations["unknown"])
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics for monitoring"""
        return {
            "cache_stats": _global_cache.get_stats(),
            "tavily_credits_used_session": self.tavily.get_credit_usage()
        }


# ===================== SINGLETON =====================

_web_research_service: Optional[WebResearchService] = None

def get_web_research_service() -> WebResearchService:
    """Get singleton instance of web research service"""
    global _web_research_service
    if _web_research_service is None:
        _web_research_service = WebResearchService()
    return _web_research_service
