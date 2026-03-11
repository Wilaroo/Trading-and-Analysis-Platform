"""
Analyst Agent - Market Analysis and Stock Research
Provides technical analysis, sector context, and scanner insights.
All data comes from CODE (services), LLM only for natural language synthesis.
"""
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from agents.base_agent import BaseAgent, AgentType, AgentResponse, DataFetcher
from agents.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class AnalysisContext:
    """Container for analysis data (all from CODE)"""
    symbol: str
    current_price: float = 0
    change_percent: float = 0
    volume: int = 0
    avg_volume: int = 0
    rvol: float = 0
    
    # Technical levels
    vwap: float = 0
    hod: float = 0
    lod: float = 0
    support: float = 0
    resistance: float = 0
    
    # Indicators
    rsi: float = 0
    macd_signal: str = ""
    trend: str = ""
    
    # Sector context
    sector: str = ""
    sector_performance: float = 0
    sector_rank: int = 0
    
    # Scanner alerts
    active_setups: List[Dict] = None
    
    # News/sentiment
    sentiment_score: float = 0
    recent_news: List[str] = None
    
    # TQS (Trade Quality Score) - NEW
    tqs_score: float = 0
    tqs_grade: str = ""
    tqs_action: str = ""
    tqs_breakdown: Dict = None
    tqs_key_factors: List[str] = None
    tqs_concerns: List[str] = None


class AnalystAgent(BaseAgent):
    """
    Analyst Agent for market analysis.
    
    Responsibilities:
    - Technical analysis (CODE handles all calculations)
    - Sector/industry context (CODE)
    - Scanner alerts and setups (CODE)
    - LLM synthesizes findings into readable analysis
    """
    
    def __init__(self, llm_provider: LLMProvider):
        super().__init__(AgentType.ANALYST, llm_provider)
        self.data_fetcher: Optional[DataFetcher] = None
        self._tqs_engine = None
        
    def inject_services(self, services: Dict[str, Any]):
        """Inject required services"""
        self.data_fetcher = DataFetcher(services)
        self._services = services
        # Wire up TQS engine for Trade Quality Scores
        self._tqs_engine = services.get("tqs_engine")
        if self._tqs_engine:
            logger.info("Analyst Agent: TQS Engine connected")
    
    def get_system_prompt(self) -> str:
        return """You are a professional market analyst assistant. Your role is to synthesize 
technical analysis data into clear, actionable insights.

Guidelines:
1. Use ONLY the data provided - never make up numbers
2. Be direct and concise - traders value clarity
3. Highlight key levels (support, resistance, VWAP)
4. Note any active scanner setups or alerts
5. Include sector context when relevant
6. End with a clear bias: BULLISH, BEARISH, or NEUTRAL

Format your analysis with clear sections using **bold** headers."""
    
    async def process(self, input_data: Dict[str, Any]) -> AgentResponse:
        """
        Process an analysis request.
        
        Flow:
        1. Identify symbol(s) to analyze
        2. Gather all data from CODE
        3. Have LLM synthesize into readable analysis
        """
        start = time.time()
        message = input_data.get("message", "")
        symbol = input_data.get("symbol", "")
        analysis_type = input_data.get("analysis_type", "full")  # full, technical, sector, quick
        
        if not symbol:
            # Try to extract symbol from message
            symbols = input_data.get("symbols", [])
            symbol = symbols[0] if symbols else None
        
        if not symbol:
            return self._create_response(
                success=False,
                content={"message": "Please specify a stock symbol to analyze (e.g., 'analyze NVDA')"},
                latency_ms=(time.time() - start) * 1000,
                error="No symbol provided"
            )
        
        # Gather all data from CODE
        context = await self._build_analysis_context(symbol.upper())
        
        # For quick analysis, return without LLM
        if analysis_type == "quick":
            return self._create_response(
                success=True,
                content={
                    "message": self._format_quick_analysis(context),
                    "data": self._context_to_dict(context)
                },
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only",
                metadata={"analysis_type": "quick"}
            )
        
        # Build prompt with verified data
        prompt = self._build_analysis_prompt(message, context, analysis_type)
        
        # Get LLM synthesis
        response = await self._call_llm(
            prompt=prompt,
            temperature=0.5,
            max_tokens=1200
        )
        
        if not response.success:
            # Return raw analysis if LLM unavailable
            return self._create_response(
                success=True,
                content={
                    "message": self._format_raw_analysis(context),
                    "data": self._context_to_dict(context)
                },
                latency_ms=(time.time() - start) * 1000,
                model_used="code_only",
                metadata={"llm_available": False}
            )
        
        return self._create_response(
            success=True,
            content={
                "message": response.content,
                "data": self._context_to_dict(context)
            },
            latency_ms=(time.time() - start) * 1000,
            model_used=response.model,
            metadata={"analysis_type": analysis_type}
        )
    
    async def _build_analysis_context(self, symbol: str) -> AnalysisContext:
        """Gather all analysis data from CODE (services)"""
        context = AnalysisContext(symbol=symbol, active_setups=[], recent_news=[])
        
        # Get quote data
        if self.data_fetcher:
            quote = await self.data_fetcher.get_quote(symbol)
            if quote:
                context.current_price = quote.get("price", quote.get("last", 0))
                context.change_percent = quote.get("change_percent", quote.get("changePercent", 0))
                context.volume = quote.get("volume", 0)
                context.vwap = quote.get("vwap", 0)
                context.hod = quote.get("high", quote.get("hod", 0))
                context.lod = quote.get("low", quote.get("lod", 0))
        
        # Get technical snapshot
        try:
            tech_service = self._services.get("technical_service")
            if tech_service:
                snapshot = await tech_service.get_technical_snapshot(symbol)
                if snapshot:
                    # TechnicalSnapshot is a dataclass, access attributes directly
                    context.rsi = getattr(snapshot, "rsi_14", 0)
                    context.trend = getattr(snapshot, "trend", "unknown")
                    context.support = getattr(snapshot, "support", 0)
                    context.resistance = getattr(snapshot, "resistance", 0)
                    
                    # MACD is not directly available on TechnicalSnapshot
                    # Infer from squeeze_fire (positive = bullish momentum)
                    squeeze_fire = getattr(snapshot, "squeeze_fire", 0)
                    if squeeze_fire > 0:
                        context.macd_signal = "bullish"
                    elif squeeze_fire < 0:
                        context.macd_signal = "bearish"
                    else:
                        context.macd_signal = "neutral"
        except Exception as e:
            logger.warning(f"Error getting technical data: {e}")
        
        # Get sector context
        try:
            sector_service = self._services.get("sector_service")
            if sector_service:
                sector_ctx = await sector_service.get_sector_context(symbol)
                if sector_ctx:
                    context.sector = sector_ctx.get("sector", "")
                    context.sector_performance = sector_ctx.get("sector_change", 0)
                    context.sector_rank = sector_ctx.get("sector_rank", 0)
        except Exception as e:
            logger.warning(f"Error getting sector data: {e}")
        
        # Get scanner alerts for this symbol
        try:
            scanner = self._services.get("scanner")
            if scanner:
                alerts = scanner.get_alerts_for_symbol(symbol)
                if alerts:
                    context.active_setups = [
                        {"setup": a.setup_type, "priority": a.priority, "price": a.price}
                        for a in alerts[:5]
                    ]
        except Exception as e:
            logger.warning(f"Error getting scanner alerts: {e}")
        
        # Get sentiment
        try:
            sentiment_service = self._services.get("sentiment_service")
            if sentiment_service:
                sentiment = await sentiment_service.analyze_symbol(symbol)
                if sentiment:
                    context.sentiment_score = sentiment.get("score", 0)
                    context.recent_news = sentiment.get("headlines", [])[:3]
        except Exception as e:
            logger.warning(f"Error getting sentiment: {e}")
        
        # Get TQS (Trade Quality Score) - NEW
        if self._tqs_engine:
            try:
                # Determine setup type from scanner alerts if available
                setup_type = "momentum"  # Default
                if context.active_setups:
                    setup_type = context.active_setups[0].get("setup", "momentum")
                
                tqs_result = await self._tqs_engine.calculate_tqs(
                    symbol=symbol,
                    setup_type=setup_type,
                    direction="long"  # Default, could be inferred from context
                )
                
                if tqs_result:
                    context.tqs_score = tqs_result.score
                    context.tqs_grade = tqs_result.grade
                    context.tqs_action = tqs_result.action
                    context.tqs_breakdown = {
                        "setup": getattr(tqs_result.setup_score, 'score', 0) if tqs_result.setup_score else 0,
                        "technical": getattr(tqs_result.technical_score, 'score', 0) if tqs_result.technical_score else 0,
                        "fundamental": getattr(tqs_result.fundamental_score, 'score', 0) if tqs_result.fundamental_score else 0,
                        "context": getattr(tqs_result.context_score, 'score', 0) if tqs_result.context_score else 0,
                        "execution": getattr(tqs_result.execution_score, 'score', 0) if tqs_result.execution_score else 0
                    }
                    context.tqs_key_factors = tqs_result.key_factors[:3] if tqs_result.key_factors else []
                    context.tqs_concerns = tqs_result.concerns[:3] if tqs_result.concerns else []
                    logger.debug(f"TQS for {symbol}: {context.tqs_score:.0f} ({context.tqs_grade}) - {context.tqs_action}")
            except Exception as e:
                logger.warning(f"Error getting TQS: {e}")
        
        return context
    
    def _format_quick_analysis(self, ctx: AnalysisContext) -> str:
        """Format quick analysis without LLM"""
        lines = [f"**{ctx.symbol} Quick Analysis**\n"]
        
        # Price action
        emoji = "🟢" if ctx.change_percent >= 0 else "🔴"
        lines.append(f"{emoji} **Price:** ${ctx.current_price:.2f} ({ctx.change_percent:+.2f}%)")
        
        # Key levels
        lines.append("\n**Key Levels:**")
        lines.append(f"- VWAP: ${ctx.vwap:.2f}")
        lines.append(f"- HOD: ${ctx.hod:.2f} | LOD: ${ctx.lod:.2f}")
        if ctx.support:
            lines.append(f"- Support: ${ctx.support:.2f}")
        if ctx.resistance:
            lines.append(f"- Resistance: ${ctx.resistance:.2f}")
        
        # Indicators
        if ctx.rsi:
            rsi_status = "oversold" if ctx.rsi < 30 else "overbought" if ctx.rsi > 70 else "neutral"
            lines.append(f"\n**RSI:** {ctx.rsi:.1f} ({rsi_status})")
        
        # Active setups
        if ctx.active_setups:
            lines.append("\n**Active Setups:**")
            for setup in ctx.active_setups[:3]:
                lines.append(f"- {setup['setup']} ({setup['priority']})")
        
        return "\n".join(lines)
    
    def _format_raw_analysis(self, ctx: AnalysisContext) -> str:
        """Format raw analysis when LLM unavailable"""
        lines = [f"**{ctx.symbol} Technical Analysis**\n"]
        
        # Price
        emoji = "🟢" if ctx.change_percent >= 0 else "🔴"
        lines.append(f"{emoji} **Current:** ${ctx.current_price:.2f} ({ctx.change_percent:+.2f}%)")
        lines.append(f"**Volume:** {ctx.volume:,}")
        
        # Levels
        lines.append("\n**Technical Levels:**")
        lines.append(f"- VWAP: ${ctx.vwap:.2f} ({'above' if ctx.current_price > ctx.vwap else 'below'})")
        lines.append(f"- Day Range: ${ctx.lod:.2f} - ${ctx.hod:.2f}")
        if ctx.support:
            lines.append(f"- Support: ${ctx.support:.2f}")
        if ctx.resistance:
            lines.append(f"- Resistance: ${ctx.resistance:.2f}")
        
        # Indicators
        lines.append("\n**Indicators:**")
        if ctx.rsi:
            lines.append(f"- RSI: {ctx.rsi:.1f}")
        if ctx.macd_signal:
            lines.append(f"- MACD: {ctx.macd_signal}")
        if ctx.trend:
            lines.append(f"- Trend: {ctx.trend}")
        
        # Sector
        if ctx.sector:
            lines.append(f"\n**Sector:** {ctx.sector} ({ctx.sector_performance:+.2f}%)")
        
        # Setups
        if ctx.active_setups:
            lines.append("\n**Scanner Alerts:**")
            for setup in ctx.active_setups[:3]:
                lines.append(f"- {setup['setup']} @ ${setup['price']:.2f}")
        
        # TQS (Trade Quality Score) - NEW
        if ctx.tqs_score > 0:
            tqs_emoji = "🟢" if ctx.tqs_score >= 65 else "🟡" if ctx.tqs_score >= 50 else "🔴"
            lines.append("\n**Trade Quality Score (TQS):**")
            lines.append(f"{tqs_emoji} **Score:** {ctx.tqs_score:.0f}/100 ({ctx.tqs_grade}) - {ctx.tqs_action}")
            if ctx.tqs_breakdown:
                lines.append("Pillars:")
                for pillar, score in ctx.tqs_breakdown.items():
                    lines.append(f"  - {pillar.title()}: {score:.0f}")
            if ctx.tqs_key_factors:
                lines.append(f"Key Factors: {', '.join(ctx.tqs_key_factors)}")
            if ctx.tqs_concerns:
                lines.append(f"⚠️ Concerns: {', '.join(ctx.tqs_concerns)}")
        
        # Bias
        bias = "NEUTRAL"
        if ctx.rsi and ctx.rsi < 30:
            bias = "BULLISH (oversold)"
        elif ctx.rsi and ctx.rsi > 70:
            bias = "BEARISH (overbought)"
        elif ctx.current_price > ctx.vwap and ctx.macd_signal == "bullish":
            bias = "BULLISH"
        elif ctx.current_price < ctx.vwap and ctx.macd_signal == "bearish":
            bias = "BEARISH"
        
        # Factor in TQS for bias
        if ctx.tqs_score >= 70:
            bias += " (TQS: STRONG)"
        elif ctx.tqs_score >= 50:
            bias += " (TQS: OK)"
        elif ctx.tqs_score > 0:
            bias += " (TQS: WEAK)"
        
        lines.append(f"\n**Bias:** {bias}")
        
        return "\n".join(lines)
    
    def _build_analysis_prompt(self, message: str, ctx: AnalysisContext, analysis_type: str) -> str:
        """Build prompt with verified data for LLM synthesis"""
        support_str = f"${ctx.support:.2f}" if ctx.support else "N/A"
        resistance_str = f"${ctx.resistance:.2f}" if ctx.resistance else "N/A"
        rsi_str = f"{ctx.rsi:.1f}" if ctx.rsi else "N/A"
        
        data_block = f"""
SYMBOL: {ctx.symbol}
PRICE: ${ctx.current_price:.2f} ({ctx.change_percent:+.2f}%)
VOLUME: {ctx.volume:,}

TECHNICAL LEVELS:
- VWAP: ${ctx.vwap:.2f}
- HOD: ${ctx.hod:.2f}
- LOD: ${ctx.lod:.2f}
- Support: {support_str}
- Resistance: {resistance_str}

INDICATORS:
- RSI: {rsi_str}
- MACD: {ctx.macd_signal or 'N/A'}
- Trend: {ctx.trend or 'N/A'}

SECTOR: {ctx.sector or 'Unknown'} ({ctx.sector_performance:+.2f}%)

ACTIVE SCANNER SETUPS: {len(ctx.active_setups) if ctx.active_setups else 0}
{chr(10).join([f"- {s['setup']} ({s['priority']})" for s in (ctx.active_setups or [])[:3]])}

SENTIMENT SCORE: {ctx.sentiment_score:.2f}

TRADE QUALITY SCORE (TQS): {ctx.tqs_score:.0f}/100 ({ctx.tqs_grade}) - {ctx.tqs_action}
TQS Pillars: {ctx.tqs_breakdown if ctx.tqs_breakdown else 'N/A'}
TQS Key Factors: {', '.join(ctx.tqs_key_factors) if ctx.tqs_key_factors else 'N/A'}
TQS Concerns: {', '.join(ctx.tqs_concerns) if ctx.tqs_concerns else 'None'}
"""
        
        if analysis_type == "technical":
            instruction = "Provide a focused technical analysis with key levels and trading bias."
        elif analysis_type == "sector":
            instruction = "Focus on sector rotation and relative strength analysis."
        else:
            instruction = "Provide a comprehensive analysis covering technicals, sector context, and any active setups."
        
        return f"""Analyze the following stock data and {instruction}

User request: {message}

VERIFIED DATA (use only this):
{data_block}

Provide your analysis in a clear, structured format with **bold** headers."""
    
    def _context_to_dict(self, ctx: AnalysisContext) -> Dict:
        """Convert context to dictionary for API response"""
        return {
            "symbol": ctx.symbol,
            "price": ctx.current_price,
            "change_percent": ctx.change_percent,
            "volume": ctx.volume,
            "vwap": ctx.vwap,
            "hod": ctx.hod,
            "lod": ctx.lod,
            "support": ctx.support,
            "resistance": ctx.resistance,
            "rsi": ctx.rsi,
            "macd": ctx.macd_signal,
            "trend": ctx.trend,
            "sector": ctx.sector,
            "sector_performance": ctx.sector_performance,
            "active_setups": ctx.active_setups,
            "sentiment": ctx.sentiment_score,
            # TQS (Trade Quality Score)
            "tqs": {
                "score": ctx.tqs_score,
                "grade": ctx.tqs_grade,
                "action": ctx.tqs_action,
                "breakdown": ctx.tqs_breakdown,
                "key_factors": ctx.tqs_key_factors,
                "concerns": ctx.tqs_concerns
            } if ctx.tqs_score > 0 else None
        }
