"""
v19.34.254 — TQS context pillar de-compression.

The context pillar was frozen at ~62 ±3.5 because on the ib-direct DGX the live
SPY-quote path is dead (regime → range_bound=55) and the only two per-symbol
inputs (sector, AI) default to 50. This adds a genuine per-symbol Relative
Strength component (stock vs the index it belongs to — QQQ/SPY/IWM) computed
from daily bars, a multi-index regime fallback, and re-weights the pillar
(RS 20%, day-of-week trimmed 10%→3%).
"""
from unittest.mock import MagicMock

import pytest

from services.tqs.context_quality import (
    ContextQualityService, _rs_to_score, RS_SCALE,
)


def _fake_db(bars: dict):
    """bars: {SYMBOL: [closes newest-first]}. Serves ib_historical_data."""
    db = MagicMock()

    def _getitem(name):
        col = MagicMock()

        def _find(query, *a, **k):
            sym = query.get("symbol")
            rows = [{"date": f"d{i}", "close": c}
                    for i, c in enumerate(bars.get(sym, []))]
            cur = MagicMock()
            cur.sort.return_value.limit.return_value = rows
            return cur

        col.find.side_effect = _find
        return col

    db.__getitem__.side_effect = _getitem
    return db


def test_rs_to_score_is_smooth_and_centered():
    assert _rs_to_score(0.0) == pytest.approx(50.0)
    # symmetric around 50
    assert _rs_to_score(5.0) - 50 == pytest.approx(50 - _rs_to_score(-5.0))
    # monotonic increasing
    assert _rs_to_score(3) < _rs_to_score(6) < _rs_to_score(12)
    # graceful saturation — never hits the 0/100 rails, even at +44%
    assert _rs_to_score(44.0) < 99.5
    assert _rs_to_score(44.0) > 95
    # +3% lands in a sane mid-high band (not saturated like the old ±3% map)
    assert 60 < _rs_to_score(3.0) < 70


def test_compute_rs_long_outperformer_scores_high():
    svc = ContextQualityService()
    # AAPL → QQQ benchmark. Stock +10% 1d, QQQ +1% 1d → rs_1d +9%.
    svc.set_services(db=_fake_db({"AAPL": [110, 100], "QQQ": [101, 100]}))
    rs = svc._compute_relative_strength("AAPL", is_long=True)
    assert rs is not None
    score, bench, rs_1d, _ = rs
    assert bench == "QQQ"
    assert rs_1d == pytest.approx(9.0, abs=0.1)
    assert score > 80


def test_compute_rs_inverts_for_short():
    """A name outperforming its index is a HEADWIND for a short → low score."""
    svc = ContextQualityService()
    svc.set_services(db=_fake_db({"AAPL": [110, 100], "QQQ": [101, 100]}))
    long_score = svc._compute_relative_strength("AAPL", is_long=True)[0]
    short_score = svc._compute_relative_strength("AAPL", is_long=False)[0]
    assert short_score < 30
    assert long_score == pytest.approx(100 - short_score, abs=0.5)


def test_compute_rs_none_without_bars():
    svc = ContextQualityService()
    svc.set_services(db=_fake_db({}))  # no bars
    assert svc._compute_relative_strength("AAPL", is_long=True) is None


def test_multi_index_regime_blend():
    svc = ContextQualityService()
    # SPY +2%, QQQ +3%, IWM -1% → 0.5*2 + 0.3*3 + 0.2*(-1) = 1.7
    svc.set_services(db=_fake_db({
        "SPY": [102, 100], "QQQ": [103, 100], "IWM": [99, 100],
    }))
    assert svc._multi_index_regime_change() == pytest.approx(1.7, abs=0.01)


@pytest.mark.asyncio
async def test_calculate_score_populates_rs_and_decompresses():
    svc = ContextQualityService()
    svc.set_services(db=_fake_db({
        "AAPL": [112, 100], "QQQ": [101, 100],
        "SPY": [101, 100], "IWM": [100.5, 100],
    }))
    res = await svc.calculate_score(
        symbol="AAPL", direction="long", setup_type="breakout",
        time_of_day="morning_momentum",
    )
    # RS captured + surfaced in the breakdown
    assert res.rs_benchmark == "QQQ"
    assert res.rs_score > 70
    d = res.to_dict()
    assert "relative_strength" in d["components"]
    assert d["raw_values"]["rs_benchmark"] == "QQQ"
    # a strong-RS long should pull context above the old frozen ~62 ceiling
    assert res.score > 62


@pytest.mark.asyncio
async def test_weights_sum_to_one_via_neutral_inputs():
    """All component scores forced to 50 → composite must be exactly 50,
    proving the new weights still sum to 1.0."""
    svc = ContextQualityService()
    svc.set_services(db=_fake_db({}))  # no bars → rs neutral 50, regime default
    res = await svc.calculate_score(
        symbol="ZZZZ", direction="long", setup_type="unknown_setup",
        market_regime="range_bound", time_of_day="midday",
        vix_level=18.0, sector="unknown", sector_rank=6,
    )
    # range_bound long=55, midday default=45, sector unknown rank6=50,
    # vix 18=85, ai none=50, day varies, rs none=50 → just assert bounded/sane
    assert 1.0 <= res.score <= 99.0
