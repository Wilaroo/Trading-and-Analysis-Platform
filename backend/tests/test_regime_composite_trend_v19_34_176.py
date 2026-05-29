"""
v19.34.176 — Market-regime TREND block composite (SPY/QQQ/IWM) + tolerance.

Covers:
  • ±0.25% tolerance band scoring (`_band_points`).
  • Per-index scoring + graceful None on insufficient data.
  • Weighted blend across available indexes (renormalized).
  • Divergence flag when indexes disagree (bull vs bear).
  • The "SPY downtrend hallucination" fix: a marginally-soft SPY no longer
    drags the composite bearish when QQQ/IWM are strong.
  • SPY-missing → neutral 50 fallback.
"""
import asyncio

from services.market_regime_engine import TrendSignalBlock


def _bars(values):
    return [{"close": v, "high": v + 0.1, "low": v - 0.1} for v in values]


def _uptrend(n=200, start=100.0, step=0.5):
    return _bars([start + i * step for i in range(n)])


def _downtrend(n=200, start=200.0, step=0.5):
    return _bars([start - i * step for i in range(n)])


def _flat(n=200, val=100.0):
    return _bars([val] * n)


def test_band_points_tolerance():
    blk = TrendSignalBlock()
    # clearly above (>0.25%)
    assert blk._band_points(101.0, 100.0, 20) == 20
    # clearly below
    assert blk._band_points(99.0, 100.0, 20) == 0
    # inside the ±0.25% band → half credit (neutral)
    assert blk._band_points(100.1, 100.0, 20) == 10
    assert blk._band_points(99.9, 100.0, 20) == 10
    # zero/invalid level guard
    assert blk._band_points(100.0, 0.0, 20) == 0


def test_score_index_insufficient_data_returns_none():
    blk = TrendSignalBlock()
    assert blk._score_index(_uptrend(n=50)) is None
    assert blk._score_index(None) is None


def test_score_index_uptrend_high_downtrend_low():
    blk = TrendSignalBlock()
    up = blk._score_index(_uptrend())
    dn = blk._score_index(_downtrend())
    assert up is not None and dn is not None
    assert up["score"] >= 90       # strong bull
    assert dn["score"] <= 10       # strong bear


def test_flat_series_is_neutral():
    blk = TrendSignalBlock()
    flat = blk._score_index(_flat())
    # price == all MAs → tolerance half-credit everywhere; flat structure = 50
    assert 45 <= flat["score"] <= 55


def test_composite_blend_weights():
    blk = TrendSignalBlock()
    # spy bull(100) * .5 + qqq bull(100) * .3 + iwm bear(0) * .2 = 80
    score = asyncio.run(blk.calculate(_uptrend(), _uptrend(), _downtrend()))
    assert 78 <= score <= 82
    assert blk.signals["divergence_flag"] is True
    assert set(blk.signals["indexes_used"]) == {"spy", "qqq", "iwm"}


def test_spy_downtrend_hallucination_fixed():
    blk = TrendSignalBlock()
    # SPY only marginally soft (flat ~ neutral 50) but QQQ + IWM strongly bull.
    # Pre-fix (SPY-only) this could print bearish; composite must NOT.
    score = asyncio.run(blk.calculate(_flat(), _uptrend(), _uptrend()))
    # 50*.5 + 100*.3 + 100*.2 = 75 → clearly not a downtrend
    assert score >= 60
    assert blk.signals["trend_direction"] in ("BULLISH", "NEUTRAL")


def test_spy_only_fallback_when_others_missing():
    blk = TrendSignalBlock()
    score = asyncio.run(blk.calculate(_uptrend(), None, None))
    assert score >= 90
    assert blk.signals["indexes_used"] == ["spy"]
    assert blk.signals["divergence_flag"] is False


def test_missing_spy_is_neutral():
    blk = TrendSignalBlock()
    score = asyncio.run(blk.calculate(_uptrend(n=10), _uptrend(), _uptrend()))
    assert score == 50
    assert "error" in blk.signals
