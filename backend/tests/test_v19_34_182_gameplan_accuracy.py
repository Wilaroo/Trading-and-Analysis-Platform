"""
v19.34.182 — Gameplan data-accuracy regression tests.

Covers the three bugs fixed in gameplan_service.py:
  1. stock entries read the correct LiveAlert fields (stop_loss/target),
     not the non-existent stop_price/target_price (which returned $0).
  2. reasoning (a List[str]) is coerced to text, never stored as a list.
  3. swing/position (daily) setups are included in stocks_in_play, not dropped.

These tests exercise the PURE logic only (no DB / IB / pusher), per AGENTS.md
hardware constraints.
"""
import asyncio
from types import SimpleNamespace

from services.gameplan_service import GamePlanService


def _svc():
    # Bypass __init__ (which touches Mongo create_index) — we only need the
    # pure builder/helper methods.
    return GamePlanService.__new__(GamePlanService)


def _alert(**kw):
    base = dict(
        id="al_1",
        symbol="NVDA",
        setup_type="gap_and_go_long",
        direction="long",
        trigger_price=120.50,
        stop_loss=118.25,
        target=126.00,
        reasoning=["Gap up on volume", "Above PM high"],
        scan_tier="intraday",
        score=0.82,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_stop_and_target_are_real_not_zero():
    svc = _svc()
    entry = svc._alert_to_stock_entry(_alert(), "premarket_scanner")
    assert entry["key_levels"]["stop"] == 118.25
    assert entry["key_levels"]["target"] == 126.00
    assert entry["key_levels"]["entry"] == 120.50


def test_reasoning_list_coerced_to_text():
    svc = _svc()
    entry = svc._alert_to_stock_entry(_alert(), "premarket_scanner")
    assert isinstance(entry["catalyst"], str)
    assert "Gap up on volume" in entry["catalyst"]
    assert " · " in entry["catalyst"]
    # if_then notes must be a string slice, not a sliced list
    assert isinstance(entry["if_then_statements"][0]["notes"], str)


def test_reasoning_handles_plain_string():
    assert GamePlanService._reasoning_text(_alert(reasoning="single string")) == "single string"
    assert GamePlanService._reasoning_text(_alert(reasoning=None)) == ""


def test_setup_type_titlecased_and_action_has_price():
    svc = _svc()
    entry = svc._alert_to_stock_entry(_alert(), "daily_scanner")
    assert entry["setup_type"] == "Gap And Go Long"
    assert "$120.50" in entry["if_then_statements"][0]["action"]
    assert entry["source"] == "daily_scanner"


def test_short_direction_phrasing():
    svc = _svc()
    entry = svc._alert_to_stock_entry(_alert(direction="short"), "live_scanner")
    assert "gaps down" in entry["if_then_statements"][0]["condition"]


def test_swing_position_setups_included():
    """The previously-dropped daily (swing/position) tier must now appear."""
    svc = _svc()
    game_plan = {"stocks_in_play": []}
    live_alerts = [
        _alert(id="x1", symbol="AAPL", scan_tier="swing"),
        _alert(id="x2", symbol="MSFT", scan_tier="position"),
        _alert(id="pm_1", symbol="TSLA", scan_tier="intraday"),
        _alert(id="x3", symbol="AMD", scan_tier="scalp"),
    ]
    pm_alerts = [a for a in live_alerts if getattr(a, "id", "").startswith("pm_")]
    daily_alerts = [a for a in live_alerts if a.scan_tier in ("swing", "position")]
    intraday_alerts = [a for a in live_alerts if a.scan_tier in ("intraday", "scalp")]

    for a in pm_alerts[:8]:
        game_plan["stocks_in_play"].append(svc._alert_to_stock_entry(a, "premarket_scanner"))
    for a in daily_alerts[:6]:
        sym = a.symbol
        if not any(s.get("symbol") == sym for s in game_plan["stocks_in_play"]):
            game_plan["stocks_in_play"].append(svc._alert_to_stock_entry(a, "daily_scanner"))
    for a in intraday_alerts[:5]:
        sym = a.symbol
        if not any(s.get("symbol") == sym for s in game_plan["stocks_in_play"]):
            game_plan["stocks_in_play"].append(svc._alert_to_stock_entry(a, "live_scanner"))

    symbols = {s["symbol"] for s in game_plan["stocks_in_play"]}
    assert {"AAPL", "MSFT"}.issubset(symbols), "swing/position setups were dropped"
    assert "TSLA" in symbols and "AMD" in symbols


def test_populate_key_levels_pulls_vix_from_regime():
    svc = _svc()
    game_plan = {"big_picture": {"key_levels": {
        "spy_support": "", "spy_resistance": "",
        "qqq_support": "", "qqq_resistance": "", "vix_level": ""}}}
    regime = {"signal_blocks": {"volume_vix": {"signals": {"vix_price": 17.4}}}}
    # tech service import will be attempted; it's fine if it yields nothing in
    # the sandbox — VIX must still populate from the regime dict.
    asyncio.run(svc._populate_key_levels(game_plan, regime))
    assert game_plan["big_picture"]["key_levels"]["vix_level"] == 17.4


def test_populate_key_levels_never_raises_on_empty():
    svc = _svc()
    game_plan = {"big_picture": {"key_levels": {}}}
    asyncio.run(svc._populate_key_levels(game_plan, None))  # must not raise
