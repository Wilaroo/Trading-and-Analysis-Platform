"""Offline unit tests for v19.34.157 (P3-C) mean-reversion metrics.

Verifies:
  • Setup-family classification (MR / momentum / breakout / unknown).
  • `_hurst_rs` recognizes white noise (~0.5), trending (>0.55),
    anti-persistent (<0.45) synthetic series.
  • `_half_life_ar1` returns finite half-life for an AR(1) MR process,
    None for a random walk / pure trend.
  • `_classify_regime` composes hurst + half_life into the right tag.
  • `get_mr_multiplier` returns the correct lookup-table value for
    every (family, regime) combo + neutral fallbacks for unknowns.

NO network / Mongo / IB required — all tests run on synthetic data.

Run:
    cd /app/backend && PYTHONPATH=. python3 -m pytest \
        tests/test_mean_reversion_metrics.py -v
"""
from __future__ import annotations

import math
import os
import sys
from typing import List

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ── Synthetic price-series generators ───────────────────────────────


def _white_noise(n: int = 400, seed: int = 42) -> List[float]:
    """Random walk → Hurst ≈ 0.5, no MR (β ≈ 0 in AR(1))."""
    import numpy as np
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1.0, n)
    return list(100.0 + np.cumsum(steps))


def _trending(n: int = 400, persistence: float = 0.4, sigma: float = 0.005,
              seed: int = 1) -> List[float]:
    """Persistent/momentum series — AR(1) on RETURNS with positive ρ.

    Linear drift + i.i.d. noise produces near-constant returns and a
    LOW R/S Hurst (R/S measures persistence in the RETURN series, not
    the price level). To produce a series with H > 0.55 we need
    positively autocorrelated returns: each return inherits a fraction
    `persistence` of the previous return plus fresh noise. That's the
    statistical signature of a momentum regime, which is what we want
    to bias for here.
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    returns = [0.0]
    for _ in range(n - 1):
        returns.append(persistence * returns[-1] + rng.normal(0, sigma))
    prices = [100.0]
    for r in returns[1:]:
        prices.append(prices[-1] * (1.0 + r))
    return prices


def _mean_reverting(n: int = 400, theta: float = 0.15, mu: float = 100.0,
                    sigma: float = 0.8, seed: int = 7) -> List[float]:
    """Ornstein-Uhlenbeck (AR(1) with negative β):
        x_{t+1} = x_t + θ(μ - x_t) + ε
    Strong MR → Hurst < 0.45, finite short half-life.
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    x = [mu]
    for _ in range(n - 1):
        eps = rng.normal(0, sigma)
        x.append(x[-1] + theta * (mu - x[-1]) + eps)
    return x


# ── Setup-family classification ─────────────────────────────────────


@pytest.mark.parametrize("setup,expected", [
    ("rubber_band_scalp_long", "mean_reversion"),
    ("rubber_band_scalp_short", "mean_reversion"),
    ("vwap_reclaim_long", "mean_reversion"),
    ("mean_reversion", "mean_reversion"),
    ("vwap_fade", "mean_reversion"),
    ("gap_and_go", "momentum"),
    ("momentum_continuation", "momentum"),
    ("short_squeeze_intraday", "momentum"),
    ("short_squeeze_swing", "momentum"),
    ("vwap_continuation", "momentum"),
    ("breakout_scalp", "breakout"),
    ("breakout_swing", "breakout"),
    ("hod_breakout", "breakout"),
    ("first_vwap_pullback", "breakout"),
    ("something_new", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
    (42, "unknown"),  # Non-string
])
def test_classify_setup_family(setup, expected):
    from services.mean_reversion_metrics import classify_setup_family
    assert classify_setup_family(setup) == expected


# ── Hurst exponent on synthetic series ──────────────────────────────


def test_hurst_white_noise_near_half():
    """Random walk → Hurst should land in ~[0.40, 0.60]."""
    from services.mean_reversion_metrics import _hurst_rs
    h = _hurst_rs(_white_noise(n=500))
    assert h is not None
    assert 0.30 <= h <= 0.70, f"white noise Hurst={h}"


def test_hurst_trending_series_above_half():
    """Strong positive autocorrelation in returns → Hurst > 0.55."""
    from services.mean_reversion_metrics import _hurst_rs
    h = _hurst_rs(_trending(n=500, persistence=0.5))
    assert h is not None
    assert h > 0.55, f"trending Hurst={h}"


def test_hurst_mean_reverting_below_half():
    """Strong OU MR → Hurst should be < 0.45."""
    from services.mean_reversion_metrics import _hurst_rs
    h = _hurst_rs(_mean_reverting(n=500, theta=0.20))
    assert h is not None
    assert h < 0.45, f"MR Hurst={h}"


def test_hurst_short_series_returns_none():
    from services.mean_reversion_metrics import _hurst_rs
    assert _hurst_rs([100.0] * 40) is None
    assert _hurst_rs([]) is None


def test_hurst_zero_variance_returns_none():
    from services.mean_reversion_metrics import _hurst_rs
    assert _hurst_rs([100.0] * 100) is None


# ── Half-life via AR(1) ─────────────────────────────────────────────


def test_half_life_mean_reverting_returns_finite():
    """OU process with θ=0.15 → expected half-life ≈ ln(2)/θ ≈ 4.6 bars."""
    from services.mean_reversion_metrics import _half_life_ar1
    hl = _half_life_ar1(_mean_reverting(n=500, theta=0.15))
    assert hl is not None
    assert 1.0 < hl < 30.0, f"half_life={hl}"


def test_half_life_trending_returns_none():
    """Pure trend → β ≥ 0 → no MR → None."""
    from services.mean_reversion_metrics import _half_life_ar1
    hl = _half_life_ar1(_trending(n=400, persistence=0.5))
    assert hl is None, f"expected None for trend, got {hl}"


def test_half_life_short_series_returns_none():
    from services.mean_reversion_metrics import _half_life_ar1
    assert _half_life_ar1([100.0, 101.0, 99.0]) is None


# ── Regime classifier ───────────────────────────────────────────────


def test_classify_regime_strong_mr():
    from services.mean_reversion_metrics import _classify_regime
    tag, score, reason = _classify_regime(0.42, 8.0)
    assert tag == "MR_STRONG"
    assert 0.7 <= score <= 1.0
    assert "0.42" in reason


def test_classify_regime_trending():
    from services.mean_reversion_metrics import _classify_regime
    tag, _score, reason = _classify_regime(0.62, None)
    assert tag == "TRENDING"
    assert "0.62" in reason


def test_classify_regime_weak_mr_on_hurst_only():
    from services.mean_reversion_metrics import _classify_regime
    tag, _score, _reason = _classify_regime(0.47, None)
    assert tag == "MR_WEAK"


def test_classify_regime_weak_mr_on_medium_half_life():
    from services.mean_reversion_metrics import _classify_regime
    tag, _score, _reason = _classify_regime(0.52, 35.0)
    assert tag == "MR_WEAK"


def test_classify_regime_neutral():
    from services.mean_reversion_metrics import _classify_regime
    tag, score, _reason = _classify_regime(0.52, None)
    assert tag == "NEUTRAL"
    assert score == 0.5


def test_classify_regime_none_inputs_neutral():
    from services.mean_reversion_metrics import _classify_regime
    tag, _score, _reason = _classify_regime(None, None)
    assert tag == "NEUTRAL"


# ── Multiplier lookup table ─────────────────────────────────────────


@pytest.mark.parametrize("setup,regime,expected_mult", [
    # MR family
    ("mean_reversion", "MR_STRONG", 1.3),
    ("mean_reversion", "MR_WEAK",   1.1),
    ("mean_reversion", "NEUTRAL",   1.0),
    ("mean_reversion", "TRENDING",  0.5),
    ("vwap_reclaim_long", "MR_STRONG", 1.3),
    # Momentum family
    ("momentum_continuation", "TRENDING",  1.2),
    ("momentum_continuation", "MR_STRONG", 0.7),
    ("momentum_continuation", "NEUTRAL",   1.0),
    ("gap_and_go", "TRENDING", 1.2),
    # Breakout family
    ("breakout_scalp", "TRENDING",  1.1),
    ("breakout_scalp", "MR_STRONG", 0.8),
    ("breakout_scalp", "NEUTRAL",   1.0),
    # Unknown family
    ("something_new", "TRENDING",  1.0),
    ("something_new", "MR_STRONG", 1.0),
])
def test_get_mr_multiplier_table(setup, regime, expected_mult):
    from services.mean_reversion_metrics import get_mr_multiplier
    mult, reason = get_mr_multiplier({"regime_tag": regime}, setup)
    assert mult == expected_mult
    assert regime in reason or "no_metrics" in reason


def test_get_mr_multiplier_none_metrics_returns_1():
    from services.mean_reversion_metrics import get_mr_multiplier
    mult, reason = get_mr_multiplier(None, "mean_reversion")
    assert mult == 1.0
    assert "no_metrics" in reason


def test_get_mr_multiplier_missing_regime_defaults_neutral():
    from services.mean_reversion_metrics import get_mr_multiplier
    mult, _r = get_mr_multiplier({}, "mean_reversion")
    assert mult == 1.0  # regime_tag missing → NEUTRAL → 1.0×


def test_get_mr_multiplier_unknown_setup_in_strong_mr_still_1():
    """An unknown setup should produce 1.0× regardless of regime —
    we never want to penalize a setup the lookup table doesn't know."""
    from services.mean_reversion_metrics import get_mr_multiplier
    mult, _r = get_mr_multiplier({"regime_tag": "MR_STRONG"}, "alien_setup")
    assert mult == 1.0


# ── End-to-end compute_mr_metrics with mocked DB ────────────────────


def _bars_from_closes(closes: List[float], *, base_date: str = "2026-02-13") -> List[dict]:
    """Wrap a close-only series into bar docs suitable for the
    `ib_historical_data` mock collection."""
    from datetime import datetime, timedelta
    base = datetime.strptime(base_date, "%Y-%m-%d")
    return [
        {"symbol": "TEST", "bar_size": "5 mins",
         "date": (base + timedelta(minutes=5 * i)).isoformat(),
         "open": c, "high": c + 0.1, "low": c - 0.1, "close": c,
         "volume": 1000}
        for i, c in enumerate(closes)
    ]


class _StubCursor:
    def __init__(self, docs): self._docs = list(docs)
    def sort(self, *_args, **_kwargs):
        self._docs.sort(key=lambda d: d.get("date") or "", reverse=True)
        return self
    def limit(self, n):
        self._docs = self._docs[:n]
        return self
    def __iter__(self): return iter(self._docs)


class _StubColl:
    def __init__(self, docs): self._docs = list(docs)
    def find(self, _q, _p=None): return _StubCursor(self._docs)
    def find_one(self, _q, _p=None): return None
    def update_one(self, *_a, **_kw): return None


class _StubDB:
    def __init__(self, bars): self.ib_historical_data = _StubColl(bars)
    def __getitem__(self, name):
        # `mean_reversion_metrics` collection accessor in the cache path
        return _StubColl([])


def test_compute_mr_metrics_with_mr_series_yields_mr_regime():
    from services.mean_reversion_metrics import compute_mr_metrics
    closes = _mean_reverting(n=500, theta=0.20)
    db = _StubDB(_bars_from_closes(closes))
    out = compute_mr_metrics(db, "TEST", bar_size="5 mins", use_cache=False)
    assert out["symbol"] == "TEST"
    assert out["n_bars"] == 500
    assert out["hurst"] is not None and out["hurst"] < 0.45
    assert out["half_life_bars"] is not None
    assert out["regime_tag"] in ("MR_STRONG", "MR_WEAK")


def test_compute_mr_metrics_with_trend_yields_trending_regime():
    from services.mean_reversion_metrics import compute_mr_metrics
    closes = _trending(n=500, persistence=0.5)
    db = _StubDB(_bars_from_closes(closes))
    out = compute_mr_metrics(db, "TEST", bar_size="5 mins", use_cache=False)
    assert out["n_bars"] == 500
    assert out["hurst"] is not None and out["hurst"] > 0.55
    assert out["regime_tag"] == "TRENDING"
    # Trending → AR(1) β ≥ 0 → no finite MR half-life.
    assert out["half_life_bars"] is None


def test_compute_mr_metrics_empty_db_returns_no_data_reason():
    from services.mean_reversion_metrics import compute_mr_metrics
    db = _StubDB([])
    out = compute_mr_metrics(db, "TEST", use_cache=False)
    assert out["n_bars"] == 0
    assert out["reason"] == "no_bars_in_history"


def test_compute_mr_metrics_no_db_returns_no_db_reason():
    from services.mean_reversion_metrics import compute_mr_metrics
    out = compute_mr_metrics(None, "TEST", use_cache=False)
    assert out["reason"] == "no_db"
