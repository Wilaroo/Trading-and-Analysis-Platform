"""
test_v19_34_221_ma_stack_alignment.py

Validates v19.34.221 — the Technical pillar derives ma_stack from the EMA
ALIGNMENT (EMA9>EMA20>EMA50, price above EMA50) instead of the conservative
intraday `trend`, so a consolidating name inside a clean stack reads bullish/
bearish instead of pinning neutral.
"""
import asyncio
import importlib

tq = importlib.import_module("services.tqs.technical_quality")


class _Snap:
    def __init__(self, e9, e20, e50, px, trend="sideways"):
        self.ema_9, self.ema_20, self.ema_50 = e9, e20, e50
        self.current_price = px
        self.trend = trend
        # other fields read by the pillar
        self.rsi_14 = 55.0
        self.atr_percent = 2.0
        self.rvol = 1.5
        self.dist_from_vwap = 0.3
        self.support = px * 0.97
        self.resistance = px * 1.03
        self.squeeze_on = False


class _TechSvc:
    def __init__(self, snap):
        self._snap = snap

    async def get_technical_snapshot(self, symbol):
        return self._snap


def _ma_stack(snap, direction="long"):
    svc = tq.TechnicalQualityService()
    svc.set_services(technical_service=_TechSvc(snap))
    r = asyncio.new_event_loop().run_until_complete(
        svc.calculate_score(symbol="AAA", direction=direction)
    )
    return r.ma_stack


def test_bullish_stack_even_in_consolidation():
    # EMA9>EMA20>EMA50, price sits between EMA9 and EMA20 (intraday pullback)
    # but still above EMA50 → BULLISH stack (trend itself is "sideways").
    snap = _Snap(e9=101, e20=100, e50=98, px=100.5, trend="sideways")
    assert _ma_stack(snap) == "bullish"


def test_bearish_stack():
    snap = _Snap(e9=98, e20=100, e50=102, px=99, trend="sideways")
    assert _ma_stack(snap) == "bearish"


def test_neutral_when_emas_tangled():
    # EMAs not cleanly aligned → neutral
    snap = _Snap(e9=100, e20=101, e50=100.5, px=100.2)
    assert _ma_stack(snap) == "neutral"


def test_bullish_alignment_but_price_below_anchor_is_neutral():
    # stacked EMAs but price has fallen below EMA50 → not a clean bullish stack
    snap = _Snap(e9=101, e20=100, e50=98, px=97)
    assert _ma_stack(snap) == "neutral"


def test_fallback_to_trend_when_emas_missing():
    snap = _Snap(e9=0, e20=0, e50=0, px=100, trend="uptrend")
    assert _ma_stack(snap) == "bullish"
