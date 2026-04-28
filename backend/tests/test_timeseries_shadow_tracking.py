"""
Tests for the timeseries_ai shadow-tracking wiring.

Operator scenario 2026-04-29: `/shadow/performance` showed
`timeseries_ai: 0 decisions` despite the module firing on every
consultation. Root cause: when `ai_forecast.usable=False` (low
confidence) or when the forecast was consumed by the debate path,
the consultation never set `result["timeseries_forecast"]`, so
`log_decision` received `None` and didn't tag `timeseries_ai` in
`modules_used`.

Tests below verify the post-fix wiring:

- A *usable* forecast tags `timeseries_ai` (legacy behaviour).
- An *unusable* forecast (low confidence) still tags `timeseries_ai`
  with `consulted_but_unusable=True`.
- A forecast consumed by the debate but absent from `result` still
  tags `timeseries_ai`.
- No forecast at all → no `timeseries_ai` tag.
"""

from unittest.mock import AsyncMock

import pytest

from services.ai_modules.shadow_tracker import ShadowTracker


@pytest.mark.asyncio
async def test_log_decision_tags_timeseries_ai_for_usable_forecast():
    """Legacy: a fully-usable forecast tags `timeseries_ai`."""
    tracker = ShadowTracker()
    tracker._decisions_col = AsyncMock()
    tracker._decisions_col.insert_one = lambda doc: None

    decision = await tracker.log_decision(
        symbol="AAPL",
        trigger_type="trade_opportunity",
        price_at_decision=100.0,
        debate_result={"winner": "bull"},
        risk_assessment={"recommendation": "approve"},
        institutional_context={"flow": "bullish"},
        timeseries_forecast={"forecast": {"direction": "up", "confidence": 0.75, "usable": True}},
    )

    assert "timeseries_ai" in decision.modules_used


@pytest.mark.asyncio
async def test_log_decision_tags_timeseries_ai_for_unusable_forecast():
    """Post-fix: a low-confidence forecast (consulted but not usable)
    still tags `timeseries_ai` so the abstention is credited."""
    tracker = ShadowTracker()
    tracker._decisions_col = AsyncMock()
    tracker._decisions_col.insert_one = lambda doc: None

    # Sentinel payload built by trade_consultation when usable=False.
    consulted_but_unusable_payload = {
        "forecast": {"direction": "neutral", "confidence": 0.30, "usable": False},
        "context": None,
        "consulted_but_unusable": True,
        "consumed_by_debate": False,
    }

    decision = await tracker.log_decision(
        symbol="AAPL",
        trigger_type="trade_opportunity",
        price_at_decision=100.0,
        debate_result={"winner": "bull"},
        risk_assessment={"recommendation": "approve"},
        institutional_context={"flow": "bullish"},
        timeseries_forecast=consulted_but_unusable_payload,
    )

    assert "timeseries_ai" in decision.modules_used
    # The full payload is preserved so downstream analytics can
    # distinguish "abstained" from "actively contributed".
    assert decision.timeseries_forecast["consulted_but_unusable"] is True


@pytest.mark.asyncio
async def test_log_decision_tags_timeseries_ai_for_debate_consumed_forecast():
    """Post-fix: when debate consumed the forecast, the sentinel
    payload still tags `timeseries_ai` (so it shares credit with the
    debate verdict)."""
    tracker = ShadowTracker()
    tracker._decisions_col = AsyncMock()
    tracker._decisions_col.insert_one = lambda doc: None

    consumed_by_debate_payload = {
        "forecast": {"direction": "up", "confidence": 0.65, "usable": True},
        "context": None,
        "consulted_but_unusable": False,
        "consumed_by_debate": True,
    }

    decision = await tracker.log_decision(
        symbol="AAPL",
        trigger_type="trade_opportunity",
        price_at_decision=100.0,
        debate_result={"winner": "bull", "ai_forecast_used": True},
        risk_assessment={"recommendation": "approve"},
        institutional_context={"flow": "bullish"},
        timeseries_forecast=consumed_by_debate_payload,
    )

    # Both modules get credit — debate as the primary verdict, TS as
    # a contributing input.
    assert "debate_agents" in decision.modules_used
    assert "timeseries_ai" in decision.modules_used
    assert decision.timeseries_forecast["consumed_by_debate"] is True


@pytest.mark.asyncio
async def test_log_decision_does_not_tag_timeseries_ai_when_no_forecast():
    """If the forecast wasn't fetched at all (TS disabled or
    no bars), `timeseries_ai` must NOT appear in modules_used —
    don't credit a module for a decision it had no input on."""
    tracker = ShadowTracker()
    tracker._decisions_col = AsyncMock()
    tracker._decisions_col.insert_one = lambda doc: None

    decision = await tracker.log_decision(
        symbol="AAPL",
        trigger_type="trade_opportunity",
        price_at_decision=100.0,
        debate_result={"winner": "bull"},
        risk_assessment={"recommendation": "approve"},
        institutional_context={"flow": "bullish"},
        timeseries_forecast=None,
    )

    assert "timeseries_ai" not in decision.modules_used
    assert "debate_agents" in decision.modules_used  # Other modules unaffected


@pytest.mark.asyncio
async def test_log_decision_does_not_tag_timeseries_ai_for_empty_dict():
    """`{}` is falsy in Python — defensive check ensures empty payloads
    don't accidentally tag the module. Important because some code
    paths historically passed `{}` instead of `None`."""
    tracker = ShadowTracker()
    tracker._decisions_col = AsyncMock()
    tracker._decisions_col.insert_one = lambda doc: None

    decision = await tracker.log_decision(
        symbol="AAPL",
        trigger_type="trade_opportunity",
        price_at_decision=100.0,
        debate_result={"winner": "bull"},
        risk_assessment={"recommendation": "approve"},
        institutional_context={"flow": "bullish"},
        timeseries_forecast={},
    )

    assert "timeseries_ai" not in decision.modules_used
