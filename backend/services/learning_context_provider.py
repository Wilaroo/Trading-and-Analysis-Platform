"""
Learning Context Provider - Integrates TQS and Learning Insights into AI Prompts

This service provides personalized trading context from:
- TQS Engine: Real-time trade quality scores
- Medium Learning: Context performance, edge decay alerts
- Weekly Reports: Recent performance summaries
- RAG: Personalized historical patterns

Used by the AI Assistant to give contextually aware coaching.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class LearningContextProvider:
    """
    Aggregates learning insights for AI prompt injection.
    
    This service connects:
    - TQS scores for current setups
    - Context performance data (your win rates by setup+regime+time)
    - Edge decay alerts
    - Calibration recommendations
    - Confirmation signal effectiveness
    - RAG retrieval for similar past trades
    """
    
    def __init__(self):
        self._db = None
        
        # Service references
        self._tqs_engine = None
        self._calibration_service = None
        self._context_performance_service = None
        self._confirmation_validator_service = None
        self._edge_decay_service = None
        self._rag_service = None
        self._playbook_performance_service = None
        
    def set_db(self, db):
        """Set database connection"""
        self._db = db
        
    def set_services(
        self,
        tqs_engine=None,
        calibration_service=None,
        context_performance_service=None,
        confirmation_validator_service=None,
        edge_decay_service=None,
        rag_service=None,
        playbook_performance_service=None
    ):
        """Wire up all learning services"""
        if tqs_engine:
            self._tqs_engine = tqs_engine
        if calibration_service:
            self._calibration_service = calibration_service
        if context_performance_service:
            self._context_performance_service = context_performance_service
        if confirmation_validator_service:
            self._confirmation_validator_service = confirmation_validator_service
        if edge_decay_service:
            self._edge_decay_service = edge_decay_service
        if rag_service:
            self._rag_service = rag_service
        if playbook_performance_service:
            self._playbook_performance_service = playbook_performance_service
            
    async def get_tqs_context(self, symbol: str) -> str:
        """Get TQS score and breakdown for a symbol"""
        if self._tqs_engine is None:
            return ""
            
        try:
            score_data = await self._tqs_engine.get_score(symbol)
            if not score_data.get("success"):
                return ""
                
            score = score_data.get("tqs_score", 0)
            grade = score_data.get("grade", "N/A")
            breakdown = score_data.get("breakdown", {})
            guidance = score_data.get("guidance", "")
            
            pillars_text = []
            for pillar_name, pillar_data in breakdown.items():
                if isinstance(pillar_data, dict):
                    pillar_score = pillar_data.get("score", 0)
                    pillars_text.append(f"  - {pillar_name.title()}: {pillar_score}/100")
                    
            return f"""
=== TRADE QUALITY SCORE (TQS) ===
Symbol: {symbol}
TQS Score: {score}/100 ({grade})
Guidance: {guidance}
Pillar Breakdown:
{chr(10).join(pillars_text)}
"""
        except Exception as e:
            logger.warning(f"Error getting TQS context: {e}")
            return ""
            
    async def get_context_performance_insight(
        self,
        setup_type: str,
        market_regime: str = None,
        time_of_day: str = None
    ) -> str:
        """Get your historical performance for this context combination"""
        if self._context_performance_service is None:
            return ""
            
        try:
            perf = await self._context_performance_service.get_performance(
                setup_type=setup_type,
                market_regime=market_regime,
                time_of_day=time_of_day
            )
            
            if not perf or perf.total_trades < 3:
                return ""
                
            trend_emoji = "📈" if perf.win_rate_trend == "improving" else "📉" if perf.win_rate_trend == "declining" else "➡️"
            
            return f"""
=== YOUR HISTORICAL PERFORMANCE ===
Context: {setup_type} + {market_regime or 'any regime'} + {time_of_day or 'any time'}
Win Rate: {perf.win_rate*100:.0f}% ({perf.wins}W/{perf.losses}L from {perf.total_trades} trades)
Profit Factor: {perf.profit_factor:.2f}
Average R: {perf.avg_r:.2f}
Trend: {trend_emoji} {perf.win_rate_trend}
Confidence: {perf.confidence}
"""
        except Exception as e:
            logger.warning(f"Error getting context performance: {e}")
            return ""
            
    async def get_edge_decay_warnings(self, setup_type: str = None) -> str:
        """Get any edge decay warnings relevant to current context"""
        if self._edge_decay_service is None:
            return ""
            
        try:
            if setup_type:
                metrics = await self._edge_decay_service.get_edge_metrics(setup_type)
                if metrics and metrics.is_decaying:
                    return f"""
⚠️ EDGE DECAY ALERT: {setup_type}
Severity: {metrics.decay_severity.upper()}
All-time Win Rate: {metrics.all_time_win_rate*100:.0f}%
Recent Win Rate (30d): {metrics.win_rate_30d*100:.0f}%
{metrics.alert_message}
"""
            else:
                # Get all decaying edges
                decaying = await self._edge_decay_service.get_decaying_edges()
                if not decaying:
                    return ""
                    
                alerts = []
                for edge in decaying[:3]:  # Top 3
                    alerts.append(f"• {edge.name}: {edge.decay_severity} ({edge.all_time_win_rate*100:.0f}% → {edge.win_rate_30d*100:.0f}%)")
                    
                if alerts:
                    return f"""
⚠️ EDGE DECAY WARNINGS:
{chr(10).join(alerts)}
"""
        except Exception as e:
            logger.warning(f"Error getting edge decay warnings: {e}")
            
        return ""
        
    async def get_confirmation_guidance(self, confirmations: List[str] = None) -> str:
        """Get guidance on which confirmations actually help"""
        if self._confirmation_validator_service is None:
            return ""
            
        try:
            all_stats = await self._confirmation_validator_service.get_all_stats()
            if not all_stats:
                return ""
                
            # Get effective and ineffective confirmations
            effective = [s for s in all_stats if s.is_effective and s.win_rate_lift > 5]
            ineffective = [s for s in all_stats if not s.is_effective and s.win_rate_lift < -5]
            
            lines = []
            if effective:
                top_conf = sorted(effective, key=lambda s: s.win_rate_lift, reverse=True)[:3]
                lines.append("✅ CONFIRMATIONS THAT WORK FOR YOU:")
                for s in top_conf:
                    lines.append(f"  • {s.confirmation_type}: +{s.win_rate_lift:.0f}% win rate lift")
                    
            if ineffective:
                lines.append("❌ CONFIRMATIONS TO IGNORE:")
                for s in ineffective[:2]:
                    lines.append(f"  • {s.confirmation_type}: {s.win_rate_lift:.0f}% (may be misleading)")
                    
            if lines:
                return "\n" + "\n".join(lines) + "\n"
                
        except Exception as e:
            logger.warning(f"Error getting confirmation guidance: {e}")
            
        return ""
        
    async def get_playbook_insight(self, setup_type: str) -> str:
        """Get playbook performance insight"""
        if self._playbook_performance_service is None:
            return ""
            
        try:
            perf = await self._playbook_performance_service.get_performance(setup_type)
            if not perf or perf.total_trades < 5:
                return ""
                
            insight_lines = [f"\n=== YOUR {setup_type.upper()} PLAYBOOK STATS ==="]
            insight_lines.append(f"Win Rate: {perf.win_rate*100:.0f}% (Expected: {perf.expected_win_rate*100:.0f}%)")
            
            if perf.win_rate_deviation < -0.1:
                insight_lines.append(f"⚠️ You're {abs(perf.win_rate_deviation)*100:.0f}% below expected win rate")
            elif perf.win_rate_deviation > 0.1:
                insight_lines.append(f"✅ You're {perf.win_rate_deviation*100:.0f}% above expected win rate!")
                
            if perf.common_mistakes:
                insight_lines.append(f"Common mistakes: {', '.join(perf.common_mistakes[:2])}")
                
            if perf.improvement_areas:
                insight_lines.append(f"Focus areas: {', '.join(perf.improvement_areas[:2])}")
                
            return "\n".join(insight_lines) + "\n"
            
        except Exception as e:
            logger.warning(f"Error getting playbook insight: {e}")
            
        return ""
        
    async def get_rag_context(self, query: str, symbol: str = None) -> str:
        """Get personalized context from RAG (similar past trades)"""
        if self._rag_service is None:
            return ""
            
        try:
            # Build query for RAG
            full_query = query
            if symbol:
                full_query = f"{symbol} {query}"
                
            # Retrieve relevant context
            results = await self._rag_service.retrieve(full_query, top_k=3)
            
            if not results:
                return ""
                
            context_lines = ["\n=== RELEVANT PAST EXPERIENCES ==="]
            
            for i, result in enumerate(results[:3], 1):
                metadata = result.get("metadata", {})
                content = result.get("content", "")[:200]
                
                context_lines.append(f"\n{i}. {metadata.get('type', 'Trade')}:")
                context_lines.append(f"   {content}...")
                
            return "\n".join(context_lines) + "\n"
            
        except Exception as e:
            logger.warning(f"Error getting RAG context: {e}")
            
        return ""
        
    async def get_calibration_context(self) -> str:
        """Get any pending calibration recommendations"""
        if self._calibration_service is None:
            return ""
            
        try:
            config = await self._calibration_service.get_config()
            
            return f"""
=== CURRENT THRESHOLDS ===
TQS Strong Buy: ≥{config.tqs_strong_buy_threshold}
TQS Buy: ≥{config.tqs_buy_threshold}
TQS Hold: ≥{config.tqs_hold_threshold}
"""
        except Exception as e:
            logger.warning(f"Error getting calibration context: {e}")
            
        return ""
        
    async def build_full_learning_context(
        self,
        symbol: str = None,
        setup_type: str = None,
        market_regime: str = None,
        time_of_day: str = None,
        user_query: str = None,
        include_tqs: bool = True,
        include_performance: bool = True,
        include_edge_decay: bool = True,
        include_confirmations: bool = True,
        include_rag: bool = True,
        include_level2: bool = True,
        include_market_snapshot: bool = True
    ) -> str:
        """
        Build comprehensive learning context for AI prompt injection.
        
        This is the main entry point - aggregates all relevant learning insights
        based on the current trading context.
        """
        context_parts = []
        
        # 0. Real-time market snapshot (VIX, SPY, etc.)
        if include_market_snapshot:
            market_context = await self.get_market_snapshot_context()
            if market_context:
                context_parts.append(market_context)
        
        # 1. TQS Score for symbol
        if include_tqs and symbol:
            tqs_context = await self.get_tqs_context(symbol)
            if tqs_context:
                context_parts.append(tqs_context)
                
        # 1.5. Level 2 order book context
        if include_level2 and symbol:
            l2_context = await self.get_level2_context(symbol)
            if l2_context:
                context_parts.append(l2_context)
                
        # 2. Historical performance for this context
        if include_performance and setup_type:
            perf_context = await self.get_context_performance_insight(
                setup_type, market_regime, time_of_day
            )
            if perf_context:
                context_parts.append(perf_context)
                
            # Also get playbook insight
            playbook_context = await self.get_playbook_insight(setup_type)
            if playbook_context:
                context_parts.append(playbook_context)
                
        # 3. Edge decay warnings
        if include_edge_decay:
            decay_context = await self.get_edge_decay_warnings(setup_type)
            if decay_context:
                context_parts.append(decay_context)
                
        # 4. Confirmation guidance
        if include_confirmations:
            conf_context = await self.get_confirmation_guidance()
            if conf_context:
                context_parts.append(conf_context)
                
        # 5. RAG - similar past trades
        if include_rag and user_query:
            rag_context = await self.get_rag_context(user_query, symbol)
            if rag_context:
                context_parts.append(rag_context)
                
        if not context_parts:
            return ""
            
        return "\n=== PERSONALIZED LEARNING INSIGHTS ===\n" + "\n".join(context_parts)
        
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        return {
            "tqs_engine_connected": self._tqs_engine is not None,
            "calibration_service_connected": self._calibration_service is not None,
            "context_performance_connected": self._context_performance_service is not None,
            "confirmation_validator_connected": self._confirmation_validator_service is not None,
            "edge_decay_connected": self._edge_decay_service is not None,
            "rag_connected": self._rag_service is not None,
            "playbook_performance_connected": self._playbook_performance_service is not None
        }
    
    async def get_level2_context(self, symbol: str) -> str:
        """
        Get Level 2 / order book context for a symbol.
        Includes bid/ask imbalance analysis for AI coaching.
        """
        try:
            from routers.ib import get_level2_for_symbol, is_pusher_connected
            
            if not is_pusher_connected():
                return ""
                
            l2_data = get_level2_for_symbol(symbol.upper())
            if not l2_data:
                return ""
                
            imbalance = l2_data.get("imbalance", 0)
            bid_total = l2_data.get("bid_total_size", 0)
            ask_total = l2_data.get("ask_total_size", 0)
            bids = l2_data.get("bids", [])
            asks = l2_data.get("asks", [])
            
            # Interpret imbalance
            if imbalance > 0.2:
                pressure = "STRONG BID PRESSURE (bullish)"
            elif imbalance > 0.1:
                pressure = "Moderate bid pressure (slightly bullish)"
            elif imbalance < -0.2:
                pressure = "STRONG ASK PRESSURE (bearish)"
            elif imbalance < -0.1:
                pressure = "Moderate ask pressure (slightly bearish)"
            else:
                pressure = "Balanced order flow"
            
            context = f"""
=== LEVEL 2 ORDER BOOK ({symbol.upper()}) ===
Order Flow: {pressure}
Bid/Ask Imbalance: {imbalance:.1%}
Total Bid Size: {bid_total:,}
Total Ask Size: {ask_total:,}

Top Bids: {', '.join([f'${b[0]:.2f}x{b[1]}' for b in bids[:3]]) if bids else 'N/A'}
Top Asks: {', '.join([f'${a[0]:.2f}x{a[1]}' for a in asks[:3]]) if asks else 'N/A'}
"""
            return context
            
        except Exception as e:
            logger.debug(f"Error getting L2 context: {e}")
            return ""
    
    async def get_market_snapshot_context(self) -> str:
        """
        Get real-time market snapshot from IB pushed data.
        Includes VIX, SPY, QQQ for market context.
        """
        try:
            from routers.ib import get_pushed_quotes, get_vix_from_pushed_data, is_pusher_connected
            
            if not is_pusher_connected():
                return ""
            
            quotes = get_pushed_quotes()
            vix_data = get_vix_from_pushed_data()
            
            context_lines = ["\n=== REAL-TIME MARKET SNAPSHOT ==="]
            
            # VIX
            if vix_data and vix_data.get("price"):
                vix = vix_data["price"]
                if vix < 15:
                    vix_note = "(Low - complacent market)"
                elif vix < 20:
                    vix_note = "(Normal)"
                elif vix < 30:
                    vix_note = "(Elevated - cautious)"
                else:
                    vix_note = "(HIGH - fear in market)"
                context_lines.append(f"VIX: {vix:.2f} {vix_note}")
            
            # Major indices
            for sym in ["SPY", "QQQ", "IWM"]:
                if sym in quotes:
                    q = quotes[sym]
                    last = q.get("last") or q.get("close") or 0
                    if last > 0:
                        context_lines.append(f"{sym}: ${last:.2f}")
            
            return "\n".join(context_lines) + "\n"
            
        except Exception as e:
            logger.debug(f"Error getting market snapshot: {e}")
            return ""


# Singleton
_learning_context_provider: Optional[LearningContextProvider] = None


def get_learning_context_provider() -> LearningContextProvider:
    global _learning_context_provider
    if _learning_context_provider is None:
        _learning_context_provider = LearningContextProvider()
    return _learning_context_provider


def init_learning_context_provider(
    db=None,
    tqs_engine=None,
    calibration_service=None,
    context_performance_service=None,
    confirmation_validator_service=None,
    edge_decay_service=None,
    rag_service=None,
    playbook_performance_service=None
) -> LearningContextProvider:
    provider = get_learning_context_provider()
    if db is not None:
        provider.set_db(db)
    provider.set_services(
        tqs_engine=tqs_engine,
        calibration_service=calibration_service,
        context_performance_service=context_performance_service,
        confirmation_validator_service=confirmation_validator_service,
        edge_decay_service=edge_decay_service,
        rag_service=rag_service,
        playbook_performance_service=playbook_performance_service
    )
    return provider
