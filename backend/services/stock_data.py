"""
Stock Data Service - Unified interface for stock data from multiple providers
Primary: Alpaca (free real-time), Finnhub (60 calls/min free tier)
Fallback: Yahoo Finance, then simulated data
"""
import os
import finnhub
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import random
import asyncio

class StockDataService:
    """Unified stock data service with multiple providers and caching"""
    
    def __init__(self):
        # Alpaca service (primary provider - free real-time)
        self._alpaca_service = None
        
        # Finnhub client (secondary provider - 60 calls/min)
        self.finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        self.finnhub_client = finnhub.Client(api_key=self.finnhub_key) if self.finnhub_key else None
        
        # Twelve Data (legacy fallback - 8 calls/min)
        self.twelvedata_key = os.environ.get("TWELVEDATA_API_KEY", "demo")
        
        # Cache settings
        self._quote_cache: Dict[str, tuple] = {}
        self._fundamentals_cache: Dict[str, tuple] = {}
        self._cache_ttl = 60  # seconds for quotes
        self._fundamentals_cache_ttl = 3600  # 1 hour for fundamentals
        
        # Rate limiting
        self._last_call_time = datetime.now(timezone.utc)
        self._call_count = 0
        self._rate_limit_window = 60  # seconds
        self._rate_limit_max = 55  # calls per window (leaving buffer)
    
    def set_alpaca_service(self, alpaca_service):
        """Set the Alpaca service for real-time data"""
        self._alpaca_service = alpaca_service
    
    def _check_cache(self, cache: Dict, key: str, ttl: int) -> Optional[Dict]:
        """Check if cached data is still valid"""
        if key in cache:
            data, cached_time = cache[key]
            if (datetime.now(timezone.utc) - cached_time).total_seconds() < ttl:
                return data
        return None
    
    def _set_cache(self, cache: Dict, key: str, data: Dict):
        """Store data in cache"""
        cache[key] = (data, datetime.now(timezone.utc))
    
    async def _can_make_call(self) -> bool:
        """Check rate limiting"""
        now = datetime.now(timezone.utc)
        if (now - self._last_call_time).total_seconds() > self._rate_limit_window:
            self._call_count = 0
            self._last_call_time = now
        
        if self._call_count >= self._rate_limit_max:
            return False
        
        self._call_count += 1
        return True
    
    async def get_quote(self, symbol: str) -> Dict:
        """Get real-time quote with provider fallback chain"""
        # Sanitize symbol - remove $ prefix and clean up
        symbol = symbol.replace("$", "").upper().strip()
        cache_key = f"quote_{symbol}"
        
        # Check cache first
        cached = self._check_cache(self._quote_cache, cache_key, self._cache_ttl)
        if cached:
            return cached
        
        # Try Alpaca first (best - free real-time)
        if self._alpaca_service:
            quote = await self._fetch_alpaca_quote(symbol)
            if quote:
                self._set_cache(self._quote_cache, cache_key, quote)
                return quote
        
        # Try Finnhub second (good rate limits)
        if self.finnhub_client and await self._can_make_call():
            quote = await self._fetch_finnhub_quote(symbol)
            if quote:
                self._set_cache(self._quote_cache, cache_key, quote)
                return quote
        
        # Fallback to Twelve Data
        quote = await self._fetch_twelvedata_quote(symbol)
        if quote:
            self._set_cache(self._quote_cache, cache_key, quote)
            return quote
        
        # Fallback to Yahoo Finance
        quote = await self._fetch_yahoo_quote(symbol)
        if quote:
            self._set_cache(self._quote_cache, cache_key, quote)
            return quote
        
        # Final fallback: simulated data
        return self._generate_simulated_quote(symbol)
    
    async def _fetch_alpaca_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Alpaca API"""
        try:
            quote = await self._alpaca_service.get_quote(symbol)
            if quote and quote.get('price', 0) > 0:
                # Convert Alpaca format to our standard format
                price = quote['price']
                bid = quote.get('bid', price)
                ask = quote.get('ask', price)
                
                return {
                    "symbol": symbol,
                    "price": round(price, 2),
                    "change": 0,  # Alpaca snapshot doesn't include change
                    "change_percent": 0,
                    "volume": quote.get('volume', 0),
                    "high": round(ask, 2),  # Use ask as proxy
                    "low": round(bid, 2),   # Use bid as proxy
                    "open": round(price, 2),
                    "prev_close": round(price, 2),
                    "bid": round(bid, 2),
                    "ask": round(ask, 2),
                    "timestamp": quote.get('timestamp', datetime.now(timezone.utc).isoformat()),
                    "source": "alpaca"
                }
        except Exception as e:
            print(f"Alpaca quote error for {symbol}: {e}")
        return None
    
    async def _fetch_finnhub_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Finnhub API"""
        try:
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, 
                self.finnhub_client.quote, 
                symbol
            )
            
            if data and data.get('c', 0) > 0:  # 'c' is current price
                price = data['c']
                prev_close = data.get('pc', price)
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0
                
                return {
                    "symbol": symbol,
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "volume": 0,  # Finnhub quote doesn't include volume
                    "high": round(data.get('h', price), 2),
                    "low": round(data.get('l', price), 2),
                    "open": round(data.get('o', price), 2),
                    "prev_close": round(prev_close, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "finnhub"
                }
        except Exception as e:
            print(f"Finnhub error for {symbol}: {e}")
        return None
    
    async def _fetch_twelvedata_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Twelve Data API"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.twelvedata.com/quote",
                    params={"symbol": symbol, "apikey": self.twelvedata_key},
                    timeout=10
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    if "code" in data and data["code"] != 200:
                        return None
                    
                    price = float(data.get("close", 0))
                    prev_close = float(data.get("previous_close", price))
                    change = float(data.get("change", 0))
                    change_pct = float(data.get("percent_change", 0))
                    
                    return {
                        "symbol": symbol,
                        "name": data.get("name", symbol),
                        "price": round(price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_pct, 2),
                        "volume": int(data.get("volume", 0)),
                        "high": round(float(data.get("high", price)), 2),
                        "low": round(float(data.get("low", price)), 2),
                        "open": round(float(data.get("open", price)), 2),
                        "prev_close": round(prev_close, 2),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "twelvedata"
                    }
        except Exception as e:
            print(f"Twelve Data error for {symbol}: {e}")
        return None
    
    async def _fetch_yahoo_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Yahoo Finance"""
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            
            # Sanitize and convert index symbols to yfinance format
            clean_symbol = symbol.replace("$", "").upper().strip()
            yf_symbol = clean_symbol
            if clean_symbol == "VIX":
                yf_symbol = "^VIX"
            elif clean_symbol in ["SPY", "QQQ", "DIA", "IWM"]:
                yf_symbol = clean_symbol  # ETFs stay the same
            
            def get_yahoo_data():
                ticker = yf.Ticker(yf_symbol)
                hist = ticker.history(period="2d")
                return hist
            
            hist = await loop.run_in_executor(None, get_yahoo_data)
            
            if not hist.empty and len(hist) >= 1:
                current = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) >= 2 else hist.iloc[-1]
                prev_close = prev['Close']
                change = current['Close'] - prev_close
                change_pct = (change / prev_close) * 100 if prev_close else 0
                
                return {
                    "symbol": clean_symbol,  # Use cleaned symbol
                    "price": round(current['Close'], 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "volume": int(current['Volume']),
                    "high": round(current['High'], 2),
                    "low": round(current['Low'], 2),
                    "open": round(current['Open'], 2),
                    "prev_close": round(prev_close, 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "yahoo"
                }
        except Exception as e:
            print(f"Yahoo Finance error for {symbol}: {e}")
        return None
    
    def _generate_simulated_quote(self, symbol: str) -> Dict:
        """Generate simulated quote data as final fallback"""
        base_prices = {
            "SPY": 475, "QQQ": 415, "DIA": 385, "IWM": 198, "VIX": 15,
            "AAPL": 186, "MSFT": 379, "GOOGL": 143, "AMZN": 178, "NVDA": 495,
            "TSLA": 249, "META": 358, "AMD": 146, "NFLX": 479, "CRM": 278,
        }
        
        base = base_prices.get(symbol, random.uniform(50, 300))
        variation = random.uniform(-0.03, 0.03)
        price = base * (1 + variation)
        change_pct = random.uniform(-3, 3)
        change = price * change_pct / 100
        
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "change": round(change, 2),
            "change_percent": round(change_pct, 2),
            "volume": random.randint(5000000, 50000000),
            "high": round(price * 1.01, 2),
            "low": round(price * 0.99, 2),
            "open": round(price - change/2, 2),
            "prev_close": round(price - change, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "simulated"
        }
    
    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Get quotes for multiple symbols efficiently"""
        results = {}
        
        # Batch fetch with concurrency limit
        semaphore = asyncio.Semaphore(10)
        
        async def fetch_one(symbol: str):
            async with semaphore:
                results[symbol] = await self.get_quote(symbol)
        
        await asyncio.gather(*[fetch_one(s) for s in symbols])
        return results
    
    async def get_company_profile(self, symbol: str) -> Optional[Dict]:
        """Get company profile from Finnhub"""
        symbol = symbol.upper()
        cache_key = f"profile_{symbol}"
        
        cached = self._check_cache(self._fundamentals_cache, cache_key, self._fundamentals_cache_ttl)
        if cached:
            return cached
        
        if self.finnhub_client and await self._can_make_call():
            try:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    self.finnhub_client.company_profile2,
                    symbol=symbol
                )
                
                if data:
                    profile = {
                        "symbol": symbol,
                        "name": data.get("name"),
                        "country": data.get("country"),
                        "currency": data.get("currency"),
                        "exchange": data.get("exchange"),
                        "industry": data.get("finnhubIndustry"),
                        "ipo_date": data.get("ipo"),
                        "logo": data.get("logo"),
                        "market_cap": data.get("marketCapitalization"),
                        "shares_outstanding": data.get("shareOutstanding"),
                        "weburl": data.get("weburl"),
                        "source": "finnhub"
                    }
                    self._set_cache(self._fundamentals_cache, cache_key, profile)
                    return profile
            except Exception as e:
                print(f"Finnhub profile error for {symbol}: {e}")
        
        return None
    
    async def get_earnings_calendar(self, from_date: str = None, to_date: str = None) -> List[Dict]:
        """Get earnings calendar from Finnhub"""
        if not self.finnhub_client:
            return []
        
        try:
            if not from_date:
                from_date = datetime.now().strftime("%Y-%m-%d")
            if not to_date:
                to_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: self.finnhub_client.earnings_calendar(_from=from_date, to=to_date, symbol="")
            )
            
            if data and "earningsCalendar" in data:
                return data["earningsCalendar"]
        except Exception as e:
            print(f"Finnhub earnings calendar error: {e}")
        
        return []
    
    async def get_service_status(self) -> Dict:
        """Get status of all data services - useful for health checks"""
        status = {
            "alpaca": {"available": False, "status": "not_configured"},
            "finnhub": {"available": False, "status": "not_configured"},
            "twelvedata": {"available": False, "status": "not_configured"},
            "yfinance": {"available": False, "status": "not_configured"},
            "cache": {
                "quote_cache_size": len(self._quote_cache),
                "fundamentals_cache_size": len(self._fundamentals_cache)
            }
        }
        
        # Check Alpaca
        if self._alpaca_service:
            try:
                alpaca_status = self._alpaca_service.get_status()
                status["alpaca"] = {
                    "available": alpaca_status.get("initialized", False),
                    "status": "connected" if alpaca_status.get("initialized") else "not_initialized",
                    "data_feed": alpaca_status.get("data_feed", "unknown")
                }
            except Exception as e:
                status["alpaca"] = {"available": False, "status": f"error: {str(e)}"}
        
        # Check Finnhub
        if self.finnhub_client and self.finnhub_key:
            try:
                # Quick test - get market status (lightweight call)
                market_status = self.finnhub_client.market_status(exchange='US')
                status["finnhub"] = {
                    "available": True,
                    "status": "connected",
                    "market_open": market_status.get("isOpen", False) if market_status else False
                }
            except Exception as e:
                status["finnhub"] = {"available": False, "status": f"error: {str(e)}"}
        
        # Check TwelveData (just check if key is configured)
        if self.twelvedata_key and self.twelvedata_key != "demo":
            status["twelvedata"] = {"available": True, "status": "configured"}
        elif self.twelvedata_key == "demo":
            status["twelvedata"] = {"available": True, "status": "demo_mode"}
        
        # yfinance is always available (no API key needed)
        status["yfinance"] = {"available": True, "status": "available"}
        
        return status
    
    async def health_check(self) -> Dict:
        """Perform health check on all services - tests actual connectivity"""
        results = {
            "healthy": True,
            "services": {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Test Alpaca with a real quote request
        try:
            if self._alpaca_service:
                quote = await self._alpaca_service.get_quote("AAPL")
                results["services"]["alpaca"] = {
                    "healthy": quote is not None and quote.get("price", 0) > 0,
                    "latency_ms": None  # Could add timing
                }
            else:
                results["services"]["alpaca"] = {"healthy": False, "reason": "not_configured"}
        except Exception as e:
            results["services"]["alpaca"] = {"healthy": False, "reason": str(e)}
            results["healthy"] = False
        
        # Test Finnhub
        try:
            if self.finnhub_client:
                quote = self.finnhub_client.quote("AAPL")
                results["services"]["finnhub"] = {
                    "healthy": quote is not None and quote.get("c", 0) > 0
                }
            else:
                results["services"]["finnhub"] = {"healthy": False, "reason": "not_configured"}
        except Exception as e:
            results["services"]["finnhub"] = {"healthy": False, "reason": str(e)}
        
        # yfinance test
        try:
            import yfinance as yf
            ticker = yf.Ticker("AAPL")
            info = ticker.fast_info
            results["services"]["yfinance"] = {
                "healthy": hasattr(info, 'last_price') and info.last_price > 0
            }
        except Exception as e:
            results["services"]["yfinance"] = {"healthy": False, "reason": str(e)}
        
        return results


# Singleton instance
_stock_service: Optional[StockDataService] = None

def get_stock_service() -> StockDataService:
    """Get or create the stock data service singleton"""
    global _stock_service
    if _stock_service is None:
        _stock_service = StockDataService()
    return _stock_service
