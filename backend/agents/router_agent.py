"""
Router Agent
Fast intent classification - routes requests to the appropriate specialized agent.
Uses small, fast model since it only classifies text (no data handling).
"""
import re
import json
import time
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from agents.base_agent import BaseAgent, AgentType, AgentResponse
from agents.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Possible user intents that route to different agents"""
    TRADE_EXECUTE = "trade_execute"      # "close TMC", "buy NVDA"
    TRADE_QUERY = "trade_query"          # "should I close TMC?"
    POSITION_QUERY = "position_query"    # "what are my positions?"
    ANALYSIS = "analysis"                # "analyze NVDA", "what's the setup?"
    SCANNER = "scanner"                  # "what setups are forming?"
    COACHING = "coaching"                # "how am I doing?", "what should I improve?"
    MARKET_INFO = "market_info"          # "what's AAPL trading at?"
    GENERAL_CHAT = "general_chat"        # General questions, greetings


@dataclass
class RoutingResult:
    """Result of intent classification"""
    intent: Intent
    confidence: float
    symbols: List[str]
    action: Optional[str] = None  # buy, sell, close, etc.
    metadata: Dict = None


class RouterAgent(BaseAgent):
    """
    Fast intent classification agent.
    Uses pattern matching first, falls back to LLM for ambiguous cases.
    Routes to: TradeExecutor, Coach, Analyst, Chat
    """
    
    def __init__(self, llm_provider: LLMProvider = None):
        super().__init__(
            agent_type=AgentType.ROUTER,
            llm_provider=llm_provider,
            model="llama3:8b"  # Fast, small model for classification
        )
        
        # Compile regex patterns for fast matching
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Pre-compile regex patterns for fast matching"""
        
        # Trade execution patterns (high priority - direct action)
        self.trade_execute_patterns = [
            r"^(close|sell|exit)\s+(?:my\s+)?(?:position\s+(?:in\s+)?)?([A-Z]{1,5})(?:\s+position)?",
            r"^(buy|long|enter)\s+([A-Z]{1,5})",
            r"^(buy|long|enter)\s+\d+\s+(?:shares?\s+(?:of\s+)?)?([A-Z]{1,5})",  # "buy 100 shares of AAPL"
            r"^(short)\s+([A-Z]{1,5})",
            r"^(?:yes|yeah|yep|confirm|do it|execute|go ahead)(?:\s*,?\s*(?:close|sell|buy|execute))?",
        ]
        
        # Position query patterns
        self.position_patterns = [
            r"(?:what|show|list|display)(?:\s+are)?\s+(?:my\s+)?positions?",
            r"(?:my|current)\s+(?:open\s+)?positions?",
            r"what\s+(?:am\s+i|do\s+i)\s+(?:holding|have|own)",
            r"\bportfolio\b",
            r"\bp&?l\b|\bpnl\b|\bprofit\b|\bloss\b",
        ]
        
        # Analysis patterns
        self.analysis_patterns = [
            r"(?:analyze|analysis|analyse)\s+([a-z]{1,5})",
            r"(?:what|how)\s+(?:is|does)\s+([a-z]{1,5})\s+look",
            r"(?:technical|technicals|chart)\s+(?:on|for)\s+([a-z]{1,5})",
            r"(?:support|resistance|levels)\s+(?:on|for)\s+([a-z]{1,5})",
            r"(?:thoughts?|opinion|view)\s+(?:on|about)\s+([a-z]{1,5})",
            r"([a-z]{1,5})\s+(?:for\s+)?(?:a\s+)?trades?\b",
            r"(?:should\s+i|would\s+you)\s+(?:buy|sell|trade)\s+([a-z]{1,5})",
            r"(?:is|does)\s+([a-z]{1,5})\s+(?:look|seem)\s+(?:good|bullish|bearish)",
        ]
        
        # Scanner patterns
        self.scanner_patterns = [
            r"(?:what|any|show)\s+(?:setups?|alerts?|opportunities)",
            r"scanner",
            r"(?:what.s|whats)\s+(?:forming|setting up)",
            r"trade\s+ideas?",
        ]
        
        # Coaching patterns
        self.coaching_patterns = [
            r"(?:how|what)\s+(?:am\s+i|should\s+i)\s+doing",
            r"(?:what|where)\s+(?:should|can|could)\s+i\s+improve",
            r"(?:my|trading)\s+(?:mistakes?|patterns?|habits?)",
            r"(?:coach|coaching|advice|guidance)",
            r"(?:review|analyze)\s+(?:my\s+)?(?:trading|performance)",
        ]
        
        # Market info patterns
        self.market_info_patterns = [
            r"(?:what.s|whats|where.s|where\s+is)\s+([A-Z]{1,5})\s+(?:trading|at|price)",
            r"(?:price|quote)\s+(?:of|for|on)\s+([A-Z]{1,5})",
            r"([A-Z]{1,5})\s+(?:price|quote|bid|ask)",
        ]
        
        # Symbol extraction pattern
        self.symbol_pattern = re.compile(r'\b([A-Z]{1,5})\b')
    
    def get_system_prompt(self) -> str:
        """System prompt for LLM-based classification (fallback)"""
        return """You are an intent classifier for a trading application. 
Classify the user's message into ONE of these intents:
- trade_execute: User wants to execute a trade (buy, sell, close position)
- trade_query: User is asking WHETHER they should trade (not actually executing)
- position_query: User wants to see their current positions
- analysis: User wants technical analysis on a stock
- scanner: User wants to see scanner alerts/setups
- coaching: User wants trading coaching or performance review
- market_info: User wants current price/quote information
- general_chat: General questions, greetings, other

Also extract any stock symbols mentioned (1-5 letter tickers).

Respond in JSON format:
{"intent": "intent_name", "symbols": ["SYM1", "SYM2"], "action": "buy/sell/close/null", "confidence": 0.0-1.0}"""
    
    async def process(self, input_data: Dict[str, Any]) -> AgentResponse:
        """
        Classify intent from user message.
        Uses pattern matching first, LLM fallback for ambiguous cases.
        """
        start = time.time()
        message = input_data.get("message", "").strip()
        context = input_data.get("context", {})
        
        if not message:
            return self._create_response(
                success=False,
                content=None,
                latency_ms=0,
                error="Empty message"
            )
        
        # Try pattern matching first (fast)
        result = self._pattern_match(message, context)
        
        if result and result.confidence >= 0.8:
            # High confidence from pattern matching
            logger.debug(f"Pattern matched: {result.intent.value} (conf={result.confidence})")
            return self._create_response(
                success=True,
                content={
                    "intent": result.intent.value,
                    "symbols": result.symbols,
                    "action": result.action,
                    "confidence": result.confidence,
                    "method": "pattern"
                },
                latency_ms=(time.time() - start) * 1000,
                model_used="pattern_matching"
            )
        
        # Fall back to LLM for ambiguous cases
        llm_result = await self._llm_classify(message)
        
        if llm_result:
            return self._create_response(
                success=True,
                content={
                    "intent": llm_result.intent.value,
                    "symbols": llm_result.symbols,
                    "action": llm_result.action,
                    "confidence": llm_result.confidence,
                    "method": "llm"
                },
                latency_ms=(time.time() - start) * 1000,
                model_used=self.default_model
            )
        
        # Default to general chat
        return self._create_response(
            success=True,
            content={
                "intent": Intent.GENERAL_CHAT.value,
                "symbols": self._extract_symbols(message),
                "action": None,
                "confidence": 0.5,
                "method": "default"
            },
            latency_ms=(time.time() - start) * 1000,
            model_used="default"
        )
    
    def _pattern_match(self, message: str, context: Dict = None) -> Optional[RoutingResult]:
        """Fast pattern-based intent classification"""
        message_lower = message.lower().strip()
        
        # Check for confirmation responses (context-dependent)
        if context and context.get("awaiting_confirmation"):
            confirm_patterns = ["yes", "yeah", "yep", "confirm", "do it", "execute", "go ahead", "ok", "okay"]
            if any(message_lower.startswith(p) for p in confirm_patterns):
                # This is a confirmation of previous intent
                prev_intent = context.get("previous_intent")
                if prev_intent == "trade_execute":
                    return RoutingResult(
                        intent=Intent.TRADE_EXECUTE,
                        confidence=0.95,
                        symbols=context.get("symbols", []),
                        action=context.get("action", "close"),
                        metadata={"confirmed": True}
                    )
        
        # Check trade execution patterns (high priority)
        for pattern in self.trade_execute_patterns:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                groups = match.groups()
                action = groups[0] if groups else None
                symbol = groups[1].upper() if len(groups) > 1 else None
                symbols = [symbol] if symbol else self._extract_symbols(message)
                
                return RoutingResult(
                    intent=Intent.TRADE_EXECUTE,
                    confidence=0.9,
                    symbols=symbols,
                    action=action
                )
        
        # Check position query patterns
        for pattern in self.position_patterns:
            if re.search(pattern, message_lower):
                return RoutingResult(
                    intent=Intent.POSITION_QUERY,
                    confidence=0.9,
                    symbols=self._extract_symbols(message)
                )
        
        # Check analysis patterns
        for pattern in self.analysis_patterns:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                # Always extract all symbols from the full message
                symbols = self._extract_symbols(message)
                
                return RoutingResult(
                    intent=Intent.ANALYSIS,
                    confidence=0.85,
                    symbols=symbols
                )
        
        # Check scanner patterns
        for pattern in self.scanner_patterns:
            if re.search(pattern, message_lower):
                return RoutingResult(
                    intent=Intent.SCANNER,
                    confidence=0.85,
                    symbols=[]
                )
        
        # Check coaching patterns
        for pattern in self.coaching_patterns:
            if re.search(pattern, message_lower):
                return RoutingResult(
                    intent=Intent.COACHING,
                    confidence=0.85,
                    symbols=self._extract_symbols(message)
                )
        
        # Check market info patterns
        for pattern in self.market_info_patterns:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                groups = match.groups()
                symbol = groups[0].upper() if groups else None
                symbols = [symbol] if symbol else self._extract_symbols(message)
                
                return RoutingResult(
                    intent=Intent.MARKET_INFO,
                    confidence=0.85,
                    symbols=symbols
                )
        
        # No strong pattern match
        # But if there are 2+ symbols mentioned with opinion-like words, route to analysis
        symbols = self._extract_symbols(message)
        opinion_words = ["thoughts", "think", "opinion", "view", "take", "like", "about", "recommend", "suggest"]
        if len(symbols) >= 2 and any(word in message_lower for word in opinion_words):
            return RoutingResult(
                intent=Intent.ANALYSIS,
                confidence=0.75,
                symbols=symbols,
                metadata={"multi_symbol": True}
            )
        
        return None
    
    async def _llm_classify(self, message: str) -> Optional[RoutingResult]:
        """Use LLM to classify ambiguous messages"""
        
        prompt = f"""Classify this trading app message:
"{message}"

Respond ONLY with JSON, no other text:
{{"intent": "one_of_the_intents", "symbols": ["SYM"], "action": "buy/sell/close/null", "confidence": 0.0-1.0}}"""
        
        response = await self._call_llm(
            prompt=prompt,
            temperature=0.1,  # Low temperature for classification
            max_tokens=100
        )
        
        if not response.success:
            return None
        
        try:
            # Parse JSON response
            content = response.content.strip()
            # Handle potential markdown code blocks
            if "```" in content:
                content = content.split("```")[1].replace("json", "").strip()
            
            data = json.loads(content)
            
            intent_str = data.get("intent", "general_chat")
            try:
                intent = Intent(intent_str)
            except ValueError:
                intent = Intent.GENERAL_CHAT
            
            return RoutingResult(
                intent=intent,
                confidence=data.get("confidence", 0.7),
                symbols=data.get("symbols", []),
                action=data.get("action")
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse LLM classification: {e}")
            return None
    
    def _extract_symbols(self, message: str) -> List[str]:
        """Extract potential stock symbols from message"""
        # Find all 1-5 letter uppercase words
        potential = self.symbol_pattern.findall(message.upper())
        
        # Filter out common words
        common_words = {"I", "A", "AN", "THE", "IS", "IT", "MY", "ME", "TO", "IN", "ON", 
                       "AT", "FOR", "AND", "OR", "NOT", "YES", "NO", "HOW", "WHAT",
                       "WHEN", "WHERE", "WHY", "CAN", "DO", "DOES", "AM", "ARE", "WAS",
                       "WILL", "WOULD", "SHOULD", "COULD", "MAY", "MIGHT", "MUST",
                       "PLS", "PLZ", "ASAP", "FYI", "IMO", "TBH", "BTW", "ATM",
                       "YOUR", "YOU", "RIGHT", "NOW", "LIKE", "JUST", "THINK", "GOOD",
                       "BAD", "UP", "DOWN", "BUY", "SELL", "TRADE", "LONG", "SHORT",
                       "IF", "SO", "BE", "AS", "BY", "HAS", "HAD", "HAVE", "BEEN",
                       "ALL", "ANY", "OUT", "GET", "GOT", "SET", "LET", "PUT"}
        
        symbols = [s for s in potential if s not in common_words and len(s) >= 2]
        
        return symbols[:5]  # Max 5 symbols
    
    def route_to_agent(self, intent: Intent) -> AgentType:
        """Map intent to the appropriate agent type"""
        mapping = {
            Intent.TRADE_EXECUTE: AgentType.TRADE_EXECUTOR,
            Intent.TRADE_QUERY: AgentType.COACH,  # Coach advises on trade decisions
            Intent.POSITION_QUERY: AgentType.COACH,  # Coach handles position info
            Intent.ANALYSIS: AgentType.ANALYST,
            Intent.SCANNER: AgentType.ANALYST,
            Intent.COACHING: AgentType.COACH,
            Intent.MARKET_INFO: AgentType.COACH,  # Coach handles general market overview
            Intent.GENERAL_CHAT: AgentType.CHAT,
        }
        return mapping.get(intent, AgentType.CHAT)
