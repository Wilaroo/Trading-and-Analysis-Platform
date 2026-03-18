"""
BriefMeAgent - Generates personalized market briefings
=====================================================

ENHANCED VERSION (March 2026):
- Real news/catalysts from IB Gateway and Finnhub
- Sector rotation analysis with leading/lagging sectors
- More actionable intelligence with specific trade ideas
- Earnings calendar integration for watchlist stocks
- Market regime-based strategy recommendations

Aggregates data from multiple services to create a personalized
market report tailored to the user's trading style and current conditions.

Features:
- Quick summary (2-3 sentences)
- Detailed report with sections
- Pre-market gappers & overnight movers
- Key market levels (SPY, QQQ, VIX)
- Personalized insights based on learning data
- Top opportunities ranked by relevance
- Real news headlines and catalysts
- Sector rotation heatmap
- Earnings warnings for watchlist stocks
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import asyncio
import aiohttp
import os
import requests

logger = logging.getLogger(__name__)

# Finnhub API key
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")


class BriefMeAgent:
    """Agent that generates personalized market briefings with real news and sector analysis."""
    
    def __init__(self, llm_provider=None):
        self.name = "BriefMeAgent"
        self.llm_provider = llm_provider
        
        # Services will be injected
        self.market_intel_service = None
        self.context_service = None
        self.learning_provider = None
        self.trading_bot = None
        self.scanner_service = None
        self.regime_performance_service = None
        self.alpaca_service = None
        self.ib_pushed_data = None  # For real-time IB data
        self.news_service = None  # For real news
        self._db = None  # MongoDB for historical data
    
    def set_db(self, db):
        """Set MongoDB connection for historical data access"""
        self._db = db
    
    def inject_services(
        self,
        market_intel_service=None,
        context_service=None,
        learning_provider=None,
        trading_bot=None,
        scanner_service=None,
        regime_performance_service=None,
        alpaca_service=None,
        ib_pushed_data=None,
        news_service=None
    ):
        """Inject required services."""
        self.market_intel_service = market_intel_service
        self.context_service = context_service
        self.learning_provider = learning_provider
        self.trading_bot = trading_bot
        self.scanner_service = scanner_service
        self.regime_performance_service = regime_performance_service
        self.alpaca_service = alpaca_service
        self.ib_pushed_data = ib_pushed_data
        self.news_service = news_service
    
    async def generate_brief(self, detail_level: str = "quick") -> Dict[str, Any]:
        """
        Generate a market briefing using MarketIntelService for rich data.
        
        Args:
            detail_level: "quick" for 2-3 sentences, "detailed" for full report
            
        Returns:
            Dictionary with briefing data and formatted text
        """
        try:
            # Try to use MarketIntelService for rich pre-market data first
            rich_intel = None
            if self.market_intel_service:
                try:
                    # Get or generate pre-market report
                    result = await self.market_intel_service.generate_report("premarket", force=False)
                    if result and result.get("success"):
                        rich_intel = result.get("content", {})
                        logger.info("Using MarketIntelService for rich pre-market data")
                except Exception as e:
                    logger.warning(f"MarketIntelService failed, using fallback: {e}")
            
            # Gather all data in parallel
            data = await self._gather_all_data()
            
            # Merge rich intel if available
            if rich_intel:
                data["rich_intel"] = rich_intel
            
            # Build structured brief
            brief = self._build_structured_brief(data)
            
            # Generate natural language summary
            if detail_level == "quick":
                summary = await self._generate_quick_summary(brief)
            else:
                summary = await self._generate_detailed_summary(brief, data.get("rich_intel"))
            
            return {
                "success": True,
                "detail_level": detail_level,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data": brief,
                "summary": summary
            }
            
        except Exception as e:
            logger.error(f"Error generating brief: {e}")
            return {
                "success": False,
                "error": str(e),
                "summary": self._generate_fallback_summary()
            }
    
    async def _gather_all_data(self) -> Dict[str, Any]:
        """Gather data from all services in parallel - ENHANCED with news, sectors, earnings."""
        data = {
            "market": {},
            "session": {},
            "bot": {},
            "learning": {},
            "opportunities": [],
            "regime_performance": {},
            "premarket": {},
            "key_levels": {},
            "gappers": {"up": [], "down": []},
            "market_movers": {"gainers": [], "losers": []},
            "index_status": {},
            # NEW: Enhanced data sections
            "news": {
                "market_headlines": [],
                "ticker_news": {},
                "themes": [],
                "sentiment": "neutral"
            },
            "sectors": {
                "leaders": [],
                "laggards": [],
                "rotation_signal": None
            },
            "earnings": {
                "upcoming": [],
                "recent_reports": []
            },
            "catalysts": []
        }
        
        # Core data fetches (critical)
        core_tasks = []
        if self.context_service:
            core_tasks.append(self._fetch_regime_data(data))
            core_tasks.append(self._fetch_session_data(data))
        if self.trading_bot:
            core_tasks.append(self._fetch_bot_status(data))
        
        # Run core tasks first (with 10s timeout)
        if core_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*core_tasks, return_exceptions=True), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Core data fetch timed out after 10s")
        
        # Enhanced data fetches (best effort, with short timeouts)
        enhanced_tasks = []
        
        # Learning insights
        if self.learning_provider:
            enhanced_tasks.append(self._safe_fetch(self._fetch_learning_data(data), 5.0, "learning"))
        
        # Regime performance
        if self.regime_performance_service:
            enhanced_tasks.append(self._safe_fetch(self._fetch_regime_performance(data), 5.0, "regime_perf"))
        
        # Scanner opportunities
        if self.scanner_service:
            enhanced_tasks.append(self._safe_fetch(self._fetch_scanner_alerts(data), 5.0, "scanner"))
        
        # Pre-market/gapper data from Alpaca
        if self.alpaca_service:
            enhanced_tasks.append(self._safe_fetch(self._fetch_premarket_data(data), 8.0, "premarket"))
        
        # Real-time IB data - important for market context
        enhanced_tasks.append(self._safe_fetch(self._fetch_ib_realtime_data(data), 8.0, "ib_data"))
        
        # NEW: Enhanced data sources (with individual timeouts)
        enhanced_tasks.append(self._safe_fetch(self._fetch_news_and_catalysts(data), 10.0, "news"))
        enhanced_tasks.append(self._safe_fetch(self._fetch_sector_rotation(data), 8.0, "sectors"))
        enhanced_tasks.append(self._safe_fetch(self._fetch_earnings_calendar(data), 8.0, "earnings"))
        
        # Run all enhanced tasks in parallel with overall 15s timeout
        if enhanced_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*enhanced_tasks, return_exceptions=True), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("Enhanced data fetch timed out after 15s")
        
        return data
    
    async def _safe_fetch(self, coro, timeout: float, name: str):
        """Wrapper to safely run a coroutine with timeout."""
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Fetch {name} timed out after {timeout}s")
        except Exception as e:
            logger.warning(f"Fetch {name} failed: {e}")
    
    async def _fetch_regime_data(self, data: Dict):
        """Fetch market regime data."""
        try:
            regime_data = await asyncio.to_thread(
                self.context_service.get_regime_context
            )
            data["market"] = regime_data or {}
        except Exception as e:
            logger.warning(f"Failed to get regime context: {e}")
    
    async def _fetch_session_data(self, data: Dict):
        """Fetch session data."""
        try:
            session_data = await asyncio.to_thread(
                self.context_service.get_session_context
            )
            data["session"] = session_data or {}
        except Exception as e:
            logger.warning(f"Failed to get session context: {e}")
    
    async def _fetch_bot_status(self, data: Dict):
        """Fetch bot status."""
        try:
            bot_status = self.trading_bot.get_status()
            data["bot"] = {
                "state": bot_status.get("mode", "unknown"),
                "running": bot_status.get("running", False),
                "today_pnl": bot_status.get("daily_stats", {}).get("net_pnl", 0),
                "trades_today": bot_status.get("daily_stats", {}).get("total_trades", 0),
                "win_rate": bot_status.get("daily_stats", {}).get("win_rate", 0),
                "open_positions": self.trading_bot.get_open_trades()[:5]
            }
        except Exception as e:
            logger.warning(f"Failed to get bot status: {e}")
    
    async def _fetch_learning_data(self, data: Dict):
        """Fetch learning insights."""
        try:
            learning_data = await asyncio.to_thread(
                self.learning_provider.build_full_learning_context
            )
            data["learning"] = learning_data or {}
        except Exception as e:
            logger.warning(f"Failed to get learning context: {e}")
    
    async def _fetch_regime_performance(self, data: Dict):
        """Fetch regime-specific performance."""
        try:
            current_regime = data.get("market", {}).get("regime", "HOLD")
            perf_data = await asyncio.to_thread(
                self.regime_performance_service.get_performance_by_regime,
                current_regime
            )
            data["regime_performance"] = perf_data or {}
        except Exception as e:
            logger.warning(f"Failed to get regime performance: {e}")
    
    async def _fetch_scanner_alerts(self, data: Dict):
        """Fetch scanner alerts."""
        try:
            alerts = await asyncio.to_thread(
                self.scanner_service.get_live_alerts
            )
            # Convert LiveAlert objects to dicts
            alert_dicts = []
            for a in alerts:
                try:
                    alert_dict = {
                        "symbol": getattr(a, 'symbol', ''),
                        "setup_type": getattr(a, 'setup_type', ''),
                        "tqs_score": getattr(a, 'tqs_score', 0),
                        "direction": getattr(a, 'direction', 'long'),
                        "entry_price": getattr(a, 'entry_price', 0),
                        "risk_reward_ratio": getattr(a, 'risk_reward', 0),
                    }
                    if alert_dict.get("tqs_score", 0) >= 60:
                        alert_dicts.append(alert_dict)
                except Exception:
                    continue
            
            top_alerts = sorted(
                alert_dicts,
                key=lambda x: x.get("tqs_score", 0),
                reverse=True
            )[:5]
            data["opportunities"] = top_alerts
        except Exception as e:
            logger.warning(f"Failed to get scanner alerts: {e}")
    
    async def _get_ib_quote(self, symbol: str) -> Optional[Dict]:
        """Get real-time quote from IB pushed data if available."""
        try:
            if self.ib_pushed_data:
                quote_data = self.ib_pushed_data.get(symbol.upper())
                if quote_data and quote_data.get("last_price"):
                    return {
                        "price": quote_data.get("last_price"),
                        "bid": quote_data.get("bid"),
                        "ask": quote_data.get("ask"),
                        "volume": quote_data.get("volume"),
                        "source": "ib"
                    }
        except Exception as e:
            logger.debug(f"Error getting IB quote for {symbol}: {e}")
        return None
    
    async def _get_prev_close_from_db(self, symbol: str) -> Optional[float]:
        """Get previous close from ib_historical_data collection."""
        if self._db is None:
            return None
        try:
            bars = list(self._db["ib_historical_data"].find(
                {"symbol": symbol.upper(), "bar_size": "1 day"},
                {"_id": 0, "close": 1, "date": 1}
            ).sort("date", -1).limit(2))
            
            if bars and len(bars) >= 2:
                # Return the second most recent close (previous day)
                return bars[1].get("close")
            elif bars and len(bars) == 1:
                return bars[0].get("close")
        except Exception as e:
            logger.debug(f"Error fetching prev close for {symbol}: {e}")
        return None
    
    async def _fetch_premarket_data(self, data: Dict):
        """
        Fetch pre-market gappers and movers.
        
        Data source priority:
        1. Current price: IB pushed data (if available) -> Alpaca
        2. Previous close: ib_historical_data (MongoDB) -> Alpaca API
        """
        try:
            # Key symbols to check - expanded list
            index_etfs = ["SPY", "QQQ", "IWM", "DIA"]
            # Popular/volatile stocks likely to gap
            watchlist = [
                "NVDA", "TSLA", "AAPL", "AMD", "META", "MSFT", "AMZN", "GOOGL",
                "SMCI", "ARM", "PLTR", "COIN", "MARA", "RIOT", "SOFI", "RBLX",
                "SNOW", "CRWD", "NET", "SQ", "SHOP", "UBER", "LYFT", "ABNB"
            ]
            
            gappers_up = []
            gappers_down = []
            index_status = {}
            
            for symbol in index_etfs + watchlist:
                try:
                    current_price = None
                    quote_source = None
                    
                    # 1. Try IB pushed data first (real-time, highest quality)
                    ib_quote = await self._get_ib_quote(symbol)
                    if ib_quote and ib_quote.get("price"):
                        current_price = ib_quote["price"]
                        quote_source = "ib"
                    
                    # 2. Fallback to Alpaca if IB not available
                    if current_price is None and self.alpaca_service:
                        try:
                            alpaca_quote = await asyncio.to_thread(
                                self.alpaca_service.get_latest_quote, symbol
                            )
                            if alpaca_quote and alpaca_quote.get("price"):
                                current_price = alpaca_quote["price"]
                                quote_source = "alpaca"
                        except Exception:
                            pass
                    
                    if current_price is None or current_price <= 0:
                        continue
                    
                    # 3. Get prev close from ib_historical_data first (fast, no API call)
                    prev_close = await self._get_prev_close_from_db(symbol)
                    
                    # 4. Fallback to Alpaca API if not in DB
                    if prev_close is None and self.alpaca_service:
                        try:
                            bars = await asyncio.to_thread(
                                self.alpaca_service.get_historical_bars, symbol, 2
                            )
                            if bars is not None and len(bars) >= 2:
                                prev_close = bars.iloc[-2]["close"]
                        except Exception:
                            pass
                    
                    if prev_close and prev_close > 0:
                        gap_pct = ((current_price - prev_close) / prev_close) * 100
                        
                        item = {
                            "symbol": symbol,
                            "price": current_price,
                            "prev_close": prev_close,
                            "gap_pct": round(gap_pct, 2),
                            "gap_dollars": round(current_price - prev_close, 2),
                            "quote_source": quote_source  # Track where quote came from
                        }
                        
                        if symbol in index_etfs:
                            index_status[symbol] = item
                        elif abs(gap_pct) >= 1.0:  # 1%+ gap (lowered from 2%)
                            if gap_pct > 0:
                                gappers_up.append(item)
                            else:
                                gappers_down.append(item)
                except Exception as e:
                    logger.debug(f"Failed to get data for {symbol}: {e}")
            
            # Sort gappers by gap percentage
            gappers_up.sort(key=lambda x: x["gap_pct"], reverse=True)
            gappers_down.sort(key=lambda x: x["gap_pct"])
            
            data["gappers"] = {"up": gappers_up[:5], "down": gappers_down[:5]}
            data["index_status"] = index_status
            
        except Exception as e:
            logger.warning(f"Failed to get premarket data: {e}")
    
    async def _fetch_ib_realtime_data(self, data: Dict):
        """Fetch real-time data from IB pusher."""
        try:
            # Import at module level to avoid issues
            import sys
            if 'routers.ib' in sys.modules:
                ib_module = sys.modules['routers.ib']
                ib_data = ib_module._pushed_ib_data
            else:
                # Try direct import
                from routers.ib import _pushed_ib_data as ib_data
            
            # Get pushed quotes from IB
            quotes = ib_data.get("quotes", {})
            
            logger.info(f"IB pushed data quotes: {list(quotes.keys())}")
            
            # Extract key levels
            spy_data = quotes.get("SPY", {})
            qqq_data = quotes.get("QQQ", {})
            vix_data = quotes.get("VIX", {})
            
            key_levels = {}
            
            if spy_data:
                key_levels["SPY"] = {
                    "price": spy_data.get("last", spy_data.get("close", 0)),
                    "high": spy_data.get("high", 0),
                    "low": spy_data.get("low", 0),
                    "open": spy_data.get("open", 0),
                    "volume": spy_data.get("volume", 0)
                }
            
            if qqq_data:
                key_levels["QQQ"] = {
                    "price": qqq_data.get("last", qqq_data.get("close", 0)),
                    "high": qqq_data.get("high", 0),
                    "low": qqq_data.get("low", 0)
                }
            
            if vix_data:
                vix_price = vix_data.get("last", vix_data.get("close", 0))
                key_levels["VIX"] = {
                    "price": vix_price,
                    "level": "LOW" if vix_price < 15 else "NORMAL" if vix_price < 20 else "ELEVATED" if vix_price < 30 else "HIGH"
                }
            
            data["key_levels"] = key_levels
            
            # Populate index_status from IB data
            for symbol in ["SPY", "QQQ", "IWM", "DIA"]:
                if symbol in quotes:
                    q = quotes[symbol]
                    # Calculate gap from previous close if available
                    price = q.get("last", q.get("close", 0))
                    prev_close = q.get("prev_close", q.get("close", 0))
                    
                    if price and prev_close and prev_close > 0:
                        gap_pct = ((price - prev_close) / prev_close) * 100
                        data["index_status"][symbol] = {
                            "price": price,
                            "prev_close": prev_close,
                            "gap_pct": round(gap_pct, 2),
                            "high": q.get("high", 0),
                            "low": q.get("low", 0)
                        }
                    elif price:
                        data["index_status"][symbol] = {
                            "price": price,
                            "high": q.get("high", 0),
                            "low": q.get("low", 0)
                        }
            
            # Build gappers from IB data - use all available symbols
            gappers_up = []
            gappers_down = []
            index_symbols = ["SPY", "QQQ", "IWM", "DIA", "VIX"]
            
            for symbol, q in quotes.items():
                if symbol in index_symbols:
                    continue
                    
                price = q.get("last", q.get("close", 0))
                prev_close = q.get("prev_close", 0)
                open_price = q.get("open", 0)
                
                # Try to calculate gap from prev_close or open
                if prev_close and prev_close > 0 and price:
                    gap_pct = ((price - prev_close) / prev_close) * 100
                elif open_price and open_price > 0 and price:
                    gap_pct = ((price - open_price) / open_price) * 100
                else:
                    continue
                
                if abs(gap_pct) >= 1.0:  # 1%+ move
                    item = {
                        "symbol": symbol,
                        "price": price,
                        "prev_close": prev_close or open_price,
                        "gap_pct": round(gap_pct, 2),
                        "high": q.get("high", 0),
                        "low": q.get("low", 0)
                    }
                    
                    if gap_pct > 0:
                        gappers_up.append(item)
                    else:
                        gappers_down.append(item)
            
            # Sort and update gappers
            gappers_up.sort(key=lambda x: x["gap_pct"], reverse=True)
            gappers_down.sort(key=lambda x: x["gap_pct"])
            
            # Merge with existing gappers (IB data takes priority)
            if gappers_up:
                data["gappers"]["up"] = gappers_up[:5]
            if gappers_down:
                data["gappers"]["down"] = gappers_down[:5]
            
        except Exception as e:
            logger.warning(f"Failed to get IB realtime data: {e}")
    
    async def _fetch_news_and_catalysts(self, data: Dict):
        """
        Fetch real news headlines and identify catalysts.
        Uses IB Gateway (primary) or Finnhub (fallback).
        """
        try:
            # Try news service first (uses IB Gateway with Finnhub fallback)
            if self.news_service:
                try:
                    market_summary = await self.news_service.get_market_summary()
                    if market_summary.get("available"):
                        data["news"]["market_headlines"] = market_summary.get("headlines", [])[:10]
                        data["news"]["themes"] = market_summary.get("themes", [])[:5]
                        data["news"]["sentiment"] = market_summary.get("overall_sentiment", "neutral")
                        
                        # Identify catalysts from headlines
                        catalysts = self._extract_catalysts(market_summary.get("headlines", []))
                        data["catalysts"] = catalysts
                        
                        logger.info(f"Got {len(data['news']['market_headlines'])} headlines, {len(catalysts)} catalysts from news service")
                        return
                except Exception as e:
                    logger.warning(f"News service failed: {e}")
            
            # Fallback: Direct Finnhub API call
            if FINNHUB_API_KEY:
                try:
                    resp = requests.get(
                        "https://finnhub.io/api/v1/news",
                        params={"category": "general", "token": FINNHUB_API_KEY},
                        timeout=10
                    )
                    if resp.status_code == 200:
                        news_items = resp.json()
                        headlines = [item.get("headline", "") for item in news_items[:15]]
                        data["news"]["market_headlines"] = headlines
                        data["news"]["themes"] = self._extract_themes(headlines)
                        data["news"]["sentiment"] = self._analyze_news_sentiment(headlines)
                        data["catalysts"] = self._extract_catalysts(headlines)
                        logger.info(f"Got {len(headlines)} headlines from Finnhub")
                except Exception as e:
                    logger.warning(f"Finnhub news fetch failed: {e}")
            
            # Also fetch ticker-specific news for watchlist
            await self._fetch_ticker_specific_news(data)
            
        except Exception as e:
            logger.warning(f"Failed to fetch news and catalysts: {e}")
    
    async def _fetch_ticker_specific_news(self, data: Dict):
        """Fetch news for key watchlist symbols."""
        try:
            # Get symbols from open positions and gappers
            symbols_to_check = set()
            
            # Add open position symbols
            if data.get("bot", {}).get("open_positions"):
                for pos in data["bot"]["open_positions"][:5]:
                    symbols_to_check.add(pos.get("symbol", ""))
            
            # Add gapper symbols
            for g in data.get("gappers", {}).get("up", [])[:3]:
                symbols_to_check.add(g.get("symbol", ""))
            for g in data.get("gappers", {}).get("down", [])[:3]:
                symbols_to_check.add(g.get("symbol", ""))
            
            # Add key tech stocks if not enough symbols
            default_symbols = ["NVDA", "TSLA", "AAPL", "AMD", "META"]
            while len(symbols_to_check) < 5 and default_symbols:
                symbols_to_check.add(default_symbols.pop(0))
            
            # Remove empty strings
            symbols_to_check = {s for s in symbols_to_check if s}
            
            if not symbols_to_check:
                return
            
            # Fetch news for each symbol
            for symbol in list(symbols_to_check)[:5]:
                try:
                    if self.news_service:
                        news = await self.news_service.get_ticker_news(symbol, max_items=3)
                        if news and not news[0].get("is_placeholder"):
                            data["news"]["ticker_news"][symbol] = [
                                {
                                    "headline": n.get("headline", ""),
                                    "source": n.get("source", ""),
                                    "sentiment": n.get("sentiment", "neutral")
                                }
                                for n in news[:3]
                            ]
                    elif FINNHUB_API_KEY:
                        # Direct Finnhub fallback
                        from_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
                        to_date = datetime.now().strftime("%Y-%m-%d")
                        resp = requests.get(
                            "https://finnhub.io/api/v1/company-news",
                            params={"symbol": symbol, "from": from_date, "to": to_date, "token": FINNHUB_API_KEY},
                            timeout=5
                        )
                        if resp.status_code == 200:
                            news_items = resp.json()[:3]
                            if news_items:
                                data["news"]["ticker_news"][symbol] = [
                                    {
                                        "headline": n.get("headline", ""),
                                        "source": n.get("source", ""),
                                        "sentiment": self._analyze_headline_sentiment(n.get("headline", ""))
                                    }
                                    for n in news_items
                                ]
                except Exception as e:
                    logger.debug(f"Failed to get news for {symbol}: {e}")
                    
        except Exception as e:
            logger.warning(f"Failed to fetch ticker-specific news: {e}")
    
    async def _fetch_sector_rotation(self, data: Dict):
        """
        Fetch sector ETF performance and identify rotation patterns.
        This helps determine if market is favoring growth/value, risk-on/risk-off.
        """
        try:
            # Sector ETF mappings
            sector_etfs = {
                "XLK": "Technology",
                "XLF": "Financials",
                "XLE": "Energy",
                "XLV": "Healthcare",
                "XLI": "Industrials",
                "XLC": "Comm Services",
                "XLY": "Cons Discretionary",
                "XLP": "Cons Staples",
                "XLU": "Utilities",
                "XLRE": "Real Estate",
                "XLB": "Materials"
            }
            
            if self.alpaca_service:
                # get_quotes_batch is already async, so await it directly
                quotes = await self.alpaca_service.get_quotes_batch(list(sector_etfs.keys()))
                
                if quotes:
                    # Sort sectors by performance
                    sector_performance = []
                    for symbol, q in quotes.items():
                        chg = q.get("change_percent", 0)
                        sector_performance.append({
                            "symbol": symbol,
                            "name": sector_etfs.get(symbol, symbol),
                            "change_pct": round(chg, 2),
                            "price": q.get("price", 0)
                        })
                    
                    sector_performance.sort(key=lambda x: x["change_pct"], reverse=True)
                    
                    # Top 3 leaders and bottom 3 laggards
                    data["sectors"]["leaders"] = sector_performance[:3]
                    data["sectors"]["laggards"] = sector_performance[-3:]
                    
                    # Determine rotation signal
                    data["sectors"]["rotation_signal"] = self._analyze_sector_rotation(sector_performance)
                    
                    logger.info(f"Sector rotation: Leaders={[s['symbol'] for s in data['sectors']['leaders']]}")
            
        except Exception as e:
            logger.warning(f"Failed to fetch sector rotation: {e}")
    
    async def _fetch_earnings_calendar(self, data: Dict):
        """
        Fetch earnings calendar for watchlist stocks.
        Warns about upcoming earnings to avoid surprise moves.
        """
        try:
            if not FINNHUB_API_KEY:
                return
            
            # Get symbols to check (positions + watchlist)
            symbols_to_check = set()
            
            # Add open position symbols
            if data.get("bot", {}).get("open_positions"):
                for pos in data["bot"]["open_positions"]:
                    symbols_to_check.add(pos.get("symbol", ""))
            
            # Add gapper symbols
            for g in data.get("gappers", {}).get("up", [])[:5]:
                symbols_to_check.add(g.get("symbol", ""))
            
            # Add key stocks
            symbols_to_check.update(["NVDA", "TSLA", "AAPL", "AMD", "META", "MSFT", "GOOGL", "AMZN"])
            
            # Remove empty
            symbols_to_check = {s for s in symbols_to_check if s}
            
            # Fetch earnings calendar from Finnhub
            from_date = datetime.now().strftime("%Y-%m-%d")
            to_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            
            resp = requests.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={"from": from_date, "to": to_date, "token": FINNHUB_API_KEY},
                timeout=10
            )
            
            if resp.status_code == 200:
                calendar_data = resp.json()
                earnings_list = calendar_data.get("earningsCalendar", [])
                
                # Filter for our watchlist symbols
                upcoming = []
                for e in earnings_list:
                    sym = e.get("symbol", "")
                    if sym in symbols_to_check:
                        timing = "Before Open" if e.get("hour") == "bmo" else "After Close" if e.get("hour") == "amc" else "TBD"
                        upcoming.append({
                            "symbol": sym,
                            "date": e.get("date", ""),
                            "timing": timing,
                            "eps_estimate": e.get("epsEstimate"),
                            "revenue_estimate": e.get("revenueEstimate")
                        })
                
                data["earnings"]["upcoming"] = upcoming[:10]
                
                if upcoming:
                    logger.info(f"Found {len(upcoming)} upcoming earnings for watchlist")
            
        except Exception as e:
            logger.warning(f"Failed to fetch earnings calendar: {e}")
    
    def _extract_catalysts(self, headlines: List[str]) -> List[Dict]:
        """Extract actionable catalysts from news headlines."""
        catalysts = []
        
        # Catalyst patterns
        catalyst_patterns = {
            "earnings": ["beat", "miss", "earnings", "revenue", "eps", "profit", "guidance"],
            "analyst": ["upgrade", "downgrade", "price target", "outperform", "underperform", "buy rating", "sell rating"],
            "fed": ["fed", "fomc", "interest rate", "powell", "rate cut", "rate hike"],
            "economic": ["jobs", "unemployment", "inflation", "cpi", "ppi", "gdp"],
            "deal": ["merger", "acquisition", "buyout", "deal", "takeover"],
            "product": ["launch", "unveil", "announce", "new product", "fda approval"]
        }
        
        for headline in headlines[:15]:
            headline_lower = headline.lower()
            for cat_type, keywords in catalyst_patterns.items():
                if any(kw in headline_lower for kw in keywords):
                    # Extract ticker mention (simple heuristic)
                    ticker = self._extract_ticker_from_headline(headline)
                    catalysts.append({
                        "type": cat_type,
                        "headline": headline[:150],
                        "ticker": ticker,
                        "impact": self._estimate_catalyst_impact(cat_type, headline_lower)
                    })
                    break  # Only categorize once
        
        return catalysts[:8]  # Limit to 8 catalysts
    
    def _extract_ticker_from_headline(self, headline: str) -> Optional[str]:
        """Try to extract a ticker symbol from a headline."""
        import re
        # Look for patterns like "NVDA", "Tesla (TSLA)", etc.
        patterns = [
            r'\(([A-Z]{1,5})\)',  # (NVDA)
            r'^([A-Z]{2,5})\s',   # NVDA at start
            r'\s([A-Z]{2,5})\s',  # NVDA in middle
        ]
        for pattern in patterns:
            match = re.search(pattern, headline)
            if match:
                ticker = match.group(1)
                # Filter out common non-ticker words
                if ticker not in ["THE", "FOR", "AND", "IPO", "CEO", "CFO", "GDP", "CPI", "FED", "SEC"]:
                    return ticker
        return None
    
    def _estimate_catalyst_impact(self, cat_type: str, headline: str) -> str:
        """Estimate the potential market impact of a catalyst."""
        high_impact_words = ["surge", "plunge", "soar", "crash", "record", "historic", "major", "massive"]
        
        if any(word in headline for word in high_impact_words):
            return "high"
        
        high_impact_types = ["fed", "deal", "earnings"]
        if cat_type in high_impact_types:
            return "medium-high"
        
        return "medium"
    
    def _extract_themes(self, headlines: List[str]) -> List[str]:
        """Extract market themes from headlines."""
        themes = []
        theme_keywords = {
            "Federal Reserve / Rates": ["fed", "fomc", "interest rate", "powell"],
            "Earnings Season": ["earnings", "beat", "miss", "revenue"],
            "AI / Technology": ["ai", "artificial intelligence", "nvidia", "chip"],
            "Inflation": ["inflation", "cpi", "ppi", "prices"],
            "Employment": ["jobs", "unemployment", "payroll"],
            "Energy / Oil": ["oil", "energy", "opec"],
            "China / Trade": ["china", "tariff", "trade war"],
            "Crypto / Bitcoin": ["crypto", "bitcoin", "btc"]
        }
        
        combined = " ".join(headlines).lower()
        for theme, keywords in theme_keywords.items():
            if any(kw in combined for kw in keywords):
                themes.append(theme)
        
        return themes[:5]
    
    def _analyze_news_sentiment(self, headlines: List[str]) -> str:
        """Analyze overall sentiment from headlines."""
        bullish = 0
        bearish = 0
        
        bullish_words = ["surge", "rally", "jump", "gain", "rise", "soar", "record high", "bullish", "beat"]
        bearish_words = ["drop", "fall", "plunge", "crash", "decline", "sink", "bearish", "miss", "selloff"]
        
        combined = " ".join(headlines).lower()
        for word in bullish_words:
            bullish += combined.count(word)
        for word in bearish_words:
            bearish += combined.count(word)
        
        if bullish > bearish * 1.5:
            return "bullish"
        elif bearish > bullish * 1.5:
            return "bearish"
        return "neutral"
    
    def _analyze_headline_sentiment(self, headline: str) -> str:
        """Analyze sentiment of a single headline."""
        headline_lower = headline.lower()
        bullish_words = ["surge", "rally", "jump", "gain", "rise", "soar", "beat", "upgrade", "bullish"]
        bearish_words = ["drop", "fall", "plunge", "crash", "decline", "miss", "downgrade", "bearish"]
        
        bullish = sum(1 for w in bullish_words if w in headline_lower)
        bearish = sum(1 for w in bearish_words if w in headline_lower)
        
        if bullish > bearish:
            return "bullish"
        elif bearish > bullish:
            return "bearish"
        return "neutral"
    
    def _analyze_sector_rotation(self, sectors: List[Dict]) -> str:
        """Analyze sector performance to determine market rotation signal."""
        if not sectors:
            return "unknown"
        
        # Categorize sectors
        growth_sectors = ["XLK", "XLC", "XLY"]  # Tech, Comm Services, Consumer Discretionary
        defensive_sectors = ["XLU", "XLP", "XLV"]  # Utilities, Staples, Healthcare
        cyclical_sectors = ["XLF", "XLI", "XLB"]  # Financials, Industrials, Materials
        
        growth_avg = sum(s["change_pct"] for s in sectors if s["symbol"] in growth_sectors) / 3
        defensive_avg = sum(s["change_pct"] for s in sectors if s["symbol"] in defensive_sectors) / 3
        cyclical_avg = sum(s["change_pct"] for s in sectors if s["symbol"] in cyclical_sectors) / 3
        
        # Determine rotation signal
        if growth_avg > defensive_avg + 0.5 and growth_avg > 0:
            return "risk_on_growth"
        elif defensive_avg > growth_avg + 0.5 and defensive_avg > 0:
            return "risk_off_defensive"
        elif cyclical_avg > growth_avg and cyclical_avg > defensive_avg:
            return "cyclical_rotation"
        elif all(s["change_pct"] < 0 for s in sectors[:3]):
            return "broad_selling"
        elif all(s["change_pct"] > 0 for s in sectors[-3:]):
            return "broad_buying"
        else:
            return "mixed_rotation"
    
    def _build_structured_brief(self, data: Dict) -> Dict[str, Any]:
        """Build a structured brief from gathered data."""
        market = data.get("market", {})
        session = data.get("session", {})
        bot = data.get("bot", {})
        learning = data.get("learning", {})
        regime_perf = data.get("regime_performance", {})
        opportunities = data.get("opportunities", [])
        gappers = data.get("gappers", {"up": [], "down": []})
        index_status = data.get("index_status", {})
        key_levels = data.get("key_levels", {})
        
        # Get current regime
        regime = market.get("regime", "HOLD")
        regime_score = market.get("score", 50)
        
        # Build personalized insights
        best_setup_for_regime = None
        win_rate_in_regime = None
        setups_to_avoid = []
        
        if learning:
            # Find best setup for current regime
            regime_setups = learning.get("regime_performance", {}).get(regime, {})
            if regime_setups:
                best = max(regime_setups.items(), key=lambda x: x[1].get("win_rate", 0), default=(None, {}))
                if best[0]:
                    best_setup_for_regime = best[0]
                    win_rate_in_regime = best[1].get("win_rate", 0)
            
            # Get edge decay warnings
            edge_warnings = learning.get("edge_decay_warnings", [])
            setups_to_avoid = [w.get("setup_type") for w in edge_warnings if w.get("severity") == "high"]
        
        # Use regime performance service data if available
        if regime_perf:
            if regime_perf.get("best_strategy"):
                best_setup_for_regime = regime_perf.get("best_strategy")
            if regime_perf.get("win_rate"):
                win_rate_in_regime = regime_perf.get("win_rate")
        
        # Determine market session/time
        now = datetime.now(timezone.utc)
        hour_et = (now.hour - 5) % 24  # Rough EST conversion
        if hour_et < 9 or (hour_et == 9 and now.minute < 30):
            session_name = "Pre-Market"
        elif hour_et < 16:
            session_name = "Regular Hours"
        else:
            session_name = "After Hours"
        
        return {
            "market_summary": {
                "regime": regime,
                "regime_score": regime_score,
                "regime_label": self._get_regime_label(regime),
                "session": session.get("name", session_name),
                "session_advice": session.get("trading_advice", ""),
                "risk_level": session.get("risk_level", "medium"),
                "position_multiplier": market.get("position_multiplier", 1.0)
            },
            "index_status": {
                "SPY": index_status.get("SPY", key_levels.get("SPY", {})),
                "QQQ": index_status.get("QQQ", key_levels.get("QQQ", {})),
                "IWM": index_status.get("IWM", {}),
                "VIX": key_levels.get("VIX", {})
            },
            "gappers": {
                "up": gappers.get("up", [])[:5],
                "down": gappers.get("down", [])[:5]
            },
            "your_bot": {
                "state": bot.get("state", "offline"),
                "running": bot.get("running", False),
                "today_pnl": bot.get("today_pnl", 0),
                "trades_today": bot.get("trades_today", 0),
                "win_rate": bot.get("win_rate", 0),
                "open_positions": [
                    {
                        "symbol": p.get("symbol"),
                        "pnl": p.get("unrealized_pnl", 0),
                        "pnl_pct": p.get("pnl_pct", 0),
                        "direction": p.get("direction", "long")
                    }
                    for p in bot.get("open_positions", [])[:3]
                ]
            },
            "personalized_insights": {
                "best_setup_for_regime": best_setup_for_regime,
                "win_rate_in_regime": win_rate_in_regime,
                "setups_to_avoid": setups_to_avoid,
                "regime_performance": regime_perf
            },
            "opportunities": [
                {
                    "symbol": opp.get("symbol"),
                    "setup": opp.get("setup_type", "").replace("_", " ").title(),
                    "tqs": opp.get("tqs_score", 0),
                    "direction": opp.get("direction", "long"),
                    "entry": opp.get("entry_price"),
                    "risk_reward": opp.get("risk_reward_ratio", 0)
                }
                for opp in opportunities[:5]
            ],
            # NEW: Enhanced data sections
            "news": {
                "headlines": data.get("news", {}).get("market_headlines", [])[:8],
                "ticker_news": data.get("news", {}).get("ticker_news", {}),
                "themes": data.get("news", {}).get("themes", []),
                "sentiment": data.get("news", {}).get("sentiment", "neutral")
            },
            "sectors": {
                "leaders": data.get("sectors", {}).get("leaders", []),
                "laggards": data.get("sectors", {}).get("laggards", []),
                "rotation_signal": data.get("sectors", {}).get("rotation_signal")
            },
            "catalysts": data.get("catalysts", [])[:6],
            "earnings": {
                "upcoming": data.get("earnings", {}).get("upcoming", [])[:5]
            }
        }
    
    def _get_regime_label(self, regime: str) -> str:
        """Get human-readable regime label."""
        labels = {
            "RISK_ON": "Risk On - Bullish",
            "HOLD": "Hold - Neutral",
            "RISK_OFF": "Risk Off - Cautious",
            "CONFIRMED_DOWN": "Confirmed Down - Bearish"
        }
        return labels.get(regime, regime)
    
    async def _generate_quick_summary(self, brief: Dict) -> str:
        """Generate a quick 2-3 sentence summary with news and sector context."""
        market = brief.get("market_summary", {})
        bot = brief.get("your_bot", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        news = brief.get("news", {})
        sectors = brief.get("sectors", {})
        catalysts = brief.get("catalysts", [])
        
        # Build quick summary without LLM for speed
        regime_label = market.get("regime_label", "Neutral")
        session = market.get("session", "")
        position_mult = market.get("position_multiplier", 1.0)
        
        # News sentiment context
        themes = news.get("themes", [])
        
        # Sector context
        leaders = sectors.get("leaders", [])
        
        # Bot status
        bot_state = "actively hunting" if bot.get("running") else "paused"
        today_pnl = bot.get("today_pnl", 0)
        pnl_text = f"+${today_pnl:.0f}" if today_pnl >= 0 else f"-${abs(today_pnl):.0f}"
        
        # Build summary
        summary_parts = []
        
        # Market context with news
        summary_parts.append(f"Market is {regime_label} ({session}).")
        
        # Add news themes if available
        if themes:
            summary_parts.append(f"Key themes: {', '.join(themes[:2])}.")
        
        # Add sector rotation insight
        if leaders:
            top_sector = leaders[0].get("name", "")
            top_chg = leaders[0].get("change_pct", 0)
            if top_chg > 0:
                summary_parts.append(f"{top_sector} leading (+{top_chg:.1f}%).")
        
        # Bot status
        summary_parts.append(f"Bot is {bot_state} with {pnl_text} today.")
        
        # Best opportunity
        top_opp = opportunities[0] if opportunities else None
        if top_opp:
            summary_parts.append(f"Top setup: {top_opp['symbol']} {top_opp['setup']}.")
        
        # Top catalyst if available
        if catalysts:
            top_catalyst = catalysts[0]
            if top_catalyst.get("ticker"):
                summary_parts.append(f"Catalyst: {top_catalyst['ticker']} ({top_catalyst['type']}).")
        
        # Best setup for regime
        best_setup = insights.get("best_setup_for_regime")
        win_rate = insights.get("win_rate_in_regime")
        if best_setup and win_rate:
            summary_parts.append(f"Your best: {best_setup.replace('_', ' ').title()} ({win_rate:.0f}% WR).")
        
        # Position sizing recommendation
        if position_mult < 1.0:
            summary_parts.append(f"Size: {position_mult*100:.0f}%.")
        
        return " ".join(summary_parts)
    
    async def _generate_detailed_summary(self, brief: Dict, rich_intel: Dict = None) -> Dict[str, str]:
        """Generate a detailed multi-section summary with news, sectors, and catalysts."""
        market = brief.get("market_summary", {})
        bot = brief.get("your_bot", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        index_status = brief.get("index_status", {})
        gappers = brief.get("gappers", {"up": [], "down": []})
        # NEW: Enhanced data
        news_data = brief.get("news", {})
        sectors_data = brief.get("sectors", {})
        catalysts = brief.get("catalysts", [])
        earnings_data = brief.get("earnings", {})
        
        # Use rich_intel from MarketIntelService if available
        sections = {}
        
        # If we have rich intel from MarketIntelService, use its content
        if rich_intel:
            logger.info(f"Using rich_intel with keys: {list(rich_intel.keys())}")
            
            # MarketIntelService provides formatted sections
            if rich_intel.get("market_regime"):
                sections["market_overview"] = f"**{rich_intel.get('market_regime', '')}**\n\n{rich_intel.get('regime_detail', '')}\n\n{rich_intel.get('vix_assessment', '')}\n\n📋 {rich_intel.get('strategy_recommendation', '')}"
            
            if rich_intel.get("news_summary"):
                sections["news"] = f"**📰 Market News:**\n\n{rich_intel.get('news_summary', '')}"
            
            if rich_intel.get("watchlist_in_play"):
                sections["in_play"] = f"**🔥 IN PLAY TODAY:**\n\n{rich_intel.get('watchlist_in_play', '')}"
            
            if rich_intel.get("sector_rotation"):
                sections["sectors"] = f"**📊 Sector Rotation:**\n\n{rich_intel.get('sector_rotation', '')}"
            
            if rich_intel.get("earnings_watch"):
                sections["earnings"] = f"**📅 Earnings Watch:**\n\n{rich_intel.get('earnings_watch', '')}"
        
        # Try LLM generation if no rich_intel
        if not rich_intel and self.llm_provider:
            try:
                llm_summary = await self._generate_llm_summary(brief)
                if llm_summary:
                    return llm_summary
            except Exception as e:
                logger.warning(f"LLM summary generation failed: {e}")
        
        regime = market.get("regime", "HOLD")
        
        # Build Market Overview with Index Status if not already set
        if "market_overview" not in sections:
            regime_label = market.get("regime_label", "Neutral")
            score = market.get("regime_score", 50)
            session = market.get("session", "Unknown")
            session_advice = market.get("session_advice", "")
            
            # Build index status text
            index_text = ""
            spy = index_status.get("SPY", {})
            qqq = index_status.get("QQQ", {})
            vix = index_status.get("VIX", {})
            
            if spy:
                spy_price = spy.get("price", 0)
                spy_gap = spy.get("gap_pct", 0)
                if spy_price:
                    index_text += f"**SPY:** ${spy_price:.2f}"
                    if spy_gap:
                        index_text += f" ({'+' if spy_gap > 0 else ''}{spy_gap:.1f}%)"
                    index_text += "\n"
            
            if qqq:
                qqq_price = qqq.get("price", 0)
                qqq_gap = qqq.get("gap_pct", 0)
                if qqq_price:
                    index_text += f"**QQQ:** ${qqq_price:.2f}"
                    if qqq_gap:
                        index_text += f" ({'+' if qqq_gap > 0 else ''}{qqq_gap:.1f}%)"
                    index_text += "\n"
            
            if vix:
                vix_price = vix.get("price", 0)
                vix_level = vix.get("level", "")
                if vix_price:
                    index_text += f"**VIX:** {vix_price:.1f} ({vix_level})\n"
            
            sections["market_overview"] = (
                f"**Market Regime: {regime_label}** (Score: {score}/100)\n\n"
                f"**Session:** {session}\n\n"
                f"{index_text if index_text else ''}"
                f"{session_advice}"
            )
        
        # NEW: News & Catalysts Section
        if "news" not in sections:
            headlines = news_data.get("headlines", [])
            themes = news_data.get("themes", [])
            sentiment = news_data.get("sentiment", "neutral")
            ticker_news = news_data.get("ticker_news", {})
            
            news_text = ""
            
            # Add themes if available
            if themes:
                news_text += f"**Today's Themes:** {', '.join(themes)}\n\n"
            
            # Add sentiment
            sentiment_emoji = "🟢" if sentiment == "bullish" else "🔴" if sentiment == "bearish" else "🟡"
            news_text += f"**Market Sentiment:** {sentiment_emoji} {sentiment.title()}\n\n"
            
            # Add top headlines
            if headlines:
                news_text += "**Top Headlines:**\n"
                for h in headlines[:5]:
                    news_text += f"- {h[:100]}{'...' if len(h) > 100 else ''}\n"
            
            # Add ticker-specific news
            if ticker_news:
                news_text += "\n**Stock-Specific News:**\n"
                for symbol, news_items in list(ticker_news.items())[:3]:
                    if news_items:
                        top_headline = news_items[0].get("headline", "")[:80]
                        news_text += f"- **{symbol}:** {top_headline}\n"
            
            if news_text:
                sections["news"] = f"**📰 News & Catalysts:**\n\n{news_text}"
        
        # NEW: Catalysts Section
        if catalysts and "catalysts" not in sections:
            catalyst_text = ""
            for cat in catalysts[:5]:
                impact = cat.get("impact", "medium")
                impact_emoji = "🔥" if impact == "high" else "⚡" if "medium" in impact else "📌"
                ticker = cat.get("ticker", "")
                ticker_str = f"[{ticker}] " if ticker else ""
                cat_type = cat.get("type", "").replace("_", " ").title()
                headline = cat.get("headline", "")[:80]
                catalyst_text += f"{impact_emoji} {ticker_str}**{cat_type}:** {headline}\n"
            
            if catalyst_text:
                sections["catalysts"] = f"**🎯 Today's Catalysts:**\n\n{catalyst_text}"
        
        # NEW: Sector Rotation Section
        if "sectors" not in sections:
            leaders = sectors_data.get("leaders", [])
            laggards = sectors_data.get("laggards", [])
            rotation_signal = sectors_data.get("rotation_signal", "")
            
            sector_text = ""
            
            # Rotation signal interpretation
            if rotation_signal:
                signal_interpretations = {
                    "risk_on_growth": "🚀 **Risk-On:** Growth/Tech sectors leading - favor momentum plays",
                    "risk_off_defensive": "🛡️ **Risk-Off:** Defensive sectors leading - be cautious with growth",
                    "cyclical_rotation": "🔄 **Cyclical Rotation:** Money moving to value/industrials",
                    "broad_selling": "📉 **Broad Selling:** All sectors weak - reduce exposure",
                    "broad_buying": "📈 **Broad Buying:** All sectors strong - trend day possible",
                    "mixed_rotation": "🔀 **Mixed:** No clear rotation - focus on individual stocks"
                }
                sector_text += signal_interpretations.get(rotation_signal, f"Signal: {rotation_signal}") + "\n\n"
            
            if leaders:
                sector_text += "**Leading Sectors:**\n"
                for s in leaders:
                    chg = s.get("change_pct", 0)
                    emoji = "🟢" if chg > 0 else "🔴"
                    sector_text += f"{emoji} {s.get('name', s.get('symbol'))}: {'+' if chg > 0 else ''}{chg:.2f}%\n"
            
            if laggards:
                sector_text += "\n**Lagging Sectors:**\n"
                for s in laggards:
                    chg = s.get("change_pct", 0)
                    emoji = "🟢" if chg > 0 else "🔴"
                    sector_text += f"{emoji} {s.get('name', s.get('symbol'))}: {'+' if chg > 0 else ''}{chg:.2f}%\n"
            
            if sector_text:
                sections["sectors"] = f"**📊 Sector Rotation:**\n\n{sector_text}"
        
        # NEW: Earnings Warning Section
        if "earnings" not in sections:
            upcoming = earnings_data.get("upcoming", [])
            if upcoming:
                earnings_text = "⚠️ **Watchlist stocks reporting soon:**\n\n"
                for e in upcoming[:5]:
                    timing = e.get("timing", "TBD")
                    eps = e.get("eps_estimate")
                    eps_str = f" (EPS Est: ${eps:.2f})" if eps else ""
                    earnings_text += f"- **{e.get('symbol')}**: {e.get('date')} {timing}{eps_str}\n"
                earnings_text += "\n💡 *Consider reducing position size before earnings!*"
                sections["earnings"] = f"**📅 Earnings Watch:**\n\n{earnings_text}"
        
        # Gappers Section (only if not from rich_intel "in_play")
        if "in_play" not in sections and "gappers" not in sections:
            gappers_up = gappers.get("up", [])
            gappers_down = gappers.get("down", [])
            
            if gappers_up or gappers_down:
                gapper_text = ""
                
                if gappers_up:
                    gapper_text += "**🟢 Gapping UP:**\n"
                    for g in gappers_up[:5]:
                        gapper_text += f"- **{g['symbol']}** +{g['gap_pct']:.1f}% (${g['price']:.2f})\n"
                    gapper_text += "\n"
                
                if gappers_down:
                    gapper_text += "**🔴 Gapping DOWN:**\n"
                    for g in gappers_down[:5]:
                        gapper_text += f"- **{g['symbol']}** {g['gap_pct']:.1f}% (${g['price']:.2f})\n"
                
                sections["gappers"] = gapper_text if gapper_text else "No significant gaps today."
            else:
                sections["gappers"] = "No significant gappers detected (need 2%+ move)."
        
        # Your Bot Status
        bot_state = "actively hunting for opportunities" if bot.get("running") else "currently paused"
        today_pnl = bot.get("today_pnl", 0)
        trades = bot.get("trades_today", 0)
        win_rate = bot.get("win_rate", 0)
        
        positions_text = ""
        for pos in bot.get("open_positions", []):
            pnl_pct = pos.get("pnl_pct", 0)
            direction = pos.get("direction", "long").upper()
            positions_text += f"- **{pos['symbol']}** ({direction}): {'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%\n"
        
        sections["bot_status"] = (
            f"Your bot is {bot_state}.\n\n"
            f"**Today's Performance:**\n"
            f"- P&L: {'+'if today_pnl >= 0 else ''}${today_pnl:.2f}\n"
            f"- Trades: {trades}\n"
            f"- Win Rate: {win_rate:.0f}%\n\n"
            f"**Open Positions:**\n{positions_text if positions_text else '- No open positions'}"
        )
        
        # Personalized Insights
        best_setup = insights.get("best_setup_for_regime")
        win_rate_regime = insights.get("win_rate_in_regime")
        avoid_setups = insights.get("setups_to_avoid", [])
        
        insights_text = ""
        if best_setup:
            insights_text += f"- **Best Setup for {regime}:** {best_setup.replace('_', ' ').title()}"
            if win_rate_regime:
                insights_text += f" ({win_rate_regime:.0f}% historical win rate)"
            insights_text += "\n"
        
        if avoid_setups:
            insights_text += f"- **Consider Avoiding:** {', '.join([s.replace('_', ' ').title() for s in avoid_setups])}\n"
        
        position_mult = market.get("position_multiplier", 1.0)
        if position_mult < 1.0:
            insights_text += f"- **Position Sizing:** Reduce to {position_mult*100:.0f}% due to market conditions\n"
        
        sections["personalized_insights"] = (
            f"**Based on Your Trading History:**\n\n{insights_text if insights_text else 'Keep trading your edge!'}"
        )
        
        # Top Opportunities / Stocks to Watch
        if opportunities:
            opps_text = ""
            for opp in opportunities[:5]:
                symbol = opp.get("symbol", "")
                setup = opp.get("setup", "")
                tqs = opp.get("tqs", 0)
                direction = opp.get("direction", "long").upper()
                rr = opp.get("risk_reward", 0)
                opps_text += f"- **{symbol}** - {setup} ({direction}) | TQS: {tqs} | R:R: {rr:.1f}\n"
            
            sections["opportunities"] = f"**📊 Stocks to Watch:**\n\n{opps_text}"
        else:
            sections["opportunities"] = "**📊 Stocks to Watch:**\n\nNo high-quality setups active right now. Check the scanner for emerging opportunities."
        
        # Recommendation (enhanced with sector/catalyst context)
        recommendation = self._generate_recommendation(brief)
        sections["recommendation"] = f"**💡 Recommendation:**\n\n{recommendation}"
        
        return sections
    
    def _generate_recommendation(self, brief: Dict) -> str:
        """Generate a trading recommendation based on the brief with sector and catalyst context."""
        market = brief.get("market_summary", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        sectors = brief.get("sectors", {})
        catalysts = brief.get("catalysts", [])
        earnings = brief.get("earnings", {})
        
        regime = market.get("regime", "HOLD")
        best_setup = insights.get("best_setup_for_regime")
        position_mult = market.get("position_multiplier", 1.0)
        
        rec_parts = []
        
        # Regime-based advice
        if regime == "RISK_ON":
            rec_parts.append("Market conditions favor aggressive entries.")
        elif regime == "RISK_OFF":
            rec_parts.append("Be selective with entries and use tighter stops.")
        elif regime == "CONFIRMED_DOWN":
            rec_parts.append("Consider short setups or staying mostly cash.")
        else:
            rec_parts.append("Wait for clearer signals before committing capital.")
        
        # Sector rotation context
        rotation_signal = sectors.get("rotation_signal", "")
        if rotation_signal == "risk_on_growth":
            rec_parts.append("Tech/Growth sectors leading - favor momentum longs.")
        elif rotation_signal == "risk_off_defensive":
            rec_parts.append("Defensive rotation underway - be cautious with growth names.")
        elif rotation_signal == "broad_selling":
            rec_parts.append("Broad weakness - consider staying cash or short setups only.")
        
        # Leading sector focus
        leaders = sectors.get("leaders", [])
        if leaders and leaders[0].get("change_pct", 0) > 1.0:
            top_sector = leaders[0].get("name", "")
            rec_parts.append(f"Focus on {top_sector} stocks for best momentum.")
        
        # Setup advice
        if best_setup:
            rec_parts.append(f"Your best setup: {best_setup.replace('_', ' ').title()}.")
        
        # Opportunity highlight
        if opportunities:
            top = opportunities[0]
            rec_parts.append(f"Watch {top['symbol']} for a {top['setup']} entry.")
        
        # Catalyst awareness
        high_impact_catalysts = [c for c in catalysts if c.get("impact") == "high"]
        if high_impact_catalysts:
            tickers = [c.get("ticker") for c in high_impact_catalysts if c.get("ticker")]
            if tickers:
                rec_parts.append(f"Catalyst alert: {', '.join(tickers[:2])} - watch for volatility.")
        
        # Earnings warning
        upcoming_earnings = earnings.get("upcoming", [])
        if upcoming_earnings:
            earnings_symbols = [e.get("symbol") for e in upcoming_earnings[:2]]
            rec_parts.append(f"Earnings soon: {', '.join(earnings_symbols)} - reduce size or avoid.")
        
        # Position sizing
        if position_mult < 1.0:
            rec_parts.append(f"Size: {position_mult*100:.0f}% of normal.")
        
        return " ".join(rec_parts)
    
    async def _generate_llm_summary(self, brief: Dict) -> Optional[Dict[str, str]]:
        """Use LLM to generate a more natural summary."""
        if not self.llm_provider:
            return None
        
        prompt = self._build_llm_prompt(brief)
        
        try:
            response = await self.llm_provider.generate(
                prompt=prompt,
                system_prompt=(
                    "You are part of a trading team providing market briefings. "
                    "Speak as 'we' - the human trader and AI working together as partners. "
                    "Examples: 'We're seeing...', 'Our positions...', 'We should consider...'. "
                    "Be concise, specific with numbers. Never use 'you' or 'your' - always 'we' and 'our'. "
                    "Format your response with clear section headers using **bold**."
                ),
                max_tokens=800
            )
            
            if response and response.get("success"):
                # Parse LLM response into sections
                content = response.get("content", "")
                return {"full_summary": content}
            
        except Exception as e:
            logger.warning(f"LLM generation failed: {e}")
        
        return None
    
    def _build_llm_prompt(self, brief: Dict) -> str:
        """Build prompt for LLM summary generation."""
        market = brief.get("market_summary", {})
        bot = brief.get("your_bot", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        
        prompt = f"""Generate a personalized market briefing for our trading team based on this data:

MARKET CONDITIONS:
- Regime: {market.get('regime', 'HOLD')} (Score: {market.get('regime_score', 50)}/100)
- Session: {market.get('session', 'Unknown')}
- Position Sizing: {market.get('position_multiplier', 1.0) * 100:.0f}%

OUR BOT STATUS:
- State: {'Running' if bot.get('running') else 'Paused'}
- Today's P&L: ${bot.get('today_pnl', 0):.2f}
- Trades Today: {bot.get('trades_today', 0)}
- Open Positions: {len(bot.get('open_positions', []))}

OUR BEST SETUP FOR THIS REGIME: {insights.get('best_setup_for_regime', 'Not enough data')}
OUR WIN RATE IN THIS REGIME: {insights.get('win_rate_in_regime', 'N/A')}

TOP OPPORTUNITIES:
{self._format_opportunities(opportunities)}

Generate a 4-section briefing using "we/our" language:
1. Market Overview (2-3 sentences - what we're seeing)
2. Our Bot Status (current state + positions)
3. Our Edge (what works for us in this regime)
4. Recommendation (1-2 actionable sentences for what we should focus on)
"""
        return prompt
    
    def _format_opportunities(self, opportunities: List[Dict]) -> str:
        """Format opportunities for the LLM prompt."""
        if not opportunities:
            return "None active"
        
        lines = []
        for opp in opportunities[:5]:
            lines.append(f"- {opp['symbol']}: {opp['setup']} ({opp['direction']}) TQS={opp['tqs']}")
        
        return "\n".join(lines)
    
    def _generate_fallback_summary(self) -> str:
        """Generate a fallback summary when data fetch fails."""
        return (
            "Unable to generate a full briefing at this time. "
            "Check your positions manually and review the market regime widget for current conditions."
        )
