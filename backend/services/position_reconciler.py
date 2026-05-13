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
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import TradingBotService

logger = logging.getLogger(__name__)

# v19.34.15b — lazy idempotent index-ready flag for share_drift_events TTL.
_share_drift_indexes_ready: bool = False

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

    def __init__(self, db=None):
        # `db` is optional — when omitted (the bot's instantiation path
        # at `services/trading_bot_service.py`), we lazy-resolve via
        # `database.get_database()` on first read. This keeps the
        # router endpoint's explicit-db construction working too.
        self._db = db
        # ── v19.34.55 (Feb 2026) — drift-guard stats ─────────────────
        # Surface v19.34.52's SKIP events to the UI. Each SKIP is a
        # potential phantom-close prevented; the operator should be
        # able to see at a glance how often the guard is firing.
        # In-memory counters reset each new UTC day.
        from collections import deque
        self._guard_skip_count_today: int = 0
        self._guard_resolve_count_today: int = 0
        self._guard_stats_day: Optional[str] = None  # "YYYY-MM-DD" UTC
        self._guard_recent_skips: deque = deque(maxlen=20)
        self._guard_recent_resolves: deque = deque(maxlen=20)
        self._guard_first_skip_at: Optional[float] = None
        self._guard_last_skip_at: Optional[float] = None

        # ── v19.34.71 (Feb 2026) — Two-tick external-close confirmation ──
        # Even with v19.34.52's pusher+direct cross-check, a single scan
        # can catch a fill-propagation race that briefly shows IB=0 on
        # BOTH sources. Operator caught a -$326 NBIS phantom realized
        # loss on 2026-05-11 from exactly this fingerprint.
        #
        # The fix requires TWO consecutive scans to agree on the
        # zero-or-partial state before we record the accounting event.
        # First sighting → stash here, do not close. Next scan: if the
        # state still matches (same symbol, same bot trade-id set,
        # still IB=0), confirm and close. If state has changed
        # (position re-appeared, or new bot trades opened), drop the
        # pending entry.
        #
        # Key: symbol (uppercased). Value: dict with first_seen_ts,
        # bot_trade_ids (set), and drift_kind ("zero" or "partial").
        # Pending entries auto-expire after 90 seconds so a missed
        # scan cycle doesn't strand the symbol in pending forever.
        self._pending_external_close: Dict[str, Dict[str, Any]] = {}
        self._PENDING_EXTERNAL_CLOSE_TTL_S: float = 90.0
        # Optional override for tests/operator tuning.
        try:
            self._PENDING_EXTERNAL_CLOSE_TTL_S = float(
                os.environ.get("PENDING_EXTERNAL_CLOSE_TTL_S", 90.0)
            )
        except Exception:
            pass

        # ── v19.34.111 (Feb 2026) — Bracket-attach cooldown ──────────────
        # Even with queue-level trade_id idempotency catching duplicates
        # at the lowest layer, the reconciler should NOT be racing
        # attach attempts every 30s for the same logical trade. If the
        # last attach call hasn't reached a terminal state — fill,
        # cancel, or a clean failure that surfaced an actionable error
        # — the right move is "wait and let it land," not "queue
        # another pair." This belt-and-suspenders guard caps the
        # attach frequency to once per `BRACKET_ATTACH_COOLDOWN_S`
        # per (trade.id) so even a misconfigured caller can't melt
        # the queue.
        #
        # Key: trade.id (string). Value: monotonic timestamp of the
        # last attach attempt (success OR failure — we cooldown both
        # paths because a failure usually means the position is still
        # being worked at IB, not that the pusher silently dropped it).
        self._last_bracket_attach_at: Dict[str, float] = {}
        try:
            self._BRACKET_ATTACH_COOLDOWN_S: float = float(
                os.environ.get("BRACKET_ATTACH_COOLDOWN_S", 60.0)
            )
        except Exception:
            self._BRACKET_ATTACH_COOLDOWN_S = 60.0
        # Cooldown skip counter (operator-visible diagnostic).
        self._bracket_attach_cooldown_skips: int = 0
        # ── v19.34.115 (V6-integration prep) ───────────────────────
        # Promote the simple int counter to a recent-skips deque so
        # the future V6 Safety Activity Stream can render per-event
        # detail rows, not just totals. Mirrors the
        # `_guard_recent_skips` deque on the drift-guard path.
        from collections import deque as _deque
        self._bracket_attach_recent_skips: 'deque' = _deque(maxlen=200)

    def get_attach_cooldown_skips(self) -> List[Dict[str, Any]]:
        """v19.34.115 — Public read for the V6 Safety Activity Stream
        aggregator. Returns a snapshot list of recent
        bracket-attach cooldown skips (newest last). Each entry has:

            {
              "ts": iso-utc,
              "trade_id": str,
              "symbol": str | None,
              "cooldown_remaining_s": float,
              "cooldown_window_s": float,
            }
        """
        # Snapshot copy so the caller can't mutate the deque.
        return list(self._bracket_attach_recent_skips)

    def _bracket_attach_in_cooldown(self, trade_id: str) -> Optional[float]:
        """Return seconds remaining in cooldown for `trade_id`, or None
        if not in cooldown.

        Empty / falsy trade_id always passes (legacy paths without an
        id stay backward-compatible).
        """
        if not trade_id:
            return None
        import time as _time
        last = self._last_bracket_attach_at.get(trade_id)
        if last is None:
            return None
        elapsed = _time.monotonic() - last
        remaining = self._BRACKET_ATTACH_COOLDOWN_S - elapsed
        return remaining if remaining > 0 else None

    def _stamp_bracket_attach(self, trade_id: str) -> None:
        """Record that we just attempted a bracket attach for `trade_id`.

        Called whether the attach succeeded, failed, or raised — the
        cooldown is on *attempts*, not outcomes. A subsequent caller
        gets blocked for `BRACKET_ATTACH_COOLDOWN_S` regardless.
        """
        if not trade_id:
            return
        import time as _time
        self._last_bracket_attach_at[trade_id] = _time.monotonic()

    def _record_bracket_attach_skip(
        self,
        trade_id: str,
        cooldown_remaining_s: float,
        symbol: Optional[str] = None,
    ) -> None:
        """v19.34.115 — Bookkeeping for the V6 Safety Activity Stream.

        Each production call site (orphan-adoption, grow-slice,
        spawn-slice) calls this AFTER detecting a cooldown skip so
        the aggregator can render per-event detail rows. The legacy
        int counter still increments for backward-compat consumers.
        """
        self._bracket_attach_cooldown_skips += 1
        try:
            self._bracket_attach_recent_skips.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "trade_id": trade_id,
                "symbol": symbol,
                "cooldown_remaining_s": round(float(cooldown_remaining_s), 1),
                "cooldown_window_s": float(self._BRACKET_ATTACH_COOLDOWN_S),
            })
        except Exception:
            # Never let bookkeeping crash the reconciler.
            pass

    def _stats_roll_day_if_needed(self):
        """Reset counters on UTC midnight."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._guard_stats_day != today:
            self._guard_stats_day = today
            self._guard_skip_count_today = 0
            self._guard_resolve_count_today = 0
            self._guard_recent_skips.clear()
            self._guard_recent_resolves.clear()
            self._guard_first_skip_at = None
            self._guard_last_skip_at = None

    def _record_guard_skip(self, drift_record: dict) -> None:
        import time as _time
        self._stats_roll_day_if_needed()
        self._guard_skip_count_today += 1
        now = _time.time()
        if self._guard_first_skip_at is None:
            self._guard_first_skip_at = now
        self._guard_last_skip_at = now
        # Keep a lean record (sym + reason + ts) for tooltip/history.
        self._guard_recent_skips.append({
            "ts": now,
            "symbol": drift_record.get("symbol"),
            "kind": drift_record.get("kind"),
            "reason": drift_record.get("skip_reason"),
            "pusher_qty": drift_record.get("pusher_qty"),
            "direct_qty": drift_record.get("direct_qty"),
        })

    def _record_guard_resolve(self, drift_record: dict) -> None:
        import time as _time
        self._stats_roll_day_if_needed()
        self._guard_resolve_count_today += 1
        self._guard_recent_resolves.append({
            "ts": _time.time(),
            "symbol": drift_record.get("symbol"),
            "kind": drift_record.get("kind"),
            "shares": drift_record.get("drift_shares"),
        })

    def _confirm_external_close_two_tick(
        self,
        symbol: str,
        bot_trade_ids: set,
        drift_kind: str,
    ) -> tuple[bool, str]:
        """v19.34.71 — Two-tick confirmation gate for `external_close_v19_34_15b`.

        Returns `(confirmed, reason)`. When `confirmed=False`, the caller
        MUST skip the close on this tick and stash the symbol for the
        next scan. When `confirmed=True`, the caller proceeds with the
        close exactly as before.

        State machine:
          - First sighting → record (symbol, bot_trade_ids, ts), return
            `(False, "first_sighting_v19_34_71")`. No close.
          - Second sighting with SAME bot_trade_ids → return
            `(True, "confirmed_two_tick_v19_34_71")`. Caller closes.
          - Second sighting with DIFFERENT bot_trade_ids → reset
            pending state, return `(False, "trade_set_changed_v19_34_71")`.
            (Bot opened/closed something between scans — restart the
            confirmation window from this scan.)
          - Pending entry older than TTL → treated as new first sighting.

        Why: even with v19.34.52's pusher+direct cross-check, a single
        scan can catch a fill-propagation race where both sources
        briefly read zero (NBIS phantom -$326 realized 2026-05-11).
        Requiring two consecutive scans to agree eliminates all known
        single-tick races without slowing legitimate closes meaningfully
        (the reconciler runs every ~30-60s, so a real flatten is
        recorded within one cycle).
        """
        import time as _time
        now = _time.time()
        sym_u = (symbol or "").upper()
        pending = self._pending_external_close.get(sym_u)

        if pending is not None:
            age = now - pending.get("first_seen_ts", 0)
            if age > self._PENDING_EXTERNAL_CLOSE_TTL_S:
                pending = None  # expired → treat as first sighting

        if pending is None:
            self._pending_external_close[sym_u] = {
                "first_seen_ts": now,
                "bot_trade_ids": set(bot_trade_ids),
                "drift_kind": drift_kind,
            }
            return False, "first_sighting_v19_34_71"

        # We have a pending entry within TTL. Did the trade set change?
        if pending.get("bot_trade_ids") != set(bot_trade_ids):
            # Bot's open trades for this symbol changed between scans
            # (a real fill or close happened). Don't trust this tick —
            # reset confirmation window starting now.
            self._pending_external_close[sym_u] = {
                "first_seen_ts": now,
                "bot_trade_ids": set(bot_trade_ids),
                "drift_kind": drift_kind,
            }
            return False, "trade_set_changed_v19_34_71"

        # Confirmed across two ticks with identical trade set.
        # Pop pending so re-occurrence in future requires a fresh
        # two-tick cycle.
        self._pending_external_close.pop(sym_u, None)
        return True, "confirmed_two_tick_v19_34_71"

    def _clear_pending_external_close(self, symbol: str) -> None:
        """Drop a pending two-tick confirmation. Called when the symbol's
        state moves AWAY from zero/partial (i.e., position re-appeared or
        the bot trade was closed by some other path)."""
        self._pending_external_close.pop((symbol or "").upper(), None)

    def get_guard_stats(self) -> dict:
        """v19.34.55 — Snapshot for the UI status pill."""
        self._stats_roll_day_if_needed()
        return {
            "day_utc": self._guard_stats_day,
            "skip_count_today": self._guard_skip_count_today,
            "resolve_count_today": self._guard_resolve_count_today,
            "first_skip_at": self._guard_first_skip_at,
            "last_skip_at": self._guard_last_skip_at,
            "recent_skips": list(self._guard_recent_skips),
            "recent_resolves": list(self._guard_recent_resolves),
        }

    @property
    def db(self):
        if self._db is None:
            try:
                from database import get_database
                self._db = get_database()
            except Exception:
                return None
        return self._db

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

            # v19.34.130 — Use apply_close_pnl for: commission subtraction
            # (pre-v130 net_pnl stayed at 0 on phantom closes), alert_outcomes
            # write (learning loop signal), and exit_price_source audit.
            # Inline PnL math removed — single source of truth via pnl_compute.
            from services.pnl_compute import apply_close_pnl
            phantom_exit_price = (
                trade.current_price if (trade.current_price and trade.current_price > 0)
                else trade.fill_price
            )
            apply_close_pnl(
                trade,
                reason=f"phantom_close:{reason}",
                exit_price=phantom_exit_price,
            )
            trade.status = TradeStatus.CLOSED
            trade.exit_time = datetime.now(timezone.utc)
            trade.exit_reason = reason

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
                "net_pnl": trade.net_pnl,
                "unrealized_pnl": 0,
                "remaining_shares": 0,
                "closed_at": trade.closed_at,
                "close_reason": trade.close_reason,
            }
            await asyncio.to_thread(
                bot._db.bot_trades.update_one,
                {"id": trade_id}, {"$set": update_doc}
            )

            logger.info(f"Closed phantom trade {trade.symbol} ({trade_id}): reason={reason}, P&L=${trade.realized_pnl:.2f} (net=${trade.net_pnl:.2f})")

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

            # ── v19.34.22 (2026-05-07) — DB-aware tracked-set hardening.
            # Operator-discovered duplicate-spawn bug 2026-05-06 during
            # zombie-cleanup forensics: when a v19.34.15b/v19.34.19
            # `reconciled_excess_*` slice (or a v19.24 `reconciled_external`
            # orphan) is persisted to `bot_trades` but NOT yet hydrated
            # into `_open_trades` (restart race window, or out-of-band
            # insert from another worker), this method treated the
            # symbol as untracked and spawned a duplicate `reconciled_orphan`
            # against the same IB position. The bot then believed it
            # owned 2× the IB qty.
            #
            # Fix: union `_open_trades` symbol set with the DB's open-row
            # symbol set so duplicate spawns are impossible regardless of
            # in-memory hydration timing. Lookup is cheap (`status==open`
            # rows are bounded by the active position count).
            db_tracked: set = set()
            try:
                if self.db is not None:
                    db_cursor = self.db["bot_trades"].find(
                        {"status": "open"},
                        {"_id": 0, "symbol": 1},
                    )
                    for _doc in db_cursor:
                        _ssym = (_doc.get("symbol") or "").upper()
                        if _ssym:
                            db_tracked.add(_ssym)
                    bot_tracked |= db_tracked
            except Exception as _db_track_exc:
                logger.debug(
                    "[v19.34.22 RECONCILE] DB-tracked lookup failed "
                    "(non-fatal, falling back to in-memory only): %s",
                    _db_track_exc,
                )

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
                        # v19.34.22 — distinguish DB-only matches so the
                        # operator-visible report makes the reason for
                        # the skip unambiguous (no duplicate orphan was
                        # spawned because an open `bot_trades` row
                        # already claims this symbol, even if it isn't
                        # in `_open_trades` yet).
                        _is_db_only = sym in db_tracked and not any(
                            (t.symbol or "").upper() == sym
                            for t in bot._open_trades.values()
                        )
                        report["skipped"].append({
                            "symbol": sym,
                            "reason": "db_already_tracked" if _is_db_only else "already_tracked",
                        })
                        continue

                    # v19.34.134 — recently-closed-symbol cooldown.
                    # FIXES the AJG/FLEX duplicate-close bug (2026-05-13):
                    # IB carries a position the bot didn't open → reconciler
                    # adopts it → manage loop immediately fires `stop_loss`
                    # close because price is already below the default
                    # 2% stop → close_trade writes a `bot_trades` row but
                    # the IB position survives (orphan-attach failed, or
                    # the local close doesn't sell at IB). 5 min later
                    # this reconciler sees the IB position again →
                    # re-adopts → re-closes → fresh fake -$80 / -$694
                    # `realized_pnl` row. Compounded over 7 hours = $3.5k+
                    # of phantom realized loss vs TWS.
                    #
                    # Fix: after ANY close_trade fires for a symbol, bot
                    # stamps `bot._recently_closed_symbols[sym] = ts` with
                    # a 30-min TTL. We skip re-adoption inside that window
                    # so the IB position is left for the operator to
                    # manually clear (or for the next reconcile pass once
                    # IB confirms it's gone).
                    rcs = getattr(bot, "_recently_closed_symbols", None) or {}
                    closed_at = rcs.get(sym)
                    if closed_at is not None:
                        try:
                            age_s = (datetime.now(timezone.utc) - closed_at).total_seconds()
                        except Exception:
                            age_s = None
                        if age_s is not None and 0 <= age_s < 1800:
                            report["skipped"].append({
                                "symbol": sym,
                                "reason": "recently_closed_cooldown",
                                "cooldown_remaining_s": round(1800 - age_s, 0),
                                "closed_at": closed_at.isoformat(),
                            })
                            logger.info(
                                "[v19.34.134 RECONCILE] %s skipped — closed %.0fs ago, "
                                "%.0fs remaining in 30-min cooldown. Prevents the "
                                "AJG/FLEX duplicate-close loop.",
                                sym, age_s, 1800 - age_s,
                            )
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
                        # v19.34.17 (2026-05-06) — operator-approved EOD policy:
                        # ORPHAN reconciled positions flatten at EOD. Rationale:
                        # the bot didn't originate them (came in via v19.24
                        # orphan-reconcile path) so it has no thesis tying them
                        # to a multi-day swing — they should not carry overnight
                        # risk. Bot-originated `day_swing`/`position` trades
                        # still set `close_at_eod=False` at entry-time and are
                        # unaffected by this change.
                        close_at_eod=True,
                    )
                    trade.fill_price = avg_cost
                    trade.remaining_shares = abs_qty
                    trade.original_shares = abs_qty
                    trade.entry_time = datetime.now(timezone.utc)
                    trade.executed_at = datetime.now(timezone.utc).isoformat()
                    trade.created_at = datetime.now(timezone.utc).isoformat()

                    # ── v19.34.3 (2026-05-04) — Provenance + Smart Stop ──
                    # Operator-discovered (VALE bug): the reconciler was
                    # silently materializing IB orphans with default 2%
                    # SL / 2.0 R:R — which didn't reflect the bot's real
                    # rejection verdicts on those same setups. The bot
                    # had been rejecting VALE all afternoon for R:R 1.19,
                    # yet the reconciled row showed R:R 2.0 (synthetic).
                    # Now:
                    #   1. Stamp `entered_by="reconciled_external"` so the
                    #      UI can chip "RECONCILED · Bot did not open".
                    #   2. Query the last 5 rejection events from
                    #      sentcom_thoughts to learn the bot's prior
                    #      verdict on this symbol/setup.
                    #   3. If a recent verdict has real entry/stop/target
                    #      numbers, prefer THOSE over synthetic defaults
                    #      (smart stop). Stamp `synthetic_source` so the
                    #      UI shows which logic was used.
                    #   4. If ≥2 of the last 3 verdicts were rejections,
                    #      flag this row as `prior_verdict_conflict=True`
                    #      so the UI can show a HIGH-priority warning.
                    trade.entered_by = "reconciled_external"
                    prior_verdicts: list = []
                    last_rej_meta: Dict[str, Any] = {}
                    rejection_count_last_3 = 0
                    try:
                        cursor = self.db["sentcom_thoughts"].find(
                            {
                                "symbol": sym,
                                "kind": "rejection",
                            },
                            {"_id": 0},
                            sort=[("timestamp", -1)],
                            limit=5,
                        )
                        for thought in cursor:
                            md = thought.get("metadata") or {}
                            verdict = {
                                "timestamp": thought.get("timestamp"),
                                "setup_type": md.get("setup_type"),
                                "direction": md.get("direction"),
                                "reason_code": md.get("reason_code"),
                                "rr_ratio": md.get("rr_ratio"),
                                "min_required": md.get("min_required"),
                                "entry_price": md.get("entry_price"),
                                "stop_price": md.get("stop_price"),
                                "primary_target": md.get("primary_target"),
                                "text": thought.get("text"),
                            }
                            prior_verdicts.append(verdict)
                            if len(prior_verdicts) <= 3:
                                rejection_count_last_3 += 1
                            # Latch the most recent verdict that has
                            # real numbers we can use for smart stop.
                            if not last_rej_meta and md.get("entry_price"):
                                last_rej_meta = md
                    except Exception as e:
                        logger.debug(f"reconcile {sym}: prior-verdict lookup failed: {e}")

                    # Smart synthetic SL/PT: use the bot's real numbers
                    # when available, but only when they're directionally
                    # consistent with the IB position (LONG bot stop must
                    # be below avg_cost; SHORT bot stop must be above).
                    use_smart_stop = False
                    if last_rej_meta:
                        _e = last_rej_meta.get("entry_price")
                        _s = last_rej_meta.get("stop_price")
                        _t = last_rej_meta.get("primary_target")
                        if _e and _s and _t:
                            try:
                                _e, _s, _t = float(_e), float(_s), float(_t)
                                if direction == TradeDirection.LONG:
                                    if _s < avg_cost < _t:
                                        stop_price = _s
                                        target_1 = _t
                                        use_smart_stop = True
                                else:  # SHORT
                                    if _t < avg_cost < _s:
                                        stop_price = _s
                                        target_1 = _t
                                        use_smart_stop = True
                                # Recompute risk-reward from the smart numbers.
                                if use_smart_stop:
                                    risk_per_share = abs(avg_cost - stop_price)
                                    reward_per_share = abs(target_1 - avg_cost)
                                    if risk_per_share > 0:
                                        smart_rr = reward_per_share / risk_per_share
                                    else:
                                        smart_rr = default_rr
                                else:
                                    smart_rr = default_rr
                            except Exception:
                                smart_rr = default_rr
                        else:
                            smart_rr = default_rr
                    else:
                        smart_rr = default_rr

                    trade.target_prices = [target_1]
                    trade.stop_price = stop_price
                    trade.risk_amount = abs(avg_cost - stop_price) * abs_qty
                    trade.risk_reward_ratio = round(smart_rr, 2)

                    trade.synthetic_source = (
                        "last_verdict" if use_smart_stop else "default_pct"
                    )
                    trade.prior_verdicts = prior_verdicts
                    trade.prior_verdict_conflict = (
                        rejection_count_last_3 >= 2
                    )
                    # If ≥2 of the last 3 verdicts were rejections,
                    # emit a HIGH-priority warning event so the operator
                    # never silently inherits a setup the bot dismissed.
                    if trade.prior_verdict_conflict:
                        try:
                            from services.sentcom_service import emit_stream_event
                            recent_rr = next(
                                (v.get("rr_ratio") for v in prior_verdicts
                                 if v.get("rr_ratio") is not None),
                                None,
                            )
                            recent_setup = next(
                                (v.get("setup_type") for v in prior_verdicts
                                 if v.get("setup_type")),
                                None,
                            )
                            warn_text = (
                                f"⚠ Reconciling {sym} {direction.value.upper()} "
                                f"{abs_qty}sh @ ${avg_cost:.2f} — but my "
                                f"last {rejection_count_last_3} of 3 verdicts on "
                                f"{recent_setup or 'this setup'} were REJECT"
                                + (f" (R:R {recent_rr})" if recent_rr is not None else "")
                                + ". I did NOT open this position. Smart stop "
                                + (f"@ ${stop_price:.2f} pulled from last verdict's "
                                   f"computed numbers." if use_smart_stop
                                   else f"@ ${stop_price:.2f} is synthetic ("
                                        f"{default_stop_pct:.1f}% from avg). "
                                        "Consider closing manually or overriding SL/PT.")
                            )
                            asyncio.create_task(emit_stream_event({
                                "kind": "warning",
                                "event": "reconcile_prior_verdict_conflict_v19_34_3",
                                "symbol": sym,
                                "text": warn_text,
                                "severity": "high",
                                "metadata": {
                                    "trade_id": trade.id,
                                    "rejection_count_last_3": rejection_count_last_3,
                                    "synthetic_source": trade.synthetic_source,
                                    "stop_price": stop_price,
                                    "target_1": target_1,
                                    "recent_rr": recent_rr,
                                    "recent_setup": recent_setup,
                                },
                            }))
                        except Exception as _emit_exc:
                            logger.debug(
                                f"reconcile {sym}: conflict-warning emit failed: {_emit_exc}"
                            )
                    # ── end v19.34.3 ──────────────────────────────────────

                    # v19.34.1 (2026-05-04) — stamp trade_type from the
                    # current pusher account so reconciled-orphan rows
                    # also chip PAPER/LIVE/UNKNOWN in the V5 UI. Orphans
                    # are silent on which account they came from at fill
                    # time, but the operator's *current* connected account
                    # is the same one the orphan must belong to (otherwise
                    # the pusher snapshot wouldn't show it).
                    try:
                        from services.account_guard import classify_account_id
                        from services.ib_pusher_rpc import get_account_snapshot
                        # v19.34.8 (2026-05-05) — wrap sync pusher RPC in
                        # asyncio.to_thread to prevent event-loop wedge.
                        # `get_account_snapshot` blocks on socket I/O for
                        # up to 5s during pusher outages; called inline
                        # from async = the entire FastAPI loop stalls.
                        # Same wedge class as v19.30.6/v19.30.8 fixes.
                        snap = await asyncio.to_thread(get_account_snapshot)
                        cur_account_id = (snap or {}).get("account_id") or ""
                        trade.trade_type = classify_account_id(cur_account_id)
                        trade.account_id_at_fill = cur_account_id or None
                    except Exception as _acct_exc:
                        # Safe default: leave as "unknown" / None so the
                        # chip simply doesn't render rather than mislabel.
                        logger.debug(
                            f"reconcile {sym}: trade_type stamp skipped: {_acct_exc}"
                        )
                        trade.trade_type = "unknown"
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

                    # v19.34.68 — Submit the actual OCA stop+target legs to IB.
                    # Pre-v19.34.68 we recorded the bracket only in bot_trades
                    # (stop_price/target_prices fields) but never submitted the
                    # protective orders to IB. The 2026-05-11 CEG/FIG incident
                    # surfaced this: adopted positions appeared as "AMBER" in
                    # the UI (bot view) but were NAKED at IB — $100K of
                    # exposure on a $237K account with zero auto-stop.
                    #
                    # `attach_oca_stop_target` was added in v19.34.28 for
                    # `_spawn_excess_slice` (share-drift Case 1) but was never
                    # wired into this `reconcile_orphan_positions` path. This
                    # block closes that gap: same OCA-bracket attach pattern,
                    # same fail-safe rules (STP first, abort target if STP
                    # fails, never leave one-sided exposure).
                    bracket_attach_result: Dict[str, Any] = {"success": False, "skipped": "no_executor"}
                    executor = getattr(bot, "_trade_executor", None)
                    if executor and hasattr(executor, "attach_oca_stop_target"):
                        # v19.34.111 — cooldown guard. Skip if we tried
                        # attach for this trade.id <60s ago. Belt + suspenders
                        # on top of the queue-level trade_id idempotency.
                        _cooldown_left = self._bracket_attach_in_cooldown(trade.id)
                        if _cooldown_left is not None:
                            self._record_bracket_attach_skip(trade.id, _cooldown_left, symbol=sym)
                            bracket_attach_result = {
                                "success": False,
                                "skipped": "bracket_attach_cooldown",
                                "cooldown_remaining_s": round(_cooldown_left, 1),
                            }
                            logger.info(
                                f"[v19.34.111 COOLDOWN] {sym} {trade.id} skip "
                                f"attach — {_cooldown_left:.1f}s left in cooldown."
                            )
                        else:
                            self._stamp_bracket_attach(trade.id)
                            try:
                                oca_result = await executor.attach_oca_stop_target(trade)
                                if oca_result and oca_result.get("success"):
                                    trade.stop_order_id = oca_result.get("stop_order_id")
                                    tgt_id = oca_result.get("target_order_id")
                                    if tgt_id:
                                        # BotTrade tracks targets as a list
                                        # (`target_order_ids`) since brackets
                                        # can scale out across multiple PTs.
                                        if not hasattr(trade, "target_order_ids") or trade.target_order_ids is None:
                                            trade.target_order_ids = []
                                        trade.target_order_ids.append(tgt_id)
                                    trade.oca_group = oca_result.get("oca_group")
                                    # Re-persist so the order IDs land in bot_trades.
                                    await asyncio.to_thread(bot._persist_trade, trade)
                                    bracket_attach_result = oca_result
                                    logger.info(
                                        f"[RECONCILE BRACKET] {sym} OCA attached: "
                                        f"stop={trade.stop_order_id} "
                                        f"tgt={getattr(trade, 'target_order_ids', [])} "
                                        f"oca={getattr(trade, 'oca_group', None)}"
                                    )
                                else:
                                    err = (oca_result or {}).get("error", "unknown")
                                    bracket_attach_result = {"success": False, "error": err}
                                    logger.error(
                                        f"[RECONCILE NAKED] {sym} {trade.id} adopted "
                                        f"{abs_qty}sh but OCA attach failed: {err}. "
                                        f"Position is UNPROTECTED at IB — operator must "
                                        f"add stop manually or wait for retry."
                                    )
                            except Exception as e:
                                bracket_attach_result = {"success": False, "error": str(e)}
                                logger.error(
                                    f"[RECONCILE NAKED] {sym} OCA attach raised: {e}. "
                                    f"Position UNPROTECTED."
                                )
                    else:
                        logger.warning(
                            f"[RECONCILE] {sym} adopted but no executor with "
                            f"attach_oca_stop_target — position UNPROTECTED at IB"
                        )

                    # Best-effort: emit stream event so the V5 Unified
                    # Stream shows "Reconciled SBUX @ $100.12 · 150sh".
                    try:
                        from services.sentcom_service import emit_stream_event
                        await emit_stream_event({
                            "kind": "info" if bracket_attach_result.get("success") else "warning",
                            "text": (
                                f"Reconciled {sym} {direction.value.upper()} "
                                f"{abs_qty}sh @ ${avg_cost:.2f} · "
                                f"SL ${stop_price:.2f} · PT ${target_1:.2f} · "
                                f"R:R {default_rr:.1f}"
                                + ("" if bracket_attach_result.get("success") else " · ⚠ BRACKET ATTACH FAILED — NAKED AT IB")
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
                                "bracket_attached": bool(bracket_attach_result.get("success")),
                                "bracket_attach_error": bracket_attach_result.get("error"),
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
                        # v19.34.68 — surface bracket-attach outcome so
                        # operators / UI can tell at a glance whether the
                        # adopted position is actually protected at IB.
                        "bracket_attached": bool(bracket_attach_result.get("success")),
                        "bracket_attach_error": bracket_attach_result.get("error"),
                        "stop_order_id": getattr(trade, "stop_order_id", None),
                        "target_order_id": (getattr(trade, "target_order_ids", []) or [None])[0],
                        "target_order_ids": list(getattr(trade, "target_order_ids", []) or []),
                        "oca_group": getattr(trade, "oca_group", None),
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


    # ============== v19.34.15b SHARE-COUNT DRIFT RECONCILER (2026-05-06) =============

    async def reconcile_share_drift(
        self,
        bot: 'TradingBotService',
        drift_threshold: int = 1,
        auto_resolve: bool = True,
        zombie_detect_only: bool = False,
    ) -> Dict[str, Any]:
        """Detect + resolve share-count drift on already-tracked symbols.

        v19.34.15b. Operator caught a 4,879-share UPS drift (IB had
        5,304 long, app tracked only 425) caused by `[REJECTED: Bracket
        unknown]` parent orders firing at IB despite the bot writing
        them off. The orphan reconciler skips with `already_tracked`
        whenever `sym in bot._open_trades` — it's blind to share-count
        drift. This method fills that gap.

        Three cases (per operator approval 2026-05-06):

          1. **Excess** (IB qty > tracked qty + threshold) — spawn a
             new BotTrade for the delta as `reconciled_excess_slice`,
             anchored on `current_price` with default 2% stop / 2R
             target (same defaults as orphan reconcile). Stamps
             `reconciled_excess_v19_34_15b` provenance for the V5 UI.

          2. **Partial** (IB qty < tracked qty, IB qty > 0) — shrink
             the bot's tracked `remaining_shares` to match IB. Emits
             `external_partial_close_v19_34_15b` stream event so the
             operator sees what happened. Does NOT close the trade —
             let manage-loop continue tracking the remainder.

          3. **Zero** (IB qty == 0, tracked qty > 0) — close the
             bot_trade with `close_reason='external_close_v19_34_15b'`
             (operator-approved auto-close on inverse case). Removes
             from `_open_trades` and persists the close to Mongo.

        Threshold default `1` share matches operator approval. Bumped
        via the endpoint payload for fractional-share / rounding noise.

        Returns:
            {
              success, timestamp,
              drifts_resolved: [{symbol, kind, ...detail}],
              drifts_detected: [...],   # all drifts including unresolved
              skipped: [...],
              errors: [...],
            }
        """
        from services.trading_bot_service import (
            TradeDirection, TradeStatus, BotTrade,
        )

        report: Dict[str, Any] = {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "auto_resolve": auto_resolve,
            "zombie_detect_only": zombie_detect_only,
            "drift_threshold": drift_threshold,
            "drifts_detected": [],
            "drifts_resolved": [],
            "skipped": [],
            "errors": [],
        }

        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected
            if not is_pusher_connected():
                report["success"] = False
                report["error"] = "IB pusher not connected"
                return report

            # Reuse the orphan reconciler's IB-position-map shape.
            ib_positions = _pushed_ib_data.get("positions", []) or []
            ib_qty_by_sym: Dict[str, float] = {}
            ib_meta_by_sym: Dict[str, Dict[str, Any]] = {}
            for pos in ib_positions:
                sym = (pos.get("symbol") or pos.get("contract", {}).get("symbol") or "").upper()
                if not sym:
                    continue
                qty = float(pos.get("position", pos.get("qty", 0)) or 0)
                # Keep zero-qty entries here — we WANT to detect "IB has 0".
                ib_qty_by_sym[sym] = qty
                ib_meta_by_sym[sym] = {
                    "avg_cost": float(pos.get("avgCost", pos.get("avg_cost", 0)) or 0),
                    "market_price": float(
                        pos.get("marketPrice", pos.get("market_price", 0)) or 0
                    ),
                }
            ib_quotes = _pushed_ib_data.get("quotes", {}) or {}

            # Build bot signed-qty map from in-memory _open_trades.
            bot_qty_by_sym: Dict[str, float] = {}
            bot_trades_by_sym: Dict[str, list] = {}
            for t in list(bot._open_trades.values()):
                ssym = (getattr(t, "symbol", "") or "").upper()
                if not ssym:
                    continue
                rs = float(getattr(t, "remaining_shares", 0) or 0)
                d = getattr(t, "direction", None)
                d_val = getattr(d, "value", str(d) if d else "long").lower()
                signed = rs if d_val == "long" else -rs
                bot_qty_by_sym[ssym] = bot_qty_by_sym.get(ssym, 0.0) + signed
                bot_trades_by_sym.setdefault(ssym, []).append(t)

            # Iterate every symbol that's tracked OR present at IB.
            all_syms = set(bot_qty_by_sym.keys()) | set(ib_qty_by_sym.keys())

            # v19.34.15b — operator-approved 2026-05-06: excess slices use
            # tighter defaults than the orphan-reconcile path because the
            # entry origin is unknown (likely a [REJECTED: Bracket unknown]
            # parent fill). 1% stop / 1R target keeps blast-radius bounded
            # even if current_price is mid-range. Orphan reconciler keeps
            # using risk_params defaults because those positions were
            # discovered fresh on a known cost-basis.
            excess_stop_pct = float(getattr(
                bot.risk_params, "drift_excess_stop_pct", 1.0,
            ))
            excess_rr = float(getattr(
                bot.risk_params, "drift_excess_rr", 1.0,
            ))

            for sym in sorted(all_syms):
                bot_q = bot_qty_by_sym.get(sym, 0.0)
                ib_q = ib_qty_by_sym.get(sym, 0.0)
                drift = ib_q - bot_q

                # In sync (within threshold)? → skip.
                if abs(drift) <= drift_threshold:
                    # v19.34.71 — Symbol back in sync ⇒ drop any pending
                    # two-tick external-close confirmation. Without this,
                    # a transient (zero → recovered → zero-again) within
                    # the 90s TTL would short-circuit the gate and close
                    # on the third sighting as if it were a clean
                    # confirmation. Clearing here forces a fresh
                    # two-tick window for each new external-close event.
                    self._clear_pending_external_close(sym)
                    continue

                # ── v19.34.19 (2026-05-06) — Zombie-trade blind spot fix ──
                # OLD: `sym not in bot_qty_by_sym or abs(bot_q) < 0.01` → skip
                # both cases. That hid the "zombie" pattern caught 2026-05-06
                # by operator: bot tracks 3 OPEN trades for FDX/UPS with
                # `remaining_shares=0` (lifecycle bug — partial-close path
                # zeroed shares without flipping status to CLOSED). Bot_q sums
                # to 0 but IB still has the parent fill. Orphan reconciler
                # ignores them (sym IS tracked); old 15b skipped them too.
                # 1592 unmanaged shares accumulated.
                #
                # NEW: distinguish the cases.
                if sym not in bot_qty_by_sym:
                    # Pure orphan — defer to reconcile_orphan_positions.
                    report["skipped"].append({
                        "symbol": sym, "reason": "ib_only_use_orphan_reconciler",
                        "ib_qty": ib_q,
                    })
                    continue

                zombies = [
                    t for t in bot_trades_by_sym.get(sym, [])
                    if int(abs(getattr(t, "remaining_shares", 0) or 0)) == 0
                ]
                if abs(bot_q) < 0.01 and len(zombies) > 0 and abs(ib_q) >= 1:
                    # Tracked-but-zombie drift: bot has OPEN trades but
                    # zero remaining_shares while IB still holds the position.
                    # Spawn a `reconciled_excess_slice` to bracket the IB
                    # qty AND mark the zombie bot_trades closed for audit.
                    drift_record = {
                        "symbol": sym, "ib_qty": ib_q, "bot_qty": bot_q,
                        "drift_shares": drift, "kind": "zombie_trade_drift",
                        "zombie_count": len(zombies),
                        "zombie_trade_ids": [getattr(z, "id", None) for z in zombies],
                    }
                    report["drifts_detected"].append(drift_record)
                    if not auto_resolve or zombie_detect_only:
                        continue
                    try:
                        new_trade_id = await self._spawn_excess_slice(
                            bot, sym, ib_q,
                            bot_q=bot_q,
                            ib_meta=ib_meta_by_sym.get(sym, {}),
                            ib_quote=ib_quotes.get(sym, {}) or {},
                            stop_pct=excess_stop_pct,
                            rr=excess_rr,
                            BotTrade=BotTrade,
                            TradeDirection=TradeDirection,
                            TradeStatus=TradeStatus,
                        )
                        drift_record["new_trade_id"] = new_trade_id
                        # Close out the zombie bot_trades (audit trail).
                        zombies_closed = []
                        for zt in zombies:
                            # v19.34.123 — compute realized PnL before
                            # marking the zombie closed. Pre-v123 zombies
                            # were marked closed with realized_pnl=0
                            # regardless of how much they'd actually
                            # moved. Best-effort exit via current_price.
                            from services.pnl_compute import apply_close_pnl
                            apply_close_pnl(
                                zt,
                                reason="zombie_cleanup_v19_34_19",
                                exit_price=getattr(zt, "current_price", None),
                            )
                            zt.status = TradeStatus.CLOSED
                            zt.notes = (zt.notes or "") + (
                                " [v19.34.19: zombie cleanup, IB qty reclaimed via "
                                f"new bracketed slice {new_trade_id}]"
                            )
                            zombies_closed.append(getattr(zt, "id", None))
                            save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
                            persisted = False
                            save_err = None
                            if save_fn:
                                try:
                                    res = save_fn(zt)
                                    if asyncio.iscoroutine(res):
                                        await res
                                    persisted = True
                                except Exception as _save_exc:
                                    save_err = f"{type(_save_exc).__name__}: {_save_exc}"
                                    logger.warning(
                                        "[v19.34.21 zombie-close] _save_trade FAILED "
                                        "for %s (%s): %s — falling back to direct "
                                        "Mongo update_one",
                                        getattr(zt, "id", "?"),
                                        getattr(zt, "symbol", "?"),
                                        save_err,
                                    )
                            # ── v19.34.21 (2026-05-06) — Mongo-direct fallback.
                            # Operator-discovered 2026-05-06: the original
                            # `try: save_fn(zt) except: pass` swallowed real
                            # errors (b4d27b31 stayed `status=open` in DB
                            # despite the heal reporting it as closed).
                            # Now if the orchestrated save raised, we write
                            # the close fields directly via update_one so
                            # the DB matches the heal report.
                            if not persisted:
                                try:
                                    db_handle = getattr(bot, "_db", None) or getattr(self, "db", None)
                                    if db_handle is not None and getattr(zt, "id", None):
                                        await asyncio.to_thread(
                                            db_handle["bot_trades"].update_one,
                                            {"id": zt.id},
                                            {"$set": {
                                                "status": "closed",
                                                "close_reason": "zombie_cleanup_v19_34_19",
                                                "closed_at": zt.closed_at,
                                                "remaining_shares": 0,
                                                "notes": zt.notes,
                                            }},
                                        )
                                        logger.warning(
                                            "[v19.34.21 zombie-close] Mongo-direct "
                                            "fallback persisted close for %s",
                                            zt.id,
                                        )
                                        persisted = True
                                except Exception as _direct_exc:
                                    logger.error(
                                        "[v19.34.21 zombie-close] Mongo-direct "
                                        "fallback ALSO failed for %s: %s — DB will "
                                        "stay out of sync, operator action needed",
                                        getattr(zt, "id", "?"),
                                        _direct_exc,
                                    )
                                    drift_record.setdefault("zombie_close_failures", []).append({
                                        "trade_id": getattr(zt, "id", None),
                                        "save_err": save_err,
                                        "direct_err": f"{type(_direct_exc).__name__}: {_direct_exc}",
                                    })
                            # Drop zombie from in-memory _open_trades.
                            _ot = getattr(bot, "_open_trades", None)
                            if _ot and getattr(zt, "id", None) in _ot:
                                _ot.pop(zt.id, None)
                        drift_record["zombies_closed"] = zombies_closed
                        report["drifts_resolved"].append(drift_record)
                        await self._persist_drift_event(drift_record)
                        # ── v19.34.20c (2026-05-06) — original v19.34.19
                        # called `self._emit_drift_event(...)` which was
                        # never defined on this class — every zombie heal
                        # raised AttributeError post-resolve and got logged
                        # to `report["errors"]` even though the actual
                        # cleanup + spawn succeeded. Replaced with the same
                        # `emit_stream_event` pattern used elsewhere in
                        # this file (e.g. `_close_drift_trades_zero`).
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "warning",
                                "event": "zombie_trade_drift_v19_34_19",
                                "symbol": sym,
                                "text": (
                                    f"🧟 {sym} zombie cleanup: closed "
                                    f"{len(zombies_closed)} zombie bot_trade(s) "
                                    f"({', '.join(zombies_closed)}) and spawned "
                                    f"bracketed slice {new_trade_id} for "
                                    f"{int(abs(ib_q))} sh at IB."
                                ),
                                "metadata": drift_record,
                            })
                        except Exception:
                            pass
                    except Exception as e:
                        drift_record["error"] = f"{type(e).__name__}: {e}"
                        report["errors"].append(drift_record)
                    continue

                # ── v19.34.50 (Feb 2026) — bot_q zero-side detection ──
                # OLD: when bot tracks the symbol but `bot_q` signed-sum
                # nets to ~0 (e.g., paired LONG + SHORT trades both with
                # non-zero remaining_shares cancel out, OR a single trade
                # with rs=0 that the v19.34.19 zombie branch missed because
                # `len(zombies) == 0` failed — zombies list filters
                # `int(abs(rs)) == 0` strictly), and IB still has shares,
                # the directional Case 1/2/3 branches all rely on bot_q
                # being strictly long or short. Result: drift fell through
                # to the `unclassified` else path at line 1505 and IB
                # shares stayed silently unmanaged — same blind-spot
                # category as v19.34.19 but at the bot_q==0 + zombies==0
                # edge.
                # NEW: route any (abs(bot_q)<0.01 + abs(ib_q)>=1) where
                # the zombie branch did not already fire to
                # `_spawn_excess_slice` so the bot adopts the IB inventory
                # under a bracketed reconciled-excess slice. We do NOT
                # touch the existing tracked bot_trades — they may be
                # legitimate paired hedges; the new slice only claims the
                # IB excess.
                if abs(bot_q) < 0.01 and abs(ib_q) >= 1:
                    drift_record = {
                        "symbol": sym,
                        "ib_qty": ib_q,
                        "bot_qty": bot_q,
                        "drift_shares": drift,
                        "kind": "zero_side_external_inventory",
                        "tracked_trade_count": len(bot_trades_by_sym.get(sym, [])),
                    }
                    report["drifts_detected"].append(drift_record)
                    if not auto_resolve:
                        continue
                    try:
                        new_trade_id = await self._spawn_excess_slice(
                            bot, sym, ib_q,
                            bot_q=bot_q,
                            ib_meta=ib_meta_by_sym.get(sym, {}),
                            ib_quote=ib_quotes.get(sym, {}) or {},
                            stop_pct=excess_stop_pct,
                            rr=excess_rr,
                            BotTrade=BotTrade,
                            TradeDirection=TradeDirection,
                            TradeStatus=TradeStatus,
                        )
                        drift_record["new_trade_id"] = new_trade_id
                        report["drifts_resolved"].append(drift_record)
                        await self._persist_drift_event(drift_record)
                        try:
                            from services.sentcom_service import emit_stream_event
                            await emit_stream_event({
                                "kind": "warning",
                                "event": "zero_side_drift_v19_34_50",
                                "symbol": sym,
                                "text": (
                                    f"⚖️ {sym} zero-side drift: bot tracked "
                                    f"{len(bot_trades_by_sym.get(sym, []))} trade(s) "
                                    f"netting bot_q={bot_q:+.0f}, IB has {ib_q:+.0f}sh. "
                                    f"Spawned bracketed slice {new_trade_id} for "
                                    f"{int(abs(ib_q))}sh."
                                ),
                                "metadata": drift_record,
                            })
                        except Exception:
                            pass
                    except Exception as e:
                        drift_record["error"] = f"{type(e).__name__}: {e}"
                        report["errors"].append(drift_record)
                    continue

                drift_record = {
                    "symbol": sym,
                    "ib_qty": ib_q,
                    "bot_qty": bot_q,
                    "drift_shares": drift,
                }

                try:
                    # ── Case 3: ZERO at IB, bot still tracking ──
                    if abs(ib_q) < 0.01:
                        # ── v19.34.52 (Feb 2026) — Multi-source confirmation ──
                        # Same family as v19.34.49 phantom-recovery bug,
                        # manifesting in the share-drift reconciler.
                        # Operator caught it 2026-05-08 9:30-9:39am: bot
                        # fired entries → fills lagged in pusher's
                        # `_pushed_ib_data["positions"]` → reconciler ran,
                        # saw `ib_q=0` for symbols bot was tracking →
                        # fell into Case 3 → auto-closed REAL POSITIONS as
                        # `external_close_v19_34_15b` → bot's
                        # `pending_trade_exists` gate lifted → bot fired
                        # again → repeat. Damage: GOOG 116L, COIN 626L,
                        # AAPL 1L all phantom-closed locally while alive
                        # at IB. MA/EWY/RKT loop produced -$1,461 realized.
                        #
                        # Fix: cross-check pusher (which yielded ib_q=0)
                        # against direct IB clientId=11 BEFORE closing.
                        # Both must agree (or direct alone if pusher
                        # offline) before we mutate bot state.
                        auth_qty, auth_conf, auth_reason = (
                            await self._ib_qty_authoritative(sym)
                        )
                        if auth_conf == "unreliable" or (
                            auth_qty is not None and abs(auth_qty) >= 0.5
                        ):
                            # Either sources disagree OR direct disagrees
                            # with pusher's zero. Skip this drift cycle.
                            drift_record["kind"] = (
                                "skipped_unconfirmed_zero_v19_34_52"
                            )
                            drift_record["skip_reason"] = auth_reason
                            drift_record["pusher_qty"] = ib_q
                            drift_record["direct_qty"] = auth_qty
                            report["skipped"].append(drift_record)
                            self._record_guard_skip(drift_record)
                            logger.warning(
                                f"[v19.34.52 DRIFT-GUARD] {sym} zero-close "
                                f"BLOCKED: pusher=0 direct={auth_qty} "
                                f"conf={auth_conf} reason={auth_reason}. "
                                f"Will retry next cycle."
                            )
                            continue
                        drift_record["kind"] = "zero_external_close"
                        drift_record["confirmed_by"] = auth_conf
                        # ── v19.34.71 — Two-tick confirmation gate ─────
                        # v19.34.52's pusher+direct cross-check still
                        # catches fill-propagation races where BOTH
                        # sources momentarily read zero. NBIS phantom
                        # -$326 realized on 2026-05-11 came from exactly
                        # that pattern. Require this same (symbol,
                        # trade-id set) to be observed TWO consecutive
                        # scans before recording the accounting event.
                        _bot_trade_ids = {
                            getattr(t, "id", None) for t in bot_trades_by_sym[sym]
                        }
                        _confirmed, _conf_reason = (
                            self._confirm_external_close_two_tick(
                                symbol=sym,
                                bot_trade_ids=_bot_trade_ids,
                                drift_kind="zero",
                            )
                        )
                        if not _confirmed:
                            drift_record["kind"] = (
                                "pending_external_close_v19_34_71"
                            )
                            drift_record["pending_reason"] = _conf_reason
                            drift_record["bot_trade_ids"] = list(_bot_trade_ids)
                            report["skipped"].append(drift_record)
                            self._record_guard_skip(drift_record)
                            logger.warning(
                                f"[v19.34.71 TWO-TICK] {sym} zero-close "
                                f"PENDING ({_conf_reason}) — waiting for "
                                f"next scan to confirm before recording "
                                f"external_close."
                            )
                            continue
                        drift_record["two_tick_confirmation"] = _conf_reason
                        report["drifts_detected"].append(drift_record)
                        if not auto_resolve:
                            continue
                        await self._close_drift_trades_zero(
                            bot, sym, bot_trades_by_sym[sym]
                        )
                        report["drifts_resolved"].append(drift_record)

                    # ── Case 2: PARTIAL — IB has fewer shares than bot tracks ──
                    elif (ib_q > 0 and bot_q > 0 and ib_q < bot_q) or \
                         (ib_q < 0 and bot_q < 0 and abs(ib_q) < abs(bot_q)):
                        # ── v19.34.52 — same multi-source guard as Case 3 ──
                        # Pusher's `ib_q` partial could be mid-fill lag;
                        # if direct shows the bot's full count, this is
                        # NOT a real partial — refuse to shrink.
                        auth_qty, auth_conf, auth_reason = (
                            await self._ib_qty_authoritative(sym)
                        )
                        if auth_conf == "unreliable" or (
                            auth_qty is not None
                            and abs(auth_qty - bot_q) < 0.5
                        ):
                            drift_record["kind"] = (
                                "skipped_unconfirmed_partial_v19_34_52"
                            )
                            drift_record["skip_reason"] = auth_reason
                            drift_record["pusher_qty"] = ib_q
                            drift_record["direct_qty"] = auth_qty
                            report["skipped"].append(drift_record)
                            self._record_guard_skip(drift_record)
                            logger.warning(
                                f"[v19.34.52 DRIFT-GUARD] {sym} partial-shrink "
                                f"BLOCKED: pusher={ib_q} direct={auth_qty} "
                                f"bot={bot_q} conf={auth_conf} "
                                f"reason={auth_reason}."
                            )
                            continue
                        drift_record["kind"] = "partial_external_close"
                        drift_record["confirmed_by"] = auth_conf
                        # ── v19.34.71 — Two-tick confirmation gate ─────
                        # Same race fingerprint applies to partial shrinks:
                        # pusher and direct can briefly agree on a smaller
                        # qty if a fill notification is in flight. Require
                        # two consecutive scans before shrinking the
                        # tracked size and locking in any partial-close
                        # realized P&L.
                        _bot_trade_ids = {
                            getattr(t, "id", None) for t in bot_trades_by_sym[sym]
                        }
                        _confirmed, _conf_reason = (
                            self._confirm_external_close_two_tick(
                                symbol=sym,
                                bot_trade_ids=_bot_trade_ids,
                                drift_kind="partial",
                            )
                        )
                        if not _confirmed:
                            drift_record["kind"] = (
                                "pending_partial_close_v19_34_71"
                            )
                            drift_record["pending_reason"] = _conf_reason
                            drift_record["bot_trade_ids"] = list(_bot_trade_ids)
                            report["skipped"].append(drift_record)
                            self._record_guard_skip(drift_record)
                            logger.warning(
                                f"[v19.34.71 TWO-TICK] {sym} partial-shrink "
                                f"PENDING ({_conf_reason}) — waiting for "
                                f"next scan to confirm before shrinking."
                            )
                            continue
                        drift_record["two_tick_confirmation"] = _conf_reason
                        report["drifts_detected"].append(drift_record)
                        if not auto_resolve:
                            continue
                        # Use authoritative qty for the shrink target,
                        # not pusher's potentially-lagged value.
                        target_total_abs = int(abs(auth_qty if auth_qty is not None else ib_q))
                        await self._shrink_drift_trades(
                            bot, sym, bot_trades_by_sym[sym],
                            new_total_abs=target_total_abs,
                            drift_record=drift_record,
                        )
                        report["drifts_resolved"].append(drift_record)

                    # ── Case 1: EXCESS — IB has MORE than bot tracks ──
                    elif (ib_q > 0 and bot_q > 0 and ib_q > bot_q) or \
                         (ib_q < 0 and bot_q < 0 and abs(ib_q) > abs(bot_q)) or \
                         (ib_q * bot_q < 0):  # direction flipped — treat as excess
                        excess_qty = drift  # signed
                        drift_record["kind"] = "excess_unbracketed"
                        drift_record["excess_qty"] = excess_qty
                        report["drifts_detected"].append(drift_record)
                        if not auto_resolve:
                            continue
                        new_trade_id = await self._spawn_excess_slice(
                            bot, sym, ib_q,
                            bot_q=bot_q,
                            ib_meta=ib_meta_by_sym.get(sym, {}),
                            ib_quote=ib_quotes.get(sym, {}) or {},
                            stop_pct=excess_stop_pct,
                            rr=excess_rr,
                            BotTrade=BotTrade,
                            TradeDirection=TradeDirection,
                            TradeStatus=TradeStatus,
                        )
                        drift_record["new_trade_id"] = new_trade_id
                        report["drifts_resolved"].append(drift_record)

                    else:
                        # Shouldn't reach here, but be defensive.
                        drift_record["kind"] = "unclassified"
                        report["skipped"].append(drift_record)
                except Exception as inner_err:
                    logger.exception(
                        f"reconcile_share_drift({sym}) failed: {inner_err}"
                    )
                    report["errors"].append({
                        "symbol": sym, "error": str(inner_err),
                        "drift_record": drift_record,
                    })

            # Persist forensic event (TTL 7d via lazy index).
            try:
                if report["drifts_detected"]:
                    await self._persist_drift_event(report)
            except Exception:
                pass

            return report

        except Exception as e:
            logger.exception(f"reconcile_share_drift error: {e}")
            report["success"] = False
            report["error"] = str(e)
            return report

    async def _ib_qty_authoritative(self, sym: str):
        """v19.34.52 — Cross-check pusher's view of `sym` against direct
        IB (clientId=11) before mutating bot state on drift.

        Returns: tuple `(qty: Optional[float], confidence: str, reason: str)`

        Confidence levels:
          - "high":         pusher and direct agree within 0.5 shares.
                            qty is the agreed signed value.
          - "unreliable":   sources disagree, OR direct unavailable, OR
                            direct returned empty positions list (which
                            usually means the snapshot is mid-update).
                            qty may be partial (pusher's view) — caller
                            must NOT trust it for close/shrink.

        The bug v19.34.52 fixes: pusher's `_pushed_ib_data["positions"]`
        can lag entry fills by 1-3 seconds. During that window the
        reconciler used to see `ib_q=0` for a symbol bot just opened,
        and fell into Case 3 (zero_external_close) → marked the live
        position closed locally → bot's pending_trade_exists released →
        bot fired again. Result on 2026-05-08 open: GOOG/COIN/AAPL
        phantom-closed; MA/EWY/RKT loop racked up -$1,461 realized.
        """
        # Pusher (already in our pre-built ib_qty_by_sym map at caller).
        # Re-read to be defensive — the dict is rebuilt per reconcile pass
        # but a sub-second helper call could race.
        try:
            from routers.ib import _pushed_ib_data, is_pusher_connected
        except Exception:
            return (None, "unreliable", "pusher_module_import_failed")

        sym_u = (sym or "").upper()
        pusher_q = None
        pusher_alive = False
        try:
            pusher_alive = bool(is_pusher_connected())
        except Exception:
            pass
        if pusher_alive:
            ps = 0.0
            saw_row = False
            for p in (_pushed_ib_data.get("positions") or []):
                if (p.get("symbol") or "").upper() == sym_u:
                    saw_row = True
                    try:
                        ps += float(p.get("position") or 0)
                    except Exception:
                        pass
            # If pusher has NO row for the symbol, treat as 0 (pusher
            # only emits non-zero rows on most setups, but flat rows can
            # appear too — saw_row is informational).
            pusher_q = ps if saw_row or _pushed_ib_data.get("positions") is not None else None

        # Direct IB.
        try:
            from services.ib_direct_service import get_ib_direct_service
        except Exception:
            return (pusher_q, "unreliable", "ib_direct_module_unavailable")
        try:
            svc = get_ib_direct_service()
        except Exception:
            return (pusher_q, "unreliable", "ib_direct_service_init_failed")
        if not (svc and svc.is_available() and svc.is_connected()):
            return (
                pusher_q,
                "unreliable",
                "ib_direct_disconnected",
            )
        try:
            positions = await svc.get_positions()
        except Exception as e:
            return (
                pusher_q,
                "unreliable",
                f"ib_direct_get_positions_failed:{type(e).__name__}",
            )
        if not positions:
            # Empty list often means "mid-update", not "truly flat".
            # Refuse to confirm zero on this basis alone — wait for next
            # reconcile cycle.
            return (
                pusher_q,
                "unreliable",
                "ib_direct_returned_empty_positions",
            )

        direct_q = 0.0
        for p in positions:
            if (p.get("symbol") or "").upper() == sym_u:
                try:
                    direct_q += float(p.get("position") or 0)
                except Exception:
                    pass

        # Both available — agreement check (0.5 share tolerance for
        # rounding edge cases on fractional shares).
        if pusher_q is None:
            # Pusher not contributing — fall back to direct alone but
            # mark it as such. Direct is authoritative for this account.
            return (direct_q, "high", "direct_only_pusher_offline")
        if abs(pusher_q - direct_q) <= 0.5:
            return (direct_q, "high", "pusher_direct_agree")
        # Disagree — refuse to act. Pusher likely lagging fills.
        return (
            direct_q,
            "unreliable",
            f"pusher_direct_disagree:pusher={pusher_q}_direct={direct_q}",
        )

    async def _close_drift_trades_zero(self, bot, sym, trades) -> None:
        """Case 3: IB has 0; close every bot_trade for this symbol.

        v19.34.52 NOTE: only invoked AFTER `_ib_qty_authoritative` has
        confirmed `(qty=0, confidence='high')`. The bare check on
        pusher's `ib_q < 0.01` was the source of the 2026-05-08
        phantom-close incident.

        v19.34.71 NOTE: only invoked AFTER `_confirm_external_close_two_tick`
        has confirmed the same (symbol, trade-set) across two consecutive
        scans. Single-tick races no longer reach this method.

        v19.34.72 NOTE: by the time we reach this branch the close is
        EXTERNAL by construction — if the bot had initiated it, the
        trade would already be out of `_open_trades`. We tag each trade
        with `close_reason="operator_external_flatten"` and add the
        symbol to the session-scoped suppression set so the bot does
        NOT re-enter on the same name moments after the operator's
        risk-off action. Operator can clear via the safety API if a
        bracket-leg fill was misclassified.
        """
        from services.trading_bot_service import TradeStatus
        from services.operator_flatten_suppression import (
            get_operator_flatten_suppression,
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        trade_ids: List[str] = []
        for t in trades:
            try:
                # v19.34.123 — Compute realized PnL using current_price
                # as best-effort exit (operator closed at TWS; we don't
                # know the actual fill price without an IB execution
                # lookup. Future enhancement: query ib_direct executions
                # by symbol+timestamp to upgrade `exit_price_source`
                # from `current_price` to `ib_execution`).
                from services.pnl_compute import apply_close_pnl
                apply_close_pnl(
                    t,
                    reason="operator_external_flatten",
                    exit_price=getattr(t, "current_price", None),
                    now_iso=now_iso,
                )
                t.status = TradeStatus.CLOSED
                t.notes = (t.notes or "") + (
                    " [v19.34.72: IB qty=0 confirmed across two ticks; "
                    "bot did not initiate close → tagged as operator/external "
                    "flatten. Symbol added to re-entry suppression set for "
                    "remainder of UTC day.]"
                )
                trade_ids.append(getattr(t, "id", "") or "")
                # Persist via bot._save_trade if available (mirror existing pattern).
                save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
                if save_fn:
                    try:
                        result = save_fn(t)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        pass
                # Drop from in-memory tracking.
                if hasattr(bot, "_open_trades") and t.id in bot._open_trades:
                    del bot._open_trades[t.id]
            except Exception as ex:
                logger.warning(f"[v19.34.72] close-drift {sym} failed: {ex}")

        # Add to operator-flatten suppression set.
        try:
            get_operator_flatten_suppression().add(
                symbol=sym,
                reason="operator_external_flatten",
                trade_ids=trade_ids,
            )
        except Exception as e:
            logger.warning(
                f"[v19.34.72] failed to add {sym} to operator-flatten "
                f"suppression set: {e}"
            )

        # Stream emit so operator sees it.
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "warning",
                "event": "operator_external_flatten_v19_34_72",
                "symbol": sym,
                "text": (
                    f"⚠ {sym} flat at IB but bot was tracking "
                    f"{len(trades)} trade(s). Confirmed across two ticks → "
                    f"tagged as operator/external flatten. Re-entries on "
                    f"{sym} suppressed until UTC midnight or operator clears."
                ),
                "metadata": {
                    "closed_count": len(trades),
                    "trade_ids": trade_ids,
                    "suppression_active": True,
                },
            })
        except Exception:
            pass
        logger.warning(
            f"[v19.34.72 DRIFT] {sym} ZERO at IB (confirmed 2-tick) — "
            f"closed {len(trades)} bot_trade(s) as operator_external_flatten, "
            f"added to suppression set."
        )

    async def _shrink_drift_trades(
        self, bot, sym, trades, new_total_abs: int, drift_record: Dict[str, Any]
    ) -> None:
        """Case 2: LIFO shrink — peel shares off the most recent trade
        first until total matches IB. Operator-approved 2026-05-06:
        when a bracket parent leg fires at IB and the bot writes off
        the trade, the WORKING children that DID end up filling are
        always the most-recent slices. LIFO returns capital to the
        latest entry first, which mirrors how IB's own partial-close
        accounting collapses positions.
        """
        # Sort by entry_time / executed_at descending (newest first).
        def _sort_key(t):
            for attr in ("entry_time", "executed_at", "created_at"):
                v = getattr(t, attr, None)
                if v:
                    return str(v)
            return ""
        trades_lifo = sorted(trades, key=_sort_key, reverse=True)

        cur_total = sum(int(abs(getattr(t, "remaining_shares", 0) or 0)) for t in trades_lifo)
        if cur_total <= 0:
            return
        # How many shares to remove total (positive int).
        to_remove = max(0, cur_total - new_total_abs)
        applied: list = []
        # ── v19.34.20b (2026-05-06) — track fully-peeled trades so we can
        # mark them CLOSED post-loop. Pre-fix this loop set
        # `remaining_shares = 0` on full peels but never flipped `status`
        # to CLOSED, never popped from `_open_trades`, never stamped
        # `closed_at`. That manufactured zombie BotTrades (rs=0,
        # status=OPEN) which the v19.34.19 detector now catches. This is
        # the upstream prevention so the Case-2 auto-resolve path doesn't
        # generate fresh zombies on every run. See
        # /app/memory/forensics/zombie_root_cause_v19_34_19.md.
        from services.trading_bot_service import TradeStatus as _TS_close
        now_iso_close = datetime.now(timezone.utc).isoformat()
        fully_peeled: list = []
        for t in trades_lifo:
            old = int(abs(getattr(t, "remaining_shares", 0) or 0))
            if to_remove <= 0:
                applied.append({"trade_id": getattr(t, "id", None), "old": old, "new": old})
                continue
            take = min(old, to_remove)
            new = old - take
            t.remaining_shares = new
            t.notes = (t.notes or "") + f" [v19.34.15b: shrunk {old}→{new} (LIFO)]"
            to_remove -= take
            applied.append({"trade_id": getattr(t, "id", None), "old": old, "new": new})
            # v19.34.20b — close fully-peeled slices to prevent zombie creation.
            if new == 0 and old > 0:
                try:
                    # v19.34.123 — Compute realized PnL on the fully-peeled
                    # slice using current_price as best-effort exit. Pre-v123
                    # `unrealized_pnl=0` was the only write, leaving the
                    # actual realized loss/gain at $0 in bot_trades.
                    from services.pnl_compute import apply_close_pnl
                    # The slice had `old` shares that just peeled to zero —
                    # but t.shares (the original sizing) may differ; pass
                    # `old` as the close size via the override mechanism.
                    t._close_shares_override = old
                    apply_close_pnl(
                        t,
                        reason="shrunk_to_zero_v19_34_20b",
                        exit_price=getattr(t, "current_price", None),
                        now_iso=now_iso_close,
                    )
                    t.status = _TS_close.CLOSED
                    fully_peeled.append(t)
                except Exception as _close_err:
                    logger.warning(
                        f"[v19.34.20b] failed to mark {getattr(t, 'id', '?')} "
                        f"CLOSED on full peel: {_close_err}"
                    )
        drift_record["shrink_detail"] = applied
        drift_record["shrink_strategy"] = "lifo"
        if fully_peeled:
            drift_record["fully_peeled_closed"] = [
                getattr(t, "id", None) for t in fully_peeled
            ]
        # v19.34.20b — drop fully-peeled trades from in-memory tracking
        # and release stop-manager state. Mirror close_phantom_position
        # / close_trade invariants.
        for t in fully_peeled:
            try:
                if hasattr(bot, "_open_trades") and t.id in bot._open_trades:
                    bot._open_trades.pop(t.id, None)
                if hasattr(bot, "_closed_trades"):
                    try:
                        bot._closed_trades.append(t)
                    except Exception:
                        pass
                sm = getattr(bot, "_stop_manager", None)
                if sm and hasattr(sm, "forget_trade"):
                    sm.forget_trade(t.id)
            except Exception as _release_err:
                logger.warning(
                    f"[v19.34.20b] post-close cleanup failed for "
                    f"{getattr(t, 'id', '?')}: {_release_err}"
                )
        # Persist via bot._save_trade.
        save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
        if save_fn:
            for t in trades_lifo:
                try:
                    result = save_fn(t)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "warning",
                "event": "external_partial_close_v19_34_15b",
                "symbol": sym,
                "text": (f"⚠ {sym} partial external close detected — "
                         f"shrunk bot tracking from {cur_total} → {new_total_abs} sh"),
                "metadata": drift_record,
            })
        except Exception:
            pass
        logger.warning(
            f"[v19.34.15b DRIFT] {sym} PARTIAL external close — "
            f"shrunk {cur_total}→{new_total_abs} sh across {len(trades)} bot_trade(s)"
        )

    # ─── v19.34.42 — Idempotent excess-slice helpers ─────────────────
    def _find_existing_excess_slice(self, bot, sym: str, direction):
        """Return the existing `reconciled_excess_*` BotTrade for this
        (symbol, direction) if one is open, else None.

        Used by `_spawn_excess_slice` to grow rather than fragment.

        ── v19.34.60 (2026-02-09) — Zombie exclusion ──
        Operator-discovered after v19.34.59 zombie sweep: 5 of 7 zombie
        heals returned `new_trade_id == one_of(zombies_closed)`. Cause:
        a previously-reconciled trade had `setup_type='reconciled_excess_slice'`
        but later got drained to `remaining_shares=0` (zombified) without
        flipping status. This function then matched the zombie as a
        "grow candidate"; `_grow_existing_excess_slice` mutated it
        (rs=0→626); but immediately after, the zombie cleanup loop in
        `reconcile_share_drift` closed every zombie — including the
        just-grown slice. Net effect: the zombie persisted, the heal
        no-opped. Excluding zombies here forces `_spawn_excess_slice`
        to create a FRESH BotTrade with a new id, which then survives
        the zombie close loop intact.
        """
        d_val = getattr(direction, "value", str(direction)).lower()
        candidates = []
        for t in list(getattr(bot, "_open_trades", {}).values()):
            if (getattr(t, "symbol", "") or "").upper() != sym.upper():
                continue
            t_dir = getattr(t.direction, "value", str(t.direction)).lower()
            if t_dir != d_val:
                continue
            entered = (getattr(t, "entered_by", "") or "")
            setup = (getattr(t, "setup_type", "") or "")
            if entered.startswith("reconciled_excess") or setup == "reconciled_excess_slice":
                # v19.34.60 — skip zombies. A trade with rs=0 cannot
                # legitimately be "grown" (it has nothing to grow from)
                # AND it's about to be closed by the zombie cleanup
                # branch. Treating it as a grow target is a guaranteed
                # data race.
                rs = int(abs(getattr(t, "remaining_shares", 0) or 0))
                if rs == 0:
                    continue
                candidates.append(t)
        if not candidates:
            return None
        # Prefer the oldest reconciled slice (becomes the de-facto canonical).
        def _ts_key(t):
            for attr in ("entry_time", "executed_at", "created_at"):
                v = getattr(t, attr, None)
                if v:
                    return str(v)
            return ""
        return sorted(candidates, key=_ts_key)[0]

    async def _grow_existing_excess_slice(
        self, bot, trade, sym: str, *, ib_qty_signed, bot_q, ib_meta, ib_quote,
    ) -> str:
        """Grow an existing reconciled-excess slice's share count to match
        IB total, cancel its old bracket, place ONE new OCA bracket sized
        to the new total. Idempotent — safe to call repeatedly per tick.
        """
        excess_signed = ib_qty_signed - bot_q
        excess_abs = int(abs(excess_signed))
        old_shares = int(abs(getattr(trade, "remaining_shares", 0) or 0))
        new_shares = old_shares + excess_abs
        # Mutate in-memory.
        trade.remaining_shares = new_shares
        try:
            trade.shares = new_shares
        except Exception:
            pass
        try:
            trade.original_shares = max(int(getattr(trade, "original_shares", 0) or 0), new_shares)
        except Exception:
            pass
        # Update risk_amount to reflect new size.
        try:
            stop_dist = abs(float(getattr(trade, "fill_price", 0) or trade.entry_price)
                            - float(getattr(trade, "stop_price", 0) or 0))
            if stop_dist > 0:
                trade.risk_amount = stop_dist * new_shares
        except Exception:
            pass
        trade.notes = (getattr(trade, "notes", "") or "") + (
            f" [v19.34.42 grew excess slice {old_shares}→{new_shares} sh "
            f"(ib_qty {ib_qty_signed:+.0f}, bot_q {bot_q:+.0f})]"
        )
        # Cancel old bracket and re-issue one sized to the new total.
        executor = getattr(bot, "_trade_executor", None)
        if executor and hasattr(executor, "_cancel_ib_bracket_orders"):
            try:
                await executor._cancel_ib_bracket_orders(trade)
            except Exception as e:
                logger.warning(f"[v19.34.42 grow] {sym} cancel old bracket failed: {e}")

        # ── v19.34.79 — Sibling-bracket cancel sweep ──────────────────
        # Pre-fix the grow path only cancelled the canonical slice's
        # bracket. Any OTHER BotTrade objects for the same symbol (which
        # arise when the bot scales into a position across multiple
        # evals, or when the reconciler spawns additional excess slices)
        # kept their OWN brackets alive at IB. TWS forensic 2026-05-12:
        # ADBE 80sh long carried 320sh of pending stops, EFA 963sh long
        # carried 2,888sh, GM 109sh long carried 1,282sh — exact
        # fingerprint of overlapping brackets from sibling BotTrades.
        # On a single stop trigger, the surviving siblings would have
        # flipped the position massively short on the next tick.
        #
        # Now: after the canonical slice's bracket is replaced, sweep
        # sibling BotTrades for the same (symbol, direction) and cancel
        # their brackets too. The canonical slice's NEW bracket already
        # covers the cumulative position size, so the siblings'
        # brackets are redundant by construction.
        try:
            for sibling in list(getattr(bot, "_open_trades", {}).values()):
                if sibling is trade:
                    continue
                if (getattr(sibling, "symbol", "") or "").upper() != sym.upper():
                    continue
                sib_dir = (
                    sibling.direction.value if hasattr(sibling.direction, "value")
                    else str(getattr(sibling, "direction", ""))
                ).lower()
                trade_dir = (
                    trade.direction.value if hasattr(trade.direction, "value")
                    else str(getattr(trade, "direction", ""))
                ).lower()
                if sib_dir != trade_dir:
                    continue  # opposing-side sibling — different exposure, leave it
                if executor and hasattr(executor, "_cancel_ib_bracket_orders"):
                    try:
                        await executor._cancel_ib_bracket_orders(sibling)
                        logger.warning(
                            "[v19.34.79 SIBLING-CANCEL] %s sibling trade "
                            "%s brackets cancelled (canonical slice %s "
                            "now covers cumulative %d sh).",
                            sym, sibling.id, trade.id, new_shares,
                        )
                    except Exception as e:
                        logger.warning(
                            "[v19.34.79] %s sibling %s cancel failed: %s",
                            sym, sibling.id, e,
                        )
                # Clear the sibling's stop/target ids so they don't
                # accidentally get re-used or appear "bracketed" in the
                # v19.34.77 audit while the cancels propagate.
                sibling.stop_order_id = None
                try:
                    sibling.target_order_id = None
                except Exception:
                    pass
                try:
                    sibling.target_order_ids = []
                except Exception:
                    pass
                # Mark the sibling as merged so the manage-loop doesn't
                # try to manage stops/targets it no longer owns.
                sibling.notes = (getattr(sibling, "notes", "") or "") + (
                    f" [v19.34.79: brackets merged into canonical slice "
                    f"{trade.id} (cumulative {new_shares}sh).]"
                )
        except Exception as e:
            logger.warning(
                "[v19.34.79] %s sibling-bracket sweep raised: %s",
                sym, e,
            )

        trade.stop_order_id = None
        trade.target_order_id = None
        try:
            trade.target_order_ids = []
        except Exception:
            pass
        trade.oca_group = None

        if executor and hasattr(executor, "attach_oca_stop_target"):
            # v19.34.111 — cooldown guard (see PositionReconciler init).
            _cooldown_left = self._bracket_attach_in_cooldown(trade.id)
            if _cooldown_left is not None:
                self._record_bracket_attach_skip(trade.id, _cooldown_left, symbol=sym)
                logger.info(
                    f"[v19.34.111 COOLDOWN] {sym} {trade.id} skip grow-attach "
                    f"— {_cooldown_left:.1f}s left in cooldown."
                )
            else:
                self._stamp_bracket_attach(trade.id)
                try:
                    oca_result = await executor.attach_oca_stop_target(trade)
                    if oca_result and oca_result.get("success"):
                        trade.stop_order_id = oca_result.get("stop_order_id")
                        tgt_id = oca_result.get("target_order_id")
                        if tgt_id:
                            trade.target_order_id = tgt_id
                        trade.oca_group = oca_result.get("oca_group")
                    else:
                        logger.error(
                            f"[v19.34.42 grow NAKED] {sym} {trade.id} grew to {new_shares} "
                            f"sh but OCA reissue failed: {(oca_result or {}).get('error', 'unknown')}"
                        )
                except Exception as e:
                    logger.error(f"[v19.34.42 grow NAKED] {sym} OCA reissue raised: {e}")
        # Persist.
        save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
        if save_fn:
            try:
                res = save_fn(trade)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning(f"[v19.34.42 grow] {sym} persist failed: {e}")
        # Stream emit.
        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "warning",
                "event": "reconciled_excess_grown_v19_34_42",
                "symbol": sym,
                "text": (
                    f"🔁 {sym} drift: grew existing reconciled slice "
                    f"{old_shares}→{new_shares} sh (added {excess_abs}). "
                    "No new fragment created."
                ),
                "metadata": {
                    "trade_id": trade.id, "old_shares": old_shares,
                    "new_shares": new_shares, "added": excess_abs,
                    "ib_qty": ib_qty_signed, "bot_qty": bot_q,
                },
            })
        except Exception:
            pass
        logger.warning(
            f"[v19.34.42 GROW] {sym} reconciled-excess slice {trade.id}: "
            f"{old_shares}→{new_shares} sh"
        )
        return trade.id

    async def _spawn_excess_slice(
        self, bot, sym, ib_qty_signed, *, bot_q, ib_meta, ib_quote,
        stop_pct, rr, BotTrade, TradeDirection, TradeStatus,
    ) -> str:
        """Case 1: claim the excess (IB - bot) shares.

        v19.34.42 (2026-05-08): made idempotent. BMNR/LIN/DDOG bug —
        each tick spawned a NEW `reconciled_excess_v19_34_15b` slice
        instead of growing the existing one, fragmenting one IB
        position into N bot_trades, each with its own colliding OCA
        bracket. Now: if a same-direction `reconciled_excess_*` slice
        already exists for this symbol, GROW it (and re-issue ONE OCA
        bracket sized to the new total) rather than creating a new
        BotTrade. New slice creation only happens when there is NO
        existing reconciled-excess trade for this (symbol, direction).
        """
        excess_signed = ib_qty_signed - bot_q
        excess_abs = int(abs(excess_signed))
        direction = TradeDirection.LONG if excess_signed > 0 else TradeDirection.SHORT

        # ── v19.34.42 idempotency: find existing reconciled-excess slice
        # for this (symbol, direction). If present, grow it instead.
        existing = self._find_existing_excess_slice(bot, sym, direction)
        if existing is not None:
            return await self._grow_existing_excess_slice(
                bot, existing, sym, ib_qty_signed=ib_qty_signed,
                bot_q=bot_q, ib_meta=ib_meta, ib_quote=ib_quote,
            )

        avg_cost = float(ib_meta.get("avg_cost") or ib_meta.get("market_price") or 0)
        current_price = float(
            ib_quote.get("last") or ib_quote.get("close")
            or ib_meta.get("market_price") or avg_cost
        )
        # If we can't anchor on a real price, refuse — never write a
        # synthetic stop based on garbage.
        if avg_cost <= 0 or current_price <= 0:
            raise ValueError(f"{sym}: missing avg_cost/current_price for excess slice")

        # Anchor stop on CURRENT_PRICE not avg_cost (we don't know
        # the excess slice's actual entry — current_price is the
        # safest "what we know now" baseline).
        stop_distance = current_price * (stop_pct / 100.0)
        target_distance = stop_distance * rr
        if direction == TradeDirection.LONG:
            stop_price = current_price - stop_distance
            target_1 = current_price + target_distance
        else:
            stop_price = current_price + stop_distance
            target_1 = current_price - target_distance

        trade_id = str(uuid.uuid4())[:8]
        trade = BotTrade(
            id=trade_id,
            symbol=sym,
            direction=direction,
            status=TradeStatus.OPEN,
            setup_type="reconciled_excess_slice",
            timeframe="intraday",
            quality_score=50,
            quality_grade="R",
            entry_price=current_price,
            current_price=current_price,
            stop_price=stop_price,
            target_prices=[target_1],
            shares=excess_abs,
            risk_amount=stop_distance * excess_abs,
            potential_reward=target_distance * excess_abs,
            risk_reward_ratio=rr,
            trade_style="reconciled",
            smb_grade="R",
            # v19.34.17 (2026-05-06) — operator-approved: drift-excess slices
            # also EOD-close. These are unknown-origin shares (the v19.34.15a
            # `[REJECTED: Bracket unknown]` race fingerprint) and should not
            # carry overnight risk for the same reason orphan reconciles don't.
            close_at_eod=True,
        )
        trade.fill_price = current_price
        trade.remaining_shares = excess_abs
        trade.original_shares = excess_abs
        trade.entry_time = datetime.now(timezone.utc)
        trade.executed_at = datetime.now(timezone.utc).isoformat()
        trade.created_at = datetime.now(timezone.utc).isoformat()
        trade.entered_by = "reconciled_excess_v19_34_15b"
        trade.synthetic_source = "share_drift_excess"
        trade.notes = (
            f"v19.34.15b: spawned to claim excess of {excess_abs} sh "
            f"(IB had {ib_qty_signed:+.0f}, bot tracked {bot_q:+.0f}). "
            f"Stop {stop_pct:.1f}% from current_price."
        )

        # Insert into _open_trades + persist.
        bot._open_trades[trade.id] = trade
        save_fn = getattr(bot, "_save_trade", None) or getattr(bot, "_persist_trade", None)
        if save_fn:
            try:
                result = save_fn(trade)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as ex:
                logger.warning(f"[v19.34.15b] excess persist failed for {sym}: {ex}")

        try:
            from services.sentcom_service import emit_stream_event
            await emit_stream_event({
                "kind": "warning",
                "event": "reconciled_excess_v19_34_15b",
                "symbol": sym,
                "text": (
                    f"🔁 {sym} share drift detected: IB had {ib_qty_signed:+.0f}, "
                    f"bot tracked {bot_q:+.0f}. Spawned excess slice for "
                    f"{excess_abs} sh @ ${current_price:.2f} · SL ${stop_price:.2f} · "
                    f"PT ${target_1:.2f}"
                ),
                "metadata": {
                    "trade_id": trade.id, "excess_shares": excess_abs,
                    "ib_qty": ib_qty_signed, "bot_qty": bot_q,
                    "stop_price": stop_price, "target_1": target_1,
                },
            })
        except Exception:
            pass

        logger.warning(
            f"[v19.34.15b DRIFT] {sym} EXCESS — spawned slice trade "
            f"{trade.id} for {excess_abs}sh @ ${current_price:.2f} "
            f"(SL ${stop_price:.2f}, PT ${target_1:.2f})"
        )

        # ── v19.34.27 — Attach OCA-linked stop+target on adoption ──
        # v19.34.28 upgrade: use `attach_oca_stop_target` instead of
        # just `place_stop_order`. Pre-v19.34.28 the adopted slice got
        # a stop but NO target — so the only way it could exit was via
        # the manage loop's mid-bar stop check or an EOD close. If the
        # bot crashed between adoption and next scan, the position was
        # unilaterally long/short on a stop-only ticket, and any
        # upside never got taken. Now both legs ship together under a
        # single OCA group so whichever fills first auto-cancels the
        # other AT THE BROKER (survives bot crashes).
        #
        # Best-effort: failures are LOUD-LOGGED (not raised) so the
        # slice still gets adopted into _open_trades for the manage
        # loop to track, but the operator sees the missing protection
        # in the trade-drops feed and can fix it manually before the
        # bot crashes and loses its in-memory references.
        try:
            executor = getattr(bot, "_trade_executor", None)
            if executor and hasattr(executor, "attach_oca_stop_target"):
                # v19.34.111 — cooldown guard (see PositionReconciler init).
                _cooldown_left = self._bracket_attach_in_cooldown(trade.id)
                if _cooldown_left is not None:
                    self._record_bracket_attach_skip(trade.id, _cooldown_left, symbol=sym)
                    logger.info(
                        f"[v19.34.111 COOLDOWN] {sym} {trade.id} skip "
                        f"spawn-attach — {_cooldown_left:.1f}s left in cooldown."
                    )
                    oca_result = None
                else:
                    self._stamp_bracket_attach(trade.id)
                    oca_result = await executor.attach_oca_stop_target(trade)
                if oca_result and oca_result.get("success"):
                    trade.stop_order_id = oca_result.get("stop_order_id")
                    # Target ID lives alongside stop. Stamped on trade
                    # so future close_trade paths can cancel BOTH legs
                    # via _cancel_ib_bracket_orders.
                    tgt_id = oca_result.get("target_order_id")
                    if tgt_id:
                        trade.target_order_id = tgt_id
                    trade.oca_group = oca_result.get("oca_group")
                    if oca_result.get("partial"):
                        logger.error(
                            f"[v19.34.28 PARTIAL-OCA] {sym} adopted slice "
                            f"{trade.id}: stop attached ({trade.stop_order_id}) "
                            f"but TARGET MISSING. Operator should place a "
                            f"manual LMT at ${target_1:.2f} or accept "
                            f"stop-only protection."
                        )
                        try:
                            from services.trade_drop_recorder import record_trade_drop
                            record_trade_drop(
                                trade,
                                gate="naked_adopted_slice_partial",
                                context={
                                    "phase": "spawn_excess_slice",
                                    "stop_price": stop_price,
                                    "target_price": target_1,
                                    "shares": excess_abs,
                                    "errors": oca_result.get("errors", []),
                                },
                            )
                        except Exception:
                            pass
                    else:
                        logger.warning(
                            f"[v19.34.28] {sym} adopted slice {trade.id} "
                            f"OCA bracket attached: stop={trade.stop_order_id} "
                            f"(${stop_price:.2f}), target={tgt_id} "
                            f"(${target_1:.2f}), oca={trade.oca_group}"
                        )
                else:
                    err = (oca_result or {}).get("error", "no result")
                    logger.error(
                        f"[v19.34.28 NAKED-SLICE] {sym} adopted slice "
                        f"{trade.id} but FAILED to attach OCA bracket: "
                        f"{err}. Position is unprotected at the broker. "
                        f"Operator must place a manual stop at "
                        f"${stop_price:.2f} + target at ${target_1:.2f}, "
                        f"or close the position in TWS."
                    )
                    try:
                        from services.trade_drop_recorder import record_trade_drop
                        record_trade_drop(
                            trade,
                            gate="naked_adopted_slice",
                            context={
                                "phase": "spawn_excess_slice",
                                "stop_price": stop_price,
                                "target_price": target_1,
                                "shares": excess_abs,
                                "error": str(err)[:200],
                            },
                        )
                    except Exception:
                        pass
            elif executor and hasattr(executor, "place_stop_order"):
                # Fallback for older executor (e.g. legacy tests that
                # mock-patched only place_stop_order). Never hit in
                # production post-v19.34.28.
                stop_result = await executor.place_stop_order(trade)
                if stop_result and stop_result.get("success"):
                    trade.stop_order_id = (
                        stop_result.get("order_id")
                        or stop_result.get("stop_order_id")
                    )
                    logger.warning(
                        f"[v19.34.28 STOP-ONLY-FALLBACK] {sym} slice "
                        f"{trade.id} stop={trade.stop_order_id} "
                        f"(executor lacks attach_oca_stop_target)"
                    )
                else:
                    err = (stop_result or {}).get("error", "no result")
                    logger.error(
                        f"[v19.34.28 NAKED-SLICE] {sym} slice {trade.id} "
                        f"stop attach failed: {err}"
                    )
            else:
                logger.warning(
                    f"[v19.34.28] {sym} adopted slice {trade.id}: no "
                    f"_trade_executor on bot — slice is NAKED at IB."
                )
        except Exception as stop_err:
            logger.error(
                f"[v19.34.28] {sym} adopted slice {trade.id} OCA-attach "
                f"raised: {stop_err}. Slice is naked at IB."
            )

        return trade.id

    async def _persist_drift_event(self, report: Dict[str, Any]) -> None:
        """Forensic write to `share_drift_events` (TTL 7d)."""
        try:
            global _share_drift_indexes_ready
            if not _share_drift_indexes_ready:
                try:
                    self.db["share_drift_events"].create_index(
                        "created_at", expireAfterSeconds=7 * 24 * 60 * 60,
                    )
                    self.db["share_drift_events"].create_index([("symbol", 1)])
                    _share_drift_indexes_ready = True
                except Exception:
                    pass
            doc = {
                "created_at": datetime.now(timezone.utc),
                "auto_resolve": report.get("auto_resolve"),
                "drift_threshold": report.get("drift_threshold"),
                "drifts_detected": report.get("drifts_detected") or [],
                "drifts_resolved": report.get("drifts_resolved") or [],
                "skipped": report.get("skipped") or [],
                "errors": report.get("errors") or [],
            }
            self.db["share_drift_events"].insert_one(doc)
        except Exception as e:
            logger.debug(f"[v19.34.15b] persist drift event failed: {e}")


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
                # v19.34.5 — even emergency stops respect classification.
                # If we have a bot_trades row for this symbol, honor its style;
                # otherwise default to GTC since we don't know whether the
                # position is intraday or overnight (safer to protect).
                _legs_tif, _legs_outside_rth = ("GTC", True)
                if trade is not None:
                    from services.bracket_tif import bracket_tif as _bracket_tif
                    _legs_tif, _legs_outside_rth = _bracket_tif(
                        getattr(trade, "trade_style", None),
                        getattr(trade, "timeframe", None),
                    )
                stop_payload = {
                    "symbol": symbol,
                    "action": action,
                    "quantity": int(abs(qty)),
                    "order_type": "STP",
                    "stop_price": stop_price,
                    "limit_price": None,
                    "time_in_force": _legs_tif,
                    "outside_rth": _legs_outside_rth,
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
