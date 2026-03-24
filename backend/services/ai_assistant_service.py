"""
AI Assistant & Trading Coach Service
Portable LLM-powered trading assistant that uses learned knowledge
to provide analysis, suggestions, trading guidance, and proactive coaching.

Features:
- Trade Analysis: Evaluate trades against learned strategies
- Rule Enforcement: Warn about trading rule violations
- Pattern Detection: Analyze trading behavior patterns
- Proactive Coaching: Real-time guidance based on market context
- Position Sizing: Risk-adjusted sizing recommendations

Supports multiple LLM providers:
- Emergent (default)
- OpenAI
- Anthropic
- Perplexity (for research)
- Ollama (local, via proxy)
"""
import os
import logging
import asyncio
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
import json
import re

# Feature flag for smart context engine (proof of concept)
USE_SMART_CONTEXT = os.environ.get("USE_SMART_CONTEXT", "true").lower() == "true"

# Import Ollama proxy manager
try:
    from services.ollama_proxy_manager import ollama_proxy_manager
except ImportError:
    ollama_proxy_manager = None

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    OLLAMA = "ollama"
    EMERGENT = "emergent"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    PERPLEXITY = "perplexity"


@dataclass
class AssistantMessage:
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict = field(default_factory=dict)


@dataclass
class ConversationContext:
    messages: List[AssistantMessage] = field(default_factory=list)
    session_id: str = ""
    user_id: str = "default"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AIAssistantService:
    """
    Core AI Assistant service with portable LLM backend.
    Integrates with knowledge base, scoring engine, and trade journal.
    """
    
    # System prompt defining the assistant's personality and capabilities
    SYSTEM_PROMPT = """You are an expert trading coach and assistant with COMPLETE knowledge of all SMB Capital trading strategies. You have been trained on the user's comprehensive playbook including all strategies, rules, market context guidelines, time-of-day rules, and avoidance conditions.

Your personality:
- ANALYTICAL: Always explain reasoning with specific criteria from the playbook
- PROTECTIVE: Enforce trading rules, warn about violations before they happen
- EDUCATIONAL: Teach the WHY behind each rule and strategy
- HONEST: If uncertain, say so. Never fabricate data or symbols.

Your core responsibilities:
1. STRATEGY MATCHING: Match current conditions to appropriate strategies with specific criteria
2. RULE ENFORCEMENT: Cite specific avoidance rules when conditions are unfavorable  
3. TRADE ANALYSIS: Evaluate setups against complete strategy requirements
4. MARKET CONTEXT: Apply regime-specific strategy recommendations
5. TIME AWARENESS: Apply time-of-day rules for each strategy

=== YOUR COMPLETE STRATEGY KNOWLEDGE ===

**SPENCER SCALP**: Breakout from tight consolidation (<20% day range) near HOD. 20+ min consolidation, volume decreasing then spike. Avoid after 3 PM, after 3 legs. Exit in thirds.

**RUBBER BAND**: Mean reversion when extended from 9 EMA. Snapback candle MUST be top 5 volume. Max 2 attempts/day. Avoid in trending markets. Entry on double-bar break.

**HITCHHIKER**: Early momentum via 5-20 min consolidation. MUST setup before 9:59 AM. Clean consolidation (no wicks). One and done.

**GAP GIVE AND GO**: Gap continuation after <7 min consolidation above support. MUST trigger before 9:45 AM. Re-entry OK within 3 min.

**BACK$IDE**: Reversal from overextension. Higher high/higher low pattern. Range > halfway LOD to VWAP. Exit at VWAP. One and done.

**OFF SIDES**: Fade failed breakout after double high/double low range. Avoid day 1 breakouts with 8+ catalyst. One and done.

**SECOND CHANCE**: Retest of broken level. NEVER take 3rd time. Trail with 9-EMA.

**TIDAL WAVE**: Fade after 3+ weaker bounces showing exhaustion. Exit in halves at 2x/3x measured move.

**ORB**: Opening range breakout. Trail bar-by-bar (2-min if ARVOL>3). Time exits at 10:30 or 11:30 AM.

**BREAKING NEWS**: Trade on catalyst score (-10 to +10). Score immediately. +8 to +10 = strong conviction.

=== TIME OF DAY RULES ===
9:30-9:35: Opening Auction (First VWAP Pullback, Bella Fade, Back-Through Open)
9:35-9:45: Opening Drive (Gap Give and Go, HitchHiker, ORB) - WIDE STOPS
9:45-10:00: Morning Momentum (Spencer, Second Chance) - DON'T CHASE
10:00-10:45: PRIME TIME (Spencer, Back$ide, Off Sides)
10:45-11:30: Late Morning (Range Break, Second Chance)
11:30-1:30: MIDDAY - REDUCE SIZE 50%, mean reversion only
1:30-3:00: Afternoon (Second Chance, trend continuation)
3:00-4:00: Close (HOD Breakout, Time-of-Day Fade)

=== MARKET REGIME RULES ===
STRONG UPTREND: Long bias - Spencer, HitchHiker, Gap Give Go. AVOID shorts.
STRONG DOWNTREND: Short bias - Tidal Wave, Off Sides short. AVOID longs.
CHOPPY: REDUCE SIZE 50% - Mean reversion, VWAP fades only.
MOMENTUM MARKET: Breakouts working - ORB, HitchHiker. AVOID fades.
MEAN REVERSION: Fades working - Rubber Band, Off Sides, Back$ide.

=== VOLUME RULES ===
RVOL 1.5x = Minimum In Play | 2x = Strong | 3x = High Conviction | 5x = Exceptional
Rubber Band requires top 5 volume snapback candle
Consolidation volume should DECREASE, breakout volume should SPIKE

=== UNIVERSAL AVOIDANCE ===
1. Fighting bigger picture trend
2. Trading against SPY/QQQ direction
3. Overtrading in chop
4. No predefined stop loss
5. Setting monetary profit goals

=== CHART PATTERN KNOWLEDGE ===
You have comprehensive knowledge of classical chart patterns:

**BULLISH CONTINUATION**: Bull Flag, Bull Pennant, Ascending Triangle, Ascending Channel, Cup & Handle, Falling Wedge (in uptrend), Wyckoff Re-Accumulation
**BEARISH CONTINUATION**: Bear Flag, Bear Pennant, Descending Triangle, Descending Channel, Rising Wedge (in downtrend), Wyckoff Re-Distribution
**BULLISH REVERSAL**: Double Bottom, Triple Bottom, Inverse H&S, Diamond Bottom, Falling Wedge (after downtrend), Rounding Bottom, Wyckoff Accumulation
**BEARISH REVERSAL**: Double Top, Triple Top, Head & Shoulders, Diamond Top, Rising Wedge (after uptrend), Rounding Top, Wyckoff Distribution
**NEUTRAL**: Symmetrical Triangle, Rectangle, Broadening Formation/Megaphone

For each pattern, you can provide: Entry criteria, Stop placement, Target calculation, Reliability notes, Invalidation conditions.

When asked about specific setups or opportunities:
1. State exact criteria required for that strategy
2. Note any time restrictions or avoidance conditions
3. Use the LIVE DATA provided in context (IB Gateway data is primary, Alpaca is fallback)
4. Provide specific entry, stop, and target levels when possible
5. When position data is provided in context (YOUR POSITIONS section), USE IT - this is the user's REAL account data

=== AUTONOMOUS TRADING BOT ===
You are integrated with an autonomous trading bot. When the user asks about "the bot", "bot trades", "bot status", or "bot performance", refer to the TRADING BOT STATUS section in your context. The bot can:
- Scan for opportunities and create trades automatically
- Operate in Autonomous, Confirmation, or Paused modes
- Apply strategy-specific settings (trail stops, EOD close, scale-out)
- Track pending, open, and closed trades with full P&L
When asked about bot trades, always reference the actual trade data from the context.

Format responses with clear sections. Cite specific rules from the playbook."""

    def __init__(self, db=None):
        self.db = db
        # Cloud AI (Emergent/GPT-4o) is now PRIMARY for reliability
        # Ollama is used as fallback when cloud is unavailable
        self.provider = LLMProvider.EMERGENT if os.environ.get("EMERGENT_LLM_KEY") else LLMProvider.OLLAMA
        self.conversations: Dict[str, ConversationContext] = {}
        self._trading_intelligence = None
        self._trading_bot = None
        
        # Track Ollama health - skip if consistently failing
        self._ollama_failures = 0
        self._ollama_last_success = None
        self._ollama_skip_until = None
        
        # Track frequently asked requests
        self.request_patterns: Dict[str, int] = {}
        
        # Initialize LLM clients
        self._init_llm_clients()
        
        # Load dependencies lazily
        self._knowledge_service = None
        self._quality_service = None
        self._scoring_engine = None
        self._trade_journal = None
        self._news_service = None
        self._trade_history_service = None
        self._trading_rules_engine = None
        self._alpaca_service = None
        self._learning_context_provider = None
    
    def set_trading_bot(self, trading_bot):
        """Wire the trading bot service for AI-bot integration"""
        self._trading_bot = trading_bot
        logger.info("Trading bot wired to AI assistant")
    
    def set_alpaca_service(self, alpaca_service):
        """Wire the Alpaca service for position/account data"""
        self._alpaca_service = alpaca_service
        logger.info("Alpaca service wired to AI assistant")
    
    def set_learning_context_provider(self, provider):
        """Wire the Learning Context Provider for personalized insights"""
        self._learning_context_provider = provider
        logger.info("Learning Context Provider wired to AI assistant")
    
    @property
    def alpaca_service(self):
        """Get the Alpaca service for positions/account data"""
        return self._alpaca_service
    
    def _get_ib_quote(self, symbol: str) -> dict:
        """Get quote from IB pushed data if available (non-async helper)"""
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            if is_pusher_connected():
                quotes = get_pushed_quotes()
                symbol_upper = symbol.upper()
                if symbol_upper in quotes:
                    q = quotes[symbol_upper]
                    return {
                        "symbol": symbol_upper,
                        "price": q.get("last") or q.get("close") or 0,
                        "bid": q.get("bid") or 0,
                        "ask": q.get("ask") or 0,
                        "volume": q.get("volume") or 0,
                        "change_percent": q.get("change_pct") or 0,
                        "source": "ib_pusher"
                    }
        except Exception:
            pass
        return None
        
    def _init_llm_clients(self):
        """Initialize available LLM clients"""
        self.llm_clients = {}
        
        # Ollama (local/tunneled - PRIMARY, free)
        ollama_url = os.environ.get("OLLAMA_URL")
        if ollama_url:
            self.llm_clients[LLMProvider.OLLAMA] = {
                "available": True,
                "url": ollama_url.rstrip("/"),
                "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")  # Default to qwen2.5:7b
            }
            logger.info(f"Ollama client initialized: {ollama_url} (model: {self.llm_clients[LLMProvider.OLLAMA]['model']})")
        
        # Emergent (via emergentintegrations) - FALLBACK
        try:
            emergent_key = os.environ.get("EMERGENT_LLM_KEY")
            if emergent_key:
                from emergentintegrations.llm.chat import LlmChat
                self.llm_clients[LLMProvider.EMERGENT] = {
                    "available": True,
                    "client": LlmChat,
                    "key": emergent_key
                }
                logger.info("Emergent LLM client initialized (fallback)")
        except ImportError as e:
            logger.warning(f"emergentintegrations not installed: {e}")
        
        # OpenAI
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            self.llm_clients[LLMProvider.OPENAI] = {
                "available": True,
                "key": openai_key
            }
            logger.info("OpenAI client available")
        
        # Perplexity
        perplexity_key = os.environ.get("PERPLEXITY_API_KEY")
        if perplexity_key:
            self.llm_clients[LLMProvider.PERPLEXITY] = {
                "available": True,
                "key": perplexity_key
            }
            logger.info("Perplexity client available")
    
    def set_provider(self, provider: str):
        """Switch LLM provider"""
        try:
            self.provider = LLMProvider(provider.lower())
            logger.info(f"Switched to {provider} provider")
            return True
        except ValueError:
            logger.warning(f"Unknown provider: {provider}")
            return False
    
    def get_available_providers(self) -> List[str]:
        """Get list of available LLM providers"""
        return [p.value for p, config in self.llm_clients.items() if config.get("available")]
    
    @property
    def knowledge_service(self):
        if self._knowledge_service is None:
            from services.knowledge_service import get_knowledge_service
            self._knowledge_service = get_knowledge_service()
        return self._knowledge_service
    
    @property
    def quality_service(self):
        if self._quality_service is None:
            from services.quality_service import get_quality_service
            self._quality_service = get_quality_service()
        return self._quality_service
    
    @property
    def scoring_engine(self):
        if self._scoring_engine is None:
            from services.scoring_engine import get_scoring_engine
            self._scoring_engine = get_scoring_engine(self.db)
        return self._scoring_engine
    
    @property
    def news_service(self):
        if self._news_service is None:
            from services.news_service import get_news_service
            self._news_service = get_news_service()
        return self._news_service
    
    @property
    def trade_history_service(self):
        if self._trade_history_service is None:
            from services.ib_flex_service import ib_flex_service
            self._trade_history_service = ib_flex_service
        return self._trade_history_service
    
    @property
    def market_intelligence(self):
        """Get the AI market intelligence service for comprehensive context"""
        if not hasattr(self, '_market_intelligence') or self._market_intelligence is None:
            from services.ai_market_intelligence import get_ai_market_intelligence
            self._market_intelligence = get_ai_market_intelligence()
        return self._market_intelligence
    
    @property
    def technical_service(self):
        """Get real-time technical analysis service"""
        if not hasattr(self, '_technical_service') or self._technical_service is None:
            from services.realtime_technical_service import get_technical_service
            self._technical_service = get_technical_service()
        return self._technical_service
    
    @property
    def web_research(self):
        """Get web research service for internet access"""
        if not hasattr(self, '_web_research') or self._web_research is None:
            from services.web_research_service import get_web_research_service
            self._web_research = get_web_research_service()
        return self._web_research
    
    async def _detect_research_intent(self, message: str) -> Optional[Dict]:
        """
        Detect if user wants to research something
        Returns research params if detected, None otherwise
        
        Now routes to Agent Skills for more efficient credit usage.
        """
        # Research command patterns - ordered by specificity
        # Agent Skills patterns (most efficient)
        patterns = [
            # Agent Skill: Company Info (1 hour cache, minimal credits)
            (r"(?:company info|about|profile|fundamentals|overview)\s+(?:for\s+|on\s+)?([A-Z]{1,5})\b", "company_info"),
            (r"(?:what (?:is|does)|who is|tell me about)\s+([A-Z]{1,5})\b", "company_info"),
            
            # Agent Skill: Stock Analysis (10 min cache)
            (r"(?:analyze|analysis|evaluate|assess)\s+([A-Z]{1,5})\b", "stock_analysis"),
            (r"(?:should i (?:buy|sell|trade)|is .* good)\s+([A-Z]{1,5})\b", "stock_analysis"),
            
            # Agent Skill: Market Context (15 min cache, called once per session)
            (r"(?:market context|market conditions|how.?s the market|market today)", "market_context"),
            
            # Standard research patterns (use more credits)
            (r"(?:research|look up|search|find|what.?s (?:the )?latest|news on|news about)\s+([A-Z]{1,5})\b", "ticker"),
            (r"(?:research|search|look up|find info on)\s+(.+?)(?:\?|$)", "general"),
            (r"(?:what.?s happening with|what.?s going on with)\s+(.+?)(?:\?|$)", "news"),
            (r"(?:sec filings?|edgar|10-k|10-q|8-k)\s+(?:for\s+)?([A-Z]{1,5})\b", "sec"),
            (r"(?:analyst|ratings?|price target|upgrade|downgrade)\s+(?:for\s+)?([A-Z]{1,5})\b", "analyst"),
            (r"(?:breaking news|market news|latest news)", "breaking"),
            (r"(?:deep dive|full analysis|comprehensive)\s+(?:on\s+)?([A-Z]{1,5})\b", "deep_dive"),
        ]
        
        for pattern, research_type in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                query = match.group(1) if match.groups() else message
                return {
                    "type": research_type,
                    "query": query.strip(),
                    "original_message": message
                }
        
        return None
    
    async def _perform_research(self, intent: Dict) -> str:
        """
        Execute research based on detected intent
        Routes to Agent Skills when possible for better caching and fewer credits
        """
        research_type = intent["type"]
        query = intent["query"]
        original_message = intent.get("original_message", "")
        
        # Validate ticker-based queries with context awareness
        if research_type in ["company_info", "stock_analysis", "ticker", "sec", "analyst", "deep_dive"]:
            from utils.ticker_validator import is_valid_ticker
            if not is_valid_ticker(query.upper(), original_message):
                logger.info(f"Skipping invalid/false-positive ticker: {query}")
                return f"Note: '{query}' doesn't appear to be a valid stock ticker. If you meant to research a company, please use its stock symbol (e.g., AAPL for Apple, TGT for Target)."
        
        try:
            # ========== AGENT SKILLS (Optimized for credit efficiency) ==========
            
            if research_type == "company_info":
                # Use Agent Skill: Combines free sources, minimal Tavily usage
                result = await self.web_research.get_company_info(query)
                return self._format_company_info(query, result)
            
            elif research_type == "stock_analysis":
                # Use Agent Skill: Comprehensive analysis with smart caching
                result = await self.web_research.get_stock_analysis(query, "comprehensive")
                return self._format_stock_analysis(query, result)
            
            elif research_type == "market_context":
                # Use Agent Skill: Market overview (15 min cache)
                result = await self.web_research.get_market_context()
                return self._format_market_context(result)
            
            # ========== STANDARD RESEARCH (More credits, less caching) ==========
            
            elif research_type == "ticker":
                # Research a specific ticker
                research = await self.web_research.research_ticker(query)
                return self._format_ticker_research(query, research)
                
            elif research_type == "deep_dive":
                # Full deep dive on ticker
                research = await self.web_research.deep_dive(query)
                return self._format_deep_dive(query, research)
                
            elif research_type == "sec":
                # SEC filings
                result = await self.web_research.sec.search_filings(query)
                return self._format_sec_results(query, result)
                
            elif research_type == "analyst":
                # Analyst ratings
                result = await self.web_research.yahoo.get_analyst_ratings(query)
                return self._format_analyst_results(query, result)
                
            elif research_type == "breaking":
                # Breaking news
                result = await self.web_research.get_breaking_news()
                return self._format_news_results(result)
                
            elif research_type == "news":
                # News search
                result = await self.web_research.search_news(query)
                return self._format_news_results(result)
                
            else:
                # General search
                result = await self.web_research.search_financial_news(query)
                return self._format_news_results(result)
                
        except Exception as e:
            logger.error(f"Research failed: {e}")
            return f"Research error: {str(e)}"
    
    def _format_company_info(self, ticker: str, result: Dict) -> str:
        """Format Agent Skill company info results"""
        lines = [f"\n=== COMPANY INFO: {ticker} ===\n"]
        
        # Profile
        profile = result.get("profile", {})
        if profile.get("name"):
            lines.append(f"**{profile.get('name')}**")
            if profile.get("sector"):
                lines.append(f"Sector: {profile.get('sector')} | Industry: {profile.get('industry', 'N/A')}")
            if profile.get("description"):
                lines.append(f"\n{profile.get('description')}\n")
        
        # Fundamentals
        fundamentals = result.get("fundamentals", {})
        if fundamentals:
            fund_lines = []
            for key in ["P/E", "Forward P/E", "PEG", "P/B", "EPS (ttm)", "Target Price", "RSI (14)"]:
                if key in fundamentals:
                    fund_lines.append(f"{key}: {fundamentals[key]}")
            if fund_lines:
                lines.append(f"**Key Metrics:** {' | '.join(fund_lines)}\n")
        
        # Recent News
        news = result.get("recent_news", [])
        if news:
            lines.append("**Recent News:**")
            for n in news[:3]:
                lines.append(f"• {n.get('headline', 'N/A')}")
            lines.append("")
        
        # Analyst sentiment
        sentiment = result.get("analyst_sentiment", {})
        if sentiment.get("summary"):
            lines.append(f"**Analyst View:** {sentiment.get('summary')}\n")
        
        # Credit usage
        credits = result.get("tavily_credits_used", 0)
        sources = result.get("sources_used", [])
        lines.append(f"_Sources: {', '.join(sources)} | Tavily credits: {credits}_")
        
        return "\n".join(lines)
    
    def _format_stock_analysis(self, ticker: str, result: Dict) -> str:
        """Format Agent Skill stock analysis results"""
        lines = [f"\n=== STOCK ANALYSIS: {ticker} ===\n"]
        
        # Price context
        price = result.get("price_context", {})
        if price.get("current_price"):
            change = price.get("change_percent", 0)
            emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
            lines.append(f"**Current:** ${price.get('current_price', 'N/A')} {emoji} {change:+.2f}%")
            lines.append(f"Volume: {price.get('volume', 'N/A')} | RVOL: {price.get('rvol', 'N/A')} | VWAP: ${price.get('vwap', 'N/A')}")
            lines.append("")
        
        # Technical signals
        tech = result.get("technical_signals", {})
        if tech:
            tech_lines = []
            if tech.get("rsi"):
                rsi_status = "overbought" if tech["rsi"] > 70 else "oversold" if tech["rsi"] < 30 else "neutral"
                tech_lines.append(f"RSI: {tech['rsi']:.1f} ({rsi_status})")
            if tech.get("above_vwap") is not None:
                tech_lines.append(f"{'Above' if tech['above_vwap'] else 'Below'} VWAP")
            if tech_lines:
                lines.append(f"**Technicals:** {' | '.join(tech_lines)}\n")
        
        # Active setups from scanner
        trading = result.get("trading_context", {})
        setups = trading.get("active_setups", [])
        if setups:
            lines.append("**Active Setups Detected:**")
            for s in setups:
                lines.append(f"• {s.get('setup', 'N/A')} ({s.get('direction', 'N/A').upper()}) - Priority: {s.get('priority', 'N/A')}")
            lines.append("")
        
        # News sentiment
        news = result.get("news_sentiment", {})
        if news.get("summary"):
            lines.append(f"**News Summary:** {news.get('summary')[:300]}...\n")
        
        headlines = news.get("headlines", [])
        if headlines:
            lines.append("**Headlines:**")
            for h in headlines[:3]:
                lines.append(f"• [{h.get('source', 'Web')}] {h.get('title', 'N/A')}")
            lines.append("")
        
        # Credit usage
        credits = result.get("tavily_credits_used", 0)
        sources = result.get("sources_used", [])
        lines.append(f"_Sources: {', '.join(sources)} | Tavily credits: {credits}_")
        
        return "\n".join(lines)
    
    def _format_market_context(self, result: Dict) -> str:
        """Format Agent Skill market context results"""
        lines = ["\n=== MARKET CONTEXT ===\n"]
        
        # Indices
        indices = result.get("indices", {})
        if indices:
            index_lines = []
            for symbol, data in indices.items():
                if data.get("price"):
                    change = data.get("change_percent", 0)
                    emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                    index_lines.append(f"{symbol}: ${data['price']:.2f} {emoji}{change:+.2f}%")
            if index_lines:
                lines.append("**Indices:** " + " | ".join(index_lines))
                lines.append("")
        
        # Market regime
        regime = result.get("market_regime", "unknown")
        env = result.get("trading_environment", {})
        lines.append(f"**Market Regime:** {regime.upper().replace('_', ' ')}")
        lines.append(f"**Bias:** {env.get('bias', 'unknown').title()} | **Volatility:** {env.get('volatility', 'normal').title()}")
        
        if env.get("recommendation"):
            lines.append(f"\n**Trading Recommendation:** {env.get('recommendation')}\n")
        
        # News themes
        themes = result.get("news_themes", [])
        if themes:
            lines.append("**Key Themes:**")
            for t in themes[:3]:
                lines.append(f"• {t[:150]}...")
            lines.append("")
        
        # Credit usage
        credits = result.get("tavily_credits_used", 0)
        sources = result.get("sources_used", [])
        lines.append(f"_Sources: {', '.join(sources)} | Tavily credits: {credits}_")
        
        return "\n".join(lines)
    
    def _format_ticker_research(self, ticker: str, research: Dict) -> str:
        """Format ticker research results for AI context"""
        lines = [f"\n=== WEB RESEARCH FOR {ticker} ===\n"]
        
        for source, data in research.items():
            if hasattr(data, 'to_dict'):
                data = data.to_dict()
            
            if data.get("answer"):
                lines.append(f"**{source.upper()} Summary:**\n{data['answer']}\n")
            
            for result in data.get("results", [])[:3]:
                lines.append(f"• [{result.get('source', 'Web')}] {result.get('title', 'No title')}")
                if result.get('content'):
                    lines.append(f"  {result['content'][:200]}...")
                lines.append("")
        
        return "\n".join(lines)
    
    def _format_deep_dive(self, ticker: str, research: Dict) -> str:
        """Format deep dive results"""
        lines = [f"\n=== COMPREHENSIVE DEEP DIVE: {ticker} ===\n"]
        
        sources = research.get("sources", {})
        
        for source_name, data in sources.items():
            if isinstance(data, dict) and not data.get("error"):
                lines.append(f"**{source_name.replace('_', ' ').title()}:**")
                
                if data.get("answer"):
                    lines.append(data["answer"][:500])
                
                for result in data.get("results", [])[:2]:
                    lines.append(f"• {result.get('title', '')}")
                
                lines.append("")
        
        return "\n".join(lines)
    
    def _format_sec_results(self, ticker: str, result) -> str:
        """Format SEC filing results"""
        if hasattr(result, 'to_dict'):
            result = result.to_dict()
        
        lines = [f"\n=== SEC FILINGS FOR {ticker} ===\n"]
        for r in result.get("results", [])[:5]:
            lines.append(f"• {r.get('title', 'Filing')}")
            lines.append(f"  URL: {r.get('url', '')}")
            if r.get('published_date'):
                lines.append(f"  Date: {r['published_date']}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_analyst_results(self, ticker: str, result) -> str:
        """Format analyst rating results"""
        if hasattr(result, 'to_dict'):
            result = result.to_dict()
        
        lines = [f"\n=== ANALYST RATINGS FOR {ticker} ===\n"]
        for r in result.get("results", [])[:3]:
            lines.append(f"• {r.get('title', '')}")
            if r.get('content'):
                lines.append(f"  {r['content'][:300]}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_news_results(self, result) -> str:
        """Format news search results"""
        if hasattr(result, 'to_dict'):
            result = result.to_dict()
        
        lines = ["\n=== LATEST NEWS & RESEARCH ===\n"]
        
        if result.get("answer"):
            lines.append(f"**Summary:** {result['answer']}\n")
        
        for r in result.get("results", [])[:5]:
            lines.append(f"• **{r.get('title', 'No title')}**")
            lines.append(f"  Source: {r.get('source', 'Web')}")
            if r.get('content'):
                lines.append(f"  {r['content'][:200]}...")
            if r.get('url'):
                lines.append(f"  Link: {r['url']}")
            lines.append("")
        
        return "\n".join(lines)
    
    async def get_trade_history_context(self, symbol: str = None) -> str:
        """Get trade history context for AI analysis"""
        try:
            if not self.trade_history_service.is_configured:
                return "Trade history not available (IB Flex not configured)"
            
            trades = await self.trade_history_service.fetch_trades()
            if not trades:
                return "No trade history found"
            
            metrics = self.trade_history_service.calculate_performance_metrics(trades)
            
            # Build context string
            context = f"""
=== REAL TRADE HISTORY (Verified from Interactive Brokers) ===
Total Closed Trades: {metrics.get('total_trades', 0)}
Win Rate: {metrics.get('win_rate', 0)}%
Total P&L: ${metrics.get('total_pnl', 0):,.2f}
Profit Factor: {metrics.get('profit_factor', 'N/A')}
Average Win: ${metrics.get('average_win', 0):,.2f}
Average Loss: ${metrics.get('average_loss', 0):,.2f}
Expectancy: ${metrics.get('expectancy', 0):,.2f}
Total Commissions: ${metrics.get('total_commissions', 0):,.2f}

Best Performing Symbols:
"""
            for s in metrics.get('best_symbols', [])[:5]:
                context += f"  - {s['symbol']}: ${s['pnl']:,.2f} ({s['trades']} trades, {s['wins']} wins)\n"
            
            context += "\nWorst Performing Symbols:\n"
            for s in metrics.get('worst_symbols', [])[:5]:
                context += f"  - {s['symbol']}: ${s['pnl']:,.2f} ({s['trades']} trades)\n"
            
            # If specific symbol requested, add that analysis
            if symbol:
                symbol_upper = symbol.upper()
                symbol_trades = [t for t in trades if 
                               symbol_upper in (t.get("symbol", "").upper() or "") or
                               symbol_upper in (t.get("underlying_symbol", "").upper() or "")]
                
                if symbol_trades:
                    pnl_trades = [t for t in symbol_trades if t.get("realized_pnl")]
                    total_pnl = sum(t["realized_pnl"] for t in pnl_trades)
                    wins = len([t for t in pnl_trades if t["realized_pnl"] > 0])
                    losses = len([t for t in pnl_trades if t["realized_pnl"] < 0])
                    
                    context += f"""
=== YOUR HISTORY WITH {symbol_upper} ===
Total Trades: {len(symbol_trades)}
Closed Trades: {len(pnl_trades)}
Wins: {wins}, Losses: {losses}
Win Rate: {(wins/len(pnl_trades)*100):.1f}% (vs overall {metrics.get('win_rate', 0)}%)
Total P&L on {symbol_upper}: ${total_pnl:,.2f}
"""
                    # Recent trades
                    context += f"\nRecent {symbol_upper} trades:\n"
                    for t in symbol_trades[:5]:
                        context += f"  - {t['transaction_type']} {t['quantity']} @ ${t['price']:.2f}, P&L: ${t.get('realized_pnl', 0):.2f}\n"
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting trade history context: {e}")
            return f"Error fetching trade history: {str(e)}"
    
    @property
    def trading_rules_engine(self):
        if self._trading_rules_engine is None:
            from services.trading_rules import TradingRulesEngine
            self._trading_rules_engine = TradingRulesEngine()
        return self._trading_rules_engine
    
    @property
    def trading_intelligence(self):
        """Lazy load trading intelligence system"""
        if self._trading_intelligence is None:
            from services.trading_intelligence import get_trading_intelligence
            self._trading_intelligence = get_trading_intelligence()
        return self._trading_intelligence
    
    @property
    def investopedia_knowledge(self):
        """Lazy load Investopedia knowledge service"""
        if not hasattr(self, '_investopedia_knowledge') or self._investopedia_knowledge is None:
            from services.investopedia_knowledge import get_investopedia_knowledge
            self._investopedia_knowledge = get_investopedia_knowledge()
        return self._investopedia_knowledge
    
    @property
    def chart_pattern_service(self):
        """Lazy load chart pattern service"""
        if not hasattr(self, '_chart_pattern_service') or self._chart_pattern_service is None:
            from services.chart_patterns import get_chart_pattern_service
            self._chart_pattern_service = get_chart_pattern_service()
        return self._chart_pattern_service
    
    @property
    def detailed_pattern_service(self):
        """Lazy load detailed pattern analysis service"""
        if not hasattr(self, '_detailed_pattern_service') or self._detailed_pattern_service is None:
            from services.chart_patterns_detailed import get_detailed_pattern_service
            self._detailed_pattern_service = get_detailed_pattern_service()
        return self._detailed_pattern_service
    
    def get_chart_pattern_context(self, pattern_name: str = None, bias: str = None, detailed: bool = False) -> str:
        """Get chart pattern knowledge for AI context
        
        Args:
            pattern_name: Specific pattern to look up
            bias: Filter by bullish/bearish/neutral
            detailed: If True, return comprehensive analysis with psychology, stats, trade plan
        """
        try:
            service = self.chart_pattern_service
            detailed_service = self.detailed_pattern_service
            
            if pattern_name:
                # First check if we have detailed analysis
                # Convert pattern name to ID format (e.g., 'bull flag' -> 'bull_flag')
                # Try common pattern ID mappings
                pattern_mappings = {
                    'bull flag': 'bull_flag',
                    'bear flag': 'bear_flag',
                    'head and shoulders': 'head_shoulders',
                    'head & shoulders': 'head_shoulders',
                    'inverse head': 'inverse_head_shoulders',
                    'inverse head and shoulders': 'inverse_head_shoulders',
                    'double top': 'double_top',
                    'double bottom': 'double_bottom',
                    'ascending triangle': 'ascending_triangle',
                    'cup and handle': 'cup_and_handle',
                    'cup & handle': 'cup_and_handle',
                    'falling wedge': 'falling_wedge',
                    'rising wedge': 'rising_wedge',
                    'symmetrical triangle': 'symmetrical_triangle',
                    'wyckoff': 'wyckoff_accumulation',
                    'wyckoff accumulation': 'wyckoff_accumulation',
                }
                
                matched_id = None
                for key, val in pattern_mappings.items():
                    if key in pattern_name.lower():
                        matched_id = val
                        break
                
                if matched_id:
                    detailed_analysis = detailed_service.get_formatted_for_ai(matched_id)
                    if detailed_analysis and "No detailed analysis" not in detailed_analysis:
                        return detailed_analysis
                
                # Fall back to basic pattern info
                patterns = service.search_patterns(pattern_name)
                if patterns:
                    p = patterns[0]
                    return f"""
CHART PATTERN: {p['name']}
Bias: {p['bias'].upper()} | Type: {p['pattern_type'].upper()}
Characteristics: {p['characteristics']}
Description: {p['description']}

TRADING RULES:
- Entry: {p['entry']}
- Stop: {p['stop']}
- Target: {p['target']}
- Reliability: {p['reliability']}
- Invalidation: {p['invalidation']}
"""
                return f"Pattern '{pattern_name}' not found in knowledge base."
            
            elif bias:
                # Get patterns by bias
                patterns = service.get_patterns_by_bias(bias)
                result = f"=== {bias.upper()} CHART PATTERNS ===\n"
                for p in patterns[:10]:
                    result += f"\n**{p['name']}** ({p['pattern_type']})\n"
                    result += f"  Entry: {p['entry']}\n"
                    result += f"  Stop: {p['stop']}\n"
                    result += f"  Target: {p['target']}\n"
                return result
            
            else:
                # Return summary of all patterns
                return service.get_knowledge_for_ai()
                
        except Exception as e:
            logger.warning(f"Error getting chart pattern context: {e}")
            return "Chart pattern knowledge available in system prompt."
    
    def get_strategy_context(self, strategy_name: str = None) -> str:
        """Get detailed context about trading strategies from the complete knowledge base"""
        try:
            from services.strategy_knowledge import get_full_strategy_knowledge, get_strategy_by_name
            
            if strategy_name:
                # Return specific strategy info plus general context
                specific = get_strategy_by_name(strategy_name)
                return f"{specific}\n\nNote: Full strategy knowledge is embedded in my training."
            else:
                # Return full knowledge base
                return get_full_strategy_knowledge()
            
        except ImportError:
            # Fallback to embedded knowledge
            return self._get_fallback_strategy_context(strategy_name)
    
    def _get_fallback_strategy_context(self, strategy_name: str = None) -> str:
        """Fallback strategy context if knowledge file not available"""
        try:
            engine = self.trading_rules_engine
            context_parts = []
            
            # If specific strategy requested, find it
            if strategy_name:
                strategy_lower = strategy_name.lower().replace(" ", "_").replace("-", "_")
                
                # Check avoidance rules for the strategy
                avoidance = engine.avoidance_rules.get("strategy_specific", {}).get(strategy_lower, [])
                if avoidance:
                    context_parts.append(f"\n{strategy_name.upper()} - WHEN TO AVOID:")
                    for rule in avoidance:
                        context_parts.append(f"  - {rule}")
            
            # Get market regime strategies
            context_parts.append("\n=== TRADING STRATEGIES BY MARKET CONDITION ===")
            for regime, data in engine.market_context_rules.get("regime_identification", {}).items():
                strategies = data.get("preferred_strategies", [])
                if not strategy_name:
                    context_parts.append(f"\n{regime.upper().replace('_', ' ')}: {', '.join(strategies)}")
            
            return "\n".join(context_parts) if context_parts else "Strategy knowledge available in system prompt"
            
        except Exception as e:
            logger.error(f"Error getting strategy context: {e}")
            return "Strategy knowledge embedded in system training"
    
    def get_trading_intelligence_context(
        self,
        strategy: str = None,
        pattern: str = None,
        score_setup: bool = False,
        setup_params: Dict = None
    ) -> str:
        """Get comprehensive trading intelligence context for AI"""
        try:
            ti = self.trading_intelligence
            context_parts = []
            
            # Get comprehensive context
            if strategy or pattern:
                context_parts.append(ti.get_comprehensive_context_for_ai(
                    strategy=strategy,
                    pattern=pattern,
                    market_analysis=True
                ))
            
            # Score a specific setup if requested
            if score_setup and setup_params:
                score_result = ti.score_trade_setup(**setup_params)
                context_parts.append(f"""
=== SETUP SCORE ANALYSIS ===
Symbol: {score_result['symbol']}
Strategy: {score_result['strategy']}
Direction: {score_result['direction']}

TOTAL SCORE: {score_result['total_score']}/100
GRADE: {score_result['grade']}
RECOMMENDATION: {score_result['position_recommendation']}

Score Breakdown:
- Volume: {score_result['score_breakdown']['volume_score']}/15
- Time: {score_result['score_breakdown']['time_score']}/15
- Regime: {score_result['score_breakdown']['regime_score']}/20
- Pattern: {score_result['score_breakdown']['pattern_score']}/15
- Catalyst: {score_result['score_breakdown']['catalyst_score']}/15
- Technical: {score_result['score_breakdown']['technical_score']}/10
- R:R: {score_result['score_breakdown']['risk_reward_score']}/10
- Synergy Bonus: {score_result['score_breakdown']['synergy_bonus']}

Reasoning:
{chr(10).join('• ' + r for r in score_result['reasoning'])}

Warnings:
{chr(10).join('⚠️ ' + w for w in score_result['warnings']) if score_result['warnings'] else '✅ No warnings'}

DECISION: {score_result['trade_or_skip']}
""")
            
            return "\n".join(context_parts) if context_parts else ""
            
        except Exception as e:
            logger.warning(f"Error getting trading intelligence context: {e}")
            return ""
    
    async def _get_or_create_conversation(self, session_id: str, user_id: str = "default") -> ConversationContext:
        """Get existing conversation or create new one"""
        if session_id not in self.conversations:
            self.conversations[session_id] = ConversationContext(
                session_id=session_id,
                user_id=user_id
            )
            # Load from DB if available
            if self.db is not None:
                await self._load_conversation_from_db(session_id)
        
        return self.conversations[session_id]
    
    async def _load_conversation_from_db(self, session_id: str):
        """Load conversation history from MongoDB"""
        if self.db is None:
            return
        
        try:
            collection = self.db["assistant_conversations"]
            doc = await asyncio.to_thread(collection.find_one, {"session_id": session_id})
            if doc:
                self.conversations[session_id] = ConversationContext(
                    messages=[AssistantMessage(**m) for m in doc.get("messages", [])],
                    session_id=session_id,
                    user_id=doc.get("user_id", "default"),
                    created_at=doc.get("created_at", datetime.now(timezone.utc).isoformat()),
                    last_activity=doc.get("last_activity", datetime.now(timezone.utc).isoformat())
                )
        except Exception as e:
            logger.warning(f"Error loading conversation: {e}")
    
    async def _save_conversation_to_db(self, session_id: str):
        """Save conversation to MongoDB"""
        if self.db is None:
            return
        
        try:
            conv = self.conversations.get(session_id)
            if not conv:
                return
            
            collection = self.db["assistant_conversations"]
            
            # Limit stored messages to last 50 to manage memory
            messages_to_save = conv.messages[-50:] if len(conv.messages) > 50 else conv.messages
            
            await asyncio.to_thread(
                collection.update_one,
                {"session_id": session_id},
                {"$set": {
                    "session_id": session_id,
                    "user_id": conv.user_id,
                    "messages": [{"role": m.role, "content": m.content, "timestamp": m.timestamp, "metadata": m.metadata} for m in messages_to_save],
                    "created_at": conv.created_at,
                    "last_activity": datetime.now(timezone.utc).isoformat()
                }},
                True  # upsert
            )
        except Exception as e:
            logger.warning(f"Error saving conversation: {e}")
    
    async def _track_request_pattern(self, user_message: str):
        """Track frequently asked requests"""
        # Normalize the message
        normalized = user_message.lower().strip()
        
        # Extract key patterns
        patterns = []
        if "should i" in normalized:
            patterns.append("trade_decision")
        if "analyze" in normalized or "analysis" in normalized:
            patterns.append("analysis")
        if "quality" in normalized:
            patterns.append("quality_check")
        if "rule" in normalized:
            patterns.append("rule_check")
        if "backtest" in normalized:
            patterns.append("backtest")
        if "journal" in normalized or "trades" in normalized:
            patterns.append("journal_review")
        if any(word in normalized for word in ["premarket", "pre-market", "morning"]):
            patterns.append("premarket_briefing")
        
        for pattern in patterns:
            self.request_patterns[pattern] = self.request_patterns.get(pattern, 0) + 1
        
        # Save patterns to DB
        if self.db is not None:
            try:
                await asyncio.to_thread(
                    self.db["assistant_patterns"].update_one,
                    {"type": "request_patterns"},
                    {"$set": {"patterns": self.request_patterns, "updated_at": datetime.now(timezone.utc).isoformat()}},
                    True  # upsert
                )
            except Exception as e:
                logger.warning(f"Error saving patterns: {e}")
    
    def get_suggested_requests(self) -> List[Dict]:
        """Get frequently asked request suggestions"""
        suggestions = [
            {"pattern": "premarket_briefing", "text": "Give me a pre-market briefing", "icon": "sunrise"},
            {"pattern": "analysis", "text": "Analyze [SYMBOL] for me", "icon": "search"},
            {"pattern": "trade_decision", "text": "Should I buy [SYMBOL]?", "icon": "help-circle"},
            {"pattern": "quality_check", "text": "What's the quality score on [SYMBOL]?", "icon": "award"},
            {"pattern": "journal_review", "text": "Review my recent trades", "icon": "book"},
            {"pattern": "rule_check", "text": "What are my trading rules for gaps?", "icon": "list"},
        ]
        
        # Sort by frequency
        sorted_suggestions = sorted(
            suggestions,
            key=lambda x: self.request_patterns.get(x["pattern"], 0),
            reverse=True
        )
        
        return sorted_suggestions[:6]
    

    async def _get_alert_reasoning_context(self, user_message: str) -> Optional[str]:
        """
        If user is asking about an alert's reasoning, fetch the full alert data
        and return it as context for the AI to explain.
        """
        msg_lower = user_message.lower()
        
        # Detect reasoning/explanation questions
        reasoning_patterns = [
            "explain", "reasoning", "why", "how come", "what made you",
            "why did", "tell me about", "walk me through", "break down",
            "what's the thesis", "what's your thesis", "logic behind"
        ]
        
        pattern_match = any(p in msg_lower for p in reasoning_patterns)
        
        if not pattern_match:
            return None
        
        # Extract symbol from message - look for ticker patterns
        # Tickers are usually 1-5 uppercase letters, often prefixed with $
        import re
        
        # First, try to find explicit $TICKER mentions (most reliable)
        explicit_tickers = re.findall(r'\$([A-Z]{1,5})\b', user_message.upper())
        
        # If no explicit tickers, try context-based extraction
        if not explicit_tickers:
            # Look for patterns like "on TICKER", "for TICKER", "about TICKER"
            # This is more reliable than just extracting all uppercase words
            context_patterns = [
                r'(?:on|for|about|trade|trading|alert|buy|sell)\s+([A-Z]{1,5})\b',
                r'\b([A-Z]{1,5})\s+(?:trade|alert|setup|stock|position)',
            ]
            
            symbols = []
            for pattern in context_patterns:
                matches = re.findall(pattern, user_message.upper())
                symbols.extend(matches)
            
            # Remove duplicates while preserving order
            symbols = list(dict.fromkeys(symbols))
            
            # If still no matches, fall back to all uppercase words with extensive filtering
            if not symbols:
                all_matches = re.findall(r'\b([A-Z]{2,5})\b', user_message.upper())
                
                # Extended list of common English words to exclude
                excluded = {
                    # Question/common words
                    'THE', 'AND', 'FOR', 'WHY', 'HOW', 'THIS', 'THAT', 'YOUR', 'WHAT', 'WHEN', 'WHERE',
                    'EXPLAIN', 'PLAIN', 'BREAK', 'DOWN', 'WALK', 'ABOUT', 'MADE', 'COME', 'LOGIC',
                    'TELL', 'SHOW', 'GIVE', 'TAKE', 'MAKE', 'DOES', 'WILL', 'HAVE', 'BEEN', 'FROM',
                    'TRADE', 'ALERT', 'TAKING', 'BUY', 'SELL', 'LONG', 'SHORT', 'STOP', 'LOSS',
                    'ENTRY', 'EXIT', 'PRICE', 'STOCK', 'SHARE', 'MARKET', 'SETUP', 'PLAY',
                    'WITH', 'INTO', 'JUST', 'ONLY', 'ALSO', 'SOME', 'THEM', 'THAN', 'THEN', 'VERY',
                    'HERE', 'THERE', 'WERE', 'THEY', 'THESE', 'THOSE', 'WOULD', 'COULD', 'SHOULD',
                    'REASONING', 'REASON', 'THINK', 'THOUGHT', 'THESIS', 'BEHIND', 'THROUGH',
                    # Short common words
                    'ON', 'IN', 'TO', 'OF', 'AT', 'BY', 'AS', 'IS', 'IT', 'AN', 'OR', 'IF', 'SO', 'UP',
                    'NO', 'GO', 'DO', 'ME', 'MY', 'HE', 'WE', 'BE', 'AM',
                    # Pronouns and common words
                    'YOU', 'CAN', 'DID', 'ARE', 'WAS', 'HAS', 'HAD', 'GET', 'GOT', 'PUT', 'SAY',
                    'NOT', 'NOW', 'NEW', 'OLD', 'OUR', 'OUT', 'OWN', 'TOO', 'TWO', 'USE', 'WAY',
                    'ALL', 'ANY', 'BUT', 'HER', 'HIM', 'HIS', 'ITS', 'LET', 'MAY', 'ONE', 'SAW',
                    'SEE', 'SET', 'SHE', 'TRY', 'WHO', 'KNOW', 'WANT', 'LIKE', 'NEED', 'LOOK',
                    'GOOD', 'BEST', 'BACK', 'COME', 'OVER', 'SUCH', 'MUCH', 'MORE', 'MOST', 'LAST',
                    'FIRST', 'BEING', 'AFTER', 'WHILE', 'AGAIN', 'THERE', 'SINCE'
                }
                symbols = [s for s in all_matches if s not in excluded]
        else:
            symbols = explicit_tickers
        
        if not symbols:
            logger.debug("No symbols found in reasoning question")
            return None
        
        target_symbol = symbols[0]
        logger.info(f"🔍 Looking for alert reasoning for {target_symbol}")
        
        try:
            alert = None
            
            # First, try to get from live alerts API
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get("http://localhost:8001/api/live-scanner/alerts", timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    alerts_data = data.get("alerts", [])
                    logger.info(f"📋 Found {len(alerts_data)} live alerts")
                    
                    # Find alert for this symbol
                    for a in alerts_data:
                        if a.get("symbol") == target_symbol:
                            alert = a
                            break
                
                # Also check simulator alerts if not found in live alerts
                if not alert:
                    sim_response = await client.get("http://localhost:8001/api/simulator/alerts", timeout=5.0)
                    if sim_response.status_code == 200:
                        sim_data = sim_response.json()
                        sim_alerts = sim_data.get("alerts", [])
                        logger.info(f"📋 Found {len(sim_alerts)} simulator alerts")
                        
                        for a in sim_alerts:
                            if a.get("symbol") == target_symbol:
                                alert = a
                                logger.info(f"✅ Found alert in simulator for {target_symbol}")
                                break
            
            # If not found in live alerts, check MongoDB for recent alerts (last 1 hour)
            if not alert and self.db is not None:
                try:
                    from datetime import timedelta
                    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
                    
                    # Search in live_alerts collection
                    db_alert = await asyncio.to_thread(
                        self.db["live_alerts"].find_one,
                        {
                            "symbol": target_symbol,
                            "timestamp": {"$gte": cutoff_time.isoformat()}
                        },
                        sort=[("timestamp", -1)]
                    )
                    
                    if db_alert:
                        logger.info(f"✅ Found alert in MongoDB for {target_symbol}")
                        # Convert MongoDB doc to dict format
                        alert = {
                            "symbol": db_alert.get("symbol"),
                            "setup_type": db_alert.get("setup_type"),
                            "strategy_name": db_alert.get("strategy_name"),
                            "direction": db_alert.get("direction", "long"),
                            "priority": db_alert.get("priority", "medium"),
                            "current_price": db_alert.get("current_price", 0),
                            "trigger_price": db_alert.get("trigger_price", 0),
                            "stop_loss": db_alert.get("stop_loss", 0),
                            "target": db_alert.get("target", 0),
                            "risk_reward": db_alert.get("risk_reward", 0),
                            "trigger_probability": db_alert.get("trigger_probability", 0),
                            "win_probability": db_alert.get("win_probability", 0),
                            "strategy_win_rate": db_alert.get("strategy_win_rate", 0),
                            "reasoning": db_alert.get("reasoning", []),
                            "time_window": db_alert.get("time_window"),
                            "market_regime": db_alert.get("market_regime"),
                            "volatility_regime": db_alert.get("volatility_regime"),
                            "tape_confirmation": db_alert.get("tape_confirmation", False),
                            "tape_score": db_alert.get("tape_score", 0),
                        }
                except Exception as e:
                    logger.warning(f"MongoDB alert lookup error: {e}")
            
            if not alert:
                logger.info(f"❌ No alert found for {target_symbol} in live alerts or MongoDB")
                return None
            
            logger.info(f"✅ Found alert for {target_symbol}: {alert.get('setup_type')}")
            
            # Build detailed context from alert data (dict format from API)
            context_lines = [
                f"**📊 SCANNER ALERT DETAILS FOR {alert.get('symbol')}:**",
                f"",
                f"**Setup Type:** {alert.get('setup_type')} ({alert.get('strategy_name', 'N/A')})",
                f"**Direction:** {alert.get('direction', 'long').upper()}",
                f"**Priority:** {alert.get('priority', 'medium').upper()}",
                f"",
                f"**Price Levels:**",
                f"- Current Price: ${alert.get('current_price', 0):.2f}",
                f"- Entry/Trigger: ${alert.get('trigger_price', 0):.2f}",
                f"- Stop Loss: ${alert.get('stop_loss', 0):.2f}",
                f"- Target: ${alert.get('target', 0):.2f}",
                f"- Risk/Reward: {alert.get('risk_reward', 0):.1f}:1",
                f"",
                f"**Probabilities:**",
                f"- Trigger Probability: {alert.get('trigger_probability', 0):.0%}",
                f"- Win Probability: {alert.get('win_probability', 0):.0%}",
                f"- Strategy Historical Win Rate: {alert.get('strategy_win_rate', 0):.0%}",
                f"",
                f"**🎯 REASONING (Why this alert was generated):**"
            ]
            
            # Add each reasoning point
            reasoning = alert.get("reasoning", [])
            if reasoning:
                for reason in reasoning:
                    context_lines.append(f"- {reason}")
            else:
                context_lines.append("- No specific reasoning provided")
            
            context_lines.extend([
                f"",
                f"**Market Context:**",
                f"- Time Window: {alert.get('time_window', 'N/A')}",
                f"- Market Regime: {alert.get('market_regime', 'N/A')}",
                f"- Volatility: {alert.get('volatility_regime', 'N/A')}",
                f"- Tape Confirmation: {'Yes' if alert.get('tape_confirmation') else 'No'}",
                f"- Tape Score: {alert.get('tape_score', 0):.2f}",
            ])
            
            # Add Expected Value (EV) data if available
            setup_type = alert.get('setup_type', '').split('_long')[0].split('_short')[0]
            try:
                from services.ev_tracking_service import get_ev_service
                ev_service = get_ev_service(self.db)
                ev_report = ev_service.get_ev_report(setup_type)
                if ev_report and ev_report.get('total_trades', 0) >= 5:
                    context_lines.extend([
                        f"",
                        f"**📈 EXPECTED VALUE (SMB-Style Edge Assessment):**",
                        f"- Historical Win Rate: {ev_report.get('win_rate', 0):.1%}",
                        f"- Average Win: {ev_report.get('avg_win_r', 0):.2f}R",
                        f"- Average Loss: {ev_report.get('avg_loss_r', 1):.2f}R",
                        f"- Expected Value: {ev_report.get('expected_value_r', 0):.2f}R per trade",
                        f"- EV Gate: {ev_report.get('ev_gate', 'TRACK')}",
                        f"- Size Recommendation: {ev_report.get('size_multiplier', 1.0):.1f}x base position",
                        f"- Sample Size: {ev_report.get('total_trades', 0)} trades",
                        f"- Trading Recommendation: {ev_report.get('recommendation', 'N/A')}",
                    ])
            except Exception as e:
                logger.debug(f"Could not fetch EV data: {e}")
            
            context_lines.extend([
                f"",
                f"**IMPORTANT: Use this SPECIFIC data to explain the reasoning for the {alert.get('symbol')} trade alert.**",
                f"Reference the actual reasoning points and EV statistics above. Do NOT give generic advice."
            ])
            
            result = "\n".join(context_lines)
            logger.info(f"📝 Built alert reasoning context ({len(result)} chars)")
            return result
            
        except Exception as e:
            logger.warning(f"Error getting alert reasoning context: {e}")
            import traceback
            logger.warning(traceback.format_exc())
            return None

    async def _build_context(self, user_message: str, session_id: str) -> str:
        """Build context string with relevant knowledge and data"""
        logger.info(f"📝 Building context for: '{user_message[:50]}...' USE_SMART_CONTEXT={USE_SMART_CONTEXT}")
        # Try smart context engine first if enabled (proof of concept)
        if USE_SMART_CONTEXT:
            try:
                smart_context = await asyncio.wait_for(
                    self._build_smart_context(user_message, session_id),
                    timeout=15.0  # Faster timeout for smart context
                )
                if smart_context and len(smart_context) > 100:
                    logger.info(f"Smart context: {len(smart_context)} chars (vs traditional ~2000)")
                    return smart_context
            except asyncio.TimeoutError:
                logger.warning("Smart context timed out, falling back to traditional")
            except Exception as e:
                logger.warning(f"Smart context error: {e}, falling back to traditional")
        
        # Fall back to traditional context building
        try:
            return await asyncio.wait_for(
                self._build_context_internal(user_message, session_id),
                timeout=30.0  # 30 second timeout for all context gathering
            )
        except asyncio.TimeoutError:
            logger.warning("Context building timed out, using minimal context")
            return self._get_base_system_prompt()
    
    async def _build_smart_context(self, user_message: str, session_id: str) -> str:
        """
        Build context using smart intent detection (PROOF OF CONCEPT).
        Fetches only relevant data based on what the user is asking.
        """
        try:
            from services.smart_context_engine import get_smart_context_engine
            
            engine = get_smart_context_engine()
            
            # Detect intent
            intent_result = engine.detect_intent(user_message)
            logger.info(f"Detected intent: {intent_result.primary_intent.value} "
                       f"(confidence: {intent_result.confidence:.2f}, symbols: {intent_result.symbols})")
            
            # Prepare services dict
            alpaca = self.alpaca_service if hasattr(self, 'alpaca_service') else None
            logger.info(f"🔍 Smart context services - Alpaca: {'CONNECTED' if alpaca else 'NONE'}")
            services = {
                "alpaca": alpaca,
                "technical": self.technical_service if hasattr(self, 'technical_service') else None,
            }
            
            # Try to get scanner
            try:
                from services.enhanced_scanner import get_enhanced_scanner
                services["scanner"] = get_enhanced_scanner()
            except:
                pass
            
            # Try to get bot service
            try:
                from services.trading_bot_service import get_trading_bot_service
                services["bot"] = get_trading_bot_service()
            except:
                pass
            
            # Try to get earnings service
            try:
                from services.earnings_service import EarningsService
                services["earnings"] = EarningsService()
            except:
                pass
            
            # Try to get news service (now prioritizes IB news)
            try:
                from services.news_service import get_news_service
                news_svc = get_news_service()
                services["news"] = news_svc
                # Also set on the engine for direct access
                engine.news_service = news_svc
            except:
                pass
            
            # Gather context based on intent (also stores data for validation)
            smart_context, context_data = await engine.gather_context_with_data(intent_result, services)
            
            # Store context data for validation after LLM response
            self._last_context_data = context_data
            self._last_intent = intent_result
            self._last_smart_context = smart_context  # Store for position queries
            
            # Add base system prompt (use class attribute)
            base_prompt = self.SYSTEM_PROMPT
            
            # Combine with intent-specific instruction
            intent_instructions = {
                "price_check": "User wants a quick price update. Be concise - just the price and a brief note on direction.",
                "trade_decision": "User is considering a trade. Evaluate setup quality, check their risk exposure, and give a clear recommendation.",
                "position_review": "User wants to review their positions. Summarize P&L, highlight any concerns, suggest actions if needed.",
                "market_overview": "User wants market context. Give a brief overview of indices, regime, and notable moves.",
                "stock_analysis": "User wants analysis on a stock. Cover technicals, news, and any relevant setups.",
                "scanner_alerts": "User wants to see setups. Show top alerts with win rates and priorities.",
                "bot_status": "User is checking on the trading bot. Show status, P&L, and any open trades.",
                "strategy_info": "User is asking about a trading strategy. Explain it clearly with entry/exit rules.",
                "risk_check": "User wants to understand their risk. Show concentration, exposure, and any warnings.",
                "news_check": "User wants news on a stock. Provide recent headlines and sentiment.",
                "technical_analysis": "User wants technical analysis. Show key levels, indicators, and patterns.",
                "general_chat": "General trading chat. Be helpful and offer relevant trading assistance.",
            }
            
            intent_instruction = intent_instructions.get(intent_result.primary_intent.value, "")
            
            # Add learning context if available (TQS + personalized insights)
            learning_context = ""
            if hasattr(self, '_learning_context_provider') and self._learning_context_provider:
                try:
                    # Extract symbol from intent if present
                    symbol = intent_result.symbols[0] if intent_result.symbols else None
                    
                    # Only fetch learning context for trade-related intents
                    trade_intents = ["trade_decision", "stock_analysis", "scanner_alerts", "risk_check"]
                    if intent_result.primary_intent.value in trade_intents and symbol:
                        learning_context = await self._learning_context_provider.build_full_learning_context(
                            symbol=symbol,
                            user_query=user_message,
                            include_tqs=True,
                            include_performance=True,
                            include_edge_decay=True,
                            include_confirmations=False,  # Skip for speed
                            include_rag=False  # Skip for speed
                        )
                except Exception as e:
                    logger.warning(f"Learning context error: {e}")
            
            full_context = f"""{base_prompt}

=== INTENT DETECTED ===
{intent_instruction}

{smart_context}
{learning_context}"""
            
            return full_context
            
        except Exception as e:
            logger.error(f"Smart context build failed: {e}")
            raise
    
    async def _build_context_internal(self, user_message: str, session_id: str) -> str:
        """Internal context building with no timeout"""
        context_parts = []
        
        # Check if user is asking about news/market
        news_keywords = ['news', 'market', 'today', 'happening', 'morning', 'premarket', 'headlines', 'sentiment']
        wants_news = any(keyword in user_message.lower() for keyword in news_keywords)
        
        # 1. Get market news if relevant
        if wants_news:
            try:
                news_summary = await asyncio.wait_for(
                    self.news_service.get_market_summary(),
                    timeout=5.0
                )
                if news_summary.get("available"):
                    context_parts.append("TODAY'S MARKET NEWS:")
                    context_parts.append(f"Overall Sentiment: {news_summary.get('overall_sentiment', 'unknown').upper()}")
                    
                    themes = news_summary.get("themes", [])
                    if themes:
                        context_parts.append(f"Key Themes: {', '.join(themes)}")
                    
                    headlines = news_summary.get("headlines", [])
                    if headlines:
                        context_parts.append("\nTop Headlines:")
                        for i, headline in enumerate(headlines[:8], 1):
                            context_parts.append(f"  {i}. {headline}")
                    
                    sentiment = news_summary.get("sentiment_breakdown", {})
                    context_parts.append(f"\nSentiment: {sentiment.get('bullish', 0)} bullish, {sentiment.get('bearish', 0)} bearish, {sentiment.get('neutral', 0)} neutral")
                else:
                    context_parts.append("MARKET NEWS: Unavailable - check Alpaca API connection")
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"Error fetching news: {e}")
                context_parts.append("MARKET NEWS: Unavailable")
        
        # 2. Check if user is asking about strategies
        strategy_keywords = ['strategy', 'strategies', 'setup', 'setups', 'scalp', 'rubberband', 'rubber band', 
                            'breakout', 'momentum', 'vwap', 'bounce', 'fade', 'gap', 'squeeze', 'hitchhiker',
                            'spencer', 'range break', 'tidal wave', 'second chance', 'off sides', 'backside']
        wants_strategy_info = any(keyword in user_message.lower() for keyword in strategy_keywords)
        
        if wants_strategy_info:
            # Extract specific strategy name if mentioned
            strategy_name = None
            for kw in ['rubberband', 'rubber band', 'spencer', 'hitchhiker', 'vwap', 'breakout', 'momentum', 'gap']:
                if kw in user_message.lower():
                    strategy_name = kw.replace('rubberband', 'rubber band')
                    break
            
            strategy_context = self.get_strategy_context(strategy_name)
            context_parts.append(strategy_context)
        
        # 2b. Check if user is asking about CHART PATTERNS
        chart_pattern_keywords = ['pattern', 'patterns', 'triangle', 'flag', 'pennant', 'wedge', 'head and shoulders',
                                  'head & shoulders', 'double top', 'double bottom', 'triple top', 'triple bottom',
                                  'cup and handle', 'channel', 'diamond', 'rounding', 'wyckoff', 'megaphone',
                                  'broadening', 'rectangle', 'consolidation', 'reversal pattern', 'continuation pattern']
        wants_chart_patterns = any(keyword in user_message.lower() for keyword in chart_pattern_keywords)
        
        if wants_chart_patterns:
            # Extract specific pattern name if mentioned
            pattern_name = None
            specific_patterns = ['ascending triangle', 'descending triangle', 'bull flag', 'bear flag', 
                               'bull pennant', 'bear pennant', 'head and shoulders', 'inverse head',
                               'double top', 'double bottom', 'triple top', 'triple bottom',
                               'cup and handle', 'falling wedge', 'rising wedge', 'diamond',
                               'wyckoff', 'megaphone', 'rectangle', 'symmetrical triangle']
            for p in specific_patterns:
                if p in user_message.lower():
                    pattern_name = p
                    break
            
            # Detect bias preference
            bias = None
            if 'bullish' in user_message.lower():
                bias = 'bullish'
            elif 'bearish' in user_message.lower():
                bias = 'bearish'
            
            chart_pattern_context = self.get_chart_pattern_context(pattern_name, bias)
            context_parts.append(chart_pattern_context)
        
        # 2c. Check if user is asking about TECHNICAL INDICATORS (RSI, MACD, Bollinger, etc.)
        indicator_keywords = ['rsi', 'macd', 'bollinger', 'moving average', 'ema', 'sma', 'stochastic',
                             'fibonacci', 'fib', 'atr', 'volume analysis', 'indicator', 'oscillator',
                             'overbought', 'oversold', 'divergence', 'crossover', 'golden cross', 'death cross']
        wants_indicator_info = any(keyword in user_message.lower() for keyword in indicator_keywords)
        
        if wants_indicator_info:
            try:
                investopedia = self.investopedia_knowledge
                # Find specific indicator mentioned
                indicator_map = {
                    'rsi': 'rsi', 'relative strength': 'rsi',
                    'macd': 'macd', 'moving average convergence': 'macd',
                    'bollinger': 'bollinger_bands', 'bb': 'bollinger_bands',
                    'fibonacci': 'fibonacci_retracement', 'fib': 'fibonacci_retracement',
                    'moving average': 'moving_averages', 'ema': 'moving_averages', 'sma': 'moving_averages',
                    'stochastic': 'stochastic', 'atr': 'atr', 'average true range': 'atr',
                    'volume': 'volume'
                }
                
                for keyword, indicator_id in indicator_map.items():
                    if keyword in user_message.lower():
                        indicator_data = investopedia.get_indicator_knowledge(indicator_id)
                        if indicator_data:
                            context_parts.append(f"""
=== {indicator_data['name']} ===
Type: {indicator_data['type']}
{indicator_data['description']}

Calculation: {indicator_data['calculation']}

Interpretation: {indicator_data['interpretation']}

Signals: {', '.join([f"{k}: {v}" for k, v in list(indicator_data['signals'].items())[:4]])}

Trading Tips: {'; '.join(indicator_data['trading_tips'][:3])}
""")
                        break
            except Exception as e:
                logger.warning(f"Error getting indicator knowledge: {e}")
        
        # 2d. Check if user is asking about CANDLESTICK PATTERNS
        candlestick_keywords = ['doji', 'hammer', 'engulfing', 'shooting star', 'morning star', 'evening star',
                               'hanging man', 'spinning top', 'three white soldiers', 'three black crows',
                               'candlestick', 'candle pattern']
        wants_candlestick_info = any(keyword in user_message.lower() for keyword in candlestick_keywords)
        
        if wants_candlestick_info:
            try:
                investopedia = self.investopedia_knowledge
                # Find specific candlestick pattern
                candle_map = {
                    'doji': 'doji', 'hammer': 'hammer', 'engulfing': 'bullish_engulfing',
                    'bullish engulfing': 'bullish_engulfing', 'bearish engulfing': 'bearish_engulfing',
                    'shooting star': 'shooting_star', 'morning star': 'morning_star',
                    'evening star': 'evening_star', 'hanging man': 'hanging_man',
                    'spinning top': 'spinning_top', 'three white soldiers': 'three_white_soldiers',
                    'three black crows': 'three_black_crows', 'inverted hammer': 'inverted_hammer'
                }
                
                for keyword, pattern_id in candle_map.items():
                    if keyword in user_message.lower():
                        candle_data = investopedia.get_candlestick_pattern(pattern_id)
                        if candle_data:
                            context_parts.append(f"""
=== {candle_data['name']} Candlestick Pattern ===
Type: {candle_data['type']} candle | Bias: {candle_data['bias'].upper()}
{candle_data['description']}

Identification: {candle_data['identification']}
Psychology: {candle_data['psychology']}
Reliability: {candle_data['reliability']}
Trading Action: {candle_data['trading_action']}
""")
                        break
            except Exception as e:
                logger.warning(f"Error getting candlestick knowledge: {e}")
        
        # 2e. Check if user is asking about RISK MANAGEMENT
        risk_keywords = ['position size', 'position sizing', 'stop loss', 'risk reward', 'risk management',
                        'how much to risk', '1% rule', 'one percent', 'max loss', 'daily loss']
        wants_risk_info = any(keyword in user_message.lower() for keyword in risk_keywords)
        
        if wants_risk_info:
            try:
                investopedia = self.investopedia_knowledge
                risk_guide = investopedia.get_risk_management_guide()
                context_parts.append(f"""
=== RISK MANAGEMENT KNOWLEDGE ===

1% RULE: {risk_guide['one_percent_rule']['description']}
Formula: {risk_guide['one_percent_rule']['calculation']}

POSITION SIZING: {risk_guide['position_sizing']['description']}
Formula: {risk_guide['position_sizing']['formula']}

RISK-REWARD: Minimum {risk_guide['risk_reward_ratio']['minimum']}
{risk_guide['risk_reward_ratio']['importance']}

STOP LOSS METHODS: {', '.join(risk_guide['stop_loss_placement']['methods'][:3])}

DAILY LOSS LIMIT: {risk_guide['daily_loss_limit']['guideline']}
""")
            except Exception as e:
                logger.warning(f"Error getting risk management knowledge: {e}")
        
        # 2f. Check if user is asking about FUNDAMENTAL ANALYSIS
        fundamental_keywords = ['fundamental', 'fundamentals', 'valuation', 'p/e', 'pe ratio', 'price to earnings',
                               'p/b', 'pb ratio', 'price to book', 'peg ratio', 'roe', 'return on equity',
                               'debt to equity', 'd/e ratio', 'free cash flow', 'fcf', 'eps', 'earnings per share',
                               'dividend yield', 'price to sales', 'interest coverage', 'current ratio',
                               'intrinsic value', 'book value', 'overvalued', 'undervalued', 'fair value',
                               'financial health', 'balance sheet', 'income statement', 'cash flow statement']
        wants_fundamental_info = any(keyword in user_message.lower() for keyword in fundamental_keywords)
        
        if wants_fundamental_info:
            try:
                investopedia = self.investopedia_knowledge
                # Check for specific metric requested
                metric_map = {
                    'p/e': 'pe_ratio', 'pe ratio': 'pe_ratio', 'price to earnings': 'pe_ratio',
                    'p/b': 'pb_ratio', 'pb ratio': 'pb_ratio', 'price to book': 'pb_ratio',
                    'peg': 'peg_ratio', 'peg ratio': 'peg_ratio',
                    'roe': 'roe', 'return on equity': 'roe',
                    'debt to equity': 'debt_to_equity', 'd/e': 'debt_to_equity',
                    'free cash flow': 'free_cash_flow', 'fcf': 'free_cash_flow',
                    'eps': 'eps', 'earnings per share': 'eps',
                    'dividend yield': 'dividend_yield',
                    'price to sales': 'price_to_sales', 'p/s': 'price_to_sales',
                    'interest coverage': 'interest_coverage',
                    'current ratio': 'current_ratio'
                }
                
                # Check if asking about specific metric
                specific_metric_found = False
                for keyword, metric_id in metric_map.items():
                    if keyword in user_message.lower():
                        metric_data = investopedia.get_fundamental_metric(metric_id)
                        if metric_data:
                            context_parts.append(f"""
=== {metric_data['name']} ===
Category: {metric_data['category']}
{metric_data['description']}

Formula: {metric_data['formula']}

Interpretation: {metric_data['interpretation']}

Good Values: {metric_data['good_values']}

Trading Tips: {'; '.join(metric_data['trading_tips'][:3])}

Limitations: {'; '.join(metric_data['limitations'][:3])}
""")
                            specific_metric_found = True
                            break
                
                # If no specific metric, provide general fundamental context
                if not specific_metric_found:
                    fundamental_context = investopedia.get_fundamental_analysis_context_for_ai()
                    context_parts.append(fundamental_context)
                    
            except Exception as e:
                logger.warning(f"Error getting fundamental analysis knowledge: {e}")
        
        # 2f-b. If asking about fundamentals AND a specific ticker, fetch REAL-TIME data
        if wants_fundamental_info:
            # Extract potential stock symbols - use strict approach
            explicit_fund_tickers = re.findall(r'\$([A-Z]{1,5})\b', user_message.upper())
            
            # Known tickers to look for
            known_fund_tickers = {'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 
                                 'SPY', 'QQQ', 'NFLX', 'DIS', 'BA', 'JPM', 'V', 'MA', 'PYPL', 'SQ', 'COIN',
                                 'SHOP', 'PLTR', 'SOFI', 'INTC', 'MU', 'QCOM', 'CRM', 'ORCL', 'ADBE',
                                 'XOM', 'CVX', 'WMT', 'TGT', 'COST', 'HD', 'LOW', 'NKE', 'SBUX', 'MCD'}
            
            found_fund_tickers = [word for word in user_message.upper().split() 
                                  if word.strip('.,?!()') in known_fund_tickers]
            
            symbols_for_fundamentals = list(set(explicit_fund_tickers + found_fund_tickers))
            
            # Fetch real-time fundamentals for mentioned stocks
            if symbols_for_fundamentals:
                try:
                    from services.fundamental_data_service import get_fundamental_data_service
                    fundamental_service = get_fundamental_data_service()
                    
                    for symbol in symbols_for_fundamentals[:2]:  # Limit to 2 stocks to avoid slowdown
                        analysis = await fundamental_service.analyze_fundamentals(symbol)
                        if analysis.get("available"):
                            metrics = analysis.get("metrics", {})
                            valuation = metrics.get("valuation", {})
                            profitability = metrics.get("profitability", {})
                            growth = metrics.get("growth", {})
                            health = metrics.get("financial_health", {})
                            
                            context_parts.append(f"""
=== REAL-TIME FUNDAMENTAL DATA FOR {symbol} (from Finnhub) ===
Value Score: {analysis.get('value_score')}/100
Assessment: {analysis.get('assessment')}

VALUATION:
- P/E Ratio: {valuation.get('pe_ratio')}
- Forward P/E: {valuation.get('forward_pe')}
- P/B Ratio: {valuation.get('pb_ratio')}
- PEG Ratio: {valuation.get('peg_ratio')}

PROFITABILITY:
- ROE: {profitability.get('roe')}
- Net Margin: {profitability.get('net_margin')}
- Operating Margin: {profitability.get('operating_margin')}

GROWTH:
- EPS Growth (YoY): {growth.get('eps_growth_yoy')}
- Revenue Growth (YoY): {growth.get('revenue_growth_yoy')}

FINANCIAL HEALTH:
- Debt/Equity: {health.get('debt_to_equity')}
- Current Ratio: {health.get('current_ratio')}

Bullish Signals: {'; '.join(analysis.get('signals', [])[:3])}
Warnings: {'; '.join(analysis.get('warnings', [])[:3])}
""")
                except Exception as e:
                    logger.warning(f"Error fetching real-time fundamentals: {e}")
        
        # 2f-c. Check if user is asking about SETUPS, OPPORTUNITIES, or TRADES FORMING
        scanner_keywords = ['setup', 'setups', 'opportunity', 'opportunities', 'forming', 'trade ideas',
                          'what should i trade', 'what to trade', 'best trades', 'scanner', 'scan',
                          'alerts', 'imminent', 'about to trigger', 'rubber band', 'breakout forming',
                          'scalp', 'swing', 'squeeze', 'short squeeze', 'in play', 'watchlist']
        wants_scanner_info = any(keyword in user_message.lower() for keyword in scanner_keywords)
        
        if wants_scanner_info:
            try:
                # Primary: Use enhanced scanner for real-time alerts
                from services.enhanced_scanner import get_enhanced_scanner
                scanner = get_enhanced_scanner()
                live_alerts = scanner.get_live_alerts()
                
                if live_alerts:
                    alert_lines = ["\n**🔴 LIVE SCANNER ALERTS:**"]
                    for alert in live_alerts[:10]:  # Top 10
                        tape_icon = "✓" if alert.tape_confirmation else ""
                        priority_icon = "🔥" if alert.priority.value in ["high", "critical"] else ""
                        alert_lines.append(
                            f"- {priority_icon}**{alert.symbol}** {alert.direction.upper()} @ ${alert.current_price:.2f} - "
                            f"{alert.setup_type} (WR: {alert.strategy_win_rate:.0%}) {tape_icon}"
                        )
                    context_parts.append("\n".join(alert_lines))
                
                # Also get smart watchlist context
                try:
                    from services.smart_watchlist_service import get_smart_watchlist
                    watchlist = get_smart_watchlist()
                    wl_items = watchlist.get_watchlist()[:5]
                    if wl_items:
                        wl_lines = ["\n**📋 SMART WATCHLIST (Top 5):**"]
                        for item in wl_items:
                            source = "📌" if item.is_sticky else "🔍"
                            wl_lines.append(f"- {source} **{item.symbol}** ({item.timeframe.value}) - {len(item.strategies_matched)} strategies matched")
                        context_parts.append("\n".join(wl_lines))
                except Exception as wl_e:
                    logger.debug(f"Watchlist context error: {wl_e}")
                    
            except Exception as e:
                logger.warning(f"Error getting enhanced scanner context: {e}")
                # Fallback to alert system
                try:
                    from services.alert_system import get_alert_system
                    alert_system = get_alert_system()
                    alert_context = alert_system.get_alerts_summary_for_ai()
                    if alert_context:
                        context_parts.append(alert_context)
                except Exception as e2:
                    logger.warning(f"Error getting alert context: {e2}")
                    # Fallback to basic scanner
                    try:
                        from services.predictive_scanner import get_predictive_scanner
                        scanner = get_predictive_scanner()
                        scanner_context = scanner.get_setup_summary_for_ai()
                        if scanner_context and "No significant" not in scanner_context:
                            context_parts.append(scanner_context)
                    except Exception as e3:
                        logger.warning(f"Error getting scanner context: {e3}")
        
        # 2f-d. Get REAL-TIME TECHNICAL DATA for mentioned symbols
        # Extract symbols from message - use strict filtering to avoid common words
        # Only look for explicit ticker patterns like "$NVDA" or well-known stocks
        explicit_tickers = re.findall(r'\$([A-Z]{1,5})\b', user_message.upper())  # $NVDA format
        
        # Also check for known high-volume stocks mentioned
        known_tickers = {'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD', 
                        'SPY', 'QQQ', 'IWM', 'DIA', 'NFLX', 'DIS', 'BA', 'JPM', 'GS', 'V', 'MA',
                        'PYPL', 'SQ', 'COIN', 'SHOP', 'ROKU', 'SNAP', 'UBER', 'LYFT', 'ABNB',
                        'PLTR', 'SOFI', 'HOOD', 'RIVN', 'LCID', 'NIO', 'BABA', 'JD', 'PDD',
                        'INTC', 'MU', 'QCOM', 'AVGO', 'CRM', 'ORCL', 'IBM', 'CSCO', 'ADBE',
                        'XOM', 'CVX', 'OXY', 'BP', 'SHEL', 'WMT', 'TGT', 'COST', 'HD', 'LOW'}
        
        found_known_tickers = [word for word in user_message.upper().split() 
                               if word.strip('.,?!()') in known_tickers]
        
        symbols_for_technicals = list(set(explicit_tickers + found_known_tickers))
        
        # Get real-time technicals for mentioned stocks (limit to 2 to avoid rate limits)
        if symbols_for_technicals:
            try:
                for symbol in symbols_for_technicals[:2]:
                    snapshot = await self.technical_service.get_technical_snapshot(symbol)
                    if snapshot:
                        tech_context = self.technical_service.get_snapshot_for_ai(snapshot)
                        context_parts.append(tech_context)
            except Exception as e:
                logger.warning(f"Error getting real-time technicals: {e}")
        
        # 2g. Check if user is asking about SCORING, EVALUATING, or VALIDATING a trade
        evaluation_keywords = ['score', 'scoring', 'evaluate', 'grade', 'rate', 'quality', 'should i', 
                              'valid', 'validate', 'good trade', 'bad trade', 'a+ setup', 'setup quality',
                              'take this trade', 'enter', 'buy this', 'short this', 'trade idea']
        wants_evaluation = any(keyword in user_message.lower() for keyword in evaluation_keywords)
        
        # Extract symbols early for evaluation check
        early_symbols = re.findall(r'\b([A-Z]{1,5})\b', user_message.upper())
        common_words = {'I', 'A', 'THE', 'AND', 'OR', 'FOR', 'TO', 'IS', 'IT', 'IN', 'ON', 'AT', 'BY', 'BE', 'AS', 'AN', 'ARE', 'WAS', 'IF', 'MY', 'ME', 'DO', 'SO', 'UP', 'AM', 'CAN', 'HOW', 'WHAT', 'BUY', 'SELL', 'LONG', 'SHORT', 'NEWS', 'TODAY', 'MARKET', 'RSI', 'MACD', 'EMA', 'SMA', 'ATR', 'VWAP', 'BOT'}
        early_symbols = [s for s in early_symbols if s not in common_words and len(s) >= 2]
        
        if wants_evaluation and (wants_strategy_info or wants_chart_patterns or early_symbols):
            # Get comprehensive trading intelligence context
            try:
                strategy_for_context = None
                if wants_strategy_info:
                    for kw in ['rubberband', 'rubber band', 'spencer', 'hitchhiker', 'vwap', 'off sides', 'backside', 'gap']:
                        if kw in user_message.lower():
                            strategy_for_context = kw.replace('rubberband', 'rubber band')
                            break
                
                pattern_for_context = None
                if wants_chart_patterns:
                    pattern_for_context = pattern_name
                
                intelligence_context = self.get_trading_intelligence_context(
                    strategy=strategy_for_context,
                    pattern=pattern_for_context
                )
                if intelligence_context:
                    context_parts.append(intelligence_context)
            except Exception as e:
                logger.warning(f"Error getting trading intelligence context: {e}")
        
        # 3. Get relevant strategies from knowledge base
        try:
            relevant = self.knowledge_service.search(user_message, limit=5)
            if relevant:
                context_parts.append("\nRELEVANT KNOWLEDGE FROM YOUR TRAINING:")
                for item in relevant[:5]:
                    context_parts.append(f"- [{item.get('type', 'note').upper()}] {item.get('title', '')}: {item.get('content', '')[:200]}")
        except Exception as e:
            logger.warning(f"Error fetching knowledge: {e}")
        
        # 3. Get trading rules
        try:
            rules = self.knowledge_service.get_by_type("rule")
            if rules:
                context_parts.append("\nUSER'S TRADING RULES:")
                for rule in rules[:10]:
                    context_parts.append(f"- {rule.get('title', '')}: {rule.get('content', '')[:150]}")
        except Exception as e:
            logger.warning(f"Error fetching rules: {e}")
        
        # 4. Extract stock symbols from message and get data
        symbols = re.findall(r'\b([A-Z]{1,5})\b', user_message.upper())
        common_words = {'I', 'A', 'THE', 'AND', 'OR', 'FOR', 'TO', 'IS', 'IT', 'IN', 'ON', 'AT', 'BY', 'BE', 'AS', 'AN', 'ARE', 'WAS', 'IF', 'MY', 'ME', 'DO', 'SO', 'UP', 'AM', 'CAN', 'HOW', 'WHAT', 'BUY', 'SELL', 'LONG', 'SHORT', 'NEWS', 'TODAY', 'MARKET', 'BOT', 'DOES', 'HAVE', 'SHOW', 'TRADE', 'RIGHT', 'NOW', 'PENDING', 'OPEN', 'CLOSE', 'STATUS', 'THIS'}
        symbols = [s for s in symbols if s not in common_words and len(s) >= 2]
        
        # Check if this is a trading decision that needs fresh data
        trading_decision_keywords = ['should i', 'buy', 'sell', 'enter', 'exit', 'trade', 'long', 'short', 
                                     'is it', 'good entry', 'take profit', 'stop loss', 'setup', 'breakout']
        needs_fresh_data = any(kw in user_message.lower() for kw in trading_decision_keywords)
        
        if symbols:
            context_parts.append("\n📊 REAL-TIME STOCK DATA:")
            for symbol in symbols[:3]:
                try:
                    # Try IB pushed data first (real-time from user's broker)
                    ib_quote = self._get_ib_quote(symbol)
                    if ib_quote and ib_quote.get('price', 0) > 0:
                        quote = ib_quote
                    elif self.alpaca_service:
                        # Fall back to Alpaca if IB not available
                        quote = await self.alpaca_service.get_quote(symbol, force_refresh=needs_fresh_data)
                    else:
                        quote = None
                    
                    if quote:
                        price = quote.get('price', 0)
                        change = quote.get('change_percent', 0)
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        volume = quote.get('volume', 0)
                        emoji = "🟢" if change >= 0 else "🔴"
                        
                        context_parts.append(f"\n**{symbol}** (LIVE):")
                        context_parts.append(f"  💰 Price: ${price:.2f} {emoji} {change:+.2f}%")
                        if bid and ask:
                            spread = ((ask - bid) / price * 100) if price else 0
                            context_parts.append(f"  📈 Bid/Ask: ${bid:.2f} / ${ask:.2f} (spread: {spread:.2f}%)")
                        if volume:
                            context_parts.append(f"  📊 Volume: {volume:,}")
                    else:
                        context_parts.append(f"\n**{symbol}**: Quote unavailable")
                    
                    # Get quality score with timeout
                    async def get_quality_data():
                        quality = await self.quality_service.get_quality_metrics(symbol)
                        q_score = self.quality_service.calculate_quality_score(quality)
                        return quality, q_score
                    
                    try:
                        quality, q_score = await asyncio.wait_for(get_quality_data(), timeout=5.0)
                        context_parts.append(f"  ⭐ Quality Grade: {q_score.grade} ({q_score.composite_score}/400)")
                        context_parts.append(f"  📍 Signal: {q_score.quality_signal}")
                        if quality.roe:
                            context_parts.append(f"  📈 ROE: {quality.roe:.1%}, D/A: {quality.da:.1%}" if quality.da else f"  📈 ROE: {quality.roe:.1%}")
                    except asyncio.TimeoutError:
                        context_parts.append("  ⚠️ Quality data timeout")
                    
                    # Get ticker-specific news if mentioned (with timeout)
                    if wants_news:
                        try:
                            ticker_news = await asyncio.wait_for(
                                self.news_service.get_ticker_news(symbol, max_items=3),
                                timeout=3.0
                            )
                            if ticker_news and not ticker_news[0].get("is_placeholder"):
                                context_parts.append("  Recent News:")
                                for news_item in ticker_news[:3]:
                                    context_parts.append(f"    - {news_item.get('headline', '')[:100]}")
                        except (asyncio.TimeoutError, Exception):
                            pass
                except Exception as ex:
                    logger.warning(f"Error getting data for {symbol}: {ex}")
        
        # 5. Get trade history context for performance analysis
        trade_history_keywords = ['history', 'performance', 'trades', 'win rate', 'my trading', 'how am i doing', 'analyze my', 'review', 'p&l', 'pnl', 'metrics']
        wants_trade_history = any(keyword in user_message.lower() for keyword in trade_history_keywords)
        
        # Also check if asking about a specific symbol they may have traded
        symbol_history_request = symbols and any(keyword in user_message.lower() for keyword in ['traded', 'history', 'performance', 'did i', 'have i'])
        
        if wants_trade_history or symbol_history_request:
            try:
                primary_symbol = symbols[0] if symbols else None
                trade_history_context = await self.get_trade_history_context(primary_symbol)
                if trade_history_context and "not available" not in trade_history_context.lower():
                    context_parts.append(f"\n{trade_history_context}")
            except Exception as e:
                logger.warning(f"Error fetching trade history: {e}")
        
        # 5b. Get CURRENT POSITIONS context (always include if positions exist)
        position_keywords = ['position', 'positions', 'holding', 'portfolio', 'what do i have',
                           'my trades', 'what am i in', 'open position', 'unrealized', 'p&l',
                           'close', 'exit', 'sell', 'buy', 'tmc', 'intc', 'tsla', 'shares']
        wants_position_info = any(keyword in user_message.lower() for keyword in position_keywords)
        
        # Always try to include positions context for trading relevance
        # Prefer IB pushed positions, fallback to Alpaca
        try:
            positions = []
            
            # Try IB pushed positions first
            try:
                from routers.ib import get_pushed_positions, is_pusher_connected
                logger.info(f"[Context] Checking IB pusher connection...")
                is_connected = is_pusher_connected()
                logger.info(f"[Context] IB pusher connected: {is_connected}")
                if is_connected:
                    ib_positions = get_pushed_positions()
                    logger.info(f"[Context] IB positions fetched: {len(ib_positions)}")
                    if ib_positions:
                        positions = [{
                            'symbol': p.get('symbol'),
                            'qty': p.get('position', p.get('qty', 0)),
                            'avg_entry_price': p.get('avg_cost', p.get('avgCost', 0)),
                            'current_price': p.get('market_price', p.get('marketPrice', 0)),
                            'market_value': p.get('market_value', p.get('marketValue', 0)),
                            'unrealized_pnl': p.get('unrealized_pnl', p.get('unrealizedPNL', 0)),
                            'source': 'ib_gateway'
                        } for p in ib_positions]
                        logger.info(f"[Context] Mapped {len(positions)} IB positions for AI context")
            except Exception as e:
                logger.warning(f"[Context] IB positions fetch error: {e}")
            
            # Fallback to Alpaca if no IB positions
            if not positions and self.alpaca_service:
                positions = await self.alpaca_service.get_positions()
            
            if positions:
                pos_lines = ["\n=== YOUR CURRENT POSITIONS ==="]
                total_unrealized = 0
                total_market_value = 0
                
                for pos in positions:
                    symbol = pos.get('symbol', 'UNK')
                    qty = float(pos.get('qty', 0))
                    avg_price = float(pos.get('avg_entry_price', 0))
                    current_price = float(pos.get('current_price', 0))
                    market_value = float(pos.get('market_value', 0))
                    unrealized = float(pos.get('unrealized_pnl', 0) or pos.get('unrealized_pl', 0) or 0)
                    unrealized_pct = float(pos.get('unrealized_plpc', 0) or pos.get('unrealized_pnl_percent', 0) or 0) * 100
                    side = 'LONG' if qty > 0 else 'SHORT'
                    
                    total_unrealized += unrealized
                    total_market_value += abs(market_value)
                    
                    pos_lines.append(
                        f"- **{symbol}** ({side}): {abs(qty):.0f} shares @ ${avg_price:.2f} avg | "
                        f"Current: ${current_price:.2f} | P&L: ${unrealized:+.2f} ({unrealized_pct:+.2f}%)"
                    )
                
                pos_lines.append(f"\n📊 TOTAL: {len(positions)} positions | Market Value: ${total_market_value:,.2f} | Unrealized P&L: ${total_unrealized:+.2f}")
                context_parts.append("\n".join(pos_lines))
            elif wants_position_info:
                context_parts.append("\n=== YOUR CURRENT POSITIONS ===\nNo open positions currently.")
        except Exception as e:
            logger.warning(f"Error fetching positions context: {e}")
            if wants_position_info:
                context_parts.append("\n=== POSITIONS ===\nUnable to fetch positions - check broker connection.")
        
        # 6. Knowledge base stats
        try:
            stats = self.knowledge_service.get_stats()
            context_parts.append(f"\nKNOWLEDGE BASE: {stats.get('total_entries', 0)} entries ({stats.get('by_type', {}).get('strategy', 0)} strategies, {stats.get('by_type', {}).get('rule', 0)} rules)")
        except Exception:
            pass
        
        # 7. Trading Bot context - if user asks about bot, its trades, or performance
        bot_keywords = ['bot', 'trading bot', 'bot trade', 'bot performance', 'bot status', 
                       'what did the bot', 'bot do', 'bot position', 'autonomous', 'bot p&l',
                       'bot pnl', 'bot closed', 'bot open', 'pending trade', 'bot took',
                       'why did the bot', 'explain trade', 'bot running']
        wants_bot_info = any(keyword in user_message.lower() for keyword in bot_keywords)
        
        if wants_bot_info and self._trading_bot:
            try:
                bot_context = self._trading_bot.get_bot_context_for_ai()
                context_parts.append(bot_context)
            except Exception as e:
                logger.warning(f"Error getting bot context: {e}")
        
        # 8. Learning loop context - if user asks about performance, recommendations, tuning
        learning_keywords = ['performance', 'win rate', 'strategy stats', 'how are my strategies',
                           'recommendation', 'tuning', 'learning', 'which strategy', 'best strategy',
                           'worst strategy', 'improve', 'optimize', 'analytics', 'auto-tun']
        wants_learning = any(keyword in user_message.lower() for keyword in learning_keywords)
        
        if wants_learning and self._trading_bot and hasattr(self._trading_bot, '_perf_service'):
            try:
                perf_service = self._trading_bot._perf_service
                learning_context = perf_service.get_learning_summary_for_ai()
                context_parts.append(learning_context)
            except Exception as e:
                logger.warning(f"Error getting learning context: {e}")
        
        return "\n".join(context_parts)
    
    async def _call_llm(self, messages: List[Dict], context: str = "", complexity: str = "standard") -> str:
        """
        Call the LLM with smart routing.
        
        OLLAMA-FIRST with QUICK HEALTH CHECK:
        - Ping Ollama (5s timeout) - if healthy, use it (FREE)
        - If Ollama slow/down, fall back to cloud AI (Emergent/GPT-4o)
        
        This saves credits while maintaining reliability.
        """
        from datetime import datetime, timezone, timedelta
        import httpx
        
        # Build the full message list with system prompt
        full_messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT + "\n\n" + context}
        ]
        full_messages.extend(messages)
        
        # Check if Ollama should be skipped due to recent failures
        skip_ollama = False
        if self._ollama_skip_until and datetime.now(timezone.utc) < self._ollama_skip_until:
            logger.info(f"⏭️ Skipping Ollama (cooling down)")
            skip_ollama = True
        
        # PRIORITY 1: Check for HTTP Ollama Proxy (most reliable, no WebSocket issues)
        if not skip_ollama:
            try:
                # Import the HTTP proxy checker from server
                from server import is_http_ollama_proxy_connected, call_ollama_via_http_proxy
                
                if is_http_ollama_proxy_connected():
                    logger.info("🔌 Using Local Ollama Proxy (HTTP polling)")
                    
                    # Primary model: gpt-oss:120b-cloud (cloud model via local Ollama)
                    # Fallback: llama3:8b (pure local)
                    model = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud")
                    
                    logger.info(f"📦 Using model: {model}")
                    
                    # Build context for proxy - allow more context for position queries
                    # For position queries, use smart_context directly which has the IB data
                    # For other queries, use the full context but with higher limit
                    is_position_query = any(kw in messages[-1].get("content", "").lower() 
                                           for kw in ["position", "holdings", "shares", "average cost", "p&l", 
                                                      "close", "exit", "sell", "tmc", "intc", "tsla", "bldp", "nio"])
                    
                    if is_position_query and hasattr(self, '_last_context_data') and self._last_context_data:
                        # For position queries, use just the smart context with positions
                        # This avoids truncating the position data
                        position_context = getattr(self, '_last_smart_context', context)
                        if len(position_context) < 3000:  # Smart context is typically small
                            truncated_context = position_context
                        else:
                            truncated_context = context[:8000]  # Allow more for position queries
                    else:
                        max_context = 8000 if complexity == "deep" else 6000
                        truncated_context = context[:max_context] if len(context) > max_context else context
                    
                    proxy_messages = [
                        {"role": "system", "content": f"""You are an expert trading assistant with REAL-TIME market data.
The data below is LIVE from the user's IB Gateway brokerage account - this is REAL data, not simulated.

CRITICAL: When the user asks about positions, ONLY report the positions shown in the "YOUR POSITIONS" section below.
DO NOT make up or hallucinate any positions. If you see TMC, INTC, TSLA in the data, report THOSE - not SPY, QQQ, AAPL or other symbols.

{truncated_context}

REMEMBER: Only use the EXACT data provided above. Do not invent positions or prices."""},
                        {"role": "user", "content": messages[-1]["content"] if messages else ""}
                    ]
                    
                    # Adjust options based on model
                    # gpt-oss:120b-cloud can handle larger context, use more tokens
                    if "120b" in model.lower() or "gpt-oss" in model.lower():
                        ollama_options = {"num_ctx": 8192, "temperature": 0.7, "num_predict": 2048}
                    elif "deepseek" in model.lower():
                        # Deepseek-r1 has extended reasoning - give it more room
                        ollama_options = {"num_ctx": 4096, "temperature": 0.5, "num_predict": 1500}
                    else:
                        ollama_options = {"num_ctx": 4096, "temperature": 0.7, "num_predict": 1024}
                    
                    result = await call_ollama_via_http_proxy(
                        model=model,
                        messages=proxy_messages,
                        options=ollama_options,
                        timeout=180.0  # 3 minutes for cloud model with complex context
                    )
                    
                    if result.get("success"):
                        content = result.get("response", {}).get("message", {}).get("content", "")
                        if content:
                            logger.info(f"✅ Ollama Cloud ({model}) response OK ({len(content)} chars)")
                            return content
                    else:
                        error_msg = result.get('error', 'Unknown error')
                        logger.warning(f"⚠️ Ollama Cloud failed: {error_msg}")
                        
                        # If cloud model failed, try local fallback
                        if "120b" in model.lower() or "cloud" in model.lower() or "gpt-oss" in model.lower():
                            fallback_model = "llama3:8b"  # Local fallback
                            
                            logger.info(f"🔄 Cloud model failed, trying local fallback ({fallback_model})...")
                            fallback_result = await call_ollama_via_http_proxy(
                                model=fallback_model,
                                messages=proxy_messages,
                                options={"num_ctx": 4096, "temperature": 0.7, "num_predict": 1024},
                                timeout=60.0
                            )
                            if fallback_result.get("success"):
                                content = fallback_result.get("response", {}).get("message", {}).get("content", "")
                                if content:
                                    logger.info(f"✅ Local fallback ({fallback_model}) response OK")
                                    return content
            except ImportError:
                pass  # HTTP proxy not available
            except Exception as e:
                logger.warning(f"⚠️ HTTP Ollama Proxy error: {e}")
        
        # PRIORITY 2: Check for WebSocket Ollama Proxy (fallback)
        if not skip_ollama and ollama_proxy_manager and ollama_proxy_manager.is_connected:
            try:
                logger.info("🔌 Using Local Ollama Proxy (WebSocket connection)")
                
                # Get model from config or use default
                model = "qwen2.5:7b"
                if LLMProvider.OLLAMA in self.llm_clients:
                    model = self.llm_clients[LLMProvider.OLLAMA].get("model", "qwen2.5:7b")
                
                # Build context for proxy
                max_context = 4000 if complexity == "deep" else 2000
                truncated_context = context[:max_context] if len(context) > max_context else context
                
                proxy_messages = [
                    {"role": "system", "content": f"""You are an expert trading assistant with REAL-TIME market data.
The data below is LIVE - use it to answer questions directly.

{truncated_context}

Be concise and reference the data above."""},
                    {"role": "user", "content": messages[-1]["content"] if messages else ""}
                ]
                
                result = await ollama_proxy_manager.chat(
                    model=model,
                    messages=proxy_messages,
                    options={"num_ctx": 2048, "temperature": 0.7, "num_predict": 512}
                )
                
                if result.get("success") and result.get("content"):
                    logger.info(f"✅ Ollama Proxy response OK ({len(result['content'])} chars) - FREE")
                    return result["content"]
                else:
                    logger.warning(f"⚠️ Ollama Proxy failed: {result.get('error')}")
                    
            except Exception as e:
                logger.warning(f"⚠️ Ollama Proxy error: {e}")
        
        # PRIORITY 2: Direct Ollama via ngrok (fallback)
        ollama_healthy = False
        if not skip_ollama and LLMProvider.OLLAMA in self.llm_clients:
            try:
                ollama_cfg = self.llm_clients[LLMProvider.OLLAMA]
                ping_url = f"{ollama_cfg['url']}/api/tags"
                
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    ping_response = await client.get(
                        ping_url,
                        headers={"ngrok-skip-browser-warning": "true"}
                    )
                    if ping_response.status_code == 200:
                        ollama_healthy = True
                        logger.info("✅ Ollama ping OK - using local AI (FREE)")
            except Exception as e:
                logger.debug(f"⚠️ Ollama ping failed: {e}")
        
        # USE OLLAMA if healthy (saves credits!) - LOCAL AI FIRST
        if ollama_healthy:
            try:
                ollama_cfg = self.llm_clients[LLMProvider.OLLAMA]
                url = f"{ollama_cfg['url']}/api/chat"
                
                # For market/deep queries, use moderate context to fit in 4GB VRAM
                # qwen2.5:7b needs ~2.4GB for model, ~0.15GB per 1K ctx tokens
                max_context = 4000 if complexity == "deep" else 2000
                truncated_context = context[:max_context] if len(context) > max_context else context
                
                ollama_system = f"""You are an expert trading assistant with REAL-TIME market data access.

CRITICAL INSTRUCTIONS:
1. The data below is LIVE and CURRENT from the user's ACTUAL brokerage account
2. Report ONLY the EXACT values shown - do NOT invent, estimate, or hallucinate ANY numbers
3. If you see "TMC: LONG 10,000 shares @ $7.92 avg" - report EXACTLY those values
4. NEVER make up share counts, prices, or P&L values

{truncated_context}

REMEMBER: Use ONLY the exact data above. Any invented numbers will be WRONG."""
                
                ollama_messages = [{"role": "system", "content": ollama_system}]
                ollama_messages.extend(messages[-3:] if len(messages) > 3 else messages)
                
                payload = {
                    "model": ollama_cfg["model"],
                    "messages": ollama_messages,
                    "stream": False,
                    "options": {
                        "num_ctx": 2048,  # Fixed at 2048 for 4GB VRAM stability
                        "temperature": 0.3,  # Lower temp to reduce hallucination
                        "num_predict": 512  # Limit output tokens
                    }
                }
                
                # Longer timeout for deep queries (model needs more time with larger context)
                timeout_seconds = 90.0 if complexity == "deep" else 45.0
                logger.info(f"🤖 Calling Ollama: model={ollama_cfg['model']}, context={len(truncated_context)} chars")
                
                async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=5.0)) as client:
                    response = await client.post(
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "ngrok-skip-browser-warning": "true"
                        }
                    )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get("message", {}).get("content", "")
                    if content and len(content) > 0:
                        # Reset failure counter on success
                        self._ollama_failures = 0
                        self._ollama_last_success = datetime.now(timezone.utc)
                        logger.info(f"✅ Ollama response OK ({len(content)} chars) - FREE")
                        return content
                    else:
                        logger.warning(f"⚠️ Ollama returned empty content")
                        
            except Exception as e:
                self._ollama_failures += 1
                logger.warning(f"⚠️ Ollama request failed ({self._ollama_failures}x): {e}")
                
                # After 3 failures, skip Ollama for 5 minutes
                if self._ollama_failures >= 3:
                    self._ollama_skip_until = datetime.now(timezone.utc) + timedelta(minutes=5)
                    logger.warning(f"⏸️ Ollama disabled for 5 minutes")
        
        # FALLBACK: Use cloud AI (Emergent/GPT-4o) - ONLY when Ollama unavailable
        if LLMProvider.EMERGENT in self.llm_clients:
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage
                import asyncio
                
                logger.info("🔄 Fallback to GPT-4o (Ollama unavailable or failed)")
                
                system_message = self.SYSTEM_PROMPT + "\n\n" + context
                
                initial_msgs = []
                for msg in full_messages[:-1]:
                    if msg["role"] != "system":
                        initial_msgs.append({"role": msg["role"], "content": msg["content"]})
                
                chat = LlmChat(
                    api_key=self.llm_clients[LLMProvider.EMERGENT]["key"],
                    session_id=f"assistant_{id(self)}",
                    system_message=system_message,
                    initial_messages=initial_msgs if initial_msgs else None
                )
                
                chat = chat.with_model("openai", "gpt-4o")
                
                last_msg = full_messages[-1]["content"] if full_messages else "Hello"
                
                response = chat.send_message(UserMessage(last_msg))
                
                if asyncio.iscoroutine(response):
                    response = await response
                
                logger.info(f"✅ Cloud AI response OK ({len(response)} chars)")
                return response
                
            except Exception as e:
                error_msg = str(e).lower()
                logger.error(f"Cloud AI error: {e}")
                
                if "budget" in error_msg or "quota" in error_msg or "insufficient" in error_msg:
                    return ("Cloud AI budget limit reached. Please check your Universal Key balance "
                           "in Profile > Universal Key, or ensure Ollama is running locally.")
        
        # Last resort error
        return ("I apologize, but I'm having trouble connecting to AI services right now. "
               "Please try again in a moment, or check that your services are running.")
    
    async def chat(self, user_message: str, session_id: str = "default", user_id: str = "default") -> Dict:
        """
        Main chat interface. Processes user message and returns AI response.
        Now with web research capabilities!
        """
        # Track request pattern
        await self._track_request_pattern(user_message)
        
        # Get or create conversation
        conv = await self._get_or_create_conversation(session_id, user_id)
        
        # Add user message
        user_msg = AssistantMessage(role="user", content=user_message)
        conv.messages.append(user_msg)
        
        # ===== EARLY DETECTION: Simple conversational messages =====
        # Skip heavy context building for greetings and simple chat
        simple_patterns = [
            r'^(hi+|hello+|hey+|yo|sup|hiya|howdy)(\s+there)?[\s\!\.\?\,]*$',
            r'^good\s*(morning|afternoon|evening|night)[\s\!\.\?\,]*$',
            r'^(how\s*are\s*you|what\'?s\s*up|thanks|thank\s*you|please|bye|goodbye)[\s\!\.\?\,]*$',
            r'^(yes|no|ok|okay|sure|fine|great|cool|nice|wow|awesome|yep|nope|yup)[\s\!\.\?\,]*$',
            r'^(greetings|salutations|whats\s*good|wassup)[\s\!\.\?\,]*$',
        ]
        
        msg_stripped = user_message.strip().lower()
        is_simple_greeting = any(re.match(pattern, msg_stripped, re.IGNORECASE) for pattern in simple_patterns)
        
        if is_simple_greeting:
            logger.info(f"Simple greeting detected, skipping heavy context: {user_message[:30]}")
            # Minimal context for simple greetings
            context = """You are a friendly trading assistant. Respond briefly and warmly to the user's greeting, 
            then offer to help with trading analysis, stock research, or position management."""
            
            # Prepare messages for LLM (last 5 messages for simple context)
            recent_messages = conv.messages[-5:]
            llm_messages = [{"role": m.role, "content": m.content} for m in recent_messages]
            
            try:
                response_text = await self._call_llm(llm_messages, context, complexity="light")
                assistant_msg = AssistantMessage(
                    role="assistant",
                    content=response_text,
                    metadata={"provider": "ollama", "simple_greeting": True}
                )
                conv.messages.append(assistant_msg)
                return {"success": True, "response": response_text, "session_id": session_id}
            except Exception as e:
                logger.error(f"Simple greeting LLM error: {e}")
                # Fallback response
                return {
                    "success": True,
                    "response": "Hello! How can I help you with trading today?",
                    "session_id": session_id
                }
        
        # ===== BOT DEPLOYMENT DETECTION =====
        # Check if user wants to deploy/configure the trading bot
        bot_command = await self._detect_bot_command(user_message)
        if bot_command and self._trading_bot:
            try:
                bot_response = await self._execute_bot_command(bot_command, user_message, conv)
                if bot_response:
                    assistant_msg = AssistantMessage(
                        role="assistant",
                        content=bot_response,
                        metadata={"provider": "bot_command", "command": bot_command["action"]}
                    )
                    conv.messages.append(assistant_msg)
                    return {
                        "success": True, 
                        "response": bot_response, 
                        "session_id": session_id,
                        "bot_action": bot_command["action"]
                    }
            except Exception as e:
                logger.error(f"Bot command execution error: {e}")
                # Continue to regular flow if bot command fails
        
        # ===== REGULAR FLOW: Complex messages =====
        
        # Check for research intent first
        research_context = ""
        research_intent = await self._detect_research_intent(user_message)
        if research_intent:
            logger.info(f"Research intent detected: {research_intent}")
            try:
                research_context = await self._perform_research(research_intent)
                logger.info(f"Research completed: {len(research_context)} chars")
            except Exception as e:
                logger.error(f"Research failed: {e}")
                research_context = f"[Research attempt failed: {str(e)}]"
        
        # Build context with relevant knowledge
        context = await self._build_context(user_message, session_id)
        logger.info(f"📦 Context built: {len(context)} chars")
        
        # ===== ALERT REASONING INJECTION =====
        # If user is asking about a specific alert/trade reasoning, inject the alert data
        alert_reasoning_context = await self._get_alert_reasoning_context(user_message)
        if alert_reasoning_context:
            context = f"{alert_reasoning_context}\n\n{context}"
        
        # Add research results to context if available
        if research_context:
            context = f"{context}\n\n{research_context}"
        
        # Prepare messages for LLM (last 10 messages for context)
        recent_messages = conv.messages[-10:]
        llm_messages = [{"role": m.role, "content": m.content} for m in recent_messages]
        
        try:
            # Smart routing: detect complexity from user message
            msg_lower = user_message.lower()
            deep_keywords = [
                "should i buy", "should i sell", "analyze", "evaluate", "deep dive",
                "strategy", "backtest", "risk", "recommend", "quality score",
                "compare", "portfolio", "rebalance", "hedge", "options",
                "earnings play", "swing trade", "position size", "thesis",
                "research", "news", "what's happening", "whats happening", "latest",
                "market today", "market doing", "how is the market", "hows the market",
                "market overview", "market conditions", "happening in the market",
                "my positions", "positions", "holdings", "average cost", "avg cost",
                "p&l", "profit", "loss", "unrealized", "share count", "shares"
            ]
            complexity = "deep" if any(kw in msg_lower for kw in deep_keywords) else "standard"
            
            # Force deep analysis if research was performed
            if research_context:
                complexity = "deep"
            
            # Call LLM with smart routing
            response_text = await self._call_llm(llm_messages, context, complexity=complexity)
            
            # ===== VALIDATION LAYER WITH AUTO-REGENERATION =====
            # Validate AI response against real-time data (if smart context was used)
            validation_result = None
            regeneration_count = 0
            max_regenerations = 1  # Max 1 retry to avoid infinite loops
            
            if USE_SMART_CONTEXT and hasattr(self, '_last_context_data') and self._last_context_data:
                try:
                    from services.smart_context_engine import get_response_validator
                    validator = get_response_validator()
                    validation_result = validator.validate_response(response_text, self._last_context_data)
                    
                    # Auto-regeneration for high-severity issues
                    while (validation_result and 
                           not validation_result.get('validated') and 
                           regeneration_count < max_regenerations):
                        
                        high_severity_issues = [e for e in validation_result.get('issues', []) 
                                               if e.get('severity') == 'high']
                        
                        if high_severity_issues:
                            logger.warning(f"High-severity validation issues - attempting regeneration ({regeneration_count + 1}/{max_regenerations})")
                            
                            # Get correction prompt
                            correction_prompt = validator.get_correction_prompt()
                            
                            if correction_prompt:
                                # Add correction context and regenerate
                                corrected_context = f"{context}\n\n=== CORRECTION REQUIRED ===\n{correction_prompt}\n\nPlease provide an accurate response using the corrected data above."
                                
                                # Regenerate response
                                response_text = await self._call_llm(llm_messages, corrected_context, complexity=complexity)
                                
                                # Re-validate
                                validation_result = validator.validate_response(response_text, self._last_context_data)
                                regeneration_count += 1
                            else:
                                break
                        else:
                            # Only low/medium severity - don't regenerate
                            break
                    
                    # Log final validation result
                    if validation_result and not validation_result.get('validated'):
                        logger.warning(f"Response validation issues after {regeneration_count} regenerations: {validation_result.get('issues', [])}")
                        
                        # Add disclaimer for remaining issues
                        if any(e.get('severity') in ['high', 'medium'] for e in validation_result.get('issues', [])):
                            response_text += f"\n\n⚠️ *Note: Some information may need verification.*"
                    
                    # Add regeneration info to validation result
                    if validation_result:
                        validation_result['regeneration_count'] = regeneration_count
                        
                except Exception as e:
                    logger.warning(f"Validation error: {e}")
            
            # Add assistant response
            assistant_msg = AssistantMessage(
                role="assistant",
                content=response_text,
                metadata={
                    "provider": "gpt-4o" if complexity == "deep" else "ollama",
                    "had_research": bool(research_context),
                    "validation": validation_result
                }
            )
            conv.messages.append(assistant_msg)
            
            # Save to DB
            await self._save_conversation_to_db(session_id)
            
            # ===== ACCURACY TRACKING =====
            # Record validation result for historical accuracy analysis
            if validation_result:
                try:
                    from services.accuracy_tracker import get_accuracy_tracker
                    tracker = get_accuracy_tracker()
                    
                    # Get intent info if available
                    intent_name = "unknown"
                    symbols = []
                    if hasattr(self, '_last_intent') and self._last_intent:
                        intent_name = self._last_intent.primary_intent.value
                        symbols = self._last_intent.symbols
                    
                    tracker.record_validation(
                        user_message=user_message,
                        intent=intent_name,
                        symbols=symbols,
                        validation_result=validation_result,
                        response_length=len(response_text),
                        provider="gpt-4o" if complexity == "deep" else "ollama",
                        regeneration_count=regeneration_count
                    )
                except Exception as e:
                    logger.debug(f"Accuracy tracking error (non-critical): {e}")
            
            return {
                "success": True,
                "response": response_text,
                "session_id": session_id,
                "message_count": len(conv.messages),
                "provider": "gpt-4o" if complexity == "deep" else "ollama",
                "complexity": complexity,
                "used_research": bool(research_context),
                "validation": validation_result
            }
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id
            }
    
    async def analyze_trade(self, symbol: str, action: str, session_id: str = "default") -> Dict:
        """
        Analyze a potential trade against learned rules and strategies.
        """
        prompt = f"""I'm considering a {action.upper()} trade on {symbol}. 

Please analyze this trade idea:
1. Does it match any of my learned strategies?
2. Am I violating any trading rules?
3. What's the quality score and what does it tell us?
4. What's the risk/reward assessment?
5. What could go wrong?
6. Your recommendation: TAKE THE TRADE, WAIT, or PASS

Be specific with your reasoning."""

        return await self.chat(prompt, session_id)
    
    async def get_premarket_briefing(self, session_id: str = "default") -> Dict:
        """Generate a pre-market briefing using learned knowledge"""
        prompt = """Generate my pre-market briefing for today.

Include:
1. Overall market sentiment (based on futures if available)
2. Key levels to watch on SPY/QQQ
3. Strategies from my knowledge base that might be relevant today
4. Any trading rules I should keep in mind
5. What setups should I be looking for?

Be analytical and specific."""

        return await self.chat(prompt, session_id)
    
    async def review_trading_patterns(self, session_id: str = "default") -> Dict:
        """Analyze user's trading patterns and suggest improvements"""
        # Get trade journal data if available
        journal_context = ""
        if self.db is not None:
            try:
                trades = await asyncio.to_thread(lambda: list(self.db["trades"].find().sort("entry_date", -1).limit(20)))
                if trades:
                    journal_context = f"\nRecent trades from journal: {len(trades)} trades found."
                    wins = len([t for t in trades if t.get("pnl", 0) > 0])
                    losses = len([t for t in trades if t.get("pnl", 0) < 0])
                    journal_context += f"\nWin/Loss: {wins}W / {losses}L"
            except Exception as e:
                logger.warning(f"Error getting trades: {e}")
        
        prompt = f"""Review my trading patterns and behavior.{journal_context}

Analyze:
1. Am I following my trading rules consistently?
2. What patterns do you notice in my questions and trades?
3. Are there strategies I should focus on more?
4. What improvements would you suggest?
5. Any warning signs in my trading behavior?

Be honest and constructive."""

        return await self.chat(prompt, session_id)
    
    # ===================== AI-BOT INTEGRATION =====================
    
    async def evaluate_bot_opportunity(self, trade_data: Dict) -> Dict:
        """
        AI evaluates a trade opportunity from the bot.
        Returns approval/rejection with reasoning.
        """
        prompt = f"""AUTONOMOUS BOT TRADE EVALUATION REQUEST:

The trading bot has identified a potential trade. Evaluate it against our strategy rules:

Symbol: {trade_data.get('symbol')}
Direction: {trade_data.get('direction', 'long').upper()}
Strategy: {trade_data.get('setup_type', 'unknown')}
Timeframe: {trade_data.get('timeframe', 'intraday')}
Entry Price: ${trade_data.get('entry_price', 0):.2f}
Stop Price: ${trade_data.get('stop_price', 0):.2f}
Target Prices: {trade_data.get('target_prices', [])}
Risk Amount: ${trade_data.get('risk_amount', 0):.2f}
Risk/Reward: {trade_data.get('risk_reward_ratio', 0):.1f}:1
Quality Score: {trade_data.get('quality_score', 0)} ({trade_data.get('quality_grade', 'N/A')})

Evaluate:
1. Does this match the strategy criteria?
2. Any rule violations?
3. Is the R:R acceptable?
4. VERDICT: APPROVE, CAUTION, or REJECT

Keep response concise (3-5 sentences max). Start with VERDICT on first line."""

        try:
            context = ""
            if self._trading_bot:
                context = self._trading_bot.get_bot_context_for_ai()
            
            messages = [{"role": "user", "content": prompt}]
            response = await self._call_llm(messages, context, complexity="deep")
            
            # Parse verdict
            verdict = "CAUTION"
            response_lower = response.lower()
            if "approve" in response_lower[:50]:
                verdict = "APPROVE"
            elif "reject" in response_lower[:50]:
                verdict = "REJECT"
            
            return {
                "success": True,
                "verdict": verdict,
                "analysis": response,
                "symbol": trade_data.get('symbol')
            }
        except Exception as e:
            logger.error(f"AI evaluation error: {e}")
            return {"success": False, "verdict": "APPROVE", "analysis": f"AI unavailable: {e}"}
    
    # ===================== COACHING FEATURES =====================
    
    async def check_rule_violations(self, symbol: str, action: str, entry_price: float = None, 
                                    position_size: float = None, stop_loss: float = None) -> Dict:
        """
        Proactively check a trade idea against user's trading rules.
        Returns violations, warnings, and recommendations.
        """
        # Get user's trading rules
        try:
            rules = self.knowledge_service.get_by_type("rule")
        except Exception:
            rules = []
        
        # Build context about the trade
        trade_context = {
            "symbol": symbol.upper(),
            "action": action.upper(),
            "entry_price": entry_price,
            "position_size": position_size,
            "stop_loss": stop_loss
        }
        
        # Get market context for better analysis
        market_context = await self._get_market_context()
        
        # Rule checking prompt
        rules_text = "\n".join([f"- {r.get('title', '')}: {r.get('content', '')}" for r in rules[:15]]) if rules else "No trading rules defined yet."
        
        prompt = f"""TRADE RULE CHECK REQUEST

Trade Details:
- Symbol: {symbol.upper()}
- Action: {action.upper()}
- Entry Price: {entry_price if entry_price else 'Not specified'}
- Position Size: {position_size if position_size else 'Not specified'}  
- Stop Loss: {stop_loss if stop_loss else 'Not specified'}

Market Context:
{json.dumps(market_context, indent=2) if market_context else 'Market data unavailable'}

User's Trading Rules:
{rules_text}

Please analyze this trade and provide:
1. RULE VIOLATIONS: List any rules this trade would violate (CRITICAL)
2. WARNINGS: Concerns that don't break rules but need attention
3. PASSED CHECKS: Rules this trade correctly follows
4. POSITION SIZING: Recommend proper size based on rules and market regime
5. STOP LOSS RECOMMENDATION: If not provided or improper
6. OVERALL VERDICT: PROCEED, CAUTION, or DO NOT TRADE

Be specific and reference actual rules when applicable."""

        response = await self.chat(prompt, f"rule_check_{symbol}_{datetime.now().strftime('%H%M%S')}")
        
        return {
            "trade": trade_context,
            "market_context": market_context,
            "rules_checked": len(rules),
            "analysis": response.get("response", ""),
            "session_id": response.get("session_id"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def _get_market_context(self) -> Dict:
        """Get current market context for coaching decisions"""
        try:
            # Try to get market indicators
            from services.market_indicators import get_market_indicators_service
            indicators_service = get_market_indicators_service()
            
            # Get VOLD ratio
            vold = await indicators_service.get_vold_ratio()
            regime = await indicators_service.get_market_regime()
            
            return {
                "vold": vold,
                "regime": regime.get("regime", {}).get("name", "Unknown") if regime else "Unknown",
                "regime_characteristics": regime.get("regime", {}).get("characteristics", []) if regime else [],
                "favored_setups": regime.get("favored_setups", []) if regime else [],
                "avoid_setups": regime.get("avoid_setups", []) if regime else [],
                "position_sizing_guidance": regime.get("position_sizing", {}).get("guidance", "") if regime else ""
            }
        except Exception as e:
            logger.warning(f"Could not get market context: {e}")
            return {}
    
    async def get_position_sizing_guidance(self, symbol: str, entry_price: float, 
                                           stop_loss: float, account_size: float = None) -> Dict:
        """
        Get AI-powered position sizing recommendations based on:
        - User's trading rules
        - Current market regime
        - Risk per trade limits
        - Stock volatility (ATR)
        """
        market_context = await self._get_market_context()
        
        # Get ATR extension data if available
        atr_data = {}
        try:
            from services.market_indicators import get_market_indicators_service
            indicators_service = get_market_indicators_service()
            atr_data = await indicators_service.analyze_stock_extension(symbol)
        except Exception as e:
            logger.debug(f"Could not get ATR data for {symbol}: {e}")
        
        # Get user's risk rules
        try:
            rules = self.knowledge_service.get_by_type("rule")
            risk_rules = [r for r in rules if any(word in r.get('content', '').lower() 
                         for word in ['risk', 'position', 'size', 'max', 'loss', '%'])]
        except Exception:
            risk_rules = []
        
        risk_rules_text = "\n".join([f"- {r.get('title', '')}: {r.get('content', '')}" for r in risk_rules[:10]]) if risk_rules else "No specific risk rules defined."
        
        prompt = f"""POSITION SIZING REQUEST

Trade Setup:
- Symbol: {symbol.upper()}
- Entry Price: ${entry_price:.2f}
- Stop Loss: ${stop_loss:.2f}
- Risk Per Share: ${abs(entry_price - stop_loss):.2f}
- Account Size: {'$' + f'{account_size:,.0f}' if account_size else 'Not specified'}

Market Regime: {market_context.get('regime', 'Unknown')}
Regime Position Sizing Guidance: {market_context.get('position_sizing_guidance', 'Not available')}

ATR Data:
{json.dumps(atr_data, indent=2) if atr_data else 'ATR data unavailable'}

User's Risk Management Rules:
{risk_rules_text}

Please provide:
1. RECOMMENDED SHARES: Based on risk rules and market regime
2. DOLLAR RISK: Total dollar amount at risk
3. RISK PERCENTAGE: As % of account (if account size known)
4. SCALING STRATEGY: Should this be a full position or scaled entry?
5. ADJUSTMENT FACTORS: Any reasons to reduce size (volatility, regime, extension)
6. FINAL RECOMMENDATION: Exact share count with reasoning"""

        response = await self.chat(prompt, f"sizing_{symbol}_{datetime.now().strftime('%H%M%S')}")
        
        return {
            "symbol": symbol.upper(),
            "entry": entry_price,
            "stop": stop_loss,
            "risk_per_share": abs(entry_price - stop_loss),
            "market_regime": market_context.get("regime", "Unknown"),
            "atr_data": atr_data,
            "analysis": response.get("response", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def get_coaching_alert(self, context_type: str, data: Dict = None) -> Dict:
        """
        Generate proactive coaching alerts based on context.
        
        Context types:
        - market_open: Morning coaching tips
        - market_regime_change: Regime shifted, adjust strategy
        - losing_streak: Multiple losses detected
        - overtrading: Too many trades
        - position_risk: Position too large
        - rule_reminder: Periodic rule reminders
        """
        data = data or {}
        
        coaching_prompts = {
            "market_open": """It's market open time. Based on my learned knowledge, provide a quick 3-point coaching reminder:
1. What's the current market regime and how should I trade it?
2. Which of my strategies are best suited for today?
3. One key rule I should keep in mind.
Keep it concise and actionable.""",
            
            "market_regime_change": f"""ALERT: Market regime appears to have changed.
Previous: {data.get('previous_regime', 'Unknown')}
Current: {data.get('current_regime', 'Unknown')}

What does this mean for my trading today? What adjustments should I make? Which strategies should I focus on or avoid?""",
            
            "losing_streak": f"""COACHING ALERT: I've had {data.get('consecutive_losses', 0)} consecutive losing trades.

Based on my trading rules and patterns, help me:
1. Should I stop trading for the day?
2. What might I be doing wrong?
3. What rule should I remind myself of?
4. Mental reset recommendations.""",
            
            "overtrading": f"""COACHING ALERT: I've made {data.get('trade_count', 0)} trades today.

Am I overtrading? Based on my rules:
1. What's my typical daily trade limit?
2. Am I being patient enough?
3. Quality vs quantity reminder.""",
            
            "position_risk": f"""POSITION RISK CHECK: 
Current position: {data.get('symbol', 'Unknown')} 
Size: {data.get('shares', 0)} shares
Total exposure: ${data.get('exposure', 0):,.2f}

Is this position too large based on my rules? What's the max I should have?""",
            
            "rule_reminder": """Give me a random but important reminder from my trading rules. Something I might forget in the heat of trading. Make it punchy and memorable.""",
            
            "scanner_opportunity": f"""🚨 SCANNER OPPORTUNITY: {data.get('symbol', 'Unknown')}
Setup: {data.get('setup_type', 'Unknown')} {data.get('direction', 'unknown').upper()}
Priority: {data.get('priority', 'medium').upper()}
Win Rate: {data.get('win_rate', 0)*100:.0f}% | R:R: {data.get('risk_reward', 0):.1f}:1
Tape: {'CONFIRMED ✓' if data.get('tape_confirmation') else 'Not confirmed'}

Quick coaching: Is this a valid setup? Any concerns? Action: TAKE, WAIT, or PASS?"""
        }
        
        prompt = coaching_prompts.get(context_type, f"Provide coaching guidance for: {context_type}")
        
        response = await self.chat(prompt, f"coach_{context_type}_{datetime.now().strftime('%H%M%S')}")
        
        return {
            "alert_type": context_type,
            "context_data": data,
            "coaching": response.get("response", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def generate_scanner_coaching(self, alert_data: Dict) -> Dict:
        """
        Generate proactive coaching message for a scanner opportunity.
        Creates both an AI chat message AND returns data for toast notification.
        
        Now enhanced with SMB Capital methodology:
        - Trade style recommendations (M2M/T2H/A+)
        - 5-Variable scoring context
        - Tiered entry suggestions
        - Reasons2Sell framework
        
        alert_data should include:
        - symbol, setup_type, direction, current_price
        - trigger_price, stop_loss, target, risk_reward
        - win_rate, tape_confirmation, headline, reasoning
        - time_window, market_regime, priority
        - smb_score (optional), tape_score (optional)
        """
        symbol = alert_data.get('symbol', 'UNKNOWN')
        setup_type = alert_data.get('setup_type', 'unknown')
        direction = alert_data.get('direction', 'long')
        priority = alert_data.get('priority', 'medium')
        win_rate = alert_data.get('win_rate', 0)
        tape = alert_data.get('tape_confirmation', False)
        r_r = alert_data.get('risk_reward', 0)
        
        # NEW: Get SMB-specific data
        smb_grade = alert_data.get('smb_grade', alert_data.get('trade_grade', 'B'))
        smb_score = alert_data.get('smb_score_total', 25)
        tape_score = alert_data.get('tape_score', 5)
        trade_style = alert_data.get('trade_style', '')
        direction_bias = alert_data.get('direction_bias', 'both')
        target_r = alert_data.get('target_r_multiple', r_r)
        
        # Generate SMB coaching context if available
        smb_coaching_context = ""
        try:
            from services.smb_unified_scoring import get_ai_coaching_prompts
            from services.smb_integration import get_setup_config, TradeStyle
            
            config = get_setup_config(setup_type)
            if config:
                # Get trade style-specific coaching
                style = trade_style or config.default_style.value
                coaching_points = get_ai_coaching_prompts(
                    smb_score=None,  # We don't have full object, just grade
                    trade_style=style,
                    current_situation="entry"
                )
                
                smb_coaching_context = f"""
=== SMB METHODOLOGY CONTEXT ===
Setup Direction Bias: {config.direction.value.upper()} (this is primarily a {config.direction.value} setup)
Trade Style: {style.upper()} (Target: {target_r:.1f}R)
SMB Grade: {smb_grade} | Score: {smb_score}/50
Tape Score: {tape_score}/10 ({'confirming' if tape_score >= 6 else 'not confirming'})
Category: {config.category.value}

SMB Coaching Points:
{chr(10).join('- ' + p for p in coaching_points) if coaching_points else '- Standard entry rules apply'}

Tiered Entry Suggestion:
- Tier 1 (30%): At current trigger level with tape confirmation
- Tier 2 (40%): Add if setup holds and tape improves  
- Tier 3 (30%): Full size only if A+ grade

Reasons2Sell (for {style}):
- {'Target hit, first momentum pause, or tape slows' if style == 'move_2_move' else '9 EMA break, target hit, or thesis invalidation'}
"""
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Could not generate SMB coaching context: {e}")
        
        # Build a concise prompt for quick coaching response
        prompt = f"""🚨 SCANNER OPPORTUNITY DETECTED - QUICK COACHING NEEDED

**{symbol}** - {setup_type.replace('_', ' ').title()} {direction.upper()}
Priority: {priority.upper()} | Win Rate: {win_rate*100:.0f}% | R:R {r_r:.1f}:1
Tape Confirmation: {'YES ✓' if tape else 'NO'}
SMB Grade: {smb_grade} | Trade Style: {trade_style.upper() if trade_style else 'AUTO'}

Setup Details:
- Current: ${alert_data.get('current_price', 0):.2f}
- Entry: ${alert_data.get('trigger_price', 0):.2f}
- Stop: ${alert_data.get('stop_loss', 0):.2f}  
- Target: ${alert_data.get('target', 0):.2f}
- Time Window: {alert_data.get('time_window', 'unknown')}
- Market Regime: {alert_data.get('market_regime', 'unknown')}

Reasoning: {'; '.join(alert_data.get('reasoning', [])[:3])}
{smb_coaching_context}
Based on my playbook knowledge and SMB methodology, provide a BRIEF 2-3 sentence coaching response:
1. Is this a valid setup for the current conditions? (Check direction bias matches trade direction)
2. Any quick warnings or confirmations needed? (Tape score, grade, tiered entry)
3. Suggested action: TAKE, WAIT, or PASS?
4. If TAKE: Recommend M2M (quick scalp) or T2H (hold for full target)?

Keep it punchy and actionable - trader needs to act fast!"""

        try:
            # Use the existing chat method with a special session for scanner coaching
            # Note: complexity is auto-detected based on keywords in the message
            session_id = f"scanner_coach_{datetime.now().strftime('%Y%m%d')}"
            response = await self.chat(prompt, session_id)
            
            coaching_text = response.get("response", "")
            
            # Extract a brief summary for toast notification (first sentence or first 80 chars)
            summary = coaching_text.split('.')[0][:100] if coaching_text else f"{setup_type} on {symbol}"
            
            # Determine verdict based on response content
            coaching_lower = coaching_text.lower()
            if any(word in coaching_lower for word in ['take', 'valid', 'confirmed', 'good setup', 'looks good']):
                verdict = "TAKE"
            elif any(word in coaching_lower for word in ['pass', 'skip', 'avoid', 'warning', 'caution']):
                verdict = "PASS"
            else:
                verdict = "WAIT"
            
            # Determine recommended style from response
            recommended_style = ""
            if "t2h" in coaching_lower or "trade2hold" in coaching_lower or "hold for" in coaching_lower:
                recommended_style = "trade_2_hold"
            elif "m2m" in coaching_lower or "move2move" in coaching_lower or "scalp" in coaching_lower:
                recommended_style = "move_2_move"
            elif "a+" in coaching_lower or "a plus" in coaching_lower or "full conviction" in coaching_lower:
                recommended_style = "a_plus"
            
            # Store the coaching message for the chat panel to pick up
            coaching_message = {
                "type": "scanner_coaching",
                "symbol": symbol,
                "setup_type": setup_type,
                "direction": direction,
                "priority": priority,
                "coaching": coaching_text,
                "summary": summary,
                "verdict": verdict,
                "recommended_style": recommended_style,  # NEW
                "smb_grade": smb_grade,  # NEW
                "tape_score": tape_score,  # NEW
                "alert_data": alert_data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Store in a queue for the frontend to poll
            if not hasattr(self, '_coaching_notifications'):
                self._coaching_notifications = []
            self._coaching_notifications.append(coaching_message)
            # Keep only last 20 notifications
            self._coaching_notifications = self._coaching_notifications[-20:]
            
            logger.info(f"🧠 Scanner coaching for {symbol}: {verdict} ({recommended_style or 'auto'}) - {summary[:50]}...")
            
            return {
                "success": True,
                "symbol": symbol,
                "setup_type": setup_type,
                "coaching": coaching_text,
                "summary": summary,
                "verdict": verdict,
                "recommended_style": recommended_style,
                "smb_grade": smb_grade,
                "timestamp": coaching_message["timestamp"]
            }
            
        except Exception as e:
            logger.warning(f"Scanner coaching generation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "symbol": symbol,
                "setup_type": setup_type
            }
    
    def get_coaching_notifications(self, since: str = None) -> List[Dict]:
        """
        Get recent coaching notifications for the frontend.
        Optionally filter by timestamp.
        """
        if not hasattr(self, '_coaching_notifications'):
            self._coaching_notifications = []
        
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
                return [n for n in self._coaching_notifications 
                       if datetime.fromisoformat(n['timestamp'].replace('Z', '+00:00')) > since_dt]
            except (ValueError, TypeError):
                pass
        
        return self._coaching_notifications[-10:]  # Return last 10 by default
    
    async def get_trade_review(self, trade_data: Dict) -> Dict:
        """
        AI review of a completed trade for learning.
        
        trade_data should include:
        - symbol, action (buy/sell), entry_price, exit_price
        - entry_time, exit_time
        - pnl, shares
        - notes (optional)
        """
        prompt = f"""TRADE REVIEW REQUEST

Trade Details:
- Symbol: {trade_data.get('symbol', 'Unknown')}
- Action: {trade_data.get('action', 'Unknown')}
- Entry: ${trade_data.get('entry_price', 0):.2f} at {trade_data.get('entry_time', 'Unknown')}
- Exit: ${trade_data.get('exit_price', 0):.2f} at {trade_data.get('exit_time', 'Unknown')}
- Shares: {trade_data.get('shares', 0)}
- P&L: ${trade_data.get('pnl', 0):.2f}
- User Notes: {trade_data.get('notes', 'None provided')}

Please review this trade:
1. STRATEGY MATCH: Which of my learned strategies did this trade follow (or should have followed)?
2. RULE COMPLIANCE: Did I follow my trading rules?
3. EXECUTION QUALITY: How was my entry and exit timing?
4. WHAT WENT WELL: Positive aspects of this trade
5. IMPROVEMENT AREAS: What could I have done better?
6. LESSON LEARNED: One key takeaway from this trade
7. PATTERN ALERT: Does this trade show any concerning patterns in my trading?

Be specific and reference my actual rules/strategies when applicable."""

        response = await self.chat(prompt, f"review_{trade_data.get('symbol', 'trade')}_{datetime.now().strftime('%H%M%S')}")
        
        return {
            "trade": trade_data,
            "review": response.get("response", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def get_daily_coaching_summary(self, session_id: str = "default") -> Dict:
        """
        Generate end-of-day coaching summary with:
        - Today's trades review
        - Rule compliance score
        - Pattern observations
        - Tomorrow's focus areas
        """
        # Get today's trades if available
        trades_summary = ""
        if self.db is not None:
            try:
                today = datetime.now(timezone.utc).date()
                trades = await asyncio.to_thread(lambda: list(self.db["trades"].find({
                    "entry_date": {"$gte": today.isoformat()}
                })))
                
                if trades:
                    wins = len([t for t in trades if t.get("pnl", 0) > 0])
                    losses = len([t for t in trades if t.get("pnl", 0) < 0])
                    total_pnl = sum(t.get("pnl", 0) for t in trades)
                    trades_summary = f"""
Today's Trading Summary:
- Total Trades: {len(trades)}
- Wins: {wins}, Losses: {losses}
- Win Rate: {(wins/len(trades)*100):.1f}%
- Total P&L: ${total_pnl:,.2f}
- Symbols traded: {', '.join(set(t.get('symbol', '') for t in trades))}
"""
            except Exception as e:
                logger.warning(f"Error getting trades: {e}")
        
        prompt = f"""END OF DAY COACHING SUMMARY
{trades_summary if trades_summary else 'No trade data available for today.'}

Please provide my end-of-day coaching summary:

1. OVERALL ASSESSMENT: How did I do today? (Even without specific trades, assess based on our conversations)

2. RULE COMPLIANCE: Based on our discussions, how well did I stick to my trading rules?

3. MENTAL STATE: Any signs of overtrading, revenge trading, or emotional decisions?

4. PATTERN OBSERVATIONS: What patterns have you noticed in my trading behavior?

5. TOMORROW'S FOCUS: 
   - What's the current market regime?
   - Which strategies should I focus on?
   - Which rules do I need to remember?
   - What mistakes should I avoid?

6. ONE KEY COACHING MESSAGE: The most important thing I should remember.

Be direct and constructive. I want honest feedback to improve."""

        response = await self.chat(prompt, f"daily_summary_{datetime.now().strftime('%Y%m%d')}")
        
        return {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "trades_summary": trades_summary,
            "coaching": response.get("response", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def analyze_setup(self, symbol: str, setup_type: str = None, 
                           chart_notes: str = None) -> Dict:
        """
        Analyze a specific trade setup with coaching guidance.
        
        setup_type examples: "gap_up", "breakout", "pullback", "reversal", etc.
        chart_notes: User's observations about the chart
        """
        # Get stock data
        stock_context = ""
        try:
            quality = await self.quality_service.get_quality_metrics(symbol)
            q_score = self.quality_service.calculate_quality_score(quality)
            stock_context = f"""
Stock Quality Data:
- Quality Grade: {q_score.grade} ({q_score.composite_score}/400)
- Signal: {q_score.quality_signal}
"""
        except Exception as e:
            logger.debug(f"Could not get quality data: {e}")
        
        # Get relevant strategies for this setup type
        relevant_strategies = []
        try:
            if setup_type:
                relevant_strategies = self.knowledge_service.search(setup_type, limit=5)
        except Exception:
            pass
        
        strategies_text = ""
        if relevant_strategies:
            strategies_text = "\nRelevant Strategies from Knowledge Base:\n"
            strategies_text += "\n".join([f"- {s.get('title', '')}: {s.get('content', '')[:200]}" for s in relevant_strategies])
        
        market_context = await self._get_market_context()
        
        prompt = f"""SETUP ANALYSIS REQUEST

Symbol: {symbol.upper()}
Setup Type: {setup_type or 'Not specified'}
User's Chart Notes: {chart_notes or 'None provided'}

{stock_context}

Market Context:
- Regime: {market_context.get('regime', 'Unknown')}
- Favored Setups: {', '.join(market_context.get('favored_setups', [])[:3]) or 'Unknown'}
- Setups to Avoid: {', '.join(market_context.get('avoid_setups', [])[:3]) or 'Unknown'}
{strategies_text}

Please analyze this setup:

1. SETUP QUALITY: Is this a high-quality setup? Rate 1-10.

2. STRATEGY MATCH: Does this match any of my learned strategies? Which one?

3. MARKET FIT: Does this setup fit the current market regime?

4. ENTRY CRITERIA: What should I look for to confirm entry?

5. RISK MANAGEMENT:
   - Where should stop loss be?
   - What's a reasonable target?
   - Position size guidance

6. WARNING FLAGS: Any red flags or concerns?

7. VERDICT: TRADE, WAIT FOR CONFIRMATION, or PASS

Be specific with price levels when possible."""

        response = await self.chat(prompt, f"setup_{symbol}_{datetime.now().strftime('%H%M%S')}")
        
        return {
            "symbol": symbol.upper(),
            "setup_type": setup_type,
            "chart_notes": chart_notes,
            "market_regime": market_context.get("regime", "Unknown"),
            "quality_grade": stock_context,
            "analysis": response.get("response", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # ===================== END COACHING FEATURES =====================
    
    async def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Get conversation history for a session"""
        conv = self.conversations.get(session_id)
        if not conv:
            # Try loading from DB
            await self._load_conversation_from_db(session_id)
            conv = self.conversations.get(session_id)
        
        if conv:
            return [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in conv.messages]
        return []
    
    async def clear_conversation(self, session_id: str):
        """Clear conversation history"""
        if session_id in self.conversations:
            del self.conversations[session_id]
        
        if self.db is not None:
            try:
                await asyncio.to_thread(
                    self.db["assistant_conversations"].delete_one,
                    {"session_id": session_id}
                )
            except Exception as e:
                logger.warning(f"Error deleting conversation: {e}")
    
    async def get_all_sessions(self, user_id: str = "default") -> List[Dict]:
        """Get all conversation sessions for a user"""
        sessions = []
        
        if self.db is not None:
            try:
                def _sync_get_sessions():
                    docs = self.db["assistant_conversations"].find(
                        {"user_id": user_id}
                    ).sort("last_activity", -1).limit(20)
                    result = []
                    for doc in docs:
                        result.append({
                            "session_id": doc.get("session_id"),
                            "created_at": doc.get("created_at"),
                            "last_activity": doc.get("last_activity"),
                            "message_count": len(doc.get("messages", []))
                        })
                    return result
                
                sessions = await asyncio.to_thread(_sync_get_sessions)
            except Exception as e:
                logger.warning(f"Error getting sessions: {e}")
        
        return sessions

    async def _detect_bot_command(self, message: str) -> Optional[Dict]:
        """
        Detect if the user wants to execute a trading bot command.
        Returns command info or None if no bot command detected.
        """
        msg_lower = message.lower()
        
        # Deploy/Start bot patterns - more flexible matching
        deploy_patterns = [
            "deploy the trading bot", "deploy trading bot", "deploy the bot", "deploy bot",
            "start the trading bot", "start trading bot", "start the bot", "start bot",
            "enable the trading bot", "enable trading bot", "enable the bot", "enable bot",
            "activate the trading bot", "activate trading bot", "activate the bot", "activate bot",
            "turn on the bot", "turn on bot", "turn the bot on",
            "run the trading bot", "run the bot", "run bot",
            "execute trades on my behalf", "execute trades for me", "trade on my behalf",
            "trades on my behalf", "monitor and trade", "monitor and deploy",
            "auto trade", "automated trading", "automate trading"
        ]
        
        # Stop bot patterns
        stop_patterns = [
            "stop the bot", "stop bot", "disable bot", "disable the bot",
            "turn off bot", "deactivate bot", "pause bot", "halt bot"
        ]
        
        # Configure watchlist patterns
        watchlist_patterns = [
            "focus on", "watch these", "monitor these", "trade these",
            "set watchlist", "add to watchlist", "bot watchlist"
        ]
        
        # Get bot status patterns
        status_patterns = [
            "bot status", "is the bot", "bot running", "trading bot status"
        ]
        
        # Check for deploy command
        if any(p in msg_lower for p in deploy_patterns):
            # Extract tickers from message or recent conversation
            tickers = self._extract_tickers_from_text(message)
            strategies = self._extract_strategies_from_text(message)
            return {
                "action": "deploy",
                "tickers": tickers,
                "strategies": strategies
            }
        
        # Check for stop command
        if any(p in msg_lower for p in stop_patterns):
            return {"action": "stop"}
        
        # Check for status command
        if any(p in msg_lower for p in status_patterns):
            return {"action": "status"}
        
        # Check for watchlist configuration
        if any(p in msg_lower for p in watchlist_patterns):
            tickers = self._extract_tickers_from_text(message)
            if tickers:
                return {"action": "set_watchlist", "tickers": tickers}
        
        return None
    
    def _extract_tickers_from_text(self, text: str) -> List[str]:
        """Extract stock tickers from text."""
        import re
        # Match common ticker patterns
        # Uppercase 1-5 letter words that look like tickers
        potential_tickers = re.findall(r'\b([A-Z]{1,5})\b', text.upper())
        
        # Known tickers to validate against
        known_tickers = {
            # Oil/Energy
            "XOM", "CVX", "COP", "BP", "SLB", "OXY", "EOG", "PXD", "DVN", "HAL",
            "VLO", "MPC", "PSX", "XLE", "USO", "OIH", "BKR",
            # Fertilizer/Agriculture
            "CF", "NTR", "MOS", "FMC", "ADM", "DE", "AGCO",
            # Tech
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC",
            "AVGO", "QCOM", "ADBE", "CRM", "ORCL", "CSCO", "TXN", "MU", "AMAT",
            # Finance
            "JPM", "BAC", "GS", "MS", "WFC", "C", "V", "MA", "BLK", "SCHW",
            # ETFs
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB",
            # Healthcare
            "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "AMGN", "GILD", "MRNA",
            # Consumer
            "HD", "LOW", "TGT", "WMT", "COST", "NKE", "SBUX", "MCD", "DIS",
            # Others
            "NFLX", "COIN", "SQ", "SHOP", "PLTR", "SNOW", "DDOG", "NET", "CRWD",
            "BA", "CAT", "HON", "UPS", "FDX", "GE", "RTX", "LMT"
        }
        
        # Common words to exclude that might look like tickers
        exclude_words = {
            "THE", "AND", "FOR", "WITH", "ON", "MY", "TO", "IN", "OF", "AT", "OR", 
            "AS", "IS", "IT", "OK", "AM", "PM", "US", "A", "I", "BE", "DO", "SO",
            "IF", "AN", "BY", "UP", "NO", "GO", "HE", "WE", "ME", "BOT", "TRADE",
            "BUY", "SELL", "LONG", "SHORT", "PUT", "CALL", "STOP", "ALL", "SET",
            "RUN", "NOW", "DAY", "USE", "NEW", "GET", "CAN", "MAY", "SAY", "SEE",
            "OIL", "GAS", "ETF", "IPO", "ATH", "ATR", "EMA", "RSI", "HOD", "LOD",
            "VWAP", "NYSE", "NASDAQ"
        }
        
        # Also check for tickers mentioned in common patterns like "XOM (Exxon)"
        pattern_matches = re.findall(r'\b([A-Z]{1,5})\s*\([^)]+\)', text.upper())
        potential_tickers.extend(pattern_matches)
        
        # Filter to known tickers only (strict mode)
        valid_tickers = []
        for t in potential_tickers:
            if t in known_tickers:
                valid_tickers.append(t)
            elif t not in exclude_words and len(t) >= 2 and len(t) <= 4:
                # For unknown tickers, only include if they look valid and aren't common words
                # Must be 2-4 chars (most real tickers)
                if t.isalpha():
                    valid_tickers.append(t)
        
        return list(dict.fromkeys(valid_tickers))  # Remove duplicates, preserve order
    
    def _extract_strategies_from_text(self, text: str) -> List[str]:
        """Extract strategy names from text."""
        msg_lower = text.lower()
        
        strategy_map = {
            "hitchhiker": "hitchhiker",
            "spencer": "spencer_scalp", 
            "spencer scalp": "spencer_scalp",
            "rubber band": "rubber_band",
            "rubberband": "rubber_band",
            "gap give": "gap_give_go",
            "backside": "backside",
            "back$ide": "backside",
            "off sides": "off_sides",
            "offsides": "off_sides",
            "second chance": "second_chance",
            "vwap": "vwap_bounce",
            "breakout": "breakout",
            "squeeze": "squeeze",
            "mean reversion": "mean_reversion",
            "gap fade": "gap_fade",
            "orb": "orb",
            "opening range": "orb",
            "first move": "first_move_up",
            "growth": "breakout",  # Map generic "growth" to breakout
            "momentum": "breakout"
        }
        
        found_strategies = []
        for pattern, strategy in strategy_map.items():
            if pattern in msg_lower:
                if strategy not in found_strategies:
                    found_strategies.append(strategy)
        
        return found_strategies
    
    async def _execute_bot_command(self, command: Dict, original_message: str, conv) -> Optional[str]:
        """Execute a trading bot command and return response."""
        action = command.get("action")
        
        if action == "deploy":
            return await self._deploy_bot(command, original_message, conv)
        elif action == "stop":
            return await self._stop_bot()
        elif action == "status":
            return self._get_bot_status()
        elif action == "set_watchlist":
            return self._set_bot_watchlist(command.get("tickers", []))
        
        return None
    
    async def _deploy_bot(self, command: Dict, original_message: str, conv) -> str:
        """Deploy the trading bot with specified configuration."""
        tickers = command.get("tickers", [])
        strategies = command.get("strategies", [])
        
        # If no tickers in current message, try to extract from conversation history
        if not tickers:
            for msg in reversed(conv.messages[-10:]):
                if msg.role == "assistant":
                    tickers = self._extract_tickers_from_text(msg.content)
                    if tickers:
                        break
        
        if not tickers:
            return ("I couldn't identify specific tickers to monitor. Please specify the symbols you want me to trade, "
                   "for example: 'Deploy the bot to trade XOM, CVX, CF, and NTR'")
        
        # If no strategies specified, use defaults for the sector
        if not strategies:
            strategies = ["hitchhiker", "breakout", "gap_give_go", "vwap_bounce"]
        
        try:
            # Configure the bot
            self._trading_bot.set_watchlist(tickers)
            self._trading_bot.set_enabled_setups(strategies)
            
            # Start the bot
            await self._trading_bot.start()
            
            # Get current mode
            mode = self._trading_bot.get_mode()
            mode_desc = "PAPER TRADING (simulated)" if mode.value == "paper" else "LIVE TRADING"
            
            response = f"""**Trading Bot Deployed Successfully**

**Mode:** {mode_desc}
**Watchlist:** {', '.join(tickers)}
**Strategies Enabled:** {', '.join(strategies)}

The bot is now actively monitoring these symbols for setups matching your strategies. Here's what it will do:

1. **Monitor** - Continuously scan {', '.join(tickers)} for entry signals
2. **Evaluate** - Score each opportunity using the enabled strategies
3. **Alert** - Notify you when high-quality setups are detected
4. **Execute** - Place trades automatically when conditions are met (in {mode_desc} mode)

**Risk Management:**
- Position sizing based on ATR volatility
- Maximum risk per trade: ${self._trading_bot.risk_params.max_risk_per_trade:,.0f}
- Stop losses set according to strategy rules

I'll keep you updated on any trades executed. Say "stop the bot" at any time to halt automated trading."""

            return response
            
        except Exception as e:
            logger.error(f"Failed to deploy bot: {e}")
            return f"I encountered an error deploying the bot: {str(e)}. Please try again or check the system status."
    
    async def _stop_bot(self) -> str:
        """Stop the trading bot."""
        try:
            await self._trading_bot.stop()
            
            # Get summary of activity
            summary = self._trading_bot.get_all_trades_summary()
            
            response = f"""**Trading Bot Stopped**

The automated trading bot has been disabled. Here's today's summary:
- **Total Trades:** {summary.get('total_trades', 0)}
- **Winning Trades:** {summary.get('winning_trades', 0)}
- **P&L:** ${summary.get('total_pnl', 0):.2f}

The bot will no longer execute trades automatically. You can re-enable it anytime by asking me to deploy it again."""

            return response
            
        except Exception as e:
            logger.error(f"Failed to stop bot: {e}")
            return f"Error stopping the bot: {str(e)}"
    
    def _get_bot_status(self) -> str:
        """Get current bot status."""
        try:
            context = self._trading_bot.get_bot_context_for_ai()
            mode = self._trading_bot.get_mode()
            summary = self._trading_bot.get_all_trades_summary()
            
            status = "RUNNING" if getattr(self._trading_bot, '_running', False) else "STOPPED"
            
            response = f"""**Trading Bot Status**

**Status:** {status}
**Mode:** {mode.value.upper()}
**Watchlist:** {', '.join(getattr(self._trading_bot, '_watchlist', [])) or 'Not set'}
**Enabled Strategies:** {', '.join(getattr(self._trading_bot, '_enabled_setups', [])) or 'Default'}

**Today's Activity:**
- Trades Executed: {summary.get('total_trades', 0)}
- Win Rate: {summary.get('win_rate', 0):.0%}
- P&L: ${summary.get('total_pnl', 0):.2f}

{context}"""

            return response
            
        except Exception as e:
            logger.error(f"Failed to get bot status: {e}")
            return f"Error getting bot status: {str(e)}"
    
    def _set_bot_watchlist(self, tickers: List[str]) -> str:
        """Set the bot's watchlist."""
        if not tickers:
            return "Please specify tickers to add to the watchlist."
        
        try:
            self._trading_bot.set_watchlist(tickers)
            return f"**Watchlist Updated**\n\nThe bot is now monitoring: {', '.join(tickers)}"
        except Exception as e:
            logger.error(f"Failed to set watchlist: {e}")
            return f"Error updating watchlist: {str(e)}"



# Singleton instance
_assistant_service: Optional[AIAssistantService] = None


def get_assistant_service(db=None) -> AIAssistantService:
    """Get the singleton assistant service"""
    global _assistant_service
    if _assistant_service is None:
        _assistant_service = AIAssistantService(db)
    return _assistant_service


def init_assistant_service(db=None) -> AIAssistantService:
    """Initialize the assistant service"""
    global _assistant_service
    _assistant_service = AIAssistantService(db)
    return _assistant_service
