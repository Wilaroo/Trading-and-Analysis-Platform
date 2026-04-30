"""
Stop Manager — Extracted from trading_bot_service.py

Handles all trailing stop logic:
- Breakeven stops after Target 1
- Trailing stops after Target 2
- Trail position updates
- Stop adjustment history

2026-04-29 — Liquidity-aware trailing (Q1 from operator backlog):
  When `_db` is wired and `compute_trailing_stop_snap` finds a strong
  support/resistance cluster on the protected side of the trade, we
  snap the new stop to that level instead of using a fixed % / exact
  breakeven. Falls through cleanly to the legacy ATR/breakeven logic
  when no level is found (so the manager keeps working without smart
  levels).

2026-04-30 — Realtime stop-guard re-check (operator-flagged P1):
  Pre-fix, snaps only fired on (a) a target hit OR (b) price extending
  to a fresh high/low. If the liquidity profile shifted DURING a held
  position (e.g., a new HVN forms tighter than the current stop, or a
  HOD/LOD pivot lands in the protected zone), the trail wouldn't re-
  evaluate until the next high-water-mark print. Now `update_trailing_stop`
  runs a `_periodic_resnap_check` once every `_RESNAP_INTERVAL_SECONDS`
  per trade (default 60s — operator-confirmed throttle). Re-snap only
  RATCHETS — never loosens — so a stale liquidity read can't widen
  the stop.
"""
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradeDirection

logger = logging.getLogger(__name__)


class StopManager:
    """Manages trailing stop logic for open trades."""

    # Realtime stop-guard re-check throttle. Operator-confirmed at 60s
    # so smart_levels_service / IB-pusher RPC don't get hammered.
    _RESNAP_INTERVAL_SECONDS = 60.0

    def __init__(self):
        self._db = None
        # Per-trade timestamp of the last periodic re-snap. Keyed by
        # trade.id so multiple open positions don't share the throttle.
        self._last_resnap_at: Dict[str, datetime] = {}

    def set_db(self, db):
        """Inject DB so the manager can call into `smart_levels_service`
        for liquidity-aware stop snaps. Optional — without it, manager
        falls back to legacy ATR/breakeven behaviour."""
        self._db = db

    async def update_trailing_stop(self, trade: 'BotTrade'):
        """
        Update trailing stop based on targets hit:
        - Target 1 hit: Move stop to breakeven (entry price)
        - Target 2 hit: Start trailing stop (follows price by trail_pct)

        After the target-driven branches, runs a periodic stop-guard
        re-check (every 60s per trade) so stale liquidity reads get
        refreshed even when price hasn't extended to a fresh high/low.
        """
        from services.trading_bot_service import TradeDirection
        targets_hit = trade.scale_out_config.get('targets_hit', [])
        trailing_config = trade.trailing_stop_config
        current_mode = trailing_config.get('mode', 'original')

        if 1 in targets_hit and current_mode == 'original':
            self._activate_trailing_stop(trade)
        elif 0 in targets_hit and current_mode == 'original':
            self._move_stop_to_breakeven(trade)

        if current_mode == 'trailing':
            self._update_trail_position(trade)

        # Realtime stop-guard re-check — fires for breakeven and
        # trailing modes. Skips `original` mode (pre-T1) because the
        # operator's hard stop is intentional and shouldn't be re-snapped
        # before any profit has been booked.
        latest_mode = trailing_config.get('mode', current_mode)
        if latest_mode in ('breakeven', 'trailing'):
            self._periodic_resnap_check(trade)

    # ── Periodic stop-guard re-check ────────────────────────────────────────
    def _periodic_resnap_check(self, trade: 'BotTrade'):
        """Re-evaluate the current stop against the latest liquidity
        profile. Throttled per-trade so we don't hammer smart_levels
        every tick.

        Hard guarantee: only RATCHETS in the protective direction —
        a re-snap can never loosen the stop.
        """
        from services.trading_bot_service import TradeDirection

        # Throttle: per-trade 60s cooldown.
        trade_id = getattr(trade, 'id', None) or getattr(trade, 'trade_id', None)
        if not trade_id:
            return  # without an id we can't throttle safely
        now = datetime.now(timezone.utc)
        last = self._last_resnap_at.get(trade_id)
        if last is not None:
            if (now - last).total_seconds() < self._RESNAP_INTERVAL_SECONDS:
                return
        # Stamp BEFORE the snap call so a flaky smart_levels lookup
        # can't put us in a tight retry loop.
        self._last_resnap_at[trade_id] = now

        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)
        if old_stop is None or old_stop <= 0:
            return

        snap = self._snap_to_liquidity(trade, old_stop)
        if not snap or not snap.get("snapped"):
            return
        candidate = snap["stop"]
        # Ratchet — only commit if the candidate is more protective.
        if trade.direction == TradeDirection.LONG:
            if candidate <= old_stop:
                return
        else:
            if candidate >= old_stop:
                return

        new_stop = round(candidate, 2)
        trailing_config['current_stop'] = new_stop
        trailing_config['last_resnap_at'] = now.isoformat()
        trailing_config['last_resnap_level'] = {
            "kind":     snap.get("level_kind"),
            "price":    snap.get("level_price"),
            "strength": snap.get("level_strength"),
        }
        mode = trailing_config.get('mode', 'unknown')
        reason = f"resnap_{mode}_hvn"
        self._record_stop_adjustment(trade, old_stop, new_stop, reason)
        level_kind = snap.get("level_kind") or "level"
        level_price = snap.get("level_price")
        level_str = (
            f" (snap to {level_kind} @ ${level_price:.2f})"
            if level_price is not None else ""
        )
        logger.info(
            f"STOP-GUARD RESNAP ({mode}): {trade.symbol} "
            f"${old_stop:.2f} → ${new_stop:.2f}{level_str}"
        )

    # ── Liquidity-aware snap helper ────────────────────────────────────────
    def _snap_to_liquidity(
        self,
        trade: 'BotTrade',
        proposed_stop: float,
    ) -> Optional[dict]:
        """Try to snap `proposed_stop` to a strong S/R level on the
        protected side of the trade. Returns the snap result dict on
        success, or `None` if no snap is available (DB not wired,
        timeframe missing, no qualifying level)."""
        if self._db is None or not trade.timeframe:
            return None
        try:
            from services.smart_levels_service import compute_trailing_stop_snap
            from services.trading_bot_service import TradeDirection

            direction = "long" if trade.direction == TradeDirection.LONG else "short"
            result = compute_trailing_stop_snap(
                db=self._db,
                symbol=trade.symbol,
                bar_size=trade.timeframe,
                entry=trade.fill_price or trade.entry_price,
                current_price=trade.current_price,
                proposed_stop=proposed_stop,
                direction=direction,
            )
            if result.get("snapped"):
                return result
        except Exception as e:
            logger.warning(
                f"StopManager: liquidity snap failed for {trade.symbol}: {e}"
            )
        return None

    def _move_stop_to_breakeven(self, trade: 'BotTrade'):
        """Move stop to breakeven (entry price) after Target 1 hit.

        2026-04-29: when smart-levels DB is available, we first ask
        `compute_trailing_stop_snap` for the nearest HVN below entry
        (long) / above entry (short) and use that instead of exact
        breakeven. This anchors the stop in real liquidity rather than
        a round number that's vulnerable to wicks.
        """
        from services.trading_bot_service import TradeDirection
        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)
        breakeven_stop = trade.fill_price

        # Try liquidity-aware snap first; fall back to exact breakeven.
        snap = self._snap_to_liquidity(trade, breakeven_stop)
        new_stop = snap["stop"] if snap else breakeven_stop
        snap_meta = snap or {}

        if trade.direction == TradeDirection.LONG:
            # Only ratchet UP. The snap may suggest a stop slightly
            # below breakeven (HVN below entry) — that's intentional
            # and preferred over exact entry, but we still require it
            # be > old_stop so we never loosen mid-trade.
            if new_stop > old_stop:
                trailing_config['current_stop'] = round(new_stop, 2)
                trailing_config['mode'] = 'breakeven'
                if snap and snap.get("snapped"):
                    trailing_config['breakeven_snap_level'] = {
                        "kind": snap_meta.get("level_kind"),
                        "price": snap_meta.get("level_price"),
                        "strength": snap_meta.get("level_strength"),
                    }
                reason = 'breakeven_hvn_snap' if snap else 'breakeven'
                self._record_stop_adjustment(trade, old_stop, new_stop, reason)
                logger.info(
                    f"BREAKEVEN STOP: {trade.symbol} stop moved from ${old_stop:.2f} to ${new_stop:.2f}"
                    + (f" (snapped to {snap_meta.get('level_kind')} @ ${snap_meta.get('level_price'):.2f})" if snap else "")
                )
        else:
            if new_stop < old_stop:
                trailing_config['current_stop'] = round(new_stop, 2)
                trailing_config['mode'] = 'breakeven'
                if snap and snap.get("snapped"):
                    trailing_config['breakeven_snap_level'] = {
                        "kind": snap_meta.get("level_kind"),
                        "price": snap_meta.get("level_price"),
                        "strength": snap_meta.get("level_strength"),
                    }
                reason = 'breakeven_hvn_snap' if snap else 'breakeven'
                self._record_stop_adjustment(trade, old_stop, new_stop, reason)
                logger.info(
                    f"BREAKEVEN STOP: {trade.symbol} stop moved from ${old_stop:.2f} to ${new_stop:.2f}"
                    + (f" (snapped to {snap_meta.get('level_kind')} @ ${snap_meta.get('level_price'):.2f})" if snap else "")
                )

    def _activate_trailing_stop(self, trade: 'BotTrade'):
        """Activate trailing stop after Target 2 hit."""
        from services.trading_bot_service import TradeDirection
        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)

        if trade.direction == TradeDirection.LONG:
            trailing_config['high_water_mark'] = trade.current_price
            trail_pct = trailing_config.get('trail_pct', 0.02)
            atr_stop = round(trade.current_price * (1 - trail_pct), 2)
            # Liquidity snap — prefer the nearest HVN below price if
            # one exists in range; else fall back to ATR/% trail.
            snap = self._snap_to_liquidity(trade, atr_stop)
            new_stop = snap["stop"] if snap else atr_stop
            new_stop = max(new_stop, old_stop)
        else:
            trailing_config['low_water_mark'] = trade.current_price
            trail_pct = trailing_config.get('trail_pct', 0.02)
            atr_stop = round(trade.current_price * (1 + trail_pct), 2)
            snap = self._snap_to_liquidity(trade, atr_stop)
            new_stop = snap["stop"] if snap else atr_stop
            new_stop = min(new_stop, old_stop)

        trailing_config['current_stop'] = new_stop
        trailing_config['mode'] = 'trailing'

        if new_stop != old_stop:
            reason = 'trailing_activated_hvn_snap' if (snap and snap.get("snapped")) else 'trailing_activated'
            self._record_stop_adjustment(trade, old_stop, new_stop, reason)
            trail_label = "HVN-snap" if (snap and snap.get("snapped")) else f"{trail_pct*100:.1f}%"
            logger.info(
                f"TRAILING STOP ACTIVATED: {trade.symbol} stop at ${new_stop:.2f} (trailing {trail_label})"
            )

    def _update_trail_position(self, trade: 'BotTrade'):
        """Update the trailing stop position based on price movement.

        2026-04-29: each trail tick now tries a liquidity snap first.
        If a strong HVN sits just below the would-be ATR/% trail, we
        anchor to it; otherwise the legacy fixed-% trail kicks in.
        """
        from services.trading_bot_service import TradeDirection
        trailing_config = trade.trailing_stop_config
        trail_pct = trailing_config.get('trail_pct', 0.02)
        old_stop = trailing_config.get('current_stop', trade.stop_price)

        if trade.direction == TradeDirection.LONG:
            high_water = trailing_config.get('high_water_mark', trade.current_price)
            if trade.current_price > high_water:
                trailing_config['high_water_mark'] = trade.current_price
                atr_stop = round(trade.current_price * (1 - trail_pct), 2)
                snap = self._snap_to_liquidity(trade, atr_stop)
                new_stop = snap["stop"] if snap else atr_stop
                if new_stop > old_stop:
                    trailing_config['current_stop'] = new_stop
                    reason = 'trail_up_hvn_snap' if (snap and snap.get("snapped")) else 'trail_up'
                    self._record_stop_adjustment(trade, old_stop, new_stop, reason)
                    suffix = f" (HVN @ ${snap.get('level_price'):.2f})" if (snap and snap.get("snapped")) else ""
                    logger.info(
                        f"TRAILING STOP MOVED: {trade.symbol} stop raised to ${new_stop:.2f} (high: ${trade.current_price:.2f}){suffix}"
                    )
        else:
            low_water = trailing_config.get('low_water_mark', trade.current_price)
            if trade.current_price < low_water:
                trailing_config['low_water_mark'] = trade.current_price
                atr_stop = round(trade.current_price * (1 + trail_pct), 2)
                snap = self._snap_to_liquidity(trade, atr_stop)
                new_stop = snap["stop"] if snap else atr_stop
                if new_stop < old_stop:
                    trailing_config['current_stop'] = new_stop
                    reason = 'trail_down_hvn_snap' if (snap and snap.get("snapped")) else 'trail_down'
                    self._record_stop_adjustment(trade, old_stop, new_stop, reason)
                    suffix = f" (HVN @ ${snap.get('level_price'):.2f})" if (snap and snap.get("snapped")) else ""
                    logger.info(
                        f"TRAILING STOP MOVED: {trade.symbol} stop lowered to ${new_stop:.2f} (low: ${trade.current_price:.2f}){suffix}"
                    )

    def _record_stop_adjustment(self, trade: 'BotTrade', old_stop: float, new_stop: float, reason: str):
        """Record a stop adjustment in the trailing stop history.

        2026-04-30 v19.13 — caps history at the most-recent 100 entries
        so a long-running swing position with hundreds of trail moves
        doesn't bloat the BotTrade dict (Mongo round-trips, snapshot
        size, log spam).
        """
        adjustment = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'old_stop': old_stop,
            'new_stop': new_stop,
            'reason': reason,
            'price_at_adjustment': trade.current_price
        }
        history = trade.trailing_stop_config.setdefault('stop_adjustments', [])
        history.append(adjustment)
        # Cap at last 100 entries (drops oldest in-place)
        if len(history) > 100:
            del history[:-100]

    def forget_trade(self, trade_id: str) -> None:
        """v19.13 — release internal per-trade state when a trade closes.

        The PositionManager's `close_trade` calls this so the
        `_last_resnap_at` dict doesn't accumulate closed-trade IDs
        forever (small but real memory leak over weeks of operation).
        Safe to call multiple times.
        """
        if trade_id in self._last_resnap_at:
            self._last_resnap_at.pop(trade_id, None)
