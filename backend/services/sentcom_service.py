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
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
    """
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._chat_history: List[Dict] = []
        self._max_history = 50
        self._message_counter = 0
        logger.info("SentCom service initialized")
    
    def inject_services(self, services: Dict[str, Any]):
        """Inject required services"""
        self._services = services
        logger.info(f"SentCom services injected: {list(services.keys())}")
    
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
                    
                    # Add scanning status
                    mode = bot_status.get("mode", "confirmation")
                    running = bot_status.get("running", False)
                    if running:
                        scan_thought = f"We're actively scanning for opportunities in {mode} mode."
                        messages.append(SentComMessage(
                            id=self._generate_message_id(),
                            type="thought",
                            content=scan_thought,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            confidence=50,
                            action_type="scanning",
                            metadata={"source": "trading_bot", "mode": mode}
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
            # Process through orchestrator
            result = await orchestrator.process(message, session_id)
            
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
            
            self._chat_history.append(user_msg)
            self._chat_history.append(assistant_msg)
            
            # Trim history
            if len(self._chat_history) > self._max_history:
                self._chat_history = self._chat_history[-self._max_history:]
            
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
                bot_status = trading_bot.get_status()
                if isinstance(bot_status, dict):
                    open_trades = bot_status.get("open_trades", [])
                    if isinstance(open_trades, list):
                        for trade in open_trades:
                            symbol = trade.get("symbol")
                            if symbol:
                                seen_symbols.add(symbol)
                            
                            entry = trade.get("fill_price") or trade.get("entry_price", 0)
                            current = trade.get("current_price", entry)
                            shares = trade.get("shares") or trade.get("quantity", 0)
                            
                            pnl = (current - entry) * shares if entry and current else 0
                            pnl_pct = ((current - entry) / entry * 100) if entry else 0
                            
                            positions.append({
                                "symbol": symbol,
                                "shares": shares,
                                "entry_price": entry,
                                "current_price": current,
                                "pnl": round(pnl, 2),
                                "pnl_percent": round(pnl_pct, 2),
                                "stop_price": trade.get("stop_price"),
                                "target_prices": trade.get("target_prices", []),
                                "status": trade.get("status", "open"),
                                "entry_time": trade.get("entry_time"),
                                "source": "bot"
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
        """Get setups we're currently watching"""
        trading_bot = self._get_trading_bot()
        
        if not trading_bot:
            return []
        
        try:
            bot_status = trading_bot.get_status()
            watching = bot_status.get("watching_setups", [])
            
            setups = []
            for setup in watching:
                setups.append({
                    "symbol": setup.get("symbol"),
                    "setup_type": setup.get("setup_type"),
                    "trigger_price": setup.get("trigger_price"),
                    "current_price": setup.get("current_price"),
                    "risk_reward": setup.get("risk_reward"),
                    "confidence": setup.get("confidence"),
                    "timestamp": setup.get("timestamp")
                })
            
            return setups
            
        except Exception as e:
            logger.error(f"Error getting setups: {e}")
            return []
    
    async def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent alerts and notifications"""
        # TODO: Wire to alert system
        # For now, generate from positions and setups
        alerts = []
        
        positions = await self.get_our_positions()
        for pos in positions[:3]:
            pnl_pct = pos.get("pnl_percent", 0)
            symbol = pos.get("symbol")
            
            if pnl_pct <= -2:
                alerts.append({
                    "type": "warning",
                    "symbol": symbol,
                    "message": f"{symbol} approaching stop",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            elif pnl_pct >= 3:
                alerts.append({
                    "type": "info",
                    "symbol": symbol,
                    "message": f"{symbol} running +{pnl_pct:.1f}%",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
        
        return alerts[:limit]


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
