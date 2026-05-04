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
    # V5 HUD enrichment — populated by get_status() below. All optional so
    # older consumers that ignore these keys keep working.
    trading_phase: Optional[str] = None          # "MARKET OPEN" | "PRE MARKET" | ...
    account_equity: Optional[float] = None       # net liq (USD)
    scanner_bar_size: Optional[str] = None       # e.g. "multi" or "1 min · 5 mins"
    scanner_universe_size: Optional[int] = None  # watchlist count
    
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
            "trading_phase": self.trading_phase,
            "account_equity": self.account_equity,
            "scanner_bar_size": self.scanner_bar_size,
            "scanner_universe_size": self.scanner_universe_size,
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
        # Stream accumulator — persists messages across get_unified_stream calls
        self._stream_buffer: List[SentComMessage] = []
        self._stream_seen_keys: set = set()  # Dedup keys (type+symbol+content_hash)
        self._stream_max_size = 100  # Keep last 100 entries
        
        # Load recent chat messages (current day only, for continuity)
        self._load_recent_chat_history()
        # Load recent thoughts/decisions from MongoDB so the unified
        # stream survives backend restarts (operator's V4 muscle memory:
        # "what was the bot thinking before I restarted?"). Persistent
        # store is `sentcom_thoughts` (TTL 7d) — see emit_stream_event.
        self._load_recent_thoughts()
        logger.info(
            f"SentCom session {self._session_id}: loaded "
            f"{len(self._chat_history)} chat msgs · "
            f"{len(self._stream_buffer)} thoughts from disk"
        )
    
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

    def _load_recent_thoughts(self):
        """Hydrate `_stream_buffer` from `sentcom_thoughts` so the unified
        stream survives a backend restart. Loads up to `_stream_max_size`
        most-recent thoughts from the last 24h. Sync — runs once at init."""
        try:
            db = _get_db()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            cursor = (
                db[THOUGHTS_COLLECTION]
                .find({"created_at": {"$gte": cutoff}}, {"_id": 0})
                .sort("created_at", DESCENDING)
                .limit(self._stream_max_size)
            )
            for row in cursor:
                try:
                    msg = SentComMessage(
                        id=row.get("id") or self._generate_message_id(),
                        type=row.get("kind") or "thought",
                        content=row.get("content") or "",
                        timestamp=row.get("timestamp")
                            or (row.get("created_at").isoformat()
                                if isinstance(row.get("created_at"), datetime)
                                else datetime.now(timezone.utc).isoformat()),
                        confidence=row.get("confidence"),
                        symbol=row.get("symbol"),
                        action_type=row.get("action_type"),
                        metadata=row.get("metadata") or {},
                    )
                except Exception:
                    continue
                key = f"{msg.type}:{msg.symbol or ''}:{msg.content[:40]}"
                if key in self._stream_seen_keys:
                    continue
                self._stream_seen_keys.add(key)
                self._stream_buffer.append(msg)
            # Newest first.
            self._stream_buffer.sort(key=lambda m: m.timestamp, reverse=True)
        except Exception as e:
            logger.debug(f"Could not hydrate sentcom_thoughts on startup: {e}")

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

    def _compose_conversational_setup_narrative(
        self,
        *,
        symbol: str,
        setup_display: str,
        setup_name: str,
        headline: str,
        direction: str,
        score: float,
        tqs_grade: str,
        entry_price,
        stop_price,
        target_price,
        risk_reward: float,
        win_rate: float,
        profit_factor: float,
        trade_type: str,
        timeframe: str,
        reasoning_list,
    ) -> str:
        """
        Build a wordy, conversational setup-found narrative — operator
        preference (2026-04-28): "I really want to know what the bot
        is thinking and doing at all times."

        Replaces the terse one-liner
            "RS LEADER NVDA +6.8% vs SPY - Outperforming market — TQS 51 (C)"
        with a 2-3 sentence story:

            Sentence 1 — what the bot saw (setup + symbol + key tell)
            Sentence 2 — quality assessment (TQS + grade + interpretation,
                         win-rate + profit-factor history if available)
            Sentence 3 — the trade plan if the bot has prices
                         (entry / stop / target / R:R / hold horizon)

        Designed to never throw — every input is optional. Falls back
        to setup-only sentence if no prices/scores are available.
        """
        dir_word = (direction or "").lower()
        dir_phrase = (
            "long" if dir_word in ("long", "buy") else
            "short" if dir_word in ("short", "sell") else
            "directional"
        )

        # ---------- Sentence 1: what we saw ----------
        # Use the existing scanner headline (e.g. "RS LEADER NVDA +6.8%
        # vs SPY - Outperforming market") if available — it already
        # carries the setup-specific tell and the operator's familiar
        # with the format. Otherwise build from setup_display.
        if headline:
            saw_clause = f"📡 {symbol} — spotted a {setup_display} setup. {headline.strip()}."
        else:
            saw_clause = f"📡 {symbol} — spotted a {setup_display} setup."

        # First reasoning line tends to be the strongest tell — surface
        # it as a "why" if the headline didn't already say it.
        why = ""
        if isinstance(reasoning_list, (list, tuple)) and reasoning_list:
            first = str(reasoning_list[0]).strip()
            if first and (not headline or first.lower()[:25] not in headline.lower()):
                why = f" Why: {first}."

        # ---------- Sentence 2: quality assessment ----------
        quality = ""
        if score and score > 0:
            grade_label = ""
            if tqs_grade:
                grade_label = f" (grade {tqs_grade})"
            # Plain-English interpretation of TQS bands.
            if score >= 80:
                interp = "this is a high-conviction read — the setup is firing on most quality dimensions"
            elif score >= 70:
                interp = "this is a solid setup, comfortably above our 70+ preferred quality bar"
            elif score >= 60:
                interp = "the setup is acceptable but middling — wants more confluence to be exciting"
            elif score >= 50:
                interp = "quality is borderline — proceed cautiously, we'd rather wait for a 70+"
            else:
                interp = "quality is weak — we'd usually skip and wait for something cleaner"
            quality = f" Quality call: TQS {score:.0f}/100{grade_label} — {interp}."

        # Win-rate / profit-factor color from the strategy's recent track
        # record. Only adds a sentence when we actually have history.
        track_record = ""
        if win_rate and win_rate > 0:
            wr_pct = win_rate * 100 if win_rate <= 1 else win_rate
            edge_word = "edge" if wr_pct >= 55 else "thin edge" if wr_pct >= 50 else "no edge"
            track_record = f" Recent stats on this setup: {wr_pct:.0f}% win rate"
            if profit_factor and profit_factor > 0:
                track_record += f", profit factor {profit_factor:.1f}"
            track_record += f" — {edge_word}."

        # ---------- Sentence 3: the trade plan ----------
        plan = ""
        try:
            if entry_price and entry_price > 0:
                ep = float(entry_price)
                plan_parts = [f"💡 Plan: {dir_phrase} entry around ${ep:.2f}"]
                if stop_price and stop_price > 0:
                    plan_parts.append(f"stop at ${float(stop_price):.2f}")
                if target_price and target_price > 0:
                    plan_parts.append(f"target ${float(target_price):.2f}")
                if risk_reward and risk_reward > 0:
                    plan_parts.append(f"{float(risk_reward):.1f}R potential")
                hold = "intraday" if (trade_type or "").lower() == "scalp" else (
                    "multi-day swing" if (trade_type or "").lower() == "swing" else
                    "multi-week position" if (trade_type or "").lower() == "position" else
                    f"{trade_type.lower()}" if trade_type else ""
                )
                if hold:
                    # Grammar: "intraday" is adverbial ("holding intraday")
                    # while "multi-day swing" / "day trade" are nouns
                    # ("holding it as a multi-day swing").
                    if hold in ("intraday",):
                        plan_parts.append(f"holding {hold}")
                    else:
                        plan_parts.append(f"holding it as a {hold}")
                if timeframe:
                    plan_parts.append(f"reading off the {timeframe} chart")
                plan = " " + ", ".join(plan_parts) + "."
        except Exception:
            plan = ""

        narrative = f"{saw_clause}{why}{quality}{track_record}{plan}".strip()
        return narrative

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

        # trading_phase — derived directly using US Eastern time. Same logic
        # as `/api/market-context/session/status` router, inlined here so we
        # don't depend on the router module being importable during startup.
        trading_phase: Optional[str] = None
        try:
            import pytz
            et = pytz.timezone("US/Eastern")
            now_et = datetime.now(et)
            is_weekend = now_et.weekday() >= 5
            pre_open = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
            rth_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            rth_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            after_end = now_et.replace(hour=20, minute=0, second=0, microsecond=0)
            if is_weekend:
                trading_phase = "WEEKEND"
            elif now_et < pre_open:
                trading_phase = "OVERNIGHT"
            elif now_et < rth_open:
                trading_phase = "PRE-MARKET"
            elif now_et < rth_close:
                trading_phase = "MARKET OPEN"
            elif now_et < after_end:
                trading_phase = "AFTER-HOURS"
            else:
                trading_phase = "CLOSED"
        except Exception as e:
            logger.debug(f"trading_phase derivation failed: {e}")

        # account_equity — prefer pushed IB net_liq (real-time), fall back
        # to starting_capital + daily net_pnl so the HUD shows *something*
        # even before the first quote pump completes after a reconnect.
        account_equity: Optional[float] = None
        try:
            from routers.ib import _pushed_ib_data
            acct = _pushed_ib_data.get("account") or {}
            nl = acct.get("net_liquidation") or acct.get("NetLiquidation") or acct.get("equity")
            if nl is not None:
                account_equity = float(nl)
        except Exception:
            pass
        if account_equity is None and trading_bot:
            try:
                bot_status = trading_bot.get_status()
                rp = bot_status.get("risk_params") or {}
                ds = bot_status.get("daily_stats") or {}
                sc = rp.get("starting_capital")
                np = ds.get("net_pnl")
                if sc is not None:
                    account_equity = float(sc) + float(np or 0.0)
            except Exception:
                pass

        # scanner_bar_size / scanner_universe_size — read from enhanced scanner
        scanner_bar_size: Optional[str] = None
        scanner_universe_size: Optional[int] = None
        try:
            from services.enhanced_scanner import get_enhanced_scanner
            scanner = get_enhanced_scanner()
            if scanner:
                # `_watchlist` is the live universe set — stable attribute used
                # by the scanner's own get_status() for `watchlist_size`.
                wl = getattr(scanner, "_watchlist", None)
                if isinstance(wl, (list, set, tuple, dict)):
                    scanner_universe_size = len(wl)
                # Enhanced scanner runs across every enabled setup's native
                # timeframe — not a single bar_size. Label as "multi" so the
                # HUD renders something meaningful instead of "—".
                scanner_bar_size = "multi"
        except Exception as e:
            logger.debug(f"scanner enrichment failed: {e}")

        return SentComStatus(
            connected=connected,
            state=state,
            regime=regime,
            positions_count=positions_count,
            watching_count=watching_count,
            pending_orders=pending,
            executing_orders=executing,
            filled_orders=filled,
            last_activity=datetime.now(timezone.utc).isoformat(),
            trading_phase=trading_phase,
            account_equity=account_equity,
            scanner_bar_size=scanner_bar_size,
            scanner_universe_size=scanner_universe_size,
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

                    # 2026-04-28 — operator preference: more wordy / more
                    # conversational copy so it's clear what the bot is
                    # thinking and doing. Replaces the terse single-line
                    # "RS LEADER NVDA +6.8% vs SPY - Outperforming market — TQS 51 (C)"
                    # with a 2-3 sentence narrative that surfaces what
                    # the bot saw, why it cares, and the trade plan.
                    content = self._compose_conversational_setup_narrative(
                        symbol=symbol,
                        setup_display=setup_display,
                        setup_name=setup_name,
                        headline=headline,
                        direction=direction,
                        score=score,
                        tqs_grade=tqs_grade,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_price=target_price,
                        risk_reward=risk_reward,
                        win_rate=win_rate,
                        profit_factor=profit_factor,
                        trade_type=trade_type,
                        timeframe=timeframe,
                        reasoning_list=reasoning_list,
                    )
                    
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
        # 7. AFTER-HOURS MODE - Daily setups, session recap, portfolio review
        # =====================================================================
        try:
            from zoneinfo import ZoneInfo
            ny_now = datetime.now(ZoneInfo("America/New_York"))
            market_open = ny_now.hour * 60 + ny_now.minute >= 570  # 9:30 AM
            market_close = ny_now.hour * 60 + ny_now.minute >= 960  # 4:00 PM
            is_weekend = ny_now.weekday() >= 5
            is_after_hours = is_weekend or not market_open or market_close
            
            if is_after_hours:
                non_chat = [m for m in messages if m.type != 'chat']
                
                # After-hours status message
                if is_weekend:
                    session_label = "Weekend"
                elif not market_open:
                    # Check if pre-market (7:00-9:30)
                    is_premarket = ny_now.hour >= 7 and not is_weekend
                    session_label = "Pre-market" if is_premarket else "Pre-market (early)"
                else:
                    session_label = "After-hours"
                
                if session_label.startswith("Pre-market") and ny_now.hour >= 7:
                    # Pre-market mode: show opening trade prep
                    messages.append(SentComMessage(
                        id=self._generate_message_id(),
                        type="system",
                        content=f"Pre-market — building morning watchlist: gaps, ORB candidates, opening drives",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        confidence=70,
                        action_type="market_status",
                        metadata={"source": "sentcom_system", "session": "premarket"}
                    ))
                    
                    # Show pre-market alerts (gap plays, ORB candidates)
                    try:
                        from services.enhanced_scanner import get_enhanced_scanner
                        scanner = get_enhanced_scanner()
                        if scanner:
                            pm_alerts = [a for a in scanner.get_live_alerts()
                                        if getattr(a, 'id', '').startswith('pm_')]
                            for alert in pm_alerts[:10]:
                                symbol = getattr(alert, 'symbol', '')
                                setup = getattr(alert, 'setup_type', '')
                                price = getattr(alert, 'trigger_price', 0)
                                reasoning = getattr(alert, 'reasoning', '')
                                messages.append(SentComMessage(
                                    id=self._generate_message_id(),
                                    type="alert",
                                    content=f"{symbol} {setup.replace('_', ' ').title()} @ ${price:.2f} — {reasoning[:80]}",
                                    timestamp=getattr(alert, 'timestamp', datetime.now(timezone.utc)).isoformat() if hasattr(getattr(alert, 'timestamp', None), 'isoformat') else datetime.now(timezone.utc).isoformat(),
                                    confidence=70,
                                    symbol=symbol,
                                    action_type="premarket_setup",
                                    metadata={
                                        "source": "premarket_scanner",
                                        "setup_type": setup,
                                        "trigger_price": price,
                                    }
                                ))
                    except Exception as e:
                        logger.debug(f"Pre-market alerts error: {e}")
                else:
                    # After-hours or weekend: daily chart scanning mode
                    messages.append(SentComMessage(
                        id=self._generate_message_id(),
                        type="system",
                        content=f"{session_label} — scanning daily charts for swing and position setups",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        confidence=60,
                        action_type="market_status",
                        metadata={"source": "sentcom_system", "session": session_label.lower()}
                    ))
                
                # Session recap from bot trades (applies to all after-hours modes)
                if trading_bot:
                    try:
                        daily_stats = trading_bot._daily_stats if hasattr(trading_bot, '_daily_stats') else {}
                        trades_today = daily_stats.get("trades_executed", 0)
                        wins = daily_stats.get("trades_won", 0)
                        losses = daily_stats.get("trades_lost", 0)
                        net_pnl = daily_stats.get("net_pnl", 0)
                        
                        if trades_today > 0:
                            win_rate = (wins / trades_today * 100) if trades_today > 0 else 0
                            messages.append(SentComMessage(
                                id=self._generate_message_id(),
                                type="thought",
                                content=f"Today's session: {trades_today} trades, {wins}W/{losses}L ({win_rate:.0f}% WR), net P&L: ${net_pnl:+,.0f}",
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                confidence=85,
                                action_type="session_recap",
                                metadata={"source": "trading_bot", "trades": trades_today, "pnl": net_pnl}
                            ))
                        
                        # Portfolio review — flag positions at risk
                        open_trades = trading_bot.get_open_trades() if hasattr(trading_bot, 'get_open_trades') else []
                        if isinstance(open_trades, list) and len(open_trades) > 0:
                            messages.append(SentComMessage(
                                id=self._generate_message_id(),
                                type="thought",
                                content=f"Monitoring {len(open_trades)} open positions overnight",
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                confidence=70,
                                action_type="portfolio_review",
                                metadata={"source": "trading_bot", "open_count": len(open_trades)}
                            ))
                            
                            # Highlight any positions with tight stops
                            for trade in open_trades[:3]:
                                stop = trade.get("stop_price")
                                current = trade.get("current_price", 0)
                                symbol = trade.get("symbol", "")
                                if stop and current and current > 0:
                                    dist_pct = abs(current - stop) / current * 100
                                    if dist_pct < 3:
                                        messages.append(SentComMessage(
                                            id=self._generate_message_id(),
                                            type="risk",
                                            content=f"{symbol} stop at ${stop:.2f} — only {dist_pct:.1f}% away from current ${current:.2f}",
                                            timestamp=datetime.now(timezone.utc).isoformat(),
                                            confidence=80,
                                            symbol=symbol,
                                            action_type="stop_proximity",
                                            metadata={"source": "portfolio_review", "stop_distance_pct": dist_pct}
                                        ))
                    except Exception as e:
                        logger.debug(f"Session recap error: {e}")
                
                # Show swing/position alerts from daily scanner
                try:
                    from services.enhanced_scanner import get_enhanced_scanner
                    scanner = get_enhanced_scanner()
                    if scanner:
                        daily_alerts = [a for a in scanner.get_live_alerts() 
                                       if getattr(a, 'scan_tier', '') in ('swing', 'position', 'SWING', 'POSITION')]
                        for alert in daily_alerts[:8]:
                            symbol = getattr(alert, 'symbol', '')
                            setup = getattr(alert, 'setup_type', '')
                            price = getattr(alert, 'trigger_price', 0)
                            tier = getattr(alert, 'scan_tier', 'swing')
                            messages.append(SentComMessage(
                                id=self._generate_message_id(),
                                type="alert",
                                content=f"Daily setup: {symbol} {setup.replace('_', ' ').title()} @ ${price:.2f}",
                                timestamp=getattr(alert, 'timestamp', datetime.now(timezone.utc)).isoformat() if hasattr(getattr(alert, 'timestamp', None), 'isoformat') else datetime.now(timezone.utc).isoformat(),
                                confidence=65,
                                symbol=symbol,
                                action_type="daily_setup",
                                metadata={
                                    "source": "daily_scanner",
                                    "setup_type": setup,
                                    "trigger_price": price,
                                    "timeframe": tier,
                                }
                            ))
                except Exception as e:
                    logger.debug(f"After-hours daily alerts error: {e}")
        except Exception as e:
            logger.debug(f"After-hours mode error: {e}")
        
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
        
        # Accumulate into stream buffer — add new messages, keep old ones
        for msg in messages:
            # Dedup key: type + symbol + first 40 chars of content
            dedup_key = f"{msg.type}:{msg.symbol or ''}:{msg.content[:40]}"
            if dedup_key not in self._stream_seen_keys:
                self._stream_seen_keys.add(dedup_key)
                self._stream_buffer.append(msg)
        
        # Sort entire buffer by timestamp — newest first
        self._stream_buffer.sort(key=lambda m: m.timestamp, reverse=True)
        
        # Trim buffer to max size (remove oldest)
        if len(self._stream_buffer) > self._stream_max_size:
            removed = self._stream_buffer[self._stream_max_size:]
            self._stream_buffer = self._stream_buffer[:self._stream_max_size]
            for r in removed:
                key = f"{r.type}:{r.symbol or ''}:{r.content[:40]}"
                self._stream_seen_keys.discard(key)
        
        return self._stream_buffer[:limit]
    
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

            # Inject recent bot thoughts/decisions so the AI can recall
            # "what we were doing" — bridges the gap between the user's
            # question and the bot's recent activity. Pulls top 12 thoughts
            # from the last 4 hours (covers a full RTH session). The
            # orchestrator's chat_history accepts arbitrary role values;
            # we use "system" so the LLM treats it as background context.
            try:
                recent_thoughts = get_recent_thoughts(minutes=240, limit=12)
                if recent_thoughts:
                    summary_lines = []
                    for t in reversed(recent_thoughts):  # chronological
                        sym = t.get("symbol") or ""
                        kind = t.get("kind") or "thought"
                        text = (t.get("content") or "").strip()
                        if not text:
                            continue
                        prefix = f"[{kind}{' ' + sym if sym else ''}]"
                        summary_lines.append(f"{prefix} {text}")
                    if summary_lines:
                        recent_history.insert(0, {
                            "role": "system",
                            "content": (
                                "Recent bot activity (most recent last) — use this "
                                "to ground answers about what we were thinking / "
                                "doing:\n" + "\n".join(summary_lines[-12:])
                            ),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
            except Exception as _e:
                logger.debug(f"recent-thoughts injection skipped: {_e}")

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
    
    @staticmethod
    def _classify_source_v19_27(
        symbol: str,
        direction: str,
        bot_total: int,
        ib_pos_by_symbol: Dict[str, Dict[str, Any]],
    ) -> str:
        """v19.27 — Classify a position row's `source` based on share-
        count reconciliation between bot's `_open_trades` peer-sum and
        IB's net position. See `get_our_positions` docstring for the
        full motivation.

        Returns one of:
          'bot'        — clean tracking (bot total matches IB net)
          'partial'    — bot tracks SOME of the IB position; the rest
                         is unclaimed and renders as a separate orphan
                         row in the IB-position loop below
          'stale_bot'  — bot tracks MORE than IB shows; phantom shares
                         that the auto-sweep loop in position_manager
                         (Fix 3) will close on the next manage cycle
          'ib'         — IB has shares, bot has none (true orphan,
                         Reconcile button counts these)
        """
        sym_upper = (symbol or "").upper()
        dir_lower = (direction or "long").lower()
        ib = ib_pos_by_symbol.get(sym_upper)
        if not ib:
            # Bot tracks but IB doesn't → phantom shares to be swept.
            return "stale_bot" if (bot_total or 0) > 0 else "bot"
        if ib.get("direction") != dir_lower:
            # Direction mismatch — bot still has its long while IB is
            # short (or vice versa). Treat as stale on the bot side;
            # the IB row will render separately as an orphan in the
            # IB-position loop with its own direction.
            return "stale_bot"
        ib_qty = int(ib.get("abs_qty", 0))
        bot_qty = int(bot_total or 0)
        # Tolerate ±1 share rounding noise (extremely rare but harmless).
        if abs(bot_qty - ib_qty) <= 1:
            return "bot"
        if bot_qty < ib_qty:
            return "partial"
        return "stale_bot"

    async def get_our_positions(self) -> List[Dict[str, Any]]:
        """Get our current positions with P&L from both Trading Bot and IB.
        
        Returns enriched position data including:
        - market_value, cost_basis, portfolio_weight
        - risk_level (ok/warning/danger/critical based on drawdown)
        - today_change data from IB quotes when available

        v19.27 (2026-05-01) — Smart source detection. Pre-v19.27 the
        source field was binary ("bot" if symbol in `_open_trades`
        else "ib"). After many bot fills + scale-outs + restarts, this
        misclassified the share-count drift between the bot's
        `_open_trades` total and IB's net position. Now sourced via
        share-count reconciliation:
          - bot_shares == 0  AND  ib_shares > 0    → 'ib'         (true orphan)
          - bot_shares == ib_shares                 → 'bot'        (clean)
          - bot_shares < ib_shares                  → 'partial'    + an extra
                                                     orphan row for the remainder
          - bot_shares > ib_shares                  → 'stale_bot'  (phantom shares)
        Reconcile button counts true orphans + the unclaimed remainder
        of partial cases. `stale_bot` triggers a separate sweep
        affordance (Fix 3 auto-sweep handles it on the manage loop).
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

        # v19.27 — pre-build a (symbol, abs_qty, direction) map of IB
        # positions so each bot-trade row can flag whether its shares
        # match IB or are part of a larger / smaller IB net. This drives
        # the smart `source` field below.
        ib_pos_by_symbol: dict = {}
        # v19.34.2 (2026-05-04) — also collect per-quote `pushed_at` /
        # `as_of` timestamps so we can stamp each row with `quote_age_s`
        # + `quote_state` (fresh / amber / stale). Lets the V5 UI show
        # a Quote-Freshness chip per row instead of just "STALE" when
        # we cross the 30s line.
        quote_meta_by_symbol: dict = {}
        try:
            from routers.ib import _pushed_ib_data
            from datetime import datetime as _dt2, timezone as _tz2
            _now_utc = _dt2.now(_tz2.utc)
            for _ip in (_pushed_ib_data.get("positions") or []):
                _sym = (_ip.get("symbol") or "").upper()
                if not _sym:
                    continue
                _qty = float(_ip.get("position", _ip.get("qty", 0)) or 0)
                if abs(_qty) < 0.001:
                    continue
                ib_pos_by_symbol[_sym] = {
                    "qty": _qty,
                    "direction": "long" if _qty > 0 else "short",
                    "abs_qty": int(abs(_qty)),
                    "avg_cost": float(_ip.get("avgCost", _ip.get("avg_cost", 0)) or 0),
                    "market_price": float(_ip.get("marketPrice", _ip.get("market_price", 0)) or 0),
                }
            # v19.34.2 — quote-age computation per symbol, mirrors the
            # logic in position_manager.update_open_positions.
            _quotes_dict = _pushed_ib_data.get("quotes") or {}
            for _sym_q, _q in _quotes_dict.items():
                if not isinstance(_q, dict):
                    continue
                _q_ts_raw = (
                    _q.get("pushed_at")
                    or _q.get("as_of")
                    or _q.get("timestamp")
                    or _q.get("ts")
                )
                _age_s: Optional[float] = None
                if _q_ts_raw is not None:
                    try:
                        if isinstance(_q_ts_raw, (int, float)):
                            # Heuristic: > 1e12 → ms epoch; > 1e9 → s epoch.
                            _ts_f = float(_q_ts_raw)
                            if _ts_f > 1e12:
                                _ts_f = _ts_f / 1000.0
                            _age_s = _now_utc.timestamp() - _ts_f
                        else:
                            _norm = str(_q_ts_raw)
                            if _norm.endswith("Z"):
                                _norm = _norm[:-1] + "+00:00"
                            _dt_q = _dt2.fromisoformat(_norm)
                            if _dt_q.tzinfo is None:
                                _dt_q = _dt_q.replace(tzinfo=_tz2.utc)
                            _age_s = (_now_utc - _dt_q).total_seconds()
                    except Exception:
                        _age_s = None
                _state = (
                    "fresh" if _age_s is not None and _age_s < 5.0 else
                    "amber" if _age_s is not None and _age_s < 30.0 else
                    "stale" if _age_s is not None else
                    "unknown"
                )
                quote_meta_by_symbol[(_sym_q or "").upper()] = {
                    "quote_age_s": (round(_age_s, 1) if _age_s is not None else None),
                    "quote_state": _state,
                }
        except Exception:
            pass

        # v19.27 — sum bot _open_trades shares per (symbol, direction)
        # so each bot row knows its peer-sum and we can compute the
        # partial / stale_bot / clean cases below.
        bot_shares_by_symbol: dict = {}
        if trading_bot:
            try:
                _all_open = trading_bot.get_open_trades() or []
                for _t in _all_open:
                    _sym = (_t.get("symbol") or "").upper()
                    _dir = (_t.get("direction") or "long").lower()
                    if not _sym:
                        continue
                    rs = _t.get("remaining_shares")
                    if rs in (None, 0):
                        rs = _t.get("shares") or 0
                    key = (_sym, _dir)
                    bot_shares_by_symbol[key] = bot_shares_by_symbol.get(key, 0) + int(abs(rs or 0))
            except Exception as e:
                logger.debug(f"v19.27 bot_shares aggregation failed: {e}")
        
        # First, get bot-managed trades (these have more detailed tracking)
        # v19.34.1 (2026-05-04) — best-effort current pusher account
        # so legacy bot_trades rows that pre-date the v19.31.13
        # trade_type stamping (or reconciled-orphan rows that pre-date
        # v19.34.1) get a chip on the UI without a DB rewrite. Read once
        # per request to avoid hammering the pusher RPC on every row.
        # Defined at outer scope so BOTH the bot-managed loop AND the
        # IB-orphan / lazy-reconcile branch can fall back to it.
        _legacy_trade_type = None
        _legacy_account_id = None
        try:
            from services.account_guard import classify_account_id as _classify
            from services.ib_pusher_rpc import get_account_snapshot as _gas
            _snap = _gas()
            _legacy_account_id = (_snap or {}).get("account_id") or None
            if _legacy_account_id:
                _legacy_trade_type = _classify(_legacy_account_id)
        except Exception:
            _legacy_trade_type = None

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
                        # 2026-05-01 v19.22.3 — ALWAYS prefer the fresh
                        # pushed quote over `trade.current_price`. Operator
                        # caught the bug when 4 brand-new bracket fills
                        # showed +$0 P&L while legacy positions ticked
                        # normally. Cause: position_manager.update_open_
                        # positions runs on a timer and hadn't refreshed
                        # `trade.current_price` for symbols that just
                        # filled. The pusher's quote stream is already
                        # subscribed (via PusherRotation pinning), so the
                        # quote is HERE — we just weren't using it.
                        symbol_for_quote = (trade.get("symbol") or "").upper()
                        live_quote = ib_quotes.get(symbol_for_quote, {}) if symbol_for_quote else {}
                        live_price = live_quote.get("last") or live_quote.get("close")
                        if live_price and float(live_price) > 0:
                            current = float(live_price)
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
                        
                        # 2026-05-04 v19.31 — realized R-multiple for the
                        # MANAGE HUD aggregator. Operator caught the HUD
                        # reading +0.0R while LITE alone was +12R because
                        # this field was never populated. Compute it from
                        # pnl / risk_amount (the dollar risk locked in at
                        # entry: shares × |entry − stop|). risk_amount
                        # may be 0 for half-broken legacy trades; in that
                        # case fall back to recomputing from stop_price.
                        risk_amt_for_r = float(trade.get("risk_amount") or 0)
                        if risk_amt_for_r <= 0:
                            stop_for_r = trade.get("stop_price") or 0
                            if entry and stop_for_r and shares:
                                risk_amt_for_r = abs(float(entry) - float(stop_for_r)) * abs(float(shares))
                        pnl_r_value = (pnl / risk_amt_for_r) if risk_amt_for_r > 0 else None

                        positions.append({
                            "symbol": symbol,
                            "shares": shares,
                            "direction": direction,
                            "entry_price": entry,
                            "current_price": current,
                            "pnl": round(pnl, 2),
                            "pnl_percent": round(pnl_pct, 2),
                            # v19.31 — realized R for the manage HUD.
                            "pnl_r": round(pnl_r_value, 3) if pnl_r_value is not None else None,
                            "unrealized_r": round(pnl_r_value, 3) if pnl_r_value is not None else None,
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
                            # v19.27 — smart source detection. Default
                            # 'bot' for clean tracking; if peer-sum
                            # disagrees with IB net, downgrade to
                            # 'partial' or 'stale_bot' so the V5 chip
                            # can render an explicit drift badge.
                            "source": self._classify_source_v19_27(
                                symbol=symbol,
                                direction=direction,
                                bot_total=bot_shares_by_symbol.get(
                                    ((symbol or "").upper(), (direction or "long").lower()), 0
                                ),
                                ib_pos_by_symbol=ib_pos_by_symbol,
                            ),
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
                            # 2026-05-01 v19.22.3 — operator wants rich
                            # detail visible per position: scan tier, time
                            # horizon, why-the-bot-took-it, plan A/B,
                            # current management state. Backend already
                            # has all of this on the BotTrade record; we
                            # were just dropping it on the way out.
                            "scan_tier": trade.get("entry_context", {}).get("scan_tier")
                                          or trade.get("scan_tier")
                                          or trade.get("timeframe", "intraday"),
                            "estimated_duration": trade.get("estimated_duration", ""),
                            "tape_score": trade.get("tape_score", 0),
                            "smb_is_a_plus": trade.get("entry_context", {}).get("smb_is_a_plus", False),
                            "exit_rule": trade.get("entry_context", {}).get("exit_rule", ""),
                            "trading_approach": trade.get("entry_context", {}).get("trading_approach", ""),
                            "reasoning": trade.get("entry_context", {}).get("reasoning", []),
                            # Scale-out + trailing-stop state — what the
                            # bot is actively MANAGING right now.
                            "scale_out_state": {
                                "enabled": (trade.get("scale_out_config") or {}).get("enabled", False),
                                "targets_hit": (trade.get("scale_out_config") or {}).get("targets_hit", []),
                                "partial_exits": (trade.get("scale_out_config") or {}).get("partial_exits", []),
                            },
                            "trailing_stop_state": {
                                "enabled": (trade.get("trailing_stop_config") or {}).get("enabled", False),
                                "mode": (trade.get("trailing_stop_config") or {}).get("mode", "original"),
                                "current_stop": (trade.get("trailing_stop_config") or {}).get("current_stop", 0.0),
                                "high_water_mark": (trade.get("trailing_stop_config") or {}).get("high_water_mark", 0.0),
                                "low_water_mark": (trade.get("trailing_stop_config") or {}).get("low_water_mark", 0.0),
                            },
                            # Risk math the operator wants at-a-glance
                            "risk_amount": trade.get("risk_amount", 0),
                            "risk_reward_ratio": trade.get("risk_reward_ratio", 0),
                            "potential_reward": trade.get("potential_reward", 0),
                            "remaining_shares": trade.get("remaining_shares", shares),
                            "original_shares": trade.get("original_shares", shares),
                            "regime_score": trade.get("regime_score", 0),
                            # v19.31.13 — trade origin classification so V5 UI
                            # can render PAPER (amber) / LIVE (red) / SHADOW
                            # (sky) chips per row. Stamped at execution time
                            # by trade_execution.execute_trade.
                            # v19.34.1 — fall back to the current pusher
                            # account when the row's stamp is missing or
                            # "unknown" (legacy bot_trades / pre-stamping
                            # reconciled orphans). The pusher's account is
                            # the same account this position lives on, so
                            # the chip is correct on the UI even though
                            # we don't rewrite the DB.
                            "trade_type": (
                                trade.get("trade_type")
                                if (trade.get("trade_type") and trade.get("trade_type") != "unknown")
                                else (_legacy_trade_type or "unknown")
                            ),
                            "account_id_at_fill": (
                                trade.get("account_id_at_fill")
                                or _legacy_account_id
                            ),
                            # v19.34.2 — per-row quote freshness so the V5
                            # UI can render a fresh / amber / stale chip.
                            "quote_age_s": (
                                quote_meta_by_symbol.get(symbol.upper(), {}).get("quote_age_s")
                            ),
                            "quote_state": (
                                quote_meta_by_symbol.get(symbol.upper(), {}).get("quote_state")
                                or "unknown"
                            ),
                        })
            except Exception as e:
                logger.error(f"Error getting bot positions: {e}")
        
        # Then, get IB positions from pushed data
        try:
            from routers.ib import _pushed_ib_data
            ib_positions = _pushed_ib_data.get("positions", [])
            
            for pos in ib_positions:
                symbol = pos.get("symbol")
                if not symbol:
                    continue

                # v19.27 — share-count reconciliation. The bot may
                # already have a row for this symbol (clean tracking,
                # OR `partial` where bot tracks fewer shares than IB
                # net). In the partial case we still want to emit an
                # extra orphan row for the *unclaimed remainder* so
                # the operator can see + reconcile the missing shares.
                ib_qty_raw = float(pos.get("position", 0) or 0)
                if abs(ib_qty_raw) < 0.001:
                    continue
                ib_dir = "long" if ib_qty_raw > 0 else "short"
                ib_abs = int(abs(ib_qty_raw))
                bot_total_for_dir = bot_shares_by_symbol.get(
                    (symbol.upper(), ib_dir), 0
                )

                # Already-tracked + matches IB cleanly → bot row covers it.
                if bot_total_for_dir > 0 and abs(bot_total_for_dir - ib_abs) <= 1:
                    seen_symbols.add(symbol)
                    continue

                # `stale_bot` (bot tracks MORE than IB) → bot row is
                # already present and the auto-sweep loop will handle
                # cleanup. Skip emitting an IB-side row.
                if bot_total_for_dir > ib_abs:
                    seen_symbols.add(symbol)
                    continue

                # Either: pure orphan (bot tracks 0) → render full
                # IB position. Or: partial drift (bot tracks SOME) →
                # render an orphan row for the UNCLAIMED REMAINDER so
                # the operator sees + reconciles the gap.
                if bot_total_for_dir > 0:
                    orphan_shares_signed = ib_qty_raw - (
                        bot_total_for_dir if ib_qty_raw > 0 else -bot_total_for_dir
                    )
                else:
                    orphan_shares_signed = ib_qty_raw

                shares = orphan_shares_signed
                if symbol and symbol not in seen_symbols:
                    avg_cost = pos.get("avgCost", 0) or pos.get("avg_cost", 0)
                    market_price = pos.get("marketPrice", 0) or pos.get("market_price", 0)
                    unrealized_pnl_full = pos.get("unrealizedPnL") or pos.get("unrealizedPNL") or pos.get("unrealized_pnl")
                    realized_pnl = pos.get("realizedPnL") or pos.get("realizedPNL") or pos.get("realized_pnl") or 0

                    # Pro-rate IB's unrealized P&L to ONLY the orphan
                    # remainder so we don't double-count the bot row's
                    # P&L and the orphan row's P&L.
                    if bot_total_for_dir > 0 and ib_abs > 0:
                        ratio = abs(shares) / ib_abs
                    else:
                        ratio = 1.0

                    if unrealized_pnl_full is None and market_price and avg_cost and shares:
                        unrealized_pnl = (market_price - avg_cost) * shares
                    else:
                        unrealized_pnl = (unrealized_pnl_full or 0) * ratio
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
                    
                    # 2026-05-01 v19.23.1 — Lazy-reconcile SL/TP for
                    # untracked IB-only positions. When the bot
                    # restarted (or operator inherited a position), the
                    # IB position has no bot_trade record, so the V5 UI
                    # was rendering STOP — / TARGET — and the chart
                    # priceLines effect couldn't draw red/green lines.
                    # We look in Mongo `bot_trades` for the most recent
                    # OPEN trade matching this symbol — the operator's
                    # bot logged stop_price + target_prices when it
                    # placed the original bracket. Fall back to the
                    # most recent CLOSED trade so even fully-orphaned
                    # positions show the operator's last-known
                    # protective levels.
                    enrich_stop = None
                    enrich_targets = []
                    enrich_trade = None
                    try:
                        db = _get_db()
                        if db is not None:
                            # Prefer status=open / placed; fall back to
                            # any trade on this symbol within the last
                            # 30d so the operator at least sees the
                            # bot's intended levels.
                            from datetime import timedelta as _td
                            cutoff = datetime.now(timezone.utc) - _td(days=30)
                            doc = await asyncio.to_thread(
                                lambda: db["bot_trades"].find_one(
                                    {
                                        "symbol": symbol,
                                        "$or": [
                                            {"status": "open"},
                                            {"status": "placed"},
                                            {"executed_at": {"$gte": cutoff}},
                                        ],
                                    },
                                    {"_id": 0},
                                    sort=[("executed_at", -1)],
                                )
                            )
                            if doc:
                                enrich_stop = doc.get("stop_price")
                                _t = doc.get("target_prices") or []
                                if isinstance(_t, list):
                                    enrich_targets = [float(t) for t in _t if t is not None]
                                elif doc.get("target_price"):
                                    enrich_targets = [float(doc["target_price"])]
                                enrich_trade = doc
                    except Exception as _e:
                        logger.debug(f"Lazy-reconcile failed for {symbol}: {_e}")

                    # 2026-05-04 v19.31 — same realized R-multiple logic
                    # for IB-orphan / lazy-reconciled positions. Uses the
                    # enriched stop_price from `bot_trades` if present.
                    risk_amt_for_r_orphan = float((enrich_trade or {}).get("risk_amount") or 0)
                    if risk_amt_for_r_orphan <= 0 and enrich_stop and avg_cost and abs_shares:
                        risk_amt_for_r_orphan = abs(float(avg_cost) - float(enrich_stop)) * abs(float(abs_shares))
                    pnl_r_orphan = (
                        unrealized_pnl / risk_amt_for_r_orphan
                        if risk_amt_for_r_orphan > 0
                        else None
                    )

                    positions.append({
                        "symbol": symbol,
                        "shares": abs_shares,
                        "direction": position_type,
                        "entry_price": avg_cost,
                        "current_price": current,
                        "pnl": round(unrealized_pnl, 2),
                        "pnl_percent": round(pnl_pct, 2),
                        # v19.31 — realized R for the manage HUD.
                        "pnl_r": round(pnl_r_orphan, 3) if pnl_r_orphan is not None else None,
                        "unrealized_r": round(pnl_r_orphan, 3) if pnl_r_orphan is not None else None,
                        "market_value": round(market_value, 2),
                        "cost_basis": round(cost_basis_val, 2),
                        "realized_pnl": round(realized_pnl, 2),
                        "today_change": round(today_change * abs_shares, 2) if today_change else 0,
                        "today_change_pct": round(today_change_pct, 2) if today_change_pct else 0,
                        "risk_level": risk_level,
                        "stop_price": float(enrich_stop) if enrich_stop is not None else None,
                        "target_prices": enrich_targets,
                        "target_price": enrich_targets[0] if enrich_targets else None,
                        "status": "open",
                        "entry_time": (lambda et: et.isoformat() if hasattr(et, "isoformat") else et)(
                            (enrich_trade or {}).get("executed_at")
                        ),
                        "source": "partial" if bot_total_for_dir > 0 else "ib",
                        "reconciled": bool(enrich_trade),
                        # v19.27 — when the orphan row is part of a
                        # `partial` (bot tracks SOME), surface the
                        # share gap so the V5 chip + Reconcile button
                        # render an explicit "13,364sh untracked" hint.
                        "ib_total_shares": ib_abs,
                        "bot_tracked_shares": int(bot_total_for_dir),
                        "unclaimed_shares": int(abs(shares)),
                        "setup_type": (enrich_trade or {}).get("setup_type", ""),
                        "setup_variant": (enrich_trade or {}).get("setup_variant", ""),
                        "trade_style": (enrich_trade or {}).get("trade_style", ""),
                        "scan_tier": (enrich_trade or {}).get("scan_tier", "") or (enrich_trade or {}).get("entry_context", {}).get("scan_tier", ""),
                        "market_regime": (enrich_trade or {}).get("market_regime", ""),
                        "timeframe": (enrich_trade or {}).get("timeframe", ""),
                        "quality_grade": (enrich_trade or {}).get("quality_grade", ""),
                        "smb_grade": (enrich_trade or {}).get("smb_grade", ""),
                        "risk_amount": (enrich_trade or {}).get("risk_amount", 0),
                        "risk_reward_ratio": (enrich_trade or {}).get("risk_reward_ratio", 0),
                        "potential_reward": (enrich_trade or {}).get("potential_reward", 0),
                        "remaining_shares": (enrich_trade or {}).get("remaining_shares", abs_shares),
                        "original_shares": (enrich_trade or {}).get("original_shares", abs_shares),
                        "reasoning": ((enrich_trade or {}).get("entry_context") or {}).get("reasoning", []),
                        "exit_rule": ((enrich_trade or {}).get("entry_context") or {}).get("exit_rule", ""),
                        "trading_approach": ((enrich_trade or {}).get("entry_context") or {}).get("trading_approach", ""),
                        "notes": (enrich_trade or {}).get("notes", ""),
                        # v19.31.13 — trade-type chip for IB-orphans / lazy
                        # reconciled rows. Pulls from the bot_trade lazy-
                        # match doc when present; orphans the bot never
                        # owned land here as `unknown`.
                        # v19.34.1 — fall back to current pusher account
                        # so even un-reconciled IB orphans get a chip.
                        "trade_type": (
                            (enrich_trade or {}).get("trade_type")
                            if ((enrich_trade or {}).get("trade_type")
                                and (enrich_trade or {}).get("trade_type") != "unknown")
                            else (_legacy_trade_type or "unknown")
                        ),
                        "account_id_at_fill": (
                            (enrich_trade or {}).get("account_id_at_fill")
                            or _legacy_account_id
                        ),
                        # v19.34.2 — quote-freshness chip support for
                        # IB-orphan / lazy-reconciled rows.
                        "quote_age_s": (
                            quote_meta_by_symbol.get(symbol.upper(), {}).get("quote_age_s")
                        ),
                        "quote_state": (
                            quote_meta_by_symbol.get(symbol.upper(), {}).get("quote_state")
                            or "unknown"
                        ),
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
                for alert in live_alerts[:10]:
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


# ----------------------------------------------------------------------------
# Module-level stream emitter — push event-driven messages into the unified
# stream buffer from anywhere in the backend (trading_bot, ib router, EOD
# pipeline, etc.). The stream buffer was previously populated only by the
# pull-based `get_unified_stream` poller, which meant safety-blocks, fills,
# and bot-evaluation events were silently dropped (the import existed but
# the function did not, and callers wrapped it in try/except → silent).
#
# 2026-04-29 (afternoon-4): events ALSO persist to the `sentcom_thoughts`
# collection (TTL 7 days). The bot's "thinking trail" — evaluations,
# fills, safety blocks, rejection narratives — survives backend restarts
# AND is queryable for chat context recall ("what did we see on SPY this
# morning?") + future ML training (decision-vs-outcome alignment).
# ----------------------------------------------------------------------------

_VALID_KINDS = {
    "thought", "alert", "filter", "skip", "fill", "rejection",
    "evaluation", "system", "scan", "info", "brain",
}

THOUGHTS_COLLECTION = "sentcom_thoughts"
_THOUGHTS_TTL_DAYS = 7
_thoughts_index_initialised = False


def _ensure_thoughts_indexes():
    """Create indexes on `sentcom_thoughts` once per process. Idempotent.
    `created_at` TTL prunes 7+ day old rows automatically."""
    global _thoughts_index_initialised
    if _thoughts_index_initialised:
        return
    try:
        db = _get_db()
        col = db[THOUGHTS_COLLECTION]
        col.create_index(
            "created_at",
            expireAfterSeconds=_THOUGHTS_TTL_DAYS * 86400,
            name="created_at_ttl",
        )
        col.create_index([("symbol", 1), ("created_at", -1)], name="symbol_recent")
        col.create_index([("kind", 1), ("created_at", -1)], name="kind_recent")
        _thoughts_index_initialised = True
    except Exception as e:
        logger.debug(f"sentcom_thoughts index init skipped: {e}")


async def _persist_thought(msg: "SentComMessage") -> None:
    """Append a thought to `sentcom_thoughts`. Best-effort, never raises.

    2026-05-04 v19.31.5 — normalize symbol to upper-case on write so
    Trail Explorer's case-sensitive lookup hits. Also skip persisting
    rows with empty content (these were causing blank lines in the
    Trail Explorer drilldown).
    """
    # Skip writes for empty/None content — these are dedup sentinels
    # or metadata-only events that have no operator-readable text.
    if not msg.content or not str(msg.content).strip():
        return
    try:
        _ensure_thoughts_indexes()
        db = _get_db()

        sym_norm = (msg.symbol or "").upper() or None

        def _insert():
            db[THOUGHTS_COLLECTION].insert_one({
                "id": msg.id,
                "kind": msg.type,
                "content": msg.content,
                "symbol": sym_norm,
                "action_type": msg.action_type,
                "confidence": msg.confidence,
                "metadata": msg.metadata or {},
                "timestamp": msg.timestamp,
                "created_at": datetime.now(timezone.utc),
            })

        await asyncio.to_thread(_insert)
    except Exception as e:
        logger.debug(f"_persist_thought failed: {e}")


async def emit_stream_event(payload: Dict[str, Any]) -> bool:
    """Append an event-driven message to the SentCom unified stream buffer.

    Args:
        payload: dict with keys
            - kind/type: str (one of _VALID_KINDS — defaults to "thought")
            - text/content: str (the operator-facing line)
            - symbol: optional str
            - event/action_type: optional str (e.g. "safety_block", "fill")
            - confidence: optional int 0-100
            - metadata: optional dict

    Returns:
        True if the event was buffered, False on dedup or invalid input.

    Never raises — callers can fire-and-forget.
    """
    try:
        if not isinstance(payload, dict):
            return False
        text = payload.get("text") or payload.get("content") or ""
        if not text:
            return False

        kind = (payload.get("kind") or payload.get("type") or "thought").lower()
        if kind not in _VALID_KINDS:
            kind = "info"

        symbol = payload.get("symbol")
        action = payload.get("event") or payload.get("action_type")
        meta = payload.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {"raw": str(meta)}
        meta.setdefault("source", "emit_stream_event")

        svc = get_sentcom_service()
        msg = SentComMessage(
            id=svc._generate_message_id() if hasattr(svc, "_generate_message_id")
                else f"evt_{datetime.now(timezone.utc).timestamp()}",
            type=kind,
            content=str(text),
            timestamp=datetime.now(timezone.utc).isoformat(),
            confidence=payload.get("confidence"),
            symbol=symbol,
            action_type=action,
            metadata=meta,
        )

        # Dedup against the same key the pull-based path uses.
        dedup_key = f"{msg.type}:{msg.symbol or ''}:{msg.content[:40]}"
        if dedup_key in svc._stream_seen_keys:
            return False
        svc._stream_seen_keys.add(dedup_key)
        svc._stream_buffer.append(msg)

        # Trim — keep newest first.
        svc._stream_buffer.sort(key=lambda m: m.timestamp, reverse=True)
        if len(svc._stream_buffer) > svc._stream_max_size:
            removed = svc._stream_buffer[svc._stream_max_size:]
            svc._stream_buffer = svc._stream_buffer[:svc._stream_max_size]
            for r in removed:
                key = f"{r.type}:{r.symbol or ''}:{r.content[:40]}"
                svc._stream_seen_keys.discard(key)

        # Persist to MongoDB so thoughts/decisions survive restarts and
        # can be recalled for chat context + ML training. Fire-and-forget
        # — never blocks the caller, never raises.
        try:
            asyncio.create_task(_persist_thought(msg))
        except RuntimeError:
            # No running loop (called from sync context) — skip persistence
            # quietly. The in-memory buffer still has it.
            pass

        return True
    except Exception as e:
        logger.debug(f"emit_stream_event failed: {e}")
        return False


def get_recent_thoughts(
    *,
    symbol: Optional[str] = None,
    kind: Optional[str] = None,
    minutes: int = 240,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """Recall recent persisted thoughts for chat context / ML training.

    Args:
        symbol: filter to a specific ticker (optional)
        kind: filter to a specific event kind (optional, e.g. "evaluation",
            "fill", "skip")
        minutes: how far back to look. Default 4h covers a full RTH session.
        limit: max rows returned.

    Returns rows newest-first, with `_id` excluded.
    Never raises — returns [] on any failure.
    """
    try:
        db = _get_db()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(minutes or 240))
        q: Dict[str, Any] = {"created_at": {"$gte": cutoff}}
        if symbol:
            q["symbol"] = str(symbol).upper()
        if kind:
            q["kind"] = str(kind).lower()
        cursor = (
            db[THOUGHTS_COLLECTION]
            .find(q, {"_id": 0})
            .sort("created_at", DESCENDING)
            .limit(int(limit or 30))
        )
        rows = list(cursor)
        # Convert datetime to ISO so the caller can JSON-serialise freely.
        for r in rows:
            ca = r.get("created_at")
            if isinstance(ca, datetime):
                r["created_at"] = ca.isoformat()
        return rows
    except Exception as e:
        logger.debug(f"get_recent_thoughts failed: {e}")
        return []
