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

            # V5 Unified Stream — surface "I'm thinking about this one now"
            # so the operator sees the bot's reasoning trail in real time
            # instead of having to grep logs. Fires once per evaluation
            # (dedup happens inside emit_stream_event), kept under 80 chars
            # so it doesn't dominate the stream visually.
            try:
                from services.sentcom_service import emit_stream_event
                tqs = alert.get('tqs_score') or alert.get('score') or 0
                grade = alert.get('tqs_grade') or alert.get('trade_grade') or ''
                grade_part = f" {grade}" if grade else ""
                await emit_stream_event({
                    "kind": "evaluation",
                    "event": "evaluating_setup",
                    "symbol": symbol,
                    "text": (
                        f"🤔 Evaluating {symbol} {setup_type} {direction_str.upper()} "
                        f"(TQS {tqs:.0f}{grade_part})"
                    ),
                    "metadata": {
                        "setup_type": setup_type,
                        "direction": direction_str,
                        "tqs_score": tqs,
                        "alert_priority": alert.get("priority"),
                    },
                })
            except Exception:
                pass

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
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="no_price",
                    context={"why": "Neither IB pusher nor Alpaca returned a price"},
                )
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
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="smart_filter_skip",
                    context={
                        "why": filter_reasoning,
                        "win_rate": filter_win_rate,
                        "stats": strategy_filter.get("stats", {}),
                    },
                )
                return None

            # ==================== AI CONFIDENCE GATE ====================
            confidence_gate_result = None
            confidence_multiplier = 1.0
            # Init early — referenced by build_entry_context() before the
            # AI consultation block that assigns it. Without this, INTC /
            # AAPL / MSFT etc trigger
            #   `cannot access local variable 'ai_consultation_result'
            #    where it is not associated with a value`
            # on every scan cycle, vetoing the trade as `evaluator_veto`.
            # 2026-04-29 (afternoon-14).
            ai_consultation_result: Optional[Dict[str, Any]] = None

            if hasattr(bot, '_confidence_gate') and bot._confidence_gate is not None:
                try:
                    # GAP 1 FIX: Use TQS score (richer 5-pillar assessment) instead of raw scanner score
                    gate_quality = alert.get('tqs_score') or alert.get('score', 70)
                    # Ensure it's numeric (TQS can be float)
                    gate_quality = int(gate_quality) if gate_quality else 70

                    confidence_gate_result = await bot._confidence_gate.evaluate(
                        symbol=symbol,
                        setup_type=setup_type,
                        direction=direction.value if hasattr(direction, 'value') else str(direction),
                        quality_score=gate_quality,
                        entry_price=alert.get('trigger_price', current_price),
                        stop_price=alert.get('stop_price', 0),
                        regime_engine=bot._market_regime_engine,
                    )

                    gate_decision = confidence_gate_result.get("decision", "GO")
                    gate_confidence = confidence_gate_result.get("confidence_score", 50)
                    gate_reasoning = confidence_gate_result.get("reasoning", [])
                    confidence_multiplier = confidence_gate_result.get("position_multiplier", 1.0)
                    gate_mode = confidence_gate_result.get("trading_mode", "normal")

                    reasoning_summary = "; ".join(gate_reasoning[:4]) if gate_reasoning else "No reasoning"
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
                        bot.record_rejection(
                            symbol=symbol, setup_type=setup_type, direction=direction_str,
                            reason_code="gate_skip",
                            context={
                                "why": reasoning_summary,
                                "confidence_score": gate_confidence,
                                "trading_mode": gate_mode,
                            },
                        )
                        return None
                    elif gate_decision == "REDUCE":
                        print(f"   🧠 [CONFIDENCE GATE] REDUCE ({gate_confidence}% conf, {confidence_multiplier:.0%} size) — {reasoning_summary}")
                    else:
                        print(f"   🧠 [CONFIDENCE GATE] GO ({gate_confidence}% conf) — {reasoning_summary}")

                except Exception as e:
                    logger.warning(
                        "Confidence gate error (proceeding anyway) (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )
                    print(f"   ⚠️ Confidence gate error: {str(e)[:100]}")

            # ==================== GAP 3 FIX: POST-GATE TQS RECALCULATION ====================
            # The Confidence Gate produces the richest AI data (setup-specific live prediction,
            # model consensus, learning loop feedback). Recalculate TQS with this data so the
            # trade's quality score reflects the full AI pipeline.
            if confidence_gate_result and confidence_gate_result.get("live_prediction"):
                try:
                    from services.tqs.tqs_engine import get_tqs_engine
                    tqs_engine = get_tqs_engine()
                    
                    pred = confidence_gate_result["live_prediction"]
                    pred_dir = pred.get("direction", "flat")
                    pred_conf = pred.get("confidence", 0)
                    trade_is_long = direction_str.lower() in ("long", "buy")
                    model_agrees = (
                        (trade_is_long and pred_dir == "up") or
                        (not trade_is_long and pred_dir == "down")
                    )
                    
                    recalc_tqs = await tqs_engine.calculate_tqs(
                        symbol=symbol,
                        setup_type=setup_type,
                        direction=direction_str,
                        trade_style=alert.get("trade_style"),
                        tape_score=alert.get("tape_score", 0),
                        tape_confirmation=alert.get("tape_confirmation", False),
                        smb_grade=alert.get("smb_grade", "B"),
                        smb_5var_score=alert.get("smb_score_total", 25),
                        risk_reward=alert.get("risk_reward", 2.0),
                        alert_priority=alert.get("priority", "medium"),
                        ai_model_direction=pred_dir,
                        ai_model_confidence=pred_conf,
                        ai_model_agrees=model_agrees,
                    )
                    
                    if recalc_tqs:
                        # Store the AI-enriched TQS for the trade
                        alert["_post_gate_tqs_score"] = recalc_tqs.score
                        alert["_post_gate_tqs_grade"] = recalc_tqs.grade
                        alert["_post_gate_tqs_action"] = recalc_tqs.action
                        logger.debug(
                            f"Post-gate TQS for {symbol}: {recalc_tqs.score:.1f} "
                            f"(pre-gate: {alert.get('tqs_score', 'N/A')})"
                        )
                except Exception as e:
                    logger.debug(f"Post-gate TQS recalculation failed (non-critical): {e}")

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

            # ── Stop-placement guard (2026-04-28e) ──
            # Before targets / position size, ask Smart S/R if our stop
            # is sitting inside a Volume-Profile / pivot cluster. If so,
            # widen it to just past the cluster (capped at +40% of the
            # original distance to preserve sizing risk math). Stops are
            # NEVER tightened — only widened.
            stop_guard_meta = None
            try:
                sym_for_guard = alert.get("symbol") if isinstance(alert, dict) else None
                guard_bs = "5 mins"
                if isinstance(alert, dict):
                    guard_bs = alert.get("bar_size") or alert.get("scanner_bar_size") or "5 mins"
                db_for_guard = getattr(bot, "_db", None) or getattr(bot, "db", None)
                if sym_for_guard and db_for_guard is not None and stop_price:
                    from services.smart_levels_service import compute_stop_guard
                    dir_str = "long" if direction == TradeDirection.LONG else "short"
                    guard = compute_stop_guard(
                        db_for_guard, sym_for_guard.upper(), guard_bs,
                        float(entry_price), float(stop_price), dir_str,
                    )
                    if guard.get("snapped"):
                        logger.info(
                            f"Stop-guard widened {sym_for_guard} "
                            f"{dir_str.upper()} stop {stop_price:.2f} → "
                            f"{guard['stop']:.2f} (past {guard['level_kind']} "
                            f"@ {guard['level_price']:.2f}, widen "
                            f"{guard['widen_pct']:+.0%})"
                        )
                        stop_price = guard["stop"]
                    stop_guard_meta = guard
            except Exception as exc:
                logger.debug(f"stop-guard skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")

            # Calculate targets if not provided
            if not target_prices:
                risk = abs(entry_price - stop_price)
                if direction == TradeDirection.LONG:
                    target_prices = [entry_price + risk * 1.5, entry_price + risk * 2.5, entry_price + risk * 4]
                else:
                    target_prices = [entry_price - risk * 1.5, entry_price - risk * 2.5, entry_price - risk * 4]

            # ── Target snap (2026-04-28e) ──
            # For each computed target, snap to just before the nearest
            # strong S/R cluster on the move side. Catches the "2.5R
            # target sits 40 cents short of a thick HVN" failure mode.
            target_snap_meta = None
            try:
                sym_for_targets = alert.get("symbol") if isinstance(alert, dict) else None
                tgt_bs = "5 mins"
                if isinstance(alert, dict):
                    tgt_bs = alert.get("bar_size") or alert.get("scanner_bar_size") or "5 mins"
                db_for_targets = getattr(bot, "_db", None) or getattr(bot, "db", None)
                if sym_for_targets and db_for_targets is not None and target_prices:
                    from services.smart_levels_service import compute_target_snap
                    dir_str = "long" if direction == TradeDirection.LONG else "short"
                    snap = compute_target_snap(
                        db_for_targets, sym_for_targets.upper(), tgt_bs,
                        float(entry_price), [float(t) for t in target_prices], dir_str,
                    )
                    if snap.get("any_snapped"):
                        logger.info(
                            f"Target-snap {sym_for_targets} {dir_str.upper()} "
                            f"targets {[round(t, 2) for t in target_prices]} → "
                            f"{[round(t, 2) for t in snap['targets']]}"
                        )
                        target_prices = snap["targets"]
                    target_snap_meta = snap.get("details")
            except Exception as exc:
                logger.debug(f"target-snap skipped for {alert.get('symbol') if isinstance(alert, dict) else '?'}: {exc}")

            # Calculate position size with volatility adjustment + Volume-Profile path multiplier (2026-04-28e)
            symbol_for_vp = alert.get("symbol") if isinstance(alert, dict) else None
            if isinstance(alert, dict):
                scanner_bs = alert.get("bar_size") or alert.get("scanner_bar_size") or "5 mins"
            else:
                scanner_bs = "5 mins"
            position_multipliers: Dict[str, Any] = {}
            shares, risk_amount = self.calculate_position_size(
                entry_price, stop_price, direction, bot, atr, atr_percent,
                symbol=symbol_for_vp, bar_size=scanner_bs,
                multipliers_out=position_multipliers,
            )

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

            # ==================== STRATEGY TILT (long/short Sharpe bias) ====================
            # Re-weights size by rolling 30-day per-side Sharpe so cold streaks
            # on one side shrink while the hot side grows. Bounded [0.5x, 1.5x];
            # neutral when either side has fewer than 10 closed trades.
            try:
                from services.strategy_tilt import get_strategy_tilt_cached, get_side_tilt_multiplier
                tilt = get_strategy_tilt_cached(getattr(bot, "_db", None))
                tilt_mult = get_side_tilt_multiplier(
                    direction.value if hasattr(direction, "value") else str(direction),
                    tilt,
                )
                if abs(tilt_mult - 1.0) > 1e-3:
                    original_shares = shares
                    shares = max(1, int(shares * tilt_mult))
                    risk_amount = risk_amount * tilt_mult
                    print(f"   ⚖️ [STRATEGY TILT] {original_shares} -> {shares} shares "
                          f"(x{tilt_mult:.2f}, long_Sh={tilt.get('sharpe_long', 0):.2f}, "
                          f"short_Sh={tilt.get('sharpe_short', 0):.2f})")
            except Exception as _tilt_err:
                logger.debug(f"[StrategyTilt] skipped: {_tilt_err}")

            # ==================== HRP PORTFOLIO ALLOCATOR ====================
            # Down-weight candidates that are correlated with existing open
            # positions. Neutral (1.0) when fewer than 2 peers or when the
            # returns fetcher isn't registered — never breaks sizing.
            try:
                from services.portfolio_allocator_service import get_hrp_multiplier
                open_symbols = [t.symbol for t in bot._open_trades.values()
                                if getattr(t, "symbol", None)]
                pending_symbols = [t.symbol for t in bot._pending_trades.values()
                                   if getattr(t, "symbol", None) and t.symbol != symbol]
                peer_symbols = list(dict.fromkeys(open_symbols + pending_symbols + [symbol]))
                hrp_mult = get_hrp_multiplier(symbol, peer_symbols)
                if abs(hrp_mult - 1.0) > 1e-3:
                    original_shares = shares
                    shares = max(1, int(shares * hrp_mult))
                    risk_amount = risk_amount * hrp_mult
                    print(f"   🌐 [HRP ALLOCATOR] {original_shares} -> {shares} shares "
                          f"(x{hrp_mult:.2f}, peers={len(peer_symbols)})")
            except Exception as _hrp_err:
                logger.debug(f"[HRPAllocator] skipped: {_hrp_err}")

            if shares <= 0:
                print(f"   ❌ Position size = 0 (entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f})")
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="position_size_zero",
                    context={
                        "entry_price": float(entry_price),
                        "stop_price": float(stop_price),
                        "risk_amount": float(risk_amount),
                        "why": "Position sizer returned 0 shares — usually means equity unavailable or risk caps too tight for this entry/stop distance",
                    },
                )
                return None

            print(f"   📊 {symbol}: {shares} shares, entry=${entry_price:.2f}, stop=${stop_price:.2f}, risk=${risk_amount:.2f}")

            # Calculate risk/reward
            primary_target = target_prices[0] if target_prices else entry_price
            potential_reward = abs(primary_target - entry_price) * shares
            risk_reward_ratio = potential_reward / risk_amount if risk_amount > 0 else 0

            if risk_reward_ratio < bot.risk_params.min_risk_reward:
                print(f"   ❌ R:R {risk_reward_ratio:.2f} < {bot.risk_params.min_risk_reward} min required")
                bot.record_rejection(
                    symbol=symbol, setup_type=setup_type, direction=direction_str,
                    reason_code="rr_below_min",
                    context={
                        "rr_ratio": round(risk_reward_ratio, 2),
                        "min_required": bot.risk_params.min_risk_reward,
                        "entry_price": float(entry_price),
                        "stop_price": float(stop_price),
                        "primary_target": float(primary_target),
                        "shares": int(shares),
                    },
                )
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
                # 2026-04-30 v19.13 — initialize remaining_shares +
                # original_shares at TRADE-CREATE time, not on first
                # manage-loop tick. Pre-fix: a partial exit landing
                # before the first manage tick would decrement
                # remaining_shares while original_shares was still 0,
                # distorting all percentage-based scale-out math.
                remaining_shares=shares,
                original_shares=shares,
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
                    confidence_gate_result=confidence_gate_result,
                    multipliers_meta={
                        "position": position_multipliers,
                        "stop_guard": stop_guard_meta,
                        "target_snap": target_snap_meta,
                    },
                    # 2026-04-28f: AI module results were previously
                    # only landed under `explanation.ai_consultation`,
                    # making them invisible to the analytics + the
                    # Q3 verification curl. Now mirrored into
                    # `entry_context.ai_modules` for unified inspection.
                    ai_consultation_result=ai_consultation_result,
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
                            bot.record_rejection(
                                symbol=symbol, setup_type=setup_type, direction=direction_str,
                                reason_code="ai_consultation_block",
                                context={
                                    "why": consult_rec[:300],
                                    "shadow_decision_id": decision_id,
                                },
                            )
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
                    logger.warning(
                        "AI Consultation failed (proceeding anyway) (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )
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
                    logger.warning(
                        "AI evaluation failed (proceeding anyway) (%s): %s",
                        type(e).__name__, e, exc_info=True,
                    )

            print(f"   ✅ Returning trade object {trade.id}")

            # ==================== TRADE AUDIT LOG (P2 2026-04-23) ====================
            # Best-effort snapshot of the full decision trail for post-mortem
            # forensics. Never blocks trade flow.
            try:
                from services.trade_audit_service import record_audit_entry
                record_audit_entry(
                    getattr(bot, "_db", None),
                    trade,
                    gate_result=confidence_gate_result,
                    model_prediction=ai_prediction if "ai_prediction" in locals() else None,
                    regime=str(current_regime) if current_regime else None,
                    multipliers={
                        "smart_filter": smart_multiplier if "smart_multiplier" in locals() else None,
                        "confidence_gate": confidence_multiplier,
                        "regime": regime_multiplier if "regime_multiplier" in locals() else None,
                        "strategy_tilt": tilt_mult if "tilt_mult" in locals() else None,
                        "hrp_allocator": hrp_mult if "hrp_mult" in locals() else None,
                    },
                )
            except Exception as _audit_err:
                logger.debug(f"[TradeAudit] skipped: {_audit_err}")

            return trade

        except Exception as e:
            print(f"   ❌ Exception in _evaluate_opportunity: {e}")
            # 2026-04-30 v14: `logger.exception` writes the traceback
            # into the log line itself — `traceback.print_exc()` below
            # only reaches stdout, which can be lost when supervisor
            # rotates. Both paths kept so the operator's terminal AND
            # backend.log show the failure source.
            logger.exception(
                "Error evaluating opportunity (%s): %s",
                type(e).__name__, e,
            )
            import traceback
            traceback.print_exc()
            try:
                bot.record_rejection(
                    symbol=symbol if "symbol" in locals() else "?",
                    setup_type=setup_type if "setup_type" in locals() else "?",
                    direction=direction_str if "direction_str" in locals() else "long",
                    reason_code="evaluator_exception",
                    context={"error": str(e)[:300]},
                )
            except Exception:
                pass
            return None

    # ==================== HELPERS ====================

    def calculate_position_size(self, entry_price: float, stop_price: float, direction, bot: 'TradingBotService', atr: float = None, atr_percent: float = None, symbol: Optional[str] = None, bar_size: str = "5 mins", multipliers_out: Optional[Dict[str, Any]] = None) -> Tuple[int, float]:
        """Calculate position size based on risk management rules with volatility and market regime adjustment.

        2026-04-28e: also applies a Volume-Profile path multiplier — if the
        price corridor between entry and stop is sitting in a thick HVN
        cluster, the trade is downsized (chop-through risk). Skipped
        silently when `symbol` is None (legacy callers) or the profile
        can't be computed.

        If `multipliers_out` (a dict) is supplied, the function records
        per-multiplier values into it under keys `volatility`, `regime`,
        `vp_path` (each a float, default 1.0) — used by
        `build_entry_context` to surface multiplier provenance for
        post-trade analytics.
        """
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

        # ── Volume-Profile path multiplier (2026-04-28e) ──
        # Asks: how thick is the price corridor between entry and stop?
        # Thick HVN cluster → likely chop through stop → downsize.
        # Clean LVN airpocket → fast move on either side → full size.
        vp_path_multiplier = 1.0
        try:
            db = getattr(bot, "_db", None) or getattr(bot, "db", None)
            if symbol and db is not None:
                from services.smart_levels_service import compute_path_multiplier
                dir_str = "long" if direction == TradeDirection.LONG else "short"
                vpr = compute_path_multiplier(
                    db, symbol.upper(), bar_size,
                    float(entry_price), float(stop_price), dir_str,
                )
                vp_path_multiplier = float(vpr.get("multiplier", 1.0))
                if vp_path_multiplier < 1.0:
                    adjusted_max_risk *= vp_path_multiplier
                    logger.debug(
                        f"Position size adjusted by VP path ({vpr.get('reason')}, "
                        f"vol_pct={vpr.get('vol_pct')}): {vp_path_multiplier:.0%}"
                    )
        except Exception as exc:
            # Non-fatal: never let the profile lookup block trade execution.
            logger.debug(f"VP path multiplier skipped for {symbol}: {exc}")

        max_shares_by_risk = int(adjusted_max_risk / risk_per_share)
        max_position_value = bot.risk_params.starting_capital * (bot.risk_params.max_position_pct / 100)
        max_shares_by_capital = int(max_position_value / entry_price)

        # 2026-04-30 v19.4 — Absolute notional clamp.
        # `max_position_pct` floats with equity (50% of $1M = $500k vs 50%
        # of $250k = $125k). Operators often want a HARD ceiling (e.g.,
        # "never put more than $100k in one name regardless of equity")
        # so the bot doesn't auto-fatten when the paper account compounds.
        # Disabled when set to 0; otherwise the sizer can never produce a
        # notional larger than this value.
        max_notional = float(getattr(bot.risk_params, "max_notional_per_trade", 0) or 0)
        if max_notional > 0:
            max_shares_by_notional = int(max_notional / entry_price)
            shares = max(min(max_shares_by_risk, max_shares_by_capital, max_shares_by_notional), 1)
        else:
            shares = max(min(max_shares_by_risk, max_shares_by_capital), 1)
        risk_amount = shares * risk_per_share
        if risk_amount > adjusted_max_risk:
            shares = int(adjusted_max_risk / risk_per_share)
            risk_amount = shares * risk_per_share
        # Surface multiplier provenance for entry_context analytics.
        if multipliers_out is not None:
            multipliers_out.update({
                "volatility": round(volatility_multiplier, 3),
                "regime": round(regime_multiplier, 3),
                "vp_path": round(vp_path_multiplier, 3),
            })
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
        atr: float, atr_percent: float, confidence_gate_result: Dict = None,
        multipliers_meta: Optional[Dict[str, Any]] = None,
        ai_consultation_result: Optional[Dict[str, Any]] = None,
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
                "reasoning": confidence_gate_result.get("reasoning", [])[:5],
            }
            # Include live model prediction if available
            if confidence_gate_result.get("live_prediction"):
                pred = confidence_gate_result["live_prediction"]
                ctx["confidence_gate"]["live_prediction"] = {
                    "direction": pred.get("direction", "flat"),
                    "confidence": pred.get("confidence", 0),
                    "model_used": pred.get("model_used", ""),
                }
            # Include learning loop feedback if available
            if confidence_gate_result.get("learning_feedback"):
                fb = confidence_gate_result["learning_feedback"]
                ctx["confidence_gate"]["learning_feedback"] = {
                    "points": fb.get("points", 0),
                    "reasoning": fb.get("reasoning", ""),
                }
            # Include cross-model agreement (GAP 4)
            if confidence_gate_result.get("cross_model_agreement"):
                ctx["confidence_gate"]["cross_model_agreement"] = confidence_gate_result["cross_model_agreement"]

        # 9. Post-gate TQS recalculation (GAP 3: AI-enriched quality score)
        pre_gate_tqs = alert.get("tqs_score", 0)
        post_gate_tqs = alert.get("_post_gate_tqs_score")
        if post_gate_tqs:
            ctx["tqs"] = {
                "pre_gate_score": round(pre_gate_tqs, 1) if pre_gate_tqs else None,
                "post_gate_score": round(post_gate_tqs, 1),
                "post_gate_grade": alert.get("_post_gate_tqs_grade", ""),
                "post_gate_action": alert.get("_post_gate_tqs_action", ""),
                "delta": round(post_gate_tqs - pre_gate_tqs, 1) if pre_gate_tqs else None,
            }
        elif pre_gate_tqs:
            ctx["tqs"] = {
                "pre_gate_score": round(pre_gate_tqs, 1),
            }

        # 10. Liquidity-aware multipliers (2026-04-28e)
        # Captures the full provenance of every dial that touched the
        # trade: the volatility / regime / VP-path multipliers from
        # `calculate_position_size`, plus stop-guard + target-snap
        # results. Powers `/api/trading-bot/multiplier-analytics`.
        if multipliers_meta:
            mult_ctx: Dict[str, Any] = {}
            pos_m = multipliers_meta.get("position") or {}
            if pos_m:
                mult_ctx["volatility"] = pos_m.get("volatility", 1.0)
                mult_ctx["regime"]     = pos_m.get("regime", 1.0)
                mult_ctx["vp_path"]    = pos_m.get("vp_path", 1.0)

            sg = multipliers_meta.get("stop_guard") or {}
            if isinstance(sg, dict) and sg:
                mult_ctx["stop_guard"] = {
                    "snapped":        bool(sg.get("snapped", False)),
                    "reason":         sg.get("reason"),
                    "level_kind":     sg.get("level_kind"),
                    "level_price":    sg.get("level_price"),
                    "level_strength": sg.get("level_strength"),
                    "original_stop":  sg.get("original_stop"),
                    "widen_pct":      sg.get("widen_pct"),
                }

            ts = multipliers_meta.get("target_snap")
            if isinstance(ts, list) and ts:
                # Compact per-target snap log: only fields useful for analytics.
                mult_ctx["target_snap"] = [
                    {
                        "snapped":         bool(d.get("snapped", False)),
                        "reason":          d.get("reason"),
                        "level_kind":      d.get("level_kind"),
                        "level_price":     d.get("level_price"),
                        "shift_pct":       d.get("shift_pct"),
                        "original_target": d.get("original_target"),
                        "target":          d.get("target"),
                    }
                    for d in ts if isinstance(d, dict)
                ]

            if mult_ctx:
                ctx["multipliers"] = mult_ctx

        # 11. AI module decisions (2026-04-28f) — Bear/Bull debate,
        # AI risk manager, institutional flow, time series forecast.
        # Surfaced HERE in entry_context so they're queryable from
        # `bot_trades` and feed analytics + the Q3 verification curl.
        # Was previously only landing under `explanation.ai_consultation`.
        if ai_consultation_result and isinstance(ai_consultation_result, dict):
            ai_ctx: Dict[str, Any] = {
                "consulted":       True,
                "proceed":         bool(ai_consultation_result.get("proceed", True)),
                "size_adjustment": ai_consultation_result.get("size_adjustment"),
                "summary":         ai_consultation_result.get("summary"),
            }
            # Fold in per-module results when present
            for module_key, ec_key in (
                ("debate",         "debate"),
                ("risk_assessment","risk_manager"),
                ("institutional",  "institutional_flow"),
                ("time_series",    "time_series"),
            ):
                m = ai_consultation_result.get(module_key)
                if m:
                    ai_ctx[ec_key] = m
            ctx["ai_modules"] = ai_ctx

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
