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
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
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
        self._scheduler_running = False

    def set_services(self, ai_assistant=None, trading_bot=None, perf_service=None,
                     alpaca_service=None, news_service=None):
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
        logger.info("Market intel service wired")

    # ==================== CONTEXT GATHERING ====================

    async def _gather_news_context(self) -> str:
        """Gather news, earnings, upgrades/downgrades"""
        parts = []
        try:
            if self._news_service:
                summary = await self._news_service.get_market_summary()
                if summary.get("available"):
                    parts.append("=== MARKET NEWS ===")
                    parts.append(f"Sentiment: {summary.get('overall_sentiment', 'N/A').upper()}")
                    themes = summary.get("themes", [])
                    if themes:
                        parts.append(f"Themes: {', '.join(themes)}")
                    for i, h in enumerate(summary.get("headlines", [])[:10], 1):
                        parts.append(f"  {i}. {h}")
                    sb = summary.get("sentiment_breakdown", {})
                    parts.append(f"Breakdown: {sb.get('bullish',0)} bullish, {sb.get('bearish',0)} bearish, {sb.get('neutral',0)} neutral")
        except Exception as e:
            logger.warning(f"Error gathering news: {e}")
            parts.append("News data unavailable")

        # Earnings calendar
        try:
            if self._alpaca_service:
                from services.alpaca_service import get_alpaca_service
                svc = get_alpaca_service()
                # Try to get recent news with earnings/upgrade focus
                news = await svc.get_news(limit=15)
                earnings_news = [n for n in (news or []) if any(kw in (n.get("headline","") + n.get("summary","")).lower() for kw in ["earnings", "beat", "miss", "revenue", "eps", "guidance", "upgrade", "downgrade", "outperform", "underperform", "price target"])]
                if earnings_news:
                    parts.append("\n=== EARNINGS & ANALYST ACTIONS ===")
                    for n in earnings_news[:8]:
                        parts.append(f"  - {n.get('headline','')}")
        except Exception as e:
            logger.warning(f"Error gathering earnings/analyst news: {e}")

        return "\n".join(parts) if parts else "No news data available"

    def _gather_bot_context(self) -> str:
        """Gather trading bot status and trades"""
        if not self._trading_bot:
            return "Trading bot not connected"
        try:
            return self._trading_bot.get_bot_context_for_ai()
        except Exception as e:
            logger.warning(f"Error getting bot context: {e}")
            return "Bot context unavailable"

    def _gather_learning_context(self) -> str:
        """Gather strategy performance data"""
        if not self._perf_service:
            return "Learning loop not connected"
        try:
            return self._perf_service.get_learning_summary_for_ai()
        except Exception as e:
            logger.warning(f"Error getting learning context: {e}")
            return "Performance data unavailable"

    async def _gather_positions_context(self) -> str:
        """Gather current positions and P&L"""
        parts = []
        try:
            if self._alpaca_service:
                account = await self._alpaca_service.get_account()
                positions = await self._alpaca_service.get_positions()
                if account:
                    parts.append("=== ACCOUNT STATUS ===")
                    parts.append(f"Equity: ${float(account.get('equity', 0)):,.2f}")
                    parts.append(f"Day P&L: ${float(account.get('unrealized_pl', 0)):,.2f}")
                    parts.append(f"Buying Power: ${float(account.get('buying_power', 0)):,.2f}")
                if positions:
                    parts.append(f"\nOPEN POSITIONS ({len(positions)}):")
                    for p in positions[:10]:
                        sym = p.get("symbol", "?")
                        qty = p.get("qty", 0)
                        pnl = float(p.get("unrealized_pl", 0))
                        pnl_pct = float(p.get("unrealized_plpc", 0)) * 100
                        parts.append(f"  {sym}: {qty} sh | P&L: ${pnl:,.2f} ({pnl_pct:+.1f}%)")
        except Exception as e:
            logger.warning(f"Error gathering positions: {e}")
        return "\n".join(parts) if parts else "Position data unavailable"

    async def _gather_market_data_context(self) -> str:
        """Gather market index data"""
        parts = []
        try:
            if self._alpaca_service:
                quotes = await self._alpaca_service.get_quotes_batch(["SPY", "QQQ", "IWM", "DIA", "VIX"])
                if quotes:
                    parts.append("=== MARKET INDICES ===")
                    for q in quotes:
                        sym = q.get("symbol", "?")
                        price = q.get("price", 0)
                        chg = q.get("change_percent", 0)
                        parts.append(f"  {sym}: ${price:.2f} ({chg:+.2f}%)")
        except Exception as e:
            logger.warning(f"Error gathering market data: {e}")
        return "\n".join(parts) if parts else "Market data unavailable"

    # ==================== REPORT GENERATION ====================

    def _get_report_prompt(self, report_type: str, context: str) -> str:
        """Get the AI prompt for each report type"""
        prompts = {
            "premarket": f"""Generate a PRE-MARKET INTELLIGENCE BRIEFING (8:30 AM ET).

You are a senior trading coach preparing your trader for the day ahead. Cover:

1. **OVERNIGHT RECAP**: Key overnight developments, futures direction, Asia/Europe session summary
2. **EARNINGS & CATALYSTS**: Any earnings releases (beats/misses), analyst upgrades/downgrades, price target changes
3. **PRE-MARKET MOVERS**: Notable pre-market gainers/losers and why
4. **KEY LEVELS**: Important support/resistance levels for major indices (SPY, QQQ)
5. **STRATEGY PLAYBOOK**: Based on market conditions and the learning loop data, recommend:
   - Which strategies to favor today (e.g., "Momentum strategies favored" or "Mean reversion day")
   - Time-of-day strategy recommendations
   - Position sizing guidance (normal, reduced, or aggressive)
   - Specific setups to watch for
6. **RISK WARNINGS**: Any macro risks, economic data releases, Fed speakers, or events to watch
7. **GAME PLAN**: 3-5 bullet point action plan for the day

DATA CONTEXT:
{context}

Format with clear sections using ** for headers. Be specific and actionable. Keep it concise but comprehensive.""",

            "early_market": f"""Generate an EARLY MARKET REPORT (10:30 AM ET, first hour of trading complete).

Cover:
1. **FIRST HOUR RECAP**: How did the open play out? Gap fills? Failed gaps? Volume trends?
2. **KEY MOVERS**: Top 3-5 stocks making significant moves and why
3. **BOT ACTIVITY**: How is the trading bot performing so far today? Any trades taken?
4. **STRATEGY PERFORMANCE**: Which strategies are working/not working in today's conditions?
5. **EMERGING SETUPS**: Patterns forming for the rest of the morning session (10:00-11:30 is prime time)
6. **UPDATED PLAYBOOK**: Any adjustments to the morning playbook based on first hour action
7. **RISK UPDATE**: Any new developments or risks

DATA CONTEXT:
{context}

Be specific about what's changed since pre-market. Reference actual data.""",

            "midday": f"""Generate a MIDDAY MARKET REPORT (2:00 PM ET).

Cover:
1. **DAY PROGRESS**: Market trend, breadth, sector rotation
2. **P&L UPDATE**: Bot and position performance so far
3. **STRATEGY SCORECARD**: Which strategies have worked/failed today with specifics
4. **AFTERNOON OUTLOOK**: Expected market behavior for the afternoon session
5. **POSITION MANAGEMENT**: Should any positions be trimmed, added to, or closed?
6. **MIDDAY RULES REMINDER**: Remind about midday rules (reduce size 50%, mean reversion only 11:30-1:30)
7. **SETUPS FOR AFTERNOON**: What to watch for in the 1:30-3:00 PM window

DATA CONTEXT:
{context}

Focus on what's actionable for the afternoon. Reference bot performance data.""",

            "power_hour": f"""Generate a POWER HOUR REPORT (2:30 PM ET, preparing for last 1.5 hours).

Cover:
1. **CLOSING SETUP**: Market positioning heading into the close
2. **EOD STRATEGY**: Which strategies work in the 3:00-4:00 window (HOD Breakout, Time-of-Day Fade)
3. **POSITION REVIEW**: Which positions to close vs. hold overnight?
4. **BOT EOD SETTINGS**: Reminder about EOD auto-close settings, any trades that should be manually managed
5. **KEY LEVELS TO WATCH**: Critical levels for the final push
6. **MOMENTUM ASSESSMENT**: Is there late-day momentum building or fading?
7. **ACTION ITEMS**: Specific 3-5 things to do before 4:00 PM

DATA CONTEXT:
{context}

Be decisive and action-oriented. This is about executing, not analyzing.""",

            "post_market": f"""Generate a POST-MARKET WRAP REPORT (4:30 PM ET).

Cover:
1. **DAY SUMMARY**: How did the market close? Final moves, closing stats
2. **P&L RECAP**: Full day P&L for bot and manual positions
3. **TRADE REVIEW**: Key trades of the day - what worked, what didn't, and why
4. **STRATEGY PERFORMANCE**: Which strategies performed best/worst today
5. **LEARNING INSIGHTS**: What did we learn today? Any patterns to note?
6. **TOMORROW PREPARATION**: After-hours earnings, events, or developments to watch overnight
7. **SELF-IMPROVEMENT**: One specific thing to improve tomorrow based on today's performance

DATA CONTEXT:
{context}

Be reflective and educational. Help the trader learn from the day."""
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

        # Gather context from all sources
        context_parts = []

        news_ctx = await self._gather_news_context()
        context_parts.append(news_ctx)

        market_ctx = await self._gather_market_data_context()
        context_parts.append(market_ctx)

        positions_ctx = await self._gather_positions_context()
        context_parts.append(positions_ctx)

        bot_ctx = self._gather_bot_context()
        context_parts.append(bot_ctx)

        learning_ctx = self._gather_learning_context()
        context_parts.append(learning_ctx)

        full_context = "\n\n".join(context_parts)

        # Get time-specific prompt
        prompt = self._get_report_prompt(report_type, full_context)

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

            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo

            now_et = datetime.now(ZoneInfo("America/New_York"))

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
        today = now_et.strftime("%Y-%m-%d")

        # Find the most recent report that should exist by now
        current_minutes = now_et.hour * 60 + now_et.minute

        # Go through schedule in reverse to find latest applicable
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

        # Fallback: return any report from today
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
        logger.info("Market intel scheduler started - reports will auto-generate at scheduled times")

        triggered_today = set()

        while self._scheduler_running:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo

            now_et = datetime.now(ZoneInfo("America/New_York"))
            today_key = now_et.strftime("%Y-%m-%d")

            # Reset triggered set at midnight
            if not any(today_key in t for t in triggered_today):
                triggered_today.clear()

            # Only run on weekdays
            if now_et.weekday() < 5:
                for sched in REPORT_SCHEDULE:
                    trigger_key = f"{today_key}_{sched['type']}"
                    if trigger_key in triggered_today:
                        continue

                    # Check if it's time (within a 2-minute window)
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
