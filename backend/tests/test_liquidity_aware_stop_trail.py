"""
Tests for liquidity-aware trailing stops (Q1 from operator backlog).

Two layers of coverage:

1. `services.smart_levels_service.compute_trailing_stop_snap` —
   pure-function tests against a stubbed `compute_smart_levels`.
2. `services.stop_manager.StopManager` — verifies the manager calls
   the snap helper when DB is wired and falls back to the legacy
   fixed-% / breakeven path when DB is None or no level qualifies.
"""

from unittest.mock import patch, MagicMock

import pytest


# ───────────────────────── compute_trailing_stop_snap ─────────────────────


def _make_levels(supports=None, resistances=None, error=None):
    """Build a synthetic compute_smart_levels return shape."""
    if error:
        return {"error": error, "support": [], "resistance": []}
    return {
        "current_price": 100.0,
        "support": supports or [],
        "resistance": resistances or [],
        "sources": {},
        "timeframe": "5min",
    }


@patch("services.smart_levels_service.compute_smart_levels")
@patch("services.smart_levels_service._get_active_thresholds",
       return_value={"stop_min_level_strength": 0.5,
                     "target_snap_outside_pct": 0.012,
                     "path_vol_fat_pct": 0.025})
def test_long_snaps_to_highest_qualifying_hvn_below_price(mock_thresh, mock_levels):
    """LONG: pick the highest support below current_price (closest to
    price → tightest liquidity-anchored trail)."""
    from services.smart_levels_service import compute_trailing_stop_snap

    mock_levels.return_value = _make_levels(supports=[
        {"price": 99.50, "kind": "HVN", "strength": 0.65},
        {"price": 99.20, "kind": "VP_POC", "strength": 0.95},
        {"price": 98.80, "kind": "S1", "strength": 0.55},
    ])

    res = compute_trailing_stop_snap(
        db=MagicMock(), symbol="AAPL", bar_size="5 mins",
        entry=100.0, current_price=100.0,
        proposed_stop=98.0, direction="long",
    )
    assert res["snapped"] is True
    assert res["reason"] == "snapped_to_hvn_below"
    # Highest support below price = 99.50, snapped to 99.50 - epsilon.
    assert res["level_price"] == 99.50
    assert 99.40 <= res["stop"] < 99.50


@patch("services.smart_levels_service.compute_smart_levels")
@patch("services.smart_levels_service._get_active_thresholds",
       return_value={"stop_min_level_strength": 0.5,
                     "target_snap_outside_pct": 0.012,
                     "path_vol_fat_pct": 0.025})
def test_long_skips_weak_levels(mock_thresh, mock_levels):
    """Levels below the active min-strength threshold must be ignored."""
    from services.smart_levels_service import compute_trailing_stop_snap

    mock_levels.return_value = _make_levels(supports=[
        # All below the 0.5 strength gate.
        {"price": 99.50, "kind": "HVN", "strength": 0.40},
        {"price": 99.20, "kind": "SWING_LOW", "strength": 0.45},
    ])

    res = compute_trailing_stop_snap(
        db=MagicMock(), symbol="AAPL", bar_size="5 mins",
        entry=100.0, current_price=100.0,
        proposed_stop=98.0, direction="long",
    )
    assert res["snapped"] is False
    assert res["reason"] == "no_levels_in_range"
    assert res["stop"] == 98.0  # falls back to proposed


@patch("services.smart_levels_service.compute_smart_levels")
@patch("services.smart_levels_service._get_active_thresholds",
       return_value={"stop_min_level_strength": 0.5,
                     "target_snap_outside_pct": 0.012,
                     "path_vol_fat_pct": 0.025})
def test_long_does_not_loosen_stop(mock_thresh, mock_levels):
    """Snap must never produce a stop below `proposed_stop` (would
    loosen risk mid-trade)."""
    from services.smart_levels_service import compute_trailing_stop_snap

    mock_levels.return_value = _make_levels(supports=[
        # HVN at 99.30 sits BELOW proposed_stop at 99.50 (inside the
        # 2% search window) — snapping would loosen the stop.
        {"price": 99.30, "kind": "HVN", "strength": 0.95},
    ])

    res = compute_trailing_stop_snap(
        db=MagicMock(), symbol="AAPL", bar_size="5 mins",
        entry=100.0, current_price=100.0,
        proposed_stop=99.50, direction="long",
    )
    assert res["snapped"] is False
    assert res["reason"] == "would_loosen_stop"


@patch("services.smart_levels_service.compute_smart_levels")
@patch("services.smart_levels_service._get_active_thresholds",
       return_value={"stop_min_level_strength": 0.5,
                     "target_snap_outside_pct": 0.012,
                     "path_vol_fat_pct": 0.025})
def test_short_snaps_to_lowest_qualifying_resistance_above_price(mock_thresh, mock_levels):
    """SHORT: pick the lowest resistance above current_price."""
    from services.smart_levels_service import compute_trailing_stop_snap

    mock_levels.return_value = _make_levels(resistances=[
        {"price": 100.20, "kind": "HVN", "strength": 0.70},
        {"price": 100.80, "kind": "R1", "strength": 0.95},
    ])

    res = compute_trailing_stop_snap(
        db=MagicMock(), symbol="AAPL", bar_size="5 mins",
        entry=100.0, current_price=100.0,
        proposed_stop=102.0, direction="short",
    )
    assert res["snapped"] is True
    assert res["reason"] == "snapped_to_hvn_above"
    assert res["level_price"] == 100.20  # lowest above price
    assert 100.20 < res["stop"] <= 100.30


@patch("services.smart_levels_service.compute_smart_levels")
def test_no_levels_doc_returns_clean_fallback(mock_levels):
    """If `compute_smart_levels` errors out, helper returns clean
    `snapped=False, stop=proposed_stop`."""
    from services.smart_levels_service import compute_trailing_stop_snap

    mock_levels.return_value = _make_levels(error="insufficient bars")

    res = compute_trailing_stop_snap(
        db=MagicMock(), symbol="AAPL", bar_size="5 mins",
        entry=100.0, current_price=100.0,
        proposed_stop=98.0, direction="long",
    )
    assert res["snapped"] is False
    assert res["reason"] == "no_levels"
    assert res["stop"] == 98.0


def test_invalid_inputs_return_safe_defaults():
    """Zero/None entry must short-circuit to a safe fallback (no DB
    call) so a misconfigured trade doesn't crash the manager."""
    from services.smart_levels_service import compute_trailing_stop_snap

    res = compute_trailing_stop_snap(
        db=MagicMock(), symbol="AAPL", bar_size="5 mins",
        entry=0.0, current_price=100.0, proposed_stop=98.0,
        direction="long",
    )
    assert res["snapped"] is False
    assert res["reason"] == "invalid_inputs"


# ───────────────────────── StopManager wiring ─────────────────────────────


def _make_trade(direction="long", **kwargs):
    """Build a minimal BotTrade-shaped object for stop_manager tests.

    Avoids importing the real BotTrade dataclass (which pulls all of
    trading_bot_service). The manager only reads a fixed set of attrs.
    """
    from services.trading_bot_service import TradeDirection

    class _T:
        pass

    t = _T()
    t.symbol = "AAPL"
    t.timeframe = "5min"
    t.entry_price = 100.0
    t.fill_price = 100.0
    t.current_price = kwargs.get("current_price", 102.0)
    t.stop_price = 98.0
    t.direction = TradeDirection.LONG if direction == "long" else TradeDirection.SHORT
    t.scale_out_config = {"targets_hit": [], "scale_out_pcts": [], "partial_exits": []}
    t.trailing_stop_config = kwargs.get("trailing_stop_config", {
        "enabled": True, "mode": "original",
        "original_stop": 98.0, "current_stop": 98.0,
        "trail_pct": 0.02, "high_water_mark": 0.0,
        "low_water_mark": 0.0, "stop_adjustments": [],
    })
    return t


def test_stop_manager_falls_back_when_db_not_wired():
    """Without `set_db()`, manager keeps legacy breakeven behaviour."""
    from services.stop_manager import StopManager

    mgr = StopManager()
    # No set_db call.
    trade = _make_trade(direction="long")

    mgr._move_stop_to_breakeven(trade)

    cfg = trade.trailing_stop_config
    assert cfg["mode"] == "breakeven"
    assert cfg["current_stop"] == 100.0  # exact entry, no snap
    # Adjustment recorded with legacy reason.
    last_adj = cfg["stop_adjustments"][-1]
    assert last_adj["reason"] == "breakeven"


@patch("services.smart_levels_service.compute_trailing_stop_snap")
def test_stop_manager_snaps_to_hvn_when_db_wired(mock_snap):
    """With DB wired and a snap available, manager uses HVN price."""
    from services.stop_manager import StopManager

    mock_snap.return_value = {
        "stop": 99.40, "snapped": True, "reason": "snapped_to_hvn_below",
        "level_kind": "HVN", "level_price": 99.50,
        "level_strength": 0.65, "original_stop": 100.0,
    }

    mgr = StopManager()
    mgr.set_db(MagicMock())
    trade = _make_trade(direction="long")
    trade.trailing_stop_config["current_stop"] = 98.0  # below 99.40 so snap will ratchet up

    mgr._move_stop_to_breakeven(trade)

    cfg = trade.trailing_stop_config
    assert cfg["mode"] == "breakeven"
    assert cfg["current_stop"] == 99.40
    assert cfg["breakeven_snap_level"]["kind"] == "HVN"
    last_adj = cfg["stop_adjustments"][-1]
    assert last_adj["reason"] == "breakeven_hvn_snap"


@patch("services.smart_levels_service.compute_trailing_stop_snap")
def test_stop_manager_uses_atr_trail_when_no_snap(mock_snap):
    """`_update_trail_position` must keep working when snap returns
    `snapped=False` — operator must still get the ATR/% trail."""
    from services.stop_manager import StopManager

    mock_snap.return_value = {
        "stop": 100.0, "snapped": False,
        "reason": "no_levels_in_range", "original_stop": 100.0,
    }

    mgr = StopManager()
    mgr.set_db(MagicMock())
    trade = _make_trade(direction="long")
    trade.current_price = 105.0
    trade.trailing_stop_config["mode"] = "trailing"
    trade.trailing_stop_config["high_water_mark"] = 104.0
    trade.trailing_stop_config["current_stop"] = 100.0
    trade.trailing_stop_config["trail_pct"] = 0.02

    mgr._update_trail_position(trade)

    cfg = trade.trailing_stop_config
    # 105 * (1 - 0.02) = 102.90 — legacy ATR/% trail engaged.
    assert cfg["current_stop"] == 102.90
    last_adj = cfg["stop_adjustments"][-1]
    assert last_adj["reason"] == "trail_up"


@patch("services.smart_levels_service.compute_trailing_stop_snap")
def test_stop_manager_trail_uses_snap_when_available(mock_snap):
    """When trail tick has a qualifying HVN, manager anchors to it
    instead of the fixed-% trail."""
    from services.stop_manager import StopManager

    # Snap suggests a stop slightly higher than the 2%-trail (102.90).
    mock_snap.return_value = {
        "stop": 103.40, "snapped": True, "reason": "snapped_to_hvn_below",
        "level_kind": "HVN", "level_price": 103.50,
        "level_strength": 0.70, "original_stop": 102.90,
    }

    mgr = StopManager()
    mgr.set_db(MagicMock())
    trade = _make_trade(direction="long")
    trade.current_price = 105.0
    trade.trailing_stop_config["mode"] = "trailing"
    trade.trailing_stop_config["high_water_mark"] = 104.0
    trade.trailing_stop_config["current_stop"] = 100.0
    trade.trailing_stop_config["trail_pct"] = 0.02

    mgr._update_trail_position(trade)

    cfg = trade.trailing_stop_config
    assert cfg["current_stop"] == 103.40
    last_adj = cfg["stop_adjustments"][-1]
    assert last_adj["reason"] == "trail_up_hvn_snap"


@patch("services.smart_levels_service.compute_trailing_stop_snap",
       side_effect=RuntimeError("smart_levels imploded"))
def test_stop_manager_swallows_snap_exceptions(mock_snap):
    """A bug inside `compute_trailing_stop_snap` must NOT take down a
    breakeven move. Manager must fall back to legacy behaviour."""
    from services.stop_manager import StopManager

    mgr = StopManager()
    mgr.set_db(MagicMock())
    trade = _make_trade(direction="long")

    mgr._move_stop_to_breakeven(trade)

    cfg = trade.trailing_stop_config
    # Legacy breakeven happened despite the snap error.
    assert cfg["mode"] == "breakeven"
    assert cfg["current_stop"] == 100.0
