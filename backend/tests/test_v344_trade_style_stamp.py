"""v19.34.326 (v344) — persisted trade_style stamp uses the canonical resolver.

Run on the DGX after applying patch_v344_trade_style_stamp.py:
    PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_v344_trade_style_stamp.py -q

Guards that OpportunityEvaluator._resolve_geometry_style (now the BotTrade stamp source)
maps the legacy generic 'trade_2_hold' to the real setup-derived horizon, passes real
styles through, and falls back to 'intraday' on unknown (same horizon the old literal
default resolved to — so no behavioural regression for genuinely unknown setups).
"""
from services.opportunity_evaluator import OpportunityEvaluator as OE


def test_generic_defers_to_scalp_setup():
    assert OE._resolve_geometry_style({"trade_style": "trade_2_hold"}, "rubber_band") == "scalp"
    assert OE._resolve_geometry_style({"trade_style": "trade_2_hold"}, "vwap_fade") == "scalp"


def test_generic_defers_to_higher_tier_setup():
    assert OE._resolve_geometry_style({"trade_style": "trade_2_hold"}, "daily_breakout") == "multi_day"
    assert OE._resolve_geometry_style({"trade_style": "trade_2_hold"}, "accumulation_entry") == "swing"


def test_missing_style_intraday_setup():
    assert OE._resolve_geometry_style({}, "squeeze") == "intraday"
    assert OE._resolve_geometry_style({}, "orb") == "intraday"


def test_real_style_passes_through():
    assert OE._resolve_geometry_style({"trade_style": "scalp"}, "gap_fade") == "scalp"


def test_unknown_falls_back_to_intraday():
    # same horizon the legacy literal 'trade_2_hold' default resolved to → no regression
    assert OE._resolve_geometry_style({}, "totally_unknown_setup") == "intraday"
