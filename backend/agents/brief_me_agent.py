"""
BriefMeAgent - Generates personalized market briefings
=====================================================

Aggregates data from multiple services to create a personalized
market report tailored to the user's trading style and current conditions.

Features:
- Quick summary (2-3 sentences)
- Detailed report with sections
- Pre-market gappers & overnight movers
- Key market levels (SPY, QQQ, VIX)
- Personalized insights based on learning data
- Top opportunities ranked by relevance
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import asyncio
import aiohttp

logger = logging.getLogger(__name__)


class BriefMeAgent:
    """Agent that generates personalized market briefings."""
    
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
    
    def inject_services(
        self,
        market_intel_service=None,
        context_service=None,
        learning_provider=None,
        trading_bot=None,
        scanner_service=None,
        regime_performance_service=None,
        alpaca_service=None,
        ib_pushed_data=None
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
        """Gather data from all services in parallel."""
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
            "index_status": {}
        }
        
        # Gather everything in parallel
        tasks = []
        
        # Market regime data
        if self.context_service:
            tasks.append(self._fetch_regime_data(data))
        
        # Session data
        if self.context_service:
            tasks.append(self._fetch_session_data(data))
        
        # Bot status
        if self.trading_bot:
            tasks.append(self._fetch_bot_status(data))
        
        # Learning insights
        if self.learning_provider:
            tasks.append(self._fetch_learning_data(data))
        
        # Regime performance
        if self.regime_performance_service:
            tasks.append(self._fetch_regime_performance(data))
        
        # Scanner opportunities
        if self.scanner_service:
            tasks.append(self._fetch_scanner_alerts(data))
        
        # Pre-market/gapper data from Alpaca
        if self.alpaca_service:
            tasks.append(self._fetch_premarket_data(data))
        
        # Real-time IB data (index quotes, VIX, etc.) - always try
        tasks.append(self._fetch_ib_realtime_data(data))
        
        # Run all tasks
        await asyncio.gather(*tasks, return_exceptions=True)
        
        return data
    
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
                self.scanner_service.get_all_alerts
            )
            top_alerts = sorted(
                [a for a in alerts if a.get("tqs_score", 0) >= 60],
                key=lambda x: x.get("tqs_score", 0),
                reverse=True
            )[:5]
            data["opportunities"] = top_alerts
        except Exception as e:
            logger.warning(f"Failed to get scanner alerts: {e}")
    
    async def _fetch_premarket_data(self, data: Dict):
        """Fetch pre-market gappers and movers from Alpaca."""
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
                    quote = await asyncio.to_thread(
                        self.alpaca_service.get_latest_quote, symbol
                    )
                    bars = await asyncio.to_thread(
                        self.alpaca_service.get_historical_bars, symbol, 2
                    )
                    
                    if quote and bars is not None and len(bars) >= 2:
                        current_price = quote.get("price", 0)
                        prev_close = bars.iloc[-2]["close"] if len(bars) >= 2 else current_price
                        
                        if prev_close > 0:
                            gap_pct = ((current_price - prev_close) / prev_close) * 100
                            
                            item = {
                                "symbol": symbol,
                                "price": current_price,
                                "prev_close": prev_close,
                                "gap_pct": round(gap_pct, 2),
                                "gap_dollars": round(current_price - prev_close, 2)
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
            ]
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
        """Generate a quick 2-3 sentence summary."""
        market = brief.get("market_summary", {})
        bot = brief.get("your_bot", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        
        # Build quick summary without LLM for speed
        regime = market.get("regime", "HOLD")
        regime_label = market.get("regime_label", "Neutral")
        session = market.get("session", "")
        position_mult = market.get("position_multiplier", 1.0)
        
        # Bot status
        bot_state = "actively hunting" if bot.get("running") else "paused"
        today_pnl = bot.get("today_pnl", 0)
        pnl_text = f"+${today_pnl:.0f}" if today_pnl >= 0 else f"-${abs(today_pnl):.0f}"
        
        # Best opportunity
        top_opp = opportunities[0] if opportunities else None
        opp_text = ""
        if top_opp:
            opp_text = f" Top opportunity: {top_opp['symbol']} {top_opp['setup']} (TQS {top_opp['tqs']})."
        
        # Best setup for regime
        best_setup = insights.get("best_setup_for_regime")
        win_rate = insights.get("win_rate_in_regime")
        setup_text = ""
        if best_setup and win_rate:
            setup_text = f" Your best setup in {regime} is {best_setup.replace('_', ' ').title()} ({win_rate:.0f}% win rate)."
        
        # Position sizing recommendation
        sizing_text = ""
        if position_mult < 1.0:
            sizing_text = f" Consider reducing position size to {position_mult*100:.0f}%."
        
        summary = f"Market is {regime_label} ({session}). Your bot is {bot_state} with {pnl_text} today."
        summary += setup_text + opp_text + sizing_text
        
        return summary.strip()
    
    async def _generate_detailed_summary(self, brief: Dict, rich_intel: Dict = None) -> Dict[str, str]:
        """Generate a detailed multi-section summary."""
        market = brief.get("market_summary", {})
        bot = brief.get("your_bot", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        index_status = brief.get("index_status", {})
        gappers = brief.get("gappers", {"up": [], "down": []})
        
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
        
        # Build Market Overview with Index Status if not already set
        if "market_overview" not in sections:
            regime = market.get("regime", "HOLD")
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
        
        # Recommendation
        recommendation = self._generate_recommendation(brief)
        sections["recommendation"] = f"**💡 Recommendation:**\n\n{recommendation}"
        
        return sections
    
    def _generate_recommendation(self, brief: Dict) -> str:
        """Generate a trading recommendation based on the brief."""
        market = brief.get("market_summary", {})
        insights = brief.get("personalized_insights", {})
        opportunities = brief.get("opportunities", [])
        
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
        
        # Setup advice
        if best_setup:
            rec_parts.append(f"Focus on {best_setup.replace('_', ' ').title()} setups - they've worked well for you in similar conditions.")
        
        # Opportunity highlight
        if opportunities:
            top = opportunities[0]
            rec_parts.append(f"Watch {top['symbol']} for a {top['setup']} entry.")
        
        # Position sizing
        if position_mult < 1.0:
            rec_parts.append(f"Keep position sizes at {position_mult*100:.0f}% of normal.")
        
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
                    "You are a trading assistant providing personalized market briefings. "
                    "Be concise, specific with numbers, and use second person ('You should...', 'Your bot...'). "
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
        
        prompt = f"""Generate a personalized market briefing based on this data:

MARKET CONDITIONS:
- Regime: {market.get('regime', 'HOLD')} (Score: {market.get('regime_score', 50)}/100)
- Session: {market.get('session', 'Unknown')}
- Position Sizing: {market.get('position_multiplier', 1.0) * 100:.0f}%

USER'S BOT:
- State: {'Running' if bot.get('running') else 'Paused'}
- Today's P&L: ${bot.get('today_pnl', 0):.2f}
- Trades Today: {bot.get('trades_today', 0)}
- Open Positions: {len(bot.get('open_positions', []))}

USER'S BEST SETUP FOR THIS REGIME: {insights.get('best_setup_for_regime', 'Not enough data')}
WIN RATE IN THIS REGIME: {insights.get('win_rate_in_regime', 'N/A')}

TOP OPPORTUNITIES:
{self._format_opportunities(opportunities)}

Generate a 4-section briefing:
1. Market Overview (2-3 sentences)
2. Your Bot Status (current state + positions)
3. Personalized Insights (what works for YOU)
4. Recommendation (1-2 actionable sentences)
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
