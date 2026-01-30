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
"""
import os
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
import json
import re

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
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
3. If IB not connected, explain need for live data
4. Provide specific entry, stop, and target levels when possible

Format responses with clear sections. Cite specific rules from the playbook."""

    def __init__(self, db=None):
        self.db = db
        self.provider = LLMProvider.EMERGENT
        self.conversations: Dict[str, ConversationContext] = {}
        
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
        
    def _init_llm_clients(self):
        """Initialize available LLM clients"""
        self.llm_clients = {}
        
        # Emergent (via emergentintegrations)
        try:
            emergent_key = os.environ.get("EMERGENT_LLM_KEY")
            if emergent_key:
                from emergentintegrations.llm.chat import LlmChat
                self.llm_clients[LLMProvider.EMERGENT] = {
                    "available": True,
                    "client": LlmChat,
                    "key": emergent_key
                }
                logger.info("Emergent LLM client initialized")
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
                pattern_id = pattern_name.lower().replace(' ', '_').replace('&', 'and')
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
    
    def _get_or_create_conversation(self, session_id: str, user_id: str = "default") -> ConversationContext:
        """Get existing conversation or create new one"""
        if session_id not in self.conversations:
            self.conversations[session_id] = ConversationContext(
                session_id=session_id,
                user_id=user_id
            )
            # Load from DB if available
            if self.db is not None:
                self._load_conversation_from_db(session_id)
        
        return self.conversations[session_id]
    
    def _load_conversation_from_db(self, session_id: str):
        """Load conversation history from MongoDB"""
        if self.db is None:
            return
        
        try:
            collection = self.db["assistant_conversations"]
            doc = collection.find_one({"session_id": session_id})
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
    
    def _save_conversation_to_db(self, session_id: str):
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
            
            collection.update_one(
                {"session_id": session_id},
                {"$set": {
                    "session_id": session_id,
                    "user_id": conv.user_id,
                    "messages": [{"role": m.role, "content": m.content, "timestamp": m.timestamp, "metadata": m.metadata} for m in messages_to_save],
                    "created_at": conv.created_at,
                    "last_activity": datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
        except Exception as e:
            logger.warning(f"Error saving conversation: {e}")
    
    def _track_request_pattern(self, user_message: str):
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
                self.db["assistant_patterns"].update_one(
                    {"type": "request_patterns"},
                    {"$set": {"patterns": self.request_patterns, "updated_at": datetime.now(timezone.utc).isoformat()}},
                    upsert=True
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
    
    async def _build_context(self, user_message: str, session_id: str) -> str:
        """Build context string with relevant knowledge and data"""
        context_parts = []
        
        # Check if user is asking about news/market
        news_keywords = ['news', 'market', 'today', 'happening', 'morning', 'premarket', 'headlines', 'sentiment']
        wants_news = any(keyword in user_message.lower() for keyword in news_keywords)
        
        # 1. Get market news if relevant
        if wants_news:
            try:
                news_summary = await self.news_service.get_market_summary()
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
            except Exception as e:
                logger.warning(f"Error fetching news: {e}")
                context_parts.append("MARKET NEWS: Error fetching news data")
        
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
        common_words = {'I', 'A', 'THE', 'AND', 'OR', 'FOR', 'TO', 'IS', 'IT', 'IN', 'ON', 'AT', 'BY', 'BE', 'AS', 'AN', 'ARE', 'WAS', 'IF', 'MY', 'ME', 'DO', 'SO', 'UP', 'AM', 'CAN', 'HOW', 'WHAT', 'BUY', 'SELL', 'LONG', 'SHORT', 'NEWS', 'TODAY', 'MARKET'}
        symbols = [s for s in symbols if s not in common_words and len(s) >= 2]
        
        if symbols:
            context_parts.append("\nSTOCK DATA FOR MENTIONED SYMBOLS:")
            for symbol in symbols[:3]:
                try:
                    # Get quality score
                    quality = await self.quality_service.get_quality_metrics(symbol)
                    q_score = self.quality_service.calculate_quality_score(quality)
                    context_parts.append(f"\n{symbol}:")
                    context_parts.append(f"  Quality Grade: {q_score.grade} ({q_score.composite_score}/400)")
                    context_parts.append(f"  Signal: {q_score.quality_signal}")
                    if quality.roe:
                        context_parts.append(f"  ROE: {quality.roe:.1%}, D/A: {quality.da:.1%}" if quality.da else f"  ROE: {quality.roe:.1%}")
                    
                    # Get ticker-specific news if mentioned
                    if wants_news:
                        try:
                            ticker_news = await self.news_service.get_ticker_news(symbol, max_items=3)
                            if ticker_news and not ticker_news[0].get("is_placeholder"):
                                context_parts.append("  Recent News:")
                                for news_item in ticker_news[:3]:
                                    context_parts.append(f"    - {news_item.get('headline', '')[:100]}")
                        except Exception:
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
        
        # 6. Knowledge base stats
        try:
            stats = self.knowledge_service.get_stats()
            context_parts.append(f"\nKNOWLEDGE BASE: {stats.get('total_entries', 0)} entries ({stats.get('by_type', {}).get('strategy', 0)} strategies, {stats.get('by_type', {}).get('rule', 0)} rules)")
        except Exception:
            pass
        
        return "\n".join(context_parts)
    
    async def _call_llm(self, messages: List[Dict], context: str = "") -> str:
        """Call the LLM with the given messages"""
        
        # Build the full message list with system prompt
        full_messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT + "\n\n" + context}
        ]
        full_messages.extend(messages)
        
        # Try Emergent first
        if self.provider == LLMProvider.EMERGENT and LLMProvider.EMERGENT in self.llm_clients:
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage
                import asyncio
                
                # Build system message from context
                system_message = self.SYSTEM_PROMPT + "\n\n" + context
                
                # Build initial messages from conversation history (excluding the last user message)
                initial_msgs = []
                for msg in full_messages[:-1]:  # Exclude last message
                    if msg["role"] != "system":
                        initial_msgs.append({"role": msg["role"], "content": msg["content"]})
                
                # Create chat instance
                chat = LlmChat(
                    api_key=self.llm_clients[LLMProvider.EMERGENT]["key"],
                    session_id=f"assistant_{id(self)}",
                    system_message=system_message,
                    initial_messages=initial_msgs if initial_msgs else None
                )
                
                # Set model
                chat = chat.with_model("openai", "gpt-4o")
                
                # Get the last user message
                last_msg = full_messages[-1]["content"] if full_messages else "Hello"
                
                # Send message and get response (it's a coroutine)
                response = chat.send_message(UserMessage(last_msg))
                
                # Await if it's a coroutine
                if asyncio.iscoroutine(response):
                    response = await response
                
                return response
                
            except Exception as e:
                logger.error(f"Emergent LLM error: {e}")
                raise
        
        # Fallback to OpenAI if available
        elif LLMProvider.OPENAI in self.llm_clients:
            try:
                import httpx
                
                response = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_clients[LLMProvider.OPENAI]['key']}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o",
                        "messages": full_messages,
                        "max_tokens": 2000,
                        "temperature": 0.7
                    },
                    timeout=60
                )
                
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"]
                else:
                    raise Exception(f"OpenAI API error: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"OpenAI error: {e}")
                raise
        
        else:
            raise Exception("No LLM provider available")
    
    async def chat(self, user_message: str, session_id: str = "default", user_id: str = "default") -> Dict:
        """
        Main chat interface. Processes user message and returns AI response.
        """
        # Track request pattern
        self._track_request_pattern(user_message)
        
        # Get or create conversation
        conv = self._get_or_create_conversation(session_id, user_id)
        
        # Add user message
        user_msg = AssistantMessage(role="user", content=user_message)
        conv.messages.append(user_msg)
        
        # Build context with relevant knowledge
        context = await self._build_context(user_message, session_id)
        
        # Prepare messages for LLM (last 10 messages for context)
        recent_messages = conv.messages[-10:]
        llm_messages = [{"role": m.role, "content": m.content} for m in recent_messages]
        
        try:
            # Call LLM
            response_text = await self._call_llm(llm_messages, context)
            
            # Add assistant response
            assistant_msg = AssistantMessage(
                role="assistant",
                content=response_text,
                metadata={"provider": self.provider.value}
            )
            conv.messages.append(assistant_msg)
            
            # Save to DB
            self._save_conversation_to_db(session_id)
            
            return {
                "success": True,
                "response": response_text,
                "session_id": session_id,
                "message_count": len(conv.messages),
                "provider": self.provider.value
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
                trades = list(self.db["trades"].find().sort("entry_date", -1).limit(20))
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
            
            "rule_reminder": """Give me a random but important reminder from my trading rules. Something I might forget in the heat of trading. Make it punchy and memorable."""
        }
        
        prompt = coaching_prompts.get(context_type, f"Provide coaching guidance for: {context_type}")
        
        response = await self.chat(prompt, f"coach_{context_type}_{datetime.now().strftime('%H%M%S')}")
        
        return {
            "alert_type": context_type,
            "context_data": data,
            "coaching": response.get("response", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
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
                trades = list(self.db["trades"].find({
                    "entry_date": {"$gte": today.isoformat()}
                }))
                
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
    
    def get_conversation_history(self, session_id: str) -> List[Dict]:
        """Get conversation history for a session"""
        conv = self.conversations.get(session_id)
        if not conv:
            # Try loading from DB
            self._load_conversation_from_db(session_id)
            conv = self.conversations.get(session_id)
        
        if conv:
            return [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in conv.messages]
        return []
    
    def clear_conversation(self, session_id: str):
        """Clear conversation history"""
        if session_id in self.conversations:
            del self.conversations[session_id]
        
        if self.db is not None:
            try:
                self.db["assistant_conversations"].delete_one({"session_id": session_id})
            except Exception as e:
                logger.warning(f"Error deleting conversation: {e}")
    
    def get_all_sessions(self, user_id: str = "default") -> List[Dict]:
        """Get all conversation sessions for a user"""
        sessions = []
        
        if self.db is not None:
            try:
                docs = self.db["assistant_conversations"].find(
                    {"user_id": user_id}
                ).sort("last_activity", -1).limit(20)
                
                for doc in docs:
                    sessions.append({
                        "session_id": doc.get("session_id"),
                        "created_at": doc.get("created_at"),
                        "last_activity": doc.get("last_activity"),
                        "message_count": len(doc.get("messages", []))
                    })
            except Exception as e:
                logger.warning(f"Error getting sessions: {e}")
        
        return sessions


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
