"""
Smart Context Engine v2
Intelligent intent detection and selective context gathering for AI assistant.
Reduces context size by 50-90% while improving relevance.

Features:
- Intent detection with 10+ categories
- Dynamic context source selection
- Structured output formatting
- Response validation hooks
- Automatic symbol tracking for personalized scanning
- Query preprocessing to reduce hallucinations
"""
import re
import logging
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Import user viewed tracker for symbol tracking
try:
    from services.user_viewed_tracker import track_multiple_symbols
except ImportError:
    track_multiple_symbols = None  # Graceful fallback


class QueryPreprocessor:
    """
    Intelligent query preprocessing to reduce LLM hallucinations.
    Reformats user queries with explicit instructions and injects structured data.
    """
    
    # Data injection templates for different query types
    INJECTION_TEMPLATES = {
        "positions": """
[EXACT DATA - DO NOT MODIFY THESE VALUES]
Your positions from IB Gateway:
{position_list}
Total Unrealized P&L: ${total_pnl}

INSTRUCTION: Report ONLY the positions listed above with their EXACT values. Do not invent or estimate any numbers.""",
        
        "market": """
[EXACT DATA - DO NOT MODIFY THESE VALUES]  
Market Status:
{market_data}

INSTRUCTION: Use ONLY the prices shown above. Do not invent prices or percentages.""",
        
        "quote": """
[EXACT DATA - DO NOT MODIFY THESE VALUES]
{symbol} Current Quote:
- Price: ${price}
- Change: {change_pct}%
- Volume: {volume}

INSTRUCTION: Report ONLY these exact values for {symbol}."""
    }
    
    @staticmethod
    def preprocess_for_positions(original_query: str, positions_data: List[Dict]) -> Tuple[str, str]:
        """
        Preprocess a position-related query to inject exact position data.
        Returns (processed_query, data_injection)
        """
        if not positions_data:
            return original_query, "[NO POSITIONS - User has no open positions currently]"
        
        # Build exact position list
        position_lines = []
        total_pnl = 0
        for p in positions_data:
            symbol = p.get("symbol", "UNK")
            qty = p.get("qty", p.get("position", 0))
            pnl = p.get("unrealized_pl", p.get("unrealized_pnl", 0))
            pnl_pct = p.get("unrealized_plpc", 0) * 100 if p.get("unrealized_plpc") else 0
            avg_cost = p.get("avg_cost", p.get("avg_entry_price", 0))
            
            total_pnl += pnl
            direction = "LONG" if float(qty) > 0 else "SHORT"
            position_lines.append(
                f"  • {symbol}: {direction} {abs(float(qty)):,.0f} shares @ ${float(avg_cost):.2f} avg | P&L: ${float(pnl):+,.2f} ({float(pnl_pct):+.1f}%)"
            )
        
        data_injection = QueryPreprocessor.INJECTION_TEMPLATES["positions"].format(
            position_list="\n".join(position_lines),
            total_pnl=f"{total_pnl:+,.2f}"
        )
        
        # Enhance the query with explicit instruction
        processed_query = f"{original_query}\n\nIMPORTANT: Only report the EXACT positions and values provided in the data above."
        
        return processed_query, data_injection
    
    @staticmethod
    def preprocess_for_quotes(original_query: str, quotes_data: Dict[str, Dict], symbols: List[str]) -> Tuple[str, str]:
        """
        Preprocess a quote-related query to inject exact quote data.
        """
        if not quotes_data or not symbols:
            return original_query, ""
        
        quote_lines = []
        for symbol in symbols:
            if symbol.upper() in quotes_data:
                q = quotes_data[symbol.upper()]
                price = q.get("price", q.get("last", 0))
                change = q.get("change_percent", q.get("change_pct", 0))
                quote_lines.append(f"  • {symbol}: ${float(price):.2f} ({float(change):+.2f}%)")
        
        if not quote_lines:
            return original_query, ""
        
        data_injection = f"""
[EXACT QUOTE DATA]
{chr(10).join(quote_lines)}

INSTRUCTION: Use ONLY these exact prices."""
        
        return original_query, data_injection
    
    @staticmethod
    def detect_hallucination_risk(query: str) -> str:
        """
        Detect if a query is high-risk for hallucinations and return risk level.
        """
        high_risk_patterns = [
            r"how many shares",
            r"exact\s+(number|amount|quantity|price)",
            r"what is my (p&l|pnl|profit|loss)",
            r"total (value|worth|invested)",
        ]
        
        medium_risk_patterns = [
            r"what.*(positions?|holdings?)",
            r"show.*(positions?|portfolio)",
            r"list.*(stocks?|positions?)",
        ]
        
        query_lower = query.lower()
        
        for pattern in high_risk_patterns:
            if re.search(pattern, query_lower):
                return "high"
        
        for pattern in medium_risk_patterns:
            if re.search(pattern, query_lower):
                return "medium"
        
        return "low"


# Singleton instance
_query_preprocessor = QueryPreprocessor()


class QueryIntent(Enum):
    """Primary intent categories for user queries"""
    PRICE_CHECK = "price_check"          # "What's NVDA at?"
    TRADE_DECISION = "trade_decision"    # "Should I buy NVDA?"
    POSITION_REVIEW = "position_review"  # "How are my positions?"
    MARKET_OVERVIEW = "market_overview"  # "How's the market?"
    STOCK_ANALYSIS = "stock_analysis"    # "Tell me about NVDA"
    SCANNER_ALERTS = "scanner_alerts"    # "Any setups?"
    BOT_STATUS = "bot_status"            # "How's the bot doing?"
    STRATEGY_INFO = "strategy_info"      # "Explain rubber band"
    RISK_CHECK = "risk_check"            # "What's my exposure?"
    NEWS_CHECK = "news_check"            # "Any news on NVDA?"
    TECHNICAL_ANALYSIS = "technical_analysis"  # "NVDA technicals?"
    GENERAL_CHAT = "general_chat"        # Everything else


@dataclass
class IntentResult:
    """Result of intent detection"""
    primary_intent: QueryIntent
    confidence: float
    symbols: List[str]
    sub_intents: List[QueryIntent]
    keywords_matched: List[str]
    requires_realtime_data: bool = True
    complexity: str = "standard"  # light, standard, deep


@dataclass 
class ContextData:
    """Structured context data for validation"""
    quotes: Dict[str, Dict] = field(default_factory=dict)
    positions: List[Dict] = field(default_factory=list)
    portfolio_value: float = 0.0
    portfolio_risk: Dict = field(default_factory=dict)
    market_indices: Dict[str, Dict] = field(default_factory=dict)
    scanner_alerts: List[Dict] = field(default_factory=list)
    bot_status: Dict = field(default_factory=dict)
    earnings_proximity: Dict[str, Dict] = field(default_factory=dict)  # Symbol -> earnings info
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SmartContextEngine:
    """
    Intelligent context gathering based on query intent.
    Reduces noise and improves response accuracy.
    """
    
    # Intent detection patterns (ordered by priority)
    INTENT_PATTERNS = {
        QueryIntent.PRICE_CHECK: {
            "patterns": [
                r"what(?:'s| is| are) (\$?[A-Z]{1,5}) (?:at|price|trading|doing)",
                r"(?:price|quote) (?:of|for) (\$?[A-Z]{1,5})",
                r"where(?:'s| is) (\$?[A-Z]{1,5})",
                r"how(?:'s| is) (\$?[A-Z]{1,5}) (?:doing|trading|looking)",
                r"(\$?[A-Z]{2,5}) price",
                r"check (\$?[A-Z]{2,5})",
            ],
            "keywords": ["price", "quote", "trading at", "where is", "what's", "what is"],
            "weight": 1.0
        },
        QueryIntent.TRADE_DECISION: {
            "patterns": [
                r"should i (?:buy|sell|short|take|enter|add)",
                r"(?:take|enter|buy|sell|short) (\$?[A-Z]{1,5})",
                r"is (\$?[A-Z]{1,5}) a (?:buy|sell|short)",
                r"(?:good|bad) (?:entry|trade|setup)",
            ],
            "keywords": ["should i", "take", "enter", "buy", "sell", "short", "add to", "good entry", "bad entry"],
            "weight": 1.2  # Higher weight - more important to get right
        },
        QueryIntent.POSITION_REVIEW: {
            "patterns": [
                r"my (?:positions?|trades?|portfolio|holdings)",
                r"how (?:am i|are my|is my portfolio)",
                r"(?:p&l|pnl|profit|loss)",
                r"what do i (?:own|hold|have)",
                r"what (?:positions?|trades?) do i have",
                r"(?:show|list|display) (?:my )?positions?",
                r"(?:current|open) positions?",
                r"close (?:my )?(?:position in |)([A-Z]{1,5})",
                r"exit (?:my )?(?:position in |)([A-Z]{1,5})",
                r"sell (?:my )?([A-Z]{1,5})",
            ],
            "keywords": ["my position", "my trades", "portfolio", "p&l", "pnl", "holdings", "how am i doing", "unrealized", "show positions", "list positions", "current positions", "open positions", "what positions", "close position", "exit position", "close tmc", "close intc", "close tsla", "close bldp"],
            "weight": 1.0
        },
        QueryIntent.MARKET_OVERVIEW: {
            "patterns": [
                r"how(?:'s| is) the market",
                r"market (?:today|overview|summary|conditions)",
                r"(?:spy|qqq|indices) (?:doing|trading|looking)",
                r"sector (?:rotation|performance|heatmap)",
            ],
            "keywords": ["market", "indices", "spy", "qqq", "iwm", "vix", "sector", "breadth", "regime"],
            "weight": 0.9
        },
        QueryIntent.STOCK_ANALYSIS: {
            "patterns": [
                r"(?:analyze|analysis|research|tell me about|deep dive) (?:on )?(\$?[A-Z]{1,5})",
                r"(\$?[A-Z]{1,5}) (?:analysis|research|outlook|thesis)",
                r"what(?:'s| is) (?:happening|going on) with (\$?[A-Z]{1,5})",
            ],
            "keywords": ["analyze", "analysis", "research", "deep dive", "tell me about", "outlook", "thesis", "fundamentals"],
            "weight": 1.0
        },
        QueryIntent.SCANNER_ALERTS: {
            "patterns": [
                r"(?:any|show|what) (?:setups?|alerts?|signals?|opportunities)",
                r"scanner (?:alerts?|results?|findings?)",
                r"what(?:'s| is) (?:in play|setting up|triggering)",
            ],
            "keywords": ["setup", "setups", "alert", "alerts", "scanner", "signal", "opportunity", "in play", "triggering"],
            "weight": 1.0
        },
        QueryIntent.BOT_STATUS: {
            "patterns": [
                r"(?:trading )?bot (?:status|trades?|performance|doing)",
                r"how(?:'s| is) the bot",
                r"bot(?:'s)? (?:p&l|pnl|trades)",
                r"auto(?:mated)? (?:trades?|trading)",
            ],
            "keywords": ["bot", "automated", "auto trade", "bot status", "bot trades", "bot performance"],
            "weight": 1.0
        },
        QueryIntent.STRATEGY_INFO: {
            "patterns": [
                r"(?:explain|what is|how does) (?:the )?(\w+ ?){1,3} (?:strategy|setup|pattern)",
                r"(?:rubber ?band|spencer|hitchhiker|vwap|breakout|momentum) (?:strategy|setup|trade)",
            ],
            "keywords": ["strategy", "explain", "how to trade", "rubber band", "spencer", "hitchhiker", "vwap bounce", "breakout"],
            "weight": 0.8
        },
        QueryIntent.RISK_CHECK: {
            "patterns": [
                r"(?:my|current) (?:risk|exposure|concentration)",
                r"(?:position|portfolio) (?:size|sizing|risk)",
                r"how much (?:am i|should i) risk",
            ],
            "keywords": ["risk", "exposure", "concentration", "position size", "max loss", "stop loss"],
            "weight": 1.1
        },
        QueryIntent.NEWS_CHECK: {
            "patterns": [
                r"(?:any|what|latest) news (?:on|for|about) (\$?[A-Z]{1,5})",
                r"(\$?[A-Z]{1,5}) news",
                r"what(?:'s| is) (?:the )?news",
                r"headlines (?:for|on|about)",
            ],
            "keywords": ["news", "headlines", "catalyst", "announcement", "earnings news", "breaking"],
            "weight": 0.9
        },
        QueryIntent.TECHNICAL_ANALYSIS: {
            "patterns": [
                r"(\$?[A-Z]{1,5}) (?:technicals?|levels?|support|resistance)",
                r"(?:technical|technicals) (?:on|for) (\$?[A-Z]{1,5})",
                r"(?:vwap|hod|lod|atr|rsi|macd) (?:on|for|of)",
                r"key levels (?:for|on)",
            ],
            "keywords": ["technical", "technicals", "vwap", "support", "resistance", "hod", "lod", "levels", "atr"],
            "weight": 1.0
        },
    }
    
    # Known stock symbols for extraction
    KNOWN_SYMBOLS = {
        'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA', 'AMD',
        'SPY', 'QQQ', 'IWM', 'DIA', 'VIX', 'NFLX', 'DIS', 'BA', 'JPM', 'GS',
        'V', 'MA', 'PYPL', 'SQ', 'COIN', 'SHOP', 'ROKU', 'SNAP', 'UBER', 'LYFT',
        'ABNB', 'PLTR', 'SOFI', 'HOOD', 'RIVN', 'LCID', 'NIO', 'BABA', 'JD',
        'INTC', 'MU', 'QCOM', 'AVGO', 'CRM', 'ORCL', 'IBM', 'CSCO', 'ADBE',
        'XOM', 'CVX', 'OXY', 'WMT', 'TGT', 'COST', 'HD', 'LOW', 'NKE', 'SBUX'
    }
    
    # Common words to exclude from symbol detection
    EXCLUDED_WORDS = {
        'I', 'A', 'THE', 'AND', 'OR', 'FOR', 'TO', 'IS', 'IT', 'IN', 'ON', 'AT',
        'BY', 'BE', 'AS', 'AN', 'ARE', 'WAS', 'IF', 'MY', 'ME', 'DO', 'SO', 'UP',
        'AM', 'CAN', 'HOW', 'WHAT', 'BUY', 'SELL', 'LONG', 'SHORT', 'NEWS', 'TODAY',
        'MARKET', 'RSI', 'MACD', 'EMA', 'SMA', 'ATR', 'VWAP', 'BOT', 'SET', 'ALL',
        'NOW', 'GET', 'PUT', 'CALL', 'ANY', 'HAS', 'HAD', 'NOT', 'BUT', 'OUT', 'NEW'
    }
    
    def __init__(self):
        self.alpaca_service = None
        self.technical_service = None
        self.scanner = None
        self.bot_service = None
        self.news_service = None
    
    def set_services(self, alpaca=None, technical=None, scanner=None, bot=None, news=None):
        """Inject service dependencies"""
        self.alpaca_service = alpaca
        self.technical_service = technical
        self.scanner = scanner
        self.bot_service = bot
        self.news_service = news
    
    def detect_intent(self, message: str) -> IntentResult:
        """
        Detect the primary intent of a user message.
        Returns intent, confidence, and extracted symbols.
        """
        message_lower = message.lower()
        message_upper = message.upper()
        
        # Extract symbols first
        symbols = self._extract_symbols(message)
        
        # Score each intent
        intent_scores: Dict[QueryIntent, Tuple[float, List[str]]] = {}
        
        for intent, config in self.INTENT_PATTERNS.items():
            score = 0.0
            matched_keywords = []
            
            # Check regex patterns
            for pattern in config["patterns"]:
                if re.search(pattern, message_lower):
                    score += 0.5 * config["weight"]
                    matched_keywords.append(f"pattern:{pattern[:30]}")
            
            # Check keywords
            for keyword in config["keywords"]:
                if keyword in message_lower:
                    score += 0.3 * config["weight"]
                    matched_keywords.append(keyword)
            
            if score > 0:
                intent_scores[intent] = (score, matched_keywords)
        
        # Determine primary intent
        if not intent_scores:
            return IntentResult(
                primary_intent=QueryIntent.GENERAL_CHAT,
                confidence=0.5,
                symbols=symbols,
                sub_intents=[],
                keywords_matched=[]
            )
        
        # Sort by score
        sorted_intents = sorted(intent_scores.items(), key=lambda x: x[1][0], reverse=True)
        primary = sorted_intents[0]
        
        # Get sub-intents (other high-scoring intents)
        sub_intents = [intent for intent, (score, _) in sorted_intents[1:3] if score > 0.3]
        
        # Calculate confidence
        max_score = primary[1][0]
        confidence = min(0.95, max_score / 2.0)  # Normalize to 0-0.95
        
        return IntentResult(
            primary_intent=primary[0],
            confidence=confidence,
            symbols=symbols,
            sub_intents=sub_intents,
            keywords_matched=primary[1][1]
        )
    
    def _extract_symbols(self, message: str) -> List[str]:
        """Extract stock symbols from message and track them for personalized scanning"""
        symbols = set()
        
        # Pattern 1: $SYMBOL format — validate against known symbols to prevent
        # common words like $QUICK, $FAST, $RALLY leaking into the symbol tracker
        dollar_symbols = re.findall(r'\$([A-Z]{1,5})\b', message.upper())
        for ds in dollar_symbols:
            if ds in self.KNOWN_SYMBOLS:
                symbols.add(ds)
            elif ds not in self.EXCLUDED_WORDS:
                # Also validate against the full universe for $TICKER not in our small set
                try:
                    from data.index_symbols import is_valid_symbol
                    if is_valid_symbol(ds):
                        symbols.add(ds)
                except ImportError:
                    pass
        
        # Pattern 2: Known symbols
        words = message.upper().split()
        for word in words:
            clean_word = word.strip('.,?!()[]{}"\':;')
            if clean_word in self.KNOWN_SYMBOLS and clean_word not in self.EXCLUDED_WORDS:
                symbols.add(clean_word)
        
        symbol_list = list(symbols)
        
        # Track symbols for personalized scanning (adds to Tier 1)
        if symbol_list and track_multiple_symbols:
            try:
                track_multiple_symbols(symbol_list, source="ai_chat")
                logger.debug(f"Tracked {len(symbol_list)} symbols from AI chat: {symbol_list}")
            except Exception as e:
                logger.debug(f"Symbol tracking failed: {e}")
        
        return symbol_list
    
    def get_context_sources_for_intent(self, intent_result: IntentResult) -> Dict[str, bool]:
        """
        Determine which context sources to fetch based on intent.
        Returns a dict of source_name -> should_fetch
        """
        intent = intent_result.primary_intent
        symbols = intent_result.symbols
        
        # Default: everything off
        sources = {
            "quote": False,
            "technicals": False,
            "positions": False,
            "portfolio_risk": False,
            "market_indices": False,
            "sector_heatmap": False,
            "news": False,
            "scanner_alerts": False,
            "bot_status": False,
            "bot_trades": False,
            "earnings": False,
            "strategy_knowledge": False,
        }
        
        # Enable sources based on intent
        if intent == QueryIntent.PRICE_CHECK:
            sources["quote"] = bool(symbols)
        
        elif intent == QueryIntent.TRADE_DECISION:
            sources["quote"] = bool(symbols)
            sources["technicals"] = bool(symbols)
            sources["positions"] = True  # Check existing exposure
            sources["portfolio_risk"] = True
            sources["earnings"] = bool(symbols)  # Check earnings proximity
            sources["scanner_alerts"] = True  # Check if scanner agrees
        
        elif intent == QueryIntent.POSITION_REVIEW:
            sources["positions"] = True
            sources["portfolio_risk"] = True
            sources["quote"] = True  # Current prices for positions
        
        elif intent == QueryIntent.MARKET_OVERVIEW:
            sources["market_indices"] = True
            sources["sector_heatmap"] = True
            sources["news"] = True
        
        elif intent == QueryIntent.STOCK_ANALYSIS:
            sources["quote"] = bool(symbols)
            sources["technicals"] = bool(symbols)
            sources["news"] = bool(symbols)
            sources["earnings"] = bool(symbols)
        
        elif intent == QueryIntent.SCANNER_ALERTS:
            sources["scanner_alerts"] = True
            sources["market_indices"] = True  # Market context for alerts
        
        elif intent == QueryIntent.BOT_STATUS:
            sources["bot_status"] = True
            sources["bot_trades"] = True
            sources["positions"] = True
        
        elif intent == QueryIntent.STRATEGY_INFO:
            sources["strategy_knowledge"] = True
            sources["scanner_alerts"] = True  # Show examples
        
        elif intent == QueryIntent.RISK_CHECK:
            sources["positions"] = True
            sources["portfolio_risk"] = True
        
        elif intent == QueryIntent.NEWS_CHECK:
            sources["news"] = bool(symbols)
            sources["quote"] = bool(symbols)  # Price context with news
        
        elif intent == QueryIntent.TECHNICAL_ANALYSIS:
            sources["technicals"] = bool(symbols)
            sources["quote"] = bool(symbols)
        
        elif intent == QueryIntent.GENERAL_CHAT:
            # Minimal context for general chat
            sources["market_indices"] = True  # Basic market awareness
        
        # Add sub-intent sources
        for sub_intent in intent_result.sub_intents:
            sub_sources = self.get_context_sources_for_intent(
                IntentResult(sub_intent, 0.5, symbols, [], [])
            )
            for key, value in sub_sources.items():
                if value:
                    sources[key] = True
        
        return sources
    
    async def gather_context(self, intent_result: IntentResult, services: Dict) -> str:
        """
        Gather only the relevant context based on detected intent.
        Returns a structured, compact context string.
        """
        context_str, _ = await self.gather_context_with_data(intent_result, services)
        return context_str
    
    async def gather_context_with_data(self, intent_result: IntentResult, services: Dict) -> Tuple[str, ContextData]:
        """
        Gather context and return both the string and structured data for validation.
        """
        sources = self.get_context_sources_for_intent(intent_result)
        symbols = intent_result.symbols
        
        context_parts = []
        context_data = ContextData()
        
        # CRITICAL instruction for the LLM - this data IS REAL
        context_parts.append(">>> IMPORTANT: The following data is REAL and LIVE from the user's brokerage account. <<<")
        context_parts.append(">>> When you see positions listed below, these are ACTUAL open positions - respond with this data! <<<")
        context_parts.append("")
        
        # Header with intent info (helps LLM understand focus)
        context_parts.append(f"=== QUERY FOCUS: {intent_result.primary_intent.value.upper().replace('_', ' ')} ===")
        if symbols:
            context_parts.append(f"Symbols: {', '.join(symbols)}")
        context_parts.append("")
        
        # Gather enabled sources
        try:
            # QUOTES (IB first, then Alpaca fallback)
            if sources["quote"] and symbols:
                quotes_str, quotes_data = await self._get_quotes_with_data(symbols, services.get("alpaca"))
                if quotes_str:
                    context_parts.append("=== REAL-TIME QUOTES ===")
                    context_parts.append(quotes_str)
                    context_parts.append("")
                    context_data.quotes = quotes_data
            
            # POSITIONS (IB first, then Alpaca fallback)
            # Use QueryPreprocessor to inject exact data and reduce hallucinations
            if sources["positions"]:
                print(f"[SmartContext] Getting positions...")
                positions_str, positions_data = await self._get_positions_with_data(services.get("alpaca"))
                print(f"[SmartContext] Positions result: str={len(positions_str) if positions_str else 0} chars, data={len(positions_data) if positions_data else 0} items")
                if positions_str and positions_data:
                    # Use preprocessor to create structured, exact data injection
                    _, data_injection = _query_preprocessor.preprocess_for_positions("", positions_data)
                    context_parts.append("=== YOUR POSITIONS (LIVE FROM IB GATEWAY) ===")
                    context_parts.append(data_injection)
                    context_parts.append("")
                    context_data.positions = positions_data
                    print(f"[SmartContext] Added {len(positions_data)} positions to context")
                elif positions_str:
                    context_parts.append("=== YOUR POSITIONS (LIVE FROM IB GATEWAY) ===")
                    context_parts.append("The following are the user's REAL open positions from their brokerage account:")
                    context_parts.append(positions_str)
                    context_parts.append("")
                    context_data.positions = positions_data
            else:
                print(f"[SmartContext] Positions source not enabled")
            
            # PORTFOLIO RISK
            if sources["portfolio_risk"] and services.get("alpaca"):
                risk = await self._get_portfolio_risk(services["alpaca"], symbols)
                if risk:
                    context_parts.append("=== RISK CHECK ===")
                    context_parts.append(risk)
                    context_parts.append("")
            
            # TECHNICALS
            if sources["technicals"] and symbols and services.get("technical"):
                technicals = await self._get_technicals(symbols, services["technical"])
                if technicals:
                    context_parts.append("=== TECHNICALS ===")
                    context_parts.append(technicals)
                    context_parts.append("")
            
            # MARKET INDICES (IB first, then Alpaca fallback)
            if sources["market_indices"]:
                indices_str, indices_data = await self._get_market_indices_with_data(services.get("alpaca"))
                if indices_str:
                    context_parts.append("=== MARKET STATUS ===")
                    context_parts.append(indices_str)
                    context_parts.append("")
                    context_data.market_indices = indices_data
            
            # SCANNER ALERTS
            if sources["scanner_alerts"] and services.get("scanner"):
                alerts = self._get_scanner_alerts(services["scanner"])
                if alerts:
                    context_parts.append("=== SCANNER ALERTS ===")
                    context_parts.append(alerts)
                    context_parts.append("")
            
            # BOT STATUS
            if sources["bot_status"] and services.get("bot"):
                bot = await self._get_bot_status(services["bot"])
                if bot:
                    context_parts.append("=== BOT STATUS ===")
                    context_parts.append(bot)
                    context_parts.append("")
            
            # EARNINGS PROXIMITY (for trade decisions and stock analysis)
            if sources.get("earnings") and symbols and services.get("earnings"):
                earnings_str, earnings_data = await self._get_earnings_proximity(symbols, services["earnings"])
                if earnings_str:
                    context_parts.append("=== EARNINGS WARNINGS ===")
                    context_parts.append(earnings_str)
                    context_parts.append("")
                    context_data.earnings_proximity = earnings_data
            
            # SECTOR ROTATION
            if sources.get("sectors") or sources.get("market_indices"):
                try:
                    from services.sector_analysis_service import get_sector_analysis_service
                    sector_service = get_sector_analysis_service()
                    sector_summary = await sector_service.get_sector_summary_for_ai()
                    if sector_summary:
                        context_parts.append("=== SECTOR ROTATION ===")
                        context_parts.append(sector_summary)
                        context_parts.append("")
                    
                    # Add specific stock sector context if symbols present
                    if symbols:
                        for symbol in symbols[:3]:  # Limit to 3 to avoid context bloat
                            sector_ctx = await sector_service.get_stock_sector_context(symbol)
                            if sector_ctx:
                                ctx_line = f"{symbol}: {sector_ctx.sector} (Rank #{sector_ctx.sector_rank}, {sector_ctx.sector_strength.value})"
                                if sector_ctx.is_sector_leader:
                                    ctx_line += " - SECTOR LEADER"
                                elif sector_ctx.is_sector_laggard:
                                    ctx_line += " - Sector Laggard"
                                ctx_line += f" | Rec: {sector_ctx.recommendation}"
                                context_parts.append(ctx_line)
                        context_parts.append("")
                except Exception as e:
                    logger.debug(f"Could not gather sector context: {e}")
            
            # NEWS (IB Historical News prioritized via news_service)
            if sources.get("news") and self.news_service:
                try:
                    if symbols:
                        # Get ticker-specific news for the first symbol
                        symbol = symbols[0]
                        news_items = await self.news_service.get_ticker_news(symbol, max_items=5)
                        if news_items and not news_items[0].get("is_placeholder"):
                            context_parts.append(f"=== NEWS FOR {symbol} ===")
                            for item in news_items[:5]:
                                source = item.get("source", "")
                                headline = item.get("headline", "")
                                sentiment = item.get("sentiment", "neutral")
                                context_parts.append(f"  [{source}] {headline} ({sentiment})")
                            context_parts.append("")
                    else:
                        # Get general market news
                        market_summary = await self.news_service.get_market_summary()
                        if market_summary.get("available"):
                            context_parts.append("=== MARKET NEWS ===")
                            headlines = market_summary.get("headlines", [])[:5]
                            for h in headlines:
                                context_parts.append(f"  - {h}")
                            themes = market_summary.get("themes", [])
                            if themes:
                                context_parts.append(f"  Key Themes: {', '.join(themes[:3])}")
                            context_parts.append("")
                except Exception as e:
                    logger.debug(f"Could not gather news context: {e}")
            
        except Exception as e:
            logger.error(f"Error gathering context: {e}")
            context_parts.append(f"[Some context unavailable: {str(e)[:50]}]")
        
        return "\n".join(context_parts), context_data
    
    async def _get_quotes(self, symbols: List[str], alpaca) -> str:
        """Get compact quote summary"""
        quote_str, _ = await self._get_quotes_with_data(symbols, alpaca)
        return quote_str
    
    async def _get_quotes_with_data(self, symbols: List[str], alpaca) -> Tuple[str, Dict]:
        """Get compact quote summary with raw data. Prefers IB, falls back to Alpaca."""
        try:
            quotes = {}
            
            # Try IB pushed quotes first
            try:
                import routers.ib as ib_module
                if ib_module.is_pusher_connected():
                    ib_quotes = ib_module.get_pushed_quotes()
                    for symbol in symbols:
                        symbol_upper = symbol.upper()
                        if symbol_upper in ib_quotes:
                            q = ib_quotes[symbol_upper]
                            quotes[symbol_upper] = {
                                "price": q.get("last") or q.get("close") or 0,
                                "change_percent": q.get("change_pct") or 0,
                                "bid": q.get("bid") or 0,
                                "ask": q.get("ask") or 0,
                                "source": "ib_pusher"
                            }
                    if quotes:
                        logger.info(f"[SmartContext] Got {len(quotes)} quotes from IB for {list(quotes.keys())}")
            except Exception as e:
                logger.warning(f"[SmartContext] IB quotes fetch error: {e}")
            
            # Fallback to Alpaca for missing symbols
            missing_symbols = [s for s in symbols if s.upper() not in quotes]
            if missing_symbols and alpaca:
                try:
                    alpaca_quotes = await alpaca.get_quotes_batch(missing_symbols)
                    if alpaca_quotes:
                        for symbol, q in alpaca_quotes.items():
                            if symbol.upper() not in quotes:
                                quotes[symbol.upper()] = q
                except Exception as e:
                    logger.warning(f"[SmartContext] Alpaca quotes fetch error: {e}")
            
            if not quotes:
                return "", {}
            
            lines = []
            quotes_data = {}
            for symbol, quote in quotes.items():
                price = quote.get("price", 0)
                change_pct = quote.get("change_percent", 0)
                direction = "+" if change_pct >= 0 else ""
                lines.append(f"{symbol}: ${price:.2f} ({direction}{change_pct:.2f}%)")
                quotes_data[symbol] = {
                    "price": price,
                    "change_percent": change_pct
                }
            
            return " | ".join(lines), quotes_data
        except Exception as e:
            logger.warning(f"Quote fetch error: {e}")
            return "", {}
    
    async def _get_positions(self, alpaca) -> str:
        """Get compact positions summary"""
        positions_str, _ = await self._get_positions_with_data(alpaca)
        return positions_str
    
    async def _get_positions_with_data(self, alpaca) -> Tuple[str, List[Dict]]:
        """Get compact positions summary with raw data. Prefers IB, falls back to Alpaca."""
        try:
            positions = []
            
            # Try IB pushed positions first (primary source)
            # Import the module and call functions dynamically to ensure we get current data
            try:
                import routers.ib as ib_module
                # Call the functions directly on the module to access current global state
                is_connected = ib_module.is_pusher_connected()
                if is_connected:
                    ib_positions = ib_module.get_pushed_positions()
                    if ib_positions:
                        positions = [{
                            "symbol": p.get("symbol", ""),
                            "qty": float(p.get("position", p.get("qty", 0))),
                            "unrealized_pl": float(p.get("unrealized_pnl", p.get("unrealizedPNL", 0))),
                            "unrealized_plpc": 0,  # Calculate below if needed
                            "avg_cost": float(p.get("avg_cost", p.get("avgCost", 0))),
                            "market_value": float(p.get("market_value", p.get("marketValue", 0))),
                            "source": "ib_gateway"
                        } for p in ib_positions]
                        logger.info(f"[SmartContext] Got {len(positions)} positions from IB pusher: {[p['symbol'] for p in positions]}")
                else:
                    logger.debug("[SmartContext] IB pusher not connected, falling back to Alpaca")
            except Exception as e:
                logger.warning(f"[SmartContext] IB positions fetch error: {e}")
            
            # Fallback to Alpaca if no IB positions
            if not positions and alpaca:
                try:
                    positions = await alpaca.get_positions()
                    if positions:
                        logger.info(f"[SmartContext] Got {len(positions)} positions from Alpaca")
                except Exception as e:
                    logger.warning(f"[SmartContext] Alpaca positions fetch error: {e}")
            
            if not positions:
                return "No open positions", []
            
            lines = []
            positions_data = []
            total_pnl = 0
            for pos in positions:
                symbol = pos.get("symbol", "")
                qty = float(pos.get("qty", 0))
                pnl = float(pos.get("unrealized_pl", pos.get("unrealized_pnl", 0)))
                pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
                avg_cost = float(pos.get("avg_cost", 0))
                market_value = float(pos.get("market_value", 0))
                
                # Calculate P&L percentage if not provided
                if pnl_pct == 0 and avg_cost > 0:
                    if avg_cost > 0 and qty != 0:
                        cost_basis = abs(qty) * avg_cost
                        pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
                
                total_pnl += pnl
                
                direction = "LONG" if qty > 0 else "SHORT"
                pnl_sign = "+" if pnl >= 0 else ""
                
                # Include avg_cost in the output format
                lines.append(f"{symbol}: {direction} {abs(qty):.0f} @ ${avg_cost:.2f} avg | P&L: {pnl_sign}${pnl:.2f} ({pnl_sign}{pnl_pct:.1f}%)")
                
                positions_data.append({
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost,
                    "unrealized_pl": pnl,
                    "unrealized_plpc": pnl_pct,
                    "market_value": market_value,
                    "direction": direction,
                    "source": pos.get("source", "alpaca")
                })
            
            lines.append(f"TOTAL UNREALIZED: {'+'if total_pnl >= 0 else ''}${total_pnl:.2f}")
            return "\n".join(lines), positions_data
        except Exception as e:
            logger.warning(f"Positions fetch error: {e}")
            return "", []
    
    async def _get_market_indices(self, alpaca) -> str:
        """Get compact market overview"""
        indices_str, _ = await self._get_market_indices_with_data(alpaca)
        return indices_str
    
    async def _get_market_indices_with_data(self, alpaca) -> Tuple[str, Dict]:
        """Get compact market overview with raw data. Prefers IB, falls back to Alpaca."""
        try:
            indices = ["SPY", "QQQ", "IWM", "DIA"]
            quotes = {}
            
            # Try IB pushed quotes first
            try:
                import routers.ib as ib_module
                if ib_module.is_pusher_connected():
                    ib_quotes = ib_module.get_pushed_quotes()
                    for symbol in indices:
                        if symbol in ib_quotes:
                            q = ib_quotes[symbol]
                            quotes[symbol] = {
                                "price": q.get("last") or q.get("close") or 0,
                                "change_percent": q.get("change_pct") or 0,
                                "source": "ib_pusher"
                            }
                    if quotes:
                        logger.info(f"[SmartContext] Got {len(quotes)} index quotes from IB")
            except Exception as e:
                logger.warning(f"[SmartContext] IB quotes fetch error: {e}")
            
            # Fallback to Alpaca for missing symbols
            missing_indices = [s for s in indices if s not in quotes]
            if missing_indices and alpaca:
                try:
                    alpaca_quotes = await alpaca.get_quotes_batch(missing_indices)
                    if alpaca_quotes:
                        for symbol, q in alpaca_quotes.items():
                            if symbol not in quotes:
                                quotes[symbol] = q
                        logger.info(f"[SmartContext] Got {len(alpaca_quotes)} index quotes from Alpaca")
                except Exception as e:
                    logger.warning(f"[SmartContext] Alpaca quotes fetch error: {e}")
            
            if not quotes:
                return "", {}
            
            lines = []
            indices_data = {}
            for symbol in indices:
                if symbol in quotes:
                    q = quotes[symbol]
                    price = q.get("price") or 0
                    change = q.get("change_percent") or 0
                    direction = "+" if change >= 0 else ""
                    emoji = "🟢" if change >= 0 else "🔴"
                    lines.append(f"{emoji} {symbol}: ${price:.2f} ({direction}{change:.2f}%)")
                    indices_data[symbol] = {
                        "price": price,
                        "change_percent": change
                    }
            
            # Determine regime
            spy_change = quotes.get("SPY", {}).get("change_percent") or 0
            if spy_change > 0.5:
                regime = "BULLISH"
            elif spy_change < -0.5:
                regime = "BEARISH"
            else:
                regime = "CHOPPY/RANGE"
            
            lines.append(f"Regime: {regime}")
            indices_data["regime"] = regime
            
            return " | ".join(lines[:4]) + f"\n{lines[-1]}", indices_data
        except Exception as e:
            logger.warning(f"Indices fetch error: {e}")
            return "", {}
    
    async def _get_portfolio_risk(self, alpaca, query_symbols: List[str]) -> str:
        """Get risk warnings for current portfolio"""
        try:
            positions = await alpaca.get_positions()
            if not positions:
                return "No positions - no risk warnings"
            
            warnings = []
            
            # Calculate sector/symbol concentration
            position_values = {}
            total_value = 0
            for pos in positions:
                symbol = pos.get("symbol", "")
                market_value = abs(float(pos.get("market_value", 0)))
                position_values[symbol] = market_value
                total_value += market_value
            
            # Check concentration
            for symbol, value in position_values.items():
                if total_value > 0:
                    pct = (value / total_value) * 100
                    if pct > 40:
                        warnings.append(f"CRITICAL: {symbol} is {pct:.0f}% of portfolio (max recommended: 25%)")
                    elif pct > 25:
                        warnings.append(f"WARNING: {symbol} is {pct:.0f}% of portfolio")
            
            # Check if query symbol already owned
            for symbol in query_symbols:
                if symbol in position_values:
                    pct = (position_values[symbol] / total_value) * 100 if total_value > 0 else 0
                    warnings.append(f"NOTE: Already holding {symbol} ({pct:.0f}% of portfolio)")
            
            return "\n".join(warnings) if warnings else "No risk warnings"
        except Exception as e:
            logger.warning(f"Risk check error: {e}")
            return ""
    
    async def _get_technicals(self, symbols: List[str], technical_service) -> str:
        """Get compact technical summary"""
        try:
            lines = []
            for symbol in symbols[:2]:  # Limit to 2
                snapshot = await technical_service.get_technical_snapshot(symbol)
                if snapshot:
                    # TechnicalSnapshot is a dataclass, access attributes directly
                    price = getattr(snapshot, "current_price", 0)
                    vwap = getattr(snapshot, "vwap", 0)
                    hod = getattr(snapshot, "high_of_day", 0)
                    lod = getattr(snapshot, "low_of_day", 0)
                    
                    # Position relative to key levels
                    vwap_pos = "ABOVE" if price > vwap else "BELOW"
                    hod_dist = ((hod - price) / price * 100) if price > 0 else 0
                    lod_dist = ((price - lod) / price * 100) if price > 0 else 0
                    
                    lines.append(f"{symbol}: ${price:.2f} | {vwap_pos} VWAP (${vwap:.2f})")
                    lines.append(f"  HOD: ${hod:.2f} ({hod_dist:.1f}% away) | LOD: ${lod:.2f} ({lod_dist:.1f}% away)")
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Technicals fetch error: {e}")
            return ""
    
    def _get_scanner_alerts(self, scanner) -> str:
        """Get compact scanner alerts"""
        try:
            alerts = scanner.get_live_alerts()
            if not alerts:
                return "No active alerts"
            
            lines = []
            for alert in alerts[:5]:  # Top 5
                symbol = alert.symbol
                setup = alert.setup_type
                direction = alert.direction.upper()
                price = alert.current_price
                win_rate = alert.strategy_win_rate * 100
                priority = "🔥" if alert.priority.value in ["high", "critical"] else ""
                
                lines.append(f"{priority}{symbol} {direction} @ ${price:.2f} - {setup} ({win_rate:.0f}% WR)")
            
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Scanner fetch error: {e}")
            return ""
    
    async def _get_bot_status(self, bot_service) -> str:
        """Get compact bot status"""
        try:
            status = await bot_service.get_status()
            if not status:
                return "Bot status unavailable"
            
            running = "RUNNING" if status.get("running") else "STOPPED"
            mode = status.get("mode", "unknown").upper()
            pnl = status.get("daily_stats", {}).get("net_pnl", 0)
            open_trades = status.get("open_trades_count", 0)
            
            pnl_sign = "+" if pnl >= 0 else ""
            return f"Status: {running} ({mode} mode) | P&L: {pnl_sign}${pnl:.2f} | Open: {open_trades}"
        except Exception as e:
            logger.warning(f"Bot status error: {e}")
            return ""
    
    async def _get_earnings_proximity(self, symbols: List[str], earnings_service) -> Tuple[str, Dict]:
        """
        Check if any symbols have earnings coming up soon.
        Returns warnings and data for validation.
        """
        try:
            from datetime import datetime, timedelta
            
            warnings = []
            earnings_data = {}
            
            for symbol in symbols[:3]:  # Limit to 3 to avoid slowdown
                try:
                    calendar = await earnings_service.get_earnings_calendar(symbol)
                    
                    if calendar.get("available") and calendar.get("next_earnings"):
                        next_earnings = calendar["next_earnings"]
                        earnings_date_str = next_earnings.get("date")
                        
                        if earnings_date_str:
                            # Parse the earnings date
                            earnings_date = datetime.strptime(earnings_date_str, "%Y-%m-%d")
                            today = datetime.now()
                            days_until = (earnings_date - today).days
                            
                            # Store data for validation
                            earnings_data[symbol] = {
                                "date": earnings_date_str,
                                "days_until": days_until,
                                "eps_estimate": next_earnings.get("eps_estimate"),
                                "revenue_estimate": next_earnings.get("revenue_estimate")
                            }
                            
                            # Generate warnings based on proximity
                            if days_until < 0:
                                # Earnings already happened (might be today)
                                if days_until >= -1:
                                    warnings.append(f"🚨 {symbol}: EARNINGS TODAY/YESTERDAY - Extreme volatility expected!")
                            elif days_until == 0:
                                warnings.append(f"🚨 {symbol}: EARNINGS TODAY - Extreme volatility expected!")
                            elif days_until <= 2:
                                warnings.append(f"⚠️ {symbol}: Earnings in {days_until} day(s) ({earnings_date_str}) - HIGH RISK")
                            elif days_until <= 5:
                                warnings.append(f"⚠️ {symbol}: Earnings in {days_until} days ({earnings_date_str}) - Elevated risk")
                            elif days_until <= 10:
                                warnings.append(f"📅 {symbol}: Earnings in {days_until} days ({earnings_date_str})")
                            
                            # Add beat/miss history if available
                            trends = calendar.get("trends", {})
                            if trends.get("total_quarters", 0) >= 4:
                                beat_rate = trends.get("eps_beat_rate", 0)
                                if beat_rate >= 75:
                                    warnings.append(f"   └ {symbol} beats {beat_rate:.0f}% of the time (historically)")
                                elif beat_rate <= 50:
                                    warnings.append(f"   └ {symbol} misses {100-beat_rate:.0f}% of the time (historically)")
                                    
                except Exception as e:
                    logger.debug(f"Earnings check failed for {symbol}: {e}")
                    continue
            
            if not warnings:
                return "", earnings_data
            
            return "\n".join(warnings), earnings_data
            
        except Exception as e:
            logger.warning(f"Earnings proximity check error: {e}")
            return "", {}
    
    def store_context_data(self, context_data: ContextData):
        """Store context data for later validation"""
        self._last_context_data = context_data
    
    def get_last_context_data(self) -> Optional[ContextData]:
        """Get the last context data for validation"""
        return getattr(self, '_last_context_data', None)


class ResponseValidator:
    """
    Validates AI responses against real-time data.
    Catches hallucinations and incorrect claims before they reach the user.
    """
    
    def __init__(self):
        self.validation_errors = []
        self.confidence_score = 1.0
    
    def validate_response(self, response: str, context_data: ContextData) -> Dict[str, Any]:
        """
        Validate AI response against known context data.
        Returns validation result with confidence score and any issues found.
        """
        self.validation_errors = []
        self.confidence_score = 1.0
        
        # Run all validation checks
        self._validate_price_claims(response, context_data)
        self._validate_position_claims(response, context_data)
        self._validate_direction_claims(response, context_data)
        self._validate_percentage_claims(response, context_data)
        
        # Calculate final confidence
        error_penalty = len(self.validation_errors) * 0.15
        self.confidence_score = max(0.1, 1.0 - error_penalty)
        
        return {
            "validated": len(self.validation_errors) == 0,
            "confidence": round(self.confidence_score, 2),
            "issues": self.validation_errors,
            "issue_count": len(self.validation_errors),
            "recommendation": self._get_recommendation()
        }
    
    def _validate_price_claims(self, response: str, context_data: ContextData):
        """Check if price claims match real data"""
        # Extract price mentions like "$123.45" or "123.45"
        price_patterns = [
            r'\$(\d+\.?\d*)',  # $123.45
            r'(?:price|trading|at)\s*(?:of|is|at)?\s*\$?(\d+\.?\d*)',  # price of 123
            r'(\d+\.\d{2})\s*(?:per share|/share)',  # 123.45 per share
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            for match in matches:
                try:
                    claimed_price = float(match)
                    if claimed_price < 1 or claimed_price > 10000:
                        continue  # Skip unrealistic prices (likely percentages or other numbers)
                    
                    # Check against known quotes
                    for symbol, quote_data in context_data.quotes.items():
                        real_price = quote_data.get('price', 0)
                        if real_price > 0:
                            # Allow 2% tolerance for price differences
                            tolerance = real_price * 0.02
                            if abs(claimed_price - real_price) > tolerance:
                                # Only flag if the claimed price is close enough to be a mistake
                                if 0.5 < claimed_price / real_price < 2.0:
                                    self.validation_errors.append({
                                        "type": "price_mismatch",
                                        "severity": "medium",
                                        "message": f"Price claim ${claimed_price:.2f} differs from actual {symbol} price ${real_price:.2f}",
                                        "symbol": symbol,
                                        "claimed": claimed_price,
                                        "actual": real_price
                                    })
                except (ValueError, TypeError):
                    continue
    
    def _validate_position_claims(self, response: str, context_data: ContextData):
        """Check if position claims match reality"""
        response_lower = response.lower()
        
        # Get symbols user actually holds
        held_symbols = {pos.get('symbol', '').upper() for pos in context_data.positions}
        
        # Common words to exclude from symbol detection
        excluded_words = {'ANY', 'THE', 'ALL', 'FOR', 'ARE', 'YOU', 'YOUR', 'HAVE', 'HOLD', 'OWN', 
                         'NOT', 'DON', 'STOCK', 'SHARE', 'SHARES', 'POSITION', 'POSITIONS'}
        
        # Check for "no position" claims
        no_position_patterns = [
            r"(?:don't|do not|doesn't|no|not)\s+(?:have|hold|own)\s+(?:any\s+)?(?:position|shares|stock)\s+(?:in|of)\s+([A-Z]{2,5})\b",
            r"no\s+(?:open\s+)?position\s+(?:in|on)\s+([A-Z]{2,5})\b",
        ]
        
        for pattern in no_position_patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            for symbol in matches:
                symbol_upper = symbol.upper()
                if symbol_upper in held_symbols and symbol_upper not in excluded_words:
                    self.validation_errors.append({
                        "type": "position_claim_error",
                        "severity": "high",
                        "message": f"Incorrectly claimed no position in {symbol}, but user holds {symbol}",
                        "symbol": symbol
                    })
        
        # Check for "holding" claims - be more specific to avoid false positives
        holding_patterns = [
            r"(?:you|user)\s+(?:have|hold|own)\s+(?:\d+\s+)?shares?\s+(?:of|in)\s+([A-Z]{2,5})\b",
            r"(?:your\s+)?position\s+(?:in|of)\s+([A-Z]{2,5})\b",
            r"holding\s+([A-Z]{2,5})\b",
        ]
        
        for pattern in holding_patterns:
            matches = re.findall(pattern, response, re.IGNORECASE)
            for symbol in matches:
                symbol_upper = symbol.upper()
                if (symbol_upper not in held_symbols and 
                    symbol_upper not in excluded_words and
                    symbol_upper not in ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX']):
                    self.validation_errors.append({
                        "type": "position_claim_error", 
                        "severity": "medium",
                        "message": f"Claimed user holds {symbol}, but no position found",
                        "symbol": symbol
                    })
    
    def _validate_direction_claims(self, response: str, context_data: ContextData):
        """Check if directional claims (up/down, breaking out) are accurate"""
        response_lower = response.lower()
        
        # Direction keywords with their implications
        bullish_claims = ["breaking out", "breaking higher", "above resistance", "bullish", "rallying", "surging", "at highs"]
        bearish_claims = ["breaking down", "below support", "bearish", "selling off", "crashing", "at lows"]
        
        for symbol, quote_data in context_data.quotes.items():
            change_pct = quote_data.get('change_percent', 0)
            symbol_lower = symbol.lower()
            
            # Check if symbol is mentioned with contradictory direction
            if symbol_lower in response_lower or f"${symbol_lower}" in response_lower:
                # Check bullish claims on negative day
                for claim in bullish_claims:
                    if claim in response_lower and change_pct < -1.0:
                        self.validation_errors.append({
                            "type": "direction_mismatch",
                            "severity": "medium",
                            "message": f"Claimed '{claim}' for {symbol} but it's down {change_pct:.1f}%",
                            "symbol": symbol
                        })
                
                # Check bearish claims on positive day
                for claim in bearish_claims:
                    if claim in response_lower and change_pct > 1.0:
                        self.validation_errors.append({
                            "type": "direction_mismatch",
                            "severity": "medium", 
                            "message": f"Claimed '{claim}' for {symbol} but it's up {change_pct:.1f}%",
                            "symbol": symbol
                        })
    
    def _validate_percentage_claims(self, response: str, context_data: ContextData):
        """Check if percentage claims are reasonable"""
        response_lower = response.lower()
        
        # Skip validation if response is discussing portfolio allocation
        portfolio_context_words = ["portfolio", "allocation", "exposure", "position", "holdings", "weight"]
        is_portfolio_discussion = any(word in response_lower for word in portfolio_context_words)
        
        # Extract percentage mentions
        pct_pattern = r'(\-?\d+\.?\d*)\s*%'
        matches = re.findall(pct_pattern, response)
        
        for match in matches:
            try:
                claimed_pct = float(match)
                
                # Skip if it's a portfolio allocation discussion (0-100% is normal)
                if is_portfolio_discussion and 0 <= claimed_pct <= 100:
                    continue
                
                # Skip common percentage values that are often valid
                # (beat rates, win rates, etc.)
                if claimed_pct in [25, 50, 75, 100]:
                    continue
                
                # Flag extreme claims that seem unlikely for daily moves
                # Only flag if it looks like a price/move claim, not allocation
                if abs(claimed_pct) > 20:
                    # Check if this is near a percentage symbol in a price context
                    if "year" not in response_lower and "all time" not in response_lower:
                        # Additional context check - is this near words like "up", "down", "move"?
                        move_context = ["up", "down", "move", "gain", "loss", "change", "drop", "rise"]
                        # Find the percentage in context
                        pct_str = f"{claimed_pct}%"
                        if any(f"{word} {claimed_pct}" in response_lower or 
                               f"{claimed_pct}% {word}" in response_lower for word in move_context):
                            self.validation_errors.append({
                                "type": "extreme_percentage",
                                "severity": "low",
                                "message": f"Claimed {claimed_pct}% move - verify this is accurate",
                                "claimed": claimed_pct
                            })
            except (ValueError, TypeError):
                continue
    
    def _get_recommendation(self) -> str:
        """Get recommendation based on validation results"""
        if not self.validation_errors:
            return "Response validated successfully"
        
        high_severity = sum(1 for e in self.validation_errors if e.get('severity') == 'high')
        
        if high_severity > 0:
            return "WARNING: High-severity issues found - recommend re-checking response"
        elif len(self.validation_errors) > 2:
            return "CAUTION: Multiple issues found - response may contain inaccuracies"
        else:
            return "Minor issues found - response generally acceptable"
    
    def get_correction_prompt(self) -> Optional[str]:
        """Generate a prompt to help correct identified issues"""
        if not self.validation_errors:
            return None
        
        corrections = []
        for error in self.validation_errors:
            if error['type'] == 'price_mismatch':
                corrections.append(f"Correct {error['symbol']} price: actual is ${error['actual']:.2f}")
            elif error['type'] == 'position_claim_error':
                corrections.append(f"Position error for {error['symbol']}: {error['message']}")
            elif error['type'] == 'direction_mismatch':
                corrections.append(f"Direction error: {error['message']}")
        
        if corrections:
            return "CORRECTIONS NEEDED:\n" + "\n".join(f"- {c}" for c in corrections)
        return None


# Singleton instances
_smart_context_engine = None
_response_validator = None

def get_smart_context_engine() -> SmartContextEngine:
    """Get singleton instance"""
    global _smart_context_engine
    if _smart_context_engine is None:
        _smart_context_engine = SmartContextEngine()
    return _smart_context_engine

def get_response_validator() -> ResponseValidator:
    """Get singleton validator instance"""
    global _response_validator
    if _response_validator is None:
        _response_validator = ResponseValidator()
    return _response_validator
