"""
Stop Manager — Extracted from trading_bot_service.py

Handles all trailing stop logic:
- Breakeven stops after Target 1
- Trailing stops after Target 2
- Trail position updates
- Stop adjustment history
"""
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.trading_bot_service import BotTrade, TradeDirection

logger = logging.getLogger(__name__)


class StopManager:
    """Manages trailing stop logic for open trades."""

    async def update_trailing_stop(self, trade: 'BotTrade'):
        """
        Update trailing stop based on targets hit:
        - Target 1 hit: Move stop to breakeven (entry price)
        - Target 2 hit: Start trailing stop (follows price by trail_pct)
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

    def _move_stop_to_breakeven(self, trade: 'BotTrade'):
        """Move stop to breakeven (entry price) after Target 1 hit."""
        from services.trading_bot_service import TradeDirection
        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)
        new_stop = trade.fill_price

        if trade.direction == TradeDirection.LONG:
            if new_stop > old_stop:
                trailing_config['current_stop'] = round(new_stop, 2)
                trailing_config['mode'] = 'breakeven'
                self._record_stop_adjustment(trade, old_stop, new_stop, 'breakeven')
                logger.info(f"BREAKEVEN STOP: {trade.symbol} stop moved from ${old_stop:.2f} to ${new_stop:.2f}")
        else:
            if new_stop < old_stop:
                trailing_config['current_stop'] = round(new_stop, 2)
                trailing_config['mode'] = 'breakeven'
                self._record_stop_adjustment(trade, old_stop, new_stop, 'breakeven')
                logger.info(f"BREAKEVEN STOP: {trade.symbol} stop moved from ${old_stop:.2f} to ${new_stop:.2f}")

    def _activate_trailing_stop(self, trade: 'BotTrade'):
        """Activate trailing stop after Target 2 hit."""
        from services.trading_bot_service import TradeDirection
        trailing_config = trade.trailing_stop_config
        old_stop = trailing_config.get('current_stop', trade.stop_price)

        if trade.direction == TradeDirection.LONG:
            trailing_config['high_water_mark'] = trade.current_price
            trail_pct = trailing_config.get('trail_pct', 0.02)
            new_stop = round(trade.current_price * (1 - trail_pct), 2)
            new_stop = max(new_stop, old_stop)
        else:
            trailing_config['low_water_mark'] = trade.current_price
            trail_pct = trailing_config.get('trail_pct', 0.02)
            new_stop = round(trade.current_price * (1 + trail_pct), 2)
            new_stop = min(new_stop, old_stop)

        trailing_config['current_stop'] = new_stop
        trailing_config['mode'] = 'trailing'

        if new_stop != old_stop:
            self._record_stop_adjustment(trade, old_stop, new_stop, 'trailing_activated')
            logger.info(f"TRAILING STOP ACTIVATED: {trade.symbol} stop at ${new_stop:.2f} (trailing {trail_pct*100:.1f}%)")

    def _update_trail_position(self, trade: 'BotTrade'):
        """Update the trailing stop position based on price movement."""
        from services.trading_bot_service import TradeDirection
        trailing_config = trade.trailing_stop_config
        trail_pct = trailing_config.get('trail_pct', 0.02)
        old_stop = trailing_config.get('current_stop', trade.stop_price)

        if trade.direction == TradeDirection.LONG:
            high_water = trailing_config.get('high_water_mark', trade.current_price)
            if trade.current_price > high_water:
                trailing_config['high_water_mark'] = trade.current_price
                new_stop = round(trade.current_price * (1 - trail_pct), 2)
                if new_stop > old_stop:
                    trailing_config['current_stop'] = new_stop
                    self._record_stop_adjustment(trade, old_stop, new_stop, 'trail_up')
                    logger.info(f"TRAILING STOP MOVED: {trade.symbol} stop raised to ${new_stop:.2f} (high: ${trade.current_price:.2f})")
        else:
            low_water = trailing_config.get('low_water_mark', trade.current_price)
            if trade.current_price < low_water:
                trailing_config['low_water_mark'] = trade.current_price
                new_stop = round(trade.current_price * (1 + trail_pct), 2)
                if new_stop < old_stop:
                    trailing_config['current_stop'] = new_stop
                    self._record_stop_adjustment(trade, old_stop, new_stop, 'trail_down')
                    logger.info(f"TRAILING STOP MOVED: {trade.symbol} stop lowered to ${new_stop:.2f} (low: ${trade.current_price:.2f})")

    def _record_stop_adjustment(self, trade: 'BotTrade', old_stop: float, new_stop: float, reason: str):
        """Record a stop adjustment in the trailing stop history."""
        adjustment = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'old_stop': old_stop,
            'new_stop': new_stop,
            'reason': reason,
            'price_at_adjustment': trade.current_price
        }
        trade.trailing_stop_config.setdefault('stop_adjustments', []).append(adjustment)
