"""
Bot Persistence — Extracted from trading_bot_service.py

Handles all state persistence and restoration:
- Comprehensive session restore (bot state, EOD config, daily stats, trades)
- State saving to MongoDB
- Individual trade persistence
- Trade deserialization (dict → BotTrade)
- Startup reconciliation scheduling
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradingBotService

logger = logging.getLogger(__name__)


class BotPersistence:
    """Manages bot state persistence and restoration from MongoDB."""

    async def restore_state(self, bot: 'TradingBotService'):
        """Restore bot state from MongoDB on startup - COMPREHENSIVE SESSION PERSISTENCE"""
        from services.trading_bot_service import BotMode, DailyStats

        try:
            if bot._db is None:
                return

            # === 1. RESTORE BOT STATE ===
            state = await asyncio.to_thread(bot._db.bot_state.find_one, {"_id": "bot_state"})
            if state:
                was_running = state.get("running", False)
                saved_mode = state.get("mode", "confirmation")
                saved_watchlist = state.get("watchlist", [])
                saved_setups = state.get("enabled_setups", [])
                saved_risk_params = state.get("risk_params", {})

                # Restore mode - but prefer AUTONOMOUS if that's the default
                if saved_mode in ["autonomous", "confirmation", "paused"]:
                    bot._mode = BotMode(saved_mode)

                # Restore watchlist
                if saved_watchlist:
                    bot._watchlist = saved_watchlist
                    logger.info(f"📋 Restored watchlist: {', '.join(saved_watchlist[:5])}{'...' if len(saved_watchlist) > 5 else ''}")

                # Restore enabled setups — MERGE saved list with current
                # defaults instead of replacing. Replacing was silently
                # filtering out new strategies whenever the codebase added
                # one (e.g. `relative_strength_leader`, REVERSAL bases) —
                # the operator would persist a list, then ship new defaults,
                # then on restart the saved list would win and the new
                # strategies would be invisible until manually re-enabled.
                if saved_setups and len(saved_setups) > 10:
                    merged = sorted(set(bot._enabled_setups) | set(saved_setups))
                    added = sorted(set(bot._enabled_setups) - set(saved_setups))
                    bot._enabled_setups = merged
                    if added:
                        logger.info(
                            f"🎯 Merged {len(merged)} strategies "
                            f"(saved {len(saved_setups)} + {len(added)} new defaults: {added[:5]}{'...' if len(added) > 5 else ''})"
                        )
                    else:
                        logger.info(f"🎯 Restored {len(merged)} strategies (no new defaults to merge)")
                else:
                    logger.info(f"🎯 Using default {len(bot._enabled_setups)} strategies")

                # Restore risk parameters
                if saved_risk_params:
                    if "max_risk_per_trade" in saved_risk_params:
                        bot.risk_params.max_risk_per_trade = saved_risk_params["max_risk_per_trade"]
                    if "max_daily_loss" in saved_risk_params:
                        bot.risk_params.max_daily_loss = saved_risk_params["max_daily_loss"]
                    if "max_daily_loss_pct" in saved_risk_params:
                        bot.risk_params.max_daily_loss_pct = saved_risk_params["max_daily_loss_pct"]
                    if "max_open_positions" in saved_risk_params:
                        bot.risk_params.max_open_positions = saved_risk_params["max_open_positions"]
                    if "max_position_pct" in saved_risk_params:
                        bot.risk_params.max_position_pct = saved_risk_params["max_position_pct"]
                    if "min_risk_reward" in saved_risk_params:
                        bot.risk_params.min_risk_reward = saved_risk_params["min_risk_reward"]
                    if "starting_capital" in saved_risk_params:
                        bot.risk_params.starting_capital = saved_risk_params["starting_capital"]
                    if "max_notional_per_trade" in saved_risk_params:
                        bot.risk_params.max_notional_per_trade = saved_risk_params["max_notional_per_trade"]
                    # 2026-05-01 v19.24 — reconcile endpoint defaults
                    if "reconciled_default_stop_pct" in saved_risk_params:
                        bot.risk_params.reconciled_default_stop_pct = float(saved_risk_params["reconciled_default_stop_pct"])
                    if "reconciled_default_rr" in saved_risk_params:
                        bot.risk_params.reconciled_default_rr = float(saved_risk_params["reconciled_default_rr"])
                    # 2026-05-01 v19.21 — round-trip per-setup R:R overrides.
                    # Saved dict MERGES into the code defaults so newly-shipped
                    # setups (e.g. `the_3_30_trade` added in v19.20) get their
                    # default override even on bots that persisted before the
                    # ship. Operator-saved values still win over code defaults.
                    saved_setup_min_rr = saved_risk_params.get("setup_min_rr")
                    if isinstance(saved_setup_min_rr, dict):
                        merged_setup_min_rr = dict(bot.risk_params.setup_min_rr or {})
                        for k, v in saved_setup_min_rr.items():
                            try:
                                merged_setup_min_rr[k] = float(v)
                            except (TypeError, ValueError):
                                continue
                        bot.risk_params.setup_min_rr = merged_setup_min_rr
                    logger.info(f"💰 Restored risk params: max_risk=${bot.risk_params.max_risk_per_trade:,.0f}, max_positions={bot.risk_params.max_open_positions}, min_rr={bot.risk_params.min_risk_reward}, max_notional=${bot.risk_params.max_notional_per_trade:,.0f}")

            # === 2. RESTORE EOD CONFIG ===
            eod_config = await asyncio.to_thread(bot._db.bot_config.find_one, {"_id": "eod_config"})
            if eod_config:
                bot._eod_close_enabled = eod_config.get("enabled", True)
                bot._eod_close_hour = eod_config.get("close_hour", 15)
                bot._eod_close_minute = eod_config.get("close_minute", 55)
                logger.info(f"⏰ Restored EOD config: {bot._eod_close_hour}:{bot._eod_close_minute:02d} PM ET, enabled={bot._eod_close_enabled}")

            # === 3. RESTORE DAILY STATS ===
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily_stats = await asyncio.to_thread(bot._db.daily_stats.find_one, {"date": today_str})
            if daily_stats:
                bot._daily_stats = DailyStats(
                    date=today_str,
                    trades_executed=daily_stats.get("trades_executed", 0),
                    trades_won=daily_stats.get("trades_won", 0),
                    trades_lost=daily_stats.get("trades_lost", 0),
                    gross_pnl=daily_stats.get("gross_pnl", 0.0),
                    net_pnl=daily_stats.get("net_pnl", 0.0),
                    largest_win=daily_stats.get("largest_win", 0.0),
                    largest_loss=daily_stats.get("largest_loss", 0.0),
                    win_rate=daily_stats.get("win_rate", 0.0),
                    daily_limit_hit=daily_stats.get("daily_limit_hit", False)
                )
                logger.info(f"📊 Restored daily stats: P&L=${bot._daily_stats.net_pnl:+,.2f}, Trades={bot._daily_stats.trades_executed}")

            # === 4. RESTORE OPEN TRADES ===
            await self.restore_open_trades(bot)

            # === 5. RESTORE CLOSED TRADES (recent) ===
            await self.restore_closed_trades(bot)

            # === 6. AUTO-RESTART if bot was running ===
            if state and state.get("running", False):
                logger.info("🔄 Bot was running before restart - auto-resuming...")
                await bot.start()

            logger.info(f"✅ Session restored: mode={bot._mode.value}, running={bot._running}, open_trades={len(bot._open_trades)}, closed_trades={len(bot._closed_trades)}")

        except Exception as e:
            logger.warning(f"Could not restore bot state: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    async def restore_closed_trades(self, bot: 'TradingBotService'):
        """Restore recent closed trades for history display"""
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

        try:
            if bot._db is None:
                return

            # Restore last 100 closed trades
            closed_trades = await asyncio.to_thread(
                lambda: list(bot._db.bot_trades.find({"status": "closed"}).sort("closed_at", -1).limit(100))
            )

            for trade_doc in closed_trades:
                try:
                    # Create trade object from stored data
                    direction = trade_doc.get("direction", "long")
                    if isinstance(direction, str):
                        direction = TradeDirection.LONG if direction.lower() == "long" else TradeDirection.SHORT

                    trade = BotTrade(
                        id=trade_doc.get("id", str(uuid.uuid4())[:8]),
                        symbol=trade_doc.get("symbol", "UNKNOWN"),
                        direction=direction,
                        status=TradeStatus.CLOSED,
                        setup_type=trade_doc.get("setup_type", "unknown"),
                        timeframe=trade_doc.get("timeframe", "daily"),
                        quality_score=trade_doc.get("quality_score", 50),
                        quality_grade=trade_doc.get("quality_grade", "B"),
                        entry_price=trade_doc.get("entry_price", 0),
                        current_price=trade_doc.get("exit_price", trade_doc.get("entry_price", 0)),
                        stop_price=trade_doc.get("stop_price", 0),
                        target_prices=trade_doc.get("target_prices", []),
                        shares=trade_doc.get("shares", 0),
                        risk_amount=trade_doc.get("risk_amount", 0),
                        potential_reward=trade_doc.get("potential_reward", 0),
                        risk_reward_ratio=trade_doc.get("risk_reward_ratio", 0)
                    )
                    trade.fill_price = trade_doc.get("fill_price", trade_doc.get("entry_price", 0))
                    trade.exit_price = trade_doc.get("exit_price", 0)
                    trade.realized_pnl = trade_doc.get("realized_pnl", 0)
                    trade.close_reason = trade_doc.get("close_reason", trade_doc.get("exit_reason", "unknown"))
                    trade.closed_at = trade_doc.get("closed_at")

                    bot._closed_trades.append(trade)
                except Exception as e:
                    logger.debug(f"Could not restore closed trade: {e}")

            if bot._closed_trades:
                logger.info(f"📚 Restored {len(bot._closed_trades)} closed trades from history")

        except Exception as e:
            logger.warning(f"Could not restore closed trades: {e}")

    async def restore_open_trades(self, bot: 'TradingBotService'):
        """Restore open trades from database - CRITICAL for persistence across restarts"""
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

        try:
            if bot._db is None:
                return

            # Find all trades with open or pending status
            open_trades = await asyncio.to_thread(
                lambda: list(bot._db.bot_trades.find({"status": {"$in": ["open", "pending", "filled"]}}))
            )

            restored_count = 0
            for trade_doc in open_trades:
                try:
                    # Get all required fields with defaults for missing data
                    symbol = trade_doc.get("symbol", "UNKNOWN")
                    entry_price = trade_doc.get("entry_price", 0) or trade_doc.get("fill_price", 0)
                    stop_price = trade_doc.get("stop_price", 0)
                    target_prices = trade_doc.get("target_prices", [entry_price * 1.02])
                    shares = trade_doc.get("shares", 0)
                    risk_amount = trade_doc.get("risk_amount", 0)

                    # Calculate missing fields
                    if not target_prices:
                        target_prices = [entry_price * 1.02, entry_price * 1.05]

                    risk_per_share = abs(entry_price - stop_price) if stop_price else entry_price * 0.02
                    if risk_amount == 0:
                        risk_amount = risk_per_share * shares

                    reward_per_share = abs(target_prices[0] - entry_price) if target_prices else entry_price * 0.04
                    potential_reward = reward_per_share * shares
                    risk_reward_ratio = (reward_per_share / risk_per_share) if risk_per_share > 0 else 2.0

                    # Reconstruct BotTrade object with ALL required fields
                    trade = BotTrade(
                        id=str(trade_doc.get("id", trade_doc.get("_id", str(uuid.uuid4())))),
                        symbol=symbol,
                        direction=TradeDirection(trade_doc.get("direction", "long")),
                        status=TradeStatus(trade_doc.get("status", "open")),
                        setup_type=trade_doc.get("setup_type", "restored"),
                        timeframe=trade_doc.get("timeframe", "intraday"),
                        quality_score=trade_doc.get("quality_score", 70),
                        quality_grade=trade_doc.get("quality_grade", "B"),
                        entry_price=entry_price,
                        current_price=trade_doc.get("current_price", entry_price),
                        stop_price=stop_price,
                        target_prices=target_prices,
                        shares=shares,
                        risk_amount=risk_amount,
                        potential_reward=potential_reward,
                        risk_reward_ratio=risk_reward_ratio
                    )

                    # Restore optional fields via direct assignment
                    trade.fill_price = trade_doc.get("fill_price", entry_price)
                    trade.executed_at = trade_doc.get("executed_at")
                    trade.entry_order_id = trade_doc.get("entry_order_id")
                    trade.stop_order_id = trade_doc.get("stop_order_id")
                    trade.notes = trade_doc.get("notes", "") or trade_doc.get("rationale", "")
                    trade.market_regime = trade_doc.get("market_regime", "UNKNOWN")
                    trade.regime_score = trade_doc.get("regime_score", 50.0)

                    # Restore trailing stop config
                    if trade_doc.get("trailing_stop_config"):
                        trade.trailing_stop_config = trade_doc["trailing_stop_config"]
                    else:
                        # Initialize trailing stop with current stop
                        trade.trailing_stop_config["current_stop"] = stop_price
                        trade.trailing_stop_config["original_stop"] = stop_price

                    # Restore richer trade logging fields
                    trade.setup_variant = trade_doc.get("setup_variant", "")
                    trade.entry_context = trade_doc.get("entry_context", {})
                    trade.mfe_price = trade_doc.get("mfe_price", trade.fill_price)
                    trade.mfe_pct = trade_doc.get("mfe_pct", 0.0)
                    trade.mfe_r = trade_doc.get("mfe_r", 0.0)
                    trade.mae_price = trade_doc.get("mae_price", trade.fill_price)
                    trade.mae_pct = trade_doc.get("mae_pct", 0.0)
                    trade.mae_r = trade_doc.get("mae_r", 0.0)

                    # Add to appropriate dict
                    if trade.status == TradeStatus.PENDING:
                        bot._pending_trades[trade.id] = trade
                    else:
                        bot._open_trades[trade.id] = trade

                    restored_count += 1
                    logger.info(f"📥 Restored trade: {trade.symbol} {trade.direction.value} {trade.shares} shares @ ${trade.fill_price:.2f}, stop=${trade.stop_price:.2f}")

                except Exception as e:
                    logger.warning(f"Failed to restore trade {trade_doc.get('symbol')}: {e}")

            if restored_count > 0:
                logger.info(f"✅ Restored {restored_count} open trades from database")
            else:
                logger.info("📭 No open trades to restore from database")

            # Schedule position reconciliation after a short delay (allow IB pusher to connect)
            asyncio.create_task(self.delayed_reconciliation(bot))

        except Exception as e:
            logger.warning(f"Could not restore open trades: {e}")

    async def delayed_reconciliation(self, bot: 'TradingBotService'):
        """Run position reconciliation after startup delay to allow IB connection"""
        try:
            # Wait for IB pusher to potentially connect
            await asyncio.sleep(10)

            from routers.ib import is_pusher_connected
            if is_pusher_connected():
                logger.info("🔄 Running startup position reconciliation...")
                report = await bot.reconcile_positions_with_ib()

                if report.get("discrepancies"):
                    disc_count = len(report["discrepancies"])
                    logger.warning(f"⚠️ Found {disc_count} position discrepancies on startup!")
                    for d in report["discrepancies"]:
                        logger.warning(f"   - {d['message']}")
                    logger.info("💡 Run /api/trading-bot/positions/sync-all to auto-fix discrepancies")
                else:
                    logger.info("✅ Position reconciliation: All positions in sync with IB")
            else:
                logger.info("⏳ IB pusher not connected - skipping startup reconciliation")
        except Exception as e:
            logger.debug(f"Startup reconciliation skipped: {e}")

    async def save_state(self, bot: 'TradingBotService'):
        """Save bot state to MongoDB - COMPREHENSIVE SESSION PERSISTENCE"""
        try:
            if bot._db is None:
                return

            # Build state and stats documents first (lightweight, no IO)
            state_doc = {
                "running": bot._running,
                "mode": bot._mode.value,
                "watchlist": bot._watchlist,
                "enabled_setups": bot._enabled_setups,
                "risk_params": {
                    "max_risk_per_trade": bot.risk_params.max_risk_per_trade,
                    "max_daily_loss": bot.risk_params.max_daily_loss,
                    "max_daily_loss_pct": bot.risk_params.max_daily_loss_pct,
                    "max_open_positions": bot.risk_params.max_open_positions,
                    "max_position_pct": bot.risk_params.max_position_pct,
                    "min_risk_reward": bot.risk_params.min_risk_reward,
                    "starting_capital": bot.risk_params.starting_capital,
                    "max_notional_per_trade": bot.risk_params.max_notional_per_trade,
                    # 2026-05-01 v19.24 — reconcile endpoint defaults
                    "reconciled_default_stop_pct": bot.risk_params.reconciled_default_stop_pct,
                    "reconciled_default_rr": bot.risk_params.reconciled_default_rr,
                    # 2026-05-01 v19.21 — persist per-setup R:R overrides
                    # so operator tweaks (e.g. /api/trading-bot/risk-params
                    # PUT) survive backend restarts.
                    "setup_min_rr": dict(bot.risk_params.setup_min_rr or {}),
                },
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            stats_doc = {
                "trades_executed": bot._daily_stats.trades_executed,
                "trades_won": bot._daily_stats.trades_won,
                "trades_lost": bot._daily_stats.trades_lost,
                "gross_pnl": bot._daily_stats.gross_pnl,
                "net_pnl": bot._daily_stats.net_pnl,
                "largest_win": bot._daily_stats.largest_win,
                "largest_loss": bot._daily_stats.largest_loss,
                "win_rate": bot._daily_stats.win_rate,
                "daily_limit_hit": bot._daily_stats.daily_limit_hit,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            stats_date = bot._daily_stats.date

            # Run all DB writes in a thread to avoid blocking
            def _sync_save():
                bot._db.bot_state.update_one(
                    {"_id": "bot_state"}, {"$set": state_doc}, upsert=True
                )
                bot._db.daily_stats.update_one(
                    {"date": stats_date}, {"$set": stats_doc}, upsert=True
                )
                self.persist_all_open_trades(bot)

            await asyncio.to_thread(_sync_save)

            logger.info(f"💾 Session saved: running={bot._running}, P&L=${bot._daily_stats.net_pnl:+,.2f}, open_trades={len(bot._open_trades)}")
        except Exception as e:
            logger.warning(f"Could not save bot state: {e}")

    def persist_trade(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """
        Persist a single trade to MongoDB.
        Called whenever a trade's state changes (created, filled, updated, closed).
        This is CRITICAL for data consistency and session persistence.
        """
        from services.trading_bot_service import TradeStatus, TradeDirection

        if bot._db is None:
            logger.warning("Cannot persist trade - no database connection")
            return

        try:
            trade_dict = trade.to_dict()

            # Ensure status is stored as string value
            if isinstance(trade_dict.get("status"), TradeStatus):
                trade_dict["status"] = trade_dict["status"].value
            if isinstance(trade_dict.get("direction"), TradeDirection):
                trade_dict["direction"] = trade_dict["direction"].value

            # Add metadata
            trade_dict["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Upsert to MongoDB
            bot._db.bot_trades.update_one(
                {"id": trade.id},
                {"$set": trade_dict},
                upsert=True
            )

            logger.debug(f"💾 Trade persisted: {trade.symbol} ({trade.id}) status={trade.status.value if hasattr(trade.status, 'value') else trade.status}")

        except Exception as e:
            logger.exception(
                "Failed to persist trade %s (%s): %s",
                trade.id, type(e).__name__, e,
            )

    def persist_all_open_trades(self, bot: 'TradingBotService'):
        """Persist all open trades - call this periodically or on shutdown"""
        if bot._db is None:
            return

        for trade in bot._open_trades.values():
            self.persist_trade(trade, bot)

        logger.info(f"💾 Persisted {len(bot._open_trades)} open trades")

    async def save_trade(self, trade: 'BotTrade', bot: 'TradingBotService'):
        """Save trade to database"""
        if bot._db is None:
            return

        try:
            trades_col = bot._db["bot_trades"]
            trade_dict = trade.to_dict()
            trade_dict['_id'] = trade.id

            await asyncio.to_thread(
                lambda: trades_col.replace_one(
                    {"_id": trade.id},
                    trade_dict,
                    upsert=True
                )
            )
        except Exception as e:
            logger.exception(
                "Error saving trade (%s): %s",
                type(e).__name__, e,
            )

    async def load_trades_from_db(self, bot: 'TradingBotService'):
        """Load trades from database on startup"""
        if bot._db is None:
            return

        try:
            def _sync_load():
                trades_col = bot._db["bot_trades"]
                return list(trades_col.find({"status": "open"}))

            docs = await asyncio.to_thread(_sync_load)
            for doc in docs:
                doc.pop('_id', None)
                trade = self.dict_to_trade(doc)
                if trade:
                    bot._open_trades[trade.id] = trade

            logger.info(f"Loaded {len(bot._open_trades)} open trades from database")

        except Exception as e:
            logger.exception(
                "Error loading trades (%s): %s",
                type(e).__name__, e,
            )

    @staticmethod
    def dict_to_trade(d: Dict) -> Optional['BotTrade']:
        """Convert dictionary to BotTrade.

        ── v19.34.21 (2026-05-06) ── Pre-fix this method only passed
        ~25 of `BotTrade`'s ~50 fields to the constructor, so the rest
        defaulted to dataclass defaults on every reload. Missing fields:
        `remaining_shares`, `original_shares`, `scale_out_config`,
        `trailing_stop_config`, `mfe_price/_pct/_r`, `mae_price/_pct/_r`,
        `entered_by`, `prior_verdicts`, `prior_verdict_conflict`,
        `synthetic_source`, `pre_submit_at`, `setup_variant`,
        `entry_context`, `market_regime`, `regime_score`,
        `regime_position_multiplier`, `trade_type`, `account_id_at_fill`,
        `total_commissions`, `net_pnl`, `commission_per_share`,
        `commission_min`, `notes`, `close_reason`, `setup_variant`,
        `tape_score`, `target_r_multiple`, `direction_bias`, `smb_grade`,
        `trade_style`.

        Operator-discovered 2026-05-06: every restart was silently
        zombifying every open BotTrade because `remaining_shares=0`
        (default) replaced the persisted value. The manage-loop self-
        heal at `position_manager.py:494` (`if rs==0: rs=shares`) was
        masking the bug for trades that got a fresh quote within ~30s
        of restart; positions that didn't (TIMEOUT-NEEDS-SYNC, stale
        quote, etc.) became permanent zombies.

        Worse: dropped `scale_out_config` would reset `targets_hit=[]`,
        re-firing already-hit scale-outs after a restart. Dropped
        `trailing_stop_config` would reset trailing stops to dataclass
        defaults, losing all stop-adjustment history.

        Fix: construct with required fields, then setattr ALL persisted
        keys back onto the instance. Dataclass-typed enums are coerced
        explicitly. Datetime-like ISO strings are passed through as-is
        (the rest of the bot reads them as strings).
        """
        from services.trading_bot_service import BotTrade, TradeDirection, TradeStatus

        try:
            trade = BotTrade(
                id=d.get('id', ''),
                symbol=d.get('symbol', ''),
                direction=TradeDirection(d.get('direction', 'long')),
                status=TradeStatus(d.get('status', 'pending')),
                setup_type=d.get('setup_type', ''),
                timeframe=d.get('timeframe', 'intraday'),
                quality_score=d.get('quality_score', 0),
                quality_grade=d.get('quality_grade', ''),
                entry_price=d.get('entry_price', 0),
                current_price=d.get('current_price', 0),
                stop_price=d.get('stop_price', 0),
                target_prices=d.get('target_prices', []),
                shares=d.get('shares', 0),
                risk_amount=d.get('risk_amount', 0),
                potential_reward=d.get('potential_reward', 0),
                risk_reward_ratio=d.get('risk_reward_ratio', 0),
            )

            # ── v19.34.21: hydrate every persisted field back onto the
            # instance. We use the dataclass field set as the allow-list
            # to avoid setting random keys; explanation/_id are excluded.
            from dataclasses import fields as _dc_fields
            allowed = {f.name for f in _dc_fields(BotTrade)}
            # These were already set by the constructor — don't overwrite.
            constructor_set = {
                "id", "symbol", "direction", "status", "setup_type",
                "timeframe", "quality_score", "quality_grade",
                "entry_price", "current_price", "stop_price",
                "target_prices", "shares", "risk_amount",
                "potential_reward", "risk_reward_ratio",
            }
            # Fields that need explicit conversion to avoid losing types.
            for k, v in d.items():
                if k not in allowed or k in constructor_set or k == "explanation":
                    continue
                try:
                    setattr(trade, k, v)
                except Exception as set_err:  # pragma: no cover
                    logger.warning(
                        f"dict_to_trade: failed to setattr "
                        f"{k}={v!r} on {trade.id}: {set_err}"
                    )

            return trade
        except Exception as e:
            logger.error(f"Error deserializing trade: {e}")
            return None
