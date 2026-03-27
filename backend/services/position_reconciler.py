"""
Position Reconciler — Extracted from trading_bot_service.py

Handles IB position reconciliation:
- Compare bot positions vs IB positions
- Sync untracked positions from IB
- Close phantom positions (bot tracks, IB doesn't)
- Full position sync with automatic resolution
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import TradingBotService

logger = logging.getLogger(__name__)


class PositionReconciler:
    """Manages IB position reconciliation and sync."""

    async def reconcile_positions_with_ib(self, bot: 'TradingBotService') -> Dict:
        """
        Reconcile bot's internal trades with actual IB positions.
        Returns a report of discrepancies and optionally syncs them.

        This is critical for:
        1. Session persistence - ensuring state matches reality after restart
        2. Detecting manual trades made outside the bot
        3. Catching missed fills or order execution issues
        """
        from services.trading_bot_service import TradeDirection

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bot_positions": [],
            "ib_positions": [],
            "discrepancies": [],
            "synced": False,
            "actions_taken": []
        }

        try:
            # Get IB positions from pushed data
            from routers.ib import _pushed_ib_data, is_pusher_connected

            if not is_pusher_connected():
                report["error"] = "IB pusher not connected - cannot reconcile"
                return report

            ib_positions = _pushed_ib_data.get("positions", [])

            # Convert to comparable format
            ib_pos_map = {}
            for pos in ib_positions:
                symbol = pos.get("symbol", pos.get("contract", {}).get("symbol", ""))
                if symbol:
                    qty = float(pos.get("position", pos.get("qty", 0)))
                    ib_pos_map[symbol] = {
                        "symbol": symbol,
                        "qty": qty,
                        "avg_cost": float(pos.get("avgCost", pos.get("avg_cost", 0))),
                        "market_value": float(pos.get("marketValue", pos.get("market_value", 0))),
                        "unrealized_pnl": float(pos.get("unrealizedPNL", pos.get("unrealized_pnl", 0)))
                    }
                    report["ib_positions"].append(ib_pos_map[symbol])

            # Get bot's open trades
            bot_pos_map = {}
            for trade in bot._open_trades.values():
                symbol = trade.symbol
                # Account for direction
                qty = trade.remaining_shares if trade.direction == TradeDirection.LONG else -trade.remaining_shares
                bot_pos_map[symbol] = {
                    "symbol": symbol,
                    "qty": qty,
                    "trade_id": trade.id,
                    "fill_price": trade.fill_price,
                    "direction": trade.direction.value
                }
                report["bot_positions"].append(bot_pos_map[symbol])

            # Find discrepancies
            all_symbols = set(ib_pos_map.keys()) | set(bot_pos_map.keys())

            for symbol in all_symbols:
                ib_pos = ib_pos_map.get(symbol)
                bot_pos = bot_pos_map.get(symbol)

                if ib_pos and not bot_pos:
                    # Position exists in IB but not tracked by bot
                    report["discrepancies"].append({
                        "type": "untracked_position",
                        "symbol": symbol,
                        "ib_qty": ib_pos["qty"],
                        "bot_qty": 0,
                        "message": f"{symbol}: Position in IB ({ib_pos['qty']} shares) not tracked by bot"
                    })

                elif bot_pos and not ib_pos:
                    # Bot thinks we have a position but IB doesn't show it
                    report["discrepancies"].append({
                        "type": "phantom_position",
                        "symbol": symbol,
                        "ib_qty": 0,
                        "bot_qty": bot_pos["qty"],
                        "trade_id": bot_pos["trade_id"],
                        "message": f"{symbol}: Bot tracking position ({bot_pos['qty']} shares) but not in IB - may have been closed"
                    })

                elif ib_pos and bot_pos:
                    # Both have position - check if quantities match
                    ib_qty = ib_pos["qty"]
                    bot_qty = bot_pos["qty"]

                    if abs(ib_qty - bot_qty) > 0.1:  # Allow small floating point differences
                        report["discrepancies"].append({
                            "type": "quantity_mismatch",
                            "symbol": symbol,
                            "ib_qty": ib_qty,
                            "bot_qty": bot_qty,
                            "trade_id": bot_pos["trade_id"],
                            "message": f"{symbol}: IB shows {ib_qty} shares, bot tracking {bot_qty} shares"
                        })

            report["synced"] = len(report["discrepancies"]) == 0

            if report["discrepancies"]:
                logger.warning(f"Position reconciliation found {len(report['discrepancies'])} discrepancies")
                for d in report["discrepancies"]:
                    logger.warning(f"  - {d['message']}")
            else:
                logger.info("Position reconciliation: All positions match ✓")

            return report

        except Exception as e:
            logger.error(f"Position reconciliation error: {e}")
            report["error"] = str(e)
            return report

    async def sync_position_from_ib(self, symbol: str, bot: 'TradingBotService', auto_create_trade: bool = False) -> Dict:
        """
        Sync a single position from IB to the bot's tracking.
        Use this to import positions that were opened manually or outside the bot.

        Args:
            symbol: Stock symbol to sync
            bot: TradingBotService instance
            auto_create_trade: If True, automatically create a bot trade entry for untracked positions

        Returns:
            Dict with sync result
        """
        from services.trading_bot_service import TradeDirection, TradeStatus, BotTrade

        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected

            if not is_pusher_connected():
                return {"success": False, "error": "IB pusher not connected"}

            ib_positions = _pushed_ib_data.get("positions", [])
            ib_pos = None

            for pos in ib_positions:
                pos_symbol = pos.get("symbol", pos.get("contract", {}).get("symbol", ""))
                if pos_symbol.upper() == symbol.upper():
                    ib_pos = pos
                    break

            if not ib_pos:
                return {"success": False, "error": f"No IB position found for {symbol}"}

            qty = float(ib_pos.get("position", ib_pos.get("qty", 0)))
            avg_cost = float(ib_pos.get("avgCost", ib_pos.get("avg_cost", 0)))

            # Check if bot already tracks this
            existing_trade = None
            for trade in bot._open_trades.values():
                if trade.symbol.upper() == symbol.upper():
                    existing_trade = trade
                    break

            if existing_trade:
                # Update existing trade
                existing_trade.remaining_shares = abs(qty)
                existing_trade.shares = abs(qty)
                existing_trade.fill_price = avg_cost
                logger.info(f"Updated existing trade for {symbol}: {qty} shares @ ${avg_cost:.2f}")
                return {
                    "success": True,
                    "action": "updated",
                    "trade_id": existing_trade.id,
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost
                }

            elif auto_create_trade:
                # Create new trade entry for this position
                direction = TradeDirection.LONG if qty > 0 else TradeDirection.SHORT

                # Calculate price levels
                target_1 = avg_cost * 1.05 if direction == TradeDirection.LONG else avg_cost * 0.95
                target_2 = avg_cost * 1.10 if direction == TradeDirection.LONG else avg_cost * 0.90
                target_3 = avg_cost * 1.15 if direction == TradeDirection.LONG else avg_cost * 0.85
                stop = avg_cost * 0.95 if direction == TradeDirection.LONG else avg_cost * 1.05

                risk_per_share = abs(avg_cost - stop)
                reward_per_share = abs(target_2 - avg_cost)

                # Generate unique ID
                trade_id = str(uuid.uuid4())[:8]

                # Create a synthetic trade with all required fields
                trade = BotTrade(
                    id=trade_id,
                    symbol=symbol.upper(),
                    direction=direction,
                    status=TradeStatus.OPEN,  # Use OPEN for active positions
                    setup_type="imported_from_ib",
                    timeframe="daily",
                    quality_score=50,
                    quality_grade="B",
                    entry_price=avg_cost,
                    current_price=avg_cost,
                    stop_price=stop,
                    target_prices=[target_1, target_2, target_3],
                    shares=int(abs(qty)),
                    risk_amount=risk_per_share * abs(qty),
                    potential_reward=reward_per_share * abs(qty),
                    risk_reward_ratio=reward_per_share / risk_per_share if risk_per_share > 0 else 2.0
                )
                trade.fill_price = avg_cost
                trade.remaining_shares = int(abs(qty))
                trade.original_shares = int(abs(qty))
                trade.entry_time = datetime.now(timezone.utc)
                trade.notes = "Imported from IB - position existed before bot tracking"

                bot._open_trades[trade.id] = trade

                # Save to MongoDB using the persist method (handles enum serialization)
                await asyncio.to_thread(bot._persist_trade, trade)

                logger.info(f"Created new trade for imported position: {symbol} {int(abs(qty))} shares @ ${avg_cost:.2f}")
                return {
                    "success": True,
                    "action": "created",
                    "trade_id": trade.id,
                    "symbol": symbol,
                    "qty": qty,
                    "avg_cost": avg_cost
                }

            else:
                return {
                    "success": False,
                    "error": f"Position {symbol} not tracked by bot. Set auto_create_trade=True to import it."
                }

        except Exception as e:
            import traceback
            logger.error(f"Error syncing position {symbol}: {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    async def close_phantom_position(self, trade_id: str, bot: 'TradingBotService', reason: str = "not_in_ib") -> Dict:
        """
        Close a bot trade that no longer exists in IB.
        This handles cases where positions were manually closed or stopped out.
        """
        from services.trading_bot_service import TradeDirection, TradeStatus

        try:
            if trade_id not in bot._open_trades:
                return {"success": False, "error": f"Trade {trade_id} not found in open trades"}

            trade = bot._open_trades[trade_id]

            # Move to closed trades
            trade.status = TradeStatus.CLOSED
            trade.exit_time = datetime.now(timezone.utc)
            trade.exit_reason = reason

            # We don't know the actual exit price, use current price if available or fill price
            if trade.current_price and trade.current_price > 0:
                trade.exit_price = trade.current_price
            else:
                trade.exit_price = trade.fill_price  # Assume breakeven if no price

            # Calculate final P&L
            if trade.direction == TradeDirection.LONG:
                trade.realized_pnl = (trade.exit_price - trade.fill_price) * trade.remaining_shares
            else:
                trade.realized_pnl = (trade.fill_price - trade.exit_price) * trade.remaining_shares

            trade.unrealized_pnl = 0
            trade.remaining_shares = 0

            # Move from open to closed
            del bot._open_trades[trade_id]
            bot._closed_trades.append(trade)

            # Update MongoDB
            update_doc = {
                "status": TradeStatus.CLOSED.value,
                "exit_time": trade.exit_time.isoformat(),
                "exit_price": trade.exit_price,
                "exit_reason": trade.exit_reason,
                "realized_pnl": trade.realized_pnl,
                "unrealized_pnl": 0,
                "remaining_shares": 0
            }
            await asyncio.to_thread(
                bot._db.bot_trades.update_one,
                {"id": trade_id}, {"$set": update_doc}
            )

            logger.info(f"Closed phantom trade {trade.symbol} ({trade_id}): reason={reason}, P&L=${trade.realized_pnl:.2f}")

            return {
                "success": True,
                "trade_id": trade_id,
                "symbol": trade.symbol,
                "action": "closed",
                "reason": reason,
                "realized_pnl": trade.realized_pnl
            }

        except Exception as e:
            logger.error(f"Error closing phantom position {trade_id}: {e}")
            return {"success": False, "error": str(e)}

    async def full_position_sync(self, bot: 'TradingBotService') -> Dict:
        """
        Comprehensive position sync that:
        1. Imports untracked IB positions
        2. Closes phantom positions (bot has, IB doesn't)
        3. Fixes quantity mismatches
        4. Fixes direction mismatches

        Returns detailed report of all actions taken.
        """
        from services.trading_bot_service import TradeDirection

        report = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "imported": [],
            "closed_phantom": [],
            "updated": [],
            "errors": []
        }

        try:
            # First get reconciliation report
            recon = await self.reconcile_positions_with_ib(bot)

            if recon.get("error"):
                report["success"] = False
                report["error"] = recon["error"]
                return report

            for disc in recon.get("discrepancies", []):
                disc_type = disc["type"]
                symbol = disc["symbol"]

                try:
                    if disc_type == "untracked_position":
                        # Import from IB
                        result = await self.sync_position_from_ib(symbol, bot, auto_create_trade=True)
                        if result.get("success"):
                            report["imported"].append({
                                "symbol": symbol,
                                "qty": disc["ib_qty"],
                                "trade_id": result.get("trade_id")
                            })
                        else:
                            report["errors"].append({"symbol": symbol, "error": result.get("error"), "type": "import"})

                    elif disc_type == "phantom_position":
                        # Close the phantom trade
                        trade_id = disc.get("trade_id")
                        if trade_id:
                            result = await self.close_phantom_position(trade_id, bot, reason="closed_outside_bot")
                            if result.get("success"):
                                report["closed_phantom"].append({
                                    "symbol": symbol,
                                    "trade_id": trade_id,
                                    "realized_pnl": result.get("realized_pnl", 0)
                                })
                            else:
                                report["errors"].append({"symbol": symbol, "error": result.get("error"), "type": "close_phantom"})

                    elif disc_type == "quantity_mismatch":
                        # Update the trade quantity to match IB
                        trade_id = disc.get("trade_id")
                        ib_qty = disc["ib_qty"]

                        if trade_id and trade_id in bot._open_trades:
                            trade = bot._open_trades[trade_id]
                            old_qty = trade.remaining_shares

                            # Check if direction changed (long to short or vice versa)
                            ib_direction = TradeDirection.LONG if ib_qty > 0 else TradeDirection.SHORT

                            if ib_direction != trade.direction:
                                # Direction flipped - this is a significant change
                                # Close the old trade and create new one
                                await self.close_phantom_position(trade_id, bot, reason="direction_changed")
                                result = await self.sync_position_from_ib(symbol, bot, auto_create_trade=True)
                                report["updated"].append({
                                    "symbol": symbol,
                                    "action": "direction_changed",
                                    "old_direction": trade.direction.value,
                                    "new_direction": ib_direction.value,
                                    "new_qty": abs(ib_qty)
                                })
                            else:
                                # Same direction, just quantity changed
                                trade.remaining_shares = abs(ib_qty)
                                trade.shares = abs(ib_qty)

                                # Update MongoDB
                                update_doc = {
                                    "remaining_shares": abs(ib_qty),
                                    "shares": abs(ib_qty)
                                }
                                await asyncio.to_thread(
                                    bot._db.bot_trades.update_one,
                                    {"id": trade_id}, {"$set": update_doc}
                                )

                                report["updated"].append({
                                    "symbol": symbol,
                                    "trade_id": trade_id,
                                    "old_qty": old_qty,
                                    "new_qty": abs(ib_qty),
                                    "action": "quantity_updated"
                                })

                except Exception as e:
                    report["errors"].append({"symbol": symbol, "error": str(e), "type": disc_type})

            # Final reconciliation check
            final_recon = await self.reconcile_positions_with_ib(bot)
            report["final_synced"] = final_recon.get("synced", False)
            report["remaining_discrepancies"] = len(final_recon.get("discrepancies", []))

            logger.info(f"Full position sync complete: imported={len(report['imported'])}, closed={len(report['closed_phantom'])}, updated={len(report['updated'])}, errors={len(report['errors'])}")

            return report

        except Exception as e:
            logger.error(f"Full position sync error: {e}")
            report["success"] = False
            report["error"] = str(e)
            return report
