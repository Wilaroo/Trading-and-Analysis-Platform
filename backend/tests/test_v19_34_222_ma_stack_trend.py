"""
test_v19_34_222_ma_stack_trend.py — self-contained (no DGX-only deps).

After reverting the v221 EMA-alignment attempt, ma_stack is again derived from
the snapshot's intraday `trend` (uptrend→bullish / downtrend→bearish / else
neutral). This locks that behavior in.
"""
import asyncio
import importlib

tq = importlib.import_module("services.tqs.technical_quality")


class _Snap:
    def __init__(self, trend):
        self.trend = trend
        self.ema_9 = 101.0
        self.ema_20 = 100.0
        self.ema_50 = 98.0
        self.current_price = 100.5
        self.rsi_14 = 55.0
        self.atr_percent = 2.0
        self.rvol = 1.5
        self.dist_from_vwap = 0.3
        self.support = 97.0
        self.resistance = 103.0
        self.squeeze_on = False


class _TechSvc:
    def __init__(self, snap):
        self._snap = snap

    async def get_technical_snapshot(self, symbol):
        return self._snap


def _ma_stack(trend):
    svc = tq.TechnicalQualityService()
    svc.set_services(technical_service=_TechSvc(_Snap(trend)))
    r = asyncio.new_event_loop().run_until_complete(
        svc.calculate_score(symbol="AAA", direction="long")
    )
    return r.ma_stack


def test_uptrend_bullish():
    assert _ma_stack("uptrend") == "bullish"


def test_downtrend_bearish():
    assert _ma_stack("downtrend") == "bearish"


def test_sideways_neutral():
    assert _ma_stack("sideways") == "neutral"


def test_unknown_neutral():
    # ema alignment must NOT override trend (the reverted, single-timeframe rule)
    assert _ma_stack("") == "neutral"
