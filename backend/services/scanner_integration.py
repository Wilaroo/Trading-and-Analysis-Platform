"""
Scanner Integration — Extracted from trading_bot_service.py

Handles:
- Scanner auto-execution (submit_trade_from_scanner)
- Trade journal auto-logging (entry + exit records)
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class ScannerIntegration:
    """Manages scanner→bot trade submission and trade journal logging."""

    async def submit_trade_from_scanner(self, trade_request: Dict, bot: 'TradingBotService'):
        """
        Submit a trade from the enhanced scanner for auto-execution.
        Called when a high-priority alert with tape confirmation is detected.
        """
        from services.trading_bot_service import BotMode

        try:
            symbol = trade_request.get('symbol')
            direction = trade_request.get('direction', 'long')
            setup_type = trade_request.get('setup_type')
            entry_price = trade_request.get('entry_price')
            stop_loss = trade_request.get('stop_loss')
            target = trade_request.get('target')
            alert_id = trade_request.get('alert_id')

            logger.info(f"🤖 Scanner auto-submit: {symbol} {direction.upper()} {setup_type}")

            # Create alert dict for existing evaluation flow
            alert = {
                'symbol': symbol,
                'setup_type': setup_type,
                'direction': direction,
                'current_price': entry_price,
                'trigger_price': entry_price,
                'stop_price': stop_loss,
                'targets': [target],
                'score': 80,
                'trigger_probability': 0.65,
                'headline': f"Auto-execute: {setup_type} on {symbol}",
                'technical_reasons': [
                    f"Tape confirmed {setup_type} setup",
                    "Auto-executed from scanner alert"
                ],
                'warnings': [],
                'source': 'scanner_auto_execute',
                'alert_id': alert_id
            }

            # Evaluate and create trade
            trade = await bot._evaluate_opportunity(alert)

            if trade:
                if bot._mode == BotMode.AUTONOMOUS:
                    await bot._execute_trade(trade)
                    logger.info(f"✅ Auto-executed: {trade.symbol} {trade.direction.value.upper()}")
                else:
                    bot._pending_trades[trade.id] = trade
                    await bot._notify_trade_update(trade, "pending")
                    logger.info(f"⏳ Auto-submit pending confirmation: {trade.symbol}")

                return {"success": True, "trade_id": trade.id}
            else:
                logger.warning(f"Scanner auto-submit rejected: {symbol} did not pass evaluation")
                return {"success": False, "reason": "Failed evaluation"}

        except Exception as e:
            logger.error(f"Scanner auto-submit error: {e}")
            return {"success": False, "reason": str(e)}

    async def log_trade_to_journal(self, trade: 'BotTrade', bot: 'TradingBotService', action: str = "entry"):
        """
        Auto-record a trade to the Trade Journal.

        Args:
            trade: The BotTrade object
            bot: TradingBotService instance
            action: "entry" for new trades, "exit" for closed trades
        """
        if not bot._trade_journal:
            logger.debug("Trade journal not configured - skipping auto-record")
            return

        try:
            regime = bot._current_regime or "UNKNOWN"

            if action == "entry":
                journal_entry = {
                    "symbol": trade.symbol,
                    "direction": trade.direction.value.upper(),
                    "entry_price": trade.fill_price or trade.entry_price,
                    "entry_date": (trade.executed_at or datetime.now(timezone.utc).isoformat())[:10],
                    "shares": trade.shares,
                    "stop_loss": trade.stop_price,
                    "target": trade.target_prices[0] if trade.target_prices else None,
                    "setup_type": trade.setup_type or "bot_trade",
                    "setup_variant": trade.setup_variant,
                    "strategy": trade.setup_type or "Auto-Trade",
                    "market_regime": regime,
                    "entry_context": trade.entry_context,
                    "notes": f"[AUTO-RECORDED by Trading Bot]\nSetup: {trade.setup_type} ({trade.setup_variant})\nReason: {trade.notes or 'Bot execution'}",
                    "status": "open",
                    "tags": ["auto-recorded", "trading-bot", regime.lower()],
                    "bot_trade_id": trade.id,
                }

                result = await bot._trade_journal.log_trade(journal_entry)
                if result.get("success"):
                    logger.info(f"📓 Auto-recorded ENTRY to journal: {trade.symbol} {trade.direction.value}")
                else:
                    logger.warning(f"Failed to record entry: {result.get('error', 'Unknown error')}")

            elif action == "exit":
                try:
                    existing = await asyncio.to_thread(
                        bot._trade_journal.db.trades.find_one,
                        {"bot_trade_id": trade.id}
                    )

                    if existing:
                        update_data = {
                            "exit_price": trade.exit_price,
                            "exit_date": (trade.closed_at or datetime.now(timezone.utc).isoformat())[:10],
                            "pnl": trade.realized_pnl,
                            "pnl_percent": trade.pnl_pct,
                            "status": "closed",
                            "exit_reason": trade.close_reason or "closed",
                            "mfe_price": trade.mfe_price,
                            "mfe_pct": round(trade.mfe_pct, 2),
                            "mfe_r": round(trade.mfe_r, 2),
                            "mae_price": trade.mae_price,
                            "mae_pct": round(trade.mae_pct, 2),
                            "mae_r": round(trade.mae_r, 2),
                            "notes": existing.get("notes", "") + (
                                f"\n\n[EXIT] Reason: {trade.close_reason or 'closed'}, "
                                f"P&L: ${trade.realized_pnl:+,.2f}\n"
                                f"MFE: {trade.mfe_pct:+.2f}% ({trade.mfe_r:+.2f}R) | "
                                f"MAE: {trade.mae_pct:+.2f}% ({trade.mae_r:+.2f}R)"
                            ),
                        }

                        await asyncio.to_thread(
                            bot._trade_journal.db.trades.update_one,
                            {"_id": existing["_id"]}, {"$set": update_data}
                        )
                        logger.info(f"📓 Auto-recorded EXIT to journal: {trade.symbol} P&L: ${trade.realized_pnl:+,.2f}")
                    else:
                        journal_entry = {
                            "symbol": trade.symbol,
                            "direction": trade.direction.value.upper(),
                            "entry_price": trade.fill_price,
                            "entry_date": (trade.executed_at or datetime.now(timezone.utc).isoformat())[:10],
                            "exit_price": trade.exit_price,
                            "exit_date": (trade.closed_at or datetime.now(timezone.utc).isoformat())[:10],
                            "shares": trade.shares,
                            "pnl": trade.realized_pnl,
                            "pnl_percent": trade.pnl_pct,
                            "status": "closed",
                            "setup_type": trade.setup_type or "bot_trade",
                            "setup_variant": trade.setup_variant,
                            "strategy": trade.setup_type or "Auto-Trade",
                            "market_regime": regime,
                            "entry_context": trade.entry_context,
                            "mfe_price": trade.mfe_price,
                            "mfe_pct": round(trade.mfe_pct, 2),
                            "mfe_r": round(trade.mfe_r, 2),
                            "mae_price": trade.mae_price,
                            "mae_pct": round(trade.mae_pct, 2),
                            "mae_r": round(trade.mae_r, 2),
                            "notes": (
                                f"[AUTO-RECORDED by Trading Bot]\n"
                                f"Exit Reason: {trade.close_reason or 'closed'}\n"
                                f"MFE: {trade.mfe_pct:+.2f}% ({trade.mfe_r:+.2f}R) | "
                                f"MAE: {trade.mae_pct:+.2f}% ({trade.mae_r:+.2f}R)"
                            ),
                            "tags": ["auto-recorded", "trading-bot", regime.lower()],
                            "bot_trade_id": trade.id,
                        }

                        await bot._trade_journal.log_trade(journal_entry)
                        logger.info(f"📓 Auto-recorded complete trade to journal: {trade.symbol} P&L: ${trade.realized_pnl:+,.2f}")

                except Exception as e:
                    logger.error(f"Error finding/updating journal entry: {e}")

        except Exception as e:
            logger.error(f"Failed to auto-record trade to journal: {e}")
