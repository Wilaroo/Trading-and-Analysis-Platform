"""
Sentiment Analysis Service
Provides multi-layer sentiment analysis for news and market data:
1. Fast keyword-based scoring (real-time)
2. AI-powered deep analysis via Ollama/LLM (high-priority items)

Integrates with scanner, alerts, and AI assistant.
"""
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class SentimentLevel(Enum):
    """Sentiment classification levels"""
    VERY_BULLISH = "very_bullish"    # Score > 0.6
    BULLISH = "bullish"               # Score 0.2 to 0.6
    NEUTRAL = "neutral"               # Score -0.2 to 0.2
    BEARISH = "bearish"               # Score -0.6 to -0.2
    VERY_BEARISH = "very_bearish"    # Score < -0.6


@dataclass
class SentimentResult:
    """Comprehensive sentiment analysis result"""
    symbol: str
    overall_sentiment: SentimentLevel
    sentiment_score: float          # -1.0 (bearish) to 1.0 (bullish)
    confidence: float               # 0.0 to 1.0
    
    # Component scores
    news_sentiment: float           # Sentiment from news headlines
    social_sentiment: float         # Placeholder for social data
    analyst_sentiment: float        # From upgrade/downgrade keywords
    
    # Analysis details
    bullish_signals: List[str]
    bearish_signals: List[str]
    key_headlines: List[str]
    
    # AI analysis (if performed)
    ai_analysis: Optional[str] = None
    ai_recommendation: Optional[str] = None
    
    # Metadata
    news_count: int = 0
    analysis_depth: str = "basic"   # "basic" or "deep"
    analyzed_at: str = ""
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['overall_sentiment'] = self.overall_sentiment.value
        return result


# Enhanced keyword dictionaries with weights
BULLISH_KEYWORDS = {
    # Strong bullish (weight 2.0)
    "surge": 2.0, "soar": 2.0, "skyrocket": 2.0, "breakout": 2.0, 
    "all-time high": 2.0, "record high": 2.0, "beat expectations": 2.0,
    "blowout earnings": 2.0, "massive growth": 2.0, "upgrade": 2.0,
    
    # Moderate bullish (weight 1.5)
    "rally": 1.5, "jump": 1.5, "gain": 1.5, "rise": 1.5, "climb": 1.5,
    "outperform": 1.5, "strong": 1.5, "bullish": 1.5, "buy": 1.5,
    "positive": 1.5, "optimistic": 1.5, "growth": 1.5,
    
    # Mild bullish (weight 1.0)
    "higher": 1.0, "up": 1.0, "advance": 1.0, "improve": 1.0,
    "recover": 1.0, "rebound": 1.0, "bounce": 1.0, "support": 1.0,
    "momentum": 1.0, "accumulation": 1.0,
}

BEARISH_KEYWORDS = {
    # Strong bearish (weight 2.0)
    "crash": 2.0, "plunge": 2.0, "collapse": 2.0, "tank": 2.0,
    "all-time low": 2.0, "record low": 2.0, "miss expectations": 2.0,
    "downgrade": 2.0, "bankruptcy": 2.0, "fraud": 2.0, "investigation": 2.0,
    
    # Moderate bearish (weight 1.5)
    "drop": 1.5, "fall": 1.5, "decline": 1.5, "sink": 1.5, "tumble": 1.5,
    "underperform": 1.5, "weak": 1.5, "bearish": 1.5, "sell": 1.5,
    "negative": 1.5, "concern": 1.5, "fear": 1.5, "recession": 1.5,
    
    # Mild bearish (weight 1.0)
    "lower": 1.0, "down": 1.0, "retreat": 1.0, "pullback": 1.0,
    "pressure": 1.0, "risk": 1.0, "warning": 1.0, "layoff": 1.0,
    "cut": 1.0, "distribution": 1.0,
}

# Analyst action keywords
ANALYST_BULLISH = ["upgrade", "buy", "outperform", "overweight", "strong buy", "price target raised"]
ANALYST_BEARISH = ["downgrade", "sell", "underperform", "underweight", "price target cut", "price target lowered"]


class SentimentAnalysisService:
    """
    Multi-layer sentiment analysis service.
    Uses fast keyword analysis + optional AI deep analysis.
    """
    
    def __init__(self):
        self._news_service = None
        self._llm_service = None
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_ttl = 300  # 5 minutes
        self._initialized = False
    
    def set_services(self, news_service=None, llm_service=None):
        """Set service dependencies"""
        self._news_service = news_service
        self._llm_service = llm_service
        self._initialized = True
    
    async def analyze_sentiment(self, symbol: str, use_ai: bool = False) -> SentimentResult:
        """
        Analyze sentiment for a symbol.
        
        Args:
            symbol: Stock symbol
            use_ai: If True, perform deep AI analysis (slower but more accurate)
        
        Returns:
            SentimentResult with comprehensive sentiment data
        """
        symbol = symbol.upper()
        
        # Get news headlines
        headlines = []
        if self._news_service:
            try:
                news = await self._news_service.get_ticker_news(symbol, max_items=20)
                headlines = [n.get("headline", "") for n in news if n.get("headline")]
            except Exception as e:
                logger.warning(f"Could not fetch news for {symbol}: {e}")
        
        # Perform keyword analysis
        news_score, bullish_signals, bearish_signals = self._analyze_keywords(headlines)
        analyst_score = self._analyze_analyst_actions(headlines)
        
        # Combine scores
        overall_score = (news_score * 0.7) + (analyst_score * 0.3)
        
        # Classify sentiment
        sentiment_level = self._classify_sentiment(overall_score)
        
        # Calculate confidence based on signal count
        signal_count = len(bullish_signals) + len(bearish_signals)
        confidence = min(0.9, 0.3 + (signal_count * 0.1))
        
        result = SentimentResult(
            symbol=symbol,
            overall_sentiment=sentiment_level,
            sentiment_score=round(overall_score, 3),
            confidence=round(confidence, 2),
            news_sentiment=round(news_score, 3),
            social_sentiment=0.0,  # Placeholder
            analyst_sentiment=round(analyst_score, 3),
            bullish_signals=bullish_signals[:5],
            bearish_signals=bearish_signals[:5],
            key_headlines=headlines[:3],
            news_count=len(headlines),
            analysis_depth="basic",
            analyzed_at=datetime.now(timezone.utc).isoformat()
        )
        
        # Perform AI deep analysis if requested and available
        if use_ai and self._llm_service and headlines:
            try:
                ai_result = await self._deep_ai_analysis(symbol, headlines, result)
                if ai_result:
                    result.ai_analysis = ai_result.get("analysis")
                    result.ai_recommendation = ai_result.get("recommendation")
                    result.analysis_depth = "deep"
                    
                    # Adjust score based on AI analysis
                    ai_score = ai_result.get("score", 0)
                    if ai_score != 0:
                        # Blend AI score with keyword score (AI weighted higher)
                        result.sentiment_score = round((overall_score * 0.4) + (ai_score * 0.6), 3)
                        result.overall_sentiment = self._classify_sentiment(result.sentiment_score)
                        result.confidence = min(0.95, result.confidence + 0.15)
            except Exception as e:
                logger.warning(f"AI analysis failed for {symbol}: {e}")
        
        # Cache result
        self._cache[symbol] = result
        
        return result
    
    def _analyze_keywords(self, texts: List[str]) -> Tuple[float, List[str], List[str]]:
        """
        Analyze texts using weighted keywords.
        Returns (score, bullish_signals, bearish_signals)
        """
        if not texts:
            return 0.0, [], []
        
        bullish_score = 0.0
        bearish_score = 0.0
        bullish_signals = []
        bearish_signals = []
        
        combined_text = " ".join(texts).lower()
        
        # Check bullish keywords
        for keyword, weight in BULLISH_KEYWORDS.items():
            count = len(re.findall(r'\b' + re.escape(keyword) + r'\b', combined_text))
            if count > 0:
                bullish_score += weight * count
                bullish_signals.append(f"{keyword} ({count}x)")
        
        # Check bearish keywords
        for keyword, weight in BEARISH_KEYWORDS.items():
            count = len(re.findall(r'\b' + re.escape(keyword) + r'\b', combined_text))
            if count > 0:
                bearish_score += weight * count
                bearish_signals.append(f"{keyword} ({count}x)")
        
        # Calculate normalized score (-1 to 1)
        total = bullish_score + bearish_score
        if total > 0:
            score = (bullish_score - bearish_score) / total
        else:
            score = 0.0
        
        return score, bullish_signals, bearish_signals
    
    def _analyze_analyst_actions(self, headlines: List[str]) -> float:
        """Analyze analyst upgrade/downgrade mentions"""
        combined = " ".join(headlines).lower()
        
        bullish_count = sum(1 for kw in ANALYST_BULLISH if kw in combined)
        bearish_count = sum(1 for kw in ANALYST_BEARISH if kw in combined)
        
        total = bullish_count + bearish_count
        if total > 0:
            return (bullish_count - bearish_count) / total
        return 0.0
    
    def _classify_sentiment(self, score: float) -> SentimentLevel:
        """Classify score into sentiment level"""
        if score > 0.6:
            return SentimentLevel.VERY_BULLISH
        elif score > 0.2:
            return SentimentLevel.BULLISH
        elif score < -0.6:
            return SentimentLevel.VERY_BEARISH
        elif score < -0.2:
            return SentimentLevel.BEARISH
        else:
            return SentimentLevel.NEUTRAL
    
    async def _deep_ai_analysis(self, symbol: str, headlines: List[str], 
                                 basic_result: SentimentResult) -> Optional[Dict]:
        """
        Perform deep AI analysis using Ollama/LLM.
        """
        if not self._llm_service:
            return None
        
        headlines_text = "\n".join([f"- {h}" for h in headlines[:10]])
        
        prompt = f"""Analyze the sentiment of these recent news headlines for {symbol}:

{headlines_text}

Based on these headlines:
1. What is the overall sentiment? (very_bullish, bullish, neutral, bearish, very_bearish)
2. Score from -1.0 (very bearish) to 1.0 (very bullish)
3. Key bullish factors (if any)
4. Key bearish factors (if any)
5. Short-term trading recommendation

Respond in this exact JSON format:
{{
    "sentiment": "bullish",
    "score": 0.35,
    "analysis": "Brief 1-2 sentence analysis",
    "bullish_factors": ["factor1", "factor2"],
    "bearish_factors": ["factor1"],
    "recommendation": "Brief trading recommendation"
}}"""

        try:
            from services.llm_service import get_llm_service
            llm = get_llm_service()
            
            response = llm.generate_json(
                prompt=prompt,
                system_prompt="You are a financial sentiment analyst. Analyze news headlines objectively and provide trading insights. Always respond with valid JSON.",
                max_tokens=500
            )
            
            if response and isinstance(response, dict):
                return response
        except Exception as e:
            logger.warning(f"LLM sentiment analysis failed: {e}")
        
        return None
    
    async def get_market_sentiment(self) -> Dict:
        """
        Get overall market sentiment from major indices and news.
        """
        market_symbols = ["SPY", "QQQ", "DIA", "IWM"]
        results = []
        
        for symbol in market_symbols:
            try:
                result = await self.analyze_sentiment(symbol, use_ai=False)
                results.append(result)
            except Exception as e:
                logger.warning(f"Could not analyze {symbol}: {e}")
        
        if not results:
            return {
                "overall_sentiment": "neutral",
                "score": 0.0,
                "confidence": 0.0,
                "details": []
            }
        
        # Average the scores
        avg_score = sum(r.sentiment_score for r in results) / len(results)
        avg_confidence = sum(r.confidence for r in results) / len(results)
        
        return {
            "overall_sentiment": self._classify_sentiment(avg_score).value,
            "score": round(avg_score, 3),
            "confidence": round(avg_confidence, 2),
            "details": [r.to_dict() for r in results],
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def enhance_alert_with_sentiment(self, alert: Dict) -> Dict:
        """
        Enhance a scanner alert with sentiment data.
        Used by scanner before generating alerts.
        """
        symbol = alert.get("symbol", "")
        if not symbol:
            return alert
        
        try:
            # Use cached result or do quick analysis
            if symbol in self._cache:
                sentiment = self._cache[symbol]
            else:
                sentiment = await self.analyze_sentiment(symbol, use_ai=False)
            
            # Add sentiment to alert
            alert["sentiment"] = {
                "level": sentiment.overall_sentiment.value,
                "score": sentiment.sentiment_score,
                "confidence": sentiment.confidence
            }
            
            # Add to reasoning
            sentiment_desc = f"Sentiment: {sentiment.overall_sentiment.value.upper()} ({sentiment.sentiment_score:+.2f})"
            if "reasoning" in alert:
                alert["reasoning"].append(sentiment_desc)
            
            # Adjust priority for strong sentiment alignment
            if alert.get("direction") == "long" and sentiment.sentiment_score > 0.4:
                alert["reasoning"].append("Sentiment confirms bullish bias")
            elif alert.get("direction") == "short" and sentiment.sentiment_score < -0.4:
                alert["reasoning"].append("Sentiment confirms bearish bias")
            elif alert.get("direction") == "long" and sentiment.sentiment_score < -0.3:
                alert["warnings"] = alert.get("warnings", []) + ["Bearish sentiment headwind"]
            elif alert.get("direction") == "short" and sentiment.sentiment_score > 0.3:
                alert["warnings"] = alert.get("warnings", []) + ["Bullish sentiment headwind"]
        
        except Exception as e:
            logger.debug(f"Could not add sentiment to alert: {e}")
        
        return alert
    
    def get_sentiment_summary_for_ai(self, results: List[SentimentResult]) -> str:
        """Generate sentiment summary for AI assistant"""
        if not results:
            return "No sentiment data available."
        
        lines = ["**News Sentiment Analysis**:"]
        
        for r in results[:5]:
            emoji = "🟢" if r.sentiment_score > 0.2 else "🔴" if r.sentiment_score < -0.2 else "🟡"
            lines.append(f"- {r.symbol}: {emoji} {r.overall_sentiment.value} ({r.sentiment_score:+.2f})")
            if r.bullish_signals:
                lines.append(f"  Bullish: {', '.join(r.bullish_signals[:2])}")
            if r.bearish_signals:
                lines.append(f"  Bearish: {', '.join(r.bearish_signals[:2])}")
        
        return "\n".join(lines)


# Singleton instance
_sentiment_service: Optional[SentimentAnalysisService] = None


def get_sentiment_service() -> SentimentAnalysisService:
    """Get or create the sentiment analysis service singleton"""
    global _sentiment_service
    if _sentiment_service is None:
        _sentiment_service = SentimentAnalysisService()
    return _sentiment_service
