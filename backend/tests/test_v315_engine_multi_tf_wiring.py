"""
v315 — Engine wiring smoke test for _calculate_multi_tf.
Injects synthetic bars (daily uptrend + intraday downtrend) via method override
and asserts the engine assembles PULLBACK_IN_UPTREND with long=normal.
"""
import asyncio

from services.market_regime_engine import MarketRegimeEngine


def _ramp(start, step, n, vol=1000):
    bars, px = [], start
    for _ in range(n):
        o, c = px, px + step
        hi = max(o, c) + abs(step) * 0.2
        lo = min(o, c) - abs(step) * 0.2
        bars.append({"open": o, "high": hi, "low": lo, "close": c, "volume": vol})
        px = c
    return bars


def test_engine_calculate_multi_tf_pullback():
    eng = MarketRegimeEngine(db=None)
    up_daily = _ramp(100, 0.5, 220)      # daily uptrend
    dn_intraday = _ramp(120, -0.3, 80)   # intraday selloff

    async def fake_tf(symbol, bar_size, limit=120):
        return up_daily if bar_size == "1 day" else dn_intraday

    eng._get_tf_bars = fake_tf

    out = asyncio.run(eng._calculate_multi_tf())
    assert out["context"] == "PULLBACK_IN_UPTREND", out
    assert out["lanes"]["long"]["bias"] == "UP"
    assert out["intraday_bias"] == "DOWN"
    assert out["modes"]["long"] == "normal"
    assert out["modes"]["short"] == "cautious"


def test_engine_multi_tf_degrades_without_intraday():
    """No intraday bars → context falls back to the daily anchor (ALIGNED_UP)."""
    eng = MarketRegimeEngine(db=None)
    up_daily = _ramp(100, 0.5, 220)

    async def fake_tf(symbol, bar_size, limit=120):
        return up_daily if bar_size == "1 day" else []  # nothing intraday yet

    eng._get_tf_bars = fake_tf

    out = asyncio.run(eng._calculate_multi_tf())
    assert out["context"] == "ALIGNED_UP", out
    assert out["modes"]["long"] in ("normal", "aggressive")
