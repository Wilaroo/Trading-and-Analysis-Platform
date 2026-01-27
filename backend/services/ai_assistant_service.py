"""
AI Assistant Service
Portable LLM-powered trading assistant that uses learned knowledge
to provide analysis, suggestions, and trading guidance.

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
    SYSTEM_PROMPT = """You are an expert trading assistant with deep knowledge of stock markets, technical analysis, and trading strategies. You have access to a comprehensive knowledge base of trading strategies, rules, and patterns that your user has taught you.

Your personality:
- ANALYTICAL: Always explain your reasoning step-by-step
- PROTECTIVE: Enforce trading rules and warn about violations
- EDUCATIONAL: Help the user understand why, not just what
- HONEST: If you're uncertain, say so. Never fabricate data.

Your core responsibilities:
1. TRADE ANALYSIS: Evaluate trade ideas against learned strategies and rules
2. RULE ENFORCEMENT: Remind user of their trading rules, warn when they're about to violate them
3. PATTERN DETECTION: Notice trends in user's trading behavior and suggest improvements
4. MARKET INTELLIGENCE: Provide context-aware analysis using real market data
5. STRATEGY MATCHING: Connect current setups to relevant learned strategies

When analyzing a trade, always consider:
- Does this match any learned strategies?
- What trading rules apply?
- What's the quality score of this stock?
- What's the risk/reward?
- What could go wrong?

Format your responses clearly with sections when appropriate. Use specific numbers and levels. Be concise but thorough."""

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
        
    def _init_llm_clients(self):
        """Initialize available LLM clients"""
        self.llm_clients = {}
        
        # Emergent (via emergentintegrations)
        try:
            emergent_key = os.environ.get("EMERGENT_LLM_KEY")
            if emergent_key:
                from emergentintegrations.llm.chat import Chat
                self.llm_clients[LLMProvider.EMERGENT] = {
                    "available": True,
                    "client": Chat,
                    "key": emergent_key
                }
                logger.info("Emergent LLM client initialized")
        except ImportError:
            logger.warning("emergentintegrations not installed")
        
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
        
        # 1. Get relevant strategies from knowledge base
        try:
            relevant = self.knowledge_service.search(user_message, limit=5)
            if relevant:
                context_parts.append("RELEVANT KNOWLEDGE FROM YOUR TRAINING:")
                for item in relevant[:5]:
                    context_parts.append(f"- [{item.get('type', 'note').upper()}] {item.get('title', '')}: {item.get('content', '')[:200]}")
        except Exception as e:
            logger.warning(f"Error fetching knowledge: {e}")
        
        # 2. Get trading rules
        try:
            rules = self.knowledge_service.get_by_type("rule")
            if rules:
                context_parts.append("\nUSER'S TRADING RULES:")
                for rule in rules[:10]:
                    context_parts.append(f"- {rule.get('title', '')}: {rule.get('content', '')[:150]}")
        except Exception as e:
            logger.warning(f"Error fetching rules: {e}")
        
        # 3. Extract stock symbols from message and get data
        import re
        symbols = re.findall(r'\b([A-Z]{1,5})\b', user_message.upper())
        common_words = {'I', 'A', 'THE', 'AND', 'OR', 'FOR', 'TO', 'IS', 'IT', 'IN', 'ON', 'AT', 'BY', 'BE', 'AS', 'AN', 'ARE', 'WAS', 'IF', 'MY', 'ME', 'DO', 'SO', 'UP', 'AM', 'CAN', 'HOW', 'WHAT', 'BUY', 'SELL', 'LONG', 'SHORT'}
        symbols = [s for s in symbols if s not in common_words and len(s) >= 2]
        
        if symbols:
            context_parts.append(f"\nSTOCK DATA FOR MENTIONED SYMBOLS:")
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
                except Exception as e:
                    logger.warning(f"Error getting data for {symbol}: {e}")
        
        # 4. Knowledge base stats
        try:
            stats = self.knowledge_service.get_stats()
            context_parts.append(f"\nKNOWLEDGE BASE: {stats.get('total_entries', 0)} entries ({stats.get('by_type', {}).get('strategy', 0)} strategies, {stats.get('by_type', {}).get('rule', 0)} rules)")
        except Exception as e:
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
                from emergentintegrations.llm.chat import Chat
                
                chat = Chat(
                    api_key=self.llm_clients[LLMProvider.EMERGENT]["key"],
                    model="gpt-4o"
                )
                
                # Add messages to chat
                for msg in full_messages:
                    if msg["role"] == "system":
                        chat.add_message("system", msg["content"])
                    elif msg["role"] == "user":
                        chat.add_message("user", msg["content"])
                    elif msg["role"] == "assistant":
                        chat.add_message("assistant", msg["content"])
                
                response = chat.generate()
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
