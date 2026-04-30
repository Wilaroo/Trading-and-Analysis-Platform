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
from datetime import datetime, timedelta, timezone
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import TradingBotService

logger = logging.getLogger(__name__)

# v19.29 (2026-05-01) — Direction stability tracker for reconcile.
# Operator caught SOFI being auto-reconciled as SHORT mid-flatten on
# 2026-05-01 even though the position was actually LONG — the IB
# position briefly transitioned through net-flat → small-short during
# the 3:51pm sell wave, and the reconcile snapshot caught the wrong
# direction. To prevent repeats: track every IB position direction
# observation per (symbol) with timestamps, and refuse to reconcile
# unless the direction has been stable for ≥30s. Module-level so
# observations from the position-manager loop accumulate across
# reconcile calls.
_DIRECTION_STABILITY_SECONDS = 30
_ib_direction_history: Dict[str, list] = {}  # symbol → [(ts, direction), ...]


def record_ib_direction_observation(symbol: str, direction: str) -> None:
    """Append a (timestamp, direction) observation for a symbol. Call
    this on every position-manager update so reconcile has fresh data.

    Keeps last 10 minutes of history per symbol; older entries pruned.
    """
    if not symbol or not direction:
        return
    sym = symbol.upper()
    dir_l = direction.lower()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=10)
    hist = _ib_direction_history.setdefault(sym, [])
    hist.append((now, dir_l))
    # Prune in-place
    while hist and hist[0][0] < cutoff:
        hist.pop(0)


def is_direction_stable(symbol: str, expected_direction: str) -> tuple:
    """Has `(symbol, expected_direction)` been continuously observed
    for ≥`_DIRECTION_STABILITY_SECONDS`?

    Algorithm: walk back from newest observation. Collect consecutive
    matching observations. The "streak length" = (now - oldest match).
    Stable iff streak length ≥ threshold. Catches today's SOFI bug
    where direction flipped 5s ago — only 5s of "long" history is
    NOT 30s of stability, even if "long" was true 60s ago before
    the flip.

    Returns (stable: bool, reason: str). Reason is empty when stable.
    """
    if not symbol or not expected_direction:
        return False, "no_direction_provided"
    sym = symbol.upper()
    dir_l = expected_direction.lower()
    hist = _ib_direction_history.get(sym, [])
    if not hist:
        return False, "no_history_yet"
    now = datetime.now(timezone.utc)
    oldest_consecutive = None
    for ts, d in reversed(hist):
        if d != dir_l:
            break
        oldest_consecutive = ts
    if oldest_consecutive is None:
        return False, "newest_observation_disagrees"
    streak_seconds = (now - oldest_consecutive).total_seconds()
    if streak_seconds >= _DIRECTION_STABILITY_SECONDS:
        return True, ""
    # Identify what the disagreement was for the error message
    flipped_to = None
    for ts, d in reversed(hist):
        if d != dir_l:
            flipped_to = d
            break
    if flipped_to:
        return False, f"direction_flipped_within_{_DIRECTION_STABILITY_SECONDS}s_to_{flipped_to}_streak_{streak_seconds:.1f}s"
    return False, f"insufficient_history_streak_{streak_seconds:.1f}s"


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


    # ==================== PROPER RECONCILE (v19.24 — 2026-05-01) =====================

    async def reconcile_orphan_positions(
        self,
        bot: 'TradingBotService',
        symbols: list = None,
        all_orphans: bool = False,
        stop_pct: float = None,
        rr: float = None,
    ) -> Dict:
        """Materialize bot_trades for IB-only (orphan) positions so the bot
        can actively manage them (trail stops, scale-out, EOD close).

        v19.23.1 shipped a read-only "lazy reconcile" in `sentcom_service`
        that enriches the UI payload for orphan positions by scanning
        `bot_trades` for matching symbols. That fix only patches display —
        the bot's in-memory `_open_trades` is still empty so the manage
        loop cannot touch stops/scale-outs/EOD on those positions.

        This method is the PROPER write-through fix: it picks up orphan
        IB positions, computes a default bracket (stop at ±stop_pct from
        avgCost, target at avgCost ± stop_distance*rr), creates a real
        BotTrade record, persists it to Mongo, and inserts into
        `bot._open_trades` — at which point the manage loop owns it.

        Safety:
          - If the proposed stop is ALREADY BREACHED at reconcile time
            (e.g. long position's current price < proposed stop), the
            symbol is SKIPPED with `reason='stop_already_breached'` so
            the operator decides manually — never materialize a trade
            that would insta-stop on the next tick.
          - If the symbol is already tracked by the bot (in `_open_trades`),
            it's SKIPPED with `reason='already_tracked'` — idempotent.
          - If the symbol has no matching IB position, SKIPPED with
            `reason='no_ib_position'`.

        Args:
            bot: TradingBotService instance.
            symbols: Explicit list of symbols to reconcile. Takes priority
                over `all_orphans`.
            all_orphans: If True and `symbols` is empty/None, reconciles
                ALL orphan positions. Caller (router) guards this behind
                a confirm token for safety.
            stop_pct: Per-request stop % override. Falls back to
                `bot.risk_params.reconciled_default_stop_pct`.
            rr: Per-request R:R override. Falls back to
                `bot.risk_params.reconciled_default_rr`.

        Returns:
            Dict: {
              success: bool,
              timestamp: iso str,
              reconciled: [ {symbol, trade_id, shares, direction, entry,
                             stop, target, risk_reward_ratio}, ... ],
              skipped: [ {symbol, reason}, ... ],
              errors: [ {symbol, error}, ... ],
            }
        """
        from services.trading_bot_service import (
            TradeDirection, TradeStatus, BotTrade,
        )

        report = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reconciled": [],
            "skipped": [],
            "errors": [],
        }

        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected

            if not is_pusher_connected():
                report["success"] = False
                report["error"] = "IB pusher not connected — cannot reconcile"
                return report

            # Resolve defaults from bot risk_params if caller didn't override.
            default_stop_pct = float(
                stop_pct
                if stop_pct is not None
                else getattr(bot.risk_params, "reconciled_default_stop_pct", 2.0)
            )
            default_rr = float(
                rr
                if rr is not None
                else getattr(bot.risk_params, "reconciled_default_rr", 2.0)
            )
            if default_stop_pct <= 0:
                report["success"] = False
                report["error"] = f"stop_pct must be > 0, got {default_stop_pct}"
                return report
            if default_rr <= 0:
                report["success"] = False
                report["error"] = f"rr must be > 0, got {default_rr}"
                return report

            # Build IB position map (upper-cased symbols).
            ib_positions = _pushed_ib_data.get("positions", []) or []
            ib_pos_map = {}
            for pos in ib_positions:
                sym = (pos.get("symbol") or pos.get("contract", {}).get("symbol") or "").upper()
                if not sym:
                    continue
                qty = float(pos.get("position", pos.get("qty", 0)) or 0)
                if abs(qty) < 0.01:
                    continue  # zero-qty ghost, skip
                ib_pos_map[sym] = {
                    "symbol": sym,
                    "qty": qty,
                    "avg_cost": float(pos.get("avgCost", pos.get("avg_cost", 0)) or 0),
                    "market_price": float(
                        pos.get("marketPrice", pos.get("market_price", 0)) or 0
                    ),
                }

            # Bot-tracked symbols (so we skip already-managed positions).
            bot_tracked = {t.symbol.upper() for t in bot._open_trades.values()}

            # Resolve candidate list.
            if symbols:
                candidates = [s.upper() for s in symbols if s]
            elif all_orphans:
                candidates = [s for s in ib_pos_map.keys() if s not in bot_tracked]
            else:
                report["success"] = False
                report["error"] = "Provide symbols=[...] or all_orphans=True"
                return report

            if not candidates:
                # Nothing to do — not an error, just a no-op.
                return report

            # IB quote map for live current_price (best-effort).
            ib_quotes = _pushed_ib_data.get("quotes", {}) or {}

            for sym in candidates:
                try:
                    if sym in bot_tracked:
                        report["skipped"].append({
                            "symbol": sym,
                            "reason": "already_tracked",
                        })
                        continue

                    ib_pos = ib_pos_map.get(sym)
                    if not ib_pos:
                        report["skipped"].append({
                            "symbol": sym,
                            "reason": "no_ib_position",
                        })
                        continue

                    qty = ib_pos["qty"]
                    avg_cost = ib_pos["avg_cost"]
                    if avg_cost <= 0:
                        report["skipped"].append({
                            "symbol": sym,
                            "reason": "invalid_avg_cost",
                        })
                        continue

                    direction = TradeDirection.LONG if qty > 0 else TradeDirection.SHORT
                    abs_qty = int(abs(qty))

                    # v19.29 (2026-05-01) — Direction stability gate.
                    # Operator caught SOFI auto-reconciled as SHORT
                    # 2026-05-01 because the IB position briefly went
                    # net-flat → small-short during the 3:51pm
                    # flatten. The snapshot caught the wrong direction
                    # and froze it. Refuse to reconcile unless we've
                    # observed the same direction continuously for
                    # ≥30s. Symbols without enough history get
                    # `direction_unstable` skipped — operator can
                    # retry once steady-state is reached.
                    _stable, _reason = is_direction_stable(sym, direction.value)
                    if not _stable:
                        logger.warning(
                            "🛑 [v19.29 RECONCILE] %s direction-unstable — "
                            "%s. Refusing to claim until stability >= %ds.",
                            sym, _reason, _DIRECTION_STABILITY_SECONDS,
                        )
                        report["skipped"].append({
                            "symbol": sym,
                            "reason": "direction_unstable",
                            "detail": _reason,
                            "current_direction": direction.value,
                            "stability_required_seconds": _DIRECTION_STABILITY_SECONDS,
                            "suggest_manual": True,
                        })
                        continue

                    # Current price — prefer live quote, fall back to
                    # marketPrice from position, finally avgCost.
                    quote = ib_quotes.get(sym, {}) or {}
                    current_price = (
                        float(quote.get("last") or quote.get("close") or 0)
                        or ib_pos["market_price"]
                        or avg_cost
                    )

                    # Compute stop + target from defaults anchored on avgCost.
                    stop_distance = avg_cost * (default_stop_pct / 100.0)
                    target_distance = stop_distance * default_rr
                    if direction == TradeDirection.LONG:
                        stop_price = avg_cost - stop_distance
                        target_1 = avg_cost + target_distance
                    else:
                        stop_price = avg_cost + stop_distance
                        target_1 = avg_cost - target_distance

                    # Safety guard: stop already breached at current price.
                    breached = (
                        (direction == TradeDirection.LONG and current_price <= stop_price)
                        or (direction == TradeDirection.SHORT and current_price >= stop_price)
                    )
                    if breached:
                        report["skipped"].append({
                            "symbol": sym,
                            "reason": "stop_already_breached",
                            "avg_cost": avg_cost,
                            "current_price": current_price,
                            "proposed_stop": round(stop_price, 4),
                            "direction": direction.value,
                            "suggest_manual": True,
                        })
                        continue

                    risk_per_share = stop_distance
                    reward_per_share = target_distance

                    trade_id = str(uuid.uuid4())[:8]

                    trade = BotTrade(
                        id=trade_id,
                        symbol=sym,
                        direction=direction,
                        status=TradeStatus.OPEN,
                        setup_type="reconciled_orphan",
                        timeframe="intraday",
                        quality_score=50,
                        quality_grade="R",  # "R" for Reconciled
                        entry_price=avg_cost,
                        current_price=current_price,
                        stop_price=stop_price,
                        target_prices=[target_1],
                        shares=abs_qty,
                        risk_amount=risk_per_share * abs_qty,
                        potential_reward=reward_per_share * abs_qty,
                        risk_reward_ratio=default_rr,
                        trade_style="reconciled",
                        smb_grade="R",
                        close_at_eod=False,  # orphan reconciles default to hold overnight
                    )
                    trade.fill_price = avg_cost
                    trade.remaining_shares = abs_qty
                    trade.original_shares = abs_qty
                    trade.entry_time = datetime.now(timezone.utc)
                    trade.executed_at = datetime.now(timezone.utc).isoformat()
                    trade.created_at = datetime.now(timezone.utc).isoformat()
                    trade.notes = (
                        f"Reconciled from IB orphan — stop at {default_stop_pct:.1f}% "
                        f"from avg_cost, R:R {default_rr:.1f}"
                    )
                    # Initialize trailing stop config so the manage loop
                    # picks up the starting stop cleanly.
                    trade.trailing_stop_config["original_stop"] = stop_price
                    trade.trailing_stop_config["current_stop"] = stop_price
                    # Rich entry context so the V5 UI expanded row has
                    # the same shape as a bot-originated trade.
                    trade.entry_context = {
                        "scan_tier": "reconciled",
                        "smb_is_a_plus": False,
                        "exit_rule": f"default {default_stop_pct:.1f}% stop, {default_rr:.1f}:1 R:R",
                        "trading_approach": "reconciled orphan (bot claiming untracked IB position)",
                        "reasoning": [
                            f"Reconciled from IB orphan on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                            f"Entry anchored to IB avgCost ${avg_cost:.2f}",
                            f"Default bracket: stop ${stop_price:.2f} ({default_stop_pct:.1f}%), target ${target_1:.2f} ({default_rr:.1f} R:R)",
                        ],
                        "reconciled": True,
                        "reconcile_defaults": {
                            "stop_pct": default_stop_pct,
                            "rr": default_rr,
                        },
                    }

                    # Insert into in-memory + persist.
                    bot._open_trades[trade.id] = trade
                    await asyncio.to_thread(bot._persist_trade, trade)

                    # Best-effort: emit stream event so the V5 Unified
                    # Stream shows "Reconciled SBUX @ $100.12 · 150sh".
                    try:
                        from services.sentcom_service import emit_stream_event
                        await emit_stream_event({
                            "kind": "info",
                            "text": (
                                f"Reconciled {sym} {direction.value.upper()} "
                                f"{abs_qty}sh @ ${avg_cost:.2f} · "
                                f"SL ${stop_price:.2f} · PT ${target_1:.2f} · "
                                f"R:R {default_rr:.1f}"
                            ),
                            "symbol": sym,
                            "event": "trade_reconciled",
                            "metadata": {
                                "trade_id": trade.id,
                                "shares": abs_qty,
                                "direction": direction.value,
                                "avg_cost": avg_cost,
                                "stop_price": stop_price,
                                "target_price": target_1,
                                "risk_reward_ratio": default_rr,
                                "source": "reconcile_orphan_positions",
                            },
                        })
                    except Exception as emit_err:
                        logger.debug(f"Reconcile stream emit failed for {sym}: {emit_err}")

                    logger.info(
                        f"[RECONCILE] {sym} {direction.value.upper()} "
                        f"{abs_qty}sh @ ${avg_cost:.2f} · SL ${stop_price:.2f} · "
                        f"PT ${target_1:.2f} · trade_id={trade.id}"
                    )

                    report["reconciled"].append({
                        "symbol": sym,
                        "trade_id": trade.id,
                        "shares": abs_qty,
                        "direction": direction.value,
                        "entry_price": avg_cost,
                        "current_price": current_price,
                        "stop_price": round(stop_price, 4),
                        "target_price": round(target_1, 4),
                        "risk_reward_ratio": default_rr,
                        "stop_pct": default_stop_pct,
                    })

                except Exception as inner_err:
                    logger.exception(
                        f"reconcile_orphan_positions({sym}) failed: {inner_err}"
                    )
                    report["errors"].append({
                        "symbol": sym,
                        "error": str(inner_err),
                    })

            return report

        except Exception as e:
            logger.exception(f"reconcile_orphan_positions error: {e}")
            report["success"] = False
            report["error"] = str(e)
            return report


    # ==================== EMERGENCY STOP PROTECTION (Phase 4 — 2026-04-22) ==================

    async def protect_orphan_positions(
        self,
        bot: 'TradingBotService',
        risk_pct: float = 0.01,
        dry_run: bool = False,
    ) -> Dict:
        """Place emergency stops on IB positions that have no working stop.

        Runs at bot startup (and can be invoked manually) to close the gap
        where an IB position exists without a matching STP order — the exact
        scenario that caused the 2026-04 USO/WTI/PRCT bleed and the PD/GNW
        imported_from_ib $11k loss.

        A position is considered unprotected if:
          - It exists in IB, AND
          - Either (a) the bot has no corresponding open_trade, OR
                   (b) the bot has one but `stop_order_id` is falsy.

        Default emergency stop distance is `risk_pct` (1%) below entry for
        longs, above for shorts. This is conservative — the intent is "stop
        the bleed now", not "place the optimal stop". The user can refine
        the stop afterwards.

        Args:
            risk_pct: Default risk distance if no intended stop is known.
            dry_run: When True, log what would happen without placing orders.

        Returns:
            Dict with `protected`, `already_protected`, `skipped`, `errors`.
        """
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "protected": [],
            "already_protected": [],
            "skipped": [],
            "errors": [],
        }
        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected, queue_order

            if not is_pusher_connected():
                report["errors"].append({"error": "IB pusher not connected"})
                return report

            ib_positions = _pushed_ib_data.get("positions", []) or []

            # Map bot's open trades by symbol → (trade, has_stop)
            bot_trades_by_symbol = {}
            for trade in bot._open_trades.values():
                bot_trades_by_symbol[trade.symbol] = (trade, bool(trade.stop_order_id))

            for pos in ib_positions:
                symbol = pos.get("symbol") or (pos.get("contract", {}) or {}).get("symbol")
                if not symbol:
                    continue
                qty = float(pos.get("position", pos.get("qty", 0)) or 0)
                if abs(qty) < 1:
                    continue   # flat / phantom residual

                avg_cost = float(pos.get("avgCost", pos.get("avg_cost", 0)) or 0)
                is_long = qty > 0

                trade_entry = bot_trades_by_symbol.get(symbol)
                if trade_entry:
                    trade, has_stop = trade_entry
                    if has_stop:
                        report["already_protected"].append({
                            "symbol": symbol, "qty": qty, "trade_id": trade.id,
                            "stop_order_id": trade.stop_order_id,
                        })
                        continue
                    # Tracked trade without stop — use its intended stop if known
                    intended_stop = getattr(trade, "stop_price", None)
                else:
                    trade = None
                    intended_stop = None

                # Compute emergency stop price
                if intended_stop and intended_stop > 0:
                    stop_price = float(intended_stop)
                elif avg_cost > 0:
                    stop_price = round(
                        avg_cost * (1 - risk_pct) if is_long else avg_cost * (1 + risk_pct),
                        2,
                    )
                else:
                    report["skipped"].append({
                        "symbol": symbol, "qty": qty,
                        "reason": "no_price_to_derive_stop",
                    })
                    continue

                action = "SELL" if is_long else "BUY"
                stop_payload = {
                    "symbol": symbol,
                    "action": action,
                    "quantity": int(abs(qty)),
                    "order_type": "STP",
                    "stop_price": stop_price,
                    "limit_price": None,
                    "time_in_force": "GTC",
                    "outside_rth": True,
                    "trade_id": f"EMERGENCY-STOP-{symbol}-{uuid.uuid4().hex[:6]}",
                }

                if dry_run:
                    report["protected"].append({
                        **stop_payload, "dry_run": True,
                        "reason": "would_protect",
                    })
                    continue

                try:
                    oid = queue_order(stop_payload)
                    logger.warning(
                        f"🛡️ Emergency stop placed on {symbol} qty={qty} "
                        f"@ {stop_price} (was unprotected)"
                    )
                    if trade is not None:
                        trade.stop_order_id = oid
                        if not trade.stop_price:
                            trade.stop_price = stop_price
                        await bot._save_trade(trade)
                    report["protected"].append({
                        "symbol": symbol, "qty": qty, "stop_price": stop_price,
                        "order_id": oid, "trade_id": trade.id if trade else None,
                    })
                except Exception as e:
                    report["errors"].append({"symbol": symbol, "error": str(e)})

            logger.info(
                f"Orphan-position protection: protected={len(report['protected'])}, "
                f"already={len(report['already_protected'])}, "
                f"skipped={len(report['skipped'])}, errors={len(report['errors'])}"
            )
            return report

        except Exception as e:
            logger.error(f"protect_orphan_positions error: {e}")
            report["errors"].append({"error": str(e)})
            return report
