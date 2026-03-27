"""
Trade Intelligence — Extracted from trading_bot_service.py

Gathers and analyzes multi-source intelligence for trade evaluation:
- News sentiment (IB news → Tavily fallback)
- Technical analysis (snapshot-based)
- Quality metrics (fundamental)
- Entry context snapshots for post-trade learning
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TradeIntelligence:
    """Gathers comprehensive intelligence for trade evaluation."""

    def __init__(self, web_research=None, technical_service=None, quality_service=None):
        self._web_research = web_research
        self._technical_service = technical_service
        self._quality_service = quality_service

    def set_services(self, web_research=None, technical_service=None, quality_service=None):
        if web_research is not None:
            self._web_research = web_research
        if technical_service is not None:
            self._technical_service = technical_service
        if quality_service is not None:
            self._quality_service = quality_service

    async def gather(self, symbol: str, alert: Dict) -> Dict[str, Any]:
        """Gather comprehensive intelligence for trade evaluation."""
        intelligence = {
            "symbol": symbol,
            "gathered_at": datetime.now(timezone.utc).isoformat(),
            "news": None,
            "technicals": None,
            "market_context": None,
            "quality_metrics": None,
            "warnings": [],
            "enhancements": [],
        }

        try:
            tasks = []

            if self._web_research:
                tasks.append(self._get_news_intelligence(symbol))
            else:
                tasks.append(asyncio.coroutine(lambda: None)())

            if self._technical_service:
                tasks.append(self._get_technical_intelligence(symbol))
            else:
                tasks.append(asyncio.coroutine(lambda: None)())

            if self._quality_service:
                tasks.append(self._get_quality_intelligence(symbol))
            else:
                tasks.append(asyncio.coroutine(lambda: None)())

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=10.0,
                )

                if len(results) > 0 and results[0] and not isinstance(results[0], Exception):
                    intelligence["news"] = results[0]
                if len(results) > 1 and results[1] and not isinstance(results[1], Exception):
                    intelligence["technicals"] = results[1]
                if len(results) > 2 and results[2] and not isinstance(results[2], Exception):
                    intelligence["quality_metrics"] = results[2]

            except asyncio.TimeoutError:
                intelligence["warnings"].append("Intelligence gathering timed out - proceeding with basic data")
                logger.warning(f"Intelligence gathering timeout for {symbol}")

            self.analyze(intelligence, alert)

        except Exception as e:
            logger.error(f"Intelligence gathering error for {symbol}: {e}")
            intelligence["warnings"].append(f"Error gathering intelligence: {str(e)}")

        return intelligence

    async def _get_news_intelligence(self, symbol: str) -> Optional[Dict]:
        """Get recent news that could impact the trade — prioritizes IB news."""
        try:
            try:
                from services.news_service import get_news_service
                news_service = get_news_service()
                news_items = await news_service.get_ticker_news(symbol, max_items=5)

                if news_items and not news_items[0].get("is_placeholder"):
                    headlines = [n.get("headline", "") for n in news_items]
                    sentiments = [n.get("sentiment", "neutral") for n in news_items]
                    bullish = sentiments.count("bullish")
                    bearish = sentiments.count("bearish")

                    if bullish > bearish:
                        overall_sentiment = "bullish"
                    elif bearish > bullish:
                        overall_sentiment = "bearish"
                    else:
                        overall_sentiment = "neutral"

                    return {
                        "has_news": True,
                        "summary": f"Found {len(news_items)} recent news items for {symbol}",
                        "headlines": headlines[:5],
                        "sentiment": overall_sentiment,
                        "source": news_items[0].get("source_type", "unknown"),
                        "key_topics": [],
                    }
            except Exception as e:
                logger.debug(f"News service failed, falling back to Tavily: {e}")

            result = await self._web_research.tavily.search_financial(
                f"{symbol} stock news latest", max_results=3,
            )

            return {
                "has_news": len(result.results) > 0,
                "summary": result.answer[:500] if result.answer else None,
                "headlines": [r.title for r in result.results[:3]],
                "sentiment": self._analyze_news_sentiment(result),
                "key_topics": self._extract_news_topics(result),
                "source": "tavily",
            }

        except Exception as e:
            logger.warning(f"News intelligence error for {symbol}: {e}")
            return None

    async def _get_technical_intelligence(self, symbol: str) -> Optional[Dict]:
        """Get real-time technical analysis."""
        try:
            snapshot = await self._technical_service.get_technical_snapshot(symbol)
            if not snapshot:
                return None

            volume_trend = "normal"
            if snapshot.rvol >= 2.0:
                volume_trend = "high"
            elif snapshot.rvol < 0.5:
                volume_trend = "low"

            signals = []
            if snapshot.above_vwap and snapshot.above_ema9:
                signals.append("bullish_structure")
            if snapshot.rsi_14 > 70:
                signals.append("overbought")
            elif snapshot.rsi_14 < 30:
                signals.append("oversold")
            if snapshot.extended_from_ema9:
                signals.append("extended")
            if snapshot.holding_gap:
                signals.append("gap_hold")

            return {
                "trend": snapshot.trend or "neutral",
                "momentum": snapshot.rsi_14 or 50,
                "support_levels": [snapshot.support] if snapshot.support else [],
                "resistance_levels": [snapshot.resistance] if snapshot.resistance else [],
                "volume_trend": volume_trend,
                "signals": signals,
            }

        except Exception as e:
            logger.warning(f"Technical intelligence error for {symbol}: {e}")
            return None

    async def _get_quality_intelligence(self, symbol: str) -> Optional[Dict]:
        """Get quality score and metrics."""
        try:
            metrics = await self._quality_service.get_quality_metrics(symbol)
            if not metrics or metrics.data_quality == "low":
                return None

            score = self._quality_service.calculate_quality_score(metrics)
            strengths, weaknesses = [], []

            if score.accruals_score and score.accruals_score > 60:
                strengths.append("Low earnings manipulation risk")
            elif score.accruals_score and score.accruals_score < 40:
                weaknesses.append("High accruals concern")

            if score.roe_score and score.roe_score > 60:
                strengths.append("Strong return on equity")
            elif score.roe_score and score.roe_score < 40:
                weaknesses.append("Weak profitability")

            if score.cfa_score and score.cfa_score > 60:
                strengths.append("Good cash flow generation")
            elif score.cfa_score and score.cfa_score < 40:
                weaknesses.append("Poor cash conversion")

            if score.da_score and score.da_score > 60:
                strengths.append("Conservative leverage")
            elif score.da_score and score.da_score < 40:
                weaknesses.append("High debt levels")

            return {
                "quality_score": score.percentile_rank or 50,
                "grade": score.grade or "C",
                "strengths": strengths,
                "weaknesses": weaknesses,
            }

        except Exception as e:
            logger.warning(f"Quality intelligence error for {symbol}: {e}")
            return None

    def _analyze_news_sentiment(self, news_result) -> str:
        if not news_result or not news_result.answer:
            return "neutral"
        answer_lower = news_result.answer.lower()
        positive = ["surge", "rally", "gain", "beat", "upgrade", "buy", "bullish", "strong", "positive"]
        negative = ["drop", "fall", "miss", "downgrade", "sell", "bearish", "weak", "negative", "crash"]
        pos_count = sum(1 for word in positive if word in answer_lower)
        neg_count = sum(1 for word in negative if word in answer_lower)
        if pos_count > neg_count + 1:
            return "positive"
        elif neg_count > pos_count + 1:
            return "negative"
        return "neutral"

    def _extract_news_topics(self, news_result) -> List[str]:
        topics = []
        if news_result and news_result.answer:
            answer_lower = news_result.answer.lower()
            topic_map = {
                "earnings": ["earnings", "revenue", "profit", "quarterly"],
                "analyst": ["analyst", "upgrade", "downgrade", "rating", "target"],
                "product": ["product", "launch", "announce", "release"],
                "legal": ["lawsuit", "legal", "sec", "investigation"],
                "merger": ["merger", "acquisition", "deal", "buyout"],
                "macro": ["fed", "rate", "inflation", "economy"],
            }
            for topic, keywords in topic_map.items():
                if any(kw in answer_lower for kw in keywords):
                    topics.append(topic)
        return topics[:3]

    def analyze(self, intelligence: Dict, alert: Dict):
        """Analyze gathered intelligence and add warnings/enhancements."""
        warnings = intelligence["warnings"]
        enhancements = intelligence["enhancements"]

        news = intelligence.get("news")
        if news:
            if news.get("sentiment") == "negative":
                warnings.append("Negative news sentiment detected")
            elif news.get("sentiment") == "positive":
                enhancements.append("Positive news sentiment")
            topics = news.get("key_topics", [])
            if "earnings" in topics:
                warnings.append("Earnings-related news - volatility likely")
            if "legal" in topics:
                warnings.append("Legal/regulatory news detected")
            if "analyst" in topics:
                enhancements.append("Analyst coverage - increased visibility")

        technicals = intelligence.get("technicals")
        if technicals:
            direction = alert.get("direction", "long")
            trend = technicals.get("trend", "neutral")
            if direction == "long" and trend == "down":
                warnings.append("Trading against downtrend")
            elif direction == "short" and trend == "up":
                warnings.append("Shorting against uptrend")
            elif (direction == "long" and trend == "up") or (direction == "short" and trend == "down"):
                enhancements.append("Trade aligns with trend")

            rsi = technicals.get("momentum", 50)
            if rsi > 70 and direction == "long":
                warnings.append(f"RSI overbought ({rsi:.0f})")
            elif rsi < 30 and direction == "short":
                warnings.append(f"RSI oversold ({rsi:.0f})")

            vol_trend = technicals.get("volume_trend", "normal")
            if vol_trend == "high":
                enhancements.append("High volume confirms move")
            elif vol_trend == "low":
                warnings.append("Low volume - watch for false breakout")

        quality = intelligence.get("quality_metrics")
        if quality:
            qscore = quality.get("quality_score", 50)
            if qscore >= 80:
                enhancements.append(f"High quality setup ({qscore}/100)")
            elif qscore < 50:
                warnings.append(f"Low quality score ({qscore}/100)")

    def calculate_adjustment(self, intelligence: Dict) -> int:
        """Calculate score adjustment based on intelligence."""
        adjustment = 0
        news = intelligence.get("news")
        if news:
            sentiment = news.get("sentiment", "neutral")
            if sentiment == "positive":
                adjustment += 5
            elif sentiment == "negative":
                adjustment -= 10

        technicals = intelligence.get("technicals")
        if technicals:
            vol_trend = technicals.get("volume_trend", "normal")
            if vol_trend == "high":
                adjustment += 5
            elif vol_trend == "low":
                adjustment -= 5

        adjustment -= len(intelligence.get("warnings", [])) * 3
        adjustment += len(intelligence.get("enhancements", [])) * 2
        return adjustment

    @staticmethod
    def classify_time_window(now_et) -> str:
        """Classify the current ET time into a trading time window."""
        h, m = now_et.hour, now_et.minute
        t = h * 60 + m
        if t < 9 * 60 + 30:
            return "pre_market"
        elif t < 9 * 60 + 45:
            return "opening_auction"
        elif t < 10 * 60:
            return "opening_drive"
        elif t < 10 * 60 + 30:
            return "morning_momentum"
        elif t < 11 * 60 + 30:
            return "mid_morning"
        elif t < 14 * 60:
            return "midday"
        elif t < 15 * 60:
            return "afternoon"
        elif t < 15 * 60 + 45:
            return "power_hour"
        elif t < 16 * 60:
            return "closing_auction"
        else:
            return "after_hours"
