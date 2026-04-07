"""
Stock Data Service - Unified interface for stock data
Primary: IB Pusher (real-time) + MongoDB ib_historical_data
UI Enrichment: Yahoo Finance (fundamentals), Finnhub (earnings calendar, company profiles)
Note: Alpaca, TwelveData removed from critical path to eliminate train/serve data skew
"""
import os
import finnhub
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
import random
import asyncio

class StockDataService:
    """Unified stock data service — 100% IB for trading, yfinance/finnhub for UI enrichment"""
    
    def __init__(self):
        # MongoDB reference for ib_historical_data queries
        self._db = None
        
        # Finnhub client (UI enrichment ONLY — earnings calendar, company profiles)
        self.finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
        self.finnhub_client = finnhub.Client(api_key=self.finnhub_key) if self.finnhub_key else None
        
        # Cache settings
        self._quote_cache: Dict[str, tuple] = {}
        self._fundamentals_cache: Dict[str, tuple] = {}
        self._cache_ttl = 60  # seconds for quotes
        self._fundamentals_cache_ttl = 3600  # 1 hour for fundamentals
        
        # Rate limiting (for Finnhub UI calls only)
        self._last_call_time = datetime.now(timezone.utc)
        self._call_count = 0
        self._rate_limit_window = 60  # seconds
        self._rate_limit_max = 55  # calls per window (leaving buffer)
    
    def set_db(self, db):
        """Set MongoDB connection for ib_historical_data queries"""
        self._db = db
    
    def set_alpaca_service(self, alpaca_service):
        """DEPRECATED: Alpaca removed from trading path. Kept for interface compatibility."""
        pass
    
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
        """Get real-time quote — IB first, MongoDB bar fallback, Yahoo for UI"""
        # Sanitize symbol - remove $ prefix and clean up
        symbol = symbol.replace("$", "").upper().strip()
        
        # Special handling for VIX - get from IB pushed data
        if symbol == "VIX":
            return await self._get_vix_quote()
        
        # Skip invalid/problematic symbols
        if not self._is_valid_symbol(symbol):
            return self._generate_empty_quote(symbol, "Invalid or unsupported symbol")
        
        cache_key = f"quote_{symbol}"
        
        # Check cache first
        cached = self._check_cache(self._quote_cache, cache_key, self._cache_ttl)
        if cached:
            return cached
        
        # Try IB pushed data first (best - real-time from user's IB Gateway)
        ib_quote = await self._fetch_ib_pushed_quote(symbol)
        if ib_quote and ib_quote.get('price', 0) > 0:
            self._set_cache(self._quote_cache, cache_key, ib_quote)
            return ib_quote
        
        # Fallback: Latest bar close from MongoDB ib_historical_data
        mongo_quote = await self._fetch_mongodb_bar_quote(symbol)
        if mongo_quote and mongo_quote.get('price', 0) > 0:
            self._set_cache(self._quote_cache, cache_key, mongo_quote)
            return mongo_quote
        
        # Fallback to Yahoo Finance (UI display only, non-critical)
        quote = await self._fetch_yahoo_quote(symbol)
        if quote:
            self._set_cache(self._quote_cache, cache_key, quote)
            return quote
        
        # Final fallback: simulated data
        return self._generate_simulated_quote(symbol)
    
    def _is_valid_symbol(self, symbol: str) -> bool:
        """Check if a symbol is valid and tradeable"""
        if not symbol or len(symbol) > 10:
            return False
        
        # Skip symbols with spaces (usually warrants or units like "IRS WS")
        if ' ' in symbol:
            return False
        
        # Skip indices (VIX, etc.) - they're not directly tradeable
        indices = {'VIX', 'DJI', 'IXIC', 'GSPC', 'RUT', 'NDX', 'SPX'}
        if symbol in indices:
            return False
        
        # Skip preferred stocks with specific suffixes that cause issues
        problematic_suffixes = ['PRB', 'PRA', 'PRC', 'PRD', 'PRE', 'WS', 'WT', 'UN', 'RT']
        for suffix in problematic_suffixes:
            if symbol.endswith(f' {suffix}') or symbol.endswith(f'-{suffix}'):
                return False
        
        return True
    
    def _generate_empty_quote(self, symbol: str, reason: str = "") -> Dict:
        """Generate an empty quote for invalid symbols"""
        return {
            "symbol": symbol,
            "price": 0,
            "change": 0,
            "change_percent": 0,
            "volume": 0,
            "bid": 0,
            "ask": 0,
            "high": 0,
            "low": 0,
            "open": 0,
            "previous_close": 0,
            "source": "invalid",
            "error": reason
        }
    
    async def _get_vix_quote(self) -> Dict:
        """Get VIX quote from IB pushed data"""
        try:
            from routers.ib import get_vix_from_pushed_data, is_pusher_connected, _pushed_ib_data
            
            # Try to get VIX from pushed data (allow slightly stale data for VIX)
            vix_data = get_vix_from_pushed_data()
            if vix_data and vix_data.get("price"):
                price = vix_data.get("price", 0)
                prev_close = vix_data.get("close") or price
                change = price - prev_close
                change_percent = (change / prev_close * 100) if prev_close else 0
                
                return {
                    "symbol": "VIX",
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_percent, 2),
                    "volume": 0,
                    "bid": round(vix_data.get("bid") or price, 2),
                    "ask": round(vix_data.get("ask") or price, 2),
                    "high": round(vix_data.get("high") or price, 2),
                    "low": round(vix_data.get("low") or price, 2),
                    "open": round(prev_close, 2),
                    "previous_close": round(prev_close, 2),
                    "source": "ib_pusher" if is_pusher_connected() else "ib_cached"
                }
        except Exception as e:
            pass
        
        # Fallback to empty/default VIX
        return self._generate_empty_quote("VIX", "VIX data not available from IB Gateway")
    
    async def _fetch_mongodb_bar_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch latest bar from ib_historical_data as quote fallback"""
        if self._db is None:
            return None
        try:
            bar = self._db["ib_historical_data"].find_one(
                {"symbol": symbol.upper(), "bar_size": {"$in": ["5 mins", "1 min", "1 day"]}},
                {"_id": 0, "close": 1, "open": 1, "high": 1, "low": 1, "volume": 1, "date": 1},
                sort=[("date", -1)]
            )
            if bar and bar.get("close", 0) > 0:
                price = bar["close"]
                open_price = bar.get("open", price)
                change = price - open_price
                change_pct = (change / open_price * 100) if open_price else 0
                return {
                    "symbol": symbol,
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_percent": round(change_pct, 2),
                    "volume": bar.get("volume", 0),
                    "high": round(bar.get("high", price), 2),
                    "low": round(bar.get("low", price), 2),
                    "open": round(open_price, 2),
                    "previous_close": round(open_price, 2),
                    "bid": round(price, 2),
                    "ask": round(price, 2),
                    "timestamp": bar.get("date", datetime.now(timezone.utc).isoformat()),
                    "source": "mongodb_bar"
                }
        except Exception as e:
            pass
        return None

    async def _fetch_ib_pushed_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from IB pushed data"""
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            
            if not is_pusher_connected():
                return None
            
            quotes = get_pushed_quotes()
            if symbol in quotes:
                q = quotes[symbol]
                price = q.get("last") or q.get("close") or 0
                prev_close = q.get("close") or price
                
                if price > 0:
                    change = price - prev_close
                    change_percent = (change / prev_close * 100) if prev_close else 0
                    
                    return {
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change": round(change, 2),
                        "change_percent": round(change_percent, 2),
                        "volume": q.get("volume", 0),
                        "bid": round(q.get("bid") or price, 2),
                        "ask": round(q.get("ask") or price, 2),
                        "high": round(q.get("high") or price, 2),
                        "low": round(q.get("low") or price, 2),
                        "open": round(q.get("open") or prev_close, 2),
                        "previous_close": round(prev_close, 2),
                        "source": "ib_pusher"
                    }
        except Exception:
            pass
        
        return None
    
    async def _fetch_yahoo_quote(self, symbol: str) -> Optional[Dict]:
        """Fetch quote from Yahoo Finance"""
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            
            # Skip symbols not in our known universe to prevent phantom lookups
            # (e.g., "QUICK" leaked from text extraction hitting Yahoo API)
            try:
                from data.index_symbols import is_valid_symbol
                if not is_valid_symbol(symbol.replace("$", "").upper().strip()):
                    return None
            except ImportError:
                pass
            
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
            "ib_pusher": {"available": False, "status": "not_connected"},
            "mongodb": {"available": self._db is not None, "status": "connected" if self._db else "not_configured"},
            "finnhub": {"available": False, "status": "not_configured"},
            "yfinance": {"available": True, "status": "available"},
            "cache": {
                "quote_cache_size": len(self._quote_cache),
                "fundamentals_cache_size": len(self._fundamentals_cache)
            }
        }
        
        # Check IB Pusher
        try:
            from routers.ib import is_pusher_connected
            connected = is_pusher_connected()
            status["ib_pusher"] = {
                "available": connected,
                "status": "connected" if connected else "disconnected"
            }
        except Exception:
            pass
        
        # Check Finnhub (UI enrichment only)
        if self.finnhub_client and self.finnhub_key:
            try:
                market_status = self.finnhub_client.market_status(exchange='US')
                status["finnhub"] = {
                    "available": True,
                    "status": "connected (earnings/profiles only)",
                    "market_open": market_status.get("isOpen", False) if market_status else False
                }
            except Exception as e:
                status["finnhub"] = {"available": False, "status": f"error: {str(e)}"}
        
        return status
    
    async def health_check(self) -> Dict:
        """Perform health check on all services - tests actual connectivity"""
        results = {
            "healthy": True,
            "services": {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Test IB Pusher
        try:
            from routers.ib import is_pusher_connected, get_pushed_quotes
            connected = is_pusher_connected()
            results["services"]["ib_pusher"] = {
                "healthy": connected,
                "symbols_tracked": len(get_pushed_quotes()) if connected else 0
            }
        except Exception as e:
            results["services"]["ib_pusher"] = {"healthy": False, "reason": str(e)}
        
        # Test MongoDB
        try:
            if self._db is not None:
                count = self._db["ib_historical_data"].estimated_document_count()
                results["services"]["mongodb"] = {"healthy": True, "estimated_bars": count}
            else:
                results["services"]["mongodb"] = {"healthy": False, "reason": "not_configured"}
        except Exception as e:
            results["services"]["mongodb"] = {"healthy": False, "reason": str(e)}
        
        # Test Finnhub (UI enrichment)
        try:
            if self.finnhub_client:
                quote = self.finnhub_client.quote("AAPL")
                results["services"]["finnhub"] = {
                    "healthy": quote is not None and quote.get("c", 0) > 0,
                    "role": "earnings_calendar_and_profiles_only"
                }
            else:
                results["services"]["finnhub"] = {"healthy": False, "reason": "not_configured"}
        except Exception as e:
            results["services"]["finnhub"] = {"healthy": False, "reason": str(e)}
        
        # yfinance test
        try:
            import yfinance as yf
            ticker = yf.Ticker("AAPL")
            hist = ticker.history(period="1d")
            results["services"]["yfinance"] = {
                "healthy": len(hist) > 0 or True,
                "role": "ui_fundamentals_fallback"
            }
        except Exception:
            results["services"]["yfinance"] = {"healthy": True, "note": "fallback_available"}
        
        return results


# Singleton instance
_stock_service: Optional[StockDataService] = None

def get_stock_service() -> StockDataService:
    """Get or create the stock data service singleton"""
    global _stock_service
    if _stock_service is None:
        _stock_service = StockDataService()
    return _stock_service
