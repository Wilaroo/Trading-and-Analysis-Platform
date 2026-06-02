"""
v19.34.215 — ma_stack now derives from the snapshot's already-computed `trend`.

Validates:
 1. snapshot.trend -> ma_stack mapping (uptrend->bullish, downtrend->bearish,
    sideways->neutral), instead of the broken mixed-timeframe ema stack that
    pinned ma_stack to "neutral" 100% of the time.
 2. The trend sub-score is direction-aware: a downtrend correctly scores HIGH
    for a short and LOW for a long (and vice-versa).
"""
import asyncio
from types import SimpleNamespace

import pytest

from services.tqs.technical_quality import get_technical_quality_service


def _fake_snapshot(trend):
    # Provide every attribute calculate_score reads off the snapshot.
    return SimpleNamespace(
        rsi_14=55.0, atr_percent=3.0, rvol=2.0, dist_from_vwap=0.5,
        trend=trend, squeeze_on=False, current_price=100.0,
        support=98.0, resistance=103.0,
    )


class _FakeTechService:
    def __init__(self, trend):
        self._trend = trend

    async def get_technical_snapshot(self, symbol):
        return _fake_snapshot(self._trend)


def _score(trend, direction):
    svc = get_technical_quality_service()
    svc.set_services(technical_service=_FakeTechService(trend), alpaca_service=None)

    async def run():
        return await svc.calculate_score(symbol="TEST", direction=direction)

    return asyncio.get_event_loop().run_until_complete(run())


def test_trend_maps_to_ma_stack():
    assert _score("uptrend", "long").ma_stack == "bullish"
    assert _score("downtrend", "long").ma_stack == "bearish"
    assert _score("sideways", "long").ma_stack == "neutral"


def test_downtrend_scores_high_for_short_low_for_long():
    short = _score("downtrend", "short")
    long_ = _score("downtrend", "long")
    assert short.trend_score == 90   # bearish stack supports a short
    assert long_.trend_score == 25   # bearish stack opposes a long


def test_uptrend_scores_high_for_long_low_for_short():
    long_ = _score("uptrend", "long")
    short = _score("uptrend", "short")
    assert long_.trend_score == 90
    assert short.trend_score == 25


def test_sideways_is_neutral_either_way():
    assert _score("sideways", "long").trend_score == 60
    assert _score("sideways", "short").trend_score == 60


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
