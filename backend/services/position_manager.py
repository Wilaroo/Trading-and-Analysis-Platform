"""
Position Manager — Extracted from trading_bot_service.py

Handles open position lifecycle:
- P&L updates with IB/Alpaca price feeds
- MFE/MAE tracking
- Stop-loss monitoring (original + trailing)
- Scale-out target execution
- Partial exits
- Full trade close with commission, stats, and journal logging
- EOD auto-close
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages open position updates, scale-outs, closes, and EOD."""

    async def update_open_positions(self, bot: 'TradingBotService'):
        """Update P&L for open positions - uses IB data first, then Alpaca"""
        from services.trading_bot_service import TradeDirection, TradeStatus

        for trade_id, trade in list(bot._open_trades.items()):
            try:
                quote = None

                # Try IB pushed data first
                try:
                    from routers.ib import get_pushed_quotes, is_pusher_connected
                    if is_pusher_connected():
                        quotes = get_pushed_quotes()
                        if trade.symbol in quotes:
                            q = quotes[trade.symbol]
                            quote = {'price': q.get('last') or q.get('close') or 0}
                except Exception:
                    pass

                # Fallback to Alpaca
                if not quote and bot._alpaca_service:
                    quote = await bot._alpaca_service.get_quote(trade.symbol)

                if not quote:
                    continue

                trade.current_price = quote.get('price', trade.current_price)

                # Initialize remaining_shares if not set
                if trade.remaining_shares == 0:
                    trade.remaining_shares = trade.shares
                    trade.original_shares = trade.shares

                # Initialize trailing stop config if not set
                if trade.trailing_stop_config.get('original_stop', 0) == 0:
                    trade.trailing_stop_config['original_stop'] = trade.stop_price
                    trade.trailing_stop_config['current_stop'] = trade.stop_price
                    trade.trailing_stop_config['mode'] = 'original'

                # Calculate unrealized P&L on remaining shares
                if trade.direction == TradeDirection.LONG:
                    trade.unrealized_pnl = (trade.current_price - trade.fill_price) * trade.remaining_shares
                else:
                    trade.unrealized_pnl = (trade.fill_price - trade.current_price) * trade.remaining_shares

                # === MFE/MAE TRACKING ===
                # Track from moment of fill for the full trade lifecycle
                if trade.fill_price and trade.fill_price > 0:
                    risk_per_share = abs(trade.fill_price - trade.stop_price) if trade.stop_price else trade.fill_price * 0.02
                    if risk_per_share == 0:
                        risk_per_share = trade.fill_price * 0.02  # Fallback: 2% of entry

                    if trade.direction == TradeDirection.LONG:
                        # MFE: highest price since fill
                        if trade.current_price > trade.mfe_price or trade.mfe_price == 0:
                            trade.mfe_price = trade.current_price
                            trade.mfe_pct = ((trade.mfe_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mfe_r = (trade.mfe_price - trade.fill_price) / risk_per_share
                        # MAE: lowest price since fill
                        if trade.current_price < trade.mae_price or trade.mae_price == 0:
                            trade.mae_price = trade.current_price
                            trade.mae_pct = ((trade.mae_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mae_r = (trade.mae_price - trade.fill_price) / risk_per_share
                    else:  # SHORT
                        # MFE: lowest price since fill (favorable for shorts)
                        if trade.current_price < trade.mfe_price or trade.mfe_price == 0:
                            trade.mfe_price = trade.current_price
                            trade.mfe_pct = ((trade.fill_price - trade.mfe_price) / trade.fill_price) * 100
                            trade.mfe_r = (trade.fill_price - trade.mfe_price) / risk_per_share
                        # MAE: highest price since fill (adverse for shorts)
                        if trade.current_price > trade.mae_price or trade.mae_price == 0:
                            trade.mae_price = trade.current_price
                            trade.mae_pct = -((trade.mae_price - trade.fill_price) / trade.fill_price) * 100
                            trade.mae_r = -(trade.mae_price - trade.fill_price) / risk_per_share

                # Include realized P&L from partial exits
                total_value = trade.remaining_shares * trade.fill_price
                if total_value > 0:
                    trade.pnl_pct = ((trade.unrealized_pnl + trade.realized_pnl) / (trade.original_shares * trade.fill_price)) * 100

                # Update trailing stop if enabled
                if trade.trailing_stop_config.get('enabled', True):
                    await bot._update_trailing_stop(trade)

                # Automatic stop-loss monitoring using current_stop (which may be trailing)
                effective_stop = trade.trailing_stop_config.get('current_stop', trade.stop_price)
                stop_hit = False
                if trade.direction == TradeDirection.LONG:
                    if trade.current_price <= effective_stop:
                        stop_hit = True
                        logger.warning(f"STOP HIT: {trade.symbol} price ${trade.current_price:.2f} <= stop ${effective_stop:.2f} (mode: {trade.trailing_stop_config.get('mode')})")
                else:  # SHORT
                    if trade.current_price >= effective_stop:
                        stop_hit = True
                        logger.warning(f"STOP HIT: {trade.symbol} price ${trade.current_price:.2f} >= stop ${effective_stop:.2f} (mode: {trade.trailing_stop_config.get('mode')})")

                if stop_hit:
                    stop_mode = trade.trailing_stop_config.get('mode', 'original')
                    reason = f"stop_loss_{stop_mode}" if stop_mode != 'original' else "stop_loss"
                    logger.info(f"Auto-closing {trade.symbol} due to {stop_mode} stop trigger")
                    await self.close_trade(trade_id, bot, reason=reason)
                    continue

                # Automatic target profit-taking with scale-out
                if trade.target_prices and trade.scale_out_config.get('enabled', True):
                    await self.check_and_execute_scale_out(trade, bot)

                await bot._notify_trade_update(trade, "updated")

            except Exception as e:
                logger.error(f"Error updating position {trade_id}: {e}")

    async def check_eod_close(self, bot: 'TradingBotService'):
        """
        Close ALL open positions near market close (default: 3:57 PM ET).
        This is a critical risk management feature to avoid overnight exposure.
        """
        if not bot._eod_close_enabled:
            return

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))
        today_str = now_et.strftime("%Y-%m-%d")

        # Reset the executed flag if it's a new day
        if bot._last_eod_check_date != today_str:
            bot._eod_close_executed_today = False
            bot._last_eod_check_date = today_str

        # Skip if already executed today
        if bot._eod_close_executed_today:
            return

        # Only run on weekdays during market hours
        if now_et.weekday() >= 5:
            return

        # Check if we're in the EOD close window
        eod_hour = bot._eod_close_hour
        eod_minute = bot._eod_close_minute

        # Not yet time to close
        if now_et.hour < eod_hour or (now_et.hour == eod_hour and now_et.minute < eod_minute):
            return

        # After 4:00 PM, stop checking (market closed)
        if now_et.hour >= 16:
            return

        # Time to close all positions!
        open_count = len(bot._open_trades)
        if open_count == 0:
            bot._eod_close_executed_today = True
            return

        logger.info(f"🔔 EOD AUTO-CLOSE: Closing all {open_count} open positions at {now_et.strftime('%H:%M:%S')} ET")

        closed_count = 0
        total_pnl = 0.0

        for trade_id, trade in list(bot._open_trades.items()):
            try:
                logger.info(f"  📤 EOD CLOSE: {trade.symbol} - {trade.direction.value} {trade.remaining_shares} shares")
                result = await self.close_trade(trade_id, bot, reason="eod_auto_close")
                if result.get("success"):
                    closed_count += 1
                    total_pnl += result.get("realized_pnl", 0)
                else:
                    logger.error(f"  ❌ Failed to close {trade.symbol}: {result.get('error')}")
            except Exception as e:
                logger.error(f"  ❌ Error closing {trade.symbol}: {e}")

        bot._eod_close_executed_today = True

        # Persist the EOD close event
        if bot._db:
            eod_event = {
                "event_type": "eod_auto_close",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "date": today_str,
                "positions_closed": closed_count,
                "total_pnl": total_pnl,
                "close_time_et": now_et.strftime("%H:%M:%S")
            }
            await asyncio.to_thread(bot._db.bot_events.insert_one, eod_event)

        logger.info(f"✅ EOD AUTO-CLOSE COMPLETE: Closed {closed_count} positions, Total P&L: ${total_pnl:+,.2f}")

    async def check_and_execute_scale_out(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """
        Check if any target prices are hit and execute scale-out sells.
        Sells 1/3 at Target 1, 1/3 at Target 2, keeps 1/3 for Target 3 (runner).
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        if not trade.target_prices or trade.remaining_shares <= 0:
            return

        targets_hit = trade.scale_out_config.get('targets_hit', [])
        scale_out_pcts = trade.scale_out_config.get('scale_out_pcts', [0.33, 0.33, 0.34])

        for i, target in enumerate(trade.target_prices):
            if i in targets_hit:
                continue  # Already sold at this target

            # Check if target is hit
            target_hit = False
            if trade.direction == TradeDirection.LONG:
                if trade.current_price >= target:
                    target_hit = True
            else:  # SHORT
                if trade.current_price <= target:
                    target_hit = True

            if target_hit:
                # Calculate shares to sell at this target
                pct_to_sell = scale_out_pcts[i] if i < len(scale_out_pcts) else 0.34

                # For last target, sell all remaining
                if i == len(trade.target_prices) - 1:
                    shares_to_sell = trade.remaining_shares
                else:
                    shares_to_sell = max(1, int(trade.original_shares * pct_to_sell))
                    shares_to_sell = min(shares_to_sell, trade.remaining_shares)

                if shares_to_sell <= 0:
                    continue

                logger.info(f"TARGET {i+1} HIT: {trade.symbol} - Scaling out {shares_to_sell} shares at ${trade.current_price:.2f}")

                # Execute partial exit
                exit_result = await self.execute_partial_exit(trade, shares_to_sell, target, i, bot)

                if exit_result.get('success'):
                    fill_price = exit_result.get('fill_price', trade.current_price)

                    # Calculate P&L for this scale-out
                    if trade.direction == TradeDirection.LONG:
                        partial_pnl = (fill_price - trade.fill_price) * shares_to_sell
                    else:
                        partial_pnl = (trade.fill_price - fill_price) * shares_to_sell

                    # Update trade state
                    trade.remaining_shares -= shares_to_sell
                    trade.realized_pnl += partial_pnl

                    # Track commission for partial exit
                    scale_commission = bot._apply_commission(trade, shares_to_sell)

                    targets_hit.append(i)
                    trade.scale_out_config['targets_hit'] = targets_hit

                    # Record the partial exit
                    partial_exit_record = {
                        'target_idx': i + 1,
                        'target_price': target,
                        'shares_sold': shares_to_sell,
                        'fill_price': fill_price,
                        'pnl': partial_pnl,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                    trade.scale_out_config.setdefault('partial_exits', []).append(partial_exit_record)

                    logger.info(f"Scale-out complete: {trade.symbol} T{i+1} - Sold {shares_to_sell} @ ${fill_price:.2f}, P&L: ${partial_pnl:.2f}, Remaining: {trade.remaining_shares}")

                    await bot._notify_trade_update(trade, f"scale_out_t{i+1}")

                    # If all shares sold, close the trade
                    if trade.remaining_shares <= 0:
                        trade.status = TradeStatus.CLOSED
                        trade.closed_at = datetime.now(timezone.utc).isoformat()
                        trade.close_reason = f"target_{i+1}_complete"
                        trade.exit_price = fill_price
                        trade.unrealized_pnl = 0

                        # Update daily stats with net P&L (after commissions)
                        if trade.net_pnl > 0:
                            bot._daily_stats.trades_won += 1
                            bot._daily_stats.largest_win = max(bot._daily_stats.largest_win, trade.net_pnl)
                        else:
                            bot._daily_stats.trades_lost += 1
                            bot._daily_stats.largest_loss = min(bot._daily_stats.largest_loss, trade.net_pnl)

                        bot._daily_stats.net_pnl += trade.net_pnl
                        total = bot._daily_stats.trades_won + bot._daily_stats.trades_lost
                        bot._daily_stats.win_rate = (bot._daily_stats.trades_won / total * 100) if total > 0 else 0

                        # Move to closed trades
                        del bot._open_trades[trade.id]
                        bot._closed_trades.append(trade)

                        await bot._notify_trade_update(trade, "closed")
                        await bot._save_trade(trade)

                        # Log to regime performance tracking
                        await bot._log_trade_to_regime_performance(trade)

                        logger.info(f"Trade fully closed at Target {i+1}: {trade.symbol} Total P&L: ${trade.realized_pnl:.2f}")
                        return

    async def execute_partial_exit(self, trade: 'BotTrade', shares: int, target_price: float, target_idx: int, bot: 'TradingBotService') -> Dict:
        """Execute a partial position exit (scale-out)"""
        if not bot._trade_executor:
            # Simulated exit
            return {
                'success': True,
                'fill_price': trade.current_price,
                'shares': shares,
                'simulated': True
            }

        try:
            # Use trade executor to sell partial position
            result = await bot._trade_executor.execute_partial_exit(trade, shares)
            return result
        except Exception as e:
            logger.error(f"Partial exit error: {e}")
            # Fall back to simulated
            return {
                'success': True,
                'fill_price': trade.current_price,
                'shares': shares,
                'simulated': True
            }

    async def close_trade(self, trade_id: str, bot: 'TradingBotService', reason: str = "manual"):
        """Close an open trade (sells remaining shares)"""
        from services.trading_bot_service import TradeDirection, TradeStatus

        if trade_id not in bot._open_trades:
            return False

        trade = bot._open_trades[trade_id]

        # Use remaining shares if we've done partial exits, otherwise use original shares
        shares_to_close = trade.remaining_shares if trade.remaining_shares > 0 else trade.shares

        try:
            if bot._trade_executor and shares_to_close > 0:
                # Update trade.shares temporarily for the executor
                original_shares = trade.shares
                trade.shares = shares_to_close

                result = await bot._trade_executor.close_position(trade)

                trade.shares = original_shares  # Restore

                if result.get('success'):
                    trade.exit_price = result.get('fill_price', trade.current_price)
            else:
                trade.exit_price = trade.current_price

            # Calculate realized P&L for remaining shares and add to cumulative
            if shares_to_close > 0:
                if trade.direction == TradeDirection.LONG:
                    final_pnl = (trade.exit_price - trade.fill_price) * shares_to_close
                else:
                    final_pnl = (trade.fill_price - trade.exit_price) * shares_to_close
                trade.realized_pnl += final_pnl

                # Track exit commission
                exit_commission = bot._apply_commission(trade, shares_to_close)
                logger.info(f"Exit commission: ${exit_commission:.2f} | Total commissions: ${trade.total_commissions:.2f} | Net P&L: ${trade.net_pnl:.2f}")

            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.now(timezone.utc).isoformat()
            trade.close_reason = reason
            trade.unrealized_pnl = 0
            trade.remaining_shares = 0

            # Update daily stats with net P&L (after commissions)
            bot._daily_stats.net_pnl += trade.net_pnl
            if trade.realized_pnl > 0:
                bot._daily_stats.trades_won += 1
                bot._daily_stats.largest_win = max(bot._daily_stats.largest_win, trade.realized_pnl)
            else:
                bot._daily_stats.trades_lost += 1
                bot._daily_stats.largest_loss = min(bot._daily_stats.largest_loss, trade.realized_pnl)

            # Calculate win rate
            total = bot._daily_stats.trades_won + bot._daily_stats.trades_lost
            bot._daily_stats.win_rate = (bot._daily_stats.trades_won / total * 100) if total > 0 else 0

            # Move to closed trades
            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)

            await bot._notify_trade_update(trade, "closed")
            await bot._save_trade(trade)

            # Auto-record exit to Trade Journal
            await bot._log_trade_to_journal(trade, "exit")

            # Record performance for learning loop
            if hasattr(bot, '_perf_service') and bot._perf_service:
                try:
                    bot._perf_service.record_trade(trade.to_dict())
                except Exception as e:
                    logger.warning(f"Failed to record trade performance: {e}")

            # NEW: Record to Learning Loop (Phase 1)
            if hasattr(bot, '_learning_loop') and bot._learning_loop:
                try:
                    outcome = "won" if trade.realized_pnl > 0 else ("lost" if trade.realized_pnl < 0 else "breakeven")
                    asyncio.create_task(bot._learning_loop.record_trade_outcome(
                        trade_id=trade.id,
                        alert_id=getattr(trade, 'alert_id', trade.id),
                        symbol=trade.symbol,
                        setup_type=trade.setup_type,
                        strategy_name=trade.setup_type,
                        direction=trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction),
                        trade_style=getattr(trade, 'trade_style', 'move_2_move'),
                        entry_price=trade.fill_price,
                        exit_price=trade.exit_price,
                        stop_price=trade.stop_loss,
                        target_price=trade.targets[0] if trade.targets else trade.fill_price * 1.02,
                        outcome=outcome,
                        pnl=trade.realized_pnl,
                        entry_time=trade.opened_at,
                        exit_time=trade.closed_at,
                        confirmation_signals=getattr(trade, 'confirmation_signals', [])
                    ))
                except Exception as e:
                    logger.warning(f"Failed to record trade to learning loop: {e}")

            # Log to regime performance tracking
            await bot._log_trade_to_regime_performance(trade)

            logger.info(f"Trade closed ({reason}): {trade.symbol} P&L: ${trade.realized_pnl:.2f}")
            return True

        except Exception as e:
            logger.error(f"Error closing trade: {e}")
            return False
