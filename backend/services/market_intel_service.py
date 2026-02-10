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
        self._scheduler_running = False
        self._finnhub_key = os.environ.get("FINNHUB_API_KEY", "")

    def set_services(self, ai_assistant=None, trading_bot=None, perf_service=None,
                     alpaca_service=None, news_service=None, scanner_service=None):
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
                    for q in quotes:
                        sym = q.get("symbol", "?")
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
                recent = self._scanner_service.get_recent_signals(limit=10)
                if recent:
                    parts.append("=== SCANNER SIGNALS (EXACT recent scanner results) ===")
                    for sig in recent:
                        sym = sig.get("symbol", "?")
                        strategy = sig.get("strategy", "?")
                        grade = sig.get("grade", "?")
                        price = sig.get("price", 0)
                        parts.append(f"  {sym}: {strategy} signal (Grade {grade}) @ ${price:.2f}")
                else:
                    parts.append("=== SCANNER SIGNALS ===\nNo recent signals")
            except Exception as e:
                logger.warning(f"Error gathering scanner data: {e}")
        return "\n".join(parts) if parts else ""

    async def _gather_watchlist_context(self) -> str:
        """Gather watchlist quotes"""
        parts = []
        try:
            if self._alpaca_service:
                # Default watchlist tickers
                watchlist_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "GOOGL", "AMZN"]
                quotes = await self._alpaca_service.get_quotes_batch(watchlist_symbols)
                if quotes:
                    parts.append("=== WATCHLIST QUOTES (EXACT live prices) ===")
                    for q in quotes:
                        sym = q.get("symbol", "?")
                        price = q.get("price", 0)
                        chg = q.get("change_percent", 0)
                        vol = q.get("volume", 0)
                        parts.append(f"  {sym}: ${price:.2f} ({chg:+.2f}%) vol: {vol:,}")
        except Exception as e:
            logger.warning(f"Error gathering watchlist: {e}")
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
1. **NEWS RECAP**: Summarize ONLY the real headlines from the DATA CONTEXT below
2. **EARNINGS & ANALYST ACTIONS**: ONLY mention if found in the news data
3. **MARKET LEVELS**: Reference the EXACT index prices from the data
4. **STRATEGY PLAYBOOK**: Based on the EXACT learning loop data, recommend strategies
5. **RISK WARNINGS**: Based ONLY on real news headlines
6. **GAME PLAN**: 3-5 bullet points for the day

DATA CONTEXT:
{context}""",

            "early_market": f"""{base_rules}

Generate an EARLY MARKET REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET STATUS**: Report EXACT index prices and changes from data
2. **NEWS MOVERS**: Summarize ONLY real headlines that mention specific stocks
3. **BOT ACTIVITY**: Report the EXACT bot status from the data below — do not guess
4. **STRATEGY PERFORMANCE**: Use EXACT numbers from learning loop data
5. **SETUPS**: Based on real market data and strategy configs
6. **UPDATED PLAYBOOK**: Adjustments based on real data

DATA CONTEXT:
{context}""",

            "midday": f"""{base_rules}

Generate a MIDDAY MARKET REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET STATUS**: EXACT index prices and direction from data
2. **P&L UPDATE**: EXACT bot stats and position data — report verbatim
3. **STRATEGY SCORECARD**: EXACT performance numbers from learning loop
4. **NEWS UPDATE**: Only real headlines from data
5. **AFTERNOON OUTLOOK**: Based on real market data and strategy performance
6. **POSITION MANAGEMENT**: Based on EXACT open positions

DATA CONTEXT:
{context}""",

            "power_hour": f"""{base_rules}

Generate a POWER HOUR REPORT for {current_time_str}.

Cover (using ONLY real data below):
1. **MARKET POSITIONING**: EXACT index levels heading into close
2. **EOD STRATEGY**: Based on real strategy configs and performance data
3. **POSITION REVIEW**: EXACT open positions — close vs hold recommendations
4. **BOT EOD SETTINGS**: Read EXACT EOD close settings from strategy configs
5. **KEY LEVELS**: From EXACT market data
6. **ACTION ITEMS**: 3-5 specific actions based on real data

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

        # Gather context from all real sources
        context_parts = []

        news_ctx = await self._gather_news_context()
        context_parts.append(news_ctx)

        market_ctx = await self._gather_market_data_context()
        context_parts.append(market_ctx)

        watchlist_ctx = await self._gather_watchlist_context()
        if watchlist_ctx:
            context_parts.append(watchlist_ctx)

        positions_ctx = await self._gather_positions_context()
        context_parts.append(positions_ctx)

        bot_ctx = self._gather_bot_context()
        context_parts.append(bot_ctx)

        learning_ctx = self._gather_learning_context()
        context_parts.append(learning_ctx)

        scanner_ctx = await self._gather_scanner_context()
        if scanner_ctx:
            context_parts.append(scanner_ctx)

        full_context = "\n\n".join(context_parts)

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
