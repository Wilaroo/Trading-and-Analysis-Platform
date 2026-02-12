"""
Market Intelligence & Strategy Playbook Service

Generates time-of-day market intelligence reports with AI-powered analysis.
Auto-generates at scheduled times throughout the trading day.

Report Schedule (Eastern Time):
- 8:30 AM  - Pre-Market Briefing (overnight, earnings, upgrades/downgrades, strategy playbook)
- 10:30 AM - Early Market Report (first hour recap, gap analysis, volume)
- 2:00 PM  - Midday Report (day progress, sector rotation, bot performance)
- 2:30 PM  - Power Hour Report (EOD setups, momentum shifts, action items)
- 4:30 PM  - Post-Market Wrap (day recap, P&L, learning insights, tomorrow prep)
"""
import asyncio
import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import json

logger = logging.getLogger(__name__)

REPORT_SCHEDULE = [
    {"type": "premarket", "label": "Pre-Market Briefing", "hour": 8, "minute": 30, "icon": "sunrise"},
    {"type": "early_market", "label": "Early Market Report", "hour": 10, "minute": 30, "icon": "trending-up"},
    {"type": "midday", "label": "Midday Report", "hour": 14, "minute": 0, "icon": "sun"},
    {"type": "power_hour", "label": "Power Hour Report", "hour": 14, "minute": 30, "icon": "zap"},
    {"type": "post_market", "label": "Post-Market Wrap", "hour": 16, "minute": 30, "icon": "moon"},
]


class MarketIntelService:
    """Generates time-based market intelligence reports using AI"""

    def __init__(self, db=None):
        self._db = db
        self._ai_assistant = None
        self._trading_bot = None
        self._perf_service = None
        self._alpaca_service = None
        self._news_service = None
        self._scanner_service = None
        self._smart_watchlist = None
        self._alert_system = None
        self._earnings_service = None
        self._scheduler_running = False
        self._finnhub_key = os.environ.get("FINNHUB_API_KEY", "")

    def set_services(self, ai_assistant=None, trading_bot=None, perf_service=None,
                     alpaca_service=None, news_service=None, scanner_service=None,
                     smart_watchlist=None, alert_system=None, earnings_service=None):
        if ai_assistant:
            self._ai_assistant = ai_assistant
        if trading_bot:
            self._trading_bot = trading_bot
        if perf_service:
            self._perf_service = perf_service
        if alpaca_service:
            self._alpaca_service = alpaca_service
        if news_service:
            self._news_service = news_service
        if scanner_service:
            self._scanner_service = scanner_service
        if smart_watchlist:
            self._smart_watchlist = smart_watchlist
        if alert_system:
            self._alert_system = alert_system
        if earnings_service:
            self._earnings_service = earnings_service
        logger.info("Market intel service wired")

    # ==================== CONTEXT GATHERING ====================

    async def _gather_news_context(self) -> str:
        """Gather REAL news from Finnhub directly — no hallucination"""
        parts = []

        # Fetch real market news from Finnhub
        if self._finnhub_key:
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/news",
                    params={"category": "general", "token": self._finnhub_key},
                    timeout=10
                )
                if resp.status_code == 200:
                    news_items = resp.json()
                    if news_items:
                        parts.append("=== REAL-TIME MARKET NEWS (from Finnhub — these are REAL headlines) ===")
                        for i, item in enumerate(news_items[:15], 1):
                            headline = item.get("headline", "")
                            summary = item.get("summary", "")[:150]
                            source = item.get("source", "")
                            ts = item.get("datetime", 0)
                            time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m/%d %I:%M %p") if ts else ""
                            parts.append(f"  {i}. [{source}] {headline}")
                            if summary:
                                parts.append(f"     {summary}")
                            if time_str:
                                parts.append(f"     Published: {time_str} UTC")

                        # Categorize for the AI
                        earnings_kw = ["earnings", "beat", "miss", "revenue", "eps", "guidance", "quarterly", "profit"]
                        analyst_kw = ["upgrade", "downgrade", "price target", "outperform", "underperform", "overweight", "buy rating", "sell rating"]

                        earnings_news = [n for n in news_items[:50] if any(kw in (n.get("headline", "") + n.get("summary", "")).lower() for kw in earnings_kw)]
                        analyst_news = [n for n in news_items[:50] if any(kw in (n.get("headline", "") + n.get("summary", "")).lower() for kw in analyst_kw)]

                        if earnings_news:
                            parts.append("\n=== EARNINGS NEWS (filtered from above) ===")
                            for n in earnings_news[:5]:
                                parts.append(f"  - {n.get('headline', '')}")

                        if analyst_news:
                            parts.append("\n=== ANALYST UPGRADES/DOWNGRADES (filtered from above) ===")
                            for n in analyst_news[:5]:
                                parts.append(f"  - {n.get('headline', '')}")

                        if not earnings_news and not analyst_news:
                            parts.append("\n(No earnings or analyst actions found in recent news)")
                else:
                    parts.append(f"News API returned status {resp.status_code}")
            except Exception as e:
                logger.warning(f"Error fetching Finnhub news: {e}")
                parts.append(f"News fetch error: {e}")
        else:
            parts.append("No Finnhub API key configured — cannot fetch real news")

        return "\n".join(parts) if parts else "No real-time news available"

    def _gather_bot_context(self) -> str:
        """Gather EXACT trading bot status — read directly from service"""
        if not self._trading_bot:
            return "=== TRADING BOT STATUS ===\nBot service not connected"
        try:
            ctx = self._trading_bot.get_bot_context_for_ai()
            return f"(This is EXACT bot data read from the system — do not modify or guess)\n{ctx}"
        except Exception as e:
            logger.warning(f"Error getting bot context: {e}")
            return f"=== TRADING BOT STATUS ===\nError reading bot state: {e}"

    def _gather_learning_context(self) -> str:
        """Gather EXACT strategy performance data from the learning loop"""
        if not self._perf_service:
            return "=== STRATEGY PERFORMANCE ===\nLearning loop not connected"
        try:
            ctx = self._perf_service.get_learning_summary_for_ai()
            return f"(This is EXACT performance data from the database — do not modify or guess)\n{ctx}"
        except Exception as e:
            logger.warning(f"Error getting learning context: {e}")
            return f"=== STRATEGY PERFORMANCE ===\nError reading performance data: {e}"

    async def _gather_positions_context(self) -> str:
        """Gather EXACT current positions and P&L from Alpaca"""
        parts = []
        try:
            if self._alpaca_service:
                account = await self._alpaca_service.get_account()
                positions = await self._alpaca_service.get_positions()
                if account:
                    parts.append("=== ACCOUNT STATUS (EXACT from Alpaca) ===")
                    parts.append(f"Equity: ${float(account.get('equity', 0)):,.2f}")
                    parts.append(f"Day P&L: ${float(account.get('unrealized_pl', 0)):,.2f}")
                    parts.append(f"Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
                else:
                    parts.append("=== ACCOUNT STATUS ===\nAccount data unavailable")
                if positions:
                    parts.append(f"\nOPEN POSITIONS ({len(positions)}):")
                    for p in positions[:10]:
                        sym = p.get("symbol", "?")
                        qty = p.get("qty", 0)
                        pnl = float(p.get("unrealized_pl", 0))
                        pnl_pct = float(p.get("unrealized_plpc", 0)) * 100
                        parts.append(f"  {sym}: {qty} sh | P&L: ${pnl:,.2f} ({pnl_pct:+.1f}%)")
                else:
                    parts.append("\nOPEN POSITIONS: None")
        except Exception as e:
            logger.warning(f"Error gathering positions: {e}")
            parts.append(f"=== ACCOUNT STATUS ===\nError: {e}")
        return "\n".join(parts)

    async def _gather_market_data_context(self) -> str:
        """Gather EXACT market index data"""
        parts = []
        try:
            if self._alpaca_service:
                quotes = await self._alpaca_service.get_quotes_batch(["SPY", "QQQ", "IWM", "DIA", "VIX"])
                if quotes:
                    parts.append("=== MARKET INDICES (EXACT live quotes) ===")
                    # quotes is a dict keyed by symbol, iterate over values
                    for sym, q in quotes.items():
                        price = q.get("price", 0)
                        chg = q.get("change_percent", 0)
                        parts.append(f"  {sym}: ${price:.2f} ({chg:+.2f}%)")
                else:
                    parts.append("=== MARKET INDICES ===\nQuote data unavailable")
        except Exception as e:
            logger.warning(f"Error gathering market data: {e}")
            parts.append(f"=== MARKET INDICES ===\nError: {e}")
        return "\n".join(parts)

    async def _gather_scanner_context(self) -> str:
        """Gather recent scanner results"""
        parts = []
        if self._scanner_service:
            try:
                alerts = self._scanner_service.get_live_alerts()
                if alerts:
                    parts.append("=== SCANNER SIGNALS (EXACT recent scanner alerts) ===")
                    for alert in alerts[:10]:
                        sym = getattr(alert, 'symbol', '?')
                        setup = getattr(alert, 'setup_type', '?')
                        priority = getattr(alert, 'priority', '?')
                        price = getattr(alert, 'price', 0)
                        msg = getattr(alert, 'message', '')
                        parts.append(f"  {sym}: {setup} ({priority}) @ ${price:.2f}")
                        if msg:
                            parts.append(f"    {msg[:100]}")
                else:
                    parts.append("=== SCANNER SIGNALS ===\nNo recent signals")
            except Exception as e:
                logger.warning(f"Error gathering scanner data: {e}")
        return "\n".join(parts) if parts else ""

    async def _gather_watchlist_context(self) -> str:
        """Gather Smart Watchlist with IN PLAY status - THE KEY IMPROVEMENT"""
        parts = []
        try:
            # Get actual Smart Watchlist symbols (not hardcoded!)
            watchlist_symbols = []
            watchlist_items = {}
            
            if self._smart_watchlist:
                items = self._smart_watchlist.get_watchlist()
                watchlist_symbols = [item.symbol for item in items]
                watchlist_items = {item.symbol: item for item in items}
                
            # Fallback to default if no smart watchlist
            if not watchlist_symbols:
                watchlist_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN"]
            
            if self._alpaca_service and watchlist_symbols:
                quotes = await self._alpaca_service.get_quotes_batch(watchlist_symbols[:20])
                
                if quotes:
                    # Check IN PLAY status for each symbol
                    in_play_stocks = []
                    not_in_play_stocks = []
                    
                    for q in quotes:
                        sym = q.get("symbol", "?")
                        price = q.get("price", 0)
                        chg = q.get("change_percent", 0)
                        vol = q.get("volume", 0)
                        
                        # Get watchlist item info
                        wl_item = watchlist_items.get(sym)
                        source = wl_item.source if wl_item else "default"
                        strategies = wl_item.strategies_matched[:2] if wl_item and wl_item.strategies_matched else []
                        
                        # Basic in-play check: significant movement or high volume
                        is_active = abs(chg) >= 1.0 or vol > 500000
                        
                        stock_info = {
                            "sym": sym,
                            "price": price,
                            "chg": chg,
                            "vol": vol,
                            "source": source,
                            "strategies": strategies,
                            "is_active": is_active
                        }
                        
                        if is_active:
                            in_play_stocks.append(stock_info)
                        else:
                            not_in_play_stocks.append(stock_info)
                    
                    # Format output with IN PLAY stocks first
                    parts.append("=== SMART WATCHLIST STATUS ===")
                    parts.append(f"Total symbols: {len(quotes)} | Active/In-Play: {len(in_play_stocks)}")
                    
                    if in_play_stocks:
                        parts.append("\n🔥 IN PLAY TODAY (Active movement):")
                        for s in in_play_stocks[:10]:
                            strat_str = f" [{', '.join(s['strategies'])}]" if s['strategies'] else ""
                            parts.append(f"  {s['sym']}: ${s['price']:.2f} ({s['chg']:+.2f}%) vol:{s['vol']:,}{strat_str}")
                    
                    if not_in_play_stocks:
                        parts.append("\n⏸️ ON WATCH (Low activity today):")
                        for s in not_in_play_stocks[:5]:
                            parts.append(f"  {s['sym']}: ${s['price']:.2f} ({s['chg']:+.2f}%)")
                    
        except Exception as e:
            logger.warning(f"Error gathering smart watchlist: {e}")
            parts.append(f"=== WATCHLIST ===\nError: {e}")
        
        return "\n".join(parts) if parts else ""

    async def _gather_ticker_specific_news(self, symbols: list = None) -> str:
        """Fetch company-specific news for watchlist symbols"""
        parts = []
        
        if not self._finnhub_key:
            return ""
        
        # Get symbols from smart watchlist if not provided
        if not symbols and self._smart_watchlist:
            items = self._smart_watchlist.get_watchlist()
            symbols = [item.symbol for item in items[:10]]  # Top 10 watchlist items
        
        if not symbols:
            symbols = ["NVDA", "TSLA", "AAPL", "AMD", "META"]  # Default fallback
        
        parts.append("=== TICKER-SPECIFIC NEWS (from Finnhub company-news) ===")
        
        news_found = False
        for symbol in symbols[:8]:  # Limit to 8 to avoid rate limits
            try:
                # Finnhub company news endpoint
                from_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
                to_date = datetime.now().strftime("%Y-%m-%d")
                
                resp = requests.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={
                        "symbol": symbol,
                        "from": from_date,
                        "to": to_date,
                        "token": self._finnhub_key
                    },
                    timeout=5
                )
                
                if resp.status_code == 200:
                    news_items = resp.json()
                    if news_items:
                        news_found = True
                        parts.append(f"\n**{symbol}**:")
                        for item in news_items[:3]:  # Max 3 per ticker
                            headline = item.get("headline", "")[:100]
                            source = item.get("source", "")
                            parts.append(f"  - [{source}] {headline}")
            except Exception as e:
                logger.debug(f"Error fetching news for {symbol}: {e}")
                continue
        
        if not news_found:
            parts.append("  No recent company-specific news found")
        
        return "\n".join(parts)

    async def _gather_market_regime_context(self) -> str:
        """Classify market regime based on SPY/QQQ behavior"""
        parts = []
        
        try:
            if not self._alpaca_service:
                return ""
            
            # Get index data
            indices = await self._alpaca_service.get_quotes_batch(["SPY", "QQQ", "IWM", "VIX"])
            if not indices:
                return ""
            
            spy = next((q for q in indices if q.get("symbol") == "SPY"), {})
            qqq = next((q for q in indices if q.get("symbol") == "QQQ"), {})
            iwm = next((q for q in indices if q.get("symbol") == "IWM"), {})
            vix = next((q for q in indices if q.get("symbol") == "VIX"), {})
            
            spy_chg = spy.get("change_percent", 0)
            qqq_chg = qqq.get("change_percent", 0)
            iwm_chg = iwm.get("change_percent", 0)
            vix_level = vix.get("price", 15)
            
            # Determine regime
            regime = "UNKNOWN"
            regime_detail = ""
            strategy_recommendation = ""
            
            # Strong trend day
            if spy_chg > 1.0 and qqq_chg > 1.0:
                regime = "STRONG UPTREND DAY"
                regime_detail = "Both SPY and QQQ up >1% - momentum is strong"
                strategy_recommendation = "FAVOR: Breakouts, Gap & Go, Trend Continuation. AVOID: Fades, Mean Reversion"
            elif spy_chg < -1.0 and qqq_chg < -1.0:
                regime = "STRONG DOWNTREND DAY"
                regime_detail = "Both SPY and QQQ down >1% - sellers in control"
                strategy_recommendation = "FAVOR: Breakdowns, Short setups, Backside plays. AVOID: Long breakouts"
            
            # Rotation day (divergence)
            elif abs(spy_chg - qqq_chg) > 1.0:
                regime = "ROTATION DAY"
                if qqq_chg > spy_chg:
                    regime_detail = f"Tech leading (QQQ {qqq_chg:+.1f}% vs SPY {spy_chg:+.1f}%) - Growth > Value"
                else:
                    regime_detail = f"Value leading (SPY {spy_chg:+.1f}% vs QQQ {qqq_chg:+.1f}%) - Rotation out of tech"
                strategy_recommendation = "FAVOR: Relative strength/weakness plays. Focus on sector leaders"
            
            # Small cap day
            elif iwm_chg > spy_chg + 0.5:
                regime = "SMALL CAP RISK-ON"
                regime_detail = f"IWM outperforming (IWM {iwm_chg:+.1f}% vs SPY {spy_chg:+.1f}%)"
                strategy_recommendation = "FAVOR: Small cap momentum, speculative names. Higher risk tolerance"
            
            # Choppy/Range day
            elif abs(spy_chg) < 0.3 and abs(qqq_chg) < 0.3:
                regime = "CHOPPY/RANGE DAY"
                regime_detail = "Low directional conviction - indices flat"
                strategy_recommendation = "FAVOR: Mean reversion (Rubber Band), range plays. REDUCE SIZE 50%. AVOID: Breakouts"
            
            # Moderate trend
            elif spy_chg > 0.3:
                regime = "MODERATE UPTREND"
                regime_detail = "Grinding higher - steady buyers"
                strategy_recommendation = "FAVOR: Pullback entries, Second Chance setups. Be patient with breakouts"
            elif spy_chg < -0.3:
                regime = "MODERATE DOWNTREND"
                regime_detail = "Grinding lower - steady selling"
                strategy_recommendation = "FAVOR: Short setups, failed bounces. Avoid catching falling knives"
            else:
                regime = "NEUTRAL/UNDECIDED"
                regime_detail = "Market searching for direction"
                strategy_recommendation = "WAIT for clearer signals. Focus on individual stock setups"
            
            # VIX assessment
            vix_assessment = ""
            if vix_level > 30:
                vix_assessment = f"⚠️ HIGH VOLATILITY (VIX: {vix_level:.1f}) - Reduce position sizes, widen stops"
            elif vix_level > 20:
                vix_assessment = f"⚡ ELEVATED VOL (VIX: {vix_level:.1f}) - Good for scalping, respect stops"
            elif vix_level < 13:
                vix_assessment = f"😴 LOW VOL (VIX: {vix_level:.1f}) - Tight ranges expected, be patient"
            else:
                vix_assessment = f"✅ NORMAL VOL (VIX: {vix_level:.1f}) - Standard conditions"
            
            parts.append("=== MARKET REGIME CLASSIFICATION ===")
            parts.append(f"**{regime}**")
            parts.append(f"Detail: {regime_detail}")
            parts.append(f"VIX: {vix_assessment}")
            parts.append(f"\n📋 Strategy Recommendation: {strategy_recommendation}")
            
            # Add index summary
            parts.append(f"\nIndex Snapshot: SPY {spy_chg:+.2f}% | QQQ {qqq_chg:+.2f}% | IWM {iwm_chg:+.2f}%")
            
        except Exception as e:
            logger.warning(f"Error determining market regime: {e}")
        
        return "\n".join(parts) if parts else ""

    async def _gather_sector_heatmap(self) -> str:
        """Get sector ETF performance for rotation analysis"""
        parts = []
        
        try:
            if not self._alpaca_service:
                return ""
            
            # Key sector ETFs
            sector_etfs = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
            sector_names = {
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
            
            quotes = await self._alpaca_service.get_quotes_batch(sector_etfs)
            if not quotes:
                return ""
            
            # Sort by performance
            sorted_sectors = sorted(quotes, key=lambda x: x.get("change_percent", 0), reverse=True)
            
            parts.append("=== SECTOR PERFORMANCE (Leaders → Laggards) ===")
            
            for i, q in enumerate(sorted_sectors):
                sym = q.get("symbol", "?")
                chg = q.get("change_percent", 0)
                name = sector_names.get(sym, sym)
                
                # Color code
                if chg > 1.0:
                    indicator = "🟢"
                elif chg > 0:
                    indicator = "🔵"
                elif chg > -1.0:
                    indicator = "🟡"
                else:
                    indicator = "🔴"
                
                # Mark top 3 and bottom 3
                position = ""
                if i < 3:
                    position = " ⬆️ LEADING"
                elif i >= len(sorted_sectors) - 3:
                    position = " ⬇️ LAGGING"
                
                parts.append(f"  {indicator} {name} ({sym}): {chg:+.2f}%{position}")
            
        except Exception as e:
            logger.warning(f"Error gathering sector data: {e}")
        
        return "\n".join(parts) if parts else ""

    async def _gather_earnings_context(self) -> str:
        """Flag watchlist stocks with upcoming earnings"""
        parts = []
        
        try:
            # Get watchlist symbols
            watchlist_symbols = set()
            if self._smart_watchlist:
                items = self._smart_watchlist.get_watchlist()
                watchlist_symbols = {item.symbol for item in items}
            
            if not watchlist_symbols:
                watchlist_symbols = {"AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN"}
            
            # Fetch earnings calendar from Finnhub
            if not self._finnhub_key:
                return ""
            
            from_date = datetime.now().strftime("%Y-%m-%d")
            to_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
            
            resp = requests.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": from_date,
                    "to": to_date,
                    "token": self._finnhub_key
                },
                timeout=10
            )
            
            if resp.status_code != 200:
                return ""
            
            data = resp.json()
            earnings_list = data.get("earningsCalendar", [])
            
            # Filter for watchlist stocks
            watchlist_earnings = []
            for e in earnings_list:
                sym = e.get("symbol", "")
                if sym in watchlist_symbols:
                    watchlist_earnings.append({
                        "symbol": sym,
                        "date": e.get("date", ""),
                        "hour": e.get("hour", ""),  # "bmo" or "amc"
                        "eps_estimate": e.get("epsEstimate"),
                        "revenue_estimate": e.get("revenueEstimate")
                    })
            
            if watchlist_earnings:
                parts.append("=== ⚠️ WATCHLIST EARNINGS ALERTS ===")
                for e in watchlist_earnings[:10]:
                    timing = "Before Open" if e["hour"] == "bmo" else "After Close" if e["hour"] == "amc" else ""
                    eps_str = f"EPS Est: ${e['eps_estimate']:.2f}" if e['eps_estimate'] else ""
                    parts.append(f"  📅 {e['symbol']}: {e['date']} {timing} {eps_str}")
                    parts.append("     ⚠️ CAUTION: Avoid new positions or reduce size before earnings!")
            else:
                parts.append("=== EARNINGS ===\nNo watchlist stocks reporting in next 2 weeks")
            
        except Exception as e:
            logger.warning(f"Error gathering earnings context: {e}")
        
        return "\n".join(parts) if parts else ""

    async def _gather_in_play_technical_context(self) -> str:
        """Get detailed technical context for IN PLAY stocks"""
        parts = []
        
        try:
            # Get stocks that are actually in play from scanner
            in_play_symbols = []
            
            if self._scanner_service:
                alerts = self._scanner_service.get_live_alerts()
                if alerts:
                    in_play_symbols = list(set(getattr(a, 'symbol', '') for a in alerts[:10]))
            
            # Also check watchlist for active movers
            if self._smart_watchlist and self._alpaca_service:
                items = self._smart_watchlist.get_watchlist()
                wl_symbols = [item.symbol for item in items[:15]]
                
                if wl_symbols:
                    quotes = await self._alpaca_service.get_quotes_batch(wl_symbols)
                    for q in quotes or []:
                        if abs(q.get("change_percent", 0)) >= 2.0:  # Moving 2%+
                            if q["symbol"] not in in_play_symbols:
                                in_play_symbols.append(q["symbol"])
            
            if not in_play_symbols:
                return ""
            
            parts.append("=== IN-PLAY STOCKS - KEY LEVELS ===")
            parts.append("(Stocks with significant movement today)")
            
            # Get technical data for in-play stocks
            for symbol in in_play_symbols[:6]:  # Limit to 6 for context size
                try:
                    # Get bars data for technical levels
                    bars = await self._alpaca_service.get_bars(symbol, timeframe="1Day", limit=2)
                    if bars and len(bars) >= 1:
                        today_bar = bars[-1] if bars else {}
                        prev_bar = bars[-2] if len(bars) > 1 else {}
                        
                        high = today_bar.get("high", 0)
                        low = today_bar.get("low", 0)
                        close = today_bar.get("close", 0)
                        open_price = today_bar.get("open", 0)
                        volume = today_bar.get("volume", 0)
                        prev_close = prev_bar.get("close", 0) if prev_bar else 0
                        
                        # Calculate key metrics
                        gap_pct = ((open_price - prev_close) / prev_close * 100) if prev_close else 0
                        range_pct = ((high - low) / low * 100) if low else 0
                        
                        # VWAP approximation (simplified: avg of H/L/C)
                        vwap_approx = (high + low + close) / 3 if close else 0
                        
                        parts.append(f"\n**{symbol}**")
                        parts.append(f"  Gap: {gap_pct:+.1f}% | Day Range: {range_pct:.1f}%")
                        parts.append(f"  HOD: ${high:.2f} | LOD: ${low:.2f} | VWAP~: ${vwap_approx:.2f}")
                        parts.append(f"  Volume: {volume:,}")
                        
                        # Add actionable levels
                        if close > vwap_approx:
                            parts.append(f"  📍 Above VWAP - bullish bias. Support at ${vwap_approx:.2f}")
                        else:
                            parts.append(f"  📍 Below VWAP - bearish bias. Resistance at ${vwap_approx:.2f}")
                        
                except Exception as e:
                    logger.debug(f"Error getting technicals for {symbol}: {e}")
                    continue
            
        except Exception as e:
            logger.warning(f"Error gathering in-play technical context: {e}")
        
        return "\n".join(parts) if parts else ""


    # ==================== REPORT GENERATION ====================

    def _get_report_prompt(self, report_type: str, context: str, now_et: datetime) -> str:
        """Get the AI prompt for each report type with strict anti-hallucination rules"""
        current_time_str = now_et.strftime("%I:%M %p ET on %A, %B %d, %Y")

        base_rules = f"""CRITICAL RULES — YOU MUST FOLLOW THESE:
1. The current time is {current_time_str}. Use this as the report timestamp.
2. ONLY reference news headlines, tickers, and data that appear in the DATA CONTEXT below.
3. DO NOT invent, fabricate, or hallucinate any news stories, ticker symbols, prices, or events.
4. If a section has no relevant data, say "No data available for this section" — do NOT make something up.
5. The bot status, positions, and performance data below are EXACT system readings. Report them verbatim.
6. If market data shows $0.00 or 0.00%, the market may be closed. State that clearly.
"""

        prompts = {
            "premarket": f"""{base_rules}

Generate a PRE-MARKET INTELLIGENCE BRIEFING for {current_time_str}.

Cover these sections (skip any with no data, do NOT fabricate):
1. **MARKET REGIME**: What type of day is setting up? Reference the EXACT regime classification
2. **NEWS RECAP**: Summarize ONLY the real headlines from the DATA CONTEXT below
3. **WATCHLIST STATUS**: Which stocks are IN PLAY vs just on watch? Use the smart watchlist data
4. **SECTOR ROTATION**: What sectors are leading/lagging? Use exact sector ETF data
5. **EARNINGS WARNINGS**: Flag any watchlist stocks with upcoming earnings
6. **IN-PLAY STOCKS**: Key levels (HOD, LOD, VWAP) for stocks that are moving
7. **STRATEGY PLAYBOOK**: Based on market regime and learning loop data, recommend strategies
8. **GAME PLAN**: 3-5 bullet points for the day based on all real data

DATA CONTEXT:
{context}""",

            "early_market": f"""{base_rules}

Generate an EARLY MARKET REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET REGIME**: Current day classification and strategy implications
2. **MARKET STATUS**: Report EXACT index prices and changes from data
3. **IN-PLAY STOCKS**: Which watchlist stocks are active with key levels
4. **TICKER-SPECIFIC NEWS**: What headlines are driving individual stocks?
5. **SECTOR ROTATION**: Which sectors leading/lagging
6. **BOT ACTIVITY**: Report the EXACT bot status from the data below — do not guess
7. **STRATEGY PERFORMANCE**: Use EXACT numbers from learning loop data
8. **SETUPS**: Based on scanner alerts and in-play stocks
9. **UPDATED PLAYBOOK**: Adjustments based on market regime

DATA CONTEXT:
{context}""",

            "midday": f"""{base_rules}

Generate a MIDDAY MARKET REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET REGIME UPDATE**: Has the day type changed? Trend/chop/rotation?
2. **MARKET STATUS**: EXACT index prices and direction from data
3. **P&L UPDATE**: EXACT bot stats and position data — report verbatim
4. **IN-PLAY STOCKS**: Which are still moving, key levels update
5. **STRATEGY SCORECARD**: EXACT performance numbers from learning loop
6. **SECTOR UPDATE**: Rotation shifts since open
7. **TICKER NEWS**: Any new headlines for watchlist stocks
8. **AFTERNOON OUTLOOK**: Based on market regime and momentum
9. **POSITION MANAGEMENT**: Based on EXACT open positions

DATA CONTEXT:
{context}""",

            "power_hour": f"""{base_rules}

Generate a POWER HOUR REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET REGIME**: Final hour classification - trend continuation or reversal likely?
2. **MARKET POSITIONING**: EXACT index levels heading into close
3. **IN-PLAY STOCKS**: End of day levels and expectations
4. **EOD STRATEGY**: Based on market regime and strategy performance data
5. **POSITION REVIEW**: EXACT open positions — close vs hold recommendations
6. **TOMORROW SETUP**: Earnings warnings for next day
7. **BOT EOD SETTINGS**: Read EXACT EOD close settings from strategy configs
8. **KEY LEVELS**: From EXACT market data
9. **ACTION ITEMS**: 3-5 specific actions based on real data

DATA CONTEXT:
{context}""",

            "post_market": f"""{base_rules}

Generate a POST-MARKET WRAP REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET CLOSE**: EXACT final index prices from data
2. **P&L RECAP**: EXACT bot P&L and position data — report verbatim
3. **TRADE REVIEW**: EXACT trades from bot data (if any)
4. **STRATEGY PERFORMANCE**: EXACT numbers from learning loop
5. **NEWS RECAP**: Key headlines from real news data
6. **TOMORROW PREP**: Based on real news and strategy performance
7. **LEARNING**: One specific insight from EXACT data

DATA CONTEXT:
{context}"""
        }
        return prompts.get(report_type, prompts["premarket"])

    async def generate_report(self, report_type: str, force: bool = False) -> Dict:
        """Generate a specific market intel report"""
        if not self._ai_assistant:
            return {"success": False, "error": "AI assistant not connected"}

        # Check if we already generated this report today (unless forced)
        if not force:
            existing = self._get_todays_report(report_type)
            if existing:
                return {"success": True, "report": existing, "cached": True}

        # Get current time
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))

        # Gather context from all real sources (ENHANCED with new sources)
        context_parts = []

        # 1. Market regime classification (NEW - determines day type)
        regime_ctx = await self._gather_market_regime_context()
        if regime_ctx:
            context_parts.append(regime_ctx)

        # 2. General news context
        news_ctx = await self._gather_news_context()
        context_parts.append(news_ctx)

        # 3. Market indices data
        market_ctx = await self._gather_market_data_context()
        context_parts.append(market_ctx)

        # 4. Smart Watchlist with IN PLAY status (ENHANCED)
        watchlist_ctx = await self._gather_watchlist_context()
        if watchlist_ctx:
            context_parts.append(watchlist_ctx)

        # 5. Ticker-specific news for watchlist stocks (NEW)
        ticker_news_ctx = await self._gather_ticker_specific_news()
        if ticker_news_ctx:
            context_parts.append(ticker_news_ctx)

        # 6. In-play stocks technical levels (NEW)
        in_play_ctx = await self._gather_in_play_technical_context()
        if in_play_ctx:
            context_parts.append(in_play_ctx)

        # 7. Sector heatmap (NEW)
        sector_ctx = await self._gather_sector_heatmap()
        if sector_ctx:
            context_parts.append(sector_ctx)

        # 8. Earnings calendar for watchlist (NEW)
        earnings_ctx = await self._gather_earnings_context()
        if earnings_ctx:
            context_parts.append(earnings_ctx)

        # 9. Positions context
        positions_ctx = await self._gather_positions_context()
        context_parts.append(positions_ctx)

        # 10. Bot status
        bot_ctx = self._gather_bot_context()
        context_parts.append(bot_ctx)

        # 11. Learning loop performance
        learning_ctx = self._gather_learning_context()
        context_parts.append(learning_ctx)

        # 12. Scanner alerts
        scanner_ctx = await self._gather_scanner_context()
        if scanner_ctx:
            context_parts.append(scanner_ctx)

        full_context = "\n\n".join(filter(None, context_parts))

        # Get time-specific prompt with anti-hallucination rules
        prompt = self._get_report_prompt(report_type, full_context, now_et)

        try:
            messages = [{"role": "user", "content": prompt}]
            report_text = await self._ai_assistant._call_llm(messages, "")

            # Find label for this report type
            label = report_type.replace("_", " ").title()
            icon = "file-text"
            for sched in REPORT_SCHEDULE:
                if sched["type"] == report_type:
                    label = sched["label"]
                    icon = sched["icon"]
                    break

            report = {
                "type": report_type,
                "label": label,
                "icon": icon,
                "content": report_text,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_at_et": now_et.strftime("%I:%M %p ET"),
                "date": now_et.strftime("%Y-%m-%d"),
            }

            # Save to DB
            self._save_report(report)

            return {"success": True, "report": report, "cached": False}

        except Exception as e:
            logger.error(f"Error generating {report_type} report: {e}")
            return {"success": False, "error": str(e)}

    # ==================== DB OPERATIONS ====================

    def _save_report(self, report: Dict):
        if self._db is None:
            return
        try:
            col = self._db["market_intel_reports"]
            col.insert_one({**report, "_saved_at": datetime.now(timezone.utc).isoformat()})
        except Exception as e:
            logger.error(f"Error saving report: {e}")

    def _get_todays_report(self, report_type: str) -> Optional[Dict]:
        if self._db is None:
            return None
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        try:
            col = self._db["market_intel_reports"]
            doc = col.find_one(
                {"type": report_type, "date": today},
                {"_id": 0},
                sort=[("generated_at", -1)]
            )
            return doc
        except Exception as e:
            logger.error(f"Error fetching report: {e}")
            return None

    def get_todays_reports(self) -> List[Dict]:
        """Get all reports generated today"""
        if self._db is None:
            return []
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        try:
            col = self._db["market_intel_reports"]
            docs = list(col.find({"date": today}, {"_id": 0}).sort("generated_at", 1))
            return docs
        except Exception as e:
            logger.error(f"Error fetching reports: {e}")
            return []

    def get_current_report(self) -> Optional[Dict]:
        """Get the most relevant report based on current time"""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))

        current_minutes = now_et.hour * 60 + now_et.minute

        applicable_type = None
        for sched in reversed(REPORT_SCHEDULE):
            sched_minutes = sched["hour"] * 60 + sched["minute"]
            if current_minutes >= sched_minutes:
                applicable_type = sched["type"]
                break

        if applicable_type:
            report = self._get_todays_report(applicable_type)
            if report:
                return report

        reports = self.get_todays_reports()
        return reports[-1] if reports else None

    def get_schedule_status(self) -> List[Dict]:
        """Get schedule with generation status for today"""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))
        current_minutes = now_et.hour * 60 + now_et.minute
        today_reports = {r["type"]: r for r in self.get_todays_reports()}

        status = []
        for sched in REPORT_SCHEDULE:
            sched_minutes = sched["hour"] * 60 + sched["minute"]
            report = today_reports.get(sched["type"])
            status.append({
                "type": sched["type"],
                "label": sched["label"],
                "icon": sched["icon"],
                "scheduled_time": f"{sched['hour']}:{sched['minute']:02d}",
                "is_past": current_minutes >= sched_minutes,
                "is_current": applicable_report_type(current_minutes) == sched["type"],
                "generated": report is not None,
                "generated_at": report.get("generated_at_et") if report else None,
            })
        return status

    # ==================== SCHEDULER ====================

    async def start_scheduler(self):
        """Start the auto-generation scheduler"""
        self._scheduler_running = True
        logger.info("Market intel scheduler started")

        triggered_today = set()

        while self._scheduler_running:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo

            now_et = datetime.now(ZoneInfo("America/New_York"))
            today_key = now_et.strftime("%Y-%m-%d")

            if not any(today_key in t for t in triggered_today):
                triggered_today.clear()

            if now_et.weekday() < 5:
                for sched in REPORT_SCHEDULE:
                    trigger_key = f"{today_key}_{sched['type']}"
                    if trigger_key in triggered_today:
                        continue

                    if now_et.hour == sched["hour"] and sched["minute"] <= now_et.minute <= sched["minute"] + 1:
                        logger.info(f"Auto-generating {sched['label']}...")
                        triggered_today.add(trigger_key)
                        try:
                            result = await self.generate_report(sched["type"], force=True)
                            if result.get("success"):
                                logger.info(f"{sched['label']} generated successfully")
                            else:
                                logger.error(f"Failed to generate {sched['label']}: {result.get('error')}")
                        except Exception as e:
                            logger.error(f"Error in auto-generation of {sched['label']}: {e}")

            await asyncio.sleep(30)

    def stop_scheduler(self):
        self._scheduler_running = False


def applicable_report_type(current_minutes: int) -> Optional[str]:
    """Determine which report type is current based on time"""
    result = None
    for sched in REPORT_SCHEDULE:
        sched_minutes = sched["hour"] * 60 + sched["minute"]
        if current_minutes >= sched_minutes:
            result = sched["type"]
    return result


# Singleton
_intel_service = None

def get_market_intel_service():
    global _intel_service
    if _intel_service is None:
        _intel_service = MarketIntelService()
    return _intel_service
