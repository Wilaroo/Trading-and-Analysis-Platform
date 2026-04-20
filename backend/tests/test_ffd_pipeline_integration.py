"""
Phase 2B — End-to-end integration tests for FFD feature augmentation.

Verifies that with TB_USE_FFD_FEATURES=1:
- `_extract_symbol_worker` (timeseries_gbm) returns feat_matrix with +5 cols
- `_extract_setup_long_worker` and `_extract_setup_short_worker`
  (training_pipeline) produce matrices sized n_base+5 + n_setup
- Combining FFD + CUSUM flags does not crash and still returns 3-class targets

Run:
    PYTHONPATH=backend python -m pytest backend/tests/test_ffd_pipeline_integration.py -v
"""
import os
import numpy as np
import pytest


def _synthetic_bars(n: int = 600, seed: int = 42):
    """Generate a synthetic OHLCV bar series sufficient for lookback=50 + horizon."""
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    highs = closes + np.abs(rng.normal(0.3, 0.2, n))
    lows = closes - np.abs(rng.normal(0.3, 0.2, n))
    opens = closes + rng.normal(0, 0.1, n)
    volumes = rng.integers(100_000, 1_000_000, n).astype(float)
    bars = []
    for i in range(n):
        bars.append({
            "open": float(opens[i]),
            "high": float(max(highs[i], closes[i], opens[i])),
            "low": float(min(lows[i], closes[i], opens[i])),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "date": f"2026-03-{(i % 28) + 1:02d}",
        })
    return bars


@pytest.fixture
def bars():
    return _synthetic_bars()


@pytest.fixture
def ffd_on(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")


@pytest.fixture
def ffd_off(monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "0")


# ─── Baseline shape without FFD ──────────────────────────────────────

def test_symbol_worker_baseline_cols_without_ffd(bars, ffd_off):
    from services.ai_modules.timeseries_gbm import _extract_symbol_worker

    out = _extract_symbol_worker(("TEST", bars, 50, 10))
    assert out is not None
    feat, tgt, ivals = out
    # Baseline is 46 features
    assert feat.shape[1] == 46
    assert feat.shape[0] == len(tgt)
    assert ivals.shape == (len(tgt), 2)
    # 3-class labels
    assert set(np.unique(tgt)).issubset({0, 1, 2})


# ─── FFD-enabled shapes ──────────────────────────────────────────────

def test_symbol_worker_adds_five_ffd_cols(bars, ffd_on):
    from services.ai_modules.timeseries_gbm import _extract_symbol_worker

    out = _extract_symbol_worker(("TEST", bars, 50, 10))
    assert out is not None
    feat, tgt, ivals = out
    # FFD appends 5 features → 46 + 5 = 51
    assert feat.shape[1] == 51, f"expected 51 cols, got {feat.shape[1]}"
    assert feat.shape[0] == len(tgt)
    assert np.isfinite(feat).all(), "FFD cols should be finite (nan_to_num)"


def test_setup_long_worker_with_ffd(bars, ffd_on):
    from services.ai_modules.training_pipeline import _extract_setup_long_worker
    from services.ai_modules.setup_features import get_setup_feature_names

    setup_type = "breakout"
    fh = 10
    # legacy 3-tuple path (noise_thr ignored)
    args = ("TEST", bars, [(setup_type, fh, 0.003)])
    results = _extract_setup_long_worker(args)
    assert results is not None, "worker returned None"
    assert (setup_type, fh) in results, f"missing setup result: {results.keys()}"

    X, y = results[(setup_type, fh)]
    n_setup = len(get_setup_feature_names(setup_type))
    expected_cols = 46 + 5 + n_setup
    assert X.shape[1] == expected_cols, \
        f"expected {expected_cols} cols (46 base + 5 FFD + {n_setup} setup), got {X.shape[1]}"
    assert X.shape[0] == len(y)
    assert set(np.unique(y.astype(int))).issubset({0, 1, 2})


def test_setup_short_worker_with_ffd(bars, ffd_on):
    from services.ai_modules.training_pipeline import _extract_setup_short_worker
    from services.ai_modules.short_setup_features import get_short_setup_feature_names

    setup_type = "short_breakdown"
    fh = 10
    args = ("TEST", bars, [(setup_type, fh, 0.003)])
    results = _extract_setup_short_worker(args)
    assert results is not None
    assert (setup_type, fh) in results

    X, y = results[(setup_type, fh)]
    n_short = len(get_short_setup_feature_names(setup_type))
    expected_cols = 46 + 5 + n_short
    assert X.shape[1] == expected_cols, \
        f"expected {expected_cols} cols, got {X.shape[1]}"
    assert X.shape[0] == len(y)


# ─── All flags combined (CUSUM + FFD + triple-barrier) ───────────────

def test_symbol_worker_all_flags_on(bars, monkeypatch):
    """Smoke test: CUSUM + FFD together must not crash and must keep shape invariants."""
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    monkeypatch.setenv("TB_USE_CUSUM", "1")
    from services.ai_modules.timeseries_gbm import _extract_symbol_worker

    out = _extract_symbol_worker(("TEST", bars, 50, 10, 2.0, 1.0, 14))
    assert out is not None
    feat, tgt, ivals = out
    assert feat.shape[1] == 51  # 46 base + 5 FFD
    assert feat.shape[0] == len(tgt) == len(ivals)
    # Triple-barrier 3-class
    assert set(np.unique(tgt)).issubset({0, 1, 2})
    # Event intervals should be valid [entry, exit] with exit > entry
    assert (ivals[:, 1] >= ivals[:, 0]).all()


def test_setup_long_worker_all_flags_on(bars, monkeypatch):
    monkeypatch.setenv("TB_USE_FFD_FEATURES", "1")
    monkeypatch.setenv("TB_USE_CUSUM", "1")
    from services.ai_modules.training_pipeline import _extract_setup_long_worker
    from services.ai_modules.setup_features import get_setup_feature_names

    # 6-tuple path with per-setup PT/SL/ATR
    args = ("TEST", bars, [("breakout", 10, 0.003, 2.0, 1.0, 14)])
    results = _extract_setup_long_worker(args)
    assert results is not None and ("breakout", 10) in results
    X, y = results[("breakout", 10)]
    n_setup = len(get_setup_feature_names("breakout"))
    assert X.shape[1] == 46 + 5 + n_setup
    assert len(y) == X.shape[0] > 0
