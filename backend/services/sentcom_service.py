"""
SentCom Service - Sentient Command
Unified AI command center that orchestrates all trading intelligence.

Uses "we" voice throughout - the human trader and AI working as a team.
Combines:
- Bot thoughts (execution reasoning)
- AI assistant chat
- Proactive alerts
- Filter decisions
- Market context

Phase 2: Backend Wiring for Team Brain → SentCom
"""
import logging
import asyncio
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pymongo import MongoClient, DESCENDING

logger = logging.getLogger(__name__)

# MongoDB connection for chat persistence
_db = None

def _get_db():
    """Get MongoDB database connection for SentCom persistence"""
    global _db
    if _db is None:
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "tradecommand")
        client = MongoClient(mongo_url)
        _db = client[db_name]
    return _db


@dataclass
class SentComMessage:
    """A message in the SentCom stream"""
    id: str
    type: str  # 'thought', 'chat', 'alert', 'filter', 'system'
    content: str
    timestamp: str
    confidence: Optional[int] = None
    symbol: Optional[str] = None
    action_type: Optional[str] = None  # 'watching', 'monitoring', 'scanning', 'alert', etc.
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "symbol": self.symbol,
            "action_type": self.action_type,
            "metadata": self.metadata
        }


@dataclass  
class SentComStatus:
    """Current SentCom operational status"""
    connected: bool
    state: str  # 'active', 'watching', 'paused', 'offline'
    regime: Optional[str] = None
    positions_count: int = 0
    watching_count: int = 0
    pending_orders: int = 0
    executing_orders: int = 0
    filled_orders: int = 0
    last_activity: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "connected": self.connected,
            "state": self.state,
            "regime": self.regime,
            "positions_count": self.positions_count,
            "watching_count": self.watching_count,
            "order_pipeline": {
                "pending": self.pending_orders,
                "executing": self.executing_orders,
                "filled": self.filled_orders
            },
            "last_activity": self.last_activity
        }


class SentComService:
    """
    SentCom - Sentient Command
    
    The unified AI command center that speaks with "we" voice.
    Orchestrates all trading intelligence and provides a single
    stream of consciousness for the trading team (human + AI).
    
    Persistence: Chat history and settings are stored in MongoDB.
    """
    
    CHAT_COLLECTION = "sentcom_chat_history"
    SETTINGS_COLLECTION = "sentcom_settings"
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._chat_history: List[Dict] = []
        self._max_history = 50
        self._message_counter = 0
        self._session_id = "default"
        
        # Load persisted chat history from MongoDB
        self._load_chat_history()
        logger.info(f"SentCom service initialized with {len(self._chat_history)} persisted messages")
    
    def _load_chat_history(self):
        """Load chat history from MongoDB"""
        try:
            db = _get_db()
            # Get the most recent messages for the session
            cursor = db[self.CHAT_COLLECTION].find(
                {"session_id": self._session_id}
            ).sort("timestamp", DESCENDING).limit(self._max_history)
            
            messages = list(cursor)
            # Reverse to get chronological order
            messages.reverse()
            
            self._chat_history = []
            for msg in messages:
                self._chat_history.append({
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "timestamp": msg.get("timestamp")
                })
            
            logger.info(f"Loaded {len(self._chat_history)} chat messages from MongoDB")
        except Exception as e:
            logger.error(f"Error loading chat history: {e}")
            self._chat_history = []
    
    def _save_chat_message(self, role: str, content: str, timestamp: str):
        """Save a chat message to MongoDB"""
        try:
            db = _get_db()
            db[self.CHAT_COLLECTION].insert_one({
                "session_id": self._session_id,
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "created_at": datetime.now(timezone.utc)
            })
        except Exception as e:
            logger.error(f"Error saving chat message: {e}")
    
    def _cleanup_old_messages(self):
        """Remove old messages beyond max_history from MongoDB"""
        try:
            db = _get_db()
            # Count messages
            count = db[self.CHAT_COLLECTION].count_documents({"session_id": self._session_id})
            
            if count > self._max_history * 2:  # Clean up when we have 2x max
                # Get IDs of messages to keep (most recent max_history)
                keep_cursor = db[self.CHAT_COLLECTION].find(
                    {"session_id": self._session_id},
                    {"_id": 1}
                ).sort("timestamp", DESCENDING).limit(self._max_history)
                
                keep_ids = [doc["_id"] for doc in keep_cursor]
                
                # Delete older messages
                result = db[self.CHAT_COLLECTION].delete_many({
                    "session_id": self._session_id,
                    "_id": {"$nin": keep_ids}
                })
                logger.info(f"Cleaned up {result.deleted_count} old chat messages")
        except Exception as e:
            logger.error(f"Error cleaning up old messages: {e}")
    
    def inject_services(self, services: Dict[str, Any]):
        """Inject required services"""
        self._services = services
        logger.info(f"SentCom services injected: {list(services.keys())}")
    
    def inject_learning_services(self, learning_loop=None, learning_context_provider=None):
        """Late injection of learning services (called after learning services are initialized)"""
        if learning_loop:
            self._services["learning_loop"] = learning_loop
            logger.info("SentCom: Learning loop service injected")
        if learning_context_provider:
            self._services["learning_context_provider"] = learning_context_provider
            logger.info("SentCom: Learning context provider injected")
    
    def _generate_message_id(self) -> str:
        """Generate unique message ID"""
        self._message_counter += 1
        return f"sentcom_{int(datetime.now(timezone.utc).timestamp())}_{self._message_counter}"
    
    def _get_trading_bot(self):
        """Get trading bot service"""
        return self._services.get("trading_bot")
    
    def _get_orchestrator(self):
        """Get agent orchestrator"""
        return self._services.get("orchestrator")
    
    def _get_ib_service(self):
        """Get IB service for market data"""
        return self._services.get("ib_service")
    
    def _get_regime_engine(self):
        """Get market regime engine"""
        return self._services.get("regime_engine")
    
    def _get_learning_loop(self):
        """Get learning loop service"""
        return self._services.get("learning_loop")
    
    def _get_learning_context(self):
        """Get learning context provider"""
        return self._services.get("learning_context_provider")
    
    async def get_status(self) -> SentComStatus:
        """Get current SentCom operational status"""
        trading_bot = self._get_trading_bot()
        regime_engine = self._get_regime_engine()
        
        # Determine connection status from pushed IB data
        connected = False
        try:
            from routers.ib import _pushed_ib_data
            connected = _pushed_ib_data.get("connected", False)
        except:
            pass
        
        # Get bot state
        state = "offline"
        positions_count = 0
        watching_count = 0
        pending = 0
        executing = 0
        filled = 0
        
        if trading_bot:
            try:
                bot_status = trading_bot.get_status()
                if isinstance(bot_status, dict):
                    state = bot_status.get("state", "offline")
                    if bot_status.get("running"):
                        state = "active"
                    
                    # Get position counts from bot
                    open_trades = bot_status.get("open_trades", [])
                    if isinstance(open_trades, list):
                        positions_count = len(open_trades)
                    
                    watching_setups = bot_status.get("watching_setups", [])
                    if isinstance(watching_setups, list):
                        watching_count = len(watching_setups)
            except Exception as e:
                logger.error(f"Error getting bot status: {e}")
        
        # Also count IB positions if more than bot positions
        try:
            from routers.ib import _pushed_ib_data
            ib_positions = _pushed_ib_data.get("positions", [])
            if len(ib_positions) > positions_count:
                positions_count = len(ib_positions)
        except:
            pass
        
        # Get order pipeline
        try:
            order_queue = self._services.get("order_queue")
            if order_queue:
                queue_status = order_queue.get_queue_status()
                if isinstance(queue_status, dict):
                    pending = queue_status.get("pending_count", 0)
                    executing = queue_status.get("executing_count", 0)
                    filled = queue_status.get("filled_today", 0)
        except Exception as e:
            logger.error(f"Error getting order queue status: {e}")
        
        # Get market regime
        regime = None
        if regime_engine:
            try:
                regime_data = await regime_engine.get_current_regime()
                regime = regime_data.get("regime", "UNKNOWN")
            except:
                regime = "UNKNOWN"
        
        return SentComStatus(
            connected=connected,
            state=state,
            regime=regime,
            positions_count=positions_count,
            watching_count=watching_count,
            pending_orders=pending,
            executing_orders=executing,
            filled_orders=filled,
            last_activity=datetime.now(timezone.utc).isoformat()
        )
    
    async def get_unified_stream(self, limit: int = 20) -> List[SentComMessage]:
        """
        Get unified stream of SentCom messages.
        Combines bot thoughts, chat history, alerts, and filter decisions.
        All in "we" voice.
        """
        messages: List[SentComMessage] = []
        trading_bot = self._get_trading_bot()
        
        # 1. Get bot thoughts and position updates
        if trading_bot:
            try:
                bot_status = trading_bot.get_status()
                
                if isinstance(bot_status, dict):
                    # Generate thoughts from open trades
                    open_trades = bot_status.get("open_trades", [])
                    if isinstance(open_trades, list):
                        for trade in open_trades[:3]:
                            symbol = trade.get("symbol")
                            pnl_pct = trade.get("pnl_percent", 0)
                            status = trade.get("status", "open")
                            stop = trade.get("stop_price")
                            target = trade.get("target_prices", [None])[0] if trade.get("target_prices") else None
                            
                            thought_text = f"We're monitoring our {symbol} position. "
                            if pnl_pct > 0:
                                thought_text += f"Currently up {pnl_pct:.1f}%. "
                            elif pnl_pct < 0:
                                thought_text += f"Currently down {abs(pnl_pct):.1f}%. "
                            
                            if stop:
                                thought_text += f"Our stop at ${stop:.2f} is in place. "
                            if target:
                                thought_text += f"Target at ${target:.2f}."
                            
                            messages.append(SentComMessage(
                                id=self._generate_message_id(),
                                type="thought",
                                content=thought_text.strip(),
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                confidence=60,
                                symbol=symbol,
                                action_type="monitoring",
                                metadata={"source": "trading_bot", "pnl_percent": pnl_pct}
                            ))
                    
                    # Add scanning status with more context
                    mode = bot_status.get("mode", "confirmation")
                    running = bot_status.get("running", False)
                    if running:
                        # Check if we have real market data
                        has_market_data = False
                        scanner_status = ""
                        try:
                            from services.enhanced_scanner import get_enhanced_scanner
                            scanner = get_enhanced_scanner()
                            if scanner:
                                active_alerts = scanner.get_live_alerts() if hasattr(scanner, 'get_live_alerts') else []
                                scan_count = scanner._scan_count if hasattr(scanner, '_scan_count') else 0
                                has_market_data = scan_count > 0 and len(active_alerts) > 0
                                if has_market_data:
                                    scanner_status = f"Found {len(active_alerts)} potential setups."
                                elif scan_count > 0:
                                    scanner_status = "No setups meeting our criteria right now."
                        except Exception:
                            pass
                        
                        if has_market_data:
                            scan_thought = f"We're actively scanning for opportunities in {mode} mode. {scanner_status}"
                        else:
                            scan_thought = f"We're actively scanning for opportunities in {mode} mode."
                        
                        messages.append(SentComMessage(
                            id=self._generate_message_id(),
                            type="thought",
                            content=scan_thought,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            confidence=50,
                            action_type="scanning",
                            metadata={"source": "trading_bot", "mode": mode, "has_live_data": has_market_data}
                        ))
                
                # Get filter thoughts (smart strategy filtering)
                try:
                    filter_thoughts = trading_bot.get_filter_thoughts(limit=5)
                    for ft in filter_thoughts:
                        messages.append(SentComMessage(
                            id=self._generate_message_id(),
                            type="filter",
                            content=self._ensure_we_voice(ft.get("text", ft.get("reasoning", ""))),
                            timestamp=ft.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            confidence=ft.get("confidence"),
                            symbol=ft.get("symbol"),
                            action_type=ft.get("decision", "filter"),
                            metadata={
                                "source": "smart_filter",
                                "decision": ft.get("decision"),
                                "win_rate": ft.get("win_rate"),
                                "setup_type": ft.get("setup_type")
                            }
                        ))
                except Exception as e:
                    logger.debug(f"No filter thoughts: {e}")
                
            except Exception as e:
                logger.error(f"Error getting bot thoughts: {e}")
        
        # 2. Add IB position summaries
        try:
            from routers.ib import _pushed_ib_data
            ib_positions = _pushed_ib_data.get("positions", [])
            if ib_positions:
                # Generate a summary thought about IB positions
                pos_count = len(ib_positions)
                total_unrealized = sum(p.get("unrealizedPNL", p.get("unrealizedPnL", 0)) for p in ib_positions)
                
                summary_text = f"We're monitoring {pos_count} active positions"
                if total_unrealized > 0:
                    summary_text += f", currently up ${total_unrealized:,.2f}"
                elif total_unrealized < 0:
                    summary_text += f", currently down ${abs(total_unrealized):,.2f}"
                summary_text += " and scanning for setups."
                
                messages.append(SentComMessage(
                    id=self._generate_message_id(),
                    type="system",
                    content=summary_text,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    confidence=50,
                    action_type="status",
                    metadata={"source": "ib_positions", "position_count": pos_count}
                ))
        except Exception as e:
            logger.debug(f"No IB positions for stream: {e}")
        
        # 3. Add chat history
        for chat in self._chat_history[-10:]:
            messages.append(SentComMessage(
                id=chat.get("id", self._generate_message_id()),
                type="chat",
                content=chat.get("content", ""),
                timestamp=chat.get("timestamp", datetime.now(timezone.utc).isoformat()),
                confidence=chat.get("confidence"),
                symbol=chat.get("symbol"),
                action_type="chat_response",
                metadata={"source": "sentcom_chat", "role": chat.get("role", "assistant")}
            ))
        
        # 4. Generate system status message if no activity
        if len(messages) == 0:
            status = await self.get_status()
            state_message = self._generate_state_message(status)
            messages.append(SentComMessage(
                id=self._generate_message_id(),
                type="system",
                content=state_message,
                timestamp=datetime.now(timezone.utc).isoformat(),
                confidence=50,
                action_type="status",
                metadata={"source": "sentcom_system"}
            ))
        
        # Sort by timestamp (newest first) and limit
        messages.sort(key=lambda m: m.timestamp, reverse=True)
        return messages[:limit]
    
    def _generate_state_message(self, status: SentComStatus) -> str:
        """Generate a status message in 'we' voice"""
        if not status.connected:
            return "We're currently offline. Waiting for market connection to resume monitoring."
        
        if status.state == "paused":
            return "We're on standby. Ready to resume when you give the signal."
        
        if status.positions_count > 0:
            regime_note = f" Market regime is {status.regime}." if status.regime else ""
            return f"We're monitoring {status.positions_count} active position{'s' if status.positions_count > 1 else ''} and scanning for setups.{regime_note}"
        
        if status.watching_count > 0:
            return f"We're watching {status.watching_count} potential setup{'s' if status.watching_count > 1 else ''}. Waiting for entry triggers to confirm."
        
        regime_note = ""
        if status.regime:
            if status.regime == "RISK_ON":
                regime_note = " Market regime is RISK_ON - conditions favor momentum plays."
            elif status.regime == "RISK_OFF":
                regime_note = " Market regime is RISK_OFF - we're being selective."
            else:
                regime_note = f" Market regime is {status.regime}."
        
        return f"We're monitoring market conditions and scanning for setups that match our criteria. Looking for high R:R opportunities with clear entry triggers.{regime_note}"
    
    def _ensure_we_voice(self, text: str) -> str:
        """Convert any 'I' language to 'we' language"""
        if not text:
            return text
        
        # Common replacements
        replacements = [
            ("I'm ", "We're "),
            ("I am ", "We are "),
            ("I have ", "We have "),
            ("I've ", "We've "),
            ("I detected ", "We detected "),
            ("I found ", "We found "),
            ("I recommend ", "We recommend "),
            ("I suggest ", "We suggest "),
            ("I think ", "We think "),
            ("I see ", "We see "),
            ("I noticed ", "We noticed "),
            ("I'll ", "We'll "),
            ("I will ", "We will "),
            ("my ", "our "),
            ("My ", "Our "),
            (" me ", " us "),
            (" me.", " us."),
            ("you're ", "we're "),
            ("You're ", "We're "),
            ("your ", "our "),
            ("Your ", "Our "),
            ("you ", "we "),
            ("You ", "We "),
        ]
        
        result = text
        for old, new in replacements:
            result = result.replace(old, new)
        
        return result
    
    async def chat(self, message: str, session_id: str = "default") -> Dict[str, Any]:
        """
        Process a chat message through SentCom.
        Routes to the appropriate agent and returns unified response.
        Now includes conversation history for better context.
        """
        orchestrator = self._get_orchestrator()
        
        if not orchestrator:
            # Fallback response
            return {
                "success": False,
                "response": "We're having trouble processing that right now. Our AI systems are initializing.",
                "source": "sentcom_fallback"
            }
        
        try:
            # Format recent chat history for the orchestrator
            recent_history = []
            for chat_msg in self._chat_history[-10:]:
                recent_history.append({
                    "role": chat_msg.get("role", "user"),
                    "content": chat_msg.get("content", ""),
                    "timestamp": chat_msg.get("timestamp")
                })
            
            # Process through orchestrator with conversation history
            result = await orchestrator.process(
                message=message, 
                session_id=session_id,
                chat_history=recent_history
            )
            
            # Ensure response uses "we" voice
            response_text = self._ensure_we_voice(result.response)
            
            # Store in chat history
            user_msg = {
                "id": self._generate_message_id(),
                "role": "user",
                "content": message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            assistant_msg = {
                "id": self._generate_message_id(),
                "role": "assistant",
                "content": response_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": result.metadata.get("confidence") if result.metadata else None,
                "symbol": result.metadata.get("symbol") if result.metadata else None
            }
            
            # Add to in-memory history
            self._chat_history.append(user_msg)
            self._chat_history.append(assistant_msg)
            
            # Persist to MongoDB
            self._save_chat_message("user", message, user_msg["timestamp"])
            self._save_chat_message("assistant", response_text, assistant_msg["timestamp"])
            
            # Trim in-memory history
            if len(self._chat_history) > self._max_history:
                self._chat_history = self._chat_history[-self._max_history:]
            
            # Periodically clean up old DB messages
            self._cleanup_old_messages()
            
            return {
                "success": result.success,
                "response": response_text,
                "agent_used": result.agent_used,
                "intent": result.intent,
                "latency_ms": result.total_latency_ms,
                "requires_confirmation": result.requires_confirmation,
                "pending_trade": result.pending_trade,
                "source": "sentcom"
            }
            
        except Exception as e:
            logger.error(f"SentCom chat error: {e}")
            # Provide a friendly error message
            error_response = "We're having trouble with that query right now."
            if "connection" in str(e).lower() or "offline" in str(e).lower():
                error_response = "We're currently offline and can't access market data. Once we're connected, we'll be able to help with that."
            elif "NoneType" in str(e) or "not found" in str(e).lower():
                error_response = "We're still initializing our systems. Give us a moment and try again."
            else:
                error_response = f"We ran into an issue processing that. Let's try again in a moment."
            
            return {
                "success": False,
                "response": error_response,
                "source": "sentcom_error"
            }
    
    async def get_market_context(self) -> Dict[str, Any]:
        """Get current market context for SentCom display"""
        regime_engine = self._get_regime_engine()
        ib_service = self._get_ib_service()
        
        context = {
            "regime": "UNKNOWN",
            "spy_trend": None,
            "vix": None,
            "sector_flow": None,
            "market_open": False
        }
        
        # Get regime
        if regime_engine:
            try:
                regime_data = await regime_engine.get_current_regime()
                context["regime"] = regime_data.get("regime", "UNKNOWN")
                context["spy_trend"] = regime_data.get("spy_trend")
                context["vix"] = regime_data.get("vix")
            except Exception as e:
                logger.error(f"Error getting regime: {e}")
        
        # Check if market is open
        now = datetime.now(timezone.utc)
        # Simple check - market hours are roughly 14:30 - 21:00 UTC (9:30 AM - 4:00 PM ET)
        if now.weekday() < 5:  # Monday-Friday
            if 14 <= now.hour < 21:
                context["market_open"] = True
        
        return context
    
    async def get_our_positions(self) -> List[Dict[str, Any]]:
        """Get our current positions with P&L from both Trading Bot and IB"""
        trading_bot = self._get_trading_bot()
        
        positions = []
        seen_symbols = set()
        
        # First, get bot-managed trades (these have more detailed tracking)
        if trading_bot:
            try:
                # Get open trades directly from trading bot service
                open_trades = trading_bot.get_open_trades()
                if isinstance(open_trades, list):
                    for trade in open_trades:
                        symbol = trade.get("symbol")
                        if symbol:
                            seen_symbols.add(symbol)
                        
                        entry = trade.get("fill_price") or trade.get("entry_price", 0)
                        current = trade.get("current_price", entry)
                        shares = trade.get("shares") or trade.get("quantity", 0)
                        direction = trade.get("direction", "long")
                        
                        # Calculate P&L based on direction
                        if direction == "short":
                            pnl = (entry - current) * shares if entry and current else 0
                            pnl_pct = ((entry - current) / entry * 100) if entry else 0
                        else:
                            pnl = (current - entry) * shares if entry and current else 0
                            pnl_pct = ((current - entry) / entry * 100) if entry else 0
                        
                        positions.append({
                            "symbol": symbol,
                            "shares": shares,
                            "direction": direction,
                            "entry_price": entry,
                            "current_price": current,
                            "pnl": round(pnl, 2),
                            "pnl_percent": round(pnl_pct, 2),
                            "stop_price": trade.get("stop_price"),
                            "target_prices": trade.get("target_prices", []),
                            "status": trade.get("status", "open"),
                            "setup_type": trade.get("setup_type", "unknown"),
                            "entry_time": trade.get("executed_at"),
                            "trade_id": trade.get("id"),
                            "source": "bot",
                            "notes": trade.get("notes", "")
                        })
            except Exception as e:
                logger.error(f"Error getting bot positions: {e}")
        
        # Then, get IB positions from pushed data
        try:
            # Import the global dict directly
            from routers.ib import _pushed_ib_data
            ib_positions = _pushed_ib_data.get("positions", [])
            
            for pos in ib_positions:
                symbol = pos.get("symbol")
                if symbol and symbol not in seen_symbols:
                    shares = pos.get("position", 0)
                    avg_cost = pos.get("avgCost", 0)
                    market_price = pos.get("marketPrice", avg_cost)
                    unrealized_pnl = pos.get("unrealizedPnL", pos.get("unrealizedPNL", 0))
                    
                    # Calculate P&L percent
                    total_cost = abs(shares * avg_cost) if shares and avg_cost else 0
                    pnl_pct = (unrealized_pnl / total_cost * 100) if total_cost > 0 else 0
                    
                    # Determine if long or short
                    position_type = "long" if shares > 0 else "short"
                    
                    positions.append({
                        "symbol": symbol,
                        "shares": abs(shares),
                        "position_type": position_type,
                        "entry_price": avg_cost,
                        "current_price": market_price if market_price else avg_cost,
                        "pnl": round(unrealized_pnl, 2),
                        "pnl_percent": round(pnl_pct, 2),
                        "stop_price": None,
                        "target_prices": [],
                        "status": "ib_position",
                        "entry_time": None,
                        "source": "ib"
                    })
        except Exception as e:
            logger.error(f"Error getting IB positions: {e}")
        
        return positions
    
    async def get_setups_watching(self) -> List[Dict[str, Any]]:
        """
        Get setups we're currently watching.
        
        Sources:
        1. Live scanner alerts (PRIMARY - real-time alerts)
        2. Trading bot's watching_setups
        3. AI-generated setups from positions (potential adds/scales)
        """
        setups = []
        
        # Source 1: LIVE SCANNER ALERTS (Primary source)
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner:
                live_alerts = scanner.get_live_alerts()
                for alert in live_alerts[:6]:
                    # Handle timestamp - could be datetime or string
                    timestamp = alert.created_at
                    if hasattr(timestamp, 'isoformat'):
                        timestamp = timestamp.isoformat()
                    elif not timestamp:
                        timestamp = datetime.now(timezone.utc).isoformat()
                    
                    setups.append({
                        "symbol": alert.symbol,
                        "setup_type": alert.setup_type or alert.strategy_name,
                        "trigger_price": alert.trigger_price,
                        "current_price": alert.current_price,
                        "stop_price": alert.stop_loss,
                        "target_price": alert.target,
                        "risk_reward": f"{alert.risk_reward:.1f}:1" if alert.risk_reward else "2:1",
                        "confidence": int(alert.tqs_score) if alert.tqs_score else int(alert.trigger_probability * 100) if alert.trigger_probability else 60,
                        "grade": alert.tqs_grade or alert.trade_grade,
                        "priority": alert.priority.value if alert.priority else "medium",
                        "headline": alert.headline,
                        "timestamp": timestamp,
                        "source": "live_scanner",
                        "alert_id": alert.id
                    })
                    logger.info(f"Added scanner setup: {alert.symbol} - {alert.setup_type}")
        except Exception as e:
            logger.error(f"Error getting live scanner alerts: {e}")
        
        # Source 2: Trading bot watching list (if we don't have enough from scanner)
        if len(setups) < 4:
            trading_bot = self._get_trading_bot()
            if trading_bot:
                try:
                    bot_status = trading_bot.get_status()
                    watching = bot_status.get("watching_setups", [])
                    for setup in watching:
                        if setup.get("symbol") not in [s.get("symbol") for s in setups]:
                            setups.append({
                                "symbol": setup.get("symbol"),
                                "setup_type": setup.get("setup_type"),
                                "trigger_price": setup.get("trigger_price"),
                                "current_price": setup.get("current_price"),
                                "risk_reward": setup.get("risk_reward"),
                                "confidence": setup.get("confidence"),
                                "timestamp": setup.get("timestamp"),
                                "source": "bot"
                            })
                except Exception as e:
                    logger.error(f"Error getting bot setups: {e}")
        
        # Source 2: Generate setups from positions (scale opportunities)
        positions = await self.get_our_positions()
        for pos in positions:
            symbol = pos.get("symbol", "")
            pnl_pct = pos.get("pnl_percent", 0)
            entry_price = pos.get("entry_price", 0)
            current_price = pos.get("current_price", 0)
            
            if not symbol or not entry_price:
                continue
            
            # If position is winning, look for pullback entry
            if pnl_pct > 3 and current_price > 0:
                pullback_target = entry_price * 1.01  # 1% above entry
                setups.append({
                    "symbol": symbol,
                    "setup_type": "PULLBACK_ADD",
                    "trigger_price": round(pullback_target, 2),
                    "current_price": round(current_price, 2),
                    "risk_reward": "2:1",
                    "confidence": 65,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "position_analysis",
                    "note": f"Winner pulling back - scale opportunity"
                })
            
            # If position is near breakeven after being down, momentum setup
            elif -1 < pnl_pct < 1 and current_price > 0:
                breakout_target = current_price * 1.02  # 2% above current
                setups.append({
                    "symbol": symbol,
                    "setup_type": "BREAKOUT_ADD",
                    "trigger_price": round(breakout_target, 2),
                    "current_price": round(current_price, 2),
                    "risk_reward": "2.5:1",
                    "confidence": 55,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "position_analysis",
                    "note": f"Reclaiming - momentum add"
                })
        
        # Source 3: Check scanner service for recent alerts
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner:
                recent_alerts = scanner.get_recent_alerts(limit=5) if hasattr(scanner, 'get_recent_alerts') else []
                for alert in recent_alerts:
                    if alert.get("symbol") not in [s.get("symbol") for s in setups]:
                        setups.append({
                            "symbol": alert.get("symbol"),
                            "setup_type": alert.get("setup_type", alert.get("alert_type", "SCANNER")),
                            "trigger_price": alert.get("trigger_price", alert.get("price")),
                            "current_price": alert.get("current_price", alert.get("price")),
                            "risk_reward": alert.get("risk_reward", "2:1"),
                            "confidence": alert.get("score", alert.get("confidence", 60)),
                            "timestamp": alert.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "source": "scanner"
                        })
        except Exception as e:
            logger.debug(f"Scanner not available: {e}")
        
        # Limit to top 6 setups
        return setups[:6]
    
    async def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent alerts and notifications.
        
        Alert types:
        - stop_warning: Position approaching stop
        - runner: Position running strong
        - target_near: Position near target
        - new_setup: New scanner setup detected
        - regime_change: Market regime shifted
        """
        alerts = []
        
        # Source 1: LIVE SCANNER ALERTS
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner:
                live_alerts = scanner.get_live_alerts()
                for alert in live_alerts[:5]:
                    # Handle timestamp - could be datetime or string
                    timestamp = alert.created_at
                    if hasattr(timestamp, 'isoformat'):
                        timestamp = timestamp.isoformat()
                    elif not timestamp:
                        timestamp = datetime.now(timezone.utc).isoformat()
                    
                    alerts.append({
                        "id": alert.id,
                        "type": "new_setup",
                        "severity": alert.priority.value if alert.priority else "medium",
                        "symbol": alert.symbol,
                        "message": alert.headline or f"{alert.symbol} {alert.setup_type}",
                        "current_price": alert.current_price,
                        "trigger_price": alert.trigger_price,
                        "setup_type": alert.setup_type,
                        "grade": alert.tqs_grade or alert.trade_grade,
                        "risk_reward": alert.risk_reward,
                        "timestamp": timestamp,
                        "action_suggestion": f"Entry: ${alert.trigger_price:.2f} | Stop: ${alert.stop_loss:.2f}" if alert.trigger_price and alert.stop_loss else "Review setup"
                    })
        except Exception as e:
            logger.error(f"Error getting live scanner alerts: {e}")
        
        # Source 2: Generate alerts from positions
        positions = await self.get_our_positions()
        for pos in positions:
            pnl_pct = pos.get("pnl_percent", 0)
            symbol = pos.get("symbol", "")
            current_price = pos.get("current_price", 0)
            
            if not symbol:
                continue
            
            # Stop warning: -2% or worse
            if pnl_pct <= -2:
                alerts.append({
                    "id": f"alert_{symbol}_stop",
                    "type": "stop_warning",
                    "severity": "high" if pnl_pct <= -3 else "medium",
                    "symbol": symbol,
                    "message": f"{symbol} down {abs(pnl_pct):.1f}% - approaching stop",
                    "current_price": current_price,
                    "pnl_percent": pnl_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action_suggestion": "Review stop or cut"
                })
            
            # Runner alert: +3% or better
            elif pnl_pct >= 3:
                alerts.append({
                    "id": f"alert_{symbol}_runner",
                    "type": "runner",
                    "severity": "info",
                    "symbol": symbol,
                    "message": f"{symbol} running +{pnl_pct:.1f}%",
                    "current_price": current_price,
                    "pnl_percent": pnl_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action_suggestion": "Trail stop or take partials"
                })
            
            # Target near: +2% to +3%
            elif 2 <= pnl_pct < 3:
                alerts.append({
                    "id": f"alert_{symbol}_target",
                    "type": "target_near",
                    "severity": "info",
                    "symbol": symbol,
                    "message": f"{symbol} nearing target at +{pnl_pct:.1f}%",
                    "current_price": current_price,
                    "pnl_percent": pnl_pct,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action_suggestion": "Prepare to take profits"
                })
        
        # Sort by severity (high first) then timestamp
        severity_order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
        alerts.sort(key=lambda x: (severity_order.get(x.get("severity", "info"), 3), x.get("timestamp", "")), reverse=True)
        
        return alerts[:limit]
    
    async def get_learning_insights(self, symbol: str = None) -> Dict[str, Any]:
        """Get learning insights from the learning systems"""
        learning_loop = self._get_learning_loop()
        learning_context = self._get_learning_context()
        
        insights = {
            "available": False,
            "symbol_insights": None,
            "trader_profile": None,
            "recent_patterns": [],
            "strategy_performance": {},
            "recommendations": []
        }
        
        if not learning_loop and not learning_context:
            return insights
        
        insights["available"] = True
        
        try:
            # Get trader profile from learning context provider
            if learning_context:
                try:
                    context = learning_context.get_full_context()
                    insights["trader_profile"] = context.get("trader_profile")
                    insights["recent_patterns"] = context.get("recent_patterns", [])
                    insights["strategy_performance"] = context.get("strategy_stats", {})
                except Exception as e:
                    logger.error(f"Error getting learning context: {e}")
            
            # Get symbol-specific insights if symbol provided
            if symbol and learning_loop:
                try:
                    # Get trade history for this symbol
                    symbol_stats = learning_loop.get_symbol_stats(symbol) if hasattr(learning_loop, 'get_symbol_stats') else {}
                    insights["symbol_insights"] = {
                        "symbol": symbol,
                        "total_trades": symbol_stats.get("total_trades", 0),
                        "win_rate": symbol_stats.get("win_rate", 0),
                        "avg_pnl": symbol_stats.get("avg_pnl", 0),
                        "best_setups": symbol_stats.get("best_setups", []),
                        "notes": symbol_stats.get("notes", [])
                    }
                except Exception as e:
                    logger.error(f"Error getting symbol insights: {e}")
            
            # Generate recommendations based on learning data
            if insights["trader_profile"]:
                profile = insights["trader_profile"]
                if profile.get("common_mistakes"):
                    insights["recommendations"].append({
                        "type": "avoid",
                        "message": f"Watch for: {profile['common_mistakes'][0] if profile['common_mistakes'] else 'overtrading'}"
                    })
                if profile.get("best_timeframes"):
                    insights["recommendations"].append({
                        "type": "timing", 
                        "message": f"Best times: {', '.join(profile['best_timeframes'][:2])}"
                    })
        
        except Exception as e:
            logger.error(f"Error getting learning insights: {e}")
        
        return insights


# Singleton instance
_sentcom_service: Optional[SentComService] = None


def get_sentcom_service() -> SentComService:
    """Get or create SentCom service singleton"""
    global _sentcom_service
    if _sentcom_service is None:
        _sentcom_service = SentComService()
    return _sentcom_service


def init_sentcom_service(services: Dict[str, Any]) -> SentComService:
    """Initialize SentCom service with dependencies"""
    service = get_sentcom_service()
    service.inject_services(services)
    return service
