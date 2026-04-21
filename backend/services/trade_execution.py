"""
Trade Execution — Extracted from trading_bot_service.py

Handles:
- Trade execution (strategy phase check → broker execution)
- Trade confirmation (stale alert check, price recalculation)
- Trade rejection
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class TradeExecution:
    """Manages trade execution, confirmation, and rejection logic."""

    async def execute_trade(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """
        Execute a trade via the trade executor.

        Strategy Phase Check (SIM → PAPER → LIVE):
        - LIVE: Execute real trade via broker
        - PAPER: Record paper trade, do not execute
        - SIMULATION: Skip entirely (not ready for real-time)

        In AUTONOMOUS mode with IB data:
        - Uses live IB prices for decision-making
        - Currently executes in SIMULATED mode (orders tracked but not sent to broker)
        - Full IB order execution requires local IB Gateway order routing (future enhancement)
        """
        from services.trading_bot_service import TradeStatus

        print(f"   📤 [_execute_trade] Starting execution for {trade.symbol}")

        # === STRATEGY PHASE CHECK ===
        # This is the gate that controls which strategies execute real trades
        if bot._strategy_promotion_service:
            should_execute, phase_reason, should_paper = bot._strategy_promotion_service.should_execute_trade(trade.setup_type)

            if not should_execute:
                if should_paper:
                    # PAPER PHASE: Record the trade without executing
                    logger.info(f"📝 [PAPER TRADE] {trade.symbol} {trade.direction.value.upper()} - {phase_reason}")
                    trade.notes = (trade.notes or "") + f" [PAPER: {phase_reason}]"

                    # Record paper trade for tracking
                    try:
                        paper_trade_id = await bot._strategy_promotion_service.record_paper_trade(
                            strategy_name=trade.setup_type,
                            symbol=trade.symbol,
                            direction=trade.direction.value,
                            entry_price=trade.entry_price,
                            stop_price=trade.stop_price,
                            target_price=trade.target_prices[0] if trade.target_prices else trade.entry_price * 1.02,
                            notes=f"Would have traded: {trade.shares} shares | R:R={trade.risk_reward_ratio:.1f}"
                        )
                        logger.info(f"📝 Paper trade recorded: {paper_trade_id}")

                        # Add to filter thoughts for visibility
                        bot._add_filter_thought({
                            "text": f"📝 PAPER: {trade.symbol} {trade.setup_type} ({trade.direction.value}) - Strategy not yet LIVE",
                            "symbol": trade.symbol,
                            "setup_type": trade.setup_type,
                            "action": "PAPER_TRACKED",
                            "phase": "paper"
                        })
                    except Exception as e:
                        logger.warning(f"Failed to record paper trade: {e}")

                    # Mark trade as not executed (for UI feedback)
                    trade.status = TradeStatus.PAPER
                    trade.close_reason = "paper_phase"
                    await bot._save_trade(trade)
                    return
                else:
                    # SIMULATION PHASE: Skip entirely
                    logger.info(f"⏭️ [SKIPPED] {trade.symbol} {trade.direction.value.upper()} - {phase_reason}")
                    trade.notes = (trade.notes or "") + f" [SKIPPED: {phase_reason}]"
                    trade.status = TradeStatus.SIMULATED
                    trade.close_reason = "simulation_phase"
                    await bot._save_trade(trade)
                    return
            else:
                # LIVE PHASE: Proceed with execution
                logger.info(f"🚀 [LIVE STRATEGY] {trade.symbol} {trade.setup_type} - Executing real trade")

        if not bot._trade_executor:
            print("   ❌ Trade executor not configured")
            logger.error("Trade executor not configured")
            return

        try:
            # Log execution mode
            executor_mode = bot._trade_executor.get_mode() if bot._trade_executor else "unknown"
            print(f"   📤 [_execute_trade] Executor mode: {executor_mode.value if hasattr(executor_mode, 'value') else executor_mode}")
            logger.info(f"[TradingBot] Executing {trade.symbol} {trade.direction.value.upper()} | Mode: {executor_mode.value}")

            # Start execution tracking (Phase 1 Learning)
            if hasattr(bot, '_learning_loop') and bot._learning_loop:
                try:
                    # Use target_prices instead of targets
                    planned_r = (trade.target_prices[0] / trade.entry_price - 1) if trade.target_prices else 2.0
                    bot._learning_loop.start_execution_tracking(
                        trade_id=trade.id,
                        alert_id=getattr(trade, 'alert_id', trade.id),
                        intended_entry=trade.entry_price,
                        intended_size=trade.shares,
                        planned_r=planned_r
                    )
                except Exception as e:
                    logger.warning(f"Failed to start execution tracking: {e}")

            # === PRE-EXECUTION GUARD RAILS (2026-04-21) ===
            # Block pathologically tight stops and oversized positions BEFORE
            # any order hits the broker. See services/execution_guardrails.py
            # and memory/IB_BRACKET_ORDER_MIGRATION.md for the audit that
            # motivated these (USO $0.03 stop on a $108 stock = -261R bleed).
            try:
                from services.execution_guardrails import run_all_guardrails

                # Best-effort ATR lookup — fall back to None if unavailable
                atr_14 = getattr(trade, "atr_14", None)
                if atr_14 is None and hasattr(bot, "_atr_cache"):
                    atr_14 = bot._atr_cache.get(trade.symbol)

                account_equity = None
                try:
                    if bot._trade_executor and hasattr(bot._trade_executor, "get_account_info"):
                        acct = await bot._trade_executor.get_account_info()
                        if isinstance(acct, dict):
                            account_equity = acct.get("equity") or acct.get("portfolio_value")
                except Exception:
                    account_equity = None

                veto = run_all_guardrails(
                    entry_price=trade.entry_price,
                    stop_price=trade.stop_price,
                    shares=trade.shares,
                    atr_14=atr_14,
                    account_equity=account_equity,
                )
                if veto.skip:
                    logger.warning(f"🛡️ [Guardrail VETO] {trade.symbol}: {veto.reason}")
                    print(f"   🛡️ [Guardrail VETO] {trade.symbol}: {veto.reason}")
                    trade.status = TradeStatus.VETOED
                    trade.notes = (trade.notes or "") + f" [GUARDRAIL: {veto.reason}]"
                    trade.close_reason = "guardrail_veto"
                    if trade.id in bot._pending_trades:
                        del bot._pending_trades[trade.id]
                    await bot._save_trade(trade)
                    return
            except Exception as e:
                logger.warning(f"Guardrail check failed (allowing trade): {e}")

            # Execute entry order — Phase 3 (2026-04-22): prefer atomic bracket
            # over the legacy two-step entry→stop flow so stops can't die on
            # bot restart. Falls back automatically if pusher hasn't been
            # upgraded yet (Phase 2 pusher contract in PUSHER_BRACKET_SPEC.md).
            print("   📤 [_execute_trade] Calling trade_executor.place_bracket_order...")
            bracket_result = await bot._trade_executor.place_bracket_order(trade)
            use_legacy = (
                not bracket_result.get('success') and
                bracket_result.get('fallback') == 'legacy' or
                bracket_result.get('error') in ('bracket_not_supported',
                                                'alpaca_bracket_not_implemented',
                                                'bracket_missing_stop_or_target')
            )
            if use_legacy:
                logger.info("Bracket unavailable → legacy entry+stop path")
                print("   ↩️ [_execute_trade] Falling back to legacy execute_entry+place_stop_order")
                result = await bot._trade_executor.execute_entry(trade)
            else:
                # Translate bracket result into the legacy `result` dict shape
                # so downstream code doesn't have to change.
                result = {
                    "success": bracket_result.get("success"),
                    "order_id": bracket_result.get("entry_order_id"),
                    "fill_price": bracket_result.get("fill_price", trade.entry_price),
                    "filled_qty": bracket_result.get("filled_qty", 0),
                    "status": bracket_result.get("status"),
                    "broker": bracket_result.get("broker", "interactive_brokers"),
                    "simulated": bracket_result.get("simulated", False),
                    "error": bracket_result.get("error"),
                    "bracket": True,  # flag so we skip the separate stop placement
                    "stop_order_id": bracket_result.get("stop_order_id"),
                    "target_order_id": bracket_result.get("target_order_id"),
                    "oca_group": bracket_result.get("oca_group"),
                }
            print(f"   📤 [_execute_trade] Result: {result}")

            if result.get('success'):
                trade.status = TradeStatus.OPEN
                trade.fill_price = result.get('fill_price', trade.entry_price)
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')

                # Initialize MFE/MAE at fill price (starting point)
                trade.mfe_price = trade.fill_price
                trade.mae_price = trade.fill_price

                # Track entry commission
                entry_commission = bot._apply_commission(trade, trade.shares)

                # Mark if simulated
                if result.get('simulated'):
                    trade.notes = (trade.notes or "") + " [SIMULATED]"
                else:
                    broker = result.get('broker', 'unknown')
                    tag = "BRACKET" if result.get('bracket') else "LIVE"
                    trade.notes = (trade.notes or "") + f" [{tag}-{broker.upper()}]"

                print(f"   💰 Entry commission: ${entry_commission:.2f} ({trade.shares} shares @ ${trade.commission_per_share}/share)")

                # Record actual entry (Phase 1 Learning)
                if hasattr(bot, '_learning_loop') and bot._learning_loop:
                    try:
                        bot._learning_loop.record_trade_entry(
                            trade_id=trade.id,
                            actual_entry=trade.fill_price,
                            actual_size=trade.shares
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record entry: {e}")

                # Stop handling — bracket already placed the stop atomically,
                # otherwise place it sequentially (legacy path)
                if result.get('bracket'):
                    trade.stop_order_id = result.get('stop_order_id')
                    trade.target_order_id = result.get('target_order_id')
                    if result.get('oca_group'):
                        trade.notes = (trade.notes or "") + f" [OCA:{result['oca_group']}]"
                else:
                    stop_result = await bot._trade_executor.place_stop_order(trade)
                    if stop_result.get('success'):
                        trade.stop_order_id = stop_result.get('order_id')

                # Move to open trades
                if trade.id in bot._pending_trades:
                    del bot._pending_trades[trade.id]
                bot._open_trades[trade.id] = trade

                # Update stats
                bot._daily_stats.trades_executed += 1

                await bot._notify_trade_update(trade, "executed")
                await bot._save_trade(trade)

                # Auto-record to Trade Journal
                await bot._log_trade_to_journal(trade, "entry")

                sim_tag = " (SIMULATED)" if result.get('simulated') else ""
                logger.info(f"✅ Trade executed{sim_tag}: {trade.symbol} {trade.shares} @ ${trade.fill_price:.2f}")

            elif result.get('status') == 'timeout':
                # TIMEOUT HANDLING: Order may still execute - save as pending for sync
                trade.status = TradeStatus.OPEN  # Assume it went through
                trade.fill_price = trade.entry_price  # Use intended price
                trade.executed_at = datetime.now(timezone.utc).isoformat()
                trade.entry_order_id = result.get('order_id')
                trade.notes = (trade.notes or "") + " [TIMEOUT-NEEDS-SYNC]"

                # Initialize MFE/MAE
                trade.mfe_price = trade.fill_price
                trade.mae_price = trade.fill_price

                # Move to open trades so bot tracks it
                if trade.id in bot._pending_trades:
                    del bot._pending_trades[trade.id]
                bot._open_trades[trade.id] = trade

                # Update stats
                bot._daily_stats.trades_executed += 1

                await bot._save_trade(trade)

                logger.warning(f"⚠️ Trade timeout but saved for sync: {trade.symbol} {trade.shares} shares - will verify with IB")

            else:
                trade.status = TradeStatus.REJECTED
                logger.warning(f"Trade rejected: {result.get('error')}")

        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            trade.status = TradeStatus.REJECTED

    async def confirm_trade(self, trade_id: str, bot: 'TradingBotService') -> bool:
        """
        Confirm a pending trade for execution.

        Before executing:
        1. Check if the alert is stale (expired based on timeframe)
        2. Recalculate entry price, shares, and risk based on current market price
        """
        from services.trading_bot_service import TradeStatus

        if trade_id not in bot._pending_trades:
            return False

        trade = bot._pending_trades[trade_id]

        # === STALE ALERT CHECK ===
        # Scalps/intraday: 5 min timeout. Swings: 15 min. Investment: 60 min.
        stale_thresholds = {
            "scalp": 300,      # 5 min
            "day": 600,        # 10 min
            "swing": 900,      # 15 min
            "investment": 3600, # 60 min
        }
        max_age_seconds = stale_thresholds.get(trade.timeframe, 600)  # Default 10 min

        if trade.created_at:
            try:
                created = datetime.fromisoformat(trade.created_at.replace('Z', '+00:00'))
                age = (datetime.now(timezone.utc) - created).total_seconds()
                if age > max_age_seconds:
                    logger.info(f"Stale alert: {trade.symbol} {trade.setup_type} is {age:.0f}s old (max {max_age_seconds}s for {trade.timeframe})")
                    trade.status = TradeStatus.REJECTED
                    trade.notes = (trade.notes or "") + f" [EXPIRED: {age:.0f}s old]"
                    del bot._pending_trades[trade_id]
                    await bot._notify_trade_update(trade, "expired")
                    return False
            except Exception as e:
                logger.warning(f"Could not check alert age: {e}")

        # === PRICE RECALCULATION ===
        # Get current market price and recalculate position
        current_price = None
        try:
            from routers.ib import get_pushed_quotes, is_pusher_connected
            if is_pusher_connected():
                quotes = get_pushed_quotes()
                if trade.symbol in quotes:
                    q = quotes[trade.symbol]
                    current_price = q.get('last') or q.get('close')
        except Exception:
            pass

        if not current_price and bot._alpaca_service:
            try:
                quote = await bot._alpaca_service.get_quote(trade.symbol)
                current_price = quote.get('price') if quote else None
            except Exception:
                pass

        if current_price and current_price != trade.entry_price:
            old_entry = trade.entry_price
            old_shares = trade.shares
            trade.entry_price = current_price

            # Recalculate shares based on new entry and original stop
            if trade.stop_price and trade.stop_price != trade.entry_price:
                risk_per_share = abs(trade.entry_price - trade.stop_price)
                if risk_per_share > 0:
                    risk_amount = bot.risk_params.max_risk_per_trade
                    new_shares = max(1, int(risk_amount / risk_per_share))
                    trade.shares = new_shares
                    trade.remaining_shares = new_shares
                    trade.original_shares = new_shares

            # Recalculate targets proportionally
            if hasattr(trade, 'scale_out_config') and trade.scale_out_config.get('target_prices'):
                old_targets = trade.scale_out_config['target_prices']
                if old_entry and old_entry != 0:
                    ratio = current_price / old_entry
                    trade.scale_out_config['target_prices'] = [round(t * ratio, 2) for t in old_targets]

            logger.info(
                f"Price recalc on confirm: {trade.symbol} entry ${old_entry:.2f}→${current_price:.2f}, "
                f"shares {old_shares}→{trade.shares}"
            )
            print(f"   🔄 [CONFIRM] Price adjusted: ${old_entry:.2f}→${current_price:.2f}, shares {old_shares}→{trade.shares}")

        await self.execute_trade(trade, bot)

        # Treat every terminal status the pre-trade pipeline can *legitimately*
        # assign as a success. Previously only OPEN counted, so correctly-filtered
        # trades (phase gate → SIMULATED/PAPER, guardrail → VETOED) were
        # reported as API failures (400). The router distinguishes these from
        # a genuine REJECTED via the trade's status field in the response.
        HANDLED_STATUSES = {
            TradeStatus.OPEN,
            TradeStatus.PARTIAL,
            TradeStatus.SIMULATED,
            TradeStatus.VETOED,
            TradeStatus.PAPER,
        }
        return trade.status in HANDLED_STATUSES

    async def reject_trade(self, trade_id: str, bot: 'TradingBotService') -> bool:
        """Reject a pending trade"""
        from services.trading_bot_service import TradeStatus

        if trade_id not in bot._pending_trades:
            return False

        trade = bot._pending_trades[trade_id]
        trade.status = TradeStatus.REJECTED
        del bot._pending_trades[trade_id]
        await bot._notify_trade_update(trade, "rejected")
        return True
