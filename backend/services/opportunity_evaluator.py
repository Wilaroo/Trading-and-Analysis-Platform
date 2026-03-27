"""
Opportunity Evaluator — Extracted from trading_bot_service.py

The core trade evaluation pipeline:
1. Smart Strategy Filtering (historical performance gate)
2. AI Confidence Gate (regime + model consensus)
3. Intelligence Gathering (news, technicals, institutional)
4. Position Sizing (volatility + regime adjusted)
5. AI Trade Consultation
6. Trade Object Creation with rich entry context
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class OpportunityEvaluator:
    """Evaluates scanner alerts and builds fully-qualified trade objects."""

    async def evaluate_opportunity(self, alert: Dict, bot: 'TradingBotService') -> Optional['BotTrade']:
        """Evaluate an alert and create a trade if it meets criteria"""
        from services.trading_bot_service import (
            BotMode, BotTrade, TradeDirection, TradeStatus, TradeTimeframe,
            TradeExplanation, STRATEGY_CONFIG, DEFAULT_STRATEGY_CONFIG,
        )

        try:
            symbol = alert.get('symbol')
            setup_type = alert.get('setup_type')
            direction_str = alert.get('direction', 'long')
            direction = TradeDirection.LONG if direction_str == 'long' else TradeDirection.SHORT

            # Get current price - try IB pushed data first, then Alpaca
            current_price = alert.get('current_price', 0)
            if not current_price:
                try:
                    from routers.ib import get_pushed_quotes, is_pusher_connected
                    if is_pusher_connected():
                        quotes = get_pushed_quotes()
                        if symbol in quotes:
                            q = quotes[symbol]
                            current_price = q.get('last') or q.get('close') or 0
                except Exception:
                    pass

            # Fallback to Alpaca
            if not current_price and bot._alpaca_service:
                quote = await bot._alpaca_service.get_quote(symbol)
                current_price = quote.get('price', 0) if quote else 0

            if not current_price:
                print(f"   ❌ No price available for {symbol}")
                return None

            print(f"   📈 {symbol}: price=${current_price:.2f}")

            # ==================== SMART STRATEGY FILTERING ====================
            strategy_filter = bot._evaluate_strategy_filter(
                setup_type=setup_type,
                quality_score=alert.get('score', 70),
                symbol=symbol
            )

            filter_action = strategy_filter.get("action", "PROCEED")
            filter_reasoning = strategy_filter.get("reasoning", "")
            filter_adjustment = strategy_filter.get("adjustment_pct", 1.0)
            filter_win_rate = strategy_filter.get("win_rate", 0)

            if filter_action != "PROCEED" or (filter_win_rate and filter_win_rate > 0):
                bot._add_filter_thought({
                    "text": filter_reasoning,
                    "symbol": symbol,
                    "setup_type": setup_type,
                    "win_rate": filter_win_rate,
                    "action": filter_action,
                    "stats": strategy_filter.get("stats", {})
                })

            if filter_action == "SKIP":
                print(f"   📊 [SMART FILTER] {filter_reasoning}")
                return None

            # ==================== AI CONFIDENCE GATE ====================
            confidence_gate_result = None
            confidence_multiplier = 1.0

            if hasattr(bot, '_confidence_gate') and bot._confidence_gate is not None:
                try:
                    confidence_gate_result = await bot._confidence_gate.evaluate(
                        symbol=symbol,
                        setup_type=setup_type,
                        direction=direction.value if hasattr(direction, 'value') else str(direction),
                        quality_score=alert.get('score', 70),
                        entry_price=alert.get('trigger_price', current_price),
                        stop_price=alert.get('stop_price', 0),
                        regime_engine=bot._market_regime_engine,
                    )

                    gate_decision = confidence_gate_result.get("decision", "GO")
                    gate_confidence = confidence_gate_result.get("confidence_score", 50)
                    gate_reasoning = confidence_gate_result.get("reasoning", [])
                    confidence_multiplier = confidence_gate_result.get("position_multiplier", 1.0)
                    gate_mode = confidence_gate_result.get("trading_mode", "normal")

                    reasoning_summary = "; ".join(gate_reasoning[:2]) if gate_reasoning else "No reasoning"
                    bot._add_filter_thought({
                        "text": f"🧠 [CONFIDENCE GATE] {gate_decision} ({gate_confidence}% conf, {gate_mode} mode) — {reasoning_summary}",
                        "symbol": symbol,
                        "setup_type": setup_type,
                        "action": f"GATE_{gate_decision}",
                        "confidence_score": gate_confidence,
                        "trading_mode": gate_mode,
                    })

                    if gate_decision == "SKIP":
                        print(f"   🧠 [CONFIDENCE GATE] SKIP ({gate_confidence}% conf) — {reasoning_summary}")
                        return None
                    elif gate_decision == "REDUCE":
                        print(f"   🧠 [CONFIDENCE GATE] REDUCE ({gate_confidence}% conf, {confidence_multiplier:.0%} size) — {reasoning_summary}")
                    else:
                        print(f"   🧠 [CONFIDENCE GATE] GO ({gate_confidence}% conf) — {reasoning_summary}")

                except Exception as e:
                    logger.warning(f"Confidence gate error (proceeding anyway): {e}")
                    print(f"   ⚠️ Confidence gate error: {str(e)[:100]}")

            # ==================== ENHANCED INTELLIGENCE GATHERING ====================
            intelligence = await bot._gather_trade_intelligence(symbol, alert)

            score_adjustment = bot._calculate_intelligence_adjustment(intelligence)

            # Extract ATR from intelligence for volatility-adjusted sizing
            atr = alert.get('atr', 0)
            atr_percent = alert.get('atr_percent', 0)

            if not atr and intelligence.get('technicals'):
                tech = intelligence['technicals']
                atr = tech.get('atr', current_price * 0.02)
                atr_percent = tech.get('atr_percent', 2.0)
            elif not atr:
                atr = current_price * 0.02
                atr_percent = 2.0

            # Get trade parameters from alert
            entry_price = alert.get('trigger_price', current_price)
            stop_price = alert.get('stop_price', 0)
            target_prices = alert.get('targets', [])

            # Calculate ATR-based stop if not provided
            if not stop_price:
                stop_price = self.calculate_atr_based_stop(entry_price, direction, atr, setup_type, bot)

            # Calculate targets if not provided
            if not target_prices:
                risk = abs(entry_price - stop_price)
                if direction == TradeDirection.LONG:
                    target_prices = [entry_price + risk * 1.5, entry_price + risk * 2.5, entry_price + risk * 4]
                else:
                    target_prices = [entry_price - risk * 1.5, entry_price - risk * 2.5, entry_price - risk * 4]

            # Calculate position size with volatility adjustment
            shares, risk_amount = self.calculate_position_size(entry_price, stop_price, direction, bot, atr, atr_percent)

            # ==================== SMART STRATEGY FILTER SIZE ADJUSTMENT ====================
            if filter_action == "REDUCE_SIZE" and filter_adjustment < 1.0:
                original_shares = shares
                shares = max(1, int(shares * filter_adjustment))
                risk_amount = risk_amount * filter_adjustment
                print(f"   📊 [SMART FILTER] Reduced size: {original_shares} -> {shares} shares ({filter_adjustment*100:.0f}%)")

            # ==================== CONFIDENCE GATE SIZE ADJUSTMENT ====================
            if confidence_multiplier < 1.0:
                original_shares = shares
                shares = max(1, int(shares * confidence_multiplier))
                risk_amount = risk_amount * confidence_multiplier
                gate_conf = confidence_gate_result.get("confidence_score", 0) if confidence_gate_result else 0
                print(f"   🧠 [CONFIDENCE GATE] Reduced size: {original_shares} -> {shares} shares ({confidence_multiplier*100:.0f}%, {gate_conf}% conf)")

            if shares <= 0:
                print(f"   ❌ Position size = 0 (entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f})")
                return None

            print(f"   📊 {symbol}: {shares} shares, entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f}")

            # Calculate risk/reward
            primary_target = target_prices[0] if target_prices else entry_price
            potential_reward = abs(primary_target - entry_price) * shares
            risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0

            if risk_reward_ratio < bot.risk_params.min_risk_reward:
                print(f"   ❌ R:R {risk_reward_ratio:.2f} < {bot.risk_params.min_risk_reward} min required")
                return None

            print(f"   ✅ {symbol}: R:R={risk_reward_ratio:.2f}, target=${primary_target:.2f}, reward=${potential_reward:.2f}")

            # Get quality score with intelligence adjustment
            base_score = alert.get('score', 70)
            quality_score = min(100, max(0, base_score + score_adjustment))
            quality_grade = self.score_to_grade(quality_score)

            # Generate explanation with intelligence data
            explanation = self.generate_explanation(alert, shares, entry_price, stop_price, target_prices, intelligence, bot)

            # Get strategy config for this setup type
            strategy_cfg = STRATEGY_CONFIG.get(setup_type, DEFAULT_STRATEGY_CONFIG)
            timeframe_val = strategy_cfg["timeframe"]
            timeframe_str = timeframe_val.value if isinstance(timeframe_val, TradeTimeframe) else timeframe_val
            trail_pct = strategy_cfg.get("trail_pct", 0.02)
            scale_pcts = strategy_cfg.get("scale_out_pcts", [0.33, 0.33, 0.34])
            close_at_eod = strategy_cfg.get("close_at_eod", True)

            # Get current market regime
            current_regime = bot._current_regime or "UNKNOWN"
            regime_score = 50.0
            regime_multiplier = bot._regime_position_multipliers.get(current_regime, 1.0)

            if current_regime == "CONFIRMED_DOWN" and direction == TradeDirection.SHORT:
                regime_multiplier = 1.0
            elif current_regime == "RISK_ON" and direction == TradeDirection.SHORT:
                regime_multiplier = 0.7

            if bot._market_regime_engine is not None:
                try:
                    regime_data = await bot._market_regime_engine.get_current_regime()
                    regime_score = regime_data.get("composite_score", 50.0)
                except Exception:
                    pass

            # Create trade
            trade = BotTrade(
                id=str(uuid.uuid4())[:8],
                symbol=symbol,
                direction=direction,
                status=TradeStatus.PENDING,
                setup_type=setup_type,
                timeframe=timeframe_str,
                quality_score=quality_score,
                quality_grade=quality_grade,
                trade_style=alert.get("trade_style", "trade_2_hold"),
                smb_grade=alert.get("smb_grade", quality_grade),
                tape_score=alert.get("tape_score", 5),
                target_r_multiple=alert.get("target_r_multiple", risk_reward_ratio),
                direction_bias=alert.get("direction_bias", "both"),
                entry_price=entry_price,
                current_price=current_price,
                stop_price=stop_price,
                target_prices=target_prices,
                shares=shares,
                risk_amount=risk_amount,
                potential_reward=potential_reward,
                risk_reward_ratio=risk_reward_ratio,
                created_at=datetime.now(timezone.utc).isoformat(),
                estimated_duration=self.estimate_duration(setup_type),
                explanation=explanation,
                close_at_eod=close_at_eod,
                market_regime=current_regime,
                regime_score=regime_score,
                regime_position_multiplier=regime_multiplier,
                setup_variant=alert.get("strategy_name", alert.get("setup_variant", setup_type)),
                entry_context=self.build_entry_context(
                    alert, intelligence, current_regime, regime_score,
                    filter_action, filter_win_rate, atr, atr_percent,
                    confidence_gate_result=confidence_gate_result
                ),
                scale_out_config={
                    "enabled": True,
                    "targets_hit": [],
                    "scale_out_pcts": scale_pcts,
                    "partial_exits": []
                },
                trailing_stop_config={
                    "enabled": True,
                    "mode": "original",
                    "original_stop": stop_price,
                    "current_stop": stop_price,
                    "trail_pct": trail_pct,
                    "trail_atr_mult": 1.5,
                    "high_water_mark": 0.0,
                    "low_water_mark": 0.0,
                    "stop_adjustments": []
                }
            )

            logger.info(f"Trade opportunity created: {symbol} {direction.value} {shares} shares @ ${entry_price:.2f}")
            print(f"   🎯 Trade object created: {trade.id} {symbol} {direction.value}")

            # ==================== AI TRADE CONSULTATION (Phase 2) ====================
            ai_consultation_result = None
            if hasattr(bot, '_ai_consultation') and bot._ai_consultation:
                try:
                    market_context = {
                        "regime": current_regime,
                        "vix": intelligence.get("market_data", {}).get("vix", 0),
                        "trend": intelligence.get("market_data", {}).get("trend", "neutral"),
                        "technicals": intelligence.get("technicals", {}),
                        "session": bot._get_current_session()
                    }

                    portfolio_context = {
                        "account_value": await bot._get_account_value(),
                        "open_positions": len(bot._open_trades),
                        "positions": [t.to_dict() for t in bot._open_trades.values()]
                    }

                    bars = intelligence.get("bars", [])

                    ai_consultation_result = await bot._ai_consultation.consult_on_trade(
                        trade=trade.to_dict(),
                        market_context=market_context,
                        portfolio=portfolio_context,
                        bars=bars
                    )

                    if ai_consultation_result:
                        consult_rec = ai_consultation_result.get("reasoning", "No AI analysis")
                        shadow_mode = ai_consultation_result.get("shadow_logged", False)
                        decision_id = ai_consultation_result.get("shadow_decision_id", "")

                        print(f"   🧠 [AI Consultation] {consult_rec[:100]}")

                        if not ai_consultation_result.get("proceed", True):
                            print(f"   ❌ [AI BLOCKED] {ai_consultation_result.get('reasoning', '')}")
                            logger.info(f"AI Consultation BLOCKED trade {symbol}: {consult_rec}")
                            if shadow_mode and decision_id:
                                trade.explanation.ai_shadow_decision_id = decision_id
                            return None

                        size_adj = ai_consultation_result.get("size_adjustment", 1.0)
                        if size_adj < 1.0:
                            original_shares = trade.shares
                            trade.shares = max(1, int(trade.shares * size_adj))
                            trade.risk_amount = trade.risk_amount * size_adj
                            trade.potential_reward = trade.potential_reward * size_adj
                            print(f"   📉 [AI SIZE ADJ] {original_shares} -> {trade.shares} shares ({size_adj*100:.0f}%)")

                        if shadow_mode and decision_id:
                            if not hasattr(trade, 'ai_shadow_decision_id'):
                                trade.ai_shadow_decision_id = decision_id

                        if trade.explanation:
                            trade.explanation.ai_consultation = {
                                "proceed": ai_consultation_result.get("proceed", True),
                                "size_adjustment": size_adj,
                                "reasoning": consult_rec[:300],
                                "shadow_decision_id": decision_id
                            }

                except Exception as e:
                    logger.warning(f"AI Consultation failed (proceeding anyway): {e}")
                    print(f"   ⚠️ AI Consultation error: {str(e)[:100]}")

            # AI evaluation - legacy
            if hasattr(bot, '_ai_assistant') and bot._ai_assistant:
                try:
                    ai_result = await bot._ai_assistant.evaluate_bot_opportunity(trade.to_dict())
                    if ai_result.get("success") and trade.explanation:
                        trade.explanation.ai_evaluation = ai_result.get("analysis", "")
                        trade.explanation.ai_verdict = ai_result.get("verdict", "CAUTION")
                        if ai_result.get("verdict") == "REJECT":
                            print(f"   🤖 AI REJECTED trade: {ai_result.get('analysis', '')[:150]}")
                            logger.info(f"AI REJECTED trade {symbol}: {ai_result.get('analysis', '')[:100]}")
                            if bot._mode != BotMode.AUTONOMOUS:
                                return None
                            else:
                                print("   ⚠️ Overriding AI rejection in AUTONOMOUS mode")
                except Exception as e:
                    logger.warning(f"AI evaluation failed (proceeding anyway): {e}")

            print(f"   ✅ Returning trade object {trade.id}")
            return trade

        except Exception as e:
            print(f"   ❌ Exception in _evaluate_opportunity: {e}")
            logger.error(f"Error evaluating opportunity: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==================== HELPERS ====================

    def calculate_position_size(self, entry_price: float, stop_price: float, direction, bot: 'TradingBotService', atr: float = None, atr_percent: float = None) -> Tuple[int, float]:
        """Calculate position size based on risk management rules with volatility and market regime adjustment."""
        from services.trading_bot_service import TradeDirection

        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share <= 0:
            return 0, 0
        adjusted_max_risk = bot.risk_params.max_risk_per_trade
        volatility_multiplier = 1.0
        if bot.risk_params.use_volatility_sizing and atr_percent:
            if atr_percent < 1.5:
                volatility_multiplier = 1.3
            elif atr_percent < 2.5:
                volatility_multiplier = 1.1
            elif atr_percent < 3.5:
                volatility_multiplier = 1.0
            elif atr_percent < 5.0:
                volatility_multiplier = 0.8
            else:
                volatility_multiplier = 0.6
            volatility_multiplier *= bot.risk_params.volatility_scale_factor
            adjusted_max_risk = bot.risk_params.max_risk_per_trade * volatility_multiplier
        regime_multiplier = 1.0
        if bot._current_regime:
            base_regime_multiplier = bot._regime_position_multipliers.get(bot._current_regime, 1.0)
            if bot._current_regime == "CONFIRMED_DOWN" and direction == TradeDirection.SHORT:
                regime_multiplier = 1.0
            elif bot._current_regime == "RISK_ON" and direction == TradeDirection.SHORT:
                regime_multiplier = 0.7
            else:
                regime_multiplier = base_regime_multiplier
            adjusted_max_risk *= regime_multiplier
            if regime_multiplier < 1.0:
                logger.debug(f"Position size adjusted by regime ({bot._current_regime}): {regime_multiplier:.0%}")
        max_shares_by_risk = int(adjusted_max_risk / risk_per_share)
        max_position_value = bot.risk_params.starting_capital * (bot.risk_params.max_position_pct / 100)
        max_shares_by_capital = int(max_position_value / entry_price)
        shares = max(min(max_shares_by_risk, max_shares_by_capital), 1)
        risk_amount = shares * risk_per_share
        if risk_amount > adjusted_max_risk:
            shares = int(adjusted_max_risk / risk_per_share)
            risk_amount = shares * risk_per_share
        return shares, risk_amount

    def calculate_atr_based_stop(self, entry_price: float, direction, atr: float, setup_type: str, bot: 'TradingBotService') -> float:
        """Calculate stop loss based on ATR with setup-specific multiplier."""
        from services.trading_bot_service import TradeDirection

        setup_multipliers = {
            'rubber_band': 1.0, 'squeeze': 1.5, 'breakout': 1.5, 'vwap_bounce': 1.0,
            'gap_fade': 1.25, 'relative_strength': 1.5, 'mean_reversion': 1.0, 'orb': 1.25,
        }
        multiplier = setup_multipliers.get(setup_type, bot.risk_params.base_atr_multiplier)
        multiplier = max(bot.risk_params.min_atr_multiplier, min(multiplier, bot.risk_params.max_atr_multiplier))
        stop_distance = atr * multiplier
        if direction == TradeDirection.LONG:
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance

    @staticmethod
    def score_to_grade(score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90: return "A+"
        if score >= 80: return "A"
        if score >= 70: return "B+"
        if score >= 60: return "B"
        if score >= 50: return "C"
        return "F"

    @staticmethod
    def estimate_duration(setup_type: str) -> str:
        """Estimate trade duration based on setup type"""
        durations = {
            "rubber_band": "30min - 2hr",
            "breakout": "1hr - 4hr",
            "vwap_bounce": "15min - 1hr",
            "squeeze": "2hr - 1day"
        }
        return durations.get(setup_type, "1hr - 4hr")

    def build_entry_context(
        self, alert: Dict, intelligence: Dict, regime: str,
        regime_score: float, filter_action: str, filter_win_rate: float,
        atr: float, atr_percent: float, confidence_gate_result: Dict = None
    ) -> Dict[str, Any]:
        """
        Build rich entry context capturing WHY this trade was taken.
        This snapshot records the conditions and signals at the moment of entry
        for post-trade analysis and AI learning.
        """
        ctx = {}

        # 1. Setup identification
        ctx["scanner_setup_type"] = alert.get("setup_type", "")
        ctx["strategy_name"] = alert.get("strategy_name", "")
        ctx["setup_category"] = alert.get("setup_category", "")
        ctx["score"] = alert.get("score", 0)
        ctx["trigger_probability"] = alert.get("trigger_probability", 0)
        ctx["tape_confirmation"] = alert.get("tape_confirmation", False)
        ctx["priority"] = alert.get("priority", "medium")
        if isinstance(ctx["priority"], type) and hasattr(ctx["priority"], "value"):
            ctx["priority"] = ctx["priority"].value

        # 2. Market regime context
        ctx["market_regime"] = regime
        ctx["regime_score"] = regime_score

        # 3. Strategy filter context (smart filter)
        ctx["filter_action"] = filter_action
        ctx["filter_win_rate"] = filter_win_rate
        ctx["strategy_win_rate"] = alert.get("strategy_win_rate", 0)

        # 4. Volatility context
        ctx["atr"] = round(atr, 4) if atr else 0
        ctx["atr_percent"] = round(atr_percent, 2) if atr_percent else 0
        ctx["rvol"] = alert.get("rvol", 0) or alert.get("relative_volume", 0)

        # 5. Technical signals from intelligence
        if intelligence:
            tech = intelligence.get("technicals") or {}
            ctx["technicals"] = {
                "trend": tech.get("trend", ""),
                "rsi": tech.get("momentum", 0),
                "vwap_relation": tech.get("vwap_relation", ""),
                "volume_trend": tech.get("volume_trend", ""),
                "support_nearby": tech.get("near_support", False),
                "resistance_nearby": tech.get("near_resistance", False),
            }

            if intelligence.get("news"):
                ctx["catalyst"] = {
                    "has_catalyst": True,
                    "headline_count": len(intelligence["news"]) if isinstance(intelligence["news"], list) else 1,
                }

            if intelligence.get("institutional"):
                inst = intelligence["institutional"]
                ctx["institutional"] = {
                    "dark_pool_signal": inst.get("dark_pool_signal", ""),
                    "block_trade_alert": inst.get("block_trade_alert", False),
                }

        # 6. Time context
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
        ctx["entry_time_et"] = now_et.strftime("%H:%M:%S")
        ctx["time_window"] = self.classify_time_window(now_et)

        # 7. AI prediction context (if available)
        if hasattr(self, '_last_ai_prediction') and self._last_ai_prediction:
            pred = self._last_ai_prediction
            if pred.get("symbol") == alert.get("symbol"):
                ctx["ai_prediction"] = {
                    "direction": pred.get("direction", ""),
                    "confidence": pred.get("confidence", 0),
                    "regime_aligned": pred.get("regime_adjustment", {}).get("regime_aligned"),
                }

        # 8. Confidence gate context
        if confidence_gate_result:
            ctx["confidence_gate"] = {
                "decision": confidence_gate_result.get("decision", ""),
                "confidence_score": confidence_gate_result.get("confidence_score", 0),
                "position_multiplier": confidence_gate_result.get("position_multiplier", 1.0),
                "trading_mode": confidence_gate_result.get("trading_mode", ""),
                "ai_regime": confidence_gate_result.get("ai_regime", ""),
                "reasoning": confidence_gate_result.get("reasoning", [])[:3],
            }

        return ctx

    @staticmethod
    def classify_time_window(now_et) -> str:
        """Classify the current ET time into a trading time window."""
        h, m = now_et.hour, now_et.minute
        t = h * 60 + m
        if t < 9 * 60 + 30:
            return "pre_market"
        elif t < 9 * 60 + 45:
            return "opening_auction"
        elif t < 10 * 60:
            return "opening_drive"
        elif t < 10 * 60 + 30:
            return "morning_momentum"
        elif t < 11 * 60 + 30:
            return "morning_session"
        elif t < 12 * 60:
            return "late_morning"
        elif t < 13 * 60 + 30:
            return "midday"
        elif t < 15 * 60:
            return "afternoon"
        elif t < 16 * 60:
            return "power_hour"
        else:
            return "after_hours"

    def generate_explanation(self, alert: Dict, shares: int, entry: float, stop: float, targets: List[float], intelligence: Dict, bot: 'TradingBotService'):
        """Generate detailed explanation for the trade with intelligence data"""
        from services.trading_bot_service import TradeExplanation

        symbol = alert.get('symbol', '')
        setup_type = alert.get('setup_type', '')
        direction = alert.get('direction', 'long')

        risk_per_share = abs(entry - stop)
        total_risk = shares * risk_per_share
        target_1_profit = abs(targets[0] - entry) * shares if targets else 0

        # Build technical reasons from alert + intelligence
        technical_reasons = alert.get('technical_reasons', [
            f"Setup type: {setup_type}",
            f"Score: {alert.get('score', 'N/A')}/100",
            f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%"
        ])

        if intelligence and intelligence.get('technicals'):
            tech = intelligence['technicals']
            if tech.get('trend'):
                technical_reasons.append(f"Trend: {tech['trend']}")
            if tech.get('momentum'):
                technical_reasons.append(f"RSI: {tech['momentum']:.0f}")
            if tech.get('volume_trend'):
                technical_reasons.append(f"Volume: {tech['volume_trend']}")

        fundamental_reasons = alert.get('fundamental_reasons', [])
        if intelligence and intelligence.get('news'):
            news = intelligence['news']
            if news.get('sentiment'):
                fundamental_reasons.append(f"News sentiment: {news['sentiment']}")
            if news.get('key_topics'):
                fundamental_reasons.append(f"Key topics: {', '.join(news['key_topics'])}")
            if news.get('summary'):
                fundamental_reasons.append(f"Latest: {news['summary'][:100]}...")

        all_warnings = alert.get('warnings', []).copy()
        if intelligence:
            all_warnings.extend(intelligence.get('warnings', []))

        confidence_factors = [
            f"Quality score: {alert.get('score', 0)}/100",
            f"Trigger probability: {alert.get('trigger_probability', 0)*100:.0f}%",
            f"Risk/Reward: {abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
        ]

        if intelligence and intelligence.get('enhancements'):
            confidence_factors.extend(intelligence['enhancements'])

        return TradeExplanation(
            summary=f"{setup_type.replace('_', ' ').title()} setup identified on {symbol}. "
                    f"{'Buying' if direction == 'long' else 'Shorting'} {shares} shares at ${entry:.2f} "
                    f"with stop at ${stop:.2f} and target at ${targets[0]:.2f}.",

            setup_identified=alert.get('headline', f"{setup_type} pattern detected"),

            technical_reasons=technical_reasons,

            fundamental_reasons=fundamental_reasons,

            risk_analysis={
                "risk_per_share": f"${risk_per_share:.2f}",
                "total_risk": f"${total_risk:.2f}",
                "max_risk_allowed": f"${bot.risk_params.max_risk_per_trade:.2f}",
                "risk_pct_of_capital": f"{(total_risk / bot.risk_params.starting_capital * 100):.2f}%",
                "risk_reward_ratio": f"{abs(targets[0] - entry) / risk_per_share:.2f}:1" if targets and risk_per_share > 0 else "N/A"
            },

            entry_logic=f"Enter at ${entry:.2f} when price reaches trigger level. "
                       f"Current price is ${alert.get('current_price', 0):.2f}.",

            exit_logic=f"Stop loss at ${stop:.2f} ({(risk_per_share/entry*100):.1f}% from entry). "
                      f"Primary target at ${targets[0]:.2f} ({(abs(targets[0]-entry)/entry*100):.1f}% gain). "
                      f"Consider scaling out at subsequent targets.",

            position_sizing_logic=f"Position size: {shares} shares (${shares * entry:,.2f} value). "
                                 f"Based on max risk ${bot.risk_params.max_risk_per_trade:,.0f} "
                                 f"÷ risk per share ${risk_per_share:.2f} = {int(bot.risk_params.max_risk_per_trade/risk_per_share)} max shares. "
                                 f"Capped at {bot.risk_params.max_position_pct}% of capital.",

            confidence_factors=confidence_factors,

            warnings=all_warnings
        )
