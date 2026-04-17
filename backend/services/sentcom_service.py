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
- Dynamic Risk Management

Phase 2: Backend Wiring for Team Brain → SentCom
"""
import logging
import asyncio
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
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
        self._session_id = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self._llm_cache: Dict[str, str] = {}  # Cache LLM-enriched descriptions per symbol+setup
        self._llm_cache_ttl: Dict[str, float] = {}  # Expiry timestamps
        
        # Load recent chat messages (current day only, for continuity)
        self._load_recent_chat_history()
        logger.info(f"SentCom session {self._session_id}: loaded {len(self._chat_history)} recent messages")
    
    def _load_recent_chat_history(self):
        """Load recent chat messages from MongoDB (last 24 hours, any session).
        
        On startup, shows the most recent conversation for continuity.
        All messages are still stored in MongoDB for AI learning.
        Note: This runs synchronously at init time only (one-time cost).
        """
        try:
            db = _get_db()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            
            cursor = db[self.CHAT_COLLECTION].find(
                {"created_at": {"$gte": cutoff}}
            ).sort("created_at", -1).limit(self._max_history)
            messages = list(cursor)
            messages.reverse()  # Chronological order
            
            self._chat_history = []
            for msg in messages:
                self._chat_history.append({
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "timestamp": msg.get("timestamp")
                })
            
            logger.info(f"Loaded {len(self._chat_history)} recent chat messages (last 24h)")
        except Exception as e:
            logger.error(f"Error loading chat history: {e}")
            self._chat_history = []

    async def _enrich_setup_with_llm(self, symbol: str, setup_type: str, raw_reasoning: str, direction: str = "") -> str:
        """
        Call LLM to transform raw indicator data into a human-readable trading narrative.
        Uses Ollama proxy (free, local) with cache to avoid redundant calls.
        Falls back to raw reasoning if LLM unavailable.
        """
        import time as _t
        cache_key = f"{symbol}_{setup_type}"
        
        # Check cache (5 min TTL)
        if cache_key in self._llm_cache:
            if _t.time() < self._llm_cache_ttl.get(cache_key, 0):
                return self._llm_cache[cache_key]
        
        try:
            import httpx
            import os
            
            ollama_url = os.environ.get("OLLAMA_URL", "").rstrip("/")
            if not ollama_url:
                return raw_reasoning
            
            model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
            
            prompt = (
                f"You are a senior day trader's AI assistant. Rewrite this trading setup data "
                f"into a concise 1-2 sentence narrative a trader would find actionable. "
                f"Keep the key numbers (price, %, R:R). Use confident, direct language.\n\n"
                f"Symbol: {symbol}\nSetup: {setup_type}\nDirection: {direction}\n"
                f"Raw data: {raw_reasoning}\n\n"
                f"Narrative (1-2 sentences, no bullet points):"
            )
            
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False,
                           "options": {"num_predict": 120, "temperature": 0.3}},
                )
                if resp.status_code == 200:
                    text = resp.json().get("response", "").strip()
                    if text and len(text) > 20:
                        # Cache it
                        self._llm_cache[cache_key] = text
                        self._llm_cache_ttl[cache_key] = _t.time() + 300  # 5 min TTL
                        # Prune cache if too large
                        if len(self._llm_cache) > 100:
                            oldest = min(self._llm_cache_ttl, key=self._llm_cache_ttl.get)
                            self._llm_cache.pop(oldest, None)
                            self._llm_cache_ttl.pop(oldest, None)
                        return text
        except Exception as e:
            logger.debug(f"LLM enrichment failed for {symbol} (using raw): {e}")
        
        return raw_reasoning

    
    async def _save_chat_message(self, role: str, content: str, timestamp: str):
        """Save a chat message to MongoDB"""
        try:
            db = _get_db()
            await asyncio.to_thread(db[self.CHAT_COLLECTION].insert_one, {
                "session_id": self._session_id,
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "created_at": datetime.now(timezone.utc)
            })
        except Exception as e:
            logger.error(f"Error saving chat message: {e}")
    
    async def _cleanup_old_messages(self):
        """Remove old messages beyond max_history from MongoDB"""
        try:
            db = _get_db()
            
            def _sync_cleanup():
                count = db[self.CHAT_COLLECTION].count_documents({"session_id": self._session_id})
                if count > self._max_history * 2:
                    keep_cursor = db[self.CHAT_COLLECTION].find(
                        {"session_id": self._session_id},
                        {"_id": 1}
                    ).sort("timestamp", DESCENDING).limit(self._max_history)
                    keep_ids = [doc["_id"] for doc in keep_cursor]
                    result = db[self.CHAT_COLLECTION].delete_many({
                        "session_id": self._session_id,
                        "_id": {"$nin": keep_ids}
                    })
                    logger.info(f"Cleaned up {result.deleted_count} old chat messages")
            
            await asyncio.to_thread(_sync_cleanup)
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
    
    def inject_dynamic_risk(self, dynamic_risk_engine):
        """Inject dynamic risk engine for risk-aware responses"""
        self._services["dynamic_risk_engine"] = dynamic_risk_engine
        logger.info("SentCom: Dynamic risk engine injected")
    
    def inject_regime_engine(self, regime_engine):
        """Inject market regime engine for regime-aware responses"""
        self._services["regime_engine"] = regime_engine
        logger.info("SentCom: Market regime engine injected")
    
    def _get_dynamic_risk_engine(self):
        """Get dynamic risk engine"""
        return self._services.get("dynamic_risk_engine")
    
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
        Combines bot thoughts, chat history, alerts, filter decisions,
        market data, risk updates, and scanner alerts.
        All in "we" voice with rich contextual information.
        """
        messages: List[SentComMessage] = []
        trading_bot = self._get_trading_bot()
        
        # =====================================================================
        # 1. SCANNER ALERTS - Live setup detection
        # =====================================================================
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner:
                # Get live alerts with setup details
                live_alerts = scanner.get_live_alerts() if hasattr(scanner, 'get_live_alerts') else []
                for alert in live_alerts[:5]:  # Top 5 alerts
                    setup_name = getattr(alert, 'setup_type', 'setup') or 'setup'
                    symbol = getattr(alert, 'symbol', '')
                    # Use TQS score (0-100) as primary, fallback to SMB score (0-50, scaled to 100)
                    tqs = getattr(alert, 'tqs_score', 0) or 0
                    smb = getattr(alert, 'smb_score_total', 0) or 0
                    score = tqs if tqs > 0 else (smb * 2)  # Normalize to 0-100 scale
                    entry_price = getattr(alert, 'entry_price', None) or getattr(alert, 'trigger_price', None)
                    stop_price = getattr(alert, 'stop_price', None) or getattr(alert, 'stop_loss', None)
                    target_price = getattr(alert, 'target_price', None) or getattr(alert, 'target', None)
                    timeframe = getattr(alert, 'timeframe', None)
                    headline = getattr(alert, 'headline', '') or ''
                    reasoning_list = getattr(alert, 'reasoning', []) or []
                    tqs_grade = getattr(alert, 'tqs_grade', '') or getattr(alert, 'trade_grade', '') or ''
                    win_rate = getattr(alert, 'strategy_win_rate', 0) or 0
                    profit_factor = getattr(alert, 'strategy_profit_factor', 0) or 0
                    risk_reward = getattr(alert, 'risk_reward', 0) or 0
                    direction = getattr(alert, 'direction', '') or ''
                    atr_pct = getattr(alert, 'atr_percent', 0) or 0
                    volatility = getattr(alert, 'volatility_regime', '') or ''
                    tape_score_val = getattr(alert, 'tape_score', 0) or 0
                    
                    # Infer trade_type and timeframe from strategy config, then setup name
                    setup_lower = setup_name.lower()
                    
                    # Check STRATEGY_CONFIG for authoritative timeframe
                    SWING_SETUPS = {
                        'squeeze', 'trend_continuation', 'daily_squeeze', 'daily_breakout',
                        'earnings_momentum', 'sector_rotation', 'gap_fade_daily',
                    }
                    POSITION_SETUPS = {
                        'base_breakout', 'accumulation_entry', 'relative_strength_position',
                        'position_trade',
                    }
                    SCALP_SETUPS = {
                        '9_ema_scalp', 'abc_scalp', 'spencer_scalp', 'puppy_dog',
                        'gap_give_go', 'gap_fade', 'short_squeeze_fade',
                    }
                    
                    if not timeframe:
                        if setup_name in POSITION_SETUPS:
                            timeframe = 'Weekly'
                            trade_type = 'Position'
                        elif setup_name in SWING_SETUPS:
                            timeframe = 'Daily'
                            trade_type = 'Swing'
                        elif setup_name in SCALP_SETUPS or 'scalp' in setup_lower:
                            timeframe = '5min'
                            trade_type = 'Scalp'
                        elif 'gap' in setup_lower or 'open' in setup_lower:
                            timeframe = '1min'
                            trade_type = 'Scalp'
                        else:
                            timeframe = '15min'
                            trade_type = 'Day Trade'
                    else:
                        # Infer trade_type from timeframe
                        if timeframe in ['1min', '5min']:
                            trade_type = 'Scalp'
                        elif timeframe in ['Daily', '1week']:
                            trade_type = 'Swing'
                        else:
                            trade_type = 'Day Trade'
                    
                    # Format setup name for display
                    setup_display = setup_name.replace('_', ' ').title()
                    
                    # Use headline if available, else build content
                    if headline:
                        content = headline
                    else:
                        content = f"Found setup: {symbol} {setup_display}"
                        if entry_price:
                            content += f" @ ${entry_price:.2f}"
                    
                    # Append score to content if significant
                    if score > 0:
                        grade_str = f" ({tqs_grade})" if tqs_grade else ""
                        content += f" — TQS {score:.0f}{grade_str}"
                    
                    # Build reasoning from actual alert data
                    if reasoning_list:
                        reasoning_text = " | ".join([r for r in reasoning_list if r])
                    else:
                        reasoning_text = f"Pattern matches {setup_display} criteria with confluence of technical factors."
                    
                    # Add win rate context to reasoning if available
                    if win_rate > 0:
                        reasoning_text += f" | Win rate: {win_rate:.0%}"
                        if profit_factor > 0:
                            reasoning_text += f", PF: {profit_factor:.1f}"
                    
                    # LLM enrichment: transform raw data into trader-friendly narrative
                    enriched_reasoning = await self._enrich_setup_with_llm(
                        symbol, setup_name, reasoning_text, direction
                    )
                    
                    # Confidence from TQS (0-100 → clamp to 10-95)
                    if score > 0:
                        confidence = max(10, min(95, int(score)))
                    else:
                        confidence = 50  # Unknown quality
                    
                    messages.append(SentComMessage(
                        id=self._generate_message_id(),
                        type="alert",
                        content=content,
                        timestamp=getattr(alert, 'timestamp', datetime.now(timezone.utc)).isoformat() if hasattr(getattr(alert, 'timestamp', None), 'isoformat') else datetime.now(timezone.utc).isoformat(),
                        confidence=confidence,
                        symbol=symbol,
                        action_type="setup_found",
                        metadata={
                            "source": "scanner",
                            "setup_type": setup_name,
                            "score": round(score, 1),
                            "tqs_grade": tqs_grade,
                            "entry_price": entry_price,
                            "stop_price": stop_price,
                            "target_price": target_price,
                            "trade_type": trade_type,
                            "timeframe": timeframe,
                            "direction": direction,
                            "risk_reward": round(risk_reward, 1) if risk_reward else None,
                            "win_rate": round(win_rate * 100, 1) if win_rate else None,
                            "profit_factor": round(profit_factor, 1) if profit_factor else None,
                            "atr_percent": round(atr_pct, 2) if atr_pct else None,
                            "volatility": volatility,
                            "tape_score": round(tape_score_val, 1) if tape_score_val else None,
                            "reasoning": enriched_reasoning
                        }
                    ))
                
                # Scanner status message
                scan_count = scanner._scan_count if hasattr(scanner, '_scan_count') else 0
                symbol_count = len(getattr(scanner, '_liquid_symbols', [])) if hasattr(scanner, '_liquid_symbols') else 0
                if symbol_count > 0:
                    messages.append(SentComMessage(
                        id=self._generate_message_id(),
                        type="thought",
                        content=f"Scanning {symbol_count} liquid symbols...",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        confidence=50,
                        action_type="scanning",
                        metadata={"source": "scanner", "symbol_count": symbol_count, "scan_count": scan_count}
                    ))
        except Exception as e:
            logger.debug(f"Scanner alerts not available: {e}")
        
        # =====================================================================
        # 2. DYNAMIC RISK ENGINE - Risk adjustments
        # =====================================================================
        try:
            risk_engine = self._get_dynamic_risk_engine()
            if risk_engine:
                risk_status = risk_engine.get_status()
                if risk_status:
                    multiplier = risk_status.get("current_multiplier", 1.0)
                    risk_level = risk_status.get("risk_level", "NORMAL")
                    factors = risk_status.get("factors", {})
                    
                    # Only show if risk is not normal
                    if multiplier != 1.0 or risk_level != "NORMAL":
                        # Determine primary factor
                        primary_factor = "market conditions"
                        if factors:
                            # Find highest weight factor
                            market_factor = factors.get("market_regime", {})
                            if market_factor.get("vix_level"):
                                vix = market_factor.get("vix_level", 0)
                                if vix > 25:
                                    primary_factor = f"elevated VIX ({vix:.1f})"
                                elif vix < 15:
                                    primary_factor = f"low VIX ({vix:.1f})"
                                else:
                                    primary_factor = f"VIX at {vix:.1f}"
                        
                        content = f"Risk adjusted → {multiplier:.1f}x based on {primary_factor}"
                        messages.append(SentComMessage(
                            id=self._generate_message_id(),
                            type="risk",
                            content=content,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            confidence=80,
                            action_type="risk_update",
                            metadata={
                                "source": "dynamic_risk",
                                "multiplier": multiplier,
                                "risk_level": risk_level,
                                "reasoning": f"Position sizing adjusted to {multiplier:.1f}x based on {primary_factor}. {risk_level} risk conditions."
                            }
                        ))
        except Exception as e:
            logger.debug(f"Risk engine not available: {e}")
        
        # =====================================================================
        # 3. MARKET REGIME / VIX - Market conditions
        # =====================================================================
        try:
            from routers.ib import _pushed_ib_data, get_vix_from_pushed_data
            
            # VIX data
            vix_data = get_vix_from_pushed_data()
            if vix_data and vix_data.get("price"):
                vix_price = vix_data.get("price", 0)
                vix_change = vix_data.get("change_percent", 0)
                
                # Determine regime signal
                if vix_change < -5:
                    regime_signal = "RISK_ON"
                    content = f"VIX down {abs(vix_change):.1f}% - {regime_signal} signal"
                elif vix_change > 5:
                    regime_signal = "RISK_OFF"
                    content = f"VIX up {vix_change:.1f}% - {regime_signal} signal"
                elif vix_price < 15:
                    regime_signal = "RISK_ON"
                    content = f"VIX at {vix_price:.1f} (low) - {regime_signal} conditions"
                elif vix_price > 25:
                    regime_signal = "RISK_OFF"
                    content = f"VIX at {vix_price:.1f} (elevated) - {regime_signal} conditions"
                else:
                    regime_signal = "NEUTRAL"
                    content = f"VIX at {vix_price:.1f} - {regime_signal} market"
                
                messages.append(SentComMessage(
                    id=self._generate_message_id(),
                    type="market",
                    content=content,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    confidence=75,
                    action_type="regime_update",
                    metadata={
                        "source": "market_data",
                        "vix": vix_price,
                        "vix_change": vix_change,
                        "regime": regime_signal,
                        "reasoning": f"VIX is a key volatility indicator. Current level suggests {regime_signal.lower().replace('_', ' ')} conditions."
                    }
                ))
            
            # Market breadth from SPY/QQQ
            spy_data = _pushed_ib_data.get("market_snapshot", {}).get("SPY", {})
            if spy_data:
                spy_change = spy_data.get("change_percent", 0)
                if abs(spy_change) > 0.5:
                    direction = "up" if spy_change > 0 else "down"
                    content = f"SPY {direction} {abs(spy_change):.2f}% - market {'strengthening' if spy_change > 0 else 'weakening'}"
                    messages.append(SentComMessage(
                        id=self._generate_message_id(),
                        type="market",
                        content=content,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        confidence=70,
                        action_type="breadth_update",
                        metadata={
                            "source": "market_data",
                            "spy_change": spy_change,
                            "reasoning": "Broad market direction influences individual stock momentum."
                        }
                    ))
        except Exception as e:
            logger.debug(f"Market data not available: {e}")
        
        # =====================================================================
        # 4. POSITION MONITORING - Stop levels & P&L
        # =====================================================================
        if trading_bot:
            try:
                bot_status = trading_bot.get_status()
                
                if isinstance(bot_status, dict):
                    open_trades = bot_status.get("open_trades", [])
                    if isinstance(open_trades, list):
                        for trade in open_trades[:5]:
                            symbol = trade.get("symbol")
                            pnl_pct = trade.get("pnl_percent", 0)
                            stop = trade.get("stop_price")
                            current_price = trade.get("current_price")
                            entry = trade.get("entry_price")
                            
                            # Stop monitoring message
                            if stop and symbol:
                                content = f"Monitoring {symbol} stop @ ${stop:.2f}"
                                if current_price and stop:
                                    distance = ((current_price - stop) / current_price) * 100 if current_price > 0 else 0
                                    if distance < 2:
                                        content += f" (CLOSE - {distance:.1f}% away)"
                                
                                messages.append(SentComMessage(
                                    id=self._generate_message_id(),
                                    type="monitor",
                                    content=content,
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    confidence=60,
                                    symbol=symbol,
                                    action_type="monitoring",
                                    metadata={
                                        "source": "trading_bot",
                                        "stop_price": stop,
                                        "current_price": current_price,
                                        "pnl_percent": pnl_pct,
                                        "reasoning": f"Tracking stop level to protect {'profits' if pnl_pct > 0 else 'capital'}."
                                    }
                                ))
                            
                            # Entry zone cleared message
                            if entry and current_price and pnl_pct > 1:
                                messages.append(SentComMessage(
                                    id=self._generate_message_id(),
                                    type="alert",
                                    content=f"{symbol} cleared for profit taking zone (+{pnl_pct:.1f}%)",
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    confidence=70,
                                    symbol=symbol,
                                    action_type="entry_zone",
                                    metadata={
                                        "source": "trading_bot",
                                        "pnl_percent": pnl_pct,
                                        "reasoning": "Position has moved favorably past entry, consider trailing stop or partial profit taking."
                                    }
                                ))
                    
                    # Scanning status
                    mode = bot_status.get("mode", "confirmation")
                    running = bot_status.get("running", False)
                    if running:
                        messages.append(SentComMessage(
                            id=self._generate_message_id(),
                            type="thought",
                            content=f"Active in {mode} mode - ready to execute on confirmed setups",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            confidence=50,
                            action_type="scanning",
                            metadata={"source": "trading_bot", "mode": mode}
                        ))
                    
                    # Get filter thoughts
                    try:
                        filter_thoughts = trading_bot.get_filter_thoughts(limit=3)
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
                                    "reasoning": ft.get("reasoning", "Based on our trading rules and historical performance.")
                                }
                            ))
                    except Exception:
                        pass
                    
                    # Get recent closed trades (trade decisions/executions) — TODAY only
                    try:
                        closed_trades = trading_bot.get_closed_trades(limit=20)
                        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        today_trades = []
                        for trade in closed_trades:
                            closed_at = trade.get("closed_at", trade.get("exit_time", ""))
                            # Only include trades closed today
                            if closed_at and today_str in str(closed_at):
                                today_trades.append(trade)
                            elif not closed_at:
                                # No close time — check entry time
                                entry_time = trade.get("entry_time", trade.get("opened_at", ""))
                                if entry_time and today_str in str(entry_time):
                                    today_trades.append(trade)
                        
                        for trade in today_trades[:5]:
                            symbol = trade.get("symbol", "")
                            side = trade.get("side", trade.get("action", "BUY"))
                            entry_price = trade.get("entry_price", 0)
                            exit_price = trade.get("exit_price", 0)
                            pnl = trade.get("pnl", 0)
                            pnl_pct = trade.get("pnl_percent", 0)
                            closed_at = trade.get("closed_at", trade.get("exit_time"))
                            
                            # Format trade execution message
                            if side.upper() == "SELL" or side.upper() == "SHORT":
                                action_text = "SHORTED"
                                exit_text = "covered"
                            else:
                                action_text = "BOUGHT"
                                exit_text = "sold"
                            
                            if exit_price and exit_price > 0 and pnl is not None:
                                pnl_sign = "+" if pnl >= 0 else ""
                                content = f"Trade closed: {exit_text} {symbol} @ ${exit_price:.2f} ({pnl_sign}${pnl:.2f}, {pnl_sign}{pnl_pct:.1f}%)"
                            elif exit_price and exit_price > 0:
                                content = f"Trade closed: {exit_text} {symbol} @ ${exit_price:.2f}"
                            else:
                                content = f"Trade executed: {action_text} {symbol} @ ${entry_price:.2f}"
                            
                            # Calculate hold duration if timestamps available
                            hold_info = ""
                            try:
                                entry_time = trade.get("entry_time", trade.get("opened_at"))
                                if entry_time and closed_at:
                                    from datetime import datetime as dt
                                    t1 = dt.fromisoformat(str(entry_time).replace('Z', '+00:00')) if isinstance(entry_time, str) else entry_time
                                    t2 = dt.fromisoformat(str(closed_at).replace('Z', '+00:00')) if isinstance(closed_at, str) else closed_at
                                    hold_mins = int((t2 - t1).total_seconds() / 60)
                                    if hold_mins < 60:
                                        hold_info = f" | Held {hold_mins}min"
                                    else:
                                        hold_info = f" | Held {hold_mins // 60}h{hold_mins % 60}m"
                            except Exception:
                                pass
                            
                            # Build richer reasoning
                            if pnl and pnl > 0:
                                reasoning_text = f"Winner: Hit target on {symbol} trade.{hold_info}"
                            elif pnl and pnl < 0:
                                reasoning_text = f"Loser: Stopped out on {symbol} trade ({pnl_sign}${abs(pnl):.2f}).{hold_info}"
                            elif pnl == 0:
                                reasoning_text = f"Breakeven: Exited {symbol} at entry.{hold_info}"
                            else:
                                reasoning_text = f"Trade {'closed' if exit_price else 'executed'}: {symbol}.{hold_info}"
                            
                            messages.append(SentComMessage(
                                id=self._generate_message_id(),
                                type="trade",
                                content=content,
                                timestamp=closed_at if closed_at else datetime.now(timezone.utc).isoformat(),
                                confidence=90,
                                symbol=symbol,
                                action_type="trade_executed",
                                metadata={
                                    "source": "trading_bot",
                                    "side": side,
                                    "entry_price": entry_price,
                                    "exit_price": exit_price,
                                    "pnl": pnl,
                                    "pnl_percent": pnl_pct,
                                    "setup_type": trade.get("setup_type", trade.get("strategy", "")),
                                    "r_multiple": trade.get("r_multiple", trade.get("actual_r_multiple")),
                                    "reasoning": reasoning_text
                                }
                            ))
                    except Exception as e:
                        logger.debug(f"No closed trades for stream: {e}")
                        
            except Exception as e:
                logger.error(f"Error getting bot thoughts: {e}")
        
        # =====================================================================
        # 5. IB POSITIONS SUMMARY
        # =====================================================================
        try:
            from routers.ib import _pushed_ib_data
            ib_positions = _pushed_ib_data.get("positions", [])
            if ib_positions:
                # Price updates for each position
                for pos in ib_positions[:3]:
                    symbol = pos.get("symbol", pos.get("contract", {}).get("symbol", ""))
                    price = pos.get("marketPrice", pos.get("avgCost", 0))
                    pnl = pos.get("unrealizedPNL", pos.get("unrealizedPnL", 0))
                    pnl_pct = (pnl / (pos.get("avgCost", 1) * pos.get("position", 1))) * 100 if pos.get("avgCost") and pos.get("position") else 0
                    
                    if symbol and price:
                        direction = "▲" if pnl >= 0 else "▼"
                        content = f"{symbol} @ ${price:.2f} {direction}{abs(pnl_pct):.2f}%"
                        messages.append(SentComMessage(
                            id=self._generate_message_id(),
                            type="position",
                            content=content,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            confidence=80,
                            symbol=symbol,
                            action_type="price_update",
                            metadata={
                                "source": "ib_positions",
                                "price": price,
                                "pnl": pnl,
                                "pnl_percent": pnl_pct,
                                "reasoning": f"Position {'profitable' if pnl >= 0 else 'at a loss'} - monitoring for exit signals."
                            }
                        ))
        except Exception as e:
            logger.debug(f"No IB positions for stream: {e}")
        
        # =====================================================================
        # 6. CHAT HISTORY (Limited)
        # =====================================================================
        for chat in self._chat_history[-5:]:
            messages.append(SentComMessage(
                id=chat.get("id", self._generate_message_id()),
                type="chat",
                content=chat.get("content", ""),
                timestamp=chat.get("timestamp", datetime.now(timezone.utc).isoformat()),
                confidence=chat.get("confidence"),
                symbol=chat.get("symbol"),
                action_type="chat_response" if chat.get("role") == "assistant" else "user_message",
                metadata={"source": "sentcom_chat", "role": chat.get("role", "assistant")}
            ))
        
        # =====================================================================
        # 7. DEMO MODE - Generate sample messages when no real data
        # =====================================================================
        non_chat_messages = [m for m in messages if m.type != 'chat']
        if len(non_chat_messages) < 3:
            demo_messages = self._generate_demo_stream_messages()
            messages.extend(demo_messages)
        
        # =====================================================================
        # 8. FALLBACK - System status if no activity
        # =====================================================================
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
    
    def _generate_demo_stream_messages(self) -> List[SentComMessage]:
        """
        Generate realistic demo S.O.C. messages when real market data isn't available.
        This shows the user what the stream looks like when fully operational.
        """
        import random
        from datetime import timedelta
        
        demo_symbols = ["NVDA", "AAPL", "MSFT", "AMD", "META", "TSLA", "GOOGL"]
        demo_setups = ["momentum_breakout", "gap_and_go", "vwap_bounce", "9_ema_scalp", "pullback_entry"]
        demo_trade_types = ["Scalp", "Day Trade", "Swing"]
        demo_timeframes = ["1min", "5min", "15min", "1hr", "Daily"]
        
        messages = []
        base_time = datetime.now(timezone.utc)
        
        # 1. Scanner scanning message
        symbol_count = random.randint(180, 250)
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="thought",
            content=f"Scanning {symbol_count} liquid symbols...",
            timestamp=(base_time - timedelta(seconds=random.randint(5, 15))).isoformat(),
            confidence=50,
            action_type="scanning",
            metadata={
                "source": "demo",
                "reasoning": "Analyzing price action, volume patterns, and technical indicators across the watchlist."
            }
        ))
        
        # 2. Setup found
        setup_symbol = random.choice(demo_symbols)
        setup_type = random.choice(demo_setups)
        setup_price = round(random.uniform(100, 500), 2)
        trade_type = random.choice(demo_trade_types)
        timeframe = random.choice(demo_timeframes)
        stop_dist = round(setup_price * random.uniform(0.01, 0.03), 2)
        target_dist = round(setup_price * random.uniform(0.03, 0.08), 2)
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="alert",
            content=f"Found setup: {setup_symbol} {setup_type.replace('_', ' ').title()} @ ${setup_price:.2f}",
            timestamp=(base_time - timedelta(seconds=random.randint(16, 30))).isoformat(),
            confidence=random.randint(70, 90),
            symbol=setup_symbol,
            action_type="setup_found",
            metadata={
                "source": "demo",
                "setup_type": setup_type,
                "entry_price": setup_price,
                "stop_price": round(setup_price - stop_dist, 2),
                "target_price": round(setup_price + target_dist, 2),
                "trade_type": trade_type,
                "timeframe": timeframe,
                "score": round(random.uniform(7, 9.5), 1),
                "reasoning": f"Pattern matches {setup_type.replace('_', ' ')} criteria with strong volume confirmation."
            }
        ))
        
        # 3. Risk adjustment
        vix_level = round(random.uniform(12, 28), 1)
        risk_mult = round(1.0 + (20 - vix_level) / 40, 1)  # Higher mult when VIX is low
        risk_mult = max(0.5, min(1.5, risk_mult))
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="risk",
            content=f"Risk adjusted → {risk_mult}x based on VIX at {vix_level}",
            timestamp=(base_time - timedelta(seconds=random.randint(31, 45))).isoformat(),
            confidence=80,
            action_type="risk_update",
            metadata={
                "source": "demo",
                "multiplier": risk_mult,
                "vix": vix_level,
                "reasoning": "Position sizing adjusted based on current volatility environment."
            }
        ))
        
        # 4. VIX / Market regime
        vix_change = round(random.uniform(-8, 8), 1)
        regime = "RISK_ON" if vix_change < -3 else ("RISK_OFF" if vix_change > 3 else "NEUTRAL")
        direction = "down" if vix_change < 0 else "up"
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="market",
            content=f"VIX {direction} {abs(vix_change):.1f}% - {regime} signal",
            timestamp=(base_time - timedelta(seconds=random.randint(46, 60))).isoformat(),
            confidence=75,
            action_type="regime_update",
            metadata={
                "source": "demo",
                "vix_change": vix_change,
                "regime": regime,
                "reasoning": f"Market volatility indicator suggests {regime.lower().replace('_', ' ')} conditions."
            }
        ))
        
        # 5. Position monitoring (stop level)
        pos_symbol = random.choice(demo_symbols)
        stop_price = round(random.uniform(80, 200), 2)
        current_price = round(stop_price * random.uniform(1.01, 1.05), 2)
        watch_trade_type = random.choice(demo_trade_types)
        watch_timeframe = random.choice(demo_timeframes)
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="monitor",
            content=f"Monitoring {pos_symbol} stop @ ${stop_price:.2f} — {round((current_price - stop_price) / current_price * 100, 1)}% away",
            timestamp=(base_time - timedelta(seconds=random.randint(61, 75))).isoformat(),
            confidence=60,
            symbol=pos_symbol,
            action_type="monitoring",
            metadata={
                "source": "demo",
                "stop_price": stop_price,
                "current_price": current_price,
                "trade_type": watch_trade_type,
                "timeframe": watch_timeframe,
                "reasoning": "Tracking stop level to protect capital."
            }
        ))
        
        # 6. Breadth update
        breadth_pct = random.randint(45, 70)
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="market",
            content=f"Breadth {'improving' if breadth_pct > 55 else 'declining'}: {breadth_pct}% > 20MA",
            timestamp=(base_time - timedelta(seconds=random.randint(76, 90))).isoformat(),
            confidence=70,
            action_type="breadth_update",
            metadata={
                "source": "demo",
                "breadth": breadth_pct,
                "reasoning": "Market breadth indicates overall market participation."
            }
        ))
        
        # 7. Entry zone cleared
        entry_symbol = random.choice(demo_symbols)
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="alert",
            content=f"{entry_symbol} cleared for entry zone",
            timestamp=(base_time - timedelta(seconds=random.randint(91, 105))).isoformat(),
            confidence=75,
            symbol=entry_symbol,
            action_type="entry_zone",
            metadata={
                "source": "demo",
                "reasoning": "Price action confirms favorable entry conditions."
            }
        ))
        
        # 8. Trade execution (winner or loser)
        trade_symbol = random.choice(demo_symbols)
        is_winner = random.random() > 0.35  # 65% win rate
        entry_price = round(random.uniform(100, 400), 2)
        if is_winner:
            exit_price = round(entry_price * (1 + random.uniform(0.02, 0.08)), 2)
        else:
            exit_price = round(entry_price * (1 - random.uniform(0.01, 0.03)), 2)
        pnl = round((exit_price - entry_price) * random.randint(50, 200), 2)
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 1)
        exec_trade_type = random.choice(demo_trade_types)
        exec_timeframe = random.choice(demo_timeframes)
        
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="trade",
            content=f"Trade closed: sold {trade_symbol} @ ${exit_price:.2f} ({'+' if pnl >= 0 else ''}{pnl_pct:.1f}%)",
            timestamp=(base_time - timedelta(seconds=random.randint(106, 120))).isoformat(),
            confidence=90,
            symbol=trade_symbol,
            action_type="trade_executed",
            metadata={
                "source": "demo",
                "side": "BUY",
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_percent": pnl_pct,
                "trade_type": exec_trade_type,
                "timeframe": exec_timeframe,
                "reasoning": f"{'Winner' if pnl > 0 else 'Loser'}: {'Hit target' if pnl > 0 else 'Stopped out'} on {trade_symbol} {exec_trade_type.lower()}."
            }
        ))
        
        # 9. Trade decision (should we take this?)
        decision_symbol = random.choice(demo_symbols)
        decision_setup = random.choice(demo_setups)
        take_trade = random.random() > 0.3  # 70% approve rate
        decision_price = round(random.uniform(80, 300), 2)
        decision_trade_type = random.choice(demo_trade_types)
        decision_timeframe = random.choice(demo_timeframes)
        
        if take_trade:
            content = f"TAKING TRADE: {decision_symbol} {decision_setup.replace('_', ' ')} @ ${decision_price:.2f}"
            decision_type = "approved"
        else:
            content = f"PASSING: {decision_symbol} doesn't meet our criteria — waiting for better R:R"
            decision_type = "rejected"
        
        messages.append(SentComMessage(
            id=self._generate_message_id(),
            type="decision",
            content=content,
            timestamp=(base_time - timedelta(seconds=random.randint(121, 135))).isoformat(),
            confidence=random.randint(70, 95),
            symbol=decision_symbol,
            action_type="trade_decision",
            metadata={
                "source": "demo",
                "decision": decision_type,
                "setup_type": decision_setup,
                "price": decision_price,
                "trade_type": decision_trade_type,
                "timeframe": decision_timeframe,
                "reasoning": f"{'Setup meets our criteria with good risk/reward' if take_trade else 'Risk/reward not favorable or setup quality below threshold'}."
            }
        ))
        
        return messages
    
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
            
            # Process through orchestrator with timeout to prevent hanging
            import asyncio
            result = await asyncio.wait_for(
                orchestrator.process(
                    message=message, 
                    session_id=session_id,
                    chat_history=recent_history
                ),
                timeout=45.0  # 45s max for entire chat pipeline
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
            await self._save_chat_message("user", message, user_msg["timestamp"])
            await self._save_chat_message("assistant", response_text, assistant_msg["timestamp"])
            
            # Trim in-memory history
            if len(self._chat_history) > self._max_history:
                self._chat_history = self._chat_history[-self._max_history:]
            
            # Periodically clean up old DB messages
            await self._cleanup_old_messages()
            
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
            
        except asyncio.TimeoutError:
            logger.error("SentCom chat timed out after 45s")
            return {
                "success": False,
                "response": "Our AI took too long to respond. This usually means the language model is loading. Please try again in a few seconds.",
                "source": "sentcom_timeout"
            }
        except Exception as e:
            logger.error(f"SentCom chat error: {type(e).__name__}: {e}")
            # Provide a friendly error message
            error_response = "We're having trouble with that query right now."
            if "connection" in str(e).lower() or "offline" in str(e).lower():
                error_response = "We're currently offline and can't access market data. Once we're connected, we'll be able to help with that."
            elif "NoneType" in str(e) or "not found" in str(e).lower():
                error_response = "We're still initializing our systems. Give us a moment and try again."
            else:
                error_response = "We ran into an issue processing that. Let's try again in a moment."
            
            return {
                "success": False,
                "response": error_response,
                "source": "sentcom_error"
            }
    
    async def get_market_context(self) -> Dict[str, Any]:
        """Get current market context for SentCom display"""
        regime_engine = self._get_regime_engine()
        ib_service = self._get_ib_service()
        dynamic_risk = self._get_dynamic_risk_engine()
        
        context = {
            "regime": "UNKNOWN",
            "spy_trend": None,
            "vix": None,
            "sector_flow": None,
            "market_open": False,
            "dynamic_risk": None
        }
        
        # Get regime
        if regime_engine:
            try:
                regime_data = await regime_engine.get_current_regime()
                # The regime engine returns "state" not "regime"
                context["regime"] = regime_data.get("state", regime_data.get("regime", "UNKNOWN"))
                context["spy_trend"] = regime_data.get("spy_trend")
                # Get VIX from signal blocks if not at top level
                vix_data = regime_data.get("signal_blocks", {}).get("volume_vix", {}).get("signals", {})
                context["vix"] = regime_data.get("vix") or vix_data.get("vix_price")
            except Exception as e:
                logger.error(f"Error getting regime: {e}")
        
        # Get dynamic risk status
        if dynamic_risk:
            try:
                risk_status = dynamic_risk.get_status()
                context["dynamic_risk"] = {
                    "enabled": risk_status.get("enabled", False),
                    "multiplier": risk_status.get("current_multiplier", 1.0),
                    "risk_level": risk_status.get("current_risk_level", "normal"),
                    "position_size": risk_status.get("effective_position_size"),
                    "override_active": risk_status.get("override", {}).get("active", False)
                }
            except Exception as e:
                logger.error(f"Error getting dynamic risk status: {e}")
        
        # Check if market is open
        now = datetime.now(timezone.utc)
        # Simple check - market hours are roughly 14:30 - 21:00 UTC (9:30 AM - 4:00 PM ET)
        if now.weekday() < 5:  # Monday-Friday
            if 14 <= now.hour < 21:
                context["market_open"] = True
        
        return context
    
    async def get_risk_assessment(self, symbol: str = None, setup_type: str = None) -> Dict[str, Any]:
        """Get current risk assessment from Dynamic Risk Engine"""
        dynamic_risk = self._get_dynamic_risk_engine()
        
        if not dynamic_risk:
            return {
                "success": False,
                "error": "Dynamic risk engine not available",
                "multiplier": 1.0,
                "explanation": "Risk engine offline - using standard sizing"
            }
        
        try:
            assessment = await dynamic_risk.assess_risk(symbol=symbol, setup_type=setup_type)
            return {
                "success": True,
                **assessment.to_dict()
            }
        except Exception as e:
            logger.error(f"Error getting risk assessment: {e}")
            return {
                "success": False,
                "error": str(e),
                "multiplier": 1.0,
                "explanation": "Risk assessment failed - using standard sizing"
            }
    
    async def get_our_positions(self) -> List[Dict[str, Any]]:
        """Get our current positions with P&L from both Trading Bot and IB.
        
        Returns enriched position data including:
        - market_value, cost_basis, portfolio_weight
        - risk_level (ok/warning/danger/critical based on drawdown)
        - today_change data from IB quotes when available
        """
        trading_bot = self._get_trading_bot()
        
        positions = []
        seen_symbols = set()
        
        # Get IB quotes for today's change data
        ib_quotes = {}
        try:
            from routers.ib import _pushed_ib_data
            for sym, q in _pushed_ib_data.get("quotes", {}).items():
                ib_quotes[sym] = q
        except Exception:
            pass
        
        # First, get bot-managed trades (these have more detailed tracking)
        if trading_bot:
            try:
                open_trades = trading_bot.get_open_trades()
                if isinstance(open_trades, list):
                    for trade in open_trades:
                        symbol = trade.get("symbol")
                        if symbol:
                            seen_symbols.add(symbol)
                        
                        entry = trade.get("fill_price") or trade.get("entry_price", 0) or 0
                        current = trade.get("current_price") or entry
                        shares = trade.get("shares") or trade.get("quantity", 0) or 0
                        direction = trade.get("direction", "long")
                        
                        # Calculate P&L based on direction
                        if direction == "short":
                            pnl = (entry - current) * shares if entry and current else 0
                            pnl_pct = ((entry - current) / entry * 100) if entry else 0
                        else:
                            pnl = (current - entry) * shares if entry and current else 0
                            pnl_pct = ((current - entry) / entry * 100) if entry else 0
                        
                        market_value = abs(shares * current) if current else 0
                        cost_basis = abs(shares * entry) if entry else 0
                        
                        # Today's intraday change from IB quotes
                        quote = ib_quotes.get(symbol, {})
                        today_change = quote.get("change") or quote.get("todayChange") or 0
                        today_change_pct = quote.get("change_pct") or quote.get("todayChangePct") or 0
                        
                        # Risk level based on drawdown
                        risk_level = "ok"
                        if pnl_pct < -30:
                            risk_level = "critical"
                        elif pnl_pct < -15:
                            risk_level = "danger"
                        elif pnl_pct < -7:
                            risk_level = "warning"
                        
                        positions.append({
                            "symbol": symbol,
                            "shares": shares,
                            "direction": direction,
                            "entry_price": entry,
                            "current_price": current,
                            "pnl": round(pnl, 2),
                            "pnl_percent": round(pnl_pct, 2),
                            "market_value": round(market_value, 2),
                            "cost_basis": round(cost_basis, 2),
                            "today_change": round(today_change * shares, 2) if today_change else 0,
                            "today_change_pct": round(today_change_pct, 2) if today_change_pct else 0,
                            "risk_level": risk_level,
                            "stop_price": trade.get("stop_price"),
                            "target_prices": trade.get("target_prices", []),
                            "status": trade.get("status", "open"),
                            "setup_type": trade.get("setup_type", "unknown"),
                            "setup_variant": trade.get("setup_variant", ""),
                            "trade_style": trade.get("trade_style", ""),
                            "entry_time": trade.get("executed_at"),
                            "trade_id": trade.get("id"),
                            "source": "bot",
                            "notes": trade.get("notes", ""),
                            "quality_score": trade.get("quality_score", 0),
                            "quality_grade": trade.get("quality_grade", ""),
                            "smb_grade": trade.get("smb_grade", ""),
                            "mfe_pct": trade.get("mfe_pct", 0),
                            "mae_pct": trade.get("mae_pct", 0),
                            "ai_context": trade.get("ai_context"),
                            "market_regime": trade.get("market_regime", ""),
                            "close_reason": trade.get("close_reason"),
                            "timeframe": trade.get("timeframe", ""),
                        })
            except Exception as e:
                logger.error(f"Error getting bot positions: {e}")
        
        # Then, get IB positions from pushed data
        try:
            from routers.ib import _pushed_ib_data
            ib_positions = _pushed_ib_data.get("positions", [])
            
            for pos in ib_positions:
                symbol = pos.get("symbol")
                if symbol and symbol not in seen_symbols:
                    shares = pos.get("position", 0)
                    avg_cost = pos.get("avgCost", 0) or pos.get("avg_cost", 0)
                    market_price = pos.get("marketPrice", 0) or pos.get("market_price", 0)
                    unrealized_pnl = pos.get("unrealizedPnL") or pos.get("unrealizedPNL") or pos.get("unrealized_pnl")
                    realized_pnl = pos.get("realizedPnL") or pos.get("realizedPNL") or pos.get("realized_pnl") or 0
                    
                    # Calculate P&L from prices if unrealized_pnl not available
                    if unrealized_pnl is None and market_price and avg_cost and shares:
                        unrealized_pnl = (market_price - avg_cost) * shares
                    unrealized_pnl = unrealized_pnl or 0
                    
                    # Calculate P&L percent
                    total_cost = abs(shares * avg_cost) if shares and avg_cost else 0
                    if total_cost > 0:
                        pnl_pct = (unrealized_pnl / total_cost * 100)
                    elif market_price and avg_cost and avg_cost > 0:
                        pnl_pct = ((market_price - avg_cost) / avg_cost * 100)
                    else:
                        pnl_pct = 0
                    
                    position_type = "long" if shares > 0 else "short"
                    abs_shares = abs(shares)
                    current = market_price if market_price else avg_cost
                    market_value = abs_shares * current if current else 0
                    cost_basis_val = abs_shares * avg_cost if avg_cost else 0
                    
                    # Today's intraday change from IB quotes
                    quote = ib_quotes.get(symbol, {})
                    today_change = quote.get("change") or quote.get("todayChange") or 0
                    today_change_pct = quote.get("change_pct") or quote.get("todayChangePct") or 0
                    
                    # Risk level based on drawdown
                    risk_level = "ok"
                    if pnl_pct < -30:
                        risk_level = "critical"
                    elif pnl_pct < -15:
                        risk_level = "danger"
                    elif pnl_pct < -7:
                        risk_level = "warning"
                    
                    positions.append({
                        "symbol": symbol,
                        "shares": abs_shares,
                        "direction": position_type,
                        "entry_price": avg_cost,
                        "current_price": current,
                        "pnl": round(unrealized_pnl, 2),
                        "pnl_percent": round(pnl_pct, 2),
                        "market_value": round(market_value, 2),
                        "cost_basis": round(cost_basis_val, 2),
                        "realized_pnl": round(realized_pnl, 2),
                        "today_change": round(today_change * abs_shares, 2) if today_change else 0,
                        "today_change_pct": round(today_change_pct, 2) if today_change_pct else 0,
                        "risk_level": risk_level,
                        "stop_price": None,
                        "target_prices": [],
                        "status": "ib_position",
                        "entry_time": None,
                        "source": "ib",
                        "setup_type": "",
                        "setup_variant": "",
                        "trade_style": "",
                        "market_regime": "",
                        "timeframe": "",
                        "quality_grade": "",
                        "notes": "",
                    })
        except Exception as e:
            logger.error(f"Error getting IB positions: {e}")
        
        # Compute portfolio totals and weights
        total_market_value = sum(p.get("market_value", 0) for p in positions)
        for p in positions:
            if total_market_value > 0:
                p["portfolio_weight"] = round(p.get("market_value", 0) / total_market_value * 100, 1)
            else:
                p["portfolio_weight"] = 0
        
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
                    "note": "Winner pulling back - scale opportunity"
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
                    "note": "Reclaiming - momentum add"
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
                            "confidence": alert.get("tqs_score", alert.get("smb_score_total", alert.get("score", alert.get("confidence", 50)))),
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
