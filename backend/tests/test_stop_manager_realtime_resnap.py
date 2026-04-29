"""Tests for the realtime stop-guard re-check (2026-04-30, operator P1).

Pre-fix (`stop_manager.py` 2026-04-29 build):
  - `update_trailing_stop` only re-snapped on (a) a target hit OR
    (b) price extending to a fresh high/low.
  - If the liquidity profile shifted DURING a held position (e.g.
    a tighter HVN appeared via fresh tick-data), the stop wouldn't
    move until next high-water-mark print.

Post-fix:
  - Adds `_periodic_resnap_check(trade)` called at the end of every
    `update_trailing_stop` call.
  - Throttle: `_RESNAP_INTERVAL_SECONDS = 60.0` per-trade (operator-confirmed).
  - Hard guarantee: only ratchets — never loosens.
  - Skips `mode == 'original'` — operator's hard stop pre-T1 stays put.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/app/backend")

import pytest  # noqa: E402

STOP_MANAGER_SRC = Path(
    "/app/backend/services/stop_manager.py"
).read_text("utf-8")


# ───────── Source-level guards ─────────


def test_resnap_throttle_constant_is_60_seconds():
    """Operator-confirmed throttle. Source-pinned so a future
    refactor that bumps this without owner buy-in fails the suite."""
    assert "_RESNAP_INTERVAL_SECONDS = 60.0" in STOP_MANAGER_SRC


def test_resnap_check_method_exists():
    assert "def _periodic_resnap_check(self, trade:" in STOP_MANAGER_SRC


def test_resnap_runs_on_breakeven_and_trailing_only():
    """Source-level guard: the dispatch line must include both
    `breakeven` and `trailing` modes but NOT `original`."""
    assert "if latest_mode in ('breakeven', 'trailing'):" in STOP_MANAGER_SRC
    assert "self._periodic_resnap_check(trade)" in STOP_MANAGER_SRC


def test_resnap_only_ratchets_long():
    """For long trades, candidate must be > old_stop to commit."""
    # Find the long-side ratchet check
    block = STOP_MANAGER_SRC[
        STOP_MANAGER_SRC.find("def _periodic_resnap_check"):
    ]
    assert "if candidate <= old_stop:" in block, (
        "Long ratchet guard missing — re-snap could loosen long stops"
    )


def test_resnap_only_ratchets_short():
    """For short trades, candidate must be < old_stop to commit."""
    block = STOP_MANAGER_SRC[
        STOP_MANAGER_SRC.find("def _periodic_resnap_check"):
    ]
    assert "if candidate >= old_stop:" in block, (
        "Short ratchet guard missing — re-snap could loosen short stops"
    )


def test_resnap_records_adjustment():
    """The re-snap path must call `_record_stop_adjustment` so the
    operator's audit trail captures it."""
    block = STOP_MANAGER_SRC[
        STOP_MANAGER_SRC.find("def _periodic_resnap_check"):
    ]
    assert "self._record_stop_adjustment(trade, old_stop, new_stop, reason)" in block


def test_resnap_writes_telemetry_metadata():
    """Re-snap should populate `last_resnap_at` and `last_resnap_level`
    on the trade's trailing_stop_config so the diagnostic surfaces
    can show what changed."""
    block = STOP_MANAGER_SRC[
        STOP_MANAGER_SRC.find("def _periodic_resnap_check"):
    ]
    assert "trailing_config['last_resnap_at']" in block
    assert "trailing_config['last_resnap_level']" in block


# ───────── Behavioural tests with stub trade ─────────


class _StubDirection:
    LONG = "long"
    SHORT = "short"


class _StubTrade:
    """Minimal trade stub mimicking BotTrade for testing only the
    StopManager's re-snap surface."""

    def __init__(self, direction, entry, current_price, stop, mode='trailing',
                 trade_id="stub-1", timeframe="5 mins"):
        self.id = trade_id
        self.symbol = "TEST"
        self.direction = direction
        self.fill_price = entry
        self.entry_price = entry
        self.current_price = current_price
        self.stop_price = stop
        self.timeframe = timeframe
        self.scale_out_config = {'targets_hit': [0, 1]}  # both targets hit
        self.trailing_stop_config = {
            'enabled': True,
            'mode': mode,
            'current_stop': stop,
            'original_stop': stop,
            'high_water_mark': current_price,
            'low_water_mark': current_price,
            'trail_pct': 0.02,
            'stop_adjustments': [],
        }


def _patch_trading_bot_module():
    """Monkey-patch a fake trading_bot_service module so StopManager's
    inline TYPE_CHECKING / TradeDirection imports resolve in CI."""
    import types
    fake = types.ModuleType("services.trading_bot_service")
    fake.TradeDirection = _StubDirection
    fake.BotTrade = _StubTrade
    sys.modules["services.trading_bot_service"] = fake


def test_resnap_throttle_blocks_within_60s():
    """Calling re-snap twice in <60s → second call is a no-op."""
    _patch_trading_bot_module()
    from services.stop_manager import StopManager

    sm = StopManager()
    trade = _StubTrade(
        direction=_StubDirection.LONG,
        entry=100.0,
        current_price=110.0,
        stop=99.0,
        mode='trailing',
    )

    with patch.object(sm, '_snap_to_liquidity', return_value={
        "snapped": True, "stop": 105.0,
        "level_kind": "HVN", "level_price": 105.0, "level_strength": 0.9,
    }):
        # First call — should commit
        sm._periodic_resnap_check(trade)
        assert trade.trailing_stop_config['current_stop'] == 105.0

        # Same instant — second call is throttled
        sm._periodic_resnap_check(trade)
        # Stop should still be 105.0 (snap not re-evaluated)
        assert trade.trailing_stop_config['current_stop'] == 105.0
        # Only one adjustment recorded
        assert len(trade.trailing_stop_config['stop_adjustments']) == 1


def test_resnap_does_not_loosen_long():
    """If candidate stop is BELOW current for a long, do nothing."""
    _patch_trading_bot_module()
    from services.stop_manager import StopManager

    sm = StopManager()
    trade = _StubTrade(
        direction=_StubDirection.LONG,
        entry=100.0,
        current_price=110.0,
        stop=105.0,  # already at 105
        mode='trailing',
    )

    with patch.object(sm, '_snap_to_liquidity', return_value={
        "snapped": True, "stop": 102.0,  # WORSE — would loosen the stop
        "level_kind": "HVN", "level_price": 102.0, "level_strength": 0.9,
    }):
        sm._periodic_resnap_check(trade)

    # Stop unchanged; no adjustment recorded.
    assert trade.trailing_stop_config['current_stop'] == 105.0
    assert len(trade.trailing_stop_config['stop_adjustments']) == 0


def test_resnap_does_not_loosen_short():
    """If candidate stop is ABOVE current for a short, do nothing."""
    _patch_trading_bot_module()
    from services.stop_manager import StopManager

    sm = StopManager()
    trade = _StubTrade(
        direction=_StubDirection.SHORT,
        entry=100.0,
        current_price=90.0,
        stop=95.0,  # already at 95
        mode='trailing',
    )

    with patch.object(sm, '_snap_to_liquidity', return_value={
        "snapped": True, "stop": 98.0,  # WORSE — would loosen the short stop
        "level_kind": "HVN", "level_price": 98.0, "level_strength": 0.9,
    }):
        sm._periodic_resnap_check(trade)

    assert trade.trailing_stop_config['current_stop'] == 95.0
    assert len(trade.trailing_stop_config['stop_adjustments']) == 0


def test_resnap_throttle_clears_after_interval():
    """After 60s elapse, second re-snap call evaluates again."""
    _patch_trading_bot_module()
    from services.stop_manager import StopManager

    sm = StopManager()
    trade = _StubTrade(
        direction=_StubDirection.LONG,
        entry=100.0,
        current_price=115.0,
        stop=99.0,
        mode='trailing',
    )

    with patch.object(sm, '_snap_to_liquidity', return_value={
        "snapped": True, "stop": 110.0,
        "level_kind": "HVN", "level_price": 110.0, "level_strength": 0.9,
    }):
        sm._periodic_resnap_check(trade)
    assert trade.trailing_stop_config['current_stop'] == 110.0

    # Manually backdate the throttle stamp by 61s
    sm._last_resnap_at[trade.id] = (
        datetime.now(timezone.utc) - timedelta(seconds=61)
    )

    with patch.object(sm, '_snap_to_liquidity', return_value={
        "snapped": True, "stop": 113.0,
        "level_kind": "HVN", "level_price": 113.0, "level_strength": 0.95,
    }):
        sm._periodic_resnap_check(trade)
    # New ratchet committed
    assert trade.trailing_stop_config['current_stop'] == 113.0
    assert len(trade.trailing_stop_config['stop_adjustments']) == 2


def test_resnap_skipped_when_no_snap_available():
    """`_snap_to_liquidity` returning None → no-op, no adjustment."""
    _patch_trading_bot_module()
    from services.stop_manager import StopManager

    sm = StopManager()
    trade = _StubTrade(
        direction=_StubDirection.LONG,
        entry=100.0,
        current_price=110.0,
        stop=99.0,
        mode='trailing',
    )

    with patch.object(sm, '_snap_to_liquidity', return_value=None):
        sm._periodic_resnap_check(trade)

    assert trade.trailing_stop_config['current_stop'] == 99.0
    assert len(trade.trailing_stop_config['stop_adjustments']) == 0
